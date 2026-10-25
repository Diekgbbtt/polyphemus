# Assertions - unit threat model redesign

## Amendment 2026-10-25: impact-first elicitation

The threat-model impact-elicitation workstream supersedes the likelihood-only risk score and the failure-mode artifact in this document.
The decisions are in `docs/design/threat-model-impact-elicitation-adr.md`; the component map is `docs/design/threat-model-impact-elicitation-impact-map.md`.
Where this document and the amendment disagree, the amendment wins.

- A threat carries `VC`, `VI`, and `VA` plus a literal end impact. The store computes `impact = 1 - (1-VC)(1-VI)(1-VA)`, the ordinal weight, and `threat risk = likelihood_weight * impact_weight`.
- The ranking and the dispatch buckets use the combined risk. The run record carries `impact_weights` and `impact_breakdown`.
- The `failure_modes` artifact, `Threat.failure_mode_refs`, and the pod `failure-mode` variant basis are removed. The modeller no longer judges technical feasibility; the hunter and the pod own the effective attempt.
- The trust procedure uses the four axes `identity`, `spatial`, `temporal`, and `controls_semantics`.
- The well-formedness phase runs between `VULNERABILITIES_WRITTEN` and `COMPLETED`. Its exit is one `wellformedness` note plus the `COMPLETED` write; a lower-gate write is the re-entry signal.
- Every vulnerability binds a suite class parent or leaf. Technique families are not classes. `suite_gap` is removed. Class findings are non-blocking.


**Scope:** system "the unit threat model redesign: the threat modeller and the threat-driven hunter" - issue [#373](https://github.com/Diekgbbtt/polyphemus/issues/373).
**Source:** S1 `hunting-67-threat-modeller-spec.md`, S2 `hunting-67-threat-model-artifact-spec.md`, S3 section 8, S4 section 14, S5 section 8; the implemented code on `feat/unit-threat-model`.
**Seams under assertion:** the threat model schema and store; the modeller gate tool and passive tracker; the run intake, accumulator, halt, and resume; the mover and threat dispatch predicate; the surfer and hunter payload; the hunter pass tracker, graph, and spec-set store; the pod reduced D4, INIT gate, runner, and triager; the REST perimeter and Postgres run rows; the eval translation; the retired-surface guards.

The integration predicates attach at the typed component seams.
The walkthroughs attach at the REST entry seam and read the terminal quantities from the real stores and the Postgres row.
Every expected value comes from the spec or a stated worked value, never from the code under test.

## Contract predicates (integration)

### A. Threat model schema, store, and checker

**C1 - Partial gate write.** Seam: `ThreatModelStore.write_sections` -> the model document.
Semantic: success and state monotonicity.
Input: `state=UNIT_TECHNICAL_SHARP`, `sections={technical_sharpening: ...}` for a bound `Service:slug:a`.
Observable: one model document in `produced/Service-slug-a/`; `state == UNIT_TECHNICAL_SHARP`; the section reads back; a later `TRUST_MODELLED` write advances the state and keeps the earlier section.
Yields: `tests/attack/test_threat_model_store.py`.

**C2 - Zero-threat completion is valid.** Seam: the COMPLETED commit -> the checker and the mover.
Semantic: empty-but-valid.
Input: a COMPLETED model with `threats=[]` and every necessary attribute present.
Observable: `validation.valid is True`; zero threat files; `read_threat_files == []`; `read_completed_units` contains the unit; the mover consumes the model with zero dispatches.
Yields: `tests/attack/test_threat_model_store.py`, `tests/attack/test_hunting_threat_dispatch.py`.

**C3 - Malformed write is rejected, not persisted.** Seam: `write_sections` -> the coded schema rejection.
Semantic: malformed.
Input: an unknown section key, a state outside the gate literals, and a section body of the wrong type, one at a time.
Observable: `ThreatModelDocumentError`/the coded rejection; the prior document is unchanged; no partial file lands.
Yields: `tests/attack/test_threat_model_store.py`.

**C4 - Unknown schema version is refused.** Seam: the model loader -> the version gate.
Semantic: malformed.
Input: a persisted document with `schema_version=999`.
Observable: `ThreatModelSchemaVersionError`; no model is returned; no migration is attempted.
Yields: `tests/attack/test_threat_model_store.py`.

**C5 - Referential integrity is a completion finding.** Seam: `check_completion` -> the validation finding lists.
Semantic: malformed/out-of-contract.
Input: a threat referencing a missing vulnerability; a trust agreement referencing a missing endpoint; a violation with an unresolved `transition_ref`.
Observable: `referential_errors` names each broken reference; `valid is False`; the store still commits the document (non-blocking checker).
Yields: `tests/attack/test_threat_model_store.py`, `tests/attack/test_hunting_threat_dispatch.py` for the transition ref.

**C6 - Assumption-to-threat closure.** Seam: `check_completion` -> `unclosed`.
Semantic: outlier (an assumption with no threat path).
Input: a model with an assumption and no threat that consumes it.
Observable: `unclosed` names the assumption; `valid is False`.
Yields: `tests/attack/test_threat_model_store.py`.

**C7 - Threat order and identity.** Seam: the COMPLETED normaliser -> the threat files.
Semantic: ordering.
Input: threats supplied out of rank order, with duplicate and non-canonical ids.
Observable: threat ids are `threat-1..n` in rank order; one file per non-`none` threat; the model's `risk_profile` uses the same order.
Yields: `tests/attack/test_threat_model_store.py`.

**C8 - Risk profile is store-computed, checker-recomputed.** Seam: the COMPLETED writer -> the risk profile.
Semantic: success and tamper detection.
Input: threats with likelihoods `none/low/medium/high/critical` and a model-authored total of 99.
Observable: the store writes `risk_profile.total = 0/1/2/3/4` summed; the checker reports the 99 as a recompute finding; weights and threshold are the exported constants.
Yields: `tests/attack/test_threat_model_store.py`, `tests/attack/test_run_lifecycle.py`.

**C9 - Collision-safe unit names.** Seam: the store's derived name -> two unit ids.
Semantic: concurrency/collision.
Input: two unit ids that sanitise to `Service-slug-a`.
Observable: the first keeps the name; the second gets `Service-slug-a-<8 hex>`; both documents read back under their own ids; no overwrite.
Yields: `tests/attack/test_threat_model_store.py`.

**C10 - Commit protocol and crash window.** Seam: the COMPLETED commit -> threat files then model.
Semantic: degradation (a failing model write after the threats).
Input: a write seam that raises after the threat files land.
Observable: the previous model state survives; the threat files are present or cleaned on the next lower-gate write; no half-committed model is consumable.
Yields: `tests/attack/test_threat_model_store.py`.

**C11 - Move-aware consume and consumed-identity no-op.** Seam: `consume_threat` / `consume_model_if_done` -> the mover.
Semantic: duplicate-idempotent.
Input: consume the last threat twice; then write the same unit identity again.
Observable: the model moves to `consumed/`; the second consume is a no-op; a write after the move returns the consumed path and does not recreate a produced document.
Yields: `tests/attack/test_threat_model_store.py`, `tests/attack/test_hunting_threat_dispatch.py`.

**C12 - Invalid or degraded model archived.** Seam: `archive_unit` -> `abandoned/`.
Semantic: degradation.
Input: a COMPLETED model with `validation.valid is False`; a non-COMPLETED pass.
Observable: the unit directory moves to `abandoned/`; `read_abandoned_units` lists it; `read_completed_units` does not; no threat dispatches.
Yields: `tests/attack/test_threat_model_store.py`, `tests/attack/test_threat_modeller.py`.

**C13 - Bounded notes.** Seam: the notes store -> the shared bound.
Semantic: malformed/out-of-range.
Input: a note body over the bound; a `phase_summary` note through the modeller notes tool.
Observable: the body is capped at the shared bound; `phase_summary` is refused with a coded rejection on the modeller surface; the hunter notes accept it.
Yields: `tests/attack/test_threat_modeller.py`, `tests/attack/test_hunter_memory.py`.

### B. Modeller gate tool, tracker, and inputs

**C14 - Gate write success and hint.** Seam: `hunts_store` write -> the model store and the tracker.
Semantic: success.
Input: `{state, sections}` for each of the five gates, in order, for a bound unit.
Observable: the model reaches COMPLETED; each response carries the next-state hint except the last; the tracker state matches the persisted state; the unit id is the bound one.
Yields: `tests/attack/test_threat_modeller.py`.

**C15 - Gate write error modes.** Seam: `hunts_store` write -> the coded rejection.
Semantic: malformed and out-of-contract.
Input: a missing `state`; an unknown state; a foreign section; a `unit_id` on the write; an empty `sections`.
Observable: `hunts_store_write_rejected` with `fields` naming the offending field; the store and tracker are unchanged; no hint is injected.
Yields: `tests/attack/test_threat_modeller.py`.

**C16 - Passive tracker and trail.** Seam: the tracker -> the gate writes.
Semantic: ordering and degradation.
Input: a lower-gate write after a higher gate; a forward jump; a repeated write.
Observable: the state never regresses; the lower write is a trail-only entry; the forward jump records the skipped states; the machine never rejects a tool call.
Yields: `tests/attack/test_threat_modeller.py`.

**C17 - Tool surface and notes refusal.** Seam: `build_modeller_tool_surface` -> the model-facing tools.
Semantic: out-of-contract.
Input: the built surface; a `phase_summary` notes write; a missing skill suite.
Observable: no `graph_view`, `kb_query`, or fault-KB aid; the notes tool refuses `phase_summary`; the skill binding records a gap and degrades fail-open; the HTTP/exec seams record per-call gaps on the outcome.
Yields: `tests/attack/test_threat_modeller.py`, `tests/attack/test_hunting_review_fixes.py`.

**C18 - Resume seed.** Seam: `arun_modeller_pass` -> an existing model.
Semantic: duplicate-idempotent.
Input: a pass started against a COMPLETED model; a pass started against a partial model.
Observable: the COMPLETED pass asks for no turn and re-authors nothing; the partial pass resumes at the persisted state; a fresh unit seeds no state.
Yields: `tests/attack/test_threat_modeller.py`.

**C19 - Provider failure is an interrupted run.** Seam: the pass -> `start_hunting`.
Semantic: degradation.
Input: a pass raising `ThreatModellerDegradedError` with a `ProviderUnavailableError` cause.
Observable: the run row ends `interrupted`; the stats carry the provider status and `quota_exhausted`; the sessions settle; the run is never `complete`.
Yields: `tests/attack/test_hunting_runtime.py`.

### C. Intake, run lifecycle, halt, and resume

**C20 - Intake ordering.** Seam: `read_intake`/`order_intake` -> the frozen order.
Semantic: ordering.
Input: an L1 snapshot with live L1 edges in both directions, a retired family edge, a System connected to two Services with overlapping endpoints, and equal-count ties.
Observable: live edges count both directions; retired families do not count; the System's endpoint count sums the distinct Services; ties break by aggregated endpoints then unit id; one entry per unit id.
Yields: `tests/attack/test_unit_intake.py`.

**C21 - Intake exclusions.** Seam: `freeze_intake` -> the run record.
Semantic: empty-valid, degradation, and the resume decision.
Input: a completed unit; a produced model under a `running`, `stopped`, resumable-`interrupted`, quota-terminal-`interrupted`, and unknown-status run; an abandoned model; a stale produced model.
Observable: completed -> excluded `completed`; running/stopped/resumable -> in flight; quota-terminal -> its model is archived and the unit retried; stale terminal -> archived and `stale` excluded; abandoned -> ignored and retried; each exclusion records its reason.
Yields: `tests/attack/test_unit_intake.py`, `tests/attack/test_hunting_run_lifecycle.py`, `tests/integration/test_unit_threat_model_contracts.py` (the real white-jotter-001 L1 read and ordering).

**C22 - Accumulator and halt.** Seam: `RiskAccumulator`/`ThreatModelRun` -> the run row.
Semantic: boundary (the inclusive threshold).
Input: units with likelihoods summing to `threshold-1`, `threshold`, and `threshold+1`.
Observable: the crossing unit completes and its model is dispatched; the next unit is never modelled; `blocked_unit` names it; the order is not re-sorted; the totals use the weights `0/1/2/3/4`.
Yields: `tests/attack/test_run_lifecycle.py`, `tests/attack/test_hunting_run_lifecycle.py`.

**C23 - Run record keys and trajectory.** Seam: `ThreatModelRun` -> the run row `stats`.
Semantic: success and shape.
Input: a halted run and a complete run.
Observable: exactly the fixed keys (`intake_order`, `intake_position`, `intake_excluded`, `risk_threshold`, `threshold_basis`, `risk_weights`, `risk_total`, `model_sums`, `halt`, `crossing_unit`, `blocked_unit`, `degraded_units`, `trajectory`, `run_stats`); the trajectory records the skipped states; a resume preserves them.
Yields: `tests/attack/test_run_lifecycle.py`.

**C24 - Commit order and crash adoption.** Seam: the model commit -> the run-record write.
Semantic: degradation.
Input: a unit model written, then a record write failure; a resume after a model committed before the record.
Observable: the record never carries a sum for a model that did not land; the resume adopts the committed model and recomputes the total; no stale total survives.
Yields: `tests/attack/test_hunting_run_lifecycle.py`.

**C25 - Resume and halted-resume.** Seam: `resume_run`/`_run_intake` -> the run row.
Semantic: duplicate-idempotent and ordering.
Input: a stored run record at position `k`; a halted record; a re-launch with the same run id.
Observable: the run re-enters at `k`, does not re-freeze or re-sort; a halted record models nothing and dispatches only; the same run's threats dispatch; a foreign run's do not.
Yields: `tests/attack/test_run_lifecycle.py`, `tests/attack/test_hunting_resume.py`.

**C26 - Resume decision table.** Seam: `resume_decision` -> the resume endpoint.
Semantic: every error mode.
Input: `stopped`; `interrupted` with `quota_exhausted=false` inside and outside the window; `true`; missing/unknown class; a malformed `retry_after_s`; a missing `finished_at`; `running`; `complete`; `failed`; an unknown status.
Observable: resumable only for `stopped` and the false-class after the window; the 60s default; the malformed hint takes the default; the missing `finished_at` is `timing_unknown`; every other row is terminal with its code.
Yields: `tests/attack/test_hunting_resume.py`.

**C27 - Resume claim and restore.** Seam: `claim_hunting_run_for_resume` -> the API.
Semantic: concurrency and degradation.
Input: two concurrent resumes; a resume while another run is live; an admission failure after the claim.
Observable: one 202 and one 409; the claim clears the pause keys and `finished_at`; an admission failure restores the prior status and pause keys; no `running` orphan remains.
Yields: `tests/project_management/test_hunting_api.py`, `tests/app/test_hunting_runs.py`.

### D. Threat dispatch, mover, and surfer

**C28 - Threat validity predicate.** Seam: `read_produced_inbox`/`threat_item` -> the mover and the work read.
Semantic: success, malformed, and cross-run.
Input: a valid threat; a malformed stem; a missing field; a foreign run id; an archived unit; a unit with an unreadable model.
Observable: one item per valid threat; the malformed/foreign/archived cases yield no item and are refused once; the work read and the dispatch read return the same decision; the model is not consumed for a looping unit.
Yields: `tests/attack/test_hunting_mover.py`, `tests/attack/test_hunting_threat_dispatch.py`.

**C29 - One threat, one hunter, one session id.** Seam: `surfer._threat_dispatch` -> the control plane.
Semantic: success and count.
Input: one produced threat; two produced threats.
Observable: exactly one hunter session per threat with id `hunting:<run_id>:hunt:<dispatch_id>`; the payload is materialised at dispatch; the threat moves on admission; the model moves with the last threat.
Yields: `tests/attack/test_hunting_threat_dispatch.py`, `tests/attack/test_hunting_surfer_tick.py`.

**C30 - Sequencing and the low-threat pause.** Seam: `sequence_dispatch`/`ProducedInbox` -> the dispatch set.
Semantic: ordering and restart.
Input: a critical/high/medium threat plus a low threat; the high one live; a fresh state after a restart.
Observable: the higher threat dispatches immediately; the low threat stays produced while the higher is produced or live; the pause is per tick; a restart with the higher file still produced holds the low; releasing the higher releases the low; a later high does not preempt admitted work.
Yields: `tests/attack/test_hunting_mover.py`, `tests/attack/test_hunting_threat_dispatch.py`.

**C31 - Malformed-threat non-wedge and zero-threat consume.** Seam: the produced read -> the consume and quiesce.
Semantic: outlier (an unreadable threat file; a model with no threats).
Input: a unit whose only threat is unreadable; a unit with no threats.
Observable: the unreadable file is refused once, stays produced, the model is consumed as the no-dispatch case, `run_work_remaining` is false and `is_run_quiesced` true; the zero-threat model is consumed with zero dispatches.
Yields: `tests/attack/test_hunting_threat_dispatch.py`.

**C32 - Quiesce and role gate.** Seam: `is_run_quiesced` -> the run terminal.
Semantic: boundary.
Input: a settled pass with no produced dispatchable threat and no live session; a stopped role gate; a foreign-run threat; a live higher session.
Observable: quiesce true only when the three clauses hold; the stopped gate pauses dispatch but not quiesce; a foreign threat does not hold quiesce; a live higher session holds it.
Yields: `tests/attack/test_hunting_surfer_tick.py`, `tests/attack/test_hunting_mover.py`.

**C33 - Hunter payload field set.** Seam: `materialise_hunter_payload` -> the hunter launch.
Semantic: shape and absences.
Input: a COMPLETED unit with a trust agreement, a fault, a vulnerability, both class fields, evidence with an HTTP artifact, a likelihood, and a confidence.
Observable: exactly the S2 8.2 fields; no failure modes, no narrowed vector, no `HuntConfig`, no pre-authored vector space; `baseline_ref` is an artifact id.
Yields: `tests/attack/test_hunting_threat_dispatch.py`, `tests/attack/test_hunting_agent_prompt.py`.

**C34 - Refusal log scope.** Seam: `log_refusal_once` -> the run.
Semantic: concurrency and duplicate-idempotent.
Input: the same refusal twice in one run; the same key in another project; a new run in the same project; a full log.
Observable: one line per key per run; the key includes the project; the log is bounded; it clears with the run; a new run can log again.
Yields: `tests/attack/test_hunting_review_fixes.py`, `tests/attack/test_hunting_mover.py`.

### E. Hunter state, graph, and spec set

**C35 - Pass signal acceptance.** Seam: `detect_phase_signal`/`detect_signal`/`advance_state` -> `HuntState`.
Semantic: success, forward jump, earlier signal, no signal.
Input: each of the declared exits from its own pass; a later pass signal; an earlier pass signal; an unrelated tool; a missing signal.
Observable: advance to the next pass; a later signal forward-jumps and records the skipped states; an earlier signal is trail-only and does not regress; no signal stays; the state is monotonic; the hint is the signalling pass's.
Yields: `tests/attack/test_hunter_state.py`.

**C36 - Graph terminal.** Seam: `route_supervise` -> END.
Semantic: boundary.
Input: a state below `complete`; the `complete` state; a no-signal stay.
Observable: END only on `complete`; the stay is a no-route `Command`; the graph never ends on a no-signal or a trail-only entry.
Yields: `tests/attack/test_hunter_graph.py`.

**C37 - Phase notes.** Seam: `phase_note_name`/the notes store -> the tracker.
Semantic: success and duplicate.
Input: a `phase_summary` note for each note exit; an `update` on a re-iteration; a `delete`; a note named for GENERATE/VERIFY/COMPLETE.
Observable: the name is `phase:<state>`; an update rewrites the one record; delete is refused; the non-note exits are no signal; the note kind is bound to the hunt key.
Yields: `tests/attack/test_hunter_memory.py`, `tests/integration/test_hunter_harness_memory_contracts.py`.

**C38 - Spec-set write and status lifecycle.** Seam: `write_specs` -> the spec folder.
Semantic: success, terminal, mixed, duplicate, consumed.
Input: an all-`hypothesised` set; a terminal `ratified`/`dropped` set; a mixed hypothesised+terminal set; a duplicate `spec_id`; a consumed identity.
Observable: the set persists under `test-specs/<hunt_key>/`; the terminal upserts in place; the mixed set is rejected; the duplicate raises `DuplicateSpecError`; the consumed identity is a no-op.
Yields: `tests/attack/test_hunter_memory.py`.

**C39 - Spec store key, file name, and path safety.** Seam: `spec_identifier`/`write_specs` -> the filesystem.
Semantic: malformed and out-of-contract.
Input: a keyword pair with unsafe characters; a `../` traversal; an empty keyword; a missing dispatch id.
Observable: the file is `<fault_keyword>_<strategy_keyword>.yaml` sanitised; traversal is refused; the key is derived from the bound dispatch id, never a request field.
Yields: `tests/attack/test_hunter_memory.py`, `tests/attack/test_hunter_tools.py`.

**C40 - Reduced D4 and provenance.** Seam: `TestImplementationSpec`/`skill_procedure_from_spec` -> the pod.
Semantic: success and out-of-contract.
Input: the six-field spec with a seven-field `SkillProcedure`; `testing_pattern`/`payload_vector_space`/`interpretation_guidance`; a missing procedure field.
Observable: the reduced spec round-trips; the retired fields are `extra_forbidden`; the provenance reads the typed procedure; the seven fields are the shared `spec_contract` fields.
Yields: `tests/attack/pod/test_spec_reads.py`, `tests/attack/pod/test_verification.py`.

**C41 - Pod dispatch gate.** Seam: the mover's spec read -> the surfer's pod dispatch.
Semantic: success, ordering, and no-verdict.
Input: a `ratified` spec; a `hypothesised` spec; a `dropped` spec; a consumed spec.
Observable: one pod session per ratified spec with id `hunting:<run_id>:pod:<dispatch_id>:<spec_id>`; no pod for a non-ratified or consumed spec; no verdict is derived.
Yields: `tests/attack/test_hunting_surfer_tick.py`, `tests/integration/test_hunting_wiring_mover.py`.

### F. Pod gate, runner, and triager

**C42 - INIT gate.** Seam: `validate_spec` -> the pod graph.
Semantic: success, malformed, and all-violations.
Input: a non-empty URL and one non-blank symptom; an empty URL; a blank symptom; both missing; the store metadata keys; a retired field; a mixed symptom type.
Observable: the valid spec passes; every violation is collected in one rejection; the gate rejects with zero tool calls; the store metadata is projected away at dispatch but the retired fields still reject; the mixed type is rejected.
Yields: `tests/attack/pod/test_verification.py`, `tests/integration/test_hunting_wiring_mover.py` C39.

**C43 - Probe authoring and no-probe terminal.** Seam: `author_probe_from_spec` -> the pod graph.
Semantic: success and outlier.
Input: a spec with a URL; a spec with a `baseline_ref`; a spec with neither; a later variant with no target identity.
Observable: at least one probe is authored; the baseline replay is emitted; no derivable probe lands `no-symptom-evidence` with `clean=false`, never `space-exhausted`; the later variant does not inherit a clean exhaustion.
Yields: `tests/attack/pod/test_symbolic.py`, `tests/attack/pod/test_graph.py`.

**C44 - Replay lineage.** Seam: the replay tool -> the capture plane.
Semantic: success and degradation.
Input: a captured baseline; a baseline with an unavailable body; a mutation; a replay from another project.
Observable: the new artifact carries `derived_from` and `replay_kind`; the baseline is unchanged; a bodyless replay is refused; a cross-project replay is `not_found`; the evidence is sanitized.
Yields: `tests/attack/pod/test_replay_tool.py`, `tests/e2e/test_pod_replay_lineage.py` (live).

**C45 - Triager basis.** Seam: `first_uncovered_gap`/`resolve_variant_decision` -> the variant.
Semantic: success, first gap, fallback, triggers, duplicate, empty.
Input: each of the ten basis conditions; two uncovered gaps; a fully covered procedure; a runner failure; a runner divergence; a duplicate (basis, spec); an empty `skill_procedure` field.
Observable: the first uncovered gap wins; a fully covered procedure mints `failure-mode`; the triggers mint their recovery bases; a duplicate is not re-minted and degrades to a terminal; an empty field is a skipped class (not an uncovered gap) and the variant provenance is preserved.
Yields: `tests/attack/pod/test_variant_basis.py`, `tests/attack/pod/test_variant_mint.py`.

**C46 - Pod terminal vocabulary.** Seam: the pod graph -> the export.
Semantic: boundary.
Input: a confirmed symptom; a clean no-symptom; a declined variant; a no-probe gap; an exhausted runner.
Observable: exactly `verified`/`unverified`/`declined`/`no-symptom-evidence` with the six terminal reasons; no new literal; the clean flag matches the branch.
Yields: `tests/attack/pod/test_graph.py`.

### G. REST perimeter, Postgres, and retired surface

**C47 - Run launch and guard.** Seam: `POST /projects/{p}/hunting` -> the run row.
Semantic: success, unknown, conflict, unavailable.
Input: a known project; an unknown project; a second live launch; the control plane absent.
Observable: 201 with one `running` row; 404 for unknown; 409 for a live run; 503 for the unavailable control plane; no orphan row on the refusal.
Yields: `tests/project_management/test_hunting_api.py`.

**C48 - Modeller-only launch and the retired hunt enqueue.** Seam: `POST /hunting/modeller`; `POST /hunting/hunt`.
Semantic: success and permanent-gone.
Input: a known project; a stale hunt-config body.
Observable: 202 `{component: "threat_modeller", ...}`; the hunt enqueue is 410 naming the threat replacement; no `hunt_configs` write.
Yields: `tests/project_management/test_hunting_api.py`, `tests/integration/test_hunting_wiring_rest.py`.

**C49 - Resume endpoint error modes.** Seam: `POST /hunting/{run}/resume` -> the row.
Semantic: success, unknown, conflict, unavailable.
Input: an unknown project; an unknown run; a non-resumable status; a lost claim; an admission failure; a resumable row.
Observable: 404/409/202 as specified; `Retry-After` in the window; the prior status restored on admission failure; no `running` orphan.
Yields: `tests/project_management/test_hunting_api.py`.

**C50 - Role and session names.** Seam: the provider/session helpers -> the runtime.
Semantic: success and retired.
Input: the role id; the session segment; an old `hunting_orchestrator` id; the old env key; the old API path.
Observable: `hunting_threat_modeller`/`threat-modeller`; no old alias; no fallback env; the old path 404; the new path 202.
Yields: `tests/test_llm_providers.py`, `tests/attack/test_threat_modeller_prompt.py`, `tests/project_management/test_hunting_api.py`.

**C51 - Retired surface is absent.** Seam: the source tree -> the guard.
Semantic: out-of-contract.
Input: a live import of `HuntConfig`, `DispatchResult`, `DeliveredCandidate`, `HypothesisVerdict`, `hunting_pod`, `fault_kb`, `fault_source`, `symptom_kb`, `fault_risk`, `specified`/`verified` status, `testing_pattern`/`payload_vector_space`/`interpretation_guidance`.
Observable: no live hit; the guard fails on a reintroduction; a historical doc with a supersession note is allowed.
Yields: `tests/eval/test_retired_vocabulary.py`, `tests/attack/test_fault_kb_disposition.py`.

**C52 - Fault-KB disposition.** Seam: the app boot -> the retired modules.
Semantic: retired.
Input: the app boot; `data/hunting/fault-kb.yaml`; the curation tools.
Observable: no boot consumer; the data and modules are gone; the ADR records the disposition; the guard test fails on a reintroduction.
Yields: `tests/attack/test_fault_kb_disposition.py`.

### H. Eval translation

**C53 - Eval setup shape.** Seam: `PreloadedArtifacts` -> the trial.
Semantic: success and malformed.
Input: `models`; the retired `configs` key; a bare string; a missing model.
Observable: `models` loads; `configs`/the bare string raises `SetupError` naming the replacement; a missing model fails loud.
Yields: `tests/eval/test_orchestrator_setup.py`, `tests/eval/test_orchestrator_premined_guard.py`.

**C54 - Pre-mined retarget.** Seam: `place_premined`/`retarget_premined` -> the run.
Semantic: success and cross-run.
Input: a placed threat-model unit under a synthetic source run id; a launched run id; a foreign model; a consumed artifact.
Observable: the placed model and every threat are rebound to the launched run id; the foreign model is untouched; the consumed artifact is untouched; the same-run threat dispatches; a different run id does not.
Yields: `tests/eval/test_orchestrator_trial.py`, `tests/attack/test_hunting_resume.py`.

**C55 - Eval predicate and evidence shape.** Seam: the eval predicate/evidence store -> the trial.
Semantic: success and retired.
Input: a produced threat file and a test spec; a stale `hunt_configs/` tree; a verdict row; a diagnosis row.
Observable: the gate counts threats/specs; a stale config tree blocks with the RETIRED message; a model alone does not satisfy; `web_vulnerability_class` + `fault` and the `threat` chain key; no `fault_class`.
Yields: `tests/eval/test_orchestrator_premined_guard.py`, `tests/eval/test_orchestrator_verdicts.py`.

## Walkthrough predicates (end-to-end)

### E1 - Whole pipeline from the modeller to the pod

**id:** E1.
**grounds:** S1 US1-4, 6-7, 14, 18, 21, 24; S3 US1-4, 8, 19, 25; S5 US1-8, 10.
**entry seam:** `POST /projects/{project_id}/hunting`.
**input:** a fresh project with one live L1 Service `Service:slug:a` (two endpoints on the target's host), the target reachable from Kali, a threshold above the unit's sum, and the real provider keys. The unit's model is authored by the real modeller; the threat is the real threat; the spec set is the real hunter's; the pod is the real `arun_pod`.
**live edge:** the LLM provider (the real gateway) and the `http-e2e-target` container at `172.28.0.20:80`; nothing inside this edge is substituted.
**path:** the API opens a `running` row; `start_hunting` freezes the intake (one unit); the modeller pass grounds on the projection, writes the five gates, and completes the model with one high threat; the surfer reads the threat, materialises the payload, dispatches one hunter; the hunter runs the pass sequence, writes the spec set, and ratifies the surviving spec; the surfer dispatches one pod; the pod passes the INIT gate, authors a probe, runs it against the target, and lands a real terminal; the run quiesces `complete`.
**terminal:** one `produced/Service-slug-a/Service-slug-a.yaml` with `state=COMPLETED`, `validation.valid=true`, one `risk_profile.total`; one threat consumed; one `test-specs/Service-slug-a__threat-1/` folder with the terminal spec set; one pod export; the run row `complete` with the fixed record keys; zero `abandoned/`.
**observed:** the REST launch/GET responses; the threat model store read-back; the threat files in produced/consumed; the hunter spec folder; the pod export; the `hunting_runs` row.
**yields:** `tests/e2e/test_unit_threat_model_walkthrough.py::test_E1_whole_pipeline`.
**live status (2026-10-20):** the worktree stack, the white-jotter-001 L1, and the target loaded; the run froze the four-unit intake in the expected order and failed at the first modeller turn because OpenCode Go rejects the main `.env` `API_KEY_OPENCODE_GO` with `api_key_expired`. The e2e scaffold now forces that key into the shared `polymerhus_gateway` store, recreates the app-minted virtual key, and preflights the Go session route; the E1 test skips on the rejected key instead of failing the stack.

### E2 - Progressive halt at the threshold

**id:** E2.
**grounds:** S1 US2-4, 16-17, 20, 33.
**entry seam:** `POST /projects/{project_id}/hunting`.
**input:** a fresh project with three L1 units ordered by live edges; the first two sums below the threshold and the second crosses it; the threshold and weights are stamped in the run.
**live edge:** the LLM provider and the target fixture.
**path:** the modeller models the first unit; the second crosses the inclusive threshold; the second completes and its threat dispatches; the third is never modelled; the run halts and quiesces.
**terminal:** two COMPLETED models (the crossing one valid); the third unit absent from `produced/`; the run record `halt=true`, `crossing_unit=<second>`, `blocked_unit=<third>`, `risk_total==threshold`, the weights and threshold; the crossing threat dispatched.
**observed:** the run record; the store; the dispatched session ids.
**yields:** `tests/e2e/test_unit_threat_model_walkthrough.py::test_E2_halt`.

### E3 - Operator resume of a stopped run

**id:** E3.
**grounds:** S1 US20; T11.
**entry seam:** `POST /projects/{project_id}/hunting/{run_id}/resume`.
**input:** a project with a run row `stopped` and a persisted intake record at position `k`, a produced in-flight model for the current unit, and one foreign-run threat file.
**live edge:** the LLM provider and the target fixture, for the resumed dispatch.
**path:** the operator resumes; the claim sets `running` and clears the pause keys; the run re-enters at `k`, adopts the model, recomputes the total, and dispatches the same-run threat; the foreign threat stays produced; the run quiesces.
**terminal:** the row `complete`; the same-run model consumed; the foreign threat still produced; the intake order unchanged; the total recomputed; no re-freeze.
**observed:** the resume 202; the run row; the store; the mover's produced/consumed read.
**yields:** `tests/e2e/test_unit_threat_model_walkthrough.py::test_E3_resume`.

### E4 - Low-threat pause and the model move

**id:** E4.
**grounds:** S1 7.6; S2 8.3-8.4.
**entry seam:** a produced COMPLETED model with a low and a high threat, then `POST /hunting`.
**input:** a model with `threat-1` high and `threat-2` low for the launched run; the high threat's hunter session live for a tick; a fresh state after a restart.
**live edge:** the LLM provider for the two hunter sessions; the target fixture.
**path:** the surfer dispatches the high threat; the low stays produced while the high is produced/live; after the high settles, the low dispatches; the model moves with the last threat.
**terminal:** the high threat consumed first; the low threat consumed second; the model in `consumed/`; no dispatch for the low before the high settles; a restart with the high file still produced holds the low.
**observed:** the session ids and their order; the produced/consumed threat files; the model path.
**yields:** `tests/e2e/test_unit_threat_model_walkthrough.py::test_E4_low_pause`.

### E5 - Pod INIT rejection and the no-probe terminal

**id:** E5.
**grounds:** S5 US8-11, 25-26.
**entry seam:** `POST /hunting` with a produced spec under the threat dispatch id, or the pod-only resume path.
**input:** a spec with an empty `target_identity.url` and one blank symptom; a well-formed spec with no derivable probe.
**live edge:** none for the rejection (the real pod gate); the target fixture for the no-probe case if a probe is derivable.
**path:** the surfer dispatches one pod; the INIT gate collects both violations and rejects with zero tool calls; a separately well-formed spec with no derivable probe reaches the runner and lands the no-probe terminal.
**terminal:** the rejection envelope names both fields and records zero calls; the no-probe spec lands `no-symptom-evidence` with `clean=false`; the run stays honest (no fabricated hunt).
**observed:** the pod export envelope; the call log; the run row.
**yields:** `tests/e2e/test_unit_threat_model_walkthrough.py::test_E5_pod_gate`.

### E6 - Triager first-gap variant

**id:** E6.
**grounds:** S5 US13-22.
**entry seam:** the pod runner's terminal + the triager decision.
**input:** a reduced D4 spec with a `skill_procedure` whose `pro_tips` field is empty and whose other fields are covered; a second lap with the same basis/spec.
**live edge:** the LLM provider for the triager turn; the target fixture for the runner.
**path:** the runner executes a stretch; the triager reads the typed procedure and the trail; the first uncovered gap wins; the variant is minted with that basis; a duplicate basis/spec is not re-minted and the pod terminates.
**terminal:** the variant's `declined_attribute` is the first gap basis; the spec carries the variant; the duplicate lap adds no variant; the terminal vocabulary is unchanged.
**observed:** the pod variant record; the experiment log; the terminal export.
**yields:** `tests/e2e/test_unit_threat_model_walkthrough.py::test_E6_triager`.

### E7 - Replay lineage on the capture plane

**id:** E7.
**grounds:** S5 US12; #196.
**entry seam:** the live Kali MCP capture/replay surface, driven by the production replay tool.
**input:** a safe authenticated POST, captured as an artifact; a reduced D4 spec with `provenance.baseline_ref` = the artifact id; a declared query mutation.
**live edge:** the `http-e2e-target` and the Kali MCP capture plane; no substitution.
**path:** the baseline is captured; the pod's replay tool executes the baseline with the mutation; the capture plane mints a new artifact; the pod records the observation.
**terminal:** the new artifact carries `derived_from`/`replay_kind=mutated`; the baseline is unchanged; the untouched attributes survive; a cross-project lookup is `not_found`; no secret leaks.
**observed:** the capture-plane artifacts; the pod observation.
**yields:** `tests/e2e/test_pod_replay_lineage.py` (restored #196 gate).

## Coverage map and carried items

- The contract predicates cover every seam named in the header.
  C1-C13: the store and checker.
  C14-C19: the modeller.
  C20-C27: the run lifecycle and resume.
  C28-C34: the threat dispatch and surfer.
  C35-C41: the hunter and spec set.
  C42-C46: the pod and triager.
  C47-C52: the REST/PG and retired surface.
  C53-C55: the eval.
- The walkthroughs cover the spec's operator-facing paths: the whole pipeline, the halt, the resume, the sequencing, the pod gate, the triager, and the replay lineage.
- Carried or bootstrap-dependent:
  - The eval full trial against the comfyui target is external to this worktree's local stack; it stays a recorded follow-up, not a local walkthrough.
  - The auto-resume health checker (T11 follow-up) is not built; E3 exercises the operator verb only.
  - The live provider key is the operator-supplied bootstrap: the main `.env` `API_KEY_OPENCODE_GO` is rejected by `https://opencode.ai/zen/go/v1` as `api_key_expired` even with the `x-opencode-session` header, so E1/E2/E3/E4/E6 skip until the operator replaces it; the scaffold forces the new key into the shared gateway store and preflights the session route.
  - The LLM-free integration seam (the real white-jotter-001 L1 intake, C20-C21) passes in `tests/integration/test_unit_threat_model_contracts.py`; E5/E7 do not need the model edge.
  - The `#196` replay gate requires the Kali MCP capture plane; it skips only with `KALI_HTTP_E2E_ALLOW_SKIP=1`.

## Integration amendments (2026-10-20)

These amendments record the dev-trunk integration decisions.
They do not change the C1-C55 predicates or the E1-E7 walkthrough terminals.

- The web-vulnerability suite seam now lists every suite leaf, not only the class parents.
  The class parent remains the value stored in `web_vulnerability_class`.
  The optional assumption check may load a class parent or a variant leaf.
- The threat modeller has an optional skill-assisted assumption check before saturation.
  The check is assumption-first: a leaf may suggest a trust assumption, but it never supplies the programming fault.
  The threat modeller writes no skill and no threat-payload skill field.
- The hunter may load a sibling leaf when the threat's class skill is silent on a slice assumption.
  The hunter keeps the threat's class and failure-mode slice.
- The pod runner may load a declared suite leaf when the D4 procedure excerpt is silent on a load-bearing assumption.
  The D4 `skills` field remains the pod runner's artifact-declared configuration.
- The dev Q4 application Overview remains on the hunter's first turn.
  The first-step message chains to the Overview message.
- The SkillEvolver controller is app-owned, not hunting-owned.
  It runs on the shared `skills` module, starts on project launch, and is listed and held by the project thread endpoint.
  It is outside every hunting run's quiesce.
- The dev prompt synergy analysis is `docs/design/unit-threat-model-prompt-synergy.md`.
