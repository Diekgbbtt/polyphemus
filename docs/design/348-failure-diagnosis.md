# Diagnosis: the #348 fix did not address the mechanism_typist cache hostility

**Status:** Diagnosis (not an implementation).
**Ticket:** #348 (EV-33) follow-up.
**Date:** 2026-10-09.
**Author:** diagnosis subagent (branch `diagnose/348-failure`).
**Live evidence:** comfyui-1 trial `comfyui-1-20261009T110342-1fc05262`, project `0df6cf0c`, eval checkout `/opt/polymerhus-dev` at `6b0c9b59` (includes the #348 commit `965d91b`).

This report follows observe -> hypothesise -> experiment -> conclude.
It separates observation from inference.
It names the weak links.
It redacts every secret.

---

## 1. Verdict

The #348 fix rests on a false premise for `mechanism_typist`.
The premise is that a compaction pass leaves the thread over budget and so re-fires on every model call, regenerating the running summary and changing the request prefix.
The live run contradicts that premise on both counts:

- The pass CONVERGES.
  After each `mechanism_typist` pass the measured occupancy drops well under the budget, and the streak RESETS.
  The #348 branch never runs, so the cap never engages.
- The cache was zero from the FIRST model call, 26 calls before the first compaction pass ever ran.

The provider does cache this lane and this model in this same run: `assigner` and `data_modeller` cache normally.
For `mechanism_typist` the provider returns no cache accounting at all (`prompt_tokens_details` is JSON `null`), from the first call.
The app request prefix is append-only stable between consecutive calls.
So the cause is not app-side prefix instability.

The #348 harness measured a different regime (a replay tail that dwarfs the budget), which cannot occur at the eval's 200K budget.
The fix is correct for its own regime but that regime is not the `mechanism_typist` eval failure.

---

## 2. The #348 assumption, stated exactly

The ADR `docs/design/compaction-cache-convergence-348-adr.md` makes three chained claims:

1. (ADR:21) "a single large recent message ... is larger than the exempt replay tail (30K). D7 exempts that tail ... so the pass can fold the small older region but can never bring the thread under the 200K budget."
2. (ADR:23) A pass that "produced a summary but left the thread over budget ... looked like a recovery: the next model call re-triggered the barrier, which ran another pass, regenerated the running summary ... and changed the request prefix."
3. (ADR:27) Therefore "a pass that leaves the thread over budget ... counts the pass toward the consecutive-pass cap", and after 3 passes the trail stabilizes, "so the provider cache hits again."

The code that implements claim 3 is `src/polymerhus/app/llm/compaction.py:1162-1164`:

```
entry = self.ledger.entry(thread_id)
if entry is not None and entry.over_budget:
    self._note_failure(thread_id)
```

Claim 3 executes only when claim 1 and claim 2 hold, that is, when the applied trail is still over budget.
Both are false for `mechanism_typist`.

---

## 3. Experiment 1: does the pass leave the thread over budget?

Observation (agent container log, same run and thread `bf7bed51-...:mechanism_typist`):

```
11:00:49  compaction ledger: ... mechanism_typist occupancy=206167 budget=200000 over_budget=True
11:00:50  compaction: spawned out-of-band pass for thread ...:mechanism_typist
11:01:07  compaction: thread ...:mechanism_typist applied a compacted trail (reclaimed 141787 tokens)
11:01:11  compaction ledger: ... mechanism_typist occupancy=48109 budget=200000 over_budget=False
11:01:11  compaction: thread ...:mechanism_typist is under budget again; resetting the consecutive-pass streak
```

The applied occupancy is `48109`, far under the `200000` budget.
The streak is reset, not incremented.
The same shape repeats at every pass.
Aggregate counts for the whole run:

- `mechanism_typist` "is under budget again; resetting the consecutive-pass streak": 5.
- Any role "hit the consecutive-pass cap": 0.
- "recovered after a converging pass": 0.

Inference: the `if entry ... over_budget` branch at `compaction.py:1163` never executes for `mechanism_typist`.
The #348 cap is a no-op on this role.

Why the occupancy drops so far, even though a large recent message exists:
`_bound_oversized_tail` (`compaction.py:616-637`) strips `usage_metadata` from an oversized tail `AIMessage` (`_bound_message`, `compaction.py:605-609`).
`compute_occupancy` (`compaction.py:233-250`) then walks back to an EARLIER, smaller usage step.
So the measured occupancy is systematically optimistic for exactly the "oversized tail" case #348 targets.
The fix keys its decision on a metric that reads under budget in that very case.

Root (code): `src/polymerhus/app/llm/compaction.py:1163`.

---

## 4. Experiment 2: did the zero-cache burst begin when the thread crossed the budget?

Observation (Langfuse observations, `sessionId = bf7bed51-...:mechanism_typist`, per call `input` = fresh, `input_cache_read` = cached):

```
10:53:01  fresh=2714    cache=0   (call 1)
10:53:11  fresh=8377    cache=0
10:53:36  fresh=16306   cache=0
...
11:00:43  fresh=204327  cache=0   (call 26, the first over-budget call)
11:01:07  fresh=47719   cache=0   (call 27, after the first pass)
```

The first 36 calls (the trial window) sum to fresh `3,552,532`, cached `0`.
This exactly matches the trial record `spend_by_agent.mechanism_typist` (uncached `3,552,532`, cached `0`, calls `36`).

The first compaction pass ran at `11:00:50`, at call 26.
Calls 1 to 25 had `cache_read = 0` with no compaction in the thread's history.
So compaction cannot be the cause of the zero-cache burst.

Inference: the #348 causal model (claim 2) is refuted.
The cache hostility predates any compaction pass.

---

## 5. Experiment 3: does the provider cache this lane and model at all?

Observation (same run, same model `opencode-go/deepseek-v4.1-flash`, same process, same time window):

| role | calls | fresh (`input`) | cached (`input_cache_read`) | cached share |
|---|---|---|---|---|
| `mechanism_typist` | 81 | 8,181,473 | 1,398,656 | 14.6% |
| `assigner` | 25 | 162,201 | 1,594,240 | 90.8% |
| `data_modeller` | 38 | 552,218 | 3,221,376 | 85.4% |

`assigner` caches from its FIRST call (`10:54:11`, fresh `32`, cached `4736`).
`data_modeller` caches from its second call (`10:55:41`, cached `2048`).
Both cache while `mechanism_typist` reports zero in the same seconds.

LiteLLM gateway spend logs confirm the provider DID NOT return cache accounting for the `mechanism_typist` requests.
For 62 of the 81 `mechanism_typist` requests, `metadata.usage_object.prompt_tokens_details` is JSON `null`.
For every `assigner` and `data_modeller` request it carries a numeric `cached_tokens` (0 on a miss, non-zero on a hit).
The null rows span the whole run (`10:53:01` to `11:46:40`), so it is not a warm-up effect.

Inference: the provider caches this lane/model.
It simply performs no cache accounting for the `mechanism_typist` request stream.
This is a per-request property keyed to that role's requests, not a lane-wide or provider-wide property.

---

## 6. Experiment 4: is the app request prefix unstable?

Observation (Langfuse `input`, message lists parsed):
Between consecutive `mechanism_typist` calls the message list is append-only:

- call 1: `[system(skill), user(reflection)]`.
- call 2: the same two messages byte-for-byte, then `assistant(reflection)`, then `system(skill)`, then `user(systems)`.
- call 3: the call-2 prefix, then `assistant`, `tool`, `system(skill)`, `user(linking)`.

The system skill message (`analysis/prompts/technical-system.md`, 8196 chars) and the user reflection message hash identical across calls.
Only the tail grows.
The tool schema appears in the Langfuse rendering as a trailing `tool` pseudo-message, which shifts position between calls; it is a request-time rendering artifact, not a persisted trail rewrite.

Inference: the honest app prefix is stable.
The running-summary regeneration is periodic (one pass roughly every 10 calls), not per-call, and it cannot explain a zero at call 1.
So app-side prefix instability is not the cause.

Weak link: Langfuse truncates the larger request `input` strings at ~261,000 chars, so I could only fully parse the early calls.
The conclusion rests on those early calls plus the compaction logs, not on a full wire capture.

---

## 7. Experiment 5: is the cache convention misread?

Observation: the usage path reads correctly.
`app/llm/usage.py:107-122` decomposes `input_tokens` (inclusive) minus `cache_read` into `uncached`.
The trial's `uncached 3,552,532` equals the Langfuse fresh sum.
`trial.yaml` and the independent LiteLLM spend logs agree with the app.
No role mis-reports cached as uncached.

Inference: the convention is not misread.
The provider genuinely returned zero cache.

---

## 8. Experiment 6: did the harness measure a different regime?

Observation: the #348 regression test builds the trigger artificially.
`tests/test_llm_compaction.py:880` uses `CompactionWindow(context_limit=1000, threshold=0.9)`, that is, a budget of 900 tokens, with the DEFAULT `replay_keep_tokens=30_000` (`compaction.py:345`).
`tests/test_llm_compaction.py:891-899` pins a `ToolMessage(content="Z"*200_000)`, roughly 50K tokens, in the exempt tail.
So the exempt tail is ~50x the budget.
That guarantees a non-converging pass by construction.

The eval regime is `context_limit=1_000_000`, `threshold=0.2`, that is, a budget of 200K, with the same 30K tail.
At that budget the fold brings the thread to ~48K, as Experiment 1 shows.
The harness regime (tail dwarfs budget) cannot occur at the eval budget for the observed message sizes.

Inference: the harness is a valid test of the #348 code path but an unrepresentative model of the `mechanism_typist` eval failure.
This matches the operator's candidate 2 (the harness scaled the window so the trigger differed in kind).

---

## 9. Rooted cause

The #348 decision is rooted to a condition on a measured quantity that reads under budget in the exact case the fix was meant to catch:

- Wrong decision grounding: `src/polymerhus/app/llm/compaction.py:1163` (`if entry is not None and entry.over_budget`), fed by the T4 usage-stripping at `compaction.py:616-637`.
- Wrong hypothesis: the ADR premise at `docs/design/compaction-cache-convergence-348-adr.md:21` (the pass "can never bring the thread under the 200K budget") is false at the eval budget.
- Wrong test regime: `tests/test_llm_compaction.py:880,891` only exercises a tail that dwarfs the budget.

The real `mechanism_typist` cache hostility has a different cause that #348 does not touch.
It is present from call 1 and is a provider-side no-cache-accounting property of that role's request stream.

---

## 10. Corrected hypothesis

### 10.1 Statement

The `mechanism_typist` cache hostility is not caused by compaction.
It is present from the first model call and is a per-request property of the provider's treatment of this role's request stream: opencode-go returns `prompt_tokens_details = null` (no cache accounting) for these requests, while returning numeric `cached_tokens` for the `assigner` and `data_modeller` requests in the same run, lane, and model.
The app request prefix is append-only stable between consecutive calls, so app-side prefix instability is excluded.

Confidence: high that compaction is NOT the cause; medium that the cause is provider-side rather than an unobserved request attribute the app sets only for this role.

### 10.2 Unresolved branch (the honest weak link)

I could not observe the forwarded HTTP request (headers and body) for a `mechanism_typist` call.
The gateway's spend log stores `proxy_server_request = {}`, so `x-opencode-session` is not visible.
The role-specific request primitives are the conversation id (`providers.py:347-353`, `907`, `917`) and the request body.
Both the app request prefix (Experiment 4) and the conversation id (stable `thread_id`) look correct, so the role-specific trigger must be either:

- provider-side (the upstream or the opencode-go proxy does not cache this conversation), or
- a request attribute I could not see.

### 10.3 Candidates tested and rejected

- Running-summary prefix rewrite (the #348 claim): rejected (Experiments 1 and 2).
- Provider does not cache this model: rejected (Experiment 3).
- Cache convention misread: rejected (Experiment 5).
- Per-turn `SystemMessage(skill)` repeatedly appended in `new_messages` (`analysis/mechanism_typist.py:482,500,508`): NOT sufficient.
  `data_modeller` uses the same pattern (`analysis/data_modeller.py:745,770`) and caches at 85%.
  It remains a design smell to test, but it is not evidenced as the cause.
- The tool-set alternation (no-tools reflection vs tool-bound extraction): NOT sufficient.
  `data_modeller` alternates the same way and caches.
- `x-opencode-session` missing or rotating: not evidenced.
  No transient rotation appears (`record_transient` count 0), and the header is set at `providers.py:907,917`.

---

## 11. Proposed next step and seam

### 11.1 Decisive experiment (cheap, no production change)

Capture the exact gateway-forwarded request for one `mechanism_typist` call and one `assigner` call in the same run, and diff them:

- headers, especially `x-opencode-session` and its value length and format;
- the request body: the `tools` array, `tool_choice`, `messages`, and any cache hint.

Run the gateway with request logging for one minute, or issue a minimal two-request probe on the same session with the same bodies.
If the two requests are identical modulo the known message content, the no-cache is provider-side and belongs upstream.

### 11.2 If provider-side

The seam is not in `compaction.py`.
The design-level lever is `mechanism_typist`'s fresh-input volume.
Options to evaluate, in order:

1. Stop accumulating the full `mechanism_typist` trail across chunks.
   The role could run each chunk on a bounded, de-duplicated context (the system skill once, not three times per chunk), so its per-call fresh input falls.
2. Reduce the chunk prompt size (the reflection prompt repeats the whole chunk).
3. Accept the cost and move the budget axis.

### 11.3 If an app request attribute is the trigger

The seam is the `mechanism_typist` request construction at `analysis/mechanism_typist.py:481-511` and the session append at `app/llm/session.py:868`.
The fix is to normalize the request shape to match `assigner` (a single stable system message, stable tool set per chain).

### 11.4 Acceptance criteria for the next fix

- A live `mechanism_typist` lane over at least 20 calls shows a cached share at least as high as `assigner` in the same run (target >= 60%), measured from the durable usage ledger (`#349`).
- The compaction `apply_staged` decision must not depend on the T4-stripped occupancy.
  Either the occupancy must be measured before the T4 strip, or the cap must key on the real applied prompt size.
- A regression test that reproduces the eval regime (budget 200K, tail 30K, a large but sub-budget recent message) must show the pass converges and the streak resets.

---

## 12. Ticket proposal (not created)

**Title:** EV-33 regressed: the #348 assumption does not hold for `mechanism_typist`; the cache hostility is not a compaction loop

**Body:**
- The #348 fix (`965d91b`) assumed a non-converging compaction pass regenerated the running summary and changed the prefix.
- Live trial `comfyui-1-20261009T110342-1fc05262` (project `0df6cf0c`) shows every `mechanism_typist` pass converges (`occupancy=48109 < budget=200000`, streak reset 5 times, cap 0 times).
- Cache was zero from call 1, 26 calls before the first pass.
- The provider caches the lane concurrently (`assigner` 90.8%, `data_modeller` 85.4%) but returns `prompt_tokens_details = null` for the `mechanism_typist` requests.
- Deliverable: run the request-capture experiment in section 11.1, then apply the provider-side or request-shape fix in section 11.2 or 11.3, with the section 11.4 acceptance criteria.
- Do NOT revert #348: its code path is correct for a tail larger than the budget (the `job_orchestrator` case). Fix the `mechanism_typist` cause separately.

Suggested labels: `bug`, triage per `docs/agents/triage-labels.md`.

---

## 13. Evidence appendix

### 13.1 Trial record

`eval/runs/comfyui-1/comfyui-1-20261009T110342-1fc05262/trial.yaml`:

- `terminal: stopped`, `token_budget: 4000000`, `spent_tokens: 4015116`.
- `spend_by_agent.mechanism_typist`: `cached 0`, `uncached 3,552,532`, `calls 36`.
- `spend_by_agent.assigner`: `cached 216,064`, `uncached 42,457`, `calls 10`.
- `spend_by_agent.data_modeller`: `cached 912,384`, `uncached 236,411`, `calls 18`.

### 13.2 Langfuse per-call cache (mechanism_typist, first 26 calls)

Every one of calls 1 to 26 has `input_cache_read = 0` (JSON null in the gateway log).
The first compaction pass ran at call 26's end (`11:00:50`).
The first non-zero cache appears at `11:06:45`.

### 13.3 Gateway spend-log query used

```
SELECT (metadata->'usage_object'->'prompt_tokens_details'->>'cached_tokens' IS NULL) AS null_c,
       count(*), min(prompt_tokens), max(prompt_tokens)
FROM "LiteLLM_SpendLogs"
WHERE "startTime" > '2026-10-09 10:49' AND model LIKE '%deepseek%'
GROUP BY 1;
```

Result: 117 rows numeric, 62 rows JSON null (the `mechanism_typist` misses).

---

# Part 2: context-window mining, the growth root, and the request capture

**Date:** 2026-10-09 (second pass).
**Scope:** deep context analysis of `mechanism_typist` and `hunting_orchestrator`, the entity lifecycle, the rooted growth cause, a live request-capture experiment, and the coupling to `docs/design/compaction-caching-investigation.md`.
**Method:** read-only Langfuse observation mining, plus a bounded live gateway probe (a few dozen cheap calls, no production change).

Working hypothesis (operator): a high cache miss is NOT explained MAINLY by compaction.
Part 1 already showed compaction is not the trigger for `mechanism_typist`.
Part 2 examines the context growth and the provider cache directly.

## 14. Per-section context breakdown

### 14.1 mechanism_typist

Data source: Langfuse `input` message lists for run `bf7bed51-...:mechanism_typist`. Token share from the per-call usage (cache=0, so `input` equals the total prompt).

One chunk runs three calls: reflection (free text), systems extraction, services linking (`mechanism_typist.py:481-511`).
The token composition at call 8 (six chunks in, `input=58189`):

| section | chars | share | note |
|---|---|---|---|
| USER prompts | 97,431 | 37.2% | the three per-chunk prompts, accumulating and internally duplicated |
| ASSISTANT | 90,276 | 34.5% | the reflection prose and the extraction tool calls |
| SKILL (`SystemMessage`) | 65,568 | 25.1% | 8 byte-identical copies of an 8,056-char skill |
| SCHEMA (`L1DeltaBatch`) | 5,539 | 2.1% | one copy, request-time only |
| TOOLRESULT | 2,776 | 1.1% | small structured answers |

Observed facts:

- The skill is re-added to `new_messages` on EVERY call (`mechanism_typist.py:482,500,508`), so the checkpointed trail holds one identical copy per call, three per chunk.
  At call 8 that is 8 copies (25.1% of the window).
- The reflection prompt repeats the defined-systems block and the vocabulary (`mechanism_typist.py:318-326`).
  The systems prompt repeats the same block and vocabulary, then embeds the ENTIRE reflection prose (`mechanism_typist.py:329-357`).
  The linking prompt embeds the reflection prose again (`mechanism_typist.py:360-384`).
  Measured at call 5: the reflection prose is 66.7% of the systems prompt and 78.1% of the linking prompt; the two prompts share 27 identical lines (about 1,945 chars) of vocabulary and defined-systems.
- The reflection prose therefore appears three times per chunk: once as the assistant trail message, once inside the systems prompt, once inside the linking prompt.
- The per-chunk user prompts grow call to call: reflection 4,007 to 24,334 chars, systems 9,103 to 15,012, linking 7,775 to 10,929.

### 14.2 hunting_orchestrator

Data source: Langfuse `input` message lists for session `6480f42b-...:hunting_orchestrator` (21 calls, `input_cache_read=0` on every call, zero folds, max context 72,240 tokens).

Token composition at call 9 (`input=36838`):

| section | chars | share | note |
|---|---|---|---|
| TOOLRESULT | 56,589 | 36.0% | `graph_view` row dumps kept verbatim (11,607 + 17,515 + 9,874 chars) |
| ASSISTANT | 38,204 | 24.3% | the orchestrator's thinking, persisted |
| USER frames | 32,916 | 20.9% | the per-pair phase frames |
| SKILL (`_gate_skill`) | 16,955 | 10.8% | ONE copy (ephemeral `system_prompt`, Lane A) |
| SCHEMA (6 tools) | 12,633 | 8.0% | constant, request-time only |

Observed facts:

- The hypothesise frame is 28,660 chars, of which the single `Read-only graph surface (index cards)` line is 23,400 chars (82%).
  That line is `inp.surface`, a Python `repr` of the whole target's L1 index cards (`hunting/llm.py:467,470`).
- The same 23,400-char surface is re-rendered into the hypothesise frame of EVERY pair (observed at calls 1, 10, 13, and later), and the frames stay in the trail.
- The `L1_ONTOLOGY_PRIMER` (`llm.py:171-189`, about 1,139 chars) is rendered at the top of all three phase frames (`llm.py:467,562,604`), so it is triplicated per pair.
- The graph-view tool results are kept verbatim and grow without bound; at call 9 they are 36% of the window.
- The gate skill is NOT repeated: it rides the ephemeral `system_prompt` set once (`actors.py:705-726`, the #187 fix). This is the correct Lane A pattern, and `mechanism_typist` does NOT follow it.

## 15. Entity lifecycle table

`grows` means the entity's token footprint grows across the run.
`dedup` means an in-run deduplication exists.

| entity | produced by | enters | grows | dedup | belongs in context |
|---|---|---|---|---|---|
| mechanism_typist skill | `_load_skill()` file | `SystemMessage` per call (`mechanism_typist.py:482,500,508`) | yes, O(calls) copies | only at a fold, region only (`compaction.py:541-559`) | NO. Bind once as `system_prompt` (Lane A). |
| reflection prose | LLM (schema=None) | assistant trail + systems prompt + linking prompt | yes, 3 copies/chunk | no | Consumable. Keep once at most. |
| systems/linking prompt | `_systems_prompt`/`_linking_prompt` | `HumanMessage` per call | yes, and duplicates the prose | no | Chunk-local. Not needed on later chunks. |
| chunk assets | analysis feed | reflection prompt + summarised | yes | no | Ingestion only. |
| defined-systems block | `read_l1_inventory` | reflection + systems prompts (2x) | yes, grows with systems | no | A summarised pointer, not a full re-render. |
| assistant extraction tool calls | LLM | trail | yes | no | Foldable. |
| structured tool results | tools | trail | yes, small | no | Foldable. |
| `L1DeltaBatch` schema | ToolStrategy | request `tools` param | constant | n/a | Request-time only. |
| running summary | compaction pass | trail at a fold | no | replaced | Yes. |
| hunting gate skill | `_gate_skill()` file | `system_prompt` once | no | n/a | Yes (Lane A). |
| L1 ontology primer | constant | top of every phase frame (3x/pair) | yes, O(pairs) copies | no | Small, but the repeat is avoidable. |
| full surface index cards | surface read | every hypothesise frame (23,400 chars) | yes, O(pairs) copies | no | Reference or summarise, do not re-render. |
| pair frame | `_compose_*` | `HumanMessage` per phase turn | yes | no | Per-pair. |
| prior minted keys | `LoopLedger` | every hypothesise frame | yes | no | Grows; a bounded recent set would do. |
| graph_view tool results | agent reads | tool messages | yes (11-17K chars each) | no | Offload or bound (D8-style). |
| six tool schemas | tool surface | request `tools` param | constant | n/a | Request-time only. |
| assistant reasoning | LLM | trail | yes | no | Foldable. |

## 16. Rooted cause: why the context is so extensive

The growth is not one bug.
It is the combination of one design decision and four missing bounds.

1. **One unbounded per-run session thread.** Each analysis proposer and the hunt orchestrator run as one stateful session for the WHOLE run (`#94`; `session.py` resumes one checkpointed thread). Every model call re-sends the entire run's history. There is no per-chunk or per-pair reset, so the cost of a call is O(run length). This is the structural multiplier.
2. **Large static content is re-added per call instead of bound once.** `mechanism_typist` re-appends its skill as a `SystemMessage` on every call (`mechanism_typist.py:482,500,508`); at call 8 that is 25.1% of the window. The correct Lane A pattern already exists (`hunting_orchestrator`, `actors.py:705-726`) and is not used here.
3. **Per-turn content is duplicated within a turn.** The `mechanism_typist` reflection prose is embedded in two later prompts and also kept as an assistant message; the defined-systems block and vocabulary are rendered into two prompts. A single chunk's material is counted up to three times. The hunt orchestrator repeats the 23,400-char surface dump in every pair's hypothesise frame.
4. **Nothing is bounded or offloaded until a fold.** Tool results (`graph_view` rows, 36% of the hunt window), assistant reasoning, and prior minted keys accumulate verbatim. The only dedup is `_dedup_system_messages`, which runs on a fold, only over the region, and never over the exempt tail.
5. **The fold is a head rewrite.** When the bound is finally hit, compaction removes old messages from the front and inserts the summary, so the cache prefix breaks from the first removed message. This is inherent to fold-based compaction.

So the context is extensive because a long-horizon thread re-sends everything, and the prompt builders re-render large static and derived context every turn rather than binding it once or referencing it.
Compaction is the only bound, and it both fires late and rewrites the head.

## 17. Request-capture experiment (live, gateway mode)

Method: run short probe scripts inside the live agent container (`docker exec`), which shares the live gateway (`LLM_GATEWAY_URL=http://localhost:4000`) and credentials.
The probes rebuild the model through the production `build_chat_model`, replay the EXACT live request bodies captured in Langfuse, and read `usage_metadata.input_token_details`.

### 17.1 The app request is sound

| probe | body | transport | observed `cache_read` |
|---|---|---|---|
| replay live call 1 | exact live [system(skill), user] | gateway, stream | 2,816 of 2,830 input tokens |
| replay live call 1 | same, live session id | gateway, stream | 2,688 of 2,830 |
| replay live call 2 | exact live 5-message trail | gateway, stream | 8,448 of 8,456 |
| replay live call 1 x10 | same body scaled to ~11K | gateway, stream | 11,136 of 11,155 |

The exact live bodies cache near-completely when replayed.
The app request is therefore cacheable and correct.

### 17.2 The gateway is not the cause

- The gateway forwards `x-opencode-session` for `opencode-go/*`.
  Verified in the pinned source: `litellm/proxy/litellm_pre_call_utils.py:773-789` (`_get_forwardable_headers` keeps `x-*` except `x-stainless*`) and `:899-910` (`add_headers_to_llm_call_by_model_group`).
- The client sets the header at construction: a probe printed `default_headers = {'x-opencode-session': <id>, 'x-opencode-client': 'polymerhus'}` (`providers.py:347-353,907,917`).
- The same body caches in BOTH gateway mode and direct mode (probe 1).

### 17.3 The wire serialization is deterministic

- `ReasoningPreservingChatOpenAI._get_request_payload` (`providers.py:719-757`) re-serializes the messages and re-emits reasoning.
- Dumping the payload for the exact live call-2 trail three times gave the SAME SHA1 (`7ca004e0e1b3`) each time, with `reasoning_content` present on one message.
- No non-deterministic field appears in the serialization.

### 17.4 The provider's streamed usage is FLAKY

The reproduction of the live null is inconsistent across probes:

- One probe (tool bound + stream) returned `input_token_details = null` on two calls (`input=8377` matched the live call 2 exactly).
- A repeated probe of the SAME shape (tool bound + stream) returned numeric `cache_read` (2,048 then 4,608).
- The no-tools stream and both non-stream shapes returned numeric values in the repeated probe.

Inference: the provider (or the proxy) intermittently omits `prompt_tokens_details` from the streamed usage.
When it is omitted, Langfuse and the usage ledger record `cache_read = 0`.
This is a provider-side reporting/behavioural nondeterminism, not an app request attribute.

### 17.5 Verdict

The live 0% cache is NOT caused by the app request, the gateway, the session header, the tool binding, or the streaming mode.
The exact live bodies cache when replayed, and the wire bytes are deterministic.
The remaining variation is provider-side and time-dependent.
This confirms Part 1's provider-side finding and refutes the "unobserved request attribute" branch left open in section 10.2.

Weak link: the probe ran after the live trial, so the provider cache state differs from run time. The replay result shows the body is cacheable; it cannot prove the cache was warm at run time. The flaky-reporting result is the best explanation the evidence supports.

## 18. Checkpointing-algorithm inspection

The operator asked whether a narrow bug in the context checkpointing algorithm causes per-call byte instability.

Findings:

- The trail is append-only between folds. Langfuse shows calls 2..N as strict supersets of the previous call's messages (verified for calls 1..8).
- The wire serialization is deterministic (section 17.3), so no field reorders or churns on the wire.
- `_replay_reasoning` re-persists the whole trail with reasoning via `update_state`, but it preserves message ids (`model_copy`), and `add_messages` replaces in place, so the committed trail is idempotent (`reasoning.py:255-304`, `session.py:427-459`).
- The retry path rotates only the provider conversation id, never `thread_id` (`transient.py:147-152`), and the live run had zero transient retries.
- The one structural checkpointing defect is NOT in the checkpointer but in prompt construction: the `mechanism_typist` re-adds the skill `SystemMessage` per call, so the checkpointed trail accumulates O(calls) identical system messages. `_dedup_system_messages` (`compaction.py:541-559`) collapses them only on a fold and only in the region, so the tail keeps duplicates.
- A probe-only artifact: msgpack deserialization of `L1DeltaBatch` is blocked without `allowed_msgpack_modules`; production sets `LANGGRAPH_STRICT_MSGPACK=false`, so it is not a production bug.

Conclusion: no narrow checkpointing bug was found.
The "narrow local bug" is the per-turn prompt re-construction (repeated skill, duplicated prose, re-rendered surface), which inflates the checkpointed trail.

## 19. Coupling to the optimal-threshold report

The companion report `docs/design/compaction-caching-investigation.md` recommends per-agent thresholds (`mechanism_typist` 0.75-0.80, `data_modeller` 0.40-0.50) and states a clear warning: "Fix the cache first; then raise the thresholds."

Coupling:

- The threshold recommendation's uncached-reduction half is CONDITIONAL on the provider cache working between folds.
  My live probes show the body is cacheable and the provider's REPORTING is flaky, so the reported cache fraction is not a reliable input to the decision.
  The "fix the cache first" warning stands, but the fix is provider-side or a measurement fix, not an app-side request fix.
- The context-growth root (section 16) is the independent, app-side lever.
  Removing the per-turn re-adds and duplication lowers BOTH cached and uncached input, at any threshold, and lowers `capped_tokens` even if the cache never reports.
  This is a no-regret change.
- Ordering:
  1. Do the app-side context restructuring first (S1 ephemeral skill plus de-duplication plus a single surface reference).
     It is cache-independent and shrinks every call.
  2. Characterize the provider cache reporting (a controlled repeat of section 17 with a workload representative of a live run) before trusting any cache fraction.
  3. Only then decide the per-agent thresholds.
     If the cache truly works, raising them helps; if the reported zero is real, raising them hurts (the report's own inversion table, lines 413-422).
- Do NOT couple the threshold change to the #348 compaction cap.
  #348 does not fire for `mechanism_typist` (Part 1).

## 20. Recommended next work

1. App-side, no-regret: bind the role skill once via `system_prompt` for the analysis proposers (the Lane A pattern, `actors.py:705-726`), and delete the per-call `SystemMessage(skill)` from `mechanism_typist.py:482,500,508`.
2. App-side: stop embedding the reflection prose in the systems and linking prompts; pass it once or summarised.
3. App-side: render the L1 surface once per pass (or reference it), not per hypothesise frame; bound or offload `graph_view` tool results.
4. Measurement: repeat the section 17 probe against a live run to quantify how often the provider omits `prompt_tokens_details`, and file a provider-side bug if the omission is confirmed at scale.
5. Design: amend D7 to allow a budget-aware or profile-specific replay tail (already the companion report's S2), because a fixed 30K tail plus the re-rendered context is what makes the fold fire so often.

Acceptance criteria:
- The per-call prompt for `mechanism_typist` carries ONE skill copy and no duplicated prose; the token share of the skill falls from about 25% toward a constant.
- A live `mechanism_typist` lane over 20 calls has a context-growth slope materially below the observed 8,260 tokens per call.
- The cache fraction is read from a source that distinguishes "provider omitted the field" from "cache read zero" (or the omission is fixed upstream).
