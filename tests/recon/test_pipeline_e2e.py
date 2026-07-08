"""End-to-end pipeline integration test (SP3 Task 7).

Wires the REAL per-job agent (`agent.recon.job_agent.run_job`) + REAL pod
graph (`agent.recon.pod.build_pod_graph`) + REAL parsers
(`agent.recon.parsers`) + REAL curator (`agent.recon.curator.curate`) + REAL
pipeline (`agent.recon.pipeline.run_pipeline`) together. The only fakes are
the two true externals - tool execution (`exec_fn`) and the LLM nodes
(deterministic `default_preprocess_fn` stands in for the preprocess LLM seam;
a `triage_fn` returning `[]` stands in for the triager LLM) - plus the
Neo4j/Postgres collaborators, which are captured in-memory so the test has
no live infra dependency.

Drives a subfinder -> dnsx -> httpx slice from a seed domain, using the
canned stdout fixtures in tests/recon/fixtures/ (the same shapes the unit
parser tests exercise) as the tools' real output, and asserts the whole
chain - including the subfinder->dnsx asset handoff through a real
curate()-fed in-memory graph - works end to end.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from pathlib import Path

from agent.recon import pipeline
from agent.recon.curator import curate
from agent.recon.job_agent import build_job_agent, default_preprocess_fn, run_job as real_run_job
from agent.recon.pod import build_pod_graph
from agent.recon.types import ExecResult

FIXTURES = Path(__file__).parent / "fixtures"

SUBFINDER_STDOUT = (FIXTURES / "subfinder.jsonl").read_text()
DNSX_STDOUT = (FIXTURES / "dnsx.jsonl").read_text()
HTTPX_STDOUT = (FIXTURES / "httpx_probe.jsonl").read_text()
ARJUN_STDOUT = (FIXTURES / "arjun.json").read_text()


def fake_exec_fn(command: str, session_id: str, timeout_s: int) -> ExecResult:
    """The one true external (tool exec) - dispatches canned stdout per tool
    by matching the command's leading token, mirroring each JobSpec's real
    command_template."""
    if command.startswith("subfinder"):
        stdout = SUBFINDER_STDOUT
    elif "dnsx" in command:
        stdout = DNSX_STDOUT
    elif command.startswith("httpx"):
        stdout = HTTPX_STDOUT
    elif command.startswith("arjun"):
        stdout = ARJUN_STDOUT
    else:
        raise AssertionError(f"unexpected command in e2e test: {command!r}")
    return ExecResult(stdout=stdout, stderr="", returncode=0, duration_ms=1)


def make_recording_exec_fn():
    """Wraps `fake_exec_fn`, additionally recording every filled command -
    lets a test assert a job's `{placeholder}`s were actually resolved to
    real values (not left blank/literal) by the time exec_fn sees them."""
    commands: list[str] = []

    def exec_fn(command: str, session_id: str, timeout_s: int) -> ExecResult:
        commands.append(command)
        return fake_exec_fn(command, session_id, timeout_s)

    exec_fn.commands = commands
    return exec_fn


def fake_triage_fn(exec_result, assets, job):
    """The other true external (triager LLM) - fixed to `[]` per the brief."""
    return []


class InMemoryGraph:
    """Captures every `curate()` -> `merge_fn(cypher, params)` call and, for
    asset MERGEs (identified by the primary-node line `MERGE (n:LABEL {...})`
    that `build_asset_cypher` always emits first), derives an in-memory
    node store keyed by (project_id, label, identity).

    `read_assets` serves phase N+1's `input_assets` straight out of this
    store, scoped by project_id exactly like the real Neo4j-backed
    `read_assets` scopes by `project_id` in its Cypher `WHERE` - so the real
    curate -> read_assets seam (including project_id scoping) is genuinely
    exercised, not just faked away.

    F4: prod `pipeline.read_assets` returns `dict(record["n"])` - identity
    AND all props (minus the first_seen/last_seen/project_id bookkeeping
    keys) - not an identity-only dict. `build_asset_cypher` carries a
    delta's props in the single `params["props"]` dict (merged onto the node
    via `SET n += $props`), so this store folds `props` into the captured
    node alongside its identity, exactly mirroring what a real Neo4j node
    would look like on read-back. This is what makes a prop-dependent
    template placeholder (e.g. arjun's `{target}` from an Endpoint's `url`
    PROP) actually exercised end-to-end instead of silently no-op'd.
    """

    _PRIMARY_NODE_RE = re.compile(r"^MERGE \(n:(\w+) \{")

    def __init__(self):
        self.merges: list[tuple[str, dict]] = []
        self._store: dict[str, dict[tuple, tuple[str, dict]]] = {}

    def merge_fn(self, cypher: str, params: dict) -> None:
        self.merges.append((cypher, params))
        match = self._PRIMARY_NODE_RE.match(cypher.splitlines()[0])
        if not match:
            return  # an edge-target node MERGE or an Observation MERGE
        label = match.group(1)
        project_id = params.get("project_id")
        identity = {k[len("id_"):]: v for k, v in params.items() if k.startswith("id_")}
        node = dict(identity)
        node.update(params.get("props") or {})
        key = (project_id, tuple(sorted(identity.items())))
        self._store.setdefault(label, {})[key] = (project_id, node)

    def read_assets(self, node_type: str, project_id: str) -> list[dict]:
        return [
            node
            for (pid, node) in self._store.get(node_type, {}).values()
            if pid == project_id
        ]


class FakeRegistry:
    """Captures create_run/upsert_job/set_run_status calls, standing in for
    the Postgres registry."""

    def __init__(self):
        self.create_run_calls: list[tuple] = []
        self.set_run_status_calls: list[tuple] = []
        self.upsert_job_calls: list[dict] = []

    def create_run(self, run_id, project_id):
        self.create_run_calls.append((run_id, project_id))

    def set_run_status(self, run_id, status, current_phase=None):
        self.set_run_status_calls.append((run_id, status, current_phase))

    def upsert_job(self, run_id, phase, job, status, stats=None, error=None):
        self.upsert_job_calls.append(
            {
                "run_id": run_id,
                "phase": phase,
                "job": job,
                "status": status,
                "stats": stats,
                "error": error,
            }
        )


def _build_pod_invoke(pod_graph):
    """Same shape as `job_agent.default_pod_invoke`, but invoking OUR pod
    graph (built with the fake exec/curate/triage collaborators) instead of
    the module-level default that wires the real MCP client."""

    def pod_invoke(pod_input, job, run_id, phase):
        extra = pod_input.get("extra") or {}
        project_id = extra.get("project_id", run_id)
        session_id = f"{run_id}-{phase}-{job.tool}-{uuid.uuid4().hex[:8]}"
        pod_state = {
            "job": job,
            "input_asset": pod_input.get("input_asset", {}),
            "asset_context": pod_input.get("asset_context", ""),
            "extra": extra,
            "session_id": session_id,
            "project_id": project_id,
        }
        result = pod_graph.invoke(pod_state)
        return result["export"]

    return pod_invoke


def test_pipeline_e2e_subfinder_dnsx_httpx():
    graph = InMemoryGraph()

    def curate_fn(assets, observations, project_id):
        return curate(assets, observations, project_id, merge_fn=graph.merge_fn)

    pod_graph = build_pod_graph(exec_fn=fake_exec_fn, curate_fn=curate_fn, triage_fn=fake_triage_fn)
    job_agent = build_job_agent(
        pod_invoke=_build_pod_invoke(pod_graph), preprocess_fn=default_preprocess_fn
    )

    call_order: list[str] = []
    seen_input_assets: dict[str, list[dict]] = {}

    async def run_job(job, input_assets, *, run_id, phase, extra):
        call_order.append(job.tool)
        seen_input_assets[job.tool] = input_assets
        return await real_run_job(
            job, input_assets, run_id=run_id, phase=phase, extra=extra, agent=job_agent
        )

    registry = FakeRegistry()

    def load_settings(project_id):
        # Wildcard: exercise the full subdomain-discovery chain (an exact host
        # would suppress subfinder/dnsx under the D14 scope gate).
        return {"target_domain": "*.example.com"}

    # project_id and run_id are deliberately different values: this is the
    # only way the test can catch a pipeline that forgets to thread the real
    # project_id through to the pod (falling back to run_id) - which would
    # silently break the curate() -> read_assets() project_id scoping.
    asyncio.run(
        pipeline.run_pipeline(
            "proj-e2e",
            run_id="run-e2e",
            job_subset=["subfinder", "dnsx", "httpx"],
            run_job=run_job,
            load_settings=load_settings,
            registry=registry,
            read_assets=graph.read_assets,
        )
    )

    # 1. Phases ran in order.
    assert call_order == ["subfinder", "dnsx", "httpx"]

    # 2. Curator saw MERGE cypher for the expected node labels per phase.
    cyphers = [cy for cy, _ in graph.merges]
    assert any(":Subdomain" in cy for cy in cyphers)  # subfinder
    assert any(":IP" in cy for cy in cyphers)  # dnsx
    assert any(":DNSRecord" in cy for cy in cyphers)  # dnsx
    assert any(":BaseURL" in cy for cy in cyphers)  # httpx
    assert any(":Endpoint" in cy for cy in cyphers)  # httpx

    # 3. Registry ended complete with per-job success statuses recorded.
    assert registry.set_run_status_calls[-1] == ("run-e2e", "complete", None)
    final_status = {call["job"]: call["status"] for call in registry.upsert_job_calls}
    assert final_status["subfinder"] == "success"
    assert final_status["dnsx"] == "success"
    assert final_status["httpx"] == "success"

    # 4. subfinder -> dnsx asset handoff: dnsx's pods received exactly the
    # Subdomain identities subfinder produced (real curate -> read_assets
    # seam, not a stub), with the apex seed host prepended ahead of them
    # (D11: the apex's own origin is probed alongside discovered subdomains).
    assert seen_input_assets["dnsx"] == [
        {"name": "example.com"},
        {"name": "www.example.com"},
        {"name": "api.example.com"},
    ]


def test_pipeline_e2e_httpx_to_arjun_prop_dependent_target():
    """F4: arjun's `{target}` comes from an Endpoint's `url` PROP (Endpoint
    IDENTITY is `{path,method,baseurl}` - no url). Extends the subfinder ->
    dnsx -> httpx chain one phase further into arjun (consumes Endpoint) to
    prove `InMemoryGraph.read_assets` now round-trips props like prod's
    `dict(record["n"])` - with the old identity-only fake this would
    silently pass arjun an Endpoint with no `url`, filling `{target}` blank."""
    graph = InMemoryGraph()

    def curate_fn(assets, observations, project_id):
        return curate(assets, observations, project_id, merge_fn=graph.merge_fn)

    exec_fn = make_recording_exec_fn()
    pod_graph = build_pod_graph(exec_fn=exec_fn, curate_fn=curate_fn, triage_fn=fake_triage_fn)
    job_agent = build_job_agent(
        pod_invoke=_build_pod_invoke(pod_graph), preprocess_fn=default_preprocess_fn
    )

    seen_input_assets: dict[str, list[dict]] = {}

    async def run_job(job, input_assets, *, run_id, phase, extra):
        seen_input_assets[job.tool] = input_assets
        return await real_run_job(
            job, input_assets, run_id=run_id, phase=phase, extra=extra, agent=job_agent
        )

    registry = FakeRegistry()

    def load_settings(project_id):
        # Wildcard: exercise the full subdomain-discovery chain (an exact host
        # would suppress subfinder/dnsx under the D14 scope gate).
        return {"target_domain": "*.example.com"}

    asyncio.run(
        pipeline.run_pipeline(
            "proj-e2e-arjun",
            run_id="run-e2e-arjun",
            job_subset=["subfinder", "dnsx", "httpx", "arjun"],
            run_job=run_job,
            load_settings=load_settings,
            registry=registry,
            read_assets=graph.read_assets,
        )
    )

    # arjun's Endpoint input_assets carry the `url` PROP alongside identity -
    # the fidelity fix under test.
    endpoint_assets = seen_input_assets["arjun"]
    assert endpoint_assets, "httpx must have produced at least one Endpoint for arjun to consume"
    assert all("url" in asset for asset in endpoint_assets), (
        f"Endpoint input_assets missing the 'url' prop (identity-only fake regression): {endpoint_assets!r}"
    )

    # The real command sent to exec_fn has {target} resolved to that real
    # url, not left blank - proves the prop actually reached fill_template.
    arjun_commands = [c for c in exec_fn.commands if c.startswith("arjun")]
    assert arjun_commands, "no arjun command was executed"
    assert any("-u https://" in c for c in arjun_commands)
    assert not any("{" in c for c in arjun_commands)

    final_status = {call["job"]: call["status"] for call in registry.upsert_job_calls}
    assert final_status["arjun"] == "success"
    cyphers = [cy for cy, _ in graph.merges]
    assert any(":Parameter" in cy for cy in cyphers)  # arjun
