# kali/http_history/capabilities.py
"""The #238 follow-up runtime-capability surface (Task 7).

What this process can actually ENFORCE and PROVE, exposed so the controller can
refuse an incompatible companion BEFORE any target traffic:

* the supported `traffic-policy` versions (an old Kali that only understands v1
  has no concurrency ceiling - assuming enforcement would be the bug);
* the image's build provenance (source revision + the vegeta MODULE version read
  from Go build metadata, never from the human-readable `vegeta -version`);
* the cardinality of a pinned wordlist, so a job's declared request cost is tied
  to the file actually present in the image.

Everything here is a pure function with a lazy, injectable seam: importing the
module performs no I/O.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

from kali.http_history.governor import SUPPORTED_POLICY_VERSIONS

#: The image writes this at build time (Dockerfile.kali). Absent in a host-side
#: dev tree - the reader degrades to the env/unknown triple rather than failing.
BUILD_PROVENANCE_PATH = "/opt/polymerhus/build-provenance.json"

VEGETA_MODULE = "github.com/tsenart/vegeta/v12"
EXPECTED_VEGETA_VERSION = "v12.13.0"
"""The pinned vegeta release. The mapping's traffic shape must be reproducible
from one image to the next, so the module version - not the CLI banner - is the
identity that matters."""

FFUF_WORDLIST_PATH = "/usr/share/seclists/Discovery/Web-Content/common.txt"
"""The pinned ffuf content-discovery wordlist the ffuf `JobSpec` declares its
per-input request cost against."""


class CapabilityError(RuntimeError):
    """A required runtime capability is missing or unsupported. Loud on purpose:
    the caller refuses the traffic, never assumes enforcement."""


def supported_policy_versions() -> tuple[str, ...]:
    """The `traffic-policy` versions this governor can enforce."""
    return tuple(SUPPORTED_POLICY_VERSIONS)


def require_policy_version(advertised: Sequence[str], required: str) -> None:
    """Raise unless `required` is among the `advertised` versions. This is the
    controller/Kali negotiation: a mismatch refuses before egress."""
    if required not in set(advertised):
        raise CapabilityError(
            f"this governor does not support {required!r} "
            f"(advertised: {sorted(advertised)})"
        )


def build_provenance(path: str | os.PathLike | None = None) -> dict:
    """The image's build provenance, or a degraded but honest triple when the
    build-time file is absent (a host-side dev tree)."""
    provenance_path = Path(
        path or os.environ.get("POLYPHEMUS_BUILD_PROVENANCE", BUILD_PROVENANCE_PATH)
    )
    try:
        payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {
            "revision": os.environ.get("SOURCE_REVISION", "unknown"),
            "vegeta_module": VEGETA_MODULE,
            "vegeta_version": None,
            "source": "unavailable",
        }
    if not isinstance(payload, dict):
        return {
            "revision": "unknown", "vegeta_module": VEGETA_MODULE,
            "vegeta_version": None, "source": "unavailable",
        }
    payload.setdefault("vegeta_module", VEGETA_MODULE)
    payload.setdefault("source", str(provenance_path))
    return payload


def vegeta_module_version(vegeta_path: str | None = None) -> str | None:
    """The vegeta MODULE version from Go build metadata, or None.

    `go version -m <binary>` prints one tab-separated record per module; the
    binary's own main module is the `mod` record. The human-readable
    `vegeta -version` output is NOT the source of truth (a `go install` build can
    report empty human fields).
    """
    binary = vegeta_path or shutil.which("vegeta")
    if not binary:
        return None
    try:
        completed = subprocess.run(
            ["go", "version", "-m", binary],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    for line in completed.stdout.splitlines():
        fields = line.strip().split()
        if len(fields) >= 3 and fields[0] == "mod" and fields[1] == VEGETA_MODULE:
            return fields[2]
    return None


def wordlist_cardinality(path: str | os.PathLike) -> int | None:
    """The NON-EMPTY-LINE count of a wordlist, or None when unreadable."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return sum(1 for line in text.splitlines() if line)


def verify_wordlist(path: str | os.PathLike, expected: int) -> int:
    """Return the verified cardinality, or raise naming the file and both counts.

    This is the contract behind `estimate_job_requests`' `cardinalities` override:
    a missing or changed wordlist must fail readiness rather than silently
    underestimate a request-intensive job's cost.
    """
    actual = wordlist_cardinality(path)
    if actual is None:
        raise CapabilityError(
            f"wordlist {str(path)!r} is missing or unreadable (expected {expected} entries)"
        )
    if actual != expected:
        raise CapabilityError(
            f"wordlist {str(path)!r} has {actual} entries, expected {expected}"
        )
    return actual


def governance_capabilities(*, capture_enabled: bool, governor_enabled: bool) -> dict:
    """The immutable `traffic_governor` block `proxy_status()` reports."""
    return {
        "governor_enabled": bool(governor_enabled),
        "capture_enabled": bool(capture_enabled),
        "supported_policy_versions": list(supported_policy_versions()),
    }


def wordlist_capabilities(
    paths: Sequence[str] = (FFUF_WORDLIST_PATH,),
) -> dict:
    """`{path: non_empty_line_count | None}` for every pinned wordlist."""
    return {str(path): wordlist_cardinality(path) for path in paths}
