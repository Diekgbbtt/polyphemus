"""Unit tier: the sound unit-projection reader (#63, spec 2.2).

The projection is EXACTLY the unit's typed facets: the index-card (spine-key
presence) plus the one-hop typed neighbour surface (per-family outgoing edges
with target System kinds and role-presence) and the data axis (PRODUCES /
CONSUMES counts, DataRelationship kinds among the unit's items). The reader is
a pure traversal-then-fetch over the injectable `read_fn` (the raw cypher
seam, `neo4j_client.read` contract), resolved lazily like every read seam in
this codebase (CODING_STANDARD section 6).

The reader issues ONE read per unit (the unit row + its outgoing edges) and
ONE for the DataRelationship kinds among the unit's items. The analysis read
seams (`index_cards`, `dfs_down`) do NOT surface per-edge target kinds or rel
props, which the grammar's `reachable-via(kind, role?)` facet ranges over, so
this reader is its own read-only hop in the hunting context - never a write.

Absence is not-yet-filled (the L1 convention): a unit with no outgoing edge in
a family simply has no entry for that family in the projection - the
evaluation stage maps that to UNKNOWN (default-open), never FALSE (C12).
"""

from polymerhus.attack.hunting.unit_projection import (
    EdgeInfo,
    UnitProjection,
    build_projection,
)


# --- fake read_fn rows (the neo4j_client.read contract: (cypher, params) -> list[dict])

def _unit_row(kind_label="L1Service", **props):
    return {"labels": [kind_label], "props": props}


def _edge_row(family, target_labels, target_kind=None, role=None):
    rprops = {"role": role} if role is not None else {}
    return {
        "family": family,
        "tlabels": target_labels,
        "tprops": {"kind": target_kind} if target_kind is not None else {},
        "rprops": rprops,
    }


class FakeL1:
    """A tiny in-memory L1 model behind the read_fn seam: unit_id -> raw rows."""

    def __init__(self, units):
        # units: {unit_id: {"labels": [...], "props": {...}, "edges": [...]}}
        self.units = units
        self.calls = []

    def read(self, cypher, params):
        self.calls.append(cypher)
        if "type(dr) AS family" in cypher:
            return self._data_rel_rows(params)
        unit_id = f"{params['kind']}:{params['key']}"
        unit = self.units.get(unit_id)
        if unit is None:
            return []
        return [{
            "labels": unit["labels"],
            "props": unit["props"],
            "edges": unit.get("edges", []),
        }]

    def __call__(self, cypher, params):
        return self.read(cypher, params)

    def _data_rel_rows(self, params):
        unit_id = f"{params['kind']}:{params['key']}"
        unit = self.units.get(unit_id)
        return [{"family": f} for f in (unit or {}).get("data_rel_families", [])]


def _projection(unit_id, read_fn, project_id="p"):
    return build_projection(project_id, unit_id, read_fn=read_fn)


# --- the reader is pure mapping over the injectable seam -----------------------

def test_build_projection_lifts_card_and_one_hop_edges():
    fake = FakeL1({
        "Service:checkout": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "checkout",
                      "exposure": "public", "service_contract": "checkout flows"},
            "edges": [
                _edge_row("EXPOSED_VIA", ["L1System"], target_kind="RESTApi"),
                _edge_row("EXPOSED_VIA", ["L1System"], target_kind="GraphQLApi"),
                _edge_row("AUTHORIZED_BY", ["L1System"], target_kind="AuthorizationSystem",
                          role="admin"),
                _edge_row("CONSUMES", ["L1DataItem"]),
            ],
        },
    })
    projection = _projection("Service:checkout", fake)
    assert isinstance(projection, UnitProjection)
    assert projection.unit_id == "Service:checkout"
    assert projection.kind == "Service"
    assert projection.spine == {"exposure": "public",
                                "service_contract": "checkout flows"}
    assert projection.edges["EXPOSED_VIA"] == (
        EdgeInfo("EXPOSED_VIA", "RESTApi"),
        EdgeInfo("EXPOSED_VIA", "GraphQLApi"),
    )
    assert projection.edges["AUTHORIZED_BY"] == (
        EdgeInfo("AUTHORIZED_BY", "AuthorizationSystem", role="admin"),
    )
    assert projection.data_edges == {"CONSUMES": 1}


def test_build_projection_system_unit_and_its_own_kind():
    fake = FakeL1({
        "WAF:__singleton__": {
            "labels": ["L1System"],
            "props": {"kind": "WAF", "discriminator": "__singleton__",
                      "rendering_model": None},
            "edges": [],
        },
    })
    projection = _projection("WAF:__singleton__", fake)
    assert projection.kind == "WAF"
    assert projection.edges == {}
    assert projection.spine == {}


def test_build_projection_data_rel_kinds_among_the_units_items():
    fake = FakeL1({
        "Service:orders": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "orders"},
            "edges": [_edge_row("PRODUCES", ["L1DataItem"]),
                      _edge_row("CONSUMES", ["L1DataItem"])],
            "data_rel_families": ["DERIVED_FROM", "SUBSET_OF"],
        },
    })
    projection = _projection("Service:orders", fake)
    assert projection.data_rel_kinds == frozenset({"DERIVED_FROM", "SUBSET_OF"})


def test_build_projection_absent_family_is_absent_facet():
    # a unit with only EXPOSED_VIA edges has no CONSUMES entry at all - absence
    # is not-yet-filled (C12-b: family absent -> UNKNOWN at evaluation)
    fake = FakeL1({
        "Service:sign-in": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "sign-in"},
            "edges": [_edge_row("EXPOSED_VIA", ["L1System"], target_kind="WebPresentation")],
        },
    })
    projection = _projection("Service:sign-in", fake)
    assert "CONSUMES" not in projection.edges
    assert "AUTHORIZED_BY" not in projection.edges
    assert projection.data_edges == {}


def test_build_projection_unknown_unit_returns_none():
    fake = FakeL1({})
    assert _projection("Service:ghost", fake) is None


def test_build_projection_reads_are_scoped_and_deterministic():
    fake = FakeL1({
        "Service:checkout": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "checkout"},
            "edges": [_edge_row("EXPOSED_VIA", ["L1System"], target_kind="RESTApi")],
        },
    })
    first = _projection("Service:checkout", fake)
    second = _projection("Service:checkout", fake)
    assert first == second
    assert len(fake.calls) == 4  # two reads per build, twice - no cache, pure
    assert all("$project_id" in c for c in fake.calls[::2])


def test_build_projection_ignores_non_system_targets():
    # one-hop typed SURFACE is System-facing; L0 targets (if any) are not
    # System kinds and stay out of the typed edges
    fake = FakeL1({
        "Service:checkout": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "checkout"},
            "edges": [_edge_row("EXPOSED_VIA", ["L1System"], target_kind="RESTApi"),
                      _edge_row("AGGREGATES", ["L0Endpoint"])],
        },
    })
    projection = _projection("Service:checkout", fake)
    assert set(projection.edges) == {"EXPOSED_VIA"}
