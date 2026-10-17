# Ticket: a deliberate recon stop leaves the in-flight job rows `in_progress`

- **Severity:** medium (state hygiene: a stopped run's job rows keep reading as live work).
- **Area:** `src/polymerhus/recon/control/pipeline.py` (cancellation path + `_run_one`), `src/polymerhus/app/clients/pg.py` (job-status vocabulary).
- **Status:** open (a one-time reconcile was applied 2026-10-15; the code gap remains).
- **Filed from:** the arm H run `44e424a2` zombie, operator-reported 2026-10-15.

## Summary

The run-side stop semantics are complete and closed (#287): a deliberate stop settles the RUN row `stopped` promptly, distinguishable from a crash.
The JOB rows are not covered: the phase-setup loop inserts `in_progress` for every job of the phase (`pipeline.py:628`), and a cancellation unwinding mid-phase settles none of them.
The observed zombie sat `in_progress` for over half a day; no code path could ever have settled it.

## Evidence (the arm H zombie)

- Run `44e424a2-7bcc-4452-9d22-c9c335bd7612` (phase 8, job `kiterunner`) was deliberately stopped 2026-10-14 20:40:34.959041+00; the run row reached its `stopped` terminal in the same second.
- `recon_jobs` row `id=203`: `status='in_progress'`, `started_at=20:39:37.436633+00`, `finished_at=NULL`; the only `in_progress` row in the database.
- No live process served it: `docker top` on the agent and kali containers, and the host `ps`, were clean - a DB record only.
- One-time reconcile (2026-10-15): `status='stopped'`, `finished_at` = the run stop instant, a `stats.reconcile` note recording the settlement. After: zero `in_progress` job rows, zero non-terminal recon runs.

## Mechanism

1. The cancellation path (`pipeline.py:831`) settles the RUN row `stopped` and tears the orchestrator down; it never touches `recon_jobs`.
2. `_run_one` (`pipeline.py:638`) settles its job on completion or on `except Exception` (`pipeline.py:652`); `asyncio.CancelledError` derives from `BaseException` (Python 3.8+), so a cancellation propagates without a settle.
3. The job vocabulary has no word for the case: `_TERMINAL_JOB_STATUSES` (`pg.py:29`) is `{success, degraded, failed, skipped}`, and it also decides the `finished_at` expression (`pg.py:447`, `pg.py:486`).
4. The reaper does not reach it: `reap_stale_runs` (`pg.py:597`) only flips RUN rows with `status='running'` and a stale heartbeat to `failed`; it never touches `recon_jobs`, and a stopped run is out of its scope.
5. The jobs settled before the stop are fine (the phase's earlier jobs `success`, `steel_crawl` `degraded`); only the in-flight `kiterunner` row stayed open, so it was the phase's last unsettled job.

## Proposed fix

1. Add `stopped` to the terminal job vocabulary where terminality and `finished_at` are decided (`pg.py:29`, consumed at `pg.py:447` and `pg.py:486`).
2. Settle the run's open job rows at the same chokepoint that settles the run stopped (the pipeline cancellation path): one shared helper issuing `UPDATE recon_jobs SET status='stopped', finished_at=now() WHERE run_id=%s AND status NOT IN <terminal>`.
   This covers both the in-flight job and any not-yet-settled rows of the cancelled phase.
3. Tests: a stop-path test asserts no non-terminal job row survives a cancelled run; a vocabulary test asserts `stopped` is terminal; a reader check renders it on the status-count surfaces.

## Acceptance criteria

- After a deliberate stop, `recon_jobs` holds no `in_progress` row for that run.
- `stopped` renders on every job-status consumer without a whitelist break (`pg.py:412` `get_run_jobs` returns status as free text today).
- No parallel vocabulary is invented; `stopped` reuses the run-level terminal semantics.

See also: #76 (the per-job instant kill + output suppression this row-state half completes), #287 (the run-side `stopped` terminal, closed).
