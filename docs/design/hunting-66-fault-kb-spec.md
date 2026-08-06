# Hunting spec: the CWE/OWASP web-app fault knowledge base (phase-1 fault vocabulary)

Part of [#54](https://github.com/Diekgbbtt/polyphemus/issues/54) (hunting wayfinder map, Phase-2+ concretisation).
Resolves [#66](https://github.com/Diekgbbtt/polyphemus/issues/66) (fault KB), spawned from the [Q2 fault-source resolution](https://github.com/Diekgbbtt/polyphemus/issues/56).

*Status: spec (decision record + contract) plus the artifact and curation tooling it governs.
This document owns the KB's home decision, its artifact schema, the out-of-band curation algorithm, the two consumer facets, and the typed retrieval seam against the external symptom-technique KB.
The typed `applies-if` predicate CONTRACT is owned by [#63](https://github.com/Diekgbbtt/polyphemus/issues/63) (`docs/design/hunting-63-typed-applies-if-spec.md`); the deterministic engine that evaluates it is [#71](https://github.com/Diekgbbtt/polyphemus/issues/71); this KB carries the predicate per-entry, typed-SHAPED, and does not fork that grammar.*

## 0. Provenance and decision record

- The ticket graduated early from the map's "Not yet specified" fog at operator request (#54).
- The design basis is the operator's illustration of the fault-knowledge system (CWE-via-OWASP, fault-driven selection) and the Q2 fault-source resolution (#56).
- The core home decision (§3 of the implementation brief, the architectural profile halving point) was grilled adversarially and ratified by the operator on 2026-08-03.
- The operator's rulings, in order:
  - **FKB-1 (KB home) - filesystem artifact (Option A).**
    A versioned static artifact in the repo, produced by an offline Python curation script over the local CWE XML, is the KB.
    Option B (a runtime `cwe-tool` proxy retrieving content on the fly plus a Postgres fault catalog) was REJECTED: it contradicts the ticket's own "CWE is never a runtime dependency" invariant, puts the fault list behind a DB read in tension with the unit-tier-never-touches-a-DB rule (`CODING_STANDARD` §10), and introduces a datastore the attack context deliberately avoided (the Hunt store is filesystem, not neo4j, not a new DB - Q8).
    See §3 for the full grill.
  - **FKB-2 (artifact format) - a single structured YAML catalog.**
    One versioned YAML file, one entry per curated CWE, carrying the machine-consumed matching facet (typed-SHAPED `applies-if` + the enum-of-system-kinds gate tag) and the LLM-consumed materialisation facet (rich NL content) side by side.
    Human-diffable, git-reviewable, one authoring seat (aligns with #63 D-C).
  - **FKB-3 (two facets, both first-class).**
    The artifact is read two ways and both are designed as first-class: a MATCHING facet projected into `fault_source.FaultEntry` (predicate + enum gate) for `FaultSource` selection, and a MATERIALISATION facet (extended description, alternate terms, related attack patterns) fed by the prompt-builder into the hunting-agent prompt (`DD-6`/`DD-32`).
  - **FKB-4 (curation is out-of-band).**
    A standalone offline script produces the artifact; CWE is never a runtime dependency and is never fetched at runtime.
    The script's inputs are the local `cwec_v4.20.xml` (the source of record for content and the descendant walk) and a reviewed OWASP Top 10 2025 seed mapping (the entry lens).
  - **FKB-5 (grammar slot ownership).**
    This KB owns `fault` + `applies-if` only.
    The `symptom(s)` + `probing-technique(s)` live in the external, operator-built symptom-technique KB and are never authored here.
    The seam to that KB is a typed retrieval contract, fail-open when the external KB is not ready (§7).
  - **FKB-6 (axis non-conflation).**
    The enum gate keys on the technical-axis System-inventory kinds (`SYSTEM_KINDS`: WAF/CDN/ReverseProxy/...); the external-KB join keys on the technological axis (Springboot/GraphQL/...), which is NEVER a predicate facet.
    The two axes stay lexically and structurally separate.

## 1. Problem statement

Phase-1 `FaultSource` selection (already built, #63/#71) is fault-driven: an outer loop iterates fault-classes and matches each against Service AND System units as candidate loci.
It needs a fault vocabulary to iterate - the "what could be wrong" checklist.
That vocabulary is this KB.
Two consumers read it (§2), and until this ticket the vocabulary did not exist: `fault_source.select` takes a `Sequence[FaultEntry]` but nothing produced one grounded in a real fault catalogue.

This KB is catalogue-grounded and honest: it is the phase-1 ceiling measured by **checklist-coverage** (how completely the curated list covers the known web-app fault checklist), deliberately distinct from the target's real bespoke fault surface (**system-coverage**, analysis phase B, NOT this KB's remit).

## 2. The two consumers and the two facets (FKB-3)

The artifact is designed for exactly two reads, both first-class:

1. **The matching facet - the hunt-orchestrator harness.**
   At selection, the symbolic layer does fault-class applicability checking against a Service/System unit (`fault_source.select` / `evaluate`).
   Each entry projects into `fault_source.FaultEntry(fault_id, predicate, enum_kinds)`:
   - `predicate`: the typed-SHAPED `applies-if` (a `TypedPredicate` when the entry is hardened toward #63, else `None`).
   - `enum_kinds`: the `enum-of-system-kinds` fail-open gate tag (a `frozenset[str]` of `SYSTEM_KINDS`), consulted only for unhardened entries (R-c retires the gate per-entry when the predicate lands).
   The KB feeds this shape VERBATIM; it does not fork the grammar (`predicate.py` / `fault_source.py` own it).
2. **The materialisation facet - the prompt-builder / HuntConfig.**
   Afterward, the prompt-builder feeds each matched CWE's content (extended description, alternate terms, related attack patterns) into the hunting-agent prompt as probe-materialisation grounding.
   This is a content lookup by `fault_id`.

Neither consumer needs SQL, joins, or a search index: the matching facet loads the whole (small) catalogue into memory once; the materialisation facet is a key lookup by `fault_id`.
This is the decisive reason Option A's "custom indexing/retrieval mechanism" drawback does not materialise (§3).

## 3. The home decision, grilled (FKB-1)

### Option A - filesystem artifact (RATIFIED)

A versioned artifact in the repo, sourced offline from the local XML, loaded purely into `FaultEntry` + content-by-id.

### Option B - `cwe-tool` proxy + Postgres catalog (REJECTED)

Use the existing `cwe-tool` (an OWASP Node.js CLI over the CWE database) as a runtime proxy to retrieve content on the fly, keeping a local fault catalog in Postgres, each row carrying a `required_target_system` column (the enum-of-system-kinds pre-filter).

### The grill (weighed against repo values, not dev cost)

- **Ticket invariant.** Option B's "retrieve content on the fly" via `cwe-tool` IS a runtime CWE dependency, which the ticket forbids outright ("CWE is never a runtime dependency ... never fetch CWE at runtime").
  Decisive against B.
- **Unit-tier-no-DB (`CODING_STANDARD` §10, `loop-constraints`).**
  A Postgres-resident catalogue puts the fault list behind a DB read.
  The whole attack context already decided (Q8) its Hunt store is filesystem markdown, not neo4j and not a new DB.
  B introduces a datastore the context deliberately avoided and complicates the fail-open read path.
- **Testability + DI (§6).**
  A: the curation script is a pure offline transform (XML in -> artifact out), unit-testable with a fixture XML slice; the loader is a pure function (file in -> `list[FaultEntry]` + content map), unit-testable with a fixture artifact; no DB, no network.
  B: needs a running Postgres and an external Node process (another language runtime) for any integration test, pushing everything into the live tier.
- **Single-sourced vocabularies (§7).**
  A validates the gate tag and predicate against the analysis constants (`SYSTEM_KINDS`, the #63 validator) at curation time - one source.
  B's `required_target_system` DB column duplicates the vocabulary into a schema that can drift.
- **Robustness / fail-open.**
  A is a static in-repo file (fail-open to an empty KB on a missing/corrupt file).
  B has two live dependencies (Node process + Postgres) that can fail mid-hunt.
- **Alignment with #63 (D-C).**
  The typed predicate is "KB-embedded, one artifact one authoring seat".
  A's single YAML entry carrying predicate + content + tag is exactly that seat; B splits the seat (predicate vs DB rows).
- **Steelman for B.**
  B's genuine merit is a maintained CWE parser plus the `--parent-id --indirect` descendant-walk (precisely the "pull the full web-relevant child set" lowering the ticket wants).
  But `cwe-tool` is stale (last published ~2 years ago, ~6 downloads/week) and is Node.js, a poor runtime dependency for a Python system; its value is fully capturable by using its descendant-walk approach as OFFLINE REFERENCE inside the Python curation script, keeping the runtime a static file.
  Lazy retrieval to save memory is a non-problem at this scale (order 10^2 curated entries).

**Verdict: Option A**, using `cwe-tool`'s descendant-walk only as offline reference.

## 4. The artifact schema (FKB-2)

A single YAML file (the catalogue), a list of entries.
Each entry:

```yaml
- fault_id: "CWE-89"                 # the canonical fault id (CWE id)
  name: "SQL Injection"              # the CWE Name
  abstraction: "Base"               # Pillar | Class | Base | Variant | Compound (provenance for the lowering)
  owasp_2025: ["A05"]              # the OWASP Top 10 2025 risk(s) this entry entered through
  applies_if:                       # THE MATCHING FACET, typed-SHAPED toward #63
    nl: "The unit accepts user-controlled input that reaches a data store or interpreter."
    predicate:                      # OPTIONAL: present only when the entry is hardened (#63). null otherwise.
      target: "Both"               # Service | System | Both
      clauses:
        - form: "reachable-via"
          key: "EXPOSED_VIA"
          values: ["RESTApi", "GraphQLApi"]
  enum_kinds: []                    # THE FAIL-OPEN GATE TAG: technical-axis SYSTEM_KINDS this fault presupposes
  fold_parent: null                 # THE FOLD (selection capture): "CWE-41" for a folded Variant/Compound, null for a selection-tier entry
  materialisation:                  # THE MATERIALISATION FACET, LLM-consumed
    description: "..."             # CWE Description + Extended_Description
    alternate_terms: ["SQLi"]
    related_attack_patterns: ["CAPEC-66"]
    likelihood: "High"            # CWE Likelihood_Of_Exploit (a risk-score facet input)
    common_consequences: ["..."]
    potential_mitigations: ["..."]
    functional_areas: ["..."]
```

Invariants the schema holds:

- `fault_id` is unique across the catalogue (dedupe key).
- `applies_if.nl` is always present (phase-1 authors NL); `applies_if.predicate` is optional and, when present, must validate against the #63 `validate_predicate` grammar (hard-reject at curation time, never at runtime).
- `enum_kinds` is a subset of `SYSTEM_KINDS`, validated at curation time.
- `fold_parent` is null for a selection-tier entry; for a folded Variant/Compound it names a selection-tier Base/Class in the same catalogue (validated at curation time). A folded entry is excluded from the matching facet; its materialisation stays addressable by own id (the recipe keeps its capture's content).
- A hardened entry (predicate present) is projected with `enum_kinds` ignored by the consumer (R-c); an unhardened entry degrades to its tag; an untagged unhardened entry prunes nothing (fail-open, high recall).
- The technological axis NEVER appears as a predicate facet or gate tag (FKB-6).

## 5. The out-of-band curation algorithm (FKB-4)

A standalone offline script (`tools/` or a `scripts/` home, outside the runtime package bound) run manually, producing the YAML catalogue.
Inputs: the local `cwec_v4.20.xml` and a reviewed OWASP Top 10 2025 seed mapping.

Note: CWE v4.20 carries NO OWASP Top 10 2021/2025 view, so the 2025 category -> CWE seed mapping is captured from the OWASP Top 10 2025 site (`https://owasp.org/Top10/2025`) into a reviewed, checked-in seed file (with provenance), NOT scraped at curation time and NOT read from the XML.

The algorithm (the ticket's scrape -> filter -> lower -> dedupe):

1. **Seed.** For each of the 10 OWASP Top 10 2025 risks (A01..A10), take the mapped CWE ids from the reviewed seed file.
2. **Walk the full web-relevant child set (mitigates R-a).**
   For each seed CWE, walk its descendants in the XML `ChildOf` tree (View 1000, the research view) to the concrete web-relevant leaves - not only the ids OWASP directly references.
   Replacing an abstract OWASP category with a hand-picked few children silently narrows coverage; walking to the leaves keeps recall.
3. **Filter.**
   Remove CWE ids irrelevant to web applications (via `Applicable_Platforms` - keep Web-Based / Not-Language-Specific, drop hardware/embedded/language-specific-only-non-web), remove deprecated ids, remove duplicates.
4. **Abstract -> concrete replacement.**
   Replace a retained high-level abstract fault (Pillar / Class) with one of its more concrete descendants already in the collected set (Base / Variant), then deduplicate again.
5. **Extract per-entry content.**
   From each surviving CWE pull the meaningful content for the materialisation facet (Description, Extended_Description, Alternate_Terms, Related_Attack_Patterns / CAPEC, Likelihood_Of_Exploit, Common_Consequences, Potential_Mitigations, Functional_Areas) and the abstraction/OWASP provenance.
6. **Author the matching facet.**
   Every entry gets an NL `applies_if`; entries whose necessary preconditions are L1-typed also get a typed-SHAPED `predicate` (validated) and/or an `enum_kinds` tag; the rest stay NL-only (fail-open).
7. **Fold (the selection tier vs the materialisation tier).**
   A Variant/Compound entry gets a `fold_parent` naming its NEAREST retained Base/Class ancestor along the View-1000 ChildOf chains (BFS, multi-parent aware, cycle-guarded; Variant/Compound waypoints are skipped, so a chain lands on the narrowest retained capture - "taxed as base, not class"). An entry with no retained Base/Class ancestor (an orphan) keeps `fold_parent: null` and STAYS in the selection tier (fail-open recall). Bases/Classes are captures (`fold_parent: null`). The fold-amendments authoring layer (70-fold-amendments.yaml, the overlap-critic pass) may force deviations: `split: true` keeps a folded variant in the selection tier (a genuinely distinct fault class despite its View-1000 capture); `promote: true` ADDS a missing capture to the catalogue (an ancestor the walk never reached) and reverses a web-relevance omit where one exists, so its folded orphans land on it.
8. **Emit.** Write the deterministic, sorted YAML catalogue.

The script is pure and deterministic (same inputs -> byte-identical output), so its output is reviewable in a diff.

## 6. The loader and the two-facet contract

A pure loader module in the hunting context reads the YAML catalogue and exposes:

- `load_fault_entries(path=...) -> tuple[FaultEntry, ...]` - the MATCHING facet, i.e. the SELECTION TIER: each YAML entry projected into `fault_source.FaultEntry`, the predicate parsed and validated (a malformed predicate is a curation-time hard error, surfaced by the loader's own validation, never silently dropped). Folded entries (`fold_parent` set) are FILTERED OUT at read - the fold parent is their capture ("fold at curation, filter at read").
- `load_materialisation(path=...) -> Mapping[str, FaultMaterialisation]` - the MATERIALISATION facet: content by `fault_id` for the prompt-builder, serving ALL entries (selection-tier entries AND folded recipes, the latter carrying their `fold_parent` pointer).

The loader imports no driver and performs no I/O at import; the catalogue path resolves lazily (`CODING_STANDARD` §6).
A missing or malformed catalogue fails open to an empty KB (never crashes the caller), consistent with the fail-open selection contract.

## 7. The typed retrieval seam against the external symptom-technique KB (FKB-5)

The hunting agent queries the external, operator-built symptom-technique KB at spec-writing time for the `symptom(s)` + `probing-technique(s)` of a `(fault-class, unit technological-axis)`.
This KB does NOT author those; it specs the seam only.

- **Query shape** (typed): `SymptomTechniqueQuery(fault_id: str, technological_axis: tuple[str, ...])` - the join key is `(fault-class, unit technological-axis)`.
- **Response shape** (typed): `SymptomTechniqueResult(symptoms: tuple[str, ...], techniques: tuple[str, ...], source: str | None)` - the external KB's internal ontology stays an implementation detail behind this contract, so a swap is a seam change, not a hunting-agent rewrite.
- **Fail-open readiness (external-readiness dependency).**
  The external KB is a parallel operator build.
  Selection / spec-writing must degrade to the fault-KB's own materialisation content when it is not ready, and NEVER crash the caller: a not-ready or erroring external KB returns an empty `SymptomTechniqueResult`.
- **Vocabulary non-conflation (FKB-6, explicit).**
  The enum gate is a pruning attribute on THIS KB's entries keyed on the technical-axis `SYSTEM_KINDS`; the join is a lookup key INTO the external KB keyed on the technological axis.
  The seam's query type carries `technological_axis`; the KB entry carries `enum_kinds`; the two never share a field.

The seam is specced and typed here; its live wiring into a running hunting agent is `designed-not-built` in this ticket (the hunting agent itself is #67/#82), named at the seam, never faked (`CODING_STANDARD` §12).

## 8. Coverage evaluation (the scraping-risk gate)

The produced list risks being non-exhaustive (the CWE catalogue is not optimised for modern web vulns, or the scraping is inaccurate).
The evaluation is qualitative, comparing the produced list against authoritative web-security sources (PortSwigger Web Security Academy, HTB Academy) and reporting two measures:

- **checklist-coverage** - a catalog-vs-catalog coverage percentage (the honest phase-1 ceiling, R-2).
- **depth-of-expressiveness** - does each entry carry enough {description, preconditions, related patterns} for the LLM to both match and later materialise a probe?

The evaluation is a reported artifact (a markdown report under `docs/design/`), not a runtime gate.

## 9. Residual risks carried

- **R-a** abstract->concrete replacement can silently narrow coverage - mitigated by walking the full child set from the XML (§5.2), not hand-picking children.
- **R-b** the external-KB seam + external-readiness dependency + the `(fault, technological-axis)` join; the gate's technical-axis enum and the external KB's technological-axis vocabulary must NOT be conflated (FKB-6).
- **R-c** the fail-open enum gate is imprecise + maintenance-heavy; it retires per-entry on #63 as each entry's typed predicate lands.

## 10. Out of scope

- The typed `applies-if` predicate CONTRACT and its evaluation engine (#63 / #71) - this KB carries the predicate typed-SHAPED, it does not define or evaluate it.
- The symptom-technique KB content and ontology (external, operator-built).
- The LLM match, the yellow `insufficient-evidence` wiring (#64), candidate-minting (#69), the hunt store (#68).
- system-coverage (analysis phase B).
- Live wiring of the external-KB seam into a running hunting agent (#67/#82).

## 11. Testing decisions

- The curation script: unit tests over a fixture XML slice + a fixture OWASP seed - assert the walk pulls the full child set, the filter drops non-web ids, the abstract->concrete replacement fires, dedupe holds, the fold marks a Variant with its nearest retained Base (waypoints skipped, orphans kept fail-open), and the emitted YAML is deterministic.
- The loader: unit tests over a fixture catalogue - assert projection into `FaultEntry` (predicate parsed + validated, enum_kinds subset of `SYSTEM_KINDS`), the materialisation map by id, folded entries excluded from `load_fault_entries` but served (with `fold_parent`) by `load_materialisation`, and fail-open to empty on a missing/malformed catalogue.
- The consumer-parity test: entries loaded from the real catalogue feed `fault_source.select` without a grammar fork (a walkthrough asserting a hardened entry prunes and an unhardened entry degrades to tag/open).
- The retrieval-seam contract: unit tests over a fake external KB - assert the typed query/response shapes and fail-open to an empty result when the KB is absent or raises.
- No unit test touches a DB; the catalogue is a file fixture, the external KB is a fake.

---

*Glossary impact: the terms crystallised by this spec (fault-KB artifact, matching facet, materialisation facet, curation script, checklist-coverage as the KB's metric, the typed retrieval seam) land in `src/polymerhus/attack/hunting/CONTEXT.md` in the same change.*
