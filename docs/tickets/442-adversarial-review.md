# 442 - Adversarial critical review

**What to build:** Run the adversarial review after tickets 436-441. Check spec compliance, coding standards, and native framework patterns. Record the findings and the fixes.

**Blocked by:** 436, 437, 438, 439, 440, 441.

**Status:** done

**Seams:** the changed modules and tests

## Context

The review has three axes:

1. **Spec compliance.**
   Every acceptance criterion in 436-441 is met.
   The code matches `docs/design/impact-assessment-system-spec.md`.
   No removed field remains in a live contract.
2. **Coding standards.**
   The repository standards hold: no em dash, no co-author, TDD evidence, atomic writes, fail-open paths, coded teaching rejections, no import-time I/O, typed surfaces with `extra="forbid"`.
3. **Native framework patterns.**
   The implementation uses the existing pydantic, LangGraph, LangChain, FastAPI, and store patterns.
   It does not invent a parallel mechanism.
   It reuses the shared `notes` tool, the atomic store write, the passive state tracker, the mover, and the measurement seams.

The review is adversarial.
It looks for the failure modes the design is meant to prevent:

- a placeholder dispatched as a threat;
- a damage-less row with a non-none CIA;
- a threat with no impact reference;
- a precursor procedure that contains a request or payload;
- a prior-art query that dumps the store;
- a scope string that is paraphrased or duplicated in the run record;
- a run-record field that duplicates the files;
- a damage symptom or damage verdict that sneaks back into the spec or pod;
- a class-based green gate that survives as a pass/fail.

## Acceptance criteria

- [ ] The spec-compliance report is written.
- [ ] The coding-standard report is written.
- [ ] The native-pattern report is written.
- [ ] Every high finding has a fix or a recorded exception.
- [ ] The full focused suites pass.
- [ ] `compileall` and `git diff --check` are clean.
- [ ] The final report states the residual risks.

## Verification

- The `spec-reviewer` subagent report.
- The `code-reviewer` subagent report.
- `tests/attack`, `tests/eval`, the project-management tests, and the prompt tests.
- `compileall` and `git diff --check`.


## Result

The adversarial review ran on `impact-assessment-tdd` against base `a15f5ec3`.
The spec reviewer found one high finding (v2 models refused by the store) and one medium finding (an extra capability-path subset invariant), plus documentation drift.
The code reviewer found one high finding (the turn prompt reported `prior_art` as written before the gate) and one medium finding (the cold-jump test was weakened).
The high and medium findings are fixed in `fcb8c0c8`.
The full focused suite is 2244 passed, 6 skipped.
The residual risks are recorded in `docs/design/impact-assessment-review-2026-10-26.md`.

Acceptance criteria:

- [x] The spec-compliance report is written.
- [x] The coding-standard report is written.
- [x] The native-pattern report is written.
- [x] Every high finding has a fix or a recorded exception.
- [x] The full focused suites pass.
- [x] `compileall` and `git diff --check` are clean.
- [x] The final report states the residual risks.
