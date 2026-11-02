# steel_crawl implementation plan

**Status:** approved for execution, 2026-11-02.
**Spec:** `docs/design/steel-crawl-spec.md`.
**Design history:** `docs/design/steel-crawl-workbench.md`.
**Prototype:** `docs/experiments/steel_crawl_proto_v2.py`.
**Measurement:** `docs/experiments/steel-crawl-proto-v2-measurement.md`.

## 1. Decisions taken

- Scope is the full spec: every module in the spec's module tree, the HTTP-history ingest client and edge route, and the manifest v2 parser.
- The implementation branch is based on `fix/395-tool-contract-hardening`.
- The TypeSafe SystemOne client commit `214b53f0` is merged into the implementation branch.
- Tickets are GitHub `workflow` issues on `Diekgbbtt/polyphemus`, with native blocking links.
- The ten TDD seams below are approved.
- Verification is the unit and contract tiers.
- The live end-to-end run is a separate batch after this work, not part of this stretch.
- The authz residual risk is accepted. The `choose_removed` prompt keeps the specified categories and gains no new authz examples.
- Registration is a safe write. The prompt states it explicitly.
- The coarse effect signal is accepted. Its risk is recorded in spec section 5.4 and section 16.
- There is no per-ticket adversarial review. One adversarial review runs over the whole branch after all tickets.
- No pull request is opened in this stretch. The run stops and reports.

## 2. Worktree and branch

- Branch: `feat/steel-crawl`.
- Worktree: `/Users/diekgbbtt/.local/share/opencode/worktree/7b3bba/steel-crawl`.
- Base: `fix/395-tool-contract-hardening`.
- Merge: `fix/typesafe-systemone` at `214b53f0`.
- Docs commit: the steel design docs, the experiment scripts, the measurement docs, and the final run summaries.
- Raw CDP evidence is not committed. It stays in the experiment worktree.

## 3. Test seams

Tests are written only at these seams.

1. `SteelSession` CLI envelope through a fake `exec_fn`.
2. `AuthOracle` through a fake page fetch.
3. `BrowserState` cache and consumed set through fixture snapshots.
4. `Enumerator` projection through fixture DOM.
5. `Policy` through a fake decision client.
6. `CommandMapper` through table-driven cases.
7. `Frontier` through a fake page executor.
8. `CaptureSidecar` through a fake CDP transport.
9. `Manifest` writer and v2 parser through golden files.
10. `CrawlJob` end to end through a fake session, CDP, and policy.

No test mocks a private method or asserts an internal call sequence.
Expected values come from the spec, a worked example, or a golden file, never from recomputing the implementation.

## 4. Ticket DAG

The table is the dependency order.
A ticket starts only when every blocker is done and its targeted tests are green.

| ID | Title | Blocked by | Delivers |
| - | - | - | - |
| SC-00 | Test fixtures and fake seams | None | The fixture pack and fake seams that every later ticket tests at. No production behaviour. |
| SC-01 | Steel session attach, catalogue, and stop | SC-00 | A typed session record, catalogue attach, CLI envelope, stop, and the full session error mapping. |
| SC-02 | Auth oracle | SC-01 | A page-fetch oracle that passes only a 2xx non-redirect, with a loud missing-probe fallback. |
| SC-03 | Browser state, page instance, and stale refs | SC-01 | The page node, snapshot cache, consumed set, document generation, and stale-ref rejection. |
| SC-04 | Command mapper and action execution | SC-01, SC-03 | Action to CLI command to result, the variadic boundary, select read-back, single-key press, and form submit. |
| SC-05 | Candidate enumeration and element map | SC-03, SC-04 | The closed element types, exclusions, offer/collect/ignore channels, impact classes, and control facts. |
| SC-06 | Policy port and prompt contract | SC-05 | The policy protocol and the three question contracts, with a fake policy that drives the loop. |
| SC-07 | Jev adapter and removal loop | SC-06 | The TypeSafe adapter, sequential `choose_removed`, in-place collection, and stale-removal protocol error. |
| SC-08 | Jev choice and value selection | SC-05, SC-07 | `choose_chosen` over the impact order and `choose_value` over the catalogue, with the single-match shortcut. |
| SC-09 | Unified DFS frontier | SC-03, SC-04, SC-05, SC-08 | One depth-first traversal with navigation, local restore, backtracking, and stop reasons. |
| SC-10 | Form contract and parameter records | SC-04, SC-05, SC-08 | The form contract, declared and observed parameter records, value shapes, and provenance separation. |
| SC-11 | Capture sidecar and HTTP flows | SC-01, SC-04 | Raw CDP attach, request and response lifecycle, bodies, caps, correlation, and fail-closed capture. |
| SC-12 | WebSocket, HTTP/3, scripts, and dialogs | SC-11 | WebSocket handshake and frames, HTTP/3 flows, script assets, frame navigation, and dialog auto-dismiss. |
| SC-13 | Flow normalization and HTTP-history client | SC-12 | `http-artifact/v1` normalization, deterministic content IDs, body hashes, batch ingest, and retry cursor. |
| SC-14 | Manifest v2 writer | SC-09, SC-10, SC-13 | The v2 manifest, its graph-bearing records, stats, partial flag, and v1 compatibility. |
| SC-15 | Run ledger and finalize | SC-14 | An append-only ledger and a finalize path on success and on every failure. |
| SC-16 | HTTP-history ingest edge | SC-13 | The authenticated `POST /v1/ingest` edge, its batch limits, idempotent store, and response counts. |
| SC-17 | Manifest v2 parser | SC-14 | A v2 parser into graph deltas, with observed and declared provenance and v1 compatibility. |
| SC-18 | CrawlJob lifecycle and observability | SC-02, SC-09, SC-15 | The run lifecycle, deadline, stop reason, page and action records, and finalize on every exit. |
| SC-19 | Run loop integration | SC-16, SC-17, SC-18 | One run that traverses, acts, captures, submits a form, emits a manifest, and flushes the edge. |
| SC-20 | Session loss and resurrection boundary | SC-19 | A typed `session_missing` failure, one bounded retry, no start, and a clean finalize. |
| SC-21 | Contract acceptance suite and documentation pass | SC-20 | The deterministic P1 to P5 contract suite and the documentation sweep. |

The critical path is SC-00 to SC-01 to SC-03 to SC-04 to SC-05 to SC-06 to SC-07 to SC-08 to SC-09 to SC-14 to SC-15 to SC-18 to SC-19 to SC-20 to SC-21.

## 5. Execution protocol

Each ticket runs in one fresh implementation subagent.

1. The controller provides the full ticket text, the relevant spec sections, the approved seams, the worktree, the TDD skill path, and the verification command.
2. The implementer writes one failing test at an approved seam.
3. The implementer writes the minimal code that passes it.
4. The implementer repeats, one slice at a time.
5. The implementer runs the targeted suite and the package suite.
6. The implementer commits with a conventional message.
7. The controller reads the diff, runs the targeted suite, checks every acceptance criterion, and records the commit.
8. A red result returns to the same implementer session with the failing output.
9. A ticket is done only when its acceptance criteria and its targeted suite are green.

There is no parallel implementation.
There is no per-ticket adversarial review.
The implementer may not mark its own ticket done; the controller does.

## 6. Verification

Per ticket:

```text
.venv/bin/python -m pytest tests/recon/crawl/steel -q
```

At the end of the batch:

```text
.venv/bin/python -m pytest tests/ -q --ignore=tests/e2e --ignore=tests/integration
.venv/bin/python -m compileall -q src/polymerhus/recon/crawl/steel
```

The full unit tier is the regression gate.
The live tiers are not run in this stretch.

## 7. Final adversarial review

One review runs over the whole branch after SC-21.
It covers two axes: the repo coding standard and the spec.
The review reads the diff from the branch base, not only the last commit.
Every blocking finding is fixed and re-tested.
The review is not repeated from scratch.
The final report lists the executed tickets, the verification evidence, the review findings, and the deferrals.

## 8. Deferrals and risks

- The live P1 to P5 end-to-end run is deferred to the next batch.
- The raw CDP evidence and the White Jotter environment are not part of this branch.
- The authz residual risk is accepted by design.
- The coarse effect signal is accepted, with the risk recorded in spec section 5.4.
- The HTTP-history edge is implemented and tested locally; its deployment wiring is part of the edge ticket, not this plan's live gate.
- A ticket that cannot meet its acceptance criteria is escalated with the failing output, not weakened.

## 9. Ticket publication

Each ticket is one GitHub issue under the `workflow` label.
The issue body uses the `to-tickets` template: what to build, acceptance criteria, and blocked-by.
Issues are created in dependency order.
Native blocked-by links are added after creation.
The issue number is recorded in this plan's execution log below.

## 10. Execution log

SC-10 was completed by the controller after the implementation subagent provider refused connections three times. The partial worktree from the first dispatch was reviewed, completed with TDD, and committed.


Unrelated test repair: `887c19bf` supplies the required `SpecWrite` fields in the artifact schema test, so the whole `tests/recon` tier is green (1439 passed, 20 skipped).

| ID | Issue | Commit | Tests | Status |
| - | - | - | - | - |
| SC-00 | #416 | 73a5fde6 | 48 passed | done |
| SC-01 | #417 | 7cd600f3 | 72 passed | done |
| SC-02 | #418 | 748d3173 | 114 passed | done |
| SC-03 | #419 | f146af42 + f4ca9dad | 123 passed | done |
| SC-04 | #420 | 932ca98a | 197 passed | done |
| SC-05 | #421 | a0f4c5d8 | 220 passed | done |
| SC-06 | #422 | bab69a51 | 249 passed | done |
| SC-07 | #423 | 8bab21a6 | 273 passed | done |
| SC-08 | #424 | b3526af5 + 97e49c9c | 324 passed | done |
| SC-09 | #425 | b3b93dca | 346 passed | done |
| SC-10 | #426 | 43776069 | 358 passed | done |
| SC-11 | #427 | | | pending |
| SC-12 | #428 | | | pending |
| SC-13 | #429 | | | pending |
| SC-14 | #430 | | | pending |
| SC-15 | #431 | | | pending |
| SC-16 | #432 | | | pending |
| SC-17 | #433 | | | pending |
| SC-18 | #434 | | | pending |
| SC-19 | #435 | | | pending |
| SC-20 | #436 | | | pending |
| SC-21 | #437 | | | pending |
