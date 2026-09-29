---
name: idor-context-carrier-substitution
description: Substitute identity carriers to expose precedence and audience gaps. Use when a gateway header may override the token, when a token may replay across services, when async processing may drop the caller check.
metadata:
  version: 1.0.0
---

# IDOR Context Carrier Substitution

Carrier substitution testing decides whether the service resolves identity from the caller credential rather than an adversary-shaped channel.
The leading word is substitute: every probe contradicts one identity source with another and reads which source wins.

## Attack Surface

Substitute applies where identity travels beside the object reference through gateway-injected headers, cross-service tokens, tenant selectors acting as identity, or queued async context.
Routing-only tenant selectors that merely scope without identifying stay as aspects in the sibling direct variant, and only selector-as-identity cases live here.
Direct reference swaps with the token held constant stay in the sibling direct variant, and only carrier contradiction lives here.

## Reconnaissance

Map every identity channel the request passes through, from edge headers through service tokens to async consumers.
Record which headers the gateway injects or trusts and which token claims each service validates, using history and gateway topology from the knowledge base.
Collect token pairs scoped for different services wherever overlapping verification is suspected.
Trace one queued or worker-consumed flow end to end before probing, until the re-check point is located or shown absent.

## Detection Channels

A privileged response that follows a contradictory header while the token stays constant signals header precedence failure.
A token scoped for one service that a second service accepts signals missing audience binding.
Divergent results for the same reference under swapped carriers decide the finding without reading further.
An async effect applied to a foreign object after gateway passage signals context loss in the consumer.

## Adversarial Capabilities

This variant presupposes working sessions for at least two principals plus tokens scoped for at least two services where replay is tested.
It consumes the ability to supply headers, selectors, and cross-service tokens that contradict the caller credential.
It consumes the ability to reach services directly behind the gateway as well as through it.
Principal handling follows the procedure owned by `two-principal-authz`, named here rather than restated.

## Trust Assumptions

The feature executes under the agreement that an object reference arriving with a request is private to the caller, that any surrounding authorization already binds the referenced object to that caller, that identity arriving through surrounding channels belongs to the same caller, that a token accepted by one service transfers only to its intended audience, and that a check performed at creation still holds at retrieval, so no caller reaches data beyond its own scope.
The agreement fails when the service resolves identity from a surrounding channel that an adversary controls instead of the caller credential.

## Key Vulnerabilities

Identity-source precedence probing with audience binding checks is the bent step this variant owns over the parent.
Supply gateway-trusted headers that contradict token claims, varying presence, removal, and override independently, and record which source the service treats as the actor.
Replay a token scoped for one service against a second service sharing verification, and test whether audience and claims checks reject it.
Resubmit an authorized request through the queue or worker path and verify whether the consumer re-checks authorization before applying the effect.

## Bypass Techniques

Coerce method and content-type framings while holding the contradictory carrier constant, since per-stack middleware often resolves identity differently.
Pollute duplicate carrier fields with both orderings to probe which occurrence wins at each layer.
Treat cache-key confusion across tenant headers as defeat detail shared with the bypass family, recording only the identity verdict here.

## Chaining Attacks

Pivot a confirmed carrier override into direct swaps that now execute under the impersonated identity.
Pivot a confirmed cross-service replay into the second service's privileged objects and actions.
Pivot a confirmed async gap into queued state changes the gateway would have rejected live, keeping each step's verdict separate.

## Testing Methodology

1. Derive the request shape from evidence by collecting gateway topology, token scopes, and history material, with completion when identity channels and carrier fields are inferable.
2. Build the subject-carrier-action matrix by enumerating each role against each identity source and action, with completion when every header, token, selector, and async path has an expected-identity cell.
3. Establish principals by acquiring one working session per matrix role plus cross-service tokens where applicable, with completion when each credential issues an authenticated baseline (procedure owned by `two-principal-authz`).
4. Contradict sources by supplying carriers that disagree with the caller credential, with completion when every identity source has a conflicting attempt beside its consistent control.
5. Replay across services by submitting each token to every service sharing verification, with completion when every token-service pair carries an audience verdict.
6. Exercise async paths by resubmitting authorized requests through queues and workers, with completion when each consumer path has a re-check verdict.
7. Retry failures with the inferred verb and fields before judging, with completion when no probe is judged on a wrong-verb or placeholder-carrier attempt.

## False Positives

Discard headers the gateway strips or overwrites before the service reads them, verifying authoritative behavior rather than echo.
Discard tokens the second service rejects on audience or claims, confirming rejection symmetrically for every caller.
Discard tenant selectors that only route within one identity, confirming they never switch the actor.
Discard async consumers that demonstrably re-check authorization before applying effects, verifying the re-check rather than assuming the gap.

## Pro Tips

Vary one carrier at a time against a fixed credential, since simultaneous changes hide which source won.
Test header removal as well as override, since absent-carrier fallbacks carry their own precedence bugs.
Collect token pairs across every service sharing verification, since audience gaps hide at the second service.
Trace async consumers to their effect point, since gateway passage never implies consumer enforcement.
Name token and flow steps owned by `authentication-jwt` and `oauth` rather than restating them.

## Summary

Identity resolution must anchor on the caller credential and reject every contradictory channel.
Contradict each source in turn, and file every response that obeys the adversary channel.
