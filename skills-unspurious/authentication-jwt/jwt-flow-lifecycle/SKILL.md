---
name: jwt-flow-lifecycle
description: Drive protocol lifecycle abuse through client mix-up, flow downgrade, device misuse, refresh reuse, or revocation bypass. Use when multiple clients share one provider, when flow downgrades look possible, when device flows are exposed, or when refresh and revocation look unenforced.
metadata:
  version: 1.0.0
---

# JWT Flow Lifecycle

Drive the protocol run itself and corrupt its lifecycle state so a token from another run or a retired token still verifies.
This variant breaks the flow and lifecycle binding while the signature routine, the key source, and the claim context stay unchanged.

## Attack Surface

- Multi-step protocol runs spanning authorization, callback, token issuance, refresh, device approval, and session termination.
- Multi-client topologies where sibling clients share one provider and cross-client redemption is reachable.
- Refresh, revocation, binding, and fixation surfaces that govern token durability after issuance.

## Reconnaissance

- Inventory every client, provider, and session termination path and record which run state each one expects.
- Capture protocol transcripts for legitimate runs across at least two clients, including challenge, verifier, state, and binding posture.
- Map the refresh, revocation, device approval, and binding oracles so each lifecycle transition has a known verdict before corruption starts.
- Probe whether a downgraded flow shape, a cross-client redemption, a reused retired token, or an attacker-fixed session identifier advances the run.

## Detection Channels

- Cross-client acceptance where a code or token issued for one client redeems successfully at a sibling client.
- Downgrade acceptance where a weakened challenge, verifier, state, or binding shape still advances the run.
- Lifecycle oracle signals where refresh reuse, post-logout replay, unbound replay from a second channel, or fixed session identifiers still verify.
- Device approval signals where a device-issued artifact verifies at an unintended client or service.

## Adversarial Capabilities

- Ability to drive complete protocol runs as a legitimate client across at least two sibling clients.
- Ability to shape, omit, or downgrade flow artifacts such as challenge, verifier, state, and binding material.
- Ability to sequence lifecycle oracles covering use, reuse, termination, and replay from a second channel.
- Ability to fix or inject session identifiers and to approve device artifacts on demand.

## Trust Assumptions

- At the moment a protected feature executes, the server assumes each presented token is bound to one issuer, one audience, one verification key, one signature algorithm, and one client context, and that only the expected issuer minted it for the expected audience under the expected key and algorithm within its validity window.
- The clause binding the token to its protocol run and lifecycle state fails, so a token from another client run or a retired token still verifies.

## Key Vulnerabilities

- Client mix-up redeems artifacts issued for one client at a sibling client without binding the run to the originating client.
- Flow downgrade accepts weakened or absent challenge, verifier, state, or binding material and still advances the run.
- Device misuse accepts device-issued artifacts at unintended clients or services outside the approval scope.
- Lifecycle failure reuses retired refresh artifacts without detection, honors tokens after termination, permits replay from an unbound channel, or binds fresh tokens to attacker-fixed session identifiers.

## Advanced Techniques

- Drive two sibling clients through the full run in parallel so cross-client redemption is observable step by step.
- Vary one flow artifact per run so each downgrade verdict maps to exactly one weakened shape.
- Sequence the lifecycle oracles as use, reuse, termination, then replay so reuse detection and revocation gaps surface in order.
- Test binding absence by replaying a bound token shape from a second channel and observing whether channel binding is enforced.

## Bypass Techniques

- Defeat client binding by redeeming one client run artifacts at a sibling client callback and token path.
- Defeat challenge and verifier strength by presenting downgraded, transformed, or absent verifier shapes across runs.
- Defeat state and approval integrity by presenting predictable, reused, or absent state shapes and out-of-scope device approvals.
- Defeat rotation, reuse detection, revocation, and binding by replaying retired artifacts, replaying post-termination tokens, replaying from a second channel, and fixing session identifiers.

## Chaining Attacks

- Name the proxy-techniques family at the capture-and-replay step and start here once a cross-client artifact is obtainable.
- Name token theft skills at the exfiltration step where a retired artifact is held for lifecycle replay.
- Hand signature-only findings to the signature forgery variant once the run is correctly bound and only the algorithm binding is suspect.
- Hand cross-context findings to the claims confusion variant once the run is correctly bound and only the context binding is suspect.

## Testing Methodology

1. **Record the legitimate run** - Drive one complete run per client and note the challenge, verifier, state, binding, refresh, and termination posture.
2. **Drive cross-client redemption** - Redeem one client run artifacts at a sibling client and record each acceptance verdict.
3. **Drive downgraded flows** - Present weakened or absent challenge, verifier, state, and binding shapes across runs, one weakened shape per run.
4. **Drive lifecycle oracles** - Sequence refresh reuse, post-termination replay, second-channel replay, device misuse, and session fixation probes, and record each verdict.
5. **Verify enforcement** - Tie each acceptance verdict to the exact run or lifecycle state corrupted and declare the missing binding only on a reproducible acceptance proof.

## False Positives

- Rejection of every cross-client redemption with a consistent unauthorized verdict signals intact client binding.
- Enforcement of strong challenge, verifier, state, and binding checks with downgrade rejection signals a correct run rather than a missed mix-up.
- Refresh rotation with reuse detection and revocation on session end that rejects retired and post-termination tokens signals a correct lifecycle.
- Channel-bound tokens rejected on replay from a second channel signal correct binding rather than a missed bypass.

## Pro Tips

- Drive full runs instead of single requests because lifecycle gaps surface only across ordered transitions.
- Isolate one corrupted run element at a time so each acceptance verdict maps to exactly one binding.
- Run the lifecycle oracles in order because reuse detection must be tested before termination and termination before replay.
- Prefer minimal acceptance proofs that show one foreign-run or retired artifact verifying on the target path.
- Retest every client and channel separately because run binding commonly differs between web, alternate channel, device, and service paths.

## Summary

Protocol execution must bind each artifact to its originating client run and enforce challenge strength, approval scope, rotation, reuse detection, revocation, and channel binding on every path.
Any gap in that binding admits lifecycle abuse.
