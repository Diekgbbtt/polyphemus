"""The `python -m orchestrator` entry point.

`plan`, `trial --dry-run`, and `up --dry-run` print every command and never
construct a runner; `up`, `down`, `status`, and `trial` inject the thin local
runner (and the trial additionally the HTTP API runner). The runner factories
are parameters so plan mode's "execute nothing" is provable in a test.
"""
from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path
from typing import Callable, TextIO

from orchestrator import api, assessment, evidence, instances, trial, verdicts
from orchestrator.commands import LocalRunner
from orchestrator.files import FileStore
from orchestrator.instances import InstanceError
from orchestrator.orchestrator import (
    InstanceResult,
    Orchestrator,
    OrchestratorConfig,
    OrchestratorError,
    PlanStep,
)
from orchestrator.setup import EvalSetup, Instance, SetupError, TargetRun, load_eval_setup
from orchestrator.targets.base import TargetError
from orchestrator.workitems import WorkItemGateError

DEFAULT_INSTANCES_ROOT = "eval/instances"
DEFAULT_BRANCH = "eval"
DEFAULT_RUNS_ROOT = "eval/runs"
DEFAULT_API = "http://localhost:8080"

RunnerFactory = Callable[[], object]
ApiFactory = Callable[[str], object]
# The assessment dispatcher factory: the rendered command argv -> a dispatcher.
DispatchFactory = Callable[[tuple[str, ...]], assessment.SubagentDispatcher]
_HANDLED = (
    SetupError,
    WorkItemGateError,
    InstanceError,
    TargetError,
    OrchestratorError,
    trial.TrialError,
    trial.EscalationError,
    assessment.AssessmentError,
    evidence.EvidenceError,
    verdicts.VerdictError,
    OSError,
)


def _common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("setup", help="path to the EvalSetup YAML")
    parser.add_argument(
        "--repo",
        default=os.environ.get("EVAL_REPO", "."),
        help="the canonical eval checkout (git worktrees are added from it)",
    )
    parser.add_argument(
        "--instances-root",
        default=os.environ.get("EVAL_INSTANCES_ROOT", DEFAULT_INSTANCES_ROOT),
        help="where per-instance worktrees live",
    )
    parser.add_argument(
        "--branch",
        default=os.environ.get("EVAL_BRANCH", DEFAULT_BRANCH),
        help="the read-only branch instances run from",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m orchestrator",
        description="Render, bring up, and tear down a multi-instance eval setup.",
    )
    sub = parser.add_subparsers(dest="verb", required=True)
    for verb, help_text in (
        ("plan", "print every command without executing anything"),
        ("up", "bring up every instance and target"),
        ("down", "tear down every target and instance"),
        ("status", "show instance and target status"),
    ):
        child = sub.add_parser(verb, help=help_text)
        _common_args(child)
    sub.choices["up"].add_argument(
        "--dry-run", action="store_true", help="print the plan without executing"
    )

    # --- the trial verb (#270) ------------------------------------------------
    run_parser = sub.add_parser(
        "trial", help="run one target trial from its phase entry to terminal"
    )
    _common_args(run_parser)
    run_parser.add_argument("instance_id", help="the EvalSetup instance to run on")
    run_parser.add_argument("target_id", help="the instance's TargetRun to run")
    run_parser.add_argument(
        "--api",
        default=os.environ.get("PH_API", DEFAULT_API),
        help="the instance polymerhus API base URL",
    )
    run_parser.add_argument(
        "--data-root",
        default=os.environ.get("EVAL_DATA_ROOT"),
        help="the instance's app data root (default: <repo>/data)",
    )
    run_parser.add_argument(
        "--runs-root",
        default=os.environ.get("EVAL_RUNS_ROOT", DEFAULT_RUNS_ROOT),
        help="where per-trial record directories live",
    )
    run_parser.add_argument("--budget-s", type=float, default=7200.0)
    run_parser.add_argument("--poll-s", type=float, default=15.0)
    run_parser.add_argument("--project-id", help="resume an existing project")
    run_parser.add_argument("--recon-run", help="the recon run a later phase drains")
    run_parser.add_argument(
        "--eval-sha",
        default=os.environ.get("EVAL_SHA"),
        help="the eval SHA this trial ran on (stamped into the trial record, D32)",
    )
    run_parser.add_argument(
        "--stack-fingerprint",
        default=os.environ.get("EVAL_STACK_FINGERPRINT"),
        help="the stack fingerprint this trial ran on (stamped into the record, D37)",
    )
    run_parser.add_argument(
        "--dry-run", action="store_true", help="print the plan without executing"
    )

    # --- the assessment verbs (#271) ------------------------------------------
    assess_parser = sub.add_parser(
        "assess", help="dispatch the background assessment subagent for one trial"
    )
    _common_args(assess_parser)
    assess_parser.add_argument("--trial", required=True, help="the trial directory")
    _assessment_args(assess_parser)

    close_parser = sub.add_parser(
        "close-verify",
        help="verify every trial's verdicts.yaml; re-dispatch, then micro-diagnose",
    )
    _common_args(close_parser)
    _assessment_args(close_parser)
    return parser


def _assessment_args(parser: argparse.ArgumentParser) -> None:
    """The shared knobs of the `assess`/`close-verify` verbs (D15/D6)."""
    parser.add_argument(
        "--ground-truth",
        default=os.environ.get("EVAL_GROUND_TRUTH"),
        help="the challenge ground-truth directory (default: resolved via gt.py)",
    )
    parser.add_argument(
        "--data-root",
        default=os.environ.get("EVAL_DATA_ROOT"),
        help="the instance's app data root (default: <repo>/data)",
    )
    parser.add_argument(
        "--runs-root",
        default=os.environ.get("EVAL_RUNS_ROOT", DEFAULT_RUNS_ROOT),
        help="where per-trial record directories live",
    )
    parser.add_argument(
        "--command",
        default=os.environ.get("EVAL_ASSESS_COMMAND"),
        help="the assessment agent command line; placeholders: {prompt} "
        "{trial_record} {ground_truth} {data_root} {destination} {trace_id}",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the plan without dispatching"
    )


def _print_plan(steps: list[PlanStep], out: TextIO) -> None:
    for step in steps:
        print(f"# {step.label}", file=out)
        for command in step.commands:
            print(f"  {command.display()}", file=out)


def _print_trial_plan(plan: trial.TrialPlan, out: TextIO) -> None:
    for step in plan.steps:
        print(f"# {step.label}", file=out)
        for call in step.calls:
            print(f"  {call.display()}", file=out)
        for command in step.commands:
            print(f"  {command.display()}", file=out)
        for path in step.files:
            print(f"  write {path}", file=out)
        if step.note:
            print(f"  ({step.note})", file=out)


def _print_results(results: list[InstanceResult], out: TextIO) -> None:
    for instance in results:
        print(f"instance {instance.instance_id}: up", file=out)
        for target in instance.targets:
            print(
                f"  target {target.host}: {target.front_url} -> {target.backend}",
                file=out,
            )


def _find_instance(setup: EvalSetup, instance_id: str) -> Instance:
    for instance in setup.instances:
        if instance.instance_id == instance_id:
            return instance
    raise SetupError(f"no instance {instance_id!r} in the EvalSetup")


def _find_target(instance: Instance, target_id: str) -> TargetRun:
    for run in instance.targets:
        if run.target_id == target_id:
            return run
    raise SetupError(
        f"no target {target_id!r} in instance {instance.instance_id!r}"
    )


def _resolve_data_root(args) -> Path:
    if args.data_root:
        return Path(args.data_root)
    from data_root import resolve  # eval/ top-level helper (lazy, no import-time I/O)

    return resolve()


def _trial_config(args, setup: EvalSetup, config: OrchestratorConfig) -> tuple[
    trial.TrialConfig, "instances.InstancePaths", TargetRun
]:
    instance = _find_instance(setup, args.instance_id)
    run = _find_target(instance, args.target_id)
    paths = instances.instance_paths(
        instance,
        config.instances_root,
        repo=config.repo,
        branch=config.branch,
        compose_files=config.compose_files,
    )
    kb = None
    if run.target_config.operator_kb:
        candidate = Path(run.target_config.operator_kb)
        kb = str(candidate if candidate.is_absolute() else Path(args.repo) / candidate)
    scaffold = None
    if run.start_phase == "recon" and kb:
        scaffold = trial.ScaffoldSpec(cwd=str(paths.worktree), kb=kb)
    pinned = run.preloaded_hunting_artifacts
    if args.data_root:
        data_root = Path(args.data_root)
    elif args.dry_run:
        data_root = Path("<data-root>")  # plan mode never resolves the live root
    else:
        data_root = _resolve_data_root(args)
    cfg = trial.TrialConfig(
        instance_id=instance.instance_id,
        target_id=run.target_id,
        start_phase=run.start_phase,
        project_name=f"eval-{run.target_id}",
        target_seed=run.target_config.target_seed,
        operator_kb=kb,
        auth=run.target_config.auth,
        auth_surface=run.target_config.auth is not None,
        preloaded_hunting_artifacts=Path(pinned) if pinned else None,
        hunt_config_budget=run.hunt_config_budget,
        data_root=data_root,
        runs_root=Path(args.runs_root),
        with_analysis=True,
        scaffold=scaffold,
        budget_s=args.budget_s,
        poll_s=args.poll_s,
        project_id=args.project_id,
        recon_run_id=args.recon_run,
        eval_sha=args.eval_sha,
        stack_fingerprint=args.stack_fingerprint,
    )
    return cfg, paths, run


def _run_trial(args, setup: EvalSetup, config: OrchestratorConfig, out: TextIO, err: TextIO,
               runner_factory: RunnerFactory, api_factory: ApiFactory) -> int:
    cfg, paths, _run = _trial_config(args, setup, config)
    if args.dry_run:
        _print_trial_plan(trial.Trial(cfg).plan(), out)
        return 0

    runner = runner_factory()
    api_runner = api_factory(args.api)
    probe = trial.make_reachability_probe(paths, runner, trial.front_url(cfg))
    engine = trial.Trial(cfg, api_runner=api_runner, runner=runner, reachable=probe)
    orchestrator = Orchestrator(setup, config, runner=runner)
    record = engine.run(
        bring_up=orchestrator.up,
        repair=trial.InstanceRepair(paths, runner),
    )
    print(f"trial {record.trial_id}: {record.terminal} (project {record.project_id})", file=out)
    for phase in record.phases:
        detail = phase.status or ("blocked" if not phase.entered else "")
        print(f"  {phase.phase}: {detail}", file=out)
        for block in phase.blocks:
            print(f"    blocked: {block}", file=err)
        for note in phase.notes:
            print(f"    note: {note}", file=out)
    if record.overshoot:
        print(
            f"  cap {record.cap}: stopped at {record.stop_count}, "
            f"final {record.final_count} (overshoot {record.overshoot})",
            file=out,
        )
    return 0


# --- assessment (#271) --------------------------------------------------------


def _assessment_argv(args) -> tuple[str, ...]:
    if not args.command:
        raise assessment.AssessmentError(
            "no assessment command configured; pass --command or EVAL_ASSESS_COMMAND"
        )
    return tuple(shlex.split(args.command))


def _find_target_run(setup: EvalSetup, target_id: str) -> TargetRun:
    for instance in setup.instances:
        for run in instance.targets:
            if run.target_id == target_id:
                return run
    raise SetupError(f"no target {target_id!r} in the EvalSetup")


def _ground_truth_for(args, run: TargetRun) -> Path:
    if args.ground_truth:
        return Path(args.ground_truth)
    target = run.target_config.params.get("target")
    if not target:
        raise assessment.AssessmentError(
            f"target {run.target_id!r} declares no ground-truth name; pass --ground-truth"
        )
    return assessment.resolve_ground_truth(str(target))


def _assessment_data_root(args) -> Path:
    if args.data_root:
        return Path(args.data_root)
    return _resolve_data_root(args)


def _plan_request(args, trial_dir: Path) -> assessment.AssessmentRequest:
    """A read-free request for plan mode: explicit paths or placeholders."""
    return assessment.AssessmentRequest(
        prompt=assessment.ASSESSMENT_PROMPT,
        trial_record=trial_dir / "trial.yaml",
        ground_truth=Path(args.ground_truth) if args.ground_truth else Path("<ground-truth>"),
        data_root=Path(args.data_root) if args.data_root else Path("<data-root>"),
        destination=trial_dir / verdicts.VERDICTS_FILENAME,
    )


def _assessment_request(args, run: TargetRun, trial_dir: Path) -> assessment.AssessmentRequest:
    return assessment.AssessmentRequest(
        prompt=assessment.ASSESSMENT_PROMPT,
        trial_record=trial_dir / "trial.yaml",
        ground_truth=_ground_truth_for(args, run),
        data_root=_assessment_data_root(args),
        destination=trial_dir / verdicts.VERDICTS_FILENAME,
    )


def _make_dispatcher(args, runner_factory: RunnerFactory,
                     dispatch_factory: DispatchFactory | None):
    argv = _assessment_argv(args)
    if dispatch_factory is not None:
        return dispatch_factory(argv)
    return assessment.CommandDispatcher(runner_factory(), argv)


def _prior_attempts(payload: dict) -> list[trial.AssessmentAttempt]:
    raw = (payload.get("assessment") or {}).get("attempts") or []
    return [trial.AssessmentAttempt(**entry) for entry in raw]


def _run_assess(args, setup: EvalSetup, out: TextIO, err: TextIO,
                runner_factory: RunnerFactory,
                dispatch_factory: DispatchFactory | None) -> int:
    files = FileStore()
    trial_dir = Path(args.trial)
    record_path = trial_dir / "trial.yaml"

    if args.dry_run:
        command = assessment.plan_dispatch(_plan_request(args, trial_dir), _assessment_argv(args))
        print(command.display(), file=out)
        return 0

    payload = assessment.load_trial_record(record_path, files=files)
    run = _find_target_run(setup, str(payload.get("target_id") or ""))
    request = _assessment_request(args, run, trial_dir)
    assessment.trial_identity(record_path, files=files)  # refuse a record with no id
    dispatcher = _make_dispatcher(args, runner_factory, dispatch_factory)
    record = assessment.dispatch(
        request, dispatcher=dispatcher, prior=_prior_attempts(payload)
    )
    assessment.record_assessment(record_path, record, files=files)
    print(f"assess {trial_dir.name}: dispatched (attempt {len(record.attempts)})", file=out)
    return 0


def _run_close_verify(args, setup: EvalSetup, out: TextIO, err: TextIO,
                      runner_factory: RunnerFactory,
                      dispatch_factory: DispatchFactory | None) -> int:
    files = FileStore()
    argv = _assessment_argv(args)
    escalated = 0
    checked = 0
    for instance in setup.instances:
        for run in instance.targets:
            for trial_dir in files.list_dirs(Path(args.runs_root) / run.target_id):
                record_path = trial_dir / "trial.yaml"
                if not files.exists(record_path):
                    continue
                checked += 1
                if args.dry_run:
                    request = _plan_request(args, trial_dir)
                    print(f"# {run.target_id}/{trial_dir.name}", file=out)
                    print(f"  check {request.destination}", file=out)
                    print(f"  {assessment.plan_dispatch(request, argv).display()}", file=out)
                    continue
                request = _assessment_request(args, run, trial_dir)
                payload = assessment.load_trial_record(record_path, files=files)
                sha, fingerprint = assessment.trial_identity(record_path, files=files)
                dispatcher = _make_dispatcher(args, runner_factory, dispatch_factory)
                record = assessment.verify_trial(
                    request,
                    dispatcher=dispatcher,
                    files=files,
                    eval_sha=sha,
                    stack_fingerprint=fingerprint,
                    repair=assessment.ReDispatchRepair(dispatcher, request),
                    prior=_prior_attempts(payload),
                )
                assessment.record_assessment(record_path, record, files=files)
                print(f"{run.target_id}/{trial_dir.name}: {record.status}", file=out)
                if record.status != "present":
                    escalated += 1
                    print(
                        f"close-verify: {run.target_id}/{trial_dir.name}: {record.failure}",
                        file=err,
                    )
    if args.dry_run:
        print(f"# close-verify would check {checked} trial(s)", file=out)
        return 0
    return 1 if escalated else 0


def main(
    argv: list[str] | None = None,
    *,
    runner_factory: RunnerFactory = LocalRunner,
    api_factory: ApiFactory | None = None,
    dispatch_factory: DispatchFactory | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    args = _parser().parse_args(argv)

    try:
        setup = load_eval_setup(Path(args.setup))
        config = OrchestratorConfig(
            repo=Path(args.repo),
            instances_root=Path(args.instances_root),
            branch=args.branch,
        )
        if args.verb == "trial":
            factory = api_factory or (lambda base: api.HttpApiRunner(base))
            return _run_trial(args, setup, config, out, err, runner_factory, factory)
        if args.verb == "assess":
            return _run_assess(args, setup, out, err, runner_factory, dispatch_factory)
        if args.verb == "close-verify":
            return _run_close_verify(args, setup, out, err, runner_factory, dispatch_factory)

        dry_run = args.verb == "plan" or getattr(args, "dry_run", False)
        if dry_run:
            _print_plan(Orchestrator(setup, config).plan(), out)
            return 0

        orchestrator = Orchestrator(setup, config, runner=runner_factory())
        if args.verb == "up":
            _print_results(orchestrator.up(), out)
        elif args.verb == "down":
            errors = orchestrator.down()
            for error in errors:
                print(f"down: error: {error}", file=err)
            if errors:
                return 1
            print("down: complete", file=out)
        else:
            for instance_id, report in orchestrator.status().items():
                print(f"instance {instance_id}:\n{report['stack']}", file=out)
                aliases = report.get("aliases") or {}
                if "error" in aliases:
                    print(f"  kali aliases: unavailable ({aliases['error']})", file=out)
                elif aliases:
                    rendered = ", ".join(
                        f"{host} -> {ip}" for host, ip in sorted(aliases.items())
                    )
                    print(f"  kali aliases: {rendered}", file=out)
                else:
                    print("  kali aliases: none", file=out)
                for target_id, target in report["targets"].items():
                    print(
                        f"  target {target_id}: {target['host']} {target['front_url']}"
                        f" -> {target['status'].strip()}",
                        file=out,
                    )
        return 0
    except _HANDLED as exc:
        print(f"orchestrator: error: {exc}", file=err)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
