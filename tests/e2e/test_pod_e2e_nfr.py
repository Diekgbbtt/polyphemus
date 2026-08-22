""""NFR evaluation scorer for the pod e2e tier (#84) - assertion catalogue
`docs/design/hunting-84-assertions.md` section 8 (N1-N8).

The scorer is PURE: it reads a run's artifacts (spec.json, envelope.json, the
D6 experiment log, the pod-memory notes, and the Langfuse trace summary the
coordinator attaches) and returns the N1-N8 scorecard. The rubric itself is
unit-proven here on the HERMETIC E1 run artifacts (the deterministic offline
layer) so the scoring functions are correct before any live run happens; the
live runs (E5-E8) feed the same scorer when the stack is up.

Each criterion is scored 0-3 (0 absent/broken, 1 present but shallow, 2
correct, 3 exemplary); a run is GREEN on a criterion at >= 2; an e2e PASS
requires N1-N4 each >= 2 AND N5-N8 each >= 1 (terminality is the floor).
"""
from __future__ import annotations

import json

from polymerhus.attack.hunting.pod.types import TERMINAL_REASONS

# The six-way terminal vocabulary (D5, Q3-amended) - the scorer reads it from
# the envelope's terminal_reason.
SIX_WAY = set(TERMINAL_REASONS)

# The runner prompt's P0-P3 phases (spec 1.3, D84-16) for N2.
_PHASES = ("feasibility", "concret", "execute", "exhaust")
_PLAN_MARKERS = ("p0", "p1", "p2", "p3")


def _notes_from_artifacts(artifacts: dict) -> list[dict]:
    """The pod-memory notes (D84-32 fields) recorded on the run, or [] when
    the artifacts do not carry them (hermetic runs persist envelope only)."""
    return artifacts.get("notes") or []


def score_n1_prompt_materialization(spec: dict, trace: dict | None) -> int:
    """The runner's system prompt carries every spec attribute + the plan. The
    trace is the Langfuse system-prompt text when the coordinator attaches it;
    without it, the hermetic score is 2 (all spec attributes are present in the
    driver's persisted spec; the plan materialization is the live-run concern)."""
    if not spec:
        return 0
    required = ("target_identity", "verification_symptoms", "testing_pattern",
                "assumptions", "payload_vector_space")
    missing = [k for k in required if not spec.get(k)]
    nl_missing = not spec.get("rationale") or not spec.get("interpretation_guidance")
    if missing:
        return 1 if len(missing) < len(required) else 0
    if nl_missing:
        return 1
    if not trace:
        return 2
    text = str(trace)
    plan_ok = all(p in text.lower() for p in _PLAN_MARKERS)
    spec_ok = all(k in text for k in required)
    return 3 if plan_ok and spec_ok else (2 if spec_ok else 1)


def score_n2_react_trajectory(trace: dict | None,
                              evidence: dict | None) -> int:
    """P0-P3 traversal: the trace's tool calls (kb_retrieve/exec/note) and the
    evidence's raw observations. Hermetic floor: >= 1 observation with the
    tools present => 2."""
    if not evidence:
        return 0
    raw = evidence.get("raw_observations") or []
    if not raw:
        return 0
    trace_steps = []
    if trace:
        trace_steps = trace.get("tool_calls") or []
    tools = {"exec", "kb_retrieve", "note"} & (
        set(trace_steps) if trace_steps else set())
    if trace_steps:
        return 3 if tools == {"exec", "kb_retrieve", "note"} else (
            2 if tools else 1)
    return 2 if len(raw) >= 1 else 1


def score_n3_note_detail(notes: list[dict]) -> int:
    """P3 note density: a real note with specific body length + reference to
    probes/observations. Floor: 0 if there are no notes at all."""
    summary = [n for n in notes if n.get("kind") == "experiment_summary"]
    if not summary:
        return 0
    body = str(summary[0].get("body") or "")
    if len(body) < 40:
        return 1
    specific = any(m in body.lower() for m in ("404", "200", "probe", "payload",
                                               "status", "kb"))
    return 3 if specific and len(body) >= 120 else (2 if specific else 1)


def score_n4_init_validation(env: dict) -> int:
    """INIT criticality: a malformed/infeasible spec is rejected with
    init_validation evidence; a valid spec is accepted (the absence of a
    rejection is itself valid for a well-formed fixture)."""
    evidence = env.get("evidence") or {}
    validation = evidence.get("init_validation")
    if validation:
        return 3 if len(validation) >= 1 else 2
    # No rejection: the spec was accepted - valid for the E5-E8 rich fixtures.
    return 2 if env.get("verdict") in ("successful", "unsuccessful") else 1


def score_n5_space_exploration(evidence: dict) -> int:
    """Variant mining + probe-space exhaustion: how many distinct variants and
    raw observations really accumulated."""
    variants = evidence.get("variant_specs") or []
    raw = evidence.get("raw_observations") or []
    if not raw and not variants:
        return 0
    if len(variants) >= 2 and len(raw) >= 3:
        return 3
    if len(variants) >= 1 and len(raw) >= 2:
        return 2
    return 1


def score_n6_termination_persistence(env: dict) -> int:
    """Six-way termination + D6 persistence: the correct terminal_reason/clean
    and the persisted experiment log."""
    evidence = env.get("evidence") or {}
    if env.get("verdict") not in ("successful", "unsuccessful"):
        return 0
    if evidence.get("terminal_reason") not in SIX_WAY:
        return 0
    if (not evidence.get("variant_specs")
            or not evidence.get("raw_observations")
            or not evidence.get("interpretations")):
        return 1
    return 3 if evidence.get("terminal_reason") == "symptom-confirmed" else 2


def score_n7_triager_reflection(variants: list[dict]) -> int:
    """Did the triager mint a variant that CHANGED the testing procedure
    paradigm - a different technique/vector family, not a cosmetic tweak?"""
    if not variants:
        return 0
    if len(variants) < 2:
        return 1
    # A paradigm-sharp change: the declined attribute is the testing_pattern or
    # the payload_vector_space changed its family (not just a path tweak).
    for v in variants[1:]:
        declined = v.get("declined_attribute")
        if declined == "testing_pattern":
            return 3
        if declined == "payload_vector_space":
            return 2
    return 1


def score_n8_loop_seamless(env: dict, traces: dict | None) -> int:
    """The spec-conformant loop: binary terminal within caps, no raise."""
    if env.get("verdict") not in ("successful", "unsuccessful"):
        return 0
    evidence = env.get("evidence") or {}
    iters = int(evidence.get("iterations") or 0)
    if evidence.get("error"):
        return 1
    return 3 if 0 < iters <= 8 else (2 if iters > 0 else 1)


def score_run(artifacts: dict) -> dict:
    """Full N1-N8 scorecard for one run's artifacts. `trace` is the attached
    Langfuse trace summary (the coordinator supplies it for the live tier);
    `notes` the pod-memory note records."""
    spec = artifacts.get("spec") or {}
    env = artifacts.get("envelope") or {}
    evidence = env.get("evidence") or {}
    notes = _notes_from_artifacts(artifacts)
    trace = artifacts.get("trace")
    variants = evidence.get("variant_specs") or []
    scores = {
        "N1_prompt_materialization": score_n1_prompt_materialization(spec, trace),
        "N2_react_trajectory": score_n2_react_trajectory(trace, evidence),
        "N3_note_detail": score_n3_note_detail(notes),
        "N4_init_validation": score_n4_init_validation(env),
        "N5_space_exploration": score_n5_space_exploration(evidence),
        "N6_termination_persistence": score_n6_termination_persistence(env),
        "N7_triager_reflection": score_n7_triager_reflection(variants),
        "N8_loop_seamless": score_n8_loop_seamless(env, trace),
    }
    # The gate: N1-N4 each >= 2 AND N5-N8 each >= 1 (terminality is the floor).
    first_four = [scores["N1_prompt_materialization"], scores["N2_react_trajectory"],
                  scores["N3_note_detail"], scores["N4_init_validation"]]
    last_four = [scores["N5_space_exploration"], scores["N6_termination_persistence"],
                 scores["N7_triager_reflection"], scores["N8_loop_seamless"]]
    scores["pass"] = min(first_four) >= 2 and min(last_four) >= 1
    return scores


# --- unit-proofs: the rubric on the HERMETIC E1 artifacts ----------------------

def _hermetic_e1_spec():
    return {"target_identity": "service:web:soupmarket",
            "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
            "testing_pattern": "blind-boolean",
            "assumptions": ["network egress allowed"],
            "payload_vector_space": {"method": "GET", "path": "/"},
            "rationale": "reachability probe from H1",
            "interpretation_guidance": "a 200 with a non-empty body confirms the symptom"}


def _hermetic_h2_env():
    """The space-exhausted hermetic shape (E1/H2): the run that DOES write the
    P3 note - the pass-gate proof must exercise the full note path, not the
    symptom-confirmed early-out."""
    return {"verdict": "unsuccessful", "evidence": {
        "terminal_reason": "space-exhausted", "clean": True,
        "iterations": 2, "init_validation": [],
        "variant_specs": [{"ref": "v0"}],
        "raw_observations": [{"status": 404, "body": "not found"}],
        "interpretations": [{"classification": "symptom-absent",
                             "note": "third-party miner: no symptom established"}]}}


_HERMETIC_H2_NOTE = [{"kind": "experiment_summary", "variant_ref": "v0",
                      "body": ("the default probe (GET /) returned HTTP 404 "
                               "with an empty body; the search-parameter "
                               "families were exhausted; payload banana reflects "
                               "as plain text; no kb primitive differs from the "
                               "initial set; the consolidated summary is written "
                               "as the final tool call of the stretch")}]


def test_n1_prompt_materialization_hermetic_floor():
    assert score_n1_prompt_materialization(_hermetic_e1_spec(), None) == 2


def test_n1_drops_when_spec_missing_attribute():
    spec = _hermetic_e1_spec()
    spec.pop("assumptions")
    assert score_n1_prompt_materialization(spec, None) == 1


def test_n1_zero_when_base_absent():
    spec = {"rationale": "x", "interpretation_guidance": "y"}
    assert score_n1_prompt_materialization(spec, None) == 0


def test_n2_trajectory_hermetic_floor():
    assert score_n2_react_trajectory(None, _hermetic_h2_env()["evidence"]) == 2


def test_n2_zero_with_no_observation():
    assert score_n2_react_trajectory(None, {}) == 0


def test_n3_note_absent_is_zero():
    assert score_n3_note_detail([]) == 0


def test_n3_dense_note_scores_three():
    assert score_n3_note_detail(_HERMETIC_H2_NOTE) == 3


def test_n3_shallow_note_scores_one():
    assert score_n3_note_detail([{"kind": "experiment_summary", "body": "done"}]) == 1


def test_n4_init_validation_accepts_valid_spec():
    assert score_n4_init_validation(_hermetic_h2_env()) == 2


def test_n4_rejection_is_critical():
    env = {"verdict": "unsuccessful",
           "evidence": {"init_validation": ["target_identity empty"], "terminal_reason": "technical-infeasibility"}}
    assert score_n4_init_validation(env) == 3


def test_n6_termination_persistence_full():
    assert score_n6_termination_persistence(_hermetic_h2_env()) == 2


def test_n6_wrong_terminal_is_zero():
    env = {"verdict": "unsuccessful", "evidence": {"terminal_reason": "not-a-reason"}}
    assert score_n6_termination_persistence(env) == 0


def test_n8_loop_seamless_in_cap():
    assert score_n8_loop_seamless(_hermetic_h2_env(), None) == 3


def test_full_scorecard_pass_on_hermetic_e1():
    score = score_run({"spec": _hermetic_e1_spec(),
                       "envelope": _hermetic_h2_env(),
                       "notes": _HERMETIC_H2_NOTE})
    assert score["pass"] is True
    assert set(score) >= {"N1_prompt_materialization", "N8_loop_seamless", "pass"}