"""Unit tier: T7 (#157) - the pod's bound-tool surface (D84-16/22/26/27).

The ReAct Runner binds `tools=[exec, note]` (D84-27) plus - when
`HUNTING_LIGHTRAG_TOOL` is enabled - the single `query_lightrag` tool from the
lightrag branch (the pod runner can be configured with it, exactly like the
hunting agent's author lane). The former `kb_retrieve` symptom-technique seam
(surface B) is retired. The `exec` tool stays the raw-recording terminal (G4)
with retry and dedup-marking. Hermetic: fake terminal, no live KB, no live LLM.
"""
from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from polymerhus.attack.hunting.pod.agents import runner_react_tools, triager_react_tools
from polymerhus.attack.hunting.pod.config import EXEC_TIMEOUT_S, MAX_POD_ITERS
from polymerhus.attack.hunting.pod.context import ExperimentLog
from polymerhus.attack.hunting.pod.note_tool import PodNoteTool
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore, canonical_spec_id
from polymerhus.attack.hunting.pod.tools import (
    ExecSpec,
    ExecTool,
)
from polymerhus.recon.domain.types import ExecResult

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


# --- the KB tool: the single config-gated query_lightrag (retired kb_retrieve) -

def test_runner_binds_exec_and_note_without_a_kb_tool_by_default(tmp_path):
    """The Runner's ReAct `tools=` list carries `exec` + `note`; with
    `HUNTING_LIGHTRAG_TOOL` off (the default) there is NO KB tool (the former
    `kb_retrieve` seam is retired)."""
    tools = runner_react_tools(exec_fn=_exec(), memory_store=PodMemoryStore(tmp_path),
                               spec_id=canonical_spec_id(SPEC), log=ExperimentLog(),
                               variant_ref="v0")
    names = {t.name for t in tools}
    assert {"exec", "note"} <= names
    assert "kb_retrieve" not in names
    assert "query_lightrag" not in names


def test_runner_binds_query_lightrag_when_the_flag_is_on(tmp_path, monkeypatch):
    """With `HUNTING_LIGHTRAG_TOOL=1` the Runner's tool set carries the single
    `query_lightrag` tool (the lightrag branch's KB tool)."""
    import polymerhus.app.config as config_module

    monkeypatch.setattr(config_module.config, "HUNTING_LIGHTRAG_TOOL", True)
    tools = runner_react_tools(exec_fn=_exec(), memory_store=PodMemoryStore(tmp_path),
                               spec_id=canonical_spec_id(SPEC), log=ExperimentLog(),
                               variant_ref="v0")
    names = {t.name for t in tools}
    assert {"exec", "note", "query_lightrag"} <= names


def test_triager_binds_note_and_no_exec(tmp_path):
    tools = triager_react_tools(PodMemoryStore(tmp_path), canonical_spec_id(SPEC))
    names = {t.name for t in tools}
    assert {"note"} <= names
    assert "exec" not in names
    assert "kb_retrieve" not in names


def test_runner_tools_are_injective_constructed_per_stretch(tmp_path):
    log = ExperimentLog()
    store = PodMemoryStore(tmp_path)
    spec_id = canonical_spec_id(SPEC)
    tools_v0 = runner_react_tools(_exec(), store, spec_id, log, "v0")
    tools_v1 = runner_react_tools(_exec(), store, spec_id, log, "v1")
    exec_v0 = next(t for t in tools_v0 if t.name == "exec")
    exec_v1 = next(t for t in tools_v1 if t.name == "exec")
    assert exec_v0 is not exec_v1                     # per-stretch instances
    sig0 = exec_v0._signature("curl -k -sS /")        # variant-sensitive keys
    sig1 = exec_v1._signature("curl -k -sS /")
    assert sig0 != sig1


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
    assert ExecSpec.model_config.get("extra") == "forbid"


def test_exec_tool_async_path_records_same_shape():
    async def fake(command, timeout_s):
        return ExecResult(stdout=_OK, stderr="", returncode=0, duration_ms=1)

    log = ExperimentLog()
    tool = ExecTool(exec_fn=fake, log=log, variant_ref="v3")
    out = asyncio.run(tool.ainvoke({"command": "curl -k -sS https://t/"}))
    assert "TOOL RESULT: status=200" in out
    assert len(log.raw_observations) == 1


def test_runner_tools_note_tool_rejects_a_storeless_instance(tmp_path):
    tools = runner_react_tools(_exec(), None, canonical_spec_id(SPEC),
                               ExperimentLog(), "v0")
    note = next(t for t in tools if t.name == "note")
    assert isinstance(note, PodNoteTool)
    out = note.invoke({"operation": "write", "variant_ref": "v0", "note_name": "n",
                       "kind": "freeform", "body": "x"})
    assert out.startswith("NOTES_NO_STORE")