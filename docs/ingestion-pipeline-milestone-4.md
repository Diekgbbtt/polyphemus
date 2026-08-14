# Ingestion Pipeline Milestone 4: Secure URL Ingestion

## Overview

Milestone 4 adds `source_kind="url"` to the ingestion pipeline without changing
any existing file-ingestion behavior. A URL job is accepted through an
authenticated n8n webhook, downloaded by the backend's SSRF-guarded downloader
(the sole network authority), normalized by the existing docprep pipeline, sent
through the Milestone 3 audit gate, and then either activated as
`PROCESSED` or rejected as `FAILED` / `FAILED_AUDIT`. Duplicates and updates
follow the same registry and rollback semantics that already exist for files.

Scope is deliberately narrow and matches the confirmed contract:

- only direct HTML (`text/html`, `application/xhtml+xml`) and direct Markdown
  (`text/markdown`, `text/x-markdown`, and `text/plain` only with reliable
  `.md`/`.markdown` evidence);
- PDF and every other content format are deferred;
- only `http` and `https`, only default ports `80` and `443`;
- identity is the canonical initially requested URL, never a redirect
  destination;
- the backend downloader is the sole URL network authority; n8n never
  downloads or parses target content;
- `ETag` and `Last-Modified` are recorded as metadata only; conditional GET is
  deferred;
- no proxies, cookies, authenticated target pages, browser rendering,
  crawling, sitemap expansion, durable worker queue, or non-default public
  ports.

## Feature Scope and Architecture

### Request flow

```text
n8n webhook (Header Auth, X-Polyphemus-Ingestion-Secret)
  -> Validate URL field (native IF)
  -> POST /v1/ingestions {"source_kind":"url","source_uri":"<raw url>"}
       (FastAPI create_ingestion)
  -> service.submit: canonicalize -> build_url_source_key
     -> null-hash stub + DISCOVERED job
  -> FastAPI BackgroundTasks -> service.process_job(job_id, requested_url)
  -> UrlDownloader.download(requested_url)          [sole network authority]
  -> MIME gate (validate_content_type)
  -> normalize_downloaded_artifact                  [local bytes only]
  -> LightRAG ingest_markdown
  -> Milestone 3 audit snapshot
  -> terminal state (PROCESSED | SKIPPED_DUPLICATE | FAILED | FAILED_AUDIT)
n8n polls GET /v1/ingestions/{job_id} and responds to the caller
```

The webhook sends only the raw submitted URL string; it never fetches,
parses, or audits the target. All URL network activity happens inside
`agent/ingestion/url_downloader.py` in the ingestion process.

### Files introduced or modified by Milestone 4

The verified Milestone 4 commit range is `62e92e7~1..32419cf` (six commits
across Tasks 1–5 on `lightrag-ingestion-m4`); the list below is generated from
`git diff 62e92e7~1..HEAD --name-status` and contains every file in that range.

- `agent/app/config.py` — `URL_DOWNLOAD_*` limit settings.
- `agent/app/clients/pg.py` — registry reads/writes for `source_metadata` and
  nullable `content_hash`, plus the idempotent URL schema migration.
- `agent/ingestion/contracts.py` — `SourceRecord` gains `source_metadata`
  (JSONB, `default_factory=dict`) and a nullable `content_hash`.
- `agent/ingestion/docprep_adapter.py` — `normalize_downloaded_artifact`
  hands local artifact bytes to the existing parser router with canonical
  identity and download metadata.
- `agent/ingestion/migrate_url_schema.py` — executable migration entry point.
- `agent/ingestion/routes.py` — `POST /v1/ingestions` activates URL
  background processing only now that downloader and service integration both
  exist.
- `agent/ingestion/service.py` — URL submit/process/recrawl/rollback logic.
- `agent/ingestion/source_identity.py` — canonical URL identity, stable error
  codes, `build_url_source_key`.
- `agent/ingestion/url_downloader.py` — SSRF-safe downloader, MIME policy,
  limits, redirect handling, artifact hashing.
- `agent/Dockerfile.ingestion` — adds `h11` and `dnspython` for the
  pinned-transport and in-process DNS resolution; the preprocessing package
  is still installed without any optional extra (no `[docling]`).
- `data/lightrag/preprocessing_pipeline/src/lightrag_docprep/pipeline.py` —
  adds `process_local` (local artifact handoff) and suffix-based routable
  copies for extensionless downloads.
- `data/lightrag/preprocessing_pipeline/tests/test_pipeline_url.py` — new
  `process_local` tests (HTML, Markdown, never-uses-url-fetcher).
- `db/postgres/init.sql` — nullable `content_hash` and the `source_metadata`
  JSONB column in the fresh-install schema.
- `docker-compose.yml` — passes the `URL_DOWNLOAD_*` limits to the ingestion
  service.
- `.env.example` — documents the `URL_DOWNLOAD_*` limits and the webhook
  secret variable without ever assigning the secret.
- `workflows/n8n/lightrag-url-ingestion.json` — authenticated URL webhook
  workflow (shipped inactive).
- Tests: `tests/ingestion/test_api_routes.py`, `test_compose_n8n.py`,
  `test_contracts.py`, `test_docprep_adapter.py`, `test_n8n_url_workflow.py`,
  `test_registry_pg.py`, `test_service.py`, `test_url_downloader.py`,
  `test_url_schema_migration.py`.
- Task 6 (this document + static smoke):
  `scripts/smoke_lightrag_url_static.sh`,
  `docs/ingestion-pipeline-milestone-4.md`.

### Files that were not modified

- `workflows/n8n/lightrag-file-ingestion.json` is byte-for-byte pinned by
  `tests/ingestion/test_n8n_url_workflow.py` and unchanged.
- `data/lightrag/preprocessing_pipeline/src/lightrag_docprep/url_fetcher.py`
  is neither modified nor called.
- `ingestion_jobs.audit` and `ingestion_jobs.error` are not used for
  downloader provenance; provenance lives in `ingestion_sources.source_metadata`.

## Supported URL / MIME Policy

The downloader accepts only these media types after a `200` response:

| Declared media type | Decision |
|---|---|
| `text/html`, `application/xhtml+xml` | Accepted, parsed as HTML |
| `text/markdown`, `text/x-markdown` | Accepted, parsed as Markdown |
| `text/plain` | Accepted **only** when the final URL path or
  `Content-Disposition` filename has a reliable `.md` or `.markdown`
  suffix; otherwise `URL_CONTENT_TYPE_AMBIGUOUS` |
| Missing/empty/whitespace-only type, `application/octet-stream`,
  `application/markdown`, `application/x-markdown`, `text/md` | Rejected as
  `URL_CONTENT_TYPE_AMBIGUOUS` |
| Anything else (e.g. `application/pdf`, `image/png`) | Rejected as
  `URL_CONTENT_TYPE_UNSUPPORTED` |

Policy details enforced by `validate_content_type`:

- The media type is the part before the first `;`, lowercased and trimmed.
- `Content-Disposition` filename evidence accepts exact `filename=`,
  `filename*=`, quoted, unquoted, and single-quoted forms; malformed,
  reordered, or lookalike parameters (`xfilename`, `filename0`, unterminated
  quotes) do not count as evidence.
- Only HTTP `200` is accepted for the body; redirects use `301/302/303/307/308`
  and other statuses fail with `URL_HTTP_STATUS`.
- Duplicate singleton headers (`content-type`, `location`,
  `content-disposition`, `etag`, `last-modified`, `content-encoding`) are
  rejected, and `content-length` must be a single non-negative decimal digit
  string with no sign, whitespace, or absurd length.

## Canonical Identity and Metadata Semantics

### Identity

- `requested_url` is the exact accepted submitted URL before
  canonicalization (for example `https://Example.COM/Doc?x=1`).
- `canonical_url` is the normalized identity URL stored as `source_uri` and in
  the source key `url:<canonical-url>`.
- `final_url` is the URL after redirect resolution and `redirect_chain` is the
  ordered list of canonical hops. Identity never changes to a redirect
  destination.

Canonicalization rules (`canonicalize_url`):

- scheme lowercased, restricted to `http`/`https`; userinfo forbidden;
- default ports stripped, any other port rejected (`URL_PORT_FORBIDDEN`);
- host lowercased/IDNA-normalized; alternative IPv4 notations (hex, octal,
  shorthand, dword) rejected (`URL_HOST_INVALID`);
- dot-segments removed per RFC 3986 5.2.4; percent-encoding normalized
  (uppercase hex, unreserved bytes decoded);
- the query component is preserved exactly as submitted (including case,
  percent escapes, order, and repeated keys); an explicit empty query and an
  absent query canonicalize to the same identity;
- the fragment is dropped.

### `source_metadata` contract

`ingestion_sources.source_metadata` is `JSONB NOT NULL DEFAULT '{}'`. Once a
URL fetch is recorded it uses exactly these two top-level keys:

```json
{
  "active_download": null | {
    "requested_url": "string",
    "canonical_url": "string",
    "final_url": "string",
    "redirect_chain": ["string"],
    "content_type": "string",
    "content_disposition": null | "string",
    "etag": null | "string",
    "last_modified": null | "string",
    "downloaded_bytes": "integer",
    "sha256": "string",
    "raw_artifact_path": null | "string",
    "fetched_at": "string"
  },
  "latest_attempt": null | {
    "requested_url": "string",
    "canonical_url": "string",
    "final_url": null | "string",
    "redirect_chain": ["string"],
    "content_type": null | "string",
    "content_disposition": null | "string",
    "etag": null | "string",
    "last_modified": null | "string",
    "downloaded_bytes": null | "integer",
    "sha256": null | "string",
    "raw_artifact_path": null | "string",
    "fetched_at": "string",
    "job_id": "string",
    "terminal_outcome": "string",
    "error_code": null | "string"
  }
}
```

Semantics:

- `active_download` describes the currently activated fetch (or `null` when
  nothing is active, e.g. a stub or a rejected attempt).
- `latest_attempt` records the most recent fetch attempt with its job and
  terminal outcome, including failures. Failed recrawls write
  `latest_attempt` while preserving the previous `active_download`.
- `requested_url` is the raw submitted URL; `canonical_url` is the identity;
  `fetched_at` is an RFC 3339 UTC timestamp captured at fetch completion.
  Tests inject/freeze the clock (`now=` / `fetched_at=`) and never assert
  wall-clock timing.
- `etag` and `last_modified` are metadata only; no conditional GET is issued.
- URL stubs have `content_hash = NULL` until a successful activation; a
  `NULL` hash stub never collides as a duplicate. No parallel top-level
  copies of these fields are written.
- Unknown future metadata is preserved only by the repository's existing
  JSONB update conventions; no new fields are invented in this milestone.

## SSRF Trust Boundary and Limits

The downloader is the only component allowed to contact a target host, and it
assumes the target is hostile.

- DNS resolution is performed in-process with `dnspython` for both A and AAAA
  records. Every resolved address is classified; loopback, private, link-local,
  multicast, reserved, CGNAT (`100.64.0.0/10`), documentation ranges, and
  `169.254.169.254` are forbidden. Mixed public/forbidden answers fail with
  `URL_DNS_MIXED_FORBIDDEN`; all-forbidden answers fail with
  `URL_ADDRESS_FORBIDDEN`.
- A direct IP literal is validated the same way (including IPv6 and
  IPv4-mapped IPv6 forms).
- The transport connects to a numeric IP only (`H11PinnedTransport`): the
  socket address comes from the validated resolution, never from a hostname,
  so a DNS-rebinding race cannot change the connection target. TLS SNI keeps
  the original hostname.
- Every redirect hop is re-canonicalized, re-resolved, and re-validated before
  the next connection; redirect loops and too many redirects terminate with
  stable codes.
- Limits (configurable via `URL_DOWNLOAD_*`): connect timeout 10 s, read
  timeout 30 s, total deadline 120 s, max 5 redirects, 10 MiB wire and 10 MiB
  decoded limits, 64 KiB stream chunks; gzip/deflate decoding is bounded and
  malformed encodings fail. Partial artifacts are cleaned up on failure.

### Artifact lifecycle

- A download streams into a temporary `url-download-*.part` file inside
  `<INGESTION_ROOT>/url-artifacts` (`IngestionService.url_artifact_dir`).
- On success the completed `.part` file is atomically renamed to
  `<INGESTION_ROOT>/url-artifacts/<sha256-hex>` (content-addressed, no
  extension) and `raw_artifact_path` is stored in
  `source_metadata.active_download`.
- If the download itself fails before a completed artifact exists, the
  incomplete `.part` file is removed and `latest_attempt.raw_artifact_path`
  is `null`.
- If the download succeeds but parsing, normalization, LightRAG ingestion,
  storage parsing, or the audit later fails, the completed content-addressed
  artifact remains on disk. In those post-download failure cases its path is
  recorded only in `source_metadata.latest_attempt.raw_artifact_path`, and it
  is not activated under `source_metadata.active_download`.
- Completed artifacts from both successful activations and post-download
  failed attempts have **no** automatic retention expiry or garbage
  collection in this milestone; operator-side cleanup of `url-artifacts` is
  an explicit residual operational consideration.

Stable public error codes (`PUBLIC_CODES` in `test_url_downloader.py`):
`URL_INVALID`, `URL_UNSUPPORTED_SCHEME`, `URL_CREDENTIALS_FORBIDDEN`,
`URL_HOST_INVALID`, `URL_PORT_FORBIDDEN`, `URL_ADDRESS_FORBIDDEN`,
`URL_DNS_NO_ANSWER`, `URL_DNS_RESOLUTION_FAILED`, `URL_DNS_MIXED_FORBIDDEN`,
`URL_REDIRECT_LOCATION_MISSING`, `URL_REDIRECT_LOOP`, `URL_REDIRECT_LIMIT`,
`URL_TIMEOUT`, `URL_DOWNLOAD_TOO_LARGE`, `URL_DECOMPRESSION_LIMIT`,
`URL_HTTP_STATUS`, `URL_CONTENT_TYPE_UNSUPPORTED`,
`URL_CONTENT_TYPE_AMBIGUOUS`, `URL_CONTENT_ENCODING_UNSUPPORTED`,
`URL_CONTENT_LENGTH_INVALID`, `URL_TLS_FAILED`, `URL_CONNECTION_FAILED`.
Error messages exposed to callers are generic and sanitized (never contain
raw filesystem paths, sockets, or target internals).

## n8n Credential Provisioning

The URL webhook uses n8n **Header Auth** with header
`X-Polyphemus-Ingestion-Secret`. The workflow ships inactive and the secret is
never stored in `.env`, `.env.example`, `docker-compose.yml`, or the workflow
JSON (a compose test asserts no service receives the variable).

Operator steps (manual, per `.env.example`):

1. Generate a strong random value, e.g. `openssl rand -hex 32`. Hold it only
   in your shell or a password manager; do not commit it.
2. In n8n, open **Credentials -> New credential -> Header Auth**.
   - Credential name: `Polyphemus URL Ingestion Secret`
   - Name: `X-Polyphemus-Ingestion-Secret`
   - Value: the generated secret
   n8n stores it in its encrypted credential store.
3. In n8n, import `workflows/n8n/lightrag-url-ingestion.json`.
4. Open the **URL Ingestion Webhook** node and attach the credential. If n8n
   reports the credential as missing after import, re-select it.
5. Activate the workflow (manual operator action; automation of credential
   creation or workflow activation is intentionally out of scope).

The workflow contains only native n8n base nodes (17 total): a
`webhook` (Header Auth), native `if` gates for URL field validation,
response status, job-id validity, body validity, terminal-state and
duplicate/error routing, a `wait` poll timer, `httpRequest` nodes that only
POST the raw URL and GET the job status, and `respondToWebhook` responders.
There is no HTTP request node that fetches the target URL, no parser/audit
node, and no downloader logic.

## Terminal-State Behavior

`GET /v1/ingestions/{job_id}` returns the job row; n8n treats
`PROCESSED`, `SKIPPED_DUPLICATE`, `FAILED`, and `FAILED_AUDIT` as terminal.

- `PROCESSED`: download, normalization, LightRAG ingestion, and a clean audit
  all succeeded; `content_hash` and `lightrag_document_id` are set,
  `active_download` is populated.
- `SKIPPED_DUPLICATE`: an active URL recrawled with unchanged content — no
  normalization/ingest/audit runs; fetch/provenance metadata is refreshed
  while the source record stays active. A brand-new URL whose content hash
  matches an existing processed source also skips and reuses the owner
  document.
- `FAILED`: download, parse, normalization, or LightRAG ingestion failed;
  `content_hash` stays `NULL`, `active_download` is cleared (or preserved for
  a failed recrawl), and the job carries a sanitized `error` with a stable
  code and stage.
- `FAILED_AUDIT`: the Milestone 3 audit found critical issues; the candidate
  is never activated — `content_hash` stays `NULL` and `active_download` is
  cleared, and the job carries the full audit report plus an
  `AUDIT_FAILED` error. Warnings alone never block processing.

### Sanitized example job responses (generated from the test fixtures)

Each example below is traceable to one exact deterministic test in
`tests/ingestion/test_service.py` and uses the exact job-dict shape returned
by `GET /v1/ingestions/{job_id}` (eight fields: `job_id`, `source_key`,
`source_uri`, `status`, `content_hash`, `lightrag_document_id`, `audit`,
`error`). No values are invented; every field comes from that test's
fixture.

```text
--- PROCESSED ---
{
  "audit": {
    "checked_at": "2024-01-01T00:00:00Z",
    "critical_issues": [],
    "job_id": "job-url-1",
    "merge_candidates": [],
    "source_key": "url:https://example.com/doc",
    "warnings": []
  },
  "content_hash": "sha-abc",
  "error": null,
  "job_id": "job-url-1",
  "lightrag_document_id": "doc-url",
  "source_key": "url:https://example.com/doc",
  "source_uri": "https://example.com/doc",
  "status": "PROCESSED"
}
```

Produced by
`tests/ingestion/test_service.py::test_url_job_success_reaches_audit_and_processed`.

```text
--- SKIPPED_DUPLICATE ---
{
  "audit": null,
  "content_hash": "old-hash",
  "error": null,
  "job_id": "job-url-1",
  "lightrag_document_id": "doc-old",
  "source_key": "url:https://example.com/doc",
  "source_uri": "https://example.com/doc",
  "status": "SKIPPED_DUPLICATE"
}
```

Produced by
`tests/ingestion/test_service.py::test_url_same_url_unchanged_content_skips_and_refreshes_metadata`.

```text
--- FAILED ---
{
  "audit": null,
  "content_hash": null,
  "error": {
    "code": "URL_CONTENT_TYPE_UNSUPPORTED",
    "message": "URL download failed",
    "stage": "PROCESSING"
  },
  "job_id": "job-url-1",
  "lightrag_document_id": null,
  "source_key": "url:https://example.com/doc",
  "source_uri": "https://example.com/doc",
  "status": "FAILED"
}
```

Produced by
`tests/ingestion/test_service.py::test_url_download_failure_reaches_failed_with_sanitized_error[URL_CONTENT_TYPE_UNSUPPORTED]`
(a new-URL download failure: the stub keeps `content_hash` NULL and no
LightRAG document; the error payload is the exact
`IngestionError(code, message, stage)` model dump).

```text
--- FAILED_AUDIT ---
{
  "audit": {
    "checked_at": "2024-01-01T00:00:00Z",
    "critical_issues": [
      {
        "code": "CRIT",
        "evidence": {},
        "message": "critical problem",
        "severity": "critical"
      }
    ],
    "job_id": "job-url-1",
    "merge_candidates": [],
    "source_key": "url:https://example.com/doc",
    "warnings": []
  },
  "content_hash": null,
  "error": {
    "code": "AUDIT_FAILED",
    "message": "Post-ingestion audit found critical issues",
    "stage": "AUDITING"
  },
  "job_id": "job-url-1",
  "lightrag_document_id": "doc-url",
  "source_key": "url:https://example.com/doc",
  "source_uri": "https://example.com/doc",
  "status": "FAILED_AUDIT"
}
```

Produced by
`tests/ingestion/test_service.py::test_url_job_critical_audit_reaches_failed_audit`.

## Rollback and Audit Guarantees

- An already-active URL (`PROCESSED` with a non-null hash) is recrawled as a
  candidate: the active record is never overwritten before the candidate
  passes a clean audit. On update, the old LightRAG document is deleted, the
  new version is ingested, and the audit must be clean before the candidate is
  activated.
- If update ingestion or audit fails, the previous normalized artifacts are
  restored, the rejected candidate document is deleted, the previous
  `active_download` metadata is preserved, and the job ends `FAILED` or
  `FAILED_AUDIT`. If rollback itself fails, the audit error is kept and the
  job reports `UPDATE_ROLLBACK_FAILED`; the previous active record is still
  never clobbered by a failed candidate.
- The audit is the same non-destructive Milestone 3 snapshot audit: critical
  issues block activation (`FAILED_AUDIT`), warnings do not block
  (`PROCESSED`).

## Verification

### Static smoke (deterministic, non-credit)

```bash
sh scripts/smoke_lightrag_url_static.sh
```

The script runs fixed pytest selections that use fake resolvers/transports and
mocked downstreams (docprep, LightRAG, audit, PostgreSQL). It makes no
localhost socket, DNS, external HTTP, Docker, LightRAG, or LLM call, and it
stops at the first failing group. Real output from this checkout:

```text
== HTML download via fake resolver/transport ==
.                                                                        [100%]
1 passed in 0.05s
== Markdown download + exact MIME policy via fakes ==
....................                                                     [100%]
20 passed in 0.07s
== New HTML URL job -> audit -> PROCESSED (mocked downstreams) ==
.                                                                        [100%]
1 passed in 0.11s
== Unchanged URL recrawl -> SKIPPED_DUPLICATE (mocked downstreams) ==
.                                                                        [100%]
1 passed in 0.12s
== Changed URL recrawl -> update -> PROCESSED (mocked downstreams) ==
.                                                                        [100%]
1 passed in 0.12s
== Download failure -> FAILED with sanitized error (mocked downstreams) ==
..                                                                       [100%]
2 passed in 0.11s
== Critical audit -> FAILED_AUDIT (mocked downstreams) ==
.                                                                        [100%]
1 passed in 0.11s
== n8n URL workflow: native Header Auth + orchestration only ==
..................                                                       [100%]
18 passed in 0.69s

Static URL smoke test passed: HTML, Markdown, duplicate, update, FAILED, FAILED_AUDIT, n8n auth
```

Shell syntax check:

```bash
sh -n scripts/smoke_lightrag_url_static.sh
```

`sh -n` prints nothing on success. Result: exit status 0, stdout: empty,
stderr: empty.

### Focused URL verification

Portable runbook — resolve one repository interpreter once and reuse it in
every command below. Set `PY` to a repository interpreter that has pytest and
the preprocessing package installed (for example `<repo>/.venv/bin/python`):

```bash
ABSOLUTE_PY="$(readlink -f "$PY")"

"$ABSOLUTE_PY" -m pytest tests/ingestion/test_url_downloader.py -q
"$ABSOLUTE_PY" -m pytest tests/ingestion/test_contracts.py -q
"$ABSOLUTE_PY" -m pytest tests/ingestion/test_n8n_url_workflow.py -q
"$ABSOLUTE_PY" -m pytest tests/ingestion/test_url_schema_migration.py -q
"$ABSOLUTE_PY" -m pytest tests/ingestion/test_service.py -k url -q
```

Recorded evidence below was captured in this verification environment with the
interpreter `/home/alelxsalc03/Desktop/polyphemus/.venv/bin/python`; reruns
should use the portable `$ABSOLUTE_PY` above. Real output, each file shown
separately:

```text
$ /home/alelxsalc03/Desktop/polyphemus/.venv/bin/python -m pytest tests/ingestion/test_url_downloader.py -q
........................................................................ [ 52%]
.................................................................        [100%]
137 passed in 0.13s

$ /home/alelxsalc03/Desktop/polyphemus/.venv/bin/python -m pytest tests/ingestion/test_contracts.py -q
............................................                             [100%]
44 passed in 0.04s

$ /home/alelxsalc03/Desktop/polyphemus/.venv/bin/python -m pytest tests/ingestion/test_n8n_url_workflow.py -q
..................                                                       [100%]
18 passed in 0.70s

$ /home/alelxsalc03/Desktop/polyphemus/.venv/bin/python -m pytest tests/ingestion/test_url_schema_migration.py -q
....                                                                     [100%]
4 passed in 0.06s

$ /home/alelxsalc03/Desktop/polyphemus/.venv/bin/python -m pytest tests/ingestion/test_service.py -k url -q
.........................                                                [100%]
25 passed, 19 deselected in 0.14s
```

The `-k url` service selection covers new-URL submission, canonicalization,
HTML/Markdown source-type mapping, download/parse/normalize/ingest/audit
failures, duplicate skip, update activation, failed-audit rejection, and
recrawl metadata refresh.

### Full ingestion suite

Inside the restricted review sandbox, `pytest tests/ingestion -q` stalls the
HTML parser's `ThreadPoolExecutor` worker (a sandbox limitation, not a product
defect). The parser watchdog then fires and the run ends with:

```text
1 failed, 327 passed in 121.35s (0:02:01)

FAILED tests/ingestion/test_docprep_adapter.py::test_normalize_downloaded_artifact_reuses_existing_parsers_with_provenance[<html><body><main><h1>Guide</h1><p>Useful body.</p></main></body></html>-html-html]
result = PreprocessResult(success=False, warnings=['html timed out after 120s',
'docling unavailable; trying fallback'], error='docling unavailable; trying fallback')
```

Reading that result correctly:

- the HTML parser is built on BeautifulSoup/Markdown conversion and does not
  require Docling;
- `html timed out after 120s` is the first, root observation: the sandbox
  stalls the parser's `ThreadPoolExecutor` until the watchdog fires;
- only after the HTML parser times out does the existing parser router try its
  pre-existing optional Docling fallback, which then reports
  `docling unavailable; trying fallback`;
- Docling is unavailable because it is not installed by the repository's
  normal package installation or ingestion-image configuration
  (`agent/Dockerfile.ingestion` installs the preprocessing package without the
  `[docling]` extra); missing Docling is not the root cause and Docling is not
  a Milestone 4 dependency — PDF and all non-HTML/Markdown formats remain
  deferred;
- no dependency was installed to hide the sandbox issue; the identical command
  was instead rerun once outside the sandbox with the same interpreter and no
  Docling.

Fresh real output of the full suite outside the sandbox, same interpreter, no
Docling:

```text
........................................................................ [ 21%]
........................................................................ [ 43%]
........................................................................ [ 65%]
........................................................................ [ 87%]
........................................                                 [100%]
328 passed in 1.20s
```

Fresh real output of the full vendored preprocessing suite outside the
sandbox, same interpreter, no Docling:

```text
........................................................................ [ 91%]
.......                                                                  [100%]
79 passed in 1.75s
```

Compose validation (parses the compose file; starts no containers):

```bash
docker compose --env-file .env.example --profile lightrag config --quiet
```

`docker compose config --quiet` prints nothing on success. Result: exit status
0, stdout: empty, stderr: empty.

## Manual Approval-Gated Live-URL Procedure

This procedure performs a real network fetch and spends real ingestion/LLM
work; it requires explicit operator approval and is **not** run by CI or by
the static smoke.

Prerequisites:

1. The compose stack (`docker compose --profile lightrag up -d`) is healthy,
   including PostgreSQL, ingestion, n8n, and LightRAG.
2. The n8n Header Auth credential exists and is attached to the
   `URL Ingestion Webhook` node; the workflow is activated.
3. The target URL is operator-approved and matches scope (http/https, default
   port, HTML or Markdown, no authentication required).

Steps:

```bash
# 1. POST the URL through the authenticated webhook (or directly to the API):
curl -sS -X POST 'http://127.0.0.1:5678/webhook/url-ingestions' \
  -H 'Content-Type: application/json' \
  -H 'X-Polyphemus-Ingestion-Secret: <secret>' \
  -d '{"url":"https://example.com/document"}'

# 2. Poll the job until a terminal status (ingestion API host port is
#    INGESTION_PORT, default 8081):
curl -sS http://127.0.0.1:8081/v1/ingestions/<job_id>

# 3. Inspect the source row and metadata:
docker compose --env-file .env --profile lightrag exec -T postgres \
  psql -U polymerhus -d polymerhus \
  -c "select source_key, status, content_hash, lightrag_document_id,
             source_metadata
      from ingestion_sources
      where source_key = 'url:https://example.com/document';"
```

Expected terminal outcomes are `PROCESSED`, `SKIPPED_DUPLICATE`, `FAILED`, or
`FAILED_AUDIT` as documented above. Do not run this procedure against private,
metadata, or unauthorized hosts; the downloader will refuse those anyway.

## Live Schema Inspection Status

Live PostgreSQL inspection is **NOT EXECUTED**: starting or mutating a database
merely for evidence is out of scope, and live schema inspection was not
explicitly authorized for this checkpoint. The nullable `content_hash` and
`source_metadata` contract is instead verified deterministically by the schema
migration tests (recorded below with the interpreter used in this verification
environment, `/home/alelxsalc03/Desktop/polyphemus/.venv/bin/python`):

```text
$ /home/alelxsalc03/Desktop/polyphemus/.venv/bin/python -m pytest tests/ingestion/test_url_schema_migration.py -q
....                                                                     [100%]
4 passed in 0.06s
```

Those tests pin the exact migration SQL:

```sql
ALTER TABLE ingestion_sources ADD COLUMN IF NOT EXISTS source_metadata JSONB NOT NULL DEFAULT '{}';
ALTER TABLE ingestion_sources ALTER COLUMN content_hash DROP NOT NULL;
```

and assert the migration contains no destructive statements and is idempotent,
so an existing `pg-data` volume can be migrated without deletion or recreation.

## Residual Risks and Deferred Items

- background tasks remain inside one FastAPI process; no durable queue/retry;
- no conditional GET; ETag/Last-Modified are metadata only;
- no authenticated targets, proxies, cookies, browser rendering, crawling,
  sitemap expansion or non-default public ports;
- URL raw artifacts under `<INGESTION_ROOT>/url-artifacts` (successful
  activations and post-download failed attempts alike) are retained with no
  automatic retention period or garbage collection; cleanup is an explicit
  operator responsibility;
- PDF and non-HTML/Markdown formats remain deferred.
