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
from agent.recon.parsers._urls import registrable_domain
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
    run_id: Optional[str]
    phase: Optional[int]


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


def default_run_crawl_fn(target: str, *, scope: list[str], auth_cookies=None):
    """Real collaborator: run the agentic Steel crawl loop synchronously.

    Wraps `crawl_agent.run_crawl` (async) behind `run_coro_blocking`,
    resolving the crawl-agent module lazily so importing this module
    performs no I/O. `auth_cookies` (from the project's `auth_context.cookies`)
    is forwarded so the Steel browser context is seeded for non-interactive
    auth; it is `None` for an anonymous crawl.
    """
    from agent.recon.crawl import crawl_agent
    from agent.recon.async_bridge import run_coro_blocking

    return run_coro_blocking(crawl_agent.run_crawl(target, scope=scope, auth_cookies=auth_cookies))


def default_run_crawl_authenticated_fn(target: str, *, scope: list[str], on_awaiting_auth=None):
    """Real collaborator: authenticated agentic crawl (interactive
    `steel_await_auth` MVP path), synchronously.

    Wraps `crawl_agent.run_crawl_authenticated` (async) behind
    `run_coro_blocking`, mirroring `default_run_crawl_fn`. Returns
    `(manifest, awaiting_status)`. `on_awaiting_auth` is forwarded so the
    viewer URL is surfaced the instant the Steel session is precreated (before
    the blocking crawl).
    """
    from agent.recon.crawl import crawl_agent
    from agent.recon.async_bridge import run_coro_blocking

    return run_coro_blocking(
        crawl_agent.run_crawl_authenticated(
            target, scope=scope, on_awaiting_auth=on_awaiting_auth
        )
    )


def _host_of(url: str) -> str:
    return (url or "").split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()


def credentials_apply_to_target(credentials: dict, target_url: str) -> bool:
    """D23-7: credentials belong to ONE app. A crawl pod attempts the login only
    when its target host is in the credentials' domain - the explicit
    `credentials.domain`, else the registrable domain of `login_url`. Prevents
    submitting the same credentials to every host in a multi-BaseURL run
    (lockout / mis-auth). Fail-closed: no usable domain -> False."""
    if not isinstance(credentials, dict):
        return False
    dom = credentials.get("domain")
    if not dom:
        host = _host_of(credentials.get("login_url") or "")
        dom = registrable_domain(host) if host else ""
    if not dom:
        return False
    dom = dom.lower()
    target_host = _host_of(target_url)
    return target_host == dom or target_host.endswith("." + dom)


def default_run_crawl_credentialed_fn(target: str, *, scope: list[str], credentials: dict) -> dict:
    """Real collaborator: autonomous credentialed agentic crawl (D23), sync.

    Wraps `crawl_agent.run_crawl_credentialed` (async) behind `run_coro_blocking`,
    mirroring `default_run_crawl_fn`. Returns the crawl manifest."""
    from agent.recon.crawl import crawl_agent
    from agent.recon.async_bridge import run_coro_blocking

    return run_coro_blocking(
        crawl_agent.run_crawl_credentialed(target, scope=scope, credentials=credentials)
    )


def default_status_sink(run_id: str, phase: int, job: str, viewer_url: str) -> None:
    """Surface a crawl's Steel `viewer_url` to job status MID-FLIGHT.

    Writes the viewer URL to the recon registry row (`recon_jobs`) keyed by
    `(run_id, phase, job)` - the SAME row `pipeline._run_one` later finalizes
    and that `GET /recon/{run_id}` reads - with a non-terminal `in_progress`
    status, so the operator sees the login URL while the Steel session is still
    open (the pipeline's post-run `stats["viewer_url"]` pass-through then
    reasserts it on the terminal write). Best-effort: a registry blip must never
    abort the crawl, so callers wrap this in try/except; it is also guarded here.

    `job` is the recon job name, which for the agentic crawl equals its
    `JobSpec.tool` ("steel_crawl"), i.e. the key `pipeline._run_one` upserts.
    """
    try:
        from agent.app.clients import pg  # noqa: PLC0415

        pg.upsert_job(run_id, phase, job, "in_progress", stats={"viewer_url": viewer_url})
    except Exception:  # noqa: BLE001 - status surfacing is best-effort
        pass


def default_notify_fn(run_id: str, phase: int, job: str, viewer_url: str) -> None:
    """Best-effort Discord notify wrapper (see agent.recon.notify)."""
    from agent.recon import notify  # noqa: PLC0415
    notify.notify_awaiting_auth(run_id, phase, job, viewer_url)


def build_crawl_pod(*, run_crawl_fn, parse_fn, triage_fn, curate_fn, run_crawl_authenticated_fn=None, run_crawl_credentialed_fn=None, status_sink=None, notify_fn=None):
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
    The `awaiting_status["viewer_url"]` is surfaced two ways: (1) EARLY, the
    instant the Steel session is precreated, via `status_sink(run_id, phase,
    job, viewer_url)` (default `default_status_sink` writes it to the
    `recon_jobs` registry row `GET /recon/{run_id}` reads) - so the operator can
    complete the manual login while the session window is still open; and (2) on
    the pod export's `stats`, which `pipeline.py` reasserts on the terminal job
    write. `status_sink` is injectable so tests assert the early call without a
    live registry.

    Non-interactive cookie-injection takes PRECEDENCE over the interactive path:
    when the `auth_context` carries non-empty `cookies`, the `crawl` node calls
    the plain `run_crawl_fn(target, scope=scope, auth_cookies=...)` and the Steel
    provider seeds the browser context with them (`context.add_cookies`) before
    the crawl, so no human-viewer step is needed. The interactive
    `run_crawl_authenticated_fn` path is used only when `use_auth` is signalled
    with an `auth_context` that has NO cookies (login handled by a human in the
    viewer).
    """

    def crawl(state: CrawlPodState) -> dict:
        input_asset = state.get("input_asset") or {}
        extra = state.get("extra") or {}
        job = state.get("job")
        target = _input_asset_url(input_asset)
        scope = extra.get("scope") or ([target] if target else [])

        auth_context = extra.get("auth_context") or {}
        auth_cookies = auth_context.get("cookies") or []
        credentials = auth_context.get("credentials") or {}
        # Auth-eligibility is the pipeline's single concern (C1): auth_context is
        # present in extra only for a use_auth job, so its presence IS the signal.
        use_auth_signal = bool(auth_context)
        cred_fn = (
            run_crawl_credentialed_fn if run_crawl_credentialed_fn is not None
            else default_run_crawl_credentialed_fn
        )

        viewer_url = None
        try:
            if (
                use_auth_signal
                and credentials
                and credentials_apply_to_target(credentials, target)
            ):
                # D23: AUTONOMOUS CREDENTIALED LOGIN drives the agentic crawl. The
                # ReAct loop logs in with the operator's credentials before
                # crawling (credentials are the agentic-crawl auth channel;
                # cookies remain the request-based tools' channel). Host-gated so
                # one app's credentials are never scattered across every BaseURL.
                manifest = cred_fn(target, scope=scope, credentials=credentials)
            elif use_auth_signal and auth_cookies:
                # NON-INTERACTIVE AUTH: the project supplied session cookies, so
                # inject them into the Steel browser context and run a plain
                # crawl - no human steel_await_auth viewer step. The provider's
                # context.add_cookies seeds the session before any navigation
                # (see steel_provider._steel_crawl_start). Cookies present takes
                # precedence over the interactive path below.
                manifest = run_crawl_fn(target, scope=scope, auth_cookies=auth_cookies)
            elif use_auth_signal and run_crawl_authenticated_fn is not None:
                # EARLY SURFACING (fixes the SP4 "viewer_url too late" defect):
                # build a callback bound to this job's registry key and pass it
                # into the authenticated crawl. `run_crawl_authenticated_fn`
                # invokes it the instant the Steel session is precreated - BEFORE
                # the blocking crawl - so the sink writes the viewer_url to the
                # recon_jobs row that GET /recon/{run_id} reads, while the operator
                # still has the session window to complete the login. The export
                # stats below still carry it too (belt-and-suspenders / tests).
                run_id = state.get("run_id")
                phase = state.get("phase")
                job_name = getattr(job, "tool", None)
                sink = status_sink if status_sink is not None else default_status_sink
                notify = notify_fn if notify_fn is not None else default_notify_fn

                def _on_awaiting_auth(awaiting_status):
                    vu = (awaiting_status or {}).get("viewer_url")
                    if vu and run_id is not None and phase is not None and job_name:
                        try:
                            sink(run_id, phase, job_name, vu)
                        except Exception:  # noqa: BLE001 - best-effort surfacing
                            pass
                        try:
                            notify(run_id, phase, job_name, vu)
                        except Exception:  # noqa: BLE001 - best-effort out-of-band notify
                            pass

                manifest, awaiting_status = run_crawl_authenticated_fn(
                    target, scope=scope, on_awaiting_auth=_on_awaiting_auth
                )
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
        # run_id/phase let the crawl node's interactive-auth path write the
        # Steel viewer_url to the recon_jobs registry row mid-flight (early
        # surfacing) - the SAME (run_id, phase, job) row pipeline._run_one uses.
        "run_id": run_id,
        "phase": phase,
    }
    # Langfuse tracing: the crawl-pod tree (crawl/parse/triager/curator) becomes
    # the per-pod span tree. Empty list (Langfuse unconfigured) is inert.
    from agent.app.observability import get_langfuse_callbacks

    result = crawl_pod.invoke(
        pod_state, config={"callbacks": get_langfuse_callbacks()}
    )
    return result["export"]
