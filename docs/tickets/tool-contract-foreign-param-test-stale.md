# Ticket: the foreign-param tool-contract test expects a raise the coded rejection replaced

- **Severity:** low (test drift; the tool behaviour is the intended coded rejection).
- **Area:** `tests/integration/test_test_executor_pod_contracts.py::test_tool_contract_rejects_foreign_params`, `src/polymerhus/app/memory/tool_contract.py`.
- **Status:** open (found 2026-11-05 while running the W8 harness tests).
- **Filed from:** the #359 W8 browser-binding work, which touched the same harness invocation path.

## Summary

`test_tool_contract_rejects_foreign_params` asserts that `PodNoteTool.invoke` raises `ValueError` for a field outside `NoteToolSpec`.
`StoreToolBase.invoke` now catches `ValidationError` and returns a coded teaching rejection for the known drifts, so the call returns a JSON string instead of raising.
The property the test cares about still holds: `_run` never executes (`calls == []`).

## Evidence

```
$ .venv/bin/pytest tests/integration/test_test_executor_pod_contracts.py::test_tool_contract_rejects_foreign_params -q
E       Failed: DID NOT RAISE <class 'ValueError'>
```

The failure predates the W8 change: it reproduces with `hunting_agent.py` reverted to the W7 commit.

## Proposed fix

Assert the coded rejection envelope for the foreign field (a `success: false` / coded error string), and keep `calls == []` as the proof that `_run` never ran.
If the raw-schema raise is still a contract, assert it directly on `NoteToolSpec`, which still raises.

## Acceptance criteria

- The test passes and still proves `_run` never executes for a foreign field.
- No production code changes unless the coded rejection is itself wrong.
