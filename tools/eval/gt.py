#!/usr/bin/env python3
"""gt.py - the light eval harness's ground-truth primitive.

Reads a WebExploitBench challenge's ground truth (challenge.json +
vulnerability/*/metadata.json) and prints the per-vuln table the oracle
judges against. The table is the JUDGE's input only; it must never reach
the polymerhus pipeline (the operator_kb stays neutral, no vuln leak).

Usage:
  gt.py <target|challenge-dir> [--json]

The argument is a target name resolved under EVAL_WEB_DIR (default
~/WebExploitBench) or a challenge directory path.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

DEFAULT_WEB_DIR = Path.home() / "WebExploitBench"


def load_challenge(challenge_dir: Path) -> tuple[dict, list[dict]]:
    challenge = json.loads((challenge_dir / "challenge.json").read_text())
    vulns: list[dict] = []
    for entry in challenge.get("vulnerabilities", []):
        vuln_id = entry["vuln_id"]
        meta_path = challenge_dir / "vulnerability" / vuln_id / "metadata.json"
        meta = json.loads(meta_path.read_text())
        vulns.append({
            "vuln_id": vuln_id,
            "scoring": entry.get("scoring", []),
            "location": meta.get("Location", ""),
            "type": meta.get("Vulnerability Type", ""),
        })
    return challenge, vulns


def resolve_challenge_dir(target: str) -> Path:
    root = Path(os.environ.get("EVAL_WEB_DIR", DEFAULT_WEB_DIR))
    candidate = Path(target)
    if candidate.is_dir() and (candidate / "challenge.json").exists():
        return candidate
    resolved = root / target
    if not (resolved / "challenge.json").exists():
        sys.exit(f"gt.py: unknown target {target!r} (no {resolved / 'challenge.json'})")
    return resolved


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("target", help="target name (under EVAL_WEB_DIR) or challenge dir")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    challenge_dir = resolve_challenge_dir(args.target)
    challenge, vulns = load_challenge(challenge_dir)

    if args.json:
        print(json.dumps({
            "challenge_id": challenge.get("id"),
            "description": challenge.get("description", ""),
            "agent_input": challenge.get("agent_input", {}),
            "internal_port": challenge.get("internal_port"),
            "vulnerabilities": vulns,
        }, indent=2))
        return 0

    print(f"challenge: {challenge.get('id')}  ({challenge_dir})")
    print(f"{'vuln_id':<14} {'Location':<54} Type")
    for v in vulns:
        print(f"{v['vuln_id']:<14} {v['location']:<54} {v['type']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())