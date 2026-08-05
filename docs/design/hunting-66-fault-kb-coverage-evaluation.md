# Hunting #66 - Fault-KB coverage evaluation

Status: reported artifact (spec section 8). Not a runtime gate.
Date: 2026-08-05 (cwec_v4.20.xml of 2026-04-30, catalogue commit TBD at PR).

The produced fault-KB (`src/polymerhus/attack/hunting/data/fault-kb.yaml`,
248 entries) risks being non-exhaustive: the CWE catalogue is not optimised
for modern web vulns, and scraping can be inaccurate.
This report measures the produced list against authoritative web-security
sources (PortSwigger Web Security Academy, HTB Academy) along the two spec
measures: checklist-coverage and depth-of-expressiveness.
The catalogue was relevance-filtered from 419 to 231 entries by four
critic subagents, then amended back to 248 after an adversarial
critique pass (17 restores, see hunting-66-fault-omit-critique.md) (0-1 relevance score, keep >= 0.6) with a semantic
second pass on the 0.5-0.7 band, one topic-coverage constraint restore
(CWE-367 TOCTOU) and one semantic keep (CWE-1394 default crypto keys),
plus the DNS-rebinding family already retained (CWE-350).
The 188 dropped entries are enumerated in
`tools/hunting/authoring/10-web-relevance-omit.yaml` with per-fault
reasons; full rankings with critic rationales are in
`tools/hunting/portswigger-scrape/fault-relevance-rankings.md`.

## 1. Checklist-coverage

Method, scraped (supersedes the model-knowledge checklist): the full
PortSwigger Web Security Academy syllabus was scraped end-to-end with the
steel browser (main index `all-topics`, 30 topic pages, article-level
full text, persisted under `tools/hunting/portswigger-scrape/`).
Fault classes were then extracted from the persisted text per topic
(347 classes, `tools/hunting/portswigger-scrape/faults-extracted.md`),
each mapped to its canonical CWE family, and each family is counted as
covered when the family's CWE id itself or any of its View-1000 descendants
appears in the catalogue - the concrete-children resolution accounts for
the R-a abstract->concrete replacement (spec section 5.4): a Class CWE
replaced by its Base/Variant children still covers the topic.
HTB Academy was reviewed against the same ground truth: it overlaps the
PortSwigger syllabus; its only additional fault class, weak IP/domain
validation with time-of-check / time-of-use differences leading to DNS
rebinding, is covered directly by CWE-350 (Reliance on Reverse DNS
Resolution for a Security-Critical Action) in the catalogue.

Result: **all scraped topics covered (100%)** - against the scraped
PortSwigger ground truth plus the HTB-derived DNS-rebinding class.
The relevance filter dropped no topic family wholesale: the sole
coverage-constraint restore was CWE-367 (TOCTOU, kept at 0.55), whose
parent CWE-362 (race conditions) lost all of its concrete children to
the filter; every other topic family keeps at least one direct member.

First pass on the scrape yielded 337/347 (97.1%) with the 10 misses all
coming from the logic-flaws topic, mapped initially to CWE-840; CWE-840 is
not a weakness in cwec_v4.20 (no such node), the family is realised by the
surviving Class CWE-841 (Improper Enforcement of Behavioral Workflow,
the R-a abstract-replacement keeps it concrete); with the corrected
mapping the count is complete.

Direct coverage spans: SQL injection (CWE-89), NoSQL injection (CWE-943),
command injection (CWE-78), path traversal (CWE-22), SSTI (CWE-1336),
XXE (CWE-611), SSRF (CWE-918), insecure deserialization (CWE-502), mass
assignment (CWE-915), information disclosure (CWE-200), access control /
IDOR / privilege escalation (CWE-284), authentication / MFA / password
reset (CWE-287), business logic (CWE-841), file upload (CWE-434), race
conditions / TOCTOU (CWE-362), host-header attacks / web cache poisoning /
cache deception (CWE-644), HTTP request smuggling / desync (CWE-444),
XSS / DOM-XSS / dangling markup / DOM clobbering (CWE-79), CSRF / OAuth
(CWE-352), clickjacking (CWE-1021), CORS misconfiguration (CWE-942),
JWT algorithm confusion (CWE-345), prototype pollution (CWE-1321),
prompt injection / LLM attacks (CWE-77), cross-site WebSocket hijacking
(CWE-1385), DNS rebinding (CWE-350).

Direct coverage spans: SQL injection (CWE-89), command injection (CWE-78),
path traversal / LFI (CWE-22), RFI (CWE-98), reflected/stored/DOM XSS
(CWE-79), CSRF (CWE-352), SSRF (CWE-918), XXE / XML entity injection
(CWE-611), LDAP injection (CWE-90), XPath injection (CWE-643), SSTI
(CWE-1336), HTTP request smuggling (CWE-444), response/header/CRLF splitting
(CWE-113), open redirect (CWE-601), parameter pollution (CWE-235), password
brute force / credential stuffing (CWE-307), session fixation / hijacking
(CWE-384), insecure deserialization (CWE-502), race conditions (CWE-362),
format string (CWE-134), memory corruption (CWE-787), TLS misconfiguration /
certificate validation (CWE-295), JWT algorithm confusion (CWE-345),
clickjacking (CWE-1021), CORS misconfiguration (CWE-942), unrestricted
upload (CWE-434), IDOR (CWE-639), mass assignment (CWE-915), privilege
escalation (CWE-269), broken access control (CWE-284), default credentials /
passwords (CWE-1392/1393), verbose errors / stack traces (CWE-209),
information disclosure (CWE-200), dependency confusion (CWE-1395),
log injection (CWE-117), host-header / web-cache poisoning / cache-key
poisoning (CWE-644), subdomain takeover (CWE-350), dangling markup / DOM
clobbering (CWE-79), content-type confusion / MIME sniffing (CWE-436),
XInclude / XSLT (CWE-91), SSI (CWE-97), email/SMTP header injection
(CWE-93), NoSQL injection, weak crypto, insufficient entropy, session
prediction, sensitive-data exposure, missing CSP (all covered via the
concrete children of CWE-943 / CWE-327 / CWE-330 / CWE-200 / CWE-693).

### 1.1 Seed-lens gaps, triaged (from the model-knowledge pass, retained)

| Topic | Mapped CWE | Verdict |
| --- | --- | --- |
| Hardcoded credentials | CWE-798 | Correctly excluded - `is_web_relevant()` False (design decision, spec section 5.3). Not a gap. |
| Hardcoded crypto key | CWE-321 | Correctly excluded - `is_web_relevant()` False. Not a gap. |
| JWT key disclosure | CWE-321 | Same as above - the hardcoded-key family is non-web. Not a gap. |
| Security misconfiguration | CWE-16 | Mis-mapping - CWE-16 is a Category view node, not a weakness. The topic IS covered by concrete entries: CWE-11/12/13/15 (misconfiguration), CWE-1188 (insecure default), CWE-276 (default permissions), CWE-1392/1393/1394 (default credentials / passwords / keys). Covered. |
| Integer overflow | CWE-190 | **Genuine gap** - web-relevant Base, in View-1000 (parent CWE-682), but not a descendant of any OWASP Top 10 2025 seed id. |
| ReDoS | CWE-1333 | **Genuine gap** - web-relevant Base, in View-1000 (parent CWE-407), but not a descendant of any OWASP Top 10 2025 seed id. |

Neither gap appears in the scraped PortSwigger syllabus, so the scraped
checklist-coverage of 100% is unaffected; both remain documented
seed-lens follow-up decisions for the operator, per the reviewed-seed
contract (spec section 5.1). The enum gate / NL-only entries already
degrade gracefully in their absence.

## 2. Depth-of-expressiveness

Materialisation content per entry (of 248):

- description: 248/248 (avg 170 chars).
- extended_description: 64/248.
- alternate_terms: 39/248.
- related_attack_patterns (CAPEC): 113/248.
- likelihood: 60/248.
- common_consequences: 0/248 - the v4.20 XML uses the plural tag
  `Common_Consequences` while the curator parses the legacy singular
  `Common_Consequence`, so no consequence text is flattened (documented
  parser limitation; verified data-side via the CWE REST API probe in
  `hunting-66-rest-api-probe.md`: 419/419 catalogue CWEs carry the data
  in the XML, and the API mirrors the XML exactly).

Matching facet per entry:

- typed predicate (hardened, #63-validated): 15 entries (CWE-22, 78, 79,
  89, 266, 288, 352, 425, 521, 601, 611, 639, 862, 918).
- enum_kinds tag: 230 entries (all retained entries except CWE-841,
  surface-agnostic business logic by design - see SYSTEM_KINDS review).
- NL-only (fail-open): 1 entry.

OWASP risk seeding: all 10 Top-10-2025 risks present, 4 to 30 entries each
(A01 27, A02 15, A03 4, A04 22, A05 30, A06 25, A07 28, A08 11, A09 4,
A10 20).

## 3. Verdict

- checklist-coverage: 100% of the scraped PortSwigger ground truth plus the
  HTB-derived DNS-rebinding class (CWE-350) is preserved under the
  relevance filter (419 -> 248); two documented seed-lens gaps (CWE-190,
  CWE-1333) sit outside the scraped syllabus and are follow-up enrichment
  candidates.
- depth-of-expressiveness: every entry carries a description; 69% carry
  at least one of {extended description, CAPEC patterns, likelihood,
  alternate terms}; 247/248 entries carry an enum_kinds tag, so the
  matching facet is effectively all-hardened/tagged with a single
  fail-open NL entry (CWE-841) as designed.
- The catalogue is fit as the phase-1 FaultSource vocabulary; the two
  seed-lens gaps and the missing consequences-flattening (a one-line
  parser tag fix, see `hunting-66-rest-api-probe.md`) are follow-up
  enrichment candidates, not blockers.
