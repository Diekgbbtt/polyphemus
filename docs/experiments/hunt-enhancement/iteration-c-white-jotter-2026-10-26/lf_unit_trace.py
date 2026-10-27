#!/usr/bin/env python3
"""Reconstruct one unit's threat-modeller trace timeline from Langfuse v2 observations.

Reads credentials from the instance .env, pages the Observations API, and prints a
compact timeline: trace, span name/type, duration, level/status, and a short payload
excerpt.  Raw payloads are never printed in full.

Usage:
  python3 lf_unit_trace.py --needle IdentificationSystem \
      --from 2026-10-26T21:40:00Z --to 2026-10-26T21:47:00Z [--session-suffix hunting_threat_modeller]
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import re
import urllib.parse
import urllib.request

ENV = pathlib.Path("/opt/polymerhus-dev/eval/instances/eval-server-1/.env")


def load_env(path: pathlib.Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def fetch(url: str, key: str, secret: str, params: dict[str, str]) -> dict:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{url}?{query}")
    token = base64.b64encode(f"{key}:{secret}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def excerpts(text: str, needle: str, width: int = 220) -> list[str]:
    if not text:
        return []
    hits = []
    for match in re.finditer(re.escape(needle), text):
        start = max(0, match.start() - width // 2)
        hits.append(" ".join(text[start : start + width].split()))
        if len(hits) >= 3:
            break
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--needle", required=True)
    ap.add_argument("--from", dest="from_time", required=True)
    ap.add_argument("--to", dest="to_time", required=True)
    ap.add_argument("--session-suffix", default="")
    args = ap.parse_args()

    env = load_env(ENV)
    host = env["LANGFUSE_HOST"].rstrip("/")
    key, secret = env["LANGFUSE_PUBLIC_KEY"], env["LANGFUSE_SECRET_KEY"]
    url = f"{host}/api/public/v2/observations"
    params = {
        "fromStartTime": args.from_time,
        "toStartTime": args.to_time,
        "fields": "core,basic,io,model,usage,trace_context",
        "limit": "100",
    }
    if args.session_suffix:
        # The session id is <run_id>:<agent>; the caller may pass the full suffix.
        params["sessionId"] = args.session_suffix

    observations: list[dict] = []
    cursor = None
    pages = 0
    while True:
        if cursor:
            params["cursor"] = cursor
        payload = fetch(url, key, secret, params)
        observations.extend(payload.get("data") or [])
        cursor = (payload.get("meta") or {}).get("cursor")
        pages += 1
        if not cursor or pages >= 40:
            break

    print(f"observations={len(observations)} pages={pages}")
    by_trace: dict[str, list[dict]] = {}
    for obs in observations:
        by_trace.setdefault(obs.get("traceId") or "?", []).append(obs)

    matched = []
    for trace_id, rows in by_trace.items():
        blob = " ".join(
            str(r.get("input") or "") + " " + str(r.get("output") or "") for r in rows
        )
        if args.needle in blob:
            matched.append((trace_id, rows))
    print(f"traces={len(by_trace)} matching={len(matched)}")
    for trace_id, rows in matched:
        rows.sort(key=lambda r: r.get("startTime") or "")
        name = next((r.get("traceName") for r in rows if r.get("traceName")), "")
        print("=" * 110)
        print(
            f"TRACE {trace_id} name={name} start={rows[0].get('startTime')} "
            f"end={rows[-1].get('endTime')} observations={len(rows)}"
        )
        errors = [r for r in rows if str(r.get("level") or "").upper() in ("ERROR", "WARNING")]
        for r in errors:
            print(f"  {r.get('level')} {r.get('name')} status={r.get('statusMessage')}")
        for r in rows:
            role = r.get("name")
            otype = r.get("type")
            duration = r.get("latency")
            model = r.get("modelId") or (r.get("model") or {}).get("modelId") if isinstance(r.get("model"), dict) else ""
            usage = r.get("totalUsage")
            status = r.get("statusMessage") or ""
            print(
                f"  {r.get('startTime')} {str(otype):10s} {str(role)[:44]:44s} "
                f"dur={duration} model={model or '-'} tok={usage or '-'} status={str(status)[:40]}"
            )
            out = str(r.get("output") or "")
            if out:
                for hit in excerpts(out, args.needle, 200):
                    print(f"      out~ {hit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
