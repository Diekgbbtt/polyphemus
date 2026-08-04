# Hunting #66 - Fault-KB coverage evaluation

Status: reported artifact (spec section 8). Not a runtime gate.
Date: 2026-08-04 (cwec_v4.20.xml of 2026-04-30, catalogue commit TBD at PR).

The produced fault-KB (`src/polymerhus/attack/hunting/data/fault-kb.yaml`,
419 entries) risks being non-exhaustive: the CWE catalogue is not optimised
for modern web vulns, and scraping can be inaccurate.
This report measures the produced list against authoritative web-security
sources (PortSwigger Web Security Academy, HTB Academy) along the two spec
measures: checklist-coverage and depth-of-expressiveness.

## 1. Checklist-coverage

Method: a 79-topic checklist of web-application fault classes derived from
the PortSwigger Web Security Academy syllabus and HTB Academy web-attack
modules, each mapped to its canonical CWE family.
Each topic is counted as covered when the family's CWE id itself or any of
its View-1000 descendants appears in the catalogue - the concrete-children
resolution accounts for the R-a abstract->concrete replacement
(spec section 5.4): a Class CWE replaced by its Base/Variant children still
covers the topic.

Result: **73 / 79 topics covered (92%)** - 53 by direct CWE match,
20 via concrete children of an abstract CWE.

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

### 1.1 The six uncovered topics, triaged

| Topic | Mapped CWE | Verdict |
| --- | --- | --- |
| Hardcoded credentials | CWE-798 | Correctly excluded - `is_web_relevant()` False (design decision, spec section 5.3). Not a gap. |
| Hardcoded crypto key | CWE-321 | Correctly excluded - `is_web_relevant()` False. Not a gap. |
| JWT key disclosure | CWE-321 | Same as above - the hardcoded-key family is non-web. Not a gap. |
| Security misconfiguration | CWE-16 | Mis-mapping - CWE-16 is a Category view node, not a weakness. The topic IS covered by concrete entries: CWE-11/12/13/15 (misconfiguration), CWE-1188 (insecure default), CWE-276 (default permissions), CWE-1392/1393/1394 (default credentials / passwords / keys). Covered. |
| Integer overflow | CWE-190 | **Genuine gap** - web-relevant Base, in View-1000 (parent CWE-682), but not a descendant of any OWASP Top 10 2025 seed id. |
| ReDoS | CWE-1333 | **Genuine gap** - web-relevant Base, in View-1000 (parent CWE-407), but not a descendant of any OWASP Top 10 2025 seed id. |

The honest checklist-coverage figure is 92% with two genuine gaps
(CWE-190 integer overflow / wraparound, CWE-1333 catastrophic ReDoS),
both caused by the OWASP-lens entry point: the seed mapping
(`tools/hunting/owasp-top10-2025-seed.yaml`) contains no CWE whose
View-1000 subtree reaches those families, so the walk never collects them.
They are reachable in principle - a seed extension (e.g. adding CWE-682 or
CWE-190, and CWE-407 or CWE-1333) would pull them and their subtrees in.
Left as a documented follow-up decision for the operator, per the
reviewed-seed contract (spec section 5.1); the enum gate / NL-only entries
already degrade gracefully in their absence.

## 2. Depth-of-expressiveness

Materialisation content per entry (of 419):

- description: 419/419 (avg 170 chars).
- extended_description: 86/419.
- alternate_terms: 54/419.
- related_attack_patterns (CAPEC): 151/419.
- likelihood: 100/419.
- common_consequences: 0/419 - the v4.20 XML's Consequences are nested per
  Scope/Impact groups; not flattened in this pass (documented limitation,
  candidates for a follow-up enrichment).

Matching facet per entry:

- typed predicate (hardened, #63-validated): 15 entries (CWE-22, 78, 79,
  89, 266, 288, 352, 425, 521, 601, 611, 639, 862, 918).
- enum_kinds tag: 163 entries.
- NL-only (fail-open): 256 entries.

OWASP risk seeding: all 10 Top-10-2025 risks present, 4 to 30 entries each
(A01 27, A02 15, A03 4, A04 22, A05 30, A06 25, A07 28, A08 11, A09 4,
A10 20).

## 3. Verdict

- checklist-coverage: 92% (73/79), with two documented seed-lens gaps
  (CWE-190, CWE-1333) and zero silent exclusions of web-relevant families.
- depth-of-expressiveness: every entry carries a description; 54% carry
  at least one of {extended description, CAPEC patterns, likelihood,
  alternate terms}; the matching facet spans all three strength tiers
  (hardened / tagged / NL-only) as designed (R-c retirement path).
- The catalogue is fit as the phase-1 FaultSource vocabulary; the two
  genuine gaps and the missing consequences-flattening are follow-up
  enrichment candidates, not blockers.
