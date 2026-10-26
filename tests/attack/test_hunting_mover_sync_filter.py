"""Unit tier: the mover's sync pre-filter seam.

The phase-serialising modes hold produced items at the mover tick: a filtered
item must stay in produced (at-least-once, never dropped or moved), count as
paused on the `TickReport`, and never reach the control plane. The filter runs
after the sequencing filter and before the pure deduction, so the quiesce
predicate (which reads the unfiltered inbox) still sees held items as work.
"""
from __future__ import annotations

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


def _ratified_spec(hunt: str) -> dict:
    return {
        "status": "ratified",
        "discriminators": [
            {"axis": "fault", "value": "f"},
            {"axis": "technique", "value": "keep"},
        ],
        "target": {"unit_id": UNIT},
        "provenance": {"run_id": RUN},
    }


def test_batched_admits_a_low_threat_named_by_another_units_high_threat(tmp_path):
    """The batch is the unit's WHOLE threat set (ADR, section 2, `batched`).

    The S2 8.3 low-tier sequencing is subsumed in `batched`: a high threat file
    produced for a LATER unit must never hold the current unit's low threat. Held
    forever, that low threat would also keep the batched gate from ever leaving
    the hunt phase - and the run would wedge on a produced threat no unit could
    consume.
    """
    from polymerhus.attack.hunting.pipeline_sync import RunSyncGate, SyncMode
    from tests.hunting_fixtures import threat_row

    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _model_with_threats(threat, UNIT, [
        threat_row(likelihood="high"),
        threat_row(likelihood="low"),
    ])
    # A later unit with a high threat: risk 3 against the current unit's 4, so
    # the current unit stays first and the later threat stays produced.
    _model_with_threats(threat, "Service:later", [threat_row(likelihood="high")])
    hunt = "Service-catalogue-and-discovery__threat-1"
    hunter.write_specs(
        PROJECT, hunt,
        [{**_ratified_spec(hunt), "status": "hypothesised"}],
        enforce_complete=False)
    hunter.write_specs(
        PROJECT, hunt, [_ratified_spec(hunt)], enforce_complete=False)
    hunter.finalize_specs(PROJECT, hunt, run_id=RUN)

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
    # The WHOLE unit batch: the high threat AND the low threat dispatch together,
    # even though the later unit's high threat is still produced.
    assert first.dispatched == 2
    assert any(call.endswith("threat-1") for call in control.calls)
    assert any(call.endswith("threat-2") for call in control.calls)
    # The pod phase waits for the batch: the spec stays produced.
    assert [call for call in control.calls if ":pod:" in call] == []
    assert hunter.read_spec(
        PROJECT, hunt, "spec__f__keep", side="produced") is not None

    # Close both hunts so the F-022 consumed-threat recovery does not re-offer
    # them; the batch is then done and the pod may start.
    hunter.finalize_specs(PROJECT, hunt, run_id=RUN)
    hunter.finalize_specs(
        PROJECT, "Service-catalogue-and-discovery__threat-2", run_id=RUN)

    second = _tick_once()
    assert second.dispatched == 1
    assert [call for call in control.calls if ":pod:" in call] != []


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
    from tests.hunting_fixtures import threat_row

    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _model_with_threats(threat, UNIT, [threat_row(likelihood="low")])

    kwargs = dict(
        threat_store=threat, hunter_store=hunter,
        live_threat_buckets={"hunting:run-1:hunt:other__threat-1": "high"},
    )
    assert run_work_remaining(PROJECT, RUN, **kwargs) is False
    assert run_work_remaining(PROJECT, RUN, sequence_tiers=False, **kwargs) is True


# --- the promotion floor (2026-10-26) ---------------------------------------------

def _two_threat_model(tmp_path):
    from tests.hunting_fixtures import threat_row

    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    produce_model(
        threat, project_id=PROJECT, unit_id=UNIT, run_id=RUN,
        threats=[threat_row(likelihood="high"), threat_row(likelihood="low")],
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
    from tests.hunting_fixtures import threat_row

    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    produce_model(
        threat, project_id=PROJECT, unit_id=UNIT, run_id=RUN,
        threats=[threat_row(likelihood="low")],
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
