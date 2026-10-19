---
name: proxy-techniques-relay-forwarding
description: Relay-field forwarding where an intermediary supplies the authority, the client address, the scheme, or the destination and the origin trusts it, covering forwarded-value trust when a supplied value is read as the origin's own observation, construction decisions when the supplied value reaches a link or an identity document, field family spraying when several names carry one value, and relay rewrite when a supplied override reaches a decision made earlier.
metadata:
  version: 1.0.0
---

# Relay Forwarding

An intermediary adds its own fields to a request, and the origin reads those fields as its own observation of the connection. This variant supplies the authority, the client address, the scheme, or the destination through the relay's fields and reads whether the origin trusts them. The goal is a decision made on a value the caller supplied, proved by the effect the decision produces.

## Attack Surface

- **Applicability**: centers on a path that carries an intermediary between the caller and the origin, with fields the intermediary sets or forwards.
- **Surface composition**: authority and forwarding fields, client-address fields, scheme and protocol fields, and rewrite or override fields that reach a decision made before them.
- **Widening factors**: a relay that forwards caller-supplied values unchanged, and an origin that reads those fields without a boundary check, both widen the surface.
- **Out-of-scope variant**: a path with no intermediary rides outside this variant, because there is no relay field to supply.

## Reconnaissance

- **Reconnaissance scope**: relay forwarding maps the fields before crafting, because the mechanism is a value the origin reads as its own.
- **Field list**: list the fields the relay sets or forwards, and record which origin decision each one reaches.
- **Refusal baseline**: establish the refusal baseline with a plainly external value the origin rejects, so a later effect is attributable to the supplied field.
- **Field family probing**: probe one field family per attempt, because each layer on the path may read a different name for the same value.
- **Construction decisions**: note whether the origin constructs links, messages, or allowlist decisions from a forwarded value, since those are the decisions the field reaches.

## Detection Channels

- **Channel scope**: relay forwarding listens to the origin's decision on a supplied value, so only the entries below are live here.
- **Origin action**: the origin acting on a value the caller supplied through the relay's own fields.
- **Reflection without decision**: a reflected supplied value that reached no decision, because a reflection alone is not trust; require the origin's effect or an out-of-band callback before claiming it.
- **Intermediary arrival**: an arrival whose source is the intermediary rather than the caller, which separates a relay effect from a client-side request.
- **Paired baseline**: a paired baseline where the same request differs only by the relay field it carries.
- **Built artefact**: a message or link the origin built from a forwarded value, which proves the value reached a construction decision.
- **Ignored fields**: a negative that holds across every field family, which reads as an origin that ignores relay-supplied values.

## Adversarial Capabilities

- **Prerequisites**: relay forwarding presupposes a field inventory plus request-shaping freedom plus an effect read, and it consumes all three.
- **One family per attempt**: supply one relay field family per attempt, keeping the request otherwise identical.
- **Separate reading**: read the origin's decision separately from the relay's own answer, because the relay answers before the origin does.
- **Boundary-rejected value**: hold a value that a boundary check would reject, so the effect proves the check read the relay field.
- **Family repetition**: repeat across field families, because a layer may read one name while the next reads another.

## Trust Assumptions

- **The agreement**: the origin trusts that the values it reads as its own observation were set by the component that terminates the connection, holds the authority to the address the connection used, holds the client address to the peer that connected, holds the scheme to the transport in use, and holds a rewrite field to a decision made after it.
- **The failing clause**: this variant breaks the relay-field clause because a value the caller supplied reaches the origin through the relay's own fields, so a decision is made on an observation the caller authored.
- **Claim discipline**: the effect is claimed only when the origin's decision is read, because the relay's own answer names only the relay.

## Key Vulnerabilities

### Forwarded-Value Trust

- **Forwarded-value supply**: supply the authority, the client address, or the scheme through the relay's fields, and read whether the origin uses the supplied value where it should use its own observation.
- **Layer separation**: separate the two layers before composing anything: an authority field that selects the upstream produces a routing effect, while a path-override field that restates the routed path produces a rewrite effect, and the two act at different layers and never compose into one request, so each is probed alone.
- **Construction decisions**: the construction decisions a supplied value reaches are the artefacts the origin builds: a recovery or invitation link, a canonical or share URL, and an identity document's issuer or discovery value, each carrying the supplied value to a consumer that trusts it.
- **Accounting and permit trust**: a rate limiter or an allowlist that reads a client-supplied source field makes its decision on an observation the caller authored, which is the same trust at an accounting or permit step.
- **Parser split**: a trailing port or a userinfo split resolves the supplied value to the approved host on one reader and to another on the second; name `proxy-techniques-url-parser-differential` at that step.
- **Blind proof**: where the response reflects nothing, prove the origin resolved the supplied value with an out-of-band fetch of the supplied host, because a blind case carries no reflection to read.
- **Direct decision**: prefer the decision the value reaches directly, such as an allowlist, a secure-transport check, or a link the origin builds.
- **Ownership**: the parent path-mapping step covers what a hop forwards and cannot describe an origin that trusts the forwarded value, so this variant owns the forwarded-value procedure.

### Field Family Spraying

- **Value spraying**: send the same value under each name the path might read, because every layer may key on a different field for one meaning.
- **Duplicate precedence**: where two occurrences of the same authority field are accepted, the second occurrence's precedence is a parser-confusion instance; name `defence-bypass-parser-confusion` at that step.
- **Identical value**: keep the value identical across families so the field is the only changed variable.
- **Ignored family**: treat a family the origin ignores as a recorded negative rather than a dead end, and move to the next name.
- **Forwarded field families**: see `references/forwarded-field-families.md` for the field families by role and the layer each acts at; the same-named note under the `header-injection` class keeps the per-family consumer map and the probe discipline for the class-side handoffs.

### Relay Rewrite and Override

- **Relay rewrite**: reach a decision that was made before the relay's rewrite, because an override field honored after a check defeats the check without touching the request it evaluated.
- **Decision position**: confirm the decision's position relative to the rewrite, since a rewrite after the decision carries no leverage.
- **Early rewrite**: treat a rewrite the origin applies before its decision as a recorded negative.

## Bypass Techniques

- **Bypass scope**: relay shapes are tried only after the direct route is baselined, because an origin that reads its own observation carried nothing.
- **Authority value**: an authority value supplied through the relay's own fields.
- **Construction value**: a supplied value that reaches a construction decision: a recovery or invitation link, a canonical or share URL, or an identity document's issuer or discovery value.
- **Source field**: a source field a limiter or an allowlist reads as the peer's own address.
- **Client-address value**: a client-address value that a boundary check reads as the peer.
- **Scheme value**: a scheme value that a transport check reads as the connection's.
- **Field spraying**: the same value sprayed across every field family the path may read.
- **Rewrite field**: a rewrite or override field that reaches a decision made before it.

## Chaining Attacks

- **Chain scope**: relay forwarding chains forward into the class that owns the effect, because a trusted field is only the first hop.
- **Effect hand-off**: hand the trusted value to the class that owns the effect, and prove the class-specific consequence there.
- **Parse-differential stack**: chain into the destination parse differential where the supplied value is also parsed differently per reader.
- **Tier-gap stack**: chain into the tier gap where the decision sits at one tier and the effect is served at another.
- **Own-step naming**: name the class at its own step rather than restating its procedure here.

## Testing Methodology

Relay forwarding inventories the fields first and supplies second, because the mechanism is a value the origin reads as its own.

1. **Inventory the relay fields** - every field the intermediary sets or forwards with the decision each one reaches, and the step completes when each field names its decision.
2. **Baseline the refusal** - send a plainly external value the origin rejects, and the step completes when a refusal is recorded or the absence of a boundary check is recorded with the test that showed it.
3. **Supply one family** - send the value under one field family per attempt, and the step completes when each family carries an effect or a recorded negative.
4. **Read the decision** - record what the origin did with the supplied value, and the step completes when the decision is attributed to the field rather than to the request body.
5. **Probe the rewrite position** - place an override before and after the decision in turn, and the step completes when the position that carries leverage is named.
6. **Attribute the trust** - pair the refused external value with the supplied one, and the step completes when the field the origin trusted is named from the pair.

## False Positives

- **Stop condition**: stop when the origin used its own observation, because an ignored field carried nothing.
- **Own-observation origin**: an origin that reads its own connection values, confirmed by a refusal for every field family.
- **Value-replacing relay**: a relay that replaces caller-supplied values with its own before forwarding.
- **Undecided value**: a value that reached no decision at all, where the field arrived and the origin never used it.
- **Tester-side arrival**: an arrival whose source is the tester's client rather than the relay.
- **Simulator**: a simulator that answers the relay's own fields without reaching the origin.

## Pro Tips

- **Discipline**: relay forwarding rewards field inventory plus one family per attempt.
- **Field inventory**: inventory the relay fields before crafting, because each layer may read a different name.
- **One family per attempt**: supply one family per attempt so the trusted field is nameable.
- **Separate reading**: read the origin's decision separately from the relay's answer, since the relay answers first.
- **Value spraying**: spray the same value across families rather than guessing the one the origin reads.
- **Effect hand-off**: hand the trusted value to the class that owns the effect, and stop at the narrowest proof.

## Summary

An intermediary supplies fields that the origin reads as its own observation. Relay forwarding inventories the field families, supplies one per attempt, and claims the effect only when the origin's decision is read.
