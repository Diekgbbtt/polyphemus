# ADR: the intake order couples to the progressive halt

## Status

Accepted (design phase, 2026-10-18).
Bound to the unit threat model grilling (`docs/design/unit-threat-model-workbench.md`, R1-4, R2-5, Q16, Q20, Q60(a)).
Nothing here is built yet.

## Context

- Intake orders the L1 units by live-edge count, both directions, with retired edges excluded; ties break by aggregated endpoint count and then unit id (R1-4).
  The order is recorded in the run.
- The run accumulates a symbolic risk score over the completed loops and checks the running sum against a threshold (`>=`) at each model completion (Q16, R2-5).
  When the threshold is reached, the crossing unit is fully modelled and dispatched; only the next unit is never modelled: this is the progressive halt.
- The run interleaves modelling and dispatch: the surfer dispatches each admitted unit's loops while later units are still modelled (R2-6, R5-1).
- The interleave makes the halt set a function of the intake order.
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
  A decoupled design would either halt on a pre-computed estimate (contradicting the per-loop scoring decision) or ignore the budget (contradicting the risk budget).
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
