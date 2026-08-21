"""Unit tier: the in-memory context-management component - the experiment log,
the dedup ledger, the filtered agent context, token-aware compaction, and
(D84-2) the pod-owned canonical spec hash + HuntSession address derivation."""
from langchain_core.messages.utils import count_tokens_approximately

from polymerhus.attack.hunting.pod.context import (
    ExperimentLog,
    _dicts_to_lc,
    curate_messages,
)
from polymerhus.attack.hunting.pod.types import (
    Interpretation,
    RawObservation,
    VariantSpec,
)


def test_curation_bounds_the_window_and_compacts_reasoning():
    # A long session: many reasoning turns AND many tool results across laps.
    msgs = [{"role": "system", "content": "SYSTEM PROMPT"}]
    for i in range(300):
        msgs.append({"role": "ai", "content": f"reasoning turn {i} " * 40})
        msgs.append({"role": "tool", "content": f"TOOL RESULT {i} " * 40})

    curated = curate_messages(msgs, max_tokens=800)

    # Token-bounded (the window can never grow unbounded across laps).
    assert count_tokens_approximately(_dicts_to_lc(curated)) <= 800 + 200
    # The system prompt is always kept.
    assert curated[0]["role"] == "system"
    # Reasoning turns are compacted too, not only tool bodies (the old gap).
    assert len(curated) < len(msgs)
    # A compaction marker records the elision; the recent turns survive.
    assert any("compacted" in m["content"] for m in curated)
    assert any("turn 299" in m["content"] for m in curated)


def test_short_session_is_untouched_by_compaction():
    msgs = [{"role": "system", "content": "SYS"},
            {"role": "human", "content": "go"},
            {"role": "ai", "content": "ok"}]
    assert curate_messages(msgs, max_tokens=6000) == msgs


def test_dedup_ledger_marks_and_reports():
    log = ExperimentLog()
    assert not log.has_executed("sig-1")
    log.mark_executed("sig-1")
    log.mark_executed("sig-1")  # idempotent
    assert log.has_executed("sig-1")
    assert log.executed == ["sig-1"]


def test_variant_refs_expose_every_tried_variant():
    log = ExperimentLog()
    log.record_variant(VariantSpec(ref="v0", spec={}))
    log.record_variant(VariantSpec(ref="v1", parent_ref="v0", spec={}))
    log.record_variant(VariantSpec(ref="v1", parent_ref="v0", spec={}))  # dup ref ignored
    assert log.variant_refs() == ["v0", "v1"]


def test_triager_context_surfaces_prior_variants_for_non_duplication():
    log = ExperimentLog()
    log.record_variant(VariantSpec(ref="v0", spec={}))
    log.record_variant(VariantSpec(ref="v1", parent_ref="v0", spec={}))
    log.record_interpretation(Interpretation(variant="v0", classification="symptom-absent",
                                             note="no reflection"))
    ctx = log.triager_context({"target_identity": "svc"},
                              RawObservation(status=200, body="hi"))
    assert "v0" in ctx and "v1" in ctx           # sees what was tried
    assert "never mine a duplicate" in ctx.lower()


def test_runner_context_lists_executed_signatures():
    log = ExperimentLog()
    log.mark_executed("sig-abc")
    ctx = log.runner_context({"target_identity": "svc"}, feedback="vary the encoding",
                             iteration=2, budget=8)
    assert "sig-abc" in ctx
    assert "vary the encoding" in ctx
    assert "Lap 2" in ctx


def test_canonical_spec_hash_is_deterministic_and_shared_with_the_hunter():
    """D84-2: the canonical spec fingerprint is owned by the pod; the parent
    hunting agent re-exports it as `_canonical_hash`, so the pod's spec keys and
    the parent's experiment log stay byte-identical. Deterministic across calls
    and insensitive to dict key order (equal dicts hash equal, C9)."""
    from polymerhus.attack.hunting.hunting_agent import _canonical_hash
    from polymerhus.attack.hunting.pod.context import canonical_spec_hash

    spec_a = {"verification_symptoms": ["a"],
              "payload_vector_space": {"method": "GET", "params": {"a": 1}}}
    spec_b = {"target_identity": "svc", "assumptions": [], "rationale": "r"}

    for spec in (spec_a, spec_b):
        first = canonical_spec_hash(spec)
        assert first == canonical_spec_hash(spec)      # stable across calls
        assert first == _canonical_hash(spec)          # the parent's source of truth

    # Key order never changes the hash (C9: an identical spec is never
    # dispatched twice), and two distinct specs never collide.
    shuffled = {"payload_vector_space": {"params": {"a": 1}, "method": "GET"},
                "verification_symptoms": ["a"]}
    assert canonical_spec_hash(spec_a) == canonical_spec_hash(shuffled)
    assert canonical_spec_hash(spec_a) != canonical_spec_hash(spec_b)


def test_pod_session_address_derives_a_per_spec_hunt_session():
    """D84-2: `_pod_session_address` derives the pod's `HuntSession` address with
    the canonical spec hash as the per-spec discriminator and the given role, so
    concurrent pod sessions on one hunt never collide (#94); an empty hunt_id
    defaults to "" rather than shifting the address."""
    from polymerhus.attack.hunting.pod.context import canonical_spec_hash
    from polymerhus.attack.hunting.pod.pod import _pod_session_address

    spec = {"target_identity": "svc", "payload_vector_space": {"method": "GET"}}
    addr = _pod_session_address("run-1", "hunt-A", spec, "pod_runner")

    assert addr.role_id == "pod_runner"
    assert addr.spec == canonical_spec_hash(spec)
    assert addr.run_id == "run-1"
    assert addr.hunt_id == "hunt-A"
    assert addr.thread_id.startswith("run-1:hunt-A:")
    # The spec hash discriminates the thread: two specs on one hunt diverge.
    other = _pod_session_address("run-1", "hunt-A",
                                 {"target_identity": "svc",
                                  "payload_vector_space": {"method": "POST"}},
                                 "pod_runner")
    assert addr.thread_id != other.thread_id
    # A missing hunt_id never shifts the address (empty discriminators are dropped).
    assert _pod_session_address("run-1", "", spec, "pod_triager").hunt_id == ""
