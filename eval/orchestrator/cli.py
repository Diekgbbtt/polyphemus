"""The `python -m orchestrator` entry point.

`plan`, `trial --dry-run`, and `up --dry-run` print every command and never
construct a runner; `up`, `down`, `status`, and `trial` inject the thin local
runner (and the trial additionally the HTTP API runner). The runner factories
are parameters so plan mode's "execute nothing" is provable in a test.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Sequence, TextIO

import yaml

from orchestrator import api, assessment, chain as chain_mod, diagnosis, evidence, instances, monitor, routing, store, subagents, surfer, trial, verdicts
from orchestrator import alignment
from orchestrator.dataset import (
    BenchmarkDataset,
    DatasetError,
    load_benchmark_dataset,
    resolve_target_key,
)
from orchestrator.datasets import helper_for
from orchestrator.target_config import load_target_configuration
from orchestrator.targets import build_strategy
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
from orchestrator.setup import (
    EvalSetup,
    Instance,
    SetupError,
    TargetRun,
    is_path_safe_id,
    load_eval_setup,
)
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
# The diagnoser dispatcher factory (#272).
DiagnoseDispatchFactory = Callable[[tuple[str, ...]], diagnosis.SubagentDispatcher]
# The issue-bank factory: builds a read-only bank for the `issue-search` verb.
IssueBankFactory = Callable[[], diagnosis.IssueBank]
_HANDLED = (
    SetupError,
    DatasetError,
    WorkItemGateError,
    InstanceError,
    TargetError,
    OrchestratorError,
    trial.TrialError,
    trial.EscalationError,
    api.ApiError,
    subagents.CommandTemplateError,
    assessment.AssessmentError,
    diagnosis.DiagnosisError,
    evidence.EvidenceError,
    verdicts.VerdictError,
    store.StoreError,
    alignment.AlignmentError,
    surfer.SurferError,
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
    parser.add_argument(
        "--state",
        default=os.environ.get("EVAL_ALIGNMENT_STATE", str(alignment.DEFAULT_STATE_PATH)),
        help="the alignment state file (holds and applied actions); an "
        "unresolved hold blocks `up` and `trial`",
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
    # `plan` already executes nothing; the flag is accepted so the documented
    # `plan <setup> --dry-run` invocation (E2E-SCAFFOLD.md) parses rather than
    # tripping argparse's unrecognized-argument error.
    sub.choices["plan"].add_argument(
        "--dry-run", action="store_true", help="accepted for symmetry; plan is always dry"
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
    run_parser.add_argument(
        "--existing-project-id",
        default=os.environ.get("EVAL_EXISTING_PROJECT_ID"),
        help="hunt against a pre-recon'd project whose L0/L1 already exists "
        "(skips project creation, settings, the auth mutation, and the L1 "
        "scaffold); the target must start at hunting (#277)",
    )
    run_parser.add_argument("--recon-run", help="the recon run a later phase drains")
    run_parser.add_argument(
        "--target-run-id",
        default=os.environ.get("EVAL_TARGET_RUN_ID"),
        help="the target-run identity (artifact store middle level); overrides "
        "the setup's target_run_id, and defaults to the instance id when unset",
    )
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
        "--trace-id",
        default=os.environ.get("EVAL_TRACE_ID"),
        help="the trace id this trial ran under (stamped into the record and "
        "substituted into the assessment/diagnosis {trace_id}); no production "
        "reasoning source is wired yet, so the reasoning refs stay empty",
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
        help="verify every trial's verdicts.yaml and diagnoses.yaml pairing",
    )
    _common_args(close_parser)
    _assessment_args(close_parser)
    _diagnosis_args(close_parser)

    # --- the tick control plane (#289) ----------------------------------------
    monitor_parser = sub.add_parser(
        "monitor",
        help="one tick of the post-execution workflow control plane",
    )
    _common_args(monitor_parser)
    _assessment_args(monitor_parser)
    _diagnosis_args(monitor_parser)
    monitor_parser.add_argument(
        "--budget-s",
        type=float,
        default=float(os.environ.get("EVAL_MONITOR_BUDGET_S", 3600.0)),
        help="the wait between a node's dispatch and its re-dispatch/escalation "
        "decision",
    )

    # --- the target chain (multi-target scaffold) -----------------------------
    chain_parser = sub.add_parser(
        "next-target",
        help="advance the chain: reclaim the previous image, pull the next, "
        "bring it up, verify health",
    )
    _common_args(chain_parser)
    chain_parser.add_argument("--instance", required=True, help="the instance id")
    chain_parser.add_argument(
        "--target", required=True, help="the target_id to advance the chain to"
    )
    chain_parser.add_argument(
        "--chain-state",
        default=os.environ.get("EVAL_CHAIN_STATE"),
        help="the chain position file (default: "
        "<instances-root>/<instance_id>/chain-state.yaml)",
    )

    # --- the diagnosis verbs (#272) -------------------------------------------
    diag_parser = sub.add_parser(
        "diagnose", help="dispatch the background diagnoser subagent for one trial"
    )
    _common_args(diag_parser)
    diag_parser.add_argument("--trial", required=True, help="the trial directory")
    _paths_args(diag_parser)
    _diagnosis_args(diag_parser)

    # `issue-search` is deliberately standalone (no setup): it is the read-only
    # issue-bank primitive the diagnoser prompt invokes.
    search_parser = sub.add_parser(
        "issue-search", help="read-only GitHub issue-bank search; never files"
    )
    search_parser.add_argument("query", help="the free-text search query")
    search_parser.add_argument(
        "--repo",
        default=os.environ.get("EVAL_ISSUE_REPO"),
        help="scope the search to one repository (owner/name)",
    )
    search_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="the maximum number of relevance-ordered hits to return",
    )

    # --- the artifact store verbs (#273) --------------------------------------
    store_parser = sub.add_parser(
        "store", help="render one-way syncs and materialize finished trials"
    )
    store_sub = store_parser.add_subparsers(dest="store_verb", required=True)

    sync_parser = store_sub.add_parser(
        "render-sync", help="render the per-instance lsyncd configs and systemd units"
    )
    _common_args(sync_parser)
    sync_parser.add_argument(
        "--out",
        default=os.environ.get("EVAL_STORE_SYNC_DIR"),
        help="where to write the rendered files (default: <artifact_store>/_sync)",
    )
    sync_parser.add_argument(
        "--data-root",
        default=os.environ.get("EVAL_DATA_ROOT"),
        help="override the per-instance data root (single-instance hosts)",
    )
    sync_parser.add_argument(
        "--dry-run", action="store_true", help="print the plan without writing"
    )

    materialize_parser = store_sub.add_parser(
        "materialize", help="assemble one finished trial into the per-trial tree"
    )
    _common_args(materialize_parser)
    materialize_parser.add_argument(
        "--trial", required=True, help="the source trial directory"
    )
    materialize_parser.add_argument(
        "--data-root",
        default=os.environ.get("EVAL_DATA_ROOT"),
        help="the instance data root (default: <instances-root>/<instance>/data)",
    )
    materialize_parser.add_argument(
        "--dry-run", action="store_true", help="print the plan without writing"
    )

    # --- the alignment verbs (#274) -------------------------------------------
    align_parser = sub.add_parser(
        "align", help="assert the advance delta and execute the alignment decision"
    )
    _common_args(align_parser)
    align_parser.add_argument(
        "--instance", help="restrict the alignment to one instance of the EvalSetup"
    )
    align_parser.add_argument(
        "--decision-file",
        default=os.environ.get("EVAL_ALIGN_DECISION"),
        help="a decision-input YAML (default: the latest decision in the heartbeat)",
    )
    align_parser.add_argument(
        "--heartbeat",
        default=os.environ.get("EVAL_ADVANCE_HEARTBEAT", str(alignment.DEFAULT_HEARTBEAT_PATH)),
        help="the sync daemon heartbeat carrying the latest decision input",
    )
    align_parser.add_argument(
        "--command",
        default=os.environ.get("EVAL_ALIGN_COMMAND"),
        help="the alignment agent command line; placeholders: {prompt} {input} {destination}",
    )
    align_parser.add_argument(
        "--dry-run", action="store_true", help="plan the alignment actions without executing"
    )

    align_group = sub.add_parser("alignment", help="alignment hold management")
    align_sub = align_group.add_subparsers(dest="alignment_verb", required=True)
    resolve_parser = align_sub.add_parser(
        "resolve", help="record the operator's decision and clear a hold"
    )
    _common_args(resolve_parser)
    resolve_parser.add_argument("--hold-id", required=True, help="the hold to resolve")
    resolve_parser.add_argument(
        "--decision", required=True, help="the operator's decision, recorded on the hold"
    )

    # --- the surfer loop (#275) -----------------------------------------------
    surfer_parser = sub.add_parser(
        "surfer",
        help="assert instance state and recover a cap-reached or failed run",
    )
    _common_args(surfer_parser)
    surfer_parser.add_argument(
        "--api",
        default=os.environ.get("PH_API", DEFAULT_API),
        help="the instance polymerhus API base URL (the app-state source)",
    )
    surfer_parser.add_argument(
        "--dsn",
        default=os.environ.get("EVAL_PG_DSN"),
        help="the postgres DSN for the app-state fallback (unknown is never idle)",
    )
    surfer_parser.add_argument(
        "--data-root",
        default=os.environ.get("EVAL_DATA_ROOT"),
        help="the instance's app data root (the bounded repair's scope)",
    )
    surfer_parser.add_argument(
        "--runs-root",
        default=os.environ.get("EVAL_RUNS_ROOT", DEFAULT_RUNS_ROOT),
        help="where per-trial record directories live",
    )
    surfer_parser.add_argument(
        "--interval-s",
        type=float,
        default=float(os.environ.get("EVAL_SURFER_INTERVAL_S", 60.0)),
        help="the poll interval between cycles",
    )
    surfer_parser.add_argument(
        "--once",
        action="store_true",
        help="perform exactly one poll-assert-decide cycle (the testable unit)",
    )
    surfer_parser.add_argument(
        "--command",
        default=os.environ.get("EVAL_SURFER_COMMAND"),
        help="the surfer agent command line; placeholders: {prompt} {input} {destination}",
    )
    surfer_parser.add_argument("--budget-s", type=float, default=7200.0)
    surfer_parser.add_argument("--poll-s", type=float, default=15.0)
    surfer_parser.add_argument("--eval-sha", default=os.environ.get("EVAL_SHA"))
    surfer_parser.add_argument(
        "--stack-fingerprint", default=os.environ.get("EVAL_STACK_FINGERPRINT")
    )
    surfer_parser.add_argument("--trace-id", default=os.environ.get("EVAL_TRACE_ID"))
    surfer_parser.add_argument(
        "--dry-run", action="store_true", help="assert the state and dispatch nothing"
    )
    return parser


def _paths_args(parser: argparse.ArgumentParser) -> None:
    """The path/plan knobs shared by `assess`, `diagnose`, and `close-verify`."""
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
        "--dry-run", action="store_true", help="print the plan without dispatching"
    )


def _assessment_args(parser: argparse.ArgumentParser) -> None:
    """The shared knobs of the `assess`/`close-verify` verbs (D15/D6)."""
    _paths_args(parser)
    parser.add_argument(
        "--command",
        default=os.environ.get("EVAL_ASSESS_COMMAND"),
        help="the assessment agent command line; placeholders: {prompt} "
        "{trial_record} {ground_truth} {data_root} {destination} {trace_id}",
    )


def _diagnosis_args(parser: argparse.ArgumentParser) -> None:
    """The diagnoser knob shared by `diagnose` and `close-verify` (D19/D22)."""
    parser.add_argument(
        "--diagnose-command",
        default=os.environ.get("EVAL_DIAGNOSE_COMMAND"),
        help="the diagnoser agent command line; placeholders: {prompt} "
        "{trial_record} {verdicts} {ground_truth} {data_root} {destination} "
        "{vulns} {trace_id}",
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


# --- the keyed dataset/target resolution (spec #301) --------------------------


def _dataset_path(repo: Path, dataset_id: str) -> Path:
    return Path(repo) / "eval" / "datasets" / f"{dataset_id}.yaml"


def _load_datasets(setup: EvalSetup, repo: Path) -> dict[str, BenchmarkDataset]:
    """Every dataset the setup lists, by key, resolved under `<repo>/eval/datasets`."""
    return {
        dataset_id: load_benchmark_dataset(_dataset_path(repo, dataset_id))
        for dataset_id in setup.datasets
    }


def _resolve_dataset(
    setup: EvalSetup,
    run: TargetRun,
    *,
    repo: Path,
    datasets: dict[str, BenchmarkDataset] | None = None,
) -> BenchmarkDataset:
    """The dataset a run's `<dataset>/<target>` key names, validated against the setup."""
    dataset_id, target = resolve_target_key(run.target_key)
    if datasets is None:
        datasets = _load_datasets(setup, repo)
    dataset = datasets.get(dataset_id)
    if dataset is None:
        raise SetupError(
            f"target {run.target_id!r} names dataset {dataset_id!r}, which the "
            "EvalSetup does not list in `datasets`"
        )
    dataset.require_target(target)
    return dataset


def _dataset_and_config(
    setup: EvalSetup,
    run: TargetRun,
    *,
    repo: Path,
    datasets: dict[str, BenchmarkDataset] | None = None,
):
    """The `(dataset, target_config)` a run's key resolves to, config read fresh."""
    dataset = _resolve_dataset(setup, run, repo=repo, datasets=datasets)
    _, target = resolve_target_key(run.target_key)
    config = load_target_configuration(dataset.target_config_search(target))
    return dataset, config


def _strategy_for_factory(
    setup: EvalSetup,
    paths: "instances.InstancePaths",
    repo: Path,
    *,
    env=None,
    sleep=None,
):
    """A `TargetRun` -> strategy builder bound to one instance's paths.

    The datasets and their helpers are resolved once per factory; each step loads
    its target config from the run's key, so the chain and the config cannot
    drift. `build_strategy`'s frozen signature is `(target_config, dataset,
    helper, paths, run, ...)`.
    """
    datasets = _load_datasets(setup, repo)
    helpers = {key: helper_for(dataset) for key, dataset in datasets.items()}

    def build(run: TargetRun):
        dataset, config = _dataset_and_config(setup, run, repo=repo, datasets=datasets)
        return build_strategy(
            config, dataset, helpers[dataset.id], paths, run, env=env, sleep=sleep
        )

    return build


def _operator_kb(setup: EvalSetup, run: TargetRun, repo: Path) -> str | None:
    """The run's operator KB, or the dataset's data-dir default when it carries one."""
    declared = run.target_config.operator_kb
    if declared:
        candidate = Path(declared)
        return str(candidate if candidate.is_absolute() else Path(repo) / candidate)
    dataset = _resolve_dataset(setup, run, repo=repo)
    default = dataset.data_dir(run.target) / "operator_kb.md"
    return str(default) if default.is_file() else None


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
    kb = _operator_kb(setup, run, args.repo)
    scaffold = None
    if run.start_phase == "recon" and kb:
        scaffold = trial.ScaffoldSpec(cwd=str(paths.worktree), kb=kb)
    # #273: the CLI override wins over the setup's target_run_id; the trial
    # record still defaults to the instance id when both leave it unset.
    target_run_id = args.target_run_id or run.target_run_id
    if target_run_id is not None and not is_path_safe_id(target_run_id):
        raise SetupError(
            f"target_run_id: expected a path-safe identifier, got {target_run_id!r}"
        )
    # #277: the CLI flag overrides a setup declaration, like target_run_id. A
    # seeded trial enters at hunting by construction, so an explicit recon or
    # analysis phase is contradictory and refused here, never silently ignored.
    existing_project_id = args.existing_project_id or run.existing_project_id
    if existing_project_id is not None:
        if not is_path_safe_id(existing_project_id):
            raise SetupError(
                f"existing_project_id: expected a path-safe identifier, "
                f"got {existing_project_id!r}"
            )
        if run.start_phase != "hunting":
            raise SetupError(
                f"existing_project_id is set but start_phase is "
                f"{run.start_phase!r}; a seeded project must start at hunting"
            )
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
        # The seed the scope gate requires is the bare synthetic Host. When the
        # setup leaves it unset, derive it from the same `<instance>/<target>`
        # identity the front and routing use, so a run cannot be routed but
        # seeded differently (a setup that pins it still wins).
        target_seed=run.target_config.target_seed
        or routing.synthetic_host(f"{instance.instance_id}/{run.target_id}"),
        operator_kb=kb,
        auth=run.target_config.auth,
        auth_surface=run.target_config.auth is not None,
        preloaded_hunting_artifacts=run.preloaded_hunting_artifacts,
        hunt_config_budget=run.hunt_config_budget,
        target_run_id=target_run_id,
        data_root=data_root,
        runs_root=Path(args.runs_root),
        with_analysis=True,
        scaffold=scaffold,
        budget_s=args.budget_s,
        poll_s=args.poll_s,
        project_id=args.project_id,
        recon_run_id=args.recon_run,
        existing_project_id=existing_project_id,
        eval_sha=args.eval_sha,
        stack_fingerprint=args.stack_fingerprint,
        trace_id=args.trace_id,
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
        if phase.failure:
            print(f"    failed: {phase.failure}", file=err)
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
    # I2: a failed or timed-out run is a handled failure (the record is written
    # and printed), so exit non-zero instead of reporting success.
    return 1 if record.terminal in ("failed", "timeout") else 0


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
    # The target segment of the key is the ground-truth name gt.py resolves.
    return assessment.resolve_ground_truth(run.target)


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


def _assessment_request(
    args, run: TargetRun, trial_dir: Path, *, trace_id: str | None = None
) -> assessment.AssessmentRequest:
    return assessment.AssessmentRequest(
        prompt=assessment.ASSESSMENT_PROMPT,
        trial_record=trial_dir / "trial.yaml",
        ground_truth=_ground_truth_for(args, run),
        data_root=_assessment_data_root(args),
        destination=trial_dir / verdicts.VERDICTS_FILENAME,
        trace_id=trace_id,
    )


def _trace_id_of(payload: dict) -> str | None:
    """The trial record's trace id, when one was recorded."""
    value = payload.get("trace_id")
    return str(value) if value else None


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
    request = _assessment_request(args, run, trial_dir, trace_id=_trace_id_of(payload))
    assessment.trial_identity(record_path, files=files)  # refuse a record with no id
    dispatcher = _make_dispatcher(args, runner_factory, dispatch_factory)
    record = assessment.dispatch(
        request, dispatcher=dispatcher, prior=_prior_attempts(payload)
    )
    assessment.record_assessment(record_path, record, files=files)
    print(f"assess {trial_dir.name}: dispatched (attempt {len(record.attempts)})", file=out)
    return 0


# --- diagnosis (#272) ---------------------------------------------------------


def _diagnosis_argv(args) -> tuple[str, ...]:
    if not args.diagnose_command:
        raise diagnosis.DiagnosisError(
            "no diagnoser command configured; pass --diagnose-command or "
            "EVAL_DIAGNOSE_COMMAND"
        )
    return tuple(shlex.split(args.diagnose_command))


def _make_diagnosis_dispatcher(args, runner_factory: RunnerFactory,
                               factory: DiagnoseDispatchFactory | None):
    argv = _diagnosis_argv(args)
    if factory is not None:
        return factory(argv)
    return diagnosis.CommandDispatcher(runner_factory(), argv)


def _prior_diagnosis_attempts(payload: dict) -> list[trial.DiagnosisAttempt]:
    raw = (payload.get("diagnosis") or {}).get("attempts") or []
    return [trial.DiagnosisAttempt(**entry) for entry in raw]


def _load_verdicts(args, run: TargetRun, trial_dir: Path, files: FileStore,
                   sha: str, fingerprint: str):
    return verdicts.load_verdicts(
        trial_dir / verdicts.VERDICTS_FILENAME,
        files=files,
        data_root=_assessment_data_root(args),
        eval_sha=sha,
        stack_fingerprint=fingerprint,
    )


def _diagnosis_request(
    args,
    run: TargetRun,
    trial_dir: Path,
    vulns,
    *,
    trace_id: str | None = None,
) -> diagnosis.DiagnosisRequest:
    return diagnosis.DiagnosisRequest(
        prompt=diagnosis.DIAGNOSER_PROMPT,
        trial_record=trial_dir / "trial.yaml",
        verdicts=trial_dir / verdicts.VERDICTS_FILENAME,
        ground_truth=_ground_truth_for(args, run),
        data_root=_assessment_data_root(args),
        destination=trial_dir / diagnosis.DIAGNOSES_FILENAME,
        vulns=tuple(vulns),
        trace_id=trace_id,
    )


def _diagnosis_plan_request(args, trial_dir: Path, vulns) -> diagnosis.DiagnosisRequest:
    """A dispatch-free request for plan mode: explicit paths or placeholders."""
    return diagnosis.DiagnosisRequest(
        prompt=diagnosis.DIAGNOSER_PROMPT,
        trial_record=trial_dir / "trial.yaml",
        verdicts=trial_dir / verdicts.VERDICTS_FILENAME,
        ground_truth=Path(args.ground_truth) if args.ground_truth else Path("<ground-truth>"),
        data_root=Path(args.data_root) if args.data_root else Path("<data-root>"),
        destination=trial_dir / diagnosis.DIAGNOSES_FILENAME,
        vulns=tuple(vulns),
    )


def _run_diagnose(args, setup: EvalSetup, out: TextIO, err: TextIO,
                  runner_factory: RunnerFactory,
                  factory: DiagnoseDispatchFactory | None) -> int:
    files = FileStore()
    trial_dir = Path(args.trial)
    record_path = trial_dir / "trial.yaml"

    if args.dry_run:
        vulns = _plan_required_vulns(args, trial_dir, files)
        request = _diagnosis_plan_request(args, trial_dir, vulns)
        print(diagnosis.plan_dispatch(request, _diagnosis_argv(args)).display(), file=out)
        return 0

    payload = assessment.load_trial_record(record_path, files=files)
    run = _find_target_run(setup, str(payload.get("target_id") or ""))
    sha, fingerprint = assessment.trial_identity(record_path, files=files)
    verdict_rows = _load_verdicts(args, run, trial_dir, files, sha, fingerprint)
    vulns = diagnosis.required_vulns(verdict_rows)
    request = _diagnosis_request(args, run, trial_dir, vulns, trace_id=_trace_id_of(payload))
    if not vulns:
        record = diagnosis.verify_diagnoses(
            request, dispatcher=_noop_dispatcher, files=files, verdicts=verdict_rows,
            eval_sha=sha, stack_fingerprint=fingerprint,
            prior=_prior_diagnosis_attempts(payload),
        )
        diagnosis.record_diagnosis(record_path, record, files=files)
        print(f"diagnose {trial_dir.name}: not_required (all identified)", file=out)
        return 0
    dispatcher = _make_diagnosis_dispatcher(args, runner_factory, factory)
    record = diagnosis.dispatch(
        request, dispatcher=dispatcher, prior=_prior_diagnosis_attempts(payload)
    )
    diagnosis.record_diagnosis(record_path, record, files=files)
    print(
        f"diagnose {trial_dir.name}: dispatched (attempt {len(record.attempts)}, "
        f"vulns {', '.join(vulns)})",
        file=out,
    )
    return 0


def _noop_dispatcher(request) -> None:  # pragma: no cover - only the not_required branch
    raise diagnosis.DiagnosisError("no diagnosis entries are required")


def _noop_assessment_dispatcher(request) -> None:  # pragma: no cover - short-circuit only
    raise assessment.AssessmentError("no assessment dispatch was needed")


def _plan_required_vulns(args, trial_dir: Path, files: FileStore) -> tuple[str, ...]:
    """Best-effort required vulns for plan mode; no live root resolution."""
    path = trial_dir / verdicts.VERDICTS_FILENAME
    if not files.exists(path):
        return ()
    try:
        payload = yaml.safe_load(files.read_text(path))
    except yaml.YAMLError:
        return ()
    if not isinstance(payload, list):
        return ()
    return tuple(
        str(row.get("vuln_id"))
        for row in payload
        if isinstance(row, dict) and row.get("identified") in diagnosis.DIAGNOSABLE
    )


def _close_verify_diagnosis(args, run: TargetRun, trial_dir: Path, files: FileStore,
                            runner_factory: RunnerFactory,
                            factory: DiagnoseDispatchFactory | None, *,
                            sha: str, fingerprint: str,
                            prior: list[trial.DiagnosisAttempt],
                            trace_id: str | None = None) -> trial.DiagnosisRecord | None:
    """The paired `diagnoses.yaml` check for one trial, once verdicts are present."""
    try:
        verdict_rows = _load_verdicts(args, run, trial_dir, files, sha, fingerprint)
    except (verdicts.VerdictError, OSError):
        return None  # the verdict check already owns this failure
    request = _diagnosis_request(
        args, run, trial_dir, diagnosis.required_vulns(verdict_rows), trace_id=trace_id
    )
    if not diagnosis.required_vulns(verdict_rows):
        return diagnosis.verify_diagnoses(
            request, dispatcher=_noop_dispatcher, files=files, verdicts=verdict_rows,
            eval_sha=sha, stack_fingerprint=fingerprint,
            prior=prior,
        )
    # A present, paired file needs no dispatcher at all: short-circuit before the
    # factory runs, so a dry or already-complete close never constructs a command.
    if (
        diagnosis.check_diagnoses(
            request,
            files=files,
            verdicts=verdict_rows,
            eval_sha=sha,
            stack_fingerprint=fingerprint,
        )
        == "present"
    ):
        return diagnosis.verify_diagnoses(
            request, dispatcher=_noop_dispatcher, files=files, verdicts=verdict_rows,
            eval_sha=sha, stack_fingerprint=fingerprint,
            prior=prior,
        )
    try:
        dispatcher = _make_diagnosis_dispatcher(args, runner_factory, factory)
    except diagnosis.DiagnosisError:
        return trial.DiagnosisRecord(
            "escalated",
            list(prior),
            str(request.destination),
            failure="diagnosis_no_command",
        )
    return diagnosis.verify_diagnoses(
        request,
        dispatcher=dispatcher,
        files=files,
        verdicts=verdict_rows,
        eval_sha=sha,
        stack_fingerprint=fingerprint,
        repair=diagnosis.DiagnoserReDispatchRepair(dispatcher, request),
        prior=prior,
    )


def _run_close_verify(args, setup: EvalSetup, out: TextIO, err: TextIO,
                      runner_factory: RunnerFactory,
                      dispatch_factory: DispatchFactory | None,
                      diagnose_dispatch_factory: DiagnoseDispatchFactory | None = None) -> int:
    files = FileStore()
    # Only plan mode needs the rendered command; execution constructs the
    # dispatcher per trial, and only when a re-dispatch is actually needed.
    argv = _assessment_argv(args) if args.dry_run else ()
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
                    vulns = _plan_required_vulns(args, trial_dir, files)
                    if vulns:
                        diag_request = _diagnosis_plan_request(args, trial_dir, vulns)
                        print(f"  check {diag_request.destination}", file=out)
                        planned = diagnosis.plan_dispatch(diag_request, _diagnosis_argv(args))
                        print(f"  {planned.display()}", file=out)
                    continue
                # The identity and the ground truth are resolved per trial: a
                # record without identity, or a target with no resolvable
                # ground-truth name, is escalated on its own and the pass
                # continues with the rest.
                try:
                    payload = assessment.load_trial_record(record_path, files=files)
                    sha, fingerprint = assessment.trial_identity(record_path, files=files)
                except assessment.AssessmentError as exc:
                    escalated += 1
                    print(
                        f"close-verify: {run.target_id}/{trial_dir.name}: "
                        f"identity_missing: {exc}",
                        file=err,
                    )
                    continue
                try:
                    request = _assessment_request(
                        args, run, trial_dir, trace_id=_trace_id_of(payload)
                    )
                except assessment.AssessmentError as exc:
                    escalated += 1
                    print(
                        f"close-verify: {run.target_id}/{trial_dir.name}: "
                        f"ground_truth_missing: {exc}",
                        file=err,
                    )
                    continue
                # Mirror the diagnosis path: a present, valid file needs no
                # dispatcher, so the configured command is never constructed.
                if (
                    assessment.check_verdicts(
                        request,
                        files=files,
                        eval_sha=sha,
                        stack_fingerprint=fingerprint,
                    )
                    == "present"
                ):
                    dispatcher = _noop_assessment_dispatcher
                    repair = None
                else:
                    try:
                        dispatcher = _make_dispatcher(args, runner_factory, dispatch_factory)
                    except assessment.AssessmentError:
                        record = trial.AssessmentRecord(
                            "escalated",
                            list(_prior_attempts(payload)),
                            str(request.destination),
                            failure="assessment_no_command",
                        )
                        assessment.record_assessment(record_path, record, files=files)
                        escalated += 1
                        print(
                            f"close-verify: {run.target_id}/{trial_dir.name}: "
                            "assessment_no_command",
                            file=err,
                        )
                        continue
                    repair = assessment.ReDispatchRepair(dispatcher, request)
                record = assessment.verify_trial(
                    request,
                    dispatcher=dispatcher,
                    files=files,
                    eval_sha=sha,
                    stack_fingerprint=fingerprint,
                    repair=repair,
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
                    continue
                payload = assessment.load_trial_record(record_path, files=files)
                diag_record = _close_verify_diagnosis(
                    args, run, trial_dir, files, runner_factory,
                    diagnose_dispatch_factory,
                    sha=sha, fingerprint=fingerprint,
                    prior=_prior_diagnosis_attempts(payload),
                    trace_id=_trace_id_of(payload),
                )
                if diag_record is None:
                    continue
                diagnosis.record_diagnosis(record_path, diag_record, files=files)
                print(f"{run.target_id}/{trial_dir.name}: diagnosis {diag_record.status}", file=out)
                if diag_record.status not in ("present", "not_required"):
                    escalated += 1
                    print(
                        f"close-verify: {run.target_id}/{trial_dir.name}: {diag_record.failure}",
                        file=err,
                    )
    if args.dry_run:
        print(f"# close-verify would check {checked} trial(s)", file=out)
        return 0
    return 1 if escalated else 0


# --- the tick control plane (#289) --------------------------------------------


def _attempt_views(attempts) -> tuple[monitor.AttemptView, ...]:
    return tuple(monitor.AttemptView(at=a.at, outcome=a.outcome) for a in attempts)


def _node_view(state: str, status: str | None, attempts: Sequence) -> monitor.NodeView:
    return monitor.NodeView(
        state=state, status=status, attempts=_attempt_views(attempts)
    )


@dataclass(frozen=True)
class _MonitorContext:
    """A trial's tick view plus the requests a dispatch at that tick would use."""

    view: monitor.TrialView
    payload: dict
    assessment_request: assessment.AssessmentRequest
    diagnosis_request: diagnosis.DiagnosisRequest | None


def _monitor_trial(args, run: TargetRun, trial_dir: Path, files: FileStore):
    """Build one trial's tick view; None when the trial cannot be read."""
    record_path = trial_dir / "trial.yaml"
    try:
        payload = assessment.load_trial_record(record_path, files=files)
    except assessment.AssessmentError:
        return None
    terminal = str(payload.get("terminal") or "")
    target_id = str(payload.get("target_id") or run.target_id)
    trace_id = _trace_id_of(payload)
    try:
        sha, fingerprint = assessment.trial_identity(record_path, files=files)
    except assessment.AssessmentError:
        sha = fingerprint = None
    try:
        assessment_request = _assessment_request(args, run, trial_dir, trace_id=trace_id)
    except assessment.AssessmentError:
        # No resolvable ground truth: the close verification owns that failure.
        return None

    a_state = assessment.check_verdicts(
        assessment_request, files=files, eval_sha=sha, stack_fingerprint=fingerprint
    )
    a_status = (payload.get("assessment") or {}).get("status")
    a_view = _node_view(a_state, a_status, _prior_attempts(payload))

    diagnosis_request = None
    diagnosis_view = None
    if a_state == "present":
        try:
            verdict_rows = _load_verdicts(args, run, trial_dir, files, sha, fingerprint)
        except (verdicts.VerdictError, OSError):
            verdict_rows = ()
        vulns = diagnosis.required_vulns(verdict_rows)
        if not vulns:
            diagnosis_view = monitor.NodeView(state="present")
        else:
            diagnosis_request = _diagnosis_request(
                args, run, trial_dir, vulns, trace_id=trace_id
            )
            d_state = diagnosis.check_diagnoses(
                diagnosis_request,
                files=files,
                verdicts=verdict_rows,
                eval_sha=sha,
                stack_fingerprint=fingerprint,
            )
            d_status = (payload.get("diagnosis") or {}).get("status")
            diagnosis_view = _node_view(
                d_state, d_status, _prior_diagnosis_attempts(payload)
            )

    view = monitor.TrialView(
        trial_dir=trial_dir,
        target_id=target_id,
        terminal=terminal,
        assessment=a_view,
        diagnosis=diagnosis_view,
    )
    return _MonitorContext(view, payload, assessment_request, diagnosis_request)


def _escalate_assessment(context: _MonitorContext, cause: str, files: FileStore) -> str:
    failure = f"assessment_{cause}"
    record = trial.AssessmentRecord(
        "escalated",
        list(_prior_attempts(context.payload)),
        str(context.assessment_request.destination),
        failure=failure,
    )
    assessment.record_assessment(
        context.view.trial_dir / "trial.yaml", record, files=files
    )
    return failure


def _escalate_diagnosis(context: _MonitorContext, cause: str, files: FileStore) -> str:
    failure = f"diagnosis_{cause}"
    request = context.diagnosis_request
    destination = (
        request.destination
        if request is not None
        else context.view.trial_dir / diagnosis.DIAGNOSES_FILENAME
    )
    record = trial.DiagnosisRecord(
        "escalated",
        list(_prior_diagnosis_attempts(context.payload)),
        str(destination),
        failure=failure,
    )
    diagnosis.record_diagnosis(
        context.view.trial_dir / "trial.yaml", record, files=files
    )
    return failure


def _assessment_error_record(
    context: _MonitorContext, exc: BaseException
) -> trial.AssessmentRecord:
    """Record a raised assessment command as an `error` attempt.

    A command that raises is a dispatch failure, not a missing output: the
    attempt is appended (so the next tick re-dispatches within the bound and
    the eventual escalation names `dispatcher_process`), never escalated here.
    """
    attempts = list(_prior_attempts(context.payload))
    attempts.append(
        trial.AssessmentAttempt(
            len(attempts) + 1, "error", str(exc), subagents.utcnow()
        )
    )
    return trial.AssessmentRecord(
        "dispatched", attempts, str(context.assessment_request.destination)
    )


def _diagnosis_error_record(
    context: _MonitorContext, exc: BaseException
) -> trial.DiagnosisRecord:
    """Record a raised diagnoser command as an `error` attempt (see above)."""
    attempts = list(_prior_diagnosis_attempts(context.payload))
    attempts.append(
        trial.DiagnosisAttempt(
            len(attempts) + 1, "error", str(exc), subagents.utcnow()
        )
    )
    request = context.diagnosis_request
    destination = (
        request.destination
        if request is not None
        else context.view.trial_dir / diagnosis.DIAGNOSES_FILENAME
    )
    return trial.DiagnosisRecord("dispatched", attempts, str(destination))


def _apply_monitor(
    args,
    context: _MonitorContext,
    decision: monitor.TrialDecision,
    *,
    files: FileStore,
    runner_factory: RunnerFactory,
    dispatch_factory: DispatchFactory | None,
    diagnose_dispatch_factory: DiagnoseDispatchFactory | None,
) -> str | None:
    """Apply one tick's decision: dispatch a node, or record its escalation.

    Returns the named failure when the tick escalated the node (including a
    dispatch that could not construct its command), else None.
    """
    record_path = context.view.trial_dir / "trial.yaml"
    if decision.action == monitor.DISPATCH and decision.node == monitor.NODE_ASSESSMENT:
        try:
            dispatcher = _make_dispatcher(args, runner_factory, dispatch_factory)
        except assessment.AssessmentError:
            return _escalate_assessment(context, "no_command", files)
        try:
            record = assessment.dispatch(
                context.assessment_request,
                dispatcher=dispatcher,
                prior=_prior_attempts(context.payload),
            )
        except Exception as exc:  # noqa: BLE001 - the dispatcher outcome is arbitrary
            record = _assessment_error_record(context, exc)
        assessment.record_assessment(record_path, record, files=files)
        return None
    if decision.action == monitor.DISPATCH and decision.node == monitor.NODE_DIAGNOSIS:
        try:
            dispatcher = _make_diagnosis_dispatcher(
                args, runner_factory, diagnose_dispatch_factory
            )
        except diagnosis.DiagnosisError:
            return _escalate_diagnosis(context, "no_command", files)
        try:
            record = diagnosis.dispatch(
                context.diagnosis_request,
                dispatcher=dispatcher,
                prior=_prior_diagnosis_attempts(context.payload),
            )
        except Exception as exc:  # noqa: BLE001 - the dispatcher outcome is arbitrary
            record = _diagnosis_error_record(context, exc)
        diagnosis.record_diagnosis(record_path, record, files=files)
        return None
    if decision.action == monitor.ESCALATE:
        if decision.cause is None:
            # Already escalated on a prior tick: leave its named failure intact.
            return None
        if decision.node == monitor.NODE_ASSESSMENT:
            return _escalate_assessment(context, decision.cause, files)
        return _escalate_diagnosis(context, decision.cause, files)
    return None


def _run_monitor(
    args,
    setup: EvalSetup,
    out: TextIO,
    err: TextIO,
    runner_factory: RunnerFactory,
    dispatch_factory: DispatchFactory | None,
    diagnose_dispatch_factory: DiagnoseDispatchFactory | None,
) -> int:
    """One sweep of the control plane: verify state and advance one node per trial."""
    files = FileStore()
    now = subagents.utcnow()
    tally: dict[str, int] = {}
    escalated = 0
    for instance in setup.instances:
        for run in instance.targets:
            for trial_dir in files.list_dirs(Path(args.runs_root) / run.target_id):
                if not files.exists(trial_dir / "trial.yaml"):
                    continue
                context = _monitor_trial(args, run, trial_dir, files)
                if context is None:
                    continue
                decision = monitor.decide(context.view, now=now, budget_s=args.budget_s)
                tally[decision.state] = tally.get(decision.state, 0) + 1
                label = f"{run.target_id}/{trial_dir.name}"
                if args.dry_run:
                    print(f"{label}: {decision.state} ({decision.node})", file=out)
                    continue
                failure = _apply_monitor(
                    args,
                    context,
                    decision,
                    files=files,
                    runner_factory=runner_factory,
                    dispatch_factory=dispatch_factory,
                    diagnose_dispatch_factory=diagnose_dispatch_factory,
                )
                detail = f": {decision.detail}" if decision.detail else ""
                print(f"{label}: {decision.state} ({decision.node}){detail}", file=out)
                if failure is not None or decision.state == monitor.STATE_ESCALATED:
                    escalated += 1
                    note = failure or decision.detail or "already escalated"
                    print(f"monitor: {label}: escalated: {note}", file=err)
    summary = ", ".join(f"{state}={count}" for state, count in sorted(tally.items()))
    print(f"monitor tick: {summary or 'no trials'}", file=out)
    return 1 if escalated else 0


# --- the target chain (multi-target scaffold) ---------------------------------


def _run_next_target(
    args,
    setup: EvalSetup,
    config: OrchestratorConfig,
    out: TextIO,
    err: TextIO,
    runner_factory: RunnerFactory,
) -> int:
    """Advance one instance's chain by one target; print the step or the trace."""
    instance = _find_instance(setup, args.instance)
    paths = instances.instance_paths(
        instance,
        config.instances_root,
        repo=config.repo,
        branch=config.branch,
        compose_files=config.compose_files,
    )
    state_path = (
        Path(args.chain_state)
        if args.chain_state
        else Path(args.instances_root) / instance.instance_id / "chain-state.yaml"
    )
    chain = chain_mod.Chain(
        instance=instance,
        paths=paths,
        strategy_for=_strategy_for_factory(
            setup, paths, config.repo, env=os.environ
        ),
        runner=runner_factory(),
        files=FileStore(),
        state_path=state_path,
    )
    try:
        step = chain.next_target(args.target)
    except chain_mod.TargetFailure as failure:
        # The full inspectable trace: the step log, the command error, and the
        # Python traceback, so the orchestrator sees exactly what failed.
        print(json.dumps(failure.report(), indent=2), file=err)
        return 1
    print(
        json.dumps(
            {
                "target_id": step.target_id,
                "previous": step.previous,
                "images": list(step.images),
                "reclaimed": list(step.reclaimed),
                "pulled": list(step.pulled),
                "host": step.up.host,
                "front_url": step.up.front_url,
                "backend": step.up.backend,
                "health": step.health,
            },
            indent=2,
        ),
        file=out,
    )
    return 0


# --- artifact store (#273) ----------------------------------------------------


def _run_render_sync(args, setup: EvalSetup, out: TextIO, files: FileStore) -> int:
    plan = store.plan_sync(
        setup,
        instances_root=Path(args.instances_root),
        out_dir=Path(args.out) if args.out else None,
        data_root=Path(args.data_root) if args.data_root else None,
    )
    if args.dry_run:
        for entry in plan.files:
            print(f"# {entry.path}", file=out)
        return 0
    for path in store.write_sync(plan, files=files):
        print(f"write {path}", file=out)
    return 0


def _materialize_data_root(args, files: FileStore) -> Path:
    if args.data_root:
        return Path(args.data_root)
    record = assessment.load_trial_record(Path(args.trial) / "trial.yaml", files=files)
    instance_id = str(record.get("instance_id") or "")
    if not instance_id:
        raise store.StoreError(
            "trial record carries no instance_id", failure="record_missing"
        )
    return store.instance_data_root(Path(args.instances_root), instance_id)


def _run_materialize(args, setup: EvalSetup, out: TextIO, files: FileStore) -> int:
    trial_dir = Path(args.trial)
    record = assessment.load_trial_record(trial_dir / "trial.yaml", files=files)
    dest = store.store_trial_dir(
        Path(setup.artifact_store),
        str(record.get("target_id") or ""),
        str(record.get("target_run_id") or record.get("instance_id") or ""),
        str(record.get("trial_id") or ""),
    )
    if args.dry_run:
        print(f"# materialize {trial_dir}", file=out)
        print(f"store {dest}", file=out)
        print(f"write {dest / verdicts.VERDICTS_FILENAME}", file=out)
        if files.exists(trial_dir / "diagnoses.yaml"):
            print(f"write {dest / diagnosis.DIAGNOSES_FILENAME}", file=out)
        print(f"write {dest / store.RUN_MANIFEST}", file=out)
        return 0
    result = store.materialize(
        trial_dir,
        store=Path(setup.artifact_store),
        data_root=_materialize_data_root(args, files),
        files=files,
    )
    print(f"store {result}", file=out)
    return 0


def _run_issue_search(args, out: TextIO, bank_factory: IssueBankFactory | None) -> int:
    bank = bank_factory() if bank_factory is not None else diagnosis.GitHubIssueBank.from_env()
    query = f"{args.query} repo:{args.repo}" if args.repo else args.query
    outcome = diagnosis.match_issue(
        bank,
        query=query,
        rationale="read-only search result",
        proposed=None,
        limit=args.limit,
    )
    closest = outcome.closest_issue
    print(
        json.dumps(
            {
                "closest_issue": (
                    {
                        "repo": closest.repo,
                        "number": closest.number,
                        "title": closest.title,
                    }
                    if closest
                    else None
                ),
                "proposed_issue": None,
            },
            indent=2,
        ),
        file=out,
    )
    return 0



# --- alignment (#274) ---------------------------------------------------------


def _unused_runner(command):  # pragma: no cover - dry-run never runs a command
    raise AssertionError("alignment dry-run must not execute a command")


def _alignment_instance_paths(args, setup: EvalSetup, config: OrchestratorConfig):
    selected = setup.instances
    if getattr(args, "instance", None):
        selected = tuple(i for i in setup.instances if i.instance_id == args.instance)
        if not selected:
            raise SetupError(f"no instance {args.instance!r} in the EvalSetup")
    return tuple(
        instances.instance_paths(
            instance,
            config.instances_root,
            repo=config.repo,
            branch=config.branch,
            compose_files=config.compose_files,
        )
        for instance in selected
    )


def _alignment_environment(args, setup: EvalSetup, config: OrchestratorConfig):
    return alignment.AlignmentEnvironment(
        instances=_alignment_instance_paths(args, setup, config),
        declarations=setup.alignment or alignment.AlignmentDeclarations(),
    )


def _load_decision_input(args, files: FileStore) -> dict:
    if args.decision_file:
        path = Path(args.decision_file)
        if not files.is_file(path):
            raise alignment.AlignmentError(f"decision input not found: {path}")
        try:
            payload = yaml.safe_load(files.read_text(path))
        except yaml.YAMLError as exc:
            raise alignment.AlignmentError(f"decision input {path}: invalid YAML: {exc}") from exc
        if not isinstance(payload, dict):
            raise alignment.AlignmentError(f"decision input {path}: expected a mapping")
        return payload
    heartbeat = Path(args.heartbeat)
    if not files.is_file(heartbeat):
        raise alignment.AlignmentError(
            f"no recorded decision input at {heartbeat}; run the advance daemon "
            "or pass --decision-file"
        )
    try:
        payload = yaml.safe_load(files.read_text(heartbeat))
    except yaml.YAMLError as exc:
        raise alignment.AlignmentError(f"heartbeat {heartbeat}: invalid YAML: {exc}") from exc
    if not isinstance(payload, dict) or not payload.get("decision"):
        raise alignment.AlignmentError(
            f"heartbeat {heartbeat} carries no decision input; pass --decision-file"
        )
    return payload["decision"]


def _print_alignment_outcome(outcome: alignment.AlignmentOutcome, out: TextIO) -> None:
    for result in outcome.results:
        detail = f" ({result.evidence})" if result.evidence else ""
        print(f"  {result.action.kind}: {result.status}{detail}", file=out)
    if outcome.escalated:
        hold = outcome.hold.hold_id if outcome.hold else "dry-run"
        print(f"alignment escalated (hold {hold}): {outcome.escalation}", file=out)


def _run_align(args, setup: EvalSetup, config: OrchestratorConfig, out: TextIO,
               runner_factory: RunnerFactory,
               decider: alignment.AlignmentDecider | None) -> int:
    files = FileStore()
    state = alignment.AlignmentState(Path(args.state), files=files)
    decision_input = _load_decision_input(args, files)
    environment = _alignment_environment(args, setup, config)

    if decider is None:
        if not args.command:
            raise alignment.AlignmentError(
                "no alignment command configured; pass --command or EVAL_ALIGN_COMMAND"
            )
        runner = runner_factory()
        decider = alignment.SubagentAlignmentDecider(
            runner, tuple(shlex.split(args.command)), files=files
        )
    else:
        # An injected decider (tests) never constructs a runner in dry-run.
        runner = _unused_runner if args.dry_run else runner_factory()

    outcome = alignment.run(
        decision_input,
        decider=decider,
        environment=environment,
        runner=runner,
        state=state,
        dry_run=args.dry_run,
    )
    if outcome.no_op and not outcome.results and not outcome.escalated:
        # M1: a true no-op (nothing moved) and a decider-chosen no-action for a
        # real delta are different facts and read differently.
        if outcome.consulted:
            print("alignment: decided no action; nothing to align", file=out)
        else:
            print("alignment: no change; nothing to align", file=out)
    else:
        _print_alignment_outcome(outcome, out)
    return 0 if outcome.ok else 1


def _run_alignment_resolve(args, out: TextIO) -> int:
    state = alignment.AlignmentState(Path(args.state))
    hold = state.resolve_hold(args.hold_id, args.decision)
    print(
        f"alignment hold {hold.hold_id}: resolved ({hold.decision})",
        file=out,
    )
    return 0


# --- the surfer loop (#275) ---------------------------------------------------


class _UnusedDecider:
    """A decider that must never be dispatched: dry-run asserts only."""

    def decide(self, request):  # pragma: no cover - never reached
        raise AssertionError("surfer dry-run must not dispatch the decider")


def _surfer_argv(args) -> tuple[str, ...]:
    if not args.command:
        raise surfer.SurferError(
            "no surfer command configured; pass --command or EVAL_SURFER_COMMAND"
        )
    return tuple(shlex.split(args.command))


def _surfer_config(args) -> surfer.SurferConfig:
    return surfer.SurferConfig(interval_s=args.interval_s)


def _surfer_app_state(args):
    """The injected idle proxy, failing closed: an unknown state is never idle."""
    from advance.app_state import AppState, AppStateUnavailable, IdleProxy

    proxy = IdleProxy(args.api, dsn=args.dsn)

    def read():
        try:
            return proxy.fetch()
        except AppStateUnavailable:
            return AppState(idle=False, projects=())

    return read


def _surfer_log(err: TextIO) -> Callable[[dict], None]:
    """Surface the surfer's structured records as operator-readable lines."""

    def log(record: dict) -> None:
        event = str(record.get("event", "event"))
        path = record.get("path")
        detail = record.get("error") or record.get("reason")
        line = f"surfer: {event}"
        if path:
            line += f" {path}"
        if detail:
            line += f": {detail}"
        print(line, file=err)

    return log


def _surfer_asserter(
    args, files: FileStore, *, log: Callable[[dict], None] | None = None,
    api_runner=None,
) -> surfer.SurferStateSource:
    trial_log = surfer.FileTrialLog(args.runs_root, files=files, log=log)
    # I9: the production evidence reader reads each failed run's error payload
    # through the REST seam, so credit-exhaustion-like errors are classified
    # even when the trial record's own text is terse.
    reader = api_runner if api_runner is not None else api.HttpApiRunner(args.api)
    return surfer.SurferStateSource(
        app_state=_surfer_app_state(args),
        trial_log=trial_log,
        signals=surfer.CreditExhaustionReader(),
        evidence=surfer.RunErrorEvidence(reader, trial_log, log=log or (lambda record: None)),
        log=log or (lambda record: None),
    )


def _surfer_preloaded_for(setup: EvalSetup):
    """target_id -> the target's pre-mined artifacts, for `replace_artifacts`."""
    mapping = {
        run.target_id: run.preloaded_hunting_artifacts
        for instance in setup.instances
        for run in instance.targets
        if run.preloaded_hunting_artifacts is not None
    }
    return lambda target_id: mapping.get(target_id) if target_id else None


def _surfer_repair_factory(args, setup: EvalSetup, config: OrchestratorConfig,
                           data_root: Path, runner):
    """Build the bounded repair kit for the trigger's instance."""
    paths = {
        p.instance.instance_id: p
        for p in _alignment_instance_paths(args, setup, config)
    }
    preloaded = _surfer_preloaded_for(setup)

    def build(trigger: surfer.Trigger):
        instance_paths = paths.get(trigger.instance_id)
        if instance_paths is None:
            return None
        return surfer.SurferRepairKit(
            instance_paths,
            runner=runner,
            data_root=data_root,
            preloaded=preloaded(trigger.target_id),
        )

    return build


def _resume_trial(args, setup: EvalSetup, config: OrchestratorConfig,
                  plan: surfer.ResumePlan, data_root: Path, runner_factory: RunnerFactory,
                  api_factory: ApiFactory | None) -> str:
    """Relaunch a failed trial at its recorded phase through the trial engine."""
    instance = _find_instance(setup, plan.instance_id)
    paths = instances.instance_paths(
        instance,
        config.instances_root,
        repo=config.repo,
        branch=config.branch,
        compose_files=config.compose_files,
    )
    resume_args = argparse.Namespace(
        instance_id=plan.instance_id,
        target_id=plan.target_id,
        target_run_id=None,
        data_root=str(data_root),
        runs_root=args.runs_root,
        budget_s=args.budget_s,
        poll_s=args.poll_s,
        project_id=plan.project_id,
        recon_run=plan.recon_run_id,
        existing_project_id=None,
        eval_sha=args.eval_sha,
        stack_fingerprint=args.stack_fingerprint,
        trace_id=args.trace_id,
        repo=args.repo,
        dry_run=False,
    )
    cfg, _paths, _run = _trial_config(resume_args, setup, config)
    cfg = replace(
        cfg,
        start_phase=plan.start_phase,
        intervention=plan.intervention,
        # A resumed trial keeps its recorded trial-scoped baseline; only a new
        # trial snapshots a fresh one (D8/D16).
        cap_baseline=plan.cap_baseline,
    )
    runner = runner_factory()
    api_runner = (api_factory or (lambda base: api.HttpApiRunner(base)))(args.api)
    probe = trial.make_reachability_probe(paths, runner, trial.front_url(cfg))
    engine = trial.Trial(cfg, api_runner=api_runner, runner=runner, reachable=probe)
    orchestrator = Orchestrator(setup, config, runner=runner)
    record = engine.run(
        bring_up=orchestrator.up, repair=trial.InstanceRepair(paths, runner)
    )
    return record.trial_id


def _surfer_resumer(args, setup: EvalSetup, config: OrchestratorConfig,
                    data_root: Path, runner_factory: RunnerFactory,
                    api_factory: ApiFactory | None):
    def run(plan: surfer.ResumePlan) -> str:
        return _resume_trial(
            args, setup, config, plan, data_root, runner_factory, api_factory
        )

    return surfer.CallbackResumer(run)


def _print_surfer(outcomes: list[surfer.SurferOutcome], out: TextIO) -> None:
    for outcome in outcomes:
        if outcome.no_op:
            if outcome.skipped:
                print(
                    f"surfer cycle {outcome.cycle}: "
                    f"{len(outcome.skipped)} trigger(s) already handled; skipped",
                    file=out,
                )
            else:
                print(f"surfer cycle {outcome.cycle}: idle; no trigger", file=out)
            continue
        for trigger in outcome.state.triggers:
            print(
                f"surfer cycle {outcome.cycle}: {trigger.kind} {trigger.instance_id}: "
                f"{trigger.detail}",
                file=out,
            )
        if outcome.planned:
            print(f"  {outcome.detail}", file=out)
        elif outcome.action:
            print(f"  {outcome.action}: {outcome.detail}", file=out)


def _run_surfer(args, setup: EvalSetup, config: OrchestratorConfig, out: TextIO,
                err: TextIO, runner_factory: RunnerFactory,
                api_factory: ApiFactory | None,
                decider: surfer.SurferDecider | None,
                asserter: surfer.StateAsserter | None,
                resumer: surfer.TrialResumer | None,
                repairs_factory) -> int:
    files = FileStore()
    state = alignment.AlignmentState(Path(args.state), files=files)
    instance_paths = _alignment_instance_paths(args, setup, config)
    log = _surfer_log(err)

    # Dry-run asserts and prints only: it never dispatches the decider, never
    # constructs an execution runner, and never mutates (the surfer's own
    # side-effect-free contract, unlike #274's align).
    if args.dry_run:
        engine = surfer.Surfer(
            _surfer_config(args),
            asserter=asserter or _surfer_asserter(args, files, log=log),
            decider=_UnusedDecider(),
            instances=instance_paths,
            state=state,
            dry_run=True,
        )
        _print_surfer(engine.run(once=True), out)
        return 0

    data_root = _resolve_data_root(args)
    runner = runner_factory()
    if decider is None:
        decider = surfer.SubagentSurferDecider(runner, _surfer_argv(args), files=files)
    if asserter is None:
        asserter = _surfer_asserter(args, files, log=log)
    if repairs_factory is None:
        repairs_factory = _surfer_repair_factory(args, setup, config, data_root, runner)
    if resumer is None:
        resumer = _surfer_resumer(
            args, setup, config, data_root, runner_factory, api_factory
        )
    engine = surfer.Surfer(
        _surfer_config(args),
        asserter=asserter,
        decider=decider,
        instances=instance_paths,
        runner=runner,
        api=(api_factory or (lambda base: api.HttpApiRunner(base)))(args.api),
        repairs=repairs_factory,
        resumer=resumer,
        state=state,
        log=log,
    )
    outcomes = engine.run(once=args.once)
    _print_surfer(outcomes, out)
    return 1 if any(outcome.escalated for outcome in outcomes) else 0


def main(
    argv: list[str] | None = None,
    *,
    runner_factory: RunnerFactory = LocalRunner,
    api_factory: ApiFactory | None = None,
    dispatch_factory: DispatchFactory | None = None,
    diagnose_dispatch_factory: DiagnoseDispatchFactory | None = None,
    issue_bank_factory: IssueBankFactory | None = None,
    alignment_decider: alignment.AlignmentDecider | None = None,
    surfer_decider: surfer.SurferDecider | None = None,
    surfer_asserter: surfer.StateAsserter | None = None,
    surfer_resumer: surfer.TrialResumer | None = None,
    surfer_repairs: Callable[[surfer.Trigger], surfer.SurferRepairs] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    args = _parser().parse_args(argv)

    try:
        if args.verb == "issue-search":
            return _run_issue_search(args, out, issue_bank_factory)

        setup = load_eval_setup(Path(args.setup))
        config = OrchestratorConfig(
            repo=Path(args.repo),
            instances_root=Path(args.instances_root),
            branch=args.branch,
        )
        if args.verb == "alignment":
            return _run_alignment_resolve(args, out)
        if args.verb == "align":
            return _run_align(
                args, setup, config, out, runner_factory, alignment_decider
            )
        if args.verb == "surfer":
            return _run_surfer(
                args, setup, config, out, err, runner_factory, api_factory,
                surfer_decider, surfer_asserter, surfer_resumer, surfer_repairs,
            )
        if args.verb == "trial":
            # D42: an unresolved alignment hold refuses to start a new trial.
            alignment.AlignmentState(Path(args.state)).require_no_holds()
            factory = api_factory or (lambda base: api.HttpApiRunner(base))
            return _run_trial(args, setup, config, out, err, runner_factory, factory)
        if args.verb == "store":
            files = FileStore()
            if args.store_verb == "render-sync":
                return _run_render_sync(args, setup, out, files)
            return _run_materialize(args, setup, out, files)
        if args.verb == "assess":
            return _run_assess(args, setup, out, err, runner_factory, dispatch_factory)
        if args.verb == "diagnose":
            return _run_diagnose(
                args, setup, out, err, runner_factory, diagnose_dispatch_factory
            )
        if args.verb == "close-verify":
            return _run_close_verify(
                args, setup, out, err, runner_factory, dispatch_factory,
                diagnose_dispatch_factory,
            )
        if args.verb == "monitor":
            return _run_monitor(
                args, setup, out, err, runner_factory, dispatch_factory,
                diagnose_dispatch_factory,
            )
        if args.verb == "next-target":
            return _run_next_target(args, setup, config, out, err, runner_factory)

        dry_run = args.verb == "plan" or getattr(args, "dry_run", False)
        if dry_run:
            _print_plan(Orchestrator(setup, config).plan(), out)
            return 0

        if args.verb == "up":
            alignment.AlignmentState(Path(args.state)).require_no_holds()
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
