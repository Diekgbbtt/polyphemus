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
    AggregatedEndpoint,
    DataItem,
    DataRelationship,
    EdgeInfo,
    SystemInfo,
    UnitProjection,
    build_projection,
)


# --- fake read_fn rows (the neo4j_client.read contract: (cypher, params) -> list[dict])

def _unit_row(kind_label="L1Service", **props):
    return {"labels": [kind_label], "props": props}


def _edge_row(family, target_labels, target_props=None, role=None):
    rprops = {"role": role} if role is not None else {}
    return {
        "family": family,
        "tlabels": target_labels,
        "tprops": dict(target_props or {}),
        "rprops": rprops,
    }


class FakeL1:
    """A tiny in-memory L1 model behind the read_fn seam: unit_id -> raw rows."""

    def __init__(self, units):
        # units: {unit_id: {"labels": [...], "props": {...}, "edges": [...],
        #                    "data_rel_families": [...], "adj": {...}}}
        self.units = units
        self.calls = []

    def read(self, cypher, params):
        self.calls.append(cypher)
        if "AGGREGATES" in cypher:
            return self._aggregated_rows(params)
        if "cooperating_outs" in cypher:
            return self._adj_rows(params)
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

    def _aggregated_rows(self, params):
        unit_id = f"{params['kind']}:{params['key']}"
        unit = self.units.get(unit_id)
        rows = (unit or {}).get("aggregated")
        if rows is not None:
            return rows
        return []

    def _data_rel_rows(self, params):
        unit_id = f"{params['kind']}:{params['key']}"
        unit = self.units.get(unit_id)
        rows = unit.get("data_rel_rows")
        if rows is not None:
            return rows
        return [{"family": f} for f in (unit or {}).get("data_rel_families", [])]

    def _adj_rows(self, params):
        unit_id = f"{params['kind']}:{params['key']}"
        unit = self.units.get(unit_id)
        adj = (unit or {}).get("adj", {})
        return [{"ins": adj.get("ins", []), "cooperating_outs": adj.get("outs", [])}]


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
                _edge_row("EXPOSED_VIA", ["L1System"], target_props={"kind": "RESTApi"}),
                _edge_row("EXPOSED_VIA", ["L1System"], target_props={"kind": "GraphQLApi"}),
                _edge_row("AUTHORIZED_BY", ["L1System"],
                          target_props={"kind": "AuthorizationSystem"}, role="admin"),
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
        EdgeInfo("EXPOSED_VIA", "RESTApi",
                 target=SystemInfo(kind="RESTApi", props={"kind": "RESTApi"})),
        EdgeInfo("EXPOSED_VIA", "GraphQLApi",
                 target=SystemInfo(kind="GraphQLApi", props={"kind": "GraphQLApi"})),
    )
    assert projection.edges["AUTHORIZED_BY"] == (
        EdgeInfo("AUTHORIZED_BY", "AuthorizationSystem", role="admin",
                 target=SystemInfo(kind="AuthorizationSystem",
                                   props={"kind": "AuthorizationSystem"})),
    )
    assert projection.data_edges == {"CONSUMES": 1}
    assert projection.data_items == {
        "CONSUMES": (DataItem(item_key=None),),
    }


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
            "edges": [_edge_row("EXPOSED_VIA", ["L1System"], target_props={"kind": "WebPresentation"})],
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
            "edges": [_edge_row("EXPOSED_VIA", ["L1System"], target_props={"kind": "RESTApi"})],
        },
    })
    first = _projection("Service:checkout", fake)
    second = _projection("Service:checkout", fake)
    assert first == second
    # three reads per build (unit row + data-rel chains + AGGREGATES), twice -
    # no cache, pure
    assert len(fake.calls) == 6
    assert all("$project_id" in c for c in fake.calls[::3])


def test_build_projection_service_aggregates_endpoints():
    """#201: a Service's AGGREGATES-bound L0 Endpoints land on the projection
    as `aggregated_endpoints` (method/path/baseurl from the L0 identity props);
    the aggregate read is scoped to the target unit, never the whole surface."""
    fake = FakeL1({
        "Service:checkout": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "checkout"},
            "edges": [],
            "aggregated": [
                {"props": {"path": "/pay", "method": "POST", "baseurl": "https://a",
                           "url": "https://a/pay"}},
                {"props": {"path": "/cart", "method": "GET", "baseurl": "https://a",
                           "url": "https://a/cart"}},
            ],
        },
    })
    projection = _projection("Service:checkout", fake)
    assert projection.aggregated_endpoints == (
        AggregatedEndpoint(method="GET", path="/cart", baseurl="https://a"),
        AggregatedEndpoint(method="POST", path="/pay", baseurl="https://a"),
    )
    agg_cyphers = [c for c in fake.calls if "AGGREGATES" in c]
    assert len(agg_cyphers) == 1
    assert "business_function_slug: $key" in agg_cyphers[0]


def test_build_projection_system_aggregates_linked_services_endpoints():
    """#201 system contract: a System unit surfaces the Endpoints its LINKED
    services aggregate, each entry carrying the owning service slug."""
    fake = FakeL1({
        "System:auth:auth-1": {
            "labels": ["L1System"],
            "props": {"kind": "auth", "discriminator": "auth-1"},
            "edges": [],
            "aggregated": [
                {"slug": "sign-in", "props": {"path": "/login", "method": "POST",
                                              "baseurl": "https://a"}},
                {"slug": "sign-in", "props": {"path": "/token", "method": "GET",
                                              "baseurl": "https://a"}},
            ],
        },
    })
    projection = _projection("System:auth:auth-1", fake)
    assert projection.aggregated_endpoints == (
        AggregatedEndpoint(method="GET", path="/token", baseurl="https://a",
                           service_slug="sign-in"),
        AggregatedEndpoint(method="POST", path="/login", baseurl="https://a",
                           service_slug="sign-in"),
    )


def test_build_projection_unbound_unit_has_empty_aggregates():
    """#201 / #200 interaction: an unenriched L1 (zero AGGREGATES edges) yields
    an empty aggregated_endpoints slot - fail-open, never a raise."""
    fake = FakeL1({
        "Service:ghost": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "ghost"},
            "edges": [],
        },
    })
    projection = _projection("Service:ghost", fake)
    assert projection.aggregated_endpoints == ()


def test_build_projection_aggregates_read_failure_degrades_the_slot():
    """#201 fail-open: a raising AGGREGATES read degrades ONLY the
    aggregated_endpoints slot (the projection survives, never a raise)."""
    fake = FakeL1({
        "Service:checkout": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "checkout"},
            "edges": [],
        },
    })

    def read(cypher, params):
        if "AGGREGATES" in cypher:
            raise RuntimeError("aggregates read failed (fixture)")
        return fake.read(cypher, params)

    projection = _projection("Service:checkout", read)
    assert projection.aggregated_endpoints == ()
    assert any("aggregated" in d for d in projection.diagnostics)


def test_build_projection_ignores_non_system_targets():
    # one-hop typed SURFACE is System-facing; L0 targets (if any) are not
    # System kinds and stay out of the typed edges
    fake = FakeL1({
        "Service:checkout": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "checkout"},
            "edges": [_edge_row("EXPOSED_VIA", ["L1System"], target_props={"kind": "RESTApi"}),
                      _edge_row("AGGREGATES", ["L0Endpoint"])],
        },
    })
    projection = _projection("Service:checkout", fake)
    assert set(projection.edges) == {"EXPOSED_VIA"}


# --- rich projection (candidates-rewrite spec 3.6), additive over the thin ---

def test_data_items_explode_to_full_lists():
    # defect 3: PRODUCES/CONSUMES edges resolve to the FULL DataItem node list
    # (name/type/sensitivity/fields/notes + raw props), not just counts
    fake = FakeL1({
        "Service:orders": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "orders"},
            "edges": [
                _edge_row("PRODUCES", ["L1DataItem"], target_props={
                    "item_key": "order", "name": "order", "type": "record",
                    "sensitivity": "high", "fields": ["id", "total"],
                    "notes": "an order record"}),
                _edge_row("CONSUMES", ["L1DataItem"], target_props={
                    "item_key": "session_token", "name": "session token",
                    "type": "secret", "sensitivity": "critical"}),
            ],
        },
    })
    projection = _projection("Service:orders", fake)
    assert projection.data_edges == {"PRODUCES": 1, "CONSUMES": 1}
    assert projection.data_items["PRODUCES"] == (
        DataItem(item_key="order", name="order", type="record", sensitivity="high",
                 fields=("id", "total"), notes="an order record",
                 props={"item_key": "order", "name": "order", "type": "record",
                        "sensitivity": "high", "fields": ["id", "total"],
                        "notes": "an order record"}),
    )
    assert projection.data_items["CONSUMES"] == (
        DataItem(item_key="session_token", name="session token", type="secret",
                 sensitivity="critical",
                 props={"item_key": "session_token", "name": "session token",
                        "type": "secret", "sensitivity": "critical"}),
    )


def test_edged_systems_unpack_fully():
    # defect 3: an outgoing Service->System edge resolves to the target System
    # fully unpacked (kind/discriminator/exposure/description/raw props), not
    # the collapsed (family, target_kind, role) triple
    fake = FakeL1({
        "Service:checkout": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "checkout"},
            "edges": [
                _edge_row("EXPOSED_VIA", ["L1System"], target_props={
                    "kind": "WebPresentation", "discriminator": "checkout::cart",
                    "exposure": "public", "description": "the cart pages",
                    "rendering_model": "CSR"}),
                _edge_row("AUTHORIZED_BY", ["L1System"], role="admin", target_props={
                    "kind": "AuthorizationSystem", "discriminator": "__singleton__"}),
            ],
        },
    })
    projection = _projection("Service:checkout", fake)
    wp = projection.edges["EXPOSED_VIA"][0]
    assert wp.target_kind == "WebPresentation"
    assert wp.target == SystemInfo(
        kind="WebPresentation", discriminator="checkout::cart", exposure="public",
        description="the cart pages",
        props={"kind": "WebPresentation", "discriminator": "checkout::cart",
               "exposure": "public", "description": "the cart pages",
               "rendering_model": "CSR"})
    auth = projection.edges["AUTHORIZED_BY"][0]
    assert auth.role == "admin"
    assert auth.target.kind == "AuthorizationSystem"


def test_data_relationship_kinds_chain_verbatim():
    # defect 3: connected DataItems resolve relationship edges VERBATIM as kind
    # chains (the edge type IS the kind, L1D-13), with ordered endpoints
    fake = FakeL1({
        "Service:orders": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "orders"},
            "edges": [
                _edge_row("PRODUCES", ["L1DataItem"], target_props={"item_key": "line"}),
                _edge_row("PRODUCES", ["L1DataItem"], target_props={"item_key": "basket"}),
            ],
            "data_rel_rows": [
                {"family": "DERIVED_FROM", "from_key": "line", "to_key": "basket",
                 "rprops": {"predicate": "line = basket.items", "rationale": "a line derives"}},
                {"family": "SUBSET_OF", "from_key": "basket", "to_key": "line",
                 "rprops": {}},
            ],
        },
    })
    projection = _projection("Service:orders", fake)
    assert projection.data_rel_kinds == frozenset({"DERIVED_FROM", "SUBSET_OF"})
    assert projection.data_relationships == (
        DataRelationship(
            family="DERIVED_FROM", from_item_key="line", to_item_key="basket",
            from_item=DataItem(item_key="line", props={"item_key": "line"}),
            to_item=DataItem(item_key="basket", props={"item_key": "basket"}),
            predicate="line = basket.items", rationale="a line derives"),
        DataRelationship(
            family="SUBSET_OF", from_item_key="basket", to_item_key="line",
            from_item=DataItem(item_key="basket", props={"item_key": "basket"}),
            to_item=DataItem(item_key="line", props={"item_key": "line"})),
    )


def test_d3_system_cooperating_systems_adjacency():
    # D3 (spec 3.7 Q5): a System unit lands the inverse adjacency hop - the
    # served Services + neighbouring Systems over the §6 System families, both
    # directions (mirror of dfs_down); a Service unit carries an EMPTY slot.
    service = {"family": "EXPOSED_VIA", "nlabels": ["L1Service"],
               "nprops": {"business_function_slug": "checkout", "exposure": "public"}}
    peer = {"family": "DEPENDS_ON", "nlabels": ["L1System"],
            "nprops": {"kind": "ReverseProxy", "discriminator": "proxy-1",
                       "exposure": "public"}}
    fake = FakeL1({
        "WAF:__singleton__": {
            "labels": ["L1System"],
            "props": {"kind": "WAF", "discriminator": "__singleton__"},
            "edges": [],
            "adj": {"ins": [service], "outs": [peer]},
        },
    })
    projection = _projection("WAF:__singleton__", fake)
    assert projection.kind == "WAF"
    assert projection.cooperating_systems == {
        "EXPOSED_VIA": (SystemInfo(kind="Service", discriminator="checkout",
                                   exposure="public",
                                   props={"business_function_slug": "checkout",
                                          "exposure": "public"}),),
        "DEPENDS_ON": (SystemInfo(kind="ReverseProxy", discriminator="proxy-1",
                                  exposure="public",
                                  props={"kind": "ReverseProxy",
                                         "discriminator": "proxy-1",
                                         "exposure": "public"}),),
    }
    # a Service unit does not run the D3 hop - empty adjacency (fail-open)
    service_fake = FakeL1({
        "Service:checkout": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "checkout"},
            "edges": [_edge_row("EXPOSED_VIA", ["L1System"], target_props={"kind": "WAF"})],
        },
    })
    s = _projection("Service:checkout", service_fake)
    assert s.cooperating_systems == {}
    assert len(service_fake.calls) == 3  # unit row + data-rel + AGGREGATES, no D3


# --- per-slot degrade: absent rich data -> empty slot, never a raise -----------

def test_absent_data_items_degrade_to_empty_slot():
    # a unit with no PRODUCES/CONSUMES edges carries an empty data_items surface
    fake = FakeL1({
        "Service:sign-in": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "sign-in"},
            "edges": [_edge_row("EXPOSED_VIA", ["L1System"], target_props={"kind": "RESTApi"})],
        },
    })
    projection = _projection("Service:sign-in", fake)
    assert projection.data_items == {}

    # untyped data-flow edges (no item props at all) still resolve - the full
    # item surfaces with None slots, never a raise
    fake2 = FakeL1({
        "Service:orders": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "orders"},
            "edges": [_edge_row("CONSUMES", ["L1DataItem"])],
        },
    })
    assert _projection("Service:orders", fake2).data_items["CONSUMES"][0].item_key is None


def test_absent_system_props_degrade_to_empty_slots():
    # a System-edge target with no props unpacks to an empty SystemInfo (kind
    # absent), never a raise and never a prune signal
    fake = FakeL1({
        "Service:checkout": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "checkout"},
            "edges": [_edge_row("EXPOSED_VIA", ["L1System"])],
        },
    })
    edge = _projection("Service:checkout", fake).edges["EXPOSED_VIA"][0]
    assert edge.target_kind is None
    assert edge.target == SystemInfo(kind="", props={})


def test_absent_d3_adjacency_degrades_to_empty():
    # a System unit with no cooperating-systems adjacency (or a D3 read gap)
    # surfaces an EMPTY cooperating_systems slot - never a raise, never a prune
    fake = FakeL1({
        "WAF:__singleton__": {
            "labels": ["L1System"],
            "props": {"kind": "WAF", "discriminator": "__singleton__"},
            "edges": [],
        },
    })
    projection = _projection("WAF:__singleton__", fake)
    assert projection.cooperating_systems == {}


def test_absent_data_rel_chains_degrade_to_empty():
    # a unit whose items share no relationship edges surfaces an empty chain
    # list; untyped relationship rows are dropped, never a raise
    fake = FakeL1({
        "Service:orders": {
            "labels": ["L1Service"],
            "props": {"business_function_slug": "orders"},
            "edges": [_edge_row("PRODUCES", ["L1DataItem"], target_props={"item_key": "line"})],
            "data_rel_rows": [{"family": "BOGUS_REL", "from_key": "line"}],
        },
    })
    projection = _projection("Service:orders", fake)
    assert projection.data_rel_kinds == frozenset()
    assert projection.data_relationships == ()
