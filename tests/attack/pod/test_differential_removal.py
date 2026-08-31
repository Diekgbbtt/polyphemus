"""Unit tier: the T0 regression guard (#150, D84-30/31) - the differential
machinery is gone from the pod. Asserts the seam signatures, the typed channels,
the graph state keys, the context slices, and the prompt verbatims carry no
`differential` / `baseline_obs` remnant, so the regrounded ReAct runner (D84-29)
can build on a clean surface."""
import asyncio
import inspect

import polymerhus.attack.hunting.pod.prompts as prompts_mod
from polymerhus.attack.hunting.pod import build_pod_graph
from polymerhus.attack.hunting.pod.agents import (
    RunnerStepFn,
    TriagerFn,
    default_runner_step_fn,
    default_triager_fn,
    symbolic_runner_step_fn,
)
from polymerhus.attack.hunting.pod.context import ExperimentLog
from polymerhus.attack.hunting.pod.types import PodState, RawObservation
from polymerhus.recon.domain.types import ExecResult

VALID_SPEC = {
    "target_identity": {"url": "http://soupmarket.shop/", "unit_id": "service:web:soupmarket"},
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "testing_pattern": "blind-boolean",
    "assumptions": ["network egress allowed"],
    "payload_vector_space": {"method": "GET", "path": "/"},
    "rationale": "reachability",
    "interpretation_guidance": "a 200 with a body confirms reachability",
}

_OK = "<html>market</html>\n__POD_HTTP_STATUS__:200\n__POD_HTTP_TIME__:0.05"


def _ok_exec(command, timeout_s):
    return ExecResult(stdout=_OK, stderr="", returncode=0, duration_ms=1)


def test_no_seam_signature_carries_differential():
    for fn in (symbolic_runner_step_fn, default_runner_step_fn, default_triager_fn):
        assert "differential" not in inspect.signature(fn).parameters
    # The typed seam aliases dropped the differential slot too.
    assert "differential" not in str(RunnerStepFn)
    assert "differential" not in str(TriagerFn)


def test_typed_channels_carry_no_differential_field():
    assert "differential" not in RawObservation.model_fields
    annotations = PodState.__annotations__
    assert "baseline_obs" not in annotations
    assert "differential" not in annotations


def test_graph_runs_without_differential_or_baseline_obs_state():
    final = asyncio.run(build_pod_graph(exec_fn=_ok_exec,
                                        runner_step_fn=symbolic_runner_step_fn,
                                        triager_fn=None).ainvoke(
                                            {"spec": dict(VALID_SPEC), "run_id": "t0"},
                                            config={"recursion_limit": 100}))
    assert "baseline_obs" not in final
    assert "differential" not in final
    for obs in final["log"].raw_observations:
        assert "differential" not in obs.model_dump()


def test_exported_raw_observations_carry_no_differential():
    env = asyncio.run(build_pod_graph(exec_fn=_ok_exec,
                                      runner_step_fn=symbolic_runner_step_fn,
                                      triager_fn=None).ainvoke(
                                          {"spec": dict(VALID_SPEC), "run_id": "t0"},
                                          config={"recursion_limit": 100}))
    for obs in env["export"]["evidence"]["raw_observations"]:
        assert "differential" not in obs


def test_context_slices_carry_no_differential():
    log = ExperimentLog()
    ctx = log.runner_context({"target_identity": {"url": "http://svc/", "unit_id": "svc"}}, feedback="vary the encoding",
                             iteration=2, budget=8)
    tctx = log.triager_context({"target_identity": {"url": "http://svc/", "unit_id": "svc"}},
                               RawObservation(status=200, body="hi"))
    assert "differential" not in ctx.lower()
    assert "differential" not in tctx.lower()


def test_prompt_verbatims_contain_no_differential_reference():
    source = inspect.getsource(prompts_mod)
    assert "differential" not in source
    assert "differential" not in prompts_mod.POD_RUNNER_SYSTEM
    assert "differential" not in prompts_mod.POD_TRIAGER_SYSTEM