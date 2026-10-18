"""#236 integration tier - the artifact-declared skill configuration, chained hop
by hop.

The orchestrator names skills in its ratified `HuntConfig`; the hunter names
skills in its `TestImplementationSpec`. Each artifact is parsed by the symbolic
layer at dispatch (the surfer's `_config_dispatch` / `_spec_dispatch`, the pod
graph's per-node harness context), and the declared names are resolved, unioned
with the role baseline (`ROLE_SKILLS`), and threaded into the session invocation
context - so the existing L1 index middleware renders each resolved skill's
frontmatter `description` into that agent's system prompt, verified here through
the REAL session path (`arun_session_turn` / `create_agent`) with a recording
fake model.

Also pinned: the malformed artifact degrades its hunt/spec (refused or
INIT-rejected), never crashes the dispatch.
"""
from __future__ import annotations

import asyncio

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from polymerhus.app.llm.skills import skill_meta
from polymerhus.attack.hunting.hunt_orchestrator import HuntConfig, HuntPromptTemplate
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.attack.hunting.pod import arun_pod
from polymerhus.attack.hunting.pod.llm import (
    POD_RUNNER_ROLE,
    POD_TRIAGER_ROLE,
    PodHarnessContext,
    bind_pod_session,
)
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore, spec_identifier
from polymerhus.recon.domain.types import ExecResult

UNIT = "Service:catalogue-and-discovery"
CWE = "CWE-639"
CLASS = "IDOR"
FAULT_KEY = f"{UNIT}_{CWE}_{CLASS}"
CONFIG_KEY = f"{UNIT}::{CWE}::{CLASS}"

SPEC_ID = spec_identifier("sqli", "blind")

_ABSENT = "not found\n__POD_HTTP_STATUS__:404\n__POD_HTTP_TIME__:0.02"


def _recording_factory(seen: list, *, body: str = "concluded"):
    """A `model_factory` whose model records every message list it is handed, so
    the REAL system prompt a session turn composes (base prompt + L1 index) is
    assertable without a live model. The sink is captured in the closure: the
    model instance is built per turn, so nothing may live on the instance."""

    class _RecordingModel(BaseChatModel):
        body: str = "concluded"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            seen.append(list(messages))
            return ChatResult(generations=[ChatGeneration(
                message=AIMessage(content=self.body))])

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            # Async-native: the production path is `astream` on an async model.
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

    def make(role_id):
        return _RecordingModel(body=body)

    return make


def _system_messages(seen: list) -> list[str]:
    out = []
    for messages in seen:
        for message in messages:
            if isinstance(message, SystemMessage):
                out.append(str(message.content or ""))
    return out


def _config(**overrides) -> dict:
    data = {
        "hunt_id": "hunt-1",
        "unit_id": UNIT,
        "fault_class": CWE,
        "status": "ratified",
        "vulnerability_class": CLASS,
        "prompt_template": {"rationale": "r", "l0_evidence": []},
    }
    data.update(overrides)
    return data


def _spec(**overrides) -> dict:
    data = {
        "target_identity": {"url": "http://t/", "unit_id": "svc"},
        "verification_symptoms": ["reflects the marker"],
        "testing_pattern": "blind-boolean",
        "payload_vector_space": {"method": "GET"},
    }
    data.update(overrides)
    return data


def _exec(stdout=_ABSENT, returncode=0):
    def fake(command, timeout_s):
        return ExecResult(stdout=stdout, stderr="", returncode=returncode, duration_ms=1)
    return fake


def _no_trace(_run_id):
    return []


# --- the hunter: a ratified HuntConfig names the downstream skills -------------


def test_ratified_config_skills_render_into_the_hunters_system_prompt(tmp_path):
    """The real session path: the harness drives `arun_session_turn` with the
    binding's context + middleware, and the recorded model input carries the
    artifact-named skill's description verbatim, beside the baseline."""
    from polymerhus.attack.hunting.hunting_agent import build_hunting_agent

    seen: list = []
    dispatch = build_hunting_agent(
        run_id="run-1", project_id="proj-1",
        memory_store=HunterMemoryStore(tmp_path / "hunter"),
        hunt_store=HuntStore(tmp_path / "hunts"),
        checkpointer=InMemorySaver(),
        model_factory=_recording_factory(seen),
        observe=False,
    )
    config = HuntConfig.model_validate(_config(skills=["ssrf"]))

    asyncio.run(dispatch(config))

    assert seen, "the hunt must have taken a session turn"
    system = _system_messages(seen)[0]
    assert f"- ssrf: {skill_meta('ssrf')['description']}" in system
    for name in ("lightrag-query", "steel-browser"):
        assert f"- {name}: {skill_meta(name)['description']}" in system


def test_the_hunters_system_prompt_is_stable_across_its_turns(tmp_path):
    """The prompt-cache prefix (ADR A5): the index is byte-identical on every
    turn of one hunt - the set is rebuilt per dispatch, never mutated."""
    from polymerhus.attack.hunting.hunting_agent import build_hunting_agent

    seen: list = []
    dispatch = build_hunting_agent(
        run_id="run-1", project_id="proj-1",
        memory_store=HunterMemoryStore(tmp_path / "hunter"),
        hunt_store=HuntStore(tmp_path / "hunts"),
        checkpointer=InMemorySaver(),
        model_factory=_recording_factory(seen),
        observe=False,
    )

    asyncio.run(dispatch(HuntConfig.model_validate(_config(skills=["csrf", "ssrf"]))))

    systems = set(_system_messages(seen))
    assert len(systems) == 1, "one byte-stable system prompt across the hunt"


# --- the pod: a TestImplementationSpec names the runner's skills --------------


def test_spec_skills_render_into_the_pod_runners_system_prompt(tmp_path):
    seen: list = []
    asyncio.run(arun_pod(
        _spec(skills=["csrf"]), exec_fn=_exec(), trace_fn=_no_trace,
        memory_store=PodMemoryStore(tmp_path), spec_id=SPEC_ID,
        model_factory=_recording_factory(seen),
    ))

    assert seen, "the pod must have taken a runner turn"
    system = _system_messages(seen)[0]
    assert f"- csrf: {skill_meta('csrf')['description']}" in system
    for name in ("lightrag-query", "steel-browser"):
        assert f"- {name}: {skill_meta(name)['description']}" in system


def test_spec_skills_render_into_the_pod_triagers_system_prompt(tmp_path):
    """The triager's binding rides the same per-spec harness context, so the
    spec's declaration reaches the critic's turn too."""
    from polymerhus.attack.hunting.pod.agents import default_triager_fn
    from polymerhus.attack.hunting.pod.context import ExperimentLog

    seen: list = []
    log = ExperimentLog()
    hc = PodHarnessContext(
        exec_fn=_exec(), memory_store=PodMemoryStore(tmp_path), spec_id=SPEC_ID,
        log=log, variant_ref="v0", model_factory=_recording_factory(seen),
        task_skills=("csrf",),
    )

    async def _drive():
        with bind_pod_session("run-x", "", SPEC_ID, role_id=POD_TRIAGER_ROLE, harness=hc):
            return await default_triager_fn(
                _spec(skills=["csrf"]), None,
                [{"role": "human", "content": "triager delta"}], log)

    asyncio.run(_drive())

    assert seen, "the triager must have taken a turn"
    system = _system_messages(seen)[0]
    assert f"- csrf: {skill_meta('csrf')['description']}" in system
    assert f"- lightrag-query: {skill_meta('lightrag-query')['description']}" in system


def test_a_malformed_spec_skills_field_is_init_rejected_not_a_crash(tmp_path):
    """A malformed artifact degrades its spec: the pod's INIT gate rejects the
    spec with zero tool calls, and the envelope still comes back."""
    env = asyncio.run(arun_pod(
        _spec(skills=7), exec_fn=_exec(), trace_fn=_no_trace,
        memory_store=PodMemoryStore(tmp_path), spec_id=SPEC_ID,
    ))

    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["init_validation"], "the malformed spec must be rejected"
    assert any("TestImplementationSpec" in v
               for v in env["evidence"]["init_validation"])


def test_a_non_list_skills_value_degrades_the_graph_context(tmp_path, caplog):
    """The graph's spec-side read is defensive as well: a non-list value never
    raises into the node (the INIT gate is the loud rejection)."""
    from polymerhus.attack.hunting.pod.graph import _spec_task_skills

    assert _spec_task_skills({"spec": {"skills": 7}}) == ()
    assert _spec_task_skills({"spec": {"skills": ["ssrf", None, 3, "  "]}}) == ("ssrf",)
    assert _spec_task_skills({}) == ()


# --- a minted variant keeps (or re-declares) the run's skills ------------------


def _exec_and_conclude_factory(seen: list):
    """A two-call scripted model for ONE runner stretch: a real `exec` tool call
    (so the stretch records an observation and the graph routes to the triager),
    then a plain conclusion."""

    class _Model(BaseChatModel):
        calls: int = 0

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            seen.append(list(messages))
            self.calls += 1
            if self.calls == 1:
                return ChatResult(generations=[ChatGeneration(message=AIMessage(
                    content="", tool_calls=[{
                        "name": "exec",
                        "args": {"command": "curl -k -sS https://t/"},
                        "id": "c1",
                    }]))])
            return ChatResult(generations=[ChatGeneration(
                message=AIMessage(content="stretch concluded"))])

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
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

    def make(role_id):
        return _Model()

    return make


def _variant_triager(variant_spec: dict):
    """An injected triager that mints one variant (then terminates on the next
    lap), so the graph path mint -> runner stretch 2 is exercised."""

    laps = {"n": 0}

    def triager_fn(spec, observation, messages, log):
        laps["n"] += 1
        if laps["n"] == 1:
            return {
                "classification": "symptom-absent", "action": "variant",
                "declined_attribute": "payload vector",
                "variant_spec": variant_spec,
                "feedback": "try the derived variant",
            }
        return {
            "classification": "symptom-absent", "action": "terminate",
            "verdict": "unsuccessful", "terminal_reason": "space-exhausted",
            "clean": True, "note": "done",
        }

    return triager_fn


def test_a_minted_variant_inherits_the_parent_specs_declared_skills(tmp_path):
    """#236 mechanism: the triager's variant spec replaces `state["spec"]`
    wholesale, so the symbolic layer carries the parent's declaration onto a
    variant that does not state its own - the runner's LATER stretch still
    renders the skill the run was configured with."""
    seen: list = []
    env = asyncio.run(arun_pod(
        _spec(skills=["ssrf"]), exec_fn=_exec(), trace_fn=_no_trace,
        memory_store=PodMemoryStore(tmp_path), spec_id=SPEC_ID,
        triager_fn=_variant_triager({"testing_pattern": "blind-boolean"}),
        model_factory=_exec_and_conclude_factory(seen),
    ))

    assert env["evidence"]["iterations"] == 2, "the variant lap must have run"
    systems = _system_messages(seen)
    assert len(systems) >= 3, "two runner stretches, one model call each"
    for system in systems:
        assert f"- ssrf: {skill_meta('ssrf')['description']}" in system


def test_a_minted_variant_with_its_own_declaration_wins(tmp_path):
    """A variant that states its own `skills` replaces the inherited set: the
    later stretch renders the variant's declaration, not the parent's."""
    seen: list = []
    asyncio.run(arun_pod(
        _spec(skills=["ssrf"]), exec_fn=_exec(), trace_fn=_no_trace,
        memory_store=PodMemoryStore(tmp_path), spec_id=SPEC_ID,
        triager_fn=_variant_triager({
            "testing_pattern": "blind-boolean", "skills": ["csrf"],
        }),
        model_factory=_exec_and_conclude_factory(seen),
    ))

    systems = _system_messages(seen)
    last = systems[-1]
    assert f"- csrf: {skill_meta('csrf')['description']}" in last
    assert "ssrf" not in last


# --- the surfer dispatch: the artifact rides the parsed config/spec -----------


def test_the_surfer_threads_the_ratified_configs_skills_into_the_dispatch(
    tmp_path, monkeypatch
):
    from polymerhus.attack.hunting.surfer import RunDispatchState, build_run_dispatch
    from polymerhus.attack.hunting.mover import HuntConfigItem
    from polymerhus.attack.hunting import surfer as surfer_mod

    # The idle stretch is its own test: here only the dispatch hand-off matters,
    # and the real idle loop would wait on the run's settle message forever.
    async def _noop_idle(**kwargs):
        return None

    monkeypatch.setattr(surfer_mod, "_run_hunter_idle", _noop_idle)

    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    hunt.write_config("proj-1", _config(skills=["ssrf"]))
    received: list = []

    async def _dispatch(config):
        received.append(config)
        return None

    def builder(*, run_id, project_id, hunt_store, hunter_store, **kw):
        return _dispatch, None

    coro_for = build_run_dispatch(
        project_id="proj-1", run_id="run-1",
        hunt_store=hunt, hunter_store=hunter, pod_store=None,
        state=RunDispatchState(), gate=None,
        hunter_builder=builder, pod_builder=None,
    )
    coro = coro_for(HuntConfigItem(
        message_id=CONFIG_KEY, session_id="", config_key=CONFIG_KEY,
    ))
    assert coro is not None
    asyncio.run(coro)

    assert received and received[0].skills == ["ssrf"]


def test_a_malformed_config_is_refused_never_dispatched(tmp_path, caplog):
    """A config body whose `skills` is not a list of names is not ratifiable:
    the surfer refuses the dispatch (at-least-once, retried) - never a crash."""
    from polymerhus.attack.hunting.surfer import RunDispatchState, build_run_dispatch
    from polymerhus.attack.hunting.mover import HuntConfigItem

    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    hunt.write_config("proj-1", _config(skills="ssrf"))

    def builder(*, run_id, project_id, hunt_store, hunter_store, **kw):
        raise AssertionError("a malformed config must never dispatch")

    coro_for = build_run_dispatch(
        project_id="proj-1", run_id="run-1",
        hunt_store=hunt, hunter_store=hunter, pod_store=None,
        state=RunDispatchState(), gate=None,
        hunter_builder=builder, pod_builder=None,
    )
    with caplog.at_level("WARNING", logger="polymerhus.attack.hunting.surfer"):
        out = coro_for(HuntConfigItem(
            message_id=CONFIG_KEY, session_id="", config_key=CONFIG_KEY,
        ))
    assert out is None
    assert any("not ratifiable" in record.message for record in caplog.records)


def test_the_surfer_threads_the_specs_skills_into_the_pod_session(tmp_path):
    from polymerhus.attack.hunting.surfer import RunDispatchState, build_run_dispatch
    from polymerhus.attack.hunting.mover import TestSpecItem

    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    hunter.write_spec(
        "proj-1", FAULT_KEY, fault_keyword="sqli", strategy_keyword="blind",
        spec={**_spec(skills=["csrf"]), "status": "specified"},
    )
    received: list = []

    async def pod_builder(spec, **kw):
        received.append(spec)
        return {"verdict": "unsuccessful", "terminal_reason": "no-symptom-evidence"}

    coro_for = build_run_dispatch(
        project_id="proj-1", run_id="run-1",
        hunt_store=hunt, hunter_store=hunter, pod_store=None,
        state=RunDispatchState(), gate=None,
        hunter_builder=None, pod_builder=pod_builder,
    )
    coro = coro_for(TestSpecItem(
        message_id=f"{FAULT_KEY}/sqli_blind", session_id="",
        fault_key=FAULT_KEY, spec_file="sqli_blind",
    ))
    assert coro is not None
    asyncio.run(coro)

    assert received and received[0]["skills"] == ["csrf"]


# --- the hunter idle loop: the same artifact set on the hunt's thread ---------


def test_the_hunter_idle_loop_carries_the_configs_skills(monkeypatch, tmp_path):
    """The idle stretch is a hunter turn of the SAME hunt: its binding must
    carry the ratified config's declared skills, so the hunt's index is
    byte-stable across the graph phase and the idle phase."""
    import polymerhus.app.auth.seams as auth_seams
    import polymerhus.app.llm.actor as actor_mod
    from polymerhus.attack.hunting import surfer as surfer_mod

    captured: dict = {}

    def fake_binding(role_id, **kwargs):
        captured["role_id"] = role_id
        captured["kwargs"] = kwargs
        return type("_B", (), {"tools": [], "middleware": [], "context": {}})()

    async def fake_run_session_agent(*args, **kwargs):
        return None

    monkeypatch.setattr(auth_seams, "auth_capable_binding", fake_binding)
    monkeypatch.setattr(actor_mod, "run_session_agent", fake_run_session_agent)

    state = surfer_mod.RunDispatchState()
    from polymerhus.app.llm.actor import AgentInbox

    state.hunter_inboxes[CONFIG_KEY] = AgentInbox()
    config = HuntConfig.model_validate(_config(skills=["ssrf"]))

    asyncio.run(surfer_mod._run_hunter_idle(
        project_id="proj-1", run_id="run-1", config=config,
        config_key=CONFIG_KEY,
        hunter_store=HunterMemoryStore(tmp_path / "hunter"),
        state=state,
    ))

    assert captured["role_id"] == "hunting_hunter"
    assert captured["kwargs"]["task_skills"] == ["ssrf"]
