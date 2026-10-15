# Ticket: the dev integration suite carries pre-existing reds

- **Severity:** medium (test-trust debt; the verifier gate is blind in these areas).
- **Area:** `tests/integration/test_arjun_consumption_contracts.py`, `tests/integration/test_llm_sync_key_rotation.py`.
- **Status:** open.
- **Filed from:** the T1 pass of `docs/design/plans/2026-10-15-streamed-pipeline-corrections.md`, 2026-10-15.
- **Baseline:** all items reproduce on a clean `dev` checkout at `6ec2e55` (no local changes), so none is caused by the streamed-pipeline corrections.

## Summary

Running `pytest tests/analysis tests/integration` on clean `dev` yields 8 failures.
Three were the same mechanical drift and were fixed along in the T1 branch (the one-shot proposer `invoke_fn` seam now passes `schema=`/`system_prompt=`, and three test-local fakes still had the old one-argument signature):
`test_analyser_pod_merge.py`, `test_decoupling_contracts.py`, `test_delivery_merge.py`.
The remaining items are filed here.

## Item 1 - the arjun consumption contracts are stale against the pod-input shape

5 failures: `test_arjun_consumption_contracts.py::test_C1`, `C2`, `C4`, `C5`, `C6`.

One-line causes:

```
test_arjun_consumption_contracts.py:66  KeyError: 'path'
test_arjun_consumption_contracts.py:77  KeyError: 'path'
test_arjun_consumption_contracts.py:103 AssertionError: assert 1 == 2
test_arjun_consumption_contracts.py:121 KeyError: 'path'
test_arjun_consumption_contracts.py:138 KeyError: 'path'
```

The tests read `pi["input_asset"]["path"]` off the recorded `pod_invoke` input, and the compiled `job_agent` / `batching` seam no longer puts an asset with a `path` at that spot (the `#37` unified consumption-set derivation reshaped the pod input).
The tests were written against the pre-`6f54543` shape.
C4 additionally expects two pods where one now arrives, so the fix is not a pure shim: re-derive the expected values from the current `#37` contract before touching the assertions.
The unit tier drives the same mechanics and stays green, so this is a contract-copy refresh, not a production defect (verify that claim when fixing).

## Item 2 - the budget-window test contradicts the guard-disabled default

1 failure: `test_llm_sync_key_rotation.py::test_budget_windows_are_provisioned_and_converge` (`assert windows == {"7d": 30.0, "30d": 60.0}` fails with `windows == {}`, and the assertion message is the empty dict).

The test deletes `LLM_GATEWAY_BUDGET_*` env vars and expects minted virtual keys to carry the 7d/30d USD windows anyway.
The gateway cost guard was DISABLED by default as the mitigation for `docs/tickets/gateway-cost-guard-mistracks-spend.md` (2026-10-12), so a default sync now mints keys WITHOUT budget windows and the old expectation is stale.
The fix is a decision-aware rewrite: assert the disabled-by-default shape (no `budget_limits`), and keep a second case that sets the env vars and asserts the windows are provisioned and converge.
Blocked-by-nature: this assertion encodes a product decision, so the operator should confirm the intended default before the test is rewritten.

## Adjacent finding - the full-suite run also picks up three live-infrastructure tests

Filed 2026-10-15 during the T3/T4 verification, when a bare `pytest tests --ignore=tests/e2e` run was used as the gate.

- `tests/test_agent_health.py::test_agent_health_all_backends_ok` fails with a subprocess error without live agent backends.
- `tests/test_stack_smoke.py::test_full_stack_comes_up_and_connects` fails with a subprocess error without the running compose stack.
- `tests/test_steel_exec_live.py::test_live_run_uses_no_cloud_key` passed in isolation and failed inside the full run (`AssertionError`), so it is order- or environment-sensitive.

None of the three carries a skip gate, so a full-suite run reports them as reds outside the verifier gate's scope.
This is not caused by the streamed-pipeline corrections; it is noted so the next full-suite reader does not misattribute them.
