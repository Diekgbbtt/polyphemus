# Observability recipe (Langfuse client layer canon)

This is the canonical interaction pattern for emitting Langfuse observations from Python agent code.
It was extracted 2026-09-09 from six mutually-mirroring implementations after live verification proved a divergent seventh (raw OpenTelemetry spans in `lightrag/observability.py`) never reaches Langfuse.
Every new traced seam MUST follow this recipe; every divergent seam SHOULD be migrated to it.

## Primitives (the `langfuse` library surface we use)

All imports are lazy (inside functions, never at module scope) so a runtime without the package imports cleanly.
Three primitives cover everything: `get_client` + `propagate_attributes` for trace correlation and span I/O, `CallbackHandler` for LangChain/LangGraph runtimes only.

- `from langfuse import get_client, propagate_attributes` - the only import seam for hand-written spans.
- `from langfuse.langchain import CallbackHandler` (via `app/observability/langfuse_tracing.py::get_langfuse_callbacks`) - ONLY for LangChain `invoke`/`graph.invoke` call sites, where the graph structure yields the trace tree for free.
- Never touch `opentelemetry.trace` directly for emitted spans (see the caveat below).
- Never construct `Langfuse(...)` outside `langfuse_tracing.py` (the process-wide singleton + retrying exporter live there).

## Interaction sequence

One trace per dispatch, session-correlated to its run; step observations nest under the agent span.

1. Open an `ExitStack` (the null context when tracing is unavailable - an empty stack IS the no-op).
2. `stack.enter_context(propagate_attributes(trace_name=<name>, session_id=<run_id>, tags=[...], metadata={...}))` - sets TRACE-level correlation only, creates NO observation.
3. `stack.enter_context(get_client().start_as_current_observation(name=<name>, as_type="agent", input={...}))` - opens the agent span that step spans and LLM generations nest under.
4. Step spans: `with get_client().start_as_current_observation(name=<step>, as_type="span", input={...}) as span:` then `span.update(output={...})` for the step's result.
5. Structured generations: same shape with `as_type="generation"` so structured output rides its OWN nested observation instead of clobbering the agent span's prose I/O.
6. Free-text reasoning: `get_client().update_current_span(input={"call": <call>}, output=<prose>)` on the current span (transient, never persisted to the graph).
7. Numeric metrics: `get_client().score_current_span(name=<metric>, value=float(...))` while the target span is current.
8. Flush with `get_client().flush()` when a worker may exit before the background exporter fires - `flush`, never `shutdown`, because the client is a process-wide singleton later runs reuse.
9. LangChain-handler runs flush through the same client: `flush_observation_delivery(callbacks)` (`app/observability/langfuse_tracing.py`) drains each borrowed handler's OWN client (a fresh client may not carry the configured exporter - singleton hazard) and returns a typed `DeliveryResult`; the turn calls it with exactly the list it borrowed, teardown sweeps the cache. Design: `docs/design/observability-delivery.md`.

## Data structures

All `input` / `output` / `metadata` payloads MUST be JSON-serialisable dicts (the SDK serialises them; OTel attribute limits do not apply on this path).
`session_id` is ALWAYS the run id so a run's traces join by session.
`tags` name the layer and role (e.g. `["attack", "hunting", "hunting-agent"]`).
`metadata` carries small correlation keys (`project_id`, `hunt_id`, `phase`, `dispatch_id`).

## Fail-open discipline

Tracing is best-effort and must never fail - or even perturb - an agent dispatch.
Every helper wraps its body in `try/except Exception` degrading to a no-op (`nullcontext()` / empty `ExitStack` / swallowed span) with a `logger.debug` line naming the seam.
Unit tests therefore run with no live Langfuse by construction.

## Test recipe

Fake the `langfuse` module via `monkeypatch.setitem(sys.modules, "langfuse", ...)` with a `get_client()` returning a `MagicMock` whose `start_as_current_observation` is a context manager appending `(kind, kwargs)` calls, exactly as `tests/test_analyser_tracing.py` does.
Assert the call sequence (`propagate` -> `observation` -> `update`), the session correlation, and the fail-open path (raising client -> no-op, dispatch completes).

## Caveat: raw OTel spans are dropped (verified live 2026-09-09)

`langfuse==4.13.0`'s `LangfuseSpanProcessor.on_end` applies `is_default_export_span`, which keeps ONLY spans whose instrumentation scope is the SDK's own tracer (`langfuse-sdk`), a GenAI-semantics span, or a known LLM instrumentor.
A span opened via `opentelemetry.trace.get_tracer("anything-else").start_as_current_span(...)` is created, flushed (`force_flush` returns True), and then SILENTLY DROPPED - the debug log reads `Dropping span due to should_export_span filter`.
This was proven live with a sibling container: provider `TracerProvider` + `LangfuseSpanProcessor` active, egress 200, `auth_check` True, manual exporter OK, yet the trace 404s on read-back and the SDK debug log shows the drop for scopes `lightrag.query` and `verify207`.
Consequence: hand-written spans MUST use the SDK primitives above, never raw OTel.

## Streamed-turn usage (#225, 2026-09-11)

A streamed LLM turn records usage 0/0/0 unless the client requests the provider's terminal usage chunk.
The pinned `langchain-openai` auto-enables `stream_usage` ONLY for the default OpenAI base URL, and every `build_chat_model` construction carries a custom base_url (provider or gateway), so `stream_options.include_usage` never reached the wire.
Model/input/output/metadata were unaffected (they persist via the start/end callbacks); only usage was lost, on streamed turns only.
This refines #225's hypotheses with quoted evidence: H1 (streaming broke persistence) holds for usage alone, not for the other fields; H2 (end-of-run updates never sent) is refuted - `on_llm_end` demonstrably runs on streamed Pregel turns (output + `completion_start_time` present live).
The non-streamed path was already whole: a faithful redo of the issue's control (non-streamed direct invoke + explicit flush) yields all five fields, so no change was needed there.
Decision: `build_chat_model` (`app/llm/providers.py`) - the single construction seam every role reaches - passes `stream_usage=True`, so every streamed request carries `stream_options: {"include_usage": true}`.
Non-streamed calls are unaffected (the flag is consulted only on the streaming path).
Provider compat rides the existing gateway safety net: `stream_options` is a standard OpenAI param the proxy forwards natively, and `drop_params: true` strips it per-upstream where unsupported instead of 400ing (the same net that covers `reasoning_effort`, ADR A5).
Pinned by `test_build_chat_model_requests_stream_usage_for_streamed_calls` + `test_streamed_calls_carry_include_usage_on_the_wire` (`tests/test_llm_providers.py`); proven live by probe sessions `probe225-*-S0` (usage 0/0/0 pre-fix) vs `probe225-*-S1` (usage 40/8/48 post-fix shape).

## Witness index (mutual-mirror chain)

`analysis/bootstrap.py::_bootstrap_span` is the original; `app/observability/analyser_tracing.py` replicates it for proposer dispatches; `attack/hunting/hunting_tracing.py` and `attack/hunting/orchestrator_tracing.py` mirror the analyser module exactly; `app/llm/negotiation.py::_emit_probe_span` is the minimal one-shot form; recon LangGraph runtimes use the `CallbackHandler` seam instead (`app/observability/langfuse_tracing.py`).
