"""The triage gate tools - the pure validators (lifecycle v2, slice 6).

A gate is a real tool call the model submits its phase output through. The gate
body validates the submission and returns a coded acceptance or rejection; it
never mutates the trial state and it never advances the phase. The harness
accepts the signal only when the gate result says it accepted the call
(`gate_accepted`), mirroring the hunter's authoritative exits: a coded
rejection persists no exit, so it is no signal and the phase stays put.

The schemas are the pydantic gate models in `triage_state.py` - the one source
of truth. The request-side tool definitions are projected from those models
directly, so the JSON schema the model sees can never drift from what the gate
validates.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from polymerhus.attack.hunting.pod.triage_state import (
    AssessmentSubmission,
    DecisionSubmission,
)
from polymerhus.attack.hunting.pod.types import SPACE_EXHAUSTED

logger = logging.getLogger(__name__)

ASSESSMENT_TOOL = "submit_assessment"
DECISION_TOOL = "submit_decision"

_ASSESSMENT_DESCRIPTION = (
    "Submit the ASSESS phase output: your confirmation, divergence, clean, and "
    "note judgments. One call ends the phase.")
_DECISION_DESCRIPTION = (
    "Submit the DECIDE phase output: terminate with the honest terminal, or "
    "mint ONE new falsifiable variant. One call ends the phase.")


def gate_accepted(result: Any) -> bool:
    """Whether one gate tool result accepted the call. Never raises: a
    malformed result is not an acceptance."""
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            return False
    return isinstance(result, dict) and result.get("accepted") is True


class _GateTool:
    """One gate: a duck-typed tool the harness's `invoke_tool` executes.

    Validation failures come back as a coded rejection string - never a raise -
    so the model always receives a readable correction path."""

    name: str
    description: str
    _validator: Any

    def __init__(self, name: str, description: str, validator) -> None:
        self.name = name
        self.description = description
        self._validator = validator

    def invoke(self, args: Mapping | None) -> str:
        try:
            return self._validator(dict(args or {}))
        except Exception as exc:  # noqa: BLE001 - a gate never raises into the turn
            return json.dumps({"error": "rejected", "tool": self.name,
                               "detail": str(exc), "accepted": False})

    async def ainvoke(self, args: Mapping | None) -> str:
        return self.invoke(args)


def _accept(signal: str, message: str = "") -> str:
    return json.dumps({"accepted": True, "signal": signal, "message": message})


def _reject(tool: str, detail: str) -> str:
    return json.dumps({"error": "rejected", "tool": tool,
                       "detail": detail, "accepted": False})


def _validate_assessment(facts: Mapping, args: dict) -> str:
    AssessmentSubmission.model_validate(args)
    return _accept("assessment")


def _validate_decision(facts: Mapping, assessment: Mapping | None,
                       args: dict) -> str:
    submission = DecisionSubmission.model_validate(args)
    if submission.action == "variant":
        terminated = facts.get("runner_terminated")
        if terminated:
            return _reject(
                DECISION_TOOL,
                f"the runner is terminated ({terminated}); a variant cannot "
                "run on a dead control plane - terminate with the honest "
                "terminal instead")
        return _accept("decision")
    if submission.terminal_reason == SPACE_EXHAUSTED:
        clean = bool((assessment or {}).get("clean", False))
        if not clean:
            # The coherence rule, enforced at the gate (ratified): a
            # space-exhausted claim over unclean observations must not emerge.
            # Unclean observations are the canonical PARTIAL COVERAGE case, so
            # the corrections are a variant for the unobserved execution modes
            # or the honest no-symptom-evidence terminal.
            return _reject(
                DECISION_TOOL,
                "space-exhausted over clean=false is a contradiction: unclean "
                "observations are PARTIAL COVERAGE, not an exhausted space. "
                "Mint a variant that covers the unobserved execution modes, or "
                "terminate with no-symptom-evidence")
    return _accept("decision")


def build_triage_gate_tools(facts: Mapping,
                            assessment: Mapping | None = None) -> dict[str, Any]:
    """The two gate tools for one triage decision, closed over the harness
    facts and the assessment the decision rides.

    `assessment` is the accepted ASSESS submission (the graph state carries it
    across laps); the DECIDE gate reads its `clean` for the space-exhausted
    coherence rule and nothing else."""
    return {
        ASSESSMENT_TOOL: _GateTool(
            ASSESSMENT_TOOL, _ASSESSMENT_DESCRIPTION,
            lambda args: _validate_assessment(facts, args)),
        DECISION_TOOL: _GateTool(
            DECISION_TOOL, _DECISION_DESCRIPTION,
            lambda args: _validate_decision(facts, assessment, args)),
    }


def triage_request_tools() -> list[dict]:
    """The request-side OpenAI tool dicts for the constant tool surface,
    projected from the gate models themselves - the schema the model sees is
    the schema the gate validates, byte for byte."""
    return [
        {"type": "function",
         "function": {"name": ASSESSMENT_TOOL,
                      "description": _ASSESSMENT_DESCRIPTION,
                      "parameters": AssessmentSubmission.model_json_schema()}},
        {"type": "function",
         "function": {"name": DECISION_TOOL,
                      "description": _DECISION_DESCRIPTION,
                      "parameters": DecisionSubmission.model_json_schema()}},
    ]


__all__ = [
    "ASSESSMENT_TOOL",
    "DECISION_TOOL",
    "build_triage_gate_tools",
    "gate_accepted",
    "triage_request_tools",
]
