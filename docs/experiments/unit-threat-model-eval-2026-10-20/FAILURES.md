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
- **Status:** open; recorded for the quality measurement.
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
- **Status:** root cause identified; hard-cap fix implemented; retest pending.
- **Resolution:** the analysis roles `mechanism_typist` and `assigner` override the global `0.4` with `0.2`; the hunting roles keep `0.4`. The lower threshold alone was not sufficient: canary attempt 3 still jumped to 592K when the 1,128-asset katana family entered the second chunk. The chunker now has a hard `CHUNK_MAX_ASSETS=300` cap; a family above it splits into ordered hard-cap sub-chunks. The normal families stay atomic. The chunker and analysis suites pass (427 tests).
- **Domain:** analysis, chunking, compaction, and configuration.
- **Root cause:** a 1,128-asset katana family is atomic and enters one mechanism-typist chunk as a single recent block. The compaction backstop cannot fold a recent block of that size at either 0.4 or 0.2, so the thread grows to 592K-649K and never drains. The threshold is not the limiting control; the chunk size is.

### F-014 - The gateway sync logs a gateway key in a request URL

- **Detected:** on the app restart after the canary abort.
- **Signal:** `INFO httpx: HTTP Request: GET http://127.0.0.1:4000/key/info?key=sk-ph-...`.
- **Impact:** an internal gateway key is written to the agent container log; the log is root-readable on the eval server.
- **Evidence:** the agent startup log at 22:43:50.
- **Status:** open; security finding.
- **Domain:** secret handling and logging.
- **Root cause:** the gateway sync uses the key as a query parameter and httpx's INFO logger records the full URL. The key should be sent in a header or the URL must be redacted before the log record.

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

### Canary attempt 4 - comfyui-1 - pending

- **Trigger:** after the `CHUNK_MAX_ASSETS=300` fix is deployed.
- **Expected analysis shape:** five chunks for the comfyui delta (12, 300, 300, 300, 216 assets); the mechanism-typist should stay near 150K and below the 200K budget.
- **Gate:** the analysis must drain, hunting must start, and the official verdict tree must complete.

## Final clustering

Pending.
