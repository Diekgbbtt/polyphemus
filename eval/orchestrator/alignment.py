"""The alignment step: assert the advance delta, decide, execute or hold (#274).

The sync daemon is mechanical (D34/D42): it fast-forwards `eval`, computes the
stack manifest/fingerprint, and emits the `DecisionInput` diff in its heartbeat.
This module is the orchestrator half. It asserts that a difference exists,
interposes an agent turn (the `AlignmentDecider` seam) carrying the delta, the
documented impact map as DATA, and the environment context, then executes the
returned actions through the one command seam or escalates and writes a hold.

No per-class policy lives here. There is deliberately no branch on
`artifact_class` that chooses an action; the map below is guidance the prompt
receives, and even an artifact class the map does not name is passed to the
decider verbatim. The code only: (1) honours the decision, (2) resolves a
declared migration/rebuild command by class, and (3) records what it applied so
a re-run is idempotent. A jump the decider cannot align without an operator
decision becomes a hold (atomic) that blocks `up`/`trial` until an operator
resolves it with `alignment resolve`; the daemon's advance is never reverted
(D38: no rewind).

Every effect is injected - the decider, the `CommandRunner`, the clock, the
`FileStore` - so the unit tier needs no Docker and no agent. Import performs no
I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

import yaml

from advance.images import COMPONENTS, default_containers
from orchestrator import subagents
from orchestrator.commands import Command, CommandRunner
from orchestrator.files import FileStore
from orchestrator.ids import short_id
from orchestrator.instances import InstancePaths, compose_argv, plan_preflight
from orchestrator.setup import AlignmentDeclarations

# `eval/orchestrator/alignment.py` -> `eval/prompts/alignment.md`.
ALIGNMENT_PROMPT = Path(__file__).parents[1] / "prompts" / "alignment.md"
# The alignment state (holds + applied actions) and the daemon heartbeat the
# decision input is read from. Both are overridable by CLI/env.
DEFAULT_STATE_PATH = Path("eval/state/alignment.yaml")
DEFAULT_HEARTBEAT_PATH = Path("eval/state/heartbeat.json")

# The action vocabulary a decision may use. Not a policy: the decider chooses.
RESTART = "restart"
RECREATE = "recreate"
CONFIG_ALIGN = "config_align"
MIGRATION = "migration"
REBUILD = "rebuild"
ACTION_KINDS = (RESTART, RECREATE, CONFIG_ALIGN, MIGRATION, REBUILD)

# I6: the artifact class -> running component(s) it can impact, used to bound a
# restart/recreate to the delta's impacted set. Data, not a decision branch: a
# class the map does not name contributes no component, and a decider naming a
# component outside the impacted set escalates rather than touching it.
COMPONENTS_BY_ARTIFACT_CLASS: Mapping[str, tuple[str, ...]] = {
    "exec_plane": ("kali",),
    "gateway": ("litellm",),
    "agent_code": ("agent",),
    "schema_data_layout": ("postgres",),
    "topology_env": COMPONENTS,
    "config_schema": COMPONENTS,
    "platform": COMPONENTS,
    "image_definition": COMPONENTS,
}

# Ready / failed / planned / skipped. `skipped` means already applied for this
# version; `planned` is dry-run; `failed` always carries evidence.
STATUS_APPLIED = "applied"
STATUS_FAILED = "failed"
STATUS_PLANNED = "planned"
STATUS_SKIPPED = "skipped"


class AlignmentError(RuntimeError):
    """The alignment step could not be planned, decided, or executed."""


class AlignmentHoldError(AlignmentError):
    """An unresolved alignment hold refuses a trial/bring-up (D42)."""

    def __init__(self, hold: "Hold") -> None:
        super().__init__(f"alignment hold {hold.hold_id}: {hold.rationale}")
        self.hold_id = hold.hold_id
        self.rationale = hold.rationale


# --- the documented impact map (data, never a decision branch) ----------------


@dataclass(frozen=True)
class ImpactEntry:
    """One row of the ADR section 4 map: artifact -> component -> action."""

    artifact: str
    component: str
    action: str


IMPACT_MAP: tuple[ImpactEntry, ...] = (
    ImpactEntry(
        "src/**, skills/**, lightrag/**",
        "agent code/knowledge",
        "none (bind mount + uvicorn --reload)",
    ),
    ImpactEntry("kali/**", "exec plane", "docker restart kali"),
    ImpactEntry("gateway/**", "litellm", "docker restart litellm (never hot-reloads)"),
    ImpactEntry("docker-compose*.yml", "topology/env", "recreate the affected services"),
    ImpactEntry(".env.example", "config schema", "config-layer alignment (preflight + recreate)"),
    ImpactEntry(
        "db/**, data-root layout code",
        "database schema / data layout",
        "declared migration, else operator decision",
    ),
    ImpactEntry(
        "requirements*.txt, pyproject.toml, dependency locks",
        "python platform",
        "declared rebuild, else operator decision",
    ),
    ImpactEntry(
        "Dockerfile*, kali/Dockerfile",
        "image definitions",
        "declared rebuild, else operator decision",
    ),
)


# --- the decision seam --------------------------------------------------------


@dataclass(frozen=True)
class DecisionAction:
    """One decided alignment action; the executor resolves it mechanically."""

    kind: str
    component: str | None = None
    services: tuple[str, ...] = ()
    instance: str | None = None
    artifact_class: str | None = None
    image: str | None = None
    command: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class AlignmentDecision:
    """Either a list of actions, or an explicit not-alignable escalation."""

    actions: tuple[DecisionAction, ...] = ()
    escalation: str | None = None


@dataclass(frozen=True)
class AlignmentRequest:
    """What the decider (the agent turn) receives: delta, map, environment."""

    prompt: Path
    input_file: Path
    destination: Path
    decision_input: Mapping
    impact_map: tuple[ImpactEntry, ...]
    environment: Mapping


class AlignmentDecider(Protocol):
    """The injected seam: the real one interposes an agent turn (D42)."""

    def decide(self, request: AlignmentRequest) -> AlignmentDecision: ...


# The static decider is the shared shape (`subagents.StaticDecider`); the module
# keeps the public name for callers that reach it off this module.
StaticDecider = subagents.StaticDecider


def render_request_input(request: AlignmentRequest) -> str:
    """The agent-turn input: the delta, the impact map, and the environment."""
    payload = {
        "decision_input": request.decision_input,
        "impact_map": [asdict(entry) for entry in request.impact_map],
        "environment": request.environment,
    }
    return yaml.safe_dump(payload, sort_keys=False)


def plan_dispatch(
    request: AlignmentRequest,
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Command:
    """Render the configured agent command with `{prompt}`/`{input}`/`{destination}`."""
    return subagents.plan_dispatch(
        request, argv, cwd=cwd, env=env, description="alignment decision"
    )


def load_decision(path: str | Path, *, files: FileStore) -> AlignmentDecision:
    """Read and validate the agent-written decision document."""
    if not files.exists(path):
        raise AlignmentError(f"alignment decision not found: {path}")
    try:
        payload = yaml.safe_load(files.read_text(path))
    except yaml.YAMLError as exc:
        raise AlignmentError(f"alignment decision {path}: invalid YAML: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise AlignmentError(f"alignment decision {path}: expected a mapping")
    escalation = payload.get("escalation")
    if escalation is not None and not isinstance(escalation, str):
        raise AlignmentError(f"alignment decision {path}: escalation must be a string")
    raw_actions = payload.get("actions") or []
    if not isinstance(raw_actions, list):
        raise AlignmentError(f"alignment decision {path}: actions must be a list")
    return AlignmentDecision(
        actions=tuple(_parse_action(entry, path) for entry in raw_actions),
        escalation=escalation or None,
    )


def _parse_action(entry: object, path: str | Path) -> DecisionAction:
    if not isinstance(entry, Mapping):
        raise AlignmentError(f"alignment decision {path}: every action must be a mapping")
    kind = entry.get("kind")
    if kind not in ACTION_KINDS:
        raise AlignmentError(
            f"alignment decision {path}: unknown action kind {kind!r} "
            f"(expected one of {', '.join(ACTION_KINDS)})"
        )
    services = entry.get("services") or []
    if not isinstance(services, list) or not all(isinstance(s, str) for s in services):
        raise AlignmentError(f"alignment decision {path}: services must be a list of strings")
    command = entry.get("command") or []
    if not isinstance(command, list) or not all(isinstance(c, str) for c in command):
        raise AlignmentError(f"alignment decision {path}: command must be a list of strings")
    return DecisionAction(
        kind=str(kind),
        component=entry.get("component"),
        services=tuple(services),
        instance=entry.get("instance"),
        artifact_class=entry.get("artifact_class"),
        image=entry.get("image"),
        command=tuple(command),
        reason=str(entry.get("reason") or ""),
    )


@dataclass
class SubagentAlignmentDecider:
    """The production seam: write the input, run the agent command, read the decision."""

    runner: CommandRunner
    argv: tuple[str, ...]
    prompt: Path = ALIGNMENT_PROMPT
    cwd: str | None = None
    env: Mapping[str, str] | None = None
    files: FileStore = field(default_factory=FileStore)

    def decide(self, request: AlignmentRequest) -> AlignmentDecision:
        return subagents.decide_via_agent(
            request,
            runner=self.runner,
            argv=self.argv,
            files=self.files,
            render_input=render_request_input,
            load=load_decision,
            error=AlignmentError,
            description="alignment decision",
            cwd=self.cwd,
            env=self.env,
        )


# --- the environment context --------------------------------------------------


@dataclass(frozen=True)
class AlignmentEnvironment:
    """The instances and the declared migrations/rebuilds the decider sees."""

    instances: tuple[InstancePaths, ...]
    declarations: AlignmentDeclarations = AlignmentDeclarations()

    @property
    def repo(self) -> Path | None:
        return self.instances[0].repo if self.instances else None


def environment_context(environment: AlignmentEnvironment) -> dict:
    """The JSON-ready environment facts the agent turn receives."""
    declarations = environment.declarations
    return {
        "instances": [
            {
                "instance_id": paths.instance.instance_id,
                "compose_project": paths.compose_project,
                "worktree": str(paths.worktree),
                "env_file": str(paths.env_file),
            }
            for paths in environment.instances
        ],
        "declarations": {
            "migrations": [asdict(m) for m in declarations.migrations],
            "rebuilds": [asdict(r) for r in declarations.rebuilds],
        },
    }


# --- the state: holds and applied actions -------------------------------------


# The alignment-state namespace for the surfer's handled-trigger keys. Reusing
# the alignment `applied` map keeps one atomic state file; this constant pair
# isolates the surfer's handled keys from the alignment's per-version action
# keys. Defined here (surfer aliases them) so `resolve_hold` can clear the
# markers a surfer hold recorded, re-arming its triggers (I7).
SURFER_HANDLED_SHA = "surfer"
SURFER_HANDLED_FINGERPRINT = ""


@dataclass(frozen=True)
class Hold:
    """An unresolved alignment escalation; blocks trials until resolved."""

    hold_id: str
    rationale: str
    target_sha: str
    target_fingerprint: str
    created_at: str
    resolved: bool = False
    decision: str | None = None
    resolved_at: str | None = None
    # I7: the surfer trigger identities this hold disarmed, so resolving it can
    # re-arm them; `history` records the operator resolutions of prior re-opens.
    trigger_keys: tuple[str, ...] = ()
    history: tuple[Mapping, ...] = ()


def _hold_from(entry: Mapping) -> Hold:
    history = entry.get("history") or []
    trigger_keys = entry.get("trigger_keys") or []
    return Hold(
        hold_id=str(entry.get("hold_id") or ""),
        rationale=str(entry.get("rationale") or ""),
        target_sha=str(entry.get("target_sha") or ""),
        target_fingerprint=str(entry.get("target_fingerprint") or ""),
        created_at=str(entry.get("created_at") or ""),
        resolved=bool(entry.get("resolved")),
        decision=(str(entry["decision"]) if entry.get("decision") is not None else None),
        resolved_at=(
            str(entry["resolved_at"]) if entry.get("resolved_at") is not None else None
        ),
        trigger_keys=tuple(str(key) for key in trigger_keys if key is not None),
        history=tuple(
            item for item in history if isinstance(item, Mapping)
        ),
    )


def _pair_key(target_sha: str, target_fingerprint: str) -> str:
    return f"{target_sha}@{target_fingerprint}"


class AlignmentState:
    """The eval-wide alignment state: atomic hold markers and applied actions."""

    def __init__(self, path: str | Path, *, files: FileStore | None = None) -> None:
        self.path = Path(path)
        self._files = files or FileStore()

    # -- holds -------------------------------------------------------------

    def holds(self) -> tuple[Hold, ...]:
        return tuple(_hold_from(entry) for entry in self._load()["holds"])

    def unresolved_holds(self) -> tuple[Hold, ...]:
        return tuple(hold for hold in self.holds() if not hold.resolved)

    def require_no_holds(self) -> None:
        """Raise `AlignmentHoldError` naming the first unresolved hold."""
        holds = self.unresolved_holds()
        if holds:
            raise AlignmentHoldError(holds[0])

    def add_hold(
        self,
        *,
        target_sha: str,
        target_fingerprint: str,
        rationale: str,
        now: str,
        trigger_keys: Sequence[str] = (),
    ) -> Hold:
        """Write a hold marker atomically; re-adding the same one is idempotent.

        I7: if the same hold was resolved, re-adding re-opens it (unresolved
        again) and appends the prior resolution to its `history`, so a condition
        that persists after an operator resolution re-escalates with that
        context recorded.
        """
        payload = self._load()
        hold_id = short_id(f"{target_sha}:{target_fingerprint}:{rationale}")
        keys = tuple(str(key) for key in trigger_keys if key is not None)
        for entry in payload["holds"]:
            if entry.get("hold_id") != hold_id:
                continue
            if entry.get("resolved"):
                history = list(entry.get("history") or [])
                history.append(
                    {
                        "decision": entry.get("decision"),
                        "resolved_at": entry.get("resolved_at"),
                    }
                )
                entry["history"] = history
                entry["resolved"] = False
                entry["decision"] = None
                entry["resolved_at"] = None
                if keys:
                    entry["trigger_keys"] = sorted(set(entry.get("trigger_keys") or []) | set(keys))
                self._write(payload)
            return _hold_from(entry)
        hold = Hold(
            hold_id=hold_id,
            rationale=rationale,
            target_sha=target_sha,
            target_fingerprint=target_fingerprint,
            created_at=now,
            trigger_keys=keys,
        )
        payload["holds"].append(asdict(hold))
        self._write(payload)
        return hold

    def resolve_hold(self, hold_id: str, decision: str, *, now: str | None = None) -> Hold:
        """Record the operator's decision and clear the hold (D38: no rewind).

        I7: the surfer handled markers recorded under this hold's triggers are
        cleared, so the next surfer cycle re-asserts; a condition that persists
        re-escalates (and re-opens the hold with this decision in its history).
        """
        payload = self._load()
        for entry in payload["holds"]:
            if entry.get("hold_id") != hold_id:
                continue
            if entry.get("resolved"):
                raise AlignmentError(f"alignment hold {hold_id!r} is already resolved")
            entry["resolved"] = True
            entry["decision"] = decision
            entry["resolved_at"] = (now or subagents.utcnow)()
            self._clear_surfer_markers(payload, entry.get("trigger_keys") or [])
            self._write(payload)
            return _hold_from(entry)
        raise AlignmentError(f"no alignment hold {hold_id!r}")

    def _clear_surfer_markers(self, payload: dict, trigger_keys: Sequence) -> None:
        """Clear the surfer handled markers for `trigger_keys` (I7)."""
        keys = {str(key) for key in trigger_keys if key is not None}
        if not keys:
            return
        pair = _pair_key(SURFER_HANDLED_SHA, SURFER_HANDLED_FINGERPRINT)
        current = [str(key) for key in payload["applied"].get(pair, [])]
        remaining = [key for key in current if key not in keys]
        if remaining:
            payload["applied"][pair] = remaining
        else:
            payload["applied"].pop(pair, None)

    # -- applied actions (idempotency) -------------------------------------

    def applied_for(self, target_sha: str, target_fingerprint: str) -> frozenset[str]:
        applied = self._load()["applied"].get(_pair_key(target_sha, target_fingerprint), [])
        return frozenset(str(key) for key in applied)

    def record_applied(
        self,
        target_sha: str,
        target_fingerprint: str,
        keys: Sequence[str],
    ) -> None:
        payload = self._load()
        pair = _pair_key(target_sha, target_fingerprint)
        current = [str(key) for key in payload["applied"].get(pair, [])]
        for key in keys:
            if key not in current:
                current.append(key)
        payload["applied"][pair] = current
        self._write(payload)

    # -- storage -----------------------------------------------------------

    def _load(self) -> dict:
        if not self._files.is_file(self.path):
            return {"holds": [], "applied": {}}
        try:
            payload = yaml.safe_load(self._files.read_text(self.path))
        except yaml.YAMLError as exc:
            raise AlignmentError(f"alignment state {self.path}: invalid YAML: {exc}") from exc
        if payload is None:
            return {"holds": [], "applied": {}}
        if not isinstance(payload, Mapping):
            raise AlignmentError(f"alignment state {self.path}: expected a mapping")
        holds = payload.get("holds") or []
        applied = payload.get("applied") or {}
        if not isinstance(holds, list) or not isinstance(applied, Mapping):
            raise AlignmentError(f"alignment state {self.path}: malformed holds/applied")
        return {"holds": list(holds), "applied": dict(applied)}

    def _write(self, payload: Mapping) -> None:
        self._files.write_text_atomic(self.path, yaml.safe_dump(dict(payload), sort_keys=False))


# --- execution ----------------------------------------------------------------


@dataclass(frozen=True)
class ActionResult:
    """One action's outcome, with evidence when it failed."""

    action: DecisionAction
    key: str
    status: str
    evidence: str = ""


@dataclass(frozen=True)
class AlignmentOutcome:
    """The whole run: what was applied, or the hold an escalation wrote."""

    target_sha: str
    target_fingerprint: str
    results: tuple[ActionResult, ...] = ()
    hold: Hold | None = None
    escalated: bool = False
    no_op: bool = False
    escalation: str | None = None

    @property
    def failures(self) -> tuple[ActionResult, ...]:
        return tuple(result for result in self.results if result.status == STATUS_FAILED)

    @property
    def ok(self) -> bool:
        return not self.failures and not self.escalated


def action_key(action: DecisionAction) -> str:
    """A stable identity for one action, for the idempotency record."""
    if action.kind == RESTART:
        return f"restart:{action.component}"
    if action.kind == RECREATE:
        return f"recreate:{','.join(action.services)}"
    if action.kind == CONFIG_ALIGN:
        return f"config_align:{action.instance or '*'}"
    if action.kind == MIGRATION:
        return f"migration:{action.artifact_class}"
    if action.kind == REBUILD:
        return f"rebuild:{action.image or action.artifact_class}"
    return f"{action.kind}:{action.component or action.artifact_class or ''}"


def run(
    decision_input: Mapping,
    *,
    decider: AlignmentDecider,
    environment: AlignmentEnvironment,
    runner: CommandRunner,
    state: AlignmentState,
    dry_run: bool = False,
    now: Callable[[], str] | None = None,
    prompt: Path | None = None,
    request_dir: Path | None = None,
) -> AlignmentOutcome:
    """Assert the delta, decide, execute, and record - or escalate and hold."""
    now = now or subagents.utcnow
    changed = _changed_entries(decision_input)
    images_changed = _images_changed(decision_input)
    target_sha, target_fp = _identity(decision_input)

    # Nothing moved: there is no alignment to decide (a true no-op).
    if not changed and not images_changed:
        return AlignmentOutcome(
            target_sha, target_fp, no_op=True
        )

    directory = Path(request_dir) if request_dir is not None else state.path.parent
    request = AlignmentRequest(
        prompt=Path(prompt) if prompt is not None else ALIGNMENT_PROMPT,
        input_file=directory / "alignment-input.yaml",
        destination=directory / "alignment-decision.yaml",
        decision_input=decision_input,
        impact_map=IMPACT_MAP,
        environment=environment_context(environment),
    )
    decision = decider.decide(request)

    if decision.escalation:
        hold = None
        if not dry_run:
            hold = state.add_hold(
                target_sha=target_sha,
                target_fingerprint=target_fp,
                rationale=decision.escalation,
                now=now(),
            )
        return AlignmentOutcome(
            target_sha,
            target_fp,
            hold=hold,
            escalated=True,
            escalation=decision.escalation,
        )

    if not decision.actions:
        return AlignmentOutcome(target_sha, target_fp, no_op=True)

    # C1/D28: a decider-supplied inline command is never an authority. It must
    # be covered by a setup declaration (or it is a hold); the declaration's
    # command is what runs. This is the version freeze: no arbitrary shell.
    # I6: a restart/recreate may only name a component or service the delta
    # actually impacted; anything else is a hold, never a broader blast radius.
    impacted = _impacted_components(decision_input)
    for action in decision.actions:
        refusal = _undeclared_inline_command(
            action, environment.declarations
        ) or _out_of_scope_action(action, impacted)
        if refusal is None:
            continue
        hold = None
        if not dry_run:
            hold = state.add_hold(
                target_sha=target_sha,
                target_fingerprint=target_fp,
                rationale=refusal,
                now=now(),
            )
        return AlignmentOutcome(
            target_sha,
            target_fp,
            hold=hold,
            escalated=True,
            escalation=refusal,
        )

    applied = state.applied_for(target_sha, target_fp)
    results: list[ActionResult] = []
    newly_applied: list[str] = []
    for action in decision.actions:
        key = action_key(action)
        if not dry_run and key in applied:
            results.append(
                ActionResult(
                    action,
                    key,
                    STATUS_SKIPPED,
                    "already applied for this version",
                )
            )
            continue
        result = _execute(action, key, environment, runner, dry_run=dry_run)
        results.append(result)
        if result.status == STATUS_APPLIED:
            newly_applied.append(key)

    if not dry_run and newly_applied:
        state.record_applied(target_sha, target_fp, newly_applied)
    return AlignmentOutcome(target_sha, target_fp, results=tuple(results))


def _execute(
    action: DecisionAction,
    key: str,
    environment: AlignmentEnvironment,
    runner: CommandRunner,
    *,
    dry_run: bool,
) -> ActionResult:
    """Plan and run one action; a failure carries the command and its stderr."""
    try:
        if action.kind == CONFIG_ALIGN:
            return _execute_config_align(action, key, environment, runner, dry_run=dry_run)
        commands = _plan_commands(action, environment)
    except AlignmentError as exc:
        return ActionResult(action, key, STATUS_FAILED, str(exc))

    if dry_run:
        return ActionResult(action, key, STATUS_PLANNED, _display(commands))
    return _run_commands(action, key, commands, runner)


def _run_commands(
    action: DecisionAction, key: str, commands: Sequence[Command], runner: CommandRunner
) -> ActionResult:
    evidence: list[str] = []
    for command in commands:
        result = runner(command)
        evidence.append(command.display())
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            return ActionResult(
                action,
                key,
                STATUS_FAILED,
                f"exit {result.returncode}: {detail}",
            )
    return ActionResult(action, key, STATUS_APPLIED, "; ".join(evidence))


def _display(commands: Sequence[Command]) -> str:
    return "; ".join(command.display() for command in commands)


def _target_instances(
    action: DecisionAction, environment: AlignmentEnvironment
) -> tuple[InstancePaths, ...]:
    if action.instance is None:
        return environment.instances
    selected = tuple(
        paths for paths in environment.instances if paths.instance.instance_id == action.instance
    )
    if not selected:
        raise AlignmentError(
            f"action names instance {action.instance!r}, which is not in the environment"
        )
    return selected


def _container_name(paths: InstancePaths, component: str) -> str:
    containers = default_containers(paths.compose_project)
    return containers.get(component, f"{paths.compose_project}-{component}-1")


def _plan_commands(
    action: DecisionAction, environment: AlignmentEnvironment
) -> tuple[Command, ...]:
    if action.kind == RESTART:
        if not action.component:
            raise AlignmentError("restart action names no component")
        return tuple(
            Command(
                argv=("docker", "restart", _container_name(paths, action.component)),
                description=f"restart {action.component} for {paths.instance.instance_id}",
            )
            for paths in _target_instances(action, environment)
        )
    if action.kind == RECREATE:
        if not action.services:
            raise AlignmentError("recreate action names no services")
        return tuple(
            Command(
                argv=tuple(compose_argv(paths, "up", "-d", "--force-recreate", *action.services)),
                cwd=str(paths.worktree),
                description=(
                    f"recreate {', '.join(action.services)} for {paths.instance.instance_id}"
                ),
            )
            for paths in _target_instances(action, environment)
        )
    if action.kind in (MIGRATION, REBUILD):
        command = _resolve_declared_command(action, environment.declarations)
        if command is None:
            raise AlignmentError(
                f"no declared {action.kind} for "
                f"{action.artifact_class or action.image!r}; the decider must escalate"
            )
        repo = environment.repo
        return (
            Command(
                argv=tuple(command),
                cwd=str(repo) if repo is not None else None,
                description=f"{action.kind} {action.artifact_class or action.image}",
            ),
        )
    raise AlignmentError(f"unknown action kind {action.kind!r}")


def _resolve_declared_command(
    action: DecisionAction, declarations: AlignmentDeclarations
) -> tuple[str, ...] | None:
    """The declared migration/rebuild command matching the action, or None.

    The declaration is the only authority (D28): the action's own `command` is
    never a source here, so the decider can only name a declared recipe. An
    inline command that does not match a declaration is escalated by
    `_undeclared_inline_command` before execution is ever planned.
    """
    if action.kind == MIGRATION and action.artifact_class:
        for migration in declarations.migrations:
            if migration.artifact_class == action.artifact_class:
                return tuple(migration.command)
    if action.kind == REBUILD:
        for rebuild in declarations.rebuilds:
            class_matches = (
                action.artifact_class is not None
                and rebuild.artifact_class == action.artifact_class
            )
            image_matches = action.image is not None and rebuild.image == action.image
            if class_matches or image_matches:
                return tuple(rebuild.command)
    return None


def _undeclared_inline_command(
    action: DecisionAction, declarations: AlignmentDeclarations
) -> str | None:
    """A refusal rationale when an inline command is not covered by a declaration.

    The decider may name a declared migration/rebuild, but a command it supplies
    itself must exactly match a declaration's; anything else is an escalation,
    never an execution (D28, the version freeze).
    """
    if action.kind not in (MIGRATION, REBUILD) or not action.command:
        return None
    declared = _resolve_declared_command(action, declarations)
    if declared is not None and tuple(action.command) == declared:
        return None
    return (
        f"decider-supplied {action.kind} command {list(action.command)!r} for "
        f"{action.artifact_class or action.image!r} is not covered by a setup "
        "declaration; refusing to execute (D28)"
    )


# The preflight report's keyset counts; a changed keyset needs a recreate.
_ADDED_RE = re.compile(r"^added \((\d+)\)", re.MULTILINE)
_EXTRA_RE = re.compile(r"^extra \((\d+)\)", re.MULTILINE)


def keyset_changed(stdout: str) -> bool:
    """True when the preflight added or found extra keys (a keyset change)."""
    added = _ADDED_RE.search(stdout)
    extra = _EXTRA_RE.search(stdout)
    if added is None or extra is None:
        raise AlignmentError(
            "env_preflight output did not report added/extra keyset counts"
        )
    return int(added.group(1)) > 0 or int(extra.group(1)) > 0


def _execute_config_align(
    action: DecisionAction,
    key: str,
    environment: AlignmentEnvironment,
    runner: CommandRunner,
    *,
    dry_run: bool,
) -> ActionResult:
    commands: list[Command] = []
    for paths in _target_instances(action, environment):
        commands.append(plan_preflight(paths))
        commands.append(
            Command(
                argv=tuple(compose_argv(paths, "up", "-d", "--force-recreate")),
                cwd=str(paths.worktree),
                description=f"recreate {paths.instance.instance_id} after env alignment",
            )
        )
    if dry_run:
        return ActionResult(action, key, STATUS_PLANNED, _display(commands))

    evidence: list[str] = []
    for index in range(0, len(commands), 2):
        preflight, recreate = commands[index], commands[index + 1]
        result = runner(preflight)
        evidence.append(preflight.display())
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            return ActionResult(action, key, STATUS_FAILED, f"exit {result.returncode}: {detail}")
        try:
            changed = keyset_changed(result.stdout)
        except AlignmentError as exc:
            return ActionResult(action, key, STATUS_FAILED, str(exc))
        if not changed:
            evidence.append("keyset unchanged; recreate skipped")
            continue
        result = runner(recreate)
        evidence.append(recreate.display())
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            return ActionResult(action, key, STATUS_FAILED, f"exit {result.returncode}: {detail}")
    return ActionResult(action, key, STATUS_APPLIED, "; ".join(evidence))


# --- decision-input normalisation --------------------------------------------


def _impacted_components(decision_input: Mapping) -> frozenset[str]:
    """The components/services the delta actually impacted (I6).

    A changed artifact class contributes its mapped component(s); a changed
    running image contributes the component itself. This bounds a restart or
    recreate to what moved.
    """
    impacted: set[str] = set()
    for entry in _changed_entries(decision_input):
        artifact_class = str(entry.get("artifact_class") or "")
        impacted.update(COMPONENTS_BY_ARTIFACT_CLASS.get(artifact_class, ()))
    for entry in _images_changed(decision_input):
        component = entry.get("component")
        if component:
            impacted.add(str(component))
    return frozenset(impacted)


def _out_of_scope_action(
    action: DecisionAction, impacted: frozenset[str]
) -> str | None:
    """A refusal rationale when a restart/recreate names a non-impacted name.

    I6: the decider may not widen the blast radius beyond the delta. A name
    outside the impacted set is a hold, never an execution.
    """
    if action.kind == RESTART:
        if action.component and action.component not in impacted:
            return (
                f"restart names component {action.component!r}, which is not in "
                f"the delta's impacted components ({_impacted_text(impacted)})"
            )
        return None
    if action.kind == RECREATE:
        outside = [service for service in action.services if service not in impacted]
        if outside:
            return (
                f"recreate names service(s) {', '.join(outside)}, which are not in "
                f"the delta's impacted components ({_impacted_text(impacted)})"
            )
        return None
    return None


def _impacted_text(impacted: frozenset[str]) -> str:
    return ", ".join(sorted(impacted)) or "none"


def _changed_entries(decision_input: Mapping) -> tuple[Mapping, ...]:
    delta = decision_input.get("delta") or {}
    changed = delta.get("changed") or []
    return tuple(entry for entry in changed if isinstance(entry, Mapping))


def _images_changed(decision_input: Mapping) -> tuple[Mapping, ...]:
    delta = decision_input.get("delta") or {}
    changed = delta.get("images_changed") or []
    return tuple(entry for entry in changed if isinstance(entry, Mapping))


def _identity(decision_input: Mapping) -> tuple[str, str]:
    dev = str(decision_input.get("dev_sha") or "")
    eval_sha = str(decision_input.get("eval_sha") or "")
    fingerprints = decision_input.get("fingerprints") or {}
    fingerprint = str(fingerprints.get("dev") or fingerprints.get("eval") or "")
    return (dev or eval_sha, fingerprint)
