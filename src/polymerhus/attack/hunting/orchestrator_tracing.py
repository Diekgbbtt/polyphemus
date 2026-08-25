"""Session-correlated Langfuse spans for the hunt-orchestrator actor turns (#135).

Mirrors `hunting_tracing.py` as the shared observability recipe: ONE span per
orchestrator turn, session = run id, Langfuse optional and fail-open.

- `orchestrator_gate_span(run_id)` = `hunting_tracing.hunting_span`: the span
  context `arun_orchestration` enters per pass so the whole gate/re-match
  stretch nests under `orchestrator-<run_id[:8]>`. `propagate_attributes`
  ties it to the run's session; `start_as_current_observation` opens the
  span the step spans and LLM generations nest under.
- `trace_gate_step(name, *, input=, output=)` = `trace_span`: an observed step
  of the stretch.
- `flush_orchestrator_traces()` = `flush_hunting_traces`.

Every helper fails open exactly like bootstrap-lite: an empty stack or a
swallowed span. The orchestrator stays unit-testable with no live Langfuse.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def orchestrator_gate_span(run_id: str):
    """One span per orchestrator turn, session-correlated to the run."""
    from contextlib import ExitStack

    stack = ExitStack()
    try:
        from langfuse import get_client, propagate_attributes

        name = f"orchestrator-{run_id[:8]}"
        stack.enter_context(propagate_attributes(
            session_id=run_id, tags=["attack", "hunting", "orchestrator-gate"]))
        stack.enter_context(
            get_client().start_as_current_observation(
                name=name, as_type="agent", input={"run_id": run_id}))
    except Exception:  # noqa: BLE001 - tracing must never fail the turn
        logger.debug("orchestrator_gate_span unavailable for %s; untraced",
                     run_id, exc_info=True)
    return stack


def trace_gate_step(name: str, *, input=None, output=None) -> None:
    """Attach a step of the orchestrator stretch as a nested child span."""
    try:
        from langfuse import get_client

        with get_client().start_as_current_observation(
                name=name, as_type="span", input=input) as span:
            span.update(output=output)
    except Exception:  # noqa: BLE001
        logger.debug("trace_gate_step could not record %r", name, exc_info=True)


def flush_orchestrator_traces() -> None:
    """Flush the current client's pending observations."""
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:  # noqa: BLE001
        logger.debug("flush_orchestrator_traces failed", exc_info=True)