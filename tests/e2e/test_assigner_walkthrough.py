"""Walkthrough predicates (e2e tier) for the classification-only Assigner (#34,
agent spec #8). Mechanises E1 and E2 of the catalogue attached to #34.

E1 traces one katana job delta from the chunk builder through per-role admission
into assignment; E2 drives the same input through the supervisor control plane.
Live edge: none - the LLM is the injected `invoke_fn` and the inventory is a stated
spec value, both at seams this ticket owns. Expected values from the spec.
Verifier-gated.
"""
from polymerhus.analysis.analyser_types import (
    AggregatesProposal,
    L1DeltaBatch,
    ServiceProposal,
)
from polymerhus.analysis.assigner import assign, make_assigner_body
from polymerhus.analysis.chunking import admit_for_role, chunks_for_job
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.recon.domain.types import AssetDelta, JobSpec

JOB = JobSpec(tool="katana", skill="crawl", command_template="t",
              produces=["BaseURL", "Endpoint", "Technology"], consumes="BaseURL")
A = "https://a"
B = "https://b"

INVENTORY = {
    "services": ["checkout", "fulfilment"], "systems": [], "data_items": [],
    "service_contracts": {
        "checkout": "Takes a basket to a paid order; owns orders and payment intents.",
        "fulfilment": "Owns shipments and dispatch of placed orders.",
    },
}


def _asset(t, **identity):
    return AssetDelta(type=t, identity=identity)


def _delta():
    return [
        _asset("BaseURL", baseurl=A), _asset("BaseURL", baseurl=B),
        _asset("Endpoint", path="/orders/42", method="GET", baseurl=A),
        _asset("Endpoint", path="/ship/7", method="GET", baseurl=B),
        _asset("Technology", name="nginx"),
        _asset("Parameter", name="q", baseurl=A),
        _asset("Parameter", name="r", baseurl=B),
        _asset("Header", name="X-Api"),
        _asset("Secret", key="tok"),
        _asset("Subdomain", host="s.a"),
    ]


def _l0(path, baseurl):
    return L0Ref(label="Endpoint", identity={"path": path, "method": "GET", "baseurl": baseurl})


def _proposal():
    """What the model returns: two genuine owners of /orders/42, a weak guess on
    /ship/7, and a confident reach for a Service that does not exist."""
    return L1DeltaBatch(
        services=[ServiceProposal(business_function_slug="ghost", props={"exposure": "public"})],
        aggregates=[
            AggregatesProposal(service_slug="checkout", l0=_l0("/orders/42", A),
                               confidence=0.90, evidence_refs=["path segment /orders"]),
            AggregatesProposal(service_slug="fulfilment", l0=_l0("/orders/42", A),
                               confidence=0.80, evidence_refs=["path segment /orders"]),
            AggregatesProposal(service_slug="checkout", l0=_l0("/ship/7", B),
                               confidence=0.60, evidence_refs=["topical guess"]),
            AggregatesProposal(service_slug="ghost", l0=_l0("/ship/7", B),
                               confidence=0.99, evidence_refs=["path segment /ship"]),
        ],
    )


def _build_chunk():
    chunks = chunks_for_job(JOB, _delta())
    assert len(chunks) == 1
    return chunks[0]


def test_E1_katana_delta_through_admission_to_assignment():
    chunk = _build_chunk()

    # --- the stream: every type, one chunk (the profile gate is REMOVED, #48 -
    # nothing is withheld on that basis any more)
    assert chunk.chunk_id == "katana:0"
    assert len(chunk.assets) == 10
    assert any(a.identity.get("name") == "r" for a in chunk.assets)
    assert {a.identity["path"] for a in chunk.assets if a.type == "Endpoint"} == {"/orders/42", "/ship/7"}
    assert any(a.type == "Subdomain" for a in chunk.assets)  # pre-HTTP streamed (D2)

    # --- admission: the Assigner sees the two Endpoints and nothing else
    admitted = admit_for_role(chunk, "assigner")
    assert len(admitted) == 2
    assert {a.type for a in admitted} == {"Endpoint"}

    # --- assignment
    seen = {}

    def invoke(messages):
        seen["messages"] = messages
        return _proposal()

    out = assign(chunk, invoke_fn=invoke, inventory=INVENTORY,
                 existing_slugs=frozenset(INVENTORY["services"]), bar=0.75)

    # the prompt carried the admitted Endpoints and nothing else from the chunk
    user = seen["messages"][1].content
    assert "/orders/42" in user and "/ship/7" in user
    for leaked in ("name': 'q", "X-Api", "tok", "s.a"):
        assert leaked not in user

    # terminal quantities
    assert len(out.batch.aggregates) == 2
    assert {a.l0.identity["path"] for a in out.batch.aggregates} == {"/orders/42"}
    assert {a.service_slug for a in out.batch.aggregates} == {"checkout", "fulfilment"}
    assert sorted(a.confidence for a in out.batch.aggregates) == [0.80, 0.90]
    assert out.batch.services == []                     # D4: never mints
    assert out.batch.systems == [] and out.batch.system_edges == []
    assert out.batch.data_items == [] and out.batch.surfaces_at == []
    assert out.batch.data_flows == [] and out.batch.data_relationships == []
    assert len(out.backlog) == 1 and "ghost" in out.backlog[0]


def test_E2_assigner_through_the_supervisor_reports_written():
    from langgraph.checkpoint.memory import MemorySaver

    from polymerhus.analysis.messages import AgentDispatch
    from polymerhus.analysis.supervisor import build_supervisor_graph

    chunk = _build_chunk()
    written = {}

    class _Export:
        services_written = 0
        systems_written = 0
        aggregates_written = 2
        enrichment: dict = {}

    def write_fn(deltas, project_id, provenance):
        written["batch"] = deltas
        return _Export()

    body = make_assigner_body(
        invoke_fn=lambda messages: _proposal(),
        inventory_fn=lambda project_id: INVENTORY,
    )
    graph = build_supervisor_graph(
        proposer_bodies={"assigner": body}, write_fn=write_fn,
    ).compile(checkpointer=MemorySaver())

    state = graph.invoke(
        {
            "project_id": "p1", "run_id": "r1", "receipts": [],
            "schedule": [AgentDispatch(dispatch_id="d1", role="assigner", phase="A1",
                                       mode="create", chunk=chunk)],
        },
        {"configurable": {"thread_id": "r1"}},
    )

    receipts = state["receipts"]
    assert len(receipts) == 1
    (receipt,) = receipts
    assert receipt.role == "assigner"
    assert receipt.phase == "A1"
    assert receipt.status == "written"
    assert receipt.written.aggregates == 2
    assert receipt.written.services == 0

    assert written["batch"].services == []
    assert len(written["batch"].aggregates) == 2
