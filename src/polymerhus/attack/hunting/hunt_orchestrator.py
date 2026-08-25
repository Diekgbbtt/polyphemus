"""The hunt-orchestrator (#82): the central memory of the hunting effort.

Consumes the FaultSource candidate set (IA-1, spec 4.1) and runs the REASON
stretch as a NODE-PER-PHASE workflow graph (the #167 rework of #110's graph
engine): the supervisor pops FAULT work items (the fault stays the schedule
unit, spec 3.1) and iterates each fault's candidate queue as the pairs the
phase nodes operate on; every (unit, fault) pair runs `hypothesise -> ratify
-> note` as graph nodes with the transition logic embedded in the graph (G2)
and the phase-transition verbatims injected on-the-fly in the specific
tool-call responses (constants, never the system prompt - G1/G3). The
hypothesise phase elicits one or more vulnerability classes and WRITES the
status="hypothesised" draft (the deterministic mint from #165 is called at
this phase, via the `hunts_store` tool); the ratify phase may update/delete/
create configs and MUST end with a status="ratified" write carrying the filled
capabilities/assumptions/technique-primitives; the note phase writes the notes
and the pair's loop ENDs at the note tool's response (the next pair + the
restart verbatim). The dispatch node is REMOVED (G12) and the O9 budget stage
is REMOVED (G7): the graph ENDs at the REASON stretch - dispatch state and
spending are the runtime plane's and the pod's ownership. It never writes
L0/L1 (its graph access is the read-only view, D67-04); the hunting agent
(#83), not this module, is the test-DESIGN actor.

The pass runs NATIVE-ASYNC (feat/async-actor-agents) on the #110 GRAPH engine:
`arun_orchestration` is the single O1-O10 canon and its body IS a
supervisor-state schedule loop (the ONE flexible StateGraph in
`orchestrator_graph.py`) - per fault, the stateful phase turns run on the
run's `HuntOrchestratorActor` thread (`hunting_orchestrator` session,
monotonic across ALL faults and pairs), and the harness persists the configs
into the store's `produced/` and the notes into `memory.yaml`. Each node
closure delegates to the canon helpers in THIS module; the O1-O10 seam shapes
stay single-sourced here. `run_orchestration` is its thin sync wrapper.

The actor is the PURELY STATEFUL parent, exactly like the recon-orchestrator -
but it now LIVES in a per-run registry (`_ORCHESTRATOR_ACTORS`) instead of being
reaped in a pass's `finally` (#110): the SAME `HuntOrchestratorActor` (same
thread) serves every pair of a pass and stays live listening between passes;
the module's runtime stop path (Task 6) reaps it.

Degradations are the spec's failure canon: KB unavailable -> the gate reasons
degraded, never prunes (D67-11); a raising hypothesise turn carries the pair
bare (fail-open, the old gate-carry); a raising ratify/note turn skips that
phase's side effect but the pair keeps serving (the phase machine degrades
gracefully); store write failure -> warning and a count (O3, a duplicate-config
write is the deduplication signal and lands the same O3 path - G4); store read
failure -> empty prior insights (O4); a malformed candidate is dropped and
counted (O10). Fail-open throughout: one bad collaborator never aborts the
pass.

This module imports no driver and performs no I/O at import; the graph read
seam resolves lazily on first call (CODING_STANDARD section 6).
"""
from __future__ import annotations

import logging
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
    "merging, then run the adversarial_capabilities (the test's preconditions "
    "- the attacker's existing capabilities the test needs, never "
    "post-exploitation capabilities) / assumptions / technique-primitives "
    "analysis. End ratification with a hunts_store write carrying "
    "status='ratified'."
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

# The default targeted job a park/resume back-edge runs (a re-witness of the
# unit's surface); the agent's inline needs carry their own job.
_DEFAULT_BACK_EDGE_JOB = "httpx_reprofile"

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
    rationale, assumptions, and envisioned test primitives that stub the
    hunting agent's later, more concrete hypothesis (Q8), plus the
    candidates-rewrite class-level `research_direction` (verbatim prose, never
    narrowed to a surface locale / payload / vector / symptom). As of the
    HuntConfig typing rework the direction is the ELICITATION CARRIER: it rides
    the `vulnerability_classes` the mint fans out into ONE `HuntConfig` per
    distinct class (the class is the config's identity axis); the concrete-fault
    stretch (`supposed_payload_vectors`, per-candidate capability/blocker
    analysis) is the #164 hunter's DECOMPOSE/GENERATE ownership, never this
    carrier's."""

    unit_id: str
    fault_class: str
    carried: bool = True
    rationale: str = ""
    assumptions: list[str] = Field(default_factory=list)
    envisioned_test_primitives: list[str] = Field(default_factory=list)
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
    filled ratification fields. The harness persists them (update in place /
    dropped-on-disk, G6); the model-facing writes ride the `hunts_store`
    tool's `write` cmd."""

    configs: list["HuntConfig"] = Field(default_factory=list)


class NoteDecision(BaseModel):
    """The note phase's outcome: the notes the pair writes. The harness
    appends them idempotently; the model-facing write rides the `notes` tool,
    whose response carries the next pair + the NEXT_PAIR_HINT constant (G1)."""

    notes: list[NoteRecord] = Field(default_factory=list)


class HuntPromptTemplate(BaseModel):
    """Part 1 of the five-part HuntConfig parameter set (Q8/D3): the fault-matching
    rationale, the L0 fault-applicability evidence, and the class-level
    `research_direction` - the hypothesise-phase content of the config. The
    capability/assumption/technique-primitive analysis is NOT a template slot
    anymore: it rides the config level (`HuntConfig.adversarial_capabilities` /
    `assumptions` / `technique_primitives`, the ratification-phase fields), and
    the concrete-fault slots (`extension_points`, `supposed_payload_vectors`,
    per-class candidates) are removed - the #164 hunter owns that stretch."""

    rationale: str = ""
    l0_evidence: list[str] = Field(default_factory=list)
    research_direction: str = ""


class HuntConfig(BaseModel):
    """The declarative config the hunting agent consumes (D3): the five-part
    parameter set - prompt template, wide surface context (adapted index-card,
    a Service's edge_degree transformed to its connected DataItems), target
    caveats, prior-hunt insights (by revival key), tool registry - plus the
    orchestrator's stretch as of the typing rework: `status` (the config
    lifecycle `hypothesised -> ratified | dropped`; the mint writes
    hypothesised drafts), `vulnerability_class` (the config's identity axis,
    one config per elicited class), and the ratification-phase fields
    (`adversarial_capabilities` / `assumptions` / `technique_primitives`,
    empty on the hypothesised draft). `sub_fault_ids` carries the folded
    fault_ids (the sub-faults / reflection material) captured under the parent
    `fault_class` from the fold-family relation
    (`fault_kb.load_fold_families`): the hunting agent bounds the parent fault,
    the sub-faults are consideration material."""

    hunt_id: str
    unit_id: str
    fault_class: str
    status: ConfigStatus = "hypothesised"
    vulnerability_class: str = ""
    sub_fault_ids: list[str] = Field(default_factory=list)
    prompt_template: HuntPromptTemplate
    surface_context: dict = Field(default_factory=dict)
    target_caveats: list[str] = Field(default_factory=list)
    prior_hunt_insights: list[dict] = Field(default_factory=list)
    tool_registry: list[dict] = Field(default_factory=list)
    adversarial_capabilities: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    technique_primitives: list[str] = Field(default_factory=list)


class DispatchResult(BaseModel):
    """One hunting-agent dispatch outcome (IA-2): the delivered refs plus the
    hypothesis verdict and NL feedback (D11), or the inline back-edge needs."""

    spec_ref: str | None = None
    pod_result_ref: str | None = None
    hypothesis_verdict: str | None = None
    feedback: str | None = None
    back_edge_needs: list[AnalyserReconRequest] = Field(default_factory=list)


class MatchVerdict(BaseModel):
    """The re-match outcome after a back-edge: still three-valued (D2)."""

    unit_id: str
    fault_class: str
    verdict: Literal["applies", "does-not-apply", "insufficient-evidence"]


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
    `store_write_failures` counter."""

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
    `hunts_store` and `notes` bind to, plus the prior-config/notes reads), the
    read-only graph view (`graph_view` - the surface `graph_view` defers to
    for the projected context: the store tools only ever read service keys),
    and the run-local `phase_context` the note phase node sets so the notes
    tool's response carries the next pair's frame (G1). `back_edge` is
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


def _prior_config_insight(config: dict) -> dict:
    """The shallow projection of a prior persisted config embedded as a
    prior-hunt insight (I3): identity + the hypothesise-phase seeds only
    (`unit_id`, `fault_class`, `vulnerability_class`, `status`,
    `sub_fault_ids`, and the `prompt_template` rationale / research_direction),
    never the full `model_dump`. A persisted config's `prior_hunt_insights`
    must never contain a nested `prior_hunt_insights` key - the full-dump
    merge would embed pass N-1's config inside pass N's config and snowball
    without bound. Present keys only; absent seeds stay absent (a carried-bare
    degrade has no class)."""
    template = config.get("prompt_template")
    if not isinstance(template, dict):
        template = {}
    out: dict = {}
    for key in ("unit_id", "fault_class", "vulnerability_class",
                "status", "sub_fault_ids"):
        if config.get(key) is not None:
            out[key] = config[key]
    for key in ("rationale", "research_direction"):
        if template.get(key) is not None:
            out[key] = template[key]
    return out


def normalize_candidates(
    candidates: Sequence[DeliveredCandidate],
    known_faults: Sequence[str] | None = None,
) -> CandidateIntake:
    """Dedup by `(unit_id, fault_class)` identity (O7), drop malformed
    candidates counted (O10: a candidate with no witness - or an unknown fault
    class when a registry is given), and apply the match-verdict prune signal
    (Q8 level 1): a does-not-apply candidate is pruned before the gate - never
    pruned on a rejection, only a missing witness drops it."""
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
        if witnesses is None or witnesses.llm is None:
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


def _surface_cards_with_connected_data_items(
    surface: Sequence[Any], projection,
) -> list[Any]:
    """The config surface-context transform (ADR G5, operator correction): a
    Service card's `edge_degree` counts are replaced by the detailed connected
    DataItems (name/type/sensitivity/fields/notes) of the unit's rich
    projection, mirroring the projection reader - the slot becomes
    `connected_data_items` (family -> the item details, families and fields
    sorted for render determinism). The transform applies only to the card of
    the projection's own unit (the config's target); an absent projection, a
    non-matching card, a projection that resolved no data items, or a malformed
    card (a non-dict surface element) degrades to the card unchanged - fail-open
    per the canon, never a raise, never a prune signal."""
    unit_id = getattr(projection, "unit_id", None)
    data_items = getattr(projection, "data_items", None) if projection is not None \
        else None
    cards: list[dict] = []
    for raw_card in surface:
        if not isinstance(raw_card, dict):
            # a malformed surface element degrades unchanged (fail-open)
            cards.append(raw_card)
            continue
        card = raw_card
        key = card.get("key")
        key = key if isinstance(key, dict) else {}
        slug = key.get("business_function_slug")
        if not (card.get("kind") == "Service" and isinstance(slug, str) and slug
                and unit_id == f"Service:{slug}" and data_items):
            cards.append(card)
            continue
        transformed = dict(card)
        transformed.pop("edge_degree", None)
        transformed["connected_data_items"] = {
            family: [_data_item_detail(item) for item in items]
            for family, items in sorted(data_items.items())
        }
        cards.append(transformed)
    return cards


def mint_hunt_config(
    direction: EnvisionedDirection,
    candidate: DeliveredCandidate,
    hunt_id: str,
    *,
    surface_context: dict,
    prior_hunt_insights: Sequence[dict],
    tool_registry: Sequence[dict],
    target_caveats: Sequence[str] = (),
    sub_fault_ids: Sequence[str] = (),
    status: ConfigStatus = "hypothesised",
) -> list[HuntConfig]:
    """Mint the five-part `HuntConfig` set (D3) for a carried direction - the
    typing-rework fan-out: ONE `HuntConfig` per distinct elicited
    `vulnerability_class` (the config's identity axis, spec 3.5), after the
    (LLM-owned, Q16) same-class merge. Each minted config is a HYPOTHESISED
    draft (default `status`): the prompt template maps the direction's
    hypothesise-phase seeds verbatim (rationale -> rationale, the L0
    fault-applicability evidence from the candidate's witnesses, research_direction
    passes through), while the ratification-phase fields - `adversarial_capabilities`,
    `assumptions`, `technique_primitives` - stay empty. The remaining
    parameter-set slots - the wide surface context (adapted index-card), the
    target caveats, the prior-hunt insights, and the fault-targeting tool
    registry - and `sub_fault_ids` (the folded fault_ids captured under the
    parent `fault_class` by the fold-family relation, #135) are unchanged.

    The mint stays deterministic given the emitted set (no LLM, no I/O): the
    distinct-class grouping preserves first-emission order, and config hunt_ids
    derive from the single `hunt_id` base (the first config keeps the base, the
    i-th fan-out config gets `base-<i>`). A direction with NO elicited class
    markers - empty or absent `vulnerability_classes` - degrades to a single
    carried-bare draft: it still renders the hypothesise-phase seeds and the
    research direction, with an empty class identity (fail-open)."""
    evidence: list[str] = []
    if candidate.applies_witnesses.deterministic is not None:
        evidence.append(f"deterministic: {candidate.applies_witnesses.deterministic}")
    if candidate.applies_witnesses.llm is not None:
        evidence.append(f"llm: {candidate.applies_witnesses.llm}")
    classes = _distinct_vulnerability_classes(direction.vulnerability_classes)
    if not classes:
        # the carried-bare degrade: one config, no class identity
        classes = [""]
    configs: list[HuntConfig] = []
    for index, cls in enumerate(classes):
        config_id = hunt_id if index == 0 else f"{hunt_id}-{index}"
        configs.append(HuntConfig(
            hunt_id=config_id,
            unit_id=direction.unit_id,
            fault_class=direction.fault_class,
            status=status,
            vulnerability_class=cls,
            sub_fault_ids=list(sub_fault_ids),
            prompt_template=HuntPromptTemplate(
                rationale=direction.rationale,
                l0_evidence=evidence,
                research_direction=direction.research_direction,
            ),
            surface_context=surface_context,
            target_caveats=list(target_caveats),
            prior_hunt_insights=list(prior_hunt_insights),
            tool_registry=list(tool_registry),
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


def _registry_from_kb(kb_entry: dict) -> list[dict]:
    """The fault-targeting tool registry from a KB retrieval (D10): the entry's
    probing techniques, one registry row each."""
    techniques = (kb_entry or {}).get("probing_techniques", [])
    if isinstance(techniques, list):
        return [{"technique": t} for t in techniques if t]
    return []


async def _reap_orchestrator(run_id: str) -> None:
    """The module's stop path for the per-run orchestration actor (#110): reap
    and drop the actor the registry holds for `run_id`, if any. Called by the
    runtime teardown (Task 6) - never by a pass's `finally`."""
    with _ORCHESTRATOR_LOCK:
        actor = _ORCHESTRATOR_ACTORS.pop(run_id, None)
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
    kb_retrieve_fn: Callable[[str], dict] | None = None,
    known_faults: Sequence[str] | None = None,
    exhausted_faults: Sequence[str] = (),
    orchestrator_factory: Callable[[str], "HuntOrchestratorActor"] | None = None,
) -> OrchestratorReport:
    """One orchestration pass, NATIVE-ASYNC (spec 4.1), driven by the #110 graph
    engine as reworked by #167: intake -> KB evidence -> surface read -> ONE
    supervisor-state schedule loop over the accepted FAULTS where every (unit,
    fault) pair runs the node-per-phase REASON stretch (`hypothesise -> ratify
    -> note`, G2). The hypothesise phase elicits the vulnerability classes and
    WRITES the status="hypothesised" drafts (the deterministic mint is called
    at this phase, via the `hunts_store` tool); the ratify phase persists the
    configs at their final status (ratified or dropped - G6, dropped stays on
    disk); the note phase appends the notes. The graph ENDs at the REASON
    stretch - the dispatch node is REMOVED (G12) and the O9 budget stage is
    REMOVED (G7). Fail-open on every collaborator.

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
    `hypothesise_fn`/`ratify_fn`/`note_fn`/`kb_retrieve_fn` are injected (the
    production defaults are the actor turns); `tools` carries the store, the
    back-edge (retained for the runtime plane's dispatch ownership, G12), and
    the read-only graph view. The O1-O10 canon is single-sourced HERE;
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
        """Await an async seam, else offload a sync one to a worker thread
        (mirrors the recon pipeline's `_phase_exclusions` seam dispatch)."""
        if inspect.iscoroutinefunction(fn):
            return await fn(*args)
        out = await asyncio.to_thread(fn, *args)
        if inspect.isawaitable(out):  # a sync seam that RETURNS a coroutine
            return await out
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

    write_failures = 0
    duplicate_config_writes = 0

    def _write_config(config) -> str | None:
        """Persist one hypothesised draft into the project's `produced/` (the
        hypothesise write, memory-system spec 3.2). IDEMPOTENT against the
        model's own `hunts_store(write)` call during the same turn: when the
        config's identity is already on disk, the harness records only (the
        tool already persisted it) - never a second file, never a spurious
        duplicate count. A FAILING identity read never blocks the write (a
        degraded store still persists - the read is only the deduplication
        optimisation, O4). A genuine `DuplicateConfigError` (a re-elicitation
        the tool itself surfaced as the deduplication signal, G4) warns and
        counts; the pass keeps serving with the in-memory config (O3)."""
        nonlocal write_failures, duplicate_config_writes
        try:
            if tools.store_reads is None:
                raise OSError("no hunt store configured")
            identity = semantic_key(config.unit_id, config.fault_class,
                                    config.vulnerability_class)
            try:
                already = bool(tools.store_reads.read_configs_by_key(
                    project_id, identity))
            except Exception:  # noqa: BLE001 - a failing read never blocks the write
                already = False
            if already:
                return None  # the tool already persisted it this turn
            return tools.store_reads.write_config(project_id, config)
        except DuplicateConfigError:
            # The G4 deduplication signal is deliberately CONFLATED into the
            # O3 counter (the ADR/assertions pin store_write_failures): a
            # duplicate write IS a failed write (no file was created). The
            # separate duplicate_config_writes field gives the signal its own
            # observability without unbundling the pinned metric.
            write_failures += 1
            duplicate_config_writes += 1
            logger.warning("hunt store: duplicate config write blocked (%s)",
                           config if isinstance(config, dict) else getattr(config, "hunt_id", ""))
            return None
        except Exception as exc:  # noqa: BLE001 - O3: warn and keep serving
            write_failures += 1
            logger.warning("hunt store: config write failed (%s)", exc)
            return None

    def _update_config(config) -> str | None:
        """Persist one ratification write (the ratify upsert): overwrites the
        config at its identity in place - a ratified config amends the draft,
        a dropped config is marked on disk and NEVER deleted (G6). Fail-open
        (O3): a raising write warns and counts; the pass keeps serving."""
        nonlocal write_failures
        try:
            if tools.store_reads is None:
                raise OSError("no hunt store configured")
            return tools.store_reads.update_config(project_id, config)
        except Exception as exc:  # noqa: BLE001 - O3: warn and keep serving
            write_failures += 1
            logger.warning("hunt store: config update failed (%s)", exc)
            return None

    def _append_note(key: str, note: str) -> None:
        """Append one pair-end note into the project's `memory.yaml` (natural
        append order, no `_seq`). IDEMPOTENT against the model's own
        `notes(write, option='append')` call during the same turn: an identical
        note for the key already on disk is not duplicated by the harness.
        Fail-open (O3): a raising write warns and counts; the pass keeps
        serving."""
        nonlocal write_failures
        try:
            if tools.store_reads is None:
                raise OSError("no hunt store configured")
            try:
                existing = tools.store_reads.read_notes(project_id, key)
                already = any(n.get("note") == note for n in existing)
            except Exception:  # noqa: BLE001 - a failing read never blocks the write
                already = False
            if already:
                return
            tools.store_reads.append_note(project_id, key, note)
        except Exception as exc:  # noqa: BLE001 - O3: warn and keep serving
            write_failures += 1
            logger.warning("hunt store: note write failed (%s)", exc)

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
            store_write_failures=write_failures,
            duplicate_config_writes=duplicate_config_writes,
        )

    # KB evidence, per fault (D67-11: an unavailable KB degrades the gate, and
    # the gate must never prune on degraded grounds).
    kb_evidences: dict[str, dict] = {}
    kb_degraded = kb_retrieve_fn is None
    if kb_retrieve_fn is not None:
        for candidate in intake.accepted:
            try:
                kb_evidences[candidate.fault_class] = await _await_seam(
                    kb_retrieve_fn, candidate.fault_class)
            except Exception as exc:  # noqa: BLE001 - D67-11 fail-open
                kb_degraded = True
                logger.warning("KB retrieval degraded for %s (%s)",
                               candidate.fault_class, exc)

    # The read-only graph surface (D67-04): grounding for the phase turns.
    surface: list[dict] = []
    if tools.graph_view is not None:
        try:
            surface = await _await_seam(tools.graph_view.index_cards)
        except Exception as exc:  # noqa: BLE001 - O5: degrade to an empty view
            logger.warning("graph view read failed, gate grounds degraded (%s)", exc)

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
        """Prior configs + notes by revival key (O4: a read failure degrades
        to an empty insight set, never aborts the hunt). The store's
        `read_configs_by_key` (produced/ + consumed/) and `read_notes`
        (memory.yaml) both key on the revival key; the merged list feeds the
        minted configs' `prior_hunt_insights` slot. Each prior config is
        embedded as its shallow projection (`_prior_config_insight`), NEVER the
        full dump - so a persisted config never embeds another config's
        `prior_hunt_insights` (the nesting would snowball across passes, I3)."""
        if tools.store_reads is None:
            return []
        try:
            configs = await _await_seam(
                tools.store_reads.read_configs_by_key, project_id, key)
            notes = await _await_seam(
                tools.store_reads.read_notes, project_id, key)
            return [_prior_config_insight(c) for c in configs] + list(notes)
        except Exception as exc:  # noqa: BLE001
            logger.warning("hunt store read degraded for %s (%s)", key, exc)
            return []

    def _mint_for_direction(
        direction: EnvisionedDirection,
        candidate: DeliveredCandidate,
        prior_insights: Sequence[dict],
        projection=None,
    ) -> list[HuntConfig]:
        """The deterministic fan-out mint (D3/spec 3.5): ONE hypothesised
        `HuntConfig` draft per distinct elicited `vulnerability_class` (a
        class-less direction degrades to a single carried-bare draft), each
        config's hunt_id derived from one base. Runs at the HYPOTHESISE phase
        (the mint is called here, via the `hunts_store` tool) - the emitted set
        is the model's authoritative submission. The surface context is
        transformed at the mint: a Service card's edge_degree counts become the
        detailed connected DataItems from the unit's rich projection when the
        projection resolved them; an absent projection degrades to the counts
        card (fail-open)."""
        caveats: list[str] = []
        if candidate.match_verdict != "applies":
            caveats.append("yellow match re-matched after back-edge")
        return mint_hunt_config(
            direction,
            candidate,
            uuid.uuid4().hex,
            surface_context={
                "cards": _surface_cards_with_connected_data_items(surface, projection),
            },
            prior_hunt_insights=prior_insights,
            tool_registry=_registry_from_kb(kb_evidences.get(direction.fault_class, {})),
            target_caveats=caveats,
            sub_fault_ids=fold_families.get(direction.fault_class) or (),
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
        the run's orchestration thread, then the mint fan-out (called at this
        phase) writes the status="hypothesised" drafts into produced/. The
        `hunts_store` tool's write response carried the NEXT_RATIFY_HINT
        constant (G1/G3); the loop state HYPOTHESISED is the graph's own (the
        wrapper sets it, G2). Fail-open: a raising/empty turn carries the pair
        bare (a class-less draft) - the old gate-carry."""
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
            orchestrator_gate_span,
            trace_gate_step,
        )
        with orchestrator_gate_span(run_id):
            trace_gate_step("symbolic-render", input={
                "pair": key,
                "projection": "ok" if projection is not None else "UNKNOWN",
                "materialisation": "ok" if materialisation is not None else "UNKNOWN",
                "fold_family": "ok" if fold_ids is not None else "UNKNOWN",
                "kb_degraded": kb_degraded,
            })
            if hypothesise_fn is not None:
                try:
                    decision = await _await_seam(hypothesise_fn, gate_input)
                    directions = list(getattr(decision, "directions", None) or [])
                    trace_gate_step("gate-decision", output={
                        "directions": [{
                            "pair": revival_key(d.unit_id, d.fault_class),
                            "carried": bool(d.carried),
                            "rationale": d.rationale,
                            "assumptions": list(d.assumptions),
                            "envisioned_test_primitives": list(
                                d.envisioned_test_primitives),
                            "research_direction": d.research_direction,
                            "vulnerability_classes": list(
                                d.vulnerability_classes),
                        } for d in directions],
                        "prior_minted_keys": list(gate_input.prior_minted_keys),
                    })
                except Exception as exc:  # noqa: BLE001 - fail-open: carry bare
                    logger.warning("hypothesise turn failed for %s, carrying (%s)",
                                   key, exc)
        if not directions:
            directions = [
                EnvisionedDirection(unit_id=pair.unit_id, fault_class=fault_class)
            ]

        # --- the hypothesise write (spec 3.3, the mint called at this phase) --
        carried = [d for d in directions if d.carried]
        trail = [
            {"kind": "gate_pruned",
             "revival_key": revival_key(d.unit_id, d.fault_class)}
            for d in directions if not d.carried
        ]
        ledger = prior_ledger
        minted = dict(state.get("minted_configs") or {})
        configs_written = 0
        if not carried:
            ledger.units_skipped += 1
            return {"ledger": ledger, "minted_configs": minted, "trail": trail,
                    "projections": {pair.unit_id: projection}}
        candidate = by_identity.get((pair.unit_id, fault_class)) or pair
        for direction in carried:
            prior_insights = await _read_prior_insights(key)
            configs = _mint_for_direction(
                direction, candidate, prior_insights, projection=projection)
            # S8: several carried directions for ONE pair all sit at the SAME
            # locus key (the pair's (unit, fault)) - accumulate the union into
            # `minted[key]` (never overwrite), so every draft enters the
            # ratify set instead of earlier drafts being orphaned
            # forever-hypothesised.
            minted.setdefault(key, []).extend(configs)
            trace_gate_step("emit-mint", input={
                "revival_key": key,
                "configs": len(configs),
                "classes": sorted(cfg.vulnerability_class for cfg in configs),
            })
            for config in configs:
                # G4: a duplicate write (the deduplication signal) is counted
                # and the in-memory config keeps serving - the model-facing
                # interpretation of the signal is the `hunts_store` TOOL.
                _write_config(config)
                configs_written += 1
        ledger.minted_config_keys.append(key)
        ledger.units_done += 1
        trail.append({"kind": "hypothesised", "revival_key": key,
                      "configs": configs_written})
        return {"ledger": ledger, "minted_configs": minted, "trail": trail,
                "projections": {pair.unit_id: projection}}

    async def _ratify_node(state) -> dict:
        """The RATIFY phase (spec 3.2): the pair's ratification turn on the run's
        orchestration thread. The model may update/delete/create configs and
        MUST end with a status="ratified" write carrying the filled
        capabilities/assumptions/technique-primitives; the harness persists
        each decision config at its terminal status (ratified upsert; dropped
        stays on disk - G6). The `hunts_store` tool's ratified-write response
        carried ONLY the NEXT_NOTE_HINT constant (G1); the loop state RATIFIED
        is the graph's own. The "must END with ratified" contract (S2): a
        decision entry RETURNED without status="ratified" (still hypothesised)
        is NOT counted ratified, is NOT re-persisted (the draft stays
        hypothesised on disk), and is NOT fed to the note phase. Fail-open: a
        raising/empty turn skips the phase's side effect (the drafts stay
        hypothesised) but the pair keeps serving."""
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
            try:
                out = await _await_seam(ratify_fn, _phase_input(pair, drafts, state))
                decision = out if isinstance(out, RatifyDecision) else RatifyDecision()
            except Exception as exc:  # noqa: BLE001 - fail-open: keep serving
                logger.warning("ratify turn failed for %s (%s)", key, exc)

        trail: list[dict] = []
        ratified_configs: list[HuntConfig] = []
        ratified = dropped = unratified = 0
        for config in decision.configs:
            if config.status == "ratified":
                _update_config(config)
                ratified += 1
                ratified_configs.append(config)
                trail.append({"kind": "ratified", "revival_key": key})
            elif config.status == "dropped":
                _update_config(config)
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
            minted = dict(state.get("minted_configs") or {})
            minted[key] = ratified_configs
            return {"trail": trail, "minted_configs": minted}
        return {"trail": trail}

    async def _note_node(state) -> dict:
        """The NOTE phase (spec 3.2/G8): the pair's note-taking turn on the
        run's orchestration thread; the harness appends the decision's notes
        (idempotently). The `notes` tool's append response carried the NEXT
        pair's data + the NEXT_PAIR_HINT constant - the pair's loop ENDS there
        (G1); the loop state NOTED is the graph's own (a LOOP state, never a
        config status - G5). Fail-open: a raising/empty turn skips the phase's
        side effect but the pair keeps serving."""
        pair = state.get("current_pair")
        if pair is None:
            return {"trail": []}
        key = revival_key(pair.unit_id, pair.fault_class)
        ratified = list((state.get("minted_configs") or {}).get(key) or [])
        if not ratified:
            # a pair with no configs (pruned at hypothesise, every config
            # dropped during ratification, or all returned-unratified - S2) has
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

        decision = NoteDecision()
        if note_fn is not None:
            try:
                out = await _await_seam(note_fn, _phase_input(pair, ratified, state))
                decision = out if isinstance(out, NoteDecision) else NoteDecision()
            except Exception as exc:  # noqa: BLE001 - fail-open: keep serving
                logger.warning("note turn failed for %s (%s)", key, exc)

        ledger = _ledger(state)
        trail: list[dict] = []
        notes_written = 0
        for record in decision.notes:
            _append_note(key, record.note)
            notes_written += 1
        if decision.notes:
            from polymerhus.attack.hunting.orchestrator_tracing import (  # noqa: PLC0415
                trace_gate_step,
            )
            ledger.notes_recorded += 1
            trace_gate_step("note-written", input={"revival_key": key})
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
        store_write_failures=write_failures,
        duplicate_config_writes=duplicate_config_writes,
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
    kb_retrieve_fn: Callable[[str], dict] | None = None,
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
        kb_retrieve_fn=kb_retrieve_fn,
        known_faults=known_faults,
        exhausted_faults=exhausted_faults,
        orchestrator_factory=orchestrator_factory,
    ))
