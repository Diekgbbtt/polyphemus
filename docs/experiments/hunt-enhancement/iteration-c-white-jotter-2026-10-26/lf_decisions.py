#!/usr/bin/env python3
"""Extract the decision-node evidence for one threat-modeller unit from Langfuse.

Prints, for the traces that mention the unit:
  - every non-default level with status (functional failures),
  - the PRIOR_ART write and its note (ownership allocation),
  - the IMPACT_ASSESSED write (disposition, capability_path, precursor_refs),
  - the COMPLETED write (threats count).

Usage:
  python3 lf_decisions.py --unit IdentificationSystem --from <iso> --to <iso>
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import re
import urllib.parse
import urllib.request

ENV = pathlib.Path("/opt/polymerhus-dev/eval/instances/eval-server-1/.env")


def env() -> dict[str, str]:
    out = {}
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def observations(params: dict[str, str]) -> list[dict]:
    cfg = env()
    host = cfg["LANGFUSE_HOST"].rstrip("/")
    token = base64.b64encode(
        f"{cfg['LANGFUSE_PUBLIC_KEY']}:{cfg['LANGFUSE_SECRET_KEY']}".encode()
    ).decode()
    rows: list[dict] = []
    cursor = None
    while True:
        if cursor:
            params["cursor"] = cursor
        req = urllib.request.Request(
            f"{host}/api/public/v2/observations?{urllib.parse.urlencode(params)}"
        )
        req.add_header("Authorization", f"Basic {token}")
        with urllib.request.urlopen(req, timeout=60) as response:
            payload = json.load(response)
        rows.extend(payload.get("data") or [])
        cursor = (payload.get("meta") or {}).get("cursor")
        if not cursor:
            return rows


def clip(value: object, limit: int = 1400) -> str:
    return " ".join(str(value or "").split())[:limit]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit", required=True)
    ap.add_argument("--from", dest="from_time", required=True)
    ap.add_argument("--to", dest="to_time", required=True)
    args = ap.parse_args()

    rows = observations(
        {
            "fromStartTime": args.from_time,
            "toStartTime": args.to_time,
            "fields": "core,basic,io",
            "limit": "100",
        }
    )
    by_trace: dict[str, list[dict]] = {}
    for row in rows:
        by_trace.setdefault(row.get("traceId") or "?", []).append(row)

    print(f"observations={len(rows)} traces={len(by_trace)}")
    hits = 0
    for trace_id, group in sorted(by_trace.items(), key=lambda kv: kv[1][0].get("startTime") or ""):
        blob = " ".join(str(r.get("input") or "") + str(r.get("output") or "") for r in group)
        slug = args.unit.replace(":", "-").replace("/", "-")
        markers = (
            f"/produced/{args.unit}/",
            f"/consumed/{args.unit}/",
            f"/produced/{slug}/",
            f"/consumed/{slug}/",
            f'"unit_id": "{args.unit}"',
            f'"unit_id":"{args.unit}"',
        )
        if not any(marker in blob for marker in markers):
            continue
        hits += 1
        group.sort(key=lambda r: r.get("startTime") or "")
        print("=" * 100)
        print(f"TRACE {trace_id} start={group[0].get('startTime')} obs={len(group)}")
        for r in group:
            if str(r.get("level") or "").upper() not in ("DEFAULT", ""):
                print(f"  LEVEL {r.get('level')} {r.get('name')} {clip(r.get('statusMessage'), 200)}")
        for r in group:
            if str(r.get("type")) != "TOOL" or str(r.get("name")) != "hunts_store":
                continue
            inp = str(r.get("input") or "")
            out = str(r.get("output") or "")
            if '"prior_art"' in inp:
                note = re.findall(r'"notes":\s*"((?:[^"\\]|\\.){0,1600})', inp)
                print("  PRIOR_ART WRITE:", clip(note[0] if note else inp, 1600))
            if '"impact_assessment"' in inp:
                disp = re.findall(r'"disposition":\s*"([a-z]+)"', inp)
                paths = re.findall(r'"capability_path":\s*(\[[^\]]*\])', inp)
                refs = re.findall(r'"precursor_refs":\s*(\[[^\]]*\])', inp)
                print(f"  IMPACT WRITE: dispositions={disp} paths={paths} precursor_refs={refs}")
            if '"threats"' in inp:
                print(f"  THREATS WRITE: {clip(inp, 320)}")
            issues = re.findall(r'"issues":\s*\[(.*?)\]', out)
            if issues:
                print(f"  VALIDATION ISSUES: {clip(issues[0], 400)}")
    print(f"matching traces={hits}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
