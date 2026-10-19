"""Unit tier: the hunting module's LLM bootstrap + role wiring (`attack/hunting/llm.py`, #94).

The hunting roles (`hunting_threat_modeller`, `hunting_hunter`) are validated at the
HUNTING bootstrap, never app boot (operator ruling 2026-08-06); and the
orchestrator's `reason_fn` and the hunting agent's `author`/`judge`
seams bind to a model through `invoke_role` on those roles. These tests exercise
that at the public seam with a FAKE `invoke_role` - the unit tier touches no live
model (CODING_STANDARD sections 6, 10).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from polymerhus.app.llm import providers as P
from polymerhus.attack.hunting import llm as HL


# --- the off-app-boot bootstrap validation -----------------------------------

def test_validate_hunting_llm_config_demands_hunting_vars(monkeypatch):
    """`validate_hunting_llm_config()` is the hunting module's OWN fail-fast: with
    the hunting model vars absent it raises (unlike app boot, which never demands
    them), and with them present it passes."""
    for r in P.HUNTING_ROLES:
        monkeypatch.delenv(r.model_key, raising=False)
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    with pytest.raises(P.LLMConfigError) as e:
        HL.validate_hunting_llm_config()
    assert "HUNTING" in str(e.value)

    for r in P.HUNTING_ROLES:
        monkeypatch.setenv(r.model_key, "swissai:x")
    HL.validate_hunting_llm_config()  # now configured: no raise


def test_author_fn_invokes_hunter_and_parses_json(monkeypatch):
    seen = {}

    def fake_invoke_role(role, messages, *, schema=None, **kw):
        seen["role"] = role
        seen["schema"] = schema
        return '{"target_identity": {"url": "http://u1/", "unit_id": "u1"}, "rationale": "r"}'

    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role", fake_invoke_role)
    spec = HL.build_author_fn()("compose the D4 spec ...")
    assert seen["role"] == "hunting_hunter"
    assert seen["schema"] is None            # free-text, not a pydantic schema
    assert spec == {"target_identity": {"url": "http://u1/", "unit_id": "u1"}, "rationale": "r"}


def test_author_fn_parses_fenced_json_block(monkeypatch):
    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role",
                        lambda *a, **k: '```json\n{"a": 1}\n```')
    assert HL.build_author_fn()("x") == {"a": 1}


def test_judge_fn_returns_none_on_unparseable_reply(monkeypatch):
    """A non-JSON reply degrades to None - the hunting agent already treats that as
    a no-meaningful-insight / degraded judgment (fail-open), never a crash."""
    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role",
                        lambda *a, **k: "I could not decide.")
    assert HL.build_judge_fn()("x") is None


def test_author_and_judge_share_ONE_per_hunt_thread_when_session_bound(monkeypatch):
    """Bound to a hunt session, the hunter's turns run STATEFUL on ONE thread per hunt:
    the author and the judge of the SAME hunt resume the SAME thread (so the judge sees
    the author's reasoning), while a different hunt gets a distinct thread (no collision)."""
    import polymerhus.app.llm.session as S

    seen = []

    def fake_stateful_turn(role, thread, messages, *, checkpointer, schema=None, **kw):
        seen.append((role, getattr(thread, "thread_id", thread)))
        return '{"ok": true}'

    monkeypatch.setattr(S, "stateful_turn", fake_stateful_turn)
    with HL.hunt_session("run1", "hunt-A"):
        assert HL.build_author_fn()("author prompt") == {"ok": True}
        assert HL.build_judge_fn()("judge prompt") == {"ok": True}
    with HL.hunt_session("run1", "hunt-B"):
        HL.build_author_fn()("x")

    assert seen[0] == ("hunting_hunter", "run1:hunt-A:hunting_hunter")
    assert seen[1] == ("hunting_hunter", "run1:hunt-A:hunting_hunter")  # SAME thread -> shared memory
    assert seen[2] == ("hunting_hunter", "run1:hunt-B:hunting_hunter")  # other hunt -> distinct thread


def test_hunt_session_context_reads_the_bound_binding_only_inside_a_hunt():
    """The public `hunt_session_context()` getter returns the typed binding set by
    `hunt_session()` (None outside it) - the pod's session binding (D84-7) reads
    this to derive the pod run's run_id/hunt_id from an enclosing hunt."""
    assert HL.hunt_session_context() is None
    with HL.hunt_session("run1", "hunt-A"):
        ctx = HL.hunt_session_context()
        assert ctx is not None
        assert ctx.address.role_id == "hunting_hunter"
        assert ctx.address.run_id == "run1"
        assert ctx.address.hunt_id == "hunt-A"
    assert HL.hunt_session_context() is None


def test_hunter_turn_threads_the_hunt_project_as_usage_scope(monkeypatch):
    """The bound project rides the hunter's stateful turn as `usage_scope`, so its
    tokens land in the project's ledger bucket."""
    import polymerhus.app.llm.session as S

    seen = {}

    def fake_stateful_turn(role, thread, messages, *, checkpointer, schema=None, **kw):
        seen["usage_scope"] = kw.get("usage_scope")
        return '{"ok": true}'

    monkeypatch.setattr(S, "stateful_turn", fake_stateful_turn)
    with HL.hunt_session("run1", "hunt-A", project_id="proj-1"):
        HL.build_author_fn()("author prompt")
    assert seen["usage_scope"] == "proj-1"


# --- the rich projection render (candidates-rewrite T5, spec 3.7) -------------

def test_parse_json_object_extracts_fenced_block_after_prose():
    """A live D4 reply may open with prose and THEN carry a ```json fence (the
    model's free-text answer before the spec); the parser must recover it."""
    reply = (
        "The LightRAG retrieval returned a fallback, so I ground the spec in "
        "the rationale.\n\n"
        '```json\n{"target_identity": {"url": "http://a/", "unit_id": "Service:slug:a"}, "rationale": "spec"}\n```\n'
    )
    assert HL._parse_json_object(reply) == {
        "target_identity": {"url": "http://a/", "unit_id": "Service:slug:a"},
        "rationale": "spec",
    }


def test_parse_json_object_keeps_leading_fence_support():
    reply = '```json\n{"meaningful_insight": false, "next_step": "end"}\n```'
    assert HL._parse_json_object(reply) == {
        "meaningful_insight": False,
        "next_step": "end",
    }


def test_parse_json_object_rejects_unfenced_prose_with_inline_json():
    # No code fence: prose-plus-json stays unparseable (fail-open), so the
    # harness treats the turn as degraded instead of guessing.
    assert HL._parse_json_object('Here is the answer {"ok": true}.') is None


def test_parse_json_object_passthrough_and_empty():
    assert HL._parse_json_object({"ok": True}) == {"ok": True}
    assert HL._parse_json_object("") is None
    assert HL._parse_json_object(None) is None


# --- #292: the single-sourced surgical-conciseness directive ------------------

def test_conciseness_directive_is_single_sourced_and_names_the_cap():
    """The canonical directive (#292) lives once in `conciseness.py` (`llm.py`
    re-exports it) and names the ~500-char cap while covering the spec
    `rationale` and note bodies."""
    d = HL.HUNTING_CONCISENESS_DIRECTIVE
    assert "500" in d
    assert "rationale" in d
    assert "note" in d and "body" in d


def test_conciseness_directive_appears_verbatim_in_every_role_prompt():
    """Drift guard: the exact constant text is present in each hunting role
    prompt that writes a config family, so the writing discipline reaches every
    agent that decides what to write. The modeller's prompts carry the same cap
    through the store/notes tool DESCRIPTIONS (`append_conciseness_directive`),
    not its system prompt."""
    prompts_dir = Path(HL.__file__).resolve().parent / "prompts"
    for name in ("hunting-agent.md", "pod-runner.md", "pod-triager.md"):
        text = (prompts_dir / name).read_text(encoding="utf-8")
        assert HL.HUNTING_CONCISENESS_DIRECTIVE in text, name
