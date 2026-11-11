#!/usr/bin/env python3
"""Copy one project's L0/L1 graph to a fresh project id inside the agent image.

This is the graph half of the hunting-only project duplication. It runs inside
the agent container (the only place with the `neo4j` driver and the app's
`neo4j_client`), reads every node and relationship that carries the old
`project_id`, and recreates them under the new id with the same labels,
properties, and relationship types.

Two properties need special handling:

- `project_id` is replaced on every copied node.
- `Observation.id` is GLOBALLY unique (`observation_unique`), so a straight
  copy would violate the constraint. A copied Observation gets a fresh id;
  graph identity (element ids) and every relationship are preserved, and the
  `Observation` payload is immutable evidence, so the replacement changes no
  observable fact.

The copy is all-or-nothing in practice: it refuses to start when the target
project already has nodes, and it verifies the node/relationship counts before
it returns. A failure leaves the target project partially written; the caller
should discard it and create a fresh one.

Environment:
    OLD_PROJECT_ID  the source project
    NEW_PROJECT_ID  the fresh project
"""
from __future__ import annotations

import os
import sys
from uuid import uuid4

from polymerhus.app.clients import neo4j_client


def _count(project_id: str) -> tuple[int, int]:
    nodes = neo4j_client.read(
        "MATCH (n {project_id:$p}) RETURN count(n) AS c", {"p": project_id}
    )[0]["c"]
    rels = neo4j_client.read(
        "MATCH (a {project_id:$p})-[r]->(b {project_id:$p}) RETURN count(r) AS c",
        {"p": project_id},
    )[0]["c"]
    return int(nodes), int(rels)


def _label_clause(labels: list[str]) -> str:
    return ":" + ":".join("`" + label.replace("`", "``") + "`" for label in labels)


def _type_clause(rel_type: str) -> str:
    return "`" + rel_type.replace("`", "``") + "`"


def main() -> int:
    old = os.environ.get("OLD_PROJECT_ID", "").strip()
    new = os.environ.get("NEW_PROJECT_ID", "").strip()
    if not old or not new:
        raise SystemExit("OLD_PROJECT_ID and NEW_PROJECT_ID are required")
    if old == new:
        raise SystemExit("the old and new project ids must differ")

    old_nodes, old_rels = _count(old)
    new_nodes, new_rels = _count(new)
    if new_nodes or new_rels:
        raise SystemExit(
            f"target project {new} is not empty: {new_nodes} nodes, {new_rels} relationships"
        )
    if old_nodes == 0:
        raise SystemExit(f"source project {old} has no nodes")

    nodes = neo4j_client.read(
        "MATCH (n {project_id:$p}) "
        "RETURN elementId(n) AS eid, labels(n) AS labels, properties(n) AS props",
        {"p": old},
    )
    relationships = neo4j_client.read(
        "MATCH (a {project_id:$p})-[r]->(b {project_id:$p}) "
        "RETURN elementId(a) AS src, elementId(b) AS dst, type(r) AS typ, "
        "properties(r) AS props",
        {"p": old},
    )

    with neo4j_client._driver.session() as session:  # noqa: SLF001 - the eval copy seam
        for node in nodes:
            labels = list(node["labels"])
            props = dict(node["props"])
            props["project_id"] = new
            props["_copy_src"] = node["eid"]
            if "Observation" in labels:
                props["id"] = uuid4().hex
            session.run(
                f"CREATE (n{_label_clause(labels)}) SET n = $props",
                props=props,
            )

        by_type: dict[str, list[dict]] = {}
        for rel in relationships:
            by_type.setdefault(rel["typ"], []).append(
                {"src": rel["src"], "dst": rel["dst"], "props": dict(rel["props"])}
            )
        for rel_type, group in by_type.items():
            session.run(
                "UNWIND $rels AS rel "
                "MATCH (a {_copy_src: rel.src}), (b {_copy_src: rel.dst}) "
                f"CREATE (a)-[r{_type_clause(rel_type)}]->(b) SET r = rel.props",
                rels=group,
            )
        session.run(
            "MATCH (n {project_id:$p}) REMOVE n._copy_src", {"p": new}
        )

    copied_nodes, copied_rels = _count(new)
    if (copied_nodes, copied_rels) != (old_nodes, old_rels):
        raise SystemExit(
            "copy count mismatch: "
            f"source {old_nodes}/{old_rels}, target {copied_nodes}/{copied_rels}"
        )
    print(f"copied {copied_nodes} nodes and {copied_rels} relationships "
          f"from {old} to {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
