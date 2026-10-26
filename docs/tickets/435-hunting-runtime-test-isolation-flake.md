# 435 - Hunting runtime provider-abort test is order-dependent

**What to build:** Make `test_provider_abort_stops_the_runs_sessions_before_the_terminal` deterministic when it runs inside the full `tests/attack` suite.

**Blocked by:** none

**Status:** open

**Seams:** `tests/attack/test_hunting_runtime.py`, `src/polymerhus/attack/hunting/runtime.py`, the pod finalizer

## Context

One full `tests/attack` run on trunk `a65c445f` reported 1 failed and 1164 passed.
The failure was `tests/attack/test_hunting_runtime.py::test_provider_abort_stops_the_runs_sessions_before_the_terminal`.
The same test passes alone.
It passes when `tests/attack/test_hunting_runtime.py` runs alone, twice in a row.
The next full `tests/attack` run passed 1165 of 1165.

The first failure arrived after the pod control-plane merge.
The likely cause is shared runtime or finalizer state left by an earlier test in the suite.
The exact traceback was not captured.

## Acceptance criteria

- [ ] Reproduce the failure in a full `tests/attack` run and capture the assertion.
- [ ] Name the state that leaks between tests.
- [ ] Reset the state in the test fixture or the runtime owner.
- [ ] Run `tests/attack` at least 20 times without a failure.
- [ ] Record the reproduction command and the flake rate.

## Verification

- `pytest tests/attack -q` repeated 20 times.
- `pytest tests/attack/test_hunting_runtime.py -q` repeated 20 times.
