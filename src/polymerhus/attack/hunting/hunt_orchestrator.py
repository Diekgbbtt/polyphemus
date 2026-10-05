"""The hunt-orchestrator (#82): the central memory of the hunting effort.

Consumes the FaultSource candidate set (IA-1, spec 4.1) and runs the REASON
stretch as a NODE-PER-PHASE workflow graph (the #167 rework of #110's graph
engine): the supervisor pops FAULT work items (the fault stays the schedule
unit, spec 3.1) and iterates each fault's candidate queue as the pairs the
phase nodes operate on; every (unit, fault) pair runs `hypothesise -> ratify
-> note` as graph nodes with the transition logic embedded in the graph (G2)
and the phase-transition verbatims injected on-the-fly in the specific
tool-call responses (constants, never the system prompt - G1/G3). The
hypothesise phase elicits one or more vulnerability classes; the AGENT's
`hunts_store(write, status="hypothesised")` tool call is the SOLE writer of the
draft (#294 - the harness mints deterministically in memory only, to drive the
phase flow); the ratify phase may update/delete/create configs and MUST end with
a status="ratified" agent write; the note phase's agent `notes(write)` call is
the SOLE note writer and the pair's loop ENDs at that tool's response (the next
pair + the restart verbatim). The harness never re-persists the structured
decisions; the phase flow READS the persisted state (note frame + ledger). The
#201 carve-out is preserved: the harness-owned deterministic `surface_context`
is injected on the wrapped store seam. The dispatch node is REMOVED (G12) and the
O9 budget stage is REMOVED (G7): the graph ENDs at the REASON stretch - dispatch
state and spending are the runtime plane's and the pod's ownership. It never
writes L0/L1 (its graph access is the read-only view, D67-04); the hunting agent
(#83), not this module, is the test-DESIGN actor.

The pass runs NATIVE-ASYNC (feat/async-actor-agents) on the #110 GRAPH engine:
`arun_orchestration` is the single O1-O10 canon and its body IS a
supervisor-state schedule loop (the ONE flexible StateGraph in
`orchestrator_graph.py`) - per fault, the stateful phase turns run on the
run's `HuntOrchestratorActor` thread (`hunting_orchestrator` session,
monotonic across ALL faults and pairs), while the agent's own tool calls persist
the configs into the store's `produced/` and the notes into `memory.yaml`. Each
node closure delegates to the canon helpers in THIS module; the O1-O10 seam
shapes stay single-sourced here. `run_orchestration` is its thin sync wrapper.

The actor is the PURELY STATEFUL parent, exactly like the recon-orchestrator -
but it now LIVES in a per-run registry (`_ORCHESTRATOR_ACTORS`) instead of being
reaped in a pass's `finally` (#110): the SAME `HuntOrchestratorActor` (same
thread) serves every pair of a pass and stays live listening between passes;
the module's runtime stop path (Task 6) reaps it.

Degradations are the spec's failure canon: KB unavailable -> the gate reasons
degraded, never prunes (D67-11); a raising hypothesise turn carries the pair
bare (fail-open, the old gate-carry); a raising ratify/note turn skips that
phase's side effect but the pair keeps serving (the phase machine degrades
gracefully); an agent store write failure -> the tool degrades it fail-open and
the harness counts it on the wrapped seam (O3, a duplicate-config write is the
deduplication signal and lands the same O3 path - G4); store read failure ->
empty prior insights / an empty note frame (O4); a malformed candidate is
dropped and counted (O10). Fail-open throughout: one bad collaborator never
aborts the pass.

This module imports no driver and performs no I/O at import; the graph read
seam resolves lazily on first call (CODING_STANDARD section 6).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Literal, Sequence

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # the actor is a lazy import (CODING_STANDARD section 6)
    from polymerhus.attack.hunting.actors import HuntOrchestratorActor

from polymerhus.attack.hunting.fault_risk import risk_tier
from polymerhus.attack.hunting.hunt_store import (
    DuplicateConfigError,
    KEY_SEPARATOR,
    semantic_key,
)
from polymerhus.attack.hunting.orchestrator_graph import PhaseAbort
from polymerhus.analysis.l1_types import elide_singleton
from polymerhus.recon.control.targeted import (
    AnalyserReconRequest,
    ReconScope,
    TargetedReconResult,
)

logger = logging.getLogger(__name__)

# The orchestrator's tool surface (spec 3.4, amended by #167/G3): the two store
# tools `hunts_store` / `notes` plus the read-only graph view - exactly these,
# nothing more. The old five-tool surface (`read_memory_hunts` /
# `read_memory_notes` / `mint_hunt_config` / `record_note`) is REPLACED. No
# back-edge-to-recon tool (the back_edge request to recon is out of the agent's
# surface; operator ruling 2026-08-22 - the target-knowledge loop rides
# `graph_view`, never a recon request) and no budget tool (G7: spending is the
# runtime plane's and the pod's ownership).
TOOL_SURFACE = frozenset({
    "hunts_store", "notes", "graph_view",
})

# The phase-transition verbatims (memory-system spec 7, G1/G3): CONSTANTS
# injected on-the-fly in the SPECIFIC tool-call responses, never embedded in
# the agent system prompt (D3). NEXT_RATIFY_HINT rides the hypothesise (and
# any in-progress ratification) write's response; NEXT_NOTE_HINT rides the
# ratified write's response - ONLY this, the next pair is NOT fed there (G1
# correction); NEXT_PAIR_HINT rides the note write's response together with
# the next pair's frame (the pair end, G1).
NEXT_RATIFY_HINT = (
    "Ratification in progress: reason on proximity and too-near same-class "
    "merging, then run the preconditions (the test's preconditions - the "
    "attacker's existing capabilities AND the environment conditions the test "
    "needs, never post-exploitation capabilities) / observed_defences (the "
    "observed target characteristics that hinder the tests and support a "
    "falsification) analysis. End ratification with a hunts_store write "
    "carrying status='ratified'."
)
NEXT_NOTE_HINT = (
    "Ratification complete. Strongly take notes: write ONE note per config "
    "covering ALL the decisions that concern it - the observations drawn from "
    "your tool calls (graph_view or memory reads) that drove the rationale - "
    "more detailed than the config's rationale and walking the reasoning that "
    "yielded it."
)
NEXT_PAIR_HINT = (
    "Pair complete. Start the next iteration: reason the next pair below "
    "through the same hypothesise -> ratify -> note phases."
)


def pair_frame(unit_id: str, fault_class: str) -> dict:
    """The next pair's frame the notes tool's response carries at the pair end
    (G1): the (unit, fault) identity the iteration restarts on."""
    return {"unit_id": unit_id, "fault_class": fault_class}

# The per-run orchestration actor registry (#110): ONE `HuntOrchestratorActor`
# per run_id, lazily resolved on the pass's first LLM turn and HELD after the
# graph completes - so the SAME actor (same `hunting_orchestrator` thread)
# serves every fault of the run and stays live until the module's stop path
# reaps it. Reaping is never a pass's `finally` responsibility.
_ORCHESTRATOR_ACTORS: dict[str, "HuntOrchestratorActor"] = {}
_ORCHESTRATOR_LOCK = threading.Lock()

# The per-run store-seam wrappers (#294 requirement 2): ONE
# `SurfaceContextStore` per run_id, RETARGETED each pass. The actor's tool
# surface captures the store seam ONCE (`actors.build_orchestrator_tool_surface`
# binds `tools.store_reads` at first `_ensure_started`), so a fresh wrapper per
# pass would leave the actor writing through the previous pass's wrapper (stale
# `surface_context`, and counters the report never reads). Keeping one wrapper
# per run and retargeting it keeps the captured seam current for every pass.
# Reaped alongside the actor by the module's stop path.
_SURFACE_STORES: dict[str, "SurfaceContextStore"] = {}

# The default targeted job a park/resume back-edge runs (a re-witness of the
# unit's surface).
_DEFAULT_BACK_EDGE_JOB = "httpx_reprofile"


# --- #280 Part 2: the consecutive-degradation circuit breaker ----------------
#
# The coupled gap to the parsing-error recovery (#280 Part 1): when the phase
# turns keep returning a no-decision (None) outcome - the signature of a
# poisoned thread before the fix, or any sustained provider outage - the pass
# used to fail-open each pair and move on at full speed (a hot loop). The
# breaker counts CONSECUTIVE no-decision turn outcomes across the phase's pairs
# (reset on any real decision), applies a bounded exponential backoff once a
# small threshold is crossed, and aborts the pass with a typed, operator-visible
# failure after K. Below the threshold it stays per-pair fail-open, and it never
# silently prunes a pair (D67-11). All four knobs are env-backed with sane
# defaults: HUNT_TURN_DEGRADED_STREAK_WARN, HUNT_TURN_DEGRADED_STREAK_ABORT,
# HUNT_TURN_DEGRADED_BACKOFF_BASE_S, HUNT_TURN_DEGRADED_BACKOFF_MAX_S.

_DEFAULT_DEGRADED_WARN_STREAK = 2
_DEFAULT_DEGRADED_ABORT_STREAK = 5
_DEFAULT_DEGRADED_BACKOFF_BASE_S = 1.0
_DEFAULT_DEGRADED_BACKOFF_MAX_S = 30.0


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "") or "")
        return value
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, "") or "")
        return value if value >= 0 else default
    except (TypeError, ValueError):
        return default


class HuntOrchestrationDegradedError(PhaseAbort):
    """The pass ABORTED after a run of consecutive no-decision phase turns
    (#280 Part 2). Typed and operator-visible: it is raised out of
    `arun_orchestration`, so the runtime logs it and lands the run failed
    instead of grinding through the remaining pairs against a dead thread."""

    def __init__(self, *, phase: str, streak: int, threshold: int) -> None:
        self.phase = phase
        self.streak = streak
        self.threshold = threshold
        super().__init__(
            f"hunting pass aborted: {streak} consecutive no-decision phase "
            f"turn(s) (last phase {phase!r}, abort threshold {threshold})")


class DegradedTurnBreaker:
    """The pass-scoped counter + backoff + abort for no-decision phase turns.

    `before_turn` sleeps the current backoff (0 until the warn threshold is
    crossed); `record_outcome` resets on a real decision, counts a `None`
    outcome, and raises `HuntOrchestrationDegradedError` at the abort
    threshold. `abort_streak <= 0` disables the abort (the backoff still
    applies)."""

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
            backoff_base_s=_env_float(
                "HUNT_TURN_DEGRADED_BACKOFF_BASE_S",
                _DEFAULT_DEGRADED_BACKOFF_BASE_S),
            backoff_max_s=_env_float(
                "HUNT_TURN_DEGRADED_BACKOFF_MAX_S",
                _DEFAULT_DEGRADED_BACKOFF_MAX_S),
            warn_streak=_env_int(
                "HUNT_TURN_DEGRADED_STREAK_WARN",
                _DEFAULT_DEGRADED_WARN_STREAK),
            abort_streak=_env_int(
                "HUNT_TURN_DEGRADED_STREAK_ABORT",
                _DEFAULT_DEGRADED_ABORT_STREAK),
        )

    def delay_for(self, streak: int) -> float:
        """The bounded exponential delay for the given consecutive-failure
        streak: 0 below the warn threshold, else base * 2^(streak - warn),
        capped at the max."""
        if streak < self._warn or self._base <= 0:
            return 0.0
        return min(self._base * (2 ** (streak - self._warn)), self._max)

    async def before_turn(self, phase: str) -> None:
        delay = self.delay_for(self.streak)
        if delay > 0:
            logger.warning(
                "hunting pass degraded: %d consecutive no-decision turn(s); "
                "backing off %.2fs before the %s turn", self.streak, delay, phase)
            await self._sleep(delay)

    def record_outcome(self, phase: str, outcome: Any) -> None:
        if outcome is not None:
            self.streak = 0
            return
        self.streak += 1
        if self._abort > 0 and self.streak >= self._abort:
            raise HuntOrchestrationDegradedError(
                phase=phase, streak=self.streak, threshold=self._abort)

# The config status lifecycle (ADR G5/G6): hypothesised -> ratified | dropped.
# `noted` is a LOOP state, never a config status; `consumed` is tautological in
# the produced/consumed memory topology, never a status enum member. Single-
# sourced so the config model and the mint share one vocabulary (C_STD §7).
ConfigStatus = Literal["hypothesised", "ratified", "dropped"]

# The harness's loop-state machine (G2/G5) is single-sourced in
# `orchestrator_graph.LoopState` (an enum - the graph's phase-node wrappers and
# the `loop_state` channel share it); the canon phase nodes here reference the
# enum's `.value` strings only through the graph's wrappers. `NOTED` is a LOOP
# state, never a config status.


class Witness(BaseModel):
    """The applies-witness pair of a delivered candidate: a deterministic
    half (the violated predicate clause) and an LLM half (the match rationale)."""

    deterministic: str | None = None
    llm: str | None = None


class DeliveredCandidate(BaseModel):
    """A FaultSource output (IA-1): one `(testable-unit, fault-class)` pair with
    its applies-witnesses and the three-valued match verdict (D2)."""

    unit_id: str
    fault_class: str
    applies_witnesses: Witness
    match_verdict: Literal["applies", "does-not-apply", "insufficient-evidence"]


class EnvisionedDirection(BaseModel):
    """One gate output: a carried (or pruned) direction, seeded with the
    rationale and the candidates-rewrite class-level `research_direction`
    (verbatim feasibility prose, never narrowed to a surface locale / payload /
    vector / symptom - #202), plus the elicited `vulnerability_classes`. As of
    the HuntConfig typing rework the direction is the ELICITATION CARRIER: it
    rides the `vulnerability_classes` the mint fans out into ONE `HuntConfig`
    per distinct class (the class is the config's identity axis); the
    concrete-fault stretch (test primitives, payload vectors, per-candidate
    capability/blocker analysis) is the #164 hunter's DECOMPOSE/GENERATE
    ownership, never this carrier's (#202: the old `assumptions` /
    `envisioned_test_primitives` carrier slots are removed - traced-only, never
    minted)."""

    unit_id: str
    fault_class: str
    carried: bool = True
    rationale: str = ""
    research_direction: str = ""
    vulnerability_classes: list[str] = Field(default_factory=list)


class GateInput(BaseModel):
    """The per-fault reasoning turn's input (Q8): the accepted candidate set,
    the KB evidence (empty + degraded flag when the KB is unavailable, D67-11),
    and the read-only graph surface. As of the candidates-rewrite the schedule
    unit is the FAULT: `candidates` carries the fault's FULL matched-unit list
    (never one pair), so ONE turn reasons over all of them on the run's
    orchestration thread.

    The #135 symbolic render rides the SAME input: each unit's typed projection
    (built independently, fail-open per unit in `unit_projection`), the fault's
    materialisation-facet content for the `fault_class`, and the sorted
    sub-fault fold family captured under it (empty tuple for a leaf parent).
    `projection` reflects the single-unit slot for backward compatibility.
    `prior_minted_keys` carries the CURRENT `LoopLedger.minted_config_keys`
    (the revival keys the Q11 novelty reflection lists - seeded by the reason
    node from the ledger state, fail-open to []). Every slot is degraded
    independently - `unit_projection[unit_id]` None, an absent
    materialisation/fold-family key - and renders as UNKNOWN, never FALSE,
    never a prune signal (C16)."""

    candidates: list[DeliveredCandidate] = Field(default_factory=list)
    kb_degraded: bool = False
    kb_evidences: dict = Field(default_factory=dict)
    surface: list[dict] = Field(default_factory=list)
    projection: object | None = None
    unit_projection: dict[str, object | None] = Field(default_factory=dict)
    materialisation: dict = Field(default_factory=dict)
    fold_family: dict = Field(default_factory=dict)
    prior_minted_keys: list[str] = Field(default_factory=list)


class GateDecision(BaseModel):
    """The hypothesise phase's output: the directions, each marked carried or
    pruned in-turn. The deterministic mint fans the carried directions out into
    the status="hypothesised" drafts (one per distinct elicited class) at this
    phase."""

    directions: list[EnvisionedDirection] = Field(default_factory=list)


class PhaseTurnInput(BaseModel):
    """One ratify/note phase turn's input (the hypothesise turn keeps the
    `GateInput` shape): the (unit, fault) pair plus the pair's CURRENT configs
    - the hypothesise drafts the ratify phase may update/delete/create, and
    the ratified configs the note phase reasons over. The pair's symbolic
    render slots are carried too, so the phase turns ground identically to the
    hypothesise turn. Every slot degrades independently (fail-open)."""

    pair: DeliveredCandidate
    configs: list["HuntConfig"] = Field(default_factory=list)
    kb_degraded: bool = False
    kb_evidences: dict = Field(default_factory=dict)
    surface: list[dict] = Field(default_factory=list)
    projection: object | None = None
    unit_projection: dict[str, object | None] = Field(default_factory=dict)
    materialisation: dict = Field(default_factory=dict)
    fold_family: dict = Field(default_factory=dict)
    prior_minted_keys: list[str] = Field(default_factory=list)


class NoteRecord(BaseModel):
    """One note the note phase writes (G8): keyed by the config's identity and
    carrying the reasoning content - mostly the observations drawn from tool
    calls (graph_view or memory reads) that drove the rationale, more detailed
    than the config's `rationale` and walking the reasoning that yielded it."""

    key: str
    note: str


class RatifyDecision(BaseModel):
    """The ratify phase's outcome: the pair's configs after the ratification
    turn, each carrying its final status (`ratified` or `dropped`) and the
    filled ratification fields. The decision drives the phase transition/report
    only - the PERSISTENCE rides the agent's `hunts_store(write)` tool call
    (update in place / dropped-on-disk, G6); the harness never re-persists it
    (#294)."""

    configs: list["HuntConfig"] = Field(default_factory=list)


class NoteDecision(BaseModel):
    """The note phase's outcome: the notes the pair writes. The PERSISTENCE
    rides the agent's `notes(write, option="append")` tool call (the sole note
    writer, #294); the harness never appends the decision's notes. The tool's
    response carries the next pair + the NEXT_PAIR_HINT constant (G1)."""

    notes: list[NoteRecord] = Field(default_factory=list)


class HuntConfig(BaseModel):
    """The declarative config the hunting agent consumes (D3): the parameter
    set - the hypothesise-phase content (`rationale` + `research_direction`),
    wide surface context (adapted index-card, a Service's edge_degree
    transformed to its connected DataItems), the ratification-phase
    `preconditions` + `observed_defences`, and the downstream prior-hunt
    insights (the hunter memory's TestImplementationSpecs + Q16 pod exports by
    config_key, shallow-projected, #202) - plus the orchestrator's stretch as of
    the typing rework: `status` (the config lifecycle `hypothesised ->
    ratified | dropped`; the mint writes hypothesised drafts),
    `vulnerability_class` (the config's identity axis, one config per elicited
    class; the naming IS the initial concretisation).

    The config is oriented by the three goals (#202): (G1) feasibility of that
    fault at that unit - `rationale`, `research_direction`, `vulnerability_class`,
    `surface_context` (which now also carries the folded applies-witness as
    `fault_evidence`), `preconditions`, `observed_defences`; (G2) the initial
    concretisation - the `vulnerability_class` naming itself; (G3)
    further-concretisation material - `prior_hunt_insights`. `tool_registry` /
    `adversarial_capabilities` / `assumptions` / `technique_primitives` /
    `target_caveats` are removed (#202), and `sub_fault_ids` is removed (#298 -
    bare folded CWE ids the hunter cannot resolve were noise).

    The former `HuntPromptTemplate` wrapper is FLATTENED (2026-10-04): it carried
    exactly two plain strings, so `rationale` and `research_direction` are
    top-level config fields - the container added a model/harness ownership
    boundary with no structure to own. The former `l0_evidence` slot is REMOVED
    (#298): the candidate's applies-witness is folded into the orchestrator-owned
    `surface_context` (`fault_evidence`)."""

    hunt_id: str
    unit_id: str
    fault_class: str
    status: ConfigStatus = "hypothesised"
    vulnerability_class: str = ""
    rationale: str = ""
    research_direction: str = ""
    surface_context: dict = Field(default_factory=dict)
    observed_defences: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    prior_hunt_insights: list[dict] = Field(default_factory=list)


class DispatchResult(BaseModel):
    """One hunting-agent dispatch outcome (IA-2): the delivered refs plus the
    hypothesis verdict and NL feedback (D11)."""

    spec_ref: str | None = None
    pod_result_ref: str | None = None
    hypothesis_verdict: str | None = None
    feedback: str | None = None


class CandidateIntake(BaseModel):
    """The normalised candidate set: accepted survivors, dropped-and-counted
    duplicates (O7) and malformed candidates (O10), and the deterministic
    does-not-apply prunes (the verdict's prune signal, Q8 level 1)."""

    accepted: list[DeliveredCandidate] = Field(default_factory=list)
    duplicates_dropped: int = 0
    malformed_dropped: int = 0
    pruned_by_verdict: int = 0


class FaultWorkItem(BaseModel):
    """The schedule unit of the candidates-rewrite graph (spec 3.1): ONE work
    item per distinct fault, carrying that fault's FULL matched-unit list (every
    `DeliveredCandidate` in the intake with this `fault_class`). The graph's
    `state["current"]` is a `FaultWorkItem`, so ONE REASON turn covers the fault
    over all its matched units (never one per unit). Ordering is deterministic:
    the schedule groups by `fault_class` in first-emission order of the intake."""

    fault_class: str
    candidates: list[DeliveredCandidate] = Field(default_factory=list)


class LoopLedger(BaseModel):
    """The harness-owned loop-state ledger (spec 3.3, provisional term): units
    done/skipped, the minted config keys (REVIVAL keys - the Q11 novelty
    reflection lists exactly these) and the notes recorded, carried on the
    graph state and updated at the pair boundary. As of the workflow-graph
    rework the per-pair phase position lives on the graph's `loop_state`
    channel (`HYPOTHESISED -> RATIFIED -> NOTED`, G2/G5); this ledger holds the
    accumulated pass counts. The budget-remaining slot is REMOVED (G7): the O9
    budget stage is gone - spending is the runtime plane's and the pod's."""

    units_done: int = 0
    units_skipped: int = 0
    minted_config_keys: list[str] = Field(default_factory=list)
    notes_recorded: int = 0


class OrchestratorReport(BaseModel):
    """The pass summary (spec O1-O10, amended by the memory + workflow-graph
    rework): the graph ENDs at the REASON stretch - there is no dispatch node
    (G12) and no budget stage (G7) - so the report carries what the graph did:
    the pairs processed through the phase machine, the configs hypothesised /
    ratified / dropped, the notes written, the ledger, and the failure counts.
    `configs_unratified` counts configs the ratify turn RETURNED without a
    terminal `ratified` status (the "must END with ratified" contract, S2):
    they stay hypothesised on disk, are never counted ratified, and the note
    phase does not note over them. `duplicate_config_writes` is the G4
    deduplication-signal count, kept separate from (but additive with) the O3
    `store_write_failures` counter; under the agent-sole write model (#294)
    both are observed on the wrapped store seam (the agent's tool calls), never
    incremented by a harness write."""

    pairs_processed: int = 0
    configs_hypothesised: int = 0
    configs_ratified: int = 0
    configs_dropped: int = 0
    configs_unratified: int = 0
    notes_written: int = 0
    duplicates_dropped: int = 0
    malformed_dropped: int = 0
    pruned_by_verdict: int = 0
    gate_pruned: tuple[str, ...] = ()
    exhausted_faults: tuple[str, ...] = ()
    store_write_failures: int = 0
    duplicate_config_writes: int = 0
    ledger: LoopLedger = Field(default_factory=LoopLedger)


class ReadOnlyGraphViewError(RuntimeError):
    """A write was attempted through the read-only graph view (D67-04)."""


# Write-shaped tokens the read-only view refuses to pass through, whatever the
# calling convention (defense in depth - the API itself exposes no write seam).
_WRITE_SHAPED = re.compile(r"\b(?:MERGE|CREATE|DELETE|SET|REMOVE|FOREACH|LOAD\s+CSV)\b")


class ReadOnlyGraphView:
    """The orchestrator's read-only view over the live L0/L1 graph (D67-04):
    it grounds the gate in the live graph and can never write it. Any
    write-shaped call - including `merge` itself - raises."""

    def __init__(self, project_id: str, *, read_fn: Callable[[str, dict], list] | None = None):
        self.project_id = project_id
        self._read_fn = read_fn

    def _guard(self, cypher: str) -> None:
        if _WRITE_SHAPED.search(cypher.upper()):
            raise ReadOnlyGraphViewError(
                "the graph view is read-only: refusing write-shaped cypher "
                f"{cypher[:120]!r}"
            )

    def read(self, cypher: str, params: dict | None = None) -> list[dict]:
        self._guard(cypher)
        if self._read_fn is not None:
            return self._read_fn(cypher, params or {})
        from polymerhus.app.clients import neo4j_client

        return neo4j_client.read(cypher, params or {})

    def merge(self, *args: Any, **kwargs: Any) -> Any:
        raise ReadOnlyGraphViewError(
            "the graph view is read-only: the orchestrator never writes L0/L1"
        )

    def index_cards(self) -> list[dict]:
        from polymerhus.analysis.index_card import index_cards as _index_cards

        return _index_cards(self.project_id, read_fn=self.read)


@dataclass
class PhaseContext:
    """The harness-owned per-pair context the tool seams read to inject the
    phase-transition verbatims (G1/G3): `next_pair` (the NEXT pair's frame the
    notes tool's response carries at the pair end - the note phase's canon body
    sets it before the turn). The verbatim SELECTION rides the write's `status`
    attribute on the config object (hypothesised -> NEXT_RATIFY_HINT, ratified
    -> ONLY NEXT_NOTE_HINT, the note append -> NEXT_PAIR_HINT), so there is no
    separate phase cursor (S4). The verbatims themselves are module constants,
    never the system prompt (D3)."""

    next_pair: dict | None = None


@dataclass
class OrchestratorTools:
    """The orchestrator's tool seams (spec 3.4, amended by #167/G3): the
    per-project memory store (`store_reads` - the read/write surface both
    `hunts_store` and `notes` bind to, plus the prior-config/notes reads and
    the sibling hunter-memory reads `read_hunter_specs` / `read_hunter_notes`,
    #202), the read-only graph view (`graph_view` - the surface `graph_view`
    defers to for the projected context: the store tools only ever read service
    keys), and the run-local `phase_context` the note phase node sets so the
    notes tool's response carries the next pair's frame (G1). `back_edge` is
    retained for the runtime plane's dispatch ownership (G12) but is NOT part
    of the model surface anymore."""

    back_edge: Callable[[AnalyserReconRequest, str, str], TargetedReconResult] | None = None
    store_reads: Any = None
    graph_view: ReadOnlyGraphView | None = None
    phase_context: PhaseContext = field(default_factory=PhaseContext)


def revival_key(unit_id: str, fault_class: str) -> str:
    """The kind-qualified pair that persists a hunt's place (Q5/#70): survives
    the hunt, drives change-driven re-test, and joins the fault on the wire
    (the back-edge itself is fault-agnostic). Single-sourced on the store's
    `KEY_SEPARATOR` (M1), so it can never drift from being the 2-part prefix
    of a config's semantic key."""
    return f"{unit_id}{KEY_SEPARATOR}{fault_class}"


def normalize_candidates(
    candidates: Sequence[DeliveredCandidate],
    known_faults: Sequence[str] | None = None,
) -> CandidateIntake:
    """Dedup by `(unit_id, fault_class)` identity (O7), drop malformed
    candidates counted (O10: a candidate with NO witness half at all - neither
    deterministic nor llm - or an unknown fault class when a registry is
    given), and apply the match-verdict prune signal (Q8 level 1): a
    does-not-apply candidate is pruned before the gate - never pruned on a
    rejection, only a witness-less candidate drops it. As of #200 (spec 4.1)
    the LLM witness half is OPTIONAL: a deterministic-only witness is a valid
    delivered candidate, so the platform's own internal selection is never
    discarded here."""
    seen: set[tuple[str, str]] = set()
    intake = CandidateIntake()
    known = set(known_faults) if known_faults is not None else None
    for candidate in candidates:
        identity = (candidate.unit_id, candidate.fault_class)
        if identity in seen:
            intake.duplicates_dropped += 1
            continue
        seen.add(identity)
        witnesses = candidate.applies_witnesses
        if witnesses is None or (
                witnesses.deterministic is None and witnesses.llm is None):
            intake.malformed_dropped += 1
            continue
        if known is not None and candidate.fault_class not in known:
            intake.malformed_dropped += 1
            continue
        if candidate.match_verdict == "does-not-apply":
            intake.pruned_by_verdict += 1
            continue
        if candidate.match_verdict not in ("applies", "insufficient-evidence"):
            intake.malformed_dropped += 1
            continue
        intake.accepted.append(candidate)
    return intake


def _distinct_vulnerability_classes(classes: Sequence[str]) -> list[str]:
    """The mint's fan-out discriminator: the direction's elicited vulnerability
    classes, deduped in first-emission order (the LLM's Q16 same-class merge
    runs BEFORE the mint, so same-class duplicates should already be gone; the
    mint still collapses them deterministically). A class string carrying no
    marker - empty or absent - never forms a minted group; a direction with no
    surviving classes degrades to the carried-bare fallback."""
    seen: set[str] = set()
    out: list[str] = []
    for cls in classes:
        if not cls:
            continue
        if cls in seen:
            continue
        seen.add(cls)
        out.append(cls)
    return out


def _data_item_detail(item) -> dict:
    """Pure: one connected-DataItem detail dict for the surface-context
    transform (name/type/sensitivity/fields/notes, the ADR G5 slots). An
    absent slot stays absent - absence is not-yet-filled, never a marker."""
    detail: dict = {}
    for attr in ("name", "type", "sensitivity"):
        val = getattr(item, attr, None)
        if val is not None:
            detail[attr] = val
    if getattr(item, "fields", None):
        detail["fields"] = sorted(map(str, item.fields))
    if getattr(item, "notes", None):
        detail["notes"] = item.notes
    return detail


def _aggregated_endpoint_detail(endpoint) -> dict:
    """Pure: one aggregated L0 Endpoint detail dict for the surface-context
    transform (#201): the typed identity props (method/path/baseurl) plus the
    owning service slug when the aggregate resolves through a System unit's
    LINKED services. An absent slot stays absent - absence is not-yet-filled,
    never a marker."""
    detail: dict = {}
    for attr in ("method", "path", "baseurl"):
        val = getattr(endpoint, attr, None)
        if val is not None:
            detail[attr] = val
    slug = getattr(endpoint, "service_slug", None)
    if slug:
        detail["service_slug"] = slug
    return detail


def _unit_matches_card(card: dict, unit_id) -> bool:
    """Pure: True when `card` is the projection's own unit's card (the config's
    target). A Service card keyed on `business_function_slug` matches
    `"Service:<slug>"`; a System card keyed on `(kind, discriminator)` matches
    `"<kind>:<discriminator>"`, while a SINGLETON System card matches the bare
    kind `"<kind>"` (#279 follow-up: the sentinel is elided from the
    orchestrator-facing unit id AND from the card key at source, so the matcher
    accepts both the bare-kind singleton form and the `kind:disc` multi-instance
    form). A malformed key or an absent unit_id never matches (fail-open)."""
    if not unit_id:
        return False
    key = card.get("key")
    if not isinstance(key, dict):
        return False
    if card.get("kind") == "Service":
        slug = key.get("business_function_slug")
        return bool(isinstance(slug, str) and slug
                    and unit_id == f"Service:{slug}")
    kind = key.get("kind")
    if not (isinstance(kind, str) and kind):
        return False
    discriminator = elide_singleton(key.get("discriminator"))
    if discriminator:
        return unit_id == f"{kind}:{discriminator}"
    return unit_id == kind


def service_card_projection(
    surface: Sequence[Any], projection,
) -> list[Any]:
    """The config surface-context transform (ADR G5, operator correction;
    renamed for #201): the target unit card's `edge_degree` counts are replaced
    by the detailed connected DataItems (name/type/sensitivity/fields/notes) of
    the unit's rich projection AND the card is expanded with its aggregated L0
    Endpoints (`aggregated_endpoints`: method/path/baseurl from the projection's
    AGGREGATES slot) under the parent unit - a System card carries its linked
    services' endpoints with the owning service slug. The L0 expansion fires
    ONLY for the card of the projection's own unit (the config's target) -
    never for the whole surface (DD-4 token-light budget); the surface itself
    stays the L1-only index-cards. An absent projection, a non-matching card, a
    projection that resolved no data items / aggregates, or a malformed card (a
    non-dict surface element) degrades to the card unchanged - fail-open per the
    canon, never a raise, never a prune signal (the #200 unbound-L1 interaction
    yields zero AGGREGATES to surface)."""
    unit_id = getattr(projection, "unit_id", None)
    data_items = getattr(projection, "data_items", None) if projection is not None \
        else None
    aggregated = getattr(projection, "aggregated_endpoints", None) \
        if projection is not None else None
    cards: list[dict] = []
    for raw_card in surface:
        if not isinstance(raw_card, dict):
            # a malformed surface element degrades unchanged (fail-open)
            cards.append(raw_card)
            continue
        card = raw_card
        if not (_unit_matches_card(card, unit_id) and (data_items or aggregated)):
            cards.append(card)
            continue
        transformed = dict(card)
        transformed.pop("edge_degree", None)
        transformed["connected_data_items"] = {
            family: [_data_item_detail(item) for item in items]
            for family, items in sorted((data_items or {}).items())
        }
        if aggregated:
            transformed["aggregated_endpoints"] = sorted(
                (_aggregated_endpoint_detail(ep) for ep in aggregated),
                key=lambda d: (d.get("baseurl") or "", d.get("method") or "",
                               d.get("path") or "", d.get("service_slug") or ""),
            )
        cards.append(transformed)
    return cards


def _surface_context_for(surface, projection, *, applies_witness=None) -> dict:
    """The deterministic config surface-context assembly (#201, extended #298):
    the adapted index-card list (the `{"cards": [...]}` wrapper shape) with the
    config's target unit card expanded - `edge_degree` -> connected DataItems AND
    the aggregated L0 Endpoints under the parent unit - plus the candidate's
    applies-witness folded as `fault_evidence` (the former `l0_evidence` slot, so
    the config carries ONE L0-evidence field). Owned by the
    HARNESS (the deterministic typed-assembly ruling): the hypothesise mint and
    the ratify upsert both use it, so the model never re-authors the shape. An
    absent projection degrades to the card unchanged, an absent witness to no
    `fault_evidence` key (fail-open)."""
    out = {"cards": service_card_projection(surface, projection)}
    if applies_witness is not None:
        evidence: list[str] = []
        if applies_witness.deterministic is not None:
            evidence.append(f"deterministic: {applies_witness.deterministic}")
        if applies_witness.llm is not None:
            evidence.append(f"llm: {applies_witness.llm}")
        if evidence:
            out["fault_evidence"] = evidence
    return out


class SurfaceContextStore:
    """The orchestrator's store seam wrapper for the agent-sole write model
    (#294): the agent's `hunts_store(write)` tool call is the SOLE initiator of
    config/note persistence, and this wrapper applies the harness-owned,
    deterministic `surface_context` (#201 carve-out) on `write_config` /
    `update_config` before the write reaches the store - so the agent never
    authors the shape and a model-supplied `surface_context` is overwritten.

    The projection is per-unit (the current pair's projection), so the pass
    threads it per turn via `set_projection`; the surface is the pass's
    read-only index-card view. Every read method (reads, sibling reads) and the
    mover's `consume_config` are proxied unchanged; the note WRITE verbs
    (`append_note` / `update_note` / `delete_note`) are counted too, so
    `store_write_failures` keeps its meaning for every agent store write, not
    just the config writes. The `hunts_store` / `notes` tools bind to this
    wrapper exactly as they bind to the store.

    The wrapper is STABLE per run (`_SURFACE_STORES`) and `retarget`ed each pass
    to the current pass's raw store/surface, because the actor's tool surface
    captures the store seam only once; a fresh wrapper per pass would strand the
    actor on a stale seam.

    Fail-open canon preserved: a write that raises propagates to the caller
    (the tool degrades it fail-open, never into the turn); the wrapper only
    counts the observed failures for the report. A `DuplicateConfigError` is
    counted as both a write failure and a duplicate (G4) and re-raised so the
    tool can surface the deduplication signal."""

    def __init__(self, inner, *, surface=()):
        self._inner = inner
        self.surface = surface
        self._projection: object | None = None
        self._applies_witness: object | None = None
        self._prior_hunt_insights: object | None = None
        self._seed: tuple[str, str] | None = None
        self.write_failures = 0
        self.duplicate_config_writes = 0

    def retarget(self, *, inner, surface) -> None:
        """Point the stable per-run wrapper at the CURRENT pass's raw store and
        surface (#294 requirement 2). A `SurfaceContextStore` passed as `inner`
        is unwrapped, so the seam always delegates to the raw store; the
        per-pass counters and the per-turn projection/witness reset."""
        self._inner = inner._inner if isinstance(inner, SurfaceContextStore) else inner
        self.surface = surface
        self._projection = None
        self._applies_witness = None
        self._prior_hunt_insights = None
        self._seed = None
        self.reset_counters()

    def set_projection(self, projection, *, applies_witness=None,
                       prior_hunt_insights=None, seed=None) -> None:
        """Thread the current pair's rich projection, its applies-witness, the
        pair's orchestrator-assembled `prior_hunt_insights`, AND its hypothesise
        seeds `(rationale, research_direction)` onto the seam for the next turn
        (the surface context is per-unit, the witness folds into it as
        `fault_evidence`, and the prior-hunt insights + seeds are harness-held
        material - all are applied on the write seam, #201/#298).

        `seed` is the pair's minted `(rationale, research_direction)` - the
        symbolic layer's canonical hypothesise content. It is threaded at the
        RATIFY turn (the drafts exist there) so a ratify payload that omits or
        empties the seeds can never overwrite them on disk; it is None at the
        hypothesise turn (the draft does not exist before that turn, so the
        model authors the seeds directly)."""
        self._projection = projection
        self._applies_witness = applies_witness
        self._prior_hunt_insights = prior_hunt_insights
        self._seed = seed

    def reset_counters(self) -> None:
        """Zero the observed-write counters (the pass snapshots them)."""
        self.write_failures = 0
        self.duplicate_config_writes = 0

    def _inject(self, config):
        """Return a copy of `config` (a `HuntConfig` or a dict) carrying the
        harness-assembled deterministic `surface_context`, the pair's
        `prior_hunt_insights` (orchestrator-owned, #201/#298), AND the pair's
        hypothesise seeds `(rationale, research_direction)` when the seam threaded
        them; the caller's object is never mutated. The insights and seeds are
        applied only when the seam threaded them (a turn with no pair context
        leaves the config's own value untouched); a seed fills a MISSING/EMPTY
        payload slot, never overwrites a value the model authored."""
        context = _surface_context_for(
            self.surface, self._projection,
            applies_witness=self._applies_witness)
        insights = (list(self._prior_hunt_insights)
                    if self._prior_hunt_insights is not None else None)
        seed = self._seed
        if isinstance(config, dict):
            out = dict(config)
            out["surface_context"] = context
            if insights is not None:
                out["prior_hunt_insights"] = insights
            if seed is not None:
                if not out.get("rationale"):
                    out["rationale"] = seed[0]
                if not out.get("research_direction"):
                    out["research_direction"] = seed[1]
            return out
        amended = config.model_copy(deep=True)
        amended.surface_context = context
        if insights is not None:
            amended.prior_hunt_insights = insights
        if seed is not None:
            if not amended.rationale:
                amended.rationale = seed[0]
            if not amended.research_direction:
                amended.research_direction = seed[1]
        return amended

    def _counted(self, method, *args, **kwargs):
        """Call one inner store write, counting an observed failure (O3) and
        re-raising it to the caller (the tool degrades it fail-open)."""
        try:
            return method(*args, **kwargs)
        except DuplicateConfigError:
            self.write_failures += 1
            self.duplicate_config_writes += 1
            raise
        except Exception:
            self.write_failures += 1
            raise

    def write_config(self, project_id, config, **kwargs):
        return self._counted(
            self._inner.write_config, project_id, self._inject(config), **kwargs)

    def update_config(self, project_id, config, **kwargs):
        return self._counted(
            self._inner.update_config, project_id, self._inject(config), **kwargs)

    # The note write verbs are counted too, so `store_write_failures` covers
    # every agent store write (not only the config writes); the reads stay
    # proxied through `__getattr__`.
    def append_note(self, project_id, key, note, **kwargs):
        return self._counted(self._inner.append_note, project_id, key, note, **kwargs)

    def update_note(self, project_id, note_id, note, **kwargs):
        return self._counted(self._inner.update_note, project_id, note_id, note, **kwargs)

    def delete_note(self, project_id, note_id, **kwargs):
        return self._counted(self._inner.delete_note, project_id, note_id, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _surface_store_for(run_id: str, store, *, surface):
    """The STABLE per-run `SurfaceContextStore` for the pass's store seam
    (#294 requirement 2). ONE wrapper per `run_id` is created and `retarget`ed
    each pass to the current raw store/surface (counters/projection reset), so
    the actor's once-captured seam is always the current pass's. `None` stays
    `None` (a store-less pass)."""
    if store is None:
        return None
    with _ORCHESTRATOR_LOCK:
        wrapper = _SURFACE_STORES.get(run_id)
        if wrapper is None:
            inner = store._inner if isinstance(store, SurfaceContextStore) else store
            wrapper = SurfaceContextStore(inner, surface=surface)
            _SURFACE_STORES[run_id] = wrapper
        else:
            wrapper.retarget(inner=store, surface=surface)
        return wrapper


def hunt_id_for(unit_id: str, fault_class: str, vulnerability_class: str) -> str:
    """The DETERMINISTIC config hunt id (#298): a pure function of the identity
    triple `(unit_id, fault_class, vulnerability_class)` - the same identity the
    file name and the semantic key derive from. The former `uuid4` base plus the
    `-i` fan-out order element is REMOVED: it added a cross-run collision surface
    while carrying no information beyond the identity (each distinct class
    already has its own deterministic id)."""
    return semantic_key(unit_id, fault_class, vulnerability_class)


def mint_hunt_config(
    direction: EnvisionedDirection,
    *,
    surface_context: dict,
    prior_hunt_insights: Sequence[dict],
    observed_defences: Sequence[str] = (),
    preconditions: Sequence[str] = (),
    status: ConfigStatus = "hypothesised",
) -> list[HuntConfig]:
    """Mint the `HuntConfig` set (D3) for a carried direction - the typing-rework
    fan-out: ONE `HuntConfig` per distinct elicited `vulnerability_class` (the
    config's identity axis, spec 3.5), after the (LLM-owned, Q16) same-class
    merge. Each minted config is a HYPOTHESISED draft (default `status`): the
    top-level `rationale` / `research_direction` map the direction's
    hypothesise-phase seeds verbatim (rationale -> rationale, research_direction
    passes through), while the
    ratification-phase fields - `preconditions`, `observed_defences` - stay empty
    (the ratification phase fills them, R3.4). The wide surface context (adapted
    index-card, with the caller's applies-witness already folded as
    `fault_evidence` - the caller owns the candidate, so the mint takes no
    `candidate`; #298) and the downstream prior-hunt insights (the hunter
    memory's specs + Q16 pod exports by config_key, #202) are passed in
    pre-assembled. `tool_registry` is retired and `target_caveats` is renamed
    `observed_defences` (#202); `sub_fault_ids` is removed (#298).

    The mint stays deterministic given the emitted set (no LLM, no I/O): the
    distinct-class grouping preserves first-emission order, and each config's
    `hunt_id` is DERIVED from its identity (`hunt_id_for`, #298) - no caller base,
    no order element. A direction with NO elicited class markers - empty or
    absent `vulnerability_classes` - degrades to a single carried-bare draft: it
    still renders the hypothesise-phase seeds and the research direction, with an
    empty class identity (fail-open)."""
    classes = _distinct_vulnerability_classes(direction.vulnerability_classes)
    if not classes:
        # the carried-bare degrade: one config, no class identity
        classes = [""]
    configs: list[HuntConfig] = []
    for cls in classes:
        configs.append(HuntConfig(
            hunt_id=hunt_id_for(direction.unit_id, direction.fault_class, cls),
            unit_id=direction.unit_id,
            fault_class=direction.fault_class,
            status=status,
            vulnerability_class=cls,
            rationale=direction.rationale,
            research_direction=direction.research_direction,
            surface_context=surface_context,
            observed_defences=list(observed_defences),
            preconditions=list(preconditions),
            prior_hunt_insights=list(prior_hunt_insights),
        ))
    return configs


def build_back_edge_request(
    unit_id: str,
    fault_class: str,
    *,
    requester_id: str,
    note: str,
    job: str = _DEFAULT_BACK_EDGE_JOB,
) -> AnalyserReconRequest:
    """Build the park/resume back-edge request (IA-6/D9): the re-used
    interface-B contract with `origin="hunting"`, fault-agnostic on the wire
    (the fault joins via the correlation_id in the hunt store)."""
    return AnalyserReconRequest(
        job=job,
        scope=ReconScope(unit_id=unit_id, note=note),
        origin="hunting",
        correlation_id=uuid.uuid4().hex,
        requester_id=requester_id,
    )


async def _reap_orchestrator(run_id: str) -> None:
    """The module's stop path for the per-run orchestration actor (#110): reap
    and drop the actor AND the stable store-seam wrapper (#294) the registries
    hold for `run_id`, if any. Called by the runtime teardown (Task 6) - never
    by a pass's `finally`."""
    with _ORCHESTRATOR_LOCK:
        actor = _ORCHESTRATOR_ACTORS.pop(run_id, None)
        _SURFACE_STORES.pop(run_id, None)
    if actor is not None:
        try:
            await actor.stop()
        except Exception:  # noqa: BLE001 - teardown must never raise
            logger.warning("hunt-orchestrator actor reap failed for %s", run_id,
                           exc_info=True)


async def arun_orchestration(
    project_id: str,
    run_id: str,
    candidates: Sequence[DeliveredCandidate],
    tools: OrchestratorTools,
    *,
    hypothesise_fn: Callable[[GateInput], GateDecision] | None = None,
    ratify_fn: Callable[[PhaseTurnInput], RatifyDecision] | None = None,
    note_fn: Callable[[PhaseTurnInput], NoteDecision] | None = None,
    known_faults: Sequence[str] | None = None,
    exhausted_faults: Sequence[str] = (),
    orchestrator_factory: Callable[[str], "HuntOrchestratorActor"] | None = None,
) -> OrchestratorReport:
    """One orchestration pass, NATIVE-ASYNC (spec 4.1), driven by the #110 graph
    engine as reworked by #167: intake -> KB evidence -> surface read -> ONE
    supervisor-state schedule loop over the accepted FAULTS where every (unit,
    fault) pair runs the node-per-phase REASON stretch (`hypothesise -> ratify
    -> note`, G2). Under the agent-sole write model (#294) the harness does
    NOT persist configs or notes: the AGENT's `hunts_store(write)` /
    `notes(write, option="append")` tool calls are the sole writers (the
    hypothesise phase elicits the vulnerability classes and its tool write
    creates the status="hypothesised" drafts; the ratify phase's tool write
    upserts the final status - ratified or dropped, G6 dropped stays on disk;
    the note phase's tool write appends the notes). The deterministic mint still
    runs at the hypothesise phase to build the IN-MEMORY drafts that drive the
    phase flow and the report, but those drafts are never persisted by the
    harness. The #201 carve-out is preserved: the harness-owned deterministic
    `surface_context` is injected on the wrapped store seam before any agent
    write, so the agent never authors it. The graph ENDs at the REASON stretch
    - the dispatch node is REMOVED (G12) and the O9 budget stage is REMOVED
    (G7). Fail-open on every collaborator.

    The hunt-orchestrator is the async-native parent of the hunting effort
    (feat/async-actor-agents): when the phase seams are None (the production
    default) ONE `HuntOrchestratorActor` per run drives all three phase turns
    (hypothesise / ratify / note), serving EVERY pair of this pass (and of
    later passes on the same run) as inbox-request turns on the SAME
    `hunting_orchestrator` thread, so its checkpointed memory carries the
    pass's reasoning - PURELY stateful, exactly like the recon-orchestrator.
    The actor is held in the per-run registry and reaped only by the module's
    stop path.

    Every injected collaborator is called through `_await_seam` (an async seam
    is awaited; a sync seam is offloaded via `asyncio.to_thread`), so the pass
    never stalls the caller's event loop and sync fakes stay injectable.
    `hypothesise_fn`/`ratify_fn`/`note_fn` are injected (the production defaults
    are the actor turns); `tools` carries the store, the back-edge (retained
    for the runtime plane's dispatch ownership, G12), and the read-only graph
    view. The O1-O10 canon is single-sourced HERE;
    `run_orchestration` is its thin sync wrapper.
    """
    import asyncio
    import inspect

    orchestrator: "HuntOrchestratorActor | None" = None

    def _resolve_orchestrator() -> "HuntOrchestratorActor":
        nonlocal orchestrator
        if orchestrator is None:
            if orchestrator_factory is not None:
                orchestrator = orchestrator_factory(run_id)
            else:
                with _ORCHESTRATOR_LOCK:
                    actor = _ORCHESTRATOR_ACTORS.get(run_id)
                    if actor is None:
                        from polymerhus.attack.hunting.actors import HuntOrchestratorActor  # noqa: PLC0415
                        actor = HuntOrchestratorActor(run_id, tools=tools,
                                                      project_id=project_id)
                        _ORCHESTRATOR_ACTORS[run_id] = actor
                    orchestrator = actor
        # Arm the run's actor with THIS pass's tool seam bodies and project
        # root (#135): the actor binds them onto its session agent lazily on
        # first use, so the phase turns get the run's real seam bodies (and a
        # later pass on the same run re-arms its own).
        orchestrator.tools = tools
        orchestrator.project_id = project_id
        return orchestrator

    async def _await_seam(fn, *args):
        """Await an async seam, else offload a sync one to a worker thread.

        Async callables are awaited inline; sync ones run on a worker
        thread via `asyncio.to_thread`, and a sync seam that returns a
        coroutine has that coroutine awaited rather than handed back
        un-awaited."""
        if inspect.iscoroutinefunction(fn):
            return await fn(*args)
        out = await asyncio.to_thread(fn, *args)
        if inspect.isawaitable(out):  # a sync seam that RETURNS a coroutine
            return await out
        return out

    breaker = DegradedTurnBreaker.from_env()

    async def _phase_turn(fn, *args, phase: str):
        """Run ONE phase turn through the breaker (#280 Part 2): backoff before
        the call once the streak is past the warn threshold, per-turn fail-open
        for a raising/sync seam, then count a `None` (no-decision) outcome -
        which may abort the pass with a typed failure."""
        if fn is None:
            return None
        await breaker.before_turn(phase)
        try:
            out = await _await_seam(fn, *args)
        except PhaseAbort:
            raise
        except Exception as exc:  # noqa: BLE001 - fail-open: the turn is a no-decision
            logger.warning("%s turn failed (%s)", phase, exc)
            out = None
        breaker.record_outcome(phase, out)
        return out

    if hypothesise_fn is None:
        # The hypothesise turn rides the run's orchestration thread. The
        # actor's `hypothesise` is `async def`, so the default seam must be an
        # async lambda - a sync lambda would return the coroutine un-awaited and
        # `_await_seam` would hand it to to_thread (the un-awaited-coroutine
        # defect the live tier caught).
        hypothesise_fn = lambda inp: _resolve_orchestrator().hypothesise(inp)  # noqa: E731
    if ratify_fn is None:
        ratify_fn = lambda inp: _resolve_orchestrator().ratify(inp)  # noqa: E731
    if note_fn is None:
        note_fn = lambda inp: _resolve_orchestrator().note(inp)  # noqa: E731

    intake = normalize_candidates(candidates, known_faults=known_faults)
    if intake.malformed_dropped:
        logger.warning("%s malformed candidate(s) dropped (counted)", intake.malformed_dropped)

    if not intake.accepted:
        # Empty pass (O1): nothing for the phase machine to reason over.
        return OrchestratorReport(
            pairs_processed=0,
            configs_hypothesised=0,
            configs_ratified=0,
            configs_dropped=0,
            notes_written=0,
            duplicates_dropped=intake.duplicates_dropped,
            malformed_dropped=intake.malformed_dropped,
            pruned_by_verdict=intake.pruned_by_verdict,
            exhausted_faults=tuple(exhausted_faults),
            store_write_failures=0,
            duplicate_config_writes=0,
        )

    # KB evidence (D67-11): the duplicate symptom-technique retrieval seam is
    # RETIRED - the gate grounds via the direct fault-KB materialisation read
    # below (the CWE catalogue), never a second projection. The gate's
    # `kb_evidences`/`kb_degraded` slots stay as the empty/available defaults so
    # the phase-turn inputs and the prompt render keep their contract shape, and
    # the gate must never prune on degraded grounds.
    kb_evidences: dict[str, dict] = {}
    kb_degraded = False

    # The read-only graph surface (D67-04): grounding for the phase turns.
    surface: list[dict] = []
    if tools.graph_view is not None:
        try:
            surface = await _await_seam(tools.graph_view.index_cards)
        except Exception as exc:  # noqa: BLE001 - O5: degrade to an empty view
            logger.warning("graph view read failed, gate grounds degraded (%s)", exc)

    # The agent-sole write model (#294): the harness stops persisting configs /
    # notes itself; the agent's `hunts_store(write)` / `notes(write)` tool calls
    # are the sole writers. The #201 carve-out is preserved by wrapping the
    # store seam so every agent write carries the harness-assembled
    # deterministic `surface_context` (the projection is threaded per turn).
    # The wrapper is STABLE per run and retargeted here to THIS pass's raw
    # store/surface, so the actor's once-captured seam is always current.
    store_seam = _surface_store_for(run_id, tools.store_reads, surface=surface)
    tools.store_reads = store_seam

    # The #135 symbolic render's shared facets: the materialisation and
    # fold-family maps load ONCE per pass (static YAML reads) and are reused
    # across every fault. A failing read degrades the maps (each fault's slot
    # then renders UNKNOWN), never any single turn (C16).
    materialisations: dict = {}
    fold_families: dict = {}
    try:
        from polymerhus.attack.hunting.fault_kb import (  # noqa: PLC0415
            load_fold_families,
            load_materialisation,
        )
        materialisations = dict(load_materialisation())
        fold_families = dict(load_fold_families())
    except Exception as exc:  # noqa: BLE001 - fail-open, per-slot degrade
        logger.warning("fault-KB symbolic render degraded (%s)", exc)

    # --- The #110 graph engine -------------------------------------------------
    # Build the node closures over the canon helpers, compile IN-MEMORY per pass
    # (the durable memory stays in the actor's pooled session checkpointer and
    # the hunt store, the deterministic-pipeline discipline), and derive the
    # report deterministically from the intake counts + the returned trail.
    from polymerhus.attack.hunting.orchestrator_graph import (  # noqa: PLC0415
        build_hunting_graph,
    )

    by_identity = {(c.unit_id, c.fault_class): c for c in intake.accepted}

    # The per-fault schedule grouping (spec 3.1): ONE `FaultWorkItem` per
    # distinct `fault_class`, each holding that fault's FULL matched-unit list,
    # in RISK-DESCENDING order (the operator-authored tier policy,
    # `fault_risk.risk_tier` - broken access control first, then weak
    # validation, then sophisticated-system targets), stable within a tier so
    # equal-risk faults keep the deterministic first-emission intake order.
    # The pair-iteration decision (#167): the supervisor pops the fault and the
    # phase nodes iterate its candidate queue as the pairs they operate on.
    def _fault_schedule() -> list[FaultWorkItem]:
        grouped: dict[str, list[DeliveredCandidate]] = {}
        for c in intake.accepted:
            grouped.setdefault(c.fault_class, []).append(c)
        items = [FaultWorkItem(fault_class=f, candidates=grouped[f])
                 for f in grouped]
        return sorted(items, key=lambda item: risk_tier(item.fault_class))

    async def _read_prior_insights(key: str) -> list[dict]:
        """The downstream prior-hunt insights (G3, #202): the hunter memory's
        TestImplementationSpecs + the Q16 durable PodExport verdicts for the
        config key (a revival key or a semantic config_key), shallow-projected
        (I3 - never a full config/spec embedded). The read crosses to the
        hunter-memory SIBLING bucket under the same `data/<project_id>/` tree
        through the extended `store_reads` contract (`read_hunter_specs` /
        `read_hunter_notes`); O4 fail-open: a missing seam or a failing read
        degrades to an empty insight set, never aborts the hunt."""
        if tools.store_reads is None:
            return []
        try:
            specs_fn = getattr(tools.store_reads, "read_hunter_specs", None)
            notes_fn = getattr(tools.store_reads, "read_hunter_notes", None)
            specs = await _await_seam(specs_fn, project_id, key) \
                if callable(specs_fn) else []
            notes = await _await_seam(notes_fn, project_id, key) \
                if callable(notes_fn) else []
            return list(specs) + list(notes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("hunt store sibling read degraded for %s (%s)", key, exc)
            return []

    async def _persisted_configs(key: str) -> list[HuntConfig]:
        """The pair's PERSISTED configs for a revival/semantic key (the
        agent-sole phase flow, #294 requirement 3): the harness reads what the
        agent's `hunts_store(write)` actually landed instead of trusting its own
        in-memory mint. Fail-open per record and per read: a missing seam, a
        raising read, or a record that does not parse as a `HuntConfig`
        contributes nothing - never a raise into the pass (O4)."""
        if store_seam is None:
            return []
        reads = getattr(store_seam, "read_configs_by_key", None)
        if not callable(reads):
            return []
        try:
            records = await _await_seam(reads, project_id, key)
        except Exception as exc:  # noqa: BLE001 - O4
            logger.warning("hunt store persisted-config read degraded for %s (%s)",
                           key, exc)
            return []
        configs: list[HuntConfig] = []
        for record in records or []:
            try:
                configs.append(HuntConfig.model_validate(record))
            except Exception as exc:  # noqa: BLE001 - a malformed record degrades per record
                logger.warning(
                    "hunt store persisted config skipped for %s (unparseable "
                    "record): %s", key, exc)
                continue
        return configs

    async def _persisted_note_count(key: str) -> int:
        """How many notes the pair's key carries on disk (the agent-sole note
        ledger, #294 requirement 3). Fail-open to 0 (O4)."""
        if store_seam is None:
            return 0
        reads = getattr(store_seam, "read_notes", None)
        if not callable(reads):
            return 0
        try:
            notes = await _await_seam(reads, project_id, key)
        except Exception as exc:  # noqa: BLE001 - O4
            logger.warning("hunt store persisted-note read degraded for %s (%s)",
                           key, exc)
            return 0
        return len(notes or [])

    def _mint_for_direction(
        direction: EnvisionedDirection,
        candidate: DeliveredCandidate,
        prior_insights: Sequence[dict],
        projection=None,
    ) -> list[HuntConfig]:
        """The deterministic fan-out mint (D3/spec 3.5): ONE hypothesised
        `HuntConfig` draft per distinct elicited `vulnerability_class` (a
        class-less direction degrades to a single carried-bare draft), each
        config's hunt_id DERIVED from its identity (`hunt_id_for`, #298). Runs at
        the HYPOTHESISE phase to build the in-memory drafts the phase flow/report
        reason over (#294: the agent's `hunts_store(write)` tool call is the sole
        writer, so these drafts are NEVER persisted by the harness). The surface
        context is transformed at the mint: a Service card's edge_degree counts
        become the detailed connected DataItems from the unit's rich projection
        when the projection resolved them, and the candidate's applies-witness is
        folded in as `fault_evidence` (#298); an absent projection degrades to the
        counts card (fail-open). The ratification-phase fields (`preconditions`,
        `observed_defences`) stay empty on the hypothesised draft (R3.4)."""
        return mint_hunt_config(
            direction,
            surface_context=_surface_context_for(
                surface, projection, applies_witness=candidate.applies_witnesses),
            prior_hunt_insights=prior_insights,
            status="hypothesised",
        )

    def _phase_input(pair: DeliveredCandidate, configs: Sequence[HuntConfig],
                     state) -> PhaseTurnInput:
        """One ratify/note turn's input for the pair: the pair, its current
        configs, and the shared symbolic render slots (fail-open per slot).
        The pair's typed projection (built at the hypothesise phase and carried
        on the graph state) rides into the ratify turn so the proximity /
        too-near merging reasoning is grounded on it (S6); an absent slot
        degrades to None, never a prune signal."""
        fault_class = pair.fault_class
        projection = (state.get("projections") or {}).get(pair.unit_id)
        return PhaseTurnInput(
            pair=pair,
            configs=list(configs),
            kb_degraded=kb_degraded,
            kb_evidences=kb_evidences,
            surface=surface,
            projection=projection,
            unit_projection={pair.unit_id: projection}
            if projection is not None else {},
            materialisation={fault_class: materialisations.get(fault_class)},
            fold_family={fault_class: fold_families.get(fault_class)},
            prior_minted_keys=list(_ledger(state).minted_config_keys),
        )

    def _ledger(state) -> LoopLedger:
        prior = state.get("ledger")
        return prior.model_copy(deep=True) if isinstance(prior, LoopLedger) \
            else LoopLedger()

    def _pair_frame_for(pair: DeliveredCandidate) -> dict:
        """The pair's frame for the tool-call responses (G1): the (unit,
        fault) identity."""
        return pair_frame(pair.unit_id, pair.fault_class)

    async def _hypothesise_node(state) -> dict:
        """The HYPOTHESISE phase (Q8/spec 3.2): the pair's elicitation turn on
        the run's orchestration thread, then the deterministic mint fan-out
        builds the IN-MEMORY status="hypothesised" drafts that drive the phase
        flow and report. Under the agent-sole write model (#294) the agent's
        `hunts_store(write, status="hypothesised")` tool call is the sole
        writer - the harness never persists these drafts. The `hunts_store`
        tool's write response carried the NEXT_RATIFY_HINT constant (G1/G3); the
        loop state HYPOTHESISED is the graph's own (the wrapper sets it, G2).
        Fail-open (amended #186): a raising/empty turn SKIPS the pair (counted
        `units_skipped`) instead of minting a fully-empty draft - the
        actor-death fabrication is dead; a GENUINE carried-bare direction (the
        model emitted it: rationale present, class absent) still fans out to the
        carried-bare draft."""
        pair = state.get("current_pair")
        if pair is None:
            return {"trail": []}
        fault_class = pair.fault_class
        key = revival_key(pair.unit_id, fault_class)

        # The pair's own symbolic render (fail-open per slot: a raise/None
        # degrades that slot to None, never a prune - C16); materialisation +
        # fold family are per-FAULT and shared.
        projection: object | None = None
        if tools.graph_view is not None:
            from polymerhus.attack.hunting.unit_projection import (  # noqa: PLC0415
                build_projection,
            )
            try:
                projection = build_projection(
                    project_id, pair.unit_id, read_fn=tools.graph_view.read)
            except Exception as exc:  # noqa: BLE001 - per-pair degrade
                logger.warning("unit projection degraded for %s (%s)", key, exc)
        materialisation = materialisations.get(fault_class)
        fold_ids = fold_families.get(fault_class)
        # The Q11 novelty-reflection list: the CURRENT ledger's minted config
        # keys (fail-open to [] when the ledger slot is absent or not a
        # LoopLedger).
        prior_ledger = _ledger(state)
        gate_input = GateInput(
            candidates=[pair],
            kb_degraded=kb_degraded,
            kb_evidences=kb_evidences,
            surface=surface,
            projection=projection,
            unit_projection={pair.unit_id: projection},
            materialisation={fault_class: materialisation},
            fold_family={fault_class: fold_ids},
            prior_minted_keys=list(prior_ledger.minted_config_keys),
        )

        directions: list[EnvisionedDirection] = []
        from polymerhus.attack.hunting.orchestrator_tracing import (  # noqa: PLC0415
            trace_gate_step,
        )
        # Convergence: no hand-written gate span - the pass trace rides the
        # handler (actor turns carry the run tag); each step below carries its
        # own explicit run correlation.
        _gate_tags = ["attack", "hunting", "orchestrator-gate"]
        trace_gate_step("symbolic-render", run_id=run_id, tags=_gate_tags, input={
            "pair": key,
            "projection": "ok" if projection is not None else "UNKNOWN",
            "materialisation": "ok" if materialisation is not None else "UNKNOWN",
            "fold_family": "ok" if fold_ids is not None else "UNKNOWN",
            "kb_degraded": kb_degraded,
        })
        # The pair's orchestrator-assembled prior-hunt insights (fail-open []):
        # harness-owned downstream material applied on the write seam (#201/#298)
        # so the agent's `hunts_store(write)` carries them without authoring them.
        prior_insights = await _read_prior_insights(key)
        if hypothesise_fn is not None:
            if store_seam is not None:
                # The #201 carve-out is threaded per turn: the agent's
                # `hunts_store(write)` during this turn gets the pair's own
                # projection (the surface context is per-unit), its
                # applies-witness folded as `fault_evidence`, and the pair's
                # prior-hunt insights (#298).
                store_seam.set_projection(
                    projection, applies_witness=pair.applies_witnesses,
                    prior_hunt_insights=prior_insights)
            decision = await _phase_turn(hypothesise_fn, gate_input,
                                         phase="hypothesise")
            directions = list(getattr(decision, "directions", None) or [])
            if decision is not None:
                trace_gate_step("gate-decision", run_id=run_id, tags=_gate_tags, output={
                    "directions": [{
                        "pair": revival_key(d.unit_id, d.fault_class),
                        "carried": bool(d.carried),
                        "rationale": d.rationale,
                        "research_direction": d.research_direction,
                        "vulnerability_classes": list(
                            d.vulnerability_classes),
                    } for d in directions],
                    "prior_minted_keys": list(gate_input.prior_minted_keys),
                })
        # #186 anti-fabrication: an empty decision (a failed/None turn) NEVER
        # mints a harness-fabricated fully-empty draft - the pair flows to the
        # skip branch below (counted `units_skipped`). Only a direction the
        # model genuinely EMITTED (carried, with a rationale) reaches the mint;
        # its class-less degrade is the legit carried-bare draft (spec 3.5).

        # --- the hypothesise mint (spec 3.3, in-memory only, #294) -----------
        # The agent's `hunts_store(write, status='hypothesised')` tool call is
        # the SOLE writer; the deterministic mint below only builds the
        # in-memory drafts the phase flow reasons over and is NEVER persisted by
        # the harness. A missing agent write means no artifact on disk.
        carried = [d for d in directions if d.carried]
        trail = [
            {"kind": "gate_pruned",
             "revival_key": revival_key(d.unit_id, d.fault_class)}
            for d in directions if not d.carried
        ]
        ledger = prior_ledger
        minted = dict(state.get("minted_configs") or {})
        configs_minted = 0
        if not carried:
            ledger.units_skipped += 1
            return {"ledger": ledger, "minted_configs": minted, "trail": trail,
                    "projections": {pair.unit_id: projection}}
        candidate = by_identity.get((pair.unit_id, fault_class)) or pair
        for direction in carried:
            configs = _mint_for_direction(
                direction, candidate, prior_insights, projection=projection)
            # S8: several carried directions for ONE pair all sit at the SAME
            # locus key (the pair's (unit, fault)) - accumulate the union into
            # `minted[key]` (never overwrite), so every draft enters the
            # ratify set instead of earlier drafts being orphaned
            # forever-hypothesised.
            minted.setdefault(key, []).extend(configs)
            trace_gate_step("emit-mint", run_id=run_id, tags=_gate_tags, input={
                "revival_key": key,
                "configs": len(configs),
                "classes": sorted(cfg.vulnerability_class for cfg in configs),
            })
            configs_minted += len(configs)
        ledger.minted_config_keys.append(key)
        ledger.units_done += 1
        trail.append({"kind": "hypothesised", "revival_key": key,
                      "configs": configs_minted})
        return {"ledger": ledger, "minted_configs": minted, "trail": trail,
                "projections": {pair.unit_id: projection}}

    async def _ratify_node(state) -> dict:
        """The RATIFY phase (spec 3.2): the pair's ratification turn on the run's
        orchestration thread. The agent may update/delete/create configs and
        MUST end with a status="ratified" write carrying the filled
        preconditions/observed_defences; the agent's `hunts_store(write)` tool
        call is the SOLE writer (the harness never re-persists the decision, so
        no second write lands - #294). The `hunts_store` tool's ratified-write
        response carried ONLY the NEXT_NOTE_HINT constant (G1); the loop state
        RATIFIED is the graph's own. The "must END with ratified" contract (S2):
        a decision entry RETURNED without status="ratified" (still hypothesised)
        is NOT counted ratified and is NOT fed to the note phase. Fail-open: a
        raising/empty turn skips the phase's side effect (the drafts stay
        hypothesised) but the pair keeps serving.

        The #201 carve-out is preserved: the wrapped store seam injects the
        deterministic `surface_context` on the agent's write, so a model-authored
        shape is overwritten (the projection is threaded before the turn)."""
        pair = state.get("current_pair")
        if pair is None:
            return {"trail": []}
        key = revival_key(pair.unit_id, pair.fault_class)
        drafts = list((state.get("minted_configs") or {}).get(key) or [])
        if not drafts:
            # S5: a pair with no drafts (the gate pruned everything) has no
            # ratification work - skip the seam turn entirely, keep serving.
            return {"trail": []}

        decision = RatifyDecision()
        if ratify_fn is not None:
            if store_seam is not None:
                # #201 carve-out: thread the pair's own projection onto the
                # seam for the ratify turn, so the agent's write carries the
                # deterministic surface context (aggregates re-injected) with the
                # pair's applies-witness folded as `fault_evidence` and its
                # prior-hunt insights (#298). The insights AND the hypothesise
                # seeds ride the minted drafts (assembled at the hypothesise
                # phase for the same pair): a ratify payload that omits/empties
                # `rationale` / `research_direction` can never lose them (the
                # symbolic layer owns the pair's canonical seeds).
                store_seam.set_projection(
                    (state.get("projections") or {}).get(pair.unit_id),
                    applies_witness=pair.applies_witnesses,
                    prior_hunt_insights=(drafts[0].prior_hunt_insights
                                         if drafts else None),
                    seed=((drafts[0].rationale, drafts[0].research_direction)
                          if drafts else None))
            out = await _phase_turn(ratify_fn, _phase_input(pair, drafts, state),
                                    phase="ratify")
            decision = out if isinstance(out, RatifyDecision) else RatifyDecision()

        trail: list[dict] = []
        ratified = dropped = unratified = 0
        for config in decision.configs:
            if config.status == "ratified":
                ratified += 1
                trail.append({"kind": "ratified", "revival_key": key})
            elif config.status == "dropped":
                dropped += 1
                trail.append({"kind": "dropped", "revival_key": key})
            else:
                # S2: returned-unratified (still hypothesised) - the turn did
                # NOT end with ratified, so the config is never counted
                # ratified and never noted over; the draft stays hypothesised
                # on disk (the pair is still ratifying).
                unratified += 1
                trail.append({"kind": "unratified", "revival_key": key})
        if decision.configs:
            trail.append({"kind": "ratify-ended", "revival_key": key,
                          "ratified": ratified, "dropped": dropped,
                          "unratified": unratified})
        return {"trail": trail}

    async def _note_node(state) -> dict:
        """The NOTE phase (spec 3.2/G8): the pair's note-taking turn on the
        run's orchestration thread. The agent's `notes(write, option='append')`
        tool call is the SOLE note writer (#294): the harness never appends the
        decision's notes, and the note frame is the pair's PERSISTED ratified
        configs. The `notes` tool's append response carried the NEXT pair's data
        + the NEXT_PAIR_HINT constant - the pair's loop ENDS there (G1); the
        loop state NOTED is the graph's own (a LOOP state, never a config
        status - G5). Fail-open: a raising/empty turn skips the phase's side
        effect but the pair keeps serving."""
        pair = state.get("current_pair")
        if pair is None:
            return {"trail": []}
        key = revival_key(pair.unit_id, pair.fault_class)
        # #294 requirement 3: the note frame is built by READING the configs the
        # agent actually persisted through `hunts_store(write, status=...)` - the
        # harness no longer trusts its own in-memory set, so a missing agent
        # write means nothing to note over (fail-open, never a backfill).
        persisted = await _persisted_configs(key)
        ratified = [config for config in persisted if config.status == "ratified"]
        if not ratified:
            # a pair with no ratified config on disk (the agent never wrote, it
            # wrote only dropped configs, or all returned-unratified - S2) has
            # nothing to note: the phase skips its side effect but the loop
            # state NOTED still advances (G5).
            return {"trail": []}
        if getattr(tools, "phase_context", None) is not None:
            # The pair end: the notes tool's response carries the next pair's
            # frame + NEXT_PAIR_HINT (G1). The next pair is the queue head the
            # supervisor will pop next; at a fault DRAIN (the current fault's
            # queue is empty but the schedule holds another fault) it is the
            # next fault's first candidate (S3).
            next_pairs = list(state.get("pairs") or [])
            if not next_pairs:
                schedule = list(state.get("schedule") or [])
                if schedule:
                    next_fault_candidates = getattr(schedule[0], "candidates", None)
                    if next_fault_candidates:
                        next_pairs = [next_fault_candidates[0]]
            tools.phase_context.next_pair = _pair_frame_for(next_pairs[0]) \
                if next_pairs else None

        # The agent's `notes(write, option='append')` tool call is the SOLE note
        # writer; the ledger counts what actually landed on disk (a before/after
        # delta), never the harness's own append (#294).
        notes_before = await _persisted_note_count(key)
        if note_fn is not None:
            await _phase_turn(note_fn, _phase_input(pair, ratified, state),
                              phase="note")
        notes_after = await _persisted_note_count(key)
        notes_written = max(0, notes_after - notes_before)

        ledger = _ledger(state)
        trail: list[dict] = []
        if notes_written:
            from polymerhus.attack.hunting.orchestrator_tracing import (  # noqa: PLC0415
                trace_gate_step,
            )
            ledger.notes_recorded += 1
            trace_gate_step("note-written", run_id=run_id,
                            tags=["attack", "hunting", "orchestrator-gate"],
                            input={"revival_key": key})
            trail.append({"kind": "note", "revival_key": key,
                          "notes": notes_written})
        return {"ledger": ledger, "trail": trail}

    initial = {
        "project_id": project_id,
        "run_id": run_id,
        "schedule": _fault_schedule(),
        "current": None,
        "pairs": [],
        "current_pair": None,
        "loop_state": None,
        "loop_states": [],
        "trail": [],
        "ledger": LoopLedger(),
        "minted_configs": {},
        "projections": {},
        "kb_evidences": kb_evidences,
        "kb_degraded": kb_degraded,
        "surface": surface,
        "tools": tools,
        "store_reads": tools.store_reads,
        "hypothesise_fn": hypothesise_fn,
        "ratify_fn": ratify_fn,
        "note_fn": note_fn,
        "exhausted_faults": tuple(exhausted_faults),
    }
    graph = build_hunting_graph(
        hypothesise_node=_hypothesise_node,
        ratify_node=_ratify_node,
        note_node=_note_node,
    )
    terminal = await graph.compile().ainvoke(
        initial, {"configurable": {"thread_id": run_id}},
    )
    trail = list(terminal.get("trail") or [])
    ledger = terminal.get("ledger") or LoopLedger()
    ratified_events = [t for t in trail if t.get("kind") == "ratify-ended"]
    return OrchestratorReport(
        pairs_processed=ledger.units_done + ledger.units_skipped,
        configs_hypothesised=sum(t.get("configs", 0) for t in trail
                                 if t.get("kind") == "hypothesised"),
        configs_ratified=sum(t.get("ratified", 0) for t in ratified_events),
        configs_dropped=sum(t.get("dropped", 0) for t in ratified_events),
        configs_unratified=sum(t.get("unratified", 0) for t in ratified_events),
        notes_written=sum(t.get("notes", 0) for t in trail
                          if t.get("kind") == "note"),
        duplicates_dropped=intake.duplicates_dropped,
        malformed_dropped=intake.malformed_dropped,
        pruned_by_verdict=intake.pruned_by_verdict,
        gate_pruned=tuple(t["revival_key"] for t in trail if t.get("kind") == "gate_pruned"),
        exhausted_faults=tuple(exhausted_faults),
        # The agent-sole write counters (#294): observed on the wrapped store
        # seam (the agent's tool calls), never incremented by the harness.
        store_write_failures=store_seam.write_failures if store_seam else 0,
        duplicate_config_writes=(
            store_seam.duplicate_config_writes if store_seam else 0),
        ledger=ledger,
    )


def run_orchestration(
    project_id: str,
    run_id: str,
    candidates: Sequence[DeliveredCandidate],
    tools: OrchestratorTools,
    *,
    hypothesise_fn: Callable[[GateInput], GateDecision] | None = None,
    ratify_fn: Callable[[PhaseTurnInput], RatifyDecision] | None = None,
    note_fn: Callable[[PhaseTurnInput], NoteDecision] | None = None,
    known_faults: Sequence[str] | None = None,
    exhausted_faults: Sequence[str] = (),
    orchestrator_factory: Callable[[str], "HuntOrchestratorActor"] | None = None,
) -> OrchestratorReport:
    """The SYNC lane to one orchestration pass: a thin wrapper that runs the
    native-async `arun_orchestration` to completion, so the O1-O10 canon is
    single-sourced and never re-implemented.

    Sync seams (the legacy injected `invoke_role`-backed factories, test fakes)
    travel through `asyncio.to_thread` inside the canon; async seams (the
    actor-backed defaults) are awaited natively. When called from a running
    event loop, `run_coro_blocking` runs the pass on a separate thread so
    `asyncio.run` is never re-entered on the caller's loop. The return is
    identical to `arun_orchestration`'s.
    """
    from polymerhus.recon.control.async_bridge import run_coro_blocking  # noqa: PLC0415

    return run_coro_blocking(arun_orchestration(
        project_id,
        run_id,
        candidates,
        tools,
        hypothesise_fn=hypothesise_fn,
        ratify_fn=ratify_fn,
        note_fn=note_fn,
        known_faults=known_faults,
        exhausted_faults=exhausted_faults,
        orchestrator_factory=orchestrator_factory,
    ))
