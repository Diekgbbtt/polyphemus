# Steel pool MCP workstream plan

Date: 2026-11-05.
Status: active plan.
The plan is strict.
No phase starts before its predecessor gate passes.

## Phase 0 - Questions and ADRs

- Ask the frontier questions.
- Record each answer as a decision.
- Do not write the spec or code before the answers.

Gate: no open question remains.

## Phase 1 - System design spec

- Write the system design spec with the repository spec conventions.
- Cover components, protocols, data structures, state machines, failure
  modes, configuration, security, and rollout.
- Check every decision against the spec.

Gate: the spec is consistent with the decisions.
No unresolved alternatives remain.

## Phase 2 - Work items

- Break the spec into distinct work items.
- Map dependencies.
- Give each item acceptance tests, a rollback, and an owner-facing output.

Gate: every work item has a testable acceptance condition.

## Phase 3 - TDD implementation

- One work item at a time.
- Red test, green implementation, refactor.
- Run targeted tests after each item.
- Review the diff against the item.
- Do not touch `steel_crawl` before the last item.

Gate: the item tests pass.
The next item starts only after the gate.

## Phase 4 - steel_crawl rebase and integration

This is the last implementation work item.

- Create an integration worktree and branch based on `feat/steel-crawl`.
- Replay this branch's docs and prototype commits.
- Treat `feat/steel-crawl` as authoritative for the recon module.
- Resolve conflicts carefully.
- Adapt only the browser-pool wiring at the module seams.

Gate: the rebase is clean.
The recon engine tests pass unchanged.
The wiring tests pass.

## Phase 5 - E2E

- Low mocking.
- Production-like topology on the eval server.
- Adjust the existing tool and `steel_crawl` tests to the new architecture.
- Run the pool E2E and the `steel_crawl` E2E.
- Record evidence and failures.

Gate: the agreed E2E suite passes.
Every skip is explained.

## Phase 6 - Review and merge

- Code review.
- Spec review.
- Final verification.

Gate: review passes.
No open failure remains.

## Feedback loops

- Each item ends with targeted tests and a diff review.
- A failing gate stops the next item.
- The rebase and E2E are last.
- The plan changes only by an explicit decision.
