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

## Final clustering

Pending.
