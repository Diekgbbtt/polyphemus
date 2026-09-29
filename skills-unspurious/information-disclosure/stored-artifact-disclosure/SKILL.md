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

Deployables live in version-control metadata, backups, temporary files, build outputs, and directory listings left reachable over HTTP.
Secrets live in configuration files, environment dumps, diagnostic pages, and deployment manifests served to unauthenticated fetchers.
Client leakage lives in bundles shipped with source maps, embedded environment values, and static data payloads.
Interfaces live in published schema documents and in live introspection and reflection endpoints that answer queries natively.
Storage lives in broadly scoped buckets, signed URLs, and export endpoints serving datasets beyond one tenant.
Panels live in observability and administration surfaces whose gating decides what triage may read.

## Reconnaissance

Enumerate candidate artifact locations per channel before fetching them.
Locate live schema interfaces, storage and export surfaces, and observability panels, and note each panel's gating posture.
Record the addressing scheme each surface uses so fetching stays systematic rather than guessy.
Reconnaissance is complete when every channel has a candidate artifact list with gating notes.

## Detection Channels

Secret strings and internal hostnames inside fetched dumps, snapshots, and panel output.
Parsed file metadata from downloads: paths, versions, keys, and endpoint names the artifact carries.
Operation listings from live schema interfaces that name hidden or privileged operations.
Scope, audience, lifetime, and foreign-dataset signals read from a single storage or export response.
Only channels carried by fetched single-response content fire here; triggered failure output and two-response differentials belong to the sibling variants.

## Adversarial Capabilities

Unauthenticated fetching is the entry capability: the procedure presupposes the ability to request deployables without credentials.
Offline parsing closes the read loop: the ability to extract metadata, secrets, and endpoint names from downloaded content under tester control.
Session holding extends reach into gated triage: held sessions probe what observability and administration panels reveal at each privilege level.
Live-interface querying enumerates hidden operations through the schema dialect the target speaks.

## Trust Assumptions

At the moment the server answers a fetch, the target trusts that what it does not intend to reveal cannot be elicited.
The precise agreement is that stored deployables stay unreachable: shipped files, live schema answers, and scoped exports carry nothing beyond their intended audience.
The failing clause is the unreachable-deployable clause: fetched content renders secrets, metadata, hidden operations, or foreign datasets instead of refusing.

## Key Vulnerabilities

Fetching enumerates deployables, configs, bundles, maps, listings, and panel snapshots as static retrieval.
Parsing extracts file metadata from downloads: embedded paths, versions, keys, endpoint names, and environment values.
Querying asks live introspection and reflection interfaces natively to enumerate hidden or privileged operations, naming the graphql skill for paradigm-specific query shapes instead of restating them.
Scoping reads storage and export responses for audience, lifetime, binding, and foreign-dataset signals from the single fetched object.
Triaging reads auth-gated observability panels per held session and records the gating posture as a secondary check.
Noting records referrer, introspection-off, and expose-header states as secondary checks inside the same procedure.

## Chaining Attacks

Secrets to control: extracted credentials and keys scope control-plane access attempts.
Schemas to authorization bypass: hidden fields and operations feed requests whose missing authorization the authorization skills own.
Bundles to hidden routes: endpoint names from maps and static payloads scope further surface enumeration.
Each chain stops at a reversible proof or a stated architectural risk rather than a full exploit.

## Testing Methodology

1. **Enumerate candidates.** List deployables, configs, bundles, maps, schema interfaces, storage surfaces, exports, and panels per channel with gating notes. Complete when every channel carries a candidate list.
2. **Execute unified fetch-parse-triage.** Fetch each candidate, parse every download for metadata and secrets, query live schema interfaces for hidden operations, read scope and lifetime from storage and export responses, and triage gated panels per held session, over parent step P4, which describes only fetching static artifacts and API docs and never names metadata parsing, live querying, scope reading, or gating triage as one procedure. Complete when every candidate is fetched and read or ruled out and each parse, listing, scope reading, and triage outcome is recorded.
3. **Record secondary controls.** Note introspection-off, panel gating, redaction, and header-policy states observed during the same fetches. Complete when each observed control carries a state note.
4. **Correlate to impact.** Map each leak to keys enabling control-plane access, paths enabling file access, versions with reachable flaws, or schemas enabling authorization bypass, with a minimal reversible proof or a stated risk. Complete when every recorded leak carries a proof or a risk statement.

## False Positives

Intentional public documentation with no exploit path is not a finding.
Redacted dumps whose sensitive fields stay redacted across replays carry no leak.
Owner-visible-only panel details that never cross identity or tenant boundaries are not disclosure.
Generic banners and marketing versions with no reachable surface and no chain are not findings.

## Pro Tips

Fetch artifacts before triggering anything: deployables yield the fastest wins in the class.
Parse every download fully before moving on: metadata hides in manifests, maps, and embedded payloads alike.
Treat live schema interfaces as configuration findings and query them natively rather than scraping docs.
Mine observability panels last: they are noisy but high-yield where gating is misconfigured.

## Summary

Stored artifact disclosure turns shipped files into intelligence.
Fetch each candidate, parse what downloads, query what answers live, and convert every artifact byte into a scoped follow-on.
