#!/usr/bin/env python3
"""Copy one project's data layer into a brand-new project (iteration D).

The data layer is what recon and analysis produced, and nothing hunting wrote:

- the L0/L1 graph in Neo4j, every node and every relationship, re-keyed to the
  new `project_id` (an `Observation` gets a fresh `id`, because its uniqueness
  constraint is global);
- the auth bucket (`auth/overview.yaml` and `auth/credentials.yaml`);
- the project-specific `authn` skill bundle, when the source carries one.

`hunting/` and `usage/` are deliberately not copied: the new project starts its
hunting run from scratch with a zero token ledger.

The script runs INSIDE the agent container, where the app data root, the skills
root, the Neo4j credentials, and the local API are all reachable:

    docker cp copy_project.py ph-dd131acc-agent-1:/tmp/copy_project.py
    docker exec ph-dd131acc-agent-1 python /tmp/copy_project.py \
        --source <old-project-id> --name eval-white-jotter-1-iter-d

It prints one JSON summary. A failed copy leaves the new project in place; the
operator removes it out of band (there is no delete endpoint by design).
"""
from __future__ import annotations

import argparse
import json
import secrets
import shutil
import sys
from pathlib import Path

import httpx
import yaml
from neo4j import GraphDatabase

PROCEDURE_BRANCH = "target-specific-procedure"


def api(base: str, method: str, path: str, body=None) -> dict:
    response = httpx.request(method, f"{base}{path}", json=body, timeout=60)
    if response.status_code >= 400:
        raise SystemExit(
            f"api {method} {path} -> {response.status_code}: {response.text[:500]}"
        )
    return response.json()


def read_scaffold(data_root: Path) -> dict:
    """The source's data layer files, by bucket, with their byte counts."""
    bucket = data_root / "auth"
    return {
        "overview": bucket / "overview.yaml",
        "credentials": bucket / "credentials.yaml",
    }


def copy_auth(source: Path, destination: Path) -> dict:
    """Byte-copy the auth bucket. The store is the two files, no pg row."""
    files = read_scaffold(source)
    copied = []
    destination.mkdir(parents=True, exist_ok=True)
    for name, path in files.items():
        if not path.exists():
            continue
        target = destination / path.name
        shutil.copy2(path, target)
        copied.append({"file": path.name, "bytes": target.stat().st_size})
    if not copied:
        raise SystemExit(f"source has no auth bucket under {source}")
    return {"copied": copied}


def copy_skill(
    source_root: Path, destination_root: Path, source: str, destination: str
) -> dict | None:
    """Copy the project-specific authn bundle, when the source has one."""
    source_dir = source_root / PROCEDURE_BRANCH / source / "authn"
    if not source_dir.is_dir():
        return None
    target_dir = destination_root / PROCEDURE_BRANCH / destination / "authn"
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)
    files = sorted(
        str(path.relative_to(target_dir)) for path in target_dir.rglob("*")
        if path.is_file()
    )
    return {"skill": "authn", "files": files}


def _label_clause(labels: list[str]) -> str:
    return "".join(f":{label}" for label in labels)


def copy_graph(
    *, uri: str, user: str, password: str, source: str, destination: str
) -> dict:
    """Copy every project-scoped node and relationship, re-keyed.

    Labels and relationship types are read from the source, then each set is
    created with a static Cypher clause (Cypher cannot parameterise either). A
    temporary `__src` property carries the source `elementId` so the edges can
    be re-created, and is removed at the end.
    """
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            label_sets = [
                tuple(record["labels"])
                for record in session.run(
                    "MATCH (n {project_id: $source}) "
                    "RETURN labels(n) AS labels, count(*) AS n",
                    source=source,
                )
            ]
            rel_types = [
                record["type"]
                for record in session.run(
                    "MATCH (a {project_id: $source})-[r]->(b {project_id: $source}) "
                    "RETURN DISTINCT type(r) AS type",
                    source=source,
                )
            ]
            for labels in label_sets:
                rows = session.run(
                    "MATCH (n {project_id: $source}) WHERE labels(n) = $labels "
                    "RETURN properties(n) AS props, elementId(n) AS eid",
                    source=source,
                    labels=list(labels),
                )
                for record in rows:
                    props = dict(record["props"])
                    # The old project_id must never reach the new node: a
                    # per-label uniqueness constraint would reject the
                    # intermediate value before the override lands.
                    props.pop("project_id", None)
                    if "Observation" in labels:
                        # `observation_unique` is global on `id`, so a copy
                        # needs a fresh identity.
                        props["id"] = secrets.token_hex(20)
                    session.run(
                        f"CREATE (m{_label_clause(list(labels))}) "
                        f"SET m = $props, m.project_id = $destination, "
                        f"m.__src = $src",
                        props=props,
                        destination=destination,
                        src=record["eid"],
                    )
            for rel_type in rel_types:
                session.run(
                    f"MATCH (a {{project_id: $source}})-[r:{rel_type}]->"
                    f"(b {{project_id: $source}}) "
                    f"MATCH (na {{project_id: $destination, __src: elementId(a)}}), "
                    f"(nb {{project_id: $destination, __src: elementId(b)}}) "
                    f"CREATE (na)-[nr:{rel_type}]->(nb) SET nr = properties(r)",
                    source=source,
                    destination=destination,
                )
            session.run(
                "MATCH (n {project_id: $destination}) REMOVE n.__src",
                destination=destination,
            )
            node_counts = {
                ":".join(record["labels"]): record["n"]
                for record in session.run(
                    "MATCH (n {project_id: $project}) "
                    "RETURN labels(n) AS labels, count(*) AS n",
                    project=destination,
                )
            }
            rel_counts = {
                record["type"]: record["n"]
                for record in session.run(
                    "MATCH (a {project_id: $project})-[r]->(b {project_id: $project}) "
                    "RETURN type(r) AS type, count(*) AS n",
                    project=destination,
                )
            }
    finally:
        driver.close()
    return {"nodes": node_counts, "relationships": rel_counts}


def source_counts(
    *, uri: str, user: str, password: str, source: str
) -> dict:
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            nodes = {
                ":".join(record["labels"]): record["n"]
                for record in session.run(
                    "MATCH (n {project_id: $project}) "
                    "RETURN labels(n) AS labels, count(*) AS n",
                    project=source,
                )
            }
            rels = {
                record["type"]: record["n"]
                for record in session.run(
                    "MATCH (a {project_id: $project})-[r]->(b {project_id: $project}) "
                    "RETURN type(r) AS type, count(*) AS n",
                    project=source,
                )
            }
    finally:
        driver.close()
    return {"nodes": nodes, "relationships": rels}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="the source project id")
    parser.add_argument("--name", required=True, help="the new project's name")
    parser.add_argument(
        "--project-id",
        help="reuse an already-created empty project instead of creating one",
    )
    parser.add_argument(
        "--api", default="http://127.0.0.1:8080", help="the app base URL"
    )
    parser.add_argument(
        "--data-root", type=Path, default=Path("/srv/data"),
        help="the app data root (projects live under it)",
    )
    parser.add_argument(
        "--skills-root", type=Path, default=Path("/srv/skills"),
        help="the skills root (project skills live under it)",
    )
    parser.add_argument("--neo4j-uri", default="bolt://neo4j:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default="polymerhus")
    args = parser.parse_args()

    source_dir = args.data_root / args.source
    if not source_dir.is_dir():
        raise SystemExit(f"source project data dir does not exist: {source_dir}")

    if args.project_id:
        destination = args.project_id
    else:
        created = api(args.api, "POST", "/projects", {"name": args.name})
        destination = created["project_id"]
    destination_dir = args.data_root / destination

    auth = copy_auth(source_dir, destination_dir / "auth")
    skill = copy_skill(
        args.skills_root, args.skills_root, args.source, destination
    )
    source_graph = source_counts(
        uri=args.neo4j_uri, user=args.neo4j_user, password=args.neo4j_password,
        source=args.source,
    )
    copied_graph = copy_graph(
        uri=args.neo4j_uri, user=args.neo4j_user, password=args.neo4j_password,
        source=args.source, destination=destination,
    )
    if copied_graph["nodes"] != source_graph["nodes"]:
        raise SystemExit(
            "node count mismatch: "
            f"source={source_graph['nodes']} copied={copied_graph['nodes']}"
        )
    if copied_graph["relationships"] != source_graph["relationships"]:
        raise SystemExit(
            "relationship count mismatch: "
            f"source={source_graph['relationships']} "
            f"copied={copied_graph['relationships']}"
        )

    graph = api(args.api, "GET", f"/projects/{destination}/graph")
    auth_state = api(args.api, "GET", f"/projects/{destination}/auth")
    summary = {
        "project_id": destination,
        "name": args.name,
        "source": args.source,
        "data_dir": str(destination_dir),
        "auth": auth,
        "skill": skill,
        "graph": copied_graph,
        "graph_api": {"nodes": len(graph.get("nodes", [])),
                      "links": len(graph.get("links", []))},
        "auth_keys": sorted(auth_state),
        "usage": api(args.api, "GET", f"/projects/{destination}/usage"),
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
