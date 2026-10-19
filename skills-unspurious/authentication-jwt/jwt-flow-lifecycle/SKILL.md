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

- **Multi-step protocol runs**: span authorization, callback, token issuance, refresh, device approval, and session termination.
- **Multi-client topologies**: sibling clients share one provider and cross-client redemption is reachable.
- **Refresh, revocation, binding, and fixation surfaces**: govern token durability after issuance.

## Reconnaissance

- **Client and provider inventory**: inventory every client, provider, and session termination path and record which run state each one expects.
- **Transcript capture**: capture protocol transcripts for legitimate runs across at least two clients, including challenge, verifier, state, and binding posture.
- **Lifecycle oracle map**: map the refresh, revocation, device approval, and binding oracles so each lifecycle transition has a known verdict before corruption starts.
- **Run-advance probe**: probe whether a downgraded flow shape, a cross-client redemption, a reused retired token, or an attacker-fixed session identifier advances the run.

## Detection Channels

- **Cross-client acceptance**: a code or token issued for one client redeems successfully at a sibling client.
- **Downgrade acceptance**: a weakened challenge, verifier, state, or binding shape still advances the run.
- **Lifecycle oracle signals**: refresh reuse, post-logout replay, unbound replay from a second channel, or fixed session identifiers still verify.
- **Device approval signals**: a device-issued artifact verifies at an unintended client or service.

## Adversarial Capabilities

- **Full-run drive**: drive complete protocol runs as a legitimate client across at least two sibling clients.
- **Artifact shaping**: shape, omit, or downgrade flow artifacts such as challenge, verifier, state, and binding material.
- **Oracle sequencing**: sequence lifecycle oracles covering use, reuse, termination, and replay from a second channel.
- **Session fixation**: fix or inject session identifiers and approve device artifacts on demand.

## Trust Assumptions

- **The agreement**: at the moment a protected feature executes, the server assumes each presented token is bound to one issuer, one audience, one verification key, one signature algorithm, and one client context, and that only the expected issuer minted it for the expected audience under the expected key and algorithm within its validity window.
- **The failing clause**: the clause binding the token to its protocol run and lifecycle state fails, so a token from another client run or a retired token still verifies.

## Key Vulnerabilities

- **Client mix-up**: redeems artifacts issued for one client at a sibling client without binding the run to the originating client.
- **Flow downgrade**: accepts weakened or absent challenge, verifier, state, or binding material and still advances the run.
- **Device misuse**: accepts device-issued artifacts at unintended clients or services outside the approval scope.
- **Lifecycle failure**: reuses retired refresh artifacts without detection, honors tokens after termination, permits replay from an unbound channel, or binds fresh tokens to attacker-fixed session identifiers.

## Advanced Techniques

- **Parallel sibling runs**: drive two sibling clients through the full run in parallel so cross-client redemption is observable step by step.
- **Single-artifact variation**: vary one flow artifact per run so each downgrade verdict maps to exactly one weakened shape.
- **Ordered lifecycle oracles**: sequence the lifecycle oracles as use, reuse, termination, then replay so reuse detection and revocation gaps surface in order.
- **Binding-absence test**: test binding absence by replaying a bound token shape from a second channel and observing whether channel binding is enforced.

## Bypass Techniques

- **Client-binding bypass**: defeat client binding by redeeming one client run artifacts at a sibling client callback and token path.
- **Challenge and verifier bypass**: defeat challenge and verifier strength by presenting downgraded, transformed, or absent verifier shapes across runs.
- **State and approval bypass**: defeat state and approval integrity by presenting predictable, reused, or absent state shapes and out-of-scope device approvals.
- **Lifecycle-control bypass**: defeat rotation, reuse detection, revocation, and binding by replaying retired artifacts, replaying post-termination tokens, replaying from a second channel, and fixing session identifiers.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Proxy-techniques handoff**: name the proxy-techniques family at the capture-and-replay step and start here once a cross-client artifact is obtainable.
- **Token theft handoff**: name token theft skills at the exfiltration step where a retired artifact is held for lifecycle replay.
- **Signature forgery handoff**: hand signature-only findings to the signature forgery variant once the run is correctly bound and only the algorithm binding is suspect.
- **Claims confusion handoff**: hand cross-context findings to the claims confusion variant once the run is correctly bound and only the context binding is suspect.

## Testing Methodology

1. **Record the legitimate run** - Drive one complete run per client and note the challenge, verifier, state, binding, refresh, and termination posture.
2. **Drive cross-client redemption** - Redeem one client run artifacts at a sibling client and record each acceptance verdict.
3. **Drive downgraded flows** - Present weakened or absent challenge, verifier, state, and binding shapes across runs, one weakened shape per run.
4. **Drive lifecycle oracles** - Sequence refresh reuse, post-termination replay, second-channel replay, device misuse, and session fixation probes, and record each verdict.
5. **Verify enforcement** - Tie each acceptance verdict to the exact run or lifecycle state corrupted and declare the missing binding only on a reproducible acceptance proof.

## False Positives

- **Consistent cross-client rejection**: rejection of every cross-client redemption with a consistent unauthorized verdict signals intact client binding.
- **Strong check enforcement**: enforcement of strong challenge, verifier, state, and binding checks with downgrade rejection signals a correct run rather than a missed mix-up.
- **Rotation and revocation**: refresh rotation with reuse detection and revocation on session end that rejects retired and post-termination tokens signals a correct lifecycle.
- **Channel-bound rejection**: channel-bound tokens rejected on replay from a second channel signal correct binding rather than a missed bypass.

## Pro Tips

- **Full runs**: drive full runs instead of single requests because lifecycle gaps surface only across ordered transitions.
- **One element at a time**: isolate one corrupted run element at a time so each acceptance verdict maps to exactly one binding.
- **Oracle order**: run the lifecycle oracles in order because reuse detection must be tested before termination and termination before replay.
- **Minimal proof**: prefer minimal acceptance proofs that show one foreign-run or retired artifact verifying on the target path.
- **Path retest**: retest every client and channel separately because run binding commonly differs between web, alternate channel, device, and service paths.

## Summary

Protocol execution must bind each artifact to its originating client run and enforce challenge strength, approval scope, rotation, reuse detection, revocation, and channel binding on every path.
Any gap in that binding admits lifecycle abuse.
