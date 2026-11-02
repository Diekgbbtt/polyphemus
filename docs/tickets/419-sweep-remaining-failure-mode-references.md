# 419 - Sweep the remaining failure-mode references

**What to build:** Sweep the hunting module, the tests, and the design docs for remaining failure-mode references. Remove the obsolete references and record the deliberate exceptions: provider failures, degraded runs, and generic execution failures are not the removed artifact.

**Blocked by:** 418

**Status:** done

**Seams:** attack/hunting, tests/attack, docs/design

## Context

Historical experiment reports are not rewritten. The sweep gate is a grep over the hunting module and the tests; every remaining hit must be a deliberate exception recorded in the ticket.

## Acceptance criteria

- [x] No failure_mode, FailureMode, or failure-mode reference remains in the hunting module except the recorded exceptions.
- [x] No failure_mode or FailureMode reference remains in the hunting tests except the recorded exceptions.
- [x] The design docs no longer describe the removed artifact as current.
- [x] The grep gate and the exception list are recorded.
- [x] The full hunting suite passes.

## Verification

- Run the grep gate.
- Run tests/attack.

## Sweep result (2026-10-25)

The gate is `grep -rn "failure_mode\|FailureMode\|failure-mode" src/polymerhus/attack/hunting tests/attack`.

Remaining hits, all deliberate:

- `src/polymerhus/attack/hunting/threat_model.py`: the migration comment above `SCHEMA_VERSION`, which records that the section and the `failure_mode_refs` link were removed without a version bump.
- `tests/attack/test_threat_model_store.py`: the legacy-rejection tests, which prove a `failure_modes` write and a `failure_mode_refs` loop are rejected by the strict schema.
- `tests/attack/test_hunting_agent.py` and `tests/attack/test_hunting_loop_dispatch.py`: the negative payload assertions, which prove the payload does not carry the removed field.
- `tests/attack/pod/test_prompts.py`: `test_triager_prompt_has_no_failure_mode_fallback`, a negative prompt test.
- `src/polymerhus/attack/hunting/CONTEXT.md`: the retirement notes on the end-impact and technical-feasibility bullets.

The `eval/measure_utm.py` model-text reader no longer reads `failure_modes`. `eval/prompts/measure.md` still uses the phrase "failure-mode slice" in its measurement checklist; that is the eval measurement vocabulary, outside this ticket's hunting-module scope, and is recorded as a follow-up for the eval measurement workstream.

The full hunting suite passes with 1094 tests.
