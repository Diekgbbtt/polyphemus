"""The hunt-orchestrator (#82): the central memory of the hunting effort.

Consumes the FaultSource candidate set (IA-1, spec 4.1), runs the single
embedded gate-reasoning turn (Q8), mints one `HuntConfig` (D3) per carried
direction, dispatches one hunting agent per hunt (IA-2, synchronous
in-process), and writes every event to the append-only hunt store (#68,
O12). It is the planner: it selects, configures, dispatches, holds memory and
budget, and writes the D8 hunt records. It never writes L0/L1 (its graph
access is the read-only view, D67-04); the hunting agent (#83), not this
module, is the test-DESIGN actor.

The pass runs NATIVE-ASYNC (feat/async-actor-agents): `arun_orchestration` is
the single O1-O10 canon and drives the gate turn and the re-match judge as
inbox-request turns of ONE `HuntOrchestratorActor` per run on the
`hunting_orchestrator` session thread (purely stateful, exactly like the
recon-orchestrator); `run_orchestration` is its thin sync wrapper.

Degradations are the spec's failure canon: KB unavailable -> the gate reasons
degraded, never prunes (D67-11); dispatch failure -> degraded hunt record
(O6); store write failure -> warning and a count (O3); store read failure ->
empty prior insights (O4); a yellow candidate raises a hunt back-edge
(IA-6/D67-14) and re-matches, with a hard depth-1 cap -> `unresolved` on the
revival key (O8); a malformed candidate is dropped and counted (O10); a
budget cut records the un-dispatched direction (O9). Fail-open throughout:
one bad collaborator never aborts the pass.

This module imports no driver and performs no I/O at import; the graph read
seam resolves lazily on first call (CODING_STANDARD section 6).
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Literal, Sequence

from pydantic import BaseModel, Field

from polymerhus.recon.control.targeted import (
    AnalyserReconRequest,
    ReconScope,
    TargetedReconResult,
)

logger = logging.getLogger(__name__)

# The orchestrator's tool surface (#67 D67-04, spec 5.1): exactly these three,
# nothing more.
TOOL_SURFACE = frozenset({"back_edge", "store_reads", "graph_view"})

# The default targeted job a park/resume back-edge runs (a re-witness of the
# unit's surface); the agent's inline needs carry their own job.
_DEFAULT_BACK_EDGE_JOB = "httpx_reprofile"


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
    hunting agent's later, more concrete hypothesis (Q8)."""

    unit_id: str
    fault_class: str
    carried: bool = True
    rationale: str = ""
    assumptions: list[str] = Field(default_factory=list)
    envisioned_test_primitives: list[str] = Field(default_factory=list)
    supposed_payload_vectors: list[str] = Field(default_factory=list)


class GateInput(BaseModel):
    """The single embedded reasoning turn's input (Q8): the accepted candidate
    set, the KB evidence (empty + degraded flag when the KB is unavailable,
    D67-11), and the read-only graph surface."""

    candidates: list[DeliveredCandidate] = Field(default_factory=list)
    kb_degraded: bool = False
    kb_evidences: dict = Field(default_factory=dict)
    surface: list[dict] = Field(default_factory=list)


class GateDecision(BaseModel):
    """The gate's output: the directions, each marked carried or pruned in-turn."""

    directions: list[EnvisionedDirection] = Field(default_factory=list)


class HuntPromptTemplate(BaseModel):
    """Part 1 of the five-part HuntConfig parameter set (Q8/D3): the fault-matching
    rationale, the suggested extension points (the orchestrator's envisioned
    test primitives), the adversarial-capability / environmental assumptions,
    the supposed payload vectors, and the L0 fault-applicability evidence."""

    rationale: str = ""
    extension_points: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    supposed_payload_vectors: list[str] = Field(default_factory=list)
    l0_evidence: list[str] = Field(default_factory=list)


class HuntConfig(BaseModel):
    """The declarative config the hunting agent consumes (D3): the five-part
    parameter set - prompt template, wide surface context (adapted index-card),
    target caveats, prior-hunt insights (by revival key), tool registry."""

    hunt_id: str
    unit_id: str
    fault_class: str
    prompt_template: HuntPromptTemplate
    surface_context: dict = Field(default_factory=dict)
    target_caveats: list[str] = Field(default_factory=list)
    prior_hunt_insights: list[dict] = Field(default_factory=list)
    tool_registry: list[dict] = Field(default_factory=list)


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


class OrchestratorReport(BaseModel):
    """The pass summary (spec O1-O10): what was dispatched, dropped, pruned,
    cut, left unresolved, and how often the store writes failed."""

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
    """The orchestrator's three tools (D67-04): the hunt back-edge (IA-6), the
    hunt-store reads (#68), and the read-only graph view."""

    back_edge: Callable[[AnalyserReconRequest, str, str], TargetedReconResult] | None = None
    store_reads: Any = None
    graph_view: ReadOnlyGraphView | None = None


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


def mint_hunt_config(
    direction: EnvisionedDirection,
    candidate: DeliveredCandidate,
    hunt_id: str,
    *,
    surface_context: dict,
    prior_hunt_insights: Sequence[dict],
    tool_registry: Sequence[dict],
    target_caveats: Sequence[str] = (),
) -> HuntConfig:
    """Mint the five-part `HuntConfig` (D3) for a carried direction: the prompt
    template (rationale + extension points + assumptions + supposed payload
    vectors + L0 fault-applicability evidence), the wide surface context (the
    adapted index-card), the target caveats, the prior-hunt insights, and the
    fault-targeting tool registry."""
    evidence: list[str] = []
    if candidate.applies_witnesses.deterministic is not None:
        evidence.append(f"deterministic: {candidate.applies_witnesses.deterministic}")
    if candidate.applies_witnesses.llm is not None:
        evidence.append(f"llm: {candidate.applies_witnesses.llm}")
    return HuntConfig(
        hunt_id=hunt_id,
        unit_id=direction.unit_id,
        fault_class=direction.fault_class,
        prompt_template=HuntPromptTemplate(
            rationale=direction.rationale,
            extension_points=list(direction.envisioned_test_primitives),
            assumptions=list(direction.assumptions),
            supposed_payload_vectors=list(direction.supposed_payload_vectors),
            l0_evidence=evidence,
        ),
        surface_context=surface_context,
        target_caveats=list(target_caveats),
        prior_hunt_insights=list(prior_hunt_insights),
        tool_registry=list(tool_registry),
    )


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
    """One orchestration pass, NATIVE-ASYNC (spec 4.1): intake -> gate turn ->
    budget -> per-direction park/resume + mint + dispatch, every event appended
    to the hunt store. Fail-open on every collaborator.

    The hunt-orchestrator is the async-native parent of the hunting effort
    (feat/async-actor-agents): when `reason_fn`/`rematch_fn` are None (the
    production default) ONE `HuntOrchestratorActor` per run drives both LLM
    turns as inbox-request turns on the SAME `hunting_orchestrator` thread, so
    its checkpointed memory carries the pass's reasoning - PURELY stateful,
    exactly like the recon-orchestrator. The actor is reaped in `finally`.

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
                from polymerhus.attack.hunting.actors import HuntOrchestratorActor  # noqa: PLC0415
                orchestrator = HuntOrchestratorActor(run_id)
        return orchestrator

    async def _await_seam(fn, *args):
        """Await an async seam, else offload a sync one to a worker thread
        (mirrors the recon pipeline's `_phase_exclusions` seam dispatch)."""
        if inspect.iscoroutinefunction(fn):
            return await fn(*args)
        return await asyncio.to_thread(fn, *args)

    if reason_fn is None:
        # The gate turn rides the run's orchestration thread.
        reason_fn = lambda inp: _resolve_orchestrator().reason(inp)  # noqa: E731
    if rematch_fn is None:
        # The re-match judge rides the SAME orchestration thread.
        rematch_fn = lambda u, f, r: _resolve_orchestrator().rematch(u, f, r)  # noqa: E731

    try:
        write_failures = 0

        def _write(kind: str, record: dict) -> str | None:
            nonlocal write_failures
            try:
                if tools.store_reads is None:
                    raise OSError("no hunt store configured")
                return tools.store_reads.append(run_id, kind, record)
            except Exception as exc:  # noqa: BLE001 - O3: warn and keep serving
                write_failures += 1
                logger.warning("hunt store: %s record write failed (%s)", kind, exc)
                return None

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
            # One evidence-trail record per back-edge: the request's identity and
            # the routed outcome (the fault joins via the correlation_id, D9).
            _write("back_edge", {
                "correlation_id": result.correlation_id,
                "unit_id": request.scope.unit_id or "",
                "origin": request.origin,
                "status": result.status,
                "error": result.error,
            })
            return result

        def _unresolved(key: str, unit_id: str, fault_class: str) -> None:
            unresolved_keys.append(key)
            _write("unresolved", {
                "revival_key": key,
                "unit_id": unit_id,
                "fault_class": fault_class,
            })

        _write("run", {
            "project_id": project_id,
            "run_id": run_id,
            "candidates_received": len(candidates),
        })

        intake = normalize_candidates(candidates, known_faults=known_faults)
        if intake.malformed_dropped:
            logger.warning("%s malformed candidate(s) dropped (counted)", intake.malformed_dropped)
        gate_pruned: list[str] = []
        unresolved_keys: list[str] = []
        budget_cut_keys: list[str] = []
        hunt_ids: list[str] = []
        hunts_dispatched = 0

        if not intake.accepted:
            return OrchestratorReport(
                hunts_dispatched=hunts_dispatched,
                hunt_ids=hunt_ids,
                duplicates_dropped=intake.duplicates_dropped,
                malformed_dropped=intake.malformed_dropped,
                pruned_by_verdict=intake.pruned_by_verdict,
                exhausted_faults=tuple(exhausted_faults),
                unresolved=tuple(unresolved_keys),
                budget_cut=tuple(budget_cut_keys),
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

        # The read-only graph surface (D67-04): grounding for the gate's turn.
        surface: list[dict] = []
        if tools.graph_view is not None:
            try:
                surface = await _await_seam(tools.graph_view.index_cards)
            except Exception as exc:  # noqa: BLE001 - O5: degrade to an empty view
                logger.warning("graph view read failed, gate grounds degraded (%s)", exc)

        # The single embedded reasoning turn (Q8), on the run's orchestration thread.
        directions: list[EnvisionedDirection] = []
        if reason_fn is not None:
            try:
                directions = (await _await_seam(reason_fn, GateInput(
                    candidates=intake.accepted,
                    kb_degraded=kb_degraded,
                    kb_evidences=kb_evidences,
                    surface=surface,
                ))).directions
            except Exception as exc:  # noqa: BLE001 - fail-open: carry everything
                logger.warning("gate reasoning failed, carrying all candidates (%s)", exc)
        if not directions:
            directions = [
                EnvisionedDirection(unit_id=c.unit_id, fault_class=c.fault_class)
                for c in intake.accepted
            ]

        carried = [d for d in directions if d.carried]
        for direction in directions:
            if not direction.carried:
                gate_pruned.append(revival_key(direction.unit_id, direction.fault_class))

        # The budget (O9): cut directions are recorded, never dispatched.
        allowed: Sequence[EnvisionedDirection] = carried
        if budget_fn is not None:
            try:
                allowed = await _await_seam(budget_fn, carried)
            except Exception as exc:  # noqa: BLE001 - fail-open: no cut
                logger.warning("budget call failed, no directions cut (%s)", exc)
                allowed = carried
        for direction in carried:
            if direction not in allowed:
                budget_cut_keys.append(revival_key(direction.unit_id, direction.fault_class))
                _write("cut", {"direction": revival_key(direction.unit_id, direction.fault_class)})

        by_identity = {(c.unit_id, c.fault_class): c for c in intake.accepted}

        for direction in allowed:
            key = revival_key(direction.unit_id, direction.fault_class)
            candidate = by_identity.get((direction.unit_id, direction.fault_class))
            if candidate is None:
                logger.warning("direction %s has no candidate in the intake", key)
                continue

            # Prior-hunt insights by revival key (O4: a read failure degrades to
            # an empty insight set, never aborts the hunt).
            try:
                prior_insights = (
                    await _await_seam(tools.store_reads.read_memory, key)
                    if tools.store_reads else []
                )
            except Exception as exc:  # noqa: BLE001
                prior_insights = []
                logger.warning("hunt store read degraded for %s (%s)", key, exc)

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
                    _unresolved(key, direction.unit_id, direction.fault_class)
                    continue
                try:
                    verdict = await _await_seam(
                        rematch_fn, direction.unit_id, direction.fault_class, routed[-1])
                except Exception as exc:  # noqa: BLE001 - IA-1 fail-open
                    logger.warning("re-match exhausted for %s; unresolved (%s)", key, exc)
                    _unresolved(key, direction.unit_id, direction.fault_class)
                    continue
                if verdict.verdict == "insufficient-evidence":
                    logger.info("re-match still yellow at the depth cap; %s unresolved", key)
                    _unresolved(key, direction.unit_id, direction.fault_class)
                    continue
                if verdict.verdict != "applies":
                    logger.info("re-match refutes %s; no hunt", key)
                    continue

            caveats = (["yellow match re-matched after back-edge"] if routed else [])

            # Mint (D3), dispatch (IA-2), record (D8) - fail-open at every step.
            hunt_id = uuid.uuid4().hex
            config = mint_hunt_config(
                direction,
                candidate,
                hunt_id,
                surface_context={"cards": surface},
                prior_hunt_insights=prior_insights,
                tool_registry=_registry_from_kb(kb_evidences.get(direction.fault_class, {})),
                target_caveats=caveats,
            )
            config_ref = _write("config", config.model_dump())

            hunt: dict[str, Any] = {
                "hunt_id": hunt_id,
                "revival_key": key,
                "config_ref": config_ref,
                "degraded": False,
                "error": None,
            }
            round_no = 1
            while True:
                if dispatch_fn is None:
                    hunt.update({"degraded": True, "error": "hunting agent unavailable"})
                    _write("dispatch", {
                        "hunt_id": hunt_id, "round": round_no,
                        "error": "hunting agent unavailable",
                    })
                    break
                try:
                    result = await _await_seam(dispatch_fn, config, tuple(routed))
                except Exception as exc:  # noqa: BLE001 - O6: degrade the hunt
                    logger.warning("hunt %s dispatch failed (%s)", hunt_id, exc)
                    hunt.update({"degraded": True, "error": str(exc)})
                    _write("dispatch", {
                        "hunt_id": hunt_id, "round": round_no, "error": str(exc),
                    })
                    break
                if result.back_edge_needs:
                    # Inline request-response (S5/S6, D67-14): each returned
                    # back-edge result re-evaluates the hypothesis verdict, and the
                    # evaluation continues unbounded while needs keep surfacing -
                    # the agent ends it by returning a result without needs.
                    _write("dispatch", {
                        "hunt_id": hunt_id, "round": round_no,
                        "back_edge_needs": [n.correlation_id for n in result.back_edge_needs],
                    })
                    for need in result.back_edge_needs:
                        routed.append(await _record_back_edge(need))
                    round_no += 1
                    continue
                _write("dispatch", {
                    "hunt_id": hunt_id, "round": round_no,
                    "spec_ref": result.spec_ref,
                    "pod_result_ref": result.pod_result_ref,
                    "hypothesis_verdict": result.hypothesis_verdict,
                    "feedback": result.feedback,
                })
                _write("result", {
                    "hunt_id": hunt_id,
                    "spec_ref": result.spec_ref,
                    "pod_result_ref": result.pod_result_ref,
                    "hypothesis_verdict": result.hypothesis_verdict,
                    "feedback": result.feedback,
                })
                hunt.update({
                    "spec_ref": result.spec_ref,
                    "pod_result_ref": result.pod_result_ref,
                    "hypothesis_verdict": result.hypothesis_verdict,
                })
                # The revive-keyed memory (#70): the feedback becomes the
                # prior-hunt insight the next pass on this key retrieves.
                _write("memory", {
                    "revival_key": key,
                    "hunt_id": hunt_id,
                    "insight": result.feedback,
                })
                break
            _write("hunt", hunt)
            hunt_ids.append(hunt_id)
            hunts_dispatched += 1

        return OrchestratorReport(
            hunts_dispatched=hunts_dispatched,
            hunt_ids=hunt_ids,
            duplicates_dropped=intake.duplicates_dropped,
            malformed_dropped=intake.malformed_dropped,
            pruned_by_verdict=intake.pruned_by_verdict,
            gate_pruned=tuple(gate_pruned),
            exhausted_faults=tuple(exhausted_faults),
            unresolved=tuple(unresolved_keys),
            budget_cut=tuple(budget_cut_keys),
            store_write_failures=write_failures,
        )
    finally:
        if orchestrator is not None:
            await orchestrator.stop()


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
