"""Seam under test: `BrowserState` cache and consumed set through fixture snapshots.

Spec: `docs/design/steel-crawl-spec.md` sections 5.1, 5.2, 5.3, 6.5, and 12;
seam 3 of `docs/design/steel-crawl-implementation-plan.md` section 3. Every test
drives the public state surface - the cache key, the page instance, the restore,
the consumed set, and the stale-ref guard - with fixture snapshots and fake
navigation callables. The expected hashes are literals derived from the spec
formula, not recomputed from the implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from polymerhus.recon.crawl.steel.state import (
    BrowserState,
    PageInstance,
    SnapshotFacts,
    StaleElement,
    cache_key,
    state_key,
)
from tests.recon.crawl.steel.fixtures import load_cli


class FakeNavigate:
    """A stand-in for the `navigate_fn` seam: one URL in, one envelope out."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    def __call__(self, url: str) -> dict[str, Any]:
        self.urls.append(url)
        return {"success": True, "data": {"url": url, "title": "restored"}}


@dataclass(frozen=True)
class Candidate:
    """The candidate surface the consumed set needs: one stable fingerprint."""

    fingerprint: str
    name: str = ""


def open_home(state: BrowserState, **overrides: Any) -> PageInstance:
    """Open the fixture home page with the fields each test does not override."""
    payload: dict[str, Any] = {
        "page_visit_id": "page_1",
        "url": "https://example.test/",
        "final_url": "https://example.test/",
        "title": "Example Shop",
        "status": 200,
        "parent_id": None,
        "depth": 0,
        "discovery_source": "root",
        "navigation_path": [],
        "snapshot": load_cli("snapshot").data,
        "facts": SnapshotFacts(ax_hash="ax-home"),
    }
    payload.update(overrides)
    return state.open_page(**payload)


def test_the_cache_key_is_the_sha256_of_the_normalized_url_and_the_navigation_path():
    # HTTPS://Example.TEST:443//products///?sort=asc&page=2#top normalizes to
    # https://example.test/products?page=2&sort=asc: the fragment is dropped,
    # scheme and host are lower-cased, the default https port is removed,
    # duplicate path slashes collapse, the trailing slash goes, and the query
    # parameters are sorted.
    key = cache_key("HTTPS://Example.TEST:443//products///?sort=asc&page=2#top")

    assert key == "369d03fbfea7f3a72aa757136fa213fa1be92bb3fe15dc156328688c5183e0f0"

    # The path is the exact ordered list: sha256(normalized_url + "fp-afp-b"),
    # so a different order is a different page key.
    assert cache_key(
        "https://example.test/products?page=2", ["fp-a", "fp-b"]
    ) == "3179fbaa2828e35bed76e968de44187bd938b6c884f27e538c2458a907d4c340"
    assert cache_key(
        "https://example.test/products?page=2", ["fp-b", "fp-a"]
    ) == "bfb4d37995fb83aaea734ec2b6c75b125c65095df3288d3c871706ecd959617d"


def test_the_state_key_hashes_the_normalized_url_the_ax_hash_and_the_sorted_overlays():
    # sha256("https://example.test/products?page=2" + "ax-1" +
    #        "Cookie bannerNewsletter"): the URL is normalized, the overlay
    # titles are sorted, and their order in the input never changes the key.
    first = state_key(
        "HTTPS://Example.TEST:443//products///?page=2#top",
        SnapshotFacts(
            ax_hash="ax-1", overlay_flags=frozenset({"Newsletter", "Cookie banner"})
        ),
    )
    second = state_key(
        "https://example.test/products?page=2",
        SnapshotFacts(
            ax_hash="ax-1", overlay_flags=frozenset({"Cookie banner", "Newsletter"})
        ),
    )

    assert first == second
    assert first == "8f91ac85a44c0e8b743a64e737c273cd753b91909e66c93b26259158d648a05d"


def test_open_page_registers_the_page_node_and_caches_its_snapshot_and_facts():
    snapshot = load_cli("snapshot").data
    facts = SnapshotFacts(ax_hash="ax-home", overlay_flags=frozenset({"Newsletter"}))
    state = BrowserState()

    page = state.open_page(
        page_visit_id="page_1",
        url="https://example.test/legacy-products",
        final_url="https://example.test/products?page=2",
        title="Products",
        status=200,
        parent_id="page_0",
        depth=1,
        discovery_source="link",
        navigation_path=["fp-home", "fp-products"],
        snapshot=snapshot,
        facts=facts,
    )

    assert page.page_visit_id == "page_1"
    assert page.url == "https://example.test/legacy-products"
    assert page.final_url == "https://example.test/products?page=2"
    assert page.title == "Products"
    assert page.status == 200
    assert page.parent_id == "page_0"
    assert page.depth == 1
    assert page.discovery_source == "link"
    assert page.navigation_path == ("fp-home", "fp-products")
    assert page.cache_key == cache_key(
        "https://example.test/products?page=2", ["fp-home", "fp-products"]
    )
    assert page.state_key == state_key(
        "https://example.test/products?page=2", facts
    )
    assert page.document_generation == 1
    assert state.visited == frozenset({page.state_key})

    cached = state.cached(page)
    assert cached.snapshot is snapshot
    assert cached.facts.ax_hash == "ax-home"
    assert cached.facts.overlay_flags == frozenset({"Newsletter"})
    assert cached.facts.document_generation == page.document_generation


def test_restore_navigates_once_and_returns_the_cached_snapshot():
    snapshot = load_cli("snapshot").data
    state = BrowserState()
    page = open_home(state, snapshot=snapshot)
    navigate = FakeNavigate()

    first = state.restore(page, navigate)
    second = state.restore(page, navigate)

    assert first is snapshot
    assert second is snapshot
    assert navigate.urls == [page.url, page.url]


def test_a_restore_mints_a_new_generation_and_stales_the_pre_restore_reference():
    snapshot = load_cli("snapshot").data
    state = BrowserState()
    page = open_home(state, snapshot=snapshot)
    reference_generation = page.document_generation
    navigate = FakeNavigate()

    state.restore(page, navigate)

    assert navigate.urls == [page.url]
    # The page record keeps the generation it was opened under; the generation
    # of the restored document is the one the cached facts now carry.
    assert page.document_generation == reference_generation
    restored = state.cached(page)
    assert restored.snapshot is snapshot
    assert restored.facts.document_generation > reference_generation
    assert state.current_generation == restored.facts.document_generation
    with pytest.raises(StaleElement) as excinfo:
        state.resolve(page, reference_generation)
    assert excinfo.value.code == "stale_element"


def test_the_consumed_set_is_keyed_by_the_cache_key_not_the_state_key():
    state = BrowserState()
    page = open_home(state, facts=SnapshotFacts(ax_hash="ax-home"))
    same_document_other_state = open_home(
        state,
        facts=SnapshotFacts(ax_hash="ax-home", overlay_flags=frozenset({"Newsletter"})),
    )
    other_path = open_home(state, navigation_path=["fp-partner"])
    load_more = Candidate(fingerprint="fp-load-more", name="Load more")

    state.consume(page, load_more.fingerprint)

    assert page.cache_key == same_document_other_state.cache_key
    assert page.state_key != same_document_other_state.state_key
    assert state.unconsumed(same_document_other_state, [load_more]) == []
    # Same live state signature, different navigation history: a different page
    # key, so the action is still offered.
    assert other_path.state_key == page.state_key
    assert other_path.cache_key != page.cache_key
    assert state.unconsumed(other_path, [load_more]) == [load_more]


def test_a_reference_from_a_replaced_document_is_stale_and_the_candidate_is_consumed():
    state = BrowserState()
    page = open_home(state)
    load_more = Candidate(fingerprint="fp-load-more", name="Load more")
    reference_generation = page.document_generation
    open_home(
        state,
        page_visit_id="page_2",
        url="https://example.test/products?page=2",
        final_url="https://example.test/products?page=2",
        parent_id="page_1",
        depth=1,
        discovery_source="link",
        navigation_path=["fp-products"],
    )

    with pytest.raises(StaleElement) as excinfo:
        state.resolve(page, reference_generation)

    assert excinfo.value.code == "stale_element"
    assert excinfo.value.page_visit_id == "page_1"
    assert excinfo.value.generation == reference_generation
    # The caller consumes the candidate, so the dead action is never retried.
    state.consume(page, load_more.fingerprint)
    assert state.unconsumed(page, [load_more]) == []


def test_a_navigation_mints_a_new_document_generation_and_stales_the_old_refs():
    state = BrowserState()
    root = open_home(state)
    products = open_home(
        state,
        page_visit_id="page_2",
        url="https://example.test/products?page=2",
        final_url="https://example.test/products?page=2",
        parent_id="page_1",
        depth=1,
        discovery_source="link",
        navigation_path=["fp-products"],
    )

    assert products.document_generation > root.document_generation
    with pytest.raises(StaleElement):
        state.resolve(root, root.document_generation)


def test_a_local_state_action_keeps_the_generation_and_the_cached_references():
    state = BrowserState()
    root = open_home(state)
    generation = state.current_generation

    # A local_state impact loads no new document: it only consumes the action,
    # so the generation stays current and the cached references stay valid.
    state.consume(root, "fp-load-more")

    assert state.current_generation == generation
    assert state.cached(root).facts.document_generation == generation
    assert state.resolve(root, generation) is root
