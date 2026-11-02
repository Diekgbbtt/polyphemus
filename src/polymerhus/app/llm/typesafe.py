"""TypeSafe SystemOne decision client.

The TypeSafe API is not an OpenAI chat-completions endpoint. The contract is
``POST /v1/systemone`` with ``model``, ``state``, and ``questions``.

The OpenAI SDK remains the transport. ``AsyncOpenAI.post(..., cast_to=object)``
uses the same client, bearer auth, retries, timeouts, and HTTP stack as the chat
client, so this module adds no new HTTP dependency and no new provider branch to
``ChatOpenAI``.

Two contract details are load-bearing:

- ``cast_to=object``. ``cast_to=dict`` raises ``ValueError: not enough values to
  unpack`` in openai 2.x for this response shape.
- ``/v1/models`` returns ``{"models": [{"name": ...}]}``, not the OpenAI
  ``{"data": [{"id": ...}]}`` page, so ``AsyncOpenAI.models.list()`` is not used.

The direct catalog currently exposes ``jev-latest`` and ``jev-preview``.
``jev-latest`` resolves to ``jev-1.14.0``. The versioned id ``jev-1.13`` is
rejected with ``Unknown model``.

The optional TypeSafe Python SDK (``typesafe-sdk``) is documented at
https://docs.typesafe.ai/sdk/python. It is not required here; the OpenAI SDK
low-level call is the smaller integration and reuses the project's key,
timeout, and retry conventions.
"""
from __future__ import annotations

import os
from typing import Any

import httpx
from openai import AsyncOpenAI

from polymerhus.app.llm.providers import LLMConfigError, MAX_RETRIES, request_timeout

TYPESAFE_BASE_URL = "https://api.typesafe.ai/v1"
TYPESAFE_DEFAULT_MODEL = "jev-latest"


class TypeSafeResponseError(RuntimeError):
    """TypeSafe answered with a shape outside the SystemOne contract."""


class TypeSafeSystemOne:
    """Async SystemOne client over the OpenAI SDK transport.

    The client is deliberately separate from ``ChatOpenAI``: TypeSafe has no
    ``/chat/completions`` endpoint, so the chat client cannot carry this
    contract. It is not a gateway model either; LiteLLM has no ``typesafe``
    provider and ``openai/jev-latest`` would call ``/chat/completions`` and
    receive a 404.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: httpx.Timeout | float | None = None,
        max_retries: int | None = None,
    ) -> None:
        key = api_key or os.environ.get("API_KEY_TYPESAFE")
        if not key:
            raise LLMConfigError("missing API_KEY_TYPESAFE for the typesafe provider")
        self.model = model or os.environ.get("TYPESAFE_MODEL", TYPESAFE_DEFAULT_MODEL)
        self.base_url = base_url or os.environ.get("TYPESAFE_BASE_URL", TYPESAFE_BASE_URL)
        self._client = AsyncOpenAI(
            api_key=key,
            base_url=self.base_url,
            timeout=timeout or request_timeout(),
            max_retries=MAX_RETRIES if max_retries is None else max_retries,
        )

    async def ask(
        self,
        state: str | dict[str, Any] | list[Any],
        questions: dict[str, Any],
        *,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Answer one or more typed questions about ``state``.

        The returned mapping is the raw SystemOne response: ``model``,
        ``answers``, and ``usage``. The caller owns answer validation and
        confidence handling.
        """
        payload = {
            "model": model or self.model,
            "state": state,
            "questions": questions,
        }
        result = await self._client.post("/systemone", body=payload, cast_to=object)
        if not isinstance(result, dict):
            raise TypeSafeResponseError(f"unexpected SystemOne response: {type(result).__name__}")
        if not isinstance(result.get("answers"), dict):
            raise TypeSafeResponseError("SystemOne response has no answers object")
        return result

    async def models(self) -> list[dict[str, Any]]:
        """Return the direct TypeSafe model catalog.

        The catalog is ``{"models": [{"name": ...}, ...]}``; this is not the
        OpenAI model page.
        """
        response = await self._client.get("/models", cast_to=httpx.Response)
        data = response.json()
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            raise TypeSafeResponseError("TypeSafe model catalog has no models list")
        return [item for item in models if isinstance(item, dict)]

    async def close(self) -> None:
        await self._client.close()

    async def __aenter__(self) -> "TypeSafeSystemOne":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
