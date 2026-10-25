"""The per-threat hunter payload (S2 8.2; T4 #377).

The surfer materialises ONE payload per threat file at DISPATCH time - never at
model time: the model document and the threat file are the durable artifacts, and
the payload is the dispatch-shaped projection of them that the hunter consumes.

The payload carries (S2 8.2):

- the threat record;
- the unit id and unit kind;
- the relevant technical sharpening: the interface agreements referenced by the
  trust agreement, plus the control-flow and data-flow overview;
- the relevant trust agreement, and - when a trust-transition violation maps to
  the threat's fault - the dynamic-state transition and its violation;
- the programming fault;
- the canonical class and the web vulnerability class;
- the evidence pointers from the threat, including any recorded HTTP-history
  artifact ids, so the hunter can choose a baseline;
- the likelihood and the vulnerability-level rationale;
- the confidence degree;
- the target context the spec's target identity is authored from (the unit
  identity, and the request/http-history refs the threat grounds on).

It does NOT carry (S2 8.2): any narrowed vector or payload, a
`HuntConfig`, or a pre-authored payload vector space. The rationale stays
vulnerability-level, so the hunter keeps the room to engineer its own procedure.
The key set is exactly the list above (T4a review F4): the importing assumption
record and the threat's `suite_gap` flag are NOT separate payload fields - the
programming fault carries the fault, and the threat record the hunter receives
already carries `suite_gap`.

PURE by construction (CODING_STANDARD s3): the model document and the threat
record go in, one dict comes out; no I/O, no clock, no LLM. Every lookup is
fail-open and deterministic - a missing assumption, boundary, transition or
violation degrades that ONE payload field to None/empty, never raising into the
dispatch tick (the mover would read a raise as a refusal and the run would
hot-loop the same threat file).
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = ["materialise_hunter_payload"]


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


def _baseline_refs(evidences: Sequence[Any]) -> list[str]:
    """The refs a baseline can be chosen from: the threat's request records and
    its HTTP-history artifact ids (S2 8.2). Ordered and deduplicated."""
    refs: list[str] = []
    for evidence in evidences:
        if not isinstance(evidence, Mapping):
            continue
        if evidence.get("kind") not in ("request", "http_history"):
            continue
        ref = evidence.get("ref")
        if isinstance(ref, str) and ref and ref not in refs:
            refs.append(ref)
    return refs


def materialise_hunter_payload(
    model: Mapping,
    threat_file: Mapping,
    *,
    dispatch_id: str,
) -> dict:
    """The hunter payload for ONE threat file (S2 8.2). `model` is the unit's
    COMPLETED model document, `threat_file` the produced threat file's body (the
    mover's dispatch record, S2 8.1). Pure and fail-open."""
    threat = dict(threat_file.get("threat") or {})
    # The impact is hunter context. The derived impact weight and threat risk are
    # dispatch concerns; the hunter does not reason over the score.
    for derived in ("impact_weight", "risk"):
        threat.pop(derived, None)
    fault_ref = str(threat.get("fault_ref") or "")
    assumption = _assumption_for_fault(model, fault_ref)
    trust_model = model.get("trust_model") or {}
    trust_agreement = _by_id(trust_model.get("trust_agreements"), (assumption or {}).get("boundary_ref"))
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
        "likelihood": str(threat_file.get("likelihood") or threat.get("likelihood") or ""),
        "likelihood_rationale": str(threat.get("likelihood_rationale") or ""),
        "vulnerability_rationale": str(vulnerability.get("characterisation") or ""),
        "confidence": str(threat.get("confidence") or ""),
        "target_context": {
            "unit_id": unit_id,
            "unit_kind": unit_kind,
            "baseline_refs": _baseline_refs(evidences),
        },
    }
