"""The runner's CLI: `plan | run | resume | status` over one run config.

This is the only module that wires the production seams: the environment driver
the config's `environment.driver` names, the real validator gate, and the
`opencode api` harness. Everything else - the config loader, the wrapper
builders, the loop, the state - is called as-is, so the CLI tests replace exactly
those three builders and let the rest run for real.

Command contract (the architecture doc, section 2):

* `plan` is a read-only preflight: it prints the targets, their deterministic
  sessions, the driver's lifecycle hints, the validator commands, and the
  carriers; it verifies the carriers exist and creates nothing.
* `run` starts a fresh run in `<worktree>/.bootstrap-runs/<run.id>` (or
  `--rundir`), writes `config.resolved.yaml` plus the state, and drives the loop.
* `resume` reads the rundir's own snapshot and state, re-verifies each
  incomplete target's worker session, and continues at the first incomplete
  phase. It never needs the original `run.yaml`.
* `status` prints the per-target table from the state alone.

Exit codes: 0 success, 1 at least one target failed, 2 the run could not start
(bad inputs, drift, or a missing state).

Secrets rule: nothing here prints or stores a credential value. The state holds
paths and session ids; the per-turn logs hold prompts and transcript tails.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

import yaml

from runner import state as state_mod
from runner.config import RunConfig, load_config, load_resolved
from runner.env import AttachEnv, LocalEnv, SshServerEnv
from runner.gates import AUTH_ONLY, FULL, ValidatorGate, validator_argv
from runner.harness import OpenCodeApiHarness
from runner.orchestrator import Dispatch, Orchestrator, RunSummary, build_instructions
from runner.wrappers import WrapperFacts, WrapperSources

# The repository that ships this module: relative paths in a run config resolve
# against it (config.py's contract), and the default worktree is its root.
REPO_ROOT = Path(__file__).resolve().parents[3]

RESOLVED_NAME = "config.resolved.yaml"
# The validator's documented invocation prefix: it imports `polymerhus`, which
# resolves only with `src/` on the path (gates.validator_env does the same for
# the gate process).
VALIDATOR_PYTHON = "PYTHONPATH=src python3"

STATUS_COLUMNS = ("target", "status", "authn", "l1", "gates", "teardown", "session")


class CliError(RuntimeError):
    """A run cannot start (bad inputs, a missing state); the operator fixes it."""


# --- the three production seams (replaced by the CLI tests) ------------------


def build_env(config: RunConfig):
    """The environment driver the config names; constructing one runs nothing."""
    environment = config.environment
    if environment.driver == "ssh":
        return SshServerEnv(ssh=environment.ssh, targetctl=environment.targetctl)
    if environment.driver == "local":
        if environment.local_dir is None:
            raise CliError("the local driver needs environment.local_dir")
        return LocalEnv(
            local_dir=environment.local_dir,
            bash=environment.bash or None,
            platform=environment.docker_platform,
        )
    if environment.driver == "attach":
        if not environment.base_url:
            raise CliError("the attach driver needs environment.base_url")
        return AttachEnv(base_url=environment.base_url)
    raise CliError(f"unknown environment driver {environment.driver!r}")


def build_gate(config: RunConfig) -> ValidatorGate:
    return ValidatorGate(
        validator=config.paths.validator,
        staging=config.paths.staging,
        kbs=config.paths.kbs,
        worktree=config.run.worktree,
    )


def build_harness(config: RunConfig) -> OpenCodeApiHarness:
    return OpenCodeApiHarness(directory=str(config.run.worktree))


@dataclass
class Runtime:
    """The three wired seams one run drives."""

    env: object
    gate: object
    harness: object


def _runtime(config: RunConfig) -> Runtime:
    return Runtime(env=build_env(config), gate=build_gate(config), harness=build_harness(config))


# --- paths, carriers, facts -------------------------------------------------


def _relative(path: Path, worktree: Path) -> str:
    """The path as the worker sees it: repo-relative inside the worktree, else absolute.

    The worker session's directory is the worktree, so a repo-relative path is
    what its own commands and the contract's invocation name.
    """
    resolved = Path(path).expanduser().resolve()
    try:
        return str(resolved.relative_to(Path(worktree).expanduser().resolve()))
    except ValueError:
        return str(resolved)


def _target_dir(config: RunConfig, target: str) -> str:
    """The target's own directory, as the prompts and the sealed-path rule name it."""
    return f"{config.environment.web_root.rstrip('/')}/{target}"


def _read_carrier(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CliError(f"a procedure carrier could not be read: {path}: {exc}") from exc


def _carriers(config: RunConfig) -> tuple[Path, ...]:
    """Every versioned carrier a run needs; the meta-skill belongs to the authn phase."""
    return (
        config.paths.authn_prompt,
        config.paths.l1_prompt,
        config.paths.contract,
        config.paths.meta_skill,
        config.paths.validator,
    )


def _missing_carriers(config: RunConfig) -> list[str]:
    return [str(path) for path in _carriers(config) if not Path(path).is_file()]


def _require_carriers(config: RunConfig) -> None:
    missing = _missing_carriers(config)
    if missing:
        raise CliError("missing carrier(s): " + ", ".join(missing))


def _sources_for(config: RunConfig) -> Callable[[str], WrapperSources]:
    """The carriers per gate mode: the authn prompt (with its meta-skill) or the L1 prompt.

    The meta-skill is the authentication phase's procedure authority; the L1
    prompt does not cite it, so the L1 wrapper does not embed it.
    """
    worktree = config.run.worktree

    def sources_for(mode: str) -> WrapperSources:
        authn = mode == AUTH_ONLY
        prompt = config.paths.authn_prompt if authn else config.paths.l1_prompt
        meta = config.paths.meta_skill if authn else None
        return WrapperSources(
            prompt_path=_relative(prompt, worktree),
            prompt_text=_read_carrier(prompt),
            contract_path=_relative(config.paths.contract, worktree),
            contract_text=_read_carrier(config.paths.contract),
            meta_skill_path=_relative(meta, worktree) if meta else "",
            meta_skill_text=_read_carrier(meta) if meta else "",
            validator_path=_relative(config.paths.validator, worktree),
        )

    return sources_for


def _validator_invocation_for(config: RunConfig) -> Callable[[str, str], str]:
    """The exact command each phase's wrapper tells the worker to run until OK."""
    worktree = config.run.worktree

    def invocation(target: str, mode: str) -> str:
        argv = validator_argv(
            python=VALIDATOR_PYTHON,
            validator=_relative(config.paths.validator, worktree),
            target=target,
            mode=mode,
            staging=_relative(config.paths.staging, worktree),
            target_dir=_relative(config.paths.kbs / target, worktree),
        )
        return " ".join(argv)

    return invocation


def _facts_for(
    config: RunConfig, state: state_mod.RunState, env
) -> Callable[[str], WrapperFacts]:
    """The per-target facts a wrapper substitutes, read at dispatch time.

    `base_url` is the URL the run just observed for that target (`targetctl ps`
    with the placeholder host rewritten); the config's `environment.base_url` is
    the attach fallback.
    """
    worktree = config.run.worktree

    def facts_for(target: str) -> WrapperFacts:
        record = state.target(target)
        return WrapperFacts(
            target=target,
            base_url=record.base_url or config.environment.base_url,
            web_root=config.environment.web_root,
            worktree=str(worktree),
            staging=_relative(config.paths.staging, worktree),
            target_dir=_target_dir(config, target),
            lifecycle_hint=env.lifecycle_hints(target),
            kbs_dir=_relative(config.paths.kbs / target, worktree),
        )

    return facts_for


def _instructions_for(config: RunConfig, state: state_mod.RunState, env):
    """Each target's wrappers, built when that target is first dispatched.

    The base URL is a fact only the environment knows, so a wrapper cannot be
    built before its target is observed: this is the lazy builder the
    orchestrator calls at first dispatch, memoised per target.
    """
    facts_for = _facts_for(config, state, env)
    sources_for = _sources_for(config)
    invocation = _validator_invocation_for(config)
    cache: dict[str, Mapping[str, Dispatch]] = {}

    def instructions_for(target: str) -> Mapping[str, Dispatch]:
        if target not in cache:
            cache[target] = build_instructions(
                config,
                facts_for=facts_for,
                sources_for=sources_for,
                validator_invocation=invocation,
                target=target,
            )
        return cache[target]

    return instructions_for


# --- config, rundir, selection ----------------------------------------------


def _load_config(args) -> RunConfig:
    if not args.config:
        raise CliError("plan and run need --config <run.yaml>")
    path = Path(args.config).expanduser()
    if not path.is_file():
        raise CliError(f"no run config at {path}")
    try:
        return load_config(path, repo_root=REPO_ROOT)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise CliError(f"{path}: {exc}") from exc


def _selected(config: RunConfig, args) -> list[str]:
    raw = getattr(args, "targets", None)
    if not raw:
        return list(config.run.targets)
    chosen = [part.strip() for part in str(raw).split(",") if part.strip()]
    unknown = [target for target in chosen if target not in set(config.run.targets)]
    if unknown:
        raise CliError(f"targets not in the config: {', '.join(unknown)}")
    return [target for target in config.run.targets if target in set(chosen)]


def _batch(config: RunConfig, args) -> RunConfig:
    """The config restricted to the selected targets (plan order kept)."""
    selected = _selected(config, args)
    return config if len(selected) == len(config.run.targets) else config.with_targets(selected)


def _rundir_for(args, config: RunConfig) -> Path:
    if getattr(args, "rundir", None):
        return Path(args.rundir).expanduser().resolve()
    return config.rundir()


def _rundir_only(args) -> Path:
    if getattr(args, "rundir", None):
        return Path(args.rundir).expanduser().resolve()
    if getattr(args, "config", None):
        return _load_config(args).rundir()
    raise CliError("this command needs --rundir <dir> or --config <run.yaml>")


def _write_snapshot(config: RunConfig, rundir: Path) -> Path:
    """Write the resolved config the run and its later resumes are pinned to."""
    path = rundir / RESOLVED_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(config.resolved(), sort_keys=False), encoding="utf-8")
    return path


def _load_state(rundir: Path) -> state_mod.RunState:
    path = rundir / state_mod.STATE_FILE
    if not path.is_file():
        raise CliError(f"no run state at {path}; start one with `run`")
    try:
        return state_mod.RunState.load(rundir)
    except (OSError, ValueError) as exc:
        raise CliError(f"{path} could not be read: {exc}") from exc


def _open_run(args) -> tuple[Path, RunConfig, state_mod.RunState]:
    """A resume's inputs: the rundir's state, and the config it was run with."""
    rundir = _rundir_only(args)
    state = _load_state(rundir)
    snapshot = rundir / RESOLVED_NAME
    if snapshot.is_file():
        config = load_resolved(snapshot)
    elif getattr(args, "config", None):
        config = _load_config(args)
    else:
        raise CliError(
            f"resume needs the run's config: {snapshot} is missing; pass --config <run.yaml>"
        )
    if config.digest != state.config_digest:
        print(
            f"warning: config drift: this config digests as {config.digest}, the run "
            f"recorded {state.config_digest or '(none)'}; the state is the run's truth "
            "and the run continues from it",
            file=sys.stderr,
        )
    return rundir, config, state


# --- the loop and the report ------------------------------------------------


def _drive(
    config: RunConfig,
    state: state_mod.RunState,
    rundir: Path,
    targets: Sequence[str],
    runtime: Runtime,
    *,
    no_lifecycle: bool,
) -> RunSummary:
    orchestrator = Orchestrator(
        config=config,
        harness=runtime.harness,
        env=runtime.env,
        gate=runtime.gate,
        state=state,
        rundir=rundir,
        instructions=_instructions_for(config, state, runtime.env),
        sleep=time.sleep,
        skip_lifecycle=no_lifecycle,
    )
    return orchestrator.run_plan(targets=list(targets))


def _print_status_table(state: state_mod.RunState) -> None:
    rows = state.status_table()
    widths = {
        column: max(len(column), *(len(row[column]) for row in rows))
        for column in STATUS_COLUMNS
    }
    print("  ".join(column.ljust(widths[column]) for column in STATUS_COLUMNS))
    print("  ".join("-" * widths[column] for column in STATUS_COLUMNS))
    for row in rows:
        print("  ".join(row[column].ljust(widths[column]) for column in STATUS_COLUMNS))


def _report(state: state_mod.RunState, summary: RunSummary, rundir: Path) -> int:
    print()
    _print_status_table(state)
    for note in summary.notes:
        print(f"note: {note}")
    print(
        f"summary: {len(summary.completed)} done, {len(summary.failed)} failed, "
        f"{len(summary.skipped)} skipped"
    )
    print(f"state: {summary.state_path or rundir / state_mod.STATE_FILE}")
    return summary.exit_code


def _probe_sessions(
    state: state_mod.RunState, harness, targets: Sequence[str]
) -> None:
    """Re-verify the live worker sessions a resume is about to continue.

    Read-only (`session_model`): a session that is gone is reported, and the
    harness recreates it by its deterministic id at the target's next dispatch.
    """
    for target in targets:
        if state.first_incomplete_phase(target) is None:
            continue
        session = state.target(target).creator_session(state.run_id)
        model = harness.session_model(session)
        if model is None:
            print(f"resume: session {session} is not live; it will be recreated on dispatch")
        else:
            print(
                f"resume: session {session} is live "
                f"({model.get('providerID')}/{model.get('id')})"
            )


# --- commands ---------------------------------------------------------------


def _command_plan(args) -> int:
    config = _batch(_load_config(args), args)
    _require_carriers(config)
    _print_plan(config, _rundir_for(args, config), build_env(config))
    return 0


def _print_plan(config: RunConfig, rundir: Path, env) -> None:
    run = config.run
    print(f"plan: run {run.id} - {len(run.targets)} target(s), serial, one at a time")
    print(f"worktree: {run.worktree}")
    print(f"rundir:   {rundir}")
    print(f"agent:    {run.agent}")
    print(f"model:    {run.model}")
    print(
        "base url: "
        + (
            config.environment.base_url
            or (
                f"(discovered from targetctl; placeholder host rewritten to "
                f"{config.environment.public_host})"
                if config.environment.public_host
                else "(discovered from targetctl after deployment)"
            )
        )
    )
    print()
    for target in run.targets:
        print(f"target {target}")
        print(f"  session:    {state_mod.session_id(run.id, target)}")
        print(f"  target dir: {_target_dir(config, target)}")
        print(f"  staging:    {_relative(config.paths.staging / target, run.worktree)}")
        print(f"  kb out:     {_relative(config.paths.kbs / target, run.worktree)}")
        print("  lifecycle:")
        for hint in env.lifecycle_hints(target):
            print(f"    {hint}")
        for mode in (AUTH_ONLY, FULL):
            print(f"  gate {mode}: {_validator_invocation_for(config)(target, mode)}")
        print()
    print("plan only: nothing was created or changed.")


def _command_run(args) -> int:
    full = _load_config(args)
    config = _batch(full, args)
    _require_carriers(config)
    rundir = _rundir_for(args, full)
    state_path = rundir / state_mod.STATE_FILE
    if state_path.exists():
        raise CliError(
            f"{state_path} already holds a run; continue it with `resume` "
            "or start a fresh run with --rundir"
        )
    # The state registers the full plan, so a partial `--targets` selection can
    # be completed later; the snapshot is the config the run is pinned to.
    state = state_mod.new_state(
        full.run.id, config_digest=full.digest, targets=full.run.targets
    )
    _write_snapshot(full, rundir)
    state.save(rundir)
    runtime = _runtime(config)
    print(f"run {full.run.id}: {len(config.run.targets)} target(s) into {rundir}")
    summary = _drive(
        config, state, rundir, config.run.targets, runtime, no_lifecycle=args.no_lifecycle
    )
    return _report(state, summary, rundir)


def _command_resume(args) -> int:
    rundir, config, state = _open_run(args)
    batch = _batch(config, args)
    _require_carriers(batch)
    runtime = _runtime(batch)
    print(f"resume run {state.run_id} in {rundir}")
    _probe_sessions(state, runtime.harness, batch.run.targets)
    summary = _drive(
        batch, state, rundir, batch.run.targets, runtime, no_lifecycle=args.no_lifecycle
    )
    return _report(state, summary, rundir)


def _command_status(args) -> int:
    state = _load_state(_rundir_only(args))
    _print_status_table(state)
    failed = [row["target"] for row in state.status_table() if row["status"] == state_mod.FAILED]
    if failed:
        print(
            f"run {state.run_id}: {len(failed)} target(s) failed: {', '.join(failed)}",
            file=sys.stderr,
        )
        return 1
    return 0


# --- argv -------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_external_bootstrap.py",
        description=(
            "Mechanised external bootstrap: regenerate the WebExploitBench data "
            "dependencies (auth bundle, authn skill, L1 surface) from one run config."
        ),
        epilog=(
            "exit codes: 0 ok, 1 a target failed, 2 the run could not start. "
            "The default rundir is <worktree>/.bootstrap-runs/<run.id>."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)

    def add_shared(sub: argparse.ArgumentParser, *, config_required: bool) -> None:
        sub.add_argument(
            "--config",
            required=config_required,
            help="the run yaml (resume/status may instead read a rundir's snapshot)",
        )
        sub.add_argument("--rundir", help="the run's directory (default above)")
        sub.add_argument(
            "--targets", help="a comma-separated subset of the config's targets"
        )

    plan = commands.add_parser("plan", help="print the plan; change nothing")
    add_shared(plan, config_required=True)
    plan.set_defaults(run=_command_plan)

    run = commands.add_parser("run", help="start a fresh run")
    add_shared(run, config_required=True)
    run.add_argument(
        "--no-lifecycle",
        action="store_true",
        help="never up/down a target: work the target as it is (attach-style)",
    )
    run.set_defaults(run=_command_run)

    resume = commands.add_parser("resume", help="continue a run from its state")
    add_shared(resume, config_required=False)
    resume.add_argument(
        "--no-lifecycle",
        action="store_true",
        help="never up/down a target: work the target as it is (attach-style)",
    )
    resume.set_defaults(run=_command_resume)

    status = commands.add_parser("status", help="print the per-target table")
    add_shared(status, config_required=False)
    status.set_defaults(run=_command_status)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.run(args)
    except CliError as failure:
        print(f"error: {failure}", file=sys.stderr)
        return 2
