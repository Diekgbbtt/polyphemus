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

- **Applicability**: centers on served content plus deployable artifacts that carry a reusable credential holder.
- **Holder**: lives in rendered markup or in a linked script or in a credential-bearing artifact reachable over a guessable path.
- **Single-response decision**: the server answers each fetch with a single response whose body alone decides the outcome, with no comparison across responses required.
- **Out-of-scope siblings**: the login acceptor plus the identity oracle plus the issued token ride outside this variant and belong to its siblings.

## Reconnaissance

- **Holder inventory**: reconnaissance inventories fetchable holders before any parsing begins.
- **Linked-source listing**: list every rendered page plus every linked script reachable from anonymous navigation, and record each carrier for later shape matching.
- **Artifact-class listing**: list every guessable artifact location class that could carry credential holders, such as environment dumps plus configuration documents plus version-control remnants plus diagnostic pages plus build and bundle artifacts.
- **Build and bundle artifacts**: treat build and bundle artifacts as holders in their own right: a published source map reconstructs the client source, an interface specification document enumerates routes, and an asset manifest or build-info file names further holders.
- **Response recording**: record the response status plus body size for each candidate so later triage can separate holders from misses.

## Detection Channels

- **Listening scope**: extraction listens to single responses only.
- **Content definition**: content in this variant means rendered markup plus linked scripts plus fetched artifact bodies.
- **Secret-shape match inside fetched content**: signals a candidate reusable credential.
- **Encoded-holder match inside fetched content**: signals a candidate that needs decoding before reuse.
- **Success status plus body-size threshold on a guessed artifact path**: signals a holder worth parsing.
- **Parsed holder**: confirms the extraction when it yields a reusable pair or token.
- **Reconstructed source or route set**: a reconstructed source tree or an enumerated route set from a build or bundle artifact signals holders the served surface never named.

## Adversarial Capabilities

- **Preconditions**: extraction presupposes anonymous fetch plus local parse, and it consumes both.
- **Fetch supply**: supply ordinary fetches against rendered pages plus linked scripts plus guessable artifact paths.
- **No prior session**: hold no authenticated session, because every step runs before authentication.
- **Local parsing**: parse fetched bodies locally for secret shapes plus encoded holders plus structured credential fields.
- **No cross-response comparison**: compare nothing across identities, because each response decides alone.

## Trust Assumptions

- **The agreement**: the application agrees that served content carries no reusable secret, deployable artifacts stay unreachable over guessable paths, published default pairs grant no access, login responses stay uniform across identities, and issued tokens disclose no authority, while the request uses only ordinary fetch plus submit primitives with unauthenticated or session-held capability, the server exposes only non-sensitive renderings plus uniform outcomes, and a reusable credential or an identity oracle or an authority claim leaks only through an explicit grant, never through side content or response shape.
- **The failing clause**: this variant fails the served-content clause because a linked page or script or guessed artifact path carries a reusable secret.

## Key Vulnerabilities

### Unified Fetch-Parse-Triage

- **Unified pass**: fetch linked pages plus linked scripts plus guessed artifact paths through one procedure and parse each body for holders in the same pass.
- **Holder family**: treat markup comments plus hidden fields plus inline configuration objects plus script-embedded holders plus artifact bodies as one holder family rather than separate techniques.
- **Ownership**: the parent names linked harvesting in one step and path guessing in another and never names them as one procedure, so this variant owns the unified pass.

### Holder-Specific Reading

- **Shape-directed reading**: read each fetched body according to its holder shape, because one parser cannot cover markup plus script plus structured artifact output.
- **Parser dispatch**: match secret shapes in markup and scripts, decode encoded holders into candidate pairs, and parse structured artifact bodies into named credential fields.
- **Pattern catalogue**: see `references/secret-pattern-catalog.md` for the ordered shape rows, and run `scripts/secret-scan.py` over fetched bodies for one record per match.
- **Source and route reconstruction**: reconstruct source from a published source map and read an interface specification document for routes, because both are holders that name further secrets rather than secrets themselves.
- **Token-shape fingerprinting**: fingerprint the algorithm and entropy shape of any token-shaped holder at this step and hand the sampling and re-derivation questions to `crypto-weakness` and `crypto-predictable-token`, because a token that is not a fixed secret is judged by predictability rather than by pattern shape.
- **Match recording**: record every match with its carrier plus its location so confirmation can replay the exact holder.

## Chaining Attacks

- **Forward chaining**: extraction chains forward into authenticated testing because a holder without reuse is only discovery.
- **Credential handoff**: hand each confirmed reusable credential to an authenticated session and continue into follow-on authorization testing.
- **Replay handoff**: hand each confirmed pair to replay confirmation where the login acceptor decides success, and name token validation through authentication-jwt instead of restating it.
- **Holder-shape aspects**: treat enumerated holder shapes as aspects inside this variant rather than separate procedures.

## Testing Methodology

Extraction runs fetch first and reuse last, because no confirmation is meaningful without a parsed holder.
1. **Inventory linked holders** - fetch every rendered page plus every linked script and record each carrier, and the step completes when every reachable page plus every linked script carries a fetched-or-unreachable verdict.
2. **Probe guessed artifact paths** - request each guessable artifact location and record status plus body size, and the step completes when every guessed path carries a holder-candidate or ruled-out verdict.
3. **Execute unified fetch-parse-triage** - match secret shapes plus decode encoded holders plus parse structured bodies in one pass over all fetched content, and the step completes when every fetched body carries a match-recorded or no-holder verdict.
4. **Confirm reusability** - replay each candidate holder through its natural consumer such as a login acceptor or a credential-bearing request, and the step completes when every candidate carries a reusable or non-reusable verdict with its evidence.
5. **Rule out secondary holders** - recheck carriers that returned ambiguous bodies with holder-specific reading, and the step completes when no ambiguous body remains without a final verdict.

## False Positives

- **Authentication conversion**: stop when the holder cannot convert into authentication, because an unusable match is only noise.
- **Intentional example credentials in documentation samples**: confirmed by documentation context around the match.
- **Owner-only details with no reuse path**: confirmed when the holder grants no session and matches no acceptor.
- **Unreachable banners**: name a technology without exposing a holder, confirmed by absence of any credential field in the body.

## Pro Tips

- **Extraction economics**: extraction rewards broad fetching plus holder-specific reading.
- **Ordering**: prefer linked harvesting before path guessing, then promote only size-passing artifact bodies to parsing.
- **Broad matching**: favor shape matching across every carrier before confirming, so no holder family goes unchecked.
- **Match recording**: record each match with its carrier plus location so confirmation replays the exact holder.
- **Ambiguity handling**: treat ambiguous bodies as pending rather than negative and reread them with the matching holder parser.

## Summary

Served content that carries a reusable holder already surrendered the credential before any login guess.
Extraction fetches linked source plus guessed paths in one pass, parses each holder by its shape, and confirms reuse before any follow-on testing begins.
