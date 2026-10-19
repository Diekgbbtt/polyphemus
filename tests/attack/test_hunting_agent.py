"""Unit tier: the hunting agent's pure mechanics and the role registration.

The catalogue predicates C1-C17 live in
tests/integration/test_hunting_agent_contracts.py and are never repeated in
this tier's red/green loop (testing-strategy.md section 2, the #82 precedent).
This tier pins the pure functions the harness relies on:

  derive_technological_axis(card)
      - the deterministic technological axis for the `(fault-class, axis)`
        KB join key (IA-8, D10): derived from the unit's index card, never
        a typed predicate facet (#66 non-conflation).

  ROLES - the `hunting` role joins the LLM role registry keyed by
      `LLM_HUNTING` (Q1).

The retired D7 verdict derivation (`derive_verdict`) left with T5 (#378): the
verdict-consumption graph is out of scope and nothing live derived a verdict.
"""
import pytest

from polymerhus.attack.hunting.hunting_agent import (
    HypothesisVerdict,
    derive_technological_axis,
)
from polymerhus.app.llm.providers import HUNTING_ROLES, ROLES


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

def test_compose_grounding_renders_the_loop_payload():
    """The first-step grounding renders the loop payload's context (S2 8.2):
    the unit and loop, the two classes, the trust agreement, the programming
    fault, the technical sharpening, the evidence and the target context - and
    never a retired config field or a failure mode."""
    from polymerhus.attack.hunting.hunting_agent import _compose_grounding  # noqa: PLC0415
    from tests.hunting_fixtures import _hunter_payload

    payload = _hunter_payload()
    text = _compose_grounding(payload)
    assert "You are dispatched to hunt Service:slug:a" in text
    assert "Loop: loop-1" in text and "Service-slug-a__loop-1" in text
    assert "Canonical class: IDOR" in text
    assert "web-vulnerability suite class: idor" in text
    assert "An anonymous caller reads another user's item." in text
    assert "improper authorisation on the item lookup" in text
    assert "ta-1" in text and "ia-1" in text
    assert "GET /api/a" in text
    for gone in ("HuntConfig", "failure_modes", "payload_vector_space",
                 "technique_primitives", "prior_hunt_insights"):
        assert gone not in text


def test_payload_gaps_flags_the_missing_grounding():
    """The O3 gap flags name each missing payload part; a complete payload
    flags nothing."""
    from polymerhus.attack.hunting.hunting_agent import _payload_gaps  # noqa: PLC0415
    from tests.hunting_fixtures import _hunter_payload

    assert _payload_gaps(_hunter_payload()) == []
    gaps = _payload_gaps({})
    assert any("unit identity" in g for g in gaps)
    assert any("programming fault" in g for g in gaps)
    assert any("trust agreement" in g for g in gaps)


def test_hunting_roles_are_registered_off_app_boot():
    """The hunting agents are their own role_ids in HUNTING_ROLES (validated at the
    hunting module bootstrap), never in the app-boot ROLES (operator ruling
    2026-08-06). Both are `session` agents."""
    hunting_ids = {r.role_id for r in HUNTING_ROLES}
    assert hunting_ids == {"hunting_threat_modeller", "hunting_orchestrator",
                           "hunting_hunter", "pod_runner", "pod_triager"}
    assert not (hunting_ids & {r.role_id for r in ROLES})  # off app boot
    assert all(r.agent_mode == "session" for r in HUNTING_ROLES)


def test_hypothesis_verdict_vocabulary_is_four_valued():
    assert set(HypothesisVerdict.__args__) == {
        "successful", "unsuccessful", "insufficient-evidence", "underspecified-spec",
    }


# --- the skill rides the system channel (spec-vs-code divergence fix) --------

# The hunting specs call the skill a SYSTEM prompt (the orchestrator's
# [SystemMessage(skill), HumanMessage(prompt)] composed-turn precedent,
# `llm.build_gate_reason_fn`); the harness serves it as `system_prompt=` on
# every `arun_session_turn`, never inside the first HumanMessage.


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
                      "system_prompt": kw.get("system_prompt"),
                      "usage_scope": kw.get("usage_scope")})
        reply = turns[min(cursor["i"], len(turns) - 1)]
        cursor["i"] += 1
        return S.SessionTurn(content=reply.get("answer", ""),
                             messages=[reply["message"]],
                             thread_id=thread_id)

    monkeypatch.setattr(S, "arun_session_turn", fake_turn)
    dispatch = build_sync_hunting_agent(
        run_id="run-sys", project_id="proj-a",
        checkpointer=InMemorySaver(), middleware=[], observe=False)
    from tests.hunting_fixtures import _hunter_payload  # noqa: PLC0415

    return dispatch(_hunter_payload()), calls


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


def test_hunter_turns_thread_the_project_as_usage_scope(monkeypatch):
    """The hunter's tokens are attributed to the harness's project in the ledger."""
    from langchain_core.messages import AIMessage  # noqa: PLC0415

    _, calls = _run_stubbed_dispatch(
        monkeypatch, [{"answer": "done", "message": AIMessage(content="done")}])
    assert calls[0]["usage_scope"] == "proj-a"


def test_skill_includes_the_off_path_examples_companion():
    """The off-path worked examples (`prompts/examples.md`) are part of the SAME
    system prompt as `hunting-agent.md` (whose body points at them), so the
    reference resolves instead of dangling on a file the agent cannot read."""
    from polymerhus.attack.hunting.hunting_agent import (  # noqa: PLC0415
        _load_hunting_agent_skill,
    )

    skill = _load_hunting_agent_skill()
    assert "Hunting-agent worked examples" in skill
    assert "Example 2 - well-formedness re-entry" in skill
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
    state = first_human.index("state: grounding")
    protocol = first_human.index("Each turn you either call")
    assert grounding < surface < state < protocol


def test_two_step_scripted_dispatch_terminates_with_terminal_assembly(
        monkeypatch):
    """(c) a two-step scripted-model dispatch still terminates with the same
    terminal assembly (no derived verdict, the tracked pass in the feedback)."""
    from langchain_core.messages import AIMessage  # noqa: PLC0415

    result, _ = _run_stubbed_dispatch(monkeypatch, [
        {"message": AIMessage(content="", tool_calls=[{
            "name": "kb_query",
            "args": {"scenario_id": "s", "attack_goal": "g", "concern": "c"},
            "id": "t1", "type": "tool_call"}])},
        {"answer": "candidate set exhausted",
         "message": AIMessage(content="candidate set exhausted")},
    ])
    assert result["state"] == "grounding"
    assert "state: grounding" in result["feedback"]
    assert "candidate set exhausted" in result["feedback"]


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
        _hunter_payload,
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
        result = agent(_hunter_payload())
    assert result["state"] is not None
    assert "state: grounding" in result["feedback"]
    assert len(seen) == 2
    for turn_messages in seen:
        assert turn_messages[0] == f"{skill}\n\n{index}"  # the leading SystemMessage
        assert "steel-browser" in turn_messages[0]  # the bounded set is indexed
        # ... and the line the model actually reads is the skill's frontmatter
        # `description` VERBATIM (not a paraphrase, not a re-render).
        assert skill_meta("steel-browser")["description"] in turn_messages[0]
        assert skill not in turn_messages[1]  # the grounding HumanMessage
        assert "You are dispatched to hunt" in turn_messages[1]


# --- #312: a RAW provider error at the REAL turn seam pauses the run ----------

def _raw_error_hunt(tmp_path, exc):
    """Drive the REAL harness turn seam with `model_factory` raising `exc`.

    The store, the five-tool surface, the compiled graph, and the live session
    edge all ride; only the model raises. Returns the dispatch result when the
    harness swallows the raise, or raises whatever escapes."""
    from langgraph.checkpoint.memory import InMemorySaver  # noqa: PLC0415

    from tests.hunting_fixtures import (  # noqa: PLC0415
        _RaisingModel,
        _hunter_payload,
        _openai_rate_limit_error,
        build_memory_store,
    )
    from polymerhus.attack.hunting.hunting_agent import (  # noqa: PLC0415
        build_sync_hunting_agent,
    )

    dispatch = build_sync_hunting_agent(
        run_id="run-312", project_id="proj-a",
        memory_store=build_memory_store(tmp_path),
        model_factory=lambda role_id: _RaisingModel(exc=exc),
        checkpointer=InMemorySaver(), middleware=[], observe=False,
    )
    return dispatch(_hunter_payload())


def test_raw_rate_limit_error_at_the_turn_seam_pauses_the_run(tmp_path):
    """#312: the production hunter turn raises a RAW `openai.RateLimitError`,
    never the typed `ProviderUnavailableError`. The harness must CLASSIFY it at
    the seam and propagate the typed error so the run pauses (`interrupted`)
    instead of degrading to a spec-less result and quiescing `complete` with
    zero specs - the trial-2 outcome."""
    from tests.hunting_fixtures import _openai_rate_limit_error  # noqa: PLC0415
    from polymerhus.app.llm.provider_failure import ProviderUnavailableError

    with pytest.raises(ProviderUnavailableError) as excinfo:
        _raw_error_hunt(tmp_path, _openai_rate_limit_error())
    assert excinfo.value.status_code == 429


def test_raw_timeout_error_at_the_turn_seam_pauses_the_run(tmp_path):
    """#312: the same classification seam must type a raw `TimeoutError` (a
    provider transport failure with no HTTP status)."""
    from polymerhus.app.llm.provider_failure import ProviderUnavailableError

    with pytest.raises(ProviderUnavailableError):
        _raw_error_hunt(tmp_path, TimeoutError("read timed out"))


def test_non_provider_raw_error_still_degrades_fail_open(tmp_path):
    """#312: no over-triggering - a genuine non-provider internal error keeps
    the O3/C2/C3 fail-open degrade (a spec-less outcome), never an
    untyped raise misclassified as a provider failure."""
    result = _raw_error_hunt(tmp_path, RuntimeError("hypothesis store exploded"))
    assert result["state"] == "grounding"
    assert "hunter turn unavailable" in result["feedback"]
    assert "hypothesis store exploded" in result["feedback"]
