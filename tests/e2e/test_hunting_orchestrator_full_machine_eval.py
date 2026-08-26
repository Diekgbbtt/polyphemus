"""The hunt-orchestrator full-machine e2e eval (operator-directed).

Runs the REAL workflow graph end-to-end over the LIVE L1 surface of the
operator's source project with the top-30 risk-tiered kb-faults, using the
real orchestrator actor (real LLM through the co-located gateway), the real
KB, a scratch HuntStore, and the standard FaultSource selection. The
downstream hunting-agent dispatch does not exist on this graph (G12), so the
eval runs the orchestrator only.

The acceptance bar is every NOMINAL machine state being touched:
- supervisor routing: fault pop + pair pop per super-step + END;
- the node-per-phase machine: hypothesise -> ratify -> note per pair with the
  loop states HYPOTHESISED -> RATIFIED -> NOTED;
- the config lifecycle: hypothesised draft -> ratified terminal state
  (dropped orphans stay on disk when the LLM drops one);
- the G1 pair-end: the note phase sets the next pair's frame, crossing the
  fault drain;
- the KB grounding (real) and the empty-candidate boundary (the selected
  faults whose predicate matches no unit).
If a failure mode is entered naturally, its handling must activate (counted,
fail-open) and the pass must complete - never a crash.

Run inside the eval container (from the main repo, pointing at this worktree):
    HUNTING_EVAL_WORKTREE=$PWD \
    docker compose -f docker-compose.yml -f docker-compose.hunting-eval.yml \
        run --rm hunting-eval

Smoke subset (fast, few LLM turns):
    HUNTING_EVAL_WORKTREE=$PWD \
    docker compose -f docker-compose.yml -f docker-compose.hunting-eval.yml \
        run --rm -e HUNTING_EVAL_MAX_FAULTS=3 -e HUNTING_EVAL_MAX_UNITS_PER_FAULT=2 \
        hunting-eval
"""
from __future__ import annotations

import uuid

import pytest

from tests.e2e.hunting_observability import TraceJudge
from tests.e2e.hunting_orchestrator_eval_stack import (
    SOURCE_PROJECT_ID,
    run_orchestrator_eval,
)
from tests.e2e.hunting_stack import ensure_hunting_stack


def test_hunting_orchestrator_full_machine_eval(tmp_path):
    reason = ensure_hunting_stack(timeout=30)
    if reason:
        pytest.skip(reason)

    store_root = tmp_path / "hunt-store"
    result = run_orchestrator_eval(
        SOURCE_PROJECT_ID,
        store_root=store_root,
        run_id=f"hunt-eval-{uuid.uuid4().hex[:12]}",
    )
    report = result.report
    store = result.store
    ctx = result.phase_context
    judge = TraceJudge(result.probe)

    # --- intake + schedule boundary --------------------------------------------
    # every produced candidate pair is accepted (0 malformed / 0 duplicates) and
    # processed through the phase machine; a selected fault with no matching unit
    # contributes nothing (the empty-candidate boundary).
    assert report.malformed_dropped == 0, report
    assert report.duplicates_dropped == 0, report
    assert report.pruned_by_verdict == 0, report
    assert len(result.candidates) >= 1, "no candidates survived selection"
    assert report.pairs_processed == len(result.candidates), (
        f"{report.pairs_processed} pairs processed != {len(result.candidates)} "
        f"candidates"
    )
    assert result.expected_faults_with_pairs == len(
        {c.fault_class for c in result.candidates}), "fault routing drift"
    assert len({c.fault_class for c in result.candidates}) >= 2, (
        "the eval must route >= 2 distinct faults (fault-level schedule)"
    )

    # --- supervisor + END -------------------------------------------------------
    # the graph ran to completion and returned a terminal report (never a hang),
    # with the ledger's minted keys matching the pairs that carried directions.
    assert report.ledger.units_done >= 1, report
    assert len(report.ledger.minted_config_keys) == report.ledger.units_done, report

    # --- hypothesise (loop state HYPOTHESISED, the mint at this phase) ---------
    assert report.configs_hypothesised >= 1, report
    assert report.pairs_processed >= report.ledger.units_done, report
    assert len(store.read_configs(result.project_id)) >= 1, "no config persisted"

    # --- ratify (loop state RATIFIED, config lifecycle hypothesised->ratified) -
    assert report.configs_ratified >= 1, report
    configs = store.read_configs(result.project_id)
    statuses = {c["status"] for c in configs}
    assert statuses <= {"hypothesised", "ratified", "dropped"}, statuses
    assert "ratified" in statuses, "the happy-path config lifecycle never ratified"
    # the ratify phase never double-counts and never invents configs
    assert (report.configs_ratified + report.configs_dropped
            + report.configs_unratified) <= report.configs_hypothesised, report
    # a dropped config stays on disk statused dropped (G6) - only if the LLM
    # actually dropped one this run
    if report.configs_dropped > 0:
        assert any(c["status"] == "dropped" for c in configs), configs

    # --- note (loop state NOTED, the pair-end memory.yaml) ----------------------
    assert report.notes_written >= 1, report
    assert report.ledger.notes_recorded >= 1, report
    notes = store.read_notes(result.project_id)
    assert len(notes) >= 1, "no notes in memory.yaml"
    assert all("revival_key" in n and n["revival_key"] for n in notes), notes
    # a note keys on a config's revival key OR its semantic-key extension
    # (`unit::cwe::class`), the store's prefix-match rule
    def _matches(note_key: str, cfg: dict) -> bool:
        cfg_key = cfg["unit_id"] + "::" + cfg["fault_class"]
        return (note_key == cfg_key
                or note_key.startswith(cfg_key + "::")
                or cfg_key.startswith(note_key + "::"))
    note_keys = [n["revival_key"] for n in notes]
    print("NOTE_KEYS", note_keys)
    print("CONFIG_KEYS", [c["unit_id"] + "::" + c["fault_class"] for c in configs])
    assert any(_matches(nk, c) for nk in note_keys for c in configs), (
        "notes must key on a config's revival key or a semantic-key extension")

    # --- the phase machine observed (traces) ------------------------------------
    judge.assert_symbolic_then_gate()
    emits = judge.rows_named("emit-mint")
    notes = judge.rows_named("note-written")
    assert emits, "no emit-mint trace rows"
    assert notes, "no note-written trace rows"
    assert len(notes) <= len(emits), "note rows cannot exceed emit rows"
    for note_row in notes:
        prior = [e.order for e in emits if e.order < note_row.order]
        assert prior, f"note {note_row.order} has no preceding emit-mint"
        assert len(prior) == len(set(prior)), "duplicate emit orders"

    # --- G1 pair-end + fault drain (next-pair frames) --------------------------
    assert ctx.assignments, "the note phase never set a next pair"
    assert ctx.assignments[-1] is None, "the final pair must end the schedule"
    assert any(isinstance(a, dict) for a in ctx.assignments[:-1]), (
        "no next-pair frame carried between pairs")
    cross_fault = [a for a in ctx.assignments[:-1]
                   if isinstance(a, dict)
                   and a.get("fault_class") != result.candidates[0].fault_class]
    if result.expected_faults_with_pairs >= 2:
        assert cross_fault, "no cross-fault drain frame observed"

    # --- failure-mode handling (only if a failure mode was entered) ------------
    # if a failure mode fired, its handling must activate and the pass must
    # complete - never a crash. The G4 duplicate-write is a legitimate
    # deduplication signal (the LLM re-elicited an identity the store already
    # held); the harness counts it (O3 conflation) and keeps serving with the
    # in-memory config.
    print("REPORT", report)
    if report.store_write_failures or report.duplicate_config_writes:
        assert report.store_write_failures >= report.duplicate_config_writes, report
        assert report.pairs_processed == len(result.candidates), report
    assert report.exhausted_faults == (), report

    # --- the run's grounding -----------------------------------------------
    assert result.trace_rows, "no orchestrator observations recorded"
    assert result.unit_ids, "no testable units resolved from the source L1"
    assert len(result.unit_ids) == 22, (
        f"source L1 surface drifted: {len(result.unit_ids)} testable units")
    assert result.project_id == SOURCE_PROJECT_ID