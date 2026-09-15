"""Session-correlated Langfuse step records for the hunt-orchestrator turns (#135).

Convergence: actor turns ride the session seam under the handler, so no
hand-written gate span is opened here. What survives is the thin-exception
`trace_gate_step` step record for stretch data the handler never sees (the
symbolic render, gate decisions), fed EXPLICIT run correlation (never ambient
reads), plus the run-end flush.

Every helper fails open: an empty stack or a swallowed span. The orchestrator
stays unit-testable with no live Langfuse.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def trace_gate_step(name: str, *, input=None, output=None, run_id: str | None = None,
                    tags: list | None = None) -> None:
    """Attach a step of the orchestrator stretch as an observation.

    With explicit `run_id` the step opens under an explicit correlation context
    (convergence: no gate span exists to nest under); without it the legacy
    ambient nesting is kept."""
    try:
        from langfuse import get_client

        from polymerhus.app.observability.langfuse_tracing import explicit_correlation

        with explicit_correlation(run_id, tags=tags):
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