"""Crawl-pod variant: crawl -> parse -> triager -> curator.

`build_crawl_pod` is the `configurator_mode="agent"` counterpart of
`polymerhus.recon.domain.pod.build_pod_graph`: instead of the deterministic
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

The crawl path is session-only (#395, D20): the node runs under the
gateway-established auth state. The feed supplies the stable browser key
(`extra["steel_session"]`) and the gate metadata
(`extra["browser_auth"]`: `auth_probe` and `login_url`). The browser MCP
mounts the key, restores cookies and localStorage from the pool store, and
gates the result. There is no interactive `steel_await_auth`
human-in-the-loop path, no credentialed login, and no operator prompt -
post-gateway, auth is already established and a mid-run prompt is strictly
worse.

`default_run_crawl_fn` is the synchronous live engine (`live_run_crawl`), so
every node in this graph, like every node in `pod.py`'s graph, is a plain
sync function and the compiled graph is `.invoke()`-able synchronously from
`job_agent`, even though `job_agent` itself runs inside the pipeline's event
loop.
"""
from __future__ import annotations

import json

from typing import Optional

from langgraph.graph import StateGraph, START, END

from polymerhus.recon.domain.types import PodState, PodExport, Observation
from polymerhus.recon.domain.parsers import get_parser
from polymerhus.recon.domain.parsers._urls import registrable_domain
from polymerhus.recon.domain.curator import curate
from polymerhus.recon.domain.pod import default_triage_fn, _input_asset_url

_EMPTY_MANIFEST_KEYS = ("endpoints", "js_urls")


class CrawlPodState(PodState, total=False):
    """`PodState` plus the field this graph's `crawl` node produces.

    LangGraph's `StateGraph` schema only merges keys declared on the schema
    TypedDict - a node returning an undeclared key is silently dropped, not
    an error - so `manifest`/`crawl_error` must be declared here rather
    than only referenced ad hoc from `pod.py`'s `PodState`.
    """

    manifest: Optional[dict]
    crawl_error: Optional[str]


def _manifest_is_empty(manifest: dict | None) -> bool:
    if not manifest or not isinstance(manifest, dict):
        return True
    if manifest.get("schema_version") == "steel-crawl/v2":
        # A v2 manifest is the graph input, not the legacy endpoint list: a
        # real crawl that captured flows but declared no endpoint (an
        # unauthenticated canvas app, for example) is still a valid result.
        stats = manifest.get("stats") or {}
        return not any(
            (
                manifest.get("endpoints"),
                manifest.get("parameters"),
                manifest.get("scripts"),
                manifest.get("realtime"),
                stats.get("flows"),
            )
        )
    return not any(manifest.get(key) for key in _EMPTY_MANIFEST_KEYS)


def _manifest_partial(manifest: dict | None) -> str | None:
    """The partial stop reason, or None when the v2 run is complete.

    A partial run is evidence, not a successful graph input: the pod routes it
    to the reduced-coverage fail node instead of parsing a half surface as if
    it were complete.
    """
    if not manifest or not isinstance(manifest, dict):
        return None
    run = manifest.get("run")
    if not isinstance(run, dict) or run.get("partial") is not True:
        return None
    return str(run.get("stop_reason") or "partial")


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


def live_run_crawl_fn(
    target: str,
    *,
    scope: list[str],
    browser_auth=None,
    extra=None,
):
    """The production `steel_crawl` collaborator: the deterministic engine.

    The pod passes the job's `extra`, which carries the project and run ids,
    the selected account, and the stable browser key. The engine mounts that
    key through the browser MCP, runs the real CDP sidecar, the MCP page
    factory, the Jev policy, and the bounded DFS, and returns the v2 manifest
    dict the pod's parser consumes. Every runtime failure is raised to the
    pod's `fail` node, which records reduced coverage.
    """
    import os  # noqa: PLC0415

    extra = dict(extra or {})
    project_id = str(extra.get("project_id") or "")
    run_id = str(extra.get("run_id") or "")
    if not project_id or not run_id:
        raise RuntimeError(
            "the live steel crawl needs a project_id and a run_id in its extra"
        )
    from polymerhus.app.data_root import DATA_ROOT  # noqa: PLC0415
    from polymerhus.app.steel_session_state import (  # noqa: PLC0415
        browser_session_name,
    )
    from polymerhus.recon.crawl.steel.live import (  # noqa: PLC0415
        LiveRunContext,
        run_live_crawl,
    )

    session_name = str(
        extra.get("steel_session")
        or browser_session_name(project_id, extra.get("auth_account"))
    )
    browser_auth = browser_auth or {}
    context = LiveRunContext(
        project_id=project_id,
        run_id=run_id,
        session_name=session_name,
        target_url=target,
        scope=list(scope),
        data_root=DATA_ROOT,
        auth_probe=browser_auth.get("auth_probe"),
        login_url=browser_auth.get("login_url"),
        account=extra.get("auth_account"),
        edge_url=os.environ.get("KALI_HTTP_HISTORY_EDGE_URL") or None,
        edge_token=os.environ.get("KALI_HTTP_HISTORY_EDGE_TOKEN") or None,
        browser_mcp_url=os.environ.get("KALI_BROWSER_MCP_URL", "").strip(),
        max_duration_s=float(
            os.environ.get("STEEL_CRAWL_MAX_DURATION_S", "600")
        ),
        coverage={"scope": list(scope)},
    )
    result = run_live_crawl(context)
    return result.manifest.model_dump(mode="json")


default_run_crawl_fn = live_run_crawl_fn


def _host_of(url: str) -> str:
    return (url or "").split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()


def _resolve_crawl_scope(extra: dict, target: str) -> list[str]:
    """Fold each scope entry to the registrable domain of its host (dedup,
    order-preserving). Shared by the crawl node (frontier scope) and the
    curator node (out-of-scope BaseURL drop) so both use ONE scope.

    `_host_of` first strips scheme/path/port (a scheme-prefixed entry from the
    `[target]` fallback or an upstream `extra["scope"]` would otherwise never
    match a bare host). The provider's `_registrable_in_scope` admits a host
    equal to or a subdomain of any scope entry, so scope ["daytona.io"] lets the
    frontier reach app./docs./api.daytona.io while excluding off-registrable
    hosts (auth0/stripe/cloudfront) - the operator's "any subdomain of the
    registrable domain" scope rule. Using this SAME fold as the curator's
    `scope_domain` (rather than the pipeline's stricter seed-host
    `extra["scope_domain"]`) keeps the crawled frontier and the BaseURLs the
    curator retains on one definition, so legitimately-crawled sibling
    subdomains survive the D14 out-of-scope drop.
    """
    raw_scope = extra.get("scope") or ([target] if target else [])
    scope: list[str] = []
    for s in raw_scope:
        h = _host_of(s)
        if not h:
            continue
        reg = registrable_domain(h) or h
        if reg not in scope:
            scope.append(reg)
    return scope


def build_crawl_pod(*, run_crawl_fn, parse_fn, triage_fn, curate_fn):
    """Build the compiled crawl-pod subgraph, injecting the side-effecting
    collaborators: run_crawl_fn(target, scope=scope, browser_auth=...,
    extra=...) -> manifest dict, parse_fn(stdout) ->
    list[AssetDelta], triage_fn(exec_result, assets, job) ->
    list[Observation] (called with a synthetic exec_result carrying the
    manifest JSON as stdout, mirroring pod.py's triager signature),
    curate_fn(assets, observations, project_id) -> (int, int).

    Session-only (#395, D20): the `crawl` node runs `run_crawl_fn` under the
    feed-projected stable key. The browser MCP restores cookies and
    localStorage from the pool store; the feed supplies only the oracle and
    login URL. Auth-eligibility is the pipeline's single concern (C1): the
    feed keys are present only for a `use_auth` job with a resolved account.
    A non-auth crawl, or an auth-capable job run without a resolved account,
    crawls anonymously. There is no interactive path and no operator prompt.

    The `extra` keyword is passed only to a collaborator that declares it, so
    the three-argument fakes of the contract tier stay compatible.
    """
    import inspect  # noqa: PLC0415

    try:
        accepts_extra = "extra" in inspect.signature(run_crawl_fn).parameters
    except (TypeError, ValueError):
        accepts_extra = False

    def crawl(state: CrawlPodState) -> dict:
        input_asset = state.get("input_asset") or {}
        extra = state.get("extra") or {}
        target = _input_asset_url(input_asset)
        # Resolve scope at this authoritative point via the shared helper, which
        # folds each entry to the REGISTRABLE DOMAIN of its host (dedup,
        # order-preserving). The curator node resolves the SAME scope so the
        # crawl frontier and the retained BaseURLs share one definition.
        scope = _resolve_crawl_scope(extra, target)

        browser_auth = extra.get("browser_auth") or None
        kwargs = {
            "scope": scope,
            "browser_auth": browser_auth,
        }
        if accepts_extra:
            kwargs["extra"] = extra
        try:
            manifest = run_crawl_fn(target, **kwargs)
        except Exception as exc:  # noqa: BLE001 - best-effort, never raise
            return {"manifest": None, "crawl_error": str(exc)}

        if _manifest_is_empty(manifest):
            return {"manifest": None, "crawl_error": "empty crawl manifest"}

        partial = _manifest_partial(manifest)
        if partial is not None:
            return {
                "manifest": None,
                "crawl_error": f"partial crawl: {partial}",
            }

        return {"manifest": manifest}

    def gate(state: CrawlPodState) -> str:
        return "parse" if state.get("manifest") is not None else "fail"

    def parse(state: CrawlPodState) -> dict:
        manifest = state.get("manifest") or {}
        assets = parse_fn(json.dumps(manifest))
        return {"assets": assets}

    def triager(state: CrawlPodState) -> dict:
        from polymerhus.recon.domain.types import ExecResult

        job = state.get("job")
        manifest = state.get("manifest") or {}
        exec_result = ExecResult(stdout=json.dumps(manifest), stderr="", returncode=0)
        observations = list(triage_fn(exec_result, state.get("assets", []), job))
        return {"observations": observations}

    def curator_node(state: CrawlPodState) -> dict:
        assets = state.get("assets", [])
        observations = state.get("observations", [])
        # Thread the SAME registrable-domain scope the crawl frontier used as the
        # curator's `scope_domain`, so the agnostic noise filter (D14/D15) drops
        # out-of-scope BaseURLs (js.stripe.com, *.auth0.com, api.us.svix.com,
        # *.usepylon.com) the crawl surfaces. Only-when-present so injected 3-arg
        # fake curate_fns stay compatible.
        extra = state.get("extra") or {}
        target = _input_asset_url(state.get("input_asset") or {})
        scope = _resolve_crawl_scope(extra, target)
        curate_kwargs = {}
        if scope:
            curate_kwargs["scope_domain"] = scope[0]
        assets_merged, observations_merged, merged_assets, merged_observations = curate_fn(
            assets, observations, state["project_id"], **curate_kwargs
        )
        export = PodExport(
            input_asset=state["input_asset"],
            verdict="success",
            assets_merged=assets_merged,
            observations_merged=observations_merged,
            # The curated payload the pipeline pushes into the analysis feed (#74).
            assets=merged_assets,
            observations=merged_observations,
        )
        return {"export": export}

    def fail(state: CrawlPodState) -> dict:
        input_asset = state.get("input_asset") or {}
        reason = state.get("crawl_error") or "crawl failed"
        observation = _coverage_observation(input_asset, reason)
        _, observations_merged, _, merged_observations = curate_fn([], [observation], state["project_id"])
        export = PodExport(
            input_asset=input_asset,
            verdict="failed",
            assets_merged=0,
            observations_merged=observations_merged,
            # the coverage observation that merged still rides the payload (#74)
            observations=merged_observations,
            error=reason,
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

    extra = dict(pod_input.get("extra") or {})
    project_id = extra.get("project_id", run_id)
    # The live engine needs the run identity; the pod's `extra` is the one
    # channel the pipeline already threads to the crawl collaborator.
    extra.setdefault("run_id", run_id)
    extra.setdefault("phase", phase)
    session_id = f"{run_id}-{phase}-{job.tool}-{uuid.uuid4().hex[:8]}"

    pod_state = {
        "job": job,
        "input_asset": pod_input.get("input_asset", {}),
        "asset_context": pod_input.get("asset_context", ""),
        "extra": extra,
        "session_id": session_id,
        "project_id": project_id,
        "run_id": run_id,
        "phase": phase,
    }
    # Langfuse tracing: the crawl-pod tree (crawl/parse/triager/curator) becomes
    # the per-pod span tree. Empty list (Langfuse unconfigured) is inert.
    from polymerhus.app.observability import get_langfuse_callbacks
    from polymerhus.recon.control.job_agent import pod_trace_metadata

    result = crawl_pod.invoke(
        pod_state,
        config={"callbacks": get_langfuse_callbacks(),
                "metadata": pod_trace_metadata(run_id, phase, job.tool)},
    )
    return result["export"]
