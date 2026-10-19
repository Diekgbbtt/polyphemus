---
name: oauth-state-nonce-csrf
description: Freshness binding gaps enable login CSRF and replay. Use when grant flows start without a freshness token; when a token is accepted across sessions or requests; when identity-token freshness values replay without effect.
metadata:
  version: 1.0.0
---

# State and Nonce CSRF

Freshness tokens bind a grant response to the session that requested it.
This variant proves the binding is missing or loose by running binding-scope plus reuse-oracle plus replay confirmation.
The theft goal is a victim session fixed to an attacker-chosen grant or a replayed identity assertion the server still honors.

## Attack Surface

- **Applicability**: centers on a grant flow whose authorization entry point issues a per-request freshness token and whose identity layer attaches a single-use freshness value to each identity assertion.
- **Binding scope**: the client session, the freshness token, and the single-use verifier form the binding scope the server must join at redemption.
- **In-scope flows**: flows without any freshness carrier and flows with an identity assertion that must bind its own freshness value both sit inside this variant.
- **Token-format mutation**: stays out and is consumed from the token companion skill.

## Reconnaissance

- **Freshness mapping**: map the freshness surface before breaking it.
- **Carrier catalogue**: catalogue every client with the freshness carriers its authorization requests emit plus whether each carrier is mandatory, optional, or absent.
- **Baseline recording**: record the baseline behavior for a request started with no freshness carrier plus a request completed in a swapped session.
- **Completion criterion**: reconnaissance is complete when every client carries its carrier inventory plus its baseline no-carrier verdict.

## Detection Channels

- **Channel scope**: destination, verifier, binding, and approval signals belong to the sibling variants.
- **No-carrier acceptance**: a flow started without a freshness carrier still completes.
- **Cross-session completion**: a response minted for one session is redeemed in another.
- **Reuse-oracle acceptance**: a previously consumed freshness value succeeds a second time.
- **Scope-escape verdict**: a freshness token binds to no session or to the wrong verifier.
- **Identity-freshness replay**: an identity assertion with an injected or repeated freshness value is still honored.
- **Silent re-authentication**: a no-prompt authorization request completes inside a live victim session without an interaction, which signals a silent-auth path and a session-fixation precondition.

## Adversarial Capabilities

- **Prerequisites**: freshness probing presupposes session control plus request initiation plus response capture, and it consumes all three.
- **Carrier-shape requests**: initiate grant requests with the freshness carrier present, absent, and attacker-chosen to learn which shapes the server honors.
- **Two-session control**: hold two sessions at once so a response minted in one can be redeemed in the other.
- **Mid-flow swapping**: swap sessions mid-flow to test whether redemption checks the requesting session at all.
- **Response capture**: capture grant responses for later replay to build the reuse oracle.
- **Identity-value injection**: inject and replay identity-assertion freshness values to test the identity-layer check independently.

## Trust Assumptions

- **The agreement**: the callback destination, the freshness token, the single-use verifier, the client identity, and the token audience presented at each step belong to the same legitimate session and client, with each value checked at the step that consumes it.
- **The exposure**: sensitive account access leaks only when the server delivers grant credentials through such a checked chain.
- **The failing clause**: this variant breaks the freshness-binding clause because a response minted outside the redeeming session is honored as though it belonged to it.

## Key Vulnerabilities

### Binding-Scope Escape

- **Scope-escape sequence**: request with the freshness carrier removed, then with a carrier minted in a different session, then with a carrier joined to the wrong verifier, using shapes like `<absent-carrier>` plus `<foreign-session-carrier>` plus `<mismatched-verifier-carrier>`.
- **Scope verdict**: treat completion under any of these shapes as a scope escape and treat consistent refusal as a negative.
- **Scope ownership**: the parent probe step covers only carrier omission plus session swap and cannot describe verifier-scope joining, so this variant owns the scope procedure.

### Reuse-Oracle Sequencing

- **Reuse sequence**: redeem each captured response twice, then across sessions, recording one verdict per replay with shapes like `<first-redemption>` followed by `<second-redemption-same-value>`.
- **Reuse verdict**: treat a second success as a reuse finding and treat uniform single-use refusal as a negative.
- **Sequencing ownership**: the parent probe step never names ordered reuse oracles, so this variant owns the sequencing procedure.

### Identity-Freshness Injection and Replay

- **Injection sequence**: omit the identity-layer freshness value, then inject an attacker-chosen one, then replay a previously observed one.
- **Identity verdict**: treat acceptance of any of these shapes as an identity-binding failure.
- **Fixation parameter**: fixation-shaped login flows where the victim completes an attacker-initiated grant ride inside this variant, confirmed through the victim-session outcome rather than a separate procedure.

## Advanced Techniques

- **Account linking**: rides here as a secondary divergence rather than a separate variant.
- **Linkage sequence**: complete an attacker-initiated grant in the victim session without re-authentication and test whether the resulting account links the attacker identity to the victim profile.
- **Linkage verdict**: treat identity-collision outcomes such as same-address linkage across providers as confirmation of the same freshness finding.

## Bypass Techniques

- **Bypass scope**: bypass forms are the check values this variant defeats, each confirmed through completion rather than request shape alone.
- **Missing-carrier requests**: pass a check that treats the freshness token as advisory.
- **Attacker-chosen carriers**: pass a check that never joins the token to the server session.
- **Cross-session redemptions**: pass a check that reads the carrier without comparing sessions.
- **Reused carriers**: pass a check that never marks a value consumed.
- **Identity-freshness shapes**: omitted or replayed identity freshness passes a check that never validates the identity-layer value.

When this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Chain scope**: freshness findings chain forward into session impact because an unbound grant without a victim outcome is only a check gap.
- **Fixed-session handoff**: hand a fixed session to a victim lure so the victim completes the attacker-initiated grant and inherits the attacker binding.
- **Captured-response handoff**: hand a captured grant response to the binding companion where cross-client redemption widens the same response further.
- **Leakage amplifier**: treat log plus analytics leakage of grant responses as an amplifier that feeds the reuse oracle without new capture work.

## Testing Methodology

Freshness runs the bind-and-reuse oracle first and everything else follows, because no later claim is meaningful without a confirmed binding gap.
1. **Inventory carriers** - list every client with its freshness carriers plus their mandatory or optional status plus the baseline no-carrier verdict, and the step completes when no unlisted client or carrier remains.
2. **Probe binding scope** - redeem with absent plus foreign-session plus mismatched-verifier carriers over parent step P3, which names omission plus session swap but never names binding-scope escape plus reuse-oracle sequencing plus injection confirmation, and the step completes when every client carries a scope verdict per shape.
3. **Sequence the reuse oracle** - replay each captured response within and across sessions and record one verdict per replay, and the step completes when every capture shows single-use refusal or a documented reuse.
4. **Confirm identity freshness** - omit plus inject plus replay the identity-layer value and record each verdict, and the step completes when every shape shows refusal or a documented acceptance.
5. **Confirm victim outcome** - complete an attacker-initiated grant in a victim session and test linkage, and the step completes when each attempt shows fixation, linkage, or a documented refusal.

## False Positives

- **Check-held stop**: stop when the evidence shows the freshness check holds, because refused replays are only noise.
- **Carrier binding**: carrier enforced and bound to the requesting session with cross-session completion refused.
- **Single-use enforcement**: every replay refused and logged as consumed.
- **Identity-layer validation**: omission plus injection plus replay all refused.
- **Fixation failures**: fixation attempts that fail because the server re-issues the binding at login.

## Pro Tips

- **Discipline**: freshness rewards two sessions plus ordered replays plus quiet logging.
- **Session pre-holding**: hold both sessions open before initiating anything so swaps and replays stay clean.
- **Ordered replay**: replay each capture exactly once more before varying anything else, and log every verdict behind its capture.
- **Scope-first ordering**: test carrier scope before identity freshness so the simpler gap names itself first.
- **Cross-step comparison**: compare authorize-step and redemption-step carrier values on every attempt.
- **Refusal recording**: stop promoting refused replays and record them as refusals rather than inconclusive.

## Tooling

- **Manual chain driving**: drive the grant chain by hand so every freshness value stays under tester control.
- **Local identity decoding**: decode arriving identity assertions locally to confirm which freshness value each response actually carried before replaying it.

## Summary

A freshness token that binds to nothing lets the attacker fix or replay another session grant.
Freshness probing scopes each binding, oracles each reuse, and confirms each victim outcome before claiming impact.
