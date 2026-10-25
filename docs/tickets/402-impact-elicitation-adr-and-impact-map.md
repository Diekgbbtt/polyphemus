# 402 - Record the impact-elicitation ADR and the impact map

**What to build:** Record the decisions that this workstream implements: the impact metrics VC/VI/VA, the formula and ordinal weights, the combined loop risk, the ranking and dispatch buckets, the provisional threshold, the four trust axes, the well-formedness pseudo-phase, the failure-mode removal, the class-binding guard, and the green-loop gate. Record the impact map that lists every dependent component and the convergence order.

**Blocked by:** None - can start immediately

**Status:** ready-for-agent

**Seams:** docs/design, docs/experiments/modeller-impact-quality

## Context

The impact map is already written at docs/design/threat-model-impact-elicitation-impact-map.md. The ADR must record the failure-mode no-drop evidence from the baseline: 113 failure modes, 113 vulnerabilities, 0 drops, 78 feasible, 33 conditionally feasible, 2 infeasible. The rationale is that the modeller's feasibility check did not discriminate, and the hunter and the pod own technical feasibility and effective attempt. The ADR must also record the CVSS 4.0-like impact choice, the rate of the green-loop gate, and the decision to keep low-yield loops stored but scored low or zero.

## Acceptance criteria

- [ ] The ADR exists in the docs bank and records every decision in the plan.
- [ ] The ADR records the failure-mode no-drop evidence and the reason for the removal.
- [ ] The ADR records the impact formula, the metric weights, the ordinal thresholds, the loop risk, the ranking, the dispatch buckets, and the threshold.
- [ ] The ADR records the four trust axes and the well-formedness pseudo-phase.
- [ ] The ADR records the class-binding guard and the green-loop gate.
- [ ] The impact map lists every dependent component and the convergence order.
- [ ] The decisions match docs/experiments/modeller-impact-quality/PLAN.md.

## Verification

- Read the ADR and the impact map against the plan.
- Confirm no unresolved alternative is left implicit.
