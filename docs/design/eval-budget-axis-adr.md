# ADR: the eval token budget matches the new-token axis (generated output + uncached input)

*Status: decided (operator ruling, 2026-10-08). Implemented by #347. Supersedes the "generated tokens only" budget axis recorded in `eval/CONTEXT.md` and `app/CONTEXT.md`.*

## Context

The eval enforces a per-trial **token budget**.
`eval/orchestrator/trial.py::_check_spend` reads the project's cumulative spend from the app usage surface (`GET /projects/{id}/usage`) and stops the active run when the trial's delta reaches the configured budget.
As shipped, that matched variable was the **generated** axis only (`generated_tokens` = reasoning + visible output).
The rationale recorded at the time was "input the model re-reads should never consume the budget for new work" (2026-10-05).

Two facts forced a revisit.

1. **The budget never bounded a run, and measured the wrong thing.**
   Every 2026-10-07 trial carried `token_budget: 4,000,000` yet ended on the wall-clock deadline (`terminal=timeout`, `spent_tokens=null`).
   jetlinks-1 #2 generated 5.74M tokens - past the 4M budget - with no stop.
   The generated axis is the smallest slice of what a run actually costs to compute.

2. **The goal is to bound inference power consumption, and to reward cache reuse.**
   Cached input is very cheap to serve: the KV vectors already exist, so a cache read costs almost no compute.
   Uncached input and new output are the real work.
   A good budget therefore charges **new output + uncached input** and charges **nothing for cached input**.

The ledger already carries exactly this axis.
`app/llm/usage.py::_axis_totals` computes `capped_tokens = generated + uncached = total_tokens - cached`, and `eval/orchestrator/api.py::usage_capped` already reads it.
Only the budget's call site used `usage_generated` instead.

## Decision

The variable matched against the app budget is **`capped_tokens` = generated output + uncached input**.
Cached input is excluded completely.

- `budget_axis = generated_tokens (reasoning + visible) + context_tokens.uncached`
- equivalently `total_tokens - context_tokens.cached`

The tracking mechanism is **unchanged at the source**: the ledger already derives this projection reliably from the pinned LiteLLM/langchain-openai usage payload (`prompt_tokens_details.cached_tokens` via `input_token_details.cache_read`), and the harness already exposes it.
The defect is fixed at the matched variable (`_check_spend` switches `usage_generated` -> `usage_capped`), not by rebuilding tracking.

## Rationale

- **Power-consumption proxy.** Cached input has negligible marginal compute; new output and uncached input are the load. Charging `generated + uncached` tracks the compute the run actually induces.
- **Cache-optimisation incentive.** A run that re-reads warm context is not charged, so the budget rewards cache-friendly behaviour (stable prefixes, bounded memory blobs) instead of punishing it.
- **Reliability.** The projection is a scalar already persisted durably per project (#326) and exposed on the app surface, so the budget needs no new API or attribute.

## Consequence: budget values must be re-tuned

`capped` is far larger than `generated`.
jetlinks-1 #2: `capped ~= 77.6M` (5.74M generated + 71.9M uncached) versus `generated = 5.74M`.
Existing per-target `token_budget` values (for example `4,000,000`, chosen for the generated axis) would stop a run almost immediately under the capped axis.
Every setup's budget must therefore be re-sized from the observed capped distribution, and the `eval/CONTEXT.md` definition of **Token budget** / **Token spend** must state the capped axis.
The axis change and the value re-tuning are one change: shipping one without the other regresses every trial to an instant stop.

## Risk: token-tracking noise from untracked cached inputs

The capped axis is only as good as the provider's `cache_read` attribute.

- The pinned inclusive convention (`input_tokens` contains `cache_read`) is handled as `uncached = input_tokens - cache_read`.
- The unambiguous exclusive convention (`cache_read > input_tokens`) is handled by keeping both separate.
- The **ambiguous exclusive** case (the provider excludes `cache_read` but `cache_read <= input_tokens`) is a documented non-goal of `_axis_totals`.
  On that path `uncached` silently keeps the cached amount, so `capped` drifts toward `total_tokens` and under-credits cache reuse.

When the attribute is absent or misreported, the budget over-charges (toward the raw total) - the safe direction for a spend cap, but it weakens the cache incentive.
This noise is inherent to any projection of a provider usage payload and is accepted; the axis is a **compute proxy, not a cost guard**.

## Relationship to the provider limit

The provider limit is a **cost** allowance (`vendor_rate_limit`, e.g. the weekly opencode-go cap), not a token count.
Cached input still bills in cost terms, so a capped-token budget bounds after the fact but does not by itself track the provider's dollars.
The cost-side control is **#330 / D-4** and is separate from this axis decision.

## Consequences

- `_check_spend`, its baseline snapshot, the overshoot re-read, and the `spend_by_agent` breakdown all read the capped axis.
- The trial record's `spent_tokens` reports capped tokens.
- Docs updated: `eval/CONTEXT.md` (Token budget, Token spend, Spend baseline), `app/CONTEXT.md` (usage ledger), and the `capped_tokens` docstrings in `usage.py` / `api.py`.
- A regression test proves a cached-heavy call does not advance the budget while an uncached call does.

## Alternatives rejected

- **Keep `generated` only.** Cannot bound compute; ignores uncached input, the dominant real load in a hunting loop.
- **Use `total_tokens`.** Charges cached input, punishing cache reuse and mis-modelling power consumption - the opposite of the intent.
- **Rebuild tracking on a new provider attribute.** Unnecessary: the projection is already in the ledger and the surface.
