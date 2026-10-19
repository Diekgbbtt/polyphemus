---
name: bfla-client-identity-trust
description: Identity-source and hint-gate testing that decides which request input the service treats as the actor. Use when client-supplied identity hints may override token claims, when a tenant or scope selector may double as the actor, when gateway-injected values may clash with caller credentials, when a gate keyed on navigation provenance, an origin hint, or a routing override decides the verdict.
metadata:
  version: 1.0.0
---

# BFLA Client Identity Trust

Action-level authorization fails open when the service reads the actor from a request hint instead of the verified credential.
The hint need not be an identity claim at all: navigation provenance, routing overrides, and network-origin hints decide gates the same way, and the same contradiction primitive tests every hint class.
The leading word is identity: every probe holds the token constant while varying the hint or selector and reads which source wins beside its unhinted control.

## Attack Surface

Identity applies where a privileged action reads actor, role, or scope from any request input beyond the verified token claims.
The hint may be a client-supplied identity header, a cookie-carried role or scope flag, a request-parameter role value, an organization or project selector, or an edge-injected value the backend treats as authoritative.
The hint may also be no identity claim at all: navigation provenance, an origin or network-address hint, or a routing override that decides the verdict the way an identity source would.
Pure routing selectors that scope without identifying stay inside the shared procedure as aspects; only selector-as-identity cases enter this variant, and where a routing override also changes the route the alternate-path sibling owns that delta.
Concrete hint names and selector values are runtime knowledge-base facts and never define the attempt.

## Reconnaissance

Map every identity and selector input the privileged action accepts before varying anything.
Collect interface documents, client bundles, prior HTTP history, and gateway topology notes until each action owns a list of candidate hints and selectors.
Record which values the edge injects versus which the client supplies, since precedence between them is the question.
Record every gate keyed on a hint that is not an identity claim: navigation provenance, origin or network-address values, and routing overrides; enumerate the forwarding-address header family (including misspellings and private-address forms) where a network-origin allowlist is suspected.
Confirm the unhinted baseline decision with the lower-role token before judging any hinted attempt.

## Detection Channels

Access that changes on hint or selector change alone decides the finding.
A privileged effect under a hinted lower-role token beside denial without the hint confirms precedence failure.
Conflicting-hint pairs showing the service honoring the hint over the token confirm which source wins.
A gate that opens on a provenance, origin, or routing hint change alone, with the credential constant, confirms hint-gate trust rather than identity trust.
A before-and-after state snapshot showing the privileged change completes the proof.

## Adversarial Capabilities

This variant presupposes a working lower-role session plus the ability to call the privileged action directly, and it consumes header and selector control.
It consumes the ability to supply, remove, and contradict identity hints and scope selectors while holding the token constant.
It consumes the ability to route the same hinted request behind the gateway and direct to the service for comparison.
Principal handling follows the procedure owned by `two-principal-authz`, named here rather than restated.

## Trust Assumptions

The privileged function executes under the agreement that every route and handler reaching it enforces the same caller-to-action binding, that edge and interface gates transfer no authority downstream, that actor identity comes only from verified token claims rather than request hints, and that an approval recorded in a prior step never authorizes a later execution, so no lower-privileged caller causes a privileged effect and no privileged state leaks to an unentitled observer.
The agreement fails when the service reads the actor from a client-supplied identity hint or selector instead of the verified token claims, so conflicting sources resolve in the attacker's favor.

## Key Vulnerabilities

Conflicting-header precedence probing plus selector-as-identity substitution is the bent step this variant owns over the parent.
Resubmit each privileged action with identity hints that contradict the token claims, and record which source the service honors.
Resubmit with tenant or scope selectors swapped under the same token, and separate routing effects from identity effects before filing.
Resubmit behind the gateway versus direct to the service, since injection precedence differs by routing.

### Hint-Gate Precedence

- Test every gate keyed on a non-identity hint with the same triple primitive: supply the hint, remove it, and contradict it, holding the credential and the route constant across the three attempts.
- Where a network-origin allowlist is suspected, supply each forwarding-address header form in turn (including misspellings and private-address shapes) and record which form the gate honors.
- Where the gate reads navigation provenance, test the same request with the hint present, absent, and foreign, and read whether the verdict tracks the hint rather than the credential.
- Where the gate reads a routing override, confirm the verdict change and then hand the route-shadowing delta to the alternate-path sibling, recording only the identity verdict here.

The parent vary step covers selector switching and gateway routing but never describes hint-versus-claim precedence, so this variant owns that procedure.

## Advanced Techniques

Scope-selector cases extend the same precedence question where the runtime is multi-tenant.
Attempt cross-scope privileged actions by switching selectors under one unchanged token, and file only cases where the selector acted as the actor.
Compare gateway-routed and direct decisions for the same hinted request, since injected values clash with caller credentials exactly at that boundary.
Treat transport-specific field shapes as aspects of the same substitution, recording verdicts without splitting the procedure.

## Bypass Techniques

Identity-hint trust is the control defeat live for this variant.
Supply identity hints the token never granted, then remove them, then contradict the token with them, keeping route and body constant across the triple.
Apply the same triple to hints that are not identity claims: navigation provenance, origin and forwarding-address values, and routing overrides.
Observe which of the three the service honors, and never infer precedence from a single hinted attempt.
Record the winning source per finding so claim-wins cases stay separate from hint-wins cases.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Testing Methodology

1. Build the actor-by-action matrix by enumerating each role against each privileged action, with completion when every action has an expected-role cell (procedure owned by `two-principal-authz`).
2. Establish principals by acquiring one working session per matrix role, with completion when each role issues an authenticated baseline (procedure owned by `two-principal-authz`).
3. Inventory hints by listing every identity, selector, and non-identity hint input per privileged action with its supplier, with completion when each input is labeled client-supplied, edge-injected, or both.
4. Probe precedence by resubmitting each action hinted, unhinted, and contradictorily hinted under one constant token beside its proper-role control, with completion when every hint, including provenance, origin, and routing hints, carries all three attempts beside the control.
5. Substitute selectors by swapping scope values under the same token across gateway and direct routing, with completion when every selector and routing pair carries a recorded decision that separates routing from identity.
6. Confirm the effect by comparing state snapshots and audit entries across each pair, with completion when every positive shows a privileged change rather than a status artifact alone.

## False Positives

Discard read-only endpoints documented as public, since reachability without a privileged effect is not an actor-binding failure.
Discard preview toggles intentionally open to all roles under a clear policy, confirming the policy before filing.
Discard stubbed privileged endpoints in simulated environments that record no real effect.
Discard pure-routing selector effects where the identity stayed constant and only the scope changed without privilege gain.

## Pro Tips

Hold the token constant across each triple, since only the hint may vary when the source is the question.
Treat non-identity hints as identity sources in waiting: a gate keyed on provenance, origin, or routing is deciding the verdict on a value the caller controls.
Test the contradicting pair explicitly, since agreement between hint and token proves nothing about precedence.
Compare gateway-routed and direct decisions for every hint, since injection behavior lives at that boundary.
Prefer minimal proofs: one hinted request that flips a privileged field or invokes a privileged method with a lower-role session.
Never conclude resistance from an unhinted denial, since the hinted form may still resolve in the attacker's favor.

## Summary

The actor for every privileged action must come from verified token claims, never from request hints or selectors.
Vary each hint beside its control under one constant token, and file every pair where the hint overrules the credential.
