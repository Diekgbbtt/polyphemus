# Unit threat model - implementation plan and dependency map

*Status: implementation plan (2026-10-18). The specification is issue [#373](https://github.com/Diekgbbtt/polyphemus/issues/373). The contract set is S1-S5 in `docs/design/`. This plan maps the data and logic dependencies, cuts the workflow tickets, and fixes the TDD and review loop. It is the input to `/to-tickets` and `/subagent-driven-development`.*

## 1. Delivery strategy

- The design branch `design/unit-threat-model` carries the specification.
- The implementation branch is `feat/unit-threat-model`.
- The implementation worktree is a separate git worktree of the design branch.
- Each ticket is one workflow issue, one implementation branch commit group, and one TDD loop.
- A ticket is done only when its targeted tests pass and the spec review passes.
- The final PR targets `main`. Merging is a human action.
- No implementation ticket starts before its blockers are closed.

## 2. Ticket graph

| ID | Ticket | Blocked by | Spec |
|---|---|---|---|
| T1 | Threat model store, schema, and completion checker | - | S2 4-5, 7, 10 |
| T2a | Threat modeller agent, five gates, tools, prompt material | T1 | S1 3-9 |
| T2b | Planner retirement and modeller wiring | T2a | S1 4.4, 7.1-7.4, 9.1 |
| T2c | Residual type retirement (folded into T3, T4, T6) | T2b | S1 9.1 |
| T3 | Run lifecycle: intake, ordering, risk budget, halt, resume | T1, T2a, T2b | S1 7; S2 7.4, 9 |
| T4a | Per-loop dispatch: loop item, mover, sequencing, quiesce | T1, T3 | S2 8; S1 7.6 |
| T4b | Config family retirement and hunter launch re-point | T4a | S1 9.1 |
| T5 | Hunter harness pass FSM | - | S4 14 |
| T6 | Hunter spec set, store, tools, and removals | T5 | S3 8.6-8.8 |
| T7 | Hunter production prompt work phase | T6 | S3 8.5 |
| T8 | Pod reduced D4, INIT gate, probe authoring | - | S5 8.1-8.5 |
| T9 | Triager procedure-diff variant minting | T8 | S5 8.6 |
| T10a | Code/test hygiene, role alias, fault-KB disposition | T2a, T2b, T4a, T4b, T7, T9 | S1 9.5-9.6; impact map |
| T10b | Eval translation, e2e translation, final docs sweep | T10a | impact map; eval design |
| T11 | **PROPOSED, not cut** - the run resume trigger: the operator verb and the orphaned-run disposition | T3 | S1 7.5; #331 ESCALATED item 2; impact map 3.5 |

The frontier is T1, T5, and T8.
The loop dispatches one implementer at a time, so the practical order is T1, T2a, T2b, T3, T4a, T4b, T5, T6, T7, T8, T9, T10a, T10b.
A different order is valid when the blockers are closed.
The T2 split is recorded in the ticket tracker: #375 (T2a), #386 (T2b), and the folded T2c scope in #376, #377, and #379.
The T4 split is recorded in the ticket tracker: #377 (T4a) and #387 (T4b).
The T10 split is recorded in the ticket tracker: #383 (T10a) and #397 (T10b).
The split happened because the original T2 could not complete in one implementation context. The T2a increment is additive; the production path changes only in T2b.
The T4a increment changes the dispatch record; the config family retires in T4b.
The T10a increment removes the aliases and the dead surface; the eval and the final docs sweep land in T10b.

## 3. Data dependency map

### 3.1 New entities

| Entity | Owner | Consumers |
|---|---|---|
| `UnitThreatModel`, the section types, `Loop`, `Evidence`, `Confidence`, `RiskFactors`, `Validation`, `RiskProfile` | T1 | T2, T3, T4 |
| `ThreatModelStore` and the loop file record | T1 | T2, T3, T4 |
| `RiskAccumulator` and the run record | T3 | T4, T10 |
| `ThreatLoopItem` and the dispatch validity predicate | T4 | T10 |
| `HunterPass`, `SpecItem`, `HuntState`, `SignalOutcome` | T5 | T6, T7 |
| `SkillProcedure` | T6 or T8, single home | T7, T8, T9 |
| `VariantBasis` | T9 | T9, T10 |

The `SkillProcedure` type must have one home.
The hunter writes it into the spec provenance; the pod reads it.
Place it with the pod's D4 types and import it from the hunter, or place it in a small shared contract module.
Do not duplicate the type.

### 3.2 Store ownership

- `ThreatModelStore` owns the model document, the loop files, and the model notes.
- The hunter store owns the spec set, the spec notes, and the spec folder.
- The pod store owns the variants, the experiment log, and the pod notes.
- No store imports another store's namespace.
- The shared patterns are replicated: atomic writes, bounded notes, derived symbols, move-aware writes, coded rejections, and the shared notes tool base.

### 3.3 Status vocabulary

- One vocabulary: `{hypothesised, ratified, dropped}`.
- The spec terminal is `ratified`; the declass is `dropped`.
- `verified` and `specified` are removed from every live path.
- The vocabulary change is a cross-cutting data change. T5 and T6 carry it in the harness; T4 carries it in dispatch; T8 and T9 carry it in the pod fixtures and prompts; T10 sweeps the docs and tests.

## 4. Logic dependency map

### 4.1 Modeller track

```
T1 store
  -> T2a modeller pass: five gates, hints, tools, completion, prompt
      -> T2b planner retirement and bootstrap wiring (transitional unit order)
          -> T3 run driver: intake order, accumulator, halt, resume, trajectory
              -> T4a surfer/mover: per-loop dispatch, sequencing, quiesce
                  -> T4b config family retirement and hunter launch re-point
```

The modeller writes the model.
The run driver owns the intake and the accumulator.
The surfer owns dispatch.
The modeller never dispatches a hunter.

### 4.2 Hunter track

```
T5 pass tracker: state, graph, signals, hints, notes
  -> T6 spec set: set write, store key, status lifecycle, removals
      -> T7 production prompt
```

The pass tracker observes signals.
The spec set is the artifact the signals write.
The prompt drives the model to produce the signals.

### 4.3 Pod track

```
T8 reduced D4 + INIT gate + probe authoring
  -> T9 triager procedure diff + variant basis
```

The pod consumes the D4.
The triager mints variants from the skill procedure.
The hunter supplies the procedure excerpt.

### 4.4 Integration

```
T4 + T7 + T9 -> T10a hygiene -> T10b docs, eval translation, final sweep
```

T10 also closes the role-name aliases and the fault-KB disposition.

## 5. Tickets

### T1 - Threat model store, schema, and completion checker

**What to build.**
A new threat model schema and a new `ThreatModelStore`.
The schema is partial at the intermediate gates and complete at COMPLETED.
The store merges `{state, sections}` writes.
The store derives the unit directory, the model file, the loop file, and the dispatch id.
The store is atomic, move-aware, and collision-safe.
The store emits loop files at COMPLETED and commits the model after them.
The store archives invalid or degraded models to `abandoned/`.
The completion checker validates the necessary attributes, referential integrity, the assumption-to-loop closure, the loop order, and the risk profile.
`validation.valid` gates consumability.
The store computes `risk_profile`; the checker recomputes it.

**Acceptance criteria.**
- A partial model can be written section by section and read back.
- The COMPLETED write emits one loop file per non-`none` loop; a zero-loop model emits none.
- A failing model write after the loop files leaves the previous state; a lower-gate write deletes orphan loop files.
- The checker reports `missing`, `unclosed`, and `referential_errors`; `valid` is true only when all are empty.
- Consumability requires `state == COMPLETED` and `validation.valid`.
- An invalid or degraded model is archived to `abandoned/`.
- The store is atomic, move-aware, collision-safe, and bounded for notes.
- The risk profile is store-computed and checker-recomputed.
- Tests use a temporary project root.

### T2a - Threat modeller agent, five gates, tools, and prompt material

Delivered at `89663bcd`; the review is tracked on #375.
This increment is additive: the planner stays as the production path until T2b.

**What to build.**
The per-unit modeller pass.
The five states and their gate sections.
The modeller tool surface.
The passive tracker and the gate hints.
The completion validation call.
The runtime session segment, the actor role, the LLM role, and the provider environment variable rename, with a one-window alias for old runs.
The modeller prompt material.
The back-edge removal.

**Acceptance criteria.**
- A scripted modeller turn writes all five gates to the real store.
- The model state is monotonic; a lower-gate write does not regress it.
- Each gate hint is injected in the tool response.
- The tool surface is exactly the modeller's; `graph_view`, `kb_query`, and the fault-KB aid are absent.
- The write payload is `{state, sections}`; the unit identity is bound at construction.
- The prompt carries the required material in S1 section 8.
- The completion validation runs; an invalid model is archived.
- The rename is in place with the one-window alias.
- The back-edge surface is gone.
- The prompt contract tests pass.
- Tests use a fake turn seam and the real store.

### T2b - Planner retirement and modeller wiring

Tracked on #386.

**What to build.**
Re-point the hunting bootstrap from the planner to the modeller pass with a transitional distinct-unit order.
Swap the new-run session id to `threat_modeller_session_id` at both sites and adopt the modeller actor-reap seam.
Split the modeller pass's tool layer into `threat_modeller_tools.py` (the store tool, the notes tool, the suite pair, `ModellerTools`, and the surface builder), leaving `threat_modeller.py` the pass and the tracker.
Delete the planner: the pass, the phase nodes, the candidate and gate types, the in-turn prune, the materialisation render, the ratify and note turns, the orchestrator actor, the tool surface, and the planner prompt.
Delete or rewrite the planner tests and fixtures.
Add the actor-harness test for `ThreatModellerActor`.
Update the role and modeller terms in `attack/hunting/CONTEXT.md`.

**Hazards this slice inherits from T2a.**
- A modeller pass is SERIAL per run: it mutates the shared `ModellerTools` (the run-scoped tracker, the store wrapper, the unit cell, the suite seam). Every consumer this slice wires must dequeue one unit at a time; a concurrent second pass over the same tools would interleave unit identities and gate readings.
- The session id is swapped in two places that must move together: `runtime.start_hunting`'s registered id and `surfer`'s quiesce key. Keying the new id before the swap quiesces a run whose live pass is still registered under the legacy segment; both sites carry a `designed-not-built` marker naming this ticket.
- The modeller actor-reap seam (`_reap_modeller`) has no caller until this slice; it is marked `designed-not-built` and its registry is keyed by run id in both the default and the injected-factory lane, so the reap and the degrade-cause lookup cannot address a different actor than the pass built.
- The pass's grounding inputs (`context_provider`, and the explicit `projection` / `surface_overview` seams) are wired to a live source here: the L1 unit projection read and the L1 application-surface overview. Until then both render as recorded gaps on every turn.

**Acceptance criteria.**
- `start_hunting` runs the modeller pass as the production path; the planner has no call site.
- The planner types and nodes are gone; no dead import remains.
- The actor-harness test drives the real actor with a fake session.
- The breaker and the provider-failure path survive the move.
- The targeted suites pass.

### T2c - Residual type retirement

Folded into the consumers: the `HuntConfig` / `DispatchResult` / `DeliveredCandidate` retirement lands with T3 (#376), T4 (#377), and T6 (#379); the fault-source/KB selection retirement lands with T3; the fault-KB disposition lands with T10.

### T3 - Run lifecycle: intake, ordering, risk budget, halt, resume

**What to build.**
The intake freeze and the ordering algorithm.
The exclusions: completed, in-flight live or resumable, abandoned retried.
The symbolic risk accumulator and the halt.
The run record keys.
The resume rules and the commit order.
The interleave with the surfer.
The degraded units and the trajectory.
Retire the runtime selection consumers of `fault_source`, `fault_kb`, `symptom_kb`, and `fault_risk`.
Replace the transitional distinct-unit order that T2b introduces.

**Acceptance criteria.**
- The ordering counts live L1 edges in both directions, excludes retired families, and breaks ties by aggregated endpoints then unit id.
- A System's endpoint count sums the distinct connected Services.
- The accumulator uses weights 0/1/2/3/4 and the inclusive threshold.
- The crossing unit completes and dispatches; the next unit is never modelled; `blocked_unit` is recorded.
- The run record carries every fixed key.
- Resume re-enters at `intake_position` and recomputes `risk_total`.
- A halted run resumes dispatch only.
- A crash between the model and the run record cannot leave a stale total.
- The modeller does not wait for dispatch.
- The runtime no longer selects units through the fault-source/KB path.
- Tests cover the pure algorithms and the integration path.

### T4a - Per-loop dispatch: loop item, mover, sequencing, quiesce

Delivered at `ee2fcee3`; the review is tracked on #377.

**What to build.**
The `ThreatLoopItem` and the dispatch validity predicate.
The per-loop session ids.
The sequencing filter.
The low-loop pause.
The quiesce predicate.
The zero-loop consume.
The model document move.
The role-gate interaction.
The payload materialisation.

**Acceptance criteria.**
- One loop file dispatches one hunter.
- Critical, high, and medium loops run first; low loops pause while a higher loop is produced or live.
- The pause is per-tick and survives a restart.
- The model document moves with its last loop.
- A zero-loop model is consumed by the mover without a dispatch.
- The work read and the dispatch read share the validity predicate.
- A malformed loop is refused without wedging the quiesce.
- A stale loop from another run is not dispatched.
- Tests cover the mover deduction and an integration path with the real store.

**Implementation-time decisions (T4a).**

- The payload path is INERT until T6 (`fixed` at the T4a code-quality review): the
  run's hunter builder advertises `consumes_loop_payload` and `_default_hunter_builder`
  advertises False, so the loop family is not dispatch input at all - the loop files
  stay produced, nothing is moved and no model document is consumed, the run quiesces,
  and `report_dispatch_gap` names the state (N produced loop files, the harness
  designed-not-built, zero hunts). A capable builder (the tests' fakes, T6's real one)
  dispatches as before. T6 removes the flag, the marker and the `Mapping`
  discrimination together.
- The spec family's dispatch status moved INTO the mover's produced read (the T4a
  review's never-disagree contract): one read now fetches each produced spec body per
  inward read, and the run's work read re-reads it, so a quiesce check costs one extra
  small YAML read per produced spec. There is no status-only read in the hunter memory
  store (a YAML body must be parsed to reach the status), so a "status without a body
  fetch" would be the same read; this is recorded as an accepted, bounded scope change
  (the produced spec count is per hunt) rather than a silent one. A later change may
  give the work read the tick's already-read inbox.
- The low-loop pause reads "live" as mid-graph (`state.hunters_in_graph`): an idle
  hunter authors nothing more, and counting it live would hold both the low loop and
  the quiesce, so the run terminal's settle could never land.

### T4b - Config family retirement and hunter launch re-point

Tracked on #387.

**What to build.**
Drop `HuntConfigItem` and the config read from the mover.
Delete the surfer's config clauses and the config bridge.
Drop the `hunt_store` threading from the runtime.
Decide the disposition of `enqueue_hunt_config` and the `POST /hunting/hunt` endpoint.
Replace the temporary config bridge in `run_hunter_session`, or mark it designed-not-built with the T6 dependency.
Re-point the tests onto a shared `produce_model` fixture.
Update `CONTEXT.md` and `CONTEXT-MAP.md`.

**Acceptance criteria.**
- The mover reads only produced loop files.
- The dispatch path no longer carries `HuntConfig`, `DispatchResult`, or `DeliveredCandidate`.
- The API enqueue disposition is decided, implemented, and tested.
- The hunter launch carries the loop payload or refuses loudly with the T6 marker.
- The re-pointed tests pass.

**Implementation-time decisions (T4b).**

- The API disposition is RETIRE, with a loud tombstone: `POST /hunting/hunt`
  answers 410 Gone naming the loop-file replacement and the T10 translation, and
  `enqueue_hunt_config` is deleted. The eval check: `eval/orchestrator/api.py`
  and `eval/ph.py` never call the path (they launch the whole run), so no eval
  behaviour breaks; `eval/hunting_ctl.py` mentions it only in its docstring, and
  its ratified-config tail reads the retired family (recorded there as a T10
  translation). A re-point to the produced loop's dispatch id was rejected: the
  loop identity is store-derived per run, and a caller-supplied identity cannot
  name one without fabricating a model.
- The hunter launch carries the loop payload only: the config bridge
  (`payload=config`) retired with `_config_dispatch`, `run_hunter_session` takes
  a `Mapping` payload and the loop's likelihood, and the production
  `_default_hunter_builder` keeps its loud `HunterPayloadNotBuiltError` (the T6
  #379 marker) - no silent config fabrication anywhere.
- The `hunt_store` parameter is gone from `run_delivery_tick`,
  `read_produced_inbox`, `_apply_move`, `run_work_remaining`, `is_run_quiesced`,
  `build_run_dispatch`, `run_surfer_loop`, `report_dispatch_gap` and
  `start_hunting`. `HuntStore` itself stays as a module (`semantic_key` and the
  key helpers are still live on the hunter/pod identity path); its config I/O has
  no dispatch consumer, and its data disposition is T6/T10's.
- The carry-forward `_WARNED_UNRATIFIABLE` (the config family's SECOND
  refuse-once log, beside the mover's run-scoped `log_refusal_once`) retired with
  the config path it guarded - the mover's `log_refusal_once` is the only
  refusal log left on the dispatch path (the loop family's). The unused
  `ProducedInbox` import in `surfer.py` is gone.
- The shared `produce_model` fixture (plus `loop_row`) lives in
  `tests/hunting_fixtures.py`; the loop-dispatch tier binds it locally, and the
  re-pointed config-tier tests call the shared helper, never a copied ladder.
- Live-tier carry-forward: E4 and E5 (the hunter pause/resume and the
  single-session-stop contract) need a live hunter session, which cannot
  dispatch from a pre-seeded config any more and cannot dispatch from a loop
  until T6's payload harness - they carry with a precise T6 skip. E1/E2/E3/E6/
  E7/E8 are re-pointed (the pod family and the whole-run guard stay live; the
  retired enqueue is a 410).
- Eval translation (T10b, #397): `eval/orchestrator/trial.py::place_premined`
  writes pre-mined hunt configs into `hunt_configs/produced/`, a family the
  mover no longer reads, and `eval/orchestrator/predicates.py` / `setup.py` carry
  the same `preloaded_hunting_artifacts.configs` shape. T10 translates those to
  the loop vocabulary (or a whole-run seeding seam) and sweeps the prompt/doc
  mentions.

### T5 - Hunter harness pass FSM

**What to build.**
The eight pass literals.
The `SpecItem`, `HuntState`, detector, and advance functions.
The signal acceptance rule.
The seven hints.
The grounding KB rider.
The `phase_summary` note kind and the `phase:<state>` names.
The graph topology.
The removal of the fault lifecycle and the old hints.

**Acceptance criteria.**
- The tracker advances on the declared exit signals.
- A later signal forward-jumps and records the skipped states.
- An earlier signal is trail-only.
- No signal stays.
- The state is monotonic.
- The graph ends only when the state is `complete`.
- The machine never gates a tool call.
- The note is updated on a re-iteration.
- The old fault lists, statuses, hints, and `derive_verdict` are gone.
- Tests cover the pure functions and the graph.

**Implementation-time decisions (T5).**

- The pure surface is `hunter_state.py`: the eight pass literals, `SpecStatus`
  (`{hypothesised, ratified, dropped}`), `SpecItem`, `HuntState`
  (`state` / `specs` / `injected_constant` / `trail`), the signal shapes, the
  detector `detect_phase_signal(tool_name, args)`, the acceptance rule
  `detect_signal(state, signal) -> SignalOutcome` and
  `advance_state(state, outcome, signal) -> (new_state, hint, trail_entry)`.
  `advance_state` takes the observed signal as a third argument: S4 14.5 fixes
  that the trail entry records the signal, and the listed outcome shapes
  (`advance(target)` / `forward_jump(target, skipped)` / `trail_only(reason)` /
  `none`) do not carry it by themselves.
- The trail entry shape is `{signal, outcome, from, to}` plus `skipped` on a
  forward jump. The hint is keyed by the EXITED pass - the signalling pass on a
  forward jump, not the pass the jump started from.
- The state-machine side retires the fault lifecycle completely: `FaultStatus`,
  `FAULT_STATUSES`, `FaultItem`, `HuntPhase`, `TransitionName`,
  `detect_transition`, `push_transition`, the four lists, `current_fault`, the
  `phase` channel, the five old hint constants, and the stale `derive_verdict`
  are gone. The `spec_id`-derivation helper from #313 goes with the state
  machine: the spec identity is the store's, derived from the payload keywords
  (S3 8.6).
- The store-side status vocabulary is NOT T5's: `hunter_memory.STORE_SPEC_STATUSES`
  keeps the retiring four values locally (the store owns its write gate) because
  T6 (#379) reworks the store onto the spec set - `specified` is also the mover's
  pod-dispatch gate (`mover.SPEC_DISPATCH_STATUS`), so dropping the literal from
  the store in T5 would silently stop every pod dispatch. `SpecItem.experiment_ref`
  and the harness `HuntConfig` consumption (and the `hunter_payload_capable`
  marker) likewise stay for T6, as the ticket boundary records.
- The graph topology is as sketched in S4 14.10 with one implementation detail
  named here: the "no signal" stay carries NO destination (`Command(goto=[])` -
  the drive returns with the channels untouched) instead of routing back to
  `supervise`, because a self-route is a LangGraph superstep loop and reaching END
  would claim the chain is over. END is therefore reached only on `complete`, and
  the router is the pure `route_supervise(state)` so the contract is unit-testable.
  `detect` appends the trail-only entry itself (the sketch routes that case
  straight back to `supervise`); `advance` writes the state, the hint, and the
  entry.
- The `phase_summary` note kind and the `phase:<state>` name land in the pure
  module (`PHASE_SUMMARY_KIND`, `phase_note_name`). The hunter store's note-kind
  enum gains the kind (S4 14.8 - hunter-only: the hunt store, the pod and the
  modeller do not), so the interposed exit is writable and an `update` rewrites
  the same note. The detector accepts a phase note only for the FIVE declared
  note exits (`NOTE_EXIT_PASSES`): GENERATE and VERIFY-CLAIMS exit on the
  `hunts_store` writes and COMPLETE is terminal, so a note named for them is no
  signal and can never substitute the authoritative store write. The tracker is
  never gated on the store's acceptance anyway (see the H6 predicate).
- The harness reads the signal off the model's raw tool call BEFORE the tool's
  acceptance matters and injects the exited pass's constant in that response; the
  grounding `kb_query` rider stays outside the graph (it is not a transition).
  The hunt ends when the model concludes (a plain answer) or when the tracked
  state lands `complete` - the retired `concluded` phase is gone and the terminal
  feedback renders `state: <pass>`.
- The `specs` channel exists and rides through `advance_state` untouched
  (last-write); the harness does not yet fold a written set into it. That fold is
  T6's, together with the `specs`-list store write, because the `SpecItem` fields
  (`spec_ref`, the derived `spec_id`) come from the store's file derivation.
- Tests: `tests/attack/test_hunter_state.py` (the pure functions, re-pointed from
  the #313 payload-shape consumer) and the new `tests/attack/test_hunter_graph.py`
  (the topology and the drive); the harness predicates H1/H4 are re-pointed to the
  pass chain and a new H6 pins the no-gate invariant.

### T6 - Hunter spec set, store, tools, and removals

**What to build.**
The `specs` list write.
The `{hypothesised, ratified, dropped}` lifecycle.
The loop dispatch store key.
The spec folder and file derivation.
The move-aware write.
The notes `phase_summary`.
The `skill_list` / `skill_load` binding.
The removals: materialisation, `derive_verdict`, the FaultItem draft, the old per-config key.
The hunter-side `HuntConfig` and `DispatchResult` retirement and the fault-KB aid removal.
(`derive_verdict` and `SpecItem.experiment_ref` were already removed in T5; T6 removes the remaining dead surface.)

**Acceptance criteria.**
- A batched `specs` write creates the set.
- The terminal write promotes and declasses the set.
- The spec body is the reduced D4 at every status.
- The store key is `<unit_name>__<loop_id>`; the folder is `test-specs/<hunt_key>/`.
- The file name is derived from the keywords.
- A consumed identity is not recreated.
- The phase note is written and updated.
- The skill tools are bound.
- The removals leave no dead surface.
- The pod dispatch path stays.
- The hunter tools and store no longer consume `HuntConfig`, `DispatchResult`, or the fault-KB aid.
- Tests cover the store, the tools, the status lifecycle, and the removals.
- The harness consumes the loop payload: the `consumes_loop_payload` flag on
  `_default_hunter_builder` is removed together with its `Mapping` discrimination
  and the T4a inertness marker, so the per-loop dispatch path is live end to end.

**Spec note carried from T4a (the payload's transition link) - LANDED in T6.**
The stored `Violation` now carries `transition_ref` (S2 5.1, `threat_model.py`),
and the completion checker reports a non-null ref that resolves to no transition
as a referential error. `materialise_hunter_payload` reads the link: a valid ref
selects exactly that transition; an absent ref is unambiguous only with zero or
one transition; with several transitions it yields NO transition and records the
gap (`dynamic_state.transition` is None) instead of guessing the first. Until
this landed the payload's transition was advisory context, never a gate.

### T7 - Hunter production prompt work phase

**What to build.**
The production hunter prompt and examples.
The pass sequence, the loop ontology, the discipline paragraph, the role framing, the grounding scope, the four collection axes, the combinatorial generation, the well-formedness check, the falsification-only verify pass, and the removals.
Run multiple refine-and-adversarial-review iterations.

**Acceptance criteria.**
- The prompt carries the eight passes and the four collection axes.
- The encoding scheme is not a discrimination variable.
- The class-exhaustiveness question and EVALUATE/CONCLUDE/[G] are absent.
- The grounding uses the methodology KB only for technology configurations.
- The verify pass probes only the assumptions.
- The role framing names no codebase position or version.
- The prompt contract tests pass.
- A dry mocked run produces a well-formed spec set.
- The adversarial prompt review passes.

### T8 - Pod reduced D4, INIT gate, probe authoring

**What to build.**
The reduced D4 types.
The `SkillProcedure` type.
The INIT gate mandatory set.
The runner probe authoring from the reduced spec.
The `provenance.baseline_ref` replay path.
The no-probe terminal.
The pod runner prompt update.

**Acceptance criteria.**
- The reduced D4 round-trips; the retired fields are rejected.
- The INIT gate requires a non-empty URL and at least one non-blank symptom.
- The gate collects all violations and rejects with zero tool calls.
- The runner authors at least one probe from the spec.
- `provenance.baseline_ref` enables replay when present.
- No derivable probe lands `no-symptom-evidence` with `clean=false`.
- The pod runner prompt names the baseline, not the retired vector.
- Tests cover the gate, the D4, and the probe authoring.

### T9 - Triager procedure-diff variant minting

**What to build.**
The ten variant-basis literals.
The typed `SkillProcedure` read.
The first-uncovered procedure diff.
The failure-mode fallback on the spec's symptoms and assumptions.
The runner-failure and runner-divergence triggers.
The duplicate guard.
The `declined_attribute` basis.
The triager prompt rewrite.

**Acceptance criteria.**
- Each basis is minted from its intended condition.
- The first uncovered gap class wins.
- A fully covered procedure mints a failure-mode variant.
- A runner failure or divergence mints the recovery basis.
- A duplicate basis and detail is not re-minted.
- The variant record keeps its shape; `declined_attribute` carries the basis.
- The terminal vocabulary is unchanged.
- The triager prompt carries the algorithm.
- Tests cover the graph and the prompt.

### T10a - Code and test hygiene, role alias, fault-KB disposition

Delivered at `daff1b63`; the review is tracked on #383.

**What to build.**
The role-alias removal.
The conciseness directive.
The T9 hazard resolutions.
The fault-KB disposition.
The dead-surface removal.
The domain-model and evolution-paradigm update.
The first documentation pass.

**Acceptance criteria.**
- The role alias is removed; new runs use `threat_modeller` and the `threat-modeller` session segment.
- The conciseness directive says "spec `rationale`" across the three prompts and the drift test.
- The T9 hazards are resolved or documented.
- The fault-KB data and modules have a recorded disposition; the boot consumer is gone.
- The dead surface is removed.
- The domain model and the evolution paradigm carry the minimal update.
- The first documentation pass carries the supersession notes.
- The doc link check passes.
- The targeted test suites pass.

### T10b - Eval translation, e2e translation, final docs sweep

Tracked on #397.
**Status: implemented on `feat/unit-threat-model`.**

**What was built.**
The eval translation and the pre-mined config guard.
The e2e fixture and driver translation.
The integration hygiene.
The remaining documentation sweep.
The final no-live-obsolete-verbatim check.

**Pre-mined retarget hazard (T10b review).**
The launch mints the run id, so `retarget_premined` rebinds a pre-mined tree only after `POST /hunting` returns.
The intake freeze can observe the source run id first: a real terminal run id can be archived to `abandoned/`, while a synthetic/unknown id is treated as in-flight and survives.
The convention is a synthetic source run id (for example `pre-mined`), never a real terminal run's id.

**The #196 live e2e gate disposition.** T10a deleted `tests/e2e/test_http_proxy_history.py`
with the legacy `hunting_pod.py`. The gate exercised the retired
`payload_vector_space.request_ref` replay path through that pod, so it could
not survive the module removal. The production pod's replay path keeps its
unit/contract coverage (`tests/attack/pod/test_react_seams.py`,
`tests/attack/pod/test_request_ref.py`); a replacement LIVE replay-lineage
gate is a separate ticket, not a T10b deliverable. Recorded here and on #397.

**Acceptance criteria.**
- The eval artifacts use the loop and spec-set vocabulary; a pre-mined config cannot pass as a satisfied prerequisite.
- The e2e fixtures and driver use the reduced D4.
- The integration fixtures have no vacuous assertions and the E1 premise is true.
- The remaining documentation carries the supersession notes.
- No live obsolete verbatim remains.
- The doc link check passes.
- The targeted eval, e2e, and hunting suites pass.

## 6. TDD loop per ticket

1. Read the ticket and the named spec sections.
2. Write the seam list. Confirm the seams against the spec.
3. Write one failing test at the highest seam.
4. Run it and observe the red.
5. Write the minimal implementation.
6. Run the test and observe the green.
7. Repeat for the next behaviour.
8. Refactor in the review stage, not in the red-green cycle.
9. Run the targeted suites.
10. Self-review, commit, report.

Tests assert external behaviour at the store, tool, graph, and run seams.
Tests do not assert private methods.
Expected values come from the spec, a worked example, or a known-good literal.
No tautological assertions.
No horizontal test batches.

## 7. Review loop per ticket

After the implementer reports DONE:

1. Dispatch the spec reviewer with the full ticket text and the implementer's report.
   The reviewer reads the code and verifies nothing is missing and nothing is extra.
   A finding returns to the same implementer.
   Re-review until the spec review passes.
2. Mark the ticket complete with a comment that names the commit and the test evidence.

The code-quality review stage is cut by operator direction (2026-10-19).
It is not part of the loop.
The whole-branch review before the PR is also cut.
Findings that the spec review cannot cover, such as stale docs after a retirement, are recorded on T10a (#383) or T10b (#397) and swept there.

## 8. Risks

- The modeller and hunter tickets are large. If an implementer reports BLOCKED or the context is too large, split the ticket at the seam named in the report.
- The role rename touches provider, skills, and session configuration. A missed call site breaks old-run resume. The rename test must sweep the live names.
- The status vocabulary sweep is wide. A missed `specified` or `verified` in a fixture silently tests the old contract. The sweep test must fail on the retired literals.
- The store commit protocol has a crash window. The test must inject a failing model write after the loop files.
- The low-loop pause is per-tick. The test must prove the pause survives a restart and that a later high loop does not preempt admitted work.
- The `SkillProcedure` type must have one home. A duplicate type will drift between the hunter and the pod.
- The prompt work phase needs more than one iteration. The ticket is not done after the first draft.
- The final docs sweep must not treat a historical record with an explicit supersession note as a live claim.

## 9. Definition of done

- All twelve tickets are closed.
- The targeted unit, integration, and e2e suites pass.
- The spec review passes for every ticket.
- The documentation sweep finds no live obsolete verbatim.
- The PR body links the specification issue and the tickets.
- The human reviewer merges the PR.
