"""Session-correlated Langfuse step records for the analyser proposers (#18, #9).

Convergence: proposer dispatches run UNDER the run-sessioned supervisor graph,
whose chain spans plus the run tag carry structure and join - so no hand-written
agent span is opened here. What survives are the thin-exception step records for
proposer data the handler never sees (free-text reasoning, structured generations),
each fed EXPLICIT run correlation (never ambient reads).

  - `trace_reasoning(prose, ...)` : attach a proposer's free-text reason call.
  - `trace_generation(call, ...)`  : persist a proposer's structured generation.
  - `flush_analyser_traces()`      : flush pending spans at run end.

EVERY helper is fail-open: tracing is best-effort and must never fail - or even
perturb - a proposer. When Langfuse is unavailable (package not installed, env
unset, init failed) each degrades to a no-op, so the proposers stay unit-testable
with no live Langfuse.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def trace_reasoning(prose: str, *, call: str = "reason", run_id: str | None = None,
                    tags: list | None = None) -> None:
    """Attach a proposer's free-text reasoning (transient).

    The mechanism-typist's reflection prose is built, consumed by its extraction call,
    and otherwise discarded - so without this the WHY behind a System proposal leaves no
    inspectable record. With explicit `run_id` (convergence: no agent span exists to
    attach to) the prose opens its OWN span under an explicit correlation context;
    without it the call keeps the legacy ambient update onto the current span.
    No-op (never raises) when there is no active span."""
    if not prose:
        return
    try:
        from langfuse import get_client

        from polymerhus.app.observability.langfuse_tracing import explicit_correlation

        if run_id is None:
            get_client().update_current_span(input={"call": call}, output=prose)
            return
        with explicit_correlation(run_id, tags=tags):
            with get_client().start_as_current_observation(
                name=call, as_type="span", input={"call": call},
            ) as span:
                span.update(output=prose)
    except Exception:
        logger.debug("trace_reasoning could not attach %r reasoning", call, exc_info=True)


def trace_generation(call: str, *, input=None, output=None, run_id: str | None = None,
                     tags: list | None = None) -> None:
    """Persist a proposer's STRUCTURED generation (its input slice + the batch it returned,
    incl. per-item confidences) as a child `generation` observation under the current agent
    span.

    Closes the observability hole surfaced on moodique (run cc29fd4a): a proposer's structured
    output - the Assigner's aggregate proposals and their confidences, the typist's systems/edges
    - reached Langfuse only as anonymous, output-less LLM runs, so a post-hoc question like "did
    the Assigner withhold on confidence?" was unanswerable from the traces. `trace_reasoning`
    overwrites the AGENT span's own input/output (used for free-text prose), so structured output
    rides its OWN nested observation instead of clobbering it. With explicit `run_id` the
    observation opens under an explicit correlation context (convergence: no agent span to
    nest under); without it the legacy ambient nesting is kept. Fail-open (never raises /
    perturbs the proposer); no-op when there is no active span. `input`/`output` must be
    JSON-serialisable."""
    try:
        from langfuse import get_client

        from polymerhus.app.observability.langfuse_tracing import explicit_correlation

        with explicit_correlation(run_id, tags=tags):
            with get_client().start_as_current_observation(
                name=call, as_type="generation", input=input,
            ) as gen:
                gen.update(output=output)
    except Exception:
        logger.debug("trace_generation could not record %r", call, exc_info=True)


def flush_analyser_traces() -> None:
    """Flush pending spans (a run worker may exit before the background exporter fires).
    `flush`, never `shutdown` - the client is a process-wide singleton later runs reuse."""
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception:
        logger.debug("flush_analyser_traces failed", exc_info=True)
