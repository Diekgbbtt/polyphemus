"""Live walkthroughs for the unit threat model redesign.

Catalogue: `docs/design/unit-threat-model-assertions.md` (E1-E7).
The stack is the worktree's own `docker-compose.e2e.yml` agent (built from this
tree) on the shared dev network, with the local `http-e2e-target`.

E1 is the full production path: a real L1 unit from the white-jotter-001
ground-truth sample, the real modeller (real LLM), the real loop, the real
hunter, the real spec set, and the real test-executor pod. The target fixture
serves the ground truth's sign-in surface (`admin`/`123` accepted, a wrong
password rejected).

The test fails loudly on a broken fixture and skips only when the stack cannot
be reached (the repo's live-tier convention). Expected values come from the
ground truth and the spec, never recomputed from the code under test.
"""
from __future__ import annotations

import pytest

from tests.e2e import unit_threat_model_stack as stack
from tests.e2e.white_jotter_fixture import SERVICE_SLUG

UNIT = f"Service:{SERVICE_SLUG}"
UNIT_NAME = f"Service-{SERVICE_SLUG}"


@pytest.fixture(scope="module", autouse=True)
def _boot_stack():
    reason = stack.ensure_stack()
    if reason:
        pytest.skip(reason)


@pytest.fixture
def client():
    return stack.http_client()


@pytest.fixture(scope="module")
def _live_llm():
    reason = stack.ensure_llm()
    if reason:
        pytest.skip(reason)


def _spec_stems(project_id: str, hunt_key: str) -> list[str]:
    produced, consumed = stack.spec_files(project_id, hunt_key)
    return produced + consumed


def test_E1_whole_pipeline(client, _live_llm):
    """E1 - the whole pipeline from the modeller to the pod.

    Grounds S1 US1-4/6-7/14/18/21/24, S3 US1-4/8/19/25, S5 US1-8/10.
    The white-jotter-001 ground truth gives the unit, the trust agreement, the
    sign-in data flow, and the target's weak-default-credential surface.
    """
    project = stack.create_project(client, "utm-e1")
    seeded = stack.seed_white_jotter_l1(project)
    assert seeded["service"] == SERVICE_SLUG
    assert seeded["endpoints"] == 4

    launch = client.post(f"/projects/{project}/hunting", json={}, timeout=60)
    assert launch.status_code == 201, launch.text
    run_id = launch.json()["hunting_run_id"]

    row = stack.wait_terminal(client, project, run_id)
    assert row["status"] == "complete", row

    # The modeller's terminal artifact: one COMPLETED, valid model for the
    # ground-truth unit. It is read from the real store, not the API response.
    units = stack.read_completed_units(project)
    assert UNIT in units, f"completed units: {units}"
    model = stack.read_model(project, UNIT)
    assert model is not None, "the COMPLETED model is absent"
    assert model["state"] == "COMPLETED"
    assert model["validation"]["valid"] is True, model["validation"]
    assert model["risk_profile"]["total"] >= 0

    loops = stack.read_loop_files(project, UNIT)
    assert loops, "the ground-truth unit produced no dispatchable loop"
    dispatch_ids = [loop["dispatch_id"] for loop in loops]
    assert all(did.startswith(f"{UNIT_NAME}__loop-") for did in dispatch_ids), dispatch_ids

    # The hunter's spec set is under the loop dispatch id; the terminal status
    # vocabulary is the reduced one.
    spec_stems: list[str] = []
    for dispatch_id in dispatch_ids:
        spec_stems.extend(_spec_stems(project, dispatch_id))
    assert spec_stems, f"no spec set under {dispatch_ids}"
    from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
    store = HunterMemoryStore()
    specs = []
    for dispatch_id in dispatch_ids:
        specs.extend(store.read_specs(project, dispatch_id))
    assert specs, "the spec set is empty"
    assert all(
        spec.get("status") in {"hypothesised", "ratified", "dropped"}
        for spec in specs
    ), specs

    # The pod's terminal export exists for the emitted spec.
    spec_id = spec_stems[0].removesuffix(".yaml")
    exports = stack.pod_export_entries(project, spec_id)
    assert exports, f"no pod export for {spec_id}"

    # The operator audit trail: the run row carries the recorded intake.
    stats = row.get("stats") or {}
    assert stats.get("intake_order"), row
    assert UNIT in stats["intake_order"], stats["intake_order"]
    assert stats.get("risk_weights") == {
        "none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4,
    }, stats
