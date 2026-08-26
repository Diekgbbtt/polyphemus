"""Shared stack-up and fixture helpers for the hunting-wiring assertion
catalogue (`docs/design/hunting-wiring-assertions.md`).

The catalogue drives the hunting-wiring runtime plane under REAL production
conditions against a live agent container (the "target"), with the live
`hunting_runs` Postgres row (the target postgres is already up) and fixtures
seeded through the REAL store APIs (`HuntStore`, `HunterMemoryStore`,
`PodMemoryStore`).

Two targets selectable via `WIRING_TARGET`:
- `sibling` (default): a distinct agent container (`agent-hw`, built FROM THIS
  WORKTREE via `docker-compose.wiring.e2e.yml`, reusing the existing
  `polymerhus-agent:latest` image) attached to the shared network, routing
  every LLM turn through its embedded LiteLLM gateway (`LLM_GATEWAY_URL`).
- `main`: the `agent` service of the MAIN stack (`docker-compose.yml` +
  `docker-compose.dev.yml`, published on 8080) - used when the wiring branch
  is applied in the main worktree and its stack is brought up from there.

Two run modes mirror `tests/e2e/hunting_stack.py`:
- In-network (`docker compose -f docker-compose.yml -f
  docker-compose.dev.yml run --rm tests pytest tests/integration/...`): the
  tests service resolves the target by its network alias
  (`agent-hw` / `agent`) on 8080.
- From the host: the target is published on 8082/8080 (`AGENT_HTTP_URL`
  overrides) and the helper brings it up via the selected compose files.

The store roots are FIXED under `src/polymerhus/attack/hunting/data/`, which
the sibling mounts (`./src:/srv/src`), so fixtures seeded by the test process
through the real store APIs land on the SAME physical files the container
reads - seeding is not doubled, it is the container's own store written by the
caller of the real stores.

Failure policy (per catalogue): live-tier gates skip with a clear reason when
the stack is unreachable (matching the repo's integration/e2e convention), and
FAIL LOUDLY at setup when the stack IS reachable but a seeded fixture's surface
has drifted from the stated quantities (a bad input must fail before the path
runs, never silently substitute).
"""
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Which live target the catalogue drives. Two modes:
# - `sibling` (default): a dedicated `agent-hw` container via the wiring
#   overlay `docker-compose.wiring.e2e.yml`, published on 8082.
# - `main`: the agent service of the MAIN stack (`docker-compose.yml` +
#   `docker-compose.dev.yml`), published on 8080 - used when the wiring branch
#   is applied in the main worktree and its stack is brought up from there.
TARGET = os.environ.get("WIRING_TARGET", "sibling")
if TARGET == "main":
    WIRING_COMPOSE = [
        "docker", "compose", "-f", "docker-compose.yml",
        "-f", "docker-compose.dev.yml",
    ]
    WIRING_SERVICE = "agent"
    DEFAULT_AGENT_HTTP_URL = "http://localhost:8080"
    IN_NETWORK_ALIAS = "agent:8080"
else:
    WIRING_COMPOSE = [
        "docker", "compose", "-f", "docker-compose.wiring.e2e.yml",
    ]
    WIRING_SERVICE = "agent-hw"
    DEFAULT_AGENT_HTTP_URL = "http://localhost:8082"
    IN_NETWORK_ALIAS = "agent-hw:8080"


def agent_http_url() -> str:
    """The base URL of the live target.

    `AGENT_HTTP_URL` wins when set; in-network the tests service resolves the
    target by its network alias (`agent-hw` or `agent`) on 8080; on the host
    the default is the published 8082 (sibling) or 8080 (main)."""
    from os import environ
    if environ.get("NEO4J_URI") == "bolt://neo4j:7687":
        return environ.get("AGENT_HTTP_URL") or IN_NETWORK_ALIAS
    return environ.get("AGENT_HTTP_URL") or DEFAULT_AGENT_HTTP_URL


def _run(cmd: list[str], *, timeout: int = 60, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=cwd or REPO_ROOT, capture_output=True, text=True, timeout=timeout,
    )


# --- sibling / datastore reachability ------------------------------------------


def sibling_up() -> bool:
    """True when the wiring sibling answers `/health`."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{agent_http_url()}/health", timeout=5) as resp:  # noqa: S310
            return resp.status == 200
    except Exception:
        return False


def ensure_sibling_timeout(timeout: int = 240) -> bool | None:
    """Bring up the live target (`WIRING_SERVICE` from `WIRING_COMPOSE`) and
    wait for `/health`.

    True when ready; False when the daemon is unreachable; None when the
    container answered already or came up but not within the deadline."""
    if sibling_up():
        return True
    try:
        _run(WIRING_COMPOSE + ["up", "-d", WIRING_SERVICE], timeout=60)
    except Exception:
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if sibling_up():
            return True
        time.sleep(3)
    return None


def restart_sibling(timeout: int = 300) -> bool:
    """Restart the live target to a clean module state (`up -d --force-recreate`
    on `WIRING_SERVICE`) and wait for `/health`.

    The runtime's `drain` is TERMINAL for a module (no un-drain verb): a gate
    predicate that drains hunting leaves the shared target's module `stopped`,
    which would poison every subsequent launch on that process. Restarting the
    live container is the honest "operator restarts the module" restoration
    (a real spike of availability, acceptable in the integration tier)."""
    try:
        _run(WIRING_COMPOSE + ["up", "-d", "--force-recreate", WIRING_SERVICE], timeout=90)
    except Exception:
        return False
    deadline = time.time() + timeout
    while time.time() < deadline:
        if sibling_up():
            return True
        time.sleep(5)
    return False


def docker_daemon_reachable() -> bool:
    try:
        result = _run(["docker", "images", "--format", "{{.Repository}}"], timeout=10)
        return result.returncode == 0
    except Exception:
        return False


def pg_live_dsn() -> str | None:
    """The live Postgres DSN (the sibling postgres is already up), or None."""
    from tests.conftest import pg_live_dsn as _pg_live_dsn
    return _pg_live_dsn()


# --- skip reasons (mirror tests/e2e/hunting_stack.py) --------------------------


def wiring_stack_skip_reason() -> str | None:
    """Reason the wiring integration tier must skip, or None to run."""
    if not docker_daemon_reachable():
        return ("wiring target unreachable - hunting-wiring assertions blocked "
                "(Docker daemon not running)")
    if not sibling_up():
        return ("wiring target unreachable - hunting-wiring assertions blocked "
                f"({WIRING_SERVICE} not answering at {agent_http_url()})")
    return None


def hunting_pg_skip_reason() -> str | None:
    """Reason the PG-dependent predicates must skip, or None to run."""
    if not docker_daemon_reachable():
        return ("wiring target unreachable - hunting-wiring assertions blocked "
                "(Docker daemon not running - PG walkthrough needs live postgres)")
    if not pg_live_dsn():
        return ("wiring target unreachable - hunting-wiring assertions blocked "
                "(postgres not reachable - hunting_runs walkthrough needs live PG)")
    return None


# --- HTTP driver ----------------------------------------------------------------


def http_client():
    """An `httpx.Client` bound to the live target (the real surface under
    test - never an in-process substitution)."""
    import httpx
    return httpx.Client(base_url=agent_http_url(), timeout=30.0)


def create_project(client, name: str) -> str:
    """Create a project through the live REST surface and return its id."""
    resp = client.post("/projects", json={"name": name})
    assert resp.status_code == 200, f"create project failed: {resp.status_code} {resp.text}"
    return resp.json()["project_id"]


# --- fixture seeding through the REAL store APIs -------------------------------

# The store default roots resolve to `src/polymerhus/attack/hunting/data/`,
# which the sibling mounts (`./src:/srv/src`) - the fixture is the container's
# own store written via its real store APIs, on the caller's side of the mount.


def seed_hunt_config(project_id: str, *, unit_id: str, fault_class: str,
                     vulnerability_class: str, status: str = "ratified",
                     **overrides) -> str:
    """Write ONE hunt config through `HuntStore.write_config` (the real store
    API) into the produced family; returns its semantic `config_key`.

    The seeded body MUST satisfy the real `HuntConfig.model_validate` surface
    (the surfer refuses an unratifiable ratified config and the run wedges on
    the retained produced item - the at-least-once contract), so the required
    `hunt_id` and `prompt_template` slots ship by default, mirroring the
    orchestrator mint."""
    from polymerhus.attack.hunting.hunt_store import HuntStore
    data = {
        "hunt_id": f"{unit_id}::{fault_class}",
        "unit_id": unit_id, "fault_class": fault_class,
        "vulnerability_class": vulnerability_class, "status": status,
        "prompt_template": {
            "rationale": "seeded", "l0_evidence": [], "research_direction": "",
        },
    }
    data.update(overrides)
    store = HuntStore()
    return store.write_config(project_id, data, directory="produced")


def seed_test_spec(project_id: str, *, fault_key: str, fault_keyword: str,
                   strategy_keyword: str, status: str = "specified",
                   **overrides) -> str:
    """Write ONE test-implementation spec through
    `HunterMemoryStore.write_spec` (the real store API) into the produced
    family; returns the spec file stem. `fault_key` is the 3-part config key.

    The seeded body MUST pass the pod's REAL INIT gate
    (`verification.validate_spec`): a `specified` spec with an empty typed base
    is rejected by the pod at INIT with ZERO tool calls and settles within
    seconds - no live pod session is ever observable. The default carries a
    minimal VALID testable surface (a target identity, one verification symptom,
    a testing pattern), so a dispatched pod passes INIT and runs genuine ReAct
    turns, keeping a REAL registered session live across the pause/resume/stop
    observation windows (the per-session verbs act on a real in-flight session,
    never a fabricated one)."""
    from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
    spec = {
        "spec_id": f"{fault_keyword}_{strategy_keyword}",
        "fault_key": fault_key, "status": status,
        "fault": {"fault_id": "f1", "mechanism": "m", "supports": [],
                  "conflicts": [], "test": "t"},
        "strategy": strategy_keyword, "spec_ref": "sr", "experiment_ref": "",
        "target_identity": "Service:slug:a",
        "verification_symptoms": ["the target answers the crafted probe"],
        "testing_pattern": "baseline-refinement",
        "assumptions": [], "payload_vector_space": {},
        "rationale": "seeded", "interpretation_guidance": "seeded",
    }
    spec.update(overrides)
    store = HunterMemoryStore()
    return store.write_spec(
        project_id, fault_key, fault_keyword=fault_keyword,
        strategy_keyword=strategy_keyword, spec=spec, mode="create",
        side="produced",
    ).stem


def seed_experiment_log(project_id: str, *, spec_id: str, order: int = 1,
                        summary: dict | None = None, **slice_fields) -> None:
    """Write ONE experiment-log slice through `PodMemoryStore
    .write_experiment_log` (the real store API) - the T2 (#179) first-class
    slice shape with its terminal `experiment_summary` record."""
    from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
    summary = summary or {
        "verdict": "unsuccessful", "terminal_reason": "space-exhausted",
        "clean": True,
    }
    store = PodMemoryStore(project_id=project_id)
    store.write_experiment_log(spec_id, order, {
        "raw_observations": [], "kb_observations": [], "interpretations": [],
        "executed": True, "experiment_summary": summary, **slice_fields,
    })


def seed_pod_export(project_id: str, *, spec_id: str, run_id: str,
                    envelope: dict | None = None) -> None:
    """Write ONE durable `PodExport` envelope through
    `PodMemoryStore.write_pod_export` (T7/#183) - `<spec_id>/<run_id>.yaml`."""
    from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
    store = PodMemoryStore(project_id=project_id)
    store.write_pod_export(spec_id, run_id, envelope or {
        "verdict": "successful", "terminal_reason": "symptom-confirmed",
        "iterations": 1, "clean": True, "init_validation": [],
        "variant_specs": [], "raw_observations": [], "interpretations": [],
        "error": None,
    })


def seed_parent_note(project_id: str, *, config_key: str, run_id: str,
                     source: str, verdict: dict | None = None) -> None:
    """Write the durable parent-keyed verdict note through
    `HunterMemoryStore.write_note` (the Q16 record the identifier refactor
    writes at pod completion), mirroring `_record_durable_pod_export`."""
    from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
    store = HunterMemoryStore()
    store.write_note(
        project_id, action="append", fault_key=config_key,
        note_name=source, kind="freeform",
        body=str(verdict or {}), evidence="verdict-stub",
        provenance={"run_id": run_id, "source": source},
    )


# --- terminal-quantity read-backs (real store reads, never the code's return) ---


def produced_config_keys(project_id: str) -> list[str]:
    from polymerhus.attack.hunting.hunt_store import HuntStore
    return [k for k, _ in HuntStore().read_produced_configs(project_id)]


def produced_spec_files(project_id: str, fault_key: str) -> list[str]:
    from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
    return HunterMemoryStore().produced_spec_files(project_id, fault_key)


def consumed_spec_files(project_id: str, fault_key: str) -> list[str]:
    """The consumed-side spec file stems under one fault_key, read straight
    from the physical store layout (`test-specs/<fault_key>/consumed/`) - a
    terminal read-back independent of the store's projection code."""
    from polymerhus.attack.hunting.hunter_memory import HunterMemoryStore
    store = HunterMemoryStore()
    root = store._root  # noqa: SLF001 - physical-layout read-back
    side_dir = root / str(project_id) / "test-specs" / str(fault_key) / "consumed"
    if not side_dir.exists():
        return []
    return sorted(child.stem for child in side_dir.glob("*.yaml"))


def pod_export_entries(project_id: str, spec_id: str) -> list[tuple[str, dict]]:
    """The durable pod-export envelope files (`<spec_id>/<run_id>.yaml`)."""
    from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
    store = PodMemoryStore(project_id=project_id)
    out = []
    spec_dir = store._root / str(spec_id)  # noqa: SLF001 - read-back, deliberate
    if not spec_dir.exists():
        return out
    for child in spec_dir.iterdir():
        if child.suffix == ".yaml":
            out.append((child.stem, store.read_pod_export(spec_id, child.stem)))
    return sorted(out)


def hunting_run_rows(project_id: str) -> list[dict]:
    """The live `hunting_runs` rows for a project (real Postgres read)."""
    import psycopg
    dsn = pg_live_dsn()
    if not dsn:
        return []
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT hunting_run_id, status FROM hunting_runs "
                "WHERE project_id = %s ORDER BY hunting_run_id",
                (project_id,),
            )
            return [{"hunting_run_id": r, "status": s} for r, s in cur.fetchall()]


def wait_for_hunting_run_status(project_id: str, run_id: str, *,
                                status: str, timeout: float = 120,
                                interval: float = 2) -> dict:
    """Poll the real `hunting_runs` row until `status` (a critical-ending
    read-back the walkthroughs assert). Raises on timeout with the last row."""
    import psycopg
    deadline = time.time() + timeout
    dsn = pg_live_dsn()
    assert dsn, "live PG required for run-row polling"
    last = None
    while time.time() < deadline:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT hunting_run_id, status FROM hunting_runs "
                    "WHERE hunting_run_id = %s", (run_id,),
                )
                row = cur.fetchone()
        last = {"hunting_run_id": run_id, "status": row[1]} if row else None
        if last and last["status"] == status:
            return last
        time.sleep(interval)
    raise AssertionError(
        f"hunting run {run_id} did not reach {status!r} within {timeout}s "
        f"(last observed: {last})"
    )