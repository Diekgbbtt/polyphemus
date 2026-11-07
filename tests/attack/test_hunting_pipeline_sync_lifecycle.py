"""Integration tier: the serial cursor over the REAL hunter and pod stores.

The gate's unit tests use fakes for the lifecycle surface. These tests drive
the real `HunterMemoryStore` and `PodMemoryStore` so the terminal marker, the
consumed move, and the PodExport path are exercised together.

Pinned behaviour:
- a hunt with a durable terminal marker advances the queue after its consumed
  specs have exports;
- a stale `hypothesised` hunt holds the queue instead of being skipped;
- an unreadable spec fails closed and holds the queue.
"""
from __future__ import annotations

import asyncio

from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.mover import TestSpecItem, ThreatItem
from polymerhus.attack.hunting.pipeline_sync import (
    RunSyncGate, SyncMode, hunting_artifacts_terminal,
)
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
from polymerhus.attack.hunting.pod_export_memory import PodExportStore
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from tests.hunting_fixtures import produce_model
from polymerhus.attack.hunting import surfer as surfer_mod
from polymerhus.attack.hunting.surfer import (
    RunDispatchState, is_run_quiesced, run_hunter_session, run_pod_session,
)

PROJECT = "proj-lifecycle"
RUN = "run-lifecycle"


def _threat(unit_name: str, threat_id: str = "threat-1") -> ThreatItem:
    dispatch = f"{unit_name}__{threat_id}"
    return ThreatItem(
        message_id=dispatch,
        session_id=f"hunting:{RUN}:hunt:{dispatch}",
        unit_id=f"Service:{unit_name}",
        unit_name=unit_name,
        threat_id=threat_id,
        dispatch_id=dispatch,
        risk=9.3,
        record={"threat": {"id": threat_id}},
    )


def _spec(fault: str, strategy: str, status: str,
          unit: str = "Service:u1") -> dict:
    return {
        "status": status,
        "discriminators": [
            {"axis": "fault", "value": fault},
            {"axis": "technique", "value": strategy},
        ],
        "target": {"unit_id": unit},
        "provenance": {"run_id": RUN},
    }


def _write_set(hunter: HunterMemoryStore, hunt: str, specs: list[dict]):
    """Write the test's terminal set through the real lifecycle: draft first,
    then the terminal statuses, so the store's identity-stability rule holds."""
    drafts = [{**spec, "status": "hypothesised"} for spec in specs
              if spec.get("status") != "hypothesised"]
    if drafts:
        hunter.write_specs(PROJECT, hunt, drafts, enforce_complete=False)
    return hunter.write_specs(PROJECT, hunt, specs, enforce_complete=False)


def _gate(hunter: HunterMemoryStore, pod: PodMemoryStore) -> RunSyncGate:
    return RunSyncGate(
        mode=SyncMode.SERIAL,
        project_id=PROJECT,
        run_id=RUN,
        hunter_store=hunter,
        pod_store=pod,
        intake_order=lambda: ("Service:u1", "Service:u2"),
    )


def test_real_store_terminal_and_export_advance_the_queue(tmp_path):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    hunt = "u1__threat-1"
    _write_set(hunter, hunt, [
        _spec("f", "drop", "dropped"), _spec("f", "keep", "ratified")])
    hunter.finalize_specs(PROJECT, hunt, run_id=RUN)
    assert hunter.consume_spec(PROJECT, hunt, "spec__f__keep") is True
    pod.write_pod_export(
        "spec__f__keep", RUN,
        {"verdict": "successful", "evidence": {
            "terminal_reason": "symptom-confirmed"}},
    )

    gate = _gate(hunter, pod)
    next_threat = _threat("u2")
    # The dropped spec stays produced; it does not need an export. The consumed
    # ratified spec has one. The next hunter is admissible.
    assert gate.filter([next_threat]) == (next_threat,)


def test_real_store_stale_hypothesised_hunt_holds_the_queue(tmp_path):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    hunt = "u1__threat-1"
    hunter.write_specs(
        PROJECT, hunt, [_spec("f", "draft", "hypothesised")],
        enforce_complete=False,
    )

    gate = _gate(hunter, pod)
    next_threat = _threat("u2")
    assert gate.filter([next_threat]) == ()


def test_real_store_unreadable_spec_fails_closed(tmp_path):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    hunt = "u1__threat-1"
    _write_set(hunter, hunt, [_spec("f", "keep", "ratified")])
    path = (
        tmp_path / "hunter" / PROJECT / "hunting" / "hunter"
        / "test-specs" / hunt / "produced" / "spec__f__keep.yaml"
    )
    assert path.exists()
    path.write_text("not: [a: valid: yaml", encoding="utf-8")

    gate = _gate(hunter, pod)
    next_threat = _threat("u2")
    assert gate.filter([next_threat]) == ()


def test_surfer_degraded_pod_export_is_durable(tmp_path):
    """A builder exception must persist a terminal degraded PodExport.

    The serial gate counts a failed/degraded execution as terminal only when
    the durable export exists. The surfer's degraded envelope was previously
    returned without a PodExport, so the consumed spec was re-dispatched
    forever.
    """
    pod_exports = PodExportStore(tmp_path / "pod-export")
    pod = PodMemoryStore(tmp_path / "pod")
    hunt = "u1__threat-1"
    spec = {
        "status": "ratified",
        "discriminators": [
            {"axis": "fault", "value": "f"},
            {"axis": "technique", "value": "keep"},
        ],
        "target": {"unit_id": "Service:u1"},
        "provenance": {"run_id": RUN},
    }

    async def _raising_builder(spec, **kw):
        raise RuntimeError("builder contract broke")

    export = asyncio.run(run_pod_session(
        spec=spec, project_id=PROJECT, run_id=RUN, hunt_key=hunt,
        spec_id="spec__f__keep", inbox=None, pod_export_store=pod_exports,
        gate=None, pod_builder=_raising_builder, pod_store=pod,
    ))

    assert export["evidence"]["terminal_reason"] == "surfer-dispatch-degraded"
    stored = pod.read_pod_export("spec__f__keep", RUN)
    assert stored["evidence"]["terminal_reason"] == "surfer-dispatch-degraded"
    assert stored["verdict"] == "unsuccessful"


def test_hunter_complete_declasses_leftover_hypothesised(tmp_path):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    hunt = "u1__threat-1"
    hunter.write_specs(
        PROJECT, hunt,
        [_spec("f", "draft", "hypothesised")],
        enforce_complete=False,
    )
    _write_set(hunter, hunt, [_spec("f", "keep", "ratified")])

    marker = hunter.settle_hypothesised(PROJECT, hunt, run_id=RUN)

    assert marker["spec_statuses"] == {
        "spec__f__draft": "dropped", "spec__f__keep": "ratified"}
    body = hunter.read_spec(PROJECT, hunt, "spec__f__draft", side="produced")
    assert body["status"] == "dropped"
    assert body["declassified"] == "hunter-complete"


def test_run_hunter_session_settles_at_graph_complete(tmp_path, monkeypatch):
    """The symbolic COMPLETE hook declasses and finalizes before the idle loop."""
    hunter = HunterMemoryStore(tmp_path / "hunter")
    hunt = "u1__threat-1"

    async def _noop_idle(**kw):
        return None

    monkeypatch.setattr(surfer_mod, "_run_hunter_idle", _noop_idle)

    def _builder(*, run_id, project_id, hunter_store):
        async def _dispatch(payload):
            hunter_store.write_specs(
                project_id, hunt,
                [_spec("f", "draft", "hypothesised")],
                enforce_complete=False,
            )
        return _dispatch, None

    asyncio.run(run_hunter_session(
        payload={}, project_id=PROJECT, run_id=RUN, hunt_key=hunt,
        band="high", hunter_store=hunter, state=RunDispatchState(),
        gate=None, hunter_builder=_builder,
    ))

    body = hunter.read_spec(PROJECT, hunt, "spec__f__draft", side="produced")
    assert body["status"] == "dropped"
    marker = hunter.read_terminal_set(PROJECT, hunt)
    assert marker is not None
    assert marker["run_id"] == RUN
    assert marker["spec_statuses"] == {"spec__f__draft": "dropped"}


def test_artifacts_terminal_blocks_a_hypothesised_current_run_spec(tmp_path):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    hunt = "u1__threat-1"
    hunter.write_specs(
        PROJECT, hunt, [_spec("f", "draft", "hypothesised")],
        enforce_complete=False,
    )
    complete, reasons = hunting_artifacts_terminal(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod,
    )
    assert complete is False
    assert any("no terminal marker" in reason for reason in reasons)


def test_artifacts_terminal_requires_a_pod_export(tmp_path):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    hunt = "u1__threat-1"
    _write_set(hunter, hunt, [_spec("f", "keep", "ratified")])
    hunter.finalize_specs(PROJECT, hunt, run_id=RUN)
    hunter.consume_spec(PROJECT, hunt, "spec__f__keep")

    complete, reasons = hunting_artifacts_terminal(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod,
    )
    assert complete is False
    assert any("no PodExport" in reason for reason in reasons)

    pod.write_pod_export(
        "spec__f__keep", RUN,
        {"verdict": "unsuccessful", "evidence": {
            "terminal_reason": "surfer-dispatch-degraded"}},
    )
    complete, reasons = hunting_artifacts_terminal(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod,
    )
    assert complete is True, reasons


def test_artifacts_terminal_ignores_a_foreign_run_spec(tmp_path):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    hunt = "u1__threat-1"
    foreign = _spec("f", "keep", "ratified")
    foreign["provenance"] = {"run_id": "another-run"}
    _write_set(hunter, hunt, [foreign])

    complete, reasons = hunting_artifacts_terminal(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod,
    )
    assert complete is True, reasons


def test_artifacts_terminal_blocks_a_malformed_current_run_spec(tmp_path):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    hunt = "u1__threat-1"
    _write_set(hunter, hunt, [_spec("f", "keep", "ratified")])
    hunter.finalize_specs(PROJECT, hunt, run_id=RUN)
    path = (
        tmp_path / "hunter" / PROJECT / "hunting" / "hunter"
        / "test-specs" / hunt / "produced" / "spec__f__keep.yaml"
    )
    path.write_text("not: [a: valid: yaml", encoding="utf-8")

    complete, reasons = hunting_artifacts_terminal(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod,
    )
    assert complete is False
    assert any("produced malformed" in reason for reason in reasons)


class _NoLiveSessions:
    def live_session_ids(self):
        return frozenset()


def test_is_run_quiesced_blocks_on_a_stale_spec(tmp_path):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    threat = ThreatModelStore(tmp_path / "threat")
    hunt = "u1__threat-1"
    hunter.write_specs(
        PROJECT, hunt, [_spec("f", "draft", "hypothesised")],
        enforce_complete=False,
    )

    complete = asyncio.run(is_run_quiesced(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        pod_store=pod, control=_NoLiveSessions(), state=RunDispatchState(),
    ))
    assert complete is False


def test_artifacts_terminal_attributes_a_malformed_spec_via_the_consumed_threat(tmp_path):
    """A malformed produced spec is current-run work when its threat is consumed.

    The threat is the run-scoped join. The audit must use it to fail closed even
    when the spec body itself cannot be parsed.
    """
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    threat = ThreatModelStore(tmp_path / "threat")
    unit = "u1"
    hunt = "u1__threat-1"
    produce_model(threat, project_id=PROJECT, unit_id=unit, run_id=RUN)
    assert threat.consume_threat(PROJECT, unit, "threat-1") is True

    spec_dir = (
        tmp_path / "hunter" / PROJECT / "hunting" / "hunter"
        / "test-specs" / hunt / "produced"
    )
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "f_bad.yaml").write_text(
        "not: [a: valid: yaml", encoding="utf-8")

    complete, reasons = hunting_artifacts_terminal(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod,
        threat_store=threat,
    )
    assert complete is False
    assert any("produced malformed" in reason for reason in reasons)


def test_run_hunter_session_settles_when_the_graph_degrades(tmp_path, monkeypatch):
    """A degraded graph still settles: no draft decision can arrive after it.

    Without this the hunt keeps no current-run terminal set, so the F-022
    consumed-threat recovery re-offers its consumed threat for ever and pins the
    cursor.
    """
    hunter = HunterMemoryStore(tmp_path / "hunter")
    hunt = "u1__threat-1"

    async def _noop_idle(**kw):
        return None

    monkeypatch.setattr(surfer_mod, "_run_hunter_idle", _noop_idle)

    def _builder(*, run_id, project_id, hunter_store):
        async def _dispatch(payload):
            hunter_store.write_specs(
                project_id, hunt,
                [_spec("f", "draft", "hypothesised")],
                enforce_complete=False,
            )
            raise RuntimeError("graph blew up")

        return _dispatch, None

    asyncio.run(run_hunter_session(
        payload={}, project_id=PROJECT, run_id=RUN, hunt_key=hunt,
        band="high", hunter_store=hunter, state=RunDispatchState(),
        gate=None, hunter_builder=_builder,
    ))

    body = hunter.read_spec(PROJECT, hunt, "spec__f__draft", side="produced")
    assert body["status"] == "dropped"
    marker = hunter.read_terminal_set(PROJECT, hunt)
    assert marker is not None
    assert marker["spec_statuses"] == {"spec__f__draft": "dropped"}


def test_a_resume_cursor_does_not_count_as_a_terminal_export(tmp_path):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    hunt = "u1__threat-1"
    _write_set(hunter, hunt, [_spec("f", "keep", "ratified")])
    hunter.finalize_specs(PROJECT, hunt, run_id=RUN)
    hunter.consume_spec(PROJECT, hunt, "spec__f__keep")
    pod.write_resume("spec__f__keep", RUN, {
        "schema_version": 1,
        "last_order": 0,
        "current_variant_ref": "v0",
        "iteration": 1,
        "feedback": "",
        "executed": [],
    })

    complete, reasons = hunting_artifacts_terminal(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod,
    )

    assert complete is False
    assert any("no PodExport" in reason for reason in reasons)


def test_demoted_produced_threat_is_not_pending_in_the_completion_audit(tmp_path):
    from tests.hunting_fixtures import risk_row

    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    produce_model(
        threat, project_id=PROJECT, unit_id="Service:u1", run_id=RUN,
        threats=[risk_row(2.0)],
    )

    complete, reasons = hunting_artifacts_terminal(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod,
        threat_store=threat, promotion_risk_threshold=5,
    )

    assert complete is True
    assert reasons == ()

    # Without the frozen floor the same produced threat is pending work and
    # the audit fails closed.
    complete, reasons = hunting_artifacts_terminal(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod,
        threat_store=threat, promotion_risk_threshold=None,
    )
    assert complete is False
    assert any("no terminal marker" in reason for reason in reasons)


def test_real_store_batched_admits_the_first_block_of_n_hunts(tmp_path):
    from tests.hunting_fixtures import risk_row

    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    produce_model(
        threat, project_id=PROJECT, unit_id="Service:u1", run_id=RUN,
        threats=[risk_row(9.3) for _ in range(3)],
    )
    hunts = [f"Service-u1__threat-{rank}" for rank in (1, 2, 3)]
    for rank, hunt in enumerate(hunts, start=1):
        _write_set(hunter, hunt, [_spec("f", f"s{rank}", "ratified")])
        hunter.finalize_specs(PROJECT, hunt, run_id=RUN)

    gate = RunSyncGate(
        mode=SyncMode.BATCHED, project_id=PROJECT, run_id=RUN,
        threat_store=threat, hunter_store=hunter, pod_store=pod,
        pod_batch_size=2,
    )
    items = [
        TestSpecItem(
            message_id=f"{hunt}/spec__f__s{rank}",
            session_id=f"hunting:{RUN}:pod:{hunt}:spec__f__s{rank}",
            hunt_key=hunt,
            spec_file=f"spec__f__s{rank}",
            spec={"status": "ratified", "target": {"unit_id": "Service:u1"}},
        )
        for rank, hunt in enumerate(hunts, start=1)
    ]

    admitted = gate.filter(items)

    assert tuple(item.message_id for item in admitted) == (
        items[0].message_id, items[1].message_id)


def test_zero_risk_model_threat_never_holds_the_pod_phase(tmp_path):
    """A model threat with risk 0 has no threat file (S2 8.3) and is refused by
    the dispatch predicate. It must not join the full hunt list and freeze the
    pod phase under the default settings."""
    from tests.hunting_fixtures import risk_row, threat_row

    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    produce_model(
        threat, project_id=PROJECT, unit_id="Service:u1", run_id=RUN,
        threats=[risk_row(9.3), threat_row(risk=0.0)],
    )
    hunt = "Service-u1__threat-1"
    _write_set(hunter, hunt, [_spec("f", "s", "ratified")])
    hunter.finalize_specs(PROJECT, hunt, run_id=RUN)
    gate = RunSyncGate(
        mode=SyncMode.BATCHED, project_id=PROJECT, run_id=RUN,
        threat_store=threat, hunter_store=hunter, pod_store=pod,
    )
    item = TestSpecItem(
        message_id=f"{hunt}/spec__f__s",
        session_id=f"hunting:{RUN}:pod:{hunt}:spec__f__s",
        hunt_key=hunt,
        spec_file="spec__f__s",
        spec=_spec("f", "s", "ratified"),
    )

    assert gate.filter([item]) == (item,)


def test_demoted_hunt_leftover_spec_is_ignored_after_the_model_moves(tmp_path):
    """The audit must still know a hunt is demoted after the unit model moves
    to consumed/: a leftover spec folder cannot block the run terminal."""
    from tests.hunting_fixtures import risk_row

    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    produce_model(
        threat, project_id=PROJECT, unit_id="Service:u1", run_id=RUN,
        threats=[risk_row(9.3), risk_row(2.0)],
    )
    promoted_hunt = "Service-u1__threat-1"
    _write_set(hunter, promoted_hunt, [_spec("f", "s", "ratified")])
    hunter.finalize_specs(PROJECT, promoted_hunt, run_id=RUN)
    pod.write_pod_export(
        "spec__f__s", RUN,
        {"verdict": "successful", "evidence": {
            "terminal_reason": "symptom-confirmed"}},
    )
    assert hunter.consume_spec(PROJECT, promoted_hunt, "spec__f__s") is True
    assert threat.consume_threat(PROJECT, "Service:u1", "threat-1") is True
    assert threat.consume_model_if_done(
        PROJECT, "Service:u1", non_pending_threats=("threat-2",)) is True

    demoted_hunt = "Service-u1__threat-2"
    _write_set(hunter, demoted_hunt, [_spec("f", "leftover", "hypothesised")])

    complete, reasons = hunting_artifacts_terminal(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod,
        threat_store=threat, promotion_risk_threshold=5,
    )

    assert complete is True, reasons
