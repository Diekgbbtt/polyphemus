# Trial T1-TBSG - integrated threat_model typed surface

*Status: experiment integration record, 2026-10-18. This is the typed surface used by the treatment run `t1-tbsg-service-model-download` (run book: `input.md` in this directory). It implements the recommended options of the abduction research note (`docs/design/unit-threat-model-abduction-research.md`, sections 6.2, 6.3, 6.4, and 7) as they apply to a live trial. The production surface is not built; this record plus the trial evidence feed the adoption decision.*

## 1. What the integration implements

| Research-note decision | Implementation in this trial |
|---|---|
| Neutral first-party record names (Q1 recommended) | The model and the run book use "boundary record", "establishes", "requires", and the lowercase dimension names; no TBSG vocabulary appears in the model. |
| Record at the trust states (Q2 recommended; note section 6.2) | State 1 collects `artifact` and `establishes` per interface agreement; state 2 completes `requires` for interface records and writes the full transition records. |
| Explicit `requires` field (Q3 recommended) | Adopted, per interface trust agreement and per transition. |
| Only local/propagated, no P1/P2/P3 (Q4 recommended) | `propagation.kind` is `local` or `propagated` with `origin_ref`; no priority labels. |
| Hunter-payload rendering (Q5) | Not exercised in this trial; the model-side fields are present so the rendering question stays decidable later. |
| Necessary attributes in the loose checker (Q6) | Not exercised; the trial has no harness checker. The fields are simply present. |
| Transition records for every modelled EFSM transition (Q7 recommended) | Adopted; the run book requires a boundary record per transition. |
| Bounded composition depth (Q8) | Walk only what the EFSM already models; no interleaving enumeration; carrier-less composition claims are out of scope and go to `evidence_gaps`. |
| Replay validation (Q9) | Superseded for now by this empirical evaluation; the report records what a replay would still add. |
| TBSAM as the settled grounding (Q10) | The run book carries the four dimensions and the record shape from the research note only. |
| Dimension excluded from the risk score (Q11) | Not exercised (no scoring in the trial); the model keeps the dimension out of the loop records. |
| No-validation case recorded inside the record (Q12 recommended) | Adopted; a missing check is recorded as "no validation present" inside `establishes`. |

## 2. The integrated surface (fields used in the trial)

### 2.1 `technical_sharpening.interface_agreements`

| Field | Type | Definition |
|---|---|---|
| `id` | string | unchanged |
| `statement` | string | unchanged (what the interface agreement is) |
| `artifact` | string | the crossing item: request, message, token, response, file |
| `establishes` | list of `{item, layer, rung, evidences}` | the checks the receiving side actually applies and what each establishes; `layer` cites the request-handling stack layer or a framework default; a missing check is recorded as "no validation present" |
| `rung`, `evidences` | unchanged | record-level rung and evidence, as before |

### 2.2 `trust_model.trust_agreements`

| Field | Type | Definition |
|---|---|---|
| `id`, `statement` | unchanged | the trust agreement over data attributes, application contexts, principal privileges |
| `requires` | list of `{item, kind, rung, evidences}` | what the receiving side relies on before it can process the artifact safely; `kind` in `attribute | context | privilege` |
| `rung`, `evidences` | unchanged | as before |

### 2.3 `trust_model.dynamic_state_trust.transitions`

| Field | Type | Definition |
|---|---|---|
| `id`, `state_from`, `state_to`, `trigger`, `side_effects` | unchanged | as before |
| `artifact` | string | the transition input plus the state read |
| `establishes` | list of `{item, rung, evidences}` | the guard conditions actually enforced (the former `guard_verified` material, now per-item) |
| `requires` | list of `{item, kind, rung, evidences}` | the post-state invariant plus the trust-transition agreement (the former `guard_assumed` material, now per-item), plus the state attributes downstream steps rely on; `kind` in `invariant | trust_transition | state_attribute` |
| `rung`, `evidences` | unchanged | as before |

### 2.4 `assumptions`

| Field | Type | Definition |
|---|---|---|
| `id`, `statement` | unchanged | the developer assumption the record bends |
| `induced_fault` | unchanged | the programming fault the assumption induces |
| `boundary_ref` | string | the interface agreement, trust agreement, or transition record the assumption bends |
| `dimension` | list of `identity | spatial | temporal | interpretation` | the unestablished property the reliance leaves open |
| `propagation` | `{kind: local | propagated, origin_ref: string | null}` | `propagated` when the unverified assertion is carried in from an earlier boundary or transition |
| `rung`, `evidences` | unchanged | as before |

### 2.5 Unchanged

`control_flows`, `data_flows`, `dynamic_state_trust.states` and `violations`, `faults`, `vulnerabilities`, `failure_modes`, `loops`, `evidence_gaps`, the `environment` block, the rung and evidences semantics, the drop rule, the likelihood scale, and the suite mapping rule.

## 3. Delta versus the baseline trial surface (`trials/t1-service-model-download`)

| Surface | Baseline | Integrated | Nature of change |
|---|---|---|---|
| interface agreements | `{id, statement, rung, evidences}` | + `artifact`, + `establishes` | added fields (the behaviour of the receiving side's checks is now explicit) |
| trust agreements | `{id, statement, rung, evidences}` | + `requires` | added field (the receiving side's reliance is now explicit) |
| transitions | `{id, state_from, state_to, trigger, guard_verified, guard_assumed, side_effects, rung, evidences}` | `guard_verified` becomes `establishes` (per-item), `guard_assumed` becomes `requires` (per-item), + `artifact` | re-typed, same material, itemised |
| assumptions | `{id, statement, induced_fault, rung, evidences}` | + `boundary_ref`, + `dimension`, + `propagation` | added fields (traceability, the unestablished property, the propagation status) |
| everything else | unchanged | unchanged | - |

## 4. Fidelity notes

- The run book keeps the baseline trial's material references (the two notes documents are read by the modeller exactly as in the baseline), so the trial isolates the boundary-record and abduction discipline as the treatment, not the prompt's information content.
- The `layer` subfield of `establishes` is a trial-level convenience (it cites the request-handling stack checklist); the research note treats the layer reference as optional annotation.
- Nothing symbolic was added: no checker, no enumeration, no algorithm.
