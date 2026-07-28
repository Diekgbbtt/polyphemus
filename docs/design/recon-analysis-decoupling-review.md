# Adversarial review - `recon-analysis-decoupling.md`

*Status: REVIEW, not ratified. Written 2026-07-28 against `feat/assigner-classification-only`, second pass over the specification and its §9 addendum.*
*Every claim below was re-derived from the code, the live Postgres (`polymerhus-postgres-1`) and the live Neo4j (`polymerhus-neo4j-1`) in this environment, not from the specification.*
*Scope: the specification's reasoning and the decisions it leaves open. Non-scope: rewriting §1-§8, which are untouched.*

---

## 1. Review verdict

The specification's core direction holds - the analyser must come off recon's critical path, the queue must carry cursors rather than payloads, and the operator's "at-least-once delivery" is genuinely a completion obligation on the run rather than a transport property, exactly as §9.3 argues.
Its weakest point is that the one mechanism carrying the whole guarantee, the terminal pass of §4.4, is unfalsifiable as specified: every layer beneath it is fail-open, so a terminal pass that reads an empty surface and dispatches nothing still records `analysis_drained: true`, which is the same vacuity trap `testing-strategy.md:88-89` exists to prevent.
Before anyone builds this, three things must change: the terminal pass must record what it observed and not merely that it ran, the memory argument in §5.1 must be re-derived because its input number is wrong by a factor of thirty, and `AST-DEC-09` must stop measuring `recon_jobs.started_at` deltas because that column is stamped at phase setup for every job in the phase at once, not at job start.

---

## 2. Claims I checked

| # | Claim (section) | Verdict | Evidence |
|---|---|---|---|
| 1 | One blocking `await` from recon into analysis, at `pipeline.py:511` (§9.1) | CONFIRMED (line off by two) | The only `from polymerhus.analysis` import under `src/polymerhus/recon/` is `pipeline.py:271`; the gate is `pipeline.py:511`, the `await` is `pipeline.py:513`. |
| 2 | Jobs within a phase are sequential, not gathered (§2.1) | CONFIRMED | `pipeline.py:527-528` - `for name in job_configs: await _run_one(name)`. |
| 3 | `finished_at` is written before the streaming step, so every inter-job gap is streaming time (§2.2) | **REFUTED as methodology** | `finished_at` is written at `pipeline.py:495-502`, before the stream at 511-513 - that half holds. But `started_at` is stamped by `upsert_job(..., "in_progress")` at `pipeline.py:414-416`, inside the per-phase *config* loop that runs before `_run_one` is called for any job. Live proof: for run `64f2ccb8` all four phase-4 jobs (`katana`, `ffuf`, `paramspider`, `steel_crawl`) carry `started_at` within 60 ms of each other at `08:30:51`. Within a phase, `next.started_at - prev.finished_at` is negative. The two rows in the §2.2 table survive only because both happen to be phase boundaries. |
| 4 | 19 min 50 s gap between `steel_crawl` finishing and `jsluice` starting (§2.2) | CONFIRMED | `recon_jobs`: `steel_crawl.finished_at = 08:41:18.952`, `jsluice.started_at = 09:01:08.555`. |
| 5 | 65 checkpoints on thread `stream-64f2ccb8-...`, step counter monotonic across invocations (§1, §3.3) | CONFIRMED | `select count(*), min/max((metadata->>'step')::int) from checkpoints where thread_id='stream-64f2ccb8-f526-495b-a0ae-d2d3db59f0c5'` returns `65, -1, 63`. |
| 6 | 19.3 minutes inside one super-step, between step 44 and step 45 (§2.2) | CONFIRMED | `ts(44) = 08:41:49.936`, `ts(45) = 09:01:06.719`; delta 1156.8 s. |
| 7 | That super-step was a proposer node, and step 44 was the supervisor routing to the assigner (§2.2) | UNVERIFIABLE | Checkpoint `metadata` carries only `step`, `source`, `parents`, `langfuse_session_id` - no node name. The attribution is an inference from the topology at `supervisor.py:11-15`, not a record. It is plausible and nothing turns on it. |
| 8 | Seven streaming invocations totalling roughly 1530 s (§2.2) | CONFIRMED, precisely | Exactly 7 checkpoints carry `source='input'` (steps -1, 6, 13, 20, 31, 42, 53). Summing each pass from its `input` timestamp to its last step gives 0.04 + 0.05 + 4.39 + 69.4 + 59.4 + 1157.0 + 240.4 = **1530.7 s**. |
| 9 | The run was 33 wall-clock minutes, and the analyser owned about 72% of it (§1, §2.2) | REFUTED (immaterial) | `recon_runs.started_at = 08:29:47.44`; last job `started_at = 09:06:19.20`. Wall clock is 2192 s = **36.5 min**, so the analyser owned 69.8%, not 72%. The conclusion is unaffected; the number is wrong. |
| 10 | 605 s of actual recon work (§2.2) | CONFIRMED as a residual | 2192 s wall clock minus 1531 s of `ainvoke` minus roughly 50 s of pre-invoke pass setup leaves 611 s. The specification never states this is a residual rather than a measurement. |
| 11 | Roughly 4 minutes per analyser pass (§5.2) | REFUTED as a usable input | The seven measured passes are 0.04, 0.05, 4.4, 69.4, 59.4, 1157.0 and 240.4 s. The mean is 219 s only because of the single 1157 s outlier; the median is 59 s. §5.2 then projects "roughly 3 passes plus the terminal one" from that mean, while §7 Q2 exists to eliminate the very outlier the mean is made of. The projection is circular. |
| 12 | 136 Endpoints, 17 `L1Service`, 3 `L1System`, exactly 9 `AGGREGATES` (§2.3) | CONFIRMED | Neo4j census for project `00ea6ea4-...`: `Endpoint 136`, `L1Service 17`, `L1System 3`; `MATCH (s:L1Service)-[r:AGGREGATES]->()` returns 9, all with `prov_job = "analyser:stream-64f2ccb8-..."`. |
| 13 | The run was `cancelled` at phase 6 (§2.3) | CONFIRMED | `recon_runs.status = 'cancelled'`, `finished_at` NULL, `httpx_reprofile` left `cancelled` with no `finished_at`. |
| 14 | The receipts channel held exactly two receipts after seven passes (§2.3, §3.7) | UNVERIFIABLE here | Channel values live in `checkpoint_blobs` as msgpack; the `checkpoints.checkpoint` JSON carries no `receipts` array. The reducer behaviour it rests on is CONFIRMED at `supervisor.py:53-68` (replace-in-place by `dispatch_id`), and `dispatch_id` repetition across passes is CONFIRMED at `supervisor.py:369` + `supervisor.py:423-424`. |
| 15 | `run_analyser` has no production caller except `streaming.py` (§2.5) | CONFIRMED, and stronger than stated | Repository-wide search finds `pod.py:507` (the definition) and `streaming.py:43` only; every other hit is a test or a doc. The API router (`project_management/api.py`) exposes no analysis route at all besides `POST /projects/{id}/bootstrap`. So streaming really is the sole production trigger of analysis. |
| 16 | `build_chat_model` sets no `timeout` and no `max_retries`, under `_invoke_with_retry(attempts=3)` (§2.4) | CONFIRMED | `providers.py:40-42`; `pod.py:373`; `assigner.py:417-425`. |
| 17 | The FR-STREAM ledger names "a concurrent long-lived analyser consumer task" as a non-goal (§3.1) | CONFIRMED | `L1-MVP-plan.md:704`, restated at `streaming.py:22-24`. |
| 18 | No `mem_limit` on the agent container (§3.2, §5.1) | CONFIRMED | Neither `docker-compose.yml` nor `docker-compose.dev.yml` declares `mem_limit`, `deploy:` or `resources`. |
| 19 | **The largest recorded surface is 1364 nodes** (§3.2, and the input to the whole §5.1 memory estimate) | **REFUTED** | Excluding `Observation`, the largest project in this Neo4j holds **40,953** nodes (`a9a1d0a0-...`: 40,805 `Subdomain`, 138 `Endpoint`) with 40,955 intra-project edges. Second is 31,646, third 12,657. No project anywhere in the store holds 1364. |
| 20 | Marginal residency of one pass is under 50 MB (§5.1) | REFUTED as derived | It is computed from claim 19. It also omits that `fetch_project_graph` (`graph_read.py:110-136`) returns one row per *edge* and materialises a full copy of both endpoints' property bags per row, so the intermediate is O(edges), not O(nodes). |
| 21 | Rebuilding the `StateGraph` and opening two Postgres connections costs milliseconds (§3.3) | REFUTED as stated, conclusion survives | Measured per-pass interval from `finished_at` to the pass's `input` checkpoint: 1.01, 0.93, 0.22, 0.58, 16.02, 30.97, 0.65 s. Most of that is the L0 read and chunk build, which §4.5 keeps re-derived under either design, so "agent residency buys nothing" stands - but the figure is off by four orders of magnitude at the tail. |
| 22 | The state is already persistent - `run_supervisor` defaults `thread_id` to the run id (§3.3) | CONFIRMED | `supervisor.py:308` (`thread_id or run_id`); `run_analyser_chunked` passes no `thread_id` (`supervisor.py:439-441`) and `run_id` is already `stream-<run_id>` from `streaming.py:45`. |
| 23 | Adding `source_job` to L0 would mean editing the escalate-never-edit list (§3.4) | CONFIRMED | `loop-constraints.md:18` names `recon/domain/curator.py` and `db/neo4j/schema.py` explicitly. `l0_stream.py:8-15` records the same reasoning. |
| 24 | The ACL `MATCH`es L0 and never `MERGE`s it (§3.5) | CONFIRMED | `l1_curator.py:314-322`. |
| 25 | `REAP_TTL_SECONDS` defaults to 300 (§3.6) | CONFIRMED | `config.py:15`. |
| 26 | Recon consumes nothing analysis produces (§9.1) | CONFIRMED | No `L1`/`business_function` reference in `steering.py`, `job_agent.py`, `orchestrator_agent.py` or `recon/domain/pod.py`. |
| 27 | `anatomy.py:315` writes through recon's L0 sole-writer, and this becomes concurrent with pod writes under a queued consumer (§9.2a) | **REFUTED as a live concern** | The write exists (`anatomy.py:313-322`), but `commit_anatomy` is reachable only from `curation.py:278`, and `curation.run_curation` (`curation.py:368`) has **no production caller** - the only callers are `tests/analysis/test_curation.py`. It is exactly as unwired as the reverse seam in §9.2b, which the addendum labels as unwired while labelling this one as live. |
| 28 | `request_targeted_recon` is built and unwired (§9.2b) | CONFIRMED | `targeted.py:110`; the only callers are `tests/integration/test_targeted_roundtrip.py` and `tests/recon/test_targeted.py`. |
| 29 | `settings.recon` is the right settings namespace (§7 Q11, §8) | CONFIRMED | `pg.load_settings` selects the `recon` JSONB column (`pg.py:68-73`); the live row for the measured project carries `streaming_analysis: true` and `supervisor_enabled: true` as siblings of `target_seed`. |

Two internal inconsistencies worth recording: §7 Q11 names the flag `analysis.async_consumer` while §8 names it `settings.recon.async_analysis_consumer`, and §2.3 says six of seven passes contributed nothing while §2.4 says the first 100 Endpoints were re-dispatched on all seven.
Both are reconcilable, but an implementer would have to guess which name is the decision.

---

## 3. The delivery-semantics analysis

### 3.1 "At-least-once delivery" of what

Delivery semantics presuppose messages with distinct content.
In a depth-1 coalescing cursor queue every message has identical content - "the surface advanced, re-derive over what is now there" - so at-least-once delivery degenerates to a tautology: any single delivery occurring after the last enqueue discharges every prior enqueue.
The property is not meaningless, it is just not a property of the transport.

The property the operator actually wants, restated so it is falsifiable, is **at-least-once observation of surface**: no L0 element curated during a run may reach the run's terminal state without at least one analyser pass having read it.
That is well-defined under every queue shape, it is what "guarantee robustly the creation of the L1 graph" reduces to, and it is a completion obligation on the run.
§9.3 is right on this point, and the specification should adopt the phrase rather than argue against the operator's.

### 3.2 The Q10 interaction - the question I was asked to resolve

The claim to test is: cursors and payloads coincide only while every pass re-reads everything, so §7 Q10 (stop re-judging settled surface) silently destroys the guarantee the cursor design leans on.

It does not, and the reason is worth stating precisely because it turns on which of Q10's options is taken.

**Q10(a), no skip.** Every pass reads the whole surface. At-least-once observation follows from a single premise: one pass begins after the last `curate` of the run. Coalescing cannot violate it, because collapsing five signals into one still leaves one pass, and that pass sees everything the five would have.

**Q10(b), dispatch-level skip.** The *read* is unchanged - the pass still reads the full cumulative surface and still builds the full chunk sequence - and only the LLM dispatch for an already-judged chunk is suppressed. Because §4.4 exempts the terminal pass from the skip, the terminal pass still dispatches every chunk. The guarantee survives intact. This is the correct answer to the central tension: **the cursor design does not lose the guarantee under the biggest cost lever, provided the exemption is real and provided the skip is keyed correctly** (see §6 DQ7 - it cannot be keyed on `chunk_id`).

**Q10(c), read-level watermark.** Here the guarantee genuinely would be at risk, but not for the reason §9.3 gives. A watermarked consumer preserves at-least-once perfectly well *if* the watermark advances only after a pass succeeds - that is how every offset-based consumer works. What breaks it here is a data-model fact, not a queue fact: L0 carries no watermarkable ordering. There is no `source_job` and no monotonic sequence (`l0_stream.py:8-12`), only `first_seen` / `last_seen`, and `last_seen` is bumped on re-observation, so a `last_seen` watermark both re-delivers unchanged nodes and cannot distinguish a new node from a touched one. So (c) is blocked by the L0 schema, and unblocking it means editing the escalate-never-edit list (`loop-constraints.md:18`). (c) should be closed, not on convergence grounds but on this one.

The conclusion is that the coalescing-versus-per-increment argument is not the live question at all.
A payload queue would deliver increments, but it would still have to be followed by a cumulative pass, because §3.4's second reason is the load-bearing one and it is untouched by transport: an Endpoint judged unownable in phase 3 becomes assignable once phase 5 reveals its owner, and only a cumulative pass re-opens that judgment.
So a payload queue buys per-increment delivery *and still owes the terminal cumulative pass*.
It is strictly more machinery for strictly less guarantee.
**The first agent was right to recommend cursors, and right to reject payloads.**

### 3.3 What would actually make L1 creation guaranteed

§9.3 is right that this is a completion obligation, and the specification is right that the terminal pass is the mechanism.
Both are wrong about how much work it takes to make that mechanism real, because both treat "a terminal pass ran" as evidence that surface was observed.

It is not, and this is the single most important defect in the document.
Four fail-open layers sit under the terminal pass, each of which turns "observed nothing" into "completed successfully":

- `l0_stream.read_l0_assets` degrades a Neo4j read failure to an **empty surface** and returns `[]` (`l0_stream.py:81-85`);
- `run_analyser_chunked` returns an empty `AnalyserExport()` and dispatches nothing when `chunks` is empty (`supervisor.py:426-427`);
- the proposer wrapper degrades any body exception to a `degraded` envelope and continues (`supervisor.py:142-146`);
- `stream_analyser_step` swallows everything above it and returns `None` (`streaming.py:44-51`), and `pipeline.py:512-518` swallows that.

A terminal pass whose L0 read blipped therefore completes in milliseconds, writes nothing, and would set `analysis_drained: true`.
The run then claims a convergence guarantee it did not earn, and `AST-DEC-04` passes.
This is precisely the class of failure `docs/design/testing-strategy.md:88-89` records.

The weakest mechanism that delivers a real guarantee is small and cheap:
the terminal pass records `{l0_assets_read, chunks_built, dispatches_scheduled, dispatches_entered}` into run stats, and `analysis_drained` is true only when `l0_assets_read` is at least the run's summed `produced_assets` and `dispatches_entered` is at least one.
That costs four counters the analyser already computes for its Langfuse metadata (`supervisor.py:444-450`) and turns an unfalsifiable claim into a falsifiable one.
It does not need a broker, a durable log, or an outbox.

### 3.4 Is a queue justified at all

Steel-manning the operator, here is everything a queue buys over "make the one call at `pipeline.py:513` a task and join it at the end", honestly enumerated.

**Conflation.** A bare task-per-job leaves three choices: await it (today's stall), fire N overlapping tasks (N concurrent analyser passes - the OOM form the FR-STREAM ledger rejected), or keep one handle and skip the enqueue while it is busy. The third is a depth-1 coalescing queue whose queue can be a single boolean. This is real and it is the only structural thing the queue provides - but it is roughly fifteen lines of `asyncio`, not a queueing tool.

**Serialisation across concurrent runs.** The process-wide semaphore does this (§4.1). The queue contributes nothing.

**Ordering.** Undefined by construction and harmless, as §3.7 correctly argues. The queue contributes nothing.

**Durability across process restart.** This is the only thing a genuine queueing tool - a broker, or a Postgres-backed outbox - would buy, and it is where the operator's requirement should be scoped down. `run_pipeline` is launched as a bare `asyncio.create_task` in the API process (`project_management/api.py:104`) with no persisted execution position; on restart the run is simply gone and `reap_stale_runs` (`main.py:51`, `pg.py:297`) flips it to `failed`. A durable analysis queue would therefore let the system restart-recover the analysis of a recon run that no longer exists and can never be resumed. Durability at the analysis seam is strictly ahead of durability at the recon seam, and buying it first would be building the roof before the walls.

**Plainly stated: the operator's queue requirement should be scoped down.**
Keep the requirement - at-least-once observation of surface, and a guaranteed L1 pass - and reject the artefact.
The right artefact is an in-process, per-run, depth-1 conflating handle plus a terminal pass that records what it observed.
Build the durable variant when recon runs themselves become resumable, and not before; at that point the same seam (`start_analysis_feed`) takes a durable implementation without any call-site change, which is what makes it safe to defer.

I would also change the naming. Calling this "a queue" is what invites the broker reading; §7 Q12's `AnalysisFeed` with a single `advance()` / `drain()` pair is the honest name, and the internal depth-1 structure should not appear in the ubiquitous language at all.

---

## 4. Gaps and defects in the design

**D1 - The terminal pass is unfalsifiable.** §3.3 above. Consequence: the entire guarantee the design exists to provide can be silently absent, and `AST-DEC-04` and `AST-DEC-08` both pass while it is.

**D2 - The memory argument rests on a refuted number, and the worst case is thirty times larger.** §5.1 reasons from "1364 nodes"; the largest surface in this store is 40,953 nodes with 40,955 edges (`a9a1d0a0-...`, a wildcard-scope run: 40,805 `Subdomain`). Consequence, beyond memory: `chunks_for_job` at `CHUNK_MAX_ASSETS = 100` (`chunking.py:37`) produces roughly **410 chunks** on that surface, `build_schedule` emits one dispatch per chunk (`supervisor.py:367-374`), and each dispatch performs a live L1 inventory read before it can short-circuit (`assigner.py:444-445`, unconditional; the LLM short-circuit at `assigner.py:381-384` comes after it). One pass on that project is therefore roughly 410 inventory reads and 410 super-steps of Postgres checkpoint traffic before any LLM cost. §5.1 does not model this, and it is a far larger risk than the `+1` pass of residency the section does model.

**D3 - The `finished_at`/`started_at` methodology is wrong, and it propagates into `AST-DEC-09`.** Claim 3 above. Consequence: the stated dead-gap table happens to survive because both its rows are phase boundaries, but the assertion built on the same observable measures phase-setup latency and is blind to every streaming stall that occurs *between jobs inside a phase* - which on the measured run is four of the seven passes.

**D4 - The abnormal-termination path is unhandled, and the measured run took it.** `set_run_status(run_id, "complete")` sits at `pipeline.py:536`, **outside** the `try`/`finally` that ends at 530-535. Run `64f2ccb8` ended `cancelled`, not `complete`. §4.1 draws the drain inside the `finally`, which means it runs while a `CancelledError` is propagating - awaiting an LLM-bound drain there is at best ignored and at worst raises a second `CancelledError`. §3.6's table names "recon finishes with the queue non-empty" but never "recon does not finish". Consequence: on the exact class of run the evidence base is drawn from, the design has no defined behaviour.

**D5 - The flag matrix is not a two-way door in every cell.** Two cells are unanalysed. `async_consumer ON` + `streaming_analysis OFF`: no cursor is ever raised, but `drain()` still enqueues a terminal cursor, so this configuration would run exactly one cumulative pass at the end of a run - a post-recon batch that does not exist today and that nothing in §8 authorises. It is arguably the single most useful configuration in the document and it is unnamed. `async_consumer ON` + `supervisor_enabled OFF` routes through `run_analyser`'s legacy branch (`pod.py:551` onward), which is not chunk-fed and for which §4.6's "async entry" extraction does not exist - only `run_analyser_chunked` gets one. The consumer would have to `to_thread` the legacy path, which §4.6 does not say. Consequence: "orthogonal flag, default OFF" understates the interaction; two of four cells need a stated behaviour before code.

**D6 - Chunk windows shift between passes, and §7 Q10(b) does not account for it.** `chunks_for_job` windows the cumulative asset list in read order (`chunking.py:220-235`), and `_GRAPH_CYPHER` (`graph_read.py:110-116`) carries no `ORDER BY`. As the surface grows, window boundaries move, so `stream-<run_id>:0` names different content on every pass while `dispatch_id` stays identical (`supervisor.py:369`). §3.7 notices that ids repeat and calls it benign; it is benign for the receipts reducer, but it is fatal for any skip keyed on `chunk_id`. §7 Q10(b) says "admitted-identity set", which is content-keyed and therefore correct - but the document never says that `chunk_id` is unusable, and §3.7 reads as an invitation to use it. Consequence: the highest-value cost lever has a trap in it that the document half-marks.

**D7 - §9.2a is mis-classified.** Claim 27 above: the `anatomy.py:315` L0 write is reachable only through `curation.run_curation`, which has no production caller. The concurrency it warns about cannot occur today. This does not invalidate §4; it means the policy belongs on the ticket that wires curation, not on this one. Stating it as a live integration point overstates the coupling this design has to manage.

**D8 - §9.2b does invalidate part of §4, and the addendum stops short of saying how.** If a pass may raise an `AnalyserReconRequest` and something dispatches it via `request_targeted_recon` (`targeted.py:110`), three things in §4 break. The consumer would hold the process-wide pass semaphore while awaiting a live tool run, converting a memory guard into an availability guard. The targeted job curates new L0 surface, so a request raised *during the terminal pass* produces surface after the pass that was supposed to have settled it - the §4.4 convergence claim is then false by construction rather than by accident. And `_derive_status` in `targeted.py:100-107` writes a `recon_jobs` row outside the phase loop, so the job-gap observable is further polluted. Consequence: unless §4 states now that requests are returned to the pipeline rather than dispatched by the consumer, and states what a request raised during the terminal pass does, this will be retrofitted under pressure exactly as §9.2 predicts.

**D9 - `Chunk.observations` is always empty on this path.** `run_analyser_chunked` calls `chunks_for_job` without observations (`supervisor.py:425`), so `_observations_for` receives `None` and every chunk carries an empty observations tuple. `streaming.py:19-21` advertises auto-delivery of the cumulative Observation set as a property of the streamed path. On the `supervisor_enabled` path that property does not hold - the 149 `Observation` nodes on the measured project reached no proposer. This is out of scope for a decoupling design but it is on the escalation list from CLAUDE.md's "if something clearly looks off, get it fixed or reported", and it materially affects `AST-DEC-10`'s coverage baseline.

---

## 5. Assertion audit

**Sound as written:** `AST-DEC-02` (coalescing count is exact and falsifiable), `AST-DEC-06` (the only predicate in the set that would have caught the measured 19.3-minute step - keep it and raise its tier).

**Sound but over-claiming:** `AST-DEC-01` conflates task identity with thread identity; under the *inline* feed the work already runs on another thread via `asyncio.to_thread` (`pipeline.py:513`), so only the task discriminator is load-bearing and the observable should say so. `AST-DEC-05` states "process-wide" but observes two coroutines on one event loop, which tests the semaphore, not process scope.

**Vacuous:** `AST-DEC-04`, exactly as analysed in §3.3 - it passes when the terminal pass read an empty surface (`l0_stream.py:81-85`) or built no chunks (`supervisor.py:426-427`). It must additionally observe `l0_assets_read >= sum(recon_jobs.stats.produced_assets)` and `dispatches_entered >= 1`. `AST-DEC-03` has no non-vacuity clause at all and passes trivially with the feed disabled; it needs "the raising `analyse_fn` was entered at least once".

**Unfalsifiable in the wrong direction:** `AST-DEC-07` and `AST-DEC-08` both assert that a further pass over an identical surface adds *zero* new `AGGREGATES`. Idempotent `MERGE` guarantees no duplicate edge for the same `(Service, L0)` pair, but `#34` D3 makes multi-ownership legal, and AMV-9 records the analyser as non-deterministic. A second pass proposing a second legitimate owner for an already-assigned Endpoint therefore creates a new edge and fails the assertion, while behaving exactly as designed. The measured evidence makes this concrete: seven passes over a growing surface produced 9 edges over 136 Endpoints, and the pass that produced them was the sixth. These two must assert on *identity stability* (no new `:L1Service` / `:L1System` / `:L1DataItem` node, `prov_job` still matches `analyser:stream-%`) and treat edge count as a comparative measurement in the `evaluation.py` style, not as a threshold.

**Broken observable:** `AST-DEC-09`. `max(next.started_at - prev.finished_at)` over consecutive `recon_jobs` rows does not measure what the assertion says, because `started_at` is stamped at phase setup for all of a phase's jobs at once (`pipeline.py:414-416`). On the measured run that expression is negative within phase 4 and includes phase-setup reads at the boundaries. The correct observable is the checkpoint thread itself: `max(ts(step n+1) - ts(step n))` over `checkpoints where thread_id = 'stream-<run_id>'`, plus, per pass, `input_ts - prev_job.finished_at` for the pre-invoke interval. Its non-vacuity pair is good and must be kept.

**Missing predicates:**

- a bound on dispatches per pass as a function of surface size, without which the wildcard-scope case in D2 has no gate at all;
- an assertion that the drain runs while the heartbeat is still ticking (§3.6 names this as load-bearing and no predicate covers it);
- an assertion covering a run that terminates `cancelled` or by exception - the consumer must be shut down and `analysis_drained` recorded as false, on the path that `pipeline.py:536` never reaches;
- a named baseline for `AST-DEC-10`. "The recorded inline-mode baseline for the same target and seed" does not exist as an artefact. Run `64f2ccb8` on `soupmarket.shop` - 136 Endpoints, 9 `AGGREGATES`, 7 passes, 1531 s of analyser time - is the only baseline available and should be written into the assertion.

---

## 6. New design questions

Depth-ordered.
Each names its dependencies; a question that only matters under a particular answer says so.
None of these is answerable from the code - each is a decision.

---

### DQ1 - What exactly is guaranteed about L1 at the end of a run? (root; DQ2 through DQ5 all depend on it)

**Decision:** the precise property the operator's "guarantee robustly the creation of the L1 graph" is to be built against.

- **(a) At-least-once observation of surface.** Every L0 element curated during the run is read by at least one analyser pass before the run reaches its terminal state. Says nothing about what the analyser concluded. Consequence: falsifiable from counters the analyser already computes; buys nothing about coverage quality.
- **(b) At-least-once observation plus a non-empty judgment.** As (a), and additionally at least one `AGGREGATES` edge is written for the run. Consequence: fails a run over a target with genuinely nothing assignable, which is a real and legitimate outcome (AMV-14) - it makes an honest empty result look like a defect.
- **(c) At-least-once delivery of each recon job's increment.** Every job's produced surface is separately transported to analysis. Consequence: requires widening `PodExport` from a counts contract to a payload contract, and still owes a cumulative terminal pass afterwards, because a per-increment judgment cannot re-open an earlier one in the light of later surface. Strictly more machinery for strictly less guarantee.

**Recommended: (a).**
It is the only one of the three that is both falsifiable and honest.
(b) confuses a transport guarantee with an analysis-quality guarantee, which is what `AST-DEC-10` and the agent-configuration eval are for.
(c) is what "at-least-once delivery" sounds like it means, but the evidence says it does not deliver the guarantee it promises: coverage comes from the cumulative re-read, not from the transport.

*Downstream:* (a) makes DQ2 the whole of the guarantee work and closes the payload-queue branch permanently.
(c) re-opens `PodExport`, re-opens ordering as a hazard, and makes DQ7 unanswerable.

---

### DQ2 - What must a terminal pass record for that guarantee to be checkable? (depends on DQ1; this is the change I would insist on before any code)

**Decision:** what `analysis_drained: true` is allowed to mean.

- **(a) The terminal pass ran to completion without raising.** Today's shape, extended. Consequence: passes when the L0 read blipped to an empty surface, when no chunks were built, and when every dispatch degraded - all of which are silent under the four fail-open layers. The run then claims convergence it did not earn.
- **(b) The terminal pass ran AND recorded what it observed:** `{l0_assets_read, chunks_built, dispatches_scheduled, dispatches_entered}` in run stats, with `analysis_drained` true only when `l0_assets_read` is at least the run's summed per-job `produced_assets` and `dispatches_entered` is at least one. Consequence: four counters the analyser already computes for its trace metadata; turns the guarantee into something an assertion can fail.
- **(c) As (b), plus the pass must have written at least one L1 delta.** Consequence: conflates observation with judgment, and fails honestly-empty targets - the DQ1(b) problem again.

**Recommended: (b).**
Without it the design's central mechanism cannot be distinguished from its own absence, which is the failure mode the repository's testing strategy exists to prevent.
The cost is four integers.

*Downstream:* (b) makes `AST-DEC-04` and `AST-DEC-08` writable and is the precondition for closing DQ4 and DQ7.
(a) makes every assertion below it decorative.

---

### DQ3 - What is the transport artefact, and does it need to survive a process restart? (depends on DQ1; this is where the operator's queue requirement is scoped)

**Decision:** how much machinery the decoupling gets.

- **(a) An in-process, per-run, depth-1 conflating handle** (`AnalysisFeed` with `advance()` / `drain()`), no broker, no persisted state. Consequence: removes the stall, gives conflation, gives the terminal-pass join. Loses everything on a process restart - but so does the recon run itself.
- **(b) A durable queue** (a Postgres-backed outbox table, or a broker). Consequence: analysis survives an agent restart. But `run_pipeline` is a bare `asyncio.create_task` in the API process with no persisted execution position, and the reaper flips an orphaned run to `failed` - so durable analysis would be recovering the analysis of a run that cannot itself be resumed. It also introduces the first piece of infrastructure in this design that is not a flag flip to roll back.
- **(c) (a) now, behind a seam that (b) can be dropped into later** - the same `start_analysis_feed(project_id, run_id, *, mode)` handle, with a third mode reserved.

**Recommended: (c), which is (a) plus a named commitment.**
Durability at the analysis seam is strictly ahead of durability at the recon seam; build it when recon runs become resumable and not before.
I would also stop calling this a queue in the ubiquitous language - `AnalysisFeed` carrying an `AnalysisCursor` is the honest name, and the depth-1 structure is an implementation detail that should not appear in `CONTEXT.md`.

*Downstream:* (a)/(c) keep the change to one new module plus one modified call site.
(b) adds a schema migration, a second consumer lifecycle, and an at-least-once story that must now handle redelivery after restart - and it does not discharge DQ2, which still has to be built anyway.

---

### DQ4 - What happens to the guarantee on a run that does not reach `complete`? (depends on DQ2 and DQ3; the measured run took this path)

**Decision:** the behaviour of the drain on cancellation and on an unhandled exception.

Context the operator needs: the pipeline's terminal `set_run_status(..., "complete")` sits *outside* its `try`/`finally`, so a cancelled or failed run never executes it, and run `64f2ccb8` - the entire evidence base for this specification - ended `cancelled`.

- **(a) No drain on abnormal termination.** Cancel the consumer, record `analysis_drained: false`, let the run end as it was going to. Consequence: simple and honest; a cancelled run makes no convergence claim, which is correct. Any surface curated before the cancellation is analysed only to the extent the coalesced passes got to it.
- **(b) Drain on every path, including cancellation.** Consequence: awaits LLM-bound work while a `CancelledError` is propagating, which asyncio will either swallow or convert into a second cancellation; it also delays the run's terminal state past the reaper's 300 s TTL under exactly the conditions where the heartbeat is being torn down.
- **(c) Drain on exception, not on cancellation.** Consequence: distinguishes "the operator stopped this" from "this broke", which is the right distinction - but it doubles the exit paths in a function that currently has one `finally`.

**Recommended: (a).**
A cancelled run is an operator decision to stop, and finishing an analysis pass the operator asked to abandon serves nobody.
Whichever is chosen, the specification must also say where `set_run_status("complete")` moves to, because a drain that must precede completion cannot sit in a `finally` while completion sits after it.

*Downstream:* (a) adds one assertion (consumer shut down, `analysis_drained: false`, no exception escapes) and closes the §3.6 gap.
(b) requires a heartbeat that outlives the `finally`, which reverses §3.6's own ordering rule.

---

### DQ5 - Does the terminal pass fire when `streaming_analysis` is OFF? (depends on DQ2; determines what the flag matrix means)

**Decision:** whether the new flag introduces a post-recon batch pass that does not exist today.

Context: `run_analyser` has no production caller other than `streaming.py`, so with `streaming_analysis` off, no analysis runs at all today - "turn streaming off" means "no L1".
Under the queued feed, `drain()` enqueues a terminal cursor unconditionally, which would run one cumulative pass at the end of a run even with streaming off.

- **(a) Terminal pass gated on `streaming_analysis`.** Off means off, exactly as today. Consequence: behaviour with streaming off is byte-for-byte unchanged, and the two-way door is clean - but the most economical configuration in the whole design (analyse once, at the end, over the settled surface, at a cost of one pass instead of seven) remains unreachable.
- **(b) Terminal pass always fires when the consumer is enabled.** Consequence: `async_consumer ON` + `streaming_analysis OFF` becomes "post-recon batch analysis", the configuration the L1D-23 two-way door always promised and that no production caller has ever provided. It is a new behaviour introduced by a flag whose stated purpose is scheduling, which needs to be a ratified decision rather than a side effect.
- **(c) A third explicit value** - `analysis_mode` of `off` / `terminal_only` / `streamed`, replacing the boolean pair. Consequence: names the three real configurations instead of encoding them in the interaction of two booleans; costs a settings migration for two projects.

**Recommended: (b), stated explicitly as a decision, with (c) as the better shape if the operator is willing to touch settings.**
The measured run is the argument: seven passes for 9 edges, of which the sixth produced all 9. A single terminal pass would have produced a comparable L1 for one seventh of the analyser time.

*Downstream:* under (b) or (c), `AST-DEC-10`'s baseline must include a terminal-only run, not just inline versus queued.
Under (a), the `supervisor_enabled OFF` cell still needs an answer, because the legacy analyser path has no async entry and §4.6's extraction covers only `run_analyser_chunked`.

---

### DQ6 - What bounds one analyser pass on a large surface? (independent of DQ1-DQ5; the largest unmodelled risk in the design)

**Decision:** what happens when the cumulative surface is two orders of magnitude larger than the measured run.

Context the operator needs: the specification's memory and cost model assumes a maximum surface of 1364 nodes. The largest surface actually in this system is 40,953 nodes - a wildcard-scope run whose subdomain discovery produced 40,805 `Subdomain` nodes. At 100 assets per chunk that is roughly 410 chunks, hence 410 work orders, each of which performs a live L1 inventory read and four checkpoint writes before it can discover it has no Endpoint to judge.

- **(a) Nothing; accept it.** Consequence: on a wildcard run the analyser pass becomes minutes of Postgres and Neo4j traffic before any LLM call, repeated on every cursor, and the memory estimate in §5.1 is unquantified.
- **(b) Filter the read to types some role admits, before chunking.** The Assigner admits `Endpoint` only; `Subdomain` reaches only the unbuilt mechanism-typist. Consequence: on the measured wildcard project this collapses 40,945 assets to 138, i.e. two chunks instead of 410 - but it silently reintroduces the global type filter that `#34` D2/D8 deliberately removed, and would drop those types again the moment the generalist role gains a body.
- **(c) Skip the dispatch before the inventory read.** Move the "nothing admitted for this role" test out of `assign` and into `build_schedule`, so a chunk with no admitted asset for a role produces no work order at all. Consequence: preserves D2/D7 exactly - every type still streams, the admission table still decides - while collapsing the 410 dispatches to the handful that carry Endpoints. Costs one predicate in `build_schedule`.
- **(d) A hard cap on dispatches per pass, with the excess deferred to the next pass.** Consequence: bounds cost, but makes the terminal pass's coverage claim conditional on the cap, which breaks DQ2.

**Recommended: (c).**
It is the only option that bounds the cost without either reversing a ratified decision or weakening the guarantee, and it is a smaller change than any of the others.
(b) is tempting and wrong for the same reason `#34` gave.

*Downstream:* (c) makes a "dispatches per pass scales with admitted assets, not with total surface" assertion writable, which is the missing gate named in §5.
Under (a), the §5.1 memory figure must be re-derived and measured, not estimated, before the flag is turned on for any project.

---

### DQ7 - How is a "settled surface" skip keyed? (depends on DQ2 and DQ6; only meaningful if the cost lever is taken)

**Decision:** what identifies a chunk as "already judged this run".

Context: chunk ids are positional (`stream-<run_id>:<index>`) and the underlying read has no `ORDER BY`, so as the surface grows the window boundaries move and `stream-<run_id>:0` names different assets on every pass while its `dispatch_id` stays identical.

- **(a) Key the skip on `chunk_id` / `dispatch_id`.** Consequence: wrong. After the first pass, index 0 is permanently "judged", and every asset that later shifts into that window is never judged at all. This silently violates DQ1(a) and would be invisible.
- **(b) Key on the content hash of the role-admitted identity set.** Consequence: correct - a window whose admitted identities are unchanged is genuinely re-judgment - and it degrades safely, because any shift makes the hash differ and the chunk is re-judged. Costs a per-run set of hashes, which is bounded and holds no surface.
- **(c) Key on individual admitted identities rather than on chunks.** Skip an Endpoint that has already been judged in this run, and build chunks from the remainder. Consequence: maximal saving, but it changes the prompt context an Endpoint is judged in, and the Assigner's judgment is explicitly context-sensitive (it matches against the live Service inventory and the co-resident surface). This changes the answer, not just the cost.
- **(d) No skip.** Consequence: the drain tail stays as long as the analyser is slow, and DQ5's terminal-only mode becomes the only real cost lever.

**Recommended: (b), with the terminal pass exempt.**
(a) must be named and forbidden in the document, because §3.7's note that dispatch ids repeat reads as a licence to use them.
(c) is the same category of error as a delta-only pass: it saves work by changing what is asked.

*Downstream:* (b) plus the terminal exemption is what preserves DQ1(a) under the cost lever - this is the resolution of the Q10-versus-queue tension, and it holds.
(d) makes DQ5(b) the primary answer to the cost problem.

---

### DQ8 - Who dispatches a targeted-recon request raised by an analyser pass, and what does one raised during the terminal pass do? (depends on DQ2; the retrofit the addendum predicts)

**Decision:** the direction of the dependency once the built-but-unwired reverse seam is turned on.

Context: `request_targeted_recon` exists and is fully tested but has no production caller; the anatomy skill already constructs the request objects and returns them for a caller to dispatch. When it is wired, analysis injects recon jobs into a running recon, and the one-directional dependency this whole design leans on becomes a cycle.

- **(a) The consumer dispatches the request itself.** Consequence: the consumer holds the process-wide pass semaphore while awaiting a live tool run, so a memory guard silently becomes an availability guard, and one project's targeted probe blocks every other project's analysis.
- **(b) The pass returns requests; the pipeline dispatches them at the next job boundary.** Consequence: keeps the dependency one-directional at runtime - analysis proposes, recon disposes - and keeps the semaphore honest. Costs a return channel from the pass to the feed handle, which does not exist yet.
- **(c) Requests raised during a run are recorded and never dispatched in that run.** Consequence: simplest and safest; the request becomes evidence for the next run rather than an action in this one. Loses the whole point of a probe that informs the surface it is probing.

**Recommended: (b), and separately: a request raised during the terminal pass is recorded and not dispatched.**
The second half is the load-bearing part.
A targeted job dispatched after the terminal pass curates new L0 surface that no pass has read, which falsifies the convergence claim by construction rather than by accident - so the terminal pass must be the point after which no new surface can appear.

*Downstream:* (b) requires the `AnalysisFeed` handle to carry a return path, which is a shape decision worth making now even though nothing uses it - retrofitting it later means changing the one seam the whole design rests on.
(a) requires the semaphore's meaning to be re-specified as availability rather than memory, which would reverse §5.1's entire argument.
