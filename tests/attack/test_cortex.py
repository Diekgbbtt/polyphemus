"""Contract tier: the cognitive architecture map (C1, the cortex).

One shared verbatim, single-sourced from
`attack/hunting/prompts/COGNITIVE_ARCHITECTURE_MAP.md`, must be present in all
four hunting agents' served system prompts: the hunt-orchestrator, the hunter,
the pod runner, and the pod triager. These tests pin the single source, the
composition helper, and the presence and identity of the map in all four.
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


def _served_prompt(module_path: str, attr: str) -> str:
    import importlib

    return getattr(importlib.import_module(module_path), attr)()


def test_cortex_is_a_non_empty_single_source():
    """The cortex is its own codebase file with the entity roles, the coupling
    paths, the RDF<->KB mapping, and the pending register."""
    body = cognitive_architecture_map()
    assert body.strip()
    for marker in (
        "Entities and their roles",
        "The coupling paths",
        "The RDF<->KB mapping",
        "Pending register",
    ):
        assert marker in body, marker


def test_cortex_carries_the_rdf_to_kb_mapping_pairs():
    """The mapping section renders the landed notion-to-entity pairs."""
    body = cognitive_architecture_map()
    for entity in (
        "VulnerabilityClass",
        "AttackerCapability",
        "AttackTechnique",
        "PreconditionEnvironment",
        "DefensiveControl",
    ):
        assert entity in body, entity
    # the notion names the mapping keys on
    for notion in ("testing methodology", "adversarial capabilities",
                   "attack surface", "bypass techniques"):
        assert notion in body, notion


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
    # the role's own discipline is a real prefix, not erased by the map
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
