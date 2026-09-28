"""Per-instance stack lifecycle (D1/D10/D11/D29, D41).

One `PolyphemusInstance` is one compose project (`ph-<short>`) running from its
own git worktree off the `eval` branch, with its own `.env` validated by
`eval/env_preflight.py` before the stack is rendered (`docker compose config`)
or started. Teardown removes exactly that project's containers and volumes and
its own worktree, never another instance's.

The commands are planned purely; execution is one injected runner.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orchestrator.commands import Command, CommandRunner, require_ok
from orchestrator.ids import short_id
from orchestrator.setup import Instance

COMPOSE_FILES: tuple[str, ...] = (
    "docker-compose.yml",
    "docker-compose.dev.yml",
    "eval/docker-compose.eval.yml",
)
OVERLAY_FILE = "eval/docker-compose.eval.yml"
PREFLIGHT_SCRIPT = "eval/env_preflight.py"


class InstanceError(RuntimeError):
    """A per-instance lifecycle command failed."""


@dataclass(frozen=True)
class InstancePaths:
    """Resolved filesystem and compose identity of one instance."""

    instance: Instance
    worktree: Path
    env_file: Path
    compose_project: str
    compose_files: tuple[str, ...]
    repo: Path
    branch: str


def compose_project(instance: Instance) -> str:
    """`ph-<short>`: a deterministic, unique compose project per instance."""
    return f"ph-{short_id(instance.instance_id)}"


def instance_paths(
    instance: Instance,
    instances_root: Path,
    *,
    repo: Path,
    branch: str,
    compose_files: tuple[str, ...] = COMPOSE_FILES,
    env_file: str | None = None,
) -> InstancePaths:
    """Resolve the instance worktree and `.env` under a configurable root.

    A relative `env_file` in the setup is resolved against the instances root;
    the default is `<worktree>/.env`, which is where the eval overlay's
    `env_file: .env, required: true` reads it from.
    """
    root = Path(instances_root)
    worktree = root / instance.instance_id
    override = env_file or instance.env_file
    if override:
        resolved = Path(override)
        env = resolved if resolved.is_absolute() else root / resolved
    else:
        env = worktree / ".env"
    return InstancePaths(
        instance=instance,
        worktree=worktree,
        env_file=env,
        compose_project=compose_project(instance),
        compose_files=compose_files,
        repo=Path(repo),
        branch=branch,
    )


def compose_argv(paths: InstancePaths, *verbs: str) -> list[str]:
    """`docker compose -p <project> -f base -f dev -f eval <verbs>`."""
    argv = ["docker", "compose", "-p", paths.compose_project]
    for compose_file in paths.compose_files:
        argv += ["-f", compose_file]
    argv += list(verbs)
    return argv


def plan_worktree_add(paths: InstancePaths) -> Command:
    return Command(
        argv=(
            "git",
            "-C",
            str(paths.repo),
            "worktree",
            "add",
            str(paths.worktree),
            paths.branch,
        ),
        description=f"worktree {paths.instance.instance_id} off {paths.branch}",
    )


def plan_worktree_remove(paths: InstancePaths) -> Command:
    return Command(
        argv=(
            "git",
            "-C",
            str(paths.repo),
            "worktree",
            "remove",
            "--force",
            str(paths.worktree),
        ),
        description=f"remove worktree {paths.instance.instance_id}",
    )


def plan_preflight(paths: InstancePaths) -> Command:
    return Command(
        argv=("python3", PREFLIGHT_SCRIPT, str(paths.env_file)),
        cwd=str(paths.worktree),
        description=f"env preflight {paths.env_file.name}",
    )


def plan_render(paths: InstancePaths) -> Command:
    return Command(
        argv=tuple(compose_argv(paths, "config")),
        cwd=str(paths.worktree),
        description=f"render {paths.compose_project}",
    )


def plan_up(paths: InstancePaths) -> list[Command]:
    """Worktree, then preflight, render, and start the instance stack."""
    return [
        plan_worktree_add(paths),
        plan_preflight(paths),
        plan_render(paths),
        Command(
            argv=tuple(compose_argv(paths, "up", "-d")),
            cwd=str(paths.worktree),
            description=f"up {paths.compose_project}",
        ),
    ]


def plan_down(paths: InstancePaths) -> list[Command]:
    """Stop the instance's own project (volumes included), then drop its worktree."""
    return [
        Command(
            argv=tuple(compose_argv(paths, "down", "-v", "--remove-orphans")),
            cwd=str(paths.worktree),
            description=f"down {paths.compose_project}",
        ),
        plan_worktree_remove(paths),
    ]


def plan_status(paths: InstancePaths) -> Command:
    return Command(
        argv=tuple(compose_argv(paths, "ps")),
        cwd=str(paths.worktree),
        description=f"status {paths.compose_project}",
    )


def ensure_worktree(paths: InstancePaths, run: CommandRunner) -> None:
    """Create the instance worktree unless it is already present (idempotent)."""
    if paths.worktree.exists():
        return
    paths.worktree.parent.mkdir(parents=True, exist_ok=True)
    command = plan_worktree_add(paths)
    require_ok(run(command), command, error=InstanceError)


def remove_worktree(paths: InstancePaths, run: CommandRunner) -> None:
    """Remove the instance worktree; absent is success (idempotent teardown)."""
    if not paths.worktree.exists():
        return
    command = plan_worktree_remove(paths)
    require_ok(run(command), command, error=InstanceError)


def up(paths: InstancePaths, run: CommandRunner) -> None:
    """Bring up one instance stack: worktree, preflight, render, compose up."""
    ensure_worktree(paths, run)
    for command in (plan_preflight(paths), plan_render(paths), plan_up(paths)[-1]):
        require_ok(run(command), command, error=InstanceError)


def down(paths: InstancePaths, run: CommandRunner) -> None:
    """Tear down one instance stack and remove its worktree."""
    command = plan_down(paths)[0]
    require_ok(run(command), command, error=InstanceError)
    remove_worktree(paths, run)


def status(paths: InstancePaths, run: CommandRunner) -> str:
    """The instance project's `docker compose ps` output."""
    command = plan_status(paths)
    return require_ok(run(command), command, error=InstanceError).stdout
