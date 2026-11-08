# 441 - Documentation and prompt convergence

**What to build:** Converge the live documentation and the prompt contracts to the impact-assessment model. The historical documents stay historical and are marked superseded. The glossary and the domain model carry the new terms. The prompt states the seven states and the new contracts.

**Blocked by:** 436, 437, 438, 439, 440.

**Status:** done

**Seams:** `docs/design`, `src/polymerhus/attack/hunting/CONTEXT.md`, `attack/hunting/prompts/threat-modeller.md`, `attack/hunting/prompts/hunting-agent.md`

## Context

The spec is `docs/design/impact-assessment-system-spec.md` section 14. The prototype is `docs/design/impact-assessment-system-prototype.md`. The decision record is `docs/design/impact-assessment-open-questions.md`.

The current documents are already amended. This ticket closes the loop after the implementation:

- The prompt states the seven gates, the damage semantic, the precursor abstraction, the prior-art phase, the project scope, and the CIA-after-assessment order.
- The hunter prompt states the shared damage and the variant-specific symptoms.
- The `CONTEXT.md` terms match the code.
- The historical documents are marked superseded.
- The old `end_impact`, `damage_family`, `victim_class`, `damage_symptom`, `damage_verdict`, `precursor_use`, `cross_unit_lead`, and `enables_ref` do not appear as current contracts in a live spec.

The doc gate:

- `grep` the live specs for the removed field names.
- A removed name is allowed only in a superseded/historical section or an explicit "removed" statement.
- The new spec is the authority.

## Acceptance criteria

- [ ] The prompt states the seven gates and the new contracts.
- [ ] The hunter prompt states the shared damage and the variant-specific symptoms.
- [ ] The glossary matches the code.
- [ ] The domain model matches the code.
- [ ] The historical documents are marked superseded.
- [ ] The doc gate passes.
- [ ] The spec, prototype, and decision record are consistent.

## Verification

- `tests/attack/test_threat_modeller_prompt.py`
- `tests/attack/test_hunting_agent_prompt.py`
- A doc grep gate over `docs/design` and `CONTEXT.md`
- A cross-read of the spec, the prototype, and the code
