---
name: information-disclosure
description: Information disclosure testing covering error messages, debug endpoints, metadata leakage, and source exposure
metadata:
  version: 1.0.0
---

# Information Disclosure

Information leaks accelerate exploitation by revealing code, configuration, identifiers, and trust boundaries. Treat every response byte, artifact, and header as potential intelligence. Minimize, normalize, and scope disclosure across all channels.

## Attack Surface

- Errors and exception pages: stack traces, file paths, query fragments, component versions
- Debug and diagnostic tooling reachable in production: debuggers, profilers, feature flags
- Version-control and build artifacts, plus temp and backup files produced by editors and deploy scripts
- Configuration and secret stores reachable over HTTP: environment files, status dumps, deployment manifests
- Interface descriptions and schema interfaces: API documents, schema introspection, service reflection
- Client bundles and source maps: build maps, embedded environment values, serialized page data, static data files
- Headers and response metadata: server and platform banners, tracing identifiers, validators, range and timing fields
- Storage and export surfaces: public buckets, signed URLs, export and download endpoints
- Observability and administrative surfaces: metrics, health and actuator paths, tracing consoles, admin views
- Directory listings and indexing: autoindex, sitemaps and crawl directives revealing hidden routes

## Reconnaissance

### Channel Map

- Enumerate every channel that renders content: web, API, schema layer, socket, RPC, mobile, background jobs, exports, and the cache in front
- Per channel, record the rendering path and the hardening headers so inconsistency between channels is visible later
- Note which channels are reachable anonymously, as an owner, and as a non-owner

### Artifact Enumeration

- Sweep for deployable artifacts: version-control folders, editor backups, archives, configuration dumps, build maps, and interface documents
- Follow crawl directives and listing surfaces for route names that were meant to stay unreferenced
- Record one candidate location per artifact family before probing further

### Differential Harness

- Establish an identity-contrast baseline: the same resource fetched as anonymous, as owner, and as non-owner
- Normalize each response on status, body length, validators, and headers so later comparisons rest on digests rather than eyeballing
- Keep one never-touched control request per channel for ambient comparison

## Detection Channels

- Stack traces, file paths, query fragments, and component versions inside failure responses.
- Evaluation-probe output that confirms a live execution context behind the error renderer.
- Timing and metadata deltas adjacent to the failure that narrate handling the trigger did not intend to expose.
- Method-swap deltas where a header-only answer diverges from the full answer on existence or state.
- Conditional-replay deltas where revalidation outcomes diverge on existence or state for the same principal.
- Second-session serving where a foreign session receives content the first session keyed.
- Per-channel field extras where parallel representations of one object disagree on fields or hardening.
- Secret strings and internal hostnames inside fetched dumps, snapshots, and panel output.
- Parsed file metadata from downloads: paths, versions, keys, and endpoint names the artifact carries.
- Operation listings from live schema interfaces that name hidden or privileged operations.
- Scope, audience, lifetime, and foreign-dataset signals read from a single storage or export response.

## Adversarial Capabilities

Disclosure testing presupposes identity contrast, artifact fetching, and failure induction, and it consumes all three.
- Hold anonymous, owner, and non-owner sessions so every rendering can be compared across identities.
- Request one resource through every channel the target exposes, including caches in front.
- Induce failures deliberately: malformed types, boundary values, missing parameters, alternate content types.
- Fetch candidate artifacts by guessing deployable locations and by following listing surfaces.
- Read both single responses and response pairs, since some leaks appear only in the contrast.
- Snapshot the same object over time to catch stale entries.

## Trust Assumptions

The class rests on one agreement: every channel renders exactly what the caller is entitled to see, and any state the caller is not entitled to see renders opaquely.
The agreement holds each response to the caller's identity scope, holds failure paths to output without internals, holds artifact locations out of reach of unentitled callers, and holds cache keys to include identity.
Sensitive position leaks when one rendering clause fails: a failure narrates internals, a deployable stays reachable, a cache serves one identity's content to another, or two channels disagree about the same object.
Each variant breaks one clause: the failure-rendering clause, the artifact-scoping clause, or the pair-consistency clause.

## Key Vulnerabilities

### Differential Oracles

- Compare owner versus non-owner versus anonymous for the same resource
- Track status, length, validators, and cache-control fields
- Header-only requests beside full requests: header-only differences can confirm existence
- Conditional requests: revalidation outcomes leak existence and state

### Cache and Key Composition

- Identity-agnostic caches: keys missing the authorization or tenant binding
- Key-variation misconfiguration: varying on client shape without varying on identity
- Partial-content and stale entries leaking object fragments

### Cross-Channel Mirroring

- Inconsistent hardening between surfaces: the same object rendered with different fields per channel
- Server-rendered pages omitting fields that the structured interface includes, and the reverse

## Chaining Attacks

- Artifact to credentials: configuration dumps and deploy artifacts expose keys for databases, mail, tokens, and cloud control planes
- Version to known flaw: derive precise component versions from banners, errors, and bundles, map them to known issues, and confirm reachability
- Path to file read: paths from traces and templates reveal the layout, and an inclusion primitive then fetches configuration or keys
- Schema to authorization bypass: an interface listing hidden fields and routes, whose absence of checks is then confirmed by direct requests

## Testing Methodology

1. **Establish the differential harness** - Normalize status, length, validators, and headers across anonymous, owner, and non-owner; the step completes when the harness reports a stable baseline per channel
2. **Trigger controlled failures** - Malformed types, boundary values, missing parameters, alternate content types; the step completes when each channel carries an error-verbosity verdict
3. **Fetch and read artifacts** - Retrieve each candidate deployable and read its content for secrets, paths, versions, and endpoint names; the step completes when every candidate carries a content verdict
4. **Correlate to a chain** - Map each leak to credentials, known flaws, file reads, or bypasses; the step completes when every leak carries a chain verdict or a no-chain verdict
5. **Rule out intentional disclosure** - Compare each candidate against published documentation and public-by-design surfaces; the step completes when every candidate carries a final verdict

## Variants

- error-verbosity-disclosure - Verbose failures disclose internals when failure output turns detailed, debug or profiler surfaces answer in production, or evaluation probes confirm a live execution context.
- stored-artifact-disclosure - Stored artifacts disclose secrets when deployable files stay reachable, live schema interfaces enumerate hidden operations, or storage and export surfaces serve foreign data.
- differential-oracle-disclosure - Response differentials disclose state when method swaps change answers on one resource, cached responses leak across sessions, or parallel channels disagree on the same object.

## False Positives

- Intentional public documentation or non-sensitive metadata with no exploitation path
- Generic errors with no actionable detail
- Redacted fields that do not change a differential or oracle
- Version banners with no reachable vulnerable surface and no chain
- Owner-visible details that do not cross an identity or tenant boundary

## Pro Tips

1. Start with artifacts before payloads; deployable files and maps yield the fastest wins
2. Normalize responses and diff by digest to reduce noise when comparing identities
3. Hunt source maps and serialized page data; they often carry internal identifiers and flags
4. Probe caches for identity-unaware keys; verify the key variation covers identity and tenant
5. Treat introspection and reflection as configuration findings across schema and RPC surfaces
6. Mine observability endpoints last; they are noisy but high-yield when misconfigured
7. Chain quickly to a concrete risk and keep the proof minimal and reversible
8. Triage ladder for findings: credentials and control-plane keys first; then cross-tenant data and caches serving foreign content; then internal paths and maps that enable inclusion or fetch pivots; then banners and intended documentation with no path

## Summary

Information disclosure is an amplifier. Convert leaks into precise, minimal exploits or clear architectural risks.
