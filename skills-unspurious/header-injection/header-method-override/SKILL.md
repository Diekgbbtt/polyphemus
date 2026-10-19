---
name: header-method-override
description: Overriding routed method or rewritten path past authorization checks, pairing method-override headers with rewrite headers, and proving the reroute lands before the auth check.
metadata:
  version: 1.0.0
---

# Method Override and Rewrite Bypass

Routers that consult override and rewrite headers before the authorization layer let a header choose the handler.
This variant proves that override plus rewrite headers reroute the method or the path before the authorization check runs.
The overriding goal is a guarded handler reached through a safe-looking request, which later enables state-changing abuse plus guarded-path disclosure.

## Attack Surface

Applicability centers on a backend that routes on method-override headers plus path-rewrite headers ahead of authorization.
State-changing handlers sit behind method-based gating, and guarded paths sit behind path-based gating, while the router honors header-supplied method or address values first.
This variant solely owns the rewrite-header family, so no sibling claims path rewriting after the check.
Forwarding-alias trust for allowlist or scheme decisions belongs to header-host-forward-spoof, and framed-body smuggling belongs to header-request-smuggling.

## Reconnaissance

Inventory narrows to method-gated handlers plus rewrite-aware routers.
List state-changing endpoints reachable by safe methods and record which unsafe methods the gate refuses directly.
Probe override-header support with abstract alias shapes, namely the primary override form plus its common alias forms, and probe rewrite-header support with the original-address form plus the rewrite-address form.
Determine routing-versus-authorization order by pairing each header with a guarded endpoint and recording whether the reroute or the refusal wins.

## Detection Channels

Overriding listens for order-of-check wins, so only the entries below are live here.
- Guarded handler reached through a safe method plus an override header while the direct unsafe method stays refused binds the probe to the ordering flaw.
- Guarded path served through a rewrite header while the direct guarded request stays refused binds the probe to rewrite-after-check behavior.
- Routing-versus-refusal record per header-plus-endpoint pair isolates the trusting router from ambient method support.
- Response-behavior diff between the override replay and the clean safe-method replay separates rerouted handling from ordinary handling.

## Adversarial Capabilities

Overriding presupposes header-supplied routing control plus guarded-endpoint reachability, and it consumes both.
- Send override plus rewrite headers from a caller that issues plain requests without browser preflight behavior.
- Reach state-changing handlers through safe methods paired with one routing header at a time.
- Hold a clean baseline per endpoint, namely the direct safe-method response plus the direct unsafe-method refusal, for diffing.
- Pair each routing header with each guarded endpoint until the order record is exhaustive.

## Trust Assumptions

The stack treats an attacker-influenced value that reaches a response header field as inert data at the moment the feature executes.
The agreement holds the value free of framing meaning from capture through serialization, holds one declared interpreter for the value across the proxy-to-backend-to-client path, keeps the request in its declared method plus path plus protocol shape, keeps each response observable only to its caller, and keeps link targets plus cached bodies plus session state plus token-bearing destinations out of attacker reach.
This variant breaks the routing-order clause because override plus rewrite headers reroute the method or the path before the authorization check.

## Key Vulnerabilities

### Method Override Past Method-Based Authorization

Pair a safe-method request with an override header naming a state-changing method, and confirm the guarded handler executes while the direct unsafe method stays refused.
The parent override step names only header pairing, so this variant owns the order proof that turns supported overriding into a pre-check reroute.
Treat consistently ordered enforcement as the boundary, because overriding resolved after the check is intended flexibility rather than bypass.

### Rewrite-Header Path Change After The Check

Pair a public-path request with a rewrite header naming a guarded path, and confirm the guarded content serves while the direct guarded request stays refused.
This variant solely owns rewrite-after-auth proof on rewrite-capable stacks, where the address check runs against the original path and the handler runs against the rewritten one.
Name alias-spoof decision flips at this step rather than restating them, since header-host-forward-spoof owns forwarding-alias mapping without path rewriting.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no spelling changes the order-of-check oracle itself.
- Rotate through override-alias forms where the filter blocks only the primary spelling while the router honors an alias.
- Mangle header casing plus surrounding whitespace where the filter keys off exact spelling.
- Duplicate the routing header so the enforcing side reads one member while the router reads the other.
- Layer encoded-path forms inside the rewrite value past a filter that decodes fewer times than the router.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Overriding chains forward through the reached handler because a reroute without a follow-up action is only access.
- Hand an reached state-changing handler to state abuse such as privileged mutation or configuration change.
- Hand a disclosed guarded path to further primitive hunting inside the newly visible surface.
- Hand a bypassed method gate to workflow-order abuse where the skipped check guarded a multi-step sequence.

## Testing Methodology

Overriding runs baselines before pairing and order proof last, because unsupported headers plus refused handlers explain most deltas.
1. **Inventory gated handlers** - list every method-gated plus path-gated endpoint with its direct refusal behavior, and the step completes when no gated endpoint lacks a recorded baseline.
2. **Probe routing-header support** - replay each override plus rewrite shape against a neutral endpoint, and the step completes when every shape carries a honored-or-ignored verdict.
3. **Pair against guarded endpoints** - combine each honored shape with each gated endpoint one pair at a time, and the step completes when every pair carries a rerouted-or-refused verdict with its samples.
4. **Prove pre-check order** - diff the pair response against both baselines, and the step completes when each reroute shows handler execution past the check or is ruled out with its evidence.
5. **Exclude sibling ownership** - confirm no finding depends on framing pairs or alias allowlists, and the step completes when every such result is handed to its owning sibling with its evidence.

## False Positives

Stop when the evidence shows the router honors the header only after or without weakening the check, because ordered flexibility is only noise.
- Authorization re-evaluated after override resolution, confirmed by uniform refusals across all honored shapes.
- Rewrite values validated against an allowlist before routing, confirmed by public-path-only serving across all rewrite shapes.
- Override headers reflected into responses but never consulted by the router, confirmed by identical handling with and without the header.
- Delivery-context limits, namely constrained callers that cannot send the header shape the router honors, confirmed by caller-class diffing.

## Pro Tips

Overriding rewards order proof over header support, because supported headers without pre-check routing are only features.
1. Prefer the safe-method plus override pair first, since it costs one request per endpoint and reads directly from the diff.
2. Favor one routing header per probe so each reroute attributes to exactly one shape.
3. Record both baselines before pairing, because a missing refusal baseline voids the order claim.
4. Treat rewrite-capable stacks as the highest-yield rewrite targets and map them before sweeping aliases.
5. Hand any allowlist or scheme delta to the spoofing sibling immediately rather than stretching this oracle to fit it.

## Summary

A router that honors override and rewrite headers before the authorization layer hands handler choice to whoever sends a header.
Overriding inventories gated handlers, pairs each routing shape, and proves the reroute executes past the check before any state-abuse or disclosure chain begins.
