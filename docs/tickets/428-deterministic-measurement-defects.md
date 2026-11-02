# 428 - Fix the three deterministic measurement defects

**What to build:** Fix the `loop-*.yaml` glob, the `provenance.skill_procedure` path, and the keyword-inflated `spec_candidate`/`confirmed_non_gt`.

**Blocked by:** none

**Status:** open

**Seams:** `eval/measure_utm.py`, `eval/prompts/measure.md`

## Context

The iteration B measurement recorded three deterministic defects:

- `eval/measure_utm.py` globs `loop-*.yaml` while the schema-2 artifacts are `threat-*.yaml`, so `loop_candidate` is false for every row.
- The script reads `provenance.skill_procedure` while the hunter writes the top-level `skill_concretised_procedure`, so the procedure count is 0.
- `spec_candidate` and `confirmed_non_gt` are inflated by keyword class matching: `confirmed_non_gt` is 1, not the 4 the measurement judges novel.

## Acceptance criteria

- [ ] The loader reads `threat-*.yaml` for schema 2 and `loop-*.yaml` for a legacy trial, with the vocabulary mapped.
- [ ] The procedure check reads the top-level `skill_concretised_procedure`.
- [ ] `spec_candidate` requires the GT unit and class, not a keyword match.
- [ ] `confirmed_non_gt` counts every confirmed pod whose spec id is absent from every candidate row.
- [ ] A regression test builds one schema-2 and one schema-1 trial and asserts both parse.
- [ ] The next measurement reports the four novel non-GT findings, not one.

## Verification

- `tests/eval/test_measure_utm.py`
- A replay of the iteration B `metrics.yaml`.
