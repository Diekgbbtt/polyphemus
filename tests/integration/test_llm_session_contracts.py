"""Contract predicates (integration tier) for the session-seam negotiation
(#99, ADR A1, ticket #147): the negotiated `response_format` must survive the
REAL `create_agent` + `ProviderStrategy`/`ToolStrategy` conversion boundary and
reach the provider exactly as the unit tier proved in the negotiation.

The unit tier (`tests/test_llm_session.py`) stubs `run_session_turn`, so it pins
the CONSTRUCTION the seam requests, not the PROVIDER PAYLOAD. This tier closes
that gap with the recording-transport pattern of
`tests/test_llm_structured_output_pin.py`: a ChatOpenAI on the pinned
langchain-openai (1.3.2) talking to an httpx MockTransport that records the
request body, driven through the REAL `create_agent` path. No live provider, no
gateway, no database (CODING_STANDARD sections 6, 10). Verifier-gated; not
selected by the tdd unit loop.

Proven end to end:

- a no-tools structured session turn on a json_schema-capable profile reaches the
  provider as `response_format` of type `json_schema` with `"strict": false`
  (the open-dict-tolerant rung) and returns the parsed pydantic instance;
- the same turn on a tool-calling-only profile reaches the provider as a forced
  `tool_choice` naming the schema tool (the ToolStrategy rung).

RED on purpose if a langchain-openai bump moves either conversion boundary.
"""
import json
import signal

import httpx
from langchain.agents import create_agent
from langchain.agents.structured_output import ProviderStrategy
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

from polymerhus.app.llm import session as S
from polymerhus.app.llm.capability import CapabilityProfile


class _Closed(BaseModel):
    label: str = "x"


class _OpenDict(BaseModel):
    """The vLLM/Qwen/Apertus-style open-dict schema (root `dict` = free-form
    JSON object) - the exact field class `Observation.anchor` is."""

    anchor: dict = {}
    label: str = "y"


_PINNED = (1, 3, 2)


def _env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_TRIAGER", "openrouter:some/model")


class _Recorder:
    """A recording httpx transport that returns a canned completion for the
    given schema, so the agent graph runs to the parsed instance without a live
    provider. When the wire carries a `tools` array (the ToolStrategy rung, which
    forces the model to call the schema tool), the completion emits the matching
    `tool_calls` so the tool loop terminates; otherwise it returns the label as
    plain JSON content (the ProviderStrategy rung)."""

    def __init__(self, label):
        self.bodies = []
        self.label = label

    def handler(self, request):
        body = json.loads(request.content.decode())
        self.bodies.append(body)
        message = {"role": "assistant", "content": None}
        tools = body.get("tools") or []
        if tools:
            name = tools[0]["function"]["name"]
            message["tool_calls"] = [{
                "id": "call_1", "type": "function",
                "function": {"name": name,
                             "arguments": json.dumps({"label": self.label})}}]
        else:
            message["content"] = json.dumps({"label": self.label})
            message["tool_calls"] = None
        return httpx.Response(200, json={
            "id": "cmpl-1", "object": "chat.completion", "created": 1,
            "model": "pinned-model",
            "choices": [{"index": 0, "message": message,
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                      "total_tokens": 2},
        })


def _run_no_tools_session(monkeypatch, profile, schema, expected_label):
    """Inject the profile and drive a REAL stateful session turn (no tools bound)
    against a pinned ChatOpenAI on a recording transport. `signal.alarm` bounds
    the agent graph so a conversion regression fails fast instead of hanging.
    Returns the recorded wire bodies."""
    import langchain_openai
    assert tuple(int(p) for p in langchain_openai.__version__.split(".")) == _PINNED

    recorder = _Recorder(expected_label)
    http = httpx.Client(
        timeout=httpx.Timeout(15, connect=3),
        transport=httpx.MockTransport(recorder.handler))
    monkeypatch.setattr(S, "resolve_capability",
                        lambda provider, model: profile)
    monkeypatch.setenv("LLM_MODEL_TRIAGER", "openrouter:some/model")

    # The REAL negotiation through the REAL create_agent graph.
    response_format = S._structured_response_format("triager", schema)

    def make(role):
        return ChatOpenAI(model="pinned/model", api_key="sk-dummy",
                          base_url="http://127.0.0.1:1/v1",
                          max_retries=0,
                          http_client=http)

    agent = create_agent(make("triager"), tools=[],
                         checkpointer=InMemorySaver(),
                         response_format=response_format)
    signal.alarm(30)
    try:
        result = agent.invoke({"messages": [HumanMessage(content="hi")]},
                              {"configurable": {"thread_id": "t"}})
    finally:
        signal.alarm(0)
    structured = result.get("structured_response")
    assert structured is not None
    assert getattr(structured, "label", None) == expected_label
    return recorder.bodies


# --- A1 session rung 1: json_schema-capable profile ---------------------------

def test_session_json_schema_profile_reaches_wire_strict_false(monkeypatch):
    """A no-tools structured session turn on a json_schema-capable profile
    reaches the provider as `response_format` of type json_schema with
    `"strict": false` (the open-dict-tolerant rung) and returns the parsed
    pydantic instance. RED on purpose if the pin moves the conversion."""
    bodies = _run_no_tools_session(
        monkeypatch, CapabilityProfile(supports_structured_output=True),
        _OpenDict, expected_label="y")
    (wire,) = bodies
    rf = wire["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is False


# --- A1 session rung 2: tool-calling-only profile -----------------------------

def test_session_tool_only_profile_reaches_wire_as_forced_tool_choice(monkeypatch):
    """A tool-calling-only profile negotiates `ToolStrategy` and the schema tool
    reaches the provider in the `tools` array naming the schema tool (the proven
    force-tool rung) and returns the parsed instance. RED on purpose if the pin
    moves the construction."""
    bodies = _run_no_tools_session(
        monkeypatch, CapabilityProfile(supports_tool_calling=True),
        _Closed, expected_label="x")
    (wire,) = bodies
    assert "response_format" not in wire
    assert isinstance(wire.get("tools"), list) and wire["tools"]
    assert wire["tools"][0]["function"]["name"] == _Closed.__name__