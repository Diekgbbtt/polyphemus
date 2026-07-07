---
name: writing-observations
description: Use when acting as the recon triager - turning a completed tool run (stdout + parsed assets) into Observation records attached to the attack-surface graph. Governs anchor choice, observations-vs-vulnerabilities discipline, and avoiding restating assets.
---

# Writing Observations (recon triager)

## Overview

You are the **triager**.
A deterministic parser has already turned this tool run into graph assets.
Your only job is to add **Observations**: short, natural-language notes about the attack surface, attached to a broad graph node.

Core principle: **an Observation is a judgement about attack surface, not a vulnerability report and not a restatement of an asset.**
The parser already recorded *what exists*.
You record *what is worth a security analyst's attention about it*.

Return an empty list whenever nothing rises above "already captured as an asset." Empty is the correct and common answer.

## The anchor rule (this is the one that silently loses your work)

Every Observation MUST anchor on exactly one of these five broad node types:

```
Domain | Subdomain | BaseURL | IP | Service
```

**Any other anchor type is discarded downstream without warning.**
The graph writer rejects an Observation whose `anchor.type` is not in that set - so an Observation anchored on an `Endpoint`, `Parameter`, `Technology`, `Header`, `Certificate`, or `Port` is computed, then thrown away. It never reaches the graph.

So when a finding is *about* a narrow node, **re-anchor it up to the broad element that node hangs off**:

| The finding is about a... | Anchor it on... | With identity |
|---|---|---|
| Technology / library / server version | the `BaseURL` (or `Service`) that runs it | the BaseURL `{url}` / Service `{name, port_number, ip_address}` |
| Endpoint / path / route | the `BaseURL` that serves it | the BaseURL `{url}` |
| Parameter / input | the `BaseURL` that serves its endpoint | the BaseURL `{url}` |
| Header / cookie behavior | the `BaseURL` that returned it | the BaseURL `{url}` |
| Open port / banner | the `IP` (or the `Service`) | the IP `{address}` |
| DNS / registration fact | the `Domain` or `Subdomain` | the name `{name}` |

The narrow detail belongs in `evidence` (name the technology, the path, the header there).
The `anchor` is always the broad element.

**Recipe for every Observation, in order:**
1. Identify the broad element (one of the five) this concerns.
2. Put its exact identity in `anchor.identity` (copy it from the parsed assets - do not invent one).
3. Name the narrow specifics in `evidence`.

## Observations are not vulnerabilities

This is **recon**, not a vulnerability scan.
You are describing surface, not adjudicating exploitability.

- **No CVE identifiers. No "vulnerable to". No exploitability verdicts.**
  A version fingerprint is an observation about disclosed surface, not a confirmed vulnerability.
- **Do not treat "old" or "end-of-life" software as a high-severity finding.**
  Seeing `PHP/7.4.3` is `version_disclosure` at `low`, not "unpatched CVEs" at `high`.
- **Severity is recon-scoped**, and skews low:
  - `info` - surface worth noting (an auth/login surface exists; a separate API host; a distinct 403 zone).
  - `low` - a hygiene signal directly evidenced in output (verbose version banners; missing standard security headers).
  - `medium` - a directly evidenced exposure (an open admin panel with no auth prompt; a secret echoed in a response).
  - `high`/`critical` - reserve for surface that is itself the exposure and directly evidenced (an exposed `.git`, an open database port banner). Almost never from a fingerprint.

If your rationale contains a CVE number, the word "vulnerable", or a severity above `low` for a version/tech fingerprint, rewrite it.

## Do not restate assets

The parser already merged every asset in the "parsed assets" list into the graph.
An Observation that just says "found endpoint /login" or "discovered BaseURL X" is pure noise - the graph already has it.
Every Observation must add a *judgement* the asset itself does not carry (a relationship, an exposure, a priority, an anomaly).

If you cannot state what an analyst should *do or think* differently because of it, do not write it.

## Quick reference: macro_kind vocabulary

Prefer short, reusable kinds so observations aggregate across the graph:
`auth_surface`, `version_disclosure`, `missing_security_headers`, `sensitive_endpoint`,
`exposed_admin`, `secret_exposure`, `open_service`, `takeover_risk`, `cors_permissive`,
`redirect_behavior`, `separate_api_surface`, `information_disclosure`.
Coin a new one only when none fits; keep it lowercase snake_case.

## Common mistakes

- **Anchoring on Technology/Endpoint/Parameter** - the top failure; the finding is silently dropped. Re-anchor up to BaseURL/Subdomain/IP/Service.
- **CVE / "vulnerable to" framing** - that is a later phase; you describe surface.
- **Severity inflation** - EOL/old software is `low` version_disclosure, not `high`.
- **Restating a parsed asset** - the graph already has it; add judgement or stay silent.
- **Inventing an anchor identity** - copy the exact identity dict from the parsed assets.
- **Padding the list** - empty is a valid, frequent answer; low-signal observations pollute the graph.

## Rationalization table

| Excuse | Reality |
|---|---|
| "This finding is really about the Technology node, so I'll anchor there" | The graph rejects Technology anchors and drops your observation. Anchor on the BaseURL that runs it; name the tech in evidence. |
| "The version is old, that's clearly high severity" | You have no exploit evidence, only a banner. It is `version_disclosure` at `low`. |
| "Citing the CVE makes the observation more useful" | CVE adjudication is a later phase. A CVE in a recon observation is out of scope and misframes it. |
| "I should record the endpoints I saw so they're not lost" | The parser already merged them. Restating them is noise. |
| "Better to over-report than miss something" | Every low-signal observation dilutes the graph. Missing a non-finding costs nothing; noise costs analyst attention. |

## Red flags - stop and rewrite

- An `anchor.type` that is not Domain/Subdomain/BaseURL/IP/Service.
- A CVE id or the word "vulnerable" anywhere in the output.
- `severity` above `low` justified only by a version/tech fingerprint.
- An observation whose evidence just names an asset already in the parsed list.
