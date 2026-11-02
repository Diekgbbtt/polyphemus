"""Seam under test: the DOM snapshot fixture.

The snapshot is the raw tree every later enumerator and collector test reads.
It must carry one of each element family the element map has to classify.
"""
from __future__ import annotations

import json

import pytest

from tests.recon.crawl.steel.fixtures import DomSnapshot, FixtureError, load_dom


def _walk(nodes):
    for node in nodes:
        yield node
        yield from _walk(node.children)


def test_load_dom_returns_a_typed_snapshot():
    snapshot = load_dom("home")

    assert isinstance(snapshot, DomSnapshot)
    assert snapshot.url == "https://example.test/"
    assert snapshot.title == "Example Shop"


def test_home_snapshot_covers_every_required_element_family():
    snapshot = load_dom("home")
    nodes = list(_walk(snapshot.nodes))

    assert {"a", "form", "button", "dialog", "product-card"} <= {n.tag for n in nodes}
    assert {"link", "form", "button", "menuitem", "dialog"} <= {n.role for n in nodes}
    assert any(
        n.attributes.get("hidden") is not None
        or n.attributes.get("aria-hidden") == "true"
        or n.visible is False
        for n in nodes
    )
    assert any("-" in n.tag for n in nodes)


def test_home_snapshot_form_and_dialog_carry_their_contract_fields():
    snapshot = load_dom("home")
    nodes = list(_walk(snapshot.nodes))

    form = next(n for n in nodes if n.tag == "form")
    assert form.attributes["action"] == "/search"
    assert {"q", "category"} <= {c.attributes.get("name") for c in form.children}

    dialog = next(n for n in nodes if n.tag == "dialog")
    assert dialog.attributes.get("open") is not None
    assert dialog.attributes.get("aria-modal") == "true"


def test_products_snapshot_offers_product_links_and_a_same_origin_iframe():
    snapshot = load_dom("products")
    nodes = list(_walk(snapshot.nodes))

    assert snapshot.url == "https://example.test/products?page=2"
    product_links = [n for n in nodes if n.attributes.get("href", "").startswith("/products/")]
    assert {n.name for n in product_links} == {"Alpha", "Beta"}
    iframe = next(n for n in nodes if n.tag == "iframe")
    assert iframe.attributes["src"] == "/reviews"


def test_dom_fixture_with_missing_tag_fails_loudly(tmp_path):
    path = tmp_path / "dom" / "broken.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "url": "https://example.test/",
                "title": "Broken",
                "nodes": [{"role": "link"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(FixtureError, match="DomSnapshot") as excinfo:
        load_dom("broken", root=tmp_path)

    assert "tag" in str(excinfo.value)
