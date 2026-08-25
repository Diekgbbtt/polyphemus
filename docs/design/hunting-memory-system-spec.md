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
  YAML file per config, in `produced/` while it lives and `consumed/` once dispatched.
- **Notes** - per-config reasoning artifacts: the observations drawn from tool calls (graph_view / memory reads)
  that drove the rationale, refusal reasons, and forward-useful insights. One `memory.yaml` notes file per project.

The store is per-project (folder keyed by `project_id`, lazily created at the first write). Both bodies live in one
project folder. Note-taking is a **phase of the workflow graph** (the `note` node), so it is always reached, never
dependent on the model remembering to write.

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

## 5. The status lifecycle

**Config lifecycle (G5/G6):**

```
hypothesised -> ratified | dropped
```

- `hypothesised` - the draft written at the hypothesis-elicitation phase: only `rationale` and `research_direction`
  filled; ratification-phase fields empty.
- `ratified` - the terminal working state: the config has passed the ratification phase with its
  `adversarial_capabilities` / `assumptions` / `technique_primitives` filled. **The config itself stops here.**
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
  (O4 fail-open, unchanged).
- **`write`** takes the hunt config object. Any attribute specification is optional; internal schema validation
  never rejects on missing attributes (the hypothesised draft has only `rationale` + `research_direction`). The
  `status` attribute (`hypothesised | ratified | dropped`) is carried BY the config object (operator correction:
  it must be explicit on the config, not an out-of-band harness token).
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
service-key read of `hunts_store` defers surface inspection to `graph_view` (G3).

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

## 9. Degradation (unchanged canon)

- A read failure degrades to an empty set and the harness keeps serving (O4).
- A write failure raises to the caller, which warns and counts `store_write_failures` (O3) - never a silent
  corruption.
- Every tool seam degrades fail-open when the seam body is absent (C18) - a denoted error object, never a raise
  into the turn.

## 10. Persistence and process-lifetime semantics

- The store is per-project and per-pass durable: the config files and `memory.yaml` survive the pass, the process,
  and the run (the old `memory.md` cross-run file and the per-run kind files are gone).
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
