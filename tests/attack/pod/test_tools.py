"""Unit tier: T7 (#157) - the pod's bound-tool surface (D84-16/22/26/27).

The ReAct Runner binds `tools=[exec, kb_retrieve, note]` (D84-27); this tier
proves the KB wiring hole is closed (D84-16) - `kb_retrieve` is a `BaseTool`
bound on the runner's `tools=` list, with a typed `extra="forbid"` args schema
and fail-open semantics (O13: an empty or failing KB degrades the runner to the
spec's own primitives, never raises) - and that the `exec` tool stays the
raw-recording terminal (G4) with retry and dedup-marking. Hermetic: fake
terminal, no live KB, no live LLM.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from polymerhus.attack.hunting.pod.agents import runner_react_tools, triager_react_tools
from polymerhus.attack.hunting.pod.config import EXEC_TIMEOUT_S, MAX_POD_ITERS
from polymerhus.attack.hunting.pod.context import ExperimentLog
from polymerhus.attack.hunting.pod.note_tool import PodNoteTool
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore, spec_identifier
from polymerhus.attack.hunting.pod.tools import (
    ExecSpec,
    ExecTool,
    KbRetrieveSpec,
    KbRetrieveTool,
    kb_retrieve,
)
from polymerhus.recon.domain.types import ExecResult

SPEC_ID = spec_identifier("sqli", "blind")


SPEC = {
    "target_identity": "service:web:soupmarket",
    "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
    "payload_vector_space": {"method": "GET", "path": "/"},
}

_OK = "<html>market</html>\n__POD_HTTP_STATUS__:200\n__POD_HTTP_TIME__:0.05"


def _exec(stdout=_OK, returncode=0, calls=None):
    def fake(command, timeout_s):
        if calls is not None:
            calls.append(command)
        return ExecResult(stdout=stdout, stderr="", returncode=returncode, duration_ms=1)
    return fake


# --- the KB wiring hole is closed (D84-16): kb_retrieve is bound on the Runner -

def test_runner_binds_kb_retrieve_as_a_bound_tool(tmp_path):
    """The Runner's ReAct `tools=` list carries a `kb_retrieve` BaseTool (the
    D84-16 defect: the KB existed in the prompt text but was never bound)."""
    tools = runner_react_tools(exec_fn=_exec(), memory_store=PodMemoryStore(tmp_path),
                               spec_id=SPEC_ID, log=ExperimentLog(),
                               variant_ref="v0")
    names = {t.name for t in tools}
    assert {"exec", "kb_retrieve", "note"} <= names
    kb = next(t for t in tools if t.name == "kb_retrieve")
    assert isinstance(kb, KbRetrieveTool)


def test_triager_binds_note_and_kb_and_no_exec(tmp_path):
    tools = triager_react_tools(PodMemoryStore(tmp_path), SPEC_ID)
    names = {t.name for t in tools}
    assert {"note", "kb_retrieve"} <= names
    assert "exec" not in names


def test_runner_tools_are_injective_constructed_per_stretch(tmp_path):
    log = ExperimentLog()
    store = PodMemoryStore(tmp_path)
    spec_id = SPEC_ID
    tools_v0 = runner_react_tools(_exec(), store, spec_id, log, "v0")
    tools_v1 = runner_react_tools(_exec(), store, spec_id, log, "v1")
    exec_v0 = next(t for t in tools_v0 if t.name == "exec")
    exec_v1 = next(t for t in tools_v1 if t.name == "exec")
    assert exec_v0 is not exec_v1                     # per-stretch instances
    sig0 = exec_v0._signature("curl -k -sS /")        # variant-sensitive keys
    sig1 = exec_v1._signature("curl -k -sS /")
    assert sig0 != sig1


def test_kb_retrieve_tool_has_a_typed_contract_and_forbids_extras():
    kb = KbRetrieveTool()
    with pytest.raises(ValidationError):
        kb.invoke({"query": "x", "bogus": 1})
    out = kb.invoke({"query": "csrf on search"})
    assert isinstance(out, str)
    parsed = json.loads(out)
    assert set(parsed) == {"symptoms", "techniques", "source"}
    assert parsed["symptoms"] == []                   # dormant KB: fail-open empty


def test_kb_retrieve_uses_the_injected_lookup_when_given():
    def lookup(query):
        return {"symptoms": ("s1",), "techniques": ("t1",), "source": "fixture"}

    from polymerhus.attack.hunting import symptom_kb as SK

    def fake_lookup(q):
        return SK.SymptomTechniqueResult(symptoms=("s1",), techniques=("t1",),
                                         source="fixture")

    kb = KbRetrieveTool(lookup=fake_lookup)
    parsed = json.loads(kb.invoke({"query": "CSRF", "fault_id": "CWE-352",
                                   "technological_axis": ["web"]}))
    assert parsed["symptoms"] == ["s1"]
    assert parsed["techniques"] == ["t1"]
    assert parsed["source"] == "fixture"


def test_kb_retrieve_raising_lookup_fails_open():
    def boom(query):
        raise RuntimeError("kb down")

    kb = KbRetrieveTool(lookup=boom)
    parsed = json.loads(kb.invoke({"query": "x"}))
    assert parsed == {"symptoms": [], "techniques": [], "source": None}


# --- T3 (#179): the KB-retrieve response is recorded into the experiment log ---

def _kb_result_fixture(symptoms=("s1",), techniques=("t1",),
                       source: str | None = "fixture"):
    from polymerhus.attack.hunting import symptom_kb as SK

    def fake_lookup(q):
        return SK.SymptomTechniqueResult(symptoms=symptoms, techniques=techniques,
                                         source=source)
    return fake_lookup


def test_kb_retrieve_tool_records_a_first_class_kb_observation(tmp_path):
    """Every KB response is recorded as a first-class `KbObservation` into the
    D6 log AND the persisted variant slice (T3): the query, the fault/axis
    join-key context, the returned bundle, and the variant it drove - DISTINCT
    from an exec `RawObservation` (which stays untouched)."""
    from polymerhus.attack.hunting.pod.types import KbObservation

    store = PodMemoryStore(tmp_path)
    log = ExperimentLog(store=store, spec_id=SPEC_ID)
    tool = KbRetrieveTool(lookup=_kb_result_fixture(), log=log, variant_ref="v0")
    out = json.loads(tool.invoke({"query": "CSRF", "fault_id": "CWE-352",
                                  "technological_axis": ["web"]}))
    assert out["symptoms"] == ["s1"]                      # the response still returns
    assert len(log.kb_observations) == 1
    obs = log.kb_observations[0]
    assert isinstance(obs, KbObservation)                 # first-class typed record
    assert obs.variant_ref == "v0"
    assert obs.query == "CSRF"
    assert obs.fault_id == "CWE-352"
    assert obs.technological_axis == ["web"]
    assert obs.symptoms == ["s1"]
    assert obs.techniques == ["t1"]
    assert obs.source == "fixture"
    # store round-trip: the KB observation persists into the variant slice,
    # distinct from the exec raw_observations body.
    persisted = store.read_experiment_log(SPEC_ID, 0)
    assert persisted["kb_observations"] == [obs.model_dump()]
    assert persisted["raw_observations"] == []            # no exec record yet


def test_kb_retrieve_records_empty_bundle_on_raising_kb(tmp_path):
    """Fail-open (O13): an RAISING KB result is recorded as the EMPTY bundle -
    the empty record still lands in the log, and the recording never raises
    into the turn."""
    def boom(query):
        raise RuntimeError("kb down")

    store = PodMemoryStore(tmp_path)
    log = ExperimentLog(store=store, spec_id=SPEC_ID)
    tool = KbRetrieveTool(lookup=boom, log=log, variant_ref="v0")
    out = json.loads(tool.invoke({"query": "x"}))
    assert out == {"symptoms": [], "techniques": [], "source": None}
    assert len(log.kb_observations) == 1
    obs = log.kb_observations[0]
    assert obs.symptoms == [] and obs.techniques == [] and obs.source is None
    persisted = store.read_experiment_log(SPEC_ID, 0)
    assert persisted["kb_observations"] == [obs.model_dump()]


def test_kb_retrieve_records_empty_bundle_on_empty_kb(tmp_path):
    """Fail-open (O13): an EMPTY KB result is recorded as the empty bundle."""
    store = PodMemoryStore(tmp_path)
    log = ExperimentLog(store=store, spec_id=SPEC_ID)
    tool = KbRetrieveTool(lookup=_kb_result_fixture(symptoms=(), techniques=(), source=None),
                          log=log, variant_ref="v0")
    out = json.loads(tool.invoke({"query": "x"}))
    assert out == {"symptoms": [], "techniques": [], "source": None}
    assert len(log.kb_observations) == 1
    assert log.kb_observations[0].symptoms == []


def test_kb_retrieve_storeless_never_records_and_never_raises():
    """A storeless/logless tool (the triager's context-read seam, or the plain
    bound tool) still serves the response and never records - fail-open."""
    tool = KbRetrieveTool(lookup=_kb_result_fixture())
    assert tool._log is None                          # no log bound
    out = json.loads(tool.invoke({"query": "CSRF"}))
    assert out["symptoms"] == ["s1"]                  # the response still returns


def test_kb_retrieve_async_path_records_same_shape(tmp_path):
    async def fake_lookup(q):
        from polymerhus.attack.hunting import symptom_kb as SK
        return SK.SymptomTechniqueResult(symptoms=("s1",), techniques=("t1",), source="f")

    store = PodMemoryStore(tmp_path)
    log = ExperimentLog(store=store, spec_id=SPEC_ID)
    tool = KbRetrieveTool(lookup=fake_lookup, log=log, variant_ref="v3")
    out = json.loads(asyncio.run(tool.ainvoke({"query": "CSRF"})))
    assert out["symptoms"] == ["s1"]
    assert len(log.kb_observations) == 1
    assert log.kb_observations[0].variant_ref == "v3"
    assert log.kb_observations[0].source == "f"
    # order 3 slice carries it (variant v3 <-> order 3)
    persisted = store.read_experiment_log(SPEC_ID, 3)
    assert persisted["kb_observations"] == [log.kb_observations[0].model_dump()]


def test_kb_plain_function_seam_is_untouched():
    # The legacy plain seam stays importable and fail-open for the contract tier.
    out = kb_retrieve("csrf on search")
    assert out == {"symptoms": [], "techniques": [], "source": None}


# --- the exec tool: G4 raw recording + retry + dedup signature -----------------

def test_exec_tool_records_a_raw_observation_and_marks_executed(tmp_path):
    log = ExperimentLog()
    tool = ExecTool(exec_fn=_exec(_OK), log=log, variant_ref="v0")
    out = tool.invoke({"command": "curl -k -sS https://t/"})
    assert "TOOL RESULT: status=200" in out
    assert len(log.raw_observations) == 1
    obs = log.raw_observations[0]
    assert obs.variant_ref == "v0"
    assert obs.status == 200
    assert "market" in obs.body
    assert obs.probe_ref in log.executed            # the dedup ledger marked O7


def test_exec_tool_retries_a_non_zero_exit_up_to_the_cap():
    calls = []

    def fake(command, timeout_s):
        calls.append(command)
        if len(calls) < MAX_POD_ITERS:
            return ExecResult(stdout="", stderr="boom", returncode=1, duration_ms=1)
        return ExecResult(stdout=_OK, stderr="", returncode=0, duration_ms=1)

    log = ExperimentLog()
    tool = ExecTool(exec_fn=fake, log=log, variant_ref="v0")
    tool.invoke({"command": "curl -k -sS https://t/"})
    assert len(calls) == MAX_POD_ITERS
    assert len(log.raw_observations) == 1            # one raw record, retries folded


def test_exec_tool_passes_the_fixed_timeout_cap(monkeypatch):
    seen = {}

    def fake(command, timeout_s):
        seen["t"] = timeout_s
        return ExecResult(stdout=_OK, stderr="", returncode=0, duration_ms=1)

    log = ExperimentLog()
    tool = ExecTool(exec_fn=fake, log=log, variant_ref="v0")
    tool.invoke({"command": "curl -k -sS https://t/"})
    assert seen["t"] == EXEC_TIMEOUT_S


def test_exec_tool_rejects_a_foreign_parameter(monkeypatch):
    log = ExperimentLog()
    tool = ExecTool(exec_fn=_exec(), log=log, variant_ref="v0")
    with pytest.raises(ValidationError):
        tool.invoke({"command": "curl -k -sS /", "timeout_s": 9999, "bogus": 1})


def test_exec_spec_does_not_expose_the_pod_cap_to_the_model():
    # D67-09: the per-exec cap is the POD's, never a model-chosen field.
    assert "timeout_s" not in ExecSpec.model_fields
    assert KbRetrieveSpec.model_config.get("extra") == "forbid"
    assert ExecSpec.model_config.get("extra") == "forbid"
    assert "query" in KbRetrieveSpec.model_fields


def test_exec_tool_async_path_records_same_shape():
    async def fake(command, timeout_s):
        return ExecResult(stdout=_OK, stderr="", returncode=0, duration_ms=1)

    log = ExperimentLog()
    tool = ExecTool(exec_fn=fake, log=log, variant_ref="v3")
    out = asyncio.run(tool.ainvoke({"command": "curl -k -sS https://t/"}))
    assert "TOOL RESULT: status=200" in out
    assert len(log.raw_observations) == 1


def test_runner_tools_note_tool_rejects_a_storeless_instance(tmp_path):
    tools = runner_react_tools(_exec(), None, SPEC_ID,
                               ExperimentLog(), "v0")
    note = next(t for t in tools if t.name == "note")
    assert isinstance(note, PodNoteTool)
    out = note.invoke({"operation": "write", "order": 0, "note_name": "n",
                       "kind": "freeform", "body": "x"})
    assert out.startswith("NOTES_NO_STORE")