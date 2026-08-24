"""Integration tier: the test-executor pod assertion catalogue C1-C15
(hunting-67-test-executor-pod-spec.md section 6.1, `docs/design/hunting-84-assertions.md`).

The contract predicates exercise the pod's EXTERNAL behaviour through its one
seam - `arun_pod(spec) -> {verdict, evidence}` (IA-3 in, IA-4 out, D84-15: the
async entry is the ONLY entry; the sync `run_pod` wrapper is gone) - with every
side-effecting collaborator injected: the terminal (`exec_fn`), the Runner
(`runner_step_fn`), the Critic (`triager_fn`), the KB, and the Langfuse trace
stub. Most predicates drive the symbolic Runner (`symbolic_runner_step_fn`) so no
live LLM is needed; C13-C15 (T7: the KB tool binding, the P3 note write/read, and
the tool-contract rejection codes) drive the PRODUCTION ReAct lane through
`model_factory` with a fake chat model - the same hermetic harness as the e2e E1
walkthrough. No live target, no downstream agent.

The repo runs pytest WITHOUT pytest-asyncio (pyproject has no `asyncio_mode`):
async entry points are driven to completion with `asyncio.run`, exactly like the
hunt-orchestrator graph tier's `_drive` helper.
Q3 reconciliation (operator-ratified 2026-08-04, landed 2026-08-06): the pod
emits the six-value `terminal_reason` vocabulary the parent's derivation reads.
C5's per-agent-spec wording "infeasibility-asserted" is the amended
`technical-infeasibility`; the expected values below are taken from the spec.
"""
import asyncio
import inspect

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from polymerhus.attack.hunting.pod import arun_pod
from polymerhus.attack.hunting.pod.agents import symbolic_runner_step_fn
from polymerhus.attack.hunting.pod.config import EXEC_TIMEOUT_S, MAX_POD_ITERS
from polymerhus.attack.hunting.pod.llm import POD_RUNNER_ROLE, POD_TRIAGER_ROLE
from polymerhus.attack.hunting.pod.note_tool import (
    NOTES_BAD_KIND,
    NOTES_EMPTY_BODY,
    PodNoteTool,
    note_tool_for,
)
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore, spec_identifier
from polymerhus.attack.hunting.pod.tools import (
    ExecSpec,
    ExecTool,
    KbRetrieveSpec,
    KbRetrieveTool,
)
from polymerhus.attack.hunting.pod.types import RunnerStep, TERMINAL_REASONS
from polymerhus.recon.domain.types import ExecResult

VALID_SPEC = {
    "target_identity": "service:web:soupmarket",
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "testing_pattern": "blind-boolean",
    "assumptions": ["network egress allowed"],
    "payload_vector_space": {"method": "GET", "path": "/"},
    "rationale": "reachability probe from H1",
    "interpretation_guidance": "a 200 with a non-empty body confirms the symptom",
}

# The #164 `<fault>_<strategy>` memory key the pod stores under (D84-34).
SPEC_ID = spec_identifier("sqli", "blind")

# A spec whose symptom the symbolic recogniser cannot decide, so the Critic runs.
SEMANTIC_SPEC = {**VALID_SPEC, "verification_symptoms": ["reflects the injected marker"]}


def _no_trace(_run_id):
    return []


def _run(coro):
    """Drive the pod's async entry to completion (repo convention: no
    pytest-asyncio; sync tests `asyncio.run` the coroutine)."""
    return asyncio.run(coro)


def _exec(stdout="", returncode=0, calls=None, assert_timeout=None):
    def fake(command, timeout_s):
        if assert_timeout is not None:
            assert timeout_s == assert_timeout       # the pod's fixed cap is passed down
        if calls is not None:
            calls.append(command)
        return ExecResult(stdout=stdout, stderr="", returncode=returncode, duration_ms=1)
    return fake


_OK = "<html>market</html>\n__POD_HTTP_STATUS__:200\n__POD_HTTP_TIME__:0.05"
_ABSENT = "not found\n__POD_HTTP_STATUS__:404\n__POD_HTTP_TIME__:0.02"


def _terminate(reason, *, clean=True, verdict="unsuccessful"):
    def triager(spec, obs, messages, log):
        return {"action": "terminate", "verdict": verdict,
                "terminal_reason": reason, "clean": clean}
    return triager


# --- D84-15: the async-first entry, sync wrapper gone --------------------------

def test_arun_pod_is_the_async_entry_and_run_pod_is_gone():
    assert inspect.iscoroutinefunction(arun_pod)   # Q7/D84-15: awaited natively
    import polymerhus.attack.hunting.pod as pod_mod
    assert not hasattr(pod_mod, "run_pod")          # the sync wrapper is DELETED


# --- C1 -----------------------------------------------------------------------

def test_init_rejects_invalid_spec():
    calls = []
    env = _run(arun_pod({"target_identity": "", "verification_symptoms": [],
                         "testing_pattern": "", "payload_vector_space": {}},
                        exec_fn=_exec(_OK, calls=calls),
                        runner_step_fn=symbolic_runner_step_fn, triager_fn=None,
                        trace_fn=_no_trace))
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["init_validation"]
    assert env["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert calls == []                               # executes no tool call


# --- C2 -----------------------------------------------------------------------

@pytest.mark.parametrize("scenario", ["confirmed", "absent", "infeasible", "invalid"])
def test_binary_terminal_invariant(scenario):
    if scenario == "confirmed":
        env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK),
                            runner_step_fn=symbolic_runner_step_fn, triager_fn=None,
                            trace_fn=_no_trace))
    elif scenario == "absent":
        env = _run(arun_pod(SEMANTIC_SPEC, exec_fn=_exec(_ABSENT),
                            runner_step_fn=symbolic_runner_step_fn,
                            triager_fn=_terminate("space-exhausted"), trace_fn=_no_trace))
    elif scenario == "infeasible":
        env = _run(arun_pod(VALID_SPEC, exec_fn=_exec("", returncode=7),
                            runner_step_fn=symbolic_runner_step_fn, triager_fn=None,
                            trace_fn=_no_trace))
    else:
        env = _run(arun_pod({"verification_symptoms": []}, exec_fn=_exec(_OK),
                            runner_step_fn=symbolic_runner_step_fn, trace_fn=_no_trace))
    assert env["verdict"] in ("successful", "unsuccessful")
    assert env["evidence"]["terminal_reason"] in TERMINAL_REASONS


# --- C3 -----------------------------------------------------------------------

def test_symptom_confirmed_lands_successful():
    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=None, trace_fn=_no_trace))
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"
    assert env["evidence"]["iterations"] >= 1
    assert env["evidence"]["raw_observations"] and env["evidence"]["interpretations"]


# --- C4 -----------------------------------------------------------------------

def test_space_exhausted_lands_unsuccessful():
    env = _run(arun_pod(SEMANTIC_SPEC, exec_fn=_exec(_ABSENT),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=_terminate("space-exhausted"), trace_fn=_no_trace))
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "space-exhausted"


# --- C5 -----------------------------------------------------------------------

def test_infeasibility_asserted_with_evidence():
    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec("", returncode=7),
                        runner_step_fn=symbolic_runner_step_fn, triager_fn=None,
                        trace_fn=_no_trace))
    assert env["verdict"] == "unsuccessful"
    # Q3-amended: the per-agent spec's `infeasibility-asserted` is this value.
    assert env["evidence"]["terminal_reason"] == "technical-infeasibility"
    assert env["evidence"]["raw_observations"]


# --- C6 -----------------------------------------------------------------------

def test_budget_timeout_lands_unsuccessful(monkeypatch):
    monkeypatch.setattr("polymerhus.attack.hunting.pod.graph.HUNT_POD_MAX_ITERS", 3)

    def triager(spec, obs, messages, log):
        return {"classification": "symptom-absent", "action": "variant",
                "declined_attribute": "testing_pattern", "variant_spec": dict(spec),
                "feedback": "keep searching"}

    env = _run(arun_pod(SEMANTIC_SPEC, exec_fn=_exec(_ABSENT),
                        runner_step_fn=symbolic_runner_step_fn, triager_fn=triager,
                        trace_fn=_no_trace))
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "budget-timeout"
    assert env["evidence"]["raw_observations"]


# --- C7 -----------------------------------------------------------------------

def test_non_zero_exit_retries_to_converge():
    calls = []

    def fake(command, timeout_s):
        calls.append(command)
        if len(calls) < MAX_POD_ITERS:
            return ExecResult(stdout="", stderr="boom", returncode=1, duration_ms=1)
        return ExecResult(stdout=_OK, stderr="", returncode=0, duration_ms=1)

    env = _run(arun_pod(VALID_SPEC, exec_fn=fake, runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=None, trace_fn=_no_trace))
    assert len(calls) == MAX_POD_ITERS               # converged at the cap
    assert env["verdict"] in ("successful", "unsuccessful")
    assert env["evidence"]["terminal_reason"] in TERMINAL_REASONS


# --- C8 -----------------------------------------------------------------------

def test_exec_timeout_enforced():
    calls = []
    env = _run(arun_pod(VALID_SPEC,
                        exec_fn=_exec("", returncode=124, calls=calls,
                                      assert_timeout=EXEC_TIMEOUT_S),
                        runner_step_fn=symbolic_runner_step_fn, triager_fn=None,
                        trace_fn=_no_trace))
    assert len(calls) == MAX_POD_ITERS               # bounded by the cap
    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] in TERMINAL_REASONS


# --- C9 -----------------------------------------------------------------------

def test_variant_derivation_with_provenance():
    decisions = iter([
        {"classification": "symptom-absent", "action": "variant",
         "declined_attribute": "payload_vector_space",
         "variant_spec": {**SEMANTIC_SPEC, "payload_vector_space": {"method": "GET", "path": "/api"}},
         "feedback": "decline the path into /api"},
        {"classification": "symptom-absent", "action": "terminate",
         "verdict": "unsuccessful", "terminal_reason": "no-symptom-evidence", "clean": False},
    ])

    def triager(spec, obs, messages, log):
        return next(decisions)

    env = _run(arun_pod(SEMANTIC_SPEC, exec_fn=_exec(_ABSENT),
                        runner_step_fn=symbolic_runner_step_fn, triager_fn=triager,
                        trace_fn=_no_trace))
    variants = env["evidence"]["variant_specs"]
    assert len(variants) == 2
    assert variants[1]["parent_ref"] == "v0"
    assert variants[1]["declined_attribute"] == "payload_vector_space"
    assert env["evidence"]["raw_observations"] and env["evidence"]["interpretations"]


# --- C10 ----------------------------------------------------------------------

def test_duplicate_probe_recorded_once():
    calls = []
    steps = iter([
        RunnerStep(action="tool_call", tool="exec", command="curl -k -sS https://t/"),
        RunnerStep(action="tool_call", tool="exec", command="curl -k -sS https://t/"),  # identical
        RunnerStep(action="conclude", observation_note="done"),
    ])

    def runner(spec, messages, tool_calls):
        return next(steps)

    env = _run(arun_pod(SEMANTIC_SPEC, exec_fn=_exec(_ABSENT, calls=calls),
                        runner_step_fn=runner,
                        triager_fn=_terminate("space-exhausted"), trace_fn=_no_trace))
    assert len(calls) == 1                           # exactly one execution
    assert env["verdict"] in ("successful", "unsuccessful")


# --- C11 ----------------------------------------------------------------------

def test_empty_payload_vector_still_probes():
    calls = []
    env = _run(arun_pod({**VALID_SPEC, "payload_vector_space": {}},
                        exec_fn=_exec(_OK, calls=calls),
                        runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=None, trace_fn=_no_trace))
    assert len(calls) == 1                           # the default probe still ran
    assert env["evidence"]["raw_observations"]


# --- C12 ----------------------------------------------------------------------

def test_langfuse_failure_is_fail_open():
    def raising_trace(_run_id):
        raise RuntimeError("langfuse stub exploded")

    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=None, trace_fn=raising_trace))
    assert env["verdict"] == "successful"
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"


# --- the production-lane harness (C13-C15: T7's ReAct lane) -------------------

class _FakeModel(BaseChatModel):
    """The scripted chat model (the e2e E1 / react-seams pattern): `_generate`
    replays `replies` one per model step (the last repeats), `bind_tools` is a
    passthrough so no real tool binding resolves - the ReAct loop is
    deterministic, no live LLM."""

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
    `arun_session_turn` builds a fresh agent on a fresh instance, so the scripts
    are role-scoped, never cross-thread."""

    def make(role_id):
        replies = by_role.get(role_id) or [AIMessage(content="done")]
        return _FakeModel(replies=list(replies), idx={})

    return make


def _kb_empty(calls=None):
    def fake(query, *, fault_id="", technological_axis=()):
        if calls is not None:
            calls.append(query)
        return {"symptoms": [], "techniques": [], "source": None}
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


# The triager's production turn terminating `{unsuccessful, space-exhausted}`.
_TRIAGER_ABSENT = [
    AIMessage(content="", tool_calls=[{"name": "TriagerDecision", "id": "c9", "args": {
        "classification": "symptom-absent", "action": "terminate",
        "verdict": "unsuccessful", "terminal_reason": "space-exhausted", "clean": True,
        "note": "third-party miner: no symptom is established across the probe space"}}]),
]


# --- C13 - KB tool bound on the Runner (D84-16/26) ------------------------------

def test_kb_retrieve_bound_and_fails_open(tmp_path):
    """The production Runner's `create_agent` binds `kb_retrieve` - the KB wiring
    hole is closed. The ReAct script issues exactly one `kb_retrieve` call, the
    empty result fails open (O13: degrade to the spec's primitives), and the pod
    lands a binary end with the KB call recorded once."""
    exec_calls = []
    kb_calls = []
    runner_script = [
        AIMessage(content="", tool_calls=[
            {"name": "kb_retrieve", "args": {"query": "csrf patterns on form posts"},
             "id": "c0"}]),
        AIMessage(content="", tool_calls=[
            {"name": "exec", "args": {"command": "curl -k -sS https://t/"}, "id": "c1"}]),
        AIMessage(content="concluded; the observation grounds the verdict"),
    ]
    env = _run(arun_pod(
        VALID_SPEC, exec_fn=_exec(_OK, calls=exec_calls), kb_fn=_kb_empty(kb_calls),
        trace_fn=_no_trace, memory_store=PodMemoryStore(tmp_path), spec_id=SPEC_ID,
        model_factory=_factory({POD_RUNNER_ROLE: runner_script})))

    assert len(kb_calls) == 1                       # the binding was EXERCISED
    assert kb_calls[0] == "csrf patterns on form posts"
    assert len(exec_calls) == 1
    assert env["verdict"] == "successful"           # fail-open: the empty KB degraded
    assert env["evidence"]["terminal_reason"] == "symptom-confirmed"


# --- C14 - the P3 note written and read by the triager (D84-17/19/23) -----------

def test_note_written_on_p3_and_read_by_triager(tmp_path, monkeypatch):
    """On P3 space exhaustion the production Runner writes the ONE consolidated
    `experiment_summary` as its FINAL tool call (D84-17/19); it lands as the
    TERMINAL RECORD of the variant's experiment-log slice (D84-35) - NOT in
    notes.yaml - and the Triager's production note-reading turn terminates
    `{unsuccessful, space-exhausted}` (D84-23, C14/H6)."""
    _negotiation_for_pod_triager(monkeypatch)
    exec_calls = []
    store = PodMemoryStore(tmp_path)
    runner_script = [
        AIMessage(content="", tool_calls=[
            {"name": "kb_retrieve", "args": {"query": "csrf patterns on form posts"},
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
        AIMessage(content="space exhausted; the consolidated summary was written"),
    ]
    env = _run(arun_pod(
        VALID_SPEC, exec_fn=_exec(_ABSENT, calls=exec_calls), kb_fn=_kb_empty(),
        trace_fn=_no_trace, memory_store=store, spec_id=SPEC_ID,
        model_factory=_factory({POD_RUNNER_ROLE: runner_script,
                                POD_TRIAGER_ROLE: _TRIAGER_ABSENT})))

    assert env["verdict"] == "unsuccessful"
    assert env["evidence"]["terminal_reason"] == "space-exhausted"
    assert env["evidence"]["clean"] is True
    assert len(exec_calls) == 1

    # C14 re-scoped (T2): the summary is the terminal record of the variant's
    # experiment-log slice - the store's notes.yaml holds NO summary.
    from polymerhus.attack.hunting.pod.pod_memory import read_variant_summary
    slice = store.read_experiment_log(SPEC_ID, 0)
    assert slice["experiment_summary"] == (
        "the default probe returned HTTP 404 with an empty body; no kb "
        "primitive differs from the initial set")
    assert read_variant_summary(store, SPEC_ID, 0) == slice["experiment_summary"]
    assert "404" in slice["experiment_summary"]
    assert store.read_notes(SPEC_ID) == []


# --- T2 round-trip: the D6 log + executed ledger persist per variant ------------

def test_experiment_log_persists_round_trip_and_survives_a_rerun(tmp_path):
    """T2 (D84-38): an `arun_pod` pass with a bound store leaves its full D6
    slice + `executed` ledger + the minted variant on disk per (spec, order),
    reads back byte-equivalent, and a SECOND pass over the same (spec, order)
    REWRITES the file idempotently (D84-37) - no unbounded accumulation."""
    store = PodMemoryStore(tmp_path)
    env = _run(arun_pod(VALID_SPEC, exec_fn=_exec(_OK), runner_step_fn=symbolic_runner_step_fn,
                        triager_fn=None, trace_fn=_no_trace, memory_store=store,
                        spec_id=SPEC_ID))
    assert env["verdict"] == "successful"

    # The deterministic stages persisted the variant + the D6 slice.
    variant = store.read_variant(SPEC_ID, "v0")
    assert variant["ref"] == "v0"
    assert variant["spec"]["target_identity"] == VALID_SPEC["target_identity"]
    slice = store.read_experiment_log(SPEC_ID, 0)
    assert slice["variant_ref"] == "v0"
    assert len(slice["raw_observations"]) == len(env["evidence"]["raw_observations"]) >= 1
    assert slice["raw_observations"][0]["status"] == 200
    assert len(slice["interpretations"]) == len(env["evidence"]["interpretations"]) >= 1
    # The executed ledger persisted (the raw observation's probe_ref IS the sig).
    assert slice["executed"] and slice["executed"][0] == slice["raw_observations"][0]["probe_ref"]

    # A second pass over the same (spec, order) overwrites idempotently: the
    # file is the current truth, never an accumulation. A PRIOR run's terminal
    # summary is cleared at the new run's start (D84-37), so a run that does
    # not reach P3 does not carry a stale consolidation.
    store.write_variant_summary(SPEC_ID, 0, "stale summary from a prior run")
    env2 = _run(arun_pod(SEMANTIC_SPEC, exec_fn=_exec(_ABSENT),
                         runner_step_fn=symbolic_runner_step_fn,
                         triager_fn=_terminate("space-exhausted"), trace_fn=_no_trace,
                         memory_store=store, spec_id=SPEC_ID))
    assert env2["verdict"] == "unsuccessful"
    slice2 = store.read_experiment_log(SPEC_ID, 0)
    assert len(slice2["raw_observations"]) == 1          # overwritten, not stacked
    assert slice2["raw_observations"][0]["status"] == 404
    assert "experiment_summary" not in slice2            # no stale summary rides a re-run
    assert len(list((store._root / SPEC_ID / "experiment-log").iterdir())) == 1


def test_minted_variant_persists_to_its_variants_file(tmp_path):
    """T2 (D84-38): the mint_variant deterministic stage records the derived
    variant INTO the store - `variants/v1.yaml` lands beside v0's, one file per
    variant ref, overwritten idempotently (D84-37)."""
    decisions = iter([
        {"classification": "symptom-absent", "action": "variant",
         "declined_attribute": "testing_pattern",
         "variant_spec": {**SEMANTIC_SPEC, "testing_pattern": "blind-differential"},
         "feedback": "try the differential pattern"},
        {"classification": "symptom-absent", "action": "terminate",
         "verdict": "unsuccessful", "terminal_reason": "no-symptom-evidence",
         "clean": False},
    ])

    def triager(spec, obs, messages, log):
        return next(decisions)

    store = PodMemoryStore(tmp_path)
    env = _run(arun_pod(SEMANTIC_SPEC, exec_fn=_exec(_ABSENT),
                        runner_step_fn=symbolic_runner_step_fn, triager_fn=triager,
                        trace_fn=_no_trace, memory_store=store, spec_id=SPEC_ID))
    assert env["verdict"] == "unsuccessful"
    v0 = store.read_variant(SPEC_ID, "v0")
    v1 = store.read_variant(SPEC_ID, "v1")
    assert v0["ref"] == "v0" and v1["ref"] == "v1"
    assert v1["parent_ref"] == "v0"
    assert v1["declined_attribute"] == "testing_pattern"
    assert store.list_variant_refs(SPEC_ID) == ["v0", "v1"]
    # Both orders' log slices exist: order 1's slice holds v1's interpretation.
    slice1 = store.read_experiment_log(SPEC_ID, 1)
    assert slice1["variant_ref"] == "v1"
    assert slice1["interpretations"] and slice1["interpretations"][0]["variant"] == "v1"


# --- C15 - tool-contract validation (D84-22, extra="forbid") --------------------

def test_tool_contract_rejects_foreign_params(tmp_path):
    """A `note` write carrying a parameter outside `NoteToolSpec` is REJECTED by
    the args schema (`extra="forbid"`, D84-22) - a ValueError at the schema
    boundary - and `_run` provably never executes. The harness does not
    re-validate: the tool's OWN contract is the validator."""
    store = PodMemoryStore(tmp_path)
    calls = []

    class SpyTool(PodNoteTool):
        def _run(self, **kwargs):
            calls.append(kwargs)
            return super()._run(**kwargs)

    tool = SpyTool(store=store, spec_id="spec-x")
    with pytest.raises(ValueError):
        tool.invoke({"operation": "write", "order": 0,
                     "note_name": "x", "kind": "experiment_summary",
                     "body": "consolidation", "surprise_field": "oops"})
    assert calls == []                              # never reached _run


def test_tool_contract_coded_rejections(tmp_path):
    """The tool-contract coded rejections (D84-22) fire for the semantics only
    the run can judge: an empty write body and an unknown kind are returned as
    coded rejections, never executed, never persisted."""
    store = PodMemoryStore(tmp_path)
    tool = note_tool_for(store, "spec-x")
    empty = tool.invoke({"operation": "write", "kind": "experiment_summary",
                         "note_name": "x", "body": "   "})
    assert empty.startswith(NOTES_EMPTY_BODY)
    bad = tool.invoke({"operation": "write", "kind": "not-a-kind",
                       "note_name": "x", "body": "body"})
    assert bad.startswith(NOTES_BAD_KIND)
    assert store.read_notes("spec-x") == []         # nothing rejected persisted


def test_exec_and_kb_contracts_are_typed():
    """`exec` and `kb_retrieve` carry the typed `extra="forbid"` schemas: a
    foreign parameter is rejected at the schema boundary (D84-22), and the pod's
    caps are never model-chosen fields."""
    spec = ExecSpec(command="curl -k https://t/")
    assert spec.command == "curl -k https://t/"
    assert ExecSpec.model_config.get("extra") == "forbid"
    assert KbRetrieveSpec.model_config.get("extra") == "forbid"
    assert "command" not in KbRetrieveSpec.model_fields