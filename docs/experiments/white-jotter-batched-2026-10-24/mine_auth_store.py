"""Mine the `auth_store` call shapes from the 2026-10-24 white-jotter run.

For every unique `auth_store` tool call, record the request shape (`path`,
`view`, `fields`), the response size, and the role. Then group by shape, so the
narrowing decision follows the observed use, not a guess.
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

    calls: dict[str, dict] = {}
    for row in rows:
        role = audit.role_of(row)
        messages, _ = audit.parse_messages(row.get("input"))
        id_to_name: dict[str, str] = {}
        for message in messages:
            if message.get("role") != "assistant":
                continue
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                name = str(function.get("name") or call.get("name") or "")
                call_id = str(call.get("id") or "")
                if call_id:
                    id_to_name[call_id] = name
                if name != "auth_store" or not call_id:
                    continue
                raw = function.get("arguments", call.get("args"))
                try:
                    args = json.loads(raw) if isinstance(raw, str) else (raw or {})
                except ValueError:
                    args = {}
                calls.setdefault(call_id, {
                    "role": role, "path": str(args.get("path") or ""),
                    "view": str(args.get("view") or "summary"),
                    "fields": tuple(args.get("fields") or ()),
                    "command": str(args.get("command") or "read"),
                    "chars": 0, "head": "",
                })
        for message in messages:
            if message.get("role") != "tool":
                continue
            call_id = str(message.get("tool_call_id") or "")
            call = calls.get(call_id)
            if call is None:
                continue
            text = audit.message_text(message)
            call["chars"] = max(call["chars"], len(text))
            call["head"] = text[:160].replace("\n", " ")

    print("unique auth_store calls:", len(calls))
    by_shape: dict[tuple, dict] = collections.defaultdict(
        lambda: {"calls": 0, "chars": 0, "roles": collections.Counter(),
                 "samples": []})
    for call in calls.values():
        shape = (call["command"], call["view"], call["path"],
                 call["fields"])
        bucket = by_shape[shape]
        bucket["calls"] += 1
        bucket["chars"] += call["chars"]
        bucket["roles"][call["role"]] += 1
        if len(bucket["samples"]) < 2:
            bucket["samples"].append(call["head"])
    print(f"\n{'calls':>5} {'chars':>9} {'view':<10} {'path':<32} fields")
    for shape, bucket in sorted(
            by_shape.items(), key=lambda kv: -kv[1]["chars"]):
        command, view, path, fields = shape
        print(f"{bucket['calls']:5d} {bucket['chars']:9,d} {view:<10} "
              f"{path[:32]:<32} {list(fields)}  roles={dict(bucket['roles'])}")
        for sample in bucket["samples"]:
            print("      |", sample[:140])

    with open("/tmp/auth_store_usage.json", "w") as handle:
        json.dump({
            "unique_calls": len(calls),
            "calls": list(calls.values()),
            "shapes": [
                {"command": command, "view": view, "path": path,
                 "fields": list(fields), **{
                     "calls": bucket["calls"], "chars": bucket["chars"],
                     "roles": dict(bucket["roles"]),
                     "samples": bucket["samples"]}}
                for (command, view, path, fields), bucket in by_shape.items()
            ],
        }, handle, indent=2, default=list)


if __name__ == "__main__":
    main()
