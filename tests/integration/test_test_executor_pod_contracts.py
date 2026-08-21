"""Integration tier: the test-executor pod assertion catalogue C1-C12
(hunting-67-test-executor-pod-spec.md section 6.1).

The contract predicates exercise the pod's EXTERNAL behaviour through its one
seam - `run_pod(spec) -> {verdict, evidence}` (IA-3 in, IA-4 out) - with every
side-effecting collaborator injected: the terminal (`exec_fn`), the Runner
(`runner_step_fn`), the Critic (`triager_fn`), the KB, and the Langfuse trace
stub. Most predicates drive the symbolic Runner (`symbolic_runner_step_fn`) so no
live LLM is needed; the real chain is walked in the e2e tier (E1 real; E2-E4
blocked on #83). No live target, no downstream agent.

Q3 reconciliation (operator-ratified 2026-08-04, landed 2026-08-06): the pod
emits the six-value `terminal_reason` vocabulary the parent's derivation reads.
C5's per-agent-spec wording "infeasibility-asserted" is the amended
`technical-infeasibility`; the expected values below are taken from the spec.
"""
import pytest

from polymerhus.attack.hunting.pod import run_pod
from polymerhus.attack.hunting.pod.agents import symbolic_runner_step_fn
from polymerhus.attack.hunting.pod.config import EXEC_TIMEOUT_S, MAX_POD_ITERS
from polymerhus.attack.hunting.pod.types import RunnerStep, TERMINAL_REASONS
from polymerhus.recon.domain.types import ExecResult

VALID_SPEC = {
    "target_identity": "service:web:soupmarket",
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "testing_pattern": "blind-boolean",
    "assumptions": ["network egress allowed"],
    "payload_vector_space": {"method": "GET", "path": "/"},
    "rationale": "reachability probe from H1",
    "interpretation_guidance": "a 200 with a non-empty body confirms the symptom",
}

# A spec whose symptom the symbolic recogniser cannot decide, so the Critic runs.
SEMANTIC_SPEC = {**VALID_SPEC, "verification_symptoms": ["reflects the injected marker"]}


def _no_trace(_run_id):
    return []


def _exec(stdout="", returncode=0, calls=None, assert_timeout=None):
    def fake(command, timeout_s):
        if assert_timeout is not None:
            assert timeout_s == assert_timeout       # the pod's fixed cap is passed down
        if calls is not None:
            calls.append(command)
        return ExecResult(stdout=stdout, stderr="", returncode=returncode, duration_ms=1)
    return fake


_OK = "<html>market</html>\n__POD_HTTP_STATUS__:200\n__POD_HTTP_TIME__:0.05"
_ABSENT = "not found\n__POD_HTTP_STATUS__:404\n__POD_HTTP_TIME__:0.02"


def _terminate(reason, *, clean=True, verdict="unsuccessful"):
    def triager(spec, obs, messages, log):
        return {"action": "terminate", "verdict": verdict,
                "terminal_reason": reason, "clean": clean}
    return triager


# --- C1 -----------------------------------------------------------------------

def test_init_rejects_invalid_spec():
    calls = []
    env = run_pod({"target_identity": "", "verification_symptoms": [],
                   "testing_pattern": "", "payload_vector_space": {}},
                  exec_fn=_exec(_OK, calls=calls),
                  runner_step_fn=symbolic_runner_step_fn, triager_fn=None, trace_fn=_no_trace)
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["init_validation"]
    assert env["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert calls == []                               # executes no tool call


# --- C2 -----------------------------------------------------------------------

@pytest.mark.parametrize("scenario", ["confirmed", "absent", "infeasible", "invalid"])
def test_binary_terminal_invariant(scenario):
    if scenario == "confirmed":
        env = run_pod(VALID_SPEC, exec_fn=_exec(_OK),
                      runner_step_fn=symbolic_runner_step_fn, triager_fn=None, trace_fn=_no_trace)
    elif scenario == "absent":
        env = run_pod(SEMANTIC_SPEC, exec_fn=_exec(_ABSENT),
                      runner_step_fn=symbolic_runner_step_fn,
                      triager_fn=_terminate("space-exhausted"), trace_fn=_no_trace)
    elif scenario == "infeasible":
        env = run_pod(VALID_SPEC, exec_fn=_exec("", returncode=7),
                      runner_step_fn=symbolic_runner_step_fn, triager_fn=None, trace_fn=_no_trace)
    else:
        env = run_pod({"verification_symptoms": []}, exec_fn=_exec(_OK),
                      runner_step_fn=symbolic_runner_step_fn, trace_fn=_no_trace)
    assert env["verdict"] in ("successful", "unsuccessful")
    assert env["evidence"]["terminal_reason"] in TERMINAL_REASONS


# --- C3 -----------------------------------------------------------------------

def test_symptom_confirmed_lands_successful():
    env = run_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=symbolic_runner_step_fn,
                  triager_fn=None, trace_fn=_no_trace)
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"
    assert env["evidence"]["iterations"] >= 1
    assert env["evidence"]["raw_observations"] and env["evidence"]["interpretations"]


# --- C4 -----------------------------------------------------------------------

def test_space_exhausted_lands_unsuccessful():
    env = run_pod(SEMANTIC_SPEC, exec_fn=_exec(_ABSENT),
                  runner_step_fn=symbolic_runner_step_fn,
                  triager_fn=_terminate("space-exhausted"), trace_fn=_no_trace)
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "space-exhausted"


# --- C5 -----------------------------------------------------------------------

def test_infeasibility_asserted_with_evidence():
    env = run_pod(VALID_SPEC, exec_fn=_exec("", returncode=7),
                  runner_step_fn=symbolic_runner_step_fn, triager_fn=None, trace_fn=_no_trace)
    assert env["verdict"] == "unsuccessful"
    # Q3-amended: the per-agent spec's `infeasibility-asserted` is this value.
    assert env["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert env["evidence"]["raw_observations"]


# --- C6 -----------------------------------------------------------------------

def test_budget_timeout_lands_unsuccessful(monkeypatch):
    monkeypatch.setattr("polymerhus.attack.hunting.pod.graph.HUNT_POD_MAX_ITERS", 3)

    def triager(spec, obs, messages, log):
        return {"classification": "symptom-absent", "action": "variant",
                "declined_attribute": "testing_pattern", "variant_spec": dict(spec),
                "feedback": "keep searching"}

    env = run_pod(SEMANTIC_SPEC, exec_fn=_exec(_ABSENT),
                  runner_step_fn=symbolic_runner_step_fn, triager_fn=triager, trace_fn=_no_trace)
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "budget-timeout"
    assert env["evidence"]["raw_observations"]


# --- C7 -----------------------------------------------------------------------

def test_non_zero_exit_retries_to_converge():
    calls = []

    def fake(command, timeout_s):
        calls.append(command)
        if len(calls) < MAX_POD_ITERS:
            return ExecResult(stdout="", stderr="boom", returncode=1, duration_ms=1)
        return ExecResult(stdout=_OK, stderr="", returncode=0, duration_ms=1)

    env = run_pod(VALID_SPEC, exec_fn=fake, runner_step_fn=symbolic_runner_step_fn,
                  triager_fn=None, trace_fn=_no_trace)
    assert len(calls) == MAX_POD_ITERS               # converged at the cap
    assert env["verdict"] in ("successful", "unsuccessful")
    assert env["evidence"]["terminal_reason"] in TERMINAL_REASONS


# --- C8 -----------------------------------------------------------------------

def test_exec_timeout_enforced():
    calls = []
    env = run_pod(VALID_SPEC,
                  exec_fn=_exec("", returncode=124, calls=calls, assert_timeout=EXEC_TIMEOUT_S),
                  runner_step_fn=symbolic_runner_step_fn, triager_fn=None, trace_fn=_no_trace)
    assert len(calls) == MAX_POD_ITERS               # bounded by the cap
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] in TERMINAL_REASONS


# --- C9 -----------------------------------------------------------------------

def test_variant_derivation_with_provenance():
    decisions = iter([
        {"classification": "symptom-absent", "action": "variant",
         "declined_attribute": "payload_vector_space",
         "variant_spec": {**SEMANTIC_SPEC, "payload_vector_space": {"method": "GET", "path": "/api"}},
         "feedback": "decline the path into /api"},
        {"classification": "symptom-absent", "action": "terminate",
         "verdict": "unsuccessful", "terminal_reason": "no-symptom-evidence", "clean": False},
    ])

    def triager(spec, obs, messages, log):
        return next(decisions)

    env = run_pod(SEMANTIC_SPEC, exec_fn=_exec(_ABSENT),
                  runner_step_fn=symbolic_runner_step_fn, triager_fn=triager, trace_fn=_no_trace)
    variants = env["evidence"]["variant_specs"]
    assert len(variants) == 2
    assert variants[1]["parent_ref"] == "v0"
    assert variants[1]["declined_attribute"] == "payload_vector_space"
    assert env["evidence"]["raw_observations"] and env["evidence"]["interpretations"]


# --- C10 ----------------------------------------------------------------------

def test_duplicate_probe_recorded_once():
    calls = []
    steps = iter([
        RunnerStep(action="tool_call", tool="exec", command="curl -k -sS https://t/"),
        RunnerStep(action="tool_call", tool="exec", command="curl -k -sS https://t/"),  # identical
        RunnerStep(action="conclude", observation_note="done"),
    ])

    def runner(spec, messages, tool_calls):
        return next(steps)

    env = run_pod(SEMANTIC_SPEC, exec_fn=_exec(_ABSENT, calls=calls), runner_step_fn=runner,
                  triager_fn=_terminate("space-exhausted"), trace_fn=_no_trace)
    assert len(calls) == 1                           # exactly one execution
    assert env["verdict"] in ("successful", "unsuccessful")


# --- C11 ----------------------------------------------------------------------

def test_empty_payload_vector_still_probes():
    calls = []
    env = run_pod({**VALID_SPEC, "payload_vector_space": {}},
                  exec_fn=_exec(_OK, calls=calls), runner_step_fn=symbolic_runner_step_fn,
                  triager_fn=None, trace_fn=_no_trace)
    assert len(calls) == 1                           # the default probe still ran
    assert env["evidence"]["raw_observations"]


# --- C12 ----------------------------------------------------------------------

def test_langfuse_failure_is_fail_open():
    def raising_trace(_run_id):
        raise RuntimeError("langfuse stub exploded")

    env = run_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=symbolic_runner_step_fn,
                  triager_fn=None, trace_fn=raising_trace)
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"
