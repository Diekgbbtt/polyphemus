"""Seam under test: the real run loop through a fake session, CDP, and policy.

Spec: `docs/design/steel-crawl-spec.md` sections 5, 6, 8, 9, 10.4, and 11; seam
10 of `docs/design/steel-crawl-implementation-plan.md` section 3.

The test drives the real `CrawlRun`, `Frontier`, `ElementMap`, `CommandMapper`,
`CaptureSidecar`, `normalize_cdp_flow`, `DeclaredCollector`, and `FormLedger`
against a two-page fake application. The session is a real `SteelSessionClient`
with an injected command executor; the CDP side is the fixture stream; the
policy is a queue. It proves the routes, the one-form rule, the removed form,
the captured artifact, the observed parameter, the declared endpoint, and the
job's finalize together.
"""
from __future__ import annotations

from typing import Any

from polymerhus.recon.crawl.steel.auth import AuthVerdict
from polymerhus.recon.crawl.steel.capture.history import CaptureContext
from polymerhus.recon.crawl.steel.capture.sidecar import CaptureSidecar
from polymerhus.recon.crawl.steel.command import Action, CommandMapper
from polymerhus.recon.crawl.steel.enumerate import ElementMap, SnapshotNode
from polymerhus.recon.crawl.steel.forms import FormLedger
from polymerhus.recon.crawl.steel.job import CrawlJob
from polymerhus.recon.crawl.steel.ledger import RunLedger
from polymerhus.recon.crawl.steel.manifest import RunBlock, build_manifest
from polymerhus.recon.crawl.steel.run import CrawlRun
from polymerhus.recon.crawl.steel.session import SteelSessionClient
from polymerhus.recon.crawl.steel.state import BrowserState
from tests.recon.crawl.steel.fixtures import load_cdp, load_cli
from tests.recon.crawl.steel.support import FakeCdpTransport, FakeDecisionClient

ROOT = "https://example.test/"
A = "https://example.test/a"
TITLES = {ROOT: "Root", A: "A"}

ROOT_NODES = (
    SnapshotNode(
        tag="form",
        ref="e1",
        role="form",
        name="Delete",
        attributes={"action": "/delete", "method": "get"},
        children=(
            SnapshotNode(
                tag="input",
                ref="e1f",
                name="id",
                attributes={"type": "text", "name": "id"},
            ),
            SnapshotNode(
                tag="button",
                ref="e1s",
                name="Delete",
                attributes={"type": "submit"},
            ),
        ),
    ),
    SnapshotNode(
        tag="form",
        ref="e2",
        role="form",
        name="Search",
        attributes={"action": "/search", "method": "get"},
        children=(
            SnapshotNode(
                tag="input",
                ref="e2f",
                name="Query",
                attributes={"type": "text", "name": "q"},
            ),
            SnapshotNode(
                tag="button",
                ref="e2s",
                name="Search",
                attributes={"type": "submit"},
            ),
        ),
    ),
    SnapshotNode(
        tag="button",
        ref="e3",
        name="Refresh",
        attributes={"type": "button", "onclick": "refresh()"},
    ),
    SnapshotNode(
        tag="a",
        ref="e4",
        role="link",
        name="A",
        attributes={"href": "/a"},
    ),
)

A_NODES = (
    SnapshotNode(
        tag="button",
        ref="a1",
        name="Done",
        attributes={"type": "button"},
    ),
)

SNAPSHOTS = {ROOT: ROOT_NODES, A: A_NODES}


class AppExec:
    """A two-page fake browser behind the real session command builder."""

    def __init__(self) -> None:
        self.current_url = ROOT
        self.commands: list[list[str]] = []
        self.stopped = False

    def __call__(self, command: list[str]) -> dict[str, Any]:
        self.commands.append(list(command))
        if command == ["steel", "browser", "sessions", "--json"]:
            if self.stopped:
                return {"success": True, "data": []}
            return load_cli("catalogue").model_dump(mode="json")
        if "sessions" in command and "get" in command:
            return load_cli("session").model_dump(mode="json")
        verb = command[2] if len(command) > 2 else ""
        if verb == "stop":
            self.stopped = True
            return {"success": True, "data": {"stoppedSessions": ["crawl-fixture"]}}
        try:
            index = command.index("--json")
            args = command[index + 1 :]
        except ValueError:
            args = []
        if verb == "navigate":
            if args:
                self.current_url = args[0]
            return {
                "success": True,
                "data": {
                    "url": self.current_url,
                    "title": TITLES.get(self.current_url, ""),
                    "status": 200,
                },
            }
        if verb == "get":
            return {"success": True, "data": {"url": self.current_url}}
        return {"success": True, "data": {}}


def by_selector(elements, selector: str):
    return next(element for element in elements if element.selector == selector)


def test_the_run_loop_traverses_submits_once_captures_and_finalizes(tmp_path):
    app = AppExec()
    session = SteelSessionClient(
        exec_fn=app, prefix=("steel", "browser")
    )
    state = BrowserState()
    root = state.open_page(
        page_visit_id="page_1",
        url=ROOT,
        final_url=ROOT,
        title="Root",
        depth=0,
        discovery_source="seed",
        snapshot=ROOT_NODES,
    )
    sidecar = CaptureSidecar(FakeCdpTransport(load_cdp("http_flow")))
    mapper = CommandMapper(session, state)
    ledger = RunLedger(tmp_path / "ledger.jsonl")

    root_elements = ElementMap().project(
        ROOT_NODES, page=root, state=state, page_url=ROOT
    )
    delete = by_selector(root_elements, "@e1")
    delete_submit = by_selector(root_elements, "@e1s")
    search = by_selector(root_elements, "@e2")
    search_submit = by_selector(root_elements, "@e2s")
    refresh = by_selector(root_elements, "@e3")
    link = by_selector(root_elements, "@e4")

    throwaway = BrowserState()
    a_page = throwaway.open_page(
        page_visit_id="throwaway-a",
        url=A,
        final_url=A,
        title="A",
        snapshot=A_NODES,
    )
    a_button = by_selector(
        ElementMap().project(A_NODES, page=a_page, state=throwaway, page_url=A),
        "@a1",
    )

    policy = FakeDecisionClient(
        removed=[delete, delete_submit, *([None] * 10)],
        chosen=[refresh, search, search_submit, link, a_button, None, None],
    )
    submitted = []

    def submit_form(page, element):
        submitted.append(element.form)
        mapper.execute(
            Action(
                verb="submit",
                impact="write",
                capture="network",
                document_generation=state.current_generation,
                selector=element.form.root_selector,
            ),
            page,
        )

    def page_factory(url, parent, depth, source, navigation_path):
        return state.open_page(
            page_visit_id=f"page_{len(state.visited) + 1}",
            url=url,
            final_url=url,
            title=TITLES[url],
            status=200,
            parent_id=parent.page_visit_id if parent else None,
            depth=depth,
            discovery_source=source,
            navigation_path=navigation_path,
            snapshot=SNAPSHOTS[url],
        )

    def navigate(url):
        app.current_url = url
        session.execute("navigate", url, "--wait-until", "domcontentloaded")

    crawl = CrawlRun(
        project_id="proj-1",
        capture_context=CaptureContext(run_id="run-1"),
        session=session,
        state=state,
        sidecar=sidecar,
        policy=policy,
        mapper=mapper,
        element_map=ElementMap(),
        ledger=ledger,
        form_ledger=FormLedger(),
        page_factory=page_factory,
        navigate=navigate,
        submit_form=submit_form,
        in_scope=lambda url: url.startswith("https://example.test"),
        deadline=lambda: False,
        cancel=lambda: False,
    )

    pages: list[Any] = []
    actions: list[Any] = []
    flushed: list[Any] = []

    def manifest_fn(frontier, stop_reason):
        return build_manifest(
            run=RunBlock(
                crawl_run_id="run-1",
                session_name="crawl-fixture",
                started_at="2026-11-02T10:00:00Z",
                stop_reason=stop_reason,
            )
        )

    job = CrawlJob(
        run_id="run-1",
        session_name="crawl-fixture",
        project_id="proj-1",
        account="admin",
        session=session,
        sidecar=sidecar,
        ledger=ledger,
        prepare_fn=lambda: root,
        auth_fn=lambda page: AuthVerdict(
            classification="authenticated",
            probe_url="/api/auth",
            probe_source="overview.auth_probe.url",
        ),
        run_fn=lambda page: crawl.run(page).frontier,
        manifest_fn=manifest_fn,
        flush_fn=lambda artifacts: flushed.append(list(artifacts)) or {"cursor": 1},
        ingest_fn=lambda manifest: {"ok": True},
        record_page=pages.append,
        record_action=actions.append,
        coverage={"unreached": []},
        deadline=lambda: False,
        cancel=lambda: False,
    )

    result = job.run()

    assert result.status == "complete"
    assert result.stop_reason == "frontier_empty"
    assert [page.url for page in result.pages] == [ROOT, A]
    assert result.pages[1].parent_id == "page_1"
    assert [record.element_id for record in result.actions] == [
        "e3",
        "e2",
        "e2s",
        "e4",
        "a1",
    ]
    assert len(submitted) == 1
    assert submitted[0] is search.form

    output = crawl.last_output
    assert output is not None
    assert [element.element_id for element in output.removed] == ["e1", "e1s"]
    assert len(output.declared_endpoints) == 1
    assert output.declared_endpoints[0].path == "/delete"
    assert [field.name for field in output.declared_fields] == ["id"]
    assert len(output.artifacts) == 1
    assert output.artifacts[0][0].request.url == "https://example.test/api/items?page=2"
    assert [(parameter.name, parameter.location) for parameter in output.parameters] == [
        ("page", "query")
    ]
    assert output.flows[0].page_id == "page_1"
    assert output.flows[0].action_id == "act_1"
    assert len(flushed) == 1
    assert len(flushed[0]) == 1
    assert len(ledger.artifacts()) == 1
    assert ledger.manifests()[-1].run.stop_reason == "frontier_empty"
