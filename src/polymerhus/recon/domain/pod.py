"""Recon pod subgraph: configurator -> execute -> gate -> parser -> triager -> curator.

`build_pod_graph` takes the side-effecting collaborators (exec_fn, curate_fn,
triage_fn) as parameters so callers can inject
fakes in tests - no live Kali/LLM/Neo4j is touched by the unit tests in
tests/recon/test_pod.py.

`default_exec_fn` and `default_triage_fn` wire the real
kali MCP client and the triager LLM respectively, but they
resolve their clients lazily on first call (inside the function body).
Importing this module must never perform network I/O or require env vars to be
set - `pod_graph` is built from the defaults at import time, but building it
only wires function references, it does not invoke them.
"""
from __future__ import annotations

import inspect
import logging
import shlex
import time

import os

from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field, model_validator

from polymerhus.recon.domain.types import (
    PodState, ToolInvocation, PodExport, ExecResult, AssetDelta, Observation, JobSpec,
)
from polymerhus.recon.control.auth_feed import serialize_auth_flags
from polymerhus.recon.domain.parsers import get_parser
from polymerhus.recon.domain.parsers import graphql_parser, takeover_parser
from polymerhus.recon.domain.findings import finding_to_observation
from polymerhus.recon.domain.curator import curate
from polymerhus.recon.config import MAX_POD_ITERS, EXEC_TIMEOUT_S

# The per-pod session context for the triager's STATEFUL turn (#94): (thread_id,
# checkpointer). The triager NODE (which alone knows the concurrent pod instance) sets
# it right before calling `triage_fn` (a typed `SessionContext`: address + checkpointer),
# and the live `default_triage_fn` reads it to run on the pod's own session thread.
# Passing it out-of-band through a ContextVar keeps the injected
# `triage_fn(exec_result, assets, job)` contract UNTOUCHED (25+ test fakes stay valid); a
# fake simply ignores it. Set+read within one synchronous node execution, so concurrent
# pods (each in its own worker thread) never see each other's context. `None` => stateless
# (tests, or a pod whose state carries no run_id).
_pod_session_ctx: "ContextVar" = None  # lazily created below to keep imports light


def _pod_ctx():
    """The module ContextVar, created on first use (import stays free of contextvars)."""
    global _pod_session_ctx
    if _pod_session_ctx is None:
        from contextvars import ContextVar
        _pod_session_ctx = ContextVar("pod_session_ctx", default=None)
    return _pod_session_ctx


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


def _pod_asset_discriminator(input_asset: dict) -> str:
    """The stable token that distinguishes ONE concurrent pod instance (#94): the input
    asset's url when present, else a stable hash of the whole asset (the operator-chosen
    `url (+ hash fallback)` scheme). Recon owns HOW a pod is discriminated; the generic
    `PodSession` (app/llm) only holds the resolved token."""
    disc = _input_asset_url(input_asset)
    if disc:
        return disc
    import hashlib
    import json

    return "h" + hashlib.sha1(
        json.dumps(input_asset, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


def pod_session(run_id: str, phase, job, input_asset: dict, *, role_id: str):
    """The typed per-pod session ADDRESS for a recon pod's stateful agents (the triager).
    Up to MAX_PODS pods run the same role CONCURRENTLY (the job-agent `Send` fan-out), so
    keying by `(run, role)` alone would collide; `PodSession` discriminates by the pod's
    phase, tool, and resolved input-asset token, so each concurrent pod has its own
    checkpoint thread."""
    from polymerhus.app.llm.session_address import PodSession

    return PodSession(run_id, phase, getattr(job, "tool", ""),
                      _pod_asset_discriminator(input_asset), role_id)


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
    endpoints: list[str] | None = None,
) -> str:
    """Deterministic placeholder fill for a job's command_template.

    - {target}: input_asset["name"] or ["url"] or ["address"], first present.
    - {domain}: input_asset["name"] or ["domain"], falling back to {target}.
    - {baseurl}: input_asset["url"] or ["baseurl"], falling back to {target}.
    - {session}: the pod's session_id (per-pod `/work/{session}` workdir key).
    - {endpoints} (#208): the reprofile pod's full endpoint list, shell-quoted
      and space-joined, so ONE httpx exec can be fed the whole probe set via a
      `printf ... > file && httpx -l file` command. Empty when not provided.
    - {auth_flags}: empty unless extra["auth_context"] carries the feed's
      flat request projection, in which case it is serialized to the
      tool-appropriate header flags via the auth feed (`control.auth_feed`,
      resolved lazily from the store through the bound account identifier).
      Auth-eligibility is decided ONCE, upstream: the pipeline
      (`run_pipeline`) injects the projection into `extra` only for `use_auth`
      jobs, so a non-auth job never carries it and this gate needs no second
      `use_auth` check (C1 single-owner consolidation).
    """
    extra = extra or {}
    target = input_asset.get("name") or input_asset.get("url") or input_asset.get("address") or ""
    domain = input_asset.get("name") or input_asset.get("domain") or target
    baseurl = input_asset.get("url") or input_asset.get("baseurl") or target
    auth_flags = ""
    if extra.get("auth_context"):
        auth_flags = serialize_auth_flags(extra["auth_context"], tool)

    result = command_template
    result = result.replace("{target}", str(target))
    result = result.replace("{domain}", str(domain))
    result = result.replace("{baseurl}", str(baseurl))
    result = result.replace("{session}", str(session_id))
    result = result.replace("{auth_flags}", auth_flags)
    if "{endpoints}" in result:
        quoted = " ".join(shlex.quote(u) for u in endpoints or [])
        result = result.replace("{endpoints}", quoted)
    return result


def _best_effort_triage(triage_fn, exec_result, assets, job) -> list:
    """Structural decoupling (#208): production (exec -> parse -> curate of the
    asset deltas) and consumption (the triager's Observations) are separate
    concerns. A raising triage_fn degrades to no-observations instead of failing
    the pod, so the already-parsed profiles still reach the curator. The live
    `default_triage_fn` already fail-opens internally (None -> []); this node-level
    guard extends the same contract to any injected triage_fn."""
    try:
        return list(triage_fn(exec_result, assets, job))
    except Exception:  # noqa: BLE001 - the triager is a proposer; it must never fail a pod
        logger.warning(
            "triager failed for job %s; degrading to no observations "
            "(parsed assets still curated)", getattr(job, "tool", ""), exc_info=True)
        return []


def build_pod_graph(*, exec_fn, curate_fn, triage_fn):
    """Build the compiled recon-pod subgraph, injecting the side-effecting
    collaborators: exec_fn(command, session_id, timeout_s) -> ExecResult,
    curate_fn(assets, observations, project_id) -> (int, int),
    triage_fn(exec_result, assets, job) -> list[Observation].

    The configurator node is the deterministic command-fill only (#243:
    the per-pod steering-fed throttle turn retired with the mid-run
    steering machinery, D223-12 - request phases run unthrottled until the
    #238 rate-limit work lands its profile-driven configuration).
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
        elif job.endpoint_profiling:
            # #208 one-pod reprofile: the pod runs ONE httpx exec over the FULL
            # dedup'd endpoint set (the whole reprofile pass in a single pod).
            # The command writes the shell-quoted URL list to the per-pod
            # workdir and probes it via `httpx -l`, then cats the `-o` JSON
            # file - the established `/work/{session}` file + cat persistence
            # pattern. `endpoints` extracts each asset's probe URL via the
            # shared bundle_url helper (url, else baseurl+path). The dispatch
            # is TOTAL: an endpoint_profiling job MUST arrive with its packed
            # `endpoints` set (the preprocess packs it into ONE pod_input); a
            # mis-shaped dispatch raises rather than silently probing nothing.
            if "endpoints" not in input_asset:
                raise ValueError(
                    f"endpoint_profiling job {job.tool} dispatched without an "
                    "'endpoints' set - default_preprocess_fn must pack the dedup'd "
                    "probe set into ONE pod_input (#208)"
                )
            from polymerhus.recon.control.batching import bundle_url

            urls = [u for u in (bundle_url(e) for e in input_asset["endpoints"]) if u is not None]
            command = fill_template(
                job.command_template, input_asset, extra,
                session_id=state["session_id"], tool=job.tool, endpoints=urls,
            )
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
        return {"invocation": invocation, "iteration": iteration, "extra": extra}

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
        # #94: give the triager a STATEFUL session addressed per concurrent pod instance.
        # The run/phase ride the pod state (only in a real pipeline pod, not test-invoked
        # graphs), so we set the per-pod (thread_id, checkpointer) on the ContextVar the
        # live triage_fn reads; the injected triage_fn contract is untouched.
        run_id = state.get("run_id")
        if run_id is not None:
            from polymerhus.app.llm.checkpoints import get_session_checkpointer
            from polymerhus.app.llm.session_address import SessionContext
            address = pod_session(run_id, state.get("phase"), job,
                                  state.get("input_asset", {}), role_id="triager")
            token = _pod_ctx().set(SessionContext(address, get_session_checkpointer()))
            try:
                observations = _best_effort_triage(
                    triage_fn, state["exec_result"], state.get("assets", []), job)
            finally:
                _pod_ctx().reset(token)
        else:
            observations = _best_effort_triage(
                triage_fn, state["exec_result"], state.get("assets", []), job)

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
        job = state["job"]
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
        if extra.get("seed_root_type"):
            curate_kwargs["seed_root_type"] = extra["seed_root_type"]
        assets_merged, observations_merged, merged_assets, merged_observations = curate_fn(
            assets, observations, state["project_id"], **curate_kwargs
        )
        invocation = state.get("invocation")
        stats = {"command": invocation.command} if invocation is not None else None
        if job.endpoint_profiling:
            # #208: the reprofile pod is ONE pod for the WHOLE pass - record how
            # many endpoints it probed so the phase's lineage is recoverable from
            # the export (the D12 `consumed` count is the pre-dedup population).
            if stats is None:
                stats = {}
            stats["endpoints_total"] = len((state.get("input_asset") or {}).get("endpoints") or [])
        export = PodExport(
            input_asset=state["input_asset"],
            verdict="success",
            assets_merged=assets_merged,
            observations_merged=observations_merged,
            # The curated payload the pipeline pushes into the analysis feed (#74).
            assets=merged_assets,
            observations=merged_observations,
            iterations=state.get("iteration", 0),
            stats=stats,
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

    @model_validator(mode="before")
    @classmethod
    def _coerce_coherent_empty(cls, data):
        """Accept the coherent "no observations" artifact in whatever shape the
        provider actually returns. A reasoning model that decides "nothing
        noteworthy" does not reliably emit the wrapped `{"observations": []}`
        object - live muse-spark output included a bare `[]`, an empty string,
        and prose wrapping an array (see the reasoning-token-exhaustion
        diagnosis). All of those ARE a legitimate empty result, so they must
        parse as one instead of raising `StructuredOutputValidationError` and
        failing the pod (which silently drops the already-parsed assets). The
        validator is the native pydantic primitive for this shape coercion.
        """
        if data is None:
            return {"observations": []}
        if isinstance(data, list):
            return {"observations": data}
        if isinstance(data, str):
            text = data.strip()
            if not text:
                return {"observations": []}
            if text.startswith("["):
                import json as _json
                try:
                    parsed = _json.loads(text)
                    if isinstance(parsed, list):
                        return {"observations": parsed}
                except Exception:
                    pass
                return {"observations": []}
            return {"observations": []}
        return data


# Max parsed assets serialized into the triager prompt (see default_triage_fn).
_MAX_TRIAGE_ASSETS = int(os.environ.get("MAX_TRIAGE_ASSETS", "200"))

# The triager role prompt, memoized on first call (no import-time I/O, CODING
# STANDARD section 6). A missing prompt file is a defect: reads FAIL CLOSED.
_TRIAGER_SKILL: str | None = None


def _load_triager_skill() -> str:
    """The triager system prompt = the writing-observations role prompt, read
    directly from this module's `prompts/` dir. Memoized on first call (no
    import-time I/O); FAIL-CLOSED - a missing prompt file raises instead of
    degrading, so a role never reasons without its prompt."""
    global _TRIAGER_SKILL
    if _TRIAGER_SKILL is None:
        from pathlib import Path  # noqa: PLC0415 - lazy, mirrors the reader convention
        _TRIAGER_SKILL = (
            Path(__file__).resolve().parent / "prompts" / "writing-observations.md"
        ).read_text(encoding="utf-8")
    return _TRIAGER_SKILL


logger = logging.getLogger(__name__)


def default_triage_fn(exec_result: ExecResult, assets: list[AssetDelta], job: JobSpec) -> list[Observation]:
    """Real collaborator: ask the triager LLM to flag noteworthy observations
    from a completed tool run. Builds its chat model lazily on each call.
    """
    from polymerhus.app.llm.roles import invoke_role

    # invoke_role owns the single coherent escalating retry (#73) and chooses
    # the structured-output method per capability profile (#99, A1): a
    # tool-calling-only profile degrades to function_calling (the previously
    # hardcoded method), and the json_schema rung now constructs strict=False
    # (dict form) so Observation.anchor's open-ended `dict` field no longer 400s
    # (#44: strict-mode "'additionalProperties' is required to be supplied and
    # to be false" on OpenAI/OpenRouter-family models) - unknown profiles take
    # that semantic default unconditionally.
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
    # #94: when the triager node set a per-pod session context, run STATEFUL - the
    # `triager` role resumes its per-pod thread (so a re-witness of this unit resumes
    # what it saw before) via `ToolStrategy`, which is tool-calling and thus KEEPS the
    # function_calling path `Observation.anchor` needs (NOT native json_schema). With no
    # context (a directly-invoked pod graph in tests, or a pod carrying no run_id), fall
    # back to the stateless #73-retry `invoke_role`.
    ctx = _pod_ctx().get()
    if ctx is not None:
        from polymerhus.app.llm.session import stateful_turn
        from polymerhus.app.llm import compaction as C
        from polymerhus.app.auth.seams import auth_capable_binding  # noqa: PLC0415

        binding = auth_capable_binding("triager")
        result = stateful_turn("triager", ctx.address, messages,
                               checkpointer=ctx.checkpointer, schema=_ObservationBatch,
                               tools=binding.tools,
                               middleware=[C.cached_role_compaction_middleware("triager")]
                               + binding.middleware,
                               context=binding.context)
    else:
        result = invoke_role("triager", messages, schema=_ObservationBatch)
    return result.observations if result else []  # None = exhausted generation -> no observations


pod_graph = build_pod_graph(
    exec_fn=default_exec_fn, curate_fn=curate, triage_fn=default_triage_fn,
)
