"""The run-scoped inbox surfer loop and the run dispatch builders (tracker
#173, ADR #169 Q2a/Q3/Q11/Q12/Q15/Q16, spec #169; the per-loop dispatch is
T4 #377, S2 8, S1 7.6, S3 8.7/8.9).

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
  moves - every decision stays in the mover's deduction and its sequencing.
- The run DISPATCH builders (`build_run_dispatch`): the `coro_for` seam the
  mover's `run_delivery_tick` was designed for. A produced LOOP FILE becomes ONE
  hunter session under the per-loop id `hunting:<run_id>:hunt:<dispatch_id>`
  (S3 8.9), handed the payload materialised at dispatch time (S2 8.2) - the
  loop dispatch path is live end to end (T6 #379). A produced dispatchable test
  spec becomes ONE pod
  session (ADR Q13 pod session id, S3 8.7) riding the SAME mover. An item that
  is not dispatchable now - a
  `low` loop behind a higher-tier loop or a live higher-tier HUNTER session
  (S2 8.3 - the sequencing reads that role only), a
  stopped role, a draft spec - yields NO coroutine (the mover's
  `None`-means-refused rule): it stays in produced and the next tick
  re-attempts it (at-least-once, never dropped).
- The hunter session's IDLE LOOP (ADR "Agent idle state", spec `Agent idle
  state`): after the hunt's ReAct graph ends, the session enters a simple loop
  over its mailbox - REUSING the existing `run_session_agent` machinery, never
  checkpoint-resume mechanisation. The pod->hunter verdict handling is the ADR
  Q16 STUB (identity-based refactor, 2026-08-25): the DURABLE export record is
  authored at pod completion keyed by the hunt key (the loop's dispatch id),
  and a delivered `PodExport` in the idle loop is a WITHIN-RUN LIVE FEED for the
  future verdict node - consumed only, no re-evaluation, no further dispatch.
  The idle loop ends on a `settle` kind message (the run-terminal path posts it:
  quiesce confirmed, no more pods can deliver) or on session cancellation.
- The quiesce predicate (`is_run_quiesced`) + the pending-work read
  (`run_work_remaining`): the run reaches terminal only when the modeller
  session has settled, every dispatched hunter has LEFT its graph phase (no
  more specs can be authored), no produced item is dispatchable NOW (the
  mover's own produced read through the ONE validity predicate, plus the
  sequencing filter), and no pod session is live. Idle hunters do NOT block the
  surfer's quiesce - they are the run's only remaining live sessions, settled by
  the run-terminal `settle` message (the ADR "all its component sessions have
  settled" end).

Session bookkeeping (`RunDispatchState`) is run-local and single-loop: the
bootstrap, the surfer, the hunters, and the pods all execute on the ONE shared
worker loop, so no lock is needed. `hunters_in_graph` is the mid-graph vs
idle-loop distinction the quiesce predicate needs (a hunter whose graph is
still running may yet author a produced spec; an idling one cannot), and
`loop_likelihoods` is the live-loop half of the low-loop sequencing (S2 8.3).

T4b (#387) retired the config family from this module: there is no
`HuntConfigItem` branch, no ratified-config predicate and no hunt-store read.
The loop file is the dispatch record (S2 8.2: no `HuntConfig`); a hunter is
dispatched per produced loop file and handed the materialised payload.

This module performs no I/O at import (CODING_STANDARD section 6): the session
seams (`run_session_agent`, `HuntSession`, the checkpointer) resolve lazily on
call, and the pod/hunter builders are injected per run.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.hunter_payload import materialise_hunter_payload
from polymerhus.attack.hunting.mover import (
    MODELLER_SESSION_SEGMENT,
    SPEC_DISPATCH_STATUS,
    d4_spec_body,
    loop_refusal_detail,
    produced_spec_body,
    ProducedItem,
    TestSpecItem,
    ThreatLoopItem,
    TickReport,
    pod_session_id,
    log_refusal_once,
    read_produced_inbox,
    run_delivery_tick,
    sequence_dispatch,
    threat_modeller_session_id,
)
from polymerhus.app.llm.actor import AgentInbox, AgentMessage, STOP
from polymerhus.app.llm.provider_failure import ProviderUnavailableError

logger = logging.getLogger(__name__)

# The surfer session's Q13-extension segment (ADR Q13 names the modeller /
# hunter / pod; the surfer is the run-scoped session that uses the same
# `hunting:<run_id>:<segment>` shape - the first free segment).
SURFER_SESSION_SEGMENT = "surfer"

# The agent-sub-module role tag the renamed session segment classifies as
# (#317, S1 4.1). It is the ROLE vocabulary (`app/runtime._AGENT_ROLES_BY_MODULE`
# declares the same key beside `hunter` and `pod`), NOT the session segment: the
# spec's session segment is `threat-modeller` (underscore-free, a session-id
# part) and lives with the Q13 scheme in `mover.py`. The planner-era
# `orchestrator` segment is removed (T10).
THREAT_MODELLER_ROLE = "threat_modeller"

# The produced->consumed rename is the at-least-once marker (Q3), so the surfer
# ticks forever ONLY while work remains; the pause between laps gives freshly
# dispatched sessions (whose registry entries land asynchronously) time to
# become observable before the next quiesce check.
DEFAULT_SURFER_TICK_INTERVAL = 0.2


class _NullGate:
    """A no-op async context manager for an absent gate: a session always has
    something to acquire when the module gate or a role gate resolves to None
    (a fake control plane, or a manager-less mover)."""

    async def __aenter__(self) -> "_NullGate":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


_NULL_GATE = _NullGate()


def _gate_or_null(gate: Any) -> Any:
    return gate if gate is not None else _NULL_GATE


def derive_thread_role(session_id: str) -> str:
    """The agent role a live session id belongs to (#317), derived from the
    segment after `hunting:<run_id>:`:

    - `threat-modeller` -> `THREAT_MODELLER_ROLE` (the modeller pass)
    - `hunt:...` -> `hunter`
    - `pod:...` -> `pod`
    - `surfer`, the outer run bootstrap (`hunting:<run_id>` / the bare run id),
      or any other segment -> `infra` (runtime infrastructure, never an agent
      sub-module)."""
    parts = session_id.split(":", 2)
    if len(parts) < 3:
        return "infra"
    segment = parts[2]
    if segment == MODELLER_SESSION_SEGMENT:
        return THREAT_MODELLER_ROLE
    if segment.startswith("hunt:"):
        return "hunter"
    if segment.startswith("pod:"):
        return "pod"
    return "infra"


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
    (`hunting:<run_id>:threat-modeller|surfer|hunt:...|pod:...`)."""
    return (
        session_id == run_id
        or session_id == f"hunting:{run_id}"
        or session_id.startswith(f"hunting:{run_id}:")
    )


def is_modeller_session_id(session_id: str, run_id: str) -> bool:
    """True for the run's modelling PASS session:
    `hunting:<run_id>:threat-modeller` (S1 4.1). The planner-era
    `hunting:<run_id>:orchestrator` alias is removed (T10)."""
    return session_id == threat_modeller_session_id(run_id)


def is_hunter_session_id(session_id: str) -> bool:
    """True for a hunter session
    (`hunting:<run_id>:hunt:<dispatch_id>`, the loop dispatch id)."""
    return ":hunt:" in session_id


def is_pod_session_id(session_id: str) -> bool:
    """True for a pod session (`hunting:<run_id>:pod:<dispatch_id>:<spec_id>`)."""
    return ":pod:" in session_id


@dataclass
class RunDispatchState:
    """The run-local wire state the surfer and the bootstrap share (single
    worker loop - no lock). `hunter_inboxes` maps the dispatched item's memory
    key (the loop dispatch id) to the AgentInbox its pod exports are delivered
    into (built at hunter dispatch, before any of its specs can exist);
    `hunters_in_graph` is the set
    of those keys whose hunter is still running its ReAct graph - the
    mid-graph vs idle-loop distinction the quiesce predicate needs (a mid-graph
    hunter may still author produced specs). `loop_likelihoods` is the subset
    that came from a LOOP file: the dispatch id -> likelihood map the low-loop
    sequencing reads (S2 8.3 - only an ACTIVE higher-tier hunter holds a low
    loop; an idle one authors nothing more and settles with the run terminal, so
    counting it would deadlock the quiesce). `provider_failure` is the run-local
    typed provider error a dispatched HUNTER or POD session recorded
    (#312/#329): a provider failure is infrastructure, so the surfer surfaces it
    and the run pauses (`interrupted`) instead of quiescing `complete` with zero
    specs and no typed reason."""

    hunter_inboxes: dict[str, AgentInbox] = field(default_factory=dict)
    hunters_in_graph: set[str] = field(default_factory=set)
    loop_likelihoods: dict[str, str] = field(default_factory=dict)
    provider_failure: ProviderUnavailableError | None = None


@dataclass(frozen=True)
class SurferReport:
    """The surfer loop's terminal report: how many delivery laps ran, the last
    `TickReport`, and why the loop ended. `quiesced` True = the run's work is
    exhausted (the natural terminal); False = the loop was cancelled."""

    ticks: int
    last_tick: "TickReport | None" = None
    quiesced: bool = False


def run_work_remaining(
    project_id: str,
    run_id: str,
    *,
    threat_store: Any = None,
    hunter_store: HunterMemoryStore,
    pod_store: Any = None,
    live_loop_likelihoods: Mapping[str, str] | Iterable[str] = (),
) -> bool:
    """True when a DISPATCHABLE-NOW produced item remains for this run.

    The read is the mover's own produced read (`read_produced_inbox`) plus the
    sequencing filter, so the quiesce predicate and the dispatch decision can
    never disagree - they are the same two functions:

    - a produced LOOP file of this run that is dispatchable now (a
      critical/high/medium loop; a `low` loop only when no higher-tier loop file
      is produced and no higher-tier hunter session is live, S2 8.3);
    - a produced COMPLETED valid model with no loop file (the mover consumes it
      on its next tick, S2 8.4) - the model document move IS work;
    - a produced spec carrying the pod family's dispatch status.

    The config family retired in T4b (#387): there is no produced-config clause
    here - a hunt config is not dispatch input at all, so it is not work.

    A malformed or foreign loop file contributes NOTHING (the validity
    predicate refuses it in the read), so it can never wedge the run's quiesce;
    neither can a loop waiting on a live higher-tier session, because that
    session's own loop file is already consumed and its hunter is mid-graph -
    `is_run_quiesced` holds on the mid-graph clause in that window."""
    inbox = read_produced_inbox(
        project_id, run_id, threat_store=threat_store,
        hunter_store=hunter_store, pod_store=pod_store,
    )
    if inbox.models_to_consume:
        # a produced COMPLETED valid model with no dispatchable loop left: the
        # mover consumes it on its next tick (S2 8.4), so the move itself is work
        return True
    return bool(sequence_dispatch(inbox.items, live_loop_likelihoods))


async def is_run_quiesced(
    project_id: str,
    run_id: str,
    *,
    threat_store: Any = None,
    hunter_store: HunterMemoryStore,
    pod_store: Any = None,
    control,
    state: RunDispatchState,
) -> bool:
    """The quiesce predicate: the run's work is exhausted. ALL must hold:

    - the modeller pass session is settled (its registry entry gone - a live
      pass may still write a model and produce loop files);
    - no hunter is still mid-graph (`state.hunters_in_graph`) - a running graph
      may yet write a produced spec after quiesce;
    - no pod session is live - an in-flight pod may still deliver an export;
    - no dispatchable-now produced item remains (the mover's own produced read
      plus the sequencing filter).

    Idle hunters deliberately do NOT block this predicate: their graphs have
    ended, they author nothing more, and they settle on the run-terminal
    `settle` message once the surfer proves quiesce. The low-loop pause is
    therefore consistent with the predicate: a `low` loop held behind an ACTIVE
    higher hunter is covered by the mid-graph clause above, and it is released
    (or dispatched) as soon as that hunter leaves its graph - so the work can
    never leak past quiesce."""
    live = {sid for sid in control.live_session_ids() if is_run_session_id(sid, run_id)}
    # The run's modelling pass, keyed on the `threat-modeller` segment (S1 4.1);
    # the planner-era `orchestrator` alias is removed (T10).
    if any(is_modeller_session_id(sid, run_id) for sid in live):
        return False
    if any(is_pod_session_id(sid) for sid in live):
        return False
    if state.hunters_in_graph:
        return False
    return not run_work_remaining(
        project_id, run_id, threat_store=threat_store,
        hunter_store=hunter_store, pod_store=pod_store,
        live_loop_likelihoods=state.loop_likelihoods,
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
    threat_store: Any = None,
    hunter_store: HunterMemoryStore,
    pod_store: Any,
    state: RunDispatchState,
    gate: Any,
    hunter_builder: Callable[..., tuple[Callable[[Any], Awaitable[Any]], Any]],
    pod_builder: Callable[..., Awaitable[dict]],
    control: Any = None,
) -> Callable[[ProducedItem], Any]:
    """Build the mover's `coro_for` seam for ONE run (ADR #169 Q11/Q13, spec
    #169 "The inbox surfer semantics"): the produced family member -> the
    dispatch coroutine the control plane schedules under its Q13 session id.

    - `ThreatLoopItem` -> ONE hunter session for the produced loop file
      (S2 8.4: the loop file is the dispatch grain). The payload is materialised
      HERE, at dispatch time (S2 8.2), from the unit's model document (read
      produced-first: a model the mover already consumed is still a valid
      context source) plus the loop record the mover read. The hunter's inbox is
      minted under the loop's dispatch id so a spec the hunt authors is
      addressable, and the loop's likelihood is registered on the run state for
      the duration of its graph so a later `low` loop waits behind it (S2 8.3).
      A model that vanished, or a stopped hunter role, yields `None` (the
      mover's refused rule - stays produced, retried next tick, never dropped).
    - `TestSpecItem` -> ONE pod session for the produced spec, ONLY when its
      persisted `status == "ratified"` (the ratified-spec gate). The pod rides
      the same mover under ADR Q13's pod session id. Dispatch is gated by the
      spec's OWN persisted status - NEVER by a chain-adjacent parent's liveness
      (identity-based refactor, 2026-08-25): a produced spec whose hunt key's
      parent was consumed by an earlier run (no live parent inbox this run)
      still dispatches. The parent key IS the spec's folder (the loop dispatch
      id, S3 8.9), the completed export is RECORDED DURABLY at pod completion
      keyed by it (Q16 amendment), and a within-run co-running parent MAY also
      receive a live inbox notification (optional, best-effort - never the only
      record, never a dispatch gate).
    - Anything else yields `None` (refused; the mover retries).

    The session coroutines are gate-bounded (Q15): the hunting dispatch gate is
    acquired around each session's active stretch, so the shared width caps
    concurrent hunting work no matter how many loops fan out.

    #317 role enforcement: the builder consults the target role's agent
    sub-module state via `control.role_running(run_id, role)` - a role that is
    not `RUNNING` makes the builder answer `None` (the mover's refused rule:
    the item stays produced, at-least-once). The role gate
    (`control.role_gate(run_id, role)`) is passed to the session so its active
    stretch is held at the next unit boundary when the role is stopped. With no
    `control` (or a control lacking the reads) the roles are treated as running
    and the role gate is absent - the pre-#317 behaviour."""
    def _role_running(role: str) -> bool:
        if control is None:
            return True
        reader = getattr(control, "role_running", None)
        if reader is None:
            return True
        try:
            return bool(reader(run_id, role))
        except Exception as exc:  # noqa: BLE001 - fail-open: treat the role as up
            logger.warning(
                "surfer: role state read for %s/%s failed (%s); treating as "
                "running (fail-open)", run_id, role, exc,
            )
            return True

    def _role_gate(role: str) -> Any:
        if control is None:
            return None
        reader = getattr(control, "role_gate", None)
        if reader is None:
            return None
        try:
            return reader(run_id, role)
        except Exception as exc:  # noqa: BLE001 - fail-open: no role gate
            logger.warning(
                "surfer: role gate read for %s/%s failed (%s); session runs "
                "ungated (fail-open)", run_id, role, exc,
            )
            return None

    def coro_for(item: ProducedItem) -> Any:
        if isinstance(item, ThreatLoopItem):
            return _loop_dispatch(item)
        if isinstance(item, TestSpecItem):
            return _spec_dispatch(item)
        logger.warning(
            "surfer: no dispatch builder for produced %s (%s); retried",
            item.message_id, type(item).__name__,
        )
        return None

    def _loop_dispatch(item: ThreatLoopItem) -> Any:
        """ONE hunter session for ONE produced loop file (S2 8.4): the payload is
        materialised at dispatch time from the unit's model document and the
        session is keyed by the loop's dispatch id. The run-local registration
        (the inbox, the mid-graph key, the loop's likelihood) lands INSIDE the
        session coroutine, so a coroutine the control plane refuses - which is
        closed without ever running - mutates nothing (T4a review I1)."""
        model = item.model
        if model is None and threat_store is not None:
            # A directly constructed item (or a store that does not carry the
            # document): read it. The produced read already gates every item on a
            # readable model, so this is the belt-and-braces path.
            model = threat_store.read_model(project_id, item.unit_id)
        if model is None:
            # The model is the payload's context (S2 8.1: the loop file does not
            # duplicate it): without it there is nothing to dispatch. The loop
            # file stays produced, is NOT counted as work (the read refuses it
            # too - T4a review F2: an unreadable model must not wedge the run),
            # and the refusal is logged ONCE, never per tick.
            log_refusal_once(
                project_id, run_id, loop_refusal_detail(
                    "loop-model", item.unit_name, item.loop_id),
                "surfer: produced loop %s refused - no readable model for %s; "
                "never dispatched and not counted as work",
                item.message_id, item.unit_id,
            )
            return None
        # #317: a stopped hunter role refuses new hunter dispatch (at-least-once).
        if not _role_running("hunter"):
            return None
        payload = materialise_hunter_payload(
            model, item.record, dispatch_id=item.dispatch_id)
        return run_hunter_session(
            payload=payload,
            project_id=project_id,
            run_id=run_id,
            hunt_key=item.dispatch_id,
            likelihood=item.likelihood,
            hunter_store=hunter_store,
            state=state,
            gate=gate,
            role_gate=_role_gate("hunter"),
            hunter_builder=hunter_builder,
        )

    def _spec_dispatch(item: TestSpecItem) -> Any:
        # The item's body IS the validated one (the produced read's dispatch
        # gate, `SPEC_DISPATCH_STATUS`); the re-read is only the belt-and-braces
        # for a directly constructed item.
        body = item.spec if item.spec is not None else produced_spec_body(
            hunter_store, project_id, item.hunt_key, item.spec_file)
        if not body or body.get("status") != SPEC_DISPATCH_STATUS:
            return None
        # #317: a stopped pod role refuses new pod dispatch (at-least-once).
        if not _role_running("pod"):
            return None
        # The spec's OWN persisted status gates the pod dispatch - NEVER the
        # liveness of a chain-adjacent parent (identity-based refactor,
        # 2026-08-25): a produced `ratified` spec whose parent hunt key was
        # consumed by an earlier run (no live parent inbox in THIS run) still
        # dispatches, so the never-disagree contract holds - run_work_remaining
        # and build_run_dispatch gate on the same own-status and a produced
        # spec can never wedge the quiesce. The parent key IS the loop dispatch
        # id the spec lives under (S3 8.9); no config key is derived.
        inbox = state.hunter_inboxes.get(item.hunt_key)
        return run_pod_session(
            spec=body,
            project_id=project_id,
            run_id=run_id,
            hunt_key=item.hunt_key,
            spec_id=item.spec_file,
            inbox=inbox,
            hunter_store=hunter_store,
            gate=gate,
            role_gate=_role_gate("pod"),
            pod_builder=pod_builder,
            pod_store=pod_store,
            state=state,
        )

    return coro_for


async def run_hunter_session(
    *,
    payload: Mapping[str, Any],
    project_id: str,
    run_id: str,
    hunt_key: str,
    likelihood: str,
    hunter_store: HunterMemoryStore,
    state: RunDispatchState,
    gate: Any,
    hunter_builder: Callable[..., tuple[Callable[[Any], Awaitable[Any]], Any]],
    role_gate: Any = None,
) -> None:
    """ONE hunter session (ADR Q13 hunter id `hunting:<run_id>:hunt:<hunt_key>`,
    S3 8.9): the build-to-END ReAct graph on the hunt's own thread - handed
    the loop PAYLOAD materialised at dispatch time (S2 8.2) and the loop's
    likelihood, never a config - gate-bounded (Q15), then the IDLE LOOP over
    the run's inbox (ADR "Agent idle state", verdict handling stubbed - Q16).
    The dispatch coroutine the mover schedules when a loop file is admitted.

    The payload is the ONLY input: the config bridge retired in T4b (#387).
    T6 (#379) made the production harness consume the loop payload end to end
    (`_default_hunter_builder` hands it straight to `build_hunting_agent`), so
    the per-loop dispatch path is live - never a fabricated config.

    The run state carries the session's loop for the duration of its GRAPH
    stretch: `hunters_in_graph` holds quiesce while the hunt may still author
    specs, and `loop_likelihoods` is what a later `low` loop waits behind
    (S2 8.3). Both are released when the graph ends - an idle hunter authors
    nothing more, so it must not hold the sequencing (or the run terminal's
    settle could never land).

    The registration lands HERE, before the first await (T4a review I1): the
    mover builds this coroutine and the control plane may REFUSE to schedule it
    (gate full, module paused), in which case the coroutine is closed and never
    runs - so the dispatch seam itself must not mutate run state, or the leaked
    key would hold the quiesce and every later low loop for ever."

    #317: the session acquires the MODULE gate (Q15 width bound) AND its OWN
    hunter role gate around the active stretch, so a stopped hunter role holds
    its in-flight threads at the next unit boundary (the module gate dominates
    via the role gate's parent)."""
    state.hunter_inboxes[hunt_key] = AgentInbox()
    state.hunters_in_graph.add(hunt_key)
    # every hunter session now comes from a loop file, so it always carries the
    # loop's tier: a later lower loop waits behind it for the graph stretch
    # (S2 8.3)
    state.loop_likelihoods[hunt_key] = likelihood
    registry: Any = None
    try:
        dispatch_fn, registry = hunter_builder(
            run_id=run_id, project_id=project_id,
            hunter_store=hunter_store,
        )
    except Exception as exc:  # noqa: BLE001 - a failing builder degrades the session
        logger.warning("surfer: hunter builder failed for %s (%s)", hunt_key, exc)
        # Undo the registration whole: a leftover inbox suppresses the run's
        # dispatch-gap line (it reads as "a hunter was dispatched"), and a leftover
        # mid-graph key would hold the quiesce (M-c, T4a review round 2).
        state.hunter_inboxes.pop(hunt_key, None)
        state.hunters_in_graph.discard(hunt_key)
        state.loop_likelihoods.pop(hunt_key, None)
        return
    paused_on_provider_failure = False
    try:
        async with _gate_or_null(gate):
            async with _gate_or_null(role_gate):
                await dispatch_fn(payload)
    except asyncio.CancelledError:
        raise
    except ProviderUnavailableError as exc:
        # #312/#329: a provider failure in the hunt graph is infrastructure, not
        # a hunt degrade - record it on the run-local state so the surfer
        # surfaces it and the run pauses (`interrupted`), rather than idling
        # into a silent `complete` with zero specs and no typed reason (the
        # trial-2 outcome). The registry is still reaped below.
        logger.warning(
            "surfer: hunt %s paused on a provider failure (%s)", hunt_key, exc)
        state.provider_failure = state.provider_failure or exc
        paused_on_provider_failure = True
    except Exception as exc:  # noqa: BLE001 - the harness is fail-open; degrade and idle anyway
        logger.warning("surfer: hunt graph degraded for %s (%s)", hunt_key, exc)
    finally:
        # The graph stretch is over: the hunt authors no more specs, so the
        # quiesce predicate no longer needs to wait on it and a later low loop is
        # no longer held behind it.
        state.hunters_in_graph.discard(hunt_key)
        state.loop_likelihoods.pop(hunt_key, None)

    if not paused_on_provider_failure:
        await _run_hunter_idle(
            project_id=project_id, run_id=run_id, hunt_key=hunt_key,
            hunter_store=hunter_store, state=state,
        )
    if registry is not None:
        try:  # noqa: BLE001 - teardown must never raise into the run
            await registry.stop_all()
        except Exception as exc:
            logger.warning("surfer: hunter registry reap failed for %s (%s)", hunt_key, exc)


async def _run_hunter_idle(
    *,
    project_id: str,
    run_id: str,
    hunt_key: str,
    hunter_store: HunterMemoryStore,
    state: RunDispatchState,
) -> None:
    """The hunt's idle stretch (ADR "Agent idle state"): the mailbox loop
    machinery (`run_session_agent`) iteratively reading the hunt's inbox on the
    hunt's own `HuntSession` thread, NOT checkpoint-resume mechanisation. The
    verdict handling is the ADR Q16 STUB (identity-based refactor, 2026-08-25):
    a delivered pod export is a WITHIN-RUN LIVE FEED for the future verdict
    node, consumed only - the DURABLE parent-keyed record was authored at pod
    completion. The loop ends on the `settle` kind message the run-terminal
    path posts once quiesce is proven, or on session cancellation (stop)."""
    inbox = state.hunter_inboxes[hunt_key]
    from polymerhus.app.llm.actor import run_session_agent  # noqa: PLC0415
    from polymerhus.app.llm.checkpoints import (  # noqa: PLC0415
        get_session_checkpointer,
        module_context,
    )
    from polymerhus.app.llm.session_address import HuntSession  # noqa: PLC0415

    hunt_session = HuntSession(run_id, hunt_key)
    try:
        with module_context("hunting"):
            from polymerhus.app.auth.seams import auth_capable_binding  # noqa: PLC0415

            # The idle-loop turns are hunter turns of the SAME hunt. The unit
            # threat model retires the orchestrator's HuntConfig declaration;
            # the hunter's suite pair carries the loop's class skill, and the
            # idle turn keeps the same role binding as the graph-phase turns.
            binding = auth_capable_binding(hunt_session.role_id)
            await run_session_agent(
                hunt_session.role_id, hunt_session.thread_id, None,
                checkpointer=get_session_checkpointer(),
                inbox=inbox,
                on_message=_verdict_stub_handler(hunt_key=hunt_key),
                extra_tags=[run_id],
                usage_scope=project_id,
                tools=binding.tools,
                middleware=binding.middleware,
                context=binding.context,
            )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - the idle loop degrades, the session ends
        logger.warning("surfer: hunt %s idle loop degraded (%s)", hunt_key, exc)


def _verdict_stub_handler(*, hunt_key):
    """The ADR Q16 verdict stub (identity-based refactor, 2026-08-25): a
    delivered `PodExport` is a WITHIN-RUN LIVE FEED for the future
    verdict-processing node (D67-02/D11/D67-14) - CONSUMED ONLY, nothing more.
    The DURABLE parent-keyed export record was already authored at pod
    completion (`run_pod_session` -> `_record_durable_pod_export`), so the
    idle loop never double-records: it acknowledges the feed and keeps
    listening. `settle` ends the loop; every other kind is consumed silently."""

    async def _stub(message, last_turn):
        if message.kind == "settle":
            return STOP
        if message.kind == "pod_export":
            logger.debug(
                "surfer: hunt %s consumed pod_export live feed from %s "
                "(durable record already at pod completion)",
                hunt_key, message.source,
            )
        return None

    return _stub


def _record_durable_pod_export(*, hunter_store, project_id, run_id, hunt_key,
                               spec_id, source, export) -> None:
    """The DURABLE parent-keyed export record (identity-based refactor,
    2026-08-25 / ADR Q16 amendment, note key pinned by #199): authored
    deterministically at pod completion, keyed by the parent's loop dispatch id
    (`hunt_key`, S3 8.9) - independent of any live parent session, crash-safe,
    never lost to a live-mailbox-only path. The export envelope is recorded as
    a freeform note on the hunter memory (the verdict-stub marker), keyed
    `<hunt_key>:pod-export:<spec_id>` (the parent's loop key + the
    `pod-export:` marker + the derived `<fault>_<strategy>` spec id), with
    ONE current record per (hunt, spec): a re-export UPDATES the same key
    (one TestImplementationSpec yields at most one PodExport), and the first
    export APPENDS (the store's update-on-missing is a denoted miss, never a
    silent drop). The pod session id lives ONLY in `provenance["source"]`,
    never in the key. Fail-open (O3): a write failure warns - the export is
    never re-fabricated or dropped, and the run must never wedge on the
    record."""
    note_name = f"pod-export:{spec_id}"
    key = hunter_store.note_key(hunt_key, note_name)
    try:
        existing = [
            r for r in hunter_store.read_notes(project_id, parent_key=hunt_key)
            if r.get("key") == key
        ]
        hunter_store.write_note(
            project_id,
            action="update" if existing else "append",
            hunt_key=hunt_key,
            note_name=note_name,
            kind="freeform",
            body=json.dumps(export or {}, sort_keys=True),
            evidence="durable pod-completion export record (ADR Q16): no re-evaluation",
            provenance={
                "run_id": run_id,
                "source": source,
                "verdict_stub": True,
            },
        )
    except Exception as exc:  # noqa: BLE001 - O3: warn and keep serving
        logger.warning(
            "surfer: durable pod-export record failed for %s/%s (%s)",
            hunt_key, note_name, exc,
        )


async def run_pod_session(
    *,
    spec: dict,
    project_id: str,
    run_id: str,
    hunt_key: str,
    spec_id: str,
    inbox: AgentInbox | None,
    hunter_store: HunterMemoryStore,
    gate: Any,
    pod_builder: Callable[..., Awaitable[dict]],
    pod_store: Any,
    state: RunDispatchState | None = None,
    role_gate: Any = None,
) -> dict:
    """ONE pod session (ADR Q13 pod id): run the spec through the pod (the
    injected builder; `arun_pod` in production), then record the completed
    export DURABLY at pod completion keyed by the parent's loop dispatch id
    (`hunt_key`, S3 8.9) (identity-based refactor, 2026-08-25 / Q16 amendment -
    crash-safe, independent of any live parent session, never lost to a crash
    between dispatch and an in-memory inbox consumption), and finally deliver
    the completed export to a WITHIN-RUN co-running parent's inbox (an OPTIONAL
    live feed for the future verdict-processing node - best-effort, never the
    only record and never a dispatch gate). Gate-bounded through the shared
    hunting gate (Q15).

    The live feed is posted with `await` (same-loop put) when an inbox is
    present, BEFORE the session settles, so the run-terminal `settle` message
    can never overtake it in the hunter's inbox. A missing inbox (the parent was
    consumed by an earlier run) is not an error - the durable record has already
    landed, so nothing is dropped.

    The stored spec body carries the hunter store's own metadata (`status`, the
    two identity keywords; S3 8.6) beside the D4. The dispatch boundary projects
    it onto the reduced D4 (`d4_spec_body`), so the pod's INIT gate sees the
    spec contract and never the store's bookkeeping; a retired field still
    reaches the gate and rejects (S5 8.4/8.8)."""
    async def _run() -> dict:
        try:
            return await pod_builder(
                d4_spec_body(spec), run_id=run_id, project_id=project_id,
                memory_store=pod_store, spec_id=spec_id,
            )
        except ProviderUnavailableError as exc:
            # #329/#312: a provider failure is infrastructure, not a pod verdict.
            # Do not fabricate a domain export and do not persist one - record it
            # on the run-local state so the surfer surfaces it and the run pauses
            # (`interrupted`) rather than quiescing `complete`.
            if state is not None:
                state.provider_failure = state.provider_failure or exc
            raise
        except Exception as exc:  # noqa: BLE001 - fail-open: the pod never raises into the run
            logger.warning("surfer: pod %s degraded (%s)", spec_id, exc)
            return {
                "verdict": "unsuccessful",
                "terminal_reason": "surfer-dispatch-degraded",
                "error": str(exc),
            }

    async with _gate_or_null(gate):
        async with _gate_or_null(role_gate):
            export = await _run()

    source = pod_session_id(run_id, hunt_key, spec_id)
    # The DURABLE parent-keyed record: authored at pod completion, keyed by the
    # parent's loop dispatch id + the pod-export:<spec_id> marker (#199) - the
    # single crash-safe record, independent of any live parent inbox.
    _record_durable_pod_export(
        hunter_store=hunter_store, project_id=project_id, run_id=run_id,
        hunt_key=hunt_key, spec_id=spec_id, source=source, export=export,
    )
    # The WITHIN-RUN live feed (optional): only when a co-running parent's inbox
    # is live under the parent's hunt key. Best-effort - never a gate.
    if inbox is not None:
        await inbox.post(AgentMessage(
            kind="pod_export",
            payload=export,
            source=source,
        ))
    return export


async def run_surfer_loop(
    project_id: str,
    run_id: str,
    *,
    threat_store: Any = None,
    hunter_store: HunterMemoryStore,
    pod_store: Any = None,
    control,
    coro_for: Callable[[ProducedItem], Any],
    state: RunDispatchState,
    tick_interval: float = DEFAULT_SURFER_TICK_INTERVAL,
) -> SurferReport:
    """The run-scoped inbox surfer loop (ADR Q2a): one delivery lap per tick,
    quiesce check, sleep, repeat - until quiesce or cancellation. The surfer
    owns NO scheduling and NEVER gates admission (Q11/Q15: the control plane
    and the shared gate do); it is the mover's loop runner, nothing more.

    The quiesce check is deferred for a tick that MOVED anything (a produced
    record to consumed/, or a model document): an admitted dispatch lands a
    produced->consumed move, and its session task registers on the loop
    asynchronously - the next lap re-reads the registry fresh, so a
    just-dispatched session can never slip past a premature quiesce while its
    item's move is still seen. A REFUSED lap (dispatched but nothing moved - a
    gate-full refusal, a stopped role, an item waiting on the sequencing) does
    NOT delay the check: the refusal already left the item produced, and
    `run_work_remaining` is what decides whether it is real work.

    The loop is a session on the shared runtime manager (per-session cancel
    works on it, Q12); cancellation (stop) propagates out of the sleep, and the
    session's registry entry drains with the task."""
    ticks = 0
    last_tick = None
    while True:
        last_tick = run_delivery_tick(
            project_id, run_id,
            threat_store=threat_store,
            hunter_store=hunter_store,
            pod_store=pod_store,
            control=control, coro_for=coro_for,
            live_loop_likelihoods=state.loop_likelihoods,
        )
        ticks += 1
        if state.provider_failure is not None:
            # #312/#329: a dispatched hunter or pod hit a provider failure - the
            # run pauses (`interrupted`). Surface the typed error to the run
            # bootstrap so the cause lands on the run row, instead of quiescing
            # `complete` with zero specs and no typed reason.
            raise state.provider_failure
        quiesced = (
            last_tick.moved == 0
            and last_tick.models_consumed == 0
            and await is_run_quiesced(
                project_id, run_id,
                threat_store=threat_store,
                hunter_store=hunter_store,
                pod_store=pod_store,
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
    "THREAT_MODELLER_ROLE",
    "derive_thread_role",
    "is_hunter_session_id",
    "is_modeller_session_id",
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