"""Unit tests for the direct TypeSafe SystemOne client."""
from __future__ import annotations

import asyncio

import pytest

from polymerhus.app.llm import typesafe
from polymerhus.app.llm.providers import LLMConfigError, build_chat_model


class FakeResponse:
    def __init__(self, data: dict) -> None:
        self._data = data

    def json(self) -> dict:
        return self._data


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict, object]] = []
        self.closed = False

    async def post(self, path: str, *, body: dict, cast_to: object) -> dict:
        self.calls.append((path, body, cast_to))
        return {
            "model": "jev-1.14.0",
            "answers": {
                "next": {
                    "type": "choice",
                    "choice": "signin",
                    "confidence": 0.9,
                    "probabilities": {"signin": 0.9, "forgot": 0.1},
                }
            },
            "usage": {"input_tokens": 10, "output_tokens": 2},
        }

    async def get(self, path: str, *, cast_to: object) -> FakeResponse:
        return FakeResponse({"models": [{"name": "jev-latest"}, {"name": "jev-preview"}]})

    async def close(self) -> None:
        self.closed = True


def test_ask_posts_systemone_with_object_cast(monkeypatch) -> None:
    monkeypatch.setenv("API_KEY_TYPESAFE", "test-key")
    fake = FakeClient()
    monkeypatch.setattr(typesafe, "AsyncOpenAI", lambda **kwargs: fake)
    client = typesafe.TypeSafeSystemOne()
    result = asyncio.run(
        client.ask(
            {"page": "login"},
            {"next": {"type": "choice", "criteria": {"signin": None, "forgot": None}}},
        )
    )
    assert result["answers"]["next"]["choice"] == "signin"
    path, body, cast_to = fake.calls[0]
    assert path == "/systemone"
    assert cast_to is object
    assert body["model"] == "jev-latest"
    assert body["state"] == {"page": "login"}
    assert "questions" in body


def test_models_reads_typesafe_catalog(monkeypatch) -> None:
    monkeypatch.setenv("API_KEY_TYPESAFE", "test-key")
    fake = FakeClient()
    monkeypatch.setattr(typesafe, "AsyncOpenAI", lambda **kwargs: fake)
    client = typesafe.TypeSafeSystemOne()
    models = asyncio.run(client.models())
    assert [item["name"] for item in models] == ["jev-latest", "jev-preview"]


def test_missing_key_is_a_config_error(monkeypatch) -> None:
    monkeypatch.delenv("API_KEY_TYPESAFE", raising=False)
    with pytest.raises(LLMConfigError):
        typesafe.TypeSafeSystemOne(api_key=None)


def test_response_without_answers_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("API_KEY_TYPESAFE", "test-key")

    class NoAnswers(FakeClient):
        async def post(self, path: str, *, body: dict, cast_to: object) -> dict:
            return {"model": "jev-1.14.0"}

    fake = NoAnswers()
    monkeypatch.setattr(typesafe, "AsyncOpenAI", lambda **kwargs: fake)
    client = typesafe.TypeSafeSystemOne()
    with pytest.raises(typesafe.TypeSafeResponseError):
        asyncio.run(client.ask({"page": "login"}, {"next": {"type": "noul"}}))


def test_close_releases_the_sdk_client(monkeypatch) -> None:
    monkeypatch.setenv("API_KEY_TYPESAFE", "test-key")
    fake = FakeClient()
    monkeypatch.setattr(typesafe, "AsyncOpenAI", lambda **kwargs: fake)
    client = typesafe.TypeSafeSystemOne()
    asyncio.run(client.close())
    assert fake.closed is True


def test_typesafe_is_not_a_chat_provider(monkeypatch) -> None:
    monkeypatch.setenv("API_KEY_TYPESAFE", "test-key")
    with pytest.raises(LLMConfigError, match="SystemOne"):
        build_chat_model("typesafe", "jev-latest")
