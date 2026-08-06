# Hunting #66 - CWE REST API probe (extended typing + attribute gaps)

Status: reported artifact (operator-requested task 1); follow-up applied
(fault-KB relevance change). Not a runtime gate.
Date: 2026-08-05 (follow-up 2026-08-06).

The coverage evaluation documented materialisation gaps - most notably
`common_consequences` at 0/419 - with the hypothesis that the data might
have been updated only in the REST API backend
(`https://cwe-api.mitre.org/api/v1/`, manifest
`github.com/CWE-CAPEC/REST-API-wg/blob/main/openapi.json`).
This probe answers: (a) is the typing extended in the API entities, and
(b) are the missing attributes really absent, or recoverable?

## 1. Is the typing extended? Yes - 28 attributes vs our 9

The API `Weakness` schema (openapi.json) exposes 28 properties:

ID, Name, Diagram, Abstraction, Structure, Status, Description,
ExtendedDescription, LikelihoodOfExploit, RelatedWeaknesses,
WeaknessOrdinalities, ApplicablePlatforms, BackgroundDetails,
AlternateTerms, ModesOfIntroduction, CommonConsequences,
DetectionMethods, PotentialMitigations, DemonstrativeExamples,
ObservedExamples, FunctionalAreas, AffectedResources,
TaxonomyMappings, RelatedAttackPatterns, References, MappingNotes,
Notes, ContentHistory.

We materialise 9 of them: id, name, abstraction, status, description,
extended_description, alternate_terms, related_attack_patterns,
likelihood (plus derived fields: parents, tech classes, risks).
Untyped by us: Diagram, Structure, BackgroundDetails,
ModesOfIntroduction, CommonConsequences, DetectionMethods,
DemonstrativeExamples, ObservedExamples, AffectedResources,
TaxonomyMappings, References, MappingNotes, Notes,
WeaknessOrdinalities, ContentHistory.
(CommonConsequences, PotentialMitigations and FunctionalAreas were
untyped at probe time; all three are materialised now - section 6.)

## 2. Light probes: 20 CWEs, 100 attribute probes, 0 mismatches

The API backend reports ContentVersion 4.20 / 2026-04-30 - the same
release as our local `cwec_v4.20.xml`. 20 CWEs (web-relevant plus
non-web controls: 79, 89, 22, 78, 352, 611, 918, 434, 862, 1321, 190,
1333, 134, 787, 364, 403, 75, 300, 114, 841) were fetched via
`GET /cwe/weakness/{ids}` and compared attribute-by-attribute against
the local XML for the five probe attributes {ExtendedDescription,
AlternateTerms, RelatedAttackPatterns, CommonConsequences,
PotentialMitigations}: **0 of 100 probes disagreed**.

Conclusion: the API mirrors the same v4.20 content. For the probed
set there is NO backend-only data - every API attribute is already in
our local XML. The requirement "if the probe returns empty, assert the
attribute missing via the API as well" does not trigger: all probed
attributes are non-empty in the API.

## 3. The real cause: a parser tag-name bug, not missing data

Our curator looks for the legacy singular tag `Common_Consequence`
(`tools/hunting/curate_fault_kb.py:178`); the v4.20 XML uses the
plural `Common_Consequences` (children `Consequence`). The v4.20 XML
contains consequences for **419/419** catalogue CWEs - the parser just
never sees them. Same for `Potential_Mitigations` (children
`Mitigation`): present in the XML for 329/419, untyped by us entirely.

Per-attribute presence in the v4.20 XML across the 419 catalogue CWEs
(correct plural tags):

| Attribute (XML tag) | In catalogue | Of 419 |
| --- | --- | --- |
| Common_Consequences | 419 | 419 |
| Modes_Of_Introduction | 419 | 419 |
| Mapping_Notes | 419 | 419 |
| Weakness_Ordinalities | 419 | 419 |
| Potential_Mitigations | 329 | 419 |
| Taxonomy_Mappings | 323 | 419 |
| Observed_Examples | 304 | 419 |
| Demonstrative_Examples | 251 | 419 |
| References | 236 | 419 |
| Detection_Methods | 212 | 419 |
| Notes | 180 | 419 |
| Affected_Resources | 62 | 419 |
| Functional_Areas | 58 | 419 |
| Background_Details | 35 | 419 |

`Functional_Areas` (CWE's own application-domain tag, e.g. CWE-41 "File
Processing") is NOT low-value prose: it is the application domain a
probe would exercise, directly meaningful for adversarial analysis.
It is reclassified as valuable and materialised with the other two
(section 6).

## 4. Per-CWE genuine gaps (same in XML and API)

The probe table (XML/API agreement) shows source-level absence for
specific CWEs, e.g.: ExtendedDescription absent for CWE-89, 352, 611,
434, 862, 1321, 134, 75, 190, 1333, 787, 918, 841; AlternateTerms
absent for CWE-1321, 134, 75, 364, 114, 841; RelatedAttackPatterns
absent for CWE-787, 364, 403, 841; PotentialMitigations absent for
CWE-918, 841, 403. These are genuine source gaps, identical in both
backends - not enrichable.

## 5. Verdict

- The API typing is extended (28 vs 9 attributes) but the extension is
  fully present in our local v4.20 XML: no backend-only enrichment for
  the probed set.
- `common_consequences` at 0/419 is a parser bug (singular vs plural
  tag); fixing the tag names recovers 419/419 consequences and
  329/419 mitigations offline - no runtime API dependency.
- `potential_mitigations` (329/419) is the operator's feedback item 2:
  it is materialisable from the same XML with a one-line tag fix and
  is a candidate for the typing as the mitigation facet.

## 6. Follow-up applied (2026-08-06)

The recommended follow-up is done, as part of the fault-KB relevance
change (fold + materialisation):

- plural-tag parsing fixed (`Common_Consequences` > `Consequence`,
  `Potential_Mitigations` > `Mitigation`, `Functional_Areas` >
  `Functional_Area`) in `tools/hunting/curate_fault_kb.py`;
- `common_consequences`, `potential_mitigations`, `functional_areas`
  added to the `Weakness` dataclass, the entry schema, and the loader
  facet `FaultMaterialisation` (`src/polymerhus/attack/hunting/
  fault_kb.py`);
- over the materialised 248-entry catalogue:
  `common_consequences` 248/248 (was 0/419 before the fix),
  `potential_mitigations` 211/248, `functional_areas` 43/248.
  (The "of 419" probe figures above count the full CWE catalogue; the
  materialisation facet serves the 248-entry fault catalogue.)
- `Functional_Areas` is reclassified as valuable for adversarial
  analysis (section 3) and materialised accordingly.

The remaining 14 untyped attributes stay untyped: low-value prose for
the fault-matching use-case.
