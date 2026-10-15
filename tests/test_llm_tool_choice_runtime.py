"""A6 runtime (2026-10-15): the wire-observed forced tool_choice rejection.

The relay's backends are heterogeneous: a profile that declares support (or an
unset capability override, as in the local dev stack) can still meet a backend
that refuses a forced `tool_choice` with HTTP 400 `Thinking mode does not
support this tool_choice`. The static A6 rung relaxes where the profile SAYS
the upstream refuses; this tier pins the RUNTIME half:

- the client (`ReasoningPreservingChatOpenAI`) catches that rejection, relaxes
  the choice for the agent's client instance, and replays the request once -
  the deferred "automatic wire-observation channel" of the A6 record;
- the session seam (`stateful_turn`) refuses to launder the rejection into the
  `None` signal the proposers turn into a clean empty batch.

All wire traffic here is local (a loopback HTTP server); no live model is
touched.
"""
from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import openai
import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

import polymerhus.app.llm.session as S
from polymerhus.app.llm import providers as P

# The exact relay rejection text, captured live through the local litellm
# gateway (opencode-go/deepseek-v4.1-flash, 2026-10-15).
_REJECTION_MESSAGE = (
    "litellm.BadRequestError: OpenAIException - Upstream request failed: "
    "[invalid_request_error] Thinking mode does not support this tool_choice "
    "(request_id: test). Received Model Group=opencode-go/deepseek-v4.1-flash\n"
    "Available Model Group Fallbacks=None"
)


def _error_body(message: str = _REJECTION_MESSAGE) -> dict:
    return {"error": {"message": message, "type": "invalid_request_error",
                      "param": None, "code": "400"}}


def _completion(content: str = "ok") -> dict:
    return {"id": "c1", "object": "chat.completion", "created": 0, "model": "x",
            "choices": [{"index": 0,
                         "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}


def _sse(content: str = "ok") -> list[dict]:
    first = {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": "x",
             "choices": [{"index": 0,
                          "delta": {"role": "assistant", "content": content},
                          "finish_reason": None}]}
    last = {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": "x",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}
    return [first, last]


class _Relay:
    """A loopback stand-in for the gateway: queues responses, records requests."""

    def __init__(self, responses: list[tuple[int, object]]):
        self.responses = list(responses)
        self.requests: list[dict] = []
        relay = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):  # noqa: N802 - http.server's spelling
                n = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                relay.requests.append(body)
                idx = min(len(relay.requests) - 1, len(relay.responses) - 1)
                status, payload = relay.responses[idx]
                if isinstance(payload, list):  # SSE
                    raw = ("".join(f"data: {json.dumps(c)}\n\n" for c in payload)
                           + "data: [DONE]\n\n").encode()
                    ctype = "text/event-stream"
                else:
                    raw = json.dumps(payload).encode()
                    ctype = "application/json"
                self.send_response(status)
                self.send_header("content-type", ctype)
                self.send_header("content-length", str(len(raw)))
                self.send_header("connection", "close")
                self.end_headers()
                self.wfile.write(raw)
                self.close_connection = True

            def log_message(self, *args):  # silence the test log
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def relay_factory(monkeypatch):
    made: list[_Relay] = []

    def make(responses):
        relay = _Relay(responses)
        made.append(relay)
        # Direct-mode pin (#107): the loopback relay IS the provider.
        monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
        monkeypatch.setitem(P.PROVIDERS, "openai", f"http://127.0.0.1:{relay.port}/v1")
        monkeypatch.setenv("API_KEY_OPENAI", "sk-x")
        return relay

    yield make
    for relay in made:
        relay.stop()


@tool
def ping(text: str) -> str:
    """Return the text."""
    return text


def _bound(monkeypatch):
    return P.build_chat_model("openai", "x").bind_tools([ping], tool_choice="any")


# --- the matcher ------------------------------------------------------------

class _Status(Exception):
    status_code = 400


def test_the_matcher_matches_the_captured_relay_rejection():
    assert P.is_tool_choice_rejection(_Status(_REJECTION_MESSAGE)) is True


def test_the_matcher_rejects_other_bad_requests():
    assert P.is_tool_choice_rejection(_Status("some other 400")) is False
    assert P.is_tool_choice_rejection(_Status("rate limited")) is False


def test_the_matcher_requires_a_400():
    class _ServerError(Exception):
        status_code = 500
    assert P.is_tool_choice_rejection(_ServerError(_REJECTION_MESSAGE)) is False


# --- the client-layer runtime relax -----------------------------------------

def test_a_forced_choice_rejection_is_relaxed_and_replayed_once(relay_factory, monkeypatch):
    relay = relay_factory([(400, _error_body()), (200, _completion())])
    res = _bound(monkeypatch).invoke("hello")
    assert res.content == "ok"
    assert [r.get("tool_choice") for r in relay.requests] == ["required", "auto"]


def test_the_runtime_relax_persists_on_the_client_instance(relay_factory, monkeypatch):
    relay = relay_factory([(400, _error_body()), (200, _completion()), (200, _completion())])
    bound = _bound(monkeypatch)
    bound.invoke("hello")
    bound.invoke("hello again")
    assert [r.get("tool_choice") for r in relay.requests] == ["required", "auto", "auto"]


def test_a_streamed_rejection_replays_before_any_chunk(relay_factory, monkeypatch):
    relay = relay_factory([(400, _error_body()), (200, _sse())])
    chunks = list(_bound(monkeypatch).stream("hello"))
    assert "".join(c.content for c in chunks) == "ok"
    assert [r.get("tool_choice") for r in relay.requests] == ["required", "auto"]


def test_an_async_rejection_replays(relay_factory, monkeypatch):
    relay = relay_factory([(400, _error_body()), (200, _completion())])
    res = asyncio.run(_bound(monkeypatch).ainvoke("hello"))
    assert res.content == "ok"
    assert [r.get("tool_choice") for r in relay.requests] == ["required", "auto"]


def test_an_unrelated_bad_request_raises_without_a_retry(relay_factory, monkeypatch):
    relay = relay_factory([(400, _error_body("something else entirely"))])
    with pytest.raises(openai.BadRequestError):
        _bound(monkeypatch).invoke("hello")
    assert len(relay.requests) == 1


# --- the session-seam guard --------------------------------------------------

def test_the_session_seam_reraises_a_choice_rejection_instead_of_none(monkeypatch):
    def boom(*args, **kwargs):
        raise _Status(_REJECTION_MESSAGE)

    monkeypatch.setattr(S, "run_session_turn", boom)
    with pytest.raises(_Status):
        S.stateful_turn("mechanism_typist", "t:x", [HumanMessage(content="m")],
                        checkpointer=None)


def test_the_session_seam_still_degrades_an_unrelated_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(S, "run_session_turn", boom)
    assert S.stateful_turn("mechanism_typist", "t:x", [HumanMessage(content="m")],
                           checkpointer=None) is None
