# Token usage and context occupancy: white-jotter batched run

**Date:** 2026-10-24.
**Run:** `a5f487fb-8329-431c-b95d-207799a038f9` (white-jotter, stopped at the 7M cap).
The run first ran in `serial`, was stopped at 12:50 on 10-24, then resumed in `batched` at 12:54.
The ledger covers the whole run; the occupancy window covers the serial tail and the batched phase.
**Project:** `0c8cb6e6-7e91-4a01-880e-408896c0ce4a`.
**Exact usage data:** the project `UsageStore` ledger at stop (1,532 calls, 146.5M raw tokens, 7,000,932 capped tokens).
**Occupancy data:** Langfuse v2 observations over 2026-10-23T16:30Z to 2026-10-24T17:05Z (1,608 generations).
**Script:** `audit_context_occupancy.py` (the reference script plus HTTP 429 retry and `human_first`/`human_second` fields).
**Raw:** `audit_context_occupancy.json`, `usage.yaml`.

## Short answer

The budget axis is **7,000,932 capped tokens**, and the cap stopped the run at 7M.
The raw spend was **146,497,124 tokens**, of which **95.2% was cache reads**.
Capped tokens are only **4.8%** of the raw total.

Per agent, the capped budget is:

- **pod runner 32.9%** (2,302,408);
- **threat modeller 31.1%** (2,179,055);
- **hunter 17.9%** (1,254,212);
- **pod triager 11.5%** (806,339);
- analysis agents **6.6%** (458,918).

Per type, the raw total is cached input 139.5M (95.2%), uncached input 5.15M (3.5%), reasoning output 0.92M (0.6%), and visible output 0.93M (0.6%).

The largest lifecycle occupancy in the hunting run is **tool responses at 41.9%** of the four-role input (60.5M of 144.6M).
The second largest is the **model's own tool-call arguments at 30.5%** (44.1M), driven by the modeller at **40.1% of its session context**.
The system prompt is **16.5%** of the lifecycle (23.8M), and human input is 6.2%.
Tool descriptions are **3.0%** of the lifecycle; the first-call share is 35.5% for the hunter, 47.6% for the modeller, and 50.9% for the pod runner.

The modeller's tool-call arguments are the largest **new** persistent component.
The modeller writes the threat model through tool calls, and the full JSON arguments stay in context for every later turn.
The prior trial's hunter loop tool surface is **absent** in this run (`loop` component 0; hunter tool descriptions 7.3% against 21.9% for descriptions plus loop surface before).

Inside the tool-response class, the largest tools are **`auth_store` 23.6%**, **`search_http_history` 21.2%**, **`exec` 14.5%**, **`skill_load` 10.4%**, and **`hunts_store` 9.1%**.
Those five are 79.0% of the tool-response occupancy.
The `auth_store` full view (max 73,934 chars) and the `search_http_history` 50-row page (max 57,127 chars) are the two payloads to project first.

There are **49 non-clean tool executions**: 30 hard errors and 19 degraded fallbacks.
The hard errors are 11 `hunts_store` contract rejections, 5 `notes` contract rejections, 3 invalid `graph_view` Cypher queries, 2 invalid `search_http_history` filters, 8 `exec` stderr tracebacks, and 1 invalid `replay` request.
The degraded fallbacks are 19 `query_lightrag` answers with `model answer unavailable`.
Malformed argument JSON is 0.
The persisted error responses cost only 0.25% of the tool-response occupancy.

The skill evolver published **five project-specific skill versions during the run** (plus `authn` just before it): `rate-limit-bypass` 1.3, `username-enumeration-oracle` 1.1, `session-management` 1.3, `csrf` 1.1, and `business-logic` 1.1.
The additions are evidence-grounded and target-specific, not generic filler.

## 1. Exact token usage per agent and type

The ledger is the authoritative record the 7M cap read.
`capped_tokens = uncached input + generated output`; cached input is excluded from the cap.

### Per-agent, per-type

| Agent | Phase | Calls | Input mean | Cache share | Capped tokens | Capped share | Raw total | Raw share |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `pod_runner` | hunting | 702 | 39,700 | 93.7% | 2,302,408 | 32.9% | 28,419,528 | 19.4% |
| `hunting_threat_modeller` | hunting | 429 | 229,610 | 98.6% | 2,179,055 | 31.1% | 99,254,895 | 67.8% |
| `hunting_hunter` | hunting | 231 | 61,464 | 93.3% | 1,254,212 | 17.9% | 14,499,140 | 9.9% |
| `pod_triager` | hunting | 89 | 16,039 | 51.1% | 806,339 | 11.5% | 1,536,323 | 1.0% |
| `mechanism_typist` | analysis | 42 | 47,579 | 88.8% | 308,481 | 4.4% | 2,082,817 | 1.4% |
| `triager` | analysis | 10 | 11,241 | 50.7% | 68,846 | 1.0% | 125,806 | 0.1% |
| `job_orchestrator` | analysis | 18 | 20,715 | 95.1% | 42,812 | 0.6% | 397,244 | 0.3% |
| `assigner` | analysis | 11 | 15,243 | 85.0% | 38,779 | 0.6% | 181,371 | 0.1% |
| **total** | | **1,532** | **94,419** | **96.4%** | **7,000,932** | **100%** | **146,497,124** | **100%** |

`Input mean` is the call-weighted mean of `cached + uncached`.
The ledger call count includes every recorded model call; the Langfuse occupancy below has 1,608 generations because it includes the compaction engine and skill evolution.

### Type distribution

| Type | Tokens | Share of raw total | Share of capped budget |
|---|---:|---:|---:|
| cached input (context) | 139,496,192 | 95.2% | excluded |
| uncached input | 5,152,992 | 3.5% | 73.6% |
| reasoning output | 921,074 | 0.6% | 13.2% |
| visible output | 926,866 | 0.6% | 13.2% |
| **raw total** | **146,497,124** | **100%** | |
| **capped (budget axis)** | **7,000,932** | **4.8%** | **100%** |

The cache share is high because each agent re-sends a large, mostly stable context.
Only 4.8% of the raw tokens were new compute.
The capped spend is dominated by generated output plus fresh input, so a high cache share does not mean a low bill on the cap axis.

### Phase split

| Phase | Capped | Capped share | Raw total | Raw share | Calls |
|---|---:|---:|---:|---:|---:|
| hunting | 6,542,014 | 93.4% | 143,709,886 | 98.1% | 1,451 |
| analysis | 458,918 | 6.6% | 2,787,238 | 1.9% | 81 |
| **total** | **7,000,932** | **100%** | **146,497,124** | **100%** | **1,532** |

The analysis agents are 1.9% of the raw tokens but 6.6% of the cap because their cache share is lower (83.5% vs 95.4% for hunting).

## 2. Occupancy definitions

**Content share.**
The component's message characters divided by the total message characters in the same call or session.
This is exact and additive within a call.

**Session tokens.**
The content share multiplied by that call's provider input tokens, averaged over the calls in the session, then averaged over sessions.
This is the unweighted session mean; each session gets one vote.

**First-call tokens.**
The first-call character decomposition scaled to the first-call provider input.
This is the exact fixed-prompt measurement, without runtime tool responses.

**Lifecycle tokens.**
The session share multiplied by the role's total provider input.
This is the area under the context curve and the number to use for "what occupies the context over the lifecycle".

**Classes.**

- **N**: necessary runtime evidence or necessary output.
- **C**: fixed or compressible prompt/tool text.
- **P**: over-persistent. The payload is evidence, but it stays in context at full size after its useful life.

The system subrows are not additive: the system row contains the body, examples, map, and index.
The human subrows are not additive: `human input` contains the first and later messages.
`app overview` is the first human message when it carries the application overview.

## 3. Per-role occupancy

### Hunter (10 sessions, 231 calls)

Session input mean **62,161** tokens; cache share **93.3%**; first call **16,244** tokens.

| Component | Session tokens | Session share | First-call tokens | First-call share | Lifecycle tokens | Lifecycle share | Class |
|---|---:|---:|---:|---:|---:|---:|---|
| system | 10,118 | 16.3% | 7,150 | 44.0% | 2,331,282 | 16.4% | N/C |
| system body | 6,309 | 10.2% | 4,458 | 27.4% | 1,453,590 | 10.2% | N/C |
| system examples | 3,208 | 5.2% | 2,267 | 14.0% | 739,164 | 5.2% | C |
| cognitive map | 515 | 0.8% | 364 | 2.2% | 118,739 | 0.8% | N |
| skill index | 86 | 0.1% | 61 | 0.4% | 19,790 | 0.1% | C |
| human input | 4,741 | 7.6% | 3,333 | 20.5% | 1,092,030 | 7.7% | N |
| human first / app overview | 4,741 | 7.6% | 3,333 | 20.5% | 1,092,030 | 7.7% | N |
| tool descriptions | 4,562 | 7.3% | 5,761 | 35.5% | 1,065,721 | 7.5% | C |
| tool responses | 38,487 | 61.9% | 0 | 0.0% | 8,687,584 | 61.2% | P |
| assistant visible | 108 | 0.2% | 0 | 0.0% | 24,124 | 0.2% | N |
| assistant tool args | 4,144 | 6.7% | 0 | 0.0% | 997,454 | 7.0% | P |
| **total** | **62,161** | **100%** | **16,244** | **100%** | **14,198,194** | **100%** | |

The hunter's largest lifecycle component is tool responses at **61.9%**.
The tool responses are the work product; the over-persistent part is the full-read payloads that remain in context.
The largest fixed component is the system at 16.3%, of which examples are 5.2%.
The first call is 44.0% system and 35.5% tool descriptions; the app overview is 20.5%.

The loop tool surface from the 10-22 trial is absent.
The hunter has one human message (the overview) and no separate loop payload message in the captured input.
The hunter's tool descriptions are 7.3% of the session, against 10.2% in the earlier trial plus an 11.7% duplicate loop surface.
This is a material reduction.

### Threat modeller (1 session, 442 calls)

Session input mean **229,014** tokens; cache share **97.8%**; first call **14,338** tokens.

| Component | Session tokens | Session share | First-call tokens | First-call share | Lifecycle tokens | Lifecycle share | Class |
|---|---:|---:|---:|---:|---:|---:|---|
| system | 43,249 | 18.9% | 6,180 | 43.1% | 19,116,237 | 18.9% | N/C |
| system body | 34,633 | 15.1% | 5,727 | 39.9% | 15,307,638 | 15.1% | N/C |
| cognitive map | 1,972 | 0.9% | 397 | 2.8% | 871,756 | 0.9% | N |
| skill index | 6,644 | 2.9% | 57 | 0.4% | 2,936,843 | 2.9% | C |
| human input | 14,398 | 6.3% | 1,334 | 9.3% | 6,363,945 | 6.3% | N |
| human first | 6,634 | 2.9% | 1,334 | 9.3% | 2,932,219 | 2.9% | N |
| human later | 4,494 | 2.0% | 0 | 0.0% | 1,986,186 | 2.0% | N |
| tool descriptions | 344 | 0.1% | 6,824 | 47.6% | 151,968 | 0.1% | C |
| tool responses | 74,157 | 32.4% | 0 | 0.0% | 32,777,542 | 32.4% | P |
| assistant visible | 5,105 | 2.2% | 0 | 0.0% | 2,256,408 | 2.2% | N |
| assistant tool args | 91,760 | 40.1% | 0 | 0.0% | 40,558,157 | 40.1% | P |
| **total** | **229,014** | **100%** | **14,338** | **100%** | **101,224,256** | **100%** | |

The modeller's largest component is **its own tool-call arguments at 40.1%**, not the tool responses.
The modeller writes large threat-model structures through tool calls; those JSON arguments are re-sent on every later turn.
The tool responses are 32.4%, the system is 18.9%, and the human input is 6.3%.
The first call is 47.6% tool descriptions and 43.1% system; the lifecycle tool-description share is 0.1% because the captured inputs after the first call do not carry the trailing tool block.

This is the single largest new occupancy problem in the run.
The threat-model JSON is the work product, but the full arguments do not need to persist after the write.
Projecting the accepted model summary and dropping the raw write arguments would remove up to 40% of the modeller's context.

### Pod runner (27 sessions, 697 calls)

Session input mean **37,048** tokens; cache share **93.7%**; first call **6,359** tokens.

| Component | Session tokens | Session share | First-call tokens | First-call share | Lifecycle tokens | Lifecycle share | Class |
|---|---:|---:|---:|---:|---:|---:|---|
| system | 2,884 | 7.8% | 2,099 | 33.0% | 2,130,439 | 7.7% | N/C |
| system body | 2,278 | 6.2% | 1,660 | 26.1% | 1,682,570 | 6.1% | N/C |
| cognitive map | 510 | 1.4% | 372 | 5.8% | 377,001 | 1.4% | N |
| skill index | 96 | 0.3% | 67 | 1.1% | 70,868 | 0.3% | C |
| human input | 1,426 | 3.9% | 1,021 | 16.1% | 1,049,671 | 3.8% | N |
| human first | 1,426 | 3.9% | 1,021 | 16.1% | 1,049,671 | 3.8% | N |
| tool descriptions | 4,268 | 11.5% | 3,239 | 50.9% | 2,979,063 | 10.7% | C |
| tool responses | 25,118 | 67.8% | 0 | 0.0% | 18,525,076 | 66.8% | P |
| assistant visible | 652 | 1.8% | 0 | 0.0% | 551,793 | 2.0% | N |
| assistant tool args | 2,701 | 7.3% | 0 | 0.0% | 2,497,139 | 9.0% | P |
| **total** | **37,048** | **100%** | **6,359** | **100%** | **27,733,181** | **100%** | |

The pod runner is the largest capped consumer and its context is dominated by tool responses at **67.8%**.
The fixed tax is the tool descriptions at 11.5% of the session and 50.9% of the first call.
The system is only 7.8%.
The full auth store, replay result, and skill body are the over-persistent payloads inside the tool responses.

### Pod triager (27 sessions, 89 calls)

Session input mean **10,445** tokens; cache share **51.1%**; first call **3,057** tokens.

| Component | Session tokens | Session share | First-call tokens | First-call share | Lifecycle tokens | Lifecycle share | Class |
|---|---:|---:|---:|---:|---:|---:|---|
| system | 1,733 | 16.6% | 979 | 32.0% | 207,777 | 14.6% | N/C |
| system body | 1,235 | 11.8% | 482 | 15.8% | 160,118 | 11.2% | N/C |
| cognitive map | 472 | 4.5% | 498 | 16.3% | 43,669 | 3.1% | N |
| skill index | 26 | 0.2% | 0 | 0.0% | 3,990 | 0.3% | C |
| human input | 3,243 | 31.1% | 1,645 | 53.8% | 420,124 | 29.4% | N |
| human first | 1,039 | 10.0% | 1,645 | 53.8% | 87,620 | 6.1% | N |
| human later | 991 | 9.5% | 0 | 0.0% | 147,877 | 10.4% | N |
| tool descriptions | 1,498 | 14.3% | 433 | 14.2% | 202,607 | 14.2% | C |
| tool responses | 3,710 | 35.5% | 0 | 0.0% | 556,558 | 39.0% | P |
| assistant tool args | 260 | 2.5% | 0 | 0.0% | 40,383 | 2.8% | P |
| **total** | **10,445** | **100%** | **3,057** | **100%** | **1,427,449** | **100%** | |

The pod triager has the lowest cache share (**51.1%**) and the highest human share (**31.1%**).
It runs only 3.3 calls per session, so the first call dominates its lifecycle.
The first call is 53.8% human input, 32.0% system, and 14.2% tool descriptions.
The tool responses are 35.5% of the session; the fixed prompt is the larger part of this role.
The human input is the triager's evidence packet and is necessary, not prompt bloat.

## 4. Cross-agent lifecycle

The four hunting roles contribute **144,583,080** input tokens.

| Component | Lifecycle tokens | Lifecycle share |
|---|---:|---:|
| tool responses | 60,546,760 | 41.9% |
| assistant tool args | 44,093,132 | 30.5% |
| system | 23,785,734 | 16.5% |
| system body | 18,603,916 | 12.9% |
| system examples | 739,164 | 0.5% |
| cognitive map | 1,411,165 | 1.0% |
| skill index | 3,031,491 | 2.1% |
| human input | 8,925,770 | 6.2% |
| human first | 5,161,540 | 3.6% |
| human later | 2,134,063 | 1.5% |
| tool descriptions | 4,399,359 | 3.0% |
| assistant visible | 2,832,325 | 2.0% |
| **total** | **144,583,080** | **100%** |

Tool responses are the largest lifecycle component.
The model's own tool-call arguments are the second largest and are almost entirely the modeller.
The system is third; the body is 12.9% and the examples are only 0.5% across the four roles because the modeller's body dominates.
Tool descriptions are 3.0% of the lifecycle but 35-51% of each role's first call.
The first call is where the fixed prompt and tools are paid; the lifecycle share is diluted by the long, cached sessions.

## 5. Tool response occupancy per tool

Every tool response is counted once per later generation whose input still carries it.
`Unique calls` is the number of distinct `tool_call_id`s in the run.
`Occupancy tokens` is the lifecycle cost: the response characters scaled to the generation's provider input, summed over every appearance.

| Tool | Unique calls | Response appearances | Occupancy tokens | Share | Unique errors | Max response chars |
|---|---:|---:|---:|---:|---:|---:|
| `auth_store` | 44 | 968 | 15,431,677 | 23.6% | 0 | 73,934 |
| `search_http_history` | 148 | 1,901 | 13,912,410 | 21.2% | 2 | 57,127 |
| `exec` | 587 | 12,473 | 9,525,873 | 14.5% | 8 | 4,842 |
| `skill_load` | 17 | 605 | 6,813,975 | 10.4% | 0 | 19,271 |
| `hunts_store` | 60 | 2,944 | 5,958,781 | 9.1% | 11 | 13,030 |
| `graph_view` | 135 | 2,222 | 3,955,001 | 6.0% | 3 | 14,861 |
| `load_skill` | 39 | 449 | 2,341,770 | 3.6% | 0 | 23,785 |
| `get_http_artifact` | 78 | 1,192 | 2,149,238 | 3.3% | 0 | 1,984 |
| `skill_list` | 6 | 124 | 1,990,963 | 3.0% | 0 | 46,514 |
| `notes` | 79 | 3,121 | 1,319,112 | 2.0% | 5 | 1,989 |
| `query_lightrag` | 41 | 368 | 1,175,023 | 1.8% | 19 | 21,443 |
| `note` | 69 | 296 | 525,315 | 0.8% | 0 | 128,813 |
| `kb_query` | 11 | 179 | 345,673 | 0.5% | 0 | 20,495 |
| `TriageDecision` | 20 | 68 | 14,290 | 0.0% | 0 | 798 |
| `DivergenceDecision` | 15 | 44 | 10,780 | 0.0% | 0 | 900 |
| `replay` | 28 | 634 | 4,872 | 0.0% | 1 | 417 |
| `record_skill_lesson` | 18 | 41 | 1,074 | 0.0% | 0 | 86 |
| `write_skill` | 5 | 15 | 380 | 0.0% | 0 | 66 |
| `L1DeltaBatch` | 2 | 4 | 83 | 0.0% | 0 | 57 |
| **total** | **1,402** | **27,648** | **65,476,291** | **100%** | **49** | |

The tool layer accounts for 65.5M tokens.
It is slightly more than the 60.5M four-role `tool_resp` class because it also includes the analysis and skill-evolution roles.

### The five largest tools

**`auth_store` - 15.43M, 23.6%.**
44 unique calls, 968 appearances, max 73,934 chars.
The pod runner's 29 calls cost 11.35M; the hunter's 11 cost 2.18M; the modeller's single full read cost 1.84M.
The `view: full` response is the largest payload in the run.
The summary view is enough for most steps; the full read is the over-persistent one.

**`search_http_history` - 13.91M, 21.2%.**
148 calls, 1,901 appearances, max 57,127.
The modeller's 5 calls cost 8.75M (the 50-row page), the skill evolver's 90 cost 3.59M, the hunter's 37 cost 1.54M.
The page is the single largest named payload; it stays in context for the rest of the session.

**`exec` - 9.53M, 14.5%.**
587 unique calls, 12,473 appearances, max 4,842.
The modeller's 31 calls cost 8.01M; the pod runner's 527 cost 1.41M; the hunter's 25 cost 0.10M.
The responses are small, but the count and the persistence are high: every command stays in the context of every later turn.

**`skill_load` - 6.81M, 10.4%.**
17 calls, 605 appearances, max 19,271.
The modeller's 2 calls cost 5.29M; the hunter's 15 cost 1.52M.
The modeller loads a large skill body early and re-sends it for hundreds of turns.

**`hunts_store` - 5.96M, 9.1%.**
60 calls, 2,944 appearances, max 13,030.
The modeller's 25 calls cost 5.91M; the hunter's 35 cost 45,577.
The tool response echoes the stored hunt model; the echo is re-sent every turn.

### The named tools

`graph_view` - 3.96M, 6.0%: 135 calls, 2,222 appearances, max 14,861.
The pod runner's 68 calls cost 3.00M; the hunter's 28 cost 0.71M; the skill evolver's 17 cost 0.12M.

`load_skill` - 2.34M, 3.6%: 39 calls, 449 appearances, max 23,785.
The skill evolver's 21 calls cost 0.75M; the pod runner's 17 cost 1.58M; the pod triager's 1 costs 0.01M.

`get_http_artifact` - 2.15M, 3.3%: 78 calls, 1,192 appearances, max 1,984.
The modeller's 5 calls cost 1.69M; the skill evolver's 50 cost 0.23M; the hunter's 18 cost 0.21M.
The responses are small and bounded; the cost is the many appearances.

`skill_list` - 1.99M, 3.0%: 6 calls, 124 appearances, max 46,514.
The whole catalogue is re-sent; this is a fixed tax.

`notes` - 1.32M, 2.0%: 79 calls, 3,121 appearances, max 1,989.
The modeller's 23 calls cost 1.27M.

`note` - 0.53M, 0.8%: 69 calls, 296 appearances, max 128,813.
The pod triager's 35 calls cost 0.51M; the pod runner's 34 cost 0.02M.
One single triager note is 128,813 chars - the largest single response in the run.
It is rare, but it should be projected.

`query_lightrag` - 1.18M, 1.8%: 41 calls, 368 appearances, max 21,443.
The pod runner's 40 calls cost 1.17M.

`kb_query` - 0.35M, 0.5%: 11 calls, 179 appearances.

`record_skill_lesson`, `write_skill`, `replay`, `TriageDecision`, `DivergenceDecision`, `L1DeltaBatch`: under 0.05% each.

The three biggest levers are clear: project the `auth_store` full view, the `search_http_history` page, and the `skill_load` body.
They are 15.4M + 13.9M + 6.8M = 36.1M, or 55.2% of the tool-response occupancy.

## 6. Tool call errors

There are **49 unique non-clean tool executions** across 1,402 calls (3.5%).
Thirty are hard errors and 19 are degraded fallbacks.

### Request-contract rejections: 21

| Tool | Unique | Kinds (appearances) | What failed |
|---|---:|---|---|
| `hunts_store` | 11 | `ok_false` 110 | missing required `spec.strategy_keyword`, `spec.target_identity` |
| `notes` | 5 | `ok_false` 81 | unknown field `limit` |
| `graph_view` | 3 | `error_field` 45 | invalid Cypher (alternation pipe, wildcard star) |
| `search_http_history` | 2 | `error_field` 34 | `invalid_filter`: unknown side `header` |

The `hunts_store` rejections are the most consequential.
The hunter wrote a spec without the two required fields and the tool refused it.
The terminal markers show the specs eventually landed, so the hunter retried.
The rejection is still a write-contract gap on the hunter's side.
The `notes` rejections are the same class: the hunter used a field the tool no longer accepts.
The `graph_view` and `search_http_history` rejections are query-syntax errors.

### Execution failures: 9

| Tool | Unique | Kinds (appearances) | What failed |
|---|---:|---|---|
| `exec` | 8 | `stderr` 119 | the inline script raised a Python traceback |
| `replay` | 1 | `error_field` 9 | `invalid_request` on the replay command |

The `exec` failures are the pod runner's inline scripts.
The body often still carried a result, so the experiment continued.
The error response is re-sent on every later turn.

### Degraded answers: 19

| Tool | Unique | Kinds (appearances) | What failed |
|---|---:|---|---|
| `query_lightrag` | 19 | `fallback` 176 | `model answer unavailable`; a deterministic checklist fallback |

The LightRAG model answer was unavailable for 19 of 41 calls, all in the pod runner.
The fallback is not a hard error, but the pod runner received a checklist instead of the model's synthesis for those calls.

### Request-side and capture

- Malformed argument JSON: **0**.
- Call appearances with no captured response: **122**. The largest is `skill_list` (86 generation appearances); then `search_http_history` 18, `TriageDecision` 4, `get_http_artifact` 4, `load_skill` 4, `query_lightrag` 3, `DivergenceDecision` 3. These are mostly the trailing call of a captured turn or a truncated input, not an execution failure.
- Unattributed responses: 4 (the compaction utility and a truncated call).

### Error cost

The persisted error responses cost **165,364 tokens, 0.25%** of the tool-response occupancy (581 appearances).
The count is small in tokens, but the contract rejections are the useful signal: the `hunts_store` and `notes` schemas are not stable enough for the hunter.

## 7. Skill evolver output

The evolver published five project-specific skill versions during the run and one just before it.
The manifests record the previous version, the source lesson ids, and a snapshot.
The skill bodies are 8.5-21.8 KB.

| Skill | Version | Revisions | Written | Added content | Meaningful? |
|---|---|---|---|---|---|
| `authn` | 1.1 | 1 | 10-23 16:28 | target authn procedure | yes, but before the run |
| `rate-limit-bypass` | 1.3 | 3 | 10-23 23:07; 10-24 10:20, 10:27 | three White Jotter target notes (status 200, 54/51-byte bodies, JSESSIONID, 302 `/nowhere`, burst width), counter non-atomicity, admit-versus-effect seed | yes |
| `username-enumeration-oracle` | 1.1 | 1 | 10-24 10:47 | a new variant: fixed-secret pairwise delta over message, timing, status, redirect | yes |
| `session-management` | 1.3 | 3 | 10-24 14:19, 14:34, 16:09 | before/after recording, post-event replay, carrier comparison, header-count false signal, client-chosen acceptance two arms, three-arm negative control | yes |
| `csrf` | 1.1 | 1 | 10-24 14:43 | logout-clearing signal and termination without authority | yes |
| `business-logic` | 1.1 | 1 | 10-24 16:34 | uniqueness oracle, masked envelope, existing-record lane, ambiguous envelope | yes |

The additions are **not generic filler**.
They are target-specific procedures and negative controls.
The lesson files carry the evidence ids (`exec:`, `probe:`, `http_*`) and the authoring agent and session.

Examples:

- `rate-limit-bypass` records the exact White Jotter `POST /api/login` behavior: every attempt answers HTTP 200; `账号不存在` is a 54-byte body, `密码错误` is 51 bytes; the success is a 200 18-byte `身份认证成功` on `GET /api/authentication`; an anonymous request answers 302 to `/nowhere`. It also records that eight failing attempts span about 300 ms, so the amplification is queueing, not k-times.
- `session-management` records the Shiro two-arm result: a gate-minted `JSESSIONID` carried into `POST /api/login` is retained and promoted; an arbitrary `JSESSIONID` is discarded and replaced; the login sets only `rememberMe`. It adds the three-arm negative control (anonymous, remembered blob, live).
- `business-logic` records the uniqueness oracle: re-registering a healthy name answers `用户已存在`, a multi-row name answers the generic `{"code":400,"message":null}`; the 8-lane burst only duplicates a name absent at burst time.
- `csrf` records the logout-clearing signal: `GET /api/logout` answers 200 with a success body on an empty jar and on a garbage cookie, so the success body alone is not proof of a forced termination.

The lesson files are larger than the skills' added text and hold the full evidence; the evolver consumed them into the skill body.
The published skills are the durable, reusable product of the run.

The lesson store also holds `webpage-analysis` (16:29), `deserialization-signed-forgery` (15:21), and `defence-bypass` (16:10) lessons that did not produce a project-specific skill file in this window.
They are pending a later pass, or they target a generic skill rather than the project branch.

The one caveat is budget visibility: the evolver's 122 calls and 6.4M input are **not in the project ledger** (section 8), so the 7M cap did not count the roughly 1.07M capped tokens of skill evolution.
The output is meaningful; the spend is unmetered.

## 8. Analysis roles and unmetered spend

The analysis roles ran before the hunting run (their traces end at 16:29:50 on 10-23).
Their occupancy is reported for completeness; their exact token usage is in section 1.

| Role | Sessions | Calls | Session input mean | Cache share | Largest component | Largest share |
|---|---:|---:|---:|---:|---|---:|
| mechanism typist | 1 | 15 | 53,948 | 90.7% | human input | 55.6% |
| assigner | 1 | 5 | 21,615 | 84.0% | human input | 38.9% |
| skill evolver | 8 | 122 | 51,070 | 85.8% | tool responses | 73.9% |
| compaction summary | 1 | 4 | 225,779 | 75.0% | system (session material) | 100% |

The calls and means in this table are the traces inside the occupancy window.
The exact full-run totals are in section 1; the mechanism typist and assigner ran earlier calls before 16:30 that the window does not contain.

The mechanism typist's human input is the streamed analysis surface; it is necessary data.
The assigner's human input is the aggregate analysis surface; it is also necessary.
The compaction summary engine is not an agent; it is the running-summary utility (#95).
It made 4 calls at about 225k input each, for about 903k input and 226k uncached.
It has no session id and is not in the project ledger.

The **skill evolver** made 122 calls over 8 sessions for about **6.40M input** (5.49M cached, 0.91M uncached) and 0.17M output.
The skill evolver does **not appear in the project `usage.yaml`**, so its capped spend (about 1.07M) was **not counted by the 7M cap**.
The session ids name the project, but the calls are outside the project usage scope.
This is a real leak in the budget guard: the cap read 7,000,932 while about 1.07M more capped tokens were spent by a project-named agent.

## 9. Findings and priorities

1. **Largest lifecycle component: tool responses, 60.5M tokens, 41.9%.**
   The class is necessary; the over-persistent full-read payloads are the defect.
   The pod runner is the worst at 67.8%, the hunter at 61.9%.

2. **Largest new persistent component: the model's own tool-call arguments, 44.1M, 30.5% of the hunting lifecycle.**
   The modeller alone contributes 40.6M, or 40.1% of its session.
   The threat-model write arguments are re-sent every turn.
   Project the accepted model and drop the raw write arguments.

3. **Largest fixed component: the system prompt, 23.8M, 16.5%.**
   The hunter's system is 44.0% of its first call; the modeller's is 43.1%.
   The system examples are 5.2% of the hunter session; the modeller's skill index is 2.9%.
   These are compressible, but they are smaller than the tool responses and the modeller args.

4. **Tool descriptions are 3.0% of the four-role lifecycle, but that share is diluted by the modeller's 100M-token session.**
   Per role they are lower than the 10-22 trial: hunter 7.3% (was 10.2% plus an 11.7% loop surface), pod runner 11.5% (was 18.8%), pod triager 14.3% (was 21.9%), modeller 0.1% lifecycle and 47.6% first call.
   The first-call tax remains large: 35.5% hunter, 47.6% modeller, 50.9% pod runner, 14.2% pod triager.
   The pod runner and triager are the best targets for schema slimming.

5. **The hunter loop tool surface duplicate is gone.**
   The earlier trial paid 11.7% of the hunter session for a duplicate loop surface.
   This run has no loop component and a 7.3% tool-description share.
   That is the clearest improvement in the run.

6. **The pod triager is the least cached role (51.1%) and the most first-call heavy.**
   Its 3.3 calls per session mean the fixed prompt, not the runtime, dominates.
   This is the best target for a smaller first-call prompt.

7. **Budget guard gap: skill evolution spent about 1.07M capped tokens outside the project ledger.**
   The cap was correct for the ledger it read, but the ledger did not include the skill evolver.
   The evolver's turn seam (`app/llm/evolver.py::_default_turn_fn`) calls `arun_session_turn` without `usage_scope`, so its usage lands in the unscoped bucket.
   Set the skill-evolver usage scope to the project, or meter it explicitly.

8. **The compaction engine spent about 0.9M input (0.23M uncached) in 4 calls.**
   It is legitimate overhead, but it is invisible to the per-agent table.
   Report it as a separate utility line in future trials.

9. **Five tools are 79.0% of the tool-response occupancy.**
   `auth_store` 23.6%, `search_http_history` 21.2%, `exec` 14.5%, `skill_load` 10.4%, `hunts_store` 9.1%.
   Project the `auth_store` full view (max 73,934 chars) and the `search_http_history` page (max 57,127 chars) first; they are 36.1M tokens together with `skill_load`.

10. **The hunter's tool contract rejected 16 writes: 11 `hunts_store` and 5 `notes`.**
    The `hunts_store` rejection is a missing `spec.strategy_keyword` and `spec.target_identity`; the `notes` rejection is an unknown `limit` field.
    The hunter retried and the specs landed, but the schema gap spends turns and tokens.
    Align the hunter prompt and the tool contract, and validate the write before the model call.

11. **The evolver's five published skills are meaningful; its spend is the guard gap.**
    The skills add target-specific procedures and negative controls, grounded in the run's evidence ids.
    The evolver's usage is unscoped, so about 1.07M capped tokens bypassed the 7M cap.
    Meter the evolver and keep the output.

12. **The auth full view is the single largest removable auth payload.**
    Twenty-three reads produced 81.8% of the auth response characters.
    The read-only binding retires `view: full`, projects the summary overview, and bounds a read at 12,000 characters.
    The canonical minimal set is the overview login header plus one account's credentials or token metadata.

13. **The LightRAG fallback was a validator false positive.**
    Eighteen of the 19 fallbacks were ordinary methodology prose rejected by an over-broad "tool request" marker.
    The provider answered; the admission rejected it.
    The marker is now a protocol shape, and the one `not_json` case remains a generation-format miss.

14. **The pod note tool is now the shared notes tool.**
    The pod-only `note` name and `operation` verb are retired.
    The 128,813-character read was an unfiltered read of every note body; the unified read keeps the verbatim body but scopes it to the bound spec.

## 10. Caveats and reproduction

The Langfuse input is truncated near 261k characters on the latest turns; the decomposition uses the character share against the provider input anchor, not a second tokenizer.
The provider input total, cache read, and generated output are exact.
The first-call decomposition is the exact fixed-prompt measurement.
The tool descriptions are measured from the tool-schema messages present in the captured input; a tools array passed out-of-band is not visible, so the lifecycle tool-description share is a lower bound.
The Langfuse and ledger call counts differ slightly (1,608 vs 1,532) because Langfuse includes the compaction engine and skill evolution and because a few calls carry no usage record.
The occupancy window starts at 16:30 on 10-23 and covers the analysis tail and the whole hunting run; the analysis roles' earlier calls are outside it, but their exact usage is in the ledger.

The per-tool table counts a response once per later generation whose input still carries it.
Unique calls are distinct `tool_call_id`s.
The error classes are read from the tool envelopes (`ok: false`, `error`, `stderr`) and short error text.
A large body that merely mentions `timeout` is not an error.
The 122 call appearances with no captured response are captured-input artifacts, not a transport-error log.

Reproduction:

```
python3 audit_context_occupancy.py \
  --project-id 0c8cb6e6-7e91-4a01-880e-408896c0ce4a \
  --from 2026-10-23T16:30:00Z \
  --to 2026-10-24T17:05:00Z \
  --out audit_context_occupancy.json
```

The exact ledger is `usage.yaml` from
`/opt/polymerhus-dev/eval/instances/data/eval-server-1/0c8cb6e6-7e91-4a01-880e-408896c0ce4a/usage/usage.yaml`.

## 11. Run feedback mining

Four tools were mined again for call shape, not only for size.
The raw output is `mine_run_feedback.py`, `run_feedback.json`, `mine_auth_store.py`, and `auth_store_usage.json`.

### `auth_store`: the full view is the defect

There were 44 unique `auth_store` calls.

| Shape | Calls | Response chars | Roles |
|---|---:|---:|---|
| `view: full` | 23 | 1,509,358 | pod runner 17, hunter 3, evolver 2, modeller 1 |
| `view: summary` | 16 | 336,272 | pod runner 9, hunter 7 |
| `path: overview` | 2 | 6,537 | pod runner 1, evolver 1 |
| `path: accounts.<name>` | 2 | 1,893 | pod runner 2 |
| `path: technical_conditions` | 1 | 76 | hunter 1 |

The 23 full reads are 81.8% of the auth response characters.
They are the 15.43M-token occupancy line in section 5.

Why the agents use it: they want the login mechanism and one account's usable state.
What they need is the overview header, the chosen account's credentials or token metadata, and its status.
What they request is the whole redacted bucket because `view: full` is the easiest call and the contract offered it.

The fix:

- The read-only binding retires `view: full` with the coded `auth_full_view_retired`, which teaches `fields` and the narrow paths.
- The default `summary` now projects the overview to `login_endpoint`, `required_headers`, `mechanism`, `defences`, and a bounded note.
- A read over 12,000 characters returns its keys and a narrowing hint instead of the payload.
- The canonical minimal set is `overview.login_endpoint`, `overview.required_headers`, `overview.mechanism`, `accounts.<name>.credentials`, `accounts.<name>.tokens`, and `accounts.<name>.status`.

### `notes` and `note`: one tool now

The two tools were ambiguous: `notes` (hunter, `command` + `action`) and `note` (pod, `operation`).
The pod now binds the same `tool_contract.StoreNotesTool` implementation under the name `notes`.
The pod's typed fields (`order`, `kind`, `classification`, ...) ride the shared field map; the hunter and the modeller keep their own maps.
The 128,813-character `note` response was a triager read with no filters: the old pod read returned every matching note body verbatim.
The unified read keeps the verbatim body but scopes it to the bound spec and exposes the typed filters; the dangling-filter diagnosis is recorded here.
A hard per-response cap on the notes read is the next step if a large note recurs.

### `search_http_history`: the unfiltered page is the spurious-data source

There were 153 searches in the mining window.

| Filter profile | Calls |
|---|---:|
| no filter (whole 50-row page) | 70 |
| `contains` | 42 |
| `eq` | 22 |
| `gte` | 5 |
| `absent` | 4 |
| two or more filters | 10 |

The most common filters are `request.core.url:contains` (9), `request.core.path:contains` (7), `response.header.set-cookie:contains` (6), `request.core.method:eq` (5), `request.core.path:eq` (5), `response.core.status:eq` (4), `request.body.username:eq` (4), `response.header.location:contains` (3), and `request.cookie.JSESSIONID:contains` (3).
The agents filter on the request line, the response status, and the session-cookie headers.
They are not filtering on bodies.

The five sampled sessions show the needed pair:
a search narrows to a URL or a header shape, then `get_http_artifact` fetches the one record whose body or status is needed.
The unfiltered 70 calls are the spurious share: they return ephemeral recon enumeration rows that no later turn reads.

### `exec`: curl dominates, and the batch is the lever

There were 587 calls.

| Command shape | Calls |
|---|---:|
| `curl` | 389 |
| other | 108 |
| inline Python | 82 |
| `python3` script | 6 |
| `sh` | 2 |

The median response is 444 characters; the p90 is 478.
The response is a one-line `TOOL RESULT: status=... body='...'` envelope, so the line-density metric is not informative.
The cost is the 12,473 appearances, not any one body.

The concise convention: one inline Python script per probe batch, printing a compact JSON array of `{label, status, length, marker}` rows.
That replaces several curl calls and one shared envelope with one response that the later turns can read.

### `graph_view`: narrow and useful

There were 135 calls: 132 narrow, 3 broad, and 5 with zero rows.
The narrow queries select endpoints, technologies, and L1 services/systems with a `WHERE`, a property map, or a `LIMIT`.
The rows arrive and the agents use them; the 3.95M-token occupancy is the 2,222 appearances, not a broad query.
No query-shape change is needed.

### `query_lightrag`: a validator false positive, not a provider failure

There were 42 calls and 19 fallbacks.

| Gap | Calls |
|---|---:|
| `tool_or_stage4_request_present` | 18 |
| `not_json` | 1 |

The provider answered; the strict admission rejected the answer.
The old marker `\b(use|invoke|call|run|execute)\b.{0,32}\b(tool|function|command|agent)\b` rejected ordinary methodology prose such as "use the function to compare the ids".
The marker is now a protocol shape (`tool_call`, `function_call`, a JSON `name` of a real tool, "call the <name> tool", "stage 4").
The `not_json` case is a generation-format miss, not a provider outage.
A legitimate answer is no longer laundered into the deterministic checklist.

### Skill evolver tracking

The evolver's turn now passes the project id as `usage_scope`.
Its calls land under the `skill_evolver` role in `GET /projects/{id}/usage` with the same two-axis surface as every other agent.
The 122 calls and about 1.07M capped tokens from the 2026-10-24 run are now counted against the cap.
