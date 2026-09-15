# Observability recipe (Langfuse client layer canon)

This is the canonical interaction pattern for emitting Langfuse observations from Python agent code.
It was extracted 2026-09-09 from six mutually-mirroring implementations after live verification proved a divergent seventh (raw OpenTelemetry spans in `lightrag/observability.py`) never reaches Langfuse.
It was re-grounded 2026-09-15 on the converged single pattern below, after the #226 diagnosis proved the hand-written agent-span scaffolding redundant wherever a LangChain run already carries the trace.
Every new traced seam MUST follow this recipe; every divergent seam SHOULD be migrated to it.

## The converged pattern (CallbackHandler-first)

One observability client, one transport, one delivery path.
The LangChain `CallbackHandler` (`app/observability/langfuse_tracing.py::get_langfuse_callbacks`) is the PRIMARY and default instrumentation for every dispatch that runs under a LangChain/LangGraph run.
It captures the chain/tool/LLM/retriever tree with zero per-site code, threads trace membership explicitly through `parent_run_id` (thread-safe by construction), and - since #226 - re-establishes session/tags on every non-root observation from its own run metadata, so worker-thread children keep attribution without any ambient context.
A dispatch running under a handler-carrying config MUST NOT open a parallel hand-written agent span around itself; the run's own chain span is the grouping span.
The run-level join across session-scoped turn traces rides an explicit run tag (the bare `run_id`, mirroring the recon convention), passed through the turn seam - never a shared session, which would collide across concurrent instances (#94 keying).

## Thin-exception contract (hand-written spans)

Hand-written SDK spans are the DOCUMENTED EXCEPTION, allowed only where no LangChain run exists to carry the trace.
Each exception site MUST satisfy all four clauses, otherwise it migrates to the handler.
It takes its correlation EXPLICITLY as arguments (session id, tags, run id) and never reads ambient context.
It wraps its body in `propagate_attributes` with those explicit values plus `start_as_current_observation`, fail-open to a no-op.
It flushes through the owning call site's flush call (`flush`, never `shutdown`); delivery unification across all sites is #235.
It is covered by the unit-test recipe below with the correlation asserted from the explicit arguments, never from ambient state.

## Primitives (the `langfuse` library surface we use)

All imports are lazy (inside functions, never at module scope) so a runtime without the package imports cleanly.
Two primitives cover everything, in priority order: `CallbackHandler` for every LangChain/LangGraph runtime, `get_client` + `propagate_attributes` for the thin exception only.

- `from langfuse.langchain import CallbackHandler` (via `app/observability/langfuse_tracing.py::get_langfuse_callbacks`) - the default seam for LangChain `invoke`/`graph.invoke`/session turns, where the run structure yields the trace tree for free.
- `from langfuse import get_client, propagate_attributes` - the thin-exception import seam for hand-written spans, with explicit correlation arguments only.
- Never touch `opentelemetry.trace` directly for emitted spans (see the caveat below).
- Never construct `Langfuse(...)` outside `langfuse_tracing.py` (the process-wide singleton + retrying exporter live there).

## Interaction sequence (thin exception only)

One trace per dispatch, session-correlated to its run; step observations nest under the agent span.

1. Open an `ExitStack` (the null context when tracing is unavailable - an empty stack IS the no-op).
2. `stack.enter_context(propagate_attributes(trace_name=<name>, session_id=<run_id>, tags=[...], metadata={...}))` - sets TRACE-level correlation only, creates NO observation.
3. `stack.enter_context(get_client().start_as_current_observation(name=<name>, as_type="agent", input={...}))` - opens the agent span that step spans and LLM generations nest under.
4. Step spans: `with get_client().start_as_current_observation(name=<step>, as_type="span", input={...}) as span:` then `span.update(output={...})` for the step's result.
5. Structured generations: same shape with `as_type="generation"` so structured output rides its OWN nested observation instead of clobbering the agent span's prose I/O.
6. Free-text reasoning: `get_client().update_current_span(input={"call": <call>}, output=<prose>)` on the current span (transient, never persisted to the graph).
7. Numeric metrics: `get_client().score_current_span(name=<metric>, value=float(...))` while the target span is current.
8. Flush with `get_client().flush()` when a worker may exit before the background exporter fires - `flush`, never `shutdown`, because the client is a process-wide singleton later runs reuse.

## Data structures

All `input` / `output` / `metadata` payloads MUST be JSON-serialisable dicts (the SDK serialises them; OTel attribute limits do not apply on this path).
On the handler path the run-level join is the bare `run_id` carried as a TAG on turn configs (the session stays the per-instance thread id, so concurrent instances never collide).
On the thin-exception path `session_id` is ALWAYS the run id so a run's traces join by session.
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

## Convergence migration (2026-09-15)

The hand-written agent-span wrappers are REDUNDANT wherever a LangChain run already carries the trace, because the handler tree plus the run tag preserve both structure and join.
Each site migrates exactly once, by row, and the row states what survives.

- Supervisor proposers (`analysis/supervisor.py` + `app/observability/analyser_tracing.py`): DELETE the `analyser_span` wrapper - the proposer node is itself a fully-attributed chain span under the run-sessioned supervisor graph.
- The proposer bodies pass the bare run id as an extra turn tag, so session-scoped turn generations stay run-joinable by tag.
- `trace_reasoning` / `trace_generation` survive as thin-exception spans with EXPLICIT correlation arguments (no ambient reads), because they record proposer data the handler never sees.
- Hunting agent (`attack/hunting/hunting_agent.py` + `hunting_tracing.py`): DELETE the `hunting_span` wrapper - every step is an attributed session turn.
- The hunt passes its run id as an extra turn tag for the same join.
- `trace_span` survives as a thin-exception step span with explicit correlation arguments; the flush call stays until #235 unifies delivery.
- Hunt orchestrator (`attack/hunting/hunt_orchestrator.py`, `runtime.py` + `orchestrator_tracing.py`): DELETE the `orchestrator_gate_span` wrapper - actor turns ride the session seam.
- The pass threads its run id as an extra turn tag.
- `trace_gate_step` survives as a thin-exception step span with explicit correlation arguments; the flush call stays until #235.
- Bootstrapper (`analysis/bootstrap.py`): KEEPS `_bootstrap_span` UNCHANGED as the canonical thin exception.
- Its `invoke_role` calls carry no handler config, so no LangChain run exists to carry the trace - deletion would lose the trace, not migrate it.
- Negotiation probe (`app/llm/negotiation.py::_emit_probe_span`): KEEPS its one-shot span UNCHANGED as the minimal thin exception (no run context exists at probe time).
- Anatomy (`analysis/anatomy.py`, the `anatomy` one_shot role): OUT OF SCOPE, obsolete - untouched by this migration, neither migrated nor reclassified.
