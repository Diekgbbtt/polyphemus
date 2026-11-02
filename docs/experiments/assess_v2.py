#!/usr/bin/env python3
"""Assess a steel_crawl_proto_v2 run against the functional requirements.

Reads the persisted evidence only. Writes assessment.json and assessment.md.
"""
from __future__ import annotations

import json
import math
import sys
import urllib.parse
from collections import Counter
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def load(run_dir: Path) -> dict:
    metrics = {}
    if (run_dir / "metrics.json").exists():
        metrics = json.loads((run_dir / "metrics.json").read_text())
    manifest = {}
    if (run_dir / "manifest.json").exists():
        manifest = json.loads((run_dir / "manifest.json").read_text())
    return {
        "dir": run_dir,
        "metrics": metrics,
        "manifest": manifest,
        "pages": read_jsonl(run_dir / "pages.jsonl"),
        "actions": read_jsonl(run_dir / "actions.jsonl"),
        "forms": read_jsonl(run_dir / "forms.jsonl"),
        "safety": read_jsonl(run_dir / "safety.jsonl"),
        "removed": read_jsonl(run_dir / "removed.jsonl"),
        "flows": read_jsonl(run_dir / "flows.jsonl"),
        "candidates": read_jsonl(run_dir / "candidates.jsonl"),
        "values": read_jsonl(run_dir / "values.jsonl"),
    }


UNSAFE_ENDPOINTS = {
    ("POST", "/api/login"),
    ("GET", "/api/logout"),
    ("PUT", "/api/admin/user"),
    ("POST", "/api/admin/user"),
    ("PUT", "/api/admin/user/password"),
    ("POST", "/api/admin/user/password"),
    ("PUT", "/api/admin/user/status"),
    ("POST", "/api/admin/user/status"),
    ("POST", "/api/admin/role"),
    ("PUT", "/api/admin/role"),
    ("POST", "/api/admin/role/status"),
    ("PUT", "/api/admin/role/status"),
    ("POST", "/api/admin/role/menu"),
    ("PUT", "/api/admin/role/menu"),
    ("POST", "/api/admin/content/books/delete"),
}
UNSAFE_PREFIXES = {
    ("DELETE", "/api/admin/content/article/"),
}


def is_unsafe_endpoint(method: str, path: str) -> bool:
    m = (method or "").upper()
    p = path or ""
    if (m, p) in UNSAFE_ENDPOINTS:
        return True
    return any(m == um and p.startswith(up) for um, up in UNSAFE_PREFIXES)


def ratio(a: int, b: int) -> float | None:
    return (a / b) if b else None


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def assess(run_dir: Path) -> dict:
    r = load(run_dir)
    raw_forms = r["forms"]
    forms = [f for f in raw_forms if f.get("skipped") != "duplicate"]
    skipped_duplicates = len(raw_forms) - len(forms)
    safety = r["safety"]
    actions = r["actions"]
    flows = r["flows"]
    manifest = r["manifest"]
    metrics = r["metrics"]
    has_truth = any("ground_truth" in s for s in safety)

    fields_total = sum(len(f.get("fields", [])) for f in forms)
    fields_filled = sum(1 for f in forms for field in f.get("fields", []) if field.get("ok"))
    network_fields = sum(len(f.get("network_fields", [])) for f in forms)
    method_mismatches = sum(
        1 for f in forms
        if f.get("method") and f.get("request_method")
        and str(f.get("method")).upper() != str(f.get("request_method")).upper()
    )
    safety_counts = Counter(s.get("ground_truth") for s in safety)
    unsafe_actions = [
        a for a in actions
        if a.get("outcome") == "ok" and a.get("ground_truth") not in (None, "safe")
    ]
    xhr = [f for f in flows if f.get("resource_type") in ("XHR", "Fetch")]
    xhr_with_response = [f for f in xhr if f.get("status") is not None]
    xhr_with_body = [f for f in xhr if f.get("response_body_sha256")]
    phases = Counter(f.get("phase") or "unknown" for f in flows)
    endpoints = manifest.get("endpoints", [])
    observed = [e for e in endpoints if e.get("provenance") == "observed"]
    declared = [e for e in endpoints if e.get("provenance") == "declared"]
    observed_unsafe = [e for e in observed if is_unsafe_endpoint(e.get("method"), e.get("path"))]
    declared_unsafe = [e for e in declared if is_unsafe_endpoint(e.get("method"), e.get("path"))]
    bootstrap_unsafe = [
        f for f in flows
        if f.get("phase") == "bootstrap"
        and is_unsafe_endpoint(f.get("method"), urllib.parse.urlsplit(f.get("url", "")).path)
    ]
    crawl_unsafe = [
        f for f in flows
        if f.get("phase") == "crawl"
        and is_unsafe_endpoint(f.get("method"), urllib.parse.urlsplit(f.get("url", "")).path)
    ]
    removed_declared = [d for d in r.get("declared", [])]
    removed_modal_openers = [
        s for s in safety
        if s.get("type") in ("BUTTON", "ROLE_BUTTON")
        and any(w in str(s.get("name") or "") for w in ("添加", "编辑", "批量添加", "新增"))
    ]
    manifest_keys = set(manifest.keys()) if manifest else set()
    required_manifest = {"schema_version", "run", "endpoints", "parameters", "scripts", "realtime", "errors", "stats"}
    invariants = {
        "auth_precondition_authenticated": (metrics.get("quality", {}).get("auth_classification") == "authenticated"),
        "unsafe_actions_executed_zero": (len(unsafe_actions) == 0) if has_truth else None,
        "anonymous_api_requests_zero": metrics.get("quality", {}).get("anonymous_api_requests") == 0,
        "manifest_v2_keys": required_manifest.issubset(manifest_keys),
        "crawl_unsafe_endpoints_zero": len(observed_unsafe) == 0,
        "bootstrap_unsafe_flows_isolated": len(bootstrap_unsafe) >= 0,
        "declared_unsafe_not_observed": all(
            (e.get("method"), e.get("path")) not in {(o.get("method"), o.get("path")) for o in observed}
            for e in declared_unsafe
        ),
        "form_success": all(f.get("success") for f in forms) if forms else None,
        "xhr_response_complete": (len(xhr_with_response) == len(xhr)) if xhr else None,
    }
    out = {
        "run": str(run_dir),
        "counts": {
            "pages": len(r["pages"]), "actions": len(actions), "forms": len(forms),
            "form_skips": skipped_duplicates,
            "removed": len(safety), "flows": len(flows), "xhr_fetch": len(xhr),
            "endpoints": len(endpoints), "observed_endpoints": len(observed),
            "declared_endpoints": len(declared),
        },
        "forms": {
            "attempted": len(forms),
            "succeeded": sum(1 for f in forms if f.get("success")),
            "success_rate": ratio(sum(1 for f in forms if f.get("success")), len(forms)),
            "skipped_duplicate": skipped_duplicates,
            "fields_total": fields_total,
            "fields_filled": fields_filled,
            "field_coverage": ratio(fields_filled, fields_total),
            "network_fields": network_fields,
            "network_field_coverage": ratio(network_fields, fields_total),
            "method_mismatches": method_mismatches,
            "records": [
                {"submit": f.get("submit_text"), "synthetic": f.get("synthetic"),
                 "success": f.get("success"), "status": f.get("http_status"),
                 "url": f.get("request_url"), "method": f.get("method"),
                 "request_method": f.get("request_method"),
                 "fields": len(f.get("fields", [])),
                 "network_fields": f.get("network_fields")}
                for f in forms
            ],
        },
        "safety": {
            "removed": len(safety),
            "by_ground_truth": dict(safety_counts),
            "unsafe_removed": (sum(1 for s in safety if s.get("ground_truth") != "safe")
                               if has_truth else None),
            "safe_removed": (sum(1 for s in safety if s.get("ground_truth") == "safe")
                             if has_truth else None),
            "precision": (ratio(sum(1 for s in safety if s.get("ground_truth") != "safe"), len(safety))
                          if has_truth else None),
            "removed_modal_openers": len(removed_modal_openers),
            "records": [
                {"type": s.get("type"), "name": s.get("name"),
                 "truth": s.get("ground_truth"), "source": s.get("source")}
                for s in safety
            ],
        },
        "actions": {
            "total": len(actions),
            "navigated": sum(1 for a in actions if a.get("navigated")),
            "local_state": sum(1 for a in actions if a.get("impact") == "local_state"),
            "navigate": sum(1 for a in actions if a.get("impact") == "navigate"),
            "errors": sum(1 for a in actions if a.get("outcome") == "error"),
            "unsafe_executed": len(unsafe_actions) if has_truth else None,
            "no_op_local_state_rate": metrics.get("quality", {}).get("no_op_local_state_rate"),
            "no_op_all_actions_rate": metrics.get("quality", {}).get("no_op_all_actions_rate"),
        },
        "capture": {
            "phases": dict(phases),
            "xhr_fetch": len(xhr),
            "xhr_with_response": len(xhr_with_response),
            "xhr_with_body": len(xhr_with_body),
            "xhr_capture_rate": ratio(len(xhr_with_response), len(xhr)),
            "xhr_body_rate": ratio(len(xhr_with_body), len(xhr)),
            "statuses": dict(Counter(f.get("status") for f in xhr)),
        },
        "boundary": {
            "observed_unsafe": [
                {"method": e.get("method"), "path": e.get("path"), "url": e.get("url")}
                for e in observed_unsafe
            ],
            "declared_unsafe": [
                {"method": e.get("method"), "path": e.get("path"), "url": e.get("url")}
                for e in declared_unsafe
            ],
            "bootstrap_unsafe_flows": [
                {"method": f.get("method"), "url": f.get("url")} for f in bootstrap_unsafe
            ],
            "crawl_unsafe_flows": [
                {"method": f.get("method"), "url": f.get("url")} for f in crawl_unsafe
            ],
        },
        "manifest": {
            "schema_version": manifest.get("schema_version"),
            "keys": sorted(manifest_keys),
            "run": manifest.get("run", {}),
            "stats": manifest.get("stats", {}),
        },
        "metrics_quality": metrics.get("quality", {}),
        "metrics_jev": metrics.get("jev", {}),
        "invariants": invariants,
    }
    return out


def render_md(a: dict) -> str:
    q = a["forms"]
    s = a["safety"]
    c = a["capture"]
    inv = a["invariants"]
    lines = [
        "# steel_crawl prototype v2 assessment",
        "",
        f"- Run: `{a['run']}`",
        f"- Pages: {a['counts']['pages']}",
        f"- Actions: {a['counts']['actions']}",
        f"- Forms: {q['attempted']} attempted / {q['succeeded']} succeeded",
        f"- Fields: {q['fields_filled']}/{q['fields_total']} filled ({q['field_coverage']})",
        f"- Network field match (diagnostic): {q['network_fields']}/{q['fields_total']} ({q['network_field_coverage']})",
        f"- Removed by Jev: {s['removed']} (manual labels: unsafe {s['unsafe_removed']}, safe {s['safe_removed']})",
        f"- XHR/Fetch: {c['xhr_fetch']} captured, {c['xhr_with_response']} with response, {c['xhr_with_body']} with body",
        f"- No-op local-state rate: {a['actions']['no_op_local_state_rate']}",
        f"- No-op all-actions rate: {a['actions']['no_op_all_actions_rate']}",
        f"- Endpoints: {a['counts']['observed_endpoints']} observed, {a['counts']['declared_endpoints']} declared",
        "",
        "## Invariants",
        "",
        "| Invariant | Result |",
        "| - | - |",
    ]
    for k, v in inv.items():
        lines.append(f"| `{k}` | {'PASS' if v else 'FAIL' if v is False else 'n/a'} |")
    lines += [
        "",
        "## Forms",
        "",
        "| Submit | Synthetic | Success | HTTP | Declared method | Observed method | URL |",
        "| - | - | - | - | - | - | - |",
    ]
    for f in q["records"]:
        lines.append(
            f"| {f['submit']} | {f['synthetic']} | {f['success']} | {f['status']} | "
            f"{f['method']} | {f['request_method']} | {f['url']} |"
        )
    lines += ["", "## Safety", "", "| Type | Name | Truth | Source |", "| - | - | - | - |"]
    for r in s["records"]:
        lines.append(f"| {r['type']} | {r['name']} | {r['truth']} | {r['source']} |")
    lines += [
        "",
        "## Boundary",
        "",
        f"- Observed crawl unsafe endpoints: {len(a['boundary']['observed_unsafe'])}",
        f"- Declared unsafe endpoints: {len(a['boundary']['declared_unsafe'])}",
        f"- Bootstrap unsafe flows (outside crawl): {len(a['boundary']['bootstrap_unsafe_flows'])}",
        f"- Crawl unsafe flows: {len(a['boundary']['crawl_unsafe_flows'])}",
        "",
        "## Phase capture",
        "",
        f"- {a['capture']['phases']}",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: assess_v2.py <run_dir> [<run_dir> ...]")
        return 2
    for raw in sys.argv[1:]:
        run_dir = Path(raw)
        a = assess(run_dir)
        out = run_dir / "assessment.json"
        out.write_text(json.dumps(a, indent=2, ensure_ascii=False, default=str))
        md = run_dir / "assessment.md"
        md.write_text(render_md(a))
        print(render_md(a))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
