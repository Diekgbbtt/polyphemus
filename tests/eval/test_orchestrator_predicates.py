"""The phase-entry predicates (ticket #270, D13/D16).

Each predicate is an API/file read through injected seams; no LLM, no network.
A block names every missing prerequisite; a note is non-blocking (a single
failed recon job is note-and-continue).
"""
from __future__ import annotations

import pytest

from orchestrator import api, predicates
from orchestrator.files import (
    FileStore,
    authn_skill_path,
    hunt_configs_dir,
    hunter_test_specs_fault_dir,
)


class FakeApi:
    """A recording, ordered-match fake `ApiRunner` (the RecordingRunner shape)."""

    def __init__(self, routes: dict | None = None, default: dict | None = None):
        self.routes = routes or {}
        self.default = default
        self.calls: list = []

    def __call__(self, call):
        self.calls.append(call)
        key = f"{call.method} {call.path}"
        for needle, resp in self.routes.items():
            if needle in key:
                return resp
        if self.default is not None:
            return self.default
        raise AssertionError(f"unexpected call {key}")


PROJECT = "pid"


def _graph(services: int = 1, endpoints: int = 1, systems: int = 0) -> dict:
    nodes = [{"type": "L1Service"} for _ in range(services)]
    nodes += [{"type": "L1System"} for _ in range(systems)]
    nodes += [{"type": "Endpoint"} for _ in range(endpoints)]
    return {"nodes": nodes, "links": []}


def _present_project() -> dict:
    return {"projects": [{"project_id": PROJECT}]}


def _routed(**overrides) -> FakeApi:
    """Specific routes first, then the graph, then the project listing."""
    routes = dict(overrides)
    routes.setdefault("GET /projects/pid/graph", _graph())
    routes["GET /projects"] = _present_project()
    return FakeApi(routes)


# --- recon entry --------------------------------------------------------------


def test_recon_entry_permits_a_prepared_anonymous_project(tmp_path) -> None:
    state = predicates.PhaseState(project_id=PROJECT, target_seed="t.test")

    result = predicates.recon_entry(
        _routed(), FileStore(), state
    )

    assert result.ok
    assert result.blocks == ()


def test_recon_entry_blocks_when_the_project_is_unknown(tmp_path) -> None:
    api_runner = FakeApi({"GET /projects": {"projects": []}})
    state = predicates.PhaseState(project_id=PROJECT, target_seed="t.test")

    result = predicates.recon_entry(
        api_runner, FileStore(), state
    )

    assert not result.ok
    assert "project not found" in result.reason
    # No further reads once the project is absent.
    assert [c.display() for c in api_runner.calls] == ["GET /projects"]


def test_recon_entry_blocks_without_a_target_seed() -> None:
    state = predicates.PhaseState(project_id=PROJECT, target_seed=None)

    result = predicates.recon_entry(
        _routed(), FileStore(), state
    )

    assert not result.ok
    assert "target_seed" in result.reason


def test_recon_entry_blocks_without_an_l1_scaffold() -> None:
    api_runner = _routed(**{"GET /projects/pid/graph": _graph(services=0)})
    state = predicates.PhaseState(project_id=PROJECT, target_seed="t.test")

    result = predicates.recon_entry(
        api_runner, FileStore(), state
    )

    assert not result.ok
    assert "L1 scaffold" in result.reason


def test_recon_entry_blocks_an_auth_surface_without_the_authn_skill(tmp_path) -> None:
    files = FileStore()
    state = predicates.PhaseState(
        project_id=PROJECT,
        target_seed="t.test",
        auth_surface=True,
        data_root=tmp_path,
    )

    result = predicates.recon_entry(
        _routed(**{"GET /projects/pid/auth": {"overview": "sign in", "accounts": [{"name": "a"}]}}),
        files,
        state,
    )

    assert not result.ok
    assert "authn" in result.reason

    # The skill bundle at its designed location lifts the block.
    files.write_text(authn_skill_path(tmp_path, PROJECT), "# authn\n")
    result = predicates.recon_entry(
        _routed(**{"GET /projects/pid/auth": {"overview": "sign in", "accounts": [{"name": "a"}]}}),
        files,
        state,
    )
    assert result.ok


def test_recon_entry_blocks_an_auth_surface_without_overview_or_credentials(
    tmp_path,
) -> None:
    files = FileStore()
    files.write_text(authn_skill_path(tmp_path, PROJECT), "# authn\n")
    state = predicates.PhaseState(
        project_id=PROJECT,
        target_seed="t.test",
        auth_surface=True,
        data_root=tmp_path,
    )

    no_overview = predicates.recon_entry(
        _routed(**{"GET /projects/pid/auth": {"overview": None, "accounts": [{"name": "a"}]}}),
        files,
        state,
    )
    assert not no_overview.ok and "overview" in no_overview.reason

    no_credentials = predicates.recon_entry(
        _routed(**{"GET /projects/pid/auth": {"overview": "sign in", "accounts": []}}),
        files,
        state,
    )
    assert not no_credentials.ok and "credentials" in no_credentials.reason


def test_recon_entry_ignores_auth_state_without_a_declared_auth_surface(
    tmp_path,
) -> None:
    state = predicates.PhaseState(
        project_id=PROJECT, target_seed="t.test", auth_surface=False
    )
    api_runner = _routed()

    result = predicates.recon_entry(
        api_runner, FileStore(), state
    )

    assert result.ok
    # The auth read is never issued when no auth surface is declared.
    assert not any("/auth" in c.path for c in api_runner.calls)


def test_recon_entry_accumulates_every_independent_block() -> None:
    # Project and seed are independent: both are reported in the stable order
    # even though the project read fails first.
    api_runner = FakeApi({"GET /projects": {"projects": []}})
    state = predicates.PhaseState(project_id=PROJECT, target_seed=None)

    result = predicates.recon_entry(api_runner, FileStore(), state)

    assert not result.ok
    assert result.blocks == (
        f"project not found: {PROJECT}",
        "settings.target_seed is not set",
    )
    # A missing project skips the scaffold/auth reads (its dependent subtree).
    assert [c.display() for c in api_runner.calls] == ["GET /projects"]


def test_recon_entry_accumulates_the_auth_surface_blocks(tmp_path) -> None:
    files = FileStore()
    state = predicates.PhaseState(
        project_id=PROJECT,
        target_seed="t.test",
        auth_surface=True,
        data_root=tmp_path,
    )

    result = predicates.recon_entry(
        _routed(
            **{"GET /projects/pid/auth": {"overview": None, "accounts": []}}
        ),
        files,
        state,
    )

    assert not result.ok
    # Skill, overview, and credentials are all missing, in that order.
    assert len(result.blocks) == 3
    assert "authn" in result.blocks[0]
    assert "overview" in result.blocks[1]
    assert "credentials" in result.blocks[2]


# --- analysis entry -----------------------------------------------------------


def _recon_run(status="complete", jobs=None, stats=None) -> dict:
    return {
        "status": status,
        "per_job": jobs if jobs is not None else [{"job": "crawl", "status": "complete"}],
        "stats": stats or {"analysis_drained": True},
    }


def test_analysis_entry_permits_a_terminal_recon_with_a_surface() -> None:
    state = predicates.PhaseState(project_id=PROJECT, recon_run_id="r1")

    result = predicates.analysis_entry(
        _routed(**{"GET /projects/pid/recon/r1": _recon_run()}), FileStore(), state
    )

    assert result.ok


def test_analysis_entry_blocks_a_non_terminal_recon_run() -> None:
    state = predicates.PhaseState(project_id=PROJECT, recon_run_id="r1")

    result = predicates.analysis_entry(
        _routed(**{"GET /projects/pid/recon/r1": _recon_run(status="running")}),
        FileStore(),
        state,
    )

    assert not result.ok
    assert "not terminal" in result.reason


def test_analysis_entry_blocks_a_recon_run_with_no_job_rows() -> None:
    state = predicates.PhaseState(project_id=PROJECT, recon_run_id="r1")

    result = predicates.analysis_entry(
        _routed(**{"GET /projects/pid/recon/r1": _recon_run(jobs=[])}),
        FileStore(),
        state,
    )

    assert not result.ok
    assert "no job rows" in result.reason


def test_analysis_entry_blocks_when_l0_is_empty() -> None:
    state = predicates.PhaseState(project_id=PROJECT, recon_run_id="r1")

    result = predicates.analysis_entry(
        _routed(
            **{
                "GET /projects/pid/recon/r1": _recon_run(),
                "GET /projects/pid/graph": _graph(endpoints=0),
            }
        ),
        FileStore(),
        state,
    )

    assert not result.ok
    assert "L0" in result.reason


def test_analysis_entry_notes_a_single_failed_job_and_continues() -> None:
    """A single failed recon job is note-and-continue, never a block."""
    state = predicates.PhaseState(project_id=PROJECT, recon_run_id="r1")
    run = _recon_run(
        jobs=[
            {"job": "crawl", "status": "complete"},
            {"job": "content", "status": "failed"},
        ]
    )

    result = predicates.analysis_entry(
        _routed(**{"GET /projects/pid/recon/r1": run}), FileStore(), state
    )

    assert result.ok
    assert any("content" in note and "failed" in note for note in result.notes)


def test_recon_job_notes_names_every_failed_job() -> None:
    """I8: the shared helper the recon and analysis phases both use."""
    run = _recon_run(
        jobs=[
            {"job": "crawl", "status": "complete"},
            {"job": "content", "status": "failed"},
            {"job": "katana", "status": "failed"},
        ]
    )

    notes = predicates.recon_job_notes(run)

    assert len(notes) == 2
    assert any("content" in note for note in notes)
    assert any("katana" in note for note in notes)


def test_analysis_entry_accumulates_every_missing_prerequisite() -> None:
    state = predicates.PhaseState(project_id=PROJECT, recon_run_id="r1")
    run = _recon_run(status="running", jobs=[])

    result = predicates.analysis_entry(
        _routed(
            **{
                "GET /projects/pid/recon/r1": run,
                "GET /projects/pid/graph": _graph(endpoints=0),
            }
        ),
        FileStore(),
        state,
    )

    assert not result.ok
    # Non-terminal, no job rows, and empty L0 all report, in that order.
    assert len(result.blocks) == 3
    assert "not terminal" in result.blocks[0]
    assert "no job rows" in result.blocks[1]
    assert "L0" in result.blocks[2]


# --- hunting entry ------------------------------------------------------------


def test_hunting_entry_permits_when_analysis_drained() -> None:
    state = predicates.PhaseState(project_id=PROJECT, recon_run_id="r1")

    result = predicates.hunting_entry(
        _routed(**{"GET /projects/pid/recon/r1": _recon_run()}), FileStore(), state
    )

    assert result.ok


def test_hunting_entry_permits_when_l1_is_present_even_if_not_drained() -> None:
    state = predicates.PhaseState(project_id=PROJECT, recon_run_id="r1")
    run = _recon_run(stats={"analysis_drained": False})

    result = predicates.hunting_entry(
        _routed(**{"GET /projects/pid/recon/r1": run, "GET /projects/pid/graph": _graph()}),
        FileStore(),
        state,
    )

    assert result.ok


def test_hunting_entry_blocks_when_neither_drained_nor_l1() -> None:
    state = predicates.PhaseState(project_id=PROJECT, recon_run_id="r1")
    run = _recon_run(stats={"analysis_drained": False})

    result = predicates.hunting_entry(
        _routed(
            **{
                "GET /projects/pid/recon/r1": run,
                "GET /projects/pid/graph": _graph(services=0),
            }
        ),
        FileStore(),
        state,
    )

    assert not result.ok
    assert "drained" in result.reason or "L1" in result.reason


def test_hunting_entry_blocks_when_configured_premined_artifacts_are_absent(
    tmp_path,
) -> None:
    state = predicates.PhaseState(
        project_id=PROJECT,
        recon_run_id="r1",
        preloaded_configured=True,
        data_root=tmp_path,
    )

    result = predicates.hunting_entry(
        _routed(**{"GET /projects/pid/recon/r1": _recon_run()}), FileStore(), state
    )

    assert not result.ok
    assert "pre-mined" in result.reason

    produced = hunt_configs_dir(tmp_path, PROJECT, "produced")
    FileStore().write_text(produced / "unit_CWE-1_x.yaml", "id: x\n")
    result = predicates.hunting_entry(
        _routed(**{"GET /projects/pid/recon/r1": _recon_run()}), FileStore(), state
    )
    assert result.ok


def test_hunting_entry_accepts_premined_test_specs_present(tmp_path) -> None:
    # A setup that pre-mines only test specs must still pass the gate: presence
    # counts both the hunt-config and the test-spec produced/consumed inboxes.
    state = predicates.PhaseState(
        project_id=PROJECT,
        recon_run_id="r1",
        preloaded_configured=True,
        data_root=tmp_path,
    )

    result = predicates.hunting_entry(
        _routed(**{"GET /projects/pid/recon/r1": _recon_run()}), FileStore(), state
    )
    assert not result.ok

    spec_dir = hunter_test_specs_fault_dir(tmp_path, PROJECT, "fault-a", "produced")
    FileStore().write_text(spec_dir / "s.yaml", "id: s\n")
    result = predicates.hunting_entry(
        _routed(**{"GET /projects/pid/recon/r1": _recon_run()}), FileStore(), state
    )
    assert result.ok


def test_hunting_entry_accumulates_the_drain_and_premined_blocks(tmp_path) -> None:
    state = predicates.PhaseState(
        project_id=PROJECT,
        recon_run_id="r1",
        preloaded_configured=True,
        data_root=tmp_path,
    )
    run = _recon_run(stats={"analysis_drained": False})

    result = predicates.hunting_entry(
        _routed(
            **{
                "GET /projects/pid/recon/r1": run,
                "GET /projects/pid/graph": _graph(services=0, endpoints=0),
            }
        ),
        FileStore(),
        state,
    )

    assert not result.ok
    assert len(result.blocks) == 2
    assert "drained" in result.blocks[0] or "L1" in result.blocks[0]
    assert "pre-mined" in result.blocks[1]
