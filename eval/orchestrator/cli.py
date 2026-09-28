"""The `python -m orchestrator` entry point.

`plan` and `up --dry-run` print every command and never construct a runner;
`up`, `down`, and `status` inject the thin local runner. The runner factory is
a parameter so plan mode's "execute nothing" is provable in a test.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable, TextIO

from orchestrator.commands import LocalRunner
from orchestrator.instances import InstanceError
from orchestrator.orchestrator import (
    InstanceResult,
    Orchestrator,
    OrchestratorConfig,
    OrchestratorError,
    PlanStep,
)
from orchestrator.setup import SetupError, load_eval_setup
from orchestrator.targets.base import TargetError
from orchestrator.workitems import WorkItemGateError

DEFAULT_INSTANCES_ROOT = "eval/instances"
DEFAULT_BRANCH = "eval"

RunnerFactory = Callable[[], object]
_HANDLED = (
    SetupError,
    WorkItemGateError,
    InstanceError,
    TargetError,
    OrchestratorError,
    OSError,
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
        child.add_argument("setup", help="path to the EvalSetup YAML")
        child.add_argument(
            "--repo",
            default=os.environ.get("EVAL_REPO", "."),
            help="the canonical eval checkout (git worktrees are added from it)",
        )
        child.add_argument(
            "--instances-root",
            default=os.environ.get("EVAL_INSTANCES_ROOT", DEFAULT_INSTANCES_ROOT),
            help="where per-instance worktrees live",
        )
        child.add_argument(
            "--branch",
            default=os.environ.get("EVAL_BRANCH", DEFAULT_BRANCH),
            help="the read-only branch instances run from",
        )
    sub.choices["up"].add_argument(
        "--dry-run", action="store_true", help="print the plan without executing"
    )
    return parser


def _print_plan(steps: list[PlanStep], out: TextIO) -> None:
    for step in steps:
        print(f"# {step.label}", file=out)
        for command in step.commands:
            print(f"  {command.display()}", file=out)


def _print_results(results: list[InstanceResult], out: TextIO) -> None:
    for instance in results:
        print(f"instance {instance.instance_id}: up", file=out)
        for target in instance.targets:
            print(
                f"  target {target.host}: {target.front_url} -> {target.backend}",
                file=out,
            )


def main(
    argv: list[str] | None = None,
    *,
    runner_factory: RunnerFactory = LocalRunner,
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
        dry_run = args.verb == "plan" or getattr(args, "dry_run", False)
        if dry_run:
            _print_plan(Orchestrator(setup, config).plan(), out)
            return 0

        orchestrator = Orchestrator(setup, config, runner=runner_factory())
        if args.verb == "up":
            _print_results(orchestrator.up(), out)
        elif args.verb == "down":
            orchestrator.down()
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
