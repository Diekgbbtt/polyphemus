# LLM API Gateway (#100) - Architectural Decision Records

Decisions taken (operator-authoritative, grilled 2026-08-10) for ticket #100: the dynamic, capability-aware LLM API gateway (LiteLLM + models.dev glue) - the shared, cross-cutting subsystem that eases the two sub-issues #99 (capability-adaptive client) and #95 (context-window auto-compact).
Companion to `docs/design/dynamic-llm-gateway-design-spec.md` (the architecture-level statement this ticket realises).
These records are **authoritative over** the design spec where they clash - the spec is corrected in the same change (see the "Spec corrections" appendix).
Where a record and the live code disagree, the code wins and the record is stale.

The grilling ran Q1-Q10 with the operator. Each decision below is the ratified answer to its question, with rationale and the load-bearing nuance.

## D1 - Co-located proxy subprocess (B2), one container

LiteLLM runs as a **second ASGI process inside the agent container**, not as a standalone compose service and not as an embedded `litellm.Router` module.
The agent keeps its existing uvicorn process (`polymerhus.app.main:app`, port 8080); a litellm proxy ASGI process (`litellm.proxy.proxy_server:app`) runs on an **internal** port (4000) in the same container.
The two processes have **independent lifecycles and reload policies** - the agent's `--reload` does not restart the proxy and vice versa.
`STORE_MODEL_IN_DB=True`: the gateway persists its model records in the **shared postgres** (the app's existing DB), under litellm's own tables/schema - no separate database.

**Rationale.** A standalone compose service adds a network hop, a separate health surface, and a coordinate-two-services rollout for a thing that is, by the operator's boundary (D3), only routing + metadata + caching - the cost is unjustified. An embedded `litellm.Router` would have forced the agent's process to own model-key custody and the management-API surface, re-creating the "second competing client layer" the spec's §3.5 warns against - the proxy keeps those concerns in their own process. One container keeps the deploy surface unchanged; two decoupled ASGI processes keep the blast radius decoupled.

**Forward constraint.** The two processes stay independent: the proxy's failure must not take down the agent (and vice versa). The entrypoint (D10) is responsible for ordering and signal propagation; it does not couple the lifecycles beyond that.

## D2 - Bootstrap-only sync; no scheduler

A stateless CLI, `python -m polymerhus.app.llm.sync`, performs the spec's `fetch -> join -> map -> validate -> diff -> push` pipeline **once at container bootstrap** - invoked by the entrypoint after the proxy health-checks and before the agent ASGI starts.
There is **no out-of-band scheduler**; no cron, no async refresh loop. The only way records refresh is a container restart (or an explicit operator-triggered management-API call).

**Rationale.** The freshness requirement is bounded by "new/changed models propagate within an acceptable window" (spec §6). In this system a model change is a deploy-class event (the role env vars select models at boot), so a bootstrap pull is the natural cadence; an out-of-band scheduler adds an always-on component (a long-running service, exactly what spec §3.3 says the sync is *not*) for a problem that restart-on-deploy already solves. Stale records between restarts are surfaced via the staleness field (D6) and the conservative-unknown policy (D7).

**Spec correction.** Spec §6's "on the order of tens of minutes" cadence is **superseded** - the running cadence is "at every bootstrap". The "fail toward staleness" principle (spec §3.3 item 9) survives intact: a failed sync leaves the last-known-good records in place (D9).

## D3 - Gateway owns routing + metadata + caching; the client owns roles + retries + the profile reader

The responsibility split, with every responsibility in exactly one place (CODING_STANDARD §1):

**The gateway owns** (litellm proxy):
- routing/load-balancing/fallback across upstream providers
- provider API-key custody (the gateway concentrates keys; the agent never sees them)
- capability/context/cost metadata serving (the `/model/info` enriched surface; D5-D7)
- runtime enforcement (context-window guard, capability gating at the routing layer)
- prompt caching configuration (D8)
- `num_retries=0`: the gateway is a **hop**, never a retry layer

**The client owns** (`app/llm/providers.py`, `roles.py`, and a new `app/llm/capability.py`):
- per-role construction (`Role` records, `build_chat_model`, the `thinking` baseline)
- the **#73 escalating retry as the SINGLE retry layer** - `invoke_with_escalating_timeout`, `max_retries=0` on the client, never nested with the gateway
- the session vs one-shot seams (`invoke_role`, `stateful_turn`, `_build_agent`)
- Langfuse callbacks at construction (must keep flowing through the gateway - D8 passthrough keeps this)
- a new thin **capability-profile reader** (D7): session-scoped, resolve-and-hold, fail-open

**The sync owns** (`app/llm/sync.py`):
- the two sources (provider `/v1/models` + models.dev `catalog.json`) and the gateway management API only; nothing else

**Rationale.** A second competing client layer is the specific failure mode that would re-create the §3.5 coupling the design exists to remove. The client's job is role-shaped (per-role construction, the retry axis, the seam choice); the gateway's job is model-shaped (routing, metadata). Keeping the capability-profile reader in the client (not the gateway) keeps the gateway harness-agnostic: the reader is a *consumer* of the gateway's metadata surface, not a property of the gateway itself.

## D4 - Additive blast radius; no agent module touched

The change is **additive** to the live agent modules - no `actor`, no `checkpointer`, no `SessionAddress`, no agent module (`crawl_agentic.py`, `job_agent.py`, `orchestrator_agent.py`, the hunting module) is modified by this ticket.
The four additions:
1. `build_chat_model` resolves `base_url` through the gateway when `LLM_GATEWAY_URL` is set; direct per-provider mode is unchanged when it is not.
2. A capability-profile reader in `app/llm/capability.py` - the *surface* #95/#98 and #99 will consume. Their **consumers** are NOT built here (#95 is blocked by #94; #99's thinking/method adaptation is #99's own work).
3. The sync CLI + the entrypoint ordering (D10).
4. A crawl capability warning/refusal with graceful degradation (a non-tool-callable model on the crawl path: warn the operator, refuse to execute, degrade gracefully - the *strategy-level* tool-loop answer stays #99's work).

**Rationale.** The seams are the `app/llm` session/model-construction seams (the `_build_agent` -> `create_agent` path, the `build_chat_model` call sites), not the agent modules. The async-actor migration (`feat/async-actor-agents`, ratified 2026-08-10 in `statefulness-pattern-matrix.md`) already moved the production agents (ReconOrchestratorActor, HuntOrchestratorActor, HuntingHunterActor, the per-pod configurator/triager via ContextVar + `stateful_turn`) onto those seams; the legacy `decide_routing` one-shot path (`orchestrator_agent.py`, `job_agent.py`) is superseded (retained as OUTLIER-3 for tests/rollback) and is not the production path. Touching the agent modules would re-open the live wedge #80 warned about.

## D5 - Capability Record -> LiteLLM `model_info` mapping (the only product-specific field names)

| Canonical Capability Record (spec §4) | LiteLLM `model_info` field |
|---|---|
| `model_id` | registered `model_name` (the client sends today's `provider:model` string verbatim; the zen-family id strip moves from `build_chat_model` into the mapping layer in gateway mode - the gateway owns id translation) |
| `context_limit` / `output_limit` | `max_input_tokens` / `max_output_tokens` |
| `cost_input` / `cost_output` | `input_cost_per_token` / `output_cost_per_token` (the mapping layer performs the per-million -> per-token unit conversion as a pure function, unit-tested) |
| `cost_cache_read` / `cost_cache_write` | `input_cost_per_token_cache_read` / `input_cost_per_token_cache_write` |
| `supports_tool_calling` | `supports_function_calling` (+ `supports_parallel_function_calling` for the crawl `bind_tools` path) |
| `supports_structured_output`, `supports_reasoning` + effort tiers, `modalities_in`/`modalities_out`, `open_weights` | custom passthrough keys (litellm's `/model/info` returns them unchanged) |
| `reasoning_in_response` / `reasoning_field` (the reasoning-replay surface, from models.dev `interleaved` + provider `shape`) | custom passthrough keys `reasoning_in_response` (bool) / `reasoning_field` (`reasoning_content` \| `reasoning_details`), asserted per the D11 matrix; Rule 1 provenance applies |
| `source` / `synced_at` / `staleness` | custom keys `capability_source` / `capability_synced_at` / `capability_staleness` (full provenance) |

**Rule 1 (conservative-unknown, load-bearing).** LiteLLM merges its *own* bundled cost-map defaults into `model_info` for models it recognises - trusting those would re-introduce the exact "silent optimistic default" failure the spec exists to eliminate. So the client-side **reader trusts a record's capability fields only when the record carries our `capability_source` provenance tag**; a record without the tag, or a field absent from a tagged record, is `unknown` - treated as `false` for capability gating (spec §5), with the gap surfaced. `unknown` is never encoded as a value; it is the **absence of an authored field**.

**Rule 2 (per-provider override).** models.dev supports `base_model` inheritance (a provider-specific TOML overriding/omitting fields from a canonical model TOML). The mapping layer **resolves the inheritance before push** - one global truth per (provider x model) lands in the gateway - so the reader never has to re-resolve inheritance at read time.

**Rationale.** The mapping layer is the only place product-specific field names live (spec §3.3); Rule 1 is what makes the conservative-unknown principle actually hold against a gateway that would otherwise silently fill in defaults; Rule 2 keeps the reader a single-shape lookup.

## D6 - The gateway surface for #95: context/output window field + access path

The capability-profile reader (D7) exposes a typed `CapabilityProfile` with:
- `context_limit: int | None`
- `output_limit: int | None`
- `source: str | None` and `synced_at: datetime | None` (for logging/staleness)

**Resolution order** (inside the reader, at session construction - stateful and one-shot alike):
1. gateway `/model/info` -> `model_info.max_input_tokens` (provenance-tagged per D5 Rule 1)
2. `LLM_ROLE_MODEL_CONTEXT_LIMIT` env override (the spec §3.3 fallback when the gateway is absent or the record is unknown)
3. 150k default (spec §5; the SwissAI-is-not-on-models.dev gap takes this default)

`output_limit` has **no env fallback** - it resolves to `None` when the gateway/registry lacks it, and the consumer (#95) decides. #95's own threshold default (90%) stays in #95.
The reader is **session-scoped and resolve-and-hold**: resolved once per `SessionContext` and held; never re-queried mid-session. This keeps capability resolution **off the #73 timeout/retry axis by construction** - the #99 non-negotiable.
Unknown at runtime falls back silently (the session must start), but the gap is logged + the sync's notification path (D9) surfaces it.

**Rationale.** This closes #95's open question 1 ("what retrieves context-window lengths dynamically") in THIS ticket so #95 builds on a stable surface. The resolution order puts the gateway first (it is the authoritative synced source) and the env override second (operator-set, beats the default only when the gateway is silent) - never the reverse, because an env override beating the gateway would let a stale env value silently shadow a fresh synced record.

## D7 - The capability-profile reader: client-side, fail-open, provenance-gated

A new `app/llm/capability.py` owns a `CapabilityProfile` dataclass and a reader that resolves it per (provider, model). The reader is the surface #95/#98 and #99 consume; it is NOT their consumer logic.

Properties:
- **client-side**: lives in `app/llm`, not in the gateway - keeps the gateway harness-agnostic (D3).
- **fail-open**: a missing/unreachable gateway degrades to the env -> default chain (D6), never raises into the session construction path - the session must always be able to start.
- **provenance-gated**: applies D5 Rule 1 - trusts capability fields only when `capability_source` is present; absence is `unknown`.
- **resolve-and-hold**: cached per `SessionContext` - one resolution per session, held for the session's lifetime.
- **off the retry axis**: never retries inside the #73 escalating wrapper - resolution is a single synchronous read.

**Rationale.** A reader that raised into session construction would re-create the "capability retry nested inside the latency retry" defect #99 names; a reader that polled mid-session would couple capability freshness to the request path. Resolve-and-hold is the minimal contract that satisfies #99's non-negotiables without inventing a new failure surface.

## D8 - Prompt caching: auto-inject + passthrough; no response cache

The gateway is configured with `cache_control_injection_points` (a system-prompt breakpoint) and forwards client-sent `cache_control` / `prompt_cache_key` unchanged. The `LITELLM_CACHE_TYPE` response cache is **not enabled**.

Three verified facts drove this (litellm prompt-caching docs, the auto-inject tutorial, the tokenroute/openclaw passthrough docs):
1. **The KV cache lives only at the provider.** Neither the SDK nor the gateway "does" KV caching; they only influence hit rate via byte-identical prefixes, annotations (`cache_control`), and routing hints (`prompt_cache_key`).
2. **DeepSeek (the zen family) and OpenAI cache automatically server-side** - zero client/gateway work; byte-identical prefix suffices; hits priced via `input_cost_per_token_cache_read` (already mapped in D5).
3. **Auto-inject is the one gateway-side primitive** worth configuring: the gateway itself marks the stable system-prompt prefix with `cache_control` annotations, no client code change. It covers Anthropic-native models if they ever enter the provider set; for the current openai-compatible provider set it is a no-op (automatic).

The response cache (`LITELLM_CACHE_TYPE=redis|in-memory`) stays out - it is the identical-request cache, and litellm's own proxy docs warn against it for multi-turn agentic traffic. A stateful agent loop's requests mutate each turn; the cacheable surface is the **prefix**, not the whole request, and the prefix is already handled by provider-native caching.

**Rationale.** The original "passthrough only" proposal under-counted the gateway-side primitives (auto-inject exists). The corrected proposal adds auto-inject (one config stanza, zero client cost, covers the anthropic-family future) and keeps the response cache out (it would risk stale tool results and corrupted observability).

## D9 - Sync validation: fail toward staleness on source failure; cold stop on collapse; log-only gaps

Two distinct failure modes, two distinct exit codes from the sync CLI (the entrypoint branches on them - D10):

- **Source failure** (registry fetch fails, provider `/v1/models` refuses, parse error): **skip the push, keep the gateway DB as-is, exit non-zero (soft)**. The entrypoint logs loudly and **starts the agent anyway** - the stack runs on stale records. This is the spec's "fail toward staleness, not toward guessing" (§3.3 item 9).
- **Implausible collapse** (desired-set count < 50% of the last-known-good snapshot, or zero records): **abort the entire push, exit non-zero (hard) - cold stop**. The entrypoint **halts before starting the agent** - the agent must not start on a freshly-collapsed registry state. This is fail-loud rather than run-on-stale.

**Diffable push.** `GET /model/info` returns the registered set; the sync computes add/update/delete per model against the desired set (idempotent - a second run with no changes pushes nothing). Update = push the full `model_info` (all fields authored explicitly, D5 Rule 1), never a partial merge - a stale record can never partially shadow a fresh one.

**Last-known-good snapshot.** The sync persists a small snapshot (the desired-set's record count, hashed) after every successful push; the collapse check compares the next run's desired count against it. The snapshot lives in the gateway DB (alongside litellm's tables) - no new state surface.

**Per-env independence.** Gateways are per-env (dev/staging/prod); each env's sync writes only its own gateway. A bad registry pull in one env cannot propagate to another.

**Unknown-model gap notification.** Unknown models (exist in provider `/v1/models`, no registry entry - the SwissAI family) are still registered for routing (existence is real), but pushed with **no capability fields** - the reader then resolves them as unknown (D6). The notification path is **runtime logs only** for now - the cold stop is the strong signal for the collapse case; the unknown-model gap is a per-model data-quality matter, not a sync failure.

**Forward step (recorded).** An improved version adds configuration checks in `settings.recon` for the unknown-model gap (operator curates overrides); not in this ticket.

## D10 - Dependency plumbing: pinned layer + entrypoint ordering

- **New `requirements-gateway.txt`**: pins `litellm` (the latest stable at install time, e.g. `litellm==1.96.0`) and `httpx` (the models.dev fetch - there is **no separate "models.dev client" package**; the registry is a plain JSON endpoint `https://models.dev/catalog.json`, fetched directly). Layered in the Dockerfile like `requirements-observability.txt`.
- **Entrypoint script** (new, or extended): the ordering is
  1. start the litellm proxy ASGI on internal port 4000
  2. poll `GET /health/liveliness` until ready (bounded retries)
  3. run `python -m polymerhus.app.llm.sync`
  4. **branch on the sync's exit code**: soft (source failure) -> log and proceed; hard (collapse/zero) -> halt, do not start the agent
  5. start the agent ASGI on port 8080
  6. `SIGTERM`/`SIGINT` propagate to both children; the proxy drains, the agent exits
- **`STORE_MODEL_IN_DB=True`** + `DATABASE_URL` (the shared postgres) + `LITELLM_MASTER_KEY` (from env, never in the repo).
- The two processes keep independent uvicorn invocations and independent reload policies (D1).

**Rationale.** The entrypoint owns the ordering and the soft/hard branch; it is the only place the two processes' lifecycles meet. Pinning the layer like `requirements-observability.txt` keeps the gateway's dependency surface isolated and auditable - a litellm version bump is a one-file review, not a base-image rebuild.

## D11 - Reasoning-replay surface: metadata, grey point, replay semantics (operator caveat, grilled 2026-08-11)

The operator raised the reasoning-replay caveat after T1: for some agents, reasoning tokens must be **sent in the response** and **replayed back in further turns** (hopefully cached, if the provider supports it) so the next-turn prefix is byte-identical and provider-native KV caching can hit. Grilled against the live `catalog.json`; five ratified answers:

1. **Metadata surface (D5 extension).** The mapping layer authors two new provenance-tagged keys per (provider, model): `reasoning_in_response` (bool) and `reasoning_field` (`reasoning_content` | `reasoning_details`), asserted from models.dev `interleaved` + the provider `shape` sub-key. The assertion matrix (documented and unit-tested in T2): string `shape="responses"` + `interleaved` present -> assert; string `shape="completions"` -> NOT asserted regardless of interleaved; the zen-family npm-SDK dict form (`{"npm": "@ai-sdk/openai"|"@ai-sdk/anthropic"}`) carries no string shape, so `interleaved` presence is the signal there. `interleaved: true` (Anthropic-style, reasoning in content) -> `reasoning_in_response` asserted with `reasoning_field` ABSENT; `interleaved: {"field": ...}` (deepseek-family, e.g. `reasoning_content`) -> field authored.
2. **Reader surface (D6/D7 extension).** `CapabilityProfile` gains `reasoning_in_response: bool | None` and `reasoning_field: str | None`, provenance-gated exactly like the context window (Rule 1): absent tag or absent field = `None`/unknown, never asserted.
3. **Grey point - reasoning caching is NOT assertable from the registry.** `cache_read`/`cache_write` are **pricing** fields, not reasoning-caching evidence. For now: **heuristic proxies only** (`interleaved` + `shape` + cache-presence), explicitly low-confidence, never capability-gating; runtime cache-hit tracking (`usage.cached_tokens`) is observability, not an assertion. **Grill element carried in the replay ticket (T6):** the operator deferred the sound decision; the future direction is an **empirical in-place reasoning-caching checker** in the llm configuration settings (`settings.recon`) that sends a probe request and verifies token caching by delta. Not built now; designed and grilled there.
4. **Replay semantics.** **Encrypted reasoning is replayed as well** (the server may be stateless - replay of encrypted tokens can still be required). Readability is tracked via a **dedicated langfuse llm-response log field**, not by skipping replay. **Investigation element (T6):** whether the server tracks sessions via previous response ids / client-side session continuity such that replay becomes unnecessary.
5. **Passthrough verification belongs to T1 (#104).** The pinned litellm (1.96.0) must forward `reasoning_content`/`reasoning_details` unchanged in responses and accept replayed reasoning in subsequent request messages (openai-compatible). Verified at the **unit tier** (in-process proxy against a mocked upstream, or static litellm-transform tests - no live gateway; docker is down). **T1 is reopened for this single FR-area delta** (it was verifier-APPROVED on the original criteria).

**Rationale.** The caveat is real for the stateful thinking roles (triager, job_orchestrator, the analysis proposers, the hunting roles): their sessions re-pay reasoning cost per turn unless the reasoning is replayed into the byte-identical prefix. The registry gives us the field location but not the caching behavior; the system therefore asserts only what is assertable (in-response + field), tracks hits empirically at runtime, and carries the checker design as a grill element instead of guessing.

---

## Appendix: Spec corrections (land in the same change as the code)

The design spec `docs/design/dynamic-llm-gateway-design-spec.md` is corrected as follows:

- **§3.3 item 1 ("Fetch both sources on a schedule")** - the running cadence is bootstrap-only (D2); "schedule" is re-stated as "at container bootstrap".
- **§6 first bullet ("Sync cadence ... on the order of tens of minutes")** - superseded; the running cadence is "at every bootstrap" (D2).
- **§3.3 item 8 + §5 unknown surfacing** - clarified: unknown-model gap notification is log-only for now, with a recorded forward step to add `settings.recon` configuration checks (D9).
- **§4 Capability Record -> gateway-native mapping** - the mapping table is D5 (the only place product-specific field names live); Rule 1 (provenance-gated trust, absence = unknown) and Rule 2 (inheritance resolved before push) are added.
- **§3.3 item 4 (validate, reject implausible collapse)** - clarified: source failure = soft (skip push, keep DB, agent starts); collapse/zero = hard (cold stop, agent must not start); two distinct exit codes (D9).
- **§3.4 Gateway prompt caching** - clarified: auto-inject (`cache_control_injection_points`) + passthrough; the `LITELLM_CACHE_TYPE` response cache is explicitly out (D8).
