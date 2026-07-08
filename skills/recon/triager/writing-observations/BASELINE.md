# RED/GREEN evidence: writing-observations

Authored TDD-style per `superpowers:writing-skills`.
The skill was written only after watching an agent fail without it.

## Scenario

An `httpx` (`http_probe`) run over two hosts, with parsed assets including `BaseURL`, `Endpoint`, and three `Technology` nodes (nginx 1.18.0, PHP 7.4.3, jQuery 1.11.0).
Deliberately tempting: old software (tempts CVE/EOL framing) and narrow Technology/Endpoint nodes (tempts illegal anchors).
The curator's `ANCHOR_ALLOWLIST = {Domain, Subdomain, BaseURL, IP, Service}` silently drops any other anchor type.

## RED - triager with only the current inline prompt (no skill)

4 observations. Failures:
- **2 of 4 anchored on `Technology`** (PHP, jQuery) -> rejected by `build_observation_cypher`, silently dropped. Half the output never reaches the graph.
- **CVE framing**: jQuery cited `CVE-2015-9251, CVE-2019-11358, CVE-2020-11022/11023`; PHP framed as "unpatched CVEs". Violates "Observations, not vulnerabilities."
- **Severity inflation**: PHP EOL `high`, jQuery `medium` - from bare version fingerprints.

## GREEN - triager with the writing-observations skill

3 observations. All pass:
- **3 of 3 anchored on `BaseURL`** (100% survive curation). PHP/jQuery/nginx findings re-anchored UP to the BaseURL, tech named in evidence.
- **Zero CVE ids, zero "vulnerable"** language.
- **Version fingerprint correctly `version_disclosure` at `low`.**
- **Dropped** the redundant `/login` and `403` restatements; the agent explicitly noted discarding a would-be Technology-anchored observation.

## Result

Clean RED -> GREEN with no new rationalizations (no REFACTOR needed).
Recommended next hardening (not required for this deliverable): a wording micro-test of 5+ reps across additional tool scenarios (naabu, subdomain_takeover) with a no-guidance control, per the `writing-skills` micro-test methodology.

## Edit 2 - "Primitives are not observations" caveat

Authoritative trigger: the live-LLM e2e trace (`.superpowers/sdd/sp4-livellm-trace-100551.txt`) surfaced `macro_kind="SSL Certificate"` and `macro_kind="HTTP Status Code"` as *accepted* Observations - the operator flagged these as attack-surface primitive elements (graph nodes/properties), not Observations.
An Observation is an adversarial NLP insight that adds interpretation beyond a primitive.
See memory `observations-vs-attack-surface-primitives`.

### Scenario (primitive-tempting)

An `httpx` + tls probe over `https://app.example.com` whose parsed assets include a `Certificate` (`not_after` ~13 days out), three `Endpoint`s carrying HTTP status codes (`/login` 200, `/admin` 403, `/api/v1/users` 401), a `Technology` (nginx 1.18.0), and a `Server` `Header`.
Deliberately tempting: a near-expiry cert and security-flavored status codes that read as "findings" but are already primitives in the graph.

### RED - no-guidance control (no skill)

6 observations. The primitive-restatement failure reproduced:
- **`macro_kind: "TLS certificate near expiry"`** at `low` - a bare restatement of the `Certificate.not_after` property, exactly the flagged failure.
- Plus the older, already-covered failures: an `nginx 1.18.0` fingerprint framed as **"Outdated server software with known vulnerabilities"** at `high` with CVE language.
- (The control *did* also produce the genuine adversarial insights - the `/admin` 403-vs-404 admin-surface oracle and the `/api/v1/users` versioned-API surface - so the target is to drop the primitive restatements while keeping those.)

### GREEN - with the edited skill (primitives caveat added)

The triager drops the certificate-expiry restatement entirely (writes nothing for the cert), emits no `macro_kind` naming a primitive, and keeps only the adversarial insights - the `exposed_admin`/`auth_surface` admin-panel oracle and the `separate_api_surface` versioned REST API - all anchored on the `BaseURL`.
No CVE framing, no severity inflation.

### Result

Clean RED -> GREEN for the caveat.
The edit closes the primitive-restatement loophole (new `## Primitives are not observations` section, two rationalization-table rows, two red flags) without disturbing the anchor / no-CVE / severity discipline the first edit established.

## Edit 3 - anchor allowlist: exact type + canonical casing

Authoritative trigger: the live triager still sometimes anchored Observations on out-of-allowlist types (`Endpoint`, `Technology`, an invented `Hostname`, lowercase `domain`), which the curator (`agent/recon/curator.py` `ANCHOR_ALLOWLIST = {Domain, Subdomain, BaseURL, IP, Service}`) correctly drops - silent recall loss.

### Scenario (anchor-tempting)

A `subfinder` + `httpx` run over `example.com` whose parsed assets are a `Subdomain` (`admin.example.com`), its `BaseURL`, two `Endpoint`s (`/api/v1/keys` 200, `/login` 200), a `Parameter` (`next` on `/login`), and a `Technology` (Apache Struts 2.3.15).
Deliberately tempting: each finding is *literally about* a narrow node (Technology / Endpoint / Parameter) whose own type is NOT in the allowlist.

### RED - no-guidance control (no skill)

4 observations, **3 of 4 anchored on a dropped type**:
- Struts finding -> `anchor.type = "Technology"` (dropped).
- `/api/v1/keys` finding -> `anchor.type = "Endpoint"` (dropped).
- `next` parameter finding -> `anchor.type = "Parameter"` (dropped).
- Only the admin-host finding anchored on `Subdomain` (survives).
So 75% of the output would be silently discarded by the curator.

### GREEN - with the tightened skill

4 observations, **4 of 4 anchored on an allowlist type with exact PascalCase**:
- Struts, `/api/v1/keys`, and `next` findings all re-anchored UP to `BaseURL` (`https://admin.example.com`), the narrow detail moved to evidence.
- The admin-host finding anchored on `Subdomain`.
- Zero invented types, zero lowercase labels, zero narrow-node anchors.
100% survive curation (vs 25% in RED).

### Result

Clean RED -> GREEN for the anchor tightening.
The edit hardens the existing anchor rule (closed-set + exact-casing + no-invention block, four rationalization-table rows, one expanded red flag) and is tightly scoped to anchoring - the primitives-vs-observations section from Edit 2 is untouched.

## Edit 4 - wire the skill into the live triager (the words were never delivered)

Authoritative trigger: the 2026-07-08 multi-target validation (memory `recon-e2e-validation`) found the live triager still mis-anchoring ~36% of observations onto narrow nodes (Endpoint/Port/Header) *despite* Edits 1-3. Root cause was not the wording: `agent/recon/pod.py::default_triage_fn` invoked the triager with a terse inline prompt and **never loaded this skill** - nothing under `agent/` read it, and `skills/` was not even present in the container (`Dockerfile` copied only `agent/`+`db/`). Every prior edit hardened text the model never saw.

### RED - triager with the inline prompt only (this skill NOT wired)

Anchor-tempting scenario (`httpx` over `app.example.com`: BaseURL + two status-bearing Endpoints /admin 403, /api/v1/users 401 + a Technology nginx/1.18.0 + an X-Frame-Options Header), 3 reps against the live model:
- **8 of 11 anchors out of the allowlist** (`Endpoint`, `Technology`, `Header`), plus restatements of the raw 403/401/header primitives.
- High variance: reps disagreed (one rep happened to anchor cleanly, two did not) - the model was guessing without the rule.

### GREEN - same scenario, skill wired as the triager system prompt

Wiring: `default_triage_fn` now loads this `SKILL.md` (frontmatter stripped) via `_load_triager_skill()` and passes it as a `SystemMessage`, single-sourced from `skills/` (mounted at `/srv/skills` in dev, `COPY skills/` in the Dockerfile for prod). 4 reps:
- **0 of 12 anchors out of the allowlist** - all re-anchored UP to `BaseURL`.
- Reps converged identically on the taught insights: `exposed_admin`, `separate_api_surface`, `version_disclosure`.
- The primitives-vs-observations discipline also engaged unprompted: the X-Frame-Options and raw-status restatements were dropped.

### Result

Clean RED -> GREEN achieved by **wiring, not wording**. Edits 1-3's text was already sufficient; it simply never reached the model. No word change was made in Edit 4 (the test passes 0/12 as-is, and adding nuance to a passing recipe risks regressing it). The forward `recon-pipeline-forward-decisions.md` D8 records the deterministic curator-side re-anchor repair as the belt-and-suspenders net for the residual cases the model still gets wrong.
