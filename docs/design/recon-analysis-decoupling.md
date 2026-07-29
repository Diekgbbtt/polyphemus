# Recon / analysis runtime decoupling - design specification and grilling set

*Status: PROPOSED, not ratified. Nothing here is built. Written 2026-07-28 against `feat/assigner-classification-only`, on the evidence of live run `64f2ccb8-f526-495b-a0ae-d2d3db59f0c5` (project `00ea6ea4-8dfc-4d1b-a34d-141b0783d762`, Juice Shop).*

*Scope: the runtime relationship between the Recon pipeline (`recon/control/pipeline.py`) and the Analysis control plane (`analysis/supervisor.py`).*
*Non-scope: the analyser's reasoning, the Assigner's judgment quality, the L1 model.*

---

## 1. Verdict on the proposal

The operator is right that the analyser must come off recon's critical path, and the measured cost of not doing so is severe: on run `64f2ccb8` the streaming analyser consumed roughly 25 of the run's 33 wall-clock minutes, including a single 19.3-minute dead gap between two recon jobs, and wrote 9 `AGGREGATES` edges over 136 Endpoints for that price.

The operator is wrong about the cause and therefore about the remedy: the stall is not caused by synchronous *communication*, it is caused by an unbounded-latency LLM call on the critical path plus a re-read of the whole cumulative surface once per recon job, and "do not dispatch new agents on each stream" targets a per-step cost measured here at well under a second out of a 19-minute step - the supervisor's *state* is already long-lived (65 checkpoints on one thread, step counter 0 to 63 monotonic across seven invocations), only the `StateGraph` object and two Postgres connections are rebuilt.

My recommendation is: bound the analyser call and stop re-judging settled surface FIRST, then decouple the trigger with a depth-1 coalescing queue of *cursors* (never payloads) drained by exactly one per-run consumer task that the pipeline joins before the run reaches `complete` - which removes the stall, preserves the L1D-23 convergence guarantee exactly, and costs one extra analyser pass of resident memory rather than the unbounded consumer the FR-STREAM ledger rejected.

---

## 2. The problem, evidenced

### 2.1 What the code does today

The pipeline calls the analyser synchronously inside the job loop, after each job that produced surface, double-gated and fail-open at two layers (`src/polymerhus/recon/control/pipeline.py:504-518`).
Jobs within a phase are deliberately sequential, not gathered, because a phase-wide fan-out once OOM-killed the agent container (`src/polymerhus/recon/control/pipeline.py:523-528`).
The call is offloaded with `asyncio.to_thread` so it does not block the API event loop, but it does block the job loop: nothing else in that run proceeds while it runs.

`stream_analyser_step` (`src/polymerhus/analysis/streaming.py:33-51`) delegates to `run_analyser` (`src/polymerhus/analysis/pod.py:507-549`), which - when `analysis.supervisor_enabled` is set - routes to `run_analyser_chunked` (`src/polymerhus/analysis/supervisor.py:377-456`).

Each invocation of `run_analyser_chunked` does all of the following, from scratch:

- reads the **cumulative** L0 surface (`src/polymerhus/analysis/supervisor.py:416`, via `src/polymerhus/analysis/l0_stream.py:73`);
- builds chunks of at most 100 assets (`src/polymerhus/analysis/supervisor.py:425`, `src/polymerhus/analysis/chunking.py:37,184`);
- builds a **fresh** `StateGraph` and a **fresh** schedule (`src/polymerhus/analysis/supervisor.py:437-438`);
- calls `asyncio.run(run_supervisor(...))` (`src/polymerhus/analysis/supervisor.py:439`), which opens a **new** `AsyncPostgresSaver` and `AsyncPostgresStore` per invocation (`src/polymerhus/analysis/supervisor.py:324-329`).

So cost grows as `jobs x ceil(surface / CHUNK_MAX_ASSETS)` LLM calls and compounds for the whole run.

### 2.2 What the run actually did

`recon_jobs` for run `64f2ccb8`, with `finished_at` written *before* the streaming step (`pipeline.py:495-518`), so every inter-job gap is streaming time:

| phase | job | finished_at | next job started_at | dead gap |
|---|---|---|---|---|
| 4 | steel_crawl | 08:41:18 | jsluice 09:01:08 | **19 min 50 s** |
| 5 | jsluice | 09:02:17 | httpx_reprofile 09:06:19 | **4 min 02 s** |

The Postgres checkpointer confirms where the time went; the thread `stream-64f2ccb8-...` holds 65 checkpoints, and the gap sits between two consecutive super-steps:

```
2026-07-28T08:41:49  step 44   (supervisor routed to the assigner)
2026-07-28T09:01:06  step 45   <- 19.3 minutes inside ONE proposer node
```

Summing the seven streaming invocations gives roughly 1530 s of analyser time against roughly 605 s of actual recon work, i.e. the analyser owned about 72% of the run's wall clock.

### 2.3 What it produced

The project's graph carries 17 `L1Service` and 3 `L1System` (both written by the Bootstrapper), 136 `Endpoint`, and exactly **9** `AGGREGATES` edges.
The final receipts channel on the supervisor thread holds two receipts - chunk 0 `status=empty`, chunk 1 `status=written, aggregates=9` - so six of the seven passes contributed nothing that survived, and the run was `cancelled` at phase 6 rather than completing.

### 2.4 Two defects the decoupling would otherwise inherit

**The analyser provider call has no time bound.**
`build_chat_model` constructs `ChatOpenAI` with no `timeout` and no `max_retries` override (`src/polymerhus/app/llm/providers.py:40-42`), and the Assigner wraps it in `_invoke_with_retry(attempts=3)` (`src/polymerhus/analysis/pod.py:373`, used at `src/polymerhus/analysis/assigner.py:417-425`).
With the client library's own retry budget on top, one chunk can legitimately occupy tens of minutes before failing open to an empty batch - which is the most plausible reading of the 19.3-minute step that produced nothing.
This is the single fact that makes "just make it async" insufficient: an unbounded producer of work behind an async boundary does not stall recon, it silently builds a backlog that outlives the run.

**Re-judging settled surface is nearly all of the work.**
Every pass re-chunks the entire cumulative surface, so the first 100 Endpoints were re-dispatched to the Assigner on every one of the seven passes.
That is the design's explicit choice (`L1-MVP-plan.md:704` calls incremental analysis "an efficiency optimisation") and it is what buys convergence - but at seven passes and roughly 4 minutes per LLM call it is the dominant cost, not a rounding error.

### 2.5 One fact that reframes "batch is the default"

`run_analyser` has no production caller anywhere except `streaming.py` (verified by repository-wide search; the other references are tests, docs, and the module itself).
So in the running system, streaming is not an opt-in *mode* of analysis - it is the *only* trigger of analysis.
"Turn streaming off" is therefore not an available mitigation; it means no L1 at all.

---

## 3. Critical analysis

### 3.1 The proposal reverses a ratified decision, and here is the sentence

`docs/design/L1-MVP-plan.md:704`, the FR-STREAM / NM-7 goal statement, lists among its non-goals:

> *"a concurrent long-lived analyser consumer task (memory-unsafe on the constrained host - the OOM failure mode)"*

The same rejection is restated at the seam it protects, `src/polymerhus/analysis/streaming.py:22-24`:

> *"No concurrent long-lived consumer task: the pipeline runs this synchronously between (sequential) jobs, so peak memory stays one analyser pass - the constrained-host OOM failure mode is not reintroduced."*

The operator's proposal - "async communications, with L0 chunk streams queueing at the supervisor layer, and persistence of the multi-agent system throughout the whole recon" - is exactly that non-goal.
It must be ratified as a reversal, not slipped in as an implementation detail.

### 3.2 Does the rejection still hold?

**It was right for a reason that is narrower than the sentence suggests, and that reason can be engineered away.**

The documented OOM was not caused by the analyser.
It was phase 4 holding up to `MAX_PODS=20` concurrent pod subgraphs, each with LangGraph state, large MCP tool outputs and LLM context, on a host with 3.83 GiB shared across agent, neo4j, postgres and kali, with no `mem_limit` on the agent container (still absent - `docker-compose.yml` declares none).
The fix that resolved it was sequentialising jobs within a phase (`pipeline.py:523-528`), and the OOM has not recurred since.

The analyser's own residency is small and, critically, is *already paid today*: the cumulative L0 slice, one 100-asset chunk, one prompt and one response.
On this run that is 190 L0 nodes; the largest recorded surface is 1364 nodes.
Projecting those to `AssetDelta`s, chunking them, and serialising the supervisor state is on the order of tens of megabytes, not gigabytes.

What the rejection correctly forbids, and what I also forbid below, is the *unbounded* form: a queue that accumulates chunk payloads, or more than one analyser pass in flight.
Those reintroduce accumulation on a host that has no memory ceiling and has already died once from accumulation.

**So: the rejection no longer holds for a bounded single-consumer with a depth-1 queue of cursors, and still holds for everything else.**
The concrete claims that make it safe *this* time are stated in §5.1 and are assertions, not assurances.

### 3.3 Purity versus persistence - where the line is

The analyser is specified as a pure `f(L0-slice + observations) -> L1-deltas` (`CODING_STANDARD.md:145`, `src/polymerhus/analysis/analyser_types.py:11-13`), and the `Chunk` is frozen and carries no L1 context precisely so nothing stale is welded onto a work order (`src/polymerhus/analysis/chunking.py:12-14, 86-88`).

The line is between **machinery** and **evidence**.

Resident across a whole recon run is legitimate for: the compiled `StateGraph` (pure code, no run data), the consumer task itself, the queue of cursors, and the process-wide concurrency semaphore.
Resident across passes is **forbidden** for: L0 slices, `AssetDelta` projections, `Chunk`s, the L1 inventory, and any accumulated proposal set.

This is not a new rule; it is `#17` DP-1, already recorded in the supervisor's own docstring - "There is NO proposal-accumulator channel: the live graph is the accumulator" (`src/polymerhus/analysis/supervisor.py:17-19`).
A resident supervisor that re-derives every input at dispatch time is therefore *not* in tension with purity.
A resident supervisor that holds the surface between passes is.

Note that the state is *already* persistent in the way the operator asks for: `run_supervisor` defaults `thread_id` to the run id (`src/polymerhus/analysis/supervisor.py:308`), and streaming passes `stream-<run_id>` as the run id, so every pass resumes the same checkpointed thread.
The measured step counter running 0 to 63 across seven separate `asyncio.run` calls proves it.
What the proposal calls "not dispatching new agents on each stream" is therefore already 95% true, and the remaining 5% - constructing a `StateGraph` and opening two Postgres connections - is milliseconds.
**I recommend against pursuing agent residency as a performance measure, because the measurement says it buys nothing.**

### 3.4 Convergence - what a queue of deltas would destroy

`L1D-23` holds that push and pull produce identical reads and writes, and the mechanism is stated plainly at `l0_stream.py:8-15`: each streaming step re-reads the full current slice, which is what makes the final streamed pass equal the batch pass.

If the queue delivered per-job deltas instead, that guarantee is gone, for two independent reasons.

First, a per-job delta is not obtainable from the graph.
`PodExport` carries counts, which the pipeline sums into `produced_assets` / `produced_observations` (`pipeline.py:454-455`), and L0 nodes carry `first_seen` / `last_seen` but no `source_job`.
Adding one means editing `recon/domain/curator.py` and `db/neo4j/schema.py`, both on the escalate-never-edit list (`loop-constraints.md:18`).
It *is* obtainable inside the pod, which holds the `AssetDelta` list in memory - but harvesting it there means widening `PodExport` from a counts contract to a payload contract, which is the payload-accumulation the OOM taught against.

Second, and more fundamentally, delta-only analysis is not merely an efficiency change - it changes the answer.
An Endpoint judged unownable in phase 3 may become assignable once phase 5 reveals the Service that owns it, and only a cumulative pass re-opens that judgment.

**Recommendation: the queue carries cursors, not deltas.**
A cursor says "the surface advanced; re-derive"; the consumer does the read itself, exactly as `run_analyser_chunked` does today.
Convergence is then preserved *unchanged*, because every pass is still cumulative, and the only thing the queue changes is *when* and *how many* passes happen.

The one new obligation this creates is §4.4's terminal pass: run completion must not precede a pass over the settled surface.
Today that is free, because the last streaming step is synchronous and the last job's surface is in it.
Under a queue it must be engineered, or convergence is lost at the exact moment it matters.

### 3.5 The independence claim, interrogated

The operator says recon and analysis are two independent modules whose runtime behaviour should replicate that independence.

They are already independent in the sense the architecture cares about: two bounded contexts, a one-directional supplier/consumer relationship, and an anti-corruption seam where the interpretive writer `MATCH`es L0 nodes and never `MERGE`s them (`CONTEXT-MAP.md`, "Relationships"; `l1_curator.py:315-322`).
The integration seam between them is **the shared Neo4j L0 graph**, which is a published, read-only substrate for Analysis.

A queue does not remove that coupling.
After the change, analysis still reads L0 straight out of the same database, and a schema or vocabulary change in `recon.domain.types` still propagates.
What the queue removes is a *temporal* coupling: recon's forward progress waiting on an analyser LLM call.

So the honest framing is: **the graph is the integration seam and remains so; the queue is a scheduling change.**
That is not a criticism - the scheduling change is worth making, and it is what the measured evidence demands.
But it should be named accurately, because calling it "decoupling the modules" invites a follow-on expectation (that analysis could now run elsewhere, or against a different substrate) that the change does not deliver.

Genuine runtime independence would require analysis to consume a published L0 stream rather than query the recon store - a real published-language boundary with its own transport and its own copy of the data.
That is a much larger change, it re-opens the delta-obtainability problem of §3.4, and I do not recommend it: the graph-as-substrate design is deliberate, and its ACL is one of the strongest parts of this codebase.

### 3.6 Failure semantics under a queue - the policy for each case

Today the semantics are trivially total: a streaming failure degrades one step, fail-open at two layers (`streaming.py:44-51`, `pipeline.py:512-518`), and recon continues.
A queue is a new place for delivery semantics to be left to chance, which `CODING_STANDARD.md` §5 forbids, so each case gets a named policy.

| Case | Policy |
|---|---|
| Consumer task dies (unhandled exception, cancellation) | Recon never fails on analysis. The pipeline's `finally` inspects the task; a dead consumer is logged and recorded in run stats as `analysis_consumer: "dead"`. The run still reaches `complete`. One restart attempt is a grilling question (§7 Q8), not a default. |
| Queue overflow | Structurally impossible: depth 1 with coalescing. A `put` onto a full queue **replaces** the pending cursor and increments a `coalesced` counter that rides the run stats, so the collapse is observable rather than silent. |
| Poisoned chunk | Chunks are rebuilt from the graph each pass, so a chunk that kills a pass would kill every subsequent pass. The existing per-dispatch fail-open contains it (`supervisor.py:142-146` degrades one proposer step), and a per-pass wall-clock deadline contains the rest. |
| Recon finishes with the queue non-empty | Drain: the pipeline enqueues a terminal cursor and awaits the consumer for at most `ANALYSIS_DRAIN_DEADLINE_S`, **before** cancelling the heartbeat. On expiry the run completes with `analysis_drained: false` in its stats. Never an unbounded wait. |
| Two runs at once | Each run owns its consumer and its `stream-<run_id>` thread, so their checkpoints and schedules cannot collide. Memory is protected by a **process-wide semaphore of 1** analyser pass, so N concurrent runs still cost one pass of residency. |
| Postgres unavailable mid-pass | Already the dominant infrastructure failure mode: postgres crash-recovers under load and the pipeline has zero tolerance for it. The consumer opens its saver/store **per pass**, not for the run, so a recovery costs one degraded pass rather than a permanently broken consumer. |

The drain ordering is load-bearing and easy to get wrong.
`REAP_TTL_SECONDS` defaults to 300 (`src/polymerhus/app/config.py:15`), and the reaper has already killed healthy runs on a stalled heartbeat.
The drain must therefore run inside the `try`, before `hb.cancel()` at `pipeline.py:530-535`, so the heartbeat keeps ticking through it.

### 3.7 Ordering and idempotency

With cursors and coalescing, ordering is not a hazard - it is undefined by construction, because every cursor carries the same request ("re-derive over the current surface") and differs only in when it was raised.
Duplicate delivery costs one extra idempotent pass; every L1 write is a `MERGE` on identity (`L1D-22`, `loop-constraints.md`), so a repeat pass converges rather than duplicating.

One subtlety worth recording because a future reader will trip on it.
`dispatch_id` is `{run_id}:{chunk_id}:{role}` (`supervisor.py:369`) and `chunk_id` is `{source_job}:{batch_index}` with `source_job = "stream-<run_id>"` (`supervisor.py:423-427`, `chunking.py:227`), so dispatch ids **repeat across passes**, and `merge_receipts` replaces in place rather than appending (`supervisor.py:53-68`).
This was verified live: after seven passes the receipts channel held exactly two receipts.
That is benign today and keeps state bounded, but it means the receipts trail is a *latest-state* view, not a history.
Any future component that sequences on it as history will be wrong.

If the queue ever carries payloads (which I recommend against), ordering stops being free: two out-of-order deltas over the same Endpoint would have the later judgment overwritten by the earlier one on the `AGGREGATES` envelope, because MERGE is last-write on properties.

---

## 4. The design

### 4.1 Topology

```
run_pipeline (async, API event loop)
  |
  |-- per job, after upsert_job:  feed.advance(job, produced_assets, produced_observations)   [non-blocking]
  |
  |-- finally (heartbeat still alive): feed.drain(deadline) -> then hb.cancel() -> set_run_status complete
  |
  +-- analysis consumer task (asyncio.Task, one per run)
        loop:
          cursor = await queue.get()            # depth 1, coalescing
          async with ANALYSER_PASS_SEMAPHORE:   # process-wide, value 1
              await analyse_chunked_async(project_id, "stream-<run_id>")
```

One consumer, one queue, one pass in flight process-wide.
The consumer runs concurrently with recon jobs, which is the whole point; the semaphore is what keeps that concurrency from becoming accumulation.

### 4.2 Queue shape and back-pressure

The queue is an `asyncio.Queue(maxsize=1)` carrying an **analysis cursor**: a frozen value object of `{project_id, run_id, job, phase, produced_assets, produced_observations, terminal}`.
It carries no assets, no chunks, no observations, and no L1 context.

Back-pressure is **coalescing, never blocking**: `advance()` uses `put_nowait`, and on `QueueFull` it drains the pending cursor and puts the new one, incrementing `coalesced`.
This is correct rather than merely convenient, because the cursors are idempotent and cumulative - five pending signals mean exactly one more pass is needed, not five.
Blocking back-pressure is explicitly rejected: it reintroduces the stall this design exists to remove.

### 4.3 Lifecycle

`run_pipeline` starts the consumer, alongside the heartbeat task it already manages, and owns its shutdown.
Recon never fails on analysis: a consumer that dies is recorded, not propagated.

The two modes live behind ONE seam so the call site does not branch.
`start_analysis_feed(project_id, run_id, *, mode)` returns a handle with exactly two methods, `advance(...)` and `drain(deadline)`:

- **inline feed** (today's behaviour, the rollback path): `advance` calls `stream_analyser_step` via `asyncio.to_thread` exactly as `pipeline.py:511-518` does now, `drain` is a no-op;
- **queued feed** (the new behaviour): `advance` enqueues a cursor, `drain` enqueues a terminal cursor and awaits the consumer to quiescence or the deadline.

The pipeline therefore keeps a single analysis touchpoint plus one drain in the `finally`, and the mode is a settings flag.

### 4.4 The terminal pass - the convergence guarantee, engineered

`drain` enqueues a cursor with `terminal=True` and awaits **one pass that begins after the last recon curate**.
That pass, being cumulative, is by construction the batch pass over the settled surface, which is precisely what `L1D-23` and `AST-STREAM-05` assert.

The terminal pass is exempt from any settled-surface skip optimisation (§7 Q10), so a run always ends with a full cumulative judgment.
If the drain deadline expires first, the run completes with `analysis_drained: false`, and the convergence claim is explicitly *not* made for that run - an honest hole rather than a silent one.

### 4.5 What is resident, what is re-derived

| Resident for the run | Re-derived every pass |
|---|---|
| The consumer task and its depth-1 queue | The L0 surface read (`l0_stream.read_l0_assets`) |
| The compiled supervisor graph (code, no data) | The BaseURL profile set (`l0_stream.read_baseurl_profiles`) |
| The checkpointed thread `stream-<run_id>` (already true today) | The chunk sequence (`chunking.chunks_for_job`) |
| The process-wide pass semaphore | The schedule (`supervisor.build_schedule`) |
| | The L1 inventory, read at dispatch time (`assigner.make_assigner_body`) |
| | The `AsyncPostgresSaver` / `AsyncPostgresStore` for the pass |

The saver and store are deliberately **not** resident, against the letter of the proposal, because the documented postgres crash-recovery would leave a run-scoped connection permanently broken while a per-pass connection costs milliseconds and degrades exactly one pass.

### 4.6 Seams

**Reused, unchanged:**

- `supervisor.build_supervisor_graph` (`supervisor.py:215`)
- `supervisor.run_supervisor` (`supervisor.py:287`) - already async-native
- `supervisor.build_schedule` (`supervisor.py:353`)
- `supervisor._aggregates_write_fn` (`supervisor.py:459`)
- `chunking.chunks_for_job` / `admit_for_role` (`chunking.py:184, 113`)
- `l0_stream.read_l0_assets` / `read_baseurl_profiles` (`l0_stream.py:73, 88`)
- the `AsyncPostgresSaver` / `AsyncPostgresStore` opening (`supervisor.py:324-329`)
- the pipeline's `stream_fn` injection point (`pipeline.py:250, 270-271`)

**New - two, and they are the minimum:**

1. `analysis/feed.py` - the `AnalysisCursor` value object, the `AnalysisFeed` protocol with its two implementations (`InlineAnalysisFeed`, `QueuedAnalysisFeed`), and the consumer coroutine.
   This is the only new module.
2. An **async entry** to the chunked analyser.
   `run_analyser_chunked` currently calls `asyncio.run` (`supervisor.py:439`), which cannot be called from the event loop the consumer runs on.
   The fix is an extraction, not a second implementation: move the body into `async def analyse_chunked(...)` and leave `run_analyser_chunked` as the sync wrapper that `asyncio.run`s it, so every existing caller and test is unchanged and there is exactly one implementation.

**Modified:** `pipeline.py` - the per-job hook becomes `feed.advance(...)`, and a `feed.drain(...)` lands in the `try` before `hb.cancel()`.

No change to `l1_curator.py`, to `recon/domain/curator.py`, to the L0 schema, or to `PodExport`.

---

## 5. Consequences

### 5.1 Memory on a 3.83 GiB host

Today's peak is `max(phase-4 pod fan-out, one analyser pass)`, because the analyser is strictly serialised after each job.
The proposed peak is `phase-4 pod fan-out + one analyser pass`, because they now overlap.
That `+1` is the entire memory cost of this design, and it is bounded by the semaphore rather than by hope.

Estimated marginal residency of one pass, reasoning from the measured surfaces:

- the L0 slice read as `{nodes, links}` dicts: the largest recorded surface is 1364 nodes; at roughly 1-2 KB per node with Python dict overhead that is 1.5-3 MB;
- the `AssetDelta` projection of the same: a second 1.5-3 MB;
- the chunk sequence, which copies the admitted assets again: up to another 3 MB;
- the rendered prompt and the structured response for one 100-asset chunk: 100-300 KB;
- the serialised supervisor state written to the checkpointer: same order as the chunk, roughly 1 MB;
- HTTP and provider client buffers: single-digit MB.

**Stated peak estimate: under 50 MB marginal, against a measured agent footprint of roughly 12% of 3.83 GiB (about 460 MB).**
That is an estimate from node counts, not a measurement, which is why NFR-MEM in §6 exists and why I recommend adding a `mem_limit` to the agent service so the next OOM names itself instead of taking the host down.

The forms that would break this bound, and are structurally excluded: a queue holding chunk payloads (excluded - cursors only), more than one pass in flight (excluded - semaphore of 1), and a run-scoped accumulation of proposals (excluded - `#17` DP-1, graph-as-accumulator).

### 5.2 LLM calls versus today

Today: `sum over jobs of ceil(surface_j / 100)` dispatches, each up to 3 outer attempts times the provider client's own retry budget, with no request timeout.
Measured on run `64f2ccb8`: 7 passes, 1-2 chunks each, roughly 10 dispatches, roughly 25 minutes.

Under coalescing, passes are bounded by `ceil(recon_wall_clock / pass_duration) + 1` rather than by job count, because every signal raised during a pass collapses into one.
For the measured run - about 10 minutes of real recon work and about 4 minutes per pass - that is roughly 3 passes plus the terminal one, against 7.
Combined with a request timeout (§7 Q2) and the optional settled-surface skip (§7 Q10), the expected reduction is roughly half the dispatches and close to all of the *stall*.

The honest caveat: decoupling alone does not reduce total analyser work, it relocates it.
Without Q2 and Q10 the same 25 minutes still has to be spent, and now it is spent after recon ends, where the drain deadline will eat it.

### 5.3 Convergence

Unchanged, provided §4.4 holds.
Every pass remains cumulative, so `L1D-23`'s "push and pull produce identical reads and writes" still follows from the same argument it always did, and the terminal pass is the one that carries the guarantee.
The guarantee moves from *implicit* (the last streaming step happens to be synchronous) to *explicit* (a terminal cursor that the run joins on), which is a strict improvement in legibility and a strict increase in the number of ways it can be broken.

### 5.4 What becomes harder to test

- **Pass count is no longer deterministic.** It depends on timing, so no assertion may name it. Assertions must name invariants instead: a terminal pass exists, the final L1 equals the batch L1, no job gap exceeds a bound.
- **The unit tier must stay timing-free.** The consumer is an `asyncio.Task`; testing it with sleeps produces exactly the flakiness `loop-constraints.md` forbids papering over. Test it with an injected `analyse_fn` and explicit `await`-points, never with wall-clock waits.
- **Vacuity is the live danger.** An assertion that "no inter-job gap exceeds 60 s" passes trivially on a run where the analyser never ran - which is precisely the `arjun` filter failure recorded in `docs/design/testing-strategy.md` §6. Every gap assertion must be paired with a non-vacuity predicate (at least one pass ran, at least two jobs produced surface).
- **The e2e now has a two-part terminal condition**: the run is `complete` AND `analysis_drained` is true.

---

## 6. Assertion sketch

Named to tier per `docs/design/testing-strategy.md`; contract predicates in `tests/integration/`, walkthroughs in `tests/e2e/`, pure seams in the unit tier.

```yaml
- id: AST-DEC-01
  kind: functional
  statement: "With the queued feed enabled, no analyser pass runs inline in the job loop: the injected analyse_fn is never entered on the task that runs run_pipeline."
  tier: unit
  observable: the thread/task identity captured inside the injected analyse_fn differs from the pipeline task's, and the pipeline's per-job hook returns before analyse_fn is entered.
  non_vacuity: at least one cursor was enqueued (the recorded cursor list is non-empty).

- id: AST-DEC-02
  kind: functional
  statement: "Cursors coalesce: N signals raised while a pass is in flight yield exactly one further pass, and the collapse is counted."
  tier: unit
  observable: with a gated fake analyse_fn, 5 advance() calls during one in-flight pass produce total passes == 2 and coalesced == 4.

- id: AST-DEC-03
  kind: nonfunctional
  statement: "Analysis never fails recon: an analyse_fn that raises on every call still leaves every recon job status unchanged and the run terminal at complete."
  tier: unit
  observable: registry.set_run_status called with "complete"; the per-job statuses equal those of an identical run with the feed disabled.

- id: AST-DEC-04
  kind: functional
  statement: "A terminal pass over the settled surface always precedes run completion (or its absence is recorded)."
  tier: unit
  observable: the last analyse_fn entry timestamp is after the last curate call, AND run stats carry analysis_drained == true; when the deadline is forced to expire, analysis_drained == false and the run still completes.

- id: AST-DEC-05
  kind: functional
  statement: "One analyser pass is in flight process-wide, across concurrent runs."
  tier: unit
  observable: a counting fake analyse_fn's maximum concurrent entry count == 1 while two run_pipeline coroutines run concurrently.

- id: AST-DEC-06
  kind: nonfunctional
  statement: "A pass is time-bounded: a provider that never responds degrades that pass within the deadline rather than hanging."
  tier: integration
  observable: with a stub provider that sleeps past the request timeout, the pass returns a degraded receipt within ANALYSER_PASS_DEADLINE_S, and the run's job sequence is unaffected.

- id: AST-DEC-07
  kind: functional
  statement: "Idempotent replay: two consecutive passes over an identical surface write no new L1 identities and no new AGGREGATES."
  tier: integration
  observable: counts of :L1Service, :L1System, :L1DataItem and AGGREGATES before and after the second pass are equal.

- id: AST-DEC-08
  kind: functional
  statement: "Convergence (the L1D-23 gate): after a live decoupled run reaches complete with analysis_drained true, a further idempotent streaming pass over the final surface adds ZERO new L1 identities and ZERO new AGGREGATES."
  tier: e2e
  observable: the four counts above, before and after; and prov_job on every AGGREGATES edge still matches 'analyser:stream-%'.
  note: the convergence check MUST use the same stream-<run_id> analyser id, never a batch id - a batch pass re-MERGEs every edge and overwrites prov_job (the NM-7 clobber gotcha).

- id: AST-DEC-09
  kind: nonfunctional
  statement: "The stall is gone: on a live decoupled run, no gap between a job's finished_at and the next job's started_at exceeds ANALYSIS_MAX_JOB_GAP_S."
  tier: e2e
  observable: max(next.started_at - prev.finished_at) over consecutive rows of recon_jobs for the run.
  non_vacuity: the run has >= 3 jobs with produced_assets > 0 AND >= 2 analyser passes ran (checkpoint thread step count increased between two job boundaries). Without this pair the predicate passes on a run with analysis switched off.

- id: AST-DEC-10
  kind: nonfunctional
  statement: "Analysis coverage does not regress: the decoupled run writes at least as many AGGREGATES over the same target as the inline run did."
  tier: e2e
  observable: AGGREGATES count for the project, compared against the recorded inline-mode baseline for the same target and seed.
  note: comparative, not a threshold - the analyser is non-deterministic (AMV-9), so this is judged over repeated runs in the agent-configuration eval's style, never as a single pass/fail.
```

`AST-DEC-09` and `AST-DEC-10` together are the real gate: the first proves the stall is gone, the second proves it was not bought by doing less analysis.
Either one alone can be satisfied by a broken system.

---

## 7. Grilling questions

Depth-ordered.
Each states its dependencies; a question that only matters under a particular answer says so.

### Q1 - What is this change for: removing the stall, or reducing analyser cost? (root; everything depends on it)

- **(a) Decouple only.** Recon stops waiting; total analyser work is unchanged and moves into the drain tail.
- **(b) Fix the cost defects first (bounded call, no re-judging settled surface), decouple second, as two tickets.**
- (c) Both in one ticket.

**Recommended: (b).**
The measured 19.3-minute step is an unbounded LLM call, not a scheduling problem, and (a) would ship a design whose drain deadline immediately becomes the new stall.
(c) is one ticket with two independent failure modes, against the loop's one-bounded-area discipline.

*Downstream:* under (a), Q10 is dropped and Q7's deadline must be generous (10+ minutes), which weakens `AST-DEC-09`.
Under (b) the decoupling ticket is small and its assertions are sharp.

### Q2 - Do we bound the analyser provider call? (depends on Q1; blocks the value of everything below)

- **(a) Request timeout plus an explicit total attempt budget on the `analyser` role model.**
- (b) A per-pass wall-clock deadline only, leaving the individual call unbounded.
- **(c) Both: a per-call timeout and a per-pass deadline.**

**Recommended: (c).**
`build_chat_model` sets neither today (`providers.py:40-42`), and `_invoke_with_retry(attempts=3)` multiplies whatever the client's own budget is.
An unbounded producer behind an async boundary does not remove a stall, it hides it as a backlog.

*Downstream:* if (b) alone, a single pass can still burn the whole drain budget and `AST-DEC-06` cannot be written at the call seam.
If neither, I would not recommend building the queue at all - it would convert a visible stall into an invisible one.

### Q3 - What does the queue carry? (independent of Q1/Q2; determines Q4, Q5 and the convergence story)

- **(a) A cursor: `{project_id, run_id, job, phase, counts, terminal}`. The consumer re-reads the surface.**
- (b) The job's `AssetDelta` payload, harvested by widening `PodExport`.
- (c) A pre-built `Chunk` stream, built at recon time.

**Recommended: (a).**
(b) requires changing the counts-only `PodExport` contract (`pipeline.py:454-455`) and puts payloads in a queue on a host that has already died from accumulation; (c) additionally freezes surface at recon time, which is exactly the stale-context hazard `chunking.py:12-14` was written to prevent.
Neither (b) nor (c) preserves convergence, because a delta pass never re-opens a judgment in the light of later surface (§3.4).

*Downstream:* only under (a) is coalescing possible, so a non-(a) answer forces Q4 to a bounded-depth drop-oldest or blocking policy, and forces an unconditional cumulative terminal pass anyway - i.e. (b)/(c) add cost without removing the cumulative read.

### Q4 - Queue depth and back-pressure? (only meaningful if Q3 = (a))

- **(a) Depth 1, coalescing: a new cursor replaces the pending one, with a counter.**
- (b) Bounded depth N, drop-oldest.
- (c) Bounded depth N, block the producer when full.

**Recommended: (a).**
The cursors are idempotent and cumulative, so a backlog of five means one more pass, not five; (b) is (a) with extra bookkeeping and no extra information; (c) reintroduces the exact stall being removed.

*Downstream:* under (a), queue overflow, ordering and duplicate delivery all stop being hazards at once (§3.7), and `AST-DEC-02` becomes writable.

### Q5 - How is memory safety enforced when the analyser overlaps the pod fan-out? (depends on Q4; this is the question that reverses the ratified rejection)

- (a) Nothing structural; rely on the pass being small.
- **(b) A process-wide semaphore of 1 analyser pass, plus a `mem_limit` on the agent service so an overrun names itself.**
- (c) Suppress the consumer during the highest-memory phase (phase 4) and let the backlog drain at the phase boundary.

**Recommended: (b).**
(a) is what the FR-STREAM ledger rejected, and rightly.
(c) sounds prudent but reinstates the stall precisely where the surface grows fastest, and phase 4 is the longest phase on every measured run.

*Downstream:* (b) is the concrete claim that makes the reversal defensible, and it is what `AST-DEC-05` asserts.
If the operator declines the `mem_limit`, the memory estimate in §5.1 stays an estimate and the reversal rests on argument rather than evidence.

### Q6 - Is a terminal cumulative pass mandatory before run completion? (depends on Q3; owns the L1D-23 guarantee)

- **(a) Yes: enqueue a terminal cursor and await one pass over the settled surface.**
- (b) No: rely on whatever the last coalesced pass happened to see.
- (c) No: run a batch pass out-of-band after the run, triggered separately.

**Recommended: (a).**
(b) silently drops the convergence guarantee, and the failure would be invisible - the run looks complete and the L1 is merely incomplete.
(c) has no production caller to trigger it: `run_analyser` is reachable only through `streaming.py` today (§2.5), so (c) means building a trigger that does not exist.

*Downstream:* (a) makes `AST-DEC-04` and `AST-DEC-08` writable and forces Q7.

### Q7 - What happens when the drain deadline expires? (only if Q6 = (a))

- **(a) Complete the run, record `analysis_drained: false` in run stats.**
- (b) Keep the run `running` until drained.
- (c) A new terminal status, e.g. `complete_analysis_pending`.

**Recommended: (a).**
(b) is dangerous: `REAP_TTL_SECONDS` is 300 (`config.py:15`) and the reaper has already killed healthy runs on a stalled heartbeat, so a long drain must at minimum keep the heartbeat alive - and even then, an unbounded wait on an LLM is the failure mode this whole design exists to remove.
(c) adds a status every consumer of the run API must now handle, for information a stats field carries adequately.

### Q8 - Consumer lifetime and death policy? (depends on Q6)

- **(a) One consumer per run, created and joined by `run_pipeline`; on death, record and continue.**
- (b) One process-wide consumer serving all runs.
- (c) Per run, with one automatic restart on death.

**Recommended: (a).**
(b) breaks the per-run `stream-<run_id>` thread and the drain join, and lets one project's analysis interleave with another's.
(c) is defensible but a restart that re-enters the same poison is worse than a recorded degradation; revisit if the field shows transient deaths.

### Q9 - Are the checkpointer and store opened per pass or held for the run? (only if Q8 = (a); this is where I disagree with the proposal's letter)

- **(a) Per pass, as today (`supervisor.py:324-329`).**
- (b) Once per run, held by the consumer.

**Recommended: (a).**
Postgres crash-recovery under load is the documented dominant infrastructure failure; a run-scoped connection would be permanently broken by it, while a per-pass connection costs milliseconds and degrades exactly one pass.
This directly declines the "persistence of the multi-agent system" wording where it would cost robustness for no measured gain (§3.3).

### Q10 - Do we stop re-judging settled surface? (depends on Q1 = (b); the biggest cost lever)

- (a) No: every pass re-chunks the full cumulative surface, as today.
- **(b) Yes, at dispatch level: skip a chunk whose admitted-identity set was already judged unchanged in this run; the terminal pass is exempt.**
- (c) Yes, at read level: read only surface newer than a watermark.

**Recommended: (b).**
It is the measured waste - the first 100 Endpoints were re-dispatched on all seven passes for 9 surviving edges - and being a dispatch-level skip it changes no read, so convergence is preserved by the exempt terminal pass.
(c) is (b) with the delta-obtainability problem of §3.4 bolted back on.

*Downstream:* if (a), the drain tail stays long and Q7's deadline must be generous.

### Q11 - How is the two-way door expressed? (independent; needed before any code)

- **(a) A new orthogonal `analysis.async_consumer` flag in the same `settings.recon` blob as `streaming_analysis` and `supervisor_enabled`, default OFF.**
- (b) Reuse `streaming_analysis` with a mode string.
- (c) An environment variable.

**Recommended: (a).**
It mirrors `supervisor_enabled` exactly (`analysis/CONTEXT.md:296-298`), keeps rollback to a per-project flag flip, and does not overload a flag whose current meaning ("analyse during recon at all") must stay intact.
(c) is process-wide and cannot be rolled back for one project.

### Q12 - Vocabulary. (independent; must be settled before the CONTEXT update)

The two new terms need names that do not collide with existing ubiquitous language.
`signal` is taken by recon's WAF steering signals (`pipeline.py:192`), `channel` by the observations channel and by LangGraph state channels, `dispatch` by `AgentDispatch`.

- **(a) `AnalysisCursor` (reusing "cursor" from `AgentDispatch.sweep_cursor`) carried on the `AnalysisFeed` (reusing "feed", the plan's own verb - "the analyser is fed each recon job's freshly-curated surface").**
- (b) `SurfaceAdvanced` as a domain event.
- (c) `AnalysisRequest`.

**Recommended: (a).**
(b) introduces an `*Event` type, which `CODING_STANDARD.md` §0 forbids speculatively - there is no event bus and this is not one.
(c) collides conceptually with the already-built `AnalyserReconRequest` (interface agreement B), which travels the other way.

---

## 8. Migration and rollback

This is a two-way door and must stay one until its e2e gate is green, exactly as `analysis.supervisor_enabled` was.

**The door.**
`settings.recon.async_analysis_consumer`, default OFF, orthogonal to both `streaming_analysis` and `supervisor_enabled`.
OFF selects the inline feed, which calls `stream_analyser_step` on the same task, at the same call site, with the same double gate and the same fail-open guard as `pipeline.py:504-518` today.
ON selects the queued feed.
Both implementations funnel into the *same* analyser entry, so no analysis code is forked and rollback cannot drift.

**Sequence.**

1. Land the bounded-call fix (Q2) on its own, behind no flag - it strictly improves the existing inline path and is independently verifiable.
2. Land `analysis/feed.py` plus the `analyse_chunked` async extraction, flag OFF, fully unit-tested. The runtime is unchanged at this point.
3. Wire the pipeline call site to the feed handle, flag still OFF. `AST-DEC-01` through `AST-DEC-05` must be green; behaviour with the flag off must be byte-for-byte today's.
4. Flip ON for one project and run the live gate: `AST-DEC-08`, `AST-DEC-09`, `AST-DEC-10`.
5. Only after two consecutive green live runs, consider making ON the default. The inline path is deleted only after that, and not in the same change.

**Rollback.**
A flag flip per project, at any of steps 3-5, with no data migration: the L1 store is written by the same sole-writer with the same idempotent MERGE either way, so a project can move between modes mid-life and converge.
The one non-reversible artifact is the run-stats fields (`analysis_drained`, `coalesced`), which are additive JSONB keys and inert to every existing reader.

**What would make me stop.**
If `AST-DEC-10` shows the decoupled run writing materially fewer `AGGREGATES` over repeated runs on the same target, the decoupling is buying speed by dropping judgments, and the correct response is to revert the flag and re-open Q6/Q10 rather than to relax the assertion.

---

## 9. Addendum - the runtime integration census, and the operator's standing position

Added after the specification above, from a full trace of every import edge and call site between the two modules.
It settles empirically what §3.5 argued from the architecture, and it surfaces two integration points the specification above does not account for.

### 9.1 The census

**recon -> analysis: exactly ONE runtime edge, and it is the blocking one.**

`pipeline.py:271` is the only `from polymerhus.analysis` import anywhere under `src/polymerhus/recon/`.
It has one call site, `pipeline.py:511-513`, which `await`s `asyncio.to_thread(stream_fn, project_id, run_id)` inside the per-job loop.
The thread offload moves the work off the event loop, but the coroutine still awaits it, so this is concurrency, not decoupling.
No other recon component waits on analysis anywhere.
`run_pipeline` ends at `pipeline.py:535` with `set_run_status(run_id, "complete")` - there is no terminal analysis trigger, no join, and nothing to drain today.

**analysis -> recon: three kinds, none of which block recon.**

- Shared kernel, import-time only: `chunking.py:31-32`, `l0_stream.py:24`, `anatomy.py:35`, `supervisor.py:422`. Value types and pure functions; no behaviour crosses.
- Shared infrastructure: `skill_for` at `bootstrap.py:680`, `curation.py:169`, `anatomy.py:167`, `anatomy.py:353`, `pod.py:180`.
- Analysis calling INTO recon: `pod.py:131` reads L0 via `recon.domain.graph_read.fetch_project_graph`, and `anatomy.py:315` WRITES through `recon.domain.curator.curate([], observations, project_id)`.

**Recon consumes nothing analysis produces.**
Grepping `steering.py`, `job_agent.py`, `orchestrator_agent.py` and `recon/domain/pod.py` for `L1` or `business_function` returns nothing.
No recon decision - job selection, steering, or pod configuration - reads an analysis output.
The `L1Service` / `L1System` handling at `graph_read.py:46-74` is display-projection code that happens to live in the recon module, not a recon consumer.

### 9.2 What the census changes

It strengthens §3.5: the dependency is already one-directional in fact, not merely in intent, so removing the single `await` at `pipeline.py:511` IS the whole of the runtime decoupling.
It also raises two things the specification above does not cover.

**(a) Analysis writing through the L0 sole-writer - RETRACTED.**
An earlier version of this addendum claimed that `anatomy.py:315` calling `recon.domain.curator.curate` becomes concurrent with recon's own curator writes under a queued consumer.
That is wrong, and the review caught it.
`commit_anatomy` is reachable only from `curation.py:278`, and `curation.run_curation` has no production caller - tests only.
The write path is exactly as unwired as the reverse seam below, so there is no concurrency to police and no policy owed.
The claim is left here, struck, because the reasoning that produced it (an import edge is not a runtime edge) is the same reasoning a future reader will need.

**(b) A reverse seam exists, built and unwired.**
`recon/control/targeted.py:110` `request_targeted_recon` lets analysis inject a recon job outside the phase barrier.
`anatomy.py:144` and `anatomy.py:376` construct `AnalyserReconRequest` objects, and `anatomy.py:260` records that they are RETURNED for a caller to dispatch.
No production code dispatches one - the only callers are `tests/integration/test_targeted_roundtrip.py` and `tests/recon/test_targeted.py`.
So the analysis -> recon request loop is a typed seam carrying zero runtime traffic today.
When it is wired, analysis will inject jobs into a running recon, and the one-directional dependency this design leans on becomes bidirectional.
A decoupling design that does not say what that does to a queue-driven consumer will have the answer retrofitted under pressure.

### 9.3 The operator's standing position

Recorded verbatim in intent, because the specification above recommends against a payload queue and the operator has not accepted that:

> A queueing tool is still needed to decouple these components at runtime and to guarantee robustly at-least-once delivery and creation of the L1 graph.

Two requirements are named there that the specification above does not treat as requirements.

**At-least-once DELIVERY.**
The specification's depth-1 coalescing cursor queue deliberately collapses pending signals, on the reasoning that cursors are cumulative and idempotent so five signals mean one more pass.
That gives at-least-once *re-derivation over the cumulative surface*.
It does NOT give at-least-once delivery of each job's increment, and the two are only equivalent while every pass re-reads everything.
If the operator's requirement is per-increment delivery, coalescing violates it and the design must change.

**Guaranteed CREATION of the L1 graph.**
Today nothing guarantees L1 exists at all: `run_analyser` has no production caller except `streaming.py:43`, so with `streaming_analysis` off no analysis runs, and with it on the run may still finish with the last surface un-analysed.
A guarantee of creation is a completion obligation on the run, not a property of the transport.
Whatever the queue shape, something must assert that the run does not reach `complete` with surface that no pass has seen.

---

## 10. Ratified decisions (operator, 2026-07-28)

The eight review questions are answered.
Where an answer differs from the review's recommendation it is marked, and the consequence the operator accepts is stated rather than re-argued.

| # | Decision | vs review |
|---|---|---|
| DQ1 | (a) At-least-once OBSERVATION of surface. Every L0 element curated during the run is read by at least one analyser pass. Nothing is guaranteed about what the analyser concluded. | as recommended |
| DQ2 | (b) The terminal pass must RECORD what it observed. `analysis_drained` is true only when the recorded `l0_assets_read` is at least the run's summed per-job `produced_assets` and `dispatches_entered` is at least one. | as recommended |
| DQ3 | (a) An in-process, per-run, depth-1 conflating handle. No broker, no persisted state, and NO reserved seam for a future durable mode. | differs: review preferred (c) |
| DQ4 | (a) No drain on abnormal termination. A cancelled or failed run records `analysis_drained: false` and makes no convergence claim. | as recommended |
| DQ5 | (a) The terminal pass is GATED on `streaming_analysis`. Off means off, byte-for-byte as today. | differs: review preferred (b) |
| DQ6 | (a) Accept the unbounded per-pass dispatch cost. No pre-dispatch admission filter. | differs: review preferred (c) |
| DQ7 | (b) Skip keyed on the content hash of the role-admitted identity set, terminal pass exempt. | as recommended |
| DQ8 | Backward recon requests are OUT OF SCOPE. Phase A.1 raises none; the reverse seam belongs to phase B, which is not in scope. | resolves by scoping out |

### 10.1 Consequences the operator accepts

**DQ3 (a), no reserved durability seam.**
Analysis does not survive an agent restart.
This is consistent: `run_pipeline` is a bare `asyncio.create_task` with no persisted execution position, so a run cannot itself be resumed, and durable analysis would be recovering the analysis of an unrecoverable run.
If recon runs ever become resumable, this decision must be re-opened before that work lands, not after.

**DQ5 (a), terminal pass gated on `streaming_analysis`.**
`consumer ON + streaming OFF` does NOT become post-recon batch analysis.
The configuration the L1D-23 two-way door describes therefore remains unreachable in production, exactly as today, and `run_analyser` keeps having no production caller other than `streaming.py:43`.
The measured economy the review argued for - one terminal pass instead of seven, which on run `64f2ccb8` would have produced a comparable L1 for one seventh of the analyser time - is not taken.

**DQ6 (a), unbounded per-pass dispatch cost.**
On the largest surface in this system (project `a9a1d0a0`, 40,953 non-Observation nodes, 40,805 of them `Subdomain`), `CHUNK_MAX_ASSETS=100` yields roughly 410 chunks and therefore 410 work orders per pass.
Each performs a live L1 inventory read (`assigner.py:444-445`) and its checkpoint writes BEFORE reaching the no-admitted-assets short-circuit (`assigner.py:381-384`), even though only about 138 `Endpoint` nodes are assignable.
So a wildcard-scope run spends minutes of Postgres and Neo4j traffic per pass before any LLM call, repeated on every cursor.
The `<50 MB marginal` figure in section 5.1 is derived from a surface number the review refuted and must be re-derived and MEASURED, not estimated, before the flag is enabled on any project.

**DQ8, scoped out.**
Phase A.1 raises no backward recon requests, so the one-directional dependency this design rests on holds for the whole of the current scope.
`request_targeted_recon` (`targeted.py:110`) stays built-and-unwired.
The `AnalysisFeed` handle therefore carries NO return path, and adding one later means changing the seam the design rests on - accepted, because phase B is a separate design.

### 10.2 The settled-surface skip: the risk the operator names (DQ7)

Content-hash keying is correct about IDENTITY: a window whose role-admitted identity set is unchanged holds the same surface, so re-judging it asks the same question.
The risk is that sameness of question does not imply sameness of answer, and the skip makes the FIRST answer permanent.

**The attention hazard.**
Within a 100-asset chunk the model does not attend uniformly.
The live run is its own evidence: on run `64f2ccb8` chunk 0 returned an `empty` receipt while chunk 1 returned all 9 `AGGREGATES`, from the same model over the same kind of surface in the same pass.
A skip freezes that attention allocation for the rest of the run.
An Endpoint that was under-attended on the pass that happened to reach it first is then never re-examined, and its missing or wrong assignment is indistinguishable from a deliberate withholding - the AMV-14 hazard, arriving through the cost lever rather than through the writer.

**Why the usual mitigations do not apply.**
Context drift is NOT the mechanism here.
The Assigner cannot mint (D4), so the L1 Service inventory is written by the Bootstrapper before recon starts and does not grow during the run.
Chunk composition changes are already caught, because any change to the admitted identity set changes the hash.
What remains is model non-determinism and intra-chunk attention, which no keying scheme can detect from the inputs.

**Recorded mitigation, NOT yet ratified.**
Never skip a chunk whose previous pass yielded zero kept aggregates.
That targets the observed failure directly - the `empty` receipt is the signal that the pass may not have attended to that window - at the cost of re-judging genuinely empty windows every pass.
It is recorded here as a candidate, to be decided when the cost lever is actually built, not assumed.

**What must be asserted.**
Any assertion for the skip must show that a skipped window is re-judged by the terminal pass (the exemption is what preserves DQ1(a)), and must FAIL if a skip key is ever derived from `chunk_id` or `dispatch_id`.
Section 3.7's note that dispatch ids repeat across passes reads as a licence to key on them; it is not, and keying on them would silently violate DQ1(a) because chunk indices are positional over an unordered read.

---

## 11. Implementation record (2026-07-28, `feat/recon-analysis-decoupling`)

Built per the section 10 decisions. Migration steps 1-3 of section 8 are complete; step 4 (the live gate) has not been run.

**Step 1 - the bounded provider call, behind no flag.**
`ChatOpenAI` was constructed with neither a timeout nor `max_retries` (`providers.py`), under `pod._invoke_with_retry(attempts=3)`.
That unbounded request is the mechanism behind the measured stall, so it is fixed on its own and independently: `LLM_REQUEST_TIMEOUT_S` (default 120) and `LLM_SDK_MAX_RETRIES` (default 0).
The SDK retry is set to zero deliberately: retry policy belongs to the one layer that already owns it, and leaving the SDK default of 2 multiplies the two ladders into up to nine attempts with no single place to reason about the bound.

**Step 2 - the async extraction and the census.**
`analyse_chunked` is now the single async implementation; `run_analyser_chunked` is the sync wrapper that `asyncio.run`s it, so every existing caller and test is unchanged.
It returns a `PassResult` carrying the `AnalyserExport` AND a `PassCensus` of `{l0_assets_read, chunks_built, dispatches_scheduled, dispatches_entered, aggregates_written, terminal}` (DQ2b).
`dispatches_entered` is counted inside the proposer body rather than from the schedule, because a dispatch that was scheduled but never entered is precisely the silent case the census exists to expose.

**Step 3 - the feed, and the pipeline call site.**
`analysis/feed.py` is the one new module: `AnalysisCursor`, `InlineAnalysisFeed`, `QueuedAnalysisFeed`, `start_analysis_feed`, `resolve_feed_mode`.
The pipeline keeps ONE analysis touchpoint (`feed.advance`) plus one drain, and the mode is a settings flag, so the call site does not branch.
`recon_runs.stats` (additive JSONB, idempotent ALTER + runtime self-heal, mirroring the `last_heartbeat_at` precedent) carries the feed stats so `analysis_drained` is durable and assertable rather than only logged.

**Two things the build got right only after they went wrong.**

A pending TERMINAL cursor must never be demoted by a later ordinary cursor.
Conflation replaces the pending cursor with the newer one, and the naive version dropped the terminal flag with it, so the drain would then wait for a pass that could no longer arrive.
`terminal` is a property of the RUN, not of the signal: once the run has stopped producing surface, that fact cannot be un-learned.
Asserted by `test_AST_DEC_02b_coalescing_never_demotes_a_pending_terminal_cursor`.

The consumer `stop` is unconditional in the pipeline's `finally`, while the DRAIN stays in the `try`.
DQ4a is about not draining on abnormal termination, not about leaking the task: a `drain` that raised before its own cleanup would otherwise leave the consumer running past its run.
`stop` is idempotent, so calling it on every path is free.

**Assertions.**
AST-DEC-01..05 in `tests/analysis/test_feed.py` (unit tier, pure seam, injected `pass_fn`), AST-DEC-06/07 in `tests/integration/test_decoupling_contracts.py` (real provider construction, real sole-writer, live Neo4j), plus four pipeline-level predicates in `tests/analysis/test_streaming.py` including one that pins inline mode to today's behaviour.
Every non-vacuity guard named in section 6 is carried: the drain assertions check that a pass actually RAN before checking that it claimed nothing.

**Not done at the time of the first commit, resolved in section 12.**
AST-DEC-08/09/10 are the live gate and need a real run; they were unwritten because AST-DEC-09 as specified is unimplementable - `recon_jobs.started_at` is stamped at phase setup for every job in a phase at once, so a per-job gap cannot be measured from it.
Section 12 records the operator's proposed remedy (derive the delta from Langfuse trace timestamps), the feasibility assessment that rejected it as the gate, and the observable that replaced it.

**Still open.**
The section 5.1 memory figure is derived from the refuted surface number and must be MEASURED before the flag is enabled on any project.

---

## 12. The stall observable: why not Langfuse, and what replaced it

*Operator proposal (2026-07-28): "if langfuse-based tracking is used extensively in the recon-job agents and the analyser agents, you can identify a reliable and faithful time delta using specific traces timestamps [...] If an analysis on the feasibility of this proposal does not yield a sufficiently accurate and reliable verification system, add the minimally required metadata to calls and persist it."*

### 12.1 Feasibility: rejected as the GATE, adopted for orientation

The proposal is sound about *where* the time is: the span tree does contain the true boundaries of a pass and of a pod.
It fails on the properties a *gate* needs, and it fails hardest in the failing case.

**It cannot be selected today.**
Recon spans carry no metadata at all - `job_agent.default_pod_invoke` and `crawl_pod.crawl_pod_invoke` both invoked with `config={"callbacks": ...}` and nothing else, so no recon span named a run, a phase, or a job.
The analyser side did set `langfuse_session_id`, but to its own `stream-<run_id>` id, so the two modules traced into two sessions sharing no key.
The specific delta the proposal names - "recon-job orchestrator call up to the next dispatch from the parent supervisor" - was therefore not expressible as a query against the data that exists.

**It is optional, and silently so.**
`get_langfuse_callbacks()` returns `[]` when any of three env vars is missing, when the package is absent, or when handler construction raises, and tells no caller (`app/observability/langfuse_tracing.py`).
A gate reading traces would find no spans, compute no gap, and report no stall.
That is the vacuous-gate trap the testing-tier discipline exists to prevent: the assertion passes loudest when the instrument is off.

**It is lossy exactly under stall conditions.**
The module's own root-cause note records that on a read timeout the OTLP exporter returns FAILURE after a single attempt and `BatchSpanProcessor` never retries, dropping the batch permanently; `RetryingSpanExporter` narrows the window but still logs "retry budget exhausted; dropping batch".
A stalling run is by definition one where latency is pathological, so the runs that most need the measurement are the runs most likely to lose it - and a missing span is indistinguishable from a fast one.
Two further lossy behaviours compound this: the 256 KiB masking cap, and the resource-manager singleton hazard that `_verify_configured_exporter_in_effect` exists to detect.

**It is out-of-process and eventually consistent.**
Reading it back requires a flush, server-side ingestion, an authenticated HTTP query, and a poll loop inside the assertion.

The conclusion is a division of labour rather than a rejection: **Postgres decides the verdict, Langfuse explains it.**
The pass/fail predicate is computed from values written synchronously by the code under test; the trace is what a human opens to see *why* a gap happened.

### 12.2 The metadata that was added, and where it is persisted

Minimal, and each item exists because a specific assertion could not otherwise be written.

| datum | where | why it did not already exist |
|---|---|---|
| `PassCensus.started_at` / `finished_at` / `duration_s` | returned by `analyse_chunked`, carried into `recon_runs.stats` | a pass reported what it observed but never how long it occupied |
| `FeedStats.advance_blocked_s_max` / `_total` | `analysis/feed.py`, both feeds | the quantity the decoupling exists to drive to zero was unmeasured |
| `FeedStats.pass_seconds_max` / `_total` | `analysis/feed.py`, both feeds | non-vacuity: proves a slow pass ran while the caller was not blocked |
| `recon_jobs.stats.exec_started_at` / `exec_finished_at` / `exec_seconds` | `pipeline._run_one` | `started_at` times phase setup, not the job (see below) |
| `langfuse_session_id` + run/phase/job on recon pods | `job_agent.pod_trace_metadata` | recon traces were unattributable to a run |
| analyser session keyed to the bare recon run | `analyse_chunked` `observe_metadata` | recon and analysis traced into disjoint sessions |

**The `started_at` defect, stated plainly.**
`pg.upsert_job` inserts with `started_at = now()` and its `ON CONFLICT DO UPDATE` sets `status`, `finished_at`, `stats`, `error` - never `started_at`.
The pipeline's phase loop inserts the `in_progress` row for *every* job of a phase during setup, before any of them runs.
So `started_at` is the phase's setup instant, identical across the phase's jobs, and any gap computed from it is an artefact.
Rather than change the column's meaning (it is a registry contract with other readers), the true window is persisted alongside it in the row's existing `stats` JSONB.

**One defect found while wiring this.** `recon_runs.stats` was written by `set_run_stats` but never selected by `get_run`, so the feed's report - including `analysis_drained` - was unreadable by anything, including the operator-facing `recon_status`. Both now carry it.

### 12.3 The revised AST-DEC-09

The statement is unchanged in substance; the observable is replaced.

```yaml
- id: AST-DEC-09
  kind: nonfunctional
  statement: "The stall is gone: on a live decoupled run, no recon job waits on an analyser pass."
  tier: e2e
  observable:
    primary: recon_runs.stats.advance_blocked_s_max < 1.0 - the longest any single
      feed.advance held the recon job loop, measured at the seam itself.
    corroborating: max(next.stats.exec_started_at - prev.stats.exec_finished_at) over
      recon_jobs ordered by exec_started_at, below ANALYSIS_MAX_JOB_GAP_S (default 60s).
  non_vacuity: stats.passes >= 2 AND stats.pass_seconds_max > 1.0 - a run where no
    pass ran, or where every pass was instant, cannot demonstrate anything about
    keeping a slow analyser off the critical path.
  rationale: the originally specified observable (recon_jobs.finished_at to the next
    row's started_at) is uncomputable - started_at times phase setup. Langfuse trace
    timestamps were assessed as the replacement and rejected as the gate (12.1).
```

The primary observable is also the one that reads directly against the inline mode: under `InlineAnalysisFeed` the blocked time *is* the pass duration (up to 1157 s on run `64f2ccb8`), under `QueuedAnalysisFeed` it is an enqueue.
`test_AST_DEC_09_queued_advance_does_not_block_while_inline_advance_does` asserts that contrast in the unit tier over the same injected slow pass, so the live gate is not the first place the predicate is exercised - and neither mode can pass it by doing less work, because `pass_seconds_max` is checked on both.

The live gate itself is `tests/e2e/test_decoupling_live_gate.py`, driven by `RECON_RUN_ID` against a completed run.
It skips without a run id, and *fails* rather than skips when the run exists but is uninformative - a run with fewer than three timed jobs, or no drained claim, or zero `AGGREGATES` is a failed gate, not an absent one.

---

## 13. The gate, run (2026-07-28)

Run `cbd134a8-f862-4f2b-a1ac-c20cfd672b7e`, project `6e6c9806-f55b-454a-bd11-759170147312`, target soupmarket.shop, jobs `httpx, katana, jsluice`, feed mode `queued`.
**All four assertions pass: AST-DEC-08, AST-DEC-09, AST-DEC-09b, AST-DEC-10.**

The decisive numbers, from `recon_runs.stats`:

| quantity | value |
|---|---|
| `advance_blocked_s_max` | **0.002 s** |
| `advance_blocked_s_total` | 0.003 s |
| `pass_seconds_max` | 155.5 s |
| `pass_seconds_total` | 252.8 s |
| `passes` / `advanced` / `coalesced` | 3 / 4 / 1 |
| `analysis_drained` | true |
| `l0_assets_read` / `dispatches_entered` | 176 / 2 |

The analyser performed 253 seconds of work while blocking the recon job loop for **three milliseconds**, and the conflating queue collapsed one signal exactly as designed.
The corroborating inter-job gaps were 1.3 s and 0.6 s, against 1190 s and 242 s on the inline run `64f2ccb8` that motivated this work.

This is also the first evidence that the non-vacuity guards are doing their job rather than decorating a green result: `passes >= 2` and `pass_seconds_max > 1.0` both held with room to spare, so the near-zero blocking figure cannot be explained by an analyser that did nothing.

**Section 5.1's memory figure is now measured, not estimated.** Peak agent RSS during the run was ~883 MiB of the 4.8 GiB limit, with the queued consumer and a 176-asset pass in flight. The refuted `<50 MB` estimate is withdrawn; the correct statement is that one bounded pass over this surface costs a few hundred MiB on top of the agent's ~440 MiB idle baseline, and the process-wide semaphore of one is what keeps that from multiplying.

---

## 14. The Assigner prompt arms, measured (2026-07-28) - and why the flip is NOT taken

Two runs, same target (soupmarket.shop), same jobs (`httpx, katana, jsluice`), same feed mode.

| | skill | baseline |
|---|---|---|
| project | `6e6c9806` | `fcd113e1` |
| aggregates | 55 | 43 |
| coverage | 0.366 | 0.313 |
| stale pool | 83 | 90 |
| mean confidence | 0.869 | 0.886 |
| multi-owner endpoints | 7 | 2 |
| **Services in inventory** | **23** | **11** |

**This comparison cannot support a flip decision, and the last row is why.**
The Bootstrapper wrote 23 Services for one run and 11 for the other, from the same operator KB, with its own config unchanged.
Inventory size is the single biggest determinant of how much surface *can* be assigned - an Assigner cannot assign to an owner that does not exist - so the coverage difference (0.366 vs 0.313) is not attributable to the prompt arm.
Reporting it as a skill-arm win would be exactly the error `evaluation.py` exists to prevent.

What the runs DO support:

- **No regression.** Neither coverage nor mean confidence degraded, and both arms sit far from the two known failure poles on this target: `soupstream_faf091e0` (11 aggregates, coverage 0.005) and `soup_9b876a3c` (246 aggregates, coverage 1.0, stale pool 0 - the over-assignment signature).
- **Assignment quality is sound on inspection.** `/forgot-password` to `password-recovery`, `/api/Complaints` to `complaint-refund-handling`, `/api/SecurityAnswers` to `password-recovery`, `/api/Feedbacks` shared by `content-moderation` and `product-reviews`, every edge citing a real path segment as evidence.
- **The withholding gate is working hard**, which no column here shows: the per-chunk logs record `proposed=53 kept=23 withheld=30` and `proposed=87 kept=31 withheld=56` on the baseline arm. A pass that proposed 87 aggregates over 84 admitted endpoints is over-proposing, and the bar is absorbing it.

**My recommendation was that `ASSIGNER_PROMPT_CONFIG` stay `baseline` until a matrix with repeats against a FIXED inventory settled it.**

**The operator overruled that and ratified `skill` as the default (2026-07-29).**
The distinction matters for anyone reading this later: the flip is a judgment about the skill's CONTENT - the no-owner null hypothesis, the confidence anchors, the differential over candidate owners, none of which existed in the baseline prompt - and NOT a conclusion drawn from the table above.
The measured claim these runs support remains only "no regression".

`baseline` stays byte-identical to the pre-skill prompt and is one env var away, so the rollback is free.
The matrix with a fixed inventory remains the outstanding deliverable, and 14.1 must be fixed before it can be run meaningfully.

One thing the flip surfaced immediately, recorded because it is a real (currently harmless) redundancy: the skill's fourth move is "CALIBRATE, THEN COMMIT OR WITHHOLD" and the reflect verbatim's third step is "CALIBRATE: state each confidence".
With `skill` as the default, the create pass now teaches calibration and the reflect pass re-teaches it.
That is harmless only because nothing dispatches `mode="reflect"`; whoever wires reflection must reconcile the two rather than shipping both.
`CALIBRATE` was consequently dropped from C25's reflect-marker set, which is now `REFLECT PASS` / `RESTATE AS EVIDENCE` / `COMPETING OWNER` / `RESIDUE` - all four verified absent from the skill body, so the assertion is unchanged in strength.

### 14.1 A defect in the harness itself, found by using it

`withheld_rate`, `out_of_inventory_rate` and `unresolvable_rate` read `0.0` for every arm above, and that is **false**.
The true values are in the log lines quoted above; the columns are empty because `AssignmentStats` is returned per chunk in `AssignmentOutcome` and persisted nowhere, so `read_assignment` - which reads the graph - cannot see them.

This is the vacuous-metric trap in its purest form: three columns that always read zero look like "no judgment was ever discarded", when in fact more than half of them were.
A reader comparing arms on those columns would conclude the withholding discipline never fires.
Until `AssignmentStats` is persisted per run, **those three columns must be read as "not measured", never as "zero"** - and the fix (persist the per-gate census alongside the feed stats, where `recon_runs.stats` already lives) is the first item on the follow-up list.
