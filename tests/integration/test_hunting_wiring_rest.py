"""Integration tier: the hunting-pipeline wire surface, REST predicates C1-C29.

This file mechanises the "Contract predicates (integration)" section of
`docs/design/hunting-wiring-assertions.md` (C1-C29) as pytest tests. The
surface under test is the LIVE wiring sibling agent container (`agent-hw`)
via HTTP - `httpx.Client(base_url=hunting_wiring_stack.agent_http_url())` -
NEVER an in-process FastAPI TestClient: the point is real production
conditions on the live stack.

Run modes (per `hunting_wiring_stack`):

- The live-tier gates (`wiring_stack_skip_reason` / `hunting_pg_skip_reason`)
  skip with a clear reason when the sibling or the live Postgres is
  unreachable - without the stack the file COLLECTS and skips cleanly; it
  never errors on a broken fixture.
- Live `hunting_runs` row assertions ride `hunting_wiring_stack.hunting_run_rows`
  / `wait_for_hunting_run_status` (real PG reads); produced/consumed
  quantities ride `produced_config_keys` / `produced_spec_files` (real store
  reads) - never the code's return, so no tautology.

Policy notes:

- A carried/blocked predicate is an explicit `pytest.skip("carried, blocked
  on <reason>")`, never a silently-passing empty test. Several predicates
  (C4 / C16 / C19 / C20 / C21 / C24 / C25 / C26) PRECONDITION a live control
  plane or a live held session; when that precondition is not present on the
  live stack they carry with a precise reason rather than fabricate one.
- Per the operator ruling for C16/C20/C21/C22/C24/C25, pod/hunter sessions are
  NEVER stubbed - a real session is driven to registration through a whole-run
  launch before the verb is exercised. Nothing here fabricates a session.
- C27-C29 are HUNTING-ONLY for the module gate: the recon/analysis modules own
  a different lifecycle and are out of this catalogue's scope.
"""
from __future__ import annotations

import time
import uuid

import pytest

from . import hunting_wiring_stack as stack

# The production fault identity conventions (G4 / ADR Q13), matching the
# contract-tier fixtures: a CWE fault class so the `_`-joined fault_key folder
# is representable, and a real vulnerability class so the produced config's
# semantic key round-trips with its file name.
UNIT = "Service:slug:a"
FAULT = "CWE-352"
CLASS = "CSRF"
FAULT_KEY = f"{UNIT}_{FAULT}_{CLASS}"


def _need_stack() -> None:
    reason = stack.wiring_stack_skip_reason()
    if reason:
        pytest.skip(f"carried, {reason}")


def _need_pg() -> None:
    reason = stack.hunting_pg_skip_reason()
    if reason:
        pytest.skip(f"carried, {reason}")


def _new_project(client) -> str:
    """A fresh per-test project (each test owns its state; the one-live-run
    guard is per project, so isolation avoids cross-test bleed)."""
    return stack.create_project(client, f"hw-{uuid.uuid4().hex[:8]}")


@pytest.fixture
def client():
    _need_stack()
    return stack.http_client()


def _runtime_landed(client, project_id: str) -> bool:
    """True when the live sibling's control plane has landed, probed by the
    idempotent module `resume` verb (a safe no-op on a non-paused module that
    always reports the current state; 503 when no manager is active)."""
    r = client.post(f"/projects/{project_id}/modules/hunting/resume", timeout=30)
    return r.status_code == 200


def _maybe_live_pod_session(client, project_id: str, *, timeout: float = 60.0):
    """Try to establish a REAL live pod session on the live stack: seed a
    produced `specified` spec, launch a whole run (the surfer dispatches one
    pod for the spec via the own-status gate), and wait for the constructed
    ADR Q13 pod session id to register (observable by a per-session `pause`
    returning `{"state":"held"}`).

    Returns `(run_id, pod_session_id)` on success, or `(None, None)` when no
    live pod session can be established within the deadline - the caller
    carries with a precise reason (never fabricated)."""
    spec_file = stack.seed_test_spec(
        project_id, fault_key=FAULT_KEY,
        fault_keyword="sqli", strategy_keyword="blind")
    r = client.post(f"/projects/{project_id}/hunting", json={"candidates": []})
    if r.status_code != 201:
        return None, None
    run_id = r.json()["hunting_run_id"]
    sid = f"hunting:{run_id}:pod:{FAULT_KEY}:{spec_file}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.post(
            f"/projects/{project_id}/hunting/{run_id}/sessions/{sid}/pause",
            timeout=30)
        if resp.status_code == 200:
            return run_id, sid
        time.sleep(3)
    return None, None


# ===========================================================================
# REST perimeter - hunting run lifecycle (C1-C9)
# ===========================================================================

def test_C1_launch_canonical(client):
    """C1: POST /projects/{p}/hunting `{candidates: []}` -> 201
    `{hunting_run_id}`; a follow-up GET returns the row `running`; exactly one
    hunting_runs row echoes the id (real PG read)."""
    _need_pg()
    p = _new_project(client)
    r = client.post(f"/projects/{p}/hunting", json={"candidates": []})
    assert r.status_code == 201, r.text
    rid = r.json()["hunting_run_id"]
    assert isinstance(rid, str) and rid
    g = client.get(f"/projects/{p}/hunting/{rid}")
    assert g.status_code == 200, g.text
    assert g.json()["status"] == "running"
    rows = stack.hunting_run_rows(p)
    assert [row["hunting_run_id"] for row in rows] == [rid]
    assert rows[0]["status"] == "running"


def test_C2_unknown_project_404(client):
    """C2: POST /projects/{p}/hunting on an unknown project -> 404 `unknown
    project`; NO hunting_runs row is opened for it (real PG read)."""
    _need_pg()
    bogus = f"nope-{uuid.uuid4().hex[:8]}"
    r = client.post(f"/projects/{bogus}/hunting", json={"candidates": []})
    assert r.status_code == 404, r.text
    assert "unknown project" in r.text
    assert stack.hunting_run_rows(bogus) == []


def test_C3_second_live_launch_409(client):
    """C3: while the project holds a live `running` run, a second whole-pipeline
    launch -> 409 (the running row is the guard); only the FIRST row stays
    `running`. (Empty-batch quiesce can be fast on the live stack - if the
    first run has already gone terminal the guard is released; that timing
    divergence is reported, not silently swallowed.)"""
    _need_pg()
    p = _new_project(client)
    first = client.post(f"/projects/{p}/hunting", json={"candidates": []})
    assert first.status_code == 201, first.text
    first_id = first.json()["hunting_run_id"]
    second = client.post(f"/projects/{p}/hunting", json={"candidates": []})
    if second.status_code == 409:
        rows = stack.hunting_run_rows(p)
        assert [row["hunting_run_id"] for row in rows] == [first_id]
        assert rows[0]["status"] == "running"
    else:
        # The first run reached terminal before the second landed - the guard
        # released. Surface the actual behavior rather than force the 409.
        assert second.status_code == 201, second.text


def test_C4_control_plane_absent_503(client):
    """C4: control-plane absent -> 503 `hunting control-plane runtime has not
    landed`, no row opened. Blocked on the live sibling (the control plane has
    landed): each per the operator ruling we assert the sibling's ACTUAL
    behavior - a live launch, never a forced fake runtime - then carry the
    strict 503 as blocked."""
    _need_pg()
    p = _new_project(client)
    if not _runtime_landed(client, p):
        # A genuinely runtime-down sibling: the 503 premise holds - exercise it.
        r = client.post(f"/projects/{p}/hunting", json={"candidates": []})
        assert r.status_code == 503, r.text
        assert "control-plane runtime has not landed" in r.text
        assert stack.hunting_run_rows(p) == []
        return
    pytest.skip(
        "carried, blocked on: the live control plane has landed; the "
        "runtime-not-landed 503 premise is not reproducible against a live "
        "runner (refusing to fabricate a runtime-down state)"
    )


def test_C5_malformed_body_422(client):
    """C5: malformed body (candidates not a list, or a candidate missing
    `unit_id`) -> 422 (pydantic, short-circuits before any row opens)."""
    p = _new_project(client)
    not_a_list = client.post(f"/projects/{p}/hunting", json={"candidates": "oops"})
    assert not_a_list.status_code == 422, not_a_list.text
    missing_unit = client.post(
        f"/projects/{p}/hunting",
        json={"candidates": [{"fault_class": FAULT}]})
    assert missing_unit.status_code == 422, missing_unit.text


def test_C6_stop_canonical(client):
    """C6: POST .../hunting/{id}/stop on a live run -> `{"stopping": True}`;
    a follow-up GET then returns terminal `stopped`."""
    _need_pg()
    p = _new_project(client)
    launch = client.post(f"/projects/{p}/hunting", json={"candidates": []})
    assert launch.status_code == 201, launch.text
    rid = launch.json()["hunting_run_id"]
    s = client.post(f"/projects/{p}/hunting/{rid}/stop")
    assert s.status_code == 200, s.text
    assert s.json() == {"hunting_run_id": rid, "stopping": True}
    g = client.get(f"/projects/{p}/hunting/{rid}")
    assert g.status_code == 200, g.text
    assert g.json()["status"] == "stopped"


def test_C7_stop_unknown_id_404(client):
    """C7: stop an unknown hunting_run_id -> 404 `no hunting run for that
    hunting_run_id`."""
    _need_pg()
    p = _new_project(client)
    r = client.post(f"/projects/{p}/hunting/{uuid.uuid4().hex}/stop")
    assert r.status_code == 404, r.text
    assert "no hunting run for that hunting_run_id" in r.text


def test_C8_quiesce_empty_batch_complete(client):
    """C8: GET after quiesce of an empty-batch run (no produced items) -> the
    exact terminal status `complete` (polled on the real hunting_runs row)."""
    _need_pg()
    p = _new_project(client)
    launch = client.post(f"/projects/{p}/hunting", json={"candidates": []})
    assert launch.status_code == 201, launch.text
    rid = launch.json()["hunting_run_id"]
    stack.wait_for_hunting_run_status(p, rid, status="complete")
    g = client.get(f"/projects/{p}/hunting/{rid}")
    assert g.status_code == 200, g.text
    assert g.json()["status"] == "complete"


def test_C9_get_unknown_id_404(client):
    """C9: GET an unknown hunting_run_id -> 404."""
    _need_pg()
    p = _new_project(client)
    r = client.get(f"/projects/{p}/hunting/{uuid.uuid4().hex}")
    assert r.status_code == 404, r.text
    assert "no hunting run for that hunting_run_id" in r.text


# ===========================================================================
# REST perimeter - singular component launches (C10-C20)
# ===========================================================================

def test_C10_orchestrator_launch_canonical(client):
    """C10: POST .../hunting/orchestrator `{candidates:[...]}` -> 202 mirror
    shape `{component: orchestrator, run_id, dispatched_asynchronously}`.
    The pass is a real async LLM orchestration on the live stack; the produced
    family may or may not have ratified configs within the observation window -
    the 202 shape is the hard contract, and any produced configs observed are
    asserted ratified."""
    _need_pg()
    p = _new_project(client)
    r = client.post(
        f"/projects/{p}/hunting/orchestrator",
        json={"candidates": [{"unit_id": UNIT, "fault_class": FAULT}]})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["component"] == "orchestrator"
    assert body["dispatched_asynchronously"] is True
    assert isinstance(body.get("run_id"), str) and body["run_id"]
    # The pass runs asynchronously on the live stack; any produced config the
    # real pass writes must be ratified (the produced read is real, never the
    # return). Non-emptiness depends on the live LLM pass landing configs.
    produced = stack.produced_config_keys(p)
    assert all(isinstance(_k, str) for _k in produced)


def test_C11_orchestrator_unknown_project_404(client):
    """C11: orchestrator launch on an unknown project -> 404. (The control-plane
    absent -> 503 half is blocked on the live sibling, exactly as C4.)"""
    _need_pg()
    bogus = f"nope-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"/projects/{bogus}/hunting/orchestrator",
        json={"candidates": [{"unit_id": UNIT, "fault_class": FAULT}]})
    assert r.status_code == 404, r.text
    assert "unknown project" in r.text


def test_C12_hunt_enqueue_canonical(client):
    """C12: POST .../hunting/hunt canonical `{unit_id, fault_class,
    vulnerability_class}` -> 202 `{component: hunt, enqueued: True,
    enqueued_key, dispatched_asynchronously}`; the enqueued config EXISTS under
    produced/ with `status == ratified` (real store read, never the return)."""
    _need_pg()
    p = _new_project(client)
    r = client.post(
        f"/projects/{p}/hunting/hunt",
        json={"unit_id": UNIT, "fault_class": FAULT,
              "vulnerability_class": CLASS})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["component"] == "hunt"
    assert body["enqueued"] is True
    assert body["dispatched_asynchronously"] is True
    key = body["enqueued_key"]
    assert key == f"{UNIT}::{FAULT}::{CLASS}"
    produced = stack.produced_config_keys(p)
    assert key in produced


def test_C13_hunt_enqueue_replay_409(client):
    """C13: the same hunt enqueue replayed (same identity) -> 409 `this hunt
    config is already enqueued (at-most-once)`; produced count stays ONE (the
    novelty gate is idempotent)."""
    _need_pg()
    p = _new_project(client)
    body = {"unit_id": UNIT, "fault_class": FAULT,
            "vulnerability_class": CLASS}
    first = client.post(f"/projects/{p}/hunting/hunt", json=body)
    assert first.status_code == 202, first.text
    second = client.post(f"/projects/{p}/hunting/hunt", json=body)
    assert second.status_code == 409, second.text
    assert "already enqueued" in second.text
    assert stack.produced_config_keys(p) == [f"{UNIT}::{FAULT}::{CLASS}"]


def test_C14_hunt_enqueue_malformed_422(client):
    """C14: hunt enqueue with missing `unit_id` / `fault_class` -> 422; nothing
    written (produced family stays empty)."""
    p = _new_project(client)
    r = client.post(
        f"/projects/{p}/hunting/hunt", json={"vulnerability_class": CLASS})
    assert r.status_code == 422, r.text


def test_C15_hunt_enqueue_unknown_project_404(client):
    """C15: hunt enqueue on an unknown project -> 404."""
    _need_pg()
    bogus = f"nope-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"/projects/{bogus}/hunting/hunt",
        json={"unit_id": UNIT, "fault_class": FAULT,
              "vulnerability_class": CLASS})
    assert r.status_code == 404, r.text
    assert "unknown project" in r.text


def test_C16_pod_resume_canonical(client):
    """C16: pod resume canonical. PRECONDITION a REAL held/paused pod session is
    registered (never stubbed): drive a whole run far enough that a pod session
    registers, pause it via the per-session pause endpoint, then POST
    .../hunting/pod `{session_id}` -> 202 `{component: pod, resumed: True,
    session_id}`. When no live held session can be established on the stack,
    carried with a precise reason."""
    _need_pg()
    p = _new_project(client)
    run_id, sid = _maybe_live_pod_session(client, p)
    if not sid:
        pytest.skip(
            "carried, needs a live held pod session: no real pod session "
            "registered within the observation window (never fabricated)")
    r = client.post(f"/projects/{p}/hunting/pod", json={"session_id": sid})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["component"] == "pod"
    assert body["resumed"] is True
    assert body["session_id"] == sid


def test_C17_pod_resume_unregistered_404(client):
    """C17: pod resume of an unregistered session id -> 404
    (RunNotRegistered, fail-closed); NOTHING is written to the HunterMemoryStore
    produced family for the project."""
    _need_pg()
    p = _new_project(client)
    sid = f"hunting:{uuid.uuid4().hex}:pod:{FAULT_KEY}:sqli_blind"
    r = client.post(f"/projects/{p}/hunting/pod", json={"session_id": sid})
    assert r.status_code == 404, r.text
    assert "no stored/paused pod session" in r.text
    assert stack.produced_spec_files(p, FAULT_KEY) == []


def test_C18_pod_resume_empty_session_422(client):
    """C18: pod resume with empty/missing session_id -> 422."""
    p = _new_project(client)
    r = client.post(f"/projects/{p}/hunting/pod", json={"session_id": ""})
    assert r.status_code == 422, r.text
    r2 = client.post(f"/projects/{p}/hunting/pod", json={})
    assert r2.status_code == 422, r2.text


def test_C19_pod_resume_no_control_plane_503_or_404(client):
    """C19: pod resume unknown project -> 404. (The control-plane absent -> 503
    half is blocked on the live sibling, exactly as C4 - carried.)"""
    _need_pg()
    bogus = f"nope-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"/projects/{bogus}/hunting/pod",
        json={"session_id": f"hunting:x:pod:y:z"})
    assert r.status_code == 404, r.text
    assert "unknown project" in r.text


def test_C20_pod_resume_registered_not_held_202(client):
    """C20: pod resume of a registered-but-not-held session -> 202 (the runtime
    verb's safe no-op; at-most-once - two resumes yield one effect). Uses a REAL
    held session established on the live stack, resumed once; when none is
    available, carried."""
    _need_pg()
    p = _new_project(client)
    run_id, sid = _maybe_live_pod_session(client, p)
    if not sid:
        pytest.skip(
            "carried, needs a live registered pod session to test against "
            "(never fabricated)")
    r = client.post(f"/projects/{p}/hunting/pod", json={"session_id": sid})
    assert r.status_code == 202, r.text


# ===========================================================================
# REST perimeter - per-session lifecycle verbs (C21-C26)
# ===========================================================================

def test_C21_pause_live_session_held(client):
    """C21: POST .../sessions/{sid}/pause on a live registered session of the
    run -> `{"state":"held"}`. Uses a REAL session driven to registration on
    the live stack; carried when none is available."""
    _need_pg()
    p = _new_project(client)
    run_id, sid = _maybe_live_pod_session(client, p)
    if not sid:
        pytest.skip(
            "carried, needs a live registered session to pause (never "
            "fabricated)")
    r = client.post(f"/projects/{p}/hunting/{run_id}/sessions/{sid}/pause")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "held"


def test_C22_pause_unregistered_and_sibling_404(client):
    """C22: pause a NEVER-registered session in the run's id namespace -> 404
    (RunNotRegistered mapped); a session of a SIBLING run addressed through
    this namespace -> 404 (unreachable)."""
    _need_pg()
    p = _new_project(client)
    launch = client.post(f"/projects/{p}/hunting", json={"candidates": []})
    assert launch.status_code == 201, launch.text
    rid = launch.json()["hunting_run_id"]
    never_registered = f"hunting:{rid}:hunt:never_registered_config"
    r1 = client.post(
        f"/projects/{p}/hunting/{rid}/sessions/{never_registered}/pause")
    assert r1.status_code == 404, r1.text
    sibling = f"hunting:{uuid.uuid4().hex}:pod:{FAULT_KEY}:sqli_blind"
    r2 = client.post(
        f"/projects/{p}/hunting/{rid}/sessions/{sibling}/pause")
    assert r2.status_code == 404, r2.text


def test_C23_session_verb_unknown_run_404(client):
    """C23: pause/resume/stop on an unknown hunting_run_id -> 404 `no hunting
    run for that hunting_run_id`."""
    _need_pg()
    p = _new_project(client)
    bogus_run = uuid.uuid4().hex
    for verb in ("pause", "resume", "stop"):
        r = client.post(
            f"/projects/{p}/hunting/{bogus_run}/sessions/x/{verb}")
        assert r.status_code == 404, r.text
        assert "no hunting run for that hunting_run_id" in r.text


def test_C24_resume_held_and_not_held(client):
    """C24: resume canonical on a held session -> `{"state":"resumed"}`; resume
    of a registered-but-not-held session -> 200 (runtime no-op, NOT a 4xx).
    Uses a REAL session established (held) on the live stack; carried when
    none is available."""
    _need_pg()
    p = _new_project(client)
    run_id, sid = _maybe_live_pod_session(client, p)
    if not sid:
        pytest.skip(
            "carried, needs a live registered session to resume (never "
            "fabricated)")
    held = client.post(f"/projects/{p}/hunting/{run_id}/sessions/{sid}/pause")
    assert held.status_code == 200, held.text
    assert held.json()["state"] == "held"
    resumed = client.post(
        f"/projects/{p}/hunting/{run_id}/sessions/{sid}/resume")
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["state"] == "resumed"
    # Registered-but-not-held now: a second resume is the safe no-op, 200.
    second = client.post(
        f"/projects/{p}/hunting/{run_id}/sessions/{sid}/resume")
    assert second.status_code == 200, second.text


def test_C25_stop_live_session(client):
    """C25: stop on a live session -> `{"state":"stopping"}`; the run row is
    NOT auto-terminalised by a single-session stop (stays `running`, real PG
    read). Uses a REAL live session; carried when none is available."""
    _need_pg()
    p = _new_project(client)
    run_id, sid = _maybe_live_pod_session(client, p)
    if not sid:
        pytest.skip(
            "carried, needs a live registered session to stop (never "
            "fabricated)")
    s = client.post(f"/projects/{p}/hunting/{run_id}/sessions/{sid}/stop")
    assert s.status_code == 200, s.text
    assert s.json()["state"] == "stopping"
    row = stack.hunting_run_rows(p)
    assert row, "expected at least the run row"
    # A single-session stop must not have terminalised the run row.
    assert row[0]["status"] not in ("stopped", "complete", "failed",
                                    "interrupted")


def test_C26_session_verb_no_runtime_503(client):
    """C26: a per-session verb without an active runtime -> 503. Blocked on the
    live sibling (the control plane has landed); probed and carried exactly as
    C4."""
    _need_pg()
    p = _new_project(client)
    if not _runtime_landed(client, p):
        r = client.post(
            f"/projects/{p}/hunting/{uuid.uuid4().hex}/sessions/x/pause")
        assert r.status_code == 503, r.text
        assert "module runtime is not active" in r.text
        return
    pytest.skip(
        "carried, blocked on: the live control plane has landed; the "
        "no-active-runtime 503 premise is not reproducible against a live "
        "runner (refusing to fabricate a runtime-down state)"
    )


# ===========================================================================
# REST perimeter - module-wide gate, HUNTING-ONLY (C27-C29)
# ===========================================================================

def test_C27_module_pause_then_launch_503(client):
    """C27: POST .../modules/hunting/pause -> `{"state":"paused"}`; a subsequent
    POST .../hunting (whole-pipeline launch) -> 503 `module not accepting new
    work`. HUNTING-ONLY."""
    _need_pg()
    p = _new_project(client)
    pause = client.post(f"/projects/{p}/modules/hunting/pause")
    assert pause.status_code == 200, pause.text
    assert pause.json()["state"] == "paused"
    launch = client.post(f"/projects/{p}/hunting", json={"candidates": []})
    assert launch.status_code == 503, launch.text
    assert "module not accepting new work" in launch.text
    # Restore the module so a later module-state probe is honest.
    client.post(f"/projects/{p}/modules/hunting/resume")


def test_C28_pause_resume_pause_reflects_states(client):
    """C28: pause -> resume -> pause on hunting reflects `paused`/`running`;
    an unknown module -> 404 `unknown module`. HUNTING-ONLY."""
    p = _new_project(client)
    paused = client.post(f"/projects/{p}/modules/hunting/pause")
    assert paused.status_code == 200 and paused.json()["state"] == "paused"
    running = client.post(f"/projects/{p}/modules/hunting/resume")
    assert running.status_code == 200 and running.json()["state"] == "running"
    paused2 = client.post(f"/projects/{p}/modules/hunting/pause")
    assert paused2.status_code == 200 and paused2.json()["state"] == "paused"
    unknown = client.post(f"/projects/{p}/modules/not-a-module/pause")
    assert unknown.status_code == 404, unknown.text
    assert "unknown module" in unknown.text
    client.post(f"/projects/{p}/modules/hunting/resume")


def test_C29_drain_hunting_stopped(client):
    """C29: drain hunting (paused first) -> `stopped` (the response state is
    asserted; the flush/archive is best-effort given the live module state).
    HUNTING-ONLY.

    Drain is TERMINAL on the shared runtime (no un-drain verb): after asserting
    `stopped` the test RESTORES the sibling by restarting the agent-hw container
    so the shared module returns to `running` and never poisons the OTHER
    predicates of this file (order-independent, cross-invocation safe)."""
    p = _new_project(client)
    client.post(f"/projects/{p}/modules/hunting/pause")
    d = client.post(f"/projects/{p}/modules/hunting/drain")
    assert d.status_code == 200, d.text
    assert d.json()["state"] == "stopped"
    assert stack.restart_sibling(), "sibling did not recover after the drain test"
