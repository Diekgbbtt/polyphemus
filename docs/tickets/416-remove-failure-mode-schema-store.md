# 416 - Remove the failure-mode section from the schema and the store

**What to build:** Remove the FailureMode class, the Loop.failure_mode_refs link, the ModelSections.failure_modes field, the failure-mode gate section, the completion checks, the store writes, and the fixtures. The COMPLETED gate carries only the loops.

**Blocked by:** 415

**Status:** ready-for-agent

**Seams:** attack/hunting/threat_model.py, attack/hunting/threat_model_store.py

## Context

The impact model and the prompt already carry the end impact. The failure-mode section is now unused. The removal is the contract half of the expand-contract sequence.

## Acceptance criteria

- [ ] The FailureMode class is gone.
- [ ] Loop.failure_mode_refs is gone.
- [ ] ModelSections.failure_modes is gone.
- [ ] The COMPLETED gate accepts only the loops section.
- [ ] The completion checker has no failure-mode findings.
- [ ] The store no longer writes or reads failure_modes.
- [ ] The fixtures and tests are updated.
- [ ] A model with a failure_modes key is rejected by the strict schema, and the migration note records it.

## Verification

- Run the threat-model store tests.
- Run the full hunting suite.
