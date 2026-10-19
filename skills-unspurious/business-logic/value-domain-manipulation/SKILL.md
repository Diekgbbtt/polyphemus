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

- **Applicability**: centers on a single constrained transition that accepts value input without recomputing it from trusted sources.
- **Held surface**: the surface holds pricing plus discount plus refund plus credit operations where totals, taxes, or rates derive from caller-supplied figures.
- **Widening shapes**: currency plus locale plus timezone plus tax-region selectors widen the surface wherever they switch rulesets or rounding behavior.
- **Out-of-scope variants**: simultaneous duplication rides in concurrent-duplication rather than here, because this variant owns only single-transition value oracles.

## Reconnaissance

- **Oracle mapping**: manipulation first maps the oracle before submitting, because blind boundary fuzzing cannot separate a recomputed total from an accepted one.
- **Input enumeration**: enumerate the value inputs of the constrained transition and note which figures the server recomputes and which it accepts as given.
- **Client-math probing**: probe client-math acceptance by altering a computed total while holding line items fixed, then compare the charged figure against an independent recomputation.
- **Rounding recording**: record rounding behavior at minimum plus zero plus negative plus fractional boundaries, and record which selector values switch currency rates or tax rules.
- **Invariant documentation**: document the conservation-of-value invariant and its authoritative source so every later verdict has a baseline.

## Detection Channels

- **Channel scope**: manipulation listens for recomputation gaps, so only the entries below are live here.
- **Ledger gain**: durable ledger gain where the charged or credited figure differs from the independently recomputed expectation.
- **Rounding-boundary delta**: rounding-boundary delta where per-item versus per-order rounding favors the caller at a boundary.
- **Cross-selector mismatch**: cross-selector mismatch where changing currency or locale or tax region alters value without a matching rate refresh.
- **Client-math acceptance**: accepted client-math signal where an altered total commits instead of being corrected or rejected.
- **Retained benefit**: retained benefit after a post-commit mutation such as keeping a discount whose qualifying condition no longer holds.

## Adversarial Capabilities

- **Prerequisites**: manipulation presupposes value control plus selector control plus oracle computation, and it consumes all three.
- **Boundary numerics**: supply boundary numerics including zero plus negative plus fractional plus extreme-magnitude figures through legitimate fields.
- **Selector switching**: switch business selectors such as currency plus locale plus timezone plus tax region across otherwise identical submissions.
- **Client-total alteration**: alter client-computed totals while holding the underlying line items fixed.
- **Approval replay**: replay a prior approval with swapped value parameters between approval and capture.
- **Oracle computation**: recompute expected totals independently from trusted sources to build the oracle verdict.

## Trust Assumptions

- **The agreement**: the workflow trusts client-supplied values to stay within domain bounds, trusts each transition to run once in order after its precondition check, trusts windowed counters to reset atomically per principal, and trusts every downstream service queue and job to re-enforce the same invariants before mutating state.
- **The exposure**: sensitive value plus entitlement plus capability state leaks only when a transition commits outside these clauses.
- **The failing clause**: this variant breaks the domain-bounds clause because boundary values pass the transition while the server never recomputes them from trusted sources.

## Key Vulnerabilities

### Boundary-Value Oracle Submission

- **Boundary submission**: submit minimum plus zero plus negative plus fractional plus shape-swapped figures through the legitimate value fields of one transition.
- **Parser fallback**: submit scientific-notation and oversized-string figures too, because a custom decimal or money scalar frequently falls back to native floating-point parsing on inputs its author never anticipated, which reintroduces rounding error at the parser rather than at the ruleset.
- **Expectation comparison**: compare each committed figure against the independently recomputed expectation rather than against the response echo.
- **Ownership boundary**: the parent transition step covers only skipping plus repetition plus reordering plus late mutation and cannot describe value-oracle comparison, so this variant owns the oracle procedure.

### Client-Math Acceptance

- **Caller-side alteration**: alter totals plus taxes plus discounts on the caller side while holding line items fixed, then commit and re-read the authoritative record.
- **Verdict rules**: treat a committed altered total as acceptance failure and treat a server-corrected total as a held guard.
- **Approval-to-capture swap**: swap an approved value between approval and capture to test whether the capture re-validates or trusts the earlier step.

### Cross-Selector Arbitrage

- **Selector-pair repetition**: repeat the same purchase-and-refund pair across currency or locale or tax-region selectors to expose stale rates and per-item versus per-order rounding gaps.
- **Single-variable selectors**: hold the operation identical while varying only the selector so the resulting delta attributes cleanly to the ruleset switch.
- **Transient-quote handling**: treat deltas visible only in transient quotes as inconclusive until they persist in the settled ledger.

## Advanced Techniques

- **Oracle advance**: advance the oracle once the basic gap lands, because rounding and selector faults often compose across steps.
- **Instrument stacking**: stack otherwise incompatible benefit instruments through sequential apply, then remove the qualifying condition and verify whether the benefit persists.
- **Value cycling**: cycle value between a purchase instrument and a redemption instrument so each step is individually valid while the cycle nets positive, then repeat the cycle and confirm the gain in the ledger rather than in the quote.
- **Stale-price swapping**: swap an approved price for an archived or superseded one between the approval and the capture, which tests whether the capture re-reads the current price or trusts the stored figure.
- **Entitlement boundary cases**: carry identity-domain and email-truncation boundary cases into the same oracle where a value change feeds an entitlement change, since the boundary rule decides the entitlement rather than the price.
- **Sequential sub-moves**: split one constrained value move into sequential sub-moves only to test per-transition rounding accumulation, leaving simultaneous bursts to the duplication variant.
- **Aspect carriage**: carry e-commerce plus banking plus subscription proration shapes as aspects inside the same oracle rather than as separate procedures.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no channel difference changes the value-oracle step itself.
- **Content-type wrappers**: content-type wrappers that route the same value fields to a second code path join the oracle as extra lanes.
- **Method alternation**: method alternation that performs the same value commit through a second verb joins the oracle the same way.
- **Proxy-family naming**: name the proxy-techniques family at the channel-wrapping step rather than restating relay mechanics.
- **Defence-family naming**: name the defence-bypass family at the edge-versus-core gate step rather than restating gateway differentials.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Forward chaining scope**: manipulation chains forward into extraction once the ledger gain is durable, because a quote-only delta alone proves nothing.
- **Repeated-claim chaining**: hand a durable credit or refund delta to repeated claiming to test summation above the captured amount.
- **Identifier chaining**: hand revealed workflow identifiers to identifier-substitution checks to replay the value oracle against sibling resources.
- **Principal naming**: name the two-principal-authz skill at the authorization-principal step rather than restating its checks.

## Testing Methodology

Manipulation runs the oracle first and everything else follows, because no later step is meaningful without an independent expectation.
1. **Enumerate the value transition** - list the inputs plus the recomputation claim plus the authoritative source, and the step completes when every figure names its trusted origin or its absence.
2. **Build the recomputation oracle** - compute expected totals independently from trusted sources for the baseline case, and the step completes when the baseline matches the server figure exactly.
3. **Submit boundary values** - send edge numerics plus shape swaps plus altered client math through direct calls, and the step completes when every submission carries a committed figure.
4. **Cross selectors** - repeat the pair across currency plus locale plus tax-region values, and the step completes when each selector carries a delta verdict against the oracle.
5. **Confirm durable gain** - re-read the settled ledger and demonstrate the persisting imbalance, and the step completes when the gain is reproducible and auditable.

## False Positives

- **Stop condition**: stop when the evidence shows recomputation held, because a corrected total is not a finding.
- **Policy-allowed behavior**: promotional behavior explicitly allowed by policy such as documented trials or goodwill credits with matching annotations.
- **Visual-only drift**: visual-only quote drift with no durable ledger change after settling.
- **Server-corrected totals**: server-corrected totals where the commit reflects the recomputed figure rather than the submitted one.
- **Rate-table matches**: selector-driven price differences that match published rate tables exactly.

## Pro Tips

- **Discipline**: manipulation rewards oracle discipline plus tiny deltas plus ledger confirmation.
- **One value change per submission**: prefer one value change per submission so each delta attributes cleanly to its input.
- **Boundary figures**: favor boundary figures over random fuzz because guards fail at edges first.
- **Independent recomputation**: recompute every expectation independently and never trust the response echo as the oracle.
- **Settled confirmation**: confirm each suspected gain in the settled ledger after a delay.
- **Quote-drift caution**: stop promoting quote-only drift and record it as inconclusive rather than positive.

## Summary

A transition that trusts caller math commits boundary values without recomputation.
Manipulation submits edge numerics plus selector switches plus altered totals against an independent oracle and confirms only gains that persist in the authoritative source.
