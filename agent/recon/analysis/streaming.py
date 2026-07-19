"""FR-STREAM (NM-7) — the streaming analyser step.

The L1 attack surface can be integrated PROGRESSIVELY during recon, not only as a
post-recon batch. L1D-23 makes this a two-way door: push (stream at recon time)
and pull (post-recon batch) "produce identical reads and writes" precisely because
the analyser is a pure `f(L0-slice + observations) -> L1-deltas` written by
idempotent MERGE. So a streaming step is nothing more than invoking that same pure
function on the CURRENT cumulative surface as recon produces it; repeated passes
over the growing slice converge to (and the final pass equals) the batch result.

`stream_analyser_step` is the per-increment invocation the pipeline calls after a
recon job curates new surface. It is fail-open: a streaming error degrades that
step and never propagates into the recon run (mirrors the pipeline's best-effort
discipline and the analyser's own node-level fail-open).

Design choices (see the FR-STREAM ledger in docs/design/L1-MVP-plan.md):
- STABLE analyser id `stream-<run_id>` across steps, so re-asserting the same
  assignment as the surface grows MERGEs to one node/edge (idempotent, L1D-22).
- AUTO-DELIVER: the step leaves `observations=None` so `run_analyser` pulls the
  cumulative, id-deduped Observation set (FR-PODSTREAM) each time - the final
  step therefore sees the full slice + all observations, i.e. the batch inputs.
- No concurrent long-lived consumer task: the pipeline runs this synchronously
  between (sequential) jobs, so peak memory stays one analyser pass - the
  constrained-host OOM failure mode is not reintroduced.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def stream_analyser_step(project_id: str, run_id: str, *, analyse_fn=None):
    """Run one streaming analyser pass over the project's CURRENT surface.

    `run_id` is the recon run id; the analyser writes under the stable derived id
    `stream-<run_id>` so repeated steps are idempotent. `analyse_fn(project_id,
    run_id, observations=None) -> AnalyserExport` is injected for testing and
    defaults to the real `run_analyser` (which auto-delivers observations when
    they are None). Returns the AnalyserExport, or None if the step degraded
    (fail-open - a streaming error must never fail the recon run)."""
    if analyse_fn is None:
        from agent.recon.analysis.pod import run_analyser as analyse_fn
    try:
        return analyse_fn(project_id, f"stream-{run_id}")
    except Exception:  # fail-open: streaming is best-effort, never fails recon
        logger.warning(
            "stream_analyser_step: analyser failed for project=%s (degraded, recon continues)",
            project_id, exc_info=True,
        )
        return None
