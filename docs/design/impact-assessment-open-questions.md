# Impact assessment system - open questions and seam confirmation

*Status: decisions resolved 2026-10-26; tickets approved.*
*Companion to `docs/design/impact-assessment-system-spec.md` and `docs/design/impact-assessment-system-prototype.md`.*
*Purpose: record the resolved design decisions and the approved ticket breakdown before the TDD loop.*

## Decisions resolved 2026-10-26

### Q1. `Confidence` scope: A

Keep `Confidence` on the trust agreements, the assumptions, and the threats.
Remove it from the impact assessment and the precursor.
The threat confidence remains a likelihood factor.
The probe discipline keeps the modeller at the modelling layer.

### Q2. Impact cardinality: one threat, one damage

A threat has exactly one damage row.
A vulnerability may yield several threats, one per complementary exploitation manner.
Each threat carries its own damage row and its own capability path.
The threat stays broad: it names the exploitation manner and the damage, never the request, payload, or procedure.
The assessment's `capability_path` is the exploitation manner.
The threat's `enabling_precursors` equals the path set.

### Q3. Prior-art query scope: B

The query reads `consumed` and `produced` models.
The result carries the model `state`.
The bound unit is excluded unless a filter path is `unit_id`.

### The query primitive: regex on all threat-file attributes

`hunts_store` remains the grounding tool.
`cmd=query` takes a required `kind`, a non-empty `filters` list of `{path, regex, flags}`, and a `limit`.
The filters are AND.
Each filter is `re.search` over the value at the dotted path.
`*` iterates lists.
An unknown path, an invalid regex, or an empty filter list is a coded teaching rejection.
The path catalog covers every field of the threat file and the model records.
The prior-art requirement is one query each for `threat`, `vulnerability`, and `precursor`.

## Decisions recorded from the operator's direction

| # | Decision | Rationale | Artifact |
|---|---|---|---|
| 1 | The project scope is `Project.threat_model_scope`, persisted in `settings.hunting`, exposed by `GET/PUT /projects/{id}/hunting/config`. | Confirmed by the operator. The hunting settings already own the run-frozen configuration and the partial deep merge. | The spec section 6, the project settings, the REST API. |
| 2 | The scope is applied at the assumptions layer, not as an impact-row exclusion. | The operator: the scope covers the trust boundaries that should not be modelled, so the excluded assumption and fault are never made. | The spec section 6, the prompt, the model. |
| 3 | The impact metric is the CIA red/green share. | The operator: `none` is red, all others green. The class gate is retired. | The spec section 9, the measurement. |
| 4 | The downstream changes land in the same change window; the spec and pod contracts stay unchanged. | The operator confirmed. No `damage_claim`, no `damage_symptom`, no `damage_verdict`. | The spec section 8, the hunter payload, the hunter prompt. |
| 5 | The modeller probes are light, cheap, and falsification-only. The impact assessment does not lower the likelihood to invite deeper probing. | The operator: a lowered likelihood risks more frequent and aggressive probing. The modeller stays at the modelling layer; the hunter owns the effective attempt. | The spec section 10, the prompt, the honour clauses. |
| 6 | `Precursor.procedure` is the abstract trust-boundary mechanism, never a request, payload, or tool. | The operator: the precursor is a capability procedure; the hunter owns the technique. | The spec section 3, the prompt, the query summary. |
| 7 | `capability_path` is the ordered precursor ids. | The operator: promote the path to the model surface. The precursor entity already carries the capability, procedure, and evidence. | The spec section 3, the impact assessment, the threat file. |
| 8 | A placeholder is stored in the model, produces no threat file, and is red. | The operator: a row with no concrete end damage is a placeholder. The model keeps the reasoning without inflating the threat set. | The spec section 4, the store, the measurement. |
| 9 | The prior-art phase requires one query each for threats, vulnerabilities, and precursors. | The operator: significantly increase the attention on prior art, especially precursors. | The spec section 7, the completion check, the prompt. |
| 10 | The `damage` field is one free-text statement with the victim and property catalog in the prompt. | The operator: merge the victim and the damage into one concise field; the family and victim enums are heuristics. | The spec section 2, the prompt. |
| 11 | The run record gains no damage counts, no precursor counts, no scope field, and no leads. | The operator: redundant, ephemeral, or already in the files. | The spec section 11, the run record. |
| 12 | The directory layout keeps one `produced` and one `consumed` directory. The impact assessment and precursors live in `<unit>.yaml`. | The operator: the mover impact stays minimal; the assessment is a model field. | The spec section 12, the artifact tree. |
| 13 | The class-binding rate stays a diagnostic; the class-based green gate is retired. | The operator: the metric is the CIA values. | The spec section 9, the measurement. |

## Seam confirmation

The seams are confirmed by the accepted ticket breakdown.

1. **Project hunting config REST pair.**
   `GET/PUT /projects/{id}/hunting/config` carries `threat_model_scope`.
   The partial PUT preserves `pipeline_sync` and `risk_threshold`.
2. **`hunts_store` query.**
   The typed filters, the bound-unit exclusion, the project boundary, the result shape, and the empty-filter rejection.
3. **Completion checker.**
   The impact invariants, the precursor references, the prior-art requirement, and the placeholder closure.
4. **Store and threat file.**
   The `PRIOR_ART` and `IMPACT_ASSESSED` merges, the threat-file emission, the placeholder not emitted, and the model consumption.
5. **Hunter payload.**
   The impact block and the precursor rendering, with no request or payload leakage.
6. **Prompt contract.**
   The seven states, the damage semantic, the prior-art phase, and the project scope verbatim append.
7. **Measurement.**
   The CIA distribution, the red/green share, the placeholder share, and the v2 legacy read.

## Ticket breakdown (approved)

The breakdown is approved.
The tickets are published in `docs/tickets/` as 436-442.

| Ticket | Title | Blocked by | Delivers |
|---|---|---|---|
| 436 | Impact assessment schema and completion invariants | none | `impact_assessment`, `precursor`, `placeholder`, `threat.impact_ref`, and the completion checks. One model with a threat, a placeholder, and a multi-hop precursor path passes. |
| 437 | Prior-art gate and regex query contract | 436 | The `PRIOR_ART` state, the `prior_art` section, the `hunts_store` regex query, and the prompt phase. |
| 438 | Project scope attribute and REST surface | 436 | `Project.threat_model_scope`, the hunting config field, the run read, and the verbatim prompt append. |
| 439 | Threat file impact block and hunter payload | 436 | The impact block in the threat file, the payload impact/precursor rendering, and the unchanged spec contract. |
| 440 | Impact metric rebase | 436 | The CIA distribution, the red/green share, the placeholder share, the v2 legacy read, and the retired class gate. |
| 441 | Documentation and prompt convergence | 436-440 | The amendments, the glossary, and the supersession ledger. |
| 442 | Adversarial critical review | 436-441 | The spec-compliance review, the coding-standard review, and the native-framework-pattern review. |

The TDD loop starts at ticket 436.
The ticket 436 seam is the completion checker over a temporary store root.
The ticket 436 fixture is one model with a damage-bearing threat, one placeholder, and a multi-hop precursor path.

## Recorded glossary and ADR changes

The following are already recorded:

- `src/polymerhus/attack/hunting/CONTEXT.md`: the `threat`, `impact assessment`, `damage`, `precursor`, `placeholder`, `prior art`, `capability path`, and `project scope` terms.
- `docs/design/domain-model.md`: the new unit threat model primitives and the seven gates.
- `docs/design/impact-assessment-system-spec.md`: the authoritative spec.
- `docs/design/impact-assessment-system-prototype.md`: the rewritten prototype.
- The 2026-10-26 amendment in the six impacted specs.
- `docs/design/threat-damage-bearing-change-requirement.md`: marked superseded.
