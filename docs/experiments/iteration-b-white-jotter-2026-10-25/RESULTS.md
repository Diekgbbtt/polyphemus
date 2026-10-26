---
artifact: experiment-results
version: "1.0"
created: 2026-10-26
status: interim
---

# Experiment Results: Iteration B white-jotter impact elicitation

## Summary

| Attribute | Value |
|---|---|
| **Experiment ID** | `iteration-b-white-jotter-2026-10-25` |
| **Experiment Name** | Threat-modeller impact elicitation, iteration B |
| **Status** | Interim, trial in progress |
| **Started** | 2026-10-25T21:55:50Z |
| **Arms** | Arm A: 2026-10-24 batched white-jotter. Arm B: this run. |
| **Sample Size** | 1 trial, 3 modelled units, 26 stored threats, 53 linked specs |
| **Owner** | Operator |
| **Design Doc** | `docs/experiments/iteration-b-white-jotter-2026-10-25/PLAN.md` |
| **Trial Record** | `/opt/polymerhus-dev/eval/runs-iteration-b-20261025/white-jotter-1/` |

---

## Hypothesis Recap

**Original hypothesis:**

> The impact-first threat modeller produces a threat set that is more than 90% green, without collapsing the hunter's discrimination space.

**Success criteria:**

- Primary metric: more than 90% green threats over all stored threats.
- Secondary metrics: severe share, sharp-boundary share, class-binding rate, severe threats below the medium risk bucket, capped tokens per green threat.
- Guardrails: the 7M capped budget, `batched` sync, SkillEvolution off, no `auth_store view:full`, a terminal execution.

---

## Arm Definition

| Attribute | Arm A | Arm B |
|---|---|---|
| Branch / commit | 2026-10-24 arm A | `81522a71f3f5fbb0dcd9f9bb3c71d59a5e2b9002` |
| Target | white-jotter | white-jotter |
| Project | `0c8cb6e6-7e91-4a01-880e-408896c0ce4a` | `dda347be-abea-48e4-94e5-4a4039f41858` |
| Model | `opencode-go:deepseek-v4.1-flash` | `opencode-go:deepseek-v4.1-flash` |
| Thinking | `xhigh` | `xhigh` |
| Token budget | 7,000,000 capped | 7,000,000 capped |
| Risk threshold | 400 | 110 |
| Pipeline sync | `batched` | `batched` |
| SkillEvolution | on | off |
| Threat schema | schema 1 (`loops`) | schema 2 (`threats`) |
| Impact scoring | none | `VC`, `VI`, `VA` plus end impact |
| Trust axes | old | identity, spatial, temporal, controls semantics |
| Class guard | none | required suite class |

---

## Results

### Primary Metric: Green-threat share

| Arm | Green | Stored | Share | Denominator |
|---|---:|---:|---:|---|
| A (recomputed) | not reproducible as a green share | 111 | - | all stored threats |
| B | 10 | 26 | 38.5% | all stored threats, narrow high-yield set |
| B (broad set) | 15 | 26 | 57.7% | all stored threats, broad high-yield set |

**Observed difference:** not computable against the arm A green figure.

The ADR's arm A green figure is 45 of 113 (39.8%).
That is the same number as the arm A empty-and-suite-gap count, and the stored artifacts do not reproduce it.
The arm A class-binding rate is 68 of 111 (61.3%).

**Interpretation:**

The class guard works: 26 of 26 threats (100%) bind a suite class, against 61.3% in arm A.
The green gate does not work: 10 of 26 threats (38.5%) are green under the narrow set, or 15 of 26 (57.7%) under the broad set.
The impact elicitation shifted the class binding, not the class mass.

The dominant non-green parents are information-disclosure (6), rate-limit-bypass (2), defence-bypass (2), and proxy-techniques (1).

### Secondary Metrics

| Metric | Arm A | Arm B | Difference | Notes |
|---|---:|---:|---:|---|
| Severe share | 25/113 (22.1%) | 10/26 (38.5%) | +16.4 pp | impact weight at least 3 |
| Class-binding rate | 68/111 (61.3%) | 26/26 (100%) | +38.7 pp | non-empty suite class |
| Severe threats below medium risk bucket | 18 of 25 below `high` | 0 | improved | no severe threat below medium |
| Capped tokens per green threat | not comparable | 345,208 interim | - | 3,452,084 / 10 |
| Sharp-boundary share | 32/113 (28.3%) | not measured | - | the schema has no boundary-shape field |
| Risk total | 113 | 122 | +9 | the 110 threshold was crossed |

The severe share improved.
The severe threats are no longer demoted: every severe threat is at least medium.
The green share did not improve.

### Guardrail Metrics

| Guardrail | Threshold | Arm B | Status |
|---|---|---|---|
| Capped tokens | at most 7,000,000 | 3,452,084 interim | Pass so far |
| Pipeline sync | `batched` | `batched` | Pass |
| SkillEvolution | off | off | Pass |
| `auth_store view:full` | never called | pending the log audit | Pending |
| Execution terminal | complete or stopped at the cap | running | Pending |
| Assessment and diagnosis | terminal or escalated | not started | Pending |

### Narrowing Metrics

| Metric | Arm B | Notes |
|---|---:|---|
| Threats total | 26 | denominator |
| Broad (`bound_class_is_parent=true`) | 21 | 80.8% |
| Narrow (`false`) | 5 | 19.2% |
| Breadth unknown (`null`) | 0 | every class is in the suite |
| Linked specs | 53 | after dispatch-id normalisation |
| Substantial spec sets (at least 3) | 11 | 42.3% of threats |
| Well-formed spec sets | 1 | 3.8% of all threats, 9.1% of substantial |
| Substantial sets with overlapping axes | 10 of 11 | 90.9% |
| Broad without a well-formed set | 21 of 21 | every broad threat |
| Narrow without a well-formed set | 4 of 5 | the one well-formed set is narrow |

The one well-formed set is `session-management` threat-2 with four distinct axes.
Every broad threat produced a substantial but one-dimensional set.
The hunter varies technique, lifecycle event, artifact, signal channel, or principal consumer inside a single primary axis.
That is the narrowing risk the experiment was built to measure, and it is present.

### Token Tax

| Agent | Capped tokens | Share | Calls | Notes |
|---|---:|---:|---:|---|
| Pod runner | 1,360,814 | 39.4% | - | 41 pods, 21 terminal |
| Hunter | 967,315 | 28.0% | - | 53 linked specs |
| Threat modeller | 582,875 | 16.9% | - | 3 units, stopped at risk 122 |
| Mechanism typist | 322,896 | 9.4% | - | analysis |
| Triager | 79,570 | 2.3% | - | recon |
| Assigner | 49,080 | 1.4% | - | analysis |
| Pod triager | 48,045 | 1.4% | - | 3 verdicts |
| Job orchestrator | 41,489 | 1.2% | - | recon |
| **Total** | **3,452,084** | 100% | 1,115 | interim |

The pod runner is the largest consumer, as in arm A.
The hunter is second at 28.0%, against 17.9% in arm A.
The modeller is third at 16.9%, against 31.1% in arm A, because the risk threshold stopped it after three units.

---

## Segment Analysis

### By Unit

| Unit | Threats | Green | Severe | Risk | Substantial specs | Well-formed |
|---|---:|---:|---:|---:|---:|---:|
| `Service:sign-in` | 11 | 5 | 6 | 47 | 11 | 1 |
| `RESTApi:api` | 10 | 3 | 3 | 44 | 0 | 0 |
| `Service:library-catalog` | 5 | 2 | 1 | 31 | 0 | 0 |

`Service:sign-in` carries the only green depth and the only well-formed set.
`RESTApi:api` and `Service:library-catalog` have no specs yet; their hunter batches wait behind the first unit's pods.

### By Threat Class

| Parent class | Threats | Green | Severe | Notes |
|---|---:|---:|---:|---|
| information-disclosure | 6 | 0 | 1 | dominant non-green mass |
| session-management | 3 | 3 | 2 | the only well-formed set |
| broken-function-level-authorization | 3 | 3 | 1 | class-bound |
| rate-limit-bypass | 2 | 0 | 2 | one confirmed symptom |
| defence-bypass | 2 | 0 | 2 | one confirmed symptom |
| insecure-deserialization | 1 | 1 | 1 | - |
| crypto-weakness | 1 | 0 | 1 | - |
| csrf | 1 | 1 | 0 | - |
| weak-credential-discovery | 1 | 0 | 0 | - |
| header-injection | 1 | 0 | 1 | - |
| proxy-techniques | 1 | 0 | 0 | - |
| http-method-tampering | 1 | 0 | 0 | - |
| sql-injection | 1 | 1 | 1 | - |
| path-traversal-lfi-rfi | 1 | 1 | 0 | - |
| business-logic | 1 | 1 | 0 | - |

### By Phase

| Phase | Capped tokens | Share | Notes |
|---|---:|---:|---|
| Recon and analysis | 493,035 | 14.3% | recon complete, analysis complete |
| Hunting | 2,959,049 | 85.7% | modeller, hunter, pods |

### Segment Insights

The modeller spends most of its budget on the first unit.
The hunter spends its budget on one unit's deep spec set.
The pod phase spends the most and loses most of it to budget timeouts.

---

## Workflow and Contract Findings

- The class guard is effective: 26 of 26 threats bind a suite class.
- The hunter writes the dispatch id `<unit_name>__threat-<n>` into `provenance.threat_id`; the measurement link missed 44 specs until normalised.
- The measurement substrate now normalises the dispatch id in `eval/measure_utm.py`.
- The hunter produces deep spec sets, but 10 of 11 substantial sets share one primary axis.
- The batched 20-pod batch saturates the qemu target; 18 of 21 terminals are `budget-timeout`.
- The threat files carry the impact fields; the first print that looked for `VC/VI/VA` was a reading error, not missing data.

## Failure and Error Findings

- Three early trial attempts failed on the instance skills data-mount, not on branch code.
- The repair is configuration-only: a bind mount of the `ph-dd131acc_skills-procedures` volume and `--skills-root` pointing at the instance worktree.
- The pod budget timeouts are a harness loss, not a triager verdict. They are reported, not smoothed.

---

## Learnings

### What We Learned

- The impact model fixes the ranking: no severe threat sits below the medium bucket.
- The class guard fixes the class binding: every stored threat is huntable by a suite skill.
- Neither change shifts the class mass: 38.5% green narrow, 57.7% broad.
- The trust-boundary sharpening narrows the spec set: one well-formed set out of eleven substantial sets.
- The deepest confirmed findings are on non-green classes: rate-limit-bypass and defence-bypass-parser-confusion.
- One green class confirmed: session-management.

### What Surprised Us

- The hunter produced 53 linked specs for 11 threats in one unit, more than arm A's whole run.
- The only well-formed set is on a narrow class, not a broad one.
- The 20-pod batch timed out 18 of 21 pods on the qemu target.

### What Remains Unknown

- The official ground-truth verdicts for the three confirmed symptoms.
- The second and third units' hunter and pod behaviour; their batches have not run.
- Whether a target-aware pod concurrency would recover the 18 timeouts.
- Whether the green set should include the classes that produced confirmed findings.

---

## Recommendation

**Decision:** Iterate.

The class-binding and ranking goals are met.
The green gate and the narrowing goal are not met.
The next arm should:

- redefine or ratify the high-yield class set before the run;
- make the hunter choose distinct primary axes, not variants inside one axis;
- cap pod concurrency per target, or raise the per-pod budget for a slow qemu target;
- record the boundary-shape field that the sharp-boundary metric needs;
- normalise the spec provenance threat id at the writer, not only in the measurement.

## Next Steps

- Finish the trial and run the post-execution assessment and diagnosis.
- Run `eval/measure_utm.py` on the final trial record.
- Update this document with the final token, pod, and verdict numbers.
- Open the follow-up tickets for the axis discrimination, the pod concurrency, and the provenance normalisation.

---

## Evidence Appendix

- Trial record: `/opt/polymerhus-dev/eval/runs-iteration-b-20261025/white-jotter-1/`
- Project data: `/opt/polymerhus-dev/eval/instances/data/eval-server-1/dda347be-abea-48e4-94e5-4a4039f41858/`
- Threat files: `<project>/hunting/threat_modeller/{produced,consumed}/<unit>/threat-*.yaml`
- Hunter specs: `<project>/hunting/hunter/test-specs/**/*.yaml`
- Pod exports: `<project>/hunting/test-executor-pod/<dispatch>/<run_id>.yaml`
- Monitor log: `/opt/polymerhus-dev/eval/runs-iteration-b-20261025/monitor.jsonl`
- Trial log: `/opt/polymerhus-dev/eval/runs-iteration-b-20261025/trial.log`
- Arm A baseline: `docs/experiments/iteration-b-white-jotter-2026-10-25/ARM-A-BASELINE.md`

## Measurement Discipline Checklist

- [x] The primary metric has its numerator, denominator, and arm values.
- [x] The secondary and guardrail metrics are reported, including the ones that did not move.
- [x] The narrowing metrics are reported with the same denominator as the primary metric.
- [x] The token tax is split by agent and by phase.
- [x] The segment analysis checks for composition effects.
- [x] The single-trial limitation is stated honestly.
- [x] Every claim cites an artifact path or a metric row.
- [x] The recommendation is clear and actionable.
- [x] Negative or inconclusive results are reported, never smoothed.
