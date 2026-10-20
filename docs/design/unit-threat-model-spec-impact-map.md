# Unit threat model - specification impact map

*Status: spec-phase artifact (2026-10-18). Tracker: [#373](https://github.com/Diekgbbtt/polyphemus/issues/373). This map is the index of the unit threat model specification set. It records which documents change, which are superseded, and which decisions each spec must carry. It is an input to `/to-tickets`; it is not an implementation.*

## 1. Provenance

The specification set synthesises these sources:

- `docs/design/unit-threat-model-workbench.md` - the grilling record and the decision authority (R1-1 to R8-4, Q1-Q60).
- `docs/design/unit-threat-model-workflow.md` - the modeller workflow contract.
- `docs/design/unit-threat-model-tools-adr.md` - the tool-binding ADR.
- `docs/design/unit-threat-model-ordering-halt-adr.md` - the intake-order and progressive-halt ADR.
- `docs/design/unit-threat-model-risk-scoring-research.md` - the risk-scoring research and the adopted scheme.
- `docs/design/unit-threat-model-abduction-research.md` and `docs/experiments/unit-threat-model-abduction-eval.md` - the KILL verdict and the two adopted disciplines.
- `docs/experiments/unit-threat-model-testimplspecs-qa.md` - the typed-surface quality measurement and its structural limitation.

No item in this map reopens a decided question. The specs make implementation-level choices only where a decision delegated the choice to the change spec.

## 2. The spec set

| ID | Document | Action | Contract it owns |
|---|---|---|---|
| S1 | `docs/design/hunting-67-threat-modeller-spec.md` | NEW | The threat modeller agent: identity, goal, workflow states and gates, tools, context, prompt material, termination, probing, run lifecycle, observability, honour clauses, failure handling. |
| S2 | `docs/design/hunting-67-threat-model-artifact-spec.md` | NEW | The formal unit threat model artifact: entity shapes, evidence and confidence model, loop entity, risk scoring, store layout, consumption, dispatch payload, validation, cross-run semantics. |
| S3 | `docs/design/hunting-67-hunting-agent-spec.md` | EXTEND, section 8 | The hunter workflow redesign: loop payload input, pass sequence, prompt tree integration, spec-set lifecycle, typed surface, removals. |
| S4 | `docs/design/hunting-164-state-graph-spec.md` | EXTEND, section 14 | The passive hunter harness: new pass FSM, proxy-signal matrix, signal acceptance, hints, phase-summary notes, state channels, removals. |
| S5 | `docs/design/hunting-67-test-executor-pod-spec.md` | EXTEND, section 8 | The test-executor pod contract: D4 delta, INIT gate, probe authoring without the retired vector, triager variant minting, prompt context. |

S1 and S2 are one feature: the modeller rewrite. S3, S4, and S5 are one feature: the hunter payload redesign. The split is by contract owner, not by delivery ticket.

## 3. Decision traceability

Each decision below must appear in the named spec section. The adversarial review verifies this table against the source records.

### 3.1 The tools ADR

| Decision | Spec location |
|---|---|
| `hunts_store` and `notes` survive; the target object changes | S1 5.1, 5.2 |
| HTTP-history reads (search and get, never replay) | S1 5.3 |
| `exec` for live probes | S1 5.4 |
| Auth store plus the per-project skill coupling | S1 5.5 |
| `skill_list` / `skill_load` suite binding | S1 5.5, S3 8.7 |
| `graph_view` not bound to the modeller | S1 5.6 |
| Fault-KB aid tool withdrawn | S1 5.6 |
| No modeller-scoped probe cap | S1 5.4, 6.8; S2 7.5 |
| The execution-wide cap is the token budget; the risk budget is the modelling cap | S1 6.8; S2 7.5 |
| Probes are non-destructive where feasible; prior state restored; black-box only | S1 5.4 |
| LACK-1: server-side fetch probes behind file, reference, import, and URL-shaped inputs | S1 5.4 |
| LACK-2: drop needs a fundamental infeasibility finding, not absence in the sharpening | S1 6.5, S2 5.5 |
| Episodic notes per phase | S1 5.2, 6.2 |
| Evidence per claim (request records, note refs) | S2 5.1, 5.2 |
| Containment by prompts, discipline, review | S1 5.4, 6.7 |

### 3.2 The ordering-halt ADR

| Decision | Spec location |
|---|---|
| The coupling is accepted and documented; intake order is also the halt order | S1 7.2, 7.4; S2 9.4 |
| The sort key stays the sort key; the halt never re-sorts | S1 7.4; S2 9.4 |
| The accumulator is symbolic run state; it is checked at each model completion | S1 7.4; S2 7.4 |
| The comparison is inclusive (`>=`) | S1 7.4 |
| The crossing unit is fully modelled and dispatched; the next unit is never modelled | S1 7.4 |
| The intake order, crossing unit, and blocked unit are recorded in the run | S1 7.4; S2 9.4 |
| A resumed run re-enters at the recorded position with the persisted accumulator | S1 7.5; S2 9.2 |
| Calibration by replaying recorded runs in intake order | S2 7.4 |
| The halt set is a function of the order by construction | S1 7.2, 7.4 |

### 3.3 The grilling decisions

| Decision | Spec location |
|---|---|
| R1-1: self-standing unit threat model; attack-tree relationship inspirational only | S1 2.1; S2 2.1 |
| R1-2: rewrite the hunt-orchestrator in place; no new submodule | S1 4.1, 9.1 |
| R1-3: actor runtime, one per-run modeller session, terminal lifecycle, no model evolution | S1 4.4; S2 9.1 |
| R1-4: intake and ordering | S1 7.2 |
| R1-5: tool surface and capabilities | S1 5 |
| R2-1 / R2-10: artifact contract, one model per unit, evidences, no probe plans | S2 4, 5 |
| R2-2: loop entity, 1:n failure modes, ids in ranked order | S2 5.6, 6 |
| R2-3: hunter data contract delta (one loop record per dispatch) | S3 8.2; S2 8.2 |
| R2-4: no `HuntConfig`; the per-loop payload is materialised at dispatch | S2 8; S3 8.2 |
| R2-5: progressive risk budget | S1 7.4; S2 7.4 |
| R2-6: dispatch interleave | S1 7.3; S2 8.4 |
| R2-7: KB disposal | S1 5.6; S3 8.8 |
| R2-8 / R2-9: model lifecycle and consumption | S2 8.4, 9 |
| R2-11: one generic store-write surface; passive trajectory keeping | S1 5.1; S2 10.3 |
| R2-12: notes documents removed; material embedded in prompts | S1 6.2, 8 |
| R2-13: per-state inputs and acquisition cost | S1 4.6, 6.2, 6.3 |
| R2-14 / Q20: low-ranked loops stay dispatchable; sequencing high and medium first | S1 7.6; S2 8.3 |
| R2-15: L1 application-surface overview entity | S1 4.6, 6.2 |
| R2-16: hunter-side materialisation retired fully | S1 5.6; S3 8.8 |
| R2-17: gate cadence is prompt-level; telemetried | S1 4.5, 6.1 |
| R3-1: risk criterions, likelihood only | S2 7.2 |
| R3-2 / Q33 / Q40: CVSS-inspired four-factor reasoning, five-level enum, monotonic weights | S2 7.1 to 7.4 |
| R3-3: evidence per criterion | S2 5.2; S1 6.3 |
| R3-4: unreliability risks | S2 7.6 |
| R3-5: W2 abduction and coverage; loose dedup | S1 6.4 |
| R3-6 / Q55-Q57: termination, probe budget, side effects | S1 5.4, 6.8 |
| R3-7 / Q58: no schema gate; `ratify` completion validation | S1 6.6; S2 5.7 |
| R3-8: map-back validation; failure modes never fed forward | S2 5.5, 8.2 |
| R3-9 / Q30: retention-first drop rule | S1 6.5; S2 2.4, 5.5 |
| R3-10: live-authority rule | S1 6.7 |
| R4-1: eval translation requirement | S1 9.5 |
| R4-2: docs, supersessions, hygiene | S1 9.1, 9.6; this map |
| R4-3 / R8-4 / Q43: KILL accepted; two disciplines adopted; no boundary-record adoption | S1 6.4, 6.5 |
| R4-4: alpha-omega deferred | S1 11 |
| R4-5: surface recovery out of scope | S1 4.3, 11 |
| R5-1 / Q34: design B, per-unit directory, per-loop files | S2 4.2, 8.1 |
| R5-2 / Q35: validation seam | S1 6.6; S2 5.7 |
| R6-1 / Q35: confidence degree, falsification lifecycle | S1 6.3; S2 2.3, 5.2, 7.2 |
| R6-2 / Q36: hunter feed-forward contract | S3 8.2, 8.6; S2 8.2 |
| R6-3 / Q37: QA measurement and the exhaustiveness limitation | S3 8.5, 8.6 |
| R7 Q37-Q40: no payload-completeness rule; no exhaustiveness verification; enum and weights | S3 8.5, 8.6; S2 7.1 |
| R8-1 / Q39: production hunter prompt redesign | S3 8.5, 8.6 |
| R8-2 / Q44-Q47, Q49-Q53: harness FSM refactor | S4 14 |
| R8-3 / Q48: pod contract reframe | S5 8 |
| Q52: consistent `{hypothesised, ratified, dropped}` vocabulary | S2 6.2; S3 8.6; S4 14.6 |
| Q53: D3_HINT reframe | S4 14.7 |

### 3.4 The risk-scoring research

| Decision | Spec location |
|---|---|
| Enum `none / low / medium / high / critical` | S2 7.1 |
| Monotonic weights | S2 7.1 |
| No impact term | S2 7.2 |
| `none` loops are retained but not dispatched | S2 5.6, 8.3 |
| Threshold constant in harness configuration; calibration basis recorded | S2 7.4; S1 7.4; S2 9.2 |
| Four reasoning factors: attack vector, attack requirements, privileges required, complexity | S2 7.2 |
| Per-level breakdown recorded | S2 7.3, 7.4 |
| Confidence degree as a class-assignment factor | S2 7.2 |

### 3.5 Implementation-time additions (T3, #376)

These are implementation-time additions to the specs above, recorded here as
required by S1 4.3 (the change spec owns implementation-level choices only where
a decision delegated the choice to it).

| Addition | Spec location | Why |
|---|---|---|
| The `stale` intake-exclusion reason | S1 7.1; S2 9.2 | A terminal, non-resumable run's produced model whose archive to `abandoned/` did not land must not be modelled into (a stale COMPLETED model seeds the retry's tracker), and it must not vanish from the run record either: it is recorded as an exclusion with its reason. |
| The `skipped` key on a trajectory entry | S2 9.2 | S1 6.1 requires a forward jump to record the gates it skipped in the run record's trajectory; the six-key shape cannot carry them without it. |
| The run RECORD's fixed keys are merged, never replaced | S2 9.2 | A resume re-persists the recomputed record, so the record write is additive by top-level key (`pg.set_hunting_run_stats`) and never touches the run's status. |

**Disposition - the run-resume TRIGGER has LANDED as the operator verb (T11, #398).**
S1 7.5 fixes the resume RULES (re-enter at `intake_position`, recompute
`risk_total`, a halted run resumes dispatch only) and T3 implemented them, but
T3 added no production path that re-enters `start_hunting` with an existing run
id: the launch API always mints a new row, and `reconcile_orphaned_hunting_runs`
terminalises an orphaned `running` row without rescheduling it.
T11 adds that path: `POST /projects/{project_id}/hunting/{hunting_run_id}/resume`
applies the decision table (ADR 331 section 3) through the pure
`attack/hunting/resume.py::resume_decision`, claims the run atomically, and
re-enters `start_hunting` with the existing run id.
The operator verb is the ratified floor; the auto-resume background health
checker the operator chose (D-3) is a FOLLOW-UP, not built.
The orphaned-run disposition is recorded and executable: a process-restart
`interrupted` row carries no `quota_exhausted` class, so the table answers
do-not-resume (fail-closed); the reconcile never reschedules one, and the verb
does not guess a cause.
The claim clears the provider-pause keys in the same UPDATE, so a
resumed-then-crashed row is the same do-not-resume orphan.
The intake freeze consumes the decision too: an `interrupted` producer whose
decision is terminal or do-not-resume has its produced model archived to
`abandoned/` and its unit retried, while a resumable throttle (including one
inside its backoff window) keeps its model `in-flight`.
CONSEQUENCE (STATE): a unit whose produced model is in flight under a live
`running` / `stopped` / resumable-`interrupted` producing run is still excluded
from every later run; the operator resumes that producing run (or waits for its
terminal) before a later run can model the unit. The freeze logs the producing
run and its status for every such unit, and the exclusion is recorded in
`intake_excluded`.

## 4. Affected document ledger

The action column names the phase that performs the change: **spec** means this specification set writes the clause; **build** means the implementation change performs it; **hygiene** means a mechanical pass in the same change.

| Document | Impact | Action | Owner |
|---|---|---|---|
| `docs/design/hunting-67-threat-modeller-spec.md` | New agent contract | spec | this set |
| `docs/design/hunting-67-threat-model-artifact-spec.md` | New artifact contract | spec | this set |
| `docs/design/hunting-67-hunting-agent-spec.md` | Workflow, input, typed surface, removals superseded; section 8 added | spec + build | this set, then prompt work phase |
| `docs/design/hunting-164-state-graph-spec.md` | State vocabulary, channels, gates, hints superseded; section 14 added | spec + build | this set, then harness refactor |
| `docs/design/hunting-67-test-executor-pod-spec.md` | D4 surface, INIT gate, probe authoring, variant minting superseded; section 8 added | spec + build | this set, then pod refactor |
| `docs/design/hunting-67-orchestrator-spec.md` | The planner contract is fully superseded by S1 | hygiene | build |
| `docs/design/hunting-67-per-agent-specs-spec.md` | Sections 4, 5, and 7 superseded; add a pointer to S1/S3/S5 | hygiene | build |
| `docs/design/hunting-67-per-agent-specs-decisions.md` | D67-03, D67-07, D67-10 superseded | hygiene | build |
| `docs/design/hunting-store-write-decisions.md` | Section 10 hunter spec status and shape updated; section 4.2 hunter config-key binding superseded | build | build |
| `docs/design/hunting-memory-system-spec.md` | The hunter per-config memory layout is superseded for the hunter; atomic-write and bounds patterns stay | build | build |
| `docs/design/hunting-84-pod-memory-system-spec.md` | Variant record shape stays; `declined_attribute` semantics change; D4 references updated | build | build |
| `docs/design/hunting-164-state-graph-adr.md` | Add a supersession note for the status vocabulary and FSM | hygiene | build |
| `docs/design/hunting-164-assertion-catalogue.md` | Lifecycle and FSM assertions superseded | hygiene | build |
| `docs/design/hunting-83-hunting-agent-implementation.md` | Workflow and typed-surface clauses superseded | hygiene | build |
| `docs/design/hunting-orchestrator-candidates-rewrite-spec.md` | Modeller predecessor; superseded in full for the modeller | hygiene | build |
| `docs/design/hunting-pipeline-wiring-adr.md` | Per-config dispatch and `specified` gate updated to per-loop and `ratified` | build | build |
| `docs/design/hunting-pipeline-wiring-spec.md` | Same as above | build | build |
| `docs/design/eval-harness-design.md` | Hunt-config references translated to threat-model and loop references | build | build |
| `docs/design/vuln-testing-remediation-map.md` | D4 field list updated | build | build |
| `docs/design/typesafe-system-one-evaluation.md` | D4 field list updated | build | build |
| `docs/design/http-proxy-history-design.md` | `payload_vector_space.request_ref` reference updated to the replay runtime path | build | build |
| `docs/design/domain-model.md` | Add the unit threat model bounded context and entities | build | build |
| `docs/design/evolution-paradigm.md` | Minimal citation only, per Q60 | build | build |
| `src/polymerhus/attack/hunting/CONTEXT.md` | Stale `TestImplementationSpec` term updated; `WELL-FORMEDNESS`, `phase_summary`, loop payload, artifact terms added or sharpened | build | build |
| `src/polymerhus/attack/hunting/prompts/hunt-orchestrator.md` | Rewritten as the threat modeller prompt | build | build |
| `src/polymerhus/attack/hunting/prompts/hunting-agent.md` | Rewritten in the prompt work phase | build | prompt work phase |
| `src/polymerhus/attack/hunting/prompts/pod-triager.md` | Mining section and decision output rewritten | build | build |
| `src/polymerhus/attack/hunting/prompts/examples.md` | Examples updated to the new passes and spec surface | build | prompt work phase |
| `docs/design/unit-threat-model-workflow.md` | Active contract; stale AGGREGATE+CHECK, `testing_pattern`, and next-frontier lines fixed in this spec phase | spec | this set |
| `docs/design/unit-threat-model-workbench.md` | Living sections: exec-budget-open, ADR-unwritten, and materialisation-continues lines fixed in this spec phase | spec | this set |
| `docs/design/hunting-84-regrounding-decisions.md` | Variant-minting clauses updated to the procedure diff | build | build |
| `docs/design/hunting-84-assertions.md` | D4 and variant assertions updated | build | build |
| `docs/design/hunting-304-kb-degradation-guard-adr.md` | D4 and spec context updated | build | build |
| `docs/design/hunting-67-per-agent-specs-decisions.md` | D67-03, D67-07, D67-10 superseded; add a pointer to S3/S5 | hygiene | build |
| `docs/design/modelling-trust-boundaries-notes.md` | Removed from production as a standalone document; material embedded in the modeller prompt | build | build |
| `docs/design/modelling-dynamic-states-trust-notes.md` | Removed from production as a standalone document; material embedded in the modeller prompt | build | build |
| `eval/OPERATOR.md` | The oracle's D4 field list and hunt-config vocabulary updated | build | build |
| `src/polymerhus/attack/hunting/prompts/pod-runner.md` | `payload_vector_space.request_ref` replaced by `provenance.baseline_ref` | build | build |
| `docs/design/unit-threat-model-spec-review.md` | The adversarial review record | spec | this set |

### 4.1 Code, prompt, test, and data ledger

The document ledger above is not enough on its own.
This table names the code, prompt, test, and data surfaces the change touches.
The implementation plan cuts these into the workflow tickets.

| Surface | Impact | Action | Owner |
|---|---|---|---|
| `ThreatModelStore` and the model schema module (new) | The artifact, layout, commit protocol, checker, loop files | build | modeller ticket |
| `read_only_graph` (renamed from `hunt_orchestrator` by T10b #397), `orchestrator_graph`, `actors`, `runtime` | Planner pass replaced by the modeller pass; role and session rename; run record; the residual graph view renamed to its responsibility | build | modeller ticket; T10b done |
| `hunt_store`, `hunter_memory` | The modeller config store retires; the hunter memory moves to the loop key | build | modeller and hunter tickets |
| `surfer`, `mover` | Per-loop dispatch, the validity predicate, the pause, the quiesce, the zero-loop consume | build | wiring ticket |
| `hunter_state`, `hunter_graph`, `hunter_tools`, `hunting_agent` | Pass FSM, spec set, set write, note kind, skill tools, removals | build | hunter harness ticket |
| `prompts/hunting-agent.md`, `prompts/examples.md` | Prompt redesign and examples | build | prompt work phase |
| `prompts/hunt-orchestrator.md` | Rewritten as the threat modeller prompt | build | modeller ticket |
| `prompts/pod-triager.md` | Mining section and decision output | build | pod ticket |
| `prompts/pod-runner.md` | Baseline ref and reduced D4 | build | pod ticket |
| `pod/types`, `pod/verification`, `pod/graph`, `pod/agents`, `pod/symbolic`, `pod/pod_memory`, `pod/tools` | D4 delta, INIT gate, probe authoring, variant basis, triager context | build | pod ticket |
| `http_history_contract` | `payload_vector_space.request_ref` references replaced by `baseline_ref` | build | pod ticket |
| `fault_kb`, `fault_source`, `symptom_kb`, `fault_risk`, `data/hunting/fault-kb.yaml` | The old selection and materialisation path has no producer in the new pipeline; retire the runtime consumers and record the data-file disposition | build | modeller ticket |
| `app/llm/providers`, `app/llm/skills`, `app/llm/session_address` | New role id, skills binding, session address | build | modeller ticket |
| `tests/attack/test_hunter_state.py`, `test_hunting_agent.py`, `test_hunt_store.py`, `test_hunter_memory.py`, `test_hunting_wiring.py`, `test_hunting_surfer_tick.py` | FSM, set write, store key, dispatch | build | respective tickets |
| `tests/attack/pod/test_verification.py`, `test_graph.py`, `test_prompt_memory.py`, `test_request_ref.py`, `test_react_seams.py`, `test_compaction_seam.py` | INIT gate, variant basis, baseline ref | build | pod ticket |
| `tests/integration/test_test_executor_pod_contracts.py`, `test_hunting_wiring_mover.py`, `hunting_wiring_stack.py` | D4, dispatch, quiesce | build | respective tickets |
| `tests/e2e/test_test_executor_pod_walkthrough.py`, `tests/e2e/harness/driver.py`, `tests/e2e/fixtures/specs/*.yaml` | Reduced D4 fixtures, per-loop dispatch | build | eval ticket |
| The eval fixtures, trial records, assessor and diagnoser prompts, challenge-location mapping | Hunt-config vocabulary translated to loops; `derive_verdict` disabled or replaced | build | eval ticket |
| `src/polymerhus/project_management` references to `specified` | Status vocabulary update where the hunting artifacts are read | build | build |
| `data/hunting/fault-kb.yaml` | Keep only if a documented consumer remains; otherwise retire with the old selection path | build | modeller ticket |


## 5. Obsolete verbatim register

This register lists the stale claims a reader or an implementation could still trust. The review hunts these across the repository. Each entry names the replacement.

| Where | Stale claim | Replacement | Status |
|---|---|---|---|
| `hunting-164-state-graph-spec.md` 2.3 | Lifecycle `{hypothesised, verified, dropped, specified}` | `{hypothesised, ratified, dropped}`; terminal `ratified`; declass `dropped` | build; section 14 supersedes |
| `hunting-164-state-graph-spec.md` 2.3 | The four push transitions by fault status | The eight-state pass sequence with proxy signals | build; section 14 supersedes |
| `hunting-164-state-graph-spec.md` 2.4 | `derive_verdict` stays, stale | `derive_verdict` is removed | build; section 14.11 |
| `hunting-164-state-graph-spec.md` 3 | `HuntState` fault lists, `current_fault`, four fault statuses | `state`, `specs`, `injected_constant`, `trail` | build; section 14.9 |
| `hunting-164-state-graph-spec.md` 5 | Phase-transition constants D2, commit, next-fault, next-iteration, D3 | The seven pass hints plus the grounding retrieval-gap rider | build; section 14.7 |
| `hunting-164-state-graph-spec.md` 6 | Spec body `specified`, `payload_vector_space`, `testing_pattern` | Spec body `ratified`; three fields retired | build; section 14.6 |
| `hunting-164-state-graph-spec.md` 11 | Assertions over the fault lifecycle | Assertions over the pass FSM and the spec-set lifecycle | build; section 14.13 |
| `hunting-164-state-graph-adr.md` | Dispositions name `verified` and `specified` | Supersession note to S4 | fixed |
| `hunting-164-assertion-catalogue.md` | C-assertions over the old lifecycle | Supersession note to S4 | fixed |
| `hunting-67-hunting-agent-spec.md` 1.3 | The old decision tree and fault-hypothesis workflow | S3 8.4 pass sequence | fixed; header and section markers |
| `hunting-67-hunting-agent-spec.md` 1.6 | D4 typed base with testing pattern and payload vector space | S5 8.4 D4 base | fixed; header and section markers |
| `hunting-67-hunting-agent-spec.md` 6.1 | Spec-schema and verdict-mapping assertions | S3 8.10 and S4 14.13 | fixed; header marker |
| `hunting-67-orchestrator-spec.md` | The planner identity, candidate gate, back-edge, `HuntConfig` minting | S1 in full | fixed; header marker |
| `hunting-67-per-agent-specs-spec.md` 4, 5, 7 | Planner and old hunter contracts; D4 fields | S1, S3, S5 | fixed; header marker |
| `hunting-67-per-agent-specs-decisions.md` | D67-03, D67-07, D67-10 as live | Supersession note to S3/S5 | build |
| `hunting-store-write-decisions.md` 10 | Hunter spec status `specified`; FaultItem draft body | S2 6.2; S3 8.6 | fixed |
| `hunting-memory-system-spec.md` hunter sections | Per-config hunter folder and `fault_key` | S2 4.2 and S3 8.7 per-loop key | build |
| `hunting-67-test-executor-pod-spec.md` 2 | Testing pattern is the open NL pattern | Retired; the skill procedure carries the procedural knowledge | fixed; section marker |
| `hunting-67-test-executor-pod-spec.md` O12/C11 | Empty payload vector still probes once | No probe derivable lands `no-symptom-evidence`, `clean=false` | fixed; section marker |
| `hunting-67-test-executor-pod-spec.md` 2 variants | Declining a spec attribute yields a variant | The seven procedure-gap bases plus the failure-mode and runner triggers | fixed; section marker |
| `hunting-67-test-executor-pod-spec.md` 1.7 | The parent consumes the pod result for the hypothesis verdict | The hunter derives no verdict; the pod dispatch path stays | fixed; header marker |
| `unit-threat-model-workflow.md` 3.6 | `AGGREGATE+CHECK`; `payload_vector_space` and `interpretation_guidance` retired only | `WELL-FORMEDNESS`; `testing_pattern` retired too | fixed |
| `unit-threat-model-workflow.md` 3.6 | R8-2 and R8-3 are the next frontiers | Both are decided and land with the change spec | fixed |
| `unit-threat-model-workbench.md` 1.5 | Exec probe budget and side-effect rules remain open | Decided by Q55-Q57 | fixed |
| `unit-threat-model-workbench.md` 2/4 | The ordering-halt ADR is unwritten | Written | fixed |
| `unit-threat-model-workbench.md` 1.3 | Hunter-side materialisation continues as today | Retired by Q39 | fixed |
| `CONTEXT.md` `TestImplementationSpec` term | Testing pattern, payload vector space, interpretation guidance | The reduced D4 surface; three fields retired | fixed |
| `CONTEXT.md` `persisted artifact schema` | Spec terminal `specified` | Terminal `ratified`; `verified` retired | fixed |
| `CONTEXT.md` `config status lifecycle` | The hunter spec and config use different vocabularies | One vocabulary `{hypothesised, ratified, dropped}` | fixed |
| `CONTEXT.md` `hunting agent` term | The per-config hunter, `derive_verdict`, and the old tool surface as current | The redesign note names the per-loop hunter and the removals | fixed |
| `prompts/hunting-agent.md` | The old tree with EVALUATE, CONCLUDE, [G], and the fault lifecycle | The S3 pass sequence | build; prompt work phase |
| `prompts/pod-triager.md` | Variant mining from a declined spec attribute | The procedure-diff basis | build |
| `prompts/pod-runner.md` | `payload_vector_space.request_ref` | `provenance.baseline_ref` | build |
| `prompts/examples.md` | Old examples with retired fields | New pass and surface examples | build; prompt work phase |
| `prompts/hunt-orchestrator.md` | The planner prompt | The threat modeller prompt | build |
| `eval-harness-design.md` | `derive_verdict` and the old D4 fields | The hunt-config translation and the disabled or replaced verdict derivation | build |
| `eval/OPERATOR.md` | The oracle's D4 list and hunt-config vocabulary | The reduced D4 and loop vocabulary | build |
| `data/hunting/fault-kb.yaml` and `fault_kb.py` / `fault_source.py` / `symptom_kb.py` | The old selection and materialisation path | Retire the consumers and record the data file disposition | build |

## 6. Naming and identity decisions

These names are fixed by this spec set. Implementation must not invent alternatives.

- Agent role: **threat modeller**.
- Runtime session segment: `threat-modeller`.
- LLM role ID: `hunting_threat_modeller`.
- Actor/session role: `hunting_threat_modeller`.
- The rename is an expand-contract pass inside the change: add the new names and a one-window alias for `hunting_orchestrator`, migrate the call sites, then remove the old names. T10 closed the window: the old role, env key, session segment, API path and component label are removed, with no resume path.
- Threat-model store root: `data/<project_id>/hunting/threat_modeller/` with `produced/`, `consumed/`, and `abandoned/`.
- Unit directory: `<unit_name>/`, where `<unit_name>` sanitises `:` and `/` to `-`; a sanitised-name collision appends `-<first 8 hex of sha256(unit_id)>`.
- Model document: `<unit_name>.yaml` inside the unit directory.
- Loop file: `loop-<rank>.yaml` inside the unit directory.
- Loop id: `loop-<rank>`; rank 1 is the highest likelihood.
- Loop dispatch id: `<unit_name>__<loop_id>`.
- Hunter session id: `hunting:<run_id>:hunt:<unit_name>__<loop_id>`.
- Pod session id: `hunting:<run_id>:pod:<unit_name>__<loop_id>:<spec_id>`.
- Hunter store key: the loop dispatch id.
- Hunter spec file name: `<fault_keyword>_<strategy_keyword>.yaml`, unchanged.
- Hunter state literals: `grounding`, `slice`, `collect`, `discriminate`, `generate`, `well_formedness`, `verify_claims`, `complete`.
- Phase-summary note kind: `phase_summary`.
- Phase-summary note name: `phase:<phase>`, where `<phase>` is the state literal: `grounding`, `slice`, `collect`, `discriminate`, or `well_formedness`; the generate and verify-claims exits are store writes and need no note.
- Spec status values: `hypothesised`, `ratified`, `dropped`.
- Class fields: `canonical_class` is the freely named taxonomy class; `web_vulnerability_class` is the skills-suite directory name (the decided field); `suite_gap` marks an uncovered class.
- Baseline: `provenance.baseline_ref` is the optional single HTTP-artifact pointer.
- Skill procedure: the typed seven-field `SkillProcedure` (`recon_action`, `bypass_technique`, `technology_grounding`, `pro_tips`, `advanced_technique`, `preliminary_chaining`, `interpretation_pitfalls`), authored by the hunter, bounded to 4000 characters.
- Risk enum: `none`, `low`, `medium`, `high`, `critical`.
- Risk weights: `0`, `1`, `2`, `3`, `4`.
- Default threshold: `12`.
- Run record keys: `intake_order`, `intake_position`, `intake_excluded`, `risk_threshold`, `threshold_basis`, `risk_weights`, `risk_total`, `risk_breakdown`, `model_sums`, `crossing_unit`, `blocked_unit`, `halt`, `degraded_units`, `trajectory`.
- The `risk_breakdown` is the sum of the per-model breakdowns.
- The `trajectory` entry shape is `{unit_id, signal, from_state, to_state, outcome, at, skipped}` (`skipped` is the forward jump's passed-over gates, T3 #376).

## 7. What this set does not change

- The L1 substrate, recon, and analysis are out of scope (R4-5).
- The pod's binary terminal vocabulary, six-way termination, fixed caps, and experiment-log shape stay.
- The pod memory variant record shape stays.
- The runtime session seam, checkpointer, compaction, capability middleware, and tracing recipe stay.
- The hunting module's fail-open canon and atomic-write and bounded-store primitives stay.
- The attack-tree paradigm is not a compatibility contract (R1-1).
- The TBSG exploration stays a separate research item (`#371`).
- Alpha-omega stays deferred (`#355`); full CVSS base metrics stay deferred (`#368`).

## 8. Review checklist

The adversarial review must answer these questions with file and line evidence.

1. Does every ADR decision in section 3 appear in the named spec section?
2. Does any spec clause contradict the tools ADR or the ordering-halt ADR?
3. Does any spec leave a component ambiguous, or defer an impactful design decision to implementation?
4. Are all data structures and algorithms named or shape-specified?
5. Does every spec name the CONTEXT.md pattern it replicates, or the similar built component?
6. Does any living document still state a superseded verbatim from section 5?
7. Does any spec silently widen scope beyond section 7?
