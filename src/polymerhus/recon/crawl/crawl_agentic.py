"""
Agentic crawl loop — helper module used by api.py's /crawl/agentic endpoint.

Kept in a separate file so tests can import it without pulling in the full
FastAPI application (websockets, uvicorn, etc. not required here).

Notable design points (kept minimal + marked in-line with `D23`/`SP4`):
1. `_load_steel_crawl_skill` reads the steel-crawl role prompt directly from
   this module's `prompts/` dir, memoized on first call, fail-closed.
2. The crawl runs profile-mount only (#223 T4 #243): the loop starts its own
   session and crawls what the seeded browser context reaches - the
   persisted session cookies the provider seeds before the crawl. The
   retired interactive `steel_await_auth` human-in-the-viewer path and the
   autonomous credentialed-login branch are gone with their prompts.
3. The T5 (#108) capability gate `_refuse_crawl_without_tool_calling` runs
   BEFORE `llm.bind_tools`: a model whose `supports_tool_calling` resolves
   `false`/`unknown` (T3 reader, ADR D5 Rule 1) refuses the tool-loop with a
   warn log and degrades to the empty manifest (no emulation - #99's work).
The lazy `from api import _build_llm_with_model_for_user` fallback in
`_run_agentic_crawl` is left in place verbatim - our adapter (`crawl_agent.py`)
always injects `build_llm_fn`, so that import never fires on our host.
"""
from __future__ import annotations

from pydantic import BaseModel

from polymerhus.app.llm.capability import resolve_capability
from polymerhus.app.llm.providers import resolve_role

CRAWL_TOOL_NAMES = {
    "steel_crawl_start",
    "steel_navigate",
    "steel_frontier",
    "steel_crawl_finish",
    "steel_eval",
    "steel_click",
}


def derive_crawl_pacing(
    policy: dict | None, *, max_pages: int, max_iterations: int, navigate_wait_ms: int
) -> dict:
    """Conservatively adapt a browser crawl to a measured `TrafficPolicy` (#238).

    The Steel crawl cannot expose its sub-requests to the egress governor: one
    browser session fans out into connections the run never sees. So the policy
    is expressed the only way a browser CAN honour it - as an inter-action
    cadence plus HARDER page/iteration caps - and never as a claim that the
    sub-requests are individually governed.

    The derivation is monotone and conservative:

    * `min_delay_ms` is the policy's own cadence (or `1000 / rate_per_s` when
      the policy names only a rate), never faster than the operator's existing
      `navigate_wait_ms` - a policy that would allow a faster crawl leaves the
      crawl exactly as it was;
    * the page and iteration caps are reduced by the SAME factor the pacing
      slowed (`existing_delay / effective_delay`), so an equal-length session
      covers what the slower cadence can actually reach. They are NEVER
      increased: a permissive policy cannot enlarge the operator's budget;
    * `max_concurrent_crawls` is always 1 - one crawl session per target.

    A missing or malformed policy leaves the operator defaults untouched.
    Pure: no clock, no I/O.
    """
    existing_pages = max(1, int(max_pages))
    existing_iters = max(1, int(max_iterations))
    pacing = {
        "max_pages": existing_pages,
        "max_iterations": existing_iters,
        "min_delay_ms": 0,
        "max_concurrent_crawls": 1,
    }
    if not isinstance(policy, dict):
        return pacing
    delay_ms = policy.get("min_delay_ms")
    try:
        delay_ms = float(delay_ms) if delay_ms is not None else 0.0
    except (TypeError, ValueError):
        delay_ms = 0.0
    if delay_ms <= 0:
        rate = policy.get("rate_per_s")
        if isinstance(rate, (int, float)) and not isinstance(rate, bool) and rate > 0:
            delay_ms = 1000.0 / float(rate)
    try:
        nominal_ms = max(0.0, float(navigate_wait_ms or 0))
    except (TypeError, ValueError):
        nominal_ms = 0.0
    effective_ms = max(nominal_ms, delay_ms)
    pacing["min_delay_ms"] = int(round(effective_ms))
    if nominal_ms > 0 and effective_ms > nominal_ms:
        scale = nominal_ms / effective_ms
        pacing["max_pages"] = max(1, int(existing_pages * scale))
        pacing["max_iterations"] = max(1, int(existing_iters * scale))
    return pacing


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


# The steel-crawl role prompt, memoized on first call (no import-time I/O,
# CODING STANDARD section 6). A missing prompt file is a defect: fail-closed.
_STEEL_CRAWL_SKILL: str | None = None


def _load_steel_crawl_skill() -> str:
    """Load the steel_crawl skill system prompt directly from this module's
    `prompts/` dir. Memoized on first call; FAIL-CLOSED - a missing prompt
    file raises instead of degrading to an empty manifest, so the crawl never
    runs without its budget/frontier discipline.
    """
    global _STEEL_CRAWL_SKILL
    if _STEEL_CRAWL_SKILL is None:
        from pathlib import Path  # noqa: PLC0415 - lazy, mirrors the reader convention

        _STEEL_CRAWL_SKILL = (
            Path(__file__).resolve().parent / "prompts" / "steel-crawl.md"
        ).read_text(encoding="utf-8")
    return _STEEL_CRAWL_SKILL


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
    """Mirror of `sync_mapping.registered_model_name` (the T2 registered-name
    convention, ADR D5): `<provider>/<id>` with the zen-family (bare-catalog
    aggregator) id stripped. The reader resolves a (provider, model) pair
    against exactly this key; the seam mirrors it only for the warn log's
    transparency."""
    from polymerhus.app.llm.sync_mapping import registered_model_name
    return registered_model_name(provider, model)


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
    pacing: dict | None = None,
    sleeper=None,
    clock=None,
) -> dict:
    """Run a bounded ReAct loop driving the Steel crawl MCP tools.

    Returns the manifest produced by steel_crawl_finish:
        {"endpoints": [...], "js_urls": [...]}

    `pacing` (#238) is the conservative adaptation the caller derived from the
    run's `TrafficPolicy` (`derive_crawl_pacing`): it lowers the page/iteration
    caps and inserts `min_delay_ms` between MODEL-ISSUED browser actions, using
    the injected `sleeper` / `clock` seams. It never claims the browser's
    sub-requests are individually governed - only the agent's own actions are
    paced, and only the caps the operator already set can be reduced.
    """
    # Lazy import the real builder only when not overridden (e.g. in tests)
    if build_llm_fn is None:
        from api import _build_llm_with_model_for_user as build_llm_fn  # type: ignore

    from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage  # noqa: PLC0415

    llm = build_llm_fn(body.model, body.user_id)
    all_tools = await mcp_manager.get_tools()
    tools = [t for t in all_tools if getattr(t, "name", "") in CRAWL_TOOL_NAMES]
    by_name = {t.name: t for t in tools}
    # #238 pacing is resolved BEFORE the prompt is rendered, so the model is
    # told the caps it will actually be held to (a policy only ever reduces).
    pacing = pacing if isinstance(pacing, dict) else {}
    action_delay_s = max(0.0, float(pacing.get("min_delay_ms") or 0)) / 1000.0
    max_iterations = int(pacing.get("max_iterations") or body.max_iterations)
    paced_max_pages = int(pacing.get("max_pages") or body.max_pages)
    # T5 (#108): the capability gate - a model that cannot call tools (false
    # or unknown, provenance-gated per ADR D5 Rule 1) REFUSES the tool-loop:
    # bind_tools is never attempted and the crawl degrades fail-open to the
    # empty manifest (warn-refuse-degrade; never crashes the caller).
    if _refuse_crawl_without_tool_calling(body) is not None:
        return {"endpoints": [], "js_urls": []}
    llm_t = llm.bind_tools(tools)

    sys_prompt = _load_steel_crawl_skill()
    user = (
        f"target={body.target}\nscope={body.scope}\n"
        f"max_depth={body.max_depth} max_pages={paced_max_pages} "
        f"wait_ms={body.navigate_wait_ms} proxy_escalation={body.proxy_escalation}\n"
        f"Begin by calling steel_crawl_start."
    )
    messages = [SystemMessage(content=sys_prompt), HumanMessage(content=user)]
    last_manifest: dict = {"endpoints": [], "js_urls": []}

    import logging  # noqa: PLC0415
    import time as _time  # noqa: PLC0415
    logger = logging.getLogger("crawl_agentic")

    if sleeper is None:
        sleeper = _time.sleep
    if clock is None:
        clock = _time.monotonic

    # Soft deadline: stop reasoning early enough to still drain the captured
    # network surface before the hard job_timeout cancels the task. Each Steel
    # navigation can take ~20s, so reserve a margin for one navigate + finish.
    crawl_id = None
    finished = False
    finish_margin_s = 35
    soft_deadline = _time.time() + max(body.job_timeout_s - finish_margin_s, 1)

    last_action_at = None
    for _ in range(max_iterations):
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
            # #238: min_delay_ms between MODEL-ISSUED browser actions. Only the
            # agent's own actions are paced - the browser's sub-requests are
            # NOT individually governed (spec, traffic enforcement).
            if last_action_at is not None and action_delay_s > 0:
                remaining = action_delay_s - (clock() - last_action_at)
                if remaining > 0:
                    sleeper(remaining)
            last_action_at = clock()
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
