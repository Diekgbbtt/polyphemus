"""Native hunting admission for a workflow-bound published JS context."""

from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass

from polymerhus.app.js_context.selection import JsContextInput

_selection_context: contextvars.ContextVar[JsContextInput | None] = (
    contextvars.ContextVar("hunting_js_context_selection", default=None)
)


class JsContextAdmissionError(RuntimeError):
    """A coded refusal before a hunting run may open or schedule."""

    def __init__(
        self,
        code: str,
        *,
        gaps: list[str] | tuple[str, ...] = (),
    ) -> None:
        super().__init__(code)
        self.code = code
        self.gaps = tuple(gaps)

    def as_dict(self) -> dict:
        return {"code": self.code, "gaps": list(self.gaps)}


@dataclass(frozen=True)
class JsContextAdmission:
    selection: JsContextInput
    summary: dict


def current_js_context_selection() -> JsContextInput | None:
    """The fixed selection bound to the current hunting execution."""
    return _selection_context.get()


@contextlib.contextmanager
def js_context_selection_scope(selection: JsContextInput | None):
    """Expose one frozen selection to every task created by the hunting run."""
    token = _selection_context.set(selection)
    try:
        yield selection
    finally:
        _selection_context.reset(token)


def _refuse(code: str, gaps=()) -> None:
    raise JsContextAdmissionError(code, gaps=gaps)


def resolve_js_context_admission(
    project_id: str,
    producing_run_id: str | None,
    *,
    pg_module=None,
    expected_input_id: str | None = None,
    hunting_run: dict | None = None,
    store=None,
) -> JsContextAdmission | None:
    """Resolve zero/one active JS workflow and validate its frozen settlement.

    No active workflow means the launch keeps legacy unbound semantics. Multiple
    active workflows require an explicit producer; there is no latest-run
    fallback.
    """
    if pg_module is None:
        from polymerhus.app.clients import pg as pg_module  # noqa: PLC0415

    frozen = None
    if hunting_run is not None:
        if hunting_run.get("project_id") != project_id:
            _refuse("js_context_project_mismatch", ["hunting_run_foreign"])
        stats = hunting_run.get("stats") or {}
        if not isinstance(stats, dict):
            _refuse("js_context_selection_invalid")
        # Absence is legacy. A present but invalid/null selection is a refusal.
        if "js_context_selection" not in stats:
            if expected_input_id is not None:
                _refuse("js_context_application_changed", ["js_context_selection_missing"])
            return None
        try:
            frozen = JsContextInput.from_dict(stats["js_context_selection"])
        except (ValueError, TypeError):
            _refuse("js_context_selection_invalid")
        if frozen.project_id != project_id:
            _refuse("js_context_project_mismatch", ["selection_foreign"])
        if producing_run_id not in (None, frozen.producing_run_id):
            _refuse("js_context_application_changed", ["stale_js_context_application"])
        if expected_input_id not in (None, frozen.input_id):
            _refuse("js_context_application_changed", ["stale_js_context_application"])
        producing_run_id = frozen.producing_run_id
        expected_input_id = frozen.input_id

    selected_run = producing_run_id
    if selected_run is None:
        list_producers = getattr(
            pg_module,
            "list_active_js_context_producers",
            None,
        )
        if not callable(list_producers):
            return None
        producers = list(list_producers(project_id))
        if not producers:
            return None
        if len(producers) > 1:
            _refuse("ambiguous_producing_run", ["multiple_js_workflows"])
        selected_run = producers[0]

    run = pg_module.get_run(selected_run)
    if not isinstance(run, dict):
        _refuse("producing_run_not_found", ["js_context_analysis_missing"])
    if run.get("project_id") != project_id:
        _refuse("js_context_project_mismatch", ["producing_run_foreign"])
    if run.get("status") in {"failed", "stopped", "cancelled"}:
        _refuse("producing_run_not_active", ["producing_run_terminal_failure"])

    summary = (run.get("stats") or {}).get("js_context_application")
    if not isinstance(summary, dict):
        _refuse("js_context_analysis_missing", ["analysis_not_started"])
    if (
        summary.get("project_id") != project_id
        or summary.get("producing_run_id") != selected_run
    ):
        _refuse("js_context_application_scope_mismatch")
    selection_value = summary.get("selection")
    if not isinstance(selection_value, dict):
        _refuse(
            "js_context_selection_missing",
            ["js_context_selection_not_frozen"],
        )
    try:
        selection = JsContextInput.from_dict(selection_value)
    except (ValueError, TypeError):
        _refuse(
            "js_context_selection_invalid",
            ["js_context_selection_not_frozen"],
        )
    if (
        selection.project_id != project_id
        or selection.producing_run_id != selected_run
        or summary.get("input_id") != selection.input_id
    ):
        _refuse("js_context_application_scope_mismatch")
    if expected_input_id is not None and expected_input_id != selection.input_id:
        _refuse("js_context_application_changed", ["stale_js_context_application"])

    status = summary.get("status")
    if status not in {
        "settled_success",
        "settled_gap",
        "not_applicable",
    }:
        _refuse(
            "js_context_not_ready",
            [str(status or "application_pending"), *list(summary.get("gaps") or [])],
        )
    if frozen is not None and frozen.status == "published":
        from polymerhus.app.js_context.store import JsContextStore  # noqa: PLC0415

        seam = store if store is not None else JsContextStore()
        try:
            result = seam.read(
                project_id=project_id,
                context_id=frozen.context_id,
                selector=frozen.producing_run_id,
                expected_document_id=frozen.document_id,
                expected_sha256=frozen.document_sha256,
            )
        except (ValueError, OSError):
            _refuse("js_context_document_unavailable")
        document_status = result.get("status")
        if document_status != "ok":
            _refuse("js_context_document_unavailable", [
                {
                    "missing": "js_context_document_missing",
                    "corrupt": "js_context_document_corrupt",
                    "document_mismatch": "js_context_document_mismatch",
                    "run_mismatch": "js_context_document_scope_mismatch",
                }.get(document_status, "js_context_document_unavailable")
            ])
        context = result["context"]
        if (
            context["auth_ref"] != frozen.auth_ref
            or context["origin"] != frozen.origin.as_dict()
        ):
            _refuse("js_context_document_scope_mismatch")
    return JsContextAdmission(selection=selection, summary=summary)


__all__ = [
    "JsContextAdmission",
    "JsContextAdmissionError",
    "current_js_context_selection",
    "js_context_selection_scope",
    "resolve_js_context_admission",
]
