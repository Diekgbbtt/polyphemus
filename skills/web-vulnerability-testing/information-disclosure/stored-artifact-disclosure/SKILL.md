---
name: stored-artifact-disclosure
description: Stored artifacts disclose secrets. Use when deployable files remain reachable over HTTP; when live schema interfaces enumerate hidden operations; when storage or export surfaces serve foreign data.
metadata:
  version: 1.0.0
---

# Stored Artifact Disclosure

Deployables are a channel.
This variant fetches what should never have shipped, parses the downloads for metadata and secrets, and triages gated panels and scoped exports in one single-response fetch-parse-triage procedure.

## Attack Surface

- **Deployables**: live in version-control metadata, backups, temporary files, build outputs, asset manifests, build-info files, package manifests, server configuration, desktop and editor metadata files, cross-domain policy files, and directory listings left reachable over HTTP.
- **Secrets**: live in configuration files, environment dumps, diagnostic pages, and deployment manifests served to unauthenticated fetchers.
- **Client leakage**: lives in bundles shipped with source maps, embedded environment values, static data payloads, lazily loaded chunks beyond the shell-referenced bundles, and browser-side storage such as local storage, session storage, and serialized page state.
- **Interfaces**: live in published schema documents and in live introspection and reflection endpoints that answer queries natively.
- **Storage**: lives in broadly scoped buckets, signed URLs, and export endpoints serving datasets beyond one tenant.
- **Panels**: live in observability and administration surfaces whose gating decides what triage may read.

## Reconnaissance

- **Candidate enumeration**: enumerate candidate artifact locations per channel before fetching them.
- **Surface location**: locate live schema interfaces, storage and export surfaces, and observability panels, and note the gating posture of each panel.
- **Addressing-scheme record**: record the addressing scheme each surface uses so fetching stays systematic rather than guessy.
- **Sweep tooling**: sweep the candidate list with `scripts/artifact-sweep`, and read the families, the location shapes, and the reconstruction recipes in `references/artifact-harvesting.md`.
- **Reconnaissance completion**: reconnaissance is complete when every channel has a candidate artifact list with gating notes.

## Detection Channels

- **Secret strings and internal hostnames**: appear inside fetched dumps, snapshots, and panel output.
- **Parsed file metadata**: carries paths, versions, keys, and endpoint names from downloads.
- **Operation listings**: name hidden or privileged operations from live schema interfaces.
- **Scope, audience, lifetime, and foreign-dataset signals**: read from a single storage or export response.
- **Channel scope**: only channels carried by fetched single-response content fire here; triggered failure output and two-response differentials belong to the sibling variants.

## Adversarial Capabilities

- **Unauthenticated fetching**: the entry capability because the procedure presupposes the ability to request deployables without credentials.
- **Offline parsing**: closes the read loop because it extracts metadata, secrets, and endpoint names from downloaded content under tester control.
- **Session holding**: extends reach into gated triage because held sessions probe what observability and administration panels reveal at each privilege level.
- **Live-interface querying**: enumerates hidden operations through the schema dialect the target speaks.

## Trust Assumptions

- **The agreement**: at the moment the server answers a fetch, the target trusts that what it does not intend to reveal cannot be elicited, and stored deployables stay unreachable because shipped files, live schema answers, and scoped exports carry nothing beyond their intended audience.
- **The failing clause**: this variant breaks the unreachable-deployable clause because fetched content renders secrets, metadata, hidden operations, or foreign datasets instead of refusing.

## Key Vulnerabilities

- **Fetching**: enumerates deployables, configs, bundles, maps, listings, and panel snapshots as static retrieval.
- **Parsing**: parsing extracts file metadata from downloads: embedded paths, versions, keys, endpoint names, and environment values, including lazily loaded chunks and browser-side storage captured alongside the shell bundle.
- **Querying**: querying asks live introspection and reflection interfaces natively to enumerate hidden or privileged operations, naming the graphql skill for paradigm-specific query shapes instead of restating them; where introspection is closed, reconstruct the schema from unknown-field suggestions and error text, one probe at a time.
- **Reconstructing**: reconstructing walks that same interface one unknown-field probe at a time where introspection is closed, driven by `scripts/schema-reconstruction`, and records each harvested name beside the probe that produced it.
- **Scoping**: reads storage and export responses for audience, lifetime, binding, and foreign-dataset signals from the single fetched object.
- **Triaging**: reads auth-gated observability panels per held session and records the gating posture as a secondary check.
- **Secondary-state noting**: records referrer, introspection-off, and expose-header states as secondary checks inside the same procedure.

## Chaining Attacks

- **Secrets to control**: extracted credentials and keys scope control-plane access attempts.
- **Schemas to authorization bypass**: hidden fields and operations feed requests whose missing authorization the authorization skills own.
- **Bundles to hidden routes**: endpoint names from maps and static payloads scope further surface enumeration.
- **Chain stop condition**: each chain stops at a reversible proof or a stated architectural risk rather than a full exploit.

## Testing Methodology

1. **Enumerate candidates.** List deployables, configs, bundles, maps, schema interfaces, storage surfaces, exports, and panels per channel with gating notes. Complete when every channel carries a candidate list.
2. **Execute unified fetch-parse-triage.** Fetch each candidate, parse every download for metadata and secrets, query live schema interfaces for hidden operations, read scope and lifetime from storage and export responses, and triage gated panels per held session, over parent step P4, which describes only fetching static artifacts and API docs and never names metadata parsing, live querying, scope reading, or gating triage as one procedure. Complete when every candidate is fetched and read or ruled out and each parse, listing, scope reading, and triage outcome is recorded.
3. **Record secondary controls.** Note introspection-off, panel gating, redaction, and header-policy states observed during the same fetches. Complete when each observed control carries a state note.
4. **Correlate to impact.** Map each leak to keys enabling control-plane access, paths enabling file access, versions with reachable flaws, or schemas enabling authorization bypass, with a minimal reversible proof or a stated risk. Complete when every recorded leak carries a proof or a risk statement.

## False Positives

- **Intentional public documentation**: has no exploit path and is not a finding.
- **Redacted dumps**: keep sensitive fields redacted across replays and carry no leak.
- **Owner-visible-only details**: never cross identity or tenant boundaries and are not disclosure.
- **Generic banners and marketing versions**: have no reachable surface and no chain and are not findings.
- **Rotated artifacts**: a previously recorded artifact location that now answers not-found is not remediation: content-hashed build artifacts rotate on every deploy, so re-derive the live location before each verdict.

## Pro Tips

- **Artifact-first fetching**: fetch artifacts before triggering anything because deployables yield the fastest wins in the class.
- **Full download parsing**: parse every download fully before moving on because metadata hides in manifests, maps, and embedded payloads alike.
- **Lazy chunks**: read lazily loaded chunks and browser-side storage as well as the shell bundle, because values migrate to the parts the initial load never fetches.
- **Live-interface discipline**: treat live schema interfaces as configuration findings and query them natively rather than scraping docs, and reconstruct the schema from suggestion text where introspection is closed.
- **Panel mining last**: mine observability panels last because they are noisy but high-yield where gating is misconfigured.

## Summary

Stored artifact disclosure turns shipped files into intelligence.
Fetch each candidate, parse what downloads, query what answers live, and convert every artifact byte into a scoped follow-on.
