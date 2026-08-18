#!/usr/bin/env python3
"""Regenerate the fault-KB fold-family-view snapshot doc (#66).

Out-of-band curation doc: a deterministic human-facing view of the folded
catalogue - the capture/recipe families, the SPLIT entries, the keep-standalone
orphans, and the second-order selection structure. Read-only over the committed
catalogue artifact (never touches runtime code):

    python tools/hunting/fold_family_view.py \
        --catalogue src/polymerhus/attack/hunting/data/fault-kb.yaml \
        --out docs/design/hunting-66-fold-family-view.md
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

import yaml

_HEADER = """\
# Hunting #66 - fault-KB aggregation view (post-fold, post-critic, post-squeeze)

Machine-generated from the catalogue (`tools/hunting/fold_family_view.py` over
`src/polymerhus/attack/hunting/data/fault-kb.yaml`), not hand-maintained.
Regenerate with `python tools/hunting/fold_family_view.py --catalogue
src/polymerhus/attack/hunting/data/fault-kb.yaml --out
docs/design/hunting-66-fold-family-view.md`.

- Catalogue: {total} entries; selection tier (matching loop): {selection}; folded recipes: {recipes}.
- Selection tier: {abstraction_summary} ({splits} splits + {standalone} keep-standalone orphans among the {variant_compound} Variant/Compound).
"""


def render(rows: list[dict], split_ids: set[str]) -> str:
    by_id = {r["fault_id"]: r for r in rows}
    recipes = [r for r in rows if r["fold_parent"]]
    selection = [r for r in rows if not r["fold_parent"]]

    families: dict[str, list[dict]] = defaultdict(list)
    for r in sorted(recipes, key=lambda e: e["fault_id"]):
        families[r["fold_parent"]].append(r)

    abstraction = Counter(r["abstraction"] for r in selection)
    variant_compound = [r for r in selection
                        if r["abstraction"] in ("Variant", "Compound")]
    splits = [r for r in variant_compound if r["fault_id"] in split_ids]
    standalone = [r for r in variant_compound if r["fault_id"] not in split_ids]
    abstraction_summary = " / ".join(
        f"{abstraction[c]} {c}" for c in
        ("Base", "Variant", "Class", "Compound") if abstraction[c])

    parts = [_HEADER.format(
        total=len(rows), selection=len(selection), recipes=len(recipes),
        abstraction_summary=abstraction_summary, splits=len(splits),
        standalone=len(standalone), variant_compound=len(variant_compound))]

    parts.append("## 1. Fold families "
                 f"({len(families)} captures, {len(recipes)} folded recipes)")
    parts.append("")
    for fp in sorted(families):
        cap = by_id[fp]
        desc = _brief(_materialisation_desc(cap))
        parts.append(f"### {fp} {cap['name']} [{cap['abstraction']}] "
                     f"- capture; {len(families[fp])} recipes"
                     + (f" - {desc}" if desc else ""))
        for r in families[fp]:
            parts.append(f"- {r['fault_id']} {r['name']}")
        parts.append("")

    parts.append("## 2. SPLIT entries (critic: distinct fault class, "
                 "own selection entry)")
    parts.append("")
    for r in splits:
        parts.append(f"- {r['fault_id']} {r['name']} [{r['abstraction']}]")
    parts.append("")

    parts.append("## 3. KEEP-STANDALONE orphans (critic: no promotable "
                 "capture)")
    parts.append("")
    for r in standalone:
        parts.append(f"- {r['fault_id']} {r['name']} [{r['abstraction']}]")
    parts.append("")

    parts.append("## 4. Selection-tier View-1000 hierarchy "
                 "(second-order structure)")
    parts.append("")
    parts.append("Squeeze pass note: the 2026-08-17 squeeze (51 omits, 14 "
                 "generalises, 254 -> 203 entries) removed the recon-trivial, "
                 "naive, and framework-named faults; fold families now "
                 f"number {len(families)} captures over {len(recipes)} recipes. "
                 "The 2026-08-18 operator relevance pass (33 additional omits "
                 "and 5 `fold_to` taxonomy corrections, 203 -> 170 entries) "
                 "collapsed the traversal family onto CWE-22 (its absolute, "
                 "relative, path-equivalence, and link-following siblings all "
                 "fold there regardless of View-1000 structure) and folded "
                 "CWE-641 under CWE-73. "
                 "See docs/design/hunting-66-fault-omit-critique.md.")
    parts.append("")
    return "\n".join(parts)


def _materialisation_desc(row: dict) -> str:
    """The row's brief materialisation description (the rich NL a probe
    materialises against in the hunt-orchestrator prompt), '' when absent."""
    mat = row.get("materialisation") or {}
    desc = mat.get("description") or mat.get("extended_description") or ""
    return str(desc).replace("\n", " ").strip()


def _brief(text: str, limit: int = 180) -> str:
    """The first sentence of a description, truncated to `limit` chars."""
    if not text:
        return ""
    head = text.split(". ")[0] if ". " in text else text
    if not head.endswith("."):
        head += "."
    return head if len(head) <= limit else head[: limit - 1].rstrip() + "..."


def load_split_ids(authoring: Path) -> set[str]:
    """The authoring sidecar's SPLIT markers (70-fold-amendments.yaml): the
    Variant/Compound selection entries the overlap-critic judged genuinely
    distinct fault classes."""
    split_ids: set[str] = set()
    for path in sorted(authoring.glob("*.yaml")):
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        for fault_id, spec in (data.get("entries") or {}).items():
            if isinstance(spec, dict) and spec.get("split"):
                split_ids.add(fault_id)
    return split_ids


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate the fault-KB fold-family-view snapshot doc.")
    parser.add_argument("--catalogue", required=True,
                        help="the committed fault-kb.yaml path")
    parser.add_argument("--authoring", required=True,
                        help="the authoring sidecar directory "
                             "(for the SPLIT markers)")
    parser.add_argument("--out", required=True,
                        help="the doc file to write")
    args = parser.parse_args(argv)

    with open(args.catalogue, encoding="utf-8") as fh:
        rows = yaml.safe_load(fh)
    out = Path(args.out)
    out.write_text(render(rows, load_split_ids(Path(args.authoring))),
                   encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
