"""The hunt-orchestrator (#82): the central memory of the hunting effort.

Consumes the FaultSource candidate set (IA-1, spec 4.1), runs the per-FAULT
tool-augmented gate-reasoning turn (Q8, one turn per fault over all its matched
units), mints the deterministically fan-out `HuntConfig` set (D3, one per
distinct elicited vulnerability-class the direction carries, each a
status="hypothesised" draft) at the unit boundary, writes the configs into the
per-project memory store's `produced/` (memory-system spec #166), dispatches
one hunting agent per hunt (IA-2, synchronous in-process), and records the
per-unit note into the store's `memory.yaml`. It is the planner: it selects,
configures, dispatches, and holds memory; the D8 hunt records and the
per-run kind files are REMOVED - the persisted configs express which faults
are done / in-progress / left (G10). It never writes L0/L1 (its graph access
is the read-only view, D67-04); the hunting agent (#83), not this module, is
the test-DESIGN actor.

The pass runs NATIVE-ASYNC (feat/async-actor-agents) on the #110 GRAPH engine:
`arun_orchestration` is the single O1-O10 canon and its body IS a
supervisor-state schedule loop (the ONE flexible StateGraph in
`orchestrator_graph.py`) - per fault (the schedule unit is a fault, spec 3.1),
a stateful REASON turn covers ALL of the fault's matched units on the run's
`HuntOrchestratorActor` thread (`hunting_orchestrator` session, monotonic
across ALL faults), the deterministic unit-boundary stage mints the configs,
writes them to the store's `produced/`, and fires the note into `memory.yaml`,
then a deterministic budget stage cuts the accumulated directions, then each
allowed direction is DISPATCHED. Each node closure delegates to the canon
helpers in THIS module; the O1-O10 seam shapes stay single-sourced here.
`run_orchestration` is its thin sync wrapper.

The actor is the PURELY STATEFUL parent, exactly like the recon-orchestrator -
but it now LIVES in a per-run registry (`_ORCHESTRATOR_ACTORS`) instead of being
reaped in a pass's `finally` (#110): the SAME `HuntOrchestratorActor` (same
thread) serves every fault of a pass and stays live listening between passes;
the module's runtime stop path (Task 6) reaps it.

Degradations are the spec's failure canon: KB unavailable -> the gate reasons
degraded, never prunes (D67-11); dispatch failure -> degraded hunt record
(O6); store write failure -> warning and a count (O3, a duplicate-config write
is the deduplication signal and lands the same O3 path - G4); store read
failure -> empty prior insights (O4); a yellow candidate raises a hunt
back-edge (IA-6/D67-14) and re-matches, with a hard depth-1 cap -> `unresolved`
on the revival key (O8); a malformed candidate is dropped and counted (O10).
Fail-open throughout: one bad collaborator never aborts the pass.

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
from polymerhus.recon.control.targeted import (
    AnalyserReconRequest,
    ReconScope,
    TargetedReconResult,
)

logger = logging.getLogger(__name__)

# The orchestrator's tool surface (spec 3.4, the candidates-rewrite Q14/Q15
# correction): the split memory reads, the mint, the note, and the read-only
# graph view - exactly these, nothing more. No back-edge-to-recon tool (the
# back_edge request to recon is out of the agent's surface; operator ruling
# 2026-08-22 - the target-knowledge loop rides `graph_view`, never a recon
# request), no HuntConfig-writing tool (the deterministic mint writes the
# hypothesised drafts at the unit boundary) and no budget_consume tool (Q7:
# token budget is a global harness concern, not a hunting-local check). The
# `hunts_store` / `notes` store TOOLS are the next workstream's rework (#167);
# this ticket keeps the five-tool surface working against the new store.
TOOL_SURFACE = frozenset({
    "read_memory_hunts", "read_memory_notes", "graph_view",
    "mint_hunt_config", "record_note",
})

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
    """The gate's output: the directions, each marked carried or pruned in-turn."""

    directions: list[EnvisionedDirection] = Field(default_factory=list)


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
    reflection lists exactly these), notes recorded, and the budget remaining,
    carried on the graph state and updated deterministically at the unit
    boundary (after `record_note`). Re-injected into the prompt ONLY there -
    never after an intra-unit tool call. The verbatim render of this state is
    T5's Loop-protocol concern; this module owns the ledger STATE + the
    boundary update point."""

    units_done: int = 0
    units_skipped: int = 0
    minted_config_keys: list[str] = Field(default_factory=list)
    notes_recorded: int = 0
    budget_remaining: int = 0


class OrchestratorReport(BaseModel):
    """The pass summary (spec O1-O10): what was dispatched, dropped, pruned,
    cut, left unresolved, and how often the store writes failed. `ledger` is the
    harness-owned `LoopLedger` as of the candidates-rewrite, surfaced for
    observability (the canonical O1-O10 fields are unchanged)."""

    hunts_dispatched: int = 0
    hunt_ids: list[str] = Field(default_factory=list)
    duplicates_dropped: int = 0
    malformed_dropped: int = 0
    pruned_by_verdict: int = 0
    gate_pruned: tuple[str, ...] = ()
    exhausted_faults: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    budget_cut: tuple[str, ...] = ()
    store_write_failures: int = 0
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
class OrchestratorTools:
    """The orchestrator's tool seams (spec 3.4, the candidates-rewrite Q14/Q15
    correction): the hunt back-edge (IA-6), the per-project memory store
    (`store_reads`, the harness WRITE path - the deterministic mint writes the
    hypothesised configs into `produced/` and the unit-boundary note into
    `memory.yaml` - plus the prior-config/notes reads both memory tools share),
    the read-only graph view, and the run-local mint-emission bucket
    (`mint_hunt_config` records the model's emission onto it for the
    deterministic mint to fan out from; T4 consumes it).

    The harness write path rides `store_reads.write_config` /
    `store_reads.append_note` (per project); the two READ surfaces
    (`read_memory_hunts`, `read_memory_notes`) thread through the same store's
    `read_configs_by_key` / `read_notes`, keyed identically by revival key.
    `mint_emissions` is a run-local mutable bucket so a bare
    `OrchestratorTools` gets a working seam; the mint tool is still testable
    fail-open by passing `mint_emissions=None`."""

    back_edge: Callable[[AnalyserReconRequest, str, str], TargetedReconResult] | None = None
    store_reads: Any = None
    graph_view: ReadOnlyGraphView | None = None
    mint_emissions: list | None = field(default_factory=list)


def revival_key(unit_id: str, fault_class: str) -> str:
    """The kind-qualified pair that persists a hunt's place (Q5/#70): survives
    the hunt, drives change-driven re-test, and joins the fault on the wire
    (the back-edge itself is fault-agnostic)."""
    return f"{unit_id}::{fault_class}"


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
    dispatch_fn: Callable[[HuntConfig, tuple], DispatchResult] | None = None,
    rematch_fn: Callable[[str, str, TargetedReconResult], MatchVerdict] | None = None,
    reason_fn: Callable[[GateInput], GateDecision] | None = None,
    kb_retrieve_fn: Callable[[str], dict] | None = None,
    known_faults: Sequence[str] | None = None,
    exhausted_faults: Sequence[str] = (),
    budget_fn: Callable[[Sequence[EnvisionedDirection]], Sequence[EnvisionedDirection]] | None = None,
    orchestrator_factory: Callable[[str], "HuntOrchestratorActor"] | None = None,
) -> OrchestratorReport:
    """One orchestration pass, NATIVE-ASYNC (spec 4.1), driven by the #110 graph
    engine: intake -> KB evidence -> surface read -> ONE supervisor-state
    schedule loop over the accepted FAULTS (a stateful REASON turn per fault
    over ALL its matched units, minting the configs and firing the notes at the
    unit boundary -> a deterministic budget stage -> a DISPATCH turn per allowed
    direction), persisting the minted configs (produced/) and the unit-boundary
    note (memory.yaml) into the project's memory store. Fail-open on every
    collaborator.

    The hunt-orchestrator is the async-native parent of the hunting effort
    (feat/async-actor-agents): when `reason_fn`/`rematch_fn` are None (the
    production default) ONE `HuntOrchestratorActor` per run drives both LLM
    turns, serving EVERY fault of this pass (and of later passes on the same
    run) as inbox-request turns on the SAME `hunting_orchestrator` thread, so
    its checkpointed memory carries the pass's reasoning - PURELY stateful,
    exactly like the recon-orchestrator. The actor is held in the per-run
    registry and reaped only by the module's stop path.

    Every injected collaborator is called through `_await_seam` (an async seam
    is awaited; a sync seam is offloaded via `asyncio.to_thread`), so the pass
    never stalls the caller's event loop and sync fakes stay injectable.
    `dispatch_fn`/`rematch_fn`/`reason_fn`/`kb_retrieve_fn` are injected (the
    real hunting agent is #83, the real LLM match #71/#64); `tools` carries the
    store, the back-edge, and the read-only graph view. The O1-O10 canon is
    single-sourced HERE; `run_orchestration` is its thin sync wrapper.
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
        # first use, so the gate turn gets the run's real seam bodies (and a
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

    if reason_fn is None:
        # The gate turn rides the run's orchestration thread, per fault. The
        # actor's `reason` is `async def`, so the default seam must be an async
        # lambda - a sync lambda would return the coroutine un-awaited and
        # `_await_seam` would hand it to to_thread (the un-awaited-coroutine
        # defect the live tier caught).
        reason_fn = lambda inp: _resolve_orchestrator().reason(inp)  # noqa: E731
    if rematch_fn is None:
        # The re-match judge rides the SAME orchestration thread.
        rematch_fn = lambda u, f, r: _resolve_orchestrator().rematch(u, f, r)  # noqa: E731

    write_failures = 0

    def _write_config(config) -> str | None:
        """Persist one minted `HuntConfig` into the project's `produced/`
        (the hypothesise write, memory-system spec 3.2). Fail-open (O3): a
        raising write - including `DuplicateConfigError`, the storage-layer
        deduplication signal (G4) - warns and counts; the pass keeps serving
        with the in-memory config."""
        nonlocal write_failures
        try:
            if tools.store_reads is None:
                raise OSError("no hunt store configured")
            return tools.store_reads.write_config(project_id, config)
        except Exception as exc:  # noqa: BLE001 - O3: warn and keep serving
            write_failures += 1
            logger.warning("hunt store: config write failed (%s)", exc)
            return None

    def _append_note(key: str, note: str) -> None:
        """Append the unit-boundary note into the project's `memory.yaml`
        (natural append order, no `_seq`). Fail-open (O3): a raising write
        warns and counts; the pass keeps serving."""
        nonlocal write_failures
        try:
            if tools.store_reads is None:
                raise OSError("no hunt store configured")
            tools.store_reads.append_note(project_id, key, note)
        except Exception as exc:  # noqa: BLE001 - O3: warn and keep serving
            write_failures += 1
            logger.warning("hunt store: note write failed (%s)", exc)

    async def _record_back_edge(request: AnalyserReconRequest) -> TargetedReconResult:
        if tools.back_edge is None:
            result = TargetedReconResult(
                correlation_id=request.correlation_id,
                requester_id=request.requester_id,
                origin="hunting",
                status="error",
                error="no back-edge tool configured",
            )
        else:
            try:
                result = await _await_seam(tools.back_edge, request, run_id, project_id)
            except Exception as exc:  # noqa: BLE001 - IA-6 fail-open
                logger.warning("hunt back-edge failed for cid=%s (%s)",
                               request.correlation_id, exc)
                result = TargetedReconResult(
                    correlation_id=request.correlation_id,
                    requester_id=request.requester_id,
                    origin="hunting",
                    status="error",
                    error=str(exc),
                )
        # The back-edge's durable evidence-trail record is gone with the
        # per-run kind files (memory-system spec 3); the routed outcome flows
        # back in-memory for the re-match.
        return result

    intake = normalize_candidates(candidates, known_faults=known_faults)
    if intake.malformed_dropped:
        logger.warning("%s malformed candidate(s) dropped (counted)", intake.malformed_dropped)

    if not intake.accepted:
        # Empty pass (O1): nothing for the gate, budget, or dispatch stages.
        return OrchestratorReport(
            hunts_dispatched=0,
            hunt_ids=[],
            duplicates_dropped=intake.duplicates_dropped,
            malformed_dropped=intake.malformed_dropped,
            pruned_by_verdict=intake.pruned_by_verdict,
            exhausted_faults=tuple(exhausted_faults),
            unresolved=(),
            budget_cut=(),
            store_write_failures=write_failures,
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

    # The read-only graph surface (D67-04): grounding for the gate's turns.
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
        minted configs' `prior_hunt_insights` slot."""
        if tools.store_reads is None:
            return []
        try:
            configs = await _await_seam(
                tools.store_reads.read_configs_by_key, project_id, key)
            notes = await _await_seam(
                tools.store_reads.read_notes, project_id, key)
            return list(configs) + list(notes)
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
        config's hunt_id derived from one base. Runs at the unit boundary (in
        the REASON body) - the emitted set is the model's authoritative
        submission. The surface context is transformed at the mint: a Service
        card's edge_degree counts become the detailed connected DataItems from
        the unit's rich projection when the projection resolved them; an absent
        projection degrades to the counts card (fail-open)."""
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

    def _note_for_unit(direction: EnvisionedDirection, key: str,
                       configs: Sequence[HuntConfig]) -> str:
        """The deterministic `record_note` content (the dual-source emission
        seam, A2): PREFER the structured `EnvisionedDirection.research_direction`
        (always the carried direction's own, so it names the RIGHT fault even
        when one unit sits under two faults); THEN the run-local `mint_emissions`
        bucket, now keyed on the revival key (unit_id matched within the fault
        context) rather than on `unit_id` alone; else a deterministic synthetic
        note. Fires at the unit boundary, never after an intra-unit tool call."""
        if direction.research_direction:
            return direction.research_direction
        match = revival_key(direction.unit_id, direction.fault_class)
        for emission in (tools.mint_emissions or ()):
            if not (isinstance(emission, dict) and emission.get("research_direction")):
                continue
            if revival_key(emission.get("unit_id") or "",
                           direction.fault_class) != match:
                continue
            return emission["research_direction"]
        return f"minted {len(configs)} config(s) for {key}"

    async def _reason_node(state) -> dict:
        """The per-FAULT stateful REASON stretch (candidates-rewrite): the #135
        symbolic render builds ONE `GateInput` per fault whose `candidates` is
        the fault's FULL matched-unit list (each unit's projection slot degrades
        independently fail-open), ONE gate turn reasons over all of them on the
        run's orchestration thread, then the deterministic unit-boundary stage
        runs per emitted unit: the mint fan-out (N `HuntConfig`s per distinct
        class), the harness-fired `record_note`, and the `LoopLedger` update -
        the ONLY ledger reinjection point. Fail-open: a raising/empty turn
        carries every unit of the fault bare."""
        current = state.get("current")
        if current is None:
            return {"directions": [], "trail": []}
        fault_class = current.fault_class
        units = list(current.candidates)

        # --- the per-unit symbolic render (#135, spec 3.2) --------------------
        # Each unit's typed projection builds independently (fail-open per slot:
        # a raise/None degrades that unit's slot to None, never a prune - C16);
        # materialisation + fold family are per-FAULT and shared. `projection`
        # reflects the single-unit slot for backward compatibility.
        unit_projection: dict[str, object | None] = {}
        if tools.graph_view is not None:
            from polymerhus.attack.hunting.unit_projection import (  # noqa: PLC0415
                build_projection,
            )
            for c in units:
                proj: object | None = None
                try:
                    proj = build_projection(
                        project_id, c.unit_id, read_fn=tools.graph_view.read)
                except Exception as exc:  # noqa: BLE001 - per-unit degrade
                    logger.warning("unit projection degraded for %s (%s)",
                                   revival_key(c.unit_id, fault_class), exc)
                unit_projection[c.unit_id] = proj
        materialisation = materialisations.get(fault_class)
        fold_ids = fold_families.get(fault_class)
        # The Q11 novelty-reflection list: the CURRENT ledger's minted config
        # keys (read exactly like the unit-boundary stage below - fail-open to
        # [] when the ledger slot is absent or not a LoopLedger). Re-injected
        # into the prompt ONLY at this per-fault turn boundary, never after an
        # intra-unit tool call (spec 3.3).
        prior_ledger = state.get("ledger")
        prior_ledger = prior_ledger.model_copy(deep=True) \
            if isinstance(prior_ledger, LoopLedger) else LoopLedger()
        gate_input = GateInput(
            candidates=units,
            kb_degraded=kb_degraded,
            kb_evidences=kb_evidences,
            surface=surface,
            projection=unit_projection.get(units[0].unit_id) if units else None,
            unit_projection=unit_projection,
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
                "fault": fault_class,
                "unit_count": len(units),
                "projection": "ok" if any(unit_projection.values()) else "UNKNOWN",
                "materialisation": "ok" if materialisation is not None else "UNKNOWN",
                "fold_family": "ok" if fold_ids is not None else "UNKNOWN",
                "kb_degraded": kb_degraded,
            })
            if reason_fn is not None:
                try:
                    decision = await _await_seam(reason_fn, gate_input)
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
                except Exception as exc:  # noqa: BLE001 - fail-open: carry the fault
                    logger.warning("gate reasoning failed for %s, carrying (%s)",
                                   fault_class, exc)
        if not directions:
            directions = [
                EnvisionedDirection(unit_id=c.unit_id, fault_class=fault_class)
                for c in units
            ]
        carried = [d for d in directions if d.carried]
        trail = [
            {"kind": "gate_pruned",
             "revival_key": revival_key(d.unit_id, d.fault_class)}
            for d in directions if not d.carried
        ]

        # --- the deterministic unit-boundary stage (spec 3.3) -----------------
        # AFTER the reason turn returns: per emitted unit, read the prior
        # insights, mint the N configs from the emitted direction, write the
        # hypothesised configs into produced/ (the hypothesise write, memory
        # spec 3.2), fire the harness-owned note into memory.yaml, update the
        # `LoopLedger`. The ledger is re-injected ONLY here - never after an
        # intra-unit tool call.
        ledger = state.get("ledger")
        ledger = ledger.model_copy(deep=True) if isinstance(ledger, LoopLedger) \
            else LoopLedger()
        minted = dict(state.get("minted_configs") or {})
        for direction in carried:
            key = revival_key(direction.unit_id, direction.fault_class)
            candidate = by_identity.get((direction.unit_id, direction.fault_class))
            if candidate is None:
                ledger.units_skipped += 1
                continue
            prior_insights = await _read_prior_insights(key)
            configs = _mint_for_direction(
                direction, candidate, prior_insights,
                projection=unit_projection.get(direction.unit_id))
            minted[key] = list(configs)
            ledger.minted_config_keys.append(key)
            trace_gate_step("emit-mint", input={
                "revival_key": key,
                "configs": len(configs),
                "classes": sorted(cfg.vulnerability_class for cfg in configs),
            })
            for config in configs:
                _write_config(config)
            _append_note(key, _note_for_unit(direction, key, configs))
            trace_gate_step("note-written", input={"revival_key": key})
            ledger.notes_recorded += 1
            ledger.units_done += 1
        return {
            "directions": carried,
            "trail": trail,
            "ledger": ledger,
            "minted_configs": minted,
        }

    async def _budget_node(state) -> dict:
        """The deterministic budget stage (O9): a batch cut over the whole
        accumulated carried set; the cut directions ride the report trail only
        (the per-run `cut` kind file is removed, memory spec 3). Fail-open: a
        raising `budget_fn` cuts nothing."""
        carried = list(state.get("directions") or [])
        allowed: Sequence[EnvisionedDirection] = carried
        if budget_fn is not None:
            try:
                allowed = await _await_seam(budget_fn, carried)
            except Exception as exc:  # noqa: BLE001 - fail-open: no cut
                logger.warning("budget call failed, no directions cut (%s)", exc)
                allowed = carried
        trail: list[dict] = []
        for direction in carried:
            if direction not in allowed:
                key = revival_key(direction.unit_id, direction.fault_class)
                trail.append({"kind": "cut", "revival_key": key})
        ledger = state.get("ledger")
        ledger = ledger.model_copy(deep=True) if isinstance(ledger, LoopLedger) \
            else LoopLedger()
        ledger.budget_remaining = len(allowed)
        return {"worklist": list(allowed), "phase": "dispatch",
                "trail": trail, "ledger": ledger}

    async def _dispatch_node(state) -> dict:
        """The DISPATCH stretch: park/resume + rematch for a yellow candidate,
        then the per-config dispatch (IA-2) of the configs the per-fault REASON
        body minted at the unit boundary (spec 3.3/3.5) with the inline back-edge
        rounds (S5/S6, D67-14). Falls back to a deterministic mint when the
        direction has no pre-minted configs (the graph-default fail-open path).
        Fail-open at every step."""
        from polymerhus.recon.control.targeted import (  # noqa: PLC0415
            TargetedReconResult,
        )
        direction = state.get("current_direction")
        if direction is None:
            return {"trail": []}
        key = revival_key(direction.unit_id, direction.fault_class)
        candidate = by_identity.get((direction.unit_id, direction.fault_class))
        if candidate is None:
            logger.warning("direction %s has no candidate in the intake", key)
            return {"trail": []}

        routed: list[TargetedReconResult] = []
        if candidate.match_verdict != "applies":
            # Park/resume (S3/O8): raise the hunt back-edge, re-match on the
            # returned recon evidence, hard depth-1 cap.
            request = build_back_edge_request(
                direction.unit_id,
                direction.fault_class,
                requester_id=f"hunt-orchestrator-{run_id}",
                note=f"yellow match for {direction.fault_class}: "
                     f"{candidate.applies_witnesses.llm or ''}",
            )
            routed.append(await _record_back_edge(request))
            if rematch_fn is None:
                logger.warning("re-match unavailable for %s; unresolved", key)
                return {"trail": [{"kind": "unresolved", "revival_key": key}]}
            try:
                verdict = await _await_seam(
                    rematch_fn, direction.unit_id, direction.fault_class, routed[-1])
            except Exception as exc:  # noqa: BLE001 - IA-1 fail-open
                logger.warning("re-match exhausted for %s; unresolved (%s)", key, exc)
                return {"trail": [{"kind": "unresolved", "revival_key": key}]}
            if verdict.verdict == "insufficient-evidence":
                logger.info("re-match still yellow at the depth cap; %s unresolved", key)
                return {"trail": [{"kind": "unresolved", "revival_key": key}]}
            if verdict.verdict != "applies":
                logger.info("re-match refutes %s; no hunt", key)
                return {"trail": []}

        # The configs the per-fault REASON body minted and PERSISTED at the
        # unit boundary (produced/). A missing entry (the graph-default
        # fail-open carry path) degrades to a deterministic mint here, exactly
        # the canon's D3 fan-out - writing the configs + note exactly like the
        # unit-boundary stage, so the fail-open path never reads
        # `units_done=0` while dispatching N. The normal path never reaches
        # this branch, so nothing double-books.
        configs = list((state.get("minted_configs") or {}).get(key) or [])
        fallback_ledger: LoopLedger | None = None
        fallback_minted: dict | None = None
        if not configs:
            prior_insights = await _read_prior_insights(key)
            configs = _mint_for_direction(direction, candidate, prior_insights)
            ledger = state.get("ledger")
            fallback_ledger = ledger.model_copy(deep=True) \
                if isinstance(ledger, LoopLedger) else LoopLedger()
            for config in configs:
                _write_config(config)
            _append_note(key, _note_for_unit(direction, key, configs))
            fallback_ledger.minted_config_keys.append(key)
            fallback_ledger.notes_recorded += 1
            fallback_ledger.units_done += 1
            fallback_minted = dict(state.get("minted_configs") or {})
            fallback_minted[key] = list(configs)

        hunt_trails: list[dict] = []
        for config in configs:
            hunt_id = config.hunt_id

            hunt: dict[str, Any] = {
                "hunt_id": hunt_id,
                "revival_key": key,
                "degraded": False,
                "error": None,
            }
            round_no = 1
            while True:
                if dispatch_fn is None:
                    hunt.update({"degraded": True, "error": "hunting agent unavailable"})
                    break
                try:
                    result = await _await_seam(dispatch_fn, config, tuple(routed))
                except Exception as exc:  # noqa: BLE001 - O6: degrade the hunt
                    logger.warning("hunt %s dispatch failed (%s)", hunt_id, exc)
                    hunt.update({"degraded": True, "error": str(exc)})
                    break
                if result.back_edge_needs:
                    # Inline request-response (S5/S6, D67-14): each returned
                    # back-edge result re-evaluates the hypothesis verdict, and
                    # the evaluation continues unbounded while needs keep
                    # surfacing - the agent ends it by returning a result
                    # without needs.
                    for need in result.back_edge_needs:
                        routed.append(await _record_back_edge(need))
                    round_no += 1
                    continue
                hunt.update({
                    "spec_ref": result.spec_ref,
                    "pod_result_ref": result.pod_result_ref,
                    "hypothesis_verdict": result.hypothesis_verdict,
                })
                break
            hunt_trails.append({
                "kind": "hunt", "revival_key": key, "hunt_id": hunt_id,
                "degraded": bool(hunt.get("degraded")),
            })
        dispatch_ret: dict = {"trail": hunt_trails}
        if fallback_ledger is not None:
            dispatch_ret["ledger"] = fallback_ledger
            dispatch_ret["minted_configs"] = fallback_minted
        return dispatch_ret

    initial = {
        "project_id": project_id,
        "run_id": run_id,
        "phase": "reason",
        "schedule": _fault_schedule(),
        "current": None,
        "worklist": [],
        "current_direction": None,
        "directions": [],
        "trail": [],
        "ledger": LoopLedger(),
        "minted_configs": {},
        "kb_evidences": kb_evidences,
        "kb_degraded": kb_degraded,
        "surface": surface,
        "tools": tools,
        "store_reads": tools.store_reads,
        "reason_fn": reason_fn,
        "budget_fn": budget_fn,
        "dispatch_fn": dispatch_fn,
        "rematch_fn": rematch_fn,
        "exhausted_faults": tuple(exhausted_faults),
    }
    graph = build_hunting_graph(
        reason_node=_reason_node, budget_node=_budget_node, dispatch_node=_dispatch_node,
    )
    terminal = await graph.compile().ainvoke(
        initial, {"configurable": {"thread_id": run_id}},
    )
    trail = list(terminal.get("trail") or [])
    hunts = [t for t in trail if t.get("kind") == "hunt"]
    return OrchestratorReport(
        hunts_dispatched=len(hunts),
        hunt_ids=[t["hunt_id"] for t in hunts],
        duplicates_dropped=intake.duplicates_dropped,
        malformed_dropped=intake.malformed_dropped,
        pruned_by_verdict=intake.pruned_by_verdict,
        gate_pruned=tuple(t["revival_key"] for t in trail if t.get("kind") == "gate_pruned"),
        exhausted_faults=tuple(exhausted_faults),
        unresolved=tuple(t["revival_key"] for t in trail if t.get("kind") == "unresolved"),
        budget_cut=tuple(t["revival_key"] for t in trail if t.get("kind") == "cut"),
        store_write_failures=write_failures,
        ledger=terminal.get("ledger") or LoopLedger(),
    )


def run_orchestration(
    project_id: str,
    run_id: str,
    candidates: Sequence[DeliveredCandidate],
    tools: OrchestratorTools,
    *,
    dispatch_fn: Callable[[HuntConfig, tuple], DispatchResult] | None = None,
    rematch_fn: Callable[[str, str, TargetedReconResult], MatchVerdict] | None = None,
    reason_fn: Callable[[GateInput], GateDecision] | None = None,
    kb_retrieve_fn: Callable[[str], dict] | None = None,
    known_faults: Sequence[str] | None = None,
    exhausted_faults: Sequence[str] = (),
    budget_fn: Callable[[Sequence[EnvisionedDirection]], Sequence[EnvisionedDirection]] | None = None,
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
        dispatch_fn=dispatch_fn,
        rematch_fn=rematch_fn,
        reason_fn=reason_fn,
        kb_retrieve_fn=kb_retrieve_fn,
        known_faults=known_faults,
        exhausted_faults=exhausted_faults,
        budget_fn=budget_fn,
        orchestrator_factory=orchestrator_factory,
    ))