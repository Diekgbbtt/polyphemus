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


def _pack_skill_archive(skill_dir: str | Path, files: FileStore) -> bytes:
    """Pack a skill bundle directory into an in-memory `.tar.gz` whose members are
    bundle-relative (`SKILL.md`, `references/<name>`, ...), for the multipart
    `authn-skill` upload. The store unpacks it under the canonical bundle path."""
    import io
    import tarfile

    base = Path(skill_dir)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path in files.walk_files(base):
            relative = Path(path).relative_to(base).as_posix()
            payload = files.read_bytes(path)
            info = tarfile.TarInfo(relative)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


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
    # The per-target data-dependency source directory (holds `auth/`, `skills/`,
    # and `operator_kb.md`). Read at bootstrap and placed through the multipart
    # data-dependency endpoints; None means the target has no source dir.
    data_dir: Path | None = None
    auth_surface: bool = False
    preloaded_hunting_artifacts: PreloadedArtifacts | None = None
    # The trial-wide token budget (capped tokens: new output + uncached input)
    # and its carried baseline: None budget means no usage call at all; None
    # baseline means "snapshot the project's capped total at the first check",
    # a resumed trial carries its own.
    token_budget: int | None = None
    spend_baseline: int | None = None
    data_root: Path = Path("data")
    runs_root: Path = Path("eval/runs")
    trial_id: str | None = None
    # The target-run this trial belongs to (the artifact-store middle level,
    # #273). Defaults to the instance id: one instance evaluates one target run.
    target_run_id: str | None = None
    with_analysis: bool = True
    # The analysis is STREAMED during recon (settings.recon.streaming_analysis):
    # each producing job pushes its curated payload into the run's FIFO and the
    # queued analysis consumer drains it (analyse_chunked -> assigner ->
    # mechanism_typist -> data_modeller, whose AGGREGATES reach the L1 curator).
    # The old batched/post-recon path is obsolete, so this defaults ON: a recon
    # run without it mints no L1 edges (the #321 zero-AGGREGATES root cause).
    streaming_analysis: bool = True
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
    """A hunting poll's terminal outcome. `response` is the terminal run row,
    when the status read supplied one, so the phase can record the cause of an
    `interrupted` run (#331)."""

    status: str
    response: Mapping | None = None


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
    """The persisted trial record (ids, phases, timings, budget, assessment, diagnosis).

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
    # The trial-wide token budget and its outcome: the sum spent against the
    # carried baseline (in capped tokens: new output + uncached input), the
    # tokens spent past the bound (the post-stop re-read), and the per-agent
    # breakdown. Additive, default None, old records load.
    token_budget: int | None = None
    # Capped tokens spent over the baseline (the budget axis); not a raw total.
    spent_tokens: int | None = None
    spend_overshoot: int | None = None
    spend_baseline: int | None = None
    spend_by_agent: dict | None = None
    # #346: the terminal usage snapshot (the full two-axis surface, the raw total,
    # and the capped budget axis), read at every terminal so a failed or timed-out
    # trial still carries its token usage even when no budget stop populated
    # `spent_tokens`. Additive, default None, so older records load.
    usage: dict | None = None
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
            # The streamed-analysis gate (settings.recon.streaming_analysis): the
            # batched/post-recon path is obsolete, so every fresh trial turns it
            # on. The PUT deep-merges, so this never wipes target_seed/operator_kb.
            settings["streaming_analysis"] = cfg.streaming_analysis
            steps.append(
                TrialPlanStep("settings", calls=(api.put_settings(project, settings),))
            )
            if cfg.auth_surface and cfg.data_dir is not None:
                steps.append(
                    TrialPlanStep(
                        "data dependencies",
                        calls=(
                            api.place_auth_overview(project, b"<overview>", "overview.yaml"),
                            api.place_auth_credentials(
                                project, b"<credentials>", "credentials.yaml"
                            ),
                            api.place_authn_skill(project, b"<authn-bundle>", "authn.tar.gz"),
                        ),
                        note=f"multipart placement from {cfg.data_dir}",
                    )
                )
            if cfg.start_phase == "recon" and cfg.operator_kb is not None:
                steps.append(
                    TrialPlanStep(
                        "L1 surface",
                        calls=(api.place_l1(project, b"<operator_kb>", "operator_kb.md"),),
                        note="deterministic scaffold persisted into the graph",
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
                elif phase.status == "stopped":
                    # A recon stop ends the trial here and never chains into
                    # hunting, whether it is a token-budget stop (spend set) or a
                    # natural stop the surfer issued (#287). A `stopped` run row
                    # is a deliberate stop, distinct from a crash.
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
                # The streamed-analysis gate (see TrialConfig.streaming_analysis):
                # the batched/post-recon path is obsolete, so it is always on.
                settings["streaming_analysis"] = cfg.streaming_analysis
                self._call(api.put_settings(project_id, settings))

            # The pre-built data dependencies land by direct file write through
            # the multipart endpoints (a MOUNT the agent finds at startup), then
            # the L1 surface persists into the graph - no host-side scaffold.
            self._place_data_dependencies(project_id)
            if cfg.start_phase == "recon":
                self._place_l1(project_id)

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

    def _place_data_dependencies(self, project_id: str) -> None:
        """Upload the target's pre-built auth artifacts through the multipart
        data-dependency endpoints. Each artifact is placed only when its source
        exists; the canonical destination and the validation are server-side."""
        cfg = self.config
        base = cfg.data_dir
        if base is None:
            return
        overview = Path(base) / "auth" / "overview.yaml"
        if self._files.exists(overview):
            self._call(
                api.place_auth_overview(
                    project_id, self._files.read_bytes(overview), "overview.yaml"
                )
            )
        credentials = Path(base) / "auth" / "credentials.yaml"
        if self._files.exists(credentials):
            self._call(
                api.place_auth_credentials(
                    project_id, self._files.read_bytes(credentials), "credentials.yaml"
                )
            )
        skill_dir = Path(base) / "skills" / "authn"
        if self._files.is_dir(skill_dir):
            archive = _pack_skill_archive(skill_dir, self._files)
            self._call(api.place_authn_skill(project_id, archive, "authn.tar.gz"))
            # The recon gate reads the skill from the data root; verify it landed
            # rather than relying on the placement call's success alone.
            skill_path = authn_skill_path(cfg.data_root, project_id)
            if not self._files.exists(skill_path):
                raise TrialError(
                    f"the authn skill did not land at {skill_path} after placement"
                )

    def _place_l1(self, project_id: str) -> None:
        """Persist the deterministic L1 surface into the graph through the `l1`
        endpoint, reading the operator KB from `cfg.operator_kb`."""
        cfg = self.config
        if not cfg.operator_kb or not self._files.exists(cfg.operator_kb):
            return
        filename = Path(cfg.operator_kb).name or "operator_kb.md"
        self._call(api.place_l1(project_id, self._files.read_bytes(cfg.operator_kb), filename))

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
            run=("recon", run_id),
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
            run=("analysis", state.recon_run_id),
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
            failure=_hunting_failure(result),
        )
        return phase, result

    # --- polling --------------------------------------------------------------

    def _poll(
        self,
        project_id: str,
        status_call: api.ApiCall,
        terminal: frozenset,
        *,
        run: tuple[str, str],
    ) -> str:
        deadline = self._clock() + self.config.budget_s
        while True:
            status = api.status_of(self._call(status_call))
            if status in terminal:
                return status
            # The token budget and the trial deadline both stop the active run,
            # so a poll never returns while the run it launched keeps running.
            if self._check_spend(project_id, *run):
                return "stopped"
            if self._clock() >= deadline:
                self._stop_run(project_id, *run)
                return "timeout"
            self._sleep(self.config.poll_s)

    def _stop_run(self, project_id: str, run_kind: str, run_id: str) -> None:
        """Stop the active run through the injected API seam.

        A token-budget stop and a trial-deadline stop both stop the run the
        trial launched. No surfer runs by default and the surfer has no timeout
        trigger, so leaving the run running would orphan it and let it contend
        for the agent and provider.
        """
        self._call(api.stop_run(project_id, run_kind, run_id))

    def _check_spend(self, project_id: str, run_kind: str, run_id: str) -> SpendResult | None:
        """Enforce the trial-wide token budget; a `SpendResult` when it stops.

        The budget counts capped tokens (`capped_tokens`: new output +
        uncached input = `total_tokens - cached`) - the real compute - and never
        cached input the model re-read, so cache reuse does not consume the
        budget. No configured budget means no API call at all, so an unbudgeted
        trial pays nothing. The first check snapshots the project's cumulative
        capped total as the baseline; a resumed trial arrives with one and never
        re-snapshots. On overflow the active run is stopped and the spend, the
        post-stop overshoot, and the per-agent breakdown are recorded.
        """
        budget = self.config.token_budget
        if budget is None:
            return None
        resp = self._call(api.usage(project_id))
        total = api.usage_capped(resp)
        if self._spend_baseline is None:
            self._spend_baseline = total
        spent = max(0, total - self._spend_baseline)
        if spent < budget:
            return None
        self._stop_run(project_id, run_kind, run_id)
        # Re-read after the stop: the in-flight work may add tokens past the
        # budget, which is the recorded overshoot.
        final_total = api.usage_capped(self._call(api.usage(project_id)))
        self._spend = SpendResult(
            spent=spent,
            overshoot=max(0, final_total - self._spend_baseline - budget),
            by_agent=api.usage_by_agent(resp),
        )
        return self._spend

    def _poll_hunting(self, project_id: str, run_id: str) -> PollResult:
        cfg = self.config
        deadline = self._clock() + cfg.budget_s
        while True:
            response = self._call(api.hunting_status(project_id, run_id))
            status = api.status_of(response)
            if status in api.HUNTING_TERMINAL:
                return PollResult(status, response)
            # Only the trial-wide token budget stops hunting now: the hunt-config
            # cap is REMOVED (2026-10-05). It hard-stopped runs mid-coverage (the
            # jetlinks-1 tier-0 cap-exhaustion) and a consumed-config COUNT is not
            # a failure signal - the run settles on its own quiesce, the budget,
            # or the trial deadline.
            if self._check_spend(project_id, "hunting", run_id):
                return PollResult("stopped")
            if self._clock() >= deadline:
                self._stop_run(project_id, "hunting", run_id)
                return PollResult("timeout")
            self._sleep(cfg.poll_s)

    # --- record ---------------------------------------------------------------

    def _terminal_spend(
        self, project_id: str
    ) -> tuple[SpendResult | None, dict | None]:
        """The trial's spend at terminal, and its full usage snapshot (#346).

        A budget stop already produced a `SpendResult` (`self._spend`) and is
        returned as-is (with no extra usage read, so the budget path is
        unchanged). Otherwise the project's cumulative usage is read once here,
        so a failed or timed-out trial still records what it spent: `spent` is
        the capped-axis delta over the carried baseline and `usage` is the raw
        two-axis surface. Fail-open: an unreadable usage surface yields
        `(None, None)` and never breaks the terminal record."""
        if self._spend is not None:
            return self._spend, None
        resp = self._read_usage(project_id)
        if not resp:
            return None, None
        baseline = self._spend_baseline or 0
        return (
            SpendResult(
                spent=max(0, api.usage_capped(resp) - baseline),
                overshoot=0,
                by_agent=api.usage_by_agent(resp),
            ),
            dict(resp),
        )

    def _read_usage(self, project_id: str) -> dict:
        """Read the project usage snapshot for the terminal record, fail-open.

        The terminal record is written even when the app usage surface is
        unreachable, so this never raises into `_finish`."""
        try:
            return self._call(api.usage(project_id)) or {}
        except Exception:  # noqa: BLE001 - the terminal record must still write
            return {}

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
        spend, usage = self._terminal_spend(project_id)
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
            token_budget=cfg.token_budget,
            spent_tokens=spend.spent if spend else None,
            spend_overshoot=spend.overshoot if spend else None,
            spend_baseline=self._spend_baseline,
            spend_by_agent=spend.by_agent if spend else None,
            usage=usage,
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

def _hunting_plan_step(cfg: TrialConfig, project: str) -> TrialPlanStep:
    bounds = []
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


def _hunting_failure(result: PollResult) -> str | None:
    """The hunting phase's failure cause, or None when healthy (#331).

    An `interrupted` hunt is a resumable pause (a provider throttle or a process
    restart), never a domain failure - but the trial stops at it and must record
    WHY. The cause rides the run row's `stats.interrupt_reason`, recorded by the
    app when it landed the `interrupted` terminal; the trial reads it so the
    surfer's classifier can tell a transient 429 from consumed credits. A status
    that is neither interrupted nor a failure contributes nothing (the phase's
    own `status`/`failure` already carry it)."""
    if result.status != "interrupted":
        return None
    stats = (result.response or {}).get("stats") or {}
    reason = stats.get("interrupt_reason")
    if reason:
        return str(reason)
    return "hunting run interrupted (resumable)"


def _default_trial_id(cfg: TrialConfig, now: Callable[[], str]) -> str:
    stamp = now()
    try:
        token = datetime.fromisoformat(stamp).strftime("%Y%m%dT%H%M%S")
    except ValueError:  # a non-ISO injected clock is used verbatim
        token = stamp
    return f"{cfg.target_id}-{token}-{short_id(cfg.instance_id + '/' + cfg.target_id)}"
