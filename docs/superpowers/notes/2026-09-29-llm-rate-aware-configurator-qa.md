# LLM Rate-Aware Recon Configurator — QA and PR Readiness

**Date:** 2026-09-29
**Worktree:** `feat/rate-limit-job-admission-e2e`
**Base implementation head:** `de918a81`

## Scope reviewed

The review traced the active path from the Auth Gateway through direct Vegeta
mapping, dual persistence, the stateful Configurator, atomic technical
materialization, configured pod execution and Triager processing. It also
checked that deterministic traffic admission and runtime `TrafficPolicy`
forwarding are absent from the active recon pipeline.

Legacy admission modules and wire contracts remain available for compatibility
and historical tests, but the active pipeline does not import or invoke them.

## Defect corrected during QA

`_schedule_pipeline` passes the production `fetch_capabilities` seam to
`run_pipeline`. Three local test doubles in
`tests/app/test_launch_task_lifetime.py` still implemented the older signature:
two lifetime tests failed, while the error-logging test passed for the wrong
reason by logging that `TypeError` instead of its intended `RuntimeError`.

The correction:

- aligns all three doubles with the production call signature;
- replaces timing windows in the lifetime tests with explicit cross-thread
  entry/release barriers, so registry presence and cleanup are observed
  deterministically;
- replaces the error test's fixed sleep with an asynchronous condition-based
  wait that does not block either event loop;
- asserts the exact exception type and message (`RuntimeError`,
  `pipeline exploded`) so another launch error cannot satisfy the test.

## Verification record

Fresh results after the correction:

| Gate | Result |
|---|---|
| `tests/app/test_launch_task_lifetime.py` | 7 passed |
| focused Configurator/rate-posture contracts | 97 passed |
| `tests/app tests/recon tests/attack` | 2067 passed, 39 skipped, 0 failed |
| deterministic provider, run A | 16 passed |
| functional Configurator matrix, run A | 3 passed in 316.53 s |
| deterministic provider, run B | 16 passed |
| functional Configurator matrix, run B | 3 passed in 318.52 s |
| `git diff --check` | clean |

The repository tier still emits eight known warnings outside this change: four
FastAPI deprecation warnings, one Pytest collection warning and three
pre-existing un-awaited-coroutine warnings. The E2E logs also carry the existing
Neo4j driver destructor deprecation. None is a test failure or a changed
Configurator outcome; they remain follow-up cleanup rather than hidden gate
exceptions.

The functional matrix proves that high and low postures result in different
plans and commands, stats and YAML carry the same `RateProfile`, and an
unreadable posture creates no target-facing pod or traffic beyond the mapper's
bounded measurement.

### Environment-bound global suite

A diagnostic bare `pytest` is not a valid local gate for this feature. Its
collection requires the optional gateway dependency `litellm`; after excluding
that component it enters unrelated live E2E suites that require separately
provisioned agent, Kali, Langfuse and provider stacks. Without those fixtures it
fails on missing services and configuration rather than on this change. The
supported evidence is therefore the scoped 2067-test repository tier plus the
dedicated, twice-reset #238 stack above.

## Artifact policy

The pull request may include the four small, curated files under
`artifacts/issue-238-llm-configurator/`. Dated QA reruns and concurrency probes
are reproducible diagnostics and are ignored rather than staged.

## Merge criterion

Request review only after every gate above is green, the isolated Compose stack
has been removed, the authoritative documents are tracked, and `git status`
contains only the intended pull-request files.
