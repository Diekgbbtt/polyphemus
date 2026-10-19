---
name: proxy-techniques-css-injection
description: CSS injection as a no-execution data channel, covering attribute-value oracles when a selector matches a secret attribute character by character, prefix recursion when an imported stylesheet conditions the next position on the matched prefix, and policy gating when external resource origins decide whether the leak can leave the page.
metadata:
  version: 1.0.0
---

# CSS Injection

A stylesheet is treated as presentation, and presentation can still read the document and emit requests. This variant carries data with no script execution: an attribute selector matches a secret value one character at a time, and each match emits an out-of-band request that names the matched character. The channel is gated by the page's resource policy rather than by script execution, and the disclosure it produces is consumed by the class that owns the secret.

## Attack Surface

- **Applicability**: centers on an injection point that reaches a stylesheet context and a document value worth reading.
- **Surface composition**: theme and customisation fields, stylesheet editors, template and preview surfaces, and any reflected value that lands inside a style context or a style attribute.
- **Widening factors**: a target whose secret sits in an attribute or a metadata value, and a page whose policy permits external resource origins, both widen the surface.
- **Out-of-scope variant**: a page whose policy locks external resource origins rides outside this variant, because the matched character has no way to leave.

## Reconnaissance

- **Reconnaissance scope**: CSS injection reads the policy and the target before crafting, because the channel needs an injection, a secret, and an egress path.
- **Injection confirmation**: confirm the injection reaches a stylesheet context rather than being escaped into text, and record the smallest style that renders.
- **Policy read**: read the live resource policy first, because external resource origins decide whether the channel can emit anything; name the `defence-bypass` family at this permit step.
- **Target identification**: identify the target value and where it lives: a proof-of-intent value, a token, a nonce, or a key carried in an attribute or metadata.
- **Character set**: map the target's character set, because the oracle needs one selector per candidate character.

## Detection Channels

- **Channel scope**: CSS injection listens to the out-of-band requests the stylesheet emits, so only the entries below are live here.
- **Prefix hit**: one out-of-band hit per matching prefix, which proves the selector matched the target's value.
- **Positioned hit**: a hit carrying the position and the matched character, so the value is reconstructed rather than inferred.
- **Completed extraction**: the hit set forming the real value once every position is solved, which is the completed extraction.
- **Single-position hit**: a single-position hit only for the correct character, which localises the oracle's resolution.
- **Uniform negative**: a negative across every candidate character, which reads as a value the selector cannot match or a policy that blocks egress.

## Adversarial Capabilities

- **Prerequisites**: CSS injection presupposes a stylesheet context plus an out-of-band receiver plus a policy read, and it consumes all three.
- **Context control**: control a value that lands inside a stylesheet context.
- **Receiver operation**: operate a receiver that records each request's position and character, because the hit is the only proof.
- **Policy read**: read the page's resource policy, because a closed policy makes the channel silent rather than blocked.
- **Target record**: hold the target's character set and the target's position in the document.

## Trust Assumptions

- **The agreement**: the page trusts that styles are presentation-only and carry no data, and the policy trusts that a stylesheet reaches only the origins the policy permits, holds a stylesheet to rendering, holds the document's attribute values to the page that set them, and holds external resource origins to the permit that lists them.
- **The failing clause**: this variant breaks the presentation-only clause because a stylesheet reads attribute values and emits them to a receiver, so the page discloses a value it never meant to expose and executes nothing.
- **Claim discipline**: the disclosure is claimed only on out-of-band hits, because a rendered style change cannot separate a match from a blocked request.

## Key Vulnerabilities

### Attribute-Value Oracle

- **Attribute selector**: an attribute selector matches a prefix of the target value, so one candidate character per rule turns the stylesheet into a comparison oracle.
- **Attribute home**: the target value needs an attribute or metadata home, because the selector reads attributes rather than text content.
- **Security-relevant target**: prefer the target whose value is security-relevant, because the channel's cost is per character and only a secret justifies it.

### Prefix Recursion

- **Import recursion**: a single static stylesheet solves one position, and an imported stylesheet conditioned on the matched prefix moves the extraction to the next position; the recursion removes the static limitation.
- **Ordered import chain**: chain the import so each position's rules load only after the previous prefix matched, and keep the receiver's hit log ordered by position.
- **Early stop**: treat a recursion that stops early as a character-set gap rather than as a policy block, and widen the set before concluding.

### Policy Gating and the No-Execution Channel

- **Policy gating**: the channel leaves the page only where the policy permits external resource origins, so read the policy before crafting and record a closed policy as the finding's boundary.
- **Permit pointer**: name the `defence-bypass` family at the permit step where the policy's source list is the control under test.
- **No-execution channel**: this variant executes nothing, so it is not an XSS delivery; it is a disclosure channel that other classes consume, and `information-disclosure` names it at its data-channel step.

## Bypass Techniques

- **Bypass scope**: bypass shapes are tried only after the injection renders and the policy is read, because a closed policy carries nothing.
- **One selector per character**: one selector per candidate character, so each match is attributable to one character.
- **Import recursion**: import recursion that conditions the next position on the matched prefix.
- **Character-set widening**: character-set coverage widened until the recursion stops early no more.
- **Case and encoding variants**: case and encoding variants of the target value where the selector's matching is case-sensitive.
- **Permissive source list**: a policy whose source list omits the receiver's origin, named with the `defence-bypass` family at the permit step.

## Chaining Attacks

- **Chain scope**: CSS injection is a no-execution channel, so every chain names the class that owns the disclosed secret.
- **Disclosure hand-off**: `information-disclosure` at its data-channel step, because the extracted value is the disclosure.
- **CSRF hand-off**: `csrf` where the leaked proof-of-intent value is replayed against the operation it guards.
- **XSS hand-off**: `xss` where the leaked policy value is the permit key that class reuses, so the extraction is the enabling step rather than the execution.
- **Permit pointer**: the `defence-bypass` family where the policy's source list is the control that gates the channel.
- **Own-step naming**: name the class at its own step rather than restating its procedure here.

## Testing Methodology

CSS injection reads the policy first and solves one character second, because the channel is gated before it is useful.

1. **Confirm the injection** - the smallest style that renders, and the step completes when the value is proven to land in a stylesheet context.
2. **Read the policy** - the live resource policy with its permitted origins, and the step completes when the external-origin question is answered from the header rather than assumed.
3. **Identify the target** - the secret value with its attribute home and its character set, and the step completes when the target's position and alphabet are recorded.
4. **Probe one position** - one selector per candidate character against the first position, and the step completes when a single candidate produces the out-of-band hit.
5. **Recurse the positions** - imported stylesheets conditioned on the matched prefix, and the step completes when each solved position narrows the next one's candidate set.
6. **Reconstruct and confirm** - the hit log forming the real value, and the step completes when the reconstructed value is used or accepted by the operation it guards.
7. **Attribute and stop** - separate the disclosure channel from the class that owns the secret's consequence, and the step completes when the channel's enabling role is recorded rather than the whole chain.

## False Positives

- **Stop condition**: stop when no out-of-band hit arrives or the value is not a secret, because neither is a disclosure.
- **Closed policy**: a closed policy: external resource origins are refused, and a blocked request is indistinguishable from a match in the page's own tooling.
- **No hit**: no out-of-band hit, because a rendered style change is not an extraction.
- **Public value**: a value that is not secret, where the channel reads a public attribute and discloses nothing.
- **No attribute home**: a target with no attribute home, where the selector has nothing to match.
- **Ambient requests**: ambient requests mistaken for hits, confirmed by the absence of the position and character markers.
- **Stripped stylesheet**: a policy that permits the receiver but strips the injected stylesheet, where the injection never rendered.

## Pro Tips

- **Discipline**: CSS injection rewards policy reading plus one character per hit plus recursion discipline.
- **Policy first**: read the resource policy first, because the channel is gated by permitted origins rather than by script.
- **One position first**: prove one position before recursing, since a single hit separates the oracle from noise.
- **Position markers**: keep a position and character marker in every request, because the hit log is the extraction's evidence.
- **Character-set widening**: widen the character set when the recursion stops early, because a stopped chain usually means a missing character.
- **Reconstruction proof**: confirm the reconstruction against the operation the value guards, so the disclosure is proven rather than printed.
- **Secret hand-off**: hand the secret to the class that owns its consequence, and stop at the enabling step.

## Summary

A stylesheet reads the document and emits requests, so a secret attribute leaks one character per out-of-band hit with no script execution. CSS injection reads the policy, solves one position at a time through import recursion, and hands the disclosed value to the class that owns its consequence.
