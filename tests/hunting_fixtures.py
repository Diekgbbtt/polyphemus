"""Shared state-graph-hunter fixtures (memory integration + e2e tiers).

The state-graph hunter's seams (spec 5, ADR R4): the per-project
`HunterMemoryStore`, the `hunts_store` / `notes` tool seam over it, and the
turn-by-turn ReAct host's `model_factory` (a scripted model emitting REAL tool
calls - the standard tool interface the harness binds request-only). Owned here
so the memory contract catalogue (C1-C22) and the harness-seam catalogue (H1-H4)
speak the SAME canned objects and the duplication stays in one place.
"""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import PrivateAttr

from polymerhus.attack.hunting.hunt_orchestrator import (
    HuntConfig,
    HuntPromptTemplate,
)
from polymerhus.attack.hunting.hunt_store import semantic_key
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.hunting_agent import build_sync_hunting_agent

PROJECT = "proj-a"
UNIT_ID = "Service:slug:a"
FAULT_CLASS = "fault-x"
VULNERABILITY_CLASS = "csrf"
FAULT_KEY = semantic_key(UNIT_ID, FAULT_CLASS, VULNERABILITY_CLASS)


class _ScriptedFake(BaseChatModel):
    """A one-reply scripted model: either a REAL tool call (name + args, the
    standard tool interface the harness binds request-only) or a plain answer
    (no tool calls -> the model concluded the hunt). Every message list it was
    handed is appended to the shared `seen` list (the hint assertions read the
    tool responses). The `seen` list rides a pydantic `PrivateAttr` so
    construction never copies it."""

    reply: dict
    call_id: str
    _seen: list = PrivateAttr()

    def __init__(self, *, reply, seen, call_id):
        super().__init__(reply=reply, call_id=call_id)
        self._seen = seen

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._seen.append([getattr(m, "content", None) for m in messages])
        answer = self.reply.get("answer")
        if answer is not None:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content=answer, tool_calls=[]))])
        name, args = self.reply["tool_call"]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content="",
            tool_calls=[{
                "name": name, "args": args,
                "id": self.call_id, "type": "tool_call",
            }],
        ))])

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def _hunter_factory(steps, seen=None):
    """A `model_factory` yielding a fresh scripted model per turn, walking the
    script (one build per `arun_session_turn`)."""
    cursor = {"i": 0}
    record = seen if seen is not None else []

    def make(role_id):
        i = cursor["i"]
        cursor["i"] = i + 1
        return _ScriptedFake(
            reply=steps[min(i, len(steps) - 1)],
            seen=record,
            call_id=f"h-{i}",
        )

    return make


def _tool_call(name, args=None):
    """One scripted REAL tool call the model emits (name + args per schema)."""
    return {"tool_call": (name, args or {})}


def _answer(text):
    """One scripted plain answer - the model concluded the hunt."""
    return {"answer": text}


def _hunt_config(**overrides) -> HuntConfig:
    """A canonical `HuntConfig` for the (Service:slug:a, fault-x) pair."""
    base = HuntConfig(
        hunt_id="hunt-1",
        unit_id=UNIT_ID,
        fault_class=FAULT_CLASS,
        prompt_template=HuntPromptTemplate(
            rationale=f"{FAULT_CLASS} applies to {UNIT_ID} because ...",
            l0_evidence=["GET /api/a answers 200"],
            research_direction="CSRF feasibility reasoning at the state-changing form locus",
        ),
        surface_context={"cards": []},
        observed_defences=["perimeter WAF on /api/*"],
        preconditions=["an authenticated session is obtainable"],
        prior_hunt_insights=[],
    )
    return base.model_copy(update=overrides)


def _fault(fault_id, *, status, mechanism="m", supports=None, conflicts=None,
           test="t"):
    """A `FaultItem`-shaped write payload carrying the lifecycle status."""
    return {"fault_id": fault_id, "mechanism": mechanism,
            "supports": supports or [], "conflicts": conflicts or [],
            "test": test, "status": status}


def _spec(fault_id, spec_id, *, status, strategy="probe", **extra):
    """A `specified`-write payload carrying the commit-specification fields."""
    body = {
        "fault_id": fault_id, "spec_id": spec_id, "status": status,
        "strategy": strategy, "fault_key": FAULT_KEY,
        "spec_ref": (f"data/{PROJECT}/hunter/test-specs/{FAULT_KEY}/"
                     f"produced/{fault_id}_{strategy}.yaml"),
        "experiment_ref": "", "mechanism": "m", "supports": ["e1"],
        "conflicts": [], "test": "t",
    }
    body.update(extra)
    return body


def build_memory_store(tmp_path) -> HunterMemoryStore:
    """A real `HunterMemoryStore` rooted on the test's tmp_path (the explicit
    root the module's tests use; the fixed seam root stays production-only)."""
    return HunterMemoryStore(root_dir=tmp_path)


def build_hunter_agent(memory_store, *, run_id="run-1", project_id=PROJECT,
                       steps=None, seen=None, kb_fn=None):
    """The REAL turn-by-turn harness with a scripted model - the memory
    walkthroughs' entry seam. The live edge (the LLM session) is driven by the
    scripted `model_factory`; the real store, the real five-tool surface, and
    the real compiled graph ride."""
    return build_sync_hunting_agent(
        run_id=run_id,
        project_id=project_id,
        memory_store=memory_store,
        kb_fn=kb_fn,
        model_factory=_hunter_factory(steps or [], seen=seen),
        checkpointer=InMemorySaver(),
        middleware=[],
        observe=False,
    )