"""The two pod agents as curated, semi-stateful sessions (operator, 2026-08-06).

The `pod_runner` (actor) is the control plane of the probe stretch: it drives an
agentic tool-calling loop, proposing ONE step at a time (a tool call, or a
conclusion) and seeing each tool's result before its next step - so it reflects
on the intra-chain data flow, adjusts the kill chain, and branches (decision
blocks). The `pod_triager` (critic) reads the stretch's evidence and decides.

Both are semi-stateful: their conversation (system prompt + reasoning turns +
curated tool results) lives on the graph state (`runner_messages` /
`triager_messages`) and is curated by the context-management component
(`context.curate_messages`) - reasoning kept, raw tool bodies filtered, the whole
session bounded. Every seam is injectable and resolves its role LAZILY (never a
boot-gate); the contract tier passes stateless fakes and the E1 walkthrough uses
the symbolic runner, so neither the default LLM nor a live LLM is needed to test
the pod.

The GUARANTEE that the runner is the control plane yet the pod stays bounded is
STRUCTURAL and lives in the graph, not here: the harness owns the loop and the
caps (`HUNT_POD_MAX_TOOL_CALLS`), validates every proposed tool call, records
every result in the log, and always renders the binary envelope. The runner
proposes; the harness disposes.
"""
from __future__ import annotations

from typing import Callable, Literal

from pydantic import BaseModel, Field

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


def _to_lc_messages(messages: list[dict]):
    """Convert the curated session (role/content dicts) into LangChain messages."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    out = []
    for m in messages:
        role, content = m.get("role"), m.get("content", "")
        if role == "system":
            out.append(SystemMessage(content=content))
        elif role == "ai":
            out.append(AIMessage(content=content))
        else:  # human, tool
            out.append(HumanMessage(content=content))
    return out


def symbolic_runner_step_fn(spec: dict, messages: list, tool_calls: int) -> RunnerStep:
    """The LLM-free runner: on the first turn of a stretch it issues the default
    probe from the payload vector space (O12/C11), then concludes and hands the
    observation to the critic. Drives E1 and is the fail-open fallback."""
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


def default_runner_step_fn(spec: dict, messages: list, tool_calls: int) -> RunnerStep:
    """Real actor turn: the `pod_runner` session proposes the next step over its
    curated conversation. Resolves the role LAZILY from the bound pod-session
    address (D84-7) when the graph set one, else the `pod_runner` default; on any
    failure it degrades to the symbolic runner (fail-open) so a stretch always
    makes progress."""
    try:
        from polymerhus.app.llm.roles import chat_model_for
        from polymerhus.attack.hunting.pod.llm import POD_RUNNER_ROLE, pod_session

        ctx = pod_session()
        role = ctx.address.role_id if ctx is not None else POD_RUNNER_ROLE
        llm = chat_model_for(role).with_structured_output(
            RunnerStep, method="function_calling")
        result = llm.invoke(_to_lc_messages(messages))
        if result is None:
            raise ValueError("unmet runner generation")
        return result
    except Exception:  # noqa: BLE001 - fail-open: fall back to the symbolic runner
        return symbolic_runner_step_fn(spec, messages, tool_calls)


def default_triager_fn(spec: dict, observation: RawObservation,
                       messages: list, log) -> dict:
    """Real critic turn: the `pod_triager` session classifies the stretch and
    decides over its curated conversation. Resolves the role LAZILY from the
    bound pod-session address (D84-7) when the graph set one, else the
    `pod_triager` default; on an unmet generation it degrades to a safe honest
    terminal rather than raising."""
    try:
        from polymerhus.app.llm.roles import chat_model_for
        from polymerhus.attack.hunting.pod.llm import POD_TRIAGER_ROLE, pod_session

        ctx = pod_session()
        role = ctx.address.role_id if ctx is not None else POD_TRIAGER_ROLE
        llm = chat_model_for(role).with_structured_output(
            TriagerDecision, method="function_calling")
        result = llm.invoke(_to_lc_messages(messages))
        if result is None:
            raise ValueError("unmet triager generation")
        return result.model_dump()
    except Exception as exc:  # noqa: BLE001 - fail-open safe terminal
        return TriagerDecision(
            classification="noise", action="terminate", verdict="unsuccessful",
            terminal_reason="no-symptom-evidence", clean=False,
            note=f"triager degraded: {exc}").model_dump()


# Re-exported so the graph and run_pod can name the base prompts.
RUNNER_SYSTEM = POD_RUNNER_SYSTEM
TRIAGER_SYSTEM = POD_TRIAGER_SYSTEM
