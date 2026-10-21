---
artifact: experiment-results
version: "1.0"
created: 2026-10-21
status: canary-results
---

# Experiment Results: Unit Threat Model Eval, ComfyUI Canary

## Summary

| Attribute | Value |
|-----------|-------|
| **Experiment ID** | unit-threat-model-eval-2026-10-20-comfyui-canary |
| **Experiment Name** | Recon-to-hunting unit threat model, ComfyUI canary |
| **Status** | Ended early after one canary; not the measured eight-target run |
| **Duration** | 2026-10-20T23:07:40Z to 2026-10-21T01:05:04Z |
| **Traffic Allocation** | One trial, one target, six ground-truth vulnerabilities |
| **Total Sample Size** | 1 target, 6 vulnerabilities, 328 L0 Endpoints |
| **Owner** | Eval operator |
| **Design Doc** | [PLAN.md](PLAN.md) |

The measured eight-target run did not start.
This document reports the ComfyUI canary only.
It is a single-case measurement, not a statistical experiment.
No p-value or confidence interval is meaningful at this sample size.
The full execution and evidence record is in `/opt/polymerhus-dev/eval/runs-utm-20261020/comfyui-1/comfyui-1-20261021T002730-1fc05262/measurements.md` on the eval server.

## Hypothesis Recap

**Original Hypothesis:**

> We believed that the rewritten recon-to-hunting pipeline, operating on a unit threat model with a 7M capped-token trial budget, would identify most of the ComfyUI ground-truth vulnerabilities and produce sharp, grounded threat models, hunter specs, and pod evidence.

**Success Criteria:**

- Primary metric: identification rate above zero on the six ground-truth vulnerabilities.
- Secondary: full L0/L1 unit binding, not a name-only floor.
- Secondary: threat-model and hunter candidates that bind the benchmark's service units.
- Guardrail: the trial must respect the 7M capped-token budget and finish without an unowned provider tail.

The plan's thresholds are in [PLAN.md](PLAN.md).

## Results

### Primary Metric: Ground-Truth Identification

| Variant | Value | Sample Size | Confidence Interval |
|---------|-------|-------------|---------------------|
| Baseline expectation | 6 of 6 identified or partial | 6 vulnerabilities | Not applicable (no control arm) |
| ComfyUI canary | 0 of 6 identified, 0 partial, 6 missed | 6 vulnerabilities | Not applicable (n = 1 trial) |

**Observed Difference:** -6 identifications against the expectation.

**Statistical Significance:**

- p-value: not applicable.
- Confidence level: not applicable.
- Statistically significant: no statistical test is valid for one trial.

**Interpretation:**

The pipeline did not identify any ComfyUI ground-truth vulnerability.
The official assessor marked all six missed with confidence 0.90 to 0.95.
The execution did reach every phase: recon completed, analysis drained, the threat modeller wrote a complete model, the hunter wrote 81 specs, and 15 pod directories were created.
The miss is therefore not a "the pipeline never ran" result.
It is a discovery and delivery result.

### Secondary Metrics

| Metric | Baseline expectation | Canary | Difference | Significant? |
|--------|----------------------|--------|------------|--------------|
| L0/L1 core floor (`core_score >= 0.3`) | 6 of 6 | 6 of 6 | 0 | Not tested |
| L0/L1 full core (`unit + L0 + link`) | 6 of 6 | 2 of 6 | -4 | Not tested |
| Strict unit-level loop candidates | 6 of 6 | 0 of 6 | -6 | Not tested |
| Class-level loop candidates | 6 of 6 | 5 of 6 | -1 | Not tested |
| Manual loop binding (model body names the interface) | 6 of 6 | 2 of 6 | -4 | Not tested |
| Threat-model loops written | 6 | 18 model loops, 17 materialized files | Not comparable | Not tested |
| Hunter specs written | At least 6 ratified candidates | 81 specs, 23 ratified | Not comparable | Not tested |
| Pod directories with an export | 6 | 5 of 15 | Not comparable | Not tested |
| Ground-truth pod confirmations | 6 | 0 | -6 | Not tested |
| Confirmed non-ground-truth symptoms | 0 | 3 | +3 | Not tested |
| Capped tokens | 7,000,000 or less | 4,420,861 | -2,579,139 | Not tested |
| Calls | Not budgeted | 721 | Not applicable | Not tested |

The strict unit-level axis is the benchmark-aligned result: 0 of 6.
The class-level axis is 5 of 6 because the model wrote class-compatible loops for five vulnerabilities, but it bound the wrong L1 unit (`RESTApi:core-http`) rather than the corpus service units.
The manual axis is 2 of 6 because two loop bodies name the exact interface: loop-5 for comfyui-001 and loop-3 for comfyui-002.
That 2 of 6 is a reviewer credit, not an automatic pipeline success.

### Guardrail Metrics

| Metric | Canary | Threshold | Status |
|--------|--------|-----------|--------|
| Capped-token budget | 4,420,861 | 7,000,000 | Pass |
| Trial execution terminal | `failed` on provider 429 while the run later completed | No unowned terminal | Fail |
| Post-terminal spend | 528,690 capped after the trial record's terminal | No unowned spend | Fail |
| Analysis drain | Drained | Must drain | Pass |
| Hunting run terminal | `complete` after the T11 resume | Must complete without manual rescue | Fail |
| Pod specs lost after admission | 8 of 23 ratified specs | 0 | Fail |
| Ground-truth L0 route families | 0 `/userdata`, 0 `/manager` endpoints | Present | Fail |
| Provider failures | Repeated 429s; one trial-terminal failure | No provider-terminal failure | Fail |
| Measurement base | Corrected during measurement; strict unit axis 0 of 6 | Reproducible and honest | Pass after correction |

## Segment Analysis

### By Vulnerability

| Segment | Ground truth | Unit-level candidate | Class-level candidate | Pod reached | Verdict |
|---------|--------------|----------------------|-----------------------|-------------|---------|
| comfyui-001, restricted config read | Yes | No | Yes | No | Missed |
| comfyui-002, stored XSS on user data | Yes | No | Yes | No | Missed |
| comfyui-003, stored XSS on image upload | Yes | No | Yes | No | Missed |
| comfyui-004, arbitrary file read | Yes | No | Yes | No | Missed |
| comfyui-005, stored XSS in manager preferences | Yes | No | Yes | No | Missed |
| comfyui-006, SSRF in model download | Yes | No | No | No | Missed |

The five class-level candidates are not five successes.
They show that the model often reached the right vulnerability class while binding the wrong unit.
The benchmark scores the unit, so the strict result remains zero.

### By Phase

| Phase | Result | Segment insight |
|-------|--------|-----------------|
| Recon | Five-job subset complete | The subset omitted the routes that own four ground-truth vulnerabilities; `/userdata` and `/manager` were absent from L0. |
| Analysis | Drained with 81 `AGGREGATES` edges | The 300-asset split kept the mechanism typist near 200K but the micro-family fix is post-canary. |
| Threat model | Complete model, 18 loops, 18 failure modes | The model bound `RESTApi:core-http`, not the corpus service units; the manager surface was never modelled. |
| Hunter | 81 specs, 23 ratified | Two ground-truth specs were sharp; one near-miss `/view` spec was never ratified. |
| Pod | 15 directories, 5 exports, 3 confirmed non-GT | Eight admitted specs were lost; one provider-degraded triager produced a domain verdict. |
| Measurement | Corrected deterministic base | The corrected axes separate artifact totals, class-level candidates, and unit-level candidates. |

## Learnings

### What We Learned

1. **The dominant loss is pod delivery, not model quality.**
   The threat model and hunter produced sharp ground-truth specs for comfyui-001 and comfyui-002, but the mover consumed the specs at admission and never re-dispatched them after the provider pause.
   The result is F-017 in [FAILURES.md](FAILURES.md).

2. **The unit binding is the second loss.**
   The model wrote a single `RESTApi:core-http` model instead of the corpus service units.
   Class-level work exists for five vulnerabilities, but the strict unit axis is zero.
   The benchmark scores the unit, so a class-only success is still a miss.

3. **Recon coverage is the third loss.**
   L0 has zero `/userdata` and zero `/manager` endpoints although both families are live and unauthenticated.
   Four ground-truth units have no L0 anchor, so the modeller cannot ground them.

4. **The analysis fix works but the canary used the workaround.**
   The 300-asset split drained the analysis and kept the mechanism typist near 200K.
   The structural endpoint micro-family fix is post-canary and was tested with 427 analysis tests.

5. **The provider failure is a harness defect, not a budget breach.**
   The trial spent 4,420,861 of 7,000,000 capped tokens.
   The gateway budget guard was disabled at canary time because the compose file hardcoded `LLM_GATEWAY_BUDGET_ENABLED=false` and overrode the instance `.env`; the provider returned 429s without a cost-guard throttle.
   Post-canary the guard is enabled: the key carries the `$30/7d` and `$60/30d` windows, and the `deepseek-v4.1-flash` cost override is forced.
   The trial client still failed, the run continued, and the 7M cap has no app-side owner.

6. **The measurement base initially inverted the quality axis.**
   The first `metrics.yaml` reported zero loops, specs, and pods because it counted only unit-matched rows.
   The corrected base reports 17 materialized loop files, 81 specs, 15 pods, 5 of 6 class-level candidates, and 0 of 6 unit-level candidates.

### Surprising Findings

- The hunting run completed at 01:05:04Z after the trial record had already failed at 00:27:30Z.
- The post-terminal tail is exactly the three tail agents, which explains the 528,690 capped-token delta.
- All three confirmed pod symptoms are outside the six ground-truth vulnerabilities, while every in-set symptom is missed.

### What We Still Do Not Know

- Whether the eight-target run would produce a different unit-binding result on targets with richer L1 service inventories.
- Whether the F-017 mover fix alone recovers comfyui-001 and comfyui-002, or whether the unit-binding and L0 gaps also block them.
- Whether the manager surface needs a dedicated recon job or an L0 route seed.
- Whether the 7M cap should live in the app, the gateway, or both.

## Recommendation

### Decision: Iterate, do not start the remaining seven targets

**Rationale:**

The canary reached the full pipeline shape, but the discovery result is 0 of 6 and the execution had three high-severity structural failures.
Running the remaining seven targets now would repeat the same delivery, unit-binding, and L0 losses at seven times the cost.
The fixes are critical, simple, and structural; they should be validated on a fresh canary before the measured eight-target run.

### What to Change

- Fix F-017: reconcile consumed pod specs against terminal exports on resume and re-dispatch every consumed spec with no export.
- Bind the threat model to the corpus service units, or add a unit-selection check that refuses a system-level model when a service-level unit owns the interface.
- Add `/userdata` and `/manager` route discovery, or seed the target's own route inventory into L0.
- Apply the F-013 endpoint micro-family fix and the F-015 typed store contracts to the instance.
- Verify the live F-016 budget guard (`$30/7d`, `$60/30d`) and decide the durable 7M budget owner before the next run.
- Keep the corrected measurement axes: report artifact totals, class-level candidates, and unit-level candidates separately.

### Next Experiment

- A fresh ComfyUI canary on the fixed code, with the same five-job subset and the same 7M budget.
- Success gate: analysis drains, hunting completes without a manual resume, at least one ground-truth spec reaches a pod, and the trial terminal is `complete`.
- Only after that gate, run the remaining seven targets serially.

### Timeline

- Fix and test: immediate.
- Canary retest: after the F-017, unit-binding, L0, and F-016 fixes land.
- Eight-target run: after the canary gate passes.

## Next Steps

| Action | Owner | Due Date |
|--------|-------|----------|
| Fix F-017 consumed-spec reconciliation | Implementation | Next change |
| Add unit-binding selection check | Implementation | Next change |
| Add `/userdata` and `/manager` L0 discovery | Recon | Next change |
| Deploy F-013 and F-015 fixes to the instance | Eval operator | Next change |
| Verify the budget guard and choose the 7M budget owner | Eval operator | Next change |
| Rerun the ComfyUI canary | Eval operator | After the fixes |
| Start the remaining seven targets | Eval operator | After the canary gate |

## Appendix

### Raw Data

- Trial: `/opt/polymerhus-dev/eval/runs-utm-20261020/comfyui-1/comfyui-1-20261021T002730-1fc05262/trial.yaml`
- Verdicts: `verdicts.yaml` in the same directory.
- Diagnoses: `diagnoses.yaml` in the same directory.
- Deterministic metrics: `metrics.yaml` in the same directory.
- Measurement: `measurements.yaml` and `measurements.md` in the same directory.
- Failure register: [FAILURES.md](FAILURES.md).
- Layer attribution: [QUALITY-ATTRIBUTION.md](QUALITY-ATTRIBUTION.md).

### Methodology

- One canary trial, no control arm.
- Six ground-truth vulnerabilities, one target.
- Official verdicts from the assessor; diagnoses from the diagnoser.
- Deterministic graph, artifact, verdict, and token metrics from `eval/measure_utm.py`.
- Semantic quality scores from the measurement subagent's rubric in `eval/prompts/measure.md`.
- The corrected deterministic base reports artifact totals and class-level versus unit-level candidates separately.

### Known Issues

- n = 1 trial; no statistical significance.
- The trial record is `failed` while the hunting run completed after the T11 resume; the measurement treats the execution as interrupted and resumed, not as a clean completion.
- The canary used the 300-asset split, not the endpoint micro-family fix.
- The canary used the five-job recon subset, not the full plan.
- The gateway budget guard was disabled at canary time by a compose override; post-canary it is enabled with `$30/7d` and `$60/30d` windows and the forced `deepseek-v4.1-flash` cost override.
- F-015 dropped one four-spec batch; the typed-contract fix is post-canary.
- F-017 lost eight admitted pod specs; the 0 of 6 result is not a clean model-quality baseline.
- The deterministic matcher was corrected during measurement; the strict unit axis remains 0 of 6, while the class axis is 5 of 6 and the manual binding is 2 of 6.

---

*Results documented on 2026-10-21. Decision: iterate before the measured eight-target run.*
