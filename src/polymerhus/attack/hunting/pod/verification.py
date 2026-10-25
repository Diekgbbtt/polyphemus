"""The harness verification component (operator, 2026-08-06).

A deterministic guardrail over whatever the (non-deterministic) agents produce,
so the pod's binary-terminal + D5/D6-envelope contract holds no matter what an
LLM emits. Three responsibilities:

  1. `validate_spec` - the INIT schema gate (Phase 0). Ranges over the reduced
     D4 surface (S5 8.4); the mandatory set is exactly a non-empty
     `target_identity.url` and at least one non-blank verification symptom.
     Every violation is collected into ONE `init_validation` rejection and the
     pod executes ZERO tool calls (C1). The three retired fields are rejected
     as unknown, never silently dropped.
  2. `validate_probe_chain` - the runner's authored probe is well-formed before
     it is executed against the live target.
  3. `validate_decision` - the triager's terminal decision conforms (a verdict
     in the binary set, a terminal_reason in the Q3-amended vocabulary, `clean`
     a bool). A malformed decision degrades to a safe honest terminal rather
     than corrupting the envelope.

This module is pure and DB/LLM-free (unit-tier safe).
"""
from __future__ import annotations

from pydantic import ValidationError

from polymerhus.attack.hunting.pod.types import (
    ProbeChain,
    TargetIdentity,
    TERMINAL_REASONS,
    TestImplementationSpec,
)

_MANDATORY_FIELDS = ("target_identity", "verification_symptoms")


def _shape_violations(raw: dict) -> list[str]:
    """The D4 parse errors the gate reports (S5 8.4, S5 8.8): an unknown field
    (the retired three included) is rejected by name, and any other wrong-typed
    field is reported.

    Only a ROOT-level error under a mandatory field is skipped - the explicit
    checks below emit a better message for a missing URL or an empty symptom
    list. A NESTED error under them is kept: a mixed symptom list
    (`["ok", 3]`) has a non-blank string and would otherwise pass the
    emptiness check while failing the `list[str]` parse the gate is meant to
    be."""
    try:
        TestImplementationSpec(**raw)
    except ValidationError as exc:
        out: list[str] = []
        for err in exc.errors():
            loc = tuple(err.get("loc") or ())
            if len(loc) == 1 and loc[0] in _MANDATORY_FIELDS:
                continue
            name = ".".join(str(part) for part in loc) or "<spec>"
            if err.get("type") == "extra_forbidden":
                out.append(
                    f"{name} is not a field of the reduced D4 (retired or "
                    "unknown field)"
                )
            else:
                out.append(f"{name}: {err.get('msg')}")
        return out
    return []


def validate_spec(spec: dict | TestImplementationSpec) -> list[str]:
    """The INIT schema gate (Phase 0): return the structural violations of the
    REDUCED D4 (S5 8.4). An empty list means the schema is clean.

    The mandatory set is EXACTLY a non-empty `target_identity.url` and at least
    one non-blank `verification_symptoms` entry; every other field is optional.
    All violations are collected into one rejection - the hunter corrects the
    spec in one pass. The three retired fields are rejected as unknown. No tool
    call is made here (C1), and the gate never probes the URL."""
    if isinstance(spec, TestImplementationSpec):
        raw = spec.model_dump()
        violations: list[str] = []
    else:
        raw = dict(spec or {})
        violations = _shape_violations(raw)

    identity = raw.get("target_identity")
    if isinstance(identity, TargetIdentity):
        identity = identity.model_dump()
    if not isinstance(identity, dict):
        violations.append(
            "target_identity is malformed (author it as {'url': <base url>, "
            "'unit_id': <L1 identity>})"
        )
    elif not isinstance(identity.get("url"), str) or not identity["url"].strip():
        violations.append(
            "target_identity.url is empty (the base URL the pod probes; "
            "author it as {'url': <base url>, 'unit_id': <L1 identity>})"
        )

    symptoms = raw.get("verification_symptoms")
    if not isinstance(symptoms, list) or not any(
            isinstance(s, str) and s.strip() for s in symptoms):
        violations.append(
            "verification_symptoms is empty (the concrete observable failure "
            "mode the test would confirm)"
        )
    return violations


def init_route(violations: Sequence[str] | None) -> str:
    """The pod INIT route: `reject` only when no probe URL exists.

    Every other violation is recorded on the PodExport and the runner still
    attempts a probe. This is the malformed fail-safe: a partial body must not
    become a queue halt, and a consumed malformed spec must still land an
    export. A spec without a URL cannot make a single call, so it stops.
    """
    for violation in violations or ():
        if "target_identity.url" in str(violation):
            return "reject"
    return "runner"


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
        if not (step.url or step.command or step.request_ref):
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
