"""Private, bounded persistence and reads for generated-JS structure indexes."""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from polymerhus.app.data_root import project_dir, validate_path_component
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_acquisition.structure import ParsedStructure

_LOCKS: dict[Path, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
_ITEM_KINDS = ("import", "module", "dependency", "chunk", "loader")
_MAX_INDEX_BYTES = 16 * 1024 * 1024
_MAX_PUBLIC_ITEM_BYTES = 4096
_MAX_RESPONSE_BYTES = 15 * 1024
_MAX_STRING = 512
_URL_TOKEN = re.compile(r"""(?:https?://|\.{0,2}/)[^\s'"<>]+""")


class StructureStoreError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _lock_for(path: Path) -> threading.RLock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(path)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[path] = lock
        return lock


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _document_digest(document: dict) -> str:
    return _digest(
        {key: value for key, value in document.items() if key != "integrity"}
    )


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _safe_string(value: object, *, limit: int = _MAX_STRING) -> str:
    text = str(value)
    if len(text) > limit:
        return text[:limit] + "…"
    return text


def _redact_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return "***"
    query = "&".join(f"{name}=***" for name, _ in parse_qsl(
        parsed.query,
        keep_blank_values=True,
    ))
    hostname = parsed.hostname
    port = f":{parsed.port}" if parsed.port else ""
    netloc = ""
    if hostname:
        netloc = hostname + port
    return urlunsplit(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            query,
            "***" if parsed.fragment else "",
        )
    )


def _redact_text(value: object) -> str:
    text = _safe_string(value)
    return _URL_TOKEN.sub(_redact_url, text)


def _safe_value(value: object, *, depth: int = 0) -> object:
    if depth > 4:
        return "***"
    if isinstance(value, dict):
        return {
            _safe_string(key, limit=80): _safe_value(item, depth=depth + 1)
            for key, item in sorted(value.items())
            if str(key) not in {"message", "specifier", "expression", "value"}
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return "***"


def _public_item(item: dict, *, index_id: str) -> dict:
    kind = str(item.get("kind") or "")
    common = {
        "item_id": item.get("item_id"),
        "index_id": index_id,
        "kind": kind,
        "start_byte": item.get("start_byte"),
        "end_byte": item.get("end_byte"),
    }
    if kind == "import":
        reference = item.get("specifier")
        if reference is None:
            reference = item.get("expression")
        details = {
            "subtype": item.get("subtype"),
            "import_kind": item.get("import_kind"),
            "resolved": bool(item.get("resolved")),
            "reference": (
                {"display": _redact_text(reference), "private": True}
                if reference is not None
                else None
            ),
        }
    elif kind == "dependency":
        details = {
            "binding_kind": item.get("binding_kind"),
            "context_module_id": item.get("context_module_id"),
            "context_module_occurrence": item.get("context_module_occurrence"),
            "target_module_id": item.get("target_module_id"),
            "resolution": item.get("resolution"),
            "ambiguous": bool(item.get("ambiguous")),
            "target_item_id": item.get("target_item_id"),
            "namespace_id": item.get("namespace_id"),
        }
    elif kind == "module":
        details = {
            "module_id": item.get("module_id"),
            "module_ordinal": item.get("module_ordinal"),
            "runtime_key": item.get("runtime_key"),
            "registration_kind": item.get("registration_kind"),
            "context": _safe_value(item.get("context") or {}),
        }
    elif kind == "chunk":
        details = {
            "runtime_key": item.get("runtime_key"),
            "chunk_ids": _safe_value(item.get("chunk_ids") or []),
            "entry_ids": _safe_value(item.get("entry_ids") or []),
            "registration_kind": item.get("registration_kind"),
        }
    else:
        details = {
            "subtype": item.get("subtype"),
            "runtime_ids": _safe_value(item.get("runtime_ids") or []),
            "runtime_dependent": bool(item.get("runtime_dependent")),
        }
    public = {**common, **details}
    if len(_canonical(public)) > _MAX_PUBLIC_ITEM_BYTES:
        public = {
            "item_id": common["item_id"],
            "index_id": index_id,
            "kind": kind,
            "start_byte": common["start_byte"],
            "end_byte": common["end_byte"],
            "summary": f"{kind} item; details truncated",
        }
    return public


def _public_metadata(document: dict) -> dict:
    metadata = document.get("metadata") or {}
    return {
        "index_id": metadata.get("index_id"),
        "lead_id": metadata.get("lead_id"),
        "source_sha256": metadata.get("source_sha256"),
        "source_size": metadata.get("source_size"),
        "format": metadata.get("format"),
        "status": metadata.get("status"),
        "counts": metadata.get("counts") or {},
        "gaps": metadata.get("gaps") or [],
        "parse_error_count": len(metadata.get("parse_errors") or []),
        "parser": metadata.get("parser") or {},
        "config_identity": metadata.get("config_identity"),
    }


class StructureStore:
    def __init__(self, *, root=None) -> None:
        self._root = root

    def _run_dir(self, project_id: str, run_id: str) -> Path:
        validate_path_component(run_id, "run_id")
        return project_dir(
            project_id,
            "recon/js_analysis",
            root=self._root,
        ) / run_id

    def _index_path(self, project_id: str, run_id: str, index_id: str) -> Path:
        validate_path_component(index_id, "index_id")
        return self._run_dir(project_id, run_id) / "structures" / f"{index_id}.json"

    def _manifest(self, project_id: str, run_id: str) -> AcquisitionManifest:
        return AcquisitionManifest(
            project_id=project_id,
            run_id=run_id,
            root=self._root,
            max_run_bytes=64 * 1024 * 1024,
        )

    @contextmanager
    def _locked(self, project_id: str, run_id: str):
        path = self._run_dir(project_id, run_id) / "structures" / ".structure.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock_for(path):
            with path.open("a+", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _lead_key(context_ref: str, lead_id: str) -> str:
        return hashlib.sha256(
            f"{context_ref or ''}\0{lead_id}".encode("utf-8")
        ).hexdigest()

    def config_identity(self) -> str:
        parser_dir = Path(__file__).resolve().with_name("parser")
        payload = {
            "schema": 1,
            "adapter": "polymerhus-babel-structure",
            "adapter_version": "1.0.0",
            "parser_script_sha256": hashlib.sha256(
                (parser_dir / "structure_parser.mjs").read_bytes()
            ).hexdigest(),
            "package_sha256": hashlib.sha256(
                (parser_dir / "package.json").read_bytes()
            ).hexdigest(),
        }
        return "structure-config:" + _digest(payload)

    def _index_id(
        self,
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        lead_id: str,
        source_sha256: str,
        parser_identity: dict,
        config_identity: str,
    ) -> str:
        return "stx_" + _digest(
            {
                "schema": 1,
                "project_id": project_id,
                "run_id": run_id,
                "context_ref": context_ref,
                "lead_id": lead_id,
                "source_sha256": source_sha256,
                "parser": parser_identity,
                "config_identity": config_identity,
            }
        )[:32]

    def _item_id(self, index_id: str, occurrence_key: str) -> str:
        return "sti_" + hashlib.sha256(
            f"{index_id}\0{occurrence_key}".encode("utf-8")
        ).hexdigest()[:32]

    def _load_index(
        self,
        *,
        project_id: str,
        run_id: str,
        index_id: str,
    ) -> dict:
        path = self._index_path(project_id, run_id, index_id)
        if not path.is_file():
            raise StructureStoreError("structure_index_missing")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise StructureStoreError("structure_index_corrupt") from None
        if (
            not isinstance(document, dict)
            or document.get("schema_version") != 1
            or document.get("index_id") != index_id
            or document.get("integrity") != _document_digest(document)
            or not isinstance(document.get("metadata"), dict)
            or not isinstance(document.get("items"), list)
        ):
            raise StructureStoreError("structure_index_corrupt")
        metadata = document["metadata"]
        if (
            metadata.get("project_id") != project_id
            or metadata.get("run_id") != run_id
            or metadata.get("index_id") != index_id
        ):
            raise StructureStoreError("structure_index_corrupt")
        return document

    def _current_index_id(
        self,
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        lead_id: str,
    ) -> str:
        manifest = self._manifest(project_id, run_id).get()
        structures = manifest.get("structures") or {}
        key = self._lead_key(context_ref, lead_id)
        pointer = (structures.get("leads") or {}).get(key) or {}
        index_id = str(pointer.get("index_id") or "")
        if not index_id:
            raise StructureStoreError("structure_index_missing")
        if (
            pointer.get("context_ref") != (context_ref or "")
            or pointer.get("lead_id") != lead_id
        ):
            raise StructureStoreError("structure_index_missing")
        return index_id

    def current_index_id(
        self,
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        lead_id: str,
    ) -> str:
        return self._current_index_id(
            project_id=project_id,
            run_id=run_id,
            context_ref=context_ref,
            lead_id=lead_id,
        )

    def _resolutions(
        self,
        *,
        project_id: str,
        run_id: str,
    ) -> dict:
        manifest = self._manifest(project_id, run_id).get()
        return dict((manifest.get("structures") or {}).get("resolutions") or {})

    def store_index(
        self,
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        lead_id: str,
        source_bytes: bytes,
        parsed: ParsedStructure,
        parent_final_url: str | None = None,
    ) -> dict:
        if not isinstance(source_bytes, bytes):
            raise StructureStoreError("structure_source_must_be_bytes")
        source_sha256 = hashlib.sha256(source_bytes).hexdigest()
        if (
            source_sha256 != parsed.source_sha256
            or len(source_bytes) != parsed.source_size
        ):
            raise StructureStoreError("structure_source_mismatch")
        if parsed.status not in {"complete", "partial", "unsupported", "failed"}:
            raise StructureStoreError("invalid_structure_status")
        config_identity = self.config_identity()
        index_id = self._index_id(
            project_id=project_id,
            run_id=run_id,
            context_ref=context_ref,
            lead_id=lead_id,
            source_sha256=source_sha256,
            parser_identity=parsed.parser,
            config_identity=config_identity,
        )

        with self._locked(project_id, run_id):
            path = self._index_path(project_id, run_id, index_id)
            if path.is_file():
                document = self._load_index(
                    project_id=project_id,
                    run_id=run_id,
                    index_id=index_id,
                )
            else:
                items = []
                for parsed_item in parsed.items:
                    occurrence_key = str(parsed_item.get("occurrence_key") or "")
                    if not occurrence_key:
                        raise StructureStoreError("invalid_structure_identity")
                    item_id = self._item_id(index_id, occurrence_key)
                    private = {
                        **parsed_item,
                        "item_id": item_id,
                        "index_id": index_id,
                    }
                    if (
                        private.get("kind") == "dependency"
                        and private.get("resolution")
                        == "same_registration_candidate"
                    ):
                        private["resolution"] = "unresolved_in_file"
                    items.append(
                        {
                            "item_id": item_id,
                            "public": _public_item(private, index_id=index_id),
                            "private": private,
                        }
                    )
                counts = {
                    kind: sum(
                        1
                        for item in parsed.items
                        if item.get("kind") == kind
                    )
                    for kind in _ITEM_KINDS
                }
                now = int(time.time())
                document = {
                    "schema_version": 1,
                    "index_id": index_id,
                    "metadata": {
                        "index_id": index_id,
                        "project_id": project_id,
                        "run_id": run_id,
                        "context_ref": context_ref or "",
                        "lead_id": lead_id,
                        "source_sha256": source_sha256,
                        "source_size": len(source_bytes),
                        "format": parsed.format,
                        "status": parsed.status,
                        "counts": counts,
                        "gaps": list(parsed.gaps),
                        "parse_errors": list(parsed.parse_errors),
                        "parser": dict(parsed.parser),
                        "config_identity": config_identity,
                        "parent_final_url": parent_final_url,
                        "created_at": now,
                    },
                    "items": items,
                }
                document["integrity"] = _document_digest(document)
                body = json.dumps(
                    document,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
                if len(body.encode("utf-8")) > _MAX_INDEX_BYTES:
                    raise StructureStoreError("structure_index_size_limit")
                _atomic_text(path, body + "\n")

            metadata = document["metadata"]

            def mutate(value: dict) -> None:
                structures = value.setdefault("structures", {})
                indexes = structures.setdefault("indexes", {})
                indexes[index_id] = {
                    "index_id": index_id,
                    "index_file": f"structures/{index_id}.json",
                    "index_sha256": document["integrity"],
                    "project_id": project_id,
                    "run_id": run_id,
                    "context_ref": context_ref or "",
                    "lead_id": lead_id,
                    "source_sha256": source_sha256,
                    "source_size": len(source_bytes),
                    "parser": dict(parsed.parser),
                    "config_identity": config_identity,
                    "status": parsed.status,
                }
                key = self._lead_key(context_ref, lead_id)
                structures.setdefault("leads", {})[key] = {
                    "index_id": index_id,
                    "context_ref": context_ref or "",
                    "lead_id": lead_id,
                    "source_sha256": source_sha256,
                    "updated_at": int(time.time()),
                }

            self._manifest(project_id, run_id).update(mutate)
            return _public_metadata(document)

    def find_index(
        self,
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        lead_id: str,
        source_sha256: str,
        parser_identity: dict,
        config_identity: str,
    ) -> dict | None:
        try:
            index_id = self._current_index_id(
                project_id=project_id,
                run_id=run_id,
                context_ref=context_ref,
                lead_id=lead_id,
            )
        except StructureStoreError:
            return None
        document = self._load_index(
            project_id=project_id,
            run_id=run_id,
            index_id=index_id,
        )
        metadata = document["metadata"]
        if (
            metadata.get("source_sha256") != source_sha256
            or metadata.get("parser") != parser_identity
            or metadata.get("config_identity") != config_identity
        ):
            return None
        return _public_metadata(document)

    def current_imports(
        self,
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        lead_id: str,
        source_sha256: str,
        max_items: int = 4096,
        max_bytes: int = 8 * 1024 * 1024,
    ) -> dict:
        """Return private ESM import facts from the current verified index.

        This trusted proposal-side adapter binds every fact to the current
        project/run/context/lead/source version and rejects stale pointers,
        mismatched source hashes, corrupt indexes, and oversized inputs.
        """
        if (
            not isinstance(max_items, int)
            or isinstance(max_items, bool)
            or max_items <= 0
            or not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or max_bytes <= 0
        ):
            raise StructureStoreError("invalid_structure_limit")
        index_id = self._current_index_id(
            project_id=project_id,
            run_id=run_id,
            context_ref=context_ref,
            lead_id=lead_id,
        )
        manifest = self._manifest(project_id, run_id).get()
        pointer = (
            (manifest.get("structures") or {}).get("indexes") or {}
        ).get(index_id) or {}
        path = self._index_path(project_id, run_id, index_id)
        try:
            if path.stat().st_size > max_bytes:
                raise StructureStoreError("structure_index_limit")
        except OSError:
            raise StructureStoreError("structure_index_missing") from None
        document = self._load_index(
            project_id=project_id,
            run_id=run_id,
            index_id=index_id,
        )
        metadata = document["metadata"]
        expected_context = {
            "project_id": project_id,
            "run_id": run_id,
            "context_ref": context_ref or "",
            "lead_id": lead_id,
        }
        expected_binding = {
            **expected_context,
            "source_sha256": source_sha256,
        }
        if any(metadata.get(key) != value for key, value in expected_context.items()):
            raise StructureStoreError("structure_context_mismatch")
        if metadata.get("source_sha256") != source_sha256:
            raise StructureStoreError("structure_source_mismatch")
        if (
            pointer.get("index_sha256") != document.get("integrity")
            or any(pointer.get(key) != value for key, value in expected_binding.items())
        ):
            raise StructureStoreError("structure_index_stale")

        source_size = metadata.get("source_size")
        if not isinstance(source_size, int) or source_size < 0:
            raise StructureStoreError("structure_index_corrupt")
        imports = []
        gaps = list(metadata.get("gaps") or [])
        if metadata.get("status") == "partial":
            gaps.append("structure_index_partial")
        elif metadata.get("status") in {"unsupported", "failed"}:
            gaps.append(f"structure_index_{metadata['status']}")
        for entry in document["items"]:
            if not isinstance(entry, dict) or not isinstance(
                entry.get("private"),
                dict,
            ):
                gaps.append("invalid_structure_import")
                continue
            private = entry["private"]
            if private.get("kind") != "import":
                continue
            item_id = private.get("item_id")
            start = private.get("start_byte")
            end = private.get("end_byte")
            specifier = private.get("specifier")
            if (
                private.get("resolved") is not True
                or not isinstance(specifier, str)
                or not specifier
            ):
                gaps.append("structure_import_reference_unresolved")
                continue
            if (
                not isinstance(item_id, str)
                or item_id != entry.get("item_id")
                or not isinstance(start, int)
                or not isinstance(end, int)
                or start < 0
                or end <= start
                or end > source_size
                or private.get("subtype") not in {"static", "dynamic"}
            ):
                gaps.append("invalid_structure_import")
                continue
            if len(imports) >= max_items:
                gaps.append("structure_import_limit")
                break
            imports.append(
                {
                    "item_id": item_id,
                    "start_byte": start,
                    "end_byte": end,
                    "specifier": specifier,
                    "subtype": str(private.get("subtype")),
                    "import_kind": str(
                        private.get("import_kind") or "unknown"
                    ),
                }
            )
        return {
            "index_id": index_id,
            "index_integrity": document["integrity"],
            "source_sha256": metadata["source_sha256"],
            "source_size": source_size,
            "parent_final_url": metadata.get("parent_final_url"),
            "format": metadata.get("format"),
            "status": metadata.get("status"),
            "imports": imports,
            "gaps": sorted(set(gaps)),
        }

    @staticmethod
    def _cursor(
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        lead_id: str,
        index_id: str,
        kind: str,
        offset: int,
    ) -> str:
        body = _canonical({"offset": offset})
        binding = "\0".join(
            (
                project_id,
                run_id,
                context_ref or "",
                lead_id,
                index_id,
                kind,
            )
        ).encode("utf-8")
        digest = hashlib.sha256(binding + body).digest()[:8]
        return base64.urlsafe_b64encode(body + digest).decode().rstrip("=")

    def _cursor_offset(
        self,
        cursor: str | None,
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        lead_id: str,
        index_id: str,
        kind: str,
    ) -> int:
        if not cursor:
            return 0
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            payload = base64.urlsafe_b64decode(padded.encode("ascii"))
            body, observed = payload[:-8], payload[-8:]
            binding = "\0".join(
                (
                    project_id,
                    run_id,
                    context_ref or "",
                    lead_id,
                    index_id,
                    kind,
                )
            ).encode("utf-8")
            expected = hashlib.sha256(binding + body).digest()[:8]
            value = json.loads(body)
            offset = value.get("offset")
            if observed != expected or not isinstance(offset, int) or offset < 0:
                raise ValueError
            return offset
        except (
            ValueError,
            TypeError,
            UnicodeError,
            json.JSONDecodeError,
        ):
            raise StructureStoreError("invalid_structure_cursor") from None

    def list_items(
        self,
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        lead_id: str,
        kind: str | None = None,
        cursor: str | None = None,
        limit: int = 5,
    ) -> dict:
        if kind is not None and kind not in _ITEM_KINDS:
            raise StructureStoreError("invalid_structure_kind")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise StructureStoreError("invalid_structure_limit")
        limit = min(limit, 10)
        index_id = self._current_index_id(
            project_id=project_id,
            run_id=run_id,
            context_ref=context_ref,
            lead_id=lead_id,
        )
        document = self._load_index(
            project_id=project_id,
            run_id=run_id,
            index_id=index_id,
        )
        offset = self._cursor_offset(
            cursor,
            project_id=project_id,
            run_id=run_id,
            context_ref=context_ref,
            lead_id=lead_id,
            index_id=index_id,
            kind=kind or "",
        )
        resolutions = self._resolutions(project_id=project_id, run_id=run_id)
        selected = [
            entry
            for entry in document["items"]
            if kind is None or entry.get("public", {}).get("kind") == kind
        ]
        window = selected[offset : offset + limit]
        items = []
        for entry in window:
            private = {
                **entry["private"],
                **(resolutions.get(entry["item_id"]) or {}),
            }
            items.append(_public_item(private, index_id=index_id))
        next_offset = offset + len(items)
        metadata = _public_metadata(document)
        response = {
            **metadata,
            "item_count": len(selected),
            "items": items,
            "next_cursor": (
                self._cursor(
                    project_id=project_id,
                    run_id=run_id,
                    context_ref=context_ref,
                    lead_id=lead_id,
                    index_id=index_id,
                    kind=kind or "",
                    offset=next_offset,
                )
                if next_offset < len(selected)
                else None
            ),
        }
        while len(_canonical(response)) > _MAX_RESPONSE_BYTES:
            if not response["items"]:
                raise StructureStoreError("structure_response_too_large")
            response["items"].pop()
            returned = offset + len(response["items"])
            response["next_cursor"] = (
                self._cursor(
                    project_id=project_id,
                    run_id=run_id,
                    context_ref=context_ref,
                    lead_id=lead_id,
                    index_id=index_id,
                    kind=kind or "",
                    offset=returned,
                )
                if returned < len(selected)
                else None
            )
        return response

    def _find_item(
        self,
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        item_id: str,
    ) -> tuple[dict, dict]:
        validate_path_component(item_id, "item_id")
        manifest = self._manifest(project_id, run_id).get()
        structures = manifest.get("structures") or {}
        candidates = sorted(
            (
                index_id
                for index_id, record in (structures.get("indexes") or {}).items()
                if (record.get("context_ref") or "") == (context_ref or "")
            )
        )
        for index_id in candidates:
            document = self._load_index(
                project_id=project_id,
                run_id=run_id,
                index_id=index_id,
            )
            for entry in document["items"]:
                if entry.get("item_id") == item_id:
                    return document, entry
        raise StructureStoreError("structure_item_missing")

    def get_item(
        self,
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        item_id: str,
    ) -> dict:
        document, entry = self._find_item(
            project_id=project_id,
            run_id=run_id,
            context_ref=context_ref,
            item_id=item_id,
        )
        resolutions = self._resolutions(project_id=project_id, run_id=run_id)
        private = {
            **entry["private"],
            **(resolutions.get(item_id) or {}),
        }
        return {
            "source_sha256": document["metadata"].get("source_sha256"),
            "format": document["metadata"].get("format"),
            "item": _public_item(
                private,
                index_id=str(document["metadata"]["index_id"]),
            ),
        }

    def private_item(
        self,
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        item_id: str,
    ) -> dict:
        document, entry = self._find_item(
            project_id=project_id,
            run_id=run_id,
            context_ref=context_ref,
            item_id=item_id,
        )
        resolutions = self._resolutions(project_id=project_id, run_id=run_id)
        return {
            **entry["private"],
            **(resolutions.get(item_id) or {}),
            "lead_id": document["metadata"].get("lead_id"),
            "index_id": document["metadata"].get("index_id"),
            "parent_final_url": document["metadata"].get("parent_final_url"),
            "source_sha256": document["metadata"].get("source_sha256"),
            "source_size": document["metadata"].get("source_size"),
            "format": document["metadata"].get("format"),
        }

    def link_namespace(
        self,
        *,
        project_id: str,
        run_id: str,
        context_ref: str,
        namespace_id: str,
        index_ids: list[str],
    ) -> dict:
        validate_path_component(namespace_id, "namespace_id")
        if not index_ids or len(set(index_ids)) != len(index_ids):
            raise StructureStoreError("invalid_structure_namespace")
        documents = [
            self._load_index(
                project_id=project_id,
                run_id=run_id,
                index_id=index_id,
            )
            for index_id in index_ids
        ]
        for document in documents:
            if (
                (document["metadata"].get("context_ref") or "")
                != (context_ref or "")
            ):
                raise StructureStoreError("structure_context_mismatch")

        modules_by_id: dict[str, list[dict]] = {}
        dependencies: list[tuple[str, dict]] = []
        for document in documents:
            index_id = str(document["metadata"]["index_id"])
            for entry in document["items"]:
                private = entry["private"]
                if private.get("kind") == "module":
                    modules_by_id.setdefault(
                        str(private.get("module_id") or ""),
                        [],
                    ).append({**private, "index_id": index_id})
                elif private.get("kind") == "dependency":
                    dependencies.append((index_id, private))

        updates: dict[str, dict] = {}
        changed = 0
        ambiguous = 0
        prior = self._resolutions(project_id=project_id, run_id=run_id)
        for source_index_id, dependency in dependencies:
            candidates = modules_by_id.get(
                str(dependency.get("target_module_id") or ""),
                [],
            )
            if len(candidates) == 1:
                target = candidates[0]
                resolution = "resolved"
                target_item_id = target["item_id"]
            elif len(candidates) > 1:
                resolution = "ambiguous"
                target_item_id = None
                ambiguous += 1
            else:
                resolution = "unresolved_namespace"
                target_item_id = None
            item_id = str(dependency["item_id"])
            resolved = {
                "resolution": resolution,
                "target_item_id": target_item_id,
                "target_index_id": (
                    target["index_id"] if len(candidates) == 1 else None
                ),
                "namespace_id": namespace_id,
            }
            updates[item_id] = resolved
            previous = prior.get(item_id) or {}
            if resolution == "resolved" and (
                previous.get("resolution") != "resolved"
                or previous.get("target_item_id") != target_item_id
                or previous.get("namespace_id") != namespace_id
            ):
                changed += 1

        namespace_record = {
            "namespace_id": namespace_id,
            "context_ref": context_ref or "",
            "index_ids": list(index_ids),
            "index_integrity": {
                str(document["metadata"]["index_id"]): document["integrity"]
                for document in documents
            },
            "updated_at": int(time.time()),
        }

        def mutate(value: dict) -> None:
            structures = value.setdefault("structures", {})
            structures.setdefault("namespaces", {})[namespace_id] = namespace_record
            resolutions = structures.setdefault("resolutions", {})
            resolutions.update(updates)

        self._manifest(project_id, run_id).update(mutate)
        return {
            "namespace_id": namespace_id,
            "index_ids": list(index_ids),
            "changed_dependencies": changed,
            "ambiguous_dependencies": ambiguous,
            "unresolved_dependencies": sum(
                item["resolution"] == "unresolved_namespace"
                for item in updates.values()
            ),
        }


__all__ = ["StructureStore", "StructureStoreError"]
