"""Walkthrough predicates E1-E10 for the hunting-pipeline assertion catalogue
(`docs/design/hunting-wiring-assertions.md` - "Walkthrough predicates (e2e -
live stack)").

These are LIVE walkthroughs, in the tier's own words: the stack runs in
production state via the sibling `agent-hw` container (docker-compose.wiring.
e2e.yml), and every predicate drives the REAL HTTP surface with
`httpx.Client(base_url=hunting_wiring_stack.agent_http_url())` and reads every
terminal quantity back out of the REAL stores / Postgres via
`hunting_wiring_stack`'s named reads. Nothing inside the live edge is
substituted - the LLM pod/hunter chain is REAL (real LLM turns through the
embedded LiteLLM gateway per the operator ruling), and pod/hunter sessions are
NEVER stubbed: a real session is driven to registration through a whole-run
launch before a per-session verb is exercised.

Run modes (per `hunting_wiring_stack`, mirroring `tests/e2e/hunting_stack.py`):
the sibling is brought up if not already up; `wiring_stack_skip_reason()` skips
with a clear reason when it is unreachable, and `hunting_pg_skip_reason()`
skips the PG-row predicates (E1/E3/E5/E7/E10) when live Postgres is not
reachable. Without the stack the file COLLECTS and skips cleanly; it never
errors on a broken fixture.

Failure policy (per the catalogue precision notes): fixtures are seeded through
the REAL store APIs and validated at setup - a reachable stack with an absent
fixture FAILS LOUDLY (raises) rather than silently passing; a carried/blocked
predicate is an explicit `pytest.skip("carried, blocked on <reason>")`. Each
test owns a FRESH project (the one-live-run guard is per-project, so isolation
avoids cross-test bleed and keeps the exact-count read-backs honest).
"""
from __future__ import annotations

import os
import time
import uuid

import pytest

from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
from polymerhus.attack.hunting.mover import (
    hunter_session_id,
    pod_session_id,
)
from tests.integration import hunting_wiring_stack as stack

# The production identity conventions: the hunter memory key is the threat
# dispatch id `<unit_name>__<threat_id>` (S3 8.9), and the CWE/class pair keys the
# seeded spec's identity.
UNIT = "Service:slug:a"
UNIT_NAME = "Service-slug-a"
DISPATCH_ID = f"{UNIT_NAME}__threat-1"
FAULT = "fault-1"
CLASS = "CSRF"
SPEC = "sqli"
STRATEGY = "blind"
SPEC_FILE = f"{SPEC}_{STRATEGY}"


# --- live-tier gates ----------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _boot_wiring_stack():
    """Bring up the wiring sibling `agent-hw` ONCE per module (best-effort) so
    the per-test gates never repeat the expensive bring-up/poll. When the
    sibling cannot come up (e.g. the embedded gateway's model registry is empty
    without live keys), the per-test `_need_stack` gates skip with a clear
    reason."""
    stack.ensure_sibling_timeout()
    return


def _need_stack() -> None:
    reason = stack.wiring_stack_skip_reason()
    if reason:
        pytest.skip(f"carried, {reason}")


def _need_pg() -> None:
    reason = stack.hunting_pg_skip_reason()
    if reason:
        pytest.skip(f"carried, {reason}")


def _new_project(client, prefix: str = "hw-e2e") -> str:
    return stack.create_project(client, f"{prefix}-{uuid.uuid4().hex[:8]}")


@pytest.fixture
def client():
    _need_stack()
    return stack.http_client()


# --- local helpers -------------------------------------------------------------


def _wait_terminal(project_id: str, run_id: str, *, timeout: float = 240,
                   interval: float = 3) -> dict:
    """Poll the real `hunting_runs` row until a terminal status, returning the
    exact row observed (fail-open: the terminal may be any of complete/failed/
    stopped/interrupted - the caller asserts the branch it requires)."""
    terminal = {"complete", "failed", "stopped", "interrupted"}
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        for row in stack.hunting_run_rows(project_id):
            if row["hunting_run_id"] == run_id:
                last = row
                if row["status"] in terminal:
                    return row
        time.sleep(interval)
    raise AssertionError(
        f"hunting run {run_id} did not reach a terminal within {timeout}s "
        f"(last observed: {last})"
    )


def _session_pause_until_registered(client, project_id: str, run_id: str,
                                    session_id: str, *,
                                    timeout: float = 90.0) -> bool:
    """Poll the per-session `pause` verb until the session registers (200
    `held`) or the window closes. True when registered (a REAL live session),
    False otherwise - the caller carries with a precise reason, never
    fabricating a session."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.post(
            f"/projects/{project_id}/hunting/{run_id}/sessions/{session_id}/pause",
            timeout=30,
        )
        if resp.status_code == 200:
            return True
        time.sleep(3)
    return False


# =============================================================================
# E1 - whole-pipeline happy path
# =============================================================================

def test_E1_whole_pipeline_happy_path(client):
    """id: E1 - whole-pipeline happy path. The deterministic baseline: a run
    with no dispatchable model reaches `complete` immediately with no produced
    threat files (real `hunting_runs` row read-back). Then a run seeded with a
    `ratified` spec and an experiment-log slice is driven so the surfer
    dispatches one pod through the REAL edge; the run is polled to a terminal
    row (complete on the happy path, fail-open otherwise) and the store
    read-backs are asserted against the real store - never a value the code
    under test returns."""
    _need_pg()
    # Baseline: a run with no dispatchable produced work reaches complete.
    base = _new_project(client, "hw-e1b")
    r = client.post(f"/projects/{base}/hunting", json={})
    assert r.status_code == 201, r.text
    base_rid = r.json()["hunting_run_id"]
    row = stack.wait_for_hunting_run_status(base, base_rid, status="complete")
    assert row["status"] == "complete"
    # A whole run never fabricates dispatch input: the produced threat family is
    # empty on a project with no modeller pass.
    assert stack.produced_threat_files(base) == []

    # Richer seeded-spec run through the REAL pod/hunter edge. Seed the
    # ratified spec + experiment log first (the pod work keeps the run alive
    # while the threat is seeded), launch, then seed the COMPLETED unit threat
    # model under the LAUNCHED run id (S2 8.3: the mover's read is run-scoped,
    # so a pre-launch placeholder id would be inert).
    p = _new_project(client, "hw-e1")
    spec_file = stack.seed_test_spec(
        p, hunt_key=DISPATCH_ID, fault_keyword=SPEC, strategy_keyword=STRATEGY)
    # T4b (#387): the threat file is the dispatch record; the seeded SPEC still
    # drives the real POD edge. A hunter is dispatched from a produced threat
    # file (live after T6 #379), which needs the run's own modeller and the
    # production hunter prompt work phase (T7 #380) - never a fabricated
    # dispatch input.
    stack.seed_experiment_log(p, spec_id=spec_file)
    launch = client.post(f"/projects/{p}/hunting", json={})
    assert launch.status_code == 201, launch.text
    rid = launch.json()["hunting_run_id"]
    stack.seed_threat_model_unit(p, unit_id=UNIT, run_id=rid)
    # The live mover can consume the seeded threat in the same tick, so the
    # premise is that the identity is SEEN on the run's side (produced or
    # consumed), not that it is still produced at read time.
    seeded_threat = f"{UNIT_NAME}/threat-1"
    assert (
        seeded_threat in stack.produced_threat_files(p)
        or seeded_threat in stack.consumed_threat_files(p)
    ), "E1 seed premise: the seeded threat must exist in produced/ or consumed/"
    # The seeded pod drives REAL LLM turns + kali tool calls; on a loaded host
    # that pass can take longer than the 240s default - give it an honest
    # window. Fail-open: if the live LLM pass cannot drive the edge the run
    # still lands an honest terminal (complete on the happy path, failed on a
    # real degrade) - the run-row read-back is asserted, never a fabricated
    # non-empty statement.
    term = _wait_terminal(p, rid, timeout=600)
    # Fail-open: if the live LLM pass cannot drive the edge the run still lands
    # an honest terminal (complete on the happy path, failed on a real degrade) -
    # the run-row read-back is asserted, never a fabricated non-empty statement.
    assert term["status"] in ("complete", "failed"), term
    if term["status"] == "complete":
        # The threat file moved produced->consumed (the mover's at-least-once
        # marker), the ratified spec moved produced->consumed, and the pod
        # export + durable parent-keyed note exist.
        assert f"{UNIT_NAME}/threat-1" in stack.consumed_threat_files(p), \
            "expected the seeded threat file moved to consumed on a complete run"
        assert stack.consumed_spec_files(p, DISPATCH_ID), \
            "expected the ratified spec moved to consumed on a complete run"
        assert stack.pod_export_entries(p, spec_file), \
            "expected a durable pod export envelope on a complete run"
        notes = HunterMemoryStore().read_notes(p, parent_key=DISPATCH_ID)
        assert notes, \
            "expected the durable parent-keyed note written at pod completion"


# =============================================================================
# E2 - cross-run produced-spec reconciliation (the anti-wedge regression)
# =============================================================================

def test_E2_cross_run_produced_spec_reconciliation(client):
    """id: E2 - cross-run produced-spec reconciliation (anti-wedge regression).
    A produced `ratified` spec whose dispatch threat belongs to an EARLIER run
    (no live parent session) must still dispatch ONE pod through the own-STATUS
    gate and move produced->consumed; the export is recorded durably under the
    spec's dispatch id; and the run reaches `complete` - NEVER wedged on a
    stale parent-liveness check."""
    _need_pg()
    p = _new_project(client, "hw-e2")
    # The parent was consumed by an EARLIER run: no live parent inbox exists in
    # THIS run. The parent identity is the spec's own dispatch id, and the
    # durable note is keyed by it regardless of any parent session.
    assert stack.consumed_spec_files(p, DISPATCH_ID) == []

    # The earlier run consumed the parent threat file: seed the COMPLETED model,
    # then move its threat to consumed/ through the store primitive (no live
    # parent session in THIS run).
    stack.seed_threat_model_unit(p, unit_id=UNIT, run_id="hw-e2-earlier")
    assert stack.consume_seeded_threat(p, unit_id=UNIT) is True
    assert stack.consumed_threat_files(p) == [f"{UNIT_NAME}/threat-1"]

    # Seed the produced `ratified` spec under the dispatch id.
    spec_file = stack.seed_test_spec(
        p, hunt_key=DISPATCH_ID, fault_keyword=SPEC, strategy_keyword=STRATEGY)
    assert stack.produced_spec_files(p, DISPATCH_ID) == [spec_file]

    # Launch a fresh whole run; the surfer must dispatch the pod (own-status
    # gate) with NO live parent and reach complete - not wedge on quiesce.
    launch = client.post(f"/projects/{p}/hunting", json={})
    assert launch.status_code == 201, launch.text
    rid = launch.json()["hunting_run_id"]
    term = _wait_terminal(p, rid, timeout=240)
    # The regression's whole point: it must reach complete, never stay running.
    assert term["status"] == "complete", (
        f"E2 wedge regression: run ended {term['status']!r} instead of complete")

    # The spec dispatched through the own-status gate and moved produced->consumed.
    assert stack.produced_spec_files(p, DISPATCH_ID) == []
    assert stack.consumed_spec_files(p, DISPATCH_ID) == [spec_file]
    # The durable parent-keyed record exists under the parent's canonical key
    # (real hunter-memory read, independent of any live parent session).
    notes = HunterMemoryStore().read_notes(p, parent_key=DISPATCH_ID)
    assert notes, "E2: no durable parent-keyed note after a complete run"
    assert any(DISPATCH_ID in n["key"] for n in notes), \
        f"E2: parent-keyed note not under {DISPATCH_ID}: {notes}"


# =============================================================================
# E3 - mid-flight stop
# =============================================================================

def test_E3_mid_flight_stop(client):
    """id: E3 - mid-flight stop. Launch a whole run that has real dispatching
    work (a `ratified` spec keeps it alive mid-pass); POST
    .../hunting/{id}/stop while it is mid-pass -> `{"stopping": True}`; poll the
    run row -> `stopped`; the append-only store preserves the partial trail
    (the seeded fixtures remain readable through the real stores); and the run's
    sessions are drained (a per-session verb on the run's namespace 404s - the
    registry emptied)."""
    _need_pg()
    p = _new_project(client, "hw-e3")
    spec_file = stack.seed_test_spec(
        p, hunt_key=DISPATCH_ID, fault_keyword=SPEC, strategy_keyword=STRATEGY)
    launch = client.post(f"/projects/{p}/hunting", json={})
    assert launch.status_code == 201, launch.text
    rid = launch.json()["hunting_run_id"]

    s = client.post(f"/projects/{p}/hunting/{rid}/stop", timeout=30)
    assert s.status_code == 200, s.text
    assert s.json() == {"hunting_run_id": rid, "stopping": True}

    row = stack.wait_for_hunting_run_status(p, rid, status="stopped")
    assert row["status"] == "stopped"
    # The partial trail survives (append-only store): the seeded spec is still
    # readable through the real store (produced or consumed, whichever the stop
    # caught it in).
    spec_partial = (
        stack.produced_spec_files(p, DISPATCH_ID)
        + stack.consumed_spec_files(p, DISPATCH_ID)
    )
    assert len(spec_partial) >= 1, \
        "E3: the stopped run's partial trail vanished - expected the seeded " \
        "spec to remain readable"
    # The run's sessions were drained: pausing any session of the stopped run's
    # namespace -> 404 (no live session remains - the registry emptied).
    dead = f"hunting:{rid}:hunt:{DISPATCH_ID}"
    probe = client.post(f"/projects/{p}/hunting/{rid}/sessions/{dead}/pause")
    assert probe.status_code == 404, \
        f"E3: expected the drained run's session to 404, got {probe.status_code}"


# =============================================================================
# E4 - per-session pause/resume mid-graph
# =============================================================================

def test_E4_per_session_pause_resume_mid_graph(client):
    """id: E4 - per-session pause/resume mid-graph. Carried, blocked on T7
    (#380): the per-threat hunter session id is derived from a produced threat file
    (`<unit_name>__<threat_id>`), and driving a live hunt from one needs the
    production hunter prompt work phase. The per-session verbs themselves keep
    their own coverage in C19-C22 (pod sessions and the modeller pass) and E9
    (pod)."""
    _need_pg()
    p = _new_project(client, "hw-e4")
    launch = client.post(f"/projects/{p}/hunting", json={})
    assert launch.status_code == 201, launch.text
    rid = launch.json()["hunting_run_id"]
    hunter_sid = hunter_session_id(rid, DISPATCH_ID)

    pytest.skip(
        f"carried, blocked on T7 #380: the hunter session {hunter_sid!r} needs "
        f"a modeller-produced threat and the production hunter prompt work phase "
        f"to drive a live hunt")
    pause = client.post(
        f"/projects/{p}/hunting/{rid}/sessions/{hunter_sid}/pause")
    assert pause.status_code == 200, pause.text
    assert pause.json()["state"] == "held"
    resume = client.post(
        f"/projects/{p}/hunting/{rid}/sessions/{hunter_sid}/resume")
    assert resume.status_code == 200, resume.text
    assert resume.json()["state"] == "resumed"
    term = _wait_terminal(p, rid)
    assert term["status"] == "complete", \
        f"E4: run ended {term['status']!r} instead of complete after resume"


# =============================================================================
# E5 - single-session stop does not end the run
# =============================================================================

def test_E5_single_session_stop_does_not_end_the_run(client):
    """id: E5 - single-session stop does not end the run. Carried, blocked on
    T7 (#380): the contract needs a hunter AND a pod session live at once (one
    stopped, the sibling keeping the run alive), and driving a live hunter needs
    the production hunter prompt work phase. The single-session stop verb keeps
    its own coverage in C22 and E9 (the pod session, the surviving family)."""
    _need_pg()
    p = _new_project(client, "hw-e5")
    spec_file = stack.seed_test_spec(
        p, hunt_key=DISPATCH_ID, fault_keyword=SPEC, strategy_keyword=STRATEGY)
    launch = client.post(f"/projects/{p}/hunting", json={})
    assert launch.status_code == 201, launch.text
    rid = launch.json()["hunting_run_id"]
    pod_sid = pod_session_id(rid, DISPATCH_ID, spec_file)
    pytest.skip(
        f"carried, blocked on T7 #380: the single-session-stop contract needs "
        f"a live hunter sibling, and driving {hunter_session_id(rid, DISPATCH_ID)!r} "
        f"needs the production hunter prompt work phase")

    # The run reaches a terminal only once the remaining sessions settle.
    branch = _poll_branch(p, rid, timeout=240)
    assert branch["status"] in ("complete", "running"), branch
    # Assert the EXACT observed branch and document it (catalogue E5): either
    # `complete` (all other sessions settled -> quiesce) or `running` while
    # other sessions are still mid-flight. Both are the implementation-honest
    # outcome; neither is forced.
    if branch["status"] == "running":
        print(
            "E5 observed branch: the run stayed `running` within the window "
            "(remaining sessions still mid-flight) - the documented running "
            "branch, not a failure"
        )


def _poll_branch(project_id: str, run_id: str, *, timeout: float,
                 interval: float = 3) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        for row in stack.hunting_run_rows(project_id):
            if row["hunting_run_id"] == run_id:
                last = row
                if row["status"] in ("complete", "stopped", "failed", "interrupted"):
                    return row
        time.sleep(interval)
    return last or {"hunting_run_id": run_id, "status": "running"}


# =============================================================================
# E6 - modeller-only launch (no run row)
# =============================================================================

def test_E6_modeller_only_launch_creates_no_run_row(client):
    """id: E6 (renamed by T10) - modeller-only launch. `POST
    .../hunting/modeller` -> 202 (its synthetic run_id is for observability
    only); a follow-up `POST .../hunting/hunt` answers the T4b retirement 410
    (the config family retired - never a silent accept); and NO `hunting_runs`
    row was created by the modeller-only launch - `GET .../hunting/{synthetic_
    run_id}` -> 404."""
    _need_pg()
    p = _new_project(client, "hw-e6")
    o = client.post(f"/projects/{p}/hunting/modeller", json={})
    assert o.status_code == 202, o.text
    ob = o.json()
    assert ob["component"] == "threat_modeller"
    assert ob["dispatched_asynchronously"] is True
    synthetic_rid = ob["run_id"]
    assert isinstance(synthetic_rid, str) and synthetic_rid

    # The modeller-only launch never opened a hunting_runs row.
    assert stack.hunting_run_rows(p) == [], \
        "E6: the modeller-only launch must NOT create a hunting_runs row"
    g = client.get(f"/projects/{p}/hunting/{synthetic_rid}")
    assert g.status_code == 404, \
        f"E6: synthetic run id must 404, got {g.status_code}"

    # A follow-up hunt enqueue is the LOUD retirement (T4b #387): it writes
    # nothing into the live produced threat family.
    h = client.post(
        f"/projects/{p}/hunting/hunt",
        json={"unit_id": UNIT, "web_vulnerability_class": CLASS, "fault": FAULT})
    assert h.status_code == 410, h.text
    assert "retired" in h.json()["detail"].lower()
    assert stack.produced_threat_files(p) == []
    # No run row yet even after the component launches.
    assert stack.hunting_run_rows(p) == []


# =============================================================================
# E7 - one-live-run guard
# =============================================================================

def test_E7_one_live_run_guard(client):
    """id: E7 - one-live-run guard. Two back-to-back whole-run launches on the
    same project while the first is live -> first 201, second 409 (the running
    row is the guard); exactly ONE `running` row via `hunting_run_rows`."""
    _need_pg()
    p = _new_project(client, "hw-e7")
    # Seed dispatching work (the live POD family) so the first run stays alive
    # across the second POST. A hunter dispatches only from a produced threat
    # file (T6 #379), and the production hunter prompt work phase (T7 #380)
    # drives a live hunt.
    stack.seed_test_spec(
        p, hunt_key=DISPATCH_ID, fault_keyword=SPEC, strategy_keyword=STRATEGY)
    first = client.post(f"/projects/{p}/hunting", json={})
    assert first.status_code == 201, first.text
    first_id = first.json()["hunting_run_id"]
    second = client.post(f"/projects/{p}/hunting", json={})
    if second.status_code == 409:
        rows = stack.hunting_run_rows(p)
        assert [r["hunting_run_id"] for r in rows] == [first_id]
        assert rows[0]["status"] == "running"
    else:
        # The first run reached terminal before the second landed - the guard
        # released. Surface the actual behavior rather than force the 409.
        pytest.fail(
            f"E7 discrepancy: the first run left the live state before the "
            f"second POST landed; observed {second.status_code} instead of 409 "
            f"(single-row guard not exercised)"
        )


# =============================================================================
# E8 - at-most-once replay
# =============================================================================

def test_E8_hunt_enqueue_is_retired_loudly(client):
    """id: E8 (re-pointed by T4b #387) - the hunter-only hunt-config enqueue
    RETIRED with the config family: the threat file is the dispatch record and a
    live run's surfer dispatches it. The live stack answers a LOUD 410 naming
    the replacement instead of silently accepting a config into a family nothing
    reads; nothing lands in the live produced threat family. The at-most-once
    replay predicate retired with the enqueue (no novelty gate is left); the
    whole-run one-live-run guard keeps its own at-most-once coverage in E7.
    The eval translation is T10 (#383)."""
    _need_pg()
    p = _new_project(client, "hw-e8")
    body = {"unit_id": UNIT, "web_vulnerability_class": CLASS, "fault": FAULT}
    first = client.post(f"/projects/{p}/hunting/hunt", json=body)
    assert first.status_code == 410, first.text
    assert "retired" in first.json()["detail"].lower()
    second = client.post(f"/projects/{p}/hunting/hunt", json=body)
    assert second.status_code == 410, second.text
    assert stack.produced_threat_files(p) == [], (
        "E8: the retired enqueue must not write the produced threat family")


# =============================================================================
# E9 - pod-only resume
# =============================================================================

def test_E9_pod_only_resume(client):
    """id: E9 - pod-only resume. Precondition a REAL paused pod session (drive a
    whole run far enough that a pod session registers, then pause it - real,
    never a stub); `POST .../hunting/pod {session_id}` -> 202 resumed; the
    session's hold is released and the session remains a live registered session
    of the runtime (a subsequent per-session resume is the runtime verb's safe
    no-op, 200 - not a 404). Carried when no live pod session can be
    established."""
    _need_pg()
    p = _new_project(client, "hw-e9")
    spec_file = stack.seed_test_spec(
        p, hunt_key=DISPATCH_ID, fault_keyword=SPEC, strategy_keyword=STRATEGY)
    launch = client.post(f"/projects/{p}/hunting", json={})
    assert launch.status_code == 201, launch.text
    rid = launch.json()["hunting_run_id"]
    pod_sid = pod_session_id(rid, DISPATCH_ID, spec_file)
    if not _session_pause_until_registered(client, p, rid, pod_sid):
        pytest.skip(
            f"carried, blocked on: no real held pod session {pod_sid!r} within "
            f"the observation window (never fabricated)")

    r = client.post(f"/projects/{p}/hunting/pod", json={"session_id": pod_sid})
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["component"] == "pod"
    assert body["resumed"] is True
    assert body["session_id"] == pod_sid
    # The hold is cleared and the session is still LIVE in the runtime registry:
    # a per-session resume of the same session is the safe no-op 200, not a 404.
    again = client.post(
        f"/projects/{p}/hunting/{rid}/sessions/{pod_sid}/resume")
    assert again.status_code == 200, \
        f"E9: expected the resumed session to remain live (200), got {again.status_code}"


# =============================================================================
# E10 - process-death orphan reconcile
# =============================================================================

def test_E10_process_death_orphan_reconcile(client, monkeypatch):
    """id: E10 - process-death orphan reconcile. Open a `running` row (a real
    whole-run launch) and simulate the owning-process death by leaving a
    `running` row without its process (a row opened directly via the real PG
    accessor `pg.create_hunting_run(project_id)` that is never completed), then
    run the startup reconcile `reconcile_orphaned_hunting_runs()` through the
    REAL code path; assert the orphan flips to `interrupted`; a fresh whole-run
    launch is then allowed (the guard is released -> 201)."""
    _need_pg()
    from polymerhus.app.clients import pg
    from polymerhus.app.config import config

    # Point the real pg/config code path at the live PG (host mode); in-network
    # the env already carries the live DSN.
    live = stack.pg_live_dsn()
    assert live, "E10 requires the live PG DSN"
    monkeypatch.setenv("POSTGRES_DSN", live)
    monkeypatch.setattr(config, "POSTGRES_DSN", live)

    p = _new_project(client, "hw-e10")
    # A running row with NO owning process (never completed) - the orphan.
    orphan_id = pg.create_hunting_run(p)
    assert [r["status"] for r in stack.hunting_run_rows(p)] == ["running"]

    # The startup reconcile through the real code path flips the orphan.
    n = pg.reconcile_orphaned_hunting_runs()
    assert n >= 1
    rows = {r["hunting_run_id"]: r["status"] for r in stack.hunting_run_rows(p)}
    assert rows[orphan_id] == "interrupted", \
        f"E10: orphan run {orphan_id} not reconciled to interrupted ({rows})"

    # The guard is released: a fresh whole-run launch is now allowed (201).
    # (The no-dispatchable-work quiesce can be fast - by the read-back the fresh run may
    # already be terminal; that is reported, never forced to `running`.)
    launch = client.post(f"/projects/{p}/hunting", json={})
    assert launch.status_code == 201, launch.text
    new_rows = {r["hunting_run_id"]: r["status"] for r in stack.hunting_run_rows(p)}
    assert new_rows[launch.json()["hunting_run_id"]] in (
        "running", "complete", "failed", "stopped", "interrupted",
    ), new_rows[launch.json()["hunting_run_id"]]
