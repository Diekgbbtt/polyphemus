# Assertion catalogue - hunting-pipeline wiring (whole-pipeline runtime plane + REST perimeter)

**Scope:** system "Hunting pipeline wiring" - spec #169 (`docs/design/hunting-pipeline-wiring-spec.md`), ADR #169, wiring tickets #170-#175, identity-based refactor 2026-08-25.
**Source:** `spec #169` / `hunting-pipeline-wiring-adr.md`; implementation on `feat/hunting-pipeline-wiring`.
**Seams under assertion:** the REST surface (`project_management/api.py`), the runtime plane (`app/runtime.py` RuntimeManager + `attack/hunting/runtime.py` bootstrap), the mover + surfer (`attack/hunting/mover.py`, `attack/hunting/surfer.py`), the memory stores (`hunt_store.py`, `hunter_memory.py`, `pod/pod_memory.py`), the `hunting_runs` Postgres row.

## Runtime-plane finite state machines (the model under test)

### A. Hunting run row (`hunting_runs`: surrogate `hunting_run_id`)
States: `running` (only live) -> `complete | stopped | failed | interrupted` (terminal).

| state | input | guard | end state |
|---|---|---|---|
| running | quiesce proven (orchestrator settled, no dispatchable produced item, no pod live, no hunter mid-graph, idle hunters settled) | surfer `is_run_quiesced` + lap with nothing moved | complete |
| running | operator stop (`stop_hunting_run`) | run row exists | stopped |
| running | post-open admission refusal OR a collaborator degrades | fail-open, never raises | failed |
| running | process death mid-run; startup reconcile | `reconcile_orphaned_hunting_runs` flips orphaned `running` | interrupted |
| running | second launch same project | `_hunting_live_run_guard` 409 BEFORE row opens | still running (single row) |

### B. Orchestrator session (`hunting:<run_id>:orchestrator`)
States: `registered` (scheduled) -> `pass-running` -> `settled` (registry entry gone). Per-session hold orthogonal.

| state | input | guard | end state |
|---|---|---|---|
| registered/pass-running | pass writes ratified configs | `hunts_store(write)` via phase nodes | configs `ratified` in produced/, run still `running` |
| registered | hold_session | session registered | held (next unit waits) |
| held | resume_session | held | registered/pass-running |
| registered | cancel_run | registered | cancelled (registry drains) |
| pass-running | pass completes | graph END | settled (registry entry gone) |

### C. Hunter session (`hunting:<run_id>:hunt:<config_id>`)
States: `registered` -> `mid-graph` (ReAct) -> `idle` (inbox loop) -> `settled`. `hunters_in_graph` distinguishes mid-graph vs idle.

| state | input | guard | end state |
|---|---|---|---|
| registered | ratified config admitted via mover | `status == "ratified"` | mid-graph |
| mid-graph | writes a `specified` spec | `write_spec` | still mid-graph (spec in produced/) |
| mid-graph | graph ends | graph terminal node | idle; `hunters_in_graph` clears |
| idle | delivered `pod_export` | verdict stub | idle (consumed+recorded) |
| idle | `settle` message (run terminal) | quiesce proven | settled |
| any | `stop` (per-session or run stop) | registered | cancelled |
| any | pause/resume | registered | held / resumed |

### D. Pod session (`hunting:<run_id>:pod:<config_id>:<spec_id>`)
States: `registered` -> `executing` (`arun_pod`) -> `settled` (export persisted + recorded).

| state | input | guard | end state |
|---|---|---|---|
| registered | `specified` spec admitted via mover | own status (identity-based refactor) | executing - NO live-parent requirement |
| executing | arun_pod completes | terminal node | export envelope `<spec_id>/<run_id>.yaml` + durable parent-keyed note + session settles |
| executing | live parent inbox present | parent config_key in `hunter_inboxes` | ALSO posts live feed (optional, never a gate) |
| executing | pause/resume | registered | held / resumed |
| any | stop | registered | cancelled |

### E. Module gate (hunting handle: `ModuleState.RUNNING|PAUSED|DRAINING|STOPPED`)

| state | input | guard | end state |
|---|---|---|---|
| RUNNING | pause | not stopped | PAUSED; admission refused (`ModuleAdmissionRefused` -> 503) |
| PAUSED | resume | paused | RUNNING |
| PAUSED/DRAINING | drain | paused | DRAINING then STOPPED (flush hook) |
| any | pause of stopped | stopped | safe no-op |

## Contract predicates (integration)

### REST perimeter - hunting run lifecycle
- C1 - `POST /projects/{p}/hunting` canonical: body `{candidates: []}` (empty batch, O1) -> 201 `{hunting_run_id}`; a follow-up `GET /projects/{p}/hunting/{id}` returns the row `status == "running"`. Observable: exactly one row; id echoes.
- C2 - same endpoint, unknown project `{p}` -> 404 `unknown project`; NO row created.
- C3 - second live launch, same project, while the first is `running` -> 409 (the `running` row is the guard); both ids distinct, but only the first row stays `running`.
- C4 - control plane absent (`runtime` not landed) -> 503 `hunting control-plane runtime has not landed`; no row opened.
- C5 - malformed body (candidates not a list / a candidate missing `unit_id`) -> 422 (pydantic); no row opened.
- C6 - `POST /projects/{p}/hunting/{id}/stop` canonical (row exists) -> `{"stopping": True}`; `GET` then returns terminal `stopped`.
- C7 - stop unknown id -> 404 `no hunting run for that hunting_run_id`.
- C8 - `GET /projects/{p}/hunting/{id}` canonical returns the exact terminal status after quiesce: `complete` (empty-batch run with no produced items reaches quiesce immediately).
- C9 - GET unknown id -> 404.

### REST perimeter - singular component launches
- C10 - `POST /projects/{p}/hunting/orchestrator` canonical `{candidates:[...]}` -> 202 `{component: "orchestrator", run_id, dispatched_asynchronously}`; a later read of the HuntStore produced family shows the ratified configs the pass wrote (fixture-driven).
- C11 - orchestrator launch on unknown project -> 404; control plane absent -> 503.
- C12 - `POST /projects/{p}/hunting/hunt` canonical: `{unit_id, fault_class, vulnerability_class}` -> 202 `{component: "hunt", enqueued: True, enqueued_key, dispatched_asynchronously}`; enqueued config file exists under `hunt_configs/produced/` with `status == "ratified"`.
- C13 - hunt enqueue replayed (same identity) -> 409 `this hunt config is already enqueued (at-most-once)`; produced count stays ONE (novelty gate, idempotent).
- C14 - hunt enqueue with malformed/empty `unit_id`/`fault_class` -> 422; nothing written.
- C15 - hunt enqueue unknown project -> 404.
- C16 - `POST /projects/{p}/hunting/pod` canonical: PRECONDITION a held/paused pod session is registered (`hunting:<rid>:pod:<config_id>:<spec_id>`); body `{session_id}` -> 202 `{component: "pod", resumed: True, session_id}`; the session's hold is cleared (subsequent unit proceeds).
- C17 - pod resume with a session id that is NOT registered -> 404 `no stored/paused pod session ... (fail-closed: nothing fabricated)`; NOTHING is written to the HunterMemoryStore produced family.
- C18 - pod resume with empty/missing `session_id` -> 422.
- C19 - pod resume, control plane absent -> 503; unknown project -> 404.
- C20 - pod resume of a registered-but-`RESUMED` (not held) session -> 202 (runtime verb's safe no-op), at-most-once: resume twice yields one effect.

### REST perimeter - per-session lifecycle verbs (ADR Q17)
- C21 - `POST /projects/{p}/hunting/{rid}/sessions/{sid}/pause` canonical: live registered session of the run -> `{"state": "held"}`; the session's next unit boundary waits (admission of new work unaffected).
- C22 - pause a NEVER-REGISTERED session belonging to the run's id namespace -> 404 (RunNotRegistered mapped); a session of a SIBLING run through this namespace -> 404 (unreachable).
- C23 - pause/resume/stop on an unknown `hunting_run_id` -> 404 `no hunting run for that hunting_run_id`.
- C24 - `resume` canonical on a held session -> `{"state": "resumed"}`; resume of a not-held session -> 200 (runtime verb no-op, NOT a 4xx).
- C25 - `stop` on a live session -> `{"state": "stopping"}`; the session's task is cancelled and its registry entry drains; the run row is NOT auto-terminalised by a single-session stop.
- C26 - any per-session verb without an active runtime -> 503 (session verbs failure-handling path).

### REST perimeter - module-wide gate (recon/analysis/hunting) - shared-runtime seam
- C27 - `POST /projects/{p}/modules/hunting/pause` -> `{"state": "paused"}`; a subsequent `POST /projects/{p}/hunting` -> 503 `module not accepting new work`.
- C28 - pause -> resume -> pause on hunting reflects `paused`/`running`; unknown module -> 404 `unknown module`.
- C29 - drain canonical: hunting paused then drains to `stopped`; the module's per-project flush hook fires (checkpointer archive) with no in-flight unit dropped.

### Mover + surfer contract (produced/consumed at-least-once)
- C30 - a produced `ratified` config dispatches ONE hunter and moves produced->consumed; the consumed file is byte-identical to the produced one; produced set for that identity is empty.
- C31 - a produced config refused (gate full / module paused / not-yet-dispatchable) STAYS in produced and is retried next tick; a refused lap reports `refused == 1`, `moved == 0`.
- C32 - double-dispatch defense: a produced item whose Q13 session id is already live in the registry is NOT dispatched twice; its move still lands once (R3 window closed without extra markers).
- C33 - `TestSpecItem` dispatch gate is the spec's OWN `status == "specified"`, never a live parent: a produced `specified` spec with NO live hunter in `hunter_inboxes` still dispatches one pod and moves produced->consumed (identity-based refactor regression).
- C34 - `run_work_remaining` (quiesce pending-work) and `build_run_dispatch` agree: a produced `specified` spec is ALWAYS dispatchable -> quiesce reachable (never-disagree contract, restored).
- C35 - a produced `hypothesised`/`dropped` config contributes NOTHING to `run_work_remaining`; it never blocks quiesce; it never dispatches (G6 - dropped stays on disk).

### Pod export durability (ADR Q16 amendment)
- C36 - pod completion persists the export envelope durably: `<project>/test-executor-pod/<spec_id>/<run_id>.yaml` exists and EQUALS the envelope returned; a second identical run (same run_id) overwrites one file (idempotent).
- C37 - the DURABLE parent-keyed record is written at pod completion under the parent's `config_key`, independent of a live parent session: `HunterMemoryStore` note exists with the export payload even when the idle loop never ran (crash-between-dispatch-and-consume window closed).
- C37b - the durable record is keyed `<config_key>:pod-export:<spec_id>` with action `update` (note_name `pod-export:<spec_id>`): the note key contains NO `:`-session-id path, the pod session id is recoverable from `provenance["source"]`, and a re-export of the same (config, spec) updates the same key (one current record per spec, #199).
- C38 - a live co-running parent inbox (config_key present) ALSO receives the `pod_export` message BEFORE the pod settles (settle can never overtake); the idle loop consumes without double-recording (one note per export).

## Walkthrough predicates (e2e - live stack)

### Bootstrap (operator-supplied)
- A distinct agent container built FROM THIS WORKTREE (`docker-compose.e2e.yml` service `agent-1`, image `polymerhus-agent:latest`, published 8081, volumes mount this tree's `src/db/skills/gateway`), attached to the existing `polymerhus_polymerhus-net` so it resolves neo4j/postgres/kali by DNS. Tests drive `AGENT_HTTP_URL` (default `http://localhost:8081`/`http://agent-1:8080` in-network).
- Fixtures seeded into the stack's stores (temp or live project): a `ratified` hunt config (3-part key `<unit>_<CWE-x>_<class>`), one `specified` test-implementation spec (`test-specs/<fault_key>/produced/<fault>_<strategy>.yaml`), one experiment-log slice (`<spec_id>/experiment-log/<order>.yaml` with `experiment_summary`), one `PodExport` envelope (`<spec_id>/<run_id>.yaml`) - the data the walkthroughs read back out of the live store.

- E1 - **whole-pipeline happy path**: `POST /projects/{p}/hunting` with a seeded candidate batch -> 201; poll `GET .../hunting/{id}` until terminal -> `complete`; the store shows: ratified config moved produced->consumed, its `specified` spec produced->consumed, the pod export envelope + parent-keyed note present, the run's registry empty. Terminal: status `complete`, 1 config consumed, 1 spec consumed, 1 export file, 0 live sessions.
- E2 - **cross-run produced-spec reconciliation**: seed a produced `specified` spec whose parent config was consumed by an EARLIER run (no live parent); launch a fresh whole run; assert the pod dispatches (own-status gate), the spec moves produced->consumed, the export is recorded durably under the parent's `config_key`, and the run reaches `complete` - NOT wedged (regression for the quiesce wedge).
- E3 - **mid-flight stop**: launch a whole run; `POST .../hunting/{id}/stop` while the orchestrator is mid-pass -> `{"stopping": True}`; poll -> `stopped`; the app store preserves the partial trail (produced configs/specs survive); registry empty.
- E4 - **per-session pause/resume mid-graph**: launch a whole run; pause the hunter session (by Q13 id); assert the shared registry shows it held; resume; assert it completes (quiesce reached); terminal `complete`.
- E5 - **single-session stop does not end the run**: launch a whole run; stop ONE pod/hunter session; assert 200 `stopping`, the run row stays `running`, and the run still reaches terminal on quiesce (or remains `running` with other live sessions - assert the exact branch the implementation takes).
- E6 - **orchestrator-only launch**: `POST .../hunting/orchestrator` -> 202; then `POST .../hunting/hunt` enqueues the ratified config; assert the config file exists in produced; NO `hunting_runs` row was ever created by the orchestrator-only launch (assert `GET .../hunting/{rid}` -> 404 for its synthetic run id).
- E7 - **one-live-run guard**: two back-to-back whole-run launches on the same project -> first 201, second 409; only one `running` row in `list_hunting_runs`.
- E8 - **at-most-once replay**: same `POST .../hunting/hunt` body twice -> first 202 enqueued, second 409; produced file count for that identity is exactly 1.
- E9 - **pod-only resume**: precondition a paused pod session (or seed a held session via the shared runtime); `POST .../hunting/pod {session_id}` -> 202 resumed; assert the held session's hold cleared in the runtime registry.
- E10 - **process-death orphan reconcile**: progress a run to `running`, simulate death (drop the row's owning process/leave it `running`), restart reconcile -> `interrupted`; a new launch is then allowed (guard released).

## Precision notes
- Quantities are exact (ONE row, ONE consumed file, ONE export; replay keeps count at 1). Expected values come from the spec/fixture, never recomputed the way the code computes them.
- Contract predicates run in the integration tier - the stack is booted (agent-1 + neo4j + postgres) OR the PG layer is ring-fenced with a live `hunting_runs` DSN (the PG-twining tests live behind `pg_live_dsn()`); fixture data is seeded through the real store APIs and validated at setup.
- Walkthrough observables are read back from the live stores by named reads (`read_produced_configs`, `produced_spec_files`, `read_spec`, `read_pod_export`, `write_note`/`read_notes`), never returned by the code under test as a tautology.

## Out of scope
- Verdict-processing semantics beyond consume-and-record (ADR Q16 stub; future ticket).
- The `recon`/`analysis` modules beyond the shared module-gate verbs C27-C29 they share.
- Per-candidate rehearsal of the phase-2 ordering engine and fault-KB internals (own tickets).
- Graceful stop / finish-pass degradation (separate ticket per the sealed seam).