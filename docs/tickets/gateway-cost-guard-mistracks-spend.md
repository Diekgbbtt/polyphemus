# Ticket: the gateway cost guard mistracks spend and 429s every model call

- **Severity:** critical (availability + cost).
- **Area:** `src/polymerhus/app/llm/sync.py` (the gateway cost guard), `gateway/litellm_config.yaml` (`fail_closed_budget_enforcement`).
- **Status:** open. Guard DISABLED by default as a mitigation (2026-10-12).
- **Filed from:** the eval-server LiteLLM gateway, 2026-10-12.

## Summary

The co-located LiteLLM gateway enforces a per-virtual-key USD cost guard (LiteLLM-native `budget_limits` windows, provisioned by the sync). On the eval server the guard tripped far below the provider's real consumption, so every model call was rejected 429 before it reached the provider.

The gateway reported:

```
ExceededBudget: Key over 7d budget. Spend=$30.0052, Limit=$30.00
```

The operator's opencode-go dashboard showed only about **$15 consumed for that key**, roughly half the guard's `$30.0052`. The guard's spend accounting is therefore wrong by about 2x.

## Hypotheses

1. **Spend aggregated across keys.** The guard's per-window counter aggregates spend from more than one virtual key (or another entity) under one internal key, so the key's counter is charged traffic that was never routed through it.
2. **Wrong cost basis.** The guard prices a request with the wrong per-token rate for cached input, uncached input, or output, so the budget window counts a multiple of the provider's real charge.

Hypothesis 1 and 2 are not mutually exclusive. Both need falsification before the guard can be re-enabled.

## Evidence

- The 429 body (above): `Spend=$30.0052, Limit=$30.00` for a key the provider dashboard shows at about `$15`.
- Instance `docker-compose.yml` env values for the agent service (gateway mode):

  ```
  LLM_GATEWAY_BUDGET_ENABLED: (unset)   # new flag; absent means disabled
  LLM_GATEWAY_BUDGET_7D_USD: "30.0"
  LLM_GATEWAY_BUDGET_30D_USD: "60.0"
  LLM_GATEWAY_BUDGET_CONSERVATISM_FACTOR: "1.0"
  ```

  The `$30.00` limit in the 429 is the `7d` window (`cap_7d * k = 30.0 * 1.0`), so the weekly window is the one that tripped.

- The sync's cost basis. The sync authors each deployment's `model_info` per-token cost from the models.dev record, corrected by `sync_mapping.PROVIDER_COST_OVERRIDES` for opencode-go's role model:

  ```
  opencode-go/deepseek-v4.1-flash
    input_cost_per_token        = 1.5e-07   (0.15 / 1M)
    output_cost_per_token       = 6.0e-07   (0.60 / 1M)
    cache_read_input_token_cost = 3e-09     (0.003 / 1M)
    cost_source                 = provider-override
  ```

  LiteLLM counts spend from that authored `model_info`. The guard tripped at the `7d` cap with this basis, while the provider billed about half of it. The two candidate miscount paths are the cache-read key (a mis-mapped or absent `cache_read_input_token_cost` over-counts cached input) and cross-key aggregation in the per-window counter. The pinned 1.96.0 check `_virtual_key_budget_check` reads `valid_token.budget_limits` and its per-window spend counter, keyed by `spend:key:{token}:window:{budget_duration}` where `{token}` is the validated key token; a token-identity or counter-reseed bug would aggregate another key's spend.

## Action taken (2026-10-12)

The operator instructed removing the rate-limiting completely and filing the fault here.

- `gateway_budget_plan()` (`src/polymerhus/app/llm/sync.py`) now returns an EMPTY `BudgetPlan` by default: no `budget_limits`, no `rpm_limit`.
- `LLM_GATEWAY_BUDGET_ENABLED` is the opt-in: absent/empty is DISABLED (the default); `true`/`1` restores the retained `7d`/`30d` windows scaled by the conservatism factor.
- The sync CLEARS a pre-existing key budget when the plan is empty: `GatewayClient.ensure_virtual_key` issues a `/key/update` with `budget_limits: []`, which litellm 1.96 stores as JSON null and treats as "no guard" (`_virtual_key_budget_check` returns early on a falsy surface). A second run is a no-op.
- `gateway/litellm_config.yaml` sets `general_settings.fail_closed_budget_enforcement: false` (a static boot-time setting the sync never writes), so the 503-on-unverifiable-spend path is off while the guard is off. Re-enabling the guard takes both `LLM_GATEWAY_BUDGET_ENABLED=true` and restoring that setting.

## Acceptance criteria to re-enable the guard

1. **Reconciliation.** Over a full eval run, the guard's key-window spend count matches the provider dashboard's consumption for the same key to within a small epsilon (for example 1% or `$0.10`, whichever is larger).
2. **No cross-key charge.** A key is never charged another key's spend: provision two keys, route traffic through one, and assert the other's window spend stays zero.
3. **Cost basis verified.** A single request whose prompt and output token counts are known produces a guard spend-delta equal to the provider's priced charge (the existing `tests/e2e/test_llm_cost_override_e2e.py` shape), including the cached-input and output components separately.
4. Only after 1-3 pass, re-enable the windows and `fail_closed_budget_enforcement` together.

## Notes

- The e2e probe `tests/e2e/test_gateway_budget_guard.py` still exercises the real `budget_limits` seam with an explicitly provisioned zero-USD window, so the mechanism remains covered while disabled by default.
- This ticket is intentionally a fault report, not a fix; the accounting bug is unresolved.
