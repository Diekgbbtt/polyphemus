"""Unit-tier assertions for the v2 per-Service assign pass (ADR D46).

The v2 consumption filter for the Assigner is EACH SERVICE: `assign_services`
grounds ownership on the settled L0 surface one Service at a time, each judged
with `existing_slugs={slug}`, so a Service can write only its own `AGGREGATES`.
Everything is injected (read_fn / inventory_fn / invoke_fn / write_fn /
persist_fn / units), so the pass runs with no Neo4j, no LLM and no database.
"""
import asyncio

from polymerhus.analysis.analyser_types import AggregatesProposal
from polymerhus.analysis.assigner import assign_services
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.analysis.reasoning_workflow import AnalysisTurn

BU = "https://shop"
INVENTORY = {
    "services": ["checkout", "fulfilment"],
    "systems": [],
    "data_items": [],
    "service_contracts": {"checkout": "Take a basket to a paid order.",
                          "fulfilment": "Ship the paid order."},
}


def _surface(*paths):
    return {
        "nodes": [
            {"type": "Endpoint",
             "properties": {"path": p, "method": "GET", "baseurl": BU}}
            for p in paths
        ],
        "links": [],
    }


def _agg(path, conf, service):
    return AggregatesProposal(
        service_slug=service,
        l0=L0Ref(label="Endpoint", identity={"path": path, "method": "GET", "baseurl": BU}),
        confidence=conf,
        evidence_refs=[f"path segment {path}"],
    )


class _Invoker:
    def __init__(self, turn):
        self.turn = turn
        self.calls = []

    def __call__(self, messages, *, schema=None, system_prompt=None):
        self.calls.append(messages)
        return self.turn


class _Writer:
    """Records EVERY batch, so a test can prove each Service wrote only its own."""

    def __init__(self):
        self.batches = []

    def __call__(self, batch, project_id):
        self.batches.append(batch)
        return len(batch.aggregates)


class _Persister:
    def __init__(self):
        self.calls = []

    def __call__(self, run_id, census):
        self.calls.append((run_id, census))


def _units(*slugs):
    return [Chunk(chunk_id=s, source_job=f"service:{s}", assets=()) for s in slugs]


def test_per_service_pass_writes_only_each_services_own_aggregates():
    # The model names BOTH services on every turn; the per-Service validation set
    # (`existing_slugs={slug}`) is what keeps each write to its own Service.
    turn = AnalysisTurn(aggregates=[_agg("/a", 0.90, "checkout"),
                                    _agg("/b", 0.90, "fulfilment")])
    invoker, writer, persister = _Invoker(turn), _Writer(), _Persister()

    census = asyncio.run(assign_services(
        "p1", "ar1",
        read_fn=lambda pid: _surface("/a", "/b"),
        inventory_fn=lambda pid: INVENTORY,
        units=_units("checkout", "fulfilment"),
        invoke_fn=invoker, write_fn=writer, persist_fn=persister,
    ))

    # one pass per Service, each a five-sub-problem chain
    assert len(invoker.calls) == 2 * 5
    # one write per Service, each carrying ONLY that Service's aggregate
    assert len(writer.batches) == 2
    assert {a.service_slug for a in writer.batches[0].aggregates} == {"checkout"}
    assert {a.service_slug for a in writer.batches[1].aggregates} == {"fulfilment"}
    assert census.written == 2
    assert persister.calls == [("ar1", census)]


def test_per_service_pass_skips_a_slug_that_is_not_in_the_inventory():
    invoker, writer = _Invoker(AnalysisTurn()), _Writer()
    asyncio.run(assign_services(
        "p1", "ar1",
        read_fn=lambda pid: _surface("/a"),
        inventory_fn=lambda pid: INVENTORY,
        units=_units("checkout", "ghost"),
        invoke_fn=invoker, write_fn=writer, persist_fn=lambda *a: None,
    ))
    # only the in-inventory Service gets a pass
    assert len(invoker.calls) == 5


def test_per_service_pass_degrades_cleanly_on_a_read_failure():
    def boom(pid):
        raise RuntimeError("neo4j down")

    writer = _Writer()
    census = asyncio.run(assign_services(
        "p1", "ar1",
        read_fn=boom,
        inventory_fn=lambda pid: INVENTORY,
        units=_units("checkout"),
        invoke_fn=_Invoker(AnalysisTurn()), write_fn=writer,
        persist_fn=lambda *a: None,
    ))
    assert census.written == 0
    assert writer.batches == []
