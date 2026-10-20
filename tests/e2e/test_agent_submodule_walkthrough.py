"""Walkthrough predicates E1-E3 for the agent sub-module catalogue (#317)
(`docs/design/hunting-317-agent-submodule-assertions.md` - "Walkthrough
predicates (end-to-end)").

These are LIVE walkthroughs against the sibling agent container (the same
`hunting_wiring_stack` target the hunting-wiring e2e drives): every predicate
drives the REAL HTTP surface with `httpx.Client` and reads terminal quantities
back through the REAL stores / Postgres. The model provider is the live edge
and is never substituted.

T4b (#387) retired the config family from the dispatch path (the loop file is
the dispatch record) and T6 (#379) made the payload harness live, so E1-E3
carry with a precise T7 (#380) skip: a hunter dispatches only from a produced
loop file, and driving a live hunt from one needs the production hunter prompt
work phase. The role-state and thread surfaces keep their own coverage in the
unit and integration tiers; the pod session path stays live.

Run modes mirror the hunting-wiring e2e: the sibling is brought up best-effort
once per module; the per-test gates skip cleanly when it (or live PG) is
unreachable. Fixtures are seeded through the REAL store APIs. Each test owns a
FRESH project (the one-live-run guard is per project). The E1 race - the stop
must land before the run's first surfer tick - is reported honestly: a lost race
carries with a precise reason, never a fabricated pass.
"""
from __future__ import annotations

import uuid

import pytest

from tests.integration import hunting_wiring_stack as stack


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


# =============================================================================
# E1-E3 - carried on T7 (#380) after T4b (#387) / T6 (#379)
# =============================================================================

def test_E1_a_down_hunter_holds_the_run_open(client):
    """id: E1 - carried, blocked on T7 (#380). The predicate needs a live hunter
    session the paused role holds; T6 (#379) made a hunter dispatch from a
    produced loop file, but driving one live needs the production hunter prompt
    work phase, so no dispatchable hunter work exists to hold the run open yet.
    The role-state surface itself keeps its own coverage in the unit and
    integration tiers, and the pod path stays live."""
    _need_pg()
    p = _new_project(client, "as-e1")
    pytest.skip(
        "carried, blocked on T7 #380: no live hunter session can be driven "
        "(the loop payload harness is live after T6 #379; the production "
        "hunter prompt work phase is needed to author a hunt from a loop)")


def test_E2_starting_the_role_completes_the_run(client):
    """id: E2 - carried, blocked on T7 (#380): starting the hunter role can
    only release DISPATCHABLE work, and driving a hunt from a produced loop
    file needs the production hunter prompt work phase."""
    _need_pg()
    p = _new_project(client, "as-e2")
    pytest.skip(
        "carried, blocked on T7 #380: the hunter role has no driveable hunt "
        "to release (the production hunter prompt work phase is needed)")


def test_E3_a_single_thread_stops_and_resumes(client):
    """id: E3 - carried, blocked on T7 (#380): the `/threads/{id}/stop|resume`
    surface needs a live `hunt:` thread, and driving one needs the production
    hunter prompt work phase. The pod session path stays live (E9)."""
    _need_pg()
    p = _new_project(client, "as-e3")
    pytest.skip(
        "carried, blocked on T7 #380: no live hunter thread can be driven "
        "(the production hunter prompt work phase is needed)")
