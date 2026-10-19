"""The unit threat model schema and the pure completion checker (S2 5 and 7).

One model exists per discretely testable L1 unit (the unit id IS the model id).
The schema is **partial** at the intermediate workflow gates and **complete** at
`COMPLETED`: every section has an empty default, so a gate write extends one
document instead of re-authoring it.  Unknown fields are forbidden at every
level, so a typo can never silently persist.

The entity names are the artifact contract's (`UnitThreatModel`,
`TechnicalSharpening`, `TrustModel`, `TrustAgreement`, `DynamicStateTrust`,
`Assumption`, `Fault`, `Vulnerability`, `FailureMode`, `Loop`, `Evidence`,
`Confidence`, `Likelihood`, `RiskFactors`, `RiskProfile`, `Validation`).

Rules this module owns:

- The likelihood weights (`RISK_WEIGHTS`) and the default progressive risk
  threshold (`DEFAULT_RISK_THRESHOLD`) - the run driver records both.
- The risk profile is computed from the loop likelihoods, never authored: the
  model's own total is untrusted (S2 7.3).
- The loop normalisation (S2 5.6): a stable sort by likelihood weight
  descending, ties in the modeller's write order, ids renumbered `loop-1..n`.
  The store owns the id, so the write schema defaults `Loop.id` empty.
- The completion checker (S2 5.7): the loose necessary-attribute set, the
  referential integrity, the assumption-to-loop closure, the loop order, and a
  REGRESSION check of the stored risk profile against a fresh recomputation.
  It is non-blocking: it records findings, it never rejects the model.

The checker is pure; the store (`threat_model_store`) applies it on the
`COMPLETED` write only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1

# The progressive risk budget's default halt (S2 7.4). A documented starting
# constant, not a calibrated value; the run records the effective threshold.
DEFAULT_RISK_THRESHOLD = 12


class Confidence(StrEnum):
    """The evidence-and-grounding degree every formal claim carries."""

    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    ASSUMED = "ASSUMED"


class Likelihood(StrEnum):
    """The loop likelihood enum; the weight is monotonic (S2 7.1)."""

    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# The ONE likelihood-weight table (S2 7.1): strictly increasing, likelihood
# only (no impact factor). The run driver records this map and sums with it.
RISK_WEIGHTS: dict[Likelihood, int] = {
    Likelihood.NONE: 0,
    Likelihood.LOW: 1,
    Likelihood.MEDIUM: 2,
    Likelihood.HIGH: 3,
    Likelihood.CRITICAL: 4,
}


class UnitKind(StrEnum):
    SERVICE = "service"
    SYSTEM = "system"


class ModelState(StrEnum):
    """The five workflow gates; the persisted state is the latest gate."""

    UNIT_TECHNICAL_SHARP = "UNIT_TECHNICAL_SHARP"
    TRUST_MODELLED = "TRUST_MODELLED"
    TRUST_ASSUMPTIONS_WRITTEN = "TRUST_ASSUMPTIONS_WRITTEN"
    VULNERABILITIES_WRITTEN = "VULNERABILITIES_WRITTEN"
    COMPLETED = "COMPLETED"


# The gate order (S2 5.3): a write whose gate is lower than the persisted state
# updates content but never regresses the state.
STATE_ORDER: dict[ModelState, int] = {
    state: rank for rank, state in enumerate(ModelState)
}

# The section names each gate may write (S2 5.4). The COMPLETED write does not
# carry `risk_profile`; the store computes it after the merge.
GATE_SECTIONS: dict[ModelState, tuple[str, ...]] = {
    ModelState.UNIT_TECHNICAL_SHARP: ("technical_sharpening",),
    ModelState.TRUST_MODELLED: ("trust_model",),
    ModelState.TRUST_ASSUMPTIONS_WRITTEN: ("assumptions",),
    ModelState.VULNERABILITIES_WRITTEN: ("vulnerabilities",),
    ModelState.COMPLETED: ("failure_modes", "loops"),
}


class EvidenceKind(StrEnum):
    REQUEST = "request"
    HTTP_HISTORY = "http_history"
    PROBE = "probe"
    NOTE = "note"
    MODEL = "model"
    FRAMEWORK_DEFAULT = "framework_default"
    DOCUMENT = "document"


class ViolationKind(StrEnum):
    TRUST_TRANSITION = "trust-transition"
    STATE_CONSISTENCY = "state-consistency"
    FORCED_TRANSITION = "forced-transition"
    OTHER = "other"


class Feasibility(StrEnum):
    FEASIBLE = "feasible"
    CONDITIONALLY_FEASIBLE = "conditionally-feasible"
    INFEASIBLE = "infeasible"


class AttackVector(StrEnum):
    NETWORK = "network"
    ADJACENT = "adjacent"
    LOCAL = "local"
    PHYSICAL = "physical"


class AttackRequirements(StrEnum):
    NONE = "none"
    PRESENT = "present"


class PrivilegesRequired(StrEnum):
    NONE = "none"
    LOW = "low"
    HIGH = "high"


class Complexity(StrEnum):
    LOW = "low"
    HIGH = "high"


class _Record(BaseModel):
    """The shared shape rule: unknown fields are forbidden at every level."""

    model_config = ConfigDict(extra="forbid")


class Evidence(_Record):
    """One grounding entry of a claim (repeatable and indexable)."""

    kind: EvidenceKind
    ref: str
    detail: str = ""


class Agreement(_Record):
    """One technical-sharpening agreement (interface, control, or data flow)."""

    id: str
    statement: str
    confidence: Confidence
    evidences: list[Evidence]


class TrustAgreement(_Record):
    """One boundary trust agreement derived from the interface agreements."""

    id: str
    boundary: str
    interface_agreement_refs: list[str] = Field(default_factory=list)
    statement: str
    confidence: Confidence
    evidences: list[Evidence]


class DynamicState(_Record):
    id: str
    variables: list[str]
    confidence: Confidence
    evidences: list[Evidence]


class Transition(_Record):
    id: str
    source: str
    target: str
    guard: str
    confidence: Confidence
    evidences: list[Evidence]


class Violation(_Record):
    id: str
    kind: ViolationKind
    statement: str
    maps_to_fault: str
    # The transition the violation bounds (S2 5.1/S3 8.2): the payload's
    # dynamic-state selection reads this link. Optional because a
    # state-consistency violation need not bound a transition; when the model
    # carries transitions and this ref is absent the link is ambiguous.
    transition_ref: str | None = None
    confidence: Confidence
    evidences: list[Evidence]


class DynamicStateTrust(_Record):
    states: list[DynamicState] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    violations: list[Violation] = Field(default_factory=list)


class TechnicalSharpening(_Record):
    interface_agreements: list[Agreement] = Field(default_factory=list)
    control_flows: list[Agreement] = Field(default_factory=list)
    data_flows: list[Agreement] = Field(default_factory=list)


class TrustModel(_Record):
    trust_agreements: list[TrustAgreement] = Field(default_factory=list)
    dynamic_state_trust: DynamicStateTrust = Field(default_factory=DynamicStateTrust)


class Fault(_Record):
    id: str
    label: str
    description: str


class Assumption(_Record):
    id: str
    statement: str
    fault: Fault
    boundary_ref: str = ""
    confidence: Confidence
    evidences: list[Evidence]


class Vulnerability(_Record):
    id: str
    fault_ref: str
    canonical_class: str
    web_vulnerability_class: str = ""
    suite_gap: bool = False
    characterisation: str
    dropped: bool = False
    drop_reason: str = ""
    drop_probe: str = ""
    confidence: Confidence
    evidences: list[Evidence]


class FailureMode(_Record):
    id: str
    vulnerability_ref: str
    mode: str
    feasibility: Feasibility
    feasibility_rationale: str
    dropped: bool = False
    drop_reason: str = ""
    drop_probe: str = ""
    confidence: Confidence
    evidences: list[Evidence]


class RiskFactors(_Record):
    attack_vector: AttackVector
    attack_requirements: AttackRequirements
    privileges_required: PrivilegesRequired
    complexity: Complexity


class Loop(_Record):
    """One ranked research direction and the dispatch grain.

    `id` defaults empty: the loop id is a store-owned derived symbol assigned
    at the COMPLETED write (S2 5.6 / 10.2), never authored by the modeller.
    """

    id: str = ""
    fault_ref: str
    vulnerability_ref: str
    failure_mode_refs: list[str]
    canonical_class: str
    web_vulnerability_class: str = ""
    suite_gap: bool = False
    likelihood: Likelihood
    likelihood_rationale: str
    risk_factors: RiskFactors
    confidence: Confidence
    evidences: list[Evidence]


class RiskProfile(_Record):
    total: int
    breakdown: dict[Likelihood, int]


class Validation(_Record):
    checked_at: datetime
    parseable: bool
    valid: bool
    missing: list[str] = Field(default_factory=list)
    unclosed: list[str] = Field(default_factory=list)
    referential_errors: list[str] = Field(default_factory=list)


class UnitThreatModel(_Record):
    """The complete unit threat model (S2 5.1).

    At the intermediate gates the same shape is persisted with the empty
    section defaults (`PartialThreatModel`); the completion checker runs only
    on the COMPLETED gate.
    """

    schema_version: int = SCHEMA_VERSION
    unit_id: str
    unit_kind: UnitKind
    run_id: str
    created_at: datetime
    updated_at: datetime
    state: ModelState
    technical_sharpening: TechnicalSharpening = Field(default_factory=TechnicalSharpening)
    trust_model: TrustModel = Field(default_factory=TrustModel)
    assumptions: list[Assumption] = Field(default_factory=list)
    vulnerabilities: list[Vulnerability] = Field(default_factory=list)
    failure_modes: list[FailureMode] = Field(default_factory=list)
    loops: list[Loop] = Field(default_factory=list)
    risk_profile: RiskProfile | None = None
    validation: Validation | None = None


class PartialThreatModel(UnitThreatModel):
    """The persisted document shape at every write (S2 5.1).

    It is the complete schema with the empty section defaults: the store parses
    every write as this shape, and the completion checker is the only reader
    that requires the complete content.
    """


def unit_kind_from_unit_id(unit_id: str) -> UnitKind:
    """The unit kind from the kind-qualified L1 identity.

    A Service's identity is `Service:<business-function-slug>`; every other
    identity is a System's `(<kind>, <discriminator>)` form (bare for a
    singleton). This is the same derivation the hunting prompt projection uses
    (`hunting.llm`), kept here so the store never guesses an unbound identity.
    """
    return UnitKind.SERVICE if unit_id.startswith("Service:") else UnitKind.SYSTEM


def compute_risk_profile(loops: list[Loop]) -> RiskProfile:
    """The authoritative per-unit risk profile (S2 7.3).

    The total sums every loop's likelihood weight; the breakdown counts every
    loop by likelihood, including `none`. The modeller never authors this.
    """
    breakdown = {level: 0 for level in Likelihood}
    for loop in loops:
        breakdown[loop.likelihood] += 1
    return RiskProfile(
        total=sum(RISK_WEIGHTS[loop.likelihood] for loop in loops),
        breakdown=breakdown,
    )


def normalise_loops(loops: list[Loop]) -> list[Loop]:
    """The ranked order and the derived loop ids (S2 5.6).

    Stable sort by likelihood weight descending (ties keep the modeller's
    write order), then renumber `loop-1..n` in that order. Rank 1 is the
    highest likelihood.
    """
    ordered = sorted(loops, key=lambda loop: RISK_WEIGHTS[loop.likelihood], reverse=True)
    return [
        loop.model_copy(update={"id": f"loop-{rank}"})
        for rank, loop in enumerate(ordered, start=1)
    ]


def _check_necessary(model: UnitThreatModel) -> list[str]:
    """The fixed necessary-attribute set (S2 5.7), as dotted finding paths.

    The boundary is a pydantic-validated `UnitThreatModel`: `unit_kind` and
    the risk-factor values are already enum-checked by the schema, so no
    finding can exist for them and none is emitted (the store rejects an
    invalid shape at the write seam).
    """
    missing: list[str] = []
    sharpening = model.technical_sharpening
    if not model.unit_id:
        missing.append("unit_id")
    if not sharpening.interface_agreements:
        missing.append("technical_sharpening.interface_agreements")
    if not sharpening.control_flows:
        missing.append("technical_sharpening.control_flows")
    if not sharpening.data_flows:
        missing.append("technical_sharpening.data_flows")
    if not model.trust_model.trust_agreements:
        missing.append("trust_model.trust_agreements")
    if not model.trust_model.dynamic_state_trust.states:
        missing.append("trust_model.dynamic_state_trust.states")
    if not model.assumptions:
        missing.append("assumptions")
    for assumption in model.assumptions:
        fault = assumption.fault
        if not fault.id:
            missing.append(f"assumption:{assumption.id}.fault.id")
        if not fault.label:
            missing.append(f"assumption:{assumption.id}.fault.label")
        if not fault.description:
            missing.append(f"assumption:{assumption.id}.fault.description")
    if not model.vulnerabilities:
        missing.append("vulnerabilities")
    for vulnerability in model.vulnerabilities:
        if not vulnerability.canonical_class:
            missing.append(f"vulnerability:{vulnerability.id}.canonical_class")
        if not vulnerability.web_vulnerability_class and not vulnerability.suite_gap:
            missing.append(f"vulnerability:{vulnerability.id}.web_vulnerability_class")
    if not model.failure_modes:
        missing.append("failure_modes")
    for vulnerability in model.vulnerabilities:
        if vulnerability.dropped:
            continue
        if not any(
            failure_mode.vulnerability_ref == vulnerability.id
            for failure_mode in model.failure_modes
        ):
            missing.append(f"vulnerability:{vulnerability.id}.failure_modes")
    every_vulnerability_dropped = bool(model.vulnerabilities) and all(
        vulnerability.dropped for vulnerability in model.vulnerabilities
    )
    if not model.loops and not every_vulnerability_dropped:
        missing.append("loops")
    for loop in model.loops:
        if not loop.likelihood_rationale:
            missing.append(f"loop:{loop.id}.likelihood_rationale")
        if not loop.evidences:
            missing.append(f"loop:{loop.id}.evidences")
    weights = [RISK_WEIGHTS[loop.likelihood] for loop in model.loops]
    if any(left < right for left, right in zip(weights, weights[1:])):
        missing.append("loops.order")
    expected_ids = [f"loop-{rank}" for rank in range(1, len(model.loops) + 1)]
    if [loop.id for loop in model.loops] != expected_ids:
        missing.append("loops.ids")
    if model.risk_profile is None:
        missing.append("risk_profile")
    else:
        expected = compute_risk_profile(model.loops)
        if model.risk_profile != expected:
            if model.risk_profile.total != expected.total:
                missing.append("risk_profile.total")
            if model.risk_profile.breakdown != expected.breakdown:
                missing.append("risk_profile.breakdown")
    return missing


def _check_references(model: UnitThreatModel) -> list[str]:
    """The referential-integrity findings (S2 5.7), as dotted finding paths."""
    errors: list[str] = []
    sharpening = model.technical_sharpening
    dynamic = model.trust_model.dynamic_state_trust
    fault_ids = {assumption.fault.id for assumption in model.assumptions}
    vulnerability_ids = {vulnerability.id for vulnerability in model.vulnerabilities}
    vulnerability_index = {vulnerability.id: vulnerability for vulnerability in model.vulnerabilities}
    failure_mode_ids = {failure_mode.id for failure_mode in model.failure_modes}
    agreement_ids = {agreement.id for agreement in sharpening.interface_agreements}
    trust_agreement_ids = {
        agreement.id for agreement in model.trust_model.trust_agreements
    }
    state_ids = {state.id for state in dynamic.states}

    def unresolved(owner: str, field: str, ref: str) -> None:
        errors.append(f"{owner}.{field}={ref!r}")

    for vulnerability in model.vulnerabilities:
        if vulnerability.fault_ref not in fault_ids:
            unresolved(f"vulnerability:{vulnerability.id}", "fault_ref", vulnerability.fault_ref)
    for assumption in model.assumptions:
        if assumption.boundary_ref and assumption.boundary_ref not in trust_agreement_ids:
            unresolved(f"assumption:{assumption.id}", "boundary_ref", assumption.boundary_ref)
    for agreement in model.trust_model.trust_agreements:
        for ref in agreement.interface_agreement_refs:
            if ref not in agreement_ids:
                unresolved(f"trust_agreement:{agreement.id}", "interface_agreement_refs", ref)
    transition_ids = {transition.id for transition in dynamic.transitions}
    for transition in dynamic.transitions:
        for endpoint in (transition.source, transition.target):
            if endpoint not in state_ids:
                unresolved(f"transition:{transition.id}", "state_ref", endpoint)
    for violation in dynamic.violations:
        if violation.maps_to_fault not in fault_ids:
            unresolved(f"violation:{violation.id}", "maps_to_fault", violation.maps_to_fault)
        if violation.transition_ref and violation.transition_ref not in transition_ids:
            unresolved(f"violation:{violation.id}", "transition_ref",
                       violation.transition_ref)
    for failure_mode in model.failure_modes:
        if failure_mode.vulnerability_ref not in vulnerability_ids:
            unresolved(
                f"failure_mode:{failure_mode.id}", "vulnerability_ref",
                failure_mode.vulnerability_ref,
            )
    for loop in model.loops:
        if loop.fault_ref not in fault_ids:
            unresolved(f"loop:{loop.id}", "fault_ref", loop.fault_ref)
        if loop.vulnerability_ref not in vulnerability_ids:
            unresolved(f"loop:{loop.id}", "vulnerability_ref", loop.vulnerability_ref)
        for ref in loop.failure_mode_refs:
            if ref not in failure_mode_ids:
                unresolved(f"loop:{loop.id}", "failure_mode_refs", ref)
        vulnerability = vulnerability_index.get(loop.vulnerability_ref)
        if vulnerability is not None:
            if loop.canonical_class != vulnerability.canonical_class:
                unresolved(f"loop:{loop.id}", "canonical_class", loop.canonical_class)
            if loop.web_vulnerability_class != vulnerability.web_vulnerability_class:
                unresolved(
                    f"loop:{loop.id}", "web_vulnerability_class",
                    loop.web_vulnerability_class,
                )
            if loop.suite_gap != vulnerability.suite_gap:
                unresolved(f"loop:{loop.id}", "suite_gap", str(loop.suite_gap))
    return errors


def _check_closure(model: UnitThreatModel) -> list[str]:
    """The assumption-to-loop closure findings (S2 5.7), as dotted paths."""
    unclosed: list[str] = []
    vulnerability_index = {vulnerability.id: vulnerability for vulnerability in model.vulnerabilities}
    failure_mode_index = {failure_mode.id: failure_mode for failure_mode in model.failure_modes}
    for assumption in model.assumptions:
        if not any(
            vulnerability.fault_ref == assumption.fault.id
            for vulnerability in model.vulnerabilities
        ):
            unclosed.append(f"assumption:{assumption.id}")
    for vulnerability in model.vulnerabilities:
        if vulnerability.dropped:
            if not vulnerability.drop_reason:
                unclosed.append(f"vulnerability:{vulnerability.id}.drop_reason")
            if not vulnerability.drop_probe:
                unclosed.append(f"vulnerability:{vulnerability.id}.drop_probe")
            continue
        if not any(
            failure_mode.vulnerability_ref == vulnerability.id and not failure_mode.dropped
            for failure_mode in model.failure_modes
        ):
            unclosed.append(f"vulnerability:{vulnerability.id}.failure_modes")
        if not any(loop.vulnerability_ref == vulnerability.id for loop in model.loops):
            unclosed.append(f"vulnerability:{vulnerability.id}.loops")
    for loop in model.loops:
        if not loop.failure_mode_refs:
            unclosed.append(f"loop:{loop.id}.failure_mode_refs")
        vulnerability = vulnerability_index.get(loop.vulnerability_ref)
        if vulnerability is not None and vulnerability.dropped:
            unclosed.append(f"loop:{loop.id}.vulnerability_ref")
        for ref in loop.failure_mode_refs:
            failure_mode = failure_mode_index.get(ref)
            if failure_mode is not None and failure_mode.dropped:
                unclosed.append(f"loop:{loop.id}.failure_mode_refs")
    return unclosed


def check_completion(
    model: UnitThreatModel, *, checked_at: datetime | None = None
) -> Validation:
    """The non-blocking completion check (S2 5.7).

    It records the necessary-attribute, referential-integrity, and closure
    findings; `valid` is true only when the model parsed and all three finding
    lists are empty. The stored risk profile is REGRESSION-checked against a
    fresh recomputation from the loops, never trusted.

    The boundary is a pydantic-validated `UnitThreatModel`, so
    `Validation.parseable` is always true here: the store rejects an
    unparseable write at the write seam (S1 6.6) before any model reaches the
    checker. The flag stays on the record so a later caller that validates a
    raw document can report a parse failure without a schema change.
    """
    missing = _check_necessary(model)
    referential_errors = _check_references(model)
    unclosed = _check_closure(model)
    return Validation(
        checked_at=checked_at or datetime.now(timezone.utc),
        parseable=True,
        valid=not missing and not unclosed and not referential_errors,
        missing=missing,
        unclosed=unclosed,
        referential_errors=referential_errors,
    )


__all__ = [
    "Agreement",
    "Assumption",
    "AttackRequirements",
    "AttackVector",
    "Complexity",
    "Confidence",
    "DEFAULT_RISK_THRESHOLD",
    "DynamicState",
    "DynamicStateTrust",
    "Evidence",
    "EvidenceKind",
    "FailureMode",
    "Fault",
    "Feasibility",
    "GATE_SECTIONS",
    "Likelihood",
    "Loop",
    "ModelState",
    "PartialThreatModel",
    "PrivilegesRequired",
    "RISK_WEIGHTS",
    "RiskFactors",
    "RiskProfile",
    "SCHEMA_VERSION",
    "STATE_ORDER",
    "TechnicalSharpening",
    "Transition",
    "TrustAgreement",
    "TrustModel",
    "UnitKind",
    "UnitThreatModel",
    "Validation",
    "Violation",
    "ViolationKind",
    "Vulnerability",
    "check_completion",
    "compute_risk_profile",
    "normalise_loops",
    "unit_kind_from_unit_id",
]
