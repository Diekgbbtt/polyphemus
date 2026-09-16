"""App-side SYNC client for the kali HTTP-history tools (#196).

The hunter tools invoke their seams synchronously, so every callable here
bridges to the async MCP client with `run_coro_blocking` - the same pattern
`recon.domain.pod.default_exec_fn` uses for `execute_command`.
"""
from __future__ import annotations

import json
from typing import Any


def structured_payload(result: Any) -> dict:
    """Pure: the tool result carries its dict bare, under `structured_content`,
    or as the JSON text of an MCP content block. Anything else is an error,
    never a silent success."""
    structured: Any = result
    if isinstance(structured, dict) and "structured_content" in structured:
        structured = structured["structured_content"]
    elif isinstance(structured, (list, tuple)):
        # The MCP adapter returns `[{"type": "text", "text": "<json>"}]` for a
        # tool whose FastMCP function returns a dict (verified against the live
        # kali server, 2026-09-16).
        structured = _first_json_dict(structured)
    else:
        structured = getattr(structured, "structured_content", None) or structured
    if isinstance(structured, dict):
        return structured
    return {"error": "unstructured_response", "detail": str(result)[:400]}


def _first_json_dict(blocks) -> dict | None:
    """The first content block whose `text` decodes to a JSON object."""
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            try:
                parsed = json.loads(str(block.get("text") or ""))
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def _call_tool(name: str, args: dict) -> dict:
    from langchain_mcp_adapters.client import MultiServerMCPClient  # noqa: PLC0415
    from langchain_mcp_adapters.tools import load_mcp_tools  # noqa: PLC0415

    from polymerhus.app.config import config  # noqa: PLC0415
    from polymerhus.recon.control.async_bridge import run_coro_blocking  # noqa: PLC0415

    async def _run():
        client = MultiServerMCPClient(
            {"kali": {"url": config.KALI_MCP_URL, "transport": "streamable_http"}}
        )
        tools = await client.get_tools()
        tool = next(tool for tool in tools if tool.name == name)
        return await tool.ainvoke(args)

    try:
        return structured_payload(run_coro_blocking(_run()))
    except Exception as exc:  # noqa: BLE001 - fail-open, never into the turn
        return {"error": "http_history_failed",
                "detail": f"{type(exc).__name__}: {exc}"}


def default_http_search_fn(project_id, filters, cursor, limit, text) -> dict:
    return _call_tool("search_http_history", {
        "project_id": project_id, "filters": filters or [], "cursor": cursor,
        "limit": limit, "text": text,
    })


def default_http_get_fn(project_id, artifact_id, include_body=False) -> dict:
    return _call_tool("get_http_artifact", {
        "project_id": project_id, "artifact_id": artifact_id,
    })


def default_replay_fn(project_id, artifact_id, overrides) -> dict:
    """The pod's replay seam: read the baseline status, or replay with the
    overrides and read the new artifact's status back."""
    if not overrides:
        view = _call_tool("get_http_artifact", {
            "project_id": project_id, "artifact_id": artifact_id})
        return {"status": (view.get("response") or {}).get("status")}
    result = _call_tool("replay_http_request", {
        "project_id": project_id, "artifact_id": artifact_id, "overrides": overrides,
    })
    if result.get("error"):
        return {"status": None, "error": result}
    view = _call_tool("get_http_artifact", {
        "project_id": project_id, "artifact_id": result.get("artifact_id")})
    return {"status": (view.get("response") or {}).get("status"),
            "artifact_id": result.get("artifact_id")}
