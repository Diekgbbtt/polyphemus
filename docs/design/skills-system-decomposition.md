# Skills system decomposition and settled decisions

*Status: **ephemeral working doc** (2026-09-28). This is the cross-stream record of the skills-system reset: the component decomposition, the settled operator decisions, and the provisional vocabulary.
It is the source material for the per-stream prompts and must be superseded by each stream's own ledger as it lands.
It is not a spec and not a glossary of record yet; the glossary below is provisional and migrates into a proper `CONTEXT.md` once the skills system becomes a bounded context.*

## Why this exists

A thorough evaluation concluded that the #232 trajectory risked severe drift toward a low-quality system: coarse skills, tool-verbatim-heavy content, surface-specific material, no acceptance criteria for lessons, and a workflow prompt exposing harness internals.
The operator ruled a step back: grill the design of the underlying data and functional components the skill evolution system builds on.
The decisions already recorded in `skill-evolution-232-decisions.md` (D232-1..14) remain **authoritative unless contradicted by the new design**, and a **drift check** is owed at the end of the new component grilling.

## The components

- **C1 - Cognitive architecture map / cortex.** One shared, dense verbatim (`COGNITIVE_ARCHITECTURE_MAP.md`) living in its own codebase file, identical across all hunting agents, naming every data-layer entity's role and the specific tool that answers each abstract question at each cognitive stage (orchestrator hypothesisation, hunter test engineering, runner execution, triager triage).
  The data layer it covers: working memory/context; L0/L1 attack-surface graph; attack-surface contexts (`auth_context` = the auth store + `auth_store`; `rate_limit_posture`; `client_side_js_architecture`); the everything-vulnerability-testing knowledge base; HTTP request/response history; notes (episodic memory); prior hunting artifacts (`HuntConfig`, `TestImplementationSpec`, `ExperimentLog`, `PodExport`); skills (procedural knowledge).
- **C2 - Skill resource description framework.** The skill data model: backbone **testing methodology**; around it `vuln-specific attack surface and reconnaissance; adversarial capabilities; common trust assumptions; testing methodology; proxy techniques; defence bypass techniques; techniques anti-patterns (including pitfalls); scripted tests with placeholders (references); false positives; chaining`.
  Plus the **variant model**: a divergence in the methodology's technical layer yields a variant; the taxonomy folds variants under the parent class (`web-vulnerability-testing -> ssrf -> ssrf-blind, ...`).
- **C3 - Lesson validity gate + SkillEvolver workflow fix.** Type-specific lesson acceptance conditions, a transform-or-reject gate applying critical-thinking/bias assessment, a lesson scope tied to the RDF notions, and the rework of the SkillEvolver prompt (model-only states, no harness internals, concrete examples).
- **C4 - Well-formed skills suite writing (chained with C2).** De-spuriation ("screaming"), decomposition into variants, adoption of the RDF, and chirurgical enrichment from the local repositories.
- **C5 - Consequent hunting-agent workflow changes.** Artifact `skills` fields, description-only `load_skill`, harness rendering via native LangGraph primitives, hunter concretisation nodes, pod runner/triager lesson sub-phases, RDF<->KB mapping in the cortex.

## The workstreams and dependencies

| Stream | Content | Depends on |
|---|---|---|
| **W0** | C4 phase 1: copy `/Users/diekgbbtt/purple-swan/skills` -> `skills-unspurious/`, de-spuriate one-by-one, grill the variant boundary, decompose | nothing (boundary is its own deliverable) |
| **W1** | C2a: the frozen RDF notion set, variant decision rule, taxonomy + naming spec (the design spec doc) | W0 evidence + boundary |
| **W2** | C1: the cortex (entity -> question -> tool map, per-role reachability, RDF<->KB mapping, pending-integration markers) | W0 (the landed boundary/data-model doc) |
| **W3** | C3: SkillEvolver prompt surgery now; acceptance gate + lesson scope once W1 freezes the notion names | W1 for the gate half |
| **W4** | C2b: nested-taxonomy loader, scaffold, conformance tests, README | W1 |
| **W5** | C5a: `skills` field on both artifacts, `load_skill` descriptions command, `dynamic_prompt` rendering | W1 naming + interface decisions |
| **W6** | C5b: hunter decision nodes, pod lesson sub-phases, cortex + RDF-KB consumption, orchestrator surface | W2, W1, W5 |
| **W7** | C4-full: per-family suite rewrite and enrichment | W1, W4, W0 |

## Status map (2026-09-29, after the W0 landing)

| Stream | Status | Evidence | Blockers / next |
|---|---|---|---|
| **W0** - de-spuriation, boundary, decomposition | **Landed, validated in-session; residual doc debt** (43 commits, tip `96fb82a`; `feat/skills-suite` and `feat/232-skill-evolution` are at the same tip) | inventory (30 KEEP / 20 DISCARD, five operator-ruled borderlines); 30 per-skill de-spuriation commits plus `SCREAMING-REPORT.md`; the RDF section drop (`fc90ad3`); high-value-target extraction complete (15 of 15 source classes); group trees folded and dropped (`ssti/references/blind-probe-signals.md` preserved); 29 analyses plus 29 independent reviews; the boundary and ontology documents; 101 variants across 28 classes, all authoring-reviewed PASS; `DECOMPOSITION-REPORT.md`; the suite README | residual doc debt closed by the W0+W1 completion stream: A1 status lines, A2 stale report lines, A3 boundary reference, A4 tracked cross-stream doc, A5 arsenal ticket #303, A6 open-item refresh; parent conformance was ruled and executed (B2: all 30 parents conformed, D-T7/D-T8); see `w0-w1-completion-ledger.md` |
| **W1** - RDF data model (C2a) | **Delivered** (boundary + ontology validated in-session; the taxonomy and naming spec authored as B1 and merged into the trunk) | the variant decision rule (`skills-variant-boundary.md`), the notion set, section contract, and entity-to-section mapping (`skills-ontology.md`), and the taxonomy and naming spec (`skills-taxonomy.md`, ratified decisions in `skills-taxonomy-decisions.md`) | the single-data-model-spec role stays split across three documents; W4 consumes the spec |
| **W2** - cortex (C1) | **Landed** (cortex built and hardened; the residual register/gaps refresh merged into the trunk) | the design doc `docs/design/cortex-cognitive-architecture-map.md`, the injected verbatim `src/polymerhus/attack/hunting/prompts/COGNITIVE_ARCHITECTURE_MAP.md`, and the contract tests (`tests/attack/test_cortex.py`, 18 passed); the register and gaps re-derived from code in the refresh | carried forward: the hunt-orchestrator description-only surface and request-history grants (W5/W6); `#282` and `#283` integration tickets |
| **W3** - lesson validity gate + SkillEvolver fix (C3) | **Landed** (merged into the trunk; the single review round returned CLEAR with the one fix pass absorbed) | the reconciled decisions (D-W3-1..D-W3-8) in `skill-evolution-w3-decisions.md`; the harness-blind prompt (write-at-end order, read-only grounding, falsification checklist, internal gate); the four read grants; the revision store (manifest plus ordinal snapshots, note keys, old and new version); the version-format fix; the launch plus status pair with the durable pass record | carried forward: the auth_store read-only is prompt-enforced (accepted under D-W3-1); a REST revision-content route (deferred); the reserved name `evolution` |
| **W4** - nested taxonomy loader (C2b) | **Landed** (the mount seam and its conformance tests are merged into the trunk) | `SkillCatalogue` in `src/polymerhus/app/llm/skills.py` (explicit root, logical root identity, flat-leaf indexing, loud duplicate and layout errors, leaf-relative bundles), 16 conformance tests mounting the suite, the README corrections; the single adversarial review round returned CLEAR | carried forward: wiring a mounted suite into the agent surfaces (W5) - CLOSED by the mount replacement (the live root is now the default catalogue) |
| **W5** - artifact `skills` field, `load_skill` descriptions, runtime rendering, agent workflows (C5) | **Landed** (merged into the trunk; the review returned BLOCKED on two majors, both fixed in the one fix pass) | `HuntConfig.skills` and `TestImplementationSpec.skills` chained through the dispatch seams with the project-first union (byte-stable ordering, rebuilt per dispatch); the `load_skill` description-only listing (meta excluded, caps 8/32); the four bindings (hunter/runner/triager full load plus lesson writing; the orchestrator's request-history pair plus the description-only surface); the pod runner/triager prompt skills-synergy; the variant-inheritance fix (SP1) and the CONTEXT.md reconciliation (S1) | carried forward: the mounted-suite wiring - CLOSED by the mount replacement (the agents now resolve the suite through the live-root catalogue, project bundle first); the pre-existing malformed-config run-quiescence wedge (SP3); the sync/rollback hunter lanes bind the baseline only (documented lanes) |
| **W6** - bypass/proxy technique families (split from C4) | **Landed** (merged into the trunk; the review returned CLEAR with one major scope call, ruled by the operator: fix the concrete misses) | the two families (2 parents + 12 leaves, R1-R10 conformant, ~1,900 lines); the C2 sweep (the 13 dangling-reference files, the ruled concrete misses and scan hits in 19 more, the record corrections); the uniform extended-reading pointer in all 123 class bypass sections; `verify.sh` checks 7/8/R9/10 plus the pytest R9 pin; `verify.sh` reaches **ALL-CHECKS-PASS** | carried forward: the mounted-suite wiring - CLOSED by the mount replacement; the malformed-config wedge |
| **W7** - C4-full enrichment | **Landed** (merged into the trunk; the review returned BLOCKED on two majors, both fixed once: the R5 leaf renames and the README record) | the two mining rounds and their rulings; 20 new skills (9 classes, 11 leaves); the seven folds; the enrichment union (~400 edits); 47 references and 13 scripts; the check rewrites (the truthful floor, R3/R9/R10, the pointer) | carried forward: the mounted-suite wiring decision - CLOSED by the mount replacement; the malformed-config wedge, the layout work item (#388, landed), the deferred AI-surface refactor |
| **Carried from #232** | stub landed; four adversarial rulings open | `docs/design/skill-evolution-232-decisions.md`, "Adversarial review findings and open rulings" | C3 resolves or absorbs them |

### W0/W1 audit findings (2026-09-29)

1. **Stale `proposed` status, not missing ratification.** The transcript of `ses_f181eb14bffei9Y8v5O30nGDjG` shows the operator validated the boundary and the 29 analyses in-session ("boundary and skills analysis validated. We can move on to the effective skill writing") and corrected the ontology (trust assumptions as the generative layer, multicast detection channels, Tooling kept). The residual was the status line: both documents said `proposed`, pending operator review, and were updated to the accurate status by A1.
2. **The analyses-then-boundary order was operator-directed.** The operator instructed "After processing all skills you can write it, and I will review it"; this is canonical, not a deviation.
3. **Stale reports (closed by A2).** `INVENTORY.md` and `SCREAMING-REPORT.md` said the `llm-prompt-injection` `## Framework-Specific` block "stays, flagged for the agnosticism pass"; commit `fc90ad3` later dropped all non-RDF sections and the current skill carries none. The two report lines contradicted the landed state and are corrected.
4. **Arsenal-gaps ticket missing (closed by A5).** `SCREAMING-REPORT.md` section 3 recorded the genuine gaps with no issue; they are now filed as #303 and linked from the report.
5. **Boundary reference missing.** `docs/design/skills-ontology.md` does not reference `docs/design/skills-variant-boundary.md`, violating the ubiquitous-reference rule for documents that concern skills.
6. **Dangling reference.** `docs/design/skills-ontology.md` cites this document by repo-relative path, but it is untracked in the primary checkout and absent from the branch; it must be committed or its unique content migrated into a tracked document.
7. **The `two-principal-authz` exclusion was operator-approved** (answer 1b: analyse 29 classes, keep `two-principal-authz` as a cross-cutting reference), and `graphql` passed review as a non-decomposing outlier; only the one-line operator confirmation of the `graphql` outlier is still outstanding.
8. **Parents are not re-authored to the ontology.** W0's open point: the imported class parents keep their imported layout minus the removed sections, while the children use the full ontology contract; whether the parents get a conformance pass is an operator decision.
9. **The round-2 taxonomy map never happened.** The boundary's Q9 answer deferred the sibling-family question (`subdomain-takeover`, `two-principal-authz`, and the #278 families' placement); no taxonomy and naming spec exists beyond the README prose, and W4 consumes one.
10. **The #278 families are referenced but absent.** The children name `defence-bypass` and `proxy-techniques` at their steps; the families do not exist yet (#278 is open).

### Closure status (W0+W1 completion stream, branch `feat/w0-w1-completion`)

- A1 closes findings 1 and 2: the boundary and ontology status lines now record the operator validation; the doctrinal content is untouched.
- A2 closes finding 3: the stale `llm-prompt-injection` `Framework-Specific` lines in `INVENTORY.md` and `SCREAMING-REPORT.md` now record the `fc90ad3` drop.
- A5 closes finding 4: the seven arsenal gaps are filed as #303 and linked from `SCREAMING-REPORT.md` section 3.
- A3 closes finding 5: `skills-ontology.md` and every skill-concern document now reference the boundary.
- A4 closes finding 6: this document is now tracked on the branch and its three citations resolve.
- B4 closes finding 7: the `two-principal-authz` cross-cutting ruling is recorded (`skills-taxonomy-decisions.md`, D-T6); B3 closes the `graphql` outlier confirmation (D-T8).
- B2 closes finding 8: all 30 parents are conformed (D-T7/D-T8); B1 closes finding 9: `docs/design/skills-taxonomy.md` is authored and merged; C1/C2 close finding 10 (the families, next as W6).

## Settled decisions (operator rulings, 2026-09-28)

**Streams and integration.** C1, C2, C3, C4, C5 are different streams belonging to different git branches and worktrees; no cross-branch markers are needed; the standard development and integration procedure applies (human-merged PRs).

**Downstream branch base.** Every downstream stream branches off `feat/232-skill-evolution`, never off bare `origin/dev`: that branch carries the skill-evolution stub work (the lesson store, the SkillEvolver, the universal skill binding, the moved corpus) and its documentation, and it contains the shortened dev forwarded by merge `da8ca51` (`origin/dev` @ `2521efc`). The streams consume the stub's contracts, so basing on bare dev would lose them.

**C1 grounds on the landed W0 work (landed 2026-09-29).** C1 has a declared dependency on W0: its prompt assumes the variant boundary (`docs/design/skills-variant-boundary.md`), the ontology and section contract (`docs/design/skills-ontology.md`), and the decomposed suite have already landed on the base branch, and its RDF<->KB mapping section is authored against that landed notion set rather than invented or gated.
Both design documents now record the operator validation (2026-09-28) in their status lines; see the W0+W1 completion ledger.

**Dev forward.** All remote `origin/dev` work regarding `rate_limit_posture` is disregarded (it will likely change and was removed from dev by force-update). The #232 branch was forwarded with the remaining dev (merge `da8ca51`, the design-bank reconcile only).

**Cortex (C1).** The cortex is **identical for all agents**; its inherent characteristic is guaranteed by construction: a reasoning flow that names a missing tool must not be exploitable as a dead end.
The caveat: the orchestrator is given the HTTP-history read surface through its own tool and the skill **description-only** surface (`load_skill` with all-or-regex description listing, same tool); it does not get skill bodies or lesson writing.
The cortex is the synergistic placement of the RDF<->KB mapping verbatim.

**KB naming.** "Everything-vulnerability-testing knowledge base" is the existing LightRAG methodology KB (WSTG + writeup overlays), a rename only.

**Pro techniques.** "Pro techniques" means the current "Pro Tips"; they must be abstracted to their technique kind (optimal path / highest-yield surfaces; payload-bank scaffolding; anti-patterns; symptom-emergence modes; impact amplifiers) and projected into the respective type section of the skill.

**Variant rule.** The listed divergence set is confirmed (vuln-specific reconnaissance; attack-surface part family; communication protocol; trust-assumption difference; impact).
The methodology may change only by **extension**, never from the ground up; an explicit, precise boundary description is a W0 grilling concern and lives in `docs/design/skills-variant-boundary.md`.
Skills stay agnostic to technology stack, payloads and payload vectors, and the methodology itself.

**Discard rule.** All skills not covering web-vulnerability testing procedures or relevant network-based bypass/proxy techniques are discarded: the tool skills, the technology skills, and the Windows-AD family.

**Skill naming.** The skill name is precisely the sub-directory holding the `SKILL.md` and its `references/`-`scripts/` directories.

**Pod binding (withdrawn).** The earlier "variant bound to a specific test-executor pod" statement is deferred: underspecified, no workstream/component located.

**Lesson kinds (resolved in W3).** The three stored types stay (`specification | extension | defect`); the acceptance conditions became the falsification checklist (`skill-evolution-w3-decisions.md`, D-W3-8).

**Proactive vs gate.** Only the SkillEvolver carries the acceptance discipline; the recording agents' tool description and the skill-read protocol are unchanged for now.

**Transform semantics (superseded 2026-10-18).** A transformed lesson was ruled a revision audit with the content replaced; the W3 round-2 ruling supersedes it: transform-or-reject moves inside the SkillEvolver's chain of thought and the stored lessons remain as-is (`skill-evolution-w3-decisions.md`, D-W3-8).

**Enrichment scope.** The threat-modeller artifacts are out of scope; enrichment involves all the cited repositories except the non-web ones; the algorithm is preserved verbatim below.

**Orchestrator and runtime binding.** The orchestrator gets only the read-all-descriptions capability (same `skill_load` tool). Target agents for skill binding and lesson writing: the hunter and the pod's runner and triager.
Skills are bound to the agents at runtime with the native LangGraph primitives, sourcing from the hunting artifacts that yielded their session, which concretises into the rendering of the skill descriptions into their prompt.

**C2/C4/C5 delivery split.** C2 first delivers the base (solid enough to be consumed by other workstreams already); C4-full enriches it in parallel; C5 delivers the rendering, the context and workflow modification, and the artifact typed-surface change.

**KB mapping lacks.** The missing RDF<->KB type counterparts are intended; the hunter and the pod's runner interpret a lack as a necessity to use the cognitive system described in the cortex, which will most likely end in a knowledge-base query, organically.

## Settled decisions (operator rulings, 2026-10-18)

**Skills-synergic prompts and bindings split.** The hunter and hunt-orchestrator prompt refactoring toward a skills-synergic version is executed by another workstream; the test-executor pod's runner and triager prompt refactoring toward that version is this stream's work (W5).
Regardless of who refactors any prompt, the skills loading and listing capability binding, with the specific tools, for every agent in the hunting module (hunter, hunt-orchestrator, pod runner, pod triager) is this stream's work (W5).

**Artifact-declared skills (#236, settled 2026-10-18).** An artifact-named skill resolves project-first (the catalogue plus project bundles) and unions with the role baseline, which is never displaced; meta-skills are refused; the resolved additions are capped (8) after resolution, so unresolvable names are warned and skipped first, never silently dropped; a triager-minted variant inherits the parent spec's declaration unless it states its own. The orchestrator's surface is the three seam-backed tools plus the HTTP-history read pair plus the description-only listing; no bodies, no lesson writing.

## Deferred and open items

- **W3 grill points**: RESOLVED 2026-10-18 (round 2 closed; D-W3-6..D-W3-8).
- **The pod binding statement** (deferred, see above).
- **`client_side_js_architecture`**: unbuilt; its cortex entry is "not built", with a ticket for integration once it lands.
- **`rate_limit_posture`**: redesign pending; the cortex documents it only when the redesign lands.
- **Threat-modeller migration**: W0 extracts the high-value-target material; the migration itself is out of scope.
- **Suite-wide writing harmonisation**: per-step completion criteria and positive phrasing are applied unevenly across the 30 conformed parents (found in the W0+W1 adversarial review); fold into W7 enrichment.
- **Mounted-suite wiring - LANDED 2026-10-19 (operator-ruled, implemented)**: the enriched suite replaced the live catalogue root.
  The suite's 41 group directories (38 classes plus the R7 cross-cutting group `two-principal-authz`, never counted among the classes, and the `defence-bypass` and `proxy-techniques` families; 165 skills) moved from `skills-unspurious/` into `skills/`; the corpus's 30 flat vulnerability classes were superseded by the enriched groups, while the non-suite corpus skills, the anatomy skills, and the meta family stayed.
  The production surfaces resolve the live root through a lazy `SkillCatalogue` over it: `skill_for`/`list_skills`/`skill_meta`/`validate_skill`, the `SkillStore` reads, the L1 index, `load_skill`, and the artifact-declared `task_skills` all follow the one index (project bundle first; an explicit `catalogue=` still wins).
  Fail-open reads, the per-project precedence, the path-based meta rule, the caps, and the byte-stable ordering are unchanged.
  Evidence: commit `0e201194`; `skills-unspurious/_completion/verify.sh` reaches ALL-CHECKS-PASS against the 41 groups under `skills/`; `tests/recon/test_skill_catalogue.py` and the seam/binding/artifact-skill suites pass; `skills/README.md` carries the merged suite contract and `skills-unspurious/README.md` is now the records note.
  `skills-unspurious/` keeps the stream records (`_migration/`, `_analysis/`, `_authoring/`, `_completion/`, `INVENTORY.md`, `DECOMPOSITION-REPORT.md`, `SCREAMING-REPORT.md`).
- **Malformed-artifact run quiescence - FORMAL QUESTION PENDING (2026-10-19)**: on the trunk's hunting snapshot `run_work_remaining` counts a malformed `ratified` body as work while the dispatch path refuses it, so the run cannot quiesce (SP3 in the W5 review). Dev already carries the fix (`surfer._ratified_config`, the ONE predicate shared by both; the trunk's merge-base `2521efc5`, 2026-09-25, predates it). The dry-run merge of the trunk into dev reports 18 content conflicts, including the hunting module and `app/llm/skills.py`, so the W5/W6 hunting edits need reconciling onto dev's newer dispatch architecture. The disposition question (A: resolve-by-integration plus verification; B: port the fix onto the trunk now; C: both) was presented to the operator 2026-10-19.
- **Layout normalisation (#388) - LANDED 2026-10-19**: six parallel slices restored the reference bold-signature bullet layout across every SKILL.md; the `verify.sh` layout-conformance check (check 11) is now suite-scoped over the live-root group directories; layout and font style only, never content.
- **Documentation alignment (operator, 2026-10-19)**: once the quiescence question is answered, the decision and specification documents plus every impacted `CONTEXT.md` align to the new suite version (the replaced catalogue root, the extended tool surfaces of impacted agents, and the skill-based procedures).

## The enrichment algorithm (verbatim, for the W7/C4-full prompt)

The operator's specification, preserved literally for the later prompt:

> establish the base from the purple-swan/skills --> iterate sequentially on each purple-swann/skills by finding relevant skills in the other source repositories by matching on the vulnerability class or reasoning on techniques that can be chained to the skill in object to achieve stronger capabilities in order to enable/simplify/amplify the specific technique --> if the similarity is not sufficient, it reads the skills decomposition strategy that cites the boundary among variants and assess if any of the mentioned attributes diverges from any of the most similar skills matched, if so it writes a new skill proposal into a report document that we will assess afterward, featuring source and [NEW] target skill and extended rationale on the decision (one example that should not match is a second-order IDOR which is missing the baseline skills suite) --> if instead there was sufficient similariy to one skill, macro semantic content diff check --> if any, the resulted diffed content in source skills can be abstracted to one of the skills ontology entities and written cohesively chirurgucally --> if the diff is quite big and captures multiple entities of the ontology, including at least one mentioned in the variants boundary, that could yield a new skill, this assessment must be done as in the previosu step --> finally, move on to references/scripts, assess if sufficiently generalised, if so write them off as examples in references [this is a multiple iteration work, write literally the algorithm as I specified it]

## Provisional glossary

**skill RDF** - the resource description framework of a vulnerability-testing skill: the testing methodology as backbone, surrounded by the ordered notion sections; the authority on what a skill may contain.
_Avoid_: skill template, skill schema.

**notion (RDF section)** - one of the ordered sections a skill is built from (vuln-specific attack surface and reconnaissance, adversarial capabilities, trust assumptions, testing methodology, proxy techniques, bypass techniques, anti-patterns, scripted tests, false positives, chaining).

**variant** - a skill derived from a parent vulnerability class by a genuine divergence in the methodology's technical layer; the divergence variables are the variant boundary's closed set.
_Avoid_: sub-skill, subtype.

**variant boundary** - the explicit, precise decision rule separating a variant from an extension of the same skill; its own document (`docs/design/skills-variant-boundary.md`), referenced by every skill document.
_Avoid_: decomposition rule (ambiguous), splitting heuristic.

**de-spuriation (screaming)** - the cleanup pass removing spurious verbatims from an imported skill: internal agentic tools, non-arsenal command lines, special contexts, and high-value-target material scheduled for the threat-modeller migration.
_Avoid_: cleaning, sanitising.

**cortex (cognitive architecture map)** - the shared verbatim that names each data-layer entity's role and the tool that answers each abstract question; identical across all hunting agents.
_Avoid_: knowledge map, architecture primer.

**lesson validity gate** - the SkillEvolver-side acceptance discipline that transforms or rejects a lesson against the RDF-notion acceptance conditions, applying critical-thinking and bias assessment.
_Avoid_: lesson filter, lesson linter.

## Drift watch

Existing decisions now under pressure, to be reconciled at the drift check: the lesson `type` vocabulary versus the acceptance kinds; the `10c9a1b` FSM prompt mining (harness states must leave the model prompt); the orchestrator's frozen three-tool surface (reopened by the skill-description and HTTP-history grants); the `RECORD_LESSON_CONTRACT` mirror discipline if the lesson scope parameter lands; the "lesson types are intent hints, never enforced" ruling versus the enforcing gate.

## Provenance

The decisions above were given by the operator in the skills-system reset session (2026-09-28), in reply to the component and dependency report of the same session; the enrichment algorithm quote is verbatim from that reply.

This document was committed to the repository by the W0+W1 completion stream (branch `feat/w0-w1-completion`); before that it lived untracked in the primary checkout, so `docs/design/skills-ontology.md` and the analyses cited a path that did not resolve. The citation resolves from that commit onward.
