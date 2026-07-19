"""Read + format the project attack-surface graph for the frontend.

Node/link shape matches the design contract: node {id,name,type,properties},
link {source,target,type}, with an added Observation case. The Cypher
(fetch_project_graph) uses OPTIONAL MATCH so zero-degree nodes are still
returned."""
from __future__ import annotations


def _jsonable(value):
    """Coerce neo4j-native property values into JSON-safe primitives.

    The neo4j driver returns temporal (neo4j.time.DateTime/Date/Time/Duration)
    and spatial (neo4j.spatial.Point) types, which pydantic cannot serialize,
    causing serialize_response to 500. Detect by module (no hard neo4j import,
    so the pure formatter stays driver-free) and recurse through containers.
    Temporal -> ISO string, Duration -> ISO 8601 duration, Point -> [x, y].

    neo4j types are checked BEFORE the container branches: Duration and Point
    subclass tuple, so the generic list/tuple recursion would otherwise expand
    a Duration into its raw [months, days, seconds, nanos] components."""
    module = type(value).__module__
    if module.startswith("neo4j."):
        native = value.to_native() if hasattr(value, "to_native") else None
        if hasattr(native, "isoformat"):  # datetime / date / time
            return native.isoformat()
        if hasattr(value, "iso_format"):  # Duration -> "P1DT30S"
            return value.iso_format()
        if module.startswith("neo4j.spatial"):  # Point is iterable of coords
            return list(value)
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


# Prefer the most specific/meaningful label for display + colouring. L1 units are
# multi-label (`:L1TestableUnit:L1Service`) and Neo4j returns labels in an
# UNSPECIFIED order, so a naive `labels[0]` can surface the generic supertype -
# which made every L1 node read as one indistinct type (and one grey colour) in
# the frontend. Rank the specific subtypes / catalogue labels ahead of the
# supertype so services, systems, and data items are always distinguishable.
_LABEL_PRIORITY = (
    "L1Service", "L1System", "L1DataItem", "SystemKind", "DataRelationshipKind",
)

# The non-null discriminator sentinel (mirrors l1_types.L1_SINGLETON); inlined so
# this pure L0-side formatter stays import-light (no analysis-layer dependency).
_L1_SINGLETON = "__singleton__"


def primary_label(labels: list[str] | None) -> str:
    """The most specific label to represent a node by (type + colour). Prefers a
    known L1 subtype / catalogue label over the generic `:L1TestableUnit`
    supertype; falls back to the first label, or 'Unknown' when none."""
    for pref in _LABEL_PRIORITY:
        if pref in (labels or []):
            return pref
    return (labels or ["Unknown"])[0]


def node_name(labels: list[str], props: dict) -> str:
    label = primary_label(labels)
    p = props or {}
    if label == "Observation":
        return str(p.get("macro_kind") or p.get("severity") or "Observation")
    # L1 units name by their identity slug, not a generic label (the L0 key list
    # below never matches an L1 node, so without this they showed as bare labels).
    if label == "L1Service":
        return str(p.get("business_function_slug") or "L1Service")
    if label == "L1System":
        kind = p.get("system_kind") or "L1System"
        disc = p.get("discriminator")
        return f"{kind}:{disc}" if disc and disc != _L1_SINGLETON else str(kind)
    if label == "L1DataItem":
        return str(p.get("item_key") or "L1DataItem")
    if label in ("SystemKind", "DataRelationshipKind"):
        return str(p.get("id") or label)
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
                "type": primary_label(node.get("labels")),
                "properties": _jsonable(dict(node.get("props", {}))),
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
