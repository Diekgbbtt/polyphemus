"""Unit tier: the pod's looped state machine driven through `run_pod` with the
tools and the two agents mocked. Exercises the control-flow mechanics - the INIT
gate, the runner's agentic inner loop (intra-chain data flow + the harness inner
cap), the symbolic fast-path, variant provenance, dedup-feeds-one-execution, the
pod-budget cap, and the clean-flag semantics."""
from polymerhus.attack.hunting.pod import run_pod
from polymerhus.attack.hunting.pod.agents import symbolic_runner_step_fn
from polymerhus.attack.hunting.pod.types import RunnerStep
from polymerhus.recon.domain.types import ExecResult

VALID_SPEC = {
    "target_identity": "service:web:soupmarket",
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "testing_pattern": "blind-boolean",
    "assumptions": ["network egress allowed"],
    "payload_vector_space": {"method": "GET", "path": "/"},
    "rationale": "reachability",
    "interpretation_guidance": "a 200 with a body confirms reachability",
}


def _exec(stdout, returncode=0, calls=None):
    def fake(command, timeout_s):
        if calls is not None:
            calls.append(command)
        return ExecResult(stdout=stdout, stderr="", returncode=returncode, duration_ms=1)
    return fake


_OK = "<html>market</html>\n__POD_HTTP_STATUS__:200\n__POD_HTTP_TIME__:0.05"
_ABSENT = "not found\n__POD_HTTP_STATUS__:404\n__POD_HTTP_TIME__:0.02"


def _scripted(steps):
    it = iter(steps)

    def runner(spec, messages, tool_calls):
        try:
            return next(it)
        except StopIteration:
            return RunnerStep(action="conclude", observation_note="script exhausted")
    return runner


def _no_trace(_run_id):
    return []


def test_init_rejection_makes_no_tool_call():
    calls = []
    env = run_pod({"target_identity": "", "verification_symptoms": [],
                   "testing_pattern": "", "payload_vector_space": {}},
                  exec_fn=_exec(_OK, calls=calls),
                  runner_step_fn=symbolic_runner_step_fn, triager_fn=None, trace_fn=_no_trace)
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert env["evidence"]["init_validation"]
    assert calls == []                               # C1: no tool call


def test_symbolic_symptom_confirmed_needs_no_triager():
    env = run_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=symbolic_runner_step_fn,
                  triager_fn=None, trace_fn=_no_trace)
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"
    assert env["evidence"]["iterations"] == 1
    assert env["evidence"]["clean"] is True
    assert len(env["evidence"]["raw_observations"]) == 1


def test_runner_drives_a_multi_step_chain_with_intra_chain_flow():
    # The runner authors a dependency call then a core call, seeing the first
    # result before the second - the agentic loop, not a static chain.
    calls = []
    steps = [
        RunnerStep(action="tool_call", tool="exec", command="curl -k -sS -X GET https://t/login"),
        RunnerStep(action="tool_call", tool="exec", command="curl -k -sS -X GET https://t/api"),
        RunnerStep(action="conclude", observation_note="chain complete"),
    ]

    def triager(spec, obs, messages, log):
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "no-symptom-evidence", "clean": True}

    env = run_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                  exec_fn=_exec(_ABSENT, calls=calls), runner_step_fn=_scripted(steps),
                  triager_fn=triager, trace_fn=_no_trace)
    assert len(calls) == 2                           # both chain steps executed
    assert len(env["evidence"]["raw_observations"]) == 2


def test_inner_tool_cap_forces_conclusion(monkeypatch):
    # A runner that never concludes is cut by the harness inner cap (G1).
    monkeypatch.setattr("polymerhus.attack.hunting.pod.graph.HUNT_POD_MAX_TOOL_CALLS", 2)
    calls = []

    def runner(spec, messages, tool_calls):
        return RunnerStep(action="tool_call", tool="exec",
                          command=f"curl -k -sS https://t/{tool_calls}")

    def triager(spec, obs, messages, log):
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    env = run_pod(VALID_SPEC, exec_fn=_exec(_ABSENT, calls=calls),
                  runner_step_fn=runner, triager_fn=triager, trace_fn=_no_trace)
    assert len(calls) == 2                           # bounded by the inner cap
    assert env["verdict"] == "unsuccessful"


def test_runner_sees_tool_results_in_its_curated_session():
    # The intra-chain data flow: on its second turn the runner's session carries
    # the first tool's result, so it can reflect and branch (semi-stateful).
    seen = []

    def runner(spec, messages, tool_calls):
        seen.append(list(messages))
        if tool_calls == 0:
            return RunnerStep(action="tool_call", tool="exec", command="curl -k -sS https://t/")
        return RunnerStep(action="conclude", observation_note="saw the result")

    def triager(spec, obs, messages, log):
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    run_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
            exec_fn=_exec(_OK), runner_step_fn=runner, triager_fn=triager, trace_fn=_no_trace)
    assert len(seen) >= 2
    assert any("TOOL RESULT" in m["content"] for m in seen[1])   # 2nd turn sees the 1st result


def test_variant_loop_records_provenance():
    decisions = iter([
        {"classification": "symptom-absent", "action": "variant",
         "declined_attribute": "payload_vector_space",
         "variant_spec": {**VALID_SPEC, "payload_vector_space": {"method": "GET", "path": "/api"}},
         "feedback": "try /api"},
        {"classification": "symptom-absent", "action": "terminate",
         "verdict": "unsuccessful", "terminal_reason": "space-exhausted", "clean": True},
    ])

    def triager(spec, obs, messages, log):
        return next(decisions)

    env = run_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                  exec_fn=_exec(_ABSENT), runner_step_fn=symbolic_runner_step_fn,
                  triager_fn=triager, trace_fn=_no_trace)
    assert env["evidence"]["iterations"] == 2
    variants = env["evidence"]["variant_specs"]
    assert [v["ref"] for v in variants] == ["v0", "v1"]
    assert variants[1]["parent_ref"] == "v0"
    assert variants[1]["declined_attribute"] == "payload_vector_space"


def test_pod_budget_cap_terminates_only_the_pod(monkeypatch):
    monkeypatch.setattr("polymerhus.attack.hunting.pod.graph.HUNT_POD_MAX_ITERS", 3)

    def triager(spec, obs, messages, log):
        return {"classification": "symptom-absent", "action": "variant",
                "declined_attribute": "testing_pattern", "variant_spec": dict(spec),
                "feedback": "keep trying"}

    env = run_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                  exec_fn=_exec(_ABSENT), runner_step_fn=symbolic_runner_step_fn,
                  triager_fn=triager, trace_fn=_no_trace)
    assert env["evidence"]["terminal_reason"] == "budget-timeout"
    assert env["evidence"]["clean"] is False
    assert env["evidence"]["iterations"] == 3


def test_dedup_one_execution_per_identical_probe():
    calls = []
    steps = [
        RunnerStep(action="tool_call", tool="exec", command="curl -k -sS https://t/"),
        RunnerStep(action="tool_call", tool="exec", command="curl -k -sS https://t/"),  # identical
        RunnerStep(action="conclude", observation_note="done"),
    ]

    def triager(spec, obs, messages, log):
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    env = run_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                  exec_fn=_exec(_ABSENT, calls=calls), runner_step_fn=_scripted(steps),
                  triager_fn=triager, trace_fn=_no_trace)
    assert len(calls) == 1                           # O7/C10: executed once


def test_runner_infeasible_is_an_init_gate_with_evidence():
    steps = [RunnerStep(action="conclude", infeasible=True,
                        unverified=["no WAF on /api/a could not be confirmed"])]
    env = run_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=_scripted(steps),
                  triager_fn=None, trace_fn=_no_trace)
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert any("WAF" in v for v in env["evidence"]["init_validation"])


def test_clean_false_when_triager_reports_defence():
    def triager(spec, obs, messages, log):
        return {"classification": "infeasibility-signal", "action": "terminate",
                "verdict": "unsuccessful", "terminal_reason": "specific-defence-prevention",
                "clean": False, "note": "WAF soft-blocked every probe"}

    env = run_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                  exec_fn=_exec(_ABSENT), runner_step_fn=symbolic_runner_step_fn,
                  triager_fn=triager, trace_fn=_no_trace)
    assert env["evidence"]["terminal_reason"] == "specific-defence-prevention"
    assert env["evidence"]["clean"] is False
