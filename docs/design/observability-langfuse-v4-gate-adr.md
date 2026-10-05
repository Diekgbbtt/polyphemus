# ADR: Langfuse enabled gate + SDK v4 readiness (#327)

*Status: implemented in this change. Match check: extends `docs/design/observability-recipe.md`
and `docs/observability-langfuse.md`; adds the v4 SDK/API readiness record the repo previously lacked.*

## Context

Two concerns on the Langfuse observability seam (`src/polymerhus/app/observability/`).

1. **The enabled gate and the URL resolver disagreed.** `_REQUIRED_ENV` required
   `LANGFUSE_HOST`, while `_resolve_base_url()` accepts `LANGFUSE_BASE_URL` as an alias
   (the SDK's own canonical name). A BASE_URL-only setup therefore resolved a working
   endpoint yet failed the gate, disabling tracing silently with the reason
   `missing/empty env: LANGFUSE_HOST`.
2. **The repo needed a v4 migration record.** The pinned SDK is the v4 major, but the
   v3-to-v4 checklist (Pydantic v2, `start_observation`, `propagate_attributes`, span
   filtering, namespace renames, metadata typing, release/environment env vars) had no
   durable audit and no readiness report.

## Reproduction (recorded)

With `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL` set and
`LANGFUSE_HOST` unset:

```
_is_configured: False
resolved base_url: https://example.invalid
disabled_reason: missing/empty env: LANGFUSE_HOST
```

The resolver produced a usable base URL; the gate rejected it anyway.

## Decision

### 1. The gate accepts either base-URL alias

`_is_configured()` now requires both keys plus at least one of
`LANGFUSE_BASE_URL` / `LANGFUSE_HOST` (cleaned, non-empty). `_missing_env()` names the
absent key(s), and when neither alias is set it names the pair accurately as
`LANGFUSE_BASE_URL or LANGFUSE_HOST` instead of one misleading name. This mirrors the
SDK's own `Langfuse.__init__`, which resolves `LANGFUSE_BASE_URL` before
`LANGFUSE_HOST`. Covered by `tests/test_observability_startup.py`.

### 2. Stay on the v4 SDK major; hold the exact pin at 4.13.0

The declared and resolved SDK is `langfuse==4.13.0`, already the v4 major. The code
uses the v4 observation model throughout: `propagate_attributes`, `start_as_current_observation`,
`score_current_span`, `CallbackHandler` with no `update_trace`, Pydantic v2, and no
removed `TraceMetadata` / `ObservationParams`. No v3-only API remains.

A newer 4.x exists (4.17.0 at the time of writing). The pin is held deliberately:
the custom `RetryingSpanExporter` and the truncating `mask` were verified against
4.13.0's private resource-manager seams, and the default exporter headers and
ingestion contract changed across 4.x. A bump needs its own change, with the same
live verification, and is recorded here rather than slipped into #327.

### 3. Deprecated log-reads migrated; v4 ingestion headers made explicit

Two deprecated public-API read sites are migrated:

- The live e2e evidence read `client.api.trace.list(session_id=...)` in
  `tests/e2e/test_blackloop_live_walkthrough.py` is replaced by
  `client.api.observations.get_many(...)`, grouping rows by `trace_id`
  client-side.
- The H1 harness read `GET /api/public/traces/{id}` in
  `tools/h1_delivery_loop.py` is replaced by
  `GET /api/public/v2/observations?traceId={id}` (requesting the `io`, `model`,
  and `usage` field groups, which are not in the default `core,basic` set), and
  reading `providedModelName` / `usageDetails`.

One deprecated read remains as a named, owned exception: the standalone L1
recovery fixture `tests/e2e/hunting_l1_recovery.py` reads a trace by name and
consumes its trace-level `output`. v4 has no separate trace-level input/output
entity (it lives on the root observation), and the v2 observation ordering and
root-row selection have not been verified against a live project - rewriting it
would risk silently recovering a different trace's output. It stays on
`GET /api/public/traces?name=...` until the e2e tier can be verified live;
owner: the walkthrough e2e fixture.

The H1 harness tools accept the BASE_URL alias like the runtime. Trace and
observation writes go through the v4 OpenTelemetry export path (custom OTLP
exporter on `/api/public/otel/v1/traces`). Because the repo passes its own
`span_exporter` to opt out of the SDK's default wiring, that exporter must
reproduce the SDK's identifying headers or Langfuse reads the ingestion as an
outdated SDK configuration (the reported warning). It now sends both
`x-langfuse-sdk-version` (the installed SDK version, as the default
`LangfuseSpanProcessor` exporter does) and `x-langfuse-ingestion-version: 4`
(the v4 real-time ingestion selector for a direct OTLP client).

### 4. Docs updated with the code

`.env.example`, `docs/observability-langfuse.md`,
`docs/design/technological-architecture.md`, and the observability
`requirements.txt` comment now state the keys-plus-one-alias gate and the v4 model.

## v4 readiness report

| Row | Status | Notes |
| --- | --- | --- |
| Project access | blocked | No Langfuse project credentials/host are configured for this worktree; nothing project-side was read or written. Next: run the report against the confirmed target project from an eval instance. Link: https://cloud.langfuse.com/project/~/settings |
| SDK / instrumentation | changed | Gate fixed; custom OTLP exporter now sends `x-langfuse-sdk-version` (as the default SDK exporter does) plus `x-langfuse-ingestion-version: 4`, which the default exporter does not send; pin held at 4.13.0 (`latest` 4.17.0). Covered by unit tests. |
| Trace evaluators | blocked | Requires project access (Evaluators UI + rules); no project state inferred. Next: confirm the target host and project, then open the Evaluators UI and inspect for active legacy rows. Link: https://cloud.langfuse.com/project/~/evals |
| Dataset evaluators | blocked | Requires project access; the repo uses no dataset/evaluator SDK surface. Next: confirm whether the target project has any dataset evaluator before recording a migration target. Link: https://cloud.langfuse.com/project/~/datasets |
| Direct APIs | changed | Deprecated `client.api.trace.list` and the raw `GET /api/public/traces/{id}` (H1 tool) both migrated to the v2 observations API; no `*_v_2` aliases remain. Live read-back verification is blocked on project access. Next: confirm the target host and project, then run the live read-back from an eval instance. Link: https://cloud.langfuse.com/project/~/traces |
| Exports | manual action | Blob/Mixpanel/PostHog exports are project settings, not code, and no code consumer exists. Next: confirm in Project Settings > Integrations on the target project. Link: https://cloud.langfuse.com/project/~/settings/integrations |
| Verification / rollback | changed | Unit tests green; no production cutover happened, so rollback is the pin + code diff. Project-side trace inspection is blocked on project access. Next: confirm the target host and project, then inspect traces. Link: https://cloud.langfuse.com/project/~/traces |

## Consequences

- A BASE_URL-only operator now gets tracing, and a genuinely disabled setup names the
  real missing requirement.
- The v4 session path is recorded: session and tags ride `propagate_attributes` per
  non-root observation via the attributing handler, so worker-thread children keep
  attribution and no spans are dropped by the default v4 export filter (all emitted
  spans use `langfuse-sdk` primitives).
- The readiness rows that need a live Langfuse project remain blocked until an
  operator supplies project access.
