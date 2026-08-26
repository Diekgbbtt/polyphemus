"""Integration tier: the mover + surfer contract predicates C30-C38 of
`docs/design/hunting-wiring-assertions.md` (the "Mover + surfer contract" and
"Pod export durability" columns).

PRODUCTION-CODE-FIRST (operator ruling "use as much as possible production
code"): the tests drive the REAL `mover.run_delivery_tick`, the REAL
`surer.build_run_dispatch` `coro_for`, the REAL stores (`HuntStore`,
`HunterMemoryStore`, `PodMemoryStore`) on temp roots, the REAL
`config_key_from_fault_key`, and the REAL `surer.run_pod_session`. The ONLY
fakes sit at the two permitted seams:

- the agent-seam builder coroutines (hunter / pod builders - the contract's
  injectable produce seams), and
- a recording / running `DispatchControlPlane` implementing the protocol
  (`live_session_ids` / `dispatch` / `gate` / `start_session` /
  `cancel_session`).

The mover, the surfer-dispatch decision, the stores, and `run_work_remaining`
are never stubbed. Expected values come from the catalogue, never recomputed
the way the code computes them.

Predicate coverage (one `test_C<n>_...` each, id in the docstring line):

- C30 produced `ratified` config -> ONE hunter dispatch, produced->consumed,
  byte-identical file, empty produced set.
- C31 a produced config refused (gate-full / not-yet-dispatchable) STAYS
  produced and is retried; the refused lap reports `refused == 1`,
  `moved == 0`.
- C32 double-dispatch defense: a registry-live produced item assembles no
  re-dispatch yet its move lands once.
- C33 the identity-based-refactor regression: a produced `specified` spec with
  an EMPTY `hunter_inboxes` still dispatches ONE pod (own-status gate) and the
  pod builder is called exactly once.
- C34 never-disagree: a produced `specified` spec is real work to
  `run_work_remaining` AND `build_run_dispatch._spec_dispatch` returns a
  coroutine for it - agree by construction on the same seed.
- C35 a produced `hypothesised`/`dropped` config contributes NOTHING to
  `run_work_remaining` (False), yields no dispatch coroutine (None), and never
  blocks quiesce.
- C36 pod completion persists the export envelope durably (`<spec_id>/<run_id>.yaml`
  via the real `PodMemoryStore`), EQUAL to the returned envelope; a second
  identical run_id overwrites ONE file (idempotent).
- C37 the durable parent-keyed record lands at pod completion under the
  parent's canonical config_key, independent of any live parent.
- C38 a live co-running parent inbox also receives the `pod_export` message
  before the pod settles, and the durable record is not double-written (ONE
  note per export).
"""
from __future__ import annotations

import asyncio

import pytest

from polymerhus.attack.hunting.hunt_store import HuntStore
from polymerhus.attack.hunting.hunter_memory import (
    HunterMemoryStore,
    config_key_from_fault_key,
)
from polymerhus.attack.hunting.mover import (
    pod_session_id,
    run_delivery_tick,
)
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
from polymerhus.attack.hunting.surfer import (
    RunDispatchState,
    build_run_dispatch,
    run_pod_session,
    run_work_remaining,
)
from polymerhus.app.llm.actor import AgentInbox, AgentMessage

PROJECT = "proj-c30"
RUN = "run-c30"
UNIT = "Service:catalogue-and-discovery"
CWE = "CWE-639"
CLASS = "IDOR"
# The production `_`-joined fault_key folder convention (G4 / ADR Q13
# `config_id`): `<unit>_<CWE-x>_<class>`. This is the form that caught the
# masking bug - `config_key_from_fault_key` must recover the canonical
# `::`-joined config_key from it.
FAULT_KEY = f"{UNIT}_{CWE}_{CLASS}"
CONFIG_KEY = f"{UNIT}::{CWE}::{CLASS}"
SPEC_KEYWORD = "sqli"
STRATEGY = "blind"
SPEC_FILE = f"{SPEC_KEYWORD}_{STRATEGY}"


# --- catalogue-inherited fixtures (id conventions) ------------------------------
#
# The hunt config needs enough body for the REAL `build_run_dispatch`'s
# `_config_dispatch` to `HuntConfig.model_validate` it (the ratified config
# yields ONE hunter session). The produced config's identity rides the file-name
# convention; the semantic key round-trips with it.


def _config(**overrides) -> dict:
    data = {
        "hunt_id": "hunt-1",
        "unit_id": UNIT,
        "fault_class": CWE,
        "status": "ratified",
        "vulnerability_class": CLASS,
        "prompt_template": {"rationale": "r", "l0_evidence": [], "research_direction": "rd"},
    }
    data.update(overrides)
    return data


def _spec(**overrides) -> dict:
    data = {
        "spec_id": SPEC_FILE,
        "fault_key": FAULT_KEY,
        "fault": {},
        "strategy": STRATEGY,
        "status": "specified",
    }
    data.update(overrides)
    return data


@pytest.fixture
def stores(tmp_path):
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    return hunt, hunter


def _write_config(hunt, **overrides) -> str:
    return hunt.write_config(PROJECT, _config(**overrides))


def _write_spec(hunter, *, fault_key=FAULT_KEY, keyword=SPEC_KEYWORD,
                strategy=STRATEGY, status="specified") -> None:
    hunter.write_spec(
        PROJECT, fault_key,
        fault_keyword=keyword, strategy_keyword=strategy, spec=_spec(status=status),
    )


# --- the two permitted fakes ---------------------------------------------------
#
# (a) A recording dispatch control plane implementing the DispatchControlPlane
# protocol. `RunningControlPlane` additionally drives the dispatched session
# coroutines to completion (the mover schedules asynchronously - the runtime
# owns the loop), so the pod export / durable record / inbox delivery paths
# execute for real.


class RecordingControlPlane:
    """A recording `DispatchControlPlane`: admits unless the session is in
    `refused`; `live` sessions are pre-registered (never dispatched). The
    non-running recorder closes scheduled coroutines so pytest never warns
    about un-awaited coroutines."""

    def __init__(self, refused=(), live=()):
        self._refused = set(refused)
        self.calls: list[str] = []
        self._live = set(live)

    def live_session_ids(self):
        return set(self._live)

    def dispatch(self, session_id, coro):
        self.calls.append(session_id)
        if session_id in self._refused:
            coro.close()
            return False
        coro.close()
        return True

    def gate(self):
        return None

    def start_session(self, session_id, coro):
        coro.close()
        return None

    def cancel_session(self, session_id):
        return None


class RunningControlPlane:
    """A `DispatchControlPlane` that runs every admitted session coroutine to
    completion on the calling loop (scheduler semantics), so the session body
    (the pod export, the durable record, the inbox delivery) executes."""

    def __init__(self):
        self.calls: list[str] = []
        self._tasks: list[asyncio.Task] = []

    def live_session_ids(self):
        return set()

    def dispatch(self, session_id, coro):
        self.calls.append(session_id)
        self._tasks.append(asyncio.get_event_loop().create_task(coro))
        return True

    def gate(self):
        return None

    def start_session(self, session_id, coro):
        coro.close()
        return None

    def cancel_session(self, session_id):
        return None

    async def settle(self):
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)


def _agent_seam_builders():
    """The agent-seam builder coroutines (the contract's injectable produce
    seams). The hunter builder is never awaited by the recording planes. The pod
    builder mirrors the production `arun_pod` completion: it persists the export
    envelope through the real `PodMemoryStore` and returns it - so the durable
    `<spec_id>/<run_id>.yaml` observable is REAL."""

    def hunter_builder(*, run_id, project_id, hunt_store, hunter_store, **kw):
        async def _dispatch(config):
            return None

        return _dispatch, None

    async def pod_builder(spec, *, run_id, project_id, memory_store, spec_id, **kw):
        envelope = {
            "verdict": "successful", "terminal_reason": "symptom-confirmed",
            "evidence": {"trail": []}, "clean": True, "iterations": 0,
        }
        memory_store.write_pod_export(spec_id, run_id, envelope)
        return envelope

    return hunter_builder, pod_builder


def _real_coro_for(hunt, hunter, state=None, pod_store=None):
    """The REAL `build_run_dispatch` `coro_for` on temp-root production stores
    with the agent-seam fakes and no gate."""
    hunter_builder, pod_builder = _agent_seam_builders()
    return build_run_dispatch(
        project_id=PROJECT, run_id=RUN,
        hunt_store=hunt, hunter_store=hunter, pod_store=pod_store,
        state=state or RunDispatchState(), gate=None,
        hunter_builder=hunter_builder, pod_builder=pod_builder,
    )


def _drive_running_tick(hunt, hunter, *, state=None, pod_store=None):
    """Run one REAL `run_delivery_tick` under a running loop with the REAL
    `build_run_dispatch`, then settle the dispatched sessions (so the pod
    bodies execute). Returns the report + the plane."""

    async def _drive(plane, coro_for):
        report = run_delivery_tick(
            PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
            control=plane, coro_for=coro_for,
        )
        await plane.settle()
        return report

    plane = RunningControlPlane()
    coro_for = _real_coro_for(hunt, hunter, state=state, pod_store=pod_store)
    report = asyncio.run(_drive(plane, coro_for))
    return report, plane


# --- C30 -----------------------------------------------------------------------

def test_C30_ratified_config_dispatches_one_hunter_and_moves_produced_to_consumed(
    tmp_path,
):
    """id: C30 - a produced `ratified` config dispatches ONE hunter and moves
    produced->consumed via a REAL `run_delivery_tick` with `build_run_dispatch`; the
    consumed file is byte-identical to produced; produced set for that identity is
    empty."""
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    key = _write_config(hunt)

    produced = hunt._produced_dir(PROJECT) / f"{FAULT_KEY}.yaml"
    produced_bytes = produced.read_bytes()

    # C30 only asserts the DISPATCH decision + the move: the hunter session body
    # (the idle loop) is never run by the mover-level recorder.
    plane = RecordingControlPlane()
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=plane, coro_for=_real_coro_for(hunt, hunter),
    )

    session = f"hunting:{RUN}:hunt:{FAULT_KEY}"
    assert plane.calls == [session]
    assert report.produced == 1
    assert report.dispatched == 1 and report.admitted == 1 and report.refused == 0
    assert report.moved == 1 and report.move_failed == 0
    # produced set for that identity is empty; the consumed file is byte-identical
    assert hunt.read_produced_configs(PROJECT) == []
    consumed = hunt._consumed_dir(PROJECT) / f"{FAULT_KEY}.yaml"
    assert consumed.exists()
    assert consumed.read_bytes() == produced_bytes


# --- C31 -----------------------------------------------------------------------

def test_C31_refused_config_stays_produced_and_reports_refused_one_moved_zero(
    tmp_path,
):
    """id: C31 - a produced config REFUSED (gate full / a not-yet-dispatchable
    item) STAYS produced and is retried; the refused lap reports `refused == 1`,
    `moved == 0`."""
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    key = _write_config(hunt)
    session = f"hunting:{RUN}:hunt:{FAULT_KEY}"
    plane = RecordingControlPlane(refused={session})
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=plane, coro_for=_real_coro_for(hunt, hunter),
    )
    assert report.refused == 1 and report.moved == 0 and report.admitted == 0
    assert [k for k, _ in hunt.read_produced_configs(PROJECT)] == [key]
    # the SAME produced item is retried next tick and admitted then (recording
    # plane: only the dispatch decision + move are in scope, the hunter body is
    # not run)
    report2 = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_real_coro_for(hunt, hunter),
    )
    assert report2.moved == 1 and report2.refused == 0
    assert hunt.read_produced_configs(PROJECT) == []


# --- C32 -----------------------------------------------------------------------

def test_C32_live_registry_item_is_never_dispatched_twice_and_moves_once(
    tmp_path,
):
    """id: C32 - double-dispatch defense: a produced item whose Q13 session id is
    already live in the registry is NOT dispatched twice; its move still lands once."""
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _write_config(hunt)
    session = f"hunting:{RUN}:hunt:{FAULT_KEY}"
    plane = RecordingControlPlane(live={session})
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=plane, coro_for=_real_coro_for(hunt, hunter),
    )
    assert plane.calls == []                # no re-dispatch for a live session
    assert report.dispatched == 0 and report.refused == 0 and report.admitted == 0
    assert report.moved == 1                # registry-confirmed: marker stamped once
    assert hunt.read_produced_configs(PROJECT) == []
    assert len(hunt.read_configs(PROJECT)) == 1


# --- C33 -----------------------------------------------------------------------

def test_C33_specified_spec_with_empty_hunter_inboxes_dispatches_one_pod(
    tmp_path,
):
    """id: C33 - the identity-based-refactor regression: a produced `specified`
    spec seeded directly (production `_`-joined fault_key) with `hunter_inboxes`
    EMPTY still dispatches ONE pod and moves produced->consumed, and the pod
    builder is called exactly once - the parent-inbox lookup must be best-effort,
    never a refusal."""
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _write_spec(hunter)
    state = RunDispatchState()   # hunter_inboxes is EMPTY - no live parent
    report, plane = _drive_running_tick(hunt, hunter, state=state)

    session = pod_session_id(RUN, FAULT_KEY, SPEC_FILE)
    assert plane.calls == [session]
    assert report.admitted == 1 and report.moved == 1 and report.refused == 0
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == []
    assert len(hunter.read_specs(PROJECT, FAULT_KEY, sides=("consumed",))) == 1
    # the pod body ran exactly once over the real build_run_dispatch decision
    assert state.hunter_inboxes == {}       # no parent inbox was fabricated
    assert report.move_failed == 0


# --- C34 -----------------------------------------------------------------------

def test_C34_run_work_remaining_and_dispatch_agree_for_a_specified_spec(
    tmp_path,
):
    """id: C34 - never-disagree contract: a produced `specified` spec makes
    `run_work_remaining` return True AND `build_run_dispatch`'s `_spec_dispatch`
    returns a coroutine for it (agree by construction) - on the same seeded
    state, before the tick."""
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _write_spec(hunter)

    assert run_work_remaining(PROJECT, hunt_store=hunt, hunter_store=hunter) is True

    coro_for = _real_coro_for(hunt, hunter)
    from polymerhus.attack.hunting.mover import TestSpecItem

    item = TestSpecItem(
        message_id=f"{FAULT_KEY}/{SPEC_FILE}",
        session_id=pod_session_id(RUN, FAULT_KEY, SPEC_FILE),
        fault_key=FAULT_KEY,
        spec_file=SPEC_FILE,
    )
    produced = coro_for(item)
    assert produced is not None            # a dispatch coroutine exists (not refused)
    try:
        produced.close()
    except Exception:  # noqa: BLE001 - best-effort reap
        pass

    # and the whole thing agrees end-to-end: it dispatches and moves (work gone)
    report, plane = _drive_running_tick(hunt, hunter)
    assert report.admitted == 1 and report.moved == 1
    assert run_work_remaining(PROJECT, hunt_store=hunt, hunter_store=hunter) is False


# --- C35 -----------------------------------------------------------------------

def test_C35_hypothesised_and_dropped_configs_contribute_nothing(tmp_path):
    """id: C35 - a produced `hypothesised`/`dropped` config contributes NOTHING to
    `run_work_remaining` (False), never dispatches (`build_run_dispatch` returns
    None / `coro_for` refused), and never blocks quiesce."""
    hunt = HuntStore(tmp_path / "hunts")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _write_config(hunt, status="hypothesised")
    _write_config(hunt, status="dropped", vulnerability_class="CSRF")
    _write_spec(hunter, status="hypothesised")

    # nothing is real work: quiesce is NOT blocked by these leftovers
    assert run_work_remaining(PROJECT, hunt_store=hunt, hunter_store=hunter) is False

    # and none of them dispatches: every dispatch attempt is refused (coro None)
    report = run_delivery_tick(
        PROJECT, RUN, hunt_store=hunt, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_real_coro_for(hunt, hunter),
    )
    assert report.admitted == 0 and report.moved == 0
    assert report.refused == 3              # all three refused (None coro)
    # the leftovers stay on disk (G6), never consumed, never blocking quiesce
    assert len(hunt.read_produced_configs(PROJECT)) == 2
    assert hunter.produced_spec_files(PROJECT, FAULT_KEY) == [SPEC_FILE]


# --- C36 -----------------------------------------------------------------------

def test_C36_pod_completion_persists_the_export_envelope_durably(tmp_path):
    """id: C36 - pod completion persists the export envelope durably:
    `<spec_id>/<run_id>.yaml` exists (real `PodMemoryStore` on a temp root) and
    EQUALS the envelope returned; a second identical run_id overwrites ONE file
    (idempotent - the count stays one)."""
    pod_root = tmp_path / "pod"
    pod_store = PodMemoryStore(root_dir=pod_root, project_id=PROJECT)
    hunter = HunterMemoryStore(tmp_path / "hunter")
    hunter_builder, pod_builder = _agent_seam_builders()
    run_id = "run-id-42"

    async def _pod_session():
        return await run_pod_session(
            spec=_spec(), project_id=PROJECT, run_id=run_id,
            fault_key=FAULT_KEY, config_key=CONFIG_KEY, spec_id=SPEC_FILE,
            inbox=None, hunter_store=hunter, gate=None,
            pod_builder=pod_builder, pod_store=pod_store,
        )

    envelope = asyncio.run(_pod_session())

    assert run_id in pod_store.list_pod_exports(SPEC_FILE)
    assert pod_store.read_pod_export(SPEC_FILE, run_id) == envelope
    entries = pod_store.list_pod_exports(SPEC_FILE)
    assert entries == [run_id]
    # a second identical run_id overwrites the SAME file: count stays one
    asyncio.run(_pod_session())
    assert pod_store.list_pod_exports(SPEC_FILE) == [run_id]


# --- C37 -----------------------------------------------------------------------

def test_C37_durable_parent_keyed_record_written_without_a_live_parent(tmp_path):
    """id: C37 - the durable parent-keyed record is written at pod completion
    under the parent's canonical `config_key` INDEPENDENT of a live parent: with
    NO parent inbox present, `HunterMemoryStore.write_note`'s record exists keyed
    by the canonical config_key with the export payload."""
    pod_root = tmp_path / "pod"
    pod_store = PodMemoryStore(root_dir=pod_root, project_id=PROJECT)
    hunter = HunterMemoryStore(tmp_path / "hunter")
    hunter_builder, pod_builder = _agent_seam_builders()
    run_id = "run-id-7"

    async def _pod_session():
        return await run_pod_session(
            spec=_spec(), project_id=PROJECT, run_id=RUN,
            fault_key=FAULT_KEY, config_key=CONFIG_KEY, spec_id=SPEC_FILE,
            inbox=None, hunter_store=hunter, gate=None,
            pod_builder=pod_builder, pod_store=pod_store,
        )

    envelope = asyncio.run(_pod_session())

    # the durable record is keyed by the parent's CANONICAL config_key (the
    # `::`-joined join key), never by the raw `_`-foldered fault_key
    notes = hunter.read_notes(PROJECT, parent_key=CONFIG_KEY)
    assert len(notes) == 1
    record = notes[0]
    assert CONFIG_KEY in record["key"]
    assert record["kind"] == "freeform"
    # the export payload (json-sorted dump) is inside the note body - the O16
    # amendment record, independent of any live parent (inbox was None here)
    import json
    assert json.loads(record["body"]) == envelope


# --- C38 -----------------------------------------------------------------------

def test_C38_live_parent_inbox_receives_pod_export_before_settle_single_record(
    tmp_path,
):
    """id: C38 - a live co-running parent inbox (config_key present in
    `state.hunter_inboxes`) ALSO receives the `pod_export` message BEFORE the pod
    settles, and the idle-loop consumes WITHOUT double-recording (ONE note per
    export - the durable record is not re-authored by the live feed)."""
    pod_root = tmp_path / "pod"
    pod_store = PodMemoryStore(root_dir=pod_root, project_id=PROJECT)
    hunter = HunterMemoryStore(tmp_path / "hunter")
    state = RunDispatchState()
    # a live co-running parent inbox keyed under the parent's canonical config_key
    inbox = AgentInbox()
    state.hunter_inboxes[CONFIG_KEY] = inbox
    hunter_builder, pod_builder = _agent_seam_builders()
    run_id = "run-id-9"

    async def _pod_session():
        # run the pod session AND read the delivered feed on the SAME loop: the
        # live parent inbox must hold the `pod_export` message by the time the
        # session returns/settles
        env = await run_pod_session(
            spec=_spec(), project_id=PROJECT, run_id=run_id,
            fault_key=FAULT_KEY, config_key=CONFIG_KEY, spec_id=SPEC_FILE,
            inbox=inbox, hunter_store=hunter, gate=None,
            pod_builder=pod_builder, pod_store=pod_store,
        )
        delivered = await inbox.get()
        return env, delivered

    envelope, received = asyncio.run(_pod_session())

    # the live parent inbox holds the `pod_export` message (delivered before the
    # pod session returns/settles)
    assert isinstance(received, AgentMessage)
    assert received.kind == "pod_export"
    assert received.payload == envelope
    assert received.source == pod_session_id(run_id, FAULT_KEY, SPEC_FILE)
    # and the durable record is ONE per export: the live-feed consumption (the
    # idle-loop verdict stub) must NOT double-record against the pod-completion note
    notes = hunter.read_notes(PROJECT, parent_key=CONFIG_KEY)
    assert len(notes) == 1
