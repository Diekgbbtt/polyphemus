# Observability delivery + attribution (Langfuse)

*Design spec: how an observation gets from a model call to a readable, attributable receipt.*
*Companion: `docs/design/observability-recipe.md` (the emission canon - which primitives to call).*
*This spec covers what the recipe does not: delivery guarantees, attribution mechanics, and the turn-span accuracy contract.*
*Pattern debt: the flush/assert/loud-drop shape is borrowed from the #211 teardown contract (`flush -> assert -> teardown`, typed result, fail-open never silent); no #211 primitive is reused (that contract moves checkpoints, this one moves observations).*

## Status

* `#225 (closed): streamed generations recorded usage 0/0/0 because `stream_options.include_usage` never reached the wire; fixed at the single construction seam (`build_chat_model` passes `stream_usage=True`).`
* `H1 (this spec, to build): finished observations are lost when the process dies before the background exporter fires; fixed by a forced client flush at turn end (primary) and teardown (fallback).`
* `#226 (open, referenced not absorbed): handler-path spans never land (custom exporter/mask suspect) and recon observations carry empty session/tags (contextvars-across-threads suspect); the bisect owns those questions.`

## Seam inventory (aligned to code)

* The only supported handler source is `app/observability/langfuse_tracing.py::get_langfuse_callbacks`, returning the process-wide singleton `[handler]` when configured and `[]` otherwise (fail-open, inert as `config={"callbacks": []}`).`
* Hand-written spans use ONLY the SDK surface (`get_client`, `propagate_attributes`, `start_as_current_observation`); raw OpenTelemetry scopes are dropped by the processor filter (recipe caveat, verified live).`
* Never construct `Langfuse(...)` outside `langfuse_tracing.py`; never call client `shutdown()` (the client is a process-wide singleton later runs reuse) - `flush()` is the boundary primitive.`
* Attribution keys ride the turn config metadata (`app/llm/session.py::_observe_config`): `langfuse_session_id` = thread id, `langfuse_tags` = `["session", role_id]`, plus `role_id`.`
* Wiring points that borrow the handler per invocation: `run_session_turn` / `arun_session_turn` (via `_turn_config`), role models at construction (`providers.py::build_chat_model` passes `callbacks=`), the analysis supervisor, hunting pods.`
* No per-session handler object exists anywhere: sessions multiplex through the singleton via per-call metadata, and the handler sorts runs into traces via the explicit `parent_run_id` chain plus its LangGraph resume-key machinery.`

## Delivery model (three stages)

* Stage 1, terminal closure: every opened run gets exactly one terminal call - `on_llm_end` on success (writes output, usage, model, input, ends the observation), `on_llm_error` on failure including a mid-stream cut (verified in the installed `langchain_core`: the stream wrapper calls `on_llm_error` with the partial chunks, then re-raises; the handler ends the generation at error level with zero cost).`
* Stage 2, enqueue: `update(...).end()` serialises the finished observation into the SDK client's task-manager queue (synchronous, in-memory).`
* Stage 3, export: a background batcher carries the queue over OTLP on its own schedule or at process exit; nothing awaits it, and the handler exposes no flush of its own.`
* Consequence (H1, loop-proven): a generation finished client-side is deterministically lost when the process dies first, and deterministically lands after one blocking own-client `flush()` (control LOST / barrier LANDED, same markers, same window).`

## Decision D1: the forced delivery barrier

* New primitive `flush_observation_delivery(callbacks=None) -> DeliveryResult` in `langfuse_tracing.py`: settle-defensive sweep of still-open runs (normally empty - both terminal paths detach), then a blocking `flush()` on each borrowed handler's OWN client (never a fresh client: the singleton hazard means a new one may not carry the configured exporter), returning `{delivered, pending, dropped, cause}` with the closed cause vocabulary (`ok`, `unconfigured`, `no-client`, `flush-raised`), never raising.`
* Primary site: end of `run_session_turn` / `arun_session_turn`, flushing exactly the callback list the turn borrowed (the same list it put in `config` - no global lookup on the hot path).`
* Fallback site: the teardown walk, sweeping the cached handler where no turn context exists (mirrors the #211 bulk-flush fallback shape).`
* Bounded in practice, documented as residual risk: the drain is one blocking exporter flush (the same blocking class as the turn's own model calls, so the sync turn calls it directly); async callers ride `asyncio.to_thread` so the loop never blocks (mirroring the #211 off-loop flush shape), with no `wait_for` guillotine (a cancelled drain would leave delivery state ambiguous - worse than slow).`
* The SDK docs discourage unbounded production flushes for latency; if the drain ever dominates turn latency, bound it with a measured budget then, with a test pinning the bound - not before.`

## Attribution model (two mechanisms, different fragility)

* Trace membership (which observations join which trace) rides the explicit `parent_run_id` chain through the runnable config: thread-safe by construction, and why session turns nest correctly today.`
* Trace attributes (session id, tags, user) are parsed from metadata ONLY at chain roots and re-propagated to nested observations through `propagate_attributes`, which is contextvars-based: it does not cross thread boundaries unless copied, so any thread hop between root parse and nested creation (pregel executors, `asyncio.to_thread`, pod worker pools) silently drops the labels - the structural suspect for #226's empty session/tags on recon observations.`
* Direction (owned by #226, recorded here so the two halves stay coherent): deterministic trace ownership - `create_trace_id(seed=thread_id)` per session thread plus one enclosing observation per turn, attribution by construction instead of by propagation; handler-per-execution-context over the shared client to retire the singleton-reuse hazards.`

## Turn-span accuracy contract

* A turn span is accurate when four properties hold, each checkable: completeness (terminal generations == model calls in the turn: normal + recovery + summariser), correctness (each carries its own input/output/usage/model), closure (zero open runs left in the handler table afterwards), timeliness (readable within a bound after turn end).`
* The barrier delivers closure + timeliness structurally; completeness + correctness ride the terminal paths and the #225 fix; attributability rides the #226 outcome.`

## Test strategy

* Unit tier at the new seam with fakes (fake handler exposing an owned fake client recording `flush()` calls; raising/empty/timeout arms pinning the degraded results; turn-level test asserting the barrier receives exactly the borrowed list) - no live Langfuse by construction, mirroring the recipe's test canon.`
* Live tier: the H1 two-arm loop (control `os._exit` without flush vs barrier `os._exit` after flush, trace-id-direct read-back) is the regression proof for delivery; the marked-stream probe is the proof for usage.`
