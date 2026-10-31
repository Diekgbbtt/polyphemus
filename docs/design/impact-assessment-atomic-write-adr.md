# The impact assessment is one atomic write; the score is derived at persistence - ADR

*Status: proposed 2026-10-31. Decision owner: operator. Grilled 2026-10-31.*
*Companion: `docs/design/threat-model-cvss4-risk-scoring-adr.md`.*
*Supersedes the `IMPACT_ASSESSED` section of the modeller `hunts_store` surface and the threat-side CIA/likelihood carriage.*

## Context

The impact assessment is currently a `hunts_store` section written at the `IMPACT_ASSESSED` gate.
The CIA vector, the likelihood, and the risk factors live on the threat at `COMPLETED`.
The model authors the likelihood and the CIA values, and the store computes the product.
The assessment prose and the metric values are written at different gates, on different records, and can drift.

The new scoring model needs the prose reflection and the metric compilation to be one record.
It also needs the score to be derived without the model, and the model's response to carry no score it could iterate on.

## Decision

### 1. One tool, one atomic write

`assess_impact` is the sole writer of one `ImpactAssessment` row.
It takes the row id, the vulnerability ref, the disposition, the two prose blocks, the capability fields, the evidence refs, and the eight factors.
It validates the contract and writes the row atomically.

The row shape:

```
id                          IA-*
vulnerability_ref           V-*
disposition                 threat | precursor
impact_description          prose: the victim and the damaged property, or why no end damage follows
exploitability_description  prose: the chain, its capabilities, and its human participation
capability                  the adversarial capability gained
capability_id               P-*
capability_path             ordered P-* / Unit::P-*
evidence_refs               list of evidence refs
factors                     AV, AC, AT, PR, UI, VC, VI, VA
risk                        derived float, never authored
risk_vector                 derived string, never authored
```

### 2. The response is success or failure

The tool returns `{ok: true, hint: ...}` or a coded rejection naming the field and the fix.
The `hint` is the existing gate-transition pointer, so the model knows the next state without a second read; it carries no score, vector, or factor echo.
It does not return the score, the vector, or an echo of the factors.

### 3. The score is computed in the persistence commit

The persistence helper builds the vector with `SC = VC`, `SI = VI`, and `SA = VA`.
It computes `CVSS4(vector).base_score` and rounds to two decimals.
It persists `risk` and `risk_vector` on the row.
The computation is synchronous inside the commit.

A detached worker is rejected.
It would write a null score, force `score_state: pending | computed | failed` on the row, and add a reconciliation gate before `COMPLETED`.
That is a failure mode and a second state machine for a pure, sub-millisecond calculation.

### 4. The tool owns the `IMPACT_ASSESSED` transition

The first successful `assess_impact` call moves the model state to `IMPACT_ASSESSED`.
`hunts_store` no longer accepts the `impact_assessment` section, so the model cannot bypass the contract.
The `COMPLETED` gate requires at least one scored assessment for every non-dropped vulnerability.
A second assessment for the same vulnerability is allowed only with a distinct `capability_id`.

### 5. The assessment is the scored claim; the threat is the dispatch grain

The factors and the score live on the assessment row.
The threat keeps `impact_ref`, the ordered `enabling_precursors`, and a derived `risk` mirror for the threat file and the mover.
The threat does not carry its own CIA vector, likelihood, risk factors, or confidence.

### 6. The field names

`damage` becomes `impact_description`.
`likelihood_rationale` becomes `exploitability_description`.
The pair `impact_description` / `exploitability_description` is the canonical naming.
The capability fields (`capability`, `capability_id`, `capability_path`) keep their names.

### 7. One source of truth for the factor semantics

The enum descriptions, the decision nodes, and the examples are defined once in the risk module.
The tool description and the system prompt render the same text.
The system prompt carries the chain examples: the planted XSS payload, the DNS rebinding for SSRF and TOCTOU, the JWKS access for forged tokens.
The tool parameters carry the brief per-value examples.

The factor decision nodes:

- `PR`: the role and the permissions needed to use the chain's application primitives.
- `AC`: the defence that must be circumnavigated.
- `AT`: any other attacker capability that adds a phase.
- `UI`: passive for a routine flow, active for a specific non-routine victim action.
- `VC/VI/VA`: `high` for a direct, serious loss, `low` for a partial or bounded loss, `none` for no loss.

## Considered options

- Keep `hunts_store` as the writer and use `assess_impact` as a validator: rejected.
  It duplicates the data and allows the two copies to drift.
- Let the tool return the score: rejected.
  The score is derived, and the model must not iterate on it.
- Put the factors on the threat: rejected.
  The assessment is the claim; the threat is the dispatch grain.
- A detached scorer: rejected for the null-score window.

## Consequences

- The modeller workflow changes: after the prior-art gate, it calls `assess_impact` once per assessment row, and at least once per non-dropped vulnerability.
  The gate advances automatically.
  It then writes the threats at `COMPLETED`.
- `ModelSections` loses `impact_assessment`.
  The tool contract tests, the gate tests, and the prompt snapshots change.
- The assessment row is the single scored record.
  The prior-art query and the hunter payload read the score through the row.
- The v5 schema and the v4 raw read follow the risk ADR.
- The tool description grows by the eight factor enumerations and their examples.
  The cost is bounded and cacheable, and it replaces the likelihood and CIA prose that the prompt carried before.
