"""Browser-session store for the Steel pool.

The store is the durable browser-session entity. It is independent of the
Steel API containers and the Steel CLI. The MCP server is its only reader and
writer. The session name is the stable handle and the access key.

The record keeps cookies, localStorage, sessionStorage, and indexedDB.
The Steel API currently restores cookies and localStorage through
``sessionContext``. The other two fields are evidence only.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

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
    return datetime.now(timezone.utc).isoformat()


def validate_name(name: str) -> str:
    """Validate a browser-session name and return it unchanged."""
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise InvalidSessionName(
            "browser session names must start with a letter or number and "
            "contain only letters, numbers, hyphens, and underscores"
        )
    return name


def _mapping(value: Any, field_name: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CorruptSessionRecord(f"{field_name} is not an object")
    return dict(value)


def _cookies(value: Any) -> list[dict]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise CorruptSessionRecord("cookies is not a list")
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            raise CorruptSessionRecord("a cookie is not an object")
        result.append(dict(item))
    return result


@dataclass(frozen=True, repr=False)
class BrowserSessionRecord:
    """One durable browser-session record."""

    name: str
    account: str | None = None
    cookies: list[dict[str, Any]] = field(default_factory=list)
    local_storage: dict[str, dict[str, Any]] = field(default_factory=dict)
    session_storage: dict[str, dict[str, Any]] = field(default_factory=dict)
    indexed_db: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

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
        """
        return {
            "cookies": [dict(cookie) for cookie in self.cookies],
            "localStorage": {
                origin: dict(values)
                for origin, values in self.local_storage.items()
            },
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
        """Build a record from an API or SDK session context."""
        if not isinstance(context, Mapping):
            raise CorruptSessionRecord("session context is not an object")
        cookies = context.get("cookies")
        local = context.get("localStorage", context.get("local_storage"))
        session = context.get("sessionStorage", context.get("session_storage"))
        indexed = context.get("indexedDB", context.get("indexed_db"))
        created = created_at or _now()
        return cls(
            name=validate_name(name),
            account=account,
            cookies=_cookies(cookies),
            local_storage=_mapping(local, "localStorage"),
            session_storage=_mapping(session, "sessionStorage"),
            indexed_db=_mapping(indexed, "indexedDB"),
            created_at=created,
            updated_at=updated_at or created,
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "account": self.account,
            "cookies": self.cookies,
            "localStorage": self.local_storage,
            "sessionStorage": self.session_storage,
            "indexedDB": self.indexed_db,
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
        account = data.get("account")
        if account is not None and not isinstance(account, str):
            raise CorruptSessionRecord("account is not a string")
        created = data.get("createdAt", data.get("created_at"))
        updated = data.get("updatedAt", data.get("updated_at"))
        if created is not None and not isinstance(created, str):
            raise CorruptSessionRecord("createdAt is not a string")
        if updated is not None and not isinstance(updated, str):
            raise CorruptSessionRecord("updatedAt is not a string")
        created = created or _now()
        return cls(
            name=validate_name(name),
            account=account,
            cookies=_cookies(data.get("cookies")),
            local_storage=_mapping(
                data.get("localStorage", data.get("local_storage")),
                "localStorage",
            ),
            session_storage=_mapping(
                data.get("sessionStorage", data.get("session_storage")),
                "sessionStorage",
            ),
            indexed_db=_mapping(
                data.get("indexedDB", data.get("indexed_db")),
                "indexedDB",
            ),
            created_at=created,
            updated_at=updated or created,
        )


class SessionStore:
    """An owner-only, atomically written directory of session records."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)

    def path_for(self, name: str) -> Path:
        return self.root / f"{validate_name(name)}.json"

    def load(self, name: str) -> BrowserSessionRecord | None:
        path = self.path_for(name)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise SessionStoreError(f"could not read session {name!r}") from exc
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
        record = BrowserSessionRecord.from_dict(data)
        if record.name != name:
            raise CorruptSessionRecord(
                f"session record {name!r} carries the name {record.name!r}"
            )
        return record

    def save(self, record: BrowserSessionRecord) -> BrowserSessionRecord:
        if not isinstance(record, BrowserSessionRecord):
            raise TypeError("record must be a BrowserSessionRecord")
        validate_name(record.name)
        saved = replace(record, updated_at=_now())
        self._atomic_write(self.path_for(saved.name), saved.to_dict())
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
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=self.root
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise
