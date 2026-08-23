# ADR: #164 state-graph hunter - grilling dispositions and revised topology

*Status: LIVING - grilling in progress (2026-08-23). Records the operator's dispositions as the #164 grilling closes each grey point; the workbench for the to-spec synthesis (`~/.claude/skills/to-spec/`). Prior decision context: #83 (implementation doc), #110 (orchestrator graph engine, DP-5), #84-D84 (pod regrounding), the statefulness-pattern-matrix, and the module-runtime-architecture doc.*

## The regrounded architecture (operator ruling, 2026-08-23)

The graph does NOT navigate the decision tree.
It does **state tracking, trajectory boundaries, and intent keeping**, in both the outer loop (hunt phases) and the inner loop (per-fault candidate evaluation).

- The **engine is the ReAct loop**: the model navigates the #83 decision tree freely, in any order the evidence justifies.
- The **harness derives gates dynamically from the model's tool calls**: it reads a transition verbatim (a status parameter) in a tool-call response, validates it against the tracked state machine, moves items between the semantic lists, and forces the next action by suggesting it in the response it feeds back.
- **HuntState is the semantic state directly**: `hypothesised_faults`, `verified_faults`, `dropped_faults`, `ratified_specs` (plus the `grounding` phase flag); items move between lists on the tool-call-driven actions.
- A fault-hypothesis state (including the ratified-in-spec state) is **environment state tracked by the harness, NOT a graph node**.
- After the full fault-hypothesis list is processed, the harness enters **idle state**: it polls its inbox for pod-verdict messages (fed by the inbox surfer loop).
  The verdict-consumption graph is **currently OUT OF SCOPE**: there is no `waiting-for-verdict` node; the placeholder is a separate workflow graph (or an empty node) that chooses a condition based on the type of the fed message.

## Ratified dispositions

### GP1 - graph scope and router discipline (RATIFIED: the hybrid, operator-defined)

The graph is a state-tracking and trajectory-boundary layer over the ReAct engine, not a router graph.
The single `Command` router discipline (DP-5) does not apply in the draft's form: there are no `query_gate`/`coverage_gate` pass routers.
The D1/D2/D3 boundaries are tracked as harness state (the `grounding` phase flag and the decision records), driven by tool-call responses, never by graph routing.

### GP2 - deterministic vs ReAct boundary (RATIFIED, with amendments)

- **(a) memory_write is a MODEL tool call** - it IS the transition signal of the state machine.
  This diverges from the orchestrator's #139 deterministic note node, and the divergence is RATIFIED: the orchestrator's note step is a static per-pair bookkeeping node; the hunter's memory write is the actuation channel of the state machine. Different roles.
- **(b) state is environment state, not graph nodes** - the harness owns environment-state tracking; the fault-hypothesis state (including the ratified-in-spec state) is never a graph node.
  After the hypothesis list is exhausted the harness idles, polling its inbox for pod-verdict messages.
  The verdict-consumption workflow graph is OUT OF SCOPE: a separate workflow graph (or empty node) chooses a branch by the fed message type; there is no `waiting-for-verdict` node.
- **(c) two misdesigns blocked**:
  1. TestImplementationSpecs live in **separate files in distinct folders**; the same topology applies to the hunt-config memory store (patterns applied ubiquitously). **No append - file creation.**
  2. Experiment logs live in a **different store** on the file system, linked via an identifier.
  The model authors the spec when it commits its more detailed specification via the memory tool (`type: write`, `status: specified`); the harness only tracks state, moving the spec among the lists.
- **(d) the deterministic surface** is: the state machine (transition legality + list moves), `derive_verdict`, record appends, and the terminal assembly. Nothing else.
  `derive_verdict` stays harness-pure (RATIFIED), but its wiring node lives in the verdict-consumption workflow graph that is OUT OF SCOPE - it is **stale for the moment**.

### GP4 - state shape and vocabulary (RATIFIED)

- The model's verbatim `{hypothesised, verified, dropped, specified}` is **authoritative and replaces in full** the SKILL.md working-set `{open, dispatched, closed, dropped, confirmed}`.
- The single source of truth is a **`hunter_state.py`** module.
- The StateGraph **holds the lists**.

### GP5 - the back-edge (RATIFIED: cut from the hunter, replaced by the exec tool)

The back-edge is a **legacy feature, cut off completely from the hunter** and functionally replaced with the simple exec tool.
The impact map is RATIFIED:
- Cut from the hunter: `hunting_agent.py` `routed`/`_reenter`/the D5 `back_edge` branch/`compose_judgment_prompt`'s `back_edge` option/`_result`'s `back_edge_needs`; `hunt_orchestrator.py` `DispatchResult.back_edge_needs` and the inline round loop (803-815); the related docs and tests.
- Kept: the orchestrator's park/resume back-edge (S3, orchestrator-owned), `_record_back_edge`, `OrchestratorTools.back_edge`, the `back_edge` store kind.
- Functional replacement: the exec tool (pod's `EXEC_TIMEOUT_S` pattern) for cheap claim-verification probes inside VERIFY-CLAIMS. The pod remains the ONLY source of experimental evidence for the committed hypothesis.

### GP6 - hunter memory store (RATIFIED: the pattern + topology; adaptation grey points pending)

A new memory store **owned by the hunter** is needed, replicating the hunt-config memory store pattern (`hunting-memory-system-spec.md`, the pattern document): per-`fault_key` folders, one file per spec, **no append - file creation**, produced/consumed directories, status carried by the object, duplicate-write FAILS as a dedup signal.
- `fault_key` = the config key itself.
- The spec identifier encodes the concrete fault semantic + testing strategy keywords.
- Topology: `data/<project_id>/hunting/test-specs/<fault_key>/produced/<fault>_<strategy>.yaml` and `data/<project_id>/hunting/test-specs/<fault_key>/consumed/<fault>_<strategy>.yaml`.
- The adaptation surface is RATIFIED (G1-G9, 2026-08-23):
  - **G1** per-project scoping: `data/<project_id>/hunting/test-specs/<fault_key>/...`.
  - **G2** single module root `data/hunting/` for produced and consumed (sibling to `data/hunts/`, `data/pod-memory/`).
  - **G3** `_` filename separator + keyword sanitisation (the pattern's G4 ruling: `-`/`:` poisoned).
  - **G4** the produced/ spec files carry the status: the `hypothesised` write creates the fault draft, `verified` updates it, `specified` completes it into the full spec.
  - **G5** re-authoring UPDATES the existing file in place; the duplicate-write novelty gate is a **very rare** path.
  - **G6** the hunter has a `notes` tool + notes file (same data contract as the spec tool).
  - **G7** produced = authored, consumed = pod-dispatched; the produced->consumed movement is entirely the inbox surfer loop's ownership, OUT OF SCOPE.
  - **G8** the hunter's tool surface = `hunts_store`-analogue + `notes` + `graph_view` (the read-only L0/L1 view, write-shaped rejected) + `kb_query` + `exec`.
  - **G9** the hunter has its own phase-transition constants, injected in the tool-call responses with the same mechanism as the orchestrator's (never the system prompt).

### GP8c - lifecycle enforcement (RATIFIED: passive for the moment)

State-machine enforcement (rejecting illegal transitions + steering) is deferred: it is complex, so the harness tracks the lifecycle **passively** for now. The forced-next-action suggestions remain; the legality check does not.

### GP8d - tool surface (RATIFIED: the minimalised surface + kb_query + exec)

The orchestrator tool surface was minimalised (spec: `hunts_store` / `notes` / `graph_view`, read/write cmds, no back-edge tool, no budget tool).
The hunter uses all of its tools **plus `kb_query` and `exec`** (the back-edge replacement).

### GP7 - heuristics (RATIFIED)

`DISCRIMINATE` and `RANK` collapse into the GENERATE step as reasoning micro-step verbatims:
- discriminate: "remarkably hypothesised faults must be clearly distinguishable";
- ranking: carried by the hypothesised-faults persistence instruction ("try to sort the faults according to their risk as likelihood x impact and persist them with that order using the tool").
**Any symbolic-layer ranking logic is cut**: ranking is tautological and defined by the write-time order.

## Round 4 dispositions (R1-R6, 2026-08-23)

### R1 - kb_query tool (RATIFIED: LightRAG types, retire the typed seam)

The existing `symptom_kb.py` typed seam (`query_symptom_technique`) is retired - its design made assumptions about the knowledge base that do not hold.
A typed seam is not strictly needed now and is deferred.
The LightRAG branch (local `lightrag-probe` worktree) already provides the typed query/response layer (`QuerySpecV1`, `AnswerBundleV1`); the hunter consumes `AnswerBundleV1` directly in its author lane.
The LightRAG integration is a **simultaneous workstream**; this ticket's role is only to add the tool to the agent, replicating the project's tool-implementation pattern.

### R2 - exec tool bounds (RATIFIED: unbounded at the harness level)

The exec tool is **unbounded at the harness level** - the model decides when to probe.
Per-call `EXEC_TIMEOUT_S` remains a tool-internal concern (replicated from the pod's `pod/tools.py`).
The Q8 partition guard stays: exec never produces the hypothesis verdict; the pod remains the only source of experimental evidence for the committed hypothesis.

### R3 - tool naming (RATIFIED: reuse the names)

Reuse the `hunts_store` + `notes` names verbatim for the hunter's memory tools (the contract IS the identity; the agents never share a tool list).

### R4 - interception model (RATIFIED: turn-by-turn driver; AMENDED 2026-08-23 - detection + push)

The ReAct loop is a sequence of tool calls and LLM reason passes; a tool call returns control to the harness, which runs the tool locally and returns the result.
The StateGraph nodes hold state and transition logic.
The turn-by-turn driver is the most synergic mechanism; as long as underneath LangGraph each step is again an LLM turn, the context checkpointing and compaction middlewares apply.
VERIFIED caveat (2026-08-23): the built-in `run_session_turn`/`arun_session_turn` seam (`session.py:284-353`) runs the whole model<->tool loop to completion in ONE `agent.invoke` - intermediate tool calls do NOT return control.
The turn-by-turn granularity therefore requires the explicit-node topology (each LLM step a graph super-step, tools executed by the harness between steps - the pod's contract-tier lane shape), so every LLM call still rides the session seam and the middleware/checkpointer attach.

**Refinement (operator correction, 2026-08-23):** the (i) mechanisation holds - SessionState holds state + transition logic, turn-by-turn control - BUT the **state transition is driven by the LLM reasoning**, and the StateGraph does **NOT block any tool call in any state**.
The graph is declassified to **mostly a state tracker with DETECTION and PUSHES for state transitions**: it observes the LLM's tool calls, detects the status verbatim, and pushes the corresponding list move + the injected transition constant - it never gates a tool call on the current state (consistent with the GP8c passive lifecycle).

### R5 - middleware (RATIFIED: (a))

Both compaction (#95 D9, `build_hunter_compaction_middleware`) AND capability (#99) middleware ride every ReAct `create_agent` turn.

### R6 - test seams (RATIFIED: (a), infra spec deferred)

`(a)` is close to correct - `FakeLightRagTool`/`FakeMemoryStore`/`FakeExec`, the compiled graph driven with `ainvoke`, the pure state machine tested directly.
The full assertions workbench (C1-C12, E1-E2) must be **reviewed after this refactor**; the test-infra specification is **deferred to the to-assertion phase**.

## Outer-container correction (operator, 2026-08-23)

The supervisor's dispatch node is **REMOVED** per the ratified candidates-rewrite spec (`hunting-orchestrator-candidates-rewrite-spec.md`, G12): the #110 supervisor graph envelope is `loop -> reason -> END`, with **no dispatch node and no budget stage**; the schedule unit is a **fault** (one REASON pass per fault over all its matched units), and the REASON body is a node-per-phase workflow graph (`hypothesise -> ratify -> note`).
Dispatch is done **out-of-band by the inbox surfer loop** (the runtime plane owns dispatch state; the produced->consumed movement is G13, another workstream).
The hunter is therefore NOT invoked by a graph dispatch node - it is fed `HuntConfig`s from its inbox by the surfer.

## Open frontiers (pending grilling)

1. **The verdict-consumption workflow graph + surfer** (out of scope, another workstream).
2. **Test-infra specification** (deferred to the to-assertion phase).