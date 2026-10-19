# Skills system - execution FSM (orchestrator plan)

*Status: live control document for the skills-system feature area. The orchestrator updates it at every state transition. It never overrides the decomposition map (`docs/design/skills-system-decomposition.md`), the decision records (`docs/design/skills-taxonomy-decisions.md`), or the completion ledger (`docs/design/w0-w1-completion-ledger.md`).*
*It exists so the stream's execution is auditable: states, entry gates, evidence on exit, and the stop conditions.*

## Invariants

1. One feature-area trunk: `feat/skills-system`. Single work-item branches integrate from and to it. The trunk reaches `dev` only once, at the end, as a human-merged PR.
2. Every work item: subagent implementation, exactly one critical adversarial review round at its end, merge to the trunk, machine checks. No re-review loops; review findings are fixed once, nothing unrequested is built.
3. Evidence over intent: every transition names its evidence (commit hash, check output, review verdict).
4. The orchestrator stops and reports on: degraded execution, missing dependency, an operator-ruled decision, or goal completion.

## States

| State | Meaning | Exit evidence |
|---|---|---|
| S0 | B1 grilling closure (3 rounds; decisions compiled) | `docs/design/skills-taxonomy-decisions.md` committed on the trunk (DONE) |
| S1 | Trunk assembly: W0 landing + W0/W1 completion + W2 cortex integrated | merge commits on `feat/skills-system`; `verify.sh` FAIL-free (DONE) |
| S2 | Residual wave: W1-taxonomy (B1, B3/B4 records), W0-parent-conformance (B2), W2-refresh | DONE 2026-10-18: all three merged after their single review rounds and fix passes; `verify.sh` NO-FAILURES (1 pending: the C1 families) |
| S3 | W3: four rulings (round 1), remaining grill points (round 2), ADR compiled, then prompt surgery + validity gate | DONE 2026-10-18: both rounds closed (D-W3-1..D-W3-8); merged `b42a19d9` after the single review round (CLEAR: 0 blockers, 0 majors, 11 minors absorbed in the one fix pass) |
| S4 | W4: nested-taxonomy loader (flat-leaf identity, uniqueness hard error, level-2 nesting, logical root mount, scaffold, conformance tests, README) | DONE 2026-10-18: merged after the single review round (CLEAR); 16 conformance tests green; the wider targeted suites green; `verify.sh` NO-FAILURES (1 pending: C1) |
| S5 | W5: artifact `skills` field, `load_skill` descriptions command, runtime rendering, agent workflows (C5, workflow ticket #236); per the 2026-10-18 ruling: the pod runner/triager prompt refactoring plus the skills loading/listing binding for all four hunting-module agents | DONE 2026-10-18: merged `ac48b90b`; the review returned BLOCKED on two majors (the hunting CONTEXT.md drift; the triager-variant skill drop), both fixed in the one fix pass; the wider suites green; `verify.sh` NO-FAILURES (1 pending: C1 families) |
| S6 | W6: `defence-bypass` and `proxy-techniques` families (C1) + cross-reference wiring (C2) | DONE 2026-10-19: merged `155b6ed9`; the review returned CLEAR (one major scope call ruled by the operator: fix the concrete misses); `verify.sh` ALL-CHECKS-PASS (zero pending) |
| S7 | W7: C4-full enrichment (D1a proposal report first, operator-assessed; then D1b surgical pass, D1c references/scripts) | DONE 2026-10-19: merged `e27beada`; the review returned BLOCKED on two majors (the R5 leaf renames; the README record), both fixed once; `verify.sh` ALL-CHECKS-PASS; the suite stands at 165 skills |
| S8 | Final integration: trunk to `dev` as one PR (human-merged) | IN PROGRESS 2026-10-19: the operator's finalization decisions recorded (the enriched suite replaces the live catalogue root; #388 lands before the integration; the quiescence question pending); #388 dispatched; next the mount replacement, the documentation alignment, then the PR go |

## Ordering constraints

- S4 requires S2 (the W1 taxonomy spec is its direct input).
- S5 requires S4; S6 requires S5 (operator sequence); S7 requires S6 plus the D1a operator gate.
- S3a (prompt surgery) starts once the four rulings are answered; S3b (the validity gate) waits for the W1 taxonomy freeze from S2.

## Transition gates

- **G-review**: exactly one adversarial review round per work item, at its end, before integration; findings fixed once.
- **G-verify**: the relevant machine check is FAIL-free before any merge; the completion `verify.sh` must end at `ALL-CHECKS-PASS` before S8.
- **G-operator**: the gate items recorded in the ledger (B1 taxonomy grilling, B2 parent ruling, D1a enrichment report, A1 status wording) plus every question the orchestrator raises.

## Feedback loop

After each merge into the trunk: run `verify.sh`, update the completion ledger rows with pasted output, update the map's status rows, and record the transition here. Any FAIL or review BLOCK holds the state and is reported to the operator with the evidence.

## Current pointers (2026-10-18)

- Trunk: `feat/skills-system` (worktree `.claude/worktrees/feat-skills-system`); tip: the W7 merge `e27beada`; contains W0 landing, W0/W1 completion, W2 cortex, W3, W4, W5, W6, W7 (165 suite skills).
- S2: COMPLETE - all three residual items merged after their single review rounds (W2, W0, W1).
- S3: COMPLETE - both rounds answered and recorded (`skill-evolution-w3-decisions.md`, D-W3-1..D-W3-8); merged `b42a19d9` after review CLEAR with the one fix pass absorbed.
- S4: COMPLETE - the W4 mount seam merged after review CLEAR (`7ac935d6`).
- S5: COMPLETE - merged `ac48b90b` after the review BLOCKED on two majors, both fixed once (the hunting CONTEXT.md reconciliation; the triager-variant skill inheritance).
- S6: COMPLETE - merged `155b6ed9`; review CLEAR with one operator-ruled scope call; `verify.sh` reached ALL-CHECKS-PASS.
- S7: COMPLETE - merged `e27beada`; review BLOCKED on two majors, both fixed once; the suite stands at 165 skills.
- S8: IN PROGRESS - the trunk carries W0-W7 and `verify.sh` is ALL-CHECKS-PASS; the operator's finalization decisions are recorded; #388 (the layout normalisation) is in flight; then the mount replacement (the suite into the live root), the documentation alignment, and the PR go.
- Open operator gates: the quiescence-question answer (see the map); the final PR go.
