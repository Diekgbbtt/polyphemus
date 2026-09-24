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
      `LLM_HUNTING` (Q1).
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


# --- the skill rides the system channel (spec-vs-code divergence fix) --------

# The hunting specs call the skill a SYSTEM prompt (the orchestrator's
# [SystemMessage(skill), HumanMessage(prompt)] composed-turn precedent,
# `llm.build_gate_reason_fn`); the harness serves it as `system_prompt=` on
# every `arun_session_turn`, never inside the first HumanMessage.


def _skill_hunt_config():
    """A minimal HuntConfig for the system-channel pins."""
    from polymerhus.attack.hunting.hunt_orchestrator import (  # noqa: PLC0415
        HuntConfig,
        HuntPromptTemplate,
    )

    return HuntConfig(
        hunt_id="hunt-sys", unit_id="Service:slug:a", fault_class="fault-x",
        prompt_template=HuntPromptTemplate(
            rationale="r", research_direction="d"),
        surface_context={"kind": "Service"},
    )


def _run_stubbed_dispatch(monkeypatch, turns):
    """Drive the REAL harness with a stubbed session turn; return (result, calls).

    Each stubbed turn records its `system_prompt` kwarg and input messages, then
    replays the scripted reply (`{"message": AIMessage}` per turn)."""
    import polymerhus.app.llm.session as S  # noqa: PLC0415
    from langgraph.checkpoint.memory import InMemorySaver  # noqa: PLC0415
    from polymerhus.attack.hunting.hunting_agent import (  # noqa: PLC0415
        build_sync_hunting_agent,
    )

    calls: list = []
    cursor = {"i": 0}

    async def fake_turn(role_id, thread_id, new_messages, *, checkpointer,
                        tools=(), **kw):
        calls.append({"role_id": role_id, "new_messages": list(new_messages),
                      "system_prompt": kw.get("system_prompt")})
        reply = turns[min(cursor["i"], len(turns) - 1)]
        cursor["i"] += 1
        return S.SessionTurn(content=reply.get("answer", ""),
                             messages=[reply["message"]],
                             thread_id=thread_id)

    monkeypatch.setattr(S, "arun_session_turn", fake_turn)
    dispatch = build_sync_hunting_agent(
        run_id="run-sys", project_id="proj-a",
        checkpointer=InMemorySaver(), middleware=[], observe=False)
    return dispatch(_skill_hunt_config()), calls


def test_skill_body_rides_system_prompt_not_first_human_message(monkeypatch):
    """(a) the skill body is served as `system_prompt` on the turn, never
    inside the first HumanMessage."""
    from langchain_core.messages import AIMessage  # noqa: PLC0415
    from polymerhus.attack.hunting.hunting_agent import (  # noqa: PLC0415
        _load_hunting_agent_skill,
    )

    skill = _load_hunting_agent_skill()
    assert skill.strip()  # the pin is vacuous on an empty skill - guard it
    _, calls = _run_stubbed_dispatch(
        monkeypatch, [{"answer": "done",
                       "message": AIMessage(content="done")}])
    assert calls[0]["system_prompt"] == skill
    first_human = calls[0]["new_messages"][0].content
    assert skill not in first_human


def test_skill_includes_the_off_path_examples_companion():
    """The off-path worked examples (`prompts/examples.md`) are part of the SAME
    system prompt as `hunting-agent.md` (whose body points at them), so the
    reference resolves instead of dangling on a file the agent cannot read."""
    from polymerhus.attack.hunting.hunting_agent import (  # noqa: PLC0415
        _load_hunting_agent_skill,
    )

    skill = _load_hunting_agent_skill()
    assert "Hunting-agent worked examples" in skill
    assert "Example 2 - coverage re-entry" in skill
    assert "Example 4 - worst case" in skill
    assert "read `examples.md`" not in skill


def test_first_human_message_carries_grounding_surface_state_protocol_in_order(
        monkeypatch):
    """(b) the first HumanMessage still carries grounding + surface + state +
    protocol in order, and no skill body."""
    from langchain_core.messages import AIMessage  # noqa: PLC0415
    from polymerhus.attack.hunting.hunting_agent import (  # noqa: PLC0415
        _load_hunting_agent_skill,
    )

    _, calls = _run_stubbed_dispatch(
        monkeypatch, [{"answer": "done",
                       "message": AIMessage(content="done")}])
    first_human = calls[0]["new_messages"][0].content
    assert _load_hunting_agent_skill() not in first_human
    grounding = first_human.index("You are dispatched to hunt")
    surface = first_human.index("Tool surface")
    state = first_human.index("phase:")
    protocol = first_human.index("Each turn you either call")
    assert grounding < surface < state < protocol


def test_two_step_scripted_dispatch_terminates_with_terminal_assembly(
        monkeypatch):
    """(c) a two-step scripted-model dispatch still terminates with the same
    terminal assembly (no derived verdict, concluded phase in the feedback)."""
    from langchain_core.messages import AIMessage  # noqa: PLC0415

    result, _ = _run_stubbed_dispatch(monkeypatch, [
        {"message": AIMessage(content="", tool_calls=[{
            "name": "kb_query",
            "args": {"scenario_id": "s", "attack_goal": "g", "concern": "c"},
            "id": "t1", "type": "tool_call"}])},
        {"answer": "candidate set exhausted",
         "message": AIMessage(content="candidate set exhausted")},
    ])
    assert result.hypothesis_verdict is None
    assert "phase: concluded" in result.feedback
    assert "candidate set exhausted" in result.feedback


def test_resumed_thread_second_turn_still_carries_the_skill(monkeypatch):
    """(d) the resumed-thread second turn still carries the skill: the harness
    rebuilds the agent every turn and the checkpointer never persists the
    system message, so the skill is passed on EVERY turn."""
    from langchain_core.messages import AIMessage  # noqa: PLC0415
    from polymerhus.attack.hunting.hunting_agent import (  # noqa: PLC0415
        _load_hunting_agent_skill,
    )

    skill = _load_hunting_agent_skill()
    _, calls = _run_stubbed_dispatch(monkeypatch, [
        {"message": AIMessage(content="", tool_calls=[{
            "name": "kb_query",
            "args": {"scenario_id": "s", "attack_goal": "g", "concern": "c"},
            "id": "t1", "type": "tool_call"}])},
        {"answer": "done", "message": AIMessage(content="done")},
    ])
    assert len(calls) == 2
    assert calls[0]["system_prompt"] == skill
    assert calls[1]["system_prompt"] == skill


def test_scripted_model_sees_system_skill_first_through_the_real_session():
    """The model itself receives the skill as the leading SystemMessage through
    the REAL session path (the `create_agent` ephemeral prepend): the first
    message the scripted model is handed carries the skill, the second carries
    the grounding without it - on BOTH turns of a resumed thread."""
    from tests.hunting_fixtures import (  # noqa: PLC0415
        _answer,
        _hunt_config,
        _tool_call,
        build_hunter_agent,
        build_memory_store,
    )
    from polymerhus.attack.hunting.hunting_agent import (  # noqa: PLC0415
        _load_hunting_agent_skill,
    )

    skill = _load_hunting_agent_skill()
    from polymerhus.app.llm.skills import (  # noqa: PLC0415
        render_skill_index,
        skill_meta,
        skills_for_role,
    )

    # The role's bounded skill set rides the same system channel, after the
    # skill: `skill` verbatim, blank line, L1 index (the shared renderer's
    # exact composition - never hand-written here).
    index = render_skill_index(skills_for_role("hunting_hunter"))
    seen: list = []
    import tempfile  # noqa: PLC0415

    with tempfile.TemporaryDirectory() as tmp:
        from pathlib import Path  # noqa: PLC0415

        agent = build_hunter_agent(
            build_memory_store(Path(tmp)),
            steps=[_tool_call("kb_query", {"scenario_id": "s", "attack_goal": "g",
                                           "concern": "c"}),
                   _answer("done")],
            seen=seen)
        result = agent(_hunt_config())
    assert result.hypothesis_verdict is None
    assert "phase: concluded" in result.feedback
    assert len(seen) == 2
    for turn_messages in seen:
        assert turn_messages[0] == f"{skill}\n\n{index}"  # the leading SystemMessage
        assert "steel-browser" in turn_messages[0]  # the bounded set is indexed
        # ... and the line the model actually reads is the skill's frontmatter
        # `description` VERBATIM (not a paraphrase, not a re-render).
        assert skill_meta("steel-browser")["description"] in turn_messages[0]
        assert skill not in turn_messages[1]  # the grounding HumanMessage
        assert "You are dispatched to hunt" in turn_messages[1]
