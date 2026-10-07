# Hunting memory-system spec (per-project hunt-config + notes store)

*Status: spec (contract), NOT implementation.* The 2026-08-23 operator-locked design for the hunt-orchestrator's
memory system, resolved by the grilling round recorded in
`docs/design/hunting-orchestrator-memory-workflow-adr.md` (dispositions G1-G14 + two operator corrections). This
document is the **pattern document**: the topology, naming, lifecycle, and tool contracts here are the template
other memory systems replicate (operator statement: "its pattern will be replicated across other memory systems").
It supersedes the append-only-repo-global-memory of #68 and concretises #70 / #137.

## 1. The problem, stated from the harness

The hunting memory today is an append-only markdown stub: the `memory` record kind is the one cross-run kind, but it
lives at a **repo-global** `<root>/memory.md`, carries no `project_id`, no timestamp, no evidence/correlation linkage,
and no idempotency (every completed hunt appends a fresh `{revival_key, hunt_id, insight}` block). Reading is a
full-file scan equality-filtered on `revival_key`. The per-run kind files (`run` / `config` / `hunt` / `dispatch` /
`notes`) add `_seq` / `_ref` bookkeeping whose ordering role is tautological once the topology is one-file-per-config.

Five defects, all verified real:

- **D1 - the memory is not per project.** Directions and notes leak across projects (no `project_id` on the
  repo-global `memory.md`). A per-project folder keyed by `project_id` is required.
- **D2 - no status lifecycle.** A config is either written (dispatched) or not; there is no
  `hypothesised -> ratified | dropped` draft lifecycle, so the harness cannot track which faults are done /
  in-progress / left from the persisted state.
- **D3 - the phase-transition verbatims live in the system prompt.** The next-reasoning-phase hints are embedded in
  the agent skill; they must be injected on-the-fly in the specific tool-call responses, from proper constants.
- **D4 - `run.md` / `hunt.md` / `dispatch.md` are redundant.** The persisted environment state (the created fault
  configs) already expresses which faults are done / in-progress / left; dispatch state is the runtime plane's
  ownership; there is no dispatch node anymore.
- **D5 - `_seq` / `_ref` are tautological.** One YAML file per config makes the file name the key; the only remaining
  ordering need (note append order) is the natural list order of the notes file.

## 2. Solution

A **per-project, status-lifecycle memory store** for the hunt-orchestrator, composed of two retrievable bodies of
knowledge under one project folder:

- **Hunt configs** - the accumulated set of research directions for a project; the overlap-prevention memory. One
  YAML file per config, in `produced/` while it lives and `consumed/` once dispatched. **Oriented by the three goals
  (#202):** each config covers (G1) the technical feasibility of that fault at that unit, (G2) the initial
  concretisation (the vulnerability-class naming), and (G3) synergistic further-concretisation material
  (the downstream prior-hunt insights; `sub_fault_ids` was removed by #298). Every config attribute serves one of the three goals;
  nothing more - the config is the minimal set that still covers all three.
- **Notes** - per-config reasoning artifacts: the observations drawn from tool calls (graph_view / memory reads)
  that drove the rationale, refusal reasons, and forward-useful insights. One `memory.yaml` notes file per project.

The store is per-project (folder keyed by `project_id`, lazily created at the first write). Both bodies live in one
project folder. Note-taking is a **phase of the workflow graph** (the `note` node), so the phase is always reached
and the pair loop always closes.

**The agent-sole write model (#294).** The agent's own store tool calls
(`hunts_store(write)` / `notes(write, option="append")`) are the **sole initiator** of config and note
persistence; the harness stops initiating writes. The structured phase decisions
(`GateDecision` / `RatifyDecision` / `NoteDecision`) drive the phase transitions and the report counts, but the
harness never re-persists them - so the earlier double-write (the tool call plus the harness's re-persist of the
same decision) is gone, and two differing renderings can no longer land duplicate notes at one revival key. The
phase flow that follows a phase (the ratify drafts, the note frame, the note ledger) **reads the persisted state**
through the store seam rather than trusting the harness's own writes; an absent tool write means an absent artifact
(fail-open, never a backfill).

**The #201 carve-out (preserved).** `surface_context` is a deterministic typed assembly OWNED BY THE HARNESS
(`hunt_orchestrator._surface_context_for`); the agent never authors it. Under the agent-sole model the harness
applies it by wrapping the orchestrator's store seam: `write_config` / `update_config` inject
`config.surface_context = _surface_context_for(surface, projection)` before persisting, with the per-unit
projection threaded per phase turn. The ratify upsert's re-injection still happens (a model-authored
`surface_context` is overwritten), so removing the carve-out would reintroduce the #201 defect.

## 3. The topology

```
data/<project_id>/orchestration/
  hunt_configs/
    produced/<config_id>.yaml    (hypothesised -> ratified; the working set)
    consumed/<config_id>.yaml    (dispatched; produced->consumed is the inbox surfer's
                                  transition, delivered by another workstream - G13)
  memory.yaml                    (notes; read/write cmds, write options append/update/delete)
```

- One folder per project (`data/<project_id>/`), as today's convention - the difference is the `orchestration/`
  subtree under it.
- `consumed` is not a status enum member (G5): the produced/consumed directories express it tautologically.
- The inbox surfer (orchestrator->hunter delivery, produced->consumed movement, hunter inbox features) is
  implemented in another workstream (G13) and is OUT OF SCOPE here; this spec fixes the topology the surfer operates
  on.
- The hunt store's old per-run kind files (`run` / `config` / `hunt` / `dispatch` / `cut` / `unresolved` /
  `back_edge` / `memory` / `notes` / `spec` / `evidence`) are replaced by this topology. `_seq` / `_ref` are removed
  (G11).

## 4. Config identity and file naming

**File name (G4, ratified):**

```
<unit_id>_<CWE_ID>_<fault_class(vulnerability)>.yaml
```

- `_` is the separator. Unit ids contain `:` and `-` (`Service:catalogue-and-discovery`), so `-` and `:` are
  poisoned as separators; `_` is the one safe character.
- Semantic identity is first-class: the file name IS the config's identity. Example:
  `Service:catalogue-and-discovery_CWE-639_IDOR.yaml`.
- **Duplicate-write semantics (G4):** a later pass re-eliciting the same (unit, CWE, vulnerability class) cannot
  create a second file with the same name - the write FAILS, and the error is a **deduplication signal** the model
  interprets (it reflects on overlap and merges or refreshes instead of duplicating). This is a feature, not a risk:
  it is the enforced novelty gate at the storage layer, complementing the LLM-owned Q11 reflection.
- `CWE_ID` is the schedule fault (`fault_class`); `fault_class(vulnerability)` is the elicited vulnerability class
  (the config's identity axis, one config per class).
- **The semantic key is parsed by a CWE anchor (#279).** A testable unit is kind-qualified; a singleton System's
  orchestrator-facing unit id is the BARE kind (`AuthorizationSystem`), and a DISCRIMINATED System's unit id contains
  `::` itself (`WebPresentation:<service>::<cluster>`). The key
  `<unit_id>::<CWE_ID>::<vulnerability_class>` therefore carries MORE than three `::` segments for a discriminated
  System. The ONE shared parse, `hunt_store.split_semantic_key`, anchors on the `::<CWE_ID>::` token; it falls back
  to the plain 3-part split only for a non-CWE fault token, and it refuses a 3-part key whose last segment is a CWE
  token (an ambiguous `::`-bearing revival key). `consume_config`, `_fault_key_to_config_key`,
  `config_key_from_fault_key`, and `_validate_fault_key` all route through it; a naive `split("::")` at any site
  deadlocks the mover (a valid `::`-bearing config never moves produced -> consumed and the run hangs in `running`).
- **The `__singleton__` sentinel is elided from the orchestrator-facing identity (#279 follow-up).** The graph keeps
  the non-null `(project_id, kind, discriminator="__singleton__")` identity (`L1D-9`/`L1R-2`), but the platform's
  unit-id selection emits the bare kind for a singleton, the projection reader resolves a bare kind back to the
  singleton, the index-card key elides the sentinel at source, the prompt render elides it, and the surface-context
  matcher accepts the bare kind. So a singleton config's semantic key is a clean 3-part key and the ambiguous literal
  never reaches the mover, the persisted `surface_context`, or the orchestrator prompt. See
  `hunting-279-semantic-key-cwe-anchor-adr.md`.

## 5. The status lifecycle

**Config lifecycle (G5/G6):**

```
hypothesised -> ratified | dropped
```

- `hypothesised` - the draft written at the hypothesis-elicitation phase: only `rationale` and `research_direction`
  filled; ratification-phase fields empty.
- `ratified` - the terminal working state: the config has passed the ratification phase with its `preconditions`
  (the merged G1 preconditions-of-the-test list) and `observed_defences` (the observed target characteristics that
  hinder the tests) filled. **The config itself stops here.** (#202: the old `adversarial_capabilities` /
  `assumptions` / `technique_primitives` ratified fields are removed - capabilities and assumptions merged into the
  single `preconditions` list, technique primitives cut as redundant with the vulnerability-class naming.)
- `dropped` - the orphaned state: a config deleted during ratification (pruned by proximity/too-near same-class
  merge or novelty). Orphaned configs are NOT deleted from disk - they are statused `dropped` (G6).

**Loop states (NOT config statuses):**

- `HYPOTHESISED`, `RATIFIED`, `NOTED` - the harness's loop-state machine for the pair's iteration, embedded in the
  graph's transition logic (G2). `NOTED` is set at the note phase's tool call; the pair loop ends there, and the
  note tool's response carries the next pair's data plus the restart verbatim (G1).
- `consumed` is expressed by the produced/consumed directories, never a status enum member (G5).

**The "pair interrupted between hypothesised and ratified" scenario is NOT a risk to account for** (G6, operator) -
no crash-reconciliation logic for half-written drafts.
## 6. The tool contracts (G3)

Two store tools plus the read-only graph view form the orchestrator's memory surface:

### 6.1 `hunts_store`

Contract: `read` / `write` cmds over the produced/consumed config files.

- **`read`** needs the config identifier (the semantic file id) and accepts optionally specific attributes. The
  WHOLE surface context of a projected unit may NEVER be read through it - only the service keys, which may later be
  inspected with `graph_view` (G3). A missing or failing read degrades to a denoted error, never into the turn
  (O4 fail-open, unchanged). **Sibling-bucket reads (#202):** the store-reading contract is extended with the
  capability to read the DOWNSTREAM hunter-memory sibling bucket under the same `data/<project_id>/` tree (the
  `hunter/test-specs/<config_key>/` TestImplementationSpecs + the Q16 durable PodExport notes) - the prior-hunt
  insights of a config read those downstream records by the `::` `config_key`, shallow-projected (I3), never the
  orchestrator's own prior configs. The tool description carries this extended capability.
- **`write`** takes the hunt config object, and this tool call is the **sole writer** (#294): the harness never
  re-persists the structured decision. The `status` attribute (`hypothesised | ratified | dropped`) is carried BY
  the config object (operator correction: it must be explicit on the config, not an out-of-band harness token).
  **The identity attributes are REQUIRED and validated (#298), superseding the earlier "validation never rejects
  on missing attributes":** the payload must carry `unit_id` and `fault_class` (and `vulnerability_class`, which
  MAY be empty for a carried-bare draft). The config file name and the semantic key are DERIVED from them, and
  `hunt_id` is a deterministic function of the identity triple; the file name is never an attribute of the request
  contract. A payload missing `unit_id` or `fault_class` is a contract violation: the store raises a typed
  `ConfigIdentityError` and the tool returns a coded `hunts_store_write_rejected` error naming the missing
  attribute, never a silent degenerate-name write (the `_CWE-1220_.yaml` regression). The harness-owned
  deterministic fields are applied on the wrapped store seam (#201 carve-out, extended #298): `surface_context`
  (carrying the candidate's applies-witness folded as `fault_evidence`) and `prior_hunt_insights` - the agent never
  authors them.
- A duplicate-id write (a file name that already exists) FAILS with a denoted error - the model interprets it as
  the deduplication signal (G4). `dropped` configs stay on disk statused `dropped`, never deleted (G6).

### 6.2 `notes`

Contract: `read` / `write` cmds over `memory.yaml`, **same data contract as `hunts_store`** (G3). Write options:
`append`, `update`, `delete`.

- `read` by config identifier, optionally filtered on specific attributes.
- `write append` - a new note for a config; `update` - amend an existing note; `delete` - remove a note. The notes
  file keeps its natural append order (no `_seq`, G11).
- One note per config covering ALL decisions taken that concern that config (G8): the observations drawn from tool
  calls (graph_view or memory reads) that drove the rationale on all choices, plus anything the LLM accounts as
  potentially insightful moving forward; it must be MORE DETAILED than the config's `rationale` and walk through the
  reasoning process that yielded it.

### 6.3 `graph_view`

As-is (read-only L0/L1 view; write-shaped cypher rejected; read failure degrades to a denoted error, O5). The
service-key read of `hunts_store` defers surface inspection to `graph_view` (G3). **As of #197**: rides the ONE shared tool
`graph_view_tool.py::build_graph_view_tool` with the single-source usage contract (schema, query-language primitives,
read-only guard, `{"rows":[...]}` shape, worked example) - the same tool the orchestrator, hunter, and pod bind.

## 7. The phase-transition constants (G1/G8/G9)

The phase verbatims are **constants injected on-the-fly in the specific tool-call responses** - never embedded in
the agent system prompt (defect D3). Three constants:

- **`NEXT_RATIFY_HINT`** - carried by the `hunts_store(write, status="hypothesised")` response: instructs the model
  to reason on proximity and too-near same-class merging, then the capabilities / assumptions / technique-primitives
  analysis.
- **`NEXT_NOTE_HINT`** - carried by the `hunts_store(write, status="ratified")` response: the verbatim that strongly
  instructs note-taking. ONLY this - the next pair is NOT fed here (G1 correction).
- **`NEXT_PAIR_HINT` + pair frame** - carried by the `notes(write)` response (the pair end): the next pair's data
  plus the "start the next iteration" verbatim (G1 correction). The iteration restarts at the next pair.

The **L1 ontology primer** (G9) is a fourth constant, rendered at the top of each pair's frame (user prompt, not
system prompt): what a **System**, a **Service**, and a **DataItem** are conceived for, and the philosophy of the
domain model. It is deliberately NOT an over-specified glossary - system kinds and edge types are self-explanatory;
the primer is the fundamental knowledge that makes every other part of the graph readable.

## 8. Synergicity (G5, double-folded)

The memory + status lifecycle is synergistic in two directions:

1. **With the workflow graph** - the config lifecycle and the loop states are the graph's transition logic
   (node-per-phase `hypothesise -> ratify -> note`, G2); the harness tracks the loop state as the graph executes.
2. **With the inbox features** - the produced/consumed topology is the orchestrator->hunter handoff; the inbox
   surfer operates on it (G13, another workstream). The orchestrator and hunter are inherently different tasks, so
   their environment lifecycles differ: `hypothesised -> ratified | dropped` here; the hunter's own lifecycle
   (`hypothesised | dropped | verified | draft | ratified`) stays per #164.

## 9. Degradation

- A read failure degrades to an empty set and the harness keeps serving (O4).
- A write failure raises to the caller. Under the agent-sole model (#294) the caller is the AGENT's store tool: the
  `hunts_store` / `notes` tool catches it and degrades fail-open (a denoted error object, never into the turn), and
  the harness counts the failure it observes on the wrapped store seam (`store_write_failures`, O3) - never a
  silent corruption, never a second fallback write.
- Every tool seam degrades fail-open when the seam body is absent (C18) - a denoted error object, never a raise
  into the turn.
- An absent tool write means an absent artifact: the harness does NOT backfill a config or a note the agent did not
  write, and the note frame/ledger read whatever persisted (empty degrades the phase, never a crash).

## 10. Persistence and process-lifetime semantics

- The store is per-project and per-pass durable: the config files and `memory.yaml` survive the pass, the process,
  and the run (the old `memory.md` cross-run file and the per-run kind files are gone).
- **Every whole-file write is atomic (#340).** The orchestrator's `hunt_configs` and `memory.yaml`, the hunter's
  `notes.yaml` and spec files, and the pod's variant/experiment/export/notes files land through the shared
  `app.atomic_write` primitive (same-directory temp + `fsync` + `os.replace`), so an aborted or killed write leaves
  the previous complete file intact and a reader never sees a partial file - the corruption failure mode of EV-29.
  The unbounded growth of one `notes.yaml` (18 MB under the #338 orphan) is a SEPARATE deferred concern
  (`docs/design/atomic-write-340-adr.md`).
- **The persisted environment state IS the fault-processing tracker** (G10): the created fault configs express
  which faults are done (ratified), in-progress (hypothesised), or left (absent) - `run.md` is removed as
  redundant.
- The inbox surfer's produced->consumed movement (G13) and the hunter's consumption are another workstream's
  scope; this store is the substrate.

## 11. User stories

1. As a hunt-orchestrator, I want my memory scoped per project, so that hunting in one project never leaks
   directions or notes into another.
2. As a hunt-orchestrator, I want my accumulated hunt configs to persist across passes in a project with a status
   lifecycle, so that I can see which faults are done / in-progress / left and never re-explore a direction I have
   already ratified.
3. As a hunt-orchestrator, I want a duplicate config write to FAIL with a deduplication signal, so that novelty is
   enforced at the storage layer and I merge instead of duplicating.
4. As a hunt-orchestrator, I want the phase-transition verbatims injected in the tool-call responses, so that the
   next reasoning phase is prompted exactly when it is actionable, never pre-embedded in the system prompt.
5. As a hunt-orchestrator, I want one note per config covering all decisions that concern it, more detailed than
   the rationale and walking the reasoning process, so that forward-useful insights survive into later iterations.
6. As a maintainer, I want the topology to be the pattern for other memory systems, so that the produced/consumed +
   notes + status lifecycle shape replicates across contexts.
7. As a maintainer, I want the store to fail openly (read failure -> empty set, write failure -> warned and
   counted), matching the O3/O4 degradation canon.

## 12. Out of scope

- The inbox surfer, produced->consumed delivery mechanics, and hunter inbox features (G13, another workstream).
- The hunting agent's own memory (`hunter_tools.py` `InMemoryHunterMemory` per #164) - its lifecycle differs by
  design (G5).
- The workflow-graph rework itself (the node-per-phase REASON body) - that is the candidates-rewrite spec's scope;
  this spec fixes the store the phases operate on.
- Back-edge / targeted-recon wiring (#64).
