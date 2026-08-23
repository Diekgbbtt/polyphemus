"""The pod's ReAct-loop harness middleware (T7, D84-22).

G1 (the per-stretch tool-call cap `HUNT_POD_MAX_TOOL_CALLS`), G4 (the hanging
guarantee that every exec result is recorded RAW in the D6 log), and O7 (the
one-execution-per-identical-probe dedup gate) move HERE, onto the `create_agent`
agent - the tool-call loop lives inside `create_agent`, so the graph's `tool_exec`
node disappears from the production lane.

The middleware owns ONLY the cap + the dedup/malformed-command gates. Tool
ARGUMENT validation is the tool's own contract (`extra="forbid"` args schemas,
D84-22) - a wrong parameter fails as a REJECTED tool call at the pydantic layer;
this middleware never re-validates arguments. RAW execution recording (G4) lives
in the exec tool itself (it holds the full `ExecResult`); this middleware only
counts calls, gates a repeat, and ends the loop at the cap.

Fail-open throughout: a hook that cannot see the state/runtime degrades to a
pass-through, never raises into the loop.
"""
from __future__ import annotations

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import hook_config
from langchain_core.messages import ToolMessage

from polymerhus.attack.hunting.pod.config import HUNT_POD_MAX_TOOL_CALLS
from polymerhus.attack.hunting.pod.tools import command_signature


class _HarnessMiddleware(AgentMiddleware):
    """One stretch's harness: G1 cap + O7 dedup + the empty-command rejection.

    Built per STRETCH (fresh instance per `arun_session_turn`), holding the
    run's D6 log and the CURRENT variant_ref for the dedup signature scope."""

    def __init__(self, *, log, variant_ref: str, cap: int):
        self.log = log
        self.variant_ref = variant_ref
        self.cap = cap
        self.calls = 0   # every attempted call, dedup included (G1, like the old graph)

    @hook_config(can_jump_to=["end"])
    def after_model(self, state, runtime=None):
        """G1: once the stretch's tool-call budget is spent, END the ReAct loop -
        the trail hands to the critic, never an unbounded loop (the old `tool_exec`
        cap's exact semantics, enforced at the middleware layer)."""
        if self.calls >= self.cap:
            return {"jump_to": "end"}
        return None

    @hook_config(can_jump_to=["end"])
    async def aafter_model(self, state, runtime=None):
        """Async twin (the production seams run the agent via ainvoke)."""
        return self.after_model(state, runtime)

    def wrap_tool_call(self, request, handler):
        self.calls += 1
        if request.tool_call.get("name") != "exec":
            return handler(request)
        args = request.tool_call.get("args") or {}
        command = str(args.get("command") or "")
        # G2: a malformed exec call is rejected, not run (the harness gate).
        if not command.strip():
            return ToolMessage(content="TOOL ERROR: empty command rejected",
                               tool_call_id=request.tool_call.get("id") or "",
                               name="exec")
        # O7/C10: one execution per identical probe within the variant.
        if self.log.has_executed(command_signature(self.variant_ref, command)):
            return ToolMessage(content="TOOL RESULT: (already executed; deduped)",
                               tool_call_id=request.tool_call.get("id") or "",
                               name="exec")
        # G4: the exec tool records the raw observation itself.
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        """Async twin of `wrap_tool_call` (the same gates, the handler awaited):
        the production seams run the agent via `arun_session_turn`/`ainvoke`, so
        the middleware must surface the async hook."""
        self.calls += 1
        if request.tool_call.get("name") != "exec":
            return await handler(request)
        args = request.tool_call.get("args") or {}
        command = str(args.get("command") or "")
        if not command.strip():
            return ToolMessage(content="TOOL ERROR: empty command rejected",
                               tool_call_id=request.tool_call.get("id") or "",
                               name="exec")
        if self.log.has_executed(command_signature(self.variant_ref, command)):
            return ToolMessage(content="TOOL RESULT: (already executed; deduped)",
                               tool_call_id=request.tool_call.get("id") or "",
                               name="exec")
        return await handler(request)


def build_harness_middleware(*, log, variant_ref: str,
                             cap: int = HUNT_POD_MAX_TOOL_CALLS) -> _HarnessMiddleware:
    """Build the harness for one ReAct stretch (D84-22): G1 cap / O7 dedup /
    empty-command rejection; tool-contract validation stays with the tools."""
    return _HarnessMiddleware(log=log, variant_ref=variant_ref, cap=cap)