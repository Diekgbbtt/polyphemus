# Assertions - #100 LLM API Gateway programme (T1-T6): gateway wiring + models sync pipeline + T3-T6 surfaces

**Source:** tickets #104 (T1), #105 (T2), #106 (T3), #107 (T4), #108 (T5), #109 (T6); ADR `docs/design/llm-gateway-100-decisions.md` (D1-D11); spec `docs/design/dynamic-llm-gateway-design-spec.md`.
**Seams under assertion:** deployment config (compose/Dockerfile/YAML/requirements); the container entrypoint (`gateway_entrypoint.py`, D10 ordering + D9 exit-code branch); the litellm management surface (`/health/liveliness`, `/model/info`, `/model/new|update|delete`); the sync CLI (`python -m polymerhus.app.llm.sync`, exit 0/1/2); the gateway's dedicated postgres database (`polymerhus_gateway` on the shared instance; `LiteLLM_ProxyModelTable`, STORE_MODEL_IN_DB); the capability reader (`resolve_capability`); `build_chat_model` (LLM_GATEWAY_URL seam); the crawl gate (`_refuse_crawl_without_tool_calling`); the reasoning-replay seam (`session.py` + `ReasoningPreservingChatOpenAI`).
**Live edges:** opencode zen gateway (`https://opencode.ai/zen/v1`, `API_KEY_OPENCODE` from `.env`) - provider model existence + live completions; `https://models.dev/catalog.json` - the capability/cost/context registry. Both run live; nothing inside them is substituted.
**Oracle discipline:** expected sets and field values are derived from the two raw sources (catalog.json + /v1/models) by the spec's own join rules (D5/D9), never from the sync's output - the test recomputes the spec, not the code.

## Contract predicates (integration tier)

### FR-1 - Gateway wired in the platform configuration

- **C1** | seam: docker-compose agent service + Dockerfile vs the D10 env contract | delivery: success shape
  input: the parsed `docker-compose.yml` agent service and `Dockerfile` text
  observable: agent env contains `DATABASE_URL` (same postgres instance as `POSTGRES_DSN`, dedicated `polymerhus_gateway` database - litellm's schema machinery owns its target database) and `LITELLM_MASTER_KEY: sk-polymerhus-dev-gateway`; `Dockerfile` sets `CONFIG_FILE_PATH=/srv/gateway/litellm_config.yaml` and `CMD ["python", "-m", "polymerhus.app.gateway_entrypoint"]`; the `agent` service `ports` publishes 8080 and NOT 4000
  yields: integration test (static config parse)

- **C2** | seam: `gateway/litellm_config.yaml` vs D1/D8/D10 | delivery: success shape + secrets-absent
  input: the YAML as shipped
  observable: `model_list: []`; `general_settings.store_model_in_db: true`; NO `cache:` stanza and NO `LITELLM_CACHE_TYPE`; `litellm_settings.enable_anthropic_prompt_caching: true`; no `master_key` / `database_url` key anywhere (env-only)
  yields: integration test (static YAML parse)

- **C3** | seam: `requirements-gateway.txt` vs D10 pinning | delivery: success shape
  input: the pinned lines
  observable: `litellm[proxy]==1.96.0`, `fastapi==0.140.6`, `httpx==0.28.1` exactly (a bump is a one-file review)
  yields: integration test (static parse)

- **C4** | seam: dev overlay vs D1 independent reload policies | delivery: success shape
  input: `docker-compose.dev.yml`
  observable: `agent` gains `./gateway:/srv/gateway` bind-mount and `AGENT_UVICORN_ARGS: "--reload --reload-dir /srv/src"`; the proxy command (`_proxy_command`) never contains `--reload`
  yields: integration test (static parse + entrypoint seam)

- **C5** | seam: litellm proxy management surface, container-internal | delivery: success shape
  input: `GET /health/liveliness` against `127.0.0.1:4000` inside the agent container
  observable: HTTP 200 within the entrypoint's bounded window (300 attempts x 1 s; the
    prisma client import alone costs 40-55 s - see gateway_entrypoint.py)
  yields: integration test (docker exec curl)

- **C6** | seam: `GET /model/info` (auth LITELLM_MASTER_KEY) | delivery: success shape + empty-valid
  input: one authed GET inside the agent container
  observable: HTTP 200; body `{"data": [{"model_name": str, "litellm_params": dict, "model_info": dict}, ...]}`; after a sync, `__sync_snapshot__` is among the `model_name`s
  yields: integration test

- **C7** | seam: sync CLI exit-code contract vs the entrypoint's branch (D9) | delivery: degradation
  input: (a) `LITELLM_MASTER_KEY` unset, (b) `LLM_SYNC_GATEWAY_URL` pointing at a dead port (127.0.0.1:1)
  observable: (a) exit 1 (hard, "cannot authenticate"), (b) exit 1 (hard, management-API failure); neither run touches the registered set (diff zero afterwards)
  yields: integration test (in-container CLI runs)

- **C8** | seam: sync desired-set vs the raw-source oracle (D2/D5/D9) | delivery: success shape + unknown-model
  input: live `catalog.json` + live `/v1/models` for every provider with an `API_KEY_*` in the stack env
  observable: the registered `model_name` set EQUALS the oracle join (exact string equality, both directions); every record's `model_info` carries `capability_source`, `capability_synced_at`, `capability_staleness`; every capability field present in the record equals the oracle value (per-token cost = per-million / 1e6 rounded 12dp); a model on `/v1/models` with no registry entry is registered with ONLY the three provenance keys (staleness `unknown`)
  yields: integration test (live sync run + oracle recompute)

- **C9** | seam: diffable push idempotency (D9) | delivery: duplicate-idempotent
  input: run the sync twice back-to-back
  observable: the second run pushes ZERO add/update/delete (registered set byte-identical, `__sync_snapshot__` record unchanged: same `desired_count`, same `desired_hash`)
  yields: integration test
  note: updates go through the DB-backed `PATCH /model/{model_id}/update` with
  `model_info.id` echoing the row's `model_id`. The old `POST /model/update`
  rewrites ONLY `litellm_params` (capabilities could never converge) and its
  pydantic schema fabricates a random uuid for a missing `model_info.id`,
  which always 400s "model not found"; the PATCH body MUST carry the real id
  or the handler merges a fresh random uuid into the stored `model_info`,
  corrupting the row identity (all verified against litellm 1.96.0, 2026-08-17).

- **C10** | seam: D11 reasoning surface (D5/D11 matrix) | delivery: success shape + conservative-absent
  input: the oracle record for the opencode `deepseek-v4-flash-free` (models.dev `interleaved` present)
  observable: its `model_info` carries `reasoning_in_response` and `reasoning_field` with values equal to the matrix's verdict for that record; a record whose catalog shape is `"completions"` or with no `interleaved` carries NEITHER key
  yields: integration test (live registered record vs oracle matrix)

- **C11** | seam: STORE_MODEL_IN_DB persistence (D1) | delivery: success shape
  input: a SQL query against the gateway's dedicated postgres database (DATABASE_URL)
  observable: `LiteLLM_ProxyModelTable` (litellm's own table) contains exactly `count(/model/info data)` rows, each with the same `model_name`
  yields: integration test (psycopg query)

- **C12** | seam: capability reader vs live /model/info (D5 Rule 1, D6) | delivery: success + degradation + empty-valid
  input: `resolve_capability(provider, model)` inside the stack with `LLM_GATEWAY_URL` set, for (a) the synced triager model, (b) a model with no registered record
  observable: (a) `context_limit` == oracle value, `output_limit` == oracle or None, `supports_tool_calling` == oracle or None, `source` == `models.dev/...`, `reasoning_*` per Rule 1; (b) all capability fields None, `context_limit` falls to env override or 150_000; two calls return the SAME cached profile object (resolve-and-hold); an untagged record (no `capability_source`) yields all-None profile (Rule 1 trusts nothing)
  yields: integration test

- **C13** | seam: `build_chat_model` env selection (D4 item 1) | delivery: ordering (mode selection)
  input: `LLM_GATEWAY_URL` unset vs set to `http://127.0.0.1:4000`
  observable: unset -> `openai_api_base == PROVIDERS[provider]` and the zen id strip runs client-side (`deepseek/deepseek-v4-flash-free` -> `deepseek-v4-flash-free`); set -> `openai_api_base == "http://127.0.0.1:4000"` verbatim and the model string is sent verbatim (no strip); `max_retries=0` holds in both modes
  yields: integration test

- **C14** | seam: crawl gate vs live reader (D4 item 4, D5 Rule 1) | delivery: success + degradation
  input: `_refuse_crawl_without_tool_calling(body)` for role `crawler`, live stack
  observable: `supports_tool_calling` true -> returns None; false/None -> returns the refusal string `"opencode:deepseek-v4-flash-free"`; reader raising -> refusal (never crash); identity unresolvable -> None (proceed)
  yields: integration test

- **C15** | seam: provider API-key rotation propagation (#193, D9 snapshot) | delivery: rotation-convergent
  input: after a synced gateway, rotate ONE provider's `API_KEY_*` in env and run the sync again
  observable: that provider's registered records are re-pushed via the update path (`PATCH /model/{model_id}/update`) with the CURRENT key in `litellm_params.api_key` (litellm re-encrypts and persists it - `/model/info` masks the key, so it can never be diffed from the registered side); every other provider is untouched; the `__sync_snapshot__` record's `api_key_hashes` (per-provider fingerprint of the applied key) reflects the rotation; a third run with the unchanged key pushes ZERO add/update/delete
  yields: integration test `test_provider_key_rotation_updates_that_providers_models_with_new_key`
  note: a snapshot that predates `api_key_hashes` records no applied key, so the sync re-establishes the baseline once (every key-bearing model refreshed) and then converges - this is what repairs an already-stale DB after an upgrade.

## Walkthrough predicates (e2e tier)

- **E1** | grounds: D10 ordering + #104 acceptance ("container boots two ASGI processes ... agent starts only after the proxy is healthy and the sync has run")
  entry seam: `docker compose up -d --build agent` (fresh build of the current tree)
  input: the composed stack with the operator `.env`
  live edge: none (self-contained boot; the sync's sources are the live edges declared above)
  path: entrypoint starts the litellm CLI (127.0.0.1:4000) -> bounded poll on `/health/liveliness` answers 200 -> `python -m polymerhus.app.llm.sync` runs (exit 0) -> uvicorn agent starts on 0.0.0.0:8080 -> the container holds both processes
  terminal: `GET /health/liveliness` 200 inside the container; `GET /model/info` non-empty (the sync populated it); agent answers on 8080 from the host; the container log lines appear in the order proxy-health -> sync -> agent (no agent line precedes the sync line)
  observed: `docker compose ps`, `docker compose logs agent` (ordering), in-container curl of both surfaces, host curl of 8080
  yields: e2e test `test_boot_orders_proxy_then_sync_then_agent`

- **E2** | grounds: D1 forward constraint + #104 ("SIGTERM/SIGINT propagate to both children; the proxy drains, the agent exits; no orphaned process")
  entry seam: `docker compose stop agent` (SIGTERM to the entrypoint)
  input: the running stack from E1
  live edge: none
  path: SIGTERM -> `_on_signal` propagates to BOTH children -> both exit within 10 s -> entrypoint exits 128+SIGTERM
  terminal: the agent container reaches `Exited (143)`; no litellm or uvicorn process remains alive on the host for ports 4000/8080 (checked 5 s after stop)
  observed: `docker compose ps`, `docker inspect` exit code, host `pgrep -f` for the two ASGI processes
  yields: e2e test `test_sigterm_tears_down_both_asgi_processes`

- **E3** | grounds: D9 cold stop + #104 ("hard (collapse) -> halt, agent must not start")
  entry seam: entrypoint run in a throwaway container with `LITELLM_MASTER_KEY` unset
  input: `docker compose run --rm -e LITELLM_MASTER_KEY= agent python -m polymerhus.app.gateway_entrypoint` (bounded to 120 s)
  live edge: none
  path: proxy starts -> healthy -> sync runs -> sync returns 1 (hard: no master key, D9) -> entrypoint logs "halting before the agent starts" and returns 1 WITHOUT starting uvicorn
  terminal: exit code 1; port 8080 never listens (checked inside the throwaway container during the run); the proxy was torn down with it (no orphan after exit)
  observed: container exit code, in-container listener check, entrypoint log line
  yields: e2e test `test_hard_sync_collapse_cold_stops_before_agent`

- **E4** | grounds: D4 item 1 + #107 ("routes its LLM calls through the litellm proxy instead of directly to the provider, with no other client-semantics change")
  entry seam: `build_chat_model("opencode", model)` + one live completion, inside the agent container with `LLM_GATEWAY_URL=http://127.0.0.1:4000`
  input: model `deepseek/deepseek-v4-flash-free`, a one-line prompt, temperature 0
  live edge: opencode zen gateway (real completion through the gateway's upstream routing)
  path: client (base_url = gateway, model string verbatim `opencode:deepseek/deepseek-v4-flash-free`) -> gateway registered-name resolution (THE integration truth of the D5 registered-name convention) -> opencode zen upstream -> response returns
  terminal: HTTP 200; non-empty completion content; the gateway's own log records the routed model_name
  observed: the completion result, `docker compose logs agent` (gateway line naming the model)
  yields: e2e test `test_live_completion_routes_through_gateway`

- **E5** | grounds: D5 Rule 1 + D6/D7 + #106 ("reader resolves per (provider, model) ... resolve-and-hold ... off the retry axis")
  entry seam: `resolve_capability("opencode", "deepseek/deepseek-v4-flash-free")` inside the agent container with `LLM_GATEWAY_URL` set
  input: the triager's configured model
  live edge: none (the reader hits only the co-located gateway)
  path: reader GET /model/info (one synchronous read) -> record found, tagged -> typed profile -> held in `_PROFILE_CACHE`
  terminal: `context_limit` == oracle int; `output_limit` == oracle or None; `source` == `models.dev/opencode/deepseek-v4-flash-free`; `reasoning_in_response`/`reasoning_field` per the D11 matrix; call 2 returns the identical cached object (identity, not equality)
  observed: the returned profile object + `is` identity across calls
  yields: e2e test `test_reader_resolves_and_holds_live_profile`

- **E6** | grounds: D4 item 4 + #108 ("warns the operator, REFUSES to execute the tool-loop, and degrades gracefully")
  entry seam: `_refuse_crawl_without_tool_calling(AgenticCrawlRequest(model="crawler", ...))` inside the agent container
  input: `model="crawler"` (the role whose client the crawl seam uses), live stack
  live edge: none (reader against the co-located gateway)
  path: gate resolves the role's (provider, model) -> reader -> branch on `supports_tool_calling`
  terminal: returns None when the oracle says the model supports tool calling; returns the refusal `"opencode:deepseek-v4-flash-free"` (with the warn log line naming model/capability state/gap) when it does not; either way no exception
  observed: the gate's return value + `docker compose logs agent` warn line when refused
  yields: e2e test `test_crawl_gate_live_refusal_or_pass`

- **E7** | grounds: D11 items 3-4 + #109 ("parses the reasoning ... replays it into the next turn's message history (byte-identical prefix) ... tracks cache hits via usage.cached_tokens ... records reasoning readability via a dedicated langfuse llm-response log field")
  entry seam: the stateful session turn path (`stateful_turn` / the session seam) for the triager role, through the gateway, two turns
  input: a prompt turn 1, a continuation turn 2, model `deepseek/deepseek-v4-flash-free` (reasoning-capable per the synced profile)
  live edge: opencode zen gateway (a real response carrying reasoning)
  path: turn 1 -> `ReasoningPreservingChatOpenAI._create_chat_result` captures the wire reasoning -> `extract_reasoning` parses per the profile -> `_replay_reasoning` re-persists the assistant message with the reasoning attached (byte-identical) -> turn 2 restores the replay-ready prefix (the re-emitted message carries the reasoning surface) -> cache hits tracked from `usage.cached_tokens`
  terminal: turn 1's response carried reasoning (parsed, non-empty); the re-persisted history message carries the reasoning byte-identical to what the wire delivered; turn 2's request payload re-emits it (asserted at the seam the gateway verified: message-level `reasoning_content` / `reasoning_details`); `usage.cached_tokens` recorded (0 or more - observability, never gated); langfuse metadata carries `reasoning_readability` (`replayed` | `absent`) on the turn's llm-response
  observed: the two turn results, the re-persisted checkpoint state read back, the logged replay observability line, the langfuse llm-response metadata
  yields: e2e test `test_reasoning_replay_round_trip_through_gateway`

## Bootstrap needs (operator-supplied)

1. Docker daemon + internet on this host (confirmed: docker 29.6.2) - the stack must come up and the two live edges must be reachable from the stack.
2. `API_KEY_OPENCODE` live key (present in `.env`) - the sync's /v1/models existence fetch and E4/E7's live completions spend real calls.
3. Gateway state reset: wipe ONLY litellm's own tables in the gateway's dedicated postgres database (`LiteLLM_ProxyModelTable`, `LiteLLM_VerificationToken`, `LiteLLM_SpendLogs`, etc.) before the first boot so the bootstrap sync starts from the empty state D10 describes - the shared volumes (neo4j/pg) hold other workflows' state and are NOT touched.
4. E7 runs two real reasoning turns through the live gateway (cost + time) - confirm the deep walkthrough is in scope now.
