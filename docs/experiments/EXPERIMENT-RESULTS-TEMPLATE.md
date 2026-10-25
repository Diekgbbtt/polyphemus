---
artifact: experiment-results
version: "1.0"
created: YYYY-MM-DD
status: draft
---

# Experiment Results: [Experiment Name]

## Summary

| Attribute | Value |
|---|---|
| **Experiment ID** | [ID] |
| **Experiment Name** | [Name] |
| **Status** | Completed / Ended Early / Inconclusive |
| **Duration** | [Start] to [End] |
| **Arms** | [A] / [B] |
| **Sample Size** | [Trials, targets, stored threats] |
| **Owner** | [Name] |
| **Design Doc** | [Link to the plan] |
| **Trial Record** | [Link to `trial.yaml`] |

---

## Hypothesis Recap

**Original hypothesis:**

> We believed that [change] would [expected outcome] because [rationale].

**Success criteria:**

- Primary metric: [metric] reaches [threshold].
- Secondary metrics: [list].
- Guardrails: [list].

---

## Arm Definition

| Attribute | Arm A | Arm B |
|---|---|---|
| Branch / commit | [SHA] | [SHA] |
| Target | [target] | [target] |
| Project | [project id] | [project id] |
| Model | [model] | [model] |
| Thinking | [level] | [level] |
| Token budget | [n] | [n] |
| Risk threshold | [n] | [n] |
| Pipeline sync | [mode] | [mode] |
| SkillEvolution | [on/off] | [on/off] |
| Other changes | [list] | [list] |

---

## Results

### Primary Metric: Green-threat share

| Arm | Green | Stored | Share | Denominator |
|---|---:|---:|---:|---|
| A | [n] | [n] | [%] | all stored threats |
| B | [n] | [n] | [%] | all stored threats |

**Observed difference:** [+/- percentage points].

**Interpretation:** [Plain-language explanation].
With one trial per arm, report the counts and the descriptive difference.
Do not report a p-value or a confidence interval as if the sample supported it.

### Secondary Metrics

| Metric | Arm A | Arm B | Difference | Notes |
|---|---:|---:|---:|---|
| Severe share | [%] | [%] | [pp] | [definition] |
| Sharp-boundary share | [%] | [%] | [pp] | [definition] |
| Class-binding rate | [%] | [%] | [pp] | [definition] |
| Severe threats below medium bucket | [n] | [n] | [n] | [definition] |
| Capped tokens per green threat | [n] | [n] | [n] | [definition] |
| Modeller share of capped budget | [%] | [%] | [pp] | [definition] |

### Guardrail Metrics

| Guardrail | Threshold | Arm B | Status |
|---|---|---|---|
| Capped tokens | at most 7,000,000 | [n] | Pass / Fail |
| Pipeline sync | `batched` | [mode] | Pass / Fail |
| SkillEvolution | off | [state] | Pass / Fail |
| `auth_store view:full` | never called | [n] | Pass / Fail |
| Execution terminal | complete or stopped at the cap | [terminal] | Pass / Fail |
| Assessment and diagnosis | terminal or escalated | [state] | Pass / Fail |

### Narrowing Metrics

| Metric | Arm A | Arm B | Notes |
|---|---:|---:|---|
| Threats total | [n] | [n] | [denominator] |
| Broad (`bound_class_is_parent=true`) | [n] | [n] | [share] |
| Narrow (`false`) | [n] | [n] | [share] |
| Breadth unknown (`null`) | [n] | [n] | [share] |
| Substantial spec sets (at least 3) | [n] | [n] | [share] |
| Well-formed spec sets | [n] | [n] | [share] |
| Narrow without well-formed | [n] | [n] | [bias signal] |
| Broad without well-formed | [n] | [n] | [bias signal] |

### Token Tax

| Agent | Capped tokens | Share | Calls | Notes |
|---|---:|---:|---:|---|
| Threat modeller | [n] | [%] | [n] | [notes] |
| Hunter | [n] | [%] | [n] | [notes] |
| Pod runner | [n] | [%] | [n] | [notes] |
| Pod triager | [n] | [%] | [n] | [notes] |
| Analysis | [n] | [%] | [n] | [notes] |
| Recon | [n] | [%] | [n] | [notes] |
| **Total** | [n] | 100% | [n] | [notes] |

---

## Segment Analysis

### By Unit

| Unit | Threats | Green | Severe | Broad | Well-formed | Notes |
|---|---:|---:|---:|---:|---:|---|
| [unit] | [n] | [n] | [n] | [n] | [n] | [notes] |

### By Threat Class

| Class | Threats | Green | Severe | Broad | Well-formed | Notes |
|---|---:|---:|---:|---:|---:|---|
| [class] | [n] | [n] | [n] | [n] | [n] | [notes] |

### By Phase

| Phase | Capped tokens | Share | Duration | Notes |
|---|---:|---:|---:|---|
| Recon | [n] | [%] | [time] | [notes] |
| Analysis | [n] | [%] | [time] | [notes] |
| Hunting | [n] | [%] | [time] | [notes] |

### Segment Insights

[Where did the arm work better or worse, and why.]

---

## Workflow and Contract Findings

- [Finding with evidence.]
- [Finding with evidence.]

## Failure and Error Findings

- [Failure or error, its terminal state, and the evidence path.]
- [Any escalation and its named failure.]

---

## Learnings

### What We Learned

- [Learning.]

### What Surprised Us

- [Surprise.]

### What Remains Unknown

- [Unknown and the experiment that would resolve it.]

---

## Recommendation

**Decision:** Ship / Iterate / Kill.

[Evidence-led justification, including the trade-offs.]

## Next Steps

- [Next step, owner, and trigger.]

---

## Evidence Appendix

- Trial record: [path]
- `metrics.yaml`: [path]
- Measurement report: [path]
- `verdicts.yaml`: [path]
- `diagnoses.yaml`: [path]
- Threat files: [path]
- Specs: [path]
- Pod exports: [path]
- Langfuse trace: [id]
- Commands: [exact commands]

## Measurement Discipline Checklist

- [ ] The primary metric has its numerator, denominator, and arm values.
- [ ] The secondary and guardrail metrics are reported, including the ones that did not move.
- [ ] The narrowing metrics are reported with the same denominator as the primary metric.
- [ ] The token tax is split by agent and by phase.
- [ ] The segment analysis checks for composition effects.
- [ ] The single-trial limitation is stated honestly.
- [ ] Every claim cites an artifact path or a metric row.
- [ ] The recommendation is clear and actionable.
- [ ] Negative or inconclusive results are reported, never smoothed.
