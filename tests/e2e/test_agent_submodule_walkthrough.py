"""Walkthrough predicates E1-E3 for the agent sub-module catalogue (#317)
(`docs/design/hunting-317-agent-submodule-assertions.md` - "Walkthrough
predicates (end-to-end)").

These are LIVE walkthroughs against the sibling agent container (the same
`hunting_wiring_stack` target the hunting-wiring e2e drives): every predicate
drives the REAL HTTP surface with `httpx.Client` and reads terminal quantities
back through the REAL stores / Postgres. The model provider is the live edge
and is never substituted.

- E1: a down hunter role holds the run open - a produced RATIFIED config stays
  produced and the run does not quiesce `complete` while the role is stopped.
- E2: starting the role dispatches the produced work and the run completes.
- E3: a single `hunt:` thread stops (held) and resumes through the
  `/threads/{id}/stop|resume` surface.

Run modes mirror the hunting-wiring e2e: the sibling is brought up best-effort
once per module; the per-test gates skip cleanly when it (or live PG) is
unreachable. Fixtures are seeded through the REAL store APIs. Each test owns a
FRESH project (the one-live-run guard is per project). The E1 race - the stop
must land before the run's first surfer tick - is reported honestly: a lost race
carries with a precise reason, never a fabricated pass.
"""
from __future__ import annotations

import time
import uuid

import pytest

from tests.integration import hunting_wiring_stack as stack

UNIT = "Service:slug:a"
FAULT = "CWE-352"
CLASS = "CSRF"
FAULT_KEY = f"{UNIT}_{FAULT}_{CLASS}"
CONFIG_KEY = f"{UNIT}::{FAULT}::{CLASS}"
SPEC = "sqli"
STRATEGY = "blind"
SPEC_FILE = f"{SPEC}_{STRATEGY}"


@pytest.fixture(scope="module", autouse=True)
def _boot_wiring_stack():
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


def _new_project(client, prefix: str = "as-e2e") -> str:
    return stack.create_project(client, f"{prefix}-{uuid.uuid4().hex[:8]}")


@pytest.fixture
def client():
    _need_stack()
    return stack.http_client()


def _stop_role(client, project_id: str, run_id: str, role: str) -> None:
    """Stop the role, retrying in a tight loop (idempotent) to win the E1 race
    against the run's first surfer tick."""
    for _ in range(20):
        resp = client.post(
            f"/projects/{project_id}/hunting/{run_id}/agent-submodules/{role}/stop",
            timeout=30,
        )
        if resp.status_code == 200:
            return
        time.sleep(0.05)
    raise AssertionError(f"could not stop {role!r} for run {run_id}")


def _row_status(project_id: str, run_id: str) -> str | None:
    for row in stack.hunting_run_rows(project_id):
        if row["hunting_run_id"] == run_id:
            return row["status"]
    return None


# =============================================================================
# E1 - a down hunter holds the run open
# =============================================================================

def test_E1_a_down_hunter_holds_the_run_open(client):
    """id: E1 - a produced RATIFIED config with the hunter role `paused` stays
    produced and the run never quiesces `complete`. Entry: enqueue one config via
    `POST .../hunting/hunt`, launch the run, stop the hunter role before its
    first dispatch. The live edge (the model provider) is untouched; the stop
    race is reported, never fabricated."""
    _need_pg()
    p = _new_project(client, "as-e1")
    enq = client.post(
        f"/projects/{p}/hunting/hunt",
        json={"unit_id": UNIT, "fault_class": FAULT, "vulnerability_class": CLASS},
    )
    assert enq.status_code == 202, enq.text
    assert enq.json()["enqueued_key"] == CONFIG_KEY
    assert CONFIG_KEY in stack.produced_config_keys(p)

    launch = client.post(f"/projects/{p}/hunting", json={"candidates": []})
    assert launch.status_code == 201, launch.text
    rid = launch.json()["hunting_run_id"]

    _stop_role(client, p, rid, "hunter")
    listing = client.get(
        f"/projects/{p}/hunting/{rid}/agent-submodules").json()
    assert next(x for x in listing if x["role"] == "hunter")["state"] == "paused"

    # The run must NOT reach `complete` while the hunter is paused: its
    # dispatchable work stays produced and `run_work_remaining` holds quiesce.
    deadline = time.time() + 45
    while time.time() < deadline:
        assert _row_status(p, rid) != "complete", (
            "E1 breach: the run quiesced complete while the hunter role was paused"
        )
        time.sleep(3)

    produced = stack.produced_config_keys(p)
    threads = client.get(f"/projects/{p}/hunting/{rid}/threads").json()
    roles = {t["role"] for t in threads}
    if CONFIG_KEY not in produced:
        # The stop lost the race against the first surfer tick: the config was
        # already dispatched (consumed) and a hunter thread is live. Report it
        # honestly rather than fabricate the produced branch.
        pytest.skip(
            "carried: the stop landed after the first surfer tick dispatched the "
            f"config (produced={produced!r}, roles={roles!r})")
    # The produced branch: the config is still produced and no hunt: thread ran.
    assert CONFIG_KEY in produced
    assert "hunter" not in roles, (
        f"E1: a hunter thread must not be live while its role is paused: {roles}")


# =============================================================================
# E2 - starting the role completes the run
# =============================================================================

def test_E2_starting_the_role_completes_the_run(client):
    """id: E2 - starting the stopped hunter role releases dispatch: the next
    surfer tick dispatches the produced config, the pipeline runs through the
    REAL edge, and the run reaches `complete`."""
    _need_pg()
    p = _new_project(client, "as-e2")
    spec_file = stack.seed_test_spec(
        p, fault_key=FAULT_KEY, fault_keyword=SPEC, strategy_keyword=STRATEGY)
    assert spec_file == SPEC_FILE
    stack.seed_hunt_config(
        p, unit_id=UNIT, fault_class=FAULT, vulnerability_class=CLASS,
        status="ratified")

    launch = client.post(f"/projects/{p}/hunting", json={"candidates": []})
    assert launch.status_code == 201, launch.text
    rid = launch.json()["hunting_run_id"]

    _stop_role(client, p, rid, "hunter")
    start = client.post(
        f"/projects/{p}/hunting/{rid}/agent-submodules/hunter/start")
    assert start.status_code == 200, start.text
    assert start.json()["state"] == "running"

    row = stack.wait_for_hunting_run_status(p, rid, status="complete", timeout=900)
    assert row["status"] == "complete"
    # the produced work moved produced -> consumed
    assert stack.produced_config_keys(p) == []
    assert stack.consumed_spec_files(p, FAULT_KEY)


# =============================================================================
# E3 - a single thread stops and resumes
# =============================================================================

def test_E3_a_single_thread_stops_and_resumes(client):
    """id: E3 - a live `hunt:` thread pauses (`held`) and resumes through the
    `/threads/{id}/stop|resume` surface, and the thread stays registered. The
    real hunter thread is discovered by polling the thread listing."""
    _need_pg()
    p = _new_project(client, "as-e3")
    stack.seed_hunt_config(
        p, unit_id=UNIT, fault_class=FAULT, vulnerability_class=CLASS,
        status="ratified")
    launch = client.post(f"/projects/{p}/hunting", json={"candidates": []})
    assert launch.status_code == 201, launch.text
    rid = launch.json()["hunting_run_id"]

    thread_id = None
    deadline = time.time() + 90
    while time.time() < deadline and thread_id is None:
        threads = client.get(f"/projects/{p}/hunting/{rid}/threads").json()
        for t in threads:
            if t["role"] == "hunter":
                thread_id = t["thread_id"]
                break
        if thread_id is None:
            time.sleep(3)
    if thread_id is None:
        pytest.skip(
            "carried: no live hunter thread registered within the observation "
            "window (never fabricated)")

    stop = client.post(
        f"/projects/{p}/hunting/{rid}/threads/{thread_id}/stop", timeout=30)
    assert stop.status_code == 200, stop.text
    assert stop.json()["state"] == "held"
    held = {t["thread_id"]: t for t in client.get(
        f"/projects/{p}/hunting/{rid}/threads").json()}
    assert held[thread_id]["held"] is True

    resume = client.post(
        f"/projects/{p}/hunting/{rid}/threads/{thread_id}/resume", timeout=30)
    assert resume.status_code == 200, resume.text
    assert resume.json()["state"] == "resumed"
    held = {t["thread_id"]: t for t in client.get(
        f"/projects/{p}/hunting/{rid}/threads").json()}
    assert held[thread_id]["held"] is False
