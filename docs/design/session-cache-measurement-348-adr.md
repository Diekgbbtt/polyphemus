# Measurement: does #348 raise the session cache fraction enough for a 4M capped budget?

**Status:** Measurement record (2026-10-09), small-n harness.
**Informs:** the pre-eval decision on whether the #348 fix (`dev` @ `6b0c9b5`) lets a 4M `capped_tokens` budget reach the test-executor pods, or whether the analysis control plane needs a lower-level refactor.
**Related:** `docs/design/compaction-cache-convergence-348-adr.md` (the fix), `docs/design/eval-budget-axis-adr.md` (#347, `capped_tokens = generated + uncached`).
**Harness:** `tools/measure_session_cache.py` (untracked tool, in this worktree).

## Summary

| Attribute | Value |
|---|---|
| Experiment | post-#348 session cache fraction vs a pre-#348 emulation, on the real stateful session seam |
| Status | Inconclusive on a powered basis; directionally clear |
| Duration | 2026-10-09 (one session, 4 primary runs + 5 exploratory) |
| Sample size | mechanism_typist 11 calls/run; hunting_orchestrator 8 calls/run; 2 runs each arm |
| Owner | measurement subagent |
| Design doc | this file |

## Hypothesis recap

**Original hypothesis:** the #348 fix (count a non-converging compaction pass toward the D6 cap) raises the provider prefix-cache fraction enough that a 4M `capped_tokens` budget reaches the test-executor pods.

**Rationale:** a non-converging pass regenerates the volatile running-summary message on every model call, changing the request prefix and forcing a full re-prefill.
`capped_tokens = generated + uncached` (#347); cached input does not consume the budget, so the whole question is the cache-hit rate.
The fix caps regeneration at `CONSECUTIVE_PASS_CAP` (3), after which the prefix stabilises and the provider cache hits again.

**Success criteria (not met as a powered test):** a materially higher cache fraction and lower uncached-per-call post-fix, on both agents, from a harness that reproduces the trigger.
This harness is a deterministic proxy, not a powered experiment.

## Method

The harness drives the REAL session path directly:

- `polymerhus.app.llm.session.stateful_turn(role, address, [msg], checkpointer=MemorySaver(), schema=..., middleware=[build_role_compaction_middleware(role)], usage_scope=PROJECT)`.
- mechanism_typist mirrors `analysis/mechanism_typist.py::stateful_invoke_fn`: the role skill rides a per-turn `SystemMessage`, and the `HumanMessage` is built by the real `_reflection_prompt` over a synthetic `Chunk` of realistic Endpoint assets (method/path/content_type/title/status/server/content_length) plus triager Observations.
- hunting_orchestrator mirrors `attack/hunting/actors.py`: the `HuntingOrchestratorSession` address, the real `_compose_gate_prompt` over a synthetic `GateInput` (DeliveredCandidates + fault materialisation + fold family + prior minted keys), and the real `_gate_skill`.
- Per model call it records `usage_ledger().snapshot(PROJECT)["by_agent"][role]` deltas (uncached, cached, generated) and the compaction ledger's occupancy, streak, escalation, and applied-pass count.

### Reproducing the #348 trigger (the scaling decision)

The eval runs `LLM_COMPACTION_THRESHOLD=0.2`, `max_input_tokens=1000000` (budget 200K), `replay_keep_tokens=30000`.
The eval trigger is a recent message larger than the D7 exempt replay tail, so a pass folds the older region but cannot bring the thread under budget.

Running that shape live needs ~200K-token contexts per call, so the harness scales the window down while keeping the trigger identical in kind:
the exempt replay tail is made to dwarf the budget, which the #348 ADR's own deterministic harness used ("a trail whose exempt tail dwarfs the budget").
The primary runs use `budget = 1500` tokens (seeded `context_limit=150000`, `threshold=0.01`) with `replay_keep_tokens` of 8000 (mechanism_typist) or 30000 (hunting_orchestrator), and recent messages of ~4K tokens.

The mechanism is scale-invariant: the pass folds the older region, the pinned tail keeps the thread over budget, and the summary is regenerated on every call pre-fix versus capped at 3 post-fix.
The uncached reduction from a stable prefix GROWS with the retained-context-to-fresh-message ratio, so this scaled harness UNDERSTATES the eval-scale benefit.

### Deviations from production (documented)

- Gateway down: `LLM_GATEWAY_URL` is popped; `build_chat_model` runs direct per-provider mode.
- Capability profile seeded into `capability._PROFILE_CACHE` with the eval gateway record facts (`context_limit`, `reasoning_in_response=True`) plus the eval's required `LLM_CAPABILITY_OVERRIDES` booleans (`supports_structured_output=false`, `supports_forced_tool_choice=false`). Without this the D7 tail is empty and the trigger is hidden.
- `LANGGRAPH_STRICT_MSGPACK=false` so a structured `GateDecision` re-hydrates across turns in the in-memory `MemorySaver` (the eval uses `AsyncPostgresSaver`).
- mechanism_typist holds schema `None` (the reflection-call shape) for every turn; hunting_orchestrator holds `GateDecision` (the hypothesise-turn shape). The schemas are held constant to isolate the compaction-prefix variable. The real chains alternate schemas.
- Every run's message content is salted with the run tag, so no provider prefix cache leaks across runs except the byte-stable role skill.
- `--mode pre` monkey-patches `CompactionManager.apply_staged` to reset the consecutive-pass streak on every applied pass (the pre-#348 behaviour). Failed passes still count toward the cap, exactly as pre-#348 did.

## Results

### Primary metric: cache fraction (cached / (cached + uncached))

| Role | Run | Calls | Uncached | Cached | Cache fraction | Summary regens |
|---|---|---|---|---|---|---|
| mechanism_typist | live pre-#348 (comfyui-1, #348 ADR) | 64 | 4,923,972 | 945,024 | 0.161 | n/a |
| mechanism_typist | harness pre (emulated) | 11 | 132,370 | 28,160 | 0.175 | 8 |
| mechanism_typist | harness post | 11 | 88,791 | 167,168 | 0.653 | 3 |
| hunting_orchestrator | live pre-#348 (comfyui-1) | 21 | 912,544 | 0 | 0.000 | n/a |
| hunting_orchestrator | harness pre run A | 8 | 447,354 | 298,240 | 0.400 | 4 |
| hunting_orchestrator | harness pre run B | 9 | 256,184 | 537,088 | 0.677 | 1 (see Known issues) |
| hunting_orchestrator | harness post run A | 8 | 402,632 | 483,328 | 0.546 | 3 |
| hunting_orchestrator | harness post run B | 8 | 377,154 | 370,176 | 0.495 | 3 |

The post-fix summary regeneration is exactly 3 in every post run (the `CONSECUTIVE_PASS_CAP`), then stops; the emulated pre-fix regenerates on every foldable turn. This is the direct signature of the fix.

### Steady state (post-cap turns only)

The aggregate includes warm-up turns before the thread crosses the budget and the broken window before the cap. The steady state is the deciding shape for a 64-call eval run.

| Role | Arm | Steady turns | Mean unc/call | Cache fraction (last turn) |
|---|---|---|---|---|
| mechanism_typist | pre | 8 | 15,149 | 0.109 |
| mechanism_typist | post | 5 | 6,657 | 0.864 |
| hunting_orchestrator | pre | 4 | 89,948 | 0.440 |
| hunting_orchestrator | post | 2 | 29,758 | 0.850 |

mechanism_typist steady unc/call falls from ~15.1K to ~6.7K (2.3x); hunting_orchestrator steady unc/call falls from ~89.9K to ~29.8K (3.0x).
The cache fraction roughly doubles to quadruples.

At eval scale the retained context is ~200K and the fresh delta is small, so the unc reduction is far larger than the harness's 2-3x.

### Budget axis

`capped_tokens = generated + uncached`. Generated output is roughly unchanged by the fix.
The fix reduces capped tokens only through the uncached input, so the steady-state unc reduction is the whole budget effect.

The #348 fix does not shrink uncached to zero: the fresh user message and any regenerated summary are still uncached. Post-cap the prefix beyond the fresh delta is cached.

## Guardrails

- Provider spend: the primary and exploratory runs total roughly 5.4M tokens (uncached + cached + generated), the direct-provider cost well under one US dollar at the configured lane's rates. No gateway cost guard applies in direct mode.
- No secrets were printed; the harness reads `API_KEY_OPENCODE_GO` from the sourced `.env` and never logs it.
- The harness is small (5-11 calls/run) and makes a bounded number of summariser calls (one per applied pass).

## Segment analysis

The two roles differ in the retained-context-to-fresh-message ratio, which sets the ceiling on the cache fraction:

- mechanism_typist has a small retained tail (8K) and a ~4K fresh message, so the fresh delta is a large share and the harness cache fraction settles ~0.65-0.86.
- hunting_orchestrator has a large retained tail (30K) and accumulated context, so the stable prefix dominates and the harness cache fraction settles ~0.82-0.85 post-fix.

Both segments move the same direction.
The hunting pre-fix segment is noisy (one run's summariser failed repeatedly, see Known issues).

## Raw per-call tables

### mechanism_typist post (#348, replay_keep=8000, budget=1500)

| call | unc | cached | ctx | gen |
|---|---|---|---|---|
| 0 | 2,957 | 2,048 | 5,005 | 26,401 |
| 1 | 2,122 | 4,992 | 7,114 | 1,251 |
| 2 | 5,811 | 7,040 | 12,851 | 1,548 |
| 3 | 15,730 | 1,664 | 17,394 | 1,283 |
| 4 | 14,148 | 1,920 | 16,068 | 1,719 |
| 5 | 14,735 | 1,664 | 16,399 | 1,692 |
| 6 | 6,597 | 16,384 | 22,981 | 1,702 |
| 7 | 6,667 | 22,912 | 29,579 | 1,754 |
| 8 | 6,669 | 29,568 | 36,237 | 1,656 |
| 9 | 6,627 | 36,224 | 42,851 | 1,715 |
| 10 | 6,728 | 42,752 | 49,480 | 1,751 |

### mechanism_typist pre (emulated, identical inputs)

| call | unc | cached | ctx | gen |
|---|---|---|---|---|
| 0 | 2,957 | 2,048 | 5,005 | 13,560 |
| 1 | 2,092 | 4,992 | 7,084 | 676 |
| 2 | 5,600 | 7,040 | 12,640 | 1,506 |
| 3 | 15,803 | 1,664 | 17,467 | 1,341 |
| 4 | 13,988 | 1,920 | 15,908 | 2,387 |
| 5 | 14,709 | 1,664 | 16,373 | 2,731 |
| 6 | 15,622 | 1,664 | 17,286 | 2,128 |
| 7 | 15,973 | 1,792 | 17,765 | 3,149 |
| 8 | 16,434 | 1,792 | 18,226 | 2,367 |
| 9 | 14,504 | 1,792 | 16,296 | 2,461 |
| 10 | 14,688 | 1,792 | 16,480 | 2,595 |

### hunting_orchestrator post (#348, replay_keep=30000, budget=1500)

| call | unc | cached | ctx | gen |
|---|---|---|---|---|
| 0 | 7,630 | 8,192 | 15,822 | 12,768 |
| 1 | 35,370 | 15,616 | 50,986 | 9,352 |
| 2 | 32,046 | 50,944 | 82,990 | 8,568 |
| 3 | 82,392 | 24,576 | 106,968 | 8,322 |
| 4 | 93,398 | 29,440 | 122,838 | 8,428 |
| 5 | 92,280 | 46,848 | 139,128 | 7,964 |
| 6 | 29,804 | 139,008 | 168,812 | 7,822 |
| 7 | 29,712 | 168,704 | 198,416 | 7,760 |

### hunting_orchestrator pre (emulated, identical inputs)

| call | unc | cached | ctx | gen |
|---|---|---|---|---|
| 0 | 7,630 | 8,192 | 15,822 | 1,914 |
| 1 | 16,964 | 15,616 | 32,580 | 10,886 |
| 2 | 33,046 | 32,512 | 65,558 | 8,192 |
| 3 | 29,922 | 65,536 | 95,458 | 8,190 |
| 4 | 93,270 | 17,920 | 111,190 | 7,732 |
| 5 | 89,818 | 36,864 | 126,682 | 7,628 |
| 6 | 89,010 | 52,736 | 141,746 | 7,320 |
| 7 | 87,694 | 68,864 | 156,558 | 7,434 |

## Learnings

1. The #348 cap fires exactly as designed. Post-fix every run stops regenerating the running summary after 3 applied non-converging passes; the pre-fix emulation regenerates on every foldable turn.

2. The cache fraction rises materially for mechanism_typist, the largest fresh-input burner. Aggregate 0.175 pre to 0.653 post at matched scale; steady-state unc/call 15.1K pre to 6.7K post.

3. The unc reduction scales with context size. In the eval the stable prefix is ~200K tokens and the fresh delta is small, so the harness's 2-3x understates the eval benefit.

4. The hunting_orchestrator harness is noisy. The summariser occasionally fails a pass (status `failed`), which counts toward the cap in BOTH arms, so one pre-fix run converged like post-fix. This is a harness/relay reliability limit, not evidence against the fix.

5. The summary regeneration count is the robust signal (3 post vs unbounded pre); the provider cache fraction is the noisy signal, because it depends on provider cache timing that the harness cannot fully control.

## Known issues and gaps

- Small n. 2 runs per agent per arm, 8-11 calls each, not a powered experiment. Do not read the point estimates as precise.
- Scaled window. The budget is 1500 tokens, not the eval's 200K. The trigger is reproduced in kind, not in scale.
- Hunting pre run B is anomalous. Its summariser failed repeatedly (`summary_status=failed`), so the D6 cap fired pre-fix and its cache fraction (0.677) is not a faithful pre-#348 reading. Report it, do not average it away.
- The hunting harness does not reproduce the live 0.0% cache floor. The live floor came from a 30-call burst with a volatile summary; the harness's small scale and stable promoted summary keep the cache above zero even pre-fix.
- Synthesised entities. The eval's real chunk/tool-result text was not reachable from this worktree; the harness synthesises realistic entity text at the observed size.
- Schema held constant. The real agents alternate schemas/tools; the harness holds one request shape to isolate the compaction-prefix variable.

## Recommendation

### Decision: (a) run the eval with the current 4M budget

**Evidence:**

- The fix removes the pathological regeneration loop: 3 applied passes then stop, on both agents, every post run.
- mechanism_typist, the dominant fresh-input burner (4.9M uncached live pre-#348), drops 2.3x in steady-state unc/call in the harness; the live pre-fix cache fraction was 0.161.
- hunting_orchestrator, the 0.0%-cache agent, drops 3.0x in steady-state unc/call in the harness; one of two pre runs was confounded but the post-fix shape is consistent.
- The harness understates the eval-scale benefit because the stable prefix dominates at ~200K context.

**The lower-level analysis-control-plane refactor is NOT warranted by this evidence.**
The #348 cap is the right-height fix: it stops the futile loop and lets the provider cache do its job.

**Conditions on the recommendation:**

- Run the eval with the 4M budget as planned, and read the per-agent cache fractions from the usage surfaces afterward.
- If hunting_orchestrator still shows a near-zero cache fraction at eval scale, investigate its running-summary volatility specifically (a targeted follow-up), not a general control-plane refactor.
- Treat this harness as a go/no-go proxy, not a substitute for the eval measurement.

### If it still falls short after the eval

The named lower-level seam would be the D7 exempt replay tail: the tail is byte-identical by contract and cannot be offloaded, so a thread whose pinned tail alone exceeds the budget can never converge. A refactor there (tail bounding, or a budget-aware tail) is the candidate seam, but the harness did not show it is needed.

## Next steps

| Action | Owner | Due |
|---|---|---|
| Run the eval with the 4M budget and capture per-agent cache fractions | operator | next eval |
| Read mechanism_typist and hunting_orchestrator cache fractions from the usage surface | operator | after the eval |
| If hunting stays cache-hostile, scope a summary-volatility follow-up | operator | conditional |
| Decide whether to promote `tools/measure_session_cache.py` into the test tier | operator | optional |

## Appendix: harness paths

- Harness: `tools/measure_session_cache.py` (untracked).
- Raw JSON for this record was written under `/tmp/measure-*.json` during the run and is not committed.

*Measured on 2026-10-09 from `measure/session-cache` at `dev` @ `6b0c9b5`.*
