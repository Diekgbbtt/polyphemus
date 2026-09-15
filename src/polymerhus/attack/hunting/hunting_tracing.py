"""Session-correlated Langfuse step records for the hunting agent (#83).

Convergence: the hunt dispatch runs attributed session turns under the handler,
so no hand-written agent span is opened here. What survives is the
thin-exception `trace_span` step record for hunt data the handler never sees,
fed EXPLICIT run correlation (never ambient reads), plus the run-end flush.

  - `trace_span(name, ...)` == analyser `trace_generation`: attach a step
    (KB retrieval, spec composition, hunter step/tool) as an observation.
  - `flush_hunting_traces()`: flush pending spans at run end.

Every helper is fail-open: tracing is best-effort and must never fail - or
even perturb - an agent dispatch. When Langfuse is unavailable each degrades
to a no-op, so the agent stays unit-testable with no live Langfuse.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def trace_span(name: str, *, input=None, output=None, run_id: str | None = None,
               tags: list | None = None) -> None:
    """Persist a hunting-agent step as an observation.

    With explicit `run_id` the span opens under an explicit correlation context
    (convergence: no agent span exists to nest under); without it the legacy
    ambient nesting is kept. Fail-open (never raises / perturbs the dispatch);
    no-op when there is no active span. `input`/`output` must be
    JSON-serialisable."""
    try:
        from langfuse import get_client

        from polymerhus.app.observability.langfuse_tracing import explicit_correlation

        with explicit_correlation(run_id, tags=tags):
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