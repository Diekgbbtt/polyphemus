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
from polymerhus.attack.hunting.hunting_agent import (
    HypothesisVerdict,
    derive_technological_axis,
    derive_verdict,
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

def test_compose_grounding_renders_aggregated_endpoints_in_both_shapes():
    """#201: the hunter's grounding render spells the aggregated L0 endpoints
    coherently in BOTH the canonical {"cards": [...]} wrapper and the legacy
    direct flat shape; an absent slot degrades, never a raise."""
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        HuntConfig,
        HuntPromptTemplate,
    )
    from polymerhus.attack.hunting.hunting_agent import (  # noqa: PLC0415
        _compose_grounding,
    )

    template = HuntPromptTemplate(rationale="r", research_direction="d")
    eps = [
        {"method": "GET", "path": "/cart", "baseurl": "https://a"},
        {"method": "POST", "path": "/pay", "baseurl": "https://a",
         "service_slug": "sign-in"},
    ]
    wrapper = HuntConfig(
        hunt_id="h-1", unit_id="Service:slug:a", fault_class="fault-x",
        prompt_template=template,
        surface_context={"cards": [{"kind": "Service", "aggregated_endpoints": eps}]},
    )
    text = _compose_grounding(wrapper)
    assert "aggregated endpoints:" in text
    assert "GET /cart (baseurl: https://a)" in text
    assert "POST /pay (baseurl: https://a) [service: sign-in]" in text
    flat = HuntConfig(
        hunt_id="h-2", unit_id="Service:slug:a", fault_class="fault-x",
        prompt_template=template,
        surface_context={"kind": "Service", "aggregated_endpoints": eps},
    )
    text = _compose_grounding(flat)
    assert "aggregated endpoints:" in text
    assert "GET /cart (baseurl: https://a)" in text
    bare = HuntConfig(
        hunt_id="h-3", unit_id="Service:slug:a", fault_class="fault-x",
        prompt_template=template, surface_context={},
    )
    assert "no adapted index cards" in _compose_grounding(bare)


def test_config_gaps_does_not_flag_the_direct_flat_shape():
    """#201: the O3 gap flag accepts the direct flat shape (no 'cards' key) -
    it only flags a genuinely absent surface context."""
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        HuntConfig,
        HuntPromptTemplate,
    )
    from polymerhus.attack.hunting.hunting_agent import (  # noqa: PLC0415
        _config_gaps,
    )

    template = HuntPromptTemplate(rationale="r", research_direction="d")
    flat = HuntConfig(
        hunt_id="h-1", unit_id="Service:slug:a", fault_class="fault-x",
        prompt_template=template,
        surface_context={"kind": "Service", "aggregated_endpoints": []},
    )
    assert all("surface context" not in g for g in _config_gaps(flat))
    bare = HuntConfig(
        hunt_id="h-2", unit_id="Service:slug:a", fault_class="fault-x",
        prompt_template=template, surface_context={},
    )
    assert any("surface context missing" in g for g in _config_gaps(bare))


def test_hunting_roles_are_registered_off_app_boot():
    """The hunting agents are their own role_ids in HUNTING_ROLES (validated at the
    hunting module bootstrap), never in the app-boot ROLES (operator ruling
    2026-08-06). Both are `session` agents."""
    hunting_ids = {r.role_id for r in HUNTING_ROLES}
    assert hunting_ids == {"hunting_orchestrator", "hunting_hunter",
                           "pod_runner", "pod_triager"}
    assert not (hunting_ids & {r.role_id for r in ROLES})  # off app boot
    assert all(r.agent_mode == "session" for r in HUNTING_ROLES)


def test_hypothesis_verdict_vocabulary_is_four_valued():
    assert set(HypothesisVerdict.__args__) == {
        "successful", "unsuccessful", "insufficient-evidence", "underspecified-spec",
    }


# --- #202: the lean hunter render (surviving fields only, three-goal order) ---

def test_compose_grounding_renders_only_surviving_fields_goal_ordered():
    """#202 - the hunter render (`_compose_grounding`) shows ONLY the surviving
    fields, ordered by the three goals (feasibility -> the initial
    concretisation -> further directions); the redundant slots' lines are gone."""
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        HuntConfig,
        HuntPromptTemplate,
    )
    from polymerhus.attack.hunting.hunting_agent import _compose_grounding  # noqa: PLC0415

    config = HuntConfig(
        hunt_id="hunt-1", unit_id="Service:slug:a", fault_class="fault-x",
        status="ratified",
        prompt_template=HuntPromptTemplate(
            rationale="r", l0_evidence=["llm: witness"],
            research_direction="CSRF feasibility reasoning"),
        vulnerability_class="CSRF",
        surface_context={"kind": "Service"},
        observed_defences=["WAF blocks XSS payloads"],
        preconditions=["authenticated session obtainable"],
        sub_fault_ids=["CWE-24"],
        prior_hunt_insights=[{"kind": "prior_verdict", "verdict": "unsuccessful"}],
    )
    text = _compose_grounding(config)
    # the surviving fields render
    assert "Orchestrator's fault-matching rationale: r" in text
    assert "Vulnerability class (the initial concretisation): CSRF" in text
    assert "research direction (feasibility): CSRF feasibility reasoning" in text
    assert "L0 fault-applicability evidence: llm: witness" in text
    assert "Observed target defences" in text and "WAF blocks XSS payloads" in text
    assert "Test preconditions" in text and "authenticated session obtainable" in text
    assert "Sub-fault reflection material" in text and "CWE-24" in text
    assert "Prior-hunt insights" in text
    # the redundant slots never render
    for gone in ("technique_primitives", "adversarial_capabilities",
                 "tool_registry", "assumptions", "target caveats"):
        assert gone not in text.lower()
    # the three-goal order: the feasibility fields precede the further-directions ones
    assert text.index("research direction") < text.index("Prior-hunt insights")


def test_config_gaps_matches_the_new_shape():
    """#202 - `_config_gaps` flags the renamed `observed_defences` and the
    merged `preconditions` on their new names, never the old vocabulary."""
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        HuntConfig,
        HuntPromptTemplate,
    )
    from polymerhus.attack.hunting.hunting_agent import _config_gaps  # noqa: PLC0415

    config = HuntConfig(
        hunt_id="hunt-1", unit_id="Service:slug:a", fault_class="fault-x",
        prompt_template=HuntPromptTemplate(rationale="", research_direction=""),
        surface_context={}, observed_defences=[], preconditions=[],
    )
    gaps = _config_gaps(config)
    assert any("observed" in g for g in gaps)
    assert any("preconditions" in g for g in gaps)
    # the renamed slot's gap fires on the new field, never the old name
    assert not any("caveats" in g for g in gaps)
