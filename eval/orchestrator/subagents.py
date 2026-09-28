"""The shared subagent dispatch machinery (#271/#272, D6/D15/D28).

The assessment (#271) and the diagnosis (#272) both dispatch a configured agent
command with a typed request, record each attempt append-only on the trial
record, classify a persistent failure into a bounded configuration-layer repair
or a named escalation, and persist the outcome. The shape is identical; only the
request's fields, the record/attempt types, and the error class differ, so the
machinery lives here parameterised over those.

The one third-party dependency is PyYAML (the repo's existing dependency) for
the trial-record edge; import performs no I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, ClassVar, Generic, Mapping, Protocol, Sequence, TypeVar

import yaml

from orchestrator.commands import Command, CommandRunner, require_ok
from orchestrator.files import FileStore

Request = TypeVar("Request")
Record = TypeVar("Record")
Attempt = TypeVar("Attempt")
Decision = TypeVar("Decision")

# The request fields both subagents share; the caller adds its own.
COMMON_FIELDS = (
    "prompt",
    "trial_record",
    "ground_truth",
    "data_root",
    "destination",
    "trace_id",
)


def utcnow() -> str:
    """The shared ISO-8601 UTC clock (`timespec="seconds"`)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def non_empty(raw: object, label: str, *, error: type[Exception]) -> str:
    """Refuse a falsy or non-string value, naming the field and the error class."""
    if not isinstance(raw, str) or not raw:
        raise error(f"{label}: expected a non-empty string")
    return raw


def check_identity(
    actual: object,
    expected: str | None,
    label: str,
    *,
    error: type[Exception],
    noun: str,
) -> None:
    """Refuse an absent expected identity or a row value that invents one (D32).

    Shared by the verdict and diagnosis schemas so the two can never drift: a
    row's `eval_sha`/`stack_fingerprint` must be present, non-empty, and exactly
    the trial record's value.
    """
    if not expected:
        raise error(
            f"{label}: the trial record carries no {label}; a {noun} must never "
            "invent it"
        )
    if not actual:
        raise error(f"{label}: is required on every {noun} row")
    if str(actual) != expected:
        raise error(
            f"{label}: {actual!r} does not match the trial record's {expected!r}"
        )


def common_fields(request: object) -> dict[str, str]:
    """Render the fields both request types carry; a missing value is empty."""
    values: dict[str, str] = {}
    for name in COMMON_FIELDS:
        value = getattr(request, name, None)
        values[name] = "" if value is None else str(value)
    return values


def render_command(
    argv: "tuple[str, ...] | list[str]",
    fields: Mapping[str, str],
    *,
    cwd: str | None,
    env: Mapping[str, str] | None,
    description: str,
) -> Command:
    """Render an argv template against the request's fields into a `Command`."""
    rendered = tuple(str(part).format(**fields) for part in argv)
    return Command(argv=rendered, cwd=cwd, env=env, description=description)


class DispatchRequest(Protocol):
    """The request shape every agent-decision seam renders into its command."""

    prompt: Path
    input_file: Path
    destination: Path


@dataclass
class StaticDecider(Generic[Decision]):
    """A decision already made (tests, and a supplied decision document)."""

    decision: Decision

    def decide(self, request: DispatchRequest) -> Decision:
        return self.decision


def plan_dispatch(
    request: DispatchRequest,
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    description: str,
) -> Command:
    """Render the configured agent command with `{prompt}`/`{input}`/`{destination}`."""
    return render_command(
        argv,
        {
            "prompt": str(request.prompt),
            "input": str(request.input_file),
            "destination": str(request.destination),
        },
        cwd=cwd,
        env=env,
        description=description,
    )


def decide_via_agent(
    request: DispatchRequest,
    *,
    runner: CommandRunner,
    argv: Sequence[str],
    files: FileStore,
    render_input: Callable[[DispatchRequest], str],
    load: Callable[..., Decision],
    error: type[Exception],
    description: str,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Decision:
    """Write the input, run the agent command, read the decision document.

    The shared body of every `Subagent*Decider`: the two callers differ only in
    the input renderer, the decision loader, the error class, and the command
    description, so the three I/O steps have exactly one implementation.
    """
    files.write_text(request.input_file, render_input(request))
    command = plan_dispatch(request, argv, cwd=cwd, env=env, description=description)
    require_ok(runner(command), command, error=error)
    return load(request.destination, files=files)


class Repair(Protocol):
    """The bounded, configuration-layer-only repair of D28."""

    def supports(self, cause: str) -> bool: ...

    def apply(self, cause: str) -> None: ...


class NullRepair:
    """A repair that supports nothing; its `apply` is unreachable by construction."""

    def __init__(self, error: type[Exception]) -> None:
        self._error = error

    def supports(self, cause: str) -> bool:
        return False

    def apply(self, cause: str) -> None:  # pragma: no cover - never reached
        raise self._error(f"no repair supports {cause!r}")


@dataclass
class ReDispatchRepair:
    """Re-run an injected dispatcher once with corrected paths/flags (D28)."""

    dispatcher: Callable[[Request], None]
    request: Request
    repairable: tuple[str, ...]
    error: type[Exception]

    def supports(self, cause: str) -> bool:
        return cause in self.repairable

    def apply(self, cause: str) -> None:
        self.dispatcher(self.request)


@dataclass(frozen=True)
class Failure:
    """The micro-diagnosis of a persistent failure: cause, repair, detail."""

    cause: str
    repair: str | None
    detail: str


@dataclass
class CommandDispatcher:
    """The base production seam: run the configured agent command line once.

    Subclasses bind the request type (via their `plan`) and the raised error
    class; the injected `runner` stays the same.
    """

    runner: CommandRunner
    argv: tuple[str, ...]
    cwd: str | None = None
    env: Mapping[str, str] | None = None
    error: ClassVar[type[Exception]] = RuntimeError

    def plan(self, request: Request) -> Command:  # pragma: no cover - subclassed
        raise NotImplementedError

    def __call__(self, request: Request) -> None:
        command = self.plan(request)
        require_ok(self.runner(command), command, error=self.error)


def dispatch(
    request: Request,
    *,
    dispatcher: Callable[[Request], None],
    prior: "tuple[Attempt, ...] | list[Attempt]" = (),
    now: Callable[[], str] | None = None,
    make_attempt: Callable[[int, str, str | None, str], Attempt],
    make_record: Callable[[str, "list[Attempt]", str], Record],
) -> Record:
    """Fire-and-forget dispatch; record one `dispatched` attempt (D6)."""
    now = now or utcnow
    dispatcher(request)
    attempts = list(prior)
    attempts.append(make_attempt(len(attempts) + 1, "dispatched", None, now()))
    return make_record("dispatched", attempts, str(request.destination))


def classify_failure(
    *,
    state: str,
    error: BaseException | None,
    label: str,
    missing_detail: str,
    invalid_detail: str,
    unpaired_detail: str | None = None,
) -> Failure:
    """Classify a persistent failure into a bounded repair or an escalation.

    A raised dispatcher process is the strongest signal; otherwise an absent
    file is an empty output, a present-but-rejected file is schema-invalid, and
    (for the diagnosis pairing) a valid-but-unpaired file is `unpaired`.
    Anything else escalates without repair (D28).
    """
    if error is not None:
        return Failure("dispatcher_process", "rerun", str(error))
    if state == "missing":
        return Failure("empty_file", "rerun", missing_detail)
    if state == "invalid":
        return Failure("schema_invalid", "rerun", invalid_detail)
    if state == "unpaired" and unpaired_detail is not None:
        return Failure("unpaired", "rerun", unpaired_detail)
    return Failure("unknown", None, f"{label} did not converge")


def load_trial_record(
    path: str | Path, *, files: FileStore, error: type[Exception]
) -> dict:
    """Read a trial record; a missing or non-mapping file is a loud error."""
    if not files.exists(path):
        raise error(f"trial record not found: {path}")
    try:
        payload = yaml.safe_load(files.read_text(path))
    except yaml.YAMLError as exc:
        raise error(f"trial record {path}: invalid YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise error(f"trial record {path}: expected a mapping")
    return payload
