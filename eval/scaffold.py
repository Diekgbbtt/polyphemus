#!/usr/bin/env python3
"""scaffold.py - the deterministic L1 skeleton scaffold (the eval's primary
bootstrapping path).

The LLM bootstrap (`POST /bootstrap`) is non-deterministic: two LLM calls per
trial, run-to-run skeleton drift (AMV-12/13), cost and latency. This utility
replaces it for the eval: it parses the PRECOMPUTED per-target operator_kb.md
(services, systems, roles) into the platform's OWN `ServiceShell`/`SystemShell`
shapes and writes the skeleton through the SAME projection and sole-writer the
LLM bootstrap uses (`shells_to_batch` + `l1_curate`) - deterministically,
without an LLM call.

The parser and shell builder live in the PLATFORM
(`polymerhus.analysis.scaffold`), so the app API's data-dependency L1 endpoint
and this CLI run the identical deterministic path; this script is the thin CLI
wrapper. The system kinds in the KB are free-form mechanism names; they are
mapped onto the controlled `SYSTEM_KINDS` vocabulary by `KIND_MAP` (keyword
match after an exact vocabulary hit). Unmappable mechanisms are DROPPED with a
warning, mirroring the platform's own out-of-vocabulary gate - a mechanism the
L1 vocabulary does not speak is context, never a skeleton node.

Usage:
  scaffold.py <project_id> --kb <operator_kb.md> [--dry-run]

Run host-side from the repo root with PYTHONPATH=src and the .env in-network
view (NEO4J_URI=bolt://localhost:7687), mirroring tools/eval_bootstrapper.sh.
`--dry-run` parses the KB and prints the shells and dispositions WITHOUT
writing anything (stack-free verification).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The deterministic scaffold is a PLATFORM capability now (the app API's L1
# data-dependency endpoint reuses it); this script is the eval-side CLI over it.
from polymerhus.analysis.scaffold import (
    KB_SECTIONS,
    KIND_MAP,
    build_shells_from_path,
    map_system_kind,
    parse_kb,
    system_kinds,
)

# Back-compat alias: earlier eval callers imported SYSTEM_KINDS from this module.
SYSTEM_KINDS = system_kinds()

# The eval-side path-based entry point (validate_data_dependencies.py and the CLI
# call it with a Path); the platform module owns the text-based core.
build_shells = build_shells_from_path

# Re-exported so the eval-side parser surface is unchanged by the move into the
# platform module; tags the imports as used (pyflakes honors __all__).
__all__ = [
    "KB_SECTIONS",
    "KIND_MAP",
    "SYSTEM_KINDS",
    "build_shells",
    "build_shells_from_path",
    "map_system_kind",
    "parse_kb",
    "system_kinds",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project_id")
    ap.add_argument("--kb", required=True, help="the operator_kb.md path")
    ap.add_argument("--dry-run", action="store_true",
                    help="parse and print the shells without writing")
    args = ap.parse_args()

    kb_path = Path(args.kb)
    if not kb_path.exists():
        sys.exit(f"scaffold.py: no KB at {kb_path}")

    service_shells, system_shells, dispositions = build_shells_from_path(kb_path)

    for kind, name, outcome, note in dispositions:
        print(f"scaffold.py: {kind} {name}: {outcome} - {note}")

    print(f"scaffold.py: parsed {len(service_shells)} services, "
          f"{len(system_shells)} systems, from {kb_path}")

    if not service_shells:
        sys.exit("scaffold.py: zero services parsed - a broken KB is a blocked "
                 "scaffold, the trial must not proceed (mirrors the bootstrap "
                 "fail-closed rule)")

    if args.dry_run:
        for s in service_shells:
            print(f"  service {s.business_function_slug} exposure={s.exposure}")
        for s in system_shells:
            extra = f" roles={s.roles}" if s.roles else ""
            print(f"  system  {s.kind} <{s.discriminator}>{extra}")
        return 0

    from polymerhus.analysis.scaffold import scaffold_project

    merged_services, merged_systems = scaffold_project(args.project_id, kb_path.read_text())
    print(f"scaffold.py: wrote {merged_services} services, {merged_systems} "
          f"systems to project {args.project_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
