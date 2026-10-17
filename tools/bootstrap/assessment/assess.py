#!/usr/bin/env python3
"""Deterministic quality assessment for a target's bootstrapped artifacts.

The shape validator (`tools/bootstrap/validate_data_dependencies.py`) is the
PASS/FAIL gate. This script grades the artifacts that pass: per-criterion
ordinal scales (0-4, anchors in `RUBRIC.md`), per-target metrics, and portfolio
aggregation with optional baseline deltas.

What is graded here is the DETERMINISTIC half of the rubric; the semantic half
(journey plausibility, contract discriminating power, threat-model coverage,
auth coherence) is judged by the LLM assessor protocol in
`llm_judge_prompt.md`, whose verdicts this script merges when a target carries
`assessment.yaml`.

Usage:
  PYTHONPATH=src python3 tools/bootstrap/assessment/assess.py <target_dir> [<target_dir> ...]
  PYTHONPATH=src python3 tools/bootstrap/assessment/assess.py --portfolio <kbs_root>
  PYTHONPATH=src python3 tools/bootstrap/assessment/assess.py --portfolio <kbs_root> \\
      --json out/portfolio.json --baseline out/baseline.json \\
      --staging eval/data-dependencies --groundtruth <groundtruth_dir>

Exit 0 always (assessment is not a gate; the validator is). Import performs no
I/O beyond reading the given paths.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Every criterion this script grades, in report order. The LLM-only criteria
# (L*) are listed for completeness; the judge produces them.
CRITERIA: list[tuple[str, str]] = [
    ("A1", "overview.structure"),
    ("A2", "overview.journeys"),
    ("A3", "overview.budget"),
    ("A4", "overview.grounding"),
    ("B1", "kb.scaffold"),
    ("B2", "kb.contracts"),
    ("B3", "kb.systems"),
    ("B4", "kb.roles"),
    ("C1", "surface.schema"),
    ("C2", "surface.edges"),
    ("C3", "surface.parity"),
    ("D1", "auth.structure"),
    ("E1", "notes.presence"),
    ("E2", "integrity.no_leak"),
    ("L1", "overview.journeys.plausibility"),
    ("L2", "overview.description.quality"),
    ("L3", "contracts.discriminating"),
    ("L4", "coverage.threat_model"),
    ("L5", "auth.coherence"),
]
LLM_CRITERIA = ("L1", "L2", "L3", "L4", "L5")

FAILING_SCALE = 1  # scale <= 1 is a failing criterion in the report

# Answer-key markers the eval integrity boundary forbids in bootstrap
# artifacts (the artifacts describe WHAT the application is, never WHAT breaks).
#
# HIGH PRECISION on purpose. Bare technical vocabulary is NOT leakage: "shell"
# in a KB means a UI shell ("SPA shell", "admin-shell"), "payload" means a JSON
# or event payload, and the sealed-boundary notes legitimately say that the
# `vulnerability/` directory was not read. What IS leakage: a CVE/CWE id, an
# exploit tool, an attack-class phrase ("template RCE"), a shell-access phrase,
# or a literal payload. The LLM assessor reads the ambiguous cases.
_LEAK_PATTERNS = (
    r"\bcve-\d{4}-\d+\b",
    r"\bcwe-\d+\b",
    r"\bmetasploit\b|\bsqlmap\b|\bnuclei\b",
    r"\breverse shell\b|\bwebshell\b|\bweb shell\b|\bbind shell\b|\bshell access\b",
    r"\bsql injection\b|\bcommand injection\b|\bcode injection\b"
    r"|\bpath traversal\b|\bdirectory traversal\b|\blocal file inclusion\b"
    r"|\bremote code execution\b|\brce\b",
    r"\bprivilege escalation\b",
    r"\bauth(?:entication)?\s+bypass\b",
    r"\b0day\b|\bzero-day\b|\bproof-of-concept\b|\bpoc\b",
    r"\b(?:attack|malicious|xss|sqli|injection)\s+payloads?\b|\bpayload\s*[:=]",
)
_SURFACE_REF_RE = re.compile(
    r"(/[\w{}\-./]*|https?://|\b(page|screen|form|menu|button|link|panel|"
    r"endpoint|route|tab|dialog|modal|field)\b)", re.IGNORECASE)
_PATHISH_RE = re.compile(r"/[\w{}\-./]+|https?://")
# A path/parameter leak in a contract: a URL, a route-ish leading slash in
# normal prose context, or a query-string assignment. A bilingual gloss
# ("留言/投稿") or a hyphenated word never matches.
_PATH_LEAK_RE = re.compile(
    r"https?://|(?:^|[\s(\"'\[`])/[A-Za-z0-9][\w\-./{}]*|[?&][A-Za-z_]\w*=")


def _validator():
    """Load the shape validator by path (tools/ is not a package)."""
    path = Path(__file__).resolve().parents[1] / "validate_data_dependencies.py"
    spec = importlib.util.spec_from_file_location("bootstrap_validator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _read_yaml(path: Path):
    try:
        return yaml.safe_load(_read(path))
    except yaml.YAMLError:
        return None


def _clamp(scale: int) -> int:
    return max(0, min(4, scale))


def _criterion(scale: int, metrics: dict | None = None, notes: list[str] | None = None) -> dict:
    return {"scale": _clamp(scale), "metrics": metrics or {}, "notes": notes or []}


# --- family A: the Overview ---------------------------------------------------

def assess_overview(target_dir: Path) -> dict[str, dict]:
    """A1-A4: the structured Overview's presence, shape, budget, grounding."""
    from polymerhus.analysis.overview import (  # noqa: PLC0415
        OVERVIEW_WORD_BUDGET,
        overview_word_count,
    )
    from polymerhus.analysis.scaffold import parse_overview  # noqa: PLC0415

    kb_text = _read(target_dir / "operator_kb.md")
    overview = parse_overview(kb_text)
    domain = overview.get("domain") or ""
    description = overview.get("description") or ""
    journeys = overview.get("journeys") or []

    fields = sum(bool(x) for x in (domain, description)) + (1 if journeys else 0)
    a1 = _criterion(
        0 if fields == 0 else {1: 2, 2: 3, 3: 4}[fields],
        {"fields_present": fields, "domain": domain,
         "n_journeys": len(journeys)},
    )

    steps = [len(j.get("steps") or []) for j in journeys]
    named = sum(bool(j.get("name")) for j in journeys)
    ok_journeys = sum(1 for n in steps if n >= 3)
    if not journeys:
        a2 = _criterion(0, {"n_journeys": 0})
    elif ok_journeys >= 2 and named == len(journeys):
        a2 = _criterion(4, {"n_journeys": len(journeys), "steps": steps})
    elif ok_journeys >= 2:
        a2 = _criterion(3, {"n_journeys": len(journeys), "steps": steps})
    elif ok_journeys == 1:
        a2 = _criterion(2, {"n_journeys": len(journeys), "steps": steps})
    else:
        a2 = _criterion(1, {"n_journeys": len(journeys), "steps": steps})

    words = overview_word_count(overview)
    if words == 0:
        a3 = _criterion(0, {"words": 0, "budget": OVERVIEW_WORD_BUDGET})
    elif words <= 150:
        a3 = _criterion(4, {"words": words, "budget": OVERVIEW_WORD_BUDGET})
    elif words <= OVERVIEW_WORD_BUDGET:
        a3 = _criterion(3, {"words": words, "budget": OVERVIEW_WORD_BUDGET})
    elif words <= int(OVERVIEW_WORD_BUDGET * 1.3):
        a3 = _criterion(2, {"words": words, "budget": OVERVIEW_WORD_BUDGET})
    else:
        a3 = _criterion(1, {"words": words, "budget": OVERVIEW_WORD_BUDGET})

    slug_tokens = _kb_identity_tokens(kb_text)
    steps_flat = [s for j in journeys for s in (j.get("steps") or [])]
    surface_hits = sum(1 for s in steps_flat if _SURFACE_REF_RE.search(s))
    identity_hits = sum(1 for s in steps_flat if _mentions_identity(s, slug_tokens))
    surface_frac = round(surface_hits / len(steps_flat), 2) if steps_flat else 0.0
    identity_frac = round(identity_hits / len(steps_flat), 2) if steps_flat else 0.0
    if not steps_flat:
        a4 = _criterion(0, {"surface_ref_frac": 0.0, "identity_ref_frac": 0.0})
    elif surface_frac == 1.0 and identity_frac >= 0.8:
        a4 = _criterion(4, {"surface_ref_frac": surface_frac,
                            "identity_ref_frac": identity_frac})
    elif surface_frac >= 0.8 and identity_frac >= 0.5:
        a4 = _criterion(3, {"surface_ref_frac": surface_frac,
                            "identity_ref_frac": identity_frac})
    elif surface_frac >= 0.5:
        a4 = _criterion(2, {"surface_ref_frac": surface_frac,
                            "identity_ref_frac": identity_frac})
    else:
        a4 = _criterion(1, {"surface_ref_frac": surface_frac,
                            "identity_ref_frac": identity_frac})
    return {"A1": a1, "A2": a2, "A3": a3, "A4": a4}


def _kb_identity_tokens(kb_text: str) -> set[str]:
    """Service slugs + System kinds named anywhere in the KB (identity tokens)."""
    from polymerhus.analysis.l1_curator import SYSTEM_KINDS  # noqa: PLC0415

    tokens: set[str] = {kind.lower() for kind, _ in SYSTEM_KINDS}
    in_services = False
    for line in kb_text.splitlines():
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            in_services = m.group(1).strip().lower() == "services"
            continue
        if in_services:
            h = re.match(r"^###\s+(.*)$", line)
            if h:
                slug = h.group(1).strip()
                if slug:
                    tokens.add(slug.lower())
    return tokens


def _mentions_identity(step: str, tokens: set[str]) -> bool:
    low = step.lower()
    for token in tokens:
        if not token:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", low):
            return True
    return False


# --- family B: the L1 KB ------------------------------------------------------

def assess_kb(target_dir: Path) -> dict[str, dict]:
    """B1-B4: scaffold parse, contract quality, systems, roles."""
    from polymerhus.analysis.l1_curator import SYSTEM_KINDS  # noqa: PLC0415

    path = target_dir / "operator_kb.md"
    kb_text = _read(path)
    if not kb_text:
        return {cid: _criterion(0, {}, ["operator_kb.md missing"])
                for cid in ("B1", "B2", "B3", "B4")}
    from polymerhus.analysis.scaffold import build_shells_from_path as build_shells  # noqa: PLC0415

    try:
        services, systems, dispositions = build_shells(path)
    except Exception as exc:  # noqa: BLE001
        return {cid: _criterion(0, {}, [f"scaffold parse failed: {exc}"])
                for cid in ("B1", "B2", "B3", "B4")}

    n_services, n_systems = len(services), len(systems)
    if n_services == 0:
        b1 = _criterion(0, {"n_services": 0, "n_systems": n_systems})
    else:
        b1 = _criterion(
            4 if n_systems >= 3 else 3 if n_systems == 2 else 2,
            {"n_services": n_services, "n_systems": n_systems,
             "dropped": len(dispositions or [])})

    contracts = [getattr(s, "service_contract", "") or "" for s in services]
    empties = sum(1 for c in contracts if not c.strip())
    leaks = sum(1 for c in contracts if _PATH_LEAK_RE.search(c))
    token_sets = [set(re.findall(r"[a-z]{4,}", c.lower())) for c in contracts]
    # Discriminating power: a contract that shares EVERY meaningful token with
    # the rest of the set cannot route anything. Parallel sibling services
    # (DingTalk vs WeChat notifiers, manufacturers vs suppliers) stay fine -
    # they each carry their own entity token.
    without_unique = 0
    for i, toks in enumerate(token_sets):
        others: set = set()
        for j, other in enumerate(token_sets):
            if j != i:
                others |= other
        if toks and not (toks - others):
            without_unique += 1
    max_overlap = 0.0
    near_dupes = 0
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            a, b = token_sets[i], token_sets[j]
            if a and b:
                jac = len(a & b) / len(a | b)
                max_overlap = max(max_overlap, jac)
                if jac >= 0.9:
                    near_dupes += 1
    metrics_b2 = {
        "n_contracts": len(contracts), "empty_contracts": empties,
        "path_leaks": leaks, "without_unique_token": without_unique,
        "near_duplicate_pairs": near_dupes,
        "max_pairwise_jaccard": round(max_overlap, 3),
    }
    # Contract HYGIENE is deterministic (empty, path-leaking, or byte-near-
    # duplicate contracts). Contract DISCRIMINATION - does the contract route a
    # raw endpoint to exactly one service? - is a semantic judgement and is
    # criterion L3, judged by the LLM assessor; `without_unique_token` and
    # `max_pairwise_jaccard` are reported here as its evidence base.
    if not contracts or empties == len(contracts):
        b2 = _criterion(0, metrics_b2, ["no contracts parsed"])
    elif leaks >= 2 or empties or near_dupes >= 2:
        b2 = _criterion(1, metrics_b2)
    elif leaks == 1 or near_dupes == 1:
        b2 = _criterion(2, metrics_b2)
    else:
        b2 = _criterion(4, metrics_b2)

    vocab = {kind for kind, _ in SYSTEM_KINDS}
    kinds = [getattr(s, "kind", "") for s in systems]
    in_vocab = sum(1 for k in kinds if k in vocab)
    multi_bullet = len(re.findall(r"^- description:", kb_text, flags=re.MULTILINE)) > max(1, n_systems)
    if not systems:
        b3 = _criterion(0, {"n_systems": 0})
    elif in_vocab == len(systems) and not multi_bullet:
        b3 = _criterion(4, {"n_systems": n_systems, "in_vocabulary": in_vocab})
    elif in_vocab >= max(1, len(systems) - 1):
        b3 = _criterion(3, {"n_systems": n_systems, "in_vocabulary": in_vocab})
    else:
        b3 = _criterion(2, {"n_systems": n_systems, "in_vocabulary": in_vocab})

    roles_section = re.search(r"^##\s+Roles\s*$(.*?)(^##\s|\Z)", kb_text,
                              flags=re.MULTILINE | re.DOTALL)
    roles = re.findall(r"^\s*-\s+\S", roles_section.group(1), flags=re.MULTILINE) \
        if roles_section else []
    b4 = _criterion(0 if not roles else (4 if len(roles) >= 2 else 3),
                    {"n_roles": len(roles)})
    return {"B1": b1, "B2": b2, "B3": b3, "B4": b4}


# --- family C: the l1-surface -------------------------------------------------

def assess_surface(target_dir: Path) -> dict[str, dict]:
    """C1-C3: schema (via the validator), edges, KB/surface parity."""
    validator = _validator()
    path = target_dir / "l1-surface.yaml"
    errors = validator.check_l1_surface(path)
    if not path.is_file():
        return {cid: _criterion(0, {}, [f"l1-surface.yaml missing: {errors}"])
                for cid in ("C1", "C2", "C3")}
    doc = _read_yaml(path) or {}
    units = doc.get("units") if isinstance(doc, dict) else None
    if not isinstance(units, list):
        return {cid: _criterion(0, {}, ["units is not a list"])
                for cid in ("C1", "C2", "C3")}

    c1 = _criterion(
        4 if not errors else 3 if len(errors) <= 1 else 2 if len(errors) <= 3 else 1,
        {"validator_errors": len(errors)}, errors[:5])

    orphans = 0
    edge_count = 0
    auth_services = auth_edges = 0
    for unit in units:
        if not isinstance(unit, dict):
            continue
        out_edges = unit.get("outbound_edges") or []
        in_edges = unit.get("inbound_edges") or []
        edge_count += len(out_edges) + len(in_edges)
        if unit.get("label") == "Service" and not out_edges and not in_edges:
            orphans += 1
        if (unit.get("props") or {}).get("exposure") == "authenticated":
            auth_services += 1
            if any((e or {}).get("rel") == "AUTHENTICATED_BY" for e in out_edges):
                auth_edges += 1
    orphan_frac = round(orphans / max(1, len(units)), 2)
    c2 = _criterion(
        4 if edge_count and orphan_frac == 0
        else 3 if orphan_frac <= 0.1 else 2 if orphan_frac <= 0.25 else 1,
        {"n_units": len(units), "n_edges": edge_count,
         "orphan_frac": orphan_frac})

    from polymerhus.analysis.scaffold import build_shells_from_path as build_shells  # noqa: PLC0415

    try:
        services, systems, _d = build_shells(target_dir / "operator_kb.md")
        kb_slugs = {getattr(s, "business_function_slug", "") for s in services}
        kb_kinds = {getattr(s, "kind", "") for s in systems}
    except Exception:  # noqa: BLE001 - parity degrades, never raises
        kb_slugs, kb_kinds = set(), set()
    surface_slugs = {str((u.get("identity") or {}).get("business_function_slug"))
                     for u in units if isinstance(u, dict) and u.get("label") == "Service"}
    surface_kinds = {str((u.get("identity") or {}).get("kind"))
                     for u in units if isinstance(u, dict) and u.get("label") == "System"}
    missing = sorted(s for s in kb_slugs - surface_slugs if s and s != "None")
    auth_frac = round(auth_edges / auth_services, 2) if auth_services else 1.0
    c3 = _criterion(
        4 if not missing and auth_frac == 1.0
        else 3 if not missing and auth_frac >= 0.8
        else 2 if len(missing) <= 1
        else 1,
        {"kb_services_missing_in_surface": missing,
         "auth_edge_coverage": auth_frac,
         "extra_surface_services": sorted(s for s in surface_slugs - kb_slugs if s and s != "None")})
    return {"C1": c1, "C2": c2, "C3": c3}


# --- family D: the auth bundle ------------------------------------------------

def assess_auth(project_dir: Path) -> dict[str, dict]:
    """D1: the AuthContext + authn skill (shape, via the validator)."""
    validator = _validator()
    errors = validator.check_auth(project_dir)
    overview = _read_yaml(project_dir / "auth" / "overview.yaml") or {}
    credentials = _read_yaml(project_dir / "auth" / "credentials.yaml") or {}
    accounts = credentials.get("accounts") if isinstance(credentials, dict) else {}
    n_accounts = len(accounts) if isinstance(accounts, dict) else 0
    skill = project_dir / "skills" / "authn" / "SKILL.md"
    if errors:
        d1 = _criterion(1 if skill.is_file() or n_accounts else 0,
                        {"validator_errors": len(errors), "n_accounts": n_accounts},
                        errors[:5])
    else:
        d1 = _criterion(
            4 if n_accounts >= 2 and skill.is_file()
            else 3 if n_accounts >= 1
            else 2,  # valid empty bundle = an unauthenticated target
            {"n_accounts": n_accounts,
             "skill_present": skill.is_file(),
             "overview_present": bool(overview)})
    return {"D1": d1}


# --- family E: notes + integrity ---------------------------------------------

def assess_notes(target_dir: Path, *, groundtruth_dir: Path | None = None) -> dict[str, dict]:
    """E1-E2: research artifacts present; no answer-key leakage."""
    surface_map = _read(target_dir / "surface-map.md")
    notes = _read(target_dir / "research-notes.md")
    endpoints = len(set(_PATHISH_RE.findall(surface_map)))
    e1 = _criterion(
        4 if endpoints >= 10 and len(notes) >= 500
        else 3 if surface_map and notes
        else 2 if surface_map or notes
        else 0,
        {"endpoint_tokens": endpoints, "surface_map_chars": len(surface_map),
         "research_notes_chars": len(notes)})

    markers = list(_LEAK_PATTERNS)
    if groundtruth_dir is not None:
        gt_target = groundtruth_dir / target_dir.name
        if gt_target.is_dir():
            for p in gt_target.iterdir():
                if p.is_dir():
                    token = re.escape(p.name.replace("-", " "))
                    markers.append(rf"\b{token}\b")
    hits: list[str] = []
    for name, text in (("operator_kb.md", _read(target_dir / "operator_kb.md")),
                       ("surface-map.md", surface_map),
                       ("research-notes.md", notes)):
        for pattern in markers:
            for m in re.finditer(pattern, text, flags=re.IGNORECASE):
                line = text[: m.start()].count("\n") + 1
                hits.append(f"{name}:{line}: {m.group(0)!r}")
    e2 = _criterion(0 if hits else 4, {"marker_hits": len(hits)}, hits[:8])
    return {"E1": e1, "E2": e2}


# --- per-target and portfolio -------------------------------------------------

def assess_target(target_dir: Path, *, staging_dir: Path | None = None,
                  groundtruth_dir: Path | None = None) -> dict:
    """Run every deterministic probe for one target (fail-open per family)."""
    result: dict = {"target": target_dir.name}
    probes = (
        ("A", lambda: assess_overview(target_dir)),
        ("B", lambda: assess_kb(target_dir)),
        ("C", lambda: assess_surface(target_dir)),
        ("D", lambda: assess_auth(staging_dir or target_dir)),
        ("E", lambda: assess_notes(target_dir, groundtruth_dir=groundtruth_dir)),
    )
    for name, probe in probes:
        try:
            result.update(probe())
        except Exception as exc:  # noqa: BLE001 - one family never sinks the run
            result[f"{name}-error"] = str(exc)
    judged = _read_yaml(target_dir / "assessment.yaml")
    if isinstance(judged, dict):
        lv = judged.get("criteria") or {}
        for cid in LLM_CRITERIA:
            verdict = lv.get(cid)
            if isinstance(verdict, dict) and "scale" in verdict:
                result[cid] = {"scale": _clamp(int(verdict["scale"])),
                               "metrics": {}, "notes": [
                                   str(verdict.get("evidence", ""))[:300]]}
    result["overall"] = overall_scale(result)
    return result


def overall_scale(row: dict) -> float:
    """The target's mean scale over every criteria that has a verdict."""
    scales = [row[cid]["scale"] for cid, _title in CRITERIA
              if isinstance(row.get(cid), dict) and "scale" in row[cid]]
    return round(sum(scales) / len(scales), 2) if scales else 0.0


def _failing(row: dict) -> list[str]:
    out = []
    for cid, title in CRITERIA:
        cell = row.get(cid)
        if isinstance(cell, dict) and cell.get("scale", 4) <= FAILING_SCALE:
            note = "; ".join(cell.get("notes") or [])
            out.append(f"{row['target']}: {cid} {title} (scale {cell['scale']})"
                       + (f" - {note}" if note else ""))
    return out


def portfolio_report(rows: list[dict], *, baseline: dict | None = None) -> str:
    """A markdown portfolio report over the per-target rows."""
    lines = ["# Bootstrap artifact assessment - portfolio", ""]
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append(f"Targets: {len(rows)}")
    if baseline:
        lines.append(f"Baseline: {baseline.get('generated', 'unknown')}")
    lines.append("")
    header = "| criterion | mean | min | " + " | ".join(r["target"] for r in rows) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (3 + len(rows)))
    for cid, title in CRITERIA:
        scales = [r[cid]["scale"] for r in rows
                  if isinstance(r.get(cid), dict) and "scale" in r[cid]]
        if not scales:
            continue
        mean = round(sum(scales) / len(scales), 2)
        cells = []
        for r in rows:
            cell = r.get(cid)
            cells.append(str(cell["scale"]) if isinstance(cell, dict) else "-")
        lines.append(f"| {cid} {title} | {mean} | {min(scales)} | "
                     + " | ".join(cells) + " |")
    means = [r["overall"] for r in rows]
    lines.append(f"| **overall** | **{round(sum(means) / len(means), 2) if means else 0}** | "
                 f"**{min(means) if means else 0}** | "
                 + " | ".join(f"**{m}**" for m in means) + " |")
    failing = [f for r in rows for f in _failing(r)]
    lines += ["", "## Failing criteria (scale <= 1)", ""]
    lines += [f"- {f}" for f in failing] or ["- (none)"]
    if baseline:
        base_rows = {r["target"]: r for r in baseline.get("targets", [])}
        lines += ["", "## Deltas vs baseline", ""]
        lines.append("| target | overall | delta |")
        lines.append("|---|---|---|")
        for r in rows:
            base = base_rows.get(r["target"])
            if base is None:
                lines.append(f"| {r['target']} | {r['overall']} | (new) |")
            else:
                delta = round(r["overall"] - base.get("overall", 0), 2)
                lines.append(f"| {r['target']} | {r['overall']} | {delta:+} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("targets", nargs="*", help="target directory(ies)")
    ap.add_argument("--portfolio", metavar="KBS_ROOT",
                    help="assess every child directory of KBS_ROOT")
    ap.add_argument("--staging", metavar="STAGING_ROOT",
                    help="staging data root for the auth bundle "
                         "(<STAGING_ROOT>/<target>/{auth,skills})")
    ap.add_argument("--groundtruth", metavar="GROUNDTRUTH_ROOT",
                    help="ground-truth root; per-target vuln names extend the leak scan")
    ap.add_argument("--json", metavar="OUT", help="write the full result JSON")
    ap.add_argument("--baseline", metavar="PREV_JSON",
                    help="a previous result JSON to diff the portfolio against")
    args = ap.parse_args(argv)

    dirs = [Path(d) for d in args.targets]
    if args.portfolio:
        dirs += [p for p in sorted(Path(args.portfolio).iterdir()) if p.is_dir()]
    if not dirs:
        ap.error("no targets given (pass directories or --portfolio <kbs_root>)")

    rows = [assess_target(
        d,
        staging_dir=(Path(args.staging) / d.name) if args.staging else None,
        groundtruth_dir=Path(args.groundtruth) if args.groundtruth else None,
    ) for d in dirs]
    baseline = None
    if args.baseline and Path(args.baseline).is_file():
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    report = portfolio_report(rows, baseline=baseline)
    print(report)
    if args.json:
        payload = {
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "criteria": [cid for cid, _t in CRITERIA],
            "targets": rows,
        }
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(f"JSON written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
