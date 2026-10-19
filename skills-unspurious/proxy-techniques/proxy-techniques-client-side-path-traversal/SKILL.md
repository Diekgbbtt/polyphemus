---
name: proxy-techniques-client-side-path-traversal
description: Client-side path traversal where a caller value concatenated into the path component of a client-built request traverses to a different endpoint, covering relative-base completion when the client resolves the value against its own base, gadget-endpoint chaining when the traversed request reaches a redirecting or reflecting endpoint, and response control when the client follows the redirect and renders the attacker's answer.
metadata:
  version: '1.0.0'
---

# Client-Side Path Traversal

A client builds a request path by concatenating a value it was given, and the value can walk that path elsewhere. This variant relocates the request client-side: the traversed path reaches a gadget endpoint, the client follows the redirect the caller does not control, and the response the page renders is the attacker's. The traversal alone is often low impact, so this leaf is the family's client-request-construction mechanism and every chain names the class that owns the response's consequence.

## Attack Surface

Client-side path traversal applicability centers on a client-built request whose path component carries a caller-influenced value.
The surface holds client request constructions that concatenate a value into the path rather than the query, clients that complete a relative value against their own base, and redirecting or reflecting endpoints on the same origin that can act as the arrival.
A response the page renders into markup, evaluates, or binds into state, and a client that follows redirects without re-checking the destination, both widen the surface.
A request whose path is fixed or whose value is encoded before concatenation rides outside this variant, because the value cannot relocate the path.

## Reconnaissance

Client-side path traversal maps the request constructions and the gadget endpoints before crafting, because the mechanism needs both a path that moves and an endpoint worth reaching.
- Enumerate the client request constructions and record which parameter lands in the path component rather than the query.
- Count the segments above the value, because the depth needed to reach the root or a chosen endpoint is arithmetic.
- Find a gadget endpoint: a redirecting endpoint whose destination is caller-influenced, or an endpoint whose response the page renders.
- Record the client's encoding behaviour and its redirect-follow behaviour, because both decide whether the traversal survives the request.

## Detection Channels

Client-side path traversal listens to the relocated request and to the response the page consumes, so only the entries below are live here.
- The request path differing from the constructed one, which proves the value relocated the request.
- An arrival at an endpoint the page never intended to call, carrying the victim's session.
- The redirect followed to an operated target, which proves the client's own follower carried the request onward.
- The response rendered into markup, bound into state, or evaluated by the page, which proves the arrival's answer is consumed.
- An encoding-depth differential between the checker's depth and the client's depth, which localises the decode disagreement.
- A negative that holds across every depth and encoding, which reads as a client that encodes the value.

## Adversarial Capabilities

Client-side path traversal presupposes path influence plus a gadget endpoint plus a response read, and it consumes all three.
- Influence a value the client concatenates into a request path.
- Control or find a gadget endpoint on the same origin whose destination or response is caller-influenced.
- Read the depth and the encoding the client applies, because both decide whether the traversal lands.
- Observe the response consumption in the page, because a relocated request whose answer is discarded carries nothing.

## Trust Assumptions

The client trusts that its own concatenation preserves the intended path, and the page trusts that a response it fetched is the endpoint's own answer.
The agreement holds the concatenated value to one path segment, holds the client's base to the intended origin, and holds the fetched response to the endpoint the page meant to call.
This variant breaks the request-construction clause because a caller value relocates the request path, so the client fetches an endpoint the page never chose and renders the answer as its own.
The effect is claimed only when the arrival's response is consumed by the page, because a relocated request with a discarded answer proves nothing.

## Key Vulnerabilities

### Relative-Base Completion and Traversal

- A value completed against the client's own base resolves to a path outside the intended directory, because the client resolves the value rather than validating it.
- Traversal depth is arithmetic: the number of segments above the value minus the number of upward segments yields the arriving depth.
- Confirm the value lands in the path component, because the same value in the query string changes nothing.

### Gadget Endpoint and Redirect Follow

- The traversal reaches a redirecting endpoint whose destination is caller-influenced, and the client follows the redirect because its follower is not the caller's to control; name `proxy-techniques-redirect-chain` at this step.
- A reflecting endpoint whose response the page consumes is the other gadget kind, because the arrival's answer is what the page renders.
- Keep the traversal and the follow as one chain, since the traversal alone reaches an endpoint the page still treats as its own.

### Response Control and Encoding Depth

- The response the client receives is the attacker's, and what the page does with it decides the consequence: markup insertion, evaluation, or a state binding.
- Where a checker also reads the path, select the encoding depth that keeps the checker's depth non-negative while the client's depth goes negative; name `defence-bypass-encoding-differential` at this step.
- Treat a checker that encodes before counting as a recorded negative rather than a dead end, and move to the next encoding level.

## Bypass Techniques

Bypass shapes are tried only after the request construction and the depth are mapped, because a path that does not move carries nothing.

- Upward segments sized to the depth between the value and the target endpoint.
- Encoded separators resolved by the client after a checker read them as data.
- Padding segments that keep a depth-counting checker non-negative while the client's depth goes negative.
- Mixed encoding levels where the checker and the client decode a different number of times.
- A truncating character that ends a depth-counting checker's scan before the traversal is read.
- A redirecting gadget endpoint the client follows without re-checking the destination.

## Chaining Attacks

Client-side path traversal is a request-relocation mechanism, so every chain names the class that owns the response's consequence.

- `xss` where the page renders the arrival's response into an executable sink, because the execution belongs to that class.
- `csrf` where the relocated request reaches a state-changing endpoint under the victim's session.
- `information-disclosure` and `idor` where the arrival returns data the page's own endpoint would not, read with the victim's authority.
- `open-redirect` where the gadget is the redirecting endpoint itself.
- `proxy-techniques-redirect-chain` at the follower step, because the client's own follow is the redirect-carry mechanism.
- Name the class at its own step rather than restating its procedure here.

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

Stop when the value cannot relocate the path or the arrival's answer is discarded, because neither is a traversal finding.

- A value that lands in the query string, where the routing ignores it.
- A client that encodes the value before concatenation, confirmed by an encoded arrival path.
- A traversed path that reaches only static resources with no caller-influenced destination or response.
- An arrival whose response the page never renders, evaluates, or binds.
- A defence layer that normalises the path before the request leaves the client, confirmed across every depth and encoding.
- A redirect follow that lands on the intended endpoint, where the traversal changed nothing.

## Pro Tips

Client-side path traversal rewards depth arithmetic plus a gadget endpoint plus a consumption read.

1. Count the depth before crafting, because the traversal is arithmetic rather than a payload.
2. Confirm the value lands in the path component, since the query string changes nothing.
3. Find the gadget before crafting the traversal, because the arrival's endpoint is half the mechanism.
4. Read the client's encoding and follow behaviour, since both decide whether the traversal survives.
5. Prove the page consumes the arrival's answer, because a discarded response carries nothing.
6. Hand the response to the class that owns its consequence, and stop at the enabling step.

## Summary

A value concatenated into a client-built path walks the request to an endpoint the page never chose, and the client's own follower carries it further. Client-side path traversal counts the depth, reaches a gadget endpoint, and hands the response it controls to the class that owns the consequence.
