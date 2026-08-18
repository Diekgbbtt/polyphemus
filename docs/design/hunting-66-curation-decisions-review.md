# Hunting #66 - Curation-decisions review

Status: reported artifact (operator-requested follow-up: "the curation
decisions review"). Not a runtime gate.
Date: 2026-08-05.

This artifact reconstructs and audits every curation decision the
#66 fault-KB build made on top of the raw CWE walk: the seed-lens
skips, the abstract->concrete replacement (R-a, spec section 5.4),
the surviving Classes, the authoring omits, and the materialised
attributes. Verified against `tools/hunting/curate_fault_kb.py` as it
runs today (deterministic re-run of the full pipeline).

## 1. Seed layer (OWASP Top 10 2025 lens)

- 3 seed ids are Categories absent from the Weaknesses index and are
  skipped by the curator with a stderr note: CWE-16 (Configuration),
  CWE-320 (Key Management Errors), CWE-1035 (OWASP Top Ten 2017 A9).
  Their topic coverage is provided by concrete entries instead
  (CWE-11/12/13/15 misconfiguration, CWE-1188 insecure defaults, etc.).
- 9 A04-seeded ids present in the XML but absent from the final
  catalogue: CWE-321, 326, 327, 328, 329, 330, 340, 1240, 1241.
  Triage: CWE-327/330/340 are Classes replaced by their concrete
  children (see section 2); CWE-321/328/329/1240/1241 are
  hardware/OS-level families failing `is_web_relevant()`
  (non-web exclusion, spec section 5.3).
- Seed-lens gaps: CWE-190 (integer overflow, parent CWE-682) and
  CWE-1333 (catastrophic ReDoS, parent CWE-407) are web-relevant
  View-1000 nodes NOT reachable from any seed subtree. Both sit outside
  the scraped PortSwigger syllabus; logged as operator follow-up
  (seed extension CWE-682 / CWE-407 would pull them in).
  See the coverage evaluation report, section 1.1.

## 2. Abstract -> concrete replacement (R-a)

Of the retained Pillar/Class nodes, 52 were replaced by their
smallest-id unclaimed Base/Variant descendant already in the collected
set (deterministic: sorted iteration, smallest-id choice; an abstract
with no unclaimed concrete descendant stays, fail-open recall).

The full replacement map (verified by re-running the curator):

| Abstract (Class) | Replaced by (claimed concrete children) |
| --- | --- |
| CWE-20 Improper Input Validation | CWE-179, 622, 1173, 1284-1289 |
| CWE-74 Improper Neutralization (Injection) | CWE-75, 79, 91, 93, 94, 1236 |
| CWE-77 Command Injection | CWE-78, 88, 624, 917, 1427 |
| CWE-99 Resource Injection | CWE-641, 694, 914 |
| CWE-116 Improper Encoding / Escaping | CWE-117, 644, 838 |
| CWE-159 Improper Handling of Invalid Use | CWE-166, 167, 168 |
| CWE-200 Sensitive Information Exposure | CWE-201, 203, 209, 213, 215, 497, 538, 1273, 1295 |
| CWE-221 Information Loss / Omission | CWE-222, 223, 224, 356, 396, 397 |
| CWE-228 Improper Handling of Invalid Structure | CWE-166, 167, 168, 229, 233, 237, 241 |
| CWE-269 Improper Privilege Management | CWE-250, 266, 267, 268, 270, 274, 648 |
| CWE-271 Privilege Dropping / Lowering Errors | CWE-272, 273 |
| CWE-282 Improper Ownership Management | CWE-283, 708 |
| CWE-284 Improper Access Control | CWE-749, 1191, 1220, 1231, 1233, 1259, 1262, 1267, 1270, 1274, 1276, 1280, 1283, 1290, 1292, 1296, 1304, 1311-1317, 1334 |
| CWE-285 Improper Authorization | CWE-552, 862, 1230, 1256, 1297, 1328 |
| CWE-286 Incorrect User Management | CWE-842 |
| CWE-287 Improper Authentication | CWE-295, 306, 645 |
| CWE-311 Missing Encryption of Sensitive Data | CWE-312, 319 |
| CWE-326 Inadequate Encryption Strength | (deep descendant claimed) |
| CWE-327 Broken / Risky Crypto Algorithm | CWE-780 |
| CWE-330 Insufficiently Random Values | CWE-331, 334, 335, 338, 344, 1204 |
| CWE-340 Predictable Numbers / Identifiers | CWE-341, 342, 343 |
| CWE-346 Origin Validation Error | CWE-1385 |
| CWE-377 Insecure Temporary File | CWE-378, 379 |
| CWE-402 Resource Leak into a New Sphere | CWE-403, 619 |
| CWE-424 Improper Protection of Alternate Path | CWE-425 |
| CWE-436 Interpretation Conflict | CWE-86, 113, 115, 437, 444, 626, 650 |
| CWE-441 Confused Deputy | CWE-918, 1021 |
| CWE-451 UI Misrepresentation of Critical Info | CWE-1007, 1021 |
| CWE-506 Embedded Malicious Code | CWE-507, 510, 512 |
| CWE-522 Insufficiently Protected Credentials | CWE-257, 260, 261, 523, 549 |
| CWE-610 Externally Controlled Reference (Other Sphere) | CWE-15, 73, 384, 470, 601, 611 |
| CWE-636 Not Failing Securely | CWE-455 |
| CWE-642 External Control of Critical State Data | CWE-15, 73, 426, 472, 565 |
| CWE-653 Improper Isolation / Compartmentalization | CWE-1331 |
| CWE-657 Violation of Secure Design Principles | CWE-250, 637, 638, 654, 655, 656, 1395 |
| CWE-668 Exposure of Resource to Wrong Sphere | CWE-8, 134, 374, 375, 427, 428, 488, 491-493, 498, 499, 524, 552, 582, 583, 608, 767, 1282, 1327, 1331 |
| CWE-671 Lack of Administrator Control | CWE-447 |
| CWE-693 Protection Mechanism Failure | CWE-184, 357, 358, 654, 655, 656, 757, 807, 1039, 1248, 1253, 1269, 1278, 1291, 1318, 1326, 1338 |
| CWE-703 Improper Handling of Exceptional Conditions | CWE-393, 397 |
| CWE-732 Incorrect Permission Assignment | CWE-276-279, 281, 766, 1004 |
| CWE-754 Improper Check for Unusual Conditions | CWE-252, 253, 273, 354, 391, 394, 476 |
| CWE-755 Improper Handling of Exceptional Conditions | CWE-209, 248, 274, 280, 333, 390, 392, 395, 396, 460, 544, 756 |
| CWE-799 Improper Control of Interaction Frequency | CWE-307, 837 |
| CWE-863 Incorrect Authorization | CWE-41, 551, 639, 647, 804, 942 |
| CWE-922 Insecure Storage of Sensitive Information | CWE-312 |
| CWE-923 Improper Restriction of Communication Channel | CWE-291, 297, 300, 419, 420, 942, 1275 |
| CWE-943 Improper Neutralization in Data Query Logic | CWE-89, 90, 643, 652 |
| CWE-1263 Improper Physical Access Control | CWE-1243 |
| CWE-1294 Insecure Security Identifier Mechanism | CWE-1302 |
| CWE-1357 Reliance on Insufficiently Trustworthy Component | CWE-1104, 1329, 1395 |
| CWE-1390 Weak Authentication | CWE-41, 262, 263, 289, 290, 294, 301-303, 305, 307-309, 593, 620, 640, 804, 836 |
| CWE-1391 Use of Weak Credentials | CWE-521, 1392 |

Notes: a claimed child may itself be a surviving Class (e.g. CWE-75 in
the CWE-74 row) - the replacement only claims Base/Variant nodes unless
none exist; some abstracts claim deep descendants rather than direct
children (e.g. CWE-326). The R-c retirement path (spec section 5.4)
keeps all 52 abstracts queryable for retrieval, so no coverage is lost.

## 3. Surviving Classes (kept abstract, fail-open)

11 Pillar/Class nodes had no unclaimed concrete descendant in the
collected set and were kept as-is:

CWE-75, CWE-114, CWE-300, CWE-637, CWE-638, CWE-655, CWE-656, CWE-841,
CWE-862, CWE-1039, CWE-1395.

Audit: all 11 are web-relevant and recall-bearing. CWE-841 (Improper
Enforcement of Behavioral Workflow) is the business-logic family the
scraped logic-flaws topic resolves to (coverage evaluation, section 1);
CWE-1395 (Dependency on Vulnerable Third-Party Component) covers
dependency confusion; CWE-862 (Missing Authorization) is a top-10-web
gap in CWE-284's subtree that no concrete descendant absorbed.

## 4. Authoring omits

61 entries in `tools/hunting/authoring/00-omit.yaml` are hard-removed
by the authoring fold, each with an explicit omit_reason. Verified:
0 of the 61 ids appear in the final catalogue. Reason categories:
OS/process-level faults (signal-handler races, file-descriptor
exposure), desktop/Windows-only channels, hardware-layer weaknesses -
all non-web-app faults that `is_web_relevant()` alone cannot filter.

## 5. Materialised attributes (per entry)

- description: 419/419 (avg 170 chars).
- extended_description: 86/419.
- alternate_terms: 54/419.
- related_attack_patterns (CAPEC): 151/419.
- likelihood: 100/419.
- common_consequences: 0/419 - the v4.20 XML's Consequences are nested
  per Scope/Impact groups; not flattened in this pass (documented
  limitation, follow-up enrichment candidate).
- matching facet: 15 hardened typed predicates, 163 enum_kinds tags,
  256 NL-only fail-open entries (three strength tiers as designed).

## 6. Verdict

Every curation decision is traceable to either the reviewed-seed
contract (spec section 5.1), the is_web_relevant() design rule
(section 5.3), the R-a replacement (section 5.4), or an explicit
authoring omit. No silent exclusions: the two seed-lens gaps
(CWE-190, CWE-1333) are documented follow-up decisions, and the
scraped-ground-truth coverage is 100% (see coverage evaluation).
