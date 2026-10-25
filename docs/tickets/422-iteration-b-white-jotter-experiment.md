# 422 - Iteration B white-jotter experiment

**What to build:** Run iteration B on white-jotter from a fresh project: the impact-elicitation branch, `HUNT_RISK_THRESHOLD=110`, `SKILL_EVOLUTION_ENABLED=0`, 7M capped tokens, batched hunting, deepseek-v4.1-flash with xhigh thinking on the threat modeller and hunter. Measure the green-threat share, the impact and sharp-boundary metrics, the token tax, and the narrowing metrics against the 2026-10-24 arm A baseline.

**Blocked by:** 423

**Status:** open

**Seams:** `eval/setups/white-jotter-iteration-b.yaml`, `eval/measure_utm.py`, `eval/prompts/measure.md`, `docs/experiments`

## Context

The core assessment is whether more than 90% of stored threats are green. The arm also measures whether sharper trust boundaries narrow the hunter's discrimination space: the bound class is a suite parent or leaf, and the linked spec set is substantial and well-formed.

## Acceptance criteria

- [ ] The branch is applied to the eval instance worktree.
- [ ] The instance `.env` carries the arm settings.
- [ ] The trial starts at recon on a fresh project and finishes with a terminal record.
- [ ] `/usage` and the project data directory are polled during the run.
- [ ] `metrics.yaml` and the measurement report are written.
- [ ] The results document compares B with the 2026-10-24 arm A baseline.
- [ ] The green-threat share, severe share, sharp-boundary share, class-binding rate, capped tokens per green threat, and narrowing metrics are reported.
- [ ] Any failure or escalation is surfaced, never patched in code.

## Verification

- `orchestrator trial` and `orchestrator monitor` records
- `eval/measure_utm.py`
- The results document under `docs/experiments/iteration-b-white-jotter-2026-10-25/`
