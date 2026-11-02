---
artifact: experiment-results
version: "1.0"
created: 2026-10-26
status: complete
---

# Experiment Results: Iteration B white-jotter impact elicitation

## Summary

| Attribute | Value |
|---|---|
| **Experiment ID** | `iteration-b-white-jotter-2026-10-25` |
| **Experiment Name** | Threat-modeller impact elicitation, iteration B |
| **Status** | Complete, negative on the green gate |
| **Window** | 2026-10-25T21:51:53Z to 2026-10-26T03:11:21Z |
| **Arms** | Arm A: 2026-10-24 batched white-jotter. Arm B: this run. |
| **Sample Size** | 1 trial, 3 modelled units of 27, 26 stored threats, 104 specs |
| **Owner** | Operator |
| **Design Doc** | `docs/experiments/iteration-b-white-jotter-2026-10-25/PLAN.md` |
| **Measurement** | `artifacts/measurements.md`, `artifacts/measurements.yaml` |
| **Trial Record** | `artifacts/trial.yaml` |

**Headline:** the class guard and the impact ranking improved; the green gate, the discrimination space, and the discovery outcome did not.

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

The gate is not met.
The ADR's arm A figure of 45 of 113 (39.8%) is the same number as the arm A empty-and-suite-gap count; the stored artifacts do not reproduce it.
The arm A class-binding rate is 68 of 111 (61.3%).

**Interpretation:**

The class guard works: 26 of 26 threats (100%) bind a suite class, against 61.3% in arm A.
The impact elicitation shifted the class binding, not the class mass.
The dominant non-green parents are information-disclosure (6), rate-limit-bypass (2), defence-bypass (2), and proxy-techniques (1).

### Official Discovery Result

The official record is 0 identified, 1 partial, and 6 missed.
The identification rate is 0.0; the partial-or-identified rate is 0.1429.

The partial is `white-jotter-001` at confidence 0.45.
It is not a ground-truth-scoped discovery: the rate-limit pod's control probes authenticated `admin/123`, but the pod's confirmed class was rate-limit-bypass and its spec never tested credential acceptance.

The seven diagnoses fall into three clusters:

- the progressive risk halt (003, 004, 007) never modelled the unit;
- the batched risk-descending queue plus the token budget (005, 006) modelled the loop but never hunted it;
- modeller fault binding (001, 002) bound the wrong fault or closed the path-spelling family too early.

The full record is in `artifacts/verdicts.yaml` and `artifacts/diagnoses.yaml`.

### Secondary Metrics

| Metric | Arm A | Arm B | Difference | Notes |
|---|---:|---:|---:|---|
| Severe share | 25/113 (22.1%) | 10/26 (38.5%) | +16.4 pp | impact weight at least 3 |
| Class-binding rate | 68/111 (61.3%) | 26/26 (100%) | +38.7 pp | non-empty suite class |
| Severe threats below medium risk bucket | 18 of 25 below `high` | 0 | improved | no severe threat below medium |
| Capped tokens per green threat | not comparable | 701,745 | - | 7,017,453 / 10 |
| Capped tokens per ground-truth vulnerability | - | 1,002,493 | - | 7,017,453 / 7 |
| Sharp-boundary share | 32/113 (28.3%) | not measured | - | the schema has no boundary-shape field |
| Risk total | 113 | 122 | +9 | the 110 threshold was crossed |

### Guardrail Metrics

| Guardrail | Threshold | Arm B | Status |
|---|---|---|---|
| Capped tokens | at most 7,000,000 | 7,017,453 | Fail by 17,453 (0.25%) |
| Pipeline sync | `batched` | `batched` | Pass |
| SkillEvolution | off | off | Pass |
| `auth_store view:full` | never called | not audited | Open |
| Execution terminal | complete or stopped at the cap | `failed` (stop POST timeout) | Fail |
| Assessment and diagnosis | terminal or escalated | complete | Pass |

The app's hunting run finished `stopped` at 03:11:21 after crossing the budget.
The trial's stop confirmation POST timed out, so the trial record says `failed` and records no overshoot.
The token spend is 7,017,453, not the 7,000,000 cap.

### Narrowing Metrics

| Metric | Arm B | Notes |
|---|---:|---|
| Threats total | 26 | denominator |
| Broad (`bound_class_is_parent=true`) | 21 | 80.8% |
| Narrow (`false`) | 5 | 19.2% |
| Breadth unknown (`null`) | 0 | every class is in the suite |
| Linked specs | 104 | after dispatch-id normalisation |
| Substantial spec sets (at least 3) | 21 | 80.8% of threats |
| Well-formed spec sets | 1 | 3.8% of threats, 4.8% of substantial |
| Substantial sets with overlapping axes | 20 of 21 | 95.2% |
| Broad without a well-formed set | 21 of 21 | every broad threat |
| Narrow without a well-formed set | 4 of 5 | the one well-formed set is narrow |

The one well-formed set is `Service:sign-in__threat-2` (`session-management`) with four distinct axes.
Every broad threat produced a substantial but one-dimensional set.
The hunter varies technique, lifecycle event, artifact, signal channel, or principal consumer inside a single primary axis.

The first unit carries 53 specs and 11 substantial sets.
The second unit carries 51 specs and 10 substantial sets, none well-formed.
The third unit carries 5 threats and 0 specs; the batched queue never reached it.

The narrowing table is recomputed from the stored artifacts with the dispatch-id normalisation added in `3f8ac5cd`.
The measurement subagent's deterministic narrowing undercounted the linked specs for the same reason.

### Token Tax

| Agent | Capped tokens | Share | Calls | Notes |
|---|---:|---:|---:|---|
| Pod runner | 3,475,010 | 49.5% | 1,604 | 86 pods, 66 exports, 4 successes |
| Hunter | 2,177,105 | 31.0% | 648 | 104 specs |
| Threat modeller | 582,875 | 8.3% | 94 | 3 of 27 units |
| Mechanism typist | 322,896 | 4.6% | 45 | analysis |
| Pod triager | 289,428 | 4.1% | 31 | 4 successes |
| Triager | 79,570 | 1.1% | 9 | recon |
| Assigner | 49,080 | 0.7% | 9 | analysis |
| Job orchestrator | 41,489 | 0.6% | 19 | recon |
| **Total** | **7,017,453** | 100% | 2,459 | 0.25% over the cap |

Hunting agents take 6,524,418 capped tokens (93.0%).
The analysis-side agents take 451,546 (6.4%).
The job orchestrator takes 41,489 (0.6%).
Capped tokens are 7.25% of the 96.8M total; cached input is 94.6% of context.
Reasoning is 54.6% of generated output.
The live usage endpoint reads 7,022,363 capped and 2,460 calls, a 4,910-token drift after the terminal snapshot.

---

## Segment Analysis

### By Unit

| Unit | Threats | Green | Severe | Risk | Specs | Substantial | Well-formed |
|---|---:|---:|---:|---:|---:|---:|---:|
| `Service:sign-in` | 11 | 5 | 6 | 47 | 53 | 11 | 1 |
| `RESTApi:api` | 10 | 3 | 3 | 44 | 51 | 10 | 0 |
| `Service:library-catalog` | 5 | 2 | 1 | 31 | 0 | 0 | 0 |

`Service:sign-in` carries the only green depth and the only well-formed set.
`RESTApi:api` produced specs but no well-formed set.
`Service:library-catalog` produced the best SQL-injection loop and was never dispatched; 93% of the budget went to the two earlier units.

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
| sql-injection | 1 | 1 | 1 | the best loop, never hunted |
| path-traversal-lfi-rfi | 1 | 1 | 0 | the traversal loop, never hunted |
| business-logic | 1 | 1 | 0 | - |

### By Phase

| Phase | Capped tokens | Share | Outcome |
|---|---:|---:|---|
| Recon and analysis | 493,035 | 7.0% | recon complete, analysis drained |
| Hunting | 6,524,418 | 93.0% | modeller, hunter, pods |
| Trial total | 7,017,453 | 100% | stop confirmation failed |

### Segment Insights

The cost is concentrated in the first two units.
The third unit, which contains the best SQL-injection loop, was starved by the risk-descending batch and the 7M cap.
The pod runner is 49.5% of the total, but 58 of 66 exports are watchdog envelopes.

---

## Workflow and Contract Findings

- The modeller modelled 3 of 27 intake units; the 110 risk threshold halted coverage before the ground-truth units 003, 004, and 007.
- The batched queue drained the two highest-risk units first and never dispatched `Service:library-catalog`.
- 58 of 66 PodExports are degraded `budget-timeout` envelopes written by the 2700 s watchdog; they carry zero raw observations.
- 20 of 86 pod directories have no export at all.
- 12 of 104 ratified specs lack `verification_symptoms`, `assumptions`, and `skill_concretised_procedure`.
- The hunter writes the dispatch id into `provenance.threat_id`; the measurement link is normalised in `eval/measure_utm.py`.
- The deterministic measurement has three recorded defects: the `loop-*.yaml` glob, the `provenance.skill_procedure` path, and keyword-inflated `spec_candidate`/`confirmed_non_gt`.
- No skill-usage lesson shard exists under the project's `lessons/` directory, which is consistent with the SkillEvolution switch being off.
- The trial-to-run identity chain breaks on the failure path: `trial.yaml` has `hunting.run_id: null` although run `12d15890` produced the artifacts.

## Failure and Error Findings

- The budget-stop POST timed out after the run had stopped; the trial terminal is `failed` and `spend_overshoot` is null although the spend is 7,017,453.
- 58 watchdog envelopes and 20 missing exports are the largest discovery-quality failures.
- The 12 contract-broken specs were ratified and dispatched.
- The default administrator pair `admin/123` was authenticated repeatedly as bootstrap material and never reported as a finding.
- The wildcard BFLA pod reached `/api/;/admin/content/books` with HTTP 200 and a 41-byte code-400 envelope, then moved to `/actuator`; its export was lost to the watchdog.
- The three early trial attempts failed on the instance skills data-mount, not on branch code; the repair is recorded in `RUN-STATE.md`.

---

## Learnings

### What We Learned

- Coverage, not class knowledge, is the binding constraint on this target.
- A sharp loop is not enough if the queue cannot reach it.
- The impact model fixes the ranking: no severe threat sits below the medium bucket.
- The class guard fixes the class binding: every stored threat is huntable by a suite skill.
- Neither change shifts the class mass: 38.5% green narrow, 57.7% broad.
- The trust-boundary sharpening narrows the spec set: 1 well-formed set out of 21 substantial sets.

### What Surprised Us

- The pipeline spent 7,017,453 capped tokens to identify zero of seven ground-truth vulnerabilities.
- The deepest confirmed findings are on non-green classes: rate-limit-bypass, defence-bypass-parser-confusion, and session fixation on a green class.
- The only well-formed set is on a narrow class, not a broad one.
- The pod runner is 49.5% of the total, but most of that spend ends in watchdog envelopes.

### What Remains Unknown

- Whether a per-unit budget reservation would have admitted `Service:library-catalog` and the SQL-injection loop.
- Whether the 58 watchdog exports are an intended degraded contract or a schema regression.
- Whether the 12 contract-broken specs are a regression from `81522a71` or a pre-existing hunter defect.
- Whether the green set should include the classes that produced confirmed findings.
- Which SHA is authoritative for the aggregate: the plan says `5df29930`, the trial stamps `81522a71`.

---

## Recommendation

**Decision:** Iterate.

The class-binding and ranking goals are met.
The green gate, the discrimination space, and the discovery outcome are not.

The next arm should:

- ratify the high-yield class set before the run and report it beside the class-binding rate;
- add a per-unit budget reservation or a coverage floor, and dispatch the crossing unit;
- enforce distinct primary discrimination axes, not variants inside one axis;
- fix the pod lifecycle: preserve the pod's own terminal on watchdog expiry and emit an export for every pod;
- enforce the hunter's reduced-D4 contract at ratification;
- retry the budget-stop POST on transport timeout and record the stop as `stopped` with the overshoot;
- write the store-owned threat id, not the dispatch id, into `provenance.threat_id`;
- fix the three deterministic-measurement defects.

## Next Steps

- Ticket 422 is closed with this result.
- The follow-up tickets 424 to 430 carry the next work items.
- The branch is pushed at `1b92468c`; the trial ran at `81522a71`.
- Nothing is merged into `dev`.

---

## Evidence Appendix

- Official record: `artifacts/verdicts.yaml`, `artifacts/diagnoses.yaml`.
- Deterministic base: `artifacts/metrics.yaml`.
- Trial record: `artifacts/trial.yaml`.
- Measurement: `artifacts/measurements.md`, `artifacts/measurements.yaml`.
- Arm A baseline: `ARM-A-BASELINE.md`.
- Run state and configuration repair: `RUN-STATE.md`.
- Plan and arm definition: `PLAN.md`.
- Remote project data: `dda347be-abea-48e4-94e5-4a4039f41858/hunting/`.
- Remote trial log: `/opt/polymerhus-dev/eval/runs-iteration-b-20261025/trial.log`.
- Remote post-run log: `/opt/polymerhus-dev/eval/runs-iteration-b-20261025/post.log`.
- Monitor log: `/opt/polymerhus-dev/eval/runs-iteration-b-20261025/monitor.jsonl`.
- Private corpus: `/root/utm-groundtruth/white-jotter/white-jotter-00{1..7}/`.
- Official ground truth: `/root/WebExploitBench/white-jotter/`.

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
