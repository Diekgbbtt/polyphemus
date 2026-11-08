"""A stage-aware scripted chat model for the staged triage tree.

The production staged triager runs up to four structured `stateful_turn`s on the
SAME `pod_triager` role: `TriageDecision`, `DivergenceDecision`,
`TriagerDecision`, and `TerminalDecision`. A role-keyed fake model cannot tell
the stages apart, because the role is identical; the bound schema tool name is
the discriminator.

`StagedTriagerFake.bind_tools` records the bound tool names (the structured
output negotiation binds the schema as a tool on the ToolStrategy rung), and
`_generate` picks the reply script for the schema. A fresh instance is built per
turn by the model factory, so each turn starts at its own script index.
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


class StagedTriagerFake(BaseChatModel):
    """Replay the reply script for the currently bound structured schema."""

    by_schema: dict = Field(default_factory=dict)
    default: list = Field(default_factory=list)
    idx: dict = Field(default_factory=dict)
    bound: list = Field(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        script = None
        for name in reversed(self.bound):
            if name in self.by_schema:
                script = self.by_schema[name]
                break
        if not script:
            script = self.default or [AIMessage(content="done")]
        i = self.idx.get("i", 0)
        self.idx["i"] = i + 1
        return ChatResult(generations=[ChatGeneration(
            message=script[min(i, len(script) - 1)])])

    @property
    def _llm_type(self):
        return "staged-triager-fake"

    def bind_tools(self, tools, **kwargs):
        self.bound = [getattr(t, "name", "") for t in tools if t is not None]
        return self


def decision_call(name: str, args: dict, call_id: str = "c9") -> AIMessage:
    """One structured-output tool call for the named schema."""
    return AIMessage(content="", tool_calls=[
        {"name": name, "id": call_id, "args": args}])


def triage_reply(*, runner_failed: bool = False, symptom_confirmed: bool = False,
                 clean: bool = False, note: str = "") -> list:
    return [decision_call("TriageDecision", {
        "runner_failed": runner_failed, "symptom_confirmed": symptom_confirmed,
        "clean": clean, "note": note})]


def divergence_reply(*, runner_diverged: bool = False, note: str = "") -> list:
    return [decision_call("DivergenceDecision", {
        "runner_diverged": runner_diverged, "note": note})]


def terminal_reply(*, verdict: str = "unsuccessful",
                   terminal_reason: str = "no-symptom-evidence",
                   clean: bool = False, note: str = "") -> list:
    return [decision_call("TerminalDecision", {
        "verdict": verdict, "terminal_reason": terminal_reason,
        "clean": clean, "note": note})]
