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
from polymerhus.attack.hunting.mover import ThreatLoopItem
from polymerhus.attack.hunting.pipeline_sync import RunSyncGate, SyncMode
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
from polymerhus.attack.hunting.surfer import run_pod_session

PROJECT = "proj-lifecycle"
RUN = "run-lifecycle"


def _loop(unit_name: str, loop_id: str = "loop-1") -> ThreatLoopItem:
    dispatch = f"{unit_name}__{loop_id}"
    return ThreatLoopItem(
        message_id=dispatch,
        session_id=f"hunting:{RUN}:hunt:{dispatch}",
        unit_id=f"Service:{unit_name}",
        unit_name=unit_name,
        loop_id=loop_id,
        dispatch_id=dispatch,
        likelihood="high",
        record={"loop": {"id": loop_id}},
    )


def _spec(fault: str, strategy: str, status: str,
          unit: str = "Service:u1") -> dict:
    return {
        "status": status,
        "fault_keyword": fault,
        "strategy_keyword": strategy,
        "target": {"unit_id": unit},
        "provenance": {"run_id": RUN},
    }


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
    hunt = "u1__loop-1"
    hunter.write_specs(
        PROJECT, hunt,
        [_spec("f", "drop", "dropped"), _spec("f", "keep", "ratified")],
        enforce_complete=False,
    )
    hunter.finalize_specs(PROJECT, hunt, run_id=RUN)
    assert hunter.consume_spec(PROJECT, hunt, "f_keep") is True
    pod.write_pod_export(
        "f_keep", RUN,
        {"verdict": "successful", "evidence": {
            "terminal_reason": "symptom-confirmed"}},
    )

    gate = _gate(hunter, pod)
    next_loop = _loop("u2")
    # The dropped spec stays produced; it does not need an export. The consumed
    # ratified spec has one. The next hunter is admissible.
    assert gate.filter([next_loop]) == (next_loop,)


def test_real_store_stale_hypothesised_hunt_holds_the_queue(tmp_path):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    hunt = "u1__loop-1"
    hunter.write_specs(
        PROJECT, hunt, [_spec("f", "draft", "hypothesised")],
        enforce_complete=False,
    )

    gate = _gate(hunter, pod)
    next_loop = _loop("u2")
    assert gate.filter([next_loop]) == ()


def test_real_store_unreadable_spec_fails_closed(tmp_path):
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    hunt = "u1__loop-1"
    hunter.write_specs(
        PROJECT, hunt, [_spec("f", "keep", "ratified")],
        enforce_complete=False,
    )
    path = (
        tmp_path / "hunter" / PROJECT / "hunting" / "hunter"
        / "test-specs" / hunt / "produced" / "f_keep.yaml"
    )
    assert path.exists()
    path.write_text("not: [a: valid: yaml", encoding="utf-8")

    gate = _gate(hunter, pod)
    next_loop = _loop("u2")
    assert gate.filter([next_loop]) == ()


def test_surfer_degraded_pod_export_is_durable(tmp_path):
    """A builder exception must persist a terminal degraded PodExport.

    The serial gate counts a failed/degraded execution as terminal only when
    the durable export exists. The surfer's degraded envelope was previously
    returned without a PodExport, so the consumed spec was re-dispatched
    forever.
    """
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod = PodMemoryStore(tmp_path / "pod")
    hunt = "u1__loop-1"
    spec = {
        "status": "ratified",
        "fault_keyword": "f",
        "strategy_keyword": "keep",
        "target": {"unit_id": "Service:u1"},
        "provenance": {"run_id": RUN},
    }

    async def _raising_builder(spec, **kw):
        raise RuntimeError("builder contract broke")

    export = asyncio.run(run_pod_session(
        spec=spec, project_id=PROJECT, run_id=RUN, hunt_key=hunt,
        spec_id="f_keep", inbox=None, hunter_store=hunter, gate=None,
        pod_builder=_raising_builder, pod_store=pod,
    ))

    assert export["terminal_reason"] == "surfer-dispatch-degraded"
    stored = pod.read_pod_export("f_keep", RUN)
    assert stored["terminal_reason"] == "surfer-dispatch-degraded"
    assert stored["verdict"] == "unsuccessful"
