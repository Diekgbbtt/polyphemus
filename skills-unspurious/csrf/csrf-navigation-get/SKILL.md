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

- **Applicability**: centers on a state-changing endpoint that accepts a top-level cross-site GET without a non-replayable proof of intent.
- **Ambient authority**: the endpoint carries cookie-based ambient authority with a sending scope that permits at least one top-level navigation case.
- **Request shape**: a navigation-triggered GET emitted from an attacker page, including single links plus chained confirmation steps plus encoded query payloads.
- **Out-of-scope transports**: simple POST replay plus semantic reconstruction plus socket transports ride outside this variant in their sibling variants.
- **Staff tool endpoints**: belong here when they expose state-changing GETs intended for internal use.

## Reconnaissance

### Session Scope and GET Reachability

- **Sending-scope recording**: record cookie sending scope plus the top-level navigation exception per endpoint.
- **GET state-change recording**: record which state changes respond to GET plus which confirmation steps precede them.
- **Staff-tool recording**: record staff plus back-office GET tools separately, because their context changes the chaining shape.

### Defense Presence

- **Proof-of-intent checks**: locate proof-of-intent checks such as per-request tokens plus origin or referrer enforcement on GET paths.
- **Confirmation-step recording**: record confirmation-step presence plus token carriage on each step of a chain.
- **Redirect-chain recording**: record redirect-chained authorization entries plus encoded query mutations for the chained-payload sub-step.

## Detection Channels

- **Live channels**: navigation triggers through links rather than forms.
- **Before-versus-after state comparison**: showing the intended effect after a top-level navigation without a proof of intent.
- **Confirmation-chain completion**: showing each chained GET step executed in order.
- **Sending-scope observation**: showing the cookie travels on the top-level navigation case.
- **Redirect-chain signal**: showing an authorization entry completed through navigation plus redirect following.
- **Null-origin acceptance**: showing the navigation-triggered change proceeds from an empty-context source.

## Adversarial Capabilities

- **Chaining prerequisites**: lure plus navigation construction plus chain comparison, which the variant consumes.
- **Victim lure**: lure the victim to an attacker-controlled cross-origin page with no script execution in the target origin.
- **Navigation construction**: construct top-level navigation triggers such as links plus redirects that the victim visit activates.
- **Confirmation chaining**: chain two or more GETs through confirmation steps where the flow requires sequential visits.
- **Query-payload encoding**: encode query payloads that carry mutation semantics inside the navigation target.
- **Defeat operation**: operate the defeat sub-step by removing tokens and by presenting empty-context navigations.

## Trust Assumptions

- **The agreement**: the state-changing feature trusts a cookie-authenticated cross-origin request to carry genuine user intent, holds the session cookie stable as ambient authority, holds the endpoint in its intended state-change shape, holds the request in its declared method plus encoding shape, holds a non-replayable proof of intent enforced, holds the transport in single-request HTTP shape with victim-session direction, and changes sensitive account plus storage plus action state only through intended effects under the victim session.
- **The failing clause**: this variant breaks the navigation-safety clause because the endpoint accepts state change over top-level GET that a cross-origin link can trigger, so intent is decided by visit plus cookie presence alone.

## Key Vulnerabilities

### Chained Confirmation Navigation

- **Chained confirmation navigation**: chain two or more top-level GETs through the confirmation sequence the application expects, because single-link delivery stops at the first confirmation.
- **Per-step completion**: record completion per step rather than per chain, because a partial chain cannot confirm the full effect.
- **Chain-two-GETs ownership**: the parent navigation step covers only single top-level GET and cannot describe confirmation-step chaining, so this variant owns the chain-two-GETs procedure.

### Staff GET Tool Exploitation

- **Staff-tool triggering**: deliver navigation triggers against staff plus back-office GET tools that mutate state without token checks.
- **Back-office confirmation**: confirm the effect in the back-office context rather than in the victim-visible view, because the mutation lands off the main application surface.
- **Staff-context ownership**: the parent navigation step never names back-office context, so this variant owns the staff-context confirmation procedure.

### Encoded and Redirect-Chained Payloads

- **Encoded payloads**: encode mutation semantics inside the navigation target where the server accepts query-carried operations, including persisted-operation shapes.
- **Redirect-chained payloads**: chain authorization flow entries through redirect following where the entry accepts navigation triggering.
- **Aspect containment**: these shapes stay aspects inside this variant because the navigation action covers them with a chained-payload parameter and no new transport is needed.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no value difference changes the navigation-chaining step itself.
- **Token-gap steering**: token absence plus cross-request reuse plus query-carried tokens steer the chained navigation past a weak proof-of-intent check.
- **Header-value steering**: null plus missing plus cross-origin header values steer the navigation past a weak origin or referrer check.
- **Sending-scope steering**: sending-scope reliance steers top-level GETs through the permitted navigation case while direct cross-site sub-requests stay blocked.
- **Cookie-refresh grace window**: a cookie-refresh grace window re-admits a top-level navigation after a fresh cookie is issued, so the scoping clause weakens at refresh time.
- **Referrer stripping**: referrer stripping through an empty-context navigation source presents the chain without its origin context.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Forward chaining scope**: navigation chains forward into authorization and session abuse because a bare GET effect without a follow-up goal is only a probe.
- **Authorization-sibling chaining**: force actions on other users records once reference values are known through the authorization sibling.
- **Visual-overlay chaining**: guide confirmation-step clicks through visual overlay chaining where a confirmation resists plain navigation.
- **Forced-authorization chaining**: chain forced authorization navigations that bind victim sessions to unintended clients.
- **Staff-tool entry**: treat a successful staff-tool navigation as the entry into privilege or workflow chaining.

## Testing Methodology

Navigation runs inventory first and chaining second, because no chain is meaningful without a GET-reachability map.
1. **Inventory endpoints** - list every GET-reachable state change including confirmation steps plus staff plus back-office tools, and the step completes when no unlisted GET-reachable state change remains.
2. **Map navigation reachability** - record top-level navigation triggering plus sending-scope behavior per endpoint, and the step completes when every endpoint carries a reachable or refused verdict per navigation case.
3. **Assess session and defenses** - record cookie sending scope plus token presence plus origin or referrer enforcement per GET path, and the step completes when every GET path carries a complete defense record.
4. **Chain confirmation navigations** - deliver ordered top-level GETs through each confirmation sequence, and the step completes when every chain shows a per-step execution record.
5. **Exploit staff GET context** - deliver navigation triggers against staff plus back-office tools and confirm in that context, and the step completes when every staff target shows a recorded state-effect verdict.
6. **Confirm defeat value** - repeat successes with removed plus reused tokens and with empty-context navigations, and the step completes when every success carries its defeating value record.

## False Positives

- **Stop condition**: stop when the evidence shows the navigation never executes as a state change, because link reachability without effect is only noise.
- **Enforced defenses**: enforced per-request token plus consistent origin or referrer checks on GET paths confirmed by uniform refusals.
- **Absent session authority**: no cookie travels on the navigation case, confirmed by absent session authority in the delivered GET.
- **Idempotent-only responses**: only idempotent or non-sensitive operations respond, with no confirmation chain completing to an effect.
- **Uniform navigation negatives**: uniform negatives across every navigation case, which signal genuine enforcement rather than a missed chain.
- **No state difference**: state comparison showing no before-versus-after difference after every chained navigation.

## Pro Tips

- **Navigation discipline**: navigation rewards chain patience plus scope awareness plus context-exact confirmation.
- **Single-link probe first**: prefer the single-link probe first, then promote only guarded flows to chained confirmation delivery.
- **Per-step recording**: favor per-step recording so partial chains stay diagnosable rather than collapsing to a single verdict.
- **Thin-check targets**: probe staff plus back-office GET tools early, because token checks are thinnest there.
- **Context-exact confirmation**: confirm every success through before-versus-after state in the affected context rather than through response text.
- **Reproduction record**: record the sending-scope case plus the defeating value per success so the finding reproduces exactly.

## Summary

An endpoint that mutates on top-level GET under cookie authority alone executes on visit plus confirmation chaining.
Ordered navigation plus staff-context confirmation proves the effect before any authorization or workflow chaining follows.
