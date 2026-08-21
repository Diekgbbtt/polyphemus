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

As of T7 (#157) both are ALSO surfaced as bound `BaseTool`s (D84-16/26) - the
KB wiring hole is closed: `KbRetrieveTool` joins the Runner's `create_agent`
`tools=[exec, kb_retrieve, note]` list exactly like the hunting agent's author
tool, and `ExecTool` is the same terminal behind a typed `args_schema`. Every
pod args schema sets `extra="forbid"` (D84-22): the tool's OWN contract is the
validator - a wrong parameter FAILS as a REJECTED tool call before `_run`.

The specialised fault-targeting tool registry is #71's future home; the browser
probe is #98. This module performs no I/O at import (CODING_STANDARD section 6).
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import shlex
from typing import Any, Callable

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from polymerhus.attack.hunting.pod.config import EXEC_TIMEOUT_S, MAX_POD_ITERS
from polymerhus.attack.hunting.pod.types import ProbeStep, RawObservation
from polymerhus.recon.domain.types import ExecResult

# The injected exec seam: (command, timeout_s) -> ExecResult (async or sync).
ExecFn = Callable[[str, int], ExecResult]

# A sentinel that separates a curl body from its status/timing trailer.
_STATUS_MARK = "__POD_HTTP_STATUS__:"
_TIME_MARK = "__POD_HTTP_TIME__:"


def command_signature(variant_ref: str, command: str) -> str:
    """The O7/C10 dedup key over `(variant_ref, command)`: one execution per
    identical probe within a variant, stable across tool instances (T7)."""
    blob = f"{variant_ref}\x00{command}".encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def default_exec_fn(command: str, timeout_s: int = EXEC_TIMEOUT_S) -> ExecResult:
    """Real terminal: run `command` on the kali exec surface the recon pod uses
    (`execute_command` via the kali MCP). Resolves its client lazily - no I/O at
    import. This is the pod's general-purpose terminal (curl, installers, ...)."""
    from polymerhus.recon.domain.pod import default_exec_fn as recon_exec

    return recon_exec(command, "hunt-pod", timeout_s)


async def _await_seam(fn, *args):
    """Await an async exec seam, else offload a sync one to a worker thread -
    the `_await_seam` pattern mirrored from `hunt_orchestrator.py`."""
    if inspect.iscoroutinefunction(fn):
        return await fn(*args)
    return await asyncio.to_thread(fn, *args)


async def run_with_retry(exec_fn: ExecFn, command: str, *,
                         timeout_s: int = EXEC_TIMEOUT_S,
                         max_iters: int = MAX_POD_ITERS) -> tuple[ExecResult, int]:
    """Run `command`, retrying on a non-zero exit up to `max_iters` (O2/C7).
    Returns the last `ExecResult` and the attempt count. A clean exit (0) stops
    immediately; the caps are pod-internal (D67-09). Async-native (D84-15): each
    attempt rides `_await_seam`, so an async terminal is awaited and a sync one
    (the contract-tier fakes) is offloaded to a worker thread."""
    attempts = 0
    result = ExecResult(stdout="", stderr="no exec performed", returncode=1)
    for attempts in range(1, max(1, max_iters) + 1):
        result = await _await_seam(exec_fn, command, timeout_s)
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


# --- the bound-tool surface (T7, D84-16/22/26) --------------------------------

class KbRetrieveSpec(BaseModel):
    """The `kb_retrieve` tool's ARGS contract: an NL query citing ontology
    elements, the typed join-key hints (#66). `extra="forbid"` (D84-22) rejects
    a parameter outside this contract BEFORE `_run`; the pod's contract never
    carries a retrieval config or LLM-generation switch."""

    query: str
    fault_id: str = ""
    technological_axis: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class KbRetrieveTool(BaseTool):
    """The NL knowledge-base retrieval tool as a bound `BaseTool` (D84-16/26):
    the same fail-open `SymptomTechniqueQuery` seam, behind `extra="forbid"`
    args validation. A not-ready or raising KB yields the EMPTY result - the
    runner degrades to the spec's own primitives (O13), never a raise."""

    name: str = "kb_retrieve"
    description: str = (
        "Query the fault knowledge base in natural language, citing any ontology "
        "element(s) (fault, symptom, assumption, defence, payload, vector, "
        "strategy, technology), singly or combined, to ground a probe or a "
        "payload family. Returns symptoms and probing techniques; an empty "
        "result means the KB has nothing further - degrade to the spec's own "
        "primitives and continue."
    )
    args_schema: type[BaseModel] = KbRetrieveSpec

    def __init__(self, *, kb_fn: Callable | None = None,
                 lookup: Callable | None = None, **kwargs):
        super().__init__(**kwargs)
        self._kb_fn = kb_fn      # the pod's plain `kb_retrieve`-shaped seam
        self._lookup = lookup    # the symptom_kb-shaped fixture (contract tier)

    def _run(self, **kwargs: Any) -> str:
        spec = KbRetrieveSpec(**kwargs)
        try:
            if self._kb_fn is not None:
                result = self._kb_fn(
                    spec.query, fault_id=spec.fault_id,
                    technological_axis=tuple(spec.technological_axis)) or {}
                return json.dumps({
                    "symptoms": list(result.get("symptoms") or []),
                    "techniques": list(result.get("techniques") or []),
                    "source": result.get("source"),
                })
            from polymerhus.attack.hunting.symptom_kb import (  # noqa: PLC0415
                SymptomTechniqueQuery,
                query_symptom_technique,
            )

            typed = SymptomTechniqueQuery(
                fault_id=spec.fault_id or spec.query,
                technological_axis=tuple(spec.technological_axis),
            )
            result = query_symptom_technique(typed, lookup=self._lookup)
            return json.dumps({
                "symptoms": list(result.symptoms),
                "techniques": list(result.techniques),
                "source": result.source,
            })
        except Exception:  # noqa: BLE001 - fail-open is the contract (O13)
            return json.dumps({"symptoms": [], "techniques": [], "source": None})


class ExecSpec(BaseModel):
    """The `exec` tool's ARGS contract: the exact command to run. The per-exec
    caps are the POD's (D67-09) - `EXEC_TIMEOUT_S` / `MAX_POD_ITERS` are not
    model-chosen fields."""

    command: str

    model_config = ConfigDict(extra="forbid")


class ExecTool(BaseTool):
    """The general-purpose terminal as a bound `BaseTool`: runs `exec_fn`
    through `run_with_retry` (the pod's fixed caps), records the result RAW as a
    `RawObservation` into the D6 log (G4), and marks its O7/C10 execution
    signature. The pre-run dedup gate (O7) lives in the HARVEST middleware -
    this tool records unconditionally, the harness short-circuits a repeat."""

    name: str = "exec"
    description: str = (
        "Run a command on the target's execution surface: any command-line tool "
        "(curl for HTTP probes, package managers to install a tool you lack). "
        "Every result - status, body marker, timing - is recorded raw in the "
        "experiment log. The pod applies its own time/retry caps."
    )
    args_schema: type[BaseModel] = ExecSpec

    def __init__(self, *, exec_fn: ExecFn, log, variant_ref: str, **kwargs):
        super().__init__(**kwargs)
        self._exec_fn = exec_fn
        self._log = log
        self._variant_ref = variant_ref

    def _signature(self, command: str) -> str:
        """The variant-scoped dedup signature (O7/C10) - shared with the harness."""
        return command_signature(self._variant_ref, command)

    def _record(self, command: str, result: ExecResult) -> str:
        sig = self._signature(command)
        parsed = parse_curl(result)
        observation = RawObservation(
            probe_ref=sig, variant_ref=self._variant_ref,
            request={"command": command},
            status=parsed.get("status"), body=parsed.get("body", "") or result.stdout,
            stdout=result.stdout, stderr=result.stderr, returncode=result.returncode,
            duration_ms=result.duration_ms or parsed.get("time_ms", 0))
        self._log.mark_executed(sig)
        self._log.record_observation(observation)
        return (f"TOOL RESULT: status={observation.status} "
                f"body={observation.body[:400]!r} stderr={observation.stderr[:200]!r}")

    def _run(self, **kwargs: Any) -> str:
        spec = ExecSpec(**kwargs)
        from polymerhus.recon.control.async_bridge import run_coro_blocking

        result, _attempts = run_coro_blocking(run_with_retry(
            self._exec_fn, spec.command, timeout_s=EXEC_TIMEOUT_S, max_iters=MAX_POD_ITERS))
        return self._record(spec.command, result)

    async def _arun(self, **kwargs: Any) -> str:
        spec = ExecSpec(**kwargs)
        result, _attempts = await run_with_retry(
            self._exec_fn, spec.command, timeout_s=EXEC_TIMEOUT_S, max_iters=MAX_POD_ITERS)
        return self._record(spec.command, result)
