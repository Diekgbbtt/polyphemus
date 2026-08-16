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
  ports;
- agent query integration is explicitly out of scope: Milestone 4 delivers
  secure URL ingestion only, with no retrieval/query wiring into the agent;
- PDF and Docling remain out of scope; PDF and every non-HTML/Markdown format
  are deferred, and Docling is not installed or required.

## Feature Scope and Architecture

### Request flow

```text
n8n webhook (Header Auth, X-Polyphemus-Ingestion-Secret)
  -> Validate body.url field (native IF; item shape {"body":{"url":"<raw url>"}})
  -> POST /v1/ingestions {"source_kind":"url","source_uri":"<trimmed body.url>"}
       (FastAPI create_ingestion)
  -> service.submit: canonicalize -> build_url_source_key
     -> null-hash stub + DISCOVERED job
  -> FastAPI BackgroundTasks -> service.process_job(job_id, requested_url)
  -> UrlDownloader.download(requested_url)          [sole network authority]
  -> MIME gate (validate_content_type)
  -> normalize_downloaded_artifact                  [local bytes only]
  -> LightRAG ingest_markdown (new URL, or staged candidate for an update)
  -> Milestone 3 audit snapshot of the exact ingested document
  -> terminal state (PROCESSED | SKIPPED_DUPLICATE | FAILED | FAILED_AUDIT)
n8n polls GET /v1/ingestions/{job_id} and responds to the caller
```

The webhook reads only `body.url` from the incoming item and sends the
validated trimmed string value to the backend as a native JSON object; it
never canonicalizes the URL, never fetches, parses, or audits the target, and
never relays backend error bodies. All URL network activity happens inside
`agent/ingestion/url_downloader.py` in the ingestion process.

### Files introduced or modified by Milestone 4

The fixed Milestone 4 base is `7db35f4` (the commit that fixed the docprep
executor-shutdown hang). The original seven-commit feature checkpoint spans
`62e92e7..242622f`; this remediation adds a further corrective pass on top, so
the final range is not the old checkpoint. Review the complete milestone with:

```sh
git diff 7db35f4
```

`git diff 7db35f4` compares the fixed base against the working tree, so it
includes this uncommitted remediation in addition to the committed checkpoint.
The original seven-commit checkpoint (`242622f`) and the final remediated
working tree are deliberately distinguished: `242622f` is the pre-remediation
state, while the working tree is the reviewed state after this corrective
pass. The list below is the Milestone 4 file set; no self-referential SHA for
the commit containing this document is embedded.

- `agent/app/config.py` — `URL_DOWNLOAD_*` limit settings.
- `agent/app/clients/pg.py` — registry reads/writes for `source_metadata` and
  nullable `content_hash`, plus the idempotent URL schema migration.
- `agent/ingestion/app.py` — startup hook that runs the idempotent URL schema
  migration before the ingestion application accepts traffic.
- `agent/ingestion/contracts.py` — `SourceRecord` gains `source_metadata`
  (JSONB, `default_factory=dict`) and a nullable `content_hash`.
- `agent/ingestion/docprep_adapter.py` — `normalize_downloaded_artifact`
  hands local artifact bytes to the existing parser router with canonical
  identity and download metadata.
- `agent/ingestion/lightrag_adapter.py` — strict document-ID extraction for
  ingested candidates (missing/blank/non-string IDs fail sanitized).
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
  `test_lightrag_adapter.py`, `test_registry_pg.py`, `test_service.py`,
  `test_url_downloader.py`, `test_url_schema_migration.py`.
- Task 6 (this document + static smoke):
  `scripts/smoke_lightrag_url_static.sh`,
  `docs/ingestion-pipeline-milestone-4.md`.

### Files that were not modified

- `workflows/n8n/lightrag-file-ingestion.json` is byte-for-byte pinned by
  `tests/ingestion/test_n8n_url_workflow.py` and unchanged.
- `data/lightrag/preprocessing_pipeline/src/lightrag_docprep/url_fetcher.py`
  is not imported or called by the new Milestone 4 ingestion path. Legacy
  `DocumentPreprocessor.process_url` and its CLI may still use the old
  fetcher, so no repository-wide "unused" claim is made.
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
  suffix and trustworthy URL/disposition evidence does not conflict;
  otherwise `URL_CONTENT_TYPE_AMBIGUOUS` |
| Missing/empty/whitespace-only type, `application/octet-stream`,
  `application/markdown`, `application/x-markdown`, `text/md` | Rejected as
  `URL_CONTENT_TYPE_AMBIGUOUS` |
| Anything else (e.g. `application/pdf`, `image/png`) | Rejected as
  `URL_CONTENT_TYPE_UNSUPPORTED` |

Policy details enforced by `validate_content_type`:

- The media type is the part before the first `;`, lowercased and trimmed.
- `Content-Disposition` filename evidence matches exact parameter boundaries
  only, and every exact `filename` and `filename*` parameter is inspected so
  the result does not depend on parameter order. An ordinary `filename=`
  value is accepted only when syntactically valid under the existing
  conservative parser (quoted, single-quoted, or unquoted). An extended
  `filename*=` value is evidence only when it is a strict RFC 5987/6266
  value: unquoted, exactly
  `charset'language'value`, UTF-8-only charset (case-insensitive), language
  empty or an alphanumeric/hyphen tag, every `%` followed by exactly two hex
  digits, the percent-decoded bytes valid UTF-8, and the decoded filename
  non-empty and free of decoded Unicode control characters (including
  percent-encoded C1 controls such as U+0085). Malformed values
  (`filename*=page.md`, `%ZZ`, incomplete escapes, unknown charsets, invalid
  UTF-8, quoted `filename*`, empty values, near-match parameter names such
  as `xfilename*`/`filename*0`), conflicting `filename`/`filename*` values,
  or any control-containing evidence make the text/plain disposition
  unreliable and yield `URL_CONTENT_TYPE_AMBIGUOUS`; a malformed extended
  value is never masked by a valid plain `filename`. The filename is suffix
  evidence only — it never becomes a filesystem path.
- `text/plain` filename evidence from the final URL path and from
  `Content-Disposition` is compared as a whole: the URL basename is
  percent-decoded strictly and a decoded Unicode control character (for
  example percent-encoded U+0085 as `%C2%85`, or NUL/ESC) makes that URL
  filename unusable as evidence. When both a trustworthy URL filename
  (an explicit extension) and a trustworthy `Content-Disposition` filename
  exist but disagree about the Markdown suffix (for example `.md` URL plus a
  non-Markdown disposition filename, or the reverse), the response is
  `URL_CONTENT_TYPE_AMBIGUOUS` regardless of parameter order. Standard
  `Content-Type` parameters such as `charset` do not change the media-type
  decision; byte sniffing is never performed.
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
- percent-encoding normalized first (uppercase hex, unreserved bytes decoded),
  then dot-segments removed per RFC 3986 5.2.4, so an encoded `.`/`..`
  segment (`%2e`, `%2e%2e`, mixed case) behaves exactly like its decoded
  equivalent on the first pass; encoded reserved separators such as `%2F`
  are never decoded into path separators;
- canonicalization is idempotent:
  `canonicalize_url(canonicalize_url(x)) == canonicalize_url(x)`, and the
  stored `source_uri` is always the same value used to derive `source_key`;
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
- A cross-URL duplicate (a distinct URL whose downloaded bytes match an
  existing processed source) keeps `content_hash = NULL` and
  `active_download = null`; the candidate SHA-256 and `SKIPPED_DUPLICATE`
  outcome are recorded only in `latest_attempt`, and no parser,
  normalized-artifact, or LightRAG activation fields are copied from the
  owner. When a previously failed record is retried and reclassified as a
  duplicate, its own stale parser, normalized-artifact, LightRAG, and error
  fields are cleared so no field implies its candidate was activated. The
  distinct canonical source key/source URI are preserved and the existing
  processed owner is never modified.
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

## URL Schema Migration

The Milestone 4 schema adds `source_metadata JSONB NOT NULL DEFAULT '{}'` and
drops `NOT NULL` from `content_hash`. Fresh databases already receive both
changes through `db/postgres/init.sql`; existing `pg-data` volumes are
migrated automatically.

Automatic startup migration:

- The ingestion application (`agent/ingestion/app.py`) runs the existing
  idempotent migration in its FastAPI startup hook, following the repository's
  existing `@app.on_event("startup")` convention. The migration executes
  before the application becomes ready to accept traffic: if it fails,
  startup/readiness fails and the Compose healthcheck keeps the service
  unhealthy.
- Importing `agent.ingestion.app` never runs the migration; only application
  startup does.
- Repeated startup is safe: each statement is a no-op when the schema is
  already migrated (`ADD COLUMN IF NOT EXISTS` / `DROP NOT NULL`), and the
  migration contains no destructive operations.
- The Compose image already starts `uvicorn agent.ingestion.app:app`, so the
  Compose/startup configuration reaches this path with no Compose change.

Standalone manual recovery/upgrade command (unchanged):

```sh
python -m agent.ingestion.migrate_url_schema
```

Existing-volume upgrade behavior: an operator with an old `pg-data` volume
can either let the startup hook migrate on the next ingestion-service start,
or run the standalone command explicitly against the same
`POSTGRES_DSN` before starting the service. Either way the migration is
idempotent and non-destructive; explicit pre-traffic verification is to run
the standalone command first and confirm its success message before
submitting any URL job.

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

The workflow contains only native n8n base nodes (18 total): a
`webhook` (Header Auth), native `if` gates for `body.url` validation,
response status, job-id validity, body validity, terminal-state and
duplicate/error routing, a `wait` poll timer, `httpRequest` nodes that only
POST the trimmed URL and GET the job status, and `respondToWebhook` responders
(fixed pre-polling failures and a trusted-ID-only polling failure responder).
There is no HTTP request node that fetches the target URL, no parser/audit
node, and no downloader logic.

The webhook item shape is `{"body": {"url": "<url>"}}`. Validation requires
exactly that `body.url` exists, is a string, and has a non-empty trim; the
POST body is built as a native object expression
(`{"source_kind": "url", "source_uri": $json.body.url.trim()}`), never by
interpolating the URL inside quoted JSON text, so quotes, backslashes,
braces, commas, newlines, or JSON-like URL text always remain one string
value and `source_kind` can never be altered. The backend owns URL
validation and receives exactly the trimmed submitted value. The initial
successful POST `job_id` is validated as a canonical lowercase UUID
(8-4-4-4-12 hexadecimal groups) before it is placed into any polling URL,
retained as trusted state, or reflected; any other value (URL, filesystem
path, secret-looking string, object, array, whitespace, empty, oversized, or
non-canonical case) reaches a fixed sanitized error response with no
`job_id`. Error responses never relay the backend body, error JSON, stack
traces, or URLs with query strings: pre-polling failures (invalid input,
POST rejection, POST transport errors, invalid initial job ID) return a
fully fixed payload with no `job_id`, and post-polling failures (GET
transport errors, malformed bodies, unrecognized statuses) return only the
previously validated trusted polling `job_id` with a fixed status/error.
Terminal success/failure responses return only the validated `job_id` and
`status` scalars. The poll loop keeps the submitted `job_id` on the polling
item for identity validation, and a later hostile GET error body can never
replace that trusted ID.

## Terminal-State Behavior

`GET /v1/ingestions/{job_id}` returns the job row; n8n treats
`PROCESSED`, `SKIPPED_DUPLICATE`, `FAILED`, and `FAILED_AUDIT` as terminal.

- `PROCESSED`: download, normalization, LightRAG ingestion, and a clean audit
  all succeeded; `content_hash` and `lightrag_document_id` are set,
  `active_download` is populated.
- `SKIPPED_DUPLICATE`: an active URL recrawled with unchanged content — no
  normalization/ingest/audit runs; fetch/provenance metadata is refreshed
  while the source record stays active. A brand-new URL whose downloaded
  bytes match an existing processed source also skips, but it does not reuse
  or copy the owner document: its own record keeps `content_hash = NULL`,
  `active_download = null`, and records the candidate SHA plus the duplicate
  outcome in `latest_attempt` only.
- `FAILED`: download, parse, normalization, or LightRAG ingestion failed;
  `content_hash` stays `NULL`, `active_download` is cleared (or preserved for
  a failed recrawl), and the job carries a sanitized `error` with a stable
  code and stage.
- `FAILED_AUDIT`: the Milestone 3 audit found critical issues; the candidate
  is never activated — `content_hash` stays `NULL` and `active_download` is
  cleared, every parser/normalized-artifact/LightRAG activation field stays
  null, the rejected candidate LightRAG document is deleted when its ID is
  known, and the job carries the full audit report plus an `AUDIT_FAILED`
  error (or the stable `UPDATE_ROLLBACK_FAILED` cleanup code when candidate
  deletion fails). Warnings alone never block processing.

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
  "lightrag_document_id": null,
  "source_key": "url:https://example.com/doc",
  "source_uri": "https://example.com/doc",
  "status": "FAILED_AUDIT"
}
```

Produced by
`tests/ingestion/test_service.py::test_url_job_critical_audit_reaches_failed_audit`.

## Rollback and Audit Guarantees

- A brand-new URL is activated atomically through the audit. Before a clean
  audit the persisted source keeps `content_hash = NULL`,
  `active_download = null`, and null parser/normalized-artifact/LightRAG
  fields; the candidate document ID and parser information exist only in
  job-local memory, and the rejected/attempt provenance is recorded only in
  `latest_attempt`. On a clean audit the hash, artifact paths, parser
  information, LightRAG document ID, `active_download`, and `PROCESSED`
  status are written together in the final activation write. On a critical
  audit the rejected candidate document is deleted (when its ID is known)
  and the sanitized `FAILED_AUDIT` source state keeps every
  activation-derived field null. If candidate deletion itself fails, the job
  terminalizes `FAILED_AUDIT` conservatively with the stable
  `UPDATE_ROLLBACK_FAILED` code and the sanitized "Candidate cleanup failed"
  message; the server-side log carries the detail.
- A changed same-URL update is staged. The old registry record, normalized
  artifact, active metadata, hash, and LightRAG document identity are all
  preserved while the candidate is downloaded and normalized. Candidate
  normalization writes into a unique per-run staging directory, so it can
  never overwrite the active normalized artifact even when different raw
  bytes normalize to the same output identity; incomplete staging output is
  removed on failure. The candidate is then ingested under a distinct staging
  identity (a different `source_key`, which changes the adapter's upload
  filename and therefore the LightRAG document), so it coexists with the old
  document. Before audit, delete, or activation the candidate LightRAG
  document ID must be a non-empty string different from the active old ID;
  a missing or conflicting ID is a stable sanitized `FAILED` that never
  deletes the old document.
- The audit always runs on the exact ingested candidate, before the old
  document is touched. The old LightRAG document is deleted only after the
  candidate audit is clean, and the registry switches activation to the
  candidate only then (`PROCESSED`, candidate hash and `active_download`
  persisted).
- If the candidate audit is critical, only the candidate is deleted/cleaned;
  the old LightRAG document stays untouched, the old registry activation is
  kept, the job terminalizes `FAILED_AUDIT`, and the rejected-candidate
  provenance is recorded only in `latest_attempt`.
- A failure before candidate ingestion leaves the old document untouched. A
  failure after candidate ingestion but before activation attempts candidate
  cleanup while the old document remains active. Any failure after
  old-document deletion begins — including a delete call that completes
  remotely and then raises, leaving the remote outcome ambiguous — or during
  final persistence triggers update-aware compensation: the preserved old
  normalized artifact is re-ingested, the old registry state is restored, and
  the job terminalizes `FAILED`. If compensation itself fails (for example a
  failed candidate cleanup, a missing previous artifact, or a failed
  restore), the stable `UPDATE_ROLLBACK_FAILED` code is used.
- Unexpected `Exception`s (not `BaseException`) inside either URL background
  worker are caught by a final stage-aware boundary. Expected errors keep
  their existing stable codes; unexpected errors use the single generic
  `INTERNAL_PROCESSING_FAILED` code with the fixed public message
  "Internal processing failed". Raw exception text, paths, URLs, response
  bodies, SQL, sockets, and audit internals are never stored in the public
  error payload; the server-side log carries the traceback. New URL jobs make
  a best-effort transition to `FAILED`, and update jobs run compensation
  whenever candidate/old side effects have begun. If PostgreSQL itself is
  unavailable so no terminal state can be persisted, the worker logs the
  outage clearly and the exception propagates — a job that cannot be
  persisted is never falsely claimed terminalized. That database-outage
  residual is the unavoidable boundary documented here.
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
== Strict RFC 5987 filename* evidence via fakes ==
................                                                         [100%]
16 passed in 0.06s
== Deterministic MIME evidence: conflicts and controls ==
.................                                                        [100%]
17 passed in 0.06s
== Idempotent canonical identity incl. encoded dot segments ==
...........                                                              [100%]
11 passed in 0.13s
== New HTML URL job -> audit -> PROCESSED (mocked downstreams) ==
.                                                                        [100%]
1 passed in 0.12s
== Unchanged URL recrawl -> SKIPPED_DUPLICATE (mocked downstreams) ==
.                                                                        [100%]
1 passed in 0.12s
== Cross-URL duplicate -> null hash/activation (mocked downstreams) ==
.                                                                        [100%]
1 passed in 0.11s
== Changed URL recrawl -> staged audit-before-delete -> PROCESSED (mocked downstreams) ==
.                                                                        [100%]
1 passed in 0.12s
== Download failure -> FAILED with sanitized error (mocked downstreams) ==
..                                                                       [100%]
2 passed in 0.12s
== Critical audit -> FAILED_AUDIT (mocked downstreams) ==
.....                                                                    [100%]
5 passed in 0.12s
== Unexpected background failure boundary -> FAILED (mocked downstreams) ==
..                                                                       [100%]
2 passed in 0.12s
== n8n URL workflow: native Header Auth + orchestration only ==
..........................                                               [100%]
26 passed in 1.29s
== URL schema migration gate at application startup ==
...                                                                      [100%]
3 passed, 2 warnings in 0.22s

Static URL smoke test passed: HTML, Markdown, strict filename*, MIME conflicts/controls, idempotent canonical identity, duplicate, staged update, atomic new-URL audit, unexpected-failure boundary, FAILED, FAILED_AUDIT, migration gate, n8n auth
```

The migration-gate group prints the repository's existing `on_event`
deprecation warning (the same startup convention used by the main agent
application); it is a warning, not a failure.

Shell syntax check:

```bash
sh -n scripts/smoke_lightrag_url_static.sh
```

`sh -n` prints nothing on success: exit status 0, stdout empty, stderr empty.
`dash -n scripts/smoke_lightrag_url_static.sh` behaves identically.

### Focused URL verification

Portable runbook — resolve one repository interpreter once and reuse it in
every command below. Set `PY` to a repository interpreter that has pytest and
the preprocessing package installed (for example `<repo>/.venv/bin/python`):

```bash
# Do NOT use `readlink -f "$PY"`: it resolves the venv symlink to the system
# interpreter. Preserve the venv entry-point path while making it absolute.
PY_DIR="$(cd "$(dirname "$PY")" && pwd -P)"
ABSOLUTE_PY="$PY_DIR/$(basename "$PY")"

"$ABSOLUTE_PY" -m pytest --version
"$ABSOLUTE_PY" -m pytest tests/ingestion/test_url_downloader.py -q
"$ABSOLUTE_PY" -m pytest tests/ingestion/test_contracts.py -q
"$ABSOLUTE_PY" -m pytest tests/ingestion/test_n8n_url_workflow.py -q
"$ABSOLUTE_PY" -m pytest tests/ingestion/test_url_schema_migration.py -q
"$ABSOLUTE_PY" -m pytest tests/ingestion/test_service.py -k url -q
```

Recorded evidence below was captured in this verification environment with the
interpreter `/home/alelxsalc03/Desktop/polyphemus/.venv/bin/python`; reruns
should use the portable `$ABSOLUTE_PY` above. Real output, each command shown
with its recorded output:

Command:

```sh
"$PY" -m pytest tests/ingestion/test_url_downloader.py -q
```

Recorded output:

```text
........................................................................ [ 36%]
........................................................................ [ 73%]
...................................................                      [100%]
195 passed in 0.15s
```

Command:

```sh
"$PY" -m pytest tests/ingestion/test_contracts.py -q
```

Recorded output:

```text
......................................................                   [100%]
54 passed in 0.04s
```

Command:

```sh
"$PY" -m pytest tests/ingestion/test_n8n_url_workflow.py -q
```

Recorded output:

```text
..........................                                               [100%]
26 passed in 1.27s
```

Command:

```sh
"$PY" -m pytest tests/ingestion/test_url_schema_migration.py -q
```

Recorded output:

```text
....                                                                     [100%]
4 passed in 0.05s
```

Command:

```sh
"$PY" -m pytest tests/ingestion/test_service.py -k url -q
```

Recorded output:

```text
.................................................                        [100%]
49 passed, 20 deselected in 0.21s
```

The `-k url` service selection covers new-URL submission, canonicalization,
HTML/Markdown source-type mapping, download/parse/normalize/ingest/audit
failures, duplicate skip, atomic new-URL audit activation/rejection and
candidate cleanup, staged update activation, candidate cleanup and
compensation, unexpected-failure boundaries, failed-audit rejection, and
recrawl metadata refresh.

### Full ingestion suite

The restricted review sandbox blocks worker threads (the same
`ThreadPoolExecutor` restriction that stalls the HTML parser); both the
docprep HTML-parser test and the new application-startup tests need those
threads, so the identical `pytest tests/ingestion -q` command is run once
outside the sandbox with the same interpreter. Docling is not installed and
is not a Milestone 4 dependency: PDF and all non-HTML/Markdown formats remain
deferred.

Historical pre-remediation evidence (captured before the wait-budget
remediation commit; not re-executed for that change). Fresh real output of the
full suite outside the sandbox, same interpreter, no Docling:

```text
........................................................................ [ 16%]
........................................................................ [ 32%]
........................................................................ [ 48%]
........................................................................ [ 65%]
........................................................................ [ 81%]
........................................................................ [ 97%]
..........                                                              [100%]
442 passed, 4 warnings in 1.87s
```

Fresh real output of the full vendored preprocessing suite outside the
sandbox, same interpreter, no Docling:

```text
........................................................................ [ 91%]
.......                                                                  [100%]
79 passed in 1.78s
```

Compose validation (parses the compose file; starts no containers):

```bash
docker compose --env-file .env.example --profile lightrag config --quiet
```

`docker compose config --quiet` prints nothing on success: exit status 0,
stdout empty, stderr empty. No containers are started.

## Manual Approval-Gated Live-URL Procedure

This procedure performs a real network fetch and spends real ingestion/LLM
work; it requires explicit operator approval and is **not** run by CI or by
the static smoke.

Prerequisites:

1. Only the required services are started explicitly, and they are healthy:

   ```sh
   docker compose --env-file .env --profile lightrag \
     up -d postgres lightrag ingestion n8n
   ```
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

Command:

```sh
"$PY" -m pytest tests/ingestion/test_url_schema_migration.py -q
```

Recorded output:

```text
....                                                                     [100%]
4 passed in 0.05s
```

Those tests pin the exact migration SQL:

```sql
ALTER TABLE ingestion_sources ADD COLUMN IF NOT EXISTS source_metadata JSONB NOT NULL DEFAULT '{}';
ALTER TABLE ingestion_sources ALTER COLUMN content_hash DROP NOT NULL;
```

and assert the migration contains no destructive statements and is idempotent,
so an existing `pg-data` volume can be migrated without deletion or recreation.
The same migration now runs automatically in the ingestion application's
startup hook before traffic is accepted (see "URL Schema Migration" above);
no live database was started or mutated for this documentation.

## Ingestion Wait-Budget Configuration

The ingestion service talks to LightRAG with three separate timeout layers, and
operators should not conflate them:

- `LIGHTRAG_TIMEOUT_SECONDS` (default `30`): the per-HTTP-request timeout the
  ingestion service applies to its LightRAG API calls (document upload and each
  status poll). It is unrelated to how long document processing may take.
- `LIGHTRAG_INGESTION_TIMEOUT_SECONDS` (default `1800`): the whole-document
  polling deadline. After a successful upload, the ingestion service polls the
  document status until LightRAG reaches a recognized terminal state or this
  monotonic deadline expires. Deadline expiry is reported with the stable
  sanitized `LIGHTRAG_TIMEOUT` result; each poll sleep is capped at the
  remaining deadline.
- LightRAG's own worker ceiling, configured inside the LightRAG image rather
  than this repository: it is derived as `2 x` the role LLM timeout. With the
  current `EXTRACT_LLM_TIMEOUT` this is observed as `360` seconds. A longer
  ingestion deadline does not repair a stalled provider request: if a LightRAG
  worker times out, LightRAG itself fails the document and the ingestion
  service reports the terminal failure as the stable sanitized
  `LIGHTRAG_INGESTION_FAILED` result (`message: "LightRAG ingestion failed"`),
  never the raw LightRAG/provider/worker error text.

`LIGHTRAG_POLL_INTERVAL_SECONDS` (default `2`) controls the interval between
status polls inside the deadline window. Both new settings are finite,
strictly positive floats, and docker-compose propagates them to the ingestion
service with the defaults above.

The legacy fixed-attempt polling constructor mode (`max_poll_attempts`) is
retained only for explicit dependency-injected test usage; the production
adapter always uses the configured monotonic deadline, and providing both
limits at once is rejected.

The whole-document deadline is a soft wall-clock deadline: a status request
that has already started may finish after the deadline, and a terminal
success/failure returned by that in-flight request is accepted. No new status
request is started at or after the deadline, and a nonterminal result received
after the deadline raises `LIGHTRAG_TIMEOUT` immediately. Each poll sleep is
capped at the remaining time to the deadline.

### Wait-budget remediation verification

Executed in the isolated `fix/lightrag-ingestion-wait-budget` worktree at base
`ab925958ba0282cdf938b6f5512a5078a0c7cf69`, repository interpreter
`/home/alelxsalc03/Desktop/polyphemus/.venv/bin/python`. The focused
wait-budget and adapter suites:

```text
tests/ingestion/test_lightrag_wait_budget.py tests/ingestion/test_lightrag_adapter.py
35 passed in 0.18s
```

Fresh full ingestion suite outside the sandbox, same interpreter, after the
remediation:

```text
........................................................................ [ 15%]
........................................................................ [ 31%]
........................................................................ [ 47%]
........................................................................ [ 63%]
........................................................................ [ 78%]
........................................................................ [ 94%]
........................                                                 [100%]
460 passed, 4 warnings in 2.34s
```

The four warnings are the pre-existing FastAPI `on_event` deprecation warnings,
not new failures.

Model/provider tuning (including `EXTRACT_LLM_*`) and progress-aware polling
remain separate future work; neither is changed by this configuration.

## Accepted Residual Risks

The following risks are accepted for Milestone 4 and are **not**
implementation blockers. None of them is newly introduced by this
remediation; each is a deliberate boundary of the bounded scope.

- concurrent same-source jobs are **not** serialized; Milestone 4 adds no
  locks, queues, or per-source job serialization;
- FastAPI background work has no durable queue or retry — jobs live inside
  one process;
- a PostgreSQL outage may prevent terminal-state persistence: the worker
  logs the outage and the exception propagates, and a job that cannot be
  persisted is never falsely claimed terminalized;
- a remote LightRAG upload that completes and then fails before returning a
  document ID may leave an unidentifiable orphan document;
- remote side effects cannot always be made transactional;
- URL raw artifacts under `<INGESTION_ROOT>/url-artifacts` (successful
  activations and post-download failed attempts alike) are retained with no
  automatic retention period or garbage collection; cleanup is an explicit
  operator responsibility;
- no conditional GET; `ETag`/`Last-Modified` are metadata only;
- no live n8n runtime/import test: the workflow ships inactive and is
  verified deterministically by static workflow tests.

## Future Milestones (deferred features)

These are future work, not Milestone 4 residuals:

- PDF, Docling, and non-HTML/Markdown content formats;
- agent query integration;
- authenticated targets, proxies, cookies, browser rendering, crawling,
  sitemap expansion, and non-default public ports.
