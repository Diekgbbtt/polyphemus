#!/usr/bin/env python
"""GT unit well-formedness criterion (plan 2026-10-17, W2.2).

Measures how well a produced L1 graph represents each ground-truth unit spec
(`unit-spec.yaml` in the vuln-groundtruth corpus). The criterion answers the
operator goal: every GT Service fully specified and edged to its Systems, and
every GT System specified well enough for a threat modeller to identify the
vulnerability.

Metrics per spec (plan section 3, W2.2):

- M1 placement (gate): the produced L1 node matching the unit key exists.
- M2 L0 grounding: share of required L0 items (endpoints and parameters)
  aggregated by the produced unit. Service units read the unit's own
  `AGGREGATES` edges; System units read the endpoints surfaced via the linked
  services, mirroring `attack.hunting.unit_projection` (each entry carries the
  owning service slug). An `EVIDENCED_BY` edge from a System to a matching
  endpoint is accepted as the fallback.
- M3 typed backbone: share of required backbone items present and non-empty.
  For System units the backbone is the node description plus the
  threat-modeller sufficiency statements (keyword coverage over the node text).
- M4 service-to-system edges: share of required typed edges present
  (rel plus target kind and discriminator; the spec declares the discriminator
  mode). For System units the requirement is inbound: the GT Services that must
  carry an edge to the System.

Unit score = mean(M2, M3, M4), gated by M1. Target score = mean over specs.
The spec loader, the metric math, and the report renderer are pure functions
over plain dicts so they are unit-testable without a database; the graph query
layer is a thin adapter against Neo4j.

Run (live, credentials from env or flags):
    python tools/measure_gt_wellformedness.py --target comfyui \
        --project d04b947f-d6c3-48be-9b18-1c4eef851241 --label comfyui-formal \
        --uri bolt://localhost:7687 --user neo4j --password ...
    python tools/measure_gt_wellformedness.py --lint
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_CORPUS = Path.home() / ".local/share/polymerhus/vuln-groundtruth"
SCHEMA = "gt-unit-spec/v1"
SINGLETON = "__singleton__"
SYSTEM_EDGE_RELS = (
    "EXPOSED_VIA", "IDENTIFIED_BY", "AUTHENTICATED_BY", "AUTHORIZED_BY",
    "FRONTED_BY", "PROTECTED_BY", "ROUTED_BY", "SHAPES_DATA_OF",
    "ON_REQUEST_PATH", "DEPENDS_ON",
)


# --- spec loading and lint ----------------------------------------------------

def iter_spec_paths(corpus: Path, target: str | None = None) -> list[Path]:
    """All `<corpus>/<target>/<bundle>/unit-spec.yaml` paths, sorted."""
    if target:
        return sorted((corpus / target).glob("*/unit-spec.yaml"))
    return sorted(corpus.glob("*/*/unit-spec.yaml"))


def load_spec(path: Path) -> dict:
    """Load and structurally validate one unit spec.

    Raises ValueError on a schema violation so the lint output names the file
    and the missing piece instead of a bare KeyError.
    """
    import yaml  # local import: the tool's pure layer stays stdlib-only

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    where = str(path)
    if not isinstance(data, dict):
        raise ValueError(f"{where}: not a mapping")
    if data.get("schema") != SCHEMA:
        raise ValueError(f"{where}: schema must be {SCHEMA!r}")
    for key in ("bundle", "unit", "typed_backbone", "edges_to_l0",
                "service_to_system_edges"):
        if key not in data:
            raise ValueError(f"{where}: missing key {key!r}")
    unit = data["unit"]
    if unit.get("kind") not in ("Service", "System"):
        raise ValueError(f"{where}: unit.kind must be Service or System")
    match = unit.get("match") or {}
    if unit["kind"] == "Service" and not match.get("business_function_slug"):
        raise ValueError(f"{where}: Service unit needs match.business_function_slug")
    if unit["kind"] == "System" and not (match.get("kind") and match.get("discriminator")):
        raise ValueError(f"{where}: System unit needs match.kind and match.discriminator")
    if not (data["typed_backbone"].get("required") or []):
        raise ValueError(f"{where}: typed_backbone.required is empty")
    if not (data["edges_to_l0"].get("endpoints") or
            data["edges_to_l0"].get("parameters") or []):
        raise ValueError(f"{where}: edges_to_l0 is empty")
    if not (data["service_to_system_edges"].get("required") or []):
        raise ValueError(f"{where}: service_to_system_edges.required is empty")
    return data


def lint_specs(paths: list[Path]) -> list[str]:
    """Completeness lint (plan W2.1 verification): every spec parses, carries at
    least one L0 requirement and at least one backbone item."""
    issues: list[str] = []
    for path in paths:
        try:
            spec = load_spec(path)
        except ValueError as exc:
            issues.append(str(exc))
            continue
        if not (spec["typed_backbone"].get("required") or []):
            issues.append(f"{path}: no backbone requirement")
        if not (spec["edges_to_l0"].get("endpoints") or []):
            issues.append(f"{path}: no required endpoint")
    return issues


# --- graph snapshot -----------------------------------------------------------

def _snapshot_from_queries(run_query, project_id: str) -> dict:
    """Build the snapshot dict from a `run_query(cypher, params)` callable.

    Split from the driver so the adapter shape stays testable with a fake.
    """

    def q(cypher: str, **params: Any) -> list[dict]:
        return run_query(cypher, {"project_id": project_id, **params})

    services = {
        row["slug"]: {"props": dict(row["props"] or {})}
        for row in q("MATCH (x:L1Service {project_id: $project_id}) "
                     "RETURN x.business_function_slug AS slug, properties(x) AS props")
    }
    systems = [
        {"kind": row["kind"], "discriminator": row["disc"],
         "props": dict(row["props"] or {})}
        for row in q("MATCH (x:L1System {project_id: $project_id}) "
                     "RETURN x.kind AS kind, x.discriminator AS disc, properties(x) AS props")
    ]
    aggregates: dict[str, list[dict]] = {slug: [] for slug in services}
    for row in q("MATCH (x:L1Service {project_id: $project_id})-[:AGGREGATES]->(e:Endpoint) "
                 "RETURN x.business_function_slug AS slug, e.method AS method, e.path AS path"):
        aggregates.setdefault(row["slug"], []).append(
            {"label": "Endpoint", "method": row["method"], "path": row["path"]})
    for row in q("MATCH (x:L1Service {project_id: $project_id})-[:AGGREGATES]->(t:Parameter) "
                 "RETURN x.business_function_slug AS slug, t.name AS name, "
                 "t.position AS position, t.endpoint_path AS endpoint_path"):
        aggregates.setdefault(row["slug"], []).append(
            {"label": "Parameter", "name": row["name"], "position": row["position"],
             "endpoint_path": row["endpoint_path"]})
    system_edges = [
        {"service_slug": row["slug"], "rel": row["rel"], "kind": row["kind"],
         "discriminator": row["disc"]}
        for row in q("MATCH (x:L1Service {project_id: $project_id})-[r]->"
                     "(y:L1System {project_id: $project_id}) "
                     "WHERE type(r) IN $rels "
                     "RETURN x.business_function_slug AS slug, type(r) AS rel, "
                     "y.kind AS kind, y.discriminator AS disc", rels=list(SYSTEM_EDGE_RELS))
    ]
    linked: list[dict] = [
        {"kind": row["kind"], "discriminator": row["disc"], "service_slug": row["slug"],
         "rel": row["rel"], "method": row["method"], "path": row["path"]}
        for row in q("MATCH (y:L1System {project_id: $project_id})<-[r]-"
                     "(x:L1Service {project_id: $project_id})-[:AGGREGATES]->(e:Endpoint) "
                     "WHERE type(r) IN $rels "
                     "RETURN y.kind AS kind, y.discriminator AS disc, "
                     "x.business_function_slug AS slug, type(r) AS rel, "
                     "e.method AS method, e.path AS path", rels=list(SYSTEM_EDGE_RELS))
    ]
    evidence: list[dict] = [
        {"kind": row["kind"], "discriminator": row["disc"],
         "method": row["method"], "path": row["path"]}
        for row in q("MATCH (y:L1System {project_id: $project_id})-[r]->(e:Endpoint) "
                     "WHERE type(r) = 'EVIDENCED_BY' "
                     "RETURN y.kind AS kind, y.discriminator AS disc, "
                     "e.method AS method, e.path AS path")
    ]
    return {
        "services": services,
        "systems": systems,
        "aggregates": aggregates,
        "system_edges": system_edges,
        "system_linked_endpoints": linked,
        "system_evidence": evidence,
    }


def read_snapshot(project_id: str, uri: str, user: str, password: str) -> dict:
    """Read the produced-L1 snapshot for one project from Neo4j."""
    from neo4j import GraphDatabase  # lazy: pure-layer tests need no driver

    driver = GraphDatabase.driver(uri, auth=(user, password))

    def run_query(cypher: str, params: dict) -> list[dict]:
        with driver.session() as session:
            return [dict(record) for record in session.run(cypher, **params)]

    try:
        return _snapshot_from_queries(run_query, project_id)
    finally:
        driver.close()


# --- metric math (pure) -------------------------------------------------------

def _non_empty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _match_value(actual: Any, expected: Any) -> bool:
    """Documentation-only comparison of a field's expected value."""
    if isinstance(expected, list):
        return sorted(map(str, actual or [])) == sorted(map(str, expected))
    return str(actual).lower() == str(expected).lower()


def _match_endpoint(required: dict, aggregates: list[dict]) -> dict:
    eps = [a for a in aggregates if a.get("label") == "Endpoint"]
    exact = [a for a in eps if (a.get("method") or "").upper() == required["method"].upper()
             and a.get("path") == required["path"]]
    if exact:
        return {"status": "matched"}
    path_only = [a for a in eps if a.get("path") == required["path"]]
    if path_only:
        return {"status": "method_mismatch",
                "actual_method": path_only[0].get("method")}
    return {"status": "missing"}


def _match_parameter(required: dict, aggregates: list[dict]) -> dict:
    params = [a for a in aggregates if a.get("label") == "Parameter"]
    matching = [a for a in params
                if a.get("name") == required["name"]
                and a.get("endpoint_path") == required["endpoint"]["path"]]
    if not matching:
        return {"status": "missing"}
    position = matching[0].get("position")
    if required.get("position") and position != required["position"]:
        return {"status": "position_mismatch", "actual_position": position}
    return {"status": "matched"}


def _placement(spec: dict, snapshot: dict) -> dict:
    unit = spec["unit"]
    match = unit["match"]
    if unit["kind"] == "Service":
        found = match["business_function_slug"] in snapshot["services"]
        return {"pass": found, "identity": match["business_function_slug"]}
    for system in snapshot["systems"]:
        if (system["kind"] == match["kind"]
                and (match.get("discriminator") in (None, system["discriminator"]))):
            return {"pass": True,
                    "identity": f"{system['kind']}:{system['discriminator']}"}
    return {"pass": False, "identity": f"{match['kind']}:{match.get('discriminator')}"}


def _l0_items(spec: dict, snapshot: dict) -> list[dict]:
    unit = spec["unit"]
    edges = spec["edges_to_l0"]
    source: list[dict] = []
    if unit["kind"] == "Service":
        source = snapshot["aggregates"].get(
            unit["match"]["business_function_slug"], [])
    else:
        match = unit["match"]
        for entry in snapshot["system_linked_endpoints"]:
            if (entry["kind"] == match["kind"]
                    and entry["discriminator"] == match["discriminator"]):
                source.append({"label": "Endpoint", "method": entry["method"],
                               "path": entry["path"]})
        for entry in snapshot["system_evidence"]:
            if (entry["kind"] == match["kind"]
                    and entry["discriminator"] == match["discriminator"]):
                source.append({"label": "Endpoint", "method": entry["method"],
                               "path": entry["path"]})
    items = []
    for endpoint in edges.get("endpoints") or []:
        result = _match_endpoint(endpoint, source)
        items.append({"kind": "endpoint", "required": endpoint, **result})
    for parameter in edges.get("parameters") or []:
        result = _match_parameter(parameter, source)
        items.append({"kind": "parameter", "required": parameter, **result})
    matched = [i for i in items if i["status"] == "matched"]
    endpoints = [i for i in items if i["kind"] == "endpoint"]
    parameters = [i for i in items if i["kind"] == "parameter"]
    return_items = {
        "items": items,
        "matched": len(matched),
        "total": len(items),
        "share": (len(matched) / len(items)) if items else 1.0,
        "endpoint_matched": sum(1 for i in endpoints if i["status"] == "matched"),
        "endpoint_total": len(endpoints),
        "parameter_matched": sum(1 for i in parameters if i["status"] == "matched"),
        "parameter_total": len(parameters),
    }
    return return_items


def _backbone(spec: dict, snapshot: dict) -> dict:
    unit = spec["unit"]
    backbone = spec["typed_backbone"]
    if unit["kind"] == "Service":
        props = snapshot["services"].get(
            unit["match"]["business_function_slug"], {}).get("props", {})
        items = []
        for field in backbone["required"]:
            name = field["field"]
            present = name in props and _non_empty(props.get(name))
            item = {"item": f"field:{name}", "present": present,
                    "expected": field.get("expected")}
            if "expected" in field and name in props:
                item["value_matches_expected"] = _match_value(
                    props.get(name), field["expected"])
            items.append(item)
    else:
        match = unit["match"]
        props = {}
        for system in snapshot["systems"]:
            if system["kind"] == match["kind"] and system["discriminator"] == match["discriminator"]:
                props = system["props"]
                break
        text = json.dumps(props, ensure_ascii=False, default=str).lower()
        items = []
        for field in backbone["required"]:
            name = field["field"]
            items.append({"item": f"field:{name}",
                          "present": name in props and _non_empty(props.get(name))})
        for statement in (backbone.get("threat_modeller_sufficiency") or {}).get(
                "statements", []):
            covered = all(kw.lower() in text for kw in statement["keywords"])
            items.append({"item": f"statement:{statement['id']}", "present": covered,
                          "keywords": statement["keywords"]})
    matched = [i for i in items if i["present"]]
    return {"items": items, "matched": len(matched), "total": len(items),
            "share": (len(matched) / len(items)) if items else 1.0}


def _system_edges(spec: dict, snapshot: dict) -> dict:
    unit = spec["unit"]
    required = spec["service_to_system_edges"]["required"]
    mode = spec["service_to_system_edges"].get("mode", "outbound")
    items = []
    if mode == "inbound":
        match = unit["match"]
        for edge in required:
            found = any(
                e["service_slug"] == edge["from_service"] and e["rel"] == edge["rel"]
                and e["kind"] == match["kind"]
                and e["discriminator"] == match["discriminator"]
                for e in snapshot["system_edges"])
            items.append({"required": edge, "status": "matched" if found else "missing"})
    else:
        service_slug = unit["match"]["business_function_slug"]
        for edge in required:
            disc_mode = edge.get("discriminator_mode", "exact")
            candidates = [e for e in snapshot["system_edges"]
                          if e["service_slug"] == service_slug
                          and e["rel"] == edge["rel"]
                          and e["kind"] == edge["target_kind"]]
            if disc_mode == "kind_any":
                hit = next((e for e in candidates
                            if e["discriminator"] == edge["target_discriminator"]), None)
                if hit is None:
                    hit = candidates[0] if candidates else None
            elif disc_mode == "any_of":
                hit = next((e for e in candidates
                            if e["discriminator"] in edge["target_discriminator"]), None)
            else:  # exact
                hit = next((e for e in candidates
                            if e["discriminator"] == edge["target_discriminator"]), None)
            items.append({
                "required": edge,
                "status": "matched" if hit else "missing",
                "actual_discriminator": hit["discriminator"] if hit else None,
                "exact_discriminator": bool(
                    hit and hit["discriminator"] == edge["target_discriminator"]),
                "discriminator_mode": disc_mode,
            })
    matched = [i for i in items if i["status"] == "matched"]
    return {"items": items, "matched": len(matched), "total": len(items),
            "share": (len(matched) / len(items)) if items else 1.0}


def score_spec(spec: dict, snapshot: dict) -> dict:
    """One GT spec's verdict against a produced-graph snapshot."""
    m1 = _placement(spec, snapshot)
    m2 = _l0_items(spec, snapshot)
    m3 = _backbone(spec, snapshot)
    m4 = _system_edges(spec, snapshot)
    score = ((m2["share"] + m3["share"] + m4["share"]) / 3.0) if m1["pass"] else 0.0
    return {
        "bundle": spec["bundle"],
        "unit": f"{spec['unit']['kind']}:" + (
            spec["unit"]["match"].get("business_function_slug")
            or f"{spec['unit']['match']['kind']}:{spec['unit']['match']['discriminator']}"),
        "vulnerability": spec.get("vulnerability", {}),
        "m1": m1, "m2": m2, "m3": m3, "m4": m4,
        "score": score,
    }


def score_target(specs: list[dict], snapshot: dict) -> dict:
    results = [score_spec(spec, snapshot) for spec in specs]
    mean = sum(r["score"] for r in results) / len(results) if results else 0.0
    return {"specs": results, "target_score": mean, "spec_count": len(results)}


# --- report rendering ---------------------------------------------------------

def render_text(label: str, project_id: str, corpus: Path, result: dict) -> str:
    lines = [f"# GT unit well-formedness - {label} ({project_id})",
             f"# corpus: {corpus}  specs: {result['spec_count']}", ""]
    for spec in result["specs"]:
        lines.append(f"## {spec['bundle']}  ({spec['unit']})")
        vuln = spec["vulnerability"]
        if vuln:
            lines.append(f"   vuln: {vuln.get('type')}  {vuln.get('fault_class')}")
        m1 = spec["m1"]
        lines.append(f"M1 placement: {'PASS' if m1['pass'] else 'FAIL'} ({m1['identity']})")
        m2 = spec["m2"]
        lines.append(f"M2 L0 grounding: {m2['share']:.2f} "
                     f"({m2['matched']}/{m2['total']}; endpoints "
                     f"{m2['endpoint_matched']}/{m2['endpoint_total']}, params "
                     f"{m2['parameter_matched']}/{m2['parameter_total']})")
        for item in m2["items"]:
            req = item["required"]
            what = (f"{req['method']} {req['path']}" if item["kind"] == "endpoint"
                    else f"param {req['name']} on "
                         f"{req['endpoint']['method']} {req['endpoint']['path']}")
            extra = ""
            if item.get("actual_method") or item.get("actual_position"):
                extra = f" [{item.get('actual_method') or item.get('actual_position')}]"
            lines.append(f"   - {what}: {item['status'].upper()}{extra}")
        m3 = spec["m3"]
        lines.append(f"M3 typed backbone: {m3['share']:.2f} ({m3['matched']}/{m3['total']})")
        for item in m3["items"]:
            mark = "OK" if item["present"] else "MISSING"
            detail = ""
            if item.get("expected") is not None:
                detail = f" (expected {item['expected']})"
            if "value_matches_expected" in item:
                detail += f" value_match={item['value_matches_expected']}"
            if item.get("keywords"):
                detail += f" keywords={item['keywords']}"
            lines.append(f"   - {item['item']}: {mark}{detail}")
        m4 = spec["m4"]
        lines.append(f"M4 edges: {m4['share']:.2f} ({m4['matched']}/{m4['total']})")
        for item in m4["items"]:
            req = item["required"]
            if "from_service" in req:
                what = f"{req['rel']} <- {req['from_service']}"
            else:
                what = f"{req['rel']} -> {req['target_kind']}"
            extra = ""
            if item.get("actual_discriminator"):
                exact = "" if item.get("exact_discriminator") else ", not exact"
                extra = f" [actual {item['actual_discriminator']}{exact}]"
            lines.append(f"   - {what}: {item['status'].upper()}{extra}")
        lines.append(f"unit score: {spec['score']:.2f}")
        lines.append("")
    lines.append(f"TARGET SCORE: {result['target_score']:.2f} "
                 f"over {result['spec_count']} specs")
    return "\n".join(lines) + "\n"


# --- CLI ----------------------------------------------------------------------

def _connect_snapshot(args) -> dict:
    return read_snapshot(
        project_id=args.project,
        uri=args.uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        user=args.user or os.environ.get("NEO4J_USER", "neo4j"),
        password=args.password or os.environ.get("NEO4J_PASSWORD", "password"),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    ap.add_argument("--target", default="")
    ap.add_argument("--project", default="", help="produced-graph project id")
    ap.add_argument("--label", default="")
    ap.add_argument("--uri", default="")
    ap.add_argument("--user", default="")
    ap.add_argument("--password", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--lint", action="store_true",
                    help="only lint the specs; no graph access")
    args = ap.parse_args(argv)

    corpus = Path(args.corpus).expanduser()
    paths = iter_spec_paths(corpus, args.target or None)
    if not paths:
        print(f"no unit-spec.yaml under {corpus} (target={args.target or 'all'})",
              file=sys.stderr)
        return 2
    issues = lint_specs(paths)
    if args.lint:
        for issue in issues:
            print(issue)
        print(f"lint: {len(paths)} specs, {len(issues)} issues")
        return 1 if issues else 0
    if not args.project:
        print("--project is required (or use --lint)", file=sys.stderr)
        return 2
    specs = [load_spec(p) for p in paths]
    snapshot = _connect_snapshot(args)
    result = score_target(specs, snapshot)
    label = args.label or args.project
    if args.json:
        payload = json.dumps({"label": label, "project_id": args.project,
                              "corpus": str(corpus), **result}, indent=2)
        if args.out:
            Path(args.out).write_text(payload, encoding="utf-8")
        print(payload)
    else:
        text = render_text(label, args.project, corpus, result)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
