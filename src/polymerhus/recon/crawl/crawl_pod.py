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
exception, or an empty manifest route to a terminal `fail` node that sets
`verdict="failed"` and curates ONE `reduced_crawl_coverage` Observation
anchored to the pod's input BaseURL. A partial v2 manifest is different: its
endpoints and parameters are real evidence, so it takes the normal
parse/triager/curator path and ALSO curates the `reduced_crawl_coverage`
Observation. Nothing from this node ever propagates as an unhandled exception.

The crawl path is session-only (#395, D20): the node runs under the
gateway-established auth state. The feed supplies the decoupled auth-context
reference (`extra["browser_context_ref"]`) and the gate metadata
(`extra["browser_auth"]`: `auth_probe` and `login_url`). The browser MCP
mounts the context object from the pool store, restores cookies and
localStorage, and gates the result. There is no interactive `steel_await_auth`
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
import logging
import re

from typing import Optional
from urllib.parse import urlsplit

from langgraph.graph import StateGraph, START, END

from polymerhus.recon.crawl.sessions import (
    CrawlSession,
    anonymous_session,
    run_crawl_sessions,
)
from polymerhus.recon.domain.types import PodState, PodExport, Observation
from polymerhus.recon.domain.parsers import get_parser
from polymerhus.recon.domain.parsers._urls import registrable_domain
from polymerhus.recon.domain.curator import curate
from polymerhus.recon.domain.pod import default_triage_fn, _input_asset_url
from polymerhus.recon.js_intake import JsIntakeStore
from polymerhus.recon.js_intake.context import input_context_ref

_EMPTY_MANIFEST_KEYS = ("endpoints", "js_urls")
_LOGGER = logging.getLogger(__name__)
_JS_CONTENT_TYPES = {
    "application/ecmascript",
    "application/javascript",
    "application/node",
    "application/x-javascript",
    "text/ecmascript",
    "text/javascript",
}
_JS_SUFFIXES = (".js", ".mjs", ".cjs")


class CrawlPodState(PodState, total=False):
    """`PodState` plus the fields this graph's `crawl` node produces.

    LangGraph's `StateGraph` schema only merges keys declared on the schema
    TypedDict - a node returning an undeclared key is silently dropped, not
    an error - so the manifest batch, the per-session failures, and the
    terminal error must be declared here rather than only referenced ad hoc
    from `pod.py`'s `PodState`.
    """

    manifest: Optional[dict]
    manifests: list[dict]
    session_errors: list[dict]
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

    A partial run is real evidence with reduced coverage, not a failed crawl:
    its endpoints and parameters must reach the graph. The reason rides the
    state so the curator can attach the reduced-coverage observation without
    discarding the surface the crawl did capture.
    """
    if not manifest or not isinstance(manifest, dict):
        return None
    run = manifest.get("run")
    if not isinstance(run, dict) or run.get("partial") is not True:
        return None
    return str(run.get("stop_reason") or "partial")


def _normalize_crawl_result(result) -> tuple[list[dict], list[dict]]:
    """Read a manifest batch or one legacy manifest from the collaborator.

    The production collaborator returns `{"manifests": [...], "sessions":
    [...]}`. The injected fakes and older callers return one manifest dict;
    both shapes are accepted so the pod graph stays backward-compatible.
    """
    if isinstance(result, dict) and isinstance(result.get("manifests"), list):
        manifests = [
            manifest
            for manifest in result.get("manifests") or []
            if isinstance(manifest, dict)
        ]
        sessions = list(result.get("sessions") or [])
        return manifests, sessions
    if isinstance(result, dict):
        return [result], []
    if isinstance(result, list):
        return [manifest for manifest in result if isinstance(manifest, dict)], []
    return [], []


def _session_error(manifest: dict, reason: str) -> dict:
    run = manifest.get("run") if isinstance(manifest.get("run"), dict) else {}
    return {
        "account": run.get("account"),
        "role": run.get("role"),
        "error": str(reason),
    }


def _manifest_run(manifest: dict | None) -> dict:
    if not isinstance(manifest, dict):
        return {}
    run = manifest.get("run")
    return run if isinstance(run, dict) else {}


def _manifest_completeness(manifest: dict | None) -> str:
    run = _manifest_run(manifest)
    return "partial" if run.get("partial") is True else "complete"


def _manifest_auth(manifest: dict | None, extra: dict) -> tuple[str, str | None]:
    """Resolve auth from the session's manifest, never from the target URL."""
    run = _manifest_run(manifest)
    account = run.get("account")
    if isinstance(account, str) and account:
        return "authenticated", account
    selected = extra.get("auth_account")
    if isinstance(selected, str) and selected:
        return "authenticated", selected
    return "anonymous", None


def _header(headers: object, name: str) -> str | None:
    if not isinstance(headers, dict):
        return None
    wanted = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == wanted and isinstance(value, str):
            return value
    return None


def _is_js_flow(flow) -> bool:
    if str(getattr(flow, "resource_type", "") or "").lower() == "script":
        return True
    url = str(getattr(flow, "url", "") or "")
    if urlsplit(url).path.lower().endswith(_JS_SUFFIXES):
        return True
    mime = (
        _header(getattr(flow, "response_headers", None), "content-type")
        or str(getattr(flow, "mime_type", "") or "")
    )
    return mime.split(";", 1)[0].strip().lower() in _JS_CONTENT_TYPES


def _record_captured_js_flows(
    *,
    capture_store,
    project_id: str,
    run_id: str,
    pod_id: str,
    session,
    flows,
) -> int:
    """Project the crawler's existing CDP capture into the JS byte store.

    This consumes the same once-only capture the HTTP-history edge receives.
    A debugger record is not a request: only a real matching CDP flow can
    produce bytes, and a truncated or bodyless flow stays an explicit gap.
    """
    if capture_store is None or not flows or session.anonymous:
        return 0
    auth_ref = session.account or session.browser_context_ref
    if not auth_ref:
        return 0
    ordered = sorted(
        (flow for flow in flows if _is_js_flow(flow)),
        key=lambda flow: (
            float(getattr(flow, "received_at", 0.0) or 0.0),
            str(getattr(flow, "request_id", "") or ""),
        ),
    )
    recorded = 0
    for sequence, flow in enumerate(ordered, start=1):
        exact_url = str(getattr(flow, "url", "") or "")
        if not exact_url:
            continue
        status = int(getattr(flow, "status", 0) or 0)
        content_type = (
            _header(getattr(flow, "response_headers", None), "content-type")
            or getattr(flow, "mime_type", None)
        )
        sourcemap = _header(
            getattr(flow, "response_headers", None), "sourcemap"
        )
        x_sourcemap = _header(
            getattr(flow, "response_headers", None), "x-sourcemap"
        )
        body = getattr(flow, "response_body", None)
        common = {
            "project_id": project_id,
            "run_id": run_id,
            "pod_id": pod_id,
            "crawl_id": str(getattr(flow, "page_id", "") or run_id),
            "auth_context_ref": auth_ref,
            "exact_url": exact_url,
            "status": status,
            "content_type": (
                content_type if isinstance(content_type, str) else None
            ),
            "sequence": sequence,
            "sourcemap_header": sourcemap,
            "x_sourcemap_header": x_sourcemap,
        }
        if not 200 <= status < 300:
            capture_store.record_gap(
                **common,
                reason=f"http_status_{status or 'unknown'}",
            )
        elif getattr(flow, "body_truncated", False):
            capture_store.record_gap(
                **common,
                reason="capture_body_truncated",
            )
        elif getattr(flow, "error", None):
            capture_store.record_gap(
                **common,
                reason="response_error",
            )
        elif not isinstance(body, (bytes, bytearray)) or not body:
            capture_store.record_gap(
                **common,
                reason="response_body_unavailable",
            )
        else:
            capture_store.record_bytes(**common, body=bytes(body))
        recorded += 1
    return recorded


def _session_coverage_observation(
    input_asset: dict, entry: dict
) -> Observation:
    target = _input_asset_url(input_asset) or ""
    label = entry.get("role") or entry.get("account") or "crawl session"
    reason = entry.get("error") or "unknown"
    return Observation(
        macro_kind="reduced_crawl_coverage",
        severity="info",
        evidence=f"{label}: {reason}",
        rationale=(
            f"The {label} crawl session did not complete successfully; "
            "endpoint/parameter coverage for this session is reduced relative "
            "to a full crawl."
        ),
        anchor={"type": "BaseURL", "identity": {"url": target}},
        source_job="crawl",
        source_tool="steel_crawl",
    )


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
    capture_store=None,
):
    """The production `steel_crawl` collaborator: the deterministic engine.

    The pod passes the job's `extra`, which carries the project and run ids,
    the selected account, and the decoupled auth-context reference. The engine
    mounts that context through the browser MCP, runs the real CDP sidecar, the MCP page
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
    from polymerhus.app.llm.browser_tools import (  # noqa: PLC0415
        browser_session_name,
    )
    from polymerhus.recon.crawl.steel.live import (  # noqa: PLC0415
        LiveRunContext,
        run_live_crawl,
    )

    browser_auth = browser_auth or {}
    raw_sessions = extra.get("auth_sessions")
    sessions: list[CrawlSession] = []
    if isinstance(raw_sessions, list):
        sessions = [
            CrawlSession.from_descriptor(item, target=target)
            for item in raw_sessions
            if isinstance(item, dict)
        ]
    if not sessions and (
        extra.get("browser_context_ref")
        or extra.get("auth_account")
        or browser_auth
    ):
        sessions = [
            CrawlSession.from_descriptor(
                {
                    "account": extra.get("auth_account"),
                    "root_url": target,
                    "auth_probe": browser_auth.get("auth_probe"),
                    "login_url": browser_auth.get("login_url"),
                    "browser_context_ref": extra.get("browser_context_ref"),
                },
                target=target,
            )
        ]
    if not sessions and not bool(extra.get("auth_accounts_present")):
        sessions = [anonymous_session(target)]

    max_workers = int(os.environ.get("STEEL_CRAWL_MAX_WORKERS", "2"))
    max_duration_s = float(
        os.environ.get("STEEL_CRAWL_MAX_DURATION_S", "1800")
    )
    if capture_store is None and bool(extra.get("js_capture_enabled")):
        from polymerhus.recon.js_acquisition import SteelCaptureStore  # noqa: PLC0415

        capture_store = SteelCaptureStore(root=DATA_ROOT)

    def run_one(session: CrawlSession) -> dict:
        session_run_id = _session_run_id(run_id, session)
        session_name = browser_session_name(
            project_id,
            f"crawl-{session.role or 'baseline'}",
            session_run_id,
            session.account,
        )
        session_scope = list(scope)
        root_host = urlsplit(session.root_url).hostname
        if root_host and root_host not in session_scope:
            session_scope.append(root_host)
        context = LiveRunContext(
            project_id=project_id,
            run_id=session_run_id,
            session_name=session_name,
            target_url=target,
            scope=session_scope,
            data_root=DATA_ROOT,
            auth_probe=session.auth_probe,
            login_url=session.login_url,
            account=session.account,
            role=session.role,
            root_url=session.root_url,
            anonymous=session.anonymous,
            edge_url=os.environ.get("KALI_HTTP_HISTORY_EDGE_URL") or None,
            edge_token=os.environ.get("KALI_HTTP_HISTORY_EDGE_TOKEN") or None,
            browser_mcp_url=os.environ.get("KALI_BROWSER_MCP_URL", "").strip(),
            browser_context_ref=session.browser_context_ref,
            max_duration_s=max_duration_s,
            coverage={"scope": session_scope},
        )
        result = run_live_crawl(context)
        if capture_store is not None and not session.anonymous:
            selected_account = str(extra.get("auth_account") or "")
            account = session.account or session.browser_context_ref or ""
            if not selected_account or account == selected_account:
                _record_captured_js_flows(
                    capture_store=capture_store,
                    project_id=project_id,
                    run_id=run_id,
                    pod_id=session_name,
                    session=session,
                    flows=result.flows,
                )
        return result.manifest.model_dump(mode="json")

    results = run_crawl_sessions(
        sessions, run_one=run_one, max_workers=max_workers
    )
    return {
        "manifests": [
            result.manifest
            for result in results
            if result.manifest is not None
        ],
        # Internal handoff only: the pod graph links scanner leads to the
        # existing CDP capture occurrences through this same store.
        "capture_store": capture_store,
        "sessions": [
            {
                "account": result.session.account,
                "role": result.session.role,
                "error": result.error,
            }
            for result in results
        ],
    }


default_run_crawl_fn = live_run_crawl_fn


def _session_run_id(run_id: str, session: CrawlSession) -> str:
    """A stable, unique run id for one session lifecycle."""
    label = session.account or session.role or "anonymous"
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", label).strip("-_").lower()
    return f"{run_id}-{slug or 'session'}"


def _host_of(url: str) -> str:
    return (url or "").split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()


def _safe_session_suffix(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "session"))
    return text.strip("-_") or "session"


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


def build_crawl_pod(
    *,
    run_crawl_fn,
    parse_fn,
    triage_fn,
    curate_fn,
    intake_store=None,
    capture_store=None,
):
    """Build the compiled crawl-pod subgraph, injecting the side-effecting
    collaborators: run_crawl_fn(target, scope=scope, browser_auth=...,
    extra=...) -> manifest dict, parse_fn(stdout) ->
    list[AssetDelta], triage_fn(exec_result, assets, job) ->
    list[Observation] (called with a synthetic exec_result carrying the
    manifest JSON as stdout, mirroring pod.py's triager signature),
    curate_fn(assets, observations, project_id) -> (int, int).

    Session-only (#395, D20): the `crawl` node runs `run_crawl_fn` under the
    feed-projected auth-context reference. The browser MCP restores cookies and
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
        accepts_capture = (
            "capture_store" in inspect.signature(run_crawl_fn).parameters
        )
    except (TypeError, ValueError):
        accepts_extra = False
        accepts_capture = False

    def record_intake(
        state: CrawlPodState,
        manifest: dict | None,
        *,
        terminal_result: str,
        output_completeness: str,
        auth_label: str | None = None,
        auth_ref: str | None = None,
        pod_id: str | None = None,
        capture_store_override=None,
    ):
        run_id = state.get("run_id")
        session_id = state.get("session_id")
        if intake_store is None or not run_id or not session_id:
            return None
        extra = state.get("extra") or {}
        if auth_label is None or auth_ref is None:
            auth_label, auth_ref = _manifest_auth(manifest, extra)
        manifest_run = _manifest_run(manifest)
        session_name = manifest_run.get("session_name")
        pod_id = (
            pod_id
            or (
                str(session_name)
                if isinstance(session_name, str) and session_name
                else str(session_id)
            )
        )
        try:
            path = intake_store.record_manifest(
                project_id=state.get("project_id") or run_id,
                run_id=run_id,
                pod_id=pod_id,
                producer="steel_crawl",
                input_context_ref=input_context_ref(
                    state.get("input_asset") or {},
                    state.get("asset_context") or "",
                ),
                manifest=manifest,
                terminal_result=terminal_result,
                output_completeness=output_completeness,
                auth_context_label=auth_label,
                auth_context_ref=auth_ref,
            )
            active_capture_store = (
                capture_store_override
                if capture_store_override is not None
                else capture_store
            )
            if active_capture_store is not None:
                records = [
                    json.loads(line)
                    for line in path.read_text(encoding="utf-8").split("\n")
                    if line.strip()
                ]
                for lead in records[1:]:
                    if lead.get("record_type") != "lead":
                        continue
                    active_capture_store.link_leads(
                        project_id=state.get("project_id") or run_id,
                        run_id=run_id,
                        pod_id=pod_id,
                        auth_context_ref=lead.get("auth_context_ref") or None,
                        exact_url=str(lead.get("exact_url") or ""),
                        lead_ids=[str(lead.get("lead_id"))],
                    )
            return path
        except Exception:  # noqa: BLE001 - intake is side output
            _LOGGER.warning(
                "JavaScript intake side output failed for Steel pod %s; "
                "continuing graph path",
                pod_id,
                exc_info=True,
            )
            return None

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
        if accepts_capture:
            kwargs["capture_store"] = capture_store
        try:
            result = run_crawl_fn(target, **kwargs)
        except Exception as exc:  # noqa: BLE001 - best-effort, never raise
            auth_label, auth_ref = _manifest_auth(None, extra)
            record_intake(
                state,
                None,
                terminal_result="failed",
                output_completeness="failed",
                auth_label=auth_label,
                auth_ref=auth_ref,
            )
            return {
                "manifest": None,
                "manifests": [],
                "session_errors": [],
                "crawl_error": str(exc),
            }

        active_capture_store = capture_store
        if (
            isinstance(result, dict)
            and result.get("capture_store") is not None
        ):
            active_capture_store = result["capture_store"]
        manifests, sessions = _normalize_crawl_result(result)
        kept: list[dict] = []
        errors: list[dict] = []
        for manifest_index, manifest in enumerate(manifests):
            manifest_run = _manifest_run(manifest)
            session_name = manifest_run.get("session_name")
            pod_id = (
                str(session_name)
                if isinstance(session_name, str) and session_name
                else (
                    str(state.get("session_id"))
                    if len(manifests) == 1
                    else f"{state.get('session_id')}--session-{manifest_index + 1}"
                )
            )
            if _manifest_is_empty(manifest):
                record_intake(
                    state,
                    manifest,
                    terminal_result="success",
                    output_completeness="unknown",
                    pod_id=pod_id,
                    capture_store_override=active_capture_store,
                )
                errors.append(_session_error(manifest, "empty crawl manifest"))
                continue
            kept.append(manifest)
            record_intake(
                state,
                manifest,
                terminal_result="success",
                output_completeness=_manifest_completeness(manifest),
                pod_id=pod_id,
                capture_store_override=active_capture_store,
            )
            partial = _manifest_partial(manifest)
            if partial is not None:
                errors.append(_session_error(manifest, partial))
        for session in sessions:
            if isinstance(session, dict) and session.get("error"):
                account = session.get("account")
                record_intake(
                    state,
                    None,
                    terminal_result="failed",
                    output_completeness="failed",
                    auth_label=(
                        "authenticated"
                        if isinstance(account, str) and account
                        else "anonymous"
                    ),
                    auth_ref=account if isinstance(account, str) else None,
                    pod_id=(
                        f"{state.get('session_id')}--"
                        f"{_safe_session_suffix(account or session.get('role'))}"
                    ),
                    capture_store_override=active_capture_store,
                )
                errors.append(
                    {
                        "account": session.get("account"),
                        "role": session.get("role"),
                        "error": str(session.get("error")),
                    }
                )
        if not kept:
            reason = errors[0]["error"] if errors else "empty crawl manifest"
            return {
                "manifest": None,
                "manifests": [],
                "session_errors": errors,
                "crawl_error": reason,
            }
        return {
            "manifest": kept[0],
            "manifests": kept,
            "session_errors": errors,
        }

    def gate(state: CrawlPodState) -> str:
        return "parse" if state.get("manifests") else "fail"

    def parse(state: CrawlPodState) -> dict:
        assets = []
        for manifest in state.get("manifests") or []:
            assets.extend(parse_fn(json.dumps(manifest)))
        return {"assets": assets}

    def triager(state: CrawlPodState) -> dict:
        from polymerhus.recon.domain.types import ExecResult

        job = state.get("job")
        observations = []
        for manifest in state.get("manifests") or []:
            exec_result = ExecResult(
                stdout=json.dumps(manifest), stderr="", returncode=0
            )
            observations.extend(
                triage_fn(exec_result, state.get("assets", []), job)
            )
        return {"observations": observations}

    def curator_node(state: CrawlPodState) -> dict:
        assets = state.get("assets", [])
        observations = list(state.get("observations", []))
        # Every partial or failed session is ingested as evidence, never
        # discarded. The successful manifests supply the assets; each failure
        # carries one reduced-coverage observation naming its session.
        for entry in state.get("session_errors") or []:
            observations.append(
                _session_coverage_observation(
                    state.get("input_asset") or {}, entry
                )
            )
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
        observations = [_coverage_observation(input_asset, reason)]
        for entry in state.get("session_errors") or []:
            observations.append(
                _session_coverage_observation(input_asset, entry)
            )
        _, observations_merged, _, merged_observations = curate_fn(
            [], observations, state["project_id"]
        )
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
    intake_store=JsIntakeStore(),
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
