"""The live gate for the recon/analysis decoupling (#34): AST-DEC-08/09/10.

These three predicates cannot be proved by construction - they are claims about a
REAL run against a REAL target, and each one is a different way the decoupling
could be wrong:

- AST-DEC-08  convergence survived (a further pass adds nothing);
- AST-DEC-09  the stall is gone (nothing waits on the analyser);
- AST-DEC-10  it was not bought by doing less analysis.

WHERE THE EVIDENCE COMES FROM, AND WHY NOT LANGFUSE. The originally proposed
observable for AST-DEC-09 was a delta between Langfuse trace timestamps. That was
assessed and rejected as the GATE (design doc §12): tracing is optional and
fail-open (`get_langfuse_callbacks()` returns `[]` on any missing env var, missing
package, or handler failure, and tells no caller), and the exporter drops whole
span batches on a read timeout - i.e. exactly under the latency stress a stall
creates. A gate reading traces would therefore go quiet in precisely the failing
case, which is the vacuous-gate trap. Langfuse correlation metadata was added
anyway (`job_agent.pod_trace_metadata`, and the analyser's session id now keys off
the bare recon run) so a human can ORIENT on one timeline - but the pass/fail
predicate is decided from Postgres and Neo4j, which are written synchronously by
the code under test.

Run mechanics: these read the artifacts of a completed live run rather than
driving one, because a real recon run takes tens of minutes and needs a target.
Point them at a run with RECON_RUN_ID; they skip otherwise, and the non-vacuity
guards below fail rather than skip when the run is present but uninformative.
"""
import os
from datetime import datetime

import pytest

from polymerhus.app.clients import neo4j_client, pg

RUN_ID = os.environ.get("RECON_RUN_ID")
# The ceiling for a dead gap between two recon jobs. Generous by design: this is
# not a performance budget, it is a STALL detector. On the inline run 64f2ccb8 the
# two worst gaps were 1190 s and 242 s, so 60 s separates "the analyser is on the
# critical path" from "it is not" without any tuning against machine speed.
ANALYSIS_MAX_JOB_GAP_S = float(os.environ.get("ANALYSIS_MAX_JOB_GAP_S", "60"))

pytestmark = pytest.mark.skipif(
    not RUN_ID, reason="set RECON_RUN_ID to a completed decoupled run to gate it"
)


def _parse(ts):
    return datetime.fromisoformat(ts) if isinstance(ts, str) else ts


@pytest.fixture(scope="module")
def run():
    row = pg.get_run(RUN_ID)
    assert row, f"no recon_runs row for {RUN_ID}"
    return row


@pytest.fixture(scope="module")
def jobs():
    return pg.get_run_jobs(RUN_ID)


@pytest.fixture(scope="module")
def feed_stats(run):
    stats = (run.get("stats") or {})
    assert stats, (
        "recon_runs.stats is empty: either this run predates #34 or the feed never "
        "wrote its stats - in both cases the gate has nothing to judge"
    )
    return stats


# --- AST-DEC-09: the stall is gone -------------------------------------------

def test_AST_DEC_09_the_analyser_never_blocked_the_recon_job_loop(feed_stats):
    """The direct predicate, measured at the seam the decoupling changed.

    `advance_blocked_s_max` is the longest any single `feed.advance` held the recon
    job loop. Under the inline feed it IS the analyser pass duration (up to 1157 s
    on run 64f2ccb8); under the queued feed it is an enqueue and must be ~0."""
    assert feed_stats.get("mode") == "queued", (
        "this gate judges a DECOUPLED run; set settings.recon.async_analysis_consumer"
    )
    # Non-vacuity: analysis must actually have happened, and have taken real time.
    # Without this the predicate below passes trivially on a run with no analysis.
    assert feed_stats.get("passes", 0) >= 2, "fewer than 2 passes: nothing to stall on"
    assert feed_stats.get("pass_seconds_max", 0) > 1.0, (
        "no pass took over a second - this run cannot demonstrate anything about "
        "keeping a slow analyser off the critical path"
    )

    assert feed_stats["advance_blocked_s_max"] < 1.0, (
        f"a recon job waited {feed_stats['advance_blocked_s_max']:.1f}s on the "
        f"analyser; the queued feed must never block its caller"
    )


def test_AST_DEC_09b_no_dead_gap_between_consecutive_recon_jobs(jobs):
    """The independent, outside-in check on the same claim: recon's own timeline
    should have no holes.

    Computed from `stats.exec_started_at` / `stats.exec_finished_at`, NOT from the
    `started_at` column - `upsert_job` stamps that on INSERT and never updates it
    ON CONFLICT, and the pipeline inserts an `in_progress` row for every job of a
    phase during phase setup, so the column times phase setup rather than the job.
    That defect is why the assertion as originally specified was unwritable."""
    windows = sorted(
        (
            (_parse(j["stats"]["exec_started_at"]), _parse(j["stats"]["exec_finished_at"]), j["job"])
            for j in jobs
            if (j.get("stats") or {}).get("exec_started_at")
            and j["stats"].get("exec_finished_at")
        ),
        key=lambda w: w[0],
    )
    assert len(windows) >= 3, (
        f"only {len(windows)} jobs carry an execution window; a gap series needs at "
        f"least 3 (a run this short proves nothing about stalling)"
    )

    gaps = [
        ((nxt[0] - prev[1]).total_seconds(), prev[2], nxt[2])
        for prev, nxt in zip(windows, windows[1:])
    ]
    worst = max(gaps, key=lambda g: g[0])
    assert worst[0] < ANALYSIS_MAX_JOB_GAP_S, (
        f"dead gap of {worst[0]:.0f}s between {worst[1]} and {worst[2]} "
        f"(limit {ANALYSIS_MAX_JOB_GAP_S}s) - something is still on recon's path"
    )


# --- AST-DEC-08: convergence survived ----------------------------------------

def _l1_counts(project_id):
    """The four identity counts AST-DEC-08 compares, each counted INDEPENDENTLY.

    Chained MATCH clauses would be wrong here: one empty label (this scope writes
    no Systems or DataItems - #34 D4) drops the whole row, and every count would
    read zero. A count subquery per label cannot collapse that way."""
    rows = neo4j_client.read(
        "RETURN COUNT { MATCH (s:L1Service) WHERE s.project_id = $p } AS services, "
        "COUNT { MATCH (y:L1System) WHERE y.project_id = $p } AS systems, "
        "COUNT { MATCH (d:L1DataItem) WHERE d.project_id = $p } AS items, "
        "COUNT { MATCH (:L1Service)-[r:AGGREGATES]->(e) WHERE e.project_id = $p } "
        "AS aggregates",
        {"p": project_id},
    )
    r = rows[0]
    return (r["services"], r["systems"], r["items"], r["aggregates"])


def test_AST_DEC_08_a_further_pass_over_the_settled_surface_adds_nothing(run, feed_stats):
    """The L1D-23 gate. A decoupled run that converged must be a FIXED POINT: one
    more pass over the same surface writes no new identity and no new edge.

    The convergence pass MUST reuse the run's own `stream-<run_id>` analyser id.
    A batch id re-MERGEs every edge and overwrites `prov_job` - the NM-7 clobber -
    which would destroy the provenance this same test then checks."""
    import asyncio

    from polymerhus.analysis.supervisor import analyse_chunked

    assert feed_stats.get("analysis_drained") is True, (
        "the run made no convergence claim; there is no fixed point to check"
    )
    project_id = run["project_id"]
    before = _l1_counts(project_id)
    assert before[3] > 0, "no AGGREGATES were written - nothing converged"

    result = asyncio.run(analyse_chunked(project_id, f"stream-{RUN_ID}", terminal=True))
    # Non-vacuity: the convergence pass must have READ the surface. A pass that
    # degraded to nothing would also "add nothing", for the wrong reason.
    assert result.census.l0_assets_read > 0
    assert result.census.dispatches_entered > 0

    assert _l1_counts(project_id) == before

    orphans = neo4j_client.read(
        "MATCH (:L1Service)-[r:AGGREGATES]->(e) WHERE e.project_id = $p "
        "AND NOT r.prov_job STARTS WITH 'analyser:stream-' RETURN count(r) AS n",
        {"p": project_id},
    )
    assert orphans[0]["n"] == 0, "an AGGREGATES edge lost its streaming provenance"


# --- AST-DEC-10: coverage did not regress ------------------------------------

def test_AST_DEC_10_coverage_is_recorded_against_the_inline_baseline(run, feed_stats):
    """Comparative, never a threshold: the analyser is non-deterministic (AMV-9,
    and the 143-vs-11 assignment variance NM-7 recorded), so a single run cannot
    pass or fail this. What this test enforces is that the comparison is POSSIBLE -
    the numbers needed to make it are recorded - and it fails loudly on the one
    unambiguous regression: a decoupled run that wrote nothing at all.

    Set ANALYSIS_INLINE_BASELINE_AGGREGATES to the inline run's count over the same
    target and seed to turn this into the real comparison."""
    project_id = run["project_id"]
    _, _, _, aggregates = _l1_counts(project_id)

    assert aggregates > 0, (
        "the decoupled run wrote ZERO AGGREGATES; speed bought by writing nothing "
        "is the failure mode AST-DEC-10 exists to catch"
    )
    assert feed_stats.get("l0_assets_read", 0) > 0
    assert feed_stats.get("dispatches_entered", 0) > 0

    baseline = os.environ.get("ANALYSIS_INLINE_BASELINE_AGGREGATES")
    if baseline:
        assert aggregates >= int(baseline), (
            f"decoupled run wrote {aggregates} AGGREGATES against an inline baseline "
            f"of {baseline}: judge over repeated runs before accepting, but a "
            f"persistent shortfall means the decoupling is dropping judgments"
        )
