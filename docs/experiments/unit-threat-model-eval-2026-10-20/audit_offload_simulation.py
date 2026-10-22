#!/usr/bin/env python3
"""Simulate the approved n-turn tool-response offload on the modeller session.

Rule: at turn t, a tool response whose originating turn is older than 7 is
replaced by a fixed 50-token marker. There is no retrieval call. The marker
states that the response was offloaded and is not retrievable in this
experiment.

The provider input anchor is `usageDetails.input + input_cache_read`. The
observed and simulated curves use that anchor. One response token estimate is
the response character share of the provider input, so a truncated Langfuse
tail cannot bias the comparison.

The cache model tracks the first message whose content changes. The prefix
before that message can still cache; the suffix cannot. The lost cache is the
observed cache read beyond that prefix. The script reports raw savings and the
cache penalty side by side and never claims a net win without both.
"""
from __future__ import annotations

import argparse
import base64
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

MARKER_TOKENS = 50
THRESHOLD = 7


def read_env(path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


class Langfuse:
    def __init__(self, env: dict[str, str]):
        self.host = env["LANGFUSE_HOST"].rstrip("/")
        pair = f"{env['LANGFUSE_PUBLIC_KEY']}:{env['LANGFUSE_SECRET_KEY']}"
        self.auth = base64.b64encode(pair.encode()).decode()

    def get(self, params: dict[str, Any]) -> dict[str, Any]:
        url = self.host + "/api/public/v2/observations?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(
            url, headers={"Authorization": "Basic " + self.auth}
        )
        with urllib.request.urlopen(request, timeout=240) as response:
            return json.load(response)

    def session(self, base: dict[str, Any]) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        cursor: str | None = None
        while True:
            params = dict(base)
            if cursor:
                params["cursor"] = cursor
            payload = self.get(params)
            rows = payload.get("data") or []
            for row in rows:
                if row.get("id"):
                    seen[row["id"]] = row
            cursor = (payload.get("meta") or {}).get("cursor")
            if not rows or not cursor:
                break
        return sorted(seen.values(), key=lambda row: row.get("startTime") or "")


def message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text") or block.get("content") or "")
            for block in content
            if isinstance(block, dict)
        )
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return "" if content is None else str(content)


def parse_messages(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [message for message in raw if isinstance(message, dict)]
    if not isinstance(raw, str):
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [message for message in parsed if isinstance(message, dict)]
    except (TypeError, ValueError):
        pass
    decoder = json.JSONDecoder()
    start = raw.find("[")
    if start < 0:
        return []
    messages: list[dict[str, Any]] = []
    index = start + 1
    while index < len(raw):
        while index < len(raw) and raw[index] in " \t\r\n,":
            index += 1
        if index >= len(raw) or raw[index] == "]":
            break
        try:
            value, index = decoder.raw_decode(raw, index)
        except ValueError:
            break
        if isinstance(value, dict):
            messages.append(value)
    return messages


def is_tool_schema(message: dict[str, Any]) -> bool:
    if message.get("role") != "tool":
        return False
    content = message.get("content")
    if isinstance(content, dict):
        return content.get("type") == "function"
    if isinstance(content, list):
        return any(
            isinstance(block, dict) and block.get("type") == "function"
            for block in content
        )
    if isinstance(content, str):
        head = content[:220]
        return "function" in head and (
            '"type": "function"' in head or "'type': 'function'" in head
        )
    return False


def usage(row: dict[str, Any]) -> dict[str, int]:
    values = row.get("usageDetails") or {}
    uncached = int(values.get("input") or 0)
    cache = int(values.get("input_cache_read") or 0)
    output = int(values.get("output") or 0)
    reasoning = int(values.get("output_reasoning") or 0)
    return {
        "input_uncached": uncached,
        "cache_read": cache,
        "input_total": uncached + cache,
        "output": output,
        "reasoning": reasoning,
        "output_total": output + reasoning,
        "total": int(values.get("total") or uncached + cache + output + reasoning),
    }


def origin_map(rows: list[dict[str, Any]]) -> dict[str, int]:
    origins: dict[str, int] = {}
    for turn, row in enumerate(rows):
        try:
            output = json.loads(row.get("output") or "{}")
        except (TypeError, ValueError):
            continue
        for call in output.get("tool_calls") or []:
            if isinstance(call, dict) and call.get("id"):
                origins[str(call["id"])] = turn
    return origins


def simulate(
    rows: list[dict[str, Any]], threshold: int = THRESHOLD, marker_tokens: int = MARKER_TOKENS
) -> dict[str, Any]:
    origins = origin_map(rows)
    turns: list[dict[str, Any]] = []
    for turn, row in enumerate(rows):
        messages = parse_messages(row.get("input"))
        content_chars = 0
        response_chars = 0
        old: list[dict[str, Any]] = []
        first_changed_position: int | None = None
        for message in messages:
            text = message_text(message)
            size = len(text)
            if message.get("role") == "tool" and not is_tool_schema(message):
                tool_call_id = message.get("tool_call_id")
                origin = origins.get(str(tool_call_id)) if tool_call_id else None
                age = turn - origin if origin is not None else None
                if age is not None and age > threshold and size > 200:
                    old.append(
                        {
                            "tool_call_id": tool_call_id,
                            "origin_turn": origin,
                            "age": age,
                            "chars": size,
                        }
                    )
                    if first_changed_position is None:
                        first_changed_position = content_chars
                response_chars += size
            content_chars += size
        values = usage(row)
        observed = values["input_total"]
        offload_chars = sum(item["chars"] for item in old)
        offload_tokens = (
            observed * offload_chars / content_chars if content_chars else 0.0
        )
        saved = (
            offload_tokens - marker_tokens * len(old) if old else 0.0
        )
        simulated = observed - saved
        prefix_tokens = (
            observed * first_changed_position / content_chars
            if content_chars and first_changed_position is not None
            else observed
        )
        lost_cache = (
            max(0.0, values["cache_read"] - prefix_tokens)
            if first_changed_position is not None
            else 0.0
        )
        turns.append(
            {
                "turn": turn,
                "observed_input_tokens": observed,
                "simulated_input_tokens": round(simulated, 1),
                "saved_tokens": round(saved, 1),
                "cache_read": values["cache_read"],
                "offloads": old,
                "first_changed_char": first_changed_position,
                "prefix_tokens": round(prefix_tokens, 1),
                "lost_cache_tokens": round(lost_cache, 1),
                "input_chars": len(row.get("input") or ""),
                "content_chars": content_chars,
                "response_chars": response_chars,
                "truncated": len(messages) == 0 or len(row.get("input") or "") >= 261_000,
            }
        )
    observed_values = [item["observed_input_tokens"] for item in turns]
    simulated_values = [item["simulated_input_tokens"] for item in turns]
    saved_values = [item["saved_tokens"] for item in turns]
    lost_values = [item["lost_cache_tokens"] for item in turns]
    offloads = [item for item in turns if item["offloads"]]
    first_offload = offloads[0] if offloads else None
    return {
        "turns": len(rows),
        "threshold": threshold,
        "marker_tokens": marker_tokens,
        "first": observed_values[0] if observed_values else 0,
        "peak_observed": max(observed_values) if observed_values else 0,
        "peak_simulated": max(simulated_values) if simulated_values else 0,
        "sum_observed": sum(observed_values),
        "sum_simulated": round(sum(simulated_values), 1),
        "mean_observed": round(sum(observed_values) / len(observed_values), 1) if observed_values else 0,
        "raw_saved": round(sum(saved_values), 1),
        "raw_saved_pct": round(100 * sum(saved_values) / sum(observed_values), 2) if sum(observed_values) else 0.0,
        "cache_lost": round(sum(lost_values), 1),
        "cache_lost_pct": round(100 * sum(lost_values) / sum(observed_values), 2) if sum(observed_values) else 0.0,
        "net_tokens": round(sum(saved_values) - sum(lost_values), 1),
        "first_offload": first_offload,
        "offload_turn_count": len(offloads),
        "offloaded_response_count": sum(len(item["offloads"]) for item in turns),
        "truncated_turns": sum(1 for item in turns if item["truncated"]),
        "turns_detail": turns,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default="/opt/polymerhus-dev/eval/instances/eval-server-1/.env")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    env = read_env(args.env)
    client = Langfuse(env)
    base = {
        "limit": 100,
        "fromStartTime": args.start,
        "toStartTime": args.end,
        "fields": "core,basic,time,io,usage,trace_context",
        "projectId": args.project_id,
        "type": "GENERATION",
        "name": "ReasoningPreservingChatOpenAI",
        "sessionId": args.session_id,
    }
    rows = client.session(base)
    report = {
        "source": "langfuse v2 observations",
        "session_id": args.session_id,
        "generations": len(rows),
        "rule": {
            "threshold": THRESHOLD,
            "marker_tokens": MARKER_TOKENS,
            "no_retrieval": True,
        },
        "full": simulate(rows),
        "first_eight": simulate(rows[:8]),
        "first_sixteen": simulate(rows[:16]),
        "limitations": [
            "Langfuse truncates the stored input near 261k chars; the response-token share is used for the curve.",
            "The cache model trusts the provider cache_read and the first changed message position.",
            "The 8-turn sample is below the >7 boundary; the first offload is recorded on the full session.",
        ],
    }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    summary = {
        "generations": len(rows),
        "full": {key: report["full"][key] for key in (
            "first", "peak_observed", "sum_observed", "sum_simulated", "raw_saved",
            "raw_saved_pct", "cache_lost", "cache_lost_pct", "net_tokens",
            "first_offload", "offload_turn_count", "offloaded_response_count",
            "truncated_turns",
        )},
        "first_eight": {key: report["first_eight"][key] for key in (
            "first", "peak_observed", "sum_observed", "sum_simulated", "raw_saved",
            "raw_saved_pct", "cache_lost", "net_tokens", "first_offload",
        )},
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
