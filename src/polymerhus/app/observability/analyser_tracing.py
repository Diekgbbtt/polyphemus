"""Session-correlated Langfuse spans for the analyser proposers (#18, #9).

The Bootstrapper (`analysis/bootstrap.py`) already traces its reasoning to Langfuse
under a named, session-correlated span. The A.1 proposers dispatched by the supervisor
(the Assigner, the mechanism-typist, the DataPlane data-modeller) invoke the analyser
model DIRECTLY inside their graph node, so their generations reached Langfuse only as
anonymous LLM runs under the run's LangGraph trace - with no per-agent span to group
them, no session correlation on that span, and no capture of an agent's free-text
reasoning. Observability is a core domain of this system, so that hole is closed here
by REPLICATING the bootstrapper pattern in ONE reusable place every proposer shares:

  - `analyser_span(role, ...)`  == bootstrap `_bootstrap_span`: `propagate_attributes`
    sets the TRACE-level name/session/tags (so the span joins the run's other traces by
    `session_id=run_id`), and `start_as_current_observation` opens the actual agent span
    that the generations - traced via the graph's inherited callbacks - and any
    `trace_reasoning` call nest UNDER.
  - `trace_reasoning(prose)`     == bootstrap `_trace_reasoning`: attach a proposer's
    free-text reason call to the current span (transient - inspectable in the trace,
    never persisted to the graph).
  - `flush_analyser_traces()`    == bootstrap `_flush_traces`.

EVERY helper is fail-open (mirroring bootstrap.py): tracing is best-effort and must
never fail - or even perturb - a proposer. When Langfuse is unavailable (package not
installed, env unset, init failed) each degrades to a no-op / `nullcontext`, so the
proposers stay unit-testable with no live Langfuse.
"""
from __future__ import annotations

import logging
from contextlib import nullcontext

logger = logging.getLogger(__name__)


def analyser_span(role: str, *, project_id: str, run_id: str, phase: str | None = None,
                  dispatch_id: str | None = None):
    """The one span per proposer dispatch, session-correlated to its run.

    Mirrors bootstrap `_bootstrap_span`: `propagate_attributes` alone creates NO
    observation (every `update_current_span` under it would silently no-op), so
    `start_as_current_observation` opens the span the generations and `trace_reasoning`
    attach to. Returns a context manager; degrades to `nullcontext()` when tracing is
    unavailable, so callers wrap unconditionally."""
    try:
        from contextlib import ExitStack

        from langfuse import get_client, propagate_attributes

        metadata = {"project_id": project_id}
        if phase:
            metadata["phase"] = phase
        if dispatch_id:
            metadata["dispatch_id"] = dispatch_id

        stack = ExitStack()
        stack.enter_context(propagate_attributes(
            trace_name=f"analyser-{role}",
            session_id=run_id,
            tags=["analysis", role],
            metadata=metadata,
        ))
        stack.enter_context(get_client().start_as_current_observation(
            name=f"analyser-{role}", as_type="agent",
            input={"project_id": project_id, "phase": phase},
        ))
        return stack
    except Exception:  # tracing unavailable / misconfigured -> proposer runs untraced
        logger.debug("analyser_span unavailable for role=%s; running untraced", role, exc_info=True)
        return nullcontext()


def trace_reasoning(prose: str, *, call: str = "reason") -> None:
    """Attach a proposer's free-text reasoning to the current span (transient).

    The mechanism-typist's reflection prose is built, consumed by its extraction call,
    and otherwise discarded - so without this the WHY behind a System proposal leaves no
    inspectable record. No-op (never raises) when there is no active span."""
    if not prose:
        return
    try:
        from langfuse import get_client

        get_client().update_current_span(input={"call": call}, output=prose)
    except Exception:
        logger.debug("trace_reasoning could not attach %r reasoning", call, exc_info=True)


def flush_analyser_traces() -> None:
    """Flush pending spans (a run worker may exit before the background exporter fires).
    `flush`, never `shutdown` - the client is a process-wide singleton later runs reuse."""
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:
        logger.debug("flush_analyser_traces failed", exc_info=True)
