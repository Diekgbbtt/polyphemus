# HTTP Proxy History - Operations (#196)

Design: `docs/superpowers/specs/2026-09-12-http-proxy-history-196-design.md`.
The Kali container is no longer a blind terminal: every intercepted HTTP/1.1 and
HTTP/2 flow (including interceptable HTTPS) becomes an immutable
`http-artifact/v1` record that can be searched, fetched and replayed by
identifier within its project.

## Topology

```
MCP execute_command ──lease netns/veth──► subprocess (source 172.30.0.x)
                    DNS 169.254.169.253 ──► dnsmasq ──► Kali/Docker resolver
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

The live end-to-end target is a separate, deterministic local service
(`http-e2e-target`, see `docker-compose.e2e.yml`). The gate addresses it by its
Docker service name: each leased namespace queries the root-namespace dnsmasq
relay at `169.254.169.253`, which forwards to Kali's current Docker/VPN resolver.
This avoids copying an unreachable loopback nameserver such as `127.0.0.11`
into the isolated namespace. Port 80 is required so the per-lease transparent
REDIRECT rules intercept the request.

`/dev/net/tun` is **not** mounted by the base `docker-compose.yml`. The HTTP
capture plane needs `NET_ADMIN`, `SYS_ADMIN`, and unconfined seccomp/apparmor
to create and mount named network namespaces (`ip netns add`); `postrun.sh`
installs `iptables` and creates a tun device node only when a later VPN step
needs it. Keep host-tun mounting in a separate overlay if a VPN-in-container
run requires it; the #196 HTTP E2E gate must not depend on `/dev/net/tun`
existing on the host.

## Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `KALI_HTTP_HISTORY_ROOT` | `/data` | Store root (mounted `http-history` volume) |
| `KALI_HTTP_CAPTURE_ENABLED` | `true` | Off switch for diagnostic operation |
| `KALI_HTTP_MAX_BODY_BYTES` | `5242880` | Per-body capture cap; oversize bodies are *omitted* (never silently truncated) |
| `KALI_HTTP_NAMESPACE_POOL` | `8` | Concurrent capture sessions |
| `KALI_HTTP_LEASE_TTL_S` | `900` | Lease TTL for background processes |
| `KALI_HTTP_ACQUIRE_TIMEOUT_S` | `30` | Backpressure wait before `PoolExhaustedError` |
| `KALI_HTTP_DNS_SERVER` | `169.254.169.253` | Root-namespace dnsmasq relay used by leased namespaces |
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
- Retention and project-byte caps are implemented (`HttpHistoryService
  .enforce_limits(project_id)` / `.purge_project(project_id)`) and record a
  deletion reason, but no scheduler invokes them yet - an operator or a future
  cron calls them. `store.status()` reports the current footprint.

## Verification

```bash
.venv/bin/pytest tests/kali tests/attack/pod \
  tests/integration/test_test_executor_pod_contracts.py -q
.venv/bin/pytest tests/test_compose_config.py tests/app/test_kali_mcp_check.py -q
docker compose -f docker-compose.yml -f docker-compose.e2e.yml config
docker compose build kali
docker compose -f docker-compose.yml -f docker-compose.e2e.yml up -d kali http-e2e-target
docker compose ps kali http-e2e-target
docker compose exec kali \
  /opt/venv/bin/python /opt/kali/healthcheck.py --require-capture

KALI_MCP_URL=http://localhost:8000/mcp \
.venv/bin/pytest tests/e2e/test_http_proxy_history.py -vv -rs
```

The final command is the zero-skip live gate: it must produce `1 passed`, no
skip, `proxy_status.ok=true`, and the full acceptance set (method / header /
cookie / query / status / body marker, non-empty `http_artifact_refs`, real
`request_ref` pod resolution, immutable lineage, cookie preservation via the
local target, Docker service-name resolution from the leased namespace, project
isolation, and no raw secrets on the sanitized boundary).
For a host-only developer run that intentionally has no stack, set
`KALI_HTTP_E2E_ALLOW_SKIP=1`; that is not a valid issue-closing gate.

## Recorded live result

On 2026-09-12 the gate was run against the local compose target and passed:

```text
1 passed, 2 warnings
```

Both `polymerhus-kali-1` and `polymerhus-http-e2e-target-1` were healthy, and
`healthcheck.py --require-capture` returned `ok: true` with proxy, routing,
namespace and store components all healthy.
