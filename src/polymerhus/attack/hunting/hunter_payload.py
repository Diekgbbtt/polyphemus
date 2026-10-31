"""The per-threat hunter payload (S2 8.2; T5 #408; CVSS 4.0 spec 9).

The surfer materialises ONE payload per threat file at DISPATCH time - never at
model time: the model document and the threat file are the durable artifacts, and
the payload is the dispatch-shaped projection of them that the hunter consumes.

The payload carries (spec 9):

- the threat's derived risk: the float `risk`, its `severity_band`, the
  `risk_vector`, and the eight factors with their values, so the hunter knows
  why the threat was prioritised;
- the assessment prose: the `impact_description` (the shared end damage) and the
  `exploitability_description` (the chain, its capabilities, and its human
  participation);
- the capability, its id, and its `capability_path`;
- the threat's `enabling_precursors` - the ordered (capability, provider) pairs
  that reach the damage;
- the unit model's assumptions, each with its confidence and its evidence refs,
  so the hunter plans its verification probes and never duplicates an unverified
  premise;
- the unit context: the relevant technical sharpening, the trust agreement (or
  the dynamic-state transition and its violation), the programming fault, the two
  classes, the vulnerability-level rationale, the threat's evidences, and the
  target context the spec's target identity is authored from.

It does NOT carry (S2 8.2): any narrowed vector or payload, a `HuntConfig`, or a
pre-authored payload vector space. The rationale stays vulnerability-level, so
the hunter keeps the room to engineer its own procedure. It also never renders
the RETIRED vocabulary: no likelihood, no likelihood rationale, no threat
confidence, and no threat-side CIA block. The key set is exactly the list above
plus the v5 threat fields.

PURE by construction (CODING_STANDARD s3): the model document and the threat
record go in, one dict comes out; no I/O, no clock, no LLM. Every unit-context
lookup is fail-open and deterministic - a missing assumption, boundary,
transition or violation degrades that ONE payload field to None/empty, never
raising into the dispatch tick. The ASSESSMENT is the one exception: the store
emits a threat file only for a threat whose `impact_ref` resolves to a `threat`
row, so a missing (or mismatched) assessment block is a malformed v5 file, not a
degradation. Rendering an empty assessment would dispatch a hunter with no damage
claim, so it raises the coded `HunterPayloadError` instead - the mover reads a
raising builder as a refused dispatch and retries it, never a silent empty block.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from polymerhus.attack.hunting.risk_score import severity_band
from polymerhus.attack.hunting.threat_model import Threat

__all__ = ["HunterPayloadError", "materialise_hunter_payload"]

# The coded defects of a threat file that cannot become a payload. `code` is the
# stable machine name the log line and the operator read.
MISSING_ASSESSMENT = "hunter_payload_missing_assessment"
INCOMPLETE_FACTORS = "hunter_payload_incomplete_factors"

# The eight authored CVSS 4.0 base factors, in the vector's order. The derived
# subsequent-system mirrors (`SC/SI/SA`) are not factors: the vector carries them.
_FACTOR_FIELDS: tuple[str, ...] = (
    "attack_vector",
    "attack_complexity",
    "attack_requirements",
    "privileges_required",
    "user_interaction",
    "confidentiality",
    "integrity",
    "availability",
)

# The v5 threat fields the payload carries, taken from the schema itself so the
# projection cannot drift from it. It is a WHITELIST, not a strip list: a stale or
# foreign threat record can never reintroduce the retired v4 vocabulary (ADR 6).
_THREAT_FIELDS: tuple[str, ...] = tuple(Threat.model_fields)


class HunterPayloadError(ValueError):
    """A threat file that cannot become a payload (a coded dispatch defect).

    `code` names the defect for the log line and the operator; the message names
    the dispatch id so the offending file is identifiable without a stack read.
    """

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _by_id(items: Any, ident: Any) -> dict | None:
    """The first mapping in `items` whose `id` is `ident` (the model's records
    are id-keyed lists, S2 5.1)."""
    if not ident:
        return None
    for item in _as_list(items):
        if isinstance(item, Mapping) and item.get("id") == ident:
            return dict(item)
    return None


def _assumption_for_fault(model: Mapping, fault_ref: str) -> dict | None:
    """The assumption that carries the threat's fault (`assumptions[].fault.id`,
    the fault index of the completion checker, S2 5.7)."""
    for assumption in _as_list(model.get("assumptions")):
        if not isinstance(assumption, Mapping):
            continue
        fault = assumption.get("fault")
        if isinstance(fault, Mapping) and fault.get("id") == fault_ref:
            return dict(assumption)
    return None


def _transition_for_violation(model: Mapping, violation: Mapping | None) -> dict | None:
    """The transition the violation bounds (S2 5.1, S3 8.2).

    The schema link is `Violation.transition_ref`: a valid ref selects exactly
    that transition. An absent ref is unambiguous only when the dynamic-state
    model carries at most one transition (zero -> no transition, one -> that
    transition); with several transitions an absent ref yields NO transition -
    the payload records the gap (`dynamic_state.transition` is None) instead of
    guessing the first one. An invalid ref is a completion-checker referential
    error; here it degrades to None (the payload is never a gate)."""
    if not violation or violation.get("kind") != "trust-transition":
        return None
    transitions = [
        transition for transition in _as_list(
            (model.get("trust_model") or {}).get("dynamic_state_trust", {}).get("transitions")
        )
        if isinstance(transition, Mapping)
    ]
    ref = violation.get("transition_ref")
    if isinstance(ref, str) and ref:
        for transition in transitions:
            if transition.get("id") == ref:
                return dict(transition)
        return None
    if len(transitions) == 1:
        return dict(transitions[0])
    return None


def _refs(evidences: Any) -> list[str]:
    """The ordered, deduplicated non-empty `ref` strings of an evidence list."""
    refs: list[str] = []
    for evidence in _as_list(evidences):
        if not isinstance(evidence, Mapping):
            continue
        ref = evidence.get("ref")
        if isinstance(ref, str) and ref and ref not in refs:
            refs.append(ref)
    return refs


def _baseline_refs(evidences: Sequence[Any]) -> list[str]:
    """The refs a baseline can be chosen from: the threat's request records and
    its HTTP-history artifact ids (S2 8.2). Ordered and deduplicated."""
    return _refs([
        evidence for evidence in evidences
        if isinstance(evidence, Mapping)
        and evidence.get("kind") in ("request", "http_history")
    ])


def _assumption_context(model: Mapping) -> list[dict]:
    """The unit model's assumptions projected for the hunter (ADR 5, spec 9).

    Confidence is a verification-planning attribute: it tells the hunter which
    premises to probe and never feeds the score. The evidence refs ride with it
    so a probe starts from the grounding the modeller already holds.
    """
    context: list[dict] = []
    for assumption in _as_list(model.get("assumptions")):
        if not isinstance(assumption, Mapping):
            continue
        fault = assumption.get("fault")
        fault_ref = fault.get("id") if isinstance(fault, Mapping) else None
        context.append({
            "id": str(assumption.get("id") or ""),
            "statement": str(assumption.get("statement") or ""),
            "fault_ref": str(fault_ref or ""),
            "boundary_ref": str(assumption.get("boundary_ref") or ""),
            "confidence": str(assumption.get("confidence") or ""),
            "evidence_refs": _refs(assumption.get("evidences")),
        })
    return context


def _enabling_precursors(threat: Mapping) -> list[list]:
    """The threat's ordered (capability, provider) pairs, normalised to two
    elements so a v3 self-provided chain reads the same as a v5 pair."""
    pairs: list[list] = []
    for pair in _as_list(threat.get("enabling_precursors")):
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            capability, provider = pair
            pairs.append([
                str(capability or ""),
                str(provider) if provider is not None else None,
            ])
    return pairs


def _assessment(
    threat_file: Mapping, threat: Mapping, dispatch_id: str,
) -> dict:
    """The threat file's denormalised assessment block (spec 9, S2 8.1).

    The block is the threat's ONE resolved `threat` assessment: the store writes
    the file only when `impact_ref` resolves, so its absence or a `impact_ref`
    disagreement is a malformed file. The payload never repairs it into an empty
    block: the hunter would then hunt a damage claim it was never shown.
    """
    assessment = threat_file.get("impact")
    if not isinstance(assessment, Mapping) or not assessment:
        raise HunterPayloadError(
            MISSING_ASSESSMENT,
            f"threat file {dispatch_id} carries no impact assessment block",
        )
    declared = str(threat.get("impact_ref") or "")
    carried = str(assessment.get("impact_ref") or "")
    if declared and carried and declared != carried:
        raise HunterPayloadError(
            MISSING_ASSESSMENT,
            f"threat file {dispatch_id} carries assessment {carried} but the "
            f"threat references {declared}",
        )
    return dict(assessment)


def _factors(assessment: Mapping, dispatch_id: str) -> dict[str, str]:
    """The eight factor values, in the vector's order.

    A typed v5 row always carries all eight; a partial set would render a hunter
    a score it cannot audit, so it raises the coded defect instead.
    """
    raw = assessment.get("factors")
    factors = raw if isinstance(raw, Mapping) else {}
    missing = [name for name in _FACTOR_FIELDS if not factors.get(name)]
    if missing:
        raise HunterPayloadError(
            INCOMPLETE_FACTORS,
            f"threat file {dispatch_id} assessment misses factors {missing}",
        )
    return {name: str(factors[name]) for name in _FACTOR_FIELDS}


def _risk(threat_file: Mapping, threat: Mapping) -> float:
    """The threat's derived float score. An unreadable value degrades to `0.0`:
    the mover refuses such a file before dispatch, so this is not a gate."""
    for value in (threat_file.get("risk"), threat.get("risk")):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return round(float(value), 2)
    return 0.0


def materialise_hunter_payload(
    model: Mapping,
    threat_file: Mapping,
    *,
    dispatch_id: str,
) -> dict:
    """The hunter payload for ONE threat file (spec 9). `model` is the unit's
    COMPLETED model document, `threat_file` the produced threat file's body (the
    mover's dispatch record, S2 8.1). Pure; the unit context is fail-open, the
    assessment is required (see the module docstring)."""
    threat = dict(threat_file.get("threat") or {})
    threat = {
        field: threat[field] for field in _THREAT_FIELDS if field in threat
    }
    fault_ref = str(threat.get("fault_ref") or "")
    assessment = _assessment(threat_file, threat, dispatch_id)
    factors = _factors(assessment, dispatch_id)
    risk = _risk(threat_file, threat)
    assumption = _assumption_for_fault(model, fault_ref)
    trust_model = model.get("trust_model") or {}
    trust_agreement = _by_id(
        trust_model.get("trust_agreements"), (assumption or {}).get("boundary_ref"))
    sharpening = model.get("technical_sharpening") or {}
    if trust_agreement is not None:
        interface_agreements = [
            agreement for agreement in _as_list(sharpening.get("interface_agreements"))
            if isinstance(agreement, Mapping)
            and agreement.get("id") in _as_list(trust_agreement.get("interface_agreement_refs"))
        ]
    else:
        # No boundary resolves (an assumption without one, or a dynamic-state
        # fault): the sharpening overview stands in, so the hunter is never left
        # without the interface agreements.
        interface_agreements = [
            agreement for agreement in _as_list(sharpening.get("interface_agreements"))
            if isinstance(agreement, Mapping)
        ]
    dynamic_state = trust_model.get("dynamic_state_trust") or {}
    violation = next(
        (
            dict(candidate) for candidate in _as_list(dynamic_state.get("violations"))
            if isinstance(candidate, Mapping)
            and candidate.get("maps_to_fault") == fault_ref
        ),
        None,
    )
    transition = _transition_for_violation(model, violation)
    evidences = _as_list(threat.get("evidences"))
    vulnerability = _by_id(model.get("vulnerabilities"), threat.get("vulnerability_ref")) or {}
    unit_id = str(model.get("unit_id") or threat_file.get("unit_id") or "")
    unit_kind = str(model.get("unit_kind") or threat_file.get("unit_kind") or "")
    return {
        "dispatch_id": dispatch_id,
        "run_id": str(threat_file.get("run_id") or model.get("run_id") or ""),
        "threat_id": str(threat_file.get("threat_id") or threat.get("id") or ""),
        "unit_id": unit_id,
        "unit_kind": unit_kind,
        # The derived risk: the hunter reads why this threat was prioritised.
        "risk": risk,
        "severity_band": severity_band(risk).value,
        "risk_vector": str(assessment.get("risk_vector") or ""),
        "factors": factors,
        # The assessment prose, its capability, and the chain that reaches it.
        "impact_description": str(assessment.get("impact_description") or ""),
        "exploitability_description": str(
            assessment.get("exploitability_description") or ""),
        "capability": str(assessment.get("capability") or ""),
        "capability_id": str(assessment.get("capability_id") or ""),
        "capability_path": [
            str(ref) for ref in _as_list(assessment.get("capability_path"))
        ],
        "enabling_precursors": _enabling_precursors(threat),
        # The unit model's premise set and its verification-planning confidence.
        "assumptions": _assumption_context(model),
        "threat": threat,
        "technical_sharpening": {
            "interface_agreements": interface_agreements,
            "control_flows": _as_list(sharpening.get("control_flows")),
            "data_flows": _as_list(sharpening.get("data_flows")),
        },
        "trust_agreement": trust_agreement,
        "dynamic_state": (
            {"transition": transition, "violation": violation}
            if transition is not None or violation is not None else None
        ),
        "programming_fault": dict((assumption or {}).get("fault") or {}),
        "canonical_class": str(threat.get("canonical_class") or ""),
        "web_vulnerability_class": str(threat.get("web_vulnerability_class") or ""),
        "evidence": evidences,
        "vulnerability_rationale": str(vulnerability.get("characterisation") or ""),
        "target_context": {
            "unit_id": unit_id,
            "unit_kind": unit_kind,
            "baseline_refs": _baseline_refs(evidences),
        },
    }
