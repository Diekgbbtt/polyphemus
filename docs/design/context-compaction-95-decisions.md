# Context-Window Auto-Compact (#95) - Architectural Decision Records

Decisions taken (operator-authoritative, grilled 2026-08-18) for ticket #95: the adaptive, shared context-window manager that keeps long-horizon agent sessions inside the model's real window.
Companion to the #100 gateway ADR (`llm-gateway-100-decisions.md`), whose D6 window surface and D11 reasoning-replay surface this ticket consumes; where the two clash, the later record (this one) wins.
The grilling ran three rounds against the live #100 substrate (the session seam, the capability reader, the replay pipeline); each record below is the ratified answer with its rationale and load-bearing nuance.

## D1 - The compact pass re-persists the trail out-of-band; a strict barrier gates every call

Compaction's effect lands on the checkpointer trail the same way the T6 replay pipeline's does - never mid-call.
The out-of-band task (spawned at turn end, D4) reads the trail, summarises, offloads, and STAGES the compacted trail; it does not write the checkpointer itself.
The next call's `before_model` hook is the barrier: it awaits any pending compaction task for that thread, then applies the staged compacted trail as a state update (replacement + removal via the `messages` channel's reducer semantics), which the normal graph execution persists.
While a compaction is in flight, no further LLM turns are triggered, neither initialised - the context will be rebuilt from scratch (operator ruling).
The #94 comment's "never by reaching into the persisted checkpointed messages" is read as "never mid-call": the post-turn out-of-band path is the sanctioned non-racy mechanism, exactly as replay proved.

**The pass compacts exactly what the ledger measured; the fresh delta rides untouched.**
The out-of-band pass's input is the trail as of its turn's end (the ledger's boundary - the exact ids the ledger last measured).
A later message the pass never saw - most importantly the CURRENT turn's own input, which the graph merged into the channel before the barrier runs - MUST survive the pass.
The barrier therefore splices: it applies the staged trail, then re-appends the fresh delta (messages whose ids are not in the measured boundary).
The same splice governs the synchronous backstop (D4), which compacts the boundary subset of the current channel and preserves the delta verbatim.
Without this, the `remove_all` replacement would silently wipe the caller's fresh question - compaction must never eat input it never measured.

**Relationships are not what the summary replaces - asked questions are.**
When a compact pass produces a running summary, the region BEFORE the reserved tail folds more than assistant reasoning: older turn INPUTS (human directives the summary now carries) are summarised away too, so the window actually shrinks.
Only the D7-tail stays byte-identical, and only the measured span is ever replaced - a pass that produces no summary leaves every message verbatim (a lone unmatched question is never dropped).

**Rationale.**
A mid-call mutation races the in-flight graph execution; a before_model state update is applied through LangGraph's own reducer machinery, so the write is race-free by construction and the next turn RESTORES the compacted trail naturally.
The strict barrier is what makes "a call never proceeds on an over-budget window" true even when a previous pass failed (D6).
The boundary/delta splice keeps the barrier fail-open (a lost boundary degrades to last-known-good) while making the replacement sound under the out-of-band/next-turn race - the load-bearing concurrency edge of this whole design.

## D2 - The window is `context_limit` only; the bound is `threshold * context_limit`

The window source is the D6 capability surface: `resolve_capability(provider, model).context_limit` (gateway `/model/info` -> `LLM_ROLE_MODEL_CONTEXT_LIMIT` env -> the conservative 150k default), resolved once at session construction and held, never re-read mid-session.
The compaction bound applies to the INPUT: `0.90 * context_limit` by default.
`output_limit` is not load-bearing for the input bound; it is the output budget, recorded as observability.
The response's own growth is caught by the next post-response compaction plus the barrier, not by pre-reserving output headroom.
The threshold is tunable as an injectable builder/middleware parameter reading the `LLM_COMPACTION_THRESHOLD` env override, default `0.90`; a `settings.recon` knob is deferred to consumer wiring.

**Rationale.**
The next turn's input is what must fit the window; estimating additional next-turn input tokens is explicitly not required (operator ruling) - the threshold is applied to the post-response trail occupancy.

## D3 - Occupancy accounting comes from the real per-step usage, never a token table

The authoritative occupancy number is the provider's own `usage_metadata`, read per model step:
`input_tokens + input_token_details.cache_read` for the step (once caching engages, a growing slice moves to `cache_read`, so `input_tokens` alone under-counts).
In a tool-calling turn the loop emits one usage record per assistant step; the trail's occupancy is the LAST step's `input_tokens + cache_read` (each step's input already contains the whole prior trail) plus what migrates into the next prompt.
Tool outputs carry no usage record but occupy the next prompt, so their payload lengths count toward next-turn occupancy; reasoning sits on the output side (`completion_tokens_details.reasoning_tokens`) and migrates to the input of the next turn.
Reasoning-token placement is provider-dependent (deepseek/zen report it output-side; others may report it prompt-side) - the accounting splits per the response's own details, never per a hardcoded assumption.
`cache_read` / `cached_tokens` are recorded as observability, never a gate (D11 item 3 of the gateway ADR).

**Rationale.**
Real usage is the only provider-faithful measure for the deepseek/zen/SwissAI family; `count_tokens_approximately` (tiktoken-shaped) is a fallback for absent usage only, fail-open and logged - never the primary.

## D4 - Trigger points: ledger at `after_model`, spawn at turn end, barrier + backstop at `before_model`

`after_model` updates the usage ledger from the real response - non-blocking, never spawns.
The END of the turn (`after_agent` / the post-turn seam) spawns the out-of-band compaction task when the ledger is over threshold - spawning mid-turn would race the in-flight execution (D1).
`before_model` is the barrier: it awaits any pending task, applies the staged result, and - as a backstop - if the ledger is over budget with NO pending task (a lost or restarted task), compaction runs synchronously there.
A call never proceeds on an over-budget window; the backstop is what guarantees it after task loss.

**Known limitation (bounded, fail-open):** the barrier is a SYNCHRONOUS block (`future.result` under the `BARRIER_PENDING_TIMEOUT_S` bound), because langchain's `AgentMiddleware.before_model` hook is synchronous by contract. In the SYNC lane (`run_session_turn`) that is the natural blocking point; in the ASYNC actor lane (`arun_session_turn` -> `ainvoke`) the same hook blocks the event loop for the pass's duration. The pass is bounded (the #73 escalating read budget) and the barrier releases on timeout (fail-open), so the freeze is bounded and never a crash; making the barrier genuinely awaitable would require an async middleware hook the built seam does not expose, and is a follow-up if a live run shows the freeze matters.

**Rationale.**
Separating the non-blocking ledger update (cheap, per response) from the spawn (once per turn) keeps the model<->tool loop untouched while placing the only blocking point exactly where the next request is about to be built.

## D5 - The running summary: one atomic call, quality-gated, message + ledger

The summarisation is ONE atomic call per compact pass - no split/multi-call summarisation (operator ruling).
It uses the SESSION ROLE'S OWN model via the injectable model factory - no dedicated compactor role key, no new env var; the capability profile is already resolved for that model.
The output is structured (the running-summary contract: the narrative summary text preserving decisions, evidence pointers, and open threads).
An OUTPUT-QUALITY GATE applies: an empty, unparseable, or degenerately short summary is a FAILED generation - retried under the single retry layer, counted toward the consecutive-pass cap (D6).
The summary materialises as a synthetic message in the trail, idempotently replaced at each pass, plus a per-thread in-memory ledger keyed by the typed `SessionAddress.thread_id` (updated_at, turn_count, tokens_reclaimed, last_compacted_at, spans, over-budget flag) for the barrier and observability.

**Rationale.**
The synthetic message is what persists and is restored with the trail; the ledger is what the barrier and the observability surface read.
The quality gate closes the gap the operator flagged: without it, an empty or weak summary silently "succeeds" and analysis-relevant material is lost while the ledger claims a compacted window.

## D6 - Failure taxonomy and the loop mitigation

Generation failures map to existing surfaces plus three compaction-specific rules.
The single retry layer is reused: `invoke_with_escalating_timeout` (#73 discipline - escalating budgets, raised attempts and None results retried, exhaustion fails closed to None).
A window-cap 4xx (the request itself exceeding `max_input_tokens`) is TERMINAL for the pass - never retried with identical input, since an identical retry always fails identically.
Consecutive failed passes are counted LOCALLY in the compaction component; at the cap (3) auto-re-attempt STOPS and escalates loud (log + ledger flag + observability).
On exhaustion or cap, the barrier releases on last-known-good: the current context is sent in the request, the ledger keeps the over-budget flag, and the next post-response trigger re-attempts - this is the fail-safe path, and the cap plus the terminal classification are what make the operator-flagged self-containing loop (window-cap failure -> new compaction trial -> same failure) impossible.
A window-cap failure inside the SUMMARISATION call cannot arise from compaction's own shape: the atomic call's input is the material being compacted, bounded by the trail that itself just overflowed a window the summary request fits inside; if a provider nonetheless returns it, it is terminal (above), not looped.

**Rationale.**
Fail-safe "as reliably as possible" (operator ruling) means mapping every failure class to a coverage point rather than a blanket retry: transient classes to the #73 schedule, structural classes to terminal classification, and repetition to the local consecutive cap.

## D7 - Replay-collision precedence: a token-bounded byte-identical tail, profile-gated

The T6 replay pipeline re-persists assistant reasoning byte-identical so the next turn's restored prefix hits the provider KV cache; compaction coordinates rather than competes.
When the T3 profile says `reasoning_in_response` is true, the reasoning within a reserved TAIL slice - `replay_keep_tokens`, default 30k, measured from the trail's end - stays byte-identical.
OLDER replay-eligible reasoning is summarised into the running summary: its KV-cache replay value is negligible and re-payable, and exempting all of it would leave chain-of-thought growth unbounded for exactly the roles that need bounding.
Profile false/None (no reasoning surface) means all reasoning-bearing content is summarisable - there is nothing byte-identical to preserve.
The readability signal (`reasoning_readability`) gains a value reflecting a compaction pass, and the replay report notes it.
The unit contract: the compact pass leaves every byte of the reserved tail identical to its input and reports exactly which spans were exempted versus summarised.

**Rationale.**
This is the seam-to-seam contract between #95 and #109 (D8.1/D11): the precedence is profile-driven (the capability surface decides whether a replay surface exists at all) and budget-driven (the tail slice is the part of the prefix whose byte-identity still buys cache hits).

## D8 - Tool bodies: layered cutting, precise headers, module-owned store, no mem0

A tool-output body under ~700 tokens (approx-counted) stays FULL in context.
A body at or over the cut line is replaced by a HEADER and its full body is offloaded to the module's own store.
The header carries exactly: `tool_call_id`; the tool `name`; the OUTLINE - the command/args verbatim, bounded; the `status` - the outcome marker the tool result records (for the raw terminal tool, the exit code); bounded HEAD and TAIL excerpts of the body (required: the outline alone does not characterise a terminal body, whose informative parts are typically its opening and ending); and the `body_ref` into the module store.
No size field (operator ruling).
Retrieval is exact-ref: the store contract is `put_body(thread_id, tool_call_id, body) -> ref` / `get_body(thread_id, ref) -> body`, injectable per module; a built-in in-process backing serves hermetic tests.
A retrieved body written back into the trail is re-filtered at the next compact pass - it cannot permanently re-bloat.
The model's own transcript verdict (the brief note it writes about a tool result, reasoning or generation) is the in-context record the design leans on; the summarisation prompt instructs it.
Semantic retrieval of bodies is NOT this ticket: it belongs to the unified memory work item (#85, converging on mem0) with semantics-based indexing and domain ontology.
mem0 is evaluated and REJECTED for this ticket's offload: it serves semantic recall, not exact-ref fidelity retrieval, and would centralise what must stay module-owned.

**Rationale.**
The only current tool is the raw terminal, whose payload is the whole command output; cutting past the header is heuristic, so the header must carry the command, the outcome, and the body's head/tail shape - everything else lives in the module store at full fidelity.

## D9 - Consumers: every checkpointer-backed production session agent

The wired consumers are the checkpointer-backed (`create_agent`) production session agents across the modules, so BOTH agent shapes - a tool-calling actor loop and a chained single-shot text generator - are covered, and the middleware is proven orthogonal to the state machine it wraps:

- the hunting hunter's ASYNC lane: `HuntingHunterActor` -> `run_session_agent` -> `arun_session_turn` (a tool-calling mailbox actor);
- the analysis mechanism-typist's CHAINED TEXT-GENERATOR lane: `stateful_invoke_fn` -> `stateful_turn` -> `run_session_turn` (the 3-call reflection/extraction/linking chain over one growing session thread, no tools);
- the H generalisation (ticket #134, ratified 2026-08-18): every remaining checkpointer-backed agent - the analysis assigner + data-modeller (joining the mechanism-typist), the recon-pod configurator + triager (a process-wide per-role middleware, the manager keying state by `thread_id`), and the recon-orchestrator + hunt-orchestrator actors. The wiring is additive at session construction (`middleware`/`middleware_extra`), never agent-logic changes.

The sync `hunt_session` ContextVar rollback lane is NOT wired (counterchecked per the operator's request: `hunting_agent.py`'s dispatch comment states "The actor-backed production seams ignore it - the per-hunt `HuntingHunterActor` already owns that thread"; `actors.py` documents the actor as "replacing the `hunt_session` ContextVar + `stateful_turn` seam, which remains the sync rollback lane").
The one-shot `invoke_role` leaves (bootstrapper, anatomy, curation, sweep, the legacy gate/re-match/decide_routing seams) and the StateGraph-without-checkpointer pipelines (supervisor, pod_graph, job_agent) are NOT compacted - they hold no resumable session thread to compact. The #84 test-executor pod's migration (interim `trim_messages` -> offload + summarise) is a follow-up against this component's client seam.

**Rationale.**
The hunter and the mechanism-typist are implemented and production-bound; the rollback lane must not gain behaviour production does not share. Wiring consumers of different agent shape (tool-calling vs chained single-shot) proves the middleware is orthogonal to the state machine it wraps, not bound to one loop.

## D10 - In-flight generation: post-response only, client-side only

No compaction interposes DURING a generation, and nothing server-side drops content mid-request.
A high-reasoning generation is bounded by the provider's own output limit; the growth it causes is caught by the post-response compaction plus the next-turn barrier.
A lower pre-call threshold before high-reasoning calls remains a deferrable tunable; the mechanism is unchanged.

**Rationale.**
Server-side interposition couples the gateway into session state it is architecturally barred from (gateway ADR D3/D4), and a hard drop destroys reasoning and replay byte-identity - the exact failure mode this ticket exists to replace.

## D11 - Observability and full fidelity

A compact pass is observable on the same session trace (`langfuse_session_id`, the D11 item-4 metadata recipe, fail-open): the pass, its reclaimed-token count, and the compaction-reflected readability value ride the existing metadata surface.
`cache_read` / `cached_tokens` are recorded, never load-bearing (gateway ADR D11 item 3).
Compaction bounds only what the agent SEES: the module store keeps the full trail at full fidelity for export/eval, and the checkpointer holds the compacted working set.

**Rationale.**
The observability contract mirrors the reasoning pipeline's: same trace, same fail-open discipline, same never-gating rule for cache telemetry.
