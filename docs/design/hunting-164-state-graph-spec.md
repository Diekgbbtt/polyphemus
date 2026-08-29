# Hunting spec: the state-graph hunter (tools + graph-encoded workflow)

*Status: spec (contract), NOT implementation.* The build spec for ticket
[#164](https://github.com/Diekgbbtt/polyphemus/issues/164), synthesised from the grilling session recorded in
`docs/design/hunting-164-state-graph-adr.md` (the ADR is the authority on the 2026-08-23 dispositions; this document
is the workbench output of the grill for the to-tickets / to-assertions / implement chain). The grilling closed all
14 grey points of the ticket.

Lineage: extends [#83](https://github.com/Diekgbbtt/polyphemus/issues/83) (the hunting-agent harness). Constrained by
the orchestrator rework spec (`docs/design/hunting-orchestrator-candidates-rewrite-spec.md`), the memory-system
pattern (`docs/design/hunting-memory-system-spec.md`), the statefulness pattern matrix, and the module-runtime
architecture.

## 1. Problem statement

The hunting agent meets its contract through a prompt, not through a workflow.
The `#83` harness (`src/polymerhus/attack/hunting/hunting_agent.py::build_hunting_agent:373`) is an async
`dispatch_fn` whose system prompt narrates the decision tree (`skills/hunting/hunting-agent/SKILL.md:32`) and whose
per-turn prompts are composed by `compose_authoring_prompt:286` / `compose_judgment_prompt:343`.
State is held in a closure string (`working_sets:392`); tool use is outside the ReAct loop; the hypothesis working
set is opaque; the pod dispatch is inline and blocks the loop; the back-edge is a heavy inline recon mechanism.

This ticket encodes the tree's *structure* as a StateGraph workflow: the graph is a **state tracker with
trajectory boundaries and intent keeping** over the ReAct engine, with a typed tool surface (`hunts_store` /
`notes` / `graph_view` / `kb_query` / `exec`), a per-hunt session thread with checkpointer + compaction +
capability middleware, and the back-edge cut in favour of the `exec` tool.

## 2. The ratified architecture

### 2.1 The graph does state tracking, not navigation

The graph does NOT navigate the decision tree.
It does **state tracking, trajectory boundaries, and intent keeping**, in both the outer loop (hunt phases) and the
inner loop (per-fault candidate evaluation).

- The **engine is the ReAct loop**: the model navigates the #83 decision tree freely, in any order the evidence
  justifies.
- The **harness derives gates dynamically from the model's tool calls**: it reads a transition verbatim (a status
  parameter on a `hunts_store`-analogue write), updates the tracked state machine, moves items between the semantic
  lists, and **forces the next action** by injecting a phase-transition constant in the response it feeds back.
- **HuntState is the semantic state directly**: `hypothesised_faults`, `verified_faults`, `dropped_faults`,
  `ratified_specs` (plus a phase flag). Items move between lists on the tool-call-driven actions.
  The trail is only the trajectory record, never the authoritative state.
- A fault-hypothesis state (including the ratified-in-spec state) is **environment state tracked by the harness,
  NOT a graph node**.
- After the full fault-hypothesis list is processed, the harness enters **idle state**: it polls its inbox for
  pod-verdict messages (fed by the inbox surfer loop).
  The verdict-consumption workflow graph is **OUT OF SCOPE**: there is no `waiting-for-verdict` node; the
  placeholder is a separate workflow graph (or an empty node) that chooses a branch by the type of the fed message.

### 2.2 The state machine is passive - detection and push, never blocking

The state transition is **driven by the LLM reasoning**.
The StateGraph does **NOT block any tool call in any state** - it never gates a tool call on the current state
(consistent with the passive-lifecycle ruling: no illegal-transition rejection, no steering back).
The graph is declassified to **mostly a state tracker with DETECTION and PUSHES**: it observes the LLM's tool
calls, detects the status verbatim, and pushes the corresponding list move + the injected transition constant.

### 2.3 The lifecycle verbatim (authoritative)

The model's verbatim `{hypothesised, verified, dropped, specified}` is authoritative and replaces in full the
SKILL.md working-set `{open, dispatched, closed, dropped, confirmed}`.
The single source of truth is a **`hunter_state.py`** module.
The lifecycle, driven by the model's reasoning:

- `grounding` phase: first and subsequent `kb_query` calls prompt for D3 (tracked as the grounding phase);
  the model may advance its reasoning to DECOMPOSE/GENERATE while the harness state is still `grounding`.
- A `hunts_store`-analogue write carrying the fault list `status="hypothesised"` while grounded triggers the
  advance to the `hypothesised_faults` state; the injected constant suggests evaluating D2 critically or addressing
  the first hypothesised fault. Further appends in this state do not change the state.
- An update carrying `status="verified"` or `status="dropped"` moves the fault to `verified_faults` / `dropped_faults`
  and suggests moving on to commit-specification.
- An update carrying `status="specified"` moves the fault to `ratified_specs` and starts the next loop iteration.
- A fault may be dropped at any stage, including mid-specification.

### 2.4 The deterministic surface

The deterministic surface is exactly: the state machine (list moves + the injected constants), `derive_verdict`
(harness-pure), record appends, and the terminal assembly.
`derive_verdict` stays harness-pure, but its wiring node lives in the OUT-OF-SCOPE verdict-consumption workflow
graph - it is **stale for the moment**.

### 2.5 Heuristics

`DISCRIMINATE` and `RANK` collapse into the GENERATE step as reasoning micro-step verbatims:

- discriminate: "remarkably hypothesised faults must be clearly distinguishable";
- ranking: carried by the hypothesised-faults persistence instruction ("try to sort the faults according to their
  risk as likelihood x impact and persist them with that order using the tool").

**Any symbolic-layer ranking logic is cut**: ranking is tautological and defined by the write-time order.

## 3. HuntState and the graph channels

`HuntState` is a LangGraph `TypedDict`. The StateGraph holds the lists; the harness is the **sole writer**
(the model never writes state directly - it signals via tool calls, the harness interprets).

| Channel | Reducer | Role |
|---|---|---|
| `phase` | last-write | `grounding | hypothesised | evaluating | concluded` (the outer loop) |
| `hypothesised_faults` | last-write | the ordered candidate set (the model's write-time rank order) |
| `verified_faults` | last-write | faults the model marked verified |
| `dropped_faults` | last-write | faults the model marked dropped (incl. mid-specification) |
| `ratified_specs` | last-write | faults whose spec reached `status="specified"` |
| `current_fault` | last-write | the fault the inner loop is on |
| `injected_constant` | last-write | the phase-transition push for the next LLM step |
| `trail` | `operator.add` | the trajectory record (replay only, never authoritative) |
| `config` / `tools` | read-only | the HuntConfig + the tool surface, assembled by the driver |

There is **no `messages` channel**: the ReAct turns own their message history in the per-hunt session checkpointer.

The `FaultItem` shape (the fault-draft content): `{fault_id, mechanism, supports, conflicts, test, status}`.
The `SpecItem` shape: `{spec_id, fault_key, fault, strategy, status, spec_ref, experiment_ref}`.

## 4. The graph sketch (grilled)

```
HuntState channels: phase, hypothesised_faults, verified_faults, dropped_faults,
                    ratified_specs, current_fault, injected_constant, trail, config, tools

START -> supervise            (the state tracker: the sole entry)
supervise -> detect           (deterministic: dispatch by the observed tool-call verbatim)
detect  --status=hypothesised--> push_hypothesised   (grounding -> hypothesised_faults; inject the D2 constant)
detect  --status=verified-->      push_verified      (hypothesised -> verified_faults; inject the commit constant)
detect  --status=dropped-->       push_dropped       (-> dropped_faults; inject the next-fault constant)
detect  --status=specified-->     push_specified     (verified -> ratified_specs; inject the next-iteration constant)
detect  --no transition-->        supervise          (appends / reads / kb / exec / graph_view: no state move)
push_* -> supervise               (static; the next push is ready)
supervise --hypothesis list exhausted--> END         (idle: verdict consumption is the OUT-OF-SCOPE separate graph)

THE REACT ENGINE RUNS OUTSIDE THE GRAPH (the turn-by-turn driver):
  per LLM step the harness:
    1. runs one session-seam turn on HuntSession(run_id, hunt_id)  (checkpointer + compaction + capability)
    2. observes the returned tool call (or final text)
    3. invokes the graph's detect/push with the observation
    4. reads the pushed injected_constant and composes the next step's input
```

Mechanisation notes (ratified):

- The graph holds state + transition logic; the transitions are driven by the LLM reasoning, never blocked.
- The turn-by-turn granularity requires the explicit-node topology: the built-in `run_session_turn` /
  `arun_session_turn` seam (`app/llm/session.py:284-353`) runs the whole model<->tool loop to completion in ONE
  `agent.invoke`, so intermediate tool calls do NOT return control. The tools are therefore bound OUTSIDE the agent
  and executed by the harness between steps; every LLM call still rides the session seam, so the checkpointer,
  compaction (#95 D9), and capability (#99) middlewares attach.
- The graph is compiled in-memory per hunt (OUTLIER-1, no graph-level checkpointer).

## 5. The tool surface

The tool contract is replicated from the orchestrator's minimalised surface
(`hunting-orchestrator-candidates-rewrite-spec.md` 3.4): `hunts_store` / `notes` / `graph_view`, read/write cmds,
no back-edge tool, no budget tool. Tool names are reused verbatim. The hunter's surface adds `kb_query` and `exec`.

| Tool | Contract | Notes |
|---|---|---|
| `hunts_store` | `read` / `write` cmds; `write` takes the fault/spec object carrying the `status` attribute (`hypothesised | verified | dropped | specified`); `read` by id + optional attributes, never the whole surface | The status-bearing write seam; the transition verbatim lives here. Duplicate-id write FAILS as a *very rare* novelty gate (G4/G5); re-authoring UPDATES the existing file in place. `graph_view` is the surface-inspection tool, never this tool |
| `notes` | `read` / `write` cmds, same data contract; write options `append`, `update`, `delete` | One note per fault covering all decisions that concern it, more detailed than the rationale |
| `graph_view` | read-only L0/L1 view; write-shaped calls rejected | The hunter's target-knowledge inspection (G8a) |
| `kb_query` | LightRAG `QuerySpecV1` -> `AnswerBundleV1` | Retires `symptom_kb.py`'s typed seams (R1). Consumed directly in the author lane. Fail-open (empty/raising -> degraded grounding, C2/C3). **WIRED from scratch onto the lightrag branch's single `query_lightrag` tool** (config-gated by `HUNTING_LIGHTRAG_TOOL`): the `KbQueryTool` keeps the local `QuerySpecV1`/`AnswerBundleV1` mirror as its args/response contract, but when the opt-in flag is on it invokes the real `build_lightrag_tool`; the injected `kb_fn` seam (contract tier) is used only when the flag is off. The `lightrag` import is lazy (no I/O at import) |
| `exec` | Kali-container exec, `EXEC_TIMEOUT_S` per call | Unbounded at the harness level - the model decides (R2b). NEVER produces the hypothesis verdict; the pod remains the only source of experimental evidence for the committed hypothesis (partition guard) |

Phase-transition constants (G9): the hunter has its own constants, injected in the tool-call responses with the
same mechanism as the orchestrator's (constants, never the system prompt): after `hypothesised`, the D2 hint;
after `verified`, the commit-specification hint; after `specified`, the next-iteration hint.

## 6. The memory store (the hunt-config pattern replicated)

The store replicates the hunt-config memory store pattern (`hunting-memory-system-spec.md`), adapting the items and
variables to the hunter domain. Adaptation dispositions G1-G9:

- **Per-project scoping (G1)**: `data/<project_id>/hunting/test-specs/<fault_key>/...`.
- **Single module root (G2)**: produced and consumed both under `data/hunting/` (sibling to `data/hunts/`,
  `data/pod-memory/`).
- **Filename separator (G3)**: `_` separator + keyword sanitisation (the pattern's G4 ruling: `-`/`:` poisoned).
- **`fault_key` (G4)**: the config key itself.
- **Spec identifier**: encodes the concrete fault semantic + testing strategy keywords.

Topology:

```
data/<project_id>/hunting/test-specs/
  <fault_key>/
    produced/<fault>_<strategy>.yaml      (authored; the file carries the status lifecycle)
    consumed/<fault>_<strategy>.yaml      (dispatched; produced->consumed is the inbox surfer's, OUT OF SCOPE)
  ... (a notes file per the `notes` tool, same data contract)
```

- One file per spec; **file creation, no append**.
- The produced/ spec file carries the status: the `hypothesised` write creates the fault draft, `verified` updates
  it, `specified` completes it into the full spec - "the persisted environment state IS the fault-processing
  tracker".
- Duplicate-write FAILS as a novelty gate (very rare); re-authoring updates the existing file in place.
- **Experiment logs live in a DIFFERENT store** on the file system, linked via an identifier (the spec id /
  pod result ref) - not in this tree.

**The `fault_key` contract (pinned, #199):** the fault_key is the hunt's own config identity, model-emitted
through the tool surface but never model-trusted (the write boundary is a harness-owned gate).

- **Canonical form**: the `_`-joined `<unit_id>_<CWE_ID>_<vulnerability_class>` config file-name stem with the
  class's spaces preserved - example `Service:account-registration_CWE-1220_Privilege Escalation` (the config's
  own identity, G4/ADR Q13 `config_id`).
- **The `::`-joined semantic twin** (`hunt_store.semantic_key`) is accepted by the store's form rule and by the
  gate; the model is instructed to emit the canonical `_`-joined form.
- **The harness-owned validation gate** (a deterministic, tool-bound gate embedded in the typed layer of
  `hunts_store` / `notes`, applied to writes AND reads): the model-emitted `fault_key` must follow the naming
  convention (a well-formed 3-part config key) AND its `:`-split parts must match the parts of a persisted
  hunt-config identity (the config ids living in the `HuntStore`).
- **No canonical-form resolution**: the parts are matched literally - never resolved through a cross-form
  conversion of the model's string.
- **A mismatch is a denoted error**: a key that fails convention or existence returns the `fault_key_mismatch`
  denoted error (mirroring the `invalid_args` / `duplicate_spec` convention; never a raise into the turn, never
  a fabricated folder); the model reflects on it like the G4 dedup signal and corrects its key.
- **The note-key rule**: a note is keyed `<config_key>:<note_name>`; the durable pod-export note is keyed
  `<config_key>:pod-export:<spec_id>` with action `update` (one current record per (config, spec) - one
  TestImplementationSpec yields at most one PodExport), and the pod session id lives ONLY in
  `provenance["source"]`, never in the key.

## 7. The ReAct host and runtime integration

- **Turn-by-turn driver** through the session seam: every LLM step is one `arun_session_turn` on the per-hunt
  `HuntSession(run_id, hunt_id)` thread (the `HuntingHunterActor` / `HuntingActorRegistry` seam).
- **Checkpointer**: resolved via `module_context("hunting")` -> `get_session_checkpointer()` (the module index,
  flushed by the run-terminal + shutdown flush, #123). The graph is compiled in-memory per hunt.
- **Middleware (R5)**: compaction (#95 D9, `build_hunter_compaction_middleware`) AND capability (#99) ride every
  ReAct `create_agent` turn.
- The harness wraps the whole hunt in `hunting_span(run_id, hunt_id)` + the `hunt_session` ContextVar rollback lane
  (unchanged).

## 8. The back-edge cut (impact map, ratified)

The inline back-edge (S5/S6, D67-14) is cut COMPLETELY from the hunter and functionally replaced by the `exec` tool.

- **Removed from the hunter**: `hunting_agent.py` `dispatch_fn(config, routed)` / `_dispatch(config, routed, ...)`
  (the `routed` parameter), `_reenter(...)` (the D67-14 re-entry node), the D5 `back_edge` branch of
  `_judge_and_finish(...)`, the `back_edge` next_step + routed-results section of `compose_judgment_prompt(...)`,
  and the `back_edge_needs` parameter of `_result(...)`; `hunt_orchestrator.py` `DispatchResult.back_edge_needs` and
  the inline round loop.
- **Kept**: the orchestrator's park/resume back-edge (S3, orchestrator-owned), `_record_back_edge`,
  `OrchestratorTools.back_edge`, the `back_edge` store kind.
- **Replacement**: the `exec` tool for cheap claim-verification probes inside VERIFY-CLAIMS.
  The pod remains the ONLY source of experimental evidence for the committed hypothesis.

## 9. Degradation (unchanged canon)

- A read failure degrades to an empty set and the harness keeps serving (O4).
- A write failure raises to the caller, which warns and keeps serving (O3) - never a silent corruption.
- Every tool seam degrades fail-open when its body is absent - a denoted error object, never a raise into the turn.
- A raising/empty `kb_query`, a raising pod, or missing config parts degrade the run, never raise (C2/C3/O5).

## 10. Out of scope

- The verdict-consumption workflow graph + the inbox surfer (produced->consumed movement, orchestrator->hunter and
  hunter->pod delivery, `pending_verdicts` consumption) - another workstream.
- The test-executor pod (#84, a separate build); the hunter only contracts against its typed handoff.
- The fault-KB / symptom-technique KB content, `symptom_kb.py`'s typed seams (retired here), the closed-enum pattern
  engine (#81), the DAG plan-control tool (#136), the exploit submodule.
- No `MERGE` Cypher outside `l1_curator`; no `.env` edits; no L0/L1 writes via the hunter (only via the `exec` pod
  tool).

## 11. Test seams

The seams are the graph + the pure state machine + the tool seams, per the R6 ruling (the full assertions workbench
is reviewed AFTER this refactor; the test-infra specification is deferred to the to-assertion phase):

- **State machine (pure)**: `hunter_state.py`'s detect/push transitions tested as a pure harness function - the
  lifecycle `hypothesised -> verified | dropped -> specified`, the no-block invariant, the injected constants.
- **Graph**: a compiled `StateGraph` driven with `ainvoke` over injected tool observations; asserts the channel
  moves and the trail append.
- **Tool seams**: `FakeLightRagTool` (returns an `AnswerBundleV1`-shaped bundle / raises), `FakeMemoryStore` (a temp
  dir under the G1-G9 topology), `FakeExec` (scripted probe results) - following the pod's
  `KbQueryTool`/`ExecTool` pattern (the former `kb_retrieve` seam is retired).
- **The hunting-agent contracts** (`tests/attack/test_hunting_agent.py`, `test_hunting_agent_contracts.py`) are
  updated only after the dispositions land; the hermetic e2e (`tests/e2e/test_hunting_agent_isolated_e2e.py`) stays
  hermetic over the compiled graph with fake tools + the real skill file.
- E1-E2 stay explicitly BLOCKED on the pod surfer wiring (documented, not faked).

## 12. User stories

1. As a reviewer, I want to read `HuntState` and see which faults are `hypothesised | verified | dropped |
   specified`, so that the hunter's intent is inspectable across turns.
2. As a reviewer, I want the trajectory replayable from the state lists and the trail, so that I can tell which
   evidence closed a gap at a decision point.
3. As the hunter, I want the decision tree navigated by the ReAct engine, so that the #83 free-navigation
   architecture is preserved.
4. As the harness, I want the state machine to detect the model's status verbatims and push the transitions, so
   that state is tracked without blocking any tool call.
5. As the harness, I want the phase-transition constants injected in the tool-call responses, so that the next
   reasoning phase is prompted exactly when actionable, never pre-embedded in the system prompt.
6. As the hunter, I want the `hunts_store`/`notes`/`graph_view`/`kb_query`/`exec` surface, so that memory, KB, and
   target-probe access live inside the ReAct loop.
7. As the operator, I want the memory store per-project with produced/consumed + status-bearing files, so that the
   persisted environment state IS the fault-processing tracker.
8. As the operator, I want the back-edge cut and replaced by the `exec` tool, so that target-knowledge gaps are
   resolved by bounded probes rather than inline recon.

## 13. References

- `docs/design/hunting-164-state-graph-adr.md` - the authority on the dispositions.
- `docs/design/hunting-83-hunting-agent-implementation.md` - the cognitive architecture + verdict semantics.
- `docs/design/hunting-orchestrator-candidates-rewrite-spec.md` - the orchestrator tool surface + graph envelope
  (no dispatch node).
- `docs/design/hunting-memory-system-spec.md` - the replicated memory pattern.
- `docs/design/statefulness-pattern-matrix.md` - the execution-model classification.
- `src/polymerhus/attack/hunting/hunting_agent.py`, `actors.py`, `hunt_store.py`, `orchestrator_graph.py`.
- `src/polymerhus/app/llm/session.py`, `actor.py`, `compaction.py`, `capability.py`.
- `skills/hunting/hunting-agent/SKILL.md`.