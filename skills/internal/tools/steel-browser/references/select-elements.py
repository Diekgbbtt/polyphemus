#!/usr/bin/env python3
"""Select a family of DOM elements and return bounded, structured rows.

This is the canonical multi-element read for a live Steel session. It does not
start or stop a session. The session must already be live; the binary guard
refuses a missing or unknown name before the browser runs.

Usage:
  python3 select-elements.py --session S --url https://target/login \
      --selector 'a[href]' --attrs href,class --limit 20

  python3 select-elements.py --session S --selector '.card' \
      --attrs href,data-id --no-wait

The selector, attribute names, limits, and page URL are passed as separate
argv values. They are embedded in the JS with JSON escaping, never with shell
interpolation. The script projects inside the page: tag, normalised text,
selected attributes, visibility, and the total match count.

Output is one JSON object on stdout. A failure exits non-zero and carries
`error.code`, `error.message`, and the stage that failed.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

STEEL = "steel"


def _run(argv: list[str], timeout_s: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            [STEEL, *argv], capture_output=True, text=True, timeout=timeout_s
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


def _error_payload(proc: subprocess.CompletedProcess) -> dict:
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
    proc = _run(["browser", *args, "--session", session, "--json"], timeout_s)
    return _check(" ".join(args[:2]) or "browser", proc)


def build_js(
    selector: str,
    attrs: list[str],
    limit: int,
    text_limit: int,
    include_invisible: bool,
) -> str:
    """Build the page-side projection with JSON-escaped parameters.

    The JSON object is a valid JS literal. A selector containing a quote, a
    backslash, a newline, or `</script>` cannot break out of it.
    """
    spec = json.dumps({
        "selector": selector,
        "attrs": attrs,
        "limit": limit,
        "textLimit": text_limit,
        "includeInvisible": include_invisible,
        "maxScan": max(limit * 10, 500),
    }, ensure_ascii=False)
    return f"""(() => {{
  const spec = {spec};
  const all = Array.from(document.querySelectorAll(spec.selector));
  const rows = all.slice(0, spec.maxScan).map((el, index) => {{
    const text = (el.innerText || el.textContent || '')
      .replace(/\\s+/g, ' ').trim().slice(0, spec.textLimit);
    const rect = el.getBoundingClientRect();
    const style = window.getComputedStyle(el);
    const visible = rect.width > 0 && rect.height > 0
      && style.visibility !== 'hidden' && style.display !== 'none';
    const attributes = {{}};
    for (const name of spec.attrs) {{
      const value = el.getAttribute(name);
      if (value !== null) attributes[name] = String(value).slice(0, spec.textLimit);
    }}
    return {{index, tag: el.tagName.toLowerCase(), text, attributes, visible}};
  }});
  const filtered = spec.includeInvisible
    ? rows
    : rows.filter(row => row.visible);
  const elements = filtered.slice(0, spec.limit);
  return {{
    selector: spec.selector,
    count: all.length,
    scanned: rows.length,
    returned: elements.length,
    truncated: all.length > spec.maxScan || filtered.length > elements.length,
    elements,
  }};
}})()"""


def _page(session: str, timeout_s: int) -> tuple[str, str]:
    url = _browser(session, "get", "url", timeout_s=timeout_s).get("data")
    title = _browser(session, "get", "title", timeout_s=timeout_s).get("data")
    return str(url or ""), str(title or "")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", required=True)
    parser.add_argument("--selector", required=True)
    parser.add_argument("--attrs", default="href,src,id,class")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--text-limit", type=int, default=200)
    parser.add_argument("--include-invisible", action="store_true")
    parser.add_argument("--url", default=None)
    parser.add_argument("--wait-selector", default=None)
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--wait-timeout-ms", type=int, default=10000)
    parser.add_argument("--timeout-s", type=int, default=60)
    parser.add_argument("--max-chars", type=int, default=20000)
    parser.add_argument("--json", action="store_true", help="accepted for symmetry")
    return parser


def main() -> int:
    args = _parser().parse_args()
    attrs = [item.strip() for item in args.attrs.split(",") if item.strip()]
    if not attrs:
        print(json.dumps({"ok": False, "error": {
            "code": "invalid_arguments", "message": "--attrs must name at least one attribute",
        }}))
        return 2
    if not 1 <= args.limit <= 500:
        print(json.dumps({"ok": False, "error": {
            "code": "invalid_arguments", "message": "--limit must be between 1 and 500",
        }}))
        return 2
    if args.wait_timeout_ms >= args.timeout_s * 1000:
        print(json.dumps({"ok": False, "error": {
            "code": "timeout_ordering",
            "message": (
                f"wait timeout {args.wait_timeout_ms}ms must stay below the "
                f"tool timeout_s={args.timeout_s}"
            ),
        }}))
        return 2

    wait_selector = args.wait_selector or args.selector
    try:
        if args.url:
            _browser(
                args.session, "navigate", args.url,
                "--wait-until", "domcontentloaded", timeout_s=args.timeout_s,
            )
        if not args.no_wait:
            _browser(
                args.session, "wait", "--selector", wait_selector,
                "--timeout", str(args.wait_timeout_ms), timeout_s=args.timeout_s,
            )
        evaluated = _browser(
            args.session, "eval",
            build_js(
                args.selector, attrs, args.limit, args.text_limit,
                args.include_invisible,
            ),
            timeout_s=args.timeout_s,
        )
        url, title = _page(args.session, args.timeout_s)
    except RuntimeError as exc:
        print(str(exc))
        return 2

    data = evaluated.get("data")
    if isinstance(data, str):
        data = _json(data)
    if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
        print(json.dumps({
            "ok": False,
            "stage": "eval",
            "error": {
                "code": "invalid_response",
                "message": "the JS projection did not return an elements array",
            },
        }))
        return 1

    output = {
        "ok": True,
        "session": args.session,
        "url": url,
        "title": title,
        "selector": args.selector,
        "count": data.get("count"),
        "returned": data.get("returned"),
        "truncated": bool(data.get("truncated")),
        "elements": data.get("elements"),
    }
    serialized = json.dumps(output, ensure_ascii=False)
    if len(serialized) > args.max_chars:
        elements = output["elements"]
        while elements and len(json.dumps(
                {**output, "elements": elements}, ensure_ascii=False)) > args.max_chars:
            elements = elements[:-1]
        output["elements"] = elements
        output["returned"] = len(elements)
        output["truncated"] = True
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
