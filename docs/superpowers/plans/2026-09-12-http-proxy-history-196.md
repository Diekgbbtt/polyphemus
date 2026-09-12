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

## Verification status (2026-09-12, this workspace)

Verified green:

- `tests/kali` (92) - ids, model, store, index/search/cursor, sanitization,
  normalize, addon, registry, namespaces, replay, service/MCP tools, retention,
  deployment shape.
- `tests/attack/test_http_history_tools.py`, `tests/attack/test_hunting_pod.py`,
  `tests/attack/pod/test_request_ref.py`, `tests/attack/pod/test_http_history_refs.py`,
  `tests/recon/test_exec_result_http_refs.py`, `tests/app/test_kali_mcp_check.py`,
  `tests/test_compose_config.py` - 128 passed in one run.
- `docker compose config` exits 0; the rendered kali service matches the
  deployment test.
- `tests/e2e/test_http_proxy_history.py` skips cleanly with no stack running.

Not verifiable in this sandbox (reported, not worked around):

- `docker compose build kali` / `up -d kali`: the `redamon-kali-sandbox:latest`
  base image is not present and cannot be pulled here (`pull access denied`).
- The broad `tests/attack/pod` and `tests/attack` tiers stall in this sandbox:
  any test whose sync seam crosses `asyncio.to_thread` blocks in
  `loop.shutdown_default_executor()`. Reproduced identically on the unmodified
  `dev` checkout (`tests/attack/pod/test_tools.py`), so it is environmental, not
  a #196 regression. New tests avoid sync seams.

## E2E gate hardening (2026-09-12 follow-up)

The live acceptance test is no longer allowed to skip by default. It now:
searches method/header/cookie/query/status/body-marker conjunctively; requires
non-empty `http_artifact_refs`; runs the real `HuntingHttpPod.request_ref`
resolver rather than calling `replay_http_request` directly; asserts that
untouched attributes and the replayed cookie survive while only the declared
query mutation changes; and scans the sanitized pod/artifact boundary for raw
secrets. The local deterministic target is in
`tests/e2e/http_e2e_target.py` and `docker-compose.e2e.yml`; the base compose no
longer mounts the host `/dev/net/tun`, and the entrypoint now invokes
`/opt/kali/postrun.sh`, starts mitmproxy in transparent mode, and installs the
pydantic dependency in the mitmproxy environment. Live verification also
surfaced and fixed three runtime-only defects: `ip netns` requires `SYS_ADMIN`
plus unconfined seccomp/apparmor, the per-lease veth gateway was on a different
subnet than the namespace source, and `SourceRegistry` dropped `derived_from` /
`replay_kind` during lookup. Run the gate with the commands in
`docs/design/http-proxy-history-operations.md`; it now passes `1 passed`.

## Final live integration

The `redamon-kali-sandbox:latest` base image was built from the public RedAmon
repository (`samugit83/redamon`), then `polymerhus-kali:latest` was built from
`kali/Dockerfile`. With `docker-compose.yml` + `docker-compose.e2e.yml`, the
following were started and left healthy:

```text
polymerhus-kali-1
polymerhus-http-e2e-target-1
```

Final evidence on `dev` after the merge:

```text
116 passed - tests/kali + http-history tooling + request_ref/refs
5 passed   - compose config + kali MCP check
1 passed   - tests/e2e/test_http_proxy_history.py live gate
```

Integration commits:

```text
11c726f fix(kali): harden #196 live E2E gate and capture plane
9fbce12 merge(kali): #196 live E2E hardening
```
