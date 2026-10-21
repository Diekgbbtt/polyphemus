# Failure and error register

This file is append-only during the evaluation.
Each entry names one observed failure or error, its evidence, and its status.
A root cause is recorded only when the evidence supports it.
The final section regroups the entries by failure domain and common root cause.

## Preflight - 2026-10-20

### F-001 - The instance worktree was not aligned with the deployed dev commit

- **Detected:** before the first trial.
- **Signal:** canonical `/opt/polymerhus-dev` was at `5df29930` after the deploy workflow; instance worktree `/opt/polymerhus-dev/eval/instances/eval-server-1` was still at `34f2be38`.
- **Impact:** the agent container mounted `/opt/polymerhus-dev/eval/instances/eval-server-1/src`, so it would have run the pre-integration code.
- **Evidence:** `git -C /opt/polymerhus-dev log -1` versus `git -C /opt/polymerhus-dev/eval/instances/eval-server-1 log -1`; container mount inspection.
- **Status:** resolved.
- **Resolution:** fetched `origin/dev` and reset the instance worktree to `5df29930`.
- **Domain:** delivery and version alignment.
- **Root cause:** the CD workflow owns canonical dev only; it does not advance the instance worktree. The operator assumption that CD advances the instance was false for this setup.

### F-002 - The instance environment was stale

- **Detected:** before the first trial.
- **Signal:** `LLM_COMPACTION_THRESHOLD=0.2`; no `LLM_HUNTING_THREAT_MODELLER`; no `LLM_SKILL_EVOLVER`; LightRAG models pointed at `Apertus` and the unavailable `Qwen3-VL` and `muse-spark` models.
- **Impact:** the new app would fail boot on the missing skill-evolver role, or hunt without the new modeller role; LightRAG extraction and query would fail.
- **Evidence:** container environment and the model probes.
- **Status:** resolved.
- **Resolution:** overwrote the instance `.env` with the new roles, `0.4` threshold, and `RCP-AIaaS/deepseek-ai/DeepSeek-V4.1-Flash` for main, extract, keyword, and query; kept the NVIDIA embedding because the KB store is indexed at dimension 2048.
- **Domain:** configuration.

### F-003 - The running containers had the old environment

- **Detected:** before the first trial.
- **Signal:** the agent, LightRAG, and kali containers predated the worktree and `.env` update.
- **Impact:** the new code was mounted but the processes held the old environment; the new `skills` module and the new model binding were not active.
- **Status:** resolved.
- **Resolution:** recreated `agent`, `lightrag`, and `kali`; health returned `ok`; the new thread and skills endpoints are present.
- **Domain:** deployment lifecycle.

### F-004 - LightRAG model names were unavailable

- **Detected:** model probes before the first trial.
- **Signal:** `RCP-AIaaS/deepseek-ai/DeepSeek-V4-Flash-0731` returned 503; `RCP-AIaaS/deepseek-ai/opencode/muse-spark-1.3-contributor-free-0731` returned 404; `RCP-AIaaS/Qwen/Qwen3-VL-30B-A3B-Instruct` returned 503.
- **Impact:** extraction, keyword, and query generation could fail; the KB would be unavailable to hunting.
- **Status:** resolved.
- **Resolution:** `RCP-AIaaS/deepseek-ai/DeepSeek-V4.1-Flash` returns 200 with visible content. It is now bound for the four LightRAG roles. The embedding binding is unchanged.
- **Domain:** provider and KB configuration.

### F-005 - The old target stacks are still running

- **Detected:** before the first trial.
- **Signal:** `web_comfyui` and `web_white_jotter` containers remain up from an earlier run; `ph-eval-front` remains up with their host configurations.
- **Impact:** resource contention and stale routing entries for the canary.
- **Status:** resolved.
- **Resolution:** the old `web_comfyui` and `web_white_jotter` stacks were removed, their volumes and networks dropped, the stale front configurations deleted, and the kali target aliases cleared. The images and staged data dependencies were preserved.
- **Domain:** target lifecycle.

### F-006 - The trial re-runs target bring-up after `next-target`

- **Detected:** during the canary start.
- **Signal:** `next-target` reported the target ready, then the trial's scoped bring-up recreated the target and the front returned 502 for about two minutes while the app booted.
- **Impact:** a startup delay; the trial waited and proceeded.
- **Evidence:** the front probe history and the target container start time.
- **Status:** observed, not fatal.
- **Domain:** target lifecycle.
- **Root cause:** the native driver calls `next-target` and then `trial`, while `trial` also calls the scoped `orchestrator.up`; both are by design, but the duplicate bring-up costs a boot window.

### F-007 - The automated trial's recon plan differs from the manual target profile

- **Detected:** during the canary recon.
- **Signal:** the recon run has seven jobs, including `whois`, `subdomain_takeover`, and `naabu`.
- **Impact:** the automated trial runs tools the manual OPERATOR target profile excludes for a single-host web app; the off-scope host assets can enter L0 and the analysis.
- **Evidence:** the recon per-job rows and `eval/OPERATOR.md` section 1.2.
- **Status:** resolved in the harness; the measured run uses the subset.
- **Resolution:** `TargetConfig.recon_jobs` and `TrialConfig.recon_jobs` now carry the subset, the CLI passes it, and the trial sends it as the recon launch `jobs` list. The setup uses `httpx`, `httpx_reprofile`, `katana`, `jsluice`, and `arjun`.
- **Domain:** eval configuration and measurement provenance.
- **Root cause:** `TargetRun`/`TrialConfig` had no recon-job selector; the automated trial launched the platform default phase plan. The manual `ph.py recon launch --jobs` contract was not expressible in the orchestrator setup.

### F-008 - The canary stalled on the remote Steel crawl

- **Detected:** during the first canary recon.
- **Signal:** `steel_crawl` was in progress for more than eight minutes with no stats; the Steel API was reachable from kali (`200`), but the Steel browser is remote and the target is the synthetic host `t-1fc05262.target`, which only the eval host and kali resolve.
- **Impact:** the recon phase waited indefinitely on the crawl; the analysis was stuck at its first chunk; the trial could not reach hunting.
- **Evidence:** the recon per-job rows, the Steel API probe, the target alias, and the phase-4 timing.
- **Status:** resolved by aborting the smoke and using the five-job contract.
- **Resolution:** the trial client was terminated and the recon was stopped; the analysis queue was left to drain. The measured run excludes `steel_crawl`.
- **Domain:** recon tool reachability and eval configuration.
- **Root cause:** the full platform plan combined with a remote Steel runtime that cannot resolve or route the local synthetic host. The documented single-host contract excludes `steel_crawl`.

### F-009 - The provider returns reasoning tokens without `reasoning_content`

- **Detected:** during the canary analysis.
- **Signal:** repeated `reasoning gap: profile expects reasoning_content ... but the response message carries no matching value` warnings from `polymerhus.app.llm.reasoning`.
- **Impact:** the reasoning replay/observability surface cannot read the reasoning text, although the usage ledger still records reasoning tokens.
- **Evidence:** the app log warnings at 22:12:47 to 22:14:10.
- **Recurrence:** the 2026-10-21 hunting retest logged the same warning and provider 400 responses on hunter turns. Two hunter steps degraded.
- **Status:** open; still a quality risk.
- **Domain:** provider capability and observability.
- **Root cause:** the models.dev capability profile advertises a `reasoning_content` surface that the relay did not populate on these responses.

### F-010 - The L1 system query references a missing `l0.label` property

- **Detected:** during the canary analysis.
- **Signal:** Neo4j `UnknownPropertyKeyWarning` for `label` in the L1 system witness query.
- **Impact:** the witness-label projection is degraded; the query still returns rows.
- **Evidence:** the Neo4j warning at 22:12:47 and the graph node properties.
- **Status:** open; recorded for the quality measurement.
- **Domain:** graph query and coupling.
- **Root cause:** the query reads `l0.label`, while the L0 node records expose their identity on `name`/`properties`, not a top-level `label` property.

### F-011 - A model-client cleanup task raised after its event loop closed

- **Detected:** during the canary analysis.
- **Signal:** `Task exception was never retrieved` with `httpx.AsyncClient.aclose` raising `RuntimeError: Event loop is closed`.
- **Impact:** a background cleanup error; the model calls still completed.
- **Evidence:** the app log at 22:26:28 and later.
- **Status:** open; low severity.
- **Domain:** async lifecycle and observability.
- **Root cause:** a LangChain/OpenAI async client cleanup is scheduled after its worker loop closes; the request path is not failed.

### F-012 - The L0 technology and observation queries use mismatched schema names

- **Detected:** during the canary analysis.
- **Signal:** Neo4j `UnknownRelationshipTypeWarning: HAS_TECHNOLOGY` and `UnknownPropertyKey: key`; the live graph uses `USES_TECHNOLOGY` and stores observation identity on `name`/`properties`.
- **Impact:** the technology and observation projections return no rows; the analysis grounding is weaker.
- **Evidence:** the app log at 22:12:47 and the graph label inventory.
- **Status:** open; medium severity.
- **Domain:** graph query and coupling.
- **Root cause:** the read query and the write schema diverged; the warning is swallowed as a graph query result.

### F-013 - The canary analysis did not drain under the global 0.4 threshold

- **Detected:** canary attempt 2.
- **Signal:** recon completed with the five-job subset; `mechanism_typist` reached 649,011 tokens against a 400,000 budget; the compaction ledger kept `over_budget=True` with no reduction; the analysis stayed `draining`; the graph stopped at 2,112 nodes and one `AGGREGATES` edge; no hunting run started.
- **Impact:** the canary never reached hunting; no trial record was written; the 7M token budget was not the limiter (950,531 capped, 13,567,363 total, 54 calls).
- **Evidence:** the analysis status, usage ledger, app log, and the missing hunting tree.
- **Status:** upstream root cause fixed in `chunking.py`; 427 analysis tests pass; retest pending.
- **Resolution:** the analysis roles `mechanism_typist` and `assigner` override the global `0.4` with `0.2`; the hunting roles keep `0.4`. The lower threshold alone was not sufficient: canary attempt 3 still jumped to 592K when the 1,128-asset katana block entered the second chunk. The first hard-cap fix split that block into 300-asset slices, but that was a symptom-level workaround. The structural fix is the F-013 correction in `_family_key`: chunks are packed from COHERENT ENDPOINT MICRO-FAMILIES, one `(baseurl, endpoint path)` family holding the Endpoint plus the Headers, Parameters and endpoint-anchored Secrets that target it. The builder stacks whole micro-families until adding the next would exceed `CHUNK_MAX_ASSETS=300`; the old `(baseurl, content-class)` bucket family is retired. A pathological single family above 300 is still split as a safety valve. The analysis suites pass (427 tests).
- **Domain:** analysis, L0 chunking, compaction, and configuration.
- **Upstream root cause:** `chunking._family_key` grouped every Endpoint under one `(baseurl, content-class)` family and routed every Header to host-meta. A katana crawl of 1,128 Endpoints therefore produced ONE atomic family, not 1,128 micro-families. The family was inserted into the mechanism-typist thread as one recent block; the compaction backstop cannot fold a recent block of that size at either 0.4 or 0.2, so the thread grew to 592K-649K and never drained. The threshold was never the limiting control. The headers were also separated from the endpoints they target because the Header identity's `endpoint` key was not read by `_endpoint_path_of`.
- **Fix evidence:** `src/polymerhus/analysis/chunking.py::_family_key` now keys Endpoint/Parameter/Secret/Header on `(baseurl, endpoint path)`; `_endpoint_path_of` reads the Header's `endpoint` identity key; `chunks_for_job` packs to `CHUNK_MAX_ASSETS` only. Tests: `tests/integration/test_chunking_contracts.py` D2/D4/D5 and the 400-asset cap test.

### F-014 - The gateway sync logs a gateway key in a request URL

- **Detected:** on the app restart after the canary abort.
- **Signal:** `INFO httpx: HTTP Request: GET http://127.0.0.1:4000/key/info?key=sk-ph-...`.
- **Impact:** an internal gateway key is written to the agent container log; the log is root-readable on the eval server.
- **Evidence:** the agent startup log at 22:43:50.
- **Status:** open; security finding.
- **Domain:** secret handling and logging.
- **Root cause:** the gateway sync uses the key as a query parameter and httpx's INFO logger records the full URL. The key should be sent in a header or the URL must be redacted before the log record.

### F-015 - The hunter emitted an unparsable `hunts_store` tool call

- **Detected:** during the canary 4 hunter phase.
- **Signal:** `LiteLLM:WARNING ... Failed to parse tool call arguments for tool 'hunts_store' (chat completions). Error: Expecting ',' delimiter: line 1 column 15956 (char 15955).` The model was writing four specs in one call; the arguments were about 16KB.
- **Impact:** the spec set in that call was not written; the hunter continued, but the failed write removes four candidate specs from the pod path. The hunter tree held 18 YAML files at the observation; the pod tree still had zero.
- **Evidence:** the agent log at 2026-10-21T00:04:22; the `hunts_store` argument payload; the hunter tree count.
- **Status:** typed contract fixed and deployed; the transport-level truncation recurred in the 2026-10-21 retest and is tracked as F-025.
- **Resolution:** the `hunts_store` write contract is now the typed canonical shape. `SpecWrite` requires `status`, `fault_keyword`, `strategy_keyword` and `target_identity`; `target_identity` reuses the shared `spec_contract.TargetIdentity`; `provenance` is the typed `spec_contract.SpecProvenance` (including the typed `SkillProcedure`); `extra="forbid"` replaces the former open `dict`/`extra="allow"` surface. The modeller's `sections` is the typed `threat_model.ModelSections`, not an open mapping. The shared `StoreToolBase` now returns a coded teaching rejection naming the missing or unknown field path and the accepted required/optional set, and returns a `ToolMessage` when called from LangGraph. The generic rule is documented in `docs/design/hunting-tools-design.md`, `app/memory/tool_contract.py`, and `attack/hunting/CONTEXT.md`.
- **Domain:** hunter/modeller tool contract, structured output, and tool-call size.
- **Upstream root cause:** the tool exposed `target_identity: dict`, `provenance: dict`, and `extra="allow"` while the pod's canonical `TestImplementationSpec` is `extra="forbid"` with typed nested models. The schema therefore invited a large, loosely-checked JSON object; the model had to invent the nested shape and the field names, which is exactly where a 16KB call with a delimiter error becomes possible. The symbolic layer's later validation cannot recover a call the relay parser rejected. The contract now teaches the shape before the turn.
- **Residual risk:** a malformed JSON tool call is still a transport-level risk; the typed schema reduces the surface but cannot make the provider's JSON parser infallible. A follow-up should bound the per-call spec batch or make the write resumable per spec.

### F-016 - The gateway has no request smoother, and the 7M cap is not app-durable

- **Detected:** canary 4 hunting; provider 429s.
- **Signal:** the trial record terminal is `failed` with `failure: provider unavailable (no status)` at 2026-10-21T00:27:30Z, while the same hunting run later finished `complete` at 01:05:04Z after the T11 operator resume. The app log shows repeated `litellm.RateLimitError ... Upstream request failed: Endpoint is unavailable ... 429` during the pod phase.
- **Impact:** the trial client died on the first provider failure; the hunting run paused, then continued after the operator resume. The run spent 4,420,861 capped tokens; the trial record froze at 3,892,171. The 7M trial cap was never reached, so the cap was not the trigger.
- **Evidence:** `trial.yaml` (`token_budget: 7000000`, `spent_tokens: 3892171`, hunting failure), the hunting run row (`complete`, finished 01:05:04Z), the usage ledger (4,420,861 capped, 721 calls), the app log 429s, and the live gateway env (`LLM_GATEWAY_BUDGET_ENABLED=false`, no `LLM_GATEWAY_KEY_RPM_LIMIT`).
- **Status:** budget-guard root cause fixed and verified live; 7M cap durability gap open.
- **Domain:** eval harness, LiteLLM gateway, provider availability, and budget enforcement.
- **Upstream root causes:**
  1. **The compose file hardcoded the guard off.** `docker-compose.yml` set `LLM_GATEWAY_BUDGET_ENABLED: "false"` in the agent service's `environment` block. Docker Compose gives `environment` precedence over `env_file`, so the instance `.env` value was silently ignored. The gateway therefore minted every virtual key with no `budget_limits`; the target model was priced but the guard could not enforce the pre-configured limit.
  2. **The 7M cap is trial-client-scoped.** `TrialRunner._check_spend` enforces it by polling; the app process never loads it. The trial failed at 3,892,171 capped tokens, and the hunting run continued to 4,420,861 after the client died. The cap was not breached, but the run was unsupervised after the failure.
- **Fix:** `docker-compose.yml` now interpolates `${LLM_GATEWAY_BUDGET_ENABLED:-false}` and the two USD windows, so the instance `.env` controls them. The eval instance sets `LLM_GATEWAY_BUDGET_ENABLED=true`, `$30/7d`, `$60/30d`, and `k=1.0`; no RPM is set. The live key now carries `budget_limits` for 7d (`$30`) and 30d (`$60`). `opencode-go/deepseek-v4.1-flash` is registered with `cost_source=provider-override` and the forced `$0.15/$0.60/$0.003` per 1M costs, so the guard prices the eval model rather than failing open on it. The key's current spend is `$13.18` against the `$30/7d` window.
- **Residual:** the gateway warns that 53 other registered models are unpriced and would fail open; none are used by the eval roles. The 7M trial cap still needs an app-side owner or a stop-on-terminal rule; the current T11 resume has no budget owner.

### F-017 - An admitted pod spec is lost when the run pauses on a provider failure

- **Detected:** by the official diagnosis of canary 4 (comfyui-001, `pod_notsufficient_space_coverage`).
- **Signal:** the ratified spec `shared-store-namespace_manager-config-read` was admitted and moved from `produced/` to `consumed/` at 2026-10-21T00:18:20Z, then the run paused on the provider failure at 00:27:30. The spec has no `test-executor-pod/` directory and no PodExport. The run later completed at 01:05:04 without re-dispatching it.
- **Impact:** the pod never executed the exact ground-truth read that the threat model and hunter had bound; comfyui-001 was scored missed even though the model and spec were correct.
- **Evidence:** `diagnoses.yaml` comfyui-001; `mover.py::_spec_items`, `deduce_delivery`, `consume_spec`; `surfer.py::_run_pod_session`.
- **Status:** fixed; regression covered.
- **Domain:** pod delivery, resume, and at-least-once semantics.
- **Root cause:** `DispatchFeedback.ADMITTED` moves a spec to `to_move`, and `consume_spec` renames it into `consumed/` at admission. `mover._spec_items` re-read only `produced/`, so a spec consumed before its pod finished was never re-dispatched. A provider pause that cancelled the pod session left a consumed spec with no terminal export; the resume path did not reconcile `consumed/` against terminal exports.
- **Fix:** `mover.read_produced_inbox` now reconciles the consumed side when the pod store is bound. A consumed `ratified` spec whose typed `provenance.run_id` names THIS run and whose `PodMemoryStore.read_pod_export(spec_id, run_id)` is empty is recovered as a `TestSpecItem` (`recovered=True`) and dispatched through the same pod session. A terminal export of either verdict ends recovery; a foreign run or a legacy spec without a run id is never guessed. `HuntsStoreTool` binds the current run id into every spec's provenance, so the attribution is durable and model-independent. The surfer's `run_work_remaining`/quiesce read uses the same reconciliation, so the run cannot quiesce past a lost spec. Tests: `test_C40_consumed_ratified_spec_without_export_is_redispatched`, `test_C41_consumed_spec_with_an_export_or_a_foreign_run_is_not_redispatched`, and the store's consumed-side inventory.

### F-018 - The progressive risk halt stopped the intake after one unit

- **Detected:** by the comfyui canary layer attribution.
- **Signal:** `intake_position=1`, `crossing_unit=RESTApi:core-http`, `blocked_unit=ReverseProxy`, `risk_total=44`, `risk_threshold=12`; the expected manager units sat at positions 24, 28, and 29 and were never modelled.
- **Impact:** comfyui-005 and comfyui-006 had no model, loop, spec, or pod.
- **Status:** mitigated for the retest; calibration remains open.
- **Fix:** `HUNT_RISK_THRESHOLD=1000` is set in the eval instance `.env` for the coverage runs, so the intake is not halted before the manager surfaces. The structural follow-up is a coverage floor or a calibrated threshold, not a per-run override.

### F-019 - L1 service links and L0 route families were missing

- **Detected:** by the comfyui canary layer attribution.
- **Signal:** `workflow-library`, `extension-manager-configuration`, and `model-installation` exist in L1 with zero links; `RESTApi:manager-http` is a bare data-dependency node; L0 has zero `/userdata` and zero `/manager` endpoints.
- **Impact:** the analysis layer contributed to four misses, and the manager units ranked below the halt.
- **Status:** open; the comfyui hunting retest still had 0 of 6 strict unit-level candidates, although class-level coverage reached 5 of 6. The white-jotter fresh trial exercises the same analysis path.
- **Retest evidence:** 39 specs across 9 loops, including manager catalogue and extension-inventory candidates, all bound to `RESTApi:core-http`, not the corpus service units.
- **Structural follow-up:** ingest or link the service-to-API edges, and seed the target's route inventory into L0.

### F-020 - The hunter terminal set silently omitted a drafted spec

- **Detected:** by the comfyui canary layer attribution (comfyui-003).
- **Signal:** the `/view` SVG spec was written as `hypothesised` at 00:10:24, but the terminal write at 00:27:02 persisted only the three `/userdata` specs and claimed `/view` coverage.
- **Impact:** the correct artefact-route test never reached a pod.
- **Status:** fixed.
- **Fix:** `HunterMemoryStore.write_specs` rejects a terminal write that omits a previously produced hypothesised spec, and the `hunts_store` tool returns a coded `incomplete_spec_set` response naming the missing identities. The hunter must promote or explicitly drop every draft; the refusal is atomic.

### F-021 - Path traversal was closed on literal-only probes

- **Detected:** by the comfyui canary layer attribution (comfyui-004).
- **Signal:** IA-3 probed literal and single-encoded `/view` traversal only, then declined the class; the path-traversal suite skill was not loaded.
- **Impact:** no loop or spec for the double-decoding bypass.
- **Status:** prompt fix validated at class level; pod confirmation pending.
- **Retest evidence:** the hunter wrote `/view` subfolder-decode, metadata-path-join, and viewvideo path-join specs. The run stopped before a terminal pod export.
- **Fix:** the threat-modeller prompt now states the encoding floor for arbitrary-file-read/path-traversal/LFI/RFI: a literal or single-encoded probe is not a fundamental technical-infeasibility finding; the class skill's normalization and double-encoding bypass must run before a drop.

### F-022 - A consumed hunting loop is lost when the run pauses on a provider failure

- **Detected:** during the 2026-10-21 comfyui hunting retest.
- **Signal:** the first attempt moved 13 of 15 core-http loop files from `produced/` to `consumed/` at dispatch, then the provider returned 429 and the trial died. Hunter output was zero specs. The resume path did not re-dispatch the 13 consumed loops.
- **Impact:** 13 of 15 hunter sessions were lost. The operator restored the files manually before the resume, so the retest could proceed.
- **Evidence:** `threat_modeller/consumed/RESTApi-core-http/loop-1.yaml` through `loop-13.yaml`; no `hunter/test-specs/` output; the 13 files moved back to `produced/` at 13:59:05Z.
- **Status:** open; manual recovery only.
- **Domain:** hunting dispatch, resume, and at-least-once semantics.
- **Root cause:** loop files are consumed at dispatch with no durable completion marker. The F-017 reconciliation covers pod specs, not threat-model loops. A provider pause after loop consumption leaves no state that identifies the unfinished loops.
- **Follow-up:** add a loop lease or completion marker and recover consumed loops with no terminal hunter output on resume.

### F-023 - A quota-exhausted run is terminal after a provider key rotation

- **Detected:** during the 2026-10-21 comfyui hunting retest.
- **Signal:** `POST /hunting/{run_id}/resume` returned `the provider period quota is exhausted; the run is terminal and is not resumed`, even after the new key reported weekly `0%`, monthly `0%`, and rolling `0%`.
- **Impact:** the operator had to patch `hunting_runs.stats.quota_exhausted` to `false` in PostgreSQL before the run would resume. The old stats are preserved at `_backup/utm-comfyui-provider429-20261021T135905Z/run-stats-before-resume.json`.
- **Evidence:** resume refusal at 13:59:05Z; `UPDATE 1`; resume returned `{"resumed":true}`.
- **Status:** open; operator workaround only.
- **Domain:** run resume policy and provider identity.
- **Root cause:** `resume_decision` treats `quota_exhausted=true` as terminal because the old provider period will not recover. It has no operator override for a rotated key that restores quota immediately.
- **Follow-up:** add an explicit operator `force` or `top_up` resume path that re-checks the live provider key before refusing.

### F-024 - The capped-token watchdog overshoots because the stop is asynchronous

- **Detected:** during the 2026-10-21 comfyui hunting retest.
- **Signal:** the watchdog stopped the project at `resume_spent=2,028,454`, but the live usage continued to `7,806,215`. The retest delta is `3,355,148` capped tokens against the `3,000,000` budget, an overshoot of `355,148`.
- **Impact:** the trial exceeded the native cap by 11.8 percent. The overshoot is from calls already in flight when `execution/stop` was issued.
- **Evidence:** `/tmp/comfyui-resume-watch.log`; `/usage` at 7,806,215; `trial.yaml` `spent_tokens: 3355148`.
- **Status:** open; the F-016 app-side cap remains the structural fix.
- **Domain:** budget enforcement and run control.
- **Root cause:** the cap owner is a polling shell watchdog. `execution/stop` is not a pre-emptive reservation and does not cancel in-flight provider calls.

### F-025 - A multi-spec `hunts_store` call is truncated at 3,686 characters

- **Detected:** during the 2026-10-21 comfyui hunting retest.
- **Signal:** `LiteLLM:WARNING ... Failed to parse tool call arguments for tool 'hunts_store' ... Error: Expecting ',' delimiter: line 1 column 3686 (char 3685).` The model was writing five specs in one call.
- **Impact:** five hypothesised specs were not written in that turn. The typed contract from F-015 did not prevent transport-level truncation.
- **Evidence:** app log at 14:04; loop-9 spec set; `hunts_store` argument size.
- **Status:** open.
- **Domain:** hunter tool transport and spec batching.
- **Root cause:** the per-call argument payload is large and the relay parser rejects the truncated JSON before the typed contract can validate it.
- **Follow-up:** bound the spec batch per call, or write each spec as its own resumable call.

## Runtime trials

### Canary attempt 1 - comfyui-1 - project c289978e-c321-4ff2-894d-587b12f575f2

- **Started:** 2026-10-20T22:11:38Z.
- **Aborted:** during phase 4 on the stalled `steel_crawl` (F-008).
- **Recon run:** 15a1810f-e6fc-4bc1-a5a7-3042cb9ce254; stopped.
- **Target:** t-1fc05262.target, front 200.
- **App-level evolver thread:** `skills:c289978e-c321-4ff2-894d-587b12f575f2:evolver` was listed by `/projects/{id}/threads`.
- **Early L0/L1:** 969 nodes after the first analysis chunk; 22 L1 Services, 9 L1 Systems, 117 Endpoints, 793 Headers; one AGGREGATES edge.
- **Early tokens:** about 1.55M capped before the abort; assigner, mechanism_typist, and triager only.
- **Trial record:** none; the client was terminated before the terminal write.
- **Disposition:** smoke failure only; a fresh canary is required with the five-job subset.

### Canary attempt 2 - comfyui-1 - project f02194fa-e6de-4fe4-a640-ebfdd434e213

- **Started:** 2026-10-20T22:26:01Z.
- **Recon:** complete with the five-job subset: `httpx`, `katana`, `jsluice`, `httpx_reprofile`, `arjun`.
- **Target:** t-1fc05262.target, front 200.
- **L0/L1 after recon:** 2,112 nodes; 22 L1 Services, 9 L1 Systems, 328 Endpoints, 1,722 Headers, 10 Parameters, 4 Secrets; one `AGGREGATES` edge.
- **Analysis:** never drained; `mechanism_typist` 649,011 tokens, budget 400,000, `over_budget=True`, no reduction.
- **Tokens at abort:** 950,531 capped, 13,567,363 raw, 54 calls.
- **Hunting:** none.
- **Trial record:** none; the client was terminated.
- **Disposition:** smoke failure F-013; retest with the analysis-role `0.2` override.

### Canary attempt 3 - comfyui-1 - project 11cad59c-887f-4baa-ab98-dc4e71169fb8

- **Started:** 2026-10-20T22:49:46Z.
- **Trial PID:** 2192994; terminated.
- **Eval SHA:** `a4f47939`.
- **Stack fingerprint:** `8d3f079c93337c4c628f100ad0cb797f11d8829a33c0a31abc2ce29afed17b36`.
- **Instance env hash:** `577e942c0acd12e779bd54ad5199061ea8e69f75acee1a4bd023647f26fb782f`.
- **Recon:** five-job subset; `arjun` was still in progress when the analysis stalled.
- **Analysis:** first chunk completed in 230.4s with 12 L0 assets and 0 AGGREGATES; the second chunk inserted the 1,128-asset katana family and jumped to 592,522 against a 200,000 budget; `over_budget=True` persisted with no reduction through 596,798.
- **Tokens at abort:** 815,198 capped, 3,860,958 raw, 31 calls.
- **Graph at abort:** 2,114 nodes, 328 Endpoints, 1,722 Headers, 10 Parameters, 4 Secrets; `EXPOSED_VIA` 4, `FRONTED_BY` 19, `EVIDENCED_BY` 10; no `AGGREGATES`.
- **Hunting:** none.
- **Trial record:** none; the client was terminated and the analysis worker cleared by an agent restart.
- **Disposition:** the 0.2 threshold alone does not fix F-013; the chunk hard cap is the corrective fix.

### Canary attempt 4 - comfyui-1 - project 65f63a5a-1406-4635-9bba-92e23aa86d3d

- **Started:** 2026-10-20T23:07:40Z.
- **Eval SHA:** `9e9e8522`.
- **Stack fingerprint:** `887934226c291a6d54e40c552f85853c6690ac545bc64d7cd11489bd1fa54414`.
- **Analysis:** drained with the 300-asset cap. The mechanism-typist hovered at 200K-235K per chunk, the chunk-boundary reset worked, and the four katana/jsluice chunks completed. The analysis wrote 81 `AGGREGATES` edges and 13 `EXPOSED_VIA` edges.
- **Hunting:** started at 23:32:19; froze 32 units; the threat modeller produced a rich `RESTApi:core-http` model with six interface agreements, 15 assumptions, three observed violations, and 17 loops.
- **Hunter:** started; 18 YAML files under the hunter tree; the `hunts_store` parse failure F-015 dropped one four-spec batch; the pod tree had not started at the observation.
- **Usage at 01:00:** 2,786,586 capped, 32,159,898 raw, 401 calls; agents: assigner, hunting_threat_modeller, hunting_hunter, mechanism_typist, triager.
- **Hunting terminal:** the trial record is `failed` (provider unavailable, no status) at 00:27:30; the T11 operator resume returned 202 and the hunting run later reached `complete` at 01:05:04. The trial record was not rewritten.
- **Final usage:** 4,420,861 capped, 44,975,090 raw, 721 calls; agents: assigner, hunting_threat_modeller, hunting_hunter, mechanism_typist, pod_runner, pod_triager, triager.
- **Artifacts:** 18 model loops (17 materialized loop files), 81 spec files, 15 pod directories with 36 YAML files; the pod phase started and produced five exports.
- **Verdicts:** the official assessor marked all 6 comfyui vulnerabilities `missed`. `diagnoses.yaml` is present for all 6; the leading diagnosis is F-017 (consumed spec lost on the provider pause), with other rows covering pod coverage and evidence gaps.
- **Structural limitations:** the run used the five-job recon subset; the analysis used the 300-asset split (the endpoint micro-family fix is post-canary); the global 0.4 hunting compaction and 0.2 analysis override; the gateway budget guard was disabled by a compose override; the trial record is failed while the run was resumed manually; the T11 resume has no budget owner. Layer attribution is in [QUALITY-ATTRIBUTION.md](QUALITY-ATTRIBUTION.md).
- **Disposition:** the pipeline reached analysis-drain, threat-model, hunter, and pod phases, but the discovery quality was 0/6 and the execution was interrupted. It is a measurement case, not a clean baseline.


### Hunting retest - comfyui-1 - project 65f63a5a-1406-4635-9bba-92e23aa86d3d

- **Run:** `cdf0918c-6ff1-4abd-893c-18d018113523`.
- **First attempt:** started 2026-10-21T12:28:06Z; interrupted at 12:45:58Z by provider 429 with `quota_exhausted=true` on the primary key.
- **First-attempt spend:** 990,160 capped tokens.
- **First-attempt artifacts:** one core-http model, 15 loops, 13 consumed and 2 produced, zero hunter specs, zero pod directories.
- **Recovery:** new opencode-go key applied to the instance `.env`; agent recreated; 13 consumed loop files restored to `produced/`; `stats.quota_exhausted` cleared; resumed at 13:59:05Z.
- **Stop:** watchdog reached the 3M retest bound at 14:18:47Z and stopped the project.
- **Final spend:** 3,355,148 capped tokens, 1,204 calls. The budget was 3,000,000; the overshoot was 355,148.
- **Artifacts:** 15 loops, 39 specs, 19 pod directories. The 39 specs split into 22 `ratified`, 16 `hypothesised`, and 1 `dropped`. Nine loops produced specs.
- **Quality:** 0 of 6 unit-level candidates, 0 of 6 confirmed pods, 5 of 6 class-level candidates. The run stopped before any terminal pod export.
- **New defects:** F-022, F-023, F-024, F-025; F-009 recurred.
- **Disposition:** capped measurement, not a complete trial. The white-jotter trial is held.

## Final clustering

- The canary 4 discovery result is 0/6. The dominant diagnosed cause is F-017: a ratified spec was consumed and lost when the provider pause interrupted the pod session. This is a delivery bug, not a model-quality miss.
- The 2026-10-21 hunting retest reached 39 specs and 19 pod directories, but it remained 0/6 at the unit level and 0 confirmed at the pod level. The run stopped at the cap before pod completion.
- The retest added four open defects: F-022 loop loss on resume, F-023 quota-terminal resume, F-024 cap overshoot, and F-025 tool-call truncation. F-009 recurred.
- F-013's upstream cause was family construction, not the compaction threshold; the endpoint micro-family plus 300-asset packing is the structural fix.
- F-015's upstream cause was the open JSON contract; the typed `SpecWrite`/`SpecProvenance`/`ModelSections` and coded field rejection are the structural fix.
- F-016 has two causes: the compose file hardcoded the budget guard off, and the 7M cap is trial-client-scoped. The guard is now enabled and the live key carries the `$30/7d` and `$60/30d` windows; the `deepseek-v4.1-flash` cost override is forced. The durable 7M binding remains open.
