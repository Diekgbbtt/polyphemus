# LightRAG × Polyphemus — testing handbook

How to take the integration from a clean checkout to a live, monitored hunt
turn. Intended for a Polyphemus maintainer who has already run real tests and
wants to exercise the LightRAG integration.

**Branch:** `polyphemus-lightrag_union`

---

## 0. What you are testing

1. The **streaming generation path**: `DeepSeekClient.stream()` sends
   `stream: true` and yields SSE deltas (batch `complete()` still sends
   `stream: false`).
2. The **tool**: `query_lightrag` retrieves methodology from LightRAG and
   returns a validated `AnswerBundle` (fail-open on errors).
3. The **hunting wiring**: with `HUNTING_LIGHTRAG_TOOL=1` the author lane
   receives the tool, the D4 prompt instructs the model to use it, and the
   model's final spec is parsed robustly.
4. The **execution seam**: `HuntingHttpPod` turns the spec's payload vectors
   into bounded HTTP probes and returns a verdict envelope.

---

## 1. Prerequisites

- Docker (compose `lightrag` profile) and network access to
  `https://api.swissai.svc.cscs.ch/v1`.
- A `.env` with the standard platform vars
  (`NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `POSTGRES_DSN`, `KALI_MCP_URL`)
  and the SwissAI key (`LLM_BINDING_API_KEY` or your provider key).
- Python venv: `.venv` with the repo dependencies installed.

---

## 2. Setup

```bash
git switch polyphemus-lightrag_union
cp .env.example .env   # then fill keys locally (never commit .env)
```

For the live tiers, export the integration vars (values only, keys stay in the
environment):

```bash
export API_KEY_SWISSAI="$LLM_BINDING_API_KEY"
export LLM_MODEL_HUNTING_HUNTER=swissai:RCP-AIaaS/deepseek-ai/DeepSeek-V4-Flash-0731
export LLM_MODEL_HUNTING_ORCHESTRATOR=swissai:RCP-AIaaS/deepseek-ai/DeepSeek-V4-Flash-0731
export HUNTING_LIGHTRAG_TOOL=1
export LIGHTRAG_BASE_API_URL=http://127.0.0.1:9621
export QUERY_LLM_API_KEY="$LLM_BINDING_API_KEY"
export QUERY_LLM_BASE_URL=https://api.swissai.svc.cscs.ch/v1
export QUERY_LLM_MODEL=RCP-AIaaS/deepseek-ai/DeepSeek-V4-Flash-0731
export QUERY_LLM_MAX_TOKENS=16384
```

Start LightRAG and wait for healthy:

```bash
docker compose --profile lightrag up -d lightrag
docker inspect --format '{{.State.Health.Status}}' polymerhus-lightrag-1   # healthy
```

---

## 3. T0 — unit / hermetic suites (no services, no keys)

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

Expected: **232 passed, 1 xfailed**.

If you want only the integration-critical tests:

```bash
.venv/bin/python -m pytest \
  tests/lightrag/test_generation_stream.py \
  tests/lightrag/test_tool.py \
  tests/lightrag/test_tool_factory.py \
  tests/attack/test_hunting_actors.py \
  tests/attack/test_hunting_agent.py \
  tests/attack/test_hunting_pod.py \
  tests/attack/test_symptom_kb.py \
  -q -p no:cacheprovider
```

---

## 4. T1 — stream smoke (LightRAG + SwissAI)

```bash
.venv/bin/python examples/lightrag-tool/stream_demo.py
```

What you should see:

- incremental JSON text printed as SSE deltas (no long pause with empty
  output);
- a final line `accepted: True` (a validated `AnswerBundle`);
- total wall time in the ~20–40 s range.

`accepted: False` with a complete JSON means the answer failed validation
(rare; the tool degrades to the deterministic fallback). `accepted: False`
with **no deltas at all** would indicate the streaming path regressed
(check that `DeepSeekClient.stream()` still sends `stream: true`).

---

## 5. T2 — author-lane live smoke (the real wiring)

This exercises the production registry path: the model gets the real
`query_lightrag` tool, may call it, and must return a parseable D4 spec.

```bash
set -a; source .env; set +a
export API_KEY_SWISSAI="$LLM_BINDING_API_KEY"
export LLM_MODEL_HUNTING_HUNTER=swissai:RCP-AIaaS/deepseek-ai/DeepSeek-V4-Flash-0731
export LLM_MODEL_HUNTING_ORCHESTRATOR=swissai:RCP-AIaaS/deepseek-ai/DeepSeek-V4-Flash-0731
export HUNTING_LIGHTRAG_TOOL=1
export LIGHTRAG_BASE_API_URL=http://127.0.0.1:9621
export QUERY_LLM_API_KEY="$LLM_BINDING_API_KEY"
export QUERY_LLM_BASE_URL=https://api.swissai.svc.cscs.ch/v1
export QUERY_LLM_MODEL=RCP-AIaaS/deepseek-ai/DeepSeek-V4-Flash-0731
export QUERY_LLM_MAX_TOKENS=16384
export PYTHONPATH=src

.venv/bin/python - <<'PY'
import asyncio, json, time
from langgraph.checkpoint.memory import InMemorySaver
from polymerhus.attack.hunting.hunt_orchestrator import HuntConfig, HuntPromptTemplate
from polymerhus.attack.hunting.hunting_agent import compose_authoring_prompt
from polymerhus.attack.hunting.actors import HuntingActorRegistry

cfg = HuntConfig(
    hunt_id="t2-live",
    unit_id="Service:slug:account-api",
    fault_class="fault-x",
    prompt_template=HuntPromptTemplate(
        rationale="bounded comparison of GraphQL vs REST object-level authorization",
        extension_points=["object id tampering"],
        assumptions=["object identifiers are client supplied"],
        supposed_payload_vectors=["GET /api/users/{id}", "query { user(id: 124) }"],
        l0_evidence=["WSTG-APIT-02", "WSTG-APIT-99"],
    ),
    surface_context={"cards": [{"title": "Account API", "technology_stack": ["HTTP JSON API", "GraphQL"]}]},
    target_caveats=["authorization-boundary comparison only; no cross-tenant access"],
)
prompt = compose_authoring_prompt(
    cfg, {"kb": "WSTG-APIT-02 (object ID tampering); WSTG-APIT-99 (GraphQL)."},
    "http", kb_degraded=False,
    working_set="fresh hunt: no prior dispatch; begin at GROUND",
)

async def drive():
    registry = HuntingActorRegistry("t2-run", checkpointer=InMemorySaver(), observe=False)
    actor = registry.actor_for("hunt-1")
    print("actor_tools:", [type(t).__name__ for t in actor._tools], flush=True)
    t0 = time.time()
    out = await actor.author(prompt)
    print("elapsed_s: %.1f" % (time.time() - t0), flush=True)
    await registry.stop_all()
    trail = actor._task.result().turns[-1].messages
    print("message_kinds:", [type(m).__name__ for m in trail], flush=True)
    return out

out = asyncio.run(drive())
print("OUT_NONE:", out is None, flush=True)
print("AUTHOR_OUT:", json.dumps(out, ensure_ascii=False)[:1500] if out else None, flush=True)
PY
```

Pass criteria:

- `actor_tools: ['LightRagQueryTool']`;
- `message_kinds` contains a `ToolMessage` (the model called the tool);
- `OUT_NONE: False` and `AUTHOR_OUT` is a D4 spec (target_identity,
  verification_symptoms, testing_pattern, ...);
- elapsed ~50–70 s.

If the tool is absent (`actor_tools: []`), the flag is off or you built the
actor directly instead of via the registry. If `OUT_NONE: True`, the final
reply was not parseable JSON — check the trail (prose + fenced JSON is now
handled; unfenced prose is intentionally fail-open).

---

## 6. T3 — full hunt via the API (optional, needs the control plane)

Prerequisites: the control-plane runtime has landed, Postgres/Neo4j are up,
LightRAG is healthy, and the hunting env vars are exported for the agent
process.

```bash
curl -sS -X POST "http://127.0.0.1:PORT/projects/{project_id}/hunting" \
  -H 'Content-Type: application/json' \
  -d '{
    "candidates": [{
      "unit_id": "Service:slug:account-api",
      "fault_class": "fault-x",
      "deterministic_witness": "clause",
      "llm_witness": "witness",
      "verdict": "applies"
    }]
  }'
```

What to inspect:

- response `{hunting_run_id}`; then poll the run status (`complete`/`failed`);
- the hunt store trail under `data/hunts/` for `gate`, `dispatch`, `spec`,
  `evidence`, `back_edge` records;
- **pod behavior**: without a target URL the pod returns an INIT rejection
  (`technical-infeasibility` + `init_validation`) and the harness re-authors
  once — that is the designed fail-open, not a bug. To execute real probes,
  the pod needs the asset URL (inject `target_url` at wiring, or populate
  `target_identity.url` in the spec).

---

## 7. Monitoring

- LightRAG request log:

  ```bash
  docker logs polymerhus-lightrag-1 --tail 50
  ```

- Hunting module logs (the process running the agent) — watch for:
  - `skill_for: ... using fallback` (harmless skill loader messages);
  - `hunt ... degraded (...)` (fail-open paths);
  - `symptom-technique KB degraded` (KB seam failure).
- Timing expectations: tool turn ~20–40 s, full author turn ~50–70 s,
  deterministic pod probes fast (bounded, timeout 10 s each).

---

## 8. Troubleshooting

| Symptom | Likely cause | Action |
| --- | --- | --- |
| `actor_tools: []` | flag off, or actor built directly (not via registry) | export `HUNTING_LIGHTRAG_TOOL=1`; use `HuntingActorRegistry` |
| no deltas, `accepted: False` in seconds | streaming payload regressed (`stream: false`) | check `build_external_payload` / `DeepSeekClient.stream()` |
| `accepted: False` with full JSON | answer failed validation (rare) | retry; it is the designed fallback; consider raising `QUERY_LLM_MAX_TOKENS` |
| `502 Bad Gateway` from SwissAI | transient endpoint error | retry; the tool now fails open (no crash) |
| `OUT_NONE: True` | final reply not parseable (unfenced prose) | inspect trail; re-run; fenced JSON after prose is supported |
| tool never called by the model | prompt/model choice | the tool is available, not forced; D4 guidance steers it |
| hunting run records "hunting agent unavailable" | dispatch not wired | you are on an old commit; need `f00bab7`+ |
| `tests/attack/test_hunting_runtime.py` hangs | pre-existing flaky hang in this env (unrelated) | run the wiring test standalone; do not mask with timeouts |
| pod INIT rejection on every hunt | no target URL | inject `target_url` or populate `target_identity.url` |

---

## 9. Rollback / notes

- Disable the integration entirely: unset/`export HUNTING_LIGHTRAG_TOOL=0` —
  the author lane runs exactly as before (no tool bound, prompt unchanged).
- The batch pipeline (`run_query_pipeline`) is untouched: `complete()` still
  sends `stream: false`.
- Never commit secrets. Keys live in `.env` (gitignored) or the environment.
