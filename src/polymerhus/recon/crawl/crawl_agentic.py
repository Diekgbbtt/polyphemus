"""
Agentic crawl loop — helper module used by api.py's /crawl/agentic endpoint.

Kept in a separate file so tests can import it without pulling in the full
FastAPI application (websockets, uvicorn, etc. not required here).

Notable design points (kept minimal + marked in-line with `D23`/`SP4`):
1. `_load_steel_crawl_skill`'s path resolves to `steel_crawl_skill.md` next to
   this module.
2. `AgenticCrawlRequest.credentials` (optional) + a credentialed-login prompt
   branch in `_run_agentic_crawl` (D23): when credentials are supplied and no
   human-interactive session is precreated, the agent is instructed to log in
   autonomously before crawling.
3. The T5 (#108) capability gate `_refuse_crawl_without_tool_calling` runs
   BEFORE `llm.bind_tools`: a model whose `supports_tool_calling` resolves
   `false`/`unknown` (T3 reader, ADR D5 Rule 1) refuses the tool-loop with a
   warn log and degrades to the empty manifest (no emulation - #99's work).
The lazy `from api import _build_llm_with_model_for_user` fallback in
`_run_agentic_crawl` is left in place verbatim - our adapter (`crawl_agent.py`)
always injects `build_llm_fn`, so that import never fires on our host.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from polymerhus.app.llm.capability import resolve_capability
from polymerhus.app.llm.providers import _ZEN_FAMILY, resolve_role

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

    Adapted (SP4-T3): points at `steel_crawl_skill.md` next to this module.
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


def _registered_lookup_key(provider: str, model: str) -> str:
    """Mirror of `capability.py:_registered_name` (the T2 registered-name
    convention, ADR D5): `<provider>/<model>` with the zen-family id stripped.
    The reader resolves a (provider, model) pair against exactly this key;
    the seam mirrors it only for the warn log's transparency."""
    if provider in _ZEN_FAMILY:
        model = model.rsplit("/", 1)[-1]
    return f"{provider}/{model}"


def _refuse_crawl_without_tool_calling(body: AgenticCrawlRequest) -> str | None:
    """T5 (#108): the crawl capability gate - runs BEFORE `llm.bind_tools`.

    Queries the T3 reader (`app.llm.capability.resolve_capability`, ADR D5
    Rule 1 provenance-gated) for the crawl model's `supports_tool_calling`
    and returns the REFUSAL reason when the model cannot call tools - or
    None when the tool-loop may run:

    - `true` -> None: the loop proceeds exactly as today (no behavior change).
    - `false` / `unknown` (None) -> refusal reason: the caller must NOT call
      `bind_tools` / run the tool-loop, and degrades fail-open to the empty
      manifest. This is the REFUSAL branch only - no silent emulation (that
      is #99's strategy-level work), no silent retry, no #73 axis involvement.
    - the reader raising `LLMConfigError` (a config-lie context-limit env)
      -> treated as unknown: warn + refuse, NEVER crash the caller.
    - unresolvable model identity (the role has no bound `model_key` env):
      the gate cannot classify and warns; it then proceeds as today. This
      branch is reachable only on the injected pre-built-client seam (the
      adapter's `llm is not None` path), where the caller vetted the client
      itself and the env-less identity would also have crashed
      `build_llm_fn` before the gate on the production path.

    Model identity at the seam, per the implementer prompt: the crawl does
    NOT carry a provider:model string - `body.model` is the ROLE id
    ("crawler"; the adapter resolves the client from the role,
    `chat_model_for`). The (provider, model) pair comes from
    `resolve_role(body.model)`, and the reader then applies the registered-
    name + zen-strip lookup convention internally (`capability.py:
    _registered_name`). Documented here because the seam has no direct
    provider:model surface of its own.
    """
    import logging  # noqa: PLC0415

    logger = logging.getLogger("crawl_agentic")

    try:
        provider, model = resolve_role(body.model)
    except Exception:  # noqa: BLE001 - the identity failure must never crash the caller
        logger.warning(
            "crawl capability gate cannot identify the model for role %r; "
            "proceeding without the gate (injected/pre-built client path)",
            body.model, exc_info=True)
        return None

    try:
        profile = resolve_capability(provider, model)
    except Exception as exc:  # noqa: BLE001 - fail-open: degrade, never crash
        logger.warning(
            "crawl capability gate could not resolve %s:%s (reader raised %s); "
            "treating as unknown - refusing the tool-loop",
            provider, model, exc)
        return f"{provider}:{model}"

    if profile.supports_tool_calling is True:
        return None
    state = "false" if profile.supports_tool_calling is False else "unknown"
    logger.warning(
        "crawl REFUSED the tool-loop: model=%s:%s registered_key=%s "
        "supports_tool_calling=%s capability_source=%s synced_at=%s; "
        "gap: add the model to the gateway registry or set a manual "
        "override (spec §5) - bind_tools not attempted, returning the "
        "empty manifest",
        provider, model, _registered_lookup_key(provider, model),
        state, profile.source, profile.synced_at)
    return f"{provider}:{model}"


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
    # `steel_await_auth` is the INTERACTIVE (human-in-the-viewer) login tool. It
    # is bound ONLY on the pre-created interactive path (which explicitly drives
    # it). Autonomous credentialed / anonymous crawls must NOT see it: with no
    # human at the viewer it just blocks the whole session until timeout, and
    # the D23 autonomous flow detects login success itself (an in-scope session
    # cookie on an in-scope non-login page - see the credentialed user message).
    # The tool + its predicates stay in steel_provider.py (parked, not deleted)
    # so the interactive path can be picked up again later.
    bound_names = set(CRAWL_TOOL_NAMES)
    if not pre_created_crawl_id:
        bound_names.discard("steel_await_auth")
    tools = [t for t in all_tools if getattr(t, "name", "") in bound_names]
    by_name = {t.name: t for t in tools}
    # T5 (#108): the capability gate - a model that cannot call tools (false
    # or unknown, provenance-gated per ADR D5 Rule 1) REFUSES the tool-loop:
    # bind_tools is never attempted and the crawl degrades fail-open to the
    # empty manifest (warn-refuse-degrade; never crashes the caller).
    if _refuse_crawl_without_tool_calling(body) is not None:
        return {"endpoints": [], "js_urls": []}
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
            f"2. Fill the login form with username={creds.get('username')!r} and password={creds.get('password')!r} "
            f"using steel_eval; {sel}.\n"
            f"3. steel_click the submit control EXACTLY ONCE. Do NOT resubmit on failure (account lockout).\n"
            f"4. Verify success: an in-scope session cookie appeared AND you are on an in-scope non-login "
            f"page. Genuine AUTH blocks - redirected off {body.scope} (SSO/OAuth), a second factor / "
            f"one-time code AFTER submit, or no login form - mean you are BLOCKED: do NOT loop, call "
            f"steel_crawl_finish with whatever is reachable and stop. A page-load / pre-submit CAPTCHA "
            f"or bot-detection interstitial or a 403 bot wall (IP/session-bound) is NOT a reason to "
            f"finish: follow the skill's rotation rule - abandon the session and call steel_crawl_start "
            f"for a FRESH one (new region, new IP), up to 3 fresh sessions, then re-attempt the login.\n"
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
