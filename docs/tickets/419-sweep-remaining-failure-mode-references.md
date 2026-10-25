# 419 - Sweep the remaining failure-mode references

**What to build:** Sweep the hunting module, the tests, and the design docs for remaining failure-mode references. Remove the obsolete references and record the deliberate exceptions: provider failures, degraded runs, and generic execution failures are not the removed artifact.

**Blocked by:** 418

**Status:** ready-for-agent

**Seams:** attack/hunting, tests/attack, docs/design

## Context

Historical experiment reports are not rewritten. The sweep gate is a grep over the hunting module and the tests; every remaining hit must be a deliberate exception recorded in the ticket.

## Acceptance criteria

- [ ] No failure_mode, FailureMode, or failure-mode reference remains in the hunting module except the recorded exceptions.
- [ ] No failure_mode or FailureMode reference remains in the hunting tests except the recorded exceptions.
- [ ] The design docs no longer describe the removed artifact as current.
- [ ] The grep gate and the exception list are recorded.
- [ ] The full hunting suite passes.

## Verification

- Run the grep gate.
- Run tests/attack.
