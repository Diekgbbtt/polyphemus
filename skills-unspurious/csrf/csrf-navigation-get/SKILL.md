---
name: csrf-navigation-get
description: Chain top-level cross-site GET navigations that trigger state changes, confirm Lax-scoped confirmation steps when cookie scope permits GET, and exploit staff GET tools when back-office endpoints mutate.
metadata:
  version: 1.0.0
---

# CSRF Navigation Get

State-changing endpoints reachable by top-level navigation execute when the browser attaches cookies to a cross-site GET.
This variant chains top-level GET navigations through confirmation steps and staff tool contexts and confirms the state effect.
The confirmation goal is navigation-triggered semantics under the victim session that later enables authorization or workflow chaining.

## Attack Surface

Applicability centers on a state-changing endpoint that accepts a top-level cross-site GET without a non-replayable proof of intent.
The endpoint carries cookie-based ambient authority with a sending scope that permits at least one top-level navigation case.
The request shape stays a navigation-triggered GET emitted from an attacker page, including single links plus chained confirmation steps plus encoded query payloads.
Simple POST replay plus semantic reconstruction plus socket transports ride outside this variant in their sibling variants.
Staff and back-office tool endpoints belong here when they expose state-changing GETs intended for internal use.

## Reconnaissance

### Session Scope and GET Reachability

- Record cookie sending scope plus the top-level navigation exception per endpoint.
- Record which state changes respond to GET plus which confirmation steps precede them.
- Record staff plus back-office GET tools separately, because their context changes the chaining shape.

### Defense Presence

- Locate proof-of-intent checks such as per-request tokens plus origin or referrer enforcement on GET paths.
- Record confirmation-step presence plus token carriage on each step of a chain.
- Record redirect-chained authorization entries plus encoded query mutations for the chained-payload sub-step.

## Detection Channels

Navigation triggers through links rather than forms, so only the entries below are live here.
- Before-versus-after state comparison showing the intended effect after a top-level navigation without a proof of intent.
- Confirmation-chain completion showing each chained GET step executed in order.
- Sending-scope observation showing the cookie travels on the top-level navigation case.
- Redirect-chain signal showing an authorization entry completed through navigation plus redirect following.
- Null-origin acceptance showing the navigation-triggered change proceeds from an empty-context source.

## Adversarial Capabilities

Chaining presupposes lure plus navigation construction plus chain comparison, and it consumes all three.
- Lure the victim to an attacker-controlled cross-origin page with no script execution in the target origin.
- Construct top-level navigation triggers such as links plus redirects that the victim visit activates.
- Chain two or more GETs through confirmation steps where the flow requires sequential visits.
- Encode query payloads that carry mutation semantics inside the navigation target.
- Operate the defeat sub-step by removing tokens and by presenting empty-context navigations.

## Trust Assumptions

The state-changing feature trusts a cookie-authenticated cross-origin request to carry genuine user intent.
The agreement holds the session cookie stable as ambient authority, holds the endpoint in its intended state-change shape, holds the request in its declared method plus encoding shape, holds a non-replayable proof of intent enforced, and holds the transport in single-request HTTP shape with victim-session direction.
Sensitive account plus storage plus action state changes only through intended effects under the victim session.
This variant breaks the navigation-safety clause because the endpoint accepts state change over top-level GET that a cross-origin link can trigger, so intent is decided by visit plus cookie presence alone.

## Key Vulnerabilities

### Chained Confirmation Navigation

Chain two or more top-level GETs through the confirmation sequence the application expects, because single-link delivery stops at the first confirmation.
Record completion per step rather than per chain, because a partial chain cannot confirm the full effect.
The parent navigation step covers only single top-level GET and cannot describe confirmation-step chaining, so this variant owns the chain-two-GETs procedure.

### Staff GET Tool Exploitation

Deliver navigation triggers against staff plus back-office GET tools that mutate state without token checks.
Confirm the effect in the back-office context rather than in the victim-visible view, because the mutation lands off the main application surface.
The parent navigation step never names back-office context, so this variant owns the staff-context confirmation procedure.

### Encoded and Redirect-Chained Payloads

Encode mutation semantics inside the navigation target where the server accepts query-carried operations, including persisted-operation shapes.
Chain authorization flow entries through redirect following where the entry accepts navigation triggering.
These shapes stay aspects inside this variant because the navigation action covers them with a chained-payload parameter and no new transport is needed.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no value difference changes the navigation-chaining step itself.
- Token absence plus cross-request reuse plus query-carried tokens steer the chained navigation past a weak proof-of-intent check.
- Null plus missing plus cross-origin header values steer the navigation past a weak origin or referrer check.
- Sending-scope reliance steers top-level GETs through the permitted navigation case while direct cross-site sub-requests stay blocked.
- Referrer stripping through an empty-context navigation source presents the chain without its origin context.

## Chaining Attacks

Navigation chains forward into authorization and session abuse because a bare GET effect without a follow-up goal is only a probe.
- Force actions on other users records once reference values are known through the authorization sibling.
- Guide confirmation-step clicks through visual overlay chaining where a confirmation resists plain navigation.
- Chain forced authorization navigations that bind victim sessions to unintended clients.
- Treat a successful staff-tool navigation as the entry into privilege or workflow chaining.

## Testing Methodology

Navigation runs inventory first and chaining second, because no chain is meaningful without a GET-reachability map.
1. **Inventory endpoints** - list every GET-reachable state change including confirmation steps plus staff plus back-office tools, and the step completes when no unlisted GET-reachable state change remains.
2. **Map navigation reachability** - record top-level navigation triggering plus sending-scope behavior per endpoint, and the step completes when every endpoint carries a reachable or refused verdict per navigation case.
3. **Assess session and defenses** - record cookie sending scope plus token presence plus origin or referrer enforcement per GET path, and the step completes when every GET path carries a complete defense record.
4. **Chain confirmation navigations** - deliver ordered top-level GETs through each confirmation sequence, and the step completes when every chain shows a per-step execution record.
5. **Exploit staff GET context** - deliver navigation triggers against staff plus back-office tools and confirm in that context, and the step completes when every staff target shows a recorded state-effect verdict.
6. **Confirm defeat value** - repeat successes with removed plus reused tokens and with empty-context navigations, and the step completes when every success carries its defeating value record.

## False Positives

Stop when the evidence shows the navigation never executes as a state change, because link reachability without effect is only noise.
- Enforced per-request token plus consistent origin or referrer checks on GET paths confirmed by uniform refusals.
- No cookie travels on the navigation case, confirmed by absent session authority in the delivered GET.
- Only idempotent or non-sensitive operations respond, with no confirmation chain completing to an effect.
- Uniform negatives across every navigation case, which signal genuine enforcement rather than a missed chain.
- State comparison showing no before-versus-after difference after every chained navigation.

## Pro Tips

Navigation rewards chain patience plus scope awareness plus context-exact confirmation.
1. Prefer the single-link probe first, then promote only guarded flows to chained confirmation delivery.
2. Favor per-step recording so partial chains stay diagnosable rather than collapsing to a single verdict.
3. Probe staff plus back-office GET tools early, because token checks are thinnest there.
4. Confirm every success through before-versus-after state in the affected context rather than through response text.
5. Record the sending-scope case plus the defeating value per success so the finding reproduces exactly.

## Summary

An endpoint that mutates on top-level GET under cookie authority alone executes on visit plus confirmation chaining.
Ordered navigation plus staff-context confirmation proves the effect before any authorization or workflow chaining follows.
