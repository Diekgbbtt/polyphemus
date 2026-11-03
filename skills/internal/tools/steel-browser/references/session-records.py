#!/usr/bin/env python3
"""Collect the platform record that a live Steel session leaves behind.

This is the canonical evidence read. It does not start or stop a session.
It fetches, in order:

- session metadata (`sessions --session`);
- the full runtime record from the Steel API when the session id is known;
- the browser event log, the raw agent event log, and the semantic trace
  timeline when the runtime exposes them;
- a compact accessibility snapshot;
- a screenshot file, unless disabled.

The self-hosted runtime used by this stack currently returns 404 for the three
record endpoints. That is recorded as `supported: false` and is not treated as
a session failure. Session metadata, the snapshot, and the screenshot still
form the durable record.

The three record probes are expected to fail on this runtime, and the script
handles them. Each probe runs with its own trace scope (the inherited
`KALI_STEEL_TRACE` is removed for that child), so the expected 404 does not
override the script's own successful result in the outer tool envelope. The
probe outcome is reported in `records`; the guard still enforces the call.

Output is one JSON object on stdout. A missing session or a failed metadata
read exits non-zero; a partial evidence set sets `partial: true` and still
exits zero.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import parse_qsl, urlparse

STEEL = "steel"


def _run(
    argv: list[str], timeout_s: int, env: dict | None = None
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [STEEL, *argv], capture_output=True, text=True, timeout=timeout_s,
            env=env,
        )
    except FileNotFoundError:
        raise SystemExit(json.dumps({"ok": False, "error": {
            "code": "steel_missing",
            "message": "the steel CLI is not on PATH",
        }}))
    except subprocess.TimeoutExpired:
        raise SystemExit(json.dumps({"ok": False, "error": {
            "code": "command_timeout",
            "message": f"steel did not return within {timeout_s}s",
        }}))


def _json(text: str):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _error(proc: subprocess.CompletedProcess) -> dict:
    stdout_json = _json((proc.stdout or "").strip())
    stderr_json = _json((proc.stderr or "").strip())
    error = None
    if isinstance(stdout_json, dict):
        candidate = stdout_json.get("error")
        if isinstance(candidate, dict):
            error = candidate
        elif candidate:
            error = {
                "code": stdout_json.get("error_code") or "command_failed",
                "message": str(candidate),
            }
    if error is None and isinstance(stderr_json, dict):
        candidate = stderr_json.get("error")
        if isinstance(candidate, dict):
            error = candidate
        elif candidate:
            error = {"code": "command_failed", "message": str(candidate)}
    if error is None:
        message = (proc.stderr or proc.stdout or "").strip()
        error = {
            "code": "command_failed" if proc.returncode else "invalid_response",
            "message": message[:800] or "steel returned no JSON envelope",
        }
    return {
        "code": str(error.get("code") or "command_failed"),
        "message": str(error.get("message") or "")[:800],
        "recovery": error.get("recovery"),
        "returncode": proc.returncode,
    }


def _record_probe(
    label: str, argv: list[str], timeout_s: int, preview_chars: int
) -> dict:
    # The probe is expected to fail where the runtime has no record endpoint.
    # Give it a local trace scope so its handled 404 does not become the outer
    # tool's error; the guard still enforces the invocation.
    env = dict(os.environ)
    env.pop("KALI_STEEL_TRACE", None)
    proc = _run(argv, timeout_s, env=env)
    payload = _json((proc.stdout or "").strip())
    if proc.returncode == 0 and isinstance(payload, dict) and payload.get("success") is not False:
        data = payload.get("data")
        if isinstance(data, list):
            return {
                "supported": True,
                "count": len(data),
                "preview": json.dumps(data[:3], ensure_ascii=False)[:preview_chars],
            }
        if isinstance(data, dict):
            return {
                "supported": True,
                "count": len(data),
                "preview": json.dumps(data, ensure_ascii=False)[:preview_chars],
            }
        return {
            "supported": True,
            "count": None,
            "preview": str(data)[:preview_chars],
        }
    return {
        "supported": False,
        "error": _error(proc),
    }


def _metadata(data: dict) -> dict:
    keys = (
        "id", "status", "createdAt", "duration", "eventCount", "timeout",
        "sessionViewerUrl", "debugUrl", "debuggerUrl", "dimensions",
        "userAgent",
    )
    return {key: data.get(key) for key in keys if key in data}


def _carries_session(url: str, session_id: str) -> bool:
    if not url or not session_id:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if any(part == session_id for part in parsed.path.split("/") if part):
        return True
    return any(value == session_id for _, value in parse_qsl(parsed.query))


def _live_view(metadata: dict) -> dict | None:
    """The view candidate with its addressability explicit.

    A cloud viewer URL can name the session; the self-hosted base is shared,
    and the debug player follows the active session. Never fabricate a
    session query parameter.
    """
    session_id = str(metadata.get("id") or "")
    candidates = (
        ("viewer", str(metadata.get("sessionViewerUrl") or "")),
        ("player", str(metadata.get("debugUrl") or "")),
        ("debugger", str(metadata.get("debuggerUrl") or "")),
    )
    for kind, url in candidates:
        if _carries_session(url, session_id):
            return {
                "url": url, "kind": kind, "session_id": session_id,
                "addressable": True, "scope": "session",
            }
    for kind, url in (
        ("player", str(metadata.get("debugUrl") or "")),
        ("viewer", str(metadata.get("sessionViewerUrl") or "")),
        ("debugger", str(metadata.get("debuggerUrl") or "")),
    ):
        if url:
            return {
                "url": url, "kind": kind, "session_id": session_id,
                "addressable": False, "scope": "active",
            }
    return None


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value)[:80] or "session"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--preview-chars", type=int, default=2000)
    parser.add_argument("--timeout-s", type=int, default=60)
    parser.add_argument("--out-dir", default="/work")
    parser.add_argument("--no-snapshot", action="store_true")
    parser.add_argument("--no-screenshot", action="store_true")
    parser.add_argument("--json", action="store_true", help="accepted for symmetry")
    return parser


def main() -> int:
    args = _parser().parse_args()
    metadata_proc = _run(
        ["--local", "sessions", "--session", args.session, "--json"],
        args.timeout_s,
    )
    metadata_payload = _json((metadata_proc.stdout or "").strip())
    if (
        metadata_proc.returncode != 0
        or not isinstance(metadata_payload, dict)
        or metadata_payload.get("success") is False
    ):
        print(json.dumps({
            "ok": False,
            "stage": "sessions_metadata",
            "session": args.session,
            "error": _error(metadata_proc),
        }))
        return 2
    data = metadata_payload.get("data")
    if isinstance(data, list):
        data = next(
            (item for item in data if item.get("name") == args.session), None
        )
    if not isinstance(data, dict):
        print(json.dumps({
            "ok": False,
            "stage": "sessions_metadata",
            "session": args.session,
            "error": "the named live session is not in the catalogue",
        }))
        return 2
    metadata = _metadata(data)
    errors: list[dict] = []
    records = {
        "logs": _record_probe(
            "logs",
            ["--local", "sessions", "logs", "--session", args.session,
             "--json", "--limit", str(args.limit)],
            args.timeout_s,
            args.preview_chars,
        ),
        "agent_logs": _record_probe(
            "agent_logs",
            ["--local", "sessions", "agent-logs", "--session", args.session,
             "--json", "--limit", str(args.limit)],
            args.timeout_s,
            args.preview_chars,
        ),
        # The traces command rejects --limit in the pinned CLI; pass only the
        # session and JSON flags, even though its help advertises filters.
        "traces": _record_probe(
            "traces",
            ["--local", "sessions", "traces", "--session", args.session,
             "--json"],
            args.timeout_s,
            args.preview_chars,
        ),
    }

    snapshot = None
    if not args.no_snapshot:
        proc = _run(
            ["browser", "snapshot", "-c", "--session", args.session, "--json"],
            args.timeout_s,
        )
        payload = _json((proc.stdout or "").strip())
        if proc.returncode == 0 and isinstance(payload, dict) and payload.get("success") is not False:
            text = str(payload.get("data") or "")
            snapshot = {
                "chars": len(text),
                "preview": text[: args.preview_chars],
            }
        else:
            snapshot = {"error": _error(proc)}
            errors.append({"stage": "snapshot", **snapshot["error"]})

    screenshot = None
    if not args.no_screenshot:
        os.makedirs(args.out_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        path = os.path.join(
            args.out_dir, f"{_safe_name(args.session)}-{stamp}.png"
        )
        proc = _run(
            ["browser", "screenshot", "-o", path, "--session", args.session,
             "--json"],
            args.timeout_s,
        )
        payload = _json((proc.stdout or "").strip())
        if proc.returncode == 0 and isinstance(payload, dict) and payload.get("success") is not False:
            reported = (payload.get("data") or {}).get("path") or path
            screenshot = {
                "path": reported,
                "bytes": os.path.getsize(reported) if os.path.exists(reported) else None,
            }
        else:
            screenshot = {"error": _error(proc)}
            errors.append({"stage": "screenshot", **screenshot["error"]})

    print(json.dumps({
        "ok": True,
        "session": args.session,
        "metadata": metadata,
        "live_view": _live_view(metadata),
        "snapshot": snapshot,
        "screenshot": screenshot,
        "records": records,
        "partial": bool(errors),
        "errors": errors,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
