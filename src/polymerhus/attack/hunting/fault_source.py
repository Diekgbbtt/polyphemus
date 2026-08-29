"""The deterministic stage of FaultSource selection (#63, spec 2.1/2.4-2.6).

The typed applies-if predicate is evaluated at the head of FaultSource
selection (the S1 position, subsuming the Q8 S1 symbolic pre-filter and the Q2
fail-open enum gate, D-B). This module is the deterministic half of the
phase-1 FaultSource body - the phase-2 body is anatomy abduction (Q2) - and
the spec's three seams:

  * `evaluate` - the PURE deterministic stage
    `evaluate(predicate, unit_projection) -> {pass, does-not-apply, witness}`
    (spec 2.4): three-valued clause semantics, FALSE iff at least one clause is
    FALSE, UNKNOWN never prunes, no LLM, no wall-clock, deterministic. A
    malformed projection degrades to `pass` with a diagnostic - never prunes
    on a bug (the fail-open invariant). The witness names the FIRST violating
    clause in authoring order (a defined choice, so it is deterministic).
  * `evaluate_unit` - the stage seam with the reader wired in: a reader
    failure degrades to `pass` with a logged diagnostic (C6-a).
  * `select` - the FaultSource selection entry (the impure orchestrator,
    CODING_STANDARD section 3): mints candidates by the predicate's `target`
    declaration (the #69 joint seam - System-strict faults mint no Service
    candidates), evaluates per unit, degrades per-entry (predicate -> the
    enum-of-system-kinds tag -> default-open, spec 2.6), and passes survivors
    to the LLM `match_fn` (the real LLM match is #71/#64 scope; the production
    path uses the pass-through match until then - tests inject a counting
    stub). The stage never emits `insufficient-evidence` - the yellow
    verdict is an evidence-sufficiency judgment structure-checking cannot make
    (D-D).

As of ticket #200 this module is ALSO the PRODUCTION selection seam: the
platform plays the FaultSource role when a launch supplies no candidate batch.

  * `delivered_candidates` - the PURE mapper from the selection's
    `FaultSelectionReport` outcomes to the orchestrator's `DeliveredCandidate`
    intake: `pruned-by-predicate` / `pruned-by-tag` outcomes are dropped,
    `passed` + `matched` map to `match_verdict="applies"` with the
    deterministic witness (the clause, a fail-open diagnostic, or the pass
    marker). The llm witness half stays optional (spec 4.1): a
    deterministic-only witness is a valid delivered candidate.
  * `materialize_candidates` - the IMPURE wiring seam `start_hunting` /
    `launch_orchestrator` call on an empty candidate batch: enumerate the
    project's kind-qualified units (reusing the L1 inventory read, Systems
    kind-qualified `<kind>:<discriminator>` with the `L1_SINGLETON` elision
    handled), load the fault-KB matching facet, run `select` with the
    pass-through match, and translate the survivors via the pure mapper. A
    non-empty caller batch is returned unchanged (the caller override). Fails
    open to an empty candidate set - a degraded KB / L1 read never raises into
    the pass.

This module imports no driver and performs no I/O at import; the default read
seam resolves lazily on first call (CODING_STANDARD section 6).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable, Literal, Sequence

if TYPE_CHECKING:  # the orchestrator's intake type; resolved lazily at runtime
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        DeliveredCandidate,
    )

from polymerhus.attack.hunting.predicate import (
    Clause,
    ClauseForm,
    TypedPredicate,
    render_clause,
)
from polymerhus.attack.hunting.unit_projection import (
    UnitProjection,
    build_projection,
)
from polymerhus.analysis.l1_curator import (
    DATA_RELATIONSHIP_KINDS,
    SYSTEM_KINDS,
)

_SYSTEM_KIND_SET = frozenset(kind for kind, _desc in SYSTEM_KINDS)
_DATA_REL_EDGE_TYPES = frozenset(k.upper() for k, _desc in DATA_RELATIONSHIP_KINDS)

log = logging.getLogger(__name__)


class ClauseValue(Enum):
    """The three-valued clause semantics (spec 2.4)."""

    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class EvaluationResult:
    """The deterministic stage's total output (spec 2.4).

    `verdict` is the binary prune signal: `pass` (TRUE/UNKNOWN survive) or
    `does-not-apply` (FALSE). `witness` is the violated clause id (its
    canonical rendering) - carried fault-agnostic on the wire, joined by
    correlation_id (C7). `diagnostic` carries a fail-open degradation reason.
    """

    verdict: Literal["pass", "does-not-apply"]
    witness: str | None = None
    diagnostic: str | None = None


@dataclass(frozen=True)
class FaultEntry:
    """One fault-KB entry as the selection entry sees it (#66 owns the KB
    artifact; this is the deterministic slot shape): the typed predicate if the
    entry is hardened, else the phase-1 enum-of-system-kinds tag, else
    nothing. A hardened entry NEVER consults its tag (R-c retires the gate
    per-entry when the predicate lands)."""

    fault_id: str
    predicate: TypedPredicate | None = None
    enum_kinds: frozenset[str] = frozenset()


@dataclass(frozen=True)
class UnitOutcome:
    """One (unit, fault) verdict at the entry (the evaluation log entry)."""

    unit_id: str
    verdict: Literal["passed", "pruned-by-predicate", "pruned-by-tag"]
    witness: str | None = None
    matched: bool = False
    diagnostic: str | None = None


@dataclass(frozen=True)
class FaultSelectionReport:
    """The entry's output for one fault: the ordered outcome log, plus how many
    typed predicates were actually evaluated (the E3 observables: an
    unhardened entry's evaluation log is EMPTY - 0 evaluated)."""

    fault_id: str
    outcomes: tuple[UnitOutcome, ...]
    predicates_evaluated: int = 0


def _unit_kind_of(unit_id: str) -> str:
    """The kind half of the kind-qualified identity "<kind>:<key>"."""
    return unit_id.split(":", 1)[0]


def _eval_clause(clause: Clause, projection: UnitProjection) -> ClauseValue:
    """Three-valued evaluation of ONE necessary-condition clause (spec 2.4):
    TRUE - the facet matches; FALSE - the facet is present and contradicts;
    UNKNOWN - facet absent, edge family absent, or value unvalidated."""
    key = clause.key or ""  # validated predicates always carry a key; "" is
    # never a real facet key, so a key-less clause degrades to UNKNOWN
    if clause.form is ClauseForm.KIND_IS:
        kind = projection.kind
        if kind not in _SYSTEM_KIND_SET:
            return ClauseValue.UNKNOWN   # a non-System unit has no System kind
        return ClauseValue.TRUE if kind in clause.values else ClauseValue.FALSE

    if clause.form is ClauseForm.REACHABLE_VIA:
        edges = projection.edges.get(key) or ()
        if not edges:
            return ClauseValue.UNKNOWN   # family absent: not-yet-filled (C12-b)
        for edge in edges:
            if (edge.target_kind in clause.values
                    and (clause.role is None or edge.role is not None)):
                return ClauseValue.TRUE
        if any(edge.target_kind not in _SYSTEM_KIND_SET for edge in edges):
            return ClauseValue.UNKNOWN   # unvalidated target kind: default-open
        if clause.role is not None and not any(
                edge.role is not None for edge in edges):
            return ClauseValue.UNKNOWN   # role facet absent family-wide
        return ClauseValue.FALSE         # family present and contradicting (C12-a)

    if clause.form is ClauseForm.SPINE_PRESENT:
        value = projection.spine.get(key)
        return ClauseValue.TRUE if value is not None else ClauseValue.UNKNOWN

    if clause.form is ClauseForm.SPINE_EQUALS:
        value = next(iter(clause.values))
        kind = projection.kind
        if kind not in _SYSTEM_KIND_SET:
            return ClauseValue.UNKNOWN
        return ClauseValue.TRUE if kind == value else ClauseValue.FALSE

    if clause.form is ClauseForm.DATA_EDGE_EXISTS:
        count = projection.data_edges.get(key) or 0
        return ClauseValue.TRUE if count > 0 else ClauseValue.UNKNOWN

    if clause.form is ClauseForm.DATA_RELATIONSHIP_KIND:
        kinds = projection.data_rel_kinds
        if not kinds:
            return ClauseValue.UNKNOWN   # no relationships: facet absent
        expected = {value.upper() for value in clause.values}
        if any(k in expected for k in kinds):
            return ClauseValue.TRUE
        if any(k not in _DATA_REL_EDGE_TYPES for k in kinds):
            return ClauseValue.UNKNOWN   # unvalidated kind: default-open
        return ClauseValue.FALSE         # validated kinds present, none listed

    # SERVES_UNITS_WITH (D3-unlanded) is validator-unreachable; stay total.
    return ClauseValue.UNKNOWN


def evaluate(predicate: TypedPredicate,
             projection: UnitProjection | None) -> EvaluationResult:
    """The PURE deterministic stage: total, fail-open, no LLM, no I/O.

    The predicate is FALSE iff at least one clause is FALSE (AND of necessary
    conditions); an UNKNOWN clause never makes it FALSE. The witness names the
    FIRST violating clause in authoring order. A malformed projection (or a
    projection carrying read-time diagnostics) degrades to `pass` with a
    diagnostic - the stage never prunes on a bug."""
    if projection is None:
        return EvaluationResult("pass",
                                diagnostic="no projection for the unit (unknown or absent)")
    if not isinstance(projection, UnitProjection):
        return EvaluationResult("pass",
                                diagnostic=f"malformed projection: "
                                           f"{type(projection).__name__}")
    if not projection.kind:
        return EvaluationResult("pass",
                                diagnostic="malformed projection: missing the "
                                           "unit kind field")
    if projection.diagnostics:
        return EvaluationResult("pass",
                                diagnostic="; ".join(projection.diagnostics))
    for clause in predicate.clauses:
        if _eval_clause(clause, projection) is ClauseValue.FALSE:
            return EvaluationResult("does-not-apply", witness=render_clause(clause))
    return EvaluationResult("pass")


def evaluate_unit(predicate: TypedPredicate, unit_id: str, *,
                  project_id: str, read_fn=None) -> EvaluationResult:
    """The deterministic-stage seam over the reader: a reader failure degrades
    to `pass` with a diagnostic (C6-a) - the stage never crashes the caller
    and never prunes on a bug (spec 2.4)."""
    try:
        projection = build_projection(project_id, unit_id, read_fn=read_fn)
    except Exception as exc:  # noqa: BLE001 - fail-open is the contract
        message = f"projection read failed for {unit_id}: {exc}"
        log.warning(message)
        return EvaluationResult("pass", diagnostic=message)
    return evaluate(predicate, projection)


def mint_candidates(fault: FaultEntry, unit_ids: Sequence[str]) -> tuple[str, ...]:
    """The candidate-minting seam (the #69 joint seam, spec 2.3 D-B): the ONLY
    input is the predicate's `target` declaration - System-strict faults mint
    no Service candidates. An unhardened entry declares no direction and mints
    both kinds (fail-open). The implicit-coverage carve-out (#69) is NOT
    applied here."""
    target = fault.predicate.target if fault.predicate is not None else "Both"
    if target == "Both":
        return tuple(unit_ids)
    if target == "Service":
        return tuple(u for u in unit_ids if _unit_kind_of(u) == "Service")
    return tuple(u for u in unit_ids if _unit_kind_of(u) in _SYSTEM_KIND_SET)


def _unit_passes_tag(enum_kinds: frozenset[str], unit_id: str, *,
                     project_id: str, read_fn) -> bool:
    """The phase-1 enum-of-system-kinds signal (Q2, unchanged semantics): the
    unit passes iff it IS a System of a presupposed kind, or it is linked to
    one via an outgoing System edge. Reader failure fails open (never prunes
    on a bug)."""
    unit_kind = _unit_kind_of(unit_id)
    if unit_kind in enum_kinds and unit_kind in _SYSTEM_KIND_SET:
        return True
    try:
        projection = build_projection(project_id, unit_id, read_fn=read_fn)
    except Exception as exc:  # noqa: BLE001 - fail-open is the contract
        log.warning("tag signal read failed for %s: %s", unit_id, exc)
        return True
    if projection is None:
        return False
    return any(edge.target_kind in enum_kinds
               for edges in projection.edges.values() for edge in edges)


def select(faults: Sequence[FaultEntry], unit_ids: Sequence[str], *,
           project_id: str, read_fn=None,
           match_fn: Callable[[str, str], bool] | None = None) \
        -> tuple[FaultSelectionReport, ...]:
    """The FaultSource selection entry (the impure orchestrator): per fault,
    mint by target declaration, evaluate per unit through the deterministic
    stage, degrade per-entry, and pass survivors to the LLM `match_fn`
    (injectable; tests use pass-through counting mode). Returns one report per
    fault - the outcomes ARE the stage's evaluation log. Never emits
    `insufficient-evidence` (D-D)."""
    reports: list[FaultSelectionReport] = []
    for fault in faults:
        outcomes: list[UnitOutcome] = []
        predicates_evaluated = 0
        for unit_id in mint_candidates(fault, unit_ids):
            if fault.predicate is not None:
                result = evaluate_unit(fault.predicate, unit_id,
                                       project_id=project_id, read_fn=read_fn)
                predicates_evaluated += 1
                if result.verdict == "does-not-apply":
                    outcomes.append(UnitOutcome(unit_id, "pruned-by-predicate",
                                                witness=result.witness))
                else:
                    matched = match_fn(unit_id, fault.fault_id) \
                        if match_fn is not None else True
                    outcomes.append(UnitOutcome(unit_id, "passed",
                                                matched=matched,
                                                diagnostic=result.diagnostic))
            elif fault.enum_kinds:
                passes = _unit_passes_tag(fault.enum_kinds, unit_id,
                                          project_id=project_id, read_fn=read_fn)
                if passes:
                    matched = match_fn(unit_id, fault.fault_id) \
                        if match_fn is not None else True
                    outcomes.append(UnitOutcome(unit_id, "passed", matched=matched))
                else:
                    outcomes.append(UnitOutcome(unit_id, "pruned-by-tag"))
            else:
                matched = match_fn(unit_id, fault.fault_id) \
                    if match_fn is not None else True
                outcomes.append(UnitOutcome(unit_id, "passed", matched=matched))
        reports.append(FaultSelectionReport(fault.fault_id, tuple(outcomes),
                                            predicates_evaluated))
    return tuple(reports)


_PASS_WITNESS_MARKER = "deterministic-stage pass"


@dataclass(frozen=True)
class SelectionSummary:
    """The selection-run report (#200, spec 4.1; surfaced via `trace_gate_step`
    + a log line, the minimal observability ruling): what the production
    selection step did, so an all-pruned empty launch is distinguishable from
    "nothing supplied and nothing ran"."""

    faults_evaluated: int = 0
    units_minted: int = 0
    pruned_by_predicate: int = 0
    pruned_by_tag: int = 0
    passed: int = 0
    caller_supplied: bool = False


def _project_unit_ids(project_id: str, *, read_fn=None) -> tuple[str, ...]:
    """The deterministic project-scoped unit enumeration (#200, spec 4.1):
    the L1 inventory's Services kind-qualified `Service:<slug>` and its
    Systems kind-qualified `<kind>:<discriminator>`. The inventory render
    ELIDES the `__singleton__` discriminator (`_render_system`), so the
    singleton's discriminator is re-attached from `L1_SINGLETON` here - the
    identity the projection reader resolves. Fail-open: a read error degrades
    to the empty enumeration (the inventory's own contract)."""
    from polymerhus.analysis.l1_inventory import read_l1_inventory  # noqa: PLC0415
    from polymerhus.analysis.l1_types import L1_SINGLETON  # noqa: PLC0415

    inventory = read_l1_inventory(project_id, read_fn=read_fn)
    ids: list[str] = [f"Service:{slug}" for slug in inventory["services"]]
    for system in inventory["systems"]:
        if ":" in system:
            kind, discriminator = system.split(":", 1)
        else:
            kind, discriminator = system, L1_SINGLETON
        ids.append(f"{kind}:{discriminator}")
    return tuple(ids)


def delivered_candidates(
    reports: Sequence[FaultSelectionReport],
) -> tuple["DeliveredCandidate", ...]:
    """The PURE mapper (#200, spec 4.1): the selection's `FaultSelectionReport`
    outcomes into the orchestrator's `DeliveredCandidate` intake. A
    `pruned-by-predicate` / `pruned-by-tag` outcome is dropped (the prune
    signal is preserved); a `passed` + `matched` outcome maps to
    `match_verdict="applies"` with the deterministic witness - the fail-open
    diagnostic when the pass degraded, else the deterministic pass marker. The
    llm witness half stays None (OPTIONAL, spec 4.1): the intake's O10
    malformed check keys on ANY witness half, so the platform's own
    deterministic-only selection is never discarded."""
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        DeliveredCandidate,
        Witness,
    )

    out: list[DeliveredCandidate] = []
    for report in reports:
        for outcome in report.outcomes:
            if outcome.verdict != "passed" or not outcome.matched:
                continue
            deterministic = outcome.witness or outcome.diagnostic \
                or _PASS_WITNESS_MARKER
            out.append(DeliveredCandidate(
                unit_id=outcome.unit_id,
                fault_class=report.fault_id,
                applies_witnesses=Witness(deterministic=deterministic),
                match_verdict="applies",
            ))
    return tuple(out)


def _summarize(reports: Sequence[FaultSelectionReport]) -> SelectionSummary:
    """Pure: one `SelectionSummary` over the selection reports."""
    pruned_predicate = 0
    pruned_tag = 0
    passed = 0
    for report in reports:
        for outcome in report.outcomes:
            if outcome.verdict == "pruned-by-predicate":
                pruned_predicate += 1
            elif outcome.verdict == "pruned-by-tag":
                pruned_tag += 1
            elif outcome.verdict == "passed":
                passed += 1
    return SelectionSummary(
        faults_evaluated=len(reports),
        units_minted=sum(len(r.outcomes) for r in reports),
        pruned_by_predicate=pruned_predicate,
        pruned_by_tag=pruned_tag,
        passed=passed,
    )


def materialize_candidates(
    project_id: str,
    candidates: Sequence["DeliveredCandidate"] | None,
    *,
    fault_entries: Sequence[FaultEntry] | None = None,
    read_fn=None,
    match_fn: Callable[[str, str], bool] | None = None,
    unit_ids_fn=None,
) -> tuple[tuple["DeliveredCandidate", ...], SelectionSummary]:
    """The production selection seam (#200, spec 4.1): `start_hunting` /
    `launch_orchestrator` call it on the launch's candidate batch. A non-empty
    caller batch is the override - returned unchanged, never re-selected (the
    harness / integration / eval seams still drive selection externally). An
    empty batch triggers the platform's OWN FaultSource selection: enumerate
    the project's kind-qualified units (the L1 inventory), load the fault-KB
    matching facet, run `select` with the pass-through match, and translate
    the survivors via `delivered_candidates`.

    Returns `(candidates, summary)`; the summary records what the selection
    step did (faults evaluated / units minted / pruned-by-predicate /
    pruned-by-tag / passed / caller-supplied), so an all-pruned empty launch
    is a MEANINGFUL empty pass. Fail-open: a degraded KB or L1 read degrades
    to the empty candidate set with the zeroed summary - never raises into
    the pass."""
    if candidates:
        return tuple(candidates), SelectionSummary(caller_supplied=True)
    try:
        if fault_entries is None:
            from polymerhus.attack.hunting.fault_kb import (  # noqa: PLC0415
                load_fault_entries,
            )
            fault_entries = load_fault_entries()
        unit_ids = (
            unit_ids_fn(project_id, read_fn=read_fn)
            if unit_ids_fn is not None
            else _project_unit_ids(project_id, read_fn=read_fn)
        )
        reports = select(fault_entries, unit_ids, project_id=project_id,
                         read_fn=read_fn, match_fn=match_fn)
        selected = delivered_candidates(reports)
        summary = _summarize(reports)
        log.info("hunting selection for %s: %s", project_id, summary)
        return selected, summary
    except Exception as exc:  # noqa: BLE001 - fail-open is the contract
        log.warning("hunting selection for %s degraded (fail-open): %s",
                    project_id, exc)
        return (), SelectionSummary()
