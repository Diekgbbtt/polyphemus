# ADR: the eval trial always enables streamed analysis

## Status
Accepted (2026-10-05).

## Context
- A hunting run produced 0 L1 `AGGREGATES` edges, so hunters could not ground a
  fault to an endpoint and looped in D1 (#321).
- Root cause: `settings.recon.streaming_analysis` was unset for the eval
  projects. The live settings rows carried only `operator_kb` and `target_seed`.
- With the flag off, `run_pipeline` (`pipeline.py:386`) never starts the queued
  analysis consumer and never pushes the per-job `L0Chunk` (`pipeline.py:725`),
  so no `analyse_chunked` pass runs and the L1 curator writes no `AGGREGATES`.
- The batched / post-recon analysis path is obsolete; streamed analysis is the
  supported path.

## Decision
- `TrialConfig.streaming_analysis` defaults `True`.
- Both the plan preview and the bootstrap PUT `settings.recon.streaming_analysis
  = true` for every fresh trial. The settings PUT deep-merges, so `target_seed`
  and `operator_kb` are preserved.
- `cli.py` passes the field explicitly, so the intent is visible at the one
  construction site.

## Consequences
- Every fresh eval trial runs analysis interleaved with recon: one queued pass
  per producing job, and the L1 `AGGREGATES` are minted during recon.
- A seeded trial (`existing_project_id`) still makes no settings call - its
  project carries the operator's settings unchanged.

## References
- #321 (analysis L1 gap), `pipeline.py:386`/`:725`, `analysis/feed.py`.
