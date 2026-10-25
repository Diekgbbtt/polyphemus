# 417 - Remove the failure-mode references from the hunter

**What to build:** Remove every reference to the failure-mode attribute from the hunter prompt and module. Replace the reasoning with the existing axes: vulnerability variants, manifestation, testing technique, framework or protocol misconfiguration, and payload vector class. Do not add a new vocabulary. The hunter remains otherwise as-is.

**Blocked by:** 416

**Status:** ready-for-agent

**Seams:** attack/hunting/prompts/hunting-agent.md, attack/hunting/hunting_agent.py, attack/hunting/hunter_payload.py, attack/hunting/hunter_state.py, attack/hunting/spec_contract.py

## Context

The hunter's loop ontology, [D1] check, grounding target, slice pass, exhaustiveness sentence, and example mention failure modes. The payload and state docstrings mention them too. The removal is lexical and structural, not a redesign of the hunter.

## Acceptance criteria

- [ ] No failure-mode reference remains in the hunter prompt.
- [ ] No failure-mode reference remains in the hunter module.
- [ ] The prompt uses the existing axes and invents no new reasoning variable.
- [ ] The hunter's passes, tools, and spec contract are otherwise unchanged.
- [ ] The prompt tests assert the removals.
- [ ] The hunter payload tests pass.

## Verification

- Run the hunter prompt tests.
- Run the hunter payload and state tests.
