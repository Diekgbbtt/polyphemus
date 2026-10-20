---
name: weak-credential-discovery
description: Finding exposed credentials in HTML source, default passwords, and username enumeration across web applications
metadata:
  version: 1.0.0
---

# Weak Credential Discovery

Applications expose credential material in places they never intended to publish: served client source, guessable deployable paths, unchanged vendor defaults, identity oracles in login responses, and client-readable issued artifacts. This class converts any of those into authentication with minimal noise, which makes it the first family worth running on a fresh target. Treat every holder as fetchable or submittable until a reuse attempt says otherwise.

## Attack Surface

**Secret Holders**
- **Served client source**: comments, hidden fields, inline scripts, and configuration objects.
- **Deployable artifacts**: at guessable locations: environment files, configuration files, version-control metadata, backups, and debug or status pages.
- **Build and bundle artifacts**: source maps, asset manifests, interface specification documents, and build-info files, which reconstruct source, enumerate routes, and carry embedded secrets.
- **API responses**: that embed credential shapes or token material.

**Authentication Acceptors**
- **Login and integration endpoints**: login, panel, and integration endpoints where vendor or framework defaults may remain active.
- **Seeded accounts**: seeded accounts and placeholder identities that survive deployment.

**Identity Oracle Surfaces**
- **Identity oracle surfaces**: login, recovery, and registration flows whose responses differ per identity in message, timing, status, or redirect.

**Issued Artifacts**
- **Issued artifacts**: session cookies, tokens, and client-readable storage values issued after authentication.

## Reconnaissance

### Source Sweep

- **Page and script fetch**: fetch every rendered page and every linked script; search for credential shapes, encoded holders, and placeholder values.
- **Holder recording**: record the holder of each candidate: comment, hidden field, configuration object, or script literal.
- **Holder chains**: follow holder chains: a script path leads to a configuration location, which leads to a value.

### Path and Artifact Discovery

- **Deployable-location requests**: request well-known deployable locations (environment, configuration, metadata, backup, and debug paths) and size-filter the responses.
- **Format parsing**: parse each fetched holder per its format: key-value, structured configuration, version-control metadata, and debug output.
- **State echoes**: note responses that echo environment or configuration state without authentication.

### Default and Oracle Probing

- **Default-pair submission**: submit vendor and framework default pairs to every authentication acceptor and read the success signal.
- **Fixed-secret comparison**: submit a fixed wrong secret across candidate identities and compare message, timing, status, and redirect behaviour.
- **Timing baseline**: establish a timing baseline with repeated samples before treating latency as a signal.
- **Lockout discipline**: stay under lockout thresholds; a locked account costs more than the enumeration is worth.

### Issued-Artifact Inspection

- **Artifact decoding**: after an authenticated response, decode the session cookie, token, and storage values.
- **Claim reading**: read the identity and role claims they carry, and note which the client can alter.
- **Algorithm fingerprinting**: fingerprint the algorithm each holder uses, from its structure and digest shape, and hand the entropy and re-derivation questions to the `crypto-weakness` class and its `crypto-predictable-token` leaf at that step.

## Detection Channels

- **Credential-shaped value**: a credential-shaped value in served source, which decides the exposure finding when it is reusable.
- **Deployable artifact**: a deployable artifact answering at a guessable location with sensitive content, which proves exposure.
- **Authentication-success signal**: an authentication-success signal after a default pair submission (a session, a privileged view, or a redirect into an authenticated area), which proves acceptance.
- **Identity delta**: an identity delta across responses under one fixed secret, in message, timing, status, or redirect, which proves the enumeration oracle.
- **Timing difference**: a timing difference over a calibrated baseline between present and absent identities, confirmed by repeated samples.
- **Decoded token claims**: a decoded token or storage value carrying identity or role claims, which proves client-readable authority.
- **Excess claim authority**: a readable claim that exceeds the authority the session proved, which signals client-side authority trust.
- **Cross-surface reuse**: one secret reused across more than one surface, which raises a candidate to a usable credential.
- **Uniform responses**: uniform responses with identical timing for present and absent identities, which read as no oracle.
- **Banner noise**: a version, environment, or error banner that names no reusable value, which stays noise.

## Adversarial Capabilities

- **Weak credential discovery**: presupposes the ability to send unauthenticated requests wherever a holder might live, and it consumes nothing else.
- **Surface fetching**: fetch every served page, script, and linked artifact the application exposes.
- **Deployable-location requests**: request guessable deployable locations and size-filter the responses.
- **Candidate submission**: submit candidate identities and secrets to authentication endpoints at a controlled rate.
- **Timing baselines**: establish timing baselines with repeated samples before treating latency as a signal.
- **Authenticated session**: hold one authenticated session to decode the artifacts the application issues.
- **Cross-identity comparison**: compare responses across identities under one fixed request shape.

## Trust Assumptions

- **The agreement**: whatever the application serves to an unauthenticated caller is safe to publish, and every holder of credential material is unreachable, changed from its vendor default, and unreadable to the caller.
- **Held clauses**: the agreement holds served source and guessable paths to secret-free content, holds authentication acceptors to non-default credentials, holds login responses to uniformity across identities, and holds issued artifacts to claims the client cannot exploit.
- **Leak condition**: authentication position leaks when a clause fails: a reusable secret sits in served content or at a reachable path, a default pair still authenticates, responses differ per identity, or an issued artifact describes more authority than the caller proved.
- **The failing clause**: each variant breaks one clause: the exposure clause, the default-credential clause, the response-uniformity clause, or the artifact-authority clause.

## Key Vulnerabilities

### Exposed Secrets in Served Content

- **Inline carriers**: comments, hidden fields, and inline configuration that carry credentials, keys, or token material.
- **Encoded holders**: encoded blobs, concatenated forms, and encoded key-value pairs that decode to a reusable secret.
- **Integration surfaces**: integration and status surfaces that embed credential shapes.
- **Shared values**: values shared between environments, where one exposure authenticates several deployments.

### Reachable Deployables

- **Guessable locations**: environment files, configuration files, version-control metadata, backups, and debug pages at guessable locations.
- **Token and hash exposure**: API surfaces that expose token or hash material for the current or another identity.
- **Runtime-state echoes**: responses that echo runtime state and hold secrets in their output.

### Default Credentials

- **Active default pairs**: vendor and framework default pairs still active on login acceptors, panels, and integration endpoints.
- **Seeded accounts**: seeded accounts that survive deployment, and placeholders that were never changed.
- **Copied integration credentials**: integration credentials copied between environments, where one default opens several systems.

### Identity Enumeration

- **Differing responses**: login, recovery, and registration flows whose responses differ per identity in message, timing, status, or redirect.
- **Existence leaks**: account-existence leaks through lockout behaviour or duplicate-registration checks.
- **Per-identity work**: per-identity server-side work that shows as a timing difference.

### Issued Artifact Authority

- **Readable and influenceable claims**: session cookies and tokens whose claims the client can read and, in some designs, influence.
- **Storage role fields**: storage values carrying role or identity fields the application later trusts.
- **Excess authority claims**: claims that name more authority than the caller proved; validation and signature steps belong to the token class.

## Advanced Techniques

**Holder Parsing**
- **Format-aware parsing**: parse each fetched holder per its format rather than pattern-matching alone: key-value files, structured configuration, metadata, and debug output.
- **Layered decoding**: decode layered holders before judging reuse; an encoded string may be the only form the surface serves.

**Rate Discipline**
- **Slow submission**: submit candidate pairs slowly and stop at the first success; lockout converts a cheap test into a denial of service against the account.
- **Repeated samples**: compare timing against a baseline with repeated samples, never single measurements.

**Cross-Surface Correlation**
- **Reuse across surfaces**: a secret found on one surface often authenticates another; reuse across surfaces is the finding.
- **Holder chaining**: chain holders: served source names a path, the path yields a configuration, the configuration yields a credential.

**Liveness and Scope Validation**
- **Candidate validation**: validate a candidate against the issuing service's read-only identity endpoint before calling it usable: liveness plus the scope it grants is what turns a credential-shaped string into a finding.
- **Detectability cost**: weigh the detectability cost before each validation, and prefer the quietest validator that still answers.
- **Read-only validation**: keep the validation request read-only and shaped like ordinary traffic, because a loud validator converts a low-noise finding into a monitored one.
- **Validator shapes**: see `references/secret-validators.md` for the validator shape, the identity reads by issuer family, and the output record.

**Post-Authentication Reading**
- **Claim comparison**: decode every issued artifact after login and compare its claims with the identity the flow proved.
- **Signature hand-off**: where claims are client-side-authoritative, hand the signature and validation step to the token class.
- **Entropy hand-off**: where a holder looks opaque but must carry entropy, hand the sampling and re-derivation procedure to `crypto-weakness` and `crypto-predictable-token` rather than judging strength from one sample.

## Bypass Techniques

**Uniformity and Lockout Defences**
- **Timing fallback**: where responses are uniform, fall back to timing and connection behaviour as the residual channel.
- **Lockout hand-off**: where lockout exists, the threshold and the spread across identities are the defence-bypass family's throttle step; name it there and keep the lockout verdict here.

**Secret Obfuscation**
- **Layered decoding**: decode layered and encoded holders before judging a candidate.
- **Assembled values**: look for values assembled at runtime from parts, or split across fields.

**Artifact Reading**
- **Encoding recovery**: recover claim content from padded, compressed, or segmented encodings.
- **Visible identifiers**: read identifiers from visible fields where the artifact itself hides them.
- **Extended reading**: when this section does not fulfil the knowledge gap, extend the reading with the defence-bypass and proxy-techniques families.

## Chaining Attacks

- **Authenticated access**: exposed secrets to authenticated access, then the classes in scope for the role the secret carried.
- **Replay and recovery**: enumerated identities to replay and recovery flows, which compounds with lockout behaviour.
- **Authorization testing**: decoded identifier and role claims to authorization testing through the two-principal methodology.
- **Integration access**: default credentials on integration surfaces to the access those integrations hold.
- **Token class**: readable token claims to the token class where validation, not reading, is the weakness.

## Testing Methodology

1. **Collect surfaces** - Served pages and scripts, guessable deployable locations, authentication acceptors, and issued artifacts
2. **Extract and decode** - Pattern-match holders, decode layered forms, and record candidates with their reuse surfaces
3. **Replay defaults** - Submit default pairs to every acceptor slowly, and read the authentication-success signal
4. **Enumerate identities** - One fixed wrong secret across candidates; compare message, timing, status, and redirect against a baseline
5. **Read issued artifacts** - Decode session and storage values, and interpret the identity and role claims they carry
6. **Confirm reuse** - A finding is a holder plus a successful, reproducible use of the value

## Variants

- exposed-secret-extraction - Fetch linked source plus guessed deployable paths and parse every holder for reusable secrets, judged by reuse rather than by shape.
- default-credential-replay - Submit vendor and framework default pairs to login acceptors and read the authentication-success signal.
- username-enumeration-oracle - Compare responses under one fixed secret across candidate identities, normalizing timing before the verdict.
- session-token-authority-decode - Split, decode, and interpret issued token and storage claims under a held session to read the authority they carry.

## False Positives

- **Documentation examples**: example credentials in documentation, samples, or comments that name no live account, verified by a reuse attempt.
- **Banners and names**: version banners and environment names that disclose no reusable value.
- **Generic login errors**: generic login errors that stay uniform once timing is normalized.
- **Silent throttle**: a uniform rejection that persists while correct submissions stop being accepted, which reads as a silent throttle rather than an open endpoint; re-test with spaced samples before recording a negative.
- **Cryptographically bound claims**: a token whose claims are readable but cryptographically bound, where reading yields nothing beyond the identity that proved possession.
- **Application pages**: deployable-looking paths that return the application's own error or login page.
- **Owner-only pages**: owner-only detail pages with no authentication path.

## Pro Tips

- **Source sweep first**: sweep served source first: it is low-noise, needs no authentication, and often yields immediate access.
- **Defaults first**: test defaults before any expensive vector; on a fresh assessment it costs one request per acceptor.
- **Artifact decoding**: decode every issued artifact after login and compare claims with the identity proved.
- **Reuse as the bar**: treat reuse as the bar: a secret-shaped string that authenticates nothing is noise.
- **Timing normalization**: normalize timing before claiming an enumeration oracle; single measurements lie.
- **Lockout thresholds**: stay under lockout thresholds; a lockout costs more than the enumeration is worth.
- **Holder chains**: follow holder chains; the interesting secret is rarely on the surface that first names it.
- **Candidate lists**: keep a candidate list per holder format and re-run it after each deployment.

## Summary

Weak credential discovery ends in authentication obtained from something that should not have been reachable: served source, a deployable path, an unchanged default, an identity oracle, or a client-readable artifact. Fix the holder first; each one is a barrier that failed before any exploitation was needed.
