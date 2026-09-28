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
from typing import Callable, Mapping

from orchestrator import api
from orchestrator.files import FileStore, authn_skill_path, hunt_configs_dir


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
    pre-mined artifacts; `data_root` anchors the on-disk reads.
    """

    project_id: str
    target_seed: str | None = None
    auth_surface: bool = False
    recon_run_id: str | None = None
    preloaded_configured: bool = False
    data_root: Path | None = None


def recon_entry(
    api_runner: api.ApiRunner,
    files: FileStore,
    state: PhaseState,
    *,
    reachable: Callable[[], bool],
) -> GateResult:
    """Recon entry (D13): project, seed, L1 scaffold, reachability, and - when
    the target declares an auth surface - the project `authn` skill and the
    seeded `AuthContext` (overview AND credentials)."""
    projects = api_runner(api.list_projects())
    if state.project_id not in api.project_ids(projects):
        return GateResult(False, (f"project not found: {state.project_id}",))

    if not state.target_seed:
        return GateResult(False, ("settings.target_seed is not set",))

    graph = api_runner(api.project_graph(state.project_id))
    if api.graph_counts(graph).services <= 0:
        return GateResult(False, ("L1 scaffold incomplete: 0 services",))

    if not reachable():
        return GateResult(False, ("target not reachable from kali",))

    if state.auth_surface:
        if state.data_root is None:
            return GateResult(
                False, ("auth surface declared but no data root is configured",)
            )
        if not files.exists(authn_skill_path(state.data_root, state.project_id)):
            return GateResult(
                False,
                (f"auth surface declared but project 'authn' skill is missing for {state.project_id}",),
            )
        auth = api_runner(api.read_auth(state.project_id))
        if not _seeded(auth.get("overview")):
            return GateResult(
                False, ("auth surface declared but AuthContext overview is not seeded",)
            )
        if not auth.get("accounts"):
            return GateResult(
                False, ("auth surface declared but AuthContext credentials are not seeded",)
            )

    return GateResult(True)


def analysis_entry(
    api_runner: api.ApiRunner, files: FileStore, state: PhaseState
) -> GateResult:
    """Analysis entry: the recon run is terminal with job rows and L0 > 0.

    A single failed recon job is note-and-continue: the job is recorded, never
    a block. A run with no job rows is a failed run (the liveness gate), not an
    empty finding, so it blocks.
    """
    if not state.recon_run_id:
        return GateResult(False, ("analysis entry requires a recon run",))

    run = api_runner(api.recon_status(state.project_id, state.recon_run_id))
    status = api.status_of(run)
    if not api.recon_terminal(status):
        return GateResult(False, (f"recon run not terminal: {status or 'unknown'}",))

    jobs = api.per_job_rows(run)
    if not jobs:
        return GateResult(False, ("recon run has no job rows",))

    graph = api_runner(api.project_graph(state.project_id))
    if api.graph_counts(graph).l0 <= 0:
        return GateResult(False, ("L0 count is zero",))

    notes = tuple(
        f"recon job {job.get('job')} failed (note-and-continue)"
        for job in jobs
        if job.get("status") == "failed"
    )
    return GateResult(True, notes=notes)


def hunting_entry(
    api_runner: api.ApiRunner, files: FileStore, state: PhaseState
) -> GateResult:
    """Hunting entry: analysis drained (or L1 present) and, when configured,
    the pre-mined artifacts are in place."""
    graph = api_runner(api.project_graph(state.project_id))
    counts = api.graph_counts(graph)

    drained = False
    if state.recon_run_id:
        run = api_runner(api.recon_status(state.project_id, state.recon_run_id))
        drained = bool(((run or {}).get("stats") or {}).get("analysis_drained"))

    if not drained and counts.l1 <= 0:
        return GateResult(
            False, ("analysis not drained and no L1 surface present",)
        )

    if state.preloaded_configured:
        if state.data_root is None:
            return GateResult(
                False, ("pre-mined hunting artifacts configured but no data root is set",)
            )
        present = sum(
            files.count_files(hunt_configs_dir(state.data_root, state.project_id, side))
            for side in ("produced", "consumed")
        )
        if present == 0:
            return GateResult(
                False, ("pre-mined hunting artifacts configured but not present",)
            )

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
