#!/usr/bin/env python3
"""Tight external orchestration for a modeller-only pass.

The modeller-only launch writes no hunting_runs row and has no native budget or
stop verb. This monitor owns those controls from outside:

- it reads the project capped-token usage and stops the pass at the budget;
- it scans the produced unit models for the pass run_id and records progress;
- it reads the live control-plane thread and detects the pass terminal;
- it writes the progress and the terminal into the orchestration run row;
- it restores the project risk threshold when the pass ends.

The stop verb is the public per-session stop on the row this monitor owns.
No product code is changed.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RUN_DIR = Path(sys.argv[1])
SCOPE = json.loads((RUN_DIR / "scope.json").read_text(encoding="utf-8"))
PROJECT = SCOPE["project_id"]
RUN_ID = SCOPE["run_id"]
BASELINE = int(SCOPE["baseline_capped"])
BUDGET = int(SCOPE["token_budget"])
ORDER = list(SCOPE["order"])
DATA_ROOT = Path(SCOPE["data_root"])
PRODUCED = DATA_ROOT / PROJECT / "hunting" / "threat_modeller" / "produced"
SESSION_ID = f"hunting:{RUN_ID}:threat-modeller"
API = "http://127.0.0.1:8080"
PG = ["docker", "exec", "-i", "ph-17747005-postgres-1",
      "psql", "-U", "polymerhus", "-d", "polymerhus", "-tA"]
PROGRESS = RUN_DIR / "progress.json"
STOP_FILE = RUN_DIR / "STOP"
POLL_S = 60
ROW_UPDATE_S = 300


def now():
    return datetime.now(timezone.utc).isoformat()


def log(message):
    print(f"{now()} {message}", flush=True)


def http_json(url, method="GET", payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def usage():
    try:
        data = http_json(f"{API}/projects/{PROJECT}/usage")
        return int(data.get("capped_tokens") or 0), int(data.get("calls") or 0)
    except Exception as exc:  # noqa: BLE001 - a read failure is not a stop
        log(f"usage read failed: {exc}")
        return None, None


def live_thread():
    try:
        threads = http_json(f"{API}/projects/{PROJECT}/hunting/{RUN_ID}/threads")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        log(f"threads read failed: {exc}")
        return None
    except Exception as exc:  # noqa: BLE001
        log(f"threads read failed: {exc}")
        return None
    return any(t.get("thread_id") == SESSION_ID for t in threads or [])


def scan_models():
    units = {}
    threats = 0
    risk_total = 0.0
    if not PRODUCED.exists():
        return units, threats, risk_total
    for unit_dir in sorted(PRODUCED.iterdir()):
        if not unit_dir.is_dir():
            continue
        matched = False
        for path in unit_dir.glob("*.yaml"):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if f"run_id: {RUN_ID}" not in text:
                continue
            matched = True
            if path.name.startswith("threat-"):
                threats += 1
                for line in text.splitlines():
                    if line.startswith("risk:"):
                        try:
                            risk_total += float(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass
                        break
        if matched:
            units[unit_dir.name] = True
    return units, threats, risk_total


def update_row(status, finished, stats):
    payload = json.dumps(stats)
    finished_sql = "now()" if finished else "NULL"
    sql = (
        "UPDATE hunting_runs SET "
        f"status = '{status}', finished_at = {finished_sql}, "
        f"stats = $json${payload}$json$::jsonb "
        f"WHERE hunting_run_id = '{RUN_ID}';"
    )
    result = subprocess.run(
        PG, input=sql, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        log(f"row update failed: {result.stderr.strip()[:300]}")


def stop_pass():
    url = f"{API}/projects/{PROJECT}/hunting/{RUN_ID}/sessions/{SESSION_ID}/stop"
    try:
        http_json(url, method="POST", payload={})
        log("stop verb accepted")
        return True
    except urllib.error.HTTPError as exc:
        log(f"stop verb HTTP {exc.code}")
        return exc.code == 404
    except Exception as exc:  # noqa: BLE001
        log(f"stop verb failed: {exc}")
        return False


def restore_threshold():
    try:
        http_json(
            f"{API}/projects/{PROJECT}/hunting/config",
            method="PUT",
            payload={"risk_threshold": 220},
        )
        log("risk threshold restored to 220")
    except Exception as exc:  # noqa: BLE001
        log(f"threshold restore failed: {exc}")


def main():
    baseline_stats = {
        "mode": "threat_model_only",
        "component": "threat_modeller",
        "intake_order": ORDER,
        "intake_excluded": SCOPE.get("excluded") or [],
        "risk_threshold": 10000.0,
        "threshold_basis": "db",
        "risk_total": 0.0,
        "halt": False,
        "monitor": {
            "started_at": now(),
            "baseline_capped": BASELINE,
            "token_budget": BUDGET,
            "poll_s": POLL_S,
        },
    }
    update_row("running", False, baseline_stats)
    log(f"monitor start run={RUN_ID} units={len(ORDER)} budget={BUDGET}")

    last_row_update = 0.0
    absent_checks = 0
    previous_units = -1
    while True:
        capped, calls = usage()
        units, threats, risk_total = scan_models()
        thread = live_thread()
        spent = (capped - BASELINE) if capped is not None else None
        stats = dict(baseline_stats)
        stats.update({
            "intake_position": len(units),
            "risk_total": round(risk_total, 2),
            "monitor": {
                **baseline_stats["monitor"],
                "updated_at": now(),
                "capped_tokens": capped,
                "spent_tokens": spent,
                "calls": calls,
                "produced_units": len(units),
                "threat_files": threats,
                "thread_live": thread,
            },
        })
        PROGRESS.write_text(json.dumps(stats, indent=1), encoding="utf-8")
        log(
            f"units={len(units)}/{len(ORDER)} threats={threats} "
            f"risk={risk_total:.2f} spent={spent} calls={calls} thread={thread}"
        )

        stop_reason = None
        if STOP_FILE.exists():
            stop_reason = "manual_stop"
        elif spent is not None and spent >= BUDGET:
            stop_reason = "token_budget"
        elif thread is False and len(units) >= len(ORDER):
            stop_reason = "complete"
        elif thread is False:
            absent_checks += 1
            if absent_checks >= 2 and len(units) == previous_units:
                stop_reason = "ended_early"
        else:
            absent_checks = 0
        previous_units = len(units)

        if stop_reason:
            if stop_reason in {"manual_stop", "token_budget"}:
                stop_pass()
            status = "complete" if stop_reason == "complete" else "stopped"
            stats["halt"] = stop_reason == "token_budget"
            stats["monitor"]["stopped_reason"] = stop_reason
            stats["monitor"]["finished_at"] = now()
            update_row(status, True, stats)
            restore_threshold()
            log(f"monitor stop reason={stop_reason} status={status}")
            return 0

        if time.time() - last_row_update >= ROW_UPDATE_S:
            update_row("running", False, stats)
            last_row_update = time.time()
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
