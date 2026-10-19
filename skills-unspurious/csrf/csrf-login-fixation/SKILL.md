---
name: csrf-login-fixation
description: Plant attacker-chosen credentials through cross-site login flows that permit fixation, confirm victim browsers enter the attacker account when logout clearing precedes planting, and abuse subsequent victim actions when identity comparison proves fixation.
metadata:
  version: 1.0.0
---

# CSRF Login Fixation

Login flows that accept cross-origin credential planting bind the victim browser to the attacker account.
This variant forces logout clearing then plants attacker credentials and confirms the victim now sits in the attacker account.
The confirmation goal is reversed session direction that later enables data capture or action attribution chaining.

## Attack Surface

- **Applicability**: centers on a login flow that permits session fixation or account planting through a cross-origin request.
- **Ambient authority**: the flow carries cookie-based ambient authority with a session that can be cleared by forced logout and replanted with attacker-chosen credentials.
- **Request shape**: a chained logout-then-login sequence emitted from an attacker page, completing on account identity rather than on a single state effect.
- **Out-of-scope transports**: single-request replay plus navigation triggering plus semantic reconstruction plus socket transports ride outside this variant in their sibling variants.
- **Credential-flow endpoints**: belong here when they accept the same plant-then-abuse sequence.

## Reconnaissance

### Login and Session-Entry Reachability

- **Login-flow recording**: record login plus logout plus credential-change flows that accept cross-origin triggering.
- **Token-clearing recording**: record token clearing behavior on forced logout, noting whether proof-of-intent state resets.
- **Account-linking recording**: record account-linking plus session-entry points separately, because their planting shape differs.

### Defense Presence

- **Proof-of-intent checks**: locate proof-of-intent checks such as per-request tokens plus origin or referrer enforcement on login paths.
- **Fixation-behavior recording**: record fixation-relevant behavior including session reuse across login plus missing credential binding for the defeat sub-step.
- **Header-acceptance recording**: record null plus missing plus cross-origin header acceptance for the defeat sub-step.

## Detection Channels

- **Live channels**: fixation completes on identity rather than on a single effect.
- **Account-identity comparison**: showing the victim browser now sits in the attacker account.
- **Logout-clearing signal**: showing proof-of-intent state reset before planting.
- **Plant-acceptance signal**: showing the login flow accepted attacker-chosen credentials cross-origin.
- **Post-plant action attribution**: showing later victim actions land under the attacker account.
- **Null-origin acceptance**: showing the planting sequence proceeds from an empty-context source.

## Adversarial Capabilities

- **Planting prerequisites**: lure plus credential control plus identity comparison, which the variant consumes.
- **Victim lure**: lure the victim to an attacker-controlled cross-origin page with no script execution in the target origin.
- **Credential control**: control attacker-chosen credentials whose later activity the tester can observe.
- **Forced logout clearing**: force logout clearing to reset proof-of-intent state before planting.
- **Credential planting**: plant the credentials through a cross-site login-shaped request.
- **Identity comparison**: compare account identity before-versus-after to confirm the victim browser entered the attacker account.

## Trust Assumptions

- **The agreement**: the state-changing feature trusts a cookie-authenticated cross-origin request to carry genuine user intent, holds the session cookie stable as ambient authority, holds the endpoint in its intended state-change shape, holds the request in its declared method plus encoding shape, holds a non-replayable proof of intent enforced, holds the transport in single-request HTTP shape with victim-session direction, and changes sensitive account plus storage plus action state only through intended effects under the victim session.
- **The failing clause**: this variant breaks the session-direction clause because the login flow accepts attacker-supplied credentials after forced logout, so later victim actions run under the attacker account.

## Key Vulnerabilities

### Logout-Then-Plant Sequencing

- **Logout-then-plant sequencing**: force logout to clear existing proof-of-intent state, then plant attacker-chosen credentials through the cross-site login shape.
- **Ordered-sequence discipline**: treat clearing plus planting as one ordered sequence rather than two independent probes, because planting without clearing leaves the victim session intact.
- **Clear-then-plant ownership**: the parent session step assumes abuse of the victim session and cannot describe plant-then-abuse sequencing, so this variant owns the clear-then-plant procedure.

### Account-Identity Completion

- **Account-identity completion**: complete on account-identity comparison showing the victim browser sits in the attacker account, rather than on a single state-effect comparison.
- **Identity-point recording**: record the identity before planting plus after planting plus after a subsequent victim action, because fixation proves only when later actions attribute to the planted account.
- **Compare-identities ownership**: the parent session step never names identity-based completion, so this variant owns the compare-identities procedure.

### Credential-Flow Planting Shapes

- **Planting shapes**: plant through login plus credential-change plus account-linking shapes where the flow accepts cross-origin triggering.
- **Replay exclusion**: keep single-request state-change replay outside this variant, because planting completes on direction reversal rather than on one effect.
- **Aspect containment**: these shapes stay aspects inside this variant because the sequence covers them with a planting-shape parameter and no new transport is needed.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no value difference changes the planting step itself.
- **Token-gap steering**: token absence plus cross-request reuse plus login-scoped token gaps steer the planting sequence past a weak proof-of-intent check.
- **Header-value steering**: null plus missing plus cross-origin header values steer the planting sequence past a weak origin or referrer check.
- **Cleared-state steering**: forced logout steers the flow through a cleared state where fresh planting faces the weakest check.
- **Referrer stripping**: referrer stripping through an empty-context navigation source presents the planting without its origin context.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Forward chaining scope**: fixation chains forward into capture and attribution abuse because a planted session without follow-up observation is only a probe.
- **Data observation**: observe victim-entered data that lands in the attacker-visible account after planting.
- **Action attribution**: attribute later victim actions to the planted account for fraud or audit-confusion chaining.
- **Authorization-sibling chaining**: force actions on other users records once the planted session gains its expected authorizations through the authorization sibling.
- **Forced-authorization chaining**: chain forced authorization navigations that bind the planted session to unintended clients.

## Testing Methodology

Planting runs inventory first and clear-then-plant second, because no planting is meaningful without a fixation-capable map.
1. **Inventory endpoints** - list every login plus logout plus credential-change plus account-linking flow with its trigger shape, and the step completes when no unlisted fixation-capable flow remains.
2. **Map planting reachability** - record cross-origin triggering plus logout clearing behavior per flow, and the step completes when every flow carries a plantable or refused verdict.
3. **Assess session and defenses** - record cookie session behavior plus token presence plus origin or referrer enforcement per login path, and the step completes when every login path carries a complete defense record.
4. **Force logout clearing** - deliver the cross-site logout trigger and record proof-of-intent reset, and the step completes when every targeted flow shows a cleared or uncleared verdict.
5. **Plant attacker credentials** - deliver the cross-site login-shaped request with observable credentials, and the step completes when every planting shows an accepted or refused verdict.
6. **Confirm account identity** - compare account identity before planting plus after planting plus after a subsequent action, and the step completes when every planting shows an identity verdict proving victim-in-attacker-account or no fixation.

## False Positives

- **Stop condition**: stop when the evidence shows the victim browser never enters the attacker account, because login reachability without identity change is only noise.
- **Enforced defenses**: enforced per-request token plus consistent origin or referrer checks on login paths confirmed by uniform refusals.
- **Intact token state**: no logout clearing occurs, confirmed by intact proof-of-intent state after the forced logout probe.
- **Bound planting**: planting rejected or bound to the existing victim identity, confirmed by unchanged account identity after the sequence.
- **Absent session change**: no cookie session plants, confirmed by absent session authority change in the delivered sequence.
- **No identity change**: identity comparison showing no victim-in-attacker-account state after every chained sequence.

## Pro Tips

- **Planting discipline**: planting rewards sequence patience plus observable credentials plus identity-exact confirmation.
- **Logout probe first**: prefer the logout probe first, then promote only clearing flows to full planting.
- **Observable credentials**: favor tester-observable credentials so post-plant attribution stays provable.
- **Thin-check targets**: probe credential-change plus account-linking flows early, because planting checks are thinnest there.
- **Identity-point confirmation**: confirm every success through account-identity comparison across three points rather than through a single response.
- **Reproduction record**: record the clearing plus planting values per success so the finding reproduces exactly.

## Summary

A login flow that clears on forced logout and plants attacker credentials cross-origin reverses the session direction.
Clear-then-plant sequencing plus identity comparison proves fixation before any capture or attribution chaining follows.
