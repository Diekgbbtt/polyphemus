"""Comparative evaluation of an analysis agent's CONFIGURATION.

The analysis agents are LLM proposers whose output varies run to run - the
Bootstrapper produced 16 and 21 Services from an identical KB on consecutive
runs. That variance makes single-run judgments worthless and heuristic pass bars
actively misleading: a bar wide enough to absorb the variance cannot detect a
regression, and one tight enough to detect a regression fires on healthy runs.
A prompt change once collapsed Service breadth 25/16/20 -> 13 and stayed green in
every unit test (commit `760e93d`), which is the failure this module exists for.

So evaluation here is **comparative by construction** (operator ruling
2026-07-27): arms are ranked against each other over repeated runs, and NOTHING
in this module encodes a target count or a pass threshold. `compare()` returns
per-arm distributions and the reader draws the conclusion.

**Breadth is the primary axis; granularity is NOT.** Granularity ("is this
Service too coarse?") has no measure this codebase trusts, so it is carried as a
qualitative observation next to the numbers, never as a score. The one hard rule
is that breadth is never read alone: `INTEGRITY_KEYS` travel with it because an
arm can buy Service count by losing something else. That is not hypothetical -
the `breadth_verbatim` arm matched the best breadth mean while silently dropping
an AuthorizationSystem's entire role vocabulary in one run of three, and a
count-only metric would have ranked it a winner.

GENERALITY. The core (`run_matrix` / `compare`) is agent-agnostic: it takes an
`invoke_fn` (run the agent once, under a named config, and return the project it
wrote) and a `read_fn` (read that project's L1 skeleton back). The Bootstrapper is
the first adopter via `bootstrap_via_api` + `read_skeleton`; another analysis
proposer adopts it by supplying its own pair, and may extend `skeleton_metrics`
with metrics for the slice of L1 it owns.

RUNTIME FIDELITY. The supplied Bootstrapper adapter drives the REAL system end to
end - `POST /projects` -> `PUT settings` -> `POST bootstrap` -> the agent -> the
sole-writer -> Neo4j - rather than calling the agent in-process. An in-process
harness cannot catch a defect in the entry path, and the entry path is exactly
where one was found (`run_bootstrap` still delegating to a retired code path).

PERSISTENCE. Every evaluated project is LEFT IN THE GRAPH. Wiping is start-only,
never on teardown: a teardown wipe deletes the artifact the operator needs to
inspect, which is precisely why earlier skeletons could not be reviewed.
"""
from __future__ import annotations

import json
import logging
import os
import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable, Sequence

logger = logging.getLogger(__name__)

# Run the agent once under a named config; return the project_id it wrote into.
InvokeFn = Callable[[str, str], str]
# Read a project's L1 skeleton back as {services, systems, service_system_edges}.
ReadFn = Callable[[str], dict]

# Metrics that MUST be reported alongside breadth. An arm that wins on Service
# count while degrading any of these has not won - it has moved the cost somewhere
# the primary axis cannot see (observed live, see the module docstring).
INTEGRITY_KEYS = ("contract_coverage", "n_systems", "service_system_edges", "n_roles")


@dataclass(frozen=True)
class EvalOutcome:
    """One (config, repeat) cell: what the agent produced, and where it persists."""

    config: str
    repeat: int
    project_id: str
    elapsed_s: float
    metrics: dict = field(default_factory=dict)
    error: str | None = None


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------
_BUYING_HINTS = ("checkout", "basket", "cart", "payment", "order", "shop", "deliver")


def skeleton_metrics(skeleton: dict, *, journey_hints: Sequence[str] = _BUYING_HINTS) -> dict:
    """Measure one produced L1 skeleton.

    `n_services` is the PRIMARY (comparative) axis. The `INTEGRITY_KEYS` ride
    alongside it so a breadth win that cost something else is visible in the same
    row. `granularity_note` is QUALITATIVE - deliberately not folded into any score,
    because we have no principled measure of whether a Service is too coarse; it
    reports how many Services cover one narrated journey, which is the shape a
    human can judge at a glance.
    """
    services = skeleton.get("services") or []
    systems = skeleton.get("systems") or []
    contracts = [(s.get("service_contract") or s.get("contract") or "").strip() for s in services]
    slugs = [s.get("business_function_slug") or s.get("slug") for s in services]
    authz = next((s for s in systems if s.get("kind") == "AuthorizationSystem"), None)
    covering = sorted(s for s in slugs if s and any(h in s.lower() for h in journey_hints))
    return {
        "n_services": len(services),
        # --- integrity, never traded away for breadth ---
        "contract_coverage": round(sum(bool(c) for c in contracts) / max(len(contracts), 1), 3),
        "n_systems": len(systems),
        "service_system_edges": skeleton.get("service_system_edges", 0),
        "n_roles": len(authz.get("roles") or []) if authz else 0,
        # --- descriptive ---
        "distinct_contracts": len({c for c in contracts if c}),
        "exposure_set": sorted({s.get("exposure") for s in services if s.get("exposure")}),
        "slugs": sorted(s for s in slugs if s),
        # --- QUALITATIVE granularity observation (never scored) ---
        "granularity_note": {
            "journey_covering_services": covering,
            "journey_split": len(covering),
            "mean_contract_chars": round(
                statistics.mean([len(c) for c in contracts if c] or [0]), 1),
        },
    }


# --------------------------------------------------------------------------
# The matrix
# --------------------------------------------------------------------------
def run_matrix(
    configs: Iterable[str],
    *,
    invoke_fn: InvokeFn,
    read_fn: ReadFn,
    repeats: int = 3,
    on_outcome: Callable[[EvalOutcome], None] | None = None,
) -> list[EvalOutcome]:
    """Run every config `repeats` times and measure each result.

    Repeats are what make the comparison meaningful - a single run of a
    non-deterministic agent says almost nothing. Fail-open per cell: one failed
    run is recorded with its error and the matrix continues, because losing an
    hour of completed arms to one provider blip would be its own defect.
    """
    outcomes: list[EvalOutcome] = []
    for config in configs:
        for repeat in range(1, repeats + 1):
            started = time.time()
            try:
                project_id = invoke_fn(config, f"{config}-r{repeat}")
                metrics = skeleton_metrics(read_fn(project_id))
                outcome = EvalOutcome(config, repeat, project_id,
                                      round(time.time() - started, 1), metrics)
            except Exception as exc:  # one bad cell must not lose the whole matrix
                logger.warning("eval cell %s r%d failed", config, repeat, exc_info=True)
                outcome = EvalOutcome(config, repeat, "", round(time.time() - started, 1),
                                      error=str(exc))
            outcomes.append(outcome)
            if on_outcome:
                on_outcome(outcome)
    return outcomes


def compare(outcomes: Sequence[EvalOutcome]) -> dict:
    """Aggregate per config. Returns distributions, NOT a verdict.

    There is deliberately no "winner" field and no threshold anywhere: the ranking
    is the reader's to make, with the integrity columns in view. `min` matters as
    much as `mean` - an arm with a high mean and a low floor is less trustworthy
    than a tighter one, and the mean alone hides that.
    """
    by: dict[str, list[EvalOutcome]] = {}
    for o in outcomes:
        by.setdefault(o.config, []).append(o)

    summary = {}
    for config, cells in by.items():
        ok = [c for c in cells if c.error is None]
        if not ok:
            summary[config] = {"n": 0, "failed": len(cells)}
            continue
        breadth = [c.metrics["n_services"] for c in ok]
        summary[config] = {
            "n": len(ok),
            "failed": len(cells) - len(ok),
            "breadth": {
                "values": breadth,
                "mean": round(statistics.mean(breadth), 1),
                "min": min(breadth),
                "max": max(breadth),
                # the floor matters: a high mean with a low floor is not a win
                "stdev": round(statistics.stdev(breadth), 1) if len(breadth) > 1 else 0.0,
            },
            "integrity": {
                k: sorted({c.metrics.get(k) for c in ok}) for k in INTEGRITY_KEYS
            },
            "granularity_note": [c.metrics["granularity_note"]["journey_split"] for c in ok],
            "mean_seconds": round(statistics.mean([c.elapsed_s for c in ok])),
            "projects": [c.project_id for c in ok],
        }
    return summary


def format_comparison(summary: dict) -> str:
    """Render `compare()` as the table a human reads. Integrity is shown as the SET
    of observed values per arm, so a single degraded run (e.g. roles {0, 11}) is
    visible instead of being averaged into invisibility."""
    lines = [
        f"{'config':<18} {'n':>2} {'breadth':<16} {'mean':>5} {'min':>4} {'sd':>4}  "
        f"{'journey-split':<14} {'secs':>5}  integrity",
    ]
    for config, s in summary.items():
        if not s.get("n"):
            lines.append(f"{config:<18}  0  (all runs failed)")
            continue
        b = s["breadth"]
        integ = " ".join(f"{k}={v}" for k, v in s["integrity"].items())
        lines.append(
            f"{config:<18} {s['n']:>2} {str(b['values']):<16} {b['mean']:>5} {b['min']:>4} "
            f"{b['stdev']:>4}  {str(s['granularity_note']):<14} {s['mean_seconds']:>5}  {integ}"
        )
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Bootstrapper adapter - the first adopter (agent-specific; others add their own)
# --------------------------------------------------------------------------
def read_skeleton(project_id: str, *, read_fn=None) -> dict:
    """Read a project's L1 skeleton back. Uses the analysis context's own reader, so
    the eval sees exactly the graph the agent wrote."""
    if read_fn is None:
        from polymerhus.app.clients import neo4j_client

        read_fn = neo4j_client.read
    services = read_fn(
        "MATCH (n:L1Service) WHERE n.project_id = $p RETURN n.business_function_slug AS slug, "
        "n.exposure AS exposure, n.service_contract AS service_contract ORDER BY slug",
        {"p": project_id},
    )
    systems = read_fn(
        "MATCH (n:L1System) WHERE n.project_id = $p RETURN n.kind AS kind, "
        "n.discriminator AS discriminator, n.roles AS roles, n.realms AS realms ORDER BY kind",
        {"p": project_id},
    )
    edges = read_fn(
        "MATCH (:L1Service)-[r]->(s:L1System) WHERE s.project_id = $p RETURN count(r) AS n",
        {"p": project_id},
    )
    return {
        "services": [dict(s) for s in services],
        "systems": [dict(s) for s in systems],
        "service_system_edges": (edges[0]["n"] if edges else 0),
    }


def bootstrap_via_api(operator_kb: str, name: str, *, api: str | None = None,
                      timeout: float = 1800.0) -> str:
    """Run ONE bootstrap through the whole live system and return its project_id.

    The faithful entry path, deliberately: `POST /projects` -> `PUT settings` ->
    `POST /projects/{id}/bootstrap`. Calling `bootstrap_reasoned` in-process would
    be faster and would not exercise the API, the use-case layer, or the settings
    round-trip - the seams where an entry-path defect actually lives.
    """
    import httpx

    api = api or os.environ.get("POLYMERHUS_API", "http://localhost:8080")
    with httpx.Client(base_url=api, timeout=timeout) as c:
        project_id = c.post("/projects", json={"name": name}).json()["project_id"]
        c.put(f"/projects/{project_id}/settings",
              json={"recon": {"operator_kb": operator_kb}}).raise_for_status()
        r = c.post(f"/projects/{project_id}/bootstrap", json={})
        if r.status_code != 200:
            raise RuntimeError(f"bootstrap HTTP {r.status_code}: {r.text[:300]}")
    return project_id


def evaluate_bootstrapper(
    operator_kb: str, configs: Sequence[str], *, repeats: int = 3, tag: str = "eval",
    api: str | None = None, results_path: str | None = None,
) -> dict:
    """Run the config matrix for the Bootstrapper and return the comparison.

    NOTE: the caller is responsible for setting `BOOTSTRAP_PROMPT_CONFIG` on the
    RUNNING AGENT for each arm - uvicorn's `--reload` does not re-read the
    environment, so an arm switch needs a container recreate. `tools/` scripting
    does that; this function measures whatever the agent is currently configured
    to do and labels it with the config name it was told.
    """
    def invoke(config: str, run_name: str) -> str:
        return bootstrap_via_api(operator_kb, f"{tag}-{run_name}", api=api)

    def record(o: EvalOutcome) -> None:
        logger.info("eval %s r%d -> project=%s services=%s %.0fs",
                    o.config, o.repeat, o.project_id or "-",
                    (o.metrics or {}).get("n_services", "-"), o.elapsed_s)
        if results_path:
            with open(results_path, "a") as fh:
                fh.write(json.dumps(asdict(o)) + "\n")

    outcomes = run_matrix(configs, invoke_fn=invoke, read_fn=read_skeleton,
                          repeats=repeats, on_outcome=record)
    return compare(outcomes)
