"""Unit tier: the hunting MAILBOX actors (`attack/hunting/actors.py`, #94).

`threat_modeller.arun_modeller_pass` drives one turn per gate state on ONE
`ThreatModellerActor` per run (`hunting_threat_modeller` session thread), and
each hunt's authoring/judging rides a per-hunt `HuntingHunterActor` on its
`HuntSession` thread. These tests exercise the actors at the public seams
(`turn` / `author` / `judge` / `stop` / the registry) with a FAKE session agent
or fake models and an `InMemorySaver`; the unit tier touches no live model and
no live database (CODING_STANDARD sections 6, 10).
"""
from __future__ import annotations

import asyncio
import json

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.attack.hunting.actors import (
    HuntingActorRegistry,
    HuntingHunterActor,
    ThreatModellerActor,
)
from polymerhus.attack.hunting.threat_model import ModelState
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.attack.hunting.threat_modeller import (
    GATE_HINTS,
    ModellerTurnInput,
    STATE_INSTRUCTIONS,
    TOOL_SURFACE,
)
from polymerhus.attack.hunting.threat_modeller_tools import (
    ModellerTools,
    ModellerUnit,
)
from lightrag.tool import LightRagQueryTool

from tests.hunting_fixtures import modeller_gate_payloads


class _TextFake(BaseChatModel):
    """A free-text fake (the hunter turns carry no response_format): emits a
    JSON body as plain content, which `_parse_json_object` recovers."""

    body: str = ""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.body))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        # Async-native: see `_ToolFake._agenerate` for why (sync-only fakes
        # deadlock the resumed agent thread's model call).
        return self._generate(
            messages,
            stop=stop,
            run_manager=run_manager.get_sync() if run_manager else None,
            **kwargs,
        )

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        # As of #197 the author lane ALWAYS binds the lightrag tool, so a plain-
        # text fake must tolerate `bind_tools` (returns self - a tool-free reply
        # concludes the turn exactly like a real model declining the tool).
        return self


class _ToolLoopFake(BaseChatModel):
    """A per-instance two-reply scripted model: the first model call emits a
    `query_lightrag` tool call, the second emits the final text answer. The
    counter lives on the instance because ONE agent turn's tool loop reuses the
    same model for every model call."""

    tool_args: dict = {}
    final_body: str = ""

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        calls = getattr(self, "_calls", 0)
        self._calls = calls + 1
        if calls == 0:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(
                content="",
                tool_calls=[{
                    "name": "query_lightrag",
                    "args": self.tool_args,
                    "id": "c1",
                    "type": "tool_call",
                }],
            ))])
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.final_body))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        # Async-native: see `_ToolFake._agenerate` for why.
        return self._generate(
            messages,
            stop=stop,
            run_manager=run_manager.get_sync() if run_manager else None,
            **kwargs,
        )

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


# --- the threat modeller actor (S1 4.4, T2b #386) ------------------------------

def test_threat_modeller_actor_binds_the_surface_and_serves_a_turn(tmp_path,
                                                                   monkeypatch):
    """The actor harness: a fake session agent stands in for
    `run_session_agent`, so the REAL actor path runs end to end - the bound
    tool surface (the modeller's exactly, plus the role's load_skill/auth
    binding), the `_on_message` turn composition (a HumanMessage carrying the
    unit/state/sections/instruction/model), the gate write through the bound
    store tool, the reply delivered through the actor's inbox middleware, and
    the clean `stop()`."""
    import polymerhus.app.llm.actor as llm_actor

    store = ThreatModelStore(root_dir=tmp_path)
    tools = ModellerTools(threat_store=store, project_id="proj-1", run_id="run-1",
                          unit_cell=ModellerUnit())
    seen: dict = {}

    async def fake_run_session_agent(role_id, thread_id, initial_messages,
                                     **kwargs):
        seen["role_id"] = role_id
        seen["thread_id"] = thread_id
        seen.update(kwargs)
        message = await kwargs["inbox"].get()
        if message.kind == "stop":
            return None
        # the fake "model": compose the turn through the actor's OWN handler,
        # write the gate through the BOUND tool, deliver the reply through the
        # actor's inbox middleware
        messages = kwargs["on_message"](message, None)
        surface = {tool.name: tool for tool in kwargs["tools"]}
        seen["gate_write"] = surface["hunts_store"].invoke({
            "cmd": "write", "state": ModelState.UNIT_TECHNICAL_SHARP.value,
            "sections": modeller_gate_payloads()[
                ModelState.UNIT_TECHNICAL_SHARP],
        })
        seen["read"] = surface["hunts_store"].invoke({"cmd": "read"})
        seen["note"] = surface["notes"].invoke({
            "cmd": "write", "option": "append", "note_name": "grounding",
            "kind": "freeform", "body": "the catalogue id is caller-supplied",
        })
        delivery = next(
            item for item in kwargs["middleware"]
            if type(item).__name__ == "InboxDispatchMiddleware")
        delivery.after_agent(
            {"messages": messages, "structured_response": messages[0].content},
            None,
        )
        seen["surface"] = surface
        seen["messages"] = messages

    monkeypatch.setattr(llm_actor, "run_session_agent", fake_run_session_agent)

    turn_input = ModellerTurnInput(
        unit_id="Service:slug:a",
        state=ModelState.UNIT_TECHNICAL_SHARP,
        sections=("technical_sharpening",),
        instruction=STATE_INSTRUCTIONS[ModelState.UNIT_TECHNICAL_SHARP],
        model=None,
    )

    async def _drive():
        # the pass retargets the run's unit cell before the first turn (the
        # stable-seam pattern: the actor captures its surface once, the cell is
        # what follows the run from unit to unit)
        tools.unit_cell.retarget(project_id="proj-1", run_id="run-1",
                                 unit_id="Service:slug:a")
        actor = ThreatModellerActor(
            "run-1", checkpointer=InMemorySaver(), tools=tools,
            project_id="proj-1", compaction=False, observe=False,
        )
        content = await actor.turn(turn_input)
        await actor.stop()
        return actor, content

    actor, content = asyncio.run(_drive())

    # the run-scoped session thread and role
    assert seen["role_id"] == "hunting_threat_modeller"
    assert seen["thread_id"] == actor.thread_id
    assert "run-1" in seen["thread_id"]
    # the bound surface is the modeller's exactly, plus the role's read-only
    # skill + auth binding (never graph_view / kb_query / the fault-KB aid)
    names = set(seen["surface"])
    assert set(TOOL_SURFACE) <= names
    assert {"load_skill", "auth_store"} <= names
    assert not {"graph_view", "kb_query", "query_lightrag"} & names
    # `_on_message` composed the turn: ONE HumanMessage carrying the unit, the
    # state, the gate sections, the instruction, and the fresh-model marker
    [human] = seen["messages"]
    assert isinstance(human, HumanMessage)
    assert "Service:slug:a" in human.content
    assert "UNIT_TECHNICAL_SHARP" in human.content
    assert "technical_sharpening" in human.content
    assert STATE_INSTRUCTIONS[ModelState.UNIT_TECHNICAL_SHARP] in human.content
    assert "(not written yet)" in human.content
    # the gate write landed through the bound tool, and its response carries the
    # next-state hint (S1 9.3: the hint rides the tool response, never the turn)
    assert seen["gate_write"]["ok"] is True
    assert seen["gate_write"]["hint"] == GATE_HINTS[
        ModelState.UNIT_TECHNICAL_SHARP]
    # the bound read reports the persisted state and the written sections
    assert seen["read"]["unit_id"] == "Service:slug:a"
    assert seen["read"]["state"] == ModelState.UNIT_TECHNICAL_SHARP.value
    assert "technical_sharpening" in seen["read"]["sections"]
    # the bound notes tool wrote under the unit-bound key
    assert seen["note"] == {"ok": True, "key": "Service-slug-a:grounding"}
    assert store.read_model("proj-1", "Service:slug:a")["state"] == \
        ModelState.UNIT_TECHNICAL_SHARP.value
    # the reply the middleware delivered is the turn's return value
    assert content is not None and "Service:slug:a" in content


def test_threat_modeller_actor_turn_with_no_input_is_a_no_decision():
    """A None turn is a no-decision without spawning the session agent."""
    async def _drive():
        actor = ThreatModellerActor("run-1", observe=False)
        return await actor.turn(None)

    assert asyncio.run(_drive()) is None


# --- the per-hunt hunting-hunter actor --------------------------------------------

def test_hunting_hunter_actor_authors_and_judges_on_one_thread():
    """ONE actor per hunt: the author (D4) and judge (D5) turns on the SAME
    `HuntSession` thread, free-text JSON replies parsed back, stop() clean."""
    body_a = json.dumps({"target_identity": {"url": "http://a/", "unit_id": "Service:slug:a"}, "rationale": "spec"})
    body_j = json.dumps({"meaningful_insight": False, "next_step": "end", "rationale": "r"})
    cursor = {"i": 0}

    def factory(role_id):
        i = cursor["i"]
        cursor["i"] = i + 1
        return _TextFake(body=(body_a, body_j)[min(i, 1)])

    async def _drive():
        actor = HuntingHunterActor(
            "run1", "hunt-7", checkpointer=InMemorySaver(), model_factory=factory,
            observe=False,
        )
        spec = await actor.author("compose the spec")
        verdict = await actor.judge("any judgment text")
        await actor.stop()
        return spec, verdict

    spec, verdict = asyncio.run(_drive())
    assert spec == {"target_identity": {"url": "http://a/", "unit_id": "Service:slug:a"}, "rationale": "spec"}
    assert verdict == {"meaningful_insight": False, "next_step": "end", "rationale": "r"}


def test_hunting_hunter_actor_unparseable_turn_is_none():
    async def _drive():
        actor = HuntingHunterActor(
            "run1", "hunt-8", checkpointer=InMemorySaver(),
            model_factory=lambda role: _TextFake(body="not json at all"), observe=False,
        )
        out = await actor.author("compose")
        await actor.stop()
        return out

    assert asyncio.run(_drive()) is None  # degraded turn, fail-open


def test_hunting_hunter_actor_resumes_after_two_author_turns():
    """Regression: two consecutive turns on the SAME per-hunt thread must both
    complete. This used to deadlock inside the second turn's model call with
    sync-only fakes (langgraph resume + `run_in_executor`); the fakes are now
    async-native, matching the production ChatOpenAI path."""
    cursor = {"i": 0}

    def factory(role_id):
        i = cursor["i"]
        cursor["i"] = i + 1
        return _TextFake(body=json.dumps({"spec": i}))

    async def _drive():
        actor = HuntingHunterActor(
            "run1", "hunt-r", checkpointer=InMemorySaver(), model_factory=factory,
            observe=False,
        )
        first = await actor.author("compose first")
        second = await actor.author("compose second")
        await actor.stop()
        return first, second

    first, second = asyncio.run(_drive())
    assert first == {"spec": 0}
    assert second == {"spec": 1}


# --- the per-run registry -----------------------------------------------------------

def test_registry_routes_per_hunt_and_reaps_every_actor():
    """The run's registry keys actors by hunt_id: concurrent hunts never
    collide, and stop_all() reaps every spawned actor (idempotent)."""
    async def _drive():
        registry = HuntingActorRegistry(
            "run1", checkpointer=InMemorySaver(),
            model_factory=lambda role: _TextFake(body='{"hunt": "x"}'), observe=False,
        )
        # per-hunt distinct threads
        a = registry.actor_for("hunt-a")
        b = registry.actor_for("hunt-b")
        assert a.thread_id != b.thread_id
        assert "hunt-a" in a.thread_id and "hunt-b" in b.thread_id
        assert registry.actor_for("hunt-a") is a  # same actor, same thread
        # the bound author/judge closures route to the right hunt
        out = await registry.author_fn("hunt-a")("compose")
        await registry.stop_all()
        return out

    outcome = asyncio.run(_drive())
    assert outcome == {"hunt": "x"}


def test_author_tools_reach_run_session_agent(monkeypatch):
    """author_tools on the registry land on the actor and are forwarded to
    run_session_agent's kwargs when non-empty."""
    import polymerhus.app.llm.actor as llm_actor

    captured = {}

    async def fake_run_session_agent(
        role_id, thread_id, initial_messages, **kwargs
    ):
        captured.update(kwargs)

    monkeypatch.setattr(llm_actor, "run_session_agent", fake_run_session_agent)

    async def _drive():
        registry = HuntingActorRegistry(
            "run-1", author_tools=["fake-tool"], project_id="proj-1",
            checkpointer=InMemorySaver(), observe=False,
        )
        actor = registry.actor_for("hunt-1")
        assert "fake-tool" in actor._tools
        await actor._ensure_started()
        await actor._task
        return actor

    actor = asyncio.run(_drive())
    assert actor._tools == ["fake-tool"]
    # The actor's turns are scoped to the run's project in the usage ledger.
    assert captured["usage_scope"] == "proj-1"
    # The auth capability (#220) rides the same bounding seam as the skill
    # surface: a bound role additionally carries `auth_store`.
    assert [getattr(t, "name", t) for t in captured["tools"]] == [
        "fake-tool",
        "load_skill",
        "record_skill_lesson",
        "auth_store",
    ]


def test_hunting_hunter_actor_runs_query_lightrag_tool_loop_hermetically():
    """The full tool-calling loop, without any live service: the outer model
    first calls `query_lightrag`, the fake client/llm answer hermetically, a
    ToolMessage is produced, and the actor's final author reply uses the tool
    output (the mini live smoke, repeatable in the unit suite)."""
    class _FakeClient:
        def query_data(self, payload):
            return {
                "status": "success",
                "message": "ok",
                "data": {
                    "entities": [],
                    "relationships": [],
                    "chunks": [
                        {
                            "reference_id": "doc-1",
                            "file_path": "WSTG-ATHZ/x.md",
                            "content": "Methodology text about object id tampering.",
                        }
                    ],
                    "references": [
                        {"reference_id": "doc-1", "file_path": "WSTG-ATHZ/x.md"}
                    ],
                },
                "metadata": {"processing_info": {"final_chunks_count": 1}},
            }

    class _FakeLlm:
        def stream(self, prompt):
            yield {"type": "delta", "text": '{"scenario_id": "SIM-01", "summary": "ok",'}
            yield {
                "type": "delta",
                "text": (
                    '"ontology_explanations": [{"entity_type": "AttackTechnique", '
                    '"entity_name": "Object-level authorization comparison", '
                    '"explanation": "Compare authorization behavior for adjacent ids."}],'
                ),
            }
            yield {"type": "delta", "text": '"knowledge_gaps": ["g"]}'}
            yield {"type": "finish", "finish_reason": "stop"}

    tool = LightRagQueryTool(client=_FakeClient(), llm=_FakeLlm())
    tool_args = {
        "scenario_id": "SIM-01",
        "attack_goal": "Identify a bounded comparison hypothesis",
        "concern": "object-level authorization",
        "acceptable_technique_families": ["Object-level authorization comparison"],
    }
    final_body = json.dumps({
        "methodology": "Object-level authorization comparison",
        "verdict": "grounded",
    })

    async def _drive():
        actor = HuntingHunterActor(
            "run1", "hunt-tool", checkpointer=InMemorySaver(),
            model_factory=lambda role: _ToolLoopFake(
                tool_args=tool_args, final_body=final_body,
            ),
            observe=False, author_tools=[tool],
        )
        out = await actor.author("compose")
        await actor.stop()
        return out, actor

    out, actor = asyncio.run(_drive())
    assert out == {"methodology": "Object-level authorization comparison", "verdict": "grounded"}
    trail = actor._task.result().turns[-1].messages
    tool_msgs = [m for m in trail if type(m).__name__ == "ToolMessage"]
    assert tool_msgs, "the query_lightrag tool call must be executed"
    assert "Object-level authorization comparison" in tool_msgs[0].content


def test_lightrag_tool_always_bound(monkeypatch):
    # As of #197 the HUNTING_LIGHTRAG_TOOL gate is REMOVED: the lightrag tool is
    # always bound into the author lane (fail-open when the KB is unavailable).
    import polymerhus.attack.hunting.actors as actors

    monkeypatch.setattr(
        actors,
        "_lightrag_author_tools",
        lambda: ["lightrag-tool"],
    )
    registry = actors.HuntingActorRegistry("run-1")
    assert "lightrag-tool" in registry.actor_for("hunt-1")._tools


def test_run_scoped_actors_tag_turns_with_the_run_id():
    """Convergence join: both run-scoped actors expose the bare run id as the
    turn tags now that the hand-written agent/gate spans are gone."""
    assert ThreatModellerActor("run1")._extra_tags == ["run1"]
    assert HuntingHunterActor("run1", "hunt-a")._extra_tags == ["run1"]
