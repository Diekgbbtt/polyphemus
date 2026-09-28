"""The API-only hunting control+monitor client (replaces hunting_drive.py).

The previous driver was fundamentally faulty: it FABRICATED the candidate
batch (placeholder witnesses, a hardcoded "applies" verdict) and bypassed the
platform's FaultSource selection entirely - an empty or fabricated batch makes
the orchestrator's pass vacuous (O1) or reasons over hollow evidence.

This client does NOT select or fabricate anything. It controls and monitors
through the API REST surface alone, and its only active feature is stopping the
run at a ratified-config threshold by watching the orchestrator tail.

Control (API):
  - POST /projects/{id}/hunting                      launch (empty batch - the
                                                     selection is the platform's
                                                     concern, once wired)
  - GET  /projects/{id}/hunting/{rid}                status row
  - POST /projects/{id}/hunting/{rid}/stop           stop
  - POST /projects/{id}/hunting/orchestrator         one orchestrator pass
  - POST /projects/{id}/hunting/hunt                 enqueue one ratified config
  - per-session + module lifecycle verbs             (not used by this client)

Monitoring (the orchestrator tail):
  - The ratified-config count is read from the project's HuntStore on the HOST
    path (the dev compose mounts src/ into /srv/src), never docker exec:
    src/polymerhus/attack/hunting/data/<project>/orchestration/hunt_configs/
    produced + consumed. Stop is issued via the API when the count reaches the
    threshold, or when the run reaches terminal on its own.

Env: PH_API (default http://localhost:8080), HUNT_DATA_ROOT (default
src/polymerhus/attack/hunting/data).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("hunting_ctl")

PH_API = os.environ.get("PH_API", "http://localhost:8080")


def _hunt_data_root() -> Path:
    """The HuntStore root. Env override first, then the CWD-relative repo
    `src/...`, then the main checkout beside the worktree layout
    (`<repo>/.claude/worktrees/<name>/tools/eval/` -> repo root). The dev
    compose mounts the MAIN checkout's src into /srv/src, so the container
    writes land on the main checkout path, never the worktree's."""
    env = os.environ.get("HUNT_DATA_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    candidates = [
        here.parents[5] / "src" / "polymerhus" / "attack" / "hunting" / "data",
        Path.cwd() / "src" / "polymerhus" / "attack" / "hunting" / "data",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


HUNT_DATA_ROOT = _hunt_data_root()


def _api(method: str, path: str, body=None, timeout: int = 30):
    import httpx
    try:
        if method == "GET":
            r = httpx.get(f"{PH_API}{path}", timeout=timeout)
        elif method == "POST":
            r = httpx.post(f"{PH_API}{path}", json=body or {}, timeout=timeout)
        else:  # pragma: no cover
            raise ValueError(method)
        return r.status_code, r.json()
    except Exception as exc:  # noqa: BLE001
        return 0, {"detail": f"request failed: {exc}"}


def _ratified_count(project_id: str) -> int:
    """The orchestrator tail: distinct ratified configs in the HuntStore
    produced+consumed families (the consumed move is the at-least-once marker,
    so a config may appear once per side - dedupe by file stem)."""
    base = HUNT_DATA_ROOT / project_id / "orchestration" / "hunt_configs"
    seen: set[str] = set()
    for side in ("produced", "consumed"):
        for f in (base / side).glob("*.yaml") if (base / side).exists() else ():
            seen.add(f.stem)
    return len(seen)


def cmd_launch(args):
    code, body = _api("POST", f"/projects/{args.project_id}/hunting", {})
    if code != 201:
        log.error("launch failed (%s): %s", code, body)
        sys.exit(1)
    rid = (body or {}).get("hunting_run_id")
    log.info("hunting run launched: %s", rid)
    print(rid)


def cmd_status(args):
    code, body = _api("GET", f"/projects/{args.project_id}/hunting/{args.run_id}")
    if code != 200:
        log.error("status failed (%s): %s", code, body)
        sys.exit(1)
    d = body or {}
    print(json.dumps({k: d.get(k) for k in (
        "hunting_run_id", "status", "started_at", "finished_at")}, default=str))
    print(f"orchestrator tail (ratified configs): {_ratified_count(args.project_id)}")


def cmd_stop(args):
    code, body = _api("POST", f"/projects/{args.project_id}/hunting/{args.run_id}/stop")
    log.info("stop response: %s %s", code, body)
    print("stopped" if code == 200 else f"stop failed ({code}): {body}")


def cmd_monitor(args):
    """Poll the API status + the orchestrator tail until terminal, the
    ratified-config threshold, or a stall (no new configs for `--stall-min`).
    Stop is issued through the API when the threshold is reached."""
    last_count = -1
    stalled_since = None
    while True:
        code, body = _api("GET", f"/projects/{args.project_id}/hunting/{args.run_id}")
        status = (body or {}).get("status") if code == 200 else "unreachable"
        count = _ratified_count(args.project_id)
        log.info("status=%s ratified=%d", status, count)
        if status not in ("running",):
            log.info("run terminal (%s); nothing to stop", status)
            return
        if args.stop_after and count >= args.stop_after:
            log.info("ratified %d >= stop-after %d; stopping via the API",
                     count, args.stop_after)
            cmd_stop(args)
            return
        if count == last_count:
            if stalled_since is None:
                stalled_since = time.time()
            elif time.time() - stalled_since > (args.stall_min * 60):
                log.warning("stall watchdog: no new configs for %d min; stopping",
                            args.stall_min)
                cmd_stop(args)
                return
        else:
            stalled_since = None
            last_count = count
        time.sleep(args.poll_s)


def main():
    p = argparse.ArgumentParser(description="API-only hunting control + monitor")
    sub = p.add_subparsers(dest="cmd", required=True)

    l = sub.add_parser("launch")
    l.add_argument("project_id")
    l.set_defaults(func=cmd_launch)

    s = sub.add_parser("status")
    s.add_argument("project_id")
    s.add_argument("run_id")
    s.set_defaults(func=cmd_status)

    st = sub.add_parser("stop")
    st.add_argument("project_id")
    st.add_argument("run_id")
    st.set_defaults(func=cmd_stop)

    m = sub.add_parser("monitor")
    m.add_argument("project_id")
    m.add_argument("run_id")
    m.add_argument("--stop-after", type=int, default=0)
    m.add_argument("--poll-s", type=int, default=60)
    m.add_argument("--stall-min", type=int, default=10)
    m.set_defaults(func=cmd_monitor)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()