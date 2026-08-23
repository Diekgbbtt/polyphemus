# ADR: hunt-orchestrator memory + workflow-graph rework (grill dispositions, 2026-08-23)

Status: decided (grilling round for the hunt-orchestrator memory and workflow-graph
rework, 2026-08-23; operator dispositions recorded verbatim where they amend).
Ticket: #137 (memory system), #142/#143 (memory wiring + live e2e), builds on the
candidates-rewrite (#110 graph, #135 LLM-local artifacts) and precedes the
hunting-agent StateGraph rework (#164).
Base: `feat/hunting-orchestrator-candidates-rewrite` @ `aadb68b`.

## Context

The hunting memory today is an append-only markdown stub: the `memory` record kind
is the one cross-run kind, but it lives at a repo-global `<root>/memory.md`, carries
no `project_id`, and reading is a full-file scan equality-filtered on `revival_key`.
The per-run kinds (`run` / `config` / `hunt` / `dispatch` / `notes`) are keyed by
run id with `_seq` / `_ref` bookkeeping, and the gate turn is a single embedded
LLM turn whose per-unit decision tree is narrated in the system prompt - including
the phase-transition hints, which belong in tool-call responses, not the prompt.

The operator's investigation (2026-08-23) established four defects:

1. **The memory system is not designed as a system.** No single design document or
   ADR covers the hunt memory; the pieces are scattered across the store contract
   (O12), the candidates-rewrite spec (3.2/3.3/3.4), provisional terms, and the
   #68/#70 seams. The topology (per-project, produced/consumed, notes file) and the
   status lifecycle must be designed first-class, because the pattern will be
   replicated across other memory systems.
2. **The concretisation stretch is orphaned.** The #164 hunter re-design owns the
   DECOMPOSE/GENERATE hypothesis formulation; the production hunter prompt consumes
   none of the candidates-rewrite slots (`concrete_fault_candidates`,
   `research_direction`, `blocking_constraints`, `sub_fault_ids` are minted and
   never read). The orchestrator must own only the higher stretch: sub-classing the
   fault into vulnerability classes that could characterise the application itself.
3. **The phase-transition verbatims are mislocated.** The next-reasoning-phase
   hints are embedded in the agent system prompt; they must be injected on-the-fly
   in the specific tool-call responses, from proper constants.
4. **The L1 ontology is never specified to the model.** The gate prompt renders raw
   symbols (edge families, system kinds, spine keys, exposure facets) with no
   definition of what a Service, System, or DataItem is conceived for. The model
   reasons over an ontology it is never told.

## Decision

Rebuild the orchestrator's REASON stretch as a **node-per-phase workflow graph**
with a **tool-response-driven phase machine**, and rebuild the memory as a
**per-project, produced/consumed config store + notes file**, replacing the
per-run kind files.

### Workflow graph (per (unit, fault) pair, node-per-phase)

```
REASON pair (unit, fault)
  hypothesise  (node)  -> LLM calls hunts_store(write, config, status=hypothesised)
  ratify       (node)  -> LLM may update/delete/create configs; must END with a
                          tool call carrying status=ratified (+ the ratified fields)
  note         (node)  -> LLM reasons on the decision rationale; calls notes(write)
  END of pair; next pair fed in the note tool's response (the pair end)
```

The **transition logic is embedded in the graph itself** (StateGraph nodes +
harness state tracking), not in a harness variable outside the graph (G2). The
state machine per config: `hypothesised -> ratified | dropped`.

### The tool surface (G3)

1. **`hunts_store`** - contract: `read` / `write` cmds. `read` needs the config
   identifier and accepts optionally specific attributes; the whole surface context
   of a projected unit may NEVER be read through it - only service keys, which may
   later be inspected with `graph_view`. `write` takes the hunt config object; any
   attribute specification is optional and internal schema validation never rejects
   on missing attributes.
2. **`notes`** - contract: `read` / `write` cmds, same data contract as
   `hunts_store`. `write` options: `append`, `update`, `delete`.
3. **`graph_view`** - as-is (read-only L0/L1 view, write-shaped calls rejected).

The old surface (`read_memory_hunts`, `read_memory_notes`, `mint_hunt_config`,
`record_note`) is replaced by the two store tools above. There is no
back-edge-to-recon tool (standing operator ruling 2026-08-22).

### HuntConfig typing (G5 + operator amendments)

- **`status` attribute added** (operator correction - it was missing from the
  proposed typing): `hypothesised | ratified | dropped`. `noted` is a LOOP state,
  never a config status; the config itself stops at `ratified`. `consumed` is
  tautological in the memory topology (the produced/consumed directories express
  it) and is NOT a status enum member.
- **`concrete_fault_candidates[]` removed** (the hunter's DECOMPOSE/GENERATE owns
  the concrete-fault stretch).
- **`fault_hypothesis` removed** (redundant: one config per vulnerability class
  makes the class the identity axis).
- **`extension_points` removed** (redundant with `research_direction`; only
  `research_direction` survives).
- **`supposed_payload_vectors` removed** (moves into the hunter's GENERATE stretch).
- **`adversarial_capabilities` (and the assumption/blocker analysis) moved UP one
  level** into the config - no longer nested under a concrete-fault candidate.
- **`technique_primitives` added** as a config field (the capability/assumption/
  technique-primitive analysis output of the ratification phase).
- **One HuntConfig per elicited vulnerability class** - the class is the config's
  identity axis.
- **`edge_degree` transformed to the connected DataItems** (operator correction):
  in the config's surface context, a Service's `edge_degree` counts are replaced by
  the detailed specification of the DataItems it is connected to (name, type,
  sensitivity, fields, notes), mirroring the rich projection.
- `sub_fault_ids` (fold family) keeps feeding each class-config (#66
  non-conflation, G14); `kb_degraded` / materialisation / fold-family preloads are
  unchanged (G14).

### Memory topology (per project)

```
data/<project_id>/orchestration/
  hunt_configs/produced/<config_id>.yaml    (hypothesised -> ratified)
  hunt_configs/consumed/<config_id>.yaml    (dispatched; the inbox surfer owns the
                                            produced->consumed transition, G13 -
                                            out of scope HERE, another workstream)
  memory.yaml                                (notes; read/write, append/update/delete)
```

- **Config file naming (G4, ratified):** `<unit_id>_<CWE_ID>_<fault_class(vulnerability)>.yaml`
  - `_` is the separator (unit ids contain `:` and `-`, so `-` and `:` are poisoned
    as separators); semantic identity is first-class.
  - The "later pass re-eliciting the same (unit, CWE, class)" collision is not a
    risk but a feature: the tool-call FAILS because no file with the same name can
    be created, and the LLM must interpret the error as a deduplication signal.
- **`run.md`, `hunt.md`, `dispatch.md` removed (G10/G12).** `run.md` is redundant:
  the persisted environment state already holds fault-processing tracking - the
  created fault configs express which faults are done / in-progress / left.
  `dispatch.md` state is the runtime plane's ownership; there is no dispatch node
  anymore.
- **`_seq` / `_ref` removed (G11).** `_ref` dies with the per-config-file topology;
  `_seq`'s only remaining role (note append ordering) is the natural list order of
  `memory.yaml`.
- **Orphaned configs (G6):** status `dropped`. The "pair interrupted between
  hypothesised and ratified" scenario is NOT a risk to account for (operator).
- **Budget (G7):** the O9 batch cut is dropped - the runtime plane + pod caps own
  spending (#164 keeps pod-level caps, D67-09).

### The phase-transition constants (G1/G8/G9)

- **G1 (correction):** the pair's data plus the "start the next iteration" verbatim
  is carried by the **note tool's response** (the pair end); the ratification
  response carries ONLY the "strongly take notes" verbatim. (The operator's
  earlier "ratification tool-call response" wording was a misspecification.)
- **G8 note-taking verbatim:** one note per config covering ALL decisions taken
  that concern that config; content should be mostly the observations drawn from
  tool calls (graph_view or memory reads) that drove the rationale on all choices,
  plus anything the LLM accounts as potentially insightful moving forward; it must
  be MORE DETAILED than the config's `rationale` and literally walk through the
  reasoning process that yielded the rationale.
- **G9 ontology constant:** the L1 ontology primer lives in a constant, but NOT
  ~20 over-specified lines. System kinds and edge types are self-explanatory; the
  fundamental knowledge to specify is what a **System**, a **Service**, and a
  **DataItem** are conceived FOR, and the **philosophy of the domain model** - the
  primer that makes all other parts of the graph readable.

### Synergicity with the actor-inbox model (G5, operator's clarification)

The operator's "synergic" requirement is **double-folded**: the memory + status
lifecycle must be synergistic both (a) with the **workflow graph** (the node-per-phase
transition logic embedded in the graph) and (b) with the **inbox features** (the
produced/consumed topology is the orchestrator->hunter handoff; the surfer and
delivery mechanics are another workstream, G13). The orchestrator and hunter are
inherently different tasks, so their environment lifecycles differ:
`hypothesised -> ratified / dropped` for hunt configs here; the hunter's own
lifecycle (`hypothesised | dropped | verified | draft | ratified`) stays per #164.

## Consequences

- The candidates-rewrite spec sections 3.2-3.5 and 3.8 are amended (see the
  amended spec), the HuntStore topology is superseded by the memory-system spec,
  and the assertions catalogue (C9/C15/E2/E5 and the tool-surface predicates) is
  re-scoped.
- The produced/consumed + notes pattern is the template for other memory systems
  (the operator's stated intent: "its pattern will be replicated across other
  memory systems").
- The internal ReAct workflow becomes node-per-phase with graph-embedded
  transitions; phase hints move from the system prompt into tool-call responses
  sourced from constants.
- The gate turn's input frame needs the L1 ontology primer constant so the model
  reads the graph soundly (defect 4).

## Alternatives rejected

- Keep the per-run kind files + `_seq`/`_ref` append-only store: rejected - the
  topology is not per-project, cannot express produced/consumed, and the ordering
  bookkeeping is tautological once one-file-per-config is the rule.
- Keep `record_note` as a separate harness-fired seam: rejected - the notes tool
  with read/write + append/update/delete cmds is the unified seam (G3).
- Keep the O9 budget stage: rejected (G7) - spending is the runtime plane's and
  the pod's concern (D67-09).
- Keep `concrete_fault_candidates` in the config: rejected - the #164 hunter owns
  the concrete-fault stretch; the slots are orphaned today (verified:
  `hunting_agent.py:304-314` reads none of them).
- Phase hints in the system prompt: rejected (defect 3) - they must ride the
  tool-call responses from constants.

## References

- `hunt_orchestrator.py` (`GateInput`, `LoopLedger`, `HuntConfig`, REASON body),
  `hunt_store.py` (`HuntStore`, `KINDS`, `_seq`/`_ref`), `actors.py`
  (`build_orchestrator_tool_surface`), `llm.py` (`_compose_gate_prompt`),
  `orchestrator_graph.py` (supervisor StateGraph), `hunting_agent.py`
  (dispatch prompt), #164 ADR (`hunter_graph.py`, `hunter_tools.py`,
  `hunter_state.py`), #137 ticket (memory system), `hunting-orchestrator-candidates-rewrite-spec.md`.