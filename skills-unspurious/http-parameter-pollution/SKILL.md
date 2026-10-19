---
name: http-parameter-pollution
description: HTTP parameter pollution testing for duplicate members whose resolution differs across readers, covering server-side precedence when a duplicate decides a security-relevant value, split-payload reassembly when individually benign duplicates join into the withheld effect, and client-side injection when a reflected value re-splits into a second parameter downstream.
metadata:
  version: '1.0.0'
---

# HTTP Parameter Pollution

A request may carry one member more than once, and every reader that consumes it resolves the duplicates for itself.
This class owns the application's own duplicate handling: where a duplicate reaches a decision, where two readers disagree on which occurrence they consume, and where a value re-splits into a second parameter in a link a consumer rebuilds.
The bypass mechanics stay with the skills that own them: the duplicate-member precedence procedure is `defence-bypass-parser-confusion`, the duplicate-header case is a `header-injection` aspect, and the destination-member case names `proxy-techniques-url-parser-differential`.

## Attack Surface

- **Applicability**: any request that carries a repeated member, in the query string, a structured body, a form body, or a nested serialisation.
- **Decision points**: duplicates that reach a value the application decides on, such as an amount, a quantity, a role, a status, a destination, or a filter.
- **Reader pairs**: the validating component and the consuming component, or two components on the path that each pick a different occurrence.
- **Reflection surfaces**: responses and links that echo a parameter back, so a carried separator can re-split into a second parameter in the consumer's own construction.
- **Header case**: duplicate headers are a `header-injection` bypass aspect rather than a member of this class, and the class names that skill at the step.

## Reconnaissance

### Precedence Discovery

- **Duplicate probe**: send one member twice with two distinguishable values and read which value the application acts on, because the response names the winning occurrence.
- **Ordering probe**: reverse the pair and re-send, because a reader that takes the first occurrence and one that takes the last are different consumers.
- **Joining probe**: send a pair whose joined form is distinguishable from either value alone, because a concatenating reader returns the joined string.
- **Structured-body probe**: repeat the pair in every body shape the operation accepts, because each serialisation may resolve duplicates on its own.

### Reader and Reflection Mapping

- **Reader inventory**: list the components that read the member and record the occurrence each one consumes for the same effect.
- **Reflection tracing**: follow a reflected parameter into every link, redirect, or share value the application builds from it, because the consumer of that link resolves duplicates again.
- **Baseline pair**: record the canonical single-member request's answer, so a later pass is attributable to the duplicate.

## Detection Channels

- **Winning occurrence**: the response or state change naming which duplicate the application consumed, which proves the resolution rule.
- **Divergent verdicts**: a duplicate pair refused by the validating component while the consuming component acts on the other occurrence, which proves the two readers disagree.
- **Split reassembly**: the withheld effect appearing while each duplicate value is individually benign, which proves the sink joined them.
- **Value override**: a security-relevant value decided by the second occurrence, which proves the duplicate reached the decision.
- **Re-split parameter**: a second parameter appearing in a link the application built from a reflected value, which proves the consumer re-resolved the carried separator.
- **Paired baseline**: the canonical request's verdict beside the duplicate pair's verdict for one effect, which localises the duplicate as the changed variable.

## Adversarial Capabilities

- **Member duplication**: the ability to send a repeated member in the query string and in each body shape the operation accepts.
- **Reader visibility**: enough of the path to record which component consumes which occurrence.
- **A reflection surface**: a value the application echoes into a link or a response, so the re-split can be observed.
- **A control baseline**: a refused single-member request, so a split pass is attributable to the reassembly.
- **Ordering control**: the ability to vary the pair's order and its spelling, so each reader's precedence is established rather than assumed.

## Trust Assumptions

- **The agreement**: the application trusts that one member carries one value, that every reader of the request resolves a duplicate the same way, and that a value it echoes into a link stays one parameter for the consumer of that link.
- **The failing clause**: this class breaks the single-resolution clause because a repeated member resolves differently per reader, so the value a check approved and the value the decision consumed are different occurrences.
- **Claim discipline**: a duplicate is claimed as a finding only when the winning occurrence reaches a decision or an effect, because an ambiguity with no consequence is noise.

## Key Vulnerabilities

### Server-Side Precedence Over a Decision

- **Decision override**: a duplicate whose winning occurrence differs from the one the validator inspected decides a security-relevant value, so the checked value and the consumed value differ.
- **Rule per reader**: each component on the path applies its own precedence, so a pair ordered for the validator can be ordered against the consumer.
- **Ownership**: the precedence mechanism belongs to `defence-bypass-parser-confusion`; this class owns the decision the duplicate reaches and the impact it produces.

### Split-Payload Reassembly

- **Individually benign parts**: a payload split across duplicates reads as harmless on each occurrence and is joined by the sink, so a value-based check sees fragments rather than the effect.
- **Joining readers**: the reassembly happens wherever a reader concatenates duplicates, which is the same rule the precedence probe establishes.
- **Delegation**: name the `defence-bypass` family at this step, because the split is a matcher and decode gap rather than a duplicate-resolution decision.

### Client-Side Re-Splitting

- **Carried separator**: a value reflected into a link may carry an encoded separator that the link's consumer decodes and re-splits, injecting a second parameter into a request the victim's client makes.
- **Downstream consumer**: the effect lands on the consumer of the rebuilt link, which is a class that owns the consequence, such as `open-redirect` at its destination step or `oauth` at its redirect step.
- **Ownership**: this class owns the re-split into a second parameter; the destination parse disagreement itself stays with `proxy-techniques-url-parser-differential`.

### Duplicate Destination Members

- **Approver and consumer**: a duplicated destination member is read as one occurrence by the approver and another by the consumer, so the approved destination and the connected destination differ.
- **Delegation**: name `proxy-techniques-url-parser-differential` and the destination-owning class at this step rather than restating their procedures.

## Advanced Techniques

- **Differential ordering**: send both orderings of one pair before concluding, because a single ordering establishes one reader's rule only.
- **Serialisation spread**: repeat one pair across the query string, the form body, the structured body, and the nested shape, because each serialisation resolves duplicates separately.
- **Join proof**: prefer the pair whose joined form is observable in the response, because the join is the reassembly proof rather than an inference.
- **Reflection chase**: follow a reflected value through every link the application builds, because the re-split happens at the consumer rather than at the reflection.

## Bypass Techniques

Bypass shapes are tried only after the canonical single-member request is baselined, because a duplicate that changes nothing is not a bypass.

- **Precedence shaping**: order the duplicate pair so the validator reads the approved occurrence and the consumer reads the other one.
- **Split reassembly**: divide one effect across duplicates so each occurrence is individually benign and the sink joins them; name the `defence-bypass` family at this step.
- **Spelling variants**: fold the duplicated identifier's spelling so a per-name rule sees a fresh name while the consumer resolves the same entity.
- **Serialisation swap**: carry the duplicate in a second body shape the validator does not parse.
- **Carried separator**: place an encoded separator inside a reflected value so the consumer of the rebuilt link re-splits it into a second parameter.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

A duplicate member is a mechanism rather than a finding, so the decision it reaches hands forward to the class that owns the consequence.

- **Value layer**: `business-logic` where the duplicate decides an amount, a quantity, a price, or a quota.
- **Destination layer**: `open-redirect` and `oauth` where the duplicate decides a destination or a redirect target.
- **Authorization layer**: the function-level and object-level classes where the duplicate decides a role, a scope, or an identifier.
- **Enforcement layer**: `defence-bypass-parser-confusion` where the duplicate exists to split a value past a control.
- **Header layer**: `header-injection` where the duplicate is a repeated header rather than a repeated member.

## Testing Methodology

Parameter pollution establishes the resolution rule first and exercises the decision second, because the rule is a property of the readers.

1. **Inventory the operations** - every operation that accepts a repeated member, and the step completes when each operation carries its accepted member shapes.
2. **Baseline the canonical request** - the single-member request with its answer recorded, and the step completes when the refusal or the admit answer is recorded for comparison.
3. **Establish precedence** - both orderings of one pair, then a pair whose joined form is distinguishable, and the step completes when each reader's occurrence and the join behaviour are recorded.
4. **Repeat across shapes** - the same pair in the query string and in each body shape, and the step completes when every shape carries a precedence verdict.
5. **Reach the decision** - substitute the duplicate into the value the operation decides on, and the step completes when the second occurrence is the one the decision consumed.
6. **Probe the split** - divide one refused effect across duplicates and confirm the sink reassembles it, and the step completes when the effect reproduces while each occurrence stays individually benign.
7. **Chase the reflection** - carry an encoded separator inside a reflected value and read the link the consumer rebuilds, and the step completes when the second parameter appears downstream.
8. **Attribute and stop** - separate the duplicate's effect from a class-specific gap and from an absent check, and the step completes when the narrowest proof carries its attribution.

## False Positives

Stop when the duplicate changed nothing the application decides on, because an unresolved ambiguity is not a finding.

- **Single-resolution readers**: every reader consumes the same occurrence, confirmed across both orderings and every shape.
- **Rejected duplicates**: the application refuses requests carrying a repeated member, confirmed by a uniform rejection.
- **No decision reached**: the duplicate wins the resolution and the value is never used in a decision or an effect.
- **Client-side-only artifact**: the re-split appears in the tester's own client construction and reaches no consumer.
- **Broken request**: the duplicate pair passes the validator and the request fails before the effect.
- **Replay or simulator**: a response that answers the duplicate without a real resolution rule behind it.

## Pro Tips

Parameter pollution rewards precedence discipline plus a decision to reach.

1. Read the readers before crafting, because the resolution rule is a property of the components rather than of the payload.
2. Send both orderings, since one ordering names one reader only.
3. Prefer the duplicate that reaches a decision, because an unresolved ambiguity proves nothing.
4. Keep the two occurrences individually benign where the goal is a split, so the reassembly is the finding.
5. Chase reflections into the links they feed, because the re-split happens at the consumer.
6. Name the owning skill at each delegated step rather than restating its procedure.

## Summary

A repeated member resolves per reader, and every decision a duplicate reaches is the finding. HTTP parameter pollution establishes the precedence rule, exercises the decision it feeds, and follows the value into the links whose consumers re-split it, before handing the class its step.
