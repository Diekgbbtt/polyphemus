# ADR: a non-converging compaction pass must count toward the pass cap

**Status:** Accepted (2026-10-09).
**Issue:** #348 (EV-33).
**Owns:** the D6 consecutive-pass cap in `app/llm/compaction.py`.
**Supersedes:** nothing; it narrows D6 (`context-compaction-95-decisions.md`) which counted only FAILED passes.

## Context

The 2026-10-07 eval token forensics (Langfuse observations v2) surfaced two cache-hostility defects:

- `mechanism_typist` on jetlinks-1 #2 burned **43.1M uncached** input against **19.0M cached** (30.6% cached) - the largest fresh-input burner of any role.
- `job_orchestrator` on prestashop-1 made **30 consecutive calls averaging ~245K uncached tokens each** with `input_cache_read = 0`; white-jotter-1 `hunting_hunter` had 79 such calls.

The provider does cache these sessions: the first ~16 `job_orchestrator` calls cached normally (a growing 4.7K -> 32.6K cached prefix). The zero-cache burst began exactly when the thread crossed the compaction budget, and every cold call is preceded by a compaction running-summary call.

## Root cause (per role, one mechanism)

Both roles are checkpointer-backed session agents wired to the compaction middleware (`build_role_compaction_middleware`, D9). The eval environment sets `LLM_COMPACTION_THRESHOLD=0.2`, so the budget is `0.2 * 1_000_000 = 200K` tokens (`max_input_tokens=1000000` for `opencode-go/deepseek-v4.1-flash`).

A single large recent message - a `mechanism_typist` chunk prompt, a `job_orchestrator` terminal tool result - is larger than the exempt replay tail (`replay_keep_tokens=30K`). D7 exempts that tail from summarisation and offload, so the pass can fold the small older region but can never bring the thread under the 200K budget.

`apply_staged` reset the consecutive-pass streak to zero on every "successful" pass, and `_settle` only counted FAILED passes toward the cap. A pass that produced a summary but left the thread over budget therefore looked like a recovery: the next model call re-triggered the barrier, which ran another pass, regenerated the running summary (the first message of the compacted trail), and changed the request prefix from the very first token. The provider prefix cache was invalidated on every call, forcing a full re-prefill - the observed 30-calls-cached=0 shape. The D6 design already intended the cap to make this loop impossible; the gap was that a non-converging success reset the cap.

## Amendment (2026-10-10) - a SECOND, independent mechanism produced the same `mechanism_typist` 30.6% number

**Status:** this ADR's Decision and root cause stand unchanged; this amendment records that they did not explain the whole symptom for `mechanism_typist`, and that a second mechanism was subsequently found and fixed there. Nothing above is superseded.

**What this ADR fixed.** The compaction loop above is real and it is what the cap now bounds. It applies to a thread that has crossed the budget.

**What it did not explain.** `mechanism_typist`'s trail `SystemMessage` re-add was a separate defect that fired from call 1, budget or no budget. The role prompt was re-sent as a `SystemMessage` at the end of every turn's message list, so each call appended a fresh copy at a SHIFTING position:

| call | system-message offsets in the request |
|---|---|
| 1 | 0 |
| 2 | 0, 3 |
| 7 | 0, 3, 6, 9, 12, 15, 18 |

Rebuilding the exact request through the production seam (`run_session_turn` with a recording model, per `converged-agent-turn-adr.md`) shows the flat form for the assigner and the quadratic form for the typist, whose skill is the largest of the three prompts:

| role | per-call input (chars) | best fit | curvature |
|---|---|---|---|
| `mechanism_typist` | 2,468 / 6,053 / 11,042 / 18,126 | quadratic | +3,263 per call² |
| `assigner` | ~4.7K, flat | - | - |

So the 30.6% figure has TWO contributions: the compaction loop (this ADR, now capped) and the prompt stacking (now fixed by the converged seam). Neither fix alone recovers the cache, because a prefix is only reusable when BOTH the loop is bounded and the leading block is byte-identical.

**The fix and its ruling live elsewhere**: `docs/design/converged-agent-turn-adr.md` (the amended choice, the measured curves, and the rejected alternative of collapsing the three-call chain) with the reusable client-side rule in `statefulness-pattern-matrix.md` OUTLIER-5.

**A consequence for this ADR's own deterministic harness.** The harness measures the longest common message-prefix between consecutive requests. With the prompt re-sent in the trail, that metric reported a non-zero overlap even where nothing was cacheable, because a whole trailing `SystemMessage` block matched by coincidence of content. The overlap column above is therefore an UPPER bound on the real prefix for the `before` case. The `after` column is unaffected, since a bounded loop and a stable head make the two measures agree.

## Decision

A compaction pass that leaves the thread over budget is NOT a recovery. `apply_staged` now re-measures the applied trail and, when it is still over budget, counts the pass toward the consecutive-pass cap via `_note_failure` instead of resetting the streak. Only a pass that reaches the budget resets the streak and clears the escalation flag.

After `CONSECUTIVE_PASS_CAP` (3) non-converging passes, auto-spawn and the barrier backstop stop, the trail stabilizes on last-known-good, and every subsequent call appends to an unchanged prefix - so the provider cache hits again. A later converging pass (or the thread recovering under budget) resets the cap as before.

## Measured effect

The live before-fractions are from the 2026-10-07 harvest (`agg3.py` over Langfuse observations):

| role | trial | cached | uncached | cached fraction (before) |
|---|---|---|---|---|
| `mechanism_typist` | jetlinks-1 #2 | 19,014,016 | 43,126,293 | 30.6% |
| `job_orchestrator` | prestashop-1 | 6,348,928 | 7,848,729 | 44.7% (30 calls cached=0) |

A deterministic harness (`CompactionManager`, reasoning profile, a 200K-char tool result pinned in the exempt tail, a new turn per call) reproduces the loop and measures the cacheable request prefix (the longest common message-prefix with the previous request) and the summary-regeneration count:

| metric | before | after |
|---|---|---|
| request-prefix overlap after the first calls | 0.00 - 0.29 | 1.00 |
| running-summary regenerations over 8 calls | 58 | 3 (the cap) |

The after-fraction cannot be measured on this run's live stack because the run predates the fix; the harness is the deterministic proxy, and the regression test locks it.

## Regression guard

`tests/test_llm_compaction.py::test_non_converging_compaction_stops_after_the_cap` drives the real `CompactionManager` with a trail whose exempt tail dwarfs the budget and a varying summariser. It asserts the summary-regeneration count is bounded by the cap and that the manager escalates. It is red before this change (the summary regenerates every call, streak stays 0) and green after.

## Alternatives rejected

- **Move the running summary to the end of the trail.** A suffix does not help: any genuine fold removes messages from the front, so the request is still not a prefix of the previous one. It also breaks the D7 tail computation and the D7 contract test.
- **Offload oversized tool bodies inside the exempt tail.** Contradicts the explicit D7 contract (`test_profile_with_reasoning_reserves_byte_identical_tail`); the tail is a reasoning-replay guarantee, and rewriting it is a separate design question. Offloading the tail is not needed once the futile loop is capped.
- **Lower the compaction budget / raise the eval threshold.** An environment tuning change, not an app fix; the app must stay cache-sane at any threshold the operator sets.
- **Skip re-summarising when nothing new folds.** The over-budget thread folds new content on each call, so the condition rarely holds; the cap is the correct, general bound.
