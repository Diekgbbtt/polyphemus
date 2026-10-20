---
name: csrf-websocket-handshake
description: Open authenticated cross-site socket handshakes that rely on origin checks alone, confirm handshake acceptance when cookies travel on upgrade, and issue over-socket actions when the channel stays authorized.
metadata:
  version: 1.0.0
---

# CSRF Websocket Handshake

Socket handshakes that carry cookies and rely on origin checks alone open authenticated channels from an attacker page.
This variant opens the cross-site handshake absent origin enforcement then issues actions over the socket.
The confirmation goal is two-phase transport abuse under the victim session that later enables messaging or action chaining.

## Attack Surface

- **Applicability**: centers on a socket handshake endpoint that carries cookies and relies on an origin check without a non-replayable proof of intent.
- **Ambient authority**: the endpoint carries cookie-based ambient authority with a session that travels on the upgrade request.
- **Request shape**: a two-phase transport where the cross-site handshake opens the channel and subsequent socket messages cause actions.
- **Out-of-scope transports**: single-request replay plus navigation triggering plus semantic reconstruction plus fixation sequencing ride outside this variant in their sibling variants.
- **Over-socket flows**: belong here when they inherit the handshake authority.

## Reconnaissance

### Handshake and Channel Reachability

- **Handshake-endpoint recording**: record handshake endpoints that accept cross-origin upgrade with cookie authority.
- **Origin-check recording**: record origin-check behavior per handshake, noting absent plus permissive plus unenforced cases.
- **Over-socket shape recording**: record over-socket message plus action shapes separately, because their confirmation differs from the handshake itself.

### Defense Presence

- **Proof-of-intent checks**: locate proof-of-intent checks such as per-request tokens plus origin enforcement on handshake paths.
- **Token-and-authorization recording**: record handshake token presence plus per-message authorization for the defeat sub-step.
- **Header-acceptance recording**: record null plus missing plus cross-origin header acceptance for the defeat sub-step.

## Detection Channels

- **Live channels**: two-phase transport succeeds across two observations.
- **Handshake-acceptance signal**: showing the cross-site upgrade opened an authenticated channel.
- **Over-socket action effect**: showing a subsequent socket message caused the intended state change.
- **Origin-check outcome**: showing absent plus permissive acceptance on the handshake path.
- **Cookie-travel observation**: showing the session traveled on the upgrade request.
- **Missing-token acceptance**: showing the handshake proceeds without the expected token.

## Adversarial Capabilities

- **Two-phase prerequisites**: lure plus handshake construction plus channel operation, which the variant consumes.
- **Victim lure**: lure the victim to an attacker-controlled cross-origin page with no script execution in the target origin.
- **Handshake construction**: construct a cross-site handshake request that carries the victim cookie authority.
- **Channel operation**: operate the opened channel by issuing message plus action frames over the socket.
- **State comparison**: compare before-versus-after application state to confirm over-socket effects.
- **Defeat operation**: operate the defeat sub-step by removing tokens and by presenting empty-context handshakes.

## Trust Assumptions

- **The agreement**: the state-changing feature trusts a cookie-authenticated cross-origin request to carry genuine user intent, holds the session cookie stable as ambient authority, holds the endpoint in its intended state-change shape, holds the request in its declared method plus encoding shape, holds a non-replayable proof of intent enforced, holds the transport in single-request HTTP shape with victim-session direction, and changes sensitive account plus storage plus action state only through intended effects under the victim session.
- **The failing clause**: this variant breaks the transport-shape clause because the handshake accepts a cross-site socket upgrade on cookie authority alone, so actions move over the socket without per-request proof.

## Key Vulnerabilities

### Cross-Site Handshake Opening

- **Cross-site handshake opening**: open an authenticated socket through a cross-origin handshake that presents victim cookie authority without origin enforcement.
- **Channel confirmation**: confirm the channel through a handshake-accepted signal rather than through a single HTTP state effect, because the handshake alone causes no application action yet.
- **Handshake-opening ownership**: the parent single-request steps cover only one POST plus one GET and cannot describe two-phase socket transport, so this variant owns the handshake-opening procedure.

### Over-Socket Action Issuing

- **Over-socket action issuing**: issue action messages over the opened channel and confirm each through its application effect.
- **Ordered-transport discipline**: treat handshake plus messaging as one ordered transport rather than two independent probes, because messaging without an authenticated channel cannot be attributed.
- **Issue-over-channel ownership**: neither parent delivery step names over-socket messaging, so this variant owns the issue-over-channel procedure.

### Channel-Authorized Flow Abuse

- **Channel-authorized flow abuse**: abuse message plus action plus subscription flows that inherit handshake authority without per-message proof of intent.
- **Replay exclusion**: keep single-request replay outside this variant, because channel abuse completes over the socket rather than through a fresh HTTP request.
- **Aspect containment**: these flows stay aspects inside this variant because the transport covers them with a message-shape parameter and no new handshake is needed.

## Bypass Techniques

- **Bypass scope**: bypass forms stay aspects inside this variant because no value difference changes the two-phase step itself.
- **Token-gap steering**: token absence plus handshake-scoped token gaps steer the upgrade past a weak proof-of-intent check.
- **Header-value steering**: null plus missing plus cross-origin header values steer the handshake past a weak origin check.
- **Upgrade-shape steering**: upgrade-shape reliance steers the request through a path whose checks differ from plain HTTP paths.
- **Referrer stripping**: referrer stripping through an empty-context navigation source presents the handshake without its origin context.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Forward chaining scope**: socket abuse chains forward into messaging and action abuse because an open channel without a follow-up action is only a probe.
- **Messaging-action chaining**: issue messaging actions that mutate state under the victim session once the channel opens.
- **Authorization-sibling chaining**: force actions on other users records once reference values are known through the authorization sibling.
- **Forced-authorization chaining**: chain forced authorization navigations where a session-bound channel amplifies the authorization effect.
- **Over-socket entry**: treat a successful over-socket action as the entry into subscription or notification chaining.

## Testing Methodology

Two-phase abuse runs inventory first and handshake-then-act second, because no socket action is meaningful without an authenticated channel.
1. **Inventory endpoints** - list every handshake endpoint plus its over-socket message plus action shapes, and the step completes when no unlisted handshake or channel shape remains.
2. **Map handshake reachability** - record cross-origin upgrade acceptance plus cookie travel plus origin-check behavior per handshake, and the step completes when every handshake carries an accepted or refused verdict.
3. **Assess session and defenses** - record cookie session behavior plus token presence plus origin enforcement per handshake path, and the step completes when every handshake path carries a complete defense record.
4. **Open cross-site handshake** - deliver the handshake from a cross-origin page and record channel establishment, and the step completes when every handshake shows an opened or refused verdict.
5. **Issue over-socket actions** - send action messages over each opened channel and compare before-versus-after state, and the step completes when every message shows a recorded effect verdict.
6. **Confirm defeat value** - repeat successes with removed tokens and with empty-context handshakes, and the step completes when every success carries its defeating value record.

## False Positives

- **Stop condition**: stop when the evidence shows no authenticated channel opens cross-origin, because HTTP reachability without a socket is only noise.
- **Enforced defenses**: enforced origin check plus handshake token requirement confirmed by uniform handshake refusals.
- **Absent session authority**: no cookie travels on the upgrade, confirmed by absent session authority in the handshake request.
- **Per-message authorization**: per-message authorization requires fresh proof of intent, confirmed by refused over-socket actions despite an open channel.
- **Read-only responses**: only non-sensitive or read-only channel messages respond, with no state-changing effect.
- **No state difference**: state comparison showing no before-versus-after difference after every over-socket message.

## Pro Tips

- **Two-phase discipline**: two-phase abuse rewards handshake patience plus channel reuse plus effect-exact confirmation.
- **Handshake probe first**: prefer the handshake probe first, then promote only opened channels to action messaging.
- **One message shape per attempt**: favor one message shape per attempt so over-socket attribution stays exact per flow.
- **Thin-check targets**: probe message plus subscription flows early, because per-message checks are thinnest there.
- **State-based confirmation**: confirm every success through before-versus-after state rather than through channel-open status alone.
- **Reproduction record**: record the handshake acceptance plus the defeating value per success so the finding reproduces exactly.

## Summary

A handshake that upgrades cross-origin on cookie authority alone opens an authenticated channel without intent proof.
Handshake opening plus over-socket confirmation proves the transport abuse before any messaging or action chaining follows.
