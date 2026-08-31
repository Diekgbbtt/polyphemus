"""The two pod agents - the PRODUCTION stateful ReAct seams (T7, D84-16/17/23).

The `pod_runner` (actor) is a pure ReAct plan designer: ONE `create_agent` turn
per stretch, `tools=[exec, note]` (plus the config-gated `query_lightrag` tool),
the P0-P3 plan as `system_prompt`,
the consumed inbox delta as `new_messages` (D84-9/10/11) - the tool-call loop
lives INSIDE `create_agent`, with the harness middleware owning G1/G4/O7
(D84-22). Its final tool call at P3 space-exhaustion writes the consolidated
`experiment_summary` note (D84-17/19). The `pod_triager` (critic) is a third-party
variant miner: one `stateful_turn` with `ToolStrategy(TriagerDecision)` reading
the verbatim P3 note + the filtered context (D84-23).

Both default seams read their TYPED session (`pod_session()`), the run's #95
compaction middleware (`pod_middleware()`), and the run-scoped harness
(`pod_harness()`: exec/kb/memory-store/log/variant/model factory) from the D84-7
ContextVar binding the graph wraps each seam call in - the injected seam CONTRACT
stays untouched, so the contract tier passes stateless fakes
(`symbolic_runner_step_fn`, scripted proposers) and never touches a live LLM.
The production seams hard-fail on an unbound session (D84-14): `arun_pod`'s
fail-open wrapper degrades the run, there is no silent symbolic fallback.

The GUARANTEE that the runner is the control plane yet the pod stays bounded is
STRUCTURAL: the harness owns the cap (`HUNT_POD_MAX_TOOL_CALLS`), the exec tool
records every result RAW (G4), the dedup gate short-circuits repeats (O7), and
the terminal nodes always render the binary envelope.
"""
from __future__ import annotations

from typing import Callable, Literal

from pydantic import BaseModel, Field

from polymerhus.attack.hunting.pod.llm import POD_RUNNER_ROLE, POD_TRIAGER_ROLE
from polymerhus.attack.hunting.pod.prompts import (
    POD_RUNNER_SYSTEM,
    POD_TRIAGER_SYSTEM,
)
from polymerhus.attack.hunting.pod.types import RawObservation, RunnerStep


class TriagerDecision(BaseModel):
    """The critic's per-lap decision: classify the stretch, then either terminate
    (a binary verdict + a Q3-amended terminal_reason + `clean`) or mine a
    falsifiable variant (its declined attribute and derived spec)."""

    classification: str = ""
    action: Literal["terminate", "variant"] = "terminate"
    verdict: str = "unsuccessful"
    terminal_reason: str = "no-symptom-evidence"
    clean: bool = False
    note: str = ""
    declined_attribute: str = ""
    variant_spec: dict = Field(default_factory=dict)
    feedback: str = ""


# Injected seam signatures (the graph owns the curated message lists).
RunnerStepFn = Callable[[dict, list, int], RunnerStep]
TriagerFn = Callable[[dict, RawObservation, list, object], dict]


def symbolic_runner_step_fn(spec: dict, messages: list, tool_calls: int) -> RunnerStep:
    """The LLM-free runner: on the first turn of a stretch it issues the default
    probe from the payload vector space (O12/C11), then concludes and hands the
    observation to the critic. Drives the LLM-free CONTRACT TIER (an injected
    seam - the production default is the ReAct turn, D84-16)."""
    from polymerhus.attack.hunting.pod.symbolic import default_probe_from_spec
    from polymerhus.attack.hunting.pod.tools import curl_command

    if tool_calls == 0:
        chain = default_probe_from_spec(spec, "v")
        if chain is None:
            return RunnerStep(action="conclude", exhausted=True,
                              observation_note="no probe derivable from the payload vector space")
        return RunnerStep(action="tool_call", tool="exec",
                          command=curl_command(chain.steps[0]),
                          thought="issue the default probe for the target root")
    return RunnerStep(action="conclude",
                      observation_note="default probe issued; handing the observation to the critic")


async def default_runner_step_fn(spec: dict, messages: list, tool_calls: int) -> RunnerStep:
    """The PRODUCTION Runner (D84-16/17/22/29): ONE stateful `create_agent`
    ReAct turn per stretch - the tool-call loop lives INSIDE the agent, the graph
    never interrupts per tool result. Reads the typed session + run-scoped
    harness (exec/store/log/variant/model_factory) from the D84-7 binding
    (`pod_session()` / `pod_harness()`), binds `tools=[exec, note]` (plus the
    config-gated `query_lightrag` tool) with `middleware=[compaction, harness]`
    (D84-12/22), hands `messages` (the consumed inbox delta, D84-11) as
    `new_messages`, and synthesizes the stretch `RunnerStep` from the turn:
    `conclude`, `exhausted` when no raw observation was recorded (the old
    empty-probe rule), the final model content as the observation note.

    Hard-fails on an unbound session/harness (D84-14: no silent symbolic
    fallback) - `arun_pod`'s fail-open wrapper degrades the run, never raises
    into the parent."""
    from polymerhus.app.llm.session import arun_session_turn  # noqa: PLC0415
    from polymerhus.attack.hunting.pod.harness import (  # noqa: PLC0415
        build_harness_middleware,
    )
    from polymerhus.attack.hunting.pod.llm import (  # noqa: PLC0415
        pod_harness,
        pod_middleware,
        pod_session,
    )

    ctx = pod_session()
    hc = pod_harness()
    if ctx is None or hc is None:
        raise RuntimeError(
            "no bound pod session/harness for the stateful runner turn (D84-14)")
    if hc.log is None:
        raise RuntimeError("the production runner harness needs the D6 log")
    before_obs = len(hc.log.raw_observations)
    tools = runner_react_tools(hc.exec_fn, hc.memory_store, hc.spec_id, hc.log,
                               hc.variant_ref or "", graph_view_fn=hc.graph_view_fn)
    harness_mw = build_harness_middleware(log=hc.log,
                                          variant_ref=hc.variant_ref or "",
                                          cap=hc.cap)
    mw = list(pod_middleware()) + [harness_mw]
    turn = await arun_session_turn(
        ctx.address.role_id, ctx.address, list(messages),
        checkpointer=ctx.checkpointer, tools=tools, middleware=mw,
        system_prompt=RUNNER_SYSTEM, model_factory=hc.model_factory)
    new_obs = len(hc.log.raw_observations) - before_obs
    content = str(getattr(turn, "content", None) or "")
    return RunnerStep(action="conclude", exhausted=new_obs == 0,
                      thought=content, observation_note=content)


async def default_triager_fn(spec: dict, observation: RawObservation,
                             messages: list, log) -> dict:
    """The PRODUCTION Triager (D84-23): a `stateful_turn` over the typed
    `HuntSession` thread with `ToolStrategy(TriagerDecision)` and the critic's
    compaction middleware, reading the delta the graph composed (`messages` =
    the verbatim P3 note + filtered triager context + memory guidance, D84-23).
    Bound tools: note read + (config-gated) query_lightrag (D84-27) - NEVER exec.
    Hard-fails on an unbound session/harness (D84-14); a FAILED turn degrades to
    a safe honest terminal, never raises into the loop."""
    from polymerhus.app.llm.session import stateful_turn  # noqa: PLC0415
    from polymerhus.attack.hunting.pod.context import _dicts_to_lc  # noqa: PLC0415
    from polymerhus.attack.hunting.pod.llm import (  # noqa: PLC0415
        pod_harness,
        pod_middleware,
        pod_session,
    )

    try:
        ctx = pod_session()
        hc = pod_harness()
        if ctx is None or hc is None:
            raise RuntimeError(
                "no bound pod session/harness for the stateful triager turn (D84-14)")
        tools = triager_react_tools(hc.memory_store, hc.spec_id,
                                    log=hc.log, variant_ref=hc.variant_ref or "",
                                    graph_view_fn=hc.graph_view_fn)
        delta = _dicts_to_lc(list(messages))
        result = stateful_turn(
            ctx.address.role_id, ctx.address, delta,
            checkpointer=ctx.checkpointer, schema=TriagerDecision,
            system_prompt=TRIAGER_SYSTEM, middleware=list(pod_middleware()),
            model_factory=hc.model_factory)
        if result is None:
            raise ValueError("unmet triager generation")
        return result.model_dump()
    except Exception as exc:  # noqa: BLE001 - fail-open safe terminal
        return TriagerDecision(
            classification="noise", action="terminate", verdict="unsuccessful",
            terminal_reason="no-symptom-evidence", clean=False,
            note=f"triager degraded: {exc}").model_dump()


# --- the pod roles' #95 compaction middleware (D9), resolved LAZILY ------------

def runner_compaction_middleware(*, window=None, threshold=None, store=None):
    """The `pod_runner` role's compaction middleware for the pod's stateful
    turns (T7): the shared role builder bound to the pod's actor role, with the
    summariser on its own model and a fail-open D7 reasoning profile. Resolved
    LAZILY - the shared builder is imported inside the call, never at import, so
    nothing here is a boot-gate; a missing role config degrades the
    window/profile, never raises (the recon/analysis consumers' exact shape).
    `window`/`threshold`/`store` are explicit for hermetic tests."""
    from polymerhus.app.llm import compaction as C  # noqa: PLC0415

    return C.build_role_compaction_middleware(
        POD_RUNNER_ROLE, window=window, threshold=threshold, store=store)


def triager_compaction_middleware(*, window=None, threshold=None, store=None):
    """The `pod_triager` role's compaction middleware, same lazy fail-open shape
    as the runner's - the critic's own session stays under the window."""
    from polymerhus.app.llm import compaction as C  # noqa: PLC0415

    return C.build_role_compaction_middleware(
        POD_TRIAGER_ROLE, window=window, threshold=threshold, store=store)


# Re-exported so the graph and arun_pod can name the base prompts.
RUNNER_SYSTEM = POD_RUNNER_SYSTEM
TRIAGER_SYSTEM = POD_TRIAGER_SYSTEM


def runner_react_tools(exec_fn, memory_store, spec_id, log, variant_ref, *,
                       kb_fn=None, kb_lookup=None, graph_view_fn=None):
    """The Runner's bound-tool set (D84-16/27): `exec` (raw-recording terminal),
    `note` (pod memory write/read), the single `query_lightrag` KB tool from the
    lightrag branch (always-bound as of #197 - the `HUNTING_LIGHTRAG_TOOL` gate
    is REMOVED, fail-open to a degraded bundle), and the ONE shared `graph_view`
    read-only L0/L1 tool (#197) the runner uses to locate the target's surface.
    The T3 (#179) `KbObservation` recording is bound to the SAME log + variant
    the exec tool records into. The former `kb_retrieve` symptom-technique typed
    seam (surface B) is retired. Constructed PER STRETCH because `exec` carries
    the current variant's dedup scope."""
    from polymerhus.attack.hunting.pod.note_tool import PodNoteTool  # noqa: PLC0415
    from polymerhus.attack.hunting.pod.tools import ExecTool, KbQueryTool  # noqa: PLC0415

    tools = [
        ExecTool(exec_fn=exec_fn, log=log, variant_ref=variant_ref),
        PodNoteTool(store=memory_store, spec_id=spec_id),
    ]
    tools += [KbQueryTool(log=log, variant_ref=variant_ref)]
    tools += _graph_view_tools(graph_view_fn)
    return tools


def triager_react_tools(memory_store, spec_id, *, kb_fn=None, kb_lookup=None,
                        log=None, variant_ref="", graph_view_fn=None):
    """The Triager's bound-tool set (D84-27): note read + the always-bound
    `query_lightrag` KB tool + the shared `graph_view` L0/L1 tool (#197) - NEVER
    exec (the critic never touches the target). The triager's KB reads are
    CONTEXT reads (D84-27), so `log`/`variant_ref` may be unbound - a logless KB
    tool records nothing (fail-open); when the harness provides them, the reads
    are recorded against the current variant (T3/#179)."""
    from polymerhus.attack.hunting.pod.note_tool import PodNoteTool  # noqa: PLC0415
    from polymerhus.attack.hunting.pod.tools import KbQueryTool  # noqa: PLC0415

    tools = [PodNoteTool(store=memory_store, spec_id=spec_id)]
    tools += [KbQueryTool(log=log, variant_ref=variant_ref)]
    tools += _graph_view_tools(graph_view_fn)
    return tools


def _graph_view_tools(graph_view_fn=None) -> list:
    """The shared read-only L0/L1 `graph_view` tool (#197), always bound for the
    pod roles (runner + triager) over the injected `ReadOnlyGraphView(project_id)
    .read` seam. Absent/raising -> the tool's own fail-open `{"error": ...}`."""
    from polymerhus.attack.hunting.graph_view_tool import (  # noqa: PLC0415
        build_graph_view_tool,
    )

    return [build_graph_view_tool(graph_view_fn)]
