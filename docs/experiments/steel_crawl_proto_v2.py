#!/usr/bin/env python3
"""Steel crawl prototype v2: Jev policy, passive CDP, verbose measurement.

This is an experiment against the local Steel deployment and the White Jotter
target on the eval host. It is not production code.

Topology:
  macOS orchestrator
    -> SSH -> Steel host (pinned CLI, browser session)
    -> SSH tunnel -> local :9223 -> raw CDP
    -> SSH tunnel -> eval host :49017 -> White Jotter (target)
    -> SSH reverse tunnel + host TCP proxy -> Steel container :172.20.0.1:49017

The crawl attaches to a pre-authenticated session. The bootstrap signs in
before the crawl and is not part of the crawl action surface.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import websockets
from openai import AsyncOpenAI

STEEL_HOST = "ubuntu@dj-viscon-workshop-1.vsos.ethz.ch"
STEEL_BIN = "/tmp/steel-p0/steel-cli-x86_64-unknown-linux-gnu/steel"
STEEL_API = "http://127.0.0.1:3000/v1"
TARGET_ROOT = "http://172.20.0.1:49017"
TARGET_NETLOC = "172.20.0.1:49017"
PROJECTION_PATH = "/tmp/steel_crawl_projection_v2.js"
AUTH_JS_PATH = "/tmp/wj-auth.js"
UPLOAD_PATH = "/tmp/crawl-upload.txt"
LOCAL_CDP = "http://127.0.0.1:9223"
OUT_ROOT = Path("docs/experiments/runs")
JEV_URL = "https://api.typesafe.ai/v1"
JEV_MODEL = "jev-latest"
BODY_CAP = 512 * 1024
RUN_BODY_CAP = 64 * 1024 * 1024

IMPACT_ORDER = ["observe", "local_state", "read", "write", "navigate"]

SUBMIT_WORDS = (
    "submit", "save", "add", "create", "register", "login", "log in", "sign in",
    "send", "publish", "ok", "confirm", "apply", "search", "update", "设置",
    "保存", "添加", "创建", "注册", "登录", "提交", "确定", "发布", "搜索",
)
VALUE_CATALOGUE = {
    "username": {"value": "qacrawl-<run>", "kind": "username", "description": "unique QA account name"},
    "password": {"value": "QaCrawl!<run>", "kind": "password", "description": "QA account password"},
    "email": {"value": "qa-crawl+<run>@example.test", "kind": "email", "description": "valid email"},
    "name": {"value": "QA Crawler", "kind": "name", "description": "person name"},
    "phone": {"value": "+10000000000", "kind": "phone", "description": "valid phone"},
    "title": {"value": "QA Crawl <run>", "kind": "title", "description": "short title"},
    "text_short": {"value": "test", "kind": "text", "description": "short text"},
    "text_long": {"value": "QA crawl probe <run>", "kind": "text", "description": "long text"},
    "number": {"value": "42", "kind": "number", "description": "small integer"},
    "date": {"value": "2026-01-01", "kind": "date", "description": "ISO date"},
    "url": {"value": "https://example.test/", "kind": "url", "description": "valid URL"},
    "file": {"value": "crawl-upload.txt", "kind": "file", "description": "small text file"},
    "search": {"value": "test", "kind": "search", "description": "short search term"},
    "none": {"value": None, "kind": "none", "description": "leave empty"},
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()


def redact_text(text: str) -> str:
    text = re.sub(r'("password"\s*:\s*)"[^"]*"', r'\1"<redacted>"', text)
    text = re.sub(r"('password'\s*:\s*)'[^']*'", r"\1'<redacted>'", text)
    return text


def redact_url(url: str) -> str:
    return url


def normalize_url(url: str, base: str = TARGET_ROOT) -> str:
    p = urllib.parse.urlsplit(urllib.parse.urljoin(base, url))
    host = p.netloc.lower()
    path = p.path.rstrip("/") or "/"
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)]
    q.sort()
    return urllib.parse.urlunsplit((p.scheme, host, path, urllib.parse.urlencode(q), ""))


def in_scope(url: str) -> bool:
    try:
        p = urllib.parse.urlsplit(url)
    except Exception:
        return False
    return p.scheme in ("http", "https") and p.netloc.lower() == TARGET_NETLOC


def split_url(url: str) -> tuple[str, str]:
    p = urllib.parse.urlsplit(url)
    return p.path or "/", f"{p.scheme}://{p.netloc}"


def text_of(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@dataclass
class CliResult:
    success: bool
    data: Any
    error: dict[str, Any] | None
    duration_ms: int
    stdout: str
    stderr: str
    returncode: int


@dataclass
class Flow:
    request_id: str
    page_id: str | None = None
    action_id: str | None = None
    phase: str = ""
    method: str = ""
    url: str = ""
    resource_type: str = ""
    initiator: dict[str, Any] | None = None
    frame_id: str | None = None
    timestamp: float | None = None
    received_at: float = 0.0
    request_headers: dict[str, str] = field(default_factory=dict)
    request_body: str = ""
    response_status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    mime_type: str = ""
    protocol: str = ""
    response_body: str = ""
    response_body_len: int = 0
    response_body_base64: bool = False
    response_body_sha256: str | None = None
    finished: bool = False
    encoded_data_length: int | None = None
    error: str | None = None
    body_error: str | None = None
    body_truncated: bool = False


class Runner:
    def __init__(self, session: str, log) -> None:
        self.session = session
        self.log = log

    def _run(self, verb: str, args: tuple = (), timeout: int = 90) -> CliResult:
        if verb == "sessions":
            remote_args = [STEEL_BIN, "--api-url", STEEL_API, "browser", "sessions", "--json"]
        else:
            remote_args = [STEEL_BIN, "--api-url", STEEL_API, "browser", verb, "--session", self.session, "--json", *args]
        remote = " ".join(shlex.quote(str(a)) for a in remote_args)
        started = time.time()
        try:
            proc = subprocess.run(
                ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", STEEL_HOST, remote],
                capture_output=True, text=True, timeout=timeout,
            )
            rc = proc.returncode
            out = (proc.stdout or "").strip()
            err = (proc.stderr or "").strip()
        except subprocess.TimeoutExpired:
            return CliResult(False, None, {"code": "ssh_timeout", "message": f"{verb} exceeded {timeout}s"},
                             int((time.time() - started) * 1000), "", "", -1)
        payload = None
        if out:
            try:
                payload = json.loads(out)
            except Exception:
                for line in out.splitlines():
                    try:
                        payload = json.loads(line)
                        break
                    except Exception:
                        continue
        duration = int((time.time() - started) * 1000)
        if isinstance(payload, dict) and payload.get("success") is not False:
            return CliResult(True, payload.get("data", payload), payload.get("error"), duration, out, err, rc)
        error = (payload or {}).get("error") or {"code": "cli_error", "message": (err + " " + out)[:800]}
        return CliResult(False, None, error, duration, out, err, rc)

    async def cli(self, verb: str, args: tuple = (), timeout: int = 90) -> CliResult:
        result = await asyncio.to_thread(self._run, verb, args, timeout)
        self.log("cli", verb=verb, duration_ms=result.duration_ms, success=result.success,
                 error=result.error, args=[str(a)[:160] for a in args])
        return result

    def _run_eval_file(self, path: str, timeout: int = 60) -> CliResult:
        remote = (
            f"{shlex.quote(STEEL_BIN)} --api-url {shlex.quote(STEEL_API)} "
            f"browser eval --session {shlex.quote(self.session)} --json \"$(cat {shlex.quote(path)})\""
        )
        started = time.time()
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", STEEL_HOST, remote],
            capture_output=True, text=True, timeout=timeout,
        )
        out = (proc.stdout or "").strip()
        payload = None
        try:
            payload = json.loads(out)
        except Exception:
            pass
        duration = int((time.time() - started) * 1000)
        if isinstance(payload, dict) and payload.get("success") is not False:
            return CliResult(True, payload.get("data", payload), payload.get("error"), duration, out, proc.stderr or "", proc.returncode)
        error = (payload or {}).get("error") or {"code": "cli_error", "message": (proc.stderr or out)[:800]}
        return CliResult(False, None, error, duration, out, proc.stderr or "", proc.returncode)

    async def eval_file(self, path: str, timeout: int = 60) -> CliResult:
        result = await asyncio.to_thread(self._run_eval_file, path, timeout)
        self.log("cli", verb="eval_file", duration_ms=result.duration_ms, success=result.success,
                 error=result.error, path=path)
        return result


class Cdp:
    def __init__(self, out_dir: Path, log) -> None:
        self.out_dir = out_dir
        self.log = log
        self.ws = None
        self.reader = None
        self.next_id = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.flows: dict[str, Flow] = {}
        self.scripts: dict[str, dict[str, Any]] = {}
        self.realtime: list[dict[str, Any]] = []
        self.console: list[dict[str, Any]] = []
        self.exceptions: list[dict[str, Any]] = []
        self.navigations: list[dict[str, Any]] = []
        self.dialogs: list[dict[str, Any]] = []
        self.page_url = ""
        self.current_page_id: str | None = None
        self.current_action_id: str | None = None
        self.phase = "bootstrap"
        self.events_fh = open(out_dir / "cdp_events.jsonl", "a", encoding="utf-8")
        self.bytes_total = 0

    async def connect(self) -> None:
        url = await asyncio.to_thread(self._page_ws)
        self.ws = await websockets.connect(url, max_size=2**24, open_timeout=15)
        self.reader = asyncio.create_task(self._read())
        await self.send("Page.enable")
        await self.send("Network.enable", {"maxTotalBufferSize": 100000000, "maxResourceBufferSize": 10000000})
        await self.send("Network.setCacheDisabled", {"cacheDisabled": True})
        await self.send("Runtime.enable")
        await self.send("Debugger.enable")
        await self.send("Log.enable")
        self.log("cdp_connected", url=url)

    def _page_ws(self) -> str:
        with urllib.request.urlopen(f"{LOCAL_CDP}/json/list", timeout=10) as resp:
            items = json.load(resp)
        pages = [x for x in items if isinstance(x, dict) and x.get("type") == "page"]
        if not pages:
            raise RuntimeError("no CDP page target")
        ws = pages[0].get("webSocketDebuggerUrl") or ""
        if ws.startswith("ws://localhost/"):
            ws = ws.replace("ws://localhost/", "ws://127.0.0.1:9223/", 1)
        elif ws.startswith("ws://127.0.0.1/"):
            ws = ws.replace("ws://127.0.0.1/", "ws://127.0.0.1:9223/", 1)
        return ws

    async def send(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        mid = self.next_id
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending[mid] = fut
        assert self.ws is not None
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        return await asyncio.wait_for(fut, timeout=20)

    async def _read(self) -> None:
        assert self.ws is not None
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if "id" in msg and msg["id"] in self.pending:
                    fut = self.pending.pop(msg["id"])
                    if not fut.done():
                        fut.set_result(msg)
                    continue
                method = msg.get("method", "")
                params = msg.get("params") or {}
                try:
                    self.events_fh.write(redact_text(json.dumps(msg, ensure_ascii=False)) + "\n")
                    self.events_fh.flush()
                except Exception:
                    pass
                self._event(method, params)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.log("cdp_read_error", error=str(exc))

    def _event(self, method: str, p: dict) -> None:
        if method == "Network.requestWillBeSent":
            rid = p.get("requestId") or ""
            req = p.get("request") or {}
            flow = self.flows.get(rid) or Flow(rid)
            flow.page_id = self.current_page_id
            flow.action_id = self.current_action_id
            flow.phase = self.phase
            flow.method = req.get("method", "")
            flow.url = req.get("url", "")
            flow.resource_type = p.get("type", "")
            flow.initiator = p.get("initiator")
            flow.frame_id = p.get("frameId")
            flow.timestamp = p.get("timestamp")
            flow.received_at = time.time()
            flow.request_headers = req.get("headers") or {}
            flow.request_body = redact_text(req.get("postData") or "")
            self.flows[rid] = flow
        elif method == "Network.requestWillBeSentExtraInfo":
            rid = p.get("requestId") or ""
            if rid in self.flows:
                headers = self.flows[rid].request_headers
                for k, v in (p.get("headers") or {}).items():
                    headers.setdefault(k, v)
        elif method == "Network.responseReceived":
            rid = p.get("requestId") or ""
            flow = self.flows.get(rid) or Flow(rid)
            resp = p.get("response") or {}
            flow.response_status = resp.get("status")
            flow.response_headers = resp.get("headers") or {}
            flow.mime_type = resp.get("mimeType") or ""
            flow.protocol = resp.get("protocol") or ""
            flow.resource_type = p.get("type") or flow.resource_type
            self.flows[rid] = flow
        elif method == "Network.responseReceivedExtraInfo":
            rid = p.get("requestId") or ""
            if rid in self.flows:
                for k, v in (p.get("headers") or {}).items():
                    self.flows[rid].response_headers.setdefault(k, v)
        elif method == "Network.loadingFinished":
            rid = p.get("requestId") or ""
            flow = self.flows.get(rid) or Flow(rid)
            flow.finished = True
            flow.encoded_data_length = p.get("encodedDataLength")
            self.flows[rid] = flow
            asyncio.create_task(self._body(rid))
        elif method == "Network.loadingFailed":
            rid = p.get("requestId") or ""
            flow = self.flows.get(rid) or Flow(rid)
            flow.error = p.get("errorText") or p.get("blockedReason") or "failed"
            self.flows[rid] = flow
        elif method.startswith("Network.webSocket"):
            self.realtime.append({"method": method, "params": p, "page_id": self.current_page_id,
                                  "action_id": self.current_action_id})
        elif method == "Debugger.scriptParsed":
            sid = p.get("scriptId") or ""
            url = p.get("url") or ""
            if sid:
                self.scripts[sid] = {
                    "script_id": sid,
                    "script_url": url,
                    "page_url": self.page_url,
                    "page_id": self.current_page_id,
                    "phase": self.phase,
                    "length": p.get("length"),
                }
        elif method == "Page.frameNavigated":
            frame = p.get("frame") or {}
            self.navigations.append({"kind": "frame_navigated", "url": frame.get("url"),
                                     "frame_id": frame.get("id"), "parent_id": frame.get("parentId"),
                                     "page_id": self.current_page_id})
            if not frame.get("parentId"):
                self.page_url = frame.get("url") or self.page_url
        elif method == "Page.navigatedWithinDocument":
            self.navigations.append({"kind": "navigated_within_document", "url": p.get("url"),
                                     "page_id": self.current_page_id})
            self.page_url = p.get("url") or self.page_url
        elif method == "Page.javascriptDialogOpening":
            self.dialogs.append({"type": p.get("type"), "message": p.get("message")})
            asyncio.create_task(self._dialog())
        elif method == "Runtime.consoleAPICalled":
            self.console.append({"type": p.get("type"), "args": [
                str((a.get("value") if isinstance(a, dict) else a))[:300] for a in (p.get("args") or [])
            ]})
        elif method == "Runtime.exceptionThrown":
            d = p.get("exceptionDetails") or {}
            self.exceptions.append({"text": d.get("text"), "url": d.get("url"), "line": d.get("lineNumber")})
        elif method == "Log.entryAdded":
            entry = p.get("entry") or {}
            self.console.append({"type": "log:" + str(entry.get("level")), "args": [str(entry.get("text"))[:300]]})

    async def _body(self, rid: str) -> None:
        flow = self.flows.get(rid)
        if not flow:
            return
        if flow.resource_type not in ("Document", "XHR", "Fetch", "Script"):
            return
        if self.bytes_total >= RUN_BODY_CAP:
            flow.body_error = "run_cap"
            return
        try:
            res = await self.send("Network.getResponseBody", {"requestId": rid})
            result = res.get("result") or {}
            body = result.get("body") or ""
            flow.response_body_base64 = bool(result.get("base64Encoded"))
            if len(body) > BODY_CAP:
                body = body[:BODY_CAP]
                flow.body_truncated = True
            flow.response_body = redact_text(body)
            flow.response_body_len = len(body)
            flow.response_body_sha256 = sha(body)
            self.bytes_total += len(body)
        except Exception as exc:
            flow.body_error = str(exc)[:300]

    async def _dialog(self) -> None:
        try:
            await self.send("Page.handleJavaScriptDialog", {"accept": True, "promptText": "test"})
        except Exception:
            pass

    async def close(self) -> None:
        try:
            if self.reader:
                self.reader.cancel()
                await asyncio.gather(self.reader, return_exceptions=True)
            if self.ws:
                await self.ws.close()
        finally:
            self.events_fh.close()


class Jev:
    def __init__(self, out_dir: Path, log, enabled: bool = True) -> None:
        self.enabled = enabled
        self.key = None
        self.client = None
        self.log = log
        self.fh = open(out_dir / "decisions.jsonl", "a", encoding="utf-8")
        self.calls = 0
        self.errors = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost = 0.0
        self.latency_ms: list[int] = []
        if enabled:
            key = os.environ.get("API_KEY_TYPESAFE")
            if not key:
                env_path = Path(os.environ.get("POLYMERHUS_ENV_FILE", "/Users/diekgbbtt/polymerhus/.env"))
                if env_path.exists():
                    for line in env_path.read_text().splitlines():
                        if line.startswith("API_KEY_TYPESAFE="):
                            key = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
            if not key:
                raise RuntimeError("API_KEY_TYPESAFE is missing")
            self.key = key
            # The OpenAI SDK is the transport; TypeSafe is not a chat endpoint.
            self.client = AsyncOpenAI(api_key=key, base_url=JEV_URL, timeout=60, max_retries=1)

    async def ask(self, state: Any, questions: dict[str, Any], tag: str) -> dict[str, Any] | None:
        if not self.enabled or self.client is None:
            return None
        payload = {"model": JEV_MODEL, "state": state, "questions": questions}
        started = time.time()
        last_error = None
        for attempt in range(3):
            try:
                data = await self.client.post("/systemone", body=payload, cast_to=object)
                if not isinstance(data, dict):
                    raise RuntimeError(f"unexpected SystemOne response {type(data).__name__}")
                latency = int((time.time() - started) * 1000)
                self.calls += 1
                self.latency_ms.append(latency)
                usage = data.get("usage") or {}
                input_tokens = int(usage.get("input_tokens") or 0)
                output_tokens = int(usage.get("output_tokens") or 0)
                self.input_tokens += input_tokens
                self.output_tokens += output_tokens
                # TypeSafe direct: $42 per Btok input = 42e-9 USD per token;
                # output tokens are free.
                self.cost += input_tokens * 42e-9
                record = {"ts": utcnow(), "tag": tag, "latency_ms": latency,
                          "request": {"state": state, "questions": questions},
                          "response": data, "attempt": attempt}
                self.fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                self.fh.flush()
                self.log("jev", tag=tag, latency_ms=latency, model=data.get("model"),
                         usage=usage, answers=data.get("answers"))
                return data.get("answers")
            except Exception as exc:
                last_error = str(exc)[:500]
                self.log("jev_error", tag=tag, attempt=attempt, error=last_error)
            await asyncio.sleep(1 + attempt)
        self.errors += 1
        self.log("jev_failed", tag=tag, error=last_error)
        return None

    async def close(self) -> None:
        if self.client is not None:
            try:
                await self.client.close()
            except Exception:
                pass
        self.fh.close()


PROJECTION_JS = r"""
(() => {
  const MAXC = 500;
  const out = {url: location.href, title: document.title, ready: document.readyState,
               generation: String(performance.timeOrigin), elements: [], groups: [], notes: []};
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  const txt = (el, n) => {
    const v = (el.getAttribute && (el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('alt') || el.getAttribute('placeholder'))) || el.innerText || el.value || '';
    return String(v).replace(/\s+/g, ' ').trim().slice(0, n || 120);
  };
  const abs = (u) => { try { return new URL(u, location.href).href; } catch (e) { return ''; } };
  const same = (u) => { try { return new URL(u, location.href).origin === location.origin; } catch (e) { return false; } };
  const visible = (el) => {
    try {
      if (!el || el.nodeType !== 1) return false;
      if (el.hidden) return false;
      if (el.closest('[hidden],[inert],[aria-hidden="true"]')) return false;
      const s = getComputedStyle(el);
      if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0;
    } catch (e) { return false; }
  };
  const attr = (v) => String(v).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  const unique = (sel) => { try { return document.querySelectorAll(sel).length === 1; } catch (e) { return false; } };
  const path = (el) => {
    if (!el || el.nodeType !== 1) return '';
    if (el.id) {
      const s = '#' + esc(el.id);
      if (unique(s)) return s;
    }
    const tag = el.tagName.toLowerCase();
    if (tag === 'form') {
      const forms = [...document.querySelectorAll('form')];
      return forms.length === 1 ? 'form' : `form:nth-of-type(${forms.indexOf(el) + 1})`;
    }
    if (tag === 'input' || tag === 'textarea' || tag === 'select') {
      const ph = el.getAttribute('placeholder');
      if (ph) {
        const s = `${tag}[placeholder="${attr(ph)}"]`;
        if (unique(s)) return s;
      }
      const name = el.getAttribute('name');
      if (name) {
        const s = `${tag}[name="${attr(name)}"]`;
        if (unique(s)) return s;
      }
    }
    if (tag === 'button') {
      const form = el.closest('form');
      if (form) {
        const btns = [...form.querySelectorAll('button')];
        if (btns.length === 1) return 'form button';
        const idx = btns.indexOf(el);
        if (idx >= 0) return `form button:nth-of-type(${idx + 1})`;
      }
      const dialog = el.closest('[role="dialog"],dialog');
      if (dialog) {
        const btns = [...dialog.querySelectorAll('button')];
        if (btns.length === 1) return '[role="dialog"] button';
        const idx = btns.indexOf(el);
        if (idx >= 0) return `[role="dialog"] button:nth-of-type(${idx + 1})`;
      }
      if (document.querySelectorAll('button').length === 1) return 'button';
    }
    const parts = [];
    let n = el;
    for (let i = 0; i < 6 && n && n.nodeType === 1 && n !== document.body; i++) {
      let p = n.nodeName.toLowerCase();
      if (n.parentElement) {
        const sibs = [...n.parentElement.children].filter(c => c.nodeName === n.nodeName);
        if (sibs.length > 1) p += ':nth-of-type(' + (sibs.indexOf(n) + 1) + ')';
      }
      parts.unshift(p);
      n = n.parentElement;
    }
    return parts.join(' > ');
  };
  const fp = (s) => {
    let h = 2166136261;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return ('00000000' + (h >>> 0).toString(16)).slice(-8);
  };
  const ext = /\.(pdf|txt|zip|png|jpe?g|gif|csv|xlsx?|docx?|gz|tar|mp3|mp4|woff2?|ttf|svg)$/i;
  const fieldSel = 'input,select,textarea,[contenteditable="true"],[contenteditable=""]';
  const isField = (el) => el.matches && el.matches(fieldSel);
  const fieldRoles = new Set(['textbox','searchbox','combobox','checkbox','radio','switch','slider','spinbutton','option','listbox']);
  const submitText = (t) => {
    const s = String(t || '').toLowerCase();
    const n = s.replace(/\s+/g, '');
    return ['注册','登录','提交','保存','确定','添加','创建','发布','搜索','submit','save','add','create','register','login','log in','sign in','send','publish','ok','confirm','apply','search','update']
      .some(w => s.includes(w) || n.includes(w.replace(/\s+/g, '')));
  };
  const fieldInfo = (el) => {
    const tag = el.tagName.toLowerCase();
    const type = (el.getAttribute('type') || (tag === 'textarea' ? 'textarea' : tag)).toLowerCase();
    let label = '';
    try {
      const l = el.labels && el.labels[0];
      if (l) label = txt(l, 80);
      if (!label && el.getAttribute('aria-labelledby')) {
        const n = document.getElementById(el.getAttribute('aria-labelledby'));
        if (n) label = txt(n, 80);
      }
    } catch (e) {}
    const options = tag === 'select' ? [...el.options].map(o => ({value: o.value, text: txt(o, 80)})).slice(0, 30) : [];
    return {tag, type, name: el.getAttribute('name') || '', id: el.id || '',
            placeholder: el.getAttribute('placeholder') || '', label,
            selector: path(el), visible: visible(el), required: !!el.required,
            pattern: el.getAttribute('pattern') || '', min: el.getAttribute('min') || '',
            max: el.getAttribute('max') || '', value: el.value || '', checked: !!el.checked,
            options, disabled: !!el.disabled, readonly: !!el.readOnly,
            fingerprint: fp([tag, type, el.getAttribute('name') || '', el.id || '',
                             el.getAttribute('placeholder') || '', label, path(el)].join('|'))};
  };
  const fieldsIn = (root) => [...root.querySelectorAll(fieldSel)].filter(f => !f.closest('[hidden],[inert]')).map(fieldInfo);
  const addElement = (el, type, channel, extra) => {
    if (!el || out.elements.length >= MAXC) return null;
    const o = {id: 'cand_' + out.elements.length, type, channel,
               tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '',
               name: txt(el), text: txt(el, 160), selector: path(el),
               visible: visible(el), disabled: !!el.disabled, href: '', action: '', method: '',
               target: '', controls: [], expanded: el.getAttribute('aria-expanded') || '',
               handler: '', fingerprint: '', dialog_text: '',
               dom_path: path(el)};
    Object.assign(o, extra || {});
    o.fingerprint = fp([o.type, o.tag, o.role, o.name, o.href, o.action, o.method, o.dom_path].join('|'));
    out.elements.push(o);
    return o;
  };
  const typeFor = (el) => {
    const tag = el.tagName.toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (tag === 'a') {
      const href = el.getAttribute('href') || '';
      if (!href || href.startsWith('#') || /^(javascript|mailto|tel|data|blob):/i.test(href)) return null;
      const full = abs(href);
      if (!/^https?:/i.test(full)) return null;
      if (!same(full)) return 'EXTERNAL_LINK';
      if (el.hasAttribute('download') || ext.test(new URL(full).pathname)) return 'DOWNLOAD';
      return 'LINK';
    }
    if (tag === 'area') {
      const href = el.getAttribute('href') || '';
      if (!href || !/^https?:/i.test(abs(href))) return null;
      return same(abs(href)) ? 'AREA' : 'EXTERNAL_AREA';
    }
    if (tag === 'form') {
      const action = el.getAttribute('action') || '';
      return (!action || same(abs(action))) ? 'FORM' : 'EXTERNAL_FORM';
    }
    if (tag === 'button') {
      if (el.closest('form') && (el.getAttribute('type') || '').toLowerCase() === 'submit') return null;
      return 'BUTTON';
    }
    if (tag === 'summary') return 'DISCLOSURE';
    if (tag === 'iframe') {
      const src = el.getAttribute('src') || '';
      return src && !same(abs(src)) ? 'EXTERNAL_IFRAME' : 'IFRAME';
    }
    if (tag === 'frame') return 'FRAME';
    if (tag === 'meta' && /refresh/i.test(el.getAttribute('http-equiv') || '')) return 'META_REFRESH';
    if (tag === 'dialog' || role === 'dialog' || el.getAttribute('aria-modal') === 'true') return 'DIALOG_STATE';
    if (role === 'button') return 'ROLE_BUTTON';
    if (role === 'link') return 'ROLE_LINK';
    if (role === 'tab') return 'TAB';
    if (['menuitem','menuitemcheckbox','menuitemradio'].includes(role)) return 'MENU_ITEM';
    if (role === 'treeitem') return 'TREE_ITEM';
    if (fieldRoles.has(role)) return null;
    if (el.getAttribute('draggable') === 'true') return 'DRAGGABLE';
    if (el.hasAttribute('onclick') || el.hasAttribute('onmouseover') || el.hasAttribute('oncontextmenu')) return 'CLICKABLE';
    if ((tag === 'svg' || tag === 'canvas') && (el.hasAttribute('onclick') || role === 'button')) return 'CLICKABLE';
    if (tag.includes('-') && (role || el.hasAttribute('tabindex') || el.hasAttribute('onclick'))) return 'CUSTOM';
    if (role && role !== 'presentation' && role !== 'none' && role !== 'generic') return 'CUSTOM';
    if (el.hasAttribute('tabindex')) return 'CUSTOM';
    return null;
  };
  const channelFor = (t) => {
    if (!t) return 'ignore';
    if (t.startsWith('EXTERNAL_')) return 'ignore';
    if (t === 'DOWNLOAD') return 'collect';
    if (t === 'DIALOG_STATE') return 'ignore';
    return 'offer';
  };
  const impactFor = (t, el) => {
    if (!t) return 'observe';
    if (t === 'DOWNLOAD') return 'download';
    if (t.startsWith('EXTERNAL_')) return 'external';
    if (t === 'FORM') {
      const m = (el.getAttribute('method') || 'get').toUpperCase();
      return m === 'GET' ? 'navigate' : 'write';
    }
    if (t === 'LINK' || t === 'AREA' || t === 'IFRAME' || t === 'FRAME' || t === 'META_REFRESH') return 'navigate';
    if (t === 'MENU_ITEM') return el.getAttribute('aria-expanded') !== null ? 'local_state' : 'navigate';
    return 'local_state';
  };
  const addFieldsGroup = (root, kind, el) => {
    const native = !!(el && el.tagName.toLowerCase() === 'form');
    const allFields = fieldsIn(root);
    const fields = native ? allFields : allFields.filter(f => f.visible);
    if (!fields.length) return null;
    if (!native) {
      if (fields.length > 12) return null;
      const types = new Set(fields.map(f => f.type));
      if ([...types].every(t => t === 'checkbox' || t === 'radio')) return null;
      if (['TABLE', 'TBODY', 'TR', 'THEAD', 'UL', 'OL'].includes(root.tagName)) return null;
    }
    const buttons = [...root.querySelectorAll('button,[role="button"],input[type="submit"],input[type="button"]')]
      .filter(b => visible(b) && submitText(txt(b, 80) || b.value || ''));
    const submit = buttons[0];
    const action = el && el.tagName.toLowerCase() === 'form' ? abs(el.getAttribute('action') || location.href) : '';
    const method = el && el.tagName.toLowerCase() === 'form' ? (el.getAttribute('method') || 'get').toUpperCase() : '';
    const enctype = el && el.tagName.toLowerCase() === 'form' ? (el.getAttribute('enctype') || 'application/x-www-form-urlencoded') : '';
    const g = {id: 'group_' + out.groups.length, kind, synthetic: !native,
               action, method, enctype, selector: el ? path(el) : '', root_selector: el ? path(el) : '',
               submit_selector: submit ? path(submit) : '', submit_text: submit ? txt(submit, 60) : '',
               fields, text: el ? txt(el, 200) : '',
               fingerprint: fp(['FORM', kind, action, method, fields.map(f => f.name + ':' + f.type + ':' + f.placeholder).join(',')].join('|'))};
    out.groups.push(g);
    return g;
  };
  // native forms
  [...document.querySelectorAll('form')].forEach(f => {
    if (!visible(f)) return;
    addFieldsGroup(f, 'native', f);
  });
  // synthetic groups: fields outside forms, nearest ancestor with a submit control
  const outside = [...document.querySelectorAll(fieldSel)].filter(f => !f.closest('form') && visible(f));
  const seenRoots = new Set();
  outside.forEach(f => {
    let n = f.parentElement;
    for (let i = 0; i < 8 && n && n !== document.body; i++, n = n.parentElement) {
      const btns = [...n.querySelectorAll('button,[role="button"],input[type="submit"],input[type="button"]')]
        .filter(b => visible(b) && submitText(txt(b, 80) || b.value || ''));
      if (btns.length && !seenRoots.has(path(n))) {
        seenRoots.add(path(n));
        addFieldsGroup(n, 'synthetic', n);
        break;
      }
    }
  });
  // visible dialog groups
  [...document.querySelectorAll('[role="dialog"],[aria-modal="true"],dialog')].forEach(d => {
    if (!visible(d)) return;
    const p = path(d);
    if (seenRoots.has(p)) return;
    seenRoots.add(p);
    addFieldsGroup(d, 'dialog', d);
  });
  // element candidates
  const groupSubmitSelectors = new Set(out.groups.map(g => g.submit_selector).filter(Boolean));
  const groupImpact = (g) => {
    const t = String(g.submit_text || '').toLowerCase();
    if (t.includes('搜索') || t.includes('search') || t.includes('query')) return 'read';
    if (g.method === 'GET') return 'navigate';
    return 'write';
  };
  const sel = 'a[href],area[href],button,summary,iframe,frame,dialog,[role],[onclick],[tabindex],[draggable="true"],[onmouseover],[oncontextmenu],meta[http-equiv="refresh"],svg[onclick],canvas[onclick]';
  [...document.querySelectorAll(sel)].forEach(el => {
    if (out.elements.length >= MAXC) return;
    if (isField(el)) return;
    if (el.closest('form') && el.tagName.toLowerCase() !== 'form') return;
    if (el.tagName.toLowerCase() === 'button' && groupSubmitSelectors.has(path(el))) return;
    const t = typeFor(el);
    if (!t) return;
    if (t === 'FORM') return; // groups handle forms
    if ((t === 'CUSTOM' || t === 'CLICKABLE') &&
        (txt(el, 400).length > 220 ||
         el.querySelectorAll('a[href],button,[role],[onclick],[tabindex]').length > 6)) return;
    const shortLabel = txt(el, 40).trim();
    if (t === 'CUSTOM' && /^[\d.,%]+$/.test(shortLabel)) return;
    if (t === 'CUSTOM' && /breadcrumb|面包屑/i.test(shortLabel + ' ' + String(el.className || ''))) return;
    if (t === 'CUSTOM' && el.closest('[class*="echarts"],[class*="chart"],[class*="progress"],[class*="gauge"],[class*="breadcrumb"]')) return;
    if (t === 'BUTTON' && /^(close|关闭|×)$/i.test(shortLabel) &&
        el.closest('.el-notification,.notification,[role="alert"]')) return;
    if (t === 'BUTTON' && /^(取消|取\s*消|关闭|close|cancel|×)$/i.test(shortLabel)) return;
    const ch = channelFor(t);
    if (ch === 'ignore' && t !== 'EXTERNAL_LINK' && t !== 'EXTERNAL_FORM' && t !== 'EXTERNAL_IFRAME') return;
    const extra = {href: '', action: '', method: '', target: '', dialog_text: ''};
    const dialog = el.closest('[role="dialog"],[aria-modal="true"],dialog');
    if (dialog) extra.dialog_text = txt(dialog, 600);
    if (t === 'LINK' || t === 'DOWNLOAD' || t === 'EXTERNAL_LINK' || t === 'AREA') extra.href = abs(el.getAttribute('href') || '');
    if (t === 'IFRAME' || t === 'FRAME' || t === 'EXTERNAL_IFRAME') extra.href = abs(el.getAttribute('src') || '');
    if (t === 'MENU_ITEM' && el.getAttribute('aria-controls')) extra.controls = [el.getAttribute('aria-controls')];
    if (el.getAttribute('aria-controls')) extra.controls = (extra.controls || []).concat(el.getAttribute('aria-controls').split(/\s+/));
    if (el.getAttribute('aria-expanded') !== null) extra.expanded = el.getAttribute('aria-expanded');
    if (el.hasAttribute('onclick')) extra.handler = 'onclick';
    else if (el.tagName.toLowerCase() === 'a') extra.handler = 'href';
    const o = addElement(el, t, ch, extra);
    if (o) {
      o.impact = impactFor(t, el);
      o.capture = (t === 'FORM') ? 'network' : (t === 'LINK' || t === 'IFRAME' || t === 'AREA' || t === 'META_REFRESH' ? 'navigation' : (o.channel === 'offer' ? 'dom' : 'none'));
    }
  });
  // add group candidates as elements too
  out.groups.forEach(g => {
    if (out.elements.length >= MAXC) return;
    const o = {id: 'cand_' + out.elements.length, type: 'FORM', channel: 'offer',
               tag: g.synthetic ? 'div' : 'form', role: '', name: g.submit_text || g.text.slice(0, 80),
               text: g.text, selector: g.selector, visible: true, disabled: false,
               href: '', action: g.action, method: g.method, enctype: g.enctype,
               target: '', controls: [], expanded: '', handler: g.synthetic ? 'click' : 'onsubmit',
               fingerprint: g.fingerprint, dom_path: g.selector, synthetic: g.synthetic,
               group_id: g.id, impact: groupImpact(g),
               capture: 'network'};
    out.elements.push(o);
    g.element_id = o.id;
  });
  out.signature = fp([location.href, document.title,
                      document.body ? document.body.innerText.length : 0,
                      document.querySelectorAll('*').length].join('|'));
  out.forms = out.groups.length;
  out.native_forms = out.groups.filter(g => !g.synthetic).length;
  out.synthetic_forms = out.groups.filter(g => g.synthetic).length;
  out.fields = out.groups.reduce((n, g) => n + g.fields.length, 0);
  return JSON.stringify(out);
})()
"""


ELEMENT_DEFAULT_CHANNEL = {
    "LINK": "offer", "EXTERNAL_LINK": "ignore", "AREA": "offer", "EXTERNAL_AREA": "ignore",
    "FORM": "offer", "EXTERNAL_FORM": "ignore", "BUTTON": "offer", "DISCLOSURE": "offer",
    "ROLE_BUTTON": "offer", "ROLE_LINK": "offer", "TAB": "offer", "MENU_ITEM": "offer",
    "TREE_ITEM": "offer", "IFRAME": "offer", "EXTERNAL_IFRAME": "ignore", "FRAME": "offer",
    "CLICKABLE": "offer", "DRAGGABLE": "offer", "DOWNLOAD": "collect",
    "META_REFRESH": "offer", "DIALOG_STATE": "ignore", "CUSTOM": "ignore",
}


class EventLog:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.events = open(out_dir / "events.jsonl", "a", encoding="utf-8")
        self.run = open(out_dir / "run.log", "a", encoding="utf-8")

    def __call__(self, kind: str, **data: Any) -> None:
        rec = {"ts": utcnow(), "kind": kind, **data}
        self.events.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        self.events.flush()
        if kind in ("run_start", "run_end", "page", "action", "form", "safety", "jev", "error",
                    "auth_oracle", "bootstrap", "session", "metric", "finding"):
            line = f"{rec['ts']} {kind} " + json.dumps(
                {k: v for k, v in data.items() if k not in ("request", "response")},
                ensure_ascii=False, default=str,
            )[:1200]
            self.run.write(line + "\n")
            self.run.flush()

    def close(self) -> None:
        self.events.close()
        self.run.close()


def infer_field_name(field: dict[str, Any], index: int) -> tuple[str, str]:
    name = str(field.get("name") or "").strip()
    if name:
        return name, "dom_name"
    blob = re.sub(r"\s+", "", " ".join(str(field.get(k, "")) for k in ("placeholder", "label", "id", "type")).lower())
    table = [
        (("账号", "username", "user name"), "username"),
        (("密码", "password", "passwd"), "password"),
        (("真实姓名", "姓名", "name"), "name"),
        (("电话", "phone", "mobile", "tel"), "phone"),
        (("e-mail", "email", "邮箱", "mail"), "email"),
        (("标题", "title", "subject"), "title"),
        (("搜索", "search", "keyword", "query"), "search"),
        (("内容", "content", "body", "abstract", "描述", "description"), "content"),
        (("日期", "date", "time"), "date"),
        (("数量", "number", "count", "age", "size", "page"), "number"),
        (("url", "链接", "link", "地址"), "url"),
        (("文件", "file", "cover", "upload", "图片"), "file"),
    ]
    for keys, value in table:
        if any(k in blob for k in keys):
            return value, "placeholder_label"
    return f"field_{index}", "positional"


def infer_field_kind(field: dict[str, Any]) -> str:
    t = str(field.get("type") or "").lower()
    if t in ("email",):
        return "email"
    if t in ("password",):
        return "password"
    if t in ("tel",):
        return "phone"
    if t in ("number", "range"):
        return "number"
    if t in ("date", "datetime-local", "month", "week", "time"):
        return "date"
    if t == "url":
        return "url"
    if t == "file":
        return "file"
    if t == "search":
        return "search"
    name = infer_field_name(field, 0)[0]
    if name in VALUE_CATALOGUE:
        return name
    if name == "content":
        return "text_long"
    label = " ".join(str(field.get(k, "")) for k in ("placeholder", "label", "name")).lower()
    if any(w in label for w in ("标题", "title", "subject")):
        return "title"
    if any(w in label for w in ("内容", "content", "body", "描述", "abstract")):
        return "text_long"
    if any(w in label for w in ("搜索", "search", "keyword")):
        return "search"
    return "text_short" if len(label) < 20 else "text_long"


def value_shape(value: str) -> dict[str, Any]:
    return {"type": "string" if not str(value).isdigit() else "number",
            "len_bucket": min(len(str(value)) // 8, 12)}


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


class Crawl:
    def __init__(self, runner: Runner, cdp: Cdp, jev: Jev, log: EventLog,
                 out_dir: Path, run_id: str, max_actions: int, deadline: float) -> None:
        self.runner = runner
        self.cdp = cdp
        self.jev = jev
        self.log = log
        self.out_dir = out_dir
        self.run_id = run_id
        self.max_actions = max_actions
        self.deadline = deadline
        self.pages: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []
        self.removed: list[dict[str, Any]] = []
        self.declared: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self.candidates_log = open(out_dir / "candidates.jsonl", "a", encoding="utf-8")
        self.forms_log = open(out_dir / "forms.jsonl", "a", encoding="utf-8")
        self.safety_log = open(out_dir / "safety.jsonl", "a", encoding="utf-8")
        self.values_log = open(out_dir / "values.jsonl", "a", encoding="utf-8")
        self.page_counter = 0
        self.action_counter = 0
        self.current_page: dict[str, Any] | None = None
        self.page_stack: list[dict[str, Any]] = []
        self.snapshot_cache: dict[str, dict[str, Any]] = {}
        self.consumed: dict[str, set[str]] = defaultdict(set)
        self.cli_snapshots: list[dict[str, Any]] = []
        self.visited_routes: set[str] = set()
        self.action_started = 0.0
        self.forms_attempted = 0
        self.forms_succeeded = 0
        self.fields_total = 0
        self.fields_filled = 0
        self.fields_in_network = 0
        self.compliance_checks = 0
        self.compliance_pass = 0
        self.policy_fallbacks = 0
        self.stale_elements = 0
        self.no_ops = 0
        self.form_records: list[dict[str, Any]] = []
        self.submitted_forms: set[str] = set()
        self.forms_skipped_duplicate = 0

    def _depth(self, page: dict[str, Any]) -> int:
        return int(page.get("depth") or 0)

    def _cache_key(self, url: str, path: list[str]) -> str:
        return sha(normalize_url(url) + "|" + ">".join(path))

    def _record_error(self, stage: str, error: Any, **extra: Any) -> None:
        rec = {"ts": utcnow(), "stage": stage, "error": error, **extra}
        self.errors.append(rec)
        self.log("error", **rec)

    async def cli_snapshot(self) -> str:
        res = await self.runner.cli("snapshot", ("-i", "-c"), timeout=60)
        if not res.success:
            self._record_error("snapshot", res.error)
            return ""
        text = res.data if isinstance(res.data, str) else json.dumps(res.data)
        return text

    async def project(self, page: dict[str, Any] | None = None, include_cli: bool = True) -> dict[str, Any]:
        res = await self.runner.eval_file(PROJECTION_PATH, timeout=90)
        if not res.success:
            self._record_error("projection", res.error, page=self.current_page.get("page_visit_id") if self.current_page else None)
            return {"url": "", "elements": [], "groups": [], "error": res.error}
        raw = res.data
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception as exc:
            self._record_error("projection_parse", str(exc), raw=str(raw)[:300])
            return {"url": "", "elements": [], "groups": [], "error": str(exc)}
        if not isinstance(data, dict):
            self._record_error("projection_shape", type(data).__name__)
            return {"url": "", "elements": [], "groups": [], "error": "shape"}
        data["cli_snapshot"] = None
        if include_cli:
            snapshot = await self.cli_snapshot()
            data["cli_snapshot"] = {"chars": len(snapshot), "lines": snapshot.count("\n") + 1 if snapshot else 0,
                                    "refs": len(re.findall(r"\[ref=e\d+\]", snapshot))}
            self.cli_snapshots.append({"page_id": page.get("page_visit_id") if page else None,
                                       "url": data.get("url"), **data["cli_snapshot"]})
        self.log("projection", page=page.get("page_visit_id") if page else None,
                 url=data.get("url"), title=data.get("title"), elements=len(data.get("elements", [])),
                 groups=len(data.get("groups", [])), native_forms=data.get("native_forms"),
                 synthetic_forms=data.get("synthetic_forms"), fields=data.get("fields"),
                 cli_snapshot=data.get("cli_snapshot"))
        return data

    def _group_for(self, candidate: dict[str, Any], proj: dict[str, Any]) -> dict[str, Any] | None:
        gid = candidate.get("group_id")
        if not gid:
            return None
        for group in proj.get("groups", []):
            if group.get("id") == gid:
                return group
        return None

    def _candidate_label(self, candidate: dict[str, Any]) -> str:
        bits = [candidate.get("type"), candidate.get("name") or candidate.get("text")]
        if candidate.get("href"):
            bits.append(str(candidate["href"])[:120])
        if candidate.get("action"):
            bits.append(str(candidate["action"])[:120])
        return " | ".join(str(b) for b in bits if b)

    def _semantic_key(self, candidate: dict[str, Any]) -> str:
        group = candidate.get("_group") or {}
        fields = ",".join(sorted(
            f"{f.get('name') or ''}:{f.get('type') or ''}:{f.get('placeholder') or ''}"
            for f in group.get("fields", [])
        ))
        parts = [candidate.get("type"), candidate.get("role"), candidate.get("name"),
                 (candidate.get("text") or "")[:80], candidate.get("href"),
                 candidate.get("action"), candidate.get("method"), fields,
                 candidate.get("dom_path")]
        return sha("|".join(str(p or "") for p in parts))

    def _offered(self, page: dict[str, Any], proj: dict[str, Any]) -> list[dict[str, Any]]:
        key = page["cache_key"]
        seen = set()
        out = []
        candidates = list(proj.get("elements", [])) + list(page.get("extra_elements", []))
        for cand in candidates:
            if cand.get("channel") != "offer":
                continue
            if not cand.get("visible", True):
                continue
            if cand.get("disabled"):
                continue
            fp = cand.get("fingerprint") or ""
            sk = self._semantic_key(cand)
            if not fp or fp in self.consumed[key] or sk in self.consumed[key] or sk in seen:
                continue
            seen.add(sk)
            cand = dict(cand)
            group = self._group_for(cand, proj)
            if group:
                cand["_group"] = group
            if cand.get("type") in ("LINK", "AREA", "META_REFRESH") and cand.get("href"):
                if normalize_url(cand["href"]) in self.visited_routes:
                    continue
            out.append(cand)
        return out

    def _consume(self, page: dict[str, Any], candidate: dict[str, Any]) -> None:
        key = page["cache_key"]
        fp = candidate.get("fingerprint") or sha(self._candidate_label(candidate))
        self.consumed[key].add(fp)
        self.consumed[key].add(self._semantic_key(candidate))
        candidate["fingerprint"] = fp

    def _log_candidate(self, page: dict[str, Any], candidate: dict[str, Any], channel: str, reason: str) -> None:
        rec = {"ts": utcnow(), "run_id": self.run_id, "page_id": page.get("page_visit_id"),
               "url": page.get("url"), "candidate_id": candidate.get("id"),
               "type": candidate.get("type"), "channel": channel, "name": candidate.get("name"),
               "text": candidate.get("text"), "href": candidate.get("href"),
               "impact": candidate.get("impact"), "fingerprint": candidate.get("fingerprint"),
               "reason": reason}
        self.candidates_log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.candidates_log.flush()

    async def _choose_removed(self, page: dict[str, Any], proj: dict[str, Any],
                              candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        removed: list[dict[str, Any]] = []
        remaining = list(candidates)
        for _ in range(len(candidates) + 1):
            if not remaining:
                break
            criteria = {}
            for cand in remaining:
                criteria[cand["id"]] = self._candidate_label(cand)
            criteria["none"] = "No candidate belongs to an unsafe category."
            state = {
                "page": {"url": page.get("url"), "title": proj.get("title")},
                "forbidden_categories": ["auth state", "payment", "destruction"],
                "safe_exceptions": ["account registration is a safe write"],
                "candidates": [{"id": c["id"], "type": c.get("type"), "name": c.get("name"),
                                "text": c.get("text"), "href": c.get("href"),
                                "action": c.get("action"),
                                "dialog_text": (c.get("dialog_text") or "")[:400]} for c in remaining],
            }
            questions = {"remove": {
                "type": "choice",
                "instructions": (
                    "You are removing unsafe elements from the crawl candidate set. "
                    "Forbidden categories: auth state, payment, destruction. "
                    "Account registration is a safe write, not auth state. "
                    "Do not remove a registration form. "
                    "Choose the single candidate that belongs to a forbidden category. "
                    "Choose none if no candidate belongs to a forbidden category. "
                    "Do not choose a candidate for any other reason."
                ),
                "criteria": criteria,
            }}
            answers = await self.jev.ask(state, questions, "choose_removed") if self.jev.enabled else None
            choice = None
            if answers and isinstance(answers.get("remove"), dict):
                choice = answers["remove"].get("choice")
            if not choice or choice == "none":
                break
            chosen = next((c for c in remaining if c["id"] == choice), None)
            if chosen is None:
                self._record_error("policy_stale_removal", {"choice": choice}, page=page.get("page_visit_id"))
                break
            self._remove(page, proj, chosen)
            removed.append(chosen)
            remaining.remove(chosen)
        return removed

    def _remove(self, page: dict[str, Any], proj: dict[str, Any], candidate: dict[str, Any]) -> None:
        self._consume(page, candidate)
        group = self._group_for(candidate, proj)
        rec = {"ts": utcnow(), "run_id": self.run_id, "page_id": page.get("page_visit_id"),
               "url": page.get("url"), "candidate_id": candidate.get("id"),
               "type": candidate.get("type"), "name": candidate.get("name"),
               "text": candidate.get("text"), "href": candidate.get("href"),
               "action": candidate.get("action"),
               "source": "jev", "synthetic": candidate.get("synthetic", False),
               "semantic_key": self._semantic_key(candidate)}
        self.removed.append(rec)
        self.safety_log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.safety_log.flush()
        self.log("safety", **rec)
        if group:
            self._collect_declared(page, candidate, group, reason="removed")
        elif candidate.get("channel") == "collect":
            self._collect_download(page, candidate)

    def _collect_download(self, page: dict[str, Any], candidate: dict[str, Any]) -> None:
        self.declared.append({"kind": "download", "page_id": page.get("page_visit_id"),
                              "url": candidate.get("href"), "candidate": self._candidate_label(candidate),
                              "provenance": "declared", "ts": utcnow()})

    def _collect_declared(self, page: dict[str, Any], candidate: dict[str, Any],
                          group: dict[str, Any], reason: str) -> None:
        action_url = group.get("action") or page.get("url") or ""
        method = (group.get("method") or ("POST" if group.get("synthetic") else "GET")).upper()
        path, base = split_url(action_url)
        endpoint_id = "ep_declared_" + sha(f"{method}|{action_url}|{group.get('enctype')}|{group.get('fingerprint')}")[:16]
        field_names = []
        params = []
        for i, field in enumerate(group.get("fields", [])):
            name, source = infer_field_name(field, i)
            if not name:
                continue
            field_names.append(name)
            params.append({
                "parameter_id": "param_declared_" + sha(f"{endpoint_id}|{name}|{i}")[:16],
                "endpoint_id": endpoint_id, "provenance": "declared",
                "endpoint_path": path, "baseurl": base,
                "position": "query" if method == "GET" else "body",
                "name": name, "name_source": source,
                "value_shape": None, "http_artifact_id": None, "content_type": None,
                "field_type": field.get("type"), "label": field.get("label"),
                "options": field.get("options") or [], "pattern": field.get("pattern") or None,
                "min": field.get("min") or None, "max": field.get("max") or None,
                "required": field.get("required", False), "visible": field.get("visible", True),
                "reason": reason,
            })
        endpoint = {
            "endpoint_id": endpoint_id, "provenance": "declared", "method": method,
            "url": action_url, "path": path, "baseurl": base, "status_code": None,
            "source": "steel", "resource_type": "form", "http_artifact_id": None,
            "source_page_id": page.get("page_visit_id"), "action_id": None,
            "enctype": group.get("enctype"), "field_names": field_names,
            "synthetic": group.get("synthetic"), "confidence": "low" if group.get("synthetic") else "medium",
            "submit_text": group.get("submit_text"), "reason": reason,
        }
        self.declared.append({"kind": "form", "endpoint": endpoint, "parameters": params,
                              "page_id": page.get("page_visit_id"), "group": group,
                              "candidate": self._candidate_label(candidate), "reason": reason,
                              "ts": utcnow()})
        self.log("declared", endpoint=endpoint, parameters=len(params), reason=reason)

    async def _choose_chosen(self, page: dict[str, Any], proj: dict[str, Any],
                             candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not candidates:
            return None
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for cand in candidates:
            groups[str(cand.get("impact") or "observe")].append(cand)
        lowest = next((impact for impact in IMPACT_ORDER if groups.get(impact)), None)
        criteria = {}
        for cand in candidates:
            dialog = (cand.get("dialog_text") or "").strip()
            criteria[cand["id"]] = (
                f"type={cand.get('type')} impact={cand.get('impact')} capture={cand.get('capture')} "
                f"name={cand.get('name') or cand.get('text')} href={cand.get('href') or ''} "
                f"action={cand.get('action') or ''} method={cand.get('method') or ''}"
                + (f" dialog={dialog[:240]}" if dialog else "")
            )
        criteria["none"] = "No candidate remains on this page."
        state = {
            "page": {"url": page.get("url"), "title": proj.get("title")},
            "impact_order": IMPACT_ORDER,
            "candidates": [{"id": c["id"], "type": c.get("type"), "name": c.get("name"),
                            "text": c.get("text"), "impact": c.get("impact"),
                            "capture": c.get("capture"), "href": c.get("href"),
                            "action": c.get("action"), "method": c.get("method"),
                            "controls": c.get("controls") or [],
                            "dialog_text": (c.get("dialog_text") or "")[:400],
                            "synthetic": c.get("synthetic", False)} for c in candidates],
        }
        questions = {"next": {
            "type": "choice",
            "instructions": (
                "You are choosing the next element to exercise on the current page. "
                "Impact order: observe, local_state, read, write, navigate. "
                "Choose the lowest non-empty impact class. "
                "Within the class, prefer known change semantics, then a candidate whose "
                "control facts show a hidden target with unconsumed candidates. "
                "Choose none if no candidate remains."
            ),
            "criteria": criteria,
        }}
        answers = await self.jev.ask(state, questions, "choose_chosen") if self.jev.enabled else None
        choice = None
        if answers and isinstance(answers.get("next"), dict):
            choice = answers["next"].get("choice")
        chosen = None
        if choice and choice != "none":
            chosen = next((c for c in candidates if c["id"] == choice), None)
            if chosen is None:
                self._record_error("policy_invalid_choice", {"choice": choice}, page=page.get("page_visit_id"))
        if chosen is None:
            if self.jev.enabled:
                self.policy_fallbacks += 1
            fallback_group = groups.get(lowest) if lowest else []
            chosen = fallback_group[0] if fallback_group else candidates[0]
            self.log("policy_fallback", page=page.get("page_visit_id"), choice=choice,
                     fallback=self._candidate_label(chosen), lowest=lowest)
        self.compliance_checks += 1
        if lowest and chosen.get("impact") == lowest:
            self.compliance_pass += 1
        self.log("choice", page=page.get("page_visit_id"), chosen=self._candidate_label(chosen),
                 impact=chosen.get("impact"), lowest=lowest, compliance=bool(lowest and chosen.get("impact") == lowest),
                 candidates=len(candidates), groups={k: len(v) for k, v in groups.items()})
        return chosen

    async def _choose_value(self, page: dict[str, Any], field: dict[str, Any], index: int) -> tuple[str, Any, str]:
        name, name_source = infer_field_name(field, index)
        kind = infer_field_kind(field)
        keys = [k for k, v in VALUE_CATALOGUE.items() if v["kind"] == kind and k != "none"]
        if not keys and kind in ("text_short", "text_long"):
            keys = [kind]
        if not keys:
            keys = ["text_short", "text_long"]
        if len(keys) == 1:
            key = keys[0]
            source = "single_match"
        else:
            criteria = {k: VALUE_CATALOGUE[k]["description"] for k in keys}
            criteria["none"] = "Leave the field empty."
            state = {"field": {"name": name, "type": field.get("type"), "label": field.get("label"),
                               "placeholder": field.get("placeholder"), "required": field.get("required"),
                               "pattern": field.get("pattern"), "min": field.get("min"),
                               "max": field.get("max"), "options": field.get("options")},
                     "catalogue": {k: VALUE_CATALOGUE[k] for k in keys}}
            questions = {"value": {
                "type": "choice",
                "instructions": (
                    "Choose the catalogue key whose value is the best valid probe for this field. "
                    "The executor types the value locally. Choose none to leave the field empty."
                ),
                "criteria": criteria,
            }}
            answers = await self.jev.ask(state, questions, "choose_value") if self.jev.enabled else None
            key = None
            if answers and isinstance(answers.get("value"), dict):
                key = answers["value"].get("choice")
            source = "jev" if self.jev.enabled else "deterministic"
            if not self.jev.enabled:
                key = keys[0]
            if key not in keys and key != "none":
                self._record_error("policy_invalid_value", {"choice": key, "field": name})
                key = keys[0]
                source = "fallback"
        value = VALUE_CATALOGUE[key]["value"] if key != "none" else None
        if isinstance(value, str):
            value = value.replace("<run>", self.run_id)
        if value is not None and field.get("pattern"):
            try:
                if not re.fullmatch(field["pattern"], str(value)):
                    self.log("value_pattern_mismatch", field=name, key=key, pattern=field["pattern"])
            except re.error:
                pass
        if value is not None and field.get("min") and str(value).isdigit():
            try:
                if int(value) < int(field["min"]):
                    value = field["min"]
            except Exception:
                pass
        if value is not None and field.get("max") and str(value).isdigit():
            try:
                if int(value) > int(field["max"]):
                    value = field["max"]
            except Exception:
                pass
        rec = {"ts": utcnow(), "run_id": self.run_id, "page_id": page.get("page_visit_id"),
               "field_index": index, "field_name": name, "name_source": name_source,
               "field_kind": kind, "key": key,
               "value": "<redacted>" if kind == "password" else value, "source": source,
               "placeholder": field.get("placeholder"), "label": field.get("label")}
        self.values_log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.values_log.flush()
        self.log("value", **rec)
        return key, value, source

    async def _fill_and_submit(self, page: dict[str, Any], candidate: dict[str, Any],
                               group: dict[str, Any]) -> dict[str, Any]:
        form_key = group.get("fingerprint") or sha(json.dumps(group, sort_keys=True, default=str))
        if form_key in self.submitted_forms:
            self.forms_skipped_duplicate += 1
            rec = {"ts": utcnow(), "run_id": self.run_id, "page_id": page.get("page_visit_id"),
                   "form_id": group.get("id"), "synthetic": group.get("synthetic"),
                   "submit_text": group.get("submit_text"), "selector": group.get("selector"),
                   "action": group.get("action"), "method": group.get("method"),
                   "fields": [], "field_names": [], "network_fields": [],
                   "submit_ok": False, "http_status": None, "request_url": None,
                   "request_method": None, "request_body": "", "success": None,
                   "after_url": page.get("url"), "skipped": "duplicate",
                   "error": None}
            self.forms_log.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self.forms_log.flush()
            self.form_records.append(rec)
            self.log("form", **rec)
            return rec
        self.forms_attempted += 1
        fields = group.get("fields", [])
        self.fields_total += len(fields)
        results = []
        body_started = time.time()
        self.cdp.current_page_id = page.get("page_visit_id")
        for i, field in enumerate(fields):
            ftype = str(field.get("type") or "").lower()
            selector = field.get("selector") or ""
            visible = field.get("visible", True)
            if not visible:
                results.append({"field": field.get("name") or field.get("placeholder"), "skipped": "hidden"})
                continue
            if ftype in ("hidden", "submit", "button", "reset", "image"):
                results.append({"field": field.get("name") or field.get("placeholder"), "skipped": ftype})
                continue
            if ftype == "file":
                res = await self.runner.cli("upload", (selector, "--", UPLOAD_PATH), timeout=60)
                results.append({"field": field.get("name") or field.get("placeholder"), "kind": "file",
                                "selector": selector, "ok": res.success, "error": res.error})
                if res.success:
                    self.fields_filled += 1
                continue
            if ftype in ("checkbox", "radio"):
                if not field.get("checked"):
                    res = await self.runner.cli("check", (selector,), timeout=60)
                    results.append({"field": field.get("name") or field.get("placeholder"),
                                    "kind": ftype, "ok": res.success, "error": res.error})
                    if res.success:
                        self.fields_filled += 1
                continue
            if ftype in ("select", "select-one", "select-multiple"):
                options = [o for o in field.get("options", []) if o.get("value") not in ("", None)]
                if options:
                    res = await self.runner.cli("select", (selector, "--", str(options[0]["value"])), timeout=60)
                    results.append({"field": field.get("name") or field.get("placeholder"),
                                    "kind": "select", "value": options[0]["value"],
                                    "ok": res.success, "error": res.error})
                    if res.success:
                        self.fields_filled += 1
                continue
            key, value, source = await self._choose_value(page, field, i)
            if value is None:
                results.append({"field": field.get("name") or field.get("placeholder"),
                                "kind": "text", "key": key, "skipped": "none"})
                continue
            res = await self.runner.cli("fill", (selector, "--", str(value)), timeout=60)
            await asyncio.sleep(0.45)
            readback = await self.runner.cli("get", ("value", selector), timeout=30)
            rb = readback.data if readback.success else None
            rb_value = rb.get("value") if isinstance(rb, dict) else rb
            ok = res.success and (rb_value is None or str(rb_value) == str(value))
            results.append({"field": field.get("name") or field.get("placeholder"),
                            "kind": "text", "key": key,
                            "value": "<redacted>" if ftype == "password" else value,
                            "selector": selector, "ok": ok,
                            "readback": "<redacted>" if ftype == "password" else rb,
                            "error": res.error or readback.error})
            if ok:
                self.fields_filled += 1
            else:
                self._record_error("field_fill", {"field": field.get("name") or field.get("placeholder"),
                                                  "selector": selector,
                                                  "error": res.error or readback.error,
                                                  "readback": rb})
        submit_selector = group.get("submit_selector") or ""
        submit_res = None
        if submit_selector:
            submit_res = await self.runner.cli("click", (submit_selector,), timeout=60)
        elif not group.get("synthetic") and group.get("selector"):
            js = f"(()=>{{const f=document.querySelector({json.dumps(group['selector'])});if(!f)return JSON.stringify({{ok:false}});if(f.requestSubmit){{f.requestSubmit();return JSON.stringify({{ok:true,how:'requestSubmit'}})}}f.submit();return JSON.stringify({{ok:true,how:'submit'}})}})()"
            submit_res = await self.runner.cli("eval", (js,), timeout=60)
        await asyncio.sleep(1.8)
        after_url = await self._get_url()
        submit_label = str(group.get("submit_text") or "").lower()
        methods = {"POST", "PUT", "PATCH", "DELETE"}
        if str(group.get("method") or "").upper() == "GET" or "搜索" in submit_label or "search" in submit_label:
            methods.add("GET")
        flows = [f for f in self.cdp.flows.values()
                 if f.received_at >= (body_started - 1.0)
                 and f.method.upper() in methods
                 and in_scope(f.url)]
        success_flow = None
        for flow in flows:
            if flow.response_status is not None and 200 <= flow.response_status < 400:
                success_flow = flow
                break
        body = success_flow.request_body if success_flow else ""
        present = set()
        if body:
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    present = set(parsed.keys())
            except Exception:
                try:
                    present = {k for k, _ in urllib.parse.parse_qsl(body, keep_blank_values=True)}
                except Exception:
                    present = set(re.findall(r'name="([^"]+)"', body))
        if success_flow:
            q = urllib.parse.urlsplit(success_flow.url).query
            present |= {k for k, _ in urllib.parse.parse_qsl(q, keep_blank_values=True)}
        field_names = [infer_field_name(f, i)[0] for i, f in enumerate(fields)]
        self.fields_in_network += len([n for n in field_names if n in present])
        success = bool(success_flow) and bool(submit_res and submit_res.success)
        if success:
            self.forms_succeeded += 1
        rec = {"ts": utcnow(), "run_id": self.run_id, "page_id": page.get("page_visit_id"),
               "form_id": group.get("id"), "synthetic": group.get("synthetic"),
               "submit_text": group.get("submit_text"), "selector": group.get("selector"),
               "action": group.get("action"), "method": group.get("method"),
               "fields": results, "field_names": field_names, "network_fields": sorted(present),
               "submit_ok": bool(submit_res and submit_res.success),
               "http_status": success_flow.response_status if success_flow else None,
               "request_url": success_flow.url if success_flow else None,
               "request_method": success_flow.method if success_flow else None,
               "request_body": redact_text(body)[:1500],
               "success": success, "after_url": after_url,
               "error": (submit_res.error if submit_res and not submit_res.success else None)}
        if success:
            self.submitted_forms.add(form_key)
        self.forms_log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.forms_log.flush()
        self.form_records.append(rec)
        self.log("form", **rec)
        return rec

    async def _get_url(self) -> str:
        res = await self.runner.cli("get", ("url",), timeout=30)
        if res.success:
            return str(res.data or "")
        return ""

    async def _execute(self, page: dict[str, Any], proj: dict[str, Any],
                       candidate: dict[str, Any]) -> dict[str, Any]:
        self.action_counter += 1
        action_id = f"act_{int(time.time() * 1000)}_{self.action_counter}"
        self.cdp.current_page_id = page.get("page_visit_id")
        self.cdp.current_action_id = action_id
        self.action_started = time.time()
        ctype = candidate.get("type")
        before_url = page.get("url") or ""
        result: dict[str, Any] = {"ok": False, "navigated": False, "url": before_url, "kind": ctype}
        rec = {"ts": utcnow(), "run_id": self.run_id, "action_id": action_id,
               "page_id": page.get("page_visit_id"), "element_type": ctype,
               "name": candidate.get("name"), "text": candidate.get("text"),
               "href": candidate.get("href"), "action": candidate.get("action"),
               "method": candidate.get("method"), "impact": candidate.get("impact"),
               "capture": candidate.get("capture"), "fingerprint": candidate.get("fingerprint"),
               "synthetic": candidate.get("synthetic", False), "outcome": "attempted"}
        group = candidate.get("_group")
        if ctype == "FORM" and group:
            form_rec = await self._fill_and_submit(page, candidate, group)
            duplicate = form_rec.get("skipped") == "duplicate"
            result["ok"] = True if duplicate else bool(form_rec.get("success"))
            result["duplicate_skipped"] = duplicate
            result["form"] = form_rec
            after = form_rec.get("after_url") or await self._get_url()
            result["url"] = before_url if duplicate else after
            result["navigated"] = False if duplicate else normalize_url(after) != normalize_url(before_url)
            result["already_loaded"] = True
            rec["form_success"] = form_rec.get("success")
            rec["form_http_status"] = form_rec.get("http_status")
            rec["request_url"] = form_rec.get("request_url")
            rec["duplicate_skipped"] = duplicate
        elif ctype in ("LINK", "AREA"):
            url = candidate.get("href") or ""
            if not url:
                result["error"] = "empty_href"
            else:
                result.update(ok=True, navigated=True, url=url, already_loaded=False)
        elif ctype in ("IFRAME", "FRAME", "META_REFRESH"):
            url = candidate.get("href") or ""
            result.update(ok=bool(url), navigated=True, url=url,
                          already_loaded=False, error=None if url else "no_url")
        else:
            selector = candidate.get("selector") or ""
            if not selector:
                result["error"] = "no_selector"
            else:
                click = await self.runner.cli("click", (selector,), timeout=60)
                await asyncio.sleep(1.0)
                after = await self._get_url()
                result.update(ok=click.success, navigated=normalize_url(after) != normalize_url(before_url),
                              url=after, error=click.error, already_loaded=True)
                if click.success:
                    try:
                        await self.runner.cli("wait", ("-l", "networkidle", "--timeout", "4000"), timeout=15)
                    except Exception:
                        pass
                if not click.success and "not found" in json.dumps(click.error or {}).lower():
                    self.stale_elements += 1
                    result["stale"] = True
        self.cdp.current_action_id = None
        rec.update(outcome="ok" if result.get("ok") else "error",
                   navigated=result.get("navigated"), result_url=result.get("url"),
                   error=result.get("error"))
        self.actions.append(rec)
        self.log("action", **rec)
        return {"action_id": action_id, "record": rec, **result}

    async def _open_page(self, url: str, parent: dict[str, Any] | None,
                         path: list[str], source: str, navigate: bool = True) -> dict[str, Any]:
        if navigate:
            nav = await self.runner.cli("navigate", (url, "--wait-until", "domcontentloaded"), timeout=90)
            if not nav.success:
                self._record_error("navigate", nav.error, url=url)
        await asyncio.sleep(0.5)
        final = await self._get_url() or url
        proj = await self.project()
        final = proj.get("url") or final
        self.page_counter += 1
        page_id = f"page_{int(time.time() * 1000)}_{self.page_counter}"
        key = self._cache_key(final, path)
        page = {"page_visit_id": page_id, "url": final, "requested_url": url,
                "title": proj.get("title"), "status": self._status_for(final),
                "status_source": self._status_source(final),
                "parent_page_id": parent.get("page_visit_id") if parent else None,
                "depth": (self._depth(parent) + 1) if parent else 0,
                "source": source, "cache_key": key, "navigation_path": list(path),
                "projection": proj, "extra_elements": [], "exhausted": False,
                "cli_snapshot": proj.get("cli_snapshot"), "signature": proj.get("signature"),
                "ts": utcnow()}
        self.pages.append(page)
        self.snapshot_cache[key] = proj
        self.visited_routes.add(normalize_url(final))
        self.log("page", page_id=page_id, url=final, title=page["title"], status=page["status"],
                 depth=page["depth"], source=source, candidates=len(proj.get("elements", [])),
                 groups=len(proj.get("groups", [])), cache_key=key)
        for cand in proj.get("elements", []):
            if cand.get("channel") == "collect":
                group = self._group_for(cand, proj)
                if group:
                    self._collect_declared(page, cand, group, "collect")
                else:
                    self._collect_download(page, cand)
                self._consume(page, cand)
            self._log_candidate(page, cand, cand.get("channel", ""), "projection")
        return page

    def _status_for(self, url: str) -> int | None:
        if not url.startswith("http"):
            return None
        target = normalize_url(url)
        for flow in reversed(list(self.cdp.flows.values())):
            if flow.resource_type == "Document" and flow.url.startswith("http") and in_scope(flow.url):
                if normalize_url(flow.url) == target:
                    return flow.response_status
        return None

    def _status_source(self, url: str) -> str:
        if not url.startswith("http"):
            return "none"
        target = normalize_url(url)
        for flow in reversed(list(self.cdp.flows.values())):
            if flow.resource_type == "Document" and flow.url.startswith("http") and in_scope(flow.url):
                if normalize_url(flow.url) == target:
                    return "document"
        return "spa_shell"

    async def restore(self, page: dict[str, Any]) -> None:
        nav = await self.runner.cli("navigate", (page["url"], "--wait-until", "domcontentloaded"), timeout=90)
        await asyncio.sleep(0.5)
        if not nav.success:
            self._record_error("restore", nav.error, url=page.get("url"))
        proj = await self.project(page, include_cli=False)
        if not proj.get("error"):
            page["projection"] = proj
            page["url"] = proj.get("url") or page["url"]
            self.snapshot_cache[page["cache_key"]] = proj
        self.log("restore", page=page.get("page_visit_id"), url=page.get("url"), success=nav.success)

    async def refresh_local(self, page: dict[str, Any]) -> None:
        old_signature = page.get("signature")
        proj = await self.project(page, include_cli=False)
        if proj.get("error"):
            return
        page["projection"] = proj
        page["url"] = proj.get("url") or page["url"]
        page["signature"] = proj.get("signature")
        self.snapshot_cache[page["cache_key"]] = proj
        recent_flows = [f for f in self.cdp.flows.values() if f.received_at >= self.action_started]
        changed = old_signature != proj.get("signature")
        if not changed and not recent_flows:
            self.no_ops += 1
        self.log("snapshot_refresh", page=page.get("page_visit_id"), url=page["url"],
                 elements=len(proj.get("elements", [])), groups=len(proj.get("groups", [])),
                 changed=changed, flows=len(recent_flows))
        for cand in proj.get("elements", []):
            if cand.get("channel") == "collect":
                group = self._group_for(cand, proj)
                if group:
                    self._collect_declared(page, cand, group, "collect")
                else:
                    self._collect_download(page, cand)
                self._consume(page, cand)
            if cand.get("channel") == "offer":
                self._log_candidate(page, cand, "offer", "post_local_state")

    async def crawl(self, seeds: list[str]) -> None:
        self.cdp.phase = "crawl"
        root = await self._open_page(seeds[0], None, [], "seed")
        stack: list[dict[str, Any]] = [root]
        for extra in seeds[1:]:
            url = urllib.parse.urljoin(TARGET_ROOT + "/", extra)
            if normalize_url(url) in self.visited_routes:
                continue
            extra_page = await self._open_page(url, root, [sha("extra:" + url)], "extra_seed")
            stack.append(extra_page)
            self.log("extra_seed", url=url, page=extra_page.get("page_visit_id"))
        while stack and time.time() < self.deadline and len(self.actions) < self.max_actions:
            page = stack[-1]
            if page.get("exhausted"):
                stack.pop()
                if stack:
                    await self.restore(stack[-1])
                continue
            proj = page.get("projection") or {}
            candidates = self._offered(page, proj)
            if not candidates:
                page["exhausted"] = True
                self.log("page_exhausted", page=page.get("page_visit_id"), url=page.get("url"))
                continue
            removed = await self._choose_removed(page, proj, candidates)
            for cand in removed:
                self._log_candidate(page, cand, "removed", "choose_removed")
            candidates = self._offered(page, proj)
            if not candidates:
                page["exhausted"] = True
                continue
            chosen = await self._choose_chosen(page, proj, candidates)
            if chosen is None:
                page["exhausted"] = True
                continue
            exec_result = await self._execute(page, proj, chosen)
            if exec_result.get("stale"):
                self._consume(page, chosen)
                continue
            self._consume(page, chosen)
            if exec_result.get("navigated") and normalize_url(exec_result.get("url") or "") != normalize_url(page.get("url") or ""):
                target_url = exec_result.get("url") or ""
                if normalize_url(target_url) in self.visited_routes:
                    self.log("duplicate_route", page=page.get("page_visit_id"), url=target_url,
                             action=chosen.get("fingerprint"))
                    await self.restore(page)
                    continue
                child = await self._open_page(
                    target_url, page, page["navigation_path"] + [chosen["fingerprint"]], "action",
                    navigate=not exec_result.get("already_loaded", False),
                )
                stack.append(child)
            else:
                await self.refresh_local(page)

    async def bootstrap(self, auth_file: str) -> bool:
        self.cdp.phase = "bootstrap"
        self.log("bootstrap", step="navigate_root")
        nav = await self.runner.cli("navigate", (TARGET_ROOT + "/", "--wait-until", "domcontentloaded"), timeout=90)
        if not nav.success:
            self._record_error("bootstrap_navigate", nav.error)
        await asyncio.sleep(0.6)
        auth = await self.runner.eval_file(auth_file, timeout=60)
        self.log("bootstrap", step="auth_fetch", success=auth.success, data=auth.data, error=auth.error)
        if not auth.success:
            self._record_error("bootstrap_auth", auth.error)
            return False
        set_local = await self.runner.cli("eval", ('localStorage.setItem("username", JSON.stringify("admin")); "ok"',), timeout=30)
        self.log("bootstrap", step="set_local_storage", success=set_local.success, error=set_local.error)
        nav2 = await self.runner.cli("navigate", (TARGET_ROOT + "/admin/dashboard", "--wait-until", "domcontentloaded"), timeout=90)
        await asyncio.sleep(0.8)
        self.log("bootstrap", step="admin_route", success=nav2.success, error=nav2.error)
        return nav2.success

    async def oracle(self) -> dict[str, Any]:
        self.cdp.phase = "oracle"
        js = (
            '(async()=>{const r=await fetch("/api/authentication",{redirect:"follow",credentials:"include",cache:"no-store"});'
            'const t=await r.text();return JSON.stringify({status:r.status,redirected:r.redirected,url:r.url,'
            'body:t.slice(0,200),local:localStorage.getItem("username")})})()'
        )
        res = await self.runner.cli("eval", (js,), timeout=60)
        rec = {"ts": utcnow(), "probe_url": "/api/authentication",
               "probe_source": "legacy_surface_gate", "note": "overview.auth_probe.url is missing",
               "raw": res.data, "error": res.error}
        if res.success:
            try:
                data = json.loads(res.data) if isinstance(res.data, str) else res.data
            except Exception:
                data = {}
            status = data.get("status")
            redirected = bool(data.get("redirected"))
            body = str(data.get("body") or "")
            local = data.get("local")
            if isinstance(status, int) and 200 <= status < 300 and not redirected and "身份认证成功" in body:
                rec["classification"] = "authenticated"
            elif status in (401, 403) or redirected or (isinstance(status, int) and 300 <= status < 400):
                rec["classification"] = "unauthenticated"
            else:
                rec["classification"] = "indeterminate"
            rec["client_state"] = local
            if rec["classification"] == "authenticated" and not local:
                rec["classification"] = "client_state_missing"
        else:
            rec["classification"] = "indeterminate"
        self.log("auth_oracle", **rec)
        return rec

    def _content_id(self, flow: Flow) -> str:
        canonical = json.dumps({
            "project": "steel-crawl-v2", "method": flow.method,
            "url": normalize_url(flow.url),
            "request_body_sha256": sha(flow.request_body) if flow.request_body else None,
            "status": flow.response_status,
            "response_body_sha256": flow.response_body_sha256,
        }, sort_keys=True).encode()
        return "http_" + base64.b32encode(hashlib.sha256(canonical).digest()).decode().lower().replace("=", "")[:26]

    def _extract_params(self, flow: Flow, endpoint_id: str, path: str, base: str) -> list[dict[str, Any]]:
        params = []
        p = urllib.parse.urlsplit(flow.url)
        for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True):
            params.append({"parameter_id": "param_obs_" + sha(f"{endpoint_id}|query|{k}")[:16],
                           "endpoint_id": endpoint_id, "provenance": "observed",
                           "endpoint_path": path, "baseurl": base, "position": "query",
                           "name": k, "value_shape": value_shape(v), "http_artifact_id": self._content_id(flow),
                           "content_type": "query", "field_type": None, "label": None,
                           "options": [], "pattern": None, "min": None, "max": None})
        body = flow.request_body or ""
        ctype = (flow.request_headers.get("content-type") or flow.request_headers.get("Content-Type") or "").lower()
        keys = []
        if "json" in ctype or body.strip().startswith("{"):
            try:
                parsed = json.loads(body)
                if isinstance(parsed, dict):
                    keys = list(parsed.keys())
            except Exception:
                pass
        elif "x-www-form-urlencoded" in ctype or "=" in body:
            keys = [k for k, _ in urllib.parse.parse_qsl(body, keep_blank_values=True)]
        elif "multipart/form-data" in ctype:
            keys = re.findall(r'name="([^"]+)"', body)
        for k in keys:
            params.append({"parameter_id": "param_obs_" + sha(f"{endpoint_id}|body|{k}")[:16],
                           "endpoint_id": endpoint_id, "provenance": "observed",
                           "endpoint_path": path, "baseurl": base, "position": "body",
                           "name": k, "value_shape": {"type": "unknown", "len_bucket": 0},
                           "http_artifact_id": self._content_id(flow), "content_type": ctype or None,
                           "field_type": None, "label": None, "options": [], "pattern": None,
                           "min": None, "max": None})
        segs = [s for s in p.path.split("/") if s]
        for i, seg in enumerate(segs):
            if re.fullmatch(r"\d+", seg) or re.fullmatch(r"[0-9a-fA-F-]{16,}", seg):
                name = (segs[i - 1] if i else "id") + "_id"
                params.append({"parameter_id": "param_obs_" + sha(f"{endpoint_id}|path|{name}|{i}")[:16],
                               "endpoint_id": endpoint_id, "provenance": "observed",
                               "endpoint_path": path, "baseurl": base, "position": "path",
                               "name": name, "value_shape": value_shape(seg),
                               "http_artifact_id": self._content_id(flow), "content_type": "path",
                               "field_type": None, "label": None, "options": [], "pattern": None,
                               "min": None, "max": None})
        return params

    def write_outputs(self, stop_reason: str, started: float, auth: dict[str, Any],
                      session_info: dict[str, Any], catalogue: Any) -> dict[str, Any]:
        out = self.out_dir
        (out / "pages.jsonl").write_text("".join(json.dumps(p, ensure_ascii=False, default=str) + "\n" for p in self.pages))
        (out / "actions.jsonl").write_text("".join(json.dumps(a, ensure_ascii=False, default=str) + "\n" for a in self.actions))
        (out / "removed.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in self.removed))
        for handle in (self.safety_log, self.candidates_log, self.forms_log, self.values_log):
            try:
                handle.close()
            except Exception:
                pass

        flows = list(self.cdp.flows.values())
        for flow in flows:
            if flow.url.startswith("data:"):
                continue
        flow_records = []
        for flow in flows:
            if not flow.url:
                continue
            flow_records.append({
                "flow_id": flow.request_id, "http_artifact_id": self._content_id(flow),
                "page_id": flow.page_id, "action_id": flow.action_id, "phase": flow.phase,
                "method": flow.method, "url": flow.url, "resource_type": flow.resource_type,
                "status": flow.response_status, "mime_type": flow.mime_type, "protocol": flow.protocol,
                "initiator": flow.initiator, "request_headers": {k: v for k, v in flow.request_headers.items()
                                                                 if k.lower() not in ("cookie", "authorization")},
                "request_body": redact_text(flow.request_body)[:4000],
                "response_body_len": flow.response_body_len,
                "response_body_sha256": flow.response_body_sha256,
                "body_truncated": flow.body_truncated, "body_error": flow.body_error,
                "finished": flow.finished, "error": flow.error,
            })
        (out / "flows.jsonl").write_text("".join(json.dumps(f, ensure_ascii=False, default=str) + "\n" for f in flow_records))

        scripts = {}
        for s in self.cdp.scripts.values():
            url = s.get("script_url") or ""
            if not url or s.get("phase") != "crawl":
                continue
            absolute = urllib.parse.urljoin(TARGET_ROOT + "/", url)
            scripts.setdefault(absolute, {"script_asset_id": "script_" + sha(absolute)[:16],
                                          "script_url": absolute, "script_id": s.get("script_id"),
                                          "provenance": {"page_url": s.get("page_url"), "page_id": s.get("page_id")}})
        (out / "scripts.jsonl").write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in scripts.values()))

        endpoints: dict[str, dict[str, Any]] = {}
        parameters: dict[str, dict[str, Any]] = {}
        graph_types = {"Document", "XHR", "Fetch", "Script"}
        graph_flows = [f for f in flows if f.phase == "crawl"]
        for flow in graph_flows:
            if not flow.url or not in_scope(flow.url) or flow.resource_type not in graph_types:
                continue
            path, base = split_url(flow.url)
            key = f"{flow.method}|{path}|{base}"
            endpoint_id = "ep_obs_" + sha(key)[:16]
            endpoints.setdefault(endpoint_id, {
                "endpoint_id": endpoint_id, "provenance": "observed", "method": flow.method,
                "url": flow.url, "path": path, "baseurl": base, "status_code": flow.response_status,
                "source": "steel", "resource_type": flow.resource_type,
                "http_artifact_id": self._content_id(flow), "source_page_id": flow.page_id,
                "action_id": flow.action_id, "enctype": None, "field_names": [],
            })
            for param in self._extract_params(flow, endpoint_id, path, base):
                parameters.setdefault(param["parameter_id"], param)
        for item in self.declared:
            if item.get("kind") != "form":
                continue
            ep = item["endpoint"]
            endpoints.setdefault(ep["endpoint_id"], ep)
            for param in item["parameters"]:
                parameters.setdefault(param["parameter_id"], param)

        duration_ms = int((time.time() - started) * 1000)
        xhr = [f for f in flows if f.resource_type in ("XHR", "Fetch")]
        xhr_with_response = [f for f in xhr if f.response_status is not None]
        xhr_with_body = [f for f in xhr if f.response_body_sha256]
        api = [f for f in flows if "/api/" in f.url and f.resource_type in ("XHR", "Fetch", "Document")]
        public_prefixes = ("/api/login", "/api/register", "/api/books", "/api/search", "/api/article",
                           "/api/categories", "/api/file", "/api/logout")
        api_auth = [f for f in api if not any(urllib.parse.urlsplit(f.url).path.startswith(p) for p in public_prefixes)]
        api_with_cookie = [f for f in api_auth if "cookie" in {k.lower() for k in f.request_headers}]
        api_anonymous = [f for f in api_auth if f not in api_with_cookie]
        local_state_actions = sum(1 for a in self.actions if a.get("impact") == "local_state")
        no_op_local_state_rate = (self.no_ops / local_state_actions) if local_state_actions else None
        no_op_all_actions_rate = (self.no_ops / len(self.actions)) if self.actions else None
        dispatched_forms = [f for f in self.form_records if f.get("request_url")]
        successful_forms = [
            f for f in dispatched_forms
            if isinstance(f.get("http_status"), int) and 200 <= f["http_status"] < 300
        ]
        form_method_mismatches = sum(
            1 for f in self.form_records
            if f.get("method") and f.get("request_method")
            and str(f.get("method")).upper() != str(f.get("request_method")).upper()
        )
        removed_modal_openers = [
            r for r in self.removed
            if r.get("type") in ("BUTTON", "ROLE_BUTTON")
            and any(w in str(r.get("name") or "") for w in ("添加", "编辑", "批量添加", "新增"))
        ]
        removed_declared_endpoints = sum(
            1 for d in self.declared if d.get("kind") == "form" and d.get("reason") == "removed"
        )
        metrics = {
            "run": {"run_id": self.run_id, "session": self.runner.session, "stop_reason": stop_reason,
                    "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(),
                    "finished_at": utcnow(), "duration_ms": duration_ms,
                    "target": TARGET_ROOT, "max_actions": self.max_actions},
            "counts": {"pages": len(self.pages), "actions": len(self.actions),
                       "removed": len(self.removed), "flows": len(flows),
                       "xhr_fetch": len(xhr), "scripts": len(scripts),
                       "endpoints": len(endpoints), "parameters": len(parameters),
                       "forms_attempted": self.forms_attempted, "forms_succeeded": self.forms_succeeded,
                       "errors": len(self.errors), "declared": len(self.declared)},
            "quality": {
                "impact_order_compliance": self.compliance_pass / self.compliance_checks if self.compliance_checks else None,
                "impact_order_checks": self.compliance_checks,
                "local_state_actions": local_state_actions,
                "navigate_actions": sum(1 for a in self.actions if a.get("navigated")),
                "form_submission_success_rate": (len(successful_forms) / len(dispatched_forms))
                                                if dispatched_forms else None,
                "form_submissions_dispatched": len(dispatched_forms),
                "form_submissions_2xx": len(successful_forms),
                "form_skipped_duplicate": self.forms_skipped_duplicate,
                "form_field_coverage": self.fields_filled / self.fields_total if self.fields_total else None,
                "form_network_field_match": self.fields_in_network / self.fields_total if self.fields_total else None,
                "xhr_capture_rate": len(xhr_with_response) / len(xhr) if xhr else None,
                "xhr_body_rate": len(xhr_with_body) / len(xhr) if xhr else None,
                "xhr_total": len(xhr), "xhr_with_response": len(xhr_with_response),
                "xhr_with_body": len(xhr_with_body),
                "safety_removed": len(self.removed),
                "safety_source": "jev",
                "policy_fallbacks": self.policy_fallbacks,
                "stale_elements": self.stale_elements,
                "no_op_actions": self.no_ops,
                "no_op_local_state_rate": no_op_local_state_rate,
                "no_op_all_actions_rate": no_op_all_actions_rate,
                "form_method_mismatches": form_method_mismatches,
                "removed_modal_openers": len(removed_modal_openers),
                "removed_declared_endpoints": removed_declared_endpoints,
                "auth_classification": auth.get("classification"),
                "anonymous_api_requests": len(api_anonymous),
                "api_requests_checked": len(api_auth),
                "api_with_cookie": len(api_with_cookie),
            },
            "capture": {"bytes": sum(f.response_body_len for f in flows),
                        "phase_flows": dict(Counter(f.phase or "unknown" for f in flows)),
                        "http_versions": dict(Counter(f.protocol or "unknown" for f in flows)),
                        "resource_types": dict(Counter(f.resource_type or "unknown" for f in flows)),
                        "realtime_events": len(self.cdp.realtime),
                        "console_events": len(self.cdp.console),
                        "exceptions": len(self.cdp.exceptions)},
            "policy": "jev" if self.jev.enabled else "deterministic",
            "jev": {"calls": self.jev.calls, "errors": self.jev.errors,
                    "input_tokens": self.jev.input_tokens, "output_tokens": self.jev.output_tokens,
                    "cost_usd": round(self.jev.cost, 6),
                    "latency_ms": {"p50": sorted(self.jev.latency_ms)[len(self.jev.latency_ms) // 2]
                                   if self.jev.latency_ms else None,
                                   "p95": sorted(self.jev.latency_ms)[int(len(self.jev.latency_ms) * 0.95)]
                                   if self.jev.latency_ms else None}},
            "errors": self.errors,
            "session": {"info": session_info, "catalogue": catalogue},
        }
        (out / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False, default=str))

        manifest = {
            "schema_version": "steel-crawl/v2",
            "run": {"crawl_run_id": self.run_id, "session_name": self.runner.session,
                    "account": "admin", "started_at": metrics["run"]["started_at"],
                    "finished_at": metrics["run"]["finished_at"], "stop_reason": stop_reason,
                    "partial": stop_reason != "frontier_empty",
                    "scope": [TARGET_NETLOC],
                    "auth": {"mode": "pre_authenticated_session", "oracle": auth}},
            "endpoints": sorted(endpoints.values(), key=lambda x: (x["provenance"], x["path"], x["method"])),
            "parameters": sorted(parameters.values(), key=lambda x: (x["provenance"], x["endpoint_path"], x["position"], x["name"])),
            "scripts": sorted(scripts.values(), key=lambda x: x["script_url"]),
            "realtime": self.cdp.realtime,
            "errors": self.errors,
            "stats": {"endpoints": len(endpoints), "parameters": len(parameters), "flows": len(flows),
                      "bytes": metrics["capture"]["bytes"], "duration_ms": duration_ms,
                      "removed_elements": len(self.removed), "unrecoverable_pages": 0,
                      "pages": len(self.pages), "actions": len(self.actions)},
        }
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str))

        lines = [
            "# Steel crawl prototype v2", "",
            f"- Run: `{self.run_id}`", f"- Session: `{self.runner.session}`",
            f"- Target: `{TARGET_ROOT}`", f"- Stop: `{stop_reason}`",
            f"- Auth: `{auth.get('classification')}` ({auth.get('probe_source')})",
            f"- Pages: {len(self.pages)}", f"- Actions: {len(self.actions)}",
            f"- Forms attempted / succeeded: {self.forms_attempted} / {self.forms_succeeded}",
            f"- Flows: {len(flows)} (XHR/Fetch {len(xhr)})", f"- Endpoints: {len(endpoints)}",
            f"- Parameters: {len(parameters)}", f"- Scripts: {len(scripts)}",
            f"- Removed: {len(self.removed)}", f"- Jev calls: {self.jev.calls} (errors {self.jev.errors})",
            f"- Errors: {len(self.errors)}", "",
            "## Quality", "",
            f"- Impact order compliance: {metrics['quality']['impact_order_compliance']}",
            f"- Form success rate: {metrics['quality']['form_submission_success_rate']}",
            f"- Field coverage: {metrics['quality']['form_field_coverage']}",
            f"- XHR capture rate: {metrics['quality']['xhr_capture_rate']}",
            f"- Jev removed: {metrics['quality']['safety_removed']}",
            f"- No-op local-state rate: {metrics['quality']['no_op_local_state_rate']}",
            f"- No-op all-actions rate: {metrics['quality']['no_op_all_actions_rate']}",
            f"- Anonymous API requests: {metrics['quality']['anonymous_api_requests']}", "",
            "## Pages", "",
        ]
        for p in self.pages:
            lines.append(f"- {p['url']} | {p.get('title') or ''} | depth {p.get('depth')} | from {p.get('source')}")
        lines += ["", "## Forms", ""]
        for line in (out / "forms.jsonl").read_text().splitlines():
            rec = json.loads(line)
            lines.append(f"- {rec.get('submit_text')} | synthetic={rec.get('synthetic')} | success={rec.get('success')} | http={rec.get('http_status')} | {rec.get('request_url')}")
        lines += ["", "## Removed", ""]
        for r in self.removed:
            lines.append(f"- {r.get('type')} `{r.get('name')}` | source={r.get('source')}")
        lines += ["", "## Errors", ""]
        for e in self.errors[:80]:
            lines.append(f"- {e.get('stage')}: {str(e.get('error'))[:300]}")
        (out / "report.md").write_text("\n".join(lines) + "\n")
        self.log("run_end", **metrics["quality"], counts=metrics["counts"], jev=metrics["jev"])
        return metrics


def prepare_remote(out_dir: Path) -> None:
    local = out_dir / "projection.js"
    local.write_text(PROJECTION_JS)
    subprocess.run(
        ["scp", "-q", "-o", "BatchMode=yes", str(local), f"{STEEL_HOST}:{PROJECTION_PATH}"],
        check=True,
    )
    remote = (
        f"chmod 600 {shlex.quote(PROJECTION_PATH)}; "
        f"printf 'crawl upload fixture\\n' > {shlex.quote(UPLOAD_PATH)}; "
        f"chmod 600 {shlex.quote(UPLOAD_PATH)}; "
        f"test -s {shlex.quote(AUTH_JS_PATH)}"
    )
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", STEEL_HOST, remote],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"remote preparation failed: {(proc.stderr or proc.stdout)[:500]}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=6.0)
    parser.add_argument("--max-actions", type=int, default=120)
    parser.add_argument("--tag", default="v2")
    parser.add_argument("--seed", default=TARGET_ROOT + "/")
    parser.add_argument("--extra-seed", default="")
    parser.add_argument("--policy", choices=("jev", "deterministic"), default="jev")
    parser.add_argument("--session", default="")
    parser.add_argument("--skip-bootstrap", action="store_true")
    parser.add_argument("--reuse-session", action="store_true")
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"crawl-{args.tag}-{ts}"
    out_dir = OUT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    log = EventLog(out_dir)
    session = args.session or f"steel-{args.tag}-{ts}"
    runner = Runner(session, log)
    started = time.time()
    deadline = started + args.minutes * 60
    cdp: Cdp | None = None
    crawl: Crawl | None = None
    session_info: dict[str, Any] = {}
    catalogue: Any = None
    auth: dict[str, Any] = {"classification": "not_run"}
    stop_reason = "error"
    owned = not args.reuse_session

    log("run_start", run_id=run_id, session=session, target=TARGET_ROOT,
        minutes=args.minutes, max_actions=args.max_actions, owned=owned)
    try:
        prepare_remote(out_dir)
        log("run_start", step="remote_prepared", projection=PROJECTION_PATH, auth=AUTH_JS_PATH)
        if owned:
            res = await runner.cli("start", ("--session-timeout", "900000", "--inactivity-timeout", "300000"), timeout=90)
            if not res.success:
                raise RuntimeError(f"session start failed: {res.error}")
            session_info = res.data if isinstance(res.data, dict) else {"data": res.data}
            log("session", step="start", **session_info)
            await asyncio.sleep(1)
        cdp = Cdp(out_dir, log)
        await cdp.connect()
        crawl = Crawl(runner, cdp, Jev(out_dir, log, enabled=(args.policy == "jev")),
                      log, out_dir, run_id, args.max_actions, deadline)
        if not args.skip_bootstrap:
            if not await crawl.bootstrap(AUTH_JS_PATH):
                raise RuntimeError("bootstrap failed")
        auth = await crawl.oracle()
        if auth.get("classification") != "authenticated":
            raise RuntimeError(f"auth_precondition_failed: {auth}")
        seeds = [args.seed] + [s.strip() for s in args.extra_seed.split(",") if s.strip()]
        await crawl.crawl(seeds)
        stop_reason = "session_deadline" if time.time() >= deadline else (
            "action_budget" if len(crawl.actions) >= args.max_actions else "frontier_empty")
    except Exception as exc:
        stop_reason = "error"
        if crawl is not None:
            crawl._record_error("run", str(exc))
        else:
            log("error", stage="run", error=str(exc))
    finally:
        if cdp is not None:
            try:
                await cdp.close()
            except BaseException:
                pass
        if owned:
            try:
                await runner.cli("stop", (), timeout=60)
            except Exception:
                pass
        try:
            cat = await runner.cli("sessions", (), timeout=30)
            catalogue = cat.data if cat.success else cat.error
        except Exception as exc:
            catalogue = {"error": str(exc)}
        if crawl is not None:
            try:
                metrics = crawl.write_outputs(stop_reason, started, auth, session_info, catalogue)
                print(json.dumps({"out_dir": str(out_dir), "metrics": metrics["quality"],
                                  "counts": metrics["counts"], "jev": metrics["jev"]}, indent=2))
            except Exception as exc:
                print(json.dumps({"out_dir": str(out_dir), "output_error": str(exc)}))
            try:
                await crawl.jev.close()
            except BaseException:
                pass
        log("run_end", stop_reason=stop_reason, catalogue=catalogue)
        log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
