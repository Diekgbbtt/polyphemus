"""The eval orchestrator tick control plane (#289).

The tick verifies each trial's execution state and advances one workflow node:
a successful execution dispatches the assessment subagent, a present
`verdicts.yaml` dispatches the diagnoser for the `missed`/`partial` verdicts,
and a present, paired `diagnoses.yaml` completes the trial. A failed or
blocked execution is `deferred` (the surfer owns recovery) and never assessed.
A node whose output is absent is dispatched once, awaited, re-dispatched up to
the bound, then escalated with a named cause - the same vocabulary the close
verification writes.
"""
from __future__ import annotations

from pathlib import Path

from orchestrator import monitor

NOW = "2026-10-01T12:00:00+00:00"
RECENT = "2026-10-01T11:59:00+00:00"  # one minute ago
OLD = "2026-10-01T09:00:00+00:00"  # three hours ago
BUDGET_S = 3600.0
TRIAL_DIR = Path("/runs/comfyui-1/trial-1")


def attempt(at: str, outcome: str = "dispatched") -> monitor.AttemptView:
    return monitor.AttemptView(at=at, outcome=outcome)


def view(
    *,
    terminal: str = "complete",
    a_state: str = "missing",
    a_status: str | None = None,
    a_attempts: tuple = (),
    d_state: str | None = None,
    d_status: str | None = None,
    d_attempts: tuple = (),
) -> monitor.TrialView:
    assessment = monitor.NodeView(
        state=a_state, status=a_status, attempts=tuple(a_attempts)
    )
    diagnosis = (
        None
        if d_state is None
        else monitor.NodeView(state=d_state, status=d_status, attempts=tuple(d_attempts))
    )
    return monitor.TrialView(
        trial_dir=TRIAL_DIR,
        target_id="comfyui-1",
        terminal=terminal,
        assessment=assessment,
        diagnosis=diagnosis,
    )


def decide(v: monitor.TrialView) -> monitor.TrialDecision:
    return monitor.decide(v, now=NOW, budget_s=BUDGET_S)


# --- the execution gate --------------------------------------------------------


def test_failed_execution_is_deferred_and_never_dispatched():
    d = decide(view(terminal="failed"))
    assert d.state == monitor.STATE_DEFERRED
    assert d.action is None
    assert "failed" in d.detail


def test_blocked_and_timeout_are_deferred():
    assert decide(view(terminal="blocked")).state == monitor.STATE_DEFERRED
    assert decide(view(terminal="timeout")).state == monitor.STATE_DEFERRED


def test_interrupted_execution_is_deferred_never_escalated():
    """#331: a provider-paused run lands the resumable terminal `interrupted`.
    The monitor must DEFER it to the surfer - never escalate it, never dispatch
    the assessment - and the recorded reason stays on the trial record so the
    resume decision is repeatable."""
    d = decide(view(terminal="interrupted"))
    assert d.state == monitor.STATE_DEFERRED
    assert d.action is None
    assert d.node == monitor.NODE_ASSESSMENT
    assert "interrupted" in d.detail
    assert "resumable" in d.detail


def test_capped_hunting_stop_is_a_success():
    assert decide(view(terminal="stopped")).state == monitor.STATE_ASSESSMENT_DISPATCHED


# --- the assessment node -------------------------------------------------------


def test_first_tick_dispatches_the_assessment():
    d = decide(view())
    assert d.node == monitor.NODE_ASSESSMENT
    assert d.state == monitor.STATE_ASSESSMENT_DISPATCHED
    assert d.action == monitor.DISPATCH


def test_a_recent_dispatch_is_awaited_not_resent():
    d = decide(view(a_attempts=(attempt(RECENT),)))
    assert d.state == monitor.STATE_AWAITING_ASSESSMENT
    assert d.action == monitor.AWAIT


def test_an_old_dispatch_is_resent_within_the_bound():
    d = decide(view(a_attempts=(attempt(OLD),)))
    assert d.state == monitor.STATE_ASSESSMENT_DISPATCHED
    assert d.action == monitor.DISPATCH


def test_an_exhausted_assessment_escalates_with_a_named_cause():
    d = decide(view(a_state="missing", a_attempts=(attempt(OLD), attempt(OLD))))
    assert d.state == monitor.STATE_ESCALATED
    assert d.action == monitor.ESCALATE
    assert d.cause == "empty_file"


def test_an_invalid_assessment_escalates_schema_invalid():
    d = decide(view(a_state="invalid", a_attempts=(attempt(OLD), attempt(OLD))))
    assert d.cause == "schema_invalid"


def test_a_raised_dispatcher_escalates_dispatcher_process():
    d = decide(
        view(
            a_state="missing",
            a_attempts=(attempt(OLD), attempt(OLD, outcome="error")),
        )
    )
    assert d.cause == "dispatcher_process"


def test_an_already_escalated_node_stays_escalated():
    d = decide(view(a_status=monitor.STATE_ESCALATED, a_attempts=(attempt(OLD),)))
    assert d.state == monitor.STATE_ESCALATED
    assert d.action == monitor.ESCALATE


# --- the provider-quota backoff (#350) -----------------------------------------


def test_a_provider_death_is_awaited_past_the_normal_budget():
    # OLD is three hours ago: past the 1h budget, but well inside the 5h
    # provider backoff, so the node must NOT re-dispatch into a dead window.
    d = decide(view(a_attempts=(attempt(OLD, outcome=monitor.PROVIDER_OUTCOME),)))
    assert d.state == monitor.STATE_AWAITING_ASSESSMENT
    assert d.action == monitor.AWAIT
    assert "provider-quota" in d.detail


def test_a_provider_backoff_expires_then_re_dispatches():
    long_ago = "2026-10-01T00:00:00+00:00"  # 12h before NOW, past the backoff
    d = decide(view(a_attempts=(attempt(long_ago, outcome=monitor.PROVIDER_OUTCOME),)))
    assert d.state == monitor.STATE_ASSESSMENT_DISPATCHED
    assert d.action == monitor.DISPATCH


def test_an_exhausted_provider_node_escalates_dispatcher_process():
    d = decide(
        view(
            a_state="missing",
            a_attempts=(
                attempt("2026-10-01T00:00:00+00:00", outcome=monitor.PROVIDER_OUTCOME),
                attempt("2026-10-01T00:00:00+00:00", outcome=monitor.PROVIDER_OUTCOME),
            ),
        )
    )
    assert d.state == monitor.STATE_ESCALATED
    assert d.cause == "dispatcher_process"


# --- the diagnosis node --------------------------------------------------------


def test_present_verdicts_with_no_diagnosis_required_complete():
    d = decide(view(a_state="present", d_state=None))
    assert d.state == monitor.STATE_COMPLETE
    assert d.action is None


def test_present_verdicts_with_required_diagnosis_dispatches_it():
    d = decide(view(a_state="present", d_state="missing"))
    assert d.node == monitor.NODE_DIAGNOSIS
    assert d.state == monitor.STATE_DIAGNOSIS_DISPATCHED
    assert d.action == monitor.DISPATCH


def test_a_recent_diagnosis_dispatch_is_awaited():
    d = decide(view(a_state="present", d_state="missing", d_attempts=(attempt(RECENT),)))
    assert d.state == monitor.STATE_AWAITING_DIAGNOSIS
    assert d.action == monitor.AWAIT


def test_a_paired_diagnosis_completes():
    d = decide(view(a_state="present", d_state="present"))
    assert d.state == monitor.STATE_COMPLETE


def test_an_unpaired_diagnosis_escalates_after_the_bound():
    d = decide(
        view(
            a_state="present",
            d_state="unpaired",
            d_attempts=(attempt(OLD), attempt(OLD)),
        )
    )
    assert d.cause == "unpaired"


def test_a_fresh_assessment_is_not_re_dispatched_while_diagnosis_required():
    # The assessment node is present: the tick must never send it again.
    d = decide(view(a_state="present", d_state="missing"))
    assert d.node == monitor.NODE_DIAGNOSIS
