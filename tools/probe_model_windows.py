"""Probe the context window of every model group registered on the gateway.

A simple LLM client against the in-container gateway (reached from the host
through the scaffolded forwarding in docker-compose.probe.yml): for each
model group it reports whether it serves, its total context window, and
whether its stream carries reasoning deltas.

Window detection burns (almost) no inference: a non-streaming call with an
absurd max_completion_tokens is rejected BEFORE inference with a 400 whose
message states the limit (e.g. max_total_tokens=22000). Only the small
serve/reasoning checks execute the model.

Usage:
    docker compose -f docker-compose.yml -f docker-compose.dev.yml \\
      -f docker-compose.e2e.yml -f docker-compose.probe.yml up -d --force-recreate agent
    LITELLM_MASTER_KEY=<key> python tools/probe_model_windows.py \\
      --gateway http://127.0.0.1:14000

The key is never printed; it travels in the Authorization header only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

LIMIT_PATTERNS = [
    re.compile(r"max_total_tokens=(\d+)"),
    re.compile(r"maximum context length of (\d+) tokens"),
    re.compile(r"maximum context length is (\d+) tokens"),
    re.compile(r"max_model_len[=:](\d+)"),
    re.compile(r"context-length (\d+)"),
]


def _req(gateway: str, key: str, path: str, payload: dict | None,
         timeout: int) -> tuple[int, str]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        gateway + path, data=data, method="GET" if payload is None else "POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # unreachable / timeout - the flap signature
        return -1, f"{type(exc).__name__}: {exc}"


def _window_from_error(body: str) -> int | None:
    for pattern in LIMIT_PATTERNS:
        match = pattern.search(body)
        if match:
            return int(match.group(1))
    return None


def probe_model(gateway: str, key: str, model: str) -> dict:
    row: dict = {"model": model}
    tiny = {"model": model,
            "messages": [{"role": "user", "content": "Reply with: OK"}],
            "stream": False, "max_completion_tokens": 50}
    status, body = _req(gateway, key, "/v1/chat/completions", tiny, 180)
    row["serves"] = status == 200
    if status != 200:
        row["serve_note"] = body[:160]
        if status == -1:
            return row  # unreachable - nothing else to learn
    else:
        row["serve_note"] = "ok"
    huge = dict(tiny, max_completion_tokens=131072)
    status, body = _req(gateway, key, "/v1/chat/completions", huge, 120)
    if status == 200:
        row["max_total_tokens"] = "131072+"
    else:
        window = _window_from_error(body)
        row["max_total_tokens"] = window if window else f"unknown ({body[:120]})"
    stream_payload = {
        "model": model,
        "messages": [{"role": "user",
                      "content": "Think briefly, then reply with: DONE"}],
        "stream": True, "max_completion_tokens": 400}
    keys: set[str] = set()
    chunks = 0
    req = urllib.request.Request(
        gateway + "/v1/chat/completions",
        data=json.dumps(stream_payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Accept": "text/event-stream"})
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                try:
                    delta = (json.loads(line[6:]).get("choices") or [{}])[0].get("delta") or {}
                except json.JSONDecodeError:
                    continue
                keys.update(delta.keys())
                chunks += 1
    except Exception as exc:
        row["stream_note"] = f"{type(exc).__name__}: {str(exc)[:100]}"
    row["stream_chunks"] = chunks
    row["reasoning_deltas"] = "reasoning_content" in keys
    row["delta_keys"] = sorted(keys)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "probe gateway model windows").splitlines()[0])
    parser.add_argument("--gateway", default="http://127.0.0.1:14000")
    parser.add_argument("--key", default=None,
                        help="gateway master key (else LITELLM_MASTER_KEY env)")
    parser.add_argument("--env-file", default=None,
                        help="read LITELLM_MASTER_KEY from this .env file")
    parser.add_argument("--only", default=None,
                        help="comma-separated model group substring filter")
    args = parser.parse_args()
    key = args.key
    if not key and args.env_file:
        with open(args.env_file) as handle:
            for line in handle:
                line = line.strip()
                if line.startswith("LITELLM_MASTER_KEY="):
                    key = line.partition("=")[2].strip().strip("\"'")
                    break
    if not key:
        import os
        key = os.environ.get("LITELLM_MASTER_KEY")
    if not key:
        print("need --key, --env-file, or LITELLM_MASTER_KEY", file=sys.stderr)
        return 2
    import os
    _ = os.environ  # keys stay in memory; never printed
    status, body = _req(args.gateway, key, "/model/info", None, 60)
    if status != 200:
        print(f"/model/info failed: {status} {body[:200]}", file=sys.stderr)
        return 1
    try:
        groups = [m.get("model_name") for m in json.loads(body).get("data", [])]
    except json.JSONDecodeError:
        print("unparseable /model/info", file=sys.stderr)
        return 1
    groups = [g for g in groups if isinstance(g, str)]
    if args.only:
        wanted = [s.strip() for s in args.only.split(",")]
        groups = [g for g in groups if any(s in g for s in wanted)]
    rows = [probe_model(args.gateway, key, group) for group in groups]
    widths = {"model": 3, "serves": 3, "window": 3, "stream": 3, "reason": 3}
    pretty = []
    for row in rows:
        pretty.append({
            "model": row["model"],
            "serves": "yes" if row.get("serves") else "NO",
            "window": str(row.get("max_total_tokens", "?")),
            "stream": str(row.get("stream_chunks", "?")),
            "reason": "yes" if row.get("reasoning_deltas") else "-",
        })
    for item in pretty:
        for field, width in widths.items():
            widths[field] = max(width, len(item[field]))
    header = (f"{'model':<{widths['model']}}  {'serves':<{widths['serves']}}  "
              f"{'window':<{widths['window']}}  {'stream':<{widths['stream']}}  "
              f"{'reason':<{widths['reason']}}")
    print(header)
    print("-" * len(header))
    for item in pretty:
        print(f"{item['model']:<{widths['model']}}  {item['serves']:<{widths['serves']}}  "
              f"{item['window']:<{widths['window']}}  {item['stream']:<{widths['stream']}}  "
              f"{item['reason']:<{widths['reason']}}")
    print()
    for row in rows:
        if row.get("serve_note") not in (None, "ok"):
            print(f"# {row['model']}: {row['serve_note'][:200]}")
        if row.get("stream_note"):
            print(f"# {row['model']} stream: {row['stream_note'][:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
