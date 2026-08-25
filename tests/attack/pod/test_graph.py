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

from polymerhus.attack.hunting.llm import hunt_session
from polymerhus.attack.hunting.pod import arun_pod
from polymerhus.attack.hunting.pod.agents import symbolic_runner_step_fn
from polymerhus.attack.hunting.pod.context import canonical_spec_hash
from polymerhus.attack.hunting.pod.llm import (
    POD_DEFAULT_RUN_ID,
    POD_RUNNER_ROLE,
    POD_TRIAGER_ROLE,
    pod_session,
)
from polymerhus.attack.hunting.pod.types import RunnerStep
from polymerhus.recon.domain.types import ExecResult

from polymerhus.attack.hunting.pod.pod_memory import spec_identifier

# The #164 `<fault>_<strategy>` spec id (D84-34), the pod memory store key (T7).
SPEC_ID = spec_identifier("sqli", "blind")


def _terminate_space(spec, obs, messages, log):
    """A triager that ends a semantic (non-symbolic) stretch space-exhausted."""
    return {"action": "terminate", "verdict": "unsuccessful",
            "terminal_reason": "space-exhausted", "clean": True}


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
    """D84-15: an ASYNC runner and ASYNC terminal are awaited in-graph (the
    `_await_seam` `iscoroutinefunction` branch), not to_thread-ed - the async
    production path the sync fakes below only approximate."""
    async def runner(spec, messages, tool_calls):
        return symbolic_runner_step_fn(spec, messages, tool_calls)

    async def exec_fn(command, timeout_s):
        return ExecResult(stdout=_OK, stderr="", returncode=0, duration_ms=1)

    env = _run(arun_pod(VALID_SPEC, exec_fn=exec_fn, runner_step_fn=runner,
                        triager_fn=None, trace_fn=_no_trace))
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"


def test_init_rejection_makes_no_tool_call():
    calls = []
    env = _run(arun_pod({"target_identity": "", "verification_symptoms": [],
                         "testing_pattern": "", "payload_vector_space": {}},
                        exec_fn=_exec(_OK, calls=calls),
                        runner_step_fn=symbolic_runner_step_fn, triager_fn=None,
                        trace_fn=_no_trace))
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert env["evidence"]["init_validation"]
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
        triager_fn=None, trace_fn=_no_trace, memory_store=PodMemoryStore(project_id="p1")))
    assert env["verdict"] == "unsuccessful"
    assert "spec_id" in (env["evidence"].get("error") or "")


def test_symbolic_symptom_confirmed_needs_no_triager():
    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=None, trace_fn=_no_trace))
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

    def triager(spec, obs, messages, log):
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

    def triager(spec, obs, messages, log):
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    _run(arun_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                  exec_fn=_exec(_OK), runner_step_fn=runner, triager_fn=triager,
                  trace_fn=_no_trace))
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

    env = _run(arun_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                        exec_fn=_exec(_ABSENT), runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=triager, trace_fn=_no_trace))
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

    env = _run(arun_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                        exec_fn=_exec(_ABSENT), runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=triager, trace_fn=_no_trace))
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

    _run(arun_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                  exec_fn=_exec(_ABSENT, calls=calls), runner_step_fn=_scripted(steps),
                  triager_fn=triager, trace_fn=_no_trace))
    assert len(calls) == 1                           # O7/C10: executed once


def test_runner_infeasible_is_an_init_gate_with_evidence():
    steps = [RunnerStep(action="conclude", infeasible=True,
                        unverified=["no WAF on /api/a could not be confirmed"])]
    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=_scripted(steps),
                        triager_fn=None, trace_fn=_no_trace))
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert any("WAF" in v for v in env["evidence"]["init_validation"])


def test_clean_false_when_triager_reports_defence():
    def triager(spec, obs, messages, log):
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
    """D84-7: inside a parent `hunt_session`, the `runner_agent` node binds the
    pod_runner role's typed `HuntSession` - the parent's run_id/hunt_id + the
    canonical spec hash - around the seam call, so the default seam receives the
    typed address (this spy reads the ContextVar like the default seam does; the
    sync spy rides `asyncio.to_thread` via `_await_seam`, whose context copy
    carries the binding)."""
    seen = []

    def runner(spec, messages, tool_calls):
        seen.append(pod_session())
        return symbolic_runner_step_fn(spec, messages, tool_calls)

    with hunt_session("run-1", "hunt-A"):
        env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=runner,
                            triager_fn=None, trace_fn=_no_trace))

    assert env["verdict"] == "successful"
    ctx = seen[0]
    assert ctx is not None
    assert ctx.address.role_id == POD_RUNNER_ROLE
    assert ctx.address.run_id == "run-1"
    assert ctx.address.hunt_id == "hunt-A"
    assert ctx.address.spec == canonical_spec_hash(VALID_SPEC)


def test_runner_seam_sees_a_task_local_default_outside_a_hunt():
    """Without a parent hunt_session the graph still runs (fail-open): the seam
    sees the task-local default session - the pod's run_id and an empty hunt_id
    (an empty discriminator is dropped from the address, never shifting it)."""
    seen = []

    def runner(spec, messages, tool_calls):
        seen.append(pod_session())
        return symbolic_runner_step_fn(spec, messages, tool_calls)

    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=runner,
                        triager_fn=None, trace_fn=_no_trace))

    assert env["verdict"] == "successful"
    ctx = seen[0]
    assert ctx is not None
    assert ctx.address.role_id == POD_RUNNER_ROLE
    assert ctx.address.run_id == POD_DEFAULT_RUN_ID
    assert ctx.address.hunt_id == ""


def test_triager_seam_observes_pod_triager_session_inside_a_hunt():
    """The `triager` node binds the pod_triager role's `HuntSession` when its
    seam is consulted (the symbolic fast-path stays silent for a semantic
    symptom), again deriving the instance from the parent hunt."""
    spec = {**VALID_SPEC, "verification_symptoms": ["reflects the marker"]}
    seen = []

    def triager(s, obs, messages, log):
        seen.append(pod_session())
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    with hunt_session("run-1", "hunt-A"):
        env = _run(arun_pod(spec, exec_fn=_exec(_ABSENT), runner_step_fn=symbolic_runner_step_fn,
                            triager_fn=triager, trace_fn=_no_trace))

    assert env["verdict"] == "unsuccessful"
    ctx = seen[0]
    assert ctx is not None
    assert ctx.address.role_id == POD_TRIAGER_ROLE
    assert ctx.address.run_id == "run-1"
    assert ctx.address.hunt_id == "hunt-A"
    assert ctx.address.spec == canonical_spec_hash(spec)


# --- T6 (#156): BaseMessage + add_messages channels (D84-4) -------------------

def test_runner_channel_accumulates_appended_messages_in_order():
    """D84-4: the message channels are `Annotated[list[BaseMessage],
    add_messages]` - every node deposits ONLY its turn's new messages and the
    reducer appends them onto the channel, so the agentic loop's turns
    ACCUMULATE (order preserved, types intact) instead of replacing the channel
    wholesale."""
    from langchain_core.messages import BaseMessage

    from polymerhus.attack.hunting.pod.agents import RUNNER_SYSTEM, TRIAGER_SYSTEM
    from polymerhus.attack.hunting.pod.graph import build_pod_graph

    steps = iter([
        RunnerStep(action="tool_call", tool="exec", command="curl -k -sS https://t/"),
        RunnerStep(action="conclude", observation_note="chain done"),
    ])

    def runner(spec, messages, tool_calls):
        return next(steps)

    def triager(spec, obs, messages, log):
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    graph = build_pod_graph(exec_fn=_exec(_ABSENT), runner_step_fn=runner,
                            triager_fn=triager)
    final = _run(graph.ainvoke({"spec": dict(VALID_SPEC)}))

    msgs = final["runner_messages"]
    assert all(isinstance(m, BaseMessage) for m in msgs)     # the typed channel
    assert [m.type for m in msgs] == ["system", "human", "ai", "human", "ai"]
    assert msgs[0].content == RUNNER_SYSTEM                  # the system prompt
    assert "action: tool_call" in msgs[2].content            # turn 1's proposal
    assert "TOOL RESULT" in msgs[3].content                  # the recorded observation
    assert "action: conclude" in msgs[4].content             # turn 2: appended, not replaced

    tmsgs = final["triager_messages"]                        # the critic's own channel
    assert [m.type for m in tmsgs] == ["system", "human", "ai"]
    assert tmsgs[0].content == TRIAGER_SYSTEM
    assert "terminate" in tmsgs[2].content


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

    def triager(spec, obs, messages, log):
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
    into the seams."""
    runner_views, triager_views = [], []

    def runner(spec, messages, tool_calls):
        runner_views.append(list(messages))
        return symbolic_runner_step_fn(spec, messages, tool_calls)

    def triager(spec, obs, messages, log):
        assert all(isinstance(m, dict) for m in messages)
        triager_views.append(list(messages))
        return {"action": "terminate", "verdict": "unsuccessful",
                "terminal_reason": "space-exhausted", "clean": True}

    env = _run(arun_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                        exec_fn=_exec(_ABSENT), runner_step_fn=runner,
                        triager_fn=triager, trace_fn=_no_trace))
    assert env["verdict"] == "unsuccessful"
    assert runner_views and triager_views
    for view in runner_views[0]:
        assert "role" in view and "content" in view
        assert view["role"] in ("system", "human", "ai", "tool")
    assert triager_views[0][0]["role"] == "system"     # the critic sees its own system prompt
    assert all("role" in v and "content" in v for v in triager_views[0])


# --- T7 (#183): the pod owns the persistence of its OWN terminal result ---------

def test_terminal_export_persists_to_spec_run_id(tmp_path):
    """T7 (GP1/GP3/GP4): a completed run with a bound store + spec_id persists
    its `PodExport` envelope to `<spec_id>/<run_id>.yaml` - the persisted record
    EQUALS the returned envelope (`env["evidence"]` round-trips), written by the
    deterministic terminal node."""
    from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore

    store = PodMemoryStore(tmp_path)
    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=None, trace_fn=_no_trace, memory_store=store,
                        spec_id=SPEC_ID, run_id="run-42"))
    assert env["verdict"] == "successful"
    persisted = store.read_pod_export(SPEC_ID, "run-42")
    assert persisted == env                       # the persisted record == the returned envelope


def test_export_rerun_overwrites_the_same_file(tmp_path):
    """GP1/D84-37: a re-run of the same spec with the SAME run_id overwrites the
    same `<spec_id>/<run_id>.yaml` - the deterministic path is the address."""
    from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore

    store = PodMemoryStore(tmp_path)
    env1 = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=symbolic_runner_step_fn,
                         triager_fn=None, trace_fn=_no_trace, memory_store=store,
                         spec_id=SPEC_ID, run_id="run-1"))
    env2 = _run(arun_pod({**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
                         exec_fn=_exec(_ABSENT), runner_step_fn=symbolic_runner_step_fn,
                         triager_fn=_terminate_space, trace_fn=_no_trace,
                         memory_store=store, spec_id=SPEC_ID, run_id="run-1"))
    assert env1["verdict"] == "successful"
    assert env2["verdict"] == "unsuccessful"
    assert store.read_pod_export(SPEC_ID, "run-1") == env2
    assert store.list_pod_exports(SPEC_ID) == ["run-1"]   # one file, overwritten


def test_export_write_failure_degrades_to_the_envelope(tmp_path):
    """O3/IA-4 fail-open: a write failure degrades to the in-memory envelope -
    the run STILL returns it to the parent and never raises."""
    from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore

    class _FailingStore(PodMemoryStore):
        def write_pod_export(self, spec_id, run_id, export_dict):
            raise OSError("boom")

    store = _FailingStore(tmp_path)
    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=None, trace_fn=_no_trace, memory_store=store,
                        spec_id=SPEC_ID, run_id="run-42"))
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"
