# Recon Pipeline - Agentic Crawl (Steel) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the agentic browser-crawl recon capability - an LLM ReAct loop driving external **Steel.dev** MCP browser tools to render JS-heavy targets and harvest endpoints/JS-URLs into a manifest, parsed into Layer-0 assets. This is the `configurator_mode="agent"` job the pod model was designed to accommodate (the ReAct crawl loop replaces the deterministic configurator+execute+gate).

**Architecture:** External **steel.dev** cloud browser (operator decision, forward-decisions D3). The `steel_*` MCP tools are provided by a Steel MCP tool provider instantiated **in-process** - NOT reached over a remote MCP host. steel.dev is the authenticated cloud browser; the provider opens a steel.dev session and drives it with **Playwright connected over CDP** (`wss://connect.steel.dev?apiKey=<STEEL_API_KEY>&sessionId=<id>`), exactly as in Redamon's implementation. The only credential is the steel.dev API key (`STEEL_API_KEY`); **there is no `STEEL_MCP_URL`.** A ported **ReAct crawl loop** (from Redamon's `crawl_agentic.py`, in `redamon-agent:/app`) drives the `steel_*` tools (`steel_crawl_start/navigate/frontier/eval/click/crawl_finish/await_auth`) to produce a `{endpoints, js_urls}` manifest. A **steel manifest parser** (ported from `redamon-recon` `steel_helpers.merge_steel_into_by_base_url`) turns the manifest into `AssetDelta`s. A **crawl-pod variant** wires loop→parser→triager→curator; the `steel_crawl` JobSpec joins the phase DAG. Authenticated crawl uses `steel_await_auth` (human-in-the-loop viewer login). Unit tests mock the provider (inject `client_factory`/`tools`) - real steel.dev is a deploy-time concern (needs the API key + egress).

> **Correction (SP4, operator):** an earlier iteration wrongly modelled Steel as a remote MCP server reached over `STEEL_MCP_URL` (a `MultiServerMCPClient({"steel": {"url": ...}})`). That is wrong and has been removed. `STEEL_MCP_URL` does not exist. The provider is in-process (Playwright-proxy-to-steel.dev). **Provider seam:** Redamon's concrete in-process `steel_*` server is not vendored in any `redamon-*` image available here (it appears only as a consumer in `crawl_agentic.py`), so `steel_client._default_client_factory()` raises `SteelProviderUnavailable` until that server is ported; the public contract (`get_crawl_tools`/`CRAWL_TOOL_NAMES`/`SteelNotConfigured`/`steel_configured`) is stable and fully test-covered via injection.

**Tech Stack:** Python 3.11, LangGraph, langchain-openai, langchain-mcp-adapters (Steel MCP client), the Foundation pod/curator + orchestration (sub-plan 3), Redamon's `crawl_agentic.py` + `steel_crawl.md` skill + `steel_helpers.py` as port sources.

## Global Constraints

- External steel.dev per forward-decisions D3: do NOT build a self-hosted browser. The `steel_*` MCP tools are provided **in-process** and drive steel.dev's cloud browser over Playwright-CDP (`wss://connect.steel.dev?apiKey=<STEEL_API_KEY>&sessionId=<id>`). There is **no** remote MCP host / `STEEL_MCP_URL` - only the steel.dev API key `STEEL_API_KEY`.
- The agentic-crawl job is `configurator_mode="agent"`: the ReAct loop IS the configurator, from iteration 1 (no deterministic template fill). It replaces the pod's configurator+execute+gate; its output is a manifest, which flows through parser→triager→curator like any other job.
- Reuse sub-plan-1/2/3 primitives: `agent/recon/types.py`, `curator.curate`, `parsers` (register the steel parser), `pod` (variant), `jobs.JOBS`/`PHASES`, `job_agent`/`pipeline` (the crawl job runs through the same pipeline), `agent/app/llm` (add a `crawler` role).
- Manifest contract (do NOT change - `steel_helpers` and the ReAct loop both depend on it): `{"endpoints": [{"method","url","query":[...],"body":[...],"status"}], "js_urls": [str,...]}`.
- Steel parser emits §10.3-conformant deltas (`BaseURL{url}`, `Endpoint{path,method,baseurl}`, `Parameter{name,position,endpoint_path,baseurl}`) with byte-matched edge node_identity, reusing `agent/recon/parsers/_urls.py`. JS URLs → `Endpoint` deltas (source="steel-js"), mirroring jsluice.
- Fail-fast: if the agentic-crawl job is in a run's plan but `STEEL_MCP_URL`/`STEEL_API_KEY` are unset, the crawl pod exports `failed` with a clear error + an Observation noting reduced coverage (best-effort, §10.6) - it must NOT crash the pipeline.
- Tests run from repo root with `.venv/bin/pytest`; the Steel MCP client + LLM are mocked (canned manifest / fake tools). No live Steel/LLM in unit tests. New package dirs need `__init__.py`.

---

### Task 1: Steel MCP client + crawl config + crawler LLM role

**Files:** Create `agent/recon/crawl/__init__.py`, `agent/recon/crawl/steel_client.py`; Modify `agent/app/llm/providers.py` (add `"crawler"` to `ROLES`); Modify `agent/recon/config.py` (Steel + crawl bounds); Test `tests/recon/crawl/__init__.py`, `tests/recon/crawl/test_steel_client.py`.

**Interfaces - Produces:**
- `config.py`: `STEEL_MCP_URL = os.environ.get("STEEL_MCP_URL", "")`, `STEEL_API_KEY = os.environ.get("STEEL_API_KEY", "")`, `CRAWL_MAX_PAGES` (default 50), `CRAWL_MAX_DEPTH` (3), `CRAWL_MAX_ITERS` (30), `CRAWL_JOB_TIMEOUT_S` (480).
- `steel_client.py`: `CRAWL_TOOL_NAMES: frozenset` (the 7 steel_* tool names); `steel_configured() -> bool` (both env vars present); `async def get_crawl_tools(*, client_factory=None) -> list` (builds a `MultiServerMCPClient({"steel": {"url": STEEL_MCP_URL, "transport": "streamable_http", "headers": {"Authorization": f"Bearer {STEEL_API_KEY}"}}})`, returns the tools filtered to `CRAWL_TOOL_NAMES`; `client_factory` injectable for tests). Raise `SteelNotConfigured` if `not steel_configured()`.
- `providers.py`: `ROLES` gains `"crawler"`; `validate_llm_config` now also requires `LLM_MODEL_CRAWLER`'s provider key (so bootstrap fails fast if the crawler role is misconfigured).

- [ ] **Step 1:** Write `tests/recon/crawl/test_steel_client.py`: `steel_configured()` False when env unset, True when both set (monkeypatch); `get_crawl_tools` with an injected fake client_factory returns only the CRAWL_TOOL_NAMES tools; `get_crawl_tools` raises `SteelNotConfigured` when unconfigured; `"crawler" in providers.ROLES`.
- [ ] **Step 2:** Run `.venv/bin/pytest tests/recon/crawl/test_steel_client.py -v` → FAIL.
- [ ] **Step 3:** Implement config additions, `steel_client.py`, add `"crawler"` to ROLES.
- [ ] **Step 4:** Run → PASS; `.venv/bin/pytest tests/recon tests/test_llm_providers.py -v` green (the ROLES change - ensure existing llm tests set LLM_MODEL_CRAWLER or the validate test accounts for it; adjust the provider tests minimally).
- [ ] **Step 5:** `git commit -m "feat(recon): Steel MCP client + crawl config + crawler LLM role"`.

---

### Task 2: Steel manifest parser

**Files:** Create `agent/recon/parsers/steel_parser.py`; Modify `agent/recon/parsers/__init__.py`; fixture + `tests/recon/test_steel_parser.py`.

**Port source:** `redamon-recon:/app/recon/helpers/resource_enum/steel_helpers.py::merge_steel_into_by_base_url` + `classification.py` (`classify_endpoint`, `classify_parameter`, `infer_parameter_type`). Read via `docker run --rm --entrypoint sh redamon-recon:latest -c 'sed -n "90,210p" /app/recon/helpers/resource_enum/steel_helpers.py'`. Port the per-endpoint mapping; you may inline a minimal classification (category/type) or skip classification props (keep identity + core props).

**Target schema (§10.3):** manifest `endpoints[]` → `BaseURL{url}` + `Endpoint{path, method, baseurl}` (props `url, status_code, source="steel"`) with `HAS_ENDPOINT` edge dir "in" from BaseURL; each endpoint's `query`/`body` params → `Parameter{name, position("query"/"body"), endpoint_path, baseurl}` with `HAS_PARAMETER` edge dir "in" from Endpoint. `js_urls[]` → `Endpoint{path, method:"GET", baseurl}` (props `url, source="steel-js"`). Reuse `agent/recon/parsers/_urls.py` (`base_and_path`, and its param/edge helpers) so identities/edges match the fleet exactly.

**Interfaces - Produces:** `steel_parser.parse(stdout: str) -> list[AssetDelta]` where `stdout` is the manifest JSON (the crawl pod passes the manifest as a JSON string, so the parser signature matches the fleet). `PARSERS["steel_crawl"] = parse`. Guard non-dict/malformed JSON (isinstance), tolerate missing endpoints/js_urls keys.

- [ ] **Step 1:** Write `tests/recon/test_steel_parser.py` + `tests/recon/fixtures/steel_manifest.json` (a manifest: 2 endpoints - one with a query param + one POST with a body param - and 1 js_url). Assert: BaseURL+Endpoint deltas with HAS_ENDPOINT edges (node_identity byte-matching); query→Parameter position "query", body→Parameter position "body" with HAS_PARAMETER edges; js_url→Endpoint source "steel-js"; malformed manifest → `[]` no crash; `get_parser("steel_crawl")` resolves.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement `steel_parser.py` (reusing `_urls`), register. **Step 4:** Run → PASS (`.venv/bin/pytest tests/recon -v` green).
- [ ] **Step 5:** `git commit -m "feat(recon): steel manifest parser (endpoints/params/js -> AssetDeltas)"`.

---

### Task 3: Agentic crawl ReAct loop

**Files:** Create `agent/recon/crawl/crawl_agent.py`, `agent/recon/crawl/steel_crawl_skill.md`; Test `tests/recon/crawl/test_crawl_agent.py`.

**Port source:** `redamon-agent:/app/crawl_agentic.py` (`_run_agentic_crawl`, `CRAWL_TOOL_NAMES`, `precreate_auth_session`, the manifest-extraction helpers) and the skill prompt `redamon-agent:/app/skills/tooling/steel_crawl.md` (copy verbatim into `steel_crawl_skill.md`). Read via `docker run --rm --entrypoint sh redamon-agent:latest -c 'cat /app/crawl_agentic.py'` and `'cat /app/skills/tooling/steel_crawl.md'`.

**Interfaces - Produces:**
- `crawl_agent.py`: `async def run_crawl(target: str, *, scope: list[str], model_role: str = "crawler", tools=None, llm=None, max_pages=None, max_depth=None, max_iters=None, pre_created_crawl_id=None) -> dict` - the bounded ReAct loop; returns the manifest `{"endpoints":[...], "js_urls":[...]}`. Loads the skill prompt from `steel_crawl_skill.md`. `tools`/`llm` injectable for tests (default: `steel_client.get_crawl_tools()` + `chat_model_for("crawler").bind_tools(...)`). Bounded by `max_iters` and a soft deadline; on any error returns the last manifest (best-effort). Port Redamon's tool-call loop + `steel_crawl_finish` manifest capture.
- `_load_skill() -> str` reads the skill md next to the module.

- [ ] **Step 1:** Write `tests/recon/crawl/test_crawl_agent.py` (fully mocked): a fake `llm` that emits a scripted tool-call sequence (`steel_crawl_start` → `steel_navigate` → `steel_crawl_finish`) and fake `tools` whose `steel_crawl_finish` returns a canned manifest; assert `run_crawl` returns that manifest; assert the loop is bounded (a fake LLM that never calls finish stops at `max_iters` and returns the last/empty manifest, no infinite loop); assert `run_crawl` with `pre_created_crawl_id` set drives the await_auth path (calls `steel_await_auth` first, not `steel_crawl_start`).
- [ ] **Step 2:** Run → FAIL. **Step 3:** Port + implement `crawl_agent.py` + copy the skill md. **Step 4:** Run → PASS.
- [ ] **Step 5:** `git commit -m "feat(recon): agentic crawl ReAct loop (Steel MCP tools) + skill prompt"`.

---

### Task 4: Crawl-pod variant + steel_crawl job integration

**Files:** Create `agent/recon/crawl/crawl_pod.py`; Modify `agent/recon/jobs.py` (add the `steel_crawl` JobSpec + phase placement); Test `tests/recon/crawl/test_crawl_pod.py`, extend `tests/recon/test_jobs.py`.

**Interfaces - Produces:**
- `crawl_pod.py`: `build_crawl_pod(*, run_crawl_fn, parse_fn, triage_fn, curate_fn) -> CompiledGraph` - a LangGraph pod variant: node `crawl` (calls `run_crawl_fn(target, scope, ...)` → manifest; if Steel unconfigured or crawl errors → export `failed` + a "reduced coverage" Observation, best-effort) → node `parse` (`parse_fn(json.dumps(manifest))` via the steel parser) → node `triager` (LLM observations) → node `curator` (curate). The `target`/`scope` come from `input_asset` (a BaseURL) + settings. Injected fns for tests; `default_*` wire `crawl_agent.run_crawl` / `steel_parser.parse` / the pod's triager / `curate`. Provide a `crawl_pod_invoke(pod_input, job, run_id, phase) -> PodExport` so the per-job agent (`job_agent`) can fan crawl pods like any job.
- `jobs.py`: `JOBS["steel_crawl"]` = `JobSpec(tool="steel_crawl", skill="agentic_crawl", command_template="", produces=["BaseURL","Endpoint","Parameter"], consumes="BaseURL", use_auth=True, configurator_mode="agent")`. Place it in the resource-enum phase (consumes BaseURL from httpx). `tool="steel_crawl"` must byte-match `PARSERS["steel_crawl"]` (Task 2).
- The `job_agent`/`pipeline` dispatch: a job with `configurator_mode=="agent"` routes to `crawl_pod_invoke` instead of the default template pod. Wire this switch in `job_agent.default_pod_invoke` (dispatch on `job.configurator_mode`).

- [ ] **Step 1:** Write `tests/recon/crawl/test_crawl_pod.py` (mocked): inject `run_crawl_fn` returning a canned manifest, real `steel_parser.parse`, capturing `curate_fn`, fake triager → assert the crawl pod produces BaseURL/Endpoint/Parameter merges + `verdict="success"`; inject a `run_crawl_fn` raising / SteelNotConfigured → assert `verdict="failed"` + a reduced-coverage Observation, no crash. Extend `test_jobs.py`: `JOBS["steel_crawl"].tool in PARSERS`, `configurator_mode=="agent"`, phase placement consumes BaseURL.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement `crawl_pod.py`, the JobSpec, and the `configurator_mode=="agent"` dispatch in `job_agent`. **Step 4:** Run → PASS (`.venv/bin/pytest tests/recon -v` green).
- [ ] **Step 5:** `git commit -m "feat(recon): crawl-pod variant + steel_crawl job (configurator_mode=agent)"`.

---

### Task 5: Authenticated crawl (steel_await_auth) + settings/status wiring

**Files:** Modify `agent/recon/crawl/crawl_agent.py` (auth path already ported in T3 - here wire precreate + the viewer URL surfacing); Modify `agent/recon/crawl/crawl_pod.py` (thread auth from `extra.auth_context`); Modify `agent/app/routes.py` + `pg.py` (surface the crawl auth-session viewer URL in status); Test `tests/recon/crawl/test_crawl_auth.py`.

**Interfaces:**
- For a `use_auth` steel_crawl job with an `auth_context` that indicates manual login (or when the target requires auth), `crawl_pod` calls `precreate_auth_session` to get a `crawl_id` + viewer URL, records it (registry `recon_jobs.stats.viewer_url` or a run-level field), and drives `run_crawl(..., pre_created_crawl_id=crawl_id)` so the ReAct loop calls `steel_await_auth` first. The viewer URL appears in `GET /recon/{run_id}` so the operator can log in.
- If `auth_context` carries cookies (non-interactive), pass them to the Steel session instead (steel session with cookies) - or document that interactive `await_auth` is the MVP auth path and cookie-injection into Steel is deferred.

- [ ] **Step 1:** Write `tests/recon/crawl/test_crawl_auth.py`: a fake `precreate_auth_session` returns `(crawl_id, {viewer_url})`; assert the crawl pod threads `pre_created_crawl_id` into `run_crawl` and the viewer_url is recorded in the pod export/stats; a non-auth crawl skips precreate.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement the auth wiring + status surfacing. **Step 4:** Run → PASS.
- [ ] **Step 5:** `git commit -m "feat(recon): authenticated agentic crawl (steel_await_auth + viewer URL in status)"`.

---

### Task 6: Agentic-crawl e2e integration (mocked Steel)

**Files:** Test `tests/recon/crawl/test_crawl_e2e.py`.

**Goal:** Drive the `steel_crawl` job through the REAL crawl pod + REAL steel parser + REAL curator (capturing merge_fn) + REAL job_agent/pipeline dispatch, faking ONLY the Steel MCP tools (a fake toolset whose `steel_crawl_finish` returns a canned manifest) and the LLM (scripted tool-calls + empty triager). Assert: the crawl job dispatches to the crawl pod (via `configurator_mode=="agent"`), the manifest's endpoints/params/js reach the curator as BaseURL/Endpoint/Parameter merges, and the pipeline records the job `success`. Also assert the Steel-unconfigured path degrades gracefully (job `degraded`, run still `complete`).

- [ ] **Step 1:** Write the e2e test wiring the real stack with a mocked Steel toolset + LLM. **Step 2:** Run → FAIL (until integration). **Step 3:** Fix any dispatch/seam glue surfaced. **Step 4:** Run → PASS; full `.venv/bin/pytest tests/recon -v` green.
- [ ] **Step 5:** `git commit -m "test(recon): agentic-crawl e2e (mocked Steel MCP, real crawl-pod->parser->curator)"`.

---

## Self-Review (author checklist, completed)

- **Coverage:** Steel client+config+role (D3) → T1; manifest parser → T2; ReAct loop + skill → T3; crawl-pod variant + configurator_mode=agent dispatch + job DAG placement → T4; authenticated crawl (steel_await_auth + viewer URL) → T5; e2e net → T6. The `configurator_mode=="agent"` seam (built as a field in sub-plan 1, deterministic-only until now) is finally consumed here.
- **Placeholder scan:** each task names exact port sources (crawl_agentic.py, steel_helpers.py, steel_crawl.md) + target schemas + test assertions; no "TBD".
- **Type consistency:** steel parser uses the fleet `AssetDelta`/`_urls` contracts + `PARSERS["steel_crawl"]`; `JobSpec.tool=="steel_crawl"` == parser key; `run_crawl(...)->manifest dict`, `crawl_pod_invoke(...)->PodExport`, dispatched by `job_agent` on `configurator_mode`. Best-effort/degraded semantics match §10.6.
- **Deferred (tracked):** non-interactive cookie-injection into the Steel session (T5 documents interactive await_auth as the MVP auth path); Steel session lifecycle/cost governance.
