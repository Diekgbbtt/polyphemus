# Token accounting: white-jotter 7M trial

Trial `white-jotter-1-20261022T030303-1618c524`, project `4786aefc-c3fd-46c1-a2ab-45b05cc38e25`.
Run `5c9590ff-9a83-4cea-9aff-be1bd51e2667`.
Measured code `5789ad3f`; 7M capped-token budget; 4-hour phase deadline.

## Sources

- **Client `/usage`**: the app's durable project ledger, `GET /projects/{id}/usage`, backed by `<data_root>/<project>/usage/usage.yaml`.
  It records each model call whose response carries LangChain `usage_metadata`; it is the source the trial cap enforces.
- **Langfuse**: the observability record, queried with the Langfuse v4 `observations list` API for the trial window (2026-10-21T23:50Z to 2026-10-22T03:15Z), `type=GENERATION`, fields `usage`.
  Every generation carries `usageDetails` (`input`, `input_cache_read`, `output`, `output_reasoning`) and `totalUsage`.
- **Eval tracking**: `trial.yaml` (`spent_tokens`, `token_spectrum`) and the `metrics.yaml` token section.
  The metrics token section is the trial record's `token_spectrum`, not a fresh read of the durable ledger.

The capped definition is the same in all three: `uncached input + visible output + reasoning`.
Cached input is part of `total` but not `capped`.

## Per-agent tokens

Calls and capped tokens for the three sources.
The full per-type values are in the next table.

| Agent | /usage calls | /usage capped | Langfuse calls | Langfuse capped | Eval calls | Eval capped |
|---|---:|---:|---:|---:|---:|---:|
| job_orchestrator | 13 | 41,691 | 13 | 41,691 | 13 | 41,691 |
| triager | 9 | 65,176 | 9 | 65,176 | 9 | 65,176 |
| assigner | 10 | 66,931 | 13 | 66,931 | 10 | 66,931 |
| mechanism_typist | 43 | 321,694 | 46 | 321,694 | 43 | 321,694 |
| hunting_threat_modeller | 160 | 1,162,922 | 163 | 1,640,339 | 134 | 1,087,977 |
| hunting_hunter | 397 | 2,155,350 | 398 | 2,155,350 | 397 | 2,155,350 |
| pod_runner | 709 | 2,223,212 | 709 | 2,223,212 | 709 | 2,223,212 |
| pod_triager | 79 | 1,040,187 | 79 | 1,040,187 | 79 | 1,040,187 |
| skill_evolver | 0 | 0 | 7 | 58,339 | 0 | 0 |

The only project-role token difference between `/usage` and Langfuse is the modeller: +3 generations and +477,417 capped.
The assigner (+3), mechanism_typist (+3), and hunter (+1) call-count differences are zero-usage generations; their tokens match exactly.

## Per-agent, per-type: `/usage`

| Agent | Calls | Cached | Uncached | Visible | Reasoning | Total | Capped |
|---|---:|---:|---:|---:|---:|---:|---:|
| job_orchestrator | 13 | 179,968 | 30,439 | 6,822 | 4,430 | 221,659 | 41,691 |
| triager | 9 | 41,600 | 55,779 | 3,740 | 5,657 | 106,776 | 65,176 |
| assigner | 10 | 118,656 | 50,629 | 3,764 | 12,538 | 185,587 | 66,931 |
| mechanism_typist | 43 | 1,897,600 | 246,139 | 27,992 | 47,563 | 2,219,294 | 321,694 |
| hunting_threat_modeller | 160 | 33,565,568 | 902,851 | 153,745 | 106,326 | 34,728,490 | 1,162,922 |
| hunting_hunter | 397 | 25,069,568 | 1,763,880 | 159,017 | 232,453 | 27,224,918 | 2,155,350 |
| pod_runner | 709 | 24,366,592 | 1,754,019 | 233,817 | 235,376 | 26,589,804 | 2,223,212 |
| pod_triager | 79 | 1,674,880 | 850,278 | 37,912 | 151,997 | 2,715,067 | 1,040,187 |
| **total** | **1,420** | **86,914,432** | **5,654,014** | **626,809** | **796,340** | **93,991,595** | **7,077,163** |

## Per-type totals: all sources

| Source | Calls | Cached | Uncached | Visible | Reasoning | Total | Capped |
|---|---:|---:|---:|---:|---:|---:|---:|
| `/usage` (project) | 1,420 | 86,914,432 | 5,654,014 | 626,809 | 796,340 | 93,991,595 | 7,077,163 |
| Langfuse (project roles) | 1,430 | 87,148,800 | 6,122,879 | 630,643 | 801,058 | 94,703,380 | 7,554,580 |
| Langfuse (all, incl. skill evolver) | 1,437 | 87,278,848 | 6,164,002 | 636,379 | 812,538 | 94,891,767 | 7,612,919 |
| Eval snapshot (`trial.yaml` / `metrics.yaml`) | 1,394 | 83,264,896 | 5,608,902 | 606,212 | 787,104 | 90,267,114 | 7,002,218 |

The `skill_evolver` is an app-level role outside the project usage scope.
It contributes 7 generations and 58,339 capped tokens to the all-Langfuse figure.
The project-comparable Langfuse total is 7,554,580 capped.

## Sample session: the threat modeller

Langfuse session `5c9590ff-9a83-4cea-9aff-be1bd51e2667:hunting_threat_modeller`.
It has 6 traces and 163 generations.

| Source | Calls | Cached | Uncached | Visible | Reasoning | Total | Capped |
|---|---:|---:|---:|---:|---:|---:|---:|
| `/usage` | 160 | 33,565,568 | 902,851 | 153,745 | 106,326 | 34,728,490 | 1,162,922 |
| Langfuse | 163 | 33,799,936 | 1,371,716 | 157,579 | 111,044 | 35,440,275 | 1,640,339 |
| Eval snapshot | 134 | 29,916,032 | 857,739 | 133,148 | 97,090 | 31,004,009 | 1,087,977 |

Deltas:

| Comparison | Calls | Cached | Uncached | Visible | Reasoning | Total | Capped |
|---|---:|---:|---:|---:|---:|---:|---:|
| Langfuse minus `/usage` | +3 | +234,368 | +468,865 | +3,834 | +4,718 | +711,785 | +477,417 |
| `/usage` minus eval | +26 | +3,649,536 | +45,112 | +20,597 | +9,236 | +3,724,481 | +74,945 |
| Langfuse minus eval | +29 | +3,883,904 | +513,977 | +24,431 | +13,954 | +4,436,266 | +552,362 |

The three Langfuse-only generations are:

- two retry-shaped attempts at 02:26, each with 234,411 uncached input (capped 237,089 and 236,430);
- one cache-only generation at 02:34 with 43 uncached and 234,368 cached input, 2,316 visible and 1,539 reasoning output (capped 3,898).

The 00:33 generation with 281,630 uncached input is present in `/usage`; it is not part of the gap.
The three Langfuse-only generations are visible in the trace with different parent observations and distinct start/end times, so they are not duplicate spans of one call.

## What each source is good for

- **Langfuse is the most accurate measure of raw provider usage.**
  It records every generation the OpenAI SDK observed, including the modeller's two retry-shaped 234k-uncached attempts and one cache-only generation that the client ledger does not contain.
  It also exposes the app-level skill evolver that the project ledger intentionally excludes.
- **`/usage` is the authoritative project-scoped budget ledger.**
  It has the correct scope and it is durable, but it is not complete: it misses the modeller's three generations, so it under-reports the project by 477,417 capped tokens.
  The cap is enforced on this source, which makes the cap soft.
- **The eval snapshot is the least accurate for final spend.**
  Its token section is the trial record's terminal `token_spectrum`, not a fresh read of the durable ledger.
  It misses the 26 post-stop modeller calls (74,945 capped) and the three client-ledger gaps (477,417 capped), for a total under-report of 552,362 capped against the project-comparable Langfuse total.
  It was still correct for the decision it made: the project had crossed 7M at the terminal read.

## Cap implication

| Measure | Value |
|---|---:|
| Trial record `spent_tokens` | 7,002,218 |
| Trial record `spend_overshoot` | 3,405 |
| `/usage` at rest | 7,077,163 (overshoot 77,163) |
| Langfuse project roles | 7,554,580 (overshoot 554,580) |
| Langfuse all roles | 7,612,919 (overshoot 612,919) |

The reported overshoot of 3,405 is not the settled provider overshoot.
The project-comparable Langfuse figure says the trial spent about 7.9% more capped tokens than the 7M budget, not 0.05%.

## Structural causes

1. **Snapshot versus settle.** The trial stops at the cap after reading `/usage`; in-flight modeller calls finish after that read. The durable `/usage` at rest is 74,945 capped higher than the trial record. The metrics token section copies the trial snapshot, so it does not see the settle either.
2. **Client middleware coverage.** `TokenUsageMiddleware` records only responses that carry LangChain `usage_metadata`; a response without it is skipped fail-open. Langfuse's generation instrumentation reads the provider response directly. That is where the modeller's three extra generations come from.
3. **Usage scope.** The skill evolver is app-level, not project-level; Langfuse includes it in the time window, `/usage` excludes it by scope. Keep it out of the trial budget, but do not lose it from platform accounting.
4. **Zero-usage attempts.** Langfuse counts provider attempts that produced no usage (assigner +3, mechanism_typist +3, hunter +1). They inflate the call count, not the tokens.

## Recommendation

- Report the trial's provider usage from **Langfuse project roles**: 7,554,580 capped, 94,703,380 total, 1,430 generations.
  Add the skill evolver only for platform-level spend: 7,612,919 capped.
- Keep `/usage` as the cap source, but **reconcile it after the project is idle** and feed the settled value into `trial.yaml`.
  The current `spent_tokens` under-reports by 552,362 capped against Langfuse.
- Fix the `TokenUsageMiddleware` coverage so retry/cache-only/streaming responses are recorded, or read the provider's usage from the Langfuse generation when the middleware has no `usage_metadata`.
  Without that, a token cap enforced on `/usage` cannot be hard.
- Treat the eval snapshot as the **decision-time** record, not the **final-bill** record.
  The final-bill record is the durable `/usage` after settle, cross-checked with Langfuse.

## Reproduction

- Client ledger: `curl -s http://localhost:8080/projects/4786aefc-c3fd-46c1-a2ab-45b05cc38e25/usage`
- Durable file: `/opt/polymerhus-dev/eval/instances/data/eval-server-1/4786aefc-c3fd-46c1-a2ab-45b05cc38e25/usage/usage.yaml`
- Trial record: `/opt/polymerhus-dev/eval/runs-utm-20261021-white-jotter/white-jotter-1/white-jotter-1-20261022T030303-1618c524/trial.yaml`
- Metrics: the same directory, `metrics.yaml`
- Langfuse: `langfuse-cli api observations list --from-start-time 2026-10-21T23:50:00Z --to-start-time 2026-10-22T03:15:00Z --type GENERATION --fields core,basic,time,model,usage,trace_context --limit 1000 --all --max-items 5000 --json`
