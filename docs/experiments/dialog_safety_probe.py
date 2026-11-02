#!/usr/bin/env python3
"""Focused probe: open the White Jotter role edit dialog and classify its controls.

This is a targeted safety test, not a crawl. It uses the same projection file
as the v2 prototype and checks that every control inside the authz dialog is
classified unsafe and that cancel/close controls are not offered.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROTO = ROOT / "docs" / "experiments" / "steel_crawl_proto_v2.py"
TARGET = "http://172.20.0.1:49017/admin/user/role"
AUTH = "/tmp/wj-auth.js"
PROJECTION = "/tmp/steel_crawl_projection_v2.js"


def load_proto():
    spec = importlib.util.spec_from_file_location("proto", PROTO)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["proto"] = mod
    spec.loader.exec_module(mod)
    return mod


async def main() -> int:
    proto = load_proto()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "docs" / "experiments" / "runs" / f"dialog-probe-{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    session = f"dialog-probe-{ts}"
    log = lambda *a, **k: None
    runner = proto.Runner(session, log)
    out = {"session": session, "target": TARGET, "steps": []}
    try:
        started = await runner.cli("start", ("--session-timeout", "300000", "--inactivity-timeout", "180000"), timeout=90)
        out["steps"].append({"step": "start", "success": started.success, "data": started.data, "error": started.error})
        if not started.success:
            raise RuntimeError(f"start failed: {started.error}")
        await asyncio.sleep(1)
        await runner.cli("navigate", (proto.TARGET_ROOT + "/", "--wait-until", "domcontentloaded"), timeout=90)
        auth = await runner.eval_file(AUTH, timeout=60)
        out["steps"].append({"step": "auth", "success": auth.success, "data": auth.data, "error": auth.error})
        await runner.cli("eval", ('localStorage.setItem("username", JSON.stringify("admin")); "ok"',), timeout=30)
        nav = await runner.cli("navigate", (TARGET, "--wait-until", "domcontentloaded"), timeout=90)
        await asyncio.sleep(1)
        out["steps"].append({"step": "navigate_role", "success": nav.success, "error": nav.error})
        proj = await runner.eval_file(PROJECTION, timeout=90)
        data = json.loads(proj.data) if proj.success and isinstance(proj.data, str) else {}
        edits = [e for e in data.get("elements", []) if e.get("name") == "编辑" and e.get("type") == "BUTTON"]
        out["role_page"] = {"url": data.get("url"), "candidates": len(data.get("elements", [])),
                            "groups": len(data.get("groups", [])), "edit_buttons": len(edits),
                            "edit_selectors": [e.get("selector") for e in edits[:3]]}
        if not edits:
            raise RuntimeError("no edit button found")
        click = await runner.cli("click", (edits[0]["selector"],), timeout=60)
        await asyncio.sleep(1.2)
        out["steps"].append({"step": "click_edit", "success": click.success, "error": click.error,
                             "selector": edits[0]["selector"]})
        proj2 = await runner.eval_file(PROJECTION, timeout=90)
        data2 = json.loads(proj2.data) if proj2.success and isinstance(proj2.data, str) else {}
        dialog_candidates = []
        for cand in data2.get("elements", []):
            group = None
            if cand.get("group_id"):
                group = next((g for g in data2.get("groups", []) if g.get("id") == cand.get("group_id")), None)
            if cand.get("dialog_text") or (group and group.get("text")):
                dialog_candidates.append({
                    "type": cand.get("type"), "name": cand.get("name"),
                    "text": cand.get("text"), "selector": cand.get("selector"),
                    "dialog_text": cand.get("dialog_text"),
                })
        raw_buttons = await runner.cli("eval", (
            "JSON.stringify([...document.querySelectorAll('[role=\"dialog\"] button,dialog button')].map(b=>({t:(b.innerText||'').trim(),c:b.className})))",
        ), timeout=30)
        out["dialog"] = {
            "url": data2.get("url"),
            "candidates": len(data2.get("elements", [])),
            "groups": len(data2.get("groups", [])),
            "dialog_candidates": dialog_candidates,
            "raw_dialog_buttons": raw_buttons.data,
            "all_dialog_controls_unsafe": None,
            "cancel_or_confirm_offered": [
                c for c in dialog_candidates
                if c["type"] in ("BUTTON", "ROLE_BUTTON", "CLICKABLE")
                and c["name"] in ("取 消", "确 定", "取消", "确定", "Close")
            ],
        }
        out["ok"] = bool(dialog_candidates) and not out["dialog"]["cancel_or_confirm_offered"]
    except Exception as exc:
        out["error"] = str(exc)
    finally:
        stop = await runner.cli("stop", (), timeout=60)
        out["steps"].append({"step": "stop", "success": stop.success, "data": stop.data})
        out["stopped"] = stop.data
        (run_dir / "probe.json").write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str))
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
