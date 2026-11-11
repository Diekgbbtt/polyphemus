#!/usr/bin/env python3
"""Live e2e preflight for the capability-adaptive LLM client (#99/A1/A5/A6).

This is the operator's go/no-go probe before an eval swap. It is a LIVE test:
it spends tokens against the configured gateway and requires the agent image's
runtime dependencies. It answers one question - does the model this eval will
use actually support the generation methods the capability layer resolves for
it, at the wire?

What it checks, in order:

1. The gateway capability record resolves with a provenance source, and the
   model declares the capabilities the run depends on.
2. Method negotiation: a no-tools one-shot resolves to `json_schema`, and a
   tool-bound session turn resolves to `function_calling` (the A1 rungs).
3. Thinking negotiation: every requested level maps through
   `negotiate_thinking` to an offered wire form (never a silent downgrade).
4. The real generation methods:
   - one-shot `json_schema` through `invoke_role` (the production seam),
   - one-shot `function_calling` through `structured_output_for`,
   - a real tool loop through `ChatOpenAI.bind_tools`.

The script exits 0 only when every check passes, and prints a JSON report so a
driver can persist the result. It never writes trial state; the ambient
`PROJECT_ID` only scopes the usage ledger, and defaults to a throwaway id.

Run inside the agent image (the eval stack's `agent` container):

    python3 eval/preflight_llm_capability.py \
        --provider opencode-go --model glm-5.3 --role hunting_threat_modeller

The `--role` flag sets that role's model env var to `<provider>:<model>` for
this process only, so the production `resolve_role` path is exercised without
editing the instance `.env`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any

# Scope the usage ledger away from a real project before importing the app.
os.environ.setdefault("PROJECT_ID", "llm-capability-preflight")


def _fail(report: dict[str, Any], message: str) -> int:
    report["ok"] = False
    report.setdefault("errors", []).append(message)
    print(json.dumps(report, indent=2, default=str))
    return 1


def _role_record(role_id: str):
    from polymerhus.app.llm.providers import HUNTING_ROLES, ROLES

    for role in (*ROLES, *HUNTING_ROLES):
        if role.role_id == role_id:
            return role
    raise SystemExit(f"unknown role {role_id!r}; known: "
                     f"{sorted(r.role_id for r in (*ROLES, *HUNTING_ROLES))}")


def _pydantic_schema():
    from pydantic import BaseModel

    class PreflightAnswer(BaseModel):
        """The preflight's fixed-shape answer."""

        value: int
        reason: str

    return PreflightAnswer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", default="opencode-go")
    parser.add_argument("--model", default="glm-5.3")
    parser.add_argument("--role", default="triager",
                        help="the role whose production seam is exercised")
    parser.add_argument("--thinking", action="append", default=None,
                        help="a thinking level to negotiate; repeatable")
    parser.add_argument("--skip-thinking-live", action="store_true",
                        help="negotiate thinking levels but skip their live calls")
    parser.add_argument("--timeout-s", type=float, default=180.0)
    args = parser.parse_args()

    provider, model = args.provider, args.model
    model_ref = f"{provider}:{model}"
    report: dict[str, Any] = {
        "ok": True,
        "provider": provider,
        "model": model,
        "model_ref": model_ref,
        "gateway_url": os.environ.get("LLM_GATEWAY_URL"),
        "role": args.role,
        "checks": {},
    }

    if not os.environ.get("LLM_GATEWAY_URL"):
        return _fail(report, "LLM_GATEWAY_URL is unset; the eval path is gateway mode")

    role = _role_record(args.role)
    os.environ[role.model_key] = model_ref
    report["role_model_key"] = role.model_key
    report["declared_thinking"] = role.thinking

    from polymerhus.app.llm.capability import resolve_capability
    from polymerhus.app.llm.negotiation import (
        negotiate_method,
        negotiate_thinking,
        schema_shape_of,
    )
    from polymerhus.app.llm.providers import build_chat_model
    from polymerhus.app.llm.roles import (
        chat_model_for,
        invoke_role,
        structured_output_for,
    )

    Answer = _pydantic_schema()
    shape = schema_shape_of(Answer)

    # 1. Capability record.
    profile = resolve_capability(provider, model)
    profile_view = {
        "source": profile.source,
        "context_limit": profile.context_limit,
        "output_limit": profile.output_limit,
        "supports_tool_calling": profile.supports_tool_calling,
        "supports_structured_output": profile.supports_structured_output,
        "reasoning_control": profile.reasoning_control,
        "reasoning_efforts": list(profile.reasoning_efforts or ()),
        "thinking_budget_bounds": profile.thinking_budget_bounds,
    }
    report["checks"]["profile"] = profile_view
    missing = [
        key for key in ("supports_tool_calling", "supports_structured_output")
        if profile_view[key] is not True
    ]
    if profile.source is None or "unknown" in str(profile.source):
        return _fail(report, "the gateway has no provenance-tagged capability record")
    if missing:
        return _fail(report, f"the model does not assert {missing}")

    # 2. Method negotiation.
    method_no_tools = negotiate_method(
        profile, no_tools_bound=True, schema_shape=shape)
    method_tools = negotiate_method(
        profile, no_tools_bound=False, schema_shape=shape)
    report["checks"]["method"] = {
        "schema_shape": shape,
        "no_tools": method_no_tools,
        "tools": method_tools,
    }
    if method_no_tools != "json_schema":
        return _fail(report, f"no-tools method is {method_no_tools!r}, expected json_schema")
    if method_tools != "function_calling":
        return _fail(report, f"tool-bound method is {method_tools!r}, expected function_calling")

    # 3. Thinking negotiation.
    levels = args.thinking or [role.thinking]
    thinking: dict[str, Any] = {}
    for level in levels:
        form, value, provenance = negotiate_thinking(level, profile)
        thinking[level] = {"form": form, "value": value, "provenance": provenance}
    report["checks"]["thinking"] = thinking

    # 4a. The production one-shot seam (json_schema).
    try:
        out = invoke_role(
            args.role,
            [{"role": "user", "content":
              "Return value=7 and reason=preflight. Use the schema."}],
            schema=Answer,
        )
        report["checks"]["one_shot_json_schema"] = {
            "value": getattr(out, "value", None),
            "reason": getattr(out, "reason", None),
        }
        if out is None or getattr(out, "value", None) != 7:
            return _fail(report, "the one-shot json_schema seam returned no valid answer")
    except Exception as exc:  # noqa: BLE001 - the probe reports, the caller decides
        return _fail(report, f"one-shot json_schema raised {type(exc).__name__}: {exc}")

    # 4b. The one-shot function_calling rung.
    try:
        llm = chat_model_for(args.role)
        fc = structured_output_for(llm, Answer, "function_calling")
        out_fc = fc.invoke(
            [("user", "Return value=11 and reason=function_calling. Use the schema.")])
        report["checks"]["one_shot_function_calling"] = {
            "value": getattr(out_fc, "value", None),
            "reason": getattr(out_fc, "reason", None),
        }
        if out_fc is None or getattr(out_fc, "value", None) != 11:
            return _fail(report, "the one-shot function_calling rung returned no valid answer")
    except Exception as exc:  # noqa: BLE001
        return _fail(report, f"one-shot function_calling raised {type(exc).__name__}: {exc}")

    # 4c. The tool-loop seam (the session/tool rung).
    try:
        from langchain_core.tools import tool

        @tool
        def probe_tool(city: str) -> str:
            """Return a fixed probe answer for a city."""
            return f"probe:{city}"

        declared = levels[-1] if levels else role.thinking
        tool_llm = build_chat_model(provider, model, thinking=declared)
        bound = tool_llm.bind_tools([probe_tool])
        message = asyncio.run(bound.ainvoke(
            [("user", "Call probe_tool with city=Zurich. Do not answer in prose.")]))
        tool_calls = list(getattr(message, "tool_calls", None) or [])
        report["checks"]["tool_loop"] = {
            "declared_thinking": declared,
            "tool_calls": tool_calls,
        }
        if not tool_calls or tool_calls[0].get("name") != "probe_tool":
            return _fail(report, "the tool-loop seam returned no probe_tool call")
    except Exception as exc:  # noqa: BLE001
        return _fail(report, f"tool-loop raised {type(exc).__name__}: {exc}")

    # 4d. A live call per thinking level (unless skipped).
    if not args.skip_thinking_live:
        live: dict[str, Any] = {}
        try:
            for level in levels:
                client = build_chat_model(provider, model, thinking=level)
                reply = client.invoke(
                    [("user", "Reply with the single word ok.")])
                text = (getattr(reply, "content", "") or "").strip()
                usage = getattr(reply, "usage_metadata", None)
                live[level] = {"content_head": text[:40], "usage": usage}
                if not text and not usage:
                    return _fail(
                        report,
                        f"the live thinking={level} call returned neither content nor usage",
                    )
        except Exception as exc:  # noqa: BLE001
            return _fail(report, f"live thinking call raised {type(exc).__name__}: {exc}")
        report["checks"]["thinking_live"] = live

    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
