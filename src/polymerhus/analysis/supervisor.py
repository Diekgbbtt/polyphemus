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

import logging
import time
from datetime import datetime, timezone
from typing import Annotated, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict
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

logger = logging.getLogger(__name__)

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
    to `status='degraded'` carrying the error, never propagating out of the graph.

    A step carrying content reports `written`, not `empty` (#34): the receipt trail
    is what the supervisor sequences on, so a written step misreporting itself as
    empty makes that trail lie."""

    def proposer(state: SupervisorState) -> dict:
        dispatch = state["dispatch"]
        try:
            cargo = body(dispatch, state) if body is not None else None
            deltas = cargo if isinstance(cargo, L1DeltaBatch) else None
            env = ProposalEnvelope(
                dispatch_id=dispatch.dispatch_id, role=dispatch.role,
                phase=dispatch.phase, deltas=deltas,
                status="written" if deltas is not None and _has_content(deltas) else "empty",
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
        # Hollow passthrough (increment 0): zero counts, and NEVER `written`. The
        # envelope's `written` means "carries content" (#34); the receipt's means
        # "the curator wrote it". With no write_fn nothing was written, so mirroring
        # the envelope here would make the receipt claim a write that never happened.
        status = "empty" if env.status == "written" else env.status
        receipt = StepReceipt(
            dispatch_id=env.dispatch_id, role=env.role, phase=env.phase,
            status=status, error=env.error,
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


def _observability_config(config: dict, run_id: str, extra: dict | None = None) -> dict:
    """Attach the #18 Langfuse callbacks + a correct session id to the run config
    (closing the trace-correlation gap: the session id WAS computed but never
    passed as metadata). Empty callbacks are inert."""
    from polymerhus.app.observability import get_langfuse_callbacks

    config = dict(config)
    config["callbacks"] = get_langfuse_callbacks()
    config["metadata"] = {
        "langfuse_session_id": run_id,
        "langfuse_tags": ["analyser", "supervisor"],
        **(extra or {}),
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
    observe_metadata: dict | None = None,
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
        config = _observability_config(config, run_id, observe_metadata)

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


def build_schedule(
    chunks, run_id: str, *, roles: tuple[str, ...] = ("assigner",),
    phase: str = "A1", mode: str = "create",
) -> list[AgentDispatch]:
    """Turn a chunk sequence into the supervisor's ordered work orders (#34 wiring).

    One dispatch per (chunk, role) pair, chunk-major so a chunk is fully processed
    before the next begins. `roles` must name only proposers that actually have
    bodies, so the schedule never dispatches to a hollow node and reports an empty
    step as if it were work. The default stays `("assigner",)` for the callers that
    want assignment alone; the chunk-fed analyser (`analyse_chunked`) passes
    `("assigner", "mechanism_typist")` so the typist types each chunk right after the
    assigner has aggregated it (the data-modeller is still unbuilt).

    `dispatch_id` is a pure function of run + chunk + role, so a replayed run
    produces the same ids and the receipts reducer dedups rather than doubling."""
    return [
        AgentDispatch(
            dispatch_id=f"{run_id}:{chunk.chunk_id}:{role}",
            role=role, phase=phase, mode=mode, chunk=chunk,
        )
        for chunk in chunks
        for role in roles
    ]


class PassResult(BaseModel):
    """One pass's outcome: what it wrote, and what it observed while writing it."""

    model_config = ConfigDict(frozen=True)

    export: object = None
    census: "PassCensus" = None


class PassCensus(BaseModel):
    """What one analyser pass OBSERVED, not merely that it ran (#34 DQ2).

    The guarantee this design makes is at-least-once OBSERVATION of surface (DQ1),
    and every layer beneath this one is fail-open, so a pass that read an empty
    surface, built no chunks, or degraded every dispatch is indistinguishable from
    a healthy one unless it says what it saw. `analysis_drained` is derived from
    these counters, never from the fact that the coroutine returned."""

    model_config = ConfigDict(frozen=True)

    l0_assets_read: int = 0
    chunks_built: int = 0
    dispatches_scheduled: int = 0
    dispatches_entered: int = 0
    aggregates_written: int = 0
    systems_written: int = 0
    data_items_written: int = 0
    terminal: bool = False
    error: str | None = None

    # The pass's own wall-clock window, stamped by the pass around its whole body
    # (#34 AST-DEC-09). This is the ONE authoritative measurement of how long an
    # analyser pass occupies, and it is recorded here - in the value the pass
    # already returns to its caller - rather than reconstructed afterwards from
    # traces. Langfuse was assessed for this role and rejected (see §12 of
    # `docs/design/recon-analysis-decoupling.md`): it is fail-open, optional, and
    # drops span batches exactly under the latency stress a stall produces, so a
    # gate built on it is silently vacuous in precisely the failing case.
    started_at: str = ""
    finished_at: str = ""
    duration_s: float = 0.0


PassResult.model_rebuild()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _window(t0: float, started_at: str) -> dict:
    """The census fields describing a pass's wall-clock window.

    Duration comes from `time.monotonic` (immune to a clock step), the endpoints
    from wall-clock UTC so they can be correlated with `recon_jobs` rows and with
    a Langfuse trace by a human reading both."""
    return {
        "started_at": started_at,
        "finished_at": _utc_now_iso(),
        "duration_s": round(time.monotonic() - t0, 3),
    }


def run_analyser_chunked(
    project_id: str,
    run_id: str,
    *,
    invoke_fn=None,
    typist_invoke_fn=None,
    data_modeller_invoke_fn=None,
    assets_fn=None,
    observations_fn=None,
    inventory_fn=None,
    aggregations_fn=None,
    write_fn=None,
    checkpointer=None,
    store=None,
    observe: bool = True,
):
    """Sync wrapper over `analyse_chunked` for callers that own no event loop.

    Kept so every existing caller and test is unchanged; there is exactly ONE
    implementation, in the coroutine below. A caller already on an event loop (the
    analysis consumer) must await `analyse_chunked` directly - `asyncio.run` cannot
    be called from a running loop."""
    import asyncio

    return asyncio.run(analyse_chunked(
        project_id, run_id, invoke_fn=invoke_fn, typist_invoke_fn=typist_invoke_fn,
        data_modeller_invoke_fn=data_modeller_invoke_fn,
        assets_fn=assets_fn, observations_fn=observations_fn,
        inventory_fn=inventory_fn, aggregations_fn=aggregations_fn,
        write_fn=write_fn, checkpointer=checkpointer, store=store, observe=observe,
    )).export


async def analyse_chunked(
    project_id: str,
    run_id: str,
    *,
    invoke_fn=None,
    typist_invoke_fn=None,
    data_modeller_invoke_fn=None,
    assets_fn=None,
    observations_fn=None,
    inventory_fn=None,
    aggregations_fn=None,
    write_fn=None,
    checkpointer=None,
    store=None,
    observe: bool = True,
    terminal: bool = False,
) -> "PassResult":
    """The CHUNK-FED analyser (#34, completed by #48): read the live L0 surface,
    stream it into chunks, and dispatch one work order per (chunk, role) pair
    through the control plane, writing each step's deltas through the sole-writer.

    The schedule is CHUNK-MAJOR over THREE roles: per chunk, the `assigner` runs
    first and writes AGGREGATES against the Bootstrapper's Services, then the
    `mechanism_typist` (#9) re-reads those aggregations and writes Systems +
    Service->System edges, then the `data_modeller` (#48) re-reads them again and
    writes the DataItems + SURFACES_AT + PRODUCES/CONSUMES + DataRelationships -
    the data plane deliberately runs LAST so its Parameter-to-owning-Service join
    has a live answer (dataplane-A1-decisions.md section 3).

    Every collaborator is injectable; the defaults are the live ones. Fail-open
    throughout: a read, LLM or write failure degrades that step, never the run.
    Returns a `PassResult` carrying the export AND the census of what was observed."""
    from polymerhus.analysis.assigner import default_invoke_fn, make_assigner_body
    from polymerhus.analysis.chunking import admit_for_role, chunks_for_job
    from polymerhus.analysis.data_modeller import make_data_modeller_body
    from polymerhus.analysis.l0_stream import read_l0_assets, read_observations
    from polymerhus.analysis.l1_inventory import read_l1_inventory
    from polymerhus.analysis.l1_read import read_service_aggregations
    from polymerhus.analysis.pod import AnalyserExport

    assets_fn = assets_fn or read_l0_assets
    observations_fn = observations_fn or read_observations
    inventory_fn = inventory_fn or read_l1_inventory
    aggregations_fn = aggregations_fn or read_service_aggregations
    invoke_fn = invoke_fn or default_invoke_fn()
    write_fn = write_fn or _chunked_write_fn

    # Stamped around the WHOLE body, including the reads: a pass that spends its
    # time in Neo4j rather than in the provider is still a pass that occupied the
    # analyser, and the stall predicate must not be blind to it.
    _t0 = time.monotonic()
    _started_at = _utc_now_iso()

    assets = assets_fn(project_id)
    observations = observations_fn(project_id)
    # A pseudo-job: the chunk builder keys `chunk_id` off the source job, and this
    # read is the cumulative surface rather than one tool's output.
    from polymerhus.recon.domain.types import JobSpec
    pseudo_job = JobSpec(tool=f"stream-{run_id}", skill="analysis",
                         command_template="", produces=[], consumes="BaseURL")
    chunks = chunks_for_job(pseudo_job, assets, observations)
    if not chunks:
        # Valid empty: nothing to judge. Recorded as observed, so a drain over an
        # empty surface is distinguishable from a drain that never read anything.
        return PassResult(
            export=AnalyserExport(),
            census=PassCensus(l0_assets_read=len(assets), terminal=terminal,
                              **_window(_t0, _started_at)),
        )

    totals = {"aggregates": 0, "systems": 0, "data_items": 0}

    def _counting_write(deltas, pid, provenance):
        export = write_fn(deltas, pid, provenance)
        totals["aggregates"] += getattr(export, "aggregates_written", 0) or 0
        totals["systems"] += getattr(export, "systems_written", 0) or 0
        enrichment = getattr(export, "enrichment", None) or {}
        totals["data_items"] += enrichment.get("data_items", 0) or 0
        return export

    entered = {"n": 0}
    from functools import partial

    from polymerhus.analysis.mechanism_typist import mechanism_typist_body
    assigner_inner = make_assigner_body(invoke_fn=invoke_fn, inventory_fn=inventory_fn)

    def _counted(inner):
        # Counted HERE rather than from the schedule: a dispatch that was scheduled
        # but never entered (the graph terminated early, the step degraded before
        # the body) is exactly the case the census exists to expose.
        def body(dispatch, state):
            entered["n"] += 1
            return inner(dispatch, state)
        return body

    # Chunk-major THREE-role schedule: assigner -> mechanism_typist -> data_modeller
    # per chunk, so each later role re-reads the aggregations the assigner just
    # wrote. The three roles take DIFFERENT LLM seams - the assigner's
    # `invoke_fn(messages) -> batch`, the typist's/data_modeller's
    # `invoke_fn(messages, *, schema) -> prose | batch` - so they cannot share one
    # injected callable; `typist_invoke_fn`/`data_modeller_invoke_fn` are their own
    # seams, defaulting (None) to each role's live `_default_invoke_fn`. Every read
    # inside a body is guarded, so it is fail-open regardless.
    typist_inner = partial(mechanism_typist_body, invoke_fn=typist_invoke_fn)
    data_modeller_inner = make_data_modeller_body(
        invoke_fn=data_modeller_invoke_fn, inventory_fn=inventory_fn, aggregations_fn=aggregations_fn,
    )
    proposer_bodies = {
        "assigner": _counted(assigner_inner),
        "mechanism_typist": _counted(typist_inner),
        "data_modeller": _counted(data_modeller_inner),
    }
    builder = build_supervisor_graph(proposer_bodies=proposer_bodies, write_fn=_counting_write)
    schedule = build_schedule(chunks, run_id, roles=("assigner", "mechanism_typist", "data_modeller"))
    await (run_supervisor(
        project_id, run_id, schedule, builder=builder,
        checkpointer=checkpointer, store=store, observe=observe,
        # The chunk shape IS the diagnosis when a step writes nothing, so it rides
        # the trace rather than living only in the container log.
        observe_metadata={
            "chunks": len(chunks),
            "dispatches": len(schedule),
            "l0_assets": len(assets),
            "admitted_endpoints": sum(len(admit_for_role(c, "assigner")) for c in chunks),
            "admitted_parameters": sum(
                sum(1 for a in admit_for_role(c, "data_modeller") if a.type == "Parameter") for c in chunks
            ),
            "admitted_headers": sum(
                sum(1 for a in admit_for_role(c, "data_modeller") if a.type == "Header") for c in chunks
            ),
            "terminal": terminal,
            "langfuse_tags": [
                "analyser", "supervisor", "assigner", "mechanism_typist", "data_modeller",
                "analyse-data-plane", "chunked",
            ],
            # Join recon and analysis onto ONE Langfuse timeline. The analyser id is
            # `stream-<recon run_id>` (stable, so repeated passes MERGE), but the
            # SESSION must be the bare recon run: otherwise the two modules trace
            # into two sessions that share no key, and no human can see an analyser
            # pass sitting between two recon jobs. Overrides the default set by
            # `_observability_config`, which keys off the analyser id.
            "langfuse_session_id": run_id.removeprefix("stream-"),
            "recon_run_id": run_id.removeprefix("stream-"),
        },
    ))
    census = PassCensus(
        l0_assets_read=len(assets), chunks_built=len(chunks),
        dispatches_scheduled=len(schedule), dispatches_entered=entered["n"],
        aggregates_written=totals["aggregates"], systems_written=totals["systems"],
        data_items_written=totals["data_items"],
        terminal=terminal, **_window(_t0, _started_at),
    )
    logger.info(
        "analyser chunked run=%s terminal=%s chunks=%d scheduled=%d entered=%d "
        "l0_assets=%d aggregates_written=%d systems_written=%d data_items_written=%d duration_s=%.1f",
        run_id, terminal, census.chunks_built, census.dispatches_scheduled,
        census.dispatches_entered, census.l0_assets_read, census.aggregates_written,
        census.systems_written, census.data_items_written, census.duration_s,
    )
    return PassResult(
        export=AnalyserExport(aggregates_written=totals["aggregates"],
                              systems_written=totals["systems"]),
        census=census,
    )


def _aggregates_write_fn(deltas: L1DeltaBatch, project_id: str, provenance: Provenance):
    """The Assigner's curator collaborator: write AGGREGATES and nothing else.

    The Assigner emits an aggregates-only batch by construction (#34 D4), so this
    deliberately does NOT call `l1_curate` - a writer that could create Services
    would quietly restore the minting path the ticket removed."""
    from polymerhus.analysis import l1_curator
    from polymerhus.analysis.analyser_types import proposals_to_deltas
    from polymerhus.analysis.pod import AnalyserExport

    _, _, aggregates = proposals_to_deltas(deltas, provenance)
    return AnalyserExport(aggregates_written=l1_curator.write_aggregates(aggregates, project_id))


def _chunked_write_fn(deltas: L1DeltaBatch, project_id: str, provenance: Provenance):
    """Curator collaborator for the three-role chunk-fed run: route by delta content.

    The Assigner emits an aggregates-only batch (#34), written by the no-mint
    `_aggregates_write_fn` so it can never restore the Service-minting path. The
    mechanism-typist (#9) emits a systems + Service->System-edges batch, and the
    data_modeller (#48) emits a data_items/surfaces_at/data_flows/data_relationships
    batch; BOTH are written through the full sole-writer curate
    (`default_curate_with_enrichment_fn`). One curator node carries one `write_fn`,
    so this dispatches on the batch shape - the three roles' batches are disjoint
    by construction, so the routing is unambiguous.

    DPL-DEC-21 (#48): the ORIGINAL condition here was `if deltas.systems or
    deltas.system_edges`, which routed a data-only batch (neither systems nor
    system_edges, but non-empty data_items/surfaces_at/data_flows/
    data_relationships) to `_aggregates_write_fn` - which does NOT call
    `l1_curate`/`enrich` at all, so the data-only batch was SILENTLY DROPPED with
    a `written` receipt. Widened to cover any non-empty data list; the minimal
    correct fix reuses the existing writer rather than adding one, since
    `default_curate_with_enrichment_fn`'s `proposals_to_deltas` half is already a
    no-op for empty `services`/`systems`."""
    if (deltas.systems or deltas.system_edges or deltas.data_items or deltas.surfaces_at
            or deltas.data_flows or deltas.data_relationships):
        from polymerhus.analysis.pod import default_curate_with_enrichment_fn
        return default_curate_with_enrichment_fn(deltas, project_id, provenance)
    return _aggregates_write_fn(deltas, project_id, provenance)


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
