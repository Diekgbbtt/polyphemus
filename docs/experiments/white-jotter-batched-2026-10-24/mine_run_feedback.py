"""Mine the 2026-10-24 run for the four feedback tools.

- `query_lightrag`: why the fallback fires (the bundle's knowledge_gaps).
- `search_http_history`: the filter profiles and the needed detail pairs.
- `exec`: the binaries and the response meaning density.
- `graph_view`: broad versus narrow queries and whether the rows arrived.

Run on the eval server, where the Langfuse env lives.
"""
from __future__ import annotations

import collections
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_context_occupancy as audit  # noqa: E402

ENV = "/opt/polymerhus-dev/eval/instances/eval-server-1/.env"
PROJECT = "0c8cb6e6-7e91-4a01-880e-408896c0ce4a"
START = "2026-10-23T16:30:00Z"
END = "2026-10-24T17:05:00Z"

BINARIES = ("curl", "python3", "python", "bash", "sh", "nmap", "jq",
            "gobuster", "ffuf", "sqlmap", "wget", "node", "ruby", "perl")


def parse_args(raw):
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def classify_exec(command: str) -> str:
    lowered = command.strip().lower()
    if lowered.startswith("python -c") or lowered.startswith("python3 -c"):
        return "python-inline"
    if "python" in lowered and ("<<'py'" in lowered or "<<'python'" in lowered
                                or "import " in lowered):
        return "python-inline"
    for binary in BINARIES:
        if re.search(rf"(^|[|;&\s]){re.escape(binary)}(\s|$)", lowered):
            return binary
    return "other"


def classify_graph(cypher: str) -> str:
    text = " ".join(cypher.split()).lower()
    broad = (
        "match (n)" in text
        or ("match (n:" in text and "where" not in text and "limit" not in text)
        or ("match (n)" in text and "where" not in text)
    )
    if broad:
        return "broad"
    if "limit" in text or "where" in text or "{" in text:
        return "narrow"
    return "unknown"


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
        session = str(row.get("sessionId") or "")
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
                if call_id and name in {
                        "query_lightrag", "search_http_history", "exec",
                        "graph_view", "get_http_artifact"}:
                    calls.setdefault(call_id, {
                        "name": name, "role": role, "session": session,
                        "args": parse_args(
                            function.get("arguments", call.get("args"))),
                        "response": "", "chars": 0,
                    })
        for message in messages:
            if message.get("role") != "tool":
                continue
            call = calls.get(str(message.get("tool_call_id") or ""))
            if call is None:
                continue
            text = audit.message_text(message)
            if len(text) > call["chars"]:
                call["chars"] = len(text)
                call["response"] = text

    by_name = collections.Counter(c["name"] for c in calls.values())
    print("unique calls:", dict(by_name))

    # --- query_lightrag fallbacks -------------------------------------------
    light = [c for c in calls.values() if c["name"] == "query_lightrag"]
    fallbacks = [c for c in light if "model answer unavailable" in c["response"]]
    print(f"\nquery_lightrag: {len(light)} calls, {len(fallbacks)} fallbacks")
    reasons = collections.Counter()
    for call in fallbacks:
        try:
            payload = json.loads(call["response"])
        except ValueError:
            payload = {}
        gaps = payload.get("knowledge_gaps") or ["<no gap recorded>"]
        reasons.update(str(g) for g in gaps)
        call["gap"] = "; ".join(str(g) for g in gaps)[:300]
    for reason, count in reasons.most_common():
        print(f"  {count:3d}  {reason[:160]}")
    print("  samples:")
    for call in fallbacks[:6]:
        print("   ", call["role"], "|", call["gap"][:240])

    # --- search_http_history ------------------------------------------------
    searches = [c for c in calls.values() if c["name"] == "search_http_history"]
    profiles = collections.Counter()
    for call in searches:
        filters = call["args"].get("filters") or []
        parts = []
        for f in filters if isinstance(filters, list) else []:
            if isinstance(f, dict):
                parts.append(
                    f"{f.get('side')}.{f.get('namespace')}."
                    f"{f.get('key')}:{f.get('op') or f.get('operator')}")
            else:
                parts.append(str(f))
        profiles.update([" & ".join(parts) or "<no filter>"])
    print(f"\nsearch_http_history: {len(searches)} calls")
    for profile, count in profiles.most_common(15):
        print(f"  {count:3d}  {profile}")

    # Five sessions with >=3 searches followed by a get.
    by_session = collections.defaultdict(list)
    for call in calls.values():
        by_session[call["session"]].append(call)
    samples = []
    for session, items in by_session.items():
        ordered = [i for i in items]
        search_positions = [i for i, c in enumerate(ordered)
                            if c["name"] == "search_http_history"]
        if len(search_positions) < 3:
            continue
        gets = [c for c in ordered if c["name"] == "get_http_artifact"]
        if not gets:
            continue
        sample_searches = [ordered[p] for p in search_positions[:3]]
        samples.append({
            "session": session,
            "searches": [{"args": s["args"], "chars": s["chars"],
                          "head": s["response"][:220]} for s in sample_searches],
            "gets": [{"args": g["args"], "chars": g["chars"],
                      "head": g["response"][:220]} for g in gets[:2]],
        })
        if len(samples) >= 5:
            break
    print("  sample sessions:", len(samples))

    # --- exec ---------------------------------------------------------------
    execs = [c for c in calls.values() if c["name"] == "exec"]
    kinds = collections.Counter(classify_exec(str(c["args"].get("command") or ""))
                                for c in execs)
    sizes = [c["chars"] for c in execs]
    print(f"\nexec: {len(execs)} calls, median {statistics.median(sizes):.0f} "
          f"chars, p90 {statistics.quantiles(sizes, n=10)[8]:.0f}"
          if len(sizes) >= 10 else f"\nexec: {len(execs)} calls")
    for kind, count in kinds.most_common():
        print(f"  {count:4d}  {kind}")
    # Meaning density: the share of non-header, non-log lines.
    density = []
    for call in execs:
        text = call["response"]
        lines = [line for line in text.splitlines() if line.strip()]
        if not lines:
            continue
        noise = sum(
            1 for line in lines
            if line.startswith(("HTTP/", "Server:", "Date:", "Content-",
                                "Set-Cookie:", "Connection:", "Vary:",
                                "X-", "Transfer-Encoding:", "TOOL RESULT:",
                                "status=", "stderr=", "returncode="))
            or "duration_ms" in line)
        density.append(1 - noise / len(lines))
    if density:
        print(f"  meaning density median {statistics.median(density):.2f} "
              f"(non-header/log lines / non-empty lines)")

    # --- graph_view ---------------------------------------------------------
    graphs = [c for c in calls.values() if c["name"] == "graph_view"]
    shapes = collections.Counter(
        classify_graph(str(c["args"].get("cypher") or "")) for c in graphs)
    empty = sum(1 for c in graphs if '"rows": []' in c["response"]
                or '"rows":[]' in c["response"])
    print(f"\ngraph_view: {len(graphs)} calls, {empty} empty rows")
    for shape, count in shapes.most_common():
        print(f"  {count:4d}  {shape}")
    for call in graphs[:5]:
        print("   sample", classify_graph(str(call["args"].get("cypher") or "")),
              "|", str(call["args"].get("cypher") or "")[:160].replace("\n", " "),
              "|", call["response"][:120].replace("\n", " "))

    with open("/tmp/run_feedback.json", "w") as handle:
        json.dump({
            "counts": dict(by_name),
            "lightrag": {
                "calls": len(light), "fallbacks": len(fallbacks),
                "reasons": dict(reasons),
                "samples": [{"role": c["role"], "gap": c.get("gap", "")}
                            for c in fallbacks[:10]],
            },
            "search": {
                "calls": len(searches), "profiles": dict(profiles),
                "samples": samples,
            },
            "exec": {
                "calls": len(execs), "kinds": dict(kinds),
                "median_chars": statistics.median(sizes) if sizes else 0,
                "density_median": statistics.median(density) if density else 0,
            },
            "graph": {
                "calls": len(graphs), "shapes": dict(shapes), "empty": empty,
            },
        }, handle, indent=2)


if __name__ == "__main__":
    main()
