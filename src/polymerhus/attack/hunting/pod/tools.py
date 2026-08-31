"""The pod's minimal tool surface (spec 1.4, 6.8) with enforcement.

One core tool, injectable so the contract tier runs without a live target:

  * A general-purpose terminal (`exec`): the recon pod's kali exec surface,
    reused verbatim - any command-line tool (curl for HTTP probing) plus package
    managers to install a tool the pod lacks. Each call is bounded by
    `EXEC_TIMEOUT_S`; a non-zero exit is retried up to `MAX_POD_ITERS` (O2/C7).

The KB query capability is the single `query_lightrag` tool from the lightrag
branch (the pod runner can be configured with it, exactly like the hunting
agent's author lane, always-bound as of #197); the former
`symptom-technique` typed seam (surface B) is retired.

As of T7 (#157) `exec` is ALSO surfaced as a bound `BaseTool` (D84-16/26).
Every pod args schema sets `extra="forbid"` (D84-22): the tool's OWN contract is
the validator - a wrong parameter FAILS as a REJECTED tool call before `_run`.

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
from polymerhus.attack.hunting.pod.types import (
    KbObservation,
    ProbeStep,
    RawObservation,
)
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


async def _await_seam_kw(fn, *args, **kwargs):
    """The kwargs-capable twin of `_await_seam` (T3): the KB seams take keyword
    join-key hints (`fault_id`/`technological_axis`, `lookup`), so an async or
    sync seam is awaited/offloaded with its kwargs intact."""
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return await asyncio.to_thread(fn, *args, **kwargs)


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


# --- the bound-tool surface (T7, D84-16/22/26) --------------------------------

class KbQueryTool(BaseTool):
    """The pod's KB query tool as a bound `BaseTool` (D84-16/26): wraps the
    lightrag branch's single `query_lightrag` tool and, when a D6 log is bound,
    records every response as a first-class `KbObservation` into the variant's
    experiment-log file (T3/#179). The former `kb_retrieve` symptom-technique
    typed seam (surface B) is RETIRED; the KB capability is `query_lightrag`
    (always-bound as of #197 - the `HUNTING_LIGHTRAG_TOOL` gate is REMOVED),
    and the pod runner/triager bind it exactly like the hunting agent's author
    lane.

    Fail-open (O13): an empty/raising KB degrades to a denoted degraded bundle,
    never raises into the turn. A tool with no log bound (the contract tier)
    records nothing. The `query_lightrag` tool itself is built lazily
    (no I/O at import) from the app config."""

    name: str = "query_lightrag"
    description: str = (
        "Retrieve reusable web-application testing methodology from the "
        "LightRAG knowledge base for one bounded testing concern, then return "
        "a structured answer: one ontology entity (type + canonical name) with "
        "a detailed prose explanation, grounded only in the returned "
        "references. Use it to ground a probe or a payload family when the "
        "spec's own primitives are not enough; an empty result means the KB "
        "has nothing further - degrade to the spec's own primitives and "
        "continue."
    )
    args_schema: type[BaseModel] = None  # set in __init__ from the lightrag tool

    def __init__(self, *, log=None, variant_ref: str = "", tool=None, **kwargs):
        super().__init__(**kwargs)
        self._log = log
        self._variant_ref = variant_ref
        if tool is not None:
            self._tool = tool
            self.args_schema = tool.args_schema
        else:
            from lightrag.tool import build_lightrag_tool  # noqa: PLC0415

            self._tool = build_lightrag_tool()
            self.args_schema = self._tool.args_schema

    def _record(self, spec: Any, answer_text: str) -> None:
        """The deterministic recording step (T3/#179): the query spec + the
        returned AnswerBundle-shaped answer land in the D6 log + the variant's
        experiment-log file as a `KbObservation`. Fail-open (O13): the
        recording never raises into the turn; a logless tool records nothing."""
        if self._log is None:
            return
        try:
            if isinstance(spec, dict):
                scenario_id = str(spec.get("scenario_id") or "")
                query = str(spec.get("concern") or "")
            else:
                scenario_id = str(getattr(spec, "scenario_id", "") or "")
                query = str(getattr(spec, "concern", "") or "")
            observation = KbObservation(
                variant_ref=self._variant_ref,
                query=query or str(spec)[:200],
                fault_id=scenario_id,
            )
            try:
                answer = json.loads(answer_text)
                observation.source = str(answer.get("schema_version") or "lightrag-answer/v2")
                observation.symptoms = [
                    str(x.get("entity_name") or x.get("entity_type") or "")
                    for x in (answer.get("ontology_explanations") or [])
                    if isinstance(x, dict)
                ][:8]
            except (ValueError, TypeError):
                observation.source = "lightrag-answer/v2"
            self._log.record_kb_observation(observation)
        except Exception:  # noqa: BLE001 - fail-open (O13)
            pass

    def _run(self, **kwargs: Any) -> str:
        try:
            text = self._tool.invoke(kwargs)
            self._record(kwargs, text)
            return text
        except Exception as exc:  # noqa: BLE001 - fail-open (O13): never into the turn
            degraded = {
                "schema_version": "lightrag-answer/v2",
                "scenario_id": kwargs.get("scenario_id", ""),
                "summary": "query_lightrag degraded - grounded on the HuntConfig alone",
                "ontology_explanations": [],
                "provenance_references": [],
                "knowledge_gaps": [f"knowledge base unavailable ({type(exc).__name__})"],
                "notes": "degraded",
            }
            self._record(kwargs, json.dumps(degraded))
            return json.dumps(degraded)

    async def _arun(self, **kwargs: Any) -> str:
        try:
            text = await self._tool.ainvoke(kwargs)
            self._record(kwargs, text)
            return text
        except Exception as exc:  # noqa: BLE001 - fail-open (O13): never into the turn
            degraded = {
                "schema_version": "lightrag-answer/v2",
                "scenario_id": kwargs.get("scenario_id", ""),
                "summary": "query_lightrag degraded - grounded on the HuntConfig alone",
                "ontology_explanations": [],
                "provenance_references": [],
                "knowledge_gaps": [f"knowledge base unavailable ({type(exc).__name__})"],
                "notes": "degraded",
            }
            self._record(kwargs, json.dumps(degraded))
            return json.dumps(degraded)

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
