---
name: defence-bypass-allowance-gap
description: Allowance gap bypass where a permit enumerates what may happen, covering policy gaps when a directive or source list leaves a route to execution, sanitiser enumeration gaps when allowed elements or attributes combine into the effect, secret permit values when the key the policy relies on can be read or reused, and confinement gaps when a declared restriction has an unlisted route to the same capability.
metadata:
  version: 1.0.0
---

# Allowance Gap

A permit that enumerates what may happen is defeated by every route to the capability it omits. This variant reads the permit as an enumeration rather than a rule, then reaches the effect through a route the enumeration does not cover: an allowance the policy left open, an allowed element that combines into the withheld effect, or a substitute primitive with the same reach. The goal is a permitted request that performs what the permit meant to prevent.

## Attack Surface

- **Applicability**: centers on a permit that lists what may execute, what may be read across origins, or which primitives remain available inside a restriction.
- **Surface composition**: policy directive and source lists, sanitiser element and attribute allowlists, confinement claims that disable a primitive, allowlisted operator or name subsets, and delegate or converter policies.
- **Widening factors**: a permit whose list is broader than the author intended, and a restriction whose enforcement is narrower than its declaration, both widen the surface.
- **Confinement**: the capability is often browser-confined and gated by a declarative permit, so the surface holds a policy the browser itself enforces rather than a server-side check.
- **Out-of-scope variant**: a permit that enumerates nothing rides outside this variant, because there is no enumeration to exceed.

## Reconnaissance

- **Reconnaissance scope**: allowance gaps are read from the permit itself, because the gap is an omission rather than a malformed request.
- **Permit text**: read the permit's own text: which directives are present, which sources or elements they allow, and which are missing.
- **Route enumeration**: record the capability the permit withholds and enumerate every route to that capability that the permit's list does not name.
- **Refusal baseline**: establish the refusal baseline with a request the permit plainly forbids, so a later pass is attributable to the omission.
- **Enforcement boundary**: probe the enforcement boundary separately from the declaration, because a claim of restriction is not evidence of restriction.

## Detection Channels

- **Channel scope**: allowance gaps listen to the permit's enumeration rather than to a value comparison, so only the entries below are live here.
- **Permit refusal**: the permit's refusal on a plainly forbidden request, which proves the restriction is enforced.
- **Unlisted pass**: a permitted request that reaches the withheld capability, which shows the enumeration was incomplete.
- **Route differential**: the differential between the refused forbidden route and the permitted unlisted route, which localises the omission.
- **Allowed-route effect**: the effect appearing at the sink through an allowed element, source, or substitute primitive.
- **Sink error class**: the sink's own error class or output, which names the route that delivered the effect.

## Adversarial Capabilities

- **Prerequisites**: allowance gaps presuppose the permit's text plus a route inventory plus a repeatable baseline, and they consume all three.
- **Permit reading**: read the permit and enumerate the routes its list omits before sending anything.
- **Paired answers**: send a forbidden route and an unlisted route to the same effect, and read both answers.
- **Combination**: combine allowed elements, sources, or primitives into the withheld effect.
- **Substitute primitive**: hold a substitute primitive with the same reach where the named one is genuinely restricted.

## Trust Assumptions

- **The agreement**: the permit trusts that its enumeration covers every route to the capability it withholds, holds the directive list to every source that can deliver the effect, holds the element and attribute list to every combination that reaches it, holds the confinement claim to the primitives actually removed, and holds the allowlisted subset to every operation it must not reach.
- **The failing clause**: this variant breaks the enumeration clause because a route outside the list reaches the same capability, so the permit reports a permitted request while the withheld effect occurs.
- **Claim discipline**: the pass is claimed only against the recorded refusal of the forbidden route, because an unrestricted permit proves nothing about its list.

## Key Vulnerabilities

### Policy Allowance Gaps

- **Directive and source lists**: read the policy's directive and source lists for the route they leave open: a permissive directive, a wildcard source, a missing restriction, or an allowed dynamic construct that reaches execution.
- **Allowed primitives**: enumerate the allowed primitives that combine into the withheld capability: an allowed data endpoint that returns an executable response, an allowed callback name the page invokes, an allowed element that a helper turns into execution, and an allowed indirection to a denied attribute.
- **Origin-list pattern**: where the permit is an origin list, test the list's pattern rather than its intent: a missing separator, a missing end anchor, an unescaped dot, a prefix-only match, and the browser's own character handling are routes the list does not cover.
- **Path-list spelling**: where the permit is a path list, test the path's spelling rather than its text: case, dot segments, encoded separators, parameter separators, and trailing characters all reach the protected path through a form the rule does not match.
- **Admitted route**: prefer the route the policy itself admits, because it needs no second bypass behind it.
- **Ownership**: the parent mechanism-selection step covers one control kind and cannot describe a capability reached through the permit's own allowance, so this variant owns the enumeration procedure.
- **Permit enumeration matrix**: see `references/permit-enumeration-matrix.md` for the route inventory across permit kinds.
- **Permit references**: see `references/cors-misconfiguration.md` for the cross-origin read permit and `references/csp-bypass.md` for the browser-confined script permit.

### Secret Permit Values

- **Secret reliance**: some permits rely on a value meant to stay secret: a per-response key, a hash of the permitted content, or a token bound to the page.
- **Unwatched channel**: leak the value through a channel the permit does not watch, because the key's confidentiality is the permit's assumption rather than its rule; name `proxy-techniques-css-injection` where the channel is a stylesheet and `proxy-techniques-dom-clobbering` where markup redefines the value the page reads.
- **Context reuse**: reuse the value across the contexts the permit meant to separate: a second page, a second request, or a second response that carries the same key.
- **Reflected directive**: where the permit's own text is attacker-influenced, a reflected value can add a directive the permit never listed, so the policy admits a route its author never wrote.

### Sanitiser Enumeration Gaps

- **Combination**: combine allowed elements, attributes, or namespaces into the effect the list meant to withhold, because each entry is safe alone and the combination is not.
- **Context model**: probe the sanitiser's model of parser context, since a context switch it does not model delivers the same combination.
- **Completed probe**: treat an allowed element that reaches execution through a helper as the completed probe.

### Confinement and Substitution Gaps

- **Declaration probing**: probe a declared restriction rather than trusting it: a disabled primitive, a sandbox claim, an allowlisted subset, or a delegate policy each has a route outside its list.
- **Substitution**: substitute an alternate primitive, wrapper, or delegate with the same reach where the named one is genuinely restricted.
- **Sink confirmation**: confirm the substitute at the sink, because a substitute that reaches nothing is a broken request rather than a bypass.

## Bypass Techniques

- **Bypass scope**: bypass shapes slip past a permit that is present, so each one is tried after the forbidden route is refused.
- **Permissive directives**: permissive directives and wildcard sources the policy itself admits.
- **Element combinations**: combinations of individually allowed elements or attributes that reach the withheld effect.
- **Context switches**: context and namespace switches the sanitiser does not model.
- **List patterns**: an origin or path list whose pattern admits a look-alike value or an unlisted spelling.
- **Presence-only validation**: a permit that validates only when its member is present, or one that matches a prefix of the value rather than the whole value.
- **Token values**: a token value the permit relies on, leaked through an unwatched channel, reused across the contexts it should separate, or accepted in a permissive format.
- **Substitutes**: substitute primitives, wrappers, and delegates with the same reach as a restricted one.
- **Sibling interfaces**: routes to the capability through a sibling interface the permit never enumerated.

## Chaining Attacks

- **Chain scope**: allowance gaps chain forward into the class that owns the effect, because a permitted request is only the first layer.
- **Effect hand-off**: hand the permitted route to the class that owns the effect, and prove the class-specific consequence there.
- **Signature-evasion stack**: stack with the signature evasion where the permit also lists literal shapes to step around.
- **Tier-gap stack**: stack with the tier gap where the permit is enforced at one tier only.
- **Own-step naming**: name the class at its own step rather than restating its procedure here.

## Testing Methodology

Allowance gaps read the permit first and probe second, because the omission is named before it is exercised.

1. **Read the permit** - its directives, sources, elements, and restrictions, and the step completes when the capability it withholds and the routes it omits are both listed.
2. **Baseline the forbidden route** - send a route the permit plainly forbids and record the answer, and the step completes when a refusal is recorded or the absence of enforcement is recorded with the test that showed it.
3. **Probe the declaration** - exercise one restriction claim at a time, and the step completes when each claim carries an enforced or unenforced verdict.
4. **Craft the unlisted route** - reach the withheld capability through a route the list does not name, and the step completes when the route is permitted and the effect reproduces at the sink.
5. **Substitute where restricted** - replace a genuinely restricted primitive with one of the same reach, and the step completes when the substitute carries a verdict naming what it reached.
6. **Attribute the pass** - pair the refused forbidden route with the permitted unlisted route, and the step completes when the omitted route is named from the pair.

## False Positives

- **Stop condition**: stop when the permit held or the capability was never withheld, because neither is a bypass.
- **Uniform refusal**: a permit whose forbidden route is refused at every attempt, confirmed across the route inventory.
- **Never withheld**: a capability the permit never withheld, where the effect was always allowed.
- **Broken request**: a pass whose effect never reached the sink, where the route was permitted and the request broke later.
- **Declared but unenforced**: a restriction declared but not enforced, which is a control gap to report rather than a bypass of the restriction.
- **Cached or simulated answer**: a cached or simulator response that replays a stored verdict for the unlisted route.

## Pro Tips

- **Discipline**: allowance gaps reward permit reading plus route inventory.
- **Permit reading**: read the permit before crafting, because the omission is a property of the list.
- **Route inventory**: enumerate the routes to the withheld capability and keep the inventory current, since each attempt can grow the list.
- **Admitted route**: prefer the route the permit itself admits, because it needs no second bypass behind it.
- **Claim-by-claim probing**: probe each restriction claim separately, because a declaration is not evidence of enforcement.
- **Sink confirmation**: confirm at the sink, because a permitted request is not the effect.

## Summary

A permit lists what may happen and every omitted route to the withheld capability defeats it. Allowance gaps read the list, probe each restriction claim, and reach the effect through a route the list never named.
