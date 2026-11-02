#!/usr/bin/env python3
"""Empirical TypeSafe SystemOne probe for the polymerhus LLM client shape.

Run with the project venv:
  /Users/diekgbbtt/polymerhus/.venv/bin/python docs/experiments/typesafe_probe.py

The key is read from API_KEY_TYPESAFE in the project .env. It is never printed.
The probe compares the normal OpenAI chat path, the TypeSafe SystemOne path
through the same OpenAI SDK low-level `post`, and LiteLLM routing.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = Path(os.environ.get("TYPESAFE_ENV_FILE", "/Users/diekgbbtt/polymerhus/.env"))
OUT_DIR = ROOT / "docs" / "experiments" / "runs"
MODEL = os.environ.get("TYPESAFE_MODEL", "jev-latest")
BASE = "https://api.typesafe.ai/v1"


def load_key() -> str:
    key = os.environ.get("API_KEY_TYPESAFE")
    if key:
        return key
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("API_KEY_TYPESAFE="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("API_KEY_TYPESAFE is missing")


def state() -> dict:
    return {
        "page": {
            "url": "http://target/login",
            "title": "Sign in",
            "candidates": [
                {"id": "signin", "name": "Sign in", "type": "BUTTON"},
                {"id": "forgot", "name": "Forgot password", "type": "LINK"},
                {"id": "register", "name": "Register", "type": "LINK"},
            ],
        }
    }


def questions() -> dict:
    return {
        "next": {
            "type": "choice",
            "instructions": "Choose the next element to exercise.",
            "criteria": {
                "signin": "Submit the credentials.",
                "forgot": "Open the password recovery flow.",
                "register": "Create an account.",
            },
        }
    }


def payload() -> dict:
    return {"model": MODEL, "state": state(), "questions": questions()}


def timed(fn):
    started = time.time()
    try:
        value = fn()
        return {"ok": True, "duration_ms": int((time.time() - started) * 1000), "value": value}
    except Exception as exc:
        return {
            "ok": False,
            "duration_ms": int((time.time() - started) * 1000),
            "error_type": type(exc).__name__,
            "status": getattr(exc, "status_code", None),
            "error": str(exc)[:1200],
        }


def probe_models(client) -> dict:
    import httpx

    result = {}
    result["openai_models_list"] = timed(lambda: [m.id for m in client.models.list().data])
    result["raw_get"] = timed(lambda: {
        "status": client.get("/models", cast_to=httpx.Response).status_code,
        "json": client.get("/models", cast_to=httpx.Response).json(),
    })
    return result


def probe_chat(client) -> dict:
    return timed(lambda: client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "Reply with one word."}],
        max_tokens=5,
    ).model_dump())


def probe_chat_langchain(key: str) -> dict:
    try:
        from langchain_openai import ChatOpenAI
    except Exception as exc:
        return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)[:500]}
    return timed(lambda: ChatOpenAI(
        model=MODEL,
        api_key=key,
        base_url=BASE,
        max_retries=0,
        timeout=20,
    ).invoke("Reply with one word.").content)


def probe_systemone(client) -> dict:
    return timed(lambda: client.post("/systemone", body=payload(), cast_to=object))


def probe_systemone_dict(client) -> dict:
    return timed(lambda: client.post("/systemone", body=payload(), cast_to=dict))


def probe_systemone_raw(client) -> dict:
    import httpx

    return timed(lambda: {
        "status": client.post("/systemone", body=payload(), cast_to=httpx.Response).status_code,
        "json": client.post("/systemone", body=payload(), cast_to=httpx.Response).json(),
    })


async def probe_systemone_async(key: str) -> dict:
    from openai import AsyncOpenAI

    started = time.time()
    try:
        async with AsyncOpenAI(api_key=key, base_url=BASE, timeout=30, max_retries=0) as client:
            result = await client.post("/systemone", body=payload(), cast_to=object)
        return {"ok": True, "duration_ms": int((time.time() - started) * 1000), "value": result}
    except Exception as exc:
        return {
            "ok": False,
            "duration_ms": int((time.time() - started) * 1000),
            "error_type": type(exc).__name__,
            "status": getattr(exc, "status_code", None),
            "error": str(exc)[:1200],
        }


def probe_litellm(key: str) -> dict:
    try:
        import litellm
    except Exception as exc:
        return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)[:500]}
    out = {}
    for model in ("openai/" + MODEL, "typesafe/" + MODEL):
        out[model] = timed(lambda model=model: litellm.completion(
            model=model,
            api_base=BASE,
            api_key=key,
            messages=[{"role": "user", "content": "Reply with one word."}],
            max_tokens=5,
            timeout=30,
        ))
    return out


def main() -> int:
    key = load_key()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = OUT_DIR / f"typesafe-probe-{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    from openai import OpenAI

    client = OpenAI(api_key=key, base_url=BASE, timeout=30, max_retries=0)
    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE,
        "model": MODEL,
        "key_present": bool(key),
        "key_length": len(key),
        "openai_sdk": __import__("openai").__version__,
        "models": probe_models(client),
        "chat_openai_sdk": probe_chat(client),
        "chat_langchain": probe_chat_langchain(key),
        "systemone_openai_post_object": probe_systemone(client),
        "systemone_openai_post_dict": probe_systemone_dict(client),
        "systemone_openai_post_raw": probe_systemone_raw(client),
        "systemone_async": asyncio.run(probe_systemone_async(key)),
        "litellm": probe_litellm(key),
    }
    (out_dir / "probe.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
