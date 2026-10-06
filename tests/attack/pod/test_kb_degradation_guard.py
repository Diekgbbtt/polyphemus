"""Unit tier (#304): a degraded knowledge-base tool is UNAVAILABLE evidence,
never evidence of absence.

#329 classified a provider failure raised by an agent TURN. #304 is the adjacent
hole: the KB tool fails OPEN - it returns a deterministic-fallback bundle rather
than raising - so the triager reads "no precise new variant", applies its
EXHAUSTION rule, and terminates `{unsuccessful, space-exhausted, clean=true}`.
A degraded domain becomes a false absence.

The exercises here pin the fix at the pod/triager seam:
  * the KB tool marks its answer machine-readably and records the degraded flag
    on the `KbObservation` (no reliance on prompt obedience);
  * the graph's triager node downgrades a clean exhaustion claim to an impaired
    `no-symptom-evidence` when the run's KB evidence was degraded, so the
    hypothesis derivation yields `insufficient-evidence`, never a false absence.

Hermetic: fake terminal, fake lightrag tool, no live KB, no live LLM, no DB.
"""
from __future__ import annotations

import asyncio
import json

from langchain_core.tools import BaseTool

from lightrag.query_spec import QuerySpecV1

from polymerhus.attack.hunting.pod import arun_pod
from polymerhus.attack.hunting.pod.agents import symbolic_runner_step_fn
from polymerhus.attack.hunting.pod.context import ExperimentLog
from polymerhus.attack.hunting.pod.tools import KbQueryTool

from tests.attack.pod.test_graph import SPEC_ID, VALID_SPEC, _exec, _no_trace

_ABSENT = "not found\n__POD_HTTP_STATUS__:404\n__POD_HTTP_TIME__:0.02"

# The exact degraded bundle the lightrag tool emits when it falls back: no
# validated model answer, a `tool_failed` gap, the fallback notes.
_LIGHTRAG_FALLBACK = {
    "schema_version": "lightrag-answer/v2",
    "scenario_id": "SIM-01",
    "summary": "Deterministic checklist fallback; model answer unavailable.",
    "ontology_explanations": [],
    "provenance_references": [],
    "knowledge_gaps": ["tool_failed: RuntimeError"],
    "notes": "Fallback: no fabricated provenance is allowed.",
}


def _fallback_lightrag(*, degraded: bool):
    """A fake `query_lightrag` returning the fallback/valid bundle shape. The
    `degraded` key is part of the real tool's contract (set from `accepted`);
    the fake mirrors it so the pod wrapper's contract is exercised."""
    payload = dict(_LIGHTRAG_FALLBACK)
    payload["degraded"] = degraded
    if not degraded:
        payload = {
            "schema_version": "lightrag-answer/v2", "scenario_id": "SIM-01",
            "summary": "CSRF methodology", "ontology_explanations": [],
            "provenance_references": ["doc-1"], "knowledge_gaps": [],
            "notes": "", "degraded": False,
        }

    class _Fake(BaseTool):
        name: str = "query_lightrag"
        description: str = "fake"
        args_schema: type[QuerySpecV1] = QuerySpecV1

        def _run(self, **kwargs):
            return json.dumps(payload)

        async def _arun(self, **kwargs):
            return self._run(**kwargs)

    return _Fake()


def _kb_spec() -> dict:
    return {"scenario_id": "SIM-01", "attack_goal": "x", "concern": "object-level authorization"}


def _drive(coro):
    return asyncio.run(coro)


def _laundering_triager(*, degraded: bool):
    """The triager seam the ticket observed: query the KB, then, because it
    'returned nothing new', terminate clean space-exhausted."""

    def triager(spec, obs, messages, log):
        kb = KbQueryTool(log=log, variant_ref="v0", tool=_fallback_lightrag(degraded=degraded))
        kb.invoke(_kb_spec())
        return {"classification": "symptom-absent", "action": "terminate",
                "verdict": "unsuccessful", "terminal_reason": "space-exhausted",
                "clean": True,
                "note": "KB returned no precise new variant -> space-exhausted"}

    return triager


# --- the KbObservation carries the degraded flag -----------------------------

def test_kb_query_records_a_degraded_observation_for_a_fallback_bundle():
    log = ExperimentLog()
    tool = KbQueryTool(log=log, variant_ref="v0",
                       tool=_fallback_lightrag(degraded=True))
    tool.invoke(_kb_spec())
    assert len(log.kb_observations) == 1
    assert log.kb_observations[0].degraded is True


def test_kb_query_records_an_available_observation_for_a_valid_bundle():
    log = ExperimentLog()
    tool = KbQueryTool(log=log, variant_ref="v0",
                       tool=_fallback_lightrag(degraded=False))
    tool.invoke(_kb_spec())
    assert log.kb_observations[0].degraded is False


# --- the graph guard: degraded KB never yields a clean absence ----------------

def test_degraded_kb_blocks_a_clean_space_exhausted_verdict():
    env = _drive(arun_pod(
        {**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
        exec_fn=_exec(_ABSENT), runner_step_fn=symbolic_runner_step_fn,
        triager_fn=_laundering_triager(degraded=True), trace_fn=_no_trace))
    assert env["verdict"] == "unsuccessful"
    # The unavailable-domain reason: observations were impaired, so the
    # derivation is insufficient-evidence, never a false absence.
    assert env["evidence"]["terminal_reason"] == "no-symptom-evidence"
    assert env["evidence"]["clean"] is False


def test_available_kb_keeps_a_clean_space_exhausted_verdict():
    """No over-blocking: a genuine clean exhaustion on an available KB stands."""
    env = _drive(arun_pod(
        {**VALID_SPEC, "verification_symptoms": ["reflects the marker"]},
        exec_fn=_exec(_ABSENT), runner_step_fn=symbolic_runner_step_fn,
        triager_fn=_laundering_triager(degraded=False), trace_fn=_no_trace))
    assert env["evidence"]["terminal_reason"] == "space-exhausted"
    assert env["evidence"]["clean"] is True
