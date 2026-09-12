# HTTP Proxy History #196 - Implementation Plan

Spec: `docs/superpowers/specs/2026-09-12-http-proxy-history-196-design.md`
(commit `5732671`). Branch: `feat/http-proxy-history-196`, worktree
`.worktrees/http-proxy-history-196`.

## Module layout

```
kali/
  __init__.py
  http_history/
    __init__.py
    ids.py         ULID (Crockford base32, stdlib only)
    models.py      http-artifact/v1 record + capture context
    sanitize.py    model-facing redaction
    store.py       SQLite WAL store, bodies, attribute index, FTS, search
    replay.py      closed-set deterministic overrides
    normalize.py   flow-like object -> artifact (mitmproxy-free)
    addon.py       mitmproxy addon: response/error hooks (import-guarded)
    registry.py    shared sqlite source_ip -> capture context
    namespaces.py  persistent netns/veth lease pool with backpressure
    config.py      env-driven limits/enablement
    service.py     search/get/replay/status over the store (MCP-facing)
    mcp_tools.py   FastMCP tool bodies (testable without a server)
  mcp_server.py    FastMCP surface: execute_command + 4 new tools
  entrypoint.sh    bootstrap + mitmdump + readiness + MCP + trap
  Dockerfile       derived from redamon-kali-sandbox:latest
  postrun.sh       idempotent CA/netns/veth/NAT/routing bootstrap
```

## TDD slices

1. ULID + canonical model + body store + immutable artifacts.
2. Attribute index, conjunctive search, pagination/cursor, project isolation,
   sanitization.
3. Flow normalization + mitmproxy addon (fake flows, no mitmproxy import).
4. Netns lease pool, concurrency serialization, source_ip registry.
5. MCP surface: execute_command extension + search/get/replay/status.
6. Agent integration: `ExecResult` + `RawObservation` refs, `CaptureContext`,
   `ExecTool` wiring, D6/Langfuse safe metadata.
7. Hunting: `ProbeStep.request_ref`/`overrides`, resolver, inline compatibility
   with #191 no-defaulting.
8. Deployment: compose service, Dockerfile, entrypoint, health.
9. E2E/regression; docs; full suite.

## Invariants

- Project id `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`; every read is project-scoped
  before filters.
- Bodies durable before the record that references them; records immutable.
- No silent truncation: every omission carries state/size/reason.
- Model-facing views are sanitized; raw bodies stay runtime-only.
- Capture/store failure is fail-open for `execute_command`; replay is
  fail-closed.
