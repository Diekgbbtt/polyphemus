"""Unit tier: the hunting agent's pure mechanics and the role registration.

The catalogue predicates C1-C17 live in
tests/integration/test_hunting_agent_contracts.py and are never repeated in
this tier's red/green loop (testing-strategy.md section 2, the #82 precedent).
This tier pins the pure functions the harness relies on:

  derive_verdict(terminal_reason, *, clean, init_validation=None)
      - the D7 vierdict derivation (D67-02, Q3-amended; implementation doc
        section 2.3/5.2): reads ONLY the terminal reason plus the single
        `clean` flag (plus `init_validation` for the INIT-rejection case),
        never per-variant machinery.

  derive_technological_axis(card)
      - the deterministic technological axis for the `(fault-class, axis)`
        KB join key (IA-8, D10): derived from the unit's index card, never
        a typed predicate facet (#66 non-conflation).

  ROLES - the `hunting` role joins the LLM role registry keyed by
      `LLM_MODEL_HUNTING` (Q1).
"""
from pathlib import Path

import pytest

from polymerhus.attack.hunting.hunting_agent import (
    HypothesisVerdict,
    compose_authoring_prompt,
    derive_technological_axis,
    derive_verdict,
)
from polymerhus.attack.hunting.hunt_orchestrator import (
    HuntConfig,
    HuntPromptTemplate,
)
from polymerhus.app.llm.providers import HUNTING_ROLES, ROLES


# --- derive_verdict: the ratified Q3 map (implementation doc 2.3) ------------

def test_symptom_confirmed_derives_successful():
    assert derive_verdict("symptom-confirmed", clean=False) == "successful"


def test_space_exhausted_derives_unsuccessful():
    assert derive_verdict("space-exhausted", clean=True) == "unsuccessful"


def test_technical_infeasibility_derives_unsuccessful():
    # A structural blocker is a refutation, never insufficient-evidence (Q3).
    assert derive_verdict("technical-infeasibility", clean=False) == "unsuccessful"


def test_specific_defence_prevention_derives_unsuccessful():
    assert derive_verdict("specific-defence-prevention", clean=False) == "unsuccessful"


def test_no_symptom_evidence_blocked_derives_insufficient_evidence():
    # Blocked/unreachable observations: the absence is not established (Q3).
    assert derive_verdict("no-symptom-evidence", clean=False) == "insufficient-evidence"


def test_no_symptom_evidence_clean_derives_unsuccessful():
    # Clean completed observations: a symptom-absent is established (Q3).
    assert derive_verdict("no-symptom-evidence", clean=True) == "unsuccessful"


def test_budget_timeout_mid_flight_derives_insufficient_evidence():
    # The loop was cut mid-flight: the absence is not established (Q3).
    assert derive_verdict("budget-timeout", clean=False) == "insufficient-evidence"


def test_budget_timeout_clean_derives_unsuccessful():
    assert derive_verdict("budget-timeout", clean=True) == "unsuccessful"


def test_init_rejection_derives_underspecified_spec():
    # A pod INIT rejection (tech-infeasibility carrying init_validation)
    # derives underspecified-spec (Q3/Q5).
    assert derive_verdict(
        "technical-infeasibility",
        clean=False,
        init_validation=["symptom references an unobservable surface"],
    ) == "underspecified-spec"


def test_unknown_terminal_reason_derives_insufficient_evidence():
    # Fail-open: an out-of-enum terminal reason cannot be interpreted, so the
    # derivation is conservative - never a success or a clean absence claim.
    assert derive_verdict("something-else", clean=True) == "insufficient-evidence"


# --- derive_technological_axis: the deterministic joint-key axis (IA-8) ------

def test_axis_prefers_api_paradigm():
    card = {"kind": "Service", "spine": {"api_paradigm": "REST", "exposure": "public"}}
    assert derive_technological_axis(card) == "rest"


def test_axis_falls_back_to_navigation_model():
    card = {"kind": "System", "spine": {"navigation_model": "SPA"}}
    assert derive_technological_axis(card) == "spa"


def test_axis_defaults_to_kind():
    # CARD_A in the contract suite carries only `exposure`; the axis must
    # stay deterministic and non-empty (C1 asserts a non-empty string).
    card = {"kind": "Service", "key": {"business_function_slug": "a"}, "spine": {"exposure": "public"}}
    assert derive_technological_axis(card) == "service"


def test_axis_empty_card_defaults():
    assert derive_technological_axis({}) == "unknown"
    assert derive_technological_axis(None) == "unknown"


# --- the hunting roles join the LLM role registry (Q1, #93/#94) --------------

def test_hunting_roles_are_registered_off_app_boot():
    """The hunting agents are their own role_ids in HUNTING_ROLES (validated at the
    hunting module bootstrap), never in the app-boot ROLES (operator ruling
    2026-08-06). Both are `session` agents."""
    hunting_ids = {r.role_id for r in HUNTING_ROLES}
    assert hunting_ids == {"hunting_orchestrator", "hunting_hunter"}
    assert not (hunting_ids & {r.role_id for r in ROLES})  # off app boot
    assert all(r.agent_mode == "session" for r in HUNTING_ROLES)


def test_hypothesis_verdict_vocabulary_is_four_valued():
    assert set(HypothesisVerdict.__args__) == {
        "successful", "unsuccessful", "insufficient-evidence", "underspecified-spec",
    }


# --- compose_authoring_prompt: optional query_lightrag guidance ---------------


def _prompt_config() -> HuntConfig:
    return HuntConfig(
        hunt_id="hunt-1",
        unit_id="Service:slug:a",
        fault_class="fault-x",
        prompt_template=HuntPromptTemplate(
            rationale="rationale",
            extension_points=["ext"],
            assumptions=["assumption"],
            supposed_payload_vectors=["vector"],
            l0_evidence=["l0"],
        ),
        surface_context={"cards": [{"title": "card"}]},
        target_caveats=["caveat"],
        tool_registry=[{"name": "registry-tool"}],
    )


def _authoring_prompt(lightrag_tool_enabled: bool) -> str:
    return compose_authoring_prompt(
        _prompt_config(),
        {"kb": "kb-text"},
        "http",
        kb_degraded=False,
        working_set="fresh hunt: no prior dispatch",
        lightrag_tool_enabled=lightrag_tool_enabled,
    )


def _lightrag_query_skill_body() -> str:
    """The mounted skill body (YAML frontmatter stripped), the single source
    of the `query_lightrag` guidance the enabled prompt must inject."""
    path = (
        Path(__file__).resolve().parents[2]
        / "skills" / "hunting" / "lightrag-query" / "SKILL.md"
    )
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        text = text.split("---", 2)[-1].lstrip()
    return text


def test_authoring_prompt_disabled_mentions_no_lightrag_tool():
    prompt = _authoring_prompt(lightrag_tool_enabled=False)
    assert "query_lightrag" not in prompt
    assert "QuerySpecV1" not in prompt
    assert "Your working set: fresh hunt: no prior dispatch" in prompt


def test_authoring_prompt_enabled_instructs_the_agent_on_the_tool():
    prompt = _authoring_prompt(lightrag_tool_enabled=True)
    assert _lightrag_query_skill_body() in prompt
    assert "query_lightrag" in prompt
    for field in (
        "scenario_id",
        "attack_goal",
        "concern",
        "technology_stack",
        "target_refs",
        "input_vectors",
        "known_facts",
        "acceptable_technique_families",
        "unsupported_claims",
        "evidence",
        "expected_no_hypothesis",
    ):
        assert field in prompt
    # the guidance sits before the working set, and the disabled prompt is a
    # strict prefix of the enabled one (byte-equivalent when off).
    assert prompt.index("Your working set:") > prompt.index("query_lightrag")


def test_load_lightrag_query_skill_returns_mounted_body():
    import polymerhus.attack.hunting.hunting_agent as hunting_agent

    body = _lightrag_query_skill_body()
    assert body
    assert hunting_agent._load_lightrag_query_skill() == body


def test_load_lightrag_query_skill_degrades_to_terse_fallback(monkeypatch):
    """A missing skill mount must degrade to the terse fallback, never crash
    and never duplicate the full field contract in code."""
    import polymerhus.attack.hunting.hunting_agent as hunting_agent
    import polymerhus.recon.domain.skills as skills_module

    # Simulate an unmounted skills dir through the REAL skill_for degradation
    # path (it never raises; it returns the fallback), then restore the cache.
    monkeypatch.setattr(
        skills_module, "_SKILLS_ROOT", Path("/nonexistent-skills-mount")
    )
    skills_module.clear_cache()
    try:
        result = hunting_agent._load_lightrag_query_skill()
    finally:
        skills_module.clear_cache()
    assert result
    assert "query_lightrag" in result
    assert "acceptable_technique_families" not in result


def test_authoring_prompt_flag_helper_reads_app_config(monkeypatch):
    import polymerhus.attack.hunting.hunting_agent as hunting_agent
    import polymerhus.app.config as config_module

    monkeypatch.setattr(config_module.config, "HUNTING_LIGHTRAG_TOOL", True)
    assert hunting_agent._hunting_lightrag_tool_enabled() is True
    monkeypatch.setattr(config_module.config, "HUNTING_LIGHTRAG_TOOL", False)
    assert hunting_agent._hunting_lightrag_tool_enabled() is False
