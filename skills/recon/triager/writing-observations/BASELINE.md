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
