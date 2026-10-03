"""Deterministic capture of a Trial's final L0/L1 project graph.

A Trial reaches its terminal state while its instance is still up; the
orchestrator reads the read-only project graph endpoint once, validates it
against the existing frontend `GraphData` contract, normalizes the ordering,
and writes `project-graph.json` beside `trial.yaml` before the record itself.
The materializer never calls the live API: it consumes only these captured
bytes, so a retry cannot drift to a newer graph.

Normalization makes the content digest independent of database return order:
nodes sort by `id`, links by `(source, target, type)`, and serialization uses
sorted keys, UTF-8, stable separators, and exactly one trailing newline. The
SHA-256 is computed over the exact bytes written. Validation errors are
path-free and never echo response content. Import performs no I/O
(CODING_STANDARD section 6).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from orchestrator.files import FileStore

PROJECT_GRAPH_FILENAME = "project-graph.json"

STATUS_AVAILABLE = "available"
STATUS_UNAVAILABLE = "unavailable"

# The two stable, path-free failure codes the Trial record carries.
FAILURE_UNAVAILABLE = "project_graph_unavailable"
FAILURE_INVALID = "project_graph_invalid"


class ProjectGraphError(ValueError):
    """The project graph response does not satisfy the `GraphData` contract.

    The message names only the offending field; it never echoes response
    content or an absolute host path.
    """


@dataclass(frozen=True)
class ProjectGraphCapture:
    """The capture metadata persisted in the Trial record.

    An available capture carries the digest and counts; an unavailable capture
    carries the stable failure code and no digest.
    """

    status: str
    captured_at: str | None
    sha256: str | None
    node_count: int
    link_count: int
    failure: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "captured_at": self.captured_at,
            "sha256": self.sha256,
            "node_count": self.node_count,
            "link_count": self.link_count,
            "failure": self.failure,
        }


def normalize_project_graph(payload: Mapping, *, project_id: str) -> dict:
    """Validate `GraphData` and return a deterministic, order-stable copy.

    Only the contract is checked - no graph semantics. Node `id`/`name`/`type`
    and link `source`/`target`/`type` must be strings, node `properties` must be
    a mapping, and any extra fields the API returned are preserved. The exact
    `project_id` is required.
    """
    if not isinstance(payload, Mapping):
        raise ProjectGraphError("project graph payload is not a mapping")
    if payload.get("project_id") != project_id:
        raise ProjectGraphError("project graph project_id does not match the trial")
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        raise ProjectGraphError("project graph nodes must be a list")
    links = payload.get("links")
    if not isinstance(links, list):
        raise ProjectGraphError("project graph links must be a list")

    normalized_nodes: list[dict] = []
    for index, node in enumerate(nodes):
        if not isinstance(node, Mapping):
            raise ProjectGraphError(f"project graph node {index} is not a mapping")
        for field in ("id", "name", "type"):
            if not isinstance(node.get(field), str):
                raise ProjectGraphError(
                    f"project graph node {index} field {field!r} must be a string"
                )
        if not isinstance(node.get("properties"), Mapping):
            raise ProjectGraphError(
                f"project graph node {index} field 'properties' must be a mapping"
            )
        normalized_nodes.append(dict(node))
    normalized_nodes.sort(key=lambda node: node["id"])

    normalized_links: list[dict] = []
    for index, link in enumerate(links):
        if not isinstance(link, Mapping):
            raise ProjectGraphError(f"project graph link {index} is not a mapping")
        for field in ("source", "target", "type"):
            if not isinstance(link.get(field), str):
                raise ProjectGraphError(
                    f"project graph link {index} field {field!r} must be a string"
                )
        normalized_links.append(dict(link))
    normalized_links.sort(key=lambda link: (link["source"], link["target"], link["type"]))

    normalized = dict(payload)
    normalized["project_id"] = project_id
    normalized["nodes"] = normalized_nodes
    normalized["links"] = normalized_links
    return normalized


def canonical_project_graph_bytes(normalized: Mapping) -> bytes:
    """The exact UTF-8 bytes written and hashed for a normalized graph."""
    text = json.dumps(
        normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return (text + "\n").encode("utf-8")


def capture_project_graph(
    payload: Mapping,
    *,
    project_id: str,
    captured_at: str,
    destination: Path,
    files: FileStore,
) -> ProjectGraphCapture:
    """Normalize, hash, and atomically write one project graph capture.

    Raises `ProjectGraphError` for an invalid payload or the underlying
    `OSError` for a failed write; the caller decides how to degrade. The digest
    is computed over the exact bytes written.
    """
    normalized = normalize_project_graph(payload, project_id=project_id)
    data = canonical_project_graph_bytes(normalized)
    digest = hashlib.sha256(data).hexdigest()
    files.write_bytes_atomic(Path(destination), data)
    return ProjectGraphCapture(
        status=STATUS_AVAILABLE,
        captured_at=captured_at,
        sha256=digest,
        node_count=len(normalized["nodes"]),
        link_count=len(normalized["links"]),
        failure=None,
    )


def unavailable_project_graph(failure: str) -> ProjectGraphCapture:
    """A path-free unavailable capture for a failed best-effort read."""
    return ProjectGraphCapture(
        status=STATUS_UNAVAILABLE,
        captured_at=None,
        sha256=None,
        node_count=0,
        link_count=0,
        failure=failure,
    )


__all__ = [
    "FAILURE_INVALID",
    "FAILURE_UNAVAILABLE",
    "PROJECT_GRAPH_FILENAME",
    "STATUS_AVAILABLE",
    "STATUS_UNAVAILABLE",
    "ProjectGraphCapture",
    "ProjectGraphError",
    "canonical_project_graph_bytes",
    "capture_project_graph",
    "normalize_project_graph",
    "unavailable_project_graph",
]
