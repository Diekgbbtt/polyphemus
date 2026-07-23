"""FR-INDEXCARD unit tier — the pure card builder + the DD-4 token discipline,
with an injected read_fn (no live DB).
"""
import pytest

from polymerhus.analysis import index_card


def test_service_card_shape():
    row = {
        "labels": ["L1TestableUnit", "L1Service"],
        "props": {"business_function_slug": "checkout", "project_id": "p", "label": "Checkout",
                  "api_paradigm": "REST", "prov_job": "analyser:r", "first_seen": "t"},
        "rels": ["AGGREGATES", "AGGREGATES", "EXPOSED_VIA"],
    }
    card = index_card._card_from_row(row)
    assert card["kind"] == "Service"
    assert card["key"] == {"business_function_slug": "checkout"}
    assert card["label"] == "checkout"
    assert card["spine"] == {"api_paradigm": "REST"}
    # edge-degree BY FAMILY (counts), not the member set
    assert card["edge_degree"] == {"AGGREGATES": 2, "EXPOSED_VIA": 1}
    # NL handles exclude managed/identity/spine keys
    assert card["nl_handles"] == {"label": "Checkout"}
    assert "project_id" not in card["nl_handles"]
    assert "prov_job" not in card["nl_handles"]


def test_system_card_shape():
    row = {
        "labels": ["L1TestableUnit", "L1System"],
        "props": {"kind": "CDN", "discriminator": "Datadome", "project_id": "p"},
        "rels": [],
    }
    card = index_card._card_from_row(row)
    assert card["kind"] == "System"
    assert card["key"] == {"kind": "CDN", "discriminator": "Datadome"}
    assert card["label"] == "CDN"
    assert card["edge_degree"] == {}  # zero-degree unit kept


# --- DD-4: the card carries edge-DEGREE, never the raw member set ---

def test_card_carries_degree_not_member_set():
    # a Service aggregating 10,000 L0 elements: the card must be a single count,
    # not 10,000 member nodes (the whole point of the token-light projection).
    row = {
        "labels": ["L1TestableUnit", "L1Service"],
        "props": {"business_function_slug": "sales-analysis", "project_id": "p"},
        "rels": ["AGGREGATES"] * 10000,
    }
    card = index_card._card_from_row(row)
    assert card["edge_degree"]["AGGREGATES"] == 10000
    # the card is small: no member payload anywhere in it
    import json
    blob = json.dumps(card)
    assert len(blob) < 500  # a fixed-size card regardless of 10k members
    assert "/api/" not in blob and "https://" not in blob  # no member node data leaked


def test_dfs_down_query_shape_and_guard():
    captured = {}

    def fake_read(cy, params):
        captured["cy"] = cy
        captured["params"] = params
        return [{"labels": ["L1TestableUnit", "L1System"], "props": {"kind": "RESTApi"}}]

    out = index_card.dfs_down("p", "sales-analysis", "EXPOSED_VIA", read_fn=fake_read)
    assert "-[r:EXPOSED_VIA]->(m)" in captured["cy"]
    assert captured["params"] == {"slug": "sales-analysis", "project_id": "p"}
    assert out == [{"labels": ["L1TestableUnit", "L1System"], "props": {"kind": "RESTApi"}}]


def test_dfs_down_rejects_unsafe_rel():
    with pytest.raises(ValueError):
        index_card.dfs_down("p", "s", "EXPOSED_VIA]->() DETACH DELETE m //", read_fn=lambda cy, p: [])
    # a trailing newline must NOT slip past the guard (\Z, not $)
    with pytest.raises(ValueError):
        index_card.dfs_down("p", "s", "EXPOSED_VIA\n", read_fn=lambda cy, p: [])


def test_index_cards_maps_all_rows():
    def fake_read(cy, params):
        assert "MATCH (u:L1TestableUnit)" in cy
        assert "collect(type(r))" in cy  # edge-degree projection, not member expansion
        return [
            {"labels": ["L1TestableUnit", "L1Service"], "props": {"business_function_slug": "a", "project_id": "p"}, "rels": ["AGGREGATES"]},
            {"labels": ["L1TestableUnit", "L1System"], "props": {"kind": "WAF", "discriminator": "__singleton__", "project_id": "p"}, "rels": []},
        ]

    cards = index_card.index_cards("p", read_fn=fake_read)
    assert [c["kind"] for c in cards] == ["Service", "System"]
    assert cards[0]["edge_degree"] == {"AGGREGATES": 1}
