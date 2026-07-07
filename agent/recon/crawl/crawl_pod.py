"""Crawl-pod variant: crawl -> parse -> triager -> curator.

`build_crawl_pod` is the `configurator_mode="agent"` counterpart of
`agent.recon.pod.build_pod_graph`: instead of the deterministic
configurator/execute/gate loop, a single `crawl` node runs the agentic
Steel crawl loop (`run_crawl_fn`) and hands its manifest straight to the
shared `parse`/`triager`/`curator` nodes. `parse`/`triage_fn`/`curate_fn`
are injected so tests never touch a live Steel/LLM/Neo4j - mirroring
`pod.py`'s injection pattern.

The `crawl` node is best-effort by construction (design's Global
Constraints / plan §10.6): a `SteelNotConfigured` raise, any other
exception, or an empty manifest are all treated the same way - route to a
terminal `fail` node that sets `verdict="failed"` and curates ONE
`reduced_crawl_coverage` Observation anchored to the pod's input BaseURL.
Nothing from this node ever propagates as an unhandled exception.

`default_run_crawl_fn` wraps the async `crawl_agent.run_crawl` behind
`agent.recon.async_bridge.run_coro_blocking`, exactly like
`pod.default_exec_fn` wraps the async kali MCP call - so every node in this
graph, like every node in `pod.py`'s graph, is a plain sync function and
the compiled graph is `.invoke()`-able synchronously from `job_agent`, even
though `job_agent` itself runs inside the pipeline's event loop.
"""
from __future__ import annotations

import json

from typing import Optional

from langgraph.graph import StateGraph, START, END

from agent.recon.types import PodState, PodExport, Observation
from agent.recon.parsers import get_parser
from agent.recon.curator import curate
from agent.recon.pod import default_triage_fn, _input_asset_url

_EMPTY_MANIFEST_KEYS = ("endpoints", "js_urls")


class CrawlPodState(PodState, total=False):
    """`PodState` plus the two fields this graph's `crawl` node produces.

    LangGraph's `StateGraph` schema only merges keys declared on the schema
    TypedDict - a node returning an undeclared key is silently dropped, not
    an error - so `manifest`/`crawl_error` must be declared here rather
    than only referenced ad hoc from `pod.py`'s `PodState`.
    """

    manifest: Optional[dict]
    crawl_error: Optional[str]
    viewer_url: Optional[str]


def _manifest_is_empty(manifest: dict | None) -> bool:
    if not manifest or not isinstance(manifest, dict):
        return True
    return not any(manifest.get(key) for key in _EMPTY_MANIFEST_KEYS)


def _coverage_observation(input_asset: dict, reason: str) -> Observation:
    target = _input_asset_url(input_asset) or ""
    return Observation(
        macro_kind="reduced_crawl_coverage",
        severity="info",
        evidence=reason,
        rationale=(
            "The agentic Steel crawl for this target did not complete "
            "successfully; endpoint/parameter coverage for this BaseURL is "
            "reduced relative to a full crawl."
        ),
        anchor={"type": "BaseURL", "identity": {"url": target}},
        source_job="crawl",
        source_tool="steel_crawl",
    )


def default_run_crawl_fn(target: str, *, scope: list[str]):
    """Real collaborator: run the agentic Steel crawl loop synchronously.

    Wraps `crawl_agent.run_crawl` (async) behind `run_coro_blocking`,
    resolving the crawl-agent module lazily so importing this module
    performs no I/O.
    """
    from agent.recon.crawl import crawl_agent
    from agent.recon.async_bridge import run_coro_blocking

    return run_coro_blocking(crawl_agent.run_crawl(target, scope=scope))


def default_run_crawl_authenticated_fn(target: str, *, scope: list[str]):
    """Real collaborator: authenticated agentic crawl (interactive
    `steel_await_auth` MVP path), synchronously.

    Wraps `crawl_agent.run_crawl_authenticated` (async) behind
    `run_coro_blocking`, mirroring `default_run_crawl_fn`. Returns
    `(manifest, awaiting_status)`.
    """
    from agent.recon.crawl import crawl_agent
    from agent.recon.async_bridge import run_coro_blocking

    return run_coro_blocking(crawl_agent.run_crawl_authenticated(target, scope=scope))


def build_crawl_pod(*, run_crawl_fn, parse_fn, triage_fn, curate_fn, run_crawl_authenticated_fn=None):
    """Build the compiled crawl-pod subgraph, injecting the side-effecting
    collaborators: run_crawl_fn(target, scope=scope) -> manifest dict,
    parse_fn(stdout) -> list[AssetDelta], triage_fn(exec_result, assets, job)
    -> list[Observation] (called with a synthetic exec_result carrying the
    manifest JSON as stdout, mirroring pod.py's triager signature),
    curate_fn(assets, observations, project_id) -> (int, int).

    `run_crawl_authenticated_fn(target, scope=scope) -> (manifest, awaiting_status | None)`
    is the interactive `steel_await_auth` MVP auth path (see
    `crawl_agent.run_crawl_authenticated`). It is only invoked for a
    `use_auth` job whose `extra` carries an `auth_context` signal (set by
    the pipeline from the project's settings, see `pipeline.py`) - a
    non-auth crawl, or an auth-capable job run without an `auth_context`,
    never precreates a Steel session and calls `run_crawl_fn` as before.
    When present, the `awaiting_status["viewer_url"]` is recorded on the
    pod export's `stats` so the operator can complete the manual login
    (surfaced by `GET /recon/{run_id}` via `pipeline.py`'s stats
    pass-through). Non-interactive cookie-injection (from
    `auth_context` cookies) into the Steel session is a deferred follow-up,
    not built here.
    """

    def crawl(state: CrawlPodState) -> dict:
        input_asset = state.get("input_asset") or {}
        extra = state.get("extra") or {}
        job = state.get("job")
        target = _input_asset_url(input_asset)
        scope = extra.get("scope") or ([target] if target else [])

        use_auth_signal = bool(
            job is not None and getattr(job, "use_auth", False) and extra.get("auth_context")
        )

        viewer_url = None
        try:
            if use_auth_signal and run_crawl_authenticated_fn is not None:
                # KNOWN LIMITATION (Fix B, SP4 review): run_crawl_authenticated_fn
                # BLOCKS on the crawl before returning awaiting_status, so the
                # steel_await_auth viewer_url captured here reaches
                # GET /recon/{run_id} (via the export stats below) only after the
                # run is over - too late for a human to log in mid-run. The path
                # is also gated on extra.auth_context being present (use_auth_signal).
                # Proper fix = mid-flight registry write of viewer_url before the
                # blocking loop (tracked follow-up); not re-architected here.
                manifest, awaiting_status = run_crawl_authenticated_fn(target, scope=scope)
                if awaiting_status:
                    viewer_url = awaiting_status.get("viewer_url") or None
            else:
                manifest = run_crawl_fn(target, scope=scope)
        except Exception as exc:  # noqa: BLE001 - best-effort, never raise
            return {"manifest": None, "crawl_error": str(exc), "viewer_url": viewer_url}

        if _manifest_is_empty(manifest):
            return {"manifest": None, "crawl_error": "empty crawl manifest", "viewer_url": viewer_url}

        return {"manifest": manifest, "viewer_url": viewer_url}

    def gate(state: CrawlPodState) -> str:
        return "parse" if state.get("manifest") is not None else "fail"

    def parse(state: CrawlPodState) -> dict:
        manifest = state.get("manifest") or {}
        assets = parse_fn(json.dumps(manifest))
        return {"assets": assets}

    def triager(state: CrawlPodState) -> dict:
        from agent.recon.types import ExecResult

        job = state.get("job")
        manifest = state.get("manifest") or {}
        exec_result = ExecResult(stdout=json.dumps(manifest), stderr="", returncode=0)
        observations = list(triage_fn(exec_result, state.get("assets", []), job))
        return {"observations": observations}

    def curator_node(state: CrawlPodState) -> dict:
        assets = state.get("assets", [])
        observations = state.get("observations", [])
        assets_merged, observations_merged = curate_fn(assets, observations, state["project_id"])
        viewer_url = state.get("viewer_url")
        export = PodExport(
            input_asset=state["input_asset"],
            verdict="success",
            assets_merged=assets_merged,
            observations_merged=observations_merged,
            stats={"viewer_url": viewer_url} if viewer_url else None,
        )
        return {"export": export}

    def fail(state: CrawlPodState) -> dict:
        input_asset = state.get("input_asset") or {}
        reason = state.get("crawl_error") or "crawl failed"
        observation = _coverage_observation(input_asset, reason)
        _, observations_merged = curate_fn([], [observation], state["project_id"])
        viewer_url = state.get("viewer_url")
        export = PodExport(
            input_asset=input_asset,
            verdict="failed",
            assets_merged=0,
            observations_merged=observations_merged,
            error=reason,
            stats={"viewer_url": viewer_url} if viewer_url else None,
        )
        return {"export": export}

    g = StateGraph(CrawlPodState)
    g.add_node("crawl", crawl)
    g.add_node("parse", parse)
    g.add_node("triager", triager)
    g.add_node("curator", curator_node)
    g.add_node("fail", fail)

    g.add_edge(START, "crawl")
    g.add_conditional_edges("crawl", gate, {"parse": "parse", "fail": "fail"})
    g.add_edge("parse", "triager")
    g.add_edge("triager", "curator")
    g.add_edge("curator", END)
    g.add_edge("fail", END)

    return g.compile()


crawl_pod = build_crawl_pod(
    run_crawl_fn=default_run_crawl_fn,
    run_crawl_authenticated_fn=default_run_crawl_authenticated_fn,
    parse_fn=get_parser("steel_crawl"),
    triage_fn=default_triage_fn,
    curate_fn=curate,
)


def crawl_pod_invoke(pod_input: dict, job, run_id: str, phase: int) -> PodExport:
    """Invoke the module-level `crawl_pod` for a single pod_input and return
    its terminal export - the crawl-pod counterpart of
    `job_agent.default_pod_invoke`, mirroring its PodState construction and
    project_id scoping (`extra["project_id"]`)."""
    import uuid

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
    result = crawl_pod.invoke(pod_state)
    return result["export"]
