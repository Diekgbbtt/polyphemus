---
name: proxy-techniques-client-side-path-traversal
description: Client-side path traversal where a caller value concatenated into the path component of a client-built request traverses to a different endpoint, covering relative-base completion when the client resolves the value against its own base, gadget-endpoint chaining when the traversed request reaches a redirecting or reflecting endpoint, and response control when the client follows the redirect and renders the attacker's answer.
metadata:
  version: 1.0.0
---

# Client-Side Path Traversal

A client builds a request path by concatenating a value it was given, and the value can walk that path elsewhere. This variant relocates the request client-side: the traversed path reaches a gadget endpoint, the client follows the redirect the caller does not control, and the response the page renders is the attacker's. The traversal alone is often low impact, so this leaf is the family's client-request-construction mechanism and every chain names the class that owns the response's consequence.

## Attack Surface

- **Applicability**: centers on a client-built request whose path component carries a caller-influenced value.
- **Surface composition**: client request constructions that concatenate a value into the path rather than the query, clients that complete a relative value against their own base, and redirecting or reflecting endpoints on the same origin that can act as the arrival.
- **Widening factors**: a response the page renders into markup, evaluates, or binds into state, and a client that follows redirects without re-checking the destination, both widen the surface.
- **Out-of-scope variant**: a request whose path is fixed or whose value is encoded before concatenation rides outside this variant, because the value cannot relocate the path.

## Reconnaissance

- **Reconnaissance scope**: client-side path traversal maps the request constructions and the gadget endpoints before crafting, because the mechanism needs both a path that moves and an endpoint worth reaching.
- **Construction inventory**: enumerate the client request constructions and record which parameter lands in the path component rather than the query.
- **Depth count**: count the segments above the value, because the depth needed to reach the root or a chosen endpoint is arithmetic.
- **Gadget search**: find a gadget endpoint: a redirecting endpoint whose destination is caller-influenced, or an endpoint whose response the page renders.
- **Encoding and follow**: record the client's encoding behaviour and its redirect-follow behaviour, because both decide whether the traversal survives the request.

## Detection Channels

- **Channel scope**: client-side path traversal listens to the relocated request and to the response the page consumes, so only the entries below are live here.
- **Relocated path**: the request path differing from the constructed one, which proves the value relocated the request.
- **Unintended arrival**: an arrival at an endpoint the page never intended to call, carrying the victim's session.
- **Followed redirect**: the redirect followed to an operated target, which proves the client's own follower carried the request onward.
- **Response consumption**: the response rendered into markup, bound into state, or evaluated by the page, which proves the arrival's answer is consumed.
- **Depth differential**: an encoding-depth differential between the checker's depth and the client's depth, which localises the decode disagreement.
- **Uniform negative**: a negative that holds across every depth and encoding, which reads as a client that encodes the value.

## Adversarial Capabilities

- **Prerequisites**: client-side path traversal presupposes path influence plus a gadget endpoint plus a response read, and it consumes all three.
- **Path influence**: influence a value the client concatenates into a request path.
- **Gadget endpoint**: control or find a gadget endpoint on the same origin whose destination or response is caller-influenced.
- **Depth and encoding read**: read the depth and the encoding the client applies, because both decide whether the traversal lands.
- **Consumption observation**: observe the response consumption in the page, because a relocated request whose answer is discarded carries nothing.

## Trust Assumptions

- **The agreement**: the client trusts that its own concatenation preserves the intended path, and the page trusts that a response it fetched is the endpoint's own answer, holds the concatenated value to one path segment, holds the client's base to the intended origin, and holds the fetched response to the endpoint the page meant to call.
- **The failing clause**: this variant breaks the request-construction clause because a caller value relocates the request path, so the client fetches an endpoint the page never chose and renders the answer as its own.
- **Claim discipline**: the effect is claimed only when the arrival's response is consumed by the page, because a relocated request with a discarded answer proves nothing.

## Key Vulnerabilities

### Relative-Base Completion and Traversal

- **Relative-base completion**: a value completed against the client's own base resolves to a path outside the intended directory, because the client resolves the value rather than validating it.
- **Depth arithmetic**: traversal depth is arithmetic: the number of segments above the value minus the number of upward segments yields the arriving depth.
- **Path-component confirmation**: confirm the value lands in the path component, because the same value in the query string changes nothing.
- **Definable base**: where the base the value completes against is a named element or a global the markup can define, markup alone supplies the base; name `proxy-techniques-dom-clobbering` at that step rather than restating the mechanism.

### Gadget Endpoint and Redirect Follow

- **Redirecting gadget**: the traversal reaches a redirecting endpoint whose destination is caller-influenced, and the client follows the redirect because its follower is not the caller's to control; name `proxy-techniques-redirect-chain` at this step.
- **Reflecting gadget**: a reflecting endpoint whose response the page consumes is the other gadget kind, because the arrival's answer is what the page renders.
- **Single chain**: keep the traversal and the follow as one chain, since the traversal alone reaches an endpoint the page still treats as its own.
- **Gadget chain**: see `references/cspt-gadget-chain.md` for the worked traversal-to-gadget chain.

### Response Control and Encoding Depth

- **Response control**: the response the client receives is the attacker's, and what the page does with it decides the consequence: markup insertion, evaluation, or a state binding.
- **Encoding depth**: where a checker also reads the path, select the encoding depth that keeps the checker's depth non-negative while the client's depth goes negative; name `defence-bypass-encoding-differential` at this step.
- **Encoding checker**: treat a checker that encodes before counting as a recorded negative rather than a dead end, and move to the next encoding level.

## Bypass Techniques

- **Bypass scope**: bypass shapes are tried only after the request construction and the depth are mapped, because a path that does not move carries nothing.
- **Upward segments**: upward segments sized to the depth between the value and the target endpoint.
- **Encoded separators**: encoded separators resolved by the client after a checker read them as data.
- **Padding segments**: padding segments that keep a depth-counting checker non-negative while the client's depth goes negative.
- **Mixed encoding levels**: mixed encoding levels where the checker and the client decode a different number of times.
- **Truncating character**: a truncating character that ends a depth-counting checker's scan before the traversal is read.
- **Redirecting gadget**: a redirecting gadget endpoint the client follows without re-checking the destination.

## Chaining Attacks

- **Chain scope**: client-side path traversal is a request-relocation mechanism, so every chain names the class that owns the response's consequence.
- **XSS hand-off**: `xss` where the page renders the arrival's response into an executable sink, because the execution belongs to that class.
- **CSRF hand-off**: `csrf` where the relocated request reaches a state-changing endpoint under the victim's session.
- **Disclosure hand-off**: `information-disclosure` and `idor` where the arrival returns data the page's own endpoint would not, read with the victim's authority.
- **Redirect hand-off**: `open-redirect` where the gadget is the redirecting endpoint itself.
- **Follower pointer**: `proxy-techniques-redirect-chain` at the follower step, because the client's own follow is the redirect-carry mechanism.
- **Own-step naming**: name the class at its own step rather than restating its procedure here.

## Testing Methodology

Client-side path traversal maps the construction and the gadget first and crafts the depth second, because the mechanism needs both a moving path and a worth-reaching endpoint.

1. **Map the request constructions** - every client request whose path carries a value, with the parameter that controls it, and the step completes when each construction carries its path-controlling value.
2. **Count the depth** - the segments above the value and the depth needed to reach the root or a chosen endpoint, and the step completes when the traversal depth is stated as a number.
3. **Find the gadget** - a redirecting or reflecting endpoint the traversal can reach, and the step completes when the gadget's caller-influenced element is named.
4. **Confirm the relocation** - send the traversed value and read the arriving request path, and the step completes when the arrival endpoint differs from the intended one.
5. **Follow the redirect** - the client's own follow to an operated target, and the step completes when the arrival is attributed to the client rather than to the caller.
6. **Confirm the consumption** - the response rendered or bound by the page, and the step completes when the page's use of the arrival's answer is observed.
7. **Attribute and stop** - separate the request relocation from the class that owns the response's consequence, and the step completes when the chain's enabling step is recorded rather than the whole chain.

## False Positives

- **Stop condition**: stop when the value cannot relocate the path or the arrival's answer is discarded, because neither is a traversal finding.
- **Query-string value**: a value that lands in the query string, where the routing ignores it.
- **Encoding client**: a client that encodes the value before concatenation, confirmed by an encoded arrival path.
- **Static-only arrival**: a traversed path that reaches only static resources with no caller-influenced destination or response.
- **Discarded answer**: an arrival whose response the page never renders, evaluates, or binds.
- **Client-side normalisation**: a defence layer that normalises the path before the request leaves the client, confirmed across every depth and encoding.
- **Intended follow**: a redirect follow that lands on the intended endpoint, where the traversal changed nothing.

## Pro Tips

- **Discipline**: client-side path traversal rewards depth arithmetic plus a gadget endpoint plus a consumption read.
- **Depth first**: count the depth before crafting, because the traversal is arithmetic rather than a payload.
- **Path-component confirmation**: confirm the value lands in the path component, since the query string changes nothing.
- **Gadget first**: find the gadget before crafting the traversal, because the arrival's endpoint is half the mechanism.
- **Encoding and follow read**: read the client's encoding and follow behaviour, since both decide whether the traversal survives.
- **Consumption proof**: prove the page consumes the arrival's answer, because a discarded response carries nothing.
- **Response hand-off**: hand the response to the class that owns its consequence, and stop at the enabling step.

## Summary

A value concatenated into a client-built path walks the request to an endpoint the page never chose, and the client's own follower carries it further. Client-side path traversal counts the depth, reaches a gadget endpoint, and hands the response it controls to the class that owns the consequence.
