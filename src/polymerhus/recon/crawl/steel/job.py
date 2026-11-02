"""The crawl job lifecycle: attach, authenticate, capture, traverse, finalize.

Spec: `docs/design/steel-crawl-spec.md` sections 2.1, 10.4, 12, and 13.

The job owns the run lifecycle and nothing else: it attaches to the
pre-authenticated session (it never starts one), runs the auth oracle once,
starts the passive capture, hands the loaded root to the traversal, emits the
page and action records to the observability sink, and finalizes on success and
on every failure. The traversal, the manifest, and the HTTP flush are injected,
so the lifecycle is testable without a browser, a provider, or an edge.

No log line carries the connect URL, cookies, storage values, or credentials:
the job logs only the run id, the stop reason, and the terminal status.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict

from polymerhus.recon.crawl.steel.auth import (
    AuthPreconditionFailed,
    AuthVerdict,
)
from polymerhus.recon.crawl.steel.capture.history import HttpArtifact
from polymerhus.recon.crawl.steel.capture.sidecar import (
    CaptureSidecar,
    CaptureUnavailable,
)
from polymerhus.recon.crawl.steel.frontier import FrontierResult
from polymerhus.recon.crawl.steel.ledger import FinalizeResult, RunLedger, finalize
from polymerhus.recon.crawl.steel.manifest import Manifest
from polymerhus.recon.crawl.steel.session import (
    SessionMissing,
    SteelSessionClient,
    SteelSessionError,
)
from polymerhus.recon.crawl.steel.state import PageInstance

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class PageRecord(BaseModel):
    """One observability page record (spec 13); the manifest references its id."""

    model_config = ConfigDict(frozen=True)

    page_visit_id: str
    url: str
    final_url: str
    status: int | None = None
    title: str = ""
    parent_id: str | None = None
    depth: int = 0
    discovery_source: str = ""
    state_key: str = ""
    document_generation: int = 0


class ActionRecord(BaseModel):
    """One observability action record (spec 13)."""

    model_config = ConfigDict(frozen=True)

    action_id: str
    page_id: str
    element_id: str
    element_type: str
    impact: str
    capture: str
    outcome: str
    error: str | None = None


@dataclass(frozen=True)
class JobResult:
    """The run's terminal state and the records it emitted."""

    status: str
    stop_reason: str
    manifest: Manifest
    finalize: FinalizeResult
    pages: tuple[PageRecord, ...] = ()
    actions: tuple[ActionRecord, ...] = ()
    error: str | None = None

    @property
    def partial(self) -> bool:
        return self.status == "partial"


PrepareFn = Callable[[], PageInstance]
AuthFn = Callable[[PageInstance], AuthVerdict]
RunFn = Callable[[PageInstance], FrontierResult]
ManifestFn = Callable[[FrontierResult | None, str], Manifest]
FlushFn = Callable[
    [Sequence[tuple[HttpArtifact, dict[str, bytes]]]], Mapping[str, Any]
]
IngestFn = Callable[[Manifest], Any]
RecordPageFn = Callable[[PageRecord], None]
RecordActionFn = Callable[[ActionRecord], None]


@dataclass(frozen=True)
class BoundaryResult:
    """The outcome of one bounded session-loss recovery attempt."""

    result: JobResult
    retries: int = 0
    resurrection_requested: bool = False


class CrawlJob:
    """One authenticated crawl's lifecycle, with every side effect injected."""

    def __init__(
        self,
        *,
        run_id: str,
        session_name: str,
        project_id: str,
        account: str | None,
        session: SteelSessionClient,
        sidecar: CaptureSidecar,
        ledger: RunLedger,
        prepare_fn: PrepareFn,
        auth_fn: AuthFn,
        run_fn: RunFn,
        manifest_fn: ManifestFn,
        flush_fn: FlushFn,
        ingest_fn: IngestFn,
        record_page: RecordPageFn | None = None,
        record_action: RecordActionFn | None = None,
        coverage: Mapping[str, Any] | None = None,
        deadline: Callable[[], bool] | None = None,
        cancel: Callable[[], bool] | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._run_id = run_id
        self._session_name = session_name
        self._project_id = project_id
        self._account = account
        self._session = session
        self._sidecar = sidecar
        self._ledger = ledger
        self._prepare_fn = prepare_fn
        self._auth_fn = auth_fn
        self._run_fn = run_fn
        self._manifest_fn = manifest_fn
        self._flush_fn = flush_fn
        self._ingest_fn = ingest_fn
        self._record_page = record_page or (lambda record: None)
        self._record_action = record_action or (lambda record: None)
        self._coverage = dict(coverage or {})
        self._deadline = deadline or (lambda: False)
        self._cancel = cancel or (lambda: False)
        self._clock = clock or _utcnow
        self._sidecar_attached = False

    def run(self) -> JobResult:
        """Attach, authenticate, capture, traverse, and finalize on every exit."""
        try:
            self._session.attach(self._session_name)
        except Exception as exc:  # noqa: BLE001 - every failure is a typed stop
            return self._finish(_stop_reason(exc), str(exc), None)

        if self._cancel():
            return self._finish("operator_cancel", None, None)
        if self._deadline():
            return self._finish("session_deadline", None, None)

        try:
            root = self._prepare_fn()
            self._auth_fn(root)
        except AuthPreconditionFailed as exc:
            return self._finish("auth_precondition_failed", str(exc), None)
        except Exception as exc:  # noqa: BLE001 - a load failure is a typed stop
            return self._finish(_stop_reason(exc), str(exc), None)

        try:
            self._sidecar.attach()
            self._sidecar_attached = True
        except Exception as exc:  # noqa: BLE001 - capture must not be a false success
            return self._finish("capture_unavailable", str(exc), None)

        try:
            frontier = self._run_fn(root)
        except Exception as exc:  # noqa: BLE001 - the run ends with its own reason
            return self._finish(_stop_reason(exc), str(exc), None)

        return self._finish(
            frontier.stop_reason, frontier.error, frontier
        )

    def _finish(
        self,
        stop_reason: str,
        error: str | None,
        frontier: FrontierResult | None,
    ) -> JobResult:
        pages, actions = self._records(frontier)
        manifest = self._manifest_fn(frontier, stop_reason)
        result = finalize(
            ledger=self._ledger,
            manifest=manifest,
            stop_reason=stop_reason,
            finished_at=self._clock(),
            flush_fn=self._flush_fn,
            ingest_fn=self._ingest_fn,
            close_fn=self._sidecar.close if self._sidecar_attached else None,
            coverage=self._coverage,
        )
        logger.info(
            "crawl job %s stopped: %s (%s)",
            self._run_id,
            stop_reason,
            result.status,
        )
        return JobResult(
            status=result.status,
            stop_reason=stop_reason,
            manifest=result.manifest,
            finalize=result,
            pages=pages,
            actions=actions,
            error=error,
        )

    def _records(
        self, frontier: FrontierResult | None
    ) -> tuple[tuple[PageRecord, ...], tuple[ActionRecord, ...]]:
        if frontier is None:
            return (), ()
        pages: list[PageRecord] = []
        for visit in frontier.page_visits:
            page = visit.page
            record = PageRecord(
                page_visit_id=page.page_visit_id,
                url=page.url,
                final_url=page.final_url,
                status=page.status,
                title=page.title,
                parent_id=visit.parent.page_visit_id if visit.parent else None,
                depth=page.depth,
                discovery_source=page.discovery_source,
                state_key=page.state_key,
                document_generation=page.document_generation,
            )
            pages.append(record)
            _emit(self._record_page, record)
        actions: list[ActionRecord] = []
        for index, visit in enumerate(frontier.action_visits, start=1):
            element = visit.element
            record = ActionRecord(
                action_id=f"act_{index}",
                page_id=visit.page.page_visit_id,
                element_id=element.element_id,
                element_type=element.element_type.value,
                impact=element.impact,
                capture=element.capture,
                outcome="ok",
            )
            actions.append(record)
            _emit(self._record_action, record)
        for index, stale in enumerate(frontier.stale, start=len(actions) + 1):
            element = stale.element
            record = ActionRecord(
                action_id=f"act_{index}",
                page_id=stale.page.page_visit_id,
                element_id=element.element_id,
                element_type=element.element_type.value,
                impact=element.impact,
                capture=element.capture,
                outcome="error",
                error=stale.error.code,
            )
            actions.append(record)
            _emit(self._record_action, record)
        return tuple(pages), tuple(actions)


def _emit(sink: Callable[[Any], None], record: Any) -> None:
    """A failing observability sink never loses the run or the ledger."""
    try:
        sink(record)
    except Exception as exc:  # noqa: BLE001 - observability is best-effort
        logger.warning("observability record dropped: %s", exc)


def _stop_reason(error: BaseException) -> str:
    """Map a typed exception to the run's stop reason, or a generic error."""
    code = getattr(error, "code", "")
    if isinstance(error, SessionMissing) or code == "session_missing":
        return "session_missing"
    if isinstance(error, AuthPreconditionFailed) or code == "auth_precondition_failed":
        return "auth_precondition_failed"
    if isinstance(error, CaptureUnavailable) or code == "capture_unavailable":
        return "capture_unavailable"
    if isinstance(error, SteelSessionError):
        return "error"
    return "error"


__all__ = [
    "ActionRecord",
    "BoundaryResult",
    "CrawlJob",
    "JobResult",
    "PageRecord",
    "run_with_session_boundary",
]


def run_with_session_boundary(
    job_factory: Callable[[], CrawlJob],
    *,
    resurrect_fn: Callable[[], bool],
    max_retries: int = 1,
) -> BoundaryResult:
    """Run a job, and after `session_missing` request one bounded resurrection.

    The crawl never starts or recreates a session itself. It returns the typed
    failure to the orchestrator, which owns the auth store and the state restore;
    only after that owner reports success does the boundary build one new job and
    try again. A second `session_missing` stops with the typed result, so there is
    no retry loop. The failed job has already finalized its partial run.
    """
    retries = 0
    requested = False
    while True:
        result = job_factory().run()
        if result.stop_reason != "session_missing" or retries >= max_retries:
            return BoundaryResult(
                result=result,
                retries=retries,
                resurrection_requested=requested,
            )
        requested = True
        if not resurrect_fn():
            return BoundaryResult(
                result=result,
                retries=retries + 1,
                resurrection_requested=True,
            )
        retries += 1
