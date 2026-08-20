"""Unit tier: the SDK-pin behavior tests for the method negotiation (#99, ADR
A4, ticket #145).

`requirements-app.txt` pins EXACT `langchain-openai==1.3.2` (and `langgraph` /
`langchain` / `langchain-core` at the resolved lock) because the negotiation
relies on `with_structured_output` semantics that have silently changed across
SDK bumps (0.3.12 vs 0.3.21 - a floor-bound is not a pin). These tests exercise
`with_structured_output` through the REAL conversion boundary - a ChatOpenAI on
the pinned version talking to a recording httpx transport - and assert the WIRE
payload each negotiated rung produces: the chosen method must survive the
langchain/openai conversion boundary and reach the provider as proven in the
negotiation (the exact defect class of #99).

Load-bearing findings locked here (verified on the 1.3.2 pin):

- `method="json_schema"` + a PYDANTIC CLASS schema + `strict=False` silently
  reaches the wire as `"strict": true` (1.3.2's class path ignores the strict
  kwarg and defaults to strict). An OPEN-dict schema (Observation.anchor) under
  strict=true is exactly the 400 the negotiation exists to avoid (#44), so the
  construction seam must pass the schema as a DICT - which honors `strict: false`
  on the wire. A bump that changes either path turns these tests red on purpose.
- `method="json_schema"` uses `response_format` and never forces `tool_choice`
  (thinking models accept `response_format`; A1 rung 1).
- `method="function_calling"` forces `tool_choice` + `tools` (A1 rung 2 - the
  only tool-loop option).
- `method="json_mode"` sets `response_format={"type": "json_object"}` (the
  #44-absorbed last rung).

No live model, no live gateway, no database: the transport is an `httpx`
MockTransport that answers a canned completion and records the request body -
the unit tier touches neither (CODING_STANDARD sections 6, 10).
"""
import json

import httpx
from pydantic import BaseModel
from langchain_openai import ChatOpenAI

# The vLLM/Qwen/Apertus-style open-dict schema (root `dict` = free-form JSON
# object) - the exact field class `Observation.anchor` is (`types.py:23`).
class _OpenDict(BaseModel):
    anchor: dict
    label: str


_PINNED = (1, 3, 2)


def _langchain_openai_version_tuple() -> tuple[int, ...]:
    import langchain_openai
    return tuple(int(p) for p in langchain_openai.__version__.split("."))


def _wire(model_class, method, *, strict=False):
    """Run one `with_structured_output` call on the PINNED SDK through a
    recording transport and return the request body the provider would receive.

    The pinned client is constructed in BOTH dict-schema and pydantic-class
    forms and the captured body returned keyed by schema form; the response is a
    canned completion (the structured-output parsers may raise on the canned
    shape - only the REQUEST matters for the pin)."""
    captured: dict[str, dict] = {}

    def _send(schema):
        bodies = []

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

        transport = httpx.MockTransport(_handler)
        model = ChatOpenAI(
            model="pinned/model",
            api_key="sk-dummy",
            base_url="http://127.0.0.1:1/v1",
            http_client=httpx.Client(transport=transport,
                                     base_url="http://127.0.0.1:1/v1"),
        )
        if method == "json_schema":
            structured = model.with_structured_output(
                schema, method=method, strict=strict)
        else:
            structured = model.with_structured_output(schema, method=method)
        try:
            structured.invoke([{"role": "user", "content": "hi"}])
        except Exception:  # noqa: BLE001 - the wire payload is the assertion target
            pass
        return bodies[0]

    captured["dict"] = _send(model_class.model_json_schema())
    captured["class"] = _send(model_class)
    return captured


# ---------------------------------------------------------------------------
# json_schema rung (A1 rung 1: response_format, strict=False, no tool_choice) -
# ---------------------------------------------------------------------------

def test_pin_json_schema_dict_schema_reaches_wire_strict_false():
    """The construction the negotiation needs: a DICT schema + `strict=False`
    reaches the provider as `response_format` of type json_schema with
    `"strict": false`, and NO forced `tool_choice` / `tools` - thinking models
    accept `response_format` (the deepseek 400 story of #99). RED on purpose if
    a bump changes the dict path."""
    assert _langchain_openai_version_tuple() == _PINNED
    wire = _wire(_OpenDict, "json_schema", strict=False)["dict"]
    rf = wire["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is False
    assert "tool_choice" not in wire or wire["tool_choice"] is None
    assert "tools" not in wire
    anchor = rf["json_schema"]["schema"]["properties"]["anchor"]
    assert anchor["type"] == "object"
    assert anchor.get("additionalProperties") is True  # the open-dict tolerance


def test_pin_json_schema_pydantic_class_path_silently_defaults_strict_true():
    """1.3.2 load-bearing trap: `strict=False` with a PYDANTIC-CLASS schema does
    NOT reach the wire - the class path defaults to `"strict": true`, which 400s
    on open-dict schemas (#44). The construction seam MUST pass the schema as a
    dict. RED on purpose if a bump honors strict on the class path (the trap
    closes) OR drops the dict path."""
    wire = _wire(_OpenDict, "json_schema", strict=False)["class"]
    assert wire["response_format"]["type"] == "json_schema"
    assert wire["response_format"]["json_schema"]["strict"] is True


# ---------------------------------------------------------------------------
# function_calling rung (A1 rung 2: forced tool choice, no method-swap) ------
# ---------------------------------------------------------------------------

def test_pin_function_calling_forces_tool_choice():
    """The tool-loop rung reaches the wire as a forced tool call: `tool_choice`
    naming the schema tool + the `tools` array, no `response_format`. This is
    the ONLY wire form a tool loop tolerates - a silent method-swap inside a
    tool loop would break the T5 gate contract. RED on purpose if the pin moves
    the function_calling construction."""
    wire = _wire(_OpenDict, "function_calling")["class"]
    assert "response_format" not in wire
    assert wire["tool_choice"] == {
        "type": "function", "function": {"name": _OpenDict.__name__}}
    assert isinstance(wire["tools"], list) and wire["tools"]
    assert wire["tools"][0]["function"]["name"] == _OpenDict.__name__


# ---------------------------------------------------------------------------
# json_mode rung (A1 chain end: response_format json_object) -----------------
# ---------------------------------------------------------------------------

def test_pin_json_mode_sets_json_object_response_format():
    """The last degrade rung reaches the wire as `response_format` of type
    `json_object` with no forced tools - the parse-validation contract then
    guards the shape (#44's silent-wrong-shape failure). RED on purpose if a
    bump changes the json_mode construction."""
    wire = _wire(_OpenDict, "json_mode")["class"]
    assert wire["response_format"] == {"type": "json_object"}
    assert "tools" not in wire