# ADR: the triage lifecycle v2 ownership model and the monotonic verdict

**Status:** ratified and implemented (branch `fix/pod-triager-cache-prefix`).
**Date:** 2026-11-14.
**Authority:** the operator's 2026-11-14 ratification; the measured trial
`siyucms-web-20261112T074242-38e49ca5` (25.56% provider cache hit ratio,
47 triage decisions, 82 stage entries, 42 warm stage switches).
**Design:** `docs/design/pod-triager-lifecycle-v2.md`; **spec:** the pod spec
8.11 rewrite.

## Decision

The old `clean` word carried three concepts. They are split into three owners,
and the pod's verdicts gain a structural monotonicity guarantee.

| Concern | Owner | Carrier |
|---|---|---|
| Observation integrity (`clean`) | Triager | `submit_assessment.clean`, carried into the terminal |
| Evidence sufficiency | Triager | The action: a variant, or a terminal reason |
| Domain verdict (`verdict`, `terminal_reason`) | Triager | `submit_decision` |
| Infrastructure terminal | Harness | `PodTerminal.infrastructure` |
| Durable finality | Finalizer | First non-empty domain verdict wins |

## Why

- The triager reads the raw observations anyway; a harness grep over the trail
  (`_clean_from_trail`) checked only `returncode` and ignored `stderr` and the
  structured `success: false` (FF-06). The judgement of observation integrity
  belongs to the reader of the raw fields.
- Sufficiency already has a vocabulary: `space-exhausted` versus
  `no-symptom-evidence`. A field would have been a second encoding of the same
  answer.
- The last-lap verdict selection buried an earlier confirmed negative under a
  later session expiry (FF-07). Only a structural rule fixes it.

## The monotonicity ladder (enforced in `finalize_pod`, the ONE writer)

1. A latched DOMAIN verdict is final: no later write replaces it, whatever
   `replace_existing` says.
2. A DOMAIN verdict may replace a latched HARNESS terminal; the superseded
   control-plane end reason survives additively as
   `evidence.control_plane_end_reason`.
3. A HARNESS terminal replaces another HARNESS terminal only through the
   existing `replace_existing` policy.
4. An unlatched export (no verdict, an empty verdict, or no terminal reason)
   never latches: the next write fills it, even from the backstop.

The graph's `_export` reads the durable envelope's verdict and reason back, so
the in-memory result and the durable record can never disagree.

## The control plane keeps the runner end reason

The harness owns the runner end reason whenever it kills the runner (a node
timeout, a tool timeout, the budget cap). A kill is not a reason to skip
triage: the triager still evaluates the most recent runner loop execution and
reports the attempted kill chain, with `variant_allowed=false` (a variant
cannot run on a dead control plane). A no-evaluation triage outcome (the
fail-open degrade or the step-budget exhaustion) is marked `degraded` and a
kill then keeps the harness terminal standing - the pod did not evaluate, so
the control-plane fact is the honest export.

## The `space-exhausted` coherence rule

A `space-exhausted` terminal over `clean=false` must not emerge at all, so the
`submit_decision` gate refuses it and names the canonical corrections: a
partial-coverage assessment plus a variant that covers the unobserved
execution modes, or `no-symptom-evidence`. The #304 degraded-KB guard keeps
its terminal-reason downgrade and no longer forces `clean=false`: degraded KB
is a sufficiency condition, not an integrity condition.

## Consequences

- `TriageDecision.clean`, `_clean_from_trail`, and the #304 clean forcing are
  removed.
- A same-run re-dispatch rewrites a harness export, never a latched domain
  verdict (a stricter contract than the pre-v2 `replace_existing` behavior).
- The export gains one optional additive field,
  `evidence.control_plane_end_reason`; the parent's derivation is untouched.
- The eval harness reads three additive ledger counters
  (`first_calls`, `first_cached`, `first_uncached`) and prints the marginal
  cache-hit KPI.
