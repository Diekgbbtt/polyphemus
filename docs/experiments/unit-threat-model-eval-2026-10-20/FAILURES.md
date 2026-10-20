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
- **Status:** open.
- **Next step:** tear down the old target stacks and stale front configurations before the canary, preserving the images and data dependencies.
- **Domain:** target lifecycle.

## Runtime trials

No runtime trial has started.
Entries will be appended after each probe and each trial.

## Final clustering

Pending.
