"""The hunt-orchestrator full-machine e2e eval stack (operator-directed).

The RUNTIME-CONTROL COMPONENT: a thin harness that runs ONLY the orchestrator
through the project's standard interfaces against the LIVE L1 surface of the
source project, then hands back the machine-state evidence - the
``OrchestratorReport``, the store artifacts (produced/ configs + ``memory.yaml``
notes), the phase-context next-pair assignments, and the orchestrator trace
rows.

No seam is mocked:
- the candidate set is produced by the standard FaultSource selection
  (``fault_source.select`` over the live L1 read-only view); the LLM match is
  #71/#64 scope (designed-not-built), so the intake's O10 llm-witness slot is
  filled from the deterministic stage's pass evidence - the minimal adapter
  the contract requires, never a substitute for a built seam;
- the orchestrator phase turns run the REAL actor (real LLM through the
  co-located gateway, ``LLM_MODEL_HUNTING_ORCHESTRATOR``);
- the KB grounding is the real ``fault_kb.load_materialisation``;
- the memory store is a scratch ``HuntStore`` so the eval never pollutes the
  branch's ``data/hunts``.

The downstream hunting-agent dispatch does not exist on this graph (G12): the
graph ENDs at the REASON stretch, so this component runs the orchestrator
only. The harness drives ``arun_orchestration`` (the single O1-O10 canon)
under ``hunting_module_context``, exactly as ``start_hunting`` does.

Machine-state evidence the component collects:
- ``report`` - the deterministic pass summary (supervisor routing, ledger,
  config lifecycle, failure counts);
- ``store`` - the produced/ config YAMLs (hypothesised / ratified / dropped
  lifecycle) and the memory.yaml notes;
- ``phase_context.assignments`` - every next-pair frame the note phase set
  (the G1 pair-end + fault-drain logic, observed through a recording
  ``PhaseContext``, never a mocked seam);
- ``trace_rows`` - the orchestrator's own observations
  (``orchestrator_gate_span`` / ``trace_gate_step``) captured through the
  standard ``hunting_observability`` probe.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence, cast

from polymerhus.attack.hunting.fault_kb import load_fault_entries, load_materialisation
from polymerhus.attack.hunting.fault_risk import risk_tier
from polymerhus.attack.hunting.fault_source import select
from polymerhus.attack.hunting.hunt_orchestrator import (
    DeliveredCandidate,
    OrchestratorReport,
    OrchestratorTools,
    PhaseContext,
    ReadOnlyGraphView,
    Witness,
)
from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.attack.hunting.runtime import hunting_module_context

# The operator's mapped L1 surface (live in the shared neo4j): the moodique
# storefront project - 14 L1Service + 8 L1System testable units.
SOURCE_PROJECT_ID = "2a7544e3-ee8d-4e11-8465-609c774d28b2"

# Eval knobs (env): a quick smoke run caps the candidate set; the full run
# leaves both at 0 (= all).
_EVAL_MAX_FAULTS = int(os.environ.get("HUNTING_EVAL_MAX_FAULTS", "0"))
_EVAL_MAX_UNITS_PER_FAULT = int(os.environ.get("HUNTING_EVAL_MAX_UNITS_PER_FAULT", "0"))


def select_fault_ids(count: int = 30) -> list[str]:
    """The eval's fault set: the top-``count`` selection-tier kb entries by the
    operator risk tier (``fault_risk.risk_tier``), stable within a tier in kb
    order - the exact ordering the orchestrator's schedule uses. Selected
    regardless of whether the fault's predicate applies to any unit; a fault
    with no matching unit simply yields no candidates (the intake handles it).
    """
    ordered = sorted(load_fault_entries(), key=lambda e: risk_tier(e.fault_id))
    return [e.fault_id for e in ordered[:count]]


def testable_unit_ids(project_id: str, read_fn: Callable) -> list[str]:
    """Every kind-qualified testable-unit identity of the project's live L1:
    ``Service:<business_function_slug>`` and ``<SystemKind>:<discriminator>``.
    """
    rows = read_fn(
        "MATCH (u:L1TestableUnit) WHERE u.project_id = $p "
        "RETURN u.business_function_slug AS slug, u.kind AS k, "
        "u.discriminator AS d",
        {"p": project_id},
    )
    unit_ids: list[str] = []
    for row in rows:
        if row.get("slug"):
            unit_ids.append(f"Service:{row['slug']}")
        elif row.get("k"):
            unit_ids.append(f"{row['k']}:{row.get('d') or '__singleton__'}")
    return unit_ids


def produce_candidates(
    fault_ids: Sequence[str],
    project_id: str,
    view: ReadOnlyGraphView,
    unit_ids: Sequence[str] | None = None,
    *,
    max_units_per_fault: int = 0,
) -> list[DeliveredCandidate]:
    """The candidate set through the standard FaultSource selection over the
    live L1: every (unit, fault) pair the deterministic stage passes becomes a
    ``DeliveredCandidate`` with ``match_verdict='applies'``. The llm witness is
    filled from the deterministic-stage pass evidence (the LLM match is
    #71/#64 scope) so the intake's O10 contract holds; ``max_units_per_fault``
    bounds the pair count for a smoke run (0 = all)."""
    if unit_ids is None:
        unit_ids = testable_unit_ids(project_id, view.read)
    faults = [e for e in load_fault_entries() if e.fault_id in set(fault_ids)]
    reports = select(faults, unit_ids, project_id=project_id, read_fn=view.read)
    candidates: list[DeliveredCandidate] = []
    for rep in reports:
        matched = [o.unit_id for o in rep.outcomes if o.verdict == "passed"]
        if max_units_per_fault > 0:
            matched = matched[:max_units_per_fault]
        for unit_id in matched:
            candidates.append(DeliveredCandidate(
                unit_id=unit_id,
                fault_class=rep.fault_id,
                applies_witnesses=Witness(
                    deterministic=None,
                    llm=f"deterministic-stage pass: {unit_id}::{rep.fault_id}",
                ),
                match_verdict="applies",
            ))
    return candidates


class EvalPhaseContext:
    """A recording phase context: every ``next_pair`` assignment the note phase
    makes is captured in order (the G1 pair-end / fault-drain machine, observed
    without mocking the note seam). Duck-typed against ``PhaseContext`` - the
    note node only reads/writes ``next_pair``."""

    def __init__(self) -> None:
        self._next_pair: dict | None = None
        self.assignments: list[dict | None] = []

    @property
    def next_pair(self) -> dict | None:
        return self._next_pair

    @next_pair.setter
    def next_pair(self, value: dict | None) -> None:
        self._next_pair = value
        self.assignments.append(value)


@dataclass
class EvalResult:
    """The machine-state evidence a run hands back."""

    project_id: str
    run_id: str
    fault_ids: list[str]
    unit_ids: list[str]
    candidates: list[DeliveredCandidate]
    report: OrchestratorReport
    store: HuntStore
    phase_context: Any
    probe: Any = None
    trace_rows: list[Any] = field(default_factory=list)
    expected_faults_with_pairs: int = 0


def _kb_retrieve_fn(fault_class: str) -> dict:
    """The real KB grounding seam: the fault's materialisation-facet content
    (static YAML read, fail-open to an empty dict on an absent entry)."""
    materialisation = dict(load_materialisation())
    entry = materialisation.get(fault_class)
    return asdict(entry) if entry is not None else {}


async def _eval_pass(
    project_id: str,
    run_id: str,
    candidates: list[DeliveredCandidate],
    tools: OrchestratorTools,
) -> OrchestratorReport:
    from polymerhus.attack.hunting.hunt_orchestrator import arun_orchestration

    # dev retired the kb_retrieve_fn seam (#407f8da) - the gate now grounds via
    # the direct fault-KB materialisation read. Pass the seam only when the
    # running arun_orchestration still declares it, so the harness is faithful
    # to both the branch under test and the dev container it runs in.
    kwargs = {}
    if "kb_retrieve_fn" in inspect.signature(arun_orchestration).parameters:
        kwargs["kb_retrieve_fn"] = _kb_retrieve_fn

    async with hunting_module_context():
        return await arun_orchestration(
            project_id, run_id, candidates, tools, **kwargs,
        )


def run_orchestrator_eval(
    project_id: str = SOURCE_PROJECT_ID,
    *,
    fault_ids: Sequence[str] | None = None,
    store_root=None,
    run_id: str | None = None,
    max_faults: int = _EVAL_MAX_FAULTS,
    max_units_per_fault: int = _EVAL_MAX_UNITS_PER_FAULT,
    trace_rows: bool = True,
) -> EvalResult:
    """The runtime control: select the fault set, produce the candidates over
    the live L1, run ONLY the orchestrator (real actor, real KB, scratch
    store) under the hunting module context, and return the machine-state
    evidence. ``max_faults=0`` means all selected faults (default 30)."""
    selected = list(fault_ids) if fault_ids is not None else select_fault_ids(30)
    if max_faults > 0:
        selected = selected[:max_faults]

    view = ReadOnlyGraphView(project_id)
    units = testable_unit_ids(project_id, view.read)
    candidates = produce_candidates(
        selected, project_id, view, units, max_units_per_fault=max_units_per_fault,
    )
    store = HuntStore(root_dir=store_root)
    phase_context = cast(PhaseContext, EvalPhaseContext())
    tools = OrchestratorTools(
        store_reads=store,
        graph_view=view,
        phase_context=phase_context,
    )
    rid = run_id or f"hunt-eval-{uuid.uuid4().hex[:12]}"

    probe = None
    traced_run = None
    if trace_rows:
        from tests.e2e.hunting_observability import traced_run as _traced_run
        from tests.e2e.hunting_observability import probe_for_run

        probe, _ = probe_for_run(rid, store_root=store_root)
        traced_run = _traced_run

    async def _drive() -> OrchestratorReport:
        if probe is not None and traced_run is not None:
            with traced_run(probe):
                return await _eval_pass(project_id, rid, candidates, tools)
        return await _eval_pass(project_id, rid, candidates, tools)

    report = asyncio.run(_drive())

    expected_with_pairs = len({c.fault_class for c in candidates})
    result = EvalResult(
        project_id=project_id,
        run_id=rid,
        fault_ids=list(selected),
        unit_ids=units,
        candidates=candidates,
        report=report,
        store=store,
        phase_context=phase_context,
        probe=probe,
        trace_rows=probe.rows() if probe is not None else [],
        expected_faults_with_pairs=expected_with_pairs,
    )
    _dump_evidence(result)
    return result


def _dump_evidence(result: EvalResult) -> None:
    """Dump the run's machine-state evidence to a JSON file under the store
    root (probe rows + report + next-pair assignments) so a diagnosis can read
    the LLM-turn verbatims after the in-process observability probe is gone.
    Best-effort: a failing dump must never fail the eval."""
    try:
        from polymerhus.attack.hunting.hunt_store import HUNT_STORE_ROOT

        root = Path(HUNT_STORE_ROOT)
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"{result.run_id}.eval.json"
        target.write_text(json.dumps({
            "project_id": result.project_id,
            "run_id": result.run_id,
            "fault_ids": result.fault_ids,
            "unit_ids": result.unit_ids,
            "candidates": [c.model_dump() for c in result.candidates],
            "report": result.report.model_dump(),
            "next_pair_assignments": result.phase_context.assignments,
            "trace_rows": [row.__dict__ for row in result.trace_rows],
        }, indent=2, default=str), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - never fail the eval on a dump
        logger = __import__("logging").getLogger(__name__)
        logger.warning("hunt-eval evidence dump failed (%s)", exc)