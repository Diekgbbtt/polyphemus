"""Contract predicates (integration tier) for increment 2b slice 1 - the cross-layer
Assigner (#25, agent spec #8). Mechanises P1-P3, P5-P8.

The withholding gate + exposure baseline + fail-open, over crafted proposals and an
injected invoke_fn (no live LLM/graph). Expected values from the spec. Verifier-gated;
not selected by the tdd unit loop.
"""
from polymerhus.analysis.analyser_types import (
    AggregatesProposal,
    L1DeltaBatch,
    ServiceProposal,
    SystemProposal,
)
from polymerhus.analysis.assigner import (
    apply_service_baseline,
    assign,
    narrow_to_assignment,
    shape_proposal,
    withhold_below_bar,
)
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.recon.domain.types import AssetDelta


def _agg(path, conf):
    return AggregatesProposal(
        service_slug="checkout",
        l0=L0Ref(label="Endpoint", identity={"path": path, "method": "GET", "baseurl": "https://a"}),
        confidence=conf, evidence_refs=[f"obs:{path}"],
    )


# --- P1: the withholding gate -------------------------------------------------

def test_P1_withhold_below_bar_drops_low_confidence():
    batch = L1DeltaBatch(aggregates=[_agg("/x", 0.9), _agg("/y", 0.5), _agg("/z", 0.75)])
    out = withhold_below_bar(batch, bar=0.75)
    assert {a.l0.identity["path"] for a in out.aggregates} == {"/x", "/z"}  # /y dropped


# --- P2: above-bar -> well-formed ---------------------------------------------

def test_P2_above_bar_carries_confidence_and_evidence():
    batch = L1DeltaBatch(aggregates=[_agg("/x", 0.9)])
    out = withhold_below_bar(batch, bar=0.75)
    (survivor,) = out.aggregates
    assert survivor.confidence == 0.9
    assert survivor.evidence_refs == ["obs:/x"]


# --- P3: reused Service -> empty props ----------------------------------------

def test_P3_reused_service_emitted_with_empty_props():
    raw = L1DeltaBatch(services=[ServiceProposal(business_function_slug="pay", props={"exposure": "bogus"})])
    out = apply_service_baseline(raw, minted_slugs=frozenset())  # pay is reused (not minted)
    assert out.services[0].props == {}


# --- P5: minted Service -> exposure-only --------------------------------------

def test_P5_minted_service_keeps_only_valid_exposure():
    raw = L1DeltaBatch(services=[
        ServiceProposal(business_function_slug="checkout", props={"exposure": "public", "label": "X", "salience": "high"}),
        ServiceProposal(business_function_slug="pay", props={"exposure": "bogus"}),
    ])
    out = apply_service_baseline(raw, minted_slugs=frozenset({"checkout", "pay"}))
    props = {s.business_function_slug: s.props for s in out.services}
    assert props["checkout"] == {"exposure": "public"}  # label/salience dropped
    assert props["pay"] == {}  # invalid exposure dropped


# --- P5b (#29): the minted Service carries its service_contract ----------------

def test_P5b_minted_service_keeps_its_service_contract():
    """A minted Service is minted BECAUSE no existing identity covered the surface, so
    the next chunk meets it in the inventory with nothing to route on unless it
    describes itself. Dropping the contract here would make Assigner-minted Services
    second-class - matchable only for the Bootstrapper's."""
    raw = L1DeltaBatch(services=[ServiceProposal(
        business_function_slug="webhooks",
        props={"exposure": "authenticated", "label": "X",
               "service_contract": "Register and deliver  outbound\nevent callbacks."},
    )])
    out = apply_service_baseline(raw, minted_slugs=frozenset({"webhooks"}))
    assert out.services[0].props == {
        "exposure": "authenticated",
        # whitespace collapsed, label dropped
        "service_contract": "Register and deliver outbound event callbacks.",
    }


def test_P5c_reused_service_contract_is_not_re_emitted():
    """The Bootstrapper read the WHOLE architecture to write the contract; the Assigner
    sees one chunk of surface. So for a Service that already exists the Assigner is
    never the better source, and emitting empty props keeps the idempotent MERGE from
    clobbering the richer stored contract (AMV-12)."""
    raw = L1DeltaBatch(services=[ServiceProposal(
        business_function_slug="checkout",
        props={"exposure": "public", "service_contract": "thin chunk-local guess"},
    )])
    out = apply_service_baseline(raw, minted_slugs=frozenset())  # reused
    assert out.services[0].props == {}


def test_P5d_blank_contract_on_a_minted_service_is_omitted():
    raw = L1DeltaBatch(services=[ServiceProposal(
        business_function_slug="x", props={"exposure": "public", "service_contract": "   "},
    )])
    out = apply_service_baseline(raw, minted_slugs=frozenset({"x"}))
    assert out.services[0].props == {"exposure": "public"}


def test_P5e_assignment_prompt_directs_the_semantic_match_against_contracts():
    """The contract is the PRIMARY routing evidence (#29): the prompt must actually
    tell the model to match path nouns against it, or the attribute is inert data."""
    from polymerhus.analysis.assigner import _assignment_prompt

    rendered = _assignment_prompt(
        {"nodes": [], "links": []},
        {"services": ["checkout"], "systems": [], "data_items": [],
         "service_contracts": {"checkout": "Take a basket to a paid order."}},
    )
    assert "Take a basket to a paid order." in rendered   # the contract is IN the prompt
    assert "contract" in rendered.lower()
    assert "path segments" in rendered                     # the match is directed
    assert "service_contract" in rendered                  # required when minting


def test_narrow_drops_non_assignment_lists():
    raw = L1DeltaBatch(systems=[SystemProposal(kind="RESTApi")], aggregates=[_agg("/x", 0.9)])
    out = narrow_to_assignment(raw)
    assert out.systems == [] and out.system_edges == []
    assert out.aggregates  # assignment survives


# --- P6: empty / all-withheld -> empty batch ----------------------------------

def test_P6_empty_chunk_yields_empty_batch():
    assert assign(Chunk(chunk_id="c", concern="service"), invoke_fn=lambda m: None) == L1DeltaBatch()


def test_P6_all_withheld_yields_no_aggregates():
    chunk = Chunk(chunk_id="c", concern="service",
                  assets=(AssetDelta(type="Endpoint", identity={"path": "/x", "baseurl": "https://a"}),))
    raw = L1DeltaBatch(aggregates=[_agg("/x", 0.4), _agg("/y", 0.5)])
    out = assign(chunk, invoke_fn=lambda m: raw, bar=0.75)
    assert out.aggregates == []


# --- P7: idempotent -----------------------------------------------------------

def test_P7_idempotent_same_inputs_same_batch():
    chunk = Chunk(chunk_id="c", concern="service",
                  assets=(AssetDelta(type="Endpoint", identity={"path": "/x", "baseurl": "https://a"}),))
    raw = L1DeltaBatch(
        services=[ServiceProposal(business_function_slug="checkout", props={"exposure": "public"})],
        aggregates=[_agg("/x", 0.9)],
    )
    a = assign(chunk, invoke_fn=lambda m: raw, existing_slugs=frozenset())
    b = assign(chunk, invoke_fn=lambda m: raw, existing_slugs=frozenset())
    assert a == b


# --- P8: degradation ----------------------------------------------------------

def test_P8_invoke_raises_or_none_degrades_to_empty():
    chunk = Chunk(chunk_id="c", concern="service",
                  assets=(AssetDelta(type="Endpoint", identity={"path": "/x", "baseurl": "https://a"}),))

    def boom(messages):
        raise RuntimeError("llm down")

    assert assign(chunk, invoke_fn=boom) == L1DeltaBatch()
    assert assign(chunk, invoke_fn=lambda m: None) == L1DeltaBatch()
