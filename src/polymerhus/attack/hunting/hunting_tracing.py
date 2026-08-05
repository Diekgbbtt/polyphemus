"""Session-correlated Langfuse spans for the hunting agent (#83).

Mirrors `analyser_tracing.py` exactly as the shared observability recipe
(merged spec section 8, implementation doc section 5.4): ONE trace per
spec-authoring turn, session = run id, Langfuse optional and fail-open.

  - `hunting_span(run_id, hunt_id)`  == analyser `analyser_span`: the
    `propagate_attributes` sets the TRACE-level name/session/tags (so the span
    joins the run's other traces by `session_id=run_id`) and
    `start_as_current_observation` opens the agent span that the step spans and
    any LLM generations - traced via `build_chat_model`'s inherited
    `get_langfuse_callbacks()` - nest UNDER.
  - `trace_span(name, input, output)` == analyser `trace_generation`: attach a
    step (KB retrieval, spec composition) as a nested child observation.
  - `flush_hunting_traces()`          == analyser `flush_analyser_traces`.

Every helper is fail-open (mirroring bootstrap.py): tracing is best-effort and
must never fail - or even perturb - an agent dispatch. When Langfuse is
unavailable each degrades to a no-op (an empty `ExitStack` / a swallowed span),
so the agent stays unit-testable with no live Langfuse.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def hunting_span(run_id: str, hunt_id: str):
    """The one span per hunting-agent dispatch, session-correlated to its run.

    `propagate_attributes` alone creates NO observation (every
    `update_current_span` under it would silently no-op), so
    `start_as_current_observation` opens the span the step spans attach to.
    Returns a context manager; an empty stack when tracing is unavailable (an
    empty `ExitStack` IS the null context), so callers wrap unconditionally."""
    from contextlib import ExitStack

    stack = ExitStack()
    try:
        from langfuse import get_client, propagate_attributes

        stack.enter_context(propagate_attributes(
            trace_name=f"hunting-agent-{hunt_id[:8]}",
            session_id=run_id,
            tags=["attack", "hunting", "hunting-agent"],
            metadata={"hunt_id": hunt_id},
        ))
        stack.enter_context(get_client().start_as_current_observation(
            name=f"hunting-agent-{hunt_id[:8]}", as_type="agent",
            input={"hunt_id": hunt_id},
        ))
    except Exception:  # tracing unavailable / misconfigured -> agent runs untraced
        logger.debug("hunting_span unavailable for hunt=%s; running untraced", hunt_id, exc_info=True)
    return stack


def trace_span(name: str, *, input=None, output=None) -> None:
    """Persist a hunting-agent step (KB retrieval, spec composition) as a child
    observation under the current agent span. Fail-open (never raises /
    perturbs the dispatch); no-op when there is no active span. `input`/`output`
    must be JSON-serialisable."""
    try:
        from langfuse import get_client

        with get_client().start_as_current_observation(
            name=name, as_type="span", input=input,
        ) as span:
            span.update(output=output)
    except Exception:
        logger.debug("trace_span could not record %r", name, exc_info=True)


def flush_hunting_traces() -> None:
    """Flush pending spans (a run worker may exit before the background exporter
    fires). `flush`, never `shutdown` - the client is a process-wide singleton
    later runs reuse."""
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:
        logger.debug("flush_hunting_traces failed", exc_info=True)