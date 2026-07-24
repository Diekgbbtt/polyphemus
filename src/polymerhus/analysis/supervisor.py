"""Increment-0 analyser control plane: the central supervisor + the message
topology, with HOLLOW agents (#22, realising #20 increment 0).

This module is the orchestration logic - the riskiest, least-reversible part of
the analyser redesign - built and tested BEFORE any proposer does real work. The
supervisor holds a `schedule` of `AgentDispatch`es and sequences through them one
super-step at a time; every proposer is a hollow wrapper-node that yields an empty
`ProposalEnvelope`; the auditor annotates nothing; the curator turns the baton into
a `StepReceipt`. The whole thing is BORN ASYNC-NATIVE (async compile + `ainvoke`,
#20 fork-A / T2 D3) so the runtime is the real target runtime from increment 0.

Topology (#17 DP-5/DP-7):
  START -> supervisor
  supervisor --Command(goto=role)--> <one of 5 proposers>   (dynamic routing, ONLY here)
  <proposer> --edge--> auditor --edge--> curator --edge--> supervisor   (STATIC pipeline)
  supervisor --Command(goto=END)--> END                     (schedule exhausted)

State (#17): every field is LAST-WRITE (safe - one logical writer per sequential
super-step) EXCEPT `receipts`, the one reducer channel (dedup-by-dispatch_id = the
state-level mirror of the idempotent MERGE). There is NO proposal-accumulator
channel: the live graph is the accumulator; the supervisor sequences on receipts.
"""
from __future__ import annotations

from typing import Annotated, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from polymerhus.analysis.messages import (
    PROPOSER_ROLES,
    AgentDispatch,
    ProposalEnvelope,
    Role,
    StepReceipt,
    SteeringState,
)

# A proposer BODY is the real per-role work (increment 1+); None = hollow.
# It receives (dispatch, state) and may raise - the wrapper degrades fail-open.
ProposerBody = Callable[[AgentDispatch, dict], None]
# The auditor BODY (increment 3) returns verdicts to annotate; None = hollow.
AuditorBody = Callable[[ProposalEnvelope, dict], list]


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
    reducer channel). No accumulated-proposals channel exists by design (#17)."""

    project_id: str
    run_id: str
    schedule: list[AgentDispatch]      # last-write: the supervisor rewrites the tail
    dispatch: AgentDispatch | None     # last-write: the current work order
    inflight: ProposalEnvelope | None  # last-write: the baton (one writer/super-step)
    receipts: Annotated[list[StepReceipt], merge_receipts]  # the ONLY reducer channel
    steer: SteeringState               # carried, inert in increment 0


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
    """Build a proposer wrapper-node (subgraph-capable per DP-7, so a later
    increment can grow the mechanism-typist react-loop without reshaping the
    topology). HOLLOW default: yields an empty `ProposalEnvelope`. Fail-open: a
    body that raises degrades to `status='degraded'` carrying the error, never
    propagating out of the compiled supervisor."""

    def proposer(state: SupervisorState) -> dict:
        dispatch = state["dispatch"]
        try:
            if body is not None:
                body(dispatch, state)  # increment 1+ real work; hollow default is a no-op
            env = ProposalEnvelope(
                dispatch_id=dispatch.dispatch_id, role=dispatch.role,
                phase=dispatch.phase, status="empty",
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


def _curator(state: SupervisorState) -> dict:
    """Plain node (#17 DP-7): turn the baton into a `StepReceipt` and hand it up.
    The supervisor sequences on this OUTCOME. HOLLOW: nothing is written, so the
    receipt mirrors the envelope's status with zero `WriteCounts`. Increment 2b
    makes the curator write through the sole-writer and derive real counts."""
    env = state.get("inflight")
    if env is None:  # defensive: no baton -> nothing to record
        return {}
    receipt = StepReceipt(
        dispatch_id=env.dispatch_id, role=env.role, phase=env.phase,
        status=env.status, error=env.error,
    )
    return {"receipts": [receipt]}


# --- graph --------------------------------------------------------------------

def build_supervisor_graph(
    *,
    proposer_bodies: dict[str, ProposerBody] | None = None,
    auditor_body: AuditorBody | None = None,
    curator_fn: Callable[[SupervisorState], dict] | None = None,
) -> StateGraph:
    """Build (do NOT compile) the supervisor graph. Injectable seams let tests
    drive the control plane with instrumented / raising stubs:
      - `proposer_bodies[role]` - a per-role work body (hollow when absent);
      - `auditor_body` - the score-and-annotate check (hollow when absent);
      - `curator_fn` - override the whole curator node.
    Static edges wire proposer -> auditor -> curator -> supervisor; the supervisor
    routes out via `Command(goto=...)` alone (DP-5: the both-paths-fire pitfall
    cannot occur)."""
    proposer_bodies = proposer_bodies or {}
    g = StateGraph(SupervisorState)

    g.add_node("supervisor", _supervisor)
    g.add_node("auditor", _make_auditor(auditor_body))
    g.add_node("curator", curator_fn or _curator)
    for role in PROPOSER_ROLES:
        g.add_node(role, _make_proposer(role, proposer_bodies.get(role)))
        g.add_edge(role, "auditor")     # static
    g.add_edge("auditor", "curator")    # static
    g.add_edge("curator", "supervisor")  # static: outcome returns to the supervisor
    g.add_edge(START, "supervisor")
    return g


# --- async-native driver ------------------------------------------------------

def _initial_state(
    project_id: str, run_id: str, schedule: list[AgentDispatch] | None
) -> SupervisorState:
    return {
        "project_id": project_id, "run_id": run_id,
        "schedule": list(schedule or []), "dispatch": None, "inflight": None,
        "receipts": [], "steer": SteeringState(),
    }


async def run_supervisor(
    project_id: str,
    run_id: str,
    schedule: list[AgentDispatch] | None = None,
    *,
    checkpointer=None,
    builder: StateGraph | None = None,
    thread_id: str | None = None,
) -> SupervisorState:
    """Drive the control plane async-native (`ainvoke`). A `checkpointer` is
    injected in tests (`MemorySaver`); in production it is left None and the
    `AsyncPostgresSaver` already set up in the app lifespan (#16) is opened here
    for the run. Returns the terminal `SupervisorState` (its `receipts` trail is
    the observable outcome)."""
    builder = builder or build_supervisor_graph()
    state = _initial_state(project_id, run_id, schedule)
    config = {"configurable": {"thread_id": thread_id or run_id}}

    if checkpointer is not None:
        compiled = builder.compile(checkpointer=checkpointer)
        return await compiled.ainvoke(state, config)

    from polymerhus.app.config import config as app_config
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(app_config.POSTGRES_DSN) as saver:
        compiled = builder.compile(checkpointer=saver)
        return await compiled.ainvoke(state, config)


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


def run_analyser_supervised(project_id: str, run_id: str, observations=None):
    """Sync bridge from `run_analyser` (offloaded via `asyncio.to_thread` by both
    callers, so this worker thread has no running loop) into the born-async
    supervisor, driven with `asyncio.run`.

    Increment 0 is HOLLOW: no schedule is built yet (schedule construction is the
    supervisor's real logic in later increments / the #13 chunk seam), so the run
    sequences an empty schedule, writes nothing, and returns an empty export -
    proving the async runtime is live end to end without any business logic."""
    import asyncio

    from polymerhus.analysis.pod import AnalyserExport

    schedule: list[AgentDispatch] = []  # increment 1+ builds the real schedule
    asyncio.run(run_supervisor(project_id, run_id, schedule))
    return AnalyserExport()
