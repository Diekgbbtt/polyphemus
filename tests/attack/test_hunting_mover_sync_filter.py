"""Unit tier: the mover's sync pre-filter seam.

The phase-serialising modes hold produced items at the mover tick: a filtered
item must stay in produced (at-least-once, never dropped or moved), count as
paused on the `TickReport`, and never reach the control plane. The filter runs
after the sequencing filter and before the pure deduction, so the quiesce
predicate (which reads the unfiltered inbox) still sees held items as work.
"""
from __future__ import annotations

import yaml

from polymerhus.attack.hunting.mover import (
    ThreatItem,
    read_produced_inbox,
    run_delivery_tick,
)
from polymerhus.attack.hunting.surfer import run_work_remaining

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
    # The threat file is still produced: the quiesce read still counts the work.
    threat, _hunter = stores
    assert any(
        entry.get("run_id") == RUN
        for entry in threat.read_produced_threats(PROJECT)
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
        for entry in threat.read_produced_threats(PROJECT)
    )


# --- batched: the low-tier sequencing must not order a batch ---------------------


def _model_with_threats(threat, unit_id, threats):
    produce_model(
        threat, project_id=PROJECT, unit_id=unit_id, run_id=RUN, threats=threats,
    )


def test_batched_admits_the_highest_risk_threat_across_units(tmp_path):
    """The queue is GLOBAL (spec 8): the highest-risk threat dispatches first,
    whatever unit it belongs to, and no unit boundary holds a later unit.

    The S2 8.3 low-band sequencing is subsumed by the risk order in `batched`:
    a produced high threat for a LATER unit must never hold an equally-ranked
    threat, and once the top threat is done the later unit's threat is next
    even though its own unit still has a produced threat.
    """
    from polymerhus.attack.hunting.pipeline_sync import RunSyncGate, SyncMode
    from tests.hunting_fixtures import risk_row

    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _model_with_threats(threat, UNIT, [
        risk_row(9.3),
        risk_row(2.0),
    ])
    # The later unit's threat ties the current unit's top threat at 9.3; the
    # intake position (UNIT first) breaks the tie on the first tick.
    _model_with_threats(threat, "Service:later", [risk_row(9.3)])

    gate = RunSyncGate(
        mode=SyncMode.BATCHED, project_id=PROJECT, run_id=RUN,
        threat_store=threat, hunter_store=hunter, pod_store=None,
        intake_order=lambda: (UNIT, "Service:later"),
    )
    control = RecordingControlPlane()

    from polymerhus.attack.hunting.surfer import tier_sequencing_enabled

    def _tick_once():
        return run_delivery_tick(
            PROJECT, RUN,
            threat_store=threat,
            hunter_store=hunter,
            pod_store=None,
            control=control,
            coro_for=lambda item: _noop(),
            pre_filter=lambda items, live: gate.filter(
                items, live_session_ids=live),
            sequence_tiers=tier_sequencing_enabled(gate),
        )

    first = _tick_once()
    # ONE hunter at a time, the global top: the current unit's threat-1.
    assert first.dispatched == 1
    assert control.calls == [
        f"hunting:{RUN}:hunt:{UNIT.replace(':', '-')}__threat-1"]

    # Close the top hunt so the F-022 recovery does not re-offer it.
    top = f"{UNIT.replace(':', '-')}__threat-1"
    hunter.finalize_specs(PROJECT, top, run_id=RUN)

    second = _tick_once()
    # The later unit's 9.3 is next: the current unit's remaining produced low
    # threat (2.0) never becomes a unit barrier.
    assert second.dispatched == 1
    assert control.calls[-1] == (
        f"hunting:{RUN}:hunt:Service-later__threat-1")


def test_tier_sequencing_applies_to_parallel_and_serial_only():
    """The S2 8.3 tier ordering does not order a `batched` batch."""
    from polymerhus.attack.hunting.pipeline_sync import RunSyncGate, SyncMode
    from polymerhus.attack.hunting.surfer import tier_sequencing_enabled

    def _gate(mode):
        return RunSyncGate(
            mode=mode, project_id=PROJECT, run_id=RUN,
            hunter_store=HunterMemoryStore("/nonexistent"),
        )

    assert tier_sequencing_enabled(None) is True
    assert tier_sequencing_enabled(_gate(SyncMode.PARALLEL)) is True
    assert tier_sequencing_enabled(_gate(SyncMode.SERIAL)) is True
    assert tier_sequencing_enabled(_gate(SyncMode.BATCHED)) is False


def test_run_work_remaining_counts_a_held_low_when_sequencing_is_off(tmp_path):
    """`batched` quiesce reads the low as work: the tier filter must not hide it.

    With the tier ordering on, a live higher-tier hunter holds the low threat and
    the read reports no work; a batched run releases it, so its quiesce must
    keep counting it.
    """
    from polymerhus.attack.hunting.surfer import run_work_remaining
    from tests.hunting_fixtures import risk_row

    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _model_with_threats(threat, UNIT, [risk_row(2.0)])

    kwargs = dict(
        threat_store=threat, hunter_store=hunter,
        live_threat_bands={"hunting:run-1:hunt:other__threat-1": "high"},
    )
    assert run_work_remaining(PROJECT, RUN, **kwargs) is False
    assert run_work_remaining(PROJECT, RUN, sequence_tiers=False, **kwargs) is True


# --- the promotion floor (2026-10-26) ---------------------------------------------

def _two_threat_model(tmp_path):
    from tests.hunting_fixtures import risk_row

    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    produce_model(
        threat, project_id=PROJECT, unit_id=UNIT, run_id=RUN,
        threats=[risk_row(9.3), risk_row(2.0)],
    )
    return threat, hunter


def test_promotion_omits_a_demoted_threat_and_consumes_the_model(tmp_path):
    threat, hunter = _two_threat_model(tmp_path)
    control = RecordingControlPlane()

    first = run_delivery_tick(
        PROJECT, RUN,
        threat_store=threat,
        hunter_store=hunter,
        pod_store=None,
        control=control,
        coro_for=lambda item: _noop(),
        promotion_risk_threshold=3,
    )

    assert first.dispatched == 1
    assert first.moved == 1
    assert len(control.calls) == 1
    assert control.calls[0].endswith("threat-1")
    # The demoted threat is still produced; the model is not consumed yet.
    assert [
        threat_row["threat_id"]
        for entry in threat.read_produced_threats(PROJECT)
        for threat_row in entry["threats"]
    ] == ["threat-2"]
    # Close the promoted hunt so the F-022 recovery does not re-offer it.
    hunt_key = control.calls[0].rsplit("hunt:", 1)[-1]
    hunter.finalize_specs(PROJECT, hunt_key, run_id=RUN)

    second = run_delivery_tick(
        PROJECT, RUN,
        threat_store=threat,
        hunter_store=hunter,
        pod_store=None,
        control=control,
        coro_for=lambda item: _noop(),
        promotion_risk_threshold=3,
    )

    assert second.dispatched == 0
    assert second.models_consumed == 1
    # The unit model moved; the demoted file stays as evidence.
    assert threat.read_produced_threats(PROJECT) == []
    assert list((tmp_path / "threat").rglob("threat-2.yaml"))


def test_promotion_none_dispatches_every_threat(tmp_path):
    threat, hunter = _two_threat_model(tmp_path)
    control = RecordingControlPlane()

    report = run_delivery_tick(
        PROJECT, RUN,
        threat_store=threat,
        hunter_store=hunter,
        pod_store=None,
        control=control,
        coro_for=lambda item: _noop(),
        promotion_risk_threshold=None,
        sequence_tiers=False,
    )

    assert report.dispatched == 2
    assert report.moved == 2
    assert len(control.calls) == 2


def test_all_demoted_unit_is_model_consume_work_then_quiet(tmp_path):
    from tests.hunting_fixtures import risk_row

    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    produce_model(
        threat, project_id=PROJECT, unit_id=UNIT, run_id=RUN,
        threats=[risk_row(2.0)],
    )

    # The model consume is work, so the run is not quiet yet.
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        promotion_risk_threshold=5,
    ) is True

    control = RecordingControlPlane()
    report = run_delivery_tick(
        PROJECT, RUN,
        threat_store=threat,
        hunter_store=hunter,
        pod_store=None,
        control=control,
        coro_for=lambda item: _noop(),
        promotion_risk_threshold=5,
    )

    assert report.dispatched == 0
    assert report.models_consumed == 1
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        promotion_risk_threshold=5,
    ) is False
    assert list((tmp_path / "threat").rglob("threat-1.yaml"))


def test_a_recovered_consumed_threat_is_never_demoted(tmp_path):
    """A consumed threat was already admitted under the frozen floor. Its F-022
    recovery must not be filtered, even when a later read sees a higher floor."""
    threat, hunter = _two_threat_model(tmp_path)
    assert threat.consume_threat(PROJECT, UNIT, "threat-2") is True

    inbox = read_produced_inbox(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        promotion_risk_threshold=10,
    )

    threats = [item for item in inbox.items if isinstance(item, ThreatItem)]
    assert [item.threat_id for item in threats] == ["threat-2"]


def test_a_refused_threat_stays_in_produced_and_is_not_archived(tmp_path):
    """A mover refusal leaves the file in produced/. It is not an `abandoned/`
    archive: that family is written only for a whole stale or invalid unit
    model, by the intake freeze or the modeller."""
    from tests.hunting_fixtures import risk_row

    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    produce_model(
        threat, project_id=PROJECT, unit_id=UNIT, run_id=RUN,
        threats=[risk_row(9.3), risk_row(9.3)],
    )
    produced = (
        tmp_path / "threat" / PROJECT / "hunting" / "threat_modeller"
        / "produced" / "Service-catalogue-and-discovery"
    )
    refused_path = produced / "threat-2.yaml"
    record = yaml.safe_load(refused_path.read_text())
    record["unit_kind"] = "not-a-unit-kind"
    refused_path.write_text(yaml.safe_dump(record), encoding="utf-8")

    assert threat.consume_threat(PROJECT, UNIT, "threat-1") is True
    hunter.finalize_specs(
        PROJECT, "Service-catalogue-and-discovery__threat-1", run_id=RUN)
    report = run_delivery_tick(
        PROJECT, RUN,
        threat_store=threat,
        hunter_store=hunter,
        pod_store=None,
        control=RecordingControlPlane(),
        coro_for=lambda item: None,
    )

    assert report.dispatched == 0
    assert report.models_consumed == 1
    assert refused_path.exists()
    assert threat.read_produced_threats(PROJECT) == []
    assert not list((tmp_path / "threat").rglob("abandoned/*"))
