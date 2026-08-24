"""The pod's looped state machine (D67-06) as a LangGraph StateGraph, with the
PRODUCTION runner driving each stretch as ONE stateful `create_agent` ReAct turn
(T7, D84-16/17/22/29).

Inversion of control (operator, 2026-08-06, re-specified in the #84 regrounding):
the RUNNER is the control plane of the probe stretch - it perceives a tool
result, interprets, and reasons the next step INSIDE `create_agent`; it is a pure
ReAct plan designer running the P0-P3 plan (D84-16). The HARNESS owns the bounds
and the contract:

  G1 termination - the ReAct loop is capped at `HUNT_POD_MAX_TOOL_CALLS` per
     stretch by the harness middleware (D84-22) and the outer loop at
     `HUNT_POD_MAX_ITERS` stretches (`decide_router`); LangGraph's recursion
     limit is the backstop.
  G2 safety      - a malformed exec call is rejected by the harness gate; tool
     ARGUMENT validation is the tool's own `extra="forbid"` contract (a wrong
     parameter is a REJECTED tool call, never re-validated by the harness).
  G3 contract    - only the triager + terminal nodes assign the verdict and the
     terminal_reason; the runner never touches the terminal vocabulary.
  G4 honesty     - every exec result is recorded RAW in the experiment log (D6)
     by the exec tool before curation.
  G5 fail-open   - a raising collaborator degrades to a terminal with the partial
     trail; nothing raises past `arun_pod`.

The FSM (production):

  INIT-schema (deterministic gate; C1: reject with no tool call)
    -> runner_agent     (ONE `arun_session_turn` per stretch: the ReAct loop with
                         tools=[exec, kb_retrieve, note], system_prompt = the
                         P0-P3 plan, new_messages = the consumed inbox delta;
                         the P3 note write is the runner's FINAL tool call)
    -> triager (symbolic fast-path, else the critic's note-reading stateful turn)
    -> decide  -> {terminal | mine variant -> [POD-BUDGET CHECK] -> runner_agent
                   | budget_terminal}
    -> TERMINAL (render the D5 + D6 envelope)

THE CONTRACT-TIER LANE: an injected `runner_step_fn` (a sync fake such as
`symbolic_runner_step_fn`) keeps the pre-regrounding node shape - the same
`runner_agent` <-> `tool_exec` bounded loop with dict message views (the interim
`curate_messages` pre_model_hook is removed - D84-13) - so the LLM-free
contract tier runs unchanged. The PRODUCTION default seam
(`default_runner_step_fn`, chosen when `runner_step_fn=None`) performs the whole
ReAct loop inside its turn and returns a synthetic `conclude` step: the
`tool_exec` node is then NOT registered at all (D84-29: "the tool_exec node
disappears").

The pod is ASYNC-NATIVE (D84-15, Q7): the nodes that call injected seams
(`runner_agent`, `tool_exec`, `triager`) are `async def` and ride every
collaborator call through `_await_seam` - an async seam is awaited natively, a
sync seam is offloaded via `asyncio.to_thread`. The graph is driven with
`ainvoke`; the deterministic nodes stay sync.

`build_pod_graph` injects every side-effecting collaborator so the contract tier
runs without a live target, a live LLM, or the downstream agents.
"""
from __future__ import annotations

import asyncio
import inspect

from langgraph.graph import END, START, StateGraph

from polymerhus.attack.hunting.pod.agents import (
    RUNNER_SYSTEM,
    TRIAGER_SYSTEM,
    default_runner_step_fn,
    default_triager_fn,
)
from polymerhus.attack.hunting.pod.config import (
    EXEC_TIMEOUT_S,
    HUNT_POD_MAX_ITERS,
    HUNT_POD_MAX_TOOL_CALLS,
    MAX_POD_ITERS,
)
from polymerhus.attack.hunting.pod.context import (
    ExperimentLog,
    _dicts_to_lc,
    _lc_to_dicts,
    compose_runner_delta,
    compose_triager_delta,
)
from polymerhus.attack.hunting.pod.llm import (
    POD_DEFAULT_RUN_ID,
    POD_RUNNER_ROLE,
    POD_TRIAGER_ROLE,
    PodHarnessContext,
    bind_pod_session,
)
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
from polymerhus.attack.hunting.pod.symbolic import evaluate_symptom
from polymerhus.attack.hunting.pod.tools import command_signature, parse_curl, run_with_retry
from polymerhus.attack.hunting.pod.types import (
    BUDGET_TIMEOUT,
    INFEASIBILITY_SIGNAL_CLASS,
    Interpretation,
    NO_SYMPTOM_EVIDENCE,
    PodExport,
    PodState,
    RawObservation,
    RunnerStep,
    SPACE_EXHAUSTED,
    SYMPTOM_CONFIRMED,
    SYMPTOM_CONFIRMED_CLASS,
    TECHNICAL_INFEASIBILITY,
    VariantSpec,
)
from polymerhus.attack.hunting.pod.verification import validate_decision, validate_spec


def _curated(messages) -> list[dict]:
    """Channel BaseMessages -> the seam-facing dict views (D84-4): the
    message-type conversion happens HERE, at the graph-channel boundary, never
    inside the seams. The runner's tool results live on the channel as
    HumanMessages (`_dicts_to_lc` maps the `tool` role onto one) but are
    re-tagged to their semantic `tool` role so the seam-facing views keep the
    established shape (the interim body-slicing/window `curate_messages` step is
    removed - D84-13); the triager channel carries no tool messages."""
    views = _lc_to_dicts(messages)
    for v in views:
        if (v["role"] == "human"
                and v["content"].startswith(("TOOL RESULT:", "TOOL ERROR:", "KB RESULT:"))):
            v["role"] = "tool"
    return views


def _command_signature(variant_ref: str, command: str) -> str:
    """The O7/C10 dedup signature over `(variant_ref, command)` (re-exported from
    the tools module so the contract-tier tool_exec lane and the harness share
    one key derivation)."""
    return command_signature(variant_ref, command)


def _step(state: PodState) -> RunnerStep:
    raw = state.get("pending_step", {})
    try:
        return raw if isinstance(raw, RunnerStep) else RunnerStep(**(raw or {}))
    except Exception:  # noqa: BLE001
        return RunnerStep(action="conclude", exhausted=True)


def _clean_from_trail(log: ExperimentLog) -> bool:
    for obs in log.raw_observations:
        if obs.status is None and (obs.returncode not in (0, None)):
            return False
    return bool(log.raw_observations)


async def _await_seam(fn, *args):
    """Await an async seam, else offload a sync one to a worker thread - the
    `_await_seam` pattern mirrored from `hunt_orchestrator.py` /
    `hunting_agent.py`. `asyncio.to_thread` copies the caller's context, so the
    graph's pod-session ContextVar binding (D84-7) reaches sync seams too."""
    if inspect.iscoroutinefunction(fn):
        return await fn(*args)
    return await asyncio.to_thread(fn, *args)


def _export(state: PodState, *, verdict: str, reason: str, clean: bool,
            init_validation=None, error=None) -> dict:
    log: ExperimentLog = state["log"]
    export = PodExport(
        verdict=verdict, terminal_reason=reason,
        iterations=state.get("iteration", 0), clean=clean,
        init_validation=list(init_validation or []),
        variant_specs=[v.model_dump() for v in log.variant_specs],
        raw_observations=[o.model_dump() for o in log.raw_observations],
        interpretations=[i.model_dump() for i in log.interpretations],
        error=error)
    return {"export": export.to_envelope(), "verdict": verdict, "terminal_reason": reason}


def _root_spec_id(state: PodState, spec_id: str | None) -> str:
    """The memory-store key (D84-34): the #164 hunter's `spec_id`
    (`<fault>_<strategy>`) crossed through the typed handoff. NO FALLBACK
    (operator, 2026-08-23): the typed handoff is the runtime control-plane's
    ownership (communicated by the inbox surfer loop), so a missing `spec_id`
    is the dispatch's own anticipated failure mode, never the pod's to paper
    over. A caller with a bound store but without a `spec_id` is a hard
    configuration error - the dispatch must fail before the pod runs, never
    persist under a hash. The session thread identity is ALWAYS the canonical
    hash (`context.canonical_spec_hash`, unchanged), never this memory key."""
    if not spec_id:
        raise ValueError(
            "pod memory requires the #164 hunter's spec_id "
            "(<fault>_<strategy>); a missing spec_id is the dispatch's "
            "failure mode, the pod never falls back to a hash")
    return spec_id


def _variant_order(state: PodState) -> int:
    """The variant ORDINAL (D84-34): the current variant's index in the D6 log,
    0 for the initial v0 - the memory key's order component."""
    log = state.get("log")
    if log is not None and log.variant_specs:
        ref = state.get("current_variant_ref", "v0")
        for i, v in enumerate(log.variant_specs):
            if v.ref == ref:
                return i
    return 0


def _harness_ctx(state: PodState, *, exec_fn, kb_fn, memory_store,
                 model_factory, spec_id) -> PodHarnessContext:
    """The run-scoped harness the production seams read (T7): exec/kb/store/log/
    variant/model factory, with the memory key on the #164 spec id (D84-34). The
    memory key is required ONLY when a store is bound (a real persist path) -
    the contract tier with no store never persists, so no spec_id is demanded
    and the note tool degrades fail-open (O10)."""
    mem_key = _root_spec_id(state, spec_id) if memory_store is not None else (spec_id or "")
    return PodHarnessContext(
        exec_fn=exec_fn, kb_fn=kb_fn, memory_store=memory_store,
        spec_id=mem_key, log=state.get("log"),
        variant_ref=state.get("current_variant_ref", "v0"),
        model_factory=model_factory, cap=HUNT_POD_MAX_TOOL_CALLS)


def build_pod_graph(*, exec_fn, runner_step_fn=None, triager_fn=None, kb_fn=None,
                    runner_middleware=(), triager_middleware=(),
                    memory_store=None, model_factory=None,
                    project_id=None, spec_id=None):
    """Compile the pod subgraph, injecting the side-effecting collaborators:

    - `exec_fn(command, timeout_s) -> ExecResult` - the terminal (required).
    - `runner_step_fn(spec, messages, tool_calls) -> RunnerStep` - PRODUCTION
      default (`None`) = `default_runner_step_fn`, ONE stateful ReAct turn per
      stretch (the `tool_exec` node stays unregistered); an injected sync fake =
      the contract-tier lane (the bounded `runner_agent` <-> `tool_exec` loop).
    - `triager_fn(spec, observation, messages, log) -> decision` - the critic;
      the production default is the note-reading `stateful_turn` (D84-23).
    - `kb_fn(query, *, fault_id, technological_axis) -> dict` - the NL
      knowledge-base seam; default = the fail-open `kb_retrieve` stub.
    - `runner_middleware` / `triager_middleware` - the per-role #95 compaction
      middleware sets the run injected (T5); the production default seams pass
      them to the stateful turns verbatim (D84-12). Default `()` = uncompacted.
    - `memory_store` - the pod-owned experiment-memory store (D84-33); default
      = the per-project root `data/<project_id>/test-executor-pod/` when a
      PRODUCTION seam is in play AND `project_id` is provided, `None` (never
      constructed) for a fully-injected contract tier or an absent project id
      (the note tool then degrades fail-open, O10).
    - `model_factory(role) -> chat model` - the session model seam for the
      production turns (`None` = the role's real model; tests inject a fake).
    - `project_id` - the store's scoping axis (D84-33), from the parent hunting
      module context.
    - `spec_id` - the #164 hunter's `SpecItem.spec_id` (`<fault>_<strategy>`)
      crossed through the typed handoff; REQUIRED when a memory store is bound
      (no fallback - a missing spec_id is the dispatch's failure mode, never a
      hash key), optional only for a fully-injected store-less contract tier.
    """
    if runner_step_fn is None:
        runner_step_fn = default_runner_step_fn
        production_runner = True
    else:
        production_runner = False
    if triager_fn is None:
        triager_fn = default_triager_fn
        production_triager = True
    else:
        production_triager = False
    if kb_fn is None:
        from polymerhus.attack.hunting.pod.tools import kb_retrieve
        kb_fn = kb_retrieve
    if memory_store is None and (production_runner or production_triager) and project_id:
        memory_store = PodMemoryStore(project_id=project_id)

    def init(state: PodState) -> dict:
        spec = dict(state["spec"])
        mem_key = _root_spec_id(state, spec_id) if memory_store is not None else (spec_id or "")
        # T2: the in-memory ExperimentLog is ALSO the symbolic-layer capture
        # middleware - bound to the store it re-persists every deterministic
        # mutation to the variant's experiment-log slice (init records v0 here).
        log = ExperimentLog(store=memory_store, spec_id=mem_key)
        log.start_run()
        log.record_variant(VariantSpec(ref="v0", parent_ref=None, spec=spec))
        violations = validate_spec(spec)
        runner_messages = [{"role": "system", "content": RUNNER_SYSTEM}]
        if not violations and not production_runner:
            runner_messages.append(
                {"role": "human",
                 "content": log.runner_context(spec, "", 1, HUNT_POD_MAX_ITERS)})
        return {
            "log": log, "root_spec": spec, "spec": spec,
            "init_validation": violations, "iteration": 1,
            "current_variant_ref": "v0", "feedback": "",
            "runner_messages": _dicts_to_lc(runner_messages),
            "triager_messages": _dicts_to_lc(
                [{"role": "system", "content": TRIAGER_SYSTEM}]),
            "tool_calls": 0, "stretch_obs": 0,
        }

    def init_router(state: PodState) -> str:
        # C1: a schema-malformed spec is rejected here with ZERO tool calls.
        return "reject" if state.get("init_validation") else "runner"

    # --- the runner's stretch (production ReAct turn OR contract-tier loop) ----

    async def runner_agent(state: PodState) -> dict:
        spec = state["spec"]
        if production_runner:
            log: ExperimentLog = state["log"]
            mem_key = _root_spec_id(state, spec_id) if memory_store is not None else (spec_id or "")
            delta = _dicts_to_lc([{"role": "human",
                                   "content": compose_runner_delta(
                                       log, spec, state.get("feedback", ""),
                                       state.get("iteration", 1), HUNT_POD_MAX_ITERS,
                                       store=memory_store,
                                       spec_id=mem_key)}])
            before_obs = len(log.raw_observations)
            before_exec = len(log.executed)
            # D84-7: the graph owns the pod-session binding - the `pod_runner`
            # session + the run's compaction middleware + the harness context
            # reach the production default seam out-of-band.
            with bind_pod_session(state.get("run_id") or POD_DEFAULT_RUN_ID, "",
                                  state.get("root_spec") or spec,
                                  role_id=POD_RUNNER_ROLE,
                                  middleware=runner_middleware,
                                  harness=_harness_ctx(
                                      state, exec_fn=exec_fn, kb_fn=kb_fn,
                                      memory_store=memory_store,
                                      model_factory=model_factory,
                                      spec_id=spec_id)):
                step = await _await_seam(runner_step_fn, spec, delta,
                                         state.get("tool_calls", 0))
            if not isinstance(step, RunnerStep):
                try:
                    step = RunnerStep(**step) if isinstance(step, dict) else RunnerStep()
                except Exception:  # noqa: BLE001
                    step = RunnerStep(action="conclude", exhausted=True,
                                      observation_note="malformed runner turn")
            obs_added = len(log.raw_observations) - before_obs
            return {
                "pending_step": step.model_dump(),
                # D84-11: the consumed inbox delta is deleted on consumption
                # (the state update is atomic with the seam call).
                "feedback": "",
                "tool_calls": state.get("tool_calls", 0)
                    + (len(log.executed) - before_exec),
                "stretch_obs": state.get("stretch_obs", 0) + obs_added,
                "last_observation": (log.raw_observations[-1].model_dump()
                                     if log.raw_observations else None),
                # D84-4: deposit ONLY the consumed delta; `add_messages` merges.
                "runner_messages": delta,
            }
        # --- the contract-tier lane (injected sync proposers) ------------------
        msgs = state.get("runner_messages", [])
        with bind_pod_session(state.get("run_id") or POD_DEFAULT_RUN_ID, "", spec,
                              role_id=POD_RUNNER_ROLE, middleware=runner_middleware):
            step = await _await_seam(runner_step_fn, spec,
                                     _curated(msgs),
                                     state.get("tool_calls", 0))
        if not isinstance(step, RunnerStep):
            try:
                step = RunnerStep(**step) if isinstance(step, dict) else RunnerStep()
            except Exception:  # noqa: BLE001
                step = RunnerStep(action="conclude", exhausted=True,
                                  observation_note="malformed runner step")
        ai = (f"thought: {step.thought}\naction: {step.action} "
              f"{step.tool} {step.command}{step.kb_query}").strip()
        # D84-4: deposit ONLY the turn's new messages - `add_messages` merges
        # them onto the channel (never the replacement list).
        return {"pending_step": step.model_dump(),
                "runner_messages": _dicts_to_lc([{"role": "ai", "content": ai}])}

    def runner_router(state: PodState) -> str:
        step = _step(state)
        if step.infeasible:
            return "infeasible"
        if step.exhausted:
            return "exhausted"
        # G1: the inner cap forces a conclusion once the stretch budget is spent
        # (the contract-tier lane only; the production harness enforces its own).
        if step.action == "tool_call" and state.get("tool_calls", 0) < HUNT_POD_MAX_TOOL_CALLS:
            return "tool"
        # A conclusion with no observation this stretch is an empty probe.
        if step.action == "conclude" and state.get("stretch_obs", 0) == 0:
            return "exhausted"
        return "triager"

    async def tool_exec(state: PodState) -> dict:
        # Contract-tier lane only (G2/G4): the HARNESS executes and records; the
        # injected runner only proposed.
        log: ExperimentLog = state["log"]
        step = _step(state)
        tc = state.get("tool_calls", 0) + 1  # count every call (dedup included) for G1
        variant_ref = state.get("current_variant_ref", "v0")

        if step.tool == "kb_retrieve":
            try:
                kb = await _await_seam(kb_fn, step.kb_query)
            except Exception as exc:  # noqa: BLE001 - fail-open KB
                kb = {"error": str(exc)}
            return {"tool_calls": tc,
                    "runner_messages": _dicts_to_lc(
                        [{"role": "tool", "content": f"KB RESULT: {kb}"}])}

        command = step.command.strip()
        if not command:  # G2: reject a malformed tool call, do not execute
            return {"tool_calls": tc,
                    "runner_messages": _dicts_to_lc(
                        [{"role": "tool",
                          "content": "TOOL ERROR: empty command rejected"}])}

        sig = _command_signature(variant_ref, command)
        if log.has_executed(sig):  # O7/C10: one execution per identical probe
            return {"tool_calls": tc,
                    "runner_messages": _dicts_to_lc(
                        [{"role": "tool",
                          "content": "TOOL RESULT: (already executed; deduped)"}])}

        result, _attempts = await run_with_retry(exec_fn, command,
                                                 timeout_s=EXEC_TIMEOUT_S,
                                                 max_iters=MAX_POD_ITERS)
        parsed = parse_curl(result)
        observation = RawObservation(
            probe_ref=sig, variant_ref=variant_ref, request={"command": command},
            status=parsed.get("status"), body=parsed.get("body", "") or result.stdout,
            stdout=result.stdout, stderr=result.stderr, returncode=result.returncode,
            duration_ms=result.duration_ms or parsed.get("time_ms", 0))
        log.mark_executed(sig)
        log.record_observation(observation)
        result_text = (f"TOOL RESULT: status={observation.status} "
                       f"body={observation.body[:400]!r} stderr={observation.stderr[:200]!r}")
        return {"tool_calls": tc, "stretch_obs": state.get("stretch_obs", 0) + 1,
                "last_observation": observation.model_dump(),
                "runner_messages": _dicts_to_lc(
                    [{"role": "tool", "content": result_text}])}

    # --- the critic ------------------------------------------------------------

    async def triager(state: PodState) -> dict:
        log: ExperimentLog = state["log"]
        spec = state["spec"]
        obs = RawObservation(**state["last_observation"]) if state.get("last_observation") \
            else RawObservation()
        symptoms = [str(s) for s in (spec.get("verification_symptoms", []) or [])]
        symbolic = evaluate_symptom(symptoms, obs)
        if production_triager:
            # D84-23: the delta = the verbatim P3 note + the filtered context +
            # the memory guidance + variant_refs; the thread holds the history,
            # so only the delta is new_messages (D84-11).
            human = {"role": "human", "content": compose_triager_delta(
                log, spec, obs, store=memory_store,
                spec_id=(_root_spec_id(state, spec_id)
                         if memory_store is not None else (spec_id or "")),
                order=_variant_order(state))}
            seam_view = [human]
        else:
            human = {"role": "human", "content": log.triager_context(spec, obs)}
            seam_view = _curated(state.get("triager_messages", [])) + [human]
        decision: dict = {}

        if symbolic == SYMPTOM_CONFIRMED_CLASS:
            decision = {"classification": SYMPTOM_CONFIRMED_CLASS, "action": "terminate",
                        "verdict": "successful", "terminal_reason": SYMPTOM_CONFIRMED,
                        "clean": True, "note": "verification symptom observed (symbolic)"}
        elif symbolic == INFEASIBILITY_SIGNAL_CLASS:
            decision = {"classification": INFEASIBILITY_SIGNAL_CLASS, "action": "terminate",
                        "verdict": "unsuccessful", "terminal_reason": TECHNICAL_INFEASIBILITY,
                        "clean": False, "note": "no response captured (symbolic infeasibility)"}
        else:
            # D84-7: the `pod_triager` session binding, same shape as the
            # runner's - the graph owns the per-instance session address.
            with bind_pod_session(state.get("run_id") or POD_DEFAULT_RUN_ID, "",
                                  state.get("root_spec") or spec,
                                  role_id=POD_TRIAGER_ROLE,
                                  middleware=triager_middleware,
                                  harness=_harness_ctx(
                                      state, exec_fn=exec_fn, kb_fn=kb_fn,
                                      memory_store=memory_store,
                                       model_factory=model_factory,
                                       spec_id=spec_id)):
                raw = await _await_seam(triager_fn, spec, obs, seam_view, log)
            decision = raw if isinstance(raw, dict) else {}
            if decision.get("action") == "terminate":
                violations = validate_decision({"verdict": decision.get("verdict"),
                                                "terminal_reason": decision.get("terminal_reason"),
                                                "clean": decision.get("clean")})
                if violations:  # G3: a malformed terminal degrades to a safe honest end
                    decision = {"classification": decision.get("classification", "noise"),
                                "action": "terminate", "verdict": "unsuccessful",
                                "terminal_reason": NO_SYMPTOM_EVIDENCE, "clean": False,
                                "note": "triager decision malformed; degraded (" +
                                        "; ".join(violations) + ")"}
            elif decision.get("action") != "variant":
                decision = {"classification": decision.get("classification", "noise"),
                            "action": "terminate", "verdict": "unsuccessful",
                            "terminal_reason": NO_SYMPTOM_EVIDENCE, "clean": False,
                            "note": "triager action missing; degraded"}

        log.record_interpretation(Interpretation(
            variant=state.get("current_variant_ref", "v0"),
            classification=decision.get("classification", ""), note=decision.get("note", "")))
        # D84-4: deposit ONLY this lap's new messages (the context turn + the
        # decision turn); `add_messages` merges them onto the triager channel.
        return {"decision": decision,
                "triager_messages": _dicts_to_lc(
                    [human, {"role": "ai", "content": str(decision)}])}

    def decide_router(state: PodState) -> str:
        decision = state.get("decision", {})
        if decision.get("action") != "variant":
            return "terminal"
        # G1 outer cap: after the critic, before the next runner stretch.
        if state.get("iteration", 0) >= HUNT_POD_MAX_ITERS:
            return "budget"
        return "variant"

    def mint_variant(state: PodState) -> dict:
        log: ExperimentLog = state["log"]
        decision = state["decision"]
        parent_ref = state.get("current_variant_ref", "v0")
        ref = f"v{len(log.variant_specs)}"
        variant_spec = decision.get("variant_spec") or dict(state["spec"])
        log.record_variant(VariantSpec(ref=ref, parent_ref=parent_ref,
                                       declined_attribute=decision.get("declined_attribute", ""),
                                       spec=variant_spec))
        iteration = state.get("iteration", 1) + 1
        out = {"current_variant_ref": ref, "spec": variant_spec, "iteration": iteration,
               "tool_calls": 0, "stretch_obs": 0,
               "feedback": decision.get("feedback", "")}
        if production_runner:
            # The runner_agent node composes the next lap's delta on entry and
            # clears the inbox on consumption (D84-9/11) - no deposit here.
            return out
        opener = log.runner_context(variant_spec, decision.get("feedback", ""),
                                    iteration, HUNT_POD_MAX_ITERS)
        return {**out, "runner_messages": _dicts_to_lc(
            [{"role": "human", "content": opener}])}

    # --- terminals -------------------------------------------------------------

    def terminal(state: PodState) -> dict:
        init_v = state.get("init_validation") or []
        if init_v:
            return _export(state, verdict="unsuccessful", reason=TECHNICAL_INFEASIBILITY,
                           clean=False, init_validation=init_v)
        decision = state.get("decision", {})
        clean = decision.get("clean") if isinstance(decision.get("clean"), bool) \
            else _clean_from_trail(state["log"])
        return _export(state, verdict=decision.get("verdict", "unsuccessful"),
                       reason=decision.get("terminal_reason", SPACE_EXHAUSTED), clean=clean)

    def infeasible_terminal(state: PodState) -> dict:
        # The runner's INIT-gate Phase-1 rejection: assumptions the evidence
        # contradicts, with the feasibility probes already in the trail.
        step = _step(state)
        unverified = step.unverified or ["load-bearing assumptions could not be verified"]
        return _export(state, verdict="unsuccessful", reason=TECHNICAL_INFEASIBILITY,
                       clean=False, init_validation=unverified)

    def exhausted_terminal(state: PodState) -> dict:
        clean = _clean_from_trail(state["log"])
        return _export(state, verdict="unsuccessful",
                       reason=SPACE_EXHAUSTED if clean else NO_SYMPTOM_EVIDENCE, clean=clean)

    def budget_terminal(state: PodState) -> dict:
        return _export(state, verdict="unsuccessful", reason=BUDGET_TIMEOUT, clean=False)

    g = StateGraph(PodState)
    for name, fn in [("init", init), ("runner_agent", runner_agent),
                     ("triager", triager), ("mint_variant", mint_variant),
                     ("terminal", terminal), ("infeasible_terminal", infeasible_terminal),
                     ("exhausted_terminal", exhausted_terminal),
                     ("budget_terminal", budget_terminal)]:
        g.add_node(name, fn)

    g.add_edge(START, "init")
    g.add_conditional_edges("init", init_router,
                            {"reject": "terminal", "runner": "runner_agent"})
    if production_runner:
        # D84-29: the ReAct tool-call loop lives INSIDE `create_agent` - the
        # `tool_exec` node is NOT registered for the production lane. The harness
        # middleware owns G1/G4/O7 (D84-22).
        g.add_conditional_edges("runner_agent", runner_router,
                                {"triager": "triager",
                                 "exhausted": "exhausted_terminal",
                                 "infeasible": "infeasible_terminal"})
    else:
        g.add_node("tool_exec", tool_exec)
        g.add_conditional_edges("runner_agent", runner_router,
                                {"tool": "tool_exec", "triager": "triager",
                                 "exhausted": "exhausted_terminal",
                                 "infeasible": "infeasible_terminal"})
        g.add_edge("tool_exec", "runner_agent")
    g.add_conditional_edges("triager", decide_router,
                            {"terminal": "terminal", "variant": "mint_variant",
                             "budget": "budget_terminal"})
    g.add_edge("mint_variant", "runner_agent")
    for t in ("terminal", "infeasible_terminal", "exhausted_terminal", "budget_terminal"):
        g.add_edge(t, END)
    return g.compile()


# The recursion backstop: outer laps x (inner tool loop x 2 + triager/decide),
# plus slack for init and the terminals.
RECURSION_LIMIT = HUNT_POD_MAX_ITERS * (HUNT_POD_MAX_TOOL_CALLS * 2 + 4) + 12