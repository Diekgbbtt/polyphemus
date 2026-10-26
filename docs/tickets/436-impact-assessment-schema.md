# 436 - Impact assessment schema and completion invariants

**What to build:** Replace the damage-first model with the impact-assessment model. A threat is a damage-bearing row with a concrete victim and damaged property. A placeholder is a row with no concrete damage. A precursor is a capability entity. One threat references exactly one impact row. One vulnerability may yield several threats, one per exploitation manner. The CIA score is authored after the assessment.

**Blocked by:** None - can start immediately.

**Status:** done

**Seams:** `attack/hunting/threat_model.py`, `attack/hunting/threat_model_store.py`, `attack/hunting/threat_modeller.py`, `attack/hunting/prompts/threat-modeller.md`

## Context

The spec is `docs/design/impact-assessment-system-spec.md`. The prototype is `docs/design/impact-assessment-system-prototype.md`.

The current model has one free-text `end_impact` on the threat, a `loop`/`threat` row that may carry no damage, and no precursor entity. The five states are `UNIT_TECHNICAL_SHARP`, `TRUST_MODELLED`, `TRUST_ASSUMPTIONS_WRITTEN`, `VULNERABILITIES_WRITTEN`, `COMPLETED`.

The new model has seven states: `UNIT_TECHNICAL_SHARP`, `PRIOR_ART`, `TRUST_MODELLED`, `TRUST_ASSUMPTIONS_WRITTEN`, `VULNERABILITIES_WRITTEN`, `IMPACT_ASSESSED`, `COMPLETED`.

The impact assessment is a first-class model section. It carries one row per damage claim. A row has an `id` (`IA-*`), a `vulnerability_ref` (`V-*`), a `disposition` (`threat` or `placeholder`), a `damage` field, the yielded precursor references, the capability path, and the evidence. The `damage` field names the victim and the damaged property in one concise statement.

The precursor list is a top-level model section. A precursor has an `id` (`P-*`), the capability gained, the abstract procedure that gains it, and the evidence. The procedure is a trust-boundary mechanism, never a request, payload, or tool.

The threat keeps its fault, class, likelihood, risk factors, confidence, evidence, CIA vector, and risk. It gains `impact_ref` and `enabling_precursors`. The `end_impact` string is removed from `Impact`.

The completion check enforces:

- every non-dropped vulnerability has at least one assessment;
- a `threat` row has at least one non-none CIA value, a non-empty `damage`, a non-empty `capability_path`, and at least one enabling precursor;
- a `placeholder` row has all-none CIA values, a non-empty `damage` that states no concrete victim, and an empty `capability_path`;
- every threat references exactly one `threat` row with the same vulnerability;
- every `threat` row has exactly one threat;
- a `placeholder` row has no threat;
- the threat's `enabling_precursors` set equals the row's `capability_path` set;
- every precursor reference resolves;
- a vulnerability may have several `threat` rows, one per exploitation manner.

The store writes a threat file only for a `threat` row. A placeholder stays in the model. The threat file carries a denormalised `impact` block with the damage, the disposition, the precursors, and the path.

The prompt defines the seven states, the damage semantic, the victim and property catalog, the precursor abstraction, the one-threat-one-damage rule, and the CIA-after-assessment order.

## Acceptance criteria

- [ ] The schema exposes `impact_assessment`, `precursors`, `Threat.impact_ref`, `Threat.enabling_precursors`, and `Impact` without `end_impact`.
- [ ] The seven states and their gate sections are wired.
- [ ] The completion check enforces every invariant above.
- [ ] A placeholder produces no threat file.
- [ ] A threat produces one threat file with the `impact` block.
- [ ] The prompt states the seven states, the damage semantic, and the precursor boundary.
- [ ] The old five-state and `end_impact` behaviour is gone from the live path.
- [ ] The default and the degraded paths remain fail-open.

## Verification

- `tests/attack/test_threat_model.py`
- `tests/attack/test_threat_model_store.py`
- `tests/attack/test_threat_modeller.py`
- `tests/attack/test_threat_modeller_prompt.py`
- `compileall` and `git diff --check`
