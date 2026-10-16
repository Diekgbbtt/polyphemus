"""FR-INVENTORY unit tier - `read_l1_inventory` with an injected read_fn (no DB).

Encodes the FR-INVENTORY assertion ledger (AST-INV-01): the reader returns the
project's current service slugs and system `kind:disc` keys (sorted, deduped),
and fails open to the empty shape on a read error.
"""
from polymerhus.analysis.l1_inventory import _empty, read_l1_inventory


def test_reads_service_slugs_and_systems():
    """AST-INV-01: read_l1_inventory returns {services, systems}
    (sorted + deduped); a `__singleton__` system renders as its bare kind while a
    discriminated one renders `kind:disc`."""
    def fake_read(cypher, params):
        assert params == {"project_id": "proj-1"}
        if "L1Service" in cypher:
            # a duplicate slug proves dedup; unsorted input proves the sort
            return [{"slug": "sign-in"}, {"slug": "checkout"}, {"slug": "sign-in"}]
        if "L1System" in cypher:
            return [
                {"kind": "AuthenticationMechanism", "disc": "__singleton__"},
                {"kind": "CDN", "disc": "cloudflare"},
            ]
        return []

    inv = read_l1_inventory("proj-1", read_fn=fake_read)
    assert inv["services"] == ["checkout", "sign-in"]  # sorted + deduped
    # singleton -> bare kind; discriminated -> kind:disc; both sorted
    assert inv["systems"] == ["AuthenticationMechanism", "CDN:cloudflare"]


def test_read_error_is_fail_open():
    """AST-INV-01: a read error degrades to the empty inventory shape and never
    raises into the caller (fail-open, mirroring the analyser pod). The L1-graph
    keys (`system_details`, `edges`) are ADDITIVE to that empty shape too."""
    def boom(cypher, params):
        raise RuntimeError("neo4j down")

    inv = read_l1_inventory("proj-1", read_fn=boom, settings_fn=lambda pid: {})
    assert inv == {"services": [], "systems": [],
                   "service_contracts": {}, "system_descriptions": {},
                   "system_details": {}, "edges": [],
                   "application_overview": ""}


def test_system_details_carry_non_bookkeeping_attributes_only():
    """The L1-graph read (2026-10-16): a System's NOTABLE attributes ride beside
    its description. Identity/provenance/lifecycle keys (kind, discriminator,
    project_id, first/last_seen, prov_*) and the description itself are NOT
    notable attributes - they are surface elsewhere. A System with no notable
    attribute contributes no entry (absence means nothing extra to show)."""
    def fake_read(cypher, params):
        if "-[r]->" in cypher:
            return []
        if "business_function_slug AS slug" in cypher:
            return []
        if "properties(n) AS props" in cypher:
            return [
                {"kind": "CDN", "disc": "cloudflare", "description": "Edge cache.",
                 "props": {"kind": "CDN", "discriminator": "cloudflare",
                           "description": "Edge cache.", "project_id": "proj-1",
                           "first_seen": "t0", "last_seen": "t1", "prov_job": "j",
                           "prov_model": "m", "prov_prompt_id": "p",
                           "product": "cloudflare", "note": "edge cache"}},
                {"kind": "WAF", "disc": "__singleton__", "description": "",
                 "props": {"kind": "WAF", "discriminator": "__singleton__"}},
            ]
        return []

    inv = read_l1_inventory("proj-1", read_fn=fake_read)
    assert inv["system_details"] == {
        "CDN:cloudflare": {"product": "cloudflare", "note": "edge cache"},
    }
    assert _empty()["system_details"] == {}   # additive in the empty shape too


def test_edges_are_returned_typed_with_role_realm_order():
    """The L1-graph read (2026-10-16): the typed `Service -> System` edges with
    their role/realm/order sub-granularity, keyed by the same `kind[:disc]` shape
    as the Systems list. Rel labels outside the `SYSTEM_EDGE_RELS` allowlist (an
    `AGGREGATES` cross-layer edge, or a stale rel) are dropped - only the §6 edge
    taxonomy is the L1 graph."""
    def fake_read(cypher, params):
        if "-[r]->" in cypher:
            return [
                {"service_slug": "checkout", "rel": "EXPOSED_VIA", "kind": "RESTApi",
                 "disc": "__singleton__", "role": None, "realm": "public", "order": None},
                {"service_slug": "checkout", "rel": "AUTHORIZED_BY",
                 "kind": "AuthorizationSystem", "disc": "seller",
                 "role": "seller-admin", "realm": None, "order": 1},
                # not a System-edge rel -> dropped (the allowlist is the boundary)
                {"service_slug": "checkout", "rel": "AGGREGATES", "kind": "RESTApi",
                 "disc": "__singleton__", "role": None, "realm": None, "order": None},
            ]
        if "business_function_slug AS slug" in cypher:
            return []
        if "properties(n) AS props" in cypher:
            return []
        return []

    inv = read_l1_inventory("proj-1", read_fn=fake_read)
    assert inv["edges"] == [
        {"service_slug": "checkout", "rel": "AUTHORIZED_BY",
         "system_key": "AuthorizationSystem:seller",
         "role": "seller-admin", "realm": None, "order": 1},
        {"service_slug": "checkout", "rel": "EXPOSED_VIA", "system_key": "RESTApi",
         "role": None, "realm": "public", "order": None},
    ]
    assert _empty()["edges"] == []            # additive in the empty shape too


def test_edges_read_failure_degrades_only_the_edges():
    """Fail-open refinement: the edge read is its own try, so a failing edge read
    degrades `edges` to [] without discarding the Service/System identity reads."""
    def fake_read(cypher, params):
        if "-[r]->" in cypher:
            raise RuntimeError("edge read down")
        if "business_function_slug AS slug" in cypher:
            return [{"slug": "checkout", "contract": None}]
        if "properties(n) AS props" in cypher:
            return [{"kind": "RESTApi", "disc": "__singleton__",
                     "description": "", "props": {}}]
        return []

    inv = read_l1_inventory("proj-1", read_fn=fake_read, settings_fn=lambda pid: {})
    assert inv["services"] == ["checkout"]
    assert inv["systems"] == ["RESTApi"]
    assert inv["edges"] == []


def test_service_contracts_are_returned_alongside_the_slugs():
    """#29: the contract map is ADDITIVE - `services` stays a plain slug list so the
    existing call sites are untouched, and the routing profile rides beside it."""
    def fake_read(cypher, params):
        if "L1Service" in cypher:
            return [
                {"slug": "checkout", "contract": "Take a basket to a paid order."},
                {"slug": "byoc", "contract": None},       # not yet filled
                {"slug": "docs", "contract": "   "},      # blank -> not a contract
            ]
        return []

    inv = read_l1_inventory("proj-1", read_fn=fake_read)
    assert inv["services"] == ["byoc", "checkout", "docs"]
    # only Services that actually carry one appear; absence means not-yet-filled
    assert inv["service_contracts"] == {"checkout": "Take a basket to a paid order."}
