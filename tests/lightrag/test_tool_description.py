"""Unit tier: the single canonical tool description (#207, defect 2).

The KB is a testing-METHODOLOGY knowledge base, never a "fault knowledge base".
One constant (`QUERY_LIGHTRAG_DESCRIPTION` in `lightrag/tool.py`) is imported
verbatim by all three description sites (the real tool, the pod wrapper, the
hunter wrapper), so the description cannot drift. The ontology list must match
the real `lightrag.ontology.ENTITY_TYPES`, and the framing must not invite using
the KB to verify or adjudicate a bug.
"""
from __future__ import annotations

from lightrag.ontology import ENTITY_TYPES
from lightrag.tool import QUERY_LIGHTRAG_DESCRIPTION, LightRagQueryTool


class _FakeWrappedTool:
    """A minimal stand-in for the pod wrapper's injected `tool` (the real
    `query_lightrag` tool) - the pod `KbQueryTool` needs one to build."""

    name: str = "query_lightrag"
    args_schema = None

ENTITY_NAMES = {
    "technology stack": "TechnologyStack",
    "attack technique": "AttackTechnique",
    "payload pattern": "PayloadPattern",
    "artifact": "Artifact",
    "observable signal": "ObservableSignal",
    "vulnerability class": "VulnerabilityClass",
    "attack goal": "AttackGoal",
    "attacker capability": "AttackerCapability",
    "precondition environment": "PreconditionEnvironment",
    "defensive control": "DefensiveControl",
}


def test_description_lists_exactly_the_real_ontology_entities():
    for label, entity in ENTITY_NAMES.items():
        assert label in QUERY_LIGHTRAG_DESCRIPTION, f"missing {label!r}"
        assert entity in ENTITY_TYPES
    # The description names 10 distinct concepts - the full ENTITY_TYPES set.
    assert len(ENTITY_NAMES) == len(ENTITY_TYPES) == 10
    # No stale fault-era terms survive.
    for stale in ("fault", "symptom, assumption", "strategy"):
        assert stale not in QUERY_LIGHTRAG_DESCRIPTION.lower()


def test_description_frames_the_kb_as_methodology_not_verifier():
    lower = QUERY_LIGHTRAG_DESCRIPTION.lower()
    assert "methodology" in lower
    assert "knowledge base" in lower
    assert "fault knowledge base" not in lower
    # The enriched-answers caveat keeps the grounding-vs-enrichment honesty.
    assert "enrich" in lower


def test_tool_uses_the_canonical_constant():
    tool = LightRagQueryTool(client=object(), llm=object())
    assert tool.description == QUERY_LIGHTRAG_DESCRIPTION


def test_pod_tool_uses_the_canonical_constant():
    from polymerhus.attack.hunting.pod.tools import KbQueryTool as PodKbQueryTool

    assert PodKbQueryTool(tool=_FakeWrappedTool()).description == QUERY_LIGHTRAG_DESCRIPTION


def test_hunter_tool_uses_the_canonical_constant():
    from polymerhus.attack.hunting.hunter_tools import KbQueryTool as HunterKbQueryTool

    assert HunterKbQueryTool().description == QUERY_LIGHTRAG_DESCRIPTION