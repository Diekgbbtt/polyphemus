"""E1 e2e walkthrough for the test-executor pod (spec section 6.2, D84-5/24).

E1 is a REAL pod run via `arun_pod` with the PRODUCTION lane: the compiled
production graph (no `tool_exec` node - D84-29), the production ReAct Runner
seam (ONE `create_agent` turn per stretch with `tools=[exec, note,
query_lightrag, graph_view]`), the symbolic fast path, and the terminals. It
exercises the ReAct runner, the KB tool binding (D84-16/26, always-bound
`query_lightrag` as of #197 - fail-open to a degraded bundle in this hermetic
env, O13), and the `exec` tool against a HERMETIC, deterministic substrate: the
live LLM is a scripted `BaseChatModel` fake injected through the `model_factory`
seam (the established fake-model / ToolStrategy pattern -
`tests/attack/pod/test_react_seams.py`), the terminal is a fake `exec_fn`
returning a fixed synthetic curl trailer (`__POD_HTTP_STATUS__` /
`__POD_HTTP_TIME__` markers). No live network target, no live LLM, no docker,
no neo4j.

The spec's E1 live edge (`soupmarket.shop` in `eval-targets.yaml`, live HTTP
mode) is mechanised by the fixed synthetic observation: the runner still issues
the symbolic default probe (O12/C11) through the ReAct lane, and the E1 symptom
("HTTP 200 with a non-empty body on GET /") is SYMBOLICALLY decidable, so the
symbolic symptom recogniser terminates the trivial run with no LLM (spec 2:
"the E1 walkthrough symptom is symbolically decidable, so the trivial real run
needs no live LLM"). The drop-to-fake-model is exactly the ticket's mandate
(#158): "inject the production lane but with a FAKE model, a fake `exec_fn`,
and a fake/empty KB tool".

Assertion catalogue (bounded, spec 6.2 E1 + H1/H2):

  E1/1 symptom-confirmed - the spec's verification symptom appears in the
      synthetic observation: `{successful, symptom-confirmed, iterations >= 1}`
      with an experiment log holding the variant spec, the raw observation, and
      the interpretation (H1, D6 provenance), and the response status read back
      from the tool-call log.
  E1/2 space-exhausted  - the symptom never appears across the probe space:
      `{unsuccessful, space-exhausted}` (clean trail), ONE consolidated
      `experiment_summary` note written to the pod experiment-memory store as
      the runner's FINAL tool call (H2/C14), and the Triager's production
      note-reading turn lands the terminal (D84-23).

The full-pipeline chain walkthroughs (E2-E4, orchestrator -> hunter -> pod) are
OUT OF SCOPE (2026-08-22): the operator narrowed this workstream to the
test-executor pod alone, so those skeletons are REMOVED. The holistic pod e2e
over the in-network stack (E5-E8, sibling container + juice-shop spec fixtures)
and the NFR scorer live in the sibling test modules.
"""
from __future__ import annotations

import asyncio

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from polymerhus.attack.hunting.pod import arun_pod
from polymerhus.attack.hunting.pod.llm import POD_RUNNER_ROLE, POD_TRIAGER_ROLE
from polymerhus.attack.hunting.pod.pod_memory import (
    PodMemoryStore,
    spec_identifier,
)
from polymerhus.recon.domain.types import ExecResult

# The E1 spec fixture (spec 6.2 E1 input, mirroring the contract tier's
# VALID_SPEC): target identity "service:web:soupmarket", verification symptom
# "HTTP 200 with a non-empty body on GET /", testing pattern "blind-boolean",
# assumptions ["network egress allowed"], payload vector space {method: GET,
# path: "/"}.
VALID_SPEC = {
    "target_identity": {"url": "http://soupmarket.shop/", "unit_id": "service:web:soupmarket"},
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "testing_pattern": "blind-boolean",
    "assumptions": ["network egress allowed"],
    "payload_vector_space": {"method": "GET", "path": "/"},
    "rationale": "reachability probe from H1",
    "interpretation_guidance": "a 200 with a non-empty body confirms the symptom",
}

# The #164 `<fault>_<strategy>` memory key the pod stores under (D84-34).
SPEC_ID = spec_identifier("sqli", "blind")

# The fixed synthetic curl trailers (tools.py `parse_curl` reads the markers).
_OK = "<html>market</html>\n__POD_HTTP_STATUS__:200\n__POD_HTTP_TIME__:0.05"
_ABSENT = "not found\n__POD_HTTP_STATUS__:404\n__POD_HTTP_TIME__:0.02"


class _FakeModel(BaseChatModel):
    """The scripted chat model (the repo's established fake-model pattern -
    `tests/attack/pod/test_react_seams.py`): `_generate` replays its `replies`
    one per model step (the last reply repeats), `bind_tools` is a passthrough
    so no real tool binding resolves, and the whole ReAct loop is deterministic."""

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


def _factory(by_role):
    """A `model_factory(role_id) -> model` walking `by_role[role_id]`; each
    `arun_session_turn` builds a fresh agent on a fresh instance (one stretch /
    one triager turn), so the scripts are role-scoped, never cross-thread."""

    def make(role_id):
        replies = by_role.get(role_id) or [AIMessage(content="done")]
        return _FakeModel(replies=list(replies), idx={})

    return make


# --- the runner's ReAct scripts (one `create_agent` loop per stretch) ---------

# P1 kb query (concretization, D84-16/26), P2 default probe, then conclude: the
# KB tool binding is EXERCISED (a degraded/empty bundle -> degrade to the spec's
# own primitives, O13 - the always-bound `query_lightrag` tool fails open in this
# hermetic env) and the symbolic recogniser reads the 200 trailer.
_REACT_KB_EXEC_CONCLUDE = [
    AIMessage(content="", tool_calls=[
        {"name": "query_lightrag", "args": {"scenario_id": "SIM-01",
                                            "attack_goal": "identify a bounded comparison hypothesis",
                                            "concern": "csrf patterns on form posts"},
         "id": "c0"}]),
    AIMessage(content="", tool_calls=[
        {"name": "exec", "args": {"command": "curl -k -sS https://t/"}, "id": "c1"}]),
    AIMessage(content="stretch concluded; the observation grounds the verdict"),
]

# P3 space exhaustion: the kb query returns nothing new, the default probe
# returns a 404 (symptom absent), and the runner writes the ONE consolidated
# experiment_summary note as its FINAL tool call (D84-17/19), then concludes.
_REACT_KB_EXEC_NOTE_CONCLUDE = [
    AIMessage(content="", tool_calls=[
        {"name": "query_lightrag", "args": {"scenario_id": "SIM-01",
                                            "attack_goal": "identify a bounded comparison hypothesis",
                                            "concern": "csrf patterns on form posts"},
         "id": "c0"}]),
    AIMessage(content="", tool_calls=[
        {"name": "exec", "args": {"command": "curl -k -sS https://t/"}, "id": "c1"}]),
    AIMessage(content="", tool_calls=[
        {"name": "note", "args": {"operation": "write", "order": 0,
                                  "note_name": "experiment",
                                  "kind": "experiment_summary",
                                  "body": "the default probe returned HTTP 404 "
                                          "with an empty body; no kb primitive "
                                          "differs from the initial set"},
         "id": "c2"}]),
    AIMessage(content="probe space exhausted; the consolidated summary was written"),
]

# The Triager's production turn (D84-23): a `ToolStrategy(TriagerDecision)`
# structured call terminating the run with `{unsuccessful, space-exhausted}`.
_TRIAGER_ABSENT = [
    AIMessage(content="", tool_calls=[{"name": "TriagerDecision", "id": "c9", "args": {
        "classification": "symptom-absent", "action": "terminate",
        "verdict": "unsuccessful", "terminal_reason": "space-exhausted", "clean": True,
        "note": "third-party miner: the default probe returned 404 and no symptom "
                "is established across the probe space"}}]),
]


def _exec(stdout=_OK, returncode=0, calls=None):
    def fake(command, timeout_s):
        if calls is not None:
            calls.append(command)
        return ExecResult(stdout=stdout, stderr="", returncode=returncode, duration_ms=1)
    return fake


def _negotiation_for_pod_triager(monkeypatch):
    """Thread the #99 negotiation seam for a hermetic pod-triager schema turn
    (#147): the no-tools `stateful_turn(schema=TriagerDecision)` resolves the
    role's env model key + capability profile. Point it at a tool-calling-only
    profile so the fake's TriagerDecision tool_calls become the structured
    output (ToolStrategy) instead of an unmet json_schema probe."""
    monkeypatch.setenv("LLM_MODEL_POD_TRIAGER", "openrouter:some/model")
    import polymerhus.app.llm.session as S

    monkeypatch.setattr(
        S, "resolve_capability",
        lambda provider, model: type("_P", (), {
            "supports_structured_output": False, "supports_tool_calling": True})())


def _no_trace(_run_id):
    return []


def _run(coro):
    """Drive the pod's async entry to completion (repo convention: no
    pytest-asyncio; sync tests `asyncio.run` the coroutine)."""
    return asyncio.run(coro)


# --- E1/1: symptom-confirmed (spec 6.2 E1, H1) --------------------------------

def test_trivial_real_run(tmp_path):
    """The trivial real run: the production lane - fake model, fake exec (the
    fixed 200 trailer), fail-open KB (the always-bound `query_lightrag` tool
    degrades in this hermetic env, O13) - lands exactly one verdict
    `{successful, symptom-confirmed, iterations >= 1}` with an experiment log
    holding the variant spec, the raw observation (status read back from the
    tool-call log), the KB observation, and the interpretation (D6)."""
    exec_calls = []
    store = PodMemoryStore(tmp_path)
    env = _run(arun_pod(
        VALID_SPEC, exec_fn=_exec(_OK, calls=exec_calls),
        trace_fn=_no_trace, memory_store=store, spec_id=SPEC_ID,
        model_factory=_factory({POD_RUNNER_ROLE: _REACT_KB_EXEC_CONCLUDE})))

    # E1 terminal: exactly one verdict + the experiment log.
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"
    assert env["evidence"]["iterations"] >= 1
    assert env["evidence"]["clean"] is True

    # The KB tool binding ran end-to-end (D84-16; a degraded bundle was
    # recorded as a first-class KbObservation, T3/#179) and the default probe
    # was executed exactly once through the ReAct runners exec tool.
    slice = store.read_experiment_log(SPEC_ID, 0)
    assert len(slice["kb_observations"]) == 1
    assert slice["kb_observations"][0]["query"] == "csrf patterns on form posts"
    assert len(exec_calls) == 1

    # The experiment log (D6): the v0 variant spec, at least one raw
    # observation with the status read back from the tool-call log (spec E1
    # "Observed"), and the triager's interpretation.
    assert env["evidence"]["variant_specs"][0]["ref"] == "v0"
    assert len(env["evidence"]["raw_observations"]) >= 1
    obs = env["evidence"]["raw_observations"][0]
    assert obs["status"] == 200
    assert (obs["body"] or "").strip()
    assert len(env["evidence"]["interpretations"]) >= 1
    assert env["evidence"]["interpretations"][0]["classification"] == "symptom-confirmed"


# --- E1/2: space-exhausted (spec 2 H2, C14) -----------------------------------

def test_space_exhausted_run_writes_the_p3_note(tmp_path, monkeypatch):
    """The runner concludes with no symptom in the probe space, writes the ONE
    consolidated `experiment_summary` P3 note as its FINAL tool call, and the
    Triager's production note-reading turn terminates `{unsuccessful,
    space-exhausted}` with a clean trail."""
    _negotiation_for_pod_triager(monkeypatch)
    exec_calls = []
    store = PodMemoryStore(tmp_path)
    env = _run(arun_pod(
        VALID_SPEC, exec_fn=_exec(_ABSENT, calls=exec_calls),
        trace_fn=_no_trace, memory_store=store, spec_id=SPEC_ID,
        model_factory=_factory({POD_RUNNER_ROLE: _REACT_KB_EXEC_NOTE_CONCLUDE,
                                POD_TRIAGER_ROLE: _TRIAGER_ABSENT})))

    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "space-exhausted"
    assert env["evidence"]["clean"] is True
    assert len(exec_calls) == 1
    assert len(env["evidence"]["raw_observations"]) == 1
    assert env["evidence"]["raw_observations"][0]["status"] == 404
    # The triager's production stateful turn ran (its note rides the
    # interpretation) - not a symbolic fast path.
    assert "third-party miner" in env["evidence"]["interpretations"][0]["note"]

    # C14/H6 (T2 re-scoped): the ONE consolidated experiment-summary lands as
    # the TERMINAL RECORD of the variant's experiment-log slice - keyed by the
    # spec id + variant order - NOT in notes.yaml (kb_insight/freeform only).
    from polymerhus.attack.hunting.pod.pod_memory import read_variant_summary
    slice = store.read_experiment_log(SPEC_ID, 0)
    assert slice["experiment_summary"] == (
        "the default probe returned HTTP 404 with an empty body; no kb "
        "primitive differs from the initial set")
    assert slice["variant_ref"] == "v0"
    assert read_variant_summary(store, SPEC_ID, 0) == slice["experiment_summary"]
    assert "404" in slice["experiment_summary"]
    assert store.read_notes(SPEC_ID) == []


# --- E2-E4 are OUT OF SCOPE (2026-08-22): the full-pipeline chain walkthroughs
# (orchestrator -> hunter -> pod) and any other single-component testing are
# removed per the operator's scope narrowing. The holistic pod e2e (E5-E8, the
# sibling-container in-network stack + juice-shop spec fixtures) lives in
# test_pod_e2e_holistic.py and the NFR scorer in test_pod_e2e_nfr.py.