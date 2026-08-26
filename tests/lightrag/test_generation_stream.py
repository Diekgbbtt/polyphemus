import json
from types import SimpleNamespace

import lightrag.generation as gen
from lightrag.generation import DeepSeekClient


class _FakeStreamResponse:
    def __init__(self):
        self._lines = iter([
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            'data: {"choices":[{"delta":{"content":" world"}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
            "data: [DONE]",
        ])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        yield from self._lines


def test_stream_yields_deltas_and_finish(monkeypatch):
    captured = {}

    def fake_stream(method, url, **kwargs):
        captured.update(kwargs)
        return _FakeStreamResponse()

    monkeypatch.setattr(gen.httpx, "stream", fake_stream)
    client = DeepSeekClient(
        base_url="https://example.test/v1",
        api_key="k",
        model="m",
        max_tokens=128,
    )
    events = list(client.stream("prompt"))

    assert [e for e in events if e["type"] == "delta"] == [
        {"type": "delta", "text": "Hello"},
        {"type": "delta", "text": " world"},
    ]
    assert events[-1] == {"type": "finish", "finish_reason": "stop"}
    assert captured["json"]["stream"] is True
    assert captured["json"]["messages"][0]["content"] == "prompt"


def test_complete_sends_non_streaming_payload(monkeypatch):
    captured = {}

    class _FakeResponse:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return _FakeResponse(
            {
                "choices": [
                    {"message": {"content": "ok"}, "finish_reason": "stop"}
                ],
                "model": "m",
                "usage": {},
            }
        )

    monkeypatch.setattr(gen.httpx, "post", fake_post)
    client = DeepSeekClient(
        base_url="https://example.test/v1",
        api_key="k",
        model="m",
        max_tokens=128,
    )
    result = client.complete("prompt")

    assert result["content"] == "ok"
    assert captured["json"]["stream"] is False
