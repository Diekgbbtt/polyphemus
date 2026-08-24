"""T5: the singular-launch launcher seams at the runtime tier - enqueue hunt
configs / test specs into the per-project produced families and the
orchestrator-only pass (tracker #174; spec #169 "Singular component launches";
ADR #169 Q4/Q6).

The seams are asserted directly through temp-root stores, no live run and no
live control plane: an enqueued config comes back RATIFIED (the mover's
hunter-dispatch gate), an enqueued spec comes back SPECIFIED (the mover's
pod-dispatch gate), a replay of the same identity raises the storage novelty
gate (the server-side at-most-once marker), and the orchestrator-only pass
consumes its candidate batch under the run's module context. No LLM, no DB,
no process.
"""
from __future__ import annotations

import asyncio

import pytest

from polymerhus.attack.hunting import runtime as hunting_runtime
from polymerhus.attack.hunting.hunt_orchestrator import (
    HuntConfig,
    HuntPromptTemplate,
    OrchestratorReport,
)
from polymerhus.attack.hunting.hunt_store import (
    DuplicateConfigError,
    HuntStore,
)
from polymerhus.attack.hunting.hunter_memory import (
    DuplicateSpecError,
    HunterMemoryStore,
)

UNIT = "Service:slug:a"
FAULT = "fault-x"
CLASS = "CSRF"
FAULT_KEY = f"{UNIT}::{FAULT}::{CLASS}"
RUN = "orchestrator-only-run"


def _config() -> HuntConfig:
    return HuntConfig(
        hunt_id=UNIT,
        unit_id=UNIT,
        fault_class=FAULT,
        vulnerability_class=CLASS,
        prompt_template=HuntPromptTemplate(
            rationale="r", research_direction="rd",
        ),
    )


def test_enqueue_hunt_forces_ratified_and_round_trips_as_dispatchable(tmp_path):
    store = HuntStore(tmp_path / "hunts")

    key = hunting_runtime.enqueue_hunt_config("p1", _config(), hunt_store=store)

    assert key == f"{UNIT}::{FAULT}::{CLASS}"
    produced = store.read_produced_configs("p1")
    assert [k for k, _n in produced] == [key]
    # the persisted body round-trips as a model-valid RATIFIED config - exactly
    # what the surfer's `build_run_dispatch` dispatches a hunter for
    body = store.read_configs_by_key("p1", key)[0]
    assert body["status"] == "ratified"
    assert HuntConfig.model_validate(body).status == "ratified"


def test_enqueue_hunt_replay_refused_by_the_novelty_gate(tmp_path):
    store = HuntStore(tmp_path / "hunts")
    hunting_runtime.enqueue_hunt_config("p1", _config(), hunt_store=store)

    with pytest.raises(DuplicateConfigError):
        hunting_runtime.enqueue_hunt_config("p1", _config(), hunt_store=store)
    assert len(store.read_produced_configs("p1")) == 1  # nothing double-written


def test_enqueue_spec_forces_specified_and_round_trips_as_dispatchable(tmp_path):
    store = HunterMemoryStore(tmp_path / "hunter")

    stem = hunting_runtime.enqueue_test_spec(
        "p1",
        fault_key=FAULT_KEY,
        fault_keyword="sqli",
        strategy_keyword="blind",
        spec={"target_identity": "http://target/"},
        hunter_store=store,
    )

    assert stem == "sqli_blind"
    assert store.produced_spec_files("p1", FAULT_KEY) == ["sqli_blind"]
    body = store.read_spec(
        "p1", FAULT_KEY, fault_keyword="sqli", strategy_keyword="blind",
        side="produced",
    )
    # the mover's pod-dispatch gate (`status == "specified"`) is set
    assert body is not None and body["status"] == "specified"


def test_enqueue_spec_replay_refused_by_the_novelty_gate(tmp_path):
    store = HunterMemoryStore(tmp_path / "hunter")
    hunting_runtime.enqueue_test_spec(
        "p1", fault_key=FAULT_KEY,
        fault_keyword="sqli", strategy_keyword="blind",
        spec={}, hunter_store=store,
    )

    with pytest.raises(DuplicateSpecError):
        hunting_runtime.enqueue_test_spec(
            "p1", fault_key=FAULT_KEY,
            fault_keyword="sqli", strategy_keyword="blind",
            spec={}, hunter_store=store,
        )
    assert store.produced_spec_files("p1", FAULT_KEY) == ["sqli_blind"]


def _empty_report():
    return OrchestratorReport(pairs_processed=1)


def test_launch_orchestrator_drives_the_pass_under_the_module_context(tmp_path):
    """The orchestrator-only coroutine drives ONE pass under the hunting module
    context with no surfer and no run row: the injected pass body runs and
    returns its report. The launch succeeds without any control plane (the
    coroutine is what the launcher seam schedules)."""
    hunt_store = HuntStore(tmp_path / "hunts")
    reports: list[tuple[str, str]] = []

    async def _pass(project_id, run_id, candidates, tools, **kw):
        reports.append((project_id, run_id))
        return _empty_report()

    asyncio.run(hunting_runtime.launch_orchestrator(
        "p1", run_id=RUN, candidates=[], hunt_store=hunt_store,
        orchestrator_fn=_pass,
    ))

    assert reports == [("p1", RUN)]
    # no run row was opened or written by the pass (no pg accessors touched)
    assert not hunt_store.read_produced_configs("p1")


def test_launch_orchestrator_never_raises_through_the_control_plane(tmp_path):
    """Fail-open: a degraded pass (its body raises) is logged, the coroutine
    returns normally - the singular launch never 500s the caller."""
    hunt_store = HuntStore(tmp_path / "hunts")

    async def _exploding_pass(project_id, run_id, candidates, tools, **kw):
        raise RuntimeError("pass degraded")

    asyncio.run(hunting_runtime.launch_orchestrator(
        "p1", run_id=RUN, candidates=[], hunt_store=hunt_store,
        orchestrator_fn=_exploding_pass,
    ))