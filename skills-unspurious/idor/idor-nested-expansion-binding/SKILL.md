---
name: idor-nested-expansion-binding
description: Expand nested and projected sub-resources to test per-hop caller binding. Use when a projection knob may widen an authorized fetch, when a child resolver may skip its own check, when one batched request may multiplex foreign nodes.
metadata:
  version: 1.0.0
---

# IDOR Nested Expansion Binding

Expansion binding testing decides whether every nested or projected sub-resource inherits the caller binding of its parent.
The leading word is expand: every probe adds a knob, a hop, or a multiplexed node rather than substituting a lone identifier.

## Attack Surface

- **Expand**: applies where an authorized fetch accepts projection knobs, traverses resolver hops to child objects, or multiplexes many nodes in one batched request.
- **Knob forms**: the knobs may be field selectors, include or expand directives, or fragment spreads over privileged types.
- **Global node patterns**: global node patterns with encoded identifiers belong here as multiplexed per-node verdicts while multiplexing needs no scheduling beyond single-request batching.
- **Out-of-scope swaps**: top-level single-reference swaps stay in the sibling direct variant, and only sub-resource widening lives here.

## Reconnaissance

- **Knob mapping**: map every projection knob the fetch path honors, using interface documents and history until knob shapes are constructible.
- **Hop mapping**: map parent-to-child resolver hops by walking authorized objects outward until each hop's binding point is located.
- **Parent and child collection**: collect one valid parent per principal plus foreign child candidates from list, search, and export seeders.
- **Baseline confirmation**: confirm the unexpanded parent fetch succeeds for the owner before adding any widening.

## Detection Channels

- **Privileged sub-fields**: privileged sub-fields present in an expanded response to a non-owner decide the finding.
- **Unchecked child**: a child object returned through an authorized parent without its own check signals missing per-hop binding.
- **Multiplexed verdicts**: per-node decisions inside one multiplexed response that favor foreign callers confirm batch verdict gaps.
- **Fragment overfetch**: fragment-driven overfetch that surfaces privileged types confirms resolver-level failure.

## Adversarial Capabilities

- **Prerequisites**: this variant presupposes working sessions for at least an owner and a non-owner, with node identifiers for multiple principals where multiplexing is tested.
- **Knob addition**: it consumes the ability to add projection knobs and fragment shapes to an authorized fetch.
- **Direct addressing**: it consumes the ability to address child resolvers and multiplexed node lookups directly.
- **Principal handling**: principal handling follows the procedure owned by `two-principal-authz`, named here rather than restated.

## Trust Assumptions

- **The agreement**: the feature executes under the agreement that an object reference arriving with a request is private to the caller, that any surrounding authorization already binds the referenced object to that caller, that identity arriving through surrounding channels belongs to the same caller, that a token accepted by one service transfers only to its intended audience, and that a check performed at creation still holds at retrieval, so no caller reaches data beyond its own scope.
- **The failing clause**: the agreement fails when an expanded or nested sub-resource returns without inheriting the caller binding of its parent.

## Key Vulnerabilities

- **Bent step**: projection-parameter escalation with per-hop resolver verdicts is the bent step this variant owns over the parent.
- **Projection escalation**: add projection knobs to an authorized fetch and compare the widened response against the unexpanded control for privileged sub-fields.
- **Hop walking**: walk each authorized parent to its children across field and edge resolvers, deciding every hop separately instead of trusting the top-level gate.
- **Shared-type testing**: test the shared type explicitly: a per-type field-level check that is missing on a type nested inside an unrelated authorized query leaves the top level authorized while the nested object's fields are not.
- **Node multiplexing**: multiplex foreign nodes through aliased and batched lookups in one request, including decoded global-node forms, and decide each node independently.
- **Offline node-id swap**: decode, swap, and re-encode an opaque node identifier offline with `scripts/idor-node-id-swap`, so a swapped node is attributable to one changed part rather than to a fresh identifier.

## Bypass Techniques

- **Framing coercion**: coerce content-type and serialization framings while holding the expansion constant, since resolver and serializer checks often differ per stack.
- **Duplicate knobs**: pollute duplicate knob fields with both orderings to probe which occurrence the resolver honors.
- **Delegated transport framing**: treat transport-specific framing owned by `graphql` as a named step rather than restated mechanics, recording only the binding verdict here.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Child-identifier chaining**: feed child identifiers harvested from expanded responses into direct swaps to prove standalone reachability.
- **Overfetch pivot**: pivot a confirmed overfetch into session or object discovery through the privileged fields it exposes.
- **Multiplex pivot**: pivot a confirmed multiplex gap into bulk harvesting of foreign nodes in single requests, keeping each step's verdict separate.

## Testing Methodology

1. **Request-shape derivation** - derive the request shape from evidence by collecting interface, client, and history material, with completion when fetch paths, knob shapes, and resolver hops are inferable.
2. **Matrix build** - build the subject-resource-action matrix by enumerating each role against each parent, knob, hop, and multiplex shape, with completion when every widening action has an expected-principal cell.
3. **Principal setup** - establish principals by acquiring one working session per matrix role, with completion when each role issues an authenticated baseline (procedure owned by `two-principal-authz`).
4. **Projection escalation** - escalate by projection by adding knobs and fragments to authorized fetches, with completion when every knob has a widened attempt beside its unexpanded control.
5. **Hop traversal** - traverse resolver hops by walking each parent to its children, with completion when every hop carries its own binding verdict.
6. **Node multiplexing** - multiplex nodes by retrieving multiple principals' nodes in aliased and batched requests, with completion when every node carries an independent verdict.
7. **Retry before verdict** - retry failures with the inferred verb and fields before judging, with completion when no probe is judged on a wrong-verb or placeholder-shape attempt.

## False Positives

- **Shared sub-fields**: discard sub-fields the design exposes to every authorized parent holder, confirming exposure scope before filing.
- **Public children**: discard public child objects reachable by design without a caller binding, verifying publicity symmetrically.
- **Empty expansions**: discard empty expansions that withhold foreign children while the owner view succeeds, confirming withholding rather than hidden exposure.
- **Metadata shapes**: discard metadata shapes that name a child without returning its sensitive content, confirming no field data leaks.

## Pro Tips

- **Resolver-boundary validation**: validate at resolver boundaries and never trust parent authorization to cover children, since hops fail independently.
- **Independent node verdicts**: decide every multiplexed node separately, since one denied node masks neighboring grants.
- **Fragment testing**: test fragment spreads over privileged types explicitly, since overfetch hides inside composition.
- **One knob per probe**: vary knobs one at a time against a fixed parent, since simultaneous widening hides which hop failed.
- **Family naming**: name GraphQL-specific steps owned by `graphql` rather than restating them.

## Summary

Sub-resource binding must re-anchor the caller on every knob, hop, and multiplexed node.
Expand each fetch and walk each hop, and file every child that answers a foreign caller.
