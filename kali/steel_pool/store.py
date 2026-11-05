"""Browser-session store for the Steel pool.

The store is the durable browser-session entity. It is independent of the
Steel API containers and the Steel CLI. The MCP server is its only reader and
writer. The session name is the stable handle and the access key.

The record keeps cookies, localStorage, sessionStorage, and indexedDB.
The Steel API currently restores cookies and localStorage through
``sessionContext``. The other two fields are evidence only.

Invariants enforced here:

* Every constructed record is valid, JSON-serialisable, and readable back.
  The store never writes a record it would reject on load.
* Writes are atomic: a sibling temp file is flushed, ``fsync``-ed, renamed
  over the target, and the parent directory is ``fsync``-ed.
* Reads do not follow symlinks.
* The store root is owner-only. A pre-existing directory with group or other
  permission bits fails loud instead of being silently tightened.

The module is stdlib-only and performs no I/O at import, so the Kali image can
import it beside ``mcp_server.py``.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_NAME_RULE = (
    "browser session names must start with a letter or number and contain "
    "only letters, numbers, hyphens, and underscores (1-128 characters)"
)
_ENV_VAR = "STEEL_SESSION_STORE"

__all__ = [
    "BrowserSessionRecord",
    "CorruptSessionRecord",
    "InvalidSessionName",
    "SessionStore",
    "SessionStoreError",
    "validate_name",
]


class SessionStoreError(RuntimeError):
    """A browser-session store operation failed."""


class InvalidSessionName(SessionStoreError):
    """The session name is not a safe store key."""


class CorruptSessionRecord(SessionStoreError):
    """The stored record is missing, malformed, or inconsistent."""


def _now() -> str:
    """Server time as an ISO-8601 UTC string.

    A module-level seam (not inlined ``datetime.now``) so tests pin recency
    deterministically by monkeypatching one name.
    """
    return datetime.now(timezone.utc).isoformat()


def validate_name(name: str) -> str:
    """Validate a browser-session name and return it unchanged."""
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise InvalidSessionName(_NAME_RULE)
    return name


def _timestamp(value: object, field_name: str) -> str:
    """Require a timezone-aware ISO-8601 timestamp and return it unchanged."""
    if not isinstance(value, str) or not value:
        raise CorruptSessionRecord(f"{field_name} is not an ISO-8601 string")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CorruptSessionRecord(
            f"{field_name} is not an ISO-8601 string"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CorruptSessionRecord(f"{field_name} has no UTC offset")
    return value


def _json_copy(value: object, field_name: str) -> Any:
    """Deep-copy a JSON value, rejecting anything JSON cannot round-trip."""
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        return json.loads(encoded)
    except (TypeError, ValueError, RecursionError) as exc:
        raise CorruptSessionRecord(
            f"{field_name} is not JSON-serialisable"
        ) from exc


def _check_string_keys(value: object, field_name: str) -> None:
    """Reject non-string object keys at any depth.

    ``json.dumps`` silently coerces integer keys to strings, which would make
    a stored record differ from the record that was saved. Shared references
    are allowed; a true cycle is rejected because it cannot be serialised.
    """
    active: set[int] = set()
    stack: list[tuple[object, bool]] = [(value, False)]
    while stack:
        current, leaving = stack.pop()
        if isinstance(current, (Mapping, list, tuple)):
            marker = id(current)
            if leaving:
                active.discard(marker)
                continue
            if marker in active:
                raise CorruptSessionRecord(
                    f"{field_name} contains a cycle"
                )
            active.add(marker)
            stack.append((current, True))
            if isinstance(current, Mapping):
                for key, item in current.items():
                    if not isinstance(key, str):
                        raise CorruptSessionRecord(
                            f"{field_name} has a non-string key"
                        )
                    stack.append((item, False))
            else:
                for item in current:
                    stack.append((item, False))


def _mapping(value: object, field_name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CorruptSessionRecord(f"{field_name} is not an object")
    _check_string_keys(value, field_name)
    return _json_copy(dict(value), field_name)


def _cookies(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CorruptSessionRecord("cookies is not a list")
    plain: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise CorruptSessionRecord("a cookie is not an object")
        _check_string_keys(item, "a cookie")
        plain.append(dict(item))
    return _json_copy(plain, "cookies")


@dataclass(frozen=True, repr=False)
class BrowserSessionRecord:
    """One durable browser-session record.

    Construction is the validation point: every field is normalised to a
    JSON-native value and copied, so the record cannot alias a caller's
    mutable state and cannot hold a value the store could not read back.
    """

    name: str
    account: str | None = None
    cookies: list[dict[str, Any]] = field(default_factory=list)
    local_storage: dict[str, dict[str, Any]] = field(default_factory=dict)
    session_storage: dict[str, dict[str, Any]] = field(default_factory=dict)
    indexed_db: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", validate_name(self.name))
        if self.account is not None and not isinstance(self.account, str):
            raise CorruptSessionRecord("account is not a string")
        object.__setattr__(self, "cookies", _cookies(self.cookies))
        object.__setattr__(
            self, "local_storage", _mapping(self.local_storage, "localStorage")
        )
        object.__setattr__(
            self, "session_storage", _mapping(self.session_storage, "sessionStorage")
        )
        object.__setattr__(
            self, "indexed_db", _mapping(self.indexed_db, "indexedDB")
        )
        created = _timestamp(self.created_at, "createdAt")
        updated = self.updated_at if self.updated_at is not None else created
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", _timestamp(updated, "updatedAt"))

    def __repr__(self) -> str:
        return (
            "BrowserSessionRecord("
            f"name={self.name!r}, account={self.account!r}, "
            f"cookies=<{len(self.cookies)} redacted>, "
            f"localStorage=<{len(self.local_storage)} origins>, "
            f"sessionStorage=<{len(self.session_storage)} origins>, "
            f"indexedDB=<{len(self.indexed_db)} databases>, "
            f"created_at={self.created_at!r}, updated_at={self.updated_at!r})"
        )

    def to_session_context(self) -> dict:
        """Return the create-time sessionContext.

        Only cookies and localStorage are restored by the current API.
        The returned containers are copies.
        """
        return {
            "cookies": _json_copy(self.cookies, "cookies"),
            "localStorage": _json_copy(self.local_storage, "localStorage"),
        }

    @classmethod
    def from_context(
        cls,
        name: str,
        context: Mapping[str, Any],
        *,
        account: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> "BrowserSessionRecord":
        """Build a record from an API or SDK session context.

        Both spellings are accepted: the HTTP form (``localStorage``) and the
        SDK form (``local_storage``). ``to_session_context`` emits the HTTP
        form only.
        """
        if not isinstance(context, Mapping):
            raise CorruptSessionRecord("session context is not an object")
        return cls(
            name=name,
            account=account,
            cookies=context.get("cookies"),
            local_storage=context.get("localStorage", context.get("local_storage")),
            session_storage=context.get(
                "sessionStorage", context.get("session_storage")
            ),
            indexed_db=context.get("indexedDB", context.get("indexed_db")),
            created_at=created_at if created_at is not None else _now(),
            updated_at=updated_at,
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "account": self.account,
            "cookies": _json_copy(self.cookies, "cookies"),
            "localStorage": _json_copy(self.local_storage, "localStorage"),
            "sessionStorage": _json_copy(self.session_storage, "sessionStorage"),
            "indexedDB": _json_copy(self.indexed_db, "indexedDB"),
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BrowserSessionRecord":
        if not isinstance(data, Mapping):
            raise CorruptSessionRecord("session record is not an object")
        name = data.get("name")
        if not isinstance(name, str):
            raise CorruptSessionRecord("session record has no name")
        created = data.get("createdAt", data.get("created_at"))
        if created is None:
            created = _now()
        return cls(
            name=name,
            account=data.get("account"),
            cookies=data.get("cookies"),
            local_storage=data.get("localStorage", data.get("local_storage")),
            session_storage=data.get(
                "sessionStorage", data.get("session_storage")
            ),
            indexed_db=data.get("indexedDB", data.get("indexed_db")),
            created_at=created,
            updated_at=data.get("updatedAt", data.get("updated_at")),
        )


def _fsync_dir(directory: Path) -> None:
    """Best-effort ``fsync`` of a directory so a rename's entry is durable.

    On POSIX a rename is not durable across a power loss without an ``fsync``
    on the parent directory (the ext4 zero-length case). The app-owned
    ``polymerhus.app.atomic_write`` states the same idiom, but the Kali image
    is stdlib-only and cannot import ``src``, so the primitive is carried
    here rather than shared.
    """
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


class SessionStore:
    """An owner-only, atomically written directory of session records."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self._prepare_root()

    def _prepare_root(self) -> None:
        try:
            existed = self.root.exists()
            if self.root.is_symlink():
                raise SessionStoreError(
                    f"browser-session store root {self.root} must not be a symlink"
                )
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            flags = (
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            descriptor = os.open(self.root, flags)
            try:
                info = os.fstat(descriptor)
            finally:
                os.close(descriptor)
            if not stat.S_ISDIR(info.st_mode):
                raise SessionStoreError(
                    f"browser-session store root {self.root} is not a directory"
                )
            mode = stat.S_IMODE(info.st_mode)
            if existed:
                if mode & 0o077:
                    raise SessionStoreError(
                        f"browser-session store root {self.root} must be "
                        f"owner-only; found mode {oct(mode)}"
                    )
            else:
                os.chmod(self.root, 0o700)
        except OSError as exc:
            raise SessionStoreError(
                f"could not prepare browser-session store root {self.root}"
            ) from exc

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "SessionStore":
        """Build the store from ``STEEL_SESSION_STORE``.

        The deployment owns the volume; the store refuses to guess a path.
        """
        source = os.environ if env is None else env
        root = (source.get(_ENV_VAR) or "").strip()
        if not root:
            raise SessionStoreError(
                f"{_ENV_VAR} is unset; the browser-session store has no root"
            )
        return cls(root)

    def path_for(self, name: str) -> Path:
        return self.root / f"{validate_name(name)}.json"

    def load(self, name: str) -> BrowserSessionRecord | None:
        path = self.path_for(name)
        text = self._read_text(path, name)
        if text is None:
            return None
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise CorruptSessionRecord(
                f"session record {name!r} is not valid JSON"
            ) from exc
        if not isinstance(data, Mapping):
            raise CorruptSessionRecord(
                f"session record {name!r} is not an object"
            )
        try:
            record = BrowserSessionRecord.from_dict(data)
        except InvalidSessionName as exc:
            raise CorruptSessionRecord(
                f"session record {name!r} carries an invalid name"
            ) from exc
        if record.name != name:
            raise CorruptSessionRecord(
                f"session record {name!r} carries the name {record.name!r}"
            )
        return record

    def _read_text(self, path: Path, name: str) -> str | None:
        if path.is_symlink():
            raise CorruptSessionRecord(
                f"session record {name!r} is a symlink"
            )
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            return None
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise CorruptSessionRecord(
                    f"session record {name!r} is a symlink"
                ) from exc
            raise SessionStoreError(
                f"could not read session {name!r}"
            ) from exc
        try:
            handle = os.fdopen(descriptor, "r", encoding="utf-8")
        except BaseException:
            os.close(descriptor)
            raise
        try:
            with handle:
                return handle.read()
        except UnicodeDecodeError as exc:
            raise CorruptSessionRecord(
                f"session record {name!r} is not valid UTF-8"
            ) from exc
        except OSError as exc:
            raise SessionStoreError(
                f"could not read session {name!r}"
            ) from exc

    def save(self, record: BrowserSessionRecord) -> BrowserSessionRecord:
        if not isinstance(record, BrowserSessionRecord):
            raise TypeError("record must be a BrowserSessionRecord")
        saved = replace(record, updated_at=_now())
        path = self.path_for(saved.name)
        try:
            self._atomic_write(path, saved.to_dict())
        except SessionStoreError:
            raise
        except OSError as exc:
            raise SessionStoreError(
                f"could not write session {saved.name!r}"
            ) from exc
        return saved

    def delete(self, name: str) -> bool:
        path = self.path_for(name)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise SessionStoreError(f"could not delete session {name!r}") from exc

    def _atomic_write(self, path: Path, data: dict) -> None:
        try:
            payload = (
                json.dumps(
                    data,
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise CorruptSessionRecord(
                f"session record {path.stem!r} is not JSON-serialisable"
            ) from exc
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=self.root
        )
        try:
            try:
                handle = os.fdopen(descriptor, "wb")
            except BaseException:
                os.close(descriptor)
                raise
            with handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            _fsync_dir(self.root)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
