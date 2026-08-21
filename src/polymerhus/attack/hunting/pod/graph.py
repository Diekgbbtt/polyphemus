"""The pod's looped state machine (D67-06) as a LangGraph StateGraph, with the
runner driving the execution stretch as an agentic tool-calling loop.

Inversion of control (operator, 2026-08-06): the RUNNER is the control plane of
the probe stretch - it proposes one step at a time, sees each tool result, and
adjusts the kill chain (intra-chain data flow + decision blocks). The HARNESS
owns the loop and GUARANTEES boundedness and the contract:

  G1 termination - the inner loop is capped at `HUNT_POD_MAX_TOOL_CALLS` tool
     calls per stretch (`runner_router`), the outer loop at `HUNT_POD_MAX_ITERS`
     stretches (`decide_router`); LangGraph's recursion limit is the backstop.
  G2 safety      - `tool_exec` validates every proposed call and bounds each exec
     by `EXEC_TIMEOUT_S` / `MAX_POD_ITERS`; a malformed call is rejected, not run.
  G3 contract    - only the triager + terminal nodes assign the verdict and the
     terminal_reason; the runner never touches the terminal vocabulary.
  G4 honesty     - every tool result is recorded RAW in the experiment log (D6)
     before curation; curation only bounds what the AGENT sees, never the export.
  G5 fail-open   - a raising collaborator degrades to a terminal with the partial
     trail; nothing raises past `arun_pod`.

The FSM:

  INIT-schema (deterministic gate; C1: reject with no tool call)
    -> runner_agent  <->  tool_exec           (the runner's bounded agentic loop)
           |  conclude / exhausted / infeasible
    -> triager (symbolic fast-path, else the critic classifies + decides)
    -> decide  -> {terminal | mine variant -> [POD-BUDGET CHECK] -> runner_agent
                   | budget_terminal}
    -> TERMINAL (render the D5 + D6 envelope)

The pod is ASYNC-NATIVE (D84-15, Q7): the nodes that call injected seams
(`runner_agent`, `tool_exec`, `triager`) are `async def` and ride every
collaborator call through `_await_seam` - an async seam is awaited natively, a
sync seam is offloaded via `asyncio.to_thread` (the `_await_seam` pattern
mirrors `hunt_orchestrator.py` / `hunting_agent.py`). The graph is driven with
`ainvoke`; the deterministic nodes (init, the routers, mint_variant, the
terminals) stay sync - LangGraph 1.x mixes them under `ainvoke`.

`build_pod_graph` injects every side-effecting collaborator so the contract tier
runs without a live target, a live LLM, or the downstream agents.
"""
from __future__ import annotations

import asyncio
import hashlib
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
from polymerhus.attack.hunting.pod.context import ExperimentLog, curate_messages
from polymerhus.attack.hunting.pod.llm import (
    POD_DEFAULT_RUN_ID,
    POD_RUNNER_ROLE,
    POD_TRIAGER_ROLE,
    bind_pod_session,
)
from polymerhus.attack.hunting.pod.symbolic import evaluate_symptom
from polymerhus.attack.hunting.pod.tools import parse_curl, run_with_retry
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


def _append(msgs: list, role: str, content: str) -> list:
    return list(msgs or []) + [{"role": role, "content": content}]


def _command_signature(variant_ref: str, command: str) -> str:
    blob = f"{variant_ref}\x00{command}".encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


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


def build_pod_graph(*, exec_fn, runner_step_fn=None, triager_fn=None, kb_fn=None):
    """Compile the pod subgraph, injecting the side-effecting collaborators:

    - `exec_fn(command, timeout_s) -> ExecResult` - the terminal (required).
    - `runner_step_fn(spec, messages, tool_calls) -> RunnerStep` - the
      actor's next-step proposer over its curated session; default = the
      `pod_runner` session with a symbolic fallback.
    - `triager_fn(spec, observation, messages, log) -> decision` - the critic
      over its curated session; consulted only when the symbolic recogniser is
      inconclusive.
    - `kb_fn(query) -> dict` - the NL knowledge-base tool; default = the fail-open
      `kb_retrieve` stub.
    """
    runner_step_fn = runner_step_fn if runner_step_fn is not None else default_runner_step_fn
    triager_fn = triager_fn if triager_fn is not None else default_triager_fn
    if kb_fn is None:
        from polymerhus.attack.hunting.pod.tools import kb_retrieve
        kb_fn = kb_retrieve

    def init(state: PodState) -> dict:
        spec = dict(state["spec"])
        log = ExperimentLog()
        log.record_variant(VariantSpec(ref="v0", parent_ref=None, spec=spec))
        violations = validate_spec(spec)
        runner_messages = [{"role": "system", "content": RUNNER_SYSTEM}]
        if not violations:
            runner_messages = _append(
                runner_messages, "human",
                log.runner_context(spec, "", 1, HUNT_POD_MAX_ITERS))
        return {
            "log": log, "root_spec": spec, "spec": spec,
            "init_validation": violations, "iteration": 1,
            "current_variant_ref": "v0", "feedback": "",
            "runner_messages": runner_messages,
            "triager_messages": [{"role": "system", "content": TRIAGER_SYSTEM}],
            "tool_calls": 0, "stretch_obs": 0,
        }

    def init_router(state: PodState) -> str:
        # C1: a schema-malformed spec is rejected here with ZERO tool calls.
        return "reject" if state.get("init_validation") else "runner"

    # --- the runner's agentic loop (the runner is the control plane) -----------

    async def runner_agent(state: PodState) -> dict:
        msgs = state.get("runner_messages", [])
        spec = state["spec"]
        # D84-7: the graph owns the pod-session binding - the `pod_runner`
        # session becomes the typed address the default seam reads (derived from
        # the parent hunt_session when present; a directly-invoked pod runs on
        # the task-local default run_id with no hunt_id).
        with bind_pod_session(state.get("run_id") or POD_DEFAULT_RUN_ID, "", spec,
                              role_id=POD_RUNNER_ROLE):
            step = await _await_seam(runner_step_fn, spec, curate_messages(msgs),
                                     state.get("tool_calls", 0))
        if not isinstance(step, RunnerStep):
            try:
                step = RunnerStep(**step) if isinstance(step, dict) else RunnerStep()
            except Exception:  # noqa: BLE001
                step = RunnerStep(action="conclude", exhausted=True,
                                  observation_note="malformed runner step")
        ai = (f"thought: {step.thought}\naction: {step.action} "
              f"{step.tool} {step.command}{step.kb_query}").strip()
        return {"pending_step": step.model_dump(),
                "runner_messages": _append(msgs, "ai", ai)}

    def runner_router(state: PodState) -> str:
        step = _step(state)
        if step.infeasible:
            return "infeasible"
        if step.exhausted:
            return "exhausted"
        # G1: the inner cap forces a conclusion once the stretch budget is spent.
        if step.action == "tool_call" and state.get("tool_calls", 0) < HUNT_POD_MAX_TOOL_CALLS:
            return "tool"
        # A conclusion with no observation this stretch is an empty probe.
        if step.action == "conclude" and state.get("stretch_obs", 0) == 0:
            return "exhausted"
        return "triager"

    async def tool_exec(state: PodState) -> dict:
        # G2/G4: the HARNESS executes and records; the runner only proposed.
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
                    "runner_messages": _append(state.get("runner_messages", []),
                                               "tool", f"KB RESULT: {kb}")}

        command = step.command.strip()
        if not command:  # G2: reject a malformed tool call, do not execute
            return {"tool_calls": tc,
                    "runner_messages": _append(state.get("runner_messages", []),
                                               "tool", "TOOL ERROR: empty command rejected")}

        sig = _command_signature(variant_ref, command)
        if log.has_executed(sig):  # O7/C10: one execution per identical probe
            return {"tool_calls": tc,
                    "runner_messages": _append(state.get("runner_messages", []),
                                               "tool", "TOOL RESULT: (already executed; deduped)")}

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
                "runner_messages": _append(state.get("runner_messages", []), "tool", result_text)}

    # --- the critic ------------------------------------------------------------

    async def triager(state: PodState) -> dict:
        log: ExperimentLog = state["log"]
        spec = state["spec"]
        obs = RawObservation(**state["last_observation"]) if state.get("last_observation") \
            else RawObservation()
        symptoms = [str(s) for s in (spec.get("verification_symptoms", []) or [])]
        symbolic = evaluate_symptom(symptoms, obs)
        tmsgs = _append(state.get("triager_messages", []), "human",
                        log.triager_context(spec, obs))

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
            with bind_pod_session(state.get("run_id") or POD_DEFAULT_RUN_ID, "", spec,
                                  role_id=POD_TRIAGER_ROLE):
                raw = await _await_seam(triager_fn, spec, obs, curate_messages(tmsgs), log)
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
            tmsgs = _append(tmsgs, "ai", str(decision))

        log.record_interpretation(Interpretation(
            variant=state.get("current_variant_ref", "v0"),
            classification=decision.get("classification", ""), note=decision.get("note", "")))
        return {"decision": decision, "triager_messages": tmsgs}

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
        opener = log.runner_context(variant_spec, decision.get("feedback", ""),
                                    iteration, HUNT_POD_MAX_ITERS)
        return {"current_variant_ref": ref, "spec": variant_spec, "iteration": iteration,
                "tool_calls": 0, "stretch_obs": 0,
                "feedback": decision.get("feedback", ""),
                "runner_messages": _append(state.get("runner_messages", []), "human", opener)}

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
    for name, fn in [("init", init), ("runner_agent", runner_agent), ("tool_exec", tool_exec),
                     ("triager", triager), ("mint_variant", mint_variant),
                     ("terminal", terminal), ("infeasible_terminal", infeasible_terminal),
                     ("exhausted_terminal", exhausted_terminal),
                     ("budget_terminal", budget_terminal)]:
        g.add_node(name, fn)

    g.add_edge(START, "init")
    g.add_conditional_edges("init", init_router,
                            {"reject": "terminal", "runner": "runner_agent"})
    g.add_conditional_edges("runner_agent", runner_router,
                            {"tool": "tool_exec", "triager": "triager",
                             "exhausted": "exhausted_terminal", "infeasible": "infeasible_terminal"})
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
