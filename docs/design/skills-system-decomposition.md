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
| **W0** - de-spuriation, boundary, decomposition | **Landed, not closed** (43 commits, tip `96fb82a`; `feat/skills-suite` and `feat/232-skill-evolution` are at the same tip) | inventory (30 KEEP / 20 DISCARD, five operator-ruled borderlines); 30 per-skill de-spuriation commits plus `SCREAMING-REPORT.md`; the RDF section drop (`fc90ad3`); high-value-target extraction complete (15 of 15 source classes); group trees folded and dropped (`ssti/references/blind-probe-signals.md` preserved); 29 analyses plus 29 independent reviews; the boundary and ontology documents; 101 variants across 28 classes, all authoring-reviewed PASS; `DECOMPOSITION-REPORT.md`; the suite README | operator ratification of the two `proposed` documents, and the audit findings below |
| **W1** - RDF data model (C2a) | **Partially delivered** (boundary + ontology, not frozen) | the variant decision rule (`skills-variant-boundary.md`) and the notion set, section contract, and entity-to-section mapping (`skills-ontology.md`) | not frozen (`proposed`); the **taxonomy and naming spec** is missing as a designed document (only README prose); the single-data-model-spec role is split across three documents |
| **W2** - cortex (C1) | **Ready to start** | prompt `/Users/diekgbbtt/polymerhus/PROMPT-C1-cortex.md`, now grounded on `skills-ontology.md`; inputs landed | run C1 |
| **W3** - lesson validity gate + SkillEvolver fix (C3) | **Next on the maintainer lane** | inputs landed (the notion set, the boundary); the four adversarial-review rulings remain open (one-revision enforcement, `source_note_ids` audit, `version` semantics, 200 vs 202) | prompt surgery first, then the gate |
| **W4** - nested taxonomy loader (C2b) | **Not started** | the suite README: the loader is still flat, the nested layout is not yet loadable | after W1 ratification |
| **W5** - artifact `skills` field, `load_skill` descriptions, runtime rendering, agent workflows (C5) | **Not started**; workflow ticket **#236** exists | interface decisions settled (operator answers 1/14/15) | needs W2 and W4 |
| **W6** - bypass/proxy technique families (split from C4) | **Ticketed and open: #278** (`workflow`) | extracted material at `skills-unspurious/_migration/bypass-proxy-techniques/low-hanging-fruit.md`; the classes cross-reference the future families at their steps | author the two families |
| **W7** - C4-full enrichment | **Pending, unticketed** | the verbatim algorithm below; sources verified (`~/hacking-skills` 43 files, `~/claude-bug-hunter` 105, `~/anthropic-cybersecurity-skills` 399, `~/awsome-offensive-security-skill` 370) | open a ticket, then author the stream prompt |
| **Carried from #232** | stub landed; four adversarial rulings open | `docs/design/skill-evolution-232-decisions.md`, "Adversarial review findings and open rulings" | C3 resolves or absorbs them |

### W0/W1 audit findings (2026-09-29)

1. **Ratification unmet.** Both design documents still carry `proposed, awaiting operator review`; the W0 acceptance criterion "grilling-confirmed" is not met. The borderline rulings were taken (2026-09-28), the boundary and ontology were not.
2. **Process order inverted.** The W0 prompt ordered grill the boundary, then decompose; the delivered order induced the boundary from the 29 class analyses (`c5b6a91` bundles the analyses with the boundary algorithm). This needs explicit operator acceptance or a review pass over the induced rule.
3. **Stale reports.** `INVENTORY.md` and `SCREAMING-REPORT.md` still say the `llm-prompt-injection` `## Framework-Specific` block "stays, flagged for the agnosticism pass"; commit `fc90ad3` later dropped all non-RDF sections and the current skill carries none. Two report lines contradict the landed state.
4. **Arsenal-gaps ticket missing.** `SCREAMING-REPORT.md` section 3 records the genuine gaps "for a future ticket", but no issue exists (the repo has no arsenal-gap ticket).
5. **Boundary reference missing.** `docs/design/skills-ontology.md` does not reference `docs/design/skills-variant-boundary.md`, violating the ubiquitous-reference rule for documents that concern skills.
6. **Dangling reference.** `docs/design/skills-ontology.md` cites this document by repo-relative path, but it is untracked in the primary checkout and absent from the branch; it must be committed or its unique content migrated into a tracked document.
7. **`two-principal-authz` excluded from decomposition.** Documented as a cross-cutting methodology in both reports; the W0 acceptance criterion said "covers every kept skill", so the exclusion needs ratification or a supplementary analysis.

## Settled decisions (operator rulings, 2026-09-28)

**Streams and integration.** C1, C2, C3, C4, C5 are different streams belonging to different git branches and worktrees; no cross-branch markers are needed; the standard development and integration procedure applies (human-merged PRs).

**Downstream branch base.** Every downstream stream branches off `feat/232-skill-evolution`, never off bare `origin/dev`: that branch carries the skill-evolution stub work (the lesson store, the SkillEvolver, the universal skill binding, the moved corpus) and its documentation, and it contains the shortened dev forwarded by merge `da8ca51` (`origin/dev` @ `2521efc`). The streams consume the stub's contracts, so basing on bare dev would lose them.

**C1 grounds on the landed W0 work (landed 2026-09-29).** C1 has a declared dependency on W0: its prompt assumes the variant boundary (`docs/design/skills-variant-boundary.md`), the ontology and section contract (`docs/design/skills-ontology.md`), and the decomposed suite have already landed on the base branch, and its RDF<->KB mapping section is authored against that landed notion set rather than invented or gated.
Both design documents still carry the status `proposed, awaiting operator review`.

**Dev forward.** All remote `origin/dev` work regarding `rate_limit_posture` is disregarded (it will likely change and was removed from dev by force-update). The #232 branch was forwarded with the remaining dev (merge `da8ca51`, the design-bank reconcile only).

**Cortex (C1).** The cortex is **identical for all agents**; its inherent characteristic is guaranteed by construction: a reasoning flow that names a missing tool must not be exploitable as a dead end.
The caveat: the orchestrator is given the HTTP-history read surface through its own tool and the skill **description-only** surface (`load_skill` with all-or-regex description listing, same tool); it does not get skill bodies or lesson writing.
The cortex is the synergistic placement of the RDF<->KB mapping verbatim.

**KB naming.** "Everything-vulnerability-testing knowledge base" is the existing LightRAG methodology KB (WSTG + writeup overlays), a rename only.

**Pro techniques.** "Pro techniques" means the current "Pro Tips"; they must be abstracted to their technique kind (optimal path / highest-yield surfaces; payload-bank scaffolding; anti-patterns; symptom-emergence modes; impact amplifiers) and projected into the respective type section of the skill.

**Variant rule.** The listed divergence set is confirmed (vuln-specific reconnaissance; attack-surface part family; communication protocol; trust-assumption difference; impact).
The methodology may change only by **extension**, never from the ground up; an explicit, precise boundary description is a W0 grilling concern and lives in its own document.
Skills stay agnostic to technology stack, payloads and payload vectors, and the methodology itself.

**Discard rule.** All skills not covering web-vulnerability testing procedures or relevant network-based bypass/proxy techniques are discarded: the tool skills, the technology skills, and the Windows-AD family.

**Skill naming.** The skill name is precisely the sub-directory holding the `SKILL.md` and its `references/`-`scripts/` directories.

**Pod binding (withdrawn).** The earlier "variant bound to a specific test-executor pod" statement is deferred: underspecified, no workstream/component located.

**Lesson kinds (deferred to W3).** Whether the acceptance kinds replace or extend the current lesson-type vocabulary is a grill point once W3 starts.

**Proactive vs gate.** Only the SkillEvolver carries the acceptance discipline; the recording agents' tool description and the skill-read protocol are unchanged for now.

**Transform semantics.** A transformed lesson is a **revision audit**: the lesson content is replaced.

**Enrichment scope.** The threat-modeller artifacts are out of scope; enrichment involves all the cited repositories except the non-web ones; the algorithm is preserved verbatim below.

**Orchestrator and runtime binding.** The orchestrator gets only the read-all-descriptions capability (same `skill_load` tool). Target agents for skill binding and lesson writing: the hunter and the pod's runner and triager.
Skills are bound to the agents at runtime with the native LangGraph primitives, sourcing from the hunting artifacts that yielded their session, which concretises into the rendering of the skill descriptions into their prompt.

**C2/C4/C5 delivery split.** C2 first delivers the base (solid enough to be consumed by other workstreams already); C4-full enriches it in parallel; C5 delivers the rendering, the context and workflow modification, and the artifact typed-surface change.

**KB mapping lacks.** The missing RDF<->KB type counterparts are intended; the hunter and the pod's runner interpret a lack as a necessity to use the cognitive system described in the cortex, which will most likely end in a knowledge-base query, organically.

## Deferred and open items

- **W3 grill points**: the lesson-kind vocabulary reconciliation; "corrections only to already target-specified skills" scope; the gate's acceptance conditions wording.
- **The pod binding statement** (deferred, see above).
- **`client_side_js_architecture`**: unbuilt; its cortex entry is "not built", with a ticket for integration once it lands.
- **`rate_limit_posture`**: redesign pending; the cortex documents it only when the redesign lands.
- **Threat-modeller migration**: W0 extracts the high-value-target material; the migration itself is out of scope.

## The enrichment algorithm (verbatim, for the W7/C4-full prompt)

The operator's specification, preserved literally for the later prompt:

> establish the base from the purple-swan/skills --> iterate sequentially on each purple-swann/skills by finding relevant skills in the other source repositories by matching on the vulnerability class or reasoning on techniques that can be chained to the skill in object to achieve stronger capabilities in order to enable/simplify/amplify the specific technique --> if the similarity is not sufficient, it reads the skills decomposition strategy that cites the boundary among variants and assess if any of the mentioned attributes diverges from any of the most similar skills matched, if so it writes a new skill proposal into a report document that we will assess afterward, featuring source and [NEW] target skill and extended rationale on the decision (one example that should not match is a second-order IDOR which is missing the baseline skills suite) --> if instead there was sufficient similariy to one skill, macro semantic content diff check --> if any, the resulted diffed content in source skills can be abstracted to one of the skills ontology entities and written cohesively chirurgucally --> if the diff is quite big and captures multiple entities of the ontology, including at least one mentioned in the variants boundary, that could yield a new skill, this assessment must be done as in the previosu step --> finally, move on to references/scripts, assess if sufficiently generalised, if so write them off as examples in references [this is a multiple iteration work, write literally the algorithm as I specified it]

## Provisional glossary

**skill RDF** - the resource description framework of a vulnerability-testing skill: the testing methodology as backbone, surrounded by the ordered notion sections; the authority on what a skill may contain.
_Avoid_: skill template, skill schema.

**notion (RDF section)** - one of the ordered sections a skill is built from (vuln-specific attack surface and reconnaissance, adversarial capabilities, trust assumptions, testing methodology, proxy techniques, bypass techniques, anti-patterns, scripted tests, false positives, chaining).

**variant** - a skill derived from a parent vulnerability class by a genuine divergence in the methodology's technical layer; the divergence variables are the variant boundary's closed set.
_Avoid_: sub-skill, subtype.

**variant boundary** - the explicit, precise decision rule separating a variant from an extension of the same skill; its own document, referenced by every skill document.
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
