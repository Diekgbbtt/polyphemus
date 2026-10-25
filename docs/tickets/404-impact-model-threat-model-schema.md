# 404 - Add the impact model to the threat-model schema

**What to build:** Add the impact model to the threat-model schema: the three CVSS 4.0-like metrics VC, VI, VA with N/L/M/H values, the end-impact statement, and the ordinal impact weight. Add the pure impact computation, the metric weights, the loop risk, the combined risk profile, and the risk-first loop ranking.

**Blocked by:** 402

**Status:** done

**Seams:** attack/hunting/threat_model.py

## Context

The formula is impact = 1 - (1 - VC)(1 - VI)(1 - VA), with N = 0.00, L = 0.22, M = 0.35, H = 0.56. The ordinal weight is 0 at zero, 1 at (0, 0.25], 2 at (0.25, 0.50], 3 at (0.50, 0.75], 4 above 0.75. The loop risk is likelihood_weight * impact_weight. The ranking is risk descending, then impact descending, then likelihood descending, then write order. The store computes the profile; the modeller never authors it. Old models without an impact default to impact none and risk zero.

## Acceptance criteria

- [x] The impact record carries VC, VI, VA, the end-impact statement, the impact sub-score, and the ordinal weight.
- [x] The metric weights are single-sourced and the table test covers every value.
- [x] The ordinal thresholds are tested at the boundaries.
- [x] compute_risk_profile sums the loop risk and carries the impact breakdown beside the likelihood breakdown.
- [x] normalise_loops ranks by risk, then impact, then likelihood, then write order.
- [x] The loop ids remain loop-1..n in the ranked order.
- [x] A loop with impact zero contributes zero risk.
- [x] Old models without impact parse and contribute zero risk.
- [x] The functions are pure and the tests do not mock the formula.

## Verification

- Run the threat-model unit tests.
- Run the store tests that read the profile.
