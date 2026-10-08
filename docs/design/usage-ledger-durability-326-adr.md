# ADR: the usage ledger is durable per project

## Status
Accepted (2026-10-08).
Resolves #326.

## Context
- The app token-usage ledger (`src/polymerhus/app/llm/usage.py`) was process-wide and in-memory only.
  It died with the app process, so a project's cumulative spend and its per-agent breakdown were lost on any restart, interrupt, or drain.
- Observed live: project `d76f1bcc-eb36-42c9-9f71-cb478d0fc33a` produced real spend across 26 terminal PodExports, but its hunting run `65151438` ended `interrupted` and `GET /projects/d76f1bcc.../usage` returned `generated_tokens: {reasoning: 0, visible: 0}, calls: 0`.
  An `interrupted` hunting run is written at startup by `reconcile_orphaned_hunting_runs` (the in-memory actor died with the process) or by the hunting runtime on a provider failure, so the durable record cannot wait for a graceful stop: the process may already be gone.
- This matters to the eval: `eval/orchestrator/trial.py::_check_spend` reads `GET /projects/{id}/usage` to enforce the token budget.
  A lost ledger drops the cumulative total below the trial's carried `spend_baseline`, so `spent = max(0, total - baseline)` reads zero and the budget silently resets after any restart.
- The old spec explicitly recorded persistence as out of scope (`docs/design/eval-token-tracking-spec.md`, "Persisting the ledger").
  This ADR reverses that decision.

## Decision

### The durable store is a per-project file under the app data root
The ledger persists each project's cumulative per-agent entries to `<data_root>/<project_id>/usage/usage.yaml` through a `UsageStore`, resolved by the one layout owner `app.data_root.project_dir` and written with the shared `app.atomic_write` primitive.
`"usage"` joins `PROJECT_SCAFFOLD`.

Rejected alternatives:
- **A per-project JSONB row in the app PostgreSQL.** The usage endpoint is deliberately database-free (`GET /projects/{id}/usage` never reads Postgres and never validates project existence), and the app PG schema is owned by the recon/hunting run lifecycle, not app-layer telemetry.
  Adding a row would couple an app concern to that schema and force the endpoint onto the database for no gain.
- **The LiteLLM gateway database as the store.** The gateway's `/spend/logs`, `/global/spend/keys`, and `/global/spend/models` attribute by litellm key/model, not by polymerhus project/agent, and carry no reasoning/visible split.
  It is a cross-check, never the store.
- **The data root is durable.** In the container it is a bind mount (`${INSTANCE_DATA_ROOT:-./data}:/srv/data`, `docker-compose.dev.yml`), the same root the auth, skill, and hunting-memory stores already survive restarts in.

### The ledger is write-through on record, read-through on first use
- `UsageLedger` gains an injectable `UsageStore`.
  A ledger with no store is pure in-memory (the existing behaviour, and what unit tests that need no durability use).
  The production singleton is wired to the file store at app startup (`main._startup`).
- **Write-through.** Every `record` persists the touched project's whole cumulative entry set atomically.
  This is the decision that fixes the observed loss: a process death between stop/drain boundaries still leaves the spend on disk within one model call.
  Model calls are seconds apart and the atomic YAML replace is tiny, so the hot-path cost is negligible; `record` stays fail-open - a persist error is logged and swallowed, never raised into the agent turn.
- **Read-through.** The first `record` or `snapshot` for a project in a process seeds the in-memory entries from the durable file, so the accumulator is `durable floor + live calls`.
  A persist always writes that combined set, so a resumed project never double-counts: the durable file is REPLACED with the cumulative total, never appended to.
- **Boundary flush.** `flush(project_id)` and `flush_all()` persist on demand; they are idempotent and load the project before writing, so a flush for a project this process never recorded re-persists its durable floor rather than erasing it.
  `drain_module` and app shutdown call `flush_all`; the recon/analysis/hunting stop endpoints call `flush(project_id)`.
  With write-through these are a safety net, not the load-bearing path.

### Resume semantics are unchanged
The eval's spend baseline already snapshots the first read and is carried across a resume (`TrialConfig.spend_baseline`).
Because the durable record preserves the cumulative total, a resumed or reused project keeps counting from its true spend rather than resetting to zero.

### Fail-open
Reads and persists are fail-open: a missing, unreadable, or non-mapping record degrades to empty (warned), and a persist failure never breaks an agent turn.
The endpoint therefore keeps its contract of never erroring and never validating project existence: an unknown project, an invalid id, or an unreadable file all degrade to zeros.

## Acceptance criteria
- (a) After a restart, `GET /projects/{id}/usage` returns the accumulated two-axis surface and the `by_agent` breakdown - covered by the restart read-through test and the endpoint read-through test.
- (b) A project that spent tokens never reports `calls: 0` after stop/drain - covered by the record-without-flush test and the boundary-flush tests.
- (c) A resumed recording does not double-count the durable floor - covered by the resume test.
- (d) The store round-trips and fails open on a missing/corrupt file - covered by the store tests.

## Consequences
- A project's spend survives process death, so the eval token budget can no longer reset after a restart.
- The endpoint stays database-free; durability rides the existing data-root bind mount.
- The store is always reached under the ledger's single process-wide lock, so no second lock layer is introduced.
- Known risk (verifier-flagged, not measured): the write-through path holds the global ledger lock across a full YAML dump plus file and parent-dir `fsync` on every model call, so concurrent agents' recording serialises behind disk I/O. The cost is asserted negligible but not benchmarked; a hot-path benchmark under the eval's concurrency is a follow-up if recording latency proves material.
- The superseded `docs/design/eval-token-tracking-spec.md` "Out of Scope: Persisting the ledger" bullet is corrected in the same change.

## References
- #326 (this bug), #321/#331 (the token budget and provider-failure interrupt).
- `docs/design/eval-token-tracking-spec.md`; `docs/design/eval-token-budget-and-no-config-cap-adr.md`; `docs/design/atomic-write-340-adr.md`.
- `src/polymerhus/app/llm/usage.py`; `src/polymerhus/app/CONTEXT.md`; `tests/test_llm_usage_durability.py`; `tests/project_management/test_usage_endpoint.py`.
