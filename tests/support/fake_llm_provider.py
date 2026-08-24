"""Fake LLM provider for capability-adaptive matrix harness (#99).

Exposes OpenAI-compatible surface + control endpoints for tests to
configure per-model capabilities and inspect wire forwarding.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="fake-llm")

# per-model config: model_name -> {model_info, response_mode}
_CONFIG: dict[str, dict[str, Any]] = {}
# per-model last request JSON
_LAST: dict[str, Any] = {}


@app.get("/models")
def list_models():
    data = [{"id": k, "object": "model"} for k in _CONFIG]
    return {"object": "list", "data": data}


@app.post("/__fake/config")
async def set_config(req: Request):
    body = await req.json()
    model_name = body.get("model_name")
    if not model_name:
        return JSONResponse({"error": "model_name required"}, status_code=400)
    _CONFIG[model_name] = {
        "model_info": body.get("model_info", {}),
        "response_mode": body.get("response_mode", "json_schema"),
    }
    return {"ok": True, "model": model_name}


@app.get("/__fake/last-request")
def last_request(model: str = ""):
    return _LAST.get(model) or {}


@app.post("/__fake/reset")
def reset():
    _CONFIG.clear()
    _LAST.clear()
    return {"ok": True}


@app.get("/model/info")
def model_info():
    # LiteLLM-compatible surface for capability reader
    data = []
    for name, cfg in _CONFIG.items():
        info = dict(cfg.get("model_info", {}))
        data.append({"model_name": name, "model_info": info})
    return {"data": data}


@app.post("/v1/chat/completions")
async def chat_completions(req: Request):
    body = await req.json()
    model = body.get("model", "unknown")
    # record last request per model
    _LAST[model] = body
    cfg = _CONFIG.get(model, {})
    mode = cfg.get("response_mode", "json_schema")

    # echo wire forwarding for C25 assertions
    fake_received: dict[str, Any] = {}
    if "reasoning_effort" in body:
        fake_received["reasoning_effort"] = body["reasoning_effort"]
    extra = body.get("extra_body") or {}
    if "thinking" in extra:
        fake_received["thinking"] = extra["thinking"]

    # build content per mode
    if mode == "invalid":
        content = "not-json-at-all"
        tool_calls = None
    elif mode == "function_calling":
        tool_calls = [
            {
                "id": "call_fake",
                "type": "function",
                "function": {
                    "name": "FakeModel",
                    "arguments": json.dumps({"ok": True, "value": 1}),
                },
            }
        ]
        content = None
    elif mode == "json_mode":
        content = json.dumps({"ok": True, "value": 1})
        tool_calls = None
    else:  # json_schema
        content = json.dumps({"ok": True, "value": 1})
        tool_calls = None

    msg: dict[str, Any] = {"role": "assistant"}
    if content is not None:
        msg["content"] = content
    else:
        msg["content"] = None
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls

    resp: dict[str, Any] = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "_fake_received": fake_received},
    }
    return JSONResponse(resp)
