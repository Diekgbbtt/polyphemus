"""Contract tier: the pod triage lane's cache shape (lifecycle v2, slice 9).

The provider caches a token prefix from position 0, so the triage lane's
requests must be strict prefix extensions: one byte-identical system prompt on
every step, one identical ordered tool-definition list, append-only messages,
the bound-skill listing in the first human packet, and no SystemMessage in the
message lists. The test drives a scripted pod lifecycle through `arun_pod` with
a spy on `arun_session_turn`, so the REQUESTS are observed verbatim.
"""
from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import BaseMessage

from polymerhus.attack.hunting.pod import arun_pod
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore, spec_identifier
from polymerhus.attack.hunting.pod.prompts import load_pod_triager_contract
from polymerhus.recon.domain.types import ExecResult

SPEC_ID = spec_identifier("sqli", [{"axis": "technique", "value": "blind"},
                                   {"axis": "payload-vector", "value": "boolean"}])

_ABSENT = "not found\n__POD_HTTP_STATUS__:404\n__POD_HTTP_TIME__:0.02"
_OK = "<html>market</html>\n__POD_HTTP_STATUS__:200\n__POD_HTTP_TIME__:0.05"

RUNNER_SCRIPT = [
    __import__("langchain_core.messages", fromlist=["AIMessage"]).AIMessage(
        content="", tool_calls=[
            {"name": "exec", "args": {"command": "curl -k -sS https://t/"}, "id": "c1"}]),
    __import__("langchain_core.messages", fromlist=["AIMessage"]).AIMessage(
        content="stretch concluded"),
]

TRIAGE_SCRIPT = [
    __import__("langchain_core.messages", fromlist=["AIMessage"]).AIMessage(
        content="", tool_calls=[
            {"name": "submit_assessment", "args": {"symptom_confirmed": False,
                                                   "runner_diverged": False,
                                                   "clean": True,
                                                   "note": "no confirmation"},
             "id": "a1"}]),
    __import__("langchain_core.messages", fromlist=["AIMessage"]).AIMessage(
        content="", tool_calls=[
            {"name": "submit_decision", "args": {"action": "terminate",
                                                 "verdict": "unsuccessful",
                                                 "terminal_reason": "space-exhausted",
                                                 "note": "space covered"},
             "id": "a2"}]),
    __import__("langchain_core.messages", fromlist=["AIMessage"]).AIMessage(
        content="the decision is submitted"),
]


class _CursorFactory:
    """A role-aware model factory with a shared per-role cursor (the pod builds
    a fresh model per turn) whose replies carry unique ids, mirroring a real
    provider."""

    def __init__(self):
        self.cursor = {"pod_runner": 0, "pod_triager": 0}
        self.scripts = {}

    def set(self, role_id, replies):
        self.scripts[role_id] = list(replies)

    def __call__(self, role_id):
        import uuid

        from langchain_core.language_models import BaseChatModel
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult

        script = self.scripts.get(role_id, [])
        i = self.cursor.get(role_id, 0)
        self.cursor[role_id] = i + 1

        class _Model(BaseChatModel):
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                msg = script[min(i, len(script) - 1)] if script else AIMessage(
                    content="done")
                msg = msg.model_copy(
                    deep=True, update={"id": f"m-{i}-{uuid.uuid4().hex}"})
                return ChatResult(generations=[ChatGeneration(message=msg)])

            @property
            def _llm_type(self):
                return "fake"

            def bind_tools(self, tools, **kwargs):
                return self

        return _Model()


@pytest.fixture()
def spy(monkeypatch):
    import polymerhus.app.llm.session as S

    seen: list[dict] = []
    original = S.arun_session_turn

    async def spy_turn(role_id, thread_id, new_messages, **kwargs):
        seen.append({"role": role_id, "thread": str(thread_id),
                     "messages": list(new_messages), "kwargs": kwargs})
        return await original(role_id, thread_id, new_messages, **kwargs)

    monkeypatch.setattr(S, "arun_session_turn", spy_turn)
    return seen


def test_the_triage_lane_is_a_strict_prefix_extension(spy, tmp_path):
    factory = _CursorFactory()
    factory.set("pod_runner", RUNNER_SCRIPT)
    factory.set("pod_triager", TRIAGE_SCRIPT)

    env = asyncio.run(arun_pod(
        {"target_identity": {"url": "http://svc/", "unit_id": "svc"},
         "verification_symptoms": ["reflects the marker"],
         "assumptions": ["egress"],
         "rationale": "reachability",
         "provenance": {"threat_id": "t", "unit_id": "svc",
                        "canonical_class": "IDOR", "web_vulnerability_class": "idor"}},
        exec_fn=lambda command, timeout_s: ExecResult(
            stdout=_ABSENT, stderr="", returncode=0, duration_ms=1),
        trace_fn=lambda run_id: [], memory_store=PodMemoryStore(tmp_path),
        spec_id=SPEC_ID + "_cache", project_id="proj-1",
        model_factory=factory))

    assert env["verdict"] == "unsuccessful"
    triage_calls = [c for c in spy if c["role"] == "pod_triager"]
    assert triage_calls, "the triage lane ran"
    # One byte-identical system prompt on every triage step and closing turn.
    prompts = {c["kwargs"]["system_prompt"] for c in triage_calls}
    assert prompts == {load_pod_triager_contract()}
    # One identical ordered tool-definition list on every triage step.
    tool_lists = [tuple(t["function"]["name"] for t in c["kwargs"]["tools"])
                  for c in triage_calls]
    assert len(set(tool_lists)) == 1
    assert tool_lists[0][-2:] == ("submit_assessment", "submit_decision")
    assert "exec" not in tool_lists[0]
    # Append-only requests: every triage request is a TAIL DELTA on its thread.
    # No request ever re-sends the base packet, and no delta ever carries a
    # SystemMessage (the system prompt rides the request's system_prompt).
    messages = [c["messages"] for c in triage_calls]
    for previous, current in zip(messages, messages[1:]):
        assert current, "every request carries a delta"
        assert current[0].content != previous[-1].content, \
            "a repeated tail message would replace in place instead of appending"
    for c in triage_calls:
        for msg in c["messages"]:
            assert isinstance(msg, BaseMessage)
            assert msg.type != "system", "the system prompt never rides messages"
    # The thread's assembled transcript: the first human packet carries the
    # bound-skill listing, and no SystemMessage ever entered the thread.
    from polymerhus.app.llm.checkpoints import get_session_checkpointer
    from polymerhus.app.llm.session import _read_thread_state

    thread = _read_thread_state(get_session_checkpointer(), triage_calls[0]["thread"]) or {}
    thread_messages = thread.get("messages") or []
    assert thread_messages, "the triage thread persisted its transcript"
    assert all(m.type != "system" for m in thread_messages)
    thread_humans = [m for m in thread_messages if m.type == "human"]
    assert thread_humans
    assert "Skills available through the `load_skill` tool" in thread_humans[0].content
