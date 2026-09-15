# Unbounded reasoning (blackloop) recovery (#206) - spec

The recovery capability for the shared LLM session seam: a no-tool session agent that
enters an unbounded reasoning loop on a high-reasoning model must not lose its step.
Status: operator-grilled 2026-09-07. Companion to the #210 window-splitting spec
(`compaction-window-splitting-210-spec.md`), whose chunked progressive-fold seams this
spec wires onto, and to #208 (httpx-reprofile one-pod amplifier removal, independent).

## Problem Statement

A no-tool session agent on a high-reasoning model (`opencode-go/deepseek-v4-flash`) can
enter an **unbounded reasoning loop (blackloop)**: it burns the entire 131072-token
output ceiling (`DEFAULT_MAX_COMPLETION_TOKENS`, `providers.py`) on `reasoning_content`,
never emits the answer, and the turn fails. Diagnosis (posted on #206) confirmed two
shapes, both a genuine blackloop:

- **Shape A - the exception path.** A structured (json_schema/`ProviderStrategy`) turn
  raises `LengthFinishReasonError` (openai SDK, on `finish_reason=length`); the failed
  message is NOT persisted to the checkpointer (the graph aborts the super-step before
  the model node checkpoints); the reasoning exists only on `exc.completion`. The
  recon triager hit this (Langfuse trace `c9b07bd...`, e.g. generation `932c8867321602bc`
  21:44:43->21:49:34). `stateful_turn` fails open to None; the step output is lost.
- **Shape B - the silent-empty path.** A `schema=None` turn returns empty content; the
  failed message IS persisted with its phantom `usage_metadata` (input 22688, cache 60928,
  output 131072, total ~215k). The mechanism-typist reflection hit this (trace
  `1706eec...`, generation `a15cb21f887d0a75`: content EMPTY, a 262k-char self-reassurance
  loop, `"Need maybe mention"` x2066). The phantom usage pins the compaction ledger over
  budget forever -> the compaction-loop (reproduced empirically).

Both shapes share ONE root cause - relentless argumentation that never converges on
emitting the answer - and one recovery seam applies. The codebase-wide blast radius: every
no-tool session role with `thinking != off` - recon `triager` / `configurator` /
`job_orchestrator`, analysis `assigner` / `mechanism_typist` / `data_modeller`, and
structurally hunting's `hunting_hunter` / `hunting_orchestrator` / `pod_runner` /
`pod_triager`.

## Solution

Three mechanisms, applied codebase-wide through the ONE shared session seam
(`stateful_turn`), using native langgraph primitives, without compromising the current
fail-open contract:

1. **Streamed generation is the DEFAULT mode.** Every session turn
   (`run_session_turn` / `arun_session_turn`) runs as a streamed generation: BOTH the
   `reasoning_content` chunks and the generated `content` chunks are streamed and captured
   per chunk. The stream is the sole output path - there is no non-streamed default left
   on the session seam. Captured reasoning is segmented into bounded, window-fitting
   spans (never one un-foldable giant span), so the failed reasoning is **multi-span**,
   exactly the shape #210's progressive fold consumes (seam S2). The generated text is
   likewise streamed chunk-by-chunk, so the answer arrives incrementally and a blackloop
   (reasoning accumulating, no content) is visible in the stream as it happens.
2. **Blackloop detection + cut ride the stream.** While streaming, if accumulated
   reasoning passes a detection bound (configurable, window-threshold-derived) with no
   content chunk emitted, treat the turn as a blackloop: cut the stream and route to the
   recovery turn. The detection is fail-open - a false positive routes to a (cheap)
   recovery; a missed blackloop is caught by the existing
   `LengthFinishReasonError`/empty-content handling.
3. **Recovery turn (bounded fallback).** On the blackloop signature (both shapes),
   `stateful_turn` composes a recovery generation on the same thread: previous context +
   a compacted rendering of the failed reasoning + the verbatim blackloop instruction.
   The recovery is ITSELF a streamed generation (the same streamed chunk-capture applies,
   so it cannot re-blackloop unboundedly and can be cut), under a single bounded attempt
   (no escalating retry - a post-streaming 300s timeout is a network/engine fault caught
   downstream). Its output, together with the failed reasoning, is folded into the running
   summary by the NATIVE turn-end compaction (seam S1) - no second, ad-hoc summary path.
   Fail-open preserved: if the recovery also fails, degrade to None exactly as today.
4. **The compaction-side fixes** that make the thread converge:
   - **`reasoning_content` projection**: render the captured reasoning spans into the
     span text so the summariser sees the reasoning core (seam S2/S4).
   - **Per-message tail bound + usage_metadata repair**: a single message over the
     replay-tail budget is truncated and its `usage_metadata` stripped/repaired so
     `compute_occupancy` walks back to the prior real usage step (verified: truncate-only
     keeps 214688; truncate+strip drops to ~3921). This is what makes nested compaction
     converge for any threshold (seam S3).

## User Stories

1. As a recon triager, I want a blacklooped structured turn to recover into an answer
   instead of failing open to None, so that the pod's observations are not silently lost.
2. As the mechanism-typist, I want a blacklooped reflection to recover into prose instead
   of fail-closing to an empty batch, so that the chunk's Systems batch is not lost.
3. As any no-tool session role, I want the recovery to be automatic on the shared seam, so
   that no per-agent wiring is needed.
4. As the harness, I want streamed generation to be the DEFAULT session mode - both
   reasoning and generated text streamed per chunk - so that a blackloop is visible in the
   stream (reasoning accumulating, no content) and cut before it burns the whole 131072
   ceiling.
5. As the harness, I want the captured reasoning segmented into window-fitting spans, so
   that the compaction fold can chain on it instead of hitting a single un-foldable span.
6. As the compaction pass, I want the failed reasoning rendered into span text, so that
   the running summary features the reasoning core (the latest thought) the actor chains on.
7. As the compaction pass, I want a single oversized message bounded in the tail with its
   usage repaired, so that occupancy re-measures low and the thread converges for any
   threshold (no compaction-loop).
8. As the actor, I want the recovery turn itself streamed (the default mode) and bounded,
   so that a re-blackloop in the recovery is also cut rather than burning the ceiling again.
9. As the actor, I want the recovery turn's output folded into the running summary by the
   native turn-end compaction, so that no second, ad-hoc summary path is introduced.
10. As the caller, I want the fail-open contract preserved - a blackloop must never crash
    the caller, only be recovered or degrade to None.
11. As the operator, I want the recovery observable on the session trace, so that a
    recovered blackloop is visible (fail-open, D11 metadata recipe), not silent.
12. As the operator, I want the recovery to work for every no-tool session role through one
    seam, so that a future role is covered by construction.

## Implementation Decisions

1. **The seam is `stateful_turn`** (`session.py`). The recovery lives at the shared
   entry point every no-tool session role calls; it detects the blackloop signature,
   streams, and composes the recovery - no per-agent changes.
2. **Streamed generation is the default session mode.** `run_session_turn` /
   `arun_session_turn` stream the model turn (`stream`/`astream` on the compiled
   `create_agent` graph, which is a langgraph Pregel graph and supports both). Both the
   `reasoning_content` chunks and the generated `content` chunks are captured per chunk via
   the streamed surfaces (`ReasoningPreservingChatOpenAI` already preserves reasoning; the
   streaming path adds per-chunk capture of both). Captured reasoning is segmented into
   bounded, window-fitting spans (a segmenting cap, window-threshold-based) so a giant
   reasoning is never one un-foldable span. There is no non-streamed default left on the
   session seam.
3. **Blackloop detection + cut ride the stream.** While streaming, if accumulated
   reasoning passes a detection bound (configurable, window-threshold-derived) with no
   content chunk emitted, treat the turn as a blackloop: cut the stream and route to the
   recovery turn. The detection is fail-open - a false positive routes to a (cheap)
   recovery; a missed blackloop is caught by the existing
   `LengthFinishReasonError`/empty-content handling.
4. **Recovery turn composition** (`stateful_turn` internal). On the blackloop signature
   (streamed-cut, `LengthFinishReasonError`, or empty-content), compose a recovery
   generation on the SAME thread: the previous context (already in the checkpointer) + a
   COMPACTED rendering of the failed reasoning (extracted from `exc.completion` for shape
   A, or the returned message's `additional_kwargs` for shape B - both via the existing
   `reasoning.py` extractor) + the verbatim blackloop instruction (below). The recovery is
   itself a streamed generation with the same chunk-capture + cut, under a single bounded
   attempt. Its output and the failed reasoning are folded by the native turn-end
   compaction (seam S1) - no ad-hoc summary.
5. **`reasoning_content` projection into span text.** `summary._span_text` /
   `_text_of` additionally render `additional_kwargs.reasoning_content` (and
   `provider_specific_fields.reasoning_details`), so every summariser span sees the
   reasoning core (seam S2/S4). One seam, no handler-side duplication.
6. **Per-message tail bound + usage_metadata repair** (`compaction.py` `_exempt_tail_size`
   and the pass assembly): a single message whose content exceeds the replay-tail budget
   is truncated to a bounded excerpt AND its `usage_metadata` is stripped/repaired, so
   `compute_occupancy` walks back to the prior real usage step and the thread converges
   (seam S3). Never reserved wholesale; never a D8-offload for AIMessages (D8 stays for
   tool bodies).
7. **The verbatim blackloop instruction** (prompt content, crafted with the prompt-
   engineering patterns - system-vs-user split, explicit termination):
   "You are resuming an agent step whose previous reasoning turn entered an unbounded
   thinking loop and produced no answer. Your job is to END THIS STEP NOW, not to continue
   thinking. Ablate every corollary and surrounding thought you were entertaining: they are
   the loop. State, in the required output format, the single most defensible conclusion
   your prior reasoning converged on, with the briefest supporting evidence, then STOP. Be
   goal-oriented: the workflow needs this step's result, not more deliberation. Do not
   restate your loop; do not enumerate what you considered; do not ask what to do next.
   Produce the answer directly and finish."
   This rides the USER turn of the recovery generation, appended to the compacted failed
   reasoning.
8. **Scope - every no-tool session role** through the one seam: recon
   `triager`/`configurator`/`job_orchestrator`, analysis `assigner`/`mechanism_typist`/
   `data_modeller`, hunting `hunting_hunter`/`hunting_orchestrator`/`pod_runner`/
   `pod_triager`. Tool-bound loops (the crawler's vendored ReAct) are out of scope.
9. **Native langgraph primitives**: the recovery uses `agent.update_state` /
   `agent.stream` and the middleware/state surfaces already on the seam - it does not
   bypass langgraph, and it preserves the existing `stateful_turn` fail-open contract.
10. **Observability (D11 metadata recipe, fail-open)**: the recovery records a
    `blackloop_recovery` field on the session trace metadata (shape, whether the recovery
    produced output, the cut point), mirroring `reasoning_readability` /
    `compaction_readability`. Never gating.

## Coupling Seams (#210 - blocking edges)

- **S1 (C1/C2)** - over-window threads produce a chainable running summary via the
  progressive chunked fold, never `terminal`. The recovery turn's compaction rides this.
- **S2 (C3)** - span-granular, reasoning-agnostic chunking; a projected-reasoning span
  passes through unmodified. #206's streamed multi-span capture + projection feed this.
- **S3 (C5)** - deterministic bounded chunk size = window threshold fraction. #206's
  convergence bound rides this.
- **S4 (C6)** - the reasoning core (latest thought) survives the fold; the actor chains on
  it.

#206's implementation HOLDS until #210 lands (operator ruling 2026-09-07); S1-S4 are
blocking edges. #208 is independent (amplifier removal).

## Testing Decisions

- The unit tier drives the pure mechanics with the LLM and gateway mocked (no live model,
  no live gateway, no DB - CODING_STANDARD sections 6, 10): the recovery-turn composition
  (both shapes), the streamed chunk-capture segmentation, the blackloop detection/cut, the
  reasoning projection into span text, the per-message tail bound + usage_metadata repair,
  and the convergence guarantee (post-pass occupancy < budget). Prior art: `_good_summariser`
  fake pattern in `tests/test_llm_compaction.py`, `tests/test_llm_summary.py`, and the
  session/compaction seam tests.
- The contract catalogue (C1..Cn of this spec) lands in the integration tier.
- A live walkthrough (a blackloop -> streamed cut -> recovery turn -> native compaction ->
  a converged thread under budget) lives in e2e, in-network, once #210 lands.

## Out of Scope

- #210's chunked progressive-fold seam itself (C1-C6), the negotiated-method str-drift fix,
  and the `_text_of` reasoning rendering if it lands as a #210 change - #206 couples to it,
  it does not own it.
- #208's httpx-reprofile one-pod refactor (independent amplifier removal).
- Mid-stream progressive summarisation (deferred, #210 Decision 8).
- The tool-bound crawl loop and the one-shot `invoke_role` roles (not on the session seam).

## Further Notes

- The uncommitted `providers.py` change (triager `medium`->`low`) is INEFFECTIVE against
  the amplifier when the model offers only `high` (verified: `low` also falls back to
  `high`) - it is not a substitute for this recovery capability.
- `.env` sets `LLM_COMPACTION_THRESHOLD=0.2` and `LLM_GATEWAY_URL=http://localhost:4000`
  (gateway container down; capability reads degrade to env->default) - the convergence
  guarantee must hold for any threshold, not only the default 0.90.
- Streaming as the default session generation mode is the largest new mechanism; its
  feasibility is confirmed (the compiled `create_agent` graph streams;
  `ReasoningPreservingChatOpenAI` preserves reasoning). The #40465 opencode-go reliability
  issue (flash connection drop) is a known risk to flag for the live walkthrough.
