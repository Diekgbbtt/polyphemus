"""FR-INVENTORY, L1-graph (operator ruling 2026-10-16): the Assigner's first human
message POSTS the current L1 graph - Services with contracts, Systems with their
description and notable attributes, and the typed Service->System edges - and the
block is REBUILT on every dispatch from the live read, so it tracks the run as it
concretises more linked systems.

A previous graph_view-capable assigner degraded quality and bloated context
(retained decision), so this is a PROMPT block fed by the per-dispatch inventory
read, not a tool the model calls.
"""
from __future__ import annotations

from polymerhus.analysis.pod import _inventory_block, l1_graph_block


def _inventory() -> dict:
    return {
        "services": ["byoc", "checkout"],
        "service_contracts": {"checkout": "Take a basket to a paid order."},
        "systems": ["AuthenticationMechanism", "CDN:cloudflare"],
        "system_descriptions": {
            "AuthenticationMechanism": "Password login; no MFA seen.",
            "CDN:cloudflare": "Edge cache.",
        },
        "system_details": {"CDN:cloudflare": {"product": "cloudflare", "note": "edge cache"}},
        "edges": [
            {"service_slug": "checkout", "rel": "EXPOSED_VIA", "system_key": "RESTApi",
             "role": None, "realm": "public", "order": None},
            {"service_slug": "checkout", "rel": "AUTHENTICATED_BY",
             "system_key": "AuthenticationMechanism",
             "role": None, "realm": "credential", "order": None},
            {"service_slug": "byoc", "rel": "AUTHORIZED_BY",
             "system_key": "AuthorizationSystem:seller",
             "role": "seller-admin", "realm": None, "order": 1},
        ],
    }


def test_services_render_with_their_contracts_and_bare_slugs():
    block = l1_graph_block(_inventory())
    assert "- checkout - Take a basket to a paid order." in block
    assert "- byoc\n" in block           # contract-less Service still listed


def test_systems_render_description_and_notable_attributes():
    block = l1_graph_block(_inventory())
    assert "- AuthenticationMechanism :: Password login; no MFA seen." in block
    # singleton elided; description plus sorted notable attributes
    assert "- CDN:cloudflare :: Edge cache. {note=edge cache, product=cloudflare}" in block


def test_edges_render_typed_with_role_realm_order_when_set():
    block = l1_graph_block(_inventory())
    assert "- checkout -[EXPOSED_VIA]-> RESTApi (realm=public)" in block
    assert "- byoc -[AUTHORIZED_BY]-> AuthorizationSystem:seller (role=seller-admin, order=1)" in block


def test_block_carries_the_identity_reuse_discipline_and_is_untruncated():
    block = l1_graph_block(_inventory())
    assert "reuse these EXACT keys, do NOT coin a synonym" in block
    # every edge and system present (L1 is small; never truncated)
    for token in ("EXPOSED_VIA", "AUTHENTICATED_BY", "AUTHORIZED_BY",
                  "AuthenticationMechanism", "CDN:cloudflare", "RESTApi"):
        assert token in block


def test_empty_inventory_renders_none_yet_sections():
    block = l1_graph_block({})
    assert block.count("(none yet)") == 3   # Services, Systems, Edges
    assert l1_graph_block(None).count("(none yet)") == 3


def test_edges_are_stably_sorted():
    inv = _inventory()
    inv["edges"] = list(reversed(inv["edges"]))
    first = l1_graph_block(inv)
    second = l1_graph_block(inv)
    assert first == second
    # (service_slug, rel) ordering: byoc/AUTHORIZED_BY precedes checkout/*
    assert first.index("byoc -[AUTHORIZED_BY]") < first.index("checkout -[AUTHENTICATED_BY]")


def test_inventory_block_stays_untouched_for_its_other_consumers():
    """`_inventory_block` is kept for bootstrap: the richer graph block REPLACES it
    only in the Assigner prompt. It must not gain Systems-with-descriptions or edges."""
    rendered = _inventory_block({"services": ["checkout"], "systems": [],
                                 "service_contracts": {}})
    assert "EXPOSED_VIA" not in rendered
    assert "::" not in rendered


def test_assigner_user_prompt_posts_the_graph_block():
    from polymerhus.analysis.assigner import _user_prompt

    prompt = _user_prompt({"nodes": [], "edges": []}, _inventory())
    assert "reuse these EXACT keys, do NOT coin a synonym" in prompt
    assert "Take a basket to a paid order." in prompt
    assert "Password login; no MFA seen." in prompt
    assert "- checkout -[EXPOSED_VIA]-> RESTApi (realm=public)" in prompt
    # the identity lists are NOT duplicated (the graph block replaces _inventory_block)
    assert "EXISTING L1 IDENTITIES" not in prompt
    assert prompt.count("Services (business_function_slug") == 1


def test_user_prompt_rebuilds_the_block_per_dispatch_from_the_live_read():
    """The inventory read is LIVE per dispatch and the block is rebuilt every time,
    so a later chunk sees the graph the earlier chunks concretised."""
    from types import SimpleNamespace

    from polymerhus.analysis.assigner import make_assigner_body
    from polymerhus.analysis.chunking import Chunk
    from polymerhus.recon.domain.types import AssetDelta

    inventories = [
        {"services": ["checkout"], "systems": []},
        {"services": ["checkout", "byoc"], "systems": ["CDN:cloudflare"],
         "system_details": {"CDN:cloudflare": {"product": "cloudflare"}},
         "edges": [{"service_slug": "checkout", "rel": "EXPOSED_VIA",
                    "system_key": "CDN:cloudflare", "role": None, "realm": None,
                    "order": None}]},
    ]
    seen = {"reads": 0, "prompts": []}

    def inventory_fn(pid):
        inv = inventories[seen["reads"]]
        seen["reads"] += 1
        return inv

    def invoke_fn(messages, *, schema=None, system_prompt=None):
        from polymerhus.analysis.analyser_types import L1DeltaBatch
        seen["prompts"].append(messages[0].content)
        return L1DeltaBatch()

    chunk = Chunk(chunk_id="c", assets=(
        AssetDelta(type="Endpoint", identity={"path": "/x", "baseurl": "https://a"}),))
    body = make_assigner_body(invoke_fn=invoke_fn, inventory_fn=inventory_fn)

    dispatch = SimpleNamespace(dispatch_id="d1", role="assigner", phase="A1",
                               mode="create", chunk=chunk)
    body(dispatch, {"project_id": "p", "run_id": "r"})
    body(dispatch, {"project_id": "p", "run_id": "r"})

    assert seen["reads"] == 2                       # LIVE per dispatch, never frozen
    assert "byoc" not in seen["prompts"][0]         # first dispatch: checkout only
    assert "byoc" in seen["prompts"][1]             # second dispatch: the concretised graph
    assert "CDN:cloudflare {product=cloudflare}" in seen["prompts"][1]
    assert "- checkout -[EXPOSED_VIA]-> CDN:cloudflare" in seen["prompts"][1]
