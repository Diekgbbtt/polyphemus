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
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Mapping

# The persisted-status vocabularies (mirrors `pg.py` / `ph.py`). Recon and
# hunting terminals are the documented pipeline contract; analysis's only live
# state is `draining`.
RECON_TERMINAL = frozenset({"complete", "failed"})
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
class ApiCall:
    """One REST call: the method, path, optional JSON body, and a label."""

    method: str
    path: str
    body: Mapping | None = None
    description: str = ""

    def display(self) -> str:
        """A plan-mode rendering: `METHOD path json={...}`."""
        rendered = f"{self.method} {self.path}"
        if self.body is not None:
            rendered += f" json={json.dumps(self.body)}"
        return rendered


ApiRunner = Callable[[ApiCall], dict]


class HttpApiRunner:
    """The production runner: stdlib `urllib`, JSON in and out.

    A non-2xx raises `ApiError` carrying the status and the server's `detail`
    (the same best-effort detail extraction as `ph.py`); a transport failure
    raises with status 0. The trial treats a raise as a hard failure - the
    live-run budget/timeout handling is the caller's, not this seam's.
    """

    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def __call__(self, call: ApiCall) -> dict:
        url = f"{self.base_url}{call.path}"
        data = None
        headers = {"Accept": "application/json"}
        if call.body is not None:
            data = json.dumps(call.body).encode()
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=call.method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
                return json.loads(payload) if payload else {}
        except urllib.error.HTTPError as exc:
            raise ApiError(call, exc.code, _http_detail(exc)) from exc
        except urllib.error.URLError as exc:
            raise ApiError(call, 0, str(exc.reason)) from exc


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


def seed_auth(project_id: str, *, overview=None, accounts=None) -> ApiCall:
    return ApiCall(
        "PUT", f"/projects/{project_id}/auth", {"overview": overview, "accounts": accounts}
    )


def read_auth(project_id: str) -> ApiCall:
    return ApiCall("GET", f"/projects/{project_id}/auth")


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


def launch_hunting(project_id: str, candidates=None) -> ApiCall:
    return ApiCall("POST", f"/projects/{project_id}/hunting", {"candidates": candidates or []})


def hunting_status(project_id: str, hunting_run_id: str) -> ApiCall:
    return ApiCall("GET", f"/projects/{project_id}/hunting/{hunting_run_id}")


def stop_recon(project_id: str, run_id: str) -> ApiCall:
    return ApiCall("POST", f"/projects/{project_id}/recon/{run_id}/stop")


def stop_analysis(project_id: str, run_id: str) -> ApiCall:
    return ApiCall("POST", f"/projects/{project_id}/analysis/{run_id}/stop")


def stop_hunting(project_id: str, hunting_run_id: str) -> ApiCall:
    return ApiCall("POST", f"/projects/{project_id}/hunting/{hunting_run_id}/stop")


def project_graph(project_id: str) -> ApiCall:
    return ApiCall("GET", f"/projects/{project_id}/graph")


def app_state(project_id: str | None = None) -> ApiCall:
    path = "/app-state" if project_id is None else f"/app-state?project_id={project_id}"
    return ApiCall("GET", path)


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
