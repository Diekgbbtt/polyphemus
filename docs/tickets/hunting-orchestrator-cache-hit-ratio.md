# Ticket: the hunting orchestrator has a very low input cache-hit ratio

- **Severity:** high (cost).
- **Area:** `src/polymerhus/attack/hunting/` (the hunting orchestrator role).
- **Status:** open.
- **Filed from:** the v2 (batched L1-unit-first) comfyui trial, 2026-10-11/12.

## Summary

The hunting orchestrator reuses almost none of its input prefix at the provider cache.
Its cached-input share is about 8.7%, while the sibling hunting hunter reaches about 72.8% on the same run.
It also dominates the run cost: 123,172,461 capped tokens over 1,107 calls, which is 76.6% of the whole-project 160,727,360.

## Evidence (introspectable on the recent eval trial)

- Trial record: `eval/runs-unitv2/comfyui-1/comfyui-1-20261011T233832-1fc05262/trial.yaml` (terminal `stopped`, `spent_tokens` 4,113,244 at the trial's stop).
- Usage ledger: `GET /projects/{pid}/usage` for project `6c357d47-2b7e-401e-9521-d268f2902365` (the C4 source).
- Hunting runs: `c1dd0163-5e7a-4ce0-97ff-a628ee44a096` (the trial's run) and `82782ad7-9ddd-491d-8282-4c894a906261` (the runaway drain-chained run).
- Model at the time: `opencode-go:deepseek-v4.1-flash` (the model switch had not been applied; now `opencode-go:muse-spark-1.3-contributor`).
- Cross-version report: `docs/experiments/analysisUnitFirst-vs-l0batchFirst-pipeline-comfyui-results.md`, section "Token distribution by role".

Token distribution by role (whole project, from the usage ledger):

| Role | cached input | uncached input | capped | calls | cached share |
|------|-------------:|---------------:|-------:|------:|-------------:|
| hunting_orchestrator | 11,618,816 | 122,539,534 | 123,172,461 | 1,107 | 8.7% |
| hunting_hunter | 50,057,088 | 18,708,237 | 19,682,473 | 698 | 72.8% |
| assigner | 17,983,104 | 12,467,518 | 13,911,054 | 231 | 59.1% |
| mechanism_typist | 17,238,144 | 3,270,869 | 3,755,681 | 204 | 84.1% |
| triager | 0 | 142,995 | 149,052 | 28 | 0.0% |
| pod_runner | 164,992 | 45,672 | 56,639 | 22 | 78.3% |
| **total** | **97,062,144** | **157,174,825** | **160,727,360** | **2,290** | **38.2%** |

The analysis roles alone cache 35,221,248 of 51,102,630 input tokens (68.9%).
The hunting orchestrator alone is 122,539,534 uncached input tokens, i.e. 78.0% of the run's whole uncached input.

## Hypothesis

The orchestrator's per-call request prefix is not stable, so the provider prefix cache misses on nearly every call.
The hunter keeps a stable leading block; the orchestrator does not.
Candidates to check: the orchestrator rebuilds a large changing prefix each turn (the accumulated observations, the tool result payloads, or a re-rendered transcript), or it moves the role prompt or the schema between turns (the shape that already defeated the cache once for `data_modeller`, see the constant-request-shape rule in `analysis/CONTEXT.md`).

## Acceptance criteria

- The hunting orchestrator's cached-input share is at or above the 70% mean bar used by the analysis (C4), measured on the same target.
- No behaviour change to the hunting decisions; the fix is a request-shape/cache change only.
- A regression test asserts the orchestrator's request shape is constant across its turns (the same shape of assertion the analysis proposers already carry).

## Notes

- The 1,107 orchestrator calls over a 45-minute run are themselves a finding: the orchestrator turn count and the hunter turn count are worth revisiting alongside the cache fix.
- The hunting run ended with `provider_status` 429 (`stats` in `hunting_runs`), so some calls may have been retries that also miss the cache. Confirm whether retries inflate the uncached input before attributing all of it to prefix instability.
