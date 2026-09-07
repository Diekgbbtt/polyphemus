# Langfuse tracing (lightweight)

The recon agent ships optional, env-driven Langfuse tracing.
It is deliberately minimal: tracing only, no prompt management, no datasets, no evals.

## What it captures

When enabled, each recon run produces a trace tree that mirrors the LangGraph structure:

- **Plan overview** - the phase DAG / job fan-out.
  Each job graph (`preprocess -> pod fan-out`) is a top-level trace; the pod subgraphs (`configurator -> execute -> parser -> triager -> curator`, or the crawl variant) nest underneath.
- **Tool calls + responses** - the Kali MCP `execute_command` calls in pods (command, stdout/stderr, returncode) are captured as tool spans.
- **Agent reasoning dumps** - every role LLM's inputs and outputs (configurator, triager, job_orchestrator, crawler), captured because the Langfuse callback handler is attached at model construction.

The `steel_*` crawl tools run inside a vendored ReAct loop; the crawler LLM's reasoning (which records each tool-call decision) is traced, but the individual Steel tool-execution spans are not wired in this lightweight pass.

### Per-stage spans in the LightRAG query pipeline (#207)

The `query_lightrag` / `kb_query` tool's inner stages (retrieval, generation,
validation) are instrumented with **per-stage OpenTelemetry spans**
(`lightrag/observability.py`). They ride the SAME OTLP span processor the
Langfuse SDK registers (the retrying, truncating exporter wired below), so
they nest under the active trace and appear in Langfuse as first-class
observations:

- **`retrieval`** - input = the query, mode, top_k; metadata = status, the
  retrieved chunk ids (and best-effort scores), and the persisted
  `ReferenceRegistryV1` mapping (index -> reference_id -> file_path) so a
  cited provenance index is resolvable post-hoc (the registry is otherwise an
  in-memory value that dies with the call).
- **`generation`** - input = the assembled prompt (registry + retrieved
  context); metadata = the collected raw output AND the generator's
  `reasoning_content` (the DeepSeek reasoning deltas, surfaced as `reasoning`
  events by `DeepSeekClient.stream` and recorded on the span).
- **`validation`** - metadata = accepted/degraded, validation errors, rejected
  citations, the resolved provenance references; numeric metrics =
  `metric.provenance_empty` (1.0 for an accepted-but-empty `PROV []` bundle)
  and `metric.entity_count` (the contract-drift counter - bundles routinely
  return 3-7 entities, the drift was previously unmeasured).
- **`kb_observation`** (hunter author lane only, #207 defect 1 point D) - the
  hunter has no D6 log, so each `kb_query` records the query, scenario id,
  returned entity names, and provenance references as span metadata.

All of it is **fail-open** (CODING_STANDARD section 12): a missing
`opentelemetry` package, an unavailable tracer, or a misconfigured Langfuse
client degrades every span to a silent no-op - observability never crashes or
perturbs the query pipeline.

## How to enable

Set all three environment variables (any one missing = tracing is a silent no-op; the agent never hard-fails on Langfuse):

```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
```

`LANGFUSE_HOST` selects the backend:

- **Langfuse Cloud (EU):** `https://cloud.langfuse.com`
- **Langfuse Cloud (US):** `https://us.cloud.langfuse.com`
- **Self-hosted:** the base URL your instance is reachable at, e.g. `http://langfuse:3000` (from inside the compose network) or `http://localhost:3000` (from the host).

Get the keys from your Langfuse project under Settings -> API Keys.
The keys live in `.env` (not committed); `.env.example` documents them as commented placeholders.

The `langfuse` Python package (pinned `langfuse==4.13.0` in `agent/requirements-observability.txt`) is baked into the agent image at build time.
If it is somehow absent at runtime, tracing still degrades to a no-op rather than crashing.

## How to view traces

1. Open your Langfuse instance (the `LANGFUSE_HOST` URL) and select your project.
2. Go to **Tracing -> Traces**.
   Each recon job appears as a trace; open one to see the nested pod spans, the `execute_command` tool spans (with command + output), and the role-LLM generations (with prompt + completion).
3. Filter by time to find a specific run.

## Implementation

All the logic is confined to `agent/app/observability/langfuse_tracing.py`, which exposes:

```python
from agent.app.observability import get_langfuse_callbacks
```

`get_langfuse_callbacks() -> list` returns `[handler]` when configured, `[]` otherwise.
`[]` is inert as `config={"callbacks": []}`, so the runtime wires it unconditionally.
The handler is built once per process and cached.
