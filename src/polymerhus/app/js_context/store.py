"""Sole writer and bounded reader for published client-side JS context."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import re
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import yaml

from polymerhus.app.atomic_write import write_text_atomic
from polymerhus.app.data_root import project_dir, validate_path_component
from polymerhus.app.js_context.records import (
    MAX_DOCUMENT_BYTES,
    JsContextInvalidError,
    context_id_for,
    document_identity,
    validate_document,
)

_BUCKET = "js-client-side"
_CURRENT = "current.json"
_SCHEMA_VERSION = 1
_DEFAULT_LIMIT = 25
_MAX_LIMIT = 100
_MAX_LIST_SCAN = 1000
_MAX_CURRENT_BYTES = 4096
_CONTEXT_ID = re.compile(r"^jsctx_[0-9a-f]{40}$")
_SECTIONS = frozenset({"metadata", "context", "behaviors", "evidence"})
_CURRENT_KEYS = frozenset(
    {
        "schema_version",
        "project_id",
        "context_id",
        "run_id",
        "document_file",
        "document_sha256",
        "published_at_ns",
    }
)

_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


class JsContextStoreError(ValueError):
    """A technical publication failure with a stable reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def _validate_context_id(value: str) -> str:
    validate_path_component(value, "context_id")
    if not _CONTEXT_ID.fullmatch(value):
        raise ValueError("context_id must be a jsctx_<sha256-prefix> identity")
    return value


def _validate_run_id(value: str) -> str:
    return validate_path_component(value, "run_id")


def _bounded_limit(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("limit must be a positive integer")
    return min(value, _MAX_LIMIT)


def _encode_cursor(binding: str, offset: int) -> str:
    body = json.dumps({"offset": offset}, separators=(",", ":")).encode()
    digest = hashlib.sha256(binding.encode() + body).digest()[:8]
    return base64.urlsafe_b64encode(body + digest).decode().rstrip("=")


def _decode_cursor(binding: str, cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        payload = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        body, observed = payload[:-8], payload[-8:]
        expected = hashlib.sha256(binding.encode() + body).digest()[:8]
        value = json.loads(body)
        offset = value.get("offset")
        if (
            observed != expected
            or not isinstance(offset, int)
            or isinstance(offset, bool)
            or offset < 0
        ):
            raise ValueError
        return offset
    except Exception:
        raise ValueError("invalid js context cursor") from None


class JsContextStore:
    """Project-owned publication store with atomic current promotion."""

    def __init__(
        self,
        *,
        root_dir: str | Path | None = None,
        write_text: Callable[[Path, str], None] | None = None,
    ) -> None:
        self._root = Path(root_dir) if root_dir is not None else None
        self._write_text = write_text or write_text_atomic

    def _bucket(self, project_id: str) -> Path:
        path = project_dir(project_id, _BUCKET, root=self._root)
        if path.is_symlink():
            raise JsContextStoreError("unsafe_symlink")
        return path

    def _context_dir(self, project_id: str, context_id: str) -> Path:
        path = self._bucket(project_id) / _validate_context_id(context_id)
        if path.is_symlink():
            raise JsContextStoreError("unsafe_symlink")
        return path

    def _document_path(
        self,
        project_id: str,
        context_id: str,
        run_id: str,
    ) -> Path:
        return self._context_dir(project_id, context_id) / f"{_validate_run_id(run_id)}.yml"

    def _current_path(self, project_id: str, context_id: str) -> Path:
        return self._context_dir(project_id, context_id) / _CURRENT

    @staticmethod
    def _private_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)

    @staticmethod
    def _private_file(path: Path) -> None:
        path.chmod(0o600)

    @contextmanager
    def _locked(self, context_dir: Path):
        self._private_directory(context_dir)
        lock_path = context_dir / ".publish.lock"
        if lock_path.is_symlink():
            raise JsContextStoreError("unsafe_symlink")
        with _lock_for(lock_path):
            with lock_path.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _yaml_text(document: dict) -> str:
        return yaml.safe_dump(
            document,
            sort_keys=False,
            allow_unicode=True,
        )

    def _read_document(
        self,
        path: Path,
        *,
        project_id: str,
        context_id: str,
        expected_run_id: str,
        expected_sha256: str | None = None,
    ) -> tuple[str, dict | None, str | None]:
        if path.is_symlink():
            return "corrupt", None, None
        if not path.is_file():
            return "missing", None, None
        try:
            if path.stat().st_size > MAX_DOCUMENT_BYTES:
                return "corrupt", None, None
            raw = path.read_bytes()
            parsed = yaml.safe_load(raw.decode("utf-8"))
            document = validate_document(parsed)
        except (
            OSError,
            UnicodeError,
            yaml.YAMLError,
            JsContextInvalidError,
        ):
            return "corrupt", None, None
        observed_sha = hashlib.sha256(raw).hexdigest()
        context = document["context"]
        if (
            context["run_id"] != expected_run_id
            or context_id_for(
                project_id=context["project_id"],
                origin=context["origin"],
                auth_ref=context["auth_ref"],
            )
            != context_id
            or context["project_id"] != project_id
        ):
            return "run_mismatch", None, observed_sha
        if expected_sha256 is not None and observed_sha != expected_sha256:
            return "corrupt", None, observed_sha
        return "ok", document, observed_sha

    def _read_current(
        self,
        project_id: str,
        context_id: str,
    ) -> tuple[str, dict | None]:
        path = self._current_path(project_id, context_id)
        if path.is_symlink():
            return "corrupt", None
        if not path.is_file():
            return "missing", None
        try:
            if path.stat().st_size > _MAX_CURRENT_BYTES:
                return "corrupt", None
            pointer = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return "corrupt", None
        if (
            not isinstance(pointer, dict)
            or set(pointer) != _CURRENT_KEYS
            or not isinstance(pointer.get("schema_version"), int)
            or isinstance(pointer.get("schema_version"), bool)
            or pointer.get("schema_version") != _SCHEMA_VERSION
            or pointer.get("project_id") != project_id
            or pointer.get("context_id") != context_id
            or not isinstance(pointer.get("run_id"), str)
            or not isinstance(pointer.get("document_file"), str)
            or not isinstance(pointer.get("document_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", pointer["document_sha256"])
            or not isinstance(pointer.get("published_at_ns"), int)
            or isinstance(pointer.get("published_at_ns"), bool)
        ):
            return "corrupt", None
        if pointer["document_file"] != f"{pointer['run_id']}.yml":
            return "corrupt", None
        try:
            _validate_run_id(pointer["run_id"])
        except ValueError:
            return "corrupt", None
        return "ok", pointer

    @staticmethod
    def _pointer(
        *,
        project_id: str,
        context_id: str,
        run_id: str,
        document_sha256: str,
        published_at_ns: int,
    ) -> dict:
        return {
            "schema_version": _SCHEMA_VERSION,
            "project_id": project_id,
            "context_id": context_id,
            "run_id": run_id,
            "document_file": f"{run_id}.yml",
            "document_sha256": document_sha256,
            "published_at_ns": published_at_ns,
        }

    def _write_pointer(self, path: Path, pointer: dict) -> None:
        text = json.dumps(pointer, sort_keys=True, separators=(",", ":")) + "\n"
        try:
            self._write_text(path, text)
            self._private_file(path)
        except OSError as exc:
            raise JsContextStoreError("current_write_failed") from exc

    def _latest_valid_publication(
        self,
        *,
        project_id: str,
        context_id: str,
        context_dir: Path,
    ) -> tuple[str, dict | None]:
        """Find the newest valid run document when current is absent."""
        latest = None
        for count, path in enumerate(context_dir.glob("*.yml"), start=1):
            if count > _MAX_LIST_SCAN:
                return "limit", None
            if path.is_symlink():
                continue
            try:
                run_id = _validate_run_id(path.stem)
            except ValueError:
                continue
            status, document, document_sha = self._read_document(
                path,
                project_id=project_id,
                context_id=context_id,
                expected_run_id=run_id,
            )
            if status != "ok" or document is None or document_sha is None:
                continue
            try:
                published_at_ns = path.stat().st_mtime_ns
            except OSError:
                continue
            if latest is None or published_at_ns > latest["published_at_ns"]:
                latest = {
                    "run_id": run_id,
                    "document_sha256": document_sha,
                    "published_at_ns": published_at_ns,
                }
        return "ok", latest

    def publish(self, document: dict) -> dict:
        """Validate one document, retain its run file, then promote current."""
        value = validate_document(document)
        context = value["context"]
        project_id = context["project_id"]
        run_id = context["run_id"]
        context_id = context_id_for(
            project_id=project_id,
            origin=context["origin"],
            auth_ref=context["auth_ref"],
        )
        context_dir = self._context_dir(project_id, context_id)
        yaml_path = self._document_path(project_id, context_id, run_id)
        current_path = self._current_path(project_id, context_id)

        with self._locked(context_dir):
            if yaml_path.is_symlink() or current_path.is_symlink():
                raise JsContextStoreError("unsafe_symlink")
            existing = yaml_path.is_file()
            if existing:
                status, stored, document_sha = self._read_document(
                    yaml_path,
                    project_id=project_id,
                    context_id=context_id,
                    expected_run_id=run_id,
                )
                if status != "ok":
                    return {
                        "status": "existing_corrupt",
                        "context_id": context_id,
                        "run_id": run_id,
                        "current_advanced": False,
                    }
                try:
                    self._private_file(yaml_path)
                except OSError as exc:
                    raise JsContextStoreError("document_write_failed") from exc
                if document_identity(stored) != document_identity(value):
                    return {
                        "status": "same_run_conflict",
                        "context_id": context_id,
                        "run_id": run_id,
                        "current_advanced": False,
                    }
                base_status = "identical"
            else:
                text = self._yaml_text(value)
                if len(text.encode("utf-8")) > MAX_DOCUMENT_BYTES:
                    raise JsContextStoreError("document_too_large")
                try:
                    self._write_text(yaml_path, text)
                    self._private_file(yaml_path)
                except OSError as exc:
                    raise JsContextStoreError("document_write_failed") from exc
                status, stored, document_sha = self._read_document(
                    yaml_path,
                    project_id=project_id,
                    context_id=context_id,
                    expected_run_id=run_id,
                )
                if status != "ok" or stored is None or document_sha is None:
                    raise JsContextStoreError("document_readback_failed")
                base_status = "published"

            candidate_ns = yaml_path.stat().st_mtime_ns
            candidate_pointer = self._pointer(
                project_id=project_id,
                context_id=context_id,
                run_id=run_id,
                document_sha256=document_sha,
                published_at_ns=candidate_ns,
            )
            current_status, current = self._read_current(
                project_id,
                context_id,
            )
            if current_status == "corrupt":
                return {
                    "status": "current_corrupt",
                    "context_id": context_id,
                    "run_id": run_id,
                    "current_advanced": False,
                }
            current_advanced = False
            promote_pointer = candidate_pointer
            if current_status == "missing":
                recovery_status, latest = self._latest_valid_publication(
                    project_id=project_id,
                    context_id=context_id,
                    context_dir=context_dir,
                )
                if recovery_status == "limit":
                    return {
                        "status": "current_recovery_scan_limit",
                        "context_id": context_id,
                        "run_id": run_id,
                        "current_run_id": None,
                        "current_advanced": False,
                    }
                if latest is not None:
                    promote_pointer = self._pointer(
                        project_id=project_id,
                        context_id=context_id,
                        **latest,
                    )
                current_advanced = True
            elif current["run_id"] == run_id:
                if (
                    current["document_sha256"] != document_sha
                    or current["published_at_ns"] != candidate_ns
                ):
                    return {
                        "status": "current_binding_mismatch",
                        "context_id": context_id,
                        "run_id": run_id,
                        "current_advanced": False,
                    }
                try:
                    self._private_file(current_path)
                except OSError as exc:
                    raise JsContextStoreError("current_write_failed") from exc
            elif candidate_ns > current["published_at_ns"]:
                current_advanced = True

            if current_advanced:
                self._write_pointer(current_path, promote_pointer)
                current_run_id = promote_pointer["run_id"]
            elif current_status == "ok" and current is not None:
                current_run_id = current["run_id"]
            else:
                current_run_id = None

            if current_advanced and base_status == "identical":
                final_status = "recovered"
            elif not current_advanced and base_status == "published":
                final_status = "not_current"
            elif (
                not current_advanced
                and base_status == "identical"
                and current_status == "ok"
                and current["run_id"] != run_id
            ):
                final_status = "not_current"
            else:
                final_status = base_status
            return {
                "status": final_status,
                "context_id": context_id,
                "run_id": run_id,
                "document_file": yaml_path.name,
                "document_sha256": document_sha,
                "current_run_id": current_run_id,
                "current_advanced": current_advanced,
            }

    @staticmethod
    def _summary(
        document: dict,
        *,
        document_sha256: str,
        size_bytes: int,
        current_run_id: str | None,
    ) -> dict:
        context = document["context"]
        return {
            "context_id": context_id_for(
                project_id=context["project_id"],
                origin=context["origin"],
                auth_ref=context["auth_ref"],
            ),
            "run_id": context["run_id"],
            "origin": context["origin"],
            "auth_ref": context["auth_ref"],
            "coverage": context["coverage"],
            "behavior_count": len(document["behaviors"]),
            "evidence_count": len(document["evidence"]),
            "document_sha256": document_sha256,
            "size_bytes": size_bytes,
            "current": context["run_id"] == current_run_id,
        }

    def _load_for_read(
        self,
        *,
        project_id: str,
        context_id: str,
        selector: str,
    ) -> tuple[str, dict | None, dict | None, str | None]:
        _validate_context_id(context_id)
        if selector == "current":
            current_status, pointer = self._read_current(project_id, context_id)
            if current_status != "ok":
                return current_status, None, None, None
            run_id = pointer["run_id"]
            path = self._document_path(project_id, context_id, run_id)
            status, document, document_sha = self._read_document(
                path,
                project_id=project_id,
                context_id=context_id,
                expected_run_id=run_id,
                expected_sha256=pointer["document_sha256"],
            )
            return status, document, pointer, document_sha
        run_id = _validate_run_id(selector)
        path = self._document_path(project_id, context_id, run_id)
        status, document, document_sha = self._read_document(
            path,
            project_id=project_id,
            context_id=context_id,
            expected_run_id=run_id,
        )
        current_status, pointer = self._read_current(project_id, context_id)
        return (
            status,
            document,
            pointer if current_status == "ok" else None,
            document_sha,
        )

    def read(
        self,
        *,
        project_id: str,
        context_id: str,
        selector: str = "current",
        section: str = "metadata",
        limit: int = _DEFAULT_LIMIT,
        cursor: str | None = None,
        expected_document_id: str | None = None,
        expected_sha256: str | None = None,
    ) -> dict:
        """Read one explicitly selected publication or its bounded sections."""
        validate_path_component(project_id, "project_id")
        if section not in _SECTIONS:
            raise ValueError("unsupported js context section")
        bounded = _bounded_limit(limit)
        if selector != "current":
            _validate_run_id(selector)
        run_marker = "current" if selector == "current" else selector
        status, document, pointer, document_sha = self._load_for_read(
            project_id=project_id,
            context_id=context_id,
            selector=selector,
        )
        if status == "ok" and (
            (expected_sha256 is not None and document_sha != expected_sha256)
            or (
                expected_document_id is not None
                and document_identity(document) != expected_document_id
            )
        ):
            status = "document_mismatch"
        expected_selector = {
            "kind": "current" if selector == "current" else "run",
            "run_id": (
                pointer["run_id"]
                if selector == "current" and pointer is not None
                else run_marker if selector != "current" else None
            ),
        }
        if status != "ok":
            return {
                "status": status,
                "context_id": context_id,
                "selector": expected_selector,
            }
        assert document is not None
        assert document_sha is not None
        current_run = (
            pointer["run_id"]
            if (
                pointer is not None
                and pointer["document_sha256"] == document_sha
            )
            else None
        )
        publication = self._summary(
            document,
            document_sha256=document_sha,
            size_bytes=self._document_path(
                project_id,
                context_id,
                document["context"]["run_id"],
            ).stat().st_size,
            current_run_id=current_run,
        )
        base = {
            "status": "ok",
            "context_id": context_id,
            "selector": {
                "kind": "current" if selector == "current" else "run",
                "run_id": document["context"]["run_id"],
            },
            "context": document["context"],
            "publication": publication,
        }
        if section == "context":
            return {**base, "section": "context"}
        if section == "metadata":
            return {**base, "section": "metadata"}
        items = document[section]
        binding = f"{project_id}\0{context_id}\0{document['context']['run_id']}\0{section}"
        offset = _decode_cursor(binding, cursor)
        window = items[offset : offset + bounded]
        next_offset = offset + len(window)
        return {
            **base,
            "section": section,
            "items": window,
            "next_cursor": (
                _encode_cursor(binding, next_offset)
                if next_offset < len(items)
                else None
            ),
        }

    def list(
        self,
        *,
        project_id: str,
        context_id: str | None = None,
        limit: int = _DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> dict:
        """List bounded publication metadata without exposing filesystem paths."""
        validate_path_component(project_id, "project_id")
        bounded = _bounded_limit(limit)
        if context_id is not None:
            _validate_context_id(context_id)
            context_dirs = [self._context_dir(project_id, context_id)]
        else:
            bucket = self._bucket(project_id)
            context_dirs = (
                sorted(
                    path
                    for path in bucket.iterdir()
                    if path.is_dir() and not path.is_symlink()
                )
                if bucket.is_dir()
                else []
            )
        paths: list[tuple[str, Path]] = []
        truncated = False
        for directory in context_dirs:
            if not _CONTEXT_ID.fullmatch(directory.name):
                continue
            for path in sorted(directory.glob("*.yml")):
                if path.is_symlink():
                    continue
                if len(paths) >= _MAX_LIST_SCAN:
                    truncated = True
                    break
                paths.append((directory.name, path))
            if truncated:
                break
        current_cache = {}
        view_parts = []
        for candidate_context_id, path in paths:
            if candidate_context_id not in current_cache:
                current_cache[candidate_context_id] = self._read_current(
                    project_id,
                    candidate_context_id,
                )
            current_status, pointer = current_cache[candidate_context_id]
            try:
                stat = path.stat()
                file_part = [path.name, stat.st_size, stat.st_mtime_ns]
            except OSError:
                file_part = [path.name, None, None]
            view_parts.append(
                {
                    "context_id": candidate_context_id,
                    "file": file_part,
                    "current_status": current_status,
                    "current": pointer,
                }
            )
        view_id = hashlib.sha256(
            json.dumps(
                {
                    "context_filter": context_id,
                    "scan_truncated": truncated,
                    "publications": view_parts,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        binding = (
            f"{project_id}\0{context_id or '*'}\0{view_id}__list"
        )
        offset = _decode_cursor(binding, cursor)
        window = paths[offset : offset + bounded]
        publications = []
        for candidate_context_id, path in window:
            status, document, document_sha = self._read_document(
                path,
                project_id=project_id,
                context_id=candidate_context_id,
                expected_run_id=path.stem,
            )
            if status != "ok":
                publications.append(
                    {
                        "status": status,
                        "context_id": candidate_context_id,
                        "run_id": path.stem,
                    }
                )
                continue
            current_status, pointer = self._read_current(
                project_id,
                candidate_context_id,
            )
            current_run_id = (
                pointer["run_id"]
                if (
                    current_status == "ok"
                    and pointer is not None
                    and pointer["document_sha256"] == document_sha
                )
                else None
            )
            publications.append(
                {
                    "status": "ok",
                    **self._summary(
                        document,
                        document_sha256=document_sha,
                        size_bytes=path.stat().st_size,
                        current_run_id=current_run_id,
                    ),
                }
            )
        next_offset = offset + len(window)
        return {
            "publications": publications,
            "view_id": view_id,
            "next_cursor": (
                _encode_cursor(binding, next_offset)
                if next_offset < len(paths)
                else None
            ),
            "scan_truncated": truncated,
        }


__all__ = ["JsContextStore", "JsContextStoreError"]
