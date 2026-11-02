#!/usr/bin/env python3
"""Load one URL, optionally wait, evaluate one JS expression, return JSON.

This is the canonical multi-step read for a live Steel session. It does not
start or stop a session. The session must already be live; the binary guard
refuses a missing or unknown name before the browser runs.

Usage:
  python3 load-eval.py --session S --url https://target/login \
      --wait-selector 'form' --eval 'document.title'

  python3 load-eval.py --session S --eval-file /work/read.js

The JS expression is passed as one argv, never through a shell. A caller that
needs a large program should write it to a file and use --eval-file; a caller
that needs a bounded result should project inside the JS (map, slice,
JSON.stringify) because --max-chars is a safety net, not a substitute.

Output is one JSON object on stdout. A failure exits non-zero and carries
`error.code`, `error.message`, and the stage that failed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

STEEL = "steel"


def _run(argv: list[str], timeout_s: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [STEEL, *argv], capture_output=True, text=True, timeout=timeout_s
        )
    except FileNotFoundError:
        raise SystemExit(
            json.dumps({"ok": False, "error": {
                "code": "steel_missing",
                "message": "the steel CLI is not on PATH",
            }})
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(
            json.dumps({"ok": False, "error": {
                "code": "command_timeout",
                "message": f"steel did not return within {timeout_s}s",
            }})
        )


def _json(text: str):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _error_payload(proc: subprocess.CompletedProcess) -> dict:
    """The CLI and the binary guard use two different error channels.

    The CLI writes `{"error": "...", "error_code": ...}` to stdout. The guard
    writes `{"error": {code, message, recovery}}` to stderr and exits 2.
    Parse stdout first, then stderr; never drop the stderr text.
    """
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


def _check(stage: str, proc: subprocess.CompletedProcess) -> dict:
    payload = _json((proc.stdout or "").strip())
    if proc.returncode != 0 or not isinstance(payload, dict) or payload.get("success") is False:
        raise RuntimeError(json.dumps({
            "ok": False,
            "stage": stage,
            "error": _error_payload(proc),
            "stdout": (proc.stdout or "")[:400],
            "stderr": (proc.stderr or "")[:400],
        }))
    return payload


def _browser(session: str, *args: str, timeout_s: int) -> dict:
    proc = _run(
        ["browser", *args, "--session", session, "--json"], timeout_s
    )
    return _check(" ".join(args[:2]) or "browser", proc)


def _page(session: str, timeout_s: int) -> tuple[str, str]:
    url = _browser(session, "get", "url", timeout_s=timeout_s).get("data")
    title = _browser(session, "get", "title", timeout_s=timeout_s).get("data")
    return str(url or ""), str(title or "")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--url", default=None)
    parser.add_argument(
        "--wait-until", default="domcontentloaded",
        choices=("load", "domcontentloaded", "networkidle"),
    )
    parser.add_argument("--wait-selector", default=None)
    parser.add_argument("--wait-text", default=None)
    parser.add_argument("--wait-timeout-ms", type=int, default=10000)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--eval", dest="expression", default=None)
    group.add_argument("--eval-file", type=Path, default=None)
    parser.add_argument("--timeout-s", type=int, default=60)
    parser.add_argument("--max-chars", type=int, default=12000)
    parser.add_argument("--json", action="store_true", help="accepted for symmetry")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.wait_timeout_ms >= args.timeout_s * 1000:
        print(json.dumps({"ok": False, "error": {
            "code": "timeout_ordering",
            "message": (
                f"wait timeout {args.wait_timeout_ms}ms must stay below the "
                f"tool timeout_s={args.timeout_s}"
            ),
        }}))
        return 2
    if args.eval_file is not None:
        try:
            expression = args.eval_file.read_text(encoding="utf-8")
        except OSError as exc:
            print(json.dumps({"ok": False, "error": {
                "code": "eval_file_unreadable", "message": str(exc),
            }}))
            return 2
    else:
        expression = args.expression or ""

    try:
        if args.url:
            _browser(
                args.session, "navigate", args.url,
                "--wait-until", args.wait_until, timeout_s=args.timeout_s,
            )
        if args.wait_selector:
            _browser(
                args.session, "wait", "--selector", args.wait_selector,
                "--timeout", str(args.wait_timeout_ms), timeout_s=args.timeout_s,
            )
        if args.wait_text:
            _browser(
                args.session, "wait", "--text", args.wait_text,
                "--timeout", str(args.wait_timeout_ms), timeout_s=args.timeout_s,
            )
        evaluated = _browser(
            args.session, "eval", expression, timeout_s=args.timeout_s
        )
        url, title = _page(args.session, args.timeout_s)
    except RuntimeError as exc:
        print(str(exc))
        return 2

    result = evaluated.get("data")
    serialized = json.dumps(result, ensure_ascii=False)
    truncated = len(serialized) > args.max_chars
    if truncated:
        result = serialized[: args.max_chars]
    print(json.dumps({
        "ok": True,
        "session": args.session,
        "url": url,
        "title": title,
        "result": result,
        "result_truncated": truncated,
        "result_chars": len(serialized),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
