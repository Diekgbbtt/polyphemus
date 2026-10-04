"""Unit tier: the KB-query contract is single-sourced (#322).

The hunter's `kb_query`, the pod's `query_lightrag`, and the real LightRAG tool
must advertise the SAME args contract, `QuerySpecV1` - otherwise the shared
usage skill (`skills/lightrag-query/SKILL.md`), the shared canonical description
(`QUERY_LIGHTRAG_DESCRIPTION`), and the schema the model is handed drift apart.
The run-09c0f4c8 defect: the hunter carried a stale local `KbQuerySpec` mirror
missing `expected_no_hypothesis`; the skill told the model to pass it, and every
`kb_query` degraded to `tool_failed`. No live target, no LLM, no DB.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from lightrag.query_spec import QuerySpecV1
from lightrag.tool import QUERY_LIGHTRAG_DESCRIPTION

_SKILL_PATH = (
    Path(__file__).resolve().parents[2] / "skills" / "lightrag-query" / "SKILL.md"
)


def _bundle(spec: QuerySpecV1) -> dict:
    return {
        "schema_version": "lightrag-answer/v2",
        "scenario_id": spec.scenario_id,
        "summary": "CSRF methodology",
        "ontology_explanations": [],
        "provenance_references": ["doc-9"],
        "knowledge_gaps": [],
        "notes": "",
    }


def test_hunter_kb_query_uses_the_real_query_spec():
    """The hunter tool's args schema is the real `QuerySpecV1` - the same
    contract the pod and the lightrag tool bind - never a local mirror."""
    from polymerhus.attack.hunting.hunter_tools import KbQueryTool

    assert KbQueryTool().args_schema is QuerySpecV1


def test_hunter_kb_query_accepts_expected_no_hypothesis(monkeypatch):
    """The run-09c0f4c8 defect: the model passes `expected_no_hypothesis` (a
    real `QuerySpecV1` field the skill documents); the tool must validate and
    return a real KB bundle, never degrade to `tool_failed`."""
    from polymerhus.attack.hunting.hunter_tools import KbQueryTool

    monkeypatch.setattr(KbQueryTool, "_lightrag_tool", lambda self: None)
    tool = KbQueryTool(kb_fn=_bundle)
    out = json.loads(tool.invoke({
        "scenario_id": "HUNT-1",
        "attack_goal": "obtain admin",
        "concern": "forced browsing",
        "expected_no_hypothesis": False,
    }))
    assert out["scenario_id"] == "HUNT-1"
    assert out["summary"] == "CSRF methodology"


def test_description_cites_the_query_spec_contract():
    """The canonical description names the args contract and every field the
    model must supply - single-sourced from `QuerySpecV1`, so it cannot drift."""
    assert "QuerySpecV1" in QUERY_LIGHTRAG_DESCRIPTION
    for field in QuerySpecV1.model_fields:
        assert field in QUERY_LIGHTRAG_DESCRIPTION, field


def _documented_fields(skill_text: str) -> set[str]:
    """The field names the skill's "How to build" section documents (backticked
    tokens that name a lowercase field), never prose tokens."""
    section = skill_text.split("## How to build", 1)[1].split("## Response", 1)[0]
    tokens = re.findall(r"`([^`]+)`", section)
    return {t for t in tokens if t.isidentifier() and t.islower()}


def test_usage_skill_names_only_real_query_spec_fields():
    """The instruction/schema agreement: every QuerySpecV1 field the skill
    documents is a real `QuerySpecV1` field (the stale `supposed_payload_vectors`
    and any invented key fail here), and the required fields are all taught."""
    documented = _documented_fields(_SKILL_PATH.read_text(encoding="utf-8"))
    assert documented, "the skill documents no fields"
    unknown = documented - set(QuerySpecV1.model_fields)
    assert not unknown, f"skill names non-contract fields: {sorted(unknown)}"
    for required in ("scenario_id", "attack_goal", "concern"):
        assert required in documented, required
