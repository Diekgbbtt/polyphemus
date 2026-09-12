# HTTP Proxy History - Operations (#196)

Design: `docs/superpowers/specs/2026-09-12-http-proxy-history-196-design.md`.
The Kali container is no longer a blind terminal: every intercepted HTTP/1.1 and
HTTP/2 flow (including interceptable HTTPS) becomes an immutable
`http-artifact/v1` record that can be searched, fetched and replayed by
identifier within its project.

## Topology

```
MCP execute_command ──lease netns/veth──► subprocess (source 172.30.0.x)
                                            │ transparent REDIRECT :80/:443
                                            ▼
                       mitmdump (addon_entry.py) in the ROOT namespace
                                            │ resolves source_ip → registry
                                            ▼
              /data/<project_id>/http-history/{history.sqlite3, bodies/*.blob}
```

The proxy's own upstream connections stay in the root namespace and are never
redirected, so there is no routing loop. Flows that cannot be correlated land in
the reserved `unscoped` project, which project-scoped queries refuse to read.

## Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `KALI_HTTP_HISTORY_ROOT` | `/data` | Store root (mounted `http-history` volume) |
| `KALI_HTTP_CAPTURE_ENABLED` | `true` | Off switch for diagnostic operation |
| `KALI_HTTP_MAX_BODY_BYTES` | `5242880` | Per-body capture cap; oversize bodies are *omitted* (never silently truncated) |
| `KALI_HTTP_NAMESPACE_POOL` | `8` | Concurrent capture sessions |
| `KALI_HTTP_LEASE_TTL_S` | `900` | Lease TTL for background processes |
| `KALI_HTTP_ACQUIRE_TIMEOUT_S` | `30` | Backpressure wait before `PoolExhaustedError` |
| `KALI_HTTP_PROXY_HOST` / `KALI_HTTP_PROXY_PORT` | `127.0.0.1` / `8080` | mitmdump listener |
| `KALI_HTTP_REGISTRY_PATH` | `/run/kali-http/registry.sqlite3` | Shared source-ip registry |
| `KALI_HTTP_RETENTION_S` | `0` | Age-based retention (0 = keep) |
| `KALI_HTTP_PROJECT_MAX_BYTES` | `0` | Per-project byte cap (0 = unlimited) |

## MCP surface

- `execute_command(command, session_id, timeout_s, project_id, run_id, spec_id,
  variant_ref)` - backward compatible; adds `exec_id`, `http_artifact_refs`,
  `capture_warning`.
- `search_http_history(project_id, filters, cursor, limit, text)` - conjunctive
  `{side, namespace, key, op, value}` filters (`op` in `eq|contains|prefix|gte|lte`),
  `limit` 1..200, deterministic `(created_at, artifact_id)` cursor.
- `get_http_artifact(project_id, artifact_id, include_body=False)` - sanitized
  record; `include_body=True` is refused here.
- `replay_http_request(project_id, artifact_id, overrides, capture_context)` -
  closed override set (`method`, `url`/`path`, `query`, `header(s)`, `cookie(s)`,
  `body`/`form`/`json`); produces a new artifact with `derived_from` and
  `replay_kind`.
- `proxy_status()` - `mcp`, `proxy`, `routing`, `namespaces`, `store`, `capture`.

## Failure semantics

- Command execution is **fail-open**: a lease, proxy or store failure returns
  the command result plus `capture_warning`.
- Lookup and replay are **fail-closed**: a missing/cross-project baseline is
  `not_found`; a hunter `request_ref` that cannot be resolved becomes
  `technical-infeasibility`, never an INIT rejection.
- Schema-version mismatch surfaces an explicit error; there is no automatic
  destructive rebuild.

## Security

Raw secrets (authorization/cookie/query/form values, bodies) stay in the store
for legitimate replay. Model-facing views redact secret-bearing values and never
return body content. Langfuse/D6 receive artifact ids plus method/host/status
class/size/timing only - never wire content.

## Known limitations

- HTTP/3 (QUIC) is explicitly excluded (UDP/443 from leased namespaces is
  rejected) and reported as a limitation, never counted as captured.
- WebSocket message history and generic TCP are out of scope.
- Certificate-pinned clients remain observable only as failed/incomplete flows.
- Retention/project-byte caps are configured but the purge job is not yet
  scheduled (see the store's `status()` counts for the current footprint).

## Verification

```bash
.venv/bin/pytest tests/kali tests/attack/pod \
  tests/integration/test_test_executor_pod_contracts.py -q
.venv/bin/pytest tests/test_compose_config.py tests/app/test_kali_mcp_check.py -q
docker compose config
docker compose build kali && docker compose up -d kali
.venv/bin/pytest tests/e2e/test_http_proxy_history.py -v
```
