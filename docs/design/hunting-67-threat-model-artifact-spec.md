# Threat model spec: the formal unit threat model artifact

*Status: spec (contract), NOT implementation. Tracker: [#373](https://github.com/Diekgbbtt/polyphemus/issues/373). This document is the artifact contract for the unit threat model redesign. It is synthesised from the grilling record (`docs/design/unit-threat-model-workbench.md`), the workflow contract (`docs/design/unit-threat-model-workflow.md`), the risk-scoring research (`docs/design/unit-threat-model-risk-scoring-research.md`), and the two accepted ADRs. The agent contract is `docs/design/hunting-67-threat-modeller-spec.md`; the impact map is `docs/design/unit-threat-model-spec-impact-map.md`.*

## 1. Problem statement

The current pipeline persists hunts as `HuntConfig` files.
A config is a fault-class brief with a rationale, a research direction, preconditions, and observed defences.
It carries no formal trust model.
It carries no evidence per claim.
It carries no failure-mode assessment.
The hunter receives a fault class and must invent the unit's trust agreements from a projection.

The White Jotter evaluation showed the cost.
The consumed configs were access-control and hygiene families.
Stored XSS, RCE, SQLi, and arbitrary file read were never scheduled.
The unit-specific trust agreements that would have raised them were never written down.

The pipeline needs an artifact that is formal enough to audit, broad enough to preserve research directions, and precise enough to dispatch one hunter per direction.
The artifact must never evolve.
It must never lose a direction to a vector-level falsification.
It must carry the evidence that makes its confidence degrees meaningful.

## 2. Solution

### 2.1 One model per unit

The phase-2 attack-tree document is inspirational only, never a compatibility contract.
The two paradigms abduct in opposite directions.
The artifact is the **unit threat model**.
There is one model per discretely testable L1 unit.
The model id is the unit id.
The model is stored under the project's threat-model store.
It is produced at the five workflow gates and completed at the fifth.
It is consumed per loop, not per model.

### 2.2 The loop is the dispatch grain

The ranked rows are **loops**.
A loop is `fault -> web vulnerability class -> failure-mode assessment -> likelihood`.
Loop ids are assigned at COMPLETED in ranked order.
The highest likelihood is `loop-1`.
One loop file is emitted per dispatchable loop.
The surfer dispatches one hunter per loop file.
Low loops stay dispatchable and are paused until the higher ranks are executed.

### 2.3 Evidence and confidence

Every formal record carries a confidence degree and evidence entries.
The confidence degree is `OBSERVED`, `INFERRED`, or `ASSUMED`.
The evidence entries name the request records, HTTP-history artifacts, probes, notes, previous models, framework defaults, or documents that ground the record.
A claim may carry several evidence entries.
The entry list is repeatable and indexable.
No citations block exists.
No probe-plan artifact exists.

### 2.4 Retention

The drop rule is retention-first.
A falsified vector lowers the likelihood.
A loop with no feasible failure mode is retained with likelihood `none`.
It contributes zero to the risk sum and is not dispatched.
Only a fundamental technical-infeasibility finding drops a vulnerability.
A drop is a backward correction of the agreements it was mapped from.
The failure mode stays in the model for debugging and is never fed forward.

## 3. User stories

1. As an operator, I want one model per unit with the unit id as its id, so that the artifact identity is unambiguous.
2. As an operator, I want the model to carry the technical sharpening, the trust model, the assumptions, the vulnerabilities, the failure modes, and the loops, so that one document explains one unit end to end.
3. As an operator, I want every record to carry a confidence degree, so that the unprobed claims are visible.
4. As an operator, I want every record to carry evidence entries, so that a reviewer can reconstruct the grounding.
5. As an operator, I want the evidence list to be repeatable, so that a claim can cite several probes or request records.
6. As an operator, I want no citations block and no probe plans, so that the model does not carry a second, stale evidence form.
7. As an operator, I want the loop to carry the fault, the vulnerability class, the suite class, the failure-mode refs, the likelihood, the rationale, the four risk factors, and the confidence, so that the dispatch payload is derivable from one record.
8. As an operator, I want the loop's failure modes kept out of the hunter payload, so that the hunter is not narrowed to one engineered procedure.
9. As an operator, I want a `none` loop retained but not dispatched, so that a falsified vector never erases a direction.
10. As an operator, I want a dropped vulnerability to record the infeasibility proof and the discriminating probe shape, so that the drop is auditable.
11. As an operator, I want the drop to correct the agreements it was mapped from, so that the trust model stays honest.
12. As an operator, I want the suite class to equal a skills-suite directory name, so that the hunter can load the class skill.
13. As an operator, I want a suite gap flagged when no class covers the named vulnerability, so that the gap is visible.
14. As an operator, I want the risk factors recorded per loop, so that the likelihood class is auditable against the CVSS-inspired ontology.
15. As an operator, I want the harness to compute the per-unit sum from the loop likelihoods, so that the model cannot inflate its own budget total.
16. As an operator, I want the per-level breakdown recorded, so that the budget arithmetic is inspectable.
17. As an operator, I want the model document to commit after its loop files, so that a crash cannot leave a COMPLETED model with missing loop files.
18. As an operator, I want the loop files to be the dispatch items, so that consumption grain equals dispatch grain.
19. As an operator, I want the model document to move with its last loop file, so that the produced and consumed directories always tell the truth.
20. As an operator, I want a zero-loop unit consumed at completion, so that a fully dropped model does not wedge the quiesce.
21. As an operator, I want the low loops paused until the higher ranks are executed, so that cheap high-yield directions run first.
22. As an operator, I want the low loops to survive a restart as filesystem state, so that the pause is not lost.
23. As an operator, I want a completed model excluded from a later run, so that the pipeline never re-models a decided unit.
24. As an operator, I want an in-flight produced model skipped and recorded, so that two writers cannot race on one unit.
25. As an operator, I want a new run to refuse another run's produced loops, so that the risk accounting stays run-scoped.
26. As an operator, I want the model schema versioned, so that a later change can migrate without guessing.
27. As an operator, I want the completion checker to record missing attributes and unclosed assumptions without blocking publication, so that the model is still usable.
28. As an operator, I want the loop file to carry the loop record and the run identity, so that the dispatch is traceable.
29. As the threat modeller, I want to extend the model at each gate without re-authoring the whole document, so that the context cost stays bounded.
30. As the threat modeller, I want the store to own the file names and the ids, so that I never compose a symbol.
31. As the surfer, I want one loop file per dispatchable loop, so that one move dispatches one hunter.
32. As the surfer, I want a loop file's likelihood, so that I can sequence the dispatch.
33. As the surfer, I want the model document available while a loop file is dispatched, so that I can materialise the hunter payload.
34. As a hunter, I want the loop payload to carry the relevant trust agreement or dynamic-state transition, so that I ground on the technical failure modes of the agreement.
35. As a hunter, I want the loop payload to carry the evidence pointers, so that I can ground on the recorded traffic.
36. As a hunter, I want the loop payload to carry the suite class, so that I can load the class skill.
37. As a reviewer, I want the validation outcome persisted in the model, so that a thin model is visible after the fact.
38. As a reviewer, I want the model to record its run id and timestamps, so that the artifact is traceable to the run.
39. As a reviewer, I want the model's state to be monotonic, so that a late earlier-gate write cannot regress it.
40. As a reviewer, I want the schema to forbid unknown fields, so that a typo does not silently persist.
41. As a runtime operator, I want the store writes to be atomic, so that a killed write leaves the previous complete file.
42. As a runtime operator, I want the notes store bounded, so that a long run cannot grow one file without limit.
43. As a runtime operator, I want a move-aware write, so that a late write cannot recreate a consumed file.
44. As a runtime operator, I want a coded rejection for a missing derivation input, so that a degenerate file name is impossible.

## 4. Identity and layout

### 4.1 Identity

The model id is the unit id.
The unit id is the kind-qualified L1 identity, for example `Service:model-download` or `WebPresentation:custom-node-catalog::manager-shell`.
The model carries `unit_kind` of `service` or `system`.
The model id is the authoritative identity.
The file name is a derived symbol.

### 4.2 Store layout

The store root is `data/<project_id>/hunting/threat_modeller/`.

```
produced/
  <unit_name>/
    <unit_name>.yaml
    loop-<rank>.yaml
consumed/
  <unit_name>/
    <unit_name>.yaml
    loop-<rank>.yaml
abandoned/
  <unit_name>/
    <unit_name>.yaml
    loop-<rank>.yaml
```

`<unit_name>` sanitises `:` and `/` to `-`.
If two distinct unit ids sanitise to the same name, the store appends `-<first 8 hex of sha256(unit_id)>` to the later name.
The store checks the existing directory's model `unit_id` before it writes; a mismatch triggers the suffix.
The model document is `<unit_name>.yaml`.
The loop file is `loop-<rank>.yaml`.
The unit directory groups one model and its loop files.

The model document is written at every gate.
The loop files are written only at `COMPLETED`.
A model with at least one dispatchable loop stays in `produced/` until its last loop file is consumed.
A model with zero dispatchable loops is written to `produced/` at `COMPLETED`.
The mover consumes it on its next tick without dispatching a hunter and records zero dispatches.
This keeps the move as the single consumption marker.
`abandoned/` holds a degraded or invalid model; the intake and the mover ignore it.

### 4.3 Commit protocol

The model document is the commit marker.
At `COMPLETED`, the store writes the loop files first, atomically, then the model document with `state: COMPLETED`.
If a crash happens after the loop files and before the model document, the model remains at the previous state, and the next write repairs the set.
A gate write below COMPLETED deletes the stale loop files before it merges its section.
A loop file is never read for a model whose state is not `COMPLETED`.
A loop file written for a model that later fails the completion write is overwritten by the repair.

### 4.4 Atomicity and bounds

Every whole-file write uses the shared atomic-write primitive: same-directory temp file, flush, fsync, replace, best-effort temp cleanup.

The notes store uses the shared bounded whole-file primitive.
The bounds protect the durable prior-insight records.
The model document and the loop files are single-model files; they are not bounded records.

### 4.5 Move-aware write

A write to a `produced/` path whose identity already lives in `consumed/` is a no-op success that returns the consumed path.
The store never recreates a consumed file.
This preserves the single-writer invariant across the mover race.

## 5. The model schema

### 5.1 Shape

The persisted document is a **partial** model at the intermediate gates and a **complete** model at COMPLETED.
Every section has an empty default.
The store parses the document as `PartialThreatModel` at every write.
The completion checker validates the complete `UnitThreatModel` only at COMPLETED.
Unknown fields are forbidden at every level.
The schema version is `1`.

```
Evidence:
  kind: request | http_history | probe | note | model | framework_default | document
  ref: str
  detail: str = ""

Confidence: OBSERVED | INFERRED | ASSUMED
Likelihood: none | low | medium | high | critical

Agreement:
  id: str
  statement: str
  confidence: Confidence
  evidences: list[Evidence]

TrustAgreement:
  id: str
  boundary: str
  interface_agreement_refs: list[str] = []
  statement: str
  confidence: Confidence
  evidences: list[Evidence]

DynamicState:
  id: str
  variables: list[str]
  confidence: Confidence
  evidences: list[Evidence]

Transition:
  id: str
  source: str
  target: str
  guard: str
  confidence: Confidence
  evidences: list[Evidence]

Violation:
  id: str
  kind: trust-transition | state-consistency | forced-transition | other
  statement: str
  maps_to_fault: str
  confidence: Confidence
  evidences: list[Evidence]

DynamicStateTrust:
  states: list[DynamicState] = []
  transitions: list[Transition] = []
  violations: list[Violation] = []

TechnicalSharpening:
  interface_agreements: list[Agreement] = []
  control_flows: list[Agreement] = []
  data_flows: list[Agreement] = []

TrustModel:
  trust_agreements: list[TrustAgreement] = []
  dynamic_state_trust: DynamicStateTrust = default

Fault:
  id: str
  label: str
  description: str

Assumption:
  id: str
  statement: str
  fault: Fault
  boundary_ref: str = ""
  confidence: Confidence
  evidences: list[Evidence]

Vulnerability:
  id: str
  fault_ref: str
  canonical_class: str
  web_vulnerability_class: str = ""
  suite_gap: bool = false
  characterisation: str
  dropped: bool = false
  drop_reason: str = ""
  drop_probe: str = ""
  confidence: Confidence
  evidences: list[Evidence]

FailureMode:
  id: str
  vulnerability_ref: str
  mode: str
  feasibility: feasible | conditionally-feasible | infeasible
  feasibility_rationale: str
  dropped: bool = false
  drop_reason: str = ""
  drop_probe: str = ""
  confidence: Confidence
  evidences: list[Evidence]

RiskFactors:
  attack_vector: network | adjacent | local | physical
  attack_requirements: none | present
  privileges_required: none | low | high
  complexity: low | high

Loop:
  id: str
  fault_ref: str
  vulnerability_ref: str
  failure_mode_refs: list[str]
  canonical_class: str
  web_vulnerability_class: str = ""
  suite_gap: bool = false
  likelihood: Likelihood
  likelihood_rationale: str
  risk_factors: RiskFactors
  confidence: Confidence
  evidences: list[Evidence]

RiskProfile:
  total: int
  breakdown: {none: int, low: int, medium: int, high: int, critical: int}

Validation:
  checked_at: datetime
  parseable: bool
  valid: bool
  missing: list[str]
  unclosed: list[str]
  referential_errors: list[str]

UnitThreatModel:
  schema_version: int = 1
  unit_id: str
  unit_kind: service | system
  run_id: str
  created_at: datetime
  updated_at: datetime
  state: UNIT_TECHNICAL_SHARP | TRUST_MODELLED | TRUST_ASSUMPTIONS_WRITTEN | VULNERABILITIES_WRITTEN | COMPLETED
  technical_sharpening: TechnicalSharpening = default
  trust_model: TrustModel = default
  assumptions: list[Assumption] = []
  vulnerabilities: list[Vulnerability] = []
  failure_modes: list[FailureMode] = []
  loops: list[Loop] = []
  risk_profile: RiskProfile | null = null
  validation: Validation | null = null
```

The complete model is the schema above with all required sections non-empty per the checker.
A partial document is the same schema with the empty defaults.
A consumer that needs the complete model reads only a document whose `state` is `COMPLETED` and whose `validation.valid` is true.

### 5.2 Record rules

Every record carries a unique `id` within its section.
Every fault carries a unique `id`; the assumption embeds the fault and the vulnerability's `fault_ref` resolves to that fault id.
Every record carries a `confidence` and at least one `evidences` entry.
An `ASSUMED` record may cite the sharpening or a note that names the assumption.
An `OBSERVED` record cites a probe or a request record.
An `INFERRED` record cites the observed facts plus the framework or technology default.

A mutating probe's evidence entry states the probe, the side effect, and the restoration result.
A probe with no restoration states why restoration is not available.

The `canonical_class` is the freely named taxonomy class.
The `web_vulnerability_class` is the skills-suite class directory name.
A non-empty `web_vulnerability_class` must resolve to a suite class.
This keeps the decided field semantics: `web vulnerability class` is the suite class name.
A named class with no suite class sets `web_vulnerability_class` empty and `suite_gap: true`.
The `canonical_class` is always present.
The score terms cite the same evidence entries: the four risk factors cite the sharpening and probes; the rationale cites the vulnerability's evidence.

### 5.3 State and monotonicity

The `state` field is the latest gate.
The state is monotonic.
A write whose gate is lower than the persisted state updates the section content but leaves `state` unchanged.
The harness records the earlier signal as trail-only material in the run record's `trajectory`.

### 5.4 Gate sections

The write payload's `sections` is a mapping from section name to content.
The `state` selects the allowed section names:

| `state` | Allowed `sections` keys |
|---|---|
| `UNIT_TECHNICAL_SHARP` | `technical_sharpening` |
| `TRUST_MODELLED` | `trust_model` |
| `TRUST_ASSUMPTIONS_WRITTEN` | `assumptions` |
| `VULNERABILITIES_WRITTEN` | `vulnerabilities` |
| `COMPLETED` | `failure_modes`, `loops` |

A gate write merges its sections into the document.
A gate write never replaces the whole document.
The COMPLETED write does not carry `risk_profile`; the store computes it after the merge and before the commit.
The write payload never carries `unit_id`, a file name, a model id, or a storage path; the unit identity is bound at tool construction.
A gate write below COMPLETED deletes any stale loop files in the unit directory.
The next COMPLETED write writes the whole loop set.

### 5.5 Failure modes and drops

A vulnerability that is dropped carries `dropped: true`, `drop_reason`, and `drop_probe`.
`drop_reason` states the fundamental infeasibility finding or the misspecified trust agreement.
`drop_probe` names the discriminating probe shape that would have falsified the finding.
The drop corrects the interface or trust agreements it was mapped from; the correction is recorded in those agreements' evidence entries and confidence.

The vulnerability's failure modes stay in `failure_modes` with `dropped: true` and the same reason.
A dropped vulnerability has no loop.

A retained vulnerability whose feasibility fails carries a failure mode with `feasibility: infeasible` and a loop with `likelihood: none`.
It is not a drop.

### 5.6 Loops

The modeller writes the surviving loops in any order.
The store normalises the order at the COMPLETED write:

1. Stable sort by likelihood weight descending.
2. Ties preserve the modeller's write order.
3. Renumber the ids `loop-1`, `loop-2`, ... in that order.

The list order is the rank order.
Rank 1 is the highest likelihood weight.
The loop references its fault, its vulnerability, and at least one failure mode.
The loop's `canonical_class` and `web_vulnerability_class` repeat the vulnerability's values for dispatch convenience; the checker verifies they agree.
The loop's `confidence` grades the load-bearing premise.
The loop's `evidences` cite the grounding for the likelihood.
A loop whose likelihood is `none` carries the retention rationale and is not dispatched.

### 5.7 Completion checker

The completion checker is the `ratify` role.
It runs on the `COMPLETED` write.
It is non-blocking: it does not reject the write.
It sets `validation.valid` and records the findings.

It checks parseability and the complete model shape.
It builds the fault index from `assumptions[].fault.id`.
It checks the necessary attributes:

- `unit_id` non-empty.
- `unit_kind` valid.
- `technical_sharpening.interface_agreements` non-empty.
- `technical_sharpening.control_flows` non-empty.
- `technical_sharpening.data_flows` non-empty.
- `trust_model.trust_agreements` non-empty.
- `trust_model.dynamic_state_trust.states` non-empty.
- `assumptions` non-empty.
- Each assumption has a non-empty fault id, label, and description.
- `vulnerabilities` non-empty.
- Each vulnerability has a non-empty `canonical_class` and a `web_vulnerability_class` or a suite gap.
- `failure_modes` non-empty.
- Every vulnerability has at least one failure mode, unless the vulnerability is dropped.
- `loops` is present; it may be empty only when every vulnerability is dropped.
- Every loop has a non-empty rationale, valid risk factors, and at least one evidence entry.
- The loop order is non-increasing by weight and the ids are `loop-1..n`.
- The risk profile equals the harness-computed total and breakdown.

It checks referential integrity:

- Every `fault_ref` resolves to a fault id in the assumption index.
- Every `vulnerability_ref` resolves to a vulnerability.
- Every `failure_mode_ref` resolves to a failure mode.
- Every `boundary_ref` resolves to a trust agreement.
Every `Violation.maps_to_fault` resolves to a fault id.
- Every `interface_agreement_refs` entry resolves to an interface agreement.
- Every transition `source` and `target` resolves to a dynamic state.

It checks the assumption-to-loop closure:

- Every assumption closes to at least one vulnerability.
- Every non-dropped vulnerability closes to at least one non-dropped failure mode and at least one loop.
- Every loop refs a non-dropped vulnerability and non-dropped failure modes.
- A dropped vulnerability has a drop reason and a drop probe.
- An unclosed assumption is recorded in `unclosed`.

The checker recomputes the risk profile from the stored loops.
It compares the result to the stored `risk_profile`.
The store wrote the stored profile; the comparison is therefore a regression check against a store bug, not a trust of the modeller.

`validation.valid` is true only when `parseable` is true and `missing`, `unclosed`, and `referential_errors` are empty.

Consumability is:

```
state == COMPLETED and validation.valid == true
```

A model that fails the check is not consumed and not dispatched.
The harness moves its unit directory to `abandoned/`.
The run records the unit in `degraded_units` with the validation findings.
A later run retries the unit because no completed model exists.

### 5.8 Schema migration

The model is versioned.
A reader that does not know the document's `schema_version` refuses to consume it and records a degradation with the version.
A version-1 reader after a version-2 change follows the same rule.
The migration owner is the change that bumps the version.
The migration reads the old document, writes the new shape, and records the migration in the model's `validation` record.
No silent migration runs on a read.

## 6. The loop entity and the spec-set lifecycle

### 6.1 The loop

The loop is the research direction and the dispatch grain.
It is not a `HuntConfig`.
It carries no precondition or observed-defence fields.
Those are replaced by the trust agreement, the dynamic-state transition, and the loop rationale.

The loop is not statused.
The model is the artifact; the loops are its surviving ranked rows.
A `none` loop is retained with zero weight.
A dropped vulnerability has no loop.

### 6.2 State vocabulary

The hunting state values are exactly `{hypothesised, ratified, dropped}`.
The modeller's loops do not use this vocabulary; the model state uses the five gates.
The hunter's spec set uses the three values:

- `hypothesised`: the spec written at GENERATE.
- `ratified`: the surviving spec at the terminal write.
- `dropped`: the declassed spec at the terminal write.

`verified` and `specified` are retired everywhere.
A spec's terminal status is `ratified`.
The retired `HuntConfig` entity is not replaced by a config lifecycle; the only live hunting status vocabulary in this change is the hunter spec set's.

## 7. Risk scoring

### 7.1 The enum and the weights

The likelihood enum is `none`, `low`, `medium`, `high`, `critical`.
The weights are:

| Likelihood | Weight |
|---|---|
| `none` | 0 |
| `low` | 1 |
| `medium` | 2 |
| `high` | 3 |
| `critical` | 4 |

The weights are monotonic and strictly increasing.
The weights are a module constant.
The run records the weights.
The impact factor is excluded.
The score is likelihood only.

### 7.2 The scoring factors

The modeller reasons over four CVSS-inspired factors per loop:

- **Attack vector**: network, adjacent, local, physical.
- **Attack requirements**: none, present.
- **Privileges required**: none, low, high.
- **Complexity**: low, high.

The factor values are recorded in the loop's `risk_factors`.
The factor value sets are the CVSS v4.0 value sets for the four metrics.
The modeller uses the factor values to assign the likelihood class.
The class assignment is LLM-judged.
The factor record makes the judgement auditable.
The harness does not derive the class from the factors.
No user-interaction factor is used.
No impact factor is used.

The likelihood grounds in the unit's technical characteristics, the technical feasibility, the observed defences as mitigators, and training priors on high-yield bugs for the surface and service kind.
The loop's confidence degree is a factor of the class assignment.
The modeller lowers the class when the load-bearing premise is `ASSUMED` and records the reason in the rationale.
The harness weights only the class; the confidence is not an independent summand.
A brief ontology of the four factors is injected into the risk-scoring phase of the prompt.
The ontology defines each value in terms of the unit's metrics and state attributes.
The prompt does not present the class assignment as a CVSS score.
CVSS-derived wording carries attribution.

### 7.3 The per-unit total

The harness computes:

```
unit_total = sum(RISK_WEIGHTS[loop.likelihood] for loop in loops)
```

The per-level breakdown counts every loop by likelihood, including `none`.
The harness writes the total and the breakdown into the model's `risk_profile`.
The model's own total is not trusted; the harness value is authoritative.

Breadth coupling is accepted.
The total sums every loop.
There is no normalisation and no per-level cap.
Breadth is a feature of the phase.
A unit with many low loops can consume budget like a unit with a few high loops.
The calibration can revisit this choice.

### 7.4 The run accumulator and the threshold

The run accumulator is symbolic run state.
It is checked at each model completion.
The comparison is inclusive.
The crossing unit completes and is dispatched.
The next unit is never modelled.
The blocked unit is recorded.

The threshold default is `12`.
The threshold is overridable through the run configuration variable `HUNT_RISK_THRESHOLD`.
The run records the threshold and its basis (`default` or `override`).

The default is a starting constant, not a calibrated value.
The calibration procedure is:

1. Replay recorded models in intake order.
2. Compute the per-unit total with the fixed weights.
3. Choose the halt behaviour the operator wants.
4. Record the chosen threshold with the calibration set.

The T2 trial model (one high, five medium, three low loops) sums to 16 under the weights.
It crosses the default 12 in one unit.
This is a recorded sanity check, not a calibration result.

### 7.5 The cost boundary

The execution-wide token budget is a runtime-plane hard stop.
The risk budget is the modelling cap.
No probe cap is scoped to the modeller.
No impact term is added.

### 7.6 Unreliability risks

The scoring carries known risks:

- LLM score variance across runs.
- Central-tendency compression toward the middle of the scale.
- Pseudo-precision when the four factors are guessed.
- A score that is not calibrated on this domain.

The mitigation is the audit trail: the four factors, the rationale, the confidence degree, and the evidence entries.
The calibration set and the audit trail are implementation work items.
The deterministic/LLM split is fixed: the LLM assigns the class and factors; the harness sums.

## 8. Consumption and the hunter payload

### 8.1 The loop file

A loop file carries:

```
loop_id: loop-<rank>
unit_id: str
unit_kind: service | system
run_id: str
dispatch_id: <unit_name>__<loop_id>
likelihood: Likelihood
loop: Loop
created_at: datetime
```

The loop file does not duplicate the model.
The surfer reads the model document for the unit context.
The model document remains in `produced/` until its last loop file is consumed.

### 8.2 The hunter payload

The surfer materialises the payload at dispatch time.
The payload carries:

- The loop record.
- The unit id and unit kind.
- The relevant technical sharpening: the interface agreements referenced by the trust agreement or the transition, plus the control-flow and data-flow overview.
- The relevant trust agreement, or the dynamic-state transition and its trust-transition violation.
- The programming fault.
- The `canonical_class` and the `web_vulnerability_class`.
- The evidence pointers from the loop, including any recorded HTTP-history artifact ids, so the hunter can choose a baseline.
- The likelihood and the vulnerability-level rationale.
- The confidence degree.
- The target context needed to author the spec's target identity.

The payload does not carry:

- Failure modes.
- Any narrowed vector or payload.
- A `HuntConfig`.
- A pre-authored payload vector space.

The rationale stays vulnerability-level.
The hunter keeps the room to engineer its own procedure.

### 8.3 Dispatch sequencing

`critical`, `high`, and `medium` loop files dispatch immediately.
`low` loop files wait until no critical, high, or medium loop file is produced and no critical, high, or medium hunter session is live.
`none` loops have no file.

The sequencing is cross-unit and run-scoped.
A loop file from another run is not dispatched by this run.

### 8.4 Consumption and quiesce

The mover's dispatch grain is the loop file.
The move to `consumed/` happens on dispatch admission.
The model document moves when its last loop file is consumed.
A zero-loop model is consumed by the mover on its next tick without a dispatch.

The work read includes a produced `COMPLETED` model with `validation.valid` true and no loop files; the mover consumes it without a dispatch.
The quiesce predicate is the existing `run_work_remaining` / `is_run_quiesced` seam, updated to the loop files:

- The modeller pass has settled.
- No produced loop file is dispatchable now.
- No hunter or pod session is live.

The work read and the dispatch read share the one validity predicate.
A stopped role gate pauses dispatch; it does not change the quiesce predicate.
The low-loop pause is a per-tick condition: a low loop is released when no known higher-ranked loop file is produced and no higher-ranked session is live.
A later unit's high loop can therefore arrive after an earlier low loop has been dispatched.
This is accepted: the run is streaming and a later high loop cannot preempt work already admitted.

A low loop is dispatchable now only when no higher-ranked session is live.
A produced loop file from another run does not hold this run's quiesce.

## 9. Run record and cross-run semantics

### 9.1 The model never evolves

A model is terminal at COMPLETED.
There is no model evolution, no change-driven re-model, and no version pin.
A new run excludes a unit with a completed model.
A new run over a new model requires an explicit operator action outside the run; that action is out of scope.

### 9.2 The run record

The run record carries:

- `intake_order`: the ordered unit ids.
- `intake_position`: the index of the next unit to model.
- `intake_excluded`: the excluded unit ids with reasons `completed` or `in-flight`.
  An `abandoned/` model is ignored and retried, not excluded.
- `risk_threshold`.
- `threshold_basis`: `default` or `override`.
- `risk_weights`.
- `risk_total`.
- `risk_breakdown`: the sum of the per-model breakdowns.
- `model_sums`: one entry per modelled unit with `unit_id`, `total`, and `breakdown`.
- `crossing_unit`.
- `blocked_unit`.
- `halt`.
- `degraded_units`: the unit ids with their validation or degradation reason.
- `trajectory`: the bounded list of state and gate entries.

A `trajectory` entry is:

```
{unit_id, signal, from_state, to_state, outcome, at}
```

The trajectory is bounded by the number of units and gates.
It lives in the run record, not in the model document.

The run record is persisted with the run row.
It survives a restart.

### 9.3 Intake exclusion

A unit is excluded when a completed model exists in `consumed/`.
A unit is skipped when a model is in flight in `produced/` and its producing run is live or resumable.
The in-flight skip prevents a second writer on one unit.
The earlier run must be resumed to drain its produced loops.
A model in `abandoned/` is ignored; the unit is retried.
When the producing run is terminal and not resumable, the new run's intake moves the stale produced directory to `abandoned/` and retries the unit.

### 9.4 Halt audit

The intake order, the per-unit sums, the crossing unit, and the blocked unit carry the halt's audit trail.
The order is never re-sorted.
The halt never re-ranks the intake.

## 10. Implementation decisions

### 10.1 The store class

The store is `ThreatModelStore`.
It owns the project root, the produced and consumed directories, the model documents, the loop files, and the notes.

It reuses these established patterns:

- The `HuntStore` / `HunterMemoryStore` atomic-write and move-aware discipline.
- The `BoundedRecordStore` bounds for the notes.
- The `spec_identifier`-style keyword sanitisation for spec identities.
- The shared `notes` tool base with a caller-bound handle.
- The coded teaching rejection for a missing or malformed derivation input.

The implementation follows the patterns recorded in `src/polymerhus/attack/hunting/CONTEXT.md`: the atomic store writes (#340), the bounded whole-file notes store (#341), the shared tool-contract base (#293), the hunter memory store, the hunt store, and the inbox surfer and mover with the at-least-once marker.
The store replicates the pattern; it does not import another store's namespace.

### 10.2 Derived symbols

The store owns:

- The unit directory name.
- The model document name.
- The loop file name.
- The loop id.
- The dispatch id.
- The note key prefix.

The harness binds the unit id; the modeller never authors it.
The modeller owns:
- The model values.
- The loop likelihood and rationale.
- The evidence entries.

A write payload never carries a derived symbol.

### 10.3 The write tool

The modeller's `hunts_store` tool is a typed `BaseTool` with `extra="forbid"`.
It binds the current unit identity at construction.
The name `hunts_store` is shared with the hunter; each role binds its own store.
The modeller's binding is the threat-model store; the hunter's binding is the spec store.
It accepts `cmd: read | write`.
The write payload is `{state, sections}`, where `sections` is a mapping keyed by section name.
The response injects the next-state hint.
The read payload is `{cmd: read, unit_id?, section?}`.
A read with no `unit_id` reads the bound unit.
A read with a `unit_id` reads that unit's model for prior-model inspection.
A read with a `section` returns only that section.

### 10.4 The loop files

The store emits one loop file per loop with `likelihood != none`.
The loop file is written atomically.
The loop file's `dispatch_id` is `<unit_name>__<loop_id>`.
The file name is `loop-<rank>.yaml`.

### 10.5 The convergence

The store and the surfer share one validity predicate:

- A loop file is dispatchable work when its likelihood is not `none`, its model state is `COMPLETED`, its model `validation.valid` is true, and its run id matches the current run.
- A model document is complete and consumable when its state is `COMPLETED` and its `validation.valid` is true.

The predicate is used by both the work read and the dispatch read.
A malformed loop file is refused, stays produced, is logged once, and cannot hot-loop the mover or wedge the quiesce.

## 11. Testing decisions

### 11.1 What makes a good test

Test the persisted files and the public store API.
Use a temporary project root.
Assert the model document, the loop files, the risk profile, and the validation record.
Do not assert private methods.
Keep every write atomic and every failure fail-open.

### 11.2 Seams

- The model schema: parse, reject unknown fields, reject a non-monotonic state write.
- The gate merge: each section extends the model without replacing the others.
- The completion checker: missing attributes, referential integrity, closure, ordering.
- The commit protocol: loop files first, model document last; a crash between them leaves the previous state.
- The loop emission: one file per non-`none` loop; no file for `none`.
- The move: model document with the last loop; zero-loop model consumed at completion.
- The risk profile: harness total and breakdown.
- The validity predicate: work and dispatch agree.
- The intake exclusion: completed, in-flight.
- The run record: all keys.
- The notes store: bounded, atomic, move-aware.

### 11.3 Prior art

Reuse the patterns of:

- The hunt-store atomic and move-aware tests.
- The hunter-memory spec-file and notes tests.
- The store-write decision tests for derived symbols and coded rejections.
- The wiring mover tests for produced-to-consumed delivery.

## 12. Out of scope

- The modeller agent contract (S1).
- The hunter workflow and typed surface (S3).
- The harness FSM (S4).
- The pod contract (S5).
- Model evolution and change-driven re-modelling.
- Surface recovery.
- The eval harness translation (S1 9.5).
- Alpha-omega, full CVSS base metrics, and TBSG boundary records.

## 13. Further notes

The workbench is the decision authority.
The workflow document is the workflow contract.
The risk-scoring research note carries the evidence for the scheme.
The impact map carries the supersession ledger.

The model schema is versioned.
A later schema change must migrate the version.
The model document is the commit marker.
The loop file is the dispatch grain.
The model never evolves.
