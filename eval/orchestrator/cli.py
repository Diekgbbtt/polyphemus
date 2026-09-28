"""The `python -m orchestrator` entry point.

`plan`, `trial --dry-run`, and `up --dry-run` print every command and never
construct a runner; `up`, `down`, `status`, and `trial` inject the thin local
runner (and the trial additionally the HTTP API runner). The runner factories
are parameters so plan mode's "execute nothing" is provable in a test.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable, TextIO

from orchestrator import api, instances, trial
from orchestrator.commands import LocalRunner
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
_HANDLED = (
    SetupError,
    WorkItemGateError,
    InstanceError,
    TargetError,
    OrchestratorError,
    trial.TrialError,
    trial.EscalationError,
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
        "--dry-run", action="store_true", help="print the plan without executing"
    )
    return parser


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


def main(
    argv: list[str] | None = None,
    *,
    runner_factory: RunnerFactory = LocalRunner,
    api_factory: ApiFactory | None = None,
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
