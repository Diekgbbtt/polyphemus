"""
Agentic crawl loop — helper module used by api.py's /crawl/agentic endpoint.

Kept in a separate file so tests can import it without pulling in the full
FastAPI application (websockets, uvicorn, etc. not required here).

Vendored verbatim from Redamon's `redamon-agent:/app/crawl_agentic.py` (SP4-T3
port source). Local adaptations (kept minimal + marked in-line with `D23`/`SP4`):
1. `_load_steel_crawl_skill`'s path resolves to `steel_crawl_skill.md` next to
   this module (our copy of Redamon's `skills/tooling/steel_crawl.md`) instead
   of Redamon's `skills/tooling/` layout.
2. `AgenticCrawlRequest.credentials` (optional) + a credentialed-login prompt
   branch in `_run_agentic_crawl` (D23): when credentials are supplied and no
   human-interactive session is precreated, the agent is instructed to log in
   autonomously before crawling.
The lazy `from api import _build_llm_with_model_for_user` fallback in
`_run_agentic_crawl` is left in place verbatim - our adapter (`crawl_agent.py`)
always injects `build_llm_fn`, so that import never fires on our host.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel

CRAWL_TOOL_NAMES = {
    "steel_crawl_start",
    "steel_navigate",
    "steel_frontier",
    "steel_crawl_finish",
    "steel_eval",
    "steel_click",
    "steel_await_auth",
}


class AgenticCrawlRequest(BaseModel):
    target: str
    scope: list[str]
    project_id: str = ""
    user_id: str = ""
    model: str
    max_depth: int = 3
    max_pages: int = 50
    max_iterations: int = 30
    navigate_wait_ms: int = 800
    job_timeout_s: int = 480
    proxy_escalation: bool = False
    auth_required: bool = False
    # D23 local adaptation: optional autonomous-login credentials. When set (and
    # no pre_created_crawl_id), _run_agentic_crawl emits a credentialed-login
    # prompt branch instructing the agent to log in before crawling.
    credentials: Optional[dict] = None


async def precreate_auth_session(mcp_manager, body) -> "tuple[str | None, dict | None]":
    """Pre-create a Steel crawl session when auth is required.

    Calls the ``steel_crawl_start`` MCP tool directly so the viewer URL and
    crawl_id are available *before* the ReAct loop runs.  The caller is
    responsible for storing the returned awaiting-status dict while the job
    is in flight, and for passing ``crawl_id`` to ``_run_agentic_crawl`` as
    ``pre_created_crawl_id``.

    Returns:
        (crawl_id, awaiting_status_dict)  — when auth_required and tool found
        (None, None)                      — when auth not required or tool missing
    """
    if not getattr(body, "auth_required", False):
        return None, None
    if mcp_manager is None:
        return None, None

    tools = await mcp_manager.get_tools()
    start = next(
        (t for t in tools if getattr(t, "name", "") == "steel_crawl_start"), None
    )
    if start is None:
        return None, None

    res = await start.ainvoke(
        {
            "target": body.target,
            "scope": body.scope,
            "user_id": body.user_id,
            "max_depth": body.max_depth,
            "max_pages": body.max_pages,
        }
    )
    # MCP tools return a content-block list, not a bare dict — normalize first.
    res = _payload_from_tool_result(res)
    crawl_id = res.get("crawl_id")
    awaiting_status: dict = {
        "status": "awaiting_auth",
        "viewer_url": res.get("viewer_url", ""),
        "crawl_id": crawl_id,
    }
    return crawl_id, awaiting_status


def _load_steel_crawl_skill() -> str:
    """Load the steel_crawl skill system prompt from disk.

    Adapted (SP4-T3): points at our vendored `steel_crawl_skill.md` copy next
    to this module, rather than Redamon's `skills/tooling/steel_crawl.md`
    layout.
    """
    skill_path = Path(__file__).parent / "steel_crawl_skill.md"
    return skill_path.read_text(encoding="utf-8")


def _payload_from_tool_result(out) -> dict:
    """Normalize an MCP tool result into a plain dict.

    langchain-mcp-adapters tools return their result as a list of content
    blocks (``[{"type": "text", "text": "<json>"}]``), not the raw dict the
    underlying tool returned.  They may also return a JSON string or, in tests,
    a bare dict.  This coerces all three shapes to a dict ({} if unparseable)
    so callers can reliably read ``error`` / ``endpoints`` / ``js_urls``.
    """
    import json as _json  # noqa: PLC0415

    if isinstance(out, dict):
        return out
    if isinstance(out, str):
        try:
            v = _json.loads(out)
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}
    if isinstance(out, (list, tuple)):
        for block in out:
            text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
            if isinstance(text, str):
                try:
                    v = _json.loads(text)
                    if isinstance(v, dict):
                        return v
                except Exception:
                    continue
    return {}


async def _run_agentic_crawl(
    body: AgenticCrawlRequest,
    mcp_manager,
    # Injected by api.py so this module stays import-light (no circular deps)
    build_llm_fn=None,
    pre_created_crawl_id=None,
) -> dict:
    """Run a bounded ReAct loop driving the Steel crawl MCP tools.

    Returns the manifest produced by steel_crawl_finish:
        {"endpoints": [...], "js_urls": [...]}
    """
    # Lazy import the real builder only when not overridden (e.g. in tests)
    if build_llm_fn is None:
        from api import _build_llm_with_model_for_user as build_llm_fn  # type: ignore

    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage  # noqa: PLC0415

    llm = build_llm_fn(body.model, body.user_id)
    all_tools = await mcp_manager.get_tools()
    tools = [t for t in all_tools if getattr(t, "name", "") in CRAWL_TOOL_NAMES]
    by_name = {t.name: t for t in tools}
    llm_t = llm.bind_tools(tools)

    sys_prompt = _load_steel_crawl_skill()
    creds = getattr(body, "credentials", None) or {}
    if pre_created_crawl_id:
        user = (
            f"target={body.target}\nscope={body.scope}\n"
            f"A Steel session is ALREADY STARTED for this crawl: crawl_id={pre_created_crawl_id}\n"
            f"A human operator is logging in manually right now. Do NOT call steel_crawl_start.\n"
            f"FIRST call steel_await_auth(crawl_id={pre_created_crawl_id!r}). When it returns "
            f"authenticated=true, crawl the now-authenticated routes; if it returns timed_out=true, "
            f"crawl whatever is reachable. Then steel_crawl_finish.\n"
            f"max_depth={body.max_depth} max_pages={body.max_pages} wait_ms={body.navigate_wait_ms}"
        )
    elif creds:
        # D23 local adaptation: autonomous credentialed login before crawling.
        sel = (
            f"username selector={creds.get('username_selector') or 'auto-detect the email/text login input'}; "
            f"password selector={creds.get('password_selector') or 'auto-detect input[type=password]'}; "
            f"submit={creds.get('submit_selector') or 'the login form submit control'}"
        )
        user = (
            f"target={body.target}\nscope={body.scope}\n"
            f"Begin by calling steel_crawl_start. You must AUTHENTICATE with these credentials BEFORE "
            f"crawling:\n"
            f"1. steel_navigate to login_url={creds.get('login_url')!r}.\n"
            f"2. Fill the login form with username={creds.get('username')!r} and the provided password "
            f"using steel_eval; {sel}.\n"
            f"3. steel_click the submit control EXACTLY ONCE. Do NOT resubmit on failure (account lockout).\n"
            f"4. Verify success: an in-scope session cookie appeared AND you are on an in-scope non-login "
            f"page. If instead you are redirected off {body.scope} (SSO/OAuth), see a second factor / "
            f"one-time code / captcha, or find no login form, you are BLOCKED: do NOT loop - call "
            f"steel_crawl_finish with whatever is reachable and stop.\n"
            f"5. Once authenticated, crawl the now-authenticated routes, then steel_crawl_finish.\n"
            f"max_depth={body.max_depth} max_pages={body.max_pages} wait_ms={body.navigate_wait_ms}"
        )
    else:
        user = (
            f"target={body.target}\nscope={body.scope}\n"
            f"max_depth={body.max_depth} max_pages={body.max_pages} "
            f"wait_ms={body.navigate_wait_ms} proxy_escalation={body.proxy_escalation}\n"
            f"Begin by calling steel_crawl_start."
        )
    messages = [SystemMessage(content=sys_prompt), HumanMessage(content=user)]
    last_manifest: dict = {"endpoints": [], "js_urls": []}

    import logging  # noqa: PLC0415
    import time as _time  # noqa: PLC0415
    logger = logging.getLogger("crawl_agentic")

    # Soft deadline: stop reasoning early enough to still drain the captured
    # network surface before the hard job_timeout cancels the task. Each Steel
    # navigation can take ~20s, so reserve a margin for one navigate + finish.
    crawl_id = None
    finished = False
    finish_margin_s = 35
    soft_deadline = _time.time() + max(body.job_timeout_s - finish_margin_s, 1)

    for _ in range(body.max_iterations):
        if _time.time() >= soft_deadline:
            logger.warning("crawl soft time budget reached; draining partial manifest")
            break
        ai = await llm_t.ainvoke(messages)
        messages.append(ai)
        tool_calls = getattr(ai, "tool_calls", None) or []
        if not tool_calls:
            break
        for tc in tool_calls:
            tool = by_name.get(tc["name"])
            if tool is None:
                messages.append(
                    ToolMessage(content="unknown tool", tool_call_id=tc["id"])
                )
                continue
            args = dict(tc["args"] or {})
            if tc["name"] == "steel_crawl_start":
                args["user_id"] = body.user_id
            out = await tool.ainvoke(args)
            payload = _payload_from_tool_result(out)
            # A failed session start is a hard, non-recoverable failure (e.g. a
            # missing Steel API key): the crawl can never produce results, so
            # surface it as a job error instead of silently returning an empty
            # manifest that looks like a successful "found nothing" crawl.
            if tc["name"] == "steel_crawl_start":
                if payload.get("error") and not payload.get("crawl_id"):
                    raise RuntimeError(f"steel_crawl_start failed: {payload['error']}")
                crawl_id = payload.get("crawl_id") or crawl_id
            if tc["name"] == "steel_crawl_finish":
                finished = True
                last_manifest = {
                    "endpoints": payload.get("endpoints", []),
                    "js_urls": payload.get("js_urls", []),
                }
            messages.append(ToolMessage(content=str(out), tool_call_id=tc["id"]))
        if last_manifest["endpoints"] or last_manifest["js_urls"]:
            break

    # If the loop ended (iteration cap, soft deadline, or empty frontier) without
    # the LLM ever finishing, drain whatever the harness captured so a long crawl
    # is never thrown away. The MCP server owns the accumulator keyed by crawl_id.
    if not finished and crawl_id is not None:
        finish_tool = by_name.get("steel_crawl_finish")
        if finish_tool is not None:
            try:
                payload = _payload_from_tool_result(await finish_tool.ainvoke({"crawl_id": crawl_id}))
                if payload.get("endpoints") or payload.get("js_urls"):
                    last_manifest = {
                        "endpoints": payload.get("endpoints", []),
                        "js_urls": payload.get("js_urls", []),
                    }
            except Exception as e:  # noqa: BLE001
                logger.warning("partial-manifest drain failed: %r", e)

    return last_manifest
