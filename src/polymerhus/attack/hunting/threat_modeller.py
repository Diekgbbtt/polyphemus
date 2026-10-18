"""The threat modeller: the five-gate reasoning pass over one L1 unit (S1 4-6, 9).

The hunt-orchestrator planner is rewritten in place into the **threat modeller**
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

The tool surface (S1 5) is built by `build_modeller_tool_surface`: `hunts_store`
(the threat-model read/write), `notes` (the shared notes tool with the bound
`<unit_name>:<note_name>` key), the HTTP-history read pair, the Kali `exec`
probe, and the web-vulnerability suite pair (`skill_list` / `skill_load`). The
auth store and the project skill arrive through the role's `load_skill` binding
(the recon-orchestrator coupling). Deliberately NOT bound: `graph_view` (the
agent is fed the unit projection), `kb_query`, the withdrawn fault-KB aid, and
any back-edge-to-recon tool.

This module imports no driver and performs no I/O at import (CODING_STANDARD 6).
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from polymerhus.app.memory.tool_contract import (
    NotesFieldMap,
    StoreToolBase,
    build_notes_tool,
)

from .threat_model import GATE_SECTIONS, ModelState
from .threat_model_store import NOTE_KINDS, ThreatModelIdentityError

if TYPE_CHECKING:  # the actor is a lazy import (CODING_STANDARD section 6)
    from polymerhus.attack.hunting.actors import ThreatModellerActor

logger = logging.getLogger(__name__)

# The role identity (S1 4.1, impact-map section 6): the runtime session segment,
# the actor/session role, and the LLM role id are ONE string; the provider env
# var is its uppercase form. `hunting_orchestrator` + `orchestrator` stay
# accepted for one change window (the alias) so an interrupted old run resumes
# under its recorded session id and role.
MODELLER_ROLE = "hunting_threat_modeller"
MODELLER_ROLE_LEGACY = "hunting_orchestrator"
MODELLER_SESSION_SEGMENT = "threat-modeller"
MODELLER_SESSION_SEGMENT_LEGACY = "orchestrator"
MODELLER_MODEL_KEY = "LLM_HUNTING_THREAT_MODELLER"
MODELLER_MODEL_KEY_LEGACY = "LLM_HUNTING_ORCHESTRATOR"

# The tool surface (S1 5): exactly these, nothing more. `graph_view` is not
# bound (the agent is fed the unit projection and the application-surface
# overview), the testing-methodology KB stays with the hunters and the pod, and
# the fault-KB aid tool is withdrawn - fault hypothesisation is trust-model
# driven, never copied from an outside repository.
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
        self.trail: list[dict] = []
        self.state: ModelState | None = None

    def observe(self, state: ModelState, sections: Mapping[str, Any]) -> GateWrite:
        """Record one gate write. `advanced` is True only when this write moved
        the tracked state FORWARD (a lower-gate write updates content and the
        trail, never the state)."""
        from .threat_model import STATE_ORDER  # noqa: PLC0415 - one home for the order

        rank = STATE_ORDER[state]
        current = STATE_ORDER[self.state] if self.state is not None else -1
        advanced = rank > current
        write = GateWrite(
            state=state,
            sections=tuple(sections),
            observed_at=datetime.now(timezone.utc),
            advanced=advanced,
        )
        self.writes.append(write)
        if advanced:
            skipped = [
                member.value for member in ModelState
                if current < STATE_ORDER[member] < rank
            ]
            self.state = state
            self.trail.append({
                "kind": "gate", "state": state.value, "from": (
                    None if current < 0 else
                    [m.value for m in ModelState][current]),
                "skipped": skipped, "sections": list(sections),
                "at": write.observed_at.isoformat(),
            })
        else:
            self.trail.append({
                "kind": "lower_gate", "state": state.value,
                "tracked": self.state.value if self.state else None,
                "sections": list(sections), "at": write.observed_at.isoformat(),
            })
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
        self._tracker.observe(gate, sections)
        return path

    def __getattr__(self, name):
        return getattr(self._inner, name)


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


# --- the `hunts_store` tool for the threat model (S1 5.1) ---------------------

_WRITE_INTENT_FIELDS = ("state", "sections")


class ModellerHuntsStoreArgs(BaseModel):
    """The modeller's `hunts_store` args contract.

    A write carries `{state, sections}` ONLY: the unit identity, the file name,
    the model id, and every derived symbol are bound at construction and are
    never request fields. The read carries `{cmd, unit_id?, section?}` - no
    `unit_id` reads the bound unit, a `unit_id` reads another unit's model for
    prior insight, a `section` projects one section.
    """

    cmd: Literal["read", "write"] = Field(
        description="The operation: 'read' or 'write' (required).")
    state: str | None = Field(
        default=None,
        description="Write payload: the gate state, one of UNIT_TECHNICAL_SHARP, "
                    "TRUST_MODELLED, TRUST_ASSUMPTIONS_WRITTEN, "
                    "VULNERABILITIES_WRITTEN, COMPLETED.")
    sections: dict | None = Field(
        default=None,
        description="Write payload: the section content for that gate, a mapping "
                    "from section name to section body.")
    unit_id: str | None = Field(
        default=None,
        description="Read filter: read this unit's model instead of the bound one.")
    section: str | None = Field(
        default=None,
        description="Read projection: return only this section.")

    model_config = ConfigDict(extra="forbid")


_HUNTS_STORE_DESCRIPTION = (
    "Read or write the unit threat model through the per-project threat model "
    "store.\n"
    "cmd='write': pass the gate `state` and the `sections` that gate carries. "
    "The unit identity is BOUND: never pass a unit id, a file name, a model id, "
    "or a path. The states and their sections are: UNIT_TECHNICAL_SHARP "
    "(technical_sharpening), TRUST_MODELLED (trust_model), "
    "TRUST_ASSUMPTIONS_WRITTEN (assumptions), VULNERABILITIES_WRITTEN "
    "(vulnerabilities), COMPLETED (failure_modes + loops; the store computes the "
    "risk profile and runs the completion checker). A section outside the "
    "state's set is rejected; the model state is monotonic, so a later write for "
    "an earlier gate updates that section without regressing the state.\n"
    "cmd='read': pass an optional `unit_id` (default: the unit you are modelling) "
    "and an optional `section` to project one section. Reads are read-only."
)


class ModellerHuntsStoreTool(StoreToolBase):
    """The modeller's `hunts_store` binding: the shared store-tool base over the
    bound threat-model store and the harness-bound unit identity."""

    name: str = "hunts_store"
    description: str = _HUNTS_STORE_DESCRIPTION
    args_schema: type[BaseModel] = ModellerHuntsStoreArgs
    _discriminator: str = "cmd"
    _rejection_name: str = "hunts_store"
    _require_write_intent: bool = False
    _as_json: bool = False

    def __init__(self, *, store=None, project_id: str = "", unit_id: str = "",
                 run_id: str = "", unit: "ModellerUnit | None" = None, **data):
        super().__init__(**data)
        self._store = store
        self._project_id = project_id
        self._unit_id = unit_id
        self._run_id = run_id
        self._unit = unit

    @property
    def _bound_project(self) -> str:
        return self._unit.project_id if self._unit is not None else self._project_id

    @property
    def _bound_unit(self) -> str:
        return self._unit.unit_id if self._unit is not None else self._unit_id

    @property
    def _bound_run(self) -> str:
        return self._unit.run_id if self._unit is not None else self._run_id

    @staticmethod
    def _rejected(fields: list[str], detail: str) -> dict:
        """The coded contract rejection (the `coded_teaching_rejection`
        convention): a machine error code plus the field name(s) the model must
        supply - never a silent degenerate write and never a bare raise."""
        return {
            "ok": False, "error": "hunts_store_write_rejected",
            "fields": list(fields), "detail": detail, "rejected": True,
        }

    def _read(self, args: ModellerHuntsStoreArgs) -> dict:
        if self._store is None:
            return {"error": "threat model store unavailable", "degraded": True}
        unit_id = args.unit_id or self._bound_unit
        if not unit_id:
            return {"error": "no unit is bound to this tool and none was given"}
        try:
            if args.section:
                section = self._store.read_section(self._bound_project, unit_id,
                                                   args.section)
                return {"unit_id": unit_id, "section": section}
            model = self._store.read_model(self._bound_project, unit_id)
        except Exception as exc:  # noqa: BLE001 - fail-open read, never a raise
            logger.warning("hunts_store read degraded for %s (%s)", unit_id, exc)
            return {"error": f"hunts_store read degraded: {exc}", "unit_id": unit_id}
        if model is None:
            return {"unit_id": unit_id, "model": None,
                    "detail": "no threat model exists for this unit"}
        return {
            "unit_id": unit_id,
            "state": model.get("state"),
            "sections": ["technical_sharpening", "trust_model", "assumptions",
                         "vulnerabilities", "failure_modes", "loops"],
            "model": model,
            "risk_profile": model.get("risk_profile"),
            "validation": model.get("validation"),
        }

    def _write(self, args: ModellerHuntsStoreArgs) -> dict:
        if not self._bound_unit:
            return self._rejected(
                ["unit_id"],
                "no unit is bound to this tool; the gate write cannot derive the "
                "unit directory")
        if args.state is None or str(args.state).strip() == "":
            return self._rejected(
                ["state"],
                "a write needs `state` (one of "
                f"{', '.join(state.value for state in ModelState)})")
        try:
            gate = ModelState(str(args.state).strip())
        except ValueError:
            return self._rejected(
                ["state"],
                f"unknown state {args.state!r}; known: "
                f"{', '.join(state.value for state in ModelState)}")
        sections = args.sections
        if not isinstance(sections, dict) or not sections:
            return self._rejected(
                ["sections"],
                f"a write needs `sections` (a mapping for the "
                f"{gate.value} gate: {', '.join(GATE_SECTIONS[gate])})")
        allowed = GATE_SECTIONS[gate]
        unexpected = [key for key in sections if key not in allowed]
        if unexpected:
            return self._rejected(
                list(unexpected),
                f"state {gate.value} accepts only {', '.join(allowed)}; got "
                f"{', '.join(sorted(str(key) for key in unexpected))}")
        if self._store is None:
            return {"ok": False, "error": "hunts_store_unavailable",
                    "degraded": True, "state": gate.value}
        try:
            path = self._store.write_sections(
                self._bound_project, self._bound_unit, gate, sections,
                run_id=self._bound_run)
        except ThreatModelIdentityError as exc:
            # the store's coded teaching rejection, re-surfaced verbatim
            return self._rejected(list(exc.fields), str(exc))
        except ValueError as exc:  # pydantic / enum drift in the section body
            return self._rejected(
                ["sections"], f"the {gate.value} sections are unparseable: {exc}")
        # A store write failure (an OSError) raises to the harness (O3, warned
        # and counted), never into the turn silently.
        return {"ok": True, "state": gate.value, "sections": sorted(sections),
                "path": str(path), "hint": GATE_HINTS.get(gate)}


# --- the `notes` tool for the threat model (S1 5.2) --------------------------

_NOTE_ACTIONS = ("append", "update", "delete")

_NOTES_DESCRIPTION = (
    "Read or write the project's episodic notes through the per-project threat "
    "model store's notes file.\n"
    "The note key is BOUND to the current unit: `<unit_name>:<note_name>` - you "
    "supply only the note name, never the unit.\n"
    "Commands: read / write. A write MUST set cmd='write' and an `option` "
    "(append | update | delete); `kind` is one of "
    f"{', '.join(NOTE_KINDS)}. Each reasoning phase ends with ONE episodic note "
    "through this tool: the decision nodes and the rationales of the branches you "
    "took, in prose.\n"
    "A read with `key` (a note name or a `<unit_name>:<note_name>` key) filters "
    "to that note; a read with no key returns the unit's notes, latest-first."
)


class ModellerNotesArgs(BaseModel):
    """The modeller's `notes` args contract: the shared notes algorithm with the
    unit key bound on the handle, so no request field carries the unit."""

    cmd: Literal["read", "write"] = Field(
        description="The operation: 'read' or 'write' (required).")
    option: Literal["append", "update", "delete"] | None = Field(
        default=None, description="The write option.")
    key: str = Field(
        default="", description="Read filter: a note name or a full note key.")
    note_name: str = Field(
        default="", description="The note name (the second half of the key).")
    kind: str = Field(
        default="freeform",
        description=f"The note kind: {', '.join(NOTE_KINDS)}.")
    body: str | None = Field(default=None, description="The note body.")
    note_id: str | None = Field(
        default=None, description="The note identifier for update / delete.")
    evidence: str | None = Field(
        default=None, description="Short prose evidence for the note.")
    attributes: list[str] = Field(
        default_factory=list,
        description="Read projection: return only these attributes per note.")

    model_config = ConfigDict(extra="forbid")


_MODEL_NOTES_FIELD_MAP = NotesFieldMap(
    key=None,
    read_key=None,
    action="option",
    note="body",
    note_id="note_id",
    attributes="attributes",
    passthrough=("note_name", "kind", "evidence"),
)


class ModellerNotesHandle:
    """The modeller seam's store handle for the shared `notes` tool.

    It owns the notes destination (the threat model store's `notes.yaml`) and
    the BOUND unit identity: the shared algorithm derives the key
    `<unit_name>:<note_name>` from THIS handle, never from a request field. The
    hunter-only `phase_summary` kind is refused with a coded rejection - the note
    kinds are the store's, and the harness never raises for one."""

    def __init__(self, store, project_id: str, unit_id: str,
                 unit: "ModellerUnit | None" = None) -> None:
        self._store = store
        self._project_id = project_id
        self._unit_id = unit_id
        self._unit = unit

    @property
    def _bound_project(self) -> str:
        return self._unit.project_id if self._unit is not None else self._project_id

    @property
    def _bound_unit(self) -> str:
        return self._unit.unit_id if self._unit is not None else self._unit_id

    def _unit_name(self) -> str:
        from .threat_model_store import sanitise_unit_name  # noqa: PLC0415

        return sanitise_unit_name(self._bound_unit)

    def read(self, query) -> dict:
        if self._store is None:
            return {"error": "threat model store unavailable", "degraded": True}
        key = query.key or ""
        prefix = self._unit_name()
        if key:
            full = key if key.startswith(f"{prefix}:") else f"{prefix}:{key}"
        else:
            full = prefix
        try:
            notes = list(self._store.read_notes(self._bound_project, full))
        except Exception as exc:  # noqa: BLE001 - O4: read failure -> empty set
            return {"notes": [], "error": "notes read degraded", "detail": str(exc)}
        requested = list(query.attributes)
        out = []
        for record in notes:
            projected = {attr: record.get(attr)
                         for attr in ("key", "note_name", "kind", "body")
                         if record.get(attr) is not None}
            for attr in requested:
                if attr in record:
                    projected[attr] = record[attr]
            out.append(projected)
        return {"key": full, "notes": out}

    def write(self, request) -> dict:
        if self._store is None:
            return {"ok": False, "error": "threat model store unavailable",
                    "degraded": True}
        if request.action not in _NOTE_ACTIONS:
            return {"ok": False, "error": "notes_write_rejected",
                    "fields": ["option"],
                    "detail": f"option must be one of {', '.join(_NOTE_ACTIONS)}"}
        if not request.note_name:
            return {"ok": False, "error": "notes_write_rejected",
                    "fields": ["note_name"],
                    "detail": "a note write needs a note_name; the key "
                              "<unit_name>:<note_name> is derived from it"}
        if request.kind not in NOTE_KINDS:
            # `phase_summary` is the hunter's kind and is NOT available here
            # (S1 5.2): a coded rejection the model can correct.
            return {"ok": False, "error": "notes_write_rejected",
                    "fields": ["kind"],
                    "detail": f"kind must be one of {', '.join(NOTE_KINDS)}; "
                              f"got {request.kind!r}"}
        try:
            key = self._store.write_note(
                self._bound_project, self._bound_unit,
                action=request.action, note_name=request.note_name,
                kind=request.kind, body=request.body,
                evidence=request.evidence)
        except ValueError as exc:
            return {"ok": False, "error": "notes_write_rejected",
                    "detail": str(exc)}
        if key is None:
            return {"ok": False, "error": "note_missing",
                    "note_name": request.note_name}
        return {"ok": True, "key": key}


def build_modeller_notes_tool(store, project_id: str, unit_id: str,
                              unit: "ModellerUnit | None" = None):
    """Build the modeller's bound `notes` tool: the ONE shared notes
    implementation over the unit-bound handle."""
    from .conciseness import append_conciseness_directive  # noqa: PLC0415

    return build_notes_tool(
        ModellerNotesHandle(store, project_id, unit_id, unit),
        args_schema=ModellerNotesArgs,
        field_map=_MODEL_NOTES_FIELD_MAP,
        name="notes",
        description=append_conciseness_directive(_NOTES_DESCRIPTION),
        discriminator="cmd",
        as_json=False,
        rejection_name="notes",
        write_intent_fields=("option", "body", "note_name"),
        require_write_intent=True,
    )


# --- the web-vulnerability suite pair (S1 5.5) --------------------------------

# The assumed suite contract: a skill directory per web-vulnerability class, the
# directory name IS the class the model stores in `web_vulnerability_class`
# (S1 3.4, workflow 3.4). The suite lands with the parallel skills workstream;
# until then this seam is written against the assumed names and degrades
# fail-open, recording the gap instead of breaking the class mapping.

SKILL_LIST_DESCRIPTION = (
    "List the web-vulnerability suite: one entry per suite class, carrying the "
    "class name (the skills-suite directory name you store in "
    "`web_vulnerability_class`) and its frontmatter description. Call it before "
    "mapping a freely named canonical class onto the suite class that covers it. "
    "When the suite is unavailable the call degrades to a coded gap (`suite_gap` "
    "true): keep the canonical class name, leave `web_vulnerability_class` empty, "
    "and flag the gap - never invent a suite class."
)

SKILL_LOAD_DESCRIPTION = (
    "Load one web-vulnerability suite class by its name (a directory name from "
    "skill_list): the class procedure the downstream hunter binds. A name the "
    "suite does not carry degrades to a coded gap (`suite_gap` true) - keep the "
    "canonical name you reasoned from and flag the gap."
)


@dataclass
class VulnerabilitySuiteSeam:
    """The web-vulnerability suite seam behind `skill_list` / `skill_load`.

    `classes` is the assumed suite's class set (the directory names); `read_fn`
    is the optional injected skill-body reader (the suite's own contract). A
    seam with no classes - the suite has not landed, or its store is empty -
    degrades fail-open: the listing returns an empty class set, the load returns
    the coded gap, and every gap is RECORDED on `gaps` so the run can report the
    degraded class mapping instead of silently inventing one."""

    classes: tuple[str, ...] = ()
    read_fn: Callable[[str], str] | None = None
    gaps: list[str] = field(default_factory=list)

    def record_gap(self, detail: str) -> None:
        self.gaps.append(detail)
        logger.warning("web-vulnerability suite gap: %s", detail)

    def available(self) -> bool:
        return bool(self.classes) and self.read_fn is not None

    def list_classes(self) -> dict:
        if not self.classes:
            self.record_gap("suite_unavailable: no suite class is resolvable")
            return {"skills": [], "suite_gap": True,
                    "error": "suite_unavailable",
                    "detail": "the web-vulnerability suite is not available; "
                              "keep the canonical classes and flag the gap"}
        entries = []
        for name in self.classes:
            description = ""
            if self.read_fn is not None:
                try:
                    description = _frontmatter_description(self.read_fn(name))
                except Exception:  # noqa: BLE001 - a per-entry degrade
                    description = ""
            entries.append({"name": name, "description": description})
        return {"skills": entries, "suite_gap": False}

    def load_class(self, name: str) -> dict:
        if not self.classes:
            self.record_gap("suite_unavailable: no suite class is resolvable")
            return {"ok": False, "error": "suite_unavailable", "suite_gap": True,
                    "detail": "the web-vulnerability suite is not available"}
        if name not in self.classes:
            self.record_gap(f"suite_class_missing: {name!r}")
            return {"ok": False, "error": "suite_class_missing", "suite_gap": True,
                    "detail": f"the suite carries no class {name!r}; keep the "
                              f"canonical name and flag the gap"}
        if self.read_fn is None:
            self.record_gap(f"suite_reader_unavailable: {name!r}")
            return {"ok": False, "error": "suite_reader_unavailable",
                    "suite_gap": True,
                    "detail": "the suite reader is not wired"}
        try:
            body = self.read_fn(name)
        except Exception as exc:  # noqa: BLE001 - fail-open load
            self.record_gap(f"suite_load_failed: {name!r} ({exc})")
            return {"ok": False, "error": "suite_load_failed", "suite_gap": True,
                    "detail": str(exc)}
        return {"ok": True, "name": name, "body": body, "suite_gap": False}


def _frontmatter_description(body: str) -> str:
    """The frontmatter `description` of one skill body, or "" - the listing
    reads each class's own frontmatter, never a hand-written index."""
    if not body or not body.startswith("---"):
        return ""
    end = body.find("\n---", 3)
    if end < 0:
        return ""
    for line in body[3:end].splitlines():
        if line.strip().startswith("description:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return ""


class _SuiteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SkillListArgs(_SuiteArgs):
    pass


class SkillLoadArgs(_SuiteArgs):
    name: str = Field(description="The suite class directory name to load.")


class _SkillListTool(BaseTool):
    name: str = "skill_list"
    description: str = SKILL_LIST_DESCRIPTION
    args_schema: type[BaseModel] = SkillListArgs

    def __init__(self, *, suite: VulnerabilitySuiteSeam, **data):
        super().__init__(**data)
        self._suite = suite

    def _run(self, **kwargs: Any) -> dict:
        try:
            return self._suite.list_classes()
        except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
            self._suite.record_gap(f"suite_list_failed: {exc}")
            return {"skills": [], "suite_gap": True,
                    "error": "suite_list_failed", "detail": str(exc)}


class _SkillLoadTool(BaseTool):
    name: str = "skill_load"
    description: str = SKILL_LOAD_DESCRIPTION
    args_schema: type[BaseModel] = SkillLoadArgs

    def __init__(self, *, suite: VulnerabilitySuiteSeam, **data):
        super().__init__(**data)
        self._suite = suite

    def _run(self, **kwargs: Any) -> dict:
        name = str(kwargs.get("name") or "").strip()
        if not name:
            self._suite.record_gap("suite_load_rejected: empty class name")
            return {"ok": False, "error": "suite_load_rejected", "suite_gap": True,
                    "detail": "skill_load needs the suite class name"}
        return self._suite.load_class(name)


def build_vulnerability_suite_tools(
    *, classes: Sequence[str] = (), read_fn: Callable[[str], str] | None = None,
    suite: VulnerabilitySuiteSeam | None = None,
) -> list[BaseTool]:
    """Build the `skill_list` / `skill_load` pair over the suite seam.

    The suite is the parallel skills workstream's artifact; this binder is the
    client component written against its assumed names. A seam without classes
    binds the same tools in the fail-open mode (coded gaps, recorded), so the
    role is always enabled with an honest class-mapping contract instead of a
    missing tool."""
    seam = suite or VulnerabilitySuiteSeam(
        classes=tuple(classes), read_fn=read_fn)
    return [_SkillListTool(suite=seam), _SkillLoadTool(suite=seam)]


def suite_seam_from_tools(tools: Sequence[Any]) -> VulnerabilitySuiteSeam | None:
    """The suite seam behind an already-built pair (the injected-tools case)."""
    for tool in tools:
        seam = getattr(tool, "_suite", None)
        if isinstance(seam, VulnerabilitySuiteSeam):
            return seam
    return None


# --- the tool surface ---------------------------------------------------------

@dataclass
class ModellerTools:
    """The modeller's tool seams (S1 5).

    `threat_store` is the per-project `ThreatModelStore` (the pass wraps it in
    its tracker); `exec_fn` / `http_search_fn` / `http_get_fn` are the live
    probe and HTTP-history seams (each absent degrades fail-open); `suite_tools`
    is an injectable pre-built `skill_list` / `skill_load` pair (default: built
    from `suite_classes` / `suite_read_fn`). The auth store and the project
    skill are NOT seams here: they arrive through the role's `load_skill`
    binding (the recon-orchestrator coupling, `app/auth/seams.py`)."""

    threat_store: Any = None
    project_id: str = ""
    run_id: str = ""
    exec_fn: Any = None
    http_search_fn: Any = None
    http_get_fn: Any = None
    suite_tools: Sequence[Any] = ()
    suite_classes: Sequence[str] = ()
    suite_read_fn: Callable[[str], str] | None = None
    unit_cell: ModellerUnit | None = None


def build_modeller_tool_surface(
    project_id: str, unit_id: str, tools: ModellerTools,
) -> dict[str, BaseTool]:
    """Bind the modeller's tool surface for ONE unit (S1 5, 9.2).

    The unit identity and the harness-held run id are bound here, at
    construction: the store tool and the notes tool derive every symbol from
    them, and no request field can address another unit. Each tool is a seam
    holder; a missing seam degrades fail-open (a denoted error in the
    response), never a raise into the turn."""
    from .hunter_tools import (  # noqa: PLC0415
        ExecTool,
        HttpHistoryGetTool,
        HttpHistorySearchTool,
    )

    surface: list[BaseTool] = [
        ModellerHuntsStoreTool(
            store=tools.threat_store, project_id=project_id, unit_id=unit_id,
            run_id=tools.run_id, unit=tools.unit_cell),
        build_modeller_notes_tool(tools.threat_store, project_id, unit_id,
                                  tools.unit_cell),
        HttpHistorySearchTool(http_search_fn=tools.http_search_fn,
                              project_id=project_id),
        HttpHistoryGetTool(http_get_fn=tools.http_get_fn,
                           project_id=project_id),
        ExecTool(exec_fn=tools.exec_fn),
    ]
    if tools.suite_tools:
        surface.extend(tools.suite_tools)
    else:
        surface.extend(build_vulnerability_suite_tools(
            classes=tools.suite_classes, read_fn=tools.suite_read_fn))
    return {tool.name: tool for tool in surface}


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
    trail: list[dict] = Field(default_factory=list)
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
    dispatch (S1 7.3) - the store's produced loop files are the handoff to the
    run-scoped surfer.

    Fail-open: a raising turn is a no-decision (the breaker counts it); a
    provider failure surfaces through the breaker as a typed abort so the
    runtime pauses the run as `interrupted`.
    """
    tracker = PassiveGateTracker()
    if tools.unit_cell is not None:
        # the per-run actor's tools are captured once: retarget the unit cell so
        # every gate write lands on THIS unit (the stable-seam pattern, #294)
        tools.unit_cell.retarget(
            project_id=tools.project_id or project_id,
            run_id=tools.run_id or run_id, unit_id=unit_id)
    if tools.threat_store is not None:
        tools = ModellerTools(
            threat_store=TrackingThreatModelStore(tools.threat_store, tracker),
            project_id=tools.project_id or project_id,
            run_id=tools.run_id or run_id,
            exec_fn=tools.exec_fn,
            http_search_fn=tools.http_search_fn,
            http_get_fn=tools.http_get_fn,
            suite_tools=tools.suite_tools,
            suite_classes=tools.suite_classes,
            suite_read_fn=tools.suite_read_fn,
            unit_cell=tools.unit_cell,
        )
    surface = build_modeller_tool_surface(
        project_id, unit_id, tools) if _bindable(tools) else {}
    breaker = DegradedTurnBreaker.from_env()

    if turn_fn is None:
        turn_fn = _actor_turn_fn(run_id, project_id, tools, actor_factory)

    for state in ModelState:
        if tracker.state is not None and \
                _rank(tracker.state) >= _rank(state):
            # already observed (a forward jump rides the trail) - never re-ask
            continue
        await breaker.before_turn(state.value)
        model = _read_model(tools, project_id, unit_id)
        turn = ModellerTurnInput(
            unit_id=unit_id, state=state, sections=GATE_SECTIONS[state],
            instruction=STATE_INSTRUCTIONS[state], model=model,
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
            cause = _actor_degrade_cause(actor_factory, run_id)
        outcome = True if tracker.state is not None and \
            _rank(tracker.state) >= _rank(state) else None
        breaker.record_outcome(state.value, outcome, cause=cause)
        if tracker.state is LAST_GATE:
            break

    return _finalise(project_id, unit_id, tools, tracker)


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


def _actor_degrade_cause(actor_factory, run_id: str) -> BaseException | None:
    """The actor's most recent degraded-turn cause, when a production actor
    produced this pass (a scripted seam has none). The registry is keyed by the
    injected factory when one was given, else by the run id."""
    with _MODELLER_LOCK:
        actor = _MODELLER_ACTORS.get(actor_factory if actor_factory is not None
                                     else run_id)
    getter = getattr(actor, "last_degrade_cause", None)
    if getter is None:
        return None
    try:
        return getter()
    except Exception:  # noqa: BLE001 - a cause is provenance, never a gate
        return None


def _finalise(project_id: str, unit_id: str, tools: ModellerTools,
              tracker: PassiveGateTracker) -> UnitOutcome:
    """The completion validation call (S1 6.6) and the outcome.

    The store's COMPLETED write already ran the non-blocking checker; the pass
    reads the recorded outcome and archives an invalid model to `abandoned/` (a
    degraded unit, never a dispatchable one). A model that did not reach
    COMPLETED is degraded with its recorded state and stays in place for the run
    driver to decide."""
    store = tools.threat_store
    model = _read_model(tools, project_id, unit_id)
    outcome = UnitOutcome(
        unit_id=unit_id,
        status="degraded",
        state=(model or {}).get("state", ""),
        validation=(model or {}).get("validation"),
        risk_profile=(model or {}).get("risk_profile"),
        gate_writes=list(tracker.writes),
        trail=list(tracker.trail),
    )
    if model is None:
        outcome.reason = "no threat model was written for this unit"
        return outcome
    if model.get("state") != ModelState.COMPLETED.value:
        outcome.reason = (
            f"the model did not reach COMPLETED (state={model.get('state')!r}); "
            f"the partial model stays for the run driver"
        )
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
    archive = getattr(store, "archive_unit", None)
    if callable(archive):
        try:
            outcome.archived = archive(project_id, unit_id, outcome.reason) is not None
        except Exception as exc:  # noqa: BLE001 - the archive is best-effort
            logger.warning("threat model archive failed for %s (%s)", unit_id, exc)
    return outcome


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
    if actor_factory is not None:
        with _MODELLER_LOCK:
            actor = _MODELLER_ACTORS.get(actor_factory)
            if actor is None:
                actor = actor_factory(run_id)
                _MODELLER_ACTORS[actor_factory] = actor
    else:
        with _MODELLER_LOCK:
            actor = _MODELLER_ACTORS.get(run_id)
            if actor is None:
                from polymerhus.attack.hunting.actors import (  # noqa: PLC0415
                    ThreatModellerActor,
                )

                actor = ThreatModellerActor(run_id, tools=tools,
                                            project_id=project_id)
                _MODELLER_ACTORS[run_id] = actor
    actor.tools = tools
    actor.project_id = project_id
    return actor


async def _reap_modeller(run_id: str) -> None:
    """The module's stop path for the per-run modeller actor: reap and drop the
    actor the registry holds for `run_id`, if any. Called by the runtime
    teardown (never by a pass's `finally`)."""
    with _MODELLER_LOCK:
        actor = _MODELLER_ACTORS.pop(run_id, None)
    if actor is not None:
        try:
            await actor.stop()
        except Exception:  # noqa: BLE001 - teardown must never raise
            logger.warning("threat modeller actor reap failed for %s", run_id,
                           exc_info=True)


__all__ = [
    "GATE_HINTS",
    "GateWrite",
    "MODELLER_MODEL_KEY",
    "MODELLER_MODEL_KEY_LEGACY",
    "MODELLER_ROLE",
    "MODELLER_SESSION_SEGMENT",
    "MODELLER_SESSION_SEGMENT_LEGACY",
    "ModellerHuntsStoreArgs",
    "ModellerHuntsStoreTool",
    "ModellerNotesArgs",
    "ModellerNotesHandle",
    "ModellerTools",
    "ModellerUnit",
    "ModellerTurnInput",
    "PassiveGateTracker",
    "STATE_INSTRUCTIONS",
    "TOOL_SURFACE",
    "ThreatModellerDegradedError",
    "TrackingThreatModelStore",
    "UnitOutcome",
    "VulnerabilitySuiteSeam",
    "arun_modeller_pass",
    "build_modeller_notes_tool",
    "build_modeller_tool_surface",
    "build_vulnerability_suite_tools",
    "run_modeller_pass",
    "suite_seam_from_tools",
]
