#!/usr/bin/env python3
"""Run the test-executor pod (E3) against the live Steel session.

The pod verifies the safe httpOnly hypothesis without a modal dialog: the
runner reads `document.cookie` and the browser cookie inventory. The session
JSON is only used to redact cookie values from the evidence.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import traceback
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

from polymerhus.attack.hunting.pod.pod import arun_pod
from polymerhus.attack.hunting.pod.pod_memory import PodMemoryStore
from polymerhus.app.llm.checkpoints import module_context


def _redact(text: str, secrets: list[str]) -> str:
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "<redacted>")
    return out


def _walk_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk_strings(item)


def _extract_commands(value) -> list[str]:
    out = []
    for text in _walk_strings(value):
        if "steel browser " in text and len(text) < 2000:
            out.append(text)
    return sorted(set(out))


def _count(haystack: str, needle: str) -> int:
    return haystack.count(needle)


async def _session_live(mcp_url: str, session: str) -> bool:
    try:
        client = MultiServerMCPClient(
            {"kali": {"url": mcp_url, "transport": "streamable_http"}})
        tools = {tool.name: tool for tool in await client.get_tools()}
        result = await asyncio.wait_for(
            tools["steel_exec"].ainvoke({
                "command": "steel browser sessions --json",
                "session_id": "pod-post",
                "timeout_s": 60,
            }),
            timeout=90,
        )
        text = result[0]["text"] if isinstance(result, list) else str(result)
        envelope = json.loads(text)
        stdout = envelope.get("stdout") or ""
        inner = json.loads(stdout) if stdout.strip() else {}
        data = inner.get("data") or []
        names = {str(item.get("name")) for item in data
                 if isinstance(item, dict)}
        return session in names
    except Exception:
        return False


def _spec() -> dict:
    return {
        "target_identity": {
            "url": "http://t-1618c524.target/",
            "unit_id": "white-jotter",
        },
        "verification_symptoms": [
            "The document.cookie string contains JSESSIONID or rememberMe, "
            "or a cookie-inventory entry for either name lacks httpOnly.",
            "The authenticated session cookie values are readable from the "
            "JavaScript page context.",
        ],
        "assumptions": [
            "The operator-owned Steel session wj-gateway-e2e is live and "
            "authenticated; reuse it and do not start a replacement session.",
            "Do not run alert(...) or any modal dialog: it blocks the page. "
            "Read document.cookie and the cookie inventory instead.",
            "The authenticated surface is /api/authentication and "
            "/api/admin/user on http://t-1618c524.target/.",
        ],
        "rationale": (
            "If a session cookie is not httpOnly, an XSS payload can read and "
            "exfiltrate it. The test checks the httpOnly flag and the "
            "JavaScript visibility of the authenticated session."
        ),
        "skills": ["steel-browser"],
        "provenance": {
            "run_id": "steel-e2e-395",
            "loop_id": "steel-e2e-395",
            "unit_id": "white-jotter",
            "canonical_class": "session-cookie-exposure",
            "web_vulnerability_class": "session-management",
            "source_recon_refs": ["http://t-1618c524.target/"],
        },
    }


async def run(args: argparse.Namespace) -> int:
    payload = json.loads(args.session_json.read_text(encoding="utf-8"))
    secrets = [
        str(payload.get("JSESSIONID") or "").strip(),
        str(payload.get("rememberMe") or "").strip(),
    ]
    secrets = [s for s in secrets if s]
    spec = _spec()
    store = PodMemoryStore(root_dir=args.pod_root)
    args.evidence_dir.mkdir(parents=True, exist_ok=True)

    result = None
    error = None
    try:
        with module_context("hunting"):
            result = await asyncio.wait_for(
                arun_pod(
                    spec,
                    run_id=args.run_id,
                    memory_store=store,
                    project_id=args.project,
                    spec_id=args.spec_id,
                ),
                timeout=args.timeout,
            )
    except Exception:
        error = traceback.format_exc()

    session_live = await asyncio.wait_for(
        _session_live(args.mcp_url, args.session), timeout=120)
    memory_files = sorted(
        str(p.relative_to(args.pod_root))
        for p in Path(args.pod_root).rglob("*") if p.is_file()
    ) if Path(args.pod_root).exists() else []

    result_json = json.dumps(result, ensure_ascii=False, default=str)
    secret_leak = any(secret in result_json for secret in secrets)
    result_redacted = _redact(result_json, secrets)
    clean_result = json.loads(result_redacted) if result is not None else None

    if isinstance(clean_result, dict):
        verdict = clean_result.get("verdict")
        evidence = clean_result.get("evidence") or {}
    else:
        verdict = None
        evidence = {}
    terminal_reason = evidence.get("terminal_reason") if isinstance(evidence, dict) else None
    clean = evidence.get("clean") if isinstance(evidence, dict) else None
    iterations = evidence.get("iterations") if isinstance(evidence, dict) else None
    init_validation = evidence.get("init_validation") if isinstance(evidence, dict) else None
    raw_observations = evidence.get("raw_observations") if isinstance(evidence, dict) else None
    observations_text = json.dumps(raw_observations, ensure_ascii=False, default=str)
    commands = _extract_commands(clean_result)
    summary = {
        "run_id": args.run_id,
        "project": args.project,
        "spec_id": args.spec_id,
        "session": args.session,
        "spec": spec,
        "verdict": verdict,
        "terminal_reason": terminal_reason,
        "clean": clean,
        "iterations": iterations,
        "init_validation": init_validation,
        "raw_observations": len(raw_observations)
        if isinstance(raw_observations, list) else 0,
        "steel_commands": commands,
        "mentions_document_cookie": _count(observations_text, "document.cookie"),
        "mentions_httponly": _count(observations_text, "httpOnly"),
        "mentions_jsessionid": _count(observations_text, "JSESSIONID"),
        "mentions_rememberme": _count(observations_text, "rememberMe"),
        "session_live": session_live,
        "memory_files": memory_files,
        "secret_leak": secret_leak,
        "error": _redact(error, secrets) if error else None,
        "ok": bool(
            error is None
            and verdict == "unsuccessful"
            and terminal_reason == "no-symptom-evidence"
            and clean is True
            and session_live
        ),
    }
    (args.evidence_dir / "pod-result.json").write_text(
        result_redacted, encoding="utf-8")
    (args.evidence_dir / "pod-summary.json").write_text(
        _redact(json.dumps(summary, ensure_ascii=False, indent=2), secrets),
        encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="steel-e2e-395")
    parser.add_argument("--session", default="wj-gateway-e2e")
    parser.add_argument("--session-json", required=True, type=Path)
    parser.add_argument("--pod-root",
                        default="/srv/data/steel-e2e-395/hunting/test-executor-pod")
    parser.add_argument("--run-id", default="steel-e2e-395-pod")
    parser.add_argument("--spec-id", default="cookie_httponly_exposure")
    parser.add_argument("--evidence-dir", type=Path,
                        default=Path("/tmp/polymerhus-e2e/evidence"))
    parser.add_argument("--mcp-url", default=os.environ.get(
        "KALI_MCP_URL", "http://kali:8001/mcp"))
    parser.add_argument("--timeout", type=int, default=1800)
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(_parser().parse_args())))
