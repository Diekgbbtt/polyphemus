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

import json
from typing import Callable, Literal

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from polymerhus.attack.hunting.http_history_contract import (
    REPLAY_HTTP_REQUEST_DESCRIPTION,
)
from polymerhus.attack.hunting.pod.llm import POD_RUNNER_ROLE, POD_TRIAGER_ROLE
from polymerhus.attack.hunting.pod.prompts import (
    load_pod_divergence_skill,
    load_pod_runner_skill,
    load_pod_terminal_skill,
    load_pod_triage_skill,
    load_pod_triager_skill,
)
from polymerhus.attack.hunting.pod.types import RawObservation, RunnerStep


class TriagerDecision(BaseModel):
    """The critic's per-lap decision: classify the stretch, then either terminate
    (a binary verdict + a Q3-amended terminal_reason + `clean`) or mine a
    falsifiable variant (its basis and derived spec).

    The variant fields carry the S5 8.6 material the graph resolves the basis
    from: `covered_gap_classes` is the triager's coverage assessment of the
    executed D6 trail against the nine typed `SkillProcedure` fields (None =
    no assessment stated), and the two trigger flags name a failed or diverged
    runner execution.
    `declined_attribute` is the triager's claimed basis; the graph reconciles it
    with the first-uncovered diff and records the RESOLVED basis."""

    classification: str = ""
    action: Literal["terminate", "variant"] = "terminate"
    verdict: str = "unsuccessful"
    terminal_reason: str = "no-symptom-evidence"
    clean: bool = False
    note: str = ""
    declined_attribute: str = ""
    variant_spec: dict = Field(default_factory=dict)
    feedback: str = ""
    covered_gap_classes: list[str] | None = None
    runner_failed: bool = False
    runner_diverged: bool = False


class TriageDecision(BaseModel):
    """The FIRST staged triage decision: did the Runner execution fail, and did
    the latest observation confirm the spec's verification symptom?

    The compact stage receives no tool surface, no skill, no KB, no variants,
    and no procedure excerpt; its only judgments are these two. A confirmed
    symptom short-circuits to the deterministic export; a failed execution
    mints the `runner-failure` recovery variant; anything else walks on to the
    divergence and bounded-variant stages."""

    runner_failed: bool = Field(
        default=False,
        description="True only when the Runner execution itself failed "
                    "(a broken execution, not a negative observation).")
    symptom_confirmed: bool = Field(
        default=False,
        description="True only when the latest observation establishes the "
                    "spec's verification symptom.")
    clean: bool = Field(
        default=False,
        description="True only when the confirming observation was completed "
                    "and captured, not blocked, unreachable, or cut mid-flight.")
    note: str = Field(
        default="",
        description="The reviewer-facing interpretation; the load-bearing fact, "
                    "about 500 characters maximum.")


class DivergenceDecision(BaseModel):
    """The SECOND staged triage decision: did the execution DIVERGE from the
    spec's typed skill procedure?

    The stage receives the typed `SkillProcedure` excerpt and the executed
    trail, and no tool surface. A divergence mints the `runner-divergence`
    recovery variant; a negative observation that still followed the procedure
    is not a divergence."""

    runner_diverged: bool = Field(
        default=False,
        description="True only when the executed probes ignored or contradicted "
                    "the spec's typed procedure (not merely a negative result).")
    note: str = Field(
        default="",
        description="The reviewer-facing interpretation naming the diverging "
                    "procedure field and probe; about 500 characters maximum.")


class TerminalDecision(BaseModel):
    """The terminal staged decision: the verdict, the terminal reason, and the
    clean flag, when the spec carries no populated procedure attribute to bend
    into a variant.

    The stage mines nothing. It reads the note, the symptoms, the observation,
    the probe trail, the variant bases, and the KB degraded flags, and applies
    the binary terminal vocabulary."""

    classification: str = ""
    verdict: str = "unsuccessful"
    terminal_reason: str = "no-symptom-evidence"
    clean: bool = False
    note: str = ""



# Injected seam signatures (the graph owns the curated message lists).
RunnerStepFn = Callable[[dict, list, int], RunnerStep]
TriagerFn = Callable[[dict, RawObservation, list, object], dict]


def symbolic_runner_step_fn(spec: dict, messages: list, tool_calls: int) -> RunnerStep:
    """The LLM-free runner: on the first turn of a stretch it AUTHORS one probe
    from the reduced spec (S5 8.5) - a replay of `provenance.baseline_ref` when
    the hunter named one, otherwise a GET of `target_identity.url` - then
    concludes and hands the observation to the critic. A spec with neither is
    the real "no probe derivable" outcome. Drives the LLM-free CONTRACT TIER
    (an injected seam - the production default is the ReAct turn, D84-16)."""
    from polymerhus.attack.hunting.pod.symbolic import author_probe_from_spec
    from polymerhus.attack.hunting.pod.tools import curl_command

    if tool_calls == 0:
        chain = author_probe_from_spec(spec, "v")
        if chain is None:
            return RunnerStep(action="conclude", exhausted=True,
                              observation_note="no probe derivable from the reduced spec")
        core = chain.steps[0]
        if core.request_ref:
            return RunnerStep(action="tool_call", tool="replay",
                              request_ref=core.request_ref,
                              overrides=dict(core.overrides),
                              thought="replay the spec's recorded baseline")
        return RunnerStep(action="tool_call", tool="exec",
                          command=curl_command(core),
                          thought="issue the first probe authored from the target identity")
    return RunnerStep(action="conclude",
                      observation_note="first probe issued; handing the observation to the critic")


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
    fallback) - `arun_pod`'s fail-open wrapper degrades the run, never raises a
    DOMAIN failure into the parent; a provider failure propagates as the typed
    `ProviderUnavailableError` (#329)."""
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
                               hc.variant_ref or "", graph_view_fn=hc.graph_view_fn,
                               capture_context=hc.capture_context,
                               replay_fn=hc.replay_fn,
                               project_id=getattr(hc.capture_context, "project_id", "") or "")
    harness_mw = build_harness_middleware(log=hc.log,
                                          variant_ref=hc.variant_ref or "",
                                          cap=hc.cap)
    from polymerhus.app.auth.seams import auth_capable_binding  # noqa: PLC0415

    # #236: the spec's artifact-declared skills union into the pod_runner
    # baseline at the binding; the index middleware renders each resolved
    # description into this turn's system prompt.
    binding = auth_capable_binding(
        ctx.address.role_id, task_skills=hc.task_skills,
        project_id=getattr(hc.capture_context, "project_id", "") or None,
        with_readonly_auth_store=True)
    mw = list(pod_middleware()) + [harness_mw] + binding.middleware
    turn = await arun_session_turn(
        ctx.address.role_id, ctx.address, list(messages),
        checkpointer=ctx.checkpointer, tools=tools + binding.tools, middleware=mw,
        context=binding.context,
        usage_scope=getattr(hc.capture_context, "project_id", "") or "",
        system_prompt=load_pod_runner_skill(), model_factory=hc.model_factory)
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
    a safe honest terminal, never raises a DOMAIN failure into the loop - a
    provider failure propagates as the typed `ProviderUnavailableError` (#329)."""
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
        from polymerhus.app.auth.seams import auth_capable_binding  # noqa: PLC0415

        # #236: the spec's artifact-declared skills union into the pod_triager
        # baseline at the binding (the same ONE seam the runner uses).
        binding = auth_capable_binding(
            ctx.address.role_id, task_skills=hc.task_skills,
            project_id=getattr(hc.capture_context, "project_id", "") or None,
            with_readonly_auth_store=True)
        result = stateful_turn(
            ctx.address.role_id, ctx.address, delta,
            checkpointer=ctx.checkpointer, schema=TriagerDecision,
            tools=tools + binding.tools, context=binding.context,
            usage_scope=getattr(hc.capture_context, "project_id", "") or "",
            system_prompt=load_pod_triager_skill(),
            middleware=list(pod_middleware()) + binding.middleware,
            model_factory=hc.model_factory)
        if result is None:
            raise ValueError("unmet triager generation")
        return result.model_dump()
    except Exception as exc:  # noqa: BLE001 - fail-open safe terminal
        from polymerhus.app.llm.provider_failure import as_provider_error

        failure = as_provider_error(exc)
        if failure is not None:
            # #329: a provider failure is infrastructure, not a triager
            # assessment. Propagate the typed error (the pod classifies it) so a
            # throttle is never laundered into a benign `no-symptom-evidence`
            # domain verdict.
            raise failure from exc
        return TriagerDecision(
            classification="noise", action="terminate", verdict="unsuccessful",
            terminal_reason="no-symptom-evidence", clean=False,
            note=f"triager degraded: {exc}").model_dump()


def _schema_stage_turn(schema, system_prompt: str, messages: list) -> dict:
    """One no-tools structured stage turn (stages A, B, D).

    The turn rides the SAME bound `pod_triager` session, checkpointer, compaction
    middleware, and model factory as the full miner, but binds NO tools and no
    skill surface: the fixed first-call tax loses the tool descriptions and the
    skill index. A result the model did not produce is an unmet generation."""
    from polymerhus.attack.hunting.pod.context import _dicts_to_lc  # noqa: PLC0415
    from polymerhus.attack.hunting.pod.llm import (  # noqa: PLC0415
        pod_harness,
        pod_middleware,
        pod_session,
    )
    from polymerhus.app.llm.session import stateful_turn  # noqa: PLC0415

    ctx = pod_session()
    hc = pod_harness()
    if ctx is None or hc is None:
        raise RuntimeError(
            "no bound pod session/harness for the staged triage turn (D84-14)")
    result = stateful_turn(
        ctx.address.role_id, ctx.address, _dicts_to_lc(list(messages)),
        checkpointer=ctx.checkpointer, schema=schema, tools=(),
        context=None, system_prompt=system_prompt,
        middleware=list(pod_middleware()), model_factory=hc.model_factory,
        usage_scope=getattr(hc.capture_context, "project_id", "") or "")
    if result is None:
        raise ValueError(f"unmet {schema.__name__} generation")
    return result.model_dump()


async def default_triage_fn(spec: dict, observation: RawObservation,
                            messages: list, log) -> dict:
    """Stage A: the compact failure and symptom-confirmation turn.

    No tools, no skill, no KB, no procedure excerpt, no variants. A provider
    failure propagates; any other failure degrades to a not-confirmed
    assessment so the later stages still reach a terminal."""
    from polymerhus.app.llm.provider_failure import as_provider_error  # noqa: PLC0415

    try:
        return _schema_stage_turn(
            TriageDecision, load_pod_triage_skill(), messages)
    except Exception as exc:  # noqa: BLE001 - fail-open compact assessment
        failure = as_provider_error(exc)
        if failure is not None:
            raise failure from exc
        return TriageDecision(
            note=f"triage degraded: {exc}").model_dump()


async def default_divergence_fn(spec: dict, observation: RawObservation,
                                messages: list, log) -> dict:
    """Stage B: the compact procedure-divergence turn.

    The typed `SkillProcedure` excerpt and the executed trail ride the delta;
    no tool surface is bound. A provider failure propagates; any other failure
    degrades to not-diverged so the bounded variant or the terminal decides."""
    from polymerhus.app.llm.provider_failure import as_provider_error  # noqa: PLC0415

    try:
        return _schema_stage_turn(
            DivergenceDecision, load_pod_divergence_skill(), messages)
    except Exception as exc:  # noqa: BLE001 - fail-open divergence assessment
        failure = as_provider_error(exc)
        if failure is not None:
            raise failure from exc
        return DivergenceDecision(
            note=f"divergence degraded: {exc}").model_dump()


async def default_terminal_fn(spec: dict, observation: RawObservation,
                              messages: list, log) -> dict:
    """Stage D: the compact terminal verdict when no procedure attribute can be
    bent into a variant.

    No tool surface and no variant mining; the stage applies the binary
    terminal vocabulary to the note, the observation, the probe trail, and the
    KB degraded flags. A provider failure propagates; any other failure
    degrades to a safe `no-symptom-evidence` terminal."""
    from polymerhus.app.llm.provider_failure import as_provider_error  # noqa: PLC0415

    try:
        return _schema_stage_turn(
            TerminalDecision, load_pod_terminal_skill(), messages)
    except Exception as exc:  # noqa: BLE001 - fail-open terminal
        failure = as_provider_error(exc)
        if failure is not None:
            raise failure from exc
        return TerminalDecision(
            note=f"terminal degraded: {exc}").model_dump()


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


def runner_react_tools(exec_fn, memory_store, spec_id, log, variant_ref, *,
                       kb_fn=None, kb_lookup=None, graph_view_fn=None,
                       capture_context=None, replay_fn=None, project_id=""):
    """The Runner's bound-tool set (D84-16/27): `exec` (raw-recording terminal),
    `notes` (pod memory write/read), the single `query_lightrag` KB tool from the
    lightrag branch (always-bound as of #197 - the `HUNTING_LIGHTRAG_TOOL` gate
    is REMOVED, fail-open to a degraded bundle), and the ONE shared `graph_view`
    read-only L0/L1 tool (#197) the runner uses to locate the target's surface.
    The T3 (#179) `KbObservation` recording is bound to the SAME log + variant
    the exec tool records into. The former `kb_retrieve` symptom-technique typed
    seam (surface B) is retired. Constructed PER STRETCH because `exec` carries
    the current variant's dedup scope."""
    from polymerhus.attack.hunting.pod.note_tool import PodNoteTool  # noqa: PLC0415
    from polymerhus.attack.hunting.pod.tools import (  # noqa: PLC0415
        ExecTool,
        KbQueryTool,
        replay_signature,
    )

    tools = [
        ExecTool(exec_fn=exec_fn, log=log, variant_ref=variant_ref,
                 capture_context=capture_context),
        PodNoteTool(store=memory_store, spec_id=spec_id),
    ]
    tools += [KbQueryTool(log=log, variant_ref=variant_ref)]
    tools += _graph_view_tools(graph_view_fn)

    def _record_replay(artifact_id, overrides, result) -> None:
        """Record a replay result as a `RawObservation` (fail-open, S5 8.5): a
        replay is a probe execution like any other, so its observed status
        lands RAW in the D6 trail (G4). A missing baseline (null status) is an
        UNOBSERVABLE response (`returncode=1`), never a clean absence; a
        logless tool records nothing (the contract tier)."""
        if log is None:
            return
        try:
            sig = replay_signature(variant_ref, artifact_id, overrides)
            status = result.get("status") if isinstance(result, dict) else None
            artifact = result.get("artifact_id") if isinstance(result, dict) else None
            log.mark_executed(sig)
            log.record_observation(RawObservation(
                probe_ref=sig, variant_ref=variant_ref,
                request={"artifact_id": artifact_id, "overrides": dict(overrides)},
                status=status if isinstance(status, int) else None,
                returncode=0 if status is not None else 1,
                http_artifact_refs=(
                    [artifact] if isinstance(artifact, str) and artifact else [])))
        except Exception:  # noqa: BLE001 - evidence recording never gates the tool
            pass

    if replay_fn is not None:
        # The description is the canonical contract (#196) imported from
        # `http_history_contract` - the pod and the hunter's read pair teach the
        # SAME artifact model; a local docstring here would be a second source.
        @tool(description=REPLAY_HTTP_REQUEST_DESCRIPTION)
        def replay(artifact_id: str, overrides: dict | None = None) -> str:
            declared = overrides or {}
            result = replay_fn(project_id, artifact_id, declared)
            _record_replay(artifact_id, declared, result)
            return json.dumps(result)

        tools.append(replay)
    return tools


def triager_react_tools(memory_store, spec_id, *, kb_fn=None, kb_lookup=None,
                        log=None, variant_ref="", graph_view_fn=None):
    """The Triager's bound-tool set (D84-27): notes read + the always-bound
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
