"""Shared hunting-agent fixtures (contract + isolated-e2e tiers).

The fixture collaborators at their contract boundaries (IA-2 through IA-8):
the symptom-technique KB, the pod, the spec-authoring turn, and the D5
continuation judgment - plus the canonical D4 spec fixtures and the inline
back-edge records. Owned here so the integration catalogue (C1-C17) and the
isolated e2e catalogue (E3-E9) speak the SAME canned fixtures and the
duplication stays in one place.

Applies everywhere in this module: the fixtures never outlive the seam
contract, e.g. `_kb` records every join key, `_pod` records every received
spec, and `_judge` asserts it is consulted only on a terminal
insufficient-evidence derivation (C-tested in the tier that needs it).
"""
from polymerhus.attack.hunting.hunt_orchestrator import (
    HuntConfig,
    HuntPromptTemplate,
)
from polymerhus.attack.hunting.hunting_agent import build_hunting_agent
from polymerhus.recon.control.targeted import (
    AnalyserReconRequest,
    ReconScope,
    TargetedReconResult,
)

SERVICE_A = "Service:slug:a"
FAULT_X = "fault-x"

# The D4 fixture the authoring turn returns (typed base + NL core, section 7).
SPEC = {
    "target_identity": "Service:slug:a via GET /api/a",
    "verification_symptoms": ["HTTP 200 with the reflected parameter value"],
    "testing_pattern": "csrf-probe baseline",
    "assumptions": ["public exposure", "no WAF on /api/a"],
    "payload_vector_space": {"parameter": "q", "encodings": ["urlencoded", "json"]},
    "rationale": "fixture rationale from the spec's H1",
    "interpretation_guidance": "fixture guidance: map each status to evidence",
}

# The re-authored D4 (INIT rejection): the failing attributes declined -
# verification symptom narrowed to the observable surface, the unsupported
# method dropped from the payload vector space.
SPEC_REAUTHORED = {
    "target_identity": "Service:slug:a via GET /api/a",
    "verification_symptoms": ["HTTP status code in the 2xx/4xx band"],
    "testing_pattern": "csrf-probe baseline",
    "assumptions": ["public exposure", "no WAF on /api/a"],
    "payload_vector_space": {"parameter": "q", "encodings": ["urlencoded"]},
    "rationale": "fixture rationale from the spec's H1",
    "interpretation_guidance": "fixture guidance: map each status to evidence",
}


def _kb(queries: list | None = None, *, result=None, raise_on: bool = False):
    """The fixture symptom-technique KB (IA-8): records every join key it was
    queried on; returns the canned result, an empty result, or raises."""
    record = queries if queries is not None else []

    def kb(query):
        record.append(query)
        if raise_on:
            raise RuntimeError("KB unavailable (fixture)")
        return result or {"symptoms": [], "probing_techniques": []}

    return kb


def _outcome(terminal_reason: str, *, verdict: str = "unsuccessful",
             evidence: dict | None = None, iterations: int = 1) -> dict:
    """One D5+D6 envelope a pod run returns (IA-4)."""
    return {
        "verdict": verdict,
        "evidence": {
            "terminal_reason": terminal_reason,
            "iterations": iterations,
            **(evidence or {}),
        },
    }


def _pod(calls: list | None = None, *, outcomes: list[dict] | None = None,
         raise_on: int | None = None):
    """The fixture pod (IA-3/IA-4): records every received spec, replays the
    canned outcomes in order, or raises on the n-th call (0-indexed)."""
    record = calls if calls is not None else []
    sequence = list(outcomes or [])

    def pod(spec):
        record.append(spec)
        if raise_on is not None and len(record) - 1 == raise_on:
            raise RuntimeError("pod turn exhausted (fixture)")
        return sequence.pop(0)

    return pod


def _author(specs: list[dict] | None = None, *, calls: list | None = None):
    """The fixture spec-authoring turn: records every received prompt text
    (the REAL composed system+user turn where the tier cares) and returns the
    canned D4 dicts; None signals the validation evidence is unaddressable."""
    record = calls if calls is not None else []
    sequence = list(specs or [SPEC])

    def author(text):
        record.append(text)
        if not sequence:
            return None
        return sequence.pop(0)

    return author


def _judge(judgments: list[dict], *, calls: list | None = None):
    """The fixture D5 continuation judgment: records every received prompt
    text and replays the canned judgments in order."""
    record = calls if calls is not None else []
    sequence = list(judgments)

    def judge(text):
        record.append(text)
        return sequence.pop(0)

    return judge


def _no_judge():
    def judge(text):
        raise AssertionError(
            "the D5 judgment must not be consulted on a terminal verdict")

    return judge


def _agent(store, run_id: str, *, kb=None, pod=None, author=None, judge=None, **kw):
    return build_hunting_agent(
        store=store, run_id=run_id, kb=kb, pod=pod,
        author=author, judge=judge, **kw,
    )


def _need(fault_class: str = FAULT_X, *, unit_id: str = SERVICE_A) -> AnalyserReconRequest:
    return AnalyserReconRequest(
        job="httpx_reprofile",
        scope=ReconScope(unit_id=unit_id, note=f"hunt gap on {fault_class}"),
        origin="hunting",
        requester_id="fixture-requester",
    )


def _route(need: AnalyserReconRequest) -> TargetedReconResult:
    """The orchestrator's IA-6 side of the inline back-edge (D67-14): the
    recon result routed back on the need's correlation_id."""
    return TargetedReconResult(
        correlation_id=need.correlation_id,
        requester_id=need.requester_id,
        origin="hunting",
        status="success",
        observations_merged=1,
    )