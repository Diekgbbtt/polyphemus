# Hunting spec: the state-graph hunter (tools + graph-encoded workflow)

*Status: spec (contract), NOT implementation.*

**Harness redesign 2026-10-18.** Section 14 supersedes the fault lifecycle, state channels, gate signals, hints, and assertions of sections 2.3, 2.4, 3, 5, 6, and 11.
The old text is retained for history.
Sections 2.1, 4, and 12 also retain the older contract for history and are not current.
The redesigned machine tracks the eight-pass hunter sequence, not the fault lifecycle.
The hunter agent is S3; the pod contract is S5; the impact map is `docs/design/unit-threat-model-spec-impact-map.md`.

The build spec for ticket
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
| `notes` | `read` / `write` cmds, same data contract; write options `append`, `update`, `delete` | One note per fault covering all decisions that concern it, more detailed than the rationale. **As of #209**: `provenance` is a TYPED `NoteProvenance` (`source` / `run_id` / `verdict_stub` / `probe_refs`, `extra="forbid"`) riding the tool-calling schema; `evidence` is prose `str`; a call omitting the required `command` or passing a dict-valued `evidence` gets a CODED teaching rejection (see `hunting-tools-design.md`) |
| `graph_view` | read-only L0/L1 view; write-shaped calls rejected | The hunter's target-knowledge inspection (G8a). **As of #197**: the ONE shared tool (`graph_view_tool.py::build_graph_view_tool`) with the single-source usage contract (schema, query-language primitives, read-only guard, `{"rows":[...]}` shape, worked example) - the hunter's bespoke `GraphViewTool` is REMOVED |
| `kb_query` | LightRAG `QuerySpecV1` -> `AnswerBundleV1` | Retires `symptom_kb.py`'s typed seams (R1). Consumed directly in the author lane. Fail-open (empty/raising -> degraded grounding, C2/C3). **WIRED from scratch onto the lightrag branch's single `query_lightrag` tool** (always-bound as of #197 - the `HUNTING_LIGHTRAG_TOOL` opt-in gate is REMOVED): the `KbQueryTool` binds the real `QuerySpecV1` as its args contract and a tolerant `AnswerBundleV1`-shaped envelope as its response contract (as of #322 the stale local `KbQuerySpec` args mirror is RETIRED); it invokes the real `build_lightrag_tool` and the injected `kb_fn` seam (contract tier) is used only when the real tool is unavailable. The `lightrag` import is lazy (no I/O at import) |
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
- **The persisted body shape varies by status (#313, pinned).** A non-`specified` body is a hypothesis-only
  `FaultItem` draft (`fault_id` / `mechanism` / `supports` / `conflicts` / `test`); a `specified` body is the typed
  `TestImplementationSpec` base (`target_identity` / `verification_symptoms` / `testing_pattern` / `assumptions` /
  `payload_vector_space` + the two NL fields), the SAME D4 shape the pod's `validate_spec` gate consumes. The spec's
  identity is the file-name stem `<fault_keyword>_<strategy_keyword>` (the ADR Q13 semantic `spec_id`), a derived
  symbol, never a payload field. Consumers gate on the persisted status: only a `specified` spec dispatches to the
  pod, only a `specified` spec is a prior-hunt insight, and a draft is never read as a completed spec.
- Duplicate-write FAILS as a novelty gate (very rare); re-authoring updates the existing file in place.
- **Experiment logs live in a DIFFERENT store** on the file system, linked via an identifier (the spec id /
  pod result ref) - not in this tree.

**The `fault_key` contract (pinned, #199):** the fault_key is the hunt's own config identity, model-emitted
through the tool surface but never model-trusted (the write boundary is a harness-owned gate).

> **SUPERSEDED (2026-10-01, #298):** the fault_key is no longer model-emitted at all. The harness BINDS it at
> tool construction (`semantic_key(unit_id, fault_class, vulnerability_class)` from the dispatched `HuntConfig`),
> so the request-field gate is replaced by the binding (`hunts_store` / `notes` can only address the hunt's own
> config; an unbound tool degrades with a coded `invalid_args`). See
> `docs/design/hunting-store-write-decisions.md`. The bullets below are kept for history.

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
  `provenance["source"]`, never in the key. **As of #209, `provenance` is a TYPED `NoteProvenance` sub-model**
  (the JSON schema the model sees declares it): `source` (the pod-session-id home, pinned here), `run_id`,
  `verdict_stub` (the surfer's durable-export trio, `surfer.py::_record_durable_pod_export`), and `probe_refs`
  (the model's structured evidence refs, ratified by #209). `evidence` is prose `str`; structured refs never go
  there - a dict-valued `evidence` is a coded teaching rejection.

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

## 14. Redesign 2026-10-18: the pass-chain tracker

### 14.1 Problem statement

The passive tracker is fault-centric.
It tracks the status verbatims `{hypothesised, verified, dropped, specified}`.
It moves faults between four semantic lists.
It injects four fault-lifecycle hints.
The redesigned hunter has no faults.
It runs a pass sequence over one loop.
Its phases mostly end without a status-bearing store write.
A tracker that waits for a fault status would never leave the first pass.

### 14.2 Solution

The tracker is refactored onto the pass sequence with proxy-signal gates.
The states are:

```
GROUNDING -> SLICE -> COLLECT -> DISCRIMINATE -> GENERATE
  -> WELL-FORMEDNESS -> VERIFY-CLAIMS -> COMPLETE
```

A state's exit signal is the most accurate available proxy:

- A store write where a real write exists.
- An interposed phase-summary note where no accurate write or tool-call terminus exists.

The machine stays passive.
It never gates a tool call.
It never rejects a transition.
It records what the model signalled.

### 14.3 User stories

1. As the harness, I want to track the eight-pass sequence, so that the trajectory shows where the hunter is.
2. As the harness, I want one exit signal per pass, so that a pass advance is unambiguous.
3. As the harness, I want a phase-summary note for the passes without a store write, so that the exit is explicit.
4. As the harness, I want the generator's spec-set write to be the exit, so that a real write advances the state.
5. As the harness, I want the terminal promote-and-declass write to be the final exit, so that the spec lifecycle closes the chain.
6. As the harness, I want to advance on a later pass's signal, so that a skipped note does not wedge the tracker.
7. As the harness, I want an earlier pass's signal to stay in the trail, so that a re-entry never moves the state back.
8. As the harness, I want inner-loop calls to stay in the trail, so that a loop does not fabricate transitions.
9. As the harness, I want the grounding KB query to carry a retrieval-gap rider, so that the gap check survives without a transition.
10. As the harness, I want one hint per transition, so that the next pass is prompted exactly when actionable.
11. As the harness, I want the hints injected in the tool responses, so that the system prompt stays stable.
12. As the harness, I want the phase-summary note rewritten on a re-iteration, so that the latest summary wins.
13. As the harness, I want the note kind `phase_summary`, so that the phase notes are distinguishable from other notes.
14. As the harness, I want the state channel to carry the pass, so that the graph and the prompt agree.
15. As the harness, I want the spec set channel to carry the current specs, so that the trajectory shows the set.
16. As the harness, I want the fault lists removed, so that no dead state remains.
17. As the harness, I want the old hints removed, so that no prompt says "verified" or "specified".
18. As the harness, I want the spec status vocabulary to be `{hypothesised, ratified, dropped}`, so that all artifacts agree.
19. As the harness, I want no schema gate, so that the model is never blocked.
20. As the harness, I want a pure detector and a pure advance, so that the state machine is unit-testable.
21. As the harness, I want the graph to hold no model, so that the tracker stays passive.
22. As the harness, I want a forward jump to record the skipped states, so that a jump is auditable.
23. As the harness, I want a trail-only backward signal to be harmless, so that a re-entry is not an error.
24. As the harness, I want the terminal state to end the hunt, so that the spec set is final.
25. As a reviewer, I want the proxy-signal matrix, so that every gate's accuracy is justified.
26. As a reviewer, I want the removed verdict surfaces gone, so that no code pretends to derive a verdict.
27. As a reviewer, I want the old lifecycle assertions superseded, so that the tests pin the new chain.
28. As a reviewer, I want the grounding note's exit to be the only grounding terminus, so that a variable-length exploration is trackable.
29. As a reviewer, I want the collection note's exit to be the only collection terminus, so that the last query is not mistaken for a mid-sequence query.
30. As a reviewer, I want the well-formedness iteration to stay in the same pass, so that the trajectory does not show inner-loop states.

### 14.4 The proxy-signal matrix

| # | State | Exit to | Proxy signal | Accuracy argument |
|---|---|---|---|---|
| 1 | `GROUNDING` | `SLICE` | Interposed `phase_summary` note `phase:grounding` | Grounding is read-only exploration: target surfaces, class skill, methodology KB, HTTP history, graph, notes. The query count varies and no write or tool call is a reliable terminus. The phase-end note is the only explicit terminus. The pass is an explore/exploit loop: explore inside, exploit is the exit, finalised by the note. |
| 2 | `SLICE` | `COLLECT` | Interposed `phase_summary` note `phase:slice` | The failure-mode slice is prose reasoning. It ends in no spec and no store write. |
| 3 | `COLLECT` | `DISCRIMINATE` | Interposed `phase_summary` note `phase:collect` | Collection is a variable-length run of methodology-KB and store queries. The last query is indistinguishable from a mid-sequence query. The phase-end note is the only accurate terminus. |
| 4 | `DISCRIMINATE` | `GENERATE` | Interposed `phase_summary` note `phase:discriminate` | The discrimination analysis produces no artifact. The phase-end note is the explicit terminus. |
| 5 | `GENERATE` | `WELL-FORMEDNESS` | `hunts_store` write: the whole `specs` list, all with `status=hypothesised` | One batched store write carries the whole set. The signal is unambiguous and cannot fire on the first spec of a multi-spec set. |
| 6 | `WELL-FORMEDNESS` | `VERIFY-CLAIMS` | Interposed `phase_summary` note `phase:well_formedness` | The pass assesses the set in prose. The [D2] iteration does not move the tracked state. The confirmation note is the exit. The note records merges and drops; the terminal write applies the statuses. |
| 7 | `VERIFY-CLAIMS` | `COMPLETE` | `hunts_store` write: the whole `specs` list with survivors `ratified` and unfeasible specs `dropped` | The terminal commit is a real store write. The probe iterations do not move the tracked state. |
| 8 | `COMPLETE` | - | - | Terminal. The hunt ends on the final spec set. |

`START -> GROUNDING` is implicit: the hunt begins ungrounded.

### 14.5 Signal acceptance

The machine advances only on the current state's declared exit signal.
The acceptance rule is:

- **Expected exit**: the signal belongs to the current state. Advance to the next state.
- **Forward jump**: the signal belongs to a later state. Advance to that state's next state and record the skipped states in the trail as `skipped`.
- **Backward signal**: the signal belongs to an earlier state. Append to the trail as `reentry` and never move the state back.
- **No signal**: append nothing and stay.

The rule is a pure function:

```
detect_signal(state, signal) -> SignalOutcome
```

where `SignalOutcome` is one of:

- `advance(target)`
- `forward_jump(target, skipped)`
- `trail_only(reason)`
- `none`

`advance_state(state, outcome, signal) -> (new_state, hint, trail_entry)`

The observed signal rides the call as a third argument.
The trail entry records it (see below), and the listed outcome shapes do not carry it.
A caller may omit it: the state move and the hint still resolve, and the exited pass then reads off the current state.

The hint is the constant for the exited state - the signalling state on a forward jump, never the pass the jump started from.
The trail entry records the signal, the outcome, and the state move.

### 14.6 Vocabulary

The state literals are:

```
grounding | slice | collect | discriminate | generate
| well_formedness | verify_claims | complete
```

The note names are:

```
phase:grounding | phase:slice | phase:collect | phase:discriminate | phase:well_formedness
```

The generate and verify-claims exits are store writes and need no note.

The spec status values are exactly `{hypothesised, ratified, dropped}`.
`verified` and `specified` are retired.
A spec's terminal status is `ratified`.
The declass of a verified-unfeasible spec is `dropped`.

The hunt-config lifecycle is retired with `HuntConfig`; the only live hunting status vocabulary is the hunter spec set's `{hypothesised, ratified, dropped}`.

### 14.7 Hints

One hint exists per transition gate.
The Q46a answer lists the six post-slice hints.
The grounding exit also needs a hint because the table has one hint per transition.
The seventh hint is an implementation choice recorded here; it does not change Q46a's six post-slice hints.
The table below completes the mapping.

| Exited state | Hint |
|---|---|
| `GROUNDING` | The grounding summary is persisted. Define the failure-mode slice the loop opens. |
| `SLICE` | Write the slice note, then collect the discrimination-axis instances. |
| `COLLECT` | Close the collection with the instances note, then discriminate. |
| `DISCRIMINATE` | Persist the discrimination outcome, then generate the spec set. |
| `GENERATE` | The specs are written as `hypothesised`. Run the well-formedness check over the slice; the check absorbs the class-exhaustiveness question in its new form. |
| `WELL-FORMEDNESS` | Well-formedness is confirmed. Record the drops and merges, then verify the claims. |
| `VERIFY-CLAIMS` | Promote the surviving specs, declass the unfeasible ones. |

The table shape is `TRANSITION_HINTS: dict[HunterPass, str]`.
The hint is selected by the exited state.
The hint is injected in the signal's tool response.
The hint is a constant, never the system prompt.

The grounding retrieval-gap rider is separate:

```
GROUNDING_KB_HINT
```

It is injected on a `kb_query` call while the state is `GROUNDING`.
It is not a transition.
Its text is re-worded for the new chain: the retrieval is folded in; a closed gap proceeds to SLICE; an open gap records the residual uncertainty and proceeds on weaker grounding.
`D3_HINT` is retired; the rider replaces it.

### 14.8 Phase-summary notes

The hunter's `notes` args `kind` gains `phase_summary`.
The enum is the hunter's note-kind string in the shared notes tool.
The hunt-store and pod note enums do not gain the kind.
The modeller's `notes` tool does not accept it.
The note name is `phase:<phase>`.
The note is written through the hunter's existing `notes` tool.
The note body states the pass's output and the decision rationale, within the conciseness cap.

On a loop re-iteration, the same note is rewritten with `action=update`.
The latest note wins.
The note is episodic memory, not authoritative state.
The spec store writes remain authoritative for the spec set.

The note is not a schema gate.
A missing note is not a tool rejection.
The harness advances only when the note is observed.

### 14.9 State channels and pure functions

The pure state module owns:

```
HunterPass = Literal[
  "grounding", "slice", "collect", "discriminate",
  "generate", "well_formedness", "verify_claims", "complete",
]

SpecStatus = Literal["hypothesised", "ratified", "dropped"]

SpecItem:
  spec_id: str
  status: SpecStatus
  fault_keyword: str
  strategy_keyword: str
  spec_ref: str
  verification_symptoms: list[str]
  summary: str

HuntState:
  state: HunterPass
  specs: list[SpecItem]
  injected_constant: str | None
  trail: Annotated[list[dict], operator.add]
```

The transient drive inputs are:

```
observed_signal: PhaseSignal | None
```

`PhaseSignal` is one of:

```
{kind: "phase_note", phase: HunterPass}
{kind: "spec_set_write", statuses: list[SpecStatus]}
{kind: "kb_query"}
```

The signal detector maps:

- A `phase_summary` note whose name is `phase:<phase>` to `{kind: "phase_note", phase}`.
- A `hunts_store` write carrying a `specs` list whose entries are all `hypothesised` to `{kind: "spec_set_write", statuses: ["hypothesised"]}`.
- A `hunts_store` write carrying a `specs` list whose entries are all `ratified` or `dropped` to `{kind: "spec_set_write", statuses}`.
- A `kb_query` call to `{kind: "kb_query"}`.

The `kb_query` signal produces `GROUNDING_KB_HINT` only in `GROUNDING`; it never advances the state.

The `specs` channel is last-write.
The trailer is append-only.
The old `phase` channel, the fault lists, `current_fault`, and the old status types are removed.

### 14.10 Graph topology

```
START -> supervise
supervise --signal pending--> detect
supervise --state complete--> END
detect --advance/forward_jump--> advance
detect --trail_only/none--> supervise
advance -> supervise
supervise --no signal--> supervise  (stay; the turn carries no signal)
```

`supervise` is the sole entry.
It routes to `detect` when a signal is pending.
`detect` is a pure function of the signal and the current state.
`advance` updates the state, injects the hint, records the trail, and consumes the signal.
Every push returns to `supervise`.
There is no fault push node and no per-fault list move.

The "no signal" stay carries no destination (`Command(goto=[])` in the implementation) rather than a self-route: a self-route is a superstep loop, and reaching END there would claim the chain is over.
END is therefore reached only on `complete`.
The router is the pure `route_supervise(state)`, so the contract is unit-testable.

The graph holds no model.
The graph is compiled in memory per hunt.
The ReAct engine runs outside the graph, as before.

### 14.11 Removal scope

The refactor removes:

- The four-value fault lifecycle and its detector and push functions.
- The four fault push nodes.
- The fault lists, `current_fault`, and the old phase channel.
- `derive_verdict` (already marked STALE).
- `SpecItem.experiment_ref`.
- The old hint constants `D2_HINT`, `COMMIT_SPECIFICATION_HINT`, `NEXT_FAULT_HINT`, `NEXT_ITERATION_HINT`, and `D3_HINT`.
- The dead verdict and pod-result residue the implementation enumerates.
- The old lifecycle assertions.

The pod dispatch path stays.
The tool surface stays, with `skill_list` and `skill_load` added.

**T5 (#378) disposition of this scope.**
Landed: the fault lifecycle, its detector and push functions, the four push nodes, the fault lists, `current_fault`, the old phase channel, `derive_verdict`, `SpecItem.experiment_ref`, and the five old hint constants are removed.
T6 (#379) landed the store side: the spec-set store writes the batched `specs` set under the loop dispatch key with the `{hypothesised, ratified, dropped}` vocabulary, and the mover's pod-dispatch gate is `ratified`.

### 14.12 Implementation decisions

- The machine tracks the eight-pass sequence.
- The exit signals are the matrix in 14.4.
- The phase-summary notes carry the five note exits.
- The store writes carry the two store exits.
- The hint table is keyed by the exited state.
- The grounding KB rider is separate.
- The signal acceptance is expected, forward jump, backward trail-only, or none.
- The state is monotonic.
- The specs channel is last-write.
- The trail is append-only.
- The graph is passive and compiled in memory.
- The old lifecycle is removed.

The implementation follows the patterns recorded in `src/polymerhus/attack/hunting/CONTEXT.md`: the passive state-graph hunter with detection and pushes, the pure state module, the injected phase-transition verbatims, and the hunter memory store.
The harness replicates the pattern and keeps the no-block invariant.

### 14.13 Testing decisions

Test the pure detector and the pure advance.
Drive the graph with injected signals.
Assert the state moves, the hints, the trail entries, the forward jump, the backward trail-only, and the loop discipline.

Seams:

- The signal detector: note, store write, KB query, absent signal.
- The acceptance rule: expected, forward, backward, none.
- The state advance: hint selection, trail entry, monotonic state.
- The note contract: `phase_summary`, `phase:<phase>`, update-on-re-iteration.
- The store contract: `hypothesised` set write, terminal `ratified`/`dropped` write.
- The graph: the active path, the terminal END, the no-block invariant.
- The removals: no fault push node, no `derive_verdict`, no `experiment_ref`, no old hint constant.

Prior art:

- The state-graph hunter tests.
- The hunter state purity tests.
- The notes and store contract tests.

### 14.14 Out of scope

- The hunter prompt prose (S3 and the prompt work phase).
- The pod contract (S5).
- The modeller and artifact (S1, S2).
- The verdict-consumption graph.
- The inner-loop state tracking; the machine stays in the looping pass.

### 14.15 Further notes

The workbench R8-2, Q44-Q47, and Q49-Q53 are the decision authority.
The proxy-signal matrix is the accuracy justification.
The note kind and name are the interposed persistence contract.
The hint table is the loop driver contract.
The prompt work phase finalises the hint wording.