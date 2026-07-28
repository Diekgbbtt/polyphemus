"""Contract predicates (integration tier) for the classification-only Assigner.
Mechanises C13-C26 of the catalogue attached to #34 (agent spec #8, slice #25).

The validation gate, the withholding gate, multi-ownership, the structural
narrowing, the prompt's volatility split and the supervisor receipt - over crafted
proposals and an injected invoke_fn (no live LLM/graph). Expected values from the
spec. Verifier-gated; not selected by the tdd unit loop.
"""
from polymerhus.analysis.analyser_types import (
    AggregatesProposal,
    DataItemProposal,
    L1DeltaBatch,
    ServiceProposal,
    SystemProposal,
)
from polymerhus.analysis.assigner import (
    AssignmentOutcome,
    assign,
    drop_out_of_inventory,
    narrow_to_assignment,
    withhold_below_bar,
)
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.recon.domain.types import AssetDelta, Observation

BU = "https://a"
INVENTORY = {
    "services": ["checkout", "fulfilment"], "systems": [], "data_items": [],
    "service_contracts": {"checkout": "Take a basket to a paid order."},
}
SLUGS = frozenset({"checkout", "fulfilment"})


def _ep(path):
    return AssetDelta(type="Endpoint", identity={"path": path, "method": "GET", "baseurl": BU})


def _agg(path, conf, service="checkout"):
    return AggregatesProposal(
        service_slug=service,
        l0=L0Ref(label="Endpoint", identity={"path": path, "method": "GET", "baseurl": BU}),
        confidence=conf, evidence_refs=[f"path segment {path}"],
    )


def _chunk(*paths):
    return Chunk(chunk_id="katana:0", source_job="katana", assets=tuple(_ep(p) for p in paths))


def _capture():
    """An invoke_fn that records the messages it was handed and returns a batch."""
    seen = {}

    def make(batch):
        def invoke(messages):
            seen["messages"] = messages
            return batch
        return invoke

    return seen, make


# --- C13: the withholding gate ------------------------------------------------

def test_C13_withhold_below_bar_keeps_evidence():
    batch = L1DeltaBatch(aggregates=[_agg("/x", 0.90), _agg("/y", 0.50), _agg("/z", 0.75)])
    out = withhold_below_bar(batch, bar=0.75)
    assert {a.l0.identity["path"] for a in out.aggregates} == {"/x", "/z"}  # /y dropped
    survivor = next(a for a in out.aggregates if a.l0.identity["path"] == "/x")
    assert survivor.confidence == 0.90
    assert survivor.evidence_refs == ["path segment /x"]


# --- C14 / C15: D9 - the validation gate + the backlog ------------------------

def test_C14_out_of_inventory_slug_dropped_at_any_confidence():
    batch = L1DeltaBatch(aggregates=[_agg("/x", 0.99, service="ghost-service")])
    out = assign(_chunk("/x"), invoke_fn=lambda m: batch, inventory=INVENTORY,
                 existing_slugs=SLUGS, bar=0.75)
    assert out.batch.aggregates == []  # a high confidence does not rescue it


def test_C15_out_of_inventory_slug_becomes_backlog_description():
    batch = L1DeltaBatch(aggregates=[_agg("/x", 0.99, service="ghost-service")])
    out = assign(_chunk("/x"), invoke_fn=lambda m: batch, inventory=INVENTORY,
                 existing_slugs=SLUGS, bar=0.75)
    assert len(out.backlog) == 1
    (item,) = out.backlog
    assert isinstance(item, str)
    assert "ghost-service" in item      # the candidate slug is embedded inline
    assert out.batch.services == []


def test_C15b_validation_precedes_the_confidence_gate():
    """A ghost owner is a reference to nothing, not a weak judgment to be scored."""
    batch = L1DeltaBatch(aggregates=[_agg("/x", 0.10, service="ghost")])
    kept, backlog = drop_out_of_inventory(batch, existing_slugs=SLUGS)
    assert kept.aggregates == []
    assert len(backlog) == 1 and "ghost" in backlog[0]


# --- C16: D3 - multi-ownership ------------------------------------------------

def test_C16_two_services_may_own_the_same_endpoint():
    batch = L1DeltaBatch(aggregates=[
        _agg("/orders/42", 0.85, service="checkout"),
        _agg("/orders/42", 0.80, service="fulfilment"),
    ])
    out = assign(_chunk("/orders/42"), invoke_fn=lambda m: batch, inventory=INVENTORY,
                 existing_slugs=SLUGS, bar=0.75)
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
        aggregates=[_agg("/x", 0.90)],
    )
    out = assign(_chunk("/x"), invoke_fn=lambda m: batch, inventory=INVENTORY,
                 existing_slugs=SLUGS, bar=0.75)
    assert out.batch.services == []          # reused AND would-be-minted both dropped
    assert len(out.batch.aggregates) == 1    # the assignment survives


# --- C18: structural narrowing ------------------------------------------------

def test_C18_narrow_drops_non_assignment_lists():
    raw = L1DeltaBatch(
        services=[ServiceProposal(business_function_slug="x")],
        systems=[SystemProposal(kind="RESTApi")],
        data_items=[DataItemProposal(item_key="order")],
        aggregates=[_agg("/x", 0.90)],
    )
    out = narrow_to_assignment(raw)
    assert out.services == [] and out.systems == [] and out.system_edges == []
    assert out.data_items == [] and out.surfaces_at == []
    assert out.data_flows == [] and out.data_relationships == []
    assert len(out.aggregates) == 1


# --- C19: degradation ---------------------------------------------------------

def test_C19_degrades_to_empty_outcome():
    def boom(messages):
        raise RuntimeError("llm down")

    empty = AssignmentOutcome()
    # (a) a chunk with nothing this role admits
    assert assign(Chunk(chunk_id="katana:0"), invoke_fn=lambda m: None) == empty
    # (b) the invoke raises
    assert assign(_chunk("/x"), invoke_fn=boom) == empty
    # (c) no parseable tool call
    assert assign(_chunk("/x"), invoke_fn=lambda m: None) == empty


# --- C20: idempotent ----------------------------------------------------------

def test_C20_idempotent_same_inputs_same_result():
    batch = L1DeltaBatch(aggregates=[_agg("/x", 0.90)])
    a = assign(_chunk("/x"), invoke_fn=lambda m: batch, inventory=INVENTORY, existing_slugs=SLUGS)
    b = assign(_chunk("/x"), invoke_fn=lambda m: batch, inventory=INVENTORY, existing_slugs=SLUGS)
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
    user = seen["messages"][1].content
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
    system, user = (m.content for m in seen["messages"])
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
    system, user = (m.content for m in seen["messages"])
    assert "checkout" not in system            # no inventory identity in the stable half
    assert "checkout" in user                  # it rides the volatile half
    assert user.index("checkout") < user.index("/x")  # identities block comes FIRST


# --- C25: the reflect verbatim ------------------------------------------------

def test_C25_reflect_verbatim_only_under_reflect_mode():
    markers = ["RESTATE AS EVIDENCE", "COMPETING OWNER", "CALIBRATE", "RESIDUE"]
    seen_c, make_c = _capture()
    assign(_chunk("/x"), invoke_fn=make_c(L1DeltaBatch()), inventory=INVENTORY,
           existing_slugs=SLUGS, mode="create")
    create_system = seen_c["messages"][0].content

    seen_r, make_r = _capture()
    assign(_chunk("/x"), invoke_fn=make_r(L1DeltaBatch()), inventory=INVENTORY,
           existing_slugs=SLUGS, mode="reflect")
    reflect_system = seen_r["messages"][0].content

    assert not any(m in create_system for m in markers)
    assert all(m in reflect_system for m in markers)
    assert reflect_system.startswith(create_system)  # the cacheable prefix is unchanged


# --- C26: the supervisor receipt tells the truth ------------------------------

def test_C26_proposer_carrying_cargo_reports_written():
    from polymerhus.analysis.messages import AgentDispatch
    from polymerhus.analysis.supervisor import build_supervisor_graph

    captured = {}

    def body(dispatch, state):
        return L1DeltaBatch(aggregates=[_agg("/x", 0.90)])

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
        return L1DeltaBatch(aggregates=[_agg("/x", 0.90)])

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
        aggregates=[_agg("/x", 0.90)],
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
        assets_fn=lambda pid: [], profiles_fn=lambda pid: [],
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
        confidence=0.9, evidence_refs=["path segment /user"],
    )
    out = resolve_l0_refs(L1DeltaBatch(aggregates=[bad]),
                          endpoints=(_ep_asset("/rest/user/whoami"),))
    (fixed,) = out.aggregates
    assert fixed.l0.label == "Endpoint"
    assert fixed.l0.identity == {"path": "/rest/user/whoami", "method": "GET", "baseurl": BU}
    assert fixed.confidence == 0.9 and fixed.evidence_refs == ["path segment /user"]


def test_C33_reference_to_surface_not_in_the_chunk_is_dropped():
    from polymerhus.analysis.assigner import resolve_l0_refs

    ghost = AggregatesProposal(
        service_slug="sign-in",
        l0=L0Ref(label="Endpoint", identity={"path": "/invented", "method": "GET", "baseurl": BU}),
        confidence=0.99,
    )
    out = resolve_l0_refs(L1DeltaBatch(aggregates=[ghost]), endpoints=(_ep_asset("/real"),))
    assert out.aggregates == []


def test_C34_repaired_reference_survives_the_full_shaping_end_to_end():
    chunk = Chunk(chunk_id="katana:0", assets=(_ep_asset("/api/Complaints"),))
    raw = L1DeltaBatch(aggregates=[AggregatesProposal(
        service_slug="checkout", l0=L0Ref(label="GET /api/Complaints", identity={}),
        confidence=0.88, evidence_refs=["path segment /api/Complaints"],
    )])
    out = assign(chunk, invoke_fn=lambda m: raw, inventory=INVENTORY,
                 existing_slugs=SLUGS, bar=0.75)
    (agg,) = out.batch.aggregates
    assert agg.l0.label == "Endpoint"
    assert agg.l0.identity["path"] == "/api/Complaints"


def test_C35_prompt_states_the_reference_shape():
    seen, make = _capture()
    assign(_chunk("/x"), invoke_fn=make(L1DeltaBatch()), inventory=INVENTORY, existing_slugs=SLUGS)
    system = seen["messages"][0].content
    assert "l0.label" in system
    assert "never a path and never a method" in system
