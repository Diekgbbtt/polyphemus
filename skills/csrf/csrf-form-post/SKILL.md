---
name: csrf-form-post
description: Deliver preflightless cross-site form POSTs that replay endpoint semantics, confirm per-endpoint encoding acceptance when simple requests reach state changes, and forge storage or admin actions when multipart shapes succeed.
metadata:
  version: 1.0.0
---

# CSRF Form Post

State-changing endpoints that accept simple cross-origin encodings execute on cookie authority alone.
This variant delivers per-endpoint preflightless POSTs and confirms the storage or action effect.
The confirmation goal is replayed semantics under the victim session that later enables authorization or workflow chaining.

## Attack Surface

- **Applicability**: centers on a state-changing endpoint that accepts at least one simple cross-origin encoding without a non-replayable proof of intent.
- **Ambient authority**: the endpoint carries cookie-based ambient authority with a session that travels on cross-site requests.
- **Request shape**: a single preflightless POST emitted from an attacker page, including form plus multipart plus plain-text encoding families.
- **Out-of-scope transports**: encoded query payloads plus semantic reconstruction plus socket transports ride outside this variant in their sibling variants.
- **File and action endpoints**: belong here when they accept the same simple POST shape with only an encoding change.

## Reconnaissance

### Session and Encoding Reachability

- **Session-scope recording**: record cookie session behavior plus cross-site sending scope per endpoint.
- **Encoding-acceptance recording**: record method plus encoding acceptance per endpoint, noting which simple encoding reaches the state change.
- **Multipart-target recording**: record multipart-reachable storage or file-action endpoints separately, because their effect confirmation differs.

### Defense Presence

- **Proof-of-intent checks**: locate proof-of-intent checks such as per-request tokens plus origin or referrer enforcement.
- **Token-behavior recording**: record missing plus reusable plus untied token behavior for the defeat sub-step.
- **Header-acceptance recording**: record null plus missing plus cross-origin header acceptance for the defeat sub-step.

## Detection Channels

- **Live channels**: delivery replays identical semantics.
- **Before-versus-after state comparison**: showing the intended effect without a proof of intent.
- **Per-endpoint encoding acceptance**: showing which simple encoding family succeeds per endpoint.
- **Storage-effect signal**: showing created plus modified plus deleted records after a multipart delivery.
- **Missing-token acceptance**: showing the state change proceeds without the expected token.
- **Null-origin acceptance**: showing the state change proceeds from an empty-context delivery.

## Adversarial Capabilities

- **Replay prerequisites**: lure plus form construction plus effect comparison, which the variant consumes.
- **Victim lure**: lure the victim to an attacker-controlled cross-origin page with no script execution in the target origin.
- **Form construction**: construct an auto-submitting form that emits one chosen simple encoding per attempt.
- **Encoding variation**: vary the encoding family per endpoint until the acceptance shape is found.
- **Effect comparison**: compare before-versus-after application state to confirm storage or action effects.
- **Defeat operation**: operate the defeat sub-step by removing or reusing tokens and by presenting empty-context origins.

## Trust Assumptions

- **The agreement**: the state-changing feature trusts a cookie-authenticated cross-origin request to carry genuine user intent, holds the session cookie stable as ambient authority, holds the endpoint in its intended state-change shape, holds the request in its declared method plus encoding shape, holds a non-replayable proof of intent enforced, holds the transport in single-request HTTP shape with victim-session direction, and changes sensitive account plus storage plus action state only through intended effects under the victim session.
- **The failing clause**: this variant breaks the simple-encoding acceptance clause because the endpoint accepts a preflightless encoding that an attacker page can emit cross-origin, so intent is decided by cookie presence alone.

## Key Vulnerabilities

### Per-Endpoint Encoding Delivery

- **Per-endpoint encoding delivery**: deliver one simple encoding per attempt and record which family the endpoint accepts, because acceptance diverges per endpoint.
- **Encoding-family separation**: treat form plus multipart plus plain-text families as distinct attempts rather than interchangeable aliases.
- **Encoding-choice ownership**: the parent delivery step covers only flat preflightless attempt and cannot describe per-endpoint encoding choice, so this variant owns the encode-per-endpoint procedure.

### Storage and Admin Action Forgery

- **Multipart-shaped forging**: forge multipart-shaped requests against file plus storage plus administrative action endpoints that skipped token checks.
- **Effect confirmation**: confirm the effect through record creation plus modification plus deletion rather than through response text alone.
- **Confirm-after-write ownership**: the parent delivery step never names storage-effect confirmation, so this variant owns the confirm-after-write procedure.

### Simple Replay Without Transformation

- **Identical-semantics replay**: replay identical field semantics in the preflightless body with no key restructuring and no method coercion.
- **Transformation exclusion**: keep transformed semantics outside this variant, because reconstruction belongs to the parser-differential sibling.
- **Disjointness boundary**: preserving identical semantics is the disjointness boundary that keeps this variant separate from that sibling.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no value difference changes the replay step itself.
- **Token-value steering**: token absence plus cross-request reuse plus cross-session reuse plus untied scope steer the replay past a weak proof-of-intent check.
- **Header-value steering**: null plus missing plus cross-origin header values steer the replay past a weak origin or referrer check.
- **Encoding-family switching**: encoding-family switching reaches different server code paths while the replay semantics stay identical.
- **Referrer stripping**: referrer stripping through an empty-context navigation source presents the replay without its origin context.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Forward chaining scope**: replay chains forward into authorization and workflow abuse because a bare state change without a follow-up goal is only a probe.
- **Authorization-sibling chaining**: force actions on other users records once reference values are known through the authorization sibling.
- **Visual-overlay chaining**: guide confirmation-step clicks through visual overlay chaining where a confirmation blocks the replay.
- **Forced-authorization chaining**: chain forced authorization navigations where an authorization flow entry accepts the same simple POST shape.
- **Storage-forgery entry**: treat a successful storage forgery as the entry into later retrieval or execution chaining.

## Testing Methodology

Replay runs inventory first and encoding choice second, because no delivery is meaningful without a per-endpoint map.
1. **Inventory endpoints** - list every state-changing endpoint including storage plus file plus administrative actions with its carrier, and the step completes when no unlisted state-changing endpoint remains.
2. **Map encoding acceptance** - record method plus encoding reachability per endpoint across the simple encoding families, and the step completes when every endpoint carries an accepted or refused verdict per family.
3. **Assess session and defenses** - record cookie sending scope plus token presence plus origin or referrer enforcement per endpoint, and the step completes when every endpoint carries a complete defense record.
4. **Deliver per-endpoint replay** - emit one auto-submitting cross-origin POST per encoding per endpoint, and the step completes when every delivery shows a recorded state-effect verdict.
5. **Confirm storage or action effect** - compare before-versus-after records for storage plus file plus administrative actions, and the step completes when every successful delivery shows a confirmed effect rather than a response-only signal.
6. **Confirm defeat value** - repeat successes with removed plus reused tokens and with empty-context origins, and the step completes when every success carries its defeating value record.

## False Positives

- **Stop condition**: stop when the evidence shows the replay never executes as a state change, because response similarity without effect is only noise.
- **Enforced defenses**: enforced per-request token plus consistent origin or referrer checks confirmed by uniform refusals.
- **Absent cookie authority**: no cookie travels on cross-site requests, confirmed by absent session authority in the delivered request.
- **Idempotent-only responses**: only idempotent or non-sensitive operations respond, with no storage plus file plus administrative effect.
- **Uniform encoding negatives**: uniform negatives across every encoding family, which signal genuine enforcement rather than a missed encoding.
- **No state difference**: state comparison showing no before-versus-after difference after every delivery shape.

## Pro Tips

- **Replay discipline**: replay rewards per-endpoint patience plus tiny probes plus explicit confirmation.
- **Smallest probe first**: prefer the smallest state-changing probe first, then promote only confirmed endpoints to storage or administrative forgery.
- **One encoding per attempt**: favor one encoding per attempt so acceptance attribution stays exact per endpoint.
- **Thin-check targets**: probe storage plus file plus administrative actions early, because token checks are thinnest there.
- **State-based confirmation**: confirm every success through before-versus-after state rather than through response text.
- **Defeating-value record**: record the defeating token plus origin value per success so the finding reproduces exactly.

## Summary

An endpoint that accepts a simple cross-origin encoding on cookie authority alone replays attacker-chosen semantics.
Per-endpoint delivery plus storage-effect confirmation proves the replay before any authorization or workflow chaining follows.
