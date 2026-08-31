"""Unit tier: the hunting module's LLM bootstrap + role wiring (`attack/hunting/llm.py`, #94).

The hunting roles (`hunting_orchestrator`, `hunting_hunter`) are validated at the
HUNTING bootstrap, never app boot (operator ruling 2026-08-06); and the
orchestrator's `reason_fn`/`rematch_fn` and the hunting agent's `author`/`judge`
seams bind to a model through `invoke_role` on those roles. These tests exercise
that at the public seam with a FAKE `invoke_role` - the unit tier touches no live
model (CODING_STANDARD sections 6, 10).
"""
from __future__ import annotations

import pytest

from polymerhus.app.llm import providers as P
from polymerhus.attack.hunting import llm as HL
from polymerhus.attack.hunting.hunt_orchestrator import (
    DeliveredCandidate,
    GateDecision,
    GateInput,
    MatchVerdict,
    Witness,
)
from polymerhus.recon.control.targeted import TargetedReconResult


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


# --- the gate reasoning seam (hunting_orchestrator) ---------------------------

def _gate_input() -> GateInput:
    return GateInput(
        candidates=[DeliveredCandidate(
            unit_id="u1", fault_class="idor",
            applies_witnesses=Witness(deterministic="d", llm="looks addressable"),
            match_verdict="applies",
        )],
        kb_degraded=False, kb_evidences={}, surface=[],
    )


def test_gate_reason_fn_invokes_hunting_orchestrator_with_gatedecision_schema(monkeypatch):
    seen = {}

    def fake_invoke_role(role, messages, *, schema=None, **kw):
        seen["role"] = role
        seen["schema"] = schema
        return GateDecision(directions=[])

    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role", fake_invoke_role)
    out = HL.build_gate_reason_fn()(_gate_input())
    assert seen["role"] == "hunting_orchestrator"
    assert seen["schema"] is GateDecision
    assert isinstance(out, GateDecision)


def test_gate_reason_fn_degrades_none_to_empty_decision(monkeypatch):
    """A None/unparseable structured result surfaces as an empty GateDecision, which
    `run_orchestration` treats identically to a gate that carried nothing (fail-open
    is the orchestrator's job, never a raise here)."""
    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role",
                        lambda *a, **k: None)
    out = HL.build_gate_reason_fn()(_gate_input())
    assert isinstance(out, GateDecision)
    assert out.directions == []


# --- the re-match seam (hunting_orchestrator) ---------------------------------

def _result() -> TargetedReconResult:
    return TargetedReconResult(correlation_id="c", requester_id="r",
                               origin="hunting", status="success")


def test_rematch_fn_invokes_hunting_orchestrator_with_matchverdict_schema(monkeypatch):
    seen = {}

    def fake_invoke_role(role, messages, *, schema=None, **kw):
        seen["role"] = role
        seen["schema"] = schema
        return MatchVerdict(unit_id="u1", fault_class="idor", verdict="applies")

    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role", fake_invoke_role)
    out = HL.build_rematch_fn()("u1", "idor", _result())
    assert seen["role"] == "hunting_orchestrator"
    assert seen["schema"] is MatchVerdict
    assert out.verdict == "applies"


def test_rematch_fn_degrades_none_to_insufficient_evidence(monkeypatch):
    """A None result never fabricates an 'applies': it degrades to
    insufficient-evidence, which the orchestrator's depth-1 cap lands as unresolved."""
    monkeypatch.setattr("polymerhus.app.llm.roles.invoke_role", lambda *a, **k: None)
    out = HL.build_rematch_fn()("u1", "idor", _result())
    assert out.unit_id == "u1" and out.fault_class == "idor"
    assert out.verdict == "insufficient-evidence"


# --- the hunting agent's author / judge seams (hunting_hunter) ----------------

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


# --- the rich projection render (candidates-rewrite T5, spec 3.7) -------------

def test_render_projection_renders_rich_slots_sorted():
    """T5: `_render_projection` renders the rich typed slots the T2 projection
    carries - the exploded DataItems (name/type/sensitivity), the fully-unpacked
    target System on each edge, the DataRelationship kind chains, and the D3
    cooperating-systems adjacency - IN ADDITION to the compat facets (kind,
    spine, edges target_kind+role), sorted deterministically throughout. The
    data-edge counts and the DataRelationship kinds are NOT rendered: they are
    redundant with the exploded DataItems and the relationship chains
    (the operator ruling 2026-08-28)."""
    from polymerhus.attack.hunting.unit_projection import (  # noqa: PLC0415
        DataItem,
        DataRelationship,
        EdgeInfo,
        SystemInfo,
        UnitProjection,
    )

    proj = UnitProjection(
        unit_id="Service:orders",
        kind="Service",
        spine={"exposure": "public"},
        edges={"EXPOSED_VIA": (EdgeInfo(
            family="EXPOSED_VIA", target_kind="WebPresentation",
            target=SystemInfo(
                kind="WebPresentation", discriminator="orders::cart",
                exposure="public", description="the cart pages",
                props={"kind": "WebPresentation", "rendering_model": "CSR"})),)},
        data_edges={"PRODUCES": 1, "CONSUMES": 1},
        data_rel_kinds=frozenset({"DERIVED_FROM"}),
        data_items={
            "PRODUCES": (DataItem(item_key="order", name="order", type="record",
                                  sensitivity="high"),),
            "CONSUMES": (DataItem(item_key="session token", name="session token",
                                  type="secret", sensitivity="critical"),),
        },
        data_relationships=(DataRelationship(
            family="DERIVED_FROM", from_item_key="line", to_item_key="basket",
            predicate="line = basket.items"),),
        cooperating_systems={"DEPENDS_ON": (SystemInfo(
            kind="ReverseProxy", discriminator="proxy-1", exposure="public"),)},
    )
    text = HL._render_projection(proj)
    # the compat facets survive unchanged
    assert "unit kind: Service" in text
    assert "spine (present keys): ['exposure']" in text
    # the data-edge counts / data-rel kinds are NOT rendered (4326958 ruling:
    # redundant with the exploded data items + relationship chains)
    assert "data edges:" not in text
    assert "data-relationship kinds:" not in text
    # the rich slots render, each sorted
    assert "data items:" in text
    assert "- PRODUCES: name=order; type=record; sensitivity=high" in text
    assert "- CONSUMES: name=session token; type=secret; sensitivity=critical" in text
    assert "data relationships:" in text
    assert "- DERIVED_FROM: line -> basket (predicate: line = basket.items)" in text
    assert "cooperating systems:" in text
    assert "- DEPENDS_ON: kind=ReverseProxy; discriminator=proxy-1; " \
        "exposure=public" in text
    # the fully-unpacked target System rides the edge render
    assert "kind=WebPresentation; discriminator=orders::cart" in text
    assert "exposure=public; description=the cart pages" in text
    assert "props={rendering_model=CSR}" in text
    # deterministic: the section order is stable
    assert text.index("data items:") < text.index("data relationships:") \
        < text.index("cooperating systems:")


def test_render_projection_absent_rich_slots_degrade_fail_open():
    """T5: a projection with the rich slots absent (or the attributes missing
    entirely, the `object | None` slot contract) renders each as a '(none)'
    line - never a raise, never a prune signal."""
    from polymerhus.attack.hunting.unit_projection import (  # noqa: PLC0415
        UnitProjection,
    )

    sparse = UnitProjection(
        unit_id="Service:ghost", kind="Service",
        spine={"exposure": "public"}, edges={},
        data_edges={}, data_rel_kinds=frozenset(),
    )
    text = HL._render_projection(sparse)
    assert "unit kind: Service" in text
    assert "data items: (none)" in text
    assert "data relationships: (none)" in text
    assert "cooperating systems: (none)" in text
    assert "FALSE" not in text

    class Sparse:
        kind = "System"
        spine = {}
        edges = {}
        data_edges = {}
        data_rel_kinds = frozenset()

    text = HL._render_projection(Sparse())  # no rich attrs at all
    assert "unit kind: System" in text
    assert "data items: (none)" in text
    assert "data relationships: (none)" in text
    assert "cooperating systems: (none)" in text


# --- _parse_json_object: free-text D4/D5 replies -------------------------------


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
