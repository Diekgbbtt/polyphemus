# Loop Constraints — polymerhus L1-MVP

> Binding. The loop reads this file at the start of every iteration and must follow it verbatim.
> Source of scope truth: `docs/design/service-system-model-L1-implementation-bridge.md` (the bridge) and `docs/design/L1-MVP-plan.md`.

## Scope (post-MVP - the MVP fence is DOWN as of 2026-07-19, operator decision)

- The L1-MVP is built + verifier-APPROVED; the system has been exhaustively e2e-tested and blocking/important defects emerged that must be fixed. The operator has officially TAKEN THE MVP FENCE DOWN. We are in post-MVP defect-remediation.
- Previously-deferred identity machinery is now IN SCOPE where a confirmed defect requires it: notably `NM-1` (superseding/reified assignment provenance) and `NM-4` (service-splitting / node merge), and **destructive reconciliation** in the L1 sole-writer (merge / delete / relabel duplicate or off-role nodes). The operator chose FULL DESTRUCTIVE MERGE for post-recon curation.
- Still out of scope unless a confirmed defect forces it (surface with options, do not silently build): the Stage-3 projection algorithm, the signature-evaluation engine (`NM-8`), risk scoring, and phase-2 abduction. These remain forward-compat constraints, not build targets.
- The `FR-INGEST` `/ingest` content pipeline stays out of scope (bridge §5); the operator KB enters via a `settings.recon.operator_kb` field, not the ingest pipeline.
- Every new capability still goes through the loop discipline below (assertions first, maker/checker, minimal-fix) and the sole-writer discipline (all `:L1*` writes, including the new destructive ops, go ONLY through `l1_curator`, carrying provenance).

## Sole-writer & denylist paths (escalate, never edit)

- L0 graph writes go ONLY through `agent/recon/curator.py`; L1 graph writes go ONLY through the new `agent/recon/analysis/l1_curator.py`. Never emit `:L1*` MERGE Cypher from anywhere else.
- Never edit `.env`, `.env.*`, secrets, credentials, or infrastructure configs without human approval.
- Never edit the L0 sole-writer guarantees — `agent/recon/curator.py` and `db/neo4j/schema.py` — except through a sanctioned L1 seam (new `l1_schema.py` / `l1_curator.py`). If a change seems to require touching them, escalate.

## Invariants that must hold on every write (FR-NFR)

- Idempotent `MERGE` on L1 identity (`L1D-22`): running twice yields one node.
- `identity ⊥ membership` (`L1D-11`): never key an L1 unit on its member set.
- `discriminator` defaults to the literal non-null string `"__singleton__"` (`L1D-9`/`L1R-2`), never null.
- Provenance on every node/edge/ref write (`L1D-25`).
- Fail-open / graceful degrade: a steering / skill / LLM / targeted-job error degrades to an empty-or-error result; it never crashes the caller.
- Traversal-then-fetch / token discipline (`DD-4`): BFS reads index-cards, never the raw member set; concretisation enters only through typed projections.
- Destructive reconciliation (merge / delete / relabel) is now permitted in `l1_curator` ONLY; it must be idempotent, provenance-stamped, and re-point (never orphan) the edges of any node it removes or relabels.

## Code & loop discipline

- Report/plan first (Phase 0, done), then implement per FR area. Never attempt the whole system in one pass.
- One FR area = one bounded goal in its own git worktree. Discard the worktree on REJECT/escalation.
- Maker/checker: the implementer sub-agent writes; a SEPARATE `loop-verifier` sub-agent runs the assertions and approves. The implementer may NEVER mark its own work done.
- Debug with `loop-engineering/skills/minimal-fix`: reproduce → minimal root cause → smallest diff → rerun. One problem per fix. No drive-by refactors.
- Always run the tests before proposing a fix. Never disable, skip, or weaken a test/assertion to go green ("no cheating").
- No flake-masking: quarantine a flaky test and escalate the infra cause; never paper over it with retries.
- Max 3 fix attempts per FR area; escalate after with full context in `STATE.md` `High Priority`.
- Do not start a second FR area until the first is verifier-APPROVED.

## Communication & irreversible actions

- Tell the human what you are about to do before doing something outward-facing or hard to reverse.
- Commit/push only when the user asks; branch first if on the default branch. Never auto-merge to `main`.
- Escalation must actually reach a human: land it in `STATE.md` `High Priority` (`Waiting on human`) and notify.

## Budget & kill switch

- Read `loop-budget.md` at start/end of each iteration; if token spend hits 80% of the daily cap, switch to report-only.
- Kill switch: if `loop-pause-all` is active (flag in `STATE.md` `High Priority`), exit immediately. Resume only after a human clears it.

---
<!-- Add project-specific rules below in plain English. The loop reads this verbatim. -->
