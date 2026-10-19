---
name: exposed-secret-extraction
description: Extract reusable secrets from served source plus guessed deployable paths when pages embed credential shapes, when scripts carry encoded holders, and when config artifacts answer over guessable locations.
metadata:
  version: 1.0.0
---

# Exposed Secret Extraction

Weak credential discovery often starts with a secret the application already served to an anonymous fetcher.
This variant converts linked pages plus scripts plus guessed artifact paths into authentication through one unified single-response fetch-parse-triage procedure.
The extraction goal is a reusable credential that enables an authenticated session without submitting guesses to the login acceptor.

## Attack Surface

Applicability centers on served content plus deployable artifacts that carry a reusable credential holder.
The holder lives in rendered markup or in a linked script or in a credential-bearing artifact reachable over a guessable path.
The server answers each fetch with a single response whose body alone decides the outcome, with no comparison across responses required.
The login acceptor plus the identity oracle plus the issued token ride outside this variant and belong to its siblings.

## Reconnaissance

Reconnaissance inventories fetchable holders before any parsing begins.
List every rendered page plus every linked script reachable from anonymous navigation, and record each carrier for later shape matching.
List every guessable artifact location class that could carry credential holders, such as environment dumps plus configuration documents plus version-control remnants plus diagnostic pages plus build and bundle artifacts.
Treat build and bundle artifacts as holders in their own right: a published source map reconstructs the client source, an interface specification document enumerates routes, and an asset manifest or build-info file names further holders.
Record the response status plus body size for each candidate so later triage can separate holders from misses.

## Detection Channels

Extraction listens to single responses only, so only the entries below are live here.
Content in this variant means rendered markup plus linked scripts plus fetched artifact bodies.
- Secret-shape match inside fetched content signals a candidate reusable credential.
- Encoded-holder match inside fetched content signals a candidate that needs decoding before reuse.
- Success status plus body-size threshold on a guessed artifact path signals a holder worth parsing.
- Parsed holder yielding a reusable pair or token confirms the extraction.
- A reconstructed source tree or an enumerated route set from a build or bundle artifact signals holders the served surface never named.

## Adversarial Capabilities

Extraction presupposes anonymous fetch plus local parse, and it consumes both.
Supply ordinary fetches against rendered pages plus linked scripts plus guessable artifact paths.
Hold no authenticated session, because every step runs before authentication.
Parse fetched bodies locally for secret shapes plus encoded holders plus structured credential fields.
Compare nothing across identities, because each response decides alone.

## Trust Assumptions

At the moment the authentication feature executes, the application agrees that served content carries no reusable secret, deployable artifacts stay unreachable over guessable paths, published default pairs grant no access, login responses stay uniform across identities, and issued tokens disclose no authority.
The request uses only ordinary fetch plus submit primitives with unauthenticated or session-held capability, and the server exposes only non-sensitive renderings plus uniform outcomes.
A reusable credential or an identity oracle or an authority claim leaks only through an explicit grant, never through side content or response shape.
This variant fails the served-content clause because a linked page or script or guessed artifact path carries a reusable secret.

## Key Vulnerabilities

### Unified Fetch-Parse-Triage

Fetch linked pages plus linked scripts plus guessed artifact paths through one procedure and parse each body for holders in the same pass.
Treat markup comments plus hidden fields plus inline configuration objects plus script-embedded holders plus artifact bodies as one holder family rather than separate techniques.
The parent names linked harvesting in one step and path guessing in another and never names them as one procedure, so this variant owns the unified pass.

### Holder-Specific Reading

Read each fetched body according to its holder shape, because one parser cannot cover markup plus script plus structured artifact output.
Match secret shapes in markup and scripts, decode encoded holders into candidate pairs, and parse structured artifact bodies into named credential fields.
See `references/secret-pattern-catalog.md` for the ordered shape rows, and run `scripts/secret-scan.py` over fetched bodies for one record per match.
Reconstruct source from a published source map and read an interface specification document for routes, because both are holders that name further secrets rather than secrets themselves.
Fingerprint the algorithm and entropy shape of any token-shaped holder at this step and hand the sampling and re-derivation questions to `crypto-weakness` and `crypto-predictable-token`, because a token that is not a fixed secret is judged by predictability rather than by pattern shape.
Record every match with its carrier plus its location so confirmation can replay the exact holder.

## Chaining Attacks

Extraction chains forward into authenticated testing because a holder without reuse is only discovery.
Hand each confirmed reusable credential to an authenticated session and continue into follow-on authorization testing.
Hand each confirmed pair to replay confirmation where the login acceptor decides success, and name token validation through authentication-jwt instead of restating it.
Treat enumerated holder shapes as aspects inside this variant rather than separate procedures.

## Testing Methodology

Extraction runs fetch first and reuse last, because no confirmation is meaningful without a parsed holder.
1. **Inventory linked holders** - fetch every rendered page plus every linked script and record each carrier, and the step completes when every reachable page plus every linked script carries a fetched-or-unreachable verdict.
2. **Probe guessed artifact paths** - request each guessable artifact location and record status plus body size, and the step completes when every guessed path carries a holder-candidate or ruled-out verdict.
3. **Execute unified fetch-parse-triage** - match secret shapes plus decode encoded holders plus parse structured bodies in one pass over all fetched content, and the step completes when every fetched body carries a match-recorded or no-holder verdict.
4. **Confirm reusability** - replay each candidate holder through its natural consumer such as a login acceptor or a credential-bearing request, and the step completes when every candidate carries a reusable or non-reusable verdict with its evidence.
5. **Rule out secondary holders** - recheck carriers that returned ambiguous bodies with holder-specific reading, and the step completes when no ambiguous body remains without a final verdict.

## False Positives

Stop when the holder cannot convert into authentication, because an unusable match is only noise.
- Intentional example credentials in documentation samples, confirmed by documentation context around the match.
- Owner-only details with no reuse path, confirmed when the holder grants no session and matches no acceptor.
- Unreachable banners that name a technology without exposing a holder, confirmed by absence of any credential field in the body.

## Pro Tips

Extraction rewards broad fetching plus holder-specific reading.
1. Prefer linked harvesting before path guessing, then promote only size-passing artifact bodies to parsing.
2. Favor shape matching across every carrier before confirming, so no holder family goes unchecked.
3. Record each match with its carrier plus location so confirmation replays the exact holder.
4. Treat ambiguous bodies as pending rather than negative and reread them with the matching holder parser.

## Summary

Served content that carries a reusable holder already surrendered the credential before any login guess.
Extraction fetches linked source plus guessed paths in one pass, parses each holder by its shape, and confirms reuse before any follow-on testing begins.
