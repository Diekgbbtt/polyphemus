#!/usr/bin/env python3
"""Measure whether ``browser stop`` returns before the worker settles.

The v0.5.5 API runs one active session. ``endSession`` marks it released, then
awaits the CDP teardown, then installs a fresh idle placeholder. If the CLI
returns before that sequence finishes, the lease releases a worker that is
still tearing down and the next start races the tail of the previous end.

This probe starts one session through the production guard, stops it, and then
samples ``GET /v1/sessions`` every 20 ms so the intermediate state is visible.
"""
from __future__ import annotations

import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
CLI = os.environ["STEEL_CLI"]
GUARD = os.environ.get("STEEL_GUARD", str(ROOT / "kali" / "steel_guard.py"))
PORT = int(os.environ.get("STEEL_PROBE_WORKER_PORT", "3110"))
API = f"http://localhost:{PORT}/v1"


def sessions() -> list[dict]:
    connection = http.client.HTTPConnection("localhost", PORT, timeout=5)
    try:
        connection.request("GET", "/v1/sessions", headers={"Host": f"localhost:{PORT}"})
        response = connection.getresponse()
        body = response.read()
    finally:
        connection.close()
    payload = json.loads(body)
    return payload.get("sessions", [])


def shape(rows: list[dict]) -> list[str]:
    return [f"{row['status']}:{row['id'][:8]}" for row in rows]


def cli(*args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, GUARD, "--api-url", API, *args],
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ, "STEEL_REAL_BINARY_REAL": CLI},
    )
    if completed.returncode != 0:
        raise SystemExit(
            f"cli failed rc={completed.returncode}\n{completed.stdout}\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


def main() -> int:
    name = f"settle-{os.getpid()}"
    started = cli(
        "browser",
        "start",
        "--session",
        name,
        "--session-timeout",
        "3600000",
        "--inactivity-timeout",
        "0",
        "--json",
    )
    print(json.dumps({"stage": "start", "result": started, "sessions": shape(sessions())}))

    t0 = time.monotonic()
    stopped = cli("browser", "stop", "--session", name, "--json")
    t_stop = (time.monotonic() - t0) * 1000
    print(
        json.dumps(
            {
                "stage": "stop",
                "elapsed_ms": round(t_stop, 1),
                "result": stopped,
                "sessions": shape(sessions()),
            }
        )
    )

    samples: list[dict] = []
    deadline = time.monotonic() + float(os.environ.get("STEEL_SETTLE_WATCH_S", "2.0"))
    last = None
    while time.monotonic() < deadline:
        current = shape(sessions())
        if current != last:
            samples.append(
                {
                    "t_ms": round((time.monotonic() - t0) * 1000, 1),
                    "sessions": current,
                }
            )
            last = current
        time.sleep(0.02)
    print(json.dumps({"stage": "settle", "transitions": samples}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
