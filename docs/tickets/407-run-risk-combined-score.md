# 407 - Move the run risk accumulator to the combined score

**What to build:** Move the run risk accumulator, the model sum, the weight table, the resume recompute, and the run-record fields to the combined loop risk. Keep the likelihood breakdown for compatibility and add the impact breakdown and the risk breakdown.

**Blocked by:** 406

**Status:** ready-for-agent

**Seams:** attack/hunting/run_lifecycle.py, attack/hunting/runtime.py

## Context

The threshold is provisional at 360 and the A/B sets it per arm. The run record stores the likelihood weights, the impact weights, the risk total, the impact breakdown, the risk breakdown, and the per-unit sums. The resume recomputes the total from the model sums and the completed models, so a crash cannot leave a stale total.

## Acceptance criteria

- [ ] The model sum is the sum of the loop risks.
- [ ] The accumulator total, breakdown, and per-unit entries use the combined score.
- [ ] The run record carries both weight tables and both breakdowns.
- [ ] The resume recomputes the combined total from the models.
- [ ] The inclusive threshold comparison is preserved.
- [ ] A model without impact contributes zero.
- [ ] The crossing and blocked unit semantics are unchanged.

## Verification

- Run the run-lifecycle tests.
- Run the resume tests.
