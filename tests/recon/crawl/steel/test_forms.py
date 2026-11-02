"""Seam under test: the declared collector and the form ledger.

Spec: `docs/design/steel-crawl-spec.md` sections 2.4, 2.6 (P3, P4), 6.3, and 8.3;
seam 4 of `docs/design/steel-crawl-implementation-plan.md` section 3.

The collector is what the removal stage hands a candidate it just removed, so a
removed login form reaches the graph as a declared endpoint while it is never
submitted (spec S3, P3). A candidate with no form contract declares nothing. The
form ledger is spec P4: a form is submitted once per state, and a failed
submission never closes it. No test here submits, fetches, or executes anything:
the collector has no browser and the ledger has no executor.
"""
from __future__ import annotations

from polymerhus.recon.crawl.steel.enumerate import (
    ChangeSemantics,
    Element,
    ElementMap,
    ElementType,
    SnapshotNode,
)
from polymerhus.recon.crawl.steel.forms import (
    DeclaredCollector,
    FormExecutor,
    FormLedger,
)
from polymerhus.recon.crawl.steel.parameters import FormContract, FormField
from polymerhus.recon.crawl.steel.policy.select import DEFAULT_VALUE_CATALOGUE
from polymerhus.recon.crawl.steel.state import BrowserState, PageInstance
from tests.recon.crawl.steel.fixtures import DomNode, load_dom
from tests.recon.crawl.steel.support import FakeDecisionClient


def to_snapshot_node(record: DomNode) -> SnapshotNode:
    """Adapt the fixture's structured DOM record to the production node model."""
    return SnapshotNode(
        tag=record.tag,
        ref=record.ref,
        role=record.role,
        name=record.name,
        text=record.text,
        attributes=dict(record.attributes),
        visible=record.visible,
        children=tuple(to_snapshot_node(child) for child in record.children),
    )


def home() -> tuple[PageInstance, dict[str, Element]]:
    """The home fixture page and its candidates, keyed by element id."""
    dom = load_dom("home")
    state = BrowserState()
    page = state.open_page(
        page_visit_id="page_home",
        url=dom.url,
        final_url=dom.url,
        title=dom.title,
        snapshot=dom,
    )
    nodes = tuple(to_snapshot_node(node) for node in dom.nodes)
    elements = ElementMap().project(nodes, page=page, state=state, page_url=page.url)
    return page, {element.element_id: element for element in elements}


def test_a_removed_button_declares_nothing():
    page, elements = home()
    collector = DeclaredCollector(page)

    # e9 is a plain button, e12 a dialog button: neither has a form contract, so
    # the removal stage collects no declared endpoint for them (spec 6.3, 8.3).
    collector.collect(elements["e9"])
    collector.collect(elements["e12"])

    assert elements["e9"].form is None
    assert collector.endpoints == []
    assert collector.fields == []


def test_the_collector_writes_the_declared_endpoint_and_its_fields():
    page, elements = home()
    collector = DeclaredCollector(page)

    collector.collect(elements["e5"])

    assert len(collector.endpoints) == 1
    endpoint = collector.endpoints[0]
    # A collected form is always declared, and it has no flow and no action:
    # the removal stage never executed it (spec 8.4, P3).
    assert endpoint.provenance == "declared"
    assert endpoint.method == "GET"
    assert endpoint.url == "https://example.test/search"
    assert endpoint.path == "/search"
    assert endpoint.baseurl == "https://example.test"
    assert endpoint.status_code is None
    assert endpoint.source == "dom"
    assert endpoint.resource_type == "document"
    assert endpoint.http_artifact_id is None
    assert endpoint.source_page_id == "page_home"
    assert endpoint.action_id is None
    assert endpoint.enctype == "application/x-www-form-urlencoded"
    assert endpoint.field_names == ("q", "category")

    # One declared field per form field, each carrying the field contract and
    # no value shape at all (spec 8.4).
    assert [field.name for field in collector.fields] == ["q", "category"]
    query, category = collector.fields
    for field in collector.fields:
        assert field.endpoint_id == endpoint.endpoint_id
        assert field.provenance == "declared"
        assert field.endpoint_path == "/search"
        assert field.baseurl == "https://example.test"
        assert field.position == "body"
        assert field.value_shape is None
        assert field.http_artifact_id is None
        assert field.content_type == "application/x-www-form-urlencoded"
    assert (query.field_type, query.label) == ("search", "Search products")
    assert (category.field_type, category.options) == ("select-one", ("all", "books"))


class FakeMapper:
    def __init__(self) -> None:
        self.actions: list = []

    def execute(self, action, page):
        self.actions.append(action)


def test_the_form_executor_fills_and_submits_a_form_once():
    state = BrowserState()
    page = state.open_page(
        page_visit_id="page_exec",
        url="https://example.test/",
        final_url="https://example.test/",
        title="Exec",
        snapshot=(),
    )
    form = FormContract(
        root_selector="@form",
        action="https://example.test/search",
        method="GET",
        fields=(
            FormField(name="q", type="text", label="Query", selector="@q"),
            FormField(
                name="category",
                type="select-one",
                label="Category",
                options=("all", "books"),
                selector="@c",
            ),
        ),
        submit_selector="@s",
        submit_text="Search",
    )
    element = Element(
        element_id="form",
        fingerprint="fp-form",
        element_type=ElementType.FORM,
        name="Search",
        selector="@form",
        impact="write",
        capture="network",
        change=ChangeSemantics(impact="write", capture="network"),
        form=form,
    )
    mapper = FakeMapper()
    executor = FormExecutor(
        mapper=mapper,
        policy=FakeDecisionClient(values=["search"]),
        catalogue=DEFAULT_VALUE_CATALOGUE,
    )

    submission = executor.submit(page, element, generation=page.document_generation)

    assert submission.submitted is True
    assert submission.value_keys == ("search", "first")
    assert [action.verb for action in mapper.actions] == ["fill", "select", "submit"]
    assert mapper.actions[0].value == "test"
    assert mapper.actions[1].value == "all"
    assert mapper.actions[2].selector == "@form"
    assert executor.ledger.should_submit(form, page.state_key) is False

    second = executor.submit(page, element, generation=page.document_generation)

    assert second.skipped == "duplicate"
    assert len(mapper.actions) == 3
    assert "value" not in form.fields[0].to_policy_field()


def test_a_form_submit_without_a_2xx_is_not_marked():
    state = BrowserState()
    page = state.open_page(
        page_visit_id="page_fail",
        url="https://example.test/",
        final_url="https://example.test/",
        title="Fail",
        snapshot=(),
    )
    form = FormContract(
        root_selector="@form",
        action="https://example.test/search",
        method="GET",
        fields=(FormField(name="q", type="text", label="Query", selector="@q"),),
        submit_selector="@s",
        submit_text="Search",
    )
    element = Element(
        element_id="form",
        fingerprint="fp-form",
        element_type=ElementType.FORM,
        name="Search",
        selector="@form",
        impact="write",
        capture="network",
        change=ChangeSemantics(impact="write", capture="network"),
        form=form,
    )
    executor = FormExecutor(
        mapper=FakeMapper(),
        policy=FakeDecisionClient(values=["search"]),
        catalogue=DEFAULT_VALUE_CATALOGUE,
        submit_check=lambda value: False,
    )

    submission = executor.submit(page, element, generation=page.document_generation)

    assert submission.submitted is False
    assert submission.skipped == "submit_failed"
    assert executor.ledger.should_submit(form, page.state_key) is True
