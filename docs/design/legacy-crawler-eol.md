# Legacy crawler end of life

Date: 2026-11-07.
Status: removed.
Branch: `feat/steel-crawl-agent-browser`.
Superseded by: the deterministic `steel_crawl` engine and the one `browser`
tool over the in-stack Steel pool.

## What was removed

The agentic crawl path and its six Steel tools:

- `src/polymerhus/recon/crawl/crawl_agent.py`
- `src/polymerhus/recon/crawl/crawl_agentic.py`
- `src/polymerhus/recon/crawl/steel_provider.py`
- `src/polymerhus/recon/crawl/steel_client.py`
- `src/polymerhus/recon/crawl/prompts/steel-crawl.md`
- the `crawler` role in `src/polymerhus/app/llm/providers.py`
- the `LLM_CRAWLER` deployment requirement
- the legacy tests and the `eval/steel-e2e-395` harness
- the two direct-runtime live guards: `tests/e2e/test_steel_interactive_local.py`
  (the CLI daemon against a directly addressed API) and
  `tests/e2e/test_steel_internal_reachability.py` (the Steel SDK plus Playwright
  against a directly created session). The pool MCP owns session creation and
  rewrites the CDP endpoint; a direct CLI/SDK session cannot reach a pool
  worker. `tests/e2e/test_browser_tool_live.py` is the replacement guard: the
  worker renders the target through the production tool, and an explicit
  persist restores the decoupled context.
- every comment, test, and document wire that named the six-tool path

The six tools were `steel_crawl_start`, `steel_navigate`, `steel_frontier`,
`steel_crawl_finish`, `steel_eval`, and `steel_click`.

## Why

1. The path duplicated the browser capability. The deterministic engine and
   the pool MCP address the same target with one executor.
2. The path addressed the retired public Steel API. The in-stack pool is the
   supported runtime.
3. The path coupled auth state to a Steel session. The decoupled auth-context
   object and its pool-store record replace that coupling.
4. The path carried its own budget and action caps. The production contract is
   a 600-second crawl budget with time as the only bound.
5. The six tools tripled the agent's browser surface. One `browser` tool with
   `start`, `exec`, and `end` is the only browser surface.

## Replacement

- The deterministic `steel_crawl` job runs `run_live_crawl` through the browser
  MCP.
- Every browser-capable agent binds the one `browser` tool.
- The auth store holds only `accounts.<account>.browser_context.ref`.
- The pool store holds the decoupled auth-context object.

## Compatibility

None. There is no fallback, no alias, and no compatibility read of the legacy
`steel.state` key or the six tools.
