"""The pod's minimal tool surface (spec 1.4, 6.8) with enforcement.

Two tools, both injectable so the contract tier runs without a live target:

  * A general-purpose terminal (`exec`): the recon pod's kali exec surface,
    reused verbatim - any command-line tool (curl for HTTP probing) plus package
    managers to install a tool the pod lacks. Each call is bounded by
    `EXEC_TIMEOUT_S`; a non-zero exit is retried up to `MAX_POD_ITERS` (O2/C7).
  * The knowledge-base retrieval tool (`kb_retrieve`, the prompts' `{KB_TOOL}`):
    an inert fail-open NL stub typed per the merged #66 seam
    (`SymptomTechniqueQuery`/`SymptomTechniqueResult`); a not-ready or raising KB
    yields an empty result and never fabricates (CODING_STANDARD section 12). A
    contract-tier caller injects a fixture `lookup`.

The specialised fault-targeting tool registry is #71's future home; the browser
probe is #98. This module performs no I/O at import (CODING_STANDARD section 6).
"""
from __future__ import annotations

import shlex
import time
from typing import Callable

from polymerhus.attack.hunting.pod.config import EXEC_TIMEOUT_S, MAX_POD_ITERS
from polymerhus.attack.hunting.pod.types import ProbeStep
from polymerhus.recon.domain.types import ExecResult

# The injected exec seam: (command, timeout_s) -> ExecResult.
ExecFn = Callable[[str, int], ExecResult]

# A sentinel that separates a curl body from its status/timing trailer.
_STATUS_MARK = "__POD_HTTP_STATUS__:"
_TIME_MARK = "__POD_HTTP_TIME__:"


def default_exec_fn(command: str, timeout_s: int = EXEC_TIMEOUT_S) -> ExecResult:
    """Real terminal: run `command` on the kali exec surface the recon pod uses
    (`execute_command` via the kali MCP). Resolves its client lazily - no I/O at
    import. This is the pod's general-purpose terminal (curl, installers, ...)."""
    from polymerhus.recon.domain.pod import default_exec_fn as recon_exec

    return recon_exec(command, "hunt-pod", timeout_s)


def run_with_retry(exec_fn: ExecFn, command: str, *,
                   timeout_s: int = EXEC_TIMEOUT_S,
                   max_iters: int = MAX_POD_ITERS) -> tuple[ExecResult, int]:
    """Run `command`, retrying on a non-zero exit up to `max_iters` (O2/C7).
    Returns the last `ExecResult` and the attempt count. A clean exit (0) stops
    immediately; the caps are pod-internal (D67-09)."""
    attempts = 0
    result = ExecResult(stdout="", stderr="no exec performed", returncode=1)
    for attempts in range(1, max(1, max_iters) + 1):
        result = exec_fn(command, timeout_s)
        if result.returncode == 0:
            break
    return result, attempts


def curl_command(step: ProbeStep) -> str:
    """Build a curl command for an HTTP probe step. `-k` (self-signed TLS on the
    eval target), `-sS` (quiet but show errors), a `-w` trailer carrying the
    status code and total time so the body and the status round-trip through one
    stdout stream."""
    parts = ["curl", "-k", "-sS", "-X", shlex.quote(step.method or "GET")]
    for name, value in (step.headers or {}).items():
        parts += ["-H", shlex.quote(f"{name}: {value}")]
    if step.body:
        parts += ["--data", shlex.quote(step.body)]
    trailer = f"\\n{_STATUS_MARK}%{{http_code}}\\n{_TIME_MARK}%{{time_total}}"
    parts += ["-w", shlex.quote(trailer), shlex.quote(step.url)]
    return " ".join(parts)


def parse_curl(result: ExecResult) -> dict:
    """Parse a `curl_command` run into `{status, body, time_ms}`. A missing
    status trailer (connection refused, DNS failure) leaves `status=None`, which
    the symbolic layer reads as an infeasibility signal."""
    out = result.stdout or ""
    status: int | None = None
    time_ms = 0
    body = out
    if _STATUS_MARK in out:
        body, _, tail = out.partition(f"\n{_STATUS_MARK}")
        status_str, _, rest = tail.partition("\n")
        try:
            status = int(status_str.strip())
        except ValueError:
            status = None
        if _TIME_MARK in rest:
            try:
                time_ms = int(float(rest.split(_TIME_MARK, 1)[1].strip()) * 1000)
            except (ValueError, IndexError):
                time_ms = 0
    return {"status": status, "body": body, "time_ms": time_ms}


# --- The knowledge-base retrieval tool (the prompts' {KB_TOOL}) -----------------

def kb_retrieve(query: str, *, fault_id: str = "",
                technological_axis: tuple[str, ...] = (),
                lookup=None) -> dict:
    """The pod's NL knowledge-base retrieval tool (spec section 3 KB stub).

    Accepts a natural-language `query` (citing ontology elements) and the typed
    join-key hints, wraps the merged #66 typed seam, and NEVER crashes: a
    not-ready or raising KB yields an empty result. A contract-tier caller
    injects a fixture `lookup` (the in-memory fixture KB). The technological
    axis and the technical-axis SYSTEM_KINDS never share a field (FKB-6): this
    tool carries only the technological axis."""
    from polymerhus.attack.hunting.symptom_kb import (
        SymptomTechniqueQuery,
        query_symptom_technique,
    )

    typed_query = SymptomTechniqueQuery(
        fault_id=fault_id or query,
        technological_axis=tuple(technological_axis),
    )
    try:
        result = query_symptom_technique(typed_query, lookup=lookup)
    except Exception:  # noqa: BLE001 - fail-open is the contract
        return {"symptoms": [], "techniques": [], "source": None}
    return {
        "symptoms": list(result.symptoms),
        "techniques": list(result.techniques),
        "source": result.source,
    }
