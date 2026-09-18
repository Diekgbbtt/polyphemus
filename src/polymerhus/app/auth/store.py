"""The per-project shared auth bucket store (#220, T2).

Topology (D220-3), one bucket per project under the app-owned data root
(`app.data_root.DATA_ROOT`, `<repo>/data/` - the same root the skills and
hunting stores write under), lazily created at the first write:

    data/<project_id>/auth/
      credentials.yaml   ({accounts: {<name>: <account record>}})
      overview.yaml      (the operator-owned login-mechanism header, bare map)

Record identity is the account name; file names never encode it. Reads are
field-arbitrary dotted projections over the full state
(`{"overview": ..., "accounts": ...}`); a missing path or an unreadable file
degrades to a valid empty (warned, fail-open), never a raise. Writes are
single-field set-at-path with merge (siblings untouched), null removing an
optional field; every merged record re-validates through the T1 seam
(`records.validate_account` / `validate_overview`, mirrored never imported
upward per D220-7). Every file write is atomic (temp file in the same dir +
`os.replace`) and serialised per project (a `threading.Lock` per `project_id`
covers every check-then-write and read-modify-write critical section - the
`hunt_store` I2 pattern it repeats).

This module imports no driver and performs no I/O at import (CODING_STANDARD
section 6); the root is the app-owned `DATA_ROOT` (no env var), resolved
through the one layout owner (`app.data_root.project_dir`).
"""
from __future__ import annotations

import copy
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from polymerhus.app.auth.records import (
    AuthInvalidError,
    validate_account,
    validate_overview,
)
from polymerhus.app.data_root import DATA_ROOT, project_dir

logger = logging.getLogger(__name__)

# The store root is the app-owned data root (D220-3), the same root the skills
# and hunting stores write under - no env var, resolved through the one layout
# owner; the bucket is `<data_root>/<project_id>/auth/`. The explicit-root
# constructor is kept for the tests' temp stores (the `hunt_store` precedent).
_BUCKET_NAME = "auth"

_CREDENTIALS_FILE = "credentials.yaml"
_OVERVIEW_FILE = "overview.yaml"

_ORIGINS = frozenset({"operator", "agent"})


class DuplicateAuthError(ValueError):
    """The denoted dedup signal: creating an already-known account name fails
    instead of forking the record - the first writer wins (D220-6, G4); the
    caller reflects, merges, or refreshes. Raised for any origin: an agent
    name may never shadow an operator name."""


class OperatorImmutableError(ValueError):
    """The denoted trust-boundary refusal: an agent-origin write touching
    operator-owned state (an operator-stamped account, the operator overview)
    fails loudly instead of silently no-op-ing."""


class StoreUnavailableError(ValueError):
    """The denoted degraded-store signal: a write that cannot load or persist
    its bucket file (corrupt YAML, I/O failure) fails loudly - never a silent
    corruption, never an overwrite of unreadable state."""


def _utcnow_iso() -> str:
    """Server time as an ISO-8601 UTC string: the one `updated_at` source
    (#223 D223-18). A module-level seam (not inlined `datetime.now`) so tests
    pin recency deterministically by monkeypatching one name."""
    return datetime.now(timezone.utc).isoformat()


def _stamp_recency(record: dict, stamp: str) -> None:
    """Stamp the server-side recency fact (#223 D223-18): drop any
    client-supplied `updated_at` (never trusted) and set the server stamp,
    so no client can forge the selection ordering. The caller owns the stamp
    value - writes stamp `_utcnow_iso()` per record, seeds pass one stamp
    for the whole seed so seeded accounts tie on list position."""
    record.pop("updated_at", None)
    record["updated_at"] = stamp


# Per-project write serialisation (D220-6, the `hunt_store` I2 pattern): a
# per-project lock covers the whole check-then-write and read-modify-write
# critical section, so concurrent writers converge instead of forking records.
_PROJECT_LOCKS: dict[str, threading.Lock] = {}
_PROJECT_LOCKS_GUARD = threading.Lock()


def _lock_for(project_id: str) -> threading.Lock:
    """The per-project lock, created once (the registry itself is guarded
    against concurrent creation)."""
    with _PROJECT_LOCKS_GUARD:
        lock = _PROJECT_LOCKS.get(project_id)
        if lock is None:
            lock = threading.Lock()
            _PROJECT_LOCKS[project_id] = lock
        return lock


class AuthStore:
    """The per-project auth bucket store (D220-3): one small interface over
    the two-file bucket. The agent tool (T3) and the operator seed face (T4)
    are thin adapters over this seam; no caller reaches past it."""

    def __init__(self, root_dir: str | Path | None = None):
        """Rooted under `root_dir` (default: the app-owned `DATA_ROOT`,
        `<repo>/data/`)."""
        self._root = Path(root_dir) if root_dir is not None else DATA_ROOT

    # --- path helpers ----------------------------------------------------------

    def _bucket_dir(self, project_id: str) -> Path:
        return project_dir(project_id, _BUCKET_NAME, root=self._root)

    def _credentials_file(self, project_id: str) -> Path:
        return self._bucket_dir(project_id) / _CREDENTIALS_FILE

    def _overview_file(self, project_id: str) -> Path:
        return self._bucket_dir(project_id) / _OVERVIEW_FILE

    # --- atomic write primitive (the `hunt_store` I1 pattern) -------------------

    @staticmethod
    def _dump_yaml_atomic(path: Path, body) -> None:
        """Write `body` as YAML atomically: dump to a temp file in the SAME
        directory, then `os.replace` onto the target, so every file on disk
        always parses and a crash mid-dump never leaves a partial target."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                yaml.safe_dump(body, fh, sort_keys=False)
            os.replace(tmp, path)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

    # --- reads: full state or dotted projection, always fail-open ---------------

    def _load_file(self, path: Path) -> dict:
        """One bucket file's mapping; a missing file, an unreadable file, or
        a non-mapping body degrades to {} (warned, fail-open - O4)."""
        if not path.exists():
            return {}
        try:
            body = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("auth store: unreadable bucket file %s (%s)", path, exc)
            return {}
        if not isinstance(body, dict):
            logger.warning("auth store: non-mapping bucket file %s degrades to empty", path)
            return {}
        return body

    def _full_state(self, project_id: str) -> dict:
        """The whole bucket state: `{"overview": ..., "accounts": ...}`."""
        overview = self._load_file(self._overview_file(project_id))
        credentials = self._load_file(self._credentials_file(project_id))
        accounts = credentials.get("accounts")
        return {
            "overview": overview,
            "accounts": accounts if isinstance(accounts, dict) else {},
        }

    @staticmethod
    def _project(state: dict, path: str) -> Any:
        """The dotted-path projection of `state`: the addressed field value
        (a mapping, a scalar leaf, or the full state) - a missing path is a
        valid empty ({}), never an error."""
        if not path:
            return copy.deepcopy(state)
        current = state
        for segment in path.split("."):
            if not isinstance(current, dict) or segment not in current:
                return {}
            current = current[segment]
        return copy.deepcopy(current)

    def read(self, project_id: str, path: str = "") -> Any:
        """The full state for an empty path, the addressed field value
        otherwise (mapping or scalar leaf); a missing path or an unreadable
        file is a valid empty, never a raise."""
        with _lock_for(project_id):
            return self._project(self._full_state(project_id), path)

    # --- writes: single-field set-at-path with merge ----------------------------

    def _ensure_bucket(self, project_id: str) -> None:
        """Lazily create the bucket with exactly the two spec files: the
        touched file lands its content via the caller, the untouched side
        lands its empty default - so the first write always leaves both."""
        credentials = self._credentials_file(project_id)
        overview = self._overview_file(project_id)
        if not credentials.exists():
            self._dump_yaml_atomic(credentials, {"accounts": {}})
        if not overview.exists():
            self._dump_yaml_atomic(overview, {})

    def write(self, project_id: str, path: str, value, *, origin: str = "agent"):
        """Upsert a single field with merge (sibling fields untouched); a null
        value removes an optional field. A write to an account root
        (`accounts.<name>`) with a record mapping is a CREATE: the name is
        novelty-gated (`DuplicateAuthError` when known, any origin) and the
        origin is stamped server-side. Deeper writes MERGE into the existing
        record (creating the parent account stamped with the call origin when
        absent) and refuse `OperatorImmutableError` when the stored record is
        operator-stamped and the call origin is agent; the operator-owned
        overview likewise refuses agent-origin writes. The merged record
        re-validates through the T1 seam (shape violations refuse naming the
        field); an unreadable bucket file refuses `StoreUnavailableError`
        rather than overwriting blind. Every account write also refreshes the
        server-stamped `updated_at` recency fact (D223-18), overwriting any
        client-supplied value - a forged recency is never trusted. Every file
        write is atomic."""
        if not path:
            raise AuthInvalidError("path", "must name a single field to write")
        if origin not in _ORIGINS:
            raise AuthInvalidError("origin", 'must be "operator" or "agent"')
        segments = path.split(".")
        with _lock_for(project_id):
            self._ensure_bucket(project_id)
            if segments[0] == "overview":
                if origin == "agent":
                    raise OperatorImmutableError(
                        "operator_immutable: the overview is operator-owned; "
                        "an agent write is refused at the trust boundary")
                overview = self._load_file_strict(self._overview_file(project_id))
                self._assign(overview, segments[1:], value, "overview")
                self._dump_yaml_atomic(
                    self._overview_file(project_id), validate_overview(overview))
            elif segments[0] == "accounts" and len(segments) >= 2:
                name, field = segments[1], f"accounts.{segments[1]}"
                credentials = self._load_file_strict(self._credentials_file(project_id))
                accounts = credentials.get("accounts")
                if not isinstance(accounts, dict):
                    accounts = {}
                stored = accounts.get(name)
                if len(segments) == 2 and value is not None:
                    # CREATE: the account root with a record mapping. A known
                    # name fails with the dedup signal instead of forking.
                    if not isinstance(value, dict):
                        raise AuthInvalidError(field, "must be an object to create")
                    if isinstance(stored, dict):
                        raise DuplicateAuthError(
                            f"duplicate_auth: an account named {name!r} already "
                            "exists; merge into it or refresh it instead of "
                            "creating a second record")
                    record = copy.deepcopy(value)
                    record["origin"] = origin
                    # CREATE stamps recency alongside origin (D223-18).
                    _stamp_recency(record, _utcnow_iso())
                    accounts[name] = validate_account(record)
                    self._dump_yaml_atomic(
                        self._credentials_file(project_id), {"accounts": accounts})
                    return
                if isinstance(stored, dict):
                    if stored.get("origin") == "operator" and origin == "agent":
                        raise OperatorImmutableError(
                            f"operator_immutable: account {name!r} is "
                            "operator-owned; an agent write is refused at the "
                            "trust boundary")
                    record = stored
                    stamped = stored.get("origin")
                else:
                    record, stamped = {}, None
                if len(segments) == 2 and value is None:
                    # Null at the account root removes the caller's own
                    # record; an absent name is a no-op success.
                    if isinstance(stored, dict):
                        del accounts[name]
                        self._dump_yaml_atomic(
                            self._credentials_file(project_id), {"accounts": accounts})
                    return
                self._assign(record, segments[2:], value, field)
                # CODING_STANDARD 9 skips YAML (no graph props): `origin` is
                # stamped on the mapping server-side - stored stamp wins, else
                # the call origin, so a forged origin inside `value` never lands.
                record["origin"] = stamped if stamped in _ORIGINS else origin
                # Every account write refreshes recency (D223-18 - a deep
                # write to `accounts.<name>.updated_at` included).
                _stamp_recency(record, _utcnow_iso())
                accounts[name] = validate_account(record)
                self._dump_yaml_atomic(
                    self._credentials_file(project_id), {"accounts": accounts})
            else:
                raise AuthInvalidError(
                    segments[0], "must address `overview` or `accounts.<name>`")

    def replace_operator_state(
        self,
        project_id: str,
        *,
        overview: dict | None = None,
        accounts: dict | None = None,
    ) -> None:
        """The operator-seed primitive (the T4 face programs against this):
        each PRESENT section replaces the operator-owned state wholesale
        (value-object replace, never a merge); ABSENT sections are untouched.
        Seeded accounts are stamped operator server-side; agent-stamped
        accounts are never modified or removed. No conflict path: replace,
        never 409. Both sections validate through the T1 seam BEFORE anything
        lands, so a bad seed leaves the bucket exactly as it was."""
        with _lock_for(project_id):
            self._ensure_bucket(project_id)
            validated_overview = (
                validate_overview(overview) if overview is not None else None)
            merged = None
            if accounts is not None:
                if not isinstance(accounts, dict):
                    raise AuthInvalidError("accounts", "must be an object")
                credentials = self._load_file_strict(
                    self._credentials_file(project_id))
                current = credentials.get("accounts")
                if not isinstance(current, dict):
                    current = {}
                seeded = {}
                # Seeds stamp recency server-side too - one stamp for the whole
                # seed, so seeded accounts tie and list position (newest last)
                # decides their relative order.
                seed_stamp = _utcnow_iso()
                for name, record in accounts.items():
                    if not isinstance(record, dict):
                        raise AuthInvalidError(
                            f"accounts.{name}", "must be an object to seed")
                    entry = copy.deepcopy(record)
                    entry["origin"] = "operator"
                    _stamp_recency(entry, seed_stamp)
                    seeded[name] = validate_account(entry)
                kept = {n: r for n, r in current.items()
                        if isinstance(r, dict) and r.get("origin") == "agent"}
                for name in list(seeded):
                    # A seeded operator name colliding with a live agent record
                    # keeps the agent record (a seed never modifies or removes
                    # agent state); the collision warns instead of forking.
                    if name in kept:
                        logger.warning(
                            "auth store: seed for %s keeps the live agent "
                            "record; the operator entry is dropped", name)
                        del seeded[name]
                merged = {**seeded, **kept}
            if validated_overview is not None:
                self._dump_yaml_atomic(
                    self._overview_file(project_id), validated_overview)
            if merged is not None:
                self._dump_yaml_atomic(
                    self._credentials_file(project_id), {"accounts": merged})

    def _load_file_strict(self, path: Path) -> dict:
        """One bucket file's mapping for a WRITE path: a missing file is {},
        but an unreadable or non-mapping file refuses `StoreUnavailableError`
        - overwriting state that cannot be read would silently corrupt it."""
        if not path.exists():
            return {}
        try:
            body = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise StoreUnavailableError(
                f"store_unavailable: unreadable bucket file {path} ({exc})") from exc
        if not isinstance(body, dict):
            raise StoreUnavailableError(
                f"store_unavailable: non-mapping bucket file {path} refuses a merge")
        return body

    @staticmethod
    def _assign(container: dict, segments: list[str], value, field: str) -> None:
        """Set-at-path into `container`: navigate (creating intermediate
        mappings), set the leaf, or delete it for a null value."""
        for segment in segments[:-1]:
            child = container.get(segment)
            if child is None:
                child = {}
                container[segment] = child
            if not isinstance(child, dict):
                raise AuthInvalidError(
                    field, f"cannot address `{segment}` inside a non-mapping")
            container = child
        leaf = segments[-1] if segments else None
        if leaf is None:
            if not isinstance(value, dict):
                raise AuthInvalidError(field, "must be an object to merge")
            for key, entry in value.items():
                if entry is None:
                    container.pop(key, None)
                else:
                    container[key] = copy.deepcopy(entry)
        elif value is None:
            container.pop(leaf, None)
        else:
            container[leaf] = copy.deepcopy(value)
