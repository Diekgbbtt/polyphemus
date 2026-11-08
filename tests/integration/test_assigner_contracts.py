"""Contract predicates (integration tier) for the classification-only Assigner.
Mechanises C13-C26 of the catalogue attached to #34 (agent spec #8, slice #25).

The validation gate, admit-all, multi-ownership, the structural
narrowing, the prompt's volatility split and the supervisor receipt - over crafted
proposals and an injected invoke_fn (no live LLM/graph). Expected values from the
spec. Verifier-gated; not selected by the tdd unit threat.
"""
import pytest

from polymerhus.analysis import assigner
from polymerhus.analysis.analyser_types import (
    AggregatesProposal,
    L1DeltaBatch,
    ServiceProposal,
    SystemProposal,
)
from polymerhus.analysis.assigner import (
    AssignmentOutcome,
    assign,
    drop_out_of_inventory,
    narrow_to_assignment,
    shape_proposal,
)
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.recon.domain.types import AssetDelta, Observation

BU = "https://a"
INVENTORY = {
    "services": ["checkout", "fulfilment"], "systems": [],
    "service_contracts": {"checkout": "Take a basket to a paid order."},
}
SLUGS = frozenset({"checkout", "fulfilment"})


def _ep(path):
    return AssetDelta(type="Endpoint", identity={"path": path, "method": "GET", "baseurl": BU})


def _agg(path, service="checkout"):
    return AggregatesProposal(
        service_slug=service,
        l0=L0Ref(label="Endpoint", identity={"path": path, "method": "GET", "baseurl": BU}),
        evidence_refs=[f"path segment {path}"],
    )


def _chunk(*paths):
    return Chunk(chunk_id="katana:0", source_job="katana", assets=tuple(_ep(p) for p in paths))


def _capture():
    """An invoke_fn that records the messages it was handed and returns a batch."""
    seen = {}

    def make(batch):
        def invoke(messages, *, schema=None, system_prompt=None, **_):
            seen["messages"] = messages
            seen["schema"] = schema
            seen["system_prompt"] = system_prompt
            return batch
        return invoke

    return seen, make


# --- C13: admit-all (the withholding gate and the confidence score were removed
# on 2026-10-15, docs/design/drop-aggregate-confidence.md). The structural gates
# below are all that remain. --------------------------------------------------

def test_C13_every_structurally_valid_aggregate_is_kept():
    """Admit-all: no confidence gate follows the structural gates, so every
    aggregate that names a live Service and a known Endpoint survives with its
    evidence intact."""
    ep = AssetDelta(type="Endpoint", identity={"path": "/x", "method": "GET", "baseurl": BU})
    raw = L1DeltaBatch(aggregates=[_agg("/x"), _agg("/x", service="fulfilment")])
    out = shape_proposal(raw, existing_slugs=SLUGS, endpoints=(ep,))
    assert {a.service_slug for a in out.batch.aggregates} == {"checkout", "fulfilment"}
    survivor = next(a for a in out.batch.aggregates if a.service_slug == "checkout")
    assert survivor.evidence_refs == ["path segment /x"]


# --- C14 / C15: D9 - the validation gate + the backlog ------------------------

def test_C14_out_of_inventory_slug_is_dropped():
    batch = L1DeltaBatch(aggregates=[_agg("/x", service="ghost-service")])
    out = assign(_chunk("/x"), invoke_fn=lambda m, **_: batch, inventory=INVENTORY,
                 existing_slugs=SLUGS)
    assert out.batch.aggregates == []  # a non-existent owner never lands


def test_C15_out_of_inventory_slug_becomes_backlog_description():
    batch = L1DeltaBatch(aggregates=[_agg("/x", service="ghost-service")])
    out = assign(_chunk("/x"), invoke_fn=lambda m, **_: batch, inventory=INVENTORY,
                 existing_slugs=SLUGS)
    assert len(out.backlog) == 1
    (item,) = out.backlog
    assert isinstance(item, str)
    assert "ghost-service" in item      # the candidate slug is embedded inline
    assert out.batch.services == []


def test_C15b_validation_gate_drops_a_ghost_owner():
    """A ghost owner is a reference to nothing, not a weak judgment."""
    batch = L1DeltaBatch(aggregates=[_agg("/x", service="ghost")])
    kept, backlog = drop_out_of_inventory(batch, existing_slugs=SLUGS)
    assert kept.aggregates == []
    assert len(backlog) == 1 and "ghost" in backlog[0]


# --- C16: D3 - multi-ownership ------------------------------------------------

def test_C16_two_services_may_own_the_same_endpoint():
    batch = L1DeltaBatch(aggregates=[
        _agg("/orders/42", service="checkout"),
        _agg("/orders/42", service="fulfilment"),
    ])
    out = assign(_chunk("/orders/42"), invoke_fn=lambda m, **_: batch, inventory=INVENTORY,
                 existing_slugs=SLUGS)
    assert len(out.batch.aggregates) == 2
    assert {a.service_slug for a in out.batch.aggregates} == {"checkout", "fulfilment"}
    assert {a.l0.identity["path"] for a in out.batch.aggregates} == {"/orders/42"}


# --- C17: D4 - the Assigner never emits services ------------------------------

def test_C17_assigner_never_emits_services():
    batch = L1DeltaBatch(
        services=[
            ServiceProposal(business_function_slug="checkout", props={"exposure": "public"}),
            ServiceProposal(business_function_slug="brand-new", props={"exposure": "public"}),
        ],
        aggregates=[_agg("/x")],
    )
    out = assign(_chunk("/x"), invoke_fn=lambda m, **_: batch, inventory=INVENTORY,
                 existing_slugs=SLUGS)
    assert out.batch.services == []          # reused AND would-be-minted both dropped
    assert len(out.batch.aggregates) == 1    # the assignment survives


# --- C18: structural narrowing ------------------------------------------------

def test_C18_narrow_drops_non_assignment_lists():
    raw = L1DeltaBatch(
        services=[ServiceProposal(business_function_slug="x")],
        systems=[SystemProposal(kind="RESTApi")],
        aggregates=[_agg("/x")],
    )
    out = narrow_to_assignment(raw)
    assert out.services == [] and out.systems == [] and out.system_edges == []
    assert len(out.aggregates) == 1


# --- C19: degradation ---------------------------------------------------------

def test_C19_degrades_to_empty_outcome():
    def boom(messages):
        raise RuntimeError("llm down")

    empty = AssignmentOutcome()
    # (a) a chunk with nothing this role admits
    assert assign(Chunk(chunk_id="katana:0"), invoke_fn=lambda m, **_: None) == empty
    # (b) the invoke raises
    assert assign(_chunk("/x"), invoke_fn=boom) == empty
    # (c) no parseable tool call
    assert assign(_chunk("/x"), invoke_fn=lambda m, **_: None) == empty


# --- C20: idempotent ----------------------------------------------------------

def test_C20_idempotent_same_inputs_same_result():
    batch = L1DeltaBatch(aggregates=[_agg("/x")])
    a = assign(_chunk("/x"), invoke_fn=lambda m, **_: batch, inventory=INVENTORY, existing_slugs=SLUGS)
    b = assign(_chunk("/x"), invoke_fn=lambda m, **_: batch, inventory=INVENTORY, existing_slugs=SLUGS)
    assert a == b


# --- C21: D2/D7 applied at the proposer ---------------------------------------

def test_C21_prompt_renders_admitted_endpoints_only():
    chunk = Chunk(chunk_id="katana:0", assets=(
        _ep("/orders/42"),
        AssetDelta(type="Parameter", identity={"name": "secretparam", "baseurl": BU}),
        AssetDelta(type="Header", identity={"name": "X-Secret-Header"}),
    ))
    seen, make = _capture()
    assign(chunk, invoke_fn=make(L1DeltaBatch()), inventory=INVENTORY, existing_slugs=SLUGS)
    user = seen["messages"][0].content
    assert "/orders/42" in user
    assert "secretparam" not in user
    assert "X-Secret-Header" not in user


# --- C22: D5 - observations are not rendered here -----------------------------

def test_C22_observations_not_rendered_on_the_assigner_path():
    chunk = Chunk(chunk_id="katana:0", assets=(_ep("/x"),), observations=(
        Observation(macro_kind="k", severity="low", evidence="DISTINCTIVE-OBSERVATION-STRING",
                    rationale="why", anchor={"type": "Endpoint", "identity": {"path": "/x"}},
                    source_job="katana", source_tool="katana"),
    ))
    seen, make = _capture()
    assign(chunk, invoke_fn=make(L1DeltaBatch()), inventory=INVENTORY, existing_slugs=SLUGS)
    rendered = "".join(m.content for m in seen["messages"])
    assert "DISTINCTIVE-OBSERVATION-STRING" not in rendered


# --- C23: the prompt's contract match, and no minting directive ---------------

def test_C23_prompt_directs_contract_match_and_forbids_minting():
    seen, make = _capture()
    assign(_chunk("/x"), invoke_fn=make(L1DeltaBatch()), inventory=INVENTORY, existing_slugs=SLUGS)
    system = seen["system_prompt"]
    user = seen["messages"][0].content
    assert "Take a basket to a paid order." in user   # the contract IS in the prompt
    assert "path segments" in system                  # the match is directed
    assert "cannot create a Service" in system        # minting is forbidden
    # no minting directive survives anywhere
    assert "service_contract" not in system + user
    assert "exposure" not in system + user


# --- C24: the volatility split ------------------------------------------------

def test_C24_stable_prefix_in_system_volatile_in_user():
    seen, make = _capture()
    assign(_chunk("/x"), invoke_fn=make(L1DeltaBatch()), inventory=INVENTORY, existing_slugs=SLUGS)
    system = seen["system_prompt"]
    user = seen["messages"][0].content
    assert "checkout" not in system            # no inventory identity in the stable half
    assert "checkout" in user                  # it rides the volatile half
    assert user.index("checkout") < user.index("/x")  # identities block comes FIRST


# --- C25: the reflect verbatim ------------------------------------------------

def test_C25_reflect_verbatim_only_under_reflect_mode():
    # `CALIBRATE` was dropped from this marker set when `skill` became the default
    # (2026-07-29): the skill's own fourth move is "CALIBRATE, THEN COMMIT OR
    # WITHHOLD", so the word stopped discriminating between the two prompts. The
    # assertion is unchanged in strength - the four remaining markers are verified
    # absent from the skill body - but it now names only text the reflect verbatim
    # actually owns.
    #
    # The collision is a real (harmless) REDUNDANCY: the skill teaches calibration in
    # the create pass and the reflect verbatim re-teaches it in the reflect pass.
    # Harmless only because nothing dispatches `mode="reflect"` today; whoever wires
    # reflection must reconcile the two rather than shipping both.
    markers = ["REFLECT PASS", "RESTATE AS EVIDENCE", "COMPETING OWNER", "RESIDUE"]
    seen_c, make_c = _capture()
    assign(_chunk("/x"), invoke_fn=make_c(L1DeltaBatch()), inventory=INVENTORY,
           existing_slugs=SLUGS, mode="create")
    create_system = seen_c["system_prompt"]

    seen_r, make_r = _capture()
    assign(_chunk("/x"), invoke_fn=make_r(L1DeltaBatch()), inventory=INVENTORY,
           existing_slugs=SLUGS, mode="reflect")
    reflect_system = seen_r["system_prompt"]

    assert not any(m in create_system for m in markers)
    assert all(m in reflect_system for m in markers)
    assert reflect_system.startswith(create_system)  # the cacheable prefix is unchanged


# --- C26: the supervisor receipt tells the truth ------------------------------

def test_C26_proposer_carrying_cargo_reports_written():
    from polymerhus.analysis.messages import AgentDispatch
    from polymerhus.analysis.supervisor import build_supervisor_graph

    captured = {}

    def body(dispatch, state):
        return L1DeltaBatch(aggregates=[_agg("/x")])

    def curator(state):
        captured["status"] = state["inflight"].status
        return {}

    graph = build_supervisor_graph(proposer_bodies={"assigner": body}, curator_fn=curator).compile()
    graph.invoke({
        "project_id": "p", "run_id": "r", "receipts": [],
        "schedule": [AgentDispatch(dispatch_id="d1", role="assigner", phase="A1",
                                   chunk=Chunk(chunk_id="katana:0"))],
    })
    assert captured["status"] == "written"


def test_C26b_hollow_curator_never_reports_a_write_that_did_not_happen():
    """The envelope's `written` means "carries content"; the receipt's means "the
    curator wrote it". With no write_fn nothing was written, so the receipt must not
    inherit the envelope's status."""
    from polymerhus.analysis.messages import AgentDispatch
    from polymerhus.analysis.supervisor import build_supervisor_graph

    def body(dispatch, state):
        return L1DeltaBatch(aggregates=[_agg("/x")])

    graph = build_supervisor_graph(proposer_bodies={"assigner": body}).compile()
    state = graph.invoke({
        "project_id": "p", "run_id": "r", "receipts": [],
        "schedule": [AgentDispatch(dispatch_id="d1", role="assigner", phase="A1",
                                   chunk=Chunk(chunk_id="katana:0"))],
    })
    (receipt,) = state["receipts"]
    assert receipt.status == "empty"
    assert receipt.written.aggregates == 0


# --- C28-C31: the chunk-fed wiring (#34) --------------------------------------

def test_C28_schedule_is_one_dispatch_per_chunk_role_pair_with_stable_ids():
    from polymerhus.analysis.supervisor import build_schedule

    chunks = [Chunk(chunk_id="stream-r1:0"), Chunk(chunk_id="stream-r1:1")]
    a = build_schedule(chunks, "r1")
    b = build_schedule(chunks, "r1")
    assert [d.dispatch_id for d in a] == [
        "r1:stream-r1:0:assigner", "r1:stream-r1:1:assigner",
    ]
    assert [d.dispatch_id for d in a] == [d.dispatch_id for d in b]  # replay-stable
    assert all(d.role == "assigner" and d.phase == "A1" for d in a)


def test_C29_schedule_dispatches_only_roles_that_have_bodies():
    """A dispatch to a hollow node would report an empty step as if it were work."""
    from polymerhus.analysis.supervisor import build_schedule

    (dispatch,) = build_schedule([Chunk(chunk_id="c0")], "r1")
    assert dispatch.role == "assigner"


def test_C30_aggregates_write_fn_never_writes_services_or_systems(monkeypatch):
    """A writer that could create a Service would restore the retired mint path."""
    import polymerhus.analysis.l1_curator as l1_curator
    from polymerhus.analysis.l1_types import Provenance
    from polymerhus.analysis.supervisor import _aggregates_write_fn

    calls = []
    monkeypatch.setattr(l1_curator, "write_aggregates",
                        lambda deltas, pid, **kw: (calls.append(("aggregates", len(deltas))), len(deltas))[1])
    monkeypatch.setattr(l1_curator, "l1_curate",
                        lambda *a, **kw: calls.append(("curate", a)) or (0, 0))

    batch = L1DeltaBatch(
        services=[ServiceProposal(business_function_slug="smuggled")],
        aggregates=[_agg("/x")],
    )
    export = _aggregates_write_fn(batch, "p1", Provenance(job="analyser:r1"))

    assert export.aggregates_written == 1
    assert export.services_written == 0
    assert [c[0] for c in calls] == ["aggregates"]   # l1_curate is never reached


def test_C31_empty_surface_yields_an_empty_export_without_dispatching():
    from polymerhus.analysis.supervisor import run_analyser_chunked

    def boom(*a, **k):
        raise AssertionError("no LLM call may happen on an empty surface")

    export = run_analyser_chunked(
        "p1", "r1", invoke_fn=boom,
        assets_fn=lambda pid: [],
        inventory_fn=lambda pid: {"services": []}, observe=False,
    )
    assert export.aggregates_written == 0


# --- C32-C35: the reference gate (the live-run defect) ------------------------

def _ep_asset(path, method="GET"):
    return AssetDelta(type="Endpoint", identity={"path": path, "method": method, "baseurl": BU})


def test_C32_model_formatted_label_is_repaired_not_dropped():
    """A live run proposed 114 sound assignments and wrote ZERO: the model returned
    `l0.label='GET /rest/user/whoami'`, which the sole-writer refuses as an unsafe
    label. Correctness must not depend on the model's formatting."""
    from polymerhus.analysis.assigner import resolve_l0_refs

    bad = AggregatesProposal(
        service_slug="sign-in",
        l0=L0Ref(label="GET /rest/user/whoami", identity={"x": "y"}),
        evidence_refs=["path segment /user"],
    )
    out = resolve_l0_refs(L1DeltaBatch(aggregates=[bad]),
                          endpoints=(_ep_asset("/rest/user/whoami"),))
    (fixed,) = out.aggregates
    assert fixed.l0.label == "Endpoint"
    assert fixed.l0.identity == {"path": "/rest/user/whoami", "method": "GET", "baseurl": BU}
    assert fixed.evidence_refs == ["path segment /user"]


def test_C33_reference_to_unknown_surface_is_dropped():
    """The out-of-scope filter: a reference to surface NOBODY knows is a
    reference to nothing - its own chunk judges it when recon collects it."""
    from polymerhus.analysis.assigner import resolve_l0_refs

    ghost = AggregatesProposal(
        service_slug="sign-in",
        l0=L0Ref(label="Endpoint", identity={"path": "/invented", "method": "GET", "baseurl": BU}),
    )
    out = resolve_l0_refs(L1DeltaBatch(aggregates=[ghost]), endpoints=(_ep_asset("/real"),))
    assert out.aggregates == []


def test_C33b_reference_outside_the_chunk_is_dropped_even_when_settled():
    """The out-of-scope filter restored: a reference to an endpoint the chunk
    never carried drops as unresolvable - there is no settled-surface union
    anymore, so out-of-chunk discovery has no write path by construction."""
    raw = L1DeltaBatch(aggregates=[_agg("/neighbour")])
    out = shape_proposal(raw, existing_slugs=SLUGS, endpoints=(_ep_asset("/real"),))
    assert out.batch.aggregates == []
    assert out.stats.unresolvable == 1


def test_C33c_reference_to_unknown_surface_is_still_dropped_end_to_end():
    """The guard beside C33b: a reference to surface in no chunk at all still
    dies as unresolvable."""
    raw = L1DeltaBatch(aggregates=[_agg("/invented")])
    out = shape_proposal(raw, existing_slugs=SLUGS, endpoints=(_ep_asset("/real"),))
    assert out.batch.aggregates == []
    assert out.stats.unresolvable == 1


def test_C34b_assign_is_chunk_scoped_end_to_end():
    """Chunk-scoped judgment through `assign`: the chunk carries one endpoint,
    the model judges an adjacent one it does not carry, and the judgment drops."""
    chunk = Chunk(chunk_id="katana:0", assets=(_ep_asset("/real"),))
    raw = L1DeltaBatch(aggregates=[_agg("/neighbour")])
    out = assign(chunk, invoke_fn=lambda m, **_: raw, inventory=INVENTORY,
                 existing_slugs=SLUGS)
    assert out.batch.aggregates == []
    assert out.stats.unresolvable == 1


def test_C34c_assigner_body_takes_no_settled_surface_reader():
    """Wiring: the body judges the chunk's slice only - no surface reader is
    threaded, because no out-of-chunk discovery seam remains to feed it."""
    from polymerhus.analysis.assigner import make_assigner_body
    from polymerhus.analysis.messages import AgentDispatch

    raw = L1DeltaBatch(aggregates=[_agg("/neighbour")])
    body = make_assigner_body(
        invoke_fn=lambda m, **_: raw,
        inventory_fn=lambda project_id: INVENTORY,
    )
    out = body(AgentDispatch(dispatch_id="d1", role="assigner", phase="A1",
                             mode="create", chunk=_chunk("/real")),
               {"project_id": "p1", "run_id": "r1"})
    assert out.aggregates == []


def test_C34d_assigner_body_without_a_surface_degrades_to_the_chunk_slice():
    """The chunk slice is the only scope: a judgment on it survives the pass."""
    from polymerhus.analysis.assigner import make_assigner_body
    from polymerhus.analysis.messages import AgentDispatch

    raw = L1DeltaBatch(aggregates=[_agg("/real")])
    body = make_assigner_body(
        invoke_fn=lambda m, **_: raw,
        inventory_fn=lambda project_id: INVENTORY,
    )
    out = body(AgentDispatch(dispatch_id="d1", role="assigner", phase="A1",
                             mode="create", chunk=_chunk("/real")),
               {"project_id": "p1", "run_id": "r1"})
    assert {a.l0.identity["path"] for a in out.aggregates} == {"/real"}


def test_C34_repaired_reference_survives_the_full_shaping_end_to_end():
    chunk = Chunk(chunk_id="katana:0", assets=(_ep_asset("/api/Complaints"),))
    raw = L1DeltaBatch(aggregates=[AggregatesProposal(
        service_slug="checkout", l0=L0Ref(label="GET /api/Complaints", identity={}),
        evidence_refs=["path segment /api/Complaints"],
    )])
    out = assign(chunk, invoke_fn=lambda m, **_: raw, inventory=INVENTORY,
                 existing_slugs=SLUGS)
    (agg,) = out.batch.aggregates
    assert agg.l0.label == "Endpoint"
    assert agg.l0.identity["path"] == "/api/Complaints"


def test_C35_a_well_formed_reference_survives_the_gate_untouched():
    """The gate's HAPPY path, which C32 (repair) and C33 (drop) leave unpinned: a
    proposal that already names the endpoint correctly must pass through unchanged.

    This assertion used to read `assert "never a path and never a method" in system`.
    That froze prompt WORDING rather than behaviour, and it froze wording the code had
    since made redundant - `resolve_l0_refs` overwrites `l0.label` unconditionally, so
    no outcome depends on the model reading that sentence. Keeping it would have made
    every future prompt improvement look like weakening a test. The instruction is
    deleted and the property it was standing in for is asserted directly here."""
    from polymerhus.analysis.assigner import resolve_l0_refs

    good = AggregatesProposal(
        service_slug="sign-in",
        l0=L0Ref(label="Endpoint",
                 identity={"path": "/rest/user/whoami", "method": "GET", "baseurl": BU}),
        evidence_refs=["path segment /user"],
    )
    out = resolve_l0_refs(L1DeltaBatch(aggregates=[good]),
                          endpoints=(_ep_asset("/rest/user/whoami"),))
    (kept,) = out.aggregates
    assert kept.l0.label == "Endpoint"
    assert kept.l0.identity == {"path": "/rest/user/whoami", "method": "GET", "baseurl": BU}
    assert kept.evidence_refs == ["path segment /user"]


def test_C35b_prompt_states_the_identity_shape_the_repair_depends_on():
    """The one part of the reference rule that is NOT redundant. `_candidate_path`
    reads `identity["path"]` before it falls back to parsing the label, so the
    identity shape is what makes the repair's happy path fire rather than its
    salvage path. Asserted as a prompt property because it IS a prompt property -
    unlike the label sentence, deleting it would change outcomes."""
    seen, make = _capture()
    assign(_chunk("/x"), invoke_fn=make(L1DeltaBatch()), inventory=INVENTORY, existing_slugs=SLUGS)
    system = seen["system_prompt"]
    assert "l0.identity" in system
    for key in ("path", "method", "baseurl"):
        assert f'"{key}"' in system


# --- C35c: the HTTP-history widening seam + the deductive target ---------

def test_C35c_task_names_the_deductive_target_and_leaves_the_widening_to_the_system_prompt():
    """The volatile task frames the slice as the primary subject and names
    the inventory as the deductive target. The bounded recorded-response
    widening lives in the SYSTEM prompt (C35d/C35e), so the user turn never
    repeats tooling verbatim on every chunk."""
    seen, make = _capture()
    assign(_chunk("/x"), invoke_fn=make(L1DeltaBatch()), inventory=INVENTORY, existing_slugs=SLUGS)
    user = seen["messages"][0].content
    assert "DEDUCTIVE TARGET" in user   # the inventory is what the reasoning reasons TO
    assert "left unplaced" in user      # admit-all: an unsupported judgment yields no edge
    assert "search_http_history" not in user  # the widening is the system prompt's job
    system = seen["system_prompt"]
    assert "search_http_history" in system  # the widening seam is bound in the system prompt
    assert "graph_view" not in system        # rolled back: no graph roaming on this turn


def test_C35d_reference_rule_covers_only_the_slice_and_http_reads():
    """The role verbatim after the rollback: a reference is legal when the
    endpoint was seen - in the slice or read through the HTTP-history pair -
    and only an invented one names nothing. No `graph_view` remains."""
    seen, make = _capture()
    assign(_chunk("/x"), invoke_fn=make(L1DeltaBatch()), inventory=INVENTORY, existing_slugs=SLUGS)
    system = seen["system_prompt"]
    assert "graph_view" not in system
    assert "search_http_history" in system
    assert "you invent" in system


def test_C35e_skill_centers_the_http_pair_as_the_widening_seam():
    """The HOW file after the rollback: the recorded-response read is the
    central bounded widening seam (disambiguation AND the adjacently
    promising surface); deep technical understanding still belongs to the
    mechanism-typist; the judgment stays chunk-scoped even when the reading
    roams."""
    from polymerhus.analysis.assigner import _load_assigner_skill

    skill = _load_assigner_skill()
    assert "widening seam" in skill
    assert "graph_view" not in skill
    assert "confirm a hypothesis" in skill
    assert "promising" in skill
    assert "never a trawl" in skill
    assert "mechanism-typist" in skill
    assert "chunk-scoped" in skill


# --- C36: the gate census (the instrumentation gap) ---------------------------

def test_C36_stats_name_where_each_judgment_died():
    """Every gate is fail-open, so without a per-gate count an empty result cannot be
    told apart from a model that found nothing - which is exactly how a live run
    proposed 114 assignments, wrote zero, and reported success."""
    ep = AssetDelta(type="Endpoint", identity={"path": "/a", "method": "GET", "baseurl": BU})
    raw = L1DeltaBatch(aggregates=[
        AggregatesProposal(service_slug="checkout", l0=L0Ref(label="GET /a", identity={})),
        AggregatesProposal(service_slug="ghost", l0=L0Ref(label="GET /a", identity={})),
        AggregatesProposal(service_slug="checkout", l0=L0Ref(label="GET /gone", identity={})),
        AggregatesProposal(service_slug="checkout", l0=L0Ref(label="GET /a", identity={})),
    ])
    out = assign(Chunk(chunk_id="c0", assets=(ep,)), invoke_fn=lambda m, **_: raw,
                 inventory=INVENTORY, existing_slugs=SLUGS)
    st = out.stats
    # admit-all: the two structurally-valid checkout aggregates survive; the ghost
    # owner and the unknown /gone reference die on the structural gates.
    assert (st.admitted, st.proposed, st.kept) == (1, 4, 2)
    assert st.unresolvable == 1        # /gone was never in the chunk
    assert st.out_of_inventory == 1    # ghost is not a live Service


# --- C37-C40: the role-specific skill seam (#30 retirement for the Assigner) ---
#
# `prompts/assigner.md` carries the HOW (the ownership-judgment
# discipline); `_ROLE_VERBATIM` keeps the WHAT. Selected by ASSIGNER_PROMPT_CONFIG,
# default `baseline` until a comparative eval flips it (the bootstrap._PROMPT_CONFIGS
# discipline: a prompt default is earned by measurement, never by argument).

# The baseline arm, pinned by construction rather than by a copied literal: it must
# stay byte-identical to `_ROLE_VERBATIM` + `_FEW_SHOTS` forever. Both halves lost
# their confidence text when the score was removed, so this pins the CURRENT
# construction, not a historical byte string - there is no archived baseline literal
# to compare against.
_BASELINE_EXPECTED = f"{assigner._ROLE_VERBATIM}\n\n{assigner._FEW_SHOTS}"


def _system_for(config, monkeypatch, mode="create"):
    monkeypatch.setenv("ASSIGNER_PROMPT_CONFIG", config)
    seen, make = _capture()
    assign(_chunk("/x"), invoke_fn=make(L1DeltaBatch()), inventory=INVENTORY,
           existing_slugs=SLUGS, mode=mode)
    return seen["system_prompt"]


def test_C37_baseline_arm_is_pinned_by_construction(monkeypatch):
    """The rollback path is PINNED, not assumed. `baseline` must reproduce exactly
    `_ROLE_VERBATIM` + `_FEW_SHOTS` as they stand now, so reverting a `skill` default
    that measures badly is a one-env-var revert with no prompt drift smuggled in.

    This property survives the default flip unchanged - which is the point of pinning
    it by construction (`_ROLE_VERBATIM` + `_FEW_SHOTS`) rather than against a copied
    literal that would have to be re-copied every time the prompt moves."""
    assert _system_for("baseline", monkeypatch) == _BASELINE_EXPECTED


def test_C37b_the_default_arm_is_skill_and_an_unknown_value_coerces_to_it(monkeypatch):
    """DEFAULT = `skill` (operator-ratified 2026-07-29). An unset env var and an
    unknown one must both land on the SAME arm as an explicit `skill`, or the
    deployed behaviour depends on how the variable failed to be set."""
    explicit_skill = _system_for("skill", monkeypatch)

    monkeypatch.delenv("ASSIGNER_PROMPT_CONFIG", raising=False)
    assert assigner._system_prompt("create") == explicit_skill
    assert _system_for("no-such-arm", monkeypatch) == explicit_skill

    # non-vacuity: the default is a REAL change from the rollback arm, not the same
    # bytes under a different name
    assert explicit_skill != _BASELINE_EXPECTED
    assert assigner._load_assigner_skill() in explicit_skill


def test_C38_assigner_skill_is_single_sourced():
    """The discipline lives in ONE place - the module's prompts/ dir. A second
    copy in Python is how the two drift apart."""
    from pathlib import Path

    skill = assigner._load_assigner_skill()
    assert skill
    assert not skill.startswith("---")                      # plain .md, no frontmatter
    expected = (Path(assigner.__file__).resolve().parent / "prompts" / "assigner.md").read_text(encoding="utf-8")
    assert skill == expected                                 # single source
    # the in-process memo is what keeps the system prefix byte-stable across a run,
    # so the provider prompt-cache survives every chunk of that run
    assert assigner._load_assigner_skill() is skill


def test_C39_missing_prompt_raises_fail_closed(monkeypatch):
    """A missing prompt file is a defect, not a degraded lane: the read FAILS
    CLOSED (raises) so a role never reasons without its prompt."""
    import pathlib

    def boom(self, *a, **k):
        raise OSError("no mount")

    monkeypatch.setattr(pathlib.Path, "read_text", boom)
    monkeypatch.setattr(assigner, "_ASSIGNER_SKILL", None)
    try:
        with pytest.raises(OSError):
            assigner._load_assigner_skill()
    finally:
        monkeypatch.setattr(assigner, "_ASSIGNER_SKILL", None)


@pytest.mark.parametrize("config", assigner._ASSIGNER_PROMPT_CONFIGS)
def test_C40_role_contract_holds_under_every_prompt_config(config, monkeypatch):
    """The properties C21-C24/C35 pin must hold on BOTH arms, or flipping the default
    silently drops one. Two failure directions are covered: a property that lives only
    in `_ROLE_VERBATIM` today and would be lost if it migrated into the skill, and the
    #34 D4/D18 scope guard - the reason the SHARED analyser skill was wrong for this
    role is that it instructs Systems and data modelling this role cannot emit, so any
    skill wired here must be checked for the same defect."""
    system = _system_for(config, monkeypatch)

    # the ownership judgment is directed, and minting stays forbidden (C23)
    assert "path segments" in system
    assert "cannot create a Service" in system
    assert "service_contract" not in system
    assert "exposure" not in system
    # the reference shape survives (C35)
    assert "l0.label" in system
    # no live inventory identity leaks into the cacheable half (C24)
    assert "checkout" not in system
    # SCOPE GUARD (#34 D4/D18). Note what this can NOT assert: `_ROLE_VERBATIM`
    # legitimately NAMES `system_edges` and the data lists in order to forbid them, so
    # a bare substring ban fails on the untouched baseline prompt too. The real defect
    # to catch is a prompt that teaches the model HOW to emit them, whose fingerprints
    # are the shared analyser skill's typed vocabulary - the exact text that made that
    # skill wrong for this role.
    assert "Leave services, systems, system_edges and every data-modelling list EMPTY" in system
    for forbidden in ("EXPOSED_VIA", "AUTHENTICATED_BY", "FRONTED_BY", "PROTECTED_BY",
                      "WebPresentation", "rendering_model", "navigation_model",
                      "api_paradigm", "derived_from", "business_function_slug"):
        assert forbidden not in system, f"{config} arm instructs {forbidden}"


@pytest.mark.parametrize("config", assigner._ASSIGNER_PROMPT_CONFIGS)
def test_C40b_reflect_appends_without_disturbing_the_cacheable_prefix(config, monkeypatch):
    """C25's property, held on both arms: reflect must EXTEND the create prefix, never
    rewrite it, or the provider prompt-cache is invalidated on every reflect pass."""
    create = _system_for(config, monkeypatch, mode="create")
    reflect = _system_for(config, monkeypatch, mode="reflect")
    assert reflect.startswith(create)
    assert "RESTATE AS EVIDENCE" in reflect
    assert "RESTATE AS EVIDENCE" not in create
