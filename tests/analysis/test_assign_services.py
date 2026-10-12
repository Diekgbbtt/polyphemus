"""Unit-tier assertions for the v2 per-Service assign pass (ADR D46, T1).

The v2 consumption filter for the Assigner is EACH SERVICE: `assign_services`
grounds ownership on the settled L0 surface one Service at a time. Since T1 a
Service is judged with the FULL live inventory as `existing_slugs`, so it may
name ANY live Service as an owner - there is NO per-Service write filter. The
only surviving gate is the GLOBAL inventory validation: an unknown slug is still
dropped by `drop_out_of_inventory`. The unit context no longer carries the whole
settled surface; the model discovers it through the tools. Everything is injected
(read_fn / inventory_fn / invoke_fn / write_fn / persist_fn / units), so the pass
runs with no Neo4j, no LLM and no database.
"""
import asyncio

from polymerhus.analysis.analyser_types import AggregatesProposal
from polymerhus.analysis.assigner import assign_services
from polymerhus.analysis.chunking import Chunk
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.analysis.reasoning_workflow import AnalysisTurn, Claim

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
        if "EXTRACTION - assign" in messages[0].content:
            return self.turn
        return AnalysisTurn(claims=[Claim(subject="GET /x", assertion="found",
                                          evidence="", verdict="survive")])


class _Writer:
    """Records EVERY batch, so a test can prove what each Service wrote."""

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


def test_per_service_pass_keeps_a_proposal_naming_another_live_service():
    # NO per-Service write filter: the model names BOTH services on every turn, both
    # are live, so EACH Service keeps and writes both proposals (shared ownership).
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

    # one pass per Service, each a six-sub-problem chain
    assert len(invoker.calls) == 2 * 6
    # one write per Service, EACH carrying both services' aggregates (no write filter)
    assert len(writer.batches) == 2
    for batch in writer.batches:
        assert {a.service_slug for a in batch.aggregates} == {"checkout", "fulfilment"}
    assert census.out_of_inventory == 0
    assert census.written == 4
    assert persister.calls == [("ar1", census)]


def test_per_service_pass_still_drops_an_unknown_service_slug():
    # The GLOBAL validation gate survives the write-filter removal: a slug that
    # names no live Service is still dropped (out_of_inventory), never written.
    turn = AnalysisTurn(aggregates=[_agg("/a", 0.99, "ghost"),
                                    _agg("/a", 0.90, "checkout")])
    invoker, writer = _Invoker(turn), _Writer()

    census = asyncio.run(assign_services(
        "p1", "ar1",
        read_fn=lambda pid: _surface("/a"),
        inventory_fn=lambda pid: INVENTORY,
        units=_units("checkout"),
        invoke_fn=invoker, write_fn=writer, persist_fn=lambda *a: None,
    ))

    assert census.out_of_inventory == 1
    assert len(writer.batches) == 1
    assert {a.service_slug for a in writer.batches[0].aggregates} == {"checkout"}


def test_the_unit_context_does_not_carry_the_whole_settled_surface():
    # T1: the settled surface is NOT pre-fed. The first turn (harvest_surface)
    # carries the Service unit and the inventory, and the model discovers the
    # endpoints through the tools - so a multi-Service target's paths never ride
    # the prompt.
    seen = {}

    def invoke(messages, *, schema=None, system_prompt=None):
        seen.setdefault("first", messages[-1].content)
        return AnalysisTurn()

    asyncio.run(assign_services(
        "p1", "ar1",
        read_fn=lambda pid: _surface("/a", "/b", "/c"),
        inventory_fn=lambda pid: INVENTORY,
        units=_units("checkout"),
        invoke_fn=invoke, write_fn=_Writer(), persist_fn=lambda *a: None,
    ))

    first = seen["first"]
    for path in ("/a", "/b", "/c"):
        assert path not in first, f"{path} must be discovered, not pre-fed"
    assert "checkout" in first


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
    assert len(invoker.calls) == 6


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
