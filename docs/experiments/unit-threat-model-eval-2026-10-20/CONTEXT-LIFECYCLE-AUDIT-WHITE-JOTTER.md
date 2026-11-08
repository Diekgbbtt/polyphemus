# Context lifecycle audit: white-jotter 7M trial

## Scope

This report covers the hunting subsystem of the successful 7M white-jotter trial.
The trial is `white-jotter-1-20261022T030303-1618c524`, project `4786aefc-c3fd-46c1-a2ab-45b05cc38e25`, run `5c9590ff-9a83-4cea-9aff-be1bd51e2667`.
The measured code is `5789ad3f`.
The hunting subsystem is `hunting_threat_modeller`, `hunting_hunter`, `pod_runner`, and `pod_triager`.
The analysis roles are included as a comparison.
The two failed white-jotter validation attempts are not the audit target.

## Sources

The durable app log is `/tmp/wj-app.log` on the eval server, captured from `docker logs ph-dd131acc-agent-1`.
It starts at 2026-10-21T23:50:21Z and ends after the trial.
It carries the `compaction ledger` lines and the compaction events.

The Langfuse source is the v4 `observations list` API for the trial window 2026-10-21T23:50Z to 2026-10-22T03:15Z.
The generation records carry `usageDetails` (`input`, `input_cache_read`, `output`, `output_reasoning`) and the tool messages in `input`.
The auxiliary files are `/tmp/lf-obs.json`, `/tmp/lf-nav1-gens.json`, `/tmp/lf-mod-0006-gens.json`, `/tmp/lf-pod-runner-gens.json`, and `/tmp/lf-pod-triager-gens.json`.

The eval source is `trial.yaml`, `metrics.yaml`, and the prior token reconciliation `TOKEN-ACCOUNTING-WHITE-JOTTER.md`.
The session-unweighted occupancy analysis is `CONTEXT-OCCUPANCY-ANALYSIS.md`.
The occupancy and offload scripts are `audit_context_occupancy.py` and `audit_offload_simulation.py`.

## Executive answer

The hunting subsystem accounts for 91,970,064 of the 94,703,380 Langfuse project tokens, or 97.1%.
It accounts for 1,348 of 1,430 generations, or 94.3%.

The total is high because every session re-sends a large working context on every model call.
The context is large because several tools return full, sparse payloads and the compaction layer does not interpose at the tool boundary.

The measured first hunter call is 24,840 input tokens.
It is 27,920 system chars, 1,761 application-overview chars, 35,491 loop-payload chars, 37,325 request tool-schema chars, and 1,622 request-framing chars.
The loop payload repeats 22,470 chars of tool-description text; 22,219 of those are the same description text that the request carries.
The system prompt is 27,920 chars; the worked examples are 9,263 and the pass sequence is 8,084.
The session-unweighted role means are 64,317 input tokens for the hunter, 215,777 for the modeller, 34,979 for the pod runner, 28,293 for the pod triager, 49,854 for the mechanism typist, and 16,929 for the assigner.
The all-generation means are 67,421, 36,842, and 31,964 for the three multi-session roles; the session means are the ones to use.
The cache share is 93.4%, 96.1%, 93.3%, 66.3%, 88.5%, and 70.1% respectively.
The fixed prompt and tool tax is 45.5% of the hunter session average, 17.1% of the modeller, 34.4% of the pod runner, and 51.4% of the pod triager.
The n-turn offload lowers the raw modeller input by 77.0%, but loses 78.2% of the cache read; the full-session net is -435,207 tokens, and the first offload costs 18.1 times more cache than it saves raw.
The offload is therefore rejected as a production fix.
The system-prompt, loop-payload, and tool-description compressions remain design proposals; the direct-reference, auth-store, project-scope, CL-3, and pod-compaction fixes are implemented.

The largest single payloads are:

- the 50-row HTTP-history page at 74,649 chars, about 18.7k tokens;
- the full KB answer at 89,087 chars, about 22.3k tokens;
- the full redacted auth store at 22,302 chars, about 5.6k tokens; the two auth YAML files are 7,476 bytes;
- the full skill body at 20,898 chars, about 5.2k tokens;
- a raw terminal result that adds 17,773 tokens in one step.

The compaction budget is 400,000 tokens, which is 0.4 of the model's 1,000,000-token window.
The modeller reached 401,278 tokens and compacted once, reclaiming 196,204 tokens.
The hunters peaked at 135,235 tokens and never compacted.
The pod runner and pod triager have no compaction ledger in the recorded trial, because the trial ran before the production pod path injected the middleware.
The post-trial code now supplies the runner and triager middleware; the next trial should show the ledger rows.

The compaction is a last-resort turn-end pass, not an inline tool-response offload.
`offload_tool_message` is called only inside `compact_pass`.
A tool body over 700 tokens stays in context until a pass fires.
The hunter and pod contexts never reach the 400,000 trigger, so their large tool bodies stay for the whole session.

The fallback is not cache-breaking in the current implementation.
The running summary is staged after the stable region and before the replay tail; it is not the first message.
The modeller's over-budget calls at 02:26 and 02:34 are the three Langfuse-only generations that the client usage ledger missed.
The 02:26 calls follow a five-minute twenty-one-second gap and have zero cache read; the pass applies at 02:34:49.
The cache miss is a provider-cache timing effect, not a summary-placement defect.
The three calls remain the 477,417 capped-token gap in the token reconciliation.

## Configuration

| Role | Context limit | Threshold | Budget | Compaction wired | Ledger rows | Max occupancy |
|---|---:|---:|---:|---|---:|---:|
| hunting_threat_modeller | 1,000,000 | 0.4 | 400,000 | yes | 161 | 401,278 |
| hunting_hunter | 1,000,000 | 0.4 | 400,000 | yes | 397 | 135,235 |
| pod_runner | 1,000,000 | 0.4 (trial no; code yes) | 400,000 (trial no; code yes) | trial no; code yes | 0 | 94,424 input |
| pod_triager | 1,000,000 | 0.4 (trial no; code yes) | 400,000 (trial no; code yes) | trial no; code yes | 0 | 76,557 input |
| assigner | 1,000,000 | 0.2 | 200,000 | yes | 10 | 43,799 |
| mechanism_typist | 1,000,000 | 0.2 | 200,000 | yes | 43 | 95,280 |
| job_orchestrator | 1,000,000 | 0.4 | 400,000 | yes | 13 | 26,619 |
| triager | 1,000,000 | 0.4 | 400,000 | yes | 9 | 35,757 |

The `.env` sets `LLM_COMPACTION_THRESHOLD=0.4`, `LLM_COMPACTION_THRESHOLD_ASSIGNER=0.2`, and `LLM_COMPACTION_THRESHOLD_MECHANISM_TYPIST=0.2`.
The app log confirms `budget=400000` for the hunting roles and `budget=200000` for the analysis roles.

The recorded trial has no pod ledger row because the trial ran before `run_pod_session` supplied the role middleware.
The post-trial code now passes `runner_compaction_middleware()` and `triager_compaction_middleware()` to the pod builder in `run_pod_session` (commit `1ef3e548`).
The next trial should show the pod ledger rows.
The builders existed during the trial, but the production dispatch did not call them.

## Per-role growth

| Role | Sessions | Calls | Total tokens | Max input | Max positive delta | Sessions above 20k delta |
|---|---:|---:|---:|---:|---:|---:|
| hunting_threat_modeller | 1 | 163 | 35,440,275 | 399,346 | 34,489 | 1 |
| hunting_hunter | 17 | 397 | 27,224,918 | 135,186 | 33,420 | 10 |
| pod_runner | 27 | 709 | 26,589,804 | 94,424 | 29,559 | 16 |
| pod_triager | 24 | 79 | 2,715,067 | 76,557 | 40,232 | 12 |
| mechanism_typist | 1 | 43 | 2,219,294 | 91,881 | 9,359 | 0 |
| job_orchestrator | 1 | 13 | 221,659 | 24,316 | 5,443 | 0 |
| assigner | 1 | 10 | 185,587 | 36,434 | 11,609 | 0 |
| triager | 9 | 9 | 106,776 | 30,828 | 0 | 0 |

The hunting subsystem total is 91,970,064 tokens.
The analysis and other roles contribute the remaining 2,733,316 tokens.

The per-call averages show the repeated context clearly:

- the modeller averages 217,425 tokens per call;
- the hunter averages 68,576 tokens per call;
- the pod runner averages 37,503 tokens per call;
- the pod triager averages 34,368 tokens per call.

## Compaction timeline

The app log has 633 compaction-ledger rows across 30 threads.
Only two rows are over budget, both from the modeller:

- 2026-10-22T02:26:04, occupancy 401,143, cache read 398,976;
- 2026-10-22T02:34:49, occupancy 401,278, cache read 398,976.

The only applied pass is at 02:34:49.
It reclaimed 196,204 tokens.
The modeller occupancy dropped from 401,278 to 91,064 by 02:35:28.

The modeller occupancy timeline shows a long late plateau:

- 01:02:26, 342,035;
- 02:20:56, 399,314;
- 02:26:04, 401,143, over budget;
- 02:34:49, 401,278, over budget;
- 02:35:28, 91,064, after the pass;
- 03:09:19, 161,865, the end of the session.

The hunter sessions never crossed 400,000.
Their maximum was 135,235 in `IntegrationSystem-cross-origin-policy__loop-3`.
The pod roles never produced a ledger row.

The analysis roles never crossed their 200,000 budget.
Their maximum was 95,280 for the mechanism typist.

## Largest observed jumps

These are the largest generation-to-generation input increases in the session sample.

| Session | Time | Delta tokens | Tool call before the jump | Payload |
|---|---|---:|---|---|
| modeller | 00:06:20 | 34,489 | `search_http_history`, `auth_store` | HTTP page 74,649 chars; auth store 22,302 chars |
| pod triager | 00:50:28 | 40,232 | `query_lightrag` | KB answer 89,087 chars |
| pod runner | 01:56:34 | 29,559 | `auth_store`, `load_skill`, `replay` | replay 74,649 chars; auth store 22,302 chars; skill 20,898 chars |
| hunter `IntegrationSystem-cross-origin-policy__loop-2` | 00:49:06 | 33,420 | `get_http_artifact` x2, `auth_store` | artifact and auth payload |
| hunter `IntegrationSystem-cross-origin-policy__loop-1` | 01:25:21 | 12,843 | `graph_view`, `skill_load` | graph rows and skill body |
| hunter `Service-navigation-menu__loop-1` | 01:32:45 | 26,445 | `auth_store`, `kb_query` | auth store plus KB answer |
| modeller | 00:06:53 | 17,773 | `exec` | raw terminal output |

The message-level sizes are exact for the sampled sessions:

- the auth-store tool message is 22,302 chars;
- the KB-answer tool message is 89,087 chars;
- the HTTP-history tool message is 74,649 chars;
- the skill tool message is 20,898 chars in the pod runner and 8,567 chars in the modeller;
- the tool-message list for the pod runner contains 74,649, 20,898, 6,364, 2,948, 2,486, 2,104, 2,045, 1,927, and 1,025 chars; the 74,649-char message is the replay result.

## What the first call already pays

The first generation of each session carries the system prompt and the tool schema.

| Role | First input tokens | System message chars | First user chars |
|---|---:|---:|---:|
| hunting_hunter `Service-navigation-menu__loop-1` | 24,840 | 27,920 | 37,252 |
| hunting_hunter `IntegrationSystem-cross-origin-policy__loop-2` | 25,745 | not parsed | not parsed |
| hunting_threat_modeller | 17,076 | 23,297 | 5,015 |
| pod_runner | 8,810 | 9,446 | 6,574 |
| pod_triager | 11,712 | 11,724 | 14,318 |

The nav1 hunter first input is 104,119 chars.
It contains 27,920 system-message chars, 1,761 application-overview chars, 35,491 loop-payload chars, 37,325 tool-description chars (the 12 tool schemas), and 1,622 request-framing chars.
The 25k-token figure is plausible at about four chars per token.
The 19k-word figure is a rough token-to-word conversion, not a separate fault.
The earlier component sentence omitted the tool descriptions; the corrected breakdown is above.
The loop payload also contains a 22,470-char tool surface; 22,219 of those chars are the same description text as the request tools.
The first call therefore pays the tool description text twice: once in the loop payload and once in the request schemas.
The first call also pays 27,920 system chars, of which 9,263 are worked examples, 8,084 are the pass sequence, 1,488 are the cognitive map, and 1,081 are the skill index.
The first call cache read is 16,128 tokens; the uncached input is 8,712 tokens.
The system prompt and request tool schemas sit in the cached prefix; the loop payload and application overview are the uncached part.

The hunter's fixed first-call context is about 25k tokens.
At 397 hunter calls, the fixed first-call context alone is about 9.86M tokens.
Across the four hunting roles, the first-call context is about 19.8M tokens, or 20.9% of the total.
The system prompt is served on every turn.
The tool schemas and the long tool descriptions ride every request.
The system prompt, the application overview, the loop payload, the tool descriptions, and the request framing are the fixed tax.
The measured occupancy and the compression proposals are in the next section.

## Measured context occupancy and compressions

### Method

The occupancy extractor `audit_context_occupancy.py` reads 1,437 generation records from the Langfuse v2 observations API with full message IO and provider usage.
The input anchor is `usageDetails.input + usageDetails.input_cache_read`.
The output anchor is `usageDetails.output + usageDetails.output_reasoning`.
Component tokens are char-share estimates against that input anchor.
The residual is the request envelope plus any truncated tail; it is reported, never silently dropped.
The offload sample is the single 163-call modeller session.
157 of the 163 stored inputs are truncated near 261k chars, so the offload script uses the response character share for the curve.
The scripts and their exact commands are in the reproduction section.
The earlier auth-store figure was wrong: the full redacted auth store is 22,302 chars; the 74,649-char message is the 50-row HTTP-history page.
The first call carries no tool result; the 37,325-char tool block is the request schemas.

### First call

The canonical first call is the nav1 hunter at 01:24:08.
It is 104,119 chars and 24,840 input tokens.
The input is 8,712 uncached tokens and 16,128 cache-read tokens.
The output is 98 visible/tool-call tokens and 66 reasoning tokens; the provider total is 25,004.
The first call pays 27,920 system chars, 1,761 application-overview chars, 35,491 loop-payload chars, 37,325 request tool-schema chars, and 1,622 request-framing chars.

| Component | Chars | Tokens | Share of input |
|---|---:|---:|---:|
| system prompt | 27,920 | 6,661 | 26.8% |
| application overview | 1,761 | 420 | 1.7% |
| loop payload | 35,491 | 8,468 | 34.1% |
| request tool schemas | 37,325 | 8,904 | 35.8% |
| request framing | 1,622 | 387 | 1.6% |
| total | 104,119 | 24,840 | 100% |

The loop payload splits as follows.

| Loop section | Chars | Share of loop | Share of first call | Tokens |
|---|---:|---:|---:|---:|
| coupling lead | 131 | 0.4% | 0.1% | 31 |
| grounding | 11,896 | 33.5% | 11.4% | 2,838 |
| tool surface | 22,470 | 63.3% | 21.6% | 5,361 |
| state summary | 41 | 0.1% | 0.0% | 10 |
| step protocol | 951 | 2.7% | 0.9% | 227 |
| total | 35,491 | 100% | 34.1% | 8,468 |

The 22,470-char tool surface repeats the 22,219-char description text of the 12 request tools.
The remaining 251 chars are the surface header and the multi-line taxonomy fragments.
The request schemas add 15,106 chars of JSON parameter schema on top of the same description text.
The first call therefore carries 59,544 chars of tool text: 22,219 duplicate description chars, 15,106 schema chars, and the loop surface formatting.
This is 57.2% of the first call.

The first-call system prompt splits as follows.

| System section | Chars | Share of system | Tokens |
|---|---:|---:|---:|
| role body and pass sequence | 16,088 | 57.6% | 3,838 |
| worked examples | 9,263 | 33.2% | 2,210 |
| cognitive map | 1,488 | 5.3% | 355 |
| skill index | 1,081 | 3.9% | 258 |
| total | 27,920 | 100% | 6,661 |

The role body includes `## The passes` at 8,084 chars and `## Discipline (binding)` at 2,343 chars.
The full skill index is only 1,081 chars in this trial.
The examples are the larger system block.

The first call is 36.8% of the hunter average input.
The cache covers 64.9% of the first call.
The cached prefix is the system prompt and the request tool schemas; the loop payload and application overview are the uncached part.
The loop tool surface alone is 5,361 uncached tokens.

### Role occupancy

The role totals use all generation records.
The component shares use the non-truncated samples; the sample counts are in the table.

| Role | Sessions | Calls | Input mean | Session mean | Cache share | Input sum | Output/call | Total/call |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hunting_hunter | 17 | 398 | 67,421 | 64,317 | 93.4% | 26,833,448 | 984 | 68,404 |
| hunting_threat_modeller | 1 | 163 | 215,777 | 215,777 | 96.1% | 35,171,652 | 1,648 | 217,425 |
| pod_runner | 27 | 709 | 36,842 | 34,979 | 93.3% | 26,120,611 | 662 | 37,503 |
| pod_triager | 24 | 79 | 31,964 | 28,293 | 66.3% | 2,525,158 | 2,404 | 34,368 |
| mechanism_typist | 1 | 43 | 49,854 | 49,854 | 88.5% | 2,143,739 | 1,757 | 51,612 |
| assigner | 1 | 10 | 16,929 | 16,929 | 70.1% | 169,285 | 1,630 | 18,559 |
| job_orchestrator | 1 | 13 | 16,185 | 16,185 | 85.5% | 210,407 | 866 | 17,051 |
| skill_evolver | 1 | 7 | 24,453 | 24,453 | 76.0% | 171,171 | 2,459 | 26,912 |
| recon_triager | 9 | 9 | 10,820 | 10,820 | 42.7% | 97,379 | 1,044 | 11,864 |

The occupancy extractor sees 398 hunter generations; the earlier ledger table has 397.
The difference is one generation with usage but no compaction row.
The input sums in the table total 93,442,850; the project total 94,703,380 includes about 1.26M output tokens.

The component shares of the average context are as follows.

| Role | System | Human input | Loop | Tool descriptions | Tool responses | Assistant output |
|---|---:|---:|---:|---:|---:|---:|
| hunting_hunter | 14.5% | 0.9% app | 19.9% | 10.2% | 51.2% | 2.8% |
| hunting_threat_modeller | 14.3% | 2.5% | 0% | 0.2% | 72.9% | 10.0% |
| pod_runner | 8.8% | 6.8% | 0% | 18.8% | 55.7% | 9.9% |
| pod_triager | 12.8% | 16.7% | 0% | 21.9% | 47.1% | 1.5% |
| mechanism_typist | 16.1% | 45.2% | 0% | 11.0% | 23.6% | 4.1% |
| assigner | 22.2% | 27.2% | 0% | 30.1% | 19.8% | 0.7% |
| job_orchestrator | 11.3% | 1.0% | 0% | 29.6% | 46.7% | 11.4% |
| skill_evolver | 22.8% | 7.5% | 0% | 26.6% | 38.0% | 4.9% |

The table is session-unweighted, not all-generation weighted.
The modeller tool-description 0.2% is the truncated-session scanner value.
The fixed first-call tool descriptions are 4.4% of the session input and 56.0% of the first call.
The hunter's loop share splits into 7.7% grounding, 11.7% tool surface, 0.0% state, and 0.5% step protocol.
The assistant output combines visible content and tool-call arguments; the output tokens are reported separately.
The full lifecycle-weighted analysis, including the carried payloads, is in `CONTEXT-OCCUPANCY-ANALYSIS.md`.

The fixed prompt and tool tax is the system, human input, loop, and tool descriptions.
The runtime share is the tool responses and assistant messages.

| Role | First-call input | Session average | Fixed tax | Fixed share | Runtime share |
|---|---:|---:|---:|---:|---:|
| hunting_hunter | 24,840 | 64,317 | 29,257 | 45.5% | 54.5% |
| hunting_threat_modeller | 17,076 | 215,777 | 36,838 | 17.1% | 82.9% |
| pod_runner | 8,810 | 34,979 | 12,037 | 34.4% | 65.6% |
| pod_triager | 11,712 | 28,293 | 14,533 | 51.4% | 48.6% |
| mechanism_typist | 15,530 | 49,854 | 36,022 | 72.3% | 27.7% |
| assigner | 8,747 | 16,929 | 13,456 | 79.5% | 20.5% |
| job_orchestrator | 5,515 | 16,185 | 6,785 | 41.9% | 58.1% |
| skill_evolver | 11,180 | 24,453 | 13,933 | 57.0% | 43.0% |

The hunter and the pod roles are not dominated by the first call: their runtime tool responses are 51.2%, 55.7%, and 47.1% of the session average.
The modeller is dominated by runtime tool responses at 72.9%; its first call is only 7.9% of its average.
The analysis roles are dominated by the fixed prompt and tool tax: 72.3% for the mechanism typist and 79.5% for the assigner.
The cache share is 93.4% for the hunter, 96.1% for the modeller, 93.3% for the pod runner, 66.3% for the pod triager, 88.5% for the mechanism typist, and 70.1% for the assigner.
The high cache share means the fixed prompt and tool text is mostly cache-read, while the loop payload and the runtime tool responses are the uncached work.

### First-call table for the other roles

| Role | Raw chars | Input tokens | Cache read | System chars | First human chars | Loop chars | Tool chars | Framing |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| hunting_hunter nav1 | 104,119 | 24,840 | 16,128 | 27,920 | 1,761 | 35,491 | 37,325 | 1,622 |
| hunting_threat_modeller | 65,799 | 17,076 | 14,336 | 23,297 | 5,015 | 0 | 36,820 | 667 |
| pod_runner | 37,361 | 8,810 | 0 | 9,446 | 6,574 | 0 | 20,770 | 571 |
| pod_triager | 46,410 | 11,712 | 7,424 | 11,724 | 14,318 | 0 | 19,580 | 788 |
| mechanism_typist | 64,950 | 15,530 | 4,096 | 24,580 | 17,943 | 0 | 21,770 | 657 |
| assigner | 37,374 | 8,747 | 8,704 | 12,831 | 6,617 | 0 | 17,411 | 515 |

The mechanism and assigner first humans contain the app overview and the streamed analysis surface.
The pod first humans contain the spec or the runner note; they are not the hunter loop payload.

### Tool descriptions

The hunter has 12 request tools.
The table is ordered by schema size.

| Tool | Schema chars | Description chars | Content class | Loop surface copy |
|---|---:|---:|---|---|
| hunts_store | 8,259 | 1,603 | store write/read | yes |
| auth_store | 6,364 | 4,869 | auth read/write | yes |
| notes | 4,014 | 1,364 | note store | yes |
| search_http_history | 3,845 | 3,423 | HTTP history search | yes |
| kb_query | 2,942 | 1,257 | KB retrieval | yes |
| graph_view | 2,486 | 2,173 | graph read | yes |
| get_http_artifact | 2,231 | 2,035 | HTTP artifact read | yes |
| record_skill_lesson | 2,104 | 1,276 | skill lesson write | yes |
| load_skill | 2,045 | 1,771 | skill load | yes |
| exec | 1,753 | 1,526 | target command | yes |
| skill_list | 716 | 589 | skill listing | yes |
| skill_load | 566 | 333 | suite skill load | yes |
| total | 37,325 | 22,219 | | 22,470 |

The first call pays the 22,219-char description text twice: once in the 22,470-char loop surface and once in the request schemas.
The request schemas add 15,106 chars of parameter structure.
The tool text is 57.2% of the first call.

The same tax exists in every role.

| Role | Tools | Schema chars | Description chars | First-call share |
|---|---:|---:|---:|---:|
| hunting_hunter | 12 | 37,325 | 22,219 | 35.9% |
| hunting_threat_modeller | 10 | 36,820 | 18,038 | 56.0% |
| pod_runner | 8 | 20,770 | 14,584 | 55.6% |
| pod_triager | 7 | 19,580 | 12,894 | 42.2% |
| mechanism_typist | 8 | 21,770 | 15,166 | 33.5% |
| assigner | 6 | 17,411 | 11,344 | 46.6% |

The modeller `hunts_store` schema alone is 14,903 chars because it carries the model store and the hunt store contract.
The pod runner and pod triager each carry the 6,364-char `auth_store` schema.
The analysis roles carry the 3,386-char `auth_store` schema plus a typed output tool.

The earlier "preloaded tool result" attribution was wrong.
The first call has no tool result.
The 37,325-char block is the request tool schema; the loop surface is its duplicate description text.

### Loop-payload entities

The nav1 loop payload is 35,491 chars.
The tool surface is 22,470 chars, 63.3% of the loop and 21.6% of the first call.
The grounding is 11,896 chars; the technical sharpening is 7,512 of those chars.
The state summary is 41 chars; the step protocol is 951 chars.

| Grounding entity | Chars | Share of grounding | Share of first call |
|---|---:|---:|---:|
| coupling lead | 129 | 1.1% | 0.1% |
| unit dispatch | 77 | 0.6% | 0.1% |
| loop | 76 | 0.6% | 0.1% |
| canonical class | 183 | 1.5% | 0.2% |
| vulnerability rationale | 689 | 5.8% | 0.7% |
| likelihood rationale | 222 | 1.9% | 0.2% |
| confidence degree | 27 | 0.2% | 0.0% |
| programming fault | 601 | 5.1% | 0.6% |
| trust agreement | 691 | 5.8% | 0.7% |
| dynamic state | 1,270 | 10.7% | 1.2% |
| technical sharpening | 7,512 | 63.1% | 7.2% |
| loop evidence | 407 | 3.4% | 0.4% |
| residual/target line | 12 | 0.1% | 0.0% |
| grounding total | 11,896 | 100% | 11.4% |

The technical sharpening is the largest real entity.
The tool surface is larger but it is a copy of the request tools.
The dynamic state and trust agreement are the next largest.

The loop-payload compression proposal is:

1. Remove the tool surface from the loop payload.
The request tools already carry the names and schemas.
If a text surface is required, use one line per tool, at most 500 chars.
Save 22,470 chars, 5,361 uncached first-call tokens.
2. Project the technical sharpening to the load-bearing fields: interface agreement, control flow, data flow, authorization boundary.
Drop nested full objects and prose that repeats the unit contract.
Target 4,000 chars; save 3,512 chars.
3. Keep the unit, loop, canonical class, vulnerability rationale, likelihood, confidence, fault, trust, dynamic state, and evidence.
These are the loop facts the hunter must not lose.
4. Keep the state and step protocol; they are only 992 chars.

The proposed compact form is:

```text
Tool surface: the request schemas carry the 12 tool contracts.
Technical sharpening:
- Interface agreement: ...
- Control flow: ...
- Data flow: ...
- Authorization boundary: ...
Programming fault: ...
Trust agreement: ...
Dynamic state: ...
Evidence: ...
```

The projected loop payload is about 9,500 chars, down from 35,491.
The first call falls to about 78,100 chars, or about 18,650 tokens.
The uncached loop part falls from 8,468 to about 2,500 tokens.

### System prompt

The system prompt is 27,920 chars in the hunter.

| Hunter section | Chars | Share |
|---|---:|---:|
| role body | 16,088 | 57.6% |
| worked examples | 9,263 | 33.2% |
| cognitive map | 1,488 | 5.3% |
| skill index | 1,081 | 3.9% |

The role body contains:

| Body section | Chars |
|---|---:|
| loop ontology | 876 |
| character | 471 |
| discipline | 2,343 |
| tree | 1,001 |
| passes | 8,084 |
| spec body | 2,005 |
| tools | 1,028 |
| preamble | 280 |

The worked examples are 3,491 chars for the straight path and 5,772 for examples 2 to 4.
The pass sequence alone is 29.0% of the system prompt.
The examples are 33.2%.

The same component view for the other roles:

| Role | System total | Body | Examples | Map | Index | First-call share |
|---|---:|---:|---:|---:|---:|---:|
| hunting_hunter | 27,920 | 16,088 | 9,263 | 1,488 | 1,081 | 26.8% |
| hunting_threat_modeller | 23,297 | 21,702 | 0 | 1,488 | 107 | 35.4% |
| pod_runner | 9,446 | 6,877 | 0 | 1,488 | 1,081 | 25.3% |
| pod_triager | 11,724 | 9,695 | 0 | 1,488 | 541 | 25.3% |
| mechanism_typist | 24,580 | 14,653 | 7,863 | 1,488 | 576 | 37.8% |
| assigner | 12,831 | 8,697 | 2,070 | 1,488 | 576 | 34.3% |
| job_orchestrator | 6,037 | 5,461 | 0 | 0 | 576 | 26.5% |
| skill_evolver | 18,034 | 12,050 | 5,984 | 0 | 272 | 39.4% |

The cognitive map is a 1,488-char block repeated in every role.
The skill index is 1,081 chars in the hunter, pod runner, and pod triager; 576 in the mechanism and assigner; 107 in the modeller.
The skill-evolver body includes its 272-char index; its body and examples sum to the 18,034-char total.
The index has been replaced by the direct-reference line in the code; the line is under 1,000 chars by test.
The hunter system is 27,085 chars after the change: 26,837 static chars plus the 248-char direct-reference line.
The old 27,920-char system is 835 chars larger; the net saving is 1,081 removed and 248 added.
The first hunter call with the direct-reference system is 103,284 chars, down from 104,119.

The system-prompt compression proposal has two variants.

Variant A, direct, about 14,500 chars:

- keep the loop ontology, character, discipline, tree, spec body, tools, and cognitive map;
- replace the 8,084-char pass prose with an 8-row pass table of trigger, read, write, and exit;
- replace the 9,263-char worked examples with a 1,500-char reasoning shape and move the full examples to `load_skill` or a worked-examples reference;
- replace the 1,081-char index with the direct-reference line;
- keep the same order and attention on the pass table.

Variant B, similar length, about 24,000 to 28,000 chars:

- keep the four worked examples but rewrite each as a compact decision shape;
- keep the pass table and add a target-interaction and verification checklist;
- keep the direct-reference line;
- spend the same length on the loop facts and the pass gates rather than on repeated narrative.

The pod-runner proposal keeps the role, spec, stretch plan, constraints, and output.
It replaces the 1,145-char tools section with a one-line tool pointer, compresses the map to 500 chars, and uses the direct-reference line.
The system moves from 9,446 to about 7,000 chars.

The pod-triager proposal keeps the decision vocabulary and variant minting.
It compresses the map to 500 chars and uses the direct-reference line.
The system moves from 11,724 to about 9,500 chars.

The modeller system is 23,297 chars, and its tool descriptions are 36,820.
The tool descriptions are the modeller's first cut, not its system prompt.
The mechanism and assigner systems are 24,580 and 12,831; their fixed tax is dominated by the system and the tool descriptions.

The exact duplicate spans are:

- the 1,488-char cognitive map in every role;
- the 22,219-char tool description text in the loop surface and the request tools;
- the pass sequence in the system and the loop step protocol;
- the worked examples in the system and the repeated pass reasoning;
- the typed procedure in the triager spec and the separate skill excerpt.

### n-turn tool-response offload

The offload rule is: at turn `t`, a tool response whose originating turn is older than 7 is replaced by a fixed 50-token marker.
There is no retrieval call.
The marker states that the response was offloaded and is not retrievable in this experiment.
The first eight turns do not trigger the rule.
The first offload is turn 8, the ninth call, for the 8,567-char skill-listing response from turn 0.

| Window | Turns | First input | Peak observed | Peak simulated | Input sum observed | Input sum simulated | Raw saved | Cache lost | Net tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| first 8 turns | 8 | 17,076 | 84,294 | 84,294 | 442,593 | 442,593 | 0 | 0 | 0 |
| first 16 turns | 16 | 17,076 | 113,933 | 84,787 | 1,241,753 | 732,165 | 509,588 (41.0%) | 649,454 (52.3%) | -139,867 |
| full 163 turns | 163 | 17,076 | 399,346 | 234,411 | 35,171,652 | 8,104,423 | 27,067,229 (77.0%) | 27,502,435 (78.2%) | -435,207 |

The first offload details are:

- turn 8, observed 88,715 input tokens, simulated 84,787, raw saved 3,928;
- the first changed message is at 28,584 chars, a 13,273-token prefix;
- the observed cache read is 84,224, so the lost cache is 70,950;
- the first offload net is -67,022 tokens;
- the cache penalty is 18.1 times the raw saving at the first offload.

The 8-turn sample has no offload and no cache loss.
The first offload is the ninth call; the eighth call is still below the `> 7` boundary.
The 16-turn window already shows the problem: 41.0% raw saved, 52.3% cache lost, net -139,867.
The full session shows the same sign at scale: 77.0% raw saved, 78.2% cache lost, net -435,207.
The peak falls from 399,346 to 234,411; the raw context curve improves.
The cache curve does not: the first changed message invalidates a large suffix, and the cache read is 84,224 at the first offload while the stable prefix is only 13,273.

The offload is rejected as a production fix.
It reduces the context but does not win on tokens and would cost more in cache and retrieval quality.

### Proposal status

The approved local fixes are implemented:

- the auth-store summary view and field selection;
- project `authn` skill access with the run project;
- the full skill index removed and direct references retained;
- the CL-3 context-only deduplication;
- pod compaction through the existing `after_model` middleware;
- the canonical `skills/target-specific-procedure/<project_id>/` path everywhere;
- the cache-stable compaction verification.

The measured proposals, not implemented:

- remove the loop tool surface (22,470 chars, 5,361 uncached first-call tokens);
- project the technical sharpening (7,512 to about 4,000 chars);
- slim the request tool descriptions (22,219 to about 8,000 chars) and keep the schemas;
- compress the hunter system prompt (Variant A or Variant B);
- compress the pod and analysis prompt maps and indexes;
- reject the n-turn offload.

The projected hunter first call, if all proposals are applied:

| Step | First-call chars | Input tokens | Uncached first-call tokens |
|---|---:|---:|---:|
| baseline | 104,119 | 24,840 | 8,712 |
| remove loop tool surface | 81,649 | 19,479 | 3,351 |
| project technical sharpening | 78,137 | 18,651 | 2,513 |
| slim request descriptions | 63,918 | 15,258 | 2,513 |
| Variant A system | 50,240 | 11,995 | 2,513 |
| Variant B system | 63,918 | 15,258 | 2,513 |

The table is a projection from the measured char shares; it is not a new trial.
Variant B keeps the system length close to the current one and leaves the system cache mostly intact; its saving is the loop and tool duplication.
Variant A is the shorter prompt and the larger context saving.

The system-prompt, loop-payload, and tool-description compressions remain design decisions.
The next action is the user decision, not a code change.

## Failure-mode families

### CL-1 - Full project-context reads

The project-context tools return the full state or the full page by default.

- `auth_store` with `path=""` returns the full redacted state at 22,302 chars; the two auth YAML files are 7,476 bytes.
- `search_http_history` defaults to 50 rows, which produced a 74,649-char message.
- `graph_view` has no row cap by operator ruling, which produced a 12,843-token jump.
- `hunts_store` and `notes` reads return all matching records with no limit or cursor.
- `get_http_artifact` returns one full record with all headers and capture context.

The prompts tell the agents to read these stores for orientation.
The tool descriptions document the narrow paths and filters, but the default call is the full read.
The model follows the default.

### CL-2 - Full-bundle KB answers

`query_lightrag` returns the full answer text.
The pod triager received an 89,087-char answer, about 22.3k tokens, in one call.
The hunter's `kb_query` contributed to a 26,445-token jump.
The answer bundle carries `ontology_explanations`, `provenance_references`, `knowledge_gaps`, and notes.
The model needs a few explanations, not the whole bundle.

### CL-3 - Full skill bodies and duplicated procedure

`load_skill` returns the full skill body plus the usage protocol.
The pod runner received a 20,898-char skill message.
The modeller received an 8,567-char skill message.
The spec's `provenance.skill_procedure` also carries the typed procedure.
The pod triager receives the typed procedure again through `_skill_procedure_context`.
The same procedure therefore appears in the spec JSON, in the loaded skill, and in the typed excerpt.

### CL-4 - Raw terminal output

The hunter and modeller `ExecTool` returns raw `stdout` and `stderr` with no cap.
A 762-arg `exec` call added 17,773 tokens in one modeller step.
The pod `exec` tool caps its model-facing result at 400 body chars and 200 stderr chars.
The pod path is bounded; the hunter and modeller path is not.

### CL-5 - Late, absent, and turn-end-only compaction

The compaction budget is 400,000 tokens.
The hunter sessions peak at 135,235 and never compact.
The pod roles have no compaction at all.
The modeller compacts once, at 401,278, after more than an hour near the top of the window.
The offload of a tool body over 700 tokens happens only inside a compact pass.
The tool body stays full until the pass, and the pass only runs at the turn boundary or the next model-call barrier.

### CL-6 - Cache miss around the over-budget window

The three Langfuse-only generations are 02:26:17, 02:26:44, and 02:34:18.
The 02:26 calls have 234,411 uncached input and zero cache read.
The 02:34:18 call has 234,368 cache read.
The 02:20:56 call has 398,976 cache read.
The gap is five minutes and twenty-one seconds.
The pass applies at 02:34:49.
The pass stages the running summary after the stable region and before the replay tail.
The summary is not the first message.
The cache miss occurs before the pass, and the pass is not the cause.
The three calls remain the 477,417 capped-token client-ledger gap.

### CL-7 - Fixed prompt and tool-schema tax

The hunter's first call is about 25k tokens.
The hunter system prompt, the cognitive map, the skill index, and the tool schemas are served every turn.
The tool descriptions are long prose contracts.
The prompts do not carry a per-tool context budget.
The fixed tax is 20.9% of the total across the hunting roles.

### CL-8 - Pod handoff accumulation

The pod runner and pod triager are stateful sessions with no compaction.
The runner's lap opener carries the full current spec, the probe signatures, the feedback, and the memory guidance.
The triager's delta carries the verbatim P3 note, the full spec, the typed skill procedure, the latest observation, the prior variants, the probe lines, the recent interpretations, and the memory guidance.
The spec and the typed procedure duplicate the procedure material.
The pod sessions grow to 94,424 input tokens for the runner and 76,557 for the triager.
The 29,559 and 40,232 jumps are the visible steps.

## Diagnosis

The diagnosis follows the `/diagnosing-bugs` loop in brief form.
The red-capable loop is the recorded-trace assertion: a session fails if any model-facing tool message exceeds 4,000 chars or any generation input delta exceeds 10,000 tokens.
The recorded trial fails that loop on every sampled hunting session.
The exact command and the evidence files are in the reproduction section.

### CL-1 diagnosis

**Symptom.** A project-context read adds 12k-34k tokens to the next model call.

**Evidence.** The auth store is 22,302 chars; the two auth YAML files are 7,476 bytes.
The HTTP-history page is 74,649 chars.
The graph jump is 12,843 tokens.
The messages are in the modeller `00:06:20` input, the pod runner `01:56:34` input, and the hunter `01:25:21` input.

**Ranked hypotheses.**

1. The tool returns the full state because the prompt tells the model to orient with a full read.
2. The tool has a narrow path, but the default path is the full state and the model follows the default.
3. The model does not know the payload size, so it cannot choose a narrow read.
4. The compaction pass would offload the payload, but it does not run at this context size.
5. The payload is an unavoidable input to the task.

H1 and H2 are confirmed.
H3 is confirmed by the absence of a size or budget in the tool description.
H4 is confirmed by the ledger.
H5 is rejected: the task needs the account shape and a few HTTP rows, not the full store and a 50-row page.

**Probe.** Read the same auth store with `path="overview"`, `path="accounts.<name>"`, and `path=""`.
The full auth read is 22,302 chars; the full HTTP search is 74,649 chars; the narrow reads are the size of one account or the overview.
The probe is the recorded message plus the tool contract at `src/polymerhus/app/auth/tool.py:133`.

**Root cause.** The `AUTH_STORE_READ_CONTRACT` defines an empty path as the full state for orientation.
The `AuthStoreArgs.path` default is `""`.
The hunting and modeller prompts tell the agent to read the auth store for the project's real authentication material.
The `search_http_history` default limit is 50.
The `graph_view` contract says "Always LIMIT: the view returns no cap" but the tool enforces no cap.
The `hunts_store` and `notes` reads have no limit.

**Failure chain.**

1. The agent calls the context tool with the default full read.
2. The tool returns the full state or page.
3. The tool message enters the context at 22k-74k tokens.
4. The compaction trigger is 400,000 tokens, so the payload stays.
5. Every later call re-sends the payload.
6. The total consumption grows by the payload size times the remaining calls.
7. A cache miss turns the repeated payload into capped cost.

**Fix.** The approved follow-up is the auth-store summary view.
The default returns the overview plus the account index and token metadata; credentials, token values, form selectors, role credential sets, and steel profiles are path-only.
The auth-store agents also get the project `authn` skill in their skill listing and load path.
The HTTP-history limit, graph cap, store index, and prompt wording are proposed follow-ups; they are not approved.

**Regression test.** Add a contract test that asserts the default auth read is under 4,000 chars and that a narrow path returns one account.
Add a history test that asserts the default limit is 10.
Add a graph test that asserts the default row cap.

### CL-2 diagnosis

**Symptom.** A KB query adds 26k-40k tokens to the next model call.

**Evidence.** The pod triager tool message is 89,087 chars at 00:50:28.
The hunter `Service-navigation-menu__loop-1` jump is 26,445 tokens at 01:32:45.

**Ranked hypotheses.**

1. The lightrag tool returns the full answer bundle.
2. The model queries a broad concern and the bundle expands.
3. The answer bundle has no field or reference cap.
4. The compaction pass would offload the answer, but it does not run.
5. The answer is necessary in full.

H1, H2, and H3 are confirmed.
H4 is confirmed by the absence of a compaction at that point.
H5 is rejected: the triager needs the symptoms and a few references, not the full ontology.

**Probe.** Count the `ontology_explanations`, `provenance_references`, and `knowledge_gaps` in the 89,087-char answer.
The answer is a full bundle, not a summary.

**Root cause.** `query_lightrag` returns the full `text`.
`KbQueryTool._run` returns that text unchanged.
The tool description and the prompts do not impose a summary or a top-N cap.
The pod triager binds the KB tool and uses it as its primary evidence source.

**Failure chain.**

1. The agent asks the KB a broad concern.
2. The KB returns the full answer bundle.
3. The 89k-char tool message enters the context.
4. The triager's next call pays 22k tokens for the bundle.
5. The triager has no compaction.
6. The bundle stays for the rest of the session.

**Fix.** Add a compact answer contract.
Return the summary, at most five ontology explanations with bounded text, at most five references, and at most three gaps.
Add a `truncated` flag and a `full_ref` to the stored answer.
The prompt says: ask one concern, read the summary, request one reference only when needed.

**Regression test.** Query the fixture KB and assert the compact answer is under 4,000 chars and carries a `truncated` or `full_ref` field.

### CL-3 diagnosis

**Symptom.** Loading one skill adds 5k-19k tokens and the typed procedure is duplicated.

**Evidence.** The pod runner skill message is 20,898 chars.
The modeller skill message is 8,567 chars.
The pod triager spec has a 2,237-char typed procedure and the spec JSON also carries the same procedure.

**Ranked hypotheses.**

1. `load_skill` returns the full markdown body plus the usage protocol.
2. The spec already carries the typed procedure, so the skill load is redundant.
3. The triager context renders the typed procedure twice.
4. The skill body is necessary in full for the pod.
5. The compaction would offload it, but it does not run.

H1 and H2 are confirmed.
H3 is confirmed by `_skill_procedure_context` plus the full spec JSON.
H4 is rejected for the typed procedure: the spec already has the typed fields.
H5 is confirmed by the pod's absent ledger.

**Probe.** Load the same skill through `load_skill` and compare its typed procedure fields with the spec's `provenance.skill_procedure`.
The overlap is the duplicate.

**Root cause.** `build_load_skill_tool` returns `body + PROTOCOL_SEPARATOR + protocol`.
The protocol is appended to every load.
The hunter and pod prompts tell the agent to load the skill.
The pod spec also embeds the typed procedure.

**Failure chain.**

1. The agent loads the skill to get the procedure.
2. The full body and the protocol enter the context.
3. The spec also carries the procedure.
4. The triager renders the typed procedure a second time.
5. The pod has no compaction.
6. The duplicate stays for the session.

**Fix.** The approved dedup is context-only.
Keep the spec schema.
Omit `provenance.skill_procedure` from the full spec JSON in the pod contexts and render the typed excerpt once.
The skill-body and tool-protocol bound is a proposal, not approved.

**Regression test.** Assert the typed procedure is present once in the pod triager context and that the full spec JSON has no `skill_procedure` key.
The default skill-result size test is a proposal.

### CL-4 diagnosis

**Symptom.** One terminal probe adds 17,773 tokens.

**Evidence.** The modeller `exec` call at 00:06:34 has 762 args.
The next generation at 00:06:53 has a 17,773-token delta.
The `ExecTool` returns raw `stdout` and `stderr`.

**Ranked hypotheses.**

1. The command produced a large body and the tool returned it verbatim.
2. The prompt does not tell the model to bound the output.
3. The tool has no head/tail cap.
4. The compaction would offload the body, but it does not run.
5. The body is required in full.

H1, H2, and H3 are confirmed.
H4 is confirmed by the ledger.
H5 is rejected: the model needs a status, a marker, and a bounded excerpt.

**Probe.** Run the recorded command through `ExecTool` and measure the returned string.
The result is the full stdout/stderr.

**Root cause.** `ExecTool._run` returns `json.dumps({"stdout": result.stdout, "stderr": result.stderr, ...})`.
There is no cap and no body ref.
The pod `ExecTool` has a 400/200-char model-facing cap.
The hunter and modeller use the uncapped tool.

**Failure chain.**

1. The model runs a command with a large output.
2. The tool returns the full output.
3. The tool message enters the context.
4. The context stays under the 400k trigger, so no compaction.
5. Every later call re-sends the output.

**Fix.** Cap the model-facing stdout and stderr at about 4,000 chars total, with head and tail excerpts.
Store the full body under a ref.
Add a `max_output_chars` argument and a `truncated` marker.
The prompt says: use `-o /dev/null`, `head`, `wc`, or a status-only probe; never dump a body.

**Regression test.** Run a command that emits 1 MB and assert the tool result is under 4,000 chars and exposes a body ref.

### CL-5 diagnosis

**Symptom.** The compaction never interposes early enough.

**Evidence.** The budget is 400,000.
The hunter maximum is 135,235 and the pod maximum is 94,424.
The only pass is the modeller at 401,278.
The pod path has no compaction ledger in the recorded trial.
`offload_tool_message` is called only in `_compact_pass`.

**Ranked hypotheses.**

1. The threshold is too high for the task's working set.
2. The hunter and pod contexts never reach the threshold.
3. The pod path never injects the middleware.
4. The offload runs only inside a pass, not at the tool boundary.
5. The turn-end spawn is too late for a long single turn.

H1, H2, H3, H4, and H5 are all confirmed.
They are not competing explanations; they are a chain.

**Probe.** Read the app log for `over_budget=True`, `spawned`, and `applied`.
The log has two over-budget rows and one applied pass.
Read `arun_pod` and the surfer path for the middleware at the trial commit.
The trial pod path passes none.
The post-trial code passes both `runner_compaction_middleware()` and `triager_compaction_middleware()` in `run_pod_session` (commit `1ef3e548`).

**Root cause.** The compaction is a turn-end/next-model barrier at 0.4 of the model window.
The hunter and pod sessions stay below that budget, so the pass never runs.
The tool-output offload is coupled to the pass, so it never runs either.
The trial pod path did not inject the middleware; the post-trial code does.

**Failure chain.**

1. A tool returns a large body.
2. The body stays full because no inline offload exists.
3. The context grows to 100k-400k.
4. The hunter and pod stop below the trigger; the modeller crosses it after an hour.
5. The pass fires late or not at all.
6. The context is re-sent on every call.

**Fix.** The approved change is the pod compaction wiring through the existing `after_model` middleware.
The inline tool-response offload and the task budget are not approved; they are analysis proposals.
The n-turn offload experiment is the approved way to quantify the modified offload.

**Regression test.** Add a pod wiring test that asserts both middleware are injected.
The inline-offload and task-budget tests are proposals.

### CL-6 diagnosis

**Symptom.** The over-budget window contains a 468,865 uncapped input charge.

**Evidence.** The 02:20:56 call had 398,976 cache-read tokens.
The 02:26:17 and 02:26:44 calls had 234,411 uncached input and zero cache read.
The 02:34:18 call had 234,368 cache read.
The pass applied at 02:34:49.
The app's `/usage` misses the three generations.
The prior reconciliation values them at 477,417 capped.

**Ranked hypotheses.**

1. The five-minute gap exceeded the provider cache lifetime.
2. The two 02:26 calls were retries with a changed prompt.
3. The compaction summary changed the stable prefix.
4. The client usage middleware skipped the calls because they were streamed or retried.
5. The cache loss is unrelated to the timing.

H1 and H2 are supported.
H3 is rejected: the pass stages the summary after the stable region, and the 02:26 calls precede the pass.
H4 is confirmed by the prior token reconciliation.
H5 is rejected by the timing.

**Probe.** Compare the 02:20:56 cache read, the 02:26 calls, the 02:34:18 cache read, and the 02:34:49 pass.
The 02:26 calls have zero cache read; the 02:34:18 call has cache read; the pass is after both.
The staged order is `region_staged + unfolded + [SystemMessage(summary)] + tail`.

**Root cause.** The provider cache expired during the five-minute gap, so the 02:26 calls re-billed the prompt uncached.
The pass is not the cause.
The client usage ledger did not record the cache-miss generations.

**Failure chain.**

1. The context reaches the 400k boundary.
2. The session idles for five minutes and twenty-one seconds.
3. The provider cache expires.
4. The 02:26 calls send a large uncached input.
5. The client ledger misses the generations.
6. The cap is enforced on an undercounted ledger.

**Fix.** No cache-stable code change is needed.
The report correction removes the cache-breaking claim.
The token reconciliation must read the settled Langfuse spend.
The n-turn offload experiment measures the raw-size gain and the cache-prefix penalty separately.

### CL-7 diagnosis

**Symptom.** Every call pays about 9k-25k tokens before any task content.

**Evidence.** The hunter first input is 24,840-25,745 tokens.
The modeller system message is 23,297 chars.
The pod triager system message is 11,724 chars.
The fixed first-call context is about 19.8M tokens across the hunting roles.

**Ranked hypotheses.**

1. The system prompt carries the full cognitive map and skill index.
2. The tool schemas carry long prose descriptions.
3. The prompt is served on every turn.
4. The tool descriptions are repeated in every request.
5. The fixed tax is necessary.

H1, H2, H3, and H4 are confirmed.
H5 is partially true: some instruction is necessary, but the full prose is not.

**Probe.** Compare the first input tokens with the system and user message chars.
The hunter first input is 24,840 tokens; the modeller first input is 17,076 with a 23,297-char system.
The gap is the tool schema and the skill index.

**Root cause.** The hunting system prompt, the cognitive map, the skill index, and the long tool descriptions are re-served on every turn.
The tool descriptions are full prose contracts rather than compact usage lines.
The prompt has no context budget.

**Failure chain.**

1. Every call starts with the full system prompt and tool schema.
2. The task adds the loop and the tool outputs.
3. The fixed tax is paid on every call.
4. The model has less room for the task and reaches the cap sooner.

**Fix.** The approved change is removing the full skill index and keeping direct internal and project-authn references.
Skill discovery moves to the `load_skill` listing.
The broader system-prompt compression is a design proposal, not approved.

**Regression test.** Assert the full index is absent and the direct references are present.
The prompt-budget test is a proposal.

## Follow-up plan and approval status

The detailed follow-up plan is `CONTEXT-LIFECYCLE-FOLLOWUP-PLAN.md`.
The per-family "Fix" sections above are recommendations.
Only the items in the approved list are in the follow-up implementation plan.

### Approved local fixes

- the auth-store summary view and field selection, plus project `authn` skill access;
- removal of the full skill index from the system prompt;
- direct references to the internal skills and the project `authn` skill;
- the CL-3 context-only deduplication;
- pod compaction wiring through the existing `after_model` middleware;
- verification and correction of the cache-stable compaction claim.

The approved items are implemented on `fix/context-lifecycle-followup` in `7fb8dffe`, `c1de8b21`, and `1ef3e548`.
The project skill path is canonical at `<skills_root>/target-specific-procedure/<project_id>/`.
The live project bundle is at `4786aefc-c3fd-46c1-a2ab-45b05cc38e25/authn/SKILL.md` in the skills volume, 15,872 chars.
The old data-root mirror is removed.
The live `load_skill` with the explicit project returns the White Jotter authn body.
The impact map is `docs/design/project-specific-skill-path-impact-map.md`.

### Not approved

- the inline tool-response offload;
- the broad KB, HTTP-history, graph, exec, and store bounds;
- the task budget or threshold change;
- F-024 stop fencing and post-stop artifact handling;
- trial-record stamping.

### Analysis and proposals

- the component occupancy breakdown;
- the loop-payload entity map;
- the tool-description inventory;
- the system-prompt compression proposal;
- the n-turn offload simulation.

The system-prompt, loop-payload, and tool-description compressions are design decisions.
They stop at the proposal for the user's decision.
The formal source-level duplication audit is in `CONTEXT-DUPLICATION-FORMAL-ANALYSIS.md`.
It covers every analysis, hunting, and boundary agent and proposes the single typed context compiler.
The n-turn offload experiment is an analysis; it does not change production code.
The measured n-turn offload is rejected: it lowers raw context by 77.0%, but loses 78.2% of the cache read and has a full-session net of -435,207 tokens.
The first offload costs 18.1 times more cache than it saves raw.

### Measurement

Reconcile the final spend from Langfuse after the project is idle.
Do not use the terminal snapshot as the final bill.

## Reproduction

The app log:

```
ssh -i <key> root@<host> 'docker logs ph-dd131acc-agent-1 > /tmp/wj-app.log'
python3 - <<'PY'
# parse the compaction ledger and print the over-budget rows and passes
PY
```

The Langfuse generation query:

```
langfuse-cli api observations list \
  --session-id "<run>:<session>" \
  --type GENERATION \
  --limit 100 \
  --fields core,basic,time,io,usage,trace_context \
  --json
```

The red loop:

```
python3 /private/var/folders/.../parse_lf_msgs.py
```

It fails when any model-facing tool message exceeds 4,000 chars.
The recorded trial fails on the 74,649-char HTTP-history page, the 22,302-char auth store, and the 89,087-char KB answer.

The full trial token reconciliation is in `TOKEN-ACCOUNTING-WHITE-JOTTER.md`.
The trial record and metrics are in the run directory under `eval/runs-utm-20261021-white-jotter/`.

The occupancy extractor:

```
python3 audit_context_occupancy.py \
  --project-id cmvgbld4j02enad0ktvximbio \
  --from 2026-10-21T23:50:00Z \
  --to 2026-10-22T03:20:00Z \
  --out audit_context_occupancy.json
```

The offload simulator:

```
python3 audit_offload_simulation.py \
  --project-id cmvgbld4j02enad0ktvximbio \
  --session-id "5c9590ff-9a83-4cea-9aff-be1bd51e2667:hunting_threat_modeller" \
  --from 2026-10-21T23:50:00Z \
  --to 2026-10-22T03:20:00Z \
  --out audit_offload_simulation.json
```

Both scripts read `/opt/polymerhus-dev/eval/instances/eval-server-1/.env` by default.
The occupancy run covered 1,437 generation records across 9 roles.
The offload run covered the 163-call modeller session.

## Limitations

The Langfuse generation `input` is truncated at about 261k chars; the report here used the earlier 256k limit.
The tool-message sizes are exact for the parsed messages below that limit.
The occupancy components use the non-truncated samples; the sample counts are in the role table.
The largest sessions are truncated; their content sums are lower bounds.
The per-role totals are complete because they come from `usageDetails`.
The component tokens are char-share estimates against the provider input anchor, not a second tokenizer.
The first-call component tokens use the nav1 point estimate; the role averages use the per-role input means.
The analysis-chunk generations have no IO; the mechanism and assigner sessions were reconstructed from their 43 and 10 generation records.
The 163-turn modeller session has 157 truncated turns; the offload response share is used for the curve.
The cache model trusts the provider cache read and the first changed message position; it is not a provider billing record.
The compaction ledger is the durable app log, not a reconstructed estimate.
The pod compaction wiring was added after the recorded trial; the next trial must confirm the pod ledger rows.
The recorded trial has no new trial; the live app still runs the pre-fix binary.
The provider cache lifetime is inferred from the five-minute gap.
The final authority for the provider charge remains the provider bill; Langfuse is the closest observable record.
