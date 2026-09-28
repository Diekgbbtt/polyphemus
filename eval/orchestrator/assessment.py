"""The background assessment and the eval-close verification phase (#271).

Dispatch is fire-and-forget (D6): the orchestrator hands the configured agent
command the prompt file, the trial record, the ground truth, the data root, and
the destination `verdicts.yaml`, then returns without polling. The agent writes
that file and nothing else; the prompt states the contract.

The eval-close phase (N16/D15) checks presence and schema for every trial,
re-dispatches at most twice, then micro-diagnoses a persistent failure: a
bounded configuration-layer repair (a re-dispatch with corrected paths/flags,
D28) or a named escalation. Every attempt is recorded on the trial record.

Every effect is injected - the `SubagentDispatcher` seam, the `FileStore`, the
clock - so the phase is exercised without a live agent. Import performs no I/O
(CODING_STANDARD section 6).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

import yaml

from orchestrator import trial, verdicts
from orchestrator.commands import Command, CommandRunner, require_ok
from orchestrator.files import FileStore

# `eval/orchestrator/assessment.py` -> `eval/prompts/assessment.md`.
ASSESSMENT_PROMPT = Path(__file__).parents[1] / "prompts" / "assessment.md"

# Two dispatches before the micro-diagnosis (D15: "re-dispatches twice").
MAX_DISPATCHES = 2
# The technical defects a bounded configuration-layer repair may address (D28).
REPAIRABLE = ("dispatcher_process", "empty_file", "schema_invalid")


class AssessmentError(RuntimeError):
    """The assessment dispatch or the close verification failed to converge."""


@dataclass(frozen=True)
class AssessmentRequest:
    """The inputs the assessment subagent receives (and writes into)."""

    prompt: Path
    trial_record: Path
    ground_truth: Path
    data_root: Path
    destination: Path
    trace_id: str | None = None


# The dispatch seam: run the configured agent command with the request. The
# real implementation runs the configured command line (OPERATOR.md); tests
# inject a fake.
SubagentDispatcher = Callable[[AssessmentRequest], None]


def _format_fields(request: AssessmentRequest) -> dict[str, str]:
    return {
        "prompt": str(request.prompt),
        "trial_record": str(request.trial_record),
        "ground_truth": str(request.ground_truth),
        "data_root": str(request.data_root),
        "destination": str(request.destination),
        "trace_id": request.trace_id or "",
    }


def plan_dispatch(
    request: AssessmentRequest,
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Command:
    """Render the configured agent command with the request's paths.

    The template names `{prompt}`, `{trial_record}`, `{ground_truth}`,
    `{data_root}`, `{destination}`, and `{trace_id}`.
    """
    fields = _format_fields(request)
    rendered = tuple(str(part).format(**fields) for part in argv)
    return Command(
        argv=rendered,
        cwd=cwd,
        env=env,
        description=f"assess {request.trial_record}",
    )


@dataclass
class CommandDispatcher:
    """The production seam: run the configured agent command line once."""

    runner: CommandRunner
    argv: tuple[str, ...]
    cwd: str | None = None
    env: Mapping[str, str] | None = None

    def __call__(self, request: AssessmentRequest) -> None:
        command = plan_dispatch(request, self.argv, cwd=self.cwd, env=self.env)
        require_ok(self.runner(command), command, error=AssessmentError)


def dispatch(
    request: AssessmentRequest,
    *,
    dispatcher: SubagentDispatcher,
    prior: Sequence[trial.AssessmentAttempt] = (),
    now: Callable[[], str] | None = None,
) -> trial.AssessmentRecord:
    """Fire-and-forget dispatch; return the recorded attempt (D6)."""
    now = now or _utcnow
    dispatcher(request)
    attempts = list(prior)
    attempts.append(
        trial.AssessmentAttempt(len(attempts) + 1, "dispatched", None, now())
    )
    return trial.AssessmentRecord(
        status="dispatched",
        attempts=attempts,
        verdicts_path=str(request.destination),
    )


def check_verdicts(
    request: AssessmentRequest,
    *,
    files: FileStore,
    eval_sha: str | None,
    stack_fingerprint: str | None,
) -> str:
    """`present`, `missing`, or `invalid` for the request's destination."""
    if not files.exists(request.destination):
        return "missing"
    try:
        verdicts.load_verdicts(
            request.destination,
            files=files,
            data_root=request.data_root,
            eval_sha=eval_sha,
            stack_fingerprint=stack_fingerprint,
        )
    except (verdicts.VerdictError, OSError):
        return "invalid"
    return "present"


@dataclass(frozen=True)
class AssessmentFailure:
    """The micro-diagnosis of a persistent assessment failure (D15/D28)."""

    cause: str
    repair: str | None
    detail: str


def classify_failure(*, verdict_state: str, error: BaseException | None) -> AssessmentFailure:
    """Classify a persistent failure into a bounded repair or an escalation.

    A raised dispatcher process is the strongest signal; otherwise an absent
    file is an empty output and a present-but-rejected file is schema-invalid.
    Anything else is unknown and escalates without repair (D28).
    """
    if error is not None:
        return AssessmentFailure("dispatcher_process", "rerun", str(error))
    if verdict_state == "missing":
        return AssessmentFailure("empty_file", "rerun", "no verdicts.yaml was produced")
    if verdict_state == "invalid":
        return AssessmentFailure(
            "schema_invalid", "rerun", "verdicts.yaml failed schema validation"
        )
    return AssessmentFailure("unknown", None, "assessment did not converge")


class AssessmentRepair(Protocol):
    """The bounded, configuration-layer-only repair of D28."""

    def supports(self, cause: str) -> bool: ...

    def apply(self, cause: str) -> None: ...


class _NullRepair:
    def supports(self, cause: str) -> bool:
        return False

    def apply(self, cause: str) -> None:  # pragma: no cover - never reached
        raise AssessmentError(f"no repair supports {cause!r}")


@dataclass
class ReDispatchRepair:
    """Re-run the configured command once with the corrected paths/flags.

    This is the only bounded repair (D28): it re-invokes the injected
    dispatcher, which the operator has configured with corrected paths or
    flags; it never touches the codebase.
    """

    dispatcher: SubagentDispatcher
    request: AssessmentRequest

    def supports(self, cause: str) -> bool:
        return cause in REPAIRABLE

    def apply(self, cause: str) -> None:
        self.dispatcher(self.request)


def verify_trial(
    request: AssessmentRequest,
    *,
    dispatcher: SubagentDispatcher,
    files: FileStore,
    eval_sha: str | None,
    stack_fingerprint: str | None,
    repair: AssessmentRepair | None = None,
    prior: Sequence[trial.AssessmentAttempt] = (),
    now: Callable[[], str] | None = None,
) -> trial.AssessmentRecord:
    """The eval-close check for one trial (presence, re-dispatch, micro-diagnosis)."""
    now = now or _utcnow
    attempts = list(prior)

    def attempt(outcome: str, detail: str | None) -> None:
        attempts.append(
            trial.AssessmentAttempt(len(attempts) + 1, outcome, detail, now())
        )

    def state() -> str:
        return check_verdicts(
            request,
            files=files,
            eval_sha=eval_sha,
            stack_fingerprint=stack_fingerprint,
        )

    if state() == "present":
        return trial.AssessmentRecord("present", attempts, str(request.destination), None)

    last_error: BaseException | None = None
    for _ in range(MAX_DISPATCHES):
        try:
            dispatcher(request)
            attempt("dispatched", None)
        except Exception as exc:  # noqa: BLE001 - the dispatcher outcome is arbitrary
            last_error = exc
            attempt("error", str(exc))
        if state() == "present":
            return trial.AssessmentRecord("present", attempts, str(request.destination), None)

    failure = classify_failure(verdict_state=state(), error=last_error)
    kit = repair or _NullRepair()
    if kit.supports(failure.cause):
        try:
            kit.apply(failure.cause)
            attempt("repaired", failure.detail)
            if state() == "present":
                return trial.AssessmentRecord(
                    "present", attempts, str(request.destination), None
                )
        except Exception as exc:  # noqa: BLE001 - a repair failure is itself a signal
            attempt("repair_error", str(exc))
    return trial.AssessmentRecord(
        "escalated", attempts, str(request.destination), f"assessment_{failure.cause}"
    )


# --- the trial record ----------------------------------------------------------


def load_trial_record(path: str | Path, *, files: FileStore) -> dict:
    """Read a trial record; a missing or non-mapping file is a loud error."""
    if not files.exists(path):
        raise AssessmentError(f"trial record not found: {path}")
    try:
        payload = yaml.safe_load(files.read_text(path))
    except yaml.YAMLError as exc:
        raise AssessmentError(f"trial record {path}: invalid YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise AssessmentError(f"trial record {path}: expected a mapping")
    return payload


def trial_identity(path: str | Path, *, files: FileStore) -> tuple[str, str]:
    """The eval SHA and stack fingerprint carried by the trial record.

    Refused loud when absent: a verdict's identity is never invented (D32).
    """
    payload = load_trial_record(path, files=files)
    sha = payload.get("eval_sha")
    fingerprint = payload.get("stack_fingerprint")
    if not sha:
        raise AssessmentError(f"trial record {path} carries no eval_sha")
    if not fingerprint:
        raise AssessmentError(f"trial record {path} carries no stack_fingerprint")
    return str(sha), str(fingerprint)


def record_assessment(
    trial_record_path: str | Path,
    record: trial.AssessmentRecord,
    *,
    files: FileStore,
) -> None:
    """Persist the assessment outcome, preserving the rest of the record."""
    payload = load_trial_record(trial_record_path, files=files)
    payload["assessment"] = record.to_dict()
    files.write_text_atomic(trial_record_path, yaml.safe_dump(payload, sort_keys=False))


def resolve_ground_truth(target: str) -> Path:
    """Resolve a challenge's ground-truth directory via `gt.py` (R2)."""
    import gt  # eval/ top-level helper; lazy so import time stays pure

    try:
        return gt.resolve_challenge_dir(target)
    except SystemExit as exc:
        raise AssessmentError(f"ground truth for {target!r} not found: {exc}") from exc


def _utcnow() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")
