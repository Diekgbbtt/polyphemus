"""Pure extraction of compact JavaScript leads from producer output."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class ExtractedLead:
    exact_url: str
    discovery_class: str
    status: int | None = None
    content_type: str | None = None
    discovery_classes: tuple[str, ...] = ()
    script_ids: tuple[str, ...] = ()


@dataclass
class Extraction:
    leads: list[ExtractedLead] = field(default_factory=list)
    parse_errors: int = 0
    completeness: str = "complete"


_JS_CONTENT_TYPES = {
    "application/ecmascript",
    "application/javascript",
    "application/node",
    "application/x-javascript",
    "text/ecmascript",
    "text/javascript",
}
_JS_SUFFIXES = (".js", ".mjs", ".cjs")


def _is_js_candidate(url: str, content_type: str | None) -> bool:
    try:
        path = urlsplit(url).path.lower()
    except ValueError:
        path = ""
    if path.endswith(_JS_SUFFIXES):
        return True
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    return mime in _JS_CONTENT_TYPES


def _header_value(headers: object, name: str) -> str | None:
    if not isinstance(headers, dict):
        return None
    wanted = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == wanted and isinstance(value, str):
            return value
    return None


def _status(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def extract_katana(stdout: str) -> Extraction:
    """Extract JS candidates by physical newline, never by Unicode line breaks."""
    result = Extraction()
    seen: set[str] = set()
    for raw_line in stdout.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            result.parse_errors += 1
            continue
        if not isinstance(entry, dict):
            result.parse_errors += 1
            continue
        request = entry.get("request")
        if not isinstance(request, dict) or not isinstance(request.get("endpoint"), str):
            result.parse_errors += 1
            continue
        exact_url = request["endpoint"]
        if not exact_url:
            result.parse_errors += 1
            continue
        response = entry.get("response")
        if not isinstance(response, dict):
            response = {}
        content_type = _header_value(response.get("headers"), "content-type")
        if not _is_js_candidate(exact_url, content_type) or exact_url in seen:
            continue
        seen.add(exact_url)
        result.leads.append(
            ExtractedLead(
                exact_url=exact_url,
                discovery_class="crawler_discovered",
                status=_status(response.get("status_code")),
                content_type=content_type,
            )
        )
    if result.parse_errors:
        result.completeness = "partial"
    return result


def extract_ffuf(stdout: str) -> Extraction:
    result = Extraction()
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        start = stdout.find("{")
        try:
            payload = json.loads(stdout[start:]) if start >= 0 else None
        except (json.JSONDecodeError, TypeError):
            payload = None
    if not isinstance(payload, dict):
        result.parse_errors = 1
        result.completeness = "partial"
        return result
    entries = payload.get("results")
    if not isinstance(entries, list):
        result.parse_errors = 1
        result.completeness = "partial"
        return result

    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            result.parse_errors += 1
            continue
        exact_url = entry.get("url")
        if not isinstance(exact_url, str) or not exact_url:
            result.parse_errors += 1
            continue
        content_type = entry.get("content-type") or entry.get("content_type")
        if not isinstance(content_type, str):
            content_type = None
        if not _is_js_candidate(exact_url, content_type) or exact_url in seen:
            continue
        seen.add(exact_url)
        result.leads.append(
            ExtractedLead(
                exact_url=exact_url,
                discovery_class="path_probed",
                status=_status(entry.get("status")),
                content_type=content_type,
            )
        )
    if result.parse_errors:
        result.completeness = "partial"
    return result


def extract_steel(manifest: dict | None) -> Extraction:
    if not isinstance(manifest, dict):
        return Extraction(parse_errors=1, completeness="partial")
    if manifest.get("schema_version") == "steel-crawl/v2":
        return _extract_steel_v2(manifest)
    result = Extraction(completeness="unknown")
    js_urls = manifest.get("js_urls")
    if not isinstance(js_urls, list):
        result.parse_errors = 1
        result.completeness = "partial"
        return result
    seen: set[str] = set()
    for value in js_urls:
        if not isinstance(value, str) or not value:
            result.parse_errors += 1
            continue
        if value in seen:
            continue
        seen.add(value)
        result.leads.append(
            ExtractedLead(
                exact_url=value,
                discovery_class="browser_requested",
            )
        )
    if result.parse_errors:
        result.completeness = "partial"
    return result


def _extract_steel_v2(manifest: dict) -> Extraction:
    """Read v2 graph inputs while keeping debugger and HTTP provenance distinct."""
    result = Extraction(completeness="complete")
    records: dict[str, dict] = {}

    def add(url, discovery_class, *, status=None, script_id=None):
        if not isinstance(url, str) or not url:
            result.parse_errors += 1
            return
        row = records.setdefault(
            url,
            {
                "classes": set(),
                "statuses": set(),
                "script_ids": set(),
            },
        )
        row["classes"].add(discovery_class)
        if status is not None:
            row["statuses"].add(status)
        if script_id:
            row["script_ids"].add(script_id)

    endpoints = manifest.get("endpoints")
    if not isinstance(endpoints, list):
        result.parse_errors += 1
        endpoints = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            result.parse_errors += 1
            continue
        url = endpoint.get("url")
        resource_type = str(endpoint.get("resource_type") or "").lower()
        if not _is_js_candidate(str(url or ""), None) and resource_type != "script":
            continue
        provenance = endpoint.get("provenance")
        if provenance == "observed":
            classification = "browser_requested"
        elif provenance == "declared":
            classification = "crawl_declared"
        else:
            result.parse_errors += 1
            continue
        add(url, classification, status=_status(endpoint.get("status_code")))

    scripts = manifest.get("scripts")
    if not isinstance(scripts, list):
        result.parse_errors += 1
        scripts = []
    for script in scripts:
        if not isinstance(script, dict):
            result.parse_errors += 1
            continue
        url = script.get("script_url")
        script_id = script.get("script_id")
        # ScriptAsset is debugger evidence of a script, regardless of suffix.
        # Only HTTP(S) references can use the existing acquisition broker.
        try:
            if not isinstance(url, str) or not url or any(
                ord(char) <= 32 or ord(char) == 127 for char in url
            ):
                raise ValueError("invalid_script_url")
            parts = urlsplit(url)
            if (
                parts.scheme.lower() not in {"http", "https"}
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
            ):
                raise ValueError("unacquirable_script_url")
            parts.port  # Validate malformed or out-of-range ports before storage.
        except ValueError:
            result.parse_errors += 1
            continue
        add(
            url,
            "debugger_script",
            script_id=script_id if isinstance(script_id, str) else None,
        )

    priority = (
        "browser_requested",
        "crawl_declared",
        "debugger_script",
    )
    for url, row in records.items():
        classes = tuple(
            discovery for discovery in priority if discovery in row["classes"]
        )
        statuses = row["statuses"]
        result.leads.append(
            ExtractedLead(
                exact_url=url,
                discovery_class=classes[0],
                status=next(iter(statuses)) if len(statuses) == 1 else None,
                content_type=None,
                discovery_classes=classes,
                script_ids=tuple(sorted(row["script_ids"])),
            )
        )
    if result.parse_errors:
        result.completeness = "partial"
    return result
