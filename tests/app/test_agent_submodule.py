"""Unit tier: the agent sub-module on the module runtime manager (#317).

The primitive is the addressable agent of one module: its lifecycle state reuses
`ModuleState`, its admission gate reuses `ModuleGate` (layered UNDER the module
gate), and it owns only `start` / `stop`. These tests pin the runtime manager's
public verbs on a REAL `asyncio.Runner` worker thread (never a mocked loop):

- registration is per (run, role) and a fresh manager reports every role up;
- stop/start round-trip and are idempotent; an unknown role is a named refusal
  and creates no handle;
- the role gate holds a role's in-flight unit at its next boundary and `start`
  releases it (two concurrent holds resume together);
- the module gate dominates the role gate (module pause holds every role);
- a module drain settles the role handles with the module;
- role state is in-memory and resets up on a fresh process (a fresh manager).

No live LLM / database (unit tier, CODING_STANDARD sections 6, 10).
"""
import asyncio
import threading
import time

import pytest

from polymerhus.app.runtime import (
    ModuleState,
    RuntimeManager,
    UnknownAgentSubmoduleRole,
)


def _wait_until(pred, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.01)
    raise AssertionError(f"condition not met within {timeout}s")


def _wait_until_flat(seq, timeout=5.0):
    deadline = time.monotonic() + timeout
    samples = []
    while time.monotonic() < deadline:
        samples.append(len(seq))
        if len(samples) >= 3 and samples[-1] == samples[-2] == samples[-3]:
            return
        time.sleep(0.02)
    raise AssertionError(f"sequence did not stabilise within {timeout}s")


@pytest.fixture
def runtime():
    rm = RuntimeManager()
    rm.start()
    try:
        yield rm
    finally:
        rm.shutdown()


# --- C1/C9: registration + the up default ------------------------------------

def test_booted_run_roles_are_registered_running(runtime):
    runtime.register_module("hunting")
    for role in ("orchestrator", "hunter", "pod"):
        runtime.register_agent_submodule("hunting", "r1", role)
        assert runtime.agent_submodule_state("hunting", "r1", role) is ModuleState.RUNNING


def test_fresh_manager_reports_every_role_running(runtime):
    runtime.register_module("hunting")
    states = runtime.agent_submodule_states("hunting", "r1")
    assert states == {
        "orchestrator": ModuleState.RUNNING,
        "hunter": ModuleState.RUNNING,
        "pod": ModuleState.RUNNING,
    }


# --- C2/C3: idempotent stop/start --------------------------------------------

def test_stop_and_start_are_idempotent_and_round_trip(runtime):
    runtime.register_module("hunting")
    assert runtime.stop_agent_submodule("hunting", "r1", "hunter") is ModuleState.PAUSED
    # a second stop is a no-op (one state, not two)
    assert runtime.stop_agent_submodule("hunting", "r1", "hunter") is ModuleState.PAUSED
    assert runtime.start_agent_submodule("hunting", "r1", "hunter") is ModuleState.RUNNING
    # a further start on a running role is a no-op
    assert runtime.start_agent_submodule("hunting", "r1", "hunter") is ModuleState.RUNNING


def test_stop_before_boot_registration_is_preserved(runtime):
    """E1 ordering: an operator stop landing before the bootstrap registers the
    run's roles must not be reset by the register (idempotent, state-preserving)."""
    runtime.register_module("hunting")
    runtime.stop_agent_submodule("hunting", "r1", "hunter")
    runtime.register_agent_submodule("hunting", "r1", "hunter")
    assert runtime.agent_submodule_state("hunting", "r1", "hunter") is ModuleState.PAUSED


# --- C4: unknown role is a named refusal -------------------------------------

def test_unknown_role_is_a_named_refusal_and_creates_no_handle(runtime):
    runtime.register_module("hunting")
    with pytest.raises(UnknownAgentSubmoduleRole):
        runtime.stop_agent_submodule("hunting", "r1", "sorcerer")
    with runtime._agent_lock:  # noqa: SLF001 - registry emptiness is the claim
        assert runtime._agent_submodules == {}


# --- C6: the role gate holds an in-flight unit and start releases it ---------

def test_role_gate_holds_in_flight_unit_and_start_releases(runtime):
    runtime.register_module("hunting")
    gate = runtime.agent_submodule_gate("hunting", "r1", "hunter")
    progress = []

    async def hunter_run():
        for i in range(1500):
            async with gate:
                progress.append(i)
                await asyncio.sleep(0.002)

    fut = runtime.schedule("hunting", hunter_run(), name="hunting:r1:hunt:a")
    _wait_until(lambda: len(progress) > 5, timeout=5)

    runtime.stop_agent_submodule("hunting", "r1", "hunter")
    _wait_until_flat(progress, timeout=5)
    frozen = len(progress)
    time.sleep(0.1)
    assert len(progress) == frozen  # held at its next unit boundary

    runtime.start_agent_submodule("hunting", "r1", "hunter")
    _wait_until(lambda: len(progress) > frozen, timeout=5)
    assert fut.result(timeout=15) is None


def test_two_concurrent_hunters_hold_and_resume_together(runtime):
    runtime.register_module("hunting")
    gate = runtime.agent_submodule_gate("hunting", "r1", "hunter")
    a, b = [], []

    async def hunter(progress):
        for i in range(1500):
            async with gate:
                progress.append(i)
                await asyncio.sleep(0.002)

    fut_a = runtime.schedule("hunting", hunter(a), name="hunting:r1:hunt:a")
    fut_b = runtime.schedule("hunting", hunter(b), name="hunting:r1:hunt:b")
    _wait_until(lambda: len(a) > 5 and len(b) > 5, timeout=5)

    runtime.stop_agent_submodule("hunting", "r1", "hunter")
    _wait_until_flat(a, timeout=5)
    _wait_until_flat(b, timeout=5)
    fa, fb = len(a), len(b)
    time.sleep(0.1)
    assert len(a) == fa and len(b) == fb  # both held

    runtime.start_agent_submodule("hunting", "r1", "hunter")
    _wait_until(lambda: len(a) > fa and len(b) > fb, timeout=5)
    assert fut_a.result(timeout=15) is None
    assert fut_b.result(timeout=15) is None


# --- C7: the module gate dominates the role gate -----------------------------

def test_module_pause_holds_the_role_gate(runtime):
    runtime.register_module("hunting")
    gate = runtime.agent_submodule_gate("hunting", "r1", "hunter")
    progress = []

    async def hunter_run():
        for i in range(1500):
            async with gate:
                progress.append(i)
                await asyncio.sleep(0.002)

    fut = runtime.schedule("hunting", hunter_run(), name="hunting:r1:hunt:a")
    _wait_until(lambda: len(progress) > 5, timeout=5)

    runtime.pause("hunting")  # the module gate dominates the role gate
    _wait_until_flat(progress, timeout=5)
    frozen = len(progress)
    time.sleep(0.1)
    assert len(progress) == frozen

    runtime.resume("hunting")
    _wait_until(lambda: len(progress) > frozen, timeout=5)
    assert fut.result(timeout=15) is None


# --- C8: a module drain settles the role handles -----------------------------

def test_module_drain_reaps_the_role_handles(runtime):
    runtime.register_module("hunting")
    runtime.agent_submodule_gate("hunting", "r1", "hunter")
    assert runtime.agent_submodule_state("hunting", "r1", "hunter") is ModuleState.RUNNING

    runtime.drain("hunting", timeout=5)

    assert runtime.state("hunting") is ModuleState.STOPPED
    with runtime._agent_lock:  # noqa: SLF001 - registry emptiness is the claim
        assert runtime._agent_submodules == {}


# --- per-session held read ---------------------------------------------------

def test_is_session_held_reports_the_hold_and_its_release(runtime):
    runtime.register_module("hunting")
    entered = threading.Event()

    async def run():
        gate = runtime.gate("hunting")
        for _ in range(2000):
            async with gate:
                entered.set()
                await asyncio.sleep(0.002)

    fut = runtime.schedule("hunting", run(), name="hunting:r1:hunt:a")
    assert entered.wait(timeout=5)
    assert runtime.is_session_held("hunting", "hunting:r1:hunt:a") is False

    runtime.hold_session("hunting", "hunting:r1:hunt:a")
    _wait_until(lambda: runtime.is_session_held("hunting", "hunting:r1:hunt:a"), timeout=5)
    runtime.resume_session("hunting", "hunting:r1:hunt:a")
    _wait_until(
        lambda: runtime.is_session_held("hunting", "hunting:r1:hunt:a") is False,
        timeout=5,
    )
    runtime.cancel_run("hunting", "hunting:r1:hunt:a")
    import concurrent.futures
    with pytest.raises(concurrent.futures.CancelledError):
        fut.result(timeout=15)

    assert runtime.is_session_held("hunting", "unknown-run") is False
