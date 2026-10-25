"""Unit tier: the surfer wiring for `hunting_pipeline_sync`.

The surfer consults the run's sync gate once per tick and passes its verdict to
the mover as the pre-filter: a held threat file never reaches the control plane
and stays produced. The gate receives the live session set and the run's
mid-graph hunt set, so a resumed run and a phase barrier read the same facts.

The policy itself is pinned in `test_hunting_pipeline_sync.py`; this file pins
the SEAM - the surfer calls the gate and the mover honours it.
"""
from __future__ import annotations

import asyncio

from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.mover import hunter_session_id
from polymerhus.attack.hunting.surfer import RunDispatchState, run_surfer_loop
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore

from tests.hunting_fixtures import produce_model

PROJECT = "proj-1"
RUN = "run-1"
UNIT = "Service:catalogue-and-discovery"
UNIT_NAME = "Service-catalogue-and-discovery"
DISPATCH = f"{UNIT_NAME}__threat-1"


class RecordingControl:
    def __init__(self):
        self.calls: list[str] = []

    def live_session_ids(self):
        return set()

    def dispatch(self, session_id, coro):
        self.calls.append(session_id)
        coro.close()
        return True


class GateSpy:
    """Records the facts the surfer supplies and admits at the marked tick."""

    def __init__(self):
        self.calls: list[tuple] = []
        self.allow = False

    def filter(self, items, *, live_session_ids=(), hunts_in_graph=()):
        self.calls.append((
            tuple(items), frozenset(live_session_ids), frozenset(hunts_in_graph)))
        return tuple(items) if self.allow else ()


async def _noop():
    return None


def test_surfer_holds_the_threat_file_until_the_sync_gate_admits_it(tmp_path):
    async def scenario():
        threat = ThreatModelStore(tmp_path / "threat")
        hunter = HunterMemoryStore(tmp_path / "hunter")
        produce_model(threat, project_id=PROJECT, unit_id=UNIT, run_id=RUN)
        control = RecordingControl()
        gate = GateSpy()
        state = RunDispatchState(sync_gate=gate)

        def coro_for(item):
            # F-022: the produced->consumed move is admission; the terminal spec
            # set is completion, so the fake hunt must finalize or it would be
            # recovered and re-dispatched forever.
            hunter.finalize_specs(PROJECT, item.dispatch_id, run_id=RUN)
            return _noop()

        task = asyncio.create_task(run_surfer_loop(
            PROJECT, RUN,
            threat_store=threat,
            hunter_store=hunter,
            pod_store=None,
            control=control,
            coro_for=coro_for,
            state=state,
            tick_interval=0.01,
        ))
        for _ in range(200):
            if gate.calls:
                break
            await asyncio.sleep(0.01)
        held = list(control.calls)
        gate.allow = True
        report = await asyncio.wait_for(task, timeout=5)
        return report, held, control, gate

    report, held, control, gate = asyncio.run(scenario())

    assert held == []
    assert report.quiesced is True
    assert control.calls == [hunter_session_id(RUN, DISPATCH)]

    items, live, graph = gate.calls[0]
    assert [item.dispatch_id for item in items] == [DISPATCH]
    assert live == frozenset()
    assert graph == frozenset()
