#!/usr/bin/env python3
"""Measure the L1 coverage delta between iteration E and the next trial.

The first iteration E run is the baseline: the crawl produced 111 endpoints but
the partial-manifest path discarded them, so the analysis saw 15 endpoints and
wrote 8 AGGREGATES. The next run holds the manifest_partial fix and the longer
crawl budget. This tool reads the same project graph and the crawl manifest and
prints the comparison fields, so the delta is measured, not estimated.

Usage (on the eval server, with Neo4j up):

    python3 measure_l1_coverage.py \
      --project-id 5e7a1ea0-aef7-4894-8231-902e5ab37909 \
      --data-root /opt/polymerhus-dev/eval/instances/data/eval-server-2 \
      --neo4j-password polymerhus \
      --out baseline.json

The script performs reads only. It never writes to the graph.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from neo4j import GraphDatabase

NODE_QUERIES = {
    "services": "MATCH (s:L1Service {project_id: $p}) RETURN count(s) AS n",
    "systems": "MATCH (s:L1System {project_id: $p}) RETURN count(s) AS n",
    "endpoints": "MATCH (e:Endpoint {project_id: $p}) RETURN count(e) AS n",
    "base_urls": "MATCH (b:BaseURL {project_id: $p}) RETURN count(b) AS n",
    "observations": "MATCH (o:Observation {project_id: $p}) RETURN count(o) AS n",
}
AGGREGATE_QUERIES = {
    "aggregates": (
        "MATCH (:L1Service {project_id: $p})-[:AGGREGATES]->(e) "
        "RETURN count(*) AS n"
    ),
    "unique_aggregated_endpoints": (
        "MATCH (:L1Service {project_id: $p})-[:AGGREGATES]->(e) "
        "RETURN count(DISTINCT e) AS n"
    ),
    "services_with_aggregates": (
        "MATCH (s:L1Service {project_id: $p})-[:AGGREGATES]->(:Endpoint) "
        "RETURN count(DISTINCT s) AS n"
    ),
}
SYSTEM_EDGE_QUERY = (
    "MATCH (:L1Service {project_id: $p})-[r]->(:L1System {project_id: $p}) "
    "RETURN type(r) AS rel, count(*) AS n ORDER BY rel"
)
SYSTEMS_WITH_EVIDENCE_QUERY = (
    "MATCH (s:L1System {project_id: $p})-[:EVIDENCED_BY]->(n) "
    "RETURN count(DISTINCT s) AS n"
)
SERVICES_WITH_SYSTEM_EDGES_QUERY = (
    "MATCH (s:L1Service {project_id: $p})-[:ROUTED_BY|IDENTIFIED_BY|EXPOSED_VIA]->"
    "(:L1System {project_id: $p}) RETURN count(DISTINCT s) AS n"
)
ENDPOINTS_QUERY = (
    "MATCH (e:Endpoint {project_id: $p}) "
    "RETURN coalesce(e.url, e.final_url) AS url, e.path AS path, "
    "e.baseurl AS base"
)


def _endpoint_key(url: str | None, path: str | None, base: str | None) -> str:
    if url:
        return str(url).rstrip("/")
    if base and path:
        return f"{str(base).rstrip('/')}/{str(path).lstrip('/')}".rstrip("/")
    return str(path or "").rstrip("/")


def _graph_endpoint_keys(session, params: dict) -> set[str]:
    return {
        _endpoint_key(row["url"], row["path"], row["base"])
        for row in session.run(ENDPOINTS_QUERY, **params)
        if row["url"] or row["path"]
    }


def _manifest_endpoint_keys(path: Path) -> set[str]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    keys = set()
    for entry in doc.get("endpoints") or []:
        keys.add(_endpoint_key(
            entry.get("url"), entry.get("path"), entry.get("baseurl")))
    keys.discard("")
    return keys


def _one(session, query: str, params: dict) -> int:
    return int(session.run(query, **params).single()["n"])


def _count_manifest_endpoints(data_root: Path, project_id: str) -> dict:
    """The latest crawl manifest's endpoint count and JS subset."""
    manifests = sorted(
        (data_root / project_id / "steel-crawl").glob("*/manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    best = None
    for path in manifests:
        doc = json.loads(path.read_text(encoding="utf-8"))
        endpoints = doc.get("endpoints") or []
        if best is None or len(endpoints) > len(best[1]):
            best = (path, endpoints)
    if best is None:
        return {"manifest_path": None, "manifest_endpoints": 0, "manifest_js": 0}
    path, endpoints = best
    js = [
        e for e in endpoints
        if ".js" in (e.get("url") or "") or ".js" in (e.get("path") or "")
    ]
    return {
        "manifest_path": str(path),
        "manifest_endpoints": len(endpoints),
        "manifest_js": len(js),
    }


def measure(
    *, project_id: str, data_root: Path,
    uri: str, user: str, password: str,
) -> dict:
    driver = GraphDatabase.driver(uri, auth=(user, password))
    params = {"p": project_id}
    with driver.session() as session:
        out: dict = {"project_id": project_id}
        for key, query in NODE_QUERIES.items():
            out[key] = _one(session, query, params)
        for key, query in AGGREGATE_QUERIES.items():
            out[key] = _one(session, query, params)
        by_rel = {
            row["rel"]: int(row["n"])
            for row in session.run(SYSTEM_EDGE_QUERY, **params)
        }
        out["service_system_edges"] = sum(by_rel.values())
        out["service_system_edges_by_rel"] = by_rel
        out["systems_with_evidence"] = _one(session, SYSTEMS_WITH_EVIDENCE_QUERY, params)
        out["services_with_system_edges"] = _one(
            session, SERVICES_WITH_SYSTEM_EDGES_QUERY, params)
        graph_endpoint_keys = _graph_endpoint_keys(session, params)
    driver.close()

    out.update(_count_manifest_endpoints(data_root, project_id))
    if out["manifest_path"]:
        manifest_keys = _manifest_endpoint_keys(Path(out["manifest_path"]))
        present = graph_endpoint_keys & manifest_keys
        out["manifest_endpoints_present"] = len(present)
        out["manifest_endpoint_coverage"] = (
            len(present) / len(manifest_keys) if manifest_keys else 0.0
        )
    else:
        out["manifest_endpoints_present"] = 0
        out["manifest_endpoint_coverage"] = 0.0
    out["services_without_aggregates"] = out["services"] - out["services_with_aggregates"]
    out["services_without_system_edges"] = (
        out["services"] - out["services_with_system_edges"])
    out["aggregate_coverage"] = (
        out["unique_aggregated_endpoints"] / out["endpoints"]
        if out["endpoints"] else 0.0
    )
    out["service_aggregate_coverage"] = (
        out["services_with_aggregates"] / out["services"]
        if out["services"] else 0.0
    )
    out["service_system_edge_coverage"] = (
        out["services_with_system_edges"] / out["services"]
        if out["services"] else 0.0
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--neo4j-uri", default="bolt://127.0.0.1:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--baseline", type=Path,
                        help="an earlier JSON measurement to compare against")
    args = parser.parse_args()

    result = measure(
        project_id=args.project_id,
        data_root=args.data_root,
        uri=args.neo4j_uri,
        user=args.neo4j_user,
        password=args.neo4j_password,
    )
    if args.baseline and args.baseline.exists():
        base = json.loads(args.baseline.read_text(encoding="utf-8"))
        keys = (
            "services", "systems", "endpoints", "aggregates",
            "unique_aggregated_endpoints", "services_with_aggregates",
            "service_system_edges", "systems_with_evidence",
            "manifest_endpoints", "manifest_js", "manifest_endpoints_present",
            "aggregate_coverage", "service_aggregate_coverage",
            "service_system_edge_coverage", "manifest_endpoint_coverage",
        )
        result["delta"] = {
            key: result.get(key, 0) - base.get(key, 0) for key in keys
        }
    text = json.dumps(result, indent=2, sort_keys=True)
    print(text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
