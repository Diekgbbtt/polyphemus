# Assertions - hunting-agent state-graph hunter (#164)

**Source:** `docs/design/hunting-164-state-graph-spec.md` (sections 2-6, 11) and
`docs/design/hunting-164-state-graph-adr.md` (R4, GP4, GP6, GP8c, G1-G9).
**Seams under assertion:** the per-project `HunterMemoryStore` store seam
(`hunter_memory.py`); the `hunts_store` / `notes` tool seams over it
(`hunter_tools.py`); the turn-by-turn ReAct host binding
(`build_hunting_agent(project_id=, memory_store=)`, `hunting_agent.py`) and the
compiled state graph it drives (`hunter_graph.py`).

Scope note (operator, 2026-08-24): the whole-hunter e2e verification (walking
the workflow graph with the real LLM, the symbolic-layer materialisation, the
full test-implementation-spec lifecycle) runs AFTER the hunting pipeline
wiring + REST-capability workstream lands - that work exposes single hunting
components and hunter/pod sessions at the app REST interface, so the hunter can
be started per project and consume already-created `HuntConfig`s from the
orchestrator. The memory system is scoped NOW: its contract predicates and
walkthroughs are executable this branch. The whole-hunter walkthroughs below
are designed and accounted as validated, but blocked on that workstream.

## Contract predicates (integration) - memory, executable now

### The `HunterMemoryStore` seam

- **C1 - produced topology + lazy project dir.** Given `project_id="proj-a"`,
  `fault_key="Service:slug:a|fault-x"`, `fault_keyword="csrf"`,
  `strategy_keyword="probe"`, a `create` write of a `hypothesised` fault, at the
  store seam -> the file exists at exactly
  `<root>/proj-a/test-specs/Service:slug:a|fault-x/produced/csrf_probe.yaml`;
  the project dir is created only at the first write (a store read before any
  write returns `[]` and creates no tree).
- **C2 - identifier stability (round-trip by identity).** A `read_spec` on the
  SAME `(project_id, fault_key, fault_keyword, strategy_keyword, side)` returns
  the persisted spec dict unchanged; the read is a function of the identity,
  never of a sequence number.
- **C3 - keyword sanitisation (G3).** A `fault_keyword="fault/x:csrf"` and
  `strategy_keyword="probe_1"` write -> the file is
  `fault-x-csrf_probe-1.yaml` (each `_`/`:`/`/` replaced with `-`); a keyword
  that sanitises to an empty/dot component (e.g. `".."`) raises `ValueError`.
- **C4 - the status lifecycle rides ONE produced file.** A `hypothesised`
  create write, then `verified` and `specified` update writes on the same
  `(fault_keyword, strategy_keyword)` -> EXACTLY ONE `csrf_probe.yaml` whose
  content is the final `specified` spec (the persisted environment state IS the
  fault-processing tracker, G4).
- **C5 - duplicate novelty gate (G4).** A second `create` write to the same
  produced file raises `DuplicateSpecError` and leaves the original file
  unchanged; a different `strategy_keyword` or the `consumed` side is a fresh
  file, never a collision.
- **C6 - re-author update in place (G5).** An `update` write overwrites the
  existing file in place - exactly one file, never an append-record, no
  `_seq`/`_ref` bookkeeping on the spec records.
- **C7 - read_spec empty-valid + projection.** `read_spec` on a missing file
  returns `None` (a valid empty result, never a failure); with `attributes`
  the returned dict holds exactly those fields.
- **C8 - read_specs listing + filters.** `read_specs(fault_key)` returns all
  produced+consumed spec files in file-name order; `sides=("consumed",)`
  selects one side; `statuses` filters; a missing project/fault_key yields
  `[]`.
- **C9 - side addressing + no movement (G7).** A write to `side="consumed"`
  lands under `test-specs/<fault_key>/consumed/`; both sides are addressable;
  nothing in the store moves a file between sides (the produced->consumed
  movement is the out-of-scope surfer's); an unknown side raises `ValueError`.
- **C10 - validation.** `project_id`/`fault_key` reject a path separator, a
  control char, or dot-traversal (`".."`); `write_spec` rejects a spec whose
  `status` is outside `FAULT_STATUSES`; an unknown write mode and an unknown
  note kind/action raise `ValueError`.
- **C11 - corrupt file fails loud (O4).** A hand-corrupted produced spec file
  -> `read_spec`/`read_specs` raise `OSError` (never return `[]`); a corrupted
  `notes.yaml` -> `read_notes` raises. Never a silent corruption.
- **C12 - notes append (G6).** A `write_note(append)` adds a note with key
  `fault_key:<note_name>`, `fault_key`, `note_name`, `kind`, `body`,
  `evidence`, `provenance`; returns the key; appends keep their natural order.
- **C13 - notes update/delete + denoted miss.** `update` amends the existing
  note in place (same key, no duplicate record); `delete` removes it;
  update/delete on a missing key returns `None` (a denoted miss, never a
  failure).
- **C14 - notes read (grep-match, read-latest).** `read_notes` by `parent_key`
  (the fault_key) returns that fault's notes; `key_keyword`/`body_keyword` are
  case-insensitive substrings; filters combine; zero matches returns `[]`.
- **C15 - fault/note identifier equality.** For one `fault_key` with a produced
  spec and an appended note, `read_specs(fault_key)` and
  `read_notes(parent_key=fault_key)` both resolve by the SAME config identifier
  - the note's `fault_key` field and `key` prefix equal the spec's folder key
  (all pipeline stages are walked by one key).

### The `hunts_store` / `notes` tool seams

- **C16 - hunts_store write create.** The tool over a real store + project_id,
  `command=write`, `mode=create`, status `hypothesised` -> JSON
  `{"ok": true, "path": <abs path>, "status": "hypothesised"}`; the file exists
  on disk.
- **C17 - duplicate_spec denoted signal (G4).** A duplicate `create` through
  the tool -> `{"ok": false, "error": "duplicate_spec", ...}` - the model-facing
  dedup signal, never a raise into the turn.
- **C18 - invalid args.** A `write` missing `fault_keyword`/`strategy_keyword`
  or a spec without a lifecycle `status` -> `{"ok": false, "error":
  "invalid_args", ...}`; a `read` without `fault_key` ->
  `{"specs": [], "error": "invalid_args", ...}`.
- **C19 - tool read filters produce projection.** A `read` by `fault_key` with
  `statuses`/`attributes` returns exactly the projected produced specs.
- **C20 - notes tool denoted miss.** A `notes` update/delete on a missing key
  -> `{"ok": false, "error": "note_missing", ...}`.
- **C21 - absent-store fail-open.** `hunts_store`/`notes` with an absent store
  -> `{"...": "store_unavailable", "degraded": true}`, never a raise.
- **C22 - read failure degrades (O4).** A store whose produced spec is corrupt
  -> the tool returns `{"specs": [], "error": "read_failed", ...}` (degrades to
  an empty set, never raises into the turn).

## Walkthrough predicates (end-to-end)

### Memory walkthroughs - executable now

The **live edge** is the LLM session, declared per walkthrough as
`model service, mode=scripted` - a scripted model emits `HunterStep` tool calls
(the real-LLM mode is E5-E8, below). Every component the spec owns is real: the
harness, the five-tool surface, the compiled graph, and the per-project store on
the filesystem.

- **E1 - the full lifecycle over the real store.** Grounds: G4 (the persisted
  environment state IS the fault-processing tracker), spec 2.3, spec 6. Entry
  seam: `dispatch_fn(HuntConfig)`. Input: a `HuntConfig` for
  `(Service:slug:a, fault-x)`; the scripted model writes fault F1
  hypothesised -> verified -> specified, fault F2 hypothesised -> dropped, then
  answers. Path: harness -> `hunts_store` writes -> `HunterMemoryStore` -> the
  graph pushes on each status verbatim -> the files evolve in place. Terminal:
  EXACTLY TWO produced files `f1_probe.yaml` (status `specified`, `spec_id`
  `S1`) and `f2_probe.yaml` (status `dropped`) under
  `proj-a/test-specs/Service:slug:a|fault-x/produced/`; `hypothesis_verdict is
  None`; feedback carries the terminal state `phase: concluded`, `- ratified:
  S1`, `- dropped: F2`, and no `- hypothesised: F1`. Observed: the files read
  back via `read_spec`; the state summary read back from the feedback.
- **E2 - fault and note share the identifier over the real pipeline.** Grounds:
  G6 (notes on the same data contract), G1/G2 (per-project topology). Entry
  seam: `dispatch_fn`. Input: a `HuntConfig`; the scripted model hypothesises
  fault F1 for `fault_key` AND appends a note for the same `fault_key`. Path:
  harness -> `hunts_store` write + `notes` write -> both bodies under
  `proj-a/`. Terminal: the produced spec file exists under
  `test-specs/<fault_key>/produced/f1_probe.yaml` AND `notes.yaml` holds the
  note with `fault_key == <fault_key>` and `key == "<fault_key>:decision"`;
  `read_specs(<fault_key>)` and `read_notes(parent_key=<fault_key>)` both
  resolve - one identifier walks both bodies. Observed: the two YAML files
  read back.
- **E3 - all memory integration capabilities in one hunt.** Grounds: spec 5
  (the tool surface), G4-G6 (write modes, duplicate gate, notes options).
  Entry seam: `dispatch_fn`. Input: a `HuntConfig`; the scripted model
  exercises every memory capability - `hunts_store` write create/update,
  `hunts_store` read (with statuses+attributes), `notes` write append/update/
  delete, `notes` read (by parent key) - then answers. Path: harness ->
  both tools -> the store. Terminal: the produced side holds EXACTLY ONE
  surviving spec file (status `specified`); `notes.yaml` holds exactly the
  surviving note in append order (the deleted note absent); the tool responses
  the model saw carried the JSON contracts (create `ok:true`, read the filtered
  projection, delete `ok:true`). Observed: the files read back + the recorded
  tool responses.
- **E4 - the phase hints ride the tool responses verbatim and the graph tracks
  the loop.** Grounds: G9 (the phase-transition constants), spec 2.3, R4/GP8c
  (detection + push, never stale). Entry seam: `dispatch_fn`. Input: a
  `HuntConfig`; the scripted model does a grounding-phase `kb_query`, then F1
  hypothesised -> verified -> specified, F2 hypothesised -> dropped, then
  answers. Path: harness -> tool responses (each hint injected in the SAME
  response as its status write, consumed before the next turn) -> graph pushes.
  Terminal: the D3_HINT rides the kb_query response, D2_HINT the hypothesise
  responses, COMMIT_SPECIFICATION_HINT the verify response, NEXT_ITERATION_HINT
  the specify response, NEXT_FAULT_HINT the drop response - each verbatim inside
  `<phase-transition-hint>`; no hint leaks onto a later unrelated response; the
  terminal feedback shows the graph NOT stale - `- ratified: S1` and
  `- hypothesised: F2` together, `- verified: F1` absent; the files carry the
  lifecycle terminal statuses. Observed: the recorded tool responses + the
  files + the feedback.

### Whole-hunter walkthroughs - blocked on the REST-capability workstream

The **live edge** is `model service, mode=real` and the entry seam is the
REST capability: start the hunter per project and consume already-created
`HuntConfig`s from the orchestrator. Designed and accounted as validated;
mechanised when that workstream lands.

- **E5 - the full LLM graph-walk.** Grounds: spec 2.1 (state tracking not
  navigation), spec 2.3 (the phases), R4 (the turn-by-turn driver). Entry seam:
  the REST per-project hunter start + the orchestrator's hunt-config intake.
  Input: a real project + its hunt configs. Path: the model walks the whole
  workflow graph - grounds, hypothesises each candidate, verifies/ratifies or
  drops per the injected hints, iterates, concludes. Terminal: every candidate
  reaches a terminal lifecycle status; the reasoning traces in the session/
  observability logs explicitly execute the encoded steps per phase; the
  injected hints are interpreted verbatim and the model moves on to the
  suggested phase; the graph state tracks the ReAct loop and is never left
  stale (a ratified fault is never still `hypothesised`). Observed: the
  session logs, the produced spec files, and the graph summary.
- **E6 - the unit-pair loop is fully executed.** Grounds: spec 2.1, the
  orchestrator intake. Entry seam: the REST capability. Input: the full set of
  already-created hunt configs for the project. Path: each config is dispatched
  and run to conclusion. Terminal: EVERY dispatched unit-pair is covered -
  exact count, no pair skipped, no pair double-run. Observed: the produced
  spec files keyed per config, one terminal lifecycle status each.
- **E7 - the symbolic layer materialises all projected units and faults.** 
  Grounds: spec 3 (the channels), spec 2.3 (the injected constants). Entry
  seam: the first-step composition. Input: a `HuntConfig` whose surface context
  projects a set of units and faults. Path: `_compose_first_step` renders the
  five-part parameter set, the tool surface, and the state summary; each
  phase-transition constant rides the tool response it belongs to. Terminal:
  every projected unit and fault appears verbatim in the materialised prompt;
  every injected hint appears verbatim in its response. Observed: the composed
  prompt text + the recorded tool responses.
- **E8 - the TestImplementationSpec lifecycle and attribute quality.** Grounds:
  spec 6 (the spec body), G4 (the lifecycle). Entry seam: the REST capability.
  Input: a full-depth hunt. Path: each ratified candidate's spec file moves
  hypothesised -> verified -> specified (or dropped with the reason) on ONE
  produced file. Terminal: the produced spec files carry the complete attribute
  set (target_identity, verification_symptoms, testing_pattern, assumptions,
  payload_vector_space, rationale, interpretation_guidance, spec_id) with
  values adequate to the specification depth, and each file carries the
  lifecycle status it ended on. Observed: the produced YAML files read back.