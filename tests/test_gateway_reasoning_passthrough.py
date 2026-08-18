"""D11 item-5 delta (#104 amendment): reasoning-field passthrough at the transport.

Proves, at the UNIT tier (no docker, no live gateway), that the pinned litellm
1.96.0 proxy (`litellm.proxy.proxy_server:app`) forwards
`reasoning_content` / `reasoning_details` unchanged in responses and accepts
replayed reasoning in subsequent request messages, for openai-compatible
providers.

Verification approach (chosen and documented 2026-08-11): option (a) of the
amended ticket - an in-process test against the real proxy ASGI with a stub
openai-compatible upstream. litellm is NOT a dependency of the dev venv
(gateway-only, ADR D10); this file therefore runs under the dedicated
verification venv `~/.cache/polymerhus-gateway-verify-venv` which carries
the exact requirements-gateway.txt pin set (`litellm[proxy]==1.96.0`,
`fastapi==0.140.6`, `httpx==0.28.1`). Reproduce with:

    ~/.cache/polymerhus-gateway-verify-venv/bin/pip install \
        "litellm[proxy]==1.96.0" fastapi==0.140.6 httpx==0.28.1 pytest

    PYTHONPATH=src ~/.cache/polymerhus-gateway-verify-venv/bin/python -m pytest \
        tests/test_gateway_reasoning_passthrough.py -q

The proxy boots WITHOUT a database (no `database_url`, no prisma) - model
registry static in the config, which exercises the identical transport code
path (proxy ASGI -> router -> provider transform); the DB only holds the model
registry, it does not touch the wire format. The D11 assertion matrix and the
zen-family nuance are T2's concern, not this file's.

CRITICAL FINDING + OPERATOR RATIFICATION (2026-08-11): verified in-process
against the pinned 1.96.0 - `reasoning_content` passes through the response
transport UNCHANGED (first-class `Message.reasoning_content`), and BOTH
reasoning fields pass through the REQUEST transport verbatim (replay). But
`reasoning_details` does NOT come back at message level: litellm 1.96.0
relocates any message key that is not in `Message.model_fields` into
`message.provider_specific_fields` (convert_dict_to_response.py:666-668) - the
VALUE survives byte-identical at `provider_specific_fields.reasoning_details`,
but `message.reasoning_details` is absent (and the openai SDK injects a
synthetic `refusal: null`).

The operator RATIFIED `provider_specific_fields` as the passthrough surface for
non-schema fields (decision 2026-08-11), CONDITIONAL on the client-side reader
parsing both forms correctly - see `_client_side_reasoning` and
`test_client_side_parses_both_reasoning_surfaces`. ADR D11 item 5 was amended
accordingly; the previous strict xfail on message-level `reasoning_details`
became the correction test `test_response_relocates_reasoning_details_to_provider_specific_fields`.
"""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List

import httpx
import pytest
from litellm.proxy.proxy_server import app as proxy_app
from litellm.proxy.proxy_server import initialize

# Sentinel values proving byte-identical passthrough: any truncation, rewrap or
# reordering by the transport breaks the exact-string equality.
REASONING_CONTENT_SENTINEL = "reasoning-content-sentinel-df8c1f2e"
REASONING_DETAILS_SENTINEL = "reasoning-details-sentinel-9a4b7c3d"
ANSWER_CONTENT = "This is the model answer."
PREVIOUS_REASONING = "previous reasoning chain to replay verbatim"
PREVIOUS_ANSWER = "previous assistant answer"
PREVIOUS_DETAILS = "previous reasoning details to replay verbatim"

MODEL_WITH_REASONING_CONTENT = "reasoning-content-model"
MODEL_WITH_REASONING_DETAILS = "reasoning-details-model"


class _StubUpstreamHandler(BaseHTTPRequestHandler):
    """OpenAI-compatible stub upstream: records request bodies, answers with a
    completion that carries the reasoning field of the requested model."""

    bodies: List[dict] = []
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):  # noqa: A002 - BaseHTTPRequestHandler API
        pass

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        if not self.path.endswith("/chat/completions"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        type(self).bodies.append(body)
        model = body["model"]
        choice_message = {"role": "assistant", "content": ANSWER_CONTENT}
        if model == MODEL_WITH_REASONING_CONTENT:
            choice_message["reasoning_content"] = REASONING_CONTENT_SENTINEL
        elif model == MODEL_WITH_REASONING_DETAILS:
            choice_message["reasoning_details"] = REASONING_DETAILS_SENTINEL
        payload = {
            "id": "cmpl-stub-1",
            "object": "chat.completion",
            "created": 1700000000,
            "model": model,
            "choices": [{"index": 0, "message": choice_message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 9, "total_tokens": 16},
        }
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="session")
def upstream():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubUpstreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _StubUpstreamHandler.bodies = []
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="session", autouse=True)
def _boot_proxy(upstream, tmp_path_factory):
    """Boot the pinned litellm 1.96.0 proxy ASGI in-process, once per session.

    Autouse because every test in this module exercises the proxy - the tests
    themselves only need the stub upstream and the ASGI app."""
    config = {
        "model_list": [
            {
                "model_name": MODEL_WITH_REASONING_CONTENT,
                "litellm_params": {
                    "model": f"openai/{MODEL_WITH_REASONING_CONTENT}",
                    "api_base": upstream,
                    "api_key": "sk-test",
                },
            },
            {
                "model_name": MODEL_WITH_REASONING_DETAILS,
                "litellm_params": {
                    "model": f"openai/{MODEL_WITH_REASONING_DETAILS}",
                    "api_base": upstream,
                    "api_key": "sk-test",
                },
            },
        ],
        "general_settings": {"store_model_in_db": False},
    }
    # initialize() in 1.96.0 accepts a config FILE PATH (despite the `dict`
    # type hint) - it runs `yaml.safe_load` on the path.
    config_path = tmp_path_factory.mktemp("proxy") / "litellm_config.yaml"
    config_path.write_text(
        "model_list:\n"
        "  - model_name: reasoning-content-model\n"
        "    litellm_params:\n"
        "      model: openai/reasoning-content-model\n"
        f"      api_base: {upstream}\n"
        "      api_key: sk-test\n"
        "  - model_name: reasoning-details-model\n"
        "    litellm_params:\n"
        "      model: openai/reasoning-details-model\n"
        f"      api_base: {upstream}\n"
        "      api_key: sk-test\n"
        "general_settings:\n"
        "  store_model_in_db: false\n"
    )
    asyncio.run(initialize(config=str(config_path)))


def _chat(model, messages):
    """One proxied chat completion against the in-process proxy ASGI."""

    async def _request():
        transport = httpx.ASGITransport(app=proxy_app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            return await client.post(
                "/chat/completions",
                json={"model": model, "messages": messages},
            )

    return asyncio.run(_request())


def test_response_carries_reasoning_content_unchanged():
    response = _chat(
        MODEL_WITH_REASONING_CONTENT,
        [{"role": "user", "content": "hello"}],
    )
    assert response.status_code == 200, response.text
    message = response.json()["choices"][0]["message"]
    assert message["reasoning_content"] == REASONING_CONTENT_SENTINEL
    assert message["content"] == ANSWER_CONTENT
    assert message["role"] == "assistant"


def _client_side_reasoning(message: dict) -> str | None:
    """Client-side reader (the surface the app/T6 replay pipeline parses).

    Assumes the application's openai-compatible client response shaped like
    litellm's message dict. Reads `reasoning_content` when present (first-class
    schema field) and falls back to the ratified relocation surface
    `provider_specific_fields.reasoning_details` for non-schema fields.
    """
    reasoning = message.get("reasoning_content")
    if reasoning is not None:
        return reasoning
    provider_fields = message.get("provider_specific_fields") or {}
    return provider_fields.get("reasoning_details")


def test_client_side_parses_both_reasoning_surfaces():
    """OPERATOR CONDITION (2026-08-11): the client-side context manager parses
    `reasoning_content` (message level) AND `reasoning_details`
    (provider_specific_fields) correctly - the D11 item-5 ratification is
    conditional on this."""
    content_response = _chat(
        MODEL_WITH_REASONING_CONTENT,
        [{"role": "user", "content": "hello"}],
    )
    assert content_response.status_code == 200, content_response.text
    message = content_response.json()["choices"][0]["message"]
    assert _client_side_reasoning(message) == REASONING_CONTENT_SENTINEL
    assert message["content"] == ANSWER_CONTENT

    details_response = _chat(
        MODEL_WITH_REASONING_DETAILS,
        [{"role": "user", "content": "hello"}],
    )
    assert details_response.status_code == 200, details_response.text
    message = details_response.json()["choices"][0]["message"]
    assert _client_side_reasoning(message) == REASONING_DETAILS_SENTINEL
    assert message["content"] == ANSWER_CONTENT


def test_response_relocates_reasoning_details_to_provider_specific_fields():
    """Correction test for the ratified surface: `reasoning_details` does NOT
    come back at message level (litellm 1.96.0 relocates non-schema message
    keys - convert_dict_to_response.py:666-668 vs `Message.model_fields` in
    litellm/types/utils.py:1177-1188) but the VALUE survives byte-identical
    under `message.provider_specific_fields.reasoning_details`. ADR D11 item 5
    (operator-ratified 2026-08-11) defines that relocation as the passthrough
    surface. If a future litellm bump promotes `reasoning_details` to a schema
    field, this test turns red on purpose - re-read the D11 amendment and
    re-assert message-level passthrough."""
    response = _chat(
        MODEL_WITH_REASONING_DETAILS,
        [{"role": "user", "content": "hello"}],
    )
    assert response.status_code == 200, response.text
    message = response.json()["choices"][0]["message"]
    assert "reasoning_details" not in message, (
        "relocation broken: reasoning_details arrived at message level; "
        "surface changed - re-read ADR D11 item 5 amendment"
    )
    provider_fields = message["provider_specific_fields"]
    assert provider_fields["reasoning_details"] == REASONING_DETAILS_SENTINEL
    assert message["content"] == ANSWER_CONTENT
    assert message["role"] == "assistant"


def test_replayed_reasoning_content_reaches_upstream_unchanged(upstream):
    replay_message = {
        "role": "assistant",
        "content": PREVIOUS_ANSWER,
        "reasoning_content": PREVIOUS_REASONING,
    }
    response = _chat(
        MODEL_WITH_REASONING_CONTENT,
        [{"role": "user", "content": "first"}, replay_message,
         {"role": "user", "content": "second"}],
    )
    assert response.status_code == 200, response.text
    received = _StubUpstreamHandler.bodies[-1]
    assert received["messages"][1] == replay_message
    assert received["messages"][1]["reasoning_content"] == PREVIOUS_REASONING
    assert response.json()["choices"][0]["message"]["reasoning_content"] == (
        REASONING_CONTENT_SENTINEL
    )


def test_replayed_reasoning_details_reaches_upstream_unchanged():
    replay_message = {
        "role": "assistant",
        "content": PREVIOUS_ANSWER,
        "reasoning_details": PREVIOUS_DETAILS,
    }
    response = _chat(
        MODEL_WITH_REASONING_DETAILS,
        [{"role": "user", "content": "first"}, replay_message,
         {"role": "user", "content": "second"}],
    )
    assert response.status_code == 200, response.text
    received = _StubUpstreamHandler.bodies[-1]
    assert received["messages"][1] == replay_message
    assert received["messages"][1]["reasoning_details"] == PREVIOUS_DETAILS
    message = response.json()["choices"][0]["message"]
    assert message["content"] == ANSWER_CONTENT
    assert message["role"] == "assistant"
    assert _client_side_reasoning(message) == REASONING_DETAILS_SENTINEL


def test_replay_then_next_turn_keeps_flowing():
    response = _chat(
        MODEL_WITH_REASONING_CONTENT,
        [
            {"role": "user", "content": "think about X"},
            {"role": "assistant", "content": PREVIOUS_ANSWER,
             "reasoning_content": PREVIOUS_REASONING},
            {"role": "user", "content": "and now Y"},
        ],
    )
    assert response.status_code == 200, response.text
    assert response.json()["choices"][0]["message"]["content"] == ANSWER_CONTENT
