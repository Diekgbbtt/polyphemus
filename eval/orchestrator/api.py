"""The thin polymerhus REST client seam for the trial engine (ticket #270).

`ApiCall`/`ApiRunner` mirror `commands.Command`/`CommandRunner`: the trial
builds an `ApiCall`, an injected runner performs it, and plan mode prints
`display()` without constructing a runner. The builders encode the payload and
polling semantics from `eval/ph.py`; the parsers decode the wire shapes from
`src/polymerhus/project_management/api.py` - the two surfaces the live trial
will mirror.

Stdlib only. Import performs no I/O (CODING_STANDARD section 6).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Callable, Mapping

# The persisted-status vocabularies (mirrors `pg.py` / `ph.py`). Recon and
# hunting terminals are the documented pipeline contract; analysis's only live
# state is `draining`. Recon `stopped` is a deliberate stop (the pipeline's
# cancellation path, #287), distinct from a crash (`failed`).
RECON_TERMINAL = frozenset({"complete", "failed", "stopped"})
HUNTING_TERMINAL = frozenset({"complete", "stopped", "failed", "interrupted"})
ANALYSIS_TERMINAL = frozenset({"drained", "withheld", "stopped", "interrupted"})

# Layer-0 node labels (design §10.3), inlined so the harness stays free of a
# `polymerhus` import; mirrors `recon/domain/curator.py` ALLOWED_LABELS. L1
# units carry the `L1` label prefix; `Observation` is neither layer.
L0_LABELS = frozenset(
    {
        "Domain",
        "Subdomain",
        "IP",
        "Port",
        "Service",
        "DNSRecord",
        "BaseURL",
        "Endpoint",
        "Parameter",
        "Header",
        "Certificate",
        "Technology",
        "Secret",
        "Traceroute",
        "ExternalDomain",
    }
)


class ApiError(RuntimeError):
    """An API call failed (transport or a non-2xx status)."""

    def __init__(self, call: "ApiCall", status: int, detail: str) -> None:
        super().__init__(f"HTTP {status} {call.method} {call.path}: {detail}")
        self.call = call
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class ApiFile:
    """One multipart part: the form field name, its filename, and raw bytes."""

    field: str
    filename: str
    data: bytes
    content_type: str = "application/octet-stream"


@dataclass(frozen=True)
class ApiCall:
    """One REST call: method, path, and either a JSON body or a file upload."""

    method: str
    path: str
    body: Mapping | None = None
    description: str = ""
    # When set, the request is `multipart/form-data` carrying this one part
    # (the data-dependency placement endpoints); `body` is then unused.
    file: ApiFile | None = None

    def display(self) -> str:
        """A plan-mode rendering: `METHOD path json={...}` or `... upload=...`."""
        rendered = f"{self.method} {self.path}"
        if self.file is not None:
            rendered += f" upload={self.file.filename} ({len(self.file.data)} bytes)"
        elif self.body is not None:
            rendered += f" json={json.dumps(self.body)}"
        return rendered


ApiRunner = Callable[[ApiCall], dict]


def _multipart(file: ApiFile) -> tuple[bytes, str]:
    """Encode one file part as a `multipart/form-data` body + its boundary."""
    boundary = f"----polymerhus-{uuid.uuid4().hex}"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{file.field}"; '
        f'filename="{file.filename}"\r\n'
        f"Content-Type: {file.content_type}\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    return head + file.data + tail, boundary


class HttpApiRunner:
    """The production runner: stdlib `urllib`, JSON in and out.

    A non-2xx raises `ApiError` carrying the status and the server's `detail`
    (the same best-effort detail extraction as `ph.py`); a transport failure
    raises with status 0. An idempotent `GET`/`HEAD` transport failure is
    retried `retries` times with an exponential backoff before the terminal
    `ApiError`, so the trial records a failed phase instead of aborting on a
    raw `TimeoutError`.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        retries: int = 2,
        backoff_s: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = max(0, retries)
        self.backoff_s = max(0.0, backoff_s)
        self._sleep = sleep

    def __call__(self, call: ApiCall) -> dict:
        url = f"{self.base_url}{call.path}"
        data = None
        headers = {"Accept": "application/json"}
        if call.file is not None:
            data, boundary = _multipart(call.file)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        elif call.body is not None:
            data = json.dumps(call.body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=call.method)
        attempts = self.retries + 1 if call.method in {"GET", "HEAD"} else 1
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    payload = response.read()
                    return json.loads(payload) if payload else {}
            except urllib.error.HTTPError as exc:
                raise ApiError(call, exc.code, _http_detail(exc)) from exc
            except (TimeoutError, urllib.error.URLError) as exc:
                if attempt + 1 >= attempts:
                    reason = getattr(exc, "reason", None) or str(exc)
                    raise ApiError(
                        call,
                        0,
                        f"{type(exc).__name__}: {reason} "
                        f"(after {attempt + 1} attempt(s))",
                    ) from exc
                self._sleep(self.backoff_s * (2**attempt))
        raise AssertionError("unreachable: the retry loop always returns or raises")


def _http_detail(exc: urllib.error.HTTPError) -> str:
    try:
        return json.loads(exc.read()).get("detail") or exc.reason
    except Exception:  # noqa: BLE001 - best-effort detail extraction (ph.py)
        return str(exc.reason)


# --- call builders ------------------------------------------------------------


def list_projects() -> ApiCall:
    return ApiCall("GET", "/projects")


def create_project(name: str) -> ApiCall:
    return ApiCall("POST", "/projects", {"name": name})


def put_settings(project_id: str, recon: Mapping) -> ApiCall:
    return ApiCall("PUT", f"/projects/{project_id}/settings", {"recon": dict(recon)})


def read_auth(project_id: str) -> ApiCall:
    return ApiCall("GET", f"/projects/{project_id}/auth")


# --- eval data-dependency placement (multipart direct file write) -------------
# The four endpoints replace the retired inline `TargetConfig.auth` + `PUT /auth`
# seed: raw file bytes (or a `.tar.gz` bundle) land at the canonical project
# path, and the L1 surface persists into the graph. `fileName` is an optional
# multipart attribute and never the path authority.


def _upload(project_id: str, artifact: str, data: bytes, filename: str) -> ApiCall:
    return ApiCall(
        "POST",
        f"/projects/{project_id}/data-dependencies/{artifact}",
        file=ApiFile("file", filename, data),
    )


def place_auth_overview(project_id: str, data: bytes, filename: str = "overview.yaml") -> ApiCall:
    return _upload(project_id, "auth-overview", data, filename)


def place_auth_credentials(
    project_id: str, data: bytes, filename: str = "credentials.yaml"
) -> ApiCall:
    return _upload(project_id, "auth-credentials", data, filename)


def place_authn_skill(project_id: str, data: bytes, filename: str = "authn.tar.gz") -> ApiCall:
    return _upload(project_id, "authn-skill", data, filename)


def place_l1(project_id: str, operator_kb: bytes, filename: str = "operator_kb.md") -> ApiCall:
    return _upload(project_id, "l1", operator_kb, filename)


def bootstrap(project_id: str, operator_kb: str | None = None) -> ApiCall:
    return ApiCall("POST", f"/projects/{project_id}/bootstrap", {"operator_kb": operator_kb})


def launch_recon(project_id: str, *, with_analysis: bool = True, jobs=None) -> ApiCall:
    body: dict = {"with_analysis": with_analysis}
    if jobs:
        body["jobs"] = list(jobs)
    return ApiCall("POST", f"/projects/{project_id}/recon", body)


def recon_status(project_id: str, run_id: str) -> ApiCall:
    return ApiCall("GET", f"/projects/{project_id}/recon/{run_id}")


def launch_analysis(project_id: str, run_id: str) -> ApiCall:
    return ApiCall("POST", f"/projects/{project_id}/analysis", {"run_id": run_id})


def analysis_status(project_id: str, run_id: str) -> ApiCall:
    return ApiCall("GET", f"/projects/{project_id}/analysis/{run_id}")


def launch_hunting(project_id: str) -> ApiCall:
    """Open one whole hunting run. The body is empty: the run's input is its
    L1 INTAKE (S1 7.1), and the retired candidate batch is gone."""
    return ApiCall("POST", f"/projects/{project_id}/hunting", {})


def hunting_status(project_id: str, hunting_run_id: str) -> ApiCall:
    return ApiCall("GET", f"/projects/{project_id}/hunting/{hunting_run_id}")


def stop_recon(project_id: str, run_id: str) -> ApiCall:
    return ApiCall("POST", f"/projects/{project_id}/recon/{run_id}/stop")


def stop_analysis(project_id: str, run_id: str) -> ApiCall:
    return ApiCall("POST", f"/projects/{project_id}/analysis/{run_id}/stop")


def stop_hunting(project_id: str, hunting_run_id: str) -> ApiCall:
    return ApiCall("POST", f"/projects/{project_id}/hunting/{hunting_run_id}/stop")


# The run kinds whose stop verb shares one path shape. Each kind is its own
# path segment, so a new kind needs a new endpoint, not a generic routing rule.
_RUN_KINDS = ("recon", "analysis", "hunting")


def stop_run(project_id: str, run_kind: str, run_id: str) -> ApiCall:
    if run_kind not in _RUN_KINDS:
        raise ValueError(f"unknown run_kind: {run_kind!r}")
    return ApiCall("POST", f"/projects/{project_id}/{run_kind}/{run_id}/stop")


def stop_project(project_id: str) -> ApiCall:
    """Stop the WHOLE project execution: every live run of every kind at once.

    The ONE stop the token-budget and trial-deadline monitors call, so the monitor
    never has to know which run kinds - or which analysis mode - are live, nor
    address each module's run id separately. The project's execution is the unit it
    bounds, exactly as the project's cumulative token spend is."""
    return ApiCall("POST", f"/projects/{project_id}/execution/stop")


def project_graph(project_id: str) -> ApiCall:
    return ApiCall("GET", f"/projects/{project_id}/graph")


def app_state(project_id: str | None = None) -> ApiCall:
    path = "/app-state" if project_id is None else f"/app-state?project_id={project_id}"
    return ApiCall("GET", path)


def usage(project_id: str) -> ApiCall:
    return ApiCall("GET", f"/projects/{project_id}/usage")


# --- response parsers ---------------------------------------------------------


def project_id_of(response: Mapping) -> str:
    return response["project_id"]


def run_id_of(response: Mapping) -> str:
    return response["run_id"]


def hunting_run_id_of(response: Mapping) -> str:
    return response["hunting_run_id"]


def analysis_run_id_of(response: Mapping) -> str:
    return response["analysis_run_id"]


def project_ids(response: Mapping) -> list[str]:
    return [p["project_id"] for p in (response or {}).get("projects", []) or []]


def status_of(response: Mapping) -> str | None:
    return (response or {}).get("status")


def per_job_rows(response: Mapping) -> list:
    return (response or {}).get("per_job") or []


def usage_total(response: Mapping) -> int:
    """The project's cumulative raw token total (cache included); malformed -> zero."""
    value = (response or {}).get("total_tokens")
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def usage_generated(response: Mapping) -> int:
    """The project's cumulative GENERATED-token total (the output axis).

    The usage surface reports `generated_tokens` as a two-axis mapping
    (`{"reasoning": N, "visible": M}`, the `reasoning` + `visible` output split),
    so the scalar is their sum; a plain int is also accepted for robustness.
    It counts only what the model WROTE, so it excludes all input. The trial
    budget does NOT use this axis; it counts `usage_capped` (generated +
    uncached input). A malformed or absent value reads as zero (advisory),
    mirroring `usage_total`."""
    value = (response or {}).get("generated_tokens")
    if isinstance(value, Mapping):
        total = 0
        for part in ("reasoning", "visible"):
            v = value.get(part)
            if isinstance(v, int) and not isinstance(v, bool):
                total += v
        return total
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return 0


def usage_capped(response: Mapping) -> int:
    """The project's cumulative capped-token total, the trial budget axis:
    new output plus uncached input, i.e. `generated_tokens + uncached` =
    `total_tokens - cached`. Cached input never counts. A malformed or absent
    value reads as zero (advisory), mirroring `usage_total`."""
    value = (response or {}).get("capped_tokens")
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def usage_by_agent(response: Mapping) -> dict:
    """The per-agent token breakdown; an absent or malformed value reads empty."""
    value = (response or {}).get("by_agent")
    return dict(value) if isinstance(value, Mapping) else {}


# The flat per-agent token spectrum (#349): the eval record's first-class
# schema. Each entry is a typed, non-negative surface decoded from the durable
# ledger's nested `by_agent` (`_entry_surface` in `app/llm/usage.py`). The
# order is the schema contract. `cache_detail_omitted` (N5) counts the calls
# that carried NO cache detail at all, so a reported 0% cached share stays
# readable as "the provider did not say" rather than as "the provider measured
# a miss": a cached share read against `cache_detail_omitted == calls` is
# unaudited (`docs/design/eval-token-spectrum-349-adr.md`).
SPECTRUM_FIELDS = (
    "visible",
    "reasoning",
    "cached_input",
    "uncached_input",
    "generated",
    "total",
    "capped",
    "calls",
    "cache_detail_omitted",
)


def _spectrum_int(mapping: Mapping | None, key: str) -> int:
    """A non-negative int from a mapping, or 0 when absent/malformed (a bool is
    rejected, never treated as 0/1, mirroring `usage_total`)."""
    value = (mapping or {}).get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(0, value)


def usage_spectrum(response: Mapping) -> dict:
    """The project's per-agent token spectrum, decoded from a usage response.

    One flat typed entry per agent - `{visible, reasoning, cached_input,
    uncached_input, generated, total, capped, calls, cache_detail_omitted}` -
    projected from the durable ledger's own cumulative `by_agent` surface
    (#326). The values are the ledger's per-agent totals, NEVER a re-derivation
    from traces or spend logs; `generated = reasoning + visible` is the
    ledger's own output split summed, and `cached_input`/`uncached_input` are
    the ledger's context split. `cache_detail_omitted` is the ledger's N5 count
    of calls that carried NO cache detail at all, so a 0% cached share is
    readable as silence, not as a measured miss. An absent/malformed agent
    entry reads as zeros (advisory), so the terminal record is always writable
    and the spectrum is readable from the trial file alone (#349)."""
    by_agent = usage_by_agent(response)
    spectrum: dict[str, dict[str, int]] = {}
    for agent, entry in by_agent.items():
        if not isinstance(agent, str) or not isinstance(entry, Mapping):
            continue
        context = entry.get("context_tokens")
        generated = entry.get("generated_tokens")
        context = context if isinstance(context, Mapping) else {}
        generated = generated if isinstance(generated, Mapping) else {}
        reasoning = _spectrum_int(generated, "reasoning")
        visible = _spectrum_int(generated, "visible")
        spectrum[agent] = {
            "visible": visible,
            "reasoning": reasoning,
            "cached_input": _spectrum_int(context, "cached"),
            "uncached_input": _spectrum_int(context, "uncached"),
            "generated": reasoning + visible,
            "total": _spectrum_int(entry, "total_tokens"),
            "capped": _spectrum_int(entry, "capped_tokens"),
            "calls": _spectrum_int(entry, "calls"),
            "cache_detail_omitted": _spectrum_int(entry, "cache_detail_omitted"),
        }
    return spectrum


def spectrum_by_agent(by_agent: Mapping | None) -> dict:
    """Decode an already-read `by_agent` breakdown into the flat token spectrum.

    The trial's terminal reads `by_agent` once (at a budget stop or at the
    terminal usage snapshot); this projects that same mapping, so the record
    never re-reads or re-derives it. An absent/malformed breakdown reads empty.
    """
    if not isinstance(by_agent, Mapping):
        return {}
    return usage_spectrum({"by_agent": by_agent})


def recon_terminal(status: str | None) -> bool:
    return status in RECON_TERMINAL


def hunting_terminal(status: str | None) -> bool:
    return status in HUNTING_TERMINAL


def analysis_terminal(status: str | None) -> bool:
    return status in ANALYSIS_TERMINAL


@dataclass(frozen=True)
class GraphCounts:
    """The graph's layer tallies: `l0` primitives, `l1` units, services, observations."""

    l0: int
    l1: int
    services: int
    observations: int


def graph_counts(graph: Mapping | None) -> GraphCounts:
    """Tally the graph nodes by layer.

    A node with no/unknown `type` is ignored (a degenerate graph tallies zero),
    never counted as L0. `L1`-prefixed labels are the units; `L1Service` is the
    scaffold-presence signal; `Observation` is neither layer.
    """
    nodes = (graph or {}).get("nodes") or []
    l0 = l1 = services = observations = 0
    for node in nodes:
        node_type = node.get("type") or ""
        if node_type.startswith("L1"):
            l1 += 1
            if node_type == "L1Service":
                services += 1
        elif node_type == "Observation":
            observations += 1
        elif node_type in L0_LABELS:
            l0 += 1
    return GraphCounts(l0=l0, l1=l1, services=services, observations=observations)
