---
name: defence-bypass-edge-origin-differential
description: Edge-origin differential bypass where a control is enforced at one tier and the effect served at another, covering route divergence when a legacy or alternate route skips the current chain, verdict reuse when a stored decision is applied to a changed request, and scope divergence when the enforcing tier covers less than the serving tier.
metadata:
  version: 1.0.0
---

# Edge-Origin Differential

A verdict belongs to the tier that gave it, and the effect belongs to the tier that serves it. This variant compares the two tiers for one request: the enforcing layer answers one way and the serving layer delivers another, because a route skips the chain, a stored verdict outlives its request, or the enforcing tier covers less than the serving one. The goal is an effect reached where the verdict was never recomputed.

## Attack Surface

Edge-origin differential applicability centers on a control enforced at one tier of the path while the effect is served at another.
The surface holds edge and gateway tiers that decide before the service, middleware chains beside legacy and versioned routes, shared caches that store a verdict, and core entry points that remain reachable beside the guarded front.
A tier that reuses a stored decision, and a route set where one route carries the current chain and another does not, both widen the surface.
A path where one tier both decides and serves rides outside this variant, because there is no second tier to differ from.

## Reconnaissance

Edge-origin differentials compare tiers before crafting, because the gap is between two verdicts rather than inside one request.
- Map the tiers on the path and record which tier decides, which tier serves, and which tier stores a verdict.
- Enumerate the routes that reach the same effect, and note which of them carry the current chain.
- Establish the refusal baseline at the enforcing tier, so a later pass is attributable to the serving tier.
- Record the lifetime and the key of any stored verdict, because a decision that outlives its request is the differential.
- Compare each route's answer with and without authentication, because the two answers read each tier's scope rather than one tier's rule.

## Detection Channels

Edge-origin differentials listen to two verdicts for one request, so only the entries below are live here.
- The enforcing tier's refusal on the canonical route, which proves the chain evaluated the request.
- A pass on a sibling route for the same effect, which shows the serving tier never consulted the chain.
- The differential between the refused canonical route and the passed sibling route at one effect, which localises the tier gap.
- A stale or cached verdict applied to a changed request, such as a changed method, which proves the decision was not recomputed.
- The effect appearing at the serving tier while the enforcing tier's verdict stayed silent.
- The enforcing tier's own marker absent from a response the serving tier produced, which localises the tier that answered.
- The sink's own error class, which names the tier that answered.

## Adversarial Capabilities

Edge-origin differentials presuppose tier visibility plus route enumeration plus a repeatable baseline, and they consume all three.
- Read the same request at the enforcing tier and at the serving tier, and record both verdicts.
- Enumerate the sibling routes, versions, and entry points that reach one effect.
- Change one property of a request under a stored verdict: the claims, the session, the identity, or the target.
- Reach the core entry directly where the front tier hides it.

## Trust Assumptions

The control trusts that the tier which decides and the tier which serves evaluate the same request under the same rule.
The agreement holds every route to the current chain, holds a stored verdict to the request that produced it, and holds the enforcing tier's scope to the serving tier's effect.
This variant breaks the tier clause because one tier decides while another serves, so the request reaches an effect the deciding tier would have refused.
The pass is claimed only when both verdicts are recorded for one request, because a single verdict cannot show a tier gap.

## Key Vulnerabilities

### Route and Chain Divergence

Reach one effect through a sibling route, a legacy form, or a versioned path that does not carry the current chain, because the route table and the middleware wiring often diverge.
Enumerate the shadow and deprecated route families explicitly: an older version of the same operation, an alternate host family or device subdomain, and a legacy path alias, because the enforcement was wired to the current route only.
Where a rule is scoped to a path, reach the protected path through a spelling the rule does not match while the router still resolves it: case, dot segments, encoded separators, and trailing characters.
Where the enforcing tier skips a request it believes to be internal, the asserting field itself is the route past the chain, so test the claim the field makes rather than the path.
Vary the framing of the same route where the wiring binds a check to one framing only.
A path-override field reaches the route the enforcing tier denied; name `proxy-techniques-relay-forwarding` at that step rather than restating its procedure here.
The parent tier-mapping step covers one route's verdict and cannot describe two routes to one effect, so this variant owns the route-divergence procedure.

### Verdict Reuse Across Requests

Replay a request under a stored verdict with one property changed, because a cached or stale decision is applied to requests it never evaluated.
Change the session, the identity, the target, or the method under an unchanged decision, one property per attempt.
Treat a second property that the stored verdict still admits as the completed probe.

### Scope Divergence Between Tiers

Compare what each tier evaluates: the front tier often covers the address, the method, or the path while the serving tier applies the identity-bound rule.
Where the rule covers one verb, reach the same handler through a sibling verb the rule never evaluated.
Send the same effect through the tier that evaluates less and record which tier answered.
Treat a scope the enforcing tier never read as the bypass, and keep the effect identical across the two attempts.

## Bypass Techniques

Bypass shapes slip past a control that is present at one tier, so each one is tried after the enforcing tier refuses.
- Sibling routes, legacy forms, and versioned paths that skip the current chain.
- Stored verdicts replayed against a changed session, identity, or target.
- Direct core entries where the front tier hides a live route.
- Alternate framings of one route, where the wiring binds the check to one framing.
- Requests shaped to the scope the enforcing tier reads while the serving tier applies the full rule.

## Chaining Attacks

Edge-origin differentials chain forward into the class that owns the effect, because a tier gap is only the first layer.
- Hand the served effect to the class that owns it, and prove the class-specific consequence there.
- Stack with the parser confusion where a sibling route also reads a different member.
- Stack with the cache deception where the same tier also stores a response body rather than a verdict.
- Name the class at its own step rather than restating its procedure here.

## Testing Methodology

Edge-origin differentials read the tiers first and compare second, because the gap lives between two verdicts.

1. **Map the tiers** - every tier on the path with the verdict it holds, and the step completes when each tier is recorded as deciding, serving, or storing.
2. **Baseline the enforcing tier** - send the canonical route and record the chain's answer, and the step completes when a refusal is recorded or the absence of a deciding tier is recorded with the test that showed it.
3. **Enumerate sibling routes** - every route, version, and entry point that reaches the effect, and the step completes when each route carries the chain it passes through.
4. **Probe route divergence** - send the effect through a sibling route and read the answer, and the step completes when the route's verdict names the tier that answered.
5. **Probe verdict reuse** - change one property of a request under a stored verdict, and the step completes when the changed request carries a verdict that matches the stored one.
6. **Compare tier scope** - send the effect through the tier that evaluates less, and the step completes when both tiers' evaluated members are recorded.
7. **Attribute the pass** - pair the refused canonical route with the passed sibling route, and the step completes when the missing chain or stale verdict is named from the pair.

## False Positives

Stop when both tiers gave the same verdict, because an identical verdict is not a differential.

- A sibling route that refuses the effect, confirmed across the route inventory.
- A stored verdict recomputed on the changed request, confirmed by a fresh refusal.
- A pass whose effect never reached the serving tier, where the route passed and the request broke later.
- A second control at the serving tier, which shows a stacked control rather than a tier gap.
- A cached response body rather than a cached verdict, which is the shared-cache step rather than this one.

## Pro Tips

Edge-origin differentials reward tier mapping plus route enumeration.

1. Map which tier decides and which tier serves before crafting, because the mechanism follows the gap.
2. Enumerate sibling routes, since the chain often covers one route and not its siblings.
3. Change one property under a stored verdict so the reuse is attributable.
4. Re-baseline at both tiers after each pass, because a second control often sits at the serving tier.
5. Confirm at the serving tier, because the enforcing tier's silence is not the effect.

## Summary

A control decides at one tier while another tier serves the effect. Edge-origin differentials map the tiers, enumerate the sibling routes, and claim the pass only when both verdicts are recorded for one request.
