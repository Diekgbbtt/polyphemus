# Memory system - reconciled design (grill output, round 1)

Branch `feat/hunting-memory-system-70`. This is the shared understanding record for `to-spec`.
Continuation of #110 with #70. See `STATE-memory.md` for ticket tracking.

## Decision record

- **Q1 - store substrate**: single per-project `notes.yaml` + `configs.yaml`, structured keys,
  with an in-memory index built from them. Project folder keyed by `project_id`, lazily created
  at first note. No per-pair files; no separate manifest to keep in sync.
- **Q2 - hunt-config persistence**: yes, configs accumulate persistently per project (direction-stamp
  memory).
  - Corrected: there is NO deterministic retrieval stage. The agent calls a tool to retrieve
    prior directions if necessary.
  - The prompt is edited with an embedding/list of ALL previous hunt-config KEYS (just a list
    with a brief introduction) so the agent can index seamlessly into previous relevant research
    directions. Afterward it may query their notes as well - this requires consistent indexing of
    hunt configs and their respective notes.
- **Q3 - note taxonomy**: closed enum of kinds.
  - `constraint` is MERGED into `hypothesis_refusal` (refusal reason + evidence + constraint).
  - Remaining kinds: `hypothesis_refusal`, `implicit_test_primitive`, `freeform`.
  - Structure is HIERARCHICAL: key `unit_id:fault_class:...`.
  - Notes are keyed by a NAME that encodes the kind as an initial namespace, CHAINED with
    additional concrete details depending on the kind (e.g. a concrete missing adversarial
    capability, or a defence, or the testing primitive).
- **Q4 - note-step capture**: either or both of carried / refused directions; the MODEL decides.
  No completeness check.
- **Q5 - write semantics**: append monotonically, read-latest.
- **Q6 - read seam**: GREP-match, logic strictly inside the tool. The retrieve contract offers:
  - parent index `(unit_id, fault_class)`,
  - a keyword for the note KEYS,
  - a keyword for the note BODY;
  combinable or singular. The tool description given to the agent MUST specify the note kinds.
- **Q7 - overlap signal**: no explicit overlap decision. Phase-1 only surfaces prior configs/notes
  into the prompt (the Q2 key-list + tool read). No LLM overlap-decision call.
- **Q8 - scope/wiring**: no deferral - wire the memory write LIVE in `start_hunting`.

## Test seams (confirmed with operator)

- **Seam 1 - the store handle (`tools.store_reads`)**: the per-project memory store slots in as a
  handle on the same object the orchestrator already receives, keeping the per-run trail
  `append`/`list_records` and adding per-project `configs` + `notes` write/read.
  - Unit tier: pure filesystem, `tmp_path`, mirroring `tests/attack/test_hunt_store.py`.
  - Integration tier: `tests/integration/test_hunt_orchestrator_contracts.py`.
- **Seam 2 - the deterministic note-taking node**: a new graph node injected into
  `build_hunting_graph(..., note_node=...)`, parallel to `reason_node`/`budget_node`/`dispatch_node`;
  default (absent) node fails open (writes nothing). Tested at integration tier with fakes.
- **Seam 3 - gate-prompt key-list + tool-detection**: assert the hunt-orchestrator gate prompt
  carries the headers/keys of previous hunt configs, AND measure the orchestrator's capability to
  detect WHEN it must call the store + note-reading tool. (Operator addition.)
- **Seam 4 - LIVE e2e walkthrough**: memory is verified against the runtime stack (control plane,
  DB, runtime manager live), emulating runtime conditions as closely as possible, over a bounded
  and limited project (a small candidate set / fixture project). NOT a mocked unit call.

## Remaining steps

- Author the memory-system spec (`to-spec`) and publish to the tracker with `ready-for-agent`.
- Run `to-tickets`, `to-assertions`, then implement + wire live + code-review.
