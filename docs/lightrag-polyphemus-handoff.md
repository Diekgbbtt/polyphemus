# Polyphemus ↔ LightRAG integration — hand-off

**Branch:** `polyphemus-lightrag_union` (based on `lightrag`, HEAD `f00bab7`)
**Date:** 2026-08-19
**Audience:** a Polyphemus maintainer who has run real end-to-end tests and
wants to exercise the LightRAG methodology-KB integration for the first time.

---

## 1. Purpose

This hand-off describes, at the level needed to operate and test it, the
integration between the **LightRAG methodology knowledge base** and the
**Polyphemus hunting module**. The integration makes the hunting agent's author
lane (D4 spec authoring) able to ground its methodology in the indexed WSTG
corpus via a `query_lightrag` LangChain tool, backed by an SSE-streamed DeepSeek
generation path, and to execute the resulting spec through a real HTTP probing
pod.

Everything described here is committed on this branch. No live service is
required to run the unit suites; the live smoke requires LightRAG (local) and
the SwissAI DeepSeek endpoint.

---

## 2. End-to-end flow

```
Hunting run (POST /projects/{id}/hunting)
  └─ start_hunting → arun_orchestration (graph engine)
       └─ per candidate: gate (hunting_orchestrator actor) → dispatch
            └─ build_actor_hunting_agent (production default dispatch)
                 ├─ KB grounding: build_fault_kb_lookup (fault-KB materialisation)
                 ├─ D4 authoring prompt (with query_lightrag guidance when flag on)
                 └─ HuntingHunterActor.author (per-hunt session agent, tools bound)
                      └─ model may call query_lightrag
                           ├─ LightRAGHttpClient → POST /query/data (local KB)
                           ├─ context → reference registry → generation prompt
                           └─ DeepSeekClient.stream (SSE deltas, stream=true)
                                └─ validated AnswerBundle (accepted True/False, fail-open)
                      └─ final spec JSON parsed (tolerates prose + ```json fence)
                 └─ HuntingHttpPod(spec) → deterministic HTTP probes → verdict
                      └─ D5 judge / re-authoring / back-edge (existing canon)
```

The two generation surfaces that matter:

- `DeepSeekClient.complete()` — batch, non-streaming (used by
  `run_query_pipeline`); payload sends `stream: false`.
- `DeepSeekClient.stream()` — SSE streaming (used by the tool); payload sends
  `stream: true`. The two are intentionally separate: switching the shared
  payload to streaming would break `complete()`.

---

## 3. Repository state

### 3.1 Commits (in order, on `lightrag` / this branch)

| Commit | Message |
| --- | --- |
| `04f9dc9` | feat(lightrag): stream DeepSeek completion deltas over SSE |
| `2c61c8f` | feat(lightrag): add query_lightrag LangChain tool with streamed answer |
| `4459a88` | feat(lightrag): build_lightrag_tool factory and stream demo |
| `347e6ff` | feat(hunting): thread optional author tools through the hunter actor lane |
| `bac8a66` | feat(hunting): opt-in LightRAG query tool via HUNTING_LIGHTRAG_TOOL |
| `076f5ed` | fix(lightrag): send stream=true in DeepSeekClient.stream() |
| `9817aea` | fix(hunting): unblock actor suites and wire query_lightrag author guidance |
| `5d295ba` | fix(lightrag): fail open when the query tool's retrieval or LLM fails |
| `9d3ac94` | fix(hunting): parse fenced JSON replies after prose |
| `c006550` | feat(lightrag): raise query generation max tokens for verbose hunter answers |
| `f00bab7` | feat(hunting): wire real KB lookup, HTTP probing pod, and production dispatch defaults |

### 3.2 Key files

| File | Role |
| --- | --- |
| `src/polymerhus/app/config.py` | `HUNTING_LIGHTRAG_TOOL` flag; `QUERY_LLM_*` config (max tokens default now **16384**) |
| `src/polymerhus/lightrag/generation.py` | `DeepSeekClient.complete/stream`; `build_external_payload(stream=...)`; `max_tokens` default 16384 |
| `src/polymerhus/lightrag/tool.py` | `LightRagQueryTool` (LangChain tool) + `build_lightrag_tool()`; **fail-open** on retrieval/LLM errors; docstring explains why it does not call `run_query_pipeline` |
| `src/polymerhus/lightrag/pipeline.py` | batch path (`run_query_pipeline`) — unchanged |
| `src/polymerhus/attack/hunting/actors.py` | `HuntingActorRegistry` default resolves the flag → `_lightrag_author_tools()`; `_TurnActor` threads `tools` to `run_session_agent` only when non-empty |
| `src/polymerhus/attack/hunting/hunting_agent.py` | D4 prompt with optional `query_lightrag` guidance; typed `SymptomTechniqueQuery(fault_id, technological_axis)`; harness converts the typed result to the prompt dict |
| `src/polymerhus/attack/hunting/llm.py` | `build_actor_hunting_agent` (production dispatch seam); `_parse_json_object` tolerant of prose + fenced JSON |
| `src/polymerhus/attack/hunting/symptom_kb.py` | `build_fault_kb_lookup` (real fault-KB materialisation) and `build_gate_kb_retriever` (orchestrator gate evidence) |
| `src/polymerhus/attack/hunting/hunting_pod.py` | `HuntingHttpPod` — deterministic HTTP probing executor (new) |
| `src/polymerhus/attack/hunting/runtime.py` | `build_production_hunting_agent`; `start_hunting` now wires the production default dispatch + gate KB + registry reap |
| `.env.example` | documents the hunting roles, the flag, and `QUERY_LLM_MAX_TOKENS=16384` |

### 3.3 Working tree notes

The branch carries two unrelated pre-existing changes that must be preserved
and are **not** part of this work:

- deleted `data/lightrag/benchmarks/wstg_test_cases.json` and
  `data/lightrag/benchmarks/wstg_writeup_generation_benchmark_live.json`;
- untracked `docs/superpowers/plans/2026-08-18-lightrag-streaming-tool.md` and
  `examples/lightrag-query-simulation/live-run/`.

---

## 4. Configuration surface

### 4.1 Environment variables

| Variable | Value / default | Notes |
| --- | --- | --- |
| `HUNTING_LIGHTRAG_TOOL` | `1` to enable the tool in the author lane; default off | read by `config.py` and by the D4 prompt guidance |
| `QUERY_LLM_BASE_URL` | `https://api.swissai.svc.cscs.ch/v1` | SwissAI endpoint |
| `QUERY_LLM_API_KEY` | secret | the SwissAI/DeepSeek key; in the live tests exported from `LLM_BINDING_API_KEY` |
| `QUERY_LLM_MODEL` | `RCP-AIaaS/deepseek-ai/DeepSeek-V4-Flash-0731` | |
| `QUERY_LLM_MAX_TOKENS` | `16384` (was 4096) | raised so long verbose AnswerBundles are not truncated into `schema_error` |
| `QUERY_LLM_TIMEOUT_SECONDS` | `120` | DeepSeek request timeout |
| `LIGHTRAG_BASE_API_URL` | `http://lightrag:9621` (compose) / `http://127.0.0.1:9621` (host) | falls back to `LIGHTRAG_API_URL` |
| `LIGHTRAG_API_KEY` | optional | sent as `X-API-Key` when set |
| `LIGHTRAG_TIMEOUT_SECONDS` | `30` | LightRAG client request timeout |
| `LLM_MODEL_HUNTING_HUNTER` | `swissai:RCP-AIaaS/deepseek-ai/DeepSeek-V4-Flash-0731` | **required** to run a real hunt (hunting module bootstrap validates it) |
| `LLM_MODEL_HUNTING_ORCHESTRATOR` | `swissai:RCP-AIaaS/deepseek-ai/DeepSeek-V4-Flash-0731` | **required** to run a real hunt |
| `API_KEY_SWISSAI` | secret | required by `build_chat_model` for the `swissai` provider (`API_KEY_<PROVIDER>` convention) |
| standard platform vars | `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `POSTGRES_DSN`, `KALI_MCP_URL` | required by `config.py` at import |

> `.env` is gitignored: secrets (keys) belong there or in the runtime
> environment, never in versioned files. `.env.example` carries only
> placeholders.

### 4.2 Services

- LightRAG runs under the compose `lightrag` profile:

  ```bash
  docker compose --profile lightrag up -d lightrag
  ```

  Healthcheck: `http://127.0.0.1:9621/health` (or `http://lightrag:9621`
  inside the compose network). The KB is the mounted
  `./data/lightrag/rag_storage` corpus.
- The SwissAI DeepSeek endpoint must be reachable from the environment running
  the tool (the hunting agent container in production).

---

## 5. Component details

### 5.1 DeepSeek generation (`generation.py`)

- `build_external_payload(..., stream: bool = False)` sets `"stream": stream`
  in the request body.
- `DeepSeekClient.complete()` calls it without `stream` → `stream: false`
  (batch JSON response).
- `DeepSeekClient.stream()` calls it with `stream=True` and parses SSE `data:`
  lines into `{"type": "delta", "text": ...}` + `{"type": "finish", ...}`.
- `max_tokens` defaults to **16384** (config-driven via
  `QUERY_LLM_MAX_TOKENS`).

### 5.2 `query_lightrag` tool (`tool.py`)

- `build_lightrag_tool()` constructs `LightRAGHttpClient` + `DeepSeekClient`
  from app config, lazily (no I/O at import).
- `stream(spec)`:
  1. `client.query_data(...)` (LightRAG `/query/data`);
  2. `_build_prompt` (context → reference registry → generation prompt);
  3. yields `llm.stream(prompt)` deltas;
  4. validates the collected text into an `AnswerBundleV1`
     (`accepted` True/False);
  5. yields the final `{"type": "answer", "answer": ..., "accepted": ...}`.
- **Fail-open**: any retrieval or LLM exception is caught and replaced by the
  deterministic fallback bundle with `accepted: False` (never raises through
  the agent loop) — this honours the D4 guidance "if the tool fails, continue
  with the available grounding".
- `_run`/`_arun` return the answer JSON (used by the agent's tool loop).
- **Why it does not reuse `run_query_pipeline`**: the pipeline is a batch seam
  (`llm.complete`, aggregated `QueryPipelineResultV1`); the tool must yield
  incremental SSE events. Documented in the module docstring.

### 5.3 Hunting actor lane (`actors.py`)

- `_TurnActor` accepts `tools: Sequence = ()` and forwards them to
  `run_session_agent` **only when non-empty** (default empty ⇒ identical
  behavior to before).
- `HuntingHunterActor(author_tools=...)` forwards to the base.
- `HuntingActorRegistry` default: `list(author_tools) if author_tools else
  _lightrag_author_tools()` → with `HUNTING_LIGHTRAG_TOOL=1` the per-hunt actor
  gets `[LightRagQueryTool]`; with the flag off it gets `[]`.
- Test fakes in the actor suites are **async-native** (`_agenerate`): a
  sync-only `BaseChatModel` + `ainvoke` deadlocks langgraph when an agent
  thread resumes from a checkpoint (second turn). Production models
  (ChatOpenAI) are async-native; the fakes now mirror that.

### 5.4 D4 authoring prompt (`hunting_agent.py`)

- `compose_authoring_prompt(..., lightrag_tool_enabled=False)`: when enabled, a
  `query_lightrag` usage block is inserted before "Your working set" (when to
  use it, which `QuerySpecV1` fields to derive from the HuntConfig, that the
  AnswerBundle is methodology/provenance, not vulnerability confirmation, and
  that a tool failure degrades to the available grounding).
- Disabled ⇒ byte-identical prompt.
- The call site derives the flag lazily from `config.HUNTING_LIGHTRAG_TOOL`
  (fail-open to disabled when config is unavailable).

### 5.5 Free-text D4/D5 parsing (`llm.py`)

- `_parse_json_object` now extracts a ` ```json ` fenced block **anywhere** in
  the reply (live models often open with prose before the fence), while
  keeping unfenced prose+JSON unparseable (fail-open, no guessing).

### 5.6 Real KB grounding (`symptom_kb.py`)

- `build_fault_kb_lookup()` → typed `SymptomTechniqueLookup` backed by the
  packaged fault-KB materialisation (`fault_kb.load_materialisation`):
  symptoms from the entry description, probing techniques from related attack
  patterns + alternate terms, `source="fault-kb"`; unknown fault ⇒ empty
  result (fail-open).
- `build_gate_kb_retriever()` → orchestrator gate evidence dict
  (`symptoms`/`probing_techniques`/`source`).
- The harness now constructs the **typed** query
  (`SymptomTechniqueQuery(fault_id=..., technological_axis=(...))`). This fixes
  a latent bug where the seam always raised `TypeError` and the KB was always
  degraded.

### 5.7 Hunting pod (`hunting_pod.py`)

- `HuntingHttpPod(target_url=None, transport=None, timeout=10.0,
  max_requests=16)` implements `pod(spec)` and returns the D5+D6 envelope
  `{verdict, evidence: {terminal_reason, clean, iterations, interpretations,
  init_validation?}}`.
- Deterministic execution: payload vectors are parsed into `METHOD path`;
  `{id}` placeholders probe baseline id `1` and tampered id `124`; GET/HEAD
  only; http/https only; no redirects; bounded requests.
- Verdict mapping: tampered allowed + baseline denied ⇒ `symptom-confirmed`
  (clean); all denied ⇒ `no-symptom-evidence` (clean); connection errors ⇒
  `no-symptom-evidence` (not clean ⇒ insufficient-evidence); no target URL /
  unsupported vectors ⇒ `technical-infeasibility` + `init_validation`
  (re-authoring path), never a guessed host.
- A `transport` can be injected (hermetic tests with `httpx.MockTransport`).

### 5.8 Production wiring (`runtime.py`)

- `build_production_hunting_agent(store, run_id, target_url=None, ...)`
  composes the actor-backed harness with the real KB lookup and the real pod.
- `start_hunting` now, when `dispatch_fn` is not injected, builds this default
  dispatch and the gate `kb_retrieve_fn`, and reaps the hunting registry in
  teardown. Previously the production API path recorded
  "hunting agent unavailable".

---

## 6. What is verified

### 6.1 Unit / hermetic suites (no live services)

```bash
.venv/bin/python -m pytest \
  tests/attack/test_hunting_actors.py \
  tests/attack/test_hunting_agent.py \
  tests/attack/test_hunting_llm.py \
  tests/attack/test_hunting_pod.py \
  tests/attack/test_symptom_kb.py \
  tests/recon/test_orchestrator_actor.py \
  tests/lightrag \
  -q -p no:cacheprovider
```

Result at hand-off time: **232 passed, 1 xfailed**.

Highlights pinned by tests:

- author tools reach `run_session_agent` only when non-empty;
- `HUNTING_LIGHTRAG_TOOL` flag wires the real tool through the registry;
- hermetic tool-calling loop: outer model calls `query_lightrag`, a
  `ToolMessage` is produced, the actor's final reply uses the tool output;
- D4 prompt: disabled ⇒ no mention of `query_lightrag`; enabled ⇒ instructions
  and `QuerySpecV1` fields present;
- tool fail-open: retrieval/LLM errors ⇒ deterministic fallback,
  `accepted: False`, never raises;
- fenced JSON after prose is parsed;
- pod: symptom confirmed / no symptom / insufficient evidence / INIT
  rejection, all without network;
- real fault-KB lookup returns materialised content; unknown fault ⇒ empty.

### 6.2 Live smoke (services + real DeepSeek)

Executed during development against LightRAG at `http://127.0.0.1:9621` and
SwissAI DeepSeek Flash:

- `examples/lightrag-tool/stream_demo.py`: SSE deltas printed, final
  `accepted: True` (observed ~28 s end-to-end). After raising max tokens to
  16384 the same flow consistently produced **validated** answers (10
  ontology explanations) instead of truncated `schema_error` fallbacks.
- Author-lane live run via the production registry
  (`HUNTING_LIGHTRAG_TOOL=1`, real model factory): the model called
  `query_lightrag`, the ToolMessage carried a validated AnswerBundle
  (`accepted: True`), and `author()` returned a full D4 spec
  (`OUT_NONE: False`) in ~50–60 s.
- One observed transient: SwissAI returned `502 Bad Gateway` once; the
  fail-open fix turned that into a degraded tool answer instead of a crashed
  turn.

---

## 7. Known issues and caveats

1. **`tests/attack/test_hunting_runtime.py` has a pre-existing, flaky hang**
   in this environment. Verified unrelated to this work: the hanging test does
   not import any modified module, and the hang persists with the changes
   reverted (it occasionally passes in ~0.3 s). The new wiring test
   `test_build_production_hunting_agent_wires_real_seams` passes standalone.
2. **`tests/integration/test_hunting_agent_contracts.py` hangs** in this
   environment (pre-existing; not part of the verified suites). Its KB-query
   assertions were aligned to the typed contract
   (`fault_id`/`technological_axis`).
3. **Answer validation is not guaranteed**: DeepSeek answers occasionally fail
   schema validation (long/format drift) and the tool returns the deterministic
   fallback with `accepted: False`. With `QUERY_LLM_MAX_TOKENS=16384` this is
   rare but possible; the agent is instructed to continue with available
   grounding.
4. **The pod needs a target URL**: from the injected `target_url` or the
   spec's `target_identity.url`. Without it the pod returns an INIT rejection
   (re-authoring) instead of probing anything. Recon/cards do not yet carry a
   guaranteed URL into the candidate; wire that when running against real
   assets.
5. **Environment variables required for a real hunt**: the hunting roles
   (`LLM_MODEL_HUNTING_HUNTER`/`ORCHESTRATOR`) and `API_KEY_SWISSAI` are not in
   `.env` by default; a real run needs them set (see §4.1). The live tests
   exported them at runtime without writing files.
6. **SwissAI endpoint flakiness**: a transient `502` was observed once; the
   tool now degrades gracefully, but retries at the caller level may still be
   wanted for very long runs.

---

## 8. Hand-off checklist for the maintainer

- [ ] Branch checked out: `polyphemus-lightrag_union`
- [ ] `.env` configured per §4.1 (keys only in `.env`/environment)
- [ ] LightRAG up and healthy (compose `lightrag` profile)
- [ ] Unit suites green (§6.1)
- [ ] Stream smoke green (§T1 of the handbook)
- [ ] Author-lane live smoke green (§T2 of the handbook)
- [ ] Optional: full hunt via the API (§T3) — requires control plane + PG +
  a candidate whose target URL reaches the pod
- [ ] Known issues §7 acknowledged before judging results
