"""Unit tier: the mover's sync pre-filter seam.

The phase-serialising modes hold produced items at the mover tick: a filtered
item must stay in produced (at-least-once, never dropped or moved), count as
paused on the `TickReport`, and never reach the control plane. The filter runs
after the sequencing filter and before the pure deduction, so the quiesce
predicate (which reads the unfiltered inbox) still sees held items as work.
"""
from __future__ import annotations

from polymerhus.attack.hunting.mover import run_delivery_tick

from tests.hunting_fixtures import produce_model
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore

PROJECT = "proj-1"
RUN = "run-1"
UNIT = "Service:catalogue-and-discovery"


class RecordingControlPlane:
    def __init__(self):
        self.calls: list[str] = []

    def live_session_ids(self):
        return set()

    def dispatch(self, session_id, coro):
        self.calls.append(session_id)
        coro.close()
        return True


async def _noop():
    return None


def _stores(tmp_path):
    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    produce_model(threat, project_id=PROJECT, unit_id=UNIT, run_id=RUN)
    return threat, hunter


def _tick(stores, control, pre_filter):
    threat, hunter = stores
    return run_delivery_tick(
        PROJECT, RUN,
        threat_store=threat,
        hunter_store=hunter,
        pod_store=None,
        control=control,
        coro_for=lambda item: None,
        pre_filter=pre_filter,
    )


def test_pre_filter_holding_every_item_leaves_it_produced(tmp_path):
    stores = _stores(tmp_path)
    control = RecordingControlPlane()

    report = _tick(stores, control, lambda items, live: ())

    assert report.produced == 1
    assert report.paused == 1
    assert report.dispatched == 0
    assert report.moved == 0
    assert control.calls == []
    # The loop file is still produced: the quiesce read still counts the work.
    threat, _hunter = stores
    assert any(
        entry.get("run_id") == RUN
        for entry in threat.read_produced_loops(PROJECT)
    )


def test_pre_filter_admitting_the_item_dispatches_and_moves_normally(tmp_path):
    threat, hunter = _stores(tmp_path)
    control = RecordingControlPlane()

    report = run_delivery_tick(
        PROJECT, RUN,
        threat_store=threat,
        hunter_store=hunter,
        pod_store=None,
        control=control,
        coro_for=lambda item: _noop(),
        pre_filter=lambda items, live: tuple(items),
    )

    assert report.produced == 1
    assert report.paused == 0
    assert report.dispatched == 1
    assert report.admitted == 1
    assert report.moved == 1
    assert len(control.calls) == 1
    assert not any(
        entry.get("run_id") == RUN
        for entry in threat.read_produced_loops(PROJECT)
    )
