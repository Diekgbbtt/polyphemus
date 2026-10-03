"""The phase-entry predicates (ticket #270, D5/D13/D16).

Each predicate is an API/file read through injected seams - no LLM, no
network, no live stack. A phase is entered only when every documented
prerequisite is present; each missing one is named in `GateResult.blocks`. A
`GateResult.notes` entry is a recorded, non-blocking observation (a single
failed recon job is note-and-continue).

Import performs no I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from orchestrator import api
from orchestrator.files import (
    FileStore,
    authn_skill_path,
    hunt_configs_dir,
    hunter_test_specs_dir,
)


@dataclass(frozen=True)
class GateResult:
    """The outcome of one phase-entry check.

    `ok` is the permit/block decision; `blocks` names every missing
    prerequisite (all of them, so one gate call reports the full work list);
    `notes` are non-blocking observations to record.
    """

    ok: bool
    blocks: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def reason(self) -> str:
        return "; ".join(self.blocks)


@dataclass(frozen=True)
class PhaseState:
    """The persisted state a predicate reads about one trial's project.

    `target_seed` is the settings value the trial applied (the settings blob
    carries no read endpoint; the trial is its writer). `auth_surface` is the
    declared auth surface from the target config; `recon_run_id` is the run a
    later phase drains; `preloaded_configured` marks a trial that declared
    pre-mined artifacts; `data_root` anchors the on-disk reads. `seeded` marks a
    trial hunting against a pre-recon'd project (#277): its L1 is transferred in
    and the settings/scaffold were the operator's, so the hunting gate asserts
    the project and the L1 service count instead of the drain.
    """

    project_id: str
    target_seed: str | None = None
    auth_surface: bool = False
    recon_run_id: str | None = None
    preloaded_configured: bool = False
    data_root: Path | None = None
    seeded: bool = False


def recon_entry(
    api_runner: api.ApiRunner,
    files: FileStore,
    state: PhaseState,
) -> GateResult:
    """Recon entry (D13): project, seed, L1 scaffold, and - when the target
    declares an auth surface - the project `authn` skill and the seeded
    `AuthContext` (overview AND credentials).

    Reachability is NOT re-verified here: the target shares a Docker network that
    egresses to the underlying host and reaches loopback, and its readiness was
    already asserted by the stack's own health check (`orchestrator/readiness.py`),
    so a runtime kali probe would only duplicate that gate.

    Every missing prerequisite is accumulated in a stable order (project ->
    settings -> scaffold -> authn skill -> overview -> credentials) so one gate
    call reports the full work list. The scaffold and auth reads are only issued
    when the project exists; a missing project already reports the whole
    dependent subtree.
    """
    blocks: list[str] = []
    projects = api_runner(api.list_projects())
    project_known = state.project_id in api.project_ids(projects)
    if not project_known:
        blocks.append(f"project not found: {state.project_id}")

    if not state.target_seed:
        blocks.append("settings.target_seed is not set")

    if project_known:
        graph = api_runner(api.project_graph(state.project_id))
        if api.graph_counts(graph).services <= 0:
            blocks.append("L1 scaffold incomplete: 0 services")

    if state.auth_surface:
        if state.data_root is None:
            blocks.append("auth surface declared but no data root is configured")
        else:
            if not files.exists(authn_skill_path(state.data_root, state.project_id)):
                blocks.append(
                    "auth surface declared but project 'authn' skill is missing "
                    f"for {state.project_id}"
                )
            if project_known:
                auth = api_runner(api.read_auth(state.project_id))
                if not _seeded(auth.get("overview")):
                    blocks.append(
                        "auth surface declared but AuthContext overview is not seeded"
                    )
                if not auth.get("accounts"):
                    blocks.append(
                        "auth surface declared but AuthContext credentials are not seeded"
                    )

    if blocks:
        return GateResult(False, tuple(blocks))
    return GateResult(True)


def analysis_entry(
    api_runner: api.ApiRunner, files: FileStore, state: PhaseState
) -> GateResult:
    """Analysis entry: the recon run is terminal with job rows and L0 > 0.

    A single failed recon job is note-and-continue: the job is recorded, never
    a block. A run with no job rows is a failed run (the liveness gate), not an
    empty finding, so it blocks. Every missing prerequisite is accumulated in
    the stable order run -> terminal -> rows -> L0.
    """
    blocks: list[str] = []
    if not state.recon_run_id:
        return GateResult(False, ("analysis entry requires a recon run",))

    run = api_runner(api.recon_status(state.project_id, state.recon_run_id))
    status = api.status_of(run)
    if not api.recon_terminal(status):
        blocks.append(f"recon run not terminal: {status or 'unknown'}")

    jobs = api.per_job_rows(run)
    if not jobs:
        blocks.append("recon run has no job rows")

    graph = api_runner(api.project_graph(state.project_id))
    if api.graph_counts(graph).l0 <= 0:
        blocks.append("L0 count is zero")

    notes = recon_job_notes(run)
    if blocks:
        return GateResult(False, tuple(blocks), notes=notes)
    return GateResult(True, notes=notes)


def recon_job_notes(run: Mapping | None) -> tuple[str, ...]:
    """A note per failed recon job (note-and-continue).

    I8: shared by the analysis-entry gate and the trial's recon phase, so a
    single failed job in a full recon run is recorded as a partial-surface
    marker rather than being dropped.
    """
    return tuple(
        f"recon job {job.get('job')} failed (note-and-continue)"
        for job in api.per_job_rows(run)
        if job.get("status") == "failed"
    )


def hunting_entry(
    api_runner: api.ApiRunner, files: FileStore, state: PhaseState
) -> GateResult:
    """Hunting entry: analysis drained (or L1 present) and, when configured,
    the pre-mined artifacts are in place.

    The two prerequisites are accumulated in order (drained/L1 -> pre-mined).
    A seeded trial (#277) instead asserts the reused project exists and its L1
    carries services - the operator's transferred scaffold is the entry signal,
    there is no drain to read - and never reads the graph of a missing project.
    """
    blocks: list[str] = []
    project_known = True
    if state.seeded:
        projects = api_runner(api.list_projects())
        project_known = state.project_id in api.project_ids(projects)
        if not project_known:
            blocks.append(f"seeded project not found: {state.project_id}")

    if project_known:
        graph = api_runner(api.project_graph(state.project_id))
        counts = api.graph_counts(graph)
        if state.seeded:
            # The scaffold-presence signal is the service count, exactly as the
            # recon-entry gate reads it; a seeded L1 with zero services is not a
            # hunting entry.
            if counts.services <= 0:
                blocks.append("seeded project L1 is incomplete: 0 services")
        else:
            drained = False
            if state.recon_run_id:
                run = api_runner(api.recon_status(state.project_id, state.recon_run_id))
                drained = bool(((run or {}).get("stats") or {}).get("analysis_drained"))
            if not drained and counts.l1 <= 0:
                blocks.append("analysis not drained and no L1 surface present")

    if state.preloaded_configured:
        if state.data_root is None:
            blocks.append("pre-mined hunting artifacts configured but no data root is set")
        else:
            # Presence counts both artifact families: pre-mined hunt configs and
            # each fault key's hunter test specs (a setup may pre-mine either).
            present = sum(
                files.count_files(hunt_configs_dir(state.data_root, state.project_id, side))
                for side in ("produced", "consumed")
            )
            specs_root = hunter_test_specs_dir(state.data_root, state.project_id)
            for fault_dir in files.list_dirs(specs_root):
                for side in ("produced", "consumed"):
                    present += files.count_files(fault_dir / side)
            if present == 0:
                blocks.append("pre-mined hunting artifacts configured but not present")

    if blocks:
        return GateResult(False, tuple(blocks))
    return GateResult(True)


def _seeded(value: object) -> bool:
    """True when an AuthContext section carries content (a bare-map overview or
    a non-empty credentials section)."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return bool(value)
    return bool(value)
