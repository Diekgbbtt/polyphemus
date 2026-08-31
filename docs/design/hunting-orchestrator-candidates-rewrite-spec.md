# Hunting spec: the candidate-creation → projection → gate → mint rewrite

Part of the [`#82`](https://github.com/Diekgbbtt/polyphemus/issues/82) hunt-orchestrator lineage, continuing
[`#110`](https://github.com/Diekgbbtt/polyphemus/issues/110) (the stateful per-fault-unit orchestration + graph engine),
and realising the candidate-creation / projection scope opened by
[`#63`](https://github.com/Diekgbbtt/polyphemus/issues/63) (the typed applies-if predicate + sound unit-projection).
The current integrated ancestors are `docs/design/hunting-orchestrator-llm-artifacts-spec.md` (#135, the gate turn's
LLM-local artifacts) and the #67 orchestrator + hunting-agent contracts
(`docs/design/hunting-67-orchestrator-spec.md`, `docs/design/hunting-67-p-hunting-agent-spec.md`).

*Status: spec (contract), NOT implementation.* This document is the operator-locked design for a near from-scratch
rewrite of the system that turns the `FaultSource` candidate set into dispatched `HuntConfig`s, driven by the five-stage
pipeline (`grill-me -> to-spec -> to-tickets -> to-assertions -> implement -> code-review`). The grilling is complete;
all sixteen decisions (Q1-Q16) plus the two operator corrections (the LLM-only Q16 gate and the tool split of
`store_reads`) are locked below with their rationale.

**Amended 2026-08-23 by the memory + workflow-graph rework** (ADR
`docs/design/hunting-orchestrator-memory-workflow-adr.md`, grill dispositions G1-G14 + two operator corrections): the
REASON body becomes a **node-per-phase workflow graph** (`hypothesise -> ratify -> note`) with graph-embedded
transition logic and **phase-transition verbatims injected on-the-fly in tool-call responses** (constants, never the
system prompt); the tool surface becomes `hunts_store` / `notes` (read/write cmds) + `graph_view`; the mint is
anticipated to the hypothesis-elicitation phase with a `status` attribute (`hypothesised -> ratified | dropped`);
`HuntConfig` gains `status`, `vulnerability-class` identity, `adversarial_capabilities` raised one level, and
`technique_primitives`; `concrete_fault_candidates` / `fault_hypothesis` / `extension_points` /
`supposed_payload_vectors` are removed; the gate input gains an **L1 ontology primer constant**; and the memory
topology is the per-project produced/consumed config store + `memory.yaml` notes file (spec'd separately in
`docs/design/hunting-memory-system-spec.md`). Where this spec and the memory-system spec overlap, the memory spec is
the authority on topology and the ADR is the authority on the dispositions.

## 1. The problem, stated from the harness

The current system (the `_reason_node` internal stretch of `arun_orchestration`, the `unit_projection` reader, the
`_compose_gate_prompt` composition, the `mint_hunt_config` deterministic stage) is the #135 state: a **per-pair
embedded gate turn** over a **thin typed projection**, minting **one `HuntConfig` per carried direction** through a
deterministic fan-out. Running it against a realistic L1 ground-truth and a full fault-KB exposes five defects, all
verified real by the impact-map analysis that preceded this spec:

- **Defect 1 - one config per candidate.** `EnvisionedDirection` is emitted once per candidate pair and minted into a
  single `HuntConfig` (`hunt_orchestrator.py:315` `mint_hunt_config`). For a unit where the same fault legitimately
  splits along distinct web-vulnerability classes (e.g. CSRF and IDOR both plausible at one locus), the gate cannot
  fan out the N `HuntConfig`s the hunt warrants.
- **Defect 2 - the gate prompt does not separate Services from Systems.** A Service's surface hides its edged
  DataItems + Systems; a System is not outlined distinctly even when the fault targets `Both`. The #69 implicit-coverage
  rule makes System-anchored candidates exist only for System-strict faults, but the prompt does not surface the
  distinction it needs.
- **Defect 3 - the projection is a thin count surface.** `PRODUCES`/`CONSUMES` are counts only
  (`unit_projection.py:148-150`); edged Systems collapse to `(family, target_kind, role)` (`:151-156`); DataRelationship
  kinds are a frozenset of labels (`:158-170`). The L1 schema fully supports the rich projection (no schema blocker);
  the read gap is the System-to-System adjacency (D3, unlanded).
- **Defect 4 - one LLM turn per candidate pair.** The #110 schedule unit is a REASON node per pair, i.e. `U*F` turns
  in the worst case (tens of units x a hundred-plus fault entries -> 10^3-10^4 turns). The #135 artifacts spec pinned
  per-pair rendering; the #67 orchestrator contract pins per fault-class reasoning. This is a spec-vs-spec
  re-decision, resolved in Q1/Q13 below.
- **Defect 5 - cooperating systems are not considered.** A System-targeting hunt (System-strict fault) is blind to
  the System's cooperating systems; the skill only lists first-hop services.

## 2. Solution

Rebuild the four-stage chain - **candidate intake -> per-fault REASON pass (a tool-augmented ReAct decision-tree) ->
deterministic mint -> dispatch** - under a single locked architecture: a **thin mechanical graph envelope** (the #110
supervisor `StateGraph`, unchanged topology) around a **prompt-ReAct REASON body**. The REASON body reasons **per
fault over all its matched units** (one LLM pass, not one per unit), interposing note-taking and `HuntConfig` minting
**at the unit boundary** through two deterministic tool calls (`mint_hunt_config` then `record_note`), with the
committed-state ledger re-injected into the prompt **only at that boundary** - never after intra-unit tool calls.

## 3. The locked architecture (every decision, with rationale)

### 3.1 Gate granularity - one REASON pass per fault over all its matching units (Q1/Q13)

The **schedule unit is a fault**; one REASON node covers that fault and **every L1 unit it matched**, materialised in the
single prompt. Rationale: every LLM pass pays a fixed overhead (system prompt, tool schemas, fault-KB grounding) that
does not scale with unit count; N passes for N units pay it N times, for a structural `Nx` token and round-trip cost,
while the fault-level reasoning (hypothesis space, adversarial capabilities, test primitives, blockers, assumptions)
is computed once and reused across the units sharing the fault. The per-unit inner StateGraph loop alternative (one
fault-unit per pair) is rejected: it multiplies exactly the fixed cost and buys no quality if gates are tool-body
enforced.

Quality is **not** carried by higher reasoning effort; it is carried by three structural guarantees:

1. **Single-fault bounding** - one fault per pass caps the drift horizon.
2. **Explicit per-unit work-items with a done-when** - each matched unit is a named work-item, so a subtle unit is not
   skimmed inside a long free-form pass.
3. **Tool-body-enforced gates** - `mint_hunt_config` and `record_note` are deterministic seams the model must call per
   unit; the gates live inside the pass as tools, not between passes as untracked prompt discipline.

### 3.2 The REASON body - a node-per-phase workflow graph (amended 2026-08-23)

The REASON body is a **node-per-phase workflow graph** (G2: the transition logic is embedded in the graph itself),
not an embedded turn and not a prompt-narrated tree. Each (unit, fault) pair runs three phases as graph nodes -
`hypothesise -> ratify -> note` - and the phase-transition verbatims are injected **on-the-fly in the specific
tool-call responses**, sourced from constants, never from the system prompt (defect 3; G1/G8). The per-phase
reasoning, in order:

1. **Prior-hunt reflection (Q11).** The prompt lists the prior minted-config keys (revival keys) already carried on
   the run's orchestration thread. The model reflects on likely overlap; it **may** call `hunts_store(read)` for
   closer inspection. This is the **novelty gate**: the model asserts whether any of its elicited configs duplicate a
   prior one, right **before** the hypothesise write. Pure LLM reflection, prompt-specified - no module-side parsing
   of the candidate text (Q16 correction). A duplicate write FAILS (no file with the same name can be created; G4)
   and the error is a deduplication signal the model interprets, not a harness prune.
2. **Knowledge-sufficiency decision point (Q9).** "Given this fault class and unit type, do I have sufficient
   knowledge of the previous dispatched hunts and all potentially useful insights collected?" - if not, the model
   loops the memory reads.
3. **Target-knowledge loop.** Against the materialised unit (projection + surface), the model asks "do I have enough
   technical knowledge of this unit to concretise the abstract fault at this locus?" If not, it queries the
   attack-surface / L1 graph via `graph_view`, **iterating until sufficient** (multiple queries allowed).
4. **Hypothesis elicitation (Q8) - the hypothesise phase.** For each unit, the model elicits one or more
   **vulnerability classes** that could characterise the application at this locus - the higher stretch that
   sub-classes the fault (the concrete-fault stretch is the #164 hunter's DECOMPOSE/GENERATE ownership, never the
   orchestrator's). At this phase the model calls `hunts_store(write, config, status="hypothesised")` - the mint is
   **anticipated here** (Q14/Q15 correction): the config is a draft with only `rationale` and `research_direction`
   filled; the fields owned by the ratification phase are empty. The harness records the write, sets the loop state
   to HYPOTHESISED, and the tool-call response carries the constant hint: reason on proximity and too-near
   same-class merging, then the capabilities / assumptions / technique-primitives analysis.
5. **Ratification phase.** The model reasons on the mentioned properties (proximity merge, capabilities, assumptions,
   technique primitives) and **may do multiple tool calls to update/delete/create configs**, which must always be
   **ended by a tool call carrying `status="ratified"`** and, very likely, the filled
   `adversarial_capabilities` / `assumptions` / `technique_primitives`. The harness sets the loop state to RATIFIED,
   and the tool-call response carries the constant verbatim that **strongly instructs note-taking** (G1: nothing
   else; the next pair is NOT fed here).
6. **Note phase.** The model reasons on the rationale of the decision taken and calls `notes(write)` - potentially
   multiple times, for different decisions. One note per config covering ALL decisions that concern that config
   (G8): mostly the observations drawn from tool calls (graph_view or memory reads) that drove the rationale, plus
   anything potentially insightful moving forward; it must be MORE detailed than the config's `rationale` and walk
   through the reasoning that yielded it. The harness sets the loop state to NOTED at this call - the pair's loop
   ends, and **the note tool's response carries the next pair's data plus the "start the next iteration" verbatim**
   (G1 correction). The iteration restarts at the next pair.

All tool calls are optional (Q9): a prior-hunt lookup may be skipped when the previous unit already yielded it in the
same context; the sufficiency decision points gate the loops. The model owns every call; the harness owns the state
machine and the phase verbatims.

### 3.3 Loop-state tracking - a status lifecycle, collocated with the tool-call responses (amended 2026-08-23)

The harness tracks the pair's loop state as a **status lifecycle over the configs**, carried on the graph state and
embedded in the graph's transition logic (G2). The config lifecycle is `hypothesised -> ratified | dropped` (G5/G6);
`noted` is a LOOP state (the pair's note phase done), never a config status; `consumed` is tautological in the memory
topology (the produced/consumed directories express it), never a status enum member. `dropped` is the orphaned
status (a config deleted during ratification, G6). The "pair interrupted between hypothesised and ratified" scenario
is NOT a risk to account for (G6, operator).

The collocation is the operator-locked cadence (G1 correction - the pair end is the note response, never the
ratification response):

```
pair N (unit, fault) frame                          [user prompt / note response of pair N-1]
  -> hypothesise (Q8 elicitation): hunts_store(write, config, status="hypothesised")
     [harness: loop state -> HYPOTHESISED; response carries the constant hint:
      reason on proximity / too-near same-class merging, then capabilities /
      assumptions / technique-primitives analysis]
  -> ratify: hunts_store update/delete/create ... END with status="ratified"
     [harness: loop state -> RATIFIED; response carries ONLY the constant verbatim
      that strongly instructs note-taking]
  -> note: notes(write) - one or more calls, one note per config
     [harness: loop state -> NOTED; the note response carries the NEXT pair's data
      plus the "start the next iteration" verbatim; iteration restarts]
pair N+1 ...
```

Rationale: the phase-transition verbatims live in **proper constants injected on-the-fly in the specific tool-call
responses** - never in the agent system prompt (defect 3, operator). The state machine is the reliable cadence that
keeps the model faithful for the next phase while turning the hypothesise / ratify / note gates into reliably
interposed seams.

**Verbatim constant instrumentation (Q16/Q11 requirement, amended).** The `hunt-orchestrator` skill
(`skills/hunting/hunt-orchestrator/SKILL.md`) gains the verbatim "Loop protocol" section carrying: the per-unit
work-item structure, the knowledge-sufficiency decision point, the target-knowledge loop, the same-class merge
instruction, the prior-hunt reflection with the keys listed, and the hypothesise -> ratify -> note boundary. The
**phase-transition verbatims** (the "move to ratification" hint after hypothesise, the "strongly take notes" hint
after ratify, the "next pair + restart" hint after note) are **constants injected in the tool-call responses**, not
part of the skill.

### 3.4 The tool surface (amended 2026-08-23, G3)

The memory-read/write surface is **two store tools plus `graph_view`**; the earlier split surface
(`read_memory_hunts` / `read_memory_notes` / `mint_hunt_config` / `record_note`) is replaced:

1. **`hunts_store`** - contract: `read` / `write` cmds. `read` needs the config identifier and accepts optionally
   specific attributes; the WHOLE surface context of a projected unit may NEVER be read through it - only the
   service keys, which may later be inspected with `graph_view`. `write` takes the hunt config object; any attribute
   specification is optional and internal schema validation never rejects on missing attributes. The `status`
   attribute (`hypothesised | ratified | dropped`) is carried by the config object itself (operator correction - it
   must be explicit on the config).
2. **`notes`** - contract: `read` / `write` cmds, same data contract as `hunts_store`; write options are `append`,
   `update`, `delete` (G3).
3. **`graph_view`** - unchanged (read-only L0/L1 view, write-shaped calls rejected). **As of #197**: rides the ONE shared tool `graph_view_tool.py::build_graph_view_tool` with the single-source usage contract (schema, query-language primitives, read-only guard, `{"rows":[...]}` shape, worked example) - the SAME tool bound at the orchestrator, hunter, and pod runner + triager.

There is no back-edge-to-recon tool (standing operator ruling 2026-08-22); the target-knowledge loop rides
`graph_view`. There is no budget tool (below).

**No `budget_consume` tool** (Q7 correction). Token/budget accounting is a global harness concern, not a hunting-local
check; there is no budget logic in the gate loop. **The pre-existing O9 envelope BUDGET stage is REMOVED (G7,
amended 2026-08-23)**: budget tracking and the hard-stop mechanism are the runtime plane's and the pod's ownership
(the pod keeps internal fixed caps per D67-09; #164 keeps pod-level caps) - the orchestrator does not cut its own
accumulated set.

### 3.5 The mint (Q2/Q8/Q12, amended 2026-08-23)

The mint is **anticipated to the hypothesis-elicitation phase** (G-operator): the model calls `hunts_store(write,
config, status="hypothesised")` at elicitation, producing a **draft config** with only `rationale` and
`research_direction` filled; the ratification-phase fields are empty. The draft is then edited through further
`hunts_store` writes during ratification, ending with a `status="ratified"` call.

- **N configs per pass** (Q2/Q12): one `HuntConfig` per distinct **vulnerability class** the model elicited for that
  unit-fault locus, after the (LLM-owned) same-class merge. The vulnerability class is the config's identity axis -
  the fault is sub-classed into the vulnerability classes that could characterise the application itself; the
  concrete-fault stretch (DECOMPOSE/GENERATE) is the #164 hunter's, never the orchestrator's.
- **No mint disambiguator** (Q12 correction): the earlier "mint disambiguator" concept is removed as ambiguous and
  overlapping with the same-class merge; per-class distinctness is the fan-out criterion.
- **HuntConfig type rework (operator-confirmed, amended 2026-08-29 by #202):** the concretisation slots are
  **removed** - `concrete_fault_candidates[]`, `fault_hypothesis` (redundant: one config per class),
  `extension_points` (redundant with `research_direction`), and `supposed_payload_vectors` (moves into the hunter's
  GENERATE stretch) all leave the type. `HuntConfig` gains:

  - `status` - `hypothesised | ratified | dropped` (explicit on the config; operator correction). `noted` is a loop
    state, never a config status; `consumed` is expressed by the produced/consumed topology, not a status member.
  - `vulnerability_class` - the config's identity axis (the elicited class). **The naming of the class IS the
    initial concretisation** (G2), so no separate concretisation slot exists.
  - `preconditions[]` - the merged G1 preconditions-of-the-test list (the old `adversarial_capabilities[]` +
    `assumptions[]` unified): attacker-side AND environment-side conditions that must hold for the fault's symptoms
    to be reachable when the test runs. Filled ONCE by the ratification phase; never post-exploitation capabilities.
  - `observed_defences[]` - the renamed and re-oriented `target_caveats`: **observed** characteristics of the
    target that hinder the tests and consequently support a falsification of the hypothesised fault (e.g. a WAF for
    XSS payloads, an anti-bot gate for request-based hunting, an assertion of a hardened OAuth2 authentication
    mechanism for JWT-token forging). May be left empty when the target shows no such characteristics. Filled by
    the ratification phase.
  - **`edge_degree` transformed to the connected DataItems** (operator correction): in the config's `surface_context`,
    a Service's `edge_degree` counts are replaced by the detailed specification of the DataItems it is connected to
    (name, type, sensitivity, fields, notes) - mirroring the rich projection.

  **#202 removals and re-sourcings.** `technique_primitives[]` is **removed**: the vulnerability-class naming
  already IS the initial concretisation, the field was redundant with a class-level `research_direction` that
  pre-specified the technique, and the concrete probing techniques belong to the hunter's spec-writing stretch.
  `tool_registry` is **retired**: its KB source (`_registry_from_kb`) is dead (the KB retriever is retired and
  `kb_evidences` is empty), and the ratification model authored a generic agent-tool list with no fault-targeting
  discrimination - the hunter owns its tool surface and `kb_query`. `prior_hunt_insights` is **re-sourced
  downstream**: it reads the hunter memory's TestImplementationSpecs + the Q16 durable PodExport insights
  (`test-specs/<config_key>/` + the verdict-stub notes, joined by the `::` `config_key`), shallow-projected (I3:
  never a full config/spec embedded), instead of the orchestrator's own prior configs+notes by revival key.
  `research_direction` is **tightened to G1 feasibility prose**: verbatim reasoning WHY the fault is feasible at
  this locus (surface, preconditions), never technique words ("probe X with Y"). The remaining parameter-set slots
  (`surface_context`, `sub_fault_ids`) are unchanged (`sub_fault_ids` keeps feeding each class-config, #66
  non-conflation, G14).

  **The three-goal orientation (#202).** The config carries the orchestrator's stretch only, mapped to the three
  goals: (G1) the technical feasibility of that fault at that specific unit - `rationale`, `research_direction`,
  `vulnerability_class`, `surface_context`, `l0_evidence`, `preconditions`, `observed_defences`; (G2) the initial
  concretisation - the `vulnerability_class` naming itself; (G3) synergistic further-concretisation material -
  `sub_fault_ids` and `prior_hunt_insights`. Every attribute serves one of the three goals; nothing more.
- **Novelty (Q11)** is enforced by the LLM reflection directly before the hypothesise write; a config the model
  asserts duplicate is **never written** (prune-side only). A duplicate write attempt FAILS (no file with the same
  name can be created, G4) and the error is the deduplication signal the model interprets - the module does not
  re-check novelty on parsed text.

### 3.6 The projection reader (Q3)

`unit_projection.py::build_projection` is rebuilt from the thin facet surface to the **rich typed projection** the L1
schema already supports:

- **DataItems explode**: `PRODUCES`/`CONSUMES` edges resolve to the full DataItem node list, every property carried
  (name, type, sensitivity), not counts.
- **Edged Systems unpack**: each outgoing Service->System edge resolves to the target System fully unpacked - its
  typed attributes (kind, discriminator, exposure, trust-boundary facet), not the collapsed `(family, target_kind,
  role)` triple.
- **DataRelationship kinds chain**: connected DataItems resolve the relationship edges verbatim (kind chains), not a
  frozenset of labels.
- **System-to-System adjacency (D3) read added (Q5)**: the System-adjacency read lands (currently the inverse hop),
  so System-targeting hunts can see cooperating systems. This is the one L1-read gap; everything else the projection
  needs is already present (verified in the impact map - no schema blocker).

Each slot degrades independently to UNKNOWN (never FALSE, never a prune signal) - the #63/135 fail-open discipline
unchanged.

### 3.7 The prompt (Q4/Q5)

- **Services and Systems render in separate prompt sections** with distinct adversarial-reasoning intros (Q4): a
  Service's section spells its surface - its edged DataItems and Systems; a System's section outlines the System
  distinctly even for `Both` faults. The #69 implicit-coverage **minting** carve-out stays parked (prompt-split only in
  this change-set; target typing stays heuristic for minting).
- **Cooperating-systems instruction (Q5):** the skill/fallback gains the operator's verbatim prose: "consider
  cooperating systems when creating a HuntConfig targeting a system" - plus the new System-adjacency projection read.
  No structured `cooperating_systems` field yet.
- **L1 ontology primer (G9, amended 2026-08-23):** the gate input's user prompt carries a **fixed ontology-primer
  constant** - deliberately NOT an over-specified glossary of kinds and edge types (those are self-explanatory), but
  the fundamental knowledge that makes every other part of the graph readable: what a **System**, a **Service**, and
  a **DataItem** are conceived for, and the philosophy of the domain model. The primer is a constant rendered at the
  top of the pair's frame (never the system prompt - the phase-hint defect applies to phase hints, not stable
  knowledge, but the primer rides the per-pair frame so it versions with the render).

### 3.8 Rewrite / reuse boundary (Q6)

Reuse (maximal, unchanged internals): the #110 supervisor `StateGraph` envelope (loop -> reason -> END; **the
dispatch node is removed - there is no dispatch node anymore, the runtime plane owns dispatch state, G12 amended
2026-08-23**), the `HuntOrchestratorActor` thread + `HuntingActorRegistry`, the `FaultSource` deterministic matching
(typed applies-if predicate + LLM match), and the `skills/hunting/*` mounts.

Rebuild (the defects force these): the **schedule unit** (pair -> fault), the **REASON body** (embedded turn ->
node-per-phase workflow graph), the **projection reader** (thin -> rich), the **gate prompt** (Services/Systems split
+ Loop protocol + ontology primer + vulnerability-class elicitation), the **mint** (anticipated to elicitation with a
status lifecycle + reworked `HuntConfig`), and the **memory topology** (per-project produced/consumed + notes -
spec'd in `docs/design/hunting-memory-system-spec.md`).

## 4. Domain-ontology mapping (provisional terms, ratified where noted)

- **testable unit** - the L1 `Service` or `System` a hunt anchors on, kind-qualified identity `<kind>:<key>`. The
  REASON body iterates units **within** one per-fault pass (rich projection, Q3).
- **HuntCandidate** - the `(testable-unit, fault-class)` pair; **no longer the schedule unit**. The schedule unit is
  the **fault**; the candidate is the unit-level atom the pass reasons over internally.
- **revival key** - `<unit_id>::<fault_class>`; keys the config identity and the notes (the shared key survives the
  Q14 split, amended: the config file id is `<unit_id>_<CWE_ID>_<vulnerability_class>`, G4).
- **HuntConfig** - reworked (2026-08-23, #202): `status` (`hypothesised | ratified | dropped`),
  `vulnerability_class` identity axis, `research_direction` (tightened to G1 feasibility prose, no technique
  words), `preconditions` (the merged G1 preconditions list, ratification-filled), `observed_defences` (the
  renamed, re-oriented `target_caveats`, ratification-filled); `technique_primitives` /
  `adversarial_capabilities` / `assumptions` / `tool_registry` removed; `prior_hunt_insights` re-sourced
  downstream (hunter TestImplementationSpecs + Q16 pod exports by `config_key`, shallow-projected I3);
  `concrete_fault_candidates` / `fault_hypothesis` / `extension_points` / `supposed_payload_vectors` removed;
  `edge_degree` in the surface context transformed to the connected DataItems. The config's role is oriented by
  the three goals: G1 feasibility / G2 the vulnerability-class naming (the initial concretisation) / G3
  further-concretisation material (`sub_fault_ids`, `prior_hunt_insights`).
- **match verdict** - unchanged three-valued prune signal (level 1); the gate no longer **is** the verdict - it is the
  per-fault vulnerability-class elicitation + ratification.
- **implicit-coverage rule** - the minting carve-out stays parked (Q4); prompt-split only.

## 5. Delivery semantics and degradation (amended 2026-08-23)

The O1-O10 canon, fail-open/honour clauses, and report shape are unchanged. Every per-slot degrade of the rich
projection stays silent-and-counted; every tool seam degrades fail-open. The mint is no longer a deterministic
fan-out - it is the model-driven hypothesise/ratify writes under harness state tracking, and the O9 envelope BUDGET
stage is REMOVED (G7): budget and the hard stop are the runtime plane's and the pod's (D67-09).

**Anti-fabrication (amended by #186, 2026-08-25).** A raising/empty hypothesise decision NEVER fabricates a
fully-empty draft: the pair is SKIPPED and counted on the ledger (`units_skipped`), so an actor-runtime turn
failure degrades to a skipped pair, never to a dead-weight draft in `produced/`. The genuine carried-bare (a
direction the model emitted with a rationale but no elicited vulnerability class) is PRESERVED - it still fans out
to the single carried-bare hypothesised draft (section 3.5). The underlying turn degradation is per-turn on the
shared actor runtime: the retryable class (transport/timeout/5xx/429) is retried under a bounded escalating
per-attempt budget, then the turn degrades to a no-decision reply and the actor survives for the next pair/pass.

## 6. User stories (amended)

1. As a FaultSource consumer, I want the orchestrator to reason **once per fault over all its matched units**, so that
   token/time cost does not multiply with the unit count.
2. As the hunt-orchestrator, I want a single REASON pass to elicit one or more **vulnerability classes** per unit
   with a research-direction rationale, so that the same fault can fan out into several discriminable configs.
3. As the hunt-orchestrator, I want the elicited classes to be **application-characterising vulnerability classes**
   with envisioned research directions, so that the concrete-fault narrowing stays with the hunting agent at
   spec-writing (DECOMPOSE/GENERATE, #164).
4. As the hunt-orchestrator, I want a **node-per-phase workflow** (hypothesise -> ratify -> note) whose transitions
   are embedded in the graph and whose phase verbatims ride the tool-call responses, so that the intent is preserved
   across the pass and the phases are reliably interposed.
5. As the harness, I want the **pair loop to end at the note tool's response**, which carries the next pair's frame
   plus the restart verbatim, so that the state/context update is collocated with the durable side effects.
6. As the harness, I want `hunts_store` and `notes` as the **status-bearing write seams** (hypothesise -> ratify ->
   note), so that config and note persistence interpose reliably at each phase.
7. As the operator, I want the **same-class merge (Q16) and novelty (Q11) to be pure LLM reflection steps**
   (verbatim prompt + the duplicate-write failure signal, G4), so that there is no module-side heuristic parsing of
   emitted candidate text.
8. As the operator, I want the store tools to be **`hunts_store` and `notes` with read/write cmds**, so that prior
   configs and notes are read and written through one consistent data contract (G3).
9. As the operator, I want the **Services/Systems split prompt + cooperating-systems instruction + L1 ontology
   primer**, so that a Service's DataItems/Systems and a System's cooperating systems are read with the correct
   ontological grounding (G9).
10. As the operator, I want the **rich projection** (DataItem lists, full System unpack, DataRelationship chaining,
    D3 System adjacency), so that the gate reasons over the live L1 rather than counts and collapsed triples.
11. As the operator, I want the **HuntConfig type reworked** (`status`, `vulnerability_class`,
    `preconditions` + `observed_defences` ratification-filled, `prior_hunt_insights` re-sourced downstream;
    `technique_primitives` / `adversarial_capabilities` / `assumptions` / `tool_registry` removed;
    `concrete_fault_candidates` / `fault_hypothesis` / `extension_points` / `supposed_payload_vectors` removed;
    `edge_degree` -> connected DataItems), so that the config carries the orchestrator's stretch only, oriented by
    the three goals (G1 feasibility / G2 the vulnerability-class naming / G3 further-concretisation material),
    and the hunter owns the rest.
12. As the operator, I want the graph envelope to **end at the REASON stretch** (no dispatch node), so that dispatch
    state belongs to the runtime plane (G12).

## 7. Out of scope

- The hunting agent's prompt / decision tree (its DECOMPOSE/GENERATE narrowing is the deliberate owner of the
  concrete-fault stretch, #164; not rebuilt here).
- The inbox surfer and produced->consumed delivery mechanics - implemented in another workstream (G13).
- The ranker body (#71), `FaultSource` content, the back-edge trigger wiring (#64).
- The long-horizon harness execution-state tracking - opened separately as
  [#136](https://github.com/Diekgbbtt/polyphemus/issues/136) (TO-DO plan based, DAG workflow control plane).
- Graph topology changes beyond the REASON-body rebuild: the dispatch node is removed, the budget stage is removed;
  NO new routing nodes beyond the hypothesise/ratify/note phase nodes.

## 8. Testing decisions (amended)

- **Trace-first behavioural seam**: the per-fault REASON body is exercised through the existing
  `test_orchestrator_llm_artifacts.py` style - injected `reason_fn`, asserted: the hypothesise write lands with
  `status="hypothesised"`, the ratify write ends with `status="ratified"` and the filled
  capabilities/assumptions/technique-primitives, the note write follows at the pair end, the phase verbatims ride
  the tool-call responses (never the system prompt), knowledge-sufficiency/target-knowledge loops degrade fail-open.
- **Status-lifecycle seam**: the hypothesise -> ratify -> note state machine tested as a pure harness function
  (graph-embedded transitions, G2) - asserts the config lifecycle `hypothesised -> ratified | dropped`, the
  loop-state `NOTED` at the note call, and the duplicate-write failure signal (G4).
- **Projection seam**: `build_projection` tested directly over synthetic L1 fixtures (DataItem lists, full System
  unpack, DataRelationship chaining, D3 adjacency) mirroring `test_unit_projection.py`; per-slot degrade asserted
  fail-open.
- **Tool seams**: `hunts_store` (read/write, surface-context-read guard, optional attributes) and `notes`
  (read/write, append/update/delete) tested at the tool-surface integration tier with injected store / notes seams
  (fail-open when the seam is absent).
- **Graph envelope**: `test_orchestrator_graph.py` asserts the REASON stretch runs the three phase nodes and ENDS
  without a dispatch node or budget stage.
- **E2E**: `test_hunt_orchestrator_walkthrough.py` / `test_hunt_orchestrator_isolated_e2e.py` on the
  `hunting_orchestrator` role - the full pass writes produced/consumed configs + `memory.yaml` notes, and the rich
  projection renders.

Prior art: `tests/attack/test_unit_projection.py`, `tests/integration/test_orchestrator_llm_artifacts.py`,
`tests/attack/test_orchestrator_graph.py`, `tests/e2e/test_hunt_orchestrator_walkthrough.py`.

## 9. Further notes

- The current `skills/hunting/hunt-orchestrator/SKILL.md` (the #135 trace) is rewritten as part of this work: the
  cognitive-architecture passages survive, the "one direction per candidate" emit contract is replaced by the
  per-fault multi-unit Loop protocol, the verbatim Q16/Q11/Q9 passages land verbatim, and the phase-transition
  verbatims (hypothesise -> ratify -> note, the next-pair restart) are CONSTANTS injected in the tool-call
  responses - never part of the skill (defect 3).
- The `CONTEXT.md` hunting glossary updates: "HuntCandidate" (no longer the schedule unit), "schedule unit / REASON
  pass" (fault-level), "config status lifecycle" (`hypothesised -> ratified | dropped`), "vulnerability class",
  "hunts_store", "notes", the tool surface entry, and the produced/consumed memory topology - all land with this
  change (per the repo's living-document rule).
- The memory topology itself (produced/consumed configs + `memory.yaml`, `_seq`/`_ref` removal, run/hunt/dispatch
  file removal, file-naming convention) is specified in `docs/design/hunting-memory-system-spec.md`; the ADR
  `docs/design/hunting-orchestrator-memory-workflow-adr.md` is the authority on the 2026-08-23 dispositions.