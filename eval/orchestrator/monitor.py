"""The eval orchestrator's tick-based control plane (#289).

The orchestrator workflow (`eval/prompts/orchestrator.md`) advances every trial
through three nodes in order: execution, assessment, diagnosis. The symbolic
`orchestrator trial` performs execution and writes `trial.yaml`; this module is
the control plane that one tick executes afterwards. It verifies each trial's
execution state and drives the next node: a successful execution dispatches the
assessment subagent, a present `verdicts.yaml` dispatches the diagnoser for
every `missed`/`partial` verdict, and a present, paired `diagnoses.yaml`
completes the trial.

The pure decision (`decide`) is separated from every effect (reading records,
checking files, dispatching subagents), so the state machine is exercised
without a live agent. The decision reuses the assessment/diagnosis vocabulary:
the same `MAX_DISPATCHES` bound, the same named failure causes, and the same
trial-record attempt history the close verification writes. Since #350 the
dispatch itself is an awaited native opencode child session and the plugin runs
the assessment and the diagnosis synchronously; after a subagent dies on the
provider's own quota/rate limit the node backs off for `provider_backoff_s`
instead of hot-looping the exhausted window.

Import performs no I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from orchestrator.subagents import PROVIDER_OUTCOME

# The execution terminals that count as a successful run: the phases finished
# and produced evidence. `failed`, `timeout`, and `blocked` are not successful;
# a failed run is never assessed (the surfer loop owns recovery).
SUCCESS_TERMINALS = frozenset({"complete", "stopped"})

# A provider-paused execution (#331): the run stopped with the resumable
# terminal `interrupted` and its cause is recorded on the trial record's phase
# failure (`stats.interrupt_reason` + `provider_status` + `quota_exhausted` +
# `retry_after_s`). It is DEFERRED like a failure - the surfer loop owns
# recovery, never the assessment - and it is NEVER escalated: the decision to
# resume is derivable from the stamped attributes alone
# (`docs/design/331-stop-only-resume-assessment-adr.md`).
INTERRUPTED_TERMINAL = "interrupted"

# The two dispatched nodes, after execution.
NODE_ASSESSMENT = "assessment"
NODE_DIAGNOSIS = "diagnosis"

# The per-node next action.
DISPATCH = "dispatch"
AWAIT = "await"
ESCALATE = "escalate"

# The tick states a trial is reported in.
STATE_DEFERRED = "deferred"
STATE_ASSESSMENT_DISPATCHED = "assessment_dispatched"
STATE_AWAITING_ASSESSMENT = "awaiting_assessment"
STATE_DIAGNOSIS_DISPATCHED = "diagnosis_dispatched"
STATE_AWAITING_DIAGNOSIS = "awaiting_diagnosis"
STATE_COMPLETE = "complete"
STATE_ESCALATED = "escalated"

# Mirrors #271/#272: two dispatches before a node escalates.
MAX_DISPATCHES = 2
# The wait between a dispatch and the re-dispatch/escalation decision, seconds.
DEFAULT_BUDGET_S = 3600.0
# The far longer wait after a subagent died on the provider's own quota/rate
# limit (#350). Re-dispatching into an exhausted window only burns the window's
# recovery; the node stays `awaiting` until the provider backoff elapses.
DEFAULT_PROVIDER_BACKOFF_S = 18000.0

# The node output states `check_verdicts`/`check_diagnoses` return.
_PRESENT = "present"


@dataclass(frozen=True)
class AttemptView:
    """One recorded dispatch/verification attempt of a node (its `at` is ISO)."""

    at: str | None = None
    outcome: str | None = None


@dataclass(frozen=True)
class NodeView:
    """What one tick knows about one node of one trial.

    `state` is the output state (`present`, `missing`, `invalid`, `unpaired`).
    `status` is the trial record's recorded node status (`dispatched`,
    `present`, `escalated`, or None when the node was never reached).
    `attempts` is the append-only history the node wrote.
    """

    state: str
    status: str | None = None
    attempts: tuple[AttemptView, ...] = ()


@dataclass(frozen=True)
class TrialView:
    """What one tick knows about one trial."""

    trial_dir: Path
    target_id: str
    terminal: str
    assessment: NodeView
    # None when every verdict is `identified`: no diagnosis is required.
    diagnosis: NodeView | None = None


@dataclass(frozen=True)
class TrialDecision:
    """The next action for one trial, plus the state to report it in."""

    trial_dir: Path
    target_id: str
    terminal: str
    node: str
    state: str
    action: str | None
    cause: str | None = None
    detail: str | None = None


@dataclass(frozen=True)
class _Step:
    state: str
    action: str | None
    cause: str | None = None
    detail: str | None = None


def decide(
    view: TrialView,
    *,
    now: str,
    budget_s: float = DEFAULT_BUDGET_S,
    provider_backoff_s: float = DEFAULT_PROVIDER_BACKOFF_S,
) -> TrialDecision:
    """The pure per-trial tick decision (one node advanced at most).

    A successful execution moves to the assessment node; an assessment that is
    present and valid moves to the diagnosis node (or completes, when no
    diagnosis is required); a present, paired diagnosis completes the trial.
    A node whose output is absent is dispatched once, then awaited, then
    re-dispatched up to `MAX_DISPATCHES` and finally escalated with a named
    cause; after a provider-quota death it is awaited for `provider_backoff_s`
    instead of `budget_s`, so an exhausted window is never hot-looped. A
    non-successful execution is `deferred` and never advanced; an `interrupted`
    execution (a provider-paused run, #331) is deferred too and is NEVER
    escalated - its resumable decision rides the recorded cause.
    """
    if view.terminal == INTERRUPTED_TERMINAL:
        return TrialDecision(
            trial_dir=view.trial_dir,
            target_id=view.target_id,
            terminal=view.terminal,
            node=NODE_ASSESSMENT,
            state=STATE_DEFERRED,
            action=None,
            detail=(
                "execution terminal 'interrupted' is a resumable provider pause; "
                "the surfer owns recovery and the recorded reason is on the trial "
                "record"
            ),
        )
    if view.terminal not in SUCCESS_TERMINALS:
        return TrialDecision(
            trial_dir=view.trial_dir,
            target_id=view.target_id,
            terminal=view.terminal,
            node=NODE_ASSESSMENT,
            state=STATE_DEFERRED,
            action=None,
            detail=f"execution terminal {view.terminal!r} is not a success",
        )

    step = _node_step(
        view.assessment,
        label="assessment",
        now=now,
        budget_s=budget_s,
        provider_backoff_s=provider_backoff_s,
    )
    if step.action == DISPATCH:
        return _decision(view, NODE_ASSESSMENT, STATE_ASSESSMENT_DISPATCHED, step)
    if step.action == AWAIT:
        return _decision(view, NODE_ASSESSMENT, STATE_AWAITING_ASSESSMENT, step)
    if step.action == ESCALATE:
        return _decision(view, NODE_ASSESSMENT, STATE_ESCALATED, step)

    # The assessment output is present and valid.
    if view.diagnosis is None:
        return _decision(view, NODE_ASSESSMENT, STATE_COMPLETE, step)

    diag = _node_step(
        view.diagnosis,
        label="diagnosis",
        now=now,
        budget_s=budget_s,
        provider_backoff_s=provider_backoff_s,
    )
    if diag.action == DISPATCH:
        return _decision(view, NODE_DIAGNOSIS, STATE_DIAGNOSIS_DISPATCHED, diag)
    if diag.action == AWAIT:
        return _decision(view, NODE_DIAGNOSIS, STATE_AWAITING_DIAGNOSIS, diag)
    if diag.action == ESCALATE:
        return _decision(view, NODE_DIAGNOSIS, STATE_ESCALATED, diag)
    return _decision(view, NODE_DIAGNOSIS, STATE_COMPLETE, diag)


def _decision(
    view: TrialView, node: str, state: str, step: _Step
) -> TrialDecision:
    return TrialDecision(
        trial_dir=view.trial_dir,
        target_id=view.target_id,
        terminal=view.terminal,
        node=node,
        state=state,
        action=step.action,
        cause=step.cause,
        detail=step.detail,
    )


def _node_step(
    node: NodeView,
    *,
    label: str,
    now: str,
    budget_s: float,
    provider_backoff_s: float,
) -> _Step:
    """The next action for one node from its view (the pure decision)."""
    if node.state == _PRESENT:
        return _Step(_PRESENT, None)
    if node.status == STATE_ESCALATED:
        return _Step(
            STATE_ESCALATED, ESCALATE, cause=None, detail=f"{label} already escalated"
        )
    attempts = list(node.attempts)
    if not attempts:
        return _Step("missing", DISPATCH, detail=f"first {label} dispatch")
    last = attempts[-1]
    if last.outcome == PROVIDER_OUTCOME:
        # The dispatch count is exhausted: surface it now rather than wait out a
        # provider window that will not add another attempt.
        if len(attempts) >= MAX_DISPATCHES:
            cause = _cause(node, label=label)
            return _Step(
                STATE_ESCALATED,
                ESCALATE,
                cause=cause,
                detail=f"{label} did not converge after {len(attempts)} dispatches",
            )
        if _elapsed(last.at, now) < provider_backoff_s:
            return _Step(
                "missing",
                AWAIT,
                detail=(
                    f"{label} backed off after a provider-quota death "
                    f"({provider_backoff_s:.0f}s window)"
                ),
            )
        return _Step(
            "missing", DISPATCH, detail=f"re-dispatch {label} after provider backoff"
        )
    if _elapsed(last.at, now) < budget_s:
        return _Step("missing", AWAIT, detail=f"{label} awaiting its output")
    if len(attempts) >= MAX_DISPATCHES:
        cause = _cause(node, label=label)
        return _Step(
            STATE_ESCALATED,
            ESCALATE,
            cause=cause,
            detail=f"{label} did not converge after {len(attempts)} dispatches",
        )
    return _Step("missing", DISPATCH, detail=f"re-dispatch {label}")


def _cause(node: NodeView, *, label: str) -> str:
    """The named failure cause for an exhausted node (the close-verify vocabulary)."""
    last = node.attempts[-1] if node.attempts else None
    if last is not None and last.outcome in ("error", "timeout", PROVIDER_OUTCOME):
        return "dispatcher_process"
    if node.state == "invalid":
        return "schema_invalid"
    if node.state == "unpaired":
        return "unpaired"
    return "empty_file"


def _elapsed(at: str | None, now: str) -> float:
    """Seconds between an attempt's ISO timestamp and the tick clock.

    A missing or unparseable timestamp is treated as infinitely old, so a node
    with an unreadable history reaches its budget decision rather than stalling.
    """
    if not at:
        return float("inf")
    try:
        started = datetime.fromisoformat(at)
        current = datetime.fromisoformat(now)
    except ValueError:
        return float("inf")
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return (current - started).total_seconds()
