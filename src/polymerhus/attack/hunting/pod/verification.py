"""The harness verification component (operator, 2026-08-06).

A deterministic guardrail over whatever the (non-deterministic) agents produce,
so the pod's binary-terminal + D5/D6-envelope contract holds no matter what an
LLM emits. Three responsibilities:

  1. `validate_spec` - the INIT schema gate (Phase 0). Ranges over the D4 typed
     base only (D67-10); a structural violation is collected as an
     `init_validation` string and the pod rejects with ZERO tool calls (C1).
  2. `validate_probe_chain` - the runner's authored probe is well-formed before
     it is executed against the live target.
  3. `validate_decision` - the triager's terminal decision conforms (a verdict
     in the binary set, a terminal_reason in the Q3-amended vocabulary, `clean`
     a bool). A malformed decision degrades to a safe honest terminal rather
     than corrupting the envelope.

This module is pure and DB/LLM-free (unit-tier safe).
"""
from __future__ import annotations

from polymerhus.attack.hunting.pod.types import (
    ProbeChain,
    TERMINAL_REASONS,
    TestImplementationSpec,
)


def validate_spec(spec: dict | TestImplementationSpec) -> list[str]:
    """The INIT schema gate (Phase 0): return the structural violations of the
    D4 typed base (D67-10). An empty list means the schema is clean. Ranges over
    the MANDATORY typed base only - the NL fields (rationale, interpretation
    guidance) are not part of it, and an EMPTY `payload_vector_space` is valid
    (O12: the pattern's default probe still runs once), only a non-dict is a
    violation. No tool call is made here (C1)."""
    if isinstance(spec, TestImplementationSpec):
        model = spec
        raw = spec.model_dump()
    else:
        raw = dict(spec or {})
        try:
            model = TestImplementationSpec(**raw)
        except Exception as exc:  # noqa: BLE001 - a shape the model cannot even parse
            return [f"spec is not a valid TestImplementationSpec: {exc}"]

    violations: list[str] = []
    if not model.target_identity.url.strip():
        violations.append(
            "target_identity.url is empty (the base URL the pod probes; "
            "author it as {'url': <base url>, 'unit_id': <L1 identity>})"
        )
    if not [s for s in model.verification_symptoms if str(s).strip()]:
        violations.append(
            "verification_symptoms is empty (the load-bearing predicate the "
            "test would confirm)"
        )
    if not model.testing_pattern.strip():
        violations.append("testing_pattern is empty")
    # payload_vector_space may be an EMPTY dict (O12) but must be a dict.
    if not isinstance(raw.get("payload_vector_space", {}), dict):
        violations.append("payload_vector_space is malformed (must be an object)")
    return violations


def validate_probe_chain(chain: ProbeChain | dict | None) -> list[str]:
    """The runner-output guard: a probe chain must carry at least one step, and
    exactly one core payload-carrying call. Returns the violations (empty =
    well-formed)."""
    if chain is None:
        return ["no probe chain authored"]
    if isinstance(chain, dict):
        try:
            chain = ProbeChain(**chain)
        except Exception as exc:  # noqa: BLE001
            return [f"probe chain is malformed: {exc}"]
    violations: list[str] = []
    if not chain.steps:
        violations.append("probe chain has no steps")
    cores = [s for s in chain.steps if s.role == "core"]
    if len(cores) != 1:
        violations.append(
            f"probe chain must carry exactly one core call (found {len(cores)})"
        )
    for step in chain.steps:
        if not (step.url or step.command):
            violations.append("a probe step has neither a url nor a command")
    return violations


def validate_decision(decision: dict | None) -> list[str]:
    """The triager-output guard: a terminal decision must carry a binary verdict,
    a terminal_reason from the Q3-amended vocabulary, and a boolean `clean`.
    Returns the violations (empty = conformant)."""
    if not isinstance(decision, dict):
        return ["decision is not a mapping"]
    violations: list[str] = []
    verdict = decision.get("verdict")
    if verdict not in ("successful", "unsuccessful"):
        violations.append(f"verdict {verdict!r} is not one of successful/unsuccessful")
    reason = decision.get("terminal_reason")
    if reason not in TERMINAL_REASONS:
        violations.append(f"terminal_reason {reason!r} is not in the Q3-amended vocabulary")
    if not isinstance(decision.get("clean"), bool):
        violations.append("clean must be a boolean")
    return violations
