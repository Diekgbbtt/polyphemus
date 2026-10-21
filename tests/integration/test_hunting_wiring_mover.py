"""Integration tier: the mover + surfer contract predicates C30-C38 of
`docs/design/hunting-wiring-assertions.md` (the "Mover + surfer contract" and
"Pod export durability" columns).

PRODUCTION-CODE-FIRST (operator ruling "use as much as possible production
code"): the tests drive the REAL `mover.run_delivery_tick`, the REAL
`surfer.build_run_dispatch` `coro_for`, the REAL stores (`ThreatModelStore`,
`HunterMemoryStore`, `PodMemoryStore`) on temp roots, the REAL
and the REAL `surfer.run_pod_session`. The ONLY
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

- C30 produced loop file -> ONE hunter dispatch, produced->consumed,
  byte-identical file, empty produced set.
- C31 a produced loop refused (gate-full / not-yet-dispatchable) STAYS
  produced and is retried; the refused lap reports `refused == 1`,
  `moved == 0`.
- C32 double-dispatch defense: a registry-live produced item assembles no
  re-dispatch yet its move lands once.
- C33 the identity-based-refactor regression: a produced `ratified` spec with
  an EMPTY `hunter_inboxes` still dispatches ONE pod (own-status gate) and the
  pod builder is called exactly once.
- C34 never-disagree: a produced `ratified` spec is real work to
  `run_work_remaining` AND `build_run_dispatch._spec_dispatch` returns a
  coroutine for it - agree by construction on the same seed.
- C35 a produced loop file from ANOTHER run, and a malformed loop file,
  contribute NOTHING to `run_work_remaining` (False), yield no dispatch
  coroutine (None), and never block quiesce (T4b re-pointed the retired
  config-status predicate onto the ONE loop validity predicate).
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

from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.mover import (
    TestSpecItem,
    pod_session_id,
    read_produced_inbox,
    run_delivery_tick,
)
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
from polymerhus.attack.hunting.surfer import (
    RunDispatchState,
    build_run_dispatch,
    run_pod_session,
    run_work_remaining,
)
from polymerhus.app.llm.actor import AgentInbox, AgentMessage

from tests.hunting_fixtures import produce_model

PROJECT = "proj-c30"
RUN = "run-c30"
UNIT = "Service:catalogue-and-discovery"
CWE = "CWE-639"
CLASS = "IDOR"
OTHER_UNIT = "Service:other-bounded-context"
OTHER_NAME = "Service-other-bounded-context"
UNIT_NAME = "Service-catalogue-and-discovery"
DISPATCH_ID = f"{UNIT_NAME}__loop-1"
SPEC_KEYWORD = "sqli"
STRATEGY = "blind"
SPEC_FILE = f"{SPEC_KEYWORD}_{STRATEGY}"


# --- catalogue-inherited fixtures (id conventions) ------------------------------
#
# The dispatch input is the produced LOOP file (S2 8.4): the real store's five
# gates yield ONE hunter session per loop file. The retired config family is not
# dispatch input (T4b #387).


def _produce(threat, *, run_id=RUN):
    """One produced COMPLETED valid model with its loop file (S2 8.1)."""
    return produce_model(
        threat, project_id=PROJECT, unit_id=UNIT, run_id=run_id)


def _spec(**overrides) -> dict:
    data = {
        "status": "ratified",
        "fault_keyword": SPEC_KEYWORD,
        "strategy_keyword": STRATEGY,
        "verification_symptoms": ["a foreign item renders"],
    }
    data.update(overrides)
    return data


@pytest.fixture
def stores(tmp_path):
    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    return threat, hunter


def _write_spec(hunter, *, hunt_key=DISPATCH_ID, keyword=SPEC_KEYWORD,
                strategy=STRATEGY, status="ratified") -> None:
    hunter.write_specs(
        PROJECT, hunt_key,
        [_spec(status=status, fault_keyword=keyword, strategy_keyword=strategy)],
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

    def hunter_builder(*, run_id, project_id, hunter_store, **kw):
        async def _dispatch(payload):
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


def _real_coro_for(threat, hunter, state=None, pod_store=None):
    """The REAL `build_run_dispatch` `coro_for` on temp-root production stores
    with the agent-seam fakes and no gate."""
    hunter_builder, pod_builder = _agent_seam_builders()
    return build_run_dispatch(
        project_id=PROJECT, run_id=RUN,
        threat_store=threat, hunter_store=hunter, pod_store=pod_store,
        state=state or RunDispatchState(), gate=None,
        hunter_builder=hunter_builder, pod_builder=pod_builder,
    )


def _drive_running_tick(threat, hunter, *, state=None, pod_store=None):
    """Run one REAL `run_delivery_tick` under a running loop with the REAL
    `build_run_dispatch`, then settle the dispatched sessions (so the pod
    bodies execute). Returns the report + the plane."""

    async def _drive(plane, coro_for):
        report = run_delivery_tick(
            PROJECT, RUN, threat_store=threat, hunter_store=hunter,
            pod_store=pod_store, control=plane, coro_for=coro_for,
        )
        await plane.settle()
        return report

    plane = RunningControlPlane()
    coro_for = _real_coro_for(threat, hunter, state=state, pod_store=pod_store)
    report = asyncio.run(_drive(plane, coro_for))
    return report, plane


# --- C30 -----------------------------------------------------------------------

def test_C30_produced_loop_dispatches_one_hunter_and_moves_produced_to_consumed(
    tmp_path,
):
    """id: C30 - a produced loop file dispatches ONE hunter and moves
    produced->consumed via a REAL `run_delivery_tick` with `build_run_dispatch`;
    the consumed file is byte-identical to produced; produced set for that
    identity is empty."""
    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _produce(threat)

    produced = (tmp_path / "threat" / PROJECT / "hunting" / "threat_modeller"
                / "produced" / UNIT_NAME / "loop-1.yaml")
    produced_bytes = produced.read_bytes()

    # C30 only asserts the DISPATCH decision + the move: the hunter session body
    # (the idle loop) is never run by the mover-level recorder.
    plane = RecordingControlPlane()
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=plane, coro_for=_real_coro_for(threat, hunter),
    )

    session = f"hunting:{RUN}:hunt:{DISPATCH_ID}"
    assert plane.calls == [session]
    assert report.produced == 1
    assert report.dispatched == 1 and report.admitted == 1 and report.refused == 0
    assert report.moved == 1 and report.move_failed == 0
    # produced set for that identity is empty; the consumed file is byte-identical
    assert threat.read_produced_loops(PROJECT) == []
    consumed = (tmp_path / "threat" / PROJECT / "hunting" / "threat_modeller"
                / "consumed" / UNIT_NAME / "loop-1.yaml")
    assert consumed.exists()
    assert consumed.read_bytes() == produced_bytes


# --- C31 -----------------------------------------------------------------------

def test_C31_refused_loop_stays_produced_and_reports_refused_one_moved_zero(
    tmp_path,
):
    """id: C31 - a produced loop file REFUSED (gate full / a not-yet-dispatchable
    item) STAYS produced and is retried; the refused lap reports `refused == 1`,
    `moved == 0`."""
    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _produce(threat)
    session = f"hunting:{RUN}:hunt:{DISPATCH_ID}"
    plane = RecordingControlPlane(refused={session})
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=plane, coro_for=_real_coro_for(threat, hunter),
    )
    assert report.refused == 1 and report.moved == 0 and report.admitted == 0
    assert [entry["loop_id"] for entry in
            threat.read_produced_loops(PROJECT)[0]["loops"]] == ["loop-1"]
    # the SAME produced item is retried next tick and admitted then (recording
    # plane: only the dispatch decision + move are in scope, the hunter body is
    # not run)
    report2 = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_real_coro_for(threat, hunter),
    )
    assert report2.moved == 1 and report2.refused == 0
    assert threat.read_produced_loops(PROJECT) == []


# --- C32 -----------------------------------------------------------------------

def test_C32_live_registry_item_is_never_dispatched_twice_and_moves_once(
    tmp_path,
):
    """id: C32 - double-dispatch defense: a produced item whose Q13 session id is
    already live in the registry is NOT dispatched twice; its move still lands once."""
    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _produce(threat)
    session = f"hunting:{RUN}:hunt:{DISPATCH_ID}"
    plane = RecordingControlPlane(live={session})
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=plane, coro_for=_real_coro_for(threat, hunter),
    )
    assert plane.calls == []                # no re-dispatch for a live session
    assert report.dispatched == 0 and report.refused == 0 and report.admitted == 0
    assert report.moved == 1                # registry-confirmed: marker stamped once
    assert threat.read_produced_loops(PROJECT) == []
    assert threat.read_completed_units(PROJECT) == [UNIT]


# --- C33 -----------------------------------------------------------------------

def test_C33_ratified_spec_with_empty_hunter_inboxes_dispatches_one_pod(
    tmp_path,
):
    """id: C33 - the identity-based-refactor regression: a produced `ratified`
    spec seeded directly (production `_`-joined fault_key) with `hunter_inboxes`
    EMPTY still dispatches ONE pod and moves produced->consumed, and the pod
    builder is called exactly once - the parent-inbox lookup must be best-effort,
    never a refusal."""
    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _write_spec(hunter)
    state = RunDispatchState()   # hunter_inboxes is EMPTY - no live parent
    report, plane = _drive_running_tick(threat, hunter, state=state)

    session = pod_session_id(RUN, DISPATCH_ID, SPEC_FILE)
    assert plane.calls == [session]
    assert report.admitted == 1 and report.moved == 1 and report.refused == 0
    assert hunter.produced_spec_files(PROJECT, DISPATCH_ID) == []
    assert len(hunter.read_specs(PROJECT, DISPATCH_ID, sides=("consumed",))) == 1
    # the pod body ran exactly once over the real build_run_dispatch decision
    assert state.hunter_inboxes == {}       # no parent inbox was fabricated
    assert report.move_failed == 0


# --- C34 -----------------------------------------------------------------------

def test_C34_run_work_remaining_and_dispatch_agree_for_a_ratified_spec(
    tmp_path,
):
    """id: C34 - never-disagree contract: a produced `ratified` spec makes
    `run_work_remaining` return True AND `build_run_dispatch`'s `_spec_dispatch`
    returns a coroutine for it (agree by construction) - on the same seeded
    state, before the tick."""
    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _write_spec(hunter)

    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter) is True

    coro_for = _real_coro_for(threat, hunter)
    from polymerhus.attack.hunting.mover import TestSpecItem

    item = TestSpecItem(
        message_id=f"{DISPATCH_ID}/{SPEC_FILE}",
        session_id=pod_session_id(RUN, DISPATCH_ID, SPEC_FILE),
        hunt_key=DISPATCH_ID,
        spec_file=SPEC_FILE,
    )
    produced = coro_for(item)
    assert produced is not None            # a dispatch coroutine exists (not refused)
    try:
        produced.close()
    except Exception:  # noqa: BLE001 - best-effort reap
        pass

    # and the whole thing agrees end-to-end: it dispatches and moves (work gone)
    report, plane = _drive_running_tick(threat, hunter)
    assert report.admitted == 1 and report.moved == 1
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter) is False


# --- C35 -----------------------------------------------------------------------

def test_C35_a_foreign_loop_and_a_draft_spec_contribute_nothing(tmp_path):
    """id: C35 (part 1) - a produced loop file from ANOTHER run and a draft
    spec contribute NOTHING to `run_work_remaining` (False), never dispatch
    (`build_run_dispatch` returns None / `coro_for` refused), and never block
    quiesce. T4b replaced the retired config-status predicate with the ONE loop
    validity predicate; the pod family's own status gate is asserted too."""
    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    # a valid loop file belonging to ANOTHER run, under a DIFFERENT unit so it
    # coexists with the current run's file (the previous same-unit overwrite
    # made the "another run" case unreachable)
    produce_model(threat, project_id=PROJECT, unit_id=OTHER_UNIT,
                  run_id="another-run")
    # the current run's own zero-loop model: consumed as work, never dispatched
    produce_model(threat, project_id=PROJECT, unit_id=UNIT, run_id=RUN)
    path = (tmp_path / "threat" / PROJECT / "hunting" / "threat_modeller"
            / "produced" / UNIT_NAME / "loop-1.yaml")
    path.unlink()
    _write_spec(hunter, status="hypothesised")

    # the current run's zero-loop model is consumable work; the foreign loop
    # and the draft spec contribute nothing.
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter) is True
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_real_coro_for(threat, hunter),
    )
    assert report.admitted == 0 and report.dispatched == 0
    assert report.models_consumed == 1          # only the zero-loop model moved
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter) is False
    # the foreign loop stays on disk, never consumed, never blocking quiesce
    assert (threat._family_dir(PROJECT, "produced") / OTHER_NAME / "loop-1.yaml").exists()  # noqa: SLF001
    assert hunter.produced_spec_files(PROJECT, DISPATCH_ID) == [SPEC_FILE]


def test_C35b_a_malformed_loop_is_refused_and_never_blocks_quiesce(tmp_path):
    """id: C35 (part 2) - a malformed loop file of THIS run is refused, never
    dispatched, and never counted as a pending loop. Its consumable model is the
    only work: the tick moves it and quiesce clears. The malformed file stays in
    `produced/` as evidence.

    The previous version of this test mutated `body["loop"] = None`; the store
    reads the loop record from the MODEL document, so that mutation was a no-op
    and the malformed case was never exercised (T10 fix)."""
    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    _produce(threat, run_id=RUN)
    path = (tmp_path / "threat" / PROJECT / "hunting" / "threat_modeller"
            / "produced" / UNIT_NAME / "loop-1.yaml")
    path.write_text("- not a mapping\n", encoding="utf-8")
    _write_spec(hunter, status="hypothesised")

    # the malformed loop contributes no DISPATCH, but the model move is work
    report = run_delivery_tick(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter,
        control=RecordingControlPlane(), coro_for=_real_coro_for(threat, hunter),
    )
    assert report.admitted == 0 and report.dispatched == 0
    assert report.models_consumed == 1
    # the malformed file stays in produced/ (evidence), never consumed
    assert path.exists()
    assert threat.read_produced_loops(PROJECT) == []
    assert run_work_remaining(
        PROJECT, RUN, threat_store=threat, hunter_store=hunter) is False


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
            hunt_key=DISPATCH_ID, spec_id=SPEC_FILE,
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


# --- C40/C41: consumed-spec reconciliation on resume (F-017) ------------------

def test_C40_consumed_ratified_spec_without_export_is_redispatched(tmp_path):
    """F-017 regression: a spec consumed at admission but with no terminal
    PodExport (the provider pause) is recovered as dispatchable work on resume.
    The recovered item is the same loop/spec identity and the REAL dispatch
    carries it to a pod."""
    pod_store = PodMemoryStore(root_dir=tmp_path / "pod", project_id=PROJECT)
    hunter = HunterMemoryStore(tmp_path / "hunter")
    hunter.write_specs(
        PROJECT, DISPATCH_ID,
        [_spec(provenance={"run_id": RUN})], side="consumed")

    inbox = read_produced_inbox(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod_store)
    items = [item for item in inbox.items if isinstance(item, TestSpecItem)]
    assert len(items) == 1
    assert items[0].recovered is True
    assert items[0].message_id == f"{DISPATCH_ID}/{SPEC_FILE}"
    assert run_work_remaining(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod_store) is True

    report, plane = _drive_running_tick(
        None, hunter, pod_store=pod_store)
    assert plane.calls == [pod_session_id(RUN, DISPATCH_ID, SPEC_FILE)]
    assert report.admitted == 1 and report.moved == 1
    # the pod wrote the terminal export: the recovered item is now settled
    assert run_work_remaining(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod_store) is False


def test_C41_consumed_spec_with_an_export_or_a_foreign_run_is_not_redispatched(
    tmp_path,
):
    """F-017 at-least-once boundary: a consumed spec with a terminal export is
    settled, and a spec attributed to another run is never stolen by this run."""
    pod_store = PodMemoryStore(root_dir=tmp_path / "pod", project_id=PROJECT)
    hunter = HunterMemoryStore(tmp_path / "hunter")
    hunter.write_specs(
        PROJECT, DISPATCH_ID,
        [_spec(provenance={"run_id": RUN})], side="consumed")
    pod_store.write_pod_export(SPEC_FILE, RUN, {
        "verdict": "unsuccessful", "terminal_reason": "no-symptom-evidence"})
    assert read_produced_inbox(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod_store).items == ()
    assert run_work_remaining(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod_store) is False

    other = "run-other"
    hunter.write_specs(
        PROJECT, DISPATCH_ID,
        [_spec(fault_keyword="other", strategy_keyword="probe",
               provenance={"run_id": other})], side="consumed")
    inbox = read_produced_inbox(
        PROJECT, RUN, hunter_store=hunter, pod_store=pod_store)
    assert inbox.items == ()


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
            hunt_key=DISPATCH_ID, spec_id=SPEC_FILE,
            inbox=None, hunter_store=hunter, gate=None,
            pod_builder=pod_builder, pod_store=pod_store,
        )

    envelope = asyncio.run(_pod_session())

    # the durable record is keyed by the parent's CANONICAL config_key (the
    # `::`-joined join key), never by the raw `_`-foldered fault_key
    notes = hunter.read_notes(PROJECT, parent_key=DISPATCH_ID)
    assert len(notes) == 1
    record = notes[0]
    assert DISPATCH_ID in record["key"]
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
    state.hunter_inboxes[DISPATCH_ID] = inbox
    hunter_builder, pod_builder = _agent_seam_builders()
    run_id = "run-id-9"

    async def _pod_session():
        # run the pod session AND read the delivered feed on the SAME loop: the
        # live parent inbox must hold the `pod_export` message by the time the
        # session returns/settles
        env = await run_pod_session(
            spec=_spec(), project_id=PROJECT, run_id=run_id,
            hunt_key=DISPATCH_ID, spec_id=SPEC_FILE,
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
    assert received.source == pod_session_id(run_id, DISPATCH_ID, SPEC_FILE)
    # and the durable record is ONE per export: the live-feed consumption (the
    # idle-loop verdict stub) must NOT double-record against the pod-completion note
    notes = hunter.read_notes(PROJECT, parent_key=DISPATCH_ID)
    assert len(notes) == 1


# --- T8 spec review: the store body is projected onto the D4 -------------------

_OK = "<html>market</html>\n__POD_HTTP_STATUS__:200\n__POD_HTTP_TIME__:0.05"


def test_C39_the_real_store_body_reaches_the_real_init_gate_and_authors_a_probe(
    tmp_path,
):
    """T8 spec review (S5 8.4): the hunter store persists `status`,
    `fault_keyword`, and `strategy_keyword` beside the D4 body (S3 8.6), and the
    mover + surfer pass that body on. The dispatch boundary projects the body
    onto the D4, so the REAL store body passes the REAL INIT gate and the REAL
    runner authors the probe; the store file keeps its metadata, and a retired
    field still rejects at the schema/gate seam."""
    from pydantic import ValidationError

    from polymerhus.attack.hunting.pod import arun_pod
    from polymerhus.attack.hunting.pod.agents import symbolic_runner_step_fn
    from polymerhus.attack.hunting.pod.types import TestImplementationSpec
    from polymerhus.attack.hunting.pod.verification import validate_spec
    from polymerhus.recon.domain.types import ExecResult

    threat = ThreatModelStore(tmp_path / "threat")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    pod_store = PodMemoryStore(root_dir=tmp_path / "pod", project_id=PROJECT)
    body = {
        "status": "ratified",
        "fault_keyword": SPEC_KEYWORD,
        "strategy_keyword": STRATEGY,
        "target_identity": {"url": "http://soupmarket.shop/",
                            "unit_id": "service:web:soupmarket"},
        "verification_symptoms": ["HTTP 200 with a non-empty body on GET /"],
        "assumptions": ["network egress allowed"],
        "rationale": "reachability",
        "provenance": {"loop_id": "loop-1",
                       "unit_id": "service:web:soupmarket",
                       "canonical_class": CLASS,
                       "web_vulnerability_class": "idor"},
    }
    hunter.write_specs(PROJECT, DISPATCH_ID, [body], side="produced")

    inbox = read_produced_inbox(PROJECT, RUN, hunter_store=hunter)
    items = [item for item in inbox.items if isinstance(item, TestSpecItem)]
    assert len(items) == 1

    # The store body on disk keeps the lifecycle + identity metadata.
    persisted = hunter.read_spec(PROJECT, DISPATCH_ID, SPEC_FILE)
    assert persisted["status"] == "ratified"
    assert persisted["fault_keyword"] == SPEC_KEYWORD
    assert persisted["strategy_keyword"] == STRATEGY

    seen: dict = {}

    def fake_exec(command, timeout_s):
        seen.setdefault("calls", []).append(command)
        return ExecResult(stdout=_OK, stderr="", returncode=0, duration_ms=1)

    async def pod_builder(spec, *, run_id, project_id, memory_store, spec_id,
                          **kw):
        seen["spec"] = dict(spec)
        return await arun_pod(
            spec, exec_fn=fake_exec, runner_step_fn=symbolic_runner_step_fn,
            triager_fn=None, trace_fn=lambda _run_id: [])

    def hunter_builder(**_kwargs):  # never a hunter dispatch in this seed
        raise AssertionError("no hunter dispatch expected")

    coro_for = build_run_dispatch(
        project_id=PROJECT, run_id=RUN, threat_store=threat,
        hunter_store=hunter, pod_store=pod_store, state=RunDispatchState(),
        gate=None, hunter_builder=hunter_builder, pod_builder=pod_builder,
    )
    envelope = asyncio.run(coro_for(items[0]))

    # The INIT gate passed: the run is a real pod verdict, not a rejection.
    assert envelope["verdict"] == "successful"
    assert envelope["evidence"]["terminal_reason"] == "symptom-confirmed"
    assert not envelope["evidence"].get("init_validation")

    # The pod received the pure D4: the store metadata was projected away.
    received = seen["spec"]
    for metadata in ("status", "fault_keyword", "strategy_keyword"):
        assert metadata not in received
    assert validate_spec(received) == []

    # The runner reached probe authoring: one authored curl of the target URL.
    assert len(seen["calls"]) == 1
    assert body["target_identity"]["url"] in seen["calls"][0]
    assert envelope["evidence"]["raw_observations"]

    # The projection does NOT hide a retired field: the gate/schema still reject.
    retired = {**received, "testing_pattern": "blind-boolean"}
    assert any("testing_pattern" in v for v in validate_spec(retired))
    with pytest.raises(ValidationError):
        TestImplementationSpec.model_validate(retired)
