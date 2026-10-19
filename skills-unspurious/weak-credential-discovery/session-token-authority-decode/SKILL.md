---
name: session-token-authority-decode
description: Decode issued session tokens plus stored values for authority claims when login returns a readable holder, when cookies carry identity fields, and when storage values expose role markers.
metadata:
  version: 1.0.0
---

# Session Token Authority Decode

Authenticated sessions sometimes carry their own authority in a client-readable holder.
This variant converts issued tokens plus cookies plus stored values into identity and role knowledge through one session-gated split-decode-interpret procedure.
The decode goal is authority discovery that guides follow-on authorization testing without defeating any signature.

## Attack Surface

Applicability centers on an authenticated session that issues a client-readable token or cookie or stored value.
The holder carries identity or role claims in a splittable plus decodable shape.
The decode step gates on a held session, because no unauthenticated fetch can produce the holder.
Linked source plus guessed artifacts plus replay success plus identity oracles ride outside this variant and belong to its siblings.

## Reconnaissance

Reconnaissance inventories issued holders after authentication before any decoding begins.
Authenticate once through a confirmed credential and record every issued holder, namely cookies plus tokens plus stored values plus hidden identity fields.
Record each holder carrier plus its encoding shape with placeholders so the split step knows where to cut.
Note which holders look opaque versus structured, because only structured holders proceed to interpretation.

## Detection Channels

Decoding listens to holder content only, so only the entries below are live here.
Claim in this variant means an interpreted identity or role marker, not a validated permission.
- Decoded identity marker from a token or cookie or stored value signals authority knowledge.
- Decoded role marker from a token or cookie or stored value signals authority knowledge.
- Structured holder shape that splits plus decodes cleanly signals a readable authority carrier.

## Adversarial Capabilities

Decoding presupposes a held authenticated session plus local split plus decode plus interpretation, and it consumes all four.
Hold one authenticated session obtained through an earlier success, because the holder exists only after login.
Supply no further unauthenticated probes, because the holder is already in hand.
Split each holder into its segments plus restore padding plus decode the readable segment locally.
Interpret the decoded fields as identity plus role claims that guide follow-on testing.

## Trust Assumptions

At the moment the authentication feature executes, the application agrees that served content carries no reusable secret, deployable artifacts stay unreachable over guessable paths, published default pairs grant no access, login responses stay uniform across identities, and issued tokens disclose no authority.
The request uses only ordinary fetch plus submit primitives with unauthenticated or session-held capability, and the server exposes only non-sensitive renderings plus uniform outcomes.
A reusable credential or an identity oracle or an authority claim leaks only through an explicit grant, never through side content or response shape.
This variant fails the token-disclosure clause because an issued token or stored value discloses authority claims under a held session.

## Key Vulnerabilities

### Session-Gated Split-Decode-Interpret

Split each issued holder into segments plus restore padding plus decode the readable segment plus interpret identity and role claims in one procedure.
Gate the whole procedure on the held session, because the holder materializes only after authentication.
The parent names this decode-and-interpret loop in exactly one step, and no unauthenticated step covers session-gated splitting plus decoding, so this variant owns the decode procedure.

### Claim Interpretation

Read decoded fields as identity plus role markers that map the authorization surface for follow-on testing.
Treat readable claims as discovery rather than proof, because signature validation belongs to authentication-jwt and is named there instead of restated here.
Record token signing state as a secondary check inside interpretation, because signing rides as an aspect rather than its own bypass procedure.
Fingerprint the algorithm that protects each holder at the decode step and hand the entropy and re-derivation questions to `crypto-weakness` and its `crypto-predictable-token` leaf, because a readable holder still decides nothing about its own strength.

## Chaining Attacks

Decoding chains forward into authorization testing because a claim without reuse is only knowledge.
Hand each decoded identity plus role marker to follow-on authorization testing for privilege mapping.
Hand each structured holder shape to token-validation review through authentication-jwt where signature questions belong.
Treat replay plus oracle siblings as feeders into this variant, because their sessions produce the holders decoded here.

## Testing Methodology

Decoding runs session capture first and claim mapping last, because no interpretation is meaningful without a held holder.
1. **Capture issued holders** - authenticate once and record every issued cookie plus token plus stored value, and the step completes when every post-login artifact carries a captured or absent verdict.
2. **Execute split-decode-interpret** - split each holder plus restore padding plus decode the readable segment plus interpret identity and role fields, and the step completes when every holder carries a decoded-claims or opaque verdict.
3. **Map authority markers** - consolidate decoded identity plus role markers into one claim set, and the step completes when every decoded holder contributes its markers to the set or is recorded as marker-free.
4. **Confirm follow-on relevance** - match each marker against authorization-relevant behavior, and the step completes when every marker carries a chaining-useful or informational verdict.
5. **Record signing state** - note whether each holder carries integrity protection as a secondary check, and the step completes when every holder carries a signed-or-readable note without expanding into validation bypass.

## False Positives

Stop when the holder carries no authority, because an opaque or marker-free value offers no discovery.
- Opaque session identifiers with no decodable structure, confirmed when splitting plus decoding yields no fields.
- Owner-only display details with no reuse across calls, confirmed when markers never influence authorization behavior.
- Example claims in documentation samples that never issue from the live acceptor, confirmed by absence from captured holders.

## Pro Tips

Decoding rewards one clean session plus holder-specific splitting.
1. Prefer decoding every issued holder after login, because the auth model hides in the full set rather than one cookie.
2. Favor split plus padding restoration before decoding, so each holder parses on the first attempt.
3. Treat readable claims as discovery for authorization mapping rather than as validation proof.
4. Name token-validation questions to authentication-jwt instead of expanding this variant into signature bypass.

## Summary

An issued token that discloses identity plus role already mapped the authorization surface for whoever decodes it.
Decoding captures every holder under one held session, splits plus decodes plus interprets each claim set, and hands the markers to authorization testing before any validation question follows.
