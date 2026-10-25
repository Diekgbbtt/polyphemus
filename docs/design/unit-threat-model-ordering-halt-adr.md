# ADR: the intake order couples to the progressive halt

## Amendment 2026-10-25: impact-first elicitation

The threat-model impact-elicitation workstream supersedes the likelihood-only risk score and the failure-mode artifact in this document.
The decisions are in `docs/design/threat-model-impact-elicitation-adr.md`; the component map is `docs/design/threat-model-impact-elicitation-impact-map.md`.
Where this document and the amendment disagree, the amendment wins.

- A threat carries `VC`, `VI`, and `VA` plus a literal end impact. The store computes `impact = 1 - (1-VC)(1-VI)(1-VA)`, the ordinal weight, and `threat risk = likelihood_weight * impact_weight`.
- The ranking and the dispatch buckets use the combined risk. The run record carries `impact_weights` and `impact_breakdown`.
- The `failure_modes` artifact, `Threat.failure_mode_refs`, and the pod `failure-mode` variant basis are removed. The modeller no longer judges technical feasibility; the hunter and the pod own the effective attempt.
- The trust procedure uses the four axes `identity`, `spatial`, `temporal`, and `controls_semantics`.
- The well-formedness phase runs between `VULNERABILITIES_WRITTEN` and `COMPLETED`. Its exit is one `wellformedness` note plus the `COMPLETED` write; a lower-gate write is the re-entry signal.
- Every vulnerability binds a suite class parent or leaf. Technique families are not classes. `suite_gap` is removed. Class findings are non-blocking.


## Status

Accepted (design phase, 2026-10-18).
Bound to the unit threat model grilling (`docs/design/unit-threat-model-workbench.md`, R1-4, R2-5, Q16, Q20, Q60(a)).
Nothing here is built yet.

## Context

- Intake orders the L1 units by live-edge count, both directions, with retired edges excluded; ties break by aggregated endpoint count and then unit id (R1-4).
  The order is recorded in the run.
- The run accumulates a symbolic risk score over the completed threats and checks the running sum against a threshold (`>=`) at each model completion (Q16, R2-5).
  When the threshold is reached, the crossing unit is fully modelled and dispatched; only the next unit is never modelled: this is the progressive halt.
- The run's DISPATCH may interleave with modelling: the surfer dispatches each admitted unit's threats while later units are still modelled (R2-6, R5-1).
  Since the pipeline-sync decision (2026-10-22, ADR `hunting-pipeline-sync-adr.md`) that interleave is the `parallel` sync mode only; the default `batched` (and `serial`) models the whole risk budget before any downstream dispatch.
- The coupling of the halt set to the intake order is unaffected: the interleave makes the halt set a function of the intake order.
  Which units are ever modelled depends on how far the run gets, and the run stops on the score that the ordered units yield.

## Decision

1. The coupling is accepted and documented here; it is not designed away.
   The intake order is simultaneously the research-yield order and the halt order.
2. The sort key stays the sort key.
   The halt never re-sorts or re-ranks the intake.
3. The halt is evaluated at model completion, on the symbolic run-level accumulator, with a `>=` threshold comparison.
   The crossing unit is fully modelled and dispatched before the halt; the next unit is not modelled; the blocked unit is recorded in the run.
4. The intake order, the crossing unit, and the blocked unit are recorded in the run record.
   They carry the halt's audit trail.
5. A resumed run re-enters at the recorded order position with the persisted accumulator state.

## Rationale

- A decoupled halt would need an order-independent halt set.
  The score accumulates from completed models, so any halt is a function of which units completed, and therefore of the order.
  A decoupled design would either halt on a pre-computed estimate (contradicting the per-threat scoring decision) or ignore the budget (contradicting the risk budget).
- The intake order is the only research-yield proxy available before any unit is modelled.
  Using it for both intake and halt keeps one ordering concept instead of two competing ones.
- The rejected alternatives are explicit: halting by a fixed unit count discards the score, and halting on an upfront score estimate cannot exist because the score is only known after modelling.

## Consequences

- The halt set is a function of the order by construction.
  Run records must carry the order and the crossing and blocked units, or the halt cannot be audited.
- The threshold and the per-level weights can be calibrated by replaying recorded runs in intake order (workbench R3-2).
- Cheap or expensive early units change how many units the run reaches.
  The design accepts this as a property of a progressive budget.

## References

- `docs/design/unit-threat-model-workbench.md` (R1-4, R2-5/Q16, R2-6, R5-1, R3-2).
- `docs/design/unit-threat-model-workflow.md` (section 1 and the run lifecycle).
