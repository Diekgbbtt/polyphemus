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


# --- batched: the low-tier sequencing must not order a batch ---------------------


def _model_with_loops(threat, unit_id, loops):
    produce_model(
        threat, project_id=PROJECT, unit_id=unit_id, run_id=RUN, loops=loops,
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


def test_batched_admits_a_low_loop_named_by_another_units_high_loop(tmp_path):
    """The batch is the unit's WHOLE loop set (ADR, section 2, `batched`).

    The S2 8.3 low-tier sequencing is subsumed in `batched`: a high loop file
    produced for a LATER unit must never hold the current unit's low loop. Held
    forever, that low loop would also keep the batched gate from ever leaving
    the hunt phase - and the run would wedge on a produced loop no unit could
    consume.
    """
    from polymerhus.attack.hunting.pipeline_sync import RunSyncGate, SyncMode
    from tests.hunting_fixtures import loop_row

    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _model_with_loops(threat, UNIT, [
        loop_row(likelihood="high"),
        loop_row(likelihood="low"),
    ])
    # A later unit with a high loop: risk 3 against the current unit's 4, so
    # the current unit stays first and the later loop stays produced.
    _model_with_loops(threat, "Service:later", [loop_row(likelihood="high")])
    hunt = "Service-catalogue-and-discovery__loop-1"
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
    # The WHOLE unit batch: the high loop AND the low loop dispatch together,
    # even though the later unit's high loop is still produced.
    assert first.dispatched == 2
    assert any(call.endswith("loop-1") for call in control.calls)
    assert any(call.endswith("loop-2") for call in control.calls)
    # The pod phase waits for the batch: the spec stays produced.
    assert [call for call in control.calls if ":pod:" in call] == []
    assert hunter.read_spec(
        PROJECT, hunt, "spec__f__keep", side="produced") is not None

    # Close both hunts so the F-022 consumed-loop recovery does not re-offer
    # them; the batch is then done and the pod may start.
    hunter.finalize_specs(PROJECT, hunt, run_id=RUN)
    hunter.finalize_specs(
        PROJECT, "Service-catalogue-and-discovery__loop-2", run_id=RUN)

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

    With the tier ordering on, a live higher-tier hunter holds the low loop and
    the read reports no work; a batched run releases it, so its quiesce must
    keep counting it.
    """
    from polymerhus.attack.hunting.surfer import run_work_remaining
    from tests.hunting_fixtures import loop_row

    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _model_with_loops(threat, UNIT, [loop_row(likelihood="low")])

    kwargs = dict(
        threat_store=threat, hunter_store=hunter,
        live_loop_likelihoods={"hunting:run-1:hunt:other__loop-1": "high"},
    )
    assert run_work_remaining(PROJECT, RUN, **kwargs) is False
    assert run_work_remaining(PROJECT, RUN, sequence_tiers=False, **kwargs) is True
