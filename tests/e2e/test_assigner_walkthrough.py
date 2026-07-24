"""Walkthrough predicate (e2e tier) for increment 2b slice 1 - the cross-layer
Assigner (#25, agent spec #8). Mechanises E1: a 5-endpoint service chunk with mixed
confidence, one reused + one minted Service, through the full shaping.

Injected invoke_fn; no live LLM/graph. Expected values from the spec. Verifier-gated.
"""
from polymerhus.analysis.analyser_types import (
    AggregatesProposal,
    L1DeltaBatch,
    ServiceProposal,
)
from polymerhus.analysis.assigner import assign
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.recon.domain.types import AssetDelta


def _agg(service, path, conf):
    return AggregatesProposal(
        service_slug=service,
        l0=L0Ref(label="Endpoint", identity={"path": path, "method": "GET", "baseurl": "https://a"}),
        confidence=conf, evidence_refs=[f"obs:{path}"],
    )


def test_E1_five_endpoint_chunk_mixed_confidence_reused_and_minted():
    chunk = Chunk(chunk_id="katana:service:0", source_job="katana", concern="service", assets=tuple(
        AssetDelta(type="Endpoint", identity={"path": p, "method": "GET", "baseurl": "https://a"})
        for p in ("/a", "/b", "/c", "/d", "/e")
    ))
    raw = L1DeltaBatch(
        services=[
            ServiceProposal(business_function_slug="checkout", props={"exposure": "public", "label": "Checkout"}),
            ServiceProposal(business_function_slug="pay", props={"exposure": "authenticated"}),
        ],
        aggregates=[
            _agg("checkout", "/a", 0.90),
            _agg("checkout", "/b", 0.95),
            _agg("checkout", "/c", 0.60),  # withheld
            _agg("pay", "/d", 0.80),
            _agg("pay", "/e", 0.40),        # withheld
        ],
    )

    out = assign(chunk, invoke_fn=lambda m: raw, existing_slugs=frozenset({"pay"}), bar=0.75)

    surviving = {a.l0.identity["path"] for a in out.aggregates}
    assert surviving == {"/a", "/b", "/d"}   # /c (0.60) and /e (0.40) withheld
    assert len(out.aggregates) == 3

    props = {s.business_function_slug: s.props for s in out.services}
    assert props["checkout"] == {"exposure": "public"}  # minted -> exposure-only, label dropped
    assert props["pay"] == {}                            # reused -> empty props

    assert out.systems == [] and out.system_edges == []
    assert out.data_items == [] and out.data_flows == []
