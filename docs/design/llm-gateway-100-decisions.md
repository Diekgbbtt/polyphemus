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

**Amendment (2026-10-06, #335) - the client's gateway credential is an app-minted virtual key, never the provider key.** D3's original assumption - that the provider's API key could double as the LiteLLM virtual key, so "the client's existing bearer just works" - held only while every provider key was `sk-`-prefixed. LiteLLM's `/key/generate` enforces the format (`must start with 'sk-'`) and its inbound `user_api_key_auth` accepts only `LiteLLM_VerificationTokenTable` entries; the opencode-go provider key is now `oc_sk_...`, so minting it returned HTTP 400 and the sync took the D9 HARD path, halting the agent before it started (and it would do so for any non-`sk-` provider key). The client's gateway credential is therefore an APP-MINTED, litellm-native virtual key derived deterministically per provider: `sk-ph-<sha256(provider NUL api_key)>` (`providers.gateway_virtual_key`). The sync mints exactly this key (scoped to that provider's registered models) and the client presents exactly this key as its gateway bearer, so the two agree by construction - no persisted mapping, no new env var. The provider credential still rides each model's `litellm_params.api_key` (the gateway's upstream custody; the #193 rotation diff is unchanged), and `API_KEY_<PROVIDER>` stays required in both modes - in gateway mode it is the derivation seed. `ensure_virtual_key`/`key_info` idempotency is preserved (C9): the derived key is stable for a fixed credential, so a converged run is a no-op and a model-scope change updates. A provider-key rotation rotates the virtual key too (either side derives the new value automatically); the previous virtual key is orphaned but unused - LiteLLM's auth no longer resolves it to the rotated upstream credential. This supersedes the older "the key VALUE is the provider's own API key" claims in `sync.py::ensure_virtual_key` and `eval-provider-resilience.md` §1.2.

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
| `cost_cache_read` / `cost_cache_write` | `cache_read_input_token_cost` / `cache_creation_input_token_cost` (corrected 2026-10-06, #330 iteration 2 - litellm reads these; the earlier `input_cost_per_token_cache_read` / `_cache_write` were inert) |
| `supports_tool_calling` | `supports_function_calling` (+ `supports_parallel_function_calling` for the crawl `bind_tools` path) |
| `supports_structured_output`, `supports_reasoning` + effort tiers, `modalities_in`/`modalities_out`, `open_weights` | custom passthrough keys (litellm's `/model/info` returns them unchanged) |
| `reasoning_in_response` / `reasoning_field` (the reasoning-replay surface, from models.dev `interleaved` + provider `shape`) | custom passthrough keys `reasoning_in_response` (bool) / `reasoning_field` (`reasoning_content` \| `reasoning_details`), asserted per the D11 matrix; Rule 1 provenance applies |
| `source` / `synced_at` / `staleness` | custom keys `capability_source` / `capability_synced_at` / `capability_staleness` (full provenance) |

**Rule 1 (conservative-unknown, load-bearing; amended 2026-08-18).** LiteLLM merges its *own* bundled cost-map defaults into `model_info` for models it recognises - trusting those would re-introduce the exact "silent optimistic default" failure the spec exists to eliminate. So the client-side **reader trusts a record's capability fields only when the record carries our `capability_source` provenance tag**; a record without the tag, or a field absent from a tagged record, is `unknown` - treated as `false` for capability gating (spec §5), with the gap surfaced. `unknown` is never encoded as a value; it is the **absence of an authored field**.

*Amendment (2026-08-18, operator):* an unknown model - on `/v1/models` with no models.dev entry - is by definition **low-tier and never used**. Filling capabilities for it is therefore NOT required, so we **do not attempt to suppress litellm's cost-map enrichment** of unknown records. That enrichment is external, bears no `capability_source` tag, and the reader never trusts it (this paragraph is the load-bearing part). litellm may add untrusted default keys to an unknown record at `/model/info` (observed on `opencode-go/hy3-preview`, 2026-08-18); the sync still pushes only the three provenance keys for such records, and the c8 assertion checks the provenance subset, not a byte-exact provenance-only record.

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
2. **DeepSeek (the zen family) and OpenAI cache automatically server-side** - zero client/gateway work; byte-identical prefix suffices; hits priced via `cache_read_input_token_cost` (mapped in D5; key corrected 2026-10-06, #330 iteration 2).
3. **Auto-inject is the one gateway-side primitive** worth configuring: the gateway itself marks the stable system-prompt prefix with `cache_control` annotations, no client code change. It covers Anthropic-native models if they ever enter the provider set; for the current openai-compatible provider set it is a no-op (automatic).

The response cache (`LITELLM_CACHE_TYPE=redis|in-memory`) stays out - it is the identical-request cache, and litellm's own proxy docs warn against it for multi-turn agentic traffic. A stateful agent loop's requests mutate each turn; the cacheable surface is the **prefix**, not the whole request, and the prefix is already handled by provider-native caching.

**D8 amended 2026-10-10 - fact 1 also binds the CLIENT, and that is the half the gateway cannot supply.**
"The KV cache lives only at the provider" makes the hit rate a pure function of the request prefix, so a client that re-sends a growing prefix defeats everything this decision configures.
That is exactly what the analysis proposers did: the role prompt rode a `SystemMessage` re-added to every turn's message list, so each call appended a copy at a shifting position and `mechanism_typist` grew quadratically in the call number (measured in `converged-agent-turn-adr.md`).
The gateway side of D8 is unchanged and remains correct; the client now holds its side of the contract by binding the prompt through `create_agent(system_prompt=...)` instead of the trail (`analysis/proposer_turn.py`), so the leading block is byte-identical from call 1.
Reusable rule and the rejected alternative (collapsing the chain) are in `statefulness-pattern-matrix.md` OUTLIER-5.

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
5. **Passthrough verification belongs to T1 (#104).** The pinned litellm (1.96.0) must forward `reasoning_content`/`reasoning_details` unchanged in responses and accept replayed reasoning in subsequent request messages (openai-compatible). Verified at the **unit tier** (in-process proxy against a mocked upstream, or static litellm-transform tests - no live gateway; docker is down). **T1 is reopened for this single FR-area delta** (it was verifier-APPROVED on the original criteria). **AMENDED 2026-08-11 (ratified finding):** in-process verification against the real 1.96.0 proxy showed `reasoning_content` passes through at message level (first-class `Message.reasoning_content`) and BOTH fields replay verbatim in requests, but `reasoning_details` in a response is relocated by litellm into `message.provider_specific_fields.reasoning_details` (convert_dict_to_response.py:666-668 vs `Message.model_fields`; the value survives byte-identical, the openai SDK injects `refusal: null`). **The operator ratified `provider_specific_fields` as the passthrough surface** for non-schema fields, conditional on the client-side reader parsing both forms correctly (proved by unit test `test_client_side_parses_both_reasoning_surfaces`). T6's replay pipeline reads `reasoning_content` at message level and `reasoning_details` via `provider_specific_fields`; a future litellm bump that promotes `reasoning_details` to a schema field turns the correction test red on purpose (re-read this amendment). **AMENDED 2026-10-08 (#281):** because litellm is a gateway-only dependency (D10), the T1 test module `tests/test_gateway_reasoning_passthrough.py` guards its `litellm.proxy.proxy_server` import with `pytest.importorskip(..., exc_type=ImportError)` so a plain dev-venv full-suite run SKIPS the module cleanly instead of ERRORing at collection when the `litellm[proxy]` extra (`apscheduler` et al.) is absent; the module still runs in full under the dedicated gateway venv. This is a test-harness robustness fix, not a change to the passthrough surface or the pinned version.

**Rationale.** The caveat is real for the stateful thinking roles (triager, job_orchestrator, the analysis proposers, the hunting roles): their sessions re-pay reasoning cost per turn unless the reasoning is replayed into the byte-identical prefix. The registry gives us the field location but not the caching behavior; the system therefore asserts only what is assertable (in-response + field), tracks hits empirically at runtime, and carries the checker design as a grill element instead of guessing.

## D12 - Provider request primitives: bind at construction, forward per model group (opencode-go `x-opencode-session`)

opencode-go began enforcing a client-supplied `x-opencode-session` header on 2026-09-05 (a stable per-conversation id for routing/optimisation; upstream issue `BerriAI/litellm#39503`). The system satisfies it at three layers, each at its own native seam:

1. **Client, at construction.** `build_chat_model` (`app/llm/providers.py`, the single construction point for every role in every module) resolves a per-provider request-primitive table and binds the result through the native `ChatOpenAI.default_headers` field, which langchain-openai threads into the openai SDK client's httpx headers (`client_params["default_headers"]`, verified in the pinned langchain-openai). `_opencode_go_request_headers` emits `x-opencode-session` (the ambient conversation id) plus `x-opencode-client: polymerhus` (provenance only). An unlisted provider binds nothing and its construction is byte-identical; adding a primitive is a one-line table entry (the `_ID_KIND_BY_PROVIDER` precedent).
2. **Conversation identity, at the session seam.** The id is the session's `thread_id` (the one collision-free instance identity, `session_address.py`). `run_session_turn`/`arun_session_turn` bind it for the turn's duration through the `conversation_scope` context manager (`app/llm/conversation.py`), so every client the turn builds - including a middleware-built summariser - reads the right conversation; the scope always restores, so no binding leaks between turns. A caller with no conversation (one-shot roles) falls back to a process-stable uuid: stability is the upstream's hard requirement, and a per-process value keeps affinity as close as is honestly possible without forging a conversation.
3. **Gateway, per model group.** In gateway mode the client's `x-*` headers reach opencode-go only because `litellm_settings.model_group_settings.forward_client_headers_to_llm_api` lists `opencode-go/*` (`gateway/litellm_config.yaml`). Verified in the pinned litellm 1.96.0 source: the flag runs `_get_forwardable_headers`, which forwards `x-*` minus `x-stainless*` and never `authorization` - the deployment key remains the upstream auth surface, so forwarding cannot clobber it. The global `general_settings` boolean was rejected (it would leak the client's x- headers to every provider; the per-group path exists in 1.96.0). The config is boot-time only (ADR D1: the proxy never hot-reloads), so a change needs a container restart, and the sync's management-API model writes never touch `litellm_settings`.

**Rationale.** The requirement is a request primitive, not a role concern: binding it at the single construction point keeps it automatic for every agent in both modes without touching an agent module (D4). `default_headers` was chosen over per-request `extra_headers` (not exposed by LangChain's invoke surface) and over a custom httpx client (heavier; owns pooling/timeouts). A gateway-only static `extra_headers` value was rejected: it would collapse every conversation into one id and does nothing in direct mode.

**Amendment (2026-10-07, #299) - the conversation primitive rotates per transient retry.** The opencode-go lane intermittently returns a bare 400 for a short window; a retry that re-fires with the same `x-opencode-session` never abandons a pinned bad upstream replica, so the actor and one-shot retry seams append `#r<attempt>` to the conversation id per attempt (`transient.rotate_conversation`, the `conversation_id` override on the session turn). The checkpointer's `thread_id` does not rotate, so agent memory is never forked; the primitive this D12 binds is the only thing that changes. The full classification/backoff/fallback decision is `docs/design/llm-transient-upstream-400-adr.md`.

## D13 - Gateway cost guard: a USD virtual-key budget from the models.dev costs (#330)

A persistent provider `429 GoUsageLimitError` (opencode-go's workspace quota) cascaded through the eval (`docs/design/eval-bugs-map.md` §0/§8) because nothing enforced the provider's dollar ceiling before the provider did. The guard is LiteLLM's native **virtual-key USD budget**, provisioned at bootstrap from the sync's existing models.dev per-token costs (`sync_mapping.py` - no new pricing dependency).

**What is provisioned.** `sync.run_sync` builds one `BudgetPlan` (`gateway_budget_plan`) and `GatewayClient.ensure_virtual_key` attaches it to each provider's app-minted virtual key (D3, amended #335):

```
budget_limits = [
  {"budget_duration": "7d",  "max_budget": cap_7d  * k},
  {"budget_duration": "30d", "max_budget": cap_30d * k},
]
rpm_limit = <optional; unset means none>
```

The caps default to opencode-go's real dollar-denominated quota (`$30`/7d weekly - the dominant, first-binding boundary - and `$60`/30d monthly; `LLM_GATEWAY_BUDGET_*_USD` overrides). There is NO 5h provider cap, so no 5h window is provisioned (the original `$12`/5h window was a mis-assumption and would have bound spuriously; retired 2026-10-09, #330 / EV-34). `k` is the **conservatism factor** (`LLM_GATEWAY_BUDGET_CONSERVATISM_FACTOR`, default `1.0`, validated `0 < k <= 1`; `k > 1` would budget above the provider cap and defeat the guard, so it is a hard config error). A malformed override is a `SyncConfigError` -> exit 1 (cold stop), the same fail-fast discipline as the providers.py env overrides. The plan is applied to every minted provider key (the ticket's literal scope; the current eval configures only opencode-go). **Forward step (recorded):** if a heterogeneous provider set ever appears, key the caps by provider in a table (the `_ID_KIND_BY_PROVIDER` pattern) so opencode-go's cap is never silently applied to a provider without that cap.

**Convergence (C9).** LiteLLM initialises a server-side `reset_at` on every `budget_limits` window at write time (verified live on 1.96.0), so the diff compares a canonical `(budget_duration, max_budget)` set and IGNORES `reset_at`/any merged key. An absent or stale key -> `POST /key/generate`; a changed scope/window/rpm -> `POST /key/update`; an equal surface -> no request. A key minted before this change (no budget) is upgraded once, then the re-run is fully idle.

**Enforcement.** `gateway/litellm_config.yaml` sets `general_settings.fail_closed_budget_enforcement: true` (verified present in 1.96.0: `general_settings.get(...) is True`): when the spend backing a budget decision cannot be verified against the DB (reservation/counter unreadable), litellm returns **503** rather than admitting on an unverifiable budget. A budget-EXCEEDED request returns **429** (`litellm.BudgetExceededError.status_code = 429`, `type=budget_exceeded`) at auth, BEFORE the provider is called (verified live: a zero-USD window on a virtual key 429s a chat request with no provider round-trip). Both 429 and 503 are classified as `ProviderUnavailableError` by the #329 classifier, so the existing provider-failure handling (backoff, interrupt-not-fail) covers the gateway throttle; that wiring is #331, not here.

**Grilled grey points (resolved, with evidence).**

1. **Peak/off-peak factor (HIGH) - SUPERSEDED 2026-10-09 (#330 / EV-34).** This grey point assumed models.dev carries an OFF-PEAK price and opencode-go charges 2x at peak (01:00-04:00 and 06:00-10:00 UTC Mon-Fri), so `k = 0.5` scaled every cap to trip at half the ceiling. The premise is false: models.dev's `opencode-go/deepseek-v4.1-flash` record IS the provider's effective rate, and there is no separate off-peak/peak factor. See the 2026-10-09 amendment below.
2. **Unpriced models fail open (HIGH).** `block_requests_for_models_without_pricing` does **NOT** exist in the pinned litellm 1.96.0 (no symbol in the installed tree). `reserve_budget_for_request` returns `None` when `estimate_request_max_cost` is `None`, and litellm records no spend for such a request, so the USD guard is BLIND to an unpriced model (LiteLLM #35524). Payloads mitigation chosen over a sync-side reject: unknown models must stay registered for routing (D5/D9), so the sync cannot drop them. The **pricing-gap policy** is: (a) the sync logs a loud `pricing-gap` warning at bootstrap naming every registered model with no authored price, so an unpriced eval/hunting role model cannot silently escape the guard; (b) the operator keeps the eval role models models.dev-priced (or pins them). This is documented, observable, and does not corrupt the D9 unknown-model path.
3. **Rolling provider windows vs scheduled resets (MEDIUM).** Verified in 1.96.0 (`duration_parser.get_next_standardized_reset_time`): `budget_limits` windows reset on a CALENDAR/hour boundary (a `5h` window aligns to 00/05/10/15/20 UTC), NOT a rolling window from first use; the provider's windows are rolling. A boundary burst is therefore possible (the provider's rolling window may hold near-cap spend while a freshly reset litellm window sees 0), bounded to at most one window's overshoot. Accepted and documented rather than fixed: a rolling `CustomLogger` is materially more complex, and the per-window enforcement (plus an optional conservatism margin `k < 1`) keeps the blast radius bounded (the design assessment reached the same verdict). Revisit only if a boundary burst is observed.
4. **Budget-exceeded is 429/503 (MEDIUM).** Confirmed above; handled by the companion provider-failure ticket (#329 classifier; #331 stop/flush/resume). The guard prevents most provider 429s; a gateway 429 remains possible at the boundary and is exactly what the provider-failure handling exists to absorb.

**Enforcement substrate.** Budget reads use litellm's cross-pod spend counter (Redis first, then in-memory, then a DB reseed; per-window counters always re-check the authoritative spend-log floor). The single co-located proxy + shared postgres needs no Redis: the in-memory counter serves a single pod and `fail_closed_budget_enforcement` rejects (503) only when both the counter and the DB are unreadable - it never admits on an unverifiable value.

**Amendment (2026-10-06, #330 iteration 2) - provider-specific effective cost override, and a D5 cache-key correction. [SUPERSEDED 2026-10-09 by the iteration-3 amendment below.]**
Iteration 1 priced the guard from the raw models.dev record.
Live verification showed that record is wrong for the eval's role model: the gateway authored `opencode-go/deepseek-v4.1-flash` at `input_cost_per_token=1.5e-07`, `output_cost_per_token=6e-07`, `cache_read` absent, while opencode-go's effective off-peak rate is ~6x lower (`2.5e-08` / `1.0e-07` / `3e-09`).
LiteLLM counts spend from the authored deployment `model_info`, so the guard under-counted by ~6x and tripped late (or never).
The fix is a **provider:model cost-override table** (`sync_mapping.PROVIDER_COST_OVERRIDES`), consulted at the authoring seam on EVERY sync and applied LAST in `capability_to_model_info`, so the override always wins over the models.dev record.
The seeded entry is opencode-go's **off-peak** rate, the default because ~90% of eval wall-time is off-peak.
An override is a `model_info` correction on the provider's deployment (the D5 table), never the global litellm cost map - litellm models a provider offering as a deployment (`model_list -> litellm_params`), and only the deployment's `model_info` is re-authored by the sync.
The override is marked with `cost_source: provider-override` so the pricing provenance is auditable; the capability provenance stays models.dev-sourced (Rule 1 is untouched - the reader gates capability trust on `capability_source`, and cost is not a capability).

**D5 cache-key correction (found during this change).**
The D5 table mapped `cost_cache_read` / `cost_cache_write` to `input_cost_per_token_cache_read` / `input_cost_per_token_cache_write`.
The string `input_cost_per_token_cache_read` appears NOWHERE in the pinned litellm 1.96.0 wheel (verified by extracting the wheel and grepping the package).
The cost path reads `cache_read_input_token_cost` / `cache_creation_input_token_cost` (`litellm/litellm_core_utils/llm_cost_calc/utils.py::_get_token_base_cost`; the router registers a deployment's `model_info` into `litellm.model_cost`, which that function then reads).
The old keys were therefore INERT: litellm priced every cached input token at 0, so the guard under-counted cached input on top of the ~6x rate error.
The mapping now authors the canonical keys, so the override's `cache_read` (and every model's cache pricing) actually feeds the guard.
This is a D5 correction, not an override-only fix.

**Grey points (resolved, with evidence).**

1. **Peak/off-peak.** opencode-go charges 2x at peak (01:00-04:00 and 06:00-10:00 UTC Mon-Fri).
   The override authors the **off-peak** rate and the existing **conservatism factor** (`k = 0.5`) remains the peak handling.
   The two compose exactly: counted spend is `tokens * off_peak_rate`, the window is `0.5 * dollar_cap`, and the guard trips when counted spend reaches `0.5 * dollar_cap`, i.e. when the true worst-case (all-peak) spend reaches the dollar cap.
   Peak-price authoring was rejected: it would over-count off-peak spend by 2x and trip at half the real quota, wasting ~50% of the budget during the ~90% of wall-time that is off-peak.
2. **Tier fields.** The pinned litellm 1.96.0 **DOES** honor `input_cost_per_token_above_128k_tokens` / `output_cost_per_token_above_128k_tokens` (verified in the 1.96.0 source: `litellm/litellm_core_utils/llm_cost_calc/utils.py::_get_token_base_cost` + `_is_above_128k`; when `prompt_tokens > threshold` it applies the tiered input/output/cache rates to the WHOLE request, not marginally).
   models.dev **CAN** carry context tiers (`cost.tiers[].tier = {type: "context", size: N}`, observed on `deepinfra` and `perplexity-agent` records), but the sync's data layer does not map them and the `opencode-go/deepseek-v4.1-flash` record carries none.
   Decision: author **no** tier field - there is no tier data for the target, and authoring a guessed tier would corrupt the guard.
   A future tier mapping must match litellm's whole-request semantics, not a marginal rate.
3. **models.dev lifecycle.** The override is keyed by the registered name (`<provider>/<model_id>`), applied in the pure mapping, and re-authored on every sync, so it is idempotent and lands inside the authored `model_info` the convergence diff compares (a divergent record re-pushes once, then the re-run is idle - it never fights the diff).
   Because the key is the registered name and not the models.dev record, the override survives both a models.dev price change AND a dropped/renamed models.dev record (where the model degrades to the D9 unknown path, which now also applies the override).
   A configured override whose provider is configured but whose model is no longer on `/v1/models` cannot apply and is surfaced with a loud `cost-override gap` warning - it never disappears silently.

**Spec correction.** `docs/design/eval-provider-resilience.md` §1.1 claimed the models.dev costs for `opencode-go/deepseek-v4.1-flash` "match the off-peak prices exactly"; the iteration-2 override superseded that claim by asserting the models.dev record was ~6x above the effective off-peak rate. The 2026-10-09 amendment below reverses iteration 2: the models.dev record IS the effective rate.

**Amendment (2026-10-09, #330 iteration 3 / EV-34) - the override is the provider's real rate; the guard caps the real weekly quota.**
Iteration 2 seeded the override at an "off-peak" rate `~6x below` the models.dev record (`2.5e-08` / `1.0e-07` / `3e-09`) and relied on `k = 0.5` to compensate a presumed 2x peak.
Live forensics falsified the premise: the models.dev `opencode-go/deepseek-v4.1-flash` record (`input 0.15`, `output 0.60`, `cache_read 0.003` per 1M) IS the rate the provider bills - the window's tokens priced at that record total `$29.83`, matching the provider's `$30`/week cap to within 1% with no peak/off-peak blend. The "~6x off-peak" haircut under-counted the guard's USD ~`4.3x`, so the provider's weekly cap tripped before the guard did (the EV-34 outage).
The fix: (a) the override is set to the models.dev Go record (`1.5e-07` / `6.0e-07` / `3e-09`), so LiteLLM's spend count matches the provider's charge; (b) the fictional 5h window is retired; (c) `k` defaults to `1.0`, because there is no under-count left to compensate (it remains an env-tunable safety margin for the provider-rolling vs litellm-calendar window mismatch, grey point 3). The guard's effective windows are now the real caps: weekly `$30` (dominant) and monthly `$60`.
This supersedes grey point 1 of the iteration-2 amendment.

---

## Appendix: Spec corrections (land in the same change as the code)

The design spec `docs/design/dynamic-llm-gateway-design-spec.md` is corrected as follows:

- **§3.3 item 1 ("Fetch both sources on a schedule")** - the running cadence is bootstrap-only (D2); "schedule" is re-stated as "at container bootstrap".
- **§6 first bullet ("Sync cadence ... on the order of tens of minutes")** - superseded; the running cadence is "at every bootstrap" (D2).
- **§3.3 item 8 + §5 unknown surfacing** - clarified: unknown-model gap notification is log-only for now, with a recorded forward step to add `settings.recon` configuration checks (D9).
- **§4 Capability Record -> gateway-native mapping** - the mapping table is D5 (the only place product-specific field names live); Rule 1 (provenance-gated trust, absence = unknown) and Rule 2 (inheritance resolved before push) are added.
- **§3.3 item 4 (validate, reject implausible collapse)** - clarified: source failure = soft (skip push, keep DB, agent starts); collapse/zero = hard (cold stop, agent must not start); two distinct exit codes (D9).
- **§3.4 Gateway prompt caching** - clarified: auto-inject (`cache_control_injection_points`) + passthrough; the `LITELLM_CACHE_TYPE` response cache is explicitly out (D8).
