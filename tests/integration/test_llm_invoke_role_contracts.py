"""Contract predicates (integration tier) for the `invoke_role` negotiation
seam (#99, ADR A1, ticket #146): the negotiated method must survive the REAL
`with_structured_output` conversion boundary and reach the wire exactly as the
unit tier proved in the negotiation.

The unit tier (`tests/test_llm_roles.py`) stubs `build_chat_model`, so it pins
the CONSTRUCTION the seam requests, not the PROVIDER PAYLOAD. This tier closes
that gap with the recording-transport pattern of
`tests/test_llm_structured_output_pin.py`: a ChatOpenAI on the pinned
langchain-openai (1.3.2) talking to an httpx MockTransport that records the
request body, driven by `invoke_role`'s real escalating wrapper against the
real model. No live provider, no gateway, no database (CODING_STANDARD
sections 6, 10): the capability profile is injected and the transport is
canned. Verifier-gated; not selected by the tdd unit loop.

Proven end to end:

- a json_schema-capable profile (the deepseek/thinking class, A1 rung 1)
  yields `response_format` of type json_schema with `"strict": false` through
  the DICT construction form (the A4 pin contract) and no forced tool_choice;
- a tool-calling-only profile (A1 rung 2) yields a forced `tool_choice` naming
  the schema tool, with no response_format.

RED on purpose if a langchain-openai bump moves either conversion boundary.
"""
import json

import httpx
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from polymerhus.app.llm import roles
from polymerhus.app.llm.capability import CapabilityProfile


class _Closed(BaseModel):
    label: str


class _OpenDict(BaseModel):
    """The vLLM/Qwen/Apertus-style open-dict schema (root `dict` = free-form
    JSON object) - the exact field class `Observation.anchor` is."""

    anchor: dict
    label: str


_PINNED = (1, 3, 2)


def _env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_TRIAGER", "openrouter:some/model")
    # ONE escalating attempt per logical call, so exactly one wire payload is
    # recorded per invoke - the seek is the wire proof, not the retry schedule.
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "5")


def _inject(monkeypatch, profile):
    """Inject the held profile and route every `build_chat_model` call to a
    REAL pinned ChatOpenAI on a recording transport; returns the recorded
    request bodies. `invoke_role`'s parse-validation / escalating wrapper may
    absorb the canned completion - only the REQUEST matters for the contract."""
    bodies: list[dict] = []

    def _handler(request):
        bodies.append(json.loads(request.content.decode()))
        return httpx.Response(200, json={
            "id": "cmpl-1", "object": "chat.completion", "created": 1,
            "model": "pinned-model",
            "choices": [{"index": 0, "message": {
                "role": "assistant", "content": "{}", "tool_calls": None},
                "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                      "total_tokens": 2},
        })

    def build_chat_model(*args, **kwargs):
        return ChatOpenAI(
            model="pinned/model",
            api_key="sk-dummy",
            base_url="http://127.0.0.1:1/v1",
            http_client=httpx.Client(transport=httpx.MockTransport(_handler),
                                     base_url="http://127.0.0.1:1/v1"),
        )

    monkeypatch.setattr(roles, "resolve_capability",
                        lambda provider, model: profile)
    monkeypatch.setattr(roles, "build_chat_model", build_chat_model)
    return bodies


# --- A1 rung 1: json_schema-capable profile -----------------------------------

def test_invoke_role_json_schema_profile_reaches_wire_strict_false_dict_form(monkeypatch):
    """The A4 pin contract, proven through the real seam: a json_schema-capable
    profile negotiates `json_schema` and the DICT construction reaches the
    provider as `response_format` with `"strict": false` - the construction
    that does NOT 400 on an open-dict field (#44) - and no forced
    tool_choice / tools. RED on purpose if a bump changes the dict path."""
    import langchain_openai
    assert tuple(int(p) for p in langchain_openai.__version__.split(".")) == _PINNED
    _env(monkeypatch)
    bodies = _inject(monkeypatch, CapabilityProfile(supports_structured_output=True))
    roles.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_Closed)
    (wire,) = bodies
    rf = wire["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is False
    assert "tool_choice" not in wire or wire["tool_choice"] is None
    assert "tools" not in wire
    assert "label" in rf["json_schema"]["schema"]["properties"]  # the dict form


# --- A1 rung 2: tool-calling-only profile -------------------------------------

def test_invoke_role_tool_only_profile_reaches_wire_as_forced_tool_choice(monkeypatch):
    """The proven-mainline degrade, proven through the real seam: a
    tool-calling-only profile negotiates `function_calling` and the class-form
    construction reaches the provider as a forced `tool_choice` naming the
    schema tool - the ONLY wire form a tool loop tolerates - with no
    response_format. RED on purpose if the pin moves the construction."""
    _env(monkeypatch)
    bodies = _inject(monkeypatch, CapabilityProfile(supports_tool_calling=True))
    roles.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_OpenDict)
    (wire,) = bodies
    assert "response_format" not in wire
    assert wire["tool_choice"] == {
        "type": "function", "function": {"name": _OpenDict.__name__}}
    assert isinstance(wire["tools"], list) and wire["tools"]
    assert wire["tools"][0]["function"]["name"] == _OpenDict.__name__