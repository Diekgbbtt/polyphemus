"""The threat modeller: the five-gate reasoning pass over one L1 unit (S1 4-6, 9).

The hunt-orchestrator planner was rewritten in place into the **threat modeller**
(S1 2.1): for each admitted L1 unit it builds a formal trust model and publishes
a ranked set of loops, one gate write at a time, into the per-project
`ThreatModelStore` (T1, `threat_model_store.py`).

The machine is an extended finite state machine of five states, whose gates are
gate writes (S1 6.1):

    UNIT_TECHNICAL_SHARP      technical_sharpening
    TRUST_MODELLED            trust_model
    TRUST_ASSUMPTIONS_WRITTEN assumptions
    VULNERABILITIES_WRITTEN   vulnerabilities
    COMPLETED                 failure_modes, loops

Three rules govern the harness side:

- **Passive tracking.** The harness never gates a tool call on the current state
  and never rejects a transition. `TrackingThreatModelStore` observes every gate
  write (state, sections, advance/backward) and the pass reads the observed
  state - a forward jump is accepted and its skipped states ride the trail.
- **Prompt-level cadence.** The pass asks for the states in workflow order
  (`STATE_INSTRUCTIONS`); the cadence is a prompt instruction, never a gate.
- **No fabricated result.** An absent write means an absent artifact: the pass
  never mints a section, and a unit that does not reach `COMPLETED` returns a
  degraded outcome instead of a partial-completed one.

The completion validation call (S1 6.6) runs at the end of the pass: the store
computes the model's `validation` on the COMPLETED write, the pass reads it,
and an invalid model is archived to `abandoned/` and reported degraded - the
checker is non-blocking and never rejects a write.

The tool surface (S1 5) is built by
`threat_modeller_tools.build_modeller_tool_surface` over the seams in
`threat_modeller_tools.ModellerTools`: `hunts_store` (the threat-model
read/write), `notes` (the shared notes tool with the bound
`<unit_name>:<note_name>` key), the HTTP-history read pair, the Kali `exec`
probe, and the web-vulnerability suite pair (`skill_list` / `skill_load`). The
auth store and the project skill arrive through the role's `load_skill` binding
(the recon-orchestrator coupling). Deliberately NOT bound: `graph_view` (the
unit projection and the L1 application-surface overview reach the turn through
the pass's context seam - the projection read is live as of T2b, while the
application-surface overview entity has not landed yet and renders as a
recorded gap), `kb_query`, the withdrawn fault-KB aid, and any
back-edge-to-recon tool.

This module imports no driver and performs no I/O at import (CODING_STANDARD 6).
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .threat_model import GATE_SECTIONS, ModelState

if TYPE_CHECKING:  # the actor and the tool layer are lazy imports (C_STD 6)
    from polymerhus.attack.hunting.actors import ThreatModellerActor

    from .threat_modeller_tools import ModellerTools

logger = logging.getLogger(__name__)

# The role identity (S1 4.1, impact-map section 6): the actor/session role and
# the LLM role id are ONE string; the provider env var is its uppercase form.
# The SESSION segment (`threat-modeller`) and its legacy alias live with the Q13
# scheme in `mover.py`, and the agent-sub-module role tag (`threat_modeller`, the
# runtime's per-role gate key) in `surfer.py`/`app/runtime.py`: three distinct
# vocabularies the rename keeps aligned.
MODELLER_ROLE = "hunting_threat_modeller"
MODELLER_MODEL_KEY = "LLM_HUNTING_THREAT_MODELLER"
MODELLER_MODEL_KEY_LEGACY = "LLM_HUNTING_ORCHESTRATOR"

# The tool surface (S1 5): exactly these, nothing more. `graph_view` is not
# bound: the unit projection read is live (T2b, `build_grounding_provider`) and
# the L1 application-surface overview arrives through the same context seam once
# its entity lands (R2-15, still a recorded gap), so neither is a tool. The
# testing-methodology KB stays with the hunters and the pod, and the fault-KB
# aid tool is withdrawn - fault hypothesisation is trust-model driven, never
# copied from an outside repository.
TOOL_SURFACE: tuple[str, ...] = (
    "hunts_store", "notes", "search_http_history", "get_http_artifact", "exec",
    "skill_list", "skill_load",
)

# The gate hints (S1 9.3): module constants injected in the gate write's tool
# response, one per gate, none for the last. The harness stays passive - the
# hint only tells the model what the next state expects.
GATE_HINTS: dict[ModelState, str] = {
    ModelState.UNIT_TECHNICAL_SHARP: (
        "Proceed to trust mapping: translate the interface agreements into "
        "trust agreements over data attributes, application contexts, and "
        "principal privileges, then model dynamic-state trust (states, "
        "transitions, trust-transition violations, TOCTOU, multi-step "
        "business-logic bypass, forced state transitions). Write both branches' "
        "outcomes with a hunts_store write for state TRUST_MODELLED."
    ),
    ModelState.TRUST_MODELLED: (
        "Proceed to assumptions: continue both perspectives and write the "
        "assumptions that bend the trust agreements; each assumption names a "
        "technical programming fault a developer could have made. Write them "
        "with a hunts_store write for state TRUST_ASSUMPTIONS_WRITTEN."
    ),
    ModelState.TRUST_ASSUMPTIONS_WRITTEN: (
        "Proceed to vulnerability citation: for each programming fault name the "
        "web vulnerability classes freely from the canonical taxonomy first, "
        "then map each named class to the suite class that covers it. Write them "
        "with a hunts_store write for state VULNERABILITIES_WRITTEN."
    ),
    ModelState.VULNERABILITIES_WRITTEN: (
        "Proceed to failure-mode deduction and the ranked loops: map each "
        "not-dropped vulnerability back to one or more runtime failure modes, "
        "apply the retention-first drop rule, rank the surviving loops by "
        "likelihood and write them with a hunts_store write for state COMPLETED."
    ),
}

# The per-state cadence instruction (S1 8: the cadence is prompt-level only).
# The stable method lives in the system prompt (`prompts/threat-modeller.md`);
# these are the per-turn pointers the pass hands the model.
STATE_INSTRUCTIONS: dict[ModelState, str] = {
    ModelState.UNIT_TECHNICAL_SHARP: (
        "Ground the unit: the projection (the service contract or the system "
        "technical description, the linked endpoints and services-systems), the "
        "application-surface overview, and the HTTP-history records. Probe the "
        "live target iteratively to reverse-engineer the mechanics. Then define "
        "the technical interface agreements, the control flows, and the data "
        "flows, each with its confidence degree and evidence entries, and write "
        "the technical_sharpening section."
    ),
    ModelState.TRUST_MODELLED: (
        "Run the two trust-mapping branches sequentially: translate every "
        "interface agreement into a trust agreement over the data attributes, "
        "application contexts, and principal privileges; then model "
        "dynamic-state trust from the application-states-flow perspective. "
        "Write the trust_model section."
    ),
    ModelState.TRUST_ASSUMPTIONS_WRITTEN: (
        "Continue both perspectives and write the assumptions that bend the "
        "trust agreements. Each assumption is induced from or to one technical "
        "programming fault (with its label and description), and names the trust "
        "agreement it bends. Write the assumptions section."
    ),
    ModelState.VULNERABILITIES_WRITTEN: (
        "Switch to the abduction world: for each programming fault, name the web "
        "vulnerability classes freely from the canonical taxonomy first, then "
        "map each named class onto the suite class that covers it (skill_list "
        "and skill_load). Where no suite class covers a name, keep the canonical "
        "name, leave web_vulnerability_class empty, and set suite_gap. Write the "
        "vulnerabilities section."
    ),
    ModelState.COMPLETED: (
        "Deduce the failure modes: map each not-dropped vulnerability back to "
        "one or more runtime execution failure modes grounded in the technical "
        "sharpening. Apply the retention-first drop rule, score each feasible "
        "loop's likelihood from the four risk factors, and write ONLY the "
        "failure_modes and loops sections. The store computes the risk profile "
        "and runs the completion checker after your write."
    ),
}

# The last gate carries no hint: the model is published (S1 9.3).
LAST_GATE = ModelState.COMPLETED

# --- the consecutive-degradation circuit breaker (#280 Part 2) ----------------
#
# Kept from the planner pass: when the phase turns keep producing no gate write
# - a poisoned thread, or a sustained provider outage - the pass must not grind
# on. The breaker counts CONSECUTIVE no-decision outcomes (reset on any real
# gate write), applies a bounded exponential backoff once a small threshold is
# crossed, and aborts the pass with a typed, operator-visible failure after K.
# All four knobs are env-backed with sane defaults.

_DEFAULT_DEGRADED_WARN_STREAK = 2
_DEFAULT_DEGRADED_ABORT_STREAK = 5
_DEFAULT_DEGRADED_BACKOFF_BASE_S = 1.0
_DEFAULT_DEGRADED_BACKOFF_MAX_S = 30.0


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or "")
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, "") or "")
        return value if value >= 0 else default
    except (TypeError, ValueError):
        return default


class ThreatModellerDegradedError(RuntimeError):
    """The pass ABORTED after a run of consecutive no-decision turns.

    Typed and operator-visible: it is raised out of `arun_modeller_pass`, so the
    runtime logs it and lands the run failed (or, for a provider-caused abort,
    the resumable `interrupted` - a throttle is infrastructure, not a domain
    result; S1 4.4 `provider_cause`)."""

    def __init__(self, *, state: str, streak: int, threshold: int,
                 provider_cause: bool = False, provider_error=None) -> None:
        self.state = state
        self.streak = streak
        self.threshold = threshold
        self.provider_cause = provider_cause
        self.provider_error = provider_error
        super().__init__(
            f"threat modeller pass aborted: {streak} consecutive no-decision "
            f"turn(s) (last state {state!r}, abort threshold {threshold}"
            f"{', provider-caused' if provider_cause else ''})"
        )


class DegradedTurnBreaker:
    """The pass-scoped counter + backoff + abort for no-decision turns.

    `before_turn` sleeps the current backoff (0 until the warn threshold is
    crossed); `record_outcome` resets on a real gate write, counts a `None`
    outcome, and raises `ThreatModellerDegradedError` at the abort threshold.
    `abort_streak <= 0` disables the abort (the backoff still applies)."""

    def __init__(self, *, backoff_base_s: float, backoff_max_s: float,
                 warn_streak: int, abort_streak: int, sleep=None) -> None:
        self._base = backoff_base_s
        self._max = backoff_max_s
        self._warn = warn_streak
        self._abort = abort_streak
        self._sleep = sleep or asyncio.sleep
        self.streak = 0

    @classmethod
    def from_env(cls) -> "DegradedTurnBreaker":
        return cls(
            backoff_base_s=_env_float("HUNT_TURN_DEGRADED_BACKOFF_BASE_S",
                                      _DEFAULT_DEGRADED_BACKOFF_BASE_S),
            backoff_max_s=_env_float("HUNT_TURN_DEGRADED_BACKOFF_MAX_S",
                                     _DEFAULT_DEGRADED_BACKOFF_MAX_S),
            warn_streak=_env_int("HUNT_TURN_DEGRADED_STREAK_WARN",
                                 _DEFAULT_DEGRADED_WARN_STREAK),
            abort_streak=_env_int("HUNT_TURN_DEGRADED_STREAK_ABORT",
                                  _DEFAULT_DEGRADED_ABORT_STREAK),
        )

    def delay_for(self, streak: int) -> float:
        if streak < self._warn or self._base <= 0:
            return 0.0
        return min(self._base * (2 ** (streak - self._warn)), self._max)

    async def before_turn(self, state: str) -> None:
        delay = self.delay_for(self.streak)
        if delay > 0:
            logger.warning(
                "threat modeller degraded: %d consecutive no-decision turn(s); "
                "backing off %.2fs before the %s turn", self.streak, delay, state)
            await self._sleep(delay)

    def record_outcome(self, state: str, outcome: Any, *,
                       cause: BaseException | None = None) -> None:
        if outcome is not None:
            self.streak = 0
            return
        self.streak += 1
        if self._abort > 0 and self.streak >= self._abort:
            provider_error = None
            if cause is not None:
                from polymerhus.app.llm.provider_failure import (  # noqa: PLC0415
                    as_provider_error,
                )

                provider_error = as_provider_error(cause)
            raise ThreatModellerDegradedError(
                state=state, streak=self.streak, threshold=self._abort,
                provider_cause=provider_error is not None,
                provider_error=provider_error)


# --- the passive gate tracker (S1 6.1) ----------------------------------------

class TrailEntry(BaseModel):
    """One typed tracker trail entry (S1 6.1: a trajectory entry records the
    unit, the signal, the from-state, the to-state, the outcome, and the time).

    `kind` is `gate` (a forward write, with the states it skipped), `lower_gate`
    (a write behind the tracked state - content only) or `seeded` (the resumed
    state a pass started from)."""

    kind: Literal["gate", "lower_gate", "seeded"]
    state: str
    previous_state: str | None = None
    tracked: str | None = None
    skipped: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    at: datetime


class GateWrite(BaseModel):
    """One observed gate write: the state the model asked for, the sections it
    carried, when it landed, and whether it advanced the tracked state."""

    state: ModelState
    sections: tuple[str, ...]
    observed_at: datetime
    advanced: bool


class PassiveGateTracker:
    """The harness's passive reading of the gate writes (S1 6.1).

    It records every observed write, holds the monotonic tracked state (the
    highest gate written), and keeps the trail of backward writes. It never
    rejects a transition and never gates a tool call: a write for a lower gate
    is a trail entry, not an error.
    """

    def __init__(self) -> None:
        self.writes: list[GateWrite] = []
        self.trail: list[TrailEntry] = []
        self.state: ModelState | None = None

    def reset(self) -> None:
        """Clear the observation for a NEW unit's pass.

        ONE tracker is run-scoped (the actor captures its tools once), so a pass
        starts from a clean reading; the run's accumulated writes stay readable
        only until the next unit's pass resets them (the run driver owns the
        cross-unit history)."""
        self.writes = []
        self.trail = []
        self.state = None

    def seed(self, state: ModelState | None) -> None:
        """Seed the tracked state from the PERSISTED model (a resume, or a
        replayed unit). A seeded state at or ahead of a state the pass would ask
        for makes the pass skip it, so a resume never re-authors a gate that is
        already written, and a COMPLETED model's sections are never regressed."""
        self.state = state
        if state is not None:
            # only a REAL resume rides the trail; a fresh unit has nothing to
            # seed and nothing to report
            self.trail.append(TrailEntry(
                kind="seeded", state=state.value,
                at=datetime.now(timezone.utc)))

    def observe(self, state: ModelState, sections: Mapping[str, Any]) -> GateWrite:
        """Record one gate write. `advanced` is True only when this write moved
        the tracked state FORWARD (a lower-gate write updates content and the
        trail, never the state)."""
        from .threat_model import STATE_ORDER  # noqa: PLC0415 - one home for the order

        previous = self.state
        rank = STATE_ORDER[state]
        current = STATE_ORDER[previous] if previous is not None else -1
        advanced = rank > current
        write = GateWrite(
            state=state,
            sections=tuple(sections),
            observed_at=datetime.now(timezone.utc),
            advanced=advanced,
        )
        self.writes.append(write)
        if advanced:
            # the states between the previous and the written one, ordered by
            # their OWN rank - never by the enum's declaration order
            skipped = [
                member.value for member in sorted(
                    (m for m in ModelState if current < STATE_ORDER[m] < rank),
                    key=STATE_ORDER.__getitem__)
            ]
            self.state = state
            self.trail.append(TrailEntry(
                kind="gate", state=state.value,
                previous_state=previous.value if previous is not None else None,
                skipped=skipped, sections=list(sections),
                at=write.observed_at))
        else:
            self.trail.append(TrailEntry(
                kind="lower_gate", state=state.value,
                tracked=self.state.value if self.state is not None else None,
                sections=list(sections), at=write.observed_at))
        return write

    def write_states(self) -> list[str]:
        return [write.state.value for write in self.writes]


class TrackingThreatModelStore:
    """The observing store seam the pass hands the tools (S1 6.1).

    Every other call proxies to the real store; `write_sections` is observed by
    the tracker and then delegated. The wrapper NEVER gates: it does not read
    the tracked state to refuse a write, and it does not translate a store error
    (the store's own coded rejections stay the tool's contract)."""

    def __init__(self, inner, tracker: PassiveGateTracker) -> None:
        self._inner = inner
        self._tracker = tracker

    @property
    def tracker(self) -> PassiveGateTracker:
        return self._tracker

    def write_sections(self, project_id: str, unit_id: str, state, sections,
                       *, run_id: str):
        try:
            gate = ModelState(state)
        except ValueError:
            # A malformed state is the store's coded rejection to make; observe
            # nothing so the tracker never claims a write that did not land.
            return self._inner.write_sections(project_id, unit_id, state, sections,
                                              run_id=run_id)
        path = self._inner.write_sections(project_id, unit_id, gate, sections,
                                         run_id=run_id)
        if is_consumed_path(path):
            # the move-aware no-op write (S2 4.5): the identity is decided, the
            # store re-created nothing, so the tracker must not claim a write
            return path
        self._tracker.observe(gate, sections)
        return path

    def __getattr__(self, name):
        return getattr(self._inner, name)


def is_consumed_path(path: Any) -> bool:
    """True when a store write landed as the move-aware no-op (S2 4.5): the
    identity already lives in `consumed/`, so the returned path sits under that
    family and no produced copy was written."""
    try:
        return Path(path).parent.parent.name == "consumed"
    except Exception:  # noqa: BLE001 - an unreadable path is never a no-op claim
        return False


@dataclass
class ModellerUnit:
    """The harness-held unit identity the tools read at CALL time.

    The per-run actor captures its tool surface once (the stable-seam pattern
    the planner pass established, #294), so the per-unit identity cannot be
    frozen at the actor's first construction: the pass retargets this cell at
    every unit. A surface built without a cell (a scripted seam, a direct tool
    build) keeps the identity bound at construction."""

    project_id: str = ""
    run_id: str = ""
    unit_id: str = ""

    def retarget(self, *, project_id: str, run_id: str, unit_id: str) -> None:
        self.project_id = project_id
        self.run_id = run_id
        self.unit_id = unit_id


# --- the pass (S1 6) ----------------------------------------------------------

class ModellerTurnInput(BaseModel):
    """One reasoning turn's input (S1 8: the per-turn HumanMessage carries the
    current unit, the current state, the input data, and the gate instruction).

    `model` is the persisted model as read at the turn's start (a fresh read, so
    an evicted context is re-queried - S1 6.2); `tools` carries the bound tool
    surface for a scripted turn seam and is never serialised to the model (the
    real actor binds the same tools on its session)."""

    unit_id: str
    state: ModelState
    sections: tuple[str, ...]
    instruction: str
    model: dict | None = None
    # The grounding inputs (S1 4.6, 5.6) and the gaps where one is absent; the
    # composed turn renders both (llm._compose_modeller_prompt).
    projection: Any = None
    surface_overview: Any = None
    context_gaps: tuple[str, ...] = ()
    tools: Any = Field(default=None, exclude=True)

    model_config = ConfigDict(arbitrary_types_allowed=True)


UnitStatus = Literal["completed", "degraded"]


class UnitOutcome(BaseModel):
    """One unit's modelling outcome (S1 9.1: the modeller's run types are read
    by the run driver).

    `status` is `completed` only when the persisted model reached COMPLETED and
    its completion validation is valid; everything else is `degraded` with the
    reason recorded and no loop dispatched."""

    unit_id: str
    status: UnitStatus
    state: str = ""
    validation: dict | None = None
    risk_profile: dict | None = None
    gate_writes: list[GateWrite] = Field(default_factory=list)
    trail: list[TrailEntry] = Field(default_factory=list)
    suite_gaps: list[str] = Field(default_factory=list)
    context_gaps: list[str] = Field(default_factory=list)
    archived: bool = False
    reason: str = ""


async def _await_seam(fn, *args):
    """Await an async seam, else offload a sync one to a worker thread (a sync
    seam returning a coroutine has it awaited rather than handed back bare)."""
    if inspect.iscoroutinefunction(fn):
        return await fn(*args)
    out = await asyncio.to_thread(fn, *args)
    if inspect.isawaitable(out):
        return await out
    return out


async def arun_modeller_pass(
    project_id: str,
    run_id: str,
    unit_id: str,
    tools: ModellerTools,
    *,
    turn_fn: Callable[[ModellerTurnInput], Any] | None = None,
    actor_factory: Callable[[str], "ThreatModellerActor"] | None = None,
) -> UnitOutcome:
    """Model ONE unit through the five gates (S1 6.2).

    The pass asks for each state in workflow order; the model's gate writes are
    the only writer of the model document (the harness mints nothing). The
    tracker reads the states passively: a forward jump ends the pass early, a
    lower-gate write is a trail entry, and a state the model skipped leaves a
    missing section for the completion checker to report.

    The pass returns after one turn per state at most. It never waits for
    dispatch (S1 7.3). designed-not-built - T4 (#377): the store's produced loop
    files are INTENDED to be the dispatch handoff to the run-scoped surfer, but
    no production path translates a loop file into a dispatchable item yet
    (the surfer still reads the hunt-config family), so a modelled unit
    currently dispatches nothing.

    ONE pass at a time per run: the pass mutates the shared `ModellerTools`
    (the run-scoped tracker, the store wrapper, the unit cell, the suite seam),
    so two concurrent passes over the same tools would interleave their unit
    identities and their gate readings.

    Fail-open: a raising turn is a no-decision (the breaker counts it); a
    provider failure surfaces through the breaker as a typed abort so the
    runtime pauses the run as `interrupted`.
    """
    # The RUN-scoped tracker (Critical fix): reset for this unit, seed from the
    # persisted model, and share ONE store wrapper with the captured tools. The
    # tools object is MUTATED in place, because the per-run actor captured a
    # surface over it on its first turn and a copy would strand that surface on
    # a stale seam.
    if isinstance(tools.threat_store, TrackingThreatModelStore) \
            and tools.tracker is None:
        # a caller-supplied wrapper owns its tracker: adopting it (instead of
        # creating a second one) is what keeps the captured tool's writes
        # observed - a fresh tracker would see nothing and abort the pass
        tools.tracker = tools.threat_store.tracker
    tracker = tools.tracker
    if tracker is None:
        tracker = PassiveGateTracker()
        tools.tracker = tracker
    else:
        tracker.reset()
    if tools.unit_cell is not None:
        # the per-run actor's tools are captured once: retarget the unit cell so
        # every gate write lands on THIS unit (the stable-seam pattern, #294)
        tools.unit_cell.retarget(
            project_id=tools.project_id or project_id,
            run_id=tools.run_id or run_id, unit_id=unit_id)
    if tools.threat_store is not None and not isinstance(
            tools.threat_store, TrackingThreatModelStore):
        tools.threat_store = TrackingThreatModelStore(tools.threat_store, tracker)
    first_write = len(tracker.writes)
    first_trail = len(tracker.trail)
    first_gap = len(tools.suite.gaps) if tools.suite is not None else 0
    first_seam_gap = (
        len(tools.seam_gaps.gaps) if tools.seam_gaps is not None else 0)
    persisted = _read_model(tools, project_id, unit_id)
    tracker.seed(ModelState(persisted["state"])
                 if persisted and persisted.get("state") in set(ModelState)
                 else None)
    context, context_gaps = _grounding_context(tools, unit_id)
    if _bindable(tools):
        # lazy: the tool layer imports this module's tracker and unit cell at
        # its own import time, so the dependency runs one way only (C_STD 6)
        from .threat_modeller_tools import build_modeller_tool_surface  # noqa: PLC0415

        surface = build_modeller_tool_surface(project_id, unit_id, tools)
    else:
        surface = {}
    breaker = DegradedTurnBreaker.from_env()

    if turn_fn is None:
        turn_fn = _actor_turn_fn(run_id, project_id, tools, actor_factory)

    for state in ModelState:
        if tracker.state is not None and \
                _rank(tracker.state) >= _rank(state):
            # already observed (a forward jump rides the trail, a seeded resume
            # rides its seeded entry) - never re-ask
            continue
        await breaker.before_turn(state.value)
        model = _read_model(tools, project_id, unit_id)
        turn = ModellerTurnInput(
            unit_id=unit_id, state=state, sections=GATE_SECTIONS[state],
            instruction=STATE_INSTRUCTIONS[state], model=model,
            projection=context.get("projection"),
            surface_overview=context.get("surface_overview"),
            context_gaps=context_gaps,
            tools=list(surface.values()),
        )
        cause: BaseException | None = None
        advanced_before = len(tracker.writes)
        try:
            if turn_fn is not None:
                await _await_seam(turn_fn, turn)
        except ThreatModellerDegradedError:
            raise
        except Exception as exc:  # noqa: BLE001 - a turn is a no-decision
            logger.warning("threat modeller %s turn failed (%s)", state.value, exc)
            cause = exc
        if cause is None and len(tracker.writes) == advanced_before:
            cause = _actor_degrade_cause(run_id)
        outcome = True if tracker.state is not None and \
            _rank(tracker.state) >= _rank(state) else None
        breaker.record_outcome(state.value, outcome, cause=cause)
        if tracker.state is LAST_GATE:
            break

    return _finalise(project_id, unit_id, tools, tracker,
                     first_write=first_write, first_trail=first_trail,
                     first_gap=first_gap, first_seam_gap=first_seam_gap,
                     context_gaps=context_gaps)


def _grounding_context(tools: ModellerTools, unit_id: str) -> tuple[dict, tuple[str, ...]]:
    """The unit's grounding inputs (S1 4.6, 5.6) and the gaps where one is absent.

    `context_provider(unit_id)` is the live seam; the explicit `projection` /
    `surface_overview` fields are the direct seam. A provider that raises, and a
    source that is absent, degrade to a recorded gap - never a raise into the
    pass (S1 5.7: a failed read degrades to an empty set and is recorded).

    The run bootstrap (`runtime.start_hunting`) wires the provider
    (`threat_modeller_tools.build_grounding_provider`): the `projection` comes
    from `unit_projection.build_projection(project_id, unit_id, read_fn=...)`
    over the live read-only L1 view (T2b #386). The L1 application-surface
    overview entity has NOT landed (R2-15), so it renders as its named gap on
    every turn. Nothing here is faked: an unwired source is an empty value plus
    a named gap."""
    context: dict = {
        "projection": tools.projection,
        "surface_overview": tools.surface_overview,
    }
    if tools.context_provider is not None:
        try:
            supplied = tools.context_provider(unit_id)
        except Exception as exc:  # noqa: BLE001 - a read failure degrades
            logger.warning("modeller grounding context degraded for %s (%s)",
                           unit_id, exc)
            supplied = None
        if isinstance(supplied, Mapping):
            context.update({k: v for k, v in supplied.items()
                            if k in ("projection", "surface_overview") and v})
    gaps: list[str] = []
    if not context.get("projection"):
        gaps.append("unit projection unavailable")
    if not context.get("surface_overview"):
        gaps.append("L1 application-surface overview unavailable")
    return context, tuple(gaps)


def _bindable(tools: ModellerTools) -> bool:
    """True when a surface can be built: the seams are permissive, so the only
    unbound case is a pass with no store at all (a scripted seam may still write
    through the real store it holds itself)."""
    return tools.threat_store is not None


def _rank(state: ModelState) -> int:
    from .threat_model import STATE_ORDER  # noqa: PLC0415

    return STATE_ORDER[state]


def _read_model(tools: ModellerTools, project_id: str, unit_id: str) -> dict | None:
    store = tools.threat_store
    read = getattr(store, "read_model", None) if store is not None else None
    if not callable(read):
        return None
    try:
        return read(project_id, unit_id)
    except Exception as exc:  # noqa: BLE001 - a degraded read is an empty read
        logger.warning("threat model read degraded for %s (%s)", unit_id, exc)
        return None


def _actor_degrade_cause(run_id: str) -> BaseException | None:
    """The actor's most recent degraded-turn cause, when a production actor
    produced this pass (a scripted seam has none). ONE registry key (the run id)
    serves both the default and the injected-factory lane."""
    with _MODELLER_LOCK:
        actor = _MODELLER_ACTORS.get(run_id)
    getter = getattr(actor, "last_degrade_cause", None)
    if getter is None:
        return None
    try:
        return getter()
    except Exception:  # noqa: BLE001 - a cause is provenance, never a gate
        return None


def _finalise(project_id: str, unit_id: str, tools: ModellerTools,
              tracker: PassiveGateTracker, *, first_write: int = 0,
              first_trail: int = 0, first_gap: int = 0, first_seam_gap: int = 0,
              context_gaps: tuple[str, ...] = ()) -> UnitOutcome:
    """The completion validation call (S1 6.6) and the outcome.

    The store's COMPLETED write already ran the non-blocking checker; the pass
    reads the recorded outcome and archives an INVALID model to `abandoned/` (a
    degraded unit, never a dispatchable one).

    A model that did not reach COMPLETED is degraded too, and its PARTIAL model
    is archived to `abandoned/` with it (S1 7.7: "if a partial model exists, the
    store moves its unit directory to abandoned/"). The retry policy follows from
    that move: a later run retries the unit from scratch, because no produced
    model is left to resume from - the partial was never a consumable model and
    the in-flight exclusion would otherwise skip the unit for the rest of the
    producing run's life.
    """
    store = tools.threat_store
    model = _read_model(tools, project_id, unit_id)
    outcome = UnitOutcome(
        unit_id=unit_id,
        status="degraded",
        state=(model or {}).get("state", ""),
        validation=(model or {}).get("validation"),
        risk_profile=(model or {}).get("risk_profile"),
        gate_writes=list(tracker.writes[first_write:]),
        trail=list(tracker.trail[first_trail:]),
        suite_gaps=(list(tools.suite.gaps[first_gap:])
                    if tools.suite is not None else []),
        context_gaps=list(context_gaps) + (
            list(tools.seam_gaps.gaps[first_seam_gap:])
            if tools.seam_gaps is not None else []),
    )
    if model is None:
        outcome.reason = "no threat model was written for this unit"
        return outcome
    if model.get("state") != ModelState.COMPLETED.value:
        outcome.reason = (
            f"the model did not reach COMPLETED (state={model.get('state')!r})"
        )
        _archive_degraded(store, project_id, unit_id, outcome)
        return outcome
    validation = model.get("validation") or {}
    if validation.get("valid") is True:
        outcome.status = "completed"
        return outcome
    findings = (
        list(validation.get("missing") or [])
        + list(validation.get("unclosed") or [])
        + list(validation.get("referential_errors") or [])
    )
    outcome.reason = (
        "the COMPLETED model failed the completion check: "
        + "; ".join(str(finding) for finding in findings)
    )
    _archive_degraded(store, project_id, unit_id, outcome)
    return outcome


def _archive_degraded(store, project_id: str, unit_id: str,
                      outcome: UnitOutcome) -> None:
    """Archive a degraded unit's model to `abandoned/` (S1 7.7), best-effort.

    `outcome.archived` records whether a model directory actually moved; a store
    without the archive seam (a scripted test store) leaves it False. The reason
    is logged by the store with the archived directory."""
    archive = getattr(store, "archive_unit", None)
    if not callable(archive):
        return
    try:
        outcome.archived = archive(project_id, unit_id, outcome.reason) is not None
    except Exception as exc:  # noqa: BLE001 - the archive is best-effort
        logger.warning("threat model archive failed for %s (%s)", unit_id, exc)


def run_modeller_pass(*args, **kwargs) -> UnitOutcome:
    """The SYNC lane to one modeller pass, for a caller with no running loop."""
    from polymerhus.recon.control.async_bridge import run_coro_blocking  # noqa: PLC0415

    return run_coro_blocking(arun_modeller_pass(*args, **kwargs))


# --- the per-run actor (S1 4.4) -----------------------------------------------

# ONE `ThreatModellerActor` per run_id, so the SAME actor (same per-run session
# thread) serves every unit of the run and its checkpointed memory carries the
# run's reasoning across units. Reaped by the runtime teardown, never by a
# pass's `finally`.
_MODELLER_ACTORS: dict[str, "ThreatModellerActor"] = {}
_MODELLER_LOCK = threading.Lock()


def _actor_turn_fn(run_id: str, project_id: str, tools: ModellerTools,
                   actor_factory=None) -> Callable[[ModellerTurnInput], Any]:
    """The production turn seam: the run's modeller actor. The actor is
    constructed lazily on the first turn and armed with THIS pass's tool seams
    and project root, exactly as the planner pass armed its orchestrator."""
    def turn(turn_input: ModellerTurnInput):
        actor = _resolve_actor(run_id, project_id, tools, actor_factory)
        return actor.turn(turn_input)

    return turn


def _resolve_actor(run_id: str, project_id: str, tools: ModellerTools,
                   actor_factory=None) -> "ThreatModellerActor":
    """The run's ONE actor, from the registry keyed by `run_id` in BOTH lanes
    (the default constructor and an injected factory): one key means the reap
    seam and the degrade-cause lookup can never address a different actor than
    the pass built."""
    with _MODELLER_LOCK:
        actor = _MODELLER_ACTORS.get(run_id)
        if actor is None:
            if actor_factory is not None:
                actor = actor_factory(run_id)
            else:
                from polymerhus.attack.hunting.actors import (  # noqa: PLC0415
                    ThreatModellerActor,
                )

                actor = ThreatModellerActor(run_id, tools=tools,
                                            project_id=project_id)
            _MODELLER_ACTORS[run_id] = actor
    actor.tools = tools
    actor.project_id = project_id
    return actor


def _cancel_actor_task(actor) -> bool:
    """Cancel the actor's session task - the carrier of its in-flight turn.
    True when a live task was cancelled; a settled or never-spawned actor
    (and a non-actor fake) is a safe no-op."""
    task = getattr(actor, "_task", None)
    if task is None or task.done():
        return False
    task.cancel()
    return True


async def _reap_modeller(run_id: str) -> None:
    """The module's stop path for the per-run modeller actor: reap and drop the
    actor the registry holds for `run_id`, if any. Called by the runtime
    teardown (never by a pass's `finally`) at the run stop, the run terminal,
    and the #331 provider-failure pause - the run-scoped actor and its per-run
    session thread never outlive the run.

    The stop is UNBOUNDED here; a caller that needs a bound (the provider-failure
    pause, whose resumable terminal must not wait on a stalled turn) wraps the
    await in `asyncio.wait_for`. Cancelling this reap mid-stop still cancels the
    actor's task (`finally`), so a stalled in-flight turn never outlives the
    run."""
    with _MODELLER_LOCK:
        actor = _MODELLER_ACTORS.pop(run_id, None)
    if actor is not None:
        try:
            await actor.stop()
        except Exception:  # noqa: BLE001 - teardown must never raise
            logger.warning("threat modeller actor reap failed for %s", run_id,
                           exc_info=True)
        finally:
            # a cancelled (bounded) reap lands here too; a clean stop already
            # settled the task, so this is the no-op in the normal path
            if _cancel_actor_task(actor):
                logger.warning(
                    "threat modeller actor task for %s was still live at the "
                    "reap boundary; cancelled", run_id)


__all__ = [
    "GATE_HINTS",
    "GateWrite",
    "MODELLER_MODEL_KEY",
    "MODELLER_MODEL_KEY_LEGACY",
    "MODELLER_ROLE",
    "ModellerTurnInput",
    "ModellerUnit",
    "PassiveGateTracker",
    "STATE_INSTRUCTIONS",
    "TOOL_SURFACE",
    "ThreatModellerDegradedError",
    "TrackingThreatModelStore",
    "UnitOutcome",
    "arun_modeller_pass",
    "run_modeller_pass",
]
