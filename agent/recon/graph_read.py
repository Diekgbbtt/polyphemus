"""Read + format the project attack-surface graph for the frontend.

Node/link shape matches the design contract: node {id,name,type,properties},
link {source,target,type}. Ported from Redamon's format.ts getNodeName, plus
an Observation case. The Cypher (fetch_project_graph) uses OPTIONAL MATCH so
zero-degree nodes are still returned."""
from __future__ import annotations


def node_name(labels: list[str], props: dict) -> str:
    label = labels[0] if labels else "Unknown"
    p = props or {}
    if label == "Observation":
        return str(p.get("macro_kind") or p.get("severity") or "Observation")
    for key in ("name", "url", "path", "address", "value", "number"):
        if p.get(key) is not None:
            return str(p[key])
    return label


def format_graph_records(records: list[dict]) -> dict:
    nodes: dict[str, dict] = {}
    links: list[dict] = []

    def _register(node: dict | None) -> None:
        if not node:
            return
        nid = str(node["element_id"])
        if nid not in nodes:
            nodes[nid] = {
                "id": nid,
                "name": node_name(node.get("labels", []), node.get("props", {})),
                "type": (node.get("labels") or ["Unknown"])[0],
                "properties": dict(node.get("props", {})),
            }

    for rec in records:
        _register(rec.get("n"))
        _register(rec.get("m"))
        if rec.get("rtype") and rec.get("s") is not None and rec.get("t") is not None:
            links.append({"source": str(rec["s"]), "target": str(rec["t"]), "type": rec["rtype"]})

    return {"nodes": list(nodes.values()), "links": links}


_GRAPH_CYPHER = (
    "MATCH (n) WHERE n.project_id = $project_id "
    "OPTIONAL MATCH (n)-[r]->(m) WHERE m.project_id = $project_id "
    "RETURN n{.*, element_id: elementId(n), labels: labels(n)} AS n, "
    "CASE WHEN m IS NULL THEN NULL ELSE m{.*, element_id: elementId(m), labels: labels(m)} END AS m, "
    "type(r) AS rtype, elementId(n) AS s, elementId(m) AS t"
)


def fetch_project_graph(project_id: str, *, read_fn=None) -> dict:
    if read_fn is None:
        from agent.app.clients import neo4j_client
        read_fn = neo4j_client.read
    rows = read_fn(_GRAPH_CYPHER, {"project_id": project_id})
    # Normalize driver rows into the dict shape format_graph_records expects.
    records = []
    for row in rows:
        n = row["n"]
        m = row["m"]
        records.append({
            "n": {"element_id": n["element_id"], "labels": n["labels"],
                  "props": {k: v for k, v in n.items() if k not in ("element_id", "labels")}},
            "m": None if m is None else {
                "element_id": m["element_id"], "labels": m["labels"],
                "props": {k: v for k, v in m.items() if k not in ("element_id", "labels")}},
            "rtype": row["rtype"], "s": row["s"], "t": row["t"],
        })
    return format_graph_records(records)
