#!/usr/bin/env python3
"""Per-pod lifetime audit for one hunting run.

For every pod directory: dispatch anchor (variants/ dir mtime), first and last
experiment-log write, export time, terminal, iterations, probe count, and the sum
of tool duration_ms.  The tool-time ratio separates "the pod worked for an hour"
from "the pod waited for an hour".

Usage:
  python3 audit_pod_lifetimes.py --project-root <root> [--json]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

import yaml


def load(path: pathlib.Path) -> dict:
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-root", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = pathlib.Path(args.project_root)
    pod_root = root / "hunting/test-executor-pod"
    spec_root = root / "hunting/hunter/test-specs"

    spec_units: dict[str, str] = {}
    for directory in spec_root.glob("*"):
        if not directory.is_dir():
            continue
        for candidate in directory.glob("*.yaml"):
            if candidate.name.startswith("spec-") or candidate.name in ("notes.yaml",):
                continue
            data = load(candidate)
            unit = (data.get("provenance") or {}).get("unit_id") or (data.get("target_identity") or {}).get("unit_id")
            if unit:
                spec_units[directory.name] = str(unit)
                break

    rows: list[dict] = []
    for directory in sorted(pod_root.glob("*")):
        if not directory.is_dir():
            continue
        exports = [p for p in directory.glob("*.yaml") if not p.name.endswith(".resume.yaml")]
        logs = sorted((directory / "experiment-log").glob("*.yaml")) if (directory / "experiment-log").is_dir() else []
        variants = directory / "variants"
        # The session anchor is the FIRST artifact the pod writes.  The variants
        # directory mtime moves when a later variant lands, so it must not be
        # used: a two-iteration pod would look 80s long while its session ran an
        # hour (observed: two "short" watchdogs that were only anchor artifacts).
        artifacts = list(variants.glob("*.yaml")) if variants.is_dir() else []
        artifacts += logs
        anchor = min((p.stat().st_mtime for p in artifacts), default=directory.stat().st_mtime)
        probes = 0
        tool_ms = 0.0
        for log in logs:
            data = load(log)
            for obs in data.get("raw_observations") or []:
                if isinstance(obs, dict):
                    probes += 1
                    tool_ms += float(obs.get("duration_ms") or 0.0)
        export = exports[0] if exports else None
        export_ts = export.stat().st_mtime if export else None
        evidence = (load(export).get("evidence") or {}) if export else {}
        rows.append(
            {
                "spec_dir": directory.name,
                "unit": spec_units.get(directory.name, "?"),
                "anchor": iso(anchor),
                "first_log": iso(min(p.stat().st_mtime for p in logs)) if logs else None,
                "last_log": iso(max(p.stat().st_mtime for p in logs)) if logs else None,
                "export": iso(export_ts) if export_ts else None,
                "wall_s": round((export_ts or anchor) - anchor, 1),
                "terminal": str(evidence.get("terminal_reason") or "none"),
                "iterations": evidence.get("iterations"),
                "probes": probes,
                "tool_s": round(tool_ms / 1000.0, 1),
                "tool_ratio": round(tool_ms / 1000.0 / max((export_ts or anchor) - anchor, 1), 3),
                "recording": export is not None,
            }
        )

    if args.json:
        print(json.dumps(rows, indent=1))
        return 0

    print(f"{'spec_dir':58s} {'terminal':26s} {'it':>3s} {'probes':>6s} {'wall_s':>7s} {'tool_s':>7s} {'ratio':>6s}")
    for row in rows:
        print(
            f"{row['spec_dir'][:58]:58s} {row['terminal'][:26]:26s} {str(row['iterations']):>3s} "
            f"{row['probes']:6d} {row['wall_s']:7.0f} {row['tool_s']:7.0f} {row['tool_ratio']:6.3f}"
        )
    by_terminal: dict[str, list[dict]] = {}
    for row in rows:
        by_terminal.setdefault(row["terminal"], []).append(row)
    print()
    for terminal, group in sorted(by_terminal.items()):
        wall = [r["wall_s"] for r in group]
        ratio = [r["tool_ratio"] for r in group]
        probes = [r["probes"] for r in group]
        print(
            f"{terminal:26s} n={len(group):2d} wall_med={sorted(wall)[len(wall)//2]:6.0f} "
            f"tool_med={sorted(r['tool_s'] for r in group)[len(group)//2]:6.0f} "
            f"ratio_med={sorted(ratio)[len(ratio)//2]:5.3f} probes_med={sorted(probes)[len(probes)//2]}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
