---
name: proxy-techniques-url-parser-differential
description: Destination parse differential where two components read one destination value differently, covering authority boundary gaps when separators or userinfo split the parse, duplicate destination precedence when each component reads a different occurrence, notation folding when case, trailing dots, or encoded separators resolve on one side only, and server-side URL construction when a builder interpolates the value into a backend destination.
metadata:
  version: 1.0.0
---

# Destination Parse Differential

One destination value, two readers, two targets. This variant exploits the gap between the component that approves a destination and the component that connects to or navigates to it, by shaping a value whose authority, path, or scheme resolves differently on each side. The goal is an approval of one target and a connection to another, confirmed at the arriving target.

## Attack Surface

- **Applicability**: centers on one destination value read by more than one component before a connection is made.
- **Surface composition**: destination parameters and callback values, location and continuation values, authority and forwarding fields, and client or library components that complete a value against their own base.
- **Widening factors**: values whose separators, userinfo, fragments, case, or encoding resolve differently per reader, and duplicate destination members whose precedence differs per reader, both widen the surface.
- **Out-of-scope variant**: a value that one component reads and connects to directly rides outside this variant, because there is no second reader to disagree with.

## Reconnaissance

- **Reconnaissance scope**: destination parse differentials compare the readers before crafting, because the gap is between two parses of one value.
- **Reader inventory**: list the components that read the destination value and record the target each one derives from it.
- **Refusal baseline**: establish the refusal baseline with a plainly external destination the approver rejects, so a later arrival is attributable to the second parse.
- **Element probing**: probe one structural element at a time: authority boundary, userinfo, fragment, path, scheme, and duplicate occurrence.
- **Folding reader**: note which reader folds case, resolves relative values, or decodes separators, because the untouched element is the bypass.

## Detection Channels

- **Channel scope**: destination parse differentials listen to the two targets one value yields.
- **Two-target value**: the same destination value read as two different targets by two components, which is the primary signal.
- **Unnamed-target arrival**: an arrival at a target the approver never named, which proves the consuming parse won.
- **Paired baseline**: a paired baseline where the direct destination and the shaped value reach different targets across one operation.
- **Derived-target record**: the full chain recorded with each reader's derived target, which shows where the parses diverged.
- **Builder error**: a definition or route error naming a backend destination the caller never sent, which proves the value reached a URL builder rather than a text validator.
- **Identical parses**: a negative that holds across every shaped element, which reads as readers that parse identically.

## Adversarial Capabilities

- **Prerequisites**: destination parse differentials presuppose a reader inventory plus destination-shaping freedom plus an arrival oracle, and they consume all three.
- **Paired answers**: send a plainly external destination and a shaped candidate to the same position, and read both answers.
- **One element per attempt**: shape one structural element per attempt: separator, userinfo, fragment, case, or encoding.
- **Member duplication**: duplicate the destination member with two distinguishable values, so each reader's precedence is nameable.
- **Arrival listener**: reach the arriving target with a listener, because the shaped value's own response names only the approver's parse.

## Trust Assumptions

- **The agreement**: the destination check trusts that every component reading the destination resolves it to the same target, holds the readers to one parse of the authority, holds the path and the fragment to the same resolution, holds duplicate members to one precedence, and holds relative values to one base.
- **The failing clause**: this variant breaks the parse clause because two readers derive different targets from one value, so the approver clears a destination the consumer never connects to.
- **Claim discipline**: the arrival is claimed only when both derived targets are recorded, because one parse alone cannot show a disagreement.

## Key Vulnerabilities

### Authority Boundary Gaps

- **Authority boundary**: split the authority boundary so the approver reads the approved host and the consumer connects to another: userinfo shapes, separator substitutes, mixed slashes, and control or whitespace characters that one side strips.
- **Visible approved host**: keep the approved host visible to the approver, because the check reads the value it derives rather than the value's text.
- **Ownership**: the parent path-mapping step covers one destination value and cannot describe two derived targets, so this variant owns the parse-comparison procedure.

### Duplicate Destination Precedence

- **Duplicate sending**: send the destination member twice with two distinguishable values, because the approver often reads the first occurrence and the consumer the last.
- **Ordering variation**: vary the ordering across attempts so each reader's precedence is established rather than assumed.
- **Stop condition**: treat a consumer that reads the same occurrence as the approver as a stop condition for this element.

### Notation and Relative Folding

- **Notation shaping**: shape trailing dots, case, width variants, numeric address forms, and encoded separators, because one side folds or decodes what the other reads as data.
- **Relative completion**: complete a relative value against the consumer's own base where the approver resolves it differently, and name `proxy-techniques-client-side-path-traversal` where the consumer is a client that builds its request path from the value.
- **Delimiter family**: probe the delimiter and encoded-path family per element: separators, encoded separators, dot segments, a trailing dot, case, and a terminating null or fragment, because each reader resolves the element on its own.
- **Decode-count hand-off**: treat a decode-count disagreement on one value as the encoding differential's step rather than this one, and keep this variant on the destination's structure.
- **URL parse differential matrix**: see `references/url-parse-differential-matrix.md` for the notation family across readers.

### Server-Side URL Construction

- **Builder as reader**: where a component interpolates the caller's value into a backend destination, the builder is a second reader: a fragment or terminator inside the value ends the path the builder meant to append, and traversal segments move within the backend destination.
- **Constructed destination**: treat the constructed backend destination as the consumer's parse, and read what the builder emitted rather than what the caller sent.
- **Builder observables**: an API-definition error, a route-not-found error, or an unexpected backend path in a response is the observable that the value reached a server-side URL router rather than a text validator.
- **Out-of-band confirmation**: confirm the derived backend destination out of band where the response reflects nothing, because the builder's own answer names only the builder.

### Cache-Versus-Origin Normalisation

- **Cache-versus-origin normalisation**: where a cache and an origin resolve one path differently, the disagreement is the same two-reader parse gap on a normalising reader; name `proxy-techniques-cache-deception` at its key step rather than restating the key mechanics here.

## Bypass Techniques

- **Bypass scope**: relay shapes are tried only after the direct route is baselined, because a value both readers parse alike carried nothing.
- **Userinfo and separator shapes**: userinfo and separator shapes that move the authority boundary between readers.
- **Duplicate members**: duplicate destination members, where each reader resolves precedence for itself.
- **Notation forms**: trailing dots, case, width variants, and numeric address forms that equalize differently.
- **Encoded separators**: encoded separators resolved by the consumer after the approver read them as data.
- **Relative values**: relative and scheme-relative values completed against the consumer's own base.
- **Interpolated value**: a value interpolated into a server-side destination, where a fragment or terminator ends the built path and traversal segments move within it.

## Chaining Attacks

- **Chain scope**: destination parse differentials chain forward into the class that owns the effect, because a cleared destination is only the first hop.
- **Effect hand-off**: hand the arriving target to the class that owns the effect, and prove the class-specific consequence there.
- **Forwarded hop**: chain into a forwarded hop, because the derived target can itself be a redirecting destination.
- **Relay stack**: chain into the relay step where the same value reaches the origin through a forwarding field.
- **Own-step naming**: name the class at its own step rather than restating its procedure here.

## Testing Methodology

Destination parse differentials compare the readers first and craft second, because the gap is between two parses.

1. **Inventory the readers** - every component that reads the destination value with the target it derives, and the step completes when each reader carries a named derived target.
2. **Baseline the refusal** - send a plainly external destination the approver rejects, and the step completes when a refusal is recorded or the absence of a destination check is recorded with the test that showed it.
3. **Shape one element** - vary the authority boundary, the userinfo, the fragment, the case, or the encoding one per attempt, and the step completes when each element carries a passed or refused verdict.
4. **Duplicate the member** - send two occurrences with distinguishable values, and the step completes when each reader's precedence is recorded.
5. **Reach the derived target** - connect to the target the consumer derives, and the step completes when the arrival is proved at operated infrastructure.
6. **Attribute the divergence** - pair the approver's target with the consumer's target, and the step completes when the element that split the parse is named from the pair.

## False Positives

- **Stop condition**: stop when both readers derived the same target, because an identical parse is not a differential.
- **Identical normalisation**: readers that normalise the value identically before comparing, confirmed by a refusal for every shaped element.
- **Approver-target consumer**: a consumer that connects to the approver's derived target, where the shaped value changed nothing.
- **Tester-side arrival**: an arrival whose source is the tester's client rather than the consumer.
- **Stacked control**: a refusal from a second check behind the first, which shows a stacked control rather than a parse gap.
- **No connection**: a value that reached no connection at all, where the approver cleared it and the request broke later.

## Pro Tips

- **Discipline**: destination parse differentials reward reader inventory plus one element per attempt.
- **Reader inventory**: inventory the readers before crafting, because the disagreement is between components.
- **One element per attempt**: shape one structural element per attempt so the splitting element is nameable.
- **Visible approved host**: keep the approved host visible to the approver, since the check reads its own derived value.
- **Arrival listener**: reach the derived target with a listener, because the response names only the approver's parse.
- **Effect hand-off**: hand the arriving target to the class that owns the effect, and stop at the narrowest proof.

## Summary

One destination value yields two targets when two components parse it differently. Destination parse differentials compare the readers, shape one structural element per attempt, and claim the carry only when both derived targets are recorded.
