"""The triage phase state machine - the PURE layer (lifecycle v2, slice 4).

Mirrors `hunter_state.py`: one pure signal detector and one pure outcome
function over the observed gate call verbatim, plus the phase advance. No LLM,
no tool execution, no side effects - the harness (`triage.py`, slice 7) owns
the turns, the tool execution, and the acceptance of the gate result.

The phase machine observes what the model signalled; a malformed gate call maps
to no signal, so the phase stays put and the model receives a coded rejection
from the gate tool (slice 6). The pod graph's terminal node renders the
`PodExport` from the selected decision; the finalizer applies the monotonicity
rule.
"""
from __future__ import annotations

import logging
from typing import Any, Literal, TypedDict

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictStr,
    field_validator,
    model_validator,
)

from polymerhus.attack.hunting.pod.types import (
    DOMAIN_TERMINAL_REASONS,
    NO_SYMPTOM_EVIDENCE,
    SYMPTOM_ABSENT_CLASS,
    SYMPTOM_CONFIRMED,
    SYMPTOM_CONFIRMED_CLASS,
)
from polymerhus.attack.hunting.pod.variant_basis import (
    RUNNER_FAILURE,
    RUNNER_DIVERGENCE,
    VARIANT_BASES,
)

logger = logging.getLogger(__name__)

TriagePhase = Literal["assess", "decide", "done"]
"""The two-phase chain plus its terminal: ASSESS one turn, DECIDE one turn,
done. The pod's laps loop assess -> decide -> assess on the SAME thread."""

ASSESS_SIGNAL = "assessment"
DECIDE_SIGNAL = "decision"

_ASSESS_TOOL = "submit_assessment"
_DECIDE_TOOL = "submit_decision"


class AssessmentSubmission(BaseModel):
    """The `submit_assessment` gate payload. Extra keys are tolerated LLM slop;
    the known fields are strict, so a malformed submission validates as no
    signal (the gate then rejects it with a coded message)."""

    model_config = ConfigDict(extra="ignore")

    symptom_confirmed: StrictBool
    runner_diverged: StrictBool
    clean: StrictBool
    note: StrictStr


class DecisionSubmission(BaseModel):
    """The `submit_decision` gate payload: the terminal fields or the variant
    fields, never `clean` (the assessment owns it). The action-conditional
    fields are required per action, so an incomplete submission is malformed at
    the schema - no signal, and the gate's coded rejection names the fields."""

    model_config = ConfigDict(extra="ignore")

    action: Literal["terminate", "variant"]
    verdict: Literal["successful", "unsuccessful"] | None = None
    terminal_reason: StrictStr | None = None
    declined_attribute: StrictStr | None = None
    variant_spec: dict | None = None
    feedback: StrictStr | None = None
    covered_gap_classes: list[str] | None = None
    note: StrictStr

    @field_validator("terminal_reason")
    @classmethod
    def _reason_in_vocabulary(cls, value: str | None) -> str | None:
        if value is not None and value not in DOMAIN_TERMINAL_REASONS:
            raise ValueError(f"terminal_reason {value!r} is not a domain terminal")
        return value

    @field_validator("declined_attribute")
    @classmethod
    def _basis_in_vocabulary(cls, value: str | None) -> str | None:
        if value is not None and value not in VARIANT_BASES:
            raise ValueError(f"declined_attribute {value!r} is not a variant basis")
        return value

    @field_validator("variant_spec")
    @classmethod
    def _spec_is_mapping(cls, value: dict | None) -> dict | None:
        if value is not None and not isinstance(value, dict):
            raise ValueError("variant_spec must be a mapping")
        return value

    @model_validator(mode="after")
    def _action_fields(self) -> "DecisionSubmission":
        if self.action == "terminate":
            if self.verdict is None:
                raise ValueError("a terminate decision requires verdict")
            if self.terminal_reason is None:
                raise ValueError("a terminate decision requires terminal_reason")
        else:
            if not self.declined_attribute:
                raise ValueError("a variant decision requires declined_attribute")
        return self


class TriageFacts(TypedDict, total=False):
    """The harness facts one triage decision rides. Prompt material and graph
    state, never model fields. `runner_failed` is computed from the latest
    observation's raw fields; `runner_terminated` is the control-plane end
    reason (a kill makes `variant_allowed` false); `variant_allowed` is false
    too when no variant is mintable on this lap, and `variant_allowed_reason`
    names why (the no-mintable-procedure gap, the kill, or the lap cap)."""

    runner_failed: bool
    runner_exhausted: bool
    runner_terminated: str | None
    variant_allowed: bool
    variant_allowed_reason: str
    lap: int
    thread_id: str


class TriageDecision(TypedDict, total=False):
    """The decision the triage graph selects. Never a pod terminal: the pod
    graph's terminal node renders the `PodExport` from it."""

    action: Literal["terminate", "variant"]
    classification: str
    verdict: str
    terminal_reason: str
    clean: bool
    note: str
    declined_attribute: str
    variant_spec: dict
    feedback: str
    covered_gap_classes: list[str]


class TriageOutcome(TypedDict):
    """One detect node answer: an advance to the next phase, or the decision
    that ends the machine."""

    kind: Literal["decision", "advance"]
    decision: TriageDecision | None


def detect_triage_signal(tool_name: Any, args: Any) -> str | None:
    """Map one observed tool call to its phase signal, or None.

    A pure function of the observed call verbatim (tool name + args), validated
    against the gate schema itself: a malformed submission is no signal, so the
    phase stays put and the gate's coded rejection is the model's correction
    path. Never raises: garbage maps to None."""
    if not isinstance(args, dict):
        return None
    try:
        if tool_name == _ASSESS_TOOL:
            AssessmentSubmission.model_validate(args)
            return ASSESS_SIGNAL
        if tool_name == _DECIDE_TOOL:
            DecisionSubmission.model_validate(args)
            return DECIDE_SIGNAL
    except Exception as exc:  # noqa: BLE001 - detection never breaks the turn
        logger.debug("triage signal detection rejected %r (%s)", tool_name, exc)
        return None
    return None


def _terminate(verdict: str, reason: str, clean: bool, note: str) -> TriageDecision:
    return TriageDecision(action="terminate", verdict=verdict,
                          terminal_reason=reason, clean=clean,
                          classification=SYMPTOM_CONFIRMED_CLASS
                          if reason == SYMPTOM_CONFIRMED else SYMPTOM_ABSENT_CLASS,
                          note=note)


def _variant(basis: str, args: dict, note: str) -> TriageDecision:
    covered = args.get("covered_gap_classes")
    return TriageDecision(action="variant", classification=basis,
                          declined_attribute=basis,
                          variant_spec=dict(args.get("variant_spec") or {}),
                          feedback=str(args.get("feedback") or ""),
                          # An ABSENT coverage assessment stays None (the
                          # graph's rule: without one, the claimed basis
                          # stands); only a stated list is authoritative.
                          covered_gap_classes=(list(covered)
                                               if covered is not None else None),
                          note=note)


def detect_triage_outcome(facts: TriageFacts, assessment: dict | None,
                          signal: str, args: dict) -> TriageOutcome:
    """The detect node's pure rule, exactly the ratified tree:

    - assessment, runner-failed fact -> variant(runner-failure), done;
    - assessment, diverged           -> variant(runner-divergence), done;
    - assessment, confirmed          -> terminal(successful, symptom-confirmed), done;
    - assessment, negative           -> advance(decide);
    - decision, terminate            -> decision(verdict, reason), done;
    - decision, variant, allowed     -> decision(variant, basis), done;
    - decision, variant, not allowed -> decision(unsuccessful, no-symptom-evidence), done.

    The divergence judgement outranks a confirmation claim (the ASSESS
    verbatim: a diverged execution has no meaningful symptom coverage), and the
    runner-failed fact outranks both.

    The clean flag never comes from a decision submission: the assessment owns
    it, and EVERY terminate outcome - the not-allowed degrade included - rides
    the assessment's clean through.
    """
    if signal == ASSESS_SIGNAL:
        validated = AssessmentSubmission.model_validate(args)
        clean = validated.clean
        note = validated.note
        if facts.get("runner_failed"):
            return {"kind": "decision",
                    "decision": _variant(RUNNER_FAILURE, {}, note)}
        if validated.runner_diverged:
            return {"kind": "decision",
                    "decision": _variant(RUNNER_DIVERGENCE, {}, note)}
        if validated.symptom_confirmed:
            return {"kind": "decision",
                    "decision": _terminate("successful", SYMPTOM_CONFIRMED,
                                           clean, note)}
        return {"kind": "advance", "decision": None}

    if signal == DECIDE_SIGNAL:
        validated = DecisionSubmission.model_validate(args)
        note = validated.note
        # The decision gate carries no clean: the prior assessment's clean is
        # the pod's integrity judgement and rides into the terminal.
        clean = bool((assessment or {}).get("clean", False))
        if validated.action == "variant":
            if not facts.get("variant_allowed", False):
                reason = str(facts.get("variant_allowed_reason") or
                             "variant not allowed")
                return {"kind": "decision",
                        "decision": _terminate(
                            "unsuccessful", NO_SYMPTOM_EVIDENCE, clean,
                            f"[variant not allowed: {reason}; no variant minted] "
                            f"{note}".strip())}
            return {"kind": "decision",
                    "decision": _variant(validated.declined_attribute or "",
                                         args, note)}
        return {"kind": "decision",
                "decision": _terminate(validated.verdict or "unsuccessful",
                                       validated.terminal_reason or "",
                                       clean, note)}

    # Unreachable through the signal gate; defensive None-kind outcome.
    return {"kind": "advance", "decision": None}


def advance_triage_state(phase: TriagePhase, outcome: TriageOutcome) -> TriagePhase:
    """The advance node's pure rule: a decision ends the machine, an advance
    moves assess to decide. A defensive advance from decide stays put (a
    wrong-phase gate call can never skip the machine past its decision)."""
    if outcome.get("kind") == "decision":
        return "done"
    if phase == "assess":
        return "decide"
    return "done" if phase != "decide" else "decide"


__all__ = [
    "AssessmentSubmission",
    "DecisionSubmission",
    "TriageDecision",
    "TriageFacts",
    "TriageOutcome",
    "TriagePhase",
    "advance_triage_state",
    "detect_triage_outcome",
    "detect_triage_signal",
]
