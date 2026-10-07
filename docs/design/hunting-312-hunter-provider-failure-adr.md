# ADR: a provider failure in a dispatched hunter or pod pauses the run (#312)

*Status: RATIFIED pending verifier review (2026-10-08). Match check: this is the third slice of the provider-resilience umbrella (`docs/design/eval-provider-resilience.md`), after `hunting-329-provider-failure-classification-adr.md` (the typed classifier, the pod verdict-fabrication abolition, the orchestrator-abort `interrupted`) and `hunting-331-provider-resume-adr.md` (the run-row cause on an `interrupted`). It records the #312 re-verification finding and the gap those two slices left open; it supersedes nothing.*

## Context

Ticket #312 was filed when the comfyui `trial-2` (project `75991388`) consumed 11 ratified hunt configs but authored 0 test-specs and dispatched 0 pods.
The original comment attributed the outcome to the provider `429` degradation and deferred to #329.
#329 and #331 landed; this ADR is the re-verification.

### The re-verification finding: the zero-spec outcome was still live, and distinct

The trial-2 evidence (11 configs in `orchestration/hunt_configs/consumed/`, empty `hunter/test-specs/`) proves the orchestrator pass COMPLETED - it ratified and wrote the configs, and the surfer consumed them when dispatching the hunters.
The failure was therefore in the HUNTER phase, after the pass, which #329/#331 did not cover:

- `#329` scoped the orchestrator pass abort and the pod's fabricated `technical-infeasibility`; its impact map names `hunt_orchestrator.py`, `pod/`, and `runtime.py`, never `hunting_agent.py`.
- The hunting-agent harness (`attack/hunting/hunting_agent.py`) caught every exception at the per-turn seam and at the `dispatch_fn` boundary, returning a spec-less `DispatchResult` - including a `ProviderUnavailableError`.
- The surfer's `run_hunter_session` (`attack/hunting/surfer.py`) also caught every exception and idled anyway.

So a provider failure during the hunter phase was silently swallowed: the hunter authored no spec, recorded no typed reason, and the run quiesced `complete` with zero specs - the exact trial-2 outcome, unchanged by #329/#331.
The same gap existed for the pod: #329 made `run_pod_session` re-raise the typed error, but the raise landed in the unawaited future of a scheduled session, so the run still quiesced `complete`.

## Decision

### 1. A provider failure propagates from the hunter harness

`hunting_agent.build_hunting_agent` re-raises `ProviderUnavailableError` at both catch points (the per-turn seam and the `dispatch_fn` boundary), mirroring the pod (`arun_pod`).
A genuine non-provider error keeps the O3/C2/C3 fail-open degrade - only the typed provider error escapes.

### 2. The run-local dispatch state carries the failure to the surfer

`RunDispatchState` (`surfer.py`) gains `provider_failure: ProviderUnavailableError | None`.
A dispatched HUNTER session records it (`run_hunter_session`) and skips the idle loop; a dispatched POD session records it (`run_pod_session`) and re-raises.
The state is run-local and single-loop (the bootstrap, surfer, hunters and pods all run on the one worker loop), so no lock is needed.

### 3. The surfer surfaces the failure; the run pauses as `interrupted`

`run_surfer_loop` re-raises `state.provider_failure` after a tick, so the typed error reaches the run bootstrap through the surfer's outcome.
`runtime.start_hunting` catches `ProviderUnavailableError` and persists the resumable terminal `interrupted` with the provider cause on the run row's `stats` (`_provider_interrupt_stats`), exactly as it already does for a provider-caused orchestrator abort.

The run now records a typed reason for producing no spec, satisfying #312's acceptance criterion.

## Consequences

### The good

- A provider failure anywhere in the hunting pipeline - pass, hunter, or pod - now lands the same resumable `interrupted` with a typed cause; no phase quiesces `complete` while silently producing nothing.
- #329's pod propagation is no longer inert: its typed error now reaches the run terminal.
- No new terminal value and no domain fabrication; the six-value vocabulary and `PodExport` are untouched.

### Still open (unchanged, operator-gated)

The app-layer STOP/FLUSH/RESUME re-scheduling (the affected session types restarted from their flushed pre-failure checkpoints), its trigger, and the 429-vs-consumed-credits resume policy remain the ESCALATED operator decisions of `hunting-331-provider-resume-adr.md`.
This slice only marks the terminal and records the cause; it does not resume.
As with the existing orchestrator-abort path, sibling sessions are not proactively cancelled when the run pauses.

## Impact map (as built)

- `src/polymerhus/attack/hunting/hunting_agent.py` - `ProviderUnavailableError` re-raised at the per-turn and `dispatch_fn` catch points.
- `src/polymerhus/attack/hunting/surfer.py` - `RunDispatchState.provider_failure`; `run_hunter_session` records and skips idle; `run_pod_session` records (and re-raises); `run_surfer_loop` surfaces it.
- `src/polymerhus/attack/hunting/runtime.py` - `start_hunting` maps a child-session `ProviderUnavailableError` to `interrupted` + `stats`.
- Tests: `tests/attack/test_hunting_runtime.py::test_hunter_provider_failure_interrupts_the_run`, `tests/attack/test_hunting_wiring.py::test_pod_provider_failure_interrupts_the_run`.
