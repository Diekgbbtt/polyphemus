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
import shlex
import time

import os

from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field

from polymerhus.recon.domain.types import (
    PodState, ToolInvocation, PodExport, ExecResult, AssetDelta, Observation, JobSpec,
)
from polymerhus.recon.domain.parsers import get_parser
from polymerhus.recon.domain.parsers import graphql_parser, takeover_parser
from polymerhus.recon.domain.findings import finding_to_observation
from polymerhus.recon.domain.curator import curate
from polymerhus.recon.config import MAX_POD_ITERS, EXEC_TIMEOUT_S

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
    - {auth_header}: empty unless extra["auth_context"] is present, in which
      case it is serialized to the tool-appropriate cookie flag via
      `_auth_header`. Auth-eligibility is decided ONCE, upstream: the pipeline
      (`run_pipeline`) injects `auth_context` into `extra` only for `use_auth`
      jobs, so a non-auth job never carries it and this gate needs no second
      `use_auth` check (C1 single-owner consolidation).
    """
    extra = extra or {}
    target = input_asset.get("name") or input_asset.get("url") or input_asset.get("address") or ""
    domain = input_asset.get("name") or input_asset.get("domain") or target
    baseurl = input_asset.get("url") or input_asset.get("baseurl") or target
    auth_header = ""
    if extra.get("auth_context"):
        auth_header = _auth_header(extra["auth_context"], tool)
    rate_flags = _RATE_FLAGS.get(tool, "") if (extra.get("rate_profile") == "throttle") else ""

    result = command_template
    result = result.replace("{target}", str(target))
    result = result.replace("{domain}", str(domain))
    result = result.replace("{baseurl}", str(baseurl))
    result = result.replace("{session}", str(session_id))
    result = result.replace("{auth_header}", auth_header)
    result = result.replace("{rate_flags}", rate_flags)
    return result


# Tools whose auth-cookie flag is `--headers "Cookie: ..."` rather than the
# `-H "Cookie: ..."` form shared by httpx/katana/ffuf/kiterunner (design §4 table).
_HEADERS_FLAG_TOOLS = {"arjun"}

# graphql-cop's own --headers format: ALL headers in one comma-joined
# "Key:Value,Key2:Value2" argument (no space after the colon) - distinct from
# both the default repeated -H flag and arjun's newline-joined --headers blob.
_COMMA_HEADERS_FLAG_TOOLS = {"graphql-cop"}

# Conservative preventive rate profile, applied ONLY when the job-agent steering
# marked this pod extra["rate_profile"] == "throttle". Only ffuf currently carries
# the {rate_flags} slot: it consumes BaseURL, so a WAF-flagged host actually
# reaches decide_pod_selection and can be throttled. httpx consumes Subdomain and
# runs in the detection phase BEFORE any WAF signal exists, so it can never be
# reactively throttled - its {rate_flags} slot was a dead no-op and was removed.
# katana already carries -rl/-c and is handled by routing, so it is absent too.
_RATE_FLAGS = {"ffuf": "-rate 5 -p 0.2"}


# auth_context is header-agnostic: `cookies` is the structured source of the
# `Cookie` header, and every OTHER key (except these reserved structural ones,
# which are not HTTP headers) is emitted verbatim as its own request header.
# The role/realm structural keys (`roles`, `default_role`, `realm`; FR-AUTH) are
# reserved too, so even if a caller hands a set that still carries them they can
# never leak out as HTTP headers (defence in depth - the selector already strips
# roles/default_role; `realm` is a role's own metadata tag).
_RESERVED_AUTH_KEYS = {"cookies", "scope", "credentials", "roles", "default_role", "realm"}


def _iter_auth_headers(auth_context: dict):
    """Yield `(name, value)` HTTP header pairs from `auth_context`.

    - `cookies` (`[{name, value}, ...]`) is joined into the peculiar pair-form
      `Cookie` header value (`k=v; k2=v2`) - the Cookie header wants key=value
      pairs, not one opaque token.
    - every other key except the reserved structural keys (`scope`,
      `credentials`) is an arbitrary header (Authorization, X-Api-Key, ...),
      yielded verbatim. A literal `Cookie` key is skipped (the API layer
      rejects it; the `cookies` list is the one source of the Cookie header).
    """
    cookies = auth_context.get("cookies") or []
    cookie_str = "; ".join(
        f"{c['name']}={c['value']}" for c in cookies if c.get("name") and c.get("value")
    )
    if cookie_str:
        yield ("Cookie", cookie_str)
    for name, value in auth_context.items():
        if name in _RESERVED_AUTH_KEYS or name.lower() == "cookie":
            continue
        if isinstance(value, str) and value:
            yield (name, value)


def _auth_header(auth_context: dict, tool: str) -> str:
    """Serialize `auth_context` into tool-appropriate header CLI flags.

    Header-agnostic: the `cookies` list becomes the `Cookie` header and any
    other key (except the reserved `scope`/`credentials`) becomes its own
    header. Every `name: value` is shell-quoted (`shlex`) so an operator-
    supplied token can never break the command string.

    `-H`-flag tools take one repeatable flag per header; arjun's `--headers`
    takes all headers in a single newline-separated argument; graphql-cop's
    `--headers` takes all headers in a single comma-joined `Key:Value` argument
    (no space after the colon). Returns "" when nothing applies, so a
    template's `{auth_header}` placeholder collapses to nothing rather than
    leaving a dangling flag behind. Request-tool only - the Steel crawl injects
    cookies via CDP separately.
    """
    if not auth_context:
        return ""
    pairs = list(_iter_auth_headers(auth_context))
    if not pairs:
        return ""
    if tool in _HEADERS_FLAG_TOOLS:
        blob = "\n".join(f"{name}: {value}" for name, value in pairs)
        return f"--headers {shlex.quote(blob)}"
    if tool in _COMMA_HEADERS_FLAG_TOOLS:
        blob = ",".join(f"{name}:{value}" for name, value in pairs)
        return f"--headers {shlex.quote(blob)}"
    return " ".join(f"-H {shlex.quote(f'{name}: {value}')}" for name, value in pairs)


def build_pod_graph(*, exec_fn, curate_fn, triage_fn):
    """Build the compiled recon-pod subgraph, injecting the three
    side-effecting collaborators: exec_fn(command, session_id, timeout_s) ->
    ExecResult, curate_fn(assets, observations, project_id) -> (int, int),
    triage_fn(exec_result, assets, job) -> list[Observation].
    """

    def configurator(state: PodState) -> dict:
        job = state["job"]
        extra = dict(state.get("extra") or {})
        input_asset = state["input_asset"]
        if job.batch and "batch" in input_asset:
            # Batched job (jsluice, D17/Q6): the pod runs one command over a
            # list of bundle URLs, not a single-asset template fill.
            from polymerhus.recon.control.batching import build_batch_command

            command = build_batch_command(job, input_asset["batch"])
        else:
            command = fill_template(
                job.command_template,
                input_asset,
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
        # The seed scope domain (D14) and the exact-mode seed_domain (D28) ride
        # in `extra` alongside project_id; forward them so curate drops
        # out-of-scope BaseURLs and models the seed host as a Domain. Passed
        # only when present so injected 3-arg fake curate_fns stay compatible.
        extra = state.get("extra") or {}
        curate_kwargs = {}
        if extra.get("scope_domain"):
            curate_kwargs["scope_domain"] = extra["scope_domain"]
        if extra.get("seed_domain"):
            curate_kwargs["seed_domain"] = extra["seed_domain"]
        assets_merged, observations_merged = curate_fn(
            assets, observations, state["project_id"], **curate_kwargs
        )
        invocation = state.get("invocation")
        export = PodExport(
            input_asset=state["input_asset"],
            verdict="success",
            assets_merged=assets_merged,
            observations_merged=observations_merged,
            iterations=state.get("iteration", 0),
            stats={"command": invocation.command} if invocation is not None else None,
        )
        return {"export": export}

    def fail(state: PodState) -> dict:
        exec_result = state.get("exec_result")
        error = exec_result.stderr if exec_result is not None else "unknown error"
        invocation = state.get("invocation")
        export = PodExport(
            input_asset=state["input_asset"],
            verdict="failed",
            assets_merged=0,
            observations_merged=0,
            iterations=state.get("iteration", 0),
            error=error,
            stats={"command": invocation.command} if invocation is not None else None,
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
    from polymerhus.app.config import config
    from polymerhus.app.observability import get_langfuse_callbacks
    from polymerhus.recon.control.async_bridge import run_coro_blocking

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

def _load_triager_skill() -> str:
    """The triager system prompt = the writing-observations skill, loaded via the
    shared `skill_for` (FR-SKILLIF): single-sourced from
    skills/recon/triager/writing-observations/SKILL.md, frontmatter stripped,
    cached, and degraded to '' (no system prompt) if the mount is unavailable."""
    from polymerhus.recon.domain.skills import skill_for
    return skill_for("recon/triager/writing-observations")


def default_triage_fn(exec_result: ExecResult, assets: list[AssetDelta], job: JobSpec) -> list[Observation]:
    """Real collaborator: ask the triager LLM to flag noteworthy observations
    from a completed tool run. Builds its chat model lazily on each call.
    """
    from polymerhus.app.llm.roles import chat_model_for

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
    from langchain_core.messages import SystemMessage, HumanMessage
    skill = _load_triager_skill()
    messages = ([SystemMessage(content=skill)] if skill else []) + [HumanMessage(content=prompt)]
    result = structured_llm.invoke(messages)
    return result.observations


pod_graph = build_pod_graph(exec_fn=default_exec_fn, curate_fn=curate, triage_fn=default_triage_fn)
