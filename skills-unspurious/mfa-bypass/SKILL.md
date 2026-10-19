---
name: mfa-bypass
description: Second-factor bypass where the factor challenge is not enforced on every sensitive transition, the factor proof is replayable or guessable, or an alternate factor path accepts a weaker proof.
metadata:
  version: 1.0.0
---

# MFA Bypass

A second factor is a step-up the account owner must pass before a sensitive transition completes, and the application trusts that the step-up is enforced on every transition, that the proof it issued is single-use and bound to the challenge, and that every alternate path into the account is as strong as the primary factor.
The class covers the three ways that agreement fails: the factor is skipped because the transition never asks for it, the factor proof itself is defeated, and an alternate factor path accepts a proof the primary path would refuse.
The goal is the post-factor state, proved by reaching a resource the pre-factor state cannot reach.

## Attack Surface

- **Applicability**: centers on a flow with a pre-factor state, a factor challenge, and a post-factor state, and on every sensitive transition the post-factor state unlocks.
- **State transitions**: password change, identity and address change, factor enrolment and reset, payment or transfer, recovery, and any action the application labels sensitive.
- **Factor-accepting endpoints**: the proof-verification endpoint, the re-send endpoint, the enrolment endpoint, the factor-reset endpoint, and the status or polling endpoint.
- **Alternate paths**: recovery codes, a secondary factor, a remembered-device token, a passwordless entry, and any entry that issues the post-factor state by another route.
- **Factor strengths**: a code delivered out of band, a device-held assertion, and a knowledge answer each carry their own entropy, lifetime, and rate-limit posture.

## Reconnaissance

### State-Machine Mapping

- **State recording**: drive the flow by hand and record which request issues the pre-factor state, which request proves the factor, and which state the post-factor access requires.
- **Transition sweep**: record every sensitive transition and whether the application requires the factor again at that transition or accepts the session as already stepped up.
- **Sibling-route recording**: record the sibling routes of each gated route, because a gate is commonly attached to one registration and not to the action it guards.

### Factor Posture Mapping

- **Proof-shape recording**: record the proof shape per factor, its length, alphabet, lifetime, and single-use behavior, and whether a re-issue invalidates the previous proof.
- **Limit and verdict recording**: record the rate limit on the verification endpoint and the verdict difference between a wrong and a right value, including partial-value behavior.
- **Alternate-path recording**: enumerate the alternate paths and record the controls each one carries, because the weakest accepted path sets the effective factor strength.

## Detection Channels

- Post-factor access from a pre-factor state, shown by a resource the pre-factor session reaches that it should not.
- A consumed factor proof accepted a second time, which shows the single-use clause is unenforced.
- A partial or prefix-shaped proof accepted, which shows the comparison leaks correctness in pieces.
- More than one success from concurrent submissions of one proof, which shows a validation race.
- An alternate path accepting a proof the primary path refuses, which sets the effective strength below the declared factor.
- A remembered-device token accepted from a different device or address context, which shows the trust is not bound to the context that earned it.
- A verification endpoint whose verdict does not change between a wrong and a right value, which shows the decision is made elsewhere.

## Adversarial Capabilities

- Hold primary credentials for a test account whose factor is enrolled, plus a second account to observe the post-factor state.
- Drive the flow by hand so each state transition stays separable and replayable.
- Submit one proof more than once, and concurrently, while keeping the same pre-factor session.
- Read the channel the factor is delivered through, or hold the device that receives it.
- Reach the alternate paths, including the enrolment and reset paths, from a pre-factor session.

## Trust Assumptions

- **The agreement**: after primary authentication, every sensitive transition requires a factor proof the server issued to that account, the proof is single-use and bound to the challenge and the session that requested it, every accepted path into the account carries the same factor strength, and the post-factor state is granted only after the proof verifies.
- **The enforcement clause fails** where the factor is a user-interface step rather than a server-side requirement, so a transition completes from the pre-factor state.
- **The lifecycle clause fails** where a consumed, expired, or superseded proof still verifies, or where concurrent submissions are all accepted.
- **The strength clause fails** where an alternate path accepts a shorter, unthrottled, or client-decided proof, so the account is only as strong as its weakest accepted factor.

## Key Vulnerabilities

### Enforcement Gaps

- **Interface-only enforcement**: the application redirects to the challenge but never requires it, so any post-factor resource answers the pre-factor session.
- **Route-level gating**: the factor gate decorates one route while the sibling route that performs the same action carries no gate.
- **Transition gaps**: the factor is required at login and not at a later sensitive transition, so a step-up is assumed rather than enforced.
- **Pre-factor privilege**: the pre-factor session already carries enough authority to change the factor, the address, or the password.

### Proof Lifecycle Gaps

- **Reuse after consumption**: a proof accepted a second time, in the same session or a later one.
- **No expiry and no supersession**: an aged proof, or a proof superseded by a re-issue, still verifies.
- **Concurrent acceptance**: several submissions of one proof all succeed when they arrive inside the validation window; name `race-conditions` at the window step rather than restating the concurrency mechanics here.
- **Verification-oracle shaping**: a verdict that distinguishes a correct prefix or a correct value in pieces, which collapses the guessing space.

### Proof Strength Gaps

- **Low-entropy proof**: a short numeric or dictionary-shaped proof with no effective rate limit, where the limit slows rather than blocks.
- **Client-decided verdict**: the client acts on its own reading of the response, so a manipulated verdict reaches the post-factor state.
- **Delivery-channel weakness**: a proof delivered through a channel an attacker can read, which is a channel-trust problem rather than a factor problem.

### Alternate-Path Weakness

- **Recovery codes**: recovery codes that are low-entropy, unrotated, reusable, or displayed where any read reaches them.
- **Secondary factor**: a fallback factor offered without the primary factor's controls, so the account is downgraded to the weakest offered factor.
- **Remembered-device trust**: a device token that is not bound to the device or address context that earned it, so the token is portable.
- **Enrolment from a pre-factor session**: a factor can be enrolled or replaced before the existing factor proves, which converts a transient session into a durable factor the attacker owns.

## Advanced Techniques

- **Single-session walks**: hold one pre-factor session across a proof-space walk, because re-authentication regenerates the proof and discards the progress.
- **Window bracketing**: bracket the concurrent-validation window from both sides, because a single extra request rarely lands inside it.
- **Transition sweep after the factor**: enumerate the transitions that follow the factor, since step-up enforcement commonly stops at the login boundary.
- **Factor-reset reach**: test whether a factor reset or disable request is reachable from a pre-factor or stolen session, because it converts a session into account ownership.
- **Alternate-path enumeration**: enumerate every path that issues the post-factor state, including passwordless and recovery entries, because each path carries its own controls.
- **Token-claim reading**: where the post-factor state is asserted by a token, read whether the factor claim is bound to the session; name `authentication-jwt` at the token step rather than restating token verification here.

## Bypass Techniques

- **Throttle defeat**: a limit that slows without blocking is not enforcement; name `defence-bypass` at the throttle step rather than restating the evasion mechanics here.
- **Verdict manipulation**: a verdict the client acts on can be rewritten in transit, so the bypass defeats the client-side decision rather than the server.
- **Partial-value acceptance**: a comparison that leaks correctness in pieces defeats a proof space the full comparison would protect.
- **Superseded-proof acceptance**: a proof kept valid across a re-issue defeats the supersession control.
- **Portable device trust**: a remembered-device token replayed from another context defeats a trust that was never bound to that context.
- **Unthrottled alternate path**: the alternate path is the weakest control, so defeating it is defeating the factor.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Credential plus factor gap**: a recovered credential pairs with a factor that is not enforced on the sensitive transition, and `weak-credential-discovery` owns the credential step.
- **Session plus factor reset**: a stolen session that reaches the factor-reset path becomes durable account ownership rather than a transient read.
- **Cross-site step-up**: a cross-site delivery reaches the step-up request where the factor gate relies on the interface, and `csrf` owns the delivery step.
- **Recovery plus factor**: a recovery flow that issues a session without the factor is a factor bypass by another path, and `account-recovery` owns the artifact step.
- **Factor claim in a token**: where the factor state is asserted by a token claim, a forgeable token converts into a factor bypass; name `authentication-jwt` at the token step.

## Testing Methodology

MFA bypass maps the state machine first and attacks the factor second, because no bypass is meaningful without the state it reaches.

1. **Map the state machine** - record the pre-factor state, the challenge, the post-factor state, and every sensitive transition, and the step completes when every transition carries a factor-required verdict.
2. **Baseline the full flow** - complete the flow legitimately and record the post-factor resource set, and the step completes when the post-factor baseline is recorded with the requests that prove it.
3. **Probe the transitions** - request each sensitive transition and each gated sibling route from the pre-factor session, and the step completes when every transition carries a reached-or-refused verdict.
4. **Probe the proof lifecycle** - reuse a consumed proof, replay an aged one, re-issue and retry the first, and submit one proof concurrently, and the step completes when each lifecycle shape carries a verdict.
5. **Probe the proof strength** - test partial values, the verdict shape, and the rate limit separately, and the step completes when the guessing space and the effective limit are recorded.
6. **Probe the alternate paths** - test recovery codes, the secondary factor, remembered-device trust, and the enrolment and reset paths, and the step completes when each path carries a strength verdict.
7. **Confirm the bypass** - reach a post-factor resource from the pre-factor state and record the exact shape, and the step completes when the finding carries a reproducible shape and the state it reached.

## False Positives

- A success-shaped response with no post-factor access, where the client acted on its own verdict and the server never granted the state.
- A transition that is genuinely non-sensitive by the application's own model, so the factor is not required by design.
- A factor not required because the session is already post-factor, confirmed by the state rather than by the request.
- A test account whose factor was never enrolled, which is an enrolment state rather than a bypass.
- A limit that slows rather than blocks, which is a weak control rather than a missing one; report it as the strength finding it is.
- An alternate factor that is genuinely as strong as the primary one, which is a design choice rather than a weakness.
- A verdict difference caused by network noise rather than by proof correctness, confirmed by repeating the measurement.

## Pro Tips

1. Prove the post-factor state with a request the pre-factor session could not reach, never with the response shape alone.
2. Never re-authenticate during a proof-space walk, because a fresh login regenerates the proof.
3. Test the sibling routes of every gated route; the gate usually sits on one registration.
4. Sweep the transitions that follow the factor, since step-up enforcement often stops at the login boundary.
5. Treat the alternate paths as the same factor for impact purposes, because the account is only as strong as its weakest accepted path.
6. Record the exact shape and the state it reached so the finding reproduces from a clean session.

## Summary

A second factor holds only when every sensitive transition requires it server-side, when the proof is single-use and bound to its challenge, and when every alternate path into the account is as strong as the primary one.
Test the state machine before the proof, and treat the weakest accepted path as the factor's effective strength.

