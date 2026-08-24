# Hunting spec: test-executor pod memory system (per-project experiment logs + notes)

*Status: spec (contract), NOT implementation.* The build specification for the pod memory-system adaptation of
ticket [#84](https://github.com/Diekgbbtt/polyphemus/issues/84). Synthesised 2026-08-23 from the grilling recorded in
`docs/design/hunting-84-regrounding-decisions.md` (D84-33 through D84-38 VERDICTED 2026-08-23, plus the two
operator corrections in this grilling round) and the memory-system pattern document
`docs/design/hunting-memory-system-spec.md`. The adaptation trades the pod's content-addressed in-memory
`ExperimentLog` plus `_seq`/`_ref` notes model for the per-project deterministic-key pattern, keeping the pod's
memorization kernel (the note store semantics + the note tool) as-is.

Lineage: the pod spec is `docs/design/hunting-67-test-executor-pod-spec.md`; the underlying decisions are
`docs/design/hunting-84-regrounding-decisions.md`. The spec identifier is minted by the #164 hunter
(`docs/design/hunting-164-state-graph-spec.md`, in the `hunting-164-state-graph` worktree).

## Problem Statement

The pod's experiment memory today is not a designed system. Two problems:

1. **The experiment log is in-memory only.** The `ExperimentLog` (`pod/context.py`) is a run-scoped Python object
   held in the graph state (`PodState.log`). It is the ONLY record of what the pod did (the D6 trail:
   `variant_specs`, `raw_observations`, `interpretations`) and what it deduplicated (`executed`). It dies with the
   process. There is no persistence, no per-project scoping, no cross-run continuity, and no way to enumerate which
   variants of a spec were tried after the fact.
2. **The identity and ordering model is wrong for a persistent store.** Persistent notes
   (`pod/pod_memory.py::PodMemoryStore`) are keyed by `canonical_spec_id` - a content-addressed sha256 of the whole
   spec JSON - and records carry `_seq`/`_ref` bookkeeping. A content hash is an execution-instance identity, not a
   TestImplementationSpec identity: it re-mints on every re-wording of the spec's NL fields, and it encodes no
   order, so the "following variant" of a spec is not discoverable. `_seq`/`_ref` force an opaque counter to
   disambiguate records that already have a deterministic key address.

The orchestrator's memory-system pattern (`hunting-memory-system-spec.md`) is the operator-locked template: a
per-project store with semantic deterministic identities, one record per file, no `_seq`/`_ref`, and attribute
addressability in the reading tool. The pod's memory must be projected onto that pattern. Two further operator
directives shape the adaptation's invariants:

- **The experiment log is a pure log.** The LLM has no capability to write it. There is no `experiment_log` tool.
  All writes happen in deterministic stages of the graph (init, mint_variant, the triager's interpretation record)
  and inside tool internals (the exec tool's `_record`). Writing logic is held in the symbolic/deterministic layer,
  never expressed by the model.
- **All logs write in deterministic stages, and that must include `kb_retrieve` responses.** Today only exec
  results are recorded. A `kb_retrieve` response (the symptom/technique/source bundle that drove the Runner's
  concretization) does not enter the log, so the trail does not capture which KB knowledge led to which probe.
  Extending the log domain model with the KB-retrieve response is a NEW work item of this spec.

## Solution

A **per-project, deterministic-key memory store** for the test-executor pod, under the hunting module's data seam,
composed of two bodies:

```
data/<project_id>/test-executor-pod/
  <fault>_<strategy>/
    variants/<variant-ref>.yaml           (the minted TestImplementationSpec variants)
    experiment-log/<order>.yaml           (one file per variant, the D6 slice + summary)
    <run_id>.yaml                         (T7/#183: the pod's OWN terminal PodExport)
  notes.yaml                              (per-project note store)
```

- **Experiment logs persist entirely** (`D84-38`): one YAML file per variant holds that variant's `raw_observations`, `interpretations`, the `executed` dedup ledger for that stretch, AND the `experiment_summary`
  terminal record (`D84-35`). The minted TestImplementationSpec variant persists to `variants/<ref>.yaml`. The file is overwritten idempotently on a re-run (`D84-37`, the deterministic path is
  the address).
- **Identity** (`D84-34`): the spec identifier is the #164 hunter's `SpecItem.spec_id = "<fault>_<strategy>"`; the
  order number is the variant ordinal. The variant ref `vN` and the order `N` are the SAME ordinal in two spellings
  (operator, 2026-08-24): `variants/v0.yaml` <-> `experiment-log/0.yaml`. Following variants are the next ordinal file. The old content-addressed full-instance hash is rejected as the identity axis.
- **Notes** (`D84-33`): the per-project `notes.yaml` keep the pod's memorization kernel (closed kinds
  `experiment_summary`/`kb_insight`/`freeform`, grep-match read, read-latest, fail-open degradation). Notes are
  keyed `<fault>_<strategy>:<order>:<note_name>` (`D84-36`). `kb_insight`/`freeform` accumulate in `notes.yaml`;
  the `experiment_summary` sinks into the variant's experiment-log file as its terminal record.
- **No `_seq`/`_ref`** (`D84-36`): records are addressed by the deterministic key pattern plus typed attribute
  filters in the reading tool. Ordering within a file is the natural list order; reads are latest-first by list
  position.
- **Pure-log invariant**: the reading tool is the model's only memory seam. The run's in-memory `ExperimentLog`
  keeps supplying the deterministic write stages and the prompt context slices, but its persistence is delegated to
  the store at the deterministic boundary - the `ExperimentLog` records each mutation THROUGH the store (the
  symbolic-layer capture middleware, operator, 2026-08-24).
- **KB-retrieve recording** (implemented T3/#179): `KbRetrieveTool` has a log-recording step (a deterministic
  `_record` like the exec tool's), so every KB response enters the variant's experiment-log file with the query,
  the fault/axis context, and the returned symptoms/techniques/source.
- **Prompt materialization** (`D84-27` reconciled): the prompts embed an indexable, readable key-list covering BOTH
  the notes (by key) AND the experiment-log identifiers (spec id + orders present on file), plus the reading
  guidance - so the Runner/Triager can address any persisted artifact by a deterministic identifier.
- **`project_id` axis**: the store build is parameterised by `project_id` from the parent's hunting module context
  (verified correct by the operator). Session THREAD ids stay hash-based (`D84-2`) and become an independent
  namespace from memory keys.

## User Stories

1. As the test-executor pod, I want my experiment log to persist per project, so that the full D6 trail of a spec
   execution survives the run and the process.
2. As the test-executor pod, I want each variant's experiment log in its own file
   (`<fault>_<strategy>/experiment-log/<order>.yaml`), so that following variants are enumerable from the
   directory listing.
3. As the test-executor pod, I want the spec identifier to be `<fault>_<strategy>` (the #164 hunter's spec id),
   so that the pod store and the hunter's test-spec store link by the SAME identifier with no hash drift.
4. As the test-executor pod, I want the order number (0, 1, 2, ...) to be the variant's ordinal, so that the
   sequence of variants of one spec is immediately visible.
5. As the test-executor pod, I want a re-run of the same (spec, order) to overwrite the variant file idempotently,
   so that the persisted log is the current truth, not an unbounded accumulation.
6. As the test-executor pod, I want the `experiment_summary` to be the terminal record of the variant's log file,
   so that the Triager reads the consolidation and the raw D6 slice from one artifact.
7. As the test-executor pod, I want notes keyed `<fault>_<strategy>:<order>:<note_name>` stored in a per-project
   `notes.yaml`, so that kb insights and freeform notes accumulate read-latest without `_seq`/`_ref` bookkeeping.
8. As the test-executor pod, I want no `_seq`/`_ref` on any record, so that the deterministic key plus the natural
   list order disambiguate every artifact.
9. As the test-executor pod, I want the reading tool to accept typed attribute filters (`order`, `kind`,
   `classification`, `symptom_status`) on top of the substring filters, so that I can address an artifact without a
   counter.
10. As the test-executor pod, I want the experiment log to be a PURE log, with no tool capability for the LLM to
    write it, so that the D6 trail is a faithful record of deterministic write stages only.
11. As the test-executor pod, I want `kb_retrieve` responses recorded into the experiment log deterministically in
    the tool internals, so that the trail captures which KB knowledge informed each probe's concretization.
12. As the test-executor pod, I want all other deterministic write stages (init variant, minted variant, the
    triager's interpretation record, the exec observation) to persist into the variant file, so that nothing the
    graph records in-memory is lost.
13. As the Runner, I want the per-turn prompt to render an indexable key-list of the notes AND the experiment-log
    identifiers on file, so that I can read any persisted artifact by a deterministic identifier instead of guessing.
14. As the Triager, I want to read the variant's persisted experiment-log file (summary + D6 slice) through the
    reading tool, so that my verdict is grounded in the persisted trail, not the ephemeral in-memory object.
15. As the parent HuntingAgent, I want the pod store keyed by the same spec id I minted
    (`<fault>_<strategy>`), so that I can correlate the pod's persisted experiment logs with my test-spec files
    without a translation table.
16. As the operator, I want the memory store per-project so that hunting in one project never leaks experiment logs
    or notes into another.
17. As the operator, I want the migration to preserve the pod's existing fail-open canon: a read failure degrades
    to an empty set (O4), a write failure raises to the caller which warns and keeps serving (O3), and a `None`
    store fails open in the note tool (O10).
18. As a maintainer, I want the ExperimentLog's runtime-only state (budget counters, iteration, working set) to stay
    in the `PodState` graph channels, so that persistence is scoped to the durable D6 content and dedup ledger.
19. As the test-executor pod, I want to persist my OWN terminal `PodExport` envelope (`{verdict, evidence}`) to
    `<spec_id>/<run_id>.yaml`, written by the deterministic terminal node, so that my result is seamlessly mappable
    to the originating TestImplementationSpec and the hunting hunter-agent session that created it (T7/#183).

## Implementation Decisions

### 1. Store topology (D84-33, VERDICTED; layout re-scoped 2026-08-24)

- The pod memory store moves to `data/<project_id>/test-executor-pod/` - ONE root per project under the hunting
  module's data seam (`src/polymerhus/attack/hunting/data/`), sibling to the #164 hunter's
  `data/<project_id>/hunting/` tree.
- Three bodies, coherent per-spec layout (operator, 2026-08-24): the minted TestImplementationSpec variants in
  `<spec_id>/variants/<variant-ref>.yaml`, the per-order experiment-log slice in
  `<spec_id>/experiment-log/<order>.yaml`, and the per-project `notes.yaml`. The variant ref `vN` and the order `N`
  are the SAME ordinal in two spellings - easily mappable.
- No `produced`/`consumed` directories (the pod has no dispatch lifecycle; the experiment log is never consumed).
- No per-run kind files.
- The store build is parameterised by `project_id`, resolved from the parent's hunting module context; direct
  invocation (tests/hermetic) supplies it explicitly.
- `POD_MEMORY_ROOT` fixed-path constant is retired; the per-project root replaces it.

### 2. Identity: `<fault>_<strategy>` + order number (D84-34, VERDICTED)

- Spec identifier: the #164 hunter's `SpecItem.spec_id = "<fault>_<strategy>"` ("encodes the concrete fault
  semantic + testing strategy keywords"). The `_` separator + keyword-sanitisation ruling from the memory pattern
  applies (`:` and `-` are poisoned separators - unit/fault ids may contain them; keywords are sanitised).
- Order number: the variant ordinal, so the file name IS the order. Combined address:
  `<fault>_<strategy>/experiment-log/<order>.yaml` with `<order> = 0, 1, 2, ...`.
- The `spec_id` crosses the typed handoff from the #164 hunter to the pod (the hunter mints it). The #164 spec
  explicitly reserves a DIFFERENT store for experiment logs, linked via the spec id (hunter spec lines 194-195) -
  this pod store IS that store.
- The content-addressed full-instance hash is REJECTED as the identity axis. `canonical_spec_hash` may remain for
  session-thread disambiguation ONLY (`D84-2` thread ids), never for memory keying.
- Session THREAD ids stay hash-based and become an independent namespace from memory keys. `project_id` is the
  store's scoping axis; the run/hunt/spec-hash is the session's identity axis.

### 3. Cardinality: per-variant log file owns the D6 slice + summary (D84-35, VERDICTED)

- One file per variant holds that variant's experiment-log slice: `raw_observations` +
  `interpretations` + the `executed` dedup ledger + the `experiment_summary` terminal record. The minted
  TestImplementationSpec variant persists to `variants/<variant-ref>.yaml`.
- `experiment_summary` is promoted to the TERMINAL RECORD of the variant's experiment-log file. The Runner's P3
  consolidated summary (written via the `note` tool) lands IN `experiment-log/<spec_id>/<order>.yaml`, not in
  `notes.yaml`. The summary's value IS the note body string (operator, 2026-08-24).
- `kb_insight` / `freeform` remain notes in `notes.yaml`, keyed `spec_id:<order>:<note_name>`.
- The Triager reads the variant's experiment-log file (the terminal summary + the D6 slice) instead of a separate
  summary note.

### 4. Attribute addressability and the removal of `_seq`/`_ref` (D84-36, VERDICTED)

- Notes keyed `<fault>_<strategy>:<order>:<note_name>` (adapting the old `notation_key` to the new identity).
- The reading tool gains typed attribute filters: `order` (the variant ordinal), `kind`, `classification`,
  `symptom_status` become first-class read filters, retaining `parent_key` / `key_keyword` / `body_keyword`
  substring match.
- No `_seq`/`_ref` on any record (`D84-32`'s canonical field set drops both). Ordering within a file is the natural
  list order; reads are latest-first by list position.
- Update/replace semantics displace counters: a re-run of the same (spec, order) REWRITES the experiment-log file
  idempotently; a notes write appends a newer record under the same deterministic key and read resolves the latest.

### 5. Update/overwrite semantics (D84-37, VERDICTED)

- The per-variant experiment-log file is overwritten idempotently on a re-run - one file per variant, the
  deterministic path is the address.
- The notes file is append-only with read-latest.
- No `update`/`delete` cmds on the pod's `note` tool (the memory-spec's append/update/delete write options are the
  orchestrator's, not the pod's).

### 6. Migration scope: ALL of ExperimentLog persists (D84-38, VERDICTED)

- The in-memory `ExperimentLog` migrates ENTIRELY: `variant_specs` (to `variants/<ref>.yaml`), `raw_observations`,
  `interpretations` (the full D6 export) AND the `executed` dedup ledger persist to the per-variant files.
- Runtime-only state (budget counters `HUNT_POD_MAX_TOOL_CALLS`, iterations, the current lap's working set) stays in
  the `PodState` graph channels.
- Persisting `executed` widens O7 dedup from within-run to within-`(project, spec, order)` (cross-run dedup becomes
  possible).
- The `executed` ledger is persisted in FULL in each variant file (operator, 2026-08-24): the opaque signatures
  cannot be split per variant, so every slice write carries the full accumulated list; overwrite-on-re-run makes it
  the current truth.

### 7. The pure-log invariant (operator directive)

- The LLM is granted NO toolcapability to write the experiment log. The tool surface stays
  `exec` / `kb_retrieve` / `note`; none writes the log directly.
- All log writes remain in deterministic stages:
  - `init` records the v0 variant (`graph.py`).
  - `mint_variant` records the derived variant.
  - The triager node records the interpretation (`record_interpretation` at the graph node boundary).
  - The exec tool's `_record` records the raw observation + marks executed (tool internals).
  - The harness middleware owns the cap / dedup / empty-command gates (G1 / O7 / G2).
- The model's JUDGMENT enters only as CONTENT through these mechanical stages (the triager's classification/note,
  the runner's command), never as an LLM-initiated log write.

### 8. KB-retrieve response recording (implemented T3/#179)

- `KbRetrieveTool` has a deterministic `_record` step mirroring the exec tool's: every KB response (query,
  fault/axis context, returned symptoms / techniques / source bundle) is appended to the variant's experiment-log
  file as a KB observation (`KbObservation`).
- The log domain model is extended so a KB observation is a first-class record (`types.py::KbObservation`,
  distinct from an exec's `RawObservation`), rendered into the experiment-log file via the `ExperimentLog`'s
  capture middleware (`record_kb_observation`, the SAME seam as `record_observation`) and preserved by the
  migration.
- Degradation is unchanged: an empty/raising KB result is recorded as the empty bundle (fail-open, O13); the
  recording itself never raises into the turn. A logless tool (the triager's context-read seam when no harness is
  bound) records nothing.
- The tool surface is unchanged (`exec` / `kb_retrieve` / `note`): the recording is a deterministic stage inside
  the tool internals, never an LLM-initiated log write (the pure-log invariant holds). This is a separate work
  item integrated into this spec's ticket (T3 in the ticket split, #179), not a modification of the memorization
  kernel.

### 9. Prompt materialization of logs and notes identifiers (D84-27 reconciled)

- The per-turn memory header (`compose_memory_guidance`) is extended to render an indexable key-list covering BOTH
  the notes (by key) AND the persisted experiment-log identifiers (spec id + the orders present on file).
- The persistent reading-guidance block (`MEMORY_READ_GUIDANCE`) documents both bodies and the typed attribute
  filters, so the Runner/Triager can address any persisted artifact deterministically.
- NO deterministic retrieval stage: the agent indexes the key-list, then calls the `note` read tool (the D84-27
  pattern, unchanged).

### 10. The `note` tool and the kernel kept as-is

- `PodNoteTool`'s contract is retained verbatim: discriminated `operation` (write/read), `extra="forbid"` args
  schema, coded rejections (`NOTES_ARGS_REJECTED` / `NOTES_EMPTY_BODY` / `NOTES_BAD_KIND` / `NOTES_NO_STORE`),
  fail-open on a `None` store (O10).
- The closed note-kind enum and the reread-latest grep-match semantics are unchanged.
- The `experiment_summary` kind's WRITE SINK changes: it routes to the variant's experiment-log file (D84-35), not
  `notes.yaml`. The read of a summary ranges the experiment-log body.
- The store's internal layout and identity change; its public read/write contract and the tool it serves are the
  seams to assert.

### 11. Degradation (unchanged canon)

- A read failure degrades to an empty set and the harness keeps serving (O4).
- A write failure raises to the caller, which warns and keeps serving (O3) - never a silent corruption.
- Every tool seam degrades fail-open when its body is absent - a denoted error object, never a raise into the turn
  (the note tool on a `None` store returns `NOTES_NO_STORE`).

### 12. Architecture decisions carried from the grilling

- The parent/thread correlation is accepted as a bounded split: memory keys = `<fault>_<strategy>:<order>`, session
  threads = the existing hash address (D84-34 amendment; no drift reconciliation is needed because they are
  distinct namespaces).
- `project_id` is a first-class store axis but NOT a session axis (the session stays run/hunt/scario-keyed).
- No schema change to the #164 hunter: the pod consumes the minted `spec_id` through the typed handoff.

### 13. The PodExport body - the pod owns its OWN terminal result (T7/#183, operator grey-points GP1-GP5, 2026-08-24)

The pod OWNS the persistence of its OWN terminal `PodExport` envelope. This amends the pod spec 1.5 boundary
("persists only through the parent's hunt-store write and the pod-owned experiment-memory store") and 1.7 ("the
verdict and evidence land in the hunt store"): the pod now persists the export itself, so it is seamlessly mappable
to the originating TestImplementationSpec and the hunting hunter-agent session that created it. It is a consequent
design change following the actor-inbox runtime redesign and the message-passing mechanism. The operator's
grey-point rulings (2026-08-24) are the design authority:

- **GP1 = A**: the export identifier is the `run_id`; re-runs of the same spec overwrite the same file (idempotent
  overwrite, D84-37). The path is `data/test-executor-pod/<project_id>/<spec_id>/<run_id>.yaml` - a SINGLE filename
  segment at the spec-directory root (a run_id may contain `:`/`-`, so the `_`-separator rules for multi-part keys
  don't apply; it is kept filesystem-safe by sanitising only path separators and control chars).
- **GP2 = A**: the filename's `<spec_id>` directory + `<run_id>` resolve to the spec/session; the export body stays
  the D5/D6 fields as today (NO new correlation fields on the envelope).
- **GP3 = A**: the **pod store becomes the source of truth**; the parent reads from it instead of persisting its own
  copy. (Wiring the parent's read is the 164-merged `hunting_agent.py` path - a DOCUMENTED FOLLOW-ON when it
  ripples beyond T7's scope; this spec's T7 implements the pod-side write.)
- **GP4**: the existing deterministic write node (`_export` in `graph.py`) writes it - the terminal call sites
  (`terminal`, `infeasible_terminal`, `exhausted_terminal`, `budget_terminal`) all route through `_export`, which
  assembles the `PodExport` and persists the envelope. The envelope returned to the parent is UNCHANGED (the IA-4
  shape); the persisted record EQUALS the returned envelope (the post-validation decision fields from the terminal
  call sites, never raw model output).
- **GP5**: the pure-log invariant holds - the export is written by the deterministic node, never an LLM tool. No new
  tool seam.

The store gains a first-class export body: `write_pod_export(spec_id, run_id, export_dict)` (idempotent overwrite,
D84-37) + `read_pod_export(spec_id, run_id)` + `list_pod_exports(spec_id)`, replicating the
`write_experiment_log`/`read_experiment_log` pattern. All matching logic stays strictly inside the store; no
`_seq`/`_ref` (D84-36).

Fail-open (O3/IA-4): a write failure degrades to the in-memory envelope - the run still returns it to the parent,
never raises. The `arun_pod` degrade path (`pod.py`, the exception branch) also builds a `PodExport`; it is a REAL
terminal result, so it persists too when a store is bound with a spec_id (respecting the fail-closed spec_id gate),
degrading gracefully if the write itself is the failure source.

## Testing Decisions

### What makes a good test here

- Assert EXTERNAL behavior of the store and the tool contracts - the addresses, keys, filters, idempotency,
  fail-open semantics - never the internal file mutation mechanics.
- The pure-log invariant is asserted structurally: no tool exposes a log-write; every record in a persisted variant
  file is attributable to a deterministic stage.
- The KB-recording work item is asserted by driving `KbRetrieveTool` over a fixture KB and checking the persisted
  variant file contains the KB observation.
- The migration is asserted by round-trip: an in-memory `ExperimentLog` populated by the deterministic stages
  persists to the correct per-project file, reads back byte-equivalent, and survives a second `arun_pod` pass.

### Seams and coverage

| Seam | Coverage | Prior art |
|---|---|---|
| `PodMemoryStore` public read/write contract (primary seam) | identity/layout per D84-33/34, order enumeration, idempotent overwrite (D84-37), append + read-latest for notes, typed attribute filters (D84-36), no `_seq`/`_ref` anywhere, per-project scoping | current `tests/attack/pod/test_pod_memory.py` (rewritten to the new topology/identity) |
| Deterministic write stages incl. KB recording | init/mint_variant/triager records persist; `ExecTool._record` and the NEW `KbRetrieveTool._record` each land a record in the variant file | `tests/attack/pod/test_tools.py` (extended with the KB-record assertions) |
| Prompt materialization | the composed memory header renders BOTH the note keys and the experiment-log identifiers that the reading tool can address | `tests/attack/pod/test_prompt_memory.py` |
| `note` tool contract | unchanged contract (extra="forbid", coded rejections, fail-open) + the new typed read filters + the summary sink routing | `tests/attack/pod/test_note_tool.py` |
| Pod-level assertions | C13 (KB tool bound) extended to assert the KB response is recorded; C14 (note written on P3) re-scoped to the summary landing in the variant's experiment-log file; C15 unchanged | `tests/integration/test_test_executor_pod_contracts.py` |
| PodExport persistence (T7/#183) | the deterministic terminal node persists the envelope to `<spec_id>/<run_id>.yaml`; the persisted record equals the returned envelope; a re-run with the same run_id overwrites; a write failure degrades fail-open to the in-memory envelope; the degrade path persists a real terminal result | `tests/attack/pod/test_pod_memory.py`, `tests/attack/pod/test_graph.py`, `tests/integration/test_test_executor_pod_contracts.py` |
| E2E harness/driver | `project_id` plumbing through the in-process driver + the persisted store on the harness seam | `tests/e2e/harness/driver.py` |

### Test-tier decisions

- The store unit tier is the primary seam: all persistence semantics asserted against temp per-project roots.
- The tool tier asserts the deterministic recording (exec + KB) without a full graph.
- The integration tier keeps C13/C14/C15 but re-scopes C14's assertion to the per-variant file.
- The LLM-free contract tier (`symbolic_runner_step_fn`) is unaffected; it injects sync fakes and needs no store.

## Out of Scope

- The orchestrator's memory-system store (produced/consumed, `hunts_store`/`notes` with append/update/delete) is the
  orchestrator's, not archived here.
- The #164 hunter rework itself (its test-spec store, tool surface, state graph) - a separate ticket; the pod only
  consumes its minted `spec_id`.
- The inbox surfer and produced->consumed delivery (G13, another workstream; the pod has no dispatch lifecycle).
- LightRAG integration itself (the `lightrag` branch) - a simultaneous workstream; `kb_retrieve` keeps its fail-open
  seam and gains the recording step.
- The plan-control tool / DAG workflow control-plane (#136).
- The closed-enum testing-pattern engine (#81) and the fault-targeting tool registry (#71).
- `update`/`delete` write options on the pod's `note` tool (D84-37).
- Changes to the LLM tool surface beyond the reading filters - the tool set stays `exec` / `kb_retrieve` / `note`.

## Further Notes

- The spec identifier `<fault>_<strategy>` is minted by the #164 hunter's `SpecItem.spec_id`. The pod must not
  re-derive it from the spec body - it crosses the typed handoff. This is why NO upstream schema change is needed.
- `data/` resolves to the hunting module's store seam (`src/polymerhus/attack/hunting/data/`); `test-executor-pod`
  is a sibling directory to the #164 hunter's `hunting/` tree under the same per-project folder.
- The in-memory `ExperimentLog` (its recording/read helpers and the D6/shape) remains the deterministic write
  surface; the store is its persistence sink at the deterministic boundary. The model sees only the reading tool.
- Persisting `executed` makes O7 dedup cross-run (within `(project, spec, order)`): A later pass re-running the
  same variant starts with the prior ledger and resumes rather than re-executing cloned probes.
- The `experiment_summary` note's cardinality is ONE per variant (the memory-spec says one per config; the pod's
  config IS the spec and each order IS a stretch - D84-35 reconciles the two).