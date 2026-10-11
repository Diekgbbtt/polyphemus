"""Contract predicates (integration tier) for the TechnicalSystem Analyser
(`mechanism_typist`, agent spec #9) after the T2 reasoning-workflow rewrite.

Mechanises N1-N11 of the build spec (§10) against the DECOMPOSED 4-sub-problem
chain (mechanism_hypotheses -> page_clusters -> systems_extract -> link), every
turn speaking the ONE structured envelope `AnalysisTurn`. The retired 3-call
prompt helpers are gone; the tests exercise the workflow's own rendered prompts.

Injected `invoke_fn(messages, *, schema, system_prompt)` + injected reads: no
live LLM/graph (mirrors `test_assigner_contracts`). Expected values come from
the spec, never recomputed the way the code computes them. Verifier-gated; not
selected by the tdd loop.
"""
import inspect

from polymerhus.analysis.analyser_types import (
    L1DeltaBatch,
    ServiceProposal,
    SystemEdgeProposal,
    SystemProposal,
)
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.mechanism_typist import (
    WORKFLOW,
    _defined_systems_block,
    _linking_context,
    drop_unknown_vocabulary,
    mechanism_typist_body,
    narrow_to_typing,
    partition_services,
    type_mechanisms,
)
from polymerhus.analysis.reasoning_workflow import (
    AnalysisTurn,
    Claim,
    render_turn,
)
from polymerhus.recon.domain.types import AssetDelta, Observation

# --- test doubles -------------------------------------------------------------

_SYSTEMS_MARKER = "TASK - EXTRACT SYSTEMS"
_LINKING_MARKER = "TASK - LINK SERVICES"


def _turn(*, systems=(), edges=(), claims=False):
    """An `AnalysisTurn` carrying the fields a sub-problem emits."""
    return AnalysisTurn(
        systems=list(systems),
        system_edges=list(edges),
        claims=[Claim(subject="asset", assertion="candidate", evidence="e",
                      verdict="v")] if claims else [],
    )


class ScriptedInvoke:
    """A fake `invoke_fn(messages, *, schema, system_prompt)` matching the real
    seam. Routes by the SUB-PROBLEM (the prompt marker): a reasoning turn
    (`prose=None` forces the first to exhaust), the systems-extraction turn, and
    the linking turn. Records every (schema, prompt) call for order/degradation
    predicates."""

    def __init__(self, *, prose="reflected: WAF + REST evidenced", systems=None, linking=None):
        self.prose_none = prose is None
        self.systems_none = systems is False
        self.linking_none = linking is False
        self.systems = AnalysisTurn() if systems in (None, False) else systems
        self.linking = AnalysisTurn() if linking in (None, False) else linking
        self.calls: list[tuple] = []

    def __call__(self, messages, *, schema=None, system_prompt=None):
        prompt = messages[-1].content
        self.calls.append((schema, prompt))
        assert schema is AnalysisTurn, "every turn speaks the one structured envelope"
        if _SYSTEMS_MARKER in prompt:
            return None if self.systems_none else self.systems
        if _LINKING_MARKER in prompt:
            return None if self.linking_none else self.linking
        # a reasoning sub-problem (mechanism_hypotheses / page_clusters)
        if self.prose_none:
            return None
        return _turn(claims=True)

    @property
    def schemas(self):
        return [c[0] for c in self.calls]


class _Dispatch:
    def __init__(self, phase, chunk):
        self.phase = phase
        self.chunk = chunk


def _endpoint(path, baseurl="https://a"):
    return AssetDelta(type="Endpoint", identity={"path": path, "baseurl": baseurl})


def _service_chunk(paths=("/a",)):
    return Chunk(chunk_id="katana:service:0", source_job="katana", concern="service",
                 assets=tuple(_endpoint(p) for p in paths))


def _sys(kind, disc="__singleton__", desc=None):
    props = {"description": desc} if desc else {}
    return SystemProposal(kind=kind, discriminator=disc, props=props)


def _edge(slug, kind, rel):
    return SystemEdgeProposal(service_slug=slug, kind=kind, rel=rel)


def _systems_workflow_prompt(inventory):
    """The systems_extract sub-problem's rendered human message."""
    return render_turn(WORKFLOW.sub_problems[2], {
        "inventory": _defined_systems_block(inventory),
        "vocabulary": "",
    })


def _linking_workflow_prompt(primary, secondary, owned):
    """The link sub-problem's rendered human message."""
    return render_turn(WORKFLOW.sub_problems[3], {
        "candidates": _linking_context(primary, secondary, owned),
    })


# --- N1: narrow-to-typing -----------------------------------------------------

def test_N1_narrow_to_typing_only():
    """The typist owns ONLY {systems, system_edges}; any stray service/aggregate/data
    a call leaks is dropped."""
    inv = ScriptedInvoke(
        systems=_turn(systems=[_sys("WAF")],
                      claims=False),
        linking=_turn(edges=[_edge("checkout", "WAF", "FRONTED_BY")]),
    )
    # a leaked service on the systems turn is dropped by narrow_to_typing
    inv.systems = AnalysisTurn(
        systems=[_sys("WAF")],
        services=[ServiceProposal(business_function_slug="leak")],
    )
    out = type_mechanisms(_service_chunk(), invoke_fn=inv)
    assert [s.kind for s in out.systems] == ["WAF"]
    assert [(e.service_slug, e.rel) for e in out.system_edges] == [("checkout", "FRONTED_BY")]
    assert out.services == [] and out.aggregates == []
    assert out.data_items == [] and out.surfaces_at == [] and out.data_flows == [] and out.data_relationships == []


def test_N1_narrow_pure_shaper_drops_non_typing():
    raw = L1DeltaBatch(services=[ServiceProposal(business_function_slug="x")],
                       systems=[_sys("RESTApi")],
                       system_edges=[_edge("x", "RESTApi", "EXPOSED_VIA")])
    out = narrow_to_typing(raw)
    assert out.services == [] and out.aggregates == [] and out.data_items == []
    assert out.systems and out.system_edges


# --- N2: four-call sequence in order ------------------------------------------

def test_N2_four_call_sequence_reasoning_then_extract_then_link():
    inv = ScriptedInvoke(systems=_turn(systems=[_sys("WAF")]),
                         linking=_turn(edges=[_edge("checkout", "WAF", "FRONTED_BY")]))
    type_mechanisms(_service_chunk(), invoke_fn=inv)
    assert inv.schemas == [AnalysisTurn] * 4          # hypotheses -> clusters -> systems -> link
    assert _SYSTEMS_MARKER in inv.calls[2][1]
    assert _LINKING_MARKER in inv.calls[3][1]


# --- N3: reflection fail-closed -----------------------------------------------

def test_N3_reflection_exhaustion_fails_closed():
    """A None first reasoning turn (after bounded_retry) degrades the WHOLE step
    to empty; the extraction/linking calls are NEVER made (fail-closed, not
    soft)."""
    inv = ScriptedInvoke(prose=None,
                         systems=_turn(systems=[_sys("WAF")]),
                         linking=_turn(edges=[_edge("x", "WAF", "FRONTED_BY")]))
    out = type_mechanisms(_service_chunk(), invoke_fn=inv)
    assert out == L1DeltaBatch()                                  # empty
    assert not any(_SYSTEMS_MARKER in c[1] or _LINKING_MARKER in c[1] for c in inv.calls)


# --- N4: soft pass-through for later steps ------------------------------------

def test_N4_linking_exhaustion_keeps_systems_drops_edges():
    inv = ScriptedInvoke(systems=_turn(systems=[_sys("WAF"), _sys("RESTApi")]),
                         linking=False)  # linking exhausts
    out = type_mechanisms(_service_chunk(), invoke_fn=inv)
    assert {s.kind for s in out.systems} == {"WAF", "RESTApi"}    # earlier step survives
    assert out.system_edges == []                                 # degraded, not crashed


def test_N4_systems_exhaustion_yields_no_systems_but_does_not_crash():
    inv = ScriptedInvoke(systems=False, linking=_turn())   # systems exhausts, linking empty
    out = type_mechanisms(_service_chunk(), invoke_fn=inv)
    assert out.systems == []                                      # degraded
    assert any(_LINKING_MARKER in c[1] for c in inv.calls)        # linking STILL attempted (soft, not fail-closed)


# --- N5: controlled vocabulary only -------------------------------------------

def test_N5_out_of_vocabulary_systems_and_edges_dropped_end_to_end():
    inv = ScriptedInvoke(
        systems=_turn(systems=[_sys("RESTApi"), _sys("RenderingSystem_CSR_JSMap")]),  # 2nd is Phase-B-retired
        linking=_turn(edges=[
            _edge("x", "RESTApi", "EXPOSED_VIA"),
            _edge("x", "RESTApi", "RENDERED_BY"),     # deleted rel
            _edge("x", "BogusKind", "EXPOSED_VIA"),   # unknown kind
        ]),
    )
    out = type_mechanisms(_service_chunk(), invoke_fn=inv)
    assert [s.kind for s in out.systems] == ["RESTApi"]
    assert [(e.kind, e.rel) for e in out.system_edges] == [("RESTApi", "EXPOSED_VIA")]


def test_N5_drop_unknown_vocabulary_pure():
    kinds = frozenset({"RESTApi"})
    rels = frozenset({"EXPOSED_VIA"})
    raw = L1DeltaBatch(systems=[_sys("RESTApi"), _sys("WebPresentation")],
                       system_edges=[_edge("x", "RESTApi", "EXPOSED_VIA"),
                                     _edge("x", "RESTApi", "RENDERED_BY")])
    out = drop_unknown_vocabulary(raw, kinds=kinds, rels=rels)
    assert [s.kind for s in out.systems] == ["RESTApi"]
    assert [(e.kind, e.rel) for e in out.system_edges] == [("RESTApi", "EXPOSED_VIA")]


# --- N6: new-vs-extend, compounding description -------------------------------

def test_N6_extract_prompt_shows_existing_description_and_demands_enrichment():
    """The System `description` is the discriminative attribute; on extend it is
    COMPOUNDED, never blanked. The extraction prompt must SHOW the existing
    description and DIRECT enrichment - else the model cannot compound."""
    inv = {"systems": ["AuthenticationMechanism"],
           "system_descriptions": {"AuthenticationMechanism": "Mints session cookies; no MFA seen."}}
    prompt = _systems_workflow_prompt(inv)
    assert "Mints session cookies; no MFA seen." in prompt        # existing description shown
    assert "AuthenticationMechanism" in prompt                     # by its exact key
    assert "enrich" in prompt.lower()                              # enrichment directed
    assert "never blank" in prompt.lower()                         # never emptied


def test_N6_extract_prompt_without_existing_systems_offers_no_extend_target():
    prompt = _systems_workflow_prompt({"systems": [], "system_descriptions": {}})
    assert "(none yet)" in prompt                                  # nothing to extend -> mint fresh


# --- N7: linking to PRIMARY services, asset-less secondary excluded -----------

def test_N7_partition_primary_secondary_and_asset_less_excluded():
    chunk_assets = (_endpoint("/a"),)
    aggregations = [
        {"slug": "checkout", "labels": ["Endpoint"], "props": {"path": "/a", "baseurl": "https://a"}},  # -> primary
        {"slug": "search", "labels": ["Endpoint"], "props": {"path": "/z", "baseurl": "https://a"}},     # -> secondary
    ]
    all_services = frozenset({"checkout", "search", "profile"})    # "profile" has NO aggregation
    primary, secondary, owned = partition_services(chunk_assets, aggregations, all_services)
    assert primary == ["checkout"]
    assert secondary == ["search"]                                # asset-bearing, but not this chunk's
    assert "profile" not in primary and "profile" not in secondary  # asset-less -> excluded
    assert owned["checkout"] == ["Endpoint:/a"]                   # the linking evidence


def test_N7_linking_prompt_prefers_primary_and_shows_their_assets():
    prompt = _linking_workflow_prompt(["checkout"], ["search"], {"checkout": ["Endpoint:/a"]})
    assert "PRIMARY services" in prompt and "checkout" in prompt
    assert "Endpoint:/a" in prompt                               # the owned asset shown as evidence
    assert "search" in prompt                                    # secondary listed
    assert "prefer PRIMARY" in prompt


# --- N8: observations feed reasoning ONLY -------------------------------------

def test_N8_observations_feed_reasoning_not_extract_or_link():
    marker = "SESSION_FIXATION_ADVERSARIAL_INSIGHT"
    obs = Observation(macro_kind="header_analysis", severity="info",
                      evidence="Set-Cookie: sid=..; missing HttpOnly", rationale=marker,
                      anchor={"type": "Endpoint", "identity": {"path": "/a", "baseurl": "https://a"}},
                      source_job="triager", source_tool="triager")
    chunk = Chunk(chunk_id="c", source_job="katana", concern="service",
                  assets=(_endpoint("/a"),), observations=(obs,))
    from polymerhus.analysis.mechanism_typist import _asset_observation_paragraphs

    reflection = _asset_observation_paragraphs(chunk)
    assert marker in reflection                                   # insight drives reasoning
    assert "/a" in reflection                                     # paired with its asset
    # calls 3 & 4 see only the rendered digests, never the raw observation insight
    assert marker not in _systems_workflow_prompt(None)
    assert marker not in _linking_workflow_prompt([], [], {})


# --- N9: idempotent identity --------------------------------------------------

def test_N9_idempotent_same_inputs_same_identities():
    cfg = dict(systems=_turn(systems=[_sys("WAF"), _sys("RESTApi")]),
               linking=_turn(edges=[_edge("checkout", "WAF", "FRONTED_BY")]))
    a = type_mechanisms(_service_chunk(), invoke_fn=ScriptedInvoke(**cfg))
    b = type_mechanisms(_service_chunk(), invoke_fn=ScriptedInvoke(**cfg))
    assert {(s.kind, s.discriminator) for s in a.systems} == {(s.kind, s.discriminator) for s in b.systems}
    assert [(e.service_slug, e.kind, e.rel) for e in a.system_edges] == \
           [(e.service_slug, e.kind, e.rel) for e in b.system_edges]


def test_N9_empty_chunk_is_valid_empty():
    assert type_mechanisms(Chunk(chunk_id="c", concern="service"), invoke_fn=ScriptedInvoke()) == L1DeltaBatch()


# --- N10: read_l1_inventory carries system_descriptions additively ------------

def test_N10_read_inventory_adds_system_descriptions_without_changing_systems_shape():
    from polymerhus.analysis.l1_inventory import _empty, read_l1_inventory

    def fake_read(cypher, params):
        if "L1System" in cypher:
            return [{"kind": "WAF", "disc": "__singleton__", "description": "Blocks SQLi/XSS request patterns."},
                    {"kind": "RESTApi", "disc": "__singleton__", "description": ""}]  # blank -> excluded from map
        return []

    inv = read_l1_inventory("proj-1", read_fn=fake_read)
    assert inv["system_descriptions"] == {"WAF": "Blocks SQLi/XSS request patterns."}  # blank RESTApi absent
    assert inv["systems"] == ["RESTApi", "WAF"]                    # flat list shape UNCHANGED (sorted keys)
    assert _empty()["system_descriptions"] == {}                  # additive in the empty shape too


# --- N11: wiring / protocol (register-ready; Option B - dispatch deferred) -----

def test_N11_body_matches_proposer_body_signature():
    params = list(inspect.signature(mechanism_typist_body).parameters)
    assert params[:2] == ["dispatch", "state"]                    # ProposerBody (dispatch, state) -> ...


def test_N11_body_routes_a1_and_reads_live_inventory_and_aggregations():
    seen = {}

    def read_inventory(pid):
        seen["inv"] = pid
        return {"services": ["checkout"], "systems": [], "system_descriptions": {}}

    def read_aggregations(pid):
        seen["agg"] = pid
        return [{"slug": "checkout", "labels": ["Endpoint"], "props": {"path": "/a", "baseurl": "https://a"}}]

    inv = ScriptedInvoke(systems=_turn(systems=[_sys("WAF")]),
                         linking=_turn(edges=[_edge("checkout", "WAF", "FRONTED_BY")]))
    out = mechanism_typist_body(_Dispatch("A1", _service_chunk()), {"project_id": "proj-1"},
                                invoke_fn=inv, read_inventory=read_inventory, read_aggregations=read_aggregations)
    assert seen == {"inv": "proj-1", "agg": "proj-1"}             # LIVE reads, not a frozen snapshot
    assert [s.kind for s in out.systems] == ["WAF"]


def test_N11_non_a1_phase_is_hollow():
    assert mechanism_typist_body(_Dispatch("A2", _service_chunk()), {"project_id": "p"},
                                 invoke_fn=ScriptedInvoke()) is None


def test_N11_register_ready_in_supervisor_graph():
    """Register-ready under Option B: the body plugs into the exact supervisor seam and
    the graph builds. (Live SCHEDULE dispatch is the deferred coordinated 2b increment.)"""
    from polymerhus.analysis.messages import PROPOSER_ROLES
    from polymerhus.analysis.supervisor import build_supervisor_graph

    assert "mechanism_typist" in PROPOSER_ROLES
    g = build_supervisor_graph(proposer_bodies={"mechanism_typist": mechanism_typist_body})
    assert g is not None                                          # builds without error


def test_N11_enrichment_write_fn_is_what_carries_system_edges():
    """system_edges persist ONLY through the enrichment-capable writer (the plain
    curate writes services/systems/aggregates only). The dispatch must pair the typist
    with it - asserted structurally here since live dispatch is deferred (Option B)."""
    from polymerhus.analysis.l1_curator import enrich
    from polymerhus.analysis.pod import default_curate_with_enrichment_fn

    assert "system_edges" in inspect.signature(enrich).parameters
    assert callable(default_curate_with_enrichment_fn)
