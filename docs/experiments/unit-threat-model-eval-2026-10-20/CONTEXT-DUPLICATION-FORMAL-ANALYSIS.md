# Context duplication: formal analysis and merge design

## Summary

The agent contexts contain duplication at three levels: exact byte copies, partial or near-verbatim restatements, and independent prose renderings of a single typed contract.
The strongest exact duplication is the hunter loop surface: 22,470 chars, of which 22,219 chars are the same tool-description text that the request already carries.
The strongest structural duplication is the spec and threat-model surface: the same fields, states, statuses, variants, and gates are authored in prompts, Pydantic models, tool descriptions, and validators.
The strongest semantic collision is the skill family: `skill_list` and `skill_load` (web-vulnerability suite) coexist with `load_skill` (project catalogue), and the hunter system prompt documents only the first pair.
A single target is justified, but it must be a typed context compiler with explicit projections, not one merged prompt.
The first safe tranche is to remove the loop tool surface, generate or delete the hand-written tool summaries, and derive the spec, status, variant, and gate tables from their existing models.
The role-specific judgment, the machine schemas, and the per-session target data must remain as separate projections.

## Scope and method

The analysis covers the LLM agents in the analysis and hunting modules, plus the boundary agents that share their auth, skill, and tool context.

| Module | Agents |
|---|---|
| Hunting | `hunting_threat_modeller`, `hunting_hunter`, `pod_runner`, `pod_triager` |
| Analysis | `bootstrapper`, `assigner`, `mechanism_typist`, `curation`, and the one-shot `anatomy`, `sweep`, `anti_cluttering` roles |
| Shared boundary | `job_orchestrator` (auth gateway), `skill_evolver`, `triager` (recon observation triager) |

The crawler and the deterministic movers, parsers, and curators are out of scope.
They do not carry a role system prompt in the same sense and are not part of the measured first-call set.

The evidence has four sources.

1. The source prompts and prompt loaders in `src/polymerhus/analysis`, `src/polymerhus/attack/hunting`, `src/polymerhus/recon/control`, and `src/polymerhus/app/llm`.
2. The typed contracts: `pod/types.py::TestImplementationSpec`, `spec_contract.py::SpecProvenance`, `spec_contract.py::SkillProcedure`, `hunter_tools.py::SpecWrite`, `hunter_state.py`, `threat_model.py`, `analyser_types.py::L1DeltaBatch`, `pod/variant_basis.py`, `pod/verification.py`, and the auth and skill contracts.
3. The first-call inventories and role averages from `audit_context_occupancy.py` and the prior report `CONTEXT-LIFECYCLE-AUDIT-WHITE-JOTTER.md`.
4. The lexical extractor `audit_context_duplication.py`, which reports exact matching blocks of at least 80 chars, field coverage, tool-name coverage, and shared-tool totals.

The lexical measurements are not semantic verdicts.
A high character overlap is evidence of duplication; a low overlap does not prove semantic independence.
The semantic families below are marked as `E` (exact), `N` (near-verbatim), `P` (partial or field-level), and `S` (semantic or structural).
The per-agent claims use the measured first-call numbers where available and the source text otherwise.

## The duplication model

Seven families recur.

### D1. Exact literal duplication

The same text is served more than once in the same effective context.
The hunter loop tool surface is the clearest case.
The pod prompts also share the 328-char conciseness directive and three exact tool bullets.
The hunter and modeller share a 715-char target-front 5xx paragraph verbatim.
This family is the safest to remove because no semantic judgment is required.

### D2. Near-verbatim restatement

The same rule is written twice with small edits.
The assigner `_FEW_SHOTS` and `assigner.md` share four matching blocks of 93 to 134 chars.
The mechanism-typist `_REFLECTION_STEPS` and `technical-system.md` share three matching blocks of 89 to 107 chars.
The pod runner and pod triager share the same actor-critic and conciseness framing.
This family requires a single editor and a viewed diff, not a blind deletion.

### D3. Partial and field-level duplication

The same field list appears in prose, in a tool description, and in a Pydantic model, but no two copies are byte-identical.
The hunter `## The spec body` is 2,004 chars and names six `TestImplementationSpec` fields.
The spec model has seven fields and the writer model has ten.
The prompt omits `skills` and four `SpecProvenance` fields.
The `## The tools` sections are partial subsets of the actual request tools.
This family is more dangerous than D1 because it looks complete and is not.

### D4. Structural duplication

The same contract is authored in four forms:

- a human prompt;
- a tool description;
- a JSON schema generated from a model;
- a validator or store guard.

The spec, the threat-model states, the L1 delta batch, the variant bases, the terminal reasons, and the observation anchor all have this shape.
The machine schema is necessary.
The hand-written prose copy is the drift source.

### D5. Semantic duplication

The same rule or ontology is expressed with different words in several agents.
Examples are the evidence discipline, the fail-open rule, the degraded-is-not-absence rule, the target-front 5xx rule, the no-bulldozing rule, and the actor-critic separation.
The shared cognitive map is the natural home for the epistemic part.
The role prompts should add role-specific action, not repeat the rule.

### D6. Delivery-path duplication

A single source is rendered through several delivery paths:

- `system_prompt=`;
- a `SystemMessage` in the legacy one-shot leg;
- a `dynamic_prompt` middleware;
- a `HumanMessage` header;
- a response-format tool.

The content can be single-sourced and still appear twice because two paths run in the same turn or because the same object is rendered as a prompt and as a tool schema.
The loop surface is delivery-path duplication.
The direct references plus the full index would be delivery-path duplication.
The `The tools` summary plus the request tools is delivery-path duplication with a stale copy.

### D7. Naming and namespace collision

Two different capabilities share a near-identical name and a similar user-facing verb.
`skill_list` and `skill_load` are the web-vulnerability suite tools.
`load_skill` is the project and catalogue loader.
`write_skill` is the project bundle writer.
`record_skill_lesson` is the lesson recorder.
The hunter system prompt documents the suite pair but not `load_skill`.
The direct-reference line tells the model to use `load_skill`.
The model sees both families in one request.
This is not only duplication; it is a semantic collision.

## The measured first-call picture

The first-call extractor covers nine roles with message input.
The role set is the hunter, modeller, pod runner, pod triager, assigner, mechanism typist, gateway, skill evolver, and recon triager.

The table uses the first call of each role session from the occupancy extractor.
The canonical nav1 hunter reference is separated below because it is a later call with a warm cache.

| Role | System chars | Tool chars | First input tokens | Cache read | Shared tool chars | Tool share |
|---|---:|---:|---:|---:|---:|---:|
| hunting_hunter | 27,920 | 37,325 | 26,857 | 0 | 20,828 | 33.7% |
| hunting_threat_modeller | 23,297 | 36,820 | 17,076 | 14,336 | 18,342 | 56.0% |
| pod_runner | 9,227 | 20,770 | 8,789 | 0 | 16,386 | 56.2% |
| pod_triager | 11,226 | 19,580 | 10,732 | 0 | 15,947 | 44.7% |
| assigner | 12,831 | 17,411 | 8,747 | 8,704 | 13,611 | 46.6% |
| mechanism_typist | 24,580 | 21,770 | 15,530 | 4,096 | 17,970 | 33.5% |
| job_orchestrator | 6,037 | 15,827 | 5,515 | 0 | 12,468 | 69.4% |
| skill_evolver | 18,034 | 21,030 | 11,180 | 0 | 21,030 | 45.9% |
| triager | 10,264 | 11,089 | 6,649 | 5,248 | 10,513 | 43.1% |

The totals across those first calls are:

- 454,198 raw chars, including the 20-char analysis assembly row;
- 143,416 system chars, or 31.6%;
- 201,622 tool chars, or 44.4%;
- 147,095 shared tool chars, or 73.0% of the tool text and 32.4% of all first-call chars.

The nine message-bearing rows sum to 454,178 chars.
The extractor total is 454,198 chars because it also sees the 20-char analysis assembly row.

The shared pack counts `load_skill`, `record_skill_lesson`, `auth_store`, `graph_view`, the HTTP pair, `exec`, `query_lightrag`, and `write_skill`.
It excludes the suite pair `skill_list` and `skill_load`, and it excludes the role-specific `hunts_store`, `notes`, `note`, `replay`, `L1DeltaBatch`, `TriagerDecision`, `GatewayVerdict`, and `_ObservationBatch` entries.
The tool surface is larger than the system surface.
The shared tool pack is the largest single source of repeated text.
The shared pack is not the same as a bug: each agent that binds a tool needs the request schema.
The avoidable part is the prompt summary and the loop copy, not the request schema itself.

The hunter first call is the reference point for D1.
It is 104,119 chars and 24,840 input tokens.

| Hunter first-call component | Chars | Share |
|---|---:|---:|
| system | 27,920 | 26.8% |
| application overview | 1,761 | 1.7% |
| loop payload | 35,491 | 34.1% |
| request tool schemas | 37,325 | 35.9% |
| framing | 1,622 | 1.6% |

The role-first table and the canonical nav1 reference differ.
The role-first hunter call is 110,930 chars and 26,857 uncached tokens.
The nav1 reference is 104,119 chars and 24,840 input tokens, with 16,128 cache-read tokens.
The nav1 reference is used for the component and duplicate measurements below.
The role-first call is used for the aggregate totals.

The loop payload contains a 22,470-char tool surface.
22,219 of those chars are the same description text as the request tools.
The tool text across the loop and the request is 59,544 chars, or 57.2% of the first call.
The first call is 64.9% cache read.
The loop surface alone is 5,361 uncached tokens, or 61.5% of the 8,712 uncached input.
This is the strongest measured case for removal.

The system prompt itself is 27,920 chars.
The body is 16,088 chars, including the 8,084-char pass sequence.
The worked examples are 9,263 chars.
The cognitive map is 1,488 chars.
The skill index is 1,081 chars in the trial.
The direct-reference change replaces the index with a 248-char line and takes the system to 27,085 chars.
The system is not the only fixed cost, and it is largely cached on the hunter.
The uncached loop and the request tool surface are the higher-value targets.

## Cross-agent overlap matrix

The letters are the dominant class in that agent: `E` exact, `N` near, `P` partial, `S` semantic, and `-` absent.

| Family | Hunter | Modeller | Pod runner | Pod triager | Assigner | Typist | Boot | Curation | Gateway | Evolver | Recon triager |
|---|---|---|---|---|---|---|---|---|---|---|---|
| shared cortex | E | E | E | E | E | E | - | - | - | - | - |
| application overview | E | E | - | - | E | E | - | - | - | - | - |
| conciseness directive | E | - | E | E | - | - | - | - | - | - | - |
| target-front 5xx rule | E | E | - | - | - | - | - | - | - | - | - |
| spec fields | P | S | P | P | - | - | - | - | - | - | - |
| pass and workflow | S | S | S | S | - | - | - | - | - | - | - |
| L1 ontology and edges | - | - | - | - | S | S | S | S | - | - | - |
| skill procedure and variant bases | P | P | P | P | - | - | - | - | - | - | - |
| threat-model states | S | E | - | - | - | - | - | - | - | - | - |
| auth context | P | P | P | P | P | P | - | - | P | P | P |
| skill namespace | S | S | S | S | S | S | - | - | S | S | S |
| tool contracts | E | E | E | E | E | E | - | - | E | E | E |
| role and task | S | S | S | S | S | S | S | S | S | S | S |
| examples | S | - | - | - | N | S | S | - | - | S | - |
| output schema | P | E | P | P | P | P | P | P | P | P | P |

The matrix shows why a string deduper is insufficient.
The tool contracts are one source with many renders.
The spec, pass, L1, variant, and output rows are structural.
The cortex, overview, and example rows are mixed: some are exact copies, some are single-source renders, and some are role-specific teaching material.

## Per-agent analysis

### 1. Hunter

**Sources.** `src/polymerhus/attack/hunting/prompts/hunting-agent.md`, `prompts/examples.md`, `prompts/COGNITIVE_ARCHITECTURE_MAP.md`, `hunting_agent.py::_load_hunting_agent_skill`, `hunting_agent.py::_compose_first_step`, `hunter_tools.py`, `hunter_state.py`, `spec_contract.py`, `hunter_tools.py::SpecWrite`, and `pod/types.py::TestImplementationSpec`.

**Measured overlap.**

| Overlap | Evidence | Class | Impact |
|---|---|---|---|
| loop tool surface vs request tool descriptions | 22,470 chars vs 22,219 chars; 5,361 uncached tokens | E | Highest exact cost; 61.5% of uncached first-call input |
| system `## The tools` vs bound tools | 1,028 chars; 7 names vs 12 actual; 5 missing | P | The model reads a stale subset of its own surface |
| `## The spec body` vs spec models | 2,004 chars; missing `skills`, `run_id`, `source_recon_refs`, `assumption_ref`, `playbook` | P | The model is not told about writable fields |
| `The tree` and `The passes` vs `hunter_state` | 1,001 + 8,084 chars; 8 passes; 7 hints | S | The state machine is described three times |
| examples vs spec and pass contract | 9,263 chars; 8 pass labels and the reduced spec shape | S | Teaching material repeats the machine contract |
| target-front 5xx rule vs modeller | 715 exact chars | E | One rule in two role prompts |
| conciseness directive | 328 chars in the prompt and the notes tool | E | One directive in two delivery paths |
| skill index / direct references | 1,081 old index; 248 direct line | E/P | The index is removed by the direct-reference change |
| cognitive map | 1,486 chars | E | Shared with five other agents |

The hunter has the clearest **exact** bug and the clearest **triplication** bug.
The model sees the tool surface in three forms: the system summary (7 names), the loop catalog (12 names and 22,470 chars), and the request schemas (12 names and 37,325 chars).
Only the request schemas are complete and machine-checked.
The loop catalog is a generated copy of the same descriptions.
The system summary is hand-written and stale.

The spec surface is worse than a duplicate.
It is a **partial schema with omissions**.
The canonical pod model has `target_identity`, `verification_symptoms`, `assumptions`, `rationale`, `parent_spec_ref`, `provenance`, and `skills`.
The writer adds `status`, `fault_keyword`, and `strategy_keyword`.
The prompt names the first six but omits `skills`.
The prompt names six provenance fields but omits `run_id`, `source_recon_refs`, `assumption_ref`, and `playbook`.
The `run_id` is bound by the tool, so its omission from the human list is defensible.
The other omissions are not explained.
The pod runner later refers to a `skills` declaration that the hunter prompt never described.
This is a **semantic join failure**, not only a copy.

**Proposed join.**
The hunter should receive a `RoleSpec`, a `ProjectContext`, the shared `Cortex`, a `WorkflowSpec`, a `ToolPack`, a `SpecContract`, an `ExamplePack` on demand, and a `DisciplineBlock`.
The workflow spec generates the compact pass table and the phase hints.
The spec contract generates the human field table and the request schema from one model.
The tool pack generates one-line catalog entries for the loop and the system, and the request schemas remain the only full contract.
The examples move to `load_skill` or a help projection.
No hand-written `## The tools`, `## The spec body`, `The tree`, `The passes`, or loop tool surface remains.

### 2. Threat modeller

**Sources.** `prompts/threat-modeller.md`, `threat_modeller.py`, `threat_modeller_tools.py`, `threat_model.py`, `threat_model_store.py`, and the shared cortex.

**Measured overlap.**

| Overlap | Evidence | Class | Impact |
|---|---|---|---|
| five states and gates | 5 states; 5 gate sections in the prompt, the `hunts_store` description, `GATE_SECTIONS`, `ModelSections`, and the store validator | S | Four independent renderings of one state machine |
| reference fields | the prompt table vs `ModelSections` references and store resolution | S | The prompt is a partial human copy of the model |
| `hunts_store` description vs prompt | 1,210-char description; 14,903-char schema; prompt 21,702 | P | The prompt repeats the gate contract in prose |
| `## Tools` vs bound tools | 9 documented names vs 10 actual; `record_skill_lesson` missing | P | One bound tool is absent from the prompt |
| completion and drop rules | prompt and store validation | S | The same completion and drop semantics in prose and code |
| target-front 5xx rule | 715 exact chars shared with hunter | E | One rule in two prompts |
| cognitive map | 1,486 chars | E | Shared with five agents |
| skill index | 107 chars | P | Project skill reference |

The modeller is the strongest example of **state and schema duplication**.
The tool schema alone is 14,903 chars, or 22.6% of the first call.
The tool total is 36,820 chars, or 56.0% of the first call.
The prompt is 21,702 chars, or 35.4% of the first call.
The system is 23,297 chars.
The five-state prompt is not the only place a state or section is named.
`GATE_SECTIONS`, `ModelSections`, `ModellerHuntsStoreArgs`, the `_HUNTS_STORE_DESCRIPTION`, the prompt, and the store validator each encode part of the same contract.
The `## Tools` summary also omits `record_skill_lesson`.
The **target-front 5xx rule** is exact with the hunter, and the **conciseness directive** is absent from the prompt but present in the notes tool description.
The documentation claim that the directive is in four role prompts is inaccurate; it is in three prompts and several tool descriptions.

**Proposed join.**
The modeller should receive a `RoleSpec`, `ProjectContext`, `Cortex`, `ThreatModelContract`, `ToolPack`, and `DisciplineBlock`.
The threat-model contract owns the five states, six sections, references, completion rules, and validation.
The prompt keeps the reasoning method for each gate and the drop policy, but not a second field list.
The `hunts_store` request schema is the machine contract.
The completion rules are stated once in the contract and referenced by the prompt.
The 5xx and conciseness rules move to the shared discipline.

### 3. Pod runner

**Sources.** `prompts/pod-runner.md`, `pod/prompts.py`, `pod/agents.py`, `pod/context.py`, `pod/tools.py`, `pod/note_tool.py`, `spec_contract.py`, and `pod/types.py`.

**Measured overlap.**

| Overlap | Evidence | Class | Impact |
|---|---|---|---|
| spec prose vs spec models | prompt spec paragraph vs `TestImplementationSpec`, `SpecProvenance`, and pod validation | P | The prompt lists a subset of the D4 contract |
| `# Tools` vs bound tools | 7 documented names vs 8 actual; `auth_store` missing | P | The largest bound tool is not in the prompt |
| conciseness directive | 328 chars in the prompt and the `note` tool | E | Exact shared text |
| pod runner / pod triager tool bullets | 232 + 191 exact chars | E | The same tool usage text in two prompts |
| memory guidance | prompt `# Memory` vs `compose_memory_guidance` and the note contract | S | Three statements of the same read rule |
| variant constraints | prompt constraints vs `VARIANT_BASES` and `SkillProcedure` | S | The seven procedure bases are listed again |
| cognitive map | 1,486 chars | E | Shared with five agents |
| skill index | 1,081 chars | P | Project skill reference |

The pod runner has a **hidden tool** problem.
The bound tools include `auth_store` at 6,364 chars, but the prompt's `# Tools` does not mention it.
The model sees the schema and can call the tool, but the prompt does not say when or why.
The same is true for the pod triager, and for the analysis roles.
The `# Memory` section says the key list and the note reading contract arrive in the lap opener, while `compose_memory_guidance` also emits them.
The spec paragraph says the spec is the reduced D4, but it lists only some D4 fields and later refers to a `skills` declaration that the list omits.
The `provenance` paragraph says the dispatch context and the class-skill excerpt, while `SpecProvenance` has ten fields.
The `skill_procedure` is rendered once in the current pod context through the CL-3 projection, which is the correct precedent.
The rest of the spec is still repeated.

**Proposed join.**
The runner should receive a `RoleSpec`, a `ProjectContext` with the spec, a `ToolPack`, a `SpecContract`, a generated `WorkflowSpec` for P0-P3, and a `DisciplineBlock`.
The spec contract renders a three-line "what you receive" summary and the request schema.
The tool pack documents every bound tool, including `auth_store`, or removes it if the capability is not intended.
The memory and note rules are owned by the note contract and the context guidance, not the prompt.
The conciseness text is composed from the shared directive.

### 4. Pod triager

**Sources.** `prompts/pod-triager.md`, `pod/agents.py`, `pod/context.py`, `spec_contract.py`, `pod/variant_basis.py`, `pod/verification.py`, and `pod/types.py`.

**Measured overlap.**

| Overlap | Evidence | Class | Impact |
|---|---|---|---|
| ten variant bases | 10-row prompt table vs `VARIANT_BASES`, `PROCEDURE_GAP_FIELD`, and the first-uncovered diff | S | The prompt table is a hand copy of the code contract |
| seven procedure fields | `SkillProcedure` and the prompt's `What you read` / variant table | P | The seven fields are named in three places |
| decision vocabulary | 5 terminal reasons in the prompt vs `validate_decision` and `TriagerDecision` | S | The binary guard is described and enforced separately |
| `# Tools` vs bound tools | 4 documented names vs 7 request entries; `graph_view`, `auth_store`, and `TriagerDecision` missing | P | Two callable read-only tools are undocumented |
| auth capability | full 6,364-char `auth_store` contract on a critic role that has no write need; prompt does not mention it | P/E | Capability over-grant and silent contract |
| conciseness directive | 328 chars | E | Exact shared text |
| pod tool bullets | 232 + 191 exact chars | E | Shared with the runner |
| skill procedure rendering | CL-3 renders the typed procedure once | P | The one good existing dedup; the rest of the spec remains duplicated |
| cognitive map | 1,486 chars | E | Shared with five agents |

The triager is the strongest example of **enum-to-prompt duplication**.
The ten variant bases are a typed tuple, a mapping to the seven procedure fields, a deterministic diff, and a prompt table.
The prompt table is useful because the model must choose a basis, but it must be generated from the same tuple.
The five terminal reasons are described in the prompt and enforced in `validate_decision`; the schema and the guard are the authority.
The `TriagerDecision` schema is the output contract; the prompt describes its fields.
The prompt names four tools in `# Tools`, but the request has seven entries.
The two undocumented callables are `graph_view` and `auth_store`.
The `TriagerDecision` entry is the response format, not an external tool.
The prompt's "You never touch target" remains true for `graph_view`, which is read-only, but the model needs the explicit permission.

**Proposed join.**
The triager should receive a `RoleSpec`, a `ProjectContext` with the spec and observation, a `ToolPack`, a `PodContract`, and a `DisciplineBlock`.
The `PodContract` owns `SkillProcedure`, `VARIANT_BASES`, `PROCEDURE_GAP_FIELD`, and the terminal vocabulary.
It generates the variant table, the coverage assessment, and the decision vocabulary from one model.
The `TriagerDecision` schema is the response format.
The CL-3 single render of the skill procedure is the model for the other fields.
The prompt keeps the critic judgment and the third-party stance, not the field tables.

### 5. Assigner

**Sources.** `analysis/assigner.py` (`_ROLE_VERBATIM`, `_FEW_SHOTS`, `_system_prompt`), `analysis/prompts/assigner.md`, `analysis/analyser_types.py::L1DeltaBatch`, `analysis/messages.py`, and `analysis/proposer_turn.py`.

**Measured overlap.**

| Overlap | Evidence | Class | Impact |
|---|---|---|---|
| `_ROLE_VERBATIM` vs `assigner.md` | 1,660 + 9,105 chars; same ownership rules and output contract | S | Two independent role statements |
| `_FEW_SHOTS` vs `assigner.md` | 1,223 chars vs 2,070-char examples section; four exact blocks of 93 to 134 chars | N | The same three examples in two sources |
| `L1DeltaBatch` output | 3,800-char schema; prompt says "call L1DeltaBatch" and "aggregates only" | P | The output contract is authored in three places |
| `## The four moves` vs `_ROLE_VERBATIM` | same null hypothesis, differential, discrimination, and grounding | S | The HOW layer repeats the WHAT layer |
| `## Tools` coverage | actual 6 entries; `load_skill`, `record_skill_lesson`, `auth_store` missing from the prompt | P | Three bound tools are undocumented |
| HTTP history seam | prompt section vs `search_http_history` / `get_http_artifact` descriptions | S | The read-only rules are stated twice |
| overview and cortex | 1,761 + 1,486 chars | E | Shared with other agents |
| examples | 2,070 chars in the prompt | S | The same shape as `_FEW_SHOTS` |

The assigner has a deliberate WHAT/HOW split.
The split is not the problem.
The problem is that the WHAT layer is a second, independently edited copy of the HOW layer, and the `_FEW_SHOTS` path is a third copy of the examples.
The default `skill` configuration serves `_ROLE_VERBATIM` plus `assigner.md`; the `baseline` configuration serves `_ROLE_VERBATIM` plus `_FEW_SHOTS`.
Only one path is active at a time, but both are maintained.
The prompt also documents only three of the six request entries.
The auth and skill tools are bound but not described.
The `L1DeltaBatch` schema is the output contract; the prompt's "call the tool" is a usage rule, not a second schema.
The four moves add reasoning discipline that the WHAT layer should not repeat.

**Proposed join.**
The assigner should receive a `RoleSpec`, an `AnalysisContract`, an `ExamplePack`, a `ToolPack`, and a `DisciplineBlock`.
The role spec owns the identity and the ownership task.
The analysis contract owns `L1DeltaBatch` and the aggregate projection.
The example pack owns one copy of the four examples; the baseline and skill variants become projections of the same examples.
The tool pack documents every bound tool.
The null hypothesis and the differential stay in the role prompt as the role-specific judgment; they do not need a second copy in the role verbatim.

### 6. Mechanism typist

**Sources.** `analysis/prompts/technical-system.md`, `analysis/mechanism_typist.py` (`_REFLECTION_STEPS`, `_reflection_prompt`, `_systems_prompt`, `_linking_prompt`), `analysis/proposer_reasoning.py`, and `analysis/analyser_types.py`.

**Measured overlap.**

| Overlap | Evidence | Class | Impact |
|---|---|---|---|
| `_REFLECTION_STEPS` vs `technical-system.md` | six-step process; three exact blocks of 89 to 107 chars; same orient, hypothesise, verify, integrate, emit | N/S | The reasoning process is authored twice |
| `role_header` vs the system opening | the reflection prompt repeats the role and goal already in the system | N | The model sees the role statement twice in one turn |
| `vocabulary_prompt` | repeated in the reflection, systems, and linking messages and the system output contract | S | The L1 vocabulary is rendered four times |
| output contract vs `L1DeltaBatch` | edge labels and fields in the prompt and the schema | P | The schema is the machine contract |
| tool coverage | actual 8; `load_skill`, `record_skill_lesson`, `auth_store` missing from the prompt | P | Three bound tools are undocumented |
| examples | 7,863 chars, eight exemplars | S | The exemplars teach the same output shape |
| overview and cortex | 1,761 + 1,486 chars | E | Shared with other agents |
| skill index | 576 chars | P | Project skill reference |

The typist has the most explicit double reasoning source.
The system prompt contains the hypothesis-driven process.
The reflection human message contains `_REFLECTION_STEPS`, which repeats the same process.
The prompt also contains `## Output contract` and the edge vocabulary; the `_systems_prompt` and `_linking_prompt` each repeat the defined systems and the vocabulary.
The code comment in `_systems_prompt` says the reflection is deliberately not re-embedded to avoid a prior N2 prose triplication.
That is the right instinct, but it is applied to only one of the repeated surfaces.
The role header is a second, smaller repeat.
The tool descriptions add 21,770 chars, 33.5% of the first call.
The system is 24,580 chars, 37.8% of the first call.
The fixed tax is 77.6% of the average context.
The exemplars are 7,863 chars.
The process should have one source.
The role header should not repeat the system role.
The vocabulary should be generated from the L1 contract and rendered once.

**Proposed join.**
The typist should receive a `RoleSpec`, an `AnalysisContract`, a `ReasoningScaffold`, a `ToolPack`, an `ExamplePack`, and a `DisciplineBlock`.
The reasoning scaffold lives in one place, either the prompt or the human turn, not both.
The role header is removed.
The analysis contract owns `SYSTEM_KINDS`, the edge labels, `L1DeltaBatch`, and the vocabulary.
The example pack is on demand.
The prompt keeps only the mechanism-typing judgment and the system-link discipline.

### 7. Bootstrapper

**Sources.** `analysis/bootstrap.py` (`_BOOTSTRAPPER_BASE_SYSTEM`, `_FEW_SHOT`, `_FEW_SHOT_EXTRA`, `default_reason_fn`, `default_extract_fn`, `_load_bootstrapper_skill`), `analysis/prompts/bootstrapper.md`, and `analysis/overview.py`.

**Measured overlap.**

| Overlap | Evidence | Class | Impact |
|---|---|---|---|
| base + prompt | 1,496 + 5,759 chars; the base owns identity and output, the prompt owns the five stages and contract craft | S | The split is deliberate; the two layers overlap on the service contract |
| five stages vs few-shot | the prompt's five stages and the few-shot's five steps | N | The same reasoning shape twice |
| service contract | `bootstrapper.md` "Write a service contract" and `default_extract_fn` "SERVICE CONTRACT..." | P | The extraction prompt repeats the contract craft |
| overview | `overview.py` renderer and the bootstrapper's own `## Overview` instruction | S | The writer is told how to write the object that the renderer later formats |
| `BootstrapElicitation` | base output contract and extraction schema | P | The output is described in prose and schema |

The bootstrapper's WHAT/HOW split is intentional and stronger than the assigner's.
The remaining duplication is the **service contract craft** in the prompt and the extraction prompt.
The first call reasons over the KB; the second call extracts the shells.
The second call receives the reasoning, so it already has the content.
It does not need a second full explanation of the service contract.
The five-stage few-shot is a teaching device; it can stay, but it should be one exemplar registry rather than a list embedded in the code path.
The `## Overview` rules are a producer instruction; the `overview_message` renderer is a consumer projection.
The two are not the same copy; the producer must know what makes a good overview, and the consumer must know the final shape.
The report treats them as a **contract-to-projection pair**, not a duplicate.

**Proposed join.**
The bootstrapper should receive a `RoleSpec`, an `AnalysisContract`, an `ExamplePack`, an `ExtractionContract`, and a `DisciplineBlock`.
The base identity and the five stages become the role spec.
The service-contract craft moves to the analysis contract and is referenced by the extraction prompt.
The example pack owns the few-shot exemplars.
The overview remains a project data object with its own producer and consumer rules.

### 8. Curation

**Sources.** `analysis/curation.py`, `analysis/prompts/curation.md`, and `analysis/curation_types.py::CurationBatch`.

**Measured overlap.**

| Overlap | Evidence | Class | Impact |
|---|---|---|---|
| "the reasoning discipline above still binds" | `curation.md` line 9; `default_propose_fn` sends only `_load_curation_skill()` as the system message | P | The prompt refers to a base that is not in its context |
| curation rules vs `CurationBatch` | the prompt's YAML shapes and the schema | P | The output is described in prose and model |
| dedup, prune, relabel, rehome | the prompt's four sections | S | The four operations are the schema's four fields |
| no tool context | the curation role is a one-shot structured call with no tool pack | - | The role has no tool summary to drift |

Curation has a **missing join**, not a duplicate.
The prompt says "the reasoning discipline above still binds".
The code sends only the curation prompt.
Unless the prompt is composed with a base elsewhere, the model sees a dangling reference.
The curation prompt is 5,138 chars.
The output model is `CurationBatch`.
The YAML examples and the schema overlap.
The role should either include an explicit base or remove the reference.
The four operations are the role's judgment and should stay; they should be backed by the schema, not replaced by it.

**Proposed join.**
The curation role should receive a `RoleSpec`, an `AnalysisContract` with the shared evidence discipline, an `OutputContract` for `CurationBatch`, and a `DisciplineBlock`.
The dangling reference is removed by composing the base once.
The YAML examples are generated from the schema or moved to an example pack.
The four reconciliation operations stay in the role prompt.

### 9. Auth gateway

**Sources.** `recon/control/prompts/auth-gateway.md`, `recon/control/orchestrator_agent.py`, `app/auth/tool.py`, `app/llm/skills.py`, and the live project `authn` skill.

**Measured overlap.**

| Overlap | Evidence | Class | Impact |
|---|---|---|---|
| gateway procedure vs `authn` skill | 5,459-char gateway prompt; 15,872-char project authn bundle; gateway loads the skill and also restates ground, retrieve, validate, sign-in | S | The procedure is authored twice |
| auth store contract | 6,364-char full contract vs gateway prompt's store rules | S | The domain model and write rules repeat |
| tool coverage |7 actual; 4 names not in the prompt, though Steel, Kali, and the verdict are described semantically | P | The tool names and the prompt prose can drift |
| authn skill | project-specific; loaded at runtime | P | The prompt must be the decision and verdict, not a second procedure |
| `load_skill` contract | direct references and the catalog | S | The gateway is a skill consumer |

The gateway is a boundary case, but it is the clearest **procedure duplication**.
The prompt tells the model to load the project `authn` skill.
It then explains the same authentication procedure in its own sections.
The `authn` skill is 15,872 chars, and it is loaded in the same turn.
The auth-store contract is 6,364 chars and also describes the domain model.
The gateway prompt is 5,459 chars.
The model can receive the procedure three times: the prompt, the skill, and the store contract.
The verdict schema is the output.
The gateway should load the skill and use it; the prompt should own the gateway decision, the branch selection, and the verdict.
The auth-store contract should be the one tool contract, not a second procedure.
The `auth_store` capability is full read/write, which the gateway needs.
The skill evolver and recon triager are different; see below.

**Proposed join.**
The gateway should receive a `RoleSpec`, an `AuthContext`, a `SkillPack`, a `ToolPack`, and a `VerdictContract`.
The `AuthContext` owns the auth store contract and the project `authn` skill reference.
The gateway prompt owns the decision and the verdict.
It does not repeat the sign-in procedure.
The `load_skill` result supplies the procedure.
The auth-store tool is the single domain contract.

### 10. Skill evolver

**Sources.** `app/llm/prompts/skill_evolver.md`, `app/llm/evolver.py`, `app/llm/skills.py` (`SKILL_LOAD_CONTRACT`, `WRITE_SKILL_CONTRACT`), `app/auth/tool.py`, and the `meta-write-skill` skill.

**Measured overlap.**

| Overlap | Evidence | Class | Impact |
|---|---|---|---|
| workflow vs tool contracts | prompt "The workflow", "The single write", and "Loop discipline" vs `SKILL_LOAD_CONTRACT` and `WRITE_SKILL_CONTRACT` | S | The write and load rules are authored twice |
| authoring discipline vs `meta-write-skill` | prompt loads the meta skill and also states smallest edit, evidence, no sediment | S | The authoring rules are in two sources |
| examples | 5,984 chars, three worked examples | S | The examples repeat the workflow |
| auth capability | prompt says `auth_store` read-only; request carries the 6,364-char full read/write contract | P/E | The prompt and the tool capability disagree |
| tool coverage | 7 actual; all 7 named in the prompt | - | The names match; the contract semantics still overlap |
| skill load contract | 1,905 chars; "Mirrors skills/README.md" | P | Two documentation sources |

The evolver has a **capability mismatch**.
The prompt says the pass only ever reads the auth store.
The request carries the full read/write `auth_store` contract, 6,364 chars.
The model is told one thing in the prompt and another in the tool schema.
The analysis roles use the 3,386-char read-only contract.
The recon triager also carries the full 6,364-char contract despite its read-only role.
This is a safety and semantic bug, not only a duplication.
The authoring discipline is also duplicated between the prompt and the loaded `meta-write-skill`.
The prompt should load the discipline and not restate it.
The write and load contracts are the tool contracts; the prompt should not repeat their rules.

**Proposed join.**
The evolver should receive a `RoleSpec`, a `SkillAuthoring` context, a read-only `AuthContext`, a `ToolPack`, and an `ExamplePack`.
The `SkillAuthoring` object owns the write discipline and the load protocol.
The prompt owns the falsification and bias judgment.
The auth store is bound in the read-only variant, matching the prompt.
The examples are on demand.
The `SKILL_LOAD_CONTRACT` and `WRITE_SKILL_CONTRACT` are the machine/tool contracts, not prompt copies.

### 11. Recon triager

**Sources.** `recon/domain/prompts/writing-observations.md`, `recon/domain/curator.py` (`ANCHOR_ALLOWLIST`), the `_ObservationBatch` schema, and the recon `triager` role.

**Measured overlap.**

| Overlap | Evidence | Class | Impact |
|---|---|---|---|
| anchor rule | the five types appear in "The anchor rule", "Common mistakes", and "Red flags" | S | The same closed set three times in one prompt |
| observations versus vulnerabilities | four sections restate the "not a vulnerability report" rule | S | The same boundary repeated |
| anchor set vs code | prompt five types vs `ANCHOR_ALLOWLIST` and the schema | P | The prompt is a hand copy of the code allowlist |
| macro kind vocabulary | prompt list vs the schema/curator | P | The vocabulary is a second source |
| tools | actual 4; `load_skill`, `record_skill_lesson`, `auth_store` missing from the prompt | P | Three bound tools are undocumented |
| conciseness | the prompt has no hunting conciseness; its own "short" rule | S | The writing discipline is local |
| observation schema | `_ObservationBatch` 576 chars; prompt describes the payload | P | The schema is the machine contract |

The recon triager is a high **internal** duplication case.
The prompt is 9,855 chars, and much of it restates one rule in several forms.
The repeated forms may be pedagogical, but the same five-type allowlist and the same "not a vulnerability" boundary appear four times.
The code owns `ANCHOR_ALLOWLIST`; the prompt should be generated from it.
The schema is `_ObservationBatch`; the prompt should describe only the judgment that the schema cannot express.
The tool summary omits the skill and auth tools.
The prompt is a good candidate for compression without losing the role's judgment.

**Proposed join.**
The recon triager should receive a `RoleSpec`, an `ObservationContract`, a `ToolPack`, and a `DisciplineBlock`.
The observation contract owns the five anchor types, the macro-kind vocabulary, and `_ObservationBatch`.
The prompt keeps one anchor section, one "not a vulnerability" section, and the judgment examples.
The tool pack documents the three bound tools.
The allowlist is generated from the code, not hand-written.

### 12. One-shot analysis roles

**Sources.** `analysis/anatomy.py`, `analysis/sweep.py`, and the anti-cluttering path, together with `analysis/analyser_types.py`, `analysis/l1_types.py`, and `analysis/bootstrap.py::SYSTEM_KINDS`.

**Scope.** The `anatomy`, `sweep`, and `anti_cluttering` roles are one-shot structured calls.
They do not have a separate `prompts/*.md` system file in the same way as the four proposers.
They share the L1 ontology and the `L1DeltaBatch` or `CurationBatch` output families.
The report treats them as **consumers of the same analysis contract**, not as independent duplication sources.

**Risk.** The risk is the same as the assigner and typist: the L1 kinds, edge labels, and output fields can be copied into a one-shot human prompt even when the schema already carries them.
The target is the same `AnalysisContract`.
No separate prompt copy is recommended.

## The one target merge component

The target is one typed component, not one prompt.
Call it the **AgentContextCompiler**.

It has four parts:

- `ContextCatalog`: the single home for every semantic object.
- `ContextPlan`: an ordered set of projections per agent.
- `ProjectionRenderer`: the machine, catalog, human, help, and example renderers.
- `ContextManifest`: the object IDs, source paths, projection hashes, and consumer list.

The catalog holds these objects:

| Object | Current sources | Consumers | Projections |
|---|---|---|---|
| `RoleSpec` | `providers.ROLES` / `HUNTING_ROLES`; role prompts; `_ROLE_VERBATIM`; `role_header` | all | system role, task, output stance |
| `ProjectContext` | `settings.application_overview`; `AuthStore`; `ROLE_SKILLS`; project id | all bound agents | overview message, auth view, direct refs |
| `ToolContract` | tool classes, `args_schema`, `http_history_contract`, `auth/tool`, `skills.py` | all tool agents | request schema, catalog, help |
| `SpecContract` | `TestImplementationSpec`; `SpecProvenance`; `TargetIdentity`; `SpecWrite`; `SkillProcedure` | hunter, runner, triager | machine schema, human table |
| `ThreatModelContract` | `GATE_SECTIONS`; `ModelSections`; store validators; prompt states | modeller, hunter | gate table, completion rules |
| `AnalysisContract` | `L1DeltaBatch`; `l1_types`; `SYSTEM_KINDS`; edge relations; `CurationBatch` | bootstrapper, assigner, typist, curation, one-shot | fields, vocabularies, output |
| `WorkflowSpec` | `hunter_state`; `variant_basis`; pod P0-P3; decision vocabulary | hunter, pod | pass table, hints, variant table |
| `SkillPack` | `ROLE_SKILLS`; `SkillStore`; `SKILL_LOAD_CONTRACT`; `SKILL_REFERENCE_HEADER`; `SKILL_LIST_HEADER`; `README` | all bound agents | direct refs, listing, usage, write |
| `AuthContext` | `AUTH_STORE_CONTRACT`; `AUTH_STORE_READ_CONTRACT`; `authn` skill; gateway prompt | all auth agents | full, read-only, procedure |
| `OutputContract` | Pydantic models | every agent | schema, table, response format |
| `ExamplePack` | prompt examples; `_FEW_SHOTS`; `_FEW_SHOT`; evolver examples | hunter, assigner, typist, bootstrapper, evolver | on-demand examples |
| `DisciplineBlock` | `conciseness`; cortex rules; 5xx; evidence; fail-open | all | one stable block |
| `Payload` | loop, spec, chunk, unit projection, observation | each session | volatile user message |

The catalog is the only writer.
The role prompt is a `ContextPlan`, not a source file that restates the catalog.

## Join rules

The following rules turn the catalog into a merge.

1. **One semantic home.**
A field, enum, state, tool, skill, or rule has one owning object.
Every other appearance is a projection or a reference.

2. **Five renderers.**
`machine` is the Pydantic JSON schema.
`catalog` is a name, a one-line purpose, and the capability variant.
`human` is a short generated field table.
`help` is the full usage contract on demand.
`example` is a worked shape on demand.
No prompt owns a second full copy.

3. **The request schema is necessary.**
The model needs the machine schema to call the tool.
The compiler must not remove the request schema.
It must remove the prompt summary, the loop surface, and the hand-written help.

4. **The loop catalog is one line per tool.**
The hunter loop should say `Tool surface: hunts_store, notes, graph_view, ...`.
It should not repeat 22,219 description chars.
If the model needs the full description, it is in the request tool schema.

5. **The spec prompt is a generated field table.**
`The spec body` is a human projection of `TestImplementationSpec`, `SpecProvenance`, and `TargetIdentity`.
It must include `skills`, or the writer must remove `skills` from the writable surface.
It must state which fields are bound (`run_id`) and which are optional.
The machine `SpecWrite` is a projection of the canonical spec plus status and keywords; it is not a second full model.

6. **The status, gate, variant, and terminal tables are generated.**
`SpecStatus`, `PASS_SEQUENCE`, `VARIANT_BASES`, `PROCEDURE_GAP_FIELD`, `GATE_SECTIONS`, `ANCHOR_ALLOWLIST`, and the terminal vocabulary are the source.
The prompt tables are rendered from them.
A test fails when a prompt literal is not in the source.

7. **The skill namespace is split.**
The suite pair becomes `vuln_class_list` and `vuln_class_load`.
The catalogue loader stays `load_skill`.
The writer stays `write_skill`.
The lesson recorder stays `record_skill_lesson`.
The system prompt and the direct references use the same names.
The suite index and the project direct refs are separate projections of the `SkillPack`.

8. **The auth capability is explicit.**
`AuthContext` has `full` and `read_only` variants.
The binding and the prompt use the same variant.
The gateway uses `full`.
The analysis proposers use `read_only`.
The pod triager, skill evolver, and recon triager use `read_only` unless a real write need is proven.
The full contract is not given to a prompt that says "read only".
The pod triager currently receives the full 6,364-char contract even though it is a critic.

9. **The shared disciplines are stable blocks.**
`Concision`, `Evidence`, `FailOpen`, `DegradedNotAbsent`, `TargetFront5xx`, and `NoBulldozing` are IDs in the `DisciplineBlock`.
The cortex owns the epistemic core.
The role prompt adds the role-specific action.
The exact 5xx paragraph is removed from both hunter and modeller and replaced by the block.

10. **The examples are on demand.**
The hunter examples, the assigner examples, the typist exemplars, the bootstrapper few-shot, and the evolver examples are `ExamplePack` entries.
They can be loaded through `load_skill` or a help projection.
The system prompt keeps one compact reasoning shape per role, not the full example set.

11. **The target data is a projection, not an authored duplicate.**
The application overview is a `ProjectContext` projection for the hunter, modeller, assigner, and typist.
It is not removed from a session that needs it.
The compiler renders it once per session and caches the stable prefix.

12. **The cache layout is part of the contract.**
The stable prefix is the role, the project context, the discipline block, and the tool catalog.
The volatile payload is the loop, spec, chunk, unit, or observation.
The request schemas sit at the request layer.
The examples are outside the stable prefix.
The compiler records the prefix hash and the volatile hash.

## Migration sequence

The migration should be small, testable, and reversible.

### Phase 0. Manifest and linter

- Add the `ContextCatalog` manifest with object IDs and source paths.
- Add a lexical linter for exact blocks of at least 80 chars.
- Add a tool-name coverage test.
- Add a spec-field coverage test.
- Add a status, gate, variant, anchor, and terminal generation test.
- Do not change any prompt yet.

### Phase 1. Exact and stale removal

- Remove the loop tool surface.
- Replace the hunter system `## The tools` with the generated catalog, or remove it.
- Generate the pod `# Tools` sections from the bound pack.
- Compose the conciseness directive from the shared block; remove the prompt copy.
- Remove the 5xx paragraph from both role prompts and use the shared discipline.
- Replace the full skill index with the direct-reference projection in every role.
- Keep the request tool schemas.

This phase removes 22,470 loop chars and the stale summaries.
It changes no reasoning instruction beyond deleting the duplicate.

### Phase 2. Schema-derived prompts

- Generate the hunter and pod spec tables from `TestImplementationSpec`, `SpecProvenance`, and `TargetIdentity`.
- Resolve `skills`: keep it, document it, or remove it from the writable surface.
- Generate the modeller gate and section table from `GATE_SECTIONS` and `ModelSections`.
- Generate the variant and terminal tables from `VARIANT_BASES` and `PROCEDURE_GAP_FIELD`.
- Generate the L1 fields and edge labels from `L1DeltaBatch` and the L1 vocabulary.
- Generate the observation anchor and macro-kind list from `ANCHOR_ALLOWLIST` and `_ObservationBatch`.

This phase removes the partial and stale prose copies.
The prompt keeps the judgment that the schema cannot carry.

### Phase 3. Role-prompt consolidation

- Merge `_ROLE_VERBATIM` and the assigner prompt into one role spec.
- Keep one example pack; remove the `_FEW_SHOTS` duplicate.
- Remove the typist `role_header` and choose one home for `_REFLECTION_STEPS`.
- Remove the repeated vocabulary from the systems and linking human messages.
- Move the service-contract craft out of the extraction prompt.
- Add the missing curation base, or remove the "above" reference.
- Make the gateway load the `authn` procedure and keep only the decision and verdict.
- Make the evolver load `meta-write-skill` and keep only the judge role.
- Compress the recon triager's repeated anchor and observation rules.

This phase preserves the role-specific judgment.
It removes the independently edited prose copies.

### Phase 4. Skill and auth namespaces

- Rename `skill_list` and `skill_load` to `vuln_class_list` and `vuln_class_load`.
- Keep `load_skill`, `write_skill`, and `record_skill_lesson`.
- Generate the direct references from `ROLE_SKILLS`.
- Use one `SkillPack` projection per role.
- Bind `auth_store` read-only for the evolver and recon triager unless a write need is proven.
- Bind full `auth_store` for the gateway and the hunting agents that write.
- Generate the auth prompt from the binding variant.

### Phase 5. Examples, system prompt, and cache

- Move the full examples to the `ExamplePack`.
- Keep one compact reasoning shape in each system prompt.
- Apply the system-prompt Variant A or Variant B from the prior analysis; do not decide it here.
- Keep the stable prefix stable; keep the payload volatile.
- Measure the first call and the cache read.
- Do not run a new trial without authorisation.

### Phase 6. Tool-description slimming

- Slim the request descriptions to the target environment, the data contract, and the success and error semantics.
- Keep the parameter schema.
- Move the full usage contracts to the help projection.
- This phase is the highest remaining semantic risk; it needs the user decision and a future trial.

## Acceptance criteria

- The tool-name coverage test reports zero missing names for every bound agent.
- The spec-field coverage test reports zero missing fields, or the field is explicitly non-writable.
- The `skills` field is either documented or removed.
- The `run_id`, `source_recon_refs`, `assumption_ref`, and `playbook` fields have an explicit human projection or an explicit non-writable reason.
- `SpecStatus`, `PASS_SEQUENCE`, `VARIANT_BASES`, `PROCEDURE_GAP_FIELD`, `GATE_SECTIONS`, `ANCHOR_ALLOWLIST`, and the terminal vocabulary have one source and generated tables.
- The exact-block linter finds no unallowlisted block of at least 80 chars across two sources.
- The loop surface is absent.
- The system tool list is generated or absent.
- The `auth_store` binding matches the prompt's capability.
- `skill_list` and `skill_load` are renamed; `load_skill` is the only catalogue loader.
- The first-call tool text contains only request schemas and a compact catalog.
- The stable prefix hash is unchanged across turns; the volatile payload is separate.
- The context manifest lists every consumer and source.
- The combined test suite passes.
- No new trial is run without authorisation.

## Critical assessment

### Summary

The core claim is correct in direction: the agent contexts carry extensive duplication, and a single typed context compiler is the right target.
The strongest evidence is exact and structural, not merely intuitive.
The weakest part of the claim is the assumption that every repeated semantic is waste; some repetitions are necessary projections, examples, or per-session target data.

### Key issues

1. **The hunter loop copy is a confirmed bug.**
The 22,219 exact description chars are duplicated in the loop and the request.
It is 5,361 uncached tokens, or 61.5% of the uncached first-call input.
The fix is safe and should be first.

2. **The triplication claim needs one correction.**
The system `## The tools` is not a full copy of the request tools.
It is a stale, partial summary: 7 names versus 12.
The bug is worse than duplication because the model's own tool summary is incomplete.
The fix is generation, not just deletion.

3. **The spec duplication is a partial schema bug.**
The prompt is 2,004 chars and omits `skills` and four provenance fields.
The writer model and the pod model are separate full field lists.
The fix is a single spec contract and a generated table.
This is more important than the literal copy because it can cause missing fields.

4. **The status, gate, variant, and terminal contracts are hand-copied.**
The typed enums and models already exist.
The prompt tables are not derived from them.
The drift risk is high across the modeller, hunter, pod, analysis, and recon roles.

5. **The skill namespace collision is semantic.**
`skill_list` and `skill_load` are not the same family as `load_skill`.
The hunter system documents the suite pair but not the catalogue loader.
The direct references use the catalogue loader.
The model must infer the difference from the schemas.
Renaming is the smallest correct fix.

6. **The auth capability mismatch is a safety issue.**
The evolver prompt says read-only; the request carries the full read/write contract.
The recon triager carries the full contract despite a read-only role.
The pod triager also carries the full contract despite being a critic with no write need.
The analysis roles use the correct read-only variant.
The binding, not the prompt, must enforce the capability.

7. **Some duplication is justified.**
The cortex is a shared map; the application overview is target data; the request schema is the machine contract; the role-specific judgment is not replaceable by a generic prompt.
The merge must generate projections, not collapse the distinctions.

8. **The analysis reasoning process is authored twice.**
`_REFLECTION_STEPS` and `technical-system.md` encode the same orient, hypothesise, verify, integrate, and emit process.
The `role_header` repeats the system role.
The vocabulary is repeated in the reflection, systems, and linking messages.
One home is enough.

### Questions to probe

1. Which duplicated text is load-bearing for model compliance: the examples, the prompt tool summaries, or the full tool descriptions?
An ablation or future trial is required; this analysis cannot prove the behavioural effect of removal.

2. Is `skills` an intended hunter output?
If yes, the hunter prompt must document it and the pod must use it.
If no, remove it from the writable surface.
The current state is inconsistent.

3. Are `graph_view` and `auth_store` intentionally bound to the pod triager and the analysis roles?
If yes, document them and name the read-only capability.
If no, remove them.
The current state is silent.

4. Which auth procedure is canonical: the gateway prompt or the project `authn` skill?
The loaded skill should be the procedure, and the gateway prompt should be the decision and verdict.

5. Is the `The tools` summary meant to be complete, or a hint?
A hint is acceptable only if it is generated from the bound pack; a complete summary must be generated and tested.
A stale hand-written subset is not acceptable.

6. What is the tolerance for semantic duplication?
The linter can catch exact and near-verbatim blocks.
The semantic families need a reviewed manifest, not an automated equivalence claim.

### Bottom line

The duplication is real, but the highest-value target is not a larger prompt or a tool-response offload.
It is a typed `AgentContextCompiler` with one home per contract and explicit machine, catalog, human, help, and example projections.
The first fixes are the loop surface, the stale tool summaries, the partial spec table, and the hand-copied status and variant tables.
The role-specific judgment and the machine schemas must remain.
A future trial must validate the behavioural effect before the tool descriptions and examples are cut.

## Limitations

- The first-call measurements come from one trial and one set of role sessions.
- The lexical extractor measures exact blocks of at least 80 chars; it does not prove semantic equivalence.
- The semantic labels are human judgments based on the source and the contract models.
- The 163-turn modeller inputs are truncated near 261k chars in the stored evidence; the first-call and source-field measurements are not affected.
- The role averages are from the prior occupancy run; the source-level findings do not depend on them.
- The curation base composition is inferred from `default_propose_fn`; the report flags the dangling reference for confirmation.
- The gateway and evolver comparison uses the live project `authn` bundle and the prompt contracts, not a new gateway trial.
- The one-shot analysis roles do not have a measured first call in the same set; the report treats them as contract consumers.
- The proposed compiler is a design, not an implemented component.
- No new trial was run; no tool-description or example change is claimed to be behaviour-neutral.

## Appendix A. Measured duplication ledger

| Item | Measurement | Class |
|---|---:|---|
| hunter loop tool surface | 22,470 chars | E |
| hunter request tool descriptions | 22,219 chars, same text as the loop | E |
| hunter loop duplicate share of first call | 21.3% of 104,119 chars | E |
| hunter loop uncached tokens | 5,361 of 8,712, or 61.5% | E |
| hunter system tool summary | 1,028 chars; 7 names vs 12 actual; 5 missing | P |
| hunter spec body | 2,004 chars; 1 spec field and 4 provenance fields missing | P |
| hunter passes | 8,084 chars; tree 1,001; step protocol 951 | S |
| hunter examples | 9,263 chars | S |
| hunter and modeller 5xx rule | 715 exact chars | E |
| pod runner and triager shared blocks | 369, 232, and 191 chars | E |
| pod runner `# Tools` | 7 names vs 8 actual; `auth_store` missing | P |
| pod triager `# Tools` | 4 names vs 7 request entries; `graph_view`, `auth_store`, `TriagerDecision` missing | P |
| assigner role versus prompt | 1,660 vs 9,105 chars; overlapping ownership rules | S |
| assigner examples versus `_FEW_SHOTS` | four exact blocks of 93 to 134 chars | N |
| typist reflection versus prompt | three exact blocks of 89 to 107 chars | N |
| typist role header versus system | same role and goal in one turn | N |
| modeller `hunts_store` schema | 14,903 chars | P |
| modeller prompt | 21,702 chars | S |
| shared tool text across first calls | 147,095 chars, 73.0% of tool text, 32.4% of all first-call chars | E/P |
| shared `load_skill` | 18,405 chars over 9 roles | E |
| shared `record_skill_lesson` | 18,936 chars over 9 roles | E |
| shared `auth_store` | 51,320 chars over 9 roles; full and read-only variants | E/P |
| shared `graph_view` | 13,302 chars over 5 roles; hunting and analysis variants | E/P |
| shared HTTP pair | 30,380 chars over 5 roles | E |
| shared `exec` | 4,946 chars over 4 roles; three contracts | P |
| shared `query_lightrag` | 5,896 chars over 2 roles | E |
| shared `write_skill` | 3,910 chars over 2 roles | E |
| cortex | 1,486 chars in 6 agents | E |
| application overview | 1,761 chars in 4 agents | E |
| conciseness | 328 chars in 3 prompts and tool descriptions | E |
| skill catalogue contract | 1,905 chars; says it mirrors `skills/README.md` | P |
| write-skill contract | 1,187 chars; says it mirrors `skills/README.md` | P |
| spec status | 3 values | P |
| pass sequence | 8 values | P |
| variant bases | 10 values | P |
| threat-model gates | 5 states; 6 sections | P |
| observation anchors | 5 values | P |
| terminal reasons | 5 values | P |

## Appendix B. Source index

- `src/polymerhus/attack/hunting/prompts/hunting-agent.md`
- `src/polymerhus/attack/hunting/prompts/examples.md`
- `src/polymerhus/attack/hunting/prompts/COGNITIVE_ARCHITECTURE_MAP.md`
- `src/polymerhus/attack/hunting/prompts/threat-modeller.md`
- `src/polymerhus/attack/hunting/prompts/pod-runner.md`
- `src/polymerhus/attack/hunting/prompts/pod-triager.md`
- `src/polymerhus/attack/hunting/hunting_agent.py`
- `src/polymerhus/attack/hunting/cortex.py`
- `src/polymerhus/attack/hunting/conciseness.py`
- `src/polymerhus/attack/hunting/hunter_tools.py`
- `src/polymerhus/attack/hunting/threat_modeller_tools.py`
- `src/polymerhus/attack/hunting/threat_model.py`
- `src/polymerhus/attack/hunting/threat_model_store.py`
- `src/polymerhus/attack/hunting/spec_contract.py`
- `src/polymerhus/attack/hunting/hunter_state.py`
- `src/polymerhus/attack/hunting/pod/prompts.py`
- `src/polymerhus/attack/hunting/pod/agents.py`
- `src/polymerhus/attack/hunting/pod/context.py`
- `src/polymerhus/attack/hunting/pod/tools.py`
- `src/polymerhus/attack/hunting/pod/note_tool.py`
- `src/polymerhus/attack/hunting/pod/types.py`
- `src/polymerhus/attack/hunting/pod/variant_basis.py`
- `src/polymerhus/attack/hunting/pod/verification.py`
- `src/polymerhus/analysis/prompts/assigner.md`
- `src/polymerhus/analysis/prompts/technical-system.md`
- `src/polymerhus/analysis/prompts/bootstrapper.md`
- `src/polymerhus/analysis/prompts/curation.md`
- `src/polymerhus/analysis/assigner.py`
- `src/polymerhus/analysis/mechanism_typist.py`
- `src/polymerhus/analysis/proposer_reasoning.py`
- `src/polymerhus/analysis/proposer_turn.py`
- `src/polymerhus/analysis/bootstrap.py`
- `src/polymerhus/analysis/curation.py`
- `src/polymerhus/analysis/analyser_types.py`
- `src/polymerhus/analysis/messages.py`
- `src/polymerhus/analysis/overview.py`
- `src/polymerhus/analysis/l1_inventory.py`
- `src/polymerhus/app/llm/prompts/skill_evolver.md`
- `src/polymerhus/app/llm/evolver.py`
- `src/polymerhus/app/llm/skills.py`
- `src/polymerhus/app/auth/tool.py`
- `src/polymerhus/app/auth/seams.py`
- `src/polymerhus/app/llm/providers.py`
- `src/polymerhus/recon/control/prompts/auth-gateway.md`
- `src/polymerhus/recon/control/orchestrator_agent.py`
- `src/polymerhus/recon/domain/prompts/writing-observations.md`
- `src/polymerhus/recon/domain/curator.py`
- `docs/experiments/unit-threat-model-eval-2026-10-20/audit_context_duplication.py`
- `docs/experiments/unit-threat-model-eval-2026-10-20/audit_context_occupancy.py`
- `docs/experiments/unit-threat-model-eval-2026-10-20/CONTEXT-LIFECYCLE-AUDIT-WHITE-JOTTER.md`

## Appendix C. Reproduction

The source extractor is:

```
python3 audit_context_duplication.py \
  --source-root <path-to-utm-context-auth-followup> \
  --occupancy <path-to-audit_context_occupancy.json> \
  --out <output.json>
```

The occupancy file is produced by `audit_context_occupancy.py` against the trial window.
The source extractor reports the prompt sizes, exact matching blocks, tool-name coverage, spec-field coverage, status inventories, shared-tool totals, and first-call totals.
The report's semantic labels remain a human review; the script only supplies the lexical and schema evidence.
