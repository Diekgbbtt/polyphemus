# HTTP Proxy History (#196) — Design and walkthrough

This is the **only** design document for the HTTP proxy history. It replaces the decision
record, the two previous walkthroughs, the 2026-09-12 spec, the TDD plans and the operations
page: everything that had been scattered has been merged here, together with the real state of
the code.

Companion to this document (and the only other one): `http-proxy-history-test-evidence.md`, which
collects the runs on every target explored, the comparison between the call logs and the
artifacts, and the verdict on closure and merge.

Status: **branch `feat/http-history-hardening`**, latest commit `4585251`.

---

## 1. Pre-issue: what the system was like, and what was really missing

### 1.1 The blind terminal

Kali was (for the rest of the system) a terminal that executes commands:

```text
execute_command(command, session_id) -> {stdout, stderr, returncode, duration_ms}
```

No proxy, no transport hook, no trace of *what* the command had asked the targets. The
consequences were not cosmetic:

1. **No reproducibility.** Pod D6 recorded a `RawObservation` whose `request` was the command
   string, with a `probe_ref` that was its hash: from there you can trace back neither to a
   structured request nor to a transaction. A hunting spec had to **re-write** by hand the
   method, URL, headers, cookies, parameters and body in the `payload_vector_space`, losing the
   initial authenticated state and encouraging the agent to reconstruct (or invent) transport
   details.
2. **No attribution.** Even assuming a request could be reconstructed, there was no way to tie it
   to the project, to the run and to the unit of work that had generated it.
3. **No proof to the contrary.** Langfuse is external, best-effort observability; Steel's browser
   capture is in-memory and deduplicated; the D6 log is command-shaped. None of the three can
   answer "which HTTP transactions did this pod perform, and what was the response?".

### 1.2 The four criteria of #196

| # | Issue criterion | Where it stands today |
|---|---|---|
| 1 | every request/response leaving the kali container is recorded, with HAR-like breadth | **partial**: it holds for **leased** traffic (with a `project_id`) on ports **80/443** |
| 2 | artifacts can be queried by any recorded attribute | **implemented** (EAV index + FTS) |
| 3 | artifacts are durable and addressable through a stable id | **implemented** (SQLite + blob + ULID), with a byte ceiling |
| 4 | a hunter spec (or the pod) can reference a safe request by identifier | **implemented** (`request_ref` + `replay` tool, with no validation layer: ruling #191) |

### 1.3 The defects the implementation had to close

Found along the way, in order of discovery (all with evidence, see §3 and the test evidence):

1. the chain was wired only in the tests: `search/get/replay` answered `http_history_unavailable`
   in production, and the pod had no replay tool;
2. the lease runner used `bash -lc`: the login profile rebuilt `PATH` and the tools resolved to
   the wrong binary (or were missing), with the MOTD banner at the top of stdout;
3. the recon execution seam did not declare `capture_context`: the pods ran **without a lease**,
   so nothing was recorded — silently, with a green run;
4. the pod's capture coverage died in aggregation: `recon_jobs.stats` had no `capture` key, so
   one could not even tell that capture had not happened;
5. `enforce_limits` existed and was tested, but **nobody invoked it**: with capture on by
   default the store grew without bound;
6. inside the leased namespace **DNS did not exist** (the container's resolver is on
   `127.0.0.11`, i.e. the *container's* loopback): replay via `curl` could not resolve any
   hostname, and the defect was invisible to recon because httpx/katana bring their own
   resolvers;
7. the proxy **verifies** the upstream certificate: a lab target with a self-signed certificate
   could not be captured (502 to the client), and installing the CA "the Debian way" was not
   enough because mitmproxy verifies against **certifi**, not against the system store.

---

## 2. Post-issue: the current design

### 2.1 Architecture and boundaries

```text
┌─────────────── agent process (uvicorn :8080) ──────────────┐
│ API → recon pipeline → agent job (MAX_PODS) → POD          │
│                                   │ exec_fn(cmd, sid,      │
│                                   │  timeout, capture_ctx) │
└───────────────────────────────────┼────────────────────────┘
                                    │ MCP streamable-http :8000
┌────────────── kali container ─────┼────────────────────────┐
│ mcp_server.execute_command ──▶ HttpHistoryService          │
│        │                            │                      │
│        │                     LeaseManager.acquire          │
│        │                            │ namespace + REDIRECT │
│        │                            ▼  (tcp/80, tcp/443)   │
│        │                    tool in 172.30.0.x             │
│        │                            │ HTTP/HTTPS           │
│        │                     mitmdump ──▶ target           │
│        │                            │                      │
│        │                     addon + normalizer ──▶ store  │
│        └── refs = search(context/exec_id) ◀────────┘       │
└────────────────────────────────────────────────────────────┘
                    model frontier: sanitized views only
```

| Boundary | Rule |
|---|---|
| pod ↔ target | the pod does not open its own connections: without `exec_fn` there is no capture |
| agent ↔ kali | only the MCP contract; no shared memory or filesystem |
| kali ↔ target | traffic leaves through the lease namespace (source `172.30.0.x`), never from the container IP |
| store ↔ model | bodies and secrets do not cross: only `size`/`capture_state` and redacted values |

Four independent units, as in the original design: **capture plane** (mitmproxy, transparent
routing, normalization), **store** (immutable ids, index, content-addressed blobs), **access
plane** (MCP search/get/replay with per-project isolation), **integration** (capture context, D6
references, deterministic resolution of `request_ref`).

### 2.2 Walkthrough: the life of a request

```text
1.  the pod builds the context: project_id, run_id, spec_id (asset), session_id
      - spec_id = discriminator of the pod's asset (url, otherwise a stable hash)
2.  exec_fn(command, session_id, timeout_s, capture_context)   [only if the seam declares it]
3.  MCP execute_command(...) → the service mints an exec_id for THIS call
4.  acquire a lease: dedicated namespace + veth 172.30.0.<n> + REDIRECT tcp/80 and tcp/443
5.  the namespace receives its own /etc/resolv.conf: nameserver = lease gateway
      (the forwarder on the gateway forwards to the container's resolver: compose names and public names)
6.  the tool runs with `ip netns exec`; its web traffic ends up on mitmdump
7.  the addon resolves the source (registry source_ip → context) and normalizes the flow
8.  the record is written to the project's store; bodies go to content-addressed blobs
9.  at the end of the command, in a `finally`: refs = search(context/exec_id == exec_id) → release the lease
10. the pod writes the outcome into its export: stats.capture = {sent, refs, warning}
11. the pipeline merges the pods' exports into recon_jobs.stats[].capture
12. (throttled, best-effort) enforce_limits on the project: byte cap
```

Step 3 and step 9 are the backbone of the correlation: **the `exec_id` is minted by the
service**, not by the caller, and the search at the end of the command is the only thing that
ties a list of artifacts to the individual call — even with several pods in parallel. Step 9 is
in a `finally` because a command that blows up must neither leave a lease hanging nor lose the
artifacts already recorded.

### 2.3 The data model

```text
/data/<project_id>/http-history/
├── history.sqlite3          (WAL)
└── bodies/<sha256>.blob
```

| Table | Content |
|---|---|
| `flows` | one row per artifact: `record_json` (the truth, schema `http-artifact/v1`) + `created_at` |
| `attributes` | sparse index `(side, namespace, key, text_value|numeric_value)` for EVERY scalar |
| `flows_fts` | full-text on url/header/body marker |
| `bodies` | content-addressed blobs + reference, with GC of those no longer used |
| `meta` | audit of the last pruning |

An artifact: `artifact_id` (ULID), `project_id`, `capture_context` (session/run/spec/variant/
exec/derived_from/replay_kind), `request` and `response` (version, method/status, headers, cookies,
query/form, body with `size`/`encoding`/`capture_state`), `connection` (addresses, protocol,
tls, sni, alpn), `timings`, `error`, `derived_from`, `replay_kind`, `created_at`.

Choices and why:

| Choice | Reason |
|---|---|
| complete document per artifact | self-sufficient: it can be read without joins |
| EAV index instead of a single blob | "queryable by any attribute" without schema migrations |
| body as a content-addressed blob | dedup, and the body never enters the model views |
| explicit `capture_state` (`none/empty/captured/omitted/truncated`) | never a silent truncation |
| lineage `derived_from` + `replay_kind` | a replay is a request **with history** |
| ULID prefix `http_` | stable, sortable, addressable |

### 2.4 Querying the index

Each row of the index is `(side, namespace, key, value)`. `side` ∈
`{request, response, connection, context, timing}`; `namespace` ∈
`{core, header, cookie, query, form, body, tls}`. The filters are conjunctive and support
`eq | contains | prefix | gte | lte | absent` (plus full-text search), always restricted by
`project_id` before applying the user filters. Real examples:

```text
context/core/run_id      eq      <run>              all the traffic of a run
context/core/spec_id     eq      <asset>            what the pod working on X asked for
response/core/status     eq      200                by outcome
request/header/user-agent contains Firefox          by client
body/body/marker         contains marker=            by marker in the body
```

### 2.5 The contracts

| Seam | Essential signature |
|---|---|
| execution from the pod | `exec_fn(command, session_id, timeout_s, capture_context=None) -> ExecResult{stdout, stderr, returncode, duration_ms, exec_id, http_artifact_refs, capture_warning}` |
| MCP execution | `execute_command(command, session_id, timeout_s, project_id, run_id, spec_id, variant_ref, derived_from, replay_kind)` — backward-compatible |
| search | `search_http_history(project_id, filters, cursor, limit, text) -> {summaries, next_cursor}` |
| read | `get_http_artifact(project_id, artifact_id, include_body=False)` — `include_body=True` rejected here |
| replay | `replay_http_request(project_id, artifact_id, overrides, capture_context)` |
| status | `proxy_status() -> {mcp, proxy, routing, namespaces, store, capture}` |
| aggregation | `capture_job_stats(pod_exports) -> {sent, refs, warning}` |

The replay override vocabulary is **closed**: `method`, `url`/`path`, `query`,
`header(s)`, `cookie(s)`, `remove_header(s)`, `body`/`form`/`json`. Never a shell command, never
an expression. Ownership is asymmetric on purpose: the **context** belongs to the caller, the
**id** and the **record** belong to kali, the **merge** belongs to the pipeline.

Configuration (compose → kali container):

| Variable | Default | Meaning |
|---|---|---|
| `KALI_HTTP_CAPTURE_ENABLED` | `true` | diagnostic switch |
| `KALI_HTTP_HISTORY_ROOT` | `/data` | store root (volume) |
| `KALI_HTTP_MAX_BODY_BYTES` | 5 242 880 | cap per body; beyond → `omitted`, never silently truncated |
| `KALI_HTTP_NAMESPACE_POOL` | 8 | concurrent leases |
| `KALI_HTTP_LEASE_TTL_S` / `KALI_HTTP_ACQUIRE_TIMEOUT_S` | 900 / 30 | TTL and backpressure (`PoolExhaustedError`) |
| `KALI_HTTP_PROXY_HOST` / `PORT` | `127.0.0.1` / `8080` | mitmdump listener |
| `KALI_HTTP_RETENTION_S` | `0` | retention by age (0 = do not delete) |
| `KALI_HTTP_PROJECT_MAX_BYTES` | `1073741824` | byte ceiling per project (1 GiB) |
| `KALI_HTTP_LIMIT_ENFORCE_INTERVAL_S` | 60 | throttle of the trimmer |
| `KALI_HTTP_UPSTREAM_CA` | *(empty)* | operator CA for self-signed upstreams |
| `POD_HTTP_CAPTURE` (agent side) | `1` | kill-switch of capture in the pod |

### 2.6 The two network and trust prerequisites (learned in the field)

**DNS in the lease.** The container receives from Docker `nameserver 127.0.0.11`, which is
Docker's embedded resolver **on the container's loopback**: in a child namespace that address is
the *namespace's* loopback, and it does not answer. Every lease therefore writes its own
`/etc/resolv.conf` (which `ip netns exec` bind-mounts from `/etc/netns/<ns>/`) with the **lease
gateway** as the first nameserver, and a `DnsForwarder` forwards from there to the container's
resolver: the lease sees the same answers (compose names and public names). `/etc/hosts` is copied
into the namespace so as not to lose the aliases. One listener per gateway, bound to the life of
the lease; a query that cannot be forwarded is dropped, never invented. UDP only (declared).

**Upstream trust.** mitmdump verifies the certificate of the site it records. For a target with a
self-signed certificate the operator points `KALI_HTTP_UPSTREAM_CA` at a file containing its CA,
and the bootstrap does **two** things: it installs it in the system store (needed by the clients
inside the lease, e.g. the replay's `curl`) **and** it builds a `default store + operator CA`
bundle that the entrypoint passes to mitmdump via `ssl_verify_upstream_trusted_ca`. The second is
indispensable: mitmproxy verifies against **certifi**, not against the system store — a first run
proved it by failing with the same error right after `curl` had started working. This was
preferred over `ssl_insecure` (which would accept **any** upstream, and in a plan that records
evidence would mean trusting the wrong peer). The flag is **opt-in**: the bundle lives on the
volume, but without the knob it is not used.

### 2.7 Fail-open and fail-closed

| Situation | Behaviour | Why |
|---|---|---|
| proxy unreachable | command executed, `capture_warning` set, `refs=[]` | reconnaissance must not die because the recorder broke |
| namespace pool exhausted | same, with `PoolExhaustedError` in the warning | **declared** degradation, visible in `stats.capture` |
| exec outside the pod path (no `project_id`) | no lease, no capture, no error | capture is per project |
| body beyond the cap | artifact recorded, `capture_state="omitted"` | the content is lost, not the transaction |
| replay of a baseline with a declared but absent body | **rejected** (`body_unavailable`) | fail-closed: a replay without a body would falsify the experiment |
| cross-project lookup / nonexistent id | `not_found` | no enumeration across projects |
| corrupted index | rebuildable from `record_json` | the index is derived, the document is the truth |

### 2.8 Invariants

1. **Capture is never a gate**: no recon path degrades because the recorder is down.
2. **Failure is visible**: `sent` distinguishes "I did not ask" from "I asked and nothing came
   back"; `refs=0` with `sent=true` cannot pass for a successful capture.
3. **One writer per truth**: the proxy writes the record, sanitization is a projection.
4. **The model boundary is explicit**: what is not in the projection (body, `source_ip`,
   sensitive headers) does not exist for the model; the secrets stay in the store only for the
   replay.
5. **Lineage is not lost**: every replay carries `derived_from`; every artifact carries the
   context of the execution.
6. **Limits are declared where they bite**: body cap, byte ceiling, pool, redirected ports.

### 2.9 The decisions, and why

| Decision | Why |
|---|---|
| mitmproxy **inside** kali, transparent routing | no sidecar, no new routing boundary; kali already has `NET_ADMIN` |
| **passive** proxy | it records, it does not modify: a modification of the traffic would falsify the measurements |
| `exec_id` minted by the service + `source_ip → context` registry | correlation does not depend on time windows or on the order of commands |
| lease per execution | isolation and attribution; the pool provides explicit backpressure |
| package as truth + EAV index + FTS | queryability without migrations, self-sufficient document |
| content-addressed body with `capture_state` | dedup and no silent truncation |
| `spec_id` = the pod's asset | answers "what did the pod tasked with X ask for", which no other field covers |
| capture **on by default** + `POD_HTTP_CAPTURE=0` | the failure that closes the issue is silent; the costs are visible |
| byte ceiling 1 GiB + retention **0** | the cap covers growth; deleting by age removes evidence without disk pressure |
| `capture_context` forwarded by signature inspection | three-argument fakes keep working; no test breakage |
| operator CA instead of `ssl_insecure` | trusting any upstream falsifies every artifact |

---

## 3. Pre → post: the closed defects

| # | Symptom (pre) | Cause | Fix | Evidence |
|---|---|---|---|---|
| 1 | `search/get/replay` → `http_history_unavailable`; the pod had no replay tool | the callables were not injected in the production builder | app-side sync client + binding in `runtime.py` (`search/get` in the hunter, `replay` in the pod) | 14 tests in `tests/attack`; live gate `tests/e2e/test_http_proxy_history.py` |
| 2 | `httpx` resolved to the Python CLI, `katana`/`naabu`/… "MISSING", MOTD banner in stdout | lease runner with `bash -lc` (the profile rebuilds `PATH`) | non-login runner (`bash -c`) + MOTD guard in `postrun.sh` | lease preflight via MCP: `/root/go/bin/httpx`, `status_code=200`, `rc=0`, no banner |
| 3 | tool log with `http_artifact_refs: []`, empty store, green run | the test seam did not declare `capture_context` → no lease | capture-aware seam + forwarding conditioned by the signature | `tests/recon/test_pod_capture_context.py`, live e2e |
| 4 | `recon_jobs.stats` without a `capture` key | the pod's fragment was not merged | additive `capture_job_stats` (`refs` sum, `sent` OR, warnings preserved) | unit + e2e (`stats.capture` per job) |
| 5 | store with no limit, `enforce_limits` never called | no caller in production | throttled, best-effort invocation from `execute` + 1 GiB cap | `tests/kali/test_http_history_service.py` |
| 6 | `curl` in the lease: `Could not resolve host` (rc 6) | the copied `/etc/resolv.conf` pointed at the container's resolver | per-lease resolver on the gateway + `DnsForwarder` + copy of `/etc/hosts` | 7 tests + live evidence (`getent`, `curl`, HTTPS replay) |
| 7 | HTTPS to a self-signed target: 502, artifact with `Certificate verify failed` | mitmdump verifies the upstream against certifi | `KALI_HTTP_UPSTREAM_CA` → system store **and** bundle for the proxy (opt-in) | 6 tests + run on `soupmarket.shop` (36 TLS transactions, 0 errors) |

### 3.1 What has **not** changed (and that is fine)

The recon delta report (tool stdout ↔ graph) has remained identical: capture is an **extra**
layer, not an alternative path. The positive control of the gate, the launch guards (400 on a
missing seed, on IPv6, on unknown jobs), the katana command byte-identical to the template and
`-ct 240s` were not touched.

---

## 4. Modules and files

| Area | File |
|---|---|
| capture context and forwarding from the pod | `src/polymerhus/recon/domain/pod.py`, `src/polymerhus/recon/config.py` |
| capture coverage in the job stats | `src/polymerhus/recon/control/pipeline.py` |
| app-side client (hunting) | `src/polymerhus/app/clients/kali_http_history.py` |
| MCP surface | `kali/mcp_server.py` |
| execution, lease, ref lookup, limits, replay | `kali/http_history/service.py` |
| namespace leases, per-lease resolver | `kali/http_history/namespaces.py`, `kali/http_history/dns.py` |
| upstream trust (CA + bundle) | `kali/http_history/trust.py`, `kali/postrun.sh`, `kali/entrypoint.sh` |
| proxying and normalization | `kali/http_history/addon.py`, `normalize.py`, `models.py` |
| store, index, FTS, retention/cap | `kali/http_history/store.py`, `index.py` |
| replay (plan + sender in the namespace) | `kali/http_history/replay.py`, `sender.py` |
| model boundary | `kali/http_history/sanitize.py` |
| e2e fixtures (target, WAF, challenge, preflight) | `tests/e2e/http_e2e_target.py`, `http_challenge_target.py`, `tcp_forwarder.py`, `docker-compose.e2e.yml` |

Tests: `tests/kali/*` (store and MCP surface contract), `tests/recon/test_pod_capture_context.py`
(context and coverage in the pod), `tests/recon/test_pipeline.py` (aggregation),
`tests/e2e/test_recon_crawl_katana_depth.py` (live crawl-only gate + capture + replay),
`tests/e2e/test_http_proxy_history.py` (the #196 history gate), `tests/attack/*` (tool bindings).

---

## 5. Limits and residual risks

| Limit | Effect | Trigger to reopen it |
|---|---|---|
| capture only **in lease** and only on **tcp/80 + tcp/443** | traffic on non-web ports is not recorded; an `execute_command` without `project_id` does not go through the proxy | a real job on a non-standard port, or the need for capture outside the pod path |
| **QUIC/HTTP3** rejected (UDP/443) and declared | a client that insists on HTTP/3 is not captured | a target that serves HTTP/3 only |
| namespace **pool** = `MAX_PODS` (8) | beyond the pool: fail-open degradation, visible in `stats.capture` | per-job concurrency above the pool |
| **TLS fingerprint** of the proxy | the target sees mitmproxy, not the tool | WAFs that check the fingerprint (measured: Cloudflare on `example.com` did not block) |
| **retention 0** + 1 GiB/project ceiling | at saturation the oldest artifacts are evicted | need for long-term retention on large projects |
| body cap 5 MiB | beyond: `omitted`, replay rejected if the body is declared | recurring large payloads |
| **WAF challenge not detected** downstream (C.3/E.2) | a challenge page is ingested as application surface: evidence that *looks* clean | decide E.2: label it `inconclusive`, never `symptom-confirmed` |
| **tool telemetry** in the store | httpx/katana contact `api.pdtm.sh`: 2 artifacts per run with a `machine_id` | noise in the queries, or a policy on machine identifiers |
| CA provided by the operator | the self-signed target is capturable only with `KALI_HTTP_UPSTREAM_CA` | — (by design: trust is a decision) |
| clients with **certificate pinning** | observable only as failed/incomplete flows | mobile/desktop targets with pinning |

---

## 6. Issue status and merge readiness

### 6.1 Is #196 "fixed"?

Three criteria out of four are **implemented and verified** (queryability by attribute, durability
+ stable id, reference by identifier from pod/hunter). The first — "every request/response
leaving the kali container is recorded" — is **partial by construction**: it holds for **leased**
traffic on ports **80/443**.

So the answer is: **yes, with a scope declaration**, or no if criterion 1 is read literally
("*every* request of the container"). The two roads:

1. **close** it with the note: "recording for the traffic of executions tied to a project, on web
   ports, with declared fail-open degradation in `stats.capture`";
2. **keep it open** with a tracked follow-up for the residual (exec outside the pod path,
   non-web ports, QUIC).

In both cases the **E.2** point (WAF challenge not interpreted) stays out of the closure: capture
is complete, the interpretation is not — it is a *declared* gap, not a silence, but it is exactly
the class of error ("evidence that looks clean") that Part B of the design considered the most
dangerous.

### 6.2 Can it be merged?

**Yes**, the branch is mergeable, with these operational preconditions:

| Precondition | Status |
|---|---|
| clean working tree | **no**: three `PROMPT-*.md` show up as deleted and uncommitted (leftover from previous sessions) plus one untracked prompt. They must be restored or committed *before* the merge |
| no secrets in the repo | yes: the lab CA lives in a docker volume (`/data/upstream-ca.crt`), the worktree's `.env` symlink is git-ignored, there are no credentials in the artifacts/docs |
| green tests | yes: unit tier of the capture plane and of the pod, live gate on three targets (numbers in the test evidence) |
| no undeclared new behaviour | yes: the per-lease DNS is an always-on, tested fix; upstream trust is **opt-in**; the byte ceiling has a default but is throttled and best-effort |
| consolidated documentation | yes: this document + the test evidence; the seven previous pages have been removed |
| code served in production | **to do at deploy time**, not at merge: the agent image does not mount `src/`, so a **rebuild** (CI) is needed for the branch to be active; for kali `--force-recreate` is enough (it mounts `./kali`) |

Recommended sequence: clean the tree → rebase onto the destination branch → rebuild
`polymerhus-agent` → `up -d --force-recreate kali agent` → re-run `tests/kali`,
`tests/e2e/test_http_proxy_history.py` and `tests/e2e/test_recon_crawl_katana_depth.py` → merge.

### 6.3 Recommended follow-ups (non-blocking)

1. **E.2 — challenge detection**: use the markers we already record (`cf-mitigated`, `cf-ray`,
   interstitial) to label the challenge as inconclusive, never `symptom-confirmed`.
   The fixture is ready and the test is born red.
2. **Ignore-list for tool telemetry** (`api.pdtm.sh`) so as not to pollute the per-run queries.
3. **Non-web ports / QUIC**: topology decision (Part D of the old record, here §5).
4. **Operator-provided CA** as part of the deploy (not extracted from the handshake).

---

## 7. Glossary

| Term | Meaning |
|---|---|
| **artifact** | a recorded HTTP transaction, with a stable id (`http_01…`) |
| **capture context** | the project/run/pod/asset an execution belongs to |
| **exec_id** | identifier of **one** call to kali; the collection key for the artifacts of that window |
| **lease** | temporary loan of a network namespace with the web traffic diverted to the proxy |
| **spec_id** | discriminator of the pod's asset: "what this pod was working on" |
| **replay** | resending a recorded baseline changing only declared overrides, with lineage |
| **sanitized** | view for the model/Langfuse: no body, sensitive values redacted |
| **fail-open / fail-closed** | capture degrades and declares it; resolution of a reference fails instead of approximating |
| **`stats.capture`** | `{sent, refs, warning}` per job: the proof, in the DB, of what was captured |
