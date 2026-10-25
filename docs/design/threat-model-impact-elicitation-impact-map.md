# Threat-model impact elicitation: impact map

*Status: pre-grilling dependency map. This document lists every component that reads the threat-model loop or the failure-mode artifact, the change each component needs, and the order that keeps the tree green. It is not the final spec; the grilling round settles the scoring algorithm and the phase boundaries.*

## 1. End state

Five changes land together:

1. **Impact-first elicitation.** The modeller scores every loop with a CVSS 4.0-like impact judgement over the application and its users: vulnerable confidentiality, integrity, and availability. The modeller reasons in adversarial capabilities and vulnerability chains, not in single-system failure.
2. **Combined risk score.** The loop risk is a multiplication of the likelihood weight and the impact weight. The unit profile sums the loop risks. The dispatch order and the intake halt use the combined score.
3. **Failure modes removed.** The `failure_modes` artifact, the `failure_mode_refs` link, the prompt phase, and every reader and writer of that artifact go away. The pod `failure-mode` variant basis goes away. The hunter's failure-mode vocabulary is replaced by attack primitives and exploit chains. Feasibility moves to the hunter and the pod.
4. **Iterative trust modelling.** The linear `trust_model -> assumptions -> vulnerabilities` stretch becomes a loop. A well-formedness pseudo-phase sits between `VULNERABILITIES_WRITTEN` and `COMPLETED`. It loads the class skill for each loop, counterchecks the trust assumptions, and either patches the model or loops back over the undermodelled part. The model enters the phase by reasoning, patches by writing a lower gate (`trust_model`, `assumptions`, or `vulnerabilities`) after vulnerabilities, and exits by writing one `wellformedness` note and then `COMPLETED`. The passive tracker already records the lower-gate write as `lower_gate`, which is the re-entry signal. The note is the exit memory, written once. The loop has no iteration bound; the run cap is the bound.
5. **Class binding guard.** Every loop carries a suite class. Technique families (`defence-bypass`, `proxy-techniques`, `two-principal-authz`) and non-suite names are prompt-forbidden and recorded as non-blocking completion findings, never as symbolic rejections.

## 2. Scoring model

The operator settled the algorithm on 2026-10-25.

- Replicate the CVSS 4.0 impact logic in a light form, not the official calculator.
- Score only the vulnerable system's confidentiality, integrity, and availability: `VC`, `VI`, `VA`.
- Do not score a separate subsequent system. The operator wants the modeller to reason in adversarial capabilities and vulnerability chains, not in single-system failure.
- Elicit the attacker capabilities gained, the target application state, and the literal end damage to the application or its users.
- Combine likelihood and impact by multiplication.
- Keep the risk profile deterministic and computed by the store, never authored by the modeller.

The algorithm is:

```
metric weights: N = 0.00, L = 0.22, M = 0.35, H = 0.56
impact = 1 - (1 - VC) * (1 - VI) * (1 - VA)
impact_weight = 0 if impact == 0
              = 1 if impact <= 0.25
              = 2 if impact <= 0.50
              = 3 if impact <= 0.75
              = 4 otherwise
loop_risk = likelihood_weight * impact_weight
unit_total = sum(loop_risk)
run_total = sum(unit_total)
crossed = run_total >= threshold
```

The ranking is risk descending, then impact descending, then likelihood descending, then the modeller's write order.
The dispatch buckets are critical `>= 12`, high `8..11`, medium `4..7`, low `1..3`, none `0`.
The provisional default threshold is `360`, because the baseline corpus yields about 356 under the provisional ordinal mapping.
The A/B sets the threshold per arm.
The run record stores the likelihood weights, the impact weights, the impact breakdown, and the risk breakdown.
The modeller authors the three metrics and a literal end-impact statement; the store computes every score.

The ordinal impact weight is what the run record stores. The raw metrics stay on the vulnerability and the loop for audit.

## 2.1 Trust characterization axes

The framework lives only in the prompt.
The chain of thought compiles into the trust agreement and the assumption, as it does today.
The four axes carry equal structural weight.
`temporal` may be shorter when the unit has few state transitions; do not pad it.

### Identity

The privilege-level context held in the interaction.
Provenance, authority, delegation, and whether the claimed principal is bound to the caller, the session, the resource, and the function.
The question is not only who the artifact says it is, but whether the receiver re-establishes that claim from its own state.

### Spatial

Every attribute that can extend the artifact in breadth or depth, and the mutation and lifecycle of the objects that carry or target it.
Enumerate the spatially significant variables exposed at each interface and introduced during later processing:

- headers, URL schemes, hosts, ports, paths, fragments, query and positional parameters;
- cookies, request-body fields, multipart fields, resource identifiers;
- attributes introduced by middleware or downstream transformations.

Determine how those variables select, reference, or expand the scope of persisted and runtime objects, users, filesystem locations, hosts, tenants, and other resource domains.
Examine value domains, hierarchy, cardinality, reachability, and mutability, including object substitution, path traversal, aliases, symbolic links, redirects, DNS resolution, indirect references, and cross-tenant or cross-namespace access.
Identify the content representations they carry or resolve into: scripts, queries, filesystem paths, URLs, network addresses, templates, serialized objects, and resource identifiers.
Trace how the effective scope changes through embedding, concatenation, substitution, decoding, normalization, canonicalization, or wrapped encodings.
Trace the artifact's origin and lifecycle across creation, transformation, persistence, caching, queuing, replication, and service-to-service propagation.
Establish which components can influence its attributes and which objects or resources it can reach.
Distinguish identifiers that select or locate a target resource from identity claims that establish the caller's identity.
This axis uses the data-flow tracking and data-plane logic of the technical sharpening.

### Temporal

State and time, mainly as trust agreements over application-state transitions.
The most insightful claims name which functions or processes are assumed not to execute concurrently in the state.
Cover replay, freshness, partial states, stale cached data, and fail-open or fail-safe fallbacks for unhandled transitions.
Cover silent payload activation, including time-of-check to time-of-use and DNS rebinding.

### Controls semantics

The precise trust-invariant verification applied to every untrusted or conditionally trusted artifact attribute and to every impacted state change.
Characterize the constraints apparently applied across all relevant data dimensions:

- strict deserialization against fixed schemas, type and range constraints, allowlists, strict enum comparisons;
- context-sensitive sanitization and encoding, canonicalization, cross-field dependency validation;
- binding of resource references to caller authority, ownership, tenant scope, and hierarchical relationships;
- independent establishment of security-sensitive identities and claims versus reliance on supplied values;
- constraints on network destinations derived from request parameters, hostname construction, DNS resolution, and redirects.

Capture the placement and consistency of those controls across processing stages, including whether their guarantees extend to the effective representation consumed downstream and survive transformation, persistence, caching, delegation, and state change.
Name implicit coercions, permissive defaults, incomplete or inconsistent enforcement, and gaps between syntactic validity and semantic safety.
For each attribute, distinguish verification guarantees supported by observable evidence from those inferred or assumed but unverified.
State the extent to which the receiving component's enforcement semantics constrain unauthorized resource access, unsafe interpretation, or impermissible control-flow transitions.

## 2.2 Composite example (prompt draft)

The example is synthetic, so it does not overfit to the eval target.
It shows the four trust axes, the TOCTOU assumption, the impact metrics, the well-formedness check, and the low-yield contrast.

**Unit.** `Service:cover-fetch`, a service that fetches a remote image for a book cover.

**Technical sharpening.**
- `IA-1`: `POST /api/cover/fetch` takes `{"source_host": "<host>", "path": "<path>"}` and returns the fetched image.
- `CF-1`: the handler joins `source_host` and `path`, validates `source_host` against an allowlist, then fetches the URL.
- `DF-1`: `source_host` -> URL construction -> DNS resolution -> outbound HTTP request.

**Trust agreement.**
- `TA-1` (`spatial`): `source_host` selects a network destination. The handler joins it into a URL and fetches it.
- `TA-1` (`temporal`): the allowlist check runs when the service initialises its host list, not when the request fetches.
- `TA-1` (`controls_semantics`): the allowlist compares the submitted host string. It does not check the resolved address or a redirect target.
- The trust is that the host validated at initialisation is the host fetched at use.

**Assumption and fault.**
- `A-1`: the developer assumed the validated host is the fetched host.
- `F-1`: the allowlist is evaluated on the initial host string, while the fetch resolves the hostname again and follows redirects without revalidation.
- The temporal gap is time-of-check to time-of-use. The controls gap is that the check sits at a different layer from the use.

**Vulnerability and impact.**
- `V-1`: SSRF via TOCTOU host re-resolution and unchecked redirects.
- `VC=H`, `VI=L`, `VA=N`: `impact = 1 - (1 - 0.56)(1 - 0.22)(1 - 0) = 0.6568`, `impact_weight = 3`.
- The end impact is a read of the cloud metadata endpoint and internal admin services from the application's network position. The attacker gains internal reach and can chain the metadata credential into the cloud account.

**Well-formedness check.**
- Loop `loop-1` binds `ssrf`.
- Load `ssrf`. The Trust Assumptions section says the destination must be revalidated at fetch and the resolved address constrained.
- The model missed the redirect target. The gap is local: the spatial boundary exists, and the temporal and controls assumptions are incomplete. Add `A-2` "the redirect target is not revalidated" and `F-2`, then re-check.
- No structural gap. Write the well-formedness note. Complete.

**Low-yield contrast.**
- A soft-404 contract divergence is recorded as an assumption, not a loop.
- Its `VC=VI=VA=N`, so the impact weight is `0` and the loop risk is `0`.
- It does not dilute the green-loop share.

## 2.3 Well-formedness note (exit only)

The note is written once, when the modeller judges every assumption well-formed.
If the modeller re-enters the loop, it writes a lower gate first, and the tracker records `lower_gate`.
No note is written for an intermediate iteration.

```
kind: wellformedness
loops_checked: [loop-1, loop-2]
skills_loaded: [ssrf, broken-function-level-authorization]
assumptions_added:
  - boundary_ref: TA-1
    text: "the redirect target is not revalidated at fetch"
structural_gap: false
structural_finding: ""
action: complete
```

The note name is stable.
The trail records the lower-gate writes, so the iteration count is derived, not authored.

## 3. Dependency map

### 3.1 Threat-model schema and store

| Component | Reads or writes | Change | Convergence step |
|---|---|---|---|
| `attack/hunting/threat_model.py` `FailureMode` | schema | Delete the class | Expand: add impact first; contract: delete after no reader remains |
| `threat_model.py` `Loop.failure_mode_refs` | schema | Delete the field | Same |
| `threat_model.py` `ModelSections.failure_modes` | write schema | Delete the field | Same |
| `threat_model.py` `GATE_SECTIONS[COMPLETED]` | gate table | Replace `failure_modes` with the impact-bearing loops section | Expand: accept both during migration; contract: one section |
| `threat_model.py` `Vulnerability` | schema | Add `impact` (VC, VI, VA, end-impact statement, ordinal weight) | Add before the loop projection |
| `threat_model.py` `Loop` | schema | Add `impact` and `risk` (copied or computed) | Add before the ranking change |
| `threat_model.py` `RISK_WEIGHTS` | score table | Add `IMPACT_WEIGHTS`; keep `RISK_WEIGHTS` for likelihood | Add beside the existing table |
| `threat_model.py` `compute_risk_profile` | pure | Sum `likelihood_weight * impact_weight`; add the impact breakdown | New tests first |
| `threat_model.py` `normalise_loops` | pure | Sort by combined score, ties by impact then likelihood | New tests first |
| `threat_model.py` `check_completion` | pure | Remove failure-mode checks; add impact completeness and class-binding findings | New tests first |
| `threat_model_store.py` `MODEL_SECTIONS` | store | Remove `failure_modes`; add the impact section if separate | Expand then contract |
| `threat_model_store.py` `write_sections` | store | Accept the new gate shape; stop emitting failure modes | Expand then contract |
| `threat_model_store.py` loop files | store | Carry impact and risk in each loop file | Add before the mover reads it |
| `threat_model_store.py` `is_consumable` | store | Unchanged semantics; a valid COMPLETED model is consumable | Regression test |

### 3.2 Modeller prompt, tools, and turn input

| Component | Reads or writes | Change | Convergence step |
|---|---|---|---|
| `prompts/threat-modeller.md` | prompt | Rebalance Branch A; add the condensed trust axes; add field and state elicitation; add impact elicitation; remove failure-mode deduction and the encoding floor; add the well-formedness loop; add the class guard; add the composite example | Rewrite in one reviewed pass after the schema settles |
| `threat_modeller_tools.py` `ModellerHuntsStoreArgs` | tool schema | Remove `failure_modes`; add impact | Follow the schema |
| `threat_modeller_tools.py` `hunts_store` description | tool description | Update the gate list, the reference table, and the class copy rule | Prompt review |
| `threat_modeller_tools.py` `skill_list` / `skill_load` | tool | Expose the class and leaf index for the non-blocking class finding | Add a pure lookup seam |
| `threat_modeller_tools.py` `notes` | tool | Accept the `wellformedness` note kind; the note is the exit memory and does not advance the persisted state | Add the kind; no store gate |
| `threat_modeller.py` `ModelState` | enum | No new value. The well-formedness phase is a pass-level pseudo-phase between vulnerabilities and completed | The tracker reads the lower-gate write as the re-entry signal |
| `threat_modeller.py` `arun_modeller_pass` | runtime | Ask the well-formedness turn after vulnerabilities; re-ask it after a lower-gate write; exit on the note plus the COMPLETED write | New pass tests |
| `threat_modeller.py` `ModellerTurnInput` | turn data | Carry the pseudo-phase identity and instruction | Follow the pass |
| `threat_modeller.py` `STATE_INSTRUCTIONS` / `GATE_HINTS` | prompt data | Add the well-formedness entry and the impact exit | Follow the state decision |
| `threat_modeller.py` `ModellerTurnInput` | turn data | Render the impact state and the class coverage | Follow the prompt |
| `attack/hunting/CONTEXT.md` | vocabulary | Add end impact, combined risk, well-formedness, class binding; remove failure-mode definitions | Docs pass |

### 3.3 Risk accumulation, dispatch, and run record

| Component | Reads or writes | Change | Convergence step |
|---|---|---|---|
| `run_lifecycle.py` `model_sum` | pure | Sum the combined loop risk; add the impact breakdown | New tests first |
| `run_lifecycle.py` `RiskAccumulator` | pure | Carry the combined total and both breakdowns | New tests first |
| `run_lifecycle.py` `risk_weights` | config | Return the likelihood and impact weight tables | Run-record compatibility |
| `run_lifecycle.py` resume | pure | Recompute the combined total from `model_sums` and the models | Regression test |
| `runtime.py` threshold and record | runtime | Log and persist the combined total; keep the threshold basis | Integration test |
| `pipeline_sync.py` `_loop_weight` / `_risk` | pure | Use the combined loop risk | Unit test |
| `mover.py` `ThreatLoopItem` | pure | Carry the risk score and the priority tier, not only likelihood | Expand: keep likelihood; contract: drop it from the sequencing |
| `mover.py` `sequence_dispatch` | pure | Gate on the risk priority, not the likelihood tier | New tests first |
| `surfer.py` live-loop map | runtime | Carry the risk priority instead of the likelihood | Follow the mover |
| `hunting_status.py` | status | Render the combined breakdown | Integration test |
| `run_lifecycle.py` `RISK_LEVELS` | config | Keep the likelihood levels; add the impact levels | Compatibility |

### 3.4 Hunter payload and prompt

| Component | Reads or writes | Change | Convergence step |
|---|---|---|---|
| `hunter_payload.py` | pure | Add `impact`, `impact_rationale`, and `risk` to the payload; remove any failure-mode field | Payload tests |
| `hunting_agent.py` first human | prompt | Render the impact and the attack-primitive framing | Prompt review |
| `prompts/hunting-agent.md` | prompt | Replace failure-mode vocabulary with attack primitives and exploit chains; keep the hunter's engineering freedom | Prompt review |
| `hunter_state.py` / `hunt_store.py` / `hunter_memory.py` | state and memory | Carry the new payload fields; remove failure-mode references | Regression tests |
| `pod/*` | pod | Remove the `failure-mode` variant basis and the `failure_mode_plausible` field | Expand then contract |
| `prompts/pod-triager.md` | prompt | Remove step 5, the table row, and the field | Prompt review |
| `pod/variant_basis.py` | pure | Remove the `FAILURE_MODE` literal and fallback; return `None` when no gap remains | Unit tests |
| `pod/agents.py` / `pod/graph.py` / `pod/context.py` | code and prompt | Remove the fallback condition and the prompt mention | Follow the basis removal |

### 3.5 Design specs and ADRs

| Document | Change |
|---|---|
| `docs/design/hunting-67-threat-modeller-spec.md` | Problem statement, phases, risk scoring, prompt material, out-of-scope |
| `docs/design/hunting-67-threat-model-artifact-spec.md` | Schema, loop fields, failure-mode removal, risk profile |
| `docs/design/unit-threat-model-workflow.md` | Five phases plus the well-formedness loop; gate shapes |
| `docs/design/unit-threat-model-workbench.md` | Q14, Q33, Q38, R3-1, R3-2, R8-4 decisions superseded |
| `docs/design/unit-threat-model-assertions.md` | Assertions for impact, risk, class binding, well-formedness |
| `docs/design/unit-threat-model-spec-impact-map.md` | Component impact list |
| `docs/design/unit-threat-model-ordering-halt-adr.md` | Combined score and threshold recalibration |
| `docs/design/unit-threat-model-risk-scoring-research.md` | Mark the impact-excluded recommendation superseded |
| `docs/design/unit-threat-model-prompt-synergy.md` | Prompt structure and example |
| `docs/design/hunting-67-hunting-agent-spec.md` | Remove the failure-mode slice; add attack primitives |
| `docs/design/hunting-84-pod-memory-system-spec.md` | Remove the failure-mode variant basis |
| `docs/design/hunting-67-test-executor-pod-spec.md` | Remove the failure-mode variant basis |
| `docs/design/hunting-pipeline-sync-adr.md` | Dispatch priority uses the combined risk |
| `src/polymerhus/attack/hunting/CONTEXT.md` | Vocabulary and contracts |
| New ADR `docs/design/threat-model-impact-elicitation-adr.md` | Record the failure-mode removal, the impact scoring, the well-formedness loop, and the class guard |

### 3.6 Tests and fixtures

| Area | Tests |
|---|---|
| Threat model | `test_threat_model_store.py`, `test_threat_modeller.py`, `test_threat_modeller_prompt.py` |
| Modeller wiring | `test_hunting_modeller_wiring.py` |
| Risk and dispatch | `test_run_lifecycle.py`, `test_hunting_mover.py`, `test_hunting_loop_dispatch.py`, `test_hunting_pipeline_sync.py`, `test_hunting_pipeline_sync_gate.py`, `test_hunting_mover_sync_filter.py`, `test_hunting_surfer_sync_wiring.py` |
| Hunter payload and prompt | `test_hunting_agent.py`, `test_hunting_agent_prompt.py`, `test_hunter_state.py`, `test_artifact_skill_config.py`, `test_hunting_review_fixes.py` |
| Pod variant basis | `pod/test_variant_basis.py`, `pod/test_variant_mint.py`, `pod/test_prompts.py`, `pod/test_spec_reads.py`, `pod/test_prompt_memory.py` |
| Fixtures | `tests/hunting_fixtures.py` |
| E2E | `tests/e2e/test_pod_e2e_nfr.py`, `tests/e2e/test_test_executor_pod_walkthrough.py` |
| Eval | Check the eval prompts for threat-model failure-mode references; leave generic diagnosis language alone |

## 4. Convergence sequence

The failure-mode removal is a wide refactor. Use expand-contract so every commit stays green.

### Phase 0: Baseline and decisions

- Baseline report committed.
- Grilling answers recorded.
- This impact map committed.
- New ADR drafted.

### Phase 1: Impact schema and combined score (expand)

- Add `Impact` to `Vulnerability` and `Loop`.
- Add `IMPACT_WEIGHTS` and the combined `compute_risk_profile`.
- Keep `failure_modes` optional and unused by the new score.
- Add the impact to the loop file and the hunter payload.
- Add tests for the metrics, the weight mapping, the profile, and the ranking.
- The old models still parse because the new fields are optional or defaulted.

### Phase 2: Run risk and dispatch

- `model_sum`, `RiskAccumulator`, `pipeline_sync`, and the mover use the combined score.
- Keep the likelihood fields for compatibility; add the risk priority.
- The threshold is recalibrated in the run record; the A/B sets it per arm.
- Tests: accumulator, resume, dispatch order, low-priority gating.

### Phase 3: Prompt rewrite

- Rewrite the modeller prompt: trust axes, field and state elicitation, impact elicitation, well-formedness loop, class guard, composite example.
- Remove the failure-mode phase and the encoding floor.
- Update the hunter prompt vocabulary.
- Update the pod triager prompt and remove the failure-mode basis.
- Review each prompt adversarially for concision, completeness, and cohesion.

### Phase 4: Failure-mode contraction

- Remove `FailureMode`, `failure_mode_refs`, `ModelSections.failure_modes`, the store section, the completion checks, the payload fields, the pod basis, and the prompt remnants.
- Update every test and fixture.
- Remove the old gate shape.

### Phase 5: Docs and ADR

- Update the design specs listed in section 3.5.
- Record the failure-mode removal and the observed no-rejections evidence in the ADR.
- Update `CONTEXT.md`.

### Phase 6: Verification

- Run the focused suites, then `tests/attack`, then the pod integration and e2e suites.
- Run `compileall`.
- Run the A/B on the fresh instance with the 7M budget per the operator's later protocol.
- Measure against the baseline: the high-yield share of prioritised loops, the sharp-boundary share, the class-binding rate, the severe-below-high count, and the capped tokens per severe loop.

## 5. Settled decisions and the remaining frontier

Settled on 2026-10-25:

1. The impact metrics are `VC`, `VI`, `VA` only. No subsequent-system metrics and no `max`.
2. The impact formula, metric weights, ordinal mapping, loop risk, ranking, dispatch buckets, and provisional threshold are fixed in section 2.
3. The trust axes are `identity`, `spatial`, `temporal`, and `controls_semantics`, with the definitions in section 2.1.
4. The well-formedness phase is a pass-level pseudo-phase, not a new `ModelState`. The model enters it by reasoning after `VULNERABILITIES_WRITTEN`. A lower-gate write is the re-entry signal; the tracker already records it as `lower_gate`. The exit is one `wellformedness` note followed by the `COMPLETED` write. The note is the exit memory only, never a per-iteration note. The loop has no iteration bound.
5. The drop rule has two clauses: the data is not attacker-influenced, or the trust agreement is misspecified. Unobserved assumptions survive. A missing observation or a failed probe is not a drop reason. The modeller still judges exploitability through the likelihood score, because the likelihood names the adversarial capabilities the attack needs. The hunter and the pod own technical feasibility and effective attempt.
6. The 90% metric is the green-loop share over all stored loops. A green loop is a loop whose `web_vulnerability_class` is in the strict high-yield set plus CSRF and clickjacking. The set is the one ratified before this workstream.
7. The hunter loses every reference to the failure-mode attribute. It does not gain a replacement vocabulary. Its reasoning stays over the existing axes: vulnerability variants, manifestation, testing technique, framework or protocol misconfiguration, and payload vector class.
8. The class binding requires a suite class parent or leaf on every loop. `suite_gap` is removed. A novel class binds its nearest parent and keeps the novel name in `canonical_class`. Technique families stay in the characterisation prose. The non-blocking finding covers an empty class, a technique family, and a name outside the suite.

Remaining frontier:

1. **The composite example.** The operator chose SSRF with TOCTOU: a parameter concatenated in URL construction, a temporal check, and a controls-semantics check that may happen at initialization, which yields a TOCTOU equality assumption and SSRF. The example must show the full workflow, the impact metrics, and the well-formedness check.
2. **The well-formedness note content.** The exact fields the note carries at the exit: loops checked, skills loaded, assumptions found, structural versus local, and the final action.
3. **The hunter prompt cleanup.** The exact list of failure-mode references to remove: the loop ontology, `[D1]`, the grounding target, the slice pass, the exhaustiveness sentence, and the example.
4. **The A/B protocol.** The 7M budget per arm or total, the unit set, the fresh-instance reset, and the measurement window. The operator will specify the eval details after implementation.
5. **The threshold per arm.** The default is `360`; the A/B sets it per arm. The arms must not differ in the threshold or the comparison is not fair.
6. **The scoring calibration.** The baseline impact tiers are not the new metrics. The `360` default is provisional until the first re-model writes real `VC/VI/VA` values.

## 6. Non-goals

- No new hunting role.
- No change to the L1 intake or the unit projection.
- No change to the pod's execution contract beyond the variant-basis removal.
- No change to the eval orchestrator's assessment or diagnosis vocabulary.
- No rewrite of the historical experiment reports. New reports record the new baseline and the A/B.
