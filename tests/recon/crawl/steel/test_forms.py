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
    Element,
    ElementMap,
    SnapshotNode,
)
from polymerhus.recon.crawl.steel.forms import DeclaredCollector, FormLedger
from polymerhus.recon.crawl.steel.state import BrowserState, PageInstance
from tests.recon.crawl.steel.fixtures import DomNode, load_dom


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
