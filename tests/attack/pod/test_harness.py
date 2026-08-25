"""Unit tier: T7 (#157) - the ReAct-loop harness middleware (D84-22).

G1 (the per-stretch tool-call cap `HUNT_POD_MAX_TOOL_CALLS`), G4 (every exec
result recorded RAW in the D6 log) and O7 (one execution per identical probe)
move off the graph's `tool_exec` node and onto the `create_agent` agent. This
tier runs a REAL `create_agent` loop on a FAKE chat model with the pod's bound
tools + harness, and asserts the loop is bounded, deduped, and honest. No live
LLM, no live target.
"""
from __future__ import annotations

import asyncio

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.attack.hunting.pod.context import ExperimentLog
from polymerhus.attack.hunting.pod.harness import build_harness_middleware
from polymerhus.attack.hunting.pod.tools import ExecTool
from polymerhus.recon.domain.types import ExecResult

_OK = "<html>market</html>\n__POD_HTTP_STATUS__:200\n__POD_HTTP_TIME__:0.05"


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


def _exec(stdout=_OK, calls=None):
    def fake(command, timeout_s):
        if calls is not None:
            calls.append(command)
        return ExecResult(stdout=stdout, stderr="", returncode=0, duration_ms=1)
    return fake


def _run_loop(model_replies, tools, middleware, saver=None, thread="t"):
    model = _FakeModel(replies=model_replies)
    agent = create_agent(model, tools=tools, middleware=middleware,
                         checkpointer=saver or InMemorySaver())
    return agent.invoke({"messages": [HumanMessage(content="go")]},
                        {"configurable": {"thread_id": thread}})


def _exec_tool_call(command, cid):
    return AIMessage(content="", tool_calls=[{"name": "exec", "args": {"command": command},
                                              "id": cid}])


# --- G4: every exec result is recorded RAW ------------------------------------

def test_harness_loop_records_raw_observations():
    calls = []
    log = ExperimentLog()
    harness = build_harness_middleware(log=log, variant_ref="v0", cap=10)
    tool = ExecTool(exec_fn=_exec(_OK, calls=calls), log=log, variant_ref="v0")
    _run_loop([
        _exec_tool_call("curl -k -sS https://t/root", "c1"),
        AIMessage(content="concluded"),
    ], [tool], [harness])
    assert len(calls) == 1
    assert len(log.raw_observations) == 1            # G4: the raw result is on the D6 trail
    obs = log.raw_observations[0]
    assert obs.status == 200
    assert obs.variant_ref == "v0"
    assert log.executed == [obs.probe_ref]           # O7 mark


def test_harness_records_multiple_parallel_calls_in_one_message():
    log = ExperimentLog()
    harness = build_harness_middleware(log=log, variant_ref="v0", cap=10)
    tool = ExecTool(exec_fn=_exec(_OK), log=log, variant_ref="v0")
    _run_loop([
        AIMessage(content="", tool_calls=[
            {"name": "exec", "args": {"command": "curl -k -sS /a"}, "id": "c1"},
            {"name": "exec", "args": {"command": "curl -k -sS /b"}, "id": "c2"},
        ]),
        AIMessage(content="done"),
    ], [tool], [harness])
    assert len(log.raw_observations) == 2
    assert len({o.probe_ref for o in log.raw_observations}) == 2


# --- O7: one execution per identical probe -------------------------------------

def test_harness_dedupes_an_identical_repeat():
    calls = []
    log = ExperimentLog()
    harness = build_harness_middleware(log=log, variant_ref="v0", cap=10)
    tool = ExecTool(exec_fn=_exec(_OK, calls=calls), log=log, variant_ref="v0")
    result = _run_loop([
        _exec_tool_call("curl -k -sS https://t/", "c1"),
        _exec_tool_call("curl -k -sS https://t/", "c2"),   # identical repeat
        AIMessage(content="done"),
    ], [tool], [harness])
    assert len(calls) == 1                               # O7: executed exactly once
    assert len(log.raw_observations) == 1
    texts = " ".join(str(getattr(m, "content", "")) for m in result["messages"])
    assert "already executed; deduped" in texts          # the harness gate landed
    # The dedup gate still counts toward the cap (the old G1 "count every call").
    assert harness.calls == 2


def test_harness_scope_is_per_variant():
    calls = []
    # A prior variant executed the SAME command; the O7 signature is
    # variant-scoped (the variant is in the hash), so v1 does NOT inherit it.
    prior = ExperimentLog()
    ExecTool(exec_fn=_exec(_OK), log=prior, variant_ref="v0").invoke(
        {"command": "curl -k -sS https://t/"})
    log1 = ExperimentLog()
    harness = build_harness_middleware(log=log1, variant_ref="v1", cap=10)
    tool = ExecTool(exec_fn=_exec(_OK, calls=calls), log=log1, variant_ref="v1")
    _run_loop([
        _exec_tool_call("curl -k -sS https://t/", "c1"),
        _exec_tool_call("curl -k -sS https://t/", "c2"),
        AIMessage(content="done"),
    ], [tool], [harness])
    # v0's execution never leaks into v1's scope: the first v1 call ran, the
    # second identical v1 call deduped within the variant.
    assert calls == ["curl -k -sS https://t/"]
    assert len(log1.raw_observations) == 1


# --- G1: the per-stretch cap ends the loop -------------------------------------

def test_harness_cap_ends_the_react_loop():
    calls = []
    log = ExperimentLog()
    harness = build_harness_middleware(log=log, variant_ref="v0", cap=2)
    tool = ExecTool(exec_fn=_exec(_OK, calls=calls), log=log, variant_ref="v0")
    result = _run_loop([
        _exec_tool_call("curl -k -sS /1", "c1"),
        _exec_tool_call("curl -k -sS /2", "c2"),
        _exec_tool_call("curl -k -sS /3", "c3"),   # beyond the cap
        AIMessage(content="never reached"),
    ], [tool], [harness])
    assert len(calls) == 2                             # G1: bounded at the cap
    assert len(log.raw_observations) == 2
    assert harness.calls >= 2


def test_harness_default_cap_is_the_d84_22_value(monkeypatch):
    import importlib

    import polymerhus.attack.hunting.pod.config as cfg

    monkeypatch.delenv("HUNT_POD_MAX_TOOL_CALLS", raising=False)
    cfg = importlib.reload(cfg)
    assert cfg.HUNT_POD_MAX_TOOL_CALLS == 200


# --- G2: a malformed exec is rejected, not run ----------------------------------

def test_harness_rejects_an_empty_command():
    calls = []
    log = ExperimentLog()
    harness = build_harness_middleware(log=log, variant_ref="v0", cap=10)
    tool = ExecTool(exec_fn=_exec(_OK, calls=calls), log=log, variant_ref="v0")
    result = _run_loop([
        AIMessage(content="", tool_calls=[{"name": "exec", "args": {"command": "   "},
                                           "id": "c1"}]),
        AIMessage(content="done"),
    ], [tool], [harness])
    assert calls == []                                 # G2: not executed
    assert len(log.raw_observations) == 0
    texts = " ".join(str(getattr(m, "content", "")) for m in result["messages"])
    assert "empty command rejected" in texts


def test_harness_does_not_replace_the_tool_contract_validation():
    """D84-22: the harness never re-validates tool args - a wrong parameter is
    the TOOL's own `extra="forbid"` contract (the harness passes the call
    through; pydantic rejects it)."""
    calls = []
    log = ExperimentLog()
    harness = build_harness_middleware(log=log, variant_ref="v0", cap=10)
    tool = ExecTool(exec_fn=_exec(_OK, calls=calls), log=log, variant_ref="v0")
    result = _run_loop([
        AIMessage(content="", tool_calls=[{"name": "exec", "id": "c1",
                                           "args": {"command": "/x", "bogus": 1}}]),
        AIMessage(content="done"),
    ], [tool], [harness])
    texts = " ".join(str(getattr(m, "content", "")) for m in result["messages"])
    assert "Extra inputs are not permitted" in texts  # the tool-contract rejection
    assert calls == []


# --- the harness is inert for non-exec tools ------------------------------------

def test_harness_is_a_pass_through_for_non_exec_tools():
    """The harness gates only the exec tool; note calls flow to their own
    handlers (their contract rejection still happens at the args schema)."""
    from polymerhus.attack.hunting.pod.note_tool import PodNoteTool
    from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore

    store = PodMemoryStore("/tmp/__ph_tmp__")
    log = ExperimentLog()
    harness = build_harness_middleware(log=log, variant_ref="v0", cap=10)
    tools = [PodNoteTool(store=store, spec_id="h")]
    result = _run_loop([
        AIMessage(content="", tool_calls=[
            {"name": "note", "args": {"operation": "read", "variant_ref": "v0",
                                       "note_name": "n"}, "id": "c1"}]),
        AIMessage(content="done"),
    ], tools, [harness])
    texts = " ".join(str(getattr(m, "content", "")) for m in result["messages"])
    assert harness.calls == 1