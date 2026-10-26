# 432 - Keep stopped pods durably resumable

**What to build:** Persist a resume cursor when a pod attempt stops or is cancelled, rehydrate the experiment log on the next dispatch, and keep the gate holding until a terminal export exists.

**Blocked by:** none

**Status:** done

**Seams:** `attack/hunting/pod/pod_memory.py`, `attack/hunting/pod/context.py`, `attack/hunting/pod/graph.py`, `attack/hunting/surfer.py`, `attack/hunting/pipeline_sync.py`

## Context

Iteration B stopped the hunting run at `2026-10-26T03:11:21Z`.
The last 20 pod directories were born between `02:48:42Z` and `02:50:50Z`, had 4 to 14 executed probes each, and had no export.
The old behaviour cancelled the pods without a terminal record and lost their work.

The approved path chooses durable resume over a synthetic stop export.

## Result

- `PodMemoryStore` persists `<spec_id>/<run_id>.resume.yaml` beside the terminal export.
  The cursor is excluded from `list_pod_exports` and is never a `PodExport`.
- The cursor records the last order, current variant, iteration, feedback, and executed ledger.
- `ExperimentLog.hydrate` rebuilds variants, raw observations, KB observations, interpretations, and the executed ledger from the per-order slices.
- `init` continues at the cursor variant.
  The tools skip every probe signature already in the executed ledger.
- `runner_agent`, `triager`, and `mint_variant` write the cursor at their node boundaries.
- A terminal export clears the cursor.
- A cancelled pod writes no export.
  The gate holds because no durable export exists; the next dispatch resumes from the cursor.

## Verification

- `tests/attack/pod/test_pod_memory.py`: 50 passed, including the cursor round-trip, the per-spec isolation, the export-list exclusion, and `ExperimentLog.hydrate`.
- `tests/attack/pod/test_graph.py`: 35 passed, including the resumed pod that skips an executed probe and the cancelled pod that keeps its cursor with no export.
- `tests/attack/test_hunting_session_watchdog.py`: 5 passed, including the cancelled session with no export and a retained cursor.
- `tests/attack/test_hunting_pipeline_sync_lifecycle.py`: 14 passed, including the resume cursor that does not count as a terminal export.
- `tests/attack`: 1142 passed.
