"""E3-E9 e2e predicates for the hunting agent in ISOLATION (spec section 6.2).

The hunting agent's OWN infrastructure seams are REAL here: the REAL harness
under test (this build's artifact), the REAL append-only markdown hunt store
on the filesystem (S7 record files with `_seq`/`_ref` provenance), the REAL
stable system prompt resolved from `skills/hunting/hunting-agent/SKILL.md`
through the shared `skill_for` (implementation doc 4.10, embedded ahead of
every LLM turn), the REAL deterministic technological-axis derivation forming
the KB join key (IA-8), and the REAL tracing seam against the configured
Langfuse (best-effort, fail-open). Only the un-built collaborators are
fixtures at their contract boundaries - the pod (IA-3/IA-4, #84), the
spec-authoring and continuation-judgment LLM turns (Q8/D5), and the
symptom-technique KB content (operator-built external, IA-8). That is exactly
the fixture-agent contract spec section 3 sanctions; the REAL pod chain is the
blocked E1/E2 walkthrough's live edge
(test_hunting_agent_walkthrough.py), never substituted here.

Why this file exists (the gap it closes): C1-C17 (integration tier) drive the
agent with canned KB results and per-test tmp_path stores, asserting the
records read back in-memory; nothing asserted that (a) the ratified
decision-tree verbatims actually REACH the LLM turns (the loader was dead
code - fixed in this build), (b) the S7 persistence lands as real files with
provenance, (c) the automated join key is queried once per hunt across
differently-typed units, or (d) the tracing seam holds against a configured
observability stack. This catalogue pins all of those.

Source: docs/design/hunting-67-hunting-agent-spec.md section 6.2 (isolated
predicates, added 2026-08-05).
"""
from __future__ import annotations

import os
import uuid

import pytest

from polymerhus.attack.hunting.hunt_orchestrator import (
    HuntConfig,
    HuntPromptTemplate,
)
from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.attack.hunting.hunting_agent import derive_technological_axis
from polymerhus.attack.hunting.hunting_tracing import (
    flush_hunting_traces,
    hunting_span,
)
from tests.hunting_fixtures import (
    SPEC,
    SPEC_REAUTHORED,
    _agent,
    _author,
    _judge,
    _kb,
    _no_judge,
    _outcome,
    _pod,
)

SERVICE_A = "Service:slug:a"
SYSTEM_B = "System:key:b"
FAULT_X = "fault-x"
FAULT_Y = "fault-y"

# The real adapted index-cards (D3 part 2): a Service riding a REST mechanism
# (api_paradigm on its spine) and a System riding a CSR mechanism
# (navigation_model), so the automated join-key axes differ per unit kind.
CARD_SERVICE = {
    "kind": "Service",
    "key": {"business_function_slug": "a"},
    "label": "a",
    "spine": {"exposure": "public", "api_paradigm": "REST"},
    "edge_degree": {"EXPOSED_VIA": 1},
    "nl_handles": {},
}

CARD_SYSTEM = {
    "kind": "System",
    "key": {"kind": "key", "discriminator": "b"},
    "label": "b",
    "spine": {"rendering_model": "CSR", "navigation_model": "CSR"},
    "edge_degree": {},
    "nl_handles": {},
}


def _config(unit_id: str, fault_class: str, *, card: dict, **overrides) -> HuntConfig:
    base = HuntConfig(
        hunt_id="hunt-" + uuid.uuid4().hex[:8],
        unit_id=unit_id,
        fault_class=fault_class,
        prompt_template=HuntPromptTemplate(
            rationale=f"{fault_class} applies to {unit_id} because ...",
            extension_points=["csrf-probe"],
            assumptions=["public exposure"],
            supposed_payload_vectors=["q=value"],
            l0_evidence=["GET /api/a answers 200"],
        ),
        surface_context={"cards": [card]},
        target_caveats=["perimeter WAF on /api/*"],
        prior_hunt_insights=[],
        tool_registry=[{"technique": "csrf-probe"}],
    )
    return base.model_copy(update=overrides)


def _skill_text() -> str:
    """The REAL stable system prompt as resolved in-process (the harness's own
    loader), for marker assertions on the composed turns."""
    from polymerhus.attack.hunting import hunting_agent

    return hunting_agent._load_hunting_agent_skill()


# --- E3: the ratified verbatims reach every LLM turn --------------------------
# Implementation doc 4.10: the stable system prompt is embedded ahead of each
# per-invocation turn. This pins the wiring (the loader was dead code before
# this build) AND that the REAL skill resolved - the fallback carries none of
# the decision-tree pass markers.

def test_E3_real_skill_reaches_authoring_and_judgment_turns(tmp_path):
    store = HuntStore(tmp_path)
    author_calls: list = []
    judge_calls: list = []
    run_id = "run-e3"
    agent = _agent(
        store, run_id,
        kb=_kb(),
        pod=_pod(outcomes=[_outcome(
            "no-symptom-evidence",
            evidence={"clean": False, "interpretations": [
                {"variant": "v1", "note": "observations unreachable"},
            ]},
        )]),
        author=_author([SPEC, SPEC_REAUTHORED], calls=author_calls),
        judge=_judge([
            {"meaningful_insight": False, "next_step": "end",
             "rationale": "no insight in the blocked trail"},
        ], calls=judge_calls),
    )

    result = agent(_config(SERVICE_A, FAULT_X, card=CARD_SERVICE))

    # The real skill resolved (pass markers exist ONLY in the repo skill, and
    # the fallback's signature sentence is absent), embedded ahead of the
    # authoring turn.
    skill = _skill_text()
    assert "VERIFY-CLAIMS" in skill and "SPEC-WRITE" in skill and "GROUND" in skill
    authoring = author_calls[0]
    assert authoring.startswith("You are the hunting agent:")
    assert "VERIFY-CLAIMS" in authoring and "SPEC-WRITE" in authoring
    # The REAL skill resolved, not the terse fallback: the fallback is a ~700
    # char paragraph with no pass markers and no section headings.
    assert len(authoring) > 5000
    assert "## Vocabulary, fixed" in authoring
    # The per-invocation user prompt rides after the skill, carrying the five
    # parts and the KB join key.
    assert "fault-x" in authoring and SERVICE_A in authoring
    assert "Symptom-technique KB retrieval on (fault-x, rest)" in authoring
    # The blocked trail consulted the judgment seam; its turn carries the
    # skill too.
    assert len(judge_calls) == 1
    judging = judge_calls[0]
    assert judging.startswith("You are the hunting agent:")
    assert "VERIFY-CLAIMS" in judging
    assert "meaningful_insight" in judging
    # D67-12: the guard ended the evaluation; the hunt degraded with feedback.
    assert result.hypothesis_verdict == "unsuccessful"
    assert result.feedback and "unreachable" in result.feedback


# --- E4: the S7 persistence is REAL files with provenance ---------------------
# Q6: the agent writes exactly the `spec` and `evidence` kinds; each lands as
# an append-only markdown file under the run dir with store-wide ordering.

def test_E4_real_file_persistence_with_provenance(tmp_path):
    store = HuntStore(tmp_path)
    run_id = "run-e4"
    agent = _agent(
        store, run_id,
        kb=_kb(result={"symptoms": ["csrf-absent"], "probing_techniques": ["csrf-probe"]}),
        pod=_pod(outcomes=[_outcome("symptom-confirmed", verdict="successful")]),
        author=_author(),
        judge=_no_judge(),
    )

    result = agent(_config(SERVICE_A, FAULT_X, card=CARD_SERVICE))

    assert result.hypothesis_verdict == "successful"
    spec_file = tmp_path / run_id / "spec.md"
    evidence_file = tmp_path / run_id / "evidence.md"
    assert spec_file.is_file() and evidence_file.is_file()
    # The files actually carry the records (raw markdown round-trips).
    assert "## " in spec_file.read_text()
    # The in-memory listing agrees with the files, one record per kind.
    specs = store.list_records(run_id, "spec")
    evidence = store.list_records(run_id, "evidence")
    assert len(specs) == 1 and len(evidence) == 1
    # Store-wide provenance: _seq/_ref carry run, kind, and ordering.
    assert specs[0]["_seq"] == 1 and evidence[0]["_seq"] == 2
    assert specs[0]["_ref"] == f"{run_id}/spec-0001"
    assert evidence[0]["_ref"] == f"{run_id}/evidence-0002"
    # The result's refs are the file records' refs, and the spec record is the
    # flattened D4 typed base plus the hunt identity.
    assert result.spec_ref == specs[0]["_ref"]
    assert result.pod_result_ref == evidence[0]["_ref"]
    assert specs[0]["hunt_id"] and specs[0]["unit_id"] == SERVICE_A
    assert specs[0]["fault_class"] == FAULT_X
    assert specs[0]["target_identity"] and specs[0]["verification_symptoms"]
    assert evidence[0]["derived_verdict"] == "successful"
    assert evidence[0]["terminal_reason"] == "symptom-confirmed"


# --- E5: the automated KB join key, once per hunt, per unit kind --------------
# IA-8/D10: the agent queries the KB on (fault-class, technological axis)
# derived deterministically from the unit's card; api_paradigm is preferred,
# then navigation_model, then the kind. One query per hunt (C9 working set).

def test_E5_kb_join_key_derived_per_unit_kind(tmp_path):
    store = HuntStore(tmp_path)
    queries: list = []
    run_id = "run-e5"
    agent = _agent(
        store, run_id,
        kb=_kb(queries, result={"symptoms": [], "probing_techniques": ["csrf-probe"]}),
        pod=_pod(outcomes=[
            _outcome("symptom-confirmed", verdict="successful"),
            _outcome("symptom-confirmed", verdict="successful"),
        ]),
        author=_author([SPEC, SPEC]),
        judge=_no_judge(),
    )

    service = agent(_config(SERVICE_A, FAULT_X, card=CARD_SERVICE))
    system = agent(_config(SYSTEM_B, FAULT_Y, card=CARD_SYSTEM))

    assert service.hypothesis_verdict == "successful"
    assert system.hypothesis_verdict == "successful"
    # Exactly one KB query per hunt, on the auto-derived axes.
    assert len(queries) == 2
    assert {q.fault_class for q in queries} == {FAULT_X, FAULT_Y}
    by_fault = {q.fault_class: q.axis for q in queries}
    assert by_fault[FAULT_X] == derive_technological_axis(CARD_SERVICE)
    assert by_fault[FAULT_Y] == derive_technological_axis(CARD_SYSTEM)
    assert by_fault[FAULT_X] == "rest"  # api_paradigm preferred
    assert by_fault[FAULT_Y] == "csr"  # navigation_model preferred
    # The spec records still landed per hunt, carrying the axis-relevant
    # retrieval in the authored turn (recorded by the fixture author).
    assert len(store.list_records(run_id, "spec")) == 2


# --- E6: a raising KB degrades over REAL files, never prunes ------------------
# O2/C3: the agent authors from the HuntConfig alone, flags the gap, and the
# spec still persists.

def test_E6_kb_raise_degrades_and_still_persists(tmp_path):
    store = HuntStore(tmp_path)
    run_id = "run-e6"
    agent = _agent(
        store, run_id,
        kb=_kb(raise_on=True),
        pod=_pod(outcomes=[_outcome("symptom-confirmed", verdict="successful")]),
        author=_author(),
        judge=_no_judge(),
    )

    result = agent(_config(SERVICE_A, FAULT_X, card=CARD_SERVICE))

    assert result.hypothesis_verdict == "successful"
    assert result.feedback and "symptom-technique KB unavailable" in result.feedback
    specs = store.list_records(run_id, "spec")
    assert len(specs) == 1
    assert specs[0]["target_identity"]  # authored from the HuntConfig alone
    assert (tmp_path / run_id / "spec.md").is_file()


# --- E8: INIT-rejection lineage over the REAL files ---------------------------
# Q3/Q5: one re-authoring pass, parent lineage on the second spec record, and
# the second rejection lands underspecified-spec with the validation evidence
# on the evidence record.

def test_E8_init_rejection_lineage_over_real_files(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    author_calls: list = []
    run_id = "run-e8"
    agent = _agent(
        store, run_id,
        kb=_kb(),
        pod=_pod(pod_calls, outcomes=[
            _outcome(
                "technical-infeasibility",
                evidence={"clean": False, "interpretations": [], "init_validation": [
                    "verification_symptoms references an unobservable surface",
                    "payload_vector_space contains a method the target does not expose",
                ]},
            ),
            _outcome(
                "technical-infeasibility",
                evidence={"clean": False, "interpretations": [], "init_validation": [
                    "verification_symptoms still references an unobservable surface",
                ]},
            ),
        ]),
        author=_author([SPEC, SPEC_REAUTHORED], calls=author_calls),
        judge=_no_judge(),
    )

    result = agent(_config(SERVICE_A, FAULT_X, card=CARD_SERVICE))

    assert result.hypothesis_verdict == "underspecified-spec"
    assert len(pod_calls) == 2  # exactly two dispatches, no third attempt (Q5)
    specs = store.list_records(run_id, "spec")
    evidence = store.list_records(run_id, "evidence")
    assert len(specs) == 2 and len(evidence) == 2
    # D67-03/D67-08 lineage: the re-authored spec records its parent's ref.
    assert specs[1]["parent_spec_ref"] == specs[0]["_ref"]
    # The re-authoring turn carried the skill AND the INIT validation evidence.
    reauthoring = author_calls[1]
    assert reauthoring.startswith("You are the hunting agent:")
    assert "INIT validation evidence" in reauthoring
    assert "references an unobservable surface" in reauthoring
    # The validation evidence rides the second evidence record (Q6).
    assert evidence[1]["derived_verdict"] == "underspecified-spec"
    assert evidence[1]["init_validation"]
    # The re-authored spec declined the unsupported method (Q5 decline).
    assert "json" not in specs[1]["payload_vector_space"]["encodings"]


# --- E9: the tracing seam against the observability stack ---------------------
# The one span per dispatch, session = run id; fail-open in BOTH directions:
# the live leg completes with the span really open and flushes without raising
# (when the env is configured), and the degraded leg (the client raising)
# never perturbs a dispatch.

def test_E9_tracing_seam_live_and_fail_open(tmp_path, monkeypatch):
    store = HuntStore(tmp_path)
    run_id = "run-e9"
    _live = all(os.environ.get(k) for k in
                ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"))

    if _live:
        from langfuse import get_client

        with hunting_span(run_id, "hunt-e9-live"):
            assert get_client().get_current_trace_id(), \
                "the hunting span is not actually open on the configured stack"
        flush_hunting_traces()  # no raise against the live host

    # The real dispatch completes identically whether the client is available
    # or raising: tracing is best-effort and must never perturb the hunt. All
    # seams read `langfuse.get_client` / `propagate_attributes` lazily, so the
    # monkeypatch raises right where the harness reaches them (auto-reverted
    # by the fixture - no module pollution). One agent per leg: each leg is a
    # full hunt consuming its own pod outcome.

    def _happy_leg(run_id: str):
        return _agent(
            store, run_id,
            kb=_kb(result={"symptoms": [], "probing_techniques": ["csrf-probe"]}),
            pod=_pod(outcomes=[_outcome("symptom-confirmed", verdict="successful")]),
            author=_author(),
            judge=_no_judge(),
        )

    ok = _happy_leg("run-e9-ok")(_config(SERVICE_A, FAULT_X, card=CARD_SERVICE))

    def _boom(*args, **kwargs):
        raise RuntimeError("langfuse unavailable (fixture)")

    monkeypatch.setattr("langfuse.get_client", _boom)
    monkeypatch.setattr("langfuse.propagate_attributes", _boom)

    degraded = _happy_leg("run-e9-degraded")(
        _config(SERVICE_A, FAULT_X, card=CARD_SERVICE))
    assert ok.hypothesis_verdict == degraded.hypothesis_verdict == "successful"
    assert ok.spec_ref and degraded.spec_ref
    assert ok.feedback == degraded.feedback  # tracing perturbed nothing


# --- E10: the judgment reads the LATEST (re-authored) spec's evidence ----------
# D67-08: after an INIT re-authoring pass the pod loop continues on the
# re-authored spec, so a subsequent insufficient-evidence derivation is judged
# against THAT spec's evidence - the re-authored run's terminal reason and
# interpretation note reach the turn, never the superseded original's INIT
# rejection.

def test_E10_judge_reads_the_latest_spec_after_reauth(tmp_path):
    store = HuntStore(tmp_path)
    pod_calls: list = []
    judge_calls: list = []
    run_id = "run-e10"
    agent = _agent(
        store, run_id,
        kb=_kb(),
        pod=_pod(pod_calls, outcomes=[
            _outcome(
                "technical-infeasibility",
                evidence={"clean": False, "interpretations": [], "init_validation": [
                    "verification_symptoms references an unobservable surface",
                ]},
            ),
            _outcome(
                "no-symptom-evidence",
                evidence={"clean": False, "interpretations": [
                    {"variant": "re-authored-v1", "note": "re-authored surface still blocked"},
                ]},
            ),
        ]),
        author=_author([SPEC, SPEC_REAUTHORED]),
        judge=_judge([
            {"meaningful_insight": True, "next_step": "end",
             "rationale": "the re-authored surface gap is worth keeping"},
        ], calls=judge_calls),
    )

    result = agent(_config(SERVICE_A, FAULT_X, card=CARD_SERVICE))

    # Exactly two pod dispatches in total (init-reject + re-authored run); the
    # judgment lands on the second run's evaluation.
    assert len(pod_calls) == 2
    assert len(judge_calls) == 1
    # The judgment read the RE-AUTHORED evidence trail: the re-authored run's
    # terminal reason and unique interpretation note reached the turn - not the
    # superseded original's INIT rejection. (The skill the judge embeds itself
    # quotes the INIT-validation trigger, so the terminal reason, not phrase
    # presence, is the discriminator.)
    assert "terminal reason: no-symptom-evidence" in judge_calls[0]
    assert "terminal reason: technical-infeasibility" not in judge_calls[0]
    assert "re-authored surface still blocked" in judge_calls[0]
    # The meaningfulness guard kept the verdict (no D67-12 degradation).
    assert result.hypothesis_verdict == "insufficient-evidence"
