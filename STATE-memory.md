# Memory system workstream - ticket tracking

Continuation of #110 with #70: the hunt-orchestrator memory system rewrite.
Branch `feat/hunting-memory-system-70` (forked from `f3c4dbb`, the #135 head).

## Tickets this workstream touches

| # | Title | State | Role / disposition |
|---|---|---|---|
| 70 | Hunting Phase-2 spec: memory system (orchestrator memory) | OPEN | PRIMARY - the spec this workstream realises; CLOSE at end |
| 68 | Hunting Phase-2 spec: module domain model + persistence (hunt store) | OPEN | PRIMARY - the store rewrite the memory system rides; CLOSE at end |
| 85 | Research on unified memory layer with native indexing (mem0) | OPEN (wayfinder:research) | ABSORB - the per-project indexed note store supersedes a raw mem0 adoption; close with a synopsis or mark superseded |
| 60 | Q5 - Hunt state, identity, and hunt-orchestrator memory | CLOSED | authority - the revival-key / fault-evidence / note intent this realises |
| 64 | full impl of back-edge (yellow -> targeted-recon) | OPEN | ADJACENT - the back-edge is a feedback input to memory; the note-taking step may depend on its seam |
| 110 | stateful per-fault-unit orchestration + app-runtime seam wiring | OPEN | ADJACENT - memory writes live-fire only once dispatch_fn is wired (this workstream may trigger/coordinate) |
| 69 | control plane (orchestration/dispatch graph) | OPEN | ADJACENT - the StateGraph the deterministic note-taking step is encoded into |

## Spec + tickets published (to-spec + to-tickets)

- `#137` - Memory system spec (ready-for-agent). Parent for the six tickets.
- `#138` - Memory store: per-project indexed hunt-config + note store handle (Blocked by: none).
- `#139` - Memory: deterministic note-taking StateGraph node (Blocked by: 138).
- `#140` - Memory: refactor orchestrator memory reading into a note + hunt-config reading tool (Blocked by: 138).
- `#141` - Memory: embed previous hunt-config key-list in the orchestrator gate prompt (Blocked by: 138, 140).
- `#142` - Memory: wire per-project hunt-config + note memory live in start_hunting (Blocked by: 139, 141, 140).
- `#143` - Memory: live e2e on a bounded project + orchestrator memory-tool-detection measurement (Blocked by: 142).

Sub-issue dependency edges 404 (not enabled on this repo); blocking is recorded textually as `Blocked by:` in each body.
Reconciled design record: `RECONCILED-DESIGN-memory.md`.
Assertion catalogue: `ASSERTIONS-memory.md` (C1-C12, E1-E3).

## Implementation status (all six tickets implemented + reviewed)

- #138 store: `ProjectMemoryStore` + `HuntStore.project_memory` property (hunt_store.py). Unit C1-C7.
- #139 note node: `_NOTE` static-edge graph node, `_make_note`, `note_fn` seam, `NoteOut` (orchestrator_graph.py / hunt_orchestrator.py). Integration C8/C9.
- #140 reading tool: `OrchestratorTools.read_memory_notes` -> `ProjectMemoryStore.read_memories` (grep-match, logic contained), TOOL_SURFACE extended, `read_memory` compatible. Integration C10/C11.
- #141 key-list: `GateInput.prior_config_keys`, `_reason_node` fills it from `store.project_memory.config_keys`, `_compose_gate_prompt` embeds it. Integration C12.
- #142 wiring+docs: config accumulates per project on dispatch live; note node live-reached (body seams as injectable); CONTEXT.md + hunting-67 spec updated non-contradictory.
- #143 live e2e: E17/E18/E19 in test_hunt_orchestrator_isolated_e2e.py against real graph+store (Seam 3 + 4).
- Code review (subagent) found + fixed: dead TOOL_SURFACE assert, corrupt-file clobber (now raises O4), `::`/`:` parent-delimiter asymmetry (normalised), misleading seq docstring, CONTEXT honesty re: note body seam. Regression tests added.
- Verified: tests/attack 199->221, integration contracts, e2e isolated 18, blocked walkthroughs skipped.

## Close policy

At the end of the workstream, close #70 and #68 (their specs are realised by this branch's implementation and docs).
#85 is closed as superseded/absorbed. #64/#110/#69 are out of this branch unless the memory work genuinely completes them - they get status comments noting the dependency, not a close.
