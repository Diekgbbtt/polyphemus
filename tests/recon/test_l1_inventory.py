"""FR-INVENTORY unit tier - `read_l1_inventory` with an injected read_fn (no DB).

Encodes the FR-INVENTORY assertion ledger (AST-INV-01): the reader returns the
project's current service slugs, system `kind:disc` keys, and data-item keys
(sorted, deduped), and fails open to the empty shape on a read error.
"""
from agent.recon.analysis.l1_inventory import read_l1_inventory


def test_reads_service_slugs_systems_dataitems():
    """AST-INV-01: read_l1_inventory returns {services, systems, data_items}
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
        if "L1DataItem" in cypher:
            return [{"item_key": "shopping_basket"}, {"item_key": "order"}]
        return []

    inv = read_l1_inventory("proj-1", read_fn=fake_read)
    assert inv["services"] == ["checkout", "sign-in"]  # sorted + deduped
    # singleton -> bare kind; discriminated -> kind:disc; both sorted
    assert inv["systems"] == ["AuthenticationMechanism", "CDN:cloudflare"]
    assert inv["data_items"] == ["order", "shopping_basket"]


def test_read_error_is_fail_open():
    """AST-INV-01: a read error degrades to the empty inventory shape and never
    raises into the caller (fail-open, mirroring the analyser pod)."""
    def boom(cypher, params):
        raise RuntimeError("neo4j down")

    inv = read_l1_inventory("proj-1", read_fn=boom)
    assert inv == {"services": [], "systems": [], "data_items": []}
