"""The real run loop: frontier + element map + command mapper + capture + ledger.

Spec: `docs/design/steel-crawl-spec.md` sections 5, 6, 8, 9, 10.4, and 11.

`CrawlRun` is the production wiring of the pieces the earlier tickets built. It
projects each cached snapshot through the element map, executes through the
command mapper, lets the Jev policy choose, captures the flows, collects removed
forms as declared endpoints, submits a live form at most once per state, and
appends every normalized artifact to the run ledger. It does not own the
lifecycle (the job does) or the manifest shape (the SC-14 writer does); its
output is the evidence the job finalizes.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from polymerhus.recon.crawl.steel.capture.flow import Flow
from polymerhus.recon.crawl.steel.capture.history import (
    CaptureContext,
    HttpArtifact,
    normalize_cdp_flow,
)
from polymerhus.recon.crawl.steel.capture.sidecar import CaptureSidecar
from polymerhus.recon.crawl.steel.command import Action, CommandMapper
from polymerhus.recon.crawl.steel.enumerate import Element, ElementMap, ElementType
from polymerhus.recon.crawl.steel.forms import DeclaredCollector, FormExecutor, FormLedger
from polymerhus.recon.crawl.steel.frontier import (
    ExecutionResult,
    Frontier,
    FrontierResult,
)
from polymerhus.recon.crawl.steel.ledger import RunLedger
from polymerhus.recon.crawl.steel.parameters import (
    DeclaredEndpoint,
    DeclaredField,
    FormContract,
    ObservedParameter,
    extract_parameters,
)
from polymerhus.recon.crawl.steel.policy.port import Policy
from polymerhus.recon.crawl.steel.session import SteelSessionClient
from polymerhus.recon.crawl.steel.state import (
    BrowserState,
    PageInstance,
    SnapshotFacts,
    normalize_url,
)

PageFactory = Callable[
    [str, PageInstance | None, int, str, tuple[str, ...]], PageInstance
]


@dataclass(frozen=True)
class FormOutcome:
    """One form the run saw: submitted once, skipped, or rejected."""

    form: FormContract | None
    submitted: bool
    skipped: str | None = None


@dataclass(frozen=True)
class RunOutput:
    """The evidence one run produced for the job's finalize."""

    frontier: FrontierResult
    flows: tuple[Flow, ...] = ()
    artifacts: tuple[tuple[HttpArtifact, dict[str, bytes]], ...] = ()
    flow_artifacts: Mapping[str, str] = field(default_factory=dict)
    parameters: tuple[ObservedParameter, ...] = ()
    removed: tuple[Element, ...] = ()
    forms: tuple[FormOutcome, ...] = ()
    declared_endpoints: tuple[DeclaredEndpoint, ...] = ()
    declared_fields: tuple[DeclaredField, ...] = ()


class CrawlRun:
    """The real traversal wiring, with the browser and the policy injected."""

    def __init__(
        self,
        *,
        project_id: str,
        capture_context: CaptureContext | None,
        session: SteelSessionClient,
        state: BrowserState,
        sidecar: CaptureSidecar,
        policy: Policy,
        mapper: CommandMapper,
        element_map: ElementMap,
        ledger: RunLedger,
        form_ledger: FormLedger,
        page_factory: PageFactory,
        navigate: Callable[[str], None],
        submit_form: Callable[[PageInstance, Element], Any],
        in_scope: Callable[[str], bool],
        deadline: Callable[[], bool],
        cancel: Callable[[], bool],
        form_executor: FormExecutor | None = None,
        recapture: Callable[[PageInstance], tuple[Any, SnapshotFacts]] | None = None,
    ) -> None:
        self._project_id = project_id
        self._capture_context = capture_context
        self._session = session
        self._state = state
        self._sidecar = sidecar
        self._policy = policy
        self._mapper = mapper
        self._element_map = element_map
        self._ledger = ledger
        self._form_ledger = form_ledger
        self._page_factory = page_factory
        self._navigate = navigate
        self._submit_form = submit_form
        self._in_scope = in_scope
        self._deadline = deadline
        self._cancel = cancel
        self._form_executor = form_executor
        self._recapture = recapture
        self._collector = _Collector(self)
        self._forms: list[FormOutcome] = []
        self._actions: list[Element] = []
        self._declared: dict[str, DeclaredCollector] = {}
        self._seen_flows: set[str] = set()
        self._current_page: PageInstance | None = None
        self.last_output: RunOutput | None = None

    def run(self, root: PageInstance) -> RunOutput:
        """Traverse from the loaded root and return the captured evidence."""
        return self.run_many((root,))

    def run_many(self, roots: Sequence[PageInstance]) -> RunOutput:
        """Traverse every loaded seed in order and return the captured evidence.

        The seeds share one browser state and one capture sidecar, so a public
        root and the authenticated auth-probe entry form one run with one flow
        ledger and one deduplicated visited set.
        """
        frontier = Frontier(
            project=self._project,
            restore=self._restore,
            execute=self._execute,
            policy=self._policy,
            state=self._state,
            collector=self._collector,
            deadline=self._deadline,
            cancel=self._cancel,
            in_scope=self._in_scope,
        )
        result = frontier.run_many(roots)
        self._sidecar.pump()
        artifacts: list[tuple[HttpArtifact, dict[str, bytes]]] = []
        flow_artifacts: dict[str, str] = {}
        parameters: list[ObservedParameter] = []
        for flow in self._sidecar.flows:
            if flow.request_id in self._seen_flows:
                continue
            self._seen_flows.add(flow.request_id)
            artifact, bodies = normalize_cdp_flow(
                flow,
                project_id=self._project_id,
                capture_context=self._capture_context,
            )
            self._ledger.append_artifact(artifact, bodies)
            artifacts.append((artifact, bodies))
            flow_artifacts[flow.request_id] = artifact.artifact_id
            parameters.extend(extract_parameters(_parameter_flow(flow)))
        declared_endpoints = tuple(
            endpoint for collector in self._declared.values() for endpoint in collector.endpoints
        )
        declared_fields = tuple(
            field for collector in self._declared.values() for field in collector.fields
        )
        output = RunOutput(
            frontier=result,
            flows=self._sidecar.flows,
            artifacts=tuple(artifacts),
            flow_artifacts=flow_artifacts,
            parameters=tuple(parameters),
            removed=result.removed,
            forms=tuple(self._forms),
            declared_endpoints=declared_endpoints,
            declared_fields=declared_fields,
        )
        self.last_output = output
        return output

    def _project(self, page: PageInstance) -> Sequence[Element]:
        self._current_page = page
        return self._element_map.project(
            self._state.cached(page).snapshot,
            page=page,
            state=self._state,
            page_url=page.final_url or page.url,
        )

    def _restore(self, page: PageInstance) -> None:
        self._sidecar.set_context(page.page_visit_id)
        self._state.restore(page, self._navigate)
        if self._recapture is not None:
            snapshot, facts = self._recapture(page)
            self._state.replace_snapshot(page, snapshot, facts)

    def _execute(self, page: PageInstance, element: Element) -> ExecutionResult:
        action_id = f"act_{len(self._actions) + 1}"
        self._actions.append(element)
        self._sidecar.set_context(page.page_visit_id, action_id)
        try:
            if element.element_type is ElementType.FORM:
                self._forms.append(self._submit(page, element))
            else:
                self._mapper.execute(self._action(page, element), page)
            self._sidecar.pump()
        finally:
            self._sidecar.clear_context()
        url = self._current_url()
        if (
            url
            and normalize_url(url) != normalize_url(page.final_url or page.url)
            and self._in_scope(url)
        ):
            child = self._page_factory(
                url,
                page,
                page.depth + 1,
                "action",
                page.navigation_path + (element.fingerprint,),
            )
            return ExecutionResult(
                navigated=True,
                page=child,
                url=url,
                title=child.title,
                status=child.status,
            )
        return ExecutionResult(navigated=False, url=url)

    def _action(self, page: PageInstance, element: Element) -> Action:
        if element.element_type in {
            ElementType.LINK,
            ElementType.AREA,
            ElementType.META_REFRESH,
            ElementType.IFRAME,
            ElementType.FRAME,
        }:
            return Action(
                verb="navigate",
                impact=element.impact,
                capture=element.capture,
                document_generation=self._state.current_generation,
                value=element.change.action
                or element.change.target
                or element.href
                or element.action
                or "",
                args=("--wait-until", "domcontentloaded"),
            )
        return Action(
            verb="click",
            impact=element.impact,
            capture=element.capture,
            document_generation=self._state.current_generation,
            selector=element.selector,
        )

    def _submit(self, page: PageInstance, element: Element) -> FormOutcome:
        form = element.form
        if form is None:
            return FormOutcome(form=None, submitted=False, skipped="no_contract")
        if self._form_executor is not None:
            submission = self._form_executor.submit(
                page, element, generation=self._state.current_generation
            )
            return FormOutcome(
                form=form,
                submitted=submission.submitted,
                skipped=submission.skipped,
            )
        if not self._form_ledger.should_submit(form, page.state_key):
            return FormOutcome(form=form, submitted=False, skipped="duplicate")
        self._submit_form(page, element)
        self._form_ledger.mark_submitted(form, page.state_key)
        return FormOutcome(form=form, submitted=True)

    @property
    def action_count(self) -> int:
        """How many candidates the run has executed, for the test cap."""
        return len(self._actions)

    def _current_url(self) -> str:
        envelope = self._session.execute("get", "url")
        data = envelope.get("data")
        if isinstance(data, Mapping):
            return str(data.get("url") or "")
        if isinstance(data, str):
            return data
        return ""

    def _declared_for(self, page: PageInstance) -> DeclaredCollector:
        collector = self._declared.get(page.page_visit_id)
        if collector is None:
            collector = DeclaredCollector(page)
            self._declared[page.page_visit_id] = collector
        return collector


class _Collector:
    """The page-aware adapter the frontier's removal stage calls."""

    def __init__(self, run: CrawlRun) -> None:
        self._run = run

    def collect(self, element: Element) -> None:
        page = self._run._current_page
        if page is not None:
            self._run._declared_for(page).collect(element)


def _parameter_flow(flow: Flow) -> dict[str, Any]:
    """The observed-parameter view of one captured flow."""
    return {
        "flow_id": flow.request_id,
        "method": flow.method,
        "url": flow.url,
        "request_body": flow.request_body or "",
        "content_type": _header(flow.request_headers, "content-type")
        or _header(flow.response_headers, "content-type"),
    }


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for header, value in headers.items():
        if header.lower() == name:
            return value
    return None


__all__ = [
    "CrawlRun",
    "FormOutcome",
    "RunOutput",
]
