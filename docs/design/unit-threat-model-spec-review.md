# Unit threat model specification - adversarial review

> **Vocabulary note (2026-10-25).** The artifact called a **loop** in this historical document is now a **threat** in the module and the current documentation.

*Historical review snapshot (2026-10-18).*
It records the design review at `HEAD 454233c0`; the planner-era module names it cites were renamed by T10b #397.

*Review basis: worktree `/Users/diekgbbtt/.claude/worktrees/unit-threat-model`, branch `design/unit-threat-model`, `HEAD 454233c0`, working tree as read on 2026-10-18.
The reviewed set is S1-S5 plus the impact map.
The decision authority is the workbench plus the two ADRs, as the set states.
All line references are relative to the worktree root.
Only one file was written: this report.*

## Summary

The set is a serious synthesis.
It carries the big decisions: loop dispatch, retention-first drops, Design B, the pass chain, the reduced D4, and the INIT gate.
It keeps the as-built seams in view.
It is more concrete than the workbench.
It is not buildable as written.
The main claim fails: the five specs are not yet a complete contract for `/to-tickets`.
The artifact schema cannot represent its own intermediate states.
The hunter FSM cannot observe its GENERATE exit from a per-spec write.
The FSM ends the hunt on any non-signal turn.
The unit lifecycle has two permanent-exclusion dead ends: a degraded unit and a thin completed model.
Three contract contradictions remain: the risk profile has two authors, the `web vulnerability class` field contradicts R2-1, and the `skill_procedure` carrier is undefined.
Most of these need narrow edits.
The decision coverage is otherwise strong.

## Verdict

**FAIL, 8 blockers.**

A focused fix pass can convert the set to PASS WITH FIXES or PASS.
Do not send the set to `/to-tickets` until B1-B8 are resolved.

## Blockers

### B1 - The model schema cannot represent the intermediate gate states

**Finding.** The schema declares a complete `UnitThreatModel`.
Every section is required.
The store writes one section at a time.
It parses the document at every write.
At gate 1 the document has only `technical_sharpening`.
It cannot validate as `UnitThreatModel`.

**Evidence.**
- `docs/design/hunting-67-threat-model-artifact-spec.md:301-317`: `technical_sharpening`, `trust_model`, `assumptions`, `vulnerabilities`, `failure_modes`, `loops`, `risk_profile` are all required; only `validation` is nullable.
- `docs/design/hunting-67-threat-model-artifact-spec.md:173`: `extra="forbid"` at every level.
- `docs/design/hunting-67-threat-modeller-spec.md:208-213`: the store merges the section into the existing model document and rejects an unparseable write loudly.
- `docs/design/hunting-67-threat-model-artifact-spec.md:353-354`: a gate write merges its section and never replaces the document.

**Decision violated.** R2-11/Q12 (one generic store-write surface that extends the document at each gate) and R5-2/Q35 (parseability only at the write).
The spec cannot simultaneously parse the document as the declared model and accept a partial gate write.

**Fix.**
- Give every section a default empty container.
- Or persist a partial mapping.
- Validate the complete `UnitThreatModel` only at `COMPLETED`.
- State that the completion checker reports missing attributes, not the parser.
- Add a test: write gate 1, read it back, write gate 2, read it back.

### B2 - The GENERATE exit signal is not observable from a per-spec store write

**Finding.** S3 says the hunter writes one spec per `hunts_store` call.
S4 says the GENERATE exit is a write of the whole spec set, all `hypothesised`.
The first spec write satisfies the detector.
It advances the pass to WELL-FORMEDNESS before the set exists.

**Evidence.**
- `docs/design/hunting-164-state-graph-spec.md:407`: GENERATE exit is "the spec set, all with `status=hypothesised`".
- `docs/design/hunting-164-state-graph-spec.md:559-561`: the detector maps "a `hunts_store` write whose specs are all `hypothesised`" to `{kind: "spec_set_write", statuses: ["hypothesised"]}`.
- `docs/design/hunting-67-hunting-agent-spec.md:492`: "The write takes one `spec` payload object carrying `status` and the typed spec."

**Decision violated.** R8-2/Q44-Q46 (the GENERATE write is the proxy signal) and S3 8.7 (one spec per write).
The pass exit is either premature or unobservable, depending on which spec is taken as authoritative.

**Fix.** Choose one carrier.
State it in S3 and S4:
- (a) the hunter writes the whole set in one batched `hunts_store` call, with an amendment to S3 8.7;
- (b) the hunter writes a `phase:generate` note after the set write, and the note is the exit, with an explicit amendment to Q46a;
- (c) the set write carries a `spec_set_id` and a terminal set marker.
Option (b) is the cheapest and matches the other note-based exits.

### B3 - The tracker terminates on any turn without a signal

**Finding.** The graph topology ends the hunt when no signal is pending.
The signal-acceptance rule says no signal means stay.
The two clauses contradict each other.
Most turns carry no phase signal: reads, exec, KB queries, non-phase notes.
The graph would end on the first such turn.

**Evidence.**
- `docs/design/hunting-164-state-graph-spec.md:575`: `supervise --state complete or no signal--> END`.
- `docs/design/hunting-164-state-graph-spec.md:422`: "No signal: append nothing and stay."
- `docs/design/hunting-164-state-graph-spec.md:581-585`: `supervise` is the sole entry and routes to `detect` only when a signal is pending.

**Decision violated.** R8-2/Q44 and the no-block passive invariant (S4 14.2, S1 4.8).
The two clauses inside S4 contradict each other.

**Fix.** The terminal condition is `state == complete` only; a no-signal turn returns to `supervise` and waits.
Delete "or no signal", or scope it to an explicit hunt-settled event.

### B4 - A degraded unit's partial model permanently blocks the unit

**Finding.** The store writes the model document at every gate.
A unit that degrades after gate 1 leaves a produced model.
The next run skips an in-flight model.
The degraded path promises a retry because no completed model exists.
There is no delete or discard primitive.

**Evidence.**
- `docs/design/hunting-67-threat-modeller-spec.md:487`: a unit is skipped when its model is in flight in `produced/`.
- `docs/design/hunting-67-threat-modeller-spec.md:624-627`: a degraded unit writes no model, and a new run retries it because no completed model exists.
- `docs/design/hunting-67-threat-model-artifact-spec.md:142`: the model document is written at every gate.
- `docs/design/hunting-67-threat-model-artifact-spec.md:663-669`: the in-flight skip and "the earlier run must be resumed to drain its produced loops".

**Decision violated.** Q10/R2-9 (only completed models are excluded from intake) and S1 7.7's retry promise.
The two S1 clauses cannot both hold once a gate has written.

**Fix.** Define the degraded path's cleanup: remove or archive the unit directory on degradation, or make the in-flight skip conditional on the producing run being live or resumable, or add a store `discard` primitive.
State how a terminal earlier run's produced models are reclaimed.

### B5 - A thin or empty COMPLETED model is consumed and permanently excludes the unit

**Finding.** The completion checker is non-blocking.
The consumability rule keys only on `state == COMPLETED` and a present `loops` section.
The section may be empty.
A model with empty sections and an empty loops list is a zero-loop model.
The store writes it straight to `consumed/` and records zero dispatches.
The unit is then excluded from every later run.

**Evidence.**
- `docs/design/hunting-67-threat-model-artifact-spec.md:381-425`: the checker records `missing` and never blocks; "The model is consumable when `state == COMPLETED` and the loops section is present."
- `docs/design/hunting-67-threat-model-artifact-spec.md:145`: a zero-loop model is written directly to `consumed/` at `COMPLETED`.
- `docs/design/hunting-67-threat-model-artifact-spec.md:641`: a new run excludes a unit with a completed model.
- `docs/design/hunting-67-threat-modeller-spec.md:189`: "No fabricated result: an absent write means an absent artifact."

**Decision violated.** R5-2 (the necessary-attribute contract) and the honour clause above.
The checker's necessary attributes have no effect on consumability.

**Fix.** Make consumability require the necessary-attribute set, or at least one surviving loop and a non-empty technical sharpening.
Route a failed check to the degraded path (no `COMPLETED` write) instead of a completed empty model.
Add a test: a `COMPLETED` write with empty sections is refused or degraded, never consumed.

### B6 - The risk profile has two authors

**Finding.** One clause says the store computes the risk profile.
The same clause says the modeller does not author the total.
Another clause maps `risk_profile` into the modeller's `COMPLETED` section.
The checker compares the stored profile to a value the same store wrote.

**Evidence.**
- `docs/design/hunting-67-threat-modeller-spec.md:303`: the `COMPLETED` section is `failure_modes`, `loops`; "the store computes the risk profile".
- `docs/design/hunting-67-threat-modeller-spec.md:546-549`: "The store computes the `risk_profile` ... The modeller does not author the total."
- `docs/design/hunting-67-threat-model-artifact-spec.md:351`: the `COMPLETED` section is `failure_modes`, `loops`, `risk_profile`.
- `docs/design/hunting-67-threat-model-artifact-spec.md:508-509`: "The harness writes the total and the breakdown into the model's `risk_profile`."
- `docs/design/hunting-67-threat-model-artifact-spec.md:406`: the checker verifies the risk profile equals the harness-computed total.

**Decision violated.** The write contract of S1 5.1 (`{state, section}`) and R2-5/Q16 (the accumulator is harness-owned).
As written, the implementation must choose between two authors and the checker is tautological.

**Fix.** Remove `risk_profile` from the modeller's `COMPLETED` section map.
State that the store writes it after merging the loops and before the commit.
Make the checker recompute the profile from the stored loops and compare that value to the stored one.

### B7 - The `web vulnerability class` field contradicts R2-1/Q11

**Finding.** The decision says the stored `web vulnerability class` value must equal a skills-suite class directory name.
The spec makes `web_vulnerability_class` the canonical name.
It adds `suite_class` for the suite directory name.
This is a semantic swap of the decided field.
It is not an implementation detail.

**Evidence.**
- `docs/design/unit-threat-model-workbench.md:326`: "`skill class` is renamed `web vulnerability class` and its value must equal a skills-suite class directory name".
- `docs/design/unit-threat-model-workflow.md:107`: "The stored `web vulnerability class` value must equal a skills-suite class directory name."
- `src/polymerhus/attack/hunting/CONTEXT.md:26`: the same rule.
- `docs/design/hunting-67-threat-model-artifact-spec.md:249-251`: `web_vulnerability_class: str`, `suite_class: str = ""`, `suite_gap: bool = false`.
- `docs/design/hunting-67-threat-modeller-spec.md:349-351`: "The stored `web_vulnerability_class` is the canonical name. The stored `suite_class` is the suite directory name."

**Decision violated.** R2-1, R2-10, Q11/Q14.
The impact map claims R2-1 is used at S2 4 and 5; it is reinterpreted there without an amendment.

**Fix.** Record an explicit amendment to R2-1/Q11 and the glossary: `web_vulnerability_class` is the canonical class, `suite_class` is the suite directory name, and `suite_gap` is the exception.
Update `unit-threat-model-workbench.md:326`, `unit-threat-model-workflow.md:107`, and `CONTEXT.md:26` in the same change.
Alternatively, keep the decided single field and add the canonical name as a separate field.

### B8 - The `skill_procedure` carrier is undefined, so the triager's procedure diff is unimplementable

**Finding.** The triager's new variant algorithm reads a checklist with seven procedure sections.
The checklist comes from `spec.provenance["skill_procedure"]`.
The triager tests seven gap classes in table order.
No spec defines the carrier type, the seven section names, the author, the authoring rule, or the bound.
The hunter is told only that provenance carries a bounded excerpt.

**Evidence.**
- `docs/design/hunting-67-hunting-agent-spec.md:455-457`: provenance carries "the bounded `skill_procedure` excerpt for the pod's triager".
- `docs/design/hunting-67-test-executor-pod-spec.md:331`: the same.
- `docs/design/hunting-67-test-executor-pod-spec.md:419-424`: "Read the skill procedure checklist from `spec.provenance["skill_procedure"]`. The checklist has the seven procedure sections. ... Test the seven gap classes in the table order."
- `docs/design/hunting-67-test-executor-pod-spec.md:398-415`: ten basis literals, the first seven procedure gaps.
- `docs/design/hunting-67-hunting-agent-spec.md:444-457`: provenance is a plain `dict`; no shape.

**Decision violated.** R8-3/Q48 (the variant minting is in scope and deterministic) and the concreteness standard.
The hunter cannot author a checklist it is not told to author; the triager cannot map seven gap classes to seven unknown sections.

**Fix.** Define a typed `SkillProcedure` with seven named sections, a per-section coverage field (a boolean or an executed-action list), and a byte bound.
Define who authors it (the hunter, from the loaded class skill) and the authoring rule.
Define the mapping from each gap class to its section.
Add the shape to S3 8.6 and S5 8.4/8.6, with a test for the first-uncovered rule.

## High

### H1 - The supersession markers in S3, S4, and S5 are incomplete

**Finding.** The old text is retained for history.
Several sections still read as current.
No marker covers them.
A reader can still trust the old input contract, the old FSM, and the old typed surface.

**Evidence.**
- `docs/design/hunting-67-hunting-agent-spec.md:10-11`: the marker supersedes 1.3, 1.4, 1.6, section 2, and the D4 assertions in section 6.
  Sections 1.1, 1.2, 1.5, 1.7-1.9, 3, 4, and 5 still name `HuntConfig` as the hunter input (`:24`, `:28`, `:51`, `:109-111`, `:123`, `:131-133`, `:152`).
- `docs/design/hunting-164-state-graph-spec.md:5`: the marker supersedes 2.3, 2.4, 3, 5, 6, and 11.
  Section 2.1 still presents `hypothesised_faults`, `verified_faults`, `ratified_specs`, and `current_fault` as the semantic state (`:48-49`).
  Section 4 still presents the old status-transition graph (`:130-133`).
  Section 12 still presents the fault statuses as the reviewer's state (`:304-305`).
- `docs/design/hunting-67-test-executor-pod-spec.md:11`: the marker supersedes the D4 base, the testing-pattern clause, the empty-payload-vector outlier, and the variant-minting clauses.
  Section 2 still says an empty payload vector lands `space-exhausted` (`:111`).
  Section 6 still has C9 (declined attribute), C11 (empty payload vector), and E1-E4 (the `HuntConfig` chain) as live assertions (`:196-198`, `:208`, `:220-236`).
  Section 1.7 still says the parent consumes the pod result for the hypothesis verdict (`:75`), while S3 8.7 says the hunter derives no verdict (`:516`).

**Decision violated.** The review standard that a living contract must not present a superseded version as current.
The impact map's register records only a subset of these lines (`unit-threat-model-spec-impact-map.md:178-180`, `:185-187`).

**Fix.** Extend each marker to every section that names the retired input, FSM, or typed surface, or add a one-line "historical" note at the head of each affected section.
For S3, list 1.1, 1.2, 1.5, 1.7-1.9, 3, 4, 5.
For S4, list 2.1, 4, 12.
For S5, list 1.7, 2, 4.1, 6.

### H2 - The workbench still contradicts the specs, and the impact map claims it was fixed

**Finding.** The impact map says the workbench's "ADR-unwritten" and "materialisation-continues" lines were fixed.
They were not fixed.

**Evidence.**
- `docs/design/unit-threat-model-spec-impact-map.md:161`: "Living sections: exec-budget-open, ADR-unwritten, and materialisation-continues lines fixed in this spec phase."
- `docs/design/unit-threat-model-workbench.md:300`: "The ordering-halt coupling gets its own ADR (declared; unwritten, on the R4-2 list)".
- `docs/design/unit-threat-model-workbench.md:358`: "The ordering-halt coupling ADR is declared (R1-4) and still unwritten (R4-2)."
- `docs/design/unit-threat-model-workbench.md:532`: "the ordering-halt coupling ADR is declared (R1-4, R2-5) and still unwritten".
- `docs/design/unit-threat-model-workbench.md:369`: "the materialisation facet continues to serve the hunter side as today".
- `docs/design/unit-threat-model-workbench.md:793`: "the hunter-side materialisation grounding stays, flagged as possible debt - R2-16".
- The specs retire materialisation (`hunting-67-hunting-agent-spec.md:524-528`).

**Decision violated.** R4-2/Q60 (the workbench is the living decision record) and Q39/R2-16.
The authority now contradicts the specs, and the map's traceability claim is false.

**Fix.** Update the five workbench lines to point at the written ADR and the Q39 retirement.
Treat the workbench fix as part of this spec phase, as the map says, or change the map's action to "build" and stop claiming it is done.

### H3 - R8-1 items are omitted: `variants` and the discipline paragraph

**Finding.** R8-1 says `variants` stay, reframed as a combination of skills-ontology entities.
The reduced D4 surface in S3 and S5 does not include `variants`.
Neither spec lists it among the retired fields.
R8-1 also says the mock's end discipline paragraph extends the wider discipline paragraph in the current prompt.
S3 8.5 has no discipline item.

**Evidence.**
- `docs/design/unit-threat-model-workbench.md:653`: "`variants` stay variants, reframed as a combination of the subset of entities of the skills ontology".
- `docs/design/unit-threat-model-workbench.md:636`: "the mock's end discipline paragraph extends the wider discipline paragraph already present in the current system prompt".
- `docs/design/hunting-67-hunting-agent-spec.md:444-459`: the reduced surface lists `target_identity`, `verification_symptoms`, `assumptions`, `rationale`, `parent_spec_ref`, `provenance`; the retired fields are `payload_vector_space`, `interpretation_guidance`, `testing_pattern`.
- `docs/design/hunting-67-test-executor-pod-spec.md:309-333`: the same.
- `docs/design/hunting-67-hunting-agent-spec.md:350-440`: the required prompt clauses; no discipline paragraph.

**Decision violated.** R8-1.
A reader cannot tell whether `variants` was subsumed by the spec set or silently deleted, and the prompt work phase is not told to extend the discipline paragraph.

**Fix.** Either add `variants` to the D4 surface with the decided semantics, or record an explicit amendment to R8-1 that the hunter's variants are now the spec set itself and the pod's `VariantSpec` is the only variant record.
Add the discipline paragraph to S3 8.5's required-clause list.
Do not leave either item implicit.

### H4 - The loop's confidence degree is omitted from the score

**Finding.** The workflow and R5-2 say the loop's confidence degree is one factor of the risk score.
S2's scoring section lists four CVSS-inspired factors.
It never mentions confidence as a factor.

**Evidence.**
- `docs/design/unit-threat-model-workflow.md:39`: "it is one factor of the loop's risk score".
- `docs/design/unit-threat-model-workflow.md:46`: "the loop's confidence degree is one factor of the score".
- `docs/design/unit-threat-model-workbench.md:575`: "the loop is authored on its confidence degree (R6-1), which is one factor of the risk scoring".
- `docs/design/hunting-67-threat-modeller-spec.md:383-386`: "It is one factor of the risk score."
- `docs/design/hunting-67-threat-model-artifact-spec.md:478-497`: the four factors only.
- `docs/design/hunting-67-threat-model-artifact-spec.md:501-509`: the total sums weights only.

**Decision violated.** R6-1/Q35 and Q33.
The spec records `Loop.confidence` but gives it no role in the class assignment or the sum.

**Fix.** State how confidence enters the LLM's class assignment (for example, an ASSUMED claim may not be scored above medium), or record an amendment that the confidence degree is retained for audit only and is not a score factor.
The current text says both.

### H5 - The replay baseline carrier is lost

**Finding.** `payload_vector_space.request_ref` is retired.
The replacement is "when the hunter names an HTTP-history artifact in the rationale or provenance".
No typed field carries the artifact id.
The pod must parse free text.
The canonical tool descriptions still teach the retired field.

**Evidence.**
- `docs/design/hunting-67-test-executor-pod-spec.md:367-370`: "When the hunter names an HTTP-history artifact in the rationale or provenance, the runner may use `replay` with that id."
- `docs/design/hunting-67-hunting-agent-spec.md:455-457`: provenance carries `loop_id`, `unit_id`, `web_vulnerability_class`, `suite_class`, `skill_procedure`; no artifact ref.
- `src/polymerhus/attack/hunting/http_history_contract.py:74`, `:94`, `:113`: the canonical descriptions teach `payload_vector_space.request_ref`.
- `src/polymerhus/attack/hunting/prompts/pod-runner.md:9`: the runner prompt names `payload_vector_space.request_ref`.

**Decision violated.** S5 story 12 ("the replay capability stays available") and the #196 capture contract.
The capability is not contractually available.

**Fix.** Add a typed `baseline_ref` (or `provenance.http_artifact_ref`) to the D4 and the loop payload, and state that the runner uses it for `replay` when present.
Rewrite the three canonical descriptions and the pod-runner prompt in the same change.

### H6 - The failure-mode fallback references material the pod never receives

**Finding.** The triager's fallback step reasons on the additional observable failure modes the trust agreement could yield.
The triager's context is the note, the log, the base spec, and the skill excerpt.
The failure modes and the trust agreement are excluded from the pod contract.

**Evidence.**
- `docs/design/hunting-67-test-executor-pod-spec.md:426-427`: "reason on the additional observable failure modes the trust agreement could yield".
- `docs/design/hunting-67-test-executor-pod-spec.md:433`: the triager's context is the note, the filtered log, the base spec, and the skill excerpt.
- `docs/design/hunting-67-threat-model-artifact-spec.md:600-605`: the payload carries no failure modes and no narrowed vector.
- `docs/design/hunting-67-hunting-agent-spec.md:449-450`: `verification_symptoms` are the only failure-mode material the pod holds.

**Decision violated.** R3-8/Q30 (failure modes are never fed forward) and R8-3 (the fallback is symptoms-based).
The wording imports the modeller's failure-mode space into the pod.

**Fix.** Restate the fallback in terms of `verification_symptoms` and the spec's assumptions, which the pod does hold.
If the trust agreement is genuinely needed, add it to the pod payload as an explicit exception to R3-8, and record that amendment.

### H7 - S4's config lifecycle line contradicts S2 and the retirement of `HuntConfig`

**Finding.** S4 says the config lifecycle is unchanged.
S2 says the retired `HuntConfig` entity is not replaced by a config lifecycle.
S2 also says the only status vocabulary is the hunter spec set's.

**Evidence.**
- `docs/design/hunting-164-state-graph-spec.md:464`: "The config lifecycle is unchanged: `hypothesised -> ratified | dropped`."
- `docs/design/hunting-67-threat-model-artifact-spec.md:453`: "The retired `HuntConfig` entity is not replaced by a config lifecycle; the only status vocabulary in this change is the hunter spec set's."
- `docs/design/hunting-67-hunting-agent-spec.md:519-520`: "The hunter's store key, folder, and session id no longer use a `fault_key` or a `HuntConfig`. The old per-config memory layout is superseded."

**Decision violated.** R2-4/Q19 and Q52.
There is no config entity left to have a lifecycle.

**Fix.** Delete the line or replace it with: "The hunt-config lifecycle is retired with `HuntConfig`; the only status vocabulary is the hunter spec set's `{hypothesised, ratified, dropped}`."

### H8 - Resume does not record the position, and the accumulator can be stale after a crash

**Finding.** The ADR requires a resumed run to re-enter at the recorded position with the persisted accumulator.
The run record has no position key.
The accumulator updates after the model commit.
A crash between the commit and the run-record update leaves `risk_total` stale.
The resumed run can then model past the threshold.

**Evidence.**
- `docs/design/unit-threat-model-ordering-halt-adr.md:29`: "A resumed run re-enters at the recorded order position with the persisted accumulator state."
- `docs/design/hunting-67-threat-modeller-spec.md:594-600`: the resume reads `risk_total`, `intake_order`, and the files; no position.
- `docs/design/hunting-67-threat-modeller-spec.md:576-590`: the run record keys have no position or cursor.
- `docs/design/hunting-67-threat-model-artifact-spec.md:646-659`: the same keys.
- `docs/design/hunting-67-threat-modeller-spec.md:559`: the check runs immediately after the `COMPLETED` write.
- `docs/design/hunting-67-threat-modeller-spec.md:725`: the accumulator updates after each `COMPLETED` write.
- `docs/design/hunting-67-threat-model-artifact-spec.md:660-661`: the run record survives a restart.

**Decision violated.** Ordering-halt ADR decision 5 and R2-5/Q16.
The audit trail cannot reconstruct the resume point, and the budget can be exceeded after a crash.

**Fix.** Add `intake_position` (the last completed unit index or the next unit id) to the run record.
Define the commit order between the model document and the run-record update, and make resume recompute `risk_total` from `model_sums` or the store.
State whether a halted run is resumable and what a resumed run does when `risk_total >= threshold`.

### H9 - The schema's referential integrity is incomplete

**Finding.** `Fault` has no id.
`Vulnerability.fault_ref` and `Loop.fault_ref` point at "a fault".
The checker resolves `fault_ref` to an assumption instead.
`TrustAgreement` has no reference to the interface agreements it translates.
The payload materialiser must include the interface agreements referenced by the trust agreement.
Transition source and target are not checked.

**Evidence.**
- `docs/design/hunting-67-threat-model-artifact-spec.md:234-236`: `Fault` has only `label` and `description`.
- `docs/design/hunting-67-threat-model-artifact-spec.md:248`, `:279`: `fault_ref`.
- `docs/design/hunting-67-threat-model-artifact-spec.md:410`: "Every `fault_ref` resolves to an assumption."
- `docs/design/hunting-67-threat-model-artifact-spec.md:191-196`: `TrustAgreement` has `boundary`, `statement`, `confidence`, `evidences`; no agreement refs.
- `docs/design/hunting-67-threat-model-artifact-spec.md:591`: "the interface agreements referenced by the trust agreement".
- `docs/design/hunting-67-threat-model-artifact-spec.md:408-413`: the referential checks omit transition source and target.

**Decision violated.** The concreteness standard for data structures and the map-back contract (R3-8).
The payload materialiser cannot resolve the references it is told to use.

**Fix.** Give `Fault` an `id`, make `fault_ref` point at it, and add a checker rule.
Add `interface_agreement_refs` to `TrustAgreement`.
Add transition source and target checks.

### H10 - The modeller's "trail" has no home

**Finding.** The monotonicity rule says a lower-gate write records the earlier signal as trail-only material.
The forward-jump rule records skipped states in the trail.
The model schema has no trail field.
The run record has no trail key.

**Evidence.**
- `docs/design/hunting-67-threat-modeller-spec.md:306-309`: "The harness accepts a forward jump and records the skipped states in the trail."
- `docs/design/hunting-67-threat-model-artifact-spec.md:339`: "The harness tracker records the earlier signal as trail-only material."
- `docs/design/hunting-67-threat-model-artifact-spec.md:301-317`: no trail field.
- `docs/design/hunting-67-threat-modeller-spec.md:576-590`: no trail key.

**Fix.** State where the trail lives (the run record, the model's `validation` record, or a separate trajectory log), what an entry contains, and whether it is persisted.
If the modeller's tracker has no trail, delete the claims.

### H11 - The impact map's ledger omits most of the build surface

**Finding.** The ledger is document-only.
Even so, it omits code modules, prompts, tests, data files, and an operator doc that the change will touch.
The review brief asked for the code, prompts, tests, docs, and data files.

**Evidence.**
- `docs/design/unit-threat-model-spec-impact-map.md:126-161`: the ledger.
- Missing code: `src/polymerhus/attack/hunting/hunter_state.py`, `hunter_graph.py`, `hunter_tools.py`, `hunt_store.py`, `hunter_memory.py`, `hunting_agent.py`, `hunting_pod.py`, `surfer.py`, `mover.py`, `runtime.py`, `actors.py`, `pod/types.py`, `pod/verification.py`, `pod/graph.py`, `pod/agents.py`, `pod/symbolic.py`, `pod/pod_memory.py`, `http_history_contract.py`.
- Missing prompt: `src/polymerhus/attack/hunting/prompts/pod-runner.md` (`:9` names `payload_vector_space.request_ref`).
- Missing tests: 28 files match the changed vocabulary (`tests/attack/test_hunter_state.py`, `tests/attack/pod/test_verification.py`, `tests/e2e/test_test_executor_pod_walkthrough.py`, and others).
- Missing data: `data/hunting/fault-kb.yaml` and the modules `fault_kb.py`, `fault_source.py`, `symptom_kb.py` (the materialisation retirement has no stated module disposition).
- Missing docs: `eval/OPERATOR.md:565-566` (the oracle's D4 list), `docs/design/hunting-304-kb-degradation-guard-adr.md:14`, `docs/design/hunting-84-assertions.md:51-52`, `docs/design/hunting-84-regrounding-decisions.md`, `docs/design/hunting-67-per-agent-specs-decisions.md` (no supersession note), `docs/design/modelling-trust-boundaries-notes.md`, `docs/design/modelling-dynamic-states-trust-notes.md`.

**Fix.** Add the missing rows with an owner and an action, or state that the ledger is intentionally document-only and add a second code/test ledger.
The two modelling-notes documents need an explicit disposition because R2-12 removes them from production.

### H12 - The traceability table's section pointers are stale

**Finding.** The table points at sections that do not carry the decision.
The pattern is systematic.
The section numbers were probably not re-checked after the specs were finalised.

**Evidence and corrections.**
- `unit-threat-model-spec-impact-map.md:90`: R3-3 points at S2 5.3, which is "State and monotonicity"; the evidence rules are S2 2.3 and 5.2.
- `unit-threat-model-spec-impact-map.md:104`: R6-1 points at S2 5.3; the confidence degree is S2 2.3 and 5.2.
- `unit-threat-model-spec-impact-map.md:111`: Q52 points at S2 6.1, which is "The loop"; the state vocabulary is S2 6.2.
- `unit-threat-model-spec-impact-map.md:93`: R3-6/Q55-Q57 points at S1 6.1; termination is S1 6.8 and the probe rules are S1 5.4.
- `unit-threat-model-spec-impact-map.md:87`: R2-17 points at S1 6.1; the cadence is telemetried in S1 4.5.
- `unit-threat-model-spec-impact-map.md:81`: R2-11 points at S2 5.7, which is the completion checker; the write tool is S2 10.3.
- `unit-threat-model-spec-impact-map.md:105`: R6-2/Q36 points at S3 8.3, which is user stories; the contract is S3 8.2 and 8.6.
- `unit-threat-model-spec-impact-map.md:106-107`: R6-3/Q37 and R7 point at S3 8.4; the structural limitation and the no-payload-completeness rule are S3 8.5 and 8.6.
- `unit-threat-model-spec-impact-map.md:108`: R8-1 points at S3 8.1, which is the problem statement; the prompt decisions are S3 8.5.
- `unit-threat-model-spec-impact-map.md:49`: LACK-1 points at S1 6.5, which is the drop rule; LACK-1 is S1 5.4.
- `unit-threat-model-spec-impact-map.md:68`: R1-1 points at S2 1, which never states the attack-tree position.
- `unit-threat-model-spec-impact-map.md:80`: R2-9 points at S2 9; consumption is S2 8.4.
- `unit-threat-model-spec-impact-map.md:78`: R2-6 points at S1 7.3 and 7.6; quiesce is S2 8.4.
- `unit-threat-model-spec-impact-map.md:86`: R2-16 points at S1 5.6, which withdraws the modeller's fault-KB aid; the hunter-side materialisation retirement is S3 8.8.
- `unit-threat-model-spec-impact-map.md:118-124`: the risk-scoring rows point at S2 7.3 and 7.4 for the factors and the breakdown, which are S2 7.2 and 7.3; the `none` dispatch row points at S2 6.2, which is the state vocabulary.

**Fix.** Re-check every row against the final section headings and add the actual section for each.
Add a test to the map's own review checklist: a link check against the headings.

### H13 - Note names and status literals collide across S3/S4, and WELL-FORMEDNESS drops are ambiguous

**Finding.**
(a) The note name uses `phase:well-formedness` with a hyphen.
The `HunterPass` literal is `well_formedness` with an underscore.
The detector maps `phase:<phase>` directly to a `HunterPass`.
The WELL-FORMEDNESS exit cannot be parsed as written.
(b) The WELL-FORMEDNESS pass may drop specs.
`dropped` is defined as the terminal declass at VERIFY-CLAIMS.
A drop write during WELL-FORMEDNESS would be read as the terminal signal.
It would skip VERIFY-CLAIMS.

**Evidence.**
- `docs/design/hunting-164-state-graph-spec.md:454`: `phase:well-formedness`.
- `docs/design/hunting-164-state-graph-spec.md:446-449`: the literal is `well_formedness`.
- `docs/design/hunting-164-state-graph-spec.md:559`: the detector maps `phase:<phase>` to a `HunterPass`.
- `docs/design/hunting-67-hunting-agent-spec.md:418-419`: WELL-FORMEDNESS may "merge entries or drop them".
- `docs/design/hunting-67-hunting-agent-spec.md:462-466`: `dropped` is "the declassed spec at the terminal write".
- `docs/design/hunting-164-state-graph-spec.md:561`: a write whose specs are `ratified` or `dropped` is the terminal signal.

**Fix.** Make the note name use the state literal (`phase:well_formedness`) or state the normalisation rule in the detector.
Define a separate mechanism for a well-formedness merge/drop (for example, the set is rewritten with no status change, or a `well_formedness_drop` note), so the terminal status is only written at VERIFY-CLAIMS.

## Medium

### M1 - The run-record key set is incomplete and the run-level breakdown is undefined

**Finding.** S2 7.4 requires the threshold basis to be recorded, but neither key list includes it.
S1 and S2 include `degraded_units`, but the impact map's fixed key list omits it.
The run-level `risk_breakdown` has no stated derivation (per-unit sum? per-model breakdown?).

**Evidence.**
- `docs/design/hunting-67-threat-model-artifact-spec.md:529`: "The run records the threshold and its basis (`default` or `override`)."
- `docs/design/hunting-67-threat-model-artifact-spec.md:646-659`: no `threshold_basis`.
- `docs/design/hunting-67-threat-modeller-spec.md:576-590`: no `threshold_basis`.
- `docs/design/hunting-67-threat-modeller-spec.md:586`: `degraded_units`.
- `docs/design/unit-threat-model-spec-impact-map.md:226`: no `degraded_units`.
- `docs/design/hunting-67-threat-model-artifact-spec.md:653`: `risk_breakdown` with no shape.

**Fix.** Add `threshold_basis` and `degraded_units` to both key lists.
Define the run-level breakdown as the sum of the per-model breakdowns and state the shape.

### M2 - The read payload and the COMPLETED section shape are undefined

**Finding.** The store tool accepts `cmd: read | write`, but the read payload is only described as "a requested section" and "an optional unit id".
The write payload's `section` is singular, but the COMPLETED state maps to three sections.

**Evidence.**
- `docs/design/hunting-67-threat-modeller-spec.md:197-220`: the write payload is `{state, section}`; the read "returns the current model, or a requested section"; a read "may name another unit id".
- `docs/design/hunting-67-threat-model-artifact-spec.md:343-355`: the COMPLETED section maps to `failure_modes`, `loops`, `risk_profile`.
- `docs/design/hunting-67-threat-model-artifact-spec.md:717-722`: the read accepts an optional unit id; no payload shape.

**Fix.** Define the read payload (`cmd`, optional `unit_id`, optional `section`) and the write payload's `section` as a mapping keyed by section name.
Remove `risk_profile` from the modeller's map (see B6).

### M3 - The loop-id assignment algorithm is underdefined

**Finding.** The store owns the loop id, the list order is the rank order, and ties preserve the write order.
If the modeller writes loops out of order, the spec does not say whether the store sorts and renumbers, or rejects, or leaves the ids mismatched.

**Evidence.**
- `docs/design/hunting-67-threat-model-artifact-spec.md:372-375`: "The loop ids are `loop-1`, `loop-2`, ... in ranked order. ... Ties preserve the modeller's write order. The list order is the rank order."
- `docs/design/hunting-67-threat-model-artifact-spec.md:405`: the checker verifies the order is non-increasing.
- `docs/design/hunting-67-threat-modeller-spec.md:360-361`: "Rank the surviving loops by likelihood. Assign loop ids in ranked order."

**Fix.** State the algorithm: stable sort by weight descending, then renumber `loop-1..n`; the checker verifies the result.
State whether a wrong modeller order is a finding or is normalised.

### M4 - The System tie-break's connectivity predicate is undefined

**Finding.** For a System, the aggregated endpoint count is the sum of the `AGGREGATES` out-degree of the Services "connected to it".
"Connected" is not defined (any live L1 family? a specific family?), and multiple edges between the same pair can double-count.

**Evidence.**
- `docs/design/hunting-67-threat-modeller-spec.md:521-524`.
- `docs/design/unit-threat-model-workbench.md:298`.

**Fix.** Define connectivity as the distinct Services reachable by any live L1 edge, and deduplicate by Service id.

### M5 - The unit-name collision policy is absent

**Finding.** `<unit_name>` sanitises `:` and `/` to `-`.
Two distinct unit ids can sanitise to the same name, and the store would overwrite one model directory with another.

**Evidence.**
- `docs/design/hunting-67-threat-model-artifact-spec.md:137`.
- `docs/design/hunting-67-threat-model-artifact-spec.md:116-120`: the model id is authoritative and the file name is derived.

**Fix.** State a collision rule: a suffixed hash, a reject, or a check on the project's unit set at intake.

### M6 - The repair of orphan loop files is undefined

**Finding.** If the loop files are written and the model document write fails, the next write "repairs the set".
If the repair is a lower-gate write, no loop files are written and the stale loop files remain.

**Evidence.**
- `docs/design/hunting-67-threat-model-artifact-spec.md:150-153`.
- `docs/design/hunting-67-threat-model-artifact-spec.md:735`: a loop file is dispatchable only when the model state is `COMPLETED`.

**Fix.** State that a gate write below COMPLETED deletes the stale loop files, or that the next COMPLETED write overwrites the whole set.
Add the test.

### M7 - The zero-loop model bypasses the mover's at-least-once marker

**Finding.** The mover's move is the consumption marker, and the CONTEXT pattern records that only the mover renames.
A zero-loop model is written directly to `consumed/` by the store, so the consumption marker and the quiesce read do not see it.

**Evidence.**
- `docs/design/hunting-67-threat-model-artifact-spec.md:145`.
- `docs/design/hunting-67-threat-model-artifact-spec.md:621-624`: "The move to `consumed/` happens on dispatch admission."
- `src/polymerhus/attack/hunting/CONTEXT.md:51`: the mover applies the moves through the stores' single-owner primitives.

**Fix.** Either let the mover consume the zero-loop model on its next tick, or state that the store's completion write is the consumption marker for zero-loop models and exempt it from the at-least-once protocol.
Name the pattern exception.

### M8 - The quiesce seam and the role gate are not named

**Finding.** S2 redefines the quiesce predicate, but neither spec names the implementation seam (`surfer.run_work_remaining`, `_ratified_config`) or the #317 role-gate interaction.
The workbench R2-6 says these mechanics land in the change spec.

**Evidence.**
- `docs/design/unit-threat-model-workbench.md:363-365`.
- `docs/design/hunting-67-threat-model-artifact-spec.md:626-633`.
- `docs/design/hunting-67-threat-modeller-spec.md:767-776`: the seams list has no quiesce seam.
- `docs/design/hunting-67-threat-model-artifact-spec.md:751-763`: the seams list has no quiesce seam.

**Fix.** Name the surfer and mover functions that change, and state how a stopped role gate affects the quiesce predicate.

### M9 - The skill tool names are assumed, with no adapter or fallback

**Finding.** The suite surface is `skill_list` and `skill_load`, written "against the assumed names and data contracts".
No spec states the fallback if the suite lands with a different name, and the as-built repo has only `load_skill`.

**Evidence.**
- `docs/design/unit-threat-model-tools-adr.md:23`.
- `docs/design/hunting-67-threat-modeller-spec.md:268-271`.
- `docs/design/hunting-67-hunting-agent-spec.md:508-509`.
- `src/polymerhus/app/llm/skills.py:18-19`: the single shared `load_skill` tool.

**Fix.** State the dependency and the fallback (an adapter, or `load_skill` with a suite path), and add a contract test that the suite tools exist before the role is enabled.

### M10 - The rename's alias window does not cover the session id or the env var

**Finding.** The role, session segment, LLM role, and provider env var all rename.
An alias window works for a role key, but a session id is a checkpointer thread identity, and an env var is deployment configuration.
The spec does not state how an interrupted run's old session thread and the old env var are handled.

**Evidence.**
- `docs/design/hunting-67-threat-modeller-spec.md:99-105`.
- `docs/design/unit-threat-model-spec-impact-map.md:204-208`.
- `docs/design/hunting-67-threat-modeller-spec.md:594-600` (resume).

**Fix.** State that the session id rename takes effect for new runs only, and that resume of an old run uses the old id; or drain the old runs before the rename.
State that `LLM_HUNTING_ORCHESTRATOR` is still read as a fallback for one window, or that the deployment config is migrated in the same change.

### M11 - The acceptance scenarios 1 and 2 have no implementation or test clause

**Finding.** The workbench requires a product-submission unit to rank stored XSS high and a file-upload unit to rank RCE high.
The specs say the suite must cover the acceptance scenarios, but no clause or test asserts the ranking outcome.

**Evidence.**
- `docs/design/unit-threat-model-workbench.md:806-807`.
- `docs/design/hunting-67-threat-modeller-spec.md:790-801`: the coverage list points at the workbench scenarios.
- `docs/design/hunting-67-threat-model-artifact-spec.md:751-763`: no ranking test.

**Fix.** Add a replay test over the prototype units (or the trial models) that asserts the top-ranked class for each scenario, or state that the outcome is measured only in the post-build eval and record that as a risk.

### M12 - The low-loop pause is a rolling condition, not a run-wide barrier

**Finding.** The surfer releases low loops when no higher-ranked file is currently produced and no higher session is live.
A later unit's high loop can appear after an earlier unit's low loop has been dispatched, so the run-wide "high and medium first" order is not guaranteed.

**Evidence.**
- `docs/design/hunting-67-threat-modeller-spec.md:604-611`.
- `docs/design/hunting-67-threat-model-artifact-spec.md:612-617`, `:632`.
- `docs/design/unit-threat-model-workbench.md:57` and `:411`.

**Fix.** State explicitly that the pause is a per-tick condition and accept the late-high consequence, or define a run-wide barrier at the modeller's settle for low loops.
The current text can be read either way.

### M13 - The black-box discipline and the episodic per-phase notes are only partially carried

**Finding.** The tools ADR says black-box only (HTTP surface); S1's probe rules do not say it.
The tools ADR frames notes as per-phase episodic memories; S1 states the framing but does not instruct a note at each phase end or add a note hint.

**Evidence.**
- `docs/design/unit-threat-model-tools-adr.md:19`, `:37`.
- `docs/design/hunting-67-threat-modeller-spec.md:251-260`: no "black-box" or "HTTP surface only".
- `docs/design/hunting-67-threat-modeller-spec.md:224-231`: the notes framing.
- `docs/design/hunting-67-threat-modeller-spec.md:318-364`: no per-phase note instruction.
- `docs/design/hunting-67-threat-modeller-spec.md:709-715`: the gate hints do not mention a note.

**Fix.** Add "HTTP surface only; no internal network probing beyond the target's own interfaces" to S1 5.4, or record the relaxation.
Add a phase-end note instruction (and state whether it is a hint or prompt prose), or record that the notes are model-level only.

### M14 - The evidence-kind list is inconsistent

**Finding.** S1 lists six evidence kinds; S2 lists seven and the schema defines `document`.
S1 omits `document`.

**Evidence.**
- `docs/design/hunting-67-threat-modeller-spec.md:381`.
- `docs/design/hunting-67-threat-model-artifact-spec.md:49`.
- `docs/design/hunting-67-threat-model-artifact-spec.md:177-180`.

**Fix.** Add `document` to S1's list, or remove it from the schema if it is not used.

### M15 - The glossary is internally inconsistent and still presents the old hunter as current

**Finding.** The `persisted artifact schema` term says `ratified` in one sentence and `specified` in the next.
The `hunting agent` term still presents the per-config hunter, `derive_verdict`, and the old tool surface as the as-built contract.

**Evidence.**
- `src/polymerhus/attack/hunting/CONTEXT.md:91`.
- `src/polymerhus/attack/hunting/CONTEXT.md:37`.
- `src/polymerhus/attack/hunting/CONTEXT.md:122` (`TestImplementationSpec` still lists the retired fields).
- `docs/design/unit-threat-model-spec-impact-map.md:155`: the CONTEXT entry names only the `TestImplementationSpec` term and the new terms.

**Fix.** Update the three terms in this change (or in the build, as the ledger says) and add the per-loop hunter, the reduced surface, and the pass FSM to the entry.
Do not leave `specified` in a sentence that also says `ratified`.

### M16 - The eval design still names `derive_verdict` and the retired D4 fields

**Finding.** The eval harness design derives the hypothesis verdict with `derive_verdict` and lists the old D4 fields.
The change removes `derive_verdict` and the fields.
The impact map schedules only a hunt-config vocabulary translation for this document.

**Evidence.**
- `docs/design/eval-harness-design.md:34`, `:40`, `:75`, `:168`.
- `docs/design/unit-threat-model-spec-impact-map.md:149`.
- `docs/design/hunting-164-state-graph-spec.md:599`.
- `docs/design/hunting-67-hunting-agent-spec.md:532`.

**Fix.** Add the eval verdict mechanism and the D4 field list to the impact map's eval row, and state what replaces `derive_verdict` in the eval (or that the eval's verdict derivation is out of scope and disabled).

### M17 - The fault-KB data file and modules have no stated disposition

**Finding.** The materialisation is retired fully, and the modeller no longer consumes the matching facet.
The `data/hunting/fault-kb.yaml` artifact, `fault_kb.py`, `fault_source.py`, and `symptom_kb.py` are not in the ledger and have no stated fate.

**Evidence.**
- `docs/design/unit-threat-model-workbench.md:422` (Q39/R2-16).
- `docs/design/hunting-67-hunting-agent-spec.md:524-528`.
- `docs/design/unit-threat-model-spec-impact-map.md:126-161`.

**Fix.** Record the disposition: keep the matching facet for the recon/analysis path, delete the materialisation facet, or retire the artifact.
Name the modules and the data file.

### M18 - The schema version has no migration rule

**Finding.** The model schema is versioned, and a later change must migrate the version.
No spec states how a version-1 document is read after a version-2 change, or what the store does with an unknown version.

**Evidence.**
- `docs/design/hunting-67-threat-model-artifact-spec.md:174`.
- `docs/design/hunting-67-threat-model-artifact-spec.md:792-793`.
- `docs/design/hunting-67-threat-modeller-spec.md:684-700`.

**Fix.** State the read rule for an unknown `schema_version` (degrade, refuse, or migrate) and the migration owner.

### M19 - The "shared note-kind enum" is not named, and three enums exist

**Finding.** S4 says the shared note-kind enum gains `phase_summary`, but the repo has three closed enums: the hunt store's, the hunter's, and the pod's.
The spec does not say which one changes, and the modeller's "the existing note kinds are available" inherits the ambiguity.

**Evidence.**
- `docs/design/hunting-164-state-graph-spec.md:501`.
- `src/polymerhus/attack/hunting/hunt_store.py:708`.
- `src/polymerhus/attack/hunting/hunter_memory.py:108`.
- `src/polymerhus/attack/hunting/pod/pod_memory.py:73`.
- `docs/design/hunting-67-threat-modeller-spec.md:229-230`.

**Fix.** Name the enum (the hunter's notes enum), state whether the pod and hunt-store enums also gain the kind, and say whether the modeller's store rejects it.

## Low

### L1 - S1 story 21 has a grammar error

**Evidence.** `docs/design/hunting-67-threat-modeller-spec.md:72`: "so that I can sharpening the unit's interfaces".
**Fix.** "so that I can sharpen".

### L2 - The hint count is a reasonable completion, but it reopens Q46a

**Finding.** Q46a lists six post-slice hints; S4 adds a seventh grounding hint.
S4 states the addition explicitly, which is good, but it is still a decision made in the spec.
**Evidence.** `docs/design/unit-threat-model-workbench.md:688-690`; `docs/design/hunting-164-state-graph-spec.md:469-471`.
**Fix.** Record the seventh hint as an implementation choice in S4, or amend Q46a.

### L3 - "Pass chain" reuses the retired word "chain"

**Finding.** "Chain" is retired as an entity name, and "pass chain" is a new use.
It is clear in context, but the glossary should record it.
**Evidence.** `docs/design/hunting-164-state-graph-spec.md:333`; `docs/design/hunting-67-hunting-agent-spec.md:319`; `docs/design/unit-threat-model-workbench.md:798`.
**Fix.** Add "pass chain" to the glossary, or use "pass sequence".

### L4 - The impact map's register is stale for several entries

**Finding.** Several register rows describe lines that are already fixed (workflow 3.6, workbench 1.5, store-write decisions 10).
**Evidence.** `docs/design/unit-threat-model-spec-impact-map.md:188-195`; `docs/design/unit-threat-model-workflow.md:123-125`; `docs/design/hunting-store-write-decisions.md:126-150`.
**Fix.** Mark each row as fixed or open, so the review does not re-hunt fixed lines.

### L5 - The Q1-Q5 answers are not recorded in the workbench

**Finding.** The workbench says Round 1 (Q1-Q5) was decided but does not record the answers.
The spec set cites Q1-Q60 as the authority.
**Evidence.** `docs/design/unit-threat-model-workbench.md:7`; the Q references in `docs/design/unit-threat-model-spec-impact-map.md:9`.
**Fix.** Record the Q1-Q5 answers, or state that R1-1 to R1-5 are their only record.

### L6 - The register misses two prompt files

**Finding.** `prompts/pod-runner.md` and `prompts/examples.md` still name the retired fields.
The ledger has `examples.md` but the register does not, and neither has `pod-runner.md`.
**Evidence.** `src/polymerhus/attack/hunting/prompts/pod-runner.md:9`; `src/polymerhus/attack/hunting/prompts/examples.md:53`.
**Fix.** Add both rows.

### L7 - `hunts_store` names two different stores

**Finding.** The modeller's threat-model store and the hunter's spec store are both called `hunts_store`.
The binding is per role, so this works, but the glossary and the tool descriptions must say which store each role binds.
**Evidence.** `docs/design/hunting-67-threat-modeller-spec.md:193`; `docs/design/hunting-67-hunting-agent-spec.md:489`; `src/polymerhus/attack/hunting/CONTEXT.md:99`.
**Fix.** State the per-role binding in both specs and in the glossary.

### L8 - S2's ownership sentence is self-contradictory

**Finding.** "The modeller owns the unit id (the harness binds it)" cannot be true in both halves.
**Evidence.** `docs/design/hunting-67-threat-model-artifact-spec.md:706-708`.
**Fix.** "The harness binds the unit id; the modeller never authors it."

## Decision coverage matrix

Status values: **used** (carried and consistent), **partial** (carried but incomplete or ambiguous), **unused** (named only, not carried), **contradicted** (a spec clause or a living authority says the opposite).

### A. Tools ADR (`docs/design/unit-threat-model-tools-adr.md`)

| # | Decision | Actual carrier | Status | Note |
|---|---|---|---|---|
| 1 | `hunts_store` and `notes` survive; the target object changes | S1 5.1, 5.2 | used | The per-role store name is ambiguous (L7). |
| 2 | HTTP-history reads (search and get, never replay) | S1 5.3 | used | |
| 3 | `exec` for live probes | S1 5.4 | used | |
| 4 | Auth store plus the per-project skill coupling | S1 5.5 | used | |
| 5 | `skill_list` / `skill_load` suite binding | S1 5.5; S3 8.7 | used | The names are assumed; no fallback (M9). |
| 6 | `graph_view` not bound to the modeller | S1 5.6 | used | |
| 7 | Fault-KB aid tool withdrawn | S1 5.6 | used | |
| 8 | No modeller-scoped probe cap | S1 5.4, 6.8; S2 7.5 | used | |
| 9 | Execution-wide cap is the token budget; risk budget is the modelling cap | S1 6.8; S2 7.5 | used | |
| 10 | Probes non-destructive where feasible; prior state restored; black-box only | S1 5.4 | partial | Black-box/HTTP-only is not stated (M13). |
| 11 | LACK-1: server-side fetch probes behind file, reference, import, URL inputs | S1 5.4 | used | The map's second pointer (S1 6.5) is wrong. |
| 12 | LACK-2: drop needs a fundamental infeasibility finding | S1 6.5; S2 5.5 | used | |
| 13 | Episodic notes per phase | S1 5.2 | partial | No per-phase instruction or hint (M13). |
| 14 | Evidence per claim (request records, note refs) | S2 5.1, 5.2 | used | |
| 15 | Containment by prompts, discipline, review | S1 5.4, 6.7 | partial | The black-box element is missing (M13). |

### B. Ordering-halt ADR (`docs/design/unit-threat-model-ordering-halt-adr.md`)

| # | Decision | Actual carrier | Status | Note |
|---|---|---|---|---|
| 1 | The coupling is accepted and documented; intake order is also the halt order | S1 7.2, 7.4; S2 9.4 | partial | The specs implement it but never state the coupling. |
| 2 | The sort key stays the sort key; the halt never re-sorts | S1 7.4; S2 9.4 | used | |
| 3 | Halt at model completion, symbolic accumulator, `>=`, crossing unit dispatched, next never modelled, blocked recorded | S1 7.4; S2 7.4 | used | "Dispatched before the halt" is async in practice (see M12). |
| 4 | Intake order, crossing unit, blocked unit recorded | S1 7.4; S2 9.4 | used | |
| 5 | Resumed run re-enters at the recorded position with the persisted accumulator | S1 7.5 | partial | No position key; no halt/resume rule; stale accumulator (H8). |
| 6 | Calibration by replaying recorded runs in intake order | S2 7.4 | used | |
| 7 | The halt set is a function of the order by construction | S1 7.2, 7.4 | partial | Not stated; the consequence is undocumented (H2/M12). |

### C. Grilling decisions (R1-1 to R8-4)

| Decision | Actual carrier | Status | Note |
|---|---|---|---|
| R1-1 paradigm position | S1 2.1; S2 1 (claimed) | partial | S2 1 never states the attack-tree position. |
| R1-2 rewrite in place, no new submodule | S1 9.1, 4.1 | used | |
| R1-3 actor runtime, one session, terminal lifecycle, no evolution | S1 4.4; S2 9.1 | used | Resume is S1 7.5. |
| R1-4 intake and ordering | S1 7.2 | partial | System tie-break connectivity undefined (M4). |
| R1-5 tool surface and capabilities | S1 5 | partial | Black-box missing (M13). |
| R2-1 artifact contract, one model per unit, evidences, no probe plans | S2 4, 5 | contradicted | `web_vulnerability_class` naming swapped (B7). |
| R2-2 loop entity, 1:n failure modes, ids in ranked order | S2 6, 5.6 | used | Loop-id algorithm underdefined (M3). |
| R2-3 hunter data contract delta | S3 8.2; S2 8.2 | used | |
| R2-4 no `HuntConfig`; per-loop payload | S2 8; S3 8.2 | used | S4 14.6 contradicts (H7). |
| R2-5 progressive risk budget | S1 7.4; S2 7.4 | partial | Author and halt signal unclear (B6, H8). |
| R2-6 dispatch interleave | S1 7.3; S2 8.4 | partial | Quiesce seam and stop/resume mechanics unnamed (M8). |
| R2-7 KB disposal | S1 5.6; S3 8.8 | partial | The workbench still says materialisation continues (H2). |
| R2-8 model lifecycle record | S2 9 | used | Notes/memory successor residual not addressed. |
| R2-9 model lifecycle and consumption | S2 8.4, 9.1, 9.3 | used | Thin completion allows a bad consume (B5). |
| R2-10 threat model data contract | S2 5 | contradicted | Same as R2-1 (B7). |
| R2-11 store surface and passive trajectory | S1 5.1; S2 10.3 | used | |
| R2-12 notes documents removed, material embedded | S1 6.2, 8 | partial | The two notes docs are absent from the ledger (H11). |
| R2-13 per-state inputs and cost | S1 4.6, 6.2, 6.3 | partial | "Re-query the model if compression evicted it" is not carried. |
| R2-14 cross-unit sequencing | S1 7.6; S2 8.3 | partial | Rolling versus barrier (M12). |
| R2-15 L1 application-surface overview | S1 4.6, 6.2 | used | |
| R2-16 materialisation retired | S3 8.8 | used | Workbench text stale (H2). |
| R2-17 gate cadence | S1 4.5 | partial | "Prompt-level only" is not stated. |
| R3-1 risk criterions | S2 7.2 | partial | Observed defences and training priors are absent. |
| R3-2 / Q33 / Q40 scoring | S2 7.1-7.5 | partial | Confidence factor omitted (H4). |
| R3-3 evidence per criterion | S2 2.3, 5.2; S1 8 | partial | Per-score-term mapping not stated. |
| R3-4 unreliability risks | S2 7.6 | used | |
| R3-5 abduction and loose dedup | S1 6.4 | used | |
| R3-6 / Q55-Q57 termination, probes, side effects | S1 5.4, 6.8 | used | |
| R3-7 / Q58 validation seam and `ratify` | S1 6.6; S2 5.7 | used | |
| R3-8 map-back validation | S2 5.5, 8.2 | used | |
| R3-9 / Q30 retention-first drops | S1 6.5; S2 2.4, 5.5 | used | |
| R3-10 live authority | S1 6.7 | used | |
| R4-1 eval coupling | S1 9.5 | partial | Eval D4 and `derive_verdict` not covered (M16). |
| R4-2 docs and supersessions | S1 9.6; this map | partial | Back-edge residue and workbench fixes incomplete (H1, H2). |
| R4-2 hygiene: remove `OrchestratorTools.back_edge` | none | unused | Workbench 533 names the field; S1 9.1 removes only "the back-edge need". |
| R4-2 hygiene: chain/direction wording re-check | S1 9.6 (docs) | partial | No explicit wording re-check; "pass chain" is a new use (L3). |
| R4-3 / R8-4 / Q43 | S1 6.4, 6.5 | used | |
| R4-4 alpha-omega deferred | S1 11 | used | Excluded. |
| R4-5 surface recovery out of scope | S1 4.3, 11 | used | Excluded. |
| R5-1 / Q34 Design B | S2 4.2, 8.1 | used | Zero-loop direct consume is an addition (M7). |
| R5-2 / Q35 validation seam | S1 6.6; S2 5.7 | partial | Consumption-time non-strict parse not stated; extra="forbid" tension (C19). |
| R6-1 / Q35 confidence degree | S1 6.3; S2 2.3, 5.2 | partial | Score factor omitted (H4). |
| R6-2 / Q36 feed-forward | S3 8.2, 8.6; S2 8.2 | used | |
| R6-3 / Q37 QA and limitation | S3 8.5, 8.6 | used | The map points at 8.4. |
| R7 Q37-Q40 | S2 7.1; S3 8.6 | used | |
| R8-1 / Q39 production prompt | S3 8.5, 8.6 | partial | `variants` and the discipline paragraph omitted (H3). |
| R8-2 / Q44-Q47, Q49-Q53 | S4 14 | partial | Set-write signal, no-signal END, note-name mismatch (B2, B3, H13). |
| R8-3 / Q48 pod contract | S5 8 | partial | Failure-mode fallback (H6). |
| R8-4 KILL and disciplines | S1 6.4, 6.5 | used | |

### D. Q1-Q60

| Q | Subject | Actual carrier | Status | Note |
|---|---|---|---|---|
| Q1-Q5 | Round 1 architecture roots | R1-1 to R1-5 | partial | Answers not recorded in the workbench (L5). |
| Q6 | Model identity and workflow | R2-1; S1 6 | used | |
| Q7 | Direction model | R2-2 | used | Replaced by Q15. |
| Q8 | Workflow phases, design/execution partition | S1 6.1; S3 8 | used | |
| Q9 | Identity | R2-1 | used | |
| Q10 | Consumption at COMPLETED | S1 7.1; S2 9.3 | partial | In-flight exclusion is an addition and wedges units (B4). |
| Q11 | Document contract | S2 5 | contradicted | Web class naming (B7). |
| Q12 | Store surface | S1 5.1 | used | |
| Q13 | Notes material embedded | S1 8 | used | |
| Q14 | Grounding inputs and naming | S1 4.6, 6.2, 6.3 | partial | Web class naming (B7). |
| Q15 | Loop entity and drops | S2 6 | used | |
| Q16 | Budget mechanics | S1 7.4 | partial | Author, halt signal, resume (B6, H8). |
| Q17 | KB disposal | S1 5.6 | used | |
| Q18 | Hunter contract | S3 8.2 | used | |
| Q19 | No `HuntConfig` | S2 8 | used | S4 14.6 contradicts (H7). |
| Q20 | Sequencing | S2 8.3 | partial | Rolling versus barrier (M12). |
| Q21 | Store home | S2 4.2 | used | |
| Q22 | Application-surface entity | S1 4.6 | used | |
| Q23 | Materialisation fact-find | superseded by Q39 | used | |
| Q24 | Gate cadence | S1 4.5 | partial | Prompt-level only not stated. |
| Q25 | Scoring research order | S2 7 | used | |
| Q26 | Unreliability | S2 7.6 | used | |
| Q27 | Dedup | S1 6.4 | used | |
| Q28 | No schema gate | S1 6.6 | used | B1/B5 follow from it. |
| Q29 | Map-back | S2 5.5 | used | |
| Q30 | Failure-mode role | S2 8.2 | used | H6. |
| Q31 | Live authority | S1 6.7 | used | |
| Q32 | Eval scope | S1 9.5 | partial | M16. |
| Q33 | Scoring scheme | S2 7 | partial | H4. |
| Q34 | Design B | S2 4.2 | used | |
| Q35 | Confidence and validation seam | S1 6.3, 6.6; S2 2.3, 5.7 | partial | H4, B1. |
| Q36 | Feed-forward contract | S3 8.2, 8.6 | used | |
| Q37 | QA amendments | S3 8.5, 8.6 | used | |
| Q38 | Abduction research | S1 6.4 | used | |
| Q39 | Materialisation retired | S3 8.8 | used | H2. |
| Q40 | Enum and weights | S2 7.1 | used | |
| Q41 | Workstream sequencing | process | n/a | No spec clause needed. |
| Q42 | KILL accepted | S1 11 | used | Excluded. |
| Q43 | Two disciplines | S1 6.4, 6.5 | used | |
| Q44 | Proxy signals | S4 14 | partial | B2, B3. |
| Q45 | Loop discipline | S4 14.5, 14.8 | used | |
| Q46 | Hints | S4 14.7 | partial | Seventh hint added (L2). |
| Q47 | Removal scope | S4 14.11 | used | |
| Q48 | Variant and INIT gate | S5 8.4, 8.6 | partial | B8, H6. |
| Q49 | Grounding exit | S4 14.4 | used | |
| Q50 | Signal acceptance | S4 14.5 | partial | B3. |
| Q51 | Note label | S4 14.8 | partial | H13. |
| Q52 | Vocabulary | S2 6.2; S3 8.6; S4 14.6 | partial | H7, H13. |
| Q53 | D3 reframe | S4 14.7 | used | |
| Q54 | Next work phase | process | n/a | |
| Q55 | Termination | S1 6.8 | used | |
| Q56 | Probe budget | S1 5.4, 6.8 | used | |
| Q57 | Side effects | S1 5.4 | used | |
| Q58 | `ratify` role | S1 6.6 | used | |
| Q59 | Closure package | S1 7.5; S2 8.4 | partial | H8, M8. |
| Q60 | Docs and hygiene | S1 9.6 | partial | H1, H2. |

### E. User-story coverage

No story in S1-S5 is unserved.
Every story maps to at least one clause in its own spec.
Five decisions have no story:
- S1 4.1's alias window.
- S1 5.1's cross-unit read.
- S2 7.4's threshold override and calibration procedure.
- S2 10.5's malformed-loop-file rule.
- S1 9.5's eval translation and S1 9.6's documentation pass.
Two further clauses are only partly covered by a story:
- S2 4.3's repair protocol is covered by the commit-order story (S2 story 17) but not by a repair story.
- S2 7.6's unreliability risks have no story.
S1 story 21 is served by S1 4.6 but has a grammar error (L1).

## Independent impact map

`in ledger?` means the impact map's affected-document ledger names the component.

| Component | Change | In ledger? | Note |
|---|---|---|---|
| `src/.../hunting/hunt_orchestrator.py` | Planner pass, prompt loading, planner types | no | S1 9.1 names the types, not the module. |
| `src/.../hunting/orchestrator_graph.py` | Planner graph removed | no | Missing. |
| `src/.../hunting/llm.py` | Gate and dispatch prompt seams | no | Missing. |
| `src/.../hunting/actors.py` | Role and session rename | no | Missing. |
| `src/.../hunting/runtime.py` | Run bootstrap, run record, halt, resume | no | Missing. |
| `src/.../hunting/surfer.py` | Per-loop dispatch, quiesce, sequencing | no | Missing. |
| `src/.../hunting/mover.py` | Per-loop predicate and move | no | Missing. |
| `src/.../hunting/hunt_store.py` | Orchestrator config store retired or re-scoped | no | Missing. |
| `src/.../hunting/hunter_memory.py` | Spec store key, folder, statuses | no | Missing. |
| `src/.../hunting/hunter_state.py` | FSM, `SpecItem`, hints | no | Missing. |
| `src/.../hunting/hunter_graph.py` | Graph topology and nodes | no | Missing. |
| `src/.../hunting/hunter_tools.py` | Tool descriptions and status payloads | no | Missing. |
| `src/.../hunting/hunting_agent.py` | `derive_verdict`, `DispatchResult`, prompt loading | no | Missing. |
| `src/.../hunting/http_history_contract.py` | Canonical descriptions teach the retired field | no | Missing; H5. |
| `src/.../hunting/pod/types.py` | Reduced D4 | no | Missing. |
| `src/.../hunting/pod/verification.py` | INIT gate | no | Missing. |
| `src/.../hunting/pod/graph.py` | Triager decision and variant minting | no | Missing. |
| `src/.../hunting/pod/agents.py` | Triager decision model, default probe path | no | Missing. |
| `src/.../hunting/pod/symbolic.py` | Default probe from the retired vector | no | Missing; no stated fate. |
| `src/.../hunting/pod/pod_memory.py` | Variant record and note kinds | no | Missing (shape stays). |
| `src/.../hunting/hunting_pod.py` | Legacy pod path uses the retired vector | no | Missing. |
| `src/.../hunting/prompts/hunt-orchestrator.md` | Rewritten as the modeller prompt | yes | |
| `src/.../hunting/prompts/hunting-agent.md` | Rewritten in the prompt work phase | yes | |
| `src/.../hunting/prompts/examples.md` | Rewritten | yes | |
| `src/.../hunting/prompts/pod-triager.md` | Mining section rewritten | yes | |
| `src/.../hunting/prompts/pod-runner.md` | Replay carrier and probe authoring | no | Missing. |
| `src/.../hunting/CONTEXT.md` | Glossary terms | yes | Under-covered (M15). |
| `tests/` (28 files) | FSM, store, pod, e2e, fixtures | no | Missing. |
| `data/hunting/fault-kb.yaml` | Materialisation retirement | no | Missing (M17). |
| `docs/design/eval-harness-design.md` | Vocabulary and verdict derivation | yes | Under-covered (M16). |
| `eval/OPERATOR.md` | Oracle's D4 list and hunt-store trail | no | Missing (H11). |
| `docs/design/hunting-304-kb-degradation-guard-adr.md` | Names `derive_verdict` | no | Missing. |
| `docs/design/hunting-84-assertions.md` | Variant declines the retired vector | no | Missing. |
| `docs/design/hunting-84-regrounding-decisions.md` | D4 and NL field decisions | no | Missing. |
| `docs/design/hunting-67-per-agent-specs-decisions.md` | D67-03/07/10 superseded, no marker | yes | Ledger says build; no marker now. |
| `docs/design/hunting-memory-system-spec.md` | Per-config hunter layout superseded | yes | Ledger says build; no marker now. |
| `docs/design/hunting-84-pod-memory-system-spec.md` | `declined_attribute` semantics | yes | Note added; the body names the variant basis. |
| `docs/design/hunting-67-orchestrator-spec.md` | Superseded in full | yes | Marker added. |
| `docs/design/hunting-67-per-agent-specs-spec.md` | Sections 4, 5, 7 | yes | Marker added. |
| `docs/design/hunting-164-state-graph-adr.md` | FSM supersession | yes | Marker added. |
| `docs/design/hunting-164-assertion-catalogue.md` | Lifecycle assertions | yes | Marker added. |
| `docs/design/hunting-83-hunting-agent-implementation.md` | Workflow and typed surface | yes | Marker added. |
| `docs/design/hunting-orchestrator-candidates-rewrite-spec.md` | Modeller predecessor | yes | Marker added. |
| `docs/design/hunting-pipeline-wiring-adr.md` | Per-config to per-loop | yes | Note added. |
| `docs/design/hunting-pipeline-wiring-spec.md` | Same | yes | Note added. |
| `docs/design/hunting-store-write-decisions.md` | Section 10 and 4.2 | yes | Already updated. |
| `docs/design/vuln-testing-remediation-map.md` | D4 field list | yes | Build. |
| `docs/design/typesafe-system-one-evaluation.md` | D4 field list | yes | Build. |
| `docs/design/http-proxy-history-design.md` | `payload_vector_space.request_ref` | yes | Build; H5. |
| `docs/design/domain-model.md` | New bounded context | yes | Missing from the code plan, but in the ledger. |
| `docs/design/evolution-paradigm.md` | Minimal citation | yes | |
| `docs/design/unit-threat-model-workflow.md` | Stale lines | yes | Fixed. |
| `docs/design/unit-threat-model-workbench.md` | Stale lines | yes | Not fixed (H2). |
| `docs/design/modelling-trust-boundaries-notes.md` | Removed from production | no | Missing (H11). |
| `docs/design/modelling-dynamic-states-trust-notes.md` | Removed from production | no | Missing (H11). |

**Overclaimed items.**
- `unit-threat-model-workbench.md` is claimed fixed; it is not (H2).
- `eval-harness-design.md` is claimed translated for hunt configs only; it also needs the D4 and verdict changes (M16).
- `hunting-67-per-agent-specs-decisions.md` is claimed superseded; there is no marker yet (build-phase, but the ledger should say "marker pending").
- `hunting-memory-system-spec.md` is claimed superseded for the hunter; there is no marker yet (build-phase).

## Obsolete verbatim register

Legend: **H** = historical record explicitly marked superseded (acceptable); **F** = living claim that still reads as current (finding).

| Where | Stale claim | Replacement | Class |
|---|---|---|---|
| `hunting-67-hunting-agent-spec.md:24` | "It is dispatched by the hunt-orchestrator (IA-2)" | Dispatched by the surfer with a loop payload | F |
| `hunting-67-hunting-agent-spec.md:28` | "for its dispatched `HuntConfig`" | For its dispatched loop payload | F |
| `hunting-67-hunting-agent-spec.md:51` | "The `HuntConfig` parameter set verbatim" | The loop payload fields (S2 8.2) | F |
| `hunting-67-hunting-agent-spec.md:109-111` | The tool registry "from the `HuntConfig`"; the orchestrator arrives as a typed fixture | The loop payload; no orchestrator dispatch | F |
| `hunting-67-hunting-agent-spec.md:123` | "The `HuntConfig` covers a normal pair" | The loop payload names one research direction | F |
| `hunting-67-hunting-agent-spec.md:131-133` | "authors from the `HuntConfig` alone" | Authors from the loop payload and the reduced grounding | F |
| `hunting-67-hunting-agent-spec.md:152-153` | "authors from the `HuntConfig` alone" (IA-8) | The methodology KB degrades; the loop payload stays | F |
| `hunting-67-hunting-agent-spec.md:32` | The old fault-hypothesis workflow | S3 8.4 pass chain | H (marked) |
| `hunting-67-hunting-agent-spec.md:56-58` | D4 with testing pattern and payload vector space | Reduced D4 | H (marked) |
| `hunting-164-state-graph-spec.md:48-49` | `hypothesised_faults`, `verified_faults`, `ratified_specs`, `current_fault` | `state`, `specs`, `injected_constant`, `trail` | F |
| `hunting-164-state-graph-spec.md:130-133` | `detect --status=verified--> ...` | The eight-state pass chain with proxy signals | F |
| `hunting-164-state-graph-spec.md:304-305` | The fault status list (hypothesised, verified, dropped, specified) | The pass state and the spec set | F |
| `hunting-164-state-graph-spec.md:464` | "The config lifecycle is unchanged" | No config entity; the spec-set lifecycle only | F |
| `hunting-164-state-graph-spec.md:68-80` | The four-value fault lifecycle | `{hypothesised, ratified, dropped}` | H (section 2.3 marked) |
| `hunting-67-test-executor-pod-spec.md:111` | Empty payload vector lands `space-exhausted` | No probe derivable lands `no-symptom-evidence`, `clean=false` | F |
| `hunting-67-test-executor-pod-spec.md:198` | C11 empty payload vector lands `space-exhausted` | The new no-symptom-evidence rule | F |
| `hunting-67-test-executor-pod-spec.md:196` | C9 declined attribute yields a variant | The procedure-gap basis | F |
| `hunting-67-test-executor-pod-spec.md:208` | E1 input with testing pattern and payload vector space | The reduced D4 | F |
| `hunting-67-test-executor-pod-spec.md:220-236` | E2-E4 with two `HuntConfig`s and candidate delivery | Per-loop dispatch and one pod per ratified spec | F |
| `hunting-67-test-executor-pod-spec.md:75` | The parent consumes the pod result for the hypothesis verdict | The hunter derives no verdict; the pod exports its result | F |
| `unit-threat-model-workbench.md:300` | The ordering-halt ADR is "unwritten" | It is written | F |
| `unit-threat-model-workbench.md:358` | The ADR is "still unwritten" | Written | F |
| `unit-threat-model-workbench.md:532` | The ADR is "still unwritten" | Written | F |
| `unit-threat-model-workbench.md:369` | The materialisation facet "continues to serve the hunter side as today" | Retired by Q39 | F |
| `unit-threat-model-workbench.md:793` | The hunter-side materialisation grounding "stays" | Retired by Q39 | F |
| `unit-threat-model-spec-impact-map.md:161` | The workbench lines are fixed in this spec phase | They are not | F |
| `CONTEXT.md:26` | `web vulnerability class` equals a suite directory name | The spec splits the field (B7) | F |
| `CONTEXT.md:37` | The hunter consumes a `HuntConfig`, uses a `fault_key` folder, and `derive_verdict` is stale | Per-loop hunter; reduced surface; no verdict | F |
| `CONTEXT.md:89` | The config status lifecycle | No config entity | F |
| `CONTEXT.md:91` | `specified` body and `FaultItem` draft | `ratified` body, reduced typed spec | F (internally inconsistent) |
| `CONTEXT.md:122` | `TestImplementationSpec` with testing pattern and payload vector space | The reduced D4 | F |
| `eval/OPERATOR.md:565-566` | The D4 list with the three retired fields | The reduced D4 | F |
| `docs/design/eval-harness-design.md:34` | D4 with testing pattern, payload vector space, interpretation guidance | The reduced D4 | F |
| `docs/design/eval-harness-design.md:40`, `:75`, `:168` | `derive_verdict` derives the verdict | Removed; no verdict graph | F |
| `docs/design/hunting-304-kb-degradation-guard-adr.md:14`, `:30` | `derive_verdict` | Removed | F |
| `docs/design/hunting-84-assertions.md:51-52` | A variant declines `payload_vector_space` | The procedure-gap basis | F |
| `docs/design/hunting-84-assertions.md:61` | An empty payload vector | The reduced D4 | F |
| `docs/design/hunting-67-per-agent-specs-decisions.md:51`, `:93`, `:120` | D67-03/07/10 as current | Superseded; no marker | F |
| `docs/design/hunting-memory-system-spec.md:16`, `:44` (hunter sections) | Per-config hunter folder, notes per config, `fault_key` | Per-loop key and per-hunt notes | F |
| `docs/design/hunting-84-pod-memory-system-spec.md:11-12` | `declined_attribute` now carries the variant basis | Correct | H (updated) |
| `docs/lightrag-polyphemus-testing-handbook.md:181` | D4 includes `testing_pattern` | The reduced D4 | F |
| `STATE.md:160` | `derive_verdict` shipped | Removed | F |
| `src/.../http_history_contract.py:74`, `:94`, `:113` | `payload_vector_space.request_ref` | The typed replay carrier (H5) | F |
| `src/.../hunter_tools.py:757` | The tool description teaches `payload_vector_space.request_ref` | The typed replay carrier | F |
| `src/.../prompts/pod-runner.md:9` | The runner reads `payload_vector_space.request_ref` | The typed replay carrier | F |
| `src/.../prompts/examples.md:53` | `payload_vector_space` | The reduced D4 | F |
| `docs/design/hunting-164-state-graph-spec.md:164` | The `hunts_store` status enum with `verified` and `specified` | The reduced statuses | H (section 5 marked) |
| `docs/experiments/unit-threat-model-prototype/qa/**` | The QA outputs carry `payload_vector_space` and `interpretation_guidance` | Frozen experiment record | H (historical) |
| `docs/experiments/unit-threat-model-prototype/qa/t2/run-log.md:72` | `AGGREGATE+CHECK` | WELL-FORMEDNESS | H (historical) |

## Concreteness findings

The table lists components that remain ambiguous or leave an impactful decision to implementation.
The blockers are not repeated here.

| # | Component | What is ambiguous | Evidence | Fix |
|---|---|---|---|---|
| C1 | Run record | `threshold_basis`, `degraded_units`, and the run-level `risk_breakdown` shape | S2 7.4, 9.2; S1 7.4; map 226 | Add keys and shape (M1). |
| C2 | Store read/write payload | Read args; the COMPLETED composite section | S1 5.1; S2 5.4 | Define the payloads (M2). |
| C3 | Loop ids | Sort, tie-break, renumber | S2 5.6 | State the algorithm (M3). |
| C4 | Ordering | System connectivity; unit-name collisions | S1 7.2; S2 4.2 | Define and add a collision rule (M4, M5). |
| C5 | Commit protocol | Orphan loop files after a failed completion | S2 4.3 | State the repair (M6). |
| C6 | Zero-loop consumption | Bypasses the mover marker | S2 4.2, 8.4 | State the exception (M7). |
| C7 | Quiesce | No seam, no role-gate interaction | S2 8.4; workbench 363-365 | Name the functions (M8). |
| C8 | Skill tools | Assumed names, no fallback | ADR 23; S1 5.5 | Add an adapter or a fallback (M9). |
| C9 | Rename | Session id, checkpointer, env var alias window | S1 4.1; S1 7.5 | State the migration (M10). |
| C10 | Acceptance | No ranking test for scenarios 1-2 | workbench 806-807; S1 10.4 | Add a replay test (M11). |
| C11 | Low-loop pause | Rolling versus barrier | S1 7.6; S2 8.3 | State the semantics (M12). |
| C12 | Probe discipline | Black-box/HTTP-only not stated | ADR 37; S1 5.4 | Add the clause (M13). |
| C13 | Notes | No per-phase note instruction | ADR 19; S1 5.2, 6.2 | Add the instruction (M13). |
| C14 | Evidence kinds | `document` missing in S1 | S1 6.3; S2 2.3 | Align the lists (M14). |
| C15 | Glossary | `ratified` and `specified` in one term; old hunter entry | CONTEXT 37, 91, 122 | Update the terms (M15). |
| C16 | Eval | `derive_verdict` and the old D4 | eval-harness 34, 40, 75, 168 | Update the eval (M16). |
| C17 | Fault KB | Data file and modules have no disposition | workbench 422; S3 8.8 | Record the disposition (M17). |
| C18 | Schema migration | Unknown version behaviour | S2 174, 792 | State the read rule (M18). |
| C19 | D4 unknown fields | `extra="forbid"` not stated; the retired-field rejection test needs it | S5 8.8 | State the model config. |
| C20 | `skill_procedure` bound | "Bounded" has no number, no shape | S3 8.6; S5 8.6 | Typed object and cap (B8). |
| C21 | Replay carrier | Free-text naming of an artifact id | S5 8.5 | Typed field (H5). |
| C22 | `fault_ref` | Points at a fault with no id | S2 5.1 | Add a fault id (H9). |
| C23 | Trust agreement refs | No interface-agreement refs | S2 5.1, 8.2 | Add the ref list (H9). |
| C24 | Modeller trail | No home | S1 6.1; S2 5.3 | Define the trail (H10). |
| C25 | Note name | `phase:well-formedness` versus `well_formedness` | S4 14.6, 14.9 | Normalise (H13). |

## Pattern-reference findings

The CONTEXT patterns are the atomic writes (#340), the bounded whole-file notes (#341), the shared tool-contract base (#293), the phase-transition verbatims, the hunter memory store, the hunt store, the inbox surfer/mover with the at-least-once marker, and the reused seams.

| # | Pattern | Cited? | Fits? | Evidence | Note |
|---|---|---|---|---|---|
| P1 | Atomic store writes (#340) | yes | yes | S1 9.2; S2 4.4, 10.1 | Correct. |
| P2 | Bounded whole-file notes (#341) | yes | yes | S1 9.2; S2 4.4, 10.1 | Correct; the model files are correctly excluded from the bound. |
| P3 | Shared tool-contract base (#293) | yes | yes | S1 9.2; S2 10.1; CONTEXT 99-101 | Correct. |
| P4 | Phase-transition verbatims | yes | yes | S1 5.1, 9.3; S4 14.7 | Correct. |
| P5 | Hunter memory store | yes | partial | S1 9.2; S2 10.1; S3 8.9 | Cited, but the per-loop key and folder change more than the citation suggests. |
| P6 | Hunt store | yes | partial | S1 9.2; S2 10.1 | The orchestrator config store is retired, not just adapted; the citation should say so. |
| P7 | Inbox surfer/mover with at-least-once marker | yes | partial | S1 9.2; S2 10.1, 4.5 | The zero-loop direct-to-consumed write bypasses the marker (M7). |
| P8 | Derived-symbol discipline | yes | yes | S1 9.2; S2 10.1, 10.2 | Correct. |
| P9 | Move-aware write | yes | yes | S2 4.5, 10.1 | Correct. |
| P10 | Coded teaching rejection | yes | yes | S1 9.2; S2 10.1 | Correct. |
| P11 | Conciseness directive (#292) | named | yes | S1 5.2; S3 8.7; S4 14.8 | No ticket number, but named. |
| P12 | Surfer dispatch gate and quiesce (`run_work_remaining`, `_ratified_config`) | no | missing | S2 8.4; workbench 363-365 | The design changes this seam but does not cite it (M8). |
| P13 | #317 role gate | no | missing | workbench 50; S1 7.7 | A stopped role changes the quiesce and the intake; not cited. |
| P14 | Provider-failure path (#312/#331) | named | yes | S1 4.4 | Named as "the shared provider-failure path". |
| P15 | Target-front availability (#323) | named | yes | S1 5.4 | Correct. |
| P16 | HTTP-history read pair (#196) | yes | yes | S1 5.3; CONTEXT 77 | Correct; the replay carrier is the gap (H5). |
| P17 | Skill suite surface | cited as assumed | partial | ADR 23; S1 5.5 | No adapter or fallback (M9). |
| P18 | Notes tool base | yes | yes | S1 5.2; S2 10.1 | The note-kind enum is ambiguous (M19). |

**Pattern used but not cited.** The surfer's status-gated dispatch and quiesce seam (`run_work_remaining`, `_ratified_config`) and the #317 role gate.
**Pattern cited but not fitting.** The "inbox surfer and mover with the at-least-once marker" is cited for a store that writes a zero-loop model directly into `consumed/`, bypassing the marker (M7).

## Section-reference integrity

### Impact map pointers that do not say what the row claims

| Map row | Points at | Actual carrier |
|---|---|---|
| R3-3 (`:90`) | S2 5.3 | S2 2.3, 5.2 |
| R6-1 (`:104`) | S2 5.3 | S2 2.3, 5.2 |
| Q52 (`:111`) | S2 6.1 | S2 6.2 |
| R3-6/Q55-Q57 (`:93`) | S1 6.1 | S1 5.4, 6.8 |
| R2-17 (`:87`) | S1 6.1 | S1 4.5 |
| R2-11 (`:81`) | S2 5.7 | S2 10.3 |
| R6-2/Q36 (`:105`) | S3 8.3 | S3 8.2, 8.6 |
| R6-3/Q37 (`:106`) | S3 8.4 | S3 8.5, 8.6 |
| R7 (`:107`) | S3 8.4 | S3 8.6 |
| R8-1 (`:108`) | S3 8.1 | S3 8.5 |
| LACK-1 (`:49`) | S1 6.5 | S1 5.4 |
| R1-1 (`:68`) | S2 1 | S1 2.1 (S2 has no statement) |
| R2-9 (`:80`) | S2 9 | S2 8.4 |
| R2-6 (`:78`) | S1 7.3, 7.6 | S2 8.4 |
| Risk factors (`:123`) | S2 7.3 | S2 7.2 |
| Risk breakdown (`:124`) | S2 7.4 | S2 7.3 |
| `none` dispatch (`:121`) | S2 6.2 | S2 8.3 |

### Internal references that do not resolve

| Where | Reference | Problem |
|---|---|---|
| S2 8.2 (`:591`) | "the interface agreements referenced by the trust agreement" | `TrustAgreement` has no interface-agreement references (H9). |
| S2 5.7 (`:410`) | "Every `fault_ref` resolves to an assumption" | `Fault` has no id; the field name says fault (H9). |
| S1 6.1 (`:306-309`) | "the trail" | No model or run field (H10). |
| S2 5.3 (`:339`) | "trail-only material" | Same (H10). |
| S4 14.5 (`:422`) vs 14.10 (`:575`) | "stay" vs "END" | Direct contradiction (B3). |
| S4 14.4 (`:407`) vs S3 8.7 (`:492`) | set write vs one spec | Direct contradiction (B2). |
| S4 14.6 (`:464`) vs S2 6.2 (`:453`) | config lifecycle vs no config | Direct contradiction (H7). |
| S5 8.6 (`:426`) vs S2 8.2 (`:600`) | failure-mode fallback vs no failure modes | Contradiction (H6). |
| S1 7.4 (`:547`) vs S2 5.4 (`:351`) | store computes vs modeller writes `risk_profile` | Contradiction (B6). |
| S2 7.4 (`:529`) vs S2 9.2 (`:646-659`) | basis recorded vs no key | Gap (M1). |
| S3 8.4 (`:330`) vs S3 8.6 (`:466`) | well-formedness drop vs terminal `dropped` | Collision (H13). |
| Map 6 (`:226`) vs S1 7.4 (`:586`) | fixed run keys omit `degraded_units` | Gap (M1). |

## Questions to Probe

1. For B2, is the GENERATE exit intended to be a batched set write or a note?
   The answer changes the store contract, the S3 tool description, and the Q46a hint mapping, so it needs an operator decision rather than an implementation choice.
2. For B4 and B5, what is the recovery path for a unit whose model is produced but not completed?
   The current design has no delete primitive and no resume rule for a failed run, so a single degraded unit can permanently remove surface from every later run.
3. For B7, is the canonical class name or the suite directory name the stored value?
   The decision says the suite name; the spec says the canonical name plus a `suite_class`.
   If the answer is the spec's split, R2-1 and the glossary must be amended, not just the spec.
4. For B8, where does the seven-section checklist come from, and who authors it?
   The triager's deterministic mining cannot be built until the checklist shape and the gap-to-section mapping are fixed.
5. For H8, is a halted run resumable?
   If it is, the spec needs a position key and a recomputation rule for `risk_total`; if it is not, the spec should say that a halt is terminal and only a stopped or interrupted run resumes.

## Bottom Line

The set is a strong synthesis with a sound architecture, but it is not a buildable contract yet: the eight blockers are concentrated in the artifact lifecycle and the hunter FSM, and each needs a narrow decision before `/to-tickets`.
Fix B1-B8 first, then re-run the traceability and supersession pass described in H1, H2, H11, and H12.

## Fix verification (2026-10-18)

*Scope: re-read of the impact map, S1-S5, and the glossary after the fix pass.
The finding numbers are the original ones.
Only material regressions are reported.*

### Blocker verification

| Blocker | Status | Evidence | Note |
|---|---|---|---|
| B1 | RESOLVED | S2 5.1:185-190, 339-341; S2 5.4:372-388 | `PartialThreatModel` at every write; the complete model only at COMPLETED. |
| B2 | RESOLVED | S3 8.7:520-523; S4 14.4:408; S4 14.9:565-566 | The GENERATE and terminal writes carry one `specs` list. |
| B3 | RESOLVED | S4 14.10:578-585 | END only on `state == complete`; a no-signal turn stays. |
| B4 | RESOLVED | S2 4.2:137-156; S1 7.7:656-660; S2 9.3:755-762 | Degraded and stale produced models move to `abandoned/` and are retried. |
| B5 | NOT RESOLVED | S2 5.7:473-482 vs S2 8.4:696-698 and S2 10.5:830-836 | Consumability requires `validation.valid`, but the work read and the "complete" predicate do not. |
| B6 | NOT RESOLVED | S2 5.4:381-385 vs S1 6.2:377 | S2 removes `risk_profile` from the section; S1 still instructs the modeller to write it. |
| B7 | RESOLVED | S2 5.1:264-275; S2 5.2:355-360; S1 6.2:364-366; S3 8.6:464; S5 8.4:332; map 277 | `web_vulnerability_class` is the suite name; `canonical_class` is the free name. |
| B8 | RESOLVED | S3 8.6:471-488; S5 8.4:334-349; S5 8.6:437-448 | Typed seven-field `SkillProcedure`, one-to-one gap mapping, 4000-character bound. |

B5 is the material residual.
The new `validation.valid` gate is the right rule.
S2 10.5 still states the shared predicate as `state == COMPLETED`.
S2 8.4 lets the mover consume a COMPLETED model with no loop files.
A failed model can therefore be consumed before the archive.
The fix is one line in 10.5 and 8.4: require `validation.valid`.

B6 is the other residual.
S1 6.2 still says "Write the risk profile and the ranked loops."
S1 7.4 and S2 5.4 say the modeller does not author it.
The fix is to delete "the risk profile and" from S1 6.2.

### High-finding verification

| Finding | Status | Evidence | Note |
|---|---|---|---|
| H1 | RESOLVED | S3 10-16; S4 5-7; S5 11-15 | The markers now cover the old sections. |
| H2 | RESOLVED | workbench 360, 534, 537, 843 | The live ADR and materialisation lines are fixed; line 771 is a dated inventory. |
| H3 | PARTIAL | S3 8.6:468-469 vs workbench 655 | `variants` moves pod-side without an amendment to R8-1. |
| H4 | RESOLVED | S2 7.2:561-563; S1 6.3:398-402 | Confidence is a class-assignment factor, not a summand. |
| H5 | PARTIAL | S2 8.2:660, 666; S3 8.6:464; S5 8.5:386 | The spec provenance carrier is right; the loop-payload bullet is backwards and duplicated. |
| H6 | RESOLVED | S5 8.6:446-448 | The fallback uses `verification_symptoms` and `assumptions`. |
| H7 | RESOLVED | S4 14.6:465 | The HuntConfig lifecycle is retired. |
| H8 | RESOLVED | S1 7.5:620-630; S2 9.2:727-741 | Position, commit order, recompute, and dispatch-only resume are stated. |
| H9 | RESOLVED | S2 5.1:251-254, 207-213; S2 5.7:451-457 | Fault id, interface refs, transition endpoints, and violation mapping are checked. |
| H10 | RESOLVED | S1 6.1:319-320; S2 9.2:741-750 | The run-record `trajectory` has a shape. |
| H11 | RESOLVED | map 179-206 | The code, prompt, test, and data ledger is added. |
| H12 | RESOLVED | map 73-131 | The pointers match the carriers; R2-16 still points at S1 5.6. |
| H13 | RESOLVED | S4 14.6:452-456; S4 14.4:409; S3 8.4, 8.7 | The note uses `phase:well_formedness`; the note and terminal statuses are split. |

### New material contradictions

| # | Contradiction | Evidence | Impact | Fix |
|---|---|---|---|---|
| N1 | The loop payload carries `baseline_ref` from the spec provenance. The payload is dispatched before the spec exists. The bullet is duplicated. | S2 8.2:660, 666 | The materialiser looks for a field that does not exist. | Remove both bullets; carry the candidate artifact ids in the evidence pointers; the hunter records `provenance.baseline_ref`; the pod reads the spec. |
| N2 | The shared predicate calls a model complete on state alone; consumability requires `validation.valid`. | S2 5.7:473-482 vs S2 10.5:830-836, S2 8.4:696-698 | The thin-model consumption path remains. | Add `validation.valid` to 10.5 and 8.4. |
| N3 | S1 6.2 tells the modeller to write the risk profile; S2 5.4 and S1 7.4 forbid it. | S1 6.2:377 vs S2 5.4:381-385, S1 7.4:564-567 | The two-author ambiguity remains. | Delete "the risk profile and" from S1 6.2. |
| N4 | S1 7.1 skips any in-flight model; S2 9.3 skips only when the producing run is live or resumable. | S1 7.1:503 vs S2 9.3:758-762 | The B4 retry path has two readings. | Add the qualifier to S1 7.1. |
| N5 | `variants` is pod-side in S3; the decision says the hunter's `variants` stay. | S3 8.6:468-469 vs workbench 655 | An unrecorded change to the typed surface. | Amend R8-1, or restore the field. |
| N6 | The glossary still defines a live HuntConfig status lifecycle; S2 6.2 retires it. The map says the term is fixed. | CONTEXT 90 vs S2 6.2:517-519; map 243 | A living glossary contradiction. | Mark the term historical, or record the retirement. |

N4 and N6 are residual, not new.
N4 does not reopen B4 because S1 7.7 and S2 9.3 define the archive path.
N6 is a documentation defect, not a contract defect.

### Final verdict

**FAIL, 2 blockers remain: B5 and B6.**

Six of the eight blockers are resolved.
Eleven of the thirteen highs are resolved; H3 and H5 are partial.
The remaining fixes are narrow: one predicate line (B5/N2), one phase sentence (B6/N3), two baseline bullets (H5/N1), one S1 qualifier (N4), one R8-1 amendment (N5), and one glossary note (N6).
With those edits the set should reach PASS.

## Final fix verification

*Scope: verification of the four residual items only.
This section supersedes the verdict above.*

| Item | Status | Evidence | Note |
|---|---|---|---|
| B5 | RESOLVED | S2 8.4:696; S2 10.5:830-831; S2 5.7:471-482 | The work read, the dispatch predicate, and consumability all require `validation.valid`. A failed model is archived and not dispatched. |
| B6 | RESOLVED | S1 6.2:377; S1 7.4:565; S2 5.4:385; S2 5.7:467-469; S2 7.3:578 | The modeller writes the ranked loops; the store computes the profile; the checker recomputes it. |
| H5 | RESOLVED | S2 8.2:665; S3 8.6:464; S3 8.9:588; S5 8.4:332; S5 8.5:386 | One evidence-pointer bullet; no payload `baseline_ref`; the spec-side pointer is `provenance.baseline_ref`. |
| H3 | RESOLVED | S3 8.6:470-471; workbench 655 | The recorded reading of R8-1 is explicit in both places. |

B5: the work read includes a produced COMPLETED model only when `validation.valid` is true.
S2 10.5 states the same condition for the model document.
S2 5.7 states consumability as `state == COMPLETED and validation.valid == true`.
A failed model is archived to `abandoned/` and recorded in `degraded_units`.
The three clauses agree.

B6: S1 6.2 now says "Write the ranked loops; the store computes the risk profile."
No other S1 clause asks the modeller to write it.
S2 5.4 excludes `risk_profile` from the COMPLETED sections.
S2 7.3 has the harness write the total.
S2 5.7 recomputes the profile from the stored loops.
The authorship is single.

H5: S2 8.2 carries one bullet for the evidence pointers, including recorded HTTP-history artifact ids.
The payload no longer names `baseline_ref` from the spec provenance.
S3 8.6 defines `provenance.baseline_ref` as the optional spec-side pointer.
S3 8.9 says it rides the provenance.
S5 8.4 carries it and S5 8.5 consumes it.
The chain is coherent and has no duplicate.
The sentence that the hunter chooses a baseline is in S2 8.2:665, not S3 8.2.

H3: S3 8.6 states the recorded reading of R8-1's `variants` bullet.
The workbench line 655 carries the same note.
The amendment is explicit and consistent.

**Final verdict: PASS.**

No blocker remains.
The set is ready for `/to-tickets`.
