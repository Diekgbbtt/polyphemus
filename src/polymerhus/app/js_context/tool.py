"""The one project-bound, read-only `js_context` native tool."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from polymerhus.app.data_root import validate_path_component
from polymerhus.app.js_context.selection import JsContextInput
from polymerhus.app.js_context.store import JsContextStore, JsContextStoreError

MAX_RESPONSE_BYTES = 16 * 1024
DEFAULT_LIMIT = 5
MAX_LIMIT = 10

JS_CONTEXT_CONTRACT = (
    "Read already-published client-side JavaScript analysis context for the "
    "application-bound project. This tool is read-only and cannot accept a "
    "project override, filesystem path, write value, source URL or source "
    "bytes.\n\n"
    "COMMANDS - `list` discovers compact publications, optionally filtered by "
    "`context_id`. `read` requires both `context_id` and an explicit "
    "`selector`: a producing run ID or the literal `current`. Omitting the "
    "selector never defaults to another run.\n\n"
    "SECTIONS - `metadata` is the compact orientation view; `context` returns "
    "identity plus a paginated coverage-gap list; `behaviors` returns whole "
    "saved behavioural records; `evidence` returns whole evidence-index "
    "records. Coverage and availability labels remain explicit: "
    "`retained_unverified` does not mean source bytes were re-read, and "
    "missing/pending/gap evidence is not silently promoted to available.\n\n"
    "PAGINATION - pages default to 5 and never exceed 10 logical records. A "
    "response is additionally capped at 16 KiB of UTF-8 JSON, so a page can "
    "be shorter. `next_cursor` is bound to project, context/filter, selector, "
    "section and the publication/list snapshot. Reusing it after the current "
    "pointer or publication changes returns `stale_cursor`; restart the read. "
    "A whole behavior/evidence record is never cut. An individually oversized "
    "record returns `record_too_large` without advancing the cursor.\n\n"
    "ERRORS - failures are bounded coded envelopes: `invalid_arguments`, "
    "`invalid_cursor`, `stale_cursor`, `missing`, `corrupt`, "
    "`run_mismatch`, `record_too_large`, `response_too_large` or "
    "`store_unavailable`. Missing data never becomes a successful empty read. "
    "A clean publication with no items can return a valid empty page."
)


class JsContextArgs(BaseModel):
    """Closed argument contract for the model-facing read-only tool."""

    model_config = ConfigDict(extra="forbid")

    command: Literal["list", "read"] = Field(
        description="`list` compact publications; `read` one explicit publication section."
    )
    context_id: str | None = Field(
        default=None,
        pattern=r"^jsctx_[0-9a-f]{40}$",
        description=(
            "Required for `read`; optional context filter for `list`. "
            "The project itself is bound by the application."
        ),
    )
    selector: str | None = Field(
        default=None,
        max_length=200,
        description=(
            "Required for `read`: a producing run ID or the literal `current`. "
            "Must be omitted for `list`."
        ),
    )
    section: Literal["metadata", "context", "behaviors", "evidence"] = Field(
        default="metadata",
        description=(
            "Read section. `metadata` keeps orientation compact; `context` "
            "paginates run-wide gaps; `behaviors` and `evidence` return whole records."
        ),
    )
    limit: int = Field(
        default=DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description="Logical page size, default 5 and maximum 10.",
    )
    cursor: str | None = Field(
        default=None,
        max_length=4096,
        description=(
            "Opaque continuation bound to project, selector, section and "
            "publication/list snapshot. Restart if returned as stale."
        ),
    )


def _invalid() -> dict:
    return {"ok": False, "error": "invalid_arguments"}


def _json_bytes(value: dict) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
        ).encode("utf-8")
    )


def _compact_publication(publication: dict) -> dict:
    if "document_sha256" not in publication:
        return {
            key: publication[key]
            for key in ("status", "context_id", "run_id")
            if key in publication
        }
    coverage = publication.get("coverage") or {}
    return {
        "context_id": publication.get("context_id"),
        "run_id": publication.get("run_id"),
        "origin": publication.get("origin"),
        "auth_ref": publication.get("auth_ref"),
        "coverage": {
            "status": coverage.get("status"),
            "gap_count": len(coverage.get("gaps") or []),
        },
        "behavior_count": publication.get("behavior_count"),
        "evidence_count": publication.get("evidence_count"),
        "document_sha256": publication.get("document_sha256"),
        "size_bytes": publication.get("size_bytes"),
        "current": bool(publication.get("current")),
    }


def _compact_context(context: dict) -> dict:
    coverage = context.get("coverage") or {}
    return {
        "project_id": context.get("project_id"),
        "run_id": context.get("run_id"),
        "origin": context.get("origin"),
        "auth_ref": context.get("auth_ref"),
        "coverage": {
            "status": coverage.get("status"),
            "gap_count": len(coverage.get("gaps") or []),
        },
    }


def _cursor_digest(project_id: str, body: bytes) -> bytes:
    return hashlib.sha256(
        project_id.encode("utf-8") + b"\0" + body
    ).digest()[:8]


def _encode_cursor(project_id: str, payload: dict) -> str:
    body = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(
        body + _cursor_digest(project_id, body)
    ).decode("ascii").rstrip("=")


def _decode_cursor(project_id: str, cursor: str) -> dict:
    try:
        raw = base64.urlsafe_b64decode(
            cursor + "=" * (-len(cursor) % 4)
        )
        body, observed = raw[:-8], raw[-8:]
        if not hmac.compare_digest(
            observed,
            _cursor_digest(project_id, body),
        ):
            raise ValueError
        value = json.loads(body)
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError
        return value
    except Exception:
        raise ValueError("invalid_cursor") from None


def _store_error(status: str) -> dict:
    error = {
        "missing": "missing",
        "corrupt": "corrupt",
        "run_mismatch": "run_mismatch",
    }.get(status, "store_unavailable")
    return {"ok": False, "error": error}


def build_js_context_tool(
    project_id: str | None = None,
    store: JsContextStore | None = None,
    selection: JsContextInput | None = None,
) -> StructuredTool:
    """Build the shared `js_context` tool with the project bound by the app."""
    if project_id is None:
        from polymerhus.app.config import config  # noqa: PLC0415

        project_id = config.PROJECT_ID
    seam = store if store is not None else JsContextStore()
    selection_binding = (
        {
            "input_id": selection.input_id,
            "project_id": selection.project_id,
            "producing_run_id": selection.producing_run_id,
            "context_id": selection.context_id,
            "document_id": selection.document_id,
            "document_sha256": selection.document_sha256,
            "auth_ref": selection.auth_ref,
            "origin": selection.origin.as_dict(),
        }
        if selection is not None
        else None
    )

    def selected_result(result: dict) -> dict:
        if selection_binding is None:
            return result
        if result.get("ok") is True and selection.document_sha256 is not None:
            if "publication" in result:
                observed = {
                    (result.get("publication") or {}).get(
                        "document_sha256"
                    )
                }
            elif "publications" in result:
                observed = {
                    item.get("document_sha256")
                    for item in result.get("publications") or []
                }
            else:
                observed = {None}
            if observed != {selection.document_sha256}:
                result = {"ok": False, "error": "corrupt"}
        return {**result, "js_context_binding": dict(selection_binding)}

    def list_context(args: JsContextArgs) -> dict:
        if args.selector is not None or args.section != "metadata":
            return _invalid()
        if selection is not None:
            if args.context_id not in (None, selection.context_id):
                return selected_result({"ok": False, "error": "missing"})
            if selection.status != "published":
                return selected_result({"ok": False, "error": "missing"})
            try:
                page = seam.read(
                    project_id=project_id,
                    context_id=selection.context_id,
                    selector=selection.producing_run_id,
                    section="metadata",
                )
            except (OSError, JsContextStoreError, ValueError):
                return selected_result(
                    {"ok": False, "error": "store_unavailable"}
                )
            if page.get("status") != "ok":
                return selected_result(_store_error(str(page.get("status"))))
            return selected_result(
                {
                    "ok": True,
                    "command": "list",
                    "publications": [
                        _compact_publication(page["publication"])
                    ],
                    "has_more": False,
                    "next_cursor": None,
                    "scan_truncated": False,
                }
            )
        cursor_state = None
        if args.cursor:
            try:
                cursor_state = _decode_cursor(project_id, args.cursor)
            except ValueError:
                return {"ok": False, "error": "invalid_cursor"}
            if (
                set(cursor_state)
                != {
                    "version",
                    "command",
                    "context_id",
                    "view_id",
                    "backend_cursor",
                    "delivered",
                }
                or cursor_state["command"] != "list"
                or cursor_state["context_id"] != args.context_id
            ):
                return {"ok": False, "error": "invalid_cursor"}
        backend_cursor = (
            cursor_state["backend_cursor"] if cursor_state else None
        )
        expected_view = cursor_state["view_id"] if cursor_state else None
        publications = []
        delivered = 0
        scan_truncated = False
        view_id = expected_view

        while delivered < args.limit:
            try:
                page = seam.list(
                    project_id=project_id,
                    context_id=args.context_id,
                    limit=1,
                    cursor=backend_cursor,
                )
            except ValueError:
                return {
                    "ok": False,
                    "error": (
                        "stale_cursor" if cursor_state else "store_unavailable"
                    ),
                }
            except (OSError, JsContextStoreError):
                return {"ok": False, "error": "store_unavailable"}
            page_view = page.get("view_id")
            if not isinstance(page_view, str):
                return {"ok": False, "error": "store_unavailable"}
            if view_id is None:
                view_id = page_view
                if expected_view is not None and view_id != expected_view:
                    return {"ok": False, "error": "stale_cursor"}
            elif page_view != view_id:
                return {"ok": False, "error": "stale_cursor"}
            scan_truncated = scan_truncated or bool(
                page.get("scan_truncated")
            )
            page_publications = page.get("publications") or []
            if not page_publications:
                backend_cursor = None
                break
            item = _compact_publication(page_publications[0])
            after_cursor = page.get("next_cursor")
            candidate_publications = [*publications, item]
            next_cursor = (
                _encode_cursor(
                    project_id,
                    {
                        "version": 1,
                        "command": "list",
                        "context_id": args.context_id,
                        "view_id": view_id,
                        "backend_cursor": after_cursor,
                        "delivered": delivered + 1,
                    },
                )
                if after_cursor
                else None
            )
            candidate = {
                "ok": True,
                "command": "list",
                "publications": candidate_publications,
                "has_more": after_cursor is not None,
                "next_cursor": next_cursor,
                "scan_truncated": scan_truncated,
            }
            if _json_bytes(candidate) > MAX_RESPONSE_BYTES:
                if not publications:
                    return {
                        "ok": False,
                        "error": "response_too_large",
                    }
                break
            publications = candidate_publications
            delivered += 1
            backend_cursor = after_cursor
            if backend_cursor is None:
                break

        next_cursor = (
            _encode_cursor(
                project_id,
                {
                    "version": 1,
                    "command": "list",
                    "context_id": args.context_id,
                    "view_id": view_id,
                    "backend_cursor": backend_cursor,
                    "delivered": delivered,
                },
            )
            if backend_cursor
            else None
        )
        return {
            "ok": True,
            "command": "list",
            "publications": publications,
            "has_more": backend_cursor is not None,
            "next_cursor": next_cursor,
            "scan_truncated": scan_truncated,
        }

    def read_context(args: JsContextArgs) -> dict:
        if not args.context_id or not args.selector:
            return _invalid()
        if selection is not None:
            if selection.status != "published":
                return selected_result({"ok": False, "error": "missing"})
            if args.context_id != selection.context_id:
                return selected_result({"ok": False, "error": "missing"})
            selected_selector = (
                selection.producing_run_id
                if args.selector == "current"
                else args.selector
            )
            if selected_selector != selection.producing_run_id:
                return selected_result(
                    {"ok": False, "error": "run_mismatch"}
                )
            args = args.model_copy(
                update={"selector": selection.producing_run_id}
            )
        if args.selector != "current":
            try:
                validate_path_component(args.selector, "selector")
            except ValueError:
                return _invalid()
        cursor_state = None
        if args.cursor:
            try:
                cursor_state = _decode_cursor(project_id, args.cursor)
            except ValueError:
                return {"ok": False, "error": "invalid_cursor"}
            common = {
                "context_id": args.context_id,
                "selector": args.selector,
                "section": args.section,
            }
            if any(cursor_state.get(key) != value for key, value in common.items()):
                return {"ok": False, "error": "invalid_cursor"}
            if args.section in {"behaviors", "evidence"} and set(
                cursor_state
            ) != {
                "version",
                "command",
                "context_id",
                "selector",
                "section",
                "snapshot",
                "run_id",
                "backend_cursor",
            }:
                return {"ok": False, "error": "invalid_cursor"}

        if args.section == "context":
            try:
                page = seam.read(
                    project_id=project_id,
                    context_id=args.context_id,
                    selector=args.selector,
                    section="context",
                )
            except (OSError, JsContextStoreError, ValueError):
                return {"ok": False, "error": "store_unavailable"}
            if page.get("status") != "ok":
                return _store_error(str(page.get("status")))
            publication = _compact_publication(page["publication"])
            context = _compact_context(page["context"])
            run_id = page["selector"]["run_id"]
            snapshot = publication["document_sha256"]
            gaps = list(page["context"]["coverage"]["gaps"])
            offset = 0
            if cursor_state:
                if (
                    set(cursor_state)
                    != {
                        "version",
                        "command",
                        "context_id",
                        "selector",
                        "section",
                        "snapshot",
                        "run_id",
                        "offset",
                    }
                    or cursor_state["command"] != "read"
                    or cursor_state["section"] != "context"
                    or cursor_state["run_id"] != run_id
                    or cursor_state["snapshot"] != snapshot
                ):
                    return {"ok": False, "error": "stale_cursor"}
                offset = cursor_state["offset"]
                if not isinstance(offset, int) or offset < 0 or offset > len(gaps):
                    return {"ok": False, "error": "invalid_cursor"}
            selected = []
            while len(selected) < args.limit and offset + len(selected) < len(gaps):
                gap = gaps[offset + len(selected)]
                next_offset = offset + len(selected) + 1
                next_cursor = (
                    _encode_cursor(
                        project_id,
                        {
                            "version": 1,
                            "command": "read",
                            "context_id": args.context_id,
                            "selector": args.selector,
                            "section": "context",
                            "snapshot": snapshot,
                            "run_id": run_id,
                            "offset": next_offset,
                        },
                    )
                    if next_offset < len(gaps)
                    else None
                )
                candidate = {
                    "ok": True,
                    "command": "read",
                    "context_id": args.context_id,
                    "selector": {"kind": "current" if args.selector == "current" else "run", "run_id": run_id},
                    "section": "context",
                    "context": context,
                    "publication": publication,
                    "gaps": [*selected, gap],
                    "gap_page": {
                        "returned": len(selected) + 1,
                        "total": len(gaps),
                        "next_cursor": next_cursor,
                    },
                }
                if _json_bytes(candidate) > MAX_RESPONSE_BYTES:
                    if not selected:
                        return {"ok": False, "error": "record_too_large"}
                    break
                selected.append(gap)
            next_offset = offset + len(selected)
            next_cursor = (
                _encode_cursor(
                    project_id,
                    {
                        "version": 1,
                        "command": "read",
                        "context_id": args.context_id,
                        "selector": args.selector,
                        "section": "context",
                        "snapshot": snapshot,
                        "run_id": run_id,
                        "offset": next_offset,
                    },
                )
                if next_offset < len(gaps)
                else None
            )
            return {
                "ok": True,
                "command": "read",
                "context_id": args.context_id,
                "selector": {"kind": "current" if args.selector == "current" else "run", "run_id": run_id},
                "section": "context",
                "context": context,
                "publication": publication,
                "gaps": selected,
                "gap_page": {
                    "returned": len(selected),
                    "total": len(gaps),
                    "next_cursor": next_cursor,
                },
            }

        if args.section == "metadata":
            if cursor_state:
                return {"ok": False, "error": "invalid_cursor"}
            try:
                page = seam.read(
                    project_id=project_id,
                    context_id=args.context_id,
                    selector=args.selector,
                    section="metadata",
                )
            except (OSError, JsContextStoreError, ValueError):
                return {"ok": False, "error": "store_unavailable"}
            if page.get("status") != "ok":
                return _store_error(str(page.get("status")))
            return {
                "ok": True,
                "command": "read",
                "context_id": args.context_id,
                "selector": page["selector"],
                "section": "metadata",
                "context": _compact_context(page["context"]),
                "publication": _compact_publication(page["publication"]),
            }

        backend_cursor = (
            cursor_state["backend_cursor"] if cursor_state else None
        )
        expected_snapshot = cursor_state["snapshot"] if cursor_state else None
        expected_run = cursor_state["run_id"] if cursor_state else None
        items = []
        base = None
        while len(items) < args.limit:
            try:
                page = seam.read(
                    project_id=project_id,
                    context_id=args.context_id,
                    selector=args.selector,
                    section=args.section,
                    limit=1,
                    cursor=backend_cursor,
                )
            except ValueError:
                return {
                    "ok": False,
                    "error": (
                        "stale_cursor" if cursor_state else "store_unavailable"
                    ),
                }
            except (OSError, JsContextStoreError):
                return {"ok": False, "error": "store_unavailable"}
            if page.get("status") != "ok":
                return _store_error(str(page.get("status")))
            publication = _compact_publication(page["publication"])
            run_id = page["selector"]["run_id"]
            snapshot = publication["document_sha256"]
            if expected_snapshot is None:
                expected_snapshot = snapshot
                expected_run = run_id
            elif snapshot != expected_snapshot or run_id != expected_run:
                return {"ok": False, "error": "stale_cursor"}
            base = {
                "ok": True,
                "command": "read",
                "context_id": args.context_id,
                "selector": page["selector"],
                "section": args.section,
                "publication": publication,
            }
            page_items = page.get("items") or []
            if not page_items:
                backend_cursor = None
                break
            item = page_items[0]
            after_cursor = page.get("next_cursor")
            candidate_cursor = (
                _encode_cursor(
                    project_id,
                    {
                        "version": 1,
                        "command": "read",
                        "context_id": args.context_id,
                        "selector": args.selector,
                        "section": args.section,
                        "snapshot": expected_snapshot,
                        "run_id": expected_run,
                        "backend_cursor": after_cursor,
                    },
                )
                if after_cursor
                else None
            )
            candidate = {
                **base,
                "items": [*items, item],
                "has_more": after_cursor is not None,
                "next_cursor": candidate_cursor,
            }
            if _json_bytes(candidate) > MAX_RESPONSE_BYTES:
                if not items:
                    return {"ok": False, "error": "record_too_large"}
                break
            items.append(item)
            backend_cursor = after_cursor
            if backend_cursor is None:
                break
        if base is None:
            return {"ok": False, "error": "store_unavailable"}
        next_cursor = (
            _encode_cursor(
                project_id,
                {
                    "version": 1,
                    "command": "read",
                    "context_id": args.context_id,
                    "selector": args.selector,
                    "section": args.section,
                    "snapshot": expected_snapshot,
                    "run_id": expected_run,
                    "backend_cursor": backend_cursor,
                },
            )
            if backend_cursor
            else None
        )
        return {
            **base,
            "items": items,
            "has_more": backend_cursor is not None,
            "next_cursor": next_cursor,
        }

    def invoke(
        command: Literal["list", "read"],
        context_id: str | None = None,
        selector: str | None = None,
        section: Literal[
            "metadata", "context", "behaviors", "evidence"
        ] = "metadata",
        limit: int = DEFAULT_LIMIT,
        cursor: str | None = None,
    ) -> dict:
        args = JsContextArgs(
            command=command,
            context_id=context_id,
            selector=selector,
            section=section,
            limit=limit,
            cursor=cursor,
        )
        result = list_context(args) if command == "list" else read_context(args)
        return selected_result(result) if selection is not None else result

    def validation_error(_error) -> dict:
        return _invalid()

    return StructuredTool.from_function(
        func=invoke,
        name="js_context",
        description=JS_CONTEXT_CONTRACT,
        args_schema=JsContextArgs,
        handle_validation_error=validation_error,
    )


__all__ = [
    "DEFAULT_LIMIT",
    "JS_CONTEXT_CONTRACT",
    "MAX_LIMIT",
    "MAX_RESPONSE_BYTES",
    "build_js_context_tool",
]
