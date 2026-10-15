# Typist cache collapse (arm G2) - diagnosis [VERDICT FALSIFIED 2026-10-15]

*Status: the provider-side verdict of the 2026-10-14 diagnosis was falsified on 2026-10-15.*
*The "0.0% cached" was a measurement artifact of the gateway's streamed usage assembly (pinned litellm 1.96.0), fixed in this branch (`gateway_proxy_bootstrap.py`).*
*The original sections follow below, kept for the record: their ruled-out hypotheses still stand, their verdict does not.*

## Corrected verdict

The typist's "0.0% cached / 2,670,245 capped tokens" was not a provider cache miss and not a provider cache-eligibility defect: the arm-G2 typist calls DID hit the provider cache.
Replaying the exact `call[00]` request bytes on the same session id 13.5 h later returned `cached=4480/4673` (95.9%), and a second replay returned `cached=4672/4673`.
The provider reported `cached=0` only for a genuinely cold session, which is what a measured miss looks like.
The loss happened at OUR gateway hop: pinned litellm 1.96.0 drops `prompt_tokens` and `prompt_tokens_details` whenever the provider attaches `usage` to a choice-bearing finish chunk, and substitutes a messages-only prompt count (3614 instead of 7215 on the probe body) with no details map.
The app ledger and Langfuse then faithfully propagated the silence, and the absent `input_cache_read` key rendered as a 0% cached share.

## Falsification evidence (2026-10-15)

Controlled replay of the captured arm-G2 typist call (same body bytes, same `x-opencode-session`, 13.5 h later, through the gateway): `cached=4480/4673` (95.9%), then `cached=4672/4673`.
A fresh dev-shape nonstream call on the same warm session: `cached=7040/7215` (97.6%).
A cold session reports `cached=0`, so the provider does report measured misses explicitly.
In-container A/B on the real gateway (same warm body, same session): the running proxy returned streamed `prompt_tokens=3614` with no `prompt_tokens_details` on 2 of 3 calls, while a second proxy carrying the continuity patch returned streamed `prompt_tokens=7215` with `cached_tokens=7040` on 3 of 3 - matching the nonstream twin on both ports.
Wire check: the 23 captured chain bodies are append-only (system sha `46c57a45ee28` x23, tools sha `2b7de75e296b` x23), so the requests were cache-friendly by construction.

## Mechanism

`litellm/litellm_core_utils/streaming_handler.py:1463` runs `model_response.usage = chunk.usage` when the usage-bearing chunk also carries choices, landing the raw openai `CompletionUsage` on the message.
`_usage_chunk_calculation_helper` (`streaming_chunk_builder_utils.py:462`) then reads it with `"prompt_tokens" in usage_chunk` (false for a pydantic model) and `isinstance(..., PromptTokensDetailsWrapper)` (also false), so the real values are dropped, and `calculate_usage` falls back at `:749` to `token_counter(messages=...)` - a messages-only count, tools and cache excluded.
A usage-ONLY chunk (`choices: []`) takes an earlier conversion path and keeps the detail, so the loss depends on the upstream chunk shape, which the client does not control and which is time-intermittent.
The per-role split (typist 58/58 omitted against siblings 73/73 and 37/37 full) is consistent with the relay's per-session backend affinity (one session tends to reach one backend for as long as the affinity holds, so one role-session can keep the lossy shape for a whole run) - consistent with, not proven by, this evidence; the direct A/B above is the proof of the loss itself.
The fix rides the proxy process (`src/polymerhus/app/gateway_proxy_bootstrap.py`, launched by the entrypoint), and the eval trial record now carries `cache_detail_omitted` so a future silence is visible instead of readable as a miss.

## What survives from the original diagnosis

Compaction never fired (0/57 over-budget lines), so the churn hypothesis stays falsified.
The per-chunk reset fires correctly and the ledger sawtooths as designed.
The request construction is byte-stable (one system sha, one tool-spec sha across both roles), now confirmed append-only on the wire.
The bounded controls still hold: input size, reasoning volume, retry rotation, and TTL do not explain the recorded zero.
The provider cache facts stand: 16-token block alignment, cross-session prefix reuse, and a TTL beyond 13.5 h.

*The sections below are the original 2026-10-14 diagnosis, kept for the record.*

## Question

Arm G2's mechanism-typist spent 2,670,245 capped tokens at 0.0% cached over 58 model calls, single-handedly breaking the 70% cache-hygiene bar (run total 30.2%) and materially contributing to the 3M-budget stop.
A recent run on the same streamed-L0 pipeline showed ~90% typist cache hits.
Each proposer context resets to the system prompt at every L0 chunk on a stable per-(run, role) session id.
The hypotheses under test were: too-strict compaction churn rewriting the prefix, a broken reset leaking trail across chunks, and a tool-surface/spec toggle between turns.

## Measurements

All Langfuse reads use the pinned procedure (`GET /api/public/v2/observations`, cursor paging, tag filter).
Credentials were exported from the eval instance env, never pasted.
Arm G2 window is 2026-10-14T20:40Z-21:45Z, recon run `2c319370-6dec-4dd5-a73d-17ccf1af70bc`, model `opencode-go:deepseek-v4.1-flash` for every role.

### Usage split by role (ledger + Langfuse usageDetails)

Typist: 58 generations, every `usageDetails` carries `input`/`output`/`total`/`output_reasoning` and NO `input_cache_read` key at all.
Assigner (same run, same model, same gateway): every generation carries `input_cache_read` (e.g. 22272/24338 = 91.5%).
Data-modeller: 36/37 generations cached, 79.9% share; triager 66.8%.
The 0% is therefore per-role request handling, not a model- or gateway-wide telemetry absence.

### Compaction: never fired

The typist's compaction ledger (container log, 57 lines): max occupancy 70,236 against budget 200,000 (`0.2 x 1M` context window of `deepseek-v4.1-flash`), `over_budget=True` on 0/57 lines, `cache_read=0` on 57/57.
No `compaction_readability` / `compaction_reclaimed_tokens` / `compaction_summary_status` metadata on any of the 58 typist generations.
The strict-threshold-churn hypothesis is falsified directly: there was no churn.
For contrast, the high-hit 2026-10-13 run settled compactions (`compacted`, 127,378 tokens reclaimed on one pass) because its model window priced the budget at ~25.6k, not 200k.

### Reset lifecycle: fires correctly

197 `compaction: reset thread ... (per-chunk lifecycle)` lines in the window, all three roles.
The typist ledger shows the sawtooth of a working reset (e.g. 7393 then 4870 right after a reset line) and small first-turn occupancy per batch.
`reset_session_thread` + `manager.reset_thread` (trail, pending pass, summary pointer, streak, report, ledger) both run, fail-open.

### Request bytes: stable everywhere checked

Pulled all 58 typist generation IO records (12.5MB) plus 73 assigner ones as control, and compared consecutive prompts byte-wise.
System prompt: byte-identical across all 48 parseable typist prompts (8056 chars, 1 distinct value).
Bound tool spec (the `L1DeltaBatch` function tool, 5505 chars): ONE sha over 48/48 typist prompts, and the SAME sha rides all 73 assigner prompts - the constant-request-shape design (`_prose_tools` hand tool identical to the `ToolStrategy` tool) verified at the byte level, prose and structured turns alike.
Negotiation: `capability-probe` spans choose `voluntary_function_calling` from `models.dev` on every sampled turn; `modelParameters` (`temperature 0`, `max_completion_tokens 131072`) identical on 58/58.
Bind kwargs captured with a throwaway harness (`/tmp/wire-shape.py`, since removed): prose binds the one tool with `tool_choice=None`, structured turns bind `tool_choice='any'` - uniform per turn-type, and the local assembly shapes are identical across typist and data-modeller modulo message content.
Within-batch consecutive prompts share up to 261,876 of 261,887 chars (a retry-identical pair 10 seconds apart), yet both report zero cache.

### Controls that bound the defect

Data-modeller runs the same prose/structured alternation on the same model and caches 79.9%: alternation does not break caching.
Early typist turns were data-modeller-sized (2.8k-10.8k input) and still missed: size does not explain it.
Data-modeller hits with `output_reasoning` up to 2027 while its single miss (20:55:22Z, reasoning 1241) sits among larger-reasoning hits: reasoning volume does not explain it.
The 20:55:22Z miss is the same phenomenon in miniature (first-turn shape identical to its hitting siblings): the provider sometimes declines an identical-shape request, and for the typist it declined all 58.

### Deltas versus the high-hit run

The 2026-10-13 high-hit run (`a1c1f6ea`, typist `input_cache_read` 80-128k of 91-133k input, ~90%) differs from G2 in three ways, none of which is a typist construction change.
Model: `deepseek-v4-flash` then, `deepseek-v4.1-flash` now (key entitlement, environment - not code).
Threading: `run:pod:role` threads then, one `run:role` session plus per-batch reset now (`3b19ead`, verified working above).
Compaction budget: ~25.6k then (old window), 200k now (1M window) - this explains why compaction fired then and never now, but cannot explain the cache delta because the assigner and data-modeller cache fine under the same budget.
Typist-side construction is unchanged across the window: `git log` shows only the assigner surface change (`5b64d09`, assigner-only tools), the lifecycle refactor (`3b19ead`), and the pipeline split (`05fe5fa`) touching these files, and the endpoint-first prefix already rode the old run.
No separate-checkout A/B was needed: there is no typist-side delta to bisect.

## Falsified hypotheses

A too-strict compaction threshold rewriting the prefix: no pass ever ran (0/57 over budget).
A broken reset leaking cross-chunk trail: resets fire, ledger sawtooths, first-turn occupancy is small.
A tool-surface or spec toggle between prose and structured turns: one tool-spec sha across all turns and both roles.
Model params or negotiated-method drift between turns: 58/58 identical.
Transient-retry conversation rotation (`#rN` cold sessions): exactly one `transient` line in the window (an OTLP exporter warning, unrelated), no `#rN` conversation ids.
Cache TTL expiry: a 132s-gap data-modeller turn hits while a 115s-gap one misses.
Input size: small early typist turns miss exactly like the large ones.
Reasoning volume: counter-examples in both directions on the data-modeller.

## The "standing anomaly", re-read (2026-10-15)

The anomaly below was OUR gateway dropping the streamed cache detail (`cache_detail_omitted` 58/58 for the typist), not a provider decision: see the corrected verdict and the falsification evidence above.
The retry-identical pair is the sharpest example of a lossy-shaped stream pair on one session, not evidence of provider ineligibility.
The data-modeller's single miss is consistent with one call on the intermixed chunk shape, and remains far rarer than the typist's run-long silence.
The original text, kept for the record:

> Deepseek via opencode-go reported `input_cache_read` for 67-80% of assigner/data-modeller/triager calls and 0/58 typist calls whose logged prompt bytes share up to 261k leading chars with the previous call, same model, same gateway, same credentials, same hour.
> The retry-identical pair (21:06:35Z/21:06:45Z, 11 chars apart - both Langfuse truncation markers of the same wire bytes, 10 seconds apart) is the sharpest instance: no prefix-cache implementation misses that unless the request class is ineligible or the usage report is dropped.
> The data-modeller's single miss shows the mechanism fires outside the typist too, rarely.

## Follow-ups (status 2026-10-15)

The two provider-side follow-ups are resolved: the deterministic repro is the captured-bytes replay (95.9% cached) in "Falsification evidence" above, and the gateway capture is the in-container A/B plus the direct source read of litellm 1.96.0 (`cache-spectrum-measurement-research.md`).
Resolved in the app: `usageDetails` absence of `input_cache_read` versus explicit zero are now two facts in the ledger (`cache_detail_omitted`, N5), threaded into the eval trial record by this branch.
Still open (observability debt noticed along the way, unrelated to caching): the recorded prompt bytes alternate between raw `...` (U+2026) and its `\u2026`-escaped rendering across observations (two recorder serializations disagree on `ensure_ascii`), and several large generation IO records are truncated with `[truncated N bytes]` markers, which corrupts byte-level prefix analysis past ~261k chars.
The 21:14:19Z OTLP `Bad Gateway` span-export warning remains unrelated.
