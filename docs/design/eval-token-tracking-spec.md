# Token spend tracking and the trial token budget

**Status:** Spec (in-context; no issue filed by operator request)
**Branch:** `feat/eval-token-tracking` (off `feat/eval-pipeline` == `a83520f`)
**Vocabulary:** `eval/CONTEXT.md` (Hunting cap), `src/polymerhus/app/CONTEXT.md` (new terms below)

## Problem Statement

The eval harness bounds a trial's hunting by counting hunt configs (the hunting cap), but it cannot see how many LLM tokens a trial spends.
An operator cannot say "this target gets N tokens" and have the harness stop the trial when it overruns.
The spend is also invisible per internal agent, so an operator cannot see which agent burned the budget.
The LLM gateway exposes only aggregate, agent-less spend, and one-shot calls are untracked (recorded design lack), so the live source must be the LLM client engine, exposed through the app API.

## Solution

Two halves, one pipeline:

1. **App side.** A token-usage tracking layer attaches to every stateful agent at the ubiquitous session seam.
   It reads each model call's native `usage_metadata`, attributes it to the calling agent, and accumulates a process-wide **usage ledger** scoped by project.
   The app exposes the ledger read-only through the app API (`GET /projects/{id}/usage`).
2. **Eval side.** A per-target **token budget** is declared in the setup, carried onto `TrialConfig`, and enforced per trial as the sibling of the hunting cap.
   Each poll the trial reads the project's token spend from the app API; when the spend reaches the budget it stops the active run and records the spend, the overshoot, and the per-agent breakdown on the trial record.

Tokens only. Cost is out of scope.

## User Stories

1. As an eval operator, I want to declare a token budget per target, so that a runaway target is stopped without a wall-clock wait.
2. As an eval operator, I want a trial stopped on token overflow to record how many tokens it spent, so that I can compare targets on spend.
3. As an eval operator, I want the overshoot recorded, so that I can see how far past the budget the in-flight work ran.
4. As an eval operator, I want a per-agent token breakdown recorded, so that I can see which internal agent consumed the budget.
5. As an eval operator, I want a resumed trial to keep counting from its recorded spend baseline, so that a resume does not reset the budget.
6. As an eval operator, I want a token-stopped trial to be a success terminal (`stopped`), so that the surfer treats it like a cap stop.
7. As an eval operator, I want the surfer to detect a token-budget stop from the record, so that it can terminate or resume with the baseline carried.
8. As an eval operator, I want the plan output to name the token budget, so that a dry run shows the bound.
9. As an eval operator, I want the trial status output to print the token spend, so that I can read the outcome without opening the record.
10. As a polymerhus developer, I want the usage tracking to attach at the one ubiquitous stateful-agent seam, so that every stateful agent is tracked without per-call wiring.
11. As a polymerhus developer, I want the tracking decoupled from the Langfuse `observe` flag, so that an untraced turn is still counted.
12. As a polymerhus developer, I want the app API to expose the ledger read-only, so that the eval harness reads spend over the existing HTTP seam.
13. As a polymerhus developer, I want the usage scope passed explicitly at the session seam, so that attribution does not depend on the database.
14. As a polymerhus developer, I want the middleware to fail open, so that a tracking error never breaks an agent turn.
15. As a polymerhus developer, I want streamed turns counted, so that the default streamed session mode does not undercount.
16. As an eval harness author, I want the token budget to reuse the existing `ApiRunner` polling seam, so that the probing mechanics need no new transport.
17. As an eval harness author, I want the stop verb generalized over run kind, so that an overflow in recon, analysis, or hunting stops the right run.
18. As an eval harness author, I want a `token_budget` field validated at setup load, so that a malformed value fails loud.
19. As an eval harness author, I want the token budget to be optional (`null`), so that a target without a budget behaves exactly as today.
20. As an eval operator, I want a token-budget stop to leave the existing cap accounting untouched, so that the two bounds are independent.

## Implementation Decisions

### App side

- **New module** `src/polymerhus/app/llm/usage.py`:
  - `UsageLedger`: a process-wide, thread-safe accumulator keyed by `(project_id, agent)`.
    Each entry holds the two-axis typed surface (`context_tokens` = `cached` + `uncached`; `generated_tokens` = `reasoning` + `visible`), the scalar `total_tokens`, and `calls` (F16, below).
    Methods: `record(project_id, agent, usage)` (fail-open), `snapshot(project_id)` returning the project's aggregated surface plus a per-agent breakdown, and `reset()` (tests).
    Missing/None `project_id` records under an `"unscoped"` bucket that the project endpoint never returns.
  - `TokenUsageMiddleware(AgentMiddleware)`: records each model call's usage in `wrap_model_call`/`awrap_model_call` by reading `response.result`'s `usage_metadata`; `after_model` is the documented fallback if the streamed path does not surface usage in `wrap_model_call`.
    Reads identity from `langgraph.config.get_config()`: `metadata["role_id"]` and `metadata["usage_scope"]`.
    Fail-open: any read/record error is logged and swallowed, never raised into the turn.
  - `usage_middleware()` factory returning the middleware.
- **Attachment**: `_build_agent` (session.py) appends `usage_middleware()` to the middleware list for every stateful agent (all three entry points share it).
- **Identity**: `_turn_config` always writes `metadata["role_id"]` and `metadata["usage_scope"]`, independent of `observe` (today `role_id` is only set when `observe=True`). `usage_scope` is a new optional parameter on `run_session_turn`, `arun_session_turn`, `stateful_turn`, and `run_session_agent`, defaulting to `None`.
  Callers that run within a project pass their `project_id` as `usage_scope`.
- **Streamed usage**: `build_chat_model` constructs `ReasoningPreservingChatOpenAI(..., stream_usage=True)` so the default streamed session mode reports usage.
- **App API**: `GET /projects/{project_id}/usage` in `src/polymerhus/project_management/api.py`, beside `GET /app-state`.
  Read-only, no database access: returns `{"project_id", "context_tokens", "generated_tokens", "total_tokens", "calls", "by_agent": {agent: {...}}}`; an unknown/empty project returns zeros.
  It never validates project existence (no DB), so the eval queries only its own project.

### Token surface representation (F16, 2026-10-04)

The ledger started as a scalar surface (`input_tokens`, `output_tokens`, `total_tokens`, `calls` per agent).
It dropped the cache/reasoning detail the SDK's `usage_metadata` already carries (`input_token_details.cache_read`, `input_token_details.cache_creation`, `output_token_details.reasoning`), which `compaction.py` already reads.
Evidence: a comfyui trial-1 aggregate of 264 generations was `input=12,991,082 / output=215,821 / fresh_input=988,138 / cache_read=12,002,944 / reasoning=135,011` - 92% of input was cache reads, invisible on the surface.
The app ledger matched Langfuse within 0.2%, so this was a surface/representation gap, not a tracking bug.

**Decided representation (operator-ratified):** a two-axis typed surface.

- `context_tokens` (input) = `cached` (`input_token_details.cache_read`) + `uncached` (fresh input, i.e. `input_tokens - cache_read`, plus `input_token_details.cache_creation`).
- `generated_tokens` (output) = `reasoning` (`output_token_details.reasoning`) + `visible` (`output_tokens - reasoning`).
- `total_tokens` = context + generated, kept as the trial's budget scalar.

Each sub-component pair is clamped (cache_read to input, reasoning to output) so a malformed provider payload can never yield a negative component; the pairs still sum to the model's input (plus cache_creation) and output, so `total_tokens` remains the faithful budget scalar.

**Rejected alternative (do not implement):** a single `produced_tokens` decomposed into cached / not-cached.
It is internally inconsistent because cache is an input-side property while "produced" means output, conflating context read with generated output.

**Provider-normalization caveats (recorded, not hidden).**
The axis reads use the SDK's canonical detail keys (`input_token_details.cache_read`, `input_token_details.cache_creation`, `output_token_details.reasoning`).
On the pinned `langchain_openai` (the gateway path) `cache_creation` is never populated - OpenAI has no such field - so it is always 0 there; the read is kept for integrations that do report it.
`langchain_openai` prefixes those detail keys with the service tier (`priority_cache_read` / `priority_reasoning`) only when a priority/flex tier is negotiated; no request in this tree sets one, so the standard-tier key applies.
If a tier-prefixed payload ever arrives, the axes still total correctly (an unread `cache_read` folds into `uncached`); only the cached/uncached split is coarsened. A tier-aware read is a follow-up if a live run shows it.

### Eval side

- **Declaration**: `TargetRun.token_budget: int | None = None`; YAML key `token_budget` added to the target-run allow-list and validated as `int | None` (bool rejected).
- **Config**: `TrialConfig.token_budget: int | None = None`; `TrialConfig.spend_baseline: int | None = None` (carried across a resume).
- **Record**: `TrialRecord` gains `token_budget`, `spent_tokens`, `spend_overshoot`, `spend_baseline`, `spend_by_agent`.
- **API builders/parsers** (`eval/orchestrator/api.py`): `usage(project_id)` -> `GET /projects/{id}/usage`; `stop_run(project_id, run_kind, run_id)` generalizing the three stop paths; parsers `usage_total(response)` and `usage_by_agent(response)`.
- **Enforcement** (`eval/orchestrator/trial.py`): `Trial._check_spend(project_id, run_kind, run_id) -> SpendResult | None`.
  It reads the usage endpoint, snapshots `spend_baseline` on the first check, and when `total - baseline >= token_budget` calls `stop_run` and returns a `SpendResult` carrying `spent`, `overshoot`, `by_agent`.
  `_poll` and `_poll_hunting` call it each iteration; a spend stop ends the phase with status `stopped`.
  `_terminal_of` maps a spend stop to `stopped`.
  `_finish` persists the spend fields.
- **Surfer** (`eval/orchestrator/surfer.py`): `spend_triggers(record)` mirroring `cap_triggers`, a `TOKEN_BUDGET_REACHED` trigger kind, a `_spend_baseline(record)` reader, and `spend_baseline` carried on `Trigger` and `ResumePlan` and copied in `_fix`.
- **CLI** (`eval/orchestrator/cli.py`): thread `token_budget` into `TrialConfig`; print the token spend in the trial outcome; carry `spend_baseline` across resume.
- **Monitor** (`eval/orchestrator/monitor.py`): `SUCCESS_TERMINALS` already includes `stopped`; no change unless a token-specific view is needed.
- **Docs**: add the glossary terms below; update the `TargetRun` entry; update the app CONTEXT; update `docs/design/domain-model.md` if it carries the eval bound.

### Glossary (new terms)

- **Token spend**: the tokens a trial's project consumed, measured as the delta between the project's cumulative token total at a poll and the trial's **spend baseline**.
- **Token budget**: the per-`Target`-declared bound on a trial's token spend; on overflow the trial stops the active run and terminates `stopped`.
- **Spend baseline**: the project's cumulative token total at the trial's first spend poll; persisted (`spend_baseline`) and carried across a resume.
- **Usage ledger**: the process-wide, per-project, per-agent token accumulator the app exposes at `GET /projects/{id}/usage` as the two-axis typed surface (`context_tokens` and `generated_tokens`) plus the budget scalar `total_tokens`.
- **Context tokens**: the input axis - `cached` (`input_token_details.cache_read`) plus `uncached` (fresh input plus `cache_creation`).
- **Generated tokens**: the output axis - `reasoning` (`output_token_details.reasoning`) plus `visible` (output minus reasoning).

## Testing Decisions

- Test external behaviour only: the middleware's observable effect on the ledger and the API; the eval's observable effect on the record and the stop call.
- **App unit tests**: a fake model emits fixed `usage_metadata`; assert the ledger's two axes and per-agent breakdown; assert an unscoped record is excluded from a project snapshot; assert the middleware fails open when the config is absent.
  F16 pins the worked example (`input=12,991,082 / output=215,821 / cache_read=12,002,944 / reasoning=135,011` -> `cached=12,002,944 / uncached=988,138 / reasoning=135,011 / visible=80,810`), `cache_creation` folding into `uncached`, and the clamp guards (`cache_read > input`, `reasoning > output`) against a negative component.
- **App API tests**: `GET /projects/{id}/usage` via `TestClient` after recording into the ledger; assert the two axes and zeros for an empty project.
- **Eval unit tests**: mirror the cap tests in `tests/eval/test_orchestrator_trial.py` with a `FakeApi` that serves a usage payload; assert the stop call, the recorded spend/overshoot/by-agent, the baseline snapshot, and resume carry-over.
- **Eval setup tests**: `token_budget` parses and rejects a non-int, mirroring `hunt_config_budget`.
- **Eval surfer tests**: a token stop is detected from the record and carries the baseline.
- Prior art: `tests/eval/test_orchestrator_trial.py` (`SeqListFileStore`, `FakeApi`, `FakeClock`), `tests/eval/test_orchestrator_surfer.py`, `tests/eval/test_orchestrator_setup.py`, `tests/llm/test_llm_session.py`.

## Out of Scope

- **Cost.** Only token amounts; no pricing.
- **One-shot calls.** `invoke_role` calls stay untracked (recorded design lack).
- **The gateway aggregate.** LiteLLM spend logs and Langfuse metrics are not used; the client ledger is the single source.
- **Persisting the ledger.** It is process-wide and in-memory; it dies with the app process.
- **The database.** The usage endpoint does not read Postgres.

## Further Notes

- The tracking is decoupled from `observe`: an `observe=False` turn is still counted.
- The middleware must not depend on Langfuse being configured.
- The token budget is trial-wide (checked in every phase poll), unlike the hunting cap, which is hunting-only.
- The `spend_baseline` mirrors `cap_baseline`: it protects a resumed or seeded trial from a prior run's spend.
- **Known limitation:** a blackloop-cut streamed turn closes the stream before the model response completes, so `wrap_model_call` never records usage and the cut turn's tokens are not counted.
  The provider does not deliver usage on a client-aborted stream, and the harness never fabricates an estimated number, so a trial's recorded spend can undercount by the cut turns it ran.
