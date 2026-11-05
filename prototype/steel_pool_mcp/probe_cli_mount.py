#!/usr/bin/env python3
"""Live check of the Steel CLI mount against one v0.5.5 worker.

This is the manual E2E tier behind ``tests/kali/test_steel_pool_cli.py``.
It starts a real CLI session on a running worker, restores a cookie and a
localStorage key, reads them back, captures the API context, and stops the
session.

Usage:

    STEEL_WORKER_URL=http://127.0.0.1:3110 \
    STEEL_CLI_BINARY=/path/to/steel-0.5.0-preview.6 \
    python3 prototype/steel_pool_mcp/probe_cli_mount.py

The worker must run the v0.5.5-beta image with ``--no-nginx`` and
``ENABLE_COMMANDS_API=true``, on host port 3110 by default.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from kali.steel_pool.cli import SteelCli  # noqa: E402
from kali.steel_pool.store import BrowserSessionRecord  # noqa: E402

WORKER_URL = os.environ.get("STEEL_WORKER_URL", "http://127.0.0.1:3110")
CLI_BINARY = os.environ.get("STEEL_CLI_BINARY", "")
GUARD = str(ROOT / "kali" / "steel_guard.py")
TRACE = os.environ.get(
    "KALI_STEEL_TRACE",
    f"/tmp/steel-cli-mount-probe-{uuid.uuid4().hex}.jsonl",
)


def _fail(message: str, **details: object) -> None:
    print(json.dumps({"ok": False, "error": message, **details}, indent=2))
    raise SystemExit(1)


def main() -> int:
    if not CLI_BINARY:
        _fail("STEEL_CLI_BINARY is required")
    if not os.access(CLI_BINARY, os.X_OK):
        _fail("the Steel CLI binary is not executable", binary=CLI_BINARY)

    name = f"probe-w3-{uuid.uuid4().hex[:8]}"
    record = BrowserSessionRecord(
        name=name,
        cookies=[
            {
                "name": "probe_cookie",
                "value": "probe value",
                "domain": "localhost",
                "path": "/",
            }
        ],
        local_storage={"http://localhost:3000": {"probe_key": "probe_value"}},
    )
    cli = SteelCli(
        WORKER_URL,
        binary=CLI_BINARY,
        guard_path=GUARD,
        python=sys.executable,
        timeout_s=180.0,
        env={
            **os.environ,
            "STEEL_REAL_BINARY_REAL": CLI_BINARY,
            "KALI_STEEL_TRACE": TRACE,
            "STEEL_TELEMETRY_DISABLED": "1",
        },
    )

    report: dict[str, object] = {"ok": False, "name": name, "trace": TRACE}
    session = None
    try:
        session = cli.start(name)
        report["session_id"] = session.session_id

        restored = cli.restore(session, record)
        report["restore"] = {
            "cookies_set": restored.cookies_set,
            "origins_visited": restored.origins_visited,
            "storage_keys_set": restored.storage_keys_set,
            "warnings": list(restored.warnings),
        }

        cli.exec(session, ["navigate", "http://localhost:3000"])
        url = cli.exec(session, ["get", "url"])
        report["current_url"] = url.get("data")

        cookies = cli.exec(session, ["cookies"])
        cookie_rows = cookies.get("data")
        if not isinstance(cookie_rows, list):
            _fail("the CLI cookie read is not a list", payload=cookies)
        found_cookie = any(
            isinstance(row, dict)
            and row.get("name") == "probe_cookie"
            and row.get("value") == "probe value"
            for row in cookie_rows
        )
        if not found_cookie:
            _fail("the restored cookie is not visible", cookies=cookie_rows)
        report["cookie_restored"] = True

        storage = cli.exec(session, ["storage", "local"])
        storage_rows = storage.get("data")
        if not isinstance(storage_rows, dict):
            _fail("the CLI storage read is not an object", payload=storage)
        if storage_rows.get("probe_key") != "probe_value":
            _fail("the restored localStorage key is not visible", storage=storage_rows)
        report["local_storage_restored"] = True

        captured = cli.capture(session, record)
        report["capture"] = {
            "source": captured.source,
            "warnings": list(captured.warnings),
            "local_storage": captured.context.get("localStorage"),
            "session_storage": captured.context.get("sessionStorage"),
        }
        storage_keys = captured.context.get("localStorage")
        if not isinstance(storage_keys, dict):
            _fail("the captured localStorage is not an object", context=captured.context)
        if storage_keys.get("http://localhost:3000", {}).get("probe_key") != (
            "probe_value"
        ):
            _fail(
                "the captured localStorage is not keyed by origin",
                local_storage=storage_keys,
            )

        report["ok"] = True
    finally:
        if session is not None:
            try:
                cli.stop(session)
                report["stopped"] = True
            except Exception as exc:  # noqa: BLE001 - report the cleanup failure
                report["stop_error"] = f"{type(exc).__name__}: {exc}"
                try:
                    report["released"] = cli.release(session)
                except Exception as release_exc:  # noqa: BLE001
                    report["release_error"] = (
                        f"{type(release_exc).__name__}: {release_exc}"
                    )

    events = 0
    try:
        with open(TRACE, encoding="utf-8") as handle:
            events = sum(1 for line in handle if line.strip())
    except OSError:
        pass
    report["guard_events"] = events
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
