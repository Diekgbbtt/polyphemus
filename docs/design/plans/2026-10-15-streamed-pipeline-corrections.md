# Plan: streamed-pipeline corrections after arm H

Status: active (2026-10-15).
Branch: `fix/streamed-pipeline-corrections`, cut from `dev` at `6ec2e55`.
Origin: operator-directed, four corrections, executed sequentially in this order.
Evidence base: the arm H section of `docs/experiments/analysisUnitFirst-vs-l0batchFirst-pipeline-comfyui-results.md`, the staged measurements (`/root/arm-h-measure.out`), the kali container access log, and the Langfuse trace extracts (`lf-h-assigner-final.txt`, `lf-typist-p12-batches.txt`, `lf-typist-early-batches.txt`).

## Constraints

- Arm H stays pinned. No eval trial runs in this iteration; these corrections are the next iteration's input.
- Land on `dev`, push `origin/dev`, then the eval server pulls (the standing CD path).
- Each ticket lands with green unit tests before the next ticket begins.
- `ROLE_ADMITS` is unchanged: the queue-time drops live at the stream level in `chunks_for_job`, exactly like the existing noise-Endpoint gate. The typist's `ADMIT_ALL` sentinel keeps the fork-H guarantee for new recon tools.

## Verified evidence the plan builds on

### The queue-time premise (T1), falsified and corrected

The operator's reading - "for all proposers the chunk is queued but no asset survives the post-queue filter, so no agent turn is yielded" - is FALSE as written.
`ROLE_ADMITS` gives `mechanism_typist` the `ADMIT_ALL` sentinel, and the arm H trace confirms the typist typed from those chunks: P1 (Domain, 1 asset) wrote 4 systems (`RESTApi core-rest` plus three singletons), P2 (IP + 6 Port + 6 Service, 13 assets) wrote `RESTApi polymerhus-agent`, `IntegrationSystem postgresql` plus a singleton - off-target infrastructure inferred from port numbers.
Only the ASSIGNER yields no turn on those chunks (it admits `Endpoint` alone and short-circuits on an empty slice).
The operator's DECISION stands regardless: those four asset types are connectivity scaffolding, typing mechanisms from them is at best noise, and they must not enter any chunk.

### The MCP session seam (T2), the kill cascade

In the arm H analysis window (12:30-14:35Z) the kali access log shows 268 sessions opened, 267 clean `DELETE /mcp` 200s, and exactly one `POST /mcp` 404.
The trace shows `ClosedResourceError` in 14 of 14 assigner turns and 39 error-level tool results.
The log shows the mechanism: bursts of three `GET /mcp` (three session opens in the same instant) followed by three `DELETE /mcp` in the same instant.
Three defects compound in `app/clients/kali_http_history.py`:

1. `_session()` opens the session OUTSIDE `_SESSION_LOCK`. Parallel tool calls (langgraph `ToolNode` runs one turn's multiple tool calls on worker threads) each pass the cache check, each open their own session, and each install path closes the PREVIOUS session - which is the sibling's live session. The sibling's next call raises `ClosedResourceError`.
2. `_heal_unit_session()` tears down whatever session currently sits under the unit key. A second healer (or a healer racing a fresh install) therefore kills a LIVE fresh session, which triggers another heal: a kill cascade.
3. `close_unit_session()` exists but is never called (the ADR `docs/design/http-history-mcp-session-per-unit-adr.md` section 4 prescribed the `proposer_batch` boundary hook; it never landed). Sessions therefore close only on key change or heal.

The user-facing effect: the proposer calls systematically use sessions that a sibling or a stale heal has killed.
The close path itself is reliable: every one of the 267 DELETEs was acknowledged 200, the close is bounded (`_MCP_CLOSE_TIMEOUT_S` 15s) and best-effort.

### The typist feed quality (T3), the katana combat

The arm H katana pass pushed 12 chunks; 10 of them carried no assigner-admissible Endpoint at all (40 `*.js` Endpoints were noise-gated, but roughly 1.2k metadata deltas - `Header`, `Technology`, per-transaction `BaseURL` baskets - streamed through).
Each of those chunks still bought a typist turn, the whole pass wrote 1 aggregate, and the typist rows are near-duplicates: `Header` identity is `(name, baseurl)`, emitted once per transaction, and the stream carries no identity dedup.
The chunk builder batches in delta order with a fixed 100-asset cut, so a chunk can straddle unrelated surfaces and can split one endpoint family across chunks.

### The differentiation question (T4), the ambiguous payload

`/experiment/models` (live probe, 15 Oct 2026) returns the folder-path map (`[{"name": "checkpoints", "folders": [...]}, ...]`), not a file inventory.
`model-inventory`'s contract names "model files ... in the model folders"; `server-diagnostics`' contract names "the folder-path map".
Arm H kept the endpoint on `model-inventory` and ran its noun differential only against noun-adjacent contracts (`model-download` and friends), never against the rival whose contract names the payload class.
The same payload's other route identity (`/folder_paths`) went to `server-diagnostics`, so ownership of one payload split by PATH, not by PAYLOAD.

## T1 - Queue-time drop of the connective asset types

Goal: `Domain`, `IP`, `Port`, `Service` L0 assets never enter a chunk, for any proposer.

Behavior: extend the stream filter in `chunks_for_job` (the existing noise-Endpoint gate) with these four types.
A delta composed only of them yields zero chunks; the pass then schedules zero dispatches and reports the pushed-asset count honestly.
The assets stay in L0 (recon production untouched), exactly like noise Endpoints.

Acceptance:

- Unit tests: each of the four types is excluded; a mixed delta keeps every other type; a delta of only connective types yields `[]`; malformed-asset and noise-Endpoint behavior unchanged.
- A supervisor test: a pass whose delta is only connective assets schedules zero dispatches.
- A comment records the corrected premise: the assigner skipped these chunks, the typist did not; the drop is the operator's decision on stream hygiene, not a fix for an empty dispatch.

Files: `src/polymerhus/analysis/chunking.py`, `src/polymerhus/analysis/CONTEXT.md`, `tests/analysis/test_streaming.py`, `tests/integration/test_chunking_contracts.py`.
blocked_by: none.

## T2 - MCP session lifecycle: per-unit close, race-free installs

Goal: one kali HTTP-history MCP session per analysis unit; concurrent tool calls inside the unit share it; the unit boundary closes it; the next chunk opens fresh.

Behavior:

1. `_session()` install-or-yield: open outside the lock; under the lock, if a same-key session was installed meanwhile, keep that one, close OUR surplus only, and never touch the winner; otherwise install ours.
2. `_heal_unit_session(project_id, dead)`: identity-checked teardown. Only the session the failing call actually used is torn down; if the cache already holds a different session, the heal is a no-op. This removes the cascade.
3. `proposer_batch()` calls `close_unit_session()` in its `finally` (fail-open import), so the session closes when the unit's turns finish - the same boundary where the agent session resets (reset, not torn down). The first call of the next chunk opens fresh.
4. The FM-D heal, the bounded waits, and fail-open stay unchanged.

Assessment the operator asked for: closing at the unit boundary is reliable. The kali server acknowledged every DELETE (267/267) and the close is bounded and best-effort. The failures in arm H come from conflicting installs and stale heals, not from closing.

Acceptance:

- Concurrency test: N parallel first-calls for one unit construct exactly ONE `_UnitSession`; no caller's session is closed by a sibling.
- Heal test: a stale death does not tear down a fresh, live session installed under the same key.
- Boundary test: leaving `proposer_batch` closes the unit session.
- Existing client and FM-D tests stay green.

Files: `src/polymerhus/app/clients/kali_http_history.py`, `src/polymerhus/analysis/proposer_turn.py`, `tests/attack/test_kali_http_history_client.py`, `tests/analysis/test_proposer_turn.py`.
blocked_by: none.

## T3 - Typist feed quality: diagnosis first, then topology-cohesive chunks

Goal: the typist consumes cohesive asset families, not a metadata flood.

Step 0 - diagnosis, required before any fix (procedure `/diagnosing-bugs`): assemble the katana pass evidence (per-type delta counts, per-chunk composition, per-chunk typist output, the duplicate rows) and confirm the root cause.
Deliverable: `docs/experiments/typist-feed-quality-diagnosis.md`, committed before the fix.

Step 1 - fix in `chunking.py`, shaped by the diagnosis:

- Identity dedup: the stream drops repeated `(type, identity)` occurrences (first occurrence wins, order-stable). The delta stream repeats headers and technologies once per transaction.
- Families over topology: group the stream into families anchored on the graph topology the deltas carry (a `BaseURL` anchor with its Endpoints, its Headers, its Technologies; an Endpoint with its Parameters and Secrets, via `identity` keys `baseurl`/`endpoint_path` and the deltas' `edges`).
- Endpoint sub-buckets: classify Endpoints into client-side code, UI visuals, and HTML (from the recorded props: content type and path), so a chunk is homogeneous.
- Header aftercare: a header row names the owning Endpoint(s) it was seen on, and duplicates across endpoints collapse to one row (chunk builder dedup plus the typist renderer's row shape).
- Sizing: `CHUNK_MAX_ASSETS` becomes a SOFT target (`CHUNK_TARGET_ASSETS`); families are atomic; the builder closes a chunk once the count exceeds the target AND the current family is complete; the tail is never dropped.

Acceptance:

- The diagnosis doc is committed first and names the confirmed root cause with arm H evidence.
- Tests: identity dedup; family atomicity (a family never splits across chunks); sub-bucket separation; header collapse; soft-target behavior (chunk closes after the family that crosses the target); tail preserved; determinism.
- A katana-shaped fixture proves one chunk carries one coherent family.

Files: `src/polymerhus/analysis/chunking.py`, `src/polymerhus/analysis/mechanism_typist.py`, `tests/analysis/test_streaming.py`, `tests/analysis/test_mechanism_typist.py`, `tests/integration/test_chunking_contracts.py`; the diagnosis doc.
blocked_by: T1 (same file; the gate lands first).

## T4 - Differentiation assessment (report only)

Goal: verify the claim that `/experiment/models` could have been correctly assigned to `model-inventory`; if correct, name the reasoning quirk and report a throughput relaxation with its wrong-allocation risk.

Deliverable: `docs/experiments/assigner-differentiation-assessment.md` with:

- the live payload, both contracts quoted, and a verdict on the claim;
- the reasoning quirk that let the run reach the right owner by the wrong path (noun-driven candidate generation; the payload-class rival never entered the differential);
- a relaxation proposal: how to widen or skip the differential (payload-class candidate generation, single-candidate direct admits, one ownership question per payload across its route identities), the throughput gain it buys, and the wrong-allocation risk with the guards that bound it (arm H's 193 of 298 declined endpoints as the precision baseline).

No code change in this iteration. Acceptance: the doc quotes the payload, the contracts, and the arm H keep/drop rows, and lands one recommendation with a guard set.
Files: the doc.
blocked_by: T1-T3 (it reads the same run evidence; last in order).

## Non-goals

- No eval trial in this iteration.
- No change to `ROLE_ADMITS` and no per-role chunk filtering.
- No hunting-side session change. Note: the typist's `exec` binding runs through `recon.domain.pod.default_exec_fn`, which builds a client and opens a session PER CALL; that churn is a known, separate seam. If the next trial shows churn from it, it becomes its own ticket.

## Trial-side assertions for the next run (not executed here)

1. Proposer traces show zero `ClosedResourceError` and zero `http_history_failed` from install races.
2. Kali session opens are on the order of units plus exec calls, not multiples per unit.
3. Every katana-pass chunk either carries at least one assigner-admissible Endpoint or is not queued.
4. The typist feed shows collapsed header rows with their owning endpoints named.
