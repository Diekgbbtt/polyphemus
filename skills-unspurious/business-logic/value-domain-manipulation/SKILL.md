---
name: value-domain-manipulation
description: Submit boundary values through constrained transitions when server-side recomputation is missing, cross currency and rounding oracles, and confirm durable ledger gain.
metadata:
  version: 1.0.0
---

# Value-Domain Manipulation

Business logic assumes submitted values stay within domain bounds, yet boundary submissions can pass the transition while the server never recomputes them from trusted sources.
This variant submits edge numerics plus selector-driven ruleset changes plus client-computed totals against a server-side recomputation oracle.
The manipulation goal is durable gain from rounding plus cross-currency mismatch plus accepted client math.

## Attack Surface

Applicability centers on a single constrained transition that accepts value input without recomputing it from trusted sources.
The surface holds pricing plus discount plus refund plus credit operations where totals, taxes, or rates derive from caller-supplied figures.
Currency plus locale plus timezone plus tax-region selectors widen the surface wherever they switch rulesets or rounding behavior.
Simultaneous duplication rides in concurrent-duplication rather than here, because this variant owns only single-transition value oracles.

## Reconnaissance

Manipulation first maps the oracle before submitting, because blind boundary fuzzing cannot separate a recomputed total from an accepted one.
Enumerate the value inputs of the constrained transition and note which figures the server recomputes and which it accepts as given.
Probe client-math acceptance by altering a computed total while holding line items fixed, then compare the charged figure against an independent recomputation.
Record rounding behavior at minimum plus zero plus negative plus fractional boundaries, and record which selector values switch currency rates or tax rules.
Document the conservation-of-value invariant and its authoritative source so every later verdict has a baseline.

## Detection Channels

Manipulation listens for recomputation gaps, so only the entries below are live here.
- Durable ledger gain where the charged or credited figure differs from the independently recomputed expectation.
- Rounding-boundary delta where per-item versus per-order rounding favors the caller at a boundary.
- Cross-selector mismatch where changing currency or locale or tax region alters value without a matching rate refresh.
- Accepted client-math signal where an altered total commits instead of being corrected or rejected.
- Retained benefit after a post-commit mutation such as keeping a discount whose qualifying condition no longer holds.

## Adversarial Capabilities

Manipulation presupposes value control plus selector control plus oracle computation, and it consumes all three.
- Supply boundary numerics including zero plus negative plus fractional plus extreme-magnitude figures through legitimate fields.
- Switch business selectors such as currency plus locale plus timezone plus tax region across otherwise identical submissions.
- Alter client-computed totals while holding the underlying line items fixed.
- Replay a prior approval with swapped value parameters between approval and capture.
- Recompute expected totals independently from trusted sources to build the oracle verdict.

## Trust Assumptions

The workflow trusts client-supplied values to stay within domain bounds, trusts each transition to run once in order after its precondition check, trusts windowed counters to reset atomically per principal, and trusts every downstream service queue and job to re-enforce the same invariants before mutating state.
Sensitive value plus entitlement plus capability state leaks only when a transition commits outside these clauses.
This variant breaks the domain-bounds clause because boundary values pass the transition while the server never recomputes them from trusted sources.

## Key Vulnerabilities

### Boundary-Value Oracle Submission

Submit minimum plus zero plus negative plus fractional plus shape-swapped figures through the legitimate value fields of one transition.
Compare each committed figure against the independently recomputed expectation rather than against the response echo.
The parent transition step covers only skipping plus repetition plus reordering plus late mutation and cannot describe value-oracle comparison, so this variant owns the oracle procedure.

### Client-Math Acceptance

Alter totals plus taxes plus discounts on the caller side while holding line items fixed, then commit and re-read the authoritative record.
Treat a committed altered total as acceptance failure and treat a server-corrected total as a held guard.
Swap an approved value between approval and capture to test whether the capture re-validates or trusts the earlier step.

### Cross-Selector Arbitrage

Repeat the same purchase-and-refund pair across currency or locale or tax-region selectors to expose stale rates and per-item versus per-order rounding gaps.
Hold the operation identical while varying only the selector so the resulting delta attributes cleanly to the ruleset switch.
Treat deltas visible only in transient quotes as inconclusive until they persist in the settled ledger.

## Advanced Techniques

Advance the oracle once the basic gap lands, because rounding and selector faults often compose across steps.
Stack otherwise incompatible benefit instruments through sequential apply, then remove the qualifying condition and verify whether the benefit persists.
Split one constrained value move into sequential sub-moves only to test per-transition rounding accumulation, leaving simultaneous bursts to the duplication variant.
Carry e-commerce plus banking plus subscription proration shapes as aspects inside the same oracle rather than as separate procedures.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no channel difference changes the value-oracle step itself.
- Content-type wrappers that route the same value fields to a second code path join the oracle as extra lanes.
- Method alternation that performs the same value commit through a second verb joins the oracle the same way.
- Name the proxy-techniques family at the channel-wrapping step rather than restating relay mechanics.
- Name the defence-bypass family at the edge-versus-core gate step rather than restating gateway differentials.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Manipulation chains forward into extraction once the ledger gain is durable, because a quote-only delta alone proves nothing.
- Hand a durable credit or refund delta to repeated claiming to test summation above the captured amount.
- Hand revealed workflow identifiers to identifier-substitution checks to replay the value oracle against sibling resources.
- Name the two-principal-authz skill at the authorization-principal step rather than restating its checks.

## Testing Methodology

Manipulation runs the oracle first and everything else follows, because no later step is meaningful without an independent expectation.
1. **Enumerate the value transition** - list the inputs plus the recomputation claim plus the authoritative source, and the step completes when every figure names its trusted origin or its absence.
2. **Build the recomputation oracle** - compute expected totals independently from trusted sources for the baseline case, and the step completes when the baseline matches the server figure exactly.
3. **Submit boundary values** - send edge numerics plus shape swaps plus altered client math through direct calls, and the step completes when every submission carries a committed figure.
4. **Cross selectors** - repeat the pair across currency plus locale plus tax-region values, and the step completes when each selector carries a delta verdict against the oracle.
5. **Confirm durable gain** - re-read the settled ledger and demonstrate the persisting imbalance, and the step completes when the gain is reproducible and auditable.

## False Positives

Stop when the evidence shows recomputation held, because a corrected total is not a finding.
- Promotional behavior explicitly allowed by policy such as documented trials or goodwill credits with matching annotations.
- Visual-only quote drift with no durable ledger change after settling.
- Server-corrected totals where the commit reflects the recomputed figure rather than the submitted one.
- Selector-driven price differences that match published rate tables exactly.

## Pro Tips

Manipulation rewards oracle discipline plus tiny deltas plus ledger confirmation.
1. Prefer one value change per submission so each delta attributes cleanly to its input.
2. Favor boundary figures over random fuzz because guards fail at edges first.
3. Recompute every expectation independently and never trust the response echo as the oracle.
4. Confirm each suspected gain in the settled ledger after a delay.
5. Stop promoting quote-only drift and record it as inconclusive rather than positive.

## Summary

A transition that trusts caller math commits boundary values without recomputation.
Manipulation submits edge numerics plus selector switches plus altered totals against an independent oracle and confirms only gains that persist in the authoritative source.
