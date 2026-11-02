#!/usr/bin/env python3
"""Backfill a trial record's `stack_fingerprint` before the assessment.

The assessment gate refuses a verdicts file whose identity disagrees with the
trial record. The identity is the `eval_sha` and the `stack_fingerprint`. A
driver that launched with an empty fingerprint leaves the record without one,
so the assessor cannot produce a valid verdicts file. This script writes the
computed value into the record, atomically, and refuses to overwrite a
different non-empty value unless `--force` is given.

It changes metadata only: phases, ids, spend, and evidence are untouched.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("trial", type=Path, help="the trial.yaml path")
    parser.add_argument("fingerprint", help="the computed stack fingerprint")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    document = yaml.safe_load(args.trial.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SystemExit(f"{args.trial}: not a mapping")
    current = document.get("stack_fingerprint")
    fingerprint = args.fingerprint.strip()
    if not fingerprint:
        raise SystemExit("an empty fingerprint is not a backfill")
    if current and current != fingerprint and not args.force:
        raise SystemExit(
            f"{args.trial}: stack_fingerprint is already {current!r}; "
            "refusing to overwrite without --force"
        )
    document["stack_fingerprint"] = fingerprint
    temporary = args.trial.with_suffix(".yaml.tmp")
    temporary.write_text(
        yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
    )
    os.replace(temporary, args.trial)
    print(
        f"{args.trial}: eval_sha={document.get('eval_sha')} "
        f"worktree_dirty={document.get('worktree_dirty')} "
        f"stack_fingerprint={fingerprint}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
