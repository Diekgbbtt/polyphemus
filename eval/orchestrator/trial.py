"""The trial engine: phase entry, chaining, launch/poll, and the hunting cap.

A `Trial` drives one `TargetRun` on one instance from a phase entry to
terminal: bootstrap the project (settings, `AuthContext`, L1 scaffold,
pre-mined artifacts), gate the phase on persisted state, launch it, and poll
within a budget. The setup outcome chains into execution: a configuration-layer
failure gets one bounded repair and a retry, anything else escalates (D28).

Every effect is injected - the REST `ApiRunner`, the `FileStore` filesystem
seam, the #269 `CommandRunner`, and the clock - so the engine is exercised
without a live stack. Import performs no I/O.
"""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from orchestrator import api, instances, predicates, routing, subagents
from orchestrator.commands import Command, CommandRunner, require_ok
from orchestrator.files import (
    FileStore,
    authn_skill_path,
    hunt_configs_dir,
    hunter_test_specs_fault_dir,
)
from orchestrator.ids import short_id
from orchestrator.instances import InstanceError, InstancePaths
from orchestrator.predicates import GateResult
from orchestrator.setup import PreloadedArtifacts
from orchestrator.workitems import WorkItemGateError

CONFIGURATION = "configuration"
ESCALATE = "escalate"
# A phase terminal that names a failure stops the trial; it never chains into
# the next phase (P8). Recon `failed`, hunting `failed`/`interrupted`, and an
# analysis consumer that died (`interrupted`) all qualify.
FAILED_TERMINALS = frozenset({"failed", "interrupted"})


class TrialError(RuntimeError):
    """The trial was asked to execute without one of its injected seams."""


class EscalationError(RuntimeError):
    """A setup failure with no bounded configuration-layer repair (D28)."""

    def __init__(self, failure: "FailureClass", *, retried: bool = False) -> None:
        suffix = ", retried once" if retried else ""
        super().__init__(f"setup failed ({failure.layer}{suffix}): {failure.detail}")
        self.failure = failure
        self.retried = retried


@dataclass(frozen=True)
class FailureClass:
    """The classification of a bring-up failure and its bounded repair."""

    layer: str
    repair: str | None
    detail: str


def classify_failure(error: BaseException) -> FailureClass:
    """Classify a setup outcome.

    Configuration-layer: the instance stack (a missing/invalid `.env` key the
    preflight fills, or a service that did not come up) and a required work
    item whose content is missing. Everything else - the target application, an
    unknown error - escalates; no codebase repair is ever attempted (D28).
    """
    if isinstance(error, WorkItemGateError):
        return FailureClass(CONFIGURATION, "work_items", str(error))
    if isinstance(error, InstanceError):
        text = str(error)
        repair = "env" if ("env_preflight" in text or ".env" in text) else "stack"
        return FailureClass(CONFIGURATION, repair, text)
    return FailureClass(ESCALATE, None, f"{type(error).__name__}: {error}")


class RepairKit(Protocol):
    """The bounded, configuration-layer-only repairs the chain may apply."""

    def supports(self, repair: str) -> bool: ...

    def apply(self, repair: str) -> None: ...


class _NullRepair:
    def supports(self, repair: str) -> bool:
        return False

    def apply(self, repair: str) -> None:  # pragma: no cover - never reached
        raise TrialError(f"no repair kit supports {repair!r}")


@dataclass
class InstanceRepair:
    """Re-apply the per-instance preflight/render or recreate the stack.

    Both are the #269 effect seams, bounded to configuration: the preflight
    fills a missing `.env` key, the stack recreate re-runs worktree/preflight/
    render/`compose up`. No source is touched.
    """

    paths: InstancePaths
    runner: CommandRunner

    def supports(self, repair: str) -> bool:
        return repair in ("env", "stack")

    def apply(self, repair: str) -> None:
        if repair == "env":
            for command in (instances.plan_preflight(self.paths), instances.plan_render(self.paths)):
                require_ok(self.runner(command), command, error=InstanceError)
            return
        if repair == "stack":
            instances.up(self.paths, self.runner)
            return
        raise InstanceError(f"unsupported repair: {repair!r}")


@dataclass(frozen=True)
class ScaffoldSpec:
    """How to run the deterministic L1 scaffold for a freshly-created project."""

    cwd: str
    kb: str
    script: str = "eval/scaffold.py"
    pythonpath: str = "src"
    env: Mapping[str, str] | None = None


def plan_scaffold(spec: ScaffoldSpec, project_id: str) -> Command:
    """`python3 eval/scaffold.py <project> --kb <kb>` with `src` and the repo root
    (`spec.cwd`) on the path: the scaffold imports both `polymerhus` (under
    `src`) and `db` (at the repo root, for `db.neo4j.init_schema`)."""
    pythonpath = os.pathsep.join((spec.pythonpath, str(spec.cwd)))
    env = {"PYTHONPATH": pythonpath, **(dict(spec.env) if spec.env else {})}
    return Command(
        argv=("python3", spec.script, project_id, "--kb", spec.kb),
        cwd=spec.cwd,
        env=env,
        description=f"scaffold L1 for {project_id}",
    )


def front_url(config: TrialConfig) -> str:
    """The trial's target front URL: the synthetic Host on the standard port."""
    host = routing.synthetic_host(f"{config.instance_id}/{config.target_id}")
    return f"http://{host}/"


@dataclass(frozen=True)
class TrialConfig:
    """One trial's knobs: the target, the phase entry, and the run budget."""

    instance_id: str
    target_id: str
    start_phase: str = "recon"
    project_name: str | None = None
    target_seed: str | None = None
    operator_kb: str | None = None
    auth: Mapping[str, object] | None = None
    auth_surface: bool = False
    preloaded_hunting_artifacts: PreloadedArtifacts | None = None
    hunt_config_budget: int | None = None
    # The trial-scoped cap baseline: the consumed-config names already present
    # when this trial started. None means "snapshot it at the first hunting
    # poll" (a fresh trial); a resumed trial carries its record's baseline so
    # its count continues rather than resetting on the prior run's configs.
    cap_baseline: Sequence[str] | None = None
    # The trial-wide token budget and its carried baseline, sibling to the cap:
    # None budget means no usage call at all; None baseline means "snapshot the
    # project total at the first check", a resumed trial carries its own.
    token_budget: int | None = None
    spend_baseline: int | None = None
    data_root: Path = Path("data")
    runs_root: Path = Path("eval/runs")
    trial_id: str | None = None
    # The target-run this trial belongs to (the artifact-store middle level,
    # #273). Defaults to the instance id: one instance evaluates one target run.
    target_run_id: str | None = None
    with_analysis: bool = True
    scaffold: ScaffoldSpec | None = None
    budget_s: float = 7200.0
    poll_s: float = 15.0
    # Resume: reuse an existing project and/or drain an existing recon run.
    project_id: str | None = None
    recon_run_id: str | None = None
    # #277: hunt against a pre-recon'd project whose L0/L1 already exists. Set
    # means the trial skips project creation, settings, the auth mutation, and
    # the L1 scaffold, asserts the project and its L1, and enters at hunting.
    existing_project_id: str | None = None
    # D32: the version identity stamped into the trial record and the verdicts.
    eval_sha: str | None = None
    stack_fingerprint: str | None = None
    # The trace id this trial ran under, when one was recorded; the
    # assessment/diagnoser dispatches substitute it into `{trace_id}`. No
    # production reasoning source consumes it yet (designed-not-built, I4).
    trace_id: str | None = None
    # #275: a surfer intervention note stamped into the record when this trial
    # resumes a failed one at its recorded phase.
    intervention: str | None = None


@dataclass
class PhaseRecord:
    """One phase's entry decision and run outcome."""

    phase: str
    entered: bool = False
    status: str | None = None
    run_id: str | None = None
    # The run id the phase's stop verb expects, when it differs from `run_id`
    # (the analysis stop is keyed by the recon run id, not the consumer id).
    # The surfer names this id so its terminate is not a silent no-op.
    stop_run_id: str | None = None
    blocks: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Why the phase failed (a failed terminal, or a `complete` run whose
    # liveness check found no job rows / every job failed); None when healthy.
    failure: str | None = None


@dataclass
class PollResult:
    """A hunting poll's terminal outcome, including any cap stop."""

    status: str
    stop_count: int | None = None
    final_count: int | None = None
    overshoot: int | None = None


@dataclass(frozen=True)
class SpendResult:
    """A token-budget stop: the trial spend, the overshoot, and the breakdown."""

    spent: int
    overshoot: int
    by_agent: dict


@dataclass
class AssessmentAttempt:
    """One assessment dispatch or verification attempt (#271/D15)."""

    attempt: int
    outcome: str
    detail: str | None = None
    at: str | None = None


@dataclass
class AssessmentRecord:
    """The trial's assessment outcome and its full attempt history (#271/D6).

    Present from the first dispatch (`status="dispatched"`); rewritten by the
    eval-close verification phase to `present`, or `escalated` with a named
    failure. The attempt list is append-only across both.
    """

    status: str
    attempts: list[AssessmentAttempt] = field(default_factory=list)
    verdicts_path: str | None = None
    failure: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DiagnosisAttempt:
    """One diagnoser dispatch or pairing-verification attempt (#272/D19)."""

    attempt: int
    outcome: str
    detail: str | None = None
    at: str | None = None


@dataclass
class DiagnosisRecord:
    """The trial's diagnosis outcome and its full attempt history (#272/D19).

    Present from the first dispatch (`status="dispatched"`); rewritten by the
    eval-close pairing check to `present`, `not_required` (every verdict was
    `identified`), or `escalated` with a named failure. `entries_written`,
    `issues_matched`, and `issues_proposed` are the counts the close-verify
    reader observed in `diagnoses.yaml`.
    """

    status: str
    attempts: list[DiagnosisAttempt] = field(default_factory=list)
    diagnoses_path: str | None = None
    entries_written: int = 0
    issues_matched: int = 0
    issues_proposed: int = 0
    failure: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TrialRecord:
    """The persisted trial record (ids, phases, timings, cap, assessment, diagnosis).

    `eval_sha`/`stack_fingerprint`/`assessment` (#271) and `diagnosis` (#272)
    are additive and default to None, so a #270 record still loads and an old
    record remains readable.
    """

    trial_id: str
    instance_id: str
    target_id: str
    project_id: str
    start_phase: str
    terminal: str
    phases: list[PhaseRecord]
    started_at: str
    finished_at: str
    cap: int | None = None
    stop_count: int | None = None
    final_count: int | None = None
    overshoot: int | None = None
    # The trial-scoped cap baseline this trial counted against (the consumed
    # config names already present at its first poll, or the resumed trial's
    # carried-over baseline). Persisted so a resume keeps counting from it; a
    # new trial id snapshots a fresh one. Additive, defaults None, old records
    # still load.
    cap_baseline: list[str] | None = None
    # The trial-wide token budget and its outcome: the sum spent against the
    # carried baseline, the tokens spent past the bound (the post-stop re-read),
    # and the per-agent breakdown. Additive, default None, old records load.
    token_budget: int | None = None
    spent_tokens: int | None = None
    spend_overshoot: int | None = None
    spend_baseline: int | None = None
    spend_by_agent: dict | None = None
    notes: list[str] = field(default_factory=list)
    trial_dir: str | None = None
    # #273: the target-run grouping level of the artifact store (defaults to
    # the instance id when the trial did not name one).
    target_run_id: str | None = None
    # #277: True when the trial hunted against a reused project; the reused id
    # is `project_id` itself. Additive, defaults False, so older records load.
    seeded: bool = False
    # D32/D37: the version identity the trial ran on, and the assessment state.
    eval_sha: str | None = None
    stack_fingerprint: str | None = None
    # The trial's trace id, when one was recorded; the assessment and
    # diagnosis requests substitute it into `{trace_id}`.
    trace_id: str | None = None
    assessment: AssessmentRecord | None = None
    # D19/D20 (#272): the diagnosis state, paired with verdicts after assessment.
    diagnosis: DiagnosisRecord | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class TrialPlanStep:
    """One labelled group of planned API calls, file writes, or commands."""

    label: str
    calls: tuple[api.ApiCall, ...] = ()
    commands: tuple[Command, ...] = ()
    files: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class TrialPlan:
    """The ordered, effect-free plan of a trial."""

    steps: tuple[TrialPlanStep, ...]


class Trial:
    """One trial: bootstrap, phase entry, launch/poll, cap, and the record."""

    def __init__(
        self,
        config: TrialConfig,
        *,
        api_runner: api.ApiRunner | None = None,
        files: FileStore | None = None,
        runner: CommandRunner | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
        now: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self._api = api_runner
        self._files = files or FileStore()
        self._runner = runner
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._now = now or subagents.utcnow
        # The trial-scoped cap baseline. A resumed trial arrives with one on the
        # config; a fresh trial has none and snapshots it at its first poll.
        self._cap_baseline: tuple[str, ...] | None = (
            tuple(config.cap_baseline) if config.cap_baseline is not None else None
        )
        # The trial-wide token baseline: a resumed trial carries one on the
        # config; a fresh trial snapshots the project total at its first check.
        self._spend_baseline: int | None = config.spend_baseline
        self._spend: SpendResult | None = None

    # --- plan mode ------------------------------------------------------------

    def plan(self) -> TrialPlan:
        """Print every call, file write, and command without reading anything."""
        cfg = self.config
        seeded = cfg.existing_project_id is not None
        project = cfg.existing_project_id or cfg.project_id or "<project>"
        steps: list[TrialPlanStep] = []
        if seeded:
            # #277: a seeded trial creates nothing and mutates nothing; the plan
            # shows only its entry assertions (the project listing and graph).
            steps.append(
                TrialPlanStep(
                    "seeded project reuse",
                    calls=(api.list_projects(), api.project_graph(project)),
                    note=(
                        f"reuse project {project}; require L1 services > 0 "
                        "(no project/settings/scaffold)"
                    ),
                )
            )
        else:
            if cfg.project_id is None:
                steps.append(
                    TrialPlanStep(
                        "project",
                        calls=(api.create_project(cfg.project_name or f"eval-{cfg.target_id}"),),
                    )
                )
            settings: dict = {}
            if cfg.target_seed:
                settings["target_seed"] = cfg.target_seed
            if cfg.operator_kb:
                settings["operator_kb"] = f"<file:{cfg.operator_kb}>"
            if settings:
                steps.append(
                    TrialPlanStep("settings", calls=(api.put_settings(project, settings),))
                )
            if cfg.auth_surface:
                steps.append(
                    TrialPlanStep(
                        "auth (AuthContext)",
                        calls=(api.seed_auth(project, overview="<overview>", accounts="<accounts>"),),
                    )
                )
                if (cfg.auth or {}).get("authn_skill"):
                    steps.append(
                        TrialPlanStep(
                            "authn skill",
                            files=(str(authn_skill_path(cfg.data_root, project)),),
                        )
                    )
            if cfg.scaffold is not None:
                steps.append(
                    TrialPlanStep(
                        "L1 scaffold", commands=(plan_scaffold(cfg.scaffold, project),)
                    )
                )
        if cfg.preloaded_hunting_artifacts is not None:
            steps.append(
                TrialPlanStep(
                    "pre-mined hunting artifacts",
                    files=_premined_inboxes(cfg, project),
                )
            )
        if cfg.start_phase == "recon":
            steps.append(
                TrialPlanStep(
                    "recon entry + launch",
                    calls=(api.launch_recon(project, with_analysis=cfg.with_analysis),),
                    note=f"poll recon to terminal (budget {cfg.budget_s:g}s)",
                )
            )
        elif cfg.start_phase == "analysis":
            steps.append(
                TrialPlanStep(
                    "analysis entry + launch",
                    calls=(api.launch_analysis(project, cfg.recon_run_id or "<run>"),),
                    note=f"poll analysis to terminal (budget {cfg.budget_s:g}s)",
                )
            )
        if cfg.start_phase in ("recon", "analysis", "hunting"):
            steps.append(_hunting_plan_step(cfg, project))
        return TrialPlan(tuple(steps))

    # --- chaining -------------------------------------------------------------

    def chain(self, bring_up: Callable[[], object], repair: RepairKit | None = None):
        """Run the setup; repair a configuration failure once, else escalate."""
        kit = repair or _NullRepair()
        try:
            return bring_up()
        except Exception as exc:  # noqa: BLE001 - the setup outcome is arbitrary
            failure = classify_failure(exc)
            if failure.layer != CONFIGURATION or not kit.supports(failure.repair):
                raise EscalationError(failure) from exc
            kit.apply(failure.repair)
            try:
                return bring_up()
            except Exception as retry_exc:  # noqa: BLE001
                raise EscalationError(classify_failure(retry_exc), retried=True) from retry_exc

    # --- execution ------------------------------------------------------------

    def run(
        self,
        *,
        bring_up: Callable[[], object] | None = None,
        repair: RepairKit | None = None,
    ) -> TrialRecord:
        cfg = self.config
        started = self._now()
        # #277: a seeded trial reuses the operator's pre-existing instance and
        # project as-is; the harness must not create or bring up either.
        if bring_up is not None and cfg.existing_project_id is None:
            self.chain(bring_up, repair)

        project_id = cfg.project_id or ""
        phases: list[PhaseRecord] = []
        cap: PollResult | None = None
        terminal = "complete"
        # I2: the phase the run is currently in, so an API transport failure
        # mid-poll still records which phase it reached.
        current_phase = cfg.start_phase
        try:
            # #277: a seeded trial reuses the transferred project as-is; it is
            # never created and, by `_bootstrap`, never mutated.
            if cfg.existing_project_id is not None:
                project_id = cfg.existing_project_id
            else:
                project_id = cfg.project_id or self._create_project()
            state = self._bootstrap(project_id)

            if cfg.start_phase == "recon":
                current_phase = "recon"
                phases.append(self._phase_recon(state))
                phase = phases[-1]
                if not phase.entered:
                    terminal = "blocked"
                elif phase.status == "timeout":
                    terminal = "timeout"
                elif _spend_stopped(phase, self._spend):
                    # A token-budget stop ends the trial here; unlike a natural
                    # recon stop (which cannot occur) it never chains to hunting.
                    terminal = "stopped"
                elif _phase_failed(phase):
                    terminal = "failed"
                else:
                    state = replace(state, recon_run_id=phase.run_id)
                    current_phase = "hunting"
                    nxt, cap = self._phase_hunting(state)
                    phases.append(nxt)
                    terminal = _terminal_of(nxt, cap)
            elif cfg.start_phase == "analysis":
                current_phase = "analysis"
                phases.append(self._phase_analysis(state))
                phase = phases[-1]
                if not phase.entered:
                    terminal = "blocked"
                elif phase.status == "timeout":
                    terminal = "timeout"
                elif _spend_stopped(phase, self._spend):
                    # A token-budget stop ends the trial here; a natural analysis
                    # `stopped` is not a spend stop, so it still chains.
                    terminal = "stopped"
                elif _phase_failed(phase):
                    terminal = "failed"
                else:
                    current_phase = "hunting"
                    nxt, cap = self._phase_hunting(state)
                    phases.append(nxt)
                    terminal = _terminal_of(nxt, cap)
            elif cfg.start_phase == "hunting":
                current_phase = "hunting"
                phase, cap = self._phase_hunting(state)
                phases.append(phase)
                terminal = _terminal_of(phase, cap)
            else:  # pragma: no cover - setup validation prevents this
                raise TrialError(f"unknown start phase: {cfg.start_phase!r}")

            return self._finish(started, project_id, phases, terminal, cap, [])
        except api.ApiError as exc:
            # I2: a transport failure mid-trial is a written failure, not a lost
            # run: the record names the error and the phase it reached, so the
            # surfer's state source sees it.
            return self._finish_api_failure(
                started, project_id, phases, current_phase, exc
            )

    def _finish_api_failure(
        self,
        started: str,
        project_id: str,
        phases: list[PhaseRecord],
        phase_name: str,
        error: api.ApiError,
    ) -> TrialRecord:
        """Write a failed record for an API transport failure (I2).

        The reached phase carries the error; a failure before any phase (during
        project creation or bootstrap) lands on the entry phase. `terminal` is
        `failed` so the surfer classifies it.
        """
        detail = f"api transport failure: {error}"
        reached = [phase for phase in phases if phase.phase == phase_name]
        if reached:
            reached[-1].failure = str(error)
        else:
            phases = list(phases) + [
                PhaseRecord(
                    phase=phase_name,
                    entered=True,
                    status="failed",
                    failure=str(error),
                )
            ]
        return self._finish(
            started, project_id or "<unknown>", phases, "failed", None, [detail]
        )

    # --- bootstrap ------------------------------------------------------------

    def _create_project(self) -> str:
        cfg = self.config
        name = cfg.project_name or f"eval-{cfg.target_id}"
        return api.project_id_of(self._call(api.create_project(name)))

    def _bootstrap(self, project_id: str) -> predicates.PhaseState:
        cfg = self.config
        # #277: a seeded project carries the operator's settings/auth/scaffold
        # already; the trial must make no call that creates or mutates it and no
        # scaffold command. Only the pre-mined placement (a filesystem write into
        # the pipeline's own inbox) runs, exactly as the normal path.
        seeded = cfg.existing_project_id is not None
        if not seeded:
            if cfg.project_id is None:
                settings: dict = {}
                if cfg.target_seed:
                    settings["target_seed"] = cfg.target_seed
                if cfg.operator_kb and self._files.exists(cfg.operator_kb):
                    settings["operator_kb"] = self._files.read_text(cfg.operator_kb)
                if settings:
                    self._call(api.put_settings(project_id, settings))

            if cfg.auth_surface and cfg.auth is not None:
                auth = dict(cfg.auth)
                skill = auth.pop("authn_skill", None)
                self._call(
                    api.seed_auth(
                        project_id,
                        overview=auth.get("overview"),
                        accounts=auth.get("accounts"),
                    )
                )
                if skill:
                    self._files.write_text(
                        authn_skill_path(cfg.data_root, project_id), str(skill)
                    )

            if cfg.scaffold is not None:
                self._run_command(plan_scaffold(cfg.scaffold, project_id))

        if cfg.preloaded_hunting_artifacts is not None:
            self._place_premined(project_id)

        return predicates.PhaseState(
            project_id=project_id,
            target_seed=cfg.target_seed,
            auth_surface=cfg.auth_surface,
            recon_run_id=cfg.recon_run_id,
            preloaded_configured=cfg.preloaded_hunting_artifacts is not None,
            data_root=cfg.data_root,
            seeded=seeded,
        )

    def _place_premined(self, project_id: str) -> None:
        """Place pre-mined artifacts into the pipeline's own `produced/` inboxes.

        No bespoke read path: hunt configs land in the hunt-config `produced/`
        inbox and each test spec lands in its fault key's
        `hunter/test-specs/<fault_key>/produced/` inbox, exactly where the
        pipeline's lazy read looks, so the normal mover consumes them. The trial
        never uploads or fabricates an artifact through the API.
        """
        place_premined(
            self._files,
            data_root=self.config.data_root,
            project_id=project_id,
            preloaded=self.config.preloaded_hunting_artifacts,
        )

    # --- phases ---------------------------------------------------------------

    def _phase_recon(self, state: predicates.PhaseState) -> PhaseRecord:
        if self._api is None:
            raise TrialError("trial execution requires an API runner")
        gate: GateResult = predicates.recon_entry(self._api, self._files, state)
        if not gate.ok:
            return PhaseRecord(phase="recon", blocks=list(gate.blocks))
        run_id = api.run_id_of(
            self._call(
                api.launch_recon(state.project_id, with_analysis=self.config.with_analysis)
            )
        )
        status = self._poll(
            state.project_id,
            api.recon_status(state.project_id, run_id),
            api.RECON_TERMINAL,
            spend=("recon", run_id),
        )
        # P8 liveness: a recon run that reports `complete` with no job rows, or
        # with every job failed, is a failed run - never chained into hunting.
        # I8: a partial surface (some jobs failed) is recorded as a note.
        notes = list(gate.notes)
        failure = None
        if status == "complete":
            run = self._call(api.recon_status(state.project_id, run_id))
            failure = _recon_failure(run)
            notes.extend(predicates.recon_job_notes(run))
        return PhaseRecord(
            phase="recon",
            entered=True,
            status=status,
            run_id=run_id,
            stop_run_id=run_id,
            notes=notes,
            failure=failure,
        )

    def _phase_analysis(self, state: predicates.PhaseState) -> PhaseRecord:
        if self._api is None:
            raise TrialError("trial execution requires an API runner")
        gate = predicates.analysis_entry(self._api, self._files, state)
        if not gate.ok:
            return PhaseRecord(phase="analysis", blocks=list(gate.blocks))
        analysis_run_id = api.analysis_run_id_of(
            self._call(api.launch_analysis(state.project_id, state.recon_run_id))
        )
        status = self._poll(
            state.project_id,
            api.analysis_status(state.project_id, state.recon_run_id),
            api.ANALYSIS_TERMINAL,
            # The analysis stop is keyed by the recon run id, the same id the
            # status read uses, not the surrogate `analysis_run_id`.
            spend=("analysis", state.recon_run_id),
        )
        return PhaseRecord(
            phase="analysis",
            entered=True,
            status=status,
            run_id=analysis_run_id,
            # The analysis stop is keyed by the recon run id, not the consumer
            # surrogate; record it so the surfer stops the run the trial stopped.
            stop_run_id=state.recon_run_id,
            notes=list(gate.notes),
        )

    def _phase_hunting(self, state: predicates.PhaseState) -> tuple[PhaseRecord, PollResult | None]:
        if self._api is None:
            raise TrialError("trial execution requires an API runner")
        gate = predicates.hunting_entry(self._api, self._files, state)
        if not gate.ok:
            return PhaseRecord(phase="hunting", blocks=list(gate.blocks)), None
        run_id = api.hunting_run_id_of(self._call(api.launch_hunting(state.project_id)))
        result = self._poll_hunting(state.project_id, run_id)
        phase = PhaseRecord(
            phase="hunting",
            entered=True,
            status=result.status,
            run_id=run_id,
            stop_run_id=run_id,
            notes=list(gate.notes),
        )
        return phase, result

    # --- polling --------------------------------------------------------------

    def _poll(
        self,
        project_id: str,
        status_call: api.ApiCall,
        terminal: frozenset,
        *,
        spend: tuple[str, str] | None = None,
    ) -> str:
        deadline = self._clock() + self.config.budget_s
        while True:
            status = api.status_of(self._call(status_call))
            if status in terminal:
                return status
            # The token budget is trial-wide: a spend stop ends any phase, so
            # check it after the terminal and before the wall-clock timeout.
            if spend is not None and self._check_spend(project_id, *spend):
                return "stopped"
            if self._clock() >= deadline:
                return "timeout"
            self._sleep(self.config.poll_s)

    def _check_spend(self, project_id: str, run_kind: str, run_id: str) -> SpendResult | None:
        """Enforce the trial-wide token budget; a `SpendResult` when it stops.

        No configured budget means no API call at all, so an unbudgeted trial
        pays nothing. The first check snapshots the project's cumulative token
        total as the baseline; a resumed trial arrives with one and never
        re-snapshots. On overflow the active run is stopped and the spend, the
        post-stop overshoot, and the per-agent breakdown are recorded.
        """
        budget = self.config.token_budget
        if budget is None:
            return None
        resp = self._call(api.usage(project_id))
        total = api.usage_total(resp)
        if self._spend_baseline is None:
            self._spend_baseline = total
        spent = max(0, total - self._spend_baseline)
        if spent < budget:
            return None
        self._call(api.stop_run(project_id, run_kind, run_id))
        # Re-read after the stop: the in-flight work may add tokens past the
        # budget, which is the recorded overshoot.
        final_total = api.usage_total(self._call(api.usage(project_id)))
        self._spend = SpendResult(
            spent=spent,
            overshoot=max(0, final_total - self._spend_baseline - budget),
            by_agent=api.usage_by_agent(resp),
        )
        return self._spend

    def _poll_hunting(self, project_id: str, run_id: str) -> PollResult:
        cfg = self.config
        deadline = self._clock() + cfg.budget_s
        consumed = hunt_configs_dir(cfg.data_root, project_id, "consumed")
        while True:
            # Trial-scoped cap: count only the configs consumed during this
            # trial. On the first poll, snapshot the names already there as the
            # baseline, so a prior run's configs never satisfy a new trial's
            # cap. The baseline is a name set, not a count, so a baseline file
            # removed mid-run cannot skew the count.
            names = [path.name for path in self._files.list_files(consumed)]
            if self._cap_baseline is None:
                self._cap_baseline = tuple(sorted(set(names)))
            baseline = set(self._cap_baseline)
            status = api.status_of(self._call(api.hunting_status(project_id, run_id)))
            if status in api.HUNTING_TERMINAL:
                return PollResult(status)
            # Spend first, then the cap: a token-budget stop is trial-wide, so
            # when both bounds trip on one poll the stop is attributed to spend.
            if self._check_spend(project_id, "hunting", run_id):
                return PollResult("stopped")
            count = sum(1 for name in names if name not in baseline)
            if cfg.hunt_config_budget is not None and count >= cfg.hunt_config_budget:
                self._call(api.stop_hunting(project_id, run_id))
                # Re-read after the stop: the in-flight mover may have added
                # more configs, which is the recorded overshoot (R7).
                final = sum(
                    1
                    for path in self._files.list_files(consumed)
                    if path.name not in baseline
                )
                return PollResult(
                    "stopped",
                    stop_count=count,
                    final_count=final,
                    overshoot=max(0, final - cfg.hunt_config_budget),
                )
            if self._clock() >= deadline:
                return PollResult("timeout")
            self._sleep(cfg.poll_s)

    # --- record ---------------------------------------------------------------

    def _finish(
        self,
        started: str,
        project_id: str,
        phases: list[PhaseRecord],
        terminal: str,
        cap: PollResult | None,
        notes: list[str],
    ) -> TrialRecord:
        cfg = self.config
        trial_id = cfg.trial_id or _default_trial_id(cfg, self._now)
        trial_dir = Path(cfg.runs_root) / cfg.target_id / trial_id
        intervention = [cfg.intervention] if cfg.intervention else []
        aggregated = intervention + list(notes) + [
            note for phase in phases for note in phase.notes
        ]
        record = TrialRecord(
            trial_id=trial_id,
            instance_id=cfg.instance_id,
            target_id=cfg.target_id,
            project_id=project_id,
            start_phase=cfg.start_phase,
            terminal=terminal,
            phases=phases,
            started_at=started,
            finished_at=self._now(),
            cap=cfg.hunt_config_budget,
            stop_count=cap.stop_count if cap else None,
            final_count=cap.final_count if cap else None,
            overshoot=cap.overshoot if cap else None,
            cap_baseline=(
                list(self._cap_baseline) if self._cap_baseline is not None else None
            ),
            token_budget=cfg.token_budget,
            spent_tokens=self._spend.spent if self._spend else None,
            spend_overshoot=self._spend.overshoot if self._spend else None,
            spend_baseline=self._spend_baseline,
            spend_by_agent=self._spend.by_agent if self._spend else None,
            notes=aggregated,
            trial_dir=str(trial_dir),
            target_run_id=cfg.target_run_id or cfg.instance_id,
            seeded=cfg.existing_project_id is not None,
            eval_sha=cfg.eval_sha,
            stack_fingerprint=cfg.stack_fingerprint,
            trace_id=cfg.trace_id,
        )
        import yaml  # lazy: the record is the one place the trial serializes

        self._files.write_text_atomic(
            trial_dir / "trial.yaml", yaml.safe_dump(record.to_dict(), sort_keys=False)
        )
        return record

    # --- seams ----------------------------------------------------------------

    def _call(self, call: api.ApiCall) -> dict:
        if self._api is None:
            raise TrialError("trial execution requires an API runner")
        return self._api(call)

    def _run_command(self, command: Command) -> None:
        if self._runner is None:
            raise TrialError("trial execution requires a command runner")
        require_ok(self._runner(command), command, error=TrialError)


def _hunting_plan_step(cfg: TrialConfig, project: str) -> TrialPlanStep:
    bounds = []
    if cfg.hunt_config_budget:
        bounds.append(f"stop at the consumed cap {cfg.hunt_config_budget}")
    if cfg.token_budget:
        bounds.append(f"stop at the token budget {cfg.token_budget}")
    suffix = "; " + "; ".join(bounds) if bounds else ""
    return TrialPlanStep(
        "hunting entry + launch",
        calls=(api.launch_hunting(project),),
        note=f"poll hunting to terminal{suffix} (budget {cfg.budget_s:g}s)",
    )


def _premined_sources(files: FileStore, source: str) -> list[Path]:
    """The files a pre-mined artifact source contributes: itself, or its walk."""
    path = Path(source)
    return [path] if files.is_file(path) else files.walk_files(path)


def place_premined(
    files: FileStore,
    *,
    data_root: str | Path,
    project_id: str,
    preloaded: PreloadedArtifacts,
) -> None:
    """Place pre-mined artifacts into the pipeline's own `produced/` inboxes.

    Shared with the surfer's `replace_artifacts` data-layer repair (#275) so the
    trial bootstrap and the repair can never drift: both land in the exact
    `produced/` inbox the pipeline's lazy read drains, never a bespoke path.
    """
    if preloaded.configs is not None:
        produced = hunt_configs_dir(data_root, project_id, "produced")
        for path in _premined_sources(files, preloaded.configs):
            files.write_text(produced / path.name, files.read_text(path))
    for spec in preloaded.test_specs:
        produced = hunter_test_specs_fault_dir(
            data_root, project_id, spec.fault_key, "produced"
        )
        for path in _premined_sources(files, spec.path):
            files.write_text(produced / path.name, files.read_text(path))


def _premined_inboxes(cfg: TrialConfig, project: str) -> tuple[str, ...]:
    """Every `produced/` inbox a pre-mined artifact set writes into."""
    pre = cfg.preloaded_hunting_artifacts
    raw_project = cfg.project_id or project
    inboxes: list[str] = []
    if pre.configs is not None:
        inboxes.append(str(hunt_configs_dir(cfg.data_root, raw_project, "produced")))
    for spec in pre.test_specs:
        inboxes.append(
            str(
                hunter_test_specs_fault_dir(
                    cfg.data_root, raw_project, spec.fault_key, "produced"
                )
            )
        )
    return tuple(inboxes)


def _phase_failed(phase: PhaseRecord) -> bool:
    """True when a phase's terminal (or its liveness failure) is a failure."""
    return phase.failure is not None or phase.status in FAILED_TERMINALS


def _spend_stopped(phase: PhaseRecord, spend: SpendResult | None) -> bool:
    """True when a phase ended on a token-budget stop, not a natural stop.

    Only a spend stop sets `spend`; a natural analysis `stopped` leaves it None,
    so it keeps the normal chain into hunting.
    """
    return spend is not None and phase.status == "stopped"


def _recon_failure(run: Mapping) -> str | None:
    """The liveness failure of a `complete` recon run, or None when healthy.

    A run with no job rows, or with every job failed, is a failed run (P8).
    A partial surface (some jobs failed) is healthy here; it is recorded as a
    note through `predicates.recon_job_notes` (I8).
    """
    jobs = api.per_job_rows(run)
    if not jobs:
        return "recon reported complete with no job rows (a failed run, P8)"
    if all((job or {}).get("status") == "failed" for job in jobs):
        names = ", ".join(str((job or {}).get("job")) for job in jobs)
        return f"recon reported complete but every job failed ({names})"
    return None


def _terminal_of(phase: PhaseRecord, cap: PollResult | None) -> str:
    if not phase.entered:
        return "blocked"
    if phase.status == "timeout":
        return "timeout"
    if _phase_failed(phase):
        return "failed"
    if cap is not None and cap.status == "stopped":
        return "stopped"
    return phase.status or "complete"


def _default_trial_id(cfg: TrialConfig, now: Callable[[], str]) -> str:
    stamp = now()
    try:
        token = datetime.fromisoformat(stamp).strftime("%Y%m%dT%H%M%S")
    except ValueError:  # a non-ISO injected clock is used verbatim
        token = stamp
    return f"{cfg.target_id}-{token}-{short_id(cfg.instance_id + '/' + cfg.target_id)}"
