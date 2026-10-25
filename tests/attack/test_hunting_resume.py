"""T11 (#398): the run-resume trigger.

Two seams:
- the DECISION TABLE as a pure function (`resume_decision`): every row of
  `docs/design/331-stop-only-resume-assessment-adr.md` section 3, including the
  wait window, the fail-closed unknown case, and the process-restart orphan
  disposition;
- the runtime RESUME path: `start_hunting` re-entered with an existing run id
  (no re-freeze, re-entry at `intake_position`, adoption of committed models,
  a halted run resuming dispatch only, and the run's own produced loops
  dispatching while a foreign run's stay produced).

The endpoint's HTTP mapping lives in `tests/project_management/test_hunting_api.py`.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from polymerhus.attack.hunting import runtime as hunting_runtime
from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.mover import hunter_session_id, pod_session_id
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
from polymerhus.attack.hunting.resume import (
    DEFAULT_RESUME_BACKOFF_S,
    resume_decision,
)
from polymerhus.attack.hunting.threat_model_store import ThreatModelStore
from polymerhus.attack.hunting.threat_modeller import UnitOutcome
from polymerhus.attack.hunting.threat_modeller_tools import ModellerTools

from tests.hunting_fixtures import intake_unit, loop_row, produce_model

NOW = datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc)

PROJECT = "resume-project"
RUN = "resume-run-0001"
UNIT_A = "Service:slug:a"
UNIT_B = "GraphQLApi"
UNIT_C = "RESTApi"
FOREIGN_RUN = "foreign-run-0001"
FOREIGN_UNIT = "Service:foreign"
LOOP_A_DISPATCH = "Service-slug-a__loop-1"
LOOP_B_DISPATCH = "GraphQLApi__loop-1"
LOOP_C_DISPATCH = "RESTApi__loop-1"


def test_a_stopped_run_is_resumable_immediately():
    """The decision table: `stopped` -> resumable immediately, regardless of
    stats or finishing time (the operator's own stop is always re-enterable)."""
    decision = resume_decision(
        "stopped", {"interrupted": True}, None, now=NOW)

    assert decision.resumable is True
    assert decision.code == "stopped"
    assert decision.wait_s is None
    assert decision.not_before is None


def test_a_transient_throttle_resumes_once_its_retry_hint_elapsed():
    """The decision table: `quota_exhausted=false` is a transient throttle, and
    it is resumable after `retry_after_s` seconds - here the hint (45s) has
    elapsed, so the decision admits."""
    decision = resume_decision(
        "interrupted",
        {"interrupted": True, "quota_exhausted": False, "retry_after_s": 45.0},
        NOW - timedelta(seconds=45),
        now=NOW,
    )

    assert decision.resumable is True
    assert decision.code == "throttled"
    assert decision.retry_after_s == 45.0
    assert decision.not_before == NOW
    assert decision.wait_s is None


def test_a_transient_throttle_inside_its_retry_window_is_refused_with_a_hint():
    """The decision table's wait window: `finished_at + retry_after_s` is the
    earliest resume; before it the decision refuses and names how long remains.
    The retry hint is the run's own `retry_after_s`, never a re-derived value."""
    decision = resume_decision(
        "interrupted",
        {"interrupted": True, "quota_exhausted": False, "retry_after_s": 45.0},
        NOW - timedelta(seconds=15),
        now=NOW,
    )

    assert decision.resumable is False
    assert decision.code == "backoff_window"
    assert decision.retry_after_s == 45.0
    assert decision.not_before == NOW + timedelta(seconds=30)
    assert decision.wait_s == 30.0
    assert "retry in 30s" in decision.reason


def test_a_null_retry_hint_takes_the_default_backoff():
    """The ADR leaves the null-hint value open: the operator verb applies
    `DEFAULT_RESUME_BACKOFF_S` (60s, one per-minute provider window). A run
    inside that window refuses; one at the boundary admits."""
    stats = {"interrupted": True, "quota_exhausted": False,
             "retry_after_s": None}
    assert DEFAULT_RESUME_BACKOFF_S == 60.0

    inside = resume_decision(
        "interrupted", stats, NOW - timedelta(seconds=59), now=NOW)
    at_boundary = resume_decision(
        "interrupted", stats, NOW - timedelta(seconds=60), now=NOW)

    assert inside.resumable is False
    assert inside.code == "backoff_window"
    assert inside.retry_after_s == DEFAULT_RESUME_BACKOFF_S
    assert inside.wait_s == 1.0
    assert at_boundary.resumable is True
    assert at_boundary.code == "throttled"
    assert at_boundary.retry_after_s == DEFAULT_RESUME_BACKOFF_S


def test_consumed_quota_is_terminal():
    """The decision table: `quota_exhausted=true` is a period/credit
    exhaustion - the provider will not serve until it resets, so the run is
    terminal and is never resumed, no matter how much time has passed."""
    decision = resume_decision(
        "interrupted",
        {"interrupted": True, "quota_exhausted": True, "retry_after_s": 1.0},
        NOW - timedelta(days=30),
        now=NOW,
    )

    assert decision.resumable is False
    assert decision.code == "quota_exhausted"
    assert decision.wait_s is None


def test_an_interrupted_run_without_stats_is_do_not_resume():
    """The decision table's fail-closed row: no `stats` means the class is not
    established, so the run is not resumed. The operator verb does not guess."""
    for stats in (None, {}, {"interrupted": True}):
        decision = resume_decision(
            "interrupted", stats, NOW, now=NOW)
        assert decision.resumable is False
        assert decision.code == "cause_unknown"


def test_an_interrupted_run_with_an_unknown_quota_class_is_do_not_resume():
    """The decision table's `unknown` row: only the JSON boolean `false` is a
    transient throttle. A missing, null, string or numeric stand-in does not
    establish the class, so it fails closed (never a guess)."""
    for value in (None, "false", 0, 1, "true"):
        decision = resume_decision(
            "interrupted",
            {"interrupted": True, "quota_exhausted": value,
             "retry_after_s": 0.0},
            NOW,
            now=NOW,
        )
        assert decision.resumable is False, value
        assert decision.code == "cause_unknown", value


def test_a_process_restart_orphan_is_do_not_resume():
    """The orphaned-run disposition (T11): `reconcile_orphaned_hunting_runs`
    stamps `interrupted` with a restart reason and NO provider stats. The
    decision reads only the stamped attributes, so the orphan fails closed -
    the operator verb never resumes a crash-orphaned row, and the reconcile
    itself never reschedules one."""
    reconcile_stats = {
        "interrupted": True,
        "interrupt_reason": (
            "process ended mid-run: the in-memory orchestration actor did "
            "not survive the restart"
        ),
    }

    decision = resume_decision(
        "interrupted", reconcile_stats, NOW - timedelta(days=1), now=NOW)

    assert decision.resumable is False
    assert decision.code == "cause_unknown"


def test_a_resumed_then_crashed_run_fails_closed_on_the_reconcile_shape():
    """The resume-then-crash disposition (T11 review): a 429 stamps a
    TRANSIENT class (`quota_exhausted=false`, `retry_after_s=45`), the operator
    resumes, and the process then dies. The resume claim CLEARS the provider
    class (pinned live in `test_claim_resumes_a_resumable_row_atomically`), so
    the reconcile's restart stamp carries no class and the table answers
    do-not-resume. Without the clear, the stale `quota_exhausted=false` would
    make the crash-orphaned row resumable - exactly the guess the ADR forbids."""
    transient = {"interrupted": True, "quota_exhausted": False,
                 "retry_after_s": 45.0}
    # the pre-resume class is resumable once its window elapsed ...
    assert resume_decision(
        "interrupted", transient, NOW - timedelta(seconds=45), now=NOW,
    ).resumable is True

    # ... and the crash-orphaned row after the claim's clear carries no class,
    # so it fails closed even though its pre-resume stats once said "resumable"
    reconcile_shape = {
        "interrupted": True,
        "interrupt_reason": (
            "process ended mid-run: the in-memory orchestration actor did "
            "not survive the restart"
        ),
    }
    decision = resume_decision(
        "interrupted", reconcile_shape, NOW - timedelta(days=1), now=NOW)

    assert decision.resumable is False
    assert decision.code == "cause_unknown"


def test_an_interrupted_run_without_finished_at_is_do_not_resume():
    """The wait window is anchored on `finished_at`; a terminal row without one
    has no derivable window, so it fails closed rather than resuming on an
    invented timing."""
    decision = resume_decision(
        "interrupted",
        {"interrupted": True, "quota_exhausted": False, "retry_after_s": 0.0},
        None,
        now=NOW,
    )

    assert decision.resumable is False
    assert decision.code == "timing_unknown"


def test_a_malformed_retry_hint_falls_back_to_the_default_backoff():
    """A negative / non-finite / non-numeric `retry_after_s` is out of contract.
    It falls back to the default backoff - never to zero (`resume now`) - so a
    bad hint can neither hammer the provider nor wedge the run forever."""
    for value in (-5, float("nan"), float("inf"), "45", True):
        decision = resume_decision(
            "interrupted",
            {"interrupted": True, "quota_exhausted": False,
             "retry_after_s": value},
            NOW - timedelta(seconds=30),
            now=NOW,
        )
        assert decision.resumable is False, value
        assert decision.code == "backoff_window", value
        assert decision.retry_after_s == DEFAULT_RESUME_BACKOFF_S, value


def test_a_running_run_is_already_live():
    """The decision table: `running` is the live state - a second run must
    never be booted over it, so the decision refuses."""
    decision = resume_decision("running", {}, None, now=NOW)

    assert decision.resumable is False
    assert decision.code == "already_running"


def test_complete_and_failed_are_terminal():
    """The decision table: `complete` and `failed` are terminal - neither is a
    pause, so neither is resumable."""
    complete = resume_decision("complete", {}, None, now=NOW)
    failed = resume_decision("failed", {}, None, now=NOW)

    assert complete.resumable is False
    assert complete.code == "complete"
    assert failed.resumable is False
    assert failed.code == "failed"


def test_an_unknown_status_fails_closed():
    """The table is total: any status outside the six-value vocabulary is
    undecided, and an undecided status is never resumed."""
    decision = resume_decision("paused", {}, None, now=NOW)

    assert decision.resumable is False
    assert decision.code == "unknown_status"


# --- the runtime resume path: start_hunting re-entered with the run id --------

def _breakdown(**counts: int) -> dict[str, int]:
    levels = {"none": 0, "low": 0, "medium": 0, "high": 0, "critical": 0}
    levels.update(counts)
    return levels


def _record(**overrides) -> dict:
    """A persisted run record (the run row's `stats`) with one modelled unit at
    position 1, overridable per resume case."""
    record = {
        "intake_order": [UNIT_A, UNIT_B],
        "intake_position": 1,
        "intake_excluded": [],
        "risk_threshold": 250,
        "threshold_basis": "default",
        "risk_weights": {"none": 0, "low": 1, "medium": 2, "high": 3,
                         "critical": 4},
        "risk_total": 1,
        "risk_breakdown": _breakdown(low=1),
        "model_sums": [{"unit_id": UNIT_A, "total": 1,
                        "breakdown": _breakdown(low=1)}],
        "crossing_unit": None,
        "blocked_unit": None,
        "halt": False,
        "degraded_units": [],
        "trajectory": [],
    }
    record.update(overrides)
    return record


class _ResumePg:
    """The fake pg accessors at the resume seam: the run row carries the record
    and the claimed `running` status. A resume never mints a new row.
    `producer_rows` are the OTHER hunting runs the intake freeze reads (the
    produced models' producing runs)."""

    def __init__(self, record: dict, *, status: str = "running",
                 run_id: str = RUN, producer_rows: tuple[dict, ...] = ()):
        self.record = dict(record)
        self.status = status
        self.run_id = run_id
        self.producer_rows = tuple(producer_rows)
        self.status_writes: list[tuple[str, str]] = []

    def create_hunting_run(self, project_id: str) -> str:
        raise AssertionError("a resume must never mint a new hunting run row")

    def get_hunting_run(self, hunting_run_id: str) -> dict | None:
        if hunting_run_id != self.run_id:
            return None
        return {
            "hunting_run_id": hunting_run_id,
            "project_id": PROJECT,
            "status": self.status,
            "started_at": None,
            "finished_at": None,
            "stats": dict(self.record),
        }

    def set_hunting_run_status(self, hunting_run_id: str, status: str, *,
                               stats: dict | None = None) -> None:
        self.status = status
        self.status_writes.append((hunting_run_id, status))
        if stats:
            self.record.update(stats)

    def set_hunting_run_stats(self, hunting_run_id: str, stats: dict) -> None:
        self.record.update(stats or {})

    def list_hunting_runs(self, project_id: str) -> list[dict]:
        rows = [self.get_hunting_run(self.run_id)]
        rows.extend(dict(row) for row in self.producer_rows)
        return [row for row in rows if row is not None]


class _ResumeControl:
    """The session-capable control-plane fake: runs the started sessions as
    tasks on the current loop and mirrors the registry through the live-task
    set. `live_extra` is a callable supplying PRE-REGISTERED live sessions (a
    crash-window session the resumed run must adopt, not re-dispatch)."""

    def __init__(self, *, live_extra=None):
        self._live_extra = live_extra
        self._tasks: dict[str, asyncio.Task] = {}
        self.started: list[str] = []

    def live_session_ids(self):
        live = {sid for sid, task in self._tasks.items() if not task.done()}
        if self._live_extra is not None:
            live |= set(self._live_extra())
        return live

    def start_session(self, session_id, coro):
        self.started.append(session_id)
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks[session_id] = task
        return task

    def dispatch(self, session_id, coro):
        return self.start_session(session_id, coro) is not None

    def cancel_session(self, session_id):
        task = self._tasks.get(session_id)
        if task is not None and not task.done():
            task.cancel()


async def _noop_pod_builder(spec, **kw):
    return {"verdict": "successful", "terminal_reason": "symptom-confirmed",
            "evidence": {"trail": []}, "clean": True, "iterations": 0}


def _noop_hunter_builder(*, run_id, project_id, hunter_store, **kw):
    """Conclude the fake hunt AND write its zero-spec terminal set (F-022)."""
    async def dispatch(payload):
        hunt_key = payload.get("dispatch_id")
        if hunt_key:
            hunter_store.finalize_specs(project_id, hunt_key, run_id=run_id)
        return None

    return dispatch, None


def _recording_hunter_builder(dispatched: list):
    def build(*, run_id, project_id, hunter_store, **kw):
        async def dispatch(payload):
            dispatched.append(payload["dispatch_id"])
            if payload.get("dispatch_id"):
                hunter_store.finalize_specs(
                    project_id, payload["dispatch_id"], run_id=run_id)
            return None

        return dispatch, None

    return build


def _recording_pass(seen: list):
    async def run(project_id, run_id, unit_id, tools, **kwargs):
        seen.append(unit_id)
        return UnitOutcome(unit_id=unit_id, status="completed")

    return run


def _patch_pg(monkeypatch, fake: _ResumePg) -> None:
    monkeypatch.setattr(
        "polymerhus.app.clients.pg.create_hunting_run", fake.create_hunting_run)
    monkeypatch.setattr(
        "polymerhus.app.clients.pg.set_hunting_run_status",
        fake.set_hunting_run_status)
    monkeypatch.setattr(
        "polymerhus.app.clients.pg.set_hunting_run_stats",
        fake.set_hunting_run_stats)
    monkeypatch.setattr(
        "polymerhus.app.clients.pg.get_hunting_run", fake.get_hunting_run)
    monkeypatch.setattr(
        "polymerhus.app.clients.pg.list_hunting_runs", fake.list_hunting_runs)


def _resume_run(tmp_path, monkeypatch, *, record, threat, hunter, seen,
                dispatched=None, control=None):
    fake = _ResumePg(record)
    _patch_pg(monkeypatch, fake)
    tools = ModellerTools(threat_store=threat, project_id=PROJECT, run_id=RUN)
    asyncio.run(hunting_runtime.start_hunting(
        PROJECT,
        run_id=RUN,
        intake_units=[intake_unit(UNIT_C)],
        tools=tools,
        control=control or _ResumeControl(),
        tick_interval=0.01,
        hunter_store=hunter,
        pod_store=PodMemoryStore(root_dir=tmp_path / "pod"),
        hunter_builder=(
            _recording_hunter_builder(dispatched)
            if dispatched is not None else _noop_hunter_builder
        ),
        pod_builder=_noop_pod_builder,
        modeller_pass_fn=_recording_pass(seen),
    ))
    return fake


def test_a_resumed_run_reenters_at_the_recorded_position_and_never_refreezes(
        tmp_path, monkeypatch):
    """T11 AC: the resumed run re-enters at `intake_position` and adopts the
    recorded intake - it never re-freezes or re-sorts it. The already-modelled
    unit is never re-modelled, and an injected `intake_units` snapshot is
    IGNORED on the resume path."""
    threat = ThreatModelStore(root_dir=tmp_path / "models")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    seen: list[str] = []

    fake = _resume_run(
        tmp_path, monkeypatch, record=_record(), threat=threat, hunter=hunter,
        seen=seen)

    assert seen == [UNIT_B]  # position 1 onward only; UNIT_A and UNIT_C skipped
    assert fake.record["intake_order"] == [UNIT_A, UNIT_B]
    assert fake.record["intake_position"] == 2
    assert fake.status == "complete"


def test_a_resumed_run_adopts_the_committed_models_and_recomputes_risk_total(
        tmp_path, monkeypatch):
    """S1 7.5: the model document commits before the run-record update, so the
    resume ADOPTS every complete model at/after `intake_position` and
    recomputes `risk_total` from the recorded sums plus the adopted model - the
    run never models the unit again and its total can never be stale."""
    threat = ThreatModelStore(root_dir=tmp_path / "models")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    produce_model(threat, project_id=PROJECT, unit_id=UNIT_B, run_id=RUN,
                  loops=[loop_row(likelihood="high")])
    seen: list[str] = []
    dispatched: list[str] = []

    fake = _resume_run(
        tmp_path, monkeypatch, record=_record(intake_position=1),
        threat=threat, hunter=hunter, seen=seen, dispatched=dispatched)

    assert seen == []  # the complete model is adopted, never re-modelled
    assert fake.record["intake_position"] == 2
    assert fake.record["risk_total"] == 4  # A: 1 (low) + B: 3 (high, adopted)
    assert [entry["unit_id"] for entry in fake.record["model_sums"]] == [
        UNIT_A, UNIT_B]
    assert dispatched == [LOOP_B_DISPATCH]  # the adopted unit's loop dispatches


def test_a_halted_run_resumes_dispatch_only(tmp_path, monkeypatch):
    """S1 7.5: a halted run resumes dispatch only - it models nothing more,
    keeps its halt audit trail, and its produced loop file dispatches."""
    threat = ThreatModelStore(root_dir=tmp_path / "models")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    produce_model(threat, project_id=PROJECT, unit_id=UNIT_C, run_id=RUN,
                  loops=[loop_row(likelihood="high")])
    seen: list[str] = []
    dispatched: list[str] = []

    fake = _resume_run(
        tmp_path, monkeypatch,
        record=_record(halt=True, crossing_unit=UNIT_A, blocked_unit=UNIT_B),
        threat=threat, hunter=hunter, seen=seen, dispatched=dispatched)

    assert seen == []  # the halted run never models another unit
    assert dispatched == [LOOP_C_DISPATCH]  # ... it only resumes dispatch
    assert threat.read_produced_loops(PROJECT) == []  # the loop was consumed
    assert fake.record["halt"] is True
    assert fake.record["intake_position"] == 1
    assert fake.status == "complete"


def test_only_the_resumed_runs_produced_loops_dispatch(tmp_path, monkeypatch):
    """The surfer is run-scoped: the resumed run's own produced loop file
    dispatches and moves, while a FOREIGN run's produced loop file stays
    produced for its own run's surfer."""
    threat = ThreatModelStore(root_dir=tmp_path / "models")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    produce_model(threat, project_id=PROJECT, unit_id=UNIT_A, run_id=RUN,
                  loops=[loop_row(likelihood="high")])
    produce_model(threat, project_id=PROJECT, unit_id=FOREIGN_UNIT,
                  run_id=FOREIGN_RUN, loops=[loop_row(likelihood="high")])
    seen: list[str] = []
    dispatched: list[str] = []

    _resume_run(
        tmp_path, monkeypatch,
        record=_record(halt=True, crossing_unit=UNIT_A, blocked_unit=UNIT_B),
        threat=threat, hunter=hunter, seen=seen, dispatched=dispatched)

    assert dispatched == [LOOP_A_DISPATCH]
    remaining = threat.read_produced_loops(PROJECT)
    assert [entry["run_id"] for entry in remaining] == [FOREIGN_RUN]


def test_a_resumed_run_never_redispatches_a_live_loop(tmp_path, monkeypatch):
    """Idempotency: a produced loop whose hunter session is ALREADY LIVE is
    adopted (the produced->consumed marker lands), never dispatched a second
    time - the crash window after admission cannot double-run a hunter."""
    threat = ThreatModelStore(root_dir=tmp_path / "models")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    produce_model(threat, project_id=PROJECT, unit_id=UNIT_A, run_id=RUN,
                  loops=[loop_row(likelihood="high")])
    session_id = hunter_session_id(RUN, LOOP_A_DISPATCH)

    def _live_while_adopting():
        # The pre-registered session is live until the move lands; after the
        # admission, it completes like a real hunter and writes its zero-spec
        # terminal set (F-022). It reports live for the tick that writes the
        # marker, then settles: the consumed loop was already read as recovered
        # in that tick, so it must never be re-dispatched.
        if threat.read_produced_loops(PROJECT):
            return {session_id}
        if hunter.read_terminal_set(PROJECT, LOOP_A_DISPATCH) is None:
            hunter.finalize_specs(PROJECT, LOOP_A_DISPATCH, run_id=RUN)
            return {session_id}
        return set()

    control = _ResumeControl(live_extra=_live_while_adopting)
    seen: list[str] = []
    dispatched: list[str] = []

    _resume_run(
        tmp_path, monkeypatch,
        record=_record(halt=True, crossing_unit=UNIT_A, blocked_unit=UNIT_B),
        threat=threat, hunter=hunter, seen=seen, dispatched=dispatched,
        control=control)

    assert dispatched == []  # never a second hunter for a live dispatch
    assert session_id not in control.started  # the live session is never re-run
    assert threat.read_produced_loops(PROJECT) == []  # the move completed


def test_a_resumed_run_never_redispatches_a_live_pod(tmp_path, monkeypatch):
    """Idempotency: a produced ratified spec whose pod session is ALREADY LIVE
    is adopted (moved to consumed), never dispatched a second time."""
    threat = ThreatModelStore(root_dir=tmp_path / "models")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    spec = {
        "status": "hypothesised",
        "discriminators": [
            {"axis": "fault", "value": "sqli"},
            {"axis": "technique", "value": "blind"},
        ],
        "provenance": {"web_vulnerability_class": "sqli"},
        "verification_symptoms": ["a foreign item renders"],
    }
    hunter.write_specs(PROJECT, LOOP_A_DISPATCH, [spec])
    hunter.write_specs(
        PROJECT, LOOP_A_DISPATCH, [{**spec, "status": "ratified"}])
    session_id = pod_session_id(RUN, LOOP_A_DISPATCH, "sqli__blind__boolean")
    control = _ResumeControl(live_extra=lambda: (
        {session_id}
        if hunter.produced_spec_files(PROJECT, LOOP_A_DISPATCH) else set()))
    seen: list[str] = []

    _resume_run(
        tmp_path, monkeypatch,
        record=_record(halt=True, crossing_unit=UNIT_A, blocked_unit=UNIT_B),
        threat=threat, hunter=hunter, seen=seen, control=control)

    assert hunter.produced_spec_files(PROJECT, LOOP_A_DISPATCH) == []
    assert session_id not in control.started  # the live pod is never re-run


# --- the intake freeze consumes the resume decision (T11 review) --------------

def test_the_intake_freeze_consumes_the_resume_decision(tmp_path, monkeypatch):
    """T11 review integration: the freeze reads each `interrupted` producer's
    resume decision. A terminal producer (quota exhausted) will never resume, so
    its produced model is stale: it is archived to `abandoned/` and the unit is
    retried. A resumable throttle keeps its model in flight - including one still
    inside its backoff window, which is NOT terminal."""
    threat = ThreatModelStore(root_dir=tmp_path / "models")
    hunter = HunterMemoryStore(tmp_path / "hunter")
    produce_model(threat, project_id=PROJECT, unit_id=UNIT_A,
                  run_id="quota-producer", loops=[loop_row(likelihood="high")])
    produce_model(threat, project_id=PROJECT, unit_id=UNIT_B,
                  run_id="throttled-producer",
                  loops=[loop_row(likelihood="high")])
    produce_model(threat, project_id=PROJECT, unit_id=UNIT_C,
                  run_id="backoff-producer", loops=[loop_row(likelihood="high")])
    now = datetime.now(timezone.utc)
    fake = _ResumePg(
        {}, run_id="freeze-launch-run",
        producer_rows=(
            {"hunting_run_id": "quota-producer", "project_id": PROJECT,
             "status": "interrupted", "finished_at": now,
             "stats": {"interrupted": True, "quota_exhausted": True}},
            {"hunting_run_id": "throttled-producer", "project_id": PROJECT,
             "status": "interrupted",
             "finished_at": now - timedelta(seconds=5),
             "stats": {"interrupted": True, "quota_exhausted": False,
                       "retry_after_s": 0.0}},
            {"hunting_run_id": "backoff-producer", "project_id": PROJECT,
             "status": "interrupted", "finished_at": now,
             "stats": {"interrupted": True, "quota_exhausted": False,
                       "retry_after_s": 3600.0}},
        ))
    _patch_pg(monkeypatch, fake)
    seen: list[str] = []

    asyncio.run(hunting_runtime.start_hunting(
        PROJECT,
        run_id="freeze-launch-run",
        intake_units=[intake_unit(UNIT_A), intake_unit(UNIT_B),
                      intake_unit(UNIT_C)],
        tools=ModellerTools(threat_store=threat, project_id=PROJECT,
                            run_id="freeze-launch-run"),
        control=_ResumeControl(),
        tick_interval=0.01,
        hunter_store=hunter,
        pod_store=PodMemoryStore(root_dir=tmp_path / "pod"),
        hunter_builder=_noop_hunter_builder,
        pod_builder=_noop_pod_builder,
        modeller_pass_fn=_recording_pass(seen),
    ))

    # the quota-exhausted producer's stale model was archived and its unit
    # retried; both resumable throttles kept their models in flight
    assert seen == [UNIT_A]
    assert fake.record["intake_order"] == [UNIT_A]
    assert [(entry["unit_id"], entry["reason"])
            for entry in fake.record["intake_excluded"]] == [
        (UNIT_B, "in-flight"), (UNIT_C, "in-flight")]
    assert [entry["unit_id"] for entry in threat.read_produced_units(PROJECT)] == [
        UNIT_B, UNIT_C]
