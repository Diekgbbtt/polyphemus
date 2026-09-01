"""Unit tier: the per-project hunter-memory store's move-aware spec surface (#205).

Pure filesystem mechanics - no Neo4j, no LLM. Pins the #205 regression at the
store seam, mirroring the #192 ratify-upsert regression for the hunt store
(`tests/attack/test_hunt_store.py`): a produced-target `write_spec` whose
identity ALREADY lives in consumed/ (the mover's at-least-once marker landed)
is a no-op success returning the consumed Path - it never re-creates a
produced/ copy, so produced/ and consumed/ stay mutually exclusive per name
(G4) and the surfer's spec inbox keeps draining (the #205 race: the hunter's
late `specified` harness write can land after the mover consumed the spec;
without the guard the mover re-dispatches the identity every tick and the run
hangs in `running`, F5).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore

PROJECT = "proj-1"
FAULT_KEY = "Service:account-registration_CWE-266_Privilege Escalation"


def _spec(**extra) -> dict:
    """A `specified`-shape write payload carrying the lifecycle status."""
    body = {
        "fault_id": "F1", "spec_id": "S1", "status": "specified",
        "strategy": "probe", "fault_key": FAULT_KEY, "test": "t",
    }
    body.update(extra)
    return body


def _spec_file(tmp_path, side: Literal["produced", "consumed"]) -> Path:
    return (
        tmp_path / PROJECT / "hunter" / "test-specs" / FAULT_KEY
        / side / "registration_probe.yaml"
    )


# --- #205: write_spec is move-aware (G4 mutual exclusivity) -------------------

def test_produced_write_after_move_is_a_no_op_and_never_recreates(tmp_path, caplog):
    """#205 regression, `mode="update"`: after the mover consumed the spec, the
    hunter's late `specified` harness write (the lifecycle update) lands AFTER
    the move. It must be a no-op success returning the durable consumed Path -
    produced/ stays absent, so produced/ and consumed/ hold the name once (G4)
    and the surfer's inbox drains."""
    store = HunterMemoryStore(root_dir=tmp_path)
    k = dict(fault_keyword="registration", strategy_keyword="probe")
    store.write_spec(PROJECT, FAULT_KEY, mode="create", spec=_spec(), **k)
    assert store.consume_spec(PROJECT, FAULT_KEY, "registration_probe") is True
    assert not _spec_file(tmp_path, "produced").exists()
    with caplog.at_level(logging.WARNING):
        result = store.write_spec(PROJECT, FAULT_KEY, mode="update", spec=_spec(), **k)
    assert _spec_file(tmp_path, "consumed").exists()
    assert not _spec_file(tmp_path, "produced").exists()
    assert store.produced_spec_files(PROJECT, FAULT_KEY) == []
    assert isinstance(result, Path)
    assert result == _spec_file(tmp_path, "consumed")
    assert any("post-move write, #205" in r.message for r in caplog.records)


def test_produced_create_write_after_move_is_a_no_op(tmp_path, caplog):
    """#205 regression, `mode="create"`: the create-mode novelty gate only
    checks the produced side, so a post-move create write previously fabricated
    a fresh produced/ copy (the move-aware check must short-circuit BEFORE the
    novelty gate). It is now a no-op success returning the consumed Path."""
    store = HunterMemoryStore(root_dir=tmp_path)
    k = dict(fault_keyword="registration", strategy_keyword="probe")
    store.write_spec(PROJECT, FAULT_KEY, mode="create", spec=_spec(), **k)
    assert store.consume_spec(PROJECT, FAULT_KEY, "registration_probe") is True
    with caplog.at_level(logging.WARNING):
        result = store.write_spec(PROJECT, FAULT_KEY, mode="create", spec=_spec(), **k)
    assert _spec_file(tmp_path, "consumed").exists()
    assert not _spec_file(tmp_path, "produced").exists()
    assert store.produced_spec_files(PROJECT, FAULT_KEY) == []
    assert isinstance(result, Path)
    assert result == _spec_file(tmp_path, "consumed")
    assert any("post-move write, #205" in r.message for r in caplog.records)


def test_move_aware_no_op_keeps_consume_a_noop_success(tmp_path, caplog):
    """#205 quiesce proof: after the move-aware no-op, the next mover tick has
    an empty produced inbox - `consume_spec` is a no-op success (never the
    dual-sided clobber refusal), so the run reaches terminal (no re-dispatch
    churn, no hang in `running`)."""
    store = HunterMemoryStore(root_dir=tmp_path)
    k = dict(fault_keyword="registration", strategy_keyword="probe")
    store.write_spec(PROJECT, FAULT_KEY, mode="create", spec=_spec(), **k)
    assert store.consume_spec(PROJECT, FAULT_KEY, "registration_probe") is True
    store.write_spec(PROJECT, FAULT_KEY, mode="update", spec=_spec(), **k)
    with caplog.at_level(logging.WARNING):
        assert store.consume_spec(PROJECT, FAULT_KEY, "registration_probe") is True
    assert store.produced_spec_files(PROJECT, FAULT_KEY) == []
    assert not any("both produced/ and consumed/" in r.message for r in caplog.records)


# --- no regression: the ordinary sides keep their semantics ------------------

def test_produced_write_still_creates_when_consumed_absent(tmp_path):
    """A normal produced-target write with no consumed/ twin still creates the
    produced file (create) and re-authors it in place (update) - the guard only
    fires on a post-move write."""
    store = HunterMemoryStore(root_dir=tmp_path)
    k = dict(fault_keyword="registration", strategy_keyword="probe")
    result = store.write_spec(PROJECT, FAULT_KEY, mode="create", spec=_spec(), **k)
    assert isinstance(result, Path)
    assert result == _spec_file(tmp_path, "produced")
    assert _spec_file(tmp_path, "produced").exists()
    assert not _spec_file(tmp_path, "consumed").exists()
    store.write_spec(PROJECT, FAULT_KEY, mode="update",
                     spec=_spec(test="t2"), **k)
    assert store.read_spec(PROJECT, FAULT_KEY, **k)["test"] == "t2"
    assert store.produced_spec_files(PROJECT, FAULT_KEY) == ["registration_probe"]


def test_consumed_side_write_is_unaffected(tmp_path):
    """A `side="consumed"` write is untouched by the guard: replay still
    overwrites the consumed record in place (the mover's at-least-once marker
    is re-dumped, never blocked, never clobbered)."""
    store = HunterMemoryStore(root_dir=tmp_path)
    k = dict(fault_keyword="registration", strategy_keyword="probe")
    store.write_spec(PROJECT, FAULT_KEY, mode="create", side="consumed",
                     spec=_spec(), **k)
    assert _spec_file(tmp_path, "consumed").exists()
    assert not _spec_file(tmp_path, "produced").exists()
    store.write_spec(PROJECT, FAULT_KEY, mode="update", side="consumed",
                     spec=_spec(test="t2"), **k)
    assert store.read_spec(PROJECT, FAULT_KEY, side="consumed",
                           **k)["test"] == "t2"
    assert not _spec_file(tmp_path, "produced").exists()
