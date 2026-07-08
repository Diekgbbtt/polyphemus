"""Recon pod subgraph: configurator -> execute -> gate -> parser -> triager -> curator.

`build_pod_graph` takes the three side-effecting collaborators (exec_fn,
curate_fn, triage_fn) as parameters so callers can inject fakes in tests -
no live Kali/LLM/Neo4j is touched by the unit tests in tests/recon/test_pod.py.

`default_exec_fn` and `default_triage_fn` wire the real kali MCP client and
the triager LLM respectively, but they resolve their clients lazily on first
call (inside the function body). Importing this module must never perform
network I/O or require env vars to be set - `pod_graph` is built from the
defaults at import time, but building it only wires function references, it
does not invoke them.
"""
from __future__ import annotations

import inspect
import time

import os

from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field

from agent.recon.types import (
    PodState, ToolInvocation, PodExport, ExecResult, AssetDelta, Observation, JobSpec,
)
from agent.recon.parsers import get_parser
from agent.recon.parsers import graphql_parser, takeover_parser
from agent.recon.findings import finding_to_observation
from agent.recon.curator import curate
from agent.recon.config import MAX_POD_ITERS, EXEC_TIMEOUT_S

# Tools whose parser module exposes `parse_findings(stdout) -> list[dict]` -
# a deterministic, non-LLM source of Observations that the triager node
# merges alongside whatever the LLM triager (triage_fn) produces. Only two
# of the sixteen fleet tools have a findings parser today; every other job's
# triager behavior is unchanged (LLM-only).
_FINDINGS_MODULES = {
    "graphql-cop": graphql_parser,
    "subdomain_takeover": takeover_parser,
}


def _input_asset_url(input_asset: dict) -> str | None:
    """Best-effort extraction of the pod's target URL from its input asset
    (a BaseURL/Endpoint dict) - `url`, then `baseurl`, then `name`."""
    return (
        input_asset.get("url")
        or input_asset.get("baseurl")
        or input_asset.get("name")
    )


def _call_with_optional_target_url(fn, stdout: str, target_url: str | None):
    """Call `fn(stdout)`, passing `target_url=` too when `fn` declares that
    parameter (e.g. `graphql_parser.parse`/`parse_findings`). Other parser
    modules' `parse`/`parse_findings` (e.g. `takeover_parser`) don't accept
    `target_url` and are called unchanged - signature-aware so adding new
    findings-tools never requires touching this dispatch."""
    if "target_url" in inspect.signature(fn).parameters:
        return fn(stdout, target_url=target_url)
    return fn(stdout)


def fill_template(
    command_template: str,
    input_asset: dict,
    extra: dict,
    *,
    session_id: str = "",
    tool: str = "",
) -> str:
    """Deterministic placeholder fill for a job's command_template.

    - {target}: input_asset["name"] or ["url"] or ["address"], first present.
    - {domain}: input_asset["name"] or ["domain"], falling back to {target}.
    - {baseurl}: input_asset["url"] or ["baseurl"], falling back to {target}.
    - {session}: the pod's session_id (per-pod `/work/{session}` workdir key).
    - {auth_header}: empty unless extra["auth_context"] is present AND the
      caller has flagged extra["_use_auth"] truthy (the configurator node
      sets this from job.use_auth before calling fill_template); otherwise
      serialized to the tool-appropriate cookie flag via `_auth_header`.
    """
    extra = extra or {}
    target = input_asset.get("name") or input_asset.get("url") or input_asset.get("address") or ""
    domain = input_asset.get("name") or input_asset.get("domain") or target
    baseurl = input_asset.get("url") or input_asset.get("baseurl") or target
    auth_header = ""
    if extra.get("auth_context") and extra.get("_use_auth"):
        auth_header = _auth_header(extra["auth_context"], tool)

    result = command_template
    result = result.replace("{target}", str(target))
    result = result.replace("{domain}", str(domain))
    result = result.replace("{baseurl}", str(baseurl))
    result = result.replace("{session}", str(session_id))
    result = result.replace("{auth_header}", auth_header)
    return result


# Tools whose auth-cookie flag is `--headers "Cookie: ..."` rather than the
# `-H "Cookie: ..."` form shared by httpx/katana/ffuf (design §4 table).
_HEADERS_FLAG_TOOLS = {"arjun"}


def _auth_header(auth_context: dict, tool: str) -> str:
    """Serialize `auth_context["cookies"]` (`[{name, value}, ...]`) into the
    tool-appropriate cookie-header CLI flag - never a Python dict repr.

    Returns "" when there are no cookies (or `auth_context` is falsy), so a
    template's `{auth_header}` placeholder collapses to nothing rather than
    leaving a dangling flag/quote behind.
    """
    if not auth_context:
        return ""
    cookies = auth_context.get("cookies") or []
    cookie_str = "; ".join(
        f"{c['name']}={c['value']}" for c in cookies if c.get("name") and c.get("value")
    )
    if not cookie_str:
        return ""
    flag = "--headers" if tool in _HEADERS_FLAG_TOOLS else "-H"
    return f'{flag} "Cookie: {cookie_str}"'


def build_pod_graph(*, exec_fn, curate_fn, triage_fn):
    """Build the compiled recon-pod subgraph, injecting the three
    side-effecting collaborators: exec_fn(command, session_id, timeout_s) ->
    ExecResult, curate_fn(assets, observations, project_id) -> (int, int),
    triage_fn(exec_result, assets, job) -> list[Observation].
    """

    def configurator(state: PodState) -> dict:
        job = state["job"]
        extra = dict(state.get("extra") or {})
        extra["_use_auth"] = job.use_auth
        command = fill_template(
            job.command_template,
            state["input_asset"],
            extra,
            session_id=state["session_id"],
            tool=job.tool,
        )
        invocation = ToolInvocation(command=command, session_id=state["session_id"])
        iteration = state.get("iteration", 0) + 1
        return {"invocation": invocation, "iteration": iteration}

    def execute(state: PodState) -> dict:
        invocation = state["invocation"]
        exec_result = exec_fn(invocation.command, invocation.session_id, EXEC_TIMEOUT_S)
        return {"exec_result": exec_result}

    def gate(state: PodState) -> str:
        exec_result = state["exec_result"]
        # A clean exit (returncode 0) is a SUCCESSFUL run - even with empty
        # stdout, which just means the tool found nothing (subfinder with no
        # subdomains, jsluice on a page with no JS URLs, naabu with no open
        # ports). Route it through the parser (-> [] assets -> a "success"
        # export with 0 merges), NOT to "fail": an empty-but-clean run is a
        # valid zero-finding result, not a tool failure. Only a non-zero exit
        # is a failure (retried up to MAX_POD_ITERS, then failed).
        if exec_result.returncode == 0:
            return "parse"
        if state.get("iteration", 0) < MAX_POD_ITERS:
            return "configurator"
        return "fail"

    def parser(state: PodState) -> dict:
        job = state["job"]
        exec_result = state["exec_result"]
        parse_fn = get_parser(job.tool)
        target_url = _input_asset_url(state["input_asset"])
        assets = _call_with_optional_target_url(parse_fn, exec_result.stdout, target_url)
        return {"assets": assets}

    def triager(state: PodState) -> dict:
        job = state["job"]
        observations = list(
            triage_fn(state["exec_result"], state.get("assets", []), job)
        )

        parser_module = _FINDINGS_MODULES.get(job.tool)
        parse_findings_fn = getattr(parser_module, "parse_findings", None)
        if parse_findings_fn is not None:
            target_url = _input_asset_url(state["input_asset"])
            findings = _call_with_optional_target_url(
                parse_findings_fn, state["exec_result"].stdout, target_url
            )
            for finding in findings:
                observation = finding_to_observation(
                    finding, source_job=job.skill, source_tool=job.tool
                )
                if observation is not None:
                    observations.append(observation)

        return {"observations": observations}

    def curator_node(state: PodState) -> dict:
        assets = state.get("assets", [])
        observations = state.get("observations", [])
        assets_merged, observations_merged = curate_fn(assets, observations, state["project_id"])
        export = PodExport(
            input_asset=state["input_asset"],
            verdict="success",
            assets_merged=assets_merged,
            observations_merged=observations_merged,
            iterations=state.get("iteration", 0),
        )
        return {"export": export}

    def fail(state: PodState) -> dict:
        exec_result = state.get("exec_result")
        error = exec_result.stderr if exec_result is not None else "unknown error"
        export = PodExport(
            input_asset=state["input_asset"],
            verdict="failed",
            assets_merged=0,
            observations_merged=0,
            iterations=state.get("iteration", 0),
            error=error,
        )
        return {"export": export}

    g = StateGraph(PodState)
    g.add_node("configurator", configurator)
    g.add_node("execute", execute)
    g.add_node("parser", parser)
    g.add_node("triager", triager)
    g.add_node("curator", curator_node)
    g.add_node("fail", fail)

    g.add_edge(START, "configurator")
    g.add_edge("configurator", "execute")
    g.add_conditional_edges(
        "execute", gate, {"parse": "parser", "configurator": "configurator", "fail": "fail"}
    )
    g.add_edge("parser", "triager")
    g.add_edge("triager", "curator")
    g.add_edge("curator", END)
    g.add_edge("fail", END)

    return g.compile()


def _exec_result_from_artifact(artifact, *, content=None, duration_ms: int = 0) -> ExecResult:
    """Pure: turn an MCP tool-call artifact into an ExecResult.

    `langchain-mcp-adapters` registers `execute_command` with
    response_format="content_and_artifact": the structured
    {stdout, stderr, returncode, duration_ms} payload lives in the
    ToolMessage's `.artifact`, either as the raw dict directly or wrapped in
    an `MCPToolArtifact` TypedDict (i.e. a dict) under the
    "structured_content" key. If neither shape is present (artifact is None,
    or has no usable returncode), this is NOT success - it is a failure: we
    have no evidence the command exited 0, so we must not assume it did.
    """
    structured = artifact
    if isinstance(structured, dict) and "structured_content" in structured:
        structured = structured["structured_content"]
    else:
        structured = getattr(artifact, "structured_content", structured)

    if isinstance(structured, dict) and "returncode" in structured:
        return ExecResult(
            stdout=str(structured.get("stdout", "")),
            stderr=str(structured.get("stderr", "")),
            returncode=int(structured.get("returncode", 1)),
            duration_ms=int(structured.get("duration_ms", duration_ms)),
        )

    # No structured result: treat as FAILURE, never assume success.
    return ExecResult(
        stdout=str(content) if content else "",
        stderr="no structured result from execute_command",
        returncode=1,
        duration_ms=duration_ms,
    )


def default_exec_fn(command: str, session_id: str, timeout_s: int) -> ExecResult:
    """Real collaborator: run `command` via the kali MCP `execute_command`
    tool. Builds its MCP client lazily on each call - no client/connection is
    constructed at import time.
    """
    from langchain_mcp_adapters.client import MultiServerMCPClient
    from agent.app.config import config
    from agent.app.observability import get_langfuse_callbacks
    from agent.recon.async_bridge import run_coro_blocking

    # Trace the Kali MCP tool call + its response. This runs in a worker thread
    # (run_coro_blocking) where the graph's callback contextvar does not reach,
    # so pass the callbacks explicitly. Empty list (unconfigured) is inert.
    callbacks = get_langfuse_callbacks()

    async def _run():
        client = MultiServerMCPClient(
            {"kali": {"url": config.KALI_MCP_URL, "transport": "streamable_http"}}
        )
        tools = await client.get_tools()
        exec_tool = next(t for t in tools if t.name == "execute_command")
        # Invoke with a ToolCall (not a plain dict) so langchain-core returns
        # a ToolMessage carrying `.artifact` - a plain-dict invocation drops
        # the structured artifact and only returns the bare string content.
        return await exec_tool.ainvoke(
            {
                "type": "tool_call",
                "name": "execute_command",
                "id": session_id or "exec",
                "args": {"command": command, "session_id": session_id, "timeout_s": timeout_s},
            },
            config={"callbacks": callbacks},
        )

    start = time.monotonic()
    result = run_coro_blocking(_run())
    duration_ms = int((time.monotonic() - start) * 1000)

    artifact = getattr(result, "artifact", None)
    content = getattr(result, "content", None)
    return _exec_result_from_artifact(artifact, content=content, duration_ms=duration_ms)


class _ObservationBatch(BaseModel):
    observations: list[Observation] = Field(default_factory=list)


# Max parsed assets serialized into the triager prompt (see default_triage_fn).
_MAX_TRIAGE_ASSETS = int(os.environ.get("MAX_TRIAGE_ASSETS", "200"))


def default_triage_fn(exec_result: ExecResult, assets: list[AssetDelta], job: JobSpec) -> list[Observation]:
    """Real collaborator: ask the triager LLM to flag noteworthy observations
    from a completed tool run. Builds its chat model lazily on each call.
    """
    from agent.app.llm.roles import chat_model_for

    llm = chat_model_for("triager")
    # method="function_calling": the default "json_schema" strict-mode path
    # rejects Observation.anchor (an open-ended `dict` field with no
    # `additionalProperties: false`) on OpenAI/OpenRouter-family models -
    # confirmed live against openrouter:openai/gpt-4o-mini, which 400s with
    # "'additionalProperties' is required to be supplied and to be false"
    # under the default method. function_calling tolerates the loose schema.
    structured_llm = llm.with_structured_output(_ObservationBatch, method="function_calling")
    # Cap the assets serialized into the prompt: a high-volume tool (e.g.
    # subfinder on a large org can yield tens of thousands of Subdomain deltas)
    # would otherwise blow past the model's context window (observed: 41k assets
    # -> ~2M tokens -> 400), failing the triager AND, because the pod then fails
    # before the curator node, silently dropping every already-parsed asset. A
    # representative sample + the true total is enough to reason about.
    asset_dicts = [a.model_dump() for a in assets]
    shown = asset_dicts[:_MAX_TRIAGE_ASSETS]
    omitted = len(asset_dicts) - len(shown)
    assets_line = (
        f"Parsed assets ({len(asset_dicts)} total"
        + (f", showing first {len(shown)}, {omitted} omitted" if omitted else "")
        + f"): {shown}"
    )
    prompt = (
        f"Tool: {job.tool}\n"
        f"Command stdout:\n{exec_result.stdout[:4000]}\n"
        f"{assets_line}\n"
        "Identify any noteworthy security observations (macro_kind, severity, "
        "evidence, rationale, anchor {type, identity}, source_job, source_tool). "
        "Return an empty list if nothing notable."
    )
    result = structured_llm.invoke(prompt)
    return result.observations


pod_graph = build_pod_graph(exec_fn=default_exec_fn, curate_fn=curate, triage_fn=default_triage_fn)
