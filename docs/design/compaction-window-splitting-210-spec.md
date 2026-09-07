# Compaction summariser robustness (#210) - window-splitting spec

The capability contract the running-summary engine (#95, ADR D5/D6) must offer so an
over-window thread still produces a chainable running summary, and so #206's
blackloop-prevention recovery turn can fold a failed reasoning turn into the native
turn-end compaction. This spec is the seam #206 wires onto.

Status: operator-grilled 2026-09-07 (the window-splitting direction of #210, Track B).
Companion to the ADR amendments in `context-compaction-95-decisions.md` (D5/D6) and
`capability-adaptive-client-99-decisions.md` (A1, the str-drift Track A fix).

## Problem Statement

A thread whose trail exceeds the model window (e.g. a failed 131k-token reasoning turn
plus context, see #206) makes the summariser's own input 400 with `context_length_exceeded`.
Today `classify_terminal` maps that to the `_TerminalWindowError` sentinel and `summarise`
returns status `terminal` (`summary.py:459-463`) - the thread stays over budget with no
summary, forever. #206's convergence argument ("the thread converges under budget for any
threshold") is false while this terminal path exists.

## Solution

Window-splitting summarisation: when the summariser's composed input would exceed the
model window, split the ordered spans into window-fitting chunks (span-granular, never
mid-span) and fold them progressively - each chunk's summary becomes the next chunk's
prior (`existing`), so the final fold is the single chainable running summary the actor
chains on. The terminal path is retired: an over-window multi-chunk input is never
terminal; the only irreducible exit is a single span still exceeding the window, which
degrades to `failed` (never `terminal`).

## User Stories

1. As a long-horizon session agent, I want a thread whose trail exceeds the model window
   to still produce a running summary, so that my compaction converges and the thread
   does not stay over budget forever.
2. As the #206 recovery turn, I want the native turn-end compaction to fold a
   blacklooped over-window reasoning turn into a running summary the actor can chain on,
   so that the recovery does not depend on a second, ad-hoc summary path.
3. As the #206 reasoning projection, I want the chunker to preserve each rendered
   reasoning span unmodified and un-split, so that streamed chunk-captured reasoning
   folds progressively rather than being truncated or merged.
4. As the compaction manager, I want a mixed-outcome chunked pass (some chunks folded,
   a later chunk failed) to still report a chainable summary, so that applying a partial
   summary is strictly better than leaving the thread over budget.
5. As the compaction manager, I want a window-cap never to burn the escalating retry
   budget on an identical always-fail input, so that the pass degrades promptly to the
   fail-safe path.

## Implementation Decisions

1. **The chunk loop lives inside `summarise`** (replacing the single
   `build_summary_messages` + invoke). `compaction.py`'s pass assembly never sees a
   chunk - it composes one `summarise` call with the region's spans and the caller's
   resolved window. The terminal path is retired at the atomic-call level (seam #1 with
   #206).
2. **Span-granular, order-preserving chunking.** A span/message is never split; a chunk
   is a prefix of the ordered span list. The chunker never inspects `reasoning_content`.
   When #206 lands its projection + streamed chunk-capture, the failed reasoning arrives
   as multiple window-fitting spans, each a foldable unit; the never-split rule is what
   preserves them (seam #2 with #206).
3. **Progressive / nested fold (C2).** Chunk k's `SummaryUpdate` folds into chunk k+1's
   `existing`; the final fold's `RunningSummary.to_text()` is the single chainable
   summary. Ordering is deterministic - chunks are processed in span order. This is the
   #206-consumed mechanism.
4. **Per-chunk retry under the single #73 discipline.** Each chunk runs under
   `invoke_with_escalating_timeout`; a window-cap escapes the retry via the
   `_TerminalWindowError` sentinel (never burning retries on identical input) but is
   translated to a chunk failure. A chunk that exhausts retries aborts the pass.
5. **Mixed-outcome reporting (no new enum value).** `CompactReport.summary_status` stays
   `Literal["ok", "failed", "terminal"]`; `terminal` is retired. A chunked pass reports
   `ok` whenever a chainable `RunningSummary` exists (even a partial fold from the
   succeeded prefix), `failed` only when no summary at all. `apply_staged`/streak logic
   is unchanged - it just sees `ok` more often.
6. **Deterministic bounded chunk size (C5).** Chunk composition re-measures
   `approx_tokens` on the composed `(existing + chunk)` messages against the caller's
   resolved window budget (`window.budget = threshold * context_limit`), per chunk,
   because the existing summary grows each fold. The first chunk is re-measured against
   the incoming `existing`. The bound is the compaction window's threshold fraction, not
   an implementation accident.
7. **Irreducible single-span overflow degrades to `failed`** (operator ruling, grey
   point 4), never `terminal`. The `classify_terminal` + `_TerminalWindowError`
   machinery is retained for escaping the retry wrapper and for observability.
8. **The chunk driver consumes the trail's rendered spans at compaction turn-end**
   (operator ruling, streaming alignment): no mid-stream summarisation is built; #206's
   streamed chunk-capture just makes the reasoning multi-span, which the progressive
   fold already consumes.

## Capability contract (acceptance criteria - the seams #206 consumes)

- **C1 - never terminal on window overflow.** A thread whose trail exceeds the model
  window still produces a running summary via progressive chunked summarisation; the
  `_TerminalWindowError` -> status `terminal` path is unreachable for the over-window
  input shape. The only irreducible exit is a single span that still overflows, which
  degrades to `failed`. [feeds #206 recovery-turn compaction]
- **C2 - progressive fold across chunks.** Chunk k's `SummaryUpdate` folds into chunk
  k+1's `existing`; the final fold's `RunningSummary.to_text()` is the single chainable
  summary; ordering is deterministic. [feeds #206 recovery-turn compaction]
- **C3 - span-granular, reasoning-agnostic chunking.** Chunk boundaries at message/span
  granularity; never mid-span; never inspects `reasoning_content`; a projected-reasoning
  span (the #206 fix, landing later) passes through unmodified. [feeds #206 reasoning
  projection]
- **C4 - per-chunk quality gate.** `is_quality_summary` applies per chunk under the
  grilled semantics (grey point 3): each chunk is retried under the #73 schedule; a
  chunk that exhausts retries aborts the pass; a weak chunk never yields a terminal pass.
- **C5 - deterministic bounded chunk size.** Chunk composition re-measures
  `approx_tokens` per chunk against the model window (the existing-summary growth is
  accounted); the bound is the window's threshold fraction. [feeds #206 convergence
  bound]
- **C6 - the reasoning core survives the fold.** Per the accumulate clause, the fold
  preserves the blacklooped reasoning's conclusion (the "latest thought") across chunks,
  so the #206 actor chains on it. [feeds #206 recovery-turn compaction]

## Testing Decisions

- The unit tier drives the pure mechanics with the LLM and gateway mocked: the
  negotiated-method routing (Track A), the chunk-boundary rule, the progressive fold,
  the per-chunk quality gate, the bounded chunk size, and the never-terminal
  guarantee. No live model, no live gateway, no DB (CODING_STANDARD sections 6, 10).
- Prior art: `tests/test_llm_summary.py` (the D5/D6 atomic-call taxonomy), the
  `_good_summariser` fake pattern in `tests/test_llm_compaction.py`.
- The contract catalogue (C1-C6) lands in the integration tier; a live walkthrough (an
  over-window thread -> chunked progressive summarisation -> a single chainable
  `RunningSummary`, never `terminal`) lives in e2e.

## Out of Scope

- #206's recovery turn, the `reasoning_content` projection in span rendering, and the
  per-message tail bound - these are #206's speced fixes; this spec only documents the
  seam the chunker guarantees about rendered spans.
- #208's httpx-reprofile one-pod refactor - independent amplifier removal, not this
  domain (the LLM layer only).
- Streamed mid-turn progressive summarisation - explicitly deferred (operator ruling).

## Further Notes

- The str-drift fix (Track A) is a separate, local change in the same branch: route
  `build_summariser` through `structured_output_for` with the negotiated method. It
  needs no spec - it adjusts the ADR A1 record in the same change.
- The chunk driver is span-granular and reasoning-agnostic by construction, so #206's
  projection landing upstream is carried through untouched.
