"""Thin adapter around the vendored `crawl_agentic._run_agentic_crawl` ReAct loop.

This module does NOT reimplement the crawl loop - `crawl_agentic.py` is
vendored verbatim from Redamon (`redamon-agent:/app/crawl_agentic.py`, see its
module docstring). This adapter only:

  * builds the minimal `mcp_manager` shim (`get_tools()`) the loop expects,
    defaulting to `steel_client.get_crawl_tools()` but accepting injected
    `tools` for tests;
  * builds `build_llm_fn` from `chat_model_for(model_role)` (or wraps an
    injected `llm` directly), so the vendored module's lazy
    `from api import _build_llm_with_model_for_user` fallback never fires;
  * constructs the `AgenticCrawlRequest` from our recon config defaults
    (`CRAWL_MAX_PAGES`/`CRAWL_MAX_DEPTH`/`CRAWL_MAX_ITERS`/`CRAWL_JOB_TIMEOUT_S`);
  * is best-effort: any exception from the loop (Steel misconfigured, tool
    error, LLM error, ...) yields the empty manifest so the crawl pod can
    degrade gracefully instead of crashing the pipeline (see plan's Global
    Constraints / §10.6).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from agent.recon import config
from agent.recon.crawl import steel_client
from agent.recon.crawl.crawl_agentic import (
    AgenticCrawlRequest,
    CRAWL_TOOL_NAMES,
    _run_agentic_crawl,
    precreate_auth_session,
)

__all__ = [
    "AgenticCrawlRequest",
    "CRAWL_TOOL_NAMES",
    "precreate_auth_session",
    "run_crawl",
    "run_crawl_authenticated",
]

_EMPTY_MANIFEST = {"endpoints": [], "js_urls": []}


def _load_skill() -> str:
    """Read the steel_crawl skill prompt next to this module."""
    return (Path(__file__).parent / "steel_crawl_skill.md").read_text(encoding="utf-8")


class _ToolsManager:
    """Minimal `mcp_manager` shim: the vendored loop only calls `get_tools()`."""

    def __init__(self, tools: list):
        self._tools = tools

    async def get_tools(self) -> list:
        return self._tools


async def run_crawl(
    target: str,
    *,
    scope: list[str],
    model_role: str = "crawler",
    tools: Optional[list] = None,
    llm=None,
    max_pages: Optional[int] = None,
    max_depth: Optional[int] = None,
    max_iters: Optional[int] = None,
    pre_created_crawl_id: Optional[str] = None,
) -> dict:
    """Run the bounded agentic-crawl ReAct loop and return its manifest.

    Best-effort: any exception (Steel unconfigured, tool/LLM failure, ...)
    yields the empty manifest rather than propagating, so callers (the crawl
    pod) can treat a failed crawl as reduced coverage instead of a crash.
    """
    try:
        resolved_tools = tools
        if resolved_tools is None:
            resolved_tools = await steel_client.get_crawl_tools()
        mcp_manager = _ToolsManager(resolved_tools)

        if llm is not None:
            def build_llm_fn(model, user_id, _llm=llm):
                return _llm
        else:
            from agent.app.llm.roles import chat_model_for

            def build_llm_fn(model, user_id, _role=model_role):
                return chat_model_for(_role)

        body = AgenticCrawlRequest(
            target=target,
            scope=list(scope),
            model=model_role,
            max_depth=max_depth if max_depth is not None else config.CRAWL_MAX_DEPTH,
            max_pages=max_pages if max_pages is not None else config.CRAWL_MAX_PAGES,
            max_iterations=max_iters if max_iters is not None else config.CRAWL_MAX_ITERS,
            job_timeout_s=config.CRAWL_JOB_TIMEOUT_S,
            auth_required=bool(pre_created_crawl_id),
        )

        return await _run_agentic_crawl(
            body,
            mcp_manager,
            build_llm_fn=build_llm_fn,
            pre_created_crawl_id=pre_created_crawl_id,
        )
    except Exception:  # noqa: BLE001 - best-effort, see module docstring
        return dict(_EMPTY_MANIFEST)


async def run_crawl_authenticated(
    target: str,
    *,
    scope: list[str],
    model_role: str = "crawler",
    tools: Optional[list] = None,
    llm=None,
    max_pages: Optional[int] = None,
    max_depth: Optional[int] = None,
    max_iters: Optional[int] = None,
    precreate_fn=None,
    _run_crawl_fn=None,
) -> "tuple[dict, Optional[dict]]":
    """Authenticated agentic crawl: interactive `steel_await_auth` MVP path.

    Pre-creates a Steel crawl session (`precreate_auth_session`, or an
    injected `precreate_fn` for tests) so the viewer URL is available
    *before* the ReAct loop runs, then drives the loop with
    `pre_created_crawl_id` set so it calls `steel_await_auth` first and
    waits for a human to complete the login in the Steel viewer.

    Returns `(manifest, awaiting_status)`: `awaiting_status` is the dict
    `precreate_auth_session` returned (carries `viewer_url`/`crawl_id`), or
    `None` if precreate failed or yielded nothing.

    Non-interactive cookie-injection into the Steel session (from
    `extra.auth_context` cookies, when present) is a deferred follow-up -
    see the crawl-pod auth-signal wiring in `crawl_pod.py` and the plan's
    Task 5 decision latitude. This MVP path only supports the human-in-the
    loop viewer flow.

    Best-effort: any exception (Steel unconfigured, tool/precreate/LLM
    failure, ...) yields `(empty manifest, None)` rather than propagating,
    mirroring `run_crawl`'s degrade-not-crash contract.
    """
    try:
        resolved_tools = tools
        if resolved_tools is None:
            resolved_tools = await steel_client.get_crawl_tools()
        mcp_manager = _ToolsManager(resolved_tools)

        body = AgenticCrawlRequest(
            target=target,
            scope=list(scope),
            model=model_role,
            max_depth=max_depth if max_depth is not None else config.CRAWL_MAX_DEPTH,
            max_pages=max_pages if max_pages is not None else config.CRAWL_MAX_PAGES,
            max_iterations=max_iters if max_iters is not None else config.CRAWL_MAX_ITERS,
            job_timeout_s=config.CRAWL_JOB_TIMEOUT_S,
            auth_required=True,
        )

        precreate = precreate_fn if precreate_fn is not None else precreate_auth_session
        crawl_id, awaiting_status = await precreate(mcp_manager, body)

        crawl_fn = _run_crawl_fn if _run_crawl_fn is not None else run_crawl
        manifest = await crawl_fn(
            target,
            scope=scope,
            model_role=model_role,
            tools=resolved_tools,
            llm=llm,
            max_pages=max_pages,
            max_depth=max_depth,
            max_iters=max_iters,
            pre_created_crawl_id=crawl_id,
        )
        return manifest, awaiting_status
    except Exception:  # noqa: BLE001 - best-effort, see module docstring
        return dict(_EMPTY_MANIFEST), None
