"""Unit tier: T7 (#157) - the PRODUCTION ReAct seams and the graph's production
lane (D84-14/16/17/22/23/29).

The production default seams are ONE `create_agent` turn per stretch (runner)
and one note-reading `stateful_turn` (triager). This tier drives them
HERMETICALLY: a bound `bind_pod_session` with the module fallback checkpointer, a
FAKE chat model injected through the `model_factory` seam, a temp-dir
`PodMemoryStore`, and a fake terminal. The graph-level tests prove the
production lane is wired when NO seam is injected: the `tool_exec` node is not
registered (D84-29), the runner's ReAct turn executes and records, and the whole
pod completes through `arun_pod`.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import polymerhus.attack.hunting.pod.graph as graph_mod
from polymerhus.attack.hunting.pod import arun_pod, build_pod_graph
from polymerhus.attack.hunting.pod.agents import (
    default_runner_step_fn,
    default_triager_fn,
)
from polymerhus.attack.hunting.pod.context import ExperimentLog, _dicts_to_lc
from polymerhus.attack.hunting.pod.llm import (
    POD_RUNNER_ROLE,
    PodHarnessContext,
    bind_pod_session,
    pod_harness,
)
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore, canonical_spec_id
from polymerhus.attack.hunting.pod.types import RunnerStep
from polymerhus.recon.domain.types import ExecResult

SPEC = {
    "target_identity": "service:web:soupmarket",
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "testing_pattern": "blind-boolean",
    "assumptions": ["network egress allowed"],
    "payload_vector_space": {"method": "GET", "path": "/"},
    "rationale": "reachability",
}

_OK = "<html>market</html>\n__POD_HTTP_STATUS__:200\n__POD_HTTP_TIME__:0.05"
_ABSENT = "not found\n__POD_HTTP_STATUS__:404\n__POD_HTTP_TIME__:0.02"


class _FakeModel(BaseChatModel):
    replies: list = []
    idx: dict = {}

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        i = self.idx.get("i", 0)
        self.idx["i"] = i + 1
        return ChatResult(generations=[ChatGeneration(
            message=self.replies[min(i, len(self.replies) - 1)])])

    @property
    def _llm_type(self):
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def _factory(replies):
    def make(role_id):
        return _FakeModel(replies=list(replies), idx={})
    return make


REACT_EXEC_AND_CONCLUDE = [
    AIMessage(content="", tool_calls=[
        {"name": "exec", "args": {"command": "curl -k -sS https://t/"}, "id": "c1"}]),
    AIMessage(content="stretch concluded; hand the observation to the critic"),
]


def _exec(stdout=_OK, returncode=0, calls=None):
    def fake(command, timeout_s):
        if calls is not None:
            calls.append(command)
        return ExecResult(stdout=stdout, stderr="", returncode=returncode, duration_ms=1)
    return fake


def _run(coro):
    return asyncio.run(coro)


def _no_trace(_run_id):
    return []


def _drive_runner(spec, hc, delta="lap 1 opener"):
    async def _drive():
        with bind_pod_session("run-x", "", spec, role_id=POD_RUNNER_ROLE, harness=hc):
            return await default_runner_step_fn(spec, _dicts_to_lc(
                [{"role": "human", "content": delta}]), 0)
    return _drive()


# --- the production Runner seam: ONE ReAct turn per stretch --------------------

def test_runner_turn_performs_one_react_stretch_and_synthesizes_conclude(tmp_path):
    calls = []
    log = ExperimentLog()
    store = PodMemoryStore(tmp_path)
    spec_id = canonical_spec_id(SPEC)
    hc = PodHarnessContext(exec_fn=_exec(_OK, calls=calls), kb_fn=None,
                           memory_store=store, spec_id=spec_id, log=log,
                           variant_ref="v0", model_factory=_factory(REACT_EXEC_AND_CONCLUDE))
    step = _run(_drive_runner(SPEC, hc))
    assert isinstance(step, RunnerStep)
    assert step.action == "conclude"                  # the graph routes on this
    assert step.exhausted is False                    # one raw observation recorded
    assert "critic" in step.observation_note
    assert len(calls) == 1
    assert len(log.raw_observations) == 1             # G4: recorded raw through ReAct
    assert log.raw_observations[0].probe_ref == log.executed[0]


def test_runner_turn_flags_an_empty_stretch_as_exhausted(tmp_path):
    # The runner concludes WITHOUT executing anything: the old empty-probe rule.
    log = ExperimentLog()
    store = PodMemoryStore(tmp_path)
    spec_id = canonical_spec_id(SPEC)
    hc = PodHarnessContext(exec_fn=_exec(_OK), kb_fn=None, memory_store=store,
                           spec_id=spec_id, log=log, variant_ref="v0",
                           model_factory=_factory([AIMessage(content="nothing to probe")]))
    step = _run(_drive_runner(SPEC, hc))
    assert step.action == "conclude"
    assert step.exhausted is True
    assert len(log.raw_observations) == 0


def test_runner_turn_binds_note_and_kb_on_the_same_agent(tmp_path):
    """D84-16/27: the runner's ONE turn binds exec + kb_retrieve + note - the KB
    wiring hole and the P3 note tool ride the SAME create_agent loop; the P3 note
    write is the runner's FINAL tool call (D84-17/19)."""
    calls = []
    log = ExperimentLog()
    store = PodMemoryStore(tmp_path)
    spec_id = canonical_spec_id(SPEC)
    replies = [
        AIMessage(content="", tool_calls=[
            {"name": "kb_retrieve", "args": {"query": "csrf on search"}, "id": "c1"}]),
        AIMessage(content="", tool_calls=[
            {"name": "note", "args": {"operation": "write", "variant_ref": "v0",
                                      "note_name": "experiment",
                                      "kind": "experiment_summary",
                                      "body": "the consolidated summary"},
             "id": "c2"}]),
        AIMessage(content="space exhausted; summary note written"),
    ]
    hc = PodHarnessContext(exec_fn=_exec(_OK, calls=calls), kb_fn=None,
                           memory_store=store, spec_id=spec_id, log=log,
                           variant_ref="v0", model_factory=_factory(replies))
    step = _run(_drive_runner(SPEC, hc))
    assert step.action == "conclude"
    notes = store.read_notes(spec_id)
    assert notes, "the runner's P3 note write must persist"
    assert notes[0]["kind"] == "experiment_summary"
    assert notes[0]["body"] == "the consolidated summary"


def test_runner_turn_hard_fails_without_a_bound_session():
    with pytest.raises(RuntimeError):
        _run(default_runner_step_fn(SPEC, [], 0))


def test_production_seams_are_async():
    assert inspect.iscoroutinefunction(default_runner_step_fn)
    assert inspect.iscoroutinefunction(default_triager_fn)


# --- the production Triager seam: note-reading stateful_turn -------------------

def _drive_triager(spec, hc, log):
    async def _drive():
        with bind_pod_session("run-x", "", spec, role_id="pod_triager", harness=hc):
            # The graph passes the composed delta as DICT views (the seam's
            # boundary conversion is `_dicts_to_lc`) - mirror that here.
            return await default_triager_fn(spec, None,
                                            [{"role": "human",
                                              "content": "triager delta"}], log)
    return _drive()


def test_triager_seam_reads_the_note_and_returns_a_decision(tmp_path):
    log = ExperimentLog()
    store = PodMemoryStore(tmp_path)
    spec_id = canonical_spec_id(SPEC)
    store.append(spec_id, variant_ref="v0", note_name="experiment",
                 kind="experiment_summary", body="the verbatim consolidation")
    hc = PodHarnessContext(exec_fn=_exec(_OK), kb_fn=None, memory_store=store,
                           spec_id=spec_id, log=log, variant_ref="v0",
                           model_factory=_factory([AIMessage(content="", tool_calls=[
                               {"name": "TriagerDecision", "id": "c1", "args": {
                                   "classification": "symptom-absent",
                                   "action": "terminate", "verdict": "unsuccessful",
                                   "terminal_reason": "space-exhausted", "clean": True,
                                   "note": "third-party miner verdict"}}])]))
    decision = _run(_drive_triager(SPEC, hc, log))
    assert decision["action"] == "terminate"
    assert decision["terminal_reason"] == "space-exhausted"
    assert decision["clean"] is True
    assert "third-party miner verdict" in decision["note"]


def test_triager_seam_degrades_to_a_safe_terminal_on_failure(tmp_path):
    log = ExperimentLog()
    store = PodMemoryStore(tmp_path)
    spec_id = canonical_spec_id(SPEC)

    def raising(role_id):
        raise RuntimeError("no model")

    hc = PodHarnessContext(exec_fn=_exec(_OK), kb_fn=None, memory_store=store,
                           spec_id=spec_id, log=log, variant_ref="v0",
                           model_factory=raising)
    decision = _run(_drive_triager(SPEC, hc, log))
    assert decision["action"] == "terminate"
    assert decision["verdict"] == "unsuccessful"
    assert "degraded" in decision["note"]


# --- the graph's production lane (D84-29) --------------------------------------

def test_production_graph_has_no_tool_exec_node(monkeypatch):
    """D84-29: with no runner seam injected, the tool loop lives inside
    `create_agent` - the compiled production graph carries NO `tool_exec` node,
    while the contract-tier graph (injected seam) still does."""
    prod = build_pod_graph(exec_fn=_exec(_OK), memory_store=None)
    contract = build_pod_graph(exec_fn=_exec(_OK), memory_store=None,
                               runner_step_fn=lambda s, m, t: RunnerStep(
                                   action="conclude", exhausted=True))
    prod_nodes = set(prod.get_graph().nodes)
    contract_nodes = set(contract.get_graph().nodes)
    assert "tool_exec" not in prod_nodes
    assert "tool_exec" in contract_nodes


def test_full_production_pod_lands_symptom_confirmed_with_fake_models(tmp_path):
    """The strongest hermetic proof: `arun_pod` with NO seam injected drives the
    production lanes - the runner ReAct turn (exec + conclude), the symbolic
    fast-path, the envelope - with the fake model factory standing in for the
    live model."""
    env = _run(arun_pod(
        SPEC, exec_fn=_exec(_OK), trace_fn=_no_trace,
        memory_store=PodMemoryStore(tmp_path),
        model_factory=_factory(REACT_EXEC_AND_CONCLUDE)))
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"
    assert len(env["evidence"]["raw_observations"]) == 1
    assert env["evidence"]["iterations"] == 1


def test_production_pod_degrades_to_a_safe_terminal_without_model_env(tmp_path,
                                                                      monkeypatch):
    """D84-14: a direct pod run with NO model env configured hard-fails at the
    stateful seam and `arun_pod` degrades the run - never a silent symbolic
    fallback, never a raise into the caller."""
    monkeypatch.delenv("LLM_MODEL_POD_RUNNER", raising=False)
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    env = _run(arun_pod(SPEC, exec_fn=_exec(_OK), trace_fn=_no_trace,
                        memory_store=PodMemoryStore(tmp_path)))
    assert env["verdict"] == "unsuccessful"


def test_production_runner_node_binds_the_harness_context(monkeypatch, tmp_path):
    """The graph's production runner node binds the run-scoped harness around the
    default seam call (spied by patching `graph.default_runner_step_fn`) - the
    memory key rides the ROOT spec id, the variant_ref the current stretch."""
    seen = []
    root_spec = {"target_identity": "svc",
                 "verification_symptoms": ["reflects the marker"],
                 "testing_pattern": "blind-boolean",
                 "payload_vector_space": {"method": "GET"}}

    async def spy(spec, messages, tool_calls):
        seen.append(pod_harness())
        return RunnerStep(action="conclude", exhausted=True,
                          observation_note="empty stretch")

    monkeypatch.setattr(graph_mod, "default_runner_step_fn", spy)
    env = _run(arun_pod(root_spec, exec_fn=_exec(_ABSENT), trace_fn=_no_trace,
                        memory_store=PodMemoryStore(tmp_path)))
    assert env["verdict"] == "unsuccessful"
    assert seen and seen[0] is not None
    assert seen[0].spec_id == canonical_spec_id(root_spec)   # root spec keys the memory
    assert seen[0].variant_ref == "v0"
    assert seen[0].log is not None