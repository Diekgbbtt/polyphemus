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
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from polymerhus.recon.crawl.steel.capture.typing import RealtimeRecord, ScriptAsset
from polymerhus.recon.domain.noise_filter import is_vendor_script_path

SCHEMA_VERSION = "steel-crawl/v2"


class RunBlock(BaseModel):
    """The run identity and terminal facts the graph references."""

    model_config = ConfigDict(extra="forbid")

    crawl_run_id: str
    session_name: str
    account: str | None = None
    role: str | None = None
    root_url: str | None = None
    auth_probe: str | None = None
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
    # A script under a canonical vendor root with no target signal. The
    # manifest keeps the record; the curator drops it from the graph. False
    # means the body carried a target signal and the endpoint stays.
    vendor_script: bool = False


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


def build_manifest_from_output(
    output,
    *,
    run: RunBlock,
    flows=(),
    scripts=(),
    realtime=(),
    errors=(),
    duration_ms: int = 0,
) -> Manifest:
    """Assemble the v2 graph input from one `RunOutput` and its capture.

    `output` is the crawl run's `RunOutput`: it carries the frontier, the
    normalized artifacts, the observed parameters, and the declared records.
    The endpoint identity is the flow's actual `(method, path, baseurl)`; one
    id names one route, so two query variants of the same route are one
    endpoint. Parameters anchor to the endpoint their flow called. Declared
    records keep their own provenance and never merge with the observed ones.
    """
    from polymerhus.recon.crawl.steel.parameters import (
        endpoint_key,
        split_url,
    )

    flow_artifact: dict[str, str] = dict(getattr(output, "flow_artifacts", {}) or {})

    endpoints: dict[str, EndpointRecord] = {}
    for flow in flows:
        split = split_url(flow.url)
        if split is None:
            continue
        path, baseurl = split
        key = endpoint_key(flow.method, path, baseurl)
        vendor_script = (
            is_vendor_script_path(path) and not _has_target_signal(flow)
        )
        existing = endpoints.get(key)
        if existing is None:
            endpoints[key] = EndpointRecord(
                endpoint_id="ep_observed_" + _short_hash(key),
                provenance="observed",
                method=flow.method,
                url=flow.url,
                path=path,
                baseurl=baseurl,
                status_code=flow.status,
                source="cdp",
                resource_type=flow.resource_type,
                http_artifact_id=flow_artifact.get(flow.request_id),
                source_page_id=flow.page_id,
                action_id=flow.action_id,
                vendor_script=vendor_script,
            )
        else:
            update: dict[str, Any] = {}
            if existing.status_code is None and flow.status is not None:
                update["status_code"] = flow.status
            if existing.vendor_script and not vendor_script:
                # A later flow proved the path carries application surface.
                update["vendor_script"] = False
            if update:
                endpoints[key] = existing.model_copy(update=update)

    parameters: list[ParameterRecord] = []
    seen_parameters: set[str] = set()
    for parameter in getattr(output, "parameters", ()):
        endpoint = endpoints.get(parameter.endpoint_key)
        if endpoint is None:
            continue
        shape = getattr(parameter.value_shape, "model_dump", None)
        value_shape = (
            shape(mode="json") if callable(shape) else parameter.value_shape
        )
        parameter_id = "param_observed_" + _short_hash(
            "\x1f".join(parameter.dedup_key)
        )
        if parameter_id in seen_parameters:
            continue
        seen_parameters.add(parameter_id)
        parameters.append(
            ParameterRecord(
                parameter_id=parameter_id,
                endpoint_id=endpoint.endpoint_id,
                provenance="observed",
                endpoint_path=parameter.endpoint_path,
                baseurl=parameter.baseurl,
                position=parameter.location,
                name=parameter.name,
                value_shape=value_shape,
                http_artifact_id=flow_artifact.get(parameter.source_flow_id),
                content_type=parameter.content_type,
            )
        )

    for declared in getattr(output, "declared_endpoints", ()):
        record = EndpointRecord(
            endpoint_id=declared.endpoint_id,
            provenance="declared",
            method=declared.method,
            url=declared.url,
            path=declared.path,
            baseurl=declared.baseurl,
            status_code=None,
            source=declared.source,
            resource_type=declared.resource_type,
            http_artifact_id=None,
            source_page_id=declared.source_page_id,
            action_id=declared.action_id,
            enctype=declared.enctype,
            field_names=tuple(declared.field_names),
        )
        endpoints.setdefault(endpoint_key(record.method, record.path, record.baseurl), record)
    for declared in getattr(output, "declared_fields", ()):
        if declared.parameter_id in seen_parameters:
            continue
        seen_parameters.add(declared.parameter_id)
        parameters.append(
            ParameterRecord(
                parameter_id=declared.parameter_id,
                endpoint_id=declared.endpoint_id,
                provenance="declared",
                endpoint_path=declared.endpoint_path,
                baseurl=declared.baseurl,
                position=declared.position,
                name=declared.name,
                value_shape=None,
                http_artifact_id=None,
                content_type=declared.content_type,
                field_type=declared.field_type,
                label=declared.label,
                options=tuple(declared.options),
                pattern=declared.pattern,
                min=declared.min,
                max=declared.max,
            )
        )

    frontier = getattr(output, "frontier", None)
    error_records = list(errors)
    if frontier is not None:
        if frontier.error:
            error_records.append(
                ErrorRecord(code="traversal_error", message=frontier.error, stage="frontier")
            )
        for stale in frontier.stale:
            error_records.append(
                ErrorRecord(
                    code=stale.error.code,
                    message=str(stale.error),
                    stage="executor",
                    page_id=stale.page.page_visit_id,
                    action_id=stale.element.element_id,
                )
            )
    unique_flows = {flow.request_id for flow in flows}
    bytes_seen = sum(
        int(getattr(flow, "encoded_data_length", 0) or 0)
        or len(getattr(flow, "response_body", b"") or b"")
        for flow in flows
    )
    return build_manifest(
        run=run,
        endpoints=list(endpoints.values()),
        parameters=parameters,
        scripts=scripts,
        realtime=realtime,
        errors=error_records,
        flows=len(unique_flows),
        bytes=bytes_seen,
        duration_ms=duration_ms,
        removed_elements=len(getattr(output, "removed", ())),
        unrecoverable_pages=len(getattr(frontier, "unrecoverable", ())) if frontier else 0,
    )


def _has_target_signal(flow) -> bool:
    """Whether a captured script body carries target-specific surface.

    A vendor path is a strong prior, not proof. A body that names the target
    host or an application route marker stays in the graph even under `/lib/`.
    The markers are deliberately narrow: a generic library that merely uses
    `fetch` is still a library.
    """
    body = getattr(flow, "response_body", None) or b""
    if not body:
        return False
    host = (urlsplit(flow.url).hostname or "").lower()
    if host and host.encode("utf-8") in body:
        return True
    return any(
        marker in body
        for marker in (
            b"/api/",
            b"/graphql",
            b"/rest/",
            b"/wp-json/",
            b"/ajax",
        )
    )


def _short_hash(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "EndpointRecord",
    "ErrorRecord",
    "Manifest",
    "ParameterRecord",
    "RunBlock",
    "SCHEMA_VERSION",
    "Stats",
    "build_manifest",
    "build_manifest_from_output",
    "load_manifest",
    "write_manifest",
]
