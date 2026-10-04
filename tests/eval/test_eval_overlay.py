"""Integration tests for the eval compose overlay (`eval/docker-compose.eval.yml`).

Render `docker compose -f docker-compose.yml -f docker-compose.dev.yml
-f eval/docker-compose.eval.yml config` against a synthetic env in a tmp copy
(assert on the render output, never on file text), plus the non-eval control:
the base render keeps its service set. Skip cleanly when docker is absent.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

COMPLETE_ENV = {
    "NEO4J_URI": "bolt://neo4j:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "polymerhus",
    "POSTGRES_DSN": "postgresql://polymerhus:polymerhus@postgres:5432/polymerhus",
    "KALI_MCP_URL": "http://kali:8000/mcp",
    "LLM_CONFIGURATOR": "opencode:manual/test",
    "LLM_TRIAGER": "opencode:manual/test",
    "LLM_JOB_ORCHESTRATOR": "opencode:manual/test",
    "LLM_CRAWLER": "opencode:manual/test",
    "LLM_ANALYSER": "opencode:manual/test",
    "LLM_HUNTING_ORCHESTRATOR": "opencode:manual/test",
    "LLM_HUNTING_HUNTER": "opencode:manual/test",
    "LLM_POD_RUNNER": "opencode:manual/test",
    "LLM_POD_TRIAGER": "opencode:manual/test",
    "LLM_CAPABILITY_OVERRIDES": (
        '{"opencode-go/deepseek-v4.1-flash": {"supports_structured_output": false, '
        '"supports_forced_tool_choice": false}}'
    ),
}

BASE_SERVICES = {"agent", "kali", "postgres", "neo4j", "lightrag"}

docker = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker CLI unavailable"
)


def stage(tmp_path: Path, env: dict[str, str] | None, with_overlay: bool = True) -> Path:
    """A tmp compose project mirroring the instance layout (root files plus
    the eval overlay under `eval/`); the repo-root `.env` is never read."""
    shutil.copy(REPO_ROOT / "docker-compose.yml", tmp_path / "docker-compose.yml")
    shutil.copy(REPO_ROOT / "docker-compose.dev.yml", tmp_path / "docker-compose.dev.yml")
    if with_overlay:
        (tmp_path / "eval").mkdir()
        shutil.copy(
            REPO_ROOT / "eval" / "docker-compose.eval.yml",
            tmp_path / "eval" / "docker-compose.eval.yml",
        )
    if env is not None:
        (tmp_path / ".env").write_text(
            "".join(f"{k}={v}\n" for k, v in env.items()), encoding="utf-8"
        )
    return tmp_path


def child_env(drop: tuple[str, ...] = (), extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if k not in COMPLETE_ENV and k not in drop
    }
    env.pop("COMPOSE_ENV_FILES", None)
    env.update(extra or {})
    return env


def render(
    project: Path,
    files: list[str],
    drop: tuple[str, ...] = (),
    extra: dict[str, str] | None = None,
):
    cmd = ["docker", "compose"]
    for f in files:
        cmd += ["-f", f]
    cmd += ["config"]
    return subprocess.run(
        cmd, capture_output=True, text=True, cwd=project, env=child_env(drop, extra)
    )


@docker
def test_eval_overlay_renders_with_complete_env(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV)

    rendered = render(
        project, ["docker-compose.yml", "docker-compose.dev.yml", "eval/docker-compose.eval.yml"]
    )

    assert rendered.returncode == 0, rendered.stderr
    config = yaml.safe_load(rendered.stdout)
    assert BASE_SERVICES <= set(config["services"])
    assert "--reload" in rendered.stdout  # dev overlay still in the merge


@docker
def test_eval_overlay_fails_loud_on_missing_required_var(tmp_path: Path) -> None:
    env = {k: v for k, v in COMPLETE_ENV.items() if k != "LLM_TRIAGER"}
    project = stage(tmp_path, env)

    rendered = render(
        project,
        ["docker-compose.yml", "docker-compose.dev.yml", "eval/docker-compose.eval.yml"],
        drop=("LLM_TRIAGER",),
    )

    assert rendered.returncode != 0
    assert "LLM_TRIAGER" in rendered.stderr


@docker
def test_eval_overlay_fails_loud_on_empty_required_var(tmp_path: Path) -> None:
    env = dict(COMPLETE_ENV, LLM_ANALYSER="")
    project = stage(tmp_path, env)

    rendered = render(
        project,
        ["docker-compose.yml", "docker-compose.dev.yml", "eval/docker-compose.eval.yml"],
        drop=("LLM_ANALYSER",),
    )

    assert rendered.returncode != 0
    assert "LLM_ANALYSER" in rendered.stderr


@docker
def test_eval_overlay_requires_the_env_file(tmp_path: Path) -> None:
    project = stage(tmp_path, None)

    # Every required var is present in the process env, so only a missing
    # `.env` can fail the render - the overlay's `required: true`.
    rendered = render(
        project,
        ["docker-compose.yml", "docker-compose.dev.yml", "eval/docker-compose.eval.yml"],
        extra=dict(COMPLETE_ENV),
    )

    assert rendered.returncode != 0
    assert ".env" in rendered.stderr


@docker
def test_base_compose_renders_unchanged_without_overlay(tmp_path: Path) -> None:
    project = stage(tmp_path, COMPLETE_ENV, with_overlay=False)

    rendered = render(project, ["docker-compose.yml"], drop=tuple(COMPLETE_ENV))

    assert rendered.returncode == 0, rendered.stderr
    config = yaml.safe_load(rendered.stdout)
    assert set(config["services"]) == BASE_SERVICES
