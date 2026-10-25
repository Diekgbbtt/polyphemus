"""Attribute every tool response to its tool name and size, and count errors.

`calls` is the number of UNIQUE tool executions (by `tool_call_id`).
`appearances` and `tokens` are the lifecycle occupancy: the same response is
re-counted in every later generation whose input still carries it.
`errors` is the number of unique failed executions.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_context_occupancy as audit  # noqa: E402

ENV = "/opt/polymerhus-dev/eval/instances/eval-server-1/.env"
PROJECT = "0c8cb6e6-7e91-4a01-880e-408896c0ce4a"
START = "2026-10-23T16:30:00Z"
END = "2026-10-24T17:05:00Z"

def response_error(name: str, text: str) -> str | None:
    stripped = text.strip()
    payload = None
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            payload = json.loads(stripped)
        except ValueError:
            payload = None
    if isinstance(payload, dict):
        if payload.get("ok") is False:
            return "ok_false"
        if payload.get("error"):
            return "error_field"
        status = payload.get("status")
        if isinstance(status, int) and status >= 400:
            return f"http_{status}"
    if name == "exec":
        marker = "stderr='"
        if marker in text:
            tail = text.split(marker, 1)[1]
            if tail.split("'", 1)[0].strip():
                return "stderr"
        return None
    if name == "query_lightrag" and "model answer unavailable" in text:
        return "fallback"
    lowered = text.lower()
    if name == "load_skill":
        return "skill_not_found" if len(text) < 500 and (
            "unknown skill" in lowered or "not found" in lowered) else None
    if name == "note":
        return None
    # A large body that merely mentions "timeout" is content, not an error.
    # Generic text markers apply only to a short, error-shaped response.
    if len(text) <= 600:
        head = lowered.lstrip()
        for marker in (
            "traceback", "permission denied", "connection refused",
            "timed out", "no such file", "command not found",
        ):
            if head.startswith(marker) or f"\n{marker}" in head:
                return marker
    return None


def bucket() -> dict:
    return {
        "appearances": 0, "chars": 0, "tokens": 0.0, "seen": set(),
        "error_ids": {}, "error_appearances": 0, "error_chars": 0,
        "error_tokens": 0.0,
        "error_kinds": collections.Counter(), "roles": collections.Counter(),
        "max_chars": 0, "samples": [],
    }


def main() -> None:
    client = audit.Langfuse(audit.read_env(ENV))
    rows = client.generations({
        "limit": 100,
        "fromStartTime": START,
        "toStartTime": END,
        "fields": "core,basic,time,io,usage,trace_context",
        "projectId": PROJECT,
        "type": "GENERATION",
    })
    print("generations:", len(rows), flush=True)

    by_tool: dict[str, dict] = collections.defaultdict(bucket)
    by_role_tool: dict[tuple[str, str], dict] = collections.defaultdict(bucket)
    request_errors: collections.Counter = collections.Counter()
    unanswered = unattributed = malformed = 0

    for row in rows:
        component, _details, _truncated = audit.extract(row)
        usage = audit.usage(row)
        content = component.content
        factor = usage["input_total"] / content if content else 0.0
        role = audit.role_of(row)
        messages, _ = audit.parse_messages(row.get("input"))
        id_to_name: dict[str, str] = {}
        call_ids: set[str] = set()
        for message in messages:
            if message.get("role") != "assistant":
                continue
            for call in message.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function") or {}
                name = str(function.get("name") or call.get("name") or "?")
                call_id = str(call.get("id") or "")
                args = function.get("arguments", call.get("args"))
                if call_id:
                    id_to_name[call_id] = name
                    call_ids.add(call_id)
                if args is not None and not isinstance(args, (dict, list)):
                    try:
                        json.loads(args)
                    except (TypeError, ValueError):
                        request_errors[f"{name}:malformed_args"] += 1
                        malformed += 1
        answered: set[str] = set()
        for message in messages:
            if message.get("role") != "tool":
                continue
            call_id = str(message.get("tool_call_id") or "")
            if not call_id:
                continue  # a tool-schema message, not a response
            name = id_to_name.get(call_id)
            if not name:
                unattributed += 1
                continue
            answered.add(call_id)
            text = audit.message_text(message)
            chars = len(text)
            tokens = chars * factor
            kind = response_error(name, text)
            for target in (by_tool[name], by_role_tool[(role, name)]):
                target["appearances"] += 1
                target["chars"] += chars
                target["tokens"] += tokens
                target["seen"].add(call_id)
                target["roles"][role] += 1
                target["max_chars"] = max(target["max_chars"], chars)
                if kind:
                    target["error_appearances"] += 1
                    target["error_chars"] += chars
                    target["error_tokens"] += tokens
                    target["error_kinds"][kind] += 1
                    target["error_ids"][call_id] = kind
                    if len(target["samples"]) < 4:
                        target["samples"].append(
                            {"kind": kind, "chars": chars, "head": text[:180]})
        missing = call_ids - answered
        unanswered += len(missing)
        for call_id in missing:
            request_errors[f"{id_to_name.get(call_id, '?')}:unanswered"] += 1

    total_tokens = sum(b["tokens"] for b in by_tool.values())
    total_unique = sum(len(b["seen"]) for b in by_tool.values())
    print(f"unique tool calls: {total_unique:,}; response appearances: "
          f"{sum(b['appearances'] for b in by_tool.values()):,}; "
          f"occupancy tokens: {total_tokens:,.0f}")
    print(f"unanswered requests: {unanswered}; unattributed responses: "
          f"{unattributed}; malformed args: {malformed}")
    print()
    print(f"{'tool':26s} {'calls':>7s} {'appear':>8s} {'chars':>13s} "
          f"{'tokens':>13s} {'share':>7s} {'errors':>7s} {'max':>9s}")
    for name, b in sorted(by_tool.items(), key=lambda kv: -kv[1]["tokens"]):
        unique_errors = len(b["error_ids"])
        print(f"{name:26s} {len(b['seen']):7,d} {b['appearances']:8,d} "
              f"{b['chars']:13,d} {b['tokens']:13,.0f} "
              f"{b['tokens'] / total_tokens * 100 if total_tokens else 0:6.1f}% "
              f"{unique_errors:7,d} {b['max_chars']:9,d}")
        if b["error_kinds"]:
            print(f"    error kinds (appearances): {dict(b['error_kinds'])}")
    print("\nrequest errors:", dict(request_errors))
    print("\nper role/tool (top 24 by occupancy tokens):")
    for (role, name), b in sorted(
            by_role_tool.items(), key=lambda kv: -kv[1]["tokens"])[:24]:
        print(f"  {role:22s} {name:24s} calls {len(b['seen']):5,d} "
              f"tokens {b['tokens']:12,.0f} errors {len(b['error_ids']):3,d}")
    print("\nerror samples:")
    for name, b in sorted(by_tool.items(), key=lambda kv: -len(kv[1]["error_ids"])):
        if not b["error_ids"]:
            continue
        print(f"  {name}: {len(b['error_ids'])} unique")
        for sample in b["samples"]:
            print(f"    {sample['kind']} {sample['chars']} | {sample['head'].replace(chr(10), ' ')}")

    with open("/tmp/tool_usage.json", "w") as handle:
        json.dump({
            "generations": len(rows),
            "total_unique_calls": total_unique,
            "total_appearances": sum(b["appearances"] for b in by_tool.values()),
            "total_tokens": total_tokens,
            "unanswered": unanswered,
            "unattributed": unattributed,
            "malformed_args": malformed,
            "request_errors": dict(request_errors),
            "by_tool": {
                name: {
                    "calls": len(b["seen"]),
                    "appearances": b["appearances"],
                    "chars": b["chars"],
                    "tokens": b["tokens"],
                    "errors": len(b["error_ids"]),
                    "error_appearances": b["error_appearances"],
                    "error_chars": b["error_chars"],
                    "error_tokens": b["error_tokens"],
                    "error_kinds": dict(b["error_kinds"]),
                    "roles": dict(b["roles"]),
                    "max_chars": b["max_chars"],
                    "samples": b["samples"],
                } for name, b in by_tool.items()
            },
            "by_role_tool": {
                f"{role}|{name}": {
                    "calls": len(b["seen"]), "appearances": b["appearances"],
                    "tokens": b["tokens"], "errors": len(b["error_ids"]),
                    "error_kinds": dict(b["error_kinds"]),
                } for (role, name), b in by_role_tool.items()
            },
        }, handle, indent=2)


if __name__ == "__main__":
    main()
