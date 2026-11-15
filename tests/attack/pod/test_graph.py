"""Unit tier: the pod's looped state machine driven through `arun_pod` (the
async-only entry, D84-15) with the tools and the two agents mocked. Exercises
the control-flow mechanics - the INIT gate, the runner's agentic inner loop
(intra-chain data flow + the harness inner cap), the symbolic fast-path,
variant provenance, dedup-feeds-one-execution, the pod-budget cap, and the
clean-flag semantics.

The repo runs pytest WITHOUT pytest-asyncio: sync tests drive the async entry
with `asyncio.run`, exactly like the hunt-orchestrator graph tier's `_drive`.
"""
import asyncio
import inspect

import pytest

from polymerhus.app.llm.provider_failure import ProviderUnavailableError
from polymerhus.attack.hunting.llm import hunt_session
from polymerhus.attack.hunting.pod import arun_pod
import polymerhus.attack.hunting.pod.graph as graph_mod
from polymerhus.attack.hunting.pod.agents import symbolic_runner_step_fn
from polymerhus.attack.hunting.pod.context import ExperimentLog
from polymerhus.attack.hunting.pod.config import PodTimeouts
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
from polymerhus.attack.hunting.pod.tools import command_signature
from polymerhus.attack.hunting.pod.llm import (
    POD_DEFAULT_RUN_ID,
    POD_RUNNER_ROLE,
    POD_TRIAGER_ROLE,
    pod_session,
)
from polymerhus.attack.hunting.pod.types import RawObservation, RunnerStep
from polymerhus.recon.domain.types import ExecResult

from polymerhus.attack.hunting.pod.pod_memory import spec_identifier

# The #164 `<fault>_<strategy>` spec id (D84-34), the pod memory store key (T7).
SPEC_ID = spec_identifier("sqli", [{"axis": "technique", "value": "blind"}, {"axis": "payload-vector", "value": "boolean"}])


def _terminate_space(spec, obs, log, facts):
    """A lifecycle-v2 triager fake that ends a stretch space-exhausted."""
    return {"action": "terminate", "verdict": "unsuccessful",
            "terminal_reason": "space-exhausted", "clean": True,
            "note": "space covered"}


def _v2_confirmed(spec, obs, log, facts):
    """A lifecycle-v2 triager fake that confirms the observation - the v2
    replacement for the retired symbolic fast path in graph tests."""
    return {"action": "terminate", "verdict": "successful",
            "terminal_reason": "symptom-confirmed", "clean": True,
            "note": "verification symptom observed"}


VALID_SPEC = {
    "target_identity": {"url": "http://soupmarket.shop/", "unit_id": "service:web:soupmarket"},
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "assumptions": ["network egress allowed"],
    "rationale": "reachability",
    "provenance": {"threat_id": "threat-1", "unit_id": "service:web:soupmarket",
                   "canonical_class": "IDOR", "web_vulnerability_class": "idor"},
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


def _run(coro):
    """Drive the pod's async entry to completion (repo convention: no
    pytest-asyncio; sync tests `asyncio.run` the coroutine)."""
    return asyncio.run(coro)


# --- D84-15: the async entry is awaitable, the sync wrapper is gone -------------

def test_arun_pod_is_awaitable_and_run_pod_is_gone():
    assert inspect.iscoroutinefunction(arun_pod)
    import polymerhus.attack.hunting.pod as pod_mod
    assert not hasattr(pod_mod, "run_pod")


def test_async_seams_are_awaited_natively_by_the_graph():
    """D84-15: an ASYNC runner, ASYNC terminal, and ASYNC triager are awaited
    in-graph (the `_await_seam` `iscoroutinefunction` branch), not
    to_thread-ed."""
    calls = []

    async def runner(spec, messages, tool_calls):
        return symbolic_runner_step_fn(spec, messages, tool_calls)

    async def exec_fn(command, timeout_s):
        return ExecResult(stdout=_OK, stderr="", returncode=0, duration_ms=1)

    async def confirmed(spec, obs, log, facts):
        calls.append("triage")
        return {"action": "terminate", "verdict": "successful",
                "terminal_reason": "symptom-confirmed", "clean": True,
                "note": "the marker is reflected"}

    env = _run(arun_pod(VALID_SPEC, exec_fn=exec_fn, runner_step_fn=runner,
                        triager_fn=confirmed, trace_fn=_no_trace))
    assert calls == ["triage"]
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"


def test_init_rejection_makes_no_tool_call():
    calls = []
    env = _run(arun_pod({"target_identity": {"url": ""}, "verification_symptoms": []},
                        exec_fn=_exec(_OK, calls=calls),
                        runner_step_fn=symbolic_runner_step_fn, triager_fn=_v2_confirmed,
                        trace_fn=_no_trace))
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "technical-infeasibility"
    # The gate collects BOTH mandatory violations in one rejection.
    assert any("target_identity" in v for v in env["evidence"]["init_validation"])
    assert any("verification_symptoms" in v for v in env["evidence"]["init_validation"])
    assert calls == []                               # C1: no tool call


def test_memory_store_bound_without_spec_id_fails_closed():
    """Operator ruling (2026-08-23): the typed spec_id handoff is the runtime
    control-plane's ownership, so a bound store with NO spec_id is the dispatch's
    failure mode - the pod must NOT fall back to a hash key. The run degrades to
    `unsuccessful` with the spec_id requirement in the trail, never persists
    under the canonical hash."""
    from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore

    env = _run(arun_pod(
        VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=symbolic_runner_step_fn,
        triager_fn=_v2_confirmed, trace_fn=_no_trace, memory_store=PodMemoryStore(project_id="p1")))
    assert env["verdict"] == "unsuccessful"
    assert "spec_id" in (env["evidence"].get("error") or "")


def test_a_confirmed_triage_reaches_the_domain_terminal_through_one_lap():
    # Lifecycle v2: the symbolic fast path is retired - every domain terminal
    # comes from a triager decision. The confirmed observation is one ASSESS
    # turn away from the terminal.
    def confirmed(spec, obs, log, facts):
        return {"action": "terminate", "verdict": "successful",
                "terminal_reason": "symptom-confirmed", "clean": True,
                "note": "the marker is reflected"}

    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=confirmed, trace_fn=_no_trace))
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"
    assert env["evidence"]["iterations"] == 1
    assert env["evidence"]["clean"] is True
    assert len(env["evidence"]["raw_observations"]) == 1


def test_the_runner_authors_the_first_probe_from_the_reduced_spec():
    """S5 8.5: with no payload vector space, the runner still authors at least
    one probe from the spec - the base URL of `target_identity`."""
    calls = []
    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK, calls=calls),
                        runner_step_fn=symbolic_runner_step_fn, triager_fn=_v2_confirmed,
                        trace_fn=_no_trace))
    assert env["verdict"] == "successful"
    assert len(calls) == 1
    assert VALID_SPEC["target_identity"]["url"] in calls[0]


def test_the_baseline_ref_is_replayed_by_the_runner():
    """S5 8.5: `provenance.baseline_ref` enables replay when present - the
    runner replays the named artifact instead of authoring the request."""
    baseline = "http_01J0000000000000000000000A"
    spec = {**VALID_SPEC,
            "verification_symptoms": ["HTTP 403 on GET /admin"],
            "provenance": {**VALID_SPEC["provenance"], "baseline_ref": baseline}}
    seen = []

    def replay(project_id, artifact_id, overrides):
        seen.append((project_id, artifact_id, overrides))
        return {"status": 403, "artifact_id": "http_NEW"}

    env = _run(arun_pod(spec, exec_fn=_exec(_ABSENT),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=_v2_confirmed, replay_fn=replay, project_id="proj-1",
                        spec_id=SPEC_ID, trace_fn=_no_trace))
    assert seen == [("proj-1", baseline, {})]
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"
    obs = env["evidence"]["raw_observations"][0]
    assert obs["status"] == 403
    assert obs["http_artifact_refs"] == ["http_NEW"]


def test_no_derivable_probe_lands_no_symptom_evidence_clean_false():
    """S5 8.5: an authoring gap is impaired coverage, not target absence - it
    lands `no-symptom-evidence` with `clean=false`, never `space-exhausted`.
    The base d78d2593 would already pass THIS zero-observation case (its
    `_clean_from_trail` is false with no observations); the discriminating
    case is the later no-probe variant below."""
    steps = [RunnerStep(action="conclude", exhausted=True,
                        observation_note="no probe derivable from the spec")]
    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK),
                        runner_step_fn=_scripted(steps), triager_fn=_v2_confirmed,
                        trace_fn=_no_trace))
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "no-symptom-evidence"
    assert env["evidence"]["clean"] is False


def test_runner_failed_rejects_a_tool_error_observation():
    """The lifecycle v2 replacement for `_clean_from_trail`: the runner-failed
    harness fact reads the RAW fields - a typed error code is a failed
    execution, even with returncode 0 (the CLI's masked failure, FF-06)."""
    log = ExperimentLog()
    log.record_observation(RawObservation(
        returncode=0,
        error_code="cli_error",
        error_message="the CLI rejected the command",
        recovery={"action": "fix_command"},
    ))
    assert graph_mod._runner_failed_from(log.raw_observations[-1]) is True
    clean_obs = RawObservation(status=200, body="ok")
    assert graph_mod._runner_failed_from(clean_obs) is False
    warn_only = RawObservation(status=200, body="ok", warning={"hint": "slow"})
    assert graph_mod._runner_failed_from(warn_only) is False


def test_contract_tier_tool_exec_records_browser_error_fields():
    steps = [
        RunnerStep(action="tool_call", tool="exec",
                   command='steel browser eval "1" --session wj-live --json'),
        RunnerStep(action="conclude", observation_note="stop after the error"),
    ]

    def exec_fn(command, timeout_s):
        return ExecResult(
            stdout="", stderr="CDP error: target lost", returncode=1,
            duration_ms=1, error_code="target_lost",
            error_message="the page target is gone", retryable=False,
            fatal=False, recovery={"action": "tab_new"},
            canonical_command=command,
            session_state={"name": "wj-live", "live": True},
        )

    def triager(spec, obs, log, facts):
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "no-symptom-evidence", "clean": False}

    env = _run(arun_pod(VALID_SPEC, exec_fn=exec_fn,
                        runner_step_fn=_scripted(steps), triager_fn=triager,
                        trace_fn=_no_trace))

    obs = env["evidence"]["raw_observations"][0]
    assert obs["error_code"] == "target_lost"
    assert obs["recovery"]["action"] == "tab_new"
    assert obs["session_state"] == {"name": "wj-live", "live": True}
    assert env["evidence"]["clean"] is False


def test_a_later_variant_with_no_derivable_probe_is_not_a_clean_exhaustion():
    """S5 8.5: a spec with no derivable probe lands `no-symptom-evidence` with
    `clean=false`, never `space-exhausted`. The FIRST stretch records a clean
    observation, then the critic mints a variant with no target identity; the
    next stretch authors nothing. The base d78d2593's whole-run
    `_clean_from_trail` would have called this a clean `space-exhausted`; the
    current-stretch scope refuses it. Under lifecycle v2 the triager owns the
    exhausted-with-observations terminal and judges it itself."""
    variant_spec = {**VALID_SPEC, "target_identity": {}}
    decisions = iter([
        {"classification": "symptom-absent", "action": "variant",
         "declined_attribute": "recon-action",
         "variant_spec": variant_spec,
         "feedback": "try without a target identity"},
        {"classification": "symptom-absent", "action": "terminate",
         "verdict": "unsuccessful", "terminal_reason": "no-symptom-evidence",
         "clean": False},
    ])

    def triager(spec, obs, log, facts):
        return next(decisions)

    spec = {**VALID_SPEC, "verification_symptoms": ["reflects the marker"],
            "skill_concretised_procedure": {"recon_action": "fetch the login page",
                                            "bypass_technique": "session swap"}}
    env = _run(arun_pod(spec,
                        exec_fn=_exec(_ABSENT), runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=triager, trace_fn=_no_trace))
    assert env["evidence"]["iterations"] == 2
    assert env["evidence"]["raw_observations"]       # the first stretch did probe
    assert env["evidence"]["terminal_reason"] == "no-symptom-evidence"
    assert env["evidence"]["terminal_reason"] != "space-exhausted"
    assert env["evidence"]["clean"] is False


def test_runner_drives_a_multi_step_chain_with_intra_chain_flow():
    # The runner authors a dependency call then a core call, seeing the first
    # result before the second - the agentic loop, not a static chain.
    calls = []
    steps = [
        RunnerStep(action="tool_call", tool="exec", command="curl -k -sS -X GET https://t/login"),
        RunnerStep(action="tool_call", tool="exec", command="curl -k -sS -X GET https://t/api"),
        RunnerStep(action="conclude", observation_note="chain complete"),
    ]

    def triager(spec, obs, log, facts):
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "no-symptom-evidence", "clean": True}

    env = _run(arun_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                        exec_fn=_exec(_ABSENT, calls=calls), runner_step_fn=_scripted(steps),
                        triager_fn=triager, trace_fn=_no_trace))
    assert len(calls) == 2                           # both chain steps executed
    assert len(env["evidence"]["raw_observations"]) == 2


def test_inner_tool_cap_forces_conclusion(monkeypatch):
    # A runner that never concludes is cut by the harness inner cap (G1).
    monkeypatch.setattr("polymerhus.attack.hunting.pod.graph.HUNT_POD_MAX_TOOL_CALLS", 2)
    calls = []

    def runner(spec, messages, tool_calls):
        return RunnerStep(action="tool_call", tool="exec",
                          command=f"curl -k -sS https://t/{tool_calls}")

    def triager(spec, obs, log, facts):
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_ABSENT, calls=calls),
                        runner_step_fn=runner, triager_fn=triager, trace_fn=_no_trace))
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

    def triager(spec, obs, log, facts):
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    _run(arun_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                  exec_fn=_exec(_OK), runner_step_fn=runner, triager_fn=triager,
                  trace_fn=_no_trace))
    assert len(seen) >= 2
    assert any("TOOL RESULT" in m["content"] for m in seen[1])   # 2nd turn sees the 1st result


def test_variant_threat_records_provenance():
    decisions = iter([
        {"classification": "symptom-absent", "action": "variant",
         "declined_attribute": "recon-action",
         "variant_spec": {**VALID_SPEC, "rationale": "reachability of /api"},
         "feedback": "try /api"},
        {"classification": "symptom-absent", "action": "terminate",
         "verdict": "unsuccessful", "terminal_reason": "space-exhausted", "clean": True},
    ])

    def triager(spec, obs, log, facts):
        return next(decisions)

    spec = {**VALID_SPEC, "verification_symptoms": ["reflects the marker"],
            "skill_concretised_procedure": {"recon_action": "fetch the login page",
                                            "bypass_technique": "session swap"}}
    env = _run(arun_pod(spec,
                        exec_fn=_exec(_ABSENT), runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=triager, trace_fn=_no_trace))
    assert env["evidence"]["iterations"] == 2
    variants = env["evidence"]["variant_specs"]
    assert [v["ref"] for v in variants] == ["v0", "v1"]
    assert variants[1]["parent_ref"] == "v0"
    assert variants[1]["declined_attribute"] == "recon-action"


def test_pod_budget_cap_degrades_the_variant_instead_of_the_budget_terminal(monkeypatch):
    # Lifecycle v2: the triager node knows the lap cap through `variant_allowed`
    # BEFORE the decision, so a variant-insisting triager degrades to the honest
    # domain terminal - the harness budget terminal is only a backstop.
    monkeypatch.setattr("polymerhus.attack.hunting.pod.graph.HUNT_POD_MAX_ITERS", 3)
    lap = {"n": 0}

    def triager(spec, obs, log, facts):
        # A DISTINCT derived detail each lap: the S5 8.6 duplicate guard refuses
        # a repeated (basis, detail), so a degenerate re-mint would terminate
        # before the budget instead of exercising the cap.
        lap["n"] += 1
        return {"classification": "symptom-absent", "action": "variant",
                "declined_attribute": "bypass-technique",
                "variant_spec": {**spec, "rationale": f"bypass attempt {lap['n']}"},
                "feedback": "keep trying"}

    spec = {**VALID_SPEC, "verification_symptoms": ["reflects the marker"],
            "skill_concretised_procedure": {"recon_action": "fetch the login page",
                                            "bypass_technique": "session swap"}}
    env = _run(arun_pod(spec,
                        exec_fn=_exec(_ABSENT), runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=triager, trace_fn=_no_trace))
    assert env["evidence"]["terminal_reason"] == "no-symptom-evidence"
    assert env["evidence"]["clean"] is False
    assert env["evidence"]["iterations"] == 3


def test_dedup_one_execution_per_identical_probe():
    calls = []
    steps = [
        RunnerStep(action="tool_call", tool="exec", command="curl -k -sS https://t/"),
        RunnerStep(action="tool_call", tool="exec", command="curl -k -sS https://t/"),  # identical
        RunnerStep(action="conclude", observation_note="done"),
    ]

    def triager(spec, obs, log, facts):
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    _run(arun_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                  exec_fn=_exec(_ABSENT, calls=calls), runner_step_fn=_scripted(steps),
                  triager_fn=triager, trace_fn=_no_trace))
    assert len(calls) == 1                           # O7/C10: executed once


def test_runner_infeasible_is_an_init_gate_with_evidence():
    steps = [RunnerStep(action="conclude", infeasible=True,
                        unverified=["no WAF on /api/a could not be confirmed"])]
    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=_scripted(steps),
                        triager_fn=_v2_confirmed, trace_fn=_no_trace))
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert any("WAF" in v for v in env["evidence"]["init_validation"])


def test_a_productive_runner_exhaustion_routes_to_the_triager():
    """Lifecycle v2: a stretch that DID author and execute a probe, then
    concludes exhausted, routes to the TRIAGER - the exhausted-with-observations
    terminal is a triager decision, never a harness trail grep. The triager
    here claims a clean `space-exhausted`, which the finalizer renders."""
    steps = [RunnerStep(action="tool_call", tool="exec", command="curl -k -sS https://t/"),
             RunnerStep(action="conclude", exhausted=True,
                        observation_note="no new probe derivable")]
    seen = []

    def spaced(spec, obs, log, facts):
        seen.append(dict(facts))
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True,
                "note": "the space is covered"}

    env = _run(arun_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                        exec_fn=_exec(_ABSENT), runner_step_fn=_scripted(steps),
                        triager_fn=spaced, trace_fn=_no_trace))
    assert seen and seen[-1]["runner_exhausted"] is True
    assert env["evidence"]["terminal_reason"] == "space-exhausted"
    assert env["evidence"]["clean"] is True


def test_clean_false_when_triager_reports_defence():
    def triager(spec, obs, log, facts):
        return {"classification": "infeasibility-signal", "action": "terminate",
                "verdict": "unsuccessful", "terminal_reason": "specific-defence-prevention",
                "clean": False, "note": "WAF soft-blocked every probe"}

    env = _run(arun_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                        exec_fn=_exec(_ABSENT), runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=triager, trace_fn=_no_trace))
    assert env["evidence"]["terminal_reason"] == "specific-defence-prevention"
    assert env["evidence"]["clean"] is False


# --- T3 (#153): graph-owned pod-session ContextVar binding (D84-7) -----------

def test_runner_seam_observes_pod_runner_session_inside_a_hunt():
    """D84-7/Q13: inside a parent `hunt_session`, the `runner_agent` node binds
    the pod_runner role's typed `HuntSession` - the parent's run_id/hunt_id +
    the semantic `<fault>_<strategy>` spec id (the crossed handoff, ADR #169
    Q13) - around the seam call, so the default seam receives the typed address
    (this spy reads the ContextVar like the default seam does; the sync spy
    rides `asyncio.to_thread` via `_await_seam`, whose context copy carries
    the binding)."""
    seen = []

    def runner(spec, messages, tool_calls):
        seen.append(pod_session())
        return symbolic_runner_step_fn(spec, messages, tool_calls)

    with hunt_session("run-1", "hunt-A"):
        env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=runner,
                            triager_fn=_v2_confirmed, trace_fn=_no_trace, spec_id=SPEC_ID))

    assert env["verdict"] == "successful"
    ctx = seen[0]
    assert ctx is not None
    assert ctx.address.role_id == POD_RUNNER_ROLE
    assert ctx.address.run_id == "run-1"
    assert ctx.address.hunt_id == "hunt-A"
    assert ctx.address.spec == SPEC_ID


def test_runner_seam_sees_a_task_local_default_outside_a_hunt():
    """Without a parent hunt_session the graph still runs (fail-open): the seam
    sees the task-local default session - the pod's run_id and an empty hunt_id
    (an empty discriminator is dropped from the address, never shifting it)."""
    seen = []

    def runner(spec, messages, tool_calls):
        seen.append(pod_session())
        return symbolic_runner_step_fn(spec, messages, tool_calls)

    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=runner,
                        triager_fn=_v2_confirmed, trace_fn=_no_trace))

    assert env["verdict"] == "successful"
    ctx = seen[0]
    assert ctx is not None
    assert ctx.address.role_id == POD_RUNNER_ROLE
    assert ctx.address.run_id == POD_DEFAULT_RUN_ID
    assert ctx.address.hunt_id == ""


def test_triager_seam_observes_pod_triager_session_inside_a_hunt():
    """The `triager` node binds the pod_triager role's `HuntSession` when its
    seam is consulted (the symbolic fast-path stays silent for a semantic
    symptom), again deriving the instance from the parent hunt and the crossed
    semantic spec id."""
    spec = {**VALID_SPEC, "verification_symptoms": ["reflects the marker"]}
    seen = []

    def triager(s, obs, messages, log):
        seen.append(pod_session())
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    with hunt_session("run-1", "hunt-A"):
        env = _run(arun_pod(spec, exec_fn=_exec(_ABSENT), runner_step_fn=symbolic_runner_step_fn,
                            triager_fn=triager, trace_fn=_no_trace, spec_id=SPEC_ID))

    assert env["verdict"] == "unsuccessful"
    ctx = seen[0]
    assert ctx is not None
    assert ctx.address.role_id == POD_TRIAGER_ROLE
    assert ctx.address.run_id == "run-1"
    assert ctx.address.hunt_id == "hunt-A"
    assert ctx.address.spec == SPEC_ID


# --- T6 (#156): BaseMessage + add_messages channels (D84-4) -------------------

def test_runner_channel_accumulates_appended_messages_in_order():
    """D84-4: the runner message channel is `Annotated[list[BaseMessage],
    add_messages]` - every node deposits ONLY its turn's new messages and the
    reducer appends them onto the channel, so the agentic loop's turns
    ACCUMULATE (order preserved, types intact) instead of replacing the channel
    wholesale. Lifecycle v2: the triager owns its OWN thread, so there is no
    triager message channel to assert."""
    from langchain_core.messages import BaseMessage

    from polymerhus.attack.hunting.pod.graph import build_pod_graph
    from polymerhus.attack.hunting.pod.prompts import load_pod_runner_skill

    RUNNER_SYSTEM = load_pod_runner_skill()

    steps = iter([
        RunnerStep(action="tool_call", tool="exec", command="curl -k -sS https://t/"),
        RunnerStep(action="conclude", observation_note="chain done"),
    ])

    def runner(spec, messages, tool_calls):
        return next(steps)

    def triager(spec, obs, log, facts):
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    graph = build_pod_graph(exec_fn=_exec(_ABSENT), runner_step_fn=runner,
                            triager_fn=triager)
    final = _run(graph.ainvoke({"spec": dict(VALID_SPEC)}))

    msgs = final["runner_messages"]
    assert all(isinstance(m, BaseMessage) for m in msgs)     # the typed channel
    assert [m.type for m in msgs] == ["system", "human", "ai", "human", "ai"]
    assert msgs[0].content == RUNNER_SYSTEM         # the system prompt
    assert "action: tool_call" in msgs[2].content            # turn 1's proposal
    assert "TOOL RESULT" in msgs[3].content                  # the recorded observation
    assert "action: conclude" in msgs[4].content             # turn 2: appended, not replaced


def test_duplicate_content_messages_dedup_under_same_id_in_the_channel():
    """A repeated identical runner turn stamps the same id, so add_messages
    merges it in place (dedup-under-same-id) instead of stacking a duplicate
    turn; execution dedup stays the experiment log's job (O7/C10), untouched."""
    from polymerhus.attack.hunting.pod.graph import build_pod_graph

    steps = iter([
        RunnerStep(action="tool_call", tool="exec", command="curl -k -sS https://t/"),
        RunnerStep(action="tool_call", tool="exec", command="curl -k -sS https://t/"),  # identical turn
        RunnerStep(action="conclude", observation_note="done"),
    ])

    def runner(spec, messages, tool_calls):
        return next(steps)

    def triager(spec, obs, log, facts):
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    graph = build_pod_graph(exec_fn=_exec(_ABSENT), runner_step_fn=runner,
                            triager_fn=triager)
    final = _run(graph.ainvoke({"spec": dict(VALID_SPEC)}))

    ais = [m for m in final["runner_messages"] if m.type == "ai"]
    # The two identical tool_call turns merged to ONE (dedup-under-same-id)...
    assert len([m for m in ais if "tool_call" in m.content]) == 1
    # ...while the distinct conclude turn still appended.
    assert len([m for m in ais if "conclude" in m.content]) == 1
    tools = [m for m in final["runner_messages"]
             if m.type == "human" and "TOOL" in m.content]
    assert len(tools) == 2                        # both tool RESULTS recorded (log-deduped)


def test_seams_receive_curated_dict_views_with_role_and_content():
    """D84-4: the message-type conversion happens at the graph-channel boundary -
    the channel is BaseMessage, but every seam still receives its CURATED DICT
    views ({role, content}) exactly like before; the type boundary never leaks
    into the seams. Lifecycle v2: the triager seam's new message is the ASSESS
    packet (a plain string, composed from the log), and the runner keeps its
    curated dict views."""
    runner_views, triager_facts = [], []

    def runner(spec, messages, tool_calls):
        runner_views.append(list(messages))
        return symbolic_runner_step_fn(spec, messages, tool_calls)

    def triager(spec, obs, log, facts):
        triager_facts.append(dict(facts))
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    env = _run(arun_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                        exec_fn=_exec(_ABSENT), runner_step_fn=runner,
                        triager_fn=triager, trace_fn=_no_trace))
    assert env["verdict"] == "unsuccessful"
    assert runner_views and triager_facts
    for view in runner_views[0]:
        assert "role" in view and "content" in view
        assert view["role"] in ("system", "human", "ai", "tool")
    # The triager seam takes the typed facts record, not a curated view.
    assert triager_facts[0]["thread_id"]


# --- T7 (#183): the pod owns the persistence of its OWN terminal result ---------

def test_terminal_export_persists_to_spec_run_id(tmp_path):
    """T7 (GP1/GP3/GP4): a completed run with a bound store + spec_id persists
    its `PodExport` envelope to `<spec_id>/<run_id>.yaml` - the persisted record
    EQUALS the returned envelope (`env["evidence"]` round-trips), written by the
    deterministic terminal node."""
    from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore

    store = PodMemoryStore(tmp_path)
    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=_v2_confirmed, trace_fn=_no_trace, memory_store=store,
                        spec_id=SPEC_ID, run_id="run-42"))
    assert env["verdict"] == "successful"
    persisted = store.read_pod_export(SPEC_ID, "run-42")
    assert persisted == env                       # the persisted record == the returned envelope


def test_export_rerun_overwrites_a_harness_export(tmp_path):
    """GP1/D84-37: a re-run of the same spec with the SAME run_id overwrites the
    same `<spec_id>/<run_id>.yaml` when the prior export is a harness terminal -
    the deterministic path is the address. Monotonicity rule (a): a latched
    DOMAIN verdict is final, so a domain re-run of the same run returns the
    first verdict instead of overwriting it."""
    from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore

    store = PodMemoryStore(tmp_path)
    store.write_pod_export(SPEC_ID, "run-1", {
        "verdict": "unsuccessful",
        "evidence": {"terminal_reason": "node-timeout", "clean": False},
    })
    env1 = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=symbolic_runner_step_fn,
                         triager_fn=_v2_confirmed, trace_fn=_no_trace, memory_store=store,
                         spec_id=SPEC_ID, run_id="run-1"))
    assert env1["verdict"] == "successful"
    assert store.read_pod_export(SPEC_ID, "run-1") == env1
    assert store.list_pod_exports(SPEC_ID) == ["run-1"]   # one file, overwritten

    env2 = _run(arun_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                         exec_fn=_exec(_ABSENT), runner_step_fn=symbolic_runner_step_fn,
                         triager_fn=_terminate_space, trace_fn=_no_trace,
                         memory_store=store, spec_id=SPEC_ID, run_id="run-1"))
    # A second DOMAIN verdict never replaces the first (rule a): the re-run
    # reads back the first evaluation instead of rewriting it.
    assert env2 == env1
    assert store.read_pod_export(SPEC_ID, "run-1") == env1


def test_export_write_failure_degrades_to_the_envelope(tmp_path):
    """O3/IA-4 fail-open: a write failure degrades to the in-memory envelope -
    the run STILL returns it to the parent and never raises."""
    from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore

    class _FailingStore(PodMemoryStore):
        def write_pod_export(self, spec_id, run_id, export_dict):
            raise OSError("boom")

    store = _FailingStore(tmp_path)
    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=_v2_confirmed, trace_fn=_no_trace, memory_store=store,
                        spec_id=SPEC_ID, run_id="run-42"))
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"


# --- the lifecycle v2 pod wiring (slice 8) -------------------------------------

def _terminate_v2(spec, obs, log, facts, seen=None):
    """A lifecycle-v2 triager fake with the NEW seam shape: the facts are an
    explicit argument."""
    if seen is not None:
        seen.append(dict(facts))
    return {"action": "terminate", "verdict": "unsuccessful",
            "terminal_reason": "no-symptom-evidence", "clean": False,
            "note": "impaired observations"}


def test_the_triager_seam_receives_the_harness_facts():
    seen = []
    spec = {**VALID_SPEC,
            "skill_concretised_procedure": {
                "recon_action": "fetch the login page",
                "bypass_technique": "session swap"}}
    env = _run(arun_pod(spec, exec_fn=_exec(_ABSENT),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=lambda *a, **k: _terminate_v2(*a, seen=seen),
                        trace_fn=_no_trace))
    assert seen, "the v2 seam ran"
    facts = seen[-1]
    assert facts["lap"] == 1
    assert facts["thread_id"]
    assert facts["runner_failed"] is False
    assert facts["variant_allowed"] is True
    assert facts["runner_terminated"] is None


def test_a_spec_without_a_mintable_procedure_disallows_variants():
    seen = []
    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_ABSENT),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=lambda *a, **k: _terminate_v2(*a, seen=seen),
                        trace_fn=_no_trace))
    assert seen[-1]["variant_allowed"] is False
    assert env["verdict"] == "unsuccessful"


def test_runner_failed_is_a_harness_fact_from_the_observation():
    seen = []
    # An exec failure the runner recorded: an error code names a failed
    # execution, whatever the triager claims.
    def failing(command, timeout_s):
        return ExecResult(stdout="", stderr="boom", returncode=1,
                          error_code="EXEC_FAILED", error_message="boom",
                          duration_ms=1)

    env = _run(arun_pod(VALID_SPEC, exec_fn=failing,
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=lambda *a, **k: _terminate_v2(*a, seen=seen),
                        trace_fn=_no_trace))
    assert seen[-1]["runner_failed"] is True
    assert env["verdict"] == "unsuccessful"


def test_an_exhausted_stretch_with_observations_routes_to_the_triager():
    seen = []

    # First stretch: author and run one probe (an observation lands), then
    # conclude exhausted.
    runner = _scripted([
        RunnerStep(action="tool_call", tool="exec",
                   command="curl -k https://svc/search?q=marker"),
        RunnerStep(action="conclude", exhausted=True,
                   observation_note="nothing new derivable"),
    ])

    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_ABSENT),
                        runner_step_fn=runner,
                        triager_fn=lambda *a, **k: _terminate_v2(*a, seen=seen),
                        trace_fn=_no_trace))
    # The stretch observed something (the authored probe), so the triager owns
    # the terminal; the harness exhaustion is a fact, not a terminal.
    assert seen, "the triager judged the exhausted stretch"
    assert seen[-1]["runner_exhausted"] is True
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "no-symptom-evidence"
    assert "node-timeout" not in env["evidence"]["terminal_reason"]


def test_a_no_probe_exhaustion_is_a_harness_terminal():
    seen = []

    def conclude_empty(spec, messages, tool_calls):
        return RunnerStep(action="conclude", exhausted=True,
                          observation_note="no probe authored")

    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_ABSENT),
                        runner_step_fn=conclude_empty,
                        triager_fn=lambda *a, **k: _terminate_v2(*a, seen=seen),
                        trace_fn=_no_trace))
    # No observation this stretch: nothing to judge, the harness terminal stands.
    assert seen == []
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "no-symptom-evidence"
    assert env["evidence"]["clean"] is False


def test_a_runner_kill_routes_to_the_triager_with_runner_terminated():
    seen = []

    # Stretch 1 records an observation; stretch 2's runner turn hangs, so the
    # kill reaches the triager with something to judge.
    calls = {"n": 0}

    async def runner(spec, messages, tool_calls):
        calls["n"] += 1
        if calls["n"] == 1:
            return RunnerStep(action="tool_call", tool="exec",
                              command="curl -k -sS https://t/")
        await asyncio.sleep(30)

    env = _run(arun_pod(
        VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=runner,
        triager_fn=lambda *a, **k: _terminate_v2(*a, seen=seen),
        trace_fn=_no_trace,
        timeouts=PodTimeouts(node_idle_s=0.01, node_run_s=None,
                             tool_idle_s=None, tool_run_s=None)))
    # The kill routes to the triager for a final pass: the control-plane fact
    # kills variant minting, and the triager still evaluates the last execution.
    assert seen, "the triager ran after the kill"
    assert seen[-1]["runner_terminated"] == "node-timeout"
    assert seen[-1]["variant_allowed"] is False
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["control_plane_end_reason"] == "node-timeout"


def test_a_triager_failure_after_a_kill_leaves_the_harness_terminal_standing():
    async def hung(spec, messages, tool_calls):
        await asyncio.sleep(30)

    def broken(spec, obs, log, facts):
        raise RuntimeError("no bound pod session for the triager")

    env = _run(arun_pod(
        VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=hung,
        triager_fn=broken, trace_fn=_no_trace,
        timeouts=PodTimeouts(node_idle_s=0.01, node_run_s=None,
                             tool_idle_s=None, tool_run_s=None)))
    # The triager could not evaluate, so the control-plane fact is the honest
    # export - never a fabricated domain verdict.
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "node-timeout"
    assert env["evidence"]["clean"] is False
    assert "control_plane_end_reason" not in env["evidence"]


def test_the_budget_cap_degrades_the_variant_instead_of_the_budget_terminal():
    seen = []

    def insist_variant(spec, obs, log, facts):
        seen.append(dict(facts))
        return {"action": "variant", "classification": "payload-vector",
                "declined_attribute": "payload-vector",
                "variant_spec": {**spec, "rationale": "untested vector"},
                "feedback": "try the vector", "note": "one more"}

    env = _run(arun_pod({**VALID_SPEC, "verification_symptoms": ["never reflected"]},
                        exec_fn=_exec(_ABSENT),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=insist_variant, trace_fn=_no_trace,
                        timeouts=None))
    # The triage machine already knows the lap cap: variant_allowed rides the
    # facts, so a variant decision degrades to the honest domain terminal
    # instead of the harness budget-timeout.
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "no-symptom-evidence"
    assert "budget-timeout" != env["evidence"]["terminal_reason"]
    assert seen[-1]["variant_allowed"] is False


def test_the_interpretation_records_the_phase_path():
    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_ABSENT),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=_terminate_v2, trace_fn=_no_trace))
    interpretations = env["evidence"]["interpretations"]
    assert interpretations, "the triage decision was recorded"
    # The additive phase-path field exists on every interpretation; the
    # production harness stamps the walked chain, a contract-tier fake is
    # one-shot and leaves it empty (the production stamping is pinned in
    # test_react_seams.py).
    assert "phase_path" in interpretations[-1]


def test__clean_from_trail_is_gone():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[3]
              / "src/polymerhus/attack/hunting/pod/graph.py").read_text()
    assert "_clean_from_trail" not in source


def test_a_degraded_kb_no_longer_forces_clean_false():
    # The #304 guard keeps its terminal-reason downgrade but no longer touches
    # the triager's clean: degraded KB is a sufficiency condition, not an
    # integrity condition. (The KB-tool-level coverage lives in
    # test_kb_degradation_guard.py; here a triager claims a clean exhaustion
    # and the clean value survives the graph.)
    def spaced(spec, obs, log, facts):
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True,
                "note": "space covered"}

    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_ABSENT),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=spaced, trace_fn=_no_trace))
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "space-exhausted"
    assert env["evidence"]["clean"] is True


def test_the_assessment_clean_rides_into_the_terminal():
    def unclean_terminate(spec, obs, log, facts):
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "no-symptom-evidence", "clean": False,
                "note": "blocked observations"}

    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_ABSENT),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=unclean_terminate, trace_fn=_no_trace))
    assert env["evidence"]["clean"] is False


def test_a_confirmed_symptom_still_reaches_the_domain_terminal():
    def confirmed(spec, obs, log, facts):
        return {"action": "terminate", "verdict": "successful",
                "terminal_reason": "symptom-confirmed", "clean": True,
                "note": "the marker is reflected"}

    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=confirmed, trace_fn=_no_trace))
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"
    assert env["evidence"]["clean"] is True


def test_a_kill_on_a_stretch_with_no_observation_keeps_the_harness_terminal():
    # Ratified: a kill is not a reason to skip triage - but there must be
    # something to judge. A kill on a stretch with NO observation has nothing
    # to evaluate, so the harness terminal stands (symmetric with the
    # exhaustion split); a vacuously clean space-exhausted can never latch.
    seen = []

    async def hung(spec, messages, tool_calls):
        await asyncio.sleep(30)

    def spaced(spec, obs, log, facts):
        seen.append(dict(facts))
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True,
                "note": "vacuous clean claim"}

    env = _run(arun_pod(
        VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=hung,
        triager_fn=spaced, trace_fn=_no_trace,
        timeouts=PodTimeouts(node_idle_s=0.01, node_run_s=None,
                             tool_idle_s=None, tool_run_s=None)))
    assert seen == [], "nothing to judge: the triager never ran"
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "node-timeout"
    assert env["evidence"]["clean"] is False
    assert "control_plane_end_reason" not in env["evidence"]


def test_a_provider_failure_in_the_triager_after_a_kill_propagates():
    # #329/#312: a provider failure is infrastructure even after a kill; the
    # surfer owns the retry, and no domain verdict is fabricated. The kill
    # reaches the triager with something to judge (stretch 1 probed).
    calls = {"n": 0}

    async def runner(spec, messages, tool_calls):
        calls["n"] += 1
        if calls["n"] == 1:
            return RunnerStep(action="tool_call", tool="exec",
                              command="curl -k -sS https://t/")
        await asyncio.sleep(30)

    def throttled(spec, obs, log, facts):
        raise ProviderUnavailableError("429 too many requests")

    with pytest.raises(ProviderUnavailableError):
        _run(arun_pod(
            VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=runner,
            triager_fn=throttled, trace_fn=_no_trace,
            timeouts=PodTimeouts(node_idle_s=0.01, node_run_s=None,
                                 tool_idle_s=None, tool_run_s=None)))


def test_a_tool_timeout_routes_to_the_triager():
    # Ratified kill list: a runner node timeout, a tool timeout, and the pod
    # budget cap. The route keys on the FAILURE REASON, not the node name. The
    # first tool call succeeds (an observation lands), the second hangs.
    seen = []

    exec_calls = {"n": 0}

    async def hung_second(command, timeout_s):
        exec_calls["n"] += 1
        if exec_calls["n"] >= 2:
            await asyncio.sleep(30)
        return ExecResult(stdout=_OK, stderr="", returncode=0, duration_ms=1)

    steps = [RunnerStep(action="tool_call", tool="exec",
                        command="curl -k -sS https://t/"),
             RunnerStep(action="tool_call", tool="exec",
                        command="curl -k -sS https://t/2"),
             RunnerStep(action="conclude", observation_note="done")]

    env = _run(arun_pod(VALID_SPEC, exec_fn=hung_second,
                        runner_step_fn=_scripted(steps),
                        triager_fn=lambda *a, **k: _terminate_v2(*a, seen=seen),
                        trace_fn=_no_trace,
                        timeouts=PodTimeouts(node_idle_s=None, node_run_s=None,
                                             tool_idle_s=0.01, tool_run_s=None)))
    assert seen and seen[-1]["runner_terminated"] == "tool-timeout", (
        seen, env["evidence"]["terminal_reason"], env["evidence"].get("error"))
    assert seen[-1]["variant_allowed"] is False
    assert env["verdict"] == "unsuccessful"


def test_a_kill_does_not_claim_runner_exhausted():
    # A kill is not an exhaustion: the facts must not invite a clean absence.
    seen = []

    calls = {"n": 0}

    async def runner(spec, messages, tool_calls):
        calls["n"] += 1
        if calls["n"] == 1:
            return RunnerStep(action="tool_call", tool="exec",
                              command="curl -k -sS https://t/")
        await asyncio.sleep(30)

    _run(arun_pod(
        VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=runner,
        triager_fn=lambda *a, **k: _terminate_v2(*a, seen=seen),
        trace_fn=_no_trace,
        timeouts=PodTimeouts(node_idle_s=0.01, node_run_s=None,
                             tool_idle_s=None, tool_run_s=None)))
    assert seen and seen[-1]["runner_exhausted"] is False
    assert seen[-1]["runner_terminated"] == "node-timeout"


def test_a_malformed_triage_degrade_after_a_kill_keeps_the_harness_terminal():
    # Every NO-EVALUATION triage outcome is marked degraded; after a kill the
    # harness terminal stands. A malformed submission that the node degrades is
    # no evaluation either.
    async def hung(spec, messages, tool_calls):
        await asyncio.sleep(30)

    def malformed(spec, obs, log, facts):
        return {"action": "terminate", "verdict": "maybe",
                "terminal_reason": "not-a-reason", "clean": "yes"}

    env = _run(arun_pod(
        VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=hung,
        triager_fn=malformed, trace_fn=_no_trace,
        timeouts=PodTimeouts(node_idle_s=0.01, node_run_s=None,
                             tool_idle_s=None, tool_run_s=None)))
    assert env["evidence"]["terminal_reason"] == "node-timeout"
    assert env["evidence"]["clean"] is False
    assert "control_plane_end_reason" not in env["evidence"]


def test_the_delivered_decision_is_never_overridden_by_init_validation():
    # Monotonicity rule 1: a durable domain verdict is final. A non-URL INIT
    # violation (which does not stop the run) must never overwrite an evaluated
    # confirmation; the INIT rejection belongs to the init_router's own path.
    def confirmed(spec, obs, log, facts):
        return {"action": "terminate", "verdict": "successful",
                "terminal_reason": "symptom-confirmed", "clean": True,
                "note": "the marker is reflected"}

    mixed = {**VALID_SPEC, "verification_symptoms": ["HTTP 200", 42]}
    env = _run(arun_pod(mixed, exec_fn=_exec(_OK),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=confirmed, trace_fn=_no_trace))
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"


def test_the_init_rejection_still_rejects_before_any_probe():
    env = _run(arun_pod({"target_identity": {"url": ""}, "verification_symptoms": []},
                        exec_fn=_exec(_OK),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=_v2_confirmed, trace_fn=_no_trace))
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert env["evidence"]["init_validation"]


def test_the_terminal_default_reason_is_the_weakest_absence():
    # A missing terminal_reason in a delivered decision must never default to
    # the strongest absence claim.
    def blank_reason(spec, obs, log, facts):
        return {"action": "terminate", "verdict": "unsuccessful",
                "note": "no reason given"}

    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_ABSENT),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=blank_reason, trace_fn=_no_trace))
    assert env["evidence"]["terminal_reason"] == "no-symptom-evidence"


def test_a_duplicate_variant_degrade_keeps_the_assessed_clean():
    # Q9: clean is triager-owned. A duplicate refusal is a sufficiency
    # condition, not an integrity judgement; the assessed clean stands.
    def re_minting(spec, obs, log, facts):
        # The contract-tier fake states its own clean judgement (the
        # production harness stamps the assessment's clean instead).
        return {"action": "variant", "declined_attribute": "recon-action",
                "clean": True, "variant_spec": dict(spec),
                "feedback": "same again", "note": "duplicate"}

    spec = {**VALID_SPEC, "verification_symptoms": ["reflects the marker"],
            "skill_concretised_procedure": {"recon_action": "fetch the login page"}}
    env = _run(arun_pod(spec, exec_fn=_exec(_ABSENT),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=re_minting, trace_fn=_no_trace))
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "no-symptom-evidence"
    # The assessment claimed clean=true; it rides into the terminal.
    assert env["evidence"]["clean"] is True


def test_the_variant_not_allowed_reason_names_the_three_causes():
    seen = []

    def insist(spec, obs, log, facts):
        seen.append(dict(facts))
        return {"action": "variant", "declined_attribute": "payload-vector",
                "variant_spec": {**spec, "rationale": "untested"},
                "feedback": "f", "note": "one more"}

    # No mintable procedure -> the recorded gap reason.
    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_ABSENT),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=insist, trace_fn=_no_trace))
    assert seen[-1]["variant_allowed"] is False
    notes = " ".join(i["note"] for i in env["evidence"]["interpretations"])
    assert "recorded gap" in notes.lower()


# --- pod control-plane failure handling (2026-10-26) -------------------------

def test_a_hung_runner_routes_to_a_node_timeout_terminal_with_the_log():
    async def hung(spec, messages, tool_calls):
        await asyncio.sleep(30)

    env = _run(arun_pod(
        VALID_SPEC,
        exec_fn=_exec(_OK),
        runner_step_fn=hung,
        trace_fn=_no_trace,
        timeouts=PodTimeouts(
            node_idle_s=0.01, node_run_s=None,
            tool_idle_s=None, tool_run_s=None,
        ),
    ))

    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "node-timeout"
    assert env["evidence"]["clean"] is False
    assert "runner_agent" in env["evidence"]["error"]
    assert env["evidence"]["variant_specs"][0]["ref"] == "v0"


def test_a_provider_failure_in_a_node_is_not_a_domain_verdict():
    async def provider(spec, messages, tool_calls):
        raise ProviderUnavailableError("429 too many requests")

    with pytest.raises(ProviderUnavailableError):
        _run(arun_pod(
            VALID_SPEC,
            exec_fn=_exec(_OK),
            runner_step_fn=provider,
            trace_fn=_no_trace,
            timeouts=PodTimeouts(
                node_idle_s=None, node_run_s=None,
                tool_idle_s=None, tool_run_s=None,
            ),
        ))


def test_a_context_window_error_is_a_typed_terminal():
    async def context(spec, messages, tool_calls):
        raise Exception("This model's maximum context length is 128000 tokens")

    env = _run(arun_pod(
        VALID_SPEC,
        exec_fn=_exec(_OK),
        runner_step_fn=context,
        trace_fn=_no_trace,
        timeouts=PodTimeouts(
            node_idle_s=None, node_run_s=None,
            tool_idle_s=None, tool_run_s=None,
        ),
    ))

    assert env["evidence"]["terminal_reason"] == "context-window-exceeded"
    assert env["evidence"]["clean"] is False
    assert "context" in env["evidence"]["error"].lower()


def test_a_generic_node_error_keeps_the_domain_degrade():
    async def generic(spec, messages, tool_calls):
        raise RuntimeError("bad parsing")

    env = _run(arun_pod(
        VALID_SPEC,
        exec_fn=_exec(_OK),
        runner_step_fn=generic,
        trace_fn=_no_trace,
        timeouts=PodTimeouts(
            node_idle_s=None, node_run_s=None,
            tool_idle_s=None, tool_run_s=None,
        ),
    ))

    assert env["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert "bad parsing" in env["evidence"]["error"]


def test_a_hung_tool_routes_to_a_tool_timeout_terminal():
    async def hanging_exec(*args, **kwargs):
        await asyncio.sleep(30)

    def runner(spec, messages, tool_calls):
        return RunnerStep(action="tool_call", tool="exec",
                          command="curl -k -sS https://target/")

    env = _run(arun_pod(
        VALID_SPEC,
        exec_fn=hanging_exec,
        runner_step_fn=runner,
        trace_fn=_no_trace,
        timeouts=PodTimeouts(
            node_idle_s=None, node_run_s=None,
            tool_idle_s=0.01, tool_run_s=None,
        ),
    ))

    assert env["evidence"]["terminal_reason"] == "tool-timeout"
    assert env["evidence"]["clean"] is False
    assert "tool_exec" in env["evidence"]["error"]


def test_a_graph_recursion_error_is_a_typed_graph_limit(monkeypatch):
    monkeypatch.setattr(
        "polymerhus.attack.hunting.pod.pod.RECURSION_LIMIT", 3)

    def runner(spec, messages, tool_calls):
        return RunnerStep(action="tool_call", tool="exec",
                          command="curl -k -sS https://target/")

    env = _run(arun_pod(
        VALID_SPEC,
        exec_fn=_exec(_OK),
        runner_step_fn=runner,
        trace_fn=_no_trace,
    ))

    assert env["evidence"]["terminal_reason"] == "graph-limit"
    assert env["evidence"]["clean"] is False
    assert "recursion" in env["evidence"]["error"].lower()


# --- durable resume (2026-10-26) ---------------------------------------------

RUN = "run-resume"
COMMAND = "curl -k -sS https://target/"
RESUME_SPEC = {
    **VALID_SPEC,
    "verification_symptoms": ["reflects the marker"],
}


def _seed_resume(tmp_path):
    store = PodMemoryStore(tmp_path / "pod")
    store.write_variant(
        SPEC_ID, "v0",
        {"ref": "v0", "parent_ref": None, "declined_attribute": "",
         "spec": {**RESUME_SPEC, "rationale": "resumed"}},
    )
    store.write_experiment_log(SPEC_ID, 0, {
        "order": 0,
        "variant_ref": "v0",
        "raw_observations": [],
        "kb_observations": [],
        "interpretations": [],
        "executed": [command_signature("v0", COMMAND)],
    })
    store.write_resume(SPEC_ID, RUN, {
        "schema_version": 1,
        "last_order": 0,
        "current_variant_ref": "v0",
        "iteration": 1,
        "feedback": "continue from the persisted variant",
    })
    return store


def test_a_resumed_pod_skips_an_executed_probe(tmp_path):
    store = _seed_resume(tmp_path)
    new_command = "curl -k -sS https://target/new"
    steps = [
        RunnerStep(action="tool_call", tool="exec", command=COMMAND),
        RunnerStep(action="tool_call", tool="exec", command=new_command),
        RunnerStep(action="conclude", observation_note="done"),
    ]
    calls = []

    def triager(spec, obs, log, facts):
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    env = _run(arun_pod(
        RESUME_SPEC,
        exec_fn=_exec(_OK, calls=calls),
        runner_step_fn=_scripted(steps),
        triager_fn=triager,
        trace_fn=_no_trace,
        memory_store=store,
        spec_id=SPEC_ID,
        run_id=RUN,
    ))

    assert calls == [new_command]
    assert env["evidence"]["terminal_reason"] == "space-exhausted"
    assert env["evidence"]["variant_specs"][0]["spec"]["rationale"] == "resumed"
    assert store.read_resume(SPEC_ID, RUN) == {}


def test_a_cancelled_pod_keeps_a_resume_cursor_and_writes_no_export(tmp_path):
    store = PodMemoryStore(tmp_path / "pod")

    async def hung(spec, messages, tool_calls):
        await asyncio.sleep(30)

    with pytest.raises(asyncio.TimeoutError):
        _run(asyncio.wait_for(
            arun_pod(
                VALID_SPEC,
                exec_fn=_exec(_OK),
                runner_step_fn=hung,
                trace_fn=_no_trace,
                memory_store=store,
                spec_id=SPEC_ID,
                run_id=RUN,
                timeouts=PodTimeouts(
                    node_idle_s=None, node_run_s=None,
                    tool_idle_s=None, tool_run_s=None,
                ),
            ),
            timeout=0.05,
        ))

    assert store.read_pod_export(SPEC_ID, RUN) == {}
    cursor = store.read_resume(SPEC_ID, RUN)
    assert cursor["current_variant_ref"] == "v0"
    assert cursor["executed"] == []
