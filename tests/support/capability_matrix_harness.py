"""Helpers for the capability-adaptive matrix harness (#99)."""
from __future__ import annotations

import os
from typing import Any

import httpx

from polymerhus.app.llm.capability import CapabilityProfile

FAKE_PORT = 8001
GATEWAY_PORT = 4000


def fake_url() -> str:
    return os.environ.get("FAKE_LLM_URL", f"http://127.0.0.1:{FAKE_PORT}")


def gateway_url() -> str:
    return os.environ.get("LLM_GATEWAY_URL", f"http://127.0.0.1:{GATEWAY_PORT}")


def clear_caches() -> None:
    from polymerhus.app.llm import capability as cap
    from polymerhus.app.llm import negotiation as neg

    cap._PROFILE_CACHE.clear()
    neg._PROBE_CACHE.clear()
    try:
        neg.clear_probe_cache()
    except Exception:
        pass


def configure_fake_model(
    model_name: str,
    supports_structured_output: bool | None = None,
    supports_tool_calling: bool | None = None,
    reasoning_control: str | None = None,
    reasoning_efforts: tuple[str, ...] | None = None,
    thinking_budget_bounds: tuple[int, int] | None = None,
    response_mode: str = "json_schema",
) -> dict[str, Any]:
    """Configure fake model; best-effort HTTP to fake LLM, fallback in-memory."""
    info: dict[str, Any] = {
        "capability_source": f"models.dev/{model_name}",
        "capability_synced_at": "2026-08-11T12:00:00+00:00",
        "capability_staleness": "fresh",
    }
    if supports_structured_output is not None:
        info["supports_structured_output"] = supports_structured_output
    if supports_tool_calling is not None:
        info["supports_function_calling"] = supports_tool_calling
        info["supports_parallel_function_calling"] = supports_tool_calling
    if reasoning_control is not None:
        info["reasoning_control"] = reasoning_control
    if reasoning_efforts is not None:
        info["reasoning_efforts"] = list(reasoning_efforts)
    if thinking_budget_bounds is not None:
        info["thinking_budget_bounds"] = list(thinking_budget_bounds)

    payload = {"model_name": model_name, "model_info": info, "response_mode": response_mode}
    # try to push to fake server; ignore if not running (hermetic)
    try:
        httpx.post(f"{fake_url()}/__fake/config", json=payload, timeout=2.0)
    except Exception:
        pass
    # also keep in-process fallback for direct capability reads
    try:
        from tests.support.fake_llm_provider import _CONFIG

        _CONFIG[model_name] = {"model_info": info, "response_mode": response_mode}
    except Exception:
        pass
    return payload


def last_request(model_name: str) -> dict[str, Any] | None:
    try:
        r = httpx.get(f"{fake_url()}/__fake/last-request", params={"model": model_name}, timeout=2.0)
        if r.status_code == 200:
            data = r.json()
            return data if data else None
    except Exception:
        pass
    try:
        from tests.support.fake_llm_provider import _LAST

        return _LAST.get(model_name)
    except Exception:
        return None


def profile_from_fake(
    provider: str,
    model: str,
    http: httpx.Client | None = None,
) -> CapabilityProfile:
    """Build CapabilityProfile; try fake gateway then direct dict."""
    # try httpx fake /model/info
    url = fake_url()
    try:
        from polymerhus.app.llm.capability import resolve_capability

        # inject fake client that hits fake_url
        fake_client = http
        if fake_client is None:
            # build a client that will fetch from fake_url via monkeypatched env
            os.environ["LLM_GATEWAY_URL"] = url
            return resolve_capability(provider, model)
        return resolve_capability(provider, model, http=fake_client)
    except Exception:
        # fallback manual profile
        try:
            from tests.support.fake_llm_provider import _CONFIG

            key = f"{provider}/{model}"
            # also try without provider prefix
            cfg = _CONFIG.get(key) or _CONFIG.get(model) or {}
            info = cfg.get("model_info", {}) if isinstance(cfg, dict) else {}
        except Exception:
            info = {}
        return CapabilityProfile(
            supports_structured_output=info.get("supports_structured_output"),
            supports_tool_calling=info.get("supports_function_calling"),
            reasoning_control=info.get("reasoning_control"),
            reasoning_efforts=tuple(info["reasoning_efforts"]) if isinstance(info.get("reasoning_efforts"), list) else None,
            thinking_budget_bounds=tuple(info["thinking_budget_bounds"]) if isinstance(info.get("thinking_budget_bounds"), list) and len(info["thinking_budget_bounds"]) == 2 else None,
            source=info.get("capability_source"),
        )


def matrix_role_ids() -> list[str]:
    return ["triager", "assigner"]
