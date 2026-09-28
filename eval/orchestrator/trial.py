"""The trial engine: phase entry, chaining, launch/poll, and the hunting cap.

A `Trial` drives one `TargetRun` on one instance from a phase entry to
terminal: bootstrap the project (settings, `AuthContext`, L1 scaffold,
pre-mined artifacts), gate the phase on persisted state, launch it, and poll
within a budget. The setup outcome chains into execution: a configuration-layer
failure gets one bounded repair and a retry, anything else escalates (D28).

Every effect is injected - the REST `ApiRunner`, the `FileStore` filesystem
seam, the #269 `CommandRunner`, the clock, and the reachability probe - so the
engine is exercised without a live stack. Import performs no I/O.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Protocol

from orchestrator import api, instances, predicates, routing
from orchestrator.commands import Command, CommandRunner, require_ok
from orchestrator.files import (
    FileStore,
    authn_skill_path,
    hunt_configs_dir,
)
from orchestrator.ids import short_id
from orchestrator.instances import InstanceError, InstancePaths
from orchestrator.predicates import GateResult
from orchestrator.workitems import WorkItemGateError
from orchestrator.targets.base import READY_UNREACHABLE

CONFIGURATION = "configuration"
ESCALATE = "escalate"


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
    """`python3 eval/scaffold.py <project> --kb <kb>` with `src` on the path."""
    env = {"PYTHONPATH": spec.pythonpath, **(dict(spec.env) if spec.env else {})}
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


def make_reachability_probe(
    paths: InstancePaths,
    runner: CommandRunner,
    url: str,
    *,
    max_time_s: int = 10,
) -> Callable[[], bool]:
    """Build the recon-entry reachability probe through the kali exec plane."""

    def probe() -> bool:
        command = routing.kali_probe_command(paths, url, max_time_s=max_time_s)
        result = runner(command)
        code = (result.stdout or "").strip()
        return result.returncode == 0 and code not in READY_UNREACHABLE

    return probe


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
    preloaded_hunting_artifacts: Path | None = None
    hunt_config_budget: int | None = None
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
    # D32: the version identity stamped into the trial record and the verdicts.
    eval_sha: str | None = None
    stack_fingerprint: str | None = None


@dataclass
class PhaseRecord:
    """One phase's entry decision and run outcome."""

    phase: str
    entered: bool = False
    status: str | None = None
    run_id: str | None = None
    blocks: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class PollResult:
    """A hunting poll's terminal outcome, including any cap stop."""

    status: str
    stop_count: int | None = None
    final_count: int | None = None
    overshoot: int | None = None


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
    notes: list[str] = field(default_factory=list)
    trial_dir: str | None = None
    # #273: the target-run grouping level of the artifact store (defaults to
    # the instance id when the trial did not name one).
    target_run_id: str | None = None
    # D32/D37: the version identity the trial ran on, and the assessment state.
    eval_sha: str | None = None
    stack_fingerprint: str | None = None
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
        reachable: Callable[[], bool] | None = None,
        now: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self._api = api_runner
        self._files = files or FileStore()
        self._runner = runner
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._reachable = reachable
        self._now = now or _utcnow

    # --- plan mode ------------------------------------------------------------

    def plan(self) -> TrialPlan:
        """Print every call, file write, and command without reading anything."""
        cfg = self.config
        project = cfg.project_id or "<project>"
        steps: list[TrialPlanStep] = []
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
                    files=(str(hunt_configs_dir(cfg.data_root, project, "produced")),),
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
        if bring_up is not None:
            self.chain(bring_up, repair)

        project_id = cfg.project_id or self._create_project()
        state = self._bootstrap(project_id)

        phases: list[PhaseRecord] = []
        cap: PollResult | None = None
        terminal = "complete"

        if cfg.start_phase == "recon":
            phases.append(self._phase_recon(state))
            if not phases[-1].entered:
                terminal = "blocked"
            elif phases[-1].status == "timeout":
                terminal = "timeout"
            else:
                state = replace(state, recon_run_id=phases[-1].run_id)
                phase, cap = self._phase_hunting(state)
                phases.append(phase)
                terminal = _terminal_of(phase, cap)
        elif cfg.start_phase == "analysis":
            phases.append(self._phase_analysis(state))
            if not phases[-1].entered:
                terminal = "blocked"
            elif phases[-1].status == "timeout":
                terminal = "timeout"
            else:
                phase, cap = self._phase_hunting(state)
                phases.append(phase)
                terminal = _terminal_of(phase, cap)
        elif cfg.start_phase == "hunting":
            phase, cap = self._phase_hunting(state)
            phases.append(phase)
            terminal = _terminal_of(phase, cap)
        else:  # pragma: no cover - setup validation prevents this
            raise TrialError(f"unknown start phase: {cfg.start_phase!r}")

        return self._finish(started, project_id, state, phases, terminal, cap, [])

    # --- bootstrap ------------------------------------------------------------

    def _create_project(self) -> str:
        cfg = self.config
        name = cfg.project_name or f"eval-{cfg.target_id}"
        return api.project_id_of(self._call(api.create_project(name)))

    def _bootstrap(self, project_id: str) -> predicates.PhaseState:
        cfg = self.config
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
                self._files.write_text(authn_skill_path(cfg.data_root, project_id), str(skill))

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
        )

    def _place_premined(self, project_id: str) -> None:
        """Place pre-mined configs into the pipeline's own `produced/` inbox.

        No bespoke read path: the files land exactly where the pipeline's lazy
        read looks, so the normal mover consumes them. The trial never uploads
        or fabricates a config through the API.
        """
        cfg = self.config
        source = Path(cfg.preloaded_hunting_artifacts)
        sources = [source] if source.is_file() else self._files.walk_files(source)
        produced = hunt_configs_dir(cfg.data_root, project_id, "produced")
        for path in sources:
            self._files.write_text(produced / path.name, self._files.read_text(path))

    # --- phases ---------------------------------------------------------------

    def _phase_recon(self, state: predicates.PhaseState) -> PhaseRecord:
        if self._api is None:
            raise TrialError("trial execution requires an API runner")
        if self._reachable is None:
            raise TrialError("recon entry requires a reachability probe")
        gate: GateResult = predicates.recon_entry(
            self._api, self._files, state, reachable=self._reachable
        )
        if not gate.ok:
            return PhaseRecord(phase="recon", blocks=list(gate.blocks))
        run_id = api.run_id_of(
            self._call(
                api.launch_recon(state.project_id, with_analysis=self.config.with_analysis)
            )
        )
        status = self._poll(
            api.recon_status(state.project_id, run_id), api.RECON_TERMINAL
        )
        return PhaseRecord(
            phase="recon", entered=True, status=status, run_id=run_id, notes=list(gate.notes)
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
            api.analysis_status(state.project_id, state.recon_run_id),
            api.ANALYSIS_TERMINAL,
        )
        return PhaseRecord(
            phase="analysis",
            entered=True,
            status=status,
            run_id=analysis_run_id,
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
            notes=list(gate.notes),
        )
        return phase, result

    # --- polling --------------------------------------------------------------

    def _poll(self, status_call: api.ApiCall, terminal: frozenset) -> str:
        deadline = self._clock() + self.config.budget_s
        while True:
            status = api.status_of(self._call(status_call))
            if status in terminal:
                return status
            if self._clock() >= deadline:
                return "timeout"
            self._sleep(self.config.poll_s)

    def _poll_hunting(self, project_id: str, run_id: str) -> PollResult:
        cfg = self.config
        deadline = self._clock() + cfg.budget_s
        consumed = hunt_configs_dir(cfg.data_root, project_id, "consumed")
        while True:
            status = api.status_of(self._call(api.hunting_status(project_id, run_id)))
            if status in api.HUNTING_TERMINAL:
                return PollResult(status)
            count = self._files.count_files(consumed)
            if cfg.hunt_config_budget is not None and count >= cfg.hunt_config_budget:
                self._call(api.stop_hunting(project_id, run_id))
                final = self._files.count_files(consumed)
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
        state: predicates.PhaseState,
        phases: list[PhaseRecord],
        terminal: str,
        cap: PollResult | None,
        notes: list[str],
    ) -> TrialRecord:
        cfg = self.config
        trial_id = cfg.trial_id or _default_trial_id(cfg)
        trial_dir = Path(cfg.runs_root) / cfg.target_id / trial_id
        aggregated = list(notes) + [note for phase in phases for note in phase.notes]
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
            notes=aggregated,
            trial_dir=str(trial_dir),
            target_run_id=cfg.target_run_id or cfg.instance_id,
            eval_sha=cfg.eval_sha,
            stack_fingerprint=cfg.stack_fingerprint,
        )
        import yaml  # lazy: the record is the one place the trial serializes

        self._files.write_text(
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
    cap = f"; stop at the consumed cap {cfg.hunt_config_budget}" if cfg.hunt_config_budget else ""
    return TrialPlanStep(
        "hunting entry + launch",
        calls=(api.launch_hunting(project),),
        note=f"poll hunting to terminal{cap} (budget {cfg.budget_s:g}s)",
    )


def _terminal_of(phase: PhaseRecord, cap: PollResult | None) -> str:
    if not phase.entered:
        return "blocked"
    if phase.status == "timeout":
        return "timeout"
    if cap is not None and cap.status == "stopped":
        return "stopped"
    return phase.status or "complete"


def _default_trial_id(cfg: TrialConfig) -> str:
    token = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{cfg.target_id}-{token}-{short_id(cfg.instance_id + '/' + cfg.target_id)}"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
