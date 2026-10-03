"""Contract tier: the cognitive architecture map (C1, the cortex).

One shared verbatim, single-sourced from
`attack/hunting/prompts/COGNITIVE_ARCHITECTURE_MAP.md`, must be present in all
four hunting agents' served system prompts: the hunt-orchestrator, the hunter,
the pod runner, and the pod triager.

The injected verbatim is the concise conceptual core - the data domains and
their abstract relationships - and the agents stay blind to internal codebase
information. The full detail lives in the design document
`docs/design/cortex-cognitive-architecture-map.md`. These tests pin the single
source, the composition helper, the presence and identity of the map in all
four, the domain-and-relationship shape, and the blindness to codebase
identifiers.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from polymerhus.attack.hunting.cortex import (
    cognitive_architecture_map,
    with_cortex,
)

# The four served system prompts, one accessor each - the composition path every
# hunting agent's stable system prompt goes through.
ROLE_PROMPTS = (
    ("hunt-orchestrator", "polymerhus.attack.hunting.llm", "_gate_skill"),
    ("hunter", "polymerhus.attack.hunting.hunting_agent",
     "_load_hunting_agent_skill"),
    ("pod-runner", "polymerhus.attack.hunting.pod.prompts",
     "runner_system_prompt"),
    ("pod-triager", "polymerhus.attack.hunting.pod.prompts",
     "triager_system_prompt"),
)

# Internal codebase identifiers the agents must stay blind to: tool names,
# store paths, artifact/type names, layer labels, and source paths.
FORBIDDEN_INTERNAL_TOKENS = (
    "graph_view", "kb_query", "query_lightrag", "auth_store", "hunts_store",
    "load_skill", "record_skill_lesson", "search_http_history",
    "get_http_artifact", "hunts_store",
    "memory.yaml", "notes.yaml", "http-artifact", "HuntConfig",
    "TestImplementationSpec", "ExperimentLog", "PodExport", "KbObservation",
    "client_side_js_architecture",
    "L0", "L1", "docs/design", "cortex.py", ".md",
)


def _served_prompt(module_path: str, attr: str) -> str:
    import importlib

    return getattr(importlib.import_module(module_path), attr)()


def test_cortex_is_a_non_empty_single_source():
    """The cortex is its own codebase file with the data domains and their
    abstract relationships."""
    body = cognitive_architecture_map()
    assert body.strip()
    for marker in ("The data domains", "How they relate"):
        assert marker in body, marker


def test_cortex_lists_the_six_data_domains():
    body = cognitive_architecture_map()
    for domain in (
        "Target surface",
        "Target context",
        "Hunt memory",
        "Request history",
        "Testing knowledge",
        "Procedural knowledge",
    ):
        assert domain in body, domain


def test_target_context_is_one_domain_grouping_auth_and_rate_limit():
    """The authentication state and the rate-limit posture are ONE target
    context domain, never two distinct domains."""
    body = cognitive_architecture_map()
    assert "authentication state" in body
    assert "rate-limit posture" in body
    line = next(l for l in body.splitlines() if "Target context" in l)
    assert "authentication state" in line
    assert "rate-limit posture" in line


def test_cortex_states_the_abstract_relationships_without_flows():
    """The relationships are abstract; there are no explicit question -> tool
    flows in the injected map."""
    body = cognitive_architecture_map()
    assert "notion sections" in body          # the abstract RDF<->KB relationship
    assert "entity types" in body
    assert "->" not in body                    # no explicit flow arrows
    assert "?" not in body                     # no question -> entity -> tool lines


def test_cortex_is_blind_to_internal_codebase_information():
    body = cognitive_architecture_map()
    for token in FORBIDDEN_INTERNAL_TOKENS:
        assert token not in body, token


def test_with_cortex_appends_the_map_exactly_once():
    base = "BASE ROLE PROMPT"
    composed = with_cortex(base)
    assert composed.startswith(base)
    assert composed.count(cognitive_architecture_map()) == 1
    assert composed.rstrip().endswith(cognitive_architecture_map().rstrip())


@pytest.mark.parametrize("agent,module_path,attr", ROLE_PROMPTS,
                         ids=[r[0] for r in ROLE_PROMPTS])
def test_cortex_is_present_in_every_hunting_agents_system_prompt(
        agent, module_path, attr):
    """The cortex rides all four served system prompts - identical for every
    agent, never forked - and the role's own prompt is still there ahead of it."""
    served = _served_prompt(module_path, attr)
    assert served.strip()
    assert served.count(cognitive_architecture_map()) == 1
    assert served.rstrip().endswith(cognitive_architecture_map().rstrip())
    assert served.strip() != cognitive_architecture_map().strip()


def test_cortex_is_byte_identical_across_all_four_agents():
    """The role prefixes differ (four distinct disciplines), the map does not:
    each served prompt is its own prefix plus the ONE shared verbatim."""
    map_text = cognitive_architecture_map()
    prefixes = []
    for _, module_path, attr in ROLE_PROMPTS:
        served = _served_prompt(module_path, attr)
        assert served.endswith(map_text)
        prefixes.append(served[: -len(map_text)])
    assert len(set(prefixes)) == len(prefixes)   # four distinct role prompts
    assert all(p.strip() for p in prefixes)      # none reduced to the map alone


def test_cortex_has_no_em_dash():
    assert "\u2014" not in cognitive_architecture_map()


def test_role_prompt_files_do_not_duplicate_the_map():
    """Single source: the map lives only in its own file, never copied into a
    role prompt file."""
    base = Path(__file__).resolve().parents[2] / "src" / "polymerhus" / "attack" / "hunting"
    for name in ("prompts/hunt-orchestrator.md", "prompts/hunting-agent.md"):
        assert cognitive_architecture_map() not in (base / name).read_text(
            encoding="utf-8")


def test_the_detailed_cortex_lives_in_its_design_document():
    """The externalised detail is authored in the cortex design document."""
    doc = (
        Path(__file__).resolve().parents[2]
        / "docs" / "design" / "cortex-cognitive-architecture-map.md"
    )
    body = doc.read_text(encoding="utf-8")
    for entity in ("VulnerabilityClass", "AttackerCapability", "AttackTechnique",
                   "PreconditionEnvironment", "DefensiveControl"):
        assert entity in body, entity
