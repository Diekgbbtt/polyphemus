# Diagnosis: analysis-agent Langfuse trace content is `null` in the new project

Status: root cause found (PLATFORM, read-path field selection). No producer-side defect.
Branch: `exp/endpoint-first-prefix`. No code change made (see "Fix").

## Summary

The analysis agents **do** push `input` and `output` to Langfuse.
The content is invisible only because the read query omits the v2 `io` field group.
`/api/public/v2/observations` returns `input`/`output` **only** when `fields` includes `io`.
The operator's query uses `fields=core,basic,usage,model`, which omits `io`, so the two fields are absent from the JSON and read as `null`.
This is a platform API-contract change, not local analysis-agent wiring.

## Phase 1 - the red-capable feedback loop

The loop is one command: query one known analysis session twice, changing exactly one variable (`io` in the `fields` list).

Script (run on the eval server; keys read from `.env`, never echoed):

```
GET https://cloud.langfuse.com/api/public/v2/observations
    ?fromStartTime=2026-10-01T00:00:00Z&toStartTime=2026-10-14T00:00:00Z
    &sessionId=339edfb4-...a3ed6972:comfyui-update:assigner
    &fields=<FIELDS>&limit=100&page=N      # HTTP Basic base64(public:secret)
```

Observed (redacted; secret used only in the Authorization header):

```
fields='core,basic,usage,model'        rows=2500  GENERATION=175  in_nonnull=0    out_nonnull=0     <-- RED (the symptom)
fields='core,basic,usage,model,io'     rows=2500  GENERATION=175  in_nonnull=175  out_nonnull=175   <-- GREEN
```

- Red: `input`/`output` absent -> the operator sees "`input=null, output=null`".
- Green: after adding `io`, every GENERATION carries content.
- The loop goes green by adding `io`; it is deterministic, fast (seconds once the window is narrowed), and agent-runnable.

The `sessionId` filter was verified to work (all returned rows shared the one requested session).

## Phase 2/3 - the delta table (what stopped appearing)

Per observation type, one analysis session (`...:comfyui-update:assigner`, first 800 rows) and one probe (`var-2:assigner`, full).

| session | fields | type | n | input non-null | output non-null |
| --- | --- | --- | --- | --- | --- |
| comfyui-update:assigner | `core,basic,usage,model` | AGENT | 32 | 0 | 0 |
| comfyui-update:assigner | `core,basic,usage,model` | CHAIN | 488 | 0 | 0 |
| comfyui-update:assigner | `core,basic,usage,model` | GENERATION | 56 | 0 | 0 |
| comfyui-update:assigner | `core,basic,usage,model` | TOOL | 224 | 0 | 0 |
| comfyui-update:assigner | `+io` | AGENT | 32 | 32 | 0 |
| comfyui-update:assigner | `+io` | CHAIN | 488 | 488 | 264 |
| comfyui-update:assigner | `+io` | GENERATION | 56 | 56 | 56 |
| comfyui-update:assigner | `+io` | TOOL | 224 | 224 | 224 |
| var-2:assigner | `+io` | GENERATION | 3 | 3 | 3 |
| var-2:assigner | `+io` | TOOL | 3 | 3 | 3 |

Exact fields that stopped appearing: **`input` and `output`** (the `io` group).
They are pushed; they are simply not requested.

Two genuinely-empty cases are structural, not the symptom:
- `AGENT.output` is `null` for `_CompactionMiddleware.after_agent` spans (that span sets input, never output).
- `CHAIN.output` is `null` on the ~half of chain spans that never set an output.

`fields=` semantics measured directly (which keys each value returns):

| `fields=` | returns `input`/`output`? | notes |
| --- | --- | --- |
| (omitted) | no | default = `core` + `basic` |
| `core` | no | ids, type, times, prices |
| `basic` | no | name, level, sessionId, isRootObservation, ... |
| `usage` | no | usageDetails, costDetails, prices |
| `model` | no | model, internalModelId, modelParameters |
| `metadata` | no | metadata |
| `io` | **yes** | input, output |
| `input` / `output` / `all` | no | not valid group names -> fall back to `core` only |
| `core,basic,usage,model` | no | the operator's query -> symptom |
| `core,basic,usage,model,io` | **yes** | correct query |

## Phase 4 - local instrumentation (the decisive experiment)

Ran, inside the agent container (`ph-dd131acc-agent-1`), a throwaway `[DEBUG-lf1]` probe at the exact seam the assigner uses: `trace_generation(...)` (`src/polymerhus/analysis/proposer_turn.py` calls through `stateful_turn`; the assigner records with it at `src/polymerhus/analysis/assigner.py:800`).
`trace_generation` is defined in `src/polymerhus/app/observability/analyser_tracing.py:54`.

The probe emitted one `generation` carrying a unique marker into session `debug-lf1-session`, flushed with `flush_analyser_traces()`, then read it back with and without `io`:

```
[DEBUG-lf1] env keys present: True True https://cloud.langfuse.com
[DEBUG-lf1] emitted generation with marker into session debug-lf1-session
[DEBUG-lf1] fields='core,basic,usage,model'    GEN=1 in_nonnull=0 out_nonnull=0 marker_visible=False
[DEBUG-lf1] fields='core,basic,usage,model,io' GEN=1 in_nonnull=1 out_nonnull=1 marker_visible=True
```

One variable changed (`io`); the marker flips from invisible to visible.
The local content path is sound: content is built and pushed; only the read field set hides it. No repo change was made for this probe (throwaway script under `/tmp`, nothing committed).

## Root cause (PLATFORM)

The new organization cannot use the v1 data API, so all reads moved to the v2 observations API, whose default field set excludes `input`/`output`.

Evidence chain:
1. `GET /api/public/traces` returns HTTP 410 `LEGACY_API_UNAVAILABLE_FOR_NEW_ORGANIZATION` for organizations created on/after 2026-09-16, directing to `/api/public/v2/observations` (observed live).
2. v2 defaults to `core,basic`; `input`/`output` live only in the `io` group and are **absent** (not `null`) when unrequested.
   - "Fields from groups you do not request are absent from the response, not null." - Langfuse docs, Observations API: https://langfuse.com/docs/api-and-data-platform/features/observations-api.md and https://langfuse.com/docs/api-and-data-platform/features/public-api.md
   - `io | input, output`; default `core,basic` - same docs.
   - v2 `trace_context` group also added 2026-05-15: https://langfuse.com/changelog/2026-05-15-v2-observations-trace-context
3. v1 "returns complete rows with all fields (input/output, usage, metadata, etc.)" - that is why earlier runs "captured content": the old project was read through v1, which returned `io` by default.
4. The operator's v2 query `fields=core,basic,usage,model` omits `io`, so the fields are absent.

Discriminating evidence for platform vs local:
- **Every** producer is affected, not just analysis: analysis assigner sessions, `var-*` probes, and TOOL spans (`notes`) are all "null" under the operator's field set and all populated under `io`. A local analysis-wiring defect would be selective, not field-set-invariant.
- The instrumented `trace_generation` probe - the identical local wiring the analysis agents use - pushes a marker that is readable once `io` is requested. So the local wiring is proven correct.
- The installed SDK is unchanged: `langfuse==4.13.0` in both `/Users/diekgbbtt/polymerhus/.venv` and the agent container. Not a version regression.
- No masking is in play: with `io` requested the content is real text, not redacted.

## Not the cause (ruled out)

- **Local analysis wiring**: `_observe_config` (`src/polymerhus/app/llm/session.py:109`) attaches the shared handler and session id; `trace_generation` (`analyser_tracing.py:54`) sets `input`/`output`; `pod.py::default_exec_fn` (`src/polymerhus/recon/domain/pod.py:614`) attaches callbacks to the MCP tool call. All produce content (verified via `io`).
- **Singleton span exporter**: the warning "langfuse configured span exporter is NOT in effect - a pre-existing client for this public key won the singleton" (`langfuse_tracing.py:663`) does **not** appear anywhere in the live agent log (2158 lines scanned, 0 matches). It reproduced only in the isolated probe, where `get_client()` in `trace_generation` built a default client before `get_langfuse_callbacks()`. In the running app the configured client wins first. It concerns the retry/truncation wrapper only, not content capture.
- **SDK version**: unchanged at 4.13.0.
- **Project masking / hide-content setting**: ruled out by real content returned under `io`.

## Fix

Report only - the cause is not local and narrow, so no code change is made (per scope).
The producers are correct; the remediation is on the read side.

Remediation (consumer side, one line): request the `io` group, e.g.
`fields=core,basic,usage,model,io` (or `core,basic,io`).

Repo status:
- The repo's own v2 reader already does this: `tools/h1_delivery_loop.py:36` uses `fields=core,basic,io,model,usage`, and `docs/design/observability-langfuse-v4-gate-adr.md:65-69` records that the endpoint returns only `core,basic` by default.
- One deprecated read remains and will break against the new org: `tests/e2e/hunting_l1_recovery.py:57` still calls v1 `GET /api/public/traces?name=...`, which now returns 410 (this is the named, owned exception in the ADR, lines 71-78; it reads a trace-level `output`, which v2 has no separate entity for).
- Action for the operator: update the ad-hoc query to include `io`; the traces themselves need no change.

## Cleanup

- `[DEBUG-lf1]` was a throwaway runtime probe, not committed code; no code to revert (`git status` shows only the pre-existing `endpoint-first-prefix` work).
- The probe left one marker trace in session `debug-lf1-session` in the project; it is inert test data.
- The feedback loop was re-run after cleanup and still shows RED without `io`, GREEN with `io`.

## Update to repo model (docs pass)

No domain term changed. The v2 `fields`/`io` contract is already recorded in `docs/design/observability-langfuse-v4-gate-adr.md` (#327 section 3); this diagnosis adds the live read-back confirmation that ADR's "Direct APIs" row listed as blocked ("confirm the target host and project, then run the live read-back from an eval instance"). That row can now be marked verified against the new project.
