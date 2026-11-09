"""Seam under test: the unified DFS `Frontier` through a fake page graph.

Spec: `docs/design/steel-crawl-spec.md` sections 2.2, 5, 5.1, 5.2, 5.3, 6.3,
6.6, and 12; seam 7 of `docs/design/steel-crawl-implementation-plan.md`
section 3.

The frontier is one depth-first traversal over page instances. These tests drive
it through the three injected page seams - `project`, `restore`, and `execute` -
so the whole traversal is exercisable without a browser: the fake graph answers
each page's cached projection, records every restore, and executes a navigation
by opening the result page through the real `BrowserState`. Expected visit
orders come from the spec's DFS algorithm, never from re-reading the frontier.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlsplit

from polymerhus.recon.crawl.steel.enumerate import (
    ChangeSemantics,
    Channel,
    Element,
    ElementType,
)
from polymerhus.recon.crawl.steel.frontier import ExecutionResult, Frontier
from polymerhus.recon.crawl.steel.policy.jev import PolicyProviderError
from polymerhus.recon.crawl.steel.safety import Collector
from polymerhus.recon.crawl.steel.session import CommandFailed, SessionMissing
from polymerhus.recon.crawl.steel.state import (
    BrowserState,
    PageInstance,
    SnapshotFacts,
    StaleElement,
)

ROOT = "https://example.test/"
BASE_HOST = "example.test"


def link(element_id: str, label: str, href: str) -> Element:
    """One same-origin link: a navigation candidate (spec 6.2)."""
    return Element(
        element_id=element_id,
        fingerprint=f"fingerprint_{element_id}",
        element_type=ElementType.LINK,
        name=label,
        href=href,
        selector=f"@{element_id}",
        impact="navigate",
        capture="navigation",
        change=ChangeSemantics(impact="navigate", capture="navigation", handler="href"),
    )


def button(element_id: str, label: str) -> Element:
    """One button: a local-state candidate (spec 6.2, 6.4)."""
    return Element(
        element_id=element_id,
        fingerprint=f"fingerprint_{element_id}",
        element_type=ElementType.BUTTON,
        name=label,
        selector=f"@{element_id}",
        impact="local_state",
        capture="dom",
        change=ChangeSemantics(impact="local_state", capture="dom", handler="onclick"),
    )


def external_link(element_id: str, label: str) -> Element:
    """One external link: the element map marks it `ignore` (spec 6.2, 6.3)."""
    return Element(
        element_id=element_id,
        fingerprint=f"fingerprint_{element_id}",
        element_type=ElementType.EXTERNAL_LINK,
        name=label,
        href="https://external.test/sale",
        selector=f"@{element_id}",
        channel=Channel.IGNORE,
        impact="external",
        capture="none",
        change=ChangeSemantics(impact="external", capture="none", handler="href"),
    )


@dataclass(frozen=True)
class FakePage:
    """One page's cached projection: what `project` answers by URL."""

    url: str
    elements: tuple[Element, ...] = ()
    title: str = ""
    status: int = 200
    ax_hash: str = ""

    def facts(self) -> SnapshotFacts:
        return SnapshotFacts(ax_hash=self.ax_hash or self.url)


class RecordingCollector:
    """The collector seam: records every removed element in place."""

    def __init__(self) -> None:
        self.collected: list[Element] = []

    def collect(self, element: Element) -> None:
        self.collected.append(element)


class FirstChoicePolicy:
    """A deterministic policy: remove nothing, choose the first live candidate."""

    def choose_removed(
        self, page: PageInstance, candidates: Sequence[Element]
    ) -> Element | None:
        return None

    def choose_chosen(
        self, page: PageInstance, candidates: Sequence[Element]
    ) -> Element | None:
        return candidates[0] if candidates else None

    def choose_value(self, field: Any, catalogue: Any) -> str | None:
        return None


class ScriptedPolicy(FirstChoicePolicy):
    """A policy that answers the removal question from a queue, then chooses first."""

    def __init__(self, removals: Iterable[Element]) -> None:
        self._removals = list(removals)

    def choose_removed(
        self, page: PageInstance, candidates: Sequence[Element]
    ) -> Element | None:
        return self._removals.pop(0) if self._removals else None


class FailingPolicy(FirstChoicePolicy):
    """A policy whose question raises the configured typed failure."""

    def __init__(
        self, error: BaseException, *, question: str = "choose_chosen"
    ) -> None:
        self.error = error
        self.question = question

    def _raise(self) -> None:
        raise self.error

    def choose_removed(
        self, page: PageInstance, candidates: Sequence[Element]
    ) -> Element | None:
        if self.question == "choose_removed":
            self._raise()
        return None

    def choose_chosen(
        self, page: PageInstance, candidates: Sequence[Element]
    ) -> Element | None:
        if self.question == "choose_chosen":
            self._raise()
        return candidates[0] if candidates else None


@dataclass
class FakeGraph:
    """A fake page graph over the real `BrowserState`.

    `project` answers the page's cached elements, `restore` records the rollback,
    and `execute` records the action; a configured navigation opens the result
    page through `BrowserState.open_page`, exactly as the production loader will,
    so the frontier sees a real page instance and a real visited set.
    """

    state: BrowserState = field(default_factory=BrowserState)
    pages: dict[str, FakePage] = field(default_factory=dict)
    navigations: dict[tuple[str, str], str] = field(default_factory=dict)
    stale: set[tuple[str, str]] = field(default_factory=set)
    missing_pages: set[tuple[str, str]] = field(default_factory=set)
    failures: dict[tuple[str, str], BaseException] = field(default_factory=dict)
    restore_failures: dict[str, BaseException] = field(default_factory=dict)
    project_failure: BaseException | None = None
    events: list[tuple[str, ...]] = field(default_factory=list)
    visits: int = 0

    def add(self, page: FakePage) -> FakePage:
        self.pages[page.url] = page
        return page

    def nav(self, source: str, element_id: str, target: str) -> None:
        self.navigations[(source, element_id)] = urljoin(source, target)

    def open_root(
        self,
        url: str = ROOT,
        elements: Iterable[Element] = (),
        *,
        page_visit_id: str = "page_root",
    ) -> PageInstance:
        page = self.add(FakePage(url=url, elements=tuple(elements)))
        return self.state.open_page(
            page_visit_id=page_visit_id,
            url=url,
            final_url=url,
            title=page.title,
            status=page.status,
            discovery_source="root",
            snapshot=page,
            facts=page.facts(),
        )

    def project(self, page: PageInstance) -> Sequence[Element]:
        if self.project_failure is not None:
            raise self.project_failure
        return self.pages[page.final_url or page.url].elements

    def restore(self, page: PageInstance) -> None:
        url = page.final_url or page.url
        self.events.append(("restore", url))
        failure = self.restore_failures.get(url)
        if failure is not None:
            raise failure

    def execute(self, page: PageInstance, element: Element) -> ExecutionResult:
        source = page.final_url or page.url
        self.events.append(("execute", source, element.element_id))
        failure = self.failures.get((source, element.element_id))
        if failure is not None:
            raise failure
        if (source, element.element_id) in self.stale:
            raise StaleElement(
                page, page.document_generation, page.document_generation + 1
            )
        target = self.navigations.get((source, element.element_id))
        if target is None:
            return ExecutionResult(
                navigated=False,
                url=source,
                status=page.status,
                title=page.title,
            )
        if (source, element.element_id) in self.missing_pages:
            return ExecutionResult(navigated=True, url=target, status=200)
        return self._open_result(page, element, self.pages[target])

    def _open_result(
        self, page: PageInstance, element: Element, target: FakePage
    ) -> ExecutionResult:
        self.visits += 1
        child = self.state.open_page(
            page_visit_id=f"page_{self.visits}",
            url=target.url,
            final_url=target.url,
            title=target.title,
            status=target.status,
            parent_id=page.page_visit_id,
            depth=page.depth + 1,
            discovery_source="action",
            navigation_path=(*page.navigation_path, element.fingerprint),
            snapshot=target,
            facts=target.facts(),
        )
        return ExecutionResult(
            navigated=True,
            page=child,
            url=target.url,
            status=target.status,
            title=target.title,
        )

    @property
    def executed(self) -> list[tuple[str, str]]:
        return [
            (event[1], event[2]) for event in self.events if event[0] == "execute"
        ]

    @property
    def restored(self) -> list[str]:
        return [event[1] for event in self.events if event[0] == "restore"]

    def frontier(
        self,
        *,
        policy: Any = None,
        collector: Collector | None = None,
        deadline: Any = None,
        cancel: Any = None,
    ) -> Frontier:
        return Frontier(
            project=self.project,
            restore=self.restore,
            execute=self.execute,
            policy=policy or FirstChoicePolicy(),
            state=self.state,
            collector=collector or RecordingCollector(),
            deadline=deadline or (lambda: False),
            cancel=cancel or (lambda: False),
            in_scope=in_scope,
        )


def in_scope(url: str) -> bool:
    """The base host plus its subdomains (spec 2.2 T2, workbench C8)."""
    host = (urlsplit(url).hostname or "").lower()
    return host == BASE_HOST or host.endswith(f".{BASE_HOST}")


def test_the_root_is_the_first_page_visit_and_a_navigation_result_becomes_current():
    graph = FakeGraph()
    root = graph.open_root(elements=(link("e-a", "A", "/a"),))
    graph.add(FakePage(url="https://example.test/a"))
    graph.nav(ROOT, "e-a", "/a")

    result = graph.frontier().run(root)

    # The seed is the first page visit, the link's result becomes the second
    # visit with the root as its parent, and the exhausted child pops the root.
    assert [visit.page.url for visit in result.page_visits] == [
        ROOT,
        "https://example.test/a",
    ]
    assert result.page_visits[0].parent is None
    assert result.page_visits[1].parent == root
    assert result.stop_reason == "frontier_empty"
    assert graph.executed == [(ROOT, "e-a")]


def test_a_local_state_action_is_restored_and_the_page_continues():
    graph = FakeGraph()
    root = graph.open_root(
        elements=(button("e-button", "Open"), link("e-a", "A", "/a"))
    )
    graph.add(FakePage(url="https://example.test/a"))
    graph.nav(ROOT, "e-a", "/a")

    result = graph.frontier().run(root)

    # The button is local: it is executed, consumed, and then the current page
    # is restored before the next choice, so the link is chosen from that page.
    assert graph.executed == [(ROOT, "e-button"), (ROOT, "e-a")]
    assert [visit.page.url for visit in result.page_visits] == [
        ROOT,
        "https://example.test/a",
    ]
    events = graph.events
    button_at = events.index(("execute", ROOT, "e-button"))
    restored_at = events.index(("restore", ROOT), button_at)
    assert restored_at < events.index(("execute", ROOT, "e-a"))
    assert result.stop_reason == "frontier_empty"


def test_an_external_link_is_ignored():
    graph = FakeGraph()
    root = graph.open_root(elements=(external_link("e-external", "Sale"),))

    result = graph.frontier().run(root)

    # The element map marks the external link `ignore`, so it is never a
    # candidate, never executed, and never a page visit.
    assert graph.executed == []
    assert [visit.page.url for visit in result.page_visits] == [ROOT]
    assert result.stop_reason == "frontier_empty"


def test_the_fake_graph_is_traversed_depth_first_and_the_root_is_popped_last():
    graph = FakeGraph()
    root = graph.open_root(
        elements=(
            link("e-a", "A", "/a"),
            link("e-b", "B", "/b"),
            external_link("e-external", "Sale"),
        )
    )
    a = graph.add(
        FakePage(
            url="https://example.test/a",
            elements=(
                button("e-a-local", "Open panel"),
                link("e-a1", "Detail", "/a/1"),
            ),
            title="A",
        )
    )
    detail = "https://example.test/a/1"
    b = "https://example.test/b"
    graph.add(FakePage(url=detail, title="Detail"))
    graph.add(FakePage(url=b, elements=(button("e-b-local", "Toggle"),)))
    graph.nav(ROOT, "e-a", "/a")
    graph.nav(a.url, "e-a1", "/a/1")
    graph.nav(ROOT, "e-b", "/b")

    result = graph.frontier().run(root)

    # Depth first: the whole /a subtree runs before /b; the external link is
    # ignored; the root keeps its place on the stack and yields /b after /a/1.
    assert [visit.page.url for visit in result.page_visits] == [
        ROOT,
        a.url,
        detail,
        b,
    ]
    assert result.page_visits[0].parent is None
    assert result.page_visits[1].parent == root
    assert result.page_visits[2].parent == result.page_visits[1].page
    assert result.page_visits[3].parent == root
    assert graph.executed == [
        (ROOT, "e-a"),
        (a.url, "e-a-local"),
        (a.url, "e-a1"),
        (ROOT, "e-b"),
        (b, "e-b-local"),
    ]
    events = graph.events
    local_at = events.index(("execute", a.url, "e-a-local"))
    assert events.index(("restore", a.url), local_at) < events.index(
        ("execute", a.url, "e-a1")
    )
    # The root is re-entered only after the /a subtree is exhausted, then it is
    # the last page popped: /b runs and the frontier ends with no current page.
    assert events.index(("restore", ROOT), local_at) < events.index(
        ("execute", ROOT, "e-b")
    )
    assert ("execute", ROOT, "e-external") not in events
    assert result.removed == ()
    assert result.duplicates == ()
    assert result.unrecoverable == ()
    assert result.stop_reason == "frontier_empty"


def test_the_session_deadline_stops_the_traversal_before_any_work():
    graph = FakeGraph()
    root = graph.open_root(elements=(link("e-a", "A", "/a"),))

    result = graph.frontier(deadline=lambda: True).run(root)

    assert result.stop_reason == "session_deadline"
    assert [visit.page.url for visit in result.page_visits] == [ROOT]
    assert graph.events == []


def test_an_operator_cancel_stops_the_traversal():
    graph = FakeGraph()
    root = graph.open_root(elements=(link("e-a", "A", "/a"),))

    result = graph.frontier(cancel=lambda: True).run(root)

    assert result.stop_reason == "operator_cancel"
    assert [visit.page.url for visit in result.page_visits] == [ROOT]
    assert graph.events == []


def test_an_operator_cancel_wins_over_a_simultaneous_deadline():
    graph = FakeGraph()
    root = graph.open_root(elements=(link("e-a", "A", "/a"),))

    result = graph.frontier(cancel=lambda: True, deadline=lambda: True).run(root)

    assert result.stop_reason == "operator_cancel"


def test_a_lost_session_on_a_navigation_load_stops_the_run():
    graph = FakeGraph()
    root = graph.open_root(elements=(link("e-a", "A", "/a"),))
    graph.add(FakePage(url="https://example.test/a"))
    graph.nav(ROOT, "e-a", "/a")
    graph.failures[(ROOT, "e-a")] = SessionMissing("the session is gone")

    result = graph.frontier().run(root)

    assert result.stop_reason == "session_missing"
    assert [visit.page.url for visit in result.page_visits] == [ROOT]
    assert result.error == "session_missing: the session is gone"


def test_a_lost_session_on_a_restore_stops_the_run():
    graph = FakeGraph()
    root = graph.open_root(elements=(link("e-a", "A", "/a"),))
    graph.restore_failures[ROOT] = SessionMissing("the session is gone")

    result = graph.frontier().run(root)

    assert result.stop_reason == "session_missing"
    assert [visit.page.url for visit in result.page_visits] == [ROOT]
    assert result.unrecoverable == ()
    assert result.error == "session_missing: the session is gone"


def test_a_navigation_result_with_a_visited_state_is_recorded_and_not_re_entered():
    graph = FakeGraph()
    root = graph.open_root(
        elements=(link("e-a", "A", "/a"), link("e-alias", "Alias", "/alias"))
    )
    a = graph.add(
        FakePage(
            url="https://example.test/a",
            elements=(link("e-a1", "Detail", "/a/1"),),
        )
    )
    detail = "https://example.test/a/1"
    graph.add(FakePage(url=detail))
    # The alias link resolves to the same document state as /a: same final URL
    # and the same accessible surface, so the same state key.
    graph.nav(ROOT, "e-a", "/a")
    graph.nav(a.url, "e-a1", "/a/1")
    graph.nav(ROOT, "e-alias", "/a")

    result = graph.frontier().run(root)

    assert [visit.page.url for visit in result.page_visits] == [
        ROOT,
        a.url,
        detail,
    ]
    assert graph.executed == [
        (ROOT, "e-a"),
        (a.url, "e-a1"),
        (ROOT, "e-alias"),
    ]
    assert len(result.duplicates) == 1
    duplicate = result.duplicates[0]
    assert duplicate.reason == "duplicate_state"
    assert duplicate.url == a.url
    assert duplicate.parent == root
    assert duplicate.element.element_id == "e-alias"
    assert duplicate.page is not None
    assert duplicate.page.state_key == result.page_visits[1].page.state_key
    assert result.stop_reason == "frontier_empty"


def test_a_navigation_landing_out_of_scope_is_recorded_and_not_entered():
    graph = FakeGraph()
    root = graph.open_root(elements=(link("e-off", "Sale", "/sale"),))
    external = "https://external.test/sale"
    graph.add(
        FakePage(
            url=external,
            elements=(button("e-external-local", "Buy"),),
        )
    )
    graph.nav(ROOT, "e-off", external)

    result = graph.frontier().run(root)

    # The link executed, but the browser landed outside the base host and its
    # subdomains: the result is recorded, never entered, and the page restored.
    assert [visit.page.url for visit in result.page_visits] == [ROOT]
    assert graph.executed == [(ROOT, "e-off")]
    assert len(result.duplicates) == 1
    duplicate = result.duplicates[0]
    assert duplicate.reason == "out_of_scope"
    assert duplicate.url == external
    assert duplicate.parent == root
    assert duplicate.element.element_id == "e-off"
    assert duplicate.page is not None
    assert graph.restored == [ROOT]
    assert result.stop_reason == "frontier_empty"


def test_a_stale_element_is_consumed_and_the_page_continues():
    graph = FakeGraph()
    root = graph.open_root(
        elements=(button("e-stale", "Gone"), link("e-a", "A", "/a"))
    )
    graph.add(FakePage(url="https://example.test/a"))
    graph.nav(ROOT, "e-a", "/a")
    graph.stale.add((ROOT, "e-stale"))

    result = graph.frontier().run(root)

    # The dead reference is consumed and recorded; the run does not stop, and
    # the next candidate is chosen from the same live page without a rollback.
    assert [visit.page.url for visit in result.page_visits] == [
        ROOT,
        "https://example.test/a",
    ]
    assert graph.executed == [(ROOT, "e-stale"), (ROOT, "e-a")]
    assert graph.restored == []
    assert len(result.stale) == 1
    stale = result.stale[0]
    assert stale.page == root
    assert stale.element.element_id == "e-stale"
    assert stale.error.code == "stale_element"
    assert result.stop_reason == "frontier_empty"


def test_there_is_no_depth_or_page_cap():
    graph = FakeGraph()
    urls = [ROOT] + [
        f"https://example.test/level-{index}" for index in range(1, 6)
    ]
    root = graph.open_root(elements=(link("e-0", "Next", urls[1]),))
    for index in range(1, len(urls)):
        elements = ()
        if index < len(urls) - 1:
            elements = (link(f"e-{index}", "Next", urls[index + 1]),)
        graph.add(FakePage(url=urls[index], elements=elements))
        graph.nav(urls[index - 1], f"e-{index - 1}", urls[index])

    result = graph.frontier().run(root)

    # Six levels deep and six page visits: the session is the only bound, there
    # is no depth limit and no page cap.
    assert [visit.page.url for visit in result.page_visits] == urls
    assert result.stop_reason == "frontier_empty"


def test_a_typed_action_error_stops_with_its_code_and_message():
    graph = FakeGraph()
    root = graph.open_root(elements=(button("e-boom", "Boom"),))
    graph.failures[(ROOT, "e-boom")] = CommandFailed("the browser did not answer")

    result = graph.frontier().run(root)

    assert result.stop_reason == "error"
    assert result.error == "command_failed: the browser did not answer"
    assert graph.executed == [(ROOT, "e-boom")]
    assert len(result.failed) == 1
    assert result.failed[0].element.element_id == "e-boom"
    assert "command_failed" in result.failed[0].error


def test_a_session_loss_during_an_action_is_recorded_as_a_failed_action():
    graph = FakeGraph()
    root = graph.open_root(elements=(button("e-lost", "Lost"),))
    graph.failures[(ROOT, "e-lost")] = SessionMissing("the session is gone")

    result = graph.frontier().run(root)

    assert result.stop_reason == "session_missing"
    assert len(result.failed) == 1
    assert result.failed[0].element.element_id == "e-lost"
    assert "session_missing" in result.failed[0].error


def test_a_typed_choice_error_stops_with_its_code_and_message():
    graph = FakeGraph()
    root = graph.open_root(elements=(link("e-a", "A", "/a"),))
    failure = PolicyProviderError(
        "choose_chosen", TimeoutError("typesafe timed out")
    )

    result = graph.frontier(policy=FailingPolicy(failure)).run(root)

    assert result.stop_reason == "error"
    assert result.error == (
        "policy_provider_error: the choose_chosen question could not be "
        "answered: typesafe timed out"
    )
    assert graph.executed == []


def test_a_typed_removal_error_stops_before_any_choice():
    graph = FakeGraph()
    root = graph.open_root(
        elements=(button("e-remove", "Delete"), link("e-a", "A", "/a"))
    )
    failure = PolicyProviderError(
        "choose_removed", TimeoutError("typesafe timed out")
    )

    result = graph.frontier(
        policy=FailingPolicy(failure, question="choose_removed")
    ).run(root)

    assert result.stop_reason == "error"
    assert result.error.startswith("policy_provider_error:")
    assert graph.executed == []


def test_a_projection_error_stops_with_its_message():
    graph = FakeGraph()
    root = graph.open_root(elements=(link("e-a", "A", "/a"),))
    graph.project_failure = ValueError("not a compact snapshot line")

    result = graph.frontier().run(root)

    assert result.stop_reason == "error"
    assert result.error == "not a compact snapshot line"
    assert graph.executed == []


def test_a_stale_removal_stops_the_run_before_executing_anything():
    graph = FakeGraph()
    root = graph.open_root(
        elements=(button("e-remove", "Delete"), link("e-a", "A", "/a"))
    )
    ghost = button("e-ghost", "Delete")
    collector = RecordingCollector()

    result = graph.frontier(
        policy=ScriptedPolicy([ghost]), collector=collector
    ).run(root)

    # A removal answer outside the live set is a protocol error: the stage
    # stopped, so no candidate on the page is executed or collected.
    assert result.stop_reason == "error"
    assert result.error is not None
    assert result.error.startswith("policy_stale_removal:")
    assert graph.executed == []
    assert collector.collected == []


def test_a_removed_candidate_is_collected_in_place_and_never_executed():
    graph = FakeGraph()
    remove = button("e-remove", "Delete")
    root = graph.open_root(elements=(remove, link("e-a", "A", "/a")))
    graph.add(FakePage(url="https://example.test/a"))
    graph.nav(ROOT, "e-a", "/a")
    collector = RecordingCollector()

    result = graph.frontier(
        policy=ScriptedPolicy([remove]), collector=collector
    ).run(root)

    # The forbidden candidate is consumed and collected, never executed, and
    # the choice continues from the remaining live set.
    assert result.removed == (remove,)
    assert collector.collected == [remove]
    assert graph.executed == [(ROOT, "e-a")]
    assert graph.state.unconsumed(root, [remove]) == []
    assert [visit.page.url for visit in result.page_visits] == [
        ROOT,
        "https://example.test/a",
    ]
    assert result.stop_reason == "frontier_empty"


def test_an_unrecoverable_page_is_recorded_and_the_ancestor_resumes():
    graph = FakeGraph()
    root = graph.open_root(
        elements=(link("e-a", "A", "/a"), link("e-b", "B", "/b"))
    )
    a = graph.add(
        FakePage(
            url="https://example.test/a",
            elements=(button("e-a-local", "Open panel"),),
        )
    )
    b = "https://example.test/b"
    graph.add(FakePage(url=b))
    graph.nav(ROOT, "e-a", "/a")
    graph.nav(ROOT, "e-b", "/b")
    graph.restore_failures[a.url] = CommandFailed(
        "the page could not be restored"
    )

    result = graph.frontier().run(root)

    # A restore that fails for a page-level reason is `unrecoverable_state`
    # (spec 12): the page is recorded and the nearest ancestor with residue
    # resumes, so the session keeps traversing.
    assert [visit.page.url for visit in result.page_visits] == [
        ROOT,
        a.url,
        b,
    ]
    assert result.unrecoverable == (result.page_visits[1].page,)
    assert graph.executed == [
        (ROOT, "e-a"),
        (a.url, "e-a-local"),
        (ROOT, "e-b"),
    ]
    assert result.stop_reason == "frontier_empty"


def test_a_navigation_without_a_page_instance_stops_with_a_typed_error():
    graph = FakeGraph()
    root = graph.open_root(elements=(link("e-a", "A", "/a"),))
    graph.add(FakePage(url="https://example.test/a"))
    graph.nav(ROOT, "e-a", "/a")
    graph.missing_pages.add((ROOT, "e-a"))

    result = graph.frontier().run(root)

    assert result.stop_reason == "error"
    assert result.error == "the navigation result carries no page instance"
    assert [visit.page.url for visit in result.page_visits] == [ROOT]


ADMIN = "https://example.test/admin/"


def test_run_many_traverses_the_authenticated_seed_before_the_public_root():
    """The admin console is a known seed, not a link on the public root.

    Iteration E proved the admin dashboard in the auth oracle but never rendered
    it, because the frontier had only the public root. A multi-seed run explores
    the authenticated entry first and keeps both surfaces in one result.
    """
    graph = FakeGraph()
    public = graph.open_root(elements=(link("e-public", "A", "/a"),))
    admin = graph.open_root(
        ADMIN,
        elements=(link("e-admin", "Users", "/admin/users"),),
        page_visit_id="page_admin",
    )
    graph.add(FakePage(url="https://example.test/a"))
    graph.add(FakePage(url="https://example.test/admin/users"))
    graph.nav(ROOT, "e-public", "/a")
    graph.nav(ADMIN, "e-admin", "/admin/users")

    result = graph.frontier().run_many((admin, public))

    assert [visit.page.url for visit in result.page_visits] == [
        ADMIN,
        "https://example.test/admin/users",
        ROOT,
        "https://example.test/a",
    ]
    assert result.stop_reason == "frontier_empty"
    assert graph.executed == [
        (ADMIN, "e-admin"),
        (ROOT, "e-public"),
    ]
    # The browser moved to the admin seed; the public seed must be restored
    # before it projects or executes its first candidate.
    assert graph.events.index(("restore", ROOT)) < graph.events.index(
        ("execute", ROOT, "e-public")
    )


def test_run_many_stops_before_the_next_seed_on_a_session_deadline():
    graph = FakeGraph()
    public = graph.open_root(elements=(link("e-public", "A", "/a"),))
    admin = graph.open_root(
        ADMIN,
        elements=(link("e-admin", "Users", "/admin/users"),),
        page_visit_id="page_admin",
    )

    result = graph.frontier(deadline=lambda: True).run_many((admin, public))

    assert result.stop_reason == "session_deadline"
    assert [visit.page.url for visit in result.page_visits] == [ADMIN]
    assert graph.executed == []


def test_an_out_of_scope_navigation_without_a_page_is_still_recorded():
    graph = FakeGraph()
    root = graph.open_root(elements=(link("e-off", "Sale", "/sale"),))
    external = "https://external.test/sale"
    graph.nav(ROOT, "e-off", external)
    graph.missing_pages.add((ROOT, "e-off"))

    result = graph.frontier().run(root)

    # The landing URL alone proves the result is out of scope: the frontier
    # records it and rolls back rather than failing on the absent page.
    assert result.stop_reason == "frontier_empty"
    assert [visit.page.url for visit in result.page_visits] == [ROOT]
    assert len(result.duplicates) == 1
    assert result.duplicates[0].reason == "out_of_scope"
    assert result.duplicates[0].url == external
    assert result.duplicates[0].page is None
