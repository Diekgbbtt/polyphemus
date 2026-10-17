"""Run configuration: `run.yaml` -> `RunConfig`, plus the resolved snapshot.

The config describes one regeneration run: its identity, the targets, the
environment driver, the worker model, the timeouts and policy, and the paths of
the procedure carriers the wrappers are built from.

Two shape rules matter for the run's resumability:

* every path resolves to an ABSOLUTE path against the repository root (a
  relative path in the yaml is repo-relative), so a run started from any cwd
  behaves the same;
* the resolved config is written into the run directory as
  `config.resolved.yaml`, so `resume` and `status` are self-contained even if
  the operator's original yaml moved (the digest recorded in the state detects a
  real drift).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from runner.harness import ModelRef
from runner.state import config_digest

# Defaults, pinned by the architecture doc and the issue:
DEFAULT_AGENT = "data-dep-worker"
DEFAULT_MODEL = ModelRef("opencode", "deepseek-v4.1-flash-free", "high")
DEFAULT_TURN_TIMEOUT_S = 3600.0
DEFAULT_REPAIR_ATTEMPTS = 3
DEFAULT_TIMEOUT_REPROMPTS = 1
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_S = (60.0, 300.0, 900.0)
DEFAULT_READINESS_RETRIES = 60
DEFAULT_READINESS_INTERVAL_S = 5.0
DEFAULT_RUNDIR_ROOT = ".bootstrap-runs"
DEFAULT_STAGING = "eval/data-dependencies"
DEFAULT_KBS = "eval/data/webexploitbench"
DEFAULT_WEB_ROOT = "~/WebExploitBench"
DEFAULT_PROMPTS = "tools/bootstrap/prompts"
DEFAULT_CONTRACT = "tools/bootstrap/DATA-DEPENDENCIES.md"
DEFAULT_META_SKILL = "skills/meta/authn-skill-writing/SKILL.md"
DEFAULT_VALIDATOR = "tools/bootstrap/validate_data_dependencies.py"
DEFAULT_TARGETCTL = "/root/wb"


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded backoff for a transient provider failure."""

    attempts: int = DEFAULT_RETRY_ATTEMPTS
    backoff_s: tuple[float, ...] = DEFAULT_RETRY_BACKOFF_S


@dataclass(frozen=True)
class ReadinessPolicy:
    """The bounded readiness window; the platform's own defaults (60 x 5s)."""

    retries: int = DEFAULT_READINESS_RETRIES
    interval_s: float = DEFAULT_READINESS_INTERVAL_S


@dataclass(frozen=True)
class RunSection:
    """The `run:` block: identity, targets, model, timeouts, and policy."""

    id: str
    worktree: Path
    targets: tuple[str, ...]
    agent: str = DEFAULT_AGENT
    model: ModelRef = DEFAULT_MODEL
    per_target_model: Mapping[str, ModelRef] = field(default_factory=dict)
    turn_timeout_s: float = DEFAULT_TURN_TIMEOUT_S
    repair_attempts: int = DEFAULT_REPAIR_ATTEMPTS
    timeout_reprompts: int = DEFAULT_TIMEOUT_REPROMPTS
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    readiness: ReadinessPolicy = field(default_factory=ReadinessPolicy)
    teardown_on_failure: bool = True
    continue_on_failure: bool = True

    def model_for(self, target: str) -> ModelRef:
        """The worker model for one target: the per-target override wins."""
        return self.per_target_model.get(target, self.model)


@dataclass(frozen=True)
class EnvironmentSection:
    """The `environment:` block: which driver, and that driver's description."""

    driver: str = "ssh"
    ssh: str = ""
    web_root: str = DEFAULT_WEB_ROOT
    targetctl: str = DEFAULT_TARGETCTL
    public_host: str = ""
    local_dir: Path | None = None
    targetctl_local: str = ""
    base_url: str = ""
    bash: str = ""
    docker_platform: str = "linux/amd64"


@dataclass(frozen=True)
class PathsSection:
    """The `paths:` block: the procedure carriers and the data roots."""

    kbs: Path
    staging: Path
    prompts: Path
    contract: Path
    meta_skill: Path
    validator: Path
    authn_prompt: Path
    l1_prompt: Path

    def target_dir(self, target: str) -> Path:
        return self.kbs / target


@dataclass(frozen=True)
class RunConfig:
    """One complete run description, every path absolute."""

    run: RunSection
    environment: EnvironmentSection
    paths: PathsSection
    source_dir: Path

    def resolved(self) -> dict[str, Any]:
        """The resolved snapshot written into the run directory."""
        return {
            "run": {
                "id": self.run.id,
                "worktree": str(self.run.worktree),
                "targets": list(self.run.targets),
                "agent": self.run.agent,
                "model": {
                    "providerID": self.run.model.provider_id,
                    "id": self.run.model.id,
                    "variant": self.run.model.variant,
                },
                "per_target_model": {
                    target: {
                        "providerID": ref.provider_id,
                        "id": ref.id,
                        "variant": ref.variant,
                    }
                    for target, ref in self.run.per_target_model.items()
                },
                "turn_timeout_s": self.run.turn_timeout_s,
                "repair_attempts": self.run.repair_attempts,
                "timeout_reprompts": self.run.timeout_reprompts,
                "retry": {
                    "attempts": self.run.retry.attempts,
                    "backoff_s": list(self.run.retry.backoff_s),
                },
                "readiness": {
                    "retries": self.run.readiness.retries,
                    "interval_s": self.run.readiness.interval_s,
                },
                "teardown_on_failure": self.run.teardown_on_failure,
                "continue_on_failure": self.run.continue_on_failure,
            },
            "environment": {
                "driver": self.environment.driver,
                "ssh": self.environment.ssh,
                "web_root": self.environment.web_root,
                "targetctl": self.environment.targetctl,
                "public_host": self.environment.public_host,
                "local_dir": str(self.environment.local_dir or ""),
                "targetctl_local": self.environment.targetctl_local,
                "base_url": self.environment.base_url,
                "bash": self.environment.bash,
                "docker_platform": self.environment.docker_platform,
            },
            "paths": {
                "kbs": str(self.paths.kbs),
                "staging": str(self.paths.staging),
                "prompts": str(self.paths.prompts),
                "contract": str(self.paths.contract),
                "meta_skill": str(self.paths.meta_skill),
                "validator": str(self.paths.validator),
                "authn_prompt": str(self.paths.authn_prompt),
                "l1_prompt": str(self.paths.l1_prompt),
            },
        }

    @property
    def digest(self) -> str:
        return config_digest(self.resolved())

    def with_targets(self, targets: Sequence[str]) -> "RunConfig":
        """The same config restricted to a subset of targets, plan order kept."""
        chosen = tuple(target for target in self.run.targets if target in set(targets))
        missing = [target for target in targets if target not in set(self.run.targets)]
        if missing:
            raise ValueError(f"targets not in the config: {', '.join(missing)}")
        return RunConfig(
            run=replace(self.run, targets=chosen),
            environment=self.environment,
            paths=self.paths,
            source_dir=self.source_dir,
        )

    def rundir(self, root: Path | None = None) -> Path:
        """The run's directory: `<root>/<run_id>`, root defaulting to `.bootstrap-runs`."""
        base = Path(root) if root is not None else self.run.worktree / DEFAULT_RUNDIR_ROOT
        return base / self.run.id


# --- loading ----------------------------------------------------------------


def _resolve(base: Path, value: object, *, default: str | None = None) -> Path:
    raw = value if isinstance(value, str) and value.strip() else default
    if raw is None:
        raise ValueError("a required path is missing")
    path = Path(str(raw)).expanduser()
    return path if path.is_absolute() else (base / path)


def _text(value: object, default: str = "") -> str:
    return str(value).strip() if isinstance(value, str) and str(value).strip() else default


def _model(raw: object, default: ModelRef = DEFAULT_MODEL) -> ModelRef:
    if not isinstance(raw, Mapping):
        return default
    provider = _text(raw.get("providerID") or raw.get("provider_id"), default.provider_id)
    identifier = _text(raw.get("id"), default.id)
    variant = _text(raw.get("variant"), default.variant or "")
    return ModelRef(provider, identifier, variant or None)


def _number(value: object, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _integer(value: object, default: int) -> int:
    return int(_number(value, float(default)))


def _flag(value: object, default: bool) -> bool:
    return bool(value) if isinstance(value, bool) else default


def load_config(path: Path, *, repo_root: Path) -> RunConfig:
    """Read `run.yaml` into a `RunConfig` with every path resolved absolutely.

    Relative paths resolve against `repo_root` (the module's own repository, or
    the worktree the run names), never against the caller's cwd, so a plan
    printed from anywhere lists the same commands.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path}: the run config must be a YAML mapping")
    run_raw = raw.get("run") or {}
    env_raw = raw.get("environment") or {}
    paths_raw = raw.get("paths") or {}
    if not isinstance(run_raw, Mapping) or not isinstance(env_raw, Mapping) or not isinstance(paths_raw, Mapping):
        raise ValueError(f"{path}: run/environment/paths must each be a mapping")

    run_id = _text(run_raw.get("id"))
    if not run_id:
        raise ValueError(f"{path}: run.id is required")
    targets = tuple(str(t).strip() for t in (run_raw.get("targets") or []) if str(t).strip())
    if not targets:
        raise ValueError(f"{path}: run.targets must name at least one target")
    worktree = _resolve(repo_root, run_raw.get("worktree"), default=str(repo_root))
    base = worktree if worktree.is_dir() else repo_root

    retry_raw = run_raw.get("retry") if isinstance(run_raw.get("retry"), Mapping) else {}
    backoff_raw = retry_raw.get("backoff_s")
    backoff = (
        tuple(_number(v, 0.0) for v in backoff_raw)
        if isinstance(backoff_raw, list) and backoff_raw
        else DEFAULT_RETRY_BACKOFF_S
    )
    readiness_raw = (
        run_raw.get("readiness") if isinstance(run_raw.get("readiness"), Mapping) else {}
    )
    per_target_raw = run_raw.get("per_target_model") or {}

    run = RunSection(
        id=run_id,
        worktree=worktree,
        targets=targets,
        agent=_text(run_raw.get("agent"), DEFAULT_AGENT),
        model=_model(run_raw.get("model")),
        per_target_model={
            str(target): _model(raw_model)
            for target, raw_model in (per_target_raw.items() if isinstance(per_target_raw, Mapping) else [])
        },
        turn_timeout_s=_number(run_raw.get("turn_timeout_s"), DEFAULT_TURN_TIMEOUT_S),
        repair_attempts=_integer(run_raw.get("repair_attempts"), DEFAULT_REPAIR_ATTEMPTS),
        timeout_reprompts=_integer(run_raw.get("timeout_reprompts"), DEFAULT_TIMEOUT_REPROMPTS),
        retry=RetryPolicy(
            attempts=_integer(retry_raw.get("attempts"), DEFAULT_RETRY_ATTEMPTS),
            backoff_s=backoff,
        ),
        readiness=ReadinessPolicy(
            retries=_integer(readiness_raw.get("retries"), DEFAULT_READINESS_RETRIES),
            interval_s=_number(readiness_raw.get("interval_s"), DEFAULT_READINESS_INTERVAL_S),
        ),
        teardown_on_failure=_flag(run_raw.get("teardown_on_failure"), True),
        continue_on_failure=_flag(run_raw.get("continue_on_failure"), True),
    )

    driver = _text(env_raw.get("driver"), "ssh")
    if driver not in {"ssh", "local", "attach"}:
        raise ValueError(f"{path}: environment.driver {driver!r} is not ssh | local | attach")
    local_dir_raw = env_raw.get("local_dir")
    environment = EnvironmentSection(
        driver=driver,
        ssh=_text(env_raw.get("ssh")),
        web_root=_text(env_raw.get("web_root"), DEFAULT_WEB_ROOT),
        targetctl=_text(env_raw.get("targetctl"), DEFAULT_TARGETCTL),
        public_host=_text(env_raw.get("public_host")),
        local_dir=(
            _resolve(base, local_dir_raw) if local_dir_raw else None
        ),
        targetctl_local=_text(env_raw.get("targetctl_local")),
        base_url=_text(env_raw.get("base_url")),
        bash=_text(env_raw.get("bash")),
        docker_platform=_text(env_raw.get("docker_platform"), "linux/amd64"),
    )

    prompts = _resolve(base, paths_raw.get("prompts"), default=DEFAULT_PROMPTS)
    if prompts.is_dir():
        authn_prompt = prompts / "data-dep-authn.md"
        l1_prompt = prompts / "data-dep-l1.md"
    else:
        authn_prompt = _resolve(base, paths_raw.get("authn_prompt"), default=str(prompts))
        l1_prompt = _resolve(base, paths_raw.get("l1_prompt"), default="tools/bootstrap/prompts/data-dep-l1.md")
    paths = PathsSection(
        kbs=_resolve(base, paths_raw.get("kbs"), default=DEFAULT_KBS),
        staging=_resolve(base, paths_raw.get("staging"), default=DEFAULT_STAGING),
        prompts=prompts,
        contract=_resolve(base, paths_raw.get("contract"), default=DEFAULT_CONTRACT),
        meta_skill=_resolve(base, paths_raw.get("meta_skill"), default=DEFAULT_META_SKILL),
        validator=_resolve(base, paths_raw.get("validator"), default=DEFAULT_VALIDATOR),
        authn_prompt=authn_prompt,
        l1_prompt=l1_prompt,
    )
    return RunConfig(run=run, environment=environment, paths=paths, source_dir=Path(path))


def load_resolved(path: Path) -> RunConfig:
    """Read a `config.resolved.yaml` snapshot back into a `RunConfig`.

    The snapshot is written by the runner with absolute paths; this reader
    accepts it unchanged (it is the yaml shape `load_config` emits), so resume
    and status never need the original config file.
    """
    return load_config(path, repo_root=Path(path).resolve().parent)
