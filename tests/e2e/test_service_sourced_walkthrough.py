"""No-mock pipeline walkthrough for the service-sourced pass (T7, spec section 8).

Mirrors `tests/e2e/test_bootstrap_reasoned_walkthrough.py` in shape - the WHOLE
system runs end to end - but over INJECTED fakes for the two external seams (the
LLM and the graph), the way every seam is designed to be injected (CODING_STANDARD
section 6). Nothing is monkeypatched: `service_sourced_pass` runs its real stages,
`assign_global` runs the Assigner's real workflow (harvest_surface -> falsify_harvest
-> prior_insights -> candidate_owners -> assign -> closure) and its five shaping gates,
and `run_service_loop` runs the real Service-slice builder,
the supervisor control plane, and each role's real `ReasoningWorkflow`.

The assertions are the observable L1 counts the pipeline produced: the AGGREGATES
the global pass wrote, and the Systems / DataItems the per-Service loop wrote
through the sole-writer seam. This is the pipeline's behavioural contract at the
integration boundary - a unit test pins one seam, this pins them composed.

Runs in the e2e tree (the sanctioned walkthrough tier); it makes no live call and
needs no docker, Neo4j or LLM.
"""
from __future__ import annotations

import asyncio
from functools import partial

from polymerhus.analysis.analyser_types import (
    AggregatesProposal,
    DataFlowProposal,
    DataItemProposal,
    SurfacesAtProposal,
    SystemEdgeProposal,
    SystemProposal,
)
from polymerhus.analysis.feed import L0Chunk
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.analysis.memory import AnalysisMemoryStore
from polymerhus.analysis.pod import AnalyserExport
from polymerhus.analysis.reasoning_workflow import AnalysisTurn, Claim
from polymerhus.analysis.service_sourced import reset_pass_guard, service_sourced_pass
from polymerhus.analysis.assigner import assign_global
from polymerhus.analysis.service_slice import run_service_loop
from polymerhus.recon.domain.types import AssetDelta

BU = "https://shop"

# The bootstrapped Service inventory the run starts from: one Service, and the
# contract the global Assigner routes against.
_INVENTORY = {
    "services": ["checkout"],
    "systems": [],
    "data_items": [],
    "service_contracts": {"checkout": "Takes a basket to a paid order."},
}

# The settled L0 surface. Endpoints carry the AGGREGATES hinge; the Parameter is
# the surface site the data-modeller binds a DataItem to.
_ENDPOINTS = [
    {"type": "Endpoint", "properties": {"path": "/orders", "method": "GET", "baseurl": BU}},
]
_PARAMETERS = [
    {"type": "Parameter",
     "properties": {"name": "items", "position": "body", "endpoint_path": "/orders",
                    "baseurl": BU}},
]
_SURFACE = _ENDPOINTS + _PARAMETERS
# The same surface as typed `AssetDelta`s, the form the slice builder consumes.
_SURFACE_ASSETS = [
    AssetDelta(type="Endpoint",
               identity={"path": "/orders", "method": "GET", "baseurl": BU}),
    AssetDelta(type="Parameter",
               identity={"name": "items", "position": "body", "endpoint_path": "/orders",
                         "baseurl": BU}),
]


def _pod_read(project_id: str) -> dict:
    """The pod-shaped L0 read `assign_global` consumes: `{nodes, links}`."""
    return {"nodes": [dict(n) for n in _ENDPOINTS], "links": []}


def _live_aggregations() -> list[dict]:
    """The Service->L0 aggregation view both the slice builder and the role bodies
    read: one Endpoint row and one Parameter row, both owned by `checkout`."""
    return [
        {"slug": "checkout", "labels": ["Endpoint"],
         "props": {"path": "/orders", "method": "GET", "baseurl": BU}},
        {"slug": "checkout", "labels": ["Parameter"],
         "props": {"name": "items", "position": "body", "endpoint_path": "/orders",
                   "baseurl": BU}},
    ]


def _slice_read(project_id: str):
    """The slice builder's read seam: `(services, aggregations, assets)`."""
    return (["checkout"], _live_aggregations(), list(_SURFACE_ASSETS))


def _inv(_pid: str) -> dict:
    return _INVENTORY


class _Capture:
    """The sole-writer seam: counts the L1 deltas each role actually wrote."""

    def __init__(self) -> None:
        self.aggregates = 0
        self.systems = 0
        self.system_edges = 0
        self.data_items = 0
        self.writes: list[tuple[str, int]] = []

    # `assign_global`'s writer: `write_fn(batch, project_id) -> written count`.
    def assign_write(self, batch, project_id) -> int:
        self.aggregates += len(batch.aggregates)
        self.writes.append(("global", len(batch.aggregates)))
        return len(batch.aggregates)

    # `run_service_loop`'s writer (the chunked `_chunked_write_fn` shape):
    # `write_fn(deltas, project_id, provenance) -> AnalyserExport`.
    def loop_write(self, deltas, project_id, provenance) -> AnalyserExport:
        self.systems += len(deltas.systems)
        self.system_edges += len(deltas.system_edges)
        self.data_items += len(deltas.data_items)
        self.writes.append(("loop", len(deltas.systems) + len(deltas.data_items)))
        return AnalyserExport(
            systems_written=len(deltas.systems),
            aggregates_written=len(deltas.aggregates),
            # The loop reads data-item writes off the export's `enrichment` map
            # (`supervisor._write_counts`), so the count rides there.
            enrichment={"data_items": len(deltas.data_items)},
        )


def _global_invoke(messages, *, schema=None, system_prompt=None):
    """The global Assigner's LLM seam: the `assign` extraction turn returns one
    aggregate for `/orders`, which the five shaping gates keep."""
    return AnalysisTurn(aggregates=[AggregatesProposal(
        service_slug="checkout",
        l0=L0Ref(label="Endpoint", identity={"path": "/orders", "method": "GET", "baseurl": BU}),
        confidence=0.9,
        evidence_refs=["path segment /orders"],
    )])


def _typist_invoke(messages, *, schema=None, system_prompt=None):
    """The mechanism-typist's LLM seam, routed on the sub-problem task text."""
    task = messages[-1].content
    if "TASK - EXTRACT SYSTEMS" in task:
        return AnalysisTurn(systems=[SystemProposal(
            kind="RESTApi", props={"description": "JSON REST paradigm the checkout exposes."})])
    if "TASK - LINK SERVICES" in task:
        return AnalysisTurn(system_edges=[SystemEdgeProposal(
            service_slug="checkout", kind="RESTApi", rel="EXPOSED_VIA")])
    return AnalysisTurn(claims=[Claim(
        subject="Endpoint /orders", assertion="RESTApi overlay",
        evidence="JSON content type", verdict="new RESTApi")])


def _modeller_invoke(messages, *, schema=None, system_prompt=None):
    """The data-modeller's LLM seam, routed on the sub-problem task text."""
    task = messages[-1].content
    if "TASK - EXTRACT THE DATA ITEMS" in task:
        return AnalysisTurn(
            data_items=[DataItemProposal(item_key="shopping_basket",
                                         props={"fields": ["items"],
                                                "notes": "client-supplied basket lines"})],
            surfaces_at=[SurfacesAtProposal(
                item_key="shopping_basket",
                l0=L0Ref(label="Parameter",
                         identity={"name": "items", "position": "body",
                                   "endpoint_path": "/orders", "baseurl": BU}))],
        )
    if "TASK - EXTRACT THE FLOWS" in task:
        return AnalysisTurn(data_flows=[DataFlowProposal(
            service_slug="checkout", item_key="shopping_basket", direction="produces")])
    return AnalysisTurn(claims=[Claim(
        subject="Parameter items", assertion="basket line set",
        evidence="items parameter on /orders", verdict="coin shopping_basket")])


def test_service_sourced_pass_runs_end_to_end_and_writes_l1(tmp_path):
    """The whole pass: global assign then the per-Service loop, over injected fakes.

    The observable contract is the L1 the run produced - one AGGREGATES hinge, one
    System, one DataItem - plus a terminal, write-based census (ADR D41)."""
    reset_pass_guard()
    capture = _Capture()
    persisted: list = []
    memory = AnalysisMemoryStore(root_dir=tmp_path)

    result = asyncio.run(service_sourced_pass(
        L0Chunk(project_id="p1", run_id="run-walk", terminal=True),
        assign_fn=partial(
            assign_global, read_fn=_pod_read, inventory_fn=_inv,
            invoke_fn=_global_invoke, write_fn=capture.assign_write,
            persist_fn=lambda rid, census: persisted.append((rid, census)),
        ),
        loop_fn=partial(
            run_service_loop, read_fn=_slice_read, inventory_fn=_inv,
            aggregations_fn=lambda pid: _live_aggregations(),
            invoke_fns={"mechanism_typist": _typist_invoke,
                        "data_modeller": _modeller_invoke},
            write_fn=capture.loop_write, attempts=1,
        ),
        status_fn=lambda rid: "complete", status_wait_s=0, memory=memory, observe=False,
    ))

    # --- the observable L1 the pipeline wrote ---------------------------------
    assert capture.aggregates == 1           # the AGGREGATES hinge
    assert capture.systems == 1              # the System the typist typed
    assert capture.system_edges == 1         # its Service->System link
    assert capture.data_items == 1           # the DataItem the modeller lifted

    # --- the terminal census tells the truth about what was written -----------
    assert result.census.terminal is True
    assert result.census.unprocessed_after == 0
    assert result.census.wrote is True        # write-based drained signal (ADR D41)
    assert result.census.stopped is False
    assert result.census.units_processed == 1  # the one Service unit
    assert result.census.aggregates_written == 1
    assert result.census.systems_written == 1
    assert result.census.data_items_written == 1

    # --- the census is persisted and the per-unit backstop noted the Service ---
    assert [rid for rid, _c in persisted] == ["run-walk"]
    assert persisted[0][1].written == 1
    assert memory.has_note("p1", "checkout")
