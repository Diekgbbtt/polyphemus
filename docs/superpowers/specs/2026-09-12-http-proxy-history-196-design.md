# HTTP Proxy History #196 Design

**Status:** Proposed and operator-approved in chat on 2026-09-12  
**Scope:** Issue #196 only: durable HTTP request/response history for Kali and identifier-based reuse by the hunting pod. DOM capture and issue #51 are out of scope.

## 1. Problem

The Kali MCP surface is a blind terminal. `kali/mcp_server.py::execute_command` runs an arbitrary shell command and returns only `stdout`, `stderr`, `returncode`, and `duration_ms`. The hunting pod records that result as a `RawObservation` whose `request` is only `{"command": ...}` and whose opaque `probe_ref` hashes `(variant_ref, command)`. Neither value identifies an HTTP transaction or resolves back to a structured request.

Langfuse mirrors tool calls externally and best-effort, so it is observability rather than operational memory. The pod D6 log is durable but command-shaped. Steel's Playwright capture is browser-only, in-memory, endpoint-deduplicated, and intentionally lossy. None provides a per-project request/response store that a hunter spec can address and reuse.

The result is that a hunter must re-author method, URL, headers, cookies, parameters, and body in `payload_vector_space`. This loses authenticated baseline state, makes probes less reproducible, and encourages an agent to reconstruct or invent transport details.

## 2. Goals

1. Record HTTP/1.1 and HTTP/2 request/response flows emitted from the Kali container, including interceptable HTTPS.
2. Preserve HAR-like request, response, connection, timing, and error attributes without making HAR the internal schema.
3. Persist flows durably under `data/<project_id>/http-history/` and assign every flow an immutable identifier.
4. Search flows by every recorded scalar attribute, including arbitrary header, cookie, query, form, and textual body-marker values.
5. Resolve and replay a legitimate request by identifier within the same project.
6. Let a hunter spec carry a baseline `request_ref` inside the existing open-dict `payload_vector_space` contract.
7. Link D6 observations and Langfuse spans to HTTP artifact identifiers without duplicating secret-bearing wire content.
8. Fail honestly and preserve the no-extra-validation-layer ruling from #191.

## 3. Non-goals

- DOM snapshots or any implementation of #51.
- An interactive Burp-like UI, manual interception, or request editor.
- Generic TCP capture, WebSocket message history, or decoded QUIC/HTTP3.
- Merging Steel's endpoint manifest into this store.
- Guaranteeing HTTPS decryption for certificate-pinned clients.
- Sending raw credentials, cookies, authorization headers, or bodies to an LLM or Langfuse.
- Encryption at rest in the first delivery. The store boundary must permit it later.

## 4. Chosen architecture

Run `mitmdump` inside the existing Kali container and route Kali's outbound HTTP/HTTPS through it transparently. Kali already has `NET_ADMIN`, and co-location avoids a sidecar routing boundary. A Polyphemus mitmproxy addon converts completed `HTTPFlow` objects into immutable records and writes them through a focused store API. Proxy-originated connections are excluded from interception to prevent loops.

The proxy is passive: it does not modify application traffic. It records completed responses and transport errors. TLS interception uses a generated, persisted mitmproxy CA installed into Kali's system trust store. Clients that pin certificates remain observable only as failed/incomplete flows. QUIC/HTTP3 is not silently downgraded or claimed as captured.

The architecture has four independent units:

1. **Capture plane:** mitmproxy lifecycle, transparent routing, flow normalization.
2. **Artifact store:** immutable IDs, SQLite metadata/index, content-addressed body blobs.
3. **Access plane:** MCP search/get/replay operations with project isolation and sanitized default views.
4. **Hunting integration:** capture context propagation, D6 references, and deterministic `request_ref` resolution.

## 5. Capture context and correlation

Every `execute_command` call creates an `exec_id` and supplies a capture context:

```text
project_id, session_id, run_id, spec_id, variant_ref, exec_id
```

The context is runtime metadata, not a hunter-spec validation schema. The hunting pod must stop collapsing all production calls into the fixed `hunt-pod` session and propagate the project/run/spec/variant identity already known by its graph and memory store.

The MCP server leases one lightweight Linux network namespace per concurrent execution before spawning the command. Each namespace has a unique veth source address, shares the existing `/work/<session_id>` filesystem, and egresses through the root Kali namespace, whose existing VPN and Docker routes remain authoritative. The subprocess runs with `ip netns exec`; namespace DNS configuration mirrors Kali's resolver configuration. Transparent-routing rules send each namespace's HTTP/HTTPS egress to mitmproxy while excluding the proxy's own upstream connections.

The MCP server registers the lease as `source namespace/address -> capture context` before spawning and releases it only after the process exits and the proxy has drained its connections. The addon resolves the flow's client source through that registry. This is the mandatory concurrency mechanism: association must not rely on a time window, command order, or one process-global active context. A bounded namespace pool applies backpressure when all execution slots are occupied.

Flows that cannot be correlated are still recorded under an explicitly denoted unscoped capture bucket and are never returned by project-scoped hunting queries. This preserves forensic truth without crossing project boundaries.

## 6. Canonical artifact

Each captured transaction receives an opaque, time-sortable, immutable ID with an `http_` prefix. ULID is the intended representation. Content hashes are integrity/deduplication fields, not primary identifiers, because two identical requests can be distinct events with different responses and timing.

The canonical record contains:

```yaml
schema_version: http-artifact/v1
artifact_id: http_<ulid>
project_id: <project>
capture_context:
  session_id: <session>
  run_id: <run>
  spec_id: <fault_strategy>
  variant_ref: v0
  exec_id: <execution>
request:
  method: POST
  url: https://target.example/login
  http_version: HTTP/2
  headers: [[content-type, application/json]]
  cookies: []
  query: []
  body_ref: sha256:<digest>
  body_size: 42
  body_encoding: utf-8
  timestamp_start: 0.0
  timestamp_end: 0.0
response:
  status: 200
  reason: OK
  http_version: HTTP/2
  headers: []
  cookies: []
  body_ref: sha256:<digest>
  body_size: 100
  body_encoding: utf-8
  timestamp_start: 0.0
  timestamp_end: 0.0
connection:
  client_address: null
  server_address: null
  tls: true
  sni: target.example
  alpn: h2
timings:
  total_ms: 25
error: null
derived_from: null
replay_kind: null
created_at: 0.0
```

Header order and duplicates are preserved as pairs. Cookie parsing is additive; raw `Cookie` and `Set-Cookie` headers remain available. Missing responses and protocol errors produce artifacts with `response: null` and a structured `error`, rather than disappearing.

## 7. Persistence and indexing

Each project owns:

```text
data/<project_id>/http-history/
├── history.sqlite3
└── bodies/<sha256>.blob
```

SQLite runs in WAL mode. The schema separates immutable flow records, body metadata, and an inverted scalar-attribute index. Bodies are stored as content-addressed blobs so large or repeated payloads do not inflate the database. Blob insertion is atomic and a record is committed only after its referenced bodies are durable.

Every recorded scalar is projected into an attribute row shaped as:

```text
artifact_id, side, namespace, key, text_value, numeric_value
```

Examples include request method/URL, response status, header values, cookie values, query/form values, timing, TLS attributes, capture-context keys, and decoded textual body markers. B-tree indexes serve exact/prefix/range filters; SQLite FTS serves URL and textual marker search. Search is conjunctive, paginated, deterministically ordered by `(created_at, artifact_id)`, and always constrained by `project_id` before user filters are applied.

There is no silent body truncation. Configured capture limits may omit a body only with explicit `capture_state`, original size, hash when computable, and reason. Binary bodies are never decoded heuristically for prompt output.

## 8. Access and replay API

The Kali MCP surface gains three operations, implemented over the store rather than mitmproxy internals:

- `search_http_history(project_id, filters, cursor, limit)` returns sanitized summaries and artifact IDs.
- `get_http_artifact(project_id, artifact_id, include_body=False)` returns a sanitized record by default; raw body access is runtime-only and separately authorized.
- `replay_http_request(project_id, artifact_id, overrides, capture_context)` resolves the raw baseline, applies a closed set of deterministic overrides, sends it through the capture path, and returns the new artifact ID.

Replay never mutates the source artifact. The result carries `derived_from=<source id>` and `replay_kind=baseline|mutated`. Cross-project lookup and replay return not-found semantics, so callers cannot use the API to enumerate another project's identifiers.

The override vocabulary initially supports method, URL/path, query value, header value, cookie value, and body/form/JSON value replacement. It does not accept an arbitrary shell command.

## 9. Hunting contract

`payload_vector_space` remains one open dictionary. The new authored form is:

```yaml
payload_vector_space:
  request_ref: http_01K...
  mutations:
    - location: query
      name: search
      values: ["'", "' OR 1=1--"]
```

The existing inline `method`/`path`/`body` form remains supported. The resolver follows two exclusive paths:

1. `request_ref` present: resolve the project-local baseline and derive the probe/replay operations from it.
2. `request_ref` absent: preserve the existing authored-inline behavior, including #191's no-defaulting rule for non-empty dictionaries.

`validate_spec` continues to require only that `payload_vector_space` is a dictionary. It does not validate a new nested schema. A missing, inaccessible, or non-replayable reference is a runtime resolution failure recorded in D6 and terminates as `technical-infeasibility`; it is not an INIT malformed-spec rejection.

Hunter authoring guidance may search safe baseline requests and place an ID in the spec, but the LLM sees sanitized summaries only. Raw secrets are resolved and applied by deterministic runtime code.

## 10. D6 and observability

`RawObservation` gains `http_artifact_refs: list[str]`. `probe_ref` remains the variant-scoped command/probe dedup key and is not repurposed. The D6 record links an experiment to one or more HTTP transactions without copying the artifact contents.

Langfuse spans may contain artifact IDs, counts, methods, hosts, status classes, sizes, and timing. They must not contain raw authorization/cookie headers or request/response bodies. Store failures remain visible as denoted warnings and do not invent artifact references.

## 11. Security, retention, and failure semantics

- All access is project-scoped before filtering or ID resolution.
- Store files and blobs are owner-readable/writable only.
- Raw secrets remain in the artifact store for legitimate replay but are redacted from MCP model-facing views, logs, errors, and Langfuse.
- Configurable limits cover total project bytes, body bytes per flow, and retention age. Limit enforcement records the deletion/omission reason.
- Project purge removes database rows and then garbage-collects unreferenced blobs.
- Capture/store outages are fail-open for command execution: the command result still returns, with a capture warning.
- Artifact resolution and replay are fail-closed: a missing baseline is never approximated from partial D6 or command text.
- Database corruption and schema-version mismatch surface explicit errors; no automatic destructive rebuild occurs.

## 12. Deployment

The Kali image must contain a pinned mitmproxy version, `iproute2`, SQLite support, and the Polyphemus addon. `postrun.sh` owns idempotent CA bootstrap, namespace/veth pool bootstrap, forwarding/NAT, and transparent routing rules. Compose adds a durable host-backed or named volume for HTTP history and a health check that distinguishes MCP readiness, proxy readiness, namespace/routing readiness, and store writability.

The agent and Kali need a single agreed data ownership topology. Production artifacts are rooted at the repository's/project data seam; tests use explicit temporary roots. Environment configuration supplies capture enablement, storage root, body/project limits, retention, and proxy listen parameters. Capture defaults on in the supported compose stack once health checks pass; an explicit off switch preserves diagnostic operation.

## 13. Testing and acceptance

### Unit

- HTTPFlow normalization preserves duplicate headers, cookies, query/form values, bodies, timing, TLS fields, and errors.
- Artifact IDs are unique and immutable.
- Attribute projection and conjunctive filters cover every scalar namespace.
- Sanitization removes secret values from model-facing records.
- Replay overrides change only their declared locations.
- `request_ref` resolution preserves inline behavior and #191 validation semantics.

### Integration

- The addon records HTTP success, HTTPS success, redirect chains, duplicate requests, binary/large bodies, and connection failure.
- Concurrent command contexts do not cross-associate flows.
- Search/get/replay enforce project isolation.
- D6 observations contain valid artifact references and no duplicated raw secrets.
- A store outage leaves `execute_command` usable and produces a warning.

### End to end

Against a controlled target, execute a safe authenticated request from Kali, find it by method/header/cookie/status/body marker, author a hunter spec with its `request_ref`, mutate one declared parameter, replay it, and assert:

1. baseline and replay have distinct stable IDs;
2. replay has `derived_from` pointing to the baseline;
3. session cookies and untouched request attributes are preserved;
4. only the declared mutation changes;
5. the resulting D6 observation links the replay artifact;
6. no secret-bearing fields appear in Langfuse or tool-facing summaries.

The acceptance phrase "every request/response outbound from Kali" is considered satisfied for intercepted HTTP/1.1 and HTTP/2 traffic, including HTTPS trusted by the installed CA. Pinned TLS, QUIC/HTTP3, generic TCP, and traffic emitted while capture health is degraded are explicitly reported limitations, never silently counted as captured.

## 14. Delivery slices

1. Canonical model, SQLite/blob store, attribute projection, query API, and security views.
2. Mitmproxy addon, Kali bootstrap/routing, durable volume, and health checks.
3. Concurrent capture-context propagation from pod through MCP to subprocess flows.
4. Search/get/replay MCP operations and immutable replay lineage.
5. D6 artifact references and safe Langfuse metadata.
6. `payload_vector_space.request_ref` resolver with deterministic mutations and inline fallback.
7. Retention/purge controls and the full controlled-target end-to-end acceptance test.
