# Unit threat model - implementation plan and dependency map

*Status: implementation plan (2026-10-18). The specification is issue [#373](https://github.com/Diekgbbtt/polyphemus/issues/373). The contract set is S1-S5 in `docs/design/`. This plan maps the data and logic dependencies, cuts the workflow tickets, and fixes the TDD and review loop. It is the input to `/to-tickets` and `/subagent-driven-development`.*

## 1. Delivery strategy

- The design branch `design/unit-threat-model` carries the specification.
- The implementation branch is `feat/unit-threat-model`.
- The implementation worktree is a separate git worktree of the design branch.
- Each ticket is one workflow issue, one implementation branch commit group, and one TDD loop.
- A ticket is done only when its targeted tests pass, the spec review passes, and the code-quality review passes.
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
| T4 | Per-loop dispatch: surfer, mover, runtime | T1, T3 | S2 8; S1 7.6 |
| T5 | Hunter harness pass FSM | - | S4 14 |
| T6 | Hunter spec set, store, tools, and removals | T5 | S3 8.6-8.8 |
| T7 | Hunter production prompt work phase | T6 | S3 8.5 |
| T8 | Pod reduced D4, INIT gate, probe authoring | - | S5 8.1-8.5 |
| T9 | Triager procedure-diff variant minting | T8 | S5 8.6 |
| T10 | Documentation, hygiene, eval translation, fault-KB | T2, T4, T7, T9 | S1 9.5-9.6; impact map |

The frontier is T1, T5, and T8.
The loop dispatches one implementer at a time, so the practical order is T1, T2a, T2b, T3, T4, T5, T6, T7, T8, T9, T10.
A different order is valid when the blockers are closed.
The T2 split is recorded in the ticket tracker: #375 (T2a), #386 (T2b), and the folded T2c scope in #376, #377, and #379.
The split happened because the original T2 could not complete in one implementation context. The T2a increment is additive; the production path changes only in T2b.

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
              -> T4 surfer/mover: per-loop dispatch, sequencing, quiesce
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
T4 + T7 + T9 -> T10 docs, eval translation, hygiene
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
Delete the planner: the pass, the phase nodes, the candidate and gate types, the in-turn prune, the materialisation render, the ratify and note turns, the orchestrator actor, the tool surface, and the planner prompt.
Delete or rewrite the planner tests and fixtures.
Add the actor-harness test for `ThreatModellerActor`.
Update the role and modeller terms in `attack/hunting/CONTEXT.md`.

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

### T4 - Per-loop dispatch: surfer, mover, runtime

**What to build.**
The `ThreatLoopItem` and the dispatch validity predicate.
The per-loop session ids.
The sequencing filter.
The low-loop pause.
The quiesce predicate.
The zero-loop consume.
The model document move.
The role-gate interaction.
Retire the dispatch consumers of `HuntConfig`, `DispatchResult`, and `DeliveredCandidate`; the loop item is the dispatch record.

**Acceptance criteria.**
- One loop file dispatches one hunter.
- Critical, high, and medium loops run first; low loops pause while a higher loop is produced or live.
- The pause is per-tick and survives a restart.
- The model document moves with its last loop.
- A zero-loop model is consumed by the mover without a dispatch.
- The work read and the dispatch read share the validity predicate.
- A malformed loop is refused without wedging the quiesce.
- A stale loop from another run is not dispatched.
- The dispatch path no longer carries `HuntConfig`, `DispatchResult`, or `DeliveredCandidate`.
- Tests cover the mover deduction and an integration path with the real store.

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

### T6 - Hunter spec set, store, tools, and removals

**What to build.**
The `specs` list write.
The `{hypothesised, ratified, dropped}` lifecycle.
The loop dispatch store key.
The spec folder and file derivation.
The move-aware write.
The notes `phase_summary`.
The `skill_list` / `skill_load` binding.
The removals: materialisation, `derive_verdict`, `SpecItem.experiment_ref`, the FaultItem draft, the old per-config key.
The hunter-side `HuntConfig` and `DispatchResult` retirement and the fault-KB aid removal.

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

### T10 - Documentation, hygiene, eval translation, fault-KB

**What to build.**
The remaining document updates.
The eval fixture and prompt translation.
The role-alias removal.
The fault-KB disposition.
The stale-vocabulary sweep.
The final docs link check.

**Acceptance criteria.**
- The domain model and the evolution paradigm carry the minimal update.
- The store, memory, pod, wiring, eval, and old spec docs carry the supersession notes.
- The eval artifacts use the loop vocabulary; the old verdict derivation is disabled or replaced.
- The role alias is removed; new runs use the new names.
- The fault-KB data and modules have a recorded disposition.
- No live obsolete verbatim remains.
- The doc link check passes.
- The targeted test suites pass.

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
2. Dispatch the code-quality reviewer with the base SHA, the head SHA, the ticket text, and the critical-thinking discipline.
   The reviewer checks standards, tests, interfaces, file responsibility, and the critical adversarial questions.
   A finding returns to the same implementer.
   Re-review until the code-quality review approves.
3. Mark the ticket complete and close the workflow issue with a comment that names the commit and the test evidence.

The final ticket gets a whole-branch code review before the PR.

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

- All ten tickets are closed.
- The targeted unit, integration, and e2e suites pass.
- The spec review and the code-quality review pass for every ticket.
- The whole-branch review passes.
- The documentation sweep finds no live obsolete verbatim.
- The PR body links the specification issue and the tickets.
- The human reviewer merges the PR.
