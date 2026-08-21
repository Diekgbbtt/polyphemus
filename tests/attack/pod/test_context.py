"""Unit tier: the in-memory context-management component - the experiment log,
the dedup ledger, the filtered agent context, and token-aware compaction."""
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
