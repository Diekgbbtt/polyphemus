# Context occupancy analysis: which component is illegitimately large?

**Date:** 2026-10-23.
**Trial:** white-jotter 7M, `white-jotter-1-20261022T030303-1618c524`.
**Data:** 1,437 generation records, 9 roles, 83 sessions.
**Script:** `audit_context_occupancy.py`.
**Raw data:** `audit_context_occupancy.json` is produced by the script.

> **Correction (2026-10-23):** the worst-payload attribution below is wrong.
> The 74,649-character modeller payload is `auth_store`, not `search_http_history`.
> The modeller's 50-row HTTP page is 22,302 characters.
> The 11.5M carry figure belongs to the auth store, and the auth-store summary default has already fixed it.
> The largest remaining hunter payload is `skill_list`.
> See `TOOL-RESPONSE-OCCUPANCY-ASSESSMENT.md` for the corrected totals and the new ranking.

## Short answer

The component that occupies the most context over its lifecycle is **tool responses**.
It is 51.2% of the hunter session context, 72.9% of the modeller, 55.7% of the pod runner, and 47.1% of the pod triager.
Across the six main roles it is **55.7M of 93.4M input tokens**, or **59.6%**.

Tool responses are also the work product, so the class is not illegitimate by itself.
The illegitimate part is the **full-read payloads that stay in context for the rest of the session**.
The 50-row HTTP-history page alone carries **11.5M chars over 154 turns** from one 74,649-char response.
The auth store adds about **3.4M** carry, and the skill body about **1.3M**.

The most purely redundant component is the **hunter loop tool surface**.
It is **22,470 chars**, of which **22,219 are the same description text as the request tools**.
It is **11.7% of the hunter session context**, **3.14M lifecycle token-equivalent**, and **100% avoidable**. The raw loop-surface characters across hunter calls are about 8.94M.

The largest fixed overlong component is the **tool-description surface**.
It is **11.0M lifecycle token-equivalent**, 11.8% of all input. The raw repeated tool-description characters are 38.2M. About 4.2M token-equivalent of the description text is compressible.
About 38% of the description text is compressible without removing the schemas.
Its first-call share is 35.8% for the hunter, 56.0% for the modeller, 55.6% for the pod runner, 42.2% for the pod triager, 33.5% for the mechanism typist, and 46.6% for the assigner.

The single worst payload is the **HTTP-history page**.
The worst duplicate is the **hunter loop tool surface**.
The worst fixed tax is the **tool descriptions**.
The worst analysis-role fixed tax is the **system examples plus tool descriptions**.

## Why the earlier table was misleading

The earlier report table used all-generation weighted shares.
It also treated every component as if it had the same chars-per-token density.
Neither is true.

The fixed text is prose-like and about 4.2 chars per token.
The tool responses are JSON, Chinese text, and terminal output; their token density is much higher.
A 55% character share of tool responses can be more than 70% of the provider input tokens.
The fixed text is cached; the runtime tool responses are the uncached and lifecycle-growing part.

The modeller table showed tool descriptions at 25.2%.
That number came from the valid early-generation sample and a scaled character share.
It is not the average session share and not a token count.
The first-call share is 56.0%; the session fixed share is about 4.4%; the tool responses are 72.9% of the session.

The session-unweighted input means are also lower than the all-generation means:

| Role | All-generation mean | Session mean |
|---|---:|---:|
| hunter | 67,421 | 64,317 |
| pod runner | 36,842 | 34,979 |
| pod triager | 31,964 | 28,293 |

The multi-session agents must be averaged by session, not by generation.

## Definitions

**Content share.** The component's message characters divided by the total message characters in the same generation or session.
This is exact and additive.
It is the primary occupancy ratio in this file.

**Token equivalent.** The content share multiplied by the provider input tokens.
This is a share-preserving estimate, not a second tokenizer.
It is used because the provider input total is exact.
The first-call table is the exact first-call character decomposition.

**First-call share.** The component's first-call characters divided by the first-call message characters.
This is the only place where the fixed prompt and tool schemas are measured without runtime tool responses.

**Session share.** The unweighted mean over sessions of that session's component share.
For single-session roles this equals the session share.
For multi-session roles it gives each session one vote.

**Lifecycle occupancy.** Session share multiplied by the role's total provider input tokens.
This is the area under the context curve and the number to use for "what occupies the context over the lifecycle".

**Classes.**

- **N**: necessary runtime evidence or necessary output. Not a defect by itself.
- **C**: fixed or compressible prompt/tool text. Paid every turn; can be shortened or moved on demand.
- **D**: duplicated. The same information is already present elsewhere.
- **P**: over-persistent. A large runtime payload stays in context after its useful life. It may be necessary evidence but is not necessary at full size.

The system subrows are not additive.
The system row contains the body, examples, map, and index.
The pass sequence is inside the body.
The modeller tool-description fixed row is an alternative to the truncated session row, not an extra component.

## Master table

| Agent | Sessions | Calls | Session input mean | Cache share | Total input | Largest component | Largest share | Most illegitimate component | Class |
|---|---:|---:|---:|---:|---:|---|---:|---|---|
| hunter | 17 | 398 | 64,317 | 93.4% | 26.83M | tool responses | 51.2% | loop tool surface | D |
| modeller | 1 | 163 | 215,777 | 96.1% | 35.17M | tool responses | 72.9% | HTTP history page / tool descriptions | P / C |
| pod runner | 27 | 709 | 34,979 | 93.3% | 26.12M | tool responses | 55.7% | full auth/replay + tool descriptions | P / C |
| pod triager | 24 | 79 | 28,293 | 66.3% | 2.53M | tool responses | 47.1% | tool descriptions / KB answer | C / P |
| mechanism typist | 1 | 43 | 49,854 | 88.5% | 2.14M | human input | 45.2% | system examples + tool descriptions | C |
| assigner | 1 | 10 | 16,929 | 70.1% | 0.17M | tool descriptions | 30.1% | tool descriptions | C |
| job orchestrator | 1 | 13 | 16,185 | 85.5% | 0.21M | tool responses | 46.5% | tool descriptions | C |
| skill evolver | 1 | 7 | 24,453 | 76.0% | 0.17M | tool responses | 36.7% | tool descriptions | C |

The mechanism typist's human input is the streamed analysis surface and the app overview.
It is necessary analysis input, not a prompt defect.
The same is true for the assigner's human input.

## Hunter

The hunter input is 64,317 tokens on the session-unweighted average.
The cache share is 93.4%.
The first call is 24,840 tokens and 104,119 chars.

| Component | Session tokens | Session share | First-call tokens | First-call share | Lifecycle token-equivalent | Class |
|---|---:|---:|---:|---:|---:|---|
| system | 9,315 | 14.5% | 6,661 | 26.8% | 3.89M | N/C |
| system body | 5,368 | 8.3% | 3,838 | 15.5% | 2.24M | N/C |
| system examples | 3,091 | 4.8% | 2,210 | 8.9% | 1.29M | C |
| pass sequence | 2,697 | 4.2% | 1,928 | 7.8% | 1.12M | C |
| cognitive map | 496 | 0.8% | 355 | 1.4% | 0.21M | N |
| skill index | 361 | 0.6% | 258 | 1.0% | 0.15M | C |
| application overview | 588 | 0.9% | 420 | 1.7% | 0.24M | N |
| loop payload | 12,812 | 19.9% | 8,468 | 34.1% | 5.34M | N/C |
| loop tool surface | 7,497 | 11.7% | 5,361 | 21.6% | 3.13M | D |
| loop grounding | 4,940 | 7.7% | 2,838 | 11.4% | 2.06M | N/P |
| loop state and protocol | 331 | 0.5% | 237 | 0.9% | 0.14M | N |
| tool descriptions | 6,542 | 10.2% | 8,904 | 35.8% | 2.73M | C |
| tool responses | 32,942 | 51.2% | 0 | 0% | 13.74M | P |
| assistant output | 1,790 | 2.8% | 0 | 0% | 0.75M | N |
| total | 63,989 | 99.5% | 24,840 | 100% | 26.56M | |

The tool-description session value is the session-scaled value.
The exact first-call value is 8,904 tokens.
At 8,904 tokens it is 13.8% of the session input, not 10.2%.
The table uses the session content share for consistency; the first-call column is the exact fixed tax.

The hunter's most illegitimate component is the loop tool surface.
The request tools already carry the same 22,219 description chars.
Removing the loop surface removes 11.7% of the session context and 21.6% of the first call.

The second is the tool-description surface: 35.8% of the first call and 13.8% of the session at the exact fixed token count.
The third is the system examples plus pass sequence: 8.9% and 7.8% of the first call, 4.8% and 4.2% of the session.
The tool responses are the largest lifecycle component, but they are the actual work; the over-persistent full reads inside them are the defect, not the class.

## Modeller

The modeller input is 215,777 tokens per call.
The cache share is 96.1%.
The first call is 17,076 tokens and 65,799 chars.

| Component | Session tokens | Session share | First-call tokens | First-call share | Lifecycle token-equivalent | Class |
|---|---:|---:|---:|---:|---:|---|
| system | 30,853 | 14.3% | 6,045 | 35.4% | 5.03M | N/C |
| system body | 27,900 | 12.9% | 5,632 | 33.0% | 4.55M | N/C |
| cognitive map | 1,617 | 0.8% | 386 | 2.3% | 0.26M | N |
| skill index | 1,336 | 0.6% | 28 | 0.2% | 0.22M | C |
| human input | 5,448 | 2.5% | 1,301 | 7.6% | 0.89M | N |
| tool descriptions | 537 | 0.2% | 9,558 | 56.0% | 0.09M | C |
| tool descriptions, fixed | 9,558 | 4.4% | 9,558 | 56.0% | 1.56M | C |
| tool responses | 157,302 | 72.9% | 0 | 0% | 25.64M | P |
| assistant output | 21,637 | 10.0% | 0 | 0% | 3.52M | N |
| total | 215,777 | 100% | 17,076 | 100% | 35.17M | |

The session scanner sees only 537 tool-description tokens because the latest 157 inputs are truncated near 261k chars and the trailing tool block is cut.
The exact first-call block is 9,558 tokens.
The fixed block is 9,558 tokens, 4.4% of the session input.
The first-call share is 56.0%.

The modeller's largest lifecycle component is the tool responses, at 72.9%.
The largest single payload is the 50-row HTTP history page: 74,649 chars, first seen at turn 2, carried for 154 turns, about 11.5M chars.
The auth store adds 22,302 chars for about 154 turns, 3.4M.
The skill listing adds 8,567 chars, 1.3M.
The tool descriptions are the largest fixed tax and the largest first-call component.

The most illegitimate modeller items, in order:

1. the full HTTP-history page: 11.5M carry, 154x amplification;
2. the full auth store: 3.4M carry;
3. the full skill listing: 1.3M carry;
4. the tool descriptions: 9,558 tokens per call, 4.4% session / 56.0% first call, 1.56M lifecycle;
5. the system body and examples: 5.03M lifecycle, mostly cached.

## Pod runner

The pod-runner input is 34,979 tokens per call.
The cache share is 93.3%.
The first call is 8,810 tokens and 37,361 chars.

| Component | Session tokens | Session share | First-call tokens | First-call share | Lifecycle token-equivalent | Class |
|---|---:|---:|---:|---:|---:|---|
| system | 3,094 | 8.8% | 2,227 | 25.3% | 2.31M | N/C |
| human input | 2,362 | 6.8% | 1,550 | 17.6% | 1.76M | N |
| tool descriptions | 6,581 | 18.8% | 4,898 | 55.6% | 4.91M | C |
| tool responses | 19,490 | 55.7% | 0 | 0% | 14.55M | P |
| assistant output | 3,450 | 9.9% | 0 | 0% | 2.59M | N |
| total | 34,979 | 100% | 8,810 | 100% | 26.12M | |

The pod runner's largest lifecycle component is the tool responses, at 55.7%.
The largest fixed component is the tool descriptions, at 18.8% of the session and 55.6% of the first call.
The `auth_store` schema alone is 6,364 chars and 30.6% of the pod-runner tool-description block.
The other large descriptions are `query_lightrag` at 2,948, `graph_view` at 2,486, `replay` at 2,457, `load_skill` at 2,045, and `record_skill_lesson` at 2,104.

The over-persistent payloads are the full auth store, the 74,649-char replay result, and the 20,898-char skill body.
The tool descriptions are the fixed overlong tax.
The most illegitimate fixed component is the tool descriptions.
The most illegitimate runtime component is the full auth/replay/skill payload.

## Pod triager

The pod-triager input is 28,293 tokens per call.
The cache share is 66.3%.
The first call is 11,712 tokens and 46,410 chars.

| Component | Session tokens | Session share | First-call tokens | First-call share | Lifecycle token-equivalent | Class |
|---|---:|---:|---:|---:|---:|---|
| system | 3,614 | 12.8% | 2,959 | 25.3% | 0.32M | N/C |
| human input | 4,730 | 16.7% | 3,613 | 30.8% | 0.42M | N |
| tool descriptions | 6,189 | 21.9% | 4,942 | 42.2% | 0.55M | C |
| tool responses | 13,333 | 47.1% | 0 | 0% | 1.19M | P |
| assistant output | 428 | 1.5% | 0 | 0% | 0.04M | N |
| total | 28,293 | 100% | 11,712 | 100% | 2.53M | |

The pod triager's largest component is the tool responses, at 47.1%.
The largest fixed component is the tool descriptions, at 21.9% of the session and 42.2% of the first call.
The largest single response is the 89,087-char KB answer in one session.
The session ranges are wide: tool responses range from 3,308 to 34,570 tokens; tool descriptions range from 5,335 to 7,731.
The fixed tool-description tax is the most consistent illegitimacy.

## Mechanism typist

The mechanism-typist input is 49,854 tokens per call.
The cache share is 88.5%.
The first call is 15,530 tokens and 64,950 chars.

| Component | Session tokens | Session share | First-call tokens | First-call share | Lifecycle token-equivalent | Class |
|---|---:|---:|---:|---:|---:|---|
| system | 8,012 | 16.1% | 5,877 | 37.8% | 0.34M | N/C |
| system examples | 2,563 | 5.1% | 1,880 | 12.1% | 0.11M | C |
| cognitive map | 485 | 1.0% | 356 | 2.3% | 0.02M | N |
| skill index | 188 | 0.4% | 138 | 0.9% | 0.01M | C |
| human input | 22,539 | 45.2% | 4,289 | 27.6% | 0.97M | N |
| tool descriptions | 5,471 | 11.0% | 5,205 | 33.5% | 0.24M | C |
| tool responses | 11,788 | 23.6% | 0 | 0% | 0.51M | P |
| assistant output | 2,044 | 4.1% | 0 | 0% | 0.06M | N |
| total | 49,854 | 100% | 15,530 | 100% | 2.14M | |

The human input is the largest component at 45.2%.
It is the app overview plus the streamed surface, which is the analysis data.
It is necessary and should not be compressed as prompt text.
The most illegitimate fixed components are the system examples at 5.1% and the tool descriptions at 11.0%.
The examples are 7,863 chars in the first call; the tool descriptions are 21,770 chars.
The tool responses are 23.6%; the full responses are the over-persistent part.

## Assigner

The assigner input is 16,929 tokens per call.
The cache share is 70.1%.
The first call is 8,747 tokens and 37,374 chars.

| Component | Session tokens | Session share | First-call tokens | First-call share | Lifecycle token-equivalent | Class |
|---|---:|---:|---:|---:|---:|---|
| system | 3,757 | 22.2% | 3,003 | 34.3% | 0.038M | N/C |
| system examples | 606 | 3.6% | 485 | 5.5% | 0.006M | C |
| cognitive map | 436 | 2.6% | 348 | 4.0% | 0.004M | N |
| skill index | 169 | 1.0% | 135 | 1.5% | 0.002M | C |
| human input | 4,601 | 27.2% | 1,548 | 17.7% | 0.046M | N |
| tool descriptions | 5,098 | 30.1% | 4,075 | 46.6% | 0.051M | C |
| tool responses | 3,346 | 19.8% | 0 | 0% | 0.033M | P |
| assistant output | 126 | 0.7% | 0 | 0% | 0.001M | N |
| total | 16,929 | 100% | 8,747 | 100% | 0.169M | |

The assigner's largest component is the tool descriptions at 30.1%.
The tool descriptions are 17,411 chars and 46.6% of the first call.
The system is 22.2%; the examples are 3.6%.
The tool descriptions are the clearest fixed illegitimacy.
The tool responses are 19.8%; the full-read payload is the runtime part.

## Cross-agent lifecycle

The six main roles contribute 93.4M input tokens.

| Component | Lifecycle tokens | Lifecycle share |
|---|---:|---:|
| tool responses | 55.7M | 59.6% |
| tool descriptions | 11.0M | 11.8% |
| system | 9.6M | 10.3% |
| assistant output | 7.0M | 7.5% |
| loop payload | 5.3M | 5.7% |
| human input | 4.3M | 4.6% |
| total | 92.9M | 99.5% |

The tool responses are the largest lifecycle component by a wide margin.
The tool descriptions are the largest fixed component.
The loop payload is third because it is paid per dispatch; the loop tool surface is 3.14M of it.

The named full-read payloads inside the tool responses are:

| Payload | Unique chars | First turn | Carry turns | Carry chars | Class |
|---|---:|---:|---:|---:|---|
| HTTP history page | 74,649 | 2 | 154 | 11.5M | P |
| auth store | 22,302 | 2 | 154 | 3.4M | P |
| skill listing | 8,567 | 1 | 155 | 1.3M | P |
| KB answer (pod triager) | 89,087 | 1 | 1 | 0.09M | P |
| replay result (pod runner) | 74,649 | 1 | 1 | 0.07M | P |

These are the payloads that make the tool-response component illegitimate over its lifecycle.
They are necessary as evidence, but not at full size for the rest of the session.

## The verdict

There is no single scalar "illegitimacy" unless the definition is stated.
With the three explicit classes, the answer is:

1. **Largest lifecycle occupant:** tool responses, 55.7M tokens, 59.6% of the six-role input.
2. **Largest illegitimate runtime occupant:** the full-read tool responses, 16.4M named chars; the HTTP-history page alone is 11.5M carry.
3. **Largest fixed overlong occupant:** tool descriptions, 11.0M token-equivalent, 11.8%; 4.2M token-equivalent is compressible; the raw repeated description chars are 38.2M.
4. **Largest pure duplicate:** hunter loop tool surface, 3.14M lifecycle token-equivalent, 11.7% of hunter, 100% avoidable.
5. **Largest single payload:** HTTP-history page, 11.5M carry, 154x amplification.
6. **Largest single first-call component for the modeller and pod runner:** tool descriptions, 56.0% and 55.6%.

The single component to name is **tool responses, specifically the full-read payloads**.
The single payload to fix first is the **HTTP-history page**.
The single duplicate to remove is the **hunter loop tool surface**.
The single fixed tax to slim is the **tool descriptions**.

## Per-agent priority

| Agent | First action | Reason |
|---|---|---|
| hunter | remove the loop tool surface | 11.7% session, 100% duplicate |
| modeller | project the HTTP page and auth store; slim the tool descriptions | 11.5M + 3.4M carry; 56.0% first call |
| pod runner | project the auth/replay/skill payloads; slim the tool descriptions | 55.7% runtime, 18.8% fixed |
| pod triager | project the KB answer; slim the tool descriptions | 89,087-char KB; 21.9% fixed |
| mechanism typist | compress the system examples and tool descriptions | 5.1% + 11.0% fixed |
| assigner | slim the tool descriptions | 30.1% fixed, 46.6% first call |

## What is not the problem

The system prompt is not the largest lifecycle component.
The hunter system is 14.5% of its session; the modeller system is 14.3%; the pod runner is 8.8%; the pod triager is 12.8%; the mechanism typist is 16.1%; the assigner is 22.2%.
The system examples and pass sequence are compressible, but they are smaller than the tool responses.
The visible output and reasoning are small.
The human analysis input for the mechanism typist and assigner is necessary data, not prompt bloat.

## Why the earlier role table was not usable

The earlier table combined:

- all-generation weighted shares, not session averages;
- fixed prompt and tool characters with runtime tool responses;
- a single provider-token scaling for components with very different densities;
- a 25.2% modeller tool-description share that was a valid-sample character share, not a session share and not a token count.

This file separates:

- **first-call** fixed components;
- **session** runtime components;
- **content share** versus **token equivalent**;
- **average per call** versus **lifecycle total**;
- **necessary** versus **duplicated**, **compressible**, and **over-persistent**.

## Reproduction

```
python3 audit_context_occupancy.py \
  --project-id cmvgbld4j02enad0ktvximbio \
  --from 2026-10-21T23:50:00Z \
  --to 2026-10-22T03:20:00Z \
  --out audit_context_occupancy.json
```

The session component averages, first calls, and cumulative values are in the JSON.
The full offload/carry model is in `audit_offload_simulation.py` and the report.

## Caveats

The Langfuse input is truncated near 261k chars.
The latest modeller turns lose the trailing tool-description block; the session scanner therefore sees only 537 tool-description tokens.
The fixed first-call measurement is exact and is used for the fixed tax.
The session runtime values are content-share estimates against the provider input anchor.
The provider input total is exact; the component split is not a second tokenizer.
The cache read is exact.
The tool-carry table uses the modeller session and the named payload turns; the other roles have the same payloads in their own sessions.
