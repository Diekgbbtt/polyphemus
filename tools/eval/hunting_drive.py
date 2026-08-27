#!/usr/bin/env python3
"""hunting_drive.py - drive the hunting stretch over the API's hunting control surface.

Host-side REST-client driver. It does NOT reach the LLM gateway, boot the
runtime, or run in the container: the whole-pipeline launch (`POST /hunting`)
schedules the run onto the agent's OWN control plane, where the gateway is
native. The driver only:

  - builds the REDUCED, RISK-DESCENDING candidate batch (top-N selection-tier
    faults from the fault-KB, each bound to its top-M richest units) as the
    wire `_HuntingCandidateIn` shape;
  - launches the whole pipeline and monitors it through the API;
  - stops the run at a ratified-config threshold OR on a stall watchdog (no new
    elements across hunt configs / TestImplementationSpecs / experiment logs /
    PodExports for a window);
  - bundles the persisted artifacts.

Subcommands:

  run   <project_id> <target>            launch + monitor the whole pipeline
        [--top-faults 25] [--top-units 3] [--stop-after 40] [--poll-s 30]
        [--stall-min 10]
  probe <project_id>                      exercise EVERY hunting control endpoint
        (whole-pipeline is NOT launched; component/session/module verbs are
        hit and their responses recorded - non-destructive, immediate restore)

Env:
  PH_API            the polymerhus API base (default http://localhost:8080)
  RUNS_ROOT         the bundle root (default <repo>/tools/eval/runs)
  HUNT_DATA_ROOT    the hunt store root the agent writes (default
                    /Users/diekgbbtt/polymerhus/src/polymerhus/attack/hunting/data)
  NEO4J_URI         for the batch builder's graph richness read

The batch builder imports the platform's fault-KB / fault_risk / graph modules,
so run it with the MAIN checkout on the path: `PYTHONPATH=src` (the repo whose
src the agent mounts) and the .env sourced.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
)
logger = logging.getLogger("hunting_drive")

HERE = Path(__file__).resolve().parent
RUNS_ROOT = Path(os.environ.get("RUNS_ROOT") or (HERE / "runs"))
PH_API = os.environ.get("PH_API", "http://localhost:8080").rstrip("/")

# The hunt store lives in the AGENT CONTAINER's filesystem: since the lightrag
# refactor (commit 1f88552) the agent runs a baked image, NOT a live mount of
# the repo - so the produced-artifacts surface is read through docker exec, and
# the REST API remains the only host-side control surface.
AGENT_CONTAINER = os.environ.get("AGENT_CONTAINER", "polymerhus-agent-1")
IN_DATA = "/srv/src/polymerhus/attack/hunting/data"


def _container(cmd: str) -> str:
    """Run a read-only command inside the agent container; empty on failure."""
    import subprocess
    try:
        out = subprocess.run(
            ["docker", "exec", AGENT_CONTAINER, "sh", "-c", cmd],
            capture_output=True, text=True, timeout=120,
        )
        return out.stdout
    except Exception as exc:  # noqa: BLE001 - fail-open read
        logger.warning("container read failed (%s): %s", cmd[:60], exc)
        return ""


# --- API client ----------------------------------------------------------------

def _api(method, path, body=None):
    url = f"{PH_API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            detail = json.loads(raw)
        except Exception:  # noqa: BLE001
            detail = raw.decode(errors="replace")[:300]
        return exc.code, detail


def _hunting_status(project_id, run_id):
    code, body = _api("GET", f"/projects/{project_id}/hunting/{run_id}")
    return body if code == 200 else {"status": f"http:{code}"}


# --- candidate batch -----------------------------------------------------------

def _load_entries():
    from polymerhus.attack.hunting.fault_kb import load_fault_entries
    return list(load_fault_entries())


def _risk_sorted_fault_ids(entries, top):
    from polymerhus.attack.hunting.fault_risk import sort_risk_desc
    ids = sort_risk_desc([e.fault_id for e in entries])
    logger.info("selection tier: %d entries; taking top-%d risk-descending: %s",
                len(entries), top, ids[:top])
    return ids[:top]


def _unit_richness(project_id):
    from polymerhus.attack.hunting.hunt_orchestrator import ReadOnlyGraphView
    view = ReadOnlyGraphView(project_id)
    cards = view.index_cards()
    richness: dict[str, int] = {}
    for card in cards:
        kind = card.get("kind")
        key = card.get("key") or {}
        if kind == "Service":
            slug = key.get("business_function_slug")
            if not slug:
                continue
            unit_id = f"Service:{slug}"
        elif kind == "System":
            disc = key.get("discriminator") or card.get("label")
            if not disc:
                continue
            unit_id = f"{kind}:{disc}"
        else:
            continue
        deg = card.get("edge_degree") or {}
        richness[unit_id] = sum(int(v or 0) for v in deg.values())
    return richness


def build_batch(project_id, top_faults, top_units):
    """The wire `_HuntingCandidateIn` batch: risk-descending faults x richest units."""
    entries = _load_entries()
    fault_ids = _risk_sorted_fault_ids(entries, top_faults)
    rich = sorted(_unit_richness(project_id).items(), key=lambda kv: (-kv[1], kv[0]))
    units = [uid for uid, _n in rich[:top_units]]
    logger.info("richest units for the batch: %s", units)
    if not units:
        raise SystemExit("no L1 units found; scaffold the project first")
    return [
        {
            "unit_id": uid,
            "fault_class": fid,
            "verdict": "applies",
            # The intake's O10 gate drops a candidate with no llm witness
            # (`witnesses.llm is None`), so the deterministic harness batch
            # supplies the witness text on BOTH slots.
            "deterministic_witness": f"harness reduced batch: {uid}::{fid}",
            "llm_witness": f"harness reduced batch (deterministic; no LLM match): {uid}::{fid}",
        }
        for fid in fault_ids
        for uid in units
    ]


# --- surface fingerprint (stall watchdog) --------------------------------------

def _surface_scan(project_id):
    """Every produced-artifact path+size across the four families, read from
    the agent container (configs, TestImplementationSpecs, experiment logs,
    PodExports). Returns a list of 'relpath size' lines."""
    cfg = f"{IN_DATA}/{project_id}/orchestration/hunt_configs"
    spec = f"{IN_DATA}/hunting/{project_id}/test-specs"
    pod = f"{IN_DATA}/{project_id}/test-executor-pod"
    return _container(
        f"for d in '{cfg}/produced' '{cfg}/consumed' '{spec}' '{pod}'; do "
        f"[ -d \"$d\" ] && find \"$d\" -name '*.yaml' -exec stat -c '%n %s' {{}} +; "
        f"done 2>/dev/null | sed -e 's#{IN_DATA}/{project_id}/##' | sort"
    ).strip()


def surface_fingerprint(project_id):
    """A stable tuple of (relpath, size) - changes when any element is added or
    modified across configs / specs / experiment logs / PodExports."""
    return tuple(_surface_scan(project_id).splitlines())


def ratified_count(project_id):
    """Ratified hunt configs currently in produced/ (the stop gate)."""
    out = _container(
        f"grep -l '^status: ratified' {IN_DATA}/{project_id}/orchestration/"
        f"hunt_configs/produced/*.yaml 2>/dev/null | wc -l"
    ).strip()
    return int(out) if out.isdigit() else 0


# --- run -----------------------------------------------------------------------

async def run(project_id, target, top_faults, top_units, stop_after, poll_s, stall_min):
    run_dir = RUNS_ROOT / target / "attempt-hunting"
    run_dir.mkdir(parents=True, exist_ok=True)

    batch = build_batch(project_id, top_faults, top_units)
    logger.info("candidate batch: %d (unit,fault) pairs", len(batch))

    code, resp = _api("POST", f"/projects/{project_id}/hunting", {"candidates": batch})
    if code != 201 or "hunting_run_id" not in resp:
        logger.error("launch failed (%s): %s", code, resp)
        raise SystemExit(1)
    run_id = resp["hunting_run_id"]
    logger.info("hunting run launched: %s", run_id)

    stopped = False
    watchdog_fired = False
    last_fp = surface_fingerprint(project_id)
    last_change = time.time()

    while True:
        row = _hunting_status(project_id, run_id)
        status = row.get("status")
        ratified = ratified_count(project_id)

        if not stopped and ratified >= stop_after:
            logger.info("ratified config count %d >= stop threshold %d; stopping",
                        ratified, stop_after)
            _api("POST", f"/projects/{project_id}/hunting/{run_id}/stop")
            stopped = True

        fp = surface_fingerprint(project_id)
        if fp != last_fp:
            last_fp = fp
            last_change = time.time()
        elif (status not in ("complete", "failed", "stopped", "interrupted")
              and not watchdog_fired
              and (time.time() - last_change) >= stall_min * 60):
            logger.warning("STALL WATCHDOG: no new surface elements for %d min "
                           "(configs/specs/experiment-logs/exports frozen); stopping",
                           stall_min)
            _api("POST", f"/projects/{project_id}/hunting/{run_id}/stop")
            watchdog_fired = True
            stopped = True

        if stopped or status in ("complete", "failed", "stopped", "interrupted"):
            logger.info("hunting run %s terminal: status=%s ratified=%d "
                        "(watchdog=%s)", run_id, status, ratified, watchdog_fired)
            break
        await asyncio.sleep(poll_s)

    bundle(run_dir, project_id, target, run_id, batch, stop_after, stopped, watchdog_fired)
    return run_id


def _container_cp(src_dir_in: str, local_dir: Path) -> bool:
    """Copy one hunt-data subtree out of the container; True on success (a
    missing source is a benign no-op - fail-open)."""
    import subprocess
    if _container(f"[ -d '{src_dir_in}' ] && echo yes").strip() != "yes":
        return True
    local_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["docker", "cp", f"{AGENT_CONTAINER}:{src_dir_in}/.", str(local_dir)],
            capture_output=True, timeout=180, check=True,
        )
        return True
    except Exception as exc:  # noqa: BLE001 - fail-open copy
        logger.warning("docker cp of %s failed: %s", src_dir_in, exc)
        return False


def bundle(run_dir, project_id, target, run_id, batch, stop_after, stopped, watchdog_fired):
    proj = f"{IN_DATA}/{project_id}"
    (run_dir / "configs").mkdir(exist_ok=True)
    (run_dir / "specs").mkdir(exist_ok=True)
    (run_dir / "pods").mkdir(exist_ok=True)
    _container_cp(f"{proj}/orchestration/hunt_configs", run_dir / "configs")
    _container_cp(f"{IN_DATA}/hunting/{project_id}/test-specs", run_dir / "specs")
    _container_cp(f"{proj}/test-executor-pod", run_dir / "pods")

    # The PodExport per the pod-memory spec (T7/#183): <spec_id>/<run_id>.yaml
    # - a SINGLE filename segment at the spec-dir root (NOT variants/ or
    # experiment-log/). Rename the copied export files for readability.
    pod_dir = run_dir / "pods"
    for e in sorted(pod_dir.glob("*/*.yaml")):
        if e.parent.name not in ("variants", "experiment-log"):
            e.rename(pod_dir / f"{e.parent.name}__{e.name}")

    manifest = {
        "target": target,
        "project_id": project_id,
        "hunting_run_id": run_id,
        "orchestrator_stopped_at_ratified": stopped,
        "stall_watchdog_fired": watchdog_fired,
        "candidates_delivered": len(batch),
        "faults_batch": sorted({c["fault_class"] for c in batch}),
        "units_batch": sorted({c["unit_id"] for c in batch}),
        "stop_after": stop_after,
        "run_status": _hunting_status(project_id, run_id).get("status"),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    logger.info("bundled into %s", run_dir)


# --- control-surface probe -----------------------------------------------------

def probe(project_id):
    """Exercise every hunting control endpoint and record the responses. The
    whole-pipeline launch is NOT run; component/session/module verbs are hit
    and their responses recorded (non-destructive, immediate restore). The
    probe runs against a SCRATCH project so no artifact pollutes a real one."""
    import subprocess
    code, proj = _api("POST", "/projects", {"name": f"probe-scratch-{int(time.time())}"})
    if code not in (200, 201) or "project_id" not in proj:
        logger.error("scratch project create failed (%s): %s", code, proj)
        raise SystemExit(1)
    scratch = proj["project_id"]
    logger.info("probe scratch project: %s", scratch)
    out: dict[str, dict] = {}
    run_id = "probe"

    def hit(label, method, path, body=None):
        c, body2 = _api(method, path, body)
        out[label] = {"status": c, "response": body2}
        logger.info("%-46s -> %s", label, c)

    hit("whole-pipeline launch (empty pass)", "POST", f"/projects/{scratch}/hunting",
        {"candidates": []})
    hit("orchestrator-only", "POST", f"/projects/{scratch}/hunting/orchestrator",
        {"candidates": []})
    hit("hunt-only enqueue", "POST", f"/projects/{scratch}/hunting/hunt",
        {"unit_id": "Service:__probe__", "fault_class": "CWE-000",
         "vulnerability_class": "Probe"})
    hit("hunt-only enqueue (409 at-most-once replay)",
        "POST", f"/projects/{scratch}/hunting/hunt",
        {"unit_id": "Service:__probe__", "fault_class": "CWE-000",
         "vulnerability_class": "Probe"})
    hit("pod-only resume (404 fail-closed path)",
        "POST", f"/projects/{scratch}/hunting/pod",
        {"session_id": f"hunting:probe:pod:probe:probe"})
    hit("session stop (404 path)",
        "POST", f"/projects/{scratch}/hunting/{run_id}/sessions/nope/stop")
    hit("module pause", "POST", f"/projects/{scratch}/modules/hunting/pause")
    hit("module resume", "POST", f"/projects/{scratch}/modules/hunting/resume")
    hit("module drain", "POST", f"/projects/{scratch}/modules/hunting/drain")
    hit("module resume (restore)", "POST", f"/projects/{scratch}/modules/hunting/resume")

    probe_file = RUNS_ROOT / "control-surface-probe.json"
    probe_file.parent.mkdir(parents=True, exist_ok=True)
    probe_file.write_text(json.dumps(out, indent=1))
    logger.info("control-surface probe written to %s", probe_file)


# --- CLI -----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("project_id")
    r.add_argument("target")
    r.add_argument("--top-faults", type=int, default=25)
    r.add_argument("--top-units", type=int, default=3)
    r.add_argument("--stop-after", type=int, default=40)
    r.add_argument("--poll-s", type=int, default=30)
    r.add_argument("--stall-min", type=int, default=10)
    p = sub.add_parser("probe")
    p.add_argument("project_id")
    args = ap.parse_args()

    if args.cmd == "probe":
        probe(args.project_id)
    else:
        asyncio.run(run(args.project_id, args.target, args.top_faults,
                        args.top_units, args.stop_after, args.poll_s, args.stall_min))


if __name__ == "__main__":
    main()
