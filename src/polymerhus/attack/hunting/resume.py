"""The run-resume decision table and the operator-verb policy (T11 #398).

`docs/design/331-stop-only-resume-assessment-adr.md` section 3 fixes the
decision table: it reads ONLY the run row's status and stamped `stats`, never a
free-form error message. `resume_decision` is its ONE pure implementation - no
clock read, no I/O - so every row is testable and repeatable.

The OPERATOR VERB (the ratified floor) is the only trigger built here. It
enforces the wait window: an `interrupted` transient throttle resumes after
`retry_after_s`, or after `DEFAULT_RESUME_BACKOFF_S` when the hint is null. It
has no force flag: a force would invent an unratified interface, so the operator
retries after the window.

The AUTO-RESUME health checker the operator chose (D-3) is a FOLLOW-UP, not
built here: this module exposes the decision and nothing schedules it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

# The default backoff when a resumable transient throttle carries no
# `retry_after_s` (#331 leaves the value open). 60s is one per-minute provider
# window - the shortest window the ADR names for a transient 429 - so a resume
# never lands inside the throttle it is recovering from, while a transient
# outage still recovers within a minute. It is applied by the operator verb;
# the future auto-resume checker uses the same constant.
DEFAULT_RESUME_BACKOFF_S = 60.0

# The keys the resume claim removes from the run row's `stats`, and the keys an
# admission-refusal restore re-stamps: the provider pause and its
# machine-readable class. A resumed row must not advertise a pause, and a later
# crash + reconcile must not inherit the pre-resume class (otherwise the stale
# `quota_exhausted=false` would make the orphan look resumable).
PAUSE_STATS_KEYS: tuple[str, ...] = (
    "interrupted",
    "interrupt_reason",
    "provider_status",
    "quota_exhausted",
    "retry_after_s",
)

# The decision codes that mean an `interrupted` run will NEVER resume: the
# table's terminal and do-not-resume rows. `backoff_window` is deliberately NOT
# here - the throttle resumes once the window elapses, so its produced model
# stays in flight. The intake freeze consumes this classification (T11 review).
TERMINAL_INTERRUPT_CODES: frozenset[str] = frozenset({
    "quota_exhausted", "cause_unknown", "timing_unknown",
})


@dataclass(frozen=True)
class ResumeDecision:
    """One decision-table row's outcome.

    `code` is the stable row identifier (`stopped`, `throttled`,
    `backoff_window`, `quota_exhausted`, `cause_unknown`, `timing_unknown`,
    `already_running`, `complete`, `failed`, `unknown_status`); `reason` is the
    operator-facing one-liner. `retry_after_s` / `not_before` / `wait_s` are set
    only for a transient throttle (the wait window).
    """

    resumable: bool
    code: str
    reason: str
    retry_after_s: float | None = None
    not_before: datetime | None = None
    wait_s: float | None = None


def resume_decision(
    status: str,
    stats: Mapping[str, Any] | None,
    finished_at: datetime | None,
    *,
    now: datetime,
    default_backoff_s: float = DEFAULT_RESUME_BACKOFF_S,
) -> ResumeDecision:
    """The PURE decision table (ADR 331 section 3).

    `now` is injected (never read inside), so the same inputs yield the same
    decision in any process. Every status the discriminator can take is decided;
    an unknown status fails closed.

    - `stopped` -> resumable immediately.
    - `interrupted` and `stats.quota_exhausted is False` -> resumable after
      `retry_after_s` seconds, or `default_backoff_s` when the hint is null.
      A malformed hint (negative, non-finite, non-numeric) falls back to the
      default, never to zero: a bad hint must never mean "resume now".
    - `interrupted` and `stats.quota_exhausted is True` -> terminal (the
      provider will not serve until the period resets).
    - `interrupted` with missing/unknown stats -> do-not-resume (fail-closed).
      This is the process-restart orphan disposition: the startup reconcile
      stamps `interrupted` with a restart reason and no provider class, so the
      operator verb never guesses and never resumes it.
    - `running` -> already live.
    - `complete` / `failed` -> terminal.
    """
    if status == "stopped":
        return ResumeDecision(
            resumable=True,
            code="stopped",
            reason=(
                "the run was stopped by the operator; it resumes immediately"
            ),
        )
    if status == "running":
        return ResumeDecision(
            resumable=False,
            code="already_running",
            reason="the run is already running (already live)",
        )
    if status in ("complete", "failed"):
        return ResumeDecision(
            resumable=False,
            code=status,
            reason=(
                f"the run is already {status}; it is terminal and is not "
                f"resumable"
            ),
        )
    if status == "interrupted":
        stamped = stats if isinstance(stats, Mapping) else None
        if not stamped:
            return ResumeDecision(
                resumable=False,
                code="cause_unknown",
                reason=(
                    "the run is interrupted but carries no cause record; "
                    "do-not-resume (fail-closed)"
                ),
            )
        quota_exhausted = stamped.get("quota_exhausted")
        if quota_exhausted is True:
            return ResumeDecision(
                resumable=False,
                code="quota_exhausted",
                reason=(
                    "the provider period quota is exhausted; the run is "
                    "terminal and is not resumed"
                ),
            )
        if quota_exhausted is not False:
            return ResumeDecision(
                resumable=False,
                code="cause_unknown",
                reason=(
                    "the run's interrupt cause does not establish "
                    "quota_exhausted=false; do-not-resume (fail-closed)"
                ),
            )
        if finished_at is None:
            return ResumeDecision(
                resumable=False,
                code="timing_unknown",
                reason=(
                    "the interrupted run carries no finished_at to anchor its "
                    "resume window; do-not-resume (fail-closed)"
                ),
            )
        retry_after_s = _retry_after_s(stamped.get("retry_after_s"),
                                       default_backoff_s)
        not_before = _as_utc(finished_at) + timedelta(seconds=retry_after_s)
        current = _as_utc(now)
        if current < not_before:
            wait_s = (not_before - current).total_seconds()
            return ResumeDecision(
                resumable=False,
                code="backoff_window",
                reason=(
                    f"the run is inside its provider backoff window; retry in "
                    f"{wait_s:.0f}s (not before {not_before.isoformat()})"
                ),
                retry_after_s=retry_after_s,
                not_before=not_before,
                wait_s=wait_s,
            )
        return ResumeDecision(
            resumable=True,
            code="throttled",
            reason=(
                f"the run paused on a transient provider throttle; the "
                f"{retry_after_s:.0f}s backoff elapsed"
            ),
            retry_after_s=retry_after_s,
            not_before=not_before,
        )
    return ResumeDecision(
        resumable=False,
        code="unknown_status",
        reason=f"unknown run status {status!r}; do-not-resume (fail-closed)",
    )


def _retry_after_s(value: Any, default_backoff_s: float) -> float:
    """The wait before a resumable throttle may re-enter.

    A null hint takes `default_backoff_s`; a finite, non-negative number is the
    hint itself; anything else (a negative, a non-finite, a string, a bool)
    falls back to the default. A malformed hint must never mean "resume now",
    and it must not wedge the run behind a value it can never satisfy."""
    import math

    if value is None:
        return float(default_backoff_s)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return float(default_backoff_s)
    delay = float(value)
    if not math.isfinite(delay) or delay < 0:
        return float(default_backoff_s)
    return delay


def _as_utc(value: datetime) -> datetime:
    """A datetime comparable with `now`: a NAIVE value (a test fixture, or a
    driver that dropped the timezone) is read as UTC, the run row's convention."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
