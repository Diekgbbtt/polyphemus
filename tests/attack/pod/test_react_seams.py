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
from polymerhus.attack.hunting.pod.prompts import (
    load_pod_triager_contract,
)
from polymerhus.attack.hunting.pod.context import (
    ExperimentLog,
    _dicts_to_lc,
)
from polymerhus.attack.hunting.pod.llm import (
    POD_RUNNER_ROLE,
    POD_TRIAGER_ROLE,
    PodHarnessContext,
    bind_pod_session,
    pod_harness,
)
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore, spec_identifier
from polymerhus.attack.hunting.pod.types import RunnerStep
from polymerhus.recon.domain.types import ExecResult

SPEC = {
    "target_identity": {"url": "http://soupmarket.shop/", "unit_id": "service:web:soupmarket"},
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "assumptions": ["network egress allowed"],
    "rationale": "reachability",
    "provenance": {"threat_id": "threat-1", "unit_id": "service:web:soupmarket",
                   "canonical_class": "IDOR", "web_vulnerability_class": "idor"},
}

SPEC_ID = spec_identifier("sqli", [{"axis": "technique", "value": "blind"}, {"axis": "payload-vector", "value": "boolean"}])

_OK = "<html>market</html>\n__POD_HTTP_STATUS__:200\n__POD_HTTP_TIME__:0.05"
_ABSENT = "not found\n__POD_HTTP_STATUS__:404\n__POD_HTTP_TIME__:0.02"


class _FakeModel(BaseChatModel):
    replies: list = []
    idx: dict = {}

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        import uuid

        i = self.idx.get("i", 0)
        self.idx["i"] = i + 1
        msg = self.replies[min(i, len(self.replies) - 1)]
        # A provider stamps a unique id on every response; a scripted fake
        # must too. `add_messages` stores the message object it is given and
        # mutates its id, so re-emitting the same script object on a RESUMED
        # thread would replace the earlier copy in place instead of appending
        # - the re-dispatch path would never see the fresh gate call.
        msg = msg.model_copy(deep=True, update={"id": f"fake-{i}-{uuid.uuid4().hex}"})
        return ChatResult(generations=[ChatGeneration(message=msg)])

    @property
    def _llm_type(self):
        return "fake"

    def bind_tools(self, tools, **kwargs):
        return self


def _factory(replies):
    def make(role_id):
        return _FakeModel(replies=list(replies), idx={})
    return make


def _role_factory(*, runner_replies, triager_replies):
    """A role-aware model factory with a SHARED per-role cursor: the pod's
    `_build_agent` builds a fresh model per turn, so the script position must
    survive across the harness's turns (the conversation state is the thread;
    the model identity is stateless)."""
    cursor = {"pod_runner": 0, "pod_triager": 0}

    def make(role_id):
        key = role_id if role_id in cursor else "pod_triager"
        script = runner_replies if key == "pod_runner" else triager_replies
        i = cursor[key]
        cursor[key] = i + 1
        return _FakeModel(replies=list(script), idx={"i": i})
    return make


TRIAGE_CONFIRM = [
    AIMessage(content="", tool_calls=[
        {"name": "submit_assessment", "args": {"symptom_confirmed": True,
                                               "runner_diverged": False,
                                               "clean": True,
                                               "note": "the marker is reflected"},
         "id": "a1"}]),
    # The closing turn's reply: the machine is done, so the model answers in
    # plain text and the thread never ends on a dangling gate call.
    AIMessage(content="the assessment is submitted; the pod terminates"),
]


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
        with bind_pod_session("run-x", "", SPEC_ID, role_id=POD_RUNNER_ROLE, harness=hc):
            return await default_runner_step_fn(spec, _dicts_to_lc(
                [{"role": "human", "content": delta}]), 0)
    return _drive()


# --- the production Runner seam: ONE ReAct turn per stretch --------------------

def test_runner_turn_performs_one_react_stretch_and_synthesizes_conclude(tmp_path):
    calls = []
    log = ExperimentLog()
    store = PodMemoryStore(tmp_path)
    spec_id = SPEC_ID
    hc = PodHarnessContext(exec_fn=_exec(_OK, calls=calls),
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


def test_runner_turn_binds_the_composed_address_thread_id_as_the_conversation(tmp_path):
    """The EXACT live failure surface: the production runner hands its typed
    `HuntSession` address to `arun_session_turn`, and the model built inside the turn
    must see the composed thread-id STRING as the ambient conversation (the
    opencode-go `x-opencode-session` value) - never the address object. A raw address
    failed the provider client's `default_headers` validation in live e2e and
    degraded every pod turn to `technical-infeasibility` (0 iterations)."""
    from polymerhus.app.llm.conversation import current_conversation_id
    from polymerhus.attack.hunting.pod.llm import pod_session_address

    seen: list = []
    base = _factory(REACT_EXEC_AND_CONCLUDE)

    def recording_factory(role_id):
        seen.append(current_conversation_id())
        return base(role_id)

    log = ExperimentLog()
    hc = PodHarnessContext(exec_fn=_exec(_OK), memory_store=PodMemoryStore(tmp_path),
                           spec_id=SPEC_ID, log=log, variant_ref="v0",
                           model_factory=recording_factory)
    step = _run(_drive_runner(SPEC, hc))

    expected = pod_session_address("run-x", "", SPEC_ID, role_id=POD_RUNNER_ROLE).thread_id
    assert step.action == "conclude"                  # the production turn ran at all
    assert seen, "the ReAct turn must build its model"
    assert all(isinstance(v, str) for v in seen), (
        f"the conversation must be the composed thread-id string, got {seen!r}")
    assert set(seen) == {expected}


def test_runner_turn_flags_an_empty_stretch_as_exhausted(tmp_path):
    # The runner concludes WITHOUT executing anything: the old empty-probe rule.
    log = ExperimentLog()
    store = PodMemoryStore(tmp_path)
    spec_id = SPEC_ID
    hc = PodHarnessContext(exec_fn=_exec(_OK), memory_store=store,
                           spec_id=spec_id, log=log, variant_ref="v0",
                           model_factory=_factory([AIMessage(content="nothing to probe")]))
    step = _run(_drive_runner(SPEC, hc))
    assert step.action == "conclude"
    assert step.exhausted is True
    assert len(log.raw_observations) == 0


def test_runner_turn_binds_note_on_the_same_agent(tmp_path):
    """D84-16/27: the runner's ONE turn binds exec + note on the SAME
    create_agent threat; the P3 note write is the runner's FINAL tool call
    (D84-17/19). The former `kb_retrieve` seam (surface B) is retired; the KB
    capability is the config-gated `query_lightrag` tool."""
    calls = []
    log = ExperimentLog()
    store = PodMemoryStore(tmp_path)
    spec_id = SPEC_ID
    replies = [
        AIMessage(content="", tool_calls=[
            {"name": "notes", "args": {"command": "write",
                                      "note_name": "experiment",
                                      "kind": "experiment_summary",
                                      "body": "the consolidated summary"},
             "id": "c2"}]),
        AIMessage(content="space exhausted; summary note written"),
    ]
    hc = PodHarnessContext(exec_fn=_exec(_OK, calls=calls),
                           memory_store=store, spec_id=spec_id, log=log,
                           variant_ref="v0", model_factory=_factory(replies))
    step = _run(_drive_runner(SPEC, hc))
    assert step.action == "conclude"
    # D84-35: the P3 experiment_summary sinks into the variant's log slice as
    # its terminal record - NOT into notes.yaml.
    from polymerhus.attack.hunting.pod.pod_memory import read_variant_summary
    assert read_variant_summary(store, spec_id, 0) == "the consolidated summary"
    assert store.read_notes(spec_id) == []


def test_runner_turn_hard_fails_without_a_bound_session():
    with pytest.raises(RuntimeError):
        _run(default_runner_step_fn(SPEC, [], 0))


def test_production_seams_are_async():
    assert inspect.iscoroutinefunction(default_runner_step_fn)
    assert inspect.iscoroutinefunction(default_triager_fn)


# --- the production Triager seam: note-reading stateful_turn -------------------

def _drive_triager(spec, hc, log, facts=None):
    from polymerhus.attack.hunting.pod.triage_state import TriageFacts

    async def _drive():
        with bind_pod_session("run-x", "", SPEC_ID, role_id="pod_triager", harness=hc):
            resolved = facts or TriageFacts(
                runner_failed=False, runner_exhausted=False,
                runner_terminated=None, variant_allowed=True,
                lap=1, thread_id="pod:triager:" + SPEC_ID)
            return await default_triager_fn(spec, None, log, resolved)
    return _drive()


def test_triager_seam_reads_the_note_and_returns_a_decision(tmp_path, monkeypatch):
    log = ExperimentLog()
    store = PodMemoryStore(tmp_path)
    spec_id = SPEC_ID
    # D84-35: the P3 summary is the variant log slice's terminal record.
    store.write_experiment_log(spec_id, 0, {"order": 0, "variant_ref": "v0",
                                            "raw_observations": [], "interpretations": [],
                                            "executed": []})
    store.write_variant_summary(spec_id, 0, "the verbatim consolidation")
    monkeypatch.setenv("LLM_POD_TRIAGER", "openrouter:some/model")
    # The v2 harness drives the gate calls: one ASSESS turn (negative, clean),
    # then one DECIDE turn (the honest space-exhausted terminal).
    hc = PodHarnessContext(exec_fn=_exec(_OK), memory_store=store,
                           spec_id=spec_id, log=log, variant_ref="v0",
                           model_factory=_role_factory(
                               runner_replies=[AIMessage(content="unused")],
                               triager_replies=[
                                   AIMessage(content="", tool_calls=[
                                       {"name": "submit_assessment", "id": "a1", "args": {
                                           "symptom_confirmed": False,
                                           "runner_diverged": False,
                                           "clean": True,
                                           "note": "third-party assessment"}}]),
                                   AIMessage(content="", tool_calls=[
                                       {"name": "submit_decision", "id": "d1", "args": {
                                           "action": "terminate",
                                           "verdict": "unsuccessful",
                                           "terminal_reason": "space-exhausted",
                                           "note": "third-party miner verdict"}}]),
                               ]))
    decision = _run(_drive_triager(SPEC, hc, log))
    assert decision["action"] == "terminate"
    assert decision["terminal_reason"] == "space-exhausted"
    assert decision["clean"] is True
    assert "third-party miner verdict" in decision["note"]
    assert decision["phase_path"] == "assess>decide>terminal"


def test_runner_turn_threads_the_pod_project_as_usage_scope(tmp_path, monkeypatch):
    from polymerhus.app.llm.session import SessionTurn
    from polymerhus.recon.domain.types import CaptureContext
    import polymerhus.app.llm.session as S

    seen = {}

    async def fake_arun(role, thread, messages, *, checkpointer, **kw):
        seen["usage_scope"] = kw.get("usage_scope")
        return SessionTurn(content="done", messages=[], thread_id="t")

    monkeypatch.setattr(S, "arun_session_turn", fake_arun)
    hc = PodHarnessContext(
        exec_fn=_exec(_OK), memory_store=PodMemoryStore(tmp_path), spec_id=SPEC_ID,
        log=ExperimentLog(), variant_ref="v0", model_factory=_factory([]),
        capture_context=CaptureContext(project_id="proj-1"))
    _run(_drive_runner(SPEC, hc))
    assert seen["usage_scope"] == "proj-1"


def test_triager_turn_threads_the_pod_project_as_usage_scope(tmp_path, monkeypatch):
    from polymerhus.app.llm.session import SessionTurn
    from polymerhus.recon.domain.types import CaptureContext
    import polymerhus.app.llm.session as S

    seen = {}

    async def fake_arun(role, thread, messages, *, checkpointer, **kw):
        seen["usage_scope"] = kw.get("usage_scope")
        seen["tags"] = kw.get("extra_tags")
        return SessionTurn(content="done", messages=[], thread_id="t")

    monkeypatch.setattr(S, "arun_session_turn", fake_arun)
    hc = PodHarnessContext(
        exec_fn=_exec(_OK), memory_store=PodMemoryStore(tmp_path), spec_id=SPEC_ID,
        log=ExperimentLog(), variant_ref="v0", model_factory=_factory([]),
        capture_context=CaptureContext(project_id="proj-1"))
    _run(_drive_triager(SPEC, hc, hc.log))
    assert seen["usage_scope"] == "proj-1"
    assert "lap:1" in seen["tags"]


def test_triager_seam_degrades_to_a_safe_terminal_on_failure(tmp_path):
    log = ExperimentLog()
    store = PodMemoryStore(tmp_path)
    spec_id = SPEC_ID

    def raising(role_id):
        raise RuntimeError("no model")

    hc = PodHarnessContext(exec_fn=_exec(_OK), memory_store=store,
                           spec_id=spec_id, log=log, variant_ref="v0",
                           model_factory=raising)
    decision = _run(_drive_triager(SPEC, hc, log))
    assert decision["action"] == "terminate"
    assert decision["verdict"] == "unsuccessful"
    assert "degraded" in decision["note"]


def test_triager_seam_propagates_a_provider_failure(tmp_path, monkeypatch):
    """#329: a provider failure is infrastructure, not a triager assessment -
    the production triager re-raises the typed `ProviderUnavailableError`
    instead of laundering a throttle into `no-symptom-evidence`."""
    import httpx
    import openai

    import polymerhus.app.llm.session as S
    from polymerhus.app.llm.provider_failure import ProviderUnavailableError

    async def provider_raising(role, thread, messages, **kw):
        request = httpx.Request("POST", "https://api.example.test/v1")
        raise openai.RateLimitError(
            "Rate limit exceeded", response=httpx.Response(429, request=request),
            body=None)

    monkeypatch.setattr(S, "arun_session_turn", provider_raising)
    hc = PodHarnessContext(exec_fn=_exec(_OK), memory_store=PodMemoryStore(tmp_path),
                           spec_id=SPEC_ID, log=ExperimentLog(), variant_ref="v0",
                           model_factory=_factory([]))

    with pytest.raises(ProviderUnavailableError):
        _run(_drive_triager(SPEC, hc, hc.log))


def _tool_recording_factory(replies, seen):
    """A model factory whose model records the tool names bound onto it (the
    `create_agent` -> `bind_tools` seam), so a turn's real tool surface is
    assertable without running a tool."""

    class _Recorder(_FakeModel):
        def bind_tools(self, tools, **kwargs):
            seen.extend(t.name for t in tools if t is not None)
            return self

    def make(role_id):
        return _Recorder(replies=list(replies), idx={})

    return make


def test_triager_turn_binds_its_react_tools_and_never_exec(tmp_path, monkeypatch):
    """The lifecycle v2 constant surface: the read-only triager tools plus the
    two gates ride EVERY step; exec stays off it. The surface rides the REQUEST
    (the OpenAI tool dicts), so the spy records `arun_session_turn`'s tools."""
    log = ExperimentLog()
    store = PodMemoryStore(tmp_path)
    store.write_experiment_log(SPEC_ID, 0, {"order": 0, "variant_ref": "v0",
                                            "raw_observations": [], "interpretations": [],
                                            "executed": []})
    store.write_variant_summary(SPEC_ID, 0, "the verbatim consolidation")
    monkeypatch.setenv("LLM_POD_TRIAGER", "openrouter:some/model")

    import polymerhus.app.llm.session as S
    seen = {}
    original = S.arun_session_turn

    async def spy(role, thread, messages, *, tools=None, **kw):
        seen["names"] = [t["function"]["name"] for t in (tools or [])]
        return await original(role, thread, messages, tools=tools, **kw)

    monkeypatch.setattr(S, "arun_session_turn", spy)
    hc = PodHarnessContext(
        exec_fn=_exec(_OK), memory_store=store, spec_id=SPEC_ID,
        log=log, variant_ref="v0",
        model_factory=_factory([]))
    _run(_drive_triager(SPEC, hc, log))
    # The read-only critic surface plus the two gates; exec stays off it.
    assert {"notes", "query_lightrag", "load_skill", "record_skill_lesson",
            "submit_assessment", "submit_decision"} <= set(seen["names"])
    assert "exec" not in seen["names"]   # the critic never touches the target
    assert "write_skill" not in seen["names"]


def test_runner_turn_binds_the_full_skill_surface(tmp_path):
    """#236: the pod runner binds the full `load_skill` plus
    `record_skill_lesson` (the lesson sub-phase's tool) alongside its react
    tools - the settled target-agent decision - and never `write_skill`."""
    log = ExperimentLog()
    store = PodMemoryStore(tmp_path)
    seen: list = []
    hc = PodHarnessContext(exec_fn=_exec(_OK), memory_store=store, spec_id=SPEC_ID,
                           log=log, variant_ref="v0",
                           model_factory=_tool_recording_factory(
                               [AIMessage(content="stretch concluded")], seen))

    _run(_drive_runner(SPEC, hc))

    assert {"exec", "notes", "load_skill", "record_skill_lesson"} <= set(seen)
    assert "write_skill" not in seen


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
    production lanes - the runner ReAct turn (exec + conclude), the lifecycle v2
    triage harness (the ASSESS gate call), the envelope - with the fake model
    factory standing in for the live model."""
    env = _run(arun_pod(
        SPEC, exec_fn=_exec(_OK), trace_fn=_no_trace,
        memory_store=PodMemoryStore(tmp_path), spec_id=SPEC_ID,
        model_factory=_role_factory(
            runner_replies=REACT_EXEC_AND_CONCLUDE,
            triager_replies=TRIAGE_CONFIRM)))
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"
    assert env["evidence"]["clean"] is True
    assert len(env["evidence"]["raw_observations"]) == 1
    assert env["evidence"]["iterations"] == 1
    # The walked phase chain is recorded on the interpretation.
    assert env["evidence"]["interpretations"][-1]["phase_path"]


BASELINE = "http_01J0000000000000000000000A"
REACT_REPLAY_AND_CONCLUDE = [
    AIMessage(content="", tool_calls=[
        {"name": "replay", "args": {"artifact_id": BASELINE}, "id": "c1"}]),
    AIMessage(content="baseline replayed; hand the observation to the critic"),
]


def test_production_runner_replays_the_spec_baseline(tmp_path):
    """S5 8.5: `provenance.baseline_ref` enables replay when present - the
    production runner's `replay` tool resolves the named artifact, records the
    observed status in the D6 log, and the symbolic fast path can confirm the
    symptom from it."""
    spec = {**SPEC,
            "verification_symptoms": ["HTTP 403 on GET /admin"],
            "provenance": {**SPEC["provenance"], "baseline_ref": BASELINE}}
    seen = []

    def replay_fn(project_id, artifact_id, overrides):
        seen.append((project_id, artifact_id, overrides))
        return {"status": 403, "artifact_id": "http_NEW"}

    env = _run(arun_pod(
        spec, exec_fn=_exec(_ABSENT), trace_fn=_no_trace,
        memory_store=PodMemoryStore(tmp_path), spec_id=SPEC_ID,
        project_id="proj-1", replay_fn=replay_fn,
        model_factory=_role_factory(
            runner_replies=REACT_REPLAY_AND_CONCLUDE,
            triager_replies=TRIAGE_CONFIRM)))
    assert seen == [("proj-1", BASELINE, {})]
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"
    obs = env["evidence"]["raw_observations"][0]
    assert obs["status"] == 403
    assert obs["http_artifact_refs"] == ["http_NEW"]


def test_production_pod_degrades_to_a_safe_terminal_without_model_env(tmp_path,
                                                                      monkeypatch):
    """D84-14: a direct pod run with NO model env configured hard-fails at the
    stateful seam and `arun_pod` degrades the run - never a silent symbolic
    fallback, never a raise into the caller."""
    monkeypatch.delenv("LLM_POD_RUNNER", raising=False)
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    env = _run(arun_pod(SPEC, exec_fn=_exec(_OK), trace_fn=_no_trace,
                        memory_store=PodMemoryStore(tmp_path), spec_id=SPEC_ID))
    assert env["verdict"] == "unsuccessful"


def test_production_runner_node_binds_the_harness_context(monkeypatch, tmp_path):
    """The graph's production runner node binds the run-scoped harness around the
    default seam call (spied by patching `graph.default_runner_step_fn`) - the
    memory key rides the #164 spec id (NO hash fallback, operator 2026-08-23),
    the variant_ref the current stretch."""
    seen = []
    root_spec = {"target_identity": {"url": "http://svc/", "unit_id": "svc"},
                 "verification_symptoms": ["reflects the marker"]}

    async def spy(spec, messages, tool_calls):
        seen.append(pod_harness())
        return RunnerStep(action="conclude", exhausted=True,
                          observation_note="empty stretch")

    monkeypatch.setattr(graph_mod, "default_runner_step_fn", spy)
    env = _run(arun_pod(root_spec, exec_fn=_exec(_ABSENT), trace_fn=_no_trace,
                        memory_store=PodMemoryStore(tmp_path), spec_id="sqli__blind__boolean"))
    assert env["verdict"] == "unsuccessful"
    assert seen and seen[0] is not None
    assert seen[0].spec_id == "sqli__blind__boolean"             # the #164 handoff keys memory
    assert seen[0].variant_ref == "v0"
    assert seen[0].log is not None

def _browser_tool():
    from langchain_core.tools import tool

    @tool
    def browser(command: str, input: str | None = None) -> str:
        """One browser command."""
        return "ok"

    return browser


def test_runner_turn_binds_the_one_browser_tool(tmp_path):
    log = ExperimentLog()
    store = PodMemoryStore(tmp_path)
    seen: list = []
    hc = PodHarnessContext(
        exec_fn=_exec(_OK), memory_store=store, spec_id=SPEC_ID,
        log=log, variant_ref="v0",
        browser_tool=_browser_tool(),
        model_factory=_tool_recording_factory(
            [AIMessage(content="stretch concluded")], seen))

    _run(_drive_runner(SPEC, hc))

    assert "browser" in seen


def test_triager_turn_binds_the_browser_tool(tmp_path, monkeypatch):
    log = ExperimentLog()
    store = PodMemoryStore(tmp_path)
    store.write_experiment_log(SPEC_ID, 0, {"order": 0, "variant_ref": "v0",
                                            "raw_observations": [], "interpretations": [],
                                            "executed": []})
    store.write_variant_summary(SPEC_ID, 0, "the verbatim consolidation")
    monkeypatch.setenv("LLM_POD_TRIAGER", "openrouter:some/model")
    import polymerhus.app.llm.session as S
    seen = {}
    original = S.arun_session_turn

    async def spy(role, thread, messages, *, tools=None, **kw):
        seen["names"] = [t["function"]["name"] for t in (tools or [])]
        return await original(role, thread, messages, tools=tools, **kw)

    monkeypatch.setattr(S, "arun_session_turn", spy)
    hc = PodHarnessContext(
        exec_fn=_exec(_OK), memory_store=store, spec_id=SPEC_ID,
        log=log, variant_ref="v0",
        browser_tool=_browser_tool(),
        model_factory=_factory([]))

    _run(_drive_triager(SPEC, hc, log))

    assert "browser" in seen["names"]
    assert "exec" not in seen["names"]
