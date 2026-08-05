"""Integration tier: the hunting-agent assertion catalogue C1-C17
(hunting-67-hunting-agent-spec.md section 6.1, Q3-amended).

The contract predicates exercise the agent's EXTERNAL behaviour through the
seams - dispatch (IA-2) -> KB query (IA-8) -> spec authoring (D4) -> pod
handoff (IA-3) -> verdict derivation (D67-02) -> store (S7) - never the
internals of a single pass. Every out-of-tree collaborator is injected: the
symptom-technique KB, the pod, the spec-authoring turn, and the D5
continuation judgment all arrive as fixtures; the real KB and the real pod
(#84) are sibling tickets, and the real chain is walked in the e2e tier
(E1-E2, blocked). The hunt store is the REAL append-only markdown stub, and
the agent writes exactly the two record kinds Q6 declares (`spec` and
`evidence`) through it.

The seam contract (what the harness must expose):
  build_hunting_agent(*, store, run_id, kb, pod, author, judge, axis=None)
      -> dispatch_fn(config: HuntConfig, routed=()) -> DispatchResult
  kb(query)    - IA-8: one call per hunt on the join key; the query carries
                 `fault_class` and the deterministically derived `axis`; the
                 result is {symptoms, probing_techniques}. Empty result or a
                 raise degrades the grounding (fail-open, C2/C3).
  pod(spec)    - IA-3/IA-4: one call per dispatch; returns the D5+D6 envelope
                 {"verdict": "successful"|"unsuccessful",
                  "evidence": {"terminal_reason": <D5 terminal>, "iterations": n,
                               "clean": bool, "interpretations": [...],
                               "init_validation": [...]}}. The derivation
                 reads ONLY the terminal reason plus the single `clean`
                 flag on the envelope (operator-ratified 2026-08-04: no
                 per-variant machine outcomes); `interpretations` are pure
                 NL notes the feedback's evidence-backed insights ride on.
  author(text) - the spec-authoring turn; returns the D4 dict (typed base +
                 NL core), or None when the re-authoring evidence is
                 unaddressable (the agent then lands underspecified-spec
                 without re-rolling).
  judge(text)  - the D5 continuation judgment; consulted ONLY when the
                 derived verdict is insufficient-evidence; returns
                 {"meaningful_insight": bool, "next_step": "end"|"back_edge",
                  "rationale": str, "back_edge_requests": [...]}.

The deterministic verdict derivation (D67-02, Q3-amended; the pure function
is unit-tested in the red/green loop, the catalogue exercises it here through
the seams with the expected values taken from the spec):
  symptom-confirmed                -> successful
  space-exhausted                  -> unsuccessful
  technical-infeasibility          -> unsuccessful (structural blocker)
  specific-defence-prevention      -> unsuccessful
  no-symptom-evidence              -> insufficient-evidence when the envelope
                                      is not clean, else unsuccessful
  budget-timeout                   -> insufficient-evidence when the envelope
                                      is not clean (loop cut mid-flight),
                                      else unsuccessful
  technical-infeasibility carrying INIT validation evidence (the pod rejected
                                      the spec at INIT) -> underspecified-spec

The `clean` flag (the real pod #84 must emit the same): True = the loop
completed with clean observations (a symptom-absent is established), False =
observations were blocked, unreachable, or the loop was cut mid-flight (the
absence is not established). `init_validation` is present (list of strings)
only when the pod rejected the spec at INIT.
"""
import uuid

import pytest

from polymerhus.attack.hunting.hunt_orchestrator import (
    DispatchResult,
    HuntConfig,
    HuntPromptTemplate,
)
from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.attack.hunting.hunting_agent import build_hunting_agent
from polymerhus.recon.control.targeted import (
    AnalyserReconRequest,
    ReconScope,
    TargetedReconResult,
)

SERVICE_A = "Service:slug:a"
FAULT_X = "fault-x"

RUN_ID = "run-" + uuid.uuid4().hex[:8]

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

# The re-authored D4 (INIT rejection, example 3): the failing attributes
# declined - verification symptom narrowed to the observable surface, the
# unsupported method dropped from the payload vector space.
SPEC_REAUTHORED = {
    "target_identity": "Service:slug:a via GET /api/a",
    "verification_symptoms": ["HTTP status code in the 2xx/4xx band"],
    "testing_pattern": "csrf-probe baseline",
    "assumptions": ["public exposure", "no WAF on /api/a"],
    "payload_vector_space": {"parameter": "q", "encodings": ["urlencoded"]},
    "rationale": "fixture rationale from the spec's H1",
    "interpretation_guidance": "fixture guidance: map each status to evidence",
}

CARD_A = {
    "kind": "Service",
    "key": {"business_function_slug": "a"},
    "label": "a",
    "spine": {"exposure": "public"},
    "edge_degree": {"EXPOSED_VIA": 1},
    "nl_handles": {},
}


def _config(**overrides) -> HuntConfig:
    base = HuntConfig(
        hunt_id="hunt-1",
        unit_id=SERVICE_A,
        fault_class=FAULT_X,
        prompt_template=HuntPromptTemplate(
            rationale="fault-x applies to slug-a because ...",
            extension_points=["csrf-probe"],
            assumptions=["public exposure"],
            supposed_payload_vectors=["q=value"],
            l0_evidence=["GET /api/a answers 200"],
        ),
        surface_context={"cards": [CARD_A]},
        target_caveats=["perimeter WAF on /api/*"],
        prior_hunt_insights=[],
        tool_registry=[{"technique": "csrf-probe"}],
    )
    return base.model_copy(update=overrides)


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
    """The fixture spec-authoring turn: returns the canned D4 dicts in order;
    None signals the validation evidence is unaddressable (no re-roll)."""
    record = calls if calls is not None else []
    sequence = list(specs or [SPEC])

    def author(text):
        record.append(text)
        if not sequence:
            return None
        return sequence.pop(0)

    return author


def _judge(judgments: list[dict], *, calls: list | None = None):
    """The fixture D5 continuation judgment: consulted ONLY on an
    insufficient-evidence derivation; replays the canned judgments in order."""
    record = calls if calls is not None else []
    sequence = list(judgments)

    def judge(text):
        record.append(text)
        return sequence.pop(0)

    return judge


def _no_judge():
    def judge(text):
        pytest.fail("the D5 judgment must not be consulted on a terminal verdict")

    return judge


def _agent(store: HuntStore, *, kb=None, pod=None, author=None, judge=None, **kw):
    return build_hunting_agent(
        store=store, run_id=RUN_ID, kb=kb, pod=pod,
        author=author, judge=judge, **kw,
    )


def _need(fault_class: str = FAULT_X) -> AnalyserReconRequest:
    return AnalyserReconRequest(
        job="httpx_reprofile",
        scope=ReconScope(unit_id=SERVICE_A, note=f"hunt gap on {fault_class}"),
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


# --- C1: the authored spec validates against the typed base (D4) ---------------

def test_spec_validates_against_typed_base(tmp_path):
    store = HuntStore(tmp_path)
    queries: list = []
    pod_calls: list = []
    agent = _agent(
        store,
        kb=_kb(queries, result={"symptoms": ["csrf-absent"], "probing_techniques": ["csrf-probe"]}),
        pod=_pod(pod_calls, outcomes=[_outcome("symptom-confirmed", verdict="successful")]),
        author=_author(),
        judge=_no_judge(),
    )

    result = agent(_config())

    assert result.hypothesis_verdict == "successful"
    assert len(pod_calls) == 1
    # The KB join key was (fault-class, unit technological-axis) (D10, IA-8).
    assert len(queries) == 1
    assert queries[0].fault_class == FAULT_X
    assert isinstance(queries[0].axis, str) and queries[0].axis
    # The spec record (D4) carries the full typed base and both NL fields.
    specs = store.list_records(RUN_ID, "spec")
    assert len(specs) == 1
    spec = specs[0]
    for field in ("target_identity", "verification_symptoms", "testing_pattern",
                  "assumptions", "payload_vector_space"):
        assert spec[field], f"typed base field {field} is empty"
    assert spec["rationale"] and spec["interpretation_guidance"]
    # The evidence record (Q6) carries the derived verdict.
    evidence = store.list_records(RUN_ID, "evidence")
    assert len(evidence) == 1
    assert evidence[0]["derived_verdict"] == "successful"


# --- C2: empty KB degrades to HuntConfig-alone grounding (O1) -------------------

def test_empty_kb_degrades_to_config_grounding(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    agent = _agent(
        store,
        kb=_kb(result={"symptoms": [], "probing_techniques": []}),
        pod=_pod(pod_calls, outcomes=[_outcome("symptom-confirmed", verdict="successful")]),
        author=_author(),
        judge=_no_judge(),
    )

    result = agent(_config())

    assert result.hypothesis_verdict == "successful"
    assert len(pod_calls) == 1
    assert len(store.list_records(RUN_ID, "spec")) == 1


# --- C3: KB raise degrades the same way; nothing raises (O2) --------------------

def test_kb_unavailable_degrades(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    agent = _agent(
        store,
        kb=_kb(raise_on=True),
        pod=_pod(pod_calls, outcomes=[_outcome("symptom-confirmed", verdict="successful")]),
        author=_author(),
        judge=_no_judge(),
    )

    result = agent(_config())

    assert result.hypothesis_verdict == "successful"
    assert len(pod_calls) == 1
    assert len(store.list_records(RUN_ID, "spec")) == 1


# --- C4: malformed config authors from the present parts, gap flagged (O3) ------

def test_malformed_huntconfig_flags_gap(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    agent = _agent(
        store,
        kb=_kb(),
        pod=_pod(pod_calls, outcomes=[_outcome("symptom-confirmed", verdict="successful")]),
        author=_author(),
        judge=_no_judge(),
    )

    # Part 2 of the five-part parameter set (D3) missing: no surface context.
    result = agent(_config(surface_context={}))

    assert result.hypothesis_verdict == "successful"
    assert result.spec_ref  # still authored from the present parts
    assert result.feedback and "surface context" in result.feedback.lower()
    assert len(pod_calls) == 1


# --- C5: {successful, symptom-confirmed} -> hypothesis-successful (H1) ----------

def test_pod_success_maps_to_hypothesis_success(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    agent = _agent(
        store,
        kb=_kb(),
        pod=_pod(pod_calls, outcomes=[_outcome("symptom-confirmed", verdict="successful")]),
        author=_author(),
        judge=_no_judge(),
    )

    result = agent(_config())

    assert result.hypothesis_verdict == "successful"
    assert result.spec_ref and result.pod_result_ref
    assert result.back_edge_needs == []
    assert len(pod_calls) == 1


# --- C6: {unsuccessful, space-exhausted} clean trail -> unsuccessful (H2) -------

def test_clean_absent_maps_to_hypothesis_unsuccessful(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    agent = _agent(
        store,
        kb=_kb(),
        pod=_pod(pod_calls, outcomes=[_outcome(
            "space-exhausted",
            evidence={"clean": True, "interpretations": [
                {"variant": "v1", "note": "no symptom observed"},
            ]},
        )]),
        author=_author(),
        judge=_no_judge(),
    )

    result = agent(_config())

    assert result.hypothesis_verdict == "unsuccessful"
    assert len(pod_calls) == 1
    evidence = store.list_records(RUN_ID, "evidence")
    assert len(evidence) == 1
    assert evidence[0]["derived_verdict"] == "unsuccessful"


# --- C7: {unsuccessful, technical-infeasibility} -> unsuccessful (Q3) -----------
# Q3-amended: a structural blocker is a refutation, never insufficient-evidence.

def test_infeasibility_maps_to_unsuccessful(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    agent = _agent(
        store,
        kb=_kb(),
        pod=_pod(pod_calls, outcomes=[_outcome(
            "technical-infeasibility",
            evidence={"clean": False, "interpretations": [
                {"variant": "v1", "note": "tool cannot drive the JS flow"},
            ]},
        )]),
        author=_author(),
        judge=_no_judge(),
    )

    result = agent(_config())

    assert result.hypothesis_verdict == "unsuccessful"
    assert len(pod_calls) == 1


# --- C8: INIT rejection -> one re-authoring pass -> second rejection
#         -> underspecified-spec with the validation evidence (Q3/Q5) ------------

def test_pod_init_rejection_lands_underspecified_spec(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    agent = _agent(
        store,
        kb=_kb(),
        pod=_pod(pod_calls, outcomes=[
            _outcome(
                "technical-infeasibility",
                evidence={"clean": False, "interpretations": [], "init_validation": [
                    "verification_symptoms references an unobservable surface",
                    "payload_vector_space contains a method the target does not expose",
                ]},
            ),
            _outcome(
                "technical-infeasibility",
                evidence={"clean": False, "interpretations": [], "init_validation": [
                    "verification_symptoms still references an unobservable surface",
                ]},
            ),
        ]),
        author=_author([SPEC, SPEC_REAUTHORED]),
        judge=_no_judge(),
    )

    result = agent(_config())

    assert result.hypothesis_verdict == "underspecified-spec"
    assert len(pod_calls) == 2  # exactly two dispatches, no third attempt (Q5)
    specs = store.list_records(RUN_ID, "spec")
    assert len(specs) == 2
    # D67-03/D67-08 lineage: the re-authored spec records its parent.
    assert specs[1]["parent_spec_ref"] == specs[0]["_ref"]
    # The validation evidence rides the evidence record (Q6).
    evidence = store.list_records(RUN_ID, "evidence")
    assert len(evidence) == 2
    assert evidence[1]["derived_verdict"] == "underspecified-spec"
    assert evidence[1]["init_validation"]


# --- C9: identical spec already dispatched -> no second dispatch (O7) -----------

def test_duplicate_hypothesis_not_redispatched(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    judge_calls: list = []
    agent = _agent(
        store,
        kb=_kb(),
        pod=_pod(pod_calls, outcomes=[_outcome(
            "no-symptom-evidence",
            evidence={"clean": False, "interpretations": [
                {"variant": "v1", "note": "observations unreachable"},
            ]},
        )]),
        # The identical spec is supplied again: whether the re-entry re-authors
        # (and the canonical-hash log short-circuits) or re-enters VERIFY-CLAIMS,
        # the observable is the same - one pod dispatch, one spec record.
        author=_author([SPEC, SPEC]),
        judge=_judge([
            {"meaningful_insight": True, "next_step": "back_edge",
             "rationale": "recon the reachable surface", "back_edge_requests": [_need()]},
            {"meaningful_insight": False, "next_step": "end",
             "rationale": "still no reachable surface"},
        ], calls=judge_calls),
    )
    config = _config()

    first = agent(config)
    assert first.back_edge_needs  # insufficient-evidence surfaces the inline need

    # The orchestrator routes the recon result back (IA-6); the agent re-enters
    # with the SAME spec - the experiment log (Q5) short-circuits the pod.
    second = agent(config, routed=(_route(first.back_edge_needs[0]),))

    assert len(pod_calls) == 1  # no second dispatch for the identical spec
    assert len(store.list_records(RUN_ID, "spec")) == 1
    assert second.spec_ref == first.spec_ref
    assert second.pod_result_ref == first.pod_result_ref
    assert len(judge_calls) == 2


# --- C10: no meaningful insight ends the evaluation (D67-14, D67-12) ------------

def test_no_meaningful_insight_ends_evaluation(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    agent = _agent(
        store,
        kb=_kb(),
        pod=_pod(pod_calls, outcomes=[_outcome(
            "no-symptom-evidence",
            evidence={"clean": False, "interpretations": [
                {"variant": "v1", "note": "observations unreachable"},
            ]},
        )]),
        author=_author(),
        judge=_judge([
            {"meaningful_insight": True, "next_step": "back_edge",
             "rationale": "recon the reachable surface", "back_edge_requests": [_need()]},
            {"meaningful_insight": False, "next_step": "end",
             "rationale": "no insight in the routed recon"},
        ]),
    )
    config = _config()

    first = agent(config)
    assert first.back_edge_needs

    second = agent(config, routed=(_route(first.back_edge_needs[0]),))

    # The guard ended the evaluation: no unbounded loop, no further needs.
    assert second.back_edge_needs == []
    # D67-12 failure state: the hunt degrades to unsuccessful with the trail.
    assert second.hypothesis_verdict == "unsuccessful"
    assert second.feedback  # never empty; carries the evidence-backed insights
    assert second.feedback and "unreachable" in second.feedback


# --- C11: a raising pod degrades to unsuccessful with the error (O5) ------------

def test_raising_pod_degrades(tmp_path):
    store = HuntStore(tmp_path)
    agent = _agent(
        store,
        kb=_kb(),
        pod=_pod(outcomes=[], raise_on=0),
        author=_author(),
        judge=_no_judge(),
    )

    result = agent(_config())

    assert result.hypothesis_verdict == "unsuccessful"
    assert result.feedback and "pod turn exhausted" in result.feedback
    evidence = store.list_records(RUN_ID, "evidence")
    assert len(evidence) == 1
    assert "pod turn exhausted" in evidence[0].get("error", "")


# --- C12: worst case - technically unfeasible, feedback never empty (D67-12) ----

def test_worst_case_graceful_degradation_feeds_back(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    agent = _agent(
        store,
        kb=_kb(),
        pod=_pod(pod_calls, outcomes=[_outcome(
            "technical-infeasibility",
            evidence={"clean": False, "interpretations": [
                {"variant": "v1", "note": "all paths WAF-blocked"},
            ]},
        )]),
        author=_author(),
        judge=_no_judge(),
    )

    result = agent(_config())

    assert result.hypothesis_verdict == "unsuccessful"
    assert result.feedback and "WAF-blocked" in result.feedback  # blocking assertion
    assert len(pod_calls) == 1


# --- C13: {unsuccessful, specific-defence-prevention} -> unsuccessful (Q3) ------

def test_defence_prevention_maps_to_unsuccessful(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    agent = _agent(
        store,
        kb=_kb(),
        pod=_pod(pod_calls, outcomes=[_outcome(
            "specific-defence-prevention",
            evidence={"clean": False, "interpretations": [
                {"variant": "v1", "note": "WAF soft-blocked the probe"},
            ]},
        )]),
        author=_author(),
        judge=_no_judge(),
    )

    result = agent(_config())

    assert result.hypothesis_verdict == "unsuccessful"
    assert len(pod_calls) == 1


# --- C14: no-symptom-evidence with blocked observations ->
#         insufficient-evidence (Q3, trail-driven) --------------------------------

def test_no_symptom_evidence_blocked_maps_to_insufficient_evidence(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    agent = _agent(
        store,
        kb=_kb(),
        pod=_pod(pod_calls, outcomes=[_outcome(
            "no-symptom-evidence",
            evidence={"clean": False, "interpretations": [
                {"variant": "v1", "note": "observations unreachable"},
            ]},
        )]),
        author=_author(),
        judge=_judge([
            {"meaningful_insight": True, "next_step": "back_edge",
             "rationale": "recon the reachable surface", "back_edge_requests": [_need()]},
        ]),
    )

    result = agent(_config())

    # The blocked trail derives insufficient-evidence, surfacing the inline need.
    assert result.back_edge_needs
    assert len(result.back_edge_needs) == 1
    assert result.back_edge_needs[0].origin == "hunting"
    assert result.back_edge_needs[0].scope.unit_id == SERVICE_A
    evidence = store.list_records(RUN_ID, "evidence")
    assert len(evidence) == 1
    assert evidence[0]["derived_verdict"] == "insufficient-evidence"
    assert len(pod_calls) == 1


# --- C15: no-symptom-evidence with clean observations -> unsuccessful (Q3) ------

def test_no_symptom_evidence_clean_maps_to_unsuccessful(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    agent = _agent(
        store,
        kb=_kb(),
        pod=_pod(pod_calls, outcomes=[_outcome(
            "no-symptom-evidence",
            evidence={"clean": True, "interpretations": [
                {"variant": "v1", "note": "probe exercised the surface"},
            ]},
        )]),
        author=_author(),
        judge=_no_judge(),
    )

    result = agent(_config())

    assert result.hypothesis_verdict == "unsuccessful"
    assert result.back_edge_needs == []
    assert len(pod_calls) == 1


# --- C16: budget-timeout with a partial trail -> insufficient-evidence (Q3) -----

def test_budget_timeout_partial_maps_to_insufficient_evidence(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    agent = _agent(
        store,
        kb=_kb(),
        pod=_pod(pod_calls, outcomes=[_outcome(
            "budget-timeout",
            evidence={"clean": False, "interpretations": [
                {"variant": "v1", "note": "mid-flight"},
            ]},
        )]),
        author=_author(),
        judge=_judge([
            {"meaningful_insight": True, "next_step": "back_edge",
             "rationale": "recon the remaining surface", "back_edge_requests": [_need()]},
        ]),
    )

    result = agent(_config())

    assert result.back_edge_needs
    evidence = store.list_records(RUN_ID, "evidence")
    assert len(evidence) == 1
    assert evidence[0]["derived_verdict"] == "insufficient-evidence"
    assert len(pod_calls) == 1


# --- C17: budget-timeout with a clean trail -> unsuccessful (Q3) ----------------

def test_budget_timeout_clean_maps_to_unsuccessful(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    agent = _agent(
        store,
        kb=_kb(),
        pod=_pod(pod_calls, outcomes=[_outcome(
            "budget-timeout",
            evidence={"clean": True, "interpretations": [
                {"variant": "v1", "note": "no symptom observed"},
            ]},
        )]),
        author=_author(),
        judge=_no_judge(),
    )

    result = agent(_config())

    assert result.hypothesis_verdict == "unsuccessful"
    assert result.back_edge_needs == []
    assert len(pod_calls) == 1
