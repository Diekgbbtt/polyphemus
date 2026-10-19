---
name: csrf-parser-differential
description: Reconstruct rich request semantics inside preflightless encodings that coerce to structured bodies, confirm server-side coercion when nested shapes parse, and smuggle method overrides when override markers execute.
metadata:
  version: 1.0.0
---

# CSRF Parser Differential

Endpoints that coerce simple cross-origin bytes into structured semantics execute transformed input as the intended action.
This variant reconstructs target semantics inside a preflightless encoding and confirms server-side coercion applied.
The confirmation goal is transformed semantics under the victim session that later enables authorization or workflow chaining.

## Attack Surface

Applicability centers on a state-changing endpoint whose parser auto-coerces a simple cross-origin body into richer structured semantics.
The endpoint carries cookie-based ambient authority with a session that travels on cross-site requests.
The request shape stays a preflightless POST whose body carries reconstructed semantics, including nested-key shapes plus repeated-key shapes plus collection shapes plus override markers.
Identical replay plus navigation triggering plus socket transports ride outside this variant in their sibling variants.
Backends that honor override markers belong here when a simple POST can smuggle a destructive method through the marker.

## Reconnaissance

### Parser and Override Reachability

- Record parser coercion behavior per endpoint, noting which simple encoding coerces into structured semantics.
- Record nested-key plus repeated-key plus collection-shape handling per endpoint.
- Record override-marker support per endpoint, noting which marker promotes a simple POST to a stronger method.

### Defense Presence

- Locate proof-of-intent checks such as per-request tokens plus origin or referrer enforcement on coerced paths.
- Record token lifecycle behavior including removal plus reuse plus scope binding for the defeat sub-step.
- Record null plus missing plus cross-origin header acceptance for the defeat sub-step.

## Detection Channels

Transformation succeeds only when the server coerces, so only the entries below are live here.
- Before-versus-after state comparison showing the structured effect without a proof of intent.
- Coercion-applied signal showing the preflightless body executed with structured semantics.
- Repeated-key plus collection-shape confusion signal showing the parser resolved the ambiguous shape into an action.
- Override-acceptance signal showing the simple POST executed as the stronger method.
- Missing-token acceptance showing the coerced change proceeds without the expected token.

## Adversarial Capabilities

Reconstruction presupposes lure plus shape construction plus coercion comparison, and it consumes all three.
- Lure the victim to an attacker-controlled cross-origin page with no script execution in the target origin.
- Construct preflightless bodies that encode nested-key plus repeated-key plus collection shapes through placeholders.
- Embed override markers that promote the simple POST where the backend honors them.
- Compare before-versus-after application state to confirm the server applied the coerced semantics.
- Operate the defeat sub-step by removing or reusing tokens and by presenting empty-context origins.

## Trust Assumptions

The state-changing feature trusts a cookie-authenticated cross-origin request to carry genuine user intent.
The agreement holds the session cookie stable as ambient authority, holds the endpoint in its intended state-change shape, holds the request in its declared method plus encoding shape, holds a non-replayable proof of intent enforced, and holds the transport in single-request HTTP shape with victim-session direction.
Sensitive account plus storage plus action state changes only through intended effects under the victim session.
This variant breaks the declared-encoding clause because the server coerces a preflightless body into richer semantics plus honors override markers, so transformed bytes still execute as the intended action.

## Key Vulnerabilities

### Semantic Reconstruction Delivery

Rebuild the intended structured keys through simple-encoding fields using nested-key plus repeated-key plus collection shapes.
Confirm coercion through the resulting state effect rather than through echoed input, because echo without execution proves only parsing.
The parent delivery step covers only preflightless byte delivery and cannot describe transform-then-confirm-coercion, so this variant owns the reconstruction procedure.

### Override Smuggling Delivery

Smuggle a stronger method through an override marker carried inside a simple POST where the backend honors such markers.
Confirm the smuggled method through its distinctive effect rather than through the outer POST status, because the outer status can mask the inner promotion.
The parent delivery step never names marker-driven promotion, so this variant owns the smuggle-then-confirm-method procedure.

### Encoding-Switch Confusion

Switch across simple encoding families to reach the code path whose parser coerces most leniently.
Treat each family as a distinct coercion probe rather than a retry of the same replay, because coercion rules diverge per family.
This switching stays inside this variant because the bent step is the coercion confirmation itself, not the family choice.

## Bypass Techniques

Bypass forms stay aspects inside this variant because no value difference changes the reconstruction step itself.
- Token absence plus cross-request reuse plus cross-session reuse plus untied scope steer the reconstructed body past a weak proof-of-intent check.
- Null plus missing plus cross-origin header values steer the reconstructed body past a weak origin or referrer check.
- Duplicate-key plus collection-shape ambiguity steers the body through a lenient parser branch.
- A path-scope mismatch steers the token check: the token scope is matched on the pre-normalisation path while execution uses the post-normalisation path.
- Referrer stripping through an empty-context navigation source presents the reconstruction without its origin context.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

Reconstruction chains forward into authorization and workflow abuse because a coerced effect without a follow-up goal is only a probe.
- Force actions on other users records once reference values are known through the authorization sibling.
- Guide confirmation-step clicks through visual overlay chaining where a confirmation blocks the reconstructed delivery.
- Chain forced authorization navigations where an authorization flow entry accepts the same coerced shape.
- Treat a successful override smuggle as the entry into method-gated privilege chaining.

## Testing Methodology

Reconstruction runs inventory first and transform-then-confirm second, because no transform is meaningful without a coercion map.
1. **Inventory endpoints** - list every structured-semantics endpoint including override-honoring backends with its parser behavior, and the step completes when no unlisted coercion-capable endpoint remains.
2. **Map coercion acceptance** - record which simple encoding coerces into structured semantics per endpoint, and the step completes when every endpoint carries a coercing or non-coercing verdict per family.
3. **Assess session and defenses** - record cookie sending scope plus token presence plus origin or referrer enforcement per coerced path, and the step completes when every coerced path carries a complete defense record.
4. **Reconstruct semantics** - deliver nested-key plus repeated-key plus collection shapes inside preflightless bodies, and the step completes when every reconstruction shows a recorded coercion verdict.
5. **Smuggle override markers** - deliver simple POSTs carrying override markers where supported and confirm the promoted method effect, and the step completes when every marker attempt shows a promoted or refused verdict.
6. **Confirm defeat value** - repeat successes with removed plus reused tokens and with empty-context origins, and the step completes when every success carries its defeating value record.

## False Positives

Stop when the evidence shows the transformed body never executes as structured semantics, because parse without effect is only noise.
- Enforced per-request token plus consistent origin or referrer checks on coerced paths confirmed by uniform refusals.
- No coercion occurs, confirmed by the server treating the preflightless body as flat or rejecting it.
- Override markers ignored, confirmed by uniform outer-method behavior with no promoted effect.
- Only idempotent or non-sensitive operations respond, with no structured effect.
- State comparison showing no before-versus-after difference after every reconstructed delivery.

## Pro Tips

Reconstruction rewards shape patience plus family switching plus effect-exact confirmation.
1. Prefer the smallest nested-key probe first, then promote only coercing endpoints to repeated-key plus collection shapes.
2. Favor one shape per attempt so coercion attribution stays exact per endpoint.
3. Attempt override markers early on backends that advertise method flexibility, because promotion checks are thinnest there.
4. Confirm every success through before-versus-after state rather than through echoed input.
5. Record the coercing family plus the defeating value per success so the finding reproduces exactly.

## Summary

A parser that coerces simple cross-origin bytes into structured semantics plus honors override markers executes transformed input.
Reconstruction plus coercion confirmation proves the effect before any authorization or workflow chaining follows.
