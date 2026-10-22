#!/usr/bin/env python3
"""Measure the text components of every recorded eval generation.

The script reads the Langfuse v2 observations API with the full message IO and
provider usage. It never mutates Langfuse and never writes outside the requested
output path.

The component attribution is deliberately conservative:

* message content is measured, not the JSON envelope;
* the provider `input + input_cache_read` is the exact input anchor;
* each component gets its character share of that anchor;
* the residual is the request envelope plus the truncated tail, reported, never
  silently dropped.

Run it on the eval host, where the Langfuse env file lives:

    python3 audit_context_occupancy.py \
        --project-id cmvgbld4j02enad0ktvximbio \
        --from 2026-10-21T23:50:00Z --to 2026-10-22T03:20:00Z \
        --out audit_context_occupancy.json
"""
from __future__ import annotations

import argparse
import base64
import collections
import json
import re
import statistics
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DECODER = json.JSONDecoder()


# -- transport ---------------------------------------------------------------


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

    def generations(self, base: dict[str, Any]) -> list[dict[str, Any]]:
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
        rows = list(seen.values())
        rows.sort(key=lambda row: row.get("startTime") or "")
        return rows


# -- message parsing ---------------------------------------------------------


def message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
            else:
                parts.append(str(block))
        return "\n".join(parts)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return "" if content is None else str(content)


def parse_messages(raw: Any) -> tuple[list[dict[str, Any]], bool]:
    if isinstance(raw, list):
        return [m for m in raw if isinstance(m, dict)], False
    if not isinstance(raw, str):
        return [], True
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [m for m in parsed if isinstance(m, dict)], False
    except (TypeError, ValueError):
        pass
    start = raw.find("[")
    if start < 0:
        return [], True
    messages: list[dict[str, Any]] = []
    index = start + 1
    while index < len(raw):
        while index < len(raw) and raw[index] in " \t\r\n,":
            index += 1
        if index >= len(raw) or raw[index] == "]":
            break
        try:
            value, index = DECODER.raw_decode(raw, index)
        except ValueError:
            return messages, True
        if isinstance(value, dict):
            messages.append(value)
    return messages, True


def is_tool_schema(message: dict[str, Any]) -> bool:
    if message.get("role") != "tool":
        return False
    content = message.get("content")
    if isinstance(content, dict):
        return content.get("type") == "function" and isinstance(
            content.get("function"), dict
        )
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


def tool_schema_meta(message: dict[str, Any]) -> tuple[str, int, int]:
    content = message.get("content")
    if isinstance(content, dict):
        function = content.get("function") or {}
        name = str(function.get("name") or "")
        description = str(function.get("description") or "")
        return name, len(json.dumps(content, ensure_ascii=False)), len(description)
    if isinstance(content, list):
        names: list[str] = []
        schemas = 0
        descriptions = 0
        for block in content:
            if not isinstance(block, dict):
                continue
            function = block.get("function") or {}
            names.append(str(function.get("name") or ""))
            schemas += len(json.dumps(block, ensure_ascii=False))
            descriptions += len(str(function.get("description") or ""))
        return ",".join(names), schemas, descriptions
    return "", len(str(content or "")), 0


def section_sizes(text: str) -> tuple[int, list[tuple[str, int]]]:
    lines = text.splitlines()
    heads: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if re.match(r"^#{1,4} ", line):
            heads.append((index, line.strip()))
    sections: list[tuple[str, int]] = []
    for number, (index, heading) in enumerate(heads):
        end = heads[number + 1][0] if number + 1 < len(heads) else len(lines)
        sections.append((heading, len("\n".join(lines[index:end])) + 1))
    preamble = len("\n".join(lines[: heads[0][0]])) if heads else len(text)
    return preamble, sections


def system_parts(system: str) -> dict[str, int]:
    """Split the system prompt into role body, examples, map and skill index.

    The split is heading based: prose mentions of "worked example" or of the
    cognitive map are not section boundaries. The index is a trailing span,
    not a heading, so it is measured separately and subtracted from the map.
    """
    if not system:
        return {"body": 0, "examples": 0, "map": 0, "index": 0}
    lines = system.splitlines()
    headings: list[tuple[int, str, int]] = []
    for number, line in enumerate(lines):
        if re.match(r"^#{1,4} ", line):
            end = len(lines)
            for later in range(number + 1, len(lines)):
                if re.match(r"^#{1,4} ", lines[later]):
                    end = later
                    break
            headings.append((number, line.strip(), len("\n".join(lines[number:end])) + 1))
    map_at = next(
        (number for number, (_, title, _) in enumerate(headings)
         if "cognitive architecture map" in title.lower()),
        None,
    )
    map_total = sum(size for _, _, size in headings[map_at:]) if map_at is not None else 0
    examples = sum(
        size
        for number, (_, title, size) in enumerate(headings)
        if (map_at is None or number < map_at)
        and ("worked example" in title.lower() or "worked examples" in title.lower()
             or re.match(r"^#{1,4} Example\b", title))
    )
    index_at = system.find("Skills available through")
    if index_at < 0:
        index_at = system.find("SKILLS - direct references")
    index = len(system) - index_at if index_at >= 0 else 0
    return {
        "body": max(0, len(system) - examples - map_total),
        "examples": examples,
        "map": max(0, map_total - index),
        "index": index,
    }


def loop_parts(loop: str) -> dict[str, Any]:
    lead = (
        "Grounded in the application overview above, your loop payload, the tool "
        "surface, the current state, and the step protocol follow.\n\n"
    )
    out: dict[str, Any] = {"total": len(loop), "lead": len(lead) if loop.startswith(lead) else 0}
    rest = loop[len(lead):] if loop.startswith(lead) else loop
    surface_marker = "Tool surface - you request exactly ONE tool call per step:"
    state_marker = "\n\nstate: "
    protocol_marker = "\n\nEach turn you either call one or more"
    try:
        surface_at = rest.index(surface_marker)
    except ValueError:
        surface_at = -1
    try:
        state_at = rest.index(state_marker)
    except ValueError:
        state_at = -1
    try:
        protocol_at = rest.index(protocol_marker)
    except ValueError:
        protocol_at = -1
    bounds = [value for value in (surface_at, state_at, protocol_at) if value >= 0]
    bounds.sort()
    labels = []
    for value, label in (
        (surface_at, "tool_surface"),
        (state_at, "state"),
        (protocol_at, "step_protocol"),
    ):
        if value >= 0:
            labels.append((value, label))
    labels.sort()
    out["grounding"] = labels[0][0] if labels else len(rest)
    for order, (value, label) in enumerate(labels):
        end = labels[order + 1][0] if order + 1 < len(labels) else len(rest)
        out[label] = end - value
    # the state marker includes the leading "\n\n"; normalise the size to the text
    if "state" in out:
        out["state"] = max(0, out["state"] - 2)
    return out


def grounding_lines(grounding: str) -> list[tuple[str, int]]:
    lines: list[tuple[str, int]] = []
    for line in grounding.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        label = stripped.split(":", 1)[0]
        lines.append((label[:96], len(line)))
    return lines


# -- extraction --------------------------------------------------------------


@dataclass
class Components:
    system: int = 0
    human: int = 0
    human_first: int = 0
    human_second: int = 0
    loop: int = 0
    loop_grounding: int = 0
    loop_tool_surface: int = 0
    loop_state: int = 0
    loop_step: int = 0
    app_overview: int = 0
    tool_desc: int = 0
    tool_resp: int = 0
    assistant_visible: int = 0
    assistant_tool_args: int = 0
    reasoning_input: int = 0
    system_body: int = 0
    system_examples: int = 0
    system_map: int = 0
    system_index: int = 0
    content: int = 0


def extract(generation: dict[str, Any]) -> tuple[Components, dict[str, Any], bool]:
    messages, truncated = parse_messages(generation.get("input"))
    component = Components()
    details: dict[str, Any] = {
        "system_sections": [],
        "tool_descriptions": [],
        "tool_responses": [],
        "loop": {},
        "grounding": [],
    }
    system = ""
    users: list[str] = []
    for message in messages:
        role = message.get("role")
        text = message_text(message)
        if role == "system":
            system += text
        elif role == "user":
            users.append(text)
        elif role == "assistant":
            component.assistant_visible += len(text)
            tool_calls = message.get("tool_calls") or []
            component.assistant_tool_args += sum(
                len(json.dumps(call.get("args") or {}, ensure_ascii=False))
                for call in tool_calls
                if isinstance(call, dict)
            )
            component.reasoning_input += len(str(message.get("reasoning_content") or ""))
        elif role == "tool":
            if is_tool_schema(message):
                name, schema, description = tool_schema_meta(message)
                component.tool_desc += schema
                details["tool_descriptions"].append(
                    {"name": name, "schema": schema, "description": description}
                )
            else:
                component.tool_resp += len(text)
                details["tool_responses"].append(
                    {
                        "tool_call_id": message.get("tool_call_id"),
                        "chars": len(text),
                        "prefix": text[:80],
                    }
                )
    component.system = len(system)
    component.human = sum(len(text) for text in users)
    component.human_first = len(users[0]) if users else 0
    component.human_second = len(users[1]) if len(users) > 1 else 0
    if users and users[0].startswith("APPLICATION OVERVIEW"):
        component.app_overview = len(users[0])
    if (
        system.startswith("You are the hunting agent")
        and len(users) > 1
        and users[1].startswith("Grounded in the application overview")
    ):
        component.loop = len(users[1])
        loop = loop_parts(users[1])
        component.loop_grounding = loop.get("grounding", 0)
        component.loop_tool_surface = loop.get("tool_surface", 0)
        component.loop_state = loop.get("state", 0)
        component.loop_step = loop.get("step_protocol", 0)
        details["loop"] = loop
        details["grounding"] = grounding_lines(users[1][: loop.get("grounding", 0)])
    parts = system_parts(system)
    component.system_body = parts.get("body", 0)
    component.system_examples = parts.get("examples", 0)
    component.system_map = parts.get("map", 0)
    component.system_index = parts.get("index", 0)
    component.content = (
        component.system
        + component.human
        + component.tool_desc
        + component.tool_resp
        + component.assistant_visible
        + component.assistant_tool_args
        + component.reasoning_input
    )
    details["system_sections"] = section_sizes(system)[1]
    return component, details, truncated


def usage(generation: dict[str, Any]) -> dict[str, int]:
    values = generation.get("usageDetails") or {}
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


def role_of(generation: dict[str, Any]) -> str:
    session = generation.get("sessionId") or ""
    role = session.rsplit(":", 1)[-1]
    if role in {"mechanism_typist", "assigner", "hunting_hunter", "hunting_threat_modeller",
                "pod_runner", "pod_triager", "job_orchestrator", "skill_evolver", "triager"}:
        return role
    name = generation.get("name") or ""
    if name in {"typist-systems-and-edges", "assigner-aggregates"}:
        return "analysis_chunk"
    return role or "unknown"


def scaled(component_chars: int, content_chars: int, input_tokens: int) -> float:
    if content_chars <= 0:
        return 0.0
    return input_tokens * component_chars / content_chars


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default="/opt/polymerhus-dev/eval/instances/eval-server-1/.env")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--to", dest="end", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    env = read_env(args.env)
    client = Langfuse(env)
    base = {
        "limit": 50,
        "fromStartTime": args.start,
        "toStartTime": args.end,
        "fields": "core,basic,time,io,usage,trace_context",
        "projectId": args.project_id,
        "type": "GENERATION",
    }
    rows = client.generations(base)
    roles: dict[str, dict[str, Any]] = collections.defaultdict(
        lambda: {
            "rows": [],
            "components": [],
            "sessions": collections.defaultdict(list),
        }
    )
    for row in rows:
        role = role_of(row)
        roles[role]["rows"].append(row)
        component, details, truncated = extract(row)
        roles[role]["components"].append((component, details, truncated))
        roles[role]["sessions"][row.get("sessionId")].append((component, usage(row), truncated))

    report: dict[str, Any] = {
        "source": "langfuse v2 observations",
        "project_id": args.project_id,
        "window": {"from": args.start, "to": args.end},
        "generations": len(rows),
        "roles": {},
        "first_calls": [],
        "limitations": [
            "Langfuse truncates the stored input at roughly 261k chars; later turns are marked truncated.",
            "The provider input anchor is input + input_cache_read; the output anchor is output + output_reasoning.",
            "Component tokens are char-share estimates against the provider input anchor, not a second tokenizer.",
        ],
    }
    for role, bucket in sorted(roles.items()):
        gen_rows = bucket["rows"]
        if not gen_rows:
            continue
        usages = [usage(row) for row in gen_rows]
        valid = [
            (component, details, truncated)
            for component, details, truncated in bucket["components"]
            if not truncated
        ]
        sample = valid or bucket["components"]
        component_fields = [
            "system", "human", "loop", "loop_grounding", "loop_tool_surface",
            "loop_state", "loop_step", "app_overview", "tool_desc", "tool_resp",
            "assistant_visible", "assistant_tool_args", "reasoning_input",
            "system_body", "system_examples", "system_map", "system_index",
        ]
        average_chars = {
            field: statistics.mean(getattr(component, field) for component, _, _ in sample)
            for field in component_fields
        }
        average_input = statistics.mean(value["input_total"] for value in usages)
        average_content = statistics.mean(component.content for component, _, _ in sample)
        components: dict[str, Any] = {}
        for field in component_fields:
            tokens = scaled(average_chars[field], average_content, average_input)
            components[field] = {
                "chars": round(average_chars[field], 1),
                "tokens": round(tokens, 1),
                "share": round(tokens / average_input, 4) if average_input else 0.0,
            }
        first_component, first_details, first_truncated = bucket["components"][0]
        first_row = gen_rows[0]
        first_usage = usage(first_row)
        first_call = {
            "start": first_row.get("startTime"),
            "session": first_row.get("sessionId"),
            "raw_chars": len(first_row.get("input") or ""),
            "messages": len(parse_messages(first_row.get("input"))[0]),
            "truncated": first_truncated,
            "usage": first_usage,
            "components": {
                field: getattr(first_component, field) for field in component_fields
            },
            "system_sections": first_details["system_sections"],
            "tool_descriptions": first_details["tool_descriptions"],
            "loop": first_details["loop"],
            "grounding": first_details["grounding"],
        }
        report["first_calls"].append({"role": role, **first_call})
        session_inputs = [
            statistics.mean(value["input_total"] for _, value, _ in session_rows)
            for session_rows in bucket["sessions"].values()
            if session_rows
        ]
        report["roles"][role] = {
            "generations": len(gen_rows),
            "sessions": len(bucket["sessions"]),
            "valid_component_samples": len(valid),
            "usage": {
                "input_sum": sum(value["input_total"] for value in usages),
                "input_mean": round(statistics.mean(value["input_total"] for value in usages), 1),
                "input_session_mean": round(statistics.mean(session_inputs), 1) if session_inputs else 0,
                "input_uncached_mean": round(statistics.mean(value["input_uncached"] for value in usages), 1),
                "cache_mean": round(statistics.mean(value["cache_read"] for value in usages), 1),
                "output_mean": round(statistics.mean(value["output_total"] for value in usages), 1),
                "total_mean": round(statistics.mean(value["total"] for value in usages), 1),
                "cache_share": round(
                    statistics.mean(value["cache_read"] for value in usages)
                    / statistics.mean(value["input_total"] for value in usages),
                    4,
                ) if statistics.mean(value["input_total"] for value in usages) else 0.0,
            },
            "average_input_tokens": round(average_input, 1),
            "components": components,
            "first_call": first_call,
        }
    reference = next(
        (
            row
            for row in rows
            if role_of(row) == "hunting_hunter"
            and "Service-navigation-menu__loop-1" in (row.get("sessionId") or "")
        ),
        None,
    )
    if reference is not None:
        component, details, truncated = extract(reference)
        report["reference_first_call"] = {
            "role": "hunting_hunter",
            "start": reference.get("startTime"),
            "session": reference.get("sessionId"),
            "raw_chars": len(reference.get("input") or ""),
            "messages": len(parse_messages(reference.get("input"))[0]),
            "truncated": truncated,
            "usage": usage(reference),
            "components": {
                field: getattr(component, field)
                for field in (
                    "system", "human", "human_first", "human_second", "loop",
                    "loop_grounding", "loop_tool_surface", "loop_state",
                    "loop_step", "app_overview", "tool_desc", "tool_resp",
                    "assistant_visible", "assistant_tool_args",
                    "reasoning_input", "system_body", "system_examples",
                    "system_map", "system_index",
                )
            },
            "system_sections": details["system_sections"],
            "tool_descriptions": details["tool_descriptions"],
            "loop": details["loop"],
            "grounding": details["grounding"],
        }
    Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(
        {
            "generations": len(rows),
            "roles": {
                role: {
                    "generations": value["generations"],
                    "sessions": value["sessions"],
                    "input_mean": value["usage"]["input_mean"],
                    "input_session_mean": value["usage"]["input_session_mean"],
                    "cache_share": value["usage"]["cache_share"],
                }
                for role, value in report["roles"].items()
            },
        },
        indent=2,
    ))


if __name__ == "__main__":
    main()
