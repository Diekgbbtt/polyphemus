# Eval provider-resilience design (draft)

*Status: draft for operator review (2026-10-05). Covers the two failures surfaced by the eval bug map (`docs/design/eval-bugs-map.md` §8-9): (A) the opencode-go provider quota and the LiteLLM gateway cost guard; (B) the ubiquitous provider-failure handling pattern for agents, and the abolition of the harness-fabricated `technical-infeasibility`. This document authorises no code change.*

*Implementation note (#329, 2026-10-06): the Part 2 slice that classifies a provider failure distinctly, backs off, avoids failing the run outright, and stops the pod fabricating `technical-infeasibility` has LANDED (`docs/design/hunting-329-provider-failure-classification-adr.md`): `app/llm/provider_failure.py` (typed `ProviderUnavailableError`), the pod/triager/surfer propagation, and `runtime.start_hunting` persisting `interrupted` on a provider-caused pass abort. The full stop/flush/resume re-scheduling, the eval-monitor `interrupted` handling, and Part 1 remain #331/#330.*

*Implementation note (#330, 2026-10-06): **Part 1 (the gateway cost guard) has LANDED** (`docs/design/llm-gateway-100-decisions.md`, ADR D13). `sync.run_sync` provisions each provider virtual key with USD `budget_limits` (`5h/7d/30d`) scaled by a conservatism factor (default `0.5`) plus an optional `rpm_limit`, idempotently (the diff ignores litellm's server-set `reset_at`); `gateway/litellm_config.yaml` enables `fail_closed_budget_enforcement: true`. Verified live: a zero-USD window on a virtual key returns 429 at auth before the provider is called. Unpriced models fail open (no `block_requests_for_models_without_pricing` in the pinned 1.96.0); the sync logs every unpriced registered model at bootstrap. Part 2's stop/flush/resume remains #331.*

*Implementation note (#331, 2026-10-06): the slice that records an `interrupted` run's CAUSE and surfaces it to the eval has LANDED (`docs/design/hunting-331-provider-resume-adr.md`): the abort carries the typed `ProviderUnavailableError`, `runtime.start_hunting` stamps `hunting_runs.stats` (`interrupt_reason`/`provider_status`/`quota_exhausted`/`retry_after_s`), the eval trial reads it into the hunting-phase `failure` (fixing the `_phase_hunting` `failure=None` gap), and the monitor is pinned to defer `interrupted` rather than escalate it. The app-layer resume re-scheduling and the 429-vs-consumed-credits policy are ESCALATED operator decisions.*

## Part 1 - Gateway cost guard (failure A)

### 1.1 The provider cap, verified

The opencode-go quota is **dollar-denominated**, not token-denominated (source: `anomalyco/opencode` `packages/web/src/content/docs/go.mdx`, `opencode.ai/docs/go`):

- **5-hour limit - $12 of usage**; weekly - $30; monthly - $60.
- Model prices are per-million USD; `deepseek-v4.1-flash` is `$0.15` input / `$0.60` output / `$0.003` cached-read off-peak, doubled at peak (01:00-04:00 and 06:00-10:00 UTC Mon-Fri).

The gateway's models.dev costs for `opencode-go/deepseek-v4.1-flash` (`input_cost_per_token=0.00000015`, `output_cost_per_token=0.0000006`, `input_cost_per_token_cache_read=0.000000003`) match the off-peak prices exactly. So LiteLLM's spend accounting aligns with opencode-go's quota accounting - the earlier "USD vs tokens" objection is moot.

*Correction (#330 iteration 2, 2026-10-06): live verification falsified this paragraph and the price line above.*
The models.dev record for `opencode-go/deepseek-v4.1-flash` is `input=0.15`, `output=0.6`, `cache_read=0.003` (per million USD), while opencode-go's **effective off-peak** rate is ~6x lower (`0.025` / `0.10` / `0.003` per million).
So the models.dev record does NOT match opencode-go's off-peak prices, and LiteLLM's spend accounting did NOT align with the provider's.
The authored `cache_read` was also inert: the D5 key `input_cost_per_token_cache_read` appears nowhere in litellm 1.96.0, so cached input was priced at 0.
The fix is the provider-specific cost override (`sync_mapping.PROVIDER_COST_OVERRIDES`, ADR D13 amendment 2026-10-06), which re-authors the deployment's `model_info` cost keys from the effective off-peak rate on every sync, plus the D5 canonical cache-key correction (`cache_read_input_token_cost`).

### 1.2 Compatibility with the current stack - verdict: HIGH

The design is a small extension of seams that already exist, not a new subsystem:

| Design element | Current stack | Compatibility |
|---|---|---|
| Pricing source: models.dev | `app/llm/sync.py::_fetch_catalog` already fetches `https://models.dev/catalog.json`; `sync_mapping.py` maps `cost.input/output/cache_read/cache_write` per-million -> per-token into `model_info` (`input_cost_per_token` etc.) | **Already built.** The pricing dependency is provisioned today. |
| Persistent DB | `gateway/litellm_config.yaml` sets `store_model_in_db: true`; DB `polymerhus_gateway`; migrations owned by `gateway_entrypoint.py::_run_migrations` | **Already built.** |
| Budget/rate on the client key | `sync.py::GatewayClient.ensure_virtual_key` already creates/updates a virtual key per provider, scoped to models, idempotently (C9 convergence) | **Natural extension:** add `max_budget`/`budget_limits`/`rpm_limit` to the same provisioning. |
| Budget reservation | enabled by default (`disable_budget_reservation: false`); estimates max request cost, reserves pre-call, rejects on overflow, reconciles post-call | **Built into LiteLLM.** |
| Fail-closed enforcement | `general_settings.fail_closed_budget_enforcement: true` validates spend against the DB and 503s when unverifiable | **One config line.** |
| Client | In gateway mode the client sends the APP-MINTED virtual key as the bearer (ADR D3, amended #335: the provider credential is only the derivation seed, never the inbound key); the gateway resolves it as a virtual key | **No client change.** |

### 1.3 Impact map

- `src/polymerhus/app/llm/sync.py` - `GatewayClient.ensure_virtual_key` gains a budget/rate payload; `run_sync` passes the configured budget windows; the snapshot/diff must include the budget surface so a budget change converges (extend `_registered_matches` / the snapshot, or treat the budget as a separate idempotent `key/update`).
- `gateway/litellm_config.yaml` - `general_settings.fail_closed_budget_enforcement: true` (and the pricing-gap policy, see risks).
- `src/polymerhus/app/llm/sync_mapping.py` - optional: peak-price authoring (see risk 1).
- `.env` / compose - the budget constants (5h/$12, 7d/$30, 30d/$60) and any conservatism factor.
- Tests - `tests/.../test_llm_sync*.py` (budget payload + convergence), a gateway integration test (budget trips -> 429/503).
- Docs - `docs/design/llm-gateway-100-decisions.md` (new ADR) and `app/CONTEXT.md`.

### 1.4 Risks ranked

1. **Peak/off-peak price mismatch - HIGH.** models.dev carries one price (off-peak); opencode-go charges 2x during peak (01-04, 06-10 UTC Mon-Fri). The observed failure was inside the 06:00-10:00 peak window. LiteLLM will **undercount during peak**, so a `$12` budget trips after the provider has already charged more and 429'd. Mitigation: a conservative budget (e.g. `$6`) sized for the worst-case peak, or author peak prices (a custom callback or a per-time cost), or a custom `CustomLogger`. The conservative budget is the simplest and safest.
2. **Unpriced/unknown models - HIGH.** Models with no models.dev entry (`opencode-go/deepseek-flash`, `glm-5.1`, `minimax-m2.5` observed) carry no cost; `reserve_budget_for_request` returns `None` when it cannot estimate, so the budget **fails open** for them (LiteLLM issue #35524). Mitigation: pin the eval to priced models; or set a pricing-gap policy. `block_requests_for_models_without_pricing` is claimed in the design but **not verified in LiteLLM 1.96.0** - treat as unconfirmed and test it; otherwise reject unpriced models at the sync or eval-config layer.
3. **Window semantics mismatch - MEDIUM.** The provider's windows are rolling (5h/weekly/monthly); LiteLLM's `budget_duration` resets on a schedule (calendar-aligned for 1h/24h). A rolling-vs-fixed window can allow a boundary burst. Mitigation: express all three windows via `budget_limits` (`[{budget_duration: 5h, max_budget: ...}, {7d, ...}, {30d, ...}]`) and keep each conservative.
4. **Enforcement substrate - MEDIUM.** Budget reads use a spend counter (Redis for multi-pod; in-memory/DB single-pod). A counter reset can under-report spend. Mitigation: `fail_closed_budget_enforcement: true` (DB-validated; 503 on unverifiable). Our single co-located proxy + DB should not need Redis.
5. **Budget-exceeded is still a 429/503 - MEDIUM.** The guard prevents the provider 429 but introduces a gateway 429 (or 503 under fail-closed). The agents must handle it gracefully - this is Part 2. The two parts are complementary, not alternatives.
6. **Bundled cost-map staleness - LOW.** `LITELLM_LOCAL_MODEL_COST_MAP=True` uses the image's bundled map, but the sync's authored `model_info` costs take precedence for known models.

### 1.5 Recommended configuration (draft)

Per-provider virtual key (via the sync), with a conservative factor `k` for peak (start `k=0.5`):

```
budget_limits = [
  {"budget_duration": "5h",  "max_budget": 6.0},   # provider 5h cap $12 / peak factor
  {"budget_duration": "7d",  "max_budget": 15.0},  # provider weekly $30 / 2
  {"budget_duration": "30d", "max_budget": 30.0},  # provider monthly $60 / 2
]
rpm_limit = <optional per-minute smoothing>
```

`gateway/litellm_config.yaml`:
```yaml
general_settings:
  fail_closed_budget_enforcement: true
```

### 1.6 Open edges (operator)
- Confirm `block_requests_for_models_without_pricing` exists in the pinned LiteLLM; if not, choose the pricing-gap policy (reject unpriced / allowlist).
- Choose the conservatism factor `k` (peak headroom) and whether to author peak prices.
- Decide whether the gateway guard is the primary control, or the eval-orchestrator prompt's pause/stop is (the two are complementary).

## Part 2 - Ubiquitous provider-failure handling (failure B)

### 2.1 What exists today (fragmented)

- **Module lifecycle already exists** (`attack/hunting/runtime.py`): `start_hunting` schedules the orchestrator pass and the run-scoped surfer as SESSIONS under the ADR Q13 ids (`hunting:<run_id>:orchestrator|surfer|hunt:<config_id>|pod:<config_id>:<spec_id>`); `stop_hunting` cancels every session by id, drains, reaps the actor, persists `stopped`; `flush_hunting_checkpointer` / `flush_run_scoped("hunting", run_id)` archives the module checkpointer index (typed `FlushResult`); `hunting_module_context()` resolves the checkpointer; per-session `hold_session`/`resume_session`/`cancel_run` exist (Q12/Q17).
- **Orchestrator actors** (`app/llm/actor.py::run_session_agent`) already isolate a raising turn: retry the retryable class, then degrade to a no-decision reply and **survive**. The hunt pass adds `DegradedTurnBreaker` (#280 Part 2): 5 consecutive degraded turns -> `HuntOrchestrationDegradedError` -> `runtime.start_hunting` persists `failed`.
- **The pod is the outlier:** it is a static config-driven graph (`build_pod_graph`), not on the actor seam. A raise escapes to `pod/pod.py:114-118`, which fabricates `verdict=unsuccessful`, `terminal_reason=technical-infeasibility`, `iterations=0`, `error=<exc>` - a **domain verdict for an infrastructure failure**. This is the flaw to abolish.

### 2.2 The pattern (operator direction), sharpened

**Principle:** a provider/LLM failure is an *infrastructure* condition, handled once at the app layer, scaffolded under every agent seam; it is never encoded in domain data and never becomes a domain verdict.

**Signal.** Introduce a typed, retryable `ProviderUnavailableError` (or reuse the `_is_retryable` classification) raised by the session/actor seam when a turn exhausts its retry budget on a provider failure (429/5xx/timeout/quota). The signal carries: the provider, the model, the HTTP class, and the run/session id.

**Handle (app layer, not the agent).** A single provider-failure handler wraps every agent session:
1. **Stop** the affected session(s) with the correct primitive (`runtime.cancel_run` / `hold_session`) so the agent is not left hot-looping.
2. **Flush** the affected threads' checkpoints (`flush_run_scoped(module, run_id)`), so the pre-failure state is durable in the pooled saver.
3. **Mark the run `interrupted`** (a resumable terminal), never `failed` - `failed` is reserved for genuine domain failure.

**Resume (healthy state).** When the provider is healthy again, the run is resumed: the module re-schedules the affected sessions, and each agent resumes from its flushed checkpoint - the state **before** the failed turn. The `ProviderUnavailableError` is not committed to the trail (langgraph commits only successful super-steps; `add_messages` dedups), so resume is clean.

**Per-agent-type modularity (the operator's requirement).** The stop/flush/resume granularity is per agent type, keyed by the ADR Q13 session id:
- `hunting:<run_id>:orchestrator` - the pass; flush its actor thread.
- `hunting:<run_id>:surfer` - the mover; no LLM, unaffected.
- `hunting:<run_id>:hunt:<config_id>` - a hunter; flush its session thread.
- `hunting:<run_id>:pod:<config_id>:<spec_id>` - a pod; flush its runner/triager threads.

A provider failure stops exactly the types it affects (e.g. all pods but not the orchestrator), flushes their threads, and leaves the run `interrupted`; resume restarts exactly those types from their checkpoints. This is the "modular start/stop/flush/resume of the sub-module itself, such that only that type of agents execute" the operator asked for.

### 2.3 Abolish the fabricated `technical-infeasibility`

- Remove the catch-all in `pod/pod.py:114-118` that converts any raise into `technical-infeasibility` with an `error`. A provider failure in the pod must **propagate as `ProviderUnavailableError`** to the app-layer handler (or the pod session must be held), never written as a domain verdict.
- The pod's `technical-infeasibility` terminal remains only for a **genuine** target infeasibility asserted by the runner (`RunnerStep(infeasible=True)`), which already routes through `infeasible_terminal` (`pod/graph.py:609-614`). The harness-level catch is deleted, not reworded.
- Any `PodExport` persisted on a provider failure must be absent (or explicitly a non-domain "no verdict" record), so the assessment never reads a fabricated verdict.

### 2.4 Concrete seams and changes

- `app/llm/actor.py` / `app/llm/session.py` - raise the typed provider error instead of degrading silently where a domain result would be fabricated; the actor degrade hook stays for the *orchestrator* no-decision path but must not feed a domain verdict.
- `app/runtime.py` - add a provider-failure entry that stops+flushes the affected session type and stamps the run `interrupted`.
- `attack/hunting/runtime.py` - `start_hunting` maps `HuntOrchestrationDegradedError` to `interrupted` (not `failed`) when the cause is provider-unavailability; add the resume entry that re-schedules the affected session types.
- `attack/hunting/pod/pod.py` - delete the fabrication; propagate the typed error.
- `app/llm/checkpoints.py` - confirm the flush/resume path is per-thread and idempotent for the pod's runner/triager threads (the module index already archives per run).
- Eval monitor (`eval/prompts/orchestrator.md`, `eval/orchestrator/monitor.py`) - a provider-failure run state is `interrupted` and resumable; the monitor's `deferred` handling must not treat it as a terminal failure.

### 2.5 Impact map

- Agent seams: orchestrator (recon + hunting), hunter, pod runner/triager.
- Runtime: `app/runtime.py`, `attack/hunting/runtime.py`, the surfer/mover dispatch.
- Domain: `PodExport` no longer carries infrastructure state; the six-value terminal vocabulary is unchanged (no new value added).
- Eval: monitor/orchestrator prompt; the trial record's `failure` field should carry the provider cause (fixing the `_phase_hunting` `failure=None` gap too).
- Tests: unit (typed error propagation, no fabrication), integration (stop+flush+resume round-trip), e2e (a simulated provider outage -> interrupted -> resume completes).

### 2.6 Risks / open edges

- **Resume correctness** depends on the checkpoint being flushed *before* the process/agent dies; a hard kill loses the in-memory index. The existing `flush_run_scoped` at the run terminal is the model; the provider-failure path must flush before marking `interrupted`.
- **Idempotent resume** must not double-run a pod/hunter (the at-least-once produced/consumed markers already guard the mover; the resume path must respect them).
- **Which failures are "provider" vs "domain"** is a classification decision; the `_is_retryable` set is the starting point, extended to the quota/429 class.
- **The eval monitor** must not escalate an `interrupted` run; this touches `eval/orchestrator/monitor.py` and the orchestrator prompt.
