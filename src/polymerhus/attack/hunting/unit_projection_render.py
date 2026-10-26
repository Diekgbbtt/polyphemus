"""Pure Markdown renderer for one unit projection.

The renderer is the modeller's grounding view. It keeps the analysis unit
coherent: each cooperating Service carries its contract and its aggregated
endpoints, each endpoint carries its parameters, and each baseURL carries its
deduplicated headers. It never truncates an endpoint.
"""
from __future__ import annotations

from .unit_projection import UnitProjection


_SECRET_HEADERS = frozenset({
    "set-cookie", "cookie", "authorization", "proxy-authorization",
})


def _contract(system) -> str:
    props = system.props or {}
    return str(props.get("service_contract") or system.description or "")


def _header_value(name, value) -> str:
    text = str(value or "")
    if (name or "").lower() not in _SECRET_HEADERS:
        return text
    parts = text.split(";", 1)
    suffix = f";{parts[1]}" if len(parts) > 1 else ""
    return f"<redacted>{suffix}"


def _render_endpoint(endpoint, lines: list[str], indent: str) -> None:
    method = endpoint.method or "GET"
    path = endpoint.path or "/"
    details = []
    if endpoint.status_code is not None:
        details.append(str(endpoint.status_code))
    if endpoint.content_type:
        details.append(str(endpoint.content_type))
    if endpoint.content_length is not None:
        details.append(f"{endpoint.content_length} B")
    suffix = f" ({', '.join(details)})" if details else ""
    lines.append(f"{indent}- {method} {path}{suffix}")
    if endpoint.parameters:
        for parameter in endpoint.parameters:
            position = parameter.position or "unknown"
            lines.append(f"{indent}  - parameter: {parameter.name} ({position})")
    else:
        lines.append(f"{indent}  - Parameters: none observed")


def render_unit_projection(projection: UnitProjection) -> str:
    lines = [f"## Unit: {projection.unit_id} ({projection.kind})"]

    services = []
    for systems in (projection.cooperating_systems or {}).values():
        for system in systems:
            if system.kind == "Service":
                services.append(system)
    services.sort(key=lambda s: (s.discriminator or ""))
    service_slugs = {s.discriminator for s in services}

    for service in services:
        slug = service.discriminator or "(unknown)"
        lines.append(f"### Service: {slug}")
        contract = _contract(service)
        if contract:
            lines.append(f"Contract: {contract}")
        endpoints = [
            e for e in projection.aggregated_endpoints
            if e.service_slug == slug
        ]
        endpoints.sort(key=lambda e: (e.baseurl or "", e.path or "", e.method or ""))
        if endpoints:
            for endpoint in endpoints:
                _render_endpoint(endpoint, lines, "  ")
        else:
            lines.append("  - endpoints: none observed")

    systems = []
    for family, neighbors in (projection.cooperating_systems or {}).items():
        for system in neighbors:
            if system.kind != "Service":
                systems.append((family, system))
    for family, system in sorted(
            systems,
            key=lambda item: (item[1].kind or "", item[1].discriminator or "", item[0])):
        label = f"{system.kind}:{system.discriminator}"
        lines.append(f"### System: {label}")
        if system.description:
            lines.append(f"Description: {system.description}")
        lines.append(f"Relationship: {family}")

    if projection.kind == "Service":
        endpoints = sorted(
            projection.aggregated_endpoints,
            key=lambda e: (e.baseurl or "", e.path or "", e.method or ""),
        )
        if endpoints:
            lines.append("### Endpoints")
            for endpoint in endpoints:
                _render_endpoint(endpoint, lines, "  ")
    else:
        orphans = sorted(
            (e for e in projection.aggregated_endpoints
             if e.service_slug not in service_slugs),
            key=lambda e: (e.baseurl or "", e.path or "", e.method or ""),
        )
        if orphans:
            lines.append("### Endpoints without a cooperating service")
            for endpoint in orphans:
                _render_endpoint(endpoint, lines, "  ")

    if projection.baseurl_headers:
        lines.append("### BaseURLs and headers")
        for baseurl in sorted(projection.baseurl_headers):
            lines.append(f"#### BaseURL {baseurl}")
            for header in projection.baseurl_headers[baseurl]:
                direction = header.direction or "response"
                lines.append(
                    f"- [{direction}] {header.name}: "
                    f"{_header_value(header.name, header.value)}"
                )

    return "\n".join(lines)
