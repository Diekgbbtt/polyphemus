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
