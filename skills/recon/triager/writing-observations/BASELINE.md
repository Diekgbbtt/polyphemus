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
