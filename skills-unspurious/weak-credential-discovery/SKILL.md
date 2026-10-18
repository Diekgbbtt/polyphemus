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
- Served client source: comments, hidden fields, inline scripts, and configuration objects
- Deployable artifacts at guessable locations: environment files, configuration files, version-control metadata, backups, and debug or status pages
- API responses that embed credential shapes or token material

**Authentication Acceptors**
- Login, panel, and integration endpoints where vendor or framework defaults may remain active
- Seeded accounts and placeholder identities that survive deployment

**Identity Oracle Surfaces**
- Login, recovery, and registration flows whose responses differ per identity in message, timing, status, or redirect

**Issued Artifacts**
- Session cookies, tokens, and client-readable storage values issued after authentication

## Reconnaissance

### Source Sweep

- Fetch every rendered page and every linked script; search for credential shapes, encoded holders, and placeholder values
- Record the holder of each candidate: comment, hidden field, configuration object, or script literal
- Follow holder chains: a script path leads to a configuration location, which leads to a value

### Path and Artifact Discovery

- Request well-known deployable locations (environment, configuration, metadata, backup, and debug paths) and size-filter the responses
- Parse each fetched holder per its format: key-value, structured configuration, version-control metadata, and debug output
- Note responses that echo environment or configuration state without authentication

### Default and Oracle Probing

- Submit vendor and framework default pairs to every authentication acceptor and read the success signal
- Submit a fixed wrong secret across candidate identities and compare message, timing, status, and redirect behaviour
- Establish a timing baseline with repeated samples before treating latency as a signal
- Stay under lockout thresholds; a locked account costs more than the enumeration is worth

### Issued-Artifact Inspection

- After an authenticated response, decode the session cookie, token, and storage values
- Read the identity and role claims they carry, and note which the client can alter

## Detection Channels

- A credential-shaped value in served source, which decides the exposure finding when it is reusable.
- A deployable artifact answering at a guessable location with sensitive content, which proves exposure.
- An authentication-success signal after a default pair submission (a session, a privileged view, or a redirect into an authenticated area), which proves acceptance.
- An identity delta across responses under one fixed secret, in message, timing, status, or redirect, which proves the enumeration oracle.
- A timing difference over a calibrated baseline between present and absent identities, confirmed by repeated samples.
- A decoded token or storage value carrying identity or role claims, which proves client-readable authority.
- A readable claim that exceeds the authority the session proved, which signals client-side authority trust.
- One secret reused across more than one surface, which raises a candidate to a usable credential.
- Uniform responses with identical timing for present and absent identities, which read as no oracle.
- A version, environment, or error banner that names no reusable value, which stays noise.

## Adversarial Capabilities

Weak credential discovery presupposes the ability to send unauthenticated requests wherever a holder might live, and it consumes nothing else.
- Fetch every served page, script, and linked artifact the application exposes.
- Request guessable deployable locations and size-filter the responses.
- Submit candidate identities and secrets to authentication endpoints at a controlled rate.
- Establish timing baselines with repeated samples before treating latency as a signal.
- Hold one authenticated session to decode the artifacts the application issues.
- Compare responses across identities under one fixed request shape.

## Trust Assumptions

The class rests on one agreement: whatever the application serves to an unauthenticated caller is safe to publish, and every holder of credential material is unreachable, changed from its vendor default, and unreadable to the caller.
The agreement holds served source and guessable paths to secret-free content, holds authentication acceptors to non-default credentials, holds login responses to uniformity across identities, and holds issued artifacts to claims the client cannot exploit.
Authentication position leaks when a clause fails: a reusable secret sits in served content or at a reachable path, a default pair still authenticates, responses differ per identity, or an issued artifact describes more authority than the caller proved.
Each variant breaks one clause: the exposure clause, the default-credential clause, the response-uniformity clause, or the artifact-authority clause.

## Key Vulnerabilities

### Exposed Secrets in Served Content

- Comments, hidden fields, and inline configuration that carry credentials, keys, or token material
- Encoded holders (encoded blobs, concatenated forms, encoded key-value pairs) that decode to a reusable secret
- Integration and status surfaces that embed credential shapes
- Values shared between environments, where one exposure authenticates several deployments

### Reachable Deployables

- Environment files, configuration files, version-control metadata, backups, and debug pages at guessable locations
- API surfaces that expose token or hash material for the current or another identity
- Responses that echo runtime state and hold secrets in their output

### Default Credentials

- Vendor and framework default pairs still active on login acceptors, panels, and integration endpoints
- Seeded accounts that survive deployment, and placeholders that were never changed
- Integration credentials copied between environments, where one default opens several systems

### Identity Enumeration

- Login, recovery, and registration flows whose responses differ per identity in message, timing, status, or redirect
- Account-existence leaks through lockout behaviour or duplicate-registration checks
- Per-identity server-side work that shows as a timing difference

### Issued Artifact Authority

- Session cookies and tokens whose claims the client can read and, in some designs, influence
- Storage values carrying role or identity fields the application later trusts
- Claims that name more authority than the caller proved; validation and signature steps belong to the token class

## Advanced Techniques

**Holder Parsing**
- Parse each fetched holder per its format rather than pattern-matching alone: key-value files, structured configuration, metadata, and debug output
- Decode layered holders before judging reuse; an encoded string may be the only form the surface serves

**Rate Discipline**
- Submit candidate pairs slowly and stop at the first success; lockout converts a cheap test into a denial of service against the account
- Compare timing against a baseline with repeated samples, never single measurements

**Cross-Surface Correlation**
- A secret found on one surface often authenticates another; reuse across surfaces is the finding
- Chain holders: served source names a path, the path yields a configuration, the configuration yields a credential

**Post-Authentication Reading**
- Decode every issued artifact after login and compare its claims with the identity the flow proved
- Where claims are client-side-authoritative, hand the signature and validation step to the token class

## Bypass Techniques

**Uniformity and Lockout Defences**
- Where responses are uniform, fall back to timing and connection behaviour as the residual channel
- Where lockout exists, stay under the threshold and spread attempts across identities and sessions

**Secret Obfuscation**
- Decode layered and encoded holders before judging a candidate
- Look for values assembled at runtime from parts, or split across fields

**Artifact Reading**
- Recover claim content from padded, compressed, or segmented encodings
- Read identifiers from visible fields where the artifact itself hides them

## Chaining Attacks

- Exposed secrets to authenticated access, then the classes in scope for the role the secret carried
- Enumerated identities to replay and recovery flows, which compounds with lockout behaviour
- Decoded identifier and role claims to authorization testing through the two-principal methodology
- Default credentials on integration surfaces to the access those integrations hold
- Readable token claims to the token class where validation, not reading, is the weakness

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

- Example credentials in documentation, samples, or comments that name no live account, verified by a reuse attempt
- Version banners and environment names that disclose no reusable value
- Generic login errors that stay uniform once timing is normalized
- A token whose claims are readable but cryptographically bound, where reading yields nothing beyond the identity that proved possession
- Deployable-looking paths that return the application's own error or login page
- Owner-only detail pages with no authentication path

## Pro Tips

1. Sweep served source first: it is low-noise, needs no authentication, and often yields immediate access
2. Test defaults before any expensive vector; on a fresh assessment it costs one request per acceptor
3. Decode every issued artifact after login and compare claims with the identity proved
4. Treat reuse as the bar: a secret-shaped string that authenticates nothing is noise
5. Normalize timing before claiming an enumeration oracle; single measurements lie
6. Stay under lockout thresholds; a lockout costs more than the enumeration is worth
7. Follow holder chains; the interesting secret is rarely on the surface that first names it
8. Keep a candidate list per holder format and re-run it after each deployment

## Summary

Weak credential discovery ends in authentication obtained from something that should not have been reachable: served source, a deployable path, an unchanged default, an identity oracle, or a client-readable artifact. Fix the holder first; each one is a barrier that failed before any exploitation was needed.
