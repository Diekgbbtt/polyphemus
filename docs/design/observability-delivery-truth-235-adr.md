# ADR: source observation-delivery results from the exporter outcome, not the queue drain (#235)

*Status: implemented in this change. Match check: amends D1 of `docs/design/observability-delivery.md` and the delivery bullet in `src/polymerhus/app/CONTEXT.md`.*

## Context

The H1 delivery barrier (`app/observability/langfuse_tracing.py::flush_observation_delivery`) reported a handler as `delivered` whenever its client's `flush()` returned without raising.
But `flush()` only drains the SDK's in-memory queue into the background `BatchSpanProcessor`.
The wrapped `RetryingSpanExporter` is what actually exports, and when its retry budget is exhausted it logs `dropping batch ... retry budget exhausted` and returns `SpanExportResult.FAILURE` - an outcome the flush path never saw.

A quoted `LANGFUSE_HOST` run proved the point live: every handler batch was dropped (`No connection adapters`) while the delivery call reported success.
The queue drained, so the result said `delivered`; the batch was gone.

Five module run-end flushes bypassed the primitive entirely with `get_client().flush()`: analyser tracing, the analysis supervisor, the analysis bootstrap, hunting tracing, and orchestrator tracing.

## Decision

### 1. The exporter records its outcome and exposes it

`RetryingSpanExporter` keeps a monotonic count of the spans in every batch it permanently drops (`_dropped_spans`, guarded by `_drop_lock`), incremented on the retry-budget-exhausted path (a batch with an unknown or non-positive length counts as one span so a drop is never invisible).
It exposes `take_dropped_spans()`, which reads AND resets the count under the same lock.

### 2. The delivery result is truthful

`flush_observation_delivery` reads `take_dropped_spans()` AFTER the drain and reports a handler as `delivered` only when the flush drained AND no span was dropped in the window; a recorded drop is `dropped` with the new cause `exporter-failed` (a raising `flush()` stays `flush-raised`; `flush-raised` is never reused for an exporter drop).
When handlers disagree the most severe cause wins (`ok` < `no-client` < `exporter-failed` < `flush-raised`).

**Flush-window semantics.** The counter is read-and-reset, not reset-then-read.
Reading after the drain means the value covers every batch the retry budget exhausted during the flush and any drop since the previous delivery read, so a drop that a COMPLETED flush recorded can never be reported as `delivered`.
Read and reset share one lock with the increment, so a drop that races the read is counted by exactly one side and can never be lost.
The cost is conservatism: a background drop between two flushes is attributed to the next flush, which is the honest direction (the result can over-report a drop, never under-report one).

**Residual (the slow-timeout class).** The drain's underlying `force_flush` uses the OTel default 30s window, while a single export attempt may block up to `_DEFAULT_EXPORT_TIMEOUT_S` (60s) before its retry budget exhausts.
A drop recorded only AFTER `force_flush` returns is therefore attributed to the NEXT flush, or missed by a FINAL run-end flush that has no successor.
The proven #226 case (`No connection adapters`, an immediate exporter failure) is covered; the slow-timeout class is a known residual, filed as #345, and is not claimed closed here.

**Multi-batch.** A single flush may drain many queued batches; the wrapper applies its retry budget per batch, and the counter sums every dropped batch in the window, so one clean batch cannot mask a dropped sibling.

### 3. The seam: the in-effect exporter on the client's resource manager

The flush path resolves the exporter through the existing `_active_span_exporter(client)` accessor (`client._resources.span_exporter`, the same seam the wrapper-in-effect check already uses).
This is preferred over a module-level registry because it returns the exporter ACTUALLY in effect: if another client won the process-wide resource-manager singleton for the public key, our registered wrapper is not the one exporting, and a registry would read that unused wrapper's always-zero counter as a false success.
When the in-effect exporter is not a retrying wrapper (the SDK default, or an inaccessible resource manager), no outcome is recordable and the read returns 0 - a missing outcome is never fabricated into a drop. The access reads one private attribute (`_resources`), already guarded fail-open and already exercised by `_verify_configured_exporter_in_effect`.

### 4. One primitive, no parallel paths

The five module run-end flushes now delegate to `flush_observation_delivery()` (no arguments, sweeping the cached handler) and drop their private `get_client().flush()` copies.
A module's SDK `get_client()` and the cached handler resolve the same process-wide client keyed by public key, so the primitive reaches that module's exporter and the same truthful result applies; `rg "get_client\(\)\.flush\(\)" src/polymerhus` returns nothing.
Timing and the fail-open contract are unchanged at each site: each still flushes at its own run-end and never raises.

## Consequences

- A dropped batch is now `dropped`/`exporter-failed` instead of a misleading `delivered`; the failure is visible in the barrier's warning and in the result.
- Delivery stays fail-open: the change makes the RESULT truthful, it never makes delivery fatal. A raising flush, a raising exporter read, or both degrade to a result and never raise.
- The improvement is bounded by the wrapper being in effect; under the fallback path (a pre-existing client won the singleton, already warned about at build time) no outcome is recordable and the result is the old drain-based one.
- Tests need no network and no live Langfuse: a fake client exposing a real `RetryingSpanExporter` over a fake inner exporter drives the success, drop, multi-batch, reset, and both-raise arms (`tests/test_langfuse_delivery_barrier.py`).

## Open question / trade-off

A background drop between two flushes is attributed to the next flush (read-and-reset conservatism), so a `dropped` count can over-report in time but never hides a real drop.
A per-flush generation watermark could tighten attribution, but it adds SDK-internal coupling for no truthfulness gain; deferred.
