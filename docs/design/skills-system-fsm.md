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
| S3 | W3: four rulings (round 1), remaining grill points (round 2), ADR compiled, then prompt surgery + validity gate | rulings answered; ADR committed; W3 subagent done, one review, merge |
| S4 | W4: nested-taxonomy loader (flat-leaf identity, uniqueness hard error, level-2 nesting, logical root mount, scaffold, conformance tests, README) | one review, merge, targeted test suite green, `verify.sh` FAIL-free |
| S5 | W5: artifact `skills` field, `load_skill` descriptions command, runtime rendering, agent workflows (C5, workflow ticket #236) | one review, merge, targeted suites green |
| S6 | W6: `defence-bypass` and `proxy-techniques` families (C1) + cross-reference wiring (C2) | one review, merge, `verify.sh` family check PASS |
| S7 | W7: C4-full enrichment (D1a proposal report first, operator-assessed; then D1b surgical pass, D1c references/scripts) | D1a accepted by the operator; one review, merge, `verify.sh` ALL-CHECKS-PASS |
| S8 | Final integration: trunk to `dev` as one PR (human-merged) | PR open; operator merges |

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

- Trunk: `feat/skills-system` (worktree `.claude/worktrees/feat-skills-system`); tip: the B1 decisions commit; contains W0 landing, W0/W1 completion, W2 cortex.
- S2: COMPLETE - `feat/w2-cortex-refresh` (review CLEAR, fixes merged), `feat/w0-parent-conformance` (review CLEAR, fixes merged), `feat/w1-taxonomy` (review BLOCKED on a stale README line, fixed, merged); trunk tip `a0076955`; `verify.sh` NO-FAILURES (1 pending: the C1 families).
- S3: round 1 (the four adversarial rulings) presented to the operator; awaiting the answers.
- Open operator gates: A1 status wording; the W6/W7 reading; the four W3 rulings.
