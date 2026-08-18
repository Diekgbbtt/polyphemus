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

- L0 graph writes go ONLY through `src/polymerhus/recon/domain/curator.py`; L1 graph writes go ONLY through the new `src/polymerhus/analysis/l1_curator.py`. Never emit `:L1*` MERGE Cypher from anywhere else.
- Never edit `.env`, `.env.*`, secrets, credentials, or infrastructure configs without human approval.
- Never edit the L0 sole-writer guarantees — `src/polymerhus/recon/domain/curator.py` and `db/neo4j/schema.py` — except through a sanctioned L1 seam (new `l1_schema.py` / `l1_curator.py`). If a change seems to require touching them, escalate.

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

## Testing tiers (full reference: `docs/design/testing-strategy.md`)

- The UNIT tier (`tests/`, `tests/recon/**`) must NOT touch a real database. This is enforced: `tests/conftest.py` raises on any live Neo4j access from an unmarked test, including via the raw `_driver`. Inject a fake `read_fn`/`merge_fn` - every module supports it.
- A test that genuinely needs a live database goes in `tests/integration/` or `tests/e2e/` (auto-marked by path), never in the unit tree behind a `skipif` gate. That is how a test ends up never running and nobody noticing - it happened, to a test that had executed zero times.
- Live tests take their connection from `tests/conftest.py::neo4j_target()`. Never write a connection literal into a test file.
- Run unit: `.venv/bin/python -m pytest tests/ -q`. Run live tiers IN-NETWORK: `docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm tests tests/integration -q`.
- Do not run the host suite and an in-network run at the same time: `tests/e2e/test_stack_smoke.py` rebuilds the stack, and the restart makes the concurrent run's infra-gated tests skip - looks like a regression, is not.
- A SKIP is a silent failure with good manners. When a gated test skips, verify the gate is telling the truth before believing it - a broken gate hid a whole tier and a permanently-dead test.
- When a test asserts over a FILTERED collection, make sure the filter cannot go vacuously empty. A filter that silently stops matching reports the absence of its own coverage as a product failure (this is what made the arjun pipeline e2e "fail" for months).
- Max 3 fix attempts per FR area; escalate after with full context in `STATE.md` `High Priority`.
- Do not start a second FR area until the first is verifier-APPROVED.

## Communication & irreversible actions

- Tell the human what you are about to do before doing something outward-facing or hard to reverse.
- Integration follows the discipline in `docs/agents/issue-tracker.md`: branch first if on the default branch, one PR per `workflow` ticket against `main`, a verifier APPROVAL authorises pushing the branch and opening the PR, and merging to `main` is a human action.
- Escalation must actually reach a human: land it in `STATE.md` `High Priority` (`Waiting on human`) and notify.

## Budget & kill switch

- Read `loop-budget.md` at start/end of each iteration; if token spend hits 80% of the daily cap, switch to report-only.
- Kill switch: if `loop-pause-all` is active (flag in `STATE.md` `High Priority`), exit immediately. Resume only after a human clears it.

---
<!-- Add project-specific rules below in plain English. The loop reads this verbatim. -->
