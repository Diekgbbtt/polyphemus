# 421 - Run the full verification suite

**What to build:** Run the focused suites, `tests/attack`, `tests/eval`, the project-management and settings tests, `compileall`, and `git diff --check` on the impact-elicitation branch.

**Blocked by:** 420

**Status:** done

**Seams:** the whole tree

## Context

The plan's verification gate before the A/B. The branch now also carries the loop-to-threat rename, the narrowing measurement, and the SkillEvolution experiment switch.

## Acceptance criteria

- [x] `tests/attack` passes.
- [x] `tests/eval` passes.
- [x] The focused integration and e2e suites pass.
- [x] The project-management and settings suites pass.
- [x] `compileall` is clean.
- [x] `git diff --check` is clean.

## Verification

- `tests/attack`: 1103 passed.
- `tests/eval`: 831 passed.
- Focused integration and e2e: 89 passed.
- Project management plus settings: 50 passed, 2 skipped.
- `tests/app` and `tests/recon`: 1508 passed, 44 skipped.
- `tests/project_management/test_skill_evolve_api.py`: 14 passed.
- `compileall` clean; `git diff --check` clean.
