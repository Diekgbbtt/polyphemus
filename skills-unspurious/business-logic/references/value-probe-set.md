# Value Probe Set

A value probe is only a finding when an independent recomputation disagrees with what the transition committed.
This reference holds the probe set, the oracle rule, the selector discipline, and the failure-mode index behind the class's value-domain step.
It serves the input-surface step of the `business-logic` parent and the submission step of `value-domain-manipulation`.
The set completes when every value input of every constrained transition carries a probe beside the independently recomputed expectation.

## The Probe Set

One probe per attempt, so the delta attributes to one input.

- **Zero**: a zero price, quantity, or credit, which a guard that only rejects negatives lets through.
- **Negative**: a negative amount or count, which reverses the direction of a ledger move.
- **Fractional**: a fractional quantity or amount where the domain expects an integer.
- **Boundary pair**: the minimum and the maximum the field admits, including the values one step outside them.
- **Extreme magnitude**: a figure large enough to overflow an intermediate computation.
- **Scientific notation**: a figure a custom numeric scalar may parse natively and round.
- **Oversized string**: a numeric string longer than the scalar's own parse path expects.
- **Separator and whitespace shapes**: grouped digits, leading and trailing whitespace, and locale separators, which different parsers read differently.
- **Selector switch**: currency, locale, timezone, and tax-region values varied one at a time, because each may switch a ruleset or a rounding rule.
- **Rounding pair**: the per-item and the per-order computation of one figure, compared at the boundary where they diverge.
- **Archived figure swap**: an approved price or rate replaced by a superseded one between approval and capture.
- **Client-computed total**: a total, tax, or discount altered on the caller side while the line items stay fixed.
- **Sequential sub-moves**: one constrained move split into steps, to test rounding accumulation across steps.
- **Multiplexed duplicate**: one request carrying the same logical operation twice, as the pre-parallel confirmation of a duplication candidate.

## The Oracle

- Compute the expected figure independently from trusted sources before submitting anything.
- Compare the committed figure against the oracle, never against the response echo, because a response can echo optimistically.
- Treat a corrected figure as a held guard, and an altered figure that commits as the finding.
- Re-read the authoritative ledger after a settling delay, and treat a quote-only delta as inconclusive rather than positive.

## Selector Discipline

- Change one selector per submission, so the delta attributes to the ruleset switch rather than to the payload.
- Hold the operation identical across selector values.
- Confirm a selector-driven difference against the published rate table before filing, because a documented difference is not a gap.

## Failure-Mode Index

- **Recomputation absent at the boundary**: the transition accepts the figure as given, and the ledger records a value the ruleset would not produce.
- **Scalar fallback**: a custom numeric type falls back to native floating-point parsing on a shape its author never anticipated, so rounding error enters at the parser rather than at the ruleset.
- **Rounding applied per item instead of per order**: the boundary where the two computations diverge favours the caller.
- **Stale rate behind a selector**: the ruleset switch changes the figure without a matching rate refresh.
- **Approval trusted at capture**: the later step reads the stored figure rather than re-reading the current one.
- **Benefit surviving its condition**: a discount or entitlement persists after the qualifying item is removed or the plan is downgraded.
- **Accumulation across sub-moves**: each step is individually valid while the sequence nets a gain.

## Delegation

- The concurrent submission primitive is owned by `race-conditions`; the single-request multiplexed duplicate is the pre-parallel confirmation.
- The counter key behind a quota is owned by the `defence-bypass` family at its throttle-evasion step.
- The authorization verdict behind an entitlement change is owned by `two-principal-authz` and the function-level class.
- The instrument-arbitrage cycle is owned by the `business-logic` parent core, and the record of it is a ledger read rather than a value probe.

## False Positives

- Promotional behaviour explicitly allowed by policy, with matching ledger annotations.
- A visual-only quote drift with no durable ledger change after settling.
- A selector-driven difference that matches the published rate table exactly.
- A server-corrected total where the commit reflects the recomputed figure.
