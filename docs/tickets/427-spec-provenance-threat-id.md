# 427 - Write the store-owned threat id into the spec provenance

**What to build:** Make the hunter write `threat-<n>` into `provenance.threat_id`, and keep the dispatch id in its own field.

**Blocked by:** none

**Status:** open

**Seams:** `attack/hunting/spec_contract.py`, `attack/hunting/hunter_tools.py`, `eval/measure_utm.py`

## Context

Iteration B's hunter wrote the dispatch id `<unit_name>__threat-<n>` into `provenance.threat_id`.
The measurement link missed 44 of 104 specs until the analyser normalised the suffix.
The measurement substrate now normalises in `eval/measure_utm.py` (`3f8ac5cd`), but the writer still emits the wrong value.

## Acceptance criteria

- [ ] `provenance.threat_id` is `threat-<n>` on every produced spec.
- [ ] The dispatch id is carried in its own field, or derived at read time.
- [ ] The writer rejects a dispatch-shaped value in `threat_id`.
- [ ] The measurement link needs no suffix normalisation for a new run.
- [ ] A regression test asserts the stored provenance and the link to the threat file.

## Verification

- `tests/attack/test_spec_contract.py`
- `tests/eval/test_measure_utm.py`
- A white-jotter spec set.
