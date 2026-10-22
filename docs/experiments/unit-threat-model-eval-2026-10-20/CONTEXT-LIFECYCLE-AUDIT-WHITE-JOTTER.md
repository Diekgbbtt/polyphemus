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

## Executive answer

The hunting subsystem accounts for 91,970,064 of the 94,703,380 Langfuse project tokens, or 97.1%.
It accounts for 1,348 of 1,430 generations, or 94.3%.

The total is high because every session re-sends a large working context on every model call.
The context is large because several tools return full, sparse payloads and the compaction layer does not interpose at the tool boundary.

The largest single payloads are:

- the 50-row HTTP-history page at 74,649 chars, about 18.7k tokens;
- the full KB answer at 89,087 chars, about 22.3k tokens;
- the full redacted auth store at 22,302 chars, about 5.6k tokens; the two auth YAML files are 7,476 bytes;
- the full skill body at 20,898 chars, about 5.2k tokens;
- a raw terminal result that adds 17,773 tokens in one step.

The compaction budget is 400,000 tokens, which is 0.4 of the model's 1,000,000-token window.
The modeller reached 401,278 tokens and compacted once, reclaiming 196,204 tokens.
The hunters peaked at 135,235 tokens and never compacted.
The pod runner and pod triager have no compaction ledger at all, because the production pod path does not inject the middleware.

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
| pod_runner | 1,000,000 | 0.4 if wired | 400,000 if wired | no | 0 | 94,424 input |
| pod_triager | 1,000,000 | 0.4 if wired | 400,000 if wired | no | 0 | 76,557 input |
| assigner | 1,000,000 | 0.2 | 200,000 | yes | 10 | 43,799 |
| mechanism_typist | 1,000,000 | 0.2 | 200,000 | yes | 43 | 95,280 |
| job_orchestrator | 1,000,000 | 0.4 | 400,000 | yes | 13 | 26,619 |
| triager | 1,000,000 | 0.4 | 400,000 | yes | 9 | 35,757 |

The `.env` sets `LLM_COMPACTION_THRESHOLD=0.4`, `LLM_COMPACTION_THRESHOLD_ASSIGNER=0.2`, and `LLM_COMPACTION_THRESHOLD_MECHANISM_TYPIST=0.2`.
The app log confirms `budget=400000` for the hunting roles and `budget=200000` for the analysis roles.

The pod role has no ledger row because `arun_pod` defaults `runner_middleware=()` and `triager_middleware=()`.
The production `run_pod_session` path does not supply them.
The builders `runner_compaction_middleware` and `triager_compaction_middleware` exist, but the pod path never calls them.

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
It contains 27,920 system-message chars, 1,761 application-overview chars, 35,491 loop-payload chars, 37,330 preloaded tool-result chars, and the remaining tool-schema and request-framing chars.
The 25k-token figure is plausible at about four chars per token.
The 19k-word figure is a rough token-to-word conversion, not a separate fault.
The earlier component sentence omitted the preloaded tool results; the corrected breakdown is above.

The hunter's fixed first-call context is about 25k tokens.
At 397 hunter calls, the fixed first-call context alone is about 9.86M tokens.
Across the four hunting roles, the first-call context is about 19.8M tokens, or 20.9% of the total.
The system prompt is served on every turn.
The tool schemas and the long tool descriptions ride every request.
The system prompt, the application overview, the loop payload, the preloaded tool results, and the tool schemas are the fixed tax.

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
The pod path has no compaction ledger.
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
Read `arun_pod` and the surfer path for the middleware.
The pod path passes none.

**Root cause.** The compaction is a turn-end/next-model barrier at 0.4 of the model window.
The hunter and pod sessions stay below that budget, so the pass never runs.
The tool-output offload is coupled to the pass, so it never runs either.
The pod path does not inject the middleware.

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

### Not approved

- the inline tool-response offload;
- the broad KB, HTTP-history, graph, exec, and store bounds;
- the task budget or threshold change;
- F-024 stop fencing and post-stop artifact handling;
- trial-record stamping.

### Analysis and proposals

- the component occupancy breakdown;
- the loop-payload entity map;
- the preloaded tool-message inventory;
- the system-prompt compression proposal;
- the n-turn offload simulation.

The system-prompt, loop-payload, and preloaded-message compressions are design decisions.
They stop at the proposal for the user's decision.
The n-turn offload experiment is an analysis; it does not change production code.

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

## Limitations

The Langfuse generation `input` is truncated at about 256k chars.
The tool-message sizes are exact for the parsed messages below that limit.
The largest sessions are truncated; their sizes are lower bounds.
The per-role totals are complete because they come from `usageDetails`.
The compaction ledger is the durable app log, not a reconstructed estimate.
The cache explanation is a timing correlation, not a provider billing record.
The provider cache lifetime is inferred from the five-minute gap.
The final authority for the provider charge remains the provider bill; Langfuse is the closest observable record.
