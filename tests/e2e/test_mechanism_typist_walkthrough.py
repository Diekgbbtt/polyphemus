"""Walkthrough predicate (e2e tier) for the REWRITTEN TechnicalSystem Analyser
(`mechanism_typist`, ticket #9) - the GRILLED 3-call design. Mechanises W-N1: one
full traced path from a `mechanism_typist` A.1 dispatch over a fixture `service`
surface to the exact typing deltas handed to the sole-writer.

Replaces the retired A.1a walkthrough (W-A1 / per-service WebPresentation is VOID -
WebPresentation is Phase B).

NOTE ON THE LIVE EDGE (verifier honesty, to-assertions §4). A fully-live walkthrough
would stand the async supervisor stack up, DISPATCH a mechanism_typist step on the
real schedule, and read the System nodes/edges back out of Neo4j with their
`prov_job`. That is DEFERRED by operator ruling (grilled #9, Option B): the body is
register-ready but the schedule flip (dissolving the legacy two-pass into
assigner-assignment-only + mechanism_typist + data_modeller) is a coordinated 2b
increment gated on the data_modeller + the #34 Assigner re-homing. So this walkthrough
mirrors the established `test_assigner_walkthrough` precedent: it drives the REAL
proposer body over a fixture `service` chunk with an injected `invoke_fn`, and asserts
the exact deltas the sole-writer would MERGE. Promote to a live-graph readback +
`prov_job` assertion once the schedule flip lands.

NOT RUN by the verifier (e2e tier; and dispatch deferred). Expected values from the
build spec (§10 W-N1), never recomputed the way the code computes them.
"""
from polymerhus.analysis.analyser_types import L1DeltaBatch, SystemEdgeProposal, SystemProposal
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.mechanism_typist import type_mechanisms
from polymerhus.recon.domain.types import AssetDelta

# The fixture surface: a 3-endpoint `service` chunk owned (via the Assigner's prior
# AGGREGATES) by two Services - `checkout` (primary here) and `account`.
_BASEURL = "https://soupmarket.shop"
_FIXTURE_ASSETS = tuple(
    AssetDelta(type="Endpoint", identity={"path": p, "baseurl": _BASEURL})
    for p in ("/api/BasketItems", "/api/Orders", "/rest/user/whoami")
)
_FIXTURE_AGGREGATIONS = [
    {"slug": "checkout", "labels": ["Endpoint"], "props": {"path": "/api/BasketItems", "baseurl": _BASEURL}},
    {"slug": "checkout", "labels": ["Endpoint"], "props": {"path": "/api/Orders", "baseurl": _BASEURL}},
    {"slug": "account", "labels": ["Endpoint"], "props": {"path": "/rest/user/whoami", "baseurl": _BASEURL}},
]
_FIXTURE_INVENTORY = {"services": ["checkout", "account"], "systems": [], "system_descriptions": {}}


def _scripted_invoke(messages, *, schema=None):
    """The proposer's LLM, scripted to the fixture: reflection prose, then the two
    structured extractions (systems, then linking). Routed by prompt marker so a
    bounded_retry re-call of a step is stable."""
    prompt = messages[-1].content
    if schema is None:
        return ("The JSON REST endpoints evidence a shared RESTApi paradigm overlay; the "
                "session cookie on /whoami evidences an IdentificationSystem. No WAF proven.")
    if "TASK - EXTRACT SYSTEMS" in prompt:
        return L1DeltaBatch(systems=[
            SystemProposal(kind="RESTApi", props={"description": "JSON REST paradigm the app exposes through."}),
            SystemProposal(kind="IdentificationSystem", props={"description": "Cookie/session identity for principals."}),
        ])
    if "TASK - LINK SERVICES" in prompt:
        return L1DeltaBatch(system_edges=[
            SystemEdgeProposal(service_slug="checkout", kind="RESTApi", rel="EXPOSED_VIA"),
            SystemEdgeProposal(service_slug="account", kind="RESTApi", rel="EXPOSED_VIA"),
            SystemEdgeProposal(service_slug="account", kind="IdentificationSystem", rel="IDENTIFIED_BY"),
        ])
    return None


def test_W_N1_three_endpoint_service_chunk_types_shared_systems_and_links():
    chunk = Chunk(chunk_id="katana:service:0", source_job="katana", concern="service",
                  assets=_FIXTURE_ASSETS)

    out = type_mechanisms(chunk, invoke_fn=_scripted_invoke,
                          inventory=_FIXTURE_INVENTORY, aggregations=_FIXTURE_AGGREGATIONS)

    # Terminal quantities (exact, from the spec): 2 shared Systems, 3 typed edges.
    assert {(s.kind, s.discriminator) for s in out.systems} == {
        ("RESTApi", "__singleton__"), ("IdentificationSystem", "__singleton__")}
    assert len(out.systems) == 2

    edges = {(e.service_slug, e.kind, e.rel) for e in out.system_edges}
    assert edges == {
        ("checkout", "RESTApi", "EXPOSED_VIA"),
        ("account", "RESTApi", "EXPOSED_VIA"),
        ("account", "IdentificationSystem", "IDENTIFIED_BY"),
    }
    assert len(out.system_edges) == 3

    # The typist writes NOTHING on the assignment or data planes (breadth systems-only).
    assert out.services == [] and out.aggregates == []
    assert out.data_items == [] and out.surfaces_at == [] and out.data_flows == [] and out.data_relationships == []

    # Every emitted value is in the controlled vocabulary (the sole-writer would accept it).
    from polymerhus.analysis.l1_curator import _KNOWN_KINDS, SYSTEM_EDGE_RELS
    assert all(s.kind in _KNOWN_KINDS for s in out.systems)
    assert all(e.kind in _KNOWN_KINDS and e.rel in SYSTEM_EDGE_RELS for e in out.system_edges)
