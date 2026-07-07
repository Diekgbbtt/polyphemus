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
