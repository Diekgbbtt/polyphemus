# Compaction caching investigation (investigate/compaction-caching)

Investigation-only. No production code was changed. Base: `dev` at 70b7b5e.
Question: is the compaction design as cache-friendly as it could be, and are there
cheap, safe context-restructuring wins that do NOT introduce other qualitative
defects?

Status: complete. Every ledger item is resolved below.

## Corrections to the brief

- The brief names `docs/design/session-cache-measurement-348-adr.md`. That file does
  not exist in this worktree. The pre-#348 live evidence lives in
  `docs/design/compaction-cache-convergence-348-adr.md:33-47`.
- The brief cites a `mechanism_typist` cache fraction of `0.161`. The ADR cites
  `30.6%` cached (0.306) for jetlinks-1 #2 (`compaction-cache-convergence-348-adr.md:37`).
  The 0.161 figure is not found anywhere in the repo. The report uses the ADR numbers.

## Ledger (all resolved)

| id | item | status |
|---|---|---|
| L1 | Map compaction + context layout per stateful agent | done |
| L1a | `compaction.py` staged layout | done |
| L1b | `summary.py` summary shape | done |
| L1c | `session.py` turn seam + system_prompt channel | done |
| L1d | per-agent prompt builders | done |
| L1e | system prompt persistence (trail vs ephemeral) | done |
| L2 | Task-profile classification; is one-size policy wrong? | done |
| L3a | Keep system_prompt / first human byte-stable | done |
| L3b | Deep-analysis: fold mid-trajectory after the report | done (rejected) |
| L3c | Move volatile content to the tail | done (already satisfied / rejected) |
| L3d | Append-only prefixes | done (already satisfied; front-fold inherent) |
| L3e | Other strategies found | done |
| L4 | Quantify + rank | done |
| L5 | Low-hanging+safe vs needs-decision vs rejected | done |

## 1. Per-agent context-layout map

The session seam builds one `create_agent` graph per turn (`session.py:179-228`).
The `system_prompt` kwarg is passed to `create_agent` (`session.py:216-217`); every
other message travels in `new_messages` and is appended to the checkpointer trail.
There are two distinct lanes, and the lane decides everything about the head.

### Lane A - stable skill on the ephemeral `system_prompt` (NOT persisted)

`create_agent` prepends the system prompt at each model invocation and never persists
it into the checkpointer (`hunting_agent.py:122-138`, `actors.py:705-710`). The head is
therefore byte-stable and outside the compactable region.

| agent | role_id | system source | evidence |
|---|---|---|---|
| hunt-orchestrator (actor) | `hunting_orchestrator` | `_gate_skill()` (16744B) | `actors.py:721-726` |
| hunting-hunter (harness) | `hunting_hunter` | `hunting-agent.md` + `examples.md` (26241B) | `hunting_agent.py:526,545` |
| pod-runner | `pod_runner` | `pod-runner.md` (4382B) | `pod/agents.py:133-138` |
| pod-triager | `pod_triager` | `pod-triager.md` (4217B) | `pod/agents.py:176-183` |
| recon job-orchestrator (gateway actor) | `job_orchestrator` | `auth-gateway.md` (5459B) | `orchestrator_agent.py:382-399` |

Layout of the persisted trail (tool-calling agents):
`[first human (grounding/prompt)] [AI(tool_calls) Tool ...] [AI(tool_calls) Tool ...]`.
Each turn appends only new ToolMessages/answers (`hunting_agent.py:636`), so between
compactions the request is strictly append-only.

### Lane B - stable skill as a `SystemMessage` in `new_messages` (persisted, repeated)

The skill is re-added to the message list on every LLM call, so the checkpointer
trail accumulates one identical `SystemMessage(skill)` per call. It is byte-stable
(memoized), so it does not invalidate the cache, but it is repeated and grows the
window.

| agent | role_id | system source | evidence |
|---|---|---|---|
| assigner | `assigner` | `_system_prompt(mode)` (5344B skill) | `assigner.py:522`, `:311-331` |
| mechanism-typist | `mechanism_typist` | `technical-system.md` (8066B), 3 calls per chunk | `mechanism_typist.py:482,500,508` |
| data-modeller | `data_modeller` | `data-plane.md` (9165B), 2 calls per chunk | `data_modeller.py:745,770`, `:670-674` |
| recon triager | `triager` | `writing-observations.md` (9624B) | `pod.py:784-785` |

The compaction pass collapses these duplicates to the first copy via
`_dedup_system_messages` (`compaction.py:541-559`), pinned by
`tests/test_llm_compaction.py:556-587`.

### The compacted trail (both lanes)

A pass stages: retained region groups (systems, retained tool pairs, orphan tools),
then any partial-fold remainder, then `SystemMessage(new_summary.to_text())`, then
the D7 byte-identical tail (`compaction.py:783-786`). On a fold the model applies
`RemoveMessage(REMOVE_ALL_MESSAGES)` plus the staged trail (`compaction.py:1176-1178`),
so the head is rewritten.

- In the analysis lane (no tools, region humans folded) the compacted trail is
  `[SystemMessage(skill), SystemMessage(summary), tail]`; pinned by
  `tests/test_llm_compaction.py:722-728`.
- In the tool lane, retained (newest) tool groups come first, then the summary of the
  older folded content, then the tail.

### What changes each turn

- Between compactions: only a tail append (new human / tool result). The previous
  request is a strict prefix of the next, so the provider prefix cache hits the whole
  previous request.
- A transient retry rotates only the provider conversation primitive
  (`<thread_id>#r<attempt>`, `actors.py:315`), never `thread_id`, so checkpointer
  memory is retained (`transient.rotate_conversation`; session.py:538-541). A rotated
  `x-opencode-session` may cost the provider-side cache, but the trail itself is
  unchanged.
- A compaction fold (fires only over budget) rewrites the head and invalidates the
  prefix. This is the only cache-invalidating event besides the fresh tail.

### D7 tail + running-summary regeneration

- The D7 tail is a token-walked suffix (default 30K) reserved byte-identical for
  reasoning profiles (`compaction.py:400-425,657-664`). It is exempt from summarise and
  offload. An oversized tail AIMessage is bounded, so byte-identity is not absolute
  for that message (`compaction.py:581-637`).
- The running summary is a `SystemMessage` inserted immediately before the tail
  (`compaction.py:784`) and regenerated on every pass. Pre-#348 that happened on every
  call; post-#348 a pass that leaves the thread over budget counts toward the
  consecutive-pass cap (3) instead of resetting the streak, so the summary stops
  regenerating and the trail stabilises (`compaction.py:1154-1170`, ADR #348).

## 2. Task-profile classification

| profile | agents | shape | essential output | one-size fit |
|---|---|---|---|---|
| P1 incremental structured extraction | assigner, mechanism_typist, data_modeller | no tools, structured output per chunk, one thread per run | the structured delta (already written to the graph) | `keep_last_tools` is inert (no tools); the `replay_keep_tokens`=30K tail is the profile-sensitive knob |
| P2 tool-calling intense / sparse evolution | hunting_orchestrator, hunting_hunter, pod_runner, recon job_orchestrator | many small tool round-trips | a final structured verdict/spec | fits: ephemeral stable head + tail preservation is exactly right |
| P2b critic / medium | pod_triager | one structured turn per lap over a verbatim note | the triager decision | fits |
| P3 few-call workflow-step | recon triager (per witness) | short per-pod thread, stable skill | the observation batch | threads are short; compaction rarely fires |

Assessment: the one-size policy is not wrong for any profile in a load-bearing way.
The only profile-sensitive gap is P1's exempt reasoning tail: a 30K tail is reserved
whenever the capability profile reports a reasoning surface, but P1 agents emit
structured output and their cross-chunk reasoning replay value is low. That is a
design question (see S2), not a defect.

## 3. Strategy assessment

The decisive mechanical fact: the provider prefix cache hits the longest common token
prefix. A fold removes old messages from the front, so the head breaks at the first
removed message and the summary's position (front vs tail) is cache-neutral. The
rejected-alternatives entry in ADR #348 already states this (`compaction-cache-convergence-348-adr.md:55`).

### S1 - Move Lane B skills to the ephemeral `system_prompt` (LOW-HANGING, SAFE)

Adopt the Lane A pattern for assigner, mechanism_typist, data_modeller, recon triager.
`stateful_turn` already threads `system_prompt` (`session.py:871`), so this is a call-site
change.

- Yield: removes `(calls - 1)` copies of the skill from the trail. Sizes: assigner
  1300 tok, mechanism-typist 2000 tok (x3 per chunk), data-modeller 2300 tok (x2 per
  chunk), recon triager 2400 tok. This delays the first over-budget fold and removes
  the `_dedup_system_messages` rewrite trigger.
- Implementation risk: low.
- Defect risk: low. Same content, same channel semantics; must confirm structured
  output and the blackloop recovery path are unaffected.

### S2 - Profile-specific exempt tail (NEEDS DECISION)

Set `replay_keep_tokens` (or the profile that gates it) per profile: a smaller or zero
tail for P1 structured roles, keeping 30K for P2 reasoning agents. This lets P1 folds
reclaim more and converge sooner.

- Yield: moderate for P1 only.
- Implementation risk: low (already a builder parameter, `compaction.py:1341-1362`).
- Defect risk: medium: it is a D7 amendment; losing last-turn reasoning replay can
  reduce cross-chunk coherence. Needs an A/B on P1 output quality.

### S3 - Move the running summary to the tail / append-only folding (REJECTED)

Append-only folding never shrinks the window, which defeats compaction. Moving the
summary to the tail does not help: the front-fold still breaks the prefix. Rejected on
both counts; matches ADR #348's rejected alternative.

### S4 - Aggressively fold the P1 mid-trajectory after each structured output (REJECTED)

Folding after every chunk means a full re-prefill every chunk, which raises `uncached`
input and therefore `capped_tokens`. The current "fold only when over budget" is the
cache-optimal choice. Rejected for cache reasons.

### S5 - Raise the compaction threshold / make it role-specific (HIGHEST YIELD, CONFIG-LEVEL)

The eval sets `LLM_COMPACTION_THRESHOLD=0.2`, so the budget is 200K
(`compaction-cache-convergence-348-adr.md:19`). At that threshold a P1 thread crosses
budget every 1-2 chunks, so a fold fires almost every chunk. Each fold rewrites the
head and forces a full re-prefill, which is why mechanism_typist stayed at 30.6%
cached even with the #348 cap. A higher threshold keeps the trail append-only longer,
so the cache prefix grows, while cached input is free on the budget axis
(`capped_tokens = generated + uncached`, EV-32/#347).

- Yield: potentially high; this is the dominant lever.
- Implementation risk: none in app code (it is a knob; the app is cache-sane at any
  threshold by design, per the #348 ADR).
- Defect risk: low, but bounded by the provider's context limit and by the cache TTL:
  if inter-call gaps exceed the provider TTL, a larger window is re-prefilled in full.
- Needs an experiment: measure cached/uncached per role at thresholds 0.2, 0.5, 0.9 on
  one P1 trial and one P2 trial, and confirm requests stay under `max_input_tokens`.
  Do not run live LLM experiments in this task.

### S6 - Keep `system_prompt` and the first human message byte-stable (ALREADY SATISFIED)

- Lane A: the system prompt is ephemeral and byte-stable; the first human is the
  per-dispatch instance data and is never rewritten (`hunting_agent.py:369-383`).
- Lane B: the skill system message is byte-stable and stays first (systems stage in
  original order, `compaction.py:735-739`); the first human is volatile by nature (a
  new chunk) but is append-only, so it never invalidates the cache.
- No timestamps or ids appear in any role prompt; the volatile inventory and chunk ride
  the user turn (e.g. `assigner.py:315`, `data_modeller.py:740-746`).

No action needed.

### S7 - Summary placement after retained tool groups (QUALITY, NOT CACHE)

When retained tool groups exist, the summary of the older folded content is staged
after them (`compaction.py:783`). The order is semantically inverted (old summary after
newer messages). It is cache-neutral (the fold already broke the prefix) and is pinned
by D12/tests. Flagged as a separate quality observation; do not change without a
targeted test and a design note.

## 4. Ranked strategy table

| rank | strategy | cache yield | impl. risk | defect risk | verdict |
|---|---|---|---|---|---|
| 1 | S5 raise / make role-specific the compaction threshold | high | none (config) | low (context limit, TTL) | do, via experiment |
| 2 | S1 ephemeral `system_prompt` for Lane B skills | low-moderate | low | low | do |
| 3 | S2 profile-specific exempt tail | moderate (P1) | low | medium (D7) | needs decision + A/B |
| - | S6 stable head | already done | - | - | no action |
| - | S3 summary to tail / append-only | none | - | - | rejected |
| - | S4 aggressive P1 per-chunk fold | negative | - | - | rejected |
| - | S7 summary ordering | none | medium | medium | observe only |

## 5. Recommendation

Ordered, with minimum risk first:

1. Take S1 now. It is a safe, mechanical call-site change on the four Lane B agents,
   and it removes a class of head-rewrite and repeated context.
2. Confirm S5 with the named experiment before changing any eval threshold. It is the
   highest-yield lever and requires no app code, but its benefit is bounded by the
   provider cache TTL and the context limit.
3. Put S2 through a design decision (amend D7 for a per-profile tail) and an A/B on P1
   output quality before implementing.
4. Do not pursue S3 or S4: they are proven cache-neutral or cache-negative.
5. Leave S7 as a recorded quality observation.

Bottom line: the compaction design is already near-optimal on the cache axis after
#348. The only clearly low-hanging code win is S1. The largest remaining lever is the
folding frequency (S5), which is an environment/design decision, not a compaction
defect.

---

# Follow-on: the optimal compaction threshold per agent

Directed follow-on. Same worktree, same branch, investigation only. No production
code changed, no PR.

Goal: find the optimal context-window compaction threshold PER AGENT, grounded in real
Langfuse samples, and express the expected reduction in compaction cycles and in the
uncached spectrum.

## Follow-on ledger

| id | item | status |
|---|---|---|
| F1 | Pull per-agent context-growth trajectories from Langfuse | done |
| F2 | Reconstruct the uncompacted counterfactual growth | done |
| F3 | Identify each agent's phase boundaries from its graph/nodes | done |
| F4 | Reconcile with the post-#348 live evidence (comfyui-1) | done |
| F5 | Per-agent optimal threshold + confidence + backing + cycle/uncached reduction | done |
| F6 | Critical-thinking pass (assumptions, weak links) | done |

## Method and data provenance

Read-only Langfuse queries via the documented CLI:

```
npx -y langfuse-cli@latest --env /Users/diekgbbtt/polymerhus/.env \
  api observations list --limit 1000 --all --max-items 6000 \
  --fields core,basic,usage,trace_context \
  --from-start-time 2026-10-08T00:00:00Z --json
```

Per-generation `usageDetails`: `input` = uncached input, `input_cache_read` = cached
input, `output` = generated, `output_reasoning` = reasoning subset. Tags carry
`["session", <role>, <run_id>]`; `sessionId` = `<run_id>:<agent>` (the brief's schema
confirmed). Total prompt per call = `input + input_cache_read` (the only reading
consistent with a call of `input=5316, input_cache_read=167040`).

Runs inspected:
- `bf7bed51-de26-41a0-a75b-981f691b5b7f` = comfyui-1, the post-#348 capped trial
  (recon phase, 2026-10-09, ~11:03Z to 11:46Z). Its `mechanism_typist` session sums to
  `uncached 8,181,473 / cached 1,398,656`, exactly the brief's project cumulative.
- `0ab40280-bde0-435e-add3-41686c131312` = a second recent recon run, same roles.
- `6480f42b-9c53-4cdc-9e1e-eb415e0dc3d7` = a hunting run (orchestrator + hunters + pods).

## Per-agent context-growth reconstruction (observed)

`g` = median positive per-call growth (tokens); folds = observed sawtooth resets.

| agent | run | calls | growth g/call | observed uncached | observed cached | cache frac | max context | folds | uncompacted final |
|---|---|---|---|---|---|---|---|---|---|
| mechanism_typist | comfyui-1 | 81 | 8,260 | 8,181,473 | 1,398,656 | 0.146 | 218,550 | 5 | 663,474 |
| mechanism_typist | 0ab40280 | 81 | 14,475 | 8,841,418 | 1,349,248 | 0.132 | 230,969 | 7 | 1,160,714 |
| data_modeller | comfyui-1 | 38 | 10,257 | 552,218 | 3,221,376 | 0.854 | 213,950 | 3 | 383,612 |
| data_modeller | 0ab40280 | 37 | 6,784 | 743,905 | 3,193,216 | 0.811 | 213,939 | 1 | 248,311 |
| assigner | comfyui-1 | 25 | 4,726 | 162,201 | 1,594,240 | 0.908 | 165,296 | 0 | 118,204 |
| assigner | 0ab40280 | 25 | 4,863 | 903,476 | 861,440 | 0.488 | 167,054 | 0 | 121,480 |
| hunting_orchestrator | 6480f42b | 21 | 2,322 | 912,544 | 0 | 0.000 | 72,240 | 0 | 56,750 |
| hunting_hunter | 6480f42b | 9 | 1,708 | 95,135 | 316,288 | 0.769 | 94,651 | 0 | 36,822 |
| recon pod/triager | comfyui-1 | 1-2 per pod | ~200 | tiny | tiny | 0.74-0.92 | < 5K | 0 | < 5K |

Key observations:

1. The eval threshold is 0.2, so the budget is `0.2 * 1,000,000 = 200,000` tokens
   (`compaction-cache-convergence-348-adr.md:19`). The sawtooth max for the folding
   agents sits at 214K to 231K, i.e. just past the budget, as expected.
2. Only `mechanism_typist` and `data_modeller` fold at this budget. `assigner`,
   `hunting_orchestrator`, `hunting_hunter`, and the pod/triager never reached 200K.
3. `mechanism_typist` is the only large fresh-input burner; its 14.6% cache is the
   outlier. `data_modeller` and `assigner` cache well (81-91%).

## Counterfactual uncompacted growth

For an append-only session, the uncompacted context at call n is
`first + (n-1)*g`. The "uncompacted final" column above is that value at the last call.
The counterfactual is defensible because the first 25 `mechanism_typist` calls grew
linearly with slope 8,064/call before any fold (`input` 2,714 at call 1 to 204,327 at
call 26).

- comfyui-1 mechanism_typist: uncompacted final 663K. Under the 1M hard limit, so a
  threshold above 0.66 would have produced ZERO folds for this run.
- 0ab40280 mechanism_typist: uncompacted final 1.16M. This EXCEEDS the 1M hard limit,
  so this run genuinely required at least one fold. This is the important contrast:
  "never compact" is not safe in general; a threshold must still bound the context.
- data_modeller and assigner: uncompacted finals 118K to 384K, far under the limit.

## Phase-boundary analysis

The compaction trigger fires at `before_model` when the post-response occupancy is at
or over the budget (`compaction.py:1077-1110`). A fold lands at the call AFTER the
threshold is crossed, and the pass inserts its regenerated summary mid-trail
(`compaction.py:783-786`), so a fold that fires mid-phase bisects the phase.

Natural phase boundaries (from the workflow code):

| agent | phase (seam) | calls/phase | evidence |
|---|---|---|---|
| assigner | one chunk (AGGREGATES pass) | 1 | analysis CONTEXT: `assigner -> mechanism_typist -> data_modeller` per chunk |
| mechanism_typist | one chunk: reflection -> extraction -> linking | 3 | `mechanism_typist.py:478-511` |
| data_modeller | one chunk: reflection -> extraction | 2 | `data_modeller.py:738-775` |
| hunting_orchestrator | one pair: hypothesise -> ratify -> note | 3 | hunting CONTEXT: node-per-phase machine (#167) |
| hunting_hunter | one hunt step | 1 | `hunting_agent.py:539-636` turn-by-turn loop |
| pod_runner | one stretch | 1 `create_agent` turn | `pod/agents.py:87-142` |
| pod_triager | one lap | 1 turn | `pod/agents.py:145-200` |
| recon triager | one pod witness | 1-2 turns | `pod.py:775-808` |

Observed fold alignment (fold call index modulo calls-per-phase; 0 = clean boundary):

- comfyui-1 mechanism_typist folds at {26, 46, 59, 68, 77}; modulo 3 = {2, 1, 2, 2, 2}.
  NONE landed on a phase boundary. All 5 bisected a chunk.
- 0ab40280 mechanism_typist folds at {16, 23, 31, 40, 50, 63, 74}; modulo 3 =
  {1, 2, 1, 1, 2, 0, 2}. Six of seven bisected a chunk.
- data_modeller folds at {31, 33, 36} (mod 2 = 1, 1, 0) and {35} (mod 2 = 1). Mostly
  mid-phase.

So the observed behaviour confirms the operator's premise about misalignment: at
threshold 0.2, roughly 90% of folds land mid-phase.

But why a fixed threshold cannot fix this: the post-fold floor `F` drifts within a
run. comfyui-1 mechanism_typist's floor after each fold rose from 47,719 (call 27) to
60,395, 55,507, 68,009, 73,283. Because both `F` and the per-chunk growth vary, an
exact phase-aligned fold needs a phase-AWARE trigger, not a fixed token threshold. A
fixed threshold can only reduce the NUMBER of folds, not guarantee their alignment.
This is a load-bearing limitation of the "just pick a threshold" approach.

## The cache-regime finding (the critical weak link)

The operator's premise is that aligning folds to phase boundaries maximises the stable
prefix and therefore the cache. The live evidence tests the necessary condition: does
the provider prefix cache actually hit between folds on a stable, append-only prefix?

Answer: NO, not reliably, and for the largest grower it does not hit at all.

- comfyui-1 `mechanism_typist`: calls 1 to 41 all show `input_cache_read = 0` even
  though only one fold occurred (at call 26) and the gaps were 4 to 44 seconds. The
  capped trial's own 36 calls had 0 cached (the brief). Zero cache on 41 mostly
  append-only calls cannot be explained by fold frequency.
- hunting run `hunting_orchestrator`: 21 calls, 3 to 17 seconds apart, append-only,
  ZERO folds (max 72K, well under the 200K budget), and `input_cache_read = 0` on
  every single call. This falsifies both the TTL explanation and the fold explanation.
- In the SAME hunting run, `hunting_hunter` cached 77-86% on the same provider at the
  same time. Two structurally similar Lane A agents diverge 0% vs 80%.

Implication: the observable cache fraction is not determined by folds and prefix
stability alone. The #348 ADR's model (summary regeneration breaks the prefix, cap the
regeneration and the cache returns) is necessary but not sufficient. Something else
agent-specific suppresses caching for `mechanism_typist` and `hunting_orchestrator`.
Candidate causes (unverified): a provider/relay cache behaviour keyed by something
other than the stable `x-opencode-session` (`providers.py:351`); a structured-output
request shape the cache does not serve; or per-call byte instability in the replayed
reasoning prefix. This is the single highest-value open question.

Consequence for the threshold decision: it INVERTS the recommendation depending on the
regime.

- If the cache works between folds (the design intent), the uncached spectrum is
  dominated by full re-prefills at folds. Fewer folds is strictly better: raise the
  threshold.
- If the cache does not work (the observed comfyui-1 state), the uncached spectrum is
  the sum of per-call context sizes. Raising the threshold enlarges every call and is
  strictly WORSE; lowering it is better.

A deterministic sawtooth model (floor 50K, g 8,260, 81 calls) shows the inversion:

| threshold | folds | total sent, broken cache | uncached, working cache |
|---|---|---|---|
| 0.2 (current) | 4 | 9,823,740 | 1,546,820 |
| 0.8 (proposed) | 0 | 31,481,460 | 719,060 |

Raising the threshold cuts the working-cache uncached by ~53% but triples the
broken-cache input. The observed comfyui-1 sits in the broken regime, so raising the
threshold TODAY would increase `capped_tokens`, not reduce it.

## Per-agent optimal threshold table

Two columns per the directive. "Working-cache" is the recommended threshold under the
design intent; "confidence" is how much I trust that a threshold change helps, given
the observed cache-regime uncertainty.

| agent | observed folds @0.2 | recommended threshold | folds @recommended | cycle reduction | uncached reduction (working cache) | backing volume | confidence |
|---|---|---|---|---|---|---|---|
| mechanism_typist | 5 (comfyui-1) / 7 (0ab40280) | 0.75 - 0.80 | 0 / 1 | 5 -> 0, 7 -> 1 (-80% to -100%) | 1.55M -> 0.72M, 2.69M -> 2.01M (-53% / -25%) | 19.8M over 162 calls | 0.40 |
| data_modeller | 3 (comfyui-1) / 1 (0ab40280) | 0.40 - 0.50 | 0 | 3 -> 0, 1 -> 0 | 0.84M -> 0.43M, 0.49M -> 0.29M (-49% / -41%) | 7.7M over 75 calls | 0.55 |
| assigner | 0 | 0.20 - 0.30 (keep; no folds needed) | 0 | 0 | none (already no folds) | 3.5M over 50 calls | 0.70 |
| hunting_orchestrator | 0 | 0.10 - 0.20 (moot) | 0 | 0 | none from threshold; the 0% cache is the issue | 0.9M over 21 calls | 0.30 |
| hunting_hunter | 0 | 0.10 - 0.20 (moot) | 0 | 0 | none | 0.4M over 23 calls | 0.50 |
| pod_runner / pod_triager | 0 | any (short sessions) | 0 | 0 | none | tiny | 0.30 |
| recon triager | 0 | any (1-2 calls per pod) | 0 | 0 | none | tiny | 0.40 |

Backing volume = observed prompt tokens processed (`uncached + cached`) for the agent
across the sampled runs; it is the amount of real context that supports the estimate.

Confidence rests on: two independent runs for the analysis agents (mechanism_typist,
data_modeller, assigner), and one run for the hunting agents. The dominant confidence
subtractor is the cache-regime uncertainty above, not the trajectory reconstruction.

## Ranked recommendation

1. Diagnose the provider cache failure FIRST. `hunting_orchestrator` at 0% over 21
   seconds-apart append-only calls with zero folds, and `mechanism_typist` at 0% over
   its first 41 calls, mean no threshold tuning can deliver the promised uncached
   reduction today. Named experiment (read-only, no live LLM): for one
   `hunting_orchestrator` session, compare the exact request bytes of consecutive
   calls (Langfuse `io`) against the `x-opencode-session` header and the response
   `cached_tokens`; determine whether the prefix is byte-stable and whether any other
   agent reaches the cache on the same session. If the prefix is stable and the cache
   still misses, the defect is provider/relay-side and must be escalated, not tuned
   around.
2. Only if the cache is proven working between folds, raise the threshold for the big
   growers. mechanism_typist to 0.75-0.80, data_modeller to 0.40-0.50. Keep assigner at
   0.20-0.30. These are per-role settings, so this is a config/builder change, not a
   default change.
3. Accept that a fixed threshold cannot phase-align folds because `F` and `g` drift.
   If exact seam alignment is required, that is a phase-aware trigger (a code change)
   and a separate design ticket, not a threshold value.
4. Do NOT lower the threshold as a workaround for the broken cache without measuring
   the summary overhead: lower thresholds increase fold count and summariser calls,
   which consume `generated` tokens and re-send the folded region. The net effect on
   `capped_tokens` needs measurement, not assumption.

## Critical-thinking pass (ASD-STE / critical-thinking discipline)

Core claim: raising the per-agent threshold to just under the context limit, aligned to
phase boundaries, reduces compaction cycles and the uncached spectrum.

Assessment: the cycle-reduction half is sound and directly supported by the observed
trajectories. The uncached-reduction half is CONDITIONAL on the provider prefix cache
working between folds, and the live comfyui-1 evidence shows it does not for the two
agents that matter most. The reasoning is sound, the empirical premise is currently
false.

Weak links, stated plainly:
- The counterfactual uncompacted curve assumes a constant per-call increment. It is
  exact for comfyui-1's first 25 `mechanism_typist` calls and an approximation beyond
  that; genuine growth variance makes it uncertain by perhaps +/-20%.
- The fold detection uses a heuristic (>15% drop and >5K tokens). Small folds that
  regenerate the summary without a large size drop are not counted, so the true fold
  count may exceed the reported one. This makes the cycle-reduction estimate
  conservative.
- The uncached-reduction figures assume a perfect prefix cache between folds. They are
  an upper bound, not a prediction.
- The 0ab40280 run's identity (target, phase) is not confirmed; it is used only as a
  second sample of the same role.

Questions a decision-maker should ask before acting:
- Is the 0% `input_cache_read` a real provider miss, or a reporting gap in the ledger's
  `uncached = input_tokens - cache_read` computation?
- Why does `hunting_hunter` cache 77-86% on the same provider and run when
  `hunting_orchestrator` caches 0%?
- What is the provider's actual context-cache TTL and key on the opencode-go lane?

Bottom line: the per-agent optimal thresholds are mechanism_typist 0.75-0.80,
data_modeller 0.40-0.50, and 0.20-0.30 or moot for the rest - but the promised uncached
reduction is blocked by a provider-cache failure that the live data proves and that no
threshold can fix. Fix the cache first; then raise the thresholds.
