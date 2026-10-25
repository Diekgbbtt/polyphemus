"""The artifact-declared skill configuration (#236) on the D4 spec.

The unit threat model retires ``HuntConfig`` and its orchestrator-side skill
declaration. The one surviving declaration is the hunter's ``skills`` field on
each ``TestImplementationSpec``: the pod runner and the pod triager resolve it
project-first, union it with their role baseline, and render the frontmatter
descriptions into their system prompts. This suite pins that D4 path end to
end, the typed write schema that teaches it, the malformed-value degradation,
and the variant inheritance rule.
"""
from __future__ import annotations

import asyncio

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from polymerhus.attack.hunting.pod import arun_pod
from polymerhus.attack.hunting.pod.llm import (
    POD_TRIAGER_ROLE,
    PodHarnessContext,
    bind_pod_session,
)
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore, spec_identifier
from polymerhus.recon.domain.types import ExecResult

SPEC_ID = spec_identifier("sqli", [{"axis": "technique", "value": "blind"}, {"axis": "payload-vector", "value": "boolean"}])

_ABSENT = "not found\n__POD_HTTP_STATUS__:404\n__POD_HTTP_TIME__:0.02"


def _recording_factory(seen: list, *, body: str = "concluded"):
    """A `model_factory` whose model records every message list it is handed, so
    the REAL system prompt a session turn composes (base prompt + L1 index) is
    assertable without a live model."""

    class _RecordingModel(BaseChatModel):
        body: str = "concluded"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            seen.append(list(messages))
            return ChatResult(generations=[ChatGeneration(
                message=AIMessage(content=self.body))])

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
        return _RecordingModel(body=body)

    return make


def _system_messages(seen: list) -> list[str]:
    out = []
    for messages in seen:
        for message in messages:
            if isinstance(message, SystemMessage):
                out.append(str(message.content or ""))
    return out


def _spec(**overrides) -> dict:
    data = {
        "target_identity": {"url": "http://t/", "unit_id": "svc"},
        "verification_symptoms": ["reflects the marker"],
        "assumptions": ["the reflection is server-side"],
        "rationale": "the marker can be reflected",
        "provenance": {"loop_id": "loop-1", "unit_id": "svc"},
    }
    data.update(overrides)
    return data


def _exec(stdout=_ABSENT, returncode=0):
    def fake(command, timeout_s):
        return ExecResult(stdout=stdout, stderr="", returncode=returncode, duration_ms=1)
    return fake


def _no_trace(_run_id):
    return []


# --- the D4 declaration reaches both pod roles --------------------------------


def test_spec_skills_render_into_the_pod_runners_system_prompt(tmp_path):
    seen: list = []
    asyncio.run(arun_pod(
        _spec(skills=["csrf"]), exec_fn=_exec(), trace_fn=_no_trace,
        memory_store=PodMemoryStore(tmp_path), spec_id=SPEC_ID,
        model_factory=_recording_factory(seen),
    ))

    assert seen, "the pod must have taken a runner turn"
    system = _system_messages(seen)[0]
    assert "`csrf`" in system
    for name in ("lightrag-query", "steel-browser"):
        assert f"`{name}`" in system


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
    assert "`csrf`" in system
    assert "`lightrag-query`" in system


def test_a_malformed_spec_skills_field_is_init_rejected_not_a_crash(tmp_path):
    """A malformed artifact degrades its spec: the pod's INIT gate rejects the
    spec with zero tool calls, and the envelope still comes back."""
    env = asyncio.run(arun_pod(
        _spec(skills=7), exec_fn=_exec(), trace_fn=_no_trace,
        memory_store=PodMemoryStore(tmp_path), spec_id=SPEC_ID,
    ))

    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["init_validation"], "the malformed spec must be rejected"
    assert any("skills" in v for v in env["evidence"]["init_validation"])


def test_a_non_list_skills_value_degrades_the_graph_context(tmp_path, caplog):
    """The graph's spec-side read is defensive as well: a non-list value never
    raises into the node (the INIT gate is the loud rejection)."""
    from polymerhus.attack.hunting.pod.graph import _spec_task_skills

    assert _spec_task_skills({"spec": {"skills": 7}}) == ()
    assert _spec_task_skills({"spec": {"skills": ["ssrf", None, 3, "  "]}}) == ("ssrf",)
    assert _spec_task_skills({}) == ()


# --- a minted variant keeps (or re-declares) the parent declaration ----------


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
                "declined_attribute": "recon-action",
                "covered_gap_classes": None,
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
    """The triager's variant spec replaces `state["spec"]` wholesale, so the
    symbolic layer carries the parent's declaration onto a variant that does not
    state its own - the runner's LATER stretch still renders the skill."""
    seen: list = []
    env = asyncio.run(arun_pod(
        _spec(skills=["ssrf"]), exec_fn=_exec(), trace_fn=_no_trace,
        memory_store=PodMemoryStore(tmp_path), spec_id=SPEC_ID,
        triager_fn=_variant_triager({"rationale": "derived variant"}),
        model_factory=_exec_and_conclude_factory(seen),
    ))

    assert env["evidence"]["iterations"] == 2, "the variant lap must have run"
    systems = _system_messages(seen)
    assert len(systems) >= 3, "two runner stretches, one model call each"
    for system in systems:
        assert "`ssrf`" in system


def test_a_minted_variant_with_its_own_declaration_wins(tmp_path):
    """A variant that states its own `skills` replaces the inherited set: the
    later stretch renders the variant's declaration, not the parent's."""
    seen: list = []
    asyncio.run(arun_pod(
        _spec(skills=["ssrf"]), exec_fn=_exec(), trace_fn=_no_trace,
        memory_store=PodMemoryStore(tmp_path), spec_id=SPEC_ID,
        triager_fn=_variant_triager({
            "rationale": "derived variant", "skills": ["csrf"],
        }),
        model_factory=_exec_and_conclude_factory(seen),
    ))

    systems = _system_messages(seen)
    last = systems[-1]
    assert "`csrf`" in last
    assert "ssrf" not in last


# --- the typed write schema teaches the declaration --------------------------


def test_the_hunter_spec_schema_teaches_the_skills_declaration():
    """The `specs` set write is typed (#236): each entry's `skills` property
    carries its contract into the model-facing schema, so the hunter learns the
    declaration from the tool itself."""
    from polymerhus.attack.hunting.hunter_tools import HuntsStoreArgs

    schema = HuntsStoreArgs.model_json_schema()
    defs = schema.get("$defs", {})
    candidates = [d.get("properties", {}) for d in defs.values()]
    skills = next((p["skills"] for p in candidates if "skills" in p), None)
    assert skills is not None, "the spec write payload must type `skills`"
    description = skills["description"].lower()
    assert "pod runner" in description or "flat skill" in description
