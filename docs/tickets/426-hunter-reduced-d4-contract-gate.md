# 426 - Enforce the hunter reduced-D4 contract at ratification

**What to build:** Reject a spec at the ratify/promote gate when it omits `verification_symptoms`, `assumptions`, or `skill_concretised_procedure`.

**Blocked by:** none

**Status:** open

**Seams:** `attack/hunting/hunter_tools.py`, `attack/hunting/spec_contract.py`, `attack/hunting/hunter_memory.py`, `attack/hunting/surfer.py`

## Context

Iteration B ratified and dispatched 12 of 104 specs without `verification_symptoms`, `assumptions`, and `skill_concretised_procedure`.
The affected set is all five `Service-sign-in__threat-8` specs, two `RESTApi-api__threat-4` specs, and five `RESTApi-api__threat-10` specs.

## Acceptance criteria

- [ ] The ratify/promote gate refuses a spec missing any of the three required body fields.
- [ ] The refusal is coded and teaches the missing field, not a bare validation error.
- [ ] A refused spec stays hypothesised and is never dispatched.
- [ ] A regression test builds a spec with each missing field and asserts the refusal.
- [ ] The next run reports the count of contract-broken specs at ratification, which must be zero.

## Verification

- `tests/attack/test_hunter_tools.py`
- `tests/attack/test_hunting_surfer_tick.py`
- `tests/integration/test_hunter_memory_contracts.py`
