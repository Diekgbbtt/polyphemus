"""Bounded jsluice scans over one already-acquired local JavaScript file."""

from __future__ import annotations

import hashlib
import json
import shutil
import re
from urllib.parse import urlsplit, urlunsplit
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

try:
    from polymerhus.recon.domain.parsers._secrets import extract_secret_value
    from polymerhus.recon.js_intake.redaction import redact_url
    from polymerhus.recon.scripts.jsluice_scan import (
        JsluiceProcessResult,
        run_jsluice_file,
    )
except ModuleNotFoundError:  # installed flat in Kali
    from _secrets import extract_secret_value
    from redaction import redact_url  # type: ignore[no-redef]
    from jsluice_scan import (  # type: ignore[no-redef]
        JsluiceProcessResult,
        run_jsluice_file,
    )


@dataclass(frozen=True)
class ScanLimits:
    max_input_bytes: int = 8 * 1024 * 1024
    mode_timeout_s: float = 15
    max_mode_output_bytes: int = 1024 * 1024

    def __post_init__(self):
        if any(value <= 0 for value in vars(self).values()):
            raise ValueError("scan limits must be positive")


CANDIDATE_SCHEMA_VERSION = 2
_MODES = ("urls", "secrets")
PATTERN_FINGERPRINT = hashlib.sha256(
    b"jsluice-builtin-patterns-v1"
).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_options() -> dict:
    return {mode: [mode, "-j"] for mode in _MODES}


def binary_identity(executable: str) -> dict:
    resolved = shutil.which(executable) or executable
    path = Path(resolved)
    if not path.is_file():
        return {"path": executable, "sha256": None, "version": None}
    return {
        "path": resolved,
        "sha256": _hash_file(path),
        "version": None,
    }


def scan_key_for(
    *,
    source_sha256: str,
    binary: dict,
    options: dict,
    pattern_fingerprint: str,
    candidate_schema_version: int = CANDIDATE_SCHEMA_VERSION,
) -> str:
    key_body = json.dumps(
        {
            "candidate_schema_version": candidate_schema_version,
            "source_sha256": source_sha256,
            "binary_sha256": binary.get("sha256"),
            "version": binary.get("version"),
            "options": options,
            "pattern_fingerprint": pattern_fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(key_body.encode()).hexdigest()


def candidate_id_for(candidate: dict) -> str:
    stable = json.dumps(
        {
            key: value
            for key, value in candidate.items()
            if key != "candidate_id"
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "cand_" + hashlib.sha256(stable.encode()).hexdigest()[:24]


def _safe_names(value) -> list[str]:
    if not isinstance(value, list):
        return []
    # Never manufacture an identity by truncating a parameter name.
    return [item for item in value[:100] if isinstance(item, str)
            and 0 < len(item) <= 120 and not re.search(r"[\s\[\]<>]|[A-Za-z0-9_-]{24,}", item)]


def _label(value, limit=120):
    return value if isinstance(value, str) and len(value) <= limit and re.fullmatch(r"[A-Za-z0-9_. -]+", value) else "unknown"


def _candidate(
    *,
    mode: str,
    source_sha256: str,
    line_number: int,
    entry: dict,
) -> dict | None:
    locator = f"{mode}:line:{line_number}"
    if mode == "urls":
        url = entry.get("url")
        if not isinstance(url, str) or not url:
            return None
        try:
            redacted_url = redact_url(url)
            raw_parts = urlsplit(url)
            safe_parts = urlsplit(redacted_url)
            # Preserve existing parser's case/port identity, dropping userinfo.
            redacted_url = urlunsplit(safe_parts._replace(netloc=raw_parts.netloc.rsplit('@', 1)[-1]))
        except ValueError:
            redacted_url = "[REDACTED_URL]"
        method = entry.get("method") or "GET"
        query_names = _safe_names(entry.get("queryParams"))
        body_names = _safe_names(entry.get("bodyParams"))
        url_truncated = len(redacted_url) > 2048
        if url_truncated:
            redacted_url = redacted_url[:2025] + "...[TRUNCATED]"
        candidate = {
            "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
            "mode": mode,
            "source_sha256": source_sha256,
            "record_locator": locator,
            "redacted_url": redacted_url,
            "url_truncated": url_truncated,
            "safe_metadata": {
                "kind": _label(entry.get("kind") or entry.get("type")),
                "method": method.upper() if isinstance(method, str) and len(method) <= 16 else None,
                "method_truncated": not isinstance(method, str) or len(method) > 16,
                "query_param_names": query_names,
                "body_param_names": body_names,
                "parameter_names_limited": any(isinstance(entry.get(k), list) and len(entry[k]) != len(v)
                                               for k, v in (("queryParams", query_names), ("bodyParams", body_names))),
            },
        }
    else:
        secret = extract_secret_value(entry)
        if not secret:
            return None
        candidate = {
            "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
            "mode": mode,
            "source_sha256": source_sha256,
            "record_locator": locator,
            "secret_kind": _label(entry.get("kind")),
            "severity": _label(entry.get("severity"), 40),
            "secret_hash_algorithm": "sha1",
            "secret_fingerprint": hashlib.sha1(secret.encode()).hexdigest(),
        }
    if mode == "urls":
        # Bound the complete candidate, including URL and metadata, before output.
        meta = candidate["safe_metadata"]
        while len(json.dumps(candidate, sort_keys=True, separators=(",", ":")).encode()) > 3950:
            target = max(("query_param_names", "body_param_names"), key=lambda k: len(meta[k]))
            if not meta[target]:
                break
            meta[target].pop()
            meta["parameter_names_limited"] = True
    candidate["candidate_id"] = candidate_id_for(candidate)
    return candidate


def _parse_mode(
    *,
    mode: str,
    process: JsluiceProcessResult,
    source_sha256: str,
) -> tuple[list[dict], dict]:
    candidates = []
    malformed = 0
    unclassified = 0
    for line_number, raw_line in enumerate(process.stdout.split("\n"), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(entry, dict):
            malformed += 1
            continue
        candidate = _candidate(
            mode=mode,
            source_sha256=source_sha256,
            line_number=line_number,
            entry=entry,
        )
        if candidate is None:
            unclassified += 1
        else:
            candidates.append(candidate)

    if process.error:
        status = "partial" if candidates else "failed"
    elif process.timed_out or process.output_exceeded:
        status = "partial" if candidates else "failed"
    elif process.returncode not in (0, None):
        status = "partial" if candidates else "failed"
    elif malformed or unclassified:
        status = "partial"
    else:
        status = "complete"
    state = {
        "status": status,
        "candidate_count": len(candidates),
        "malformed_lines": malformed,
        "unclassified_records": unclassified,
        "returncode": process.returncode,
        "stderr_bytes": process.stderr_bytes,
        "timed_out": process.timed_out,
        "output_exceeded": process.output_exceeded,
        "error": process.error or (
            f"exit_{process.returncode}"
            if process.returncode not in (0, None)
            else None
        ),
        "duration_ms": process.duration_ms,
        "options": [mode, "-j"],
    }
    return candidates, state


def _invalid_source(error: str, *, expected_sha256: str, expected_size: int) -> dict:
    return {
        "schema_version": 1,
        "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
        "status": "failed",
        "error": error,
        "source": {
            "expected_sha256": expected_sha256,
            "expected_size": expected_size,
        },
        "modes": {},
        "candidates": [],
    }


def scan_local_file(
    path: str | Path,
    *,
    expected_sha256: str,
    expected_size: int,
    executable: str = "jsluice",
    limits: ScanLimits | None = None,
    executor: Callable[..., JsluiceProcessResult] | None = None,
    binary_info: dict | None = None,
) -> dict:
    limits = limits or ScanLimits()
    source = Path(path)
    if not source.is_file():
        return _invalid_source(
            "source_missing",
            expected_sha256=expected_sha256,
            expected_size=expected_size,
        )
    actual_size = source.stat().st_size
    if actual_size != expected_size:
        return _invalid_source(
            "source_size_mismatch",
            expected_sha256=expected_sha256,
            expected_size=expected_size,
        )
    if actual_size > limits.max_input_bytes:
        return _invalid_source(
            "source_too_large",
            expected_sha256=expected_sha256,
            expected_size=expected_size,
        )
    actual_sha = _hash_file(source)
    if actual_sha != expected_sha256:
        return _invalid_source(
            "source_hash_mismatch",
            expected_sha256=expected_sha256,
            expected_size=expected_size,
        )

    run = executor or run_jsluice_file
    info = binary_info or binary_identity(executable)
    candidates: list[dict] = []
    modes: dict[str, dict] = {}
    for mode in _MODES:
        try:
            process = run(
                mode,
                source,
                timeout_s=limits.mode_timeout_s,
                max_output_bytes=limits.max_mode_output_bytes,
                executable=executable,
            )
        except FileNotFoundError:
            process = JsluiceProcessResult(
                stdout="",
                returncode=None,
                error="binary_missing",
            )
        except Exception:
            process = JsluiceProcessResult(
                stdout="",
                returncode=None,
                error="scanner_failed",
            )
        mode_candidates, state = _parse_mode(
            mode=mode,
            process=process,
            source_sha256=actual_sha,
        )
        candidates.extend(mode_candidates)
        modes[mode] = state

    statuses = {state["status"] for state in modes.values()}
    if statuses == {"complete"}:
        status = "complete"
    elif statuses == {"failed"}:
        status = "failed"
    else:
        status = "partial"
    options = scan_options()
    scan_key = scan_key_for(
        source_sha256=actual_sha,
        binary=info,
        options=options,
        pattern_fingerprint=PATTERN_FINGERPRINT,
    )
    return {
        "schema_version": 1,
        "candidate_schema_version": CANDIDATE_SCHEMA_VERSION,
        "status": status,
        "source": {
            "sha256": actual_sha,
            "size": actual_size,
        },
        "binary": {
            "path": info.get("path") or executable,
            "sha256": info.get("sha256"),
            "version": info.get("version"),
        },
        "options": options,
        "pattern_fingerprint": PATTERN_FINGERPRINT,
        "scan_key": scan_key,
        "limits": asdict(limits),
        "modes": modes,
        "candidates": candidates,
    }


__all__ = [
    "ScanLimits",
    "scan_local_file",
]
