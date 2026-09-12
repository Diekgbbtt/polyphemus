"""Projection of an artifact into the inverted scalar-attribute index.

Every recorded scalar becomes a row ``(side, namespace, key, text_value,
numeric_value)``. Namespaces: ``core``, ``header``, ``cookie``, ``query``,
``form``, ``body``, ``tls``. Sides: ``request``, ``response``, ``connection``,
``context``, ``timing``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from kali.http_history.models import HttpArtifact

_MARKER_LIMIT = 20_000


@dataclass(frozen=True)
class AttributeRow:
    side: str
    namespace: str
    key: str
    text_value: str | None = None
    numeric_value: float | None = None


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def _project_message(
    side: str,
    message,
    *,
    body_text: str | None = None,
) -> list[AttributeRow]:
    rows: list[AttributeRow] = []
    core = {
        "http_version": _text(getattr(message, "http_version", "")),
    }
    if side == "request":
        core["method"] = _text(getattr(message, "method", ""))
        core["url"] = _text(getattr(message, "url", ""))
    else:
        status = getattr(message, "status", None)
        core["status"] = None if status is None else str(int(status))
        core["reason"] = _text(getattr(message, "reason", ""))
    for key, value in core.items():
        if value is None or value == "":
            continue
        numeric = float(value) if key == "status" and value is not None else None
        rows.append(AttributeRow(side, "core", key, None if numeric is not None else value, numeric))

    for name, value in getattr(message, "headers", []) or []:
        rows.append(AttributeRow(side, "header", str(name).lower(), _text(value)))
    for item in getattr(message, "cookies", []) or []:
        rows.append(AttributeRow(side, "cookie", item.name, _text(item.value)))
    for item in getattr(message, "query", []) or []:
        rows.append(AttributeRow(side, "query", item.name, _text(item.value)))
    for item in getattr(message, "form", []) or []:
        rows.append(AttributeRow(side, "form", item.name, _text(item.value)))

    body_ref = getattr(message, "body_ref", None)
    if body_ref:
        rows.append(AttributeRow(side, "body", "sha256", _text(body_ref.split(":", 1)[-1])))
    body_size = getattr(message, "body_size", 0) or 0
    if body_size:
        rows.append(AttributeRow(side, "body", "size", None, float(body_size)))
    capture_state = getattr(message, "capture_state", None)
    if capture_state and capture_state != "none":
        rows.append(AttributeRow(side, "body", "capture_state", capture_state))
    if body_text:
        rows.append(AttributeRow(side, "body", "marker", body_text[:_MARKER_LIMIT]))
    return rows


def project_attributes(
    artifact: HttpArtifact,
    body_loader: Callable[[str | None], bytes | None] | None = None,
) -> list[AttributeRow]:
    """Return the full attribute projection for one artifact."""
    request_text = _decode_body(artifact.request.body_ref, body_loader)
    rows = _project_message("request", artifact.request, body_text=request_text)

    response = artifact.response
    response_text = None
    if response is not None:
        response_text = _decode_body(response.body_ref, body_loader)
        rows.extend(_project_message("response", response, body_text=response_text))
    else:
        rows.append(AttributeRow("response", "core", "status", "none"))

    connection = artifact.connection
    rows.extend(
        [
            AttributeRow("connection", "core", "client_address", _text(connection.client_address)),
            AttributeRow("connection", "core", "server_address", _text(connection.server_address)),
            AttributeRow("connection", "core", "protocol", _text(connection.protocol)),
            AttributeRow("connection", "tls", "tls", "true" if connection.tls else "false"),
            AttributeRow("connection", "tls", "sni", _text(connection.sni)),
            AttributeRow("connection", "tls", "alpn", _text(connection.alpn)),
        ]
    )

    context = artifact.capture_context
    rows.extend(
        [
            AttributeRow("context", "core", "session_id", _text(context.session_id)),
            AttributeRow("context", "core", "run_id", _text(context.run_id)),
            AttributeRow("context", "core", "spec_id", _text(context.spec_id)),
            AttributeRow("context", "core", "variant_ref", _text(context.variant_ref)),
            AttributeRow("context", "core", "exec_id", _text(context.exec_id)),
        ]
    )
    rows.append(
        AttributeRow("timing", "core", "total_ms", None, float(artifact.timings.total_ms or 0))
    )
    if artifact.error is not None:
        rows.append(AttributeRow("connection", "core", "error_type", _text(artifact.error.type)))
    return [row for row in rows if row.text_value is not None or row.numeric_value is not None]


def _decode_body(
    body_ref: str | None, body_loader: Callable[[str | None], bytes | None] | None
) -> str | None:
    if body_ref is None or body_loader is None:
        return None
    try:
        raw = body_loader(body_ref)
    except Exception:  # noqa: BLE001 - an unreadable blob simply yields no markers
        return None
    if not raw:
        return None
    text = raw.decode("utf-8", "replace")
    # A body with NUL bytes is treated as binary: index no textual marker.
    if "\x00" in text:
        return None
    return text


def fts_document(
    artifact: HttpArtifact,
    body_loader: Callable[[str | None], bytes | None] | None = None,
) -> tuple[str, str]:
    """The FTS row: the URL plus any textual body markers."""
    url = artifact.request.url or ""
    markers = " ".join(
        row.text_value or ""
        for row in project_attributes(artifact, body_loader)
        if row.namespace == "body" and row.key == "marker"
    )
    return url, markers
