"""Thin adapter around `crawl_agentic._run_agentic_crawl`'s ReAct loop.

This module does NOT reimplement the crawl loop - it wraps `crawl_agentic.py`
(see its module docstring). This adapter only:

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

from typing import Optional

from polymerhus.recon import config
from polymerhus.recon.crawl import steel_client
from polymerhus.recon.crawl.crawl_agentic import (
    AgenticCrawlRequest,
    CRAWL_TOOL_NAMES,
    _run_agentic_crawl,
)

__all__ = [
    "AgenticCrawlRequest",
    "CRAWL_TOOL_NAMES",
    "run_crawl",
]

_EMPTY_MANIFEST = {"endpoints": [], "js_urls": []}


# The steel-crawl role prompt, memoized on first call (no import-time I/O,
# CODING STANDARD section 6). A missing prompt file is a defect: fail-closed.
_STEEL_CRAWL_SKILL: str | None = None


def _load_skill() -> str:
    """The steel_crawl skill prompt, read directly from this module's `prompts/`
    dir. Memoized on first call; FAIL-CLOSED - a missing prompt file raises."""
    global _STEEL_CRAWL_SKILL
    if _STEEL_CRAWL_SKILL is None:
        from pathlib import Path  # noqa: PLC0415

        _STEEL_CRAWL_SKILL = (
            Path(__file__).resolve().parent / "prompts" / "steel-crawl.md"
        ).read_text(encoding="utf-8")
    return _STEEL_CRAWL_SKILL


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
    auth_cookies: Optional[list] = None,
) -> dict:
    """Run the bounded agentic-crawl ReAct loop and return its manifest.

    `auth_cookies` (the feed-projected persisted session cookies, resolved
    from the store through the bound account identifier) is forwarded to
    `steel_client.get_crawl_tools` when the tools are built here, so the
    default Steel provider seeds the browser context with them before the
    crawl (profile-mount-only auth). Ignored when `tools` are injected
    (tests build the provider themselves).

    Best-effort: any exception (Steel unconfigured, tool/LLM failure, ...)
    yields the empty manifest rather than propagating, so callers (the crawl
    pod) can treat a failed crawl as reduced coverage instead of a crash.
    """
    try:
        resolved_tools = tools
        if resolved_tools is None:
            resolved_tools = await steel_client.get_crawl_tools(auth_cookies=auth_cookies)
        mcp_manager = _ToolsManager(resolved_tools)

        if llm is not None:
            def build_llm_fn(model, user_id, _llm=llm):
                return _llm
        else:
            from polymerhus.app.llm.roles import chat_model_for

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
        )

        return await _run_agentic_crawl(
            body,
            mcp_manager,
            build_llm_fn=build_llm_fn,
        )
    except Exception:  # noqa: BLE001 - best-effort, see module docstring
        return dict(_EMPTY_MANIFEST)
