"""Unit-tier assertions for the global assign pass (T4).

The pass re-reads the SETTLED L0 surface and the Service inventory, runs the
Assigner's whole workflow (harvest_surface -> falsify_harvest -> prior_insights ->
candidate_owners -> assign -> closure) over the whole surface via an injected invoke
seam, writes `AGGREGATES` through the no-mint writer, and reports the census.
Everything is injected (read_fn / inventory_fn / invoke_fn / write_fn
/ persist_fn), so the whole pass runs with no Neo4j, no LLM and no database.

The properties pinned here:

- the five shaping gates are reused UNCHANGED (narrow / resolve / inventory /
  normalise / withhold), and the census counts where each judgment died;
- the pass never mints a Service (the Bootstrapper stays the sole source);
- the residual `stale` count is the surface left with no owner;
- an empty or degraded result yields a zero census, zero writes, and never raises.
"""
import asyncio

from polymerhus.analysis.analyser_types import AggregatesProposal, ServiceProposal
from polymerhus.analysis.assigner import AssignmentCensus, assign_global
from polymerhus.analysis.l1_types import L0Ref
from polymerhus.analysis.reasoning_workflow import AnalysisTurn, Claim

BU = "https://shop"
INVENTORY = {
    "services": ["checkout", "fulfilment"],
    "systems": [],
    "data_items": [],
    "service_contracts": {"checkout": "Take a basket to a paid order."},
}


def _run(coro):
    return asyncio.run(coro)


def _surface(*paths):
    """A pod-shaped L0 read: `{nodes, links}` with Endpoint nodes only."""
    return {
        "nodes": [
            {"type": "Endpoint",
             "properties": {"path": p, "method": "GET", "baseurl": BU}}
            for p in paths
        ],
        "links": [],
    }


def _agg(path, conf, service="checkout"):
    return AggregatesProposal(
        service_slug=service,
        l0=L0Ref(label="Endpoint", identity={"path": path, "method": "GET", "baseurl": BU}),
        confidence=conf,
        evidence_refs=[f"path segment {path}"],
    )


class _Invoker:
    """An invoke seam that records its calls and returns a PER-STEP turn: a
    `survive` claim for the reasoning steps (so the bounded harvest yields a
    surface and the chain reaches `assign`), and the fixed turn for the `assign`
    extraction step. A real model never returns the extraction turn for every
    sub-problem; this stub mirrors that."""

    def __init__(self, turn):
        self.turn = turn
        self.calls = []

    def __call__(self, messages, *, schema=None, system_prompt=None):
        self.calls.append((messages, schema, system_prompt))
        if "EXTRACTION - assign" in messages[0].content:
            return self.turn
        return AnalysisTurn(claims=[Claim(subject="GET /x", assertion="found",
                                          evidence="", verdict="survive")])


class _Writer:
    def __init__(self):
        self.batch = None
        self.calls = 0

    def __call__(self, batch, project_id):
        self.batch = batch
        self.calls += 1
        return len(batch.aggregates)


class _Persister:
    def __init__(self):
        self.calls = []

    def __call__(self, run_id, census):
        self.calls.append((run_id, census))


def test_global_pass_applies_the_five_gates_and_reports_the_census():
    turn = AnalysisTurn(
        services=[ServiceProposal(business_function_slug="smuggled")],
        aggregates=[
            _agg("/a", 0.90),                 # kept
            _agg("/b", 0.50),                 # withheld (below bar)
            _agg("/c", 0.99, service="ghost"),  # out of inventory
            _agg("/missing", 0.99),           # unresolvable (not on the surface)
            _agg("/a", 85.0),                 # percentage -> 0.85, kept
        ],
    )
    invoker, writer, persister = _Invoker(turn), _Writer(), _Persister()

    census = _run(assign_global(
        "p1", "ar1",
        read_fn=lambda pid: _surface("/a", "/b", "/c", "/d"),
        inventory_fn=lambda pid: INVENTORY,
        invoke_fn=invoker,
        write_fn=writer,
        persist_fn=persister,
    ))

    assert census.admitted == 4
    assert census.proposed == 5
    assert census.unresolvable == 1
    assert census.out_of_inventory == 1
    assert census.rescaled == 1
    assert census.withheld == 1
    assert census.kept == 2
    assert census.written == 2
    assert census.stale == 3                    # /b, /c, /d left with no owner

    # the writer saw ONLY the shaped aggregates, and never a Service (no mint)
    assert writer.calls == 1
    assert writer.batch.services == []
    assert {a.l0.identity["path"] for a in writer.batch.aggregates} == {"/a"}
    assert all(a.service_slug == "checkout" for a in writer.batch.aggregates)

    # the census is returned AND persisted
    assert persister.calls == [("ar1", census)]


def test_stale_counts_only_endpoints_with_no_kept_owner():
    invoker = _Invoker(AnalysisTurn(aggregates=[_agg("/a", 0.90)]))
    census = _run(assign_global(
        "p1", "ar1",
        read_fn=lambda pid: _surface("/a", "/b"),
        inventory_fn=lambda pid: INVENTORY,
        invoke_fn=invoker, write_fn=_Writer(), persist_fn=_Persister(),
    ))
    assert (census.admitted, census.kept, census.stale) == (2, 1, 1)


def test_the_whole_surface_is_grouped_into_one_pass():
    invoker = _Invoker(AnalysisTurn())
    census = _run(assign_global(
        "p1", "ar1",
        read_fn=lambda pid: _surface("/a", "/b", "/c"),
        inventory_fn=lambda pid: INVENTORY,
        invoke_fn=invoker, write_fn=_Writer(), persist_fn=_Persister(),
    ))
    # the Assigner's six v2 sub-problems: harvest_surface, falsify_harvest,
    # prior_insights, candidate_owners, assign, closure
    assert len(invoker.calls) == 6
    # the WHOLE surface is admitted in the one pass (the deterministic gates see it)
    # AND it is now pre-fed in the hoisted endpoint-first block of the first turn.
    assert census.admitted == 3
    first_user = invoker.calls[0][0][-1].content
    assert "checkout" in first_user
    assert "/a" in first_user and "/b" in first_user and "/c" in first_user


def test_global_pass_turns_bind_notes_and_the_backstop_writes_an_assignment_note(
        monkeypatch, tmp_path):
    """Spec 3.2/5 + ADR D26/D31: the global assign pass is a proposer too, so its
    two sub-problem turns bind the SAME `{analysis_turn, notes}` set the per-Service
    proposers bind - it must NOT fall back to the notes-less one-shot seam - and the
    per-unit backstop records an `assignment` note for the pass. The `assignment`
    kind is otherwise unreachable in `service_sourced`."""
    from polymerhus.analysis.memory import AnalysisMemoryStore

    seen: list[dict] = []

    def seam(role_id, thread, messages, **kw):
        seen.append(kw)
        # A `survive` claim keeps the bounded harvest non-empty, so the chain
        # reaches every sub-problem (this test asserts all six bind notes).
        return AnalysisTurn(claims=[Claim(subject="GET /x", assertion="found",
                                          evidence="", verdict="survive")])

    monkeypatch.setattr("polymerhus.app.llm.session.stateful_turn", seam)
    store = AnalysisMemoryStore(root_dir=tmp_path)

    _run(assign_global(
        "p1", "ar1",
        read_fn=lambda pid: _surface("/a"),
        inventory_fn=lambda pid: INVENTORY,
        write_fn=_Writer(), persist_fn=_Persister(),
        memory=store, checkpointer=object(),
    ))

    # every sub-problem turn ran through the notes-bound seam (not `default_invoke_fn`)
    assert len(seen) == 6
    for kw in seen:
        names = {getattr(t, "name", "") for t in kw.get("tools") or ()}
        assert "notes" in names, "every global-pass turn binds notes (D26)"
    # the pass's unit note exists, and it is an `assignment` note
    notes = store.read_notes("p1", parent_key="global:ar1")
    assert [n["kind"] for n in notes] == ["assignment"]


def test_empty_surface_writes_nothing_and_invokes_nobody():
    invoker, writer, persister = _Invoker(AnalysisTurn(aggregates=[_agg("/a", 0.90)])), _Writer(), _Persister()
    census = _run(assign_global(
        "p1", "ar1",
        read_fn=lambda pid: _surface(),
        inventory_fn=lambda pid: INVENTORY,
        invoke_fn=invoker, write_fn=writer, persist_fn=persister,
    ))
    assert census == AssignmentCensus()
    assert invoker.calls == []      # no LLM turn on an empty surface
    assert writer.calls == 0        # zero writes
    assert persister.calls and persister.calls[0][1] == AssignmentCensus()


def test_read_failure_degrades_to_a_zero_census():
    def boom(pid):
        raise RuntimeError("neo4j down")

    writer = _Writer()
    census = _run(assign_global(
        "p1", "ar1",
        read_fn=boom, inventory_fn=lambda pid: INVENTORY,
        invoke_fn=_Invoker(AnalysisTurn(aggregates=[_agg("/a", 0.90)])),
        write_fn=writer, persist_fn=_Persister(),
    ))
    assert census == AssignmentCensus()
    assert writer.calls == 0


def test_invoke_failure_writes_nothing_and_reports_the_surface_as_stale():
    def boom(messages, *, schema=None, system_prompt=None):
        raise RuntimeError("llm down")

    writer = _Writer()
    census = _run(assign_global(
        "p1", "ar1",
        read_fn=lambda pid: _surface("/a"), inventory_fn=lambda pid: INVENTORY,
        invoke_fn=boom, write_fn=writer, persist_fn=_Persister(),
    ))
    # the surface was read but the model produced nothing: zero writes, and the
    # element is honestly reported as still stale - not silently dropped
    assert census.written == 0
    assert census.proposed == 0 and census.kept == 0
    assert census.admitted == 1 and census.stale == 1
    assert writer.calls == 0


def test_default_write_only_calls_write_aggregates_never_mints(monkeypatch):
    import polymerhus.analysis.l1_curator as l1_curator

    calls = []
    monkeypatch.setattr(l1_curator, "write_aggregates",
                        lambda deltas, pid, **kw: (calls.append(("aggregates", len(deltas))), len(deltas))[1])
    monkeypatch.setattr(l1_curator, "l1_curate",
                        lambda *a, **kw: calls.append(("curate", a)) or (0, 0))

    census = _run(assign_global(
        "p1", "ar1",
        read_fn=lambda pid: _surface("/a"), inventory_fn=lambda pid: INVENTORY,
        invoke_fn=_Invoker(AnalysisTurn(aggregates=[_agg("/a", 0.90)])),
        persist_fn=_Persister(),
    ))
    assert census.written == 1
    assert [c[0] for c in calls] == ["aggregates"]   # l1_curate is never reached


def test_default_persistence_merges_the_census_into_analysis_run_stats(monkeypatch):
    import polymerhus.app.clients.pg as pg

    calls = []
    monkeypatch.setattr(pg, "set_analysis_run_status",
                        lambda rid, status, stats=None: calls.append((rid, status, stats)))

    census = _run(assign_global(
        "p1", "ar1",
        read_fn=lambda pid: _surface("/a"), inventory_fn=lambda pid: INVENTORY,
        invoke_fn=_Invoker(AnalysisTurn(aggregates=[_agg("/a", 0.90)])),
        write_fn=_Writer(),
    ))
    assert calls == [("ar1", "draining", {"assignment_census": census.model_dump()})]
