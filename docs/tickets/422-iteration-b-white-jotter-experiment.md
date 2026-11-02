# 422 - Iteration B white-jotter experiment

**What to build:** Run iteration B on white-jotter from a fresh project: the impact-elicitation branch, `HUNT_RISK_THRESHOLD=110`, `SKILL_EVOLUTION_ENABLED=0`, 7M capped tokens, batched hunting, deepseek-v4.1-flash with xhigh thinking on the threat modeller and hunter. Measure the green-threat share, the impact and sharp-boundary metrics, the token tax, and the narrowing metrics against the 2026-10-24 arm A baseline.

**Blocked by:** 423

**Status:** done

**Seams:** `eval/setups/white-jotter-iteration-b.yaml`, `eval/measure_utm.py`, `eval/prompts/measure.md`, `docs/experiments`

## Context

The core assessment is whether more than 90% of stored threats are green. The arm also measures whether sharper trust boundaries narrow the hunter's discrimination space: the bound class is a suite parent or leaf, and the linked spec set is substantial and well-formed.

## Result

The run completed on 2026-10-26T03:11:21Z at commit `81522a71`.

- 26 stored threats, all 26 class-bound (100%).
- 10 green narrow (38.5%), 15 green broad (57.7%). The 90% gate fails.
- 10 severe (38.5%); zero severe threats below the medium risk bucket.
- 104 specs; 21 substantial sets; 1 well-formed set (3.8% of threats, 4.8% of substantial); 20 of 21 substantial sets overlap.
- 7,017,453 capped tokens (17,453 over the cap, 0.25%).
- Official discovery: 0 identified, 1 partial, 6 missed.
- 86 pod directories, 66 exports, 4 successes, 58 watchdog envelopes, 20 without an export.
- Trial terminal `failed` because the budget-stop POST timed out after the app run had stopped.

The full result is `docs/experiments/iteration-b-white-jotter-2026-10-25/RESULTS.md`.

## Acceptance criteria

- [x] The branch is applied to the eval instance worktree.
- [x] The instance `.env` carries the arm settings.
- [x] The trial starts at recon on a fresh project and finishes with a terminal record.
- [x] `/usage` and the project data directory are polled during the run.
- [x] `metrics.yaml` and the measurement report are written.
- [x] The results document compares B with the 2026-10-24 arm A baseline.
- [x] The green-threat share, severe share, class-binding rate, capped tokens per green threat, and narrowing metrics are reported.
- [x] The sharp-boundary share is reported as not measurable: the threat schema has no boundary-shape field. Follow-up ticket 430 carries the field.
- [x] Any failure or escalation is surfaced, never patched in code.

## Verification

- `artifacts/trial.yaml`
- `artifacts/metrics.yaml`
- `artifacts/measurements.yaml` and `artifacts/measurements.md`
- `artifacts/verdicts.yaml` and `artifacts/diagnoses.yaml`
- `RESULTS.md`
