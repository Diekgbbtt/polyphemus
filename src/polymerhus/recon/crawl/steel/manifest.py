"""The v2 manifest: the graph input, not the observability log.

Spec: `docs/design/steel-crawl-spec.md` section 11.

The manifest carries only the graph-bearing records: the run block, the observed
and declared endpoints and parameters, the scripts, the realtime records, the
errors, and the stats. Pages and actions live in the observability platform and
are referenced by id; flows live in the HTTP history; the manifest never
duplicates them. The schema is `steel-crawl/v2`; the v1 parser stays compatible
because this model only defines the new shape.

The writer is atomic: it writes a sibling temporary file and replaces the target,
so a killed process never leaves a half-written graph input. Nothing here
performs network I/O.
"""
from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from polymerhus.recon.crawl.steel.capture.typing import RealtimeRecord, ScriptAsset

SCHEMA_VERSION = "steel-crawl/v2"


class RunBlock(BaseModel):
    """The run identity and terminal facts the graph references."""

    model_config = ConfigDict(extra="forbid")

    crawl_run_id: str
    session_name: str
    account: str | None = None
    started_at: str
    finished_at: str | None = None
    stop_reason: str
    partial: bool = False
    scope: list[str] = Field(default_factory=list)
    auth: dict[str, Any] = Field(default_factory=dict)


class EndpointRecord(BaseModel):
    """One endpoint the crawl observed or the DOM declared (spec 8.4)."""

    model_config = ConfigDict(extra="forbid")

    endpoint_id: str
    provenance: Literal["observed", "declared"]
    method: str
    url: str
    path: str
    baseurl: str
    status_code: int | None = None
    source: str = ""
    resource_type: str | None = None
    http_artifact_id: str | None = None
    source_page_id: str | None = None
    action_id: str | None = None
    enctype: str | None = None
    field_names: tuple[str, ...] = ()


class ParameterRecord(BaseModel):
    """One parameter the network observed or the DOM declared (spec 8.4)."""

    model_config = ConfigDict(extra="forbid")

    parameter_id: str
    endpoint_id: str
    provenance: Literal["observed", "declared"]
    endpoint_path: str
    baseurl: str
    position: str
    name: str
    value_shape: dict[str, Any] | None = None
    http_artifact_id: str | None = None
    content_type: str | None = None
    field_type: str | None = None
    label: str | None = None
    options: tuple[str, ...] | None = None
    pattern: str | None = None
    min: str | None = None
    max: str | None = None


class ErrorRecord(BaseModel):
    """One typed run error, with the page and action that saw it."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    stage: str | None = None
    page_id: str | None = None
    action_id: str | None = None


class Stats(BaseModel):
    """The run's aggregate counts (spec 11)."""

    model_config = ConfigDict(extra="forbid")

    endpoints: int = 0
    parameters: int = 0
    flows: int = 0
    bytes: int = 0
    duration_ms: int = 0
    removed_elements: int = 0
    unrecoverable_pages: int = 0


class Manifest(BaseModel):
    """The `steel-crawl/v2` graph input.

    The model forbids extras, so the absent pages, actions, flows, artifacts,
    declared endpoints, declared fields, and coverage block are structural, not
    a convention. `endpoints` and `parameters` include both provenances; the
    `provenance` field is the only merge point, and it never changes.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    run: RunBlock
    endpoints: list[EndpointRecord] = Field(default_factory=list)
    parameters: list[ParameterRecord] = Field(default_factory=list)
    scripts: list[ScriptAsset] = Field(default_factory=list)
    realtime: list[RealtimeRecord] = Field(default_factory=list)
    errors: list[ErrorRecord] = Field(default_factory=list)
    stats: Stats = Field(default_factory=Stats)


def build_manifest(
    *,
    run: RunBlock,
    endpoints: Sequence[EndpointRecord] = (),
    parameters: Sequence[ParameterRecord] = (),
    scripts: Sequence[ScriptAsset] = (),
    realtime: Sequence[RealtimeRecord] = (),
    errors: Sequence[ErrorRecord] = (),
    flows: int = 0,
    bytes: int = 0,
    duration_ms: int = 0,
    removed_elements: int = 0,
    unrecoverable_pages: int = 0,
) -> Manifest:
    """Assemble the v2 manifest and derive the endpoint and parameter counts."""
    return Manifest(
        run=run,
        endpoints=list(endpoints),
        parameters=list(parameters),
        scripts=list(scripts),
        realtime=list(realtime),
        errors=list(errors),
        stats=Stats(
            endpoints=len(endpoints),
            parameters=len(parameters),
            flows=flows,
            bytes=bytes,
            duration_ms=duration_ms,
            removed_elements=removed_elements,
            unrecoverable_pages=unrecoverable_pages,
        ),
    )


def write_manifest(path: str | Path, manifest: Manifest) -> None:
    """Write the manifest atomically as UTF-8 JSON (spec 11)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    payload = json.dumps(
        manifest.model_dump(mode="json"), ensure_ascii=False, indent=2
    )
    temporary.write_text(payload + "\n", encoding="utf-8")
    os.replace(temporary, target)


def load_manifest(path: str | Path) -> Manifest:
    """Read and validate a v2 manifest; a malformed file raises."""
    return Manifest.model_validate_json(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "EndpointRecord",
    "ErrorRecord",
    "Manifest",
    "ParameterRecord",
    "RunBlock",
    "SCHEMA_VERSION",
    "Stats",
    "build_manifest",
    "load_manifest",
    "write_manifest",
]
