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

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping, Sequence

import yaml

from orchestrator import subagents, trial, verdicts
from orchestrator.commands import Command
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

# The background launch's output sink, beside the node's destination file.
DISPATCH_LOG_SUFFIX = ".dispatch.log"


def dispatch_log_path(destination: str | Path) -> Path:
    """The log a background-launched assessment subagent writes to."""
    target = Path(destination)
    return target.with_name(target.name + DISPATCH_LOG_SUFFIX)


def _format_fields(request: AssessmentRequest) -> dict[str, str]:
    return subagents.common_fields(request)


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
    return subagents.render_command(
        argv,
        _format_fields(request),
        cwd=cwd,
        env=env,
        description=f"assess {request.trial_record}",
    )


class CommandDispatcher(subagents.CommandDispatcher):
    """The production seam: run the configured agent command line once."""

    error = AssessmentError

    def plan(self, request: AssessmentRequest) -> Command:
        command = plan_dispatch(request, self.argv, cwd=self.cwd, env=self.env)
        return replace(command, log_path=dispatch_log_path(request.destination))


def dispatch(
    request: AssessmentRequest,
    *,
    dispatcher: SubagentDispatcher,
    prior: Sequence[trial.AssessmentAttempt] = (),
    now: Callable[[], str] | None = None,
) -> trial.AssessmentRecord:
    """Fire-and-forget dispatch; return the recorded attempt (D6)."""
    return subagents.dispatch(
        request,
        dispatcher=dispatcher,
        prior=prior,
        now=now,
        make_attempt=trial.AssessmentAttempt,
        make_record=lambda status, attempts, path: trial.AssessmentRecord(
            status, attempts, path
        ),
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


# The persistent-failure classification (the shared cause/repair/detail shape).
AssessmentFailure = subagents.Failure


def classify_failure(*, verdict_state: str, error: BaseException | None) -> AssessmentFailure:
    """Classify a persistent failure into a bounded repair or an escalation.

    A raised dispatcher process is the strongest signal; otherwise an absent
    file is an empty output and a present-but-rejected file is schema-invalid.
    Anything else is unknown and escalates without repair (D28).
    """
    return subagents.classify_failure(
        state=verdict_state,
        error=error,
        label="assessment",
        missing_detail="no verdicts.yaml was produced",
        invalid_detail="verdicts.yaml failed schema validation",
    )


# The bounded, configuration-layer-only repair of D28 (the shared protocol).
AssessmentRepair = subagents.Repair


class ReDispatchRepair(subagents.ReDispatchRepair):
    """Re-run the configured command once with the corrected paths/flags.

    This is the only bounded repair (D28): it re-invokes the injected
    dispatcher, which the operator has configured with corrected paths or
    flags; it never touches the codebase.
    """

    def __init__(self, dispatcher: SubagentDispatcher, request: AssessmentRequest) -> None:
        super().__init__(dispatcher, request, repairable=REPAIRABLE, error=AssessmentError)


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
    now = now or subagents.utcnow
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
    kit = repair or subagents.NullRepair(AssessmentError)
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
    return subagents.load_trial_record(path, files=files, error=AssessmentError)


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
