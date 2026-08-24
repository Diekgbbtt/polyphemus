"""The run-scoped inbox surfer loop and the run dispatch builders (tracker
#173, ADR #169 Q2a/Q3/Q11/Q12/Q15/Q16, spec #169).

The T2/T3 workstreams built the control plane (per-session lifecycle, the
hunting dispatch gate) and the mover (the produced->consumed at-least-once
delivery tick plus the ADR Q13 session scheme). THIS module is the run-scoped
wiring T4 owns:

- A run-scoped SURFER coroutine (`run_surfer_loop`): spawned by the run
  bootstrap (ADR Q2a) as a session on the SHARED runtime manager (session id
  `hunting:<run_id>:surfer` - the Q13 scheme extended by the first free
  segment, the pattern the ADR dictates), tick-drives the mover for the run's
  project, and exits on quiesce or cancellation. The surfer is a dumb mover: it
  only reads the produced inboxes, drives the control plane, and applies the
  moves - every decision stays in the mover's deduction.
- The run DISPATCH builders (`build_run_dispatch`): the T4 `coro_for` seam the
  mover's `run_delivery_tick` was designed for. A produced RATIFIED hunt config
  becomes ONE hunter session (gate-bounded through the shared hunting gate,
  Q15); a produced SPECIFIED test spec becomes ONE pod session (ADR Q13 pod
  session id) riding the SAME mover. An item whose status is not yet
  dispatchable - a hypothesised draft, a dropped config - yields NO coroutine
  (the mover's `None`-means-refused rule): it stays in produced and the next
  tick re-attempts it (at-least-once, never dropped).
- The hunter session's IDLE LOOP (ADR "Agent idle state", spec `Agent idle
  state`): after the hunt's ReAct graph ends, the session enters a simple loop
  over its mailbox - REUSING the existing `run_session_agent` machinery, never
  checkpoint-resume mechanisation. The pod->hunter verdict handling is the ADR
  Q16 STUB: a delivered `PodExport` is consumed and recorded (a freeform note
  on the hunter's memory), nothing more - no re-evaluation, no further dispatch.
  The idle loop ends on a `settle` kind message (the run-terminal path posts it:
  quiesce confirmed, no more pods can deliver) or on session cancellation.
- The quiesce predicate (`is_run_quiesced`) + the pending-work read
  (`run_work_remaining`): the run reaches terminal only when the orchestrator
  session has settled, every dispatched hunter has LEFT its graph phase (no
  more specs can be authored), no produced item is dispatchable, and no pod
  session is live. Idle hunters do NOT block the surfer's quiesce - they are
  the run's only remaining live sessions, settled by the run-terminal
  `settle` message (the ADR "all its component sessions have settled" end).

Session bookkeeping (`RunDispatchState`) is run-local and single-loop: the
bootstrap, the surfer, the hunters, and the pods all execute on the ONE shared
worker loop, so no lock is needed. `hunters_in_graph` is the mid-graph vs
idle-loop distinction the quiesce predicate needs (a hunter whose graph is
still running may yet author a produced spec; an idling one cannot).

This module performs no I/O at import (CODING_STANDARD section 6): the session
seams (`run_session_agent`, `HuntSession`, the checkpointer) resolve lazily on
call, and the pod/hunter builders are injected per run.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.mover import (
    HuntConfigItem,
    ProducedItem,
    TestSpecItem,
    TickReport,
    orchestrator_session_id,
    pod_session_id,
    run_delivery_tick,
)
from polymerhus.app.llm.actor import AgentInbox, AgentMessage, STOP

logger = logging.getLogger(__name__)

# The surfer session's Q13-extension segment (ADR Q13 names orchestrator /
# hunter / pod; the surfer is the run-scoped session that uses the same
# `hunting:<run_id>:<segment>` shape - the first free segment).
SURFER_SESSION_SEGMENT = "surfer"

# The produced->consumed rename is the at-least-once marker (Q3), so the surfer
# ticks forever ONLY while work remains; the pause between laps gives freshly
# dispatched sessions (whose registry entries land asynchronously) time to
# become observable before the next quiesce check.
DEFAULT_SURFER_TICK_INTERVAL = 0.2


def surfer_session_id(run_id: str) -> str:
    """The run-scoped surfer session id (the Q13 scheme, extended by the first
    free segment): `hunting:<run_id>:surfer`."""
    if not run_id:
        raise ValueError("run_id must be a non-empty string")
    return f"hunting:{run_id}:{SURFER_SESSION_SEGMENT}"


def is_run_session_id(session_id: str, run_id: str) -> bool:
    """True when `session_id` belongs to `run_id`'s run: the idle-loop settling
    enumerator of the run's live sessions. Matches every shape a session of the
    run is registered under - the outer bootstrap task (`hunting:<run_id>` and
    the bare `run_id` legacy forms) and every ADR Q13 segment
    (`hunting:<run_id>:orchestrator|surfer|hunt:...|pod:...`)."""
    return (
        session_id == run_id
        or session_id == f"hunting:{run_id}"
        or session_id.startswith(f"hunting:{run_id}:")
    )


def is_hunter_session_id(session_id: str) -> bool:
    """True for a hunter session (`hunting:<run_id>:hunt:<config_id>`)."""
    return ":hunt:" in session_id


def is_pod_session_id(session_id: str) -> bool:
    """True for a pod session (`hunting:<run_id>:pod:<config_id>:<spec_id>`)."""
    return ":pod:" in session_id


@dataclass
class RunDispatchState:
    """The run-local wire state the surfer and the bootstrap share (single
    worker loop - no lock). `hunter_inboxes` maps the dispatched config's
    memory key to the AgentInbox its pod exports are delivered into (built at
    hunter dispatch, before any of its specs can exist); `hunters_in_graph` is
    the set of config keys whose hunter is still running its ReAct graph - the
    mid-graph vs idle-loop distinction the quiesce predicate needs (a
    mid-graph hunter may still author produced specs)."""

    hunter_inboxes: dict[str, AgentInbox] = field(default_factory=dict)
    hunters_in_graph: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class SurferReport:
    """The surfer loop's terminal report: how many delivery laps ran, the last
    `TicketReport`, and why the loop ended. `quiesced` True = the run's work is
    exhausted (the natural terminal); False = the loop was cancelled."""

    ticks: int
    last_tick: "TickReport | None" = None
    quiesced: bool = False


def _read_config_body(hunt_store: HuntStore, project_id: str, key: str) -> dict | None:
    """The produced config's persisted body (fail-open per record - O4)."""
    try:
        records = hunt_store.read_configs_by_key(project_id, key)
    except Exception as exc:  # noqa: BLE001 - fail-open read (O4)
        logger.warning("surfer: config body read failed for %s (%s)", key, exc)
        return None
    return records[0] if records else None


def _read_spec_body(
    hunter_store: HunterMemoryStore,
    project_id: str,
    item: TestSpecItem,
) -> dict | None:
    """The produced spec's persisted body (fail-open per record - O4). The
    `<fault>_<strategy>` stem splits on the single `_` separator (G3 keywords
    never contain `_`), so the classifier can read the file it names."""
    fault_keyword, sep, strategy_keyword = item.spec_file.partition("_")
    if not sep or not fault_keyword or not strategy_keyword:
        return None
    try:
        return hunter_store.read_spec(
            project_id, item.fault_key, fault_keyword, strategy_keyword,
            side="produced",
        )
    except Exception as exc:  # noqa: BLE001 - fail-open read (O4)
        logger.warning("surfer: spec body read failed for %s (%s)", item.spec_file, exc)
        return None


def run_work_remaining(
    project_id: str,
    *,
    hunt_store: HuntStore,
    hunter_store: HunterMemoryStore,
) -> bool:
    """True when a DISPATCHABLE produced item remains: a produced hunt config
    carrying `status == "ratified"` or a produced spec carrying
    `status == "specified"`. A hypothesised draft, a dropped config (G6 stays on
    disk, never dispatchable), or a not-yet-specified spec contributes NOTHING
    - those can never dispatch and must never hold the run's quiesce open. The
    status gate is exactly the one `build_run_dispatch` applies, so the quiesce
    predicate and the dispatch decision can never disagree."""
    for key, _name in hunt_store.read_produced_configs(project_id):
        body = _read_config_body(hunt_store, project_id, key)
        if body and body.get("status") == "ratified":
            return True
    for fault_key in hunter_store.list_fault_keys(project_id):
        for spec_file in hunter_store.produced_spec_files(project_id, fault_key):
            body = _read_spec_body(
                hunter_store, project_id,
                TestSpecItem(
                    message_id=f"{fault_key}/{spec_file}",
                    session_id="",
                    fault_key=fault_key,
                    spec_file=spec_file,
                ),
            )
            if body and body.get("status") == "specified":
                return True
    return False


async def is_run_quiesced(
    project_id: str,
    run_id: str,
    *,
    hunt_store: HuntStore,
    hunter_store: HunterMemoryStore,
    control,
    state: RunDispatchState,
) -> bool:
    """The quiesce predicate: the run's work is exhausted. ALL must hold:

    - the orchestrator session is settled (its registry entry gone - a live
      pass may still author configs);
    - no hunter is still mid-graph (`state.hunters_in_graph`) - a running graph
      may yet write a produced spec after quiesce;
    - no pod session is live - an in-flight pod may still deliver an export;
    - no dispatchable produced item remains.

    Idle hunters deliberately do NOT block this predicate: their graphs have
    ended, they author nothing more, and they settle on the run-terminal
    `settle` message once the surfer proves quiesce."""
    live = {sid for sid in control.live_session_ids() if is_run_session_id(sid, run_id)}
    if orchestrator_session_id(run_id) in live:
        return False
    if any(is_pod_session_id(sid) for sid in live):
        return False
    if state.hunters_in_graph:
        return False
    return not run_work_remaining(
        project_id, hunt_store=hunt_store, hunter_store=hunter_store,
    )


def post_settle(state: RunDispatchState) -> int:
    """The run-terminal settle: post a `settle` message into every hunter
    inbox whose session ended its graph and is now idling. The idle-loop stub
    returns STOP on it, so the session ends and leaves the registry - the
    "all its component sessions have settled" state the run terminal waits
    for. FIFO-fair: every already-delivered pod export was posted before the
    pods settled, and the surfer's quiesce already proved no pod can deliver
    after this point, so nothing is dropped. Returns the number of inboxes
    settled."""
    if state is None:
        return 0
    for inbox in state.hunter_inboxes.values():
        inbox.post_nowait(AgentMessage(kind="settle"))
    return len(state.hunter_inboxes)


def build_run_dispatch(
    *,
    project_id: str,
    run_id: str,
    hunt_store: HuntStore,
    hunter_store: HunterMemoryStore,
    pod_store: Any,
    state: RunDispatchState,
    gate: Any,
    hunter_builder: Callable[..., tuple[Callable[[Any], Awaitable[Any]], Any]],
    pod_builder: Callable[..., Awaitable[dict]],
) -> Callable[[ProducedItem], Any]:
    """Build the mover's `coro_for` seam for ONE run (ADR #169 Q11/Q13, spec
    #169 "The inbox surfer semantics"): the produced family member -> the
    dispatch coroutine the control plane schedules under its Q13 session id.

    - `HuntConfigItem` -> ONE hunter session for the produced config, but ONLY
      when its persisted `status == "ratified"` (the config's ratified state is
      the gate the task text binds): a hypothesised draft or a dropped config
      yields `None` (the mover's refused rule - stays produced, retried next
      tick, never dropped). The hunter's inbox is minted here so a spec the
      hunt authors is always addressable.
    - `TestSpecItem` -> ONE pod session for the produced spec, ONLY when its
      persisted `status == "specified"` (the ratified-spec gate). The pod rides
      the same mover under ADR Q13's pod session id, and its export is
      delivered into the PARENT hunter's inbox (the experiment-log return path,
      ADR Q16(a): the mover surfaces configs and specs; the pod export flows
      into the hunter's mailbox, NOT through a file move).
    - Anything else yields `None` (refused; the mover retries).

    The session coroutines are gate-bounded (Q15): the hunting dispatch gate is
    acquired around each session's active stretch, so the shared width caps
    concurrent hunting work no matter how many configs fan out."""
    def coro_for(item: ProducedItem) -> Any:
        if isinstance(item, HuntConfigItem):
            return _config_dispatch(item)
        if isinstance(item, TestSpecItem):
            return _spec_dispatch(item)
        logger.warning(
            "surfer: no dispatch builder for produced %s (%s); retried",
            item.message_id, type(item).__name__,
        )
        return None

    def _config_dispatch(item: HuntConfigItem) -> Any:
        body = _read_config_body(hunt_store, project_id, item.config_key)
        if not body or body.get("status") != "ratified":
            # hypothesised draft / dropped config: not dispatchable, at-least-once
            return None
        from polymerhus.attack.hunting.hunt_orchestrator import HuntConfig  # noqa: PLC0415
        try:
            config = HuntConfig.model_validate(body)
        except Exception as exc:  # noqa: BLE001 - a malformed body is refused, never dispatched
            logger.warning(
                "surfer: produced config %s not ratifiable (%s); retried",
                item.config_key, exc,
            )
            return None
        inbox = AgentInbox()
        state.hunter_inboxes[item.config_key] = inbox
        state.hunters_in_graph.add(item.config_key)
        return run_hunter_session(
            config=config,
            project_id=project_id,
            run_id=run_id,
            config_key=item.config_key,
            hunt_store=hunt_store,
            hunter_store=hunter_store,
            state=state,
            gate=gate,
            hunter_builder=hunter_builder,
        )

    def _spec_dispatch(item: TestSpecItem) -> Any:
        body = _read_spec_body(hunter_store, project_id, item)
        if not body or body.get("status") != "specified":
            return None
        inbox = state.hunter_inboxes.get(item.fault_key)
        if inbox is None:
            # The parent hunter was never dispatched (or its inbox was reaped):
            # refusing keeps the spec produced - never dropped.
            logger.warning(
                "surfer: no hunter inbox for produced spec %s; retried",
                item.message_id,
            )
            return None
        return run_pod_session(
            spec=body,
            project_id=project_id,
            run_id=run_id,
            fault_key=item.fault_key,
            spec_id=item.spec_file,
            inbox=inbox,
            gate=gate,
            pod_builder=pod_builder,
            pod_store=pod_store,
        )

    return coro_for


async def run_hunter_session(
    *,
    config,
    project_id: str,
    run_id: str,
    config_key: str,
    hunt_store: HuntStore,
    hunter_store: HunterMemoryStore,
    state: RunDispatchState,
    gate: Any,
    hunter_builder: Callable[..., tuple[Callable[[Any], Awaitable[Any]], Any]],
) -> None:
    """ONE hunter session (ADR Q13 hunter id): the build-to-END ReAct graph on
    the hunt's thread, gate-bounded (Q15), then the IDLE LOOP over the run's
    inbox (ADR "Agent idle state", verdict handling stubbed - Q16). The
    dispatch coroutine the mover schedules when a ratified config dispatches."""
    registry: Any = None
    try:
        dispatch_fn, registry = hunter_builder(
            run_id=run_id, project_id=project_id,
            hunt_store=hunt_store, hunter_store=hunter_store,
        )
    except Exception as exc:  # noqa: BLE001 - a failing builder degrades the session
        logger.warning("surfer: hunter builder failed for %s (%s)", config_key, exc)
        state.hunters_in_graph.discard(config_key)
        return
    try:
        if gate is not None:
            async with gate:
                await dispatch_fn(config)
        else:
            await dispatch_fn(config)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - the harness is fail-open; degrade and idle anyway
        logger.warning("surfer: hunt graph degraded for %s (%s)", config_key, exc)
    finally:
        # The graph stretch is over: the hunt authors no more specs, so the
        # quiesce predicate no longer needs to wait on it.
        state.hunters_in_graph.discard(config_key)

    await _run_hunter_idle(
        project_id=project_id, run_id=run_id, config=config,
        config_key=config_key, hunter_store=hunter_store, state=state,
    )
    if registry is not None:
        try:  # noqa: BLE001 - teardown must never raise into the run
            await registry.stop_all()
        except Exception as exc:
            logger.warning("surfer: hunter registry reap failed for %s (%s)", config_key, exc)


async def _run_hunter_idle(
    *,
    project_id: str,
    run_id: str,
    config,
    config_key: str,
    hunter_store: HunterMemoryStore,
    state: RunDispatchState,
) -> None:
    """The hunt's idle stretch (ADR "Agent idle state"): the mailbox loop
    machinery (`run_session_agent`) iteratively reading the hunt's inbox on the
    hunt's own `HuntSession` thread, NOT checkpoint-resume mechanisation. The
    verdict handling is the ADR Q16 STUB - a delivered pod export is consumed
    and recorded, nothing more. The loop ends on the `settle` kind message the
    run-terminal path posts once quiesce is proven, or on session cancellation
    (stop)."""
    inbox = state.hunter_inboxes[config_key]
    from polymerhus.app.llm.actor import run_session_agent  # noqa: PLC0415
    from polymerhus.app.llm.checkpoints import (  # noqa: PLC0415
        get_session_checkpointer,
        module_context,
    )
    from polymerhus.app.llm.session_address import HuntSession  # noqa: PLC0415

    hunt_session = HuntSession(run_id, config.hunt_id)
    try:
        with module_context("hunting"):
            await run_session_agent(
                hunt_session.role_id, hunt_session.thread_id, None,
                checkpointer=get_session_checkpointer(),
                inbox=inbox,
                on_message=_verdict_stub_handler(
                    project_id=project_id, run_id=run_id,
                    fault_key=config_key, hunter_store=hunter_store,
                ),
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - the idle loop degrades, the session ends
        logger.warning("surfer: hunt %s idle loop degraded (%s)", config_key, exc)


def _verdict_stub_handler(*, project_id, run_id, fault_key, hunter_store):
    """The ADR Q16 verdict stub: a delivered `PodExport` is CONSUMED AND
    RECORDED (a freeform note on the hunter's memory), nothing more - no
    re-evaluation, no further dispatch (the verdict-processing workflow is a
    separate future ticket). `settle` ends the loop; every other kind is
    consumed silently (the idle loop keeps listening)."""

    async def _stub(message, last_turn):
        if message.kind == "settle":
            return STOP
        if message.kind == "pod_export":
            _record_pod_export(
                hunter_store=hunter_store, project_id=project_id, run_id=run_id,
                fault_key=fault_key, message=message,
            )
        return None

    return _stub


def _record_pod_export(*, hunter_store, project_id, run_id, fault_key, message) -> None:
    """The stub's RECORD half (consume and record, nothing more): the delivered
    export payload is appended as a freeform note on the hunter's memory under
    the fault's key, stamped with its source session and the stub marker.
    Fail-open (O3): a write failure warns and the export is still considered
    consumed - the run must never wedge on the record."""
    try:
        hunter_store.write_note(
            project_id,
            action="append",
            fault_key=fault_key,
            note_name=str(message.source or "pod-export"),
            kind="freeform",
            body=json.dumps(message.payload or {}, sort_keys=True),
            evidence="consumed by the verdict stub (ADR Q16): no re-evaluation",
            provenance={
                "run_id": run_id,
                "source": message.source,
                "verdict_stub": True,
            },
        )
    except Exception as exc:  # noqa: BLE001 - O3: warn and keep serving
        logger.warning(
            "surfer: verdict-stub record failed for %s/%s (%s)",
            fault_key, message.source, exc,
        )


async def run_pod_session(
    *,
    spec: dict,
    project_id: str,
    run_id: str,
    fault_key: str,
    spec_id: str,
    inbox: AgentInbox,
    gate: Any,
    pod_builder: Callable[..., Awaitable[dict]],
    pod_store: Any,
) -> dict:
    """ONE pod session (ADR Q13 pod id): run the spec through the pod (the
    injected builder; `arun_pod` in production), then DELIVER the completed
    export into the parent hunter's inbox - the experiment-log return path
    (ADR Q16(a)). Gate-bounded through the shared hunting gate (Q15). The
    export is posted with `await` (same-loop put) BEFORE the session settles,
    so the run-terminal `settle` message can never overtake it in the hunter's
    inbox (each exported log is consumed and recorded, never dropped)."""
    async def _run() -> dict:
        try:
            return await pod_builder(
                spec, run_id=run_id, project_id=project_id,
                memory_store=pod_store, spec_id=spec_id,
            )
        except Exception as exc:  # noqa: BLE001 - fail-open: the pod never raises into the run
            logger.warning("surfer: pod %s degraded (%s)", spec_id, exc)
            return {
                "verdict": "unsuccessful",
                "terminal_reason": "surfer-dispatch-degraded",
                "error": str(exc),
            }

    if gate is not None:
        async with gate:
            export = await _run()
    else:
        export = await _run()
    await inbox.post(AgentMessage(
        kind="pod_export",
        payload=export,
        source=pod_session_id(run_id, fault_key, spec_id),
    ))
    return export


async def run_surfer_loop(
    project_id: str,
    run_id: str,
    *,
    hunt_store: HuntStore,
    hunter_store: HunterMemoryStore,
    control,
    coro_for: Callable[[ProducedItem], Any],
    state: RunDispatchState,
    tick_interval: float = DEFAULT_SURFER_TICK_INTERVAL,
) -> SurferReport:
    """The run-scoped inbox surfer loop (ADR Q2a): one delivery lap per tick,
    quiesce check, sleep, repeat - until quiesce or cancellation. The surfer
    owns NO scheduling and NEVER gates admission (Q11/Q15: the control plane
    and the shared gate do); it is the mover's loop runner, nothing more.

    The quiesce check is deferred for a tick that MOVED anything: an admitted
    dispatch lands a produced->consumed move, and its session task registers on
    the loop asynchronously - the next lap re-reads the registry fresh, so a
    just-dispatched session can never slip past a premature quiesce while its
    item's move is still seen. A REFUSED lap (dispatched but nothing moved - a
    not-yet-dispatchable draft, a gate-full refusal) does NOT delay the check:
    the refusal already left the item produced, and `run_work_remaining` is
    what decides whether it is real work.

    The loop is a session on the shared runtime manager (per-session cancel
    works on it, Q12); cancellation (stop) propagates out of the sleep, and the
    session's registry entry drains with the task."""
    ticks = 0
    last_tick = None
    while True:
        last_tick = run_delivery_tick(
            project_id, run_id,
            hunt_store=hunt_store, hunter_store=hunter_store,
            control=control, coro_for=coro_for,
        )
        ticks += 1
        quiesced = (
            last_tick.moved == 0
            and await is_run_quiesced(
                project_id, run_id,
                hunt_store=hunt_store, hunter_store=hunter_store,
                control=control, state=state,
            )
        )
        if quiesced:
            return SurferReport(ticks=ticks, last_tick=last_tick, quiesced=True)
        await asyncio.sleep(tick_interval)


__all__ = [
    "DEFAULT_SURFER_TICK_INTERVAL",
    "RunDispatchState",
    "SurferReport",
    "SURFER_SESSION_SEGMENT",
    "build_run_dispatch",
    "is_hunter_session_id",
    "is_pod_session_id",
    "is_run_quiesced",
    "is_run_session_id",
    "post_settle",
    "run_hunter_session",
    "run_pod_session",
    "run_surfer_loop",
    "run_work_remaining",
    "surfer_session_id",
]