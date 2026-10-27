#!/usr/bin/env python3
"""Summarise one unit's threat-modeller traces: tool use, validation feedback, errors.

Prints, per matching trace: time span, tool-call inventory with short argument
excerpts, hunts_store validation issues, generation counts, and any non-default
levels.  Payloads are truncated so the output stays auditable.

Usage:
  python3 lf_trace_tools.py --needle IdentificationSystem \
      --from 2026-10-26T21:40:00Z --to 2026-10-26T21:47:00Z
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import re
import urllib.parse
import urllib.request
from collections import Counter

ENV = pathlib.Path("/opt/polymerhus-dev/eval/instances/eval-server-1/.env")


def load_env(path: pathlib.Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def fetch(url: str, key: str, secret: str, params: dict[str, str]) -> dict:
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}")
    req.add_header(
        "Authorization", "Basic " + base64.b64encode(f"{key}:{secret}".encode()).decode()
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def clip(text: object, limit: int = 260) -> str:
    return " ".join(str(text or "").split())[:limit]


def tool_args(raw: str) -> str:
    """Extract the tool call arguments from a tool observation's input blob."""
    text = str(raw or "")
    match = re.search(r'"name":\s*"([a-z_]+)".*?"args":\s*(\{.*?\})\s*[,}]', text)
    if match:
        return f"{match.group(1)}({clip(match.group(2), 240)})"
    return clip(text, 200)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--needle", required=True)
    ap.add_argument("--from", dest="from_time", required=True)
    ap.add_argument("--to", dest="to_time", required=True)
    args = ap.parse_args()

    env = load_env(ENV)
    host = env["LANGFUSE_HOST"].rstrip("/")
    url = f"{host}/api/public/v2/observations"
    params = {
        "fromStartTime": args.from_time,
        "toStartTime": args.to_time,
        "fields": "core,basic,io,usage",
        "limit": "100",
    }
    observations: list[dict] = []
    cursor = None
    while True:
        if cursor:
            params["cursor"] = cursor
        payload = fetch(url, env["LANGFUSE_PUBLIC_KEY"], env["LANGFUSE_SECRET_KEY"], params)
        observations.extend(payload.get("data") or [])
        cursor = (payload.get("meta") or {}).get("cursor")
        if not cursor:
            break

    by_trace: dict[str, list[dict]] = {}
    for obs in observations:
        by_trace.setdefault(obs.get("traceId") or "?", []).append(obs)

    seen: list[tuple[str, list[dict]]] = []
    for trace_id, rows in by_trace.items():
        blob = " ".join(str(r.get("input") or "") + str(r.get("output") or "") for r in rows)
        if args.needle in blob:
            seen.append((trace_id, sorted(rows, key=lambda r: r.get("startTime") or "")))

    seen.sort(key=lambda item: item[1][0].get("startTime") or "")
    print(f"traces matching {args.needle}: {len(seen)}")
    for trace_id, rows in seen:
        tools = [r for r in rows if str(r.get("type")) == "TOOL"]
        gens = [r for r in rows if str(r.get("type")) == "GENERATION"]
        levels = [r for r in rows if str(r.get("level") or "").upper() != "DEFAULT"]
        print("=" * 108)
        print(
            f"TRACE {trace_id} start={rows[0].get('startTime')} end={rows[-1].get('endTime')} "
            f"obs={len(rows)} tools={len(tools)} gens={len(gens)}"
        )
        if levels:
            for r in levels:
                print(f"  LEVEL {r.get('level')} {r.get('name')} status={clip(r.get('statusMessage'), 160)}")
        counts = Counter(str(t.get("name")) for t in tools)
        print(f"  tool counts: {dict(counts)}")
        for tool in tools:
            name = str(tool.get("name"))
            if name in ("notes", "skill_load"):
                continue
            print(f"  TOOL {name} dur={tool.get('latency')}")
            print(f"    in  {tool_args(tool.get('input'))}")
            out = str(tool.get("output") or "")
            issues = re.findall(r'"issues":\s*\[(.*?)\]', out)
            if issues:
                print(f"    issues {clip(issues[0], 400)}")
            if name == "hunts_store":
                hint = re.findall(r'"hint":\s*"([^"]{0,200})"', out)
                if hint:
                    print(f"    hint {clip(hint[0], 200)}")
            elif out and name not in ("hunts_store",):
                print(f"    out {clip(out, 220)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
