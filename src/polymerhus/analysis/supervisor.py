"""Analyser control plane: the central supervisor + the message topology.

Increment 0 (#22) built this with HOLLOW agents. Increment 2a (#24) makes it the
"async is runnable" checkpoint: a proposer node can now carry a real `L1DeltaBatch`
and the curator can WRITE it through the sole-writer, so the async supervisor runs
the LEGACY analyser and produces the same `AnalyserExport` the legacy pod does -
with the durable `AsyncPostgresStore` and the #18 observability recipe wired - all
still behind `analysis.supervisor_enabled` (default OFF). The per-responsibility
decomposition, the chunk feeding, and the `_two_pass_analyse` dissolution are 2b.

Topology (#17 DP-5/DP-7), unchanged from increment 0:
  START -> supervisor
  supervisor --Command(goto=role)--> <one of 5 proposers>   (dynamic routing, ONLY here)
  <proposer> --edge--> auditor --edge--> curator --edge--> supervisor   (STATIC pipeline)
  supervisor --Command(goto=END)--> END                     (schedule exhausted)

State (#17): every field is LAST-WRITE (one logical writer per sequential super-step)
EXCEPT `receipts`, the one reducer channel (dedup-by-dispatch_id). There is NO
proposal-accumulator channel: the live graph is the accumulator.
"""
from __future__ import annotations

from typing import Annotated, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from polymerhus.analysis.analyser_types import L1DeltaBatch
from polymerhus.analysis.l1_types import Provenance
from polymerhus.analysis.messages import (
    PROPOSER_ROLES,
    AgentDispatch,
    ProposalEnvelope,
    Role,
    StepReceipt,
    SteeringState,
    WriteCounts,
)

# A proposer BODY does the per-role work and RETURNS its cargo (an `L1DeltaBatch`)
# or `None` (hollow). It may raise - the wrapper degrades fail-open.
ProposerBody = Callable[[AgentDispatch, dict], "L1DeltaBatch | None"]
# The auditor BODY (increment 3) returns verdicts to annotate; None = hollow.
AuditorBody = Callable[[ProposalEnvelope, dict], list]
# The curator WRITE seam: writes an envelope's deltas through the sole-writer and
# returns the run's `AnalyserExport` (increment 2a); None = hollow passthrough.
WriteFn = Callable[["L1DeltaBatch", str, Provenance], object]


def merge_receipts(
    existing: list[StepReceipt] | None, incoming: list[StepReceipt] | None
) -> list[StepReceipt]:
    """Fan-in reducer for the receipts trail: dedup by `dispatch_id`.

    A receipt whose `dispatch_id` already exists REPLACES in place (idempotent
    replay = the state-level mirror of the idempotent MERGE, #17 DP-3); a new one
    appends. First-appearance order is preserved. T2's multi-writer fan-in fix
    applies HERE, to the receipts OUTCOME trail - never to proposals."""
    by_id: dict[str, StepReceipt] = {}
    order: list[str] = []
    for r in list(existing or []) + list(incoming or []):
        if r.dispatch_id not in by_id:
            order.append(r.dispatch_id)
        by_id[r.dispatch_id] = r
    return [by_id[d] for d in order]


class SupervisorState(TypedDict, total=False):
    """The supervisor's channels. All last-write except `receipts` (the sole
    reducer channel). No accumulated-proposals channel exists by design (#17).
    `l0_slice` / `observations` are transitional 2a inputs the legacy-wrapping
    proposer reads; 2b removes them once chunks carry the delta."""

    project_id: str
    run_id: str
    model: str
    schedule: list[AgentDispatch]      # last-write: the supervisor rewrites the tail
    dispatch: AgentDispatch | None     # last-write: the current work order
    inflight: ProposalEnvelope | None  # last-write: the baton (one writer/super-step)
    receipts: Annotated[list[StepReceipt], merge_receipts]  # the ONLY reducer channel
    steer: SteeringState               # carried, inert in increment 0
    l0_slice: dict                     # transitional (2a legacy wrapping); removed at 2b
    observations: list                 # transitional (2a legacy wrapping); removed at 2b


def _has_content(batch: L1DeltaBatch) -> bool:
    """True when the proposal batch carries at least one delta of any kind."""
    return any((
        batch.services, batch.systems, batch.aggregates, batch.data_items,
        batch.surfaces_at, batch.data_flows, batch.data_relationships, batch.system_edges,
    ))


def _write_counts(export: object) -> WriteCounts:
    """Map a curate collaborator's `AnalyserExport` to the receipt's `WriteCounts`."""
    enrichment = getattr(export, "enrichment", None) or {}
    enrich_total = sum(v for v in enrichment.values() if isinstance(v, int))
    return WriteCounts(
        services=getattr(export, "services_written", 0) or 0,
        systems=getattr(export, "systems_written", 0) or 0,
        aggregates=getattr(export, "aggregates_written", 0) or 0,
        enrichment=enrich_total,
    )


# --- nodes --------------------------------------------------------------------

def _supervisor(state: SupervisorState) -> Command:
    """Pop the head of the schedule, set it as the current dispatch, and route to
    its proposer with `Command(goto=role)` (routing ONLY; the payload travels as
    the typed `AgentDispatch` on state). An empty schedule terminates cleanly."""
    schedule = list(state.get("schedule") or [])
    if not schedule:
        return Command(goto=END)
    head, *tail = schedule
    return Command(goto=head.role, update={"dispatch": head, "schedule": tail})


def _make_proposer(role: Role, body: ProposerBody | None) -> Callable[[SupervisorState], dict]:
    """Build a proposer wrapper-node (subgraph-capable per DP-7). A body RETURNS an
    `L1DeltaBatch` (real cargo, increment 2a) or `None` (hollow, increment 0); the
    wrapper rides the cargo on the envelope. Fail-open: a body that raises degrades
    to `status='degraded'` carrying the error, never propagating out of the graph."""

    def proposer(state: SupervisorState) -> dict:
        dispatch = state["dispatch"]
        try:
            cargo = body(dispatch, state) if body is not None else None
            deltas = cargo if isinstance(cargo, L1DeltaBatch) else None
            env = ProposalEnvelope(
                dispatch_id=dispatch.dispatch_id, role=dispatch.role,
                phase=dispatch.phase, deltas=deltas, status="empty",
            )
        except Exception as exc:  # fail-open, mirroring the legacy pod's per-node discipline
            env = ProposalEnvelope(
                dispatch_id=dispatch.dispatch_id, role=dispatch.role,
                phase=dispatch.phase, status="degraded", error=str(exc),
            )
        return {"inflight": env}

    return proposer


def _make_auditor(body: AuditorBody | None) -> Callable[[SupervisorState], dict]:
    """The fixed checker stage after every proposer (#17: never dispatched).
    HOLLOW default: annotates nothing (`verdicts` stays `[]`), blocks nothing.
    Increment 3 supplies the score-and-annotate body."""

    def auditor(state: SupervisorState) -> dict:
        env = state.get("inflight")
        if body is not None and env is not None:
            verdicts = body(env, state) or []
            if verdicts:
                return {"inflight": env.model_copy(update={"verdicts": list(verdicts)})}
        return {}

    return auditor


def _make_curator(write_fn: WriteFn | None) -> Callable[[SupervisorState], dict]:
    """Plain node (#17 DP-7): turn the baton into a `StepReceipt` and hand it up.

    HOLLOW (increment 0, `write_fn=None`): the receipt mirrors the envelope status
    with zero counts. WRITING (increment 2a, `write_fn` set): when the envelope
    carries a non-empty `L1DeltaBatch`, write it through the sole-writer with
    system-supplied provenance and emit `StepReceipt(status="written")` with real
    `WriteCounts`. Fail-open: a write error degrades to `status="degraded"`."""

    def curator(state: SupervisorState) -> dict:
        env = state.get("inflight")
        if env is None:  # defensive: no baton -> nothing to record
            return {}
        if write_fn is not None and env.deltas is not None and _has_content(env.deltas):
            provenance = Provenance(
                job=f"analyser:{state.get('run_id', '')}",
                model=state.get("model"), prompt_id=None,
            )
            try:
                export = write_fn(env.deltas, state["project_id"], provenance)
            except Exception as exc:  # a write failure degrades, never crashes the run
                receipt = StepReceipt(
                    dispatch_id=env.dispatch_id, role=env.role, phase=env.phase,
                    status="degraded", error=str(exc),
                )
                return {"receipts": [receipt]}
            receipt = StepReceipt(
                dispatch_id=env.dispatch_id, role=env.role, phase=env.phase,
                status="written", written=_write_counts(export),
            )
            return {"receipts": [receipt]}
        # hollow passthrough (increment 0): mirror the envelope status, zero counts.
        receipt = StepReceipt(
            dispatch_id=env.dispatch_id, role=env.role, phase=env.phase,
            status=env.status, error=env.error,
        )
        return {"receipts": [receipt]}

    return curator


# --- graph --------------------------------------------------------------------

def build_supervisor_graph(
    *,
    proposer_bodies: dict[str, ProposerBody] | None = None,
    auditor_body: AuditorBody | None = None,
    curator_fn: Callable[[SupervisorState], dict] | None = None,
    write_fn: WriteFn | None = None,
) -> StateGraph:
    """Build (do NOT compile) the supervisor graph. Injectable seams:
      - `proposer_bodies[role]` - a per-role work body returning an `L1DeltaBatch`
        or `None` (hollow when absent);
      - `auditor_body` - the score-and-annotate check (hollow when absent);
      - `write_fn` - the curator's sole-writer collaborator (hollow when absent);
      - `curator_fn` - override the whole curator node (wins over `write_fn`).
    Static edges wire proposer -> auditor -> curator -> supervisor; the supervisor
    routes out via `Command(goto=...)` alone (DP-5: the both-paths-fire pitfall
    cannot occur)."""
    proposer_bodies = proposer_bodies or {}
    g = StateGraph(SupervisorState)

    g.add_node("supervisor", _supervisor)
    g.add_node("auditor", _make_auditor(auditor_body))
    g.add_node("curator", curator_fn or _make_curator(write_fn))
    for role in PROPOSER_ROLES:
        g.add_node(role, _make_proposer(role, proposer_bodies.get(role)))
        g.add_edge(role, "auditor")     # static
    g.add_edge("auditor", "curator")    # static
    g.add_edge("curator", "supervisor")  # static: outcome returns to the supervisor
    g.add_edge(START, "supervisor")
    return g


# --- async-native driver ------------------------------------------------------

def _initial_state(
    project_id: str, run_id: str, schedule: list[AgentDispatch] | None,
    *, l0_slice: dict | None, observations: list | None,
) -> SupervisorState:
    return {
        "project_id": project_id, "run_id": run_id,
        "schedule": list(schedule or []), "dispatch": None, "inflight": None,
        "receipts": [], "steer": SteeringState(),
        "l0_slice": l0_slice or {}, "observations": observations or [],
    }


def _flush_langfuse() -> None:
    """Flush pending Langfuse spans at run end so an outage/timeout does not drop a
    run's trace (the #18 recipe; `flush()` not `shutdown()` - the client is a
    process-wide singleton reused by later runs). Fail-open."""
    try:
        from langfuse import get_client
        get_client().flush()
    except Exception:  # tracing is best-effort; never fail a run on it
        pass


def _observability_config(config: dict, run_id: str) -> dict:
    """Attach the #18 Langfuse callbacks + a correct session id to the run config
    (closing the trace-correlation gap: the session id WAS computed but never
    passed as metadata). Empty callbacks are inert."""
    from polymerhus.app.observability import get_langfuse_callbacks

    config = dict(config)
    config["callbacks"] = get_langfuse_callbacks()
    config["metadata"] = {
        "langfuse_session_id": run_id,
        "langfuse_tags": ["analyser", "supervisor"],
    }
    return config


async def run_supervisor(
    project_id: str,
    run_id: str,
    schedule: list[AgentDispatch] | None = None,
    *,
    l0_slice: dict | None = None,
    observations: list | None = None,
    checkpointer=None,
    store=None,
    builder: StateGraph | None = None,
    thread_id: str | None = None,
    observe: bool = True,
) -> SupervisorState:
    """Drive the control plane async-native (`ainvoke`). A `checkpointer` (+ `store`)
    is injected in tests (`MemorySaver` / `InMemoryStore`); in production both are
    left None and the `AsyncPostgresSaver` + `AsyncPostgresStore` are opened here for
    the run (the Store `setup()` is idempotent). Returns the terminal
    `SupervisorState`."""
    builder = builder or build_supervisor_graph()
    state = _initial_state(project_id, run_id, schedule, l0_slice=l0_slice, observations=observations)
    config: dict = {"configurable": {"thread_id": thread_id or run_id}}
    if observe:
        config = _observability_config(config, run_id)

    if checkpointer is not None:
        compiled = builder.compile(checkpointer=checkpointer, store=store)
        try:
            return await compiled.ainvoke(state, config)
        finally:
            if observe:
                _flush_langfuse()

    from polymerhus.app.config import config as app_config
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.store.postgres.aio import AsyncPostgresStore

    async with (
        AsyncPostgresSaver.from_conn_string(app_config.POSTGRES_DSN) as saver,
        AsyncPostgresStore.from_conn_string(app_config.POSTGRES_DSN) as pg_store,
    ):
        await pg_store.setup()
        compiled = builder.compile(checkpointer=saver, store=pg_store)
        try:
            return await compiled.ainvoke(state, config)
        finally:
            if observe:
                _flush_langfuse()


# --- coexistence: the analysis.supervisor_enabled flag ------------------------

def resolve_supervisor_enabled(project_id: str, *, settings_fn=None) -> bool:
    """Read the orthogonal `analysis.supervisor_enabled` flag from project
    settings, fail-open to False so the legacy pod stays the default (a two-way
    door: rollback is a flag flip). Mirrors how `streaming_analysis` is read from
    the same settings blob."""
    if settings_fn is None:
        from polymerhus.app.clients.pg import load_settings as settings_fn
    try:
        settings = settings_fn(project_id) or {}
    except Exception:  # a settings-read failure must never enable the new path
        return False
    return bool(settings.get("supervisor_enabled"))


def run_analyser_supervised(
    project_id: str,
    run_id: str,
    observations=None,
    *,
    read_fn=None,
    analyse_fn=None,
    curate_fn=None,
    checkpointer=None,
    store=None,
    observe: bool = True,
):
    """Sync bridge from `run_analyser` (offloaded via `asyncio.to_thread` by both
    callers, so this worker thread has no running loop) into the born-async
    supervisor, driven with `asyncio.run` (increment 2a).

    Wraps the LEGACY analyser as the supervisor's nodes: it reads the whole L0
    slice and delivers observations exactly as the legacy `run_analyser` does, then
    runs ONE `assigner` dispatch whose body is the legacy `default_analyse_fn` (the
    whole two-pass) and whose curator `write_fn` is the legacy
    `default_curate_with_enrichment_fn`, so the async supervisor produces the SAME
    `AnalyserExport` as the legacy pod. The `assigner` role + one node is
    transitional; 2b replaces it with the chunk-fed per-responsibility schedule."""
    import asyncio

    from polymerhus.analysis.chunking import Chunk
    from polymerhus.analysis.pod import (
        AnalyserExport, default_analyse_fn, default_curate_with_enrichment_fn,
        default_read_fn,
    )

    read_fn = read_fn or default_read_fn
    analyse_fn = analyse_fn or default_analyse_fn
    curate_fn = curate_fn or default_curate_with_enrichment_fn

    # match the legacy run_analyser's INPUT: whole L0 slice + auto-delivered obs.
    try:
        l0_slice = read_fn(project_id)
    except Exception:  # degrade to an empty slice rather than crash (legacy parity)
        l0_slice = {"nodes": [], "links": []}
    if observations is None:
        from polymerhus.analysis.delivery import deliver_observations
        try:
            observations = deliver_observations(project_id)
        except Exception:
            observations = []

    def _legacy_analyse(dispatch, state) -> L1DeltaBatch:
        return analyse_fn(state.get("l0_slice") or {}, state.get("observations") or [])

    captured: dict = {}

    def _capturing_write(deltas, pid, provenance):
        export = curate_fn(deltas, pid, provenance)
        captured["export"] = export
        return export

    builder = build_supervisor_graph(
        proposer_bodies={"assigner": _legacy_analyse}, write_fn=_capturing_write,
    )
    schedule = [AgentDispatch(
        dispatch_id=run_id, role="assigner", phase="A1", chunk=Chunk(chunk_id=run_id),
    )]
    asyncio.run(run_supervisor(
        project_id, run_id, schedule, builder=builder,
        l0_slice=l0_slice, observations=observations,
        checkpointer=checkpointer, store=store, observe=observe,
    ))
    return captured.get("export") or AnalyserExport()
