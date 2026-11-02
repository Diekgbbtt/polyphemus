#!/usr/bin/env python3
"""Local Steel crawl prototype.

One process on the macOS side:
  - the pinned Steel CLI on the deployed host through SSH;
  - a passive CDP client on the published raw CDP port 9223 through an SSH tunnel;
  - one unified DFS over the target's same-origin pages;
  - a deterministic impact-order policy standing in for Jev;
  - a manifest v2 projection, a page/action ledger, and the captured flows.

This is an experiment, not production. It deliberately keeps the action surface
on the CLI: projection and action are `steel browser eval` calls; navigation is
`steel browser navigate`; the file upload is `steel browser upload`.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import shlex
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import websockets

HOST = "ubuntu@dj-viscon-workshop-1.vsos.ethz.ch"
BIN = "/tmp/steel-p0/steel-cli-x86_64-unknown-linux-gnu/steel"
API = "http://127.0.0.1:3000/v1"
SESSION = ""
SEED = "https://the-internet.herokuapp.com/"
SEED_HOST = "the-internet.herokuapp.com"
OUT_DIR = Path("docs/experiments/runs")
MAX_CDP_BODY = 262144
PAGE_ACTION_CAP = 40
PAGE_FORM_CAP = 10
RUN_MINUTES = 13

PROJECTION_JS = r"""
(() => {
  const MAX = 500;
  const out = [];
  let nextId = 0;
  const store = window.__crawl = {els: {}};
  const txt = (el, n) => (el.getAttribute('aria-label') || el.getAttribute('title') || el.getAttribute('alt') || el.getAttribute('placeholder') || el.innerText || el.value || '').replace(/\s+/g, ' ').trim().slice(0, n || 120);
  const abs = (u) => { try { return new URL(u, location.href).href; } catch (e) { return ''; } };
  const css = (el) => {
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [];
    let n = el;
    while (n && n.nodeType === 1 && parts.length < 5) {
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
  const visible = (el) => {
    try {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && !el.hidden;
    } catch (e) { return false; }
  };
  const add = (el, kind, frame) => {
    if (out.length >= MAX) return null;
    const id = nextId++;
    store.els[id] = el;
    const o = {
      id, kind, tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      name: txt(el), text: txt(el, 160),
      href: '', action: '', method: '', enctype: '',
      selector: css(el), frame: frame || '',
      shadow: !!el.getRootNode().host,
      visible: visible(el), disabled: !!el.disabled,
      onclick: el.hasAttribute('onclick'),
      hover: el.hasAttribute('onmouseover'),
      context: el.hasAttribute('oncontextmenu'),
      tabindex: el.getAttribute('tabindex') || '',
      draggable: el.getAttribute('draggable') || '',
      dialog: el.tagName.toLowerCase() === 'dialog' || el.getAttribute('role') === 'dialog' || el.getAttribute('aria-modal') === 'true',
      controls: el.getAttribute('aria-controls') || '',
      expanded: el.getAttribute('aria-expanded') || '',
      target: ''
    };
    out.push(o);
    return o;
  };
  const walk = (root, frame) => {
    let els = [];
    try {
      els = [...root.querySelectorAll('a[href],button,form,summary,iframe,frame,dialog,[role],[onclick],[tabindex],[draggable="true"],[onmouseover],[oncontextmenu],svg[onclick],canvas[onclick]')];
    } catch (e) { return; }
    for (const el of els) {
      if (out.length >= MAX) return;
      const tag = el.tagName.toLowerCase();
      if (['input', 'select', 'textarea'].includes(tag)) continue;
      if (el.closest('form') && tag === 'button') continue;
      const role = el.getAttribute('role') || '';
      if (['textbox', 'searchbox', 'combobox', 'checkbox', 'radio', 'switch', 'slider', 'spinbutton', 'option', 'listbox'].includes(role)) continue;
      if (tag === 'a') {
        const href = el.getAttribute('href') || '';
        if (!href || href.startsWith('#') || /^(javascript|mailto|tel|data|blob):/i.test(href)) { add(el, 'clickable', frame); continue; }
        const full = abs(href);
        let path = '';
        try { path = new URL(full).pathname; } catch (e) {}
        const ext = /\.(pdf|txt|zip|png|jpe?g|gif|csv|xlsx?|docx?|gz|tar|mp3|mp4)$/i;
        const isdl = el.hasAttribute('download') || ext.test(path) || ext.test(txt(el, 120));
        const o = add(el, isdl ? 'download' : 'link', frame);
        if (o) o.href = full;
        continue;
      }
      if (tag === 'iframe' || tag === 'frame') {
        const o = add(el, 'iframe', frame);
        if (o) o.href = abs(el.getAttribute('src') || '');
        continue;
      }
      if (tag === 'form') {
        const o = add(el, 'form', frame);
        if (o) {
          o.action = abs(el.getAttribute('action') || location.href);
          o.method = (el.getAttribute('method') || 'get').toUpperCase();
          o.enctype = el.getAttribute('enctype') || 'application/x-www-form-urlencoded';
          o.fields = [...el.querySelectorAll('input,select,textarea')].map(f => ({
            name: f.name || '',
            type: (f.type || f.tagName).toLowerCase(),
            selector: css(f),
            label: f.labels && f.labels[0] ? txt(f.labels[0]) : '',
            options: f.tagName === 'SELECT' ? [...f.options].map(x => ({value: x.value, text: txt(x, 80)})).slice(0, 20) : [],
            pattern: f.getAttribute('pattern') || '',
            min: f.getAttribute('min') || '',
            max: f.getAttribute('max') || '',
            required: !!f.required,
            checked: !!f.checked
          }));
        }
        continue;
      }
      if (tag === 'dialog' || role === 'dialog' || el.getAttribute('aria-modal') === 'true') {
        add(el, 'dialog', frame);
        continue;
      }
      if (tag === 'button' || tag === 'summary' || role || el.hasAttribute('onclick') || el.hasAttribute('tabindex') || el.getAttribute('draggable') === 'true' || el.hasAttribute('onmouseover') || el.hasAttribute('oncontextmenu')) {
        const o = add(el, tag === 'summary' ? 'disclosure' : (role || 'clickable'), frame);
        if (o && el.getAttribute('draggable') === 'true' && el.parentElement) {
          const sibs = [...el.parentElement.children].filter(x => x !== el);
          const t = sibs.find(x => x.getAttribute('draggable') === 'true' || x.getAttribute('ondrop') || /column|drop/.test(x.className || ''));
          if (t) o.target = css(t);
        }
      }
    }
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) walk(el.shadowRoot, frame ? frame + '>shadow:' + css(el) : 'shadow:' + css(el));
    }
    for (const fr of root.querySelectorAll('iframe,frame')) {
      try {
        const doc = fr.contentDocument;
        if (doc) walk(doc, frame ? frame + '>' + css(fr) : css(fr));
      } catch (e) {}
    }
  };
  walk(document, '');
  return JSON.stringify({url: location.href, title: document.title, chars: document.documentElement.outerHTML.length, elements: out});
})()
"""

ACTION_JS = r"""
(() => {
  const id = __ID__;
  const kind = __KIND__;
  const value = __VALUE__;
  const target = __TARGET__;
  const store = window.__crawl;
  const el = store && store.els ? store.els[id] : null;
  if (!el) return JSON.stringify({ok: false, reason: 'missing_element'});
  try {
    if (kind === 'click') { el.click(); return JSON.stringify({ok: true}); }
    if (kind === 'hover') {
      el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
      el.dispatchEvent(new MouseEvent('mouseenter', {bubbles: true}));
      return JSON.stringify({ok: true});
    }
    if (kind === 'context') {
      el.dispatchEvent(new MouseEvent('contextmenu', {bubbles: true, button: 2}));
      return JSON.stringify({ok: true});
    }
    if (kind === 'fill') {
      el.focus();
      el.value = value;
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      return JSON.stringify({ok: true});
    }
    if (kind === 'select') {
      el.value = value;
      el.dispatchEvent(new Event('input', {bubbles: true}));
      el.dispatchEvent(new Event('change', {bubbles: true}));
      return JSON.stringify({ok: true});
    }
    if (kind === 'check') {
      if (!el.checked) el.click();
      return JSON.stringify({ok: true});
    }
    if (kind === 'submit') {
      if (el.requestSubmit) el.requestSubmit(); else el.submit();
      return JSON.stringify({ok: true});
    }
    if (kind === 'drag') {
      const t = target ? document.querySelector(target) : null;
      if (!t) return JSON.stringify({ok: false, reason: 'no_target'});
      const dt = new DataTransfer();
      el.dispatchEvent(new DragEvent('dragstart', {bubbles: true, dataTransfer: dt}));
      t.dispatchEvent(new DragEvent('dragenter', {bubbles: true, dataTransfer: dt}));
      t.dispatchEvent(new DragEvent('dragover', {bubbles: true, dataTransfer: dt}));
      t.dispatchEvent(new DragEvent('drop', {bubbles: true, dataTransfer: dt}));
      el.dispatchEvent(new DragEvent('dragend', {bubbles: true, dataTransfer: dt}));
      return JSON.stringify({ok: true});
    }
    if (kind === 'scroll') {
      window.scrollTo(0, document.body.scrollHeight);
      return JSON.stringify({ok: true});
    }
    return JSON.stringify({ok: false, reason: 'unknown_kind'});
  } catch (e) {
    return JSON.stringify({ok: false, reason: String(e)});
  }
})()
"""

SCROLL_JS = "(() => { window.scrollTo(0, document.body.scrollHeight); return JSON.stringify({ok: true}); })()"

AUTH_LINK = ("basic auth", "digest auth", "logout", "sign out", "log out", "log-out", "sign-out")
DESTRUCT = ("delete", "destroy", "deactivate", "close account", "purge", "revoke")
PAY = ("pay", "purchase", "checkout", "donate")
FORM_AUTH = ("login", "sign in", "signin", "authenticate", "password", "reset", "mfa", "otp")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_cli(verb: str, args: tuple = (), timeout: int = 90) -> dict:
    remote_args = [BIN, "--api-url", API, "browser", verb, "--session", SESSION, "--json", *args]
    remote = " ".join(shlex.quote(a) for a in remote_args)
    try:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", HOST, remote],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": {"code": "ssh_timeout", "message": f"{verb} exceeded {timeout}s"}}
    text = (proc.stdout or "").strip()
    payload = None
    if text:
        try:
            payload = json.loads(text)
        except Exception:
            for line in text.splitlines():
                try:
                    payload = json.loads(line)
                    break
                except Exception:
                    continue
    if isinstance(payload, dict) and payload.get("success") is not False:
        return payload
    error = (payload or {}).get("error") or {
        "code": "cli_error",
        "message": ((proc.stderr or "") + text)[:500],
    }
    return {"success": False, "error": error, "returncode": proc.returncode}


def run_sessions() -> dict:
    remote = " ".join(shlex.quote(a) for a in [BIN, "--api-url", API, "browser", "sessions", "--json"])
    try:
        proc = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", HOST, remote],
            capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": {"code": "ssh_timeout"}}
    try:
        return json.loads(proc.stdout.strip())
    except Exception:
        return {"success": False, "error": {"code": "parse_error", "message": (proc.stdout or "")[:200]}}


async def cli(verb: str, args: tuple = (), timeout: int = 90) -> dict:
    return await asyncio.to_thread(run_cli, verb, args, timeout)


def get_page_ws() -> str:
    with urllib.request.urlopen("http://127.0.0.1:9223/json/list", timeout=10) as resp:
        items = json.load(resp)
    pages = [x for x in items if isinstance(x, dict) and x.get("type") == "page"]
    if not pages:
        raise RuntimeError("no page target")
    ws = pages[0].get("webSocketDebuggerUrl") or ""
    if ws.startswith("ws://localhost/"):
        return ws.replace("ws://localhost/", "ws://127.0.0.1:9223/", 1)
    if ws.startswith("ws://127.0.0.1/"):
        return ws.replace("ws://127.0.0.1/", "ws://127.0.0.1:9223/", 1)
    return ws


class Cdp:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.ws = None
        self.reader = None
        self.next_id = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.flows: dict[str, dict] = {}
        self.scripts: dict[str, dict] = {}
        self.realtime: list[dict] = []
        self.navigations: list[dict] = []
        self.dialogs: list[dict] = []
        self.page_url = ""
        self.current_page_id: str | None = None
        self.current_action_id: str | None = None
        self.events_fh = open(out_dir / "cdp_events.jsonl", "a")

    async def connect(self, url: str) -> None:
        self.ws = await websockets.connect(url, max_size=2**24, open_timeout=15)
        self.reader = asyncio.create_task(self._read())
        await self.send("Page.enable")
        await self.send("Network.enable", {"maxTotalBufferSize": 100000000, "maxResourceBufferSize": 10000000})
        await self.send("Network.setCacheDisabled", {"cacheDisabled": True})
        await self.send("Runtime.enable")
        await self.send("Debugger.enable")

    async def send(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        mid = self.next_id
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
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
                    self.events_fh.write(json.dumps(msg) + "\n")
                    self.events_fh.flush()
                except Exception:
                    pass
                self._event(method, params)
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    def _event(self, method: str, p: dict) -> None:
        if method == "Network.requestWillBeSent":
            rid = p.get("requestId")
            req = p.get("request") or {}
            self.flows[rid] = {
                "flow_id": rid,
                "request": req,
                "resource_type": p.get("type"),
                "initiator": p.get("initiator"),
                "frame_id": p.get("frameId"),
                "timestamp": p.get("timestamp"),
                "page_id": self.current_page_id,
                "action_id": self.current_action_id,
                "url": req.get("url", ""),
                "method": req.get("method", ""),
            }
        elif method == "Network.responseReceived":
            rid = p.get("requestId")
            f = self.flows.setdefault(rid or "", {"flow_id": rid})
            f["response"] = p.get("response") or {}
            f["resource_type"] = p.get("type") or f.get("resource_type")
        elif method == "Network.loadingFinished":
            rid = p.get("requestId")
            f = self.flows.setdefault(rid or "", {"flow_id": rid})
            f["finished"] = True
            f["encoded_data_length"] = p.get("encodedDataLength")
            asyncio.create_task(self._body(rid or ""))
        elif method == "Network.loadingFailed":
            rid = p.get("requestId")
            f = self.flows.setdefault(rid or "", {"flow_id": rid})
            f["error"] = p.get("errorText") or "failed"
        elif method.startswith("Network.webSocket"):
            self.realtime.append({"method": method, "params": p})
        elif method == "Debugger.scriptParsed":
            self.scripts[p.get("scriptId") or ""] = {
                "script_id": p.get("scriptId"),
                "script_url": p.get("url") or "",
                "page_url": self.page_url,
                "page_id": self.current_page_id,
            }
        elif method == "Page.frameNavigated":
            frame = p.get("frame") or {}
            self.navigations.append({"url": frame.get("url"), "frame_id": frame.get("id"), "parent_id": frame.get("parentId")})
            if not frame.get("parentId"):
                self.page_url = frame.get("url") or self.page_url
        elif method == "Page.javascriptDialogOpening":
            self.dialogs.append({"type": p.get("type"), "message": p.get("message")})
            asyncio.create_task(self._dialog())

    async def _body(self, rid: str) -> None:
        f = self.flows.get(rid)
        if not f:
            return
        if f.get("resource_type") not in ("Document", "XHR", "Fetch", "Script"):
            return
        try:
            res = await self.send("Network.getResponseBody", {"requestId": rid})
            result = res.get("result") or {}
            body = result.get("body") or ""
            f["body"] = body[:MAX_CDP_BODY]
            f["body_len"] = len(body)
            f["body_base64"] = bool(result.get("base64Encoded"))
            f["body_sha256"] = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()
        except Exception as exc:
            f["body_error"] = str(exc)

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


def normalize(u: str) -> str:
    p = urllib.parse.urlsplit(urllib.parse.urljoin(SEED, u))
    host = p.netloc.lower()
    path = p.path.rstrip("/") or "/"
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    q.sort()
    return urllib.parse.urlunsplit((p.scheme, host, path, urllib.parse.urlencode(q), ""))


def in_scope(u: str) -> bool:
    try:
        p = urllib.parse.urlsplit(u)
    except Exception:
        return False
    host = p.netloc.lower().split(":")[0]
    return p.scheme in ("http", "https") and (host == SEED_HOST or host.endswith("." + SEED_HOST))


def split_url(u: str) -> tuple[str, str]:
    p = urllib.parse.urlsplit(u)
    return p.path or "/", f"{p.scheme}://{p.netloc}"


def ekey(e: dict) -> str:
    parts = [
        e.get("kind", ""), e.get("tag", ""), e.get("role", ""), e.get("name", ""),
        e.get("href", ""), e.get("action", ""), e.get("method", ""),
    ]
    if e.get("kind") == "form":
        parts.append(",".join(sorted(str(f.get("name", "")) for f in e.get("fields", []))))
    return "|".join(str(x).lower() for x in parts)


def forbidden(e: dict) -> str | None:
    blob = " ".join(str(e.get(k, "")) for k in ("name", "text", "href", "action", "selector")).lower()
    if e.get("kind") == "form":
        if any(x in blob for x in FORM_AUTH + PAY + DESTRUCT):
            return "forbidden_form"
        if any(str(f.get("type")) == "password" for f in e.get("fields", [])):
            return "password_field"
        return None
    if e.get("kind") == "link":
        if any(x in blob for x in AUTH_LINK + PAY + DESTRUCT):
            return "forbidden_link"
    if e.get("kind") in ("clickable", "disclosure") or e.get("tag") in ("button", "summary"):
        if any(x in blob for x in DESTRUCT):
            return "forbidden_control"
    return None


def is_control(e: dict) -> bool:
    return e.get("kind") not in ("form", "link", "iframe", "download", "dialog") and bool(e.get("visible"))


def control_kind(e: dict) -> str:
    if e.get("draggable") == "true":
        return "drag"
    if e.get("hover"):
        return "hover"
    if e.get("context"):
        return "context"
    return "click"


def value_for(field: dict) -> str | None:
    t = str(field.get("type") or "").lower()
    if t in ("text", "search", "textarea", ""):
        return "test"
    if t == "email":
        return "qa@example.test"
    if t == "url":
        return "https://example.test/"
    if t == "tel":
        return "+10000000000"
    if t == "number":
        return "42"
    if t == "date":
        return "2026-01-01"
    if t == "datetime-local":
        return "2026-01-01T00:00"
    if t == "time":
        return "00:00"
    if t == "month":
        return "2026-01"
    if t == "week":
        return "2026-W01"
    if t == "color":
        return "#336699"
    if t == "range":
        return field.get("min") or "1"
    return None


@dataclass
class PageState:
    url: str
    parent_id: str | None
    depth: int
    source: str
    loaded: bool = False
    page_id: str | None = None
    link_index: int = 0
    links: list[str] = field(default_factory=list)
    consumed: set[str] = field(default_factory=set)


class Crawl:
    def __init__(self, cdp: Cdp, out_dir: Path) -> None:
        self.cdp = cdp
        self.out_dir = out_dir
        self.pages: list[dict] = []
        self.actions: list[dict] = []
        self.removed: list[dict] = []
        self.declared: list[dict] = []
        self.errors: list[dict] = []
        self.external: set[str] = set()
        self.downloads: set[str] = set()
        self.page_counter = 0
        self.action_counter = 0

    async def project(self, include_snapshot: bool) -> dict:
        snap = None
        if include_snapshot:
            s = await cli("snapshot", ("-i", "-c"), timeout=60)
            text = s.get("data") if isinstance(s.get("data"), str) else ""
            snap = {"chars": len(text), "lines": text.count("\n") + 1, "preview": text[:1000]}
        e = await cli("eval", (PROJECTION_JS,), timeout=60)
        if not e.get("success"):
            return {"error": e.get("error"), "elements": [], "snapshot": snap}
        raw = e.get("data")
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception as exc:
            return {"error": {"code": "projection_parse", "message": str(exc)}, "elements": [], "snapshot": snap}
        if not isinstance(data, dict):
            return {"error": {"code": "projection_shape"}, "elements": [], "snapshot": snap}
        data["snapshot"] = snap
        return data

    def status_for(self, url: str) -> int | None:
        target = normalize(url)
        for f in reversed(list(self.cdp.flows.values())):
            if f.get("resource_type") == "Document" and normalize(f.get("url", "")) == target:
                resp = f.get("response") or {}
                if isinstance(resp.get("status"), int):
                    return resp["status"]
        return None

    def record_visit(self, proj: dict, page: PageState, source: str | None = None, parent_id: str | None = None) -> str:
        self.page_counter += 1
        pv = f"page_{int(time.time() * 1000)}_{self.page_counter}"
        final = proj.get("url") or page.url
        rec = {
            "page_visit_id": pv,
            "url": final,
            "requested_url": page.url,
            "title": proj.get("title"),
            "status": self.status_for(final),
            "parent_page_visit_id": parent_id if parent_id is not None else page.parent_id,
            "depth": page.depth,
            "discovery_source": source or page.source,
            "snapshot": proj.get("snapshot"),
            "elements": len(proj.get("elements", [])),
            "timestamp": utcnow(),
        }
        self.pages.append(rec)
        page.page_id = pv
        page.url = final
        return pv

    def record_action(self, page: PageState, e: dict, kind: str, outcome: str = "attempted", error: dict | None = None) -> str:
        self.action_counter += 1
        aid = f"act_{int(time.time() * 1000)}_{self.action_counter}"
        rec = {
            "action_id": aid,
            "page_visit_id": page.page_id,
            "element_key": ekey(e),
            "element_kind": e.get("kind"),
            "kind": kind,
            "impact": self.impact(e),
            "outcome": outcome,
            "error": error,
            "timestamp": utcnow(),
        }
        self.actions.append(rec)
        return aid

    @staticmethod
    def impact(e: dict) -> str:
        kind = e.get("kind")
        if kind in ("link", "iframe"):
            return "navigate"
        if kind == "download":
            return "download"
        if kind == "form":
            return "navigate" if e.get("method") == "GET" else "write"
        return "local_state"

    def add_links(self, page: PageState, proj: dict) -> None:
        for e in proj.get("elements", []):
            kind = e.get("kind")
            if kind not in ("link", "iframe", "download"):
                continue
            u = e.get("href") or ""
            if not u:
                continue
            if kind == "download":
                self.downloads.add(u)
                continue
            if not e.get("visible"):
                continue
            if not in_scope(u):
                self.external.add(u)
                continue
            n = normalize(u)
            if n not in {normalize(x) for x in page.links} and u not in page.links:
                page.links.append(u)

    async def navigate(self, url: str, page: PageState, aid: str | None = None) -> dict:
        self.cdp.current_page_id = page.page_id
        self.cdp.current_action_id = aid
        res = await cli("navigate", (url, "--wait-until", "domcontentloaded"), timeout=90)
        self.cdp.current_action_id = None
        await asyncio.sleep(0.8)
        return res

    async def act(self, page: PageState, e: dict, kind: str, value: str = "", target: str = "") -> dict:
        js = (
            ACTION_JS.replace("__ID__", json.dumps(e.get("id")))
            .replace("__KIND__", json.dumps(kind))
            .replace("__VALUE__", json.dumps(value))
            .replace("__TARGET__", json.dumps(target))
        )
        aid = self.record_action(page, e, kind)
        self.cdp.current_page_id = page.page_id
        self.cdp.current_action_id = aid
        res = await cli("eval", (js,), timeout=60)
        self.cdp.current_action_id = None
        await asyncio.sleep(0.8)
        if not res.get("success"):
            self.actions[-1]["outcome"] = "error"
            self.actions[-1]["error"] = res.get("error")
            self.errors.append({"stage": "action", "page_id": page.page_id, "action_id": aid, "error": res.get("error")})
        else:
            self.actions[-1]["outcome"] = "ok"
        return res

    def declared_form(self, page: PageState, f: dict) -> dict:
        action = f.get("action") or page.url
        method = f.get("method") or "GET"
        enctype = f.get("enctype") or "application/x-www-form-urlencoded"
        path, base = split_url(action)
        fields = f.get("fields", [])
        endpoint_id = "ep_" + hashlib.sha1(f"declared|{method}|{action}|{enctype}|{','.join(sorted(str(x.get('name')) for x in fields))}".encode()).hexdigest()[:16]
        endpoint = {
            "endpoint_id": endpoint_id,
            "provenance": "declared",
            "method": method,
            "url": action,
            "path": path,
            "baseurl": base,
            "status_code": None,
            "source": "steel",
            "resource_type": "form",
            "http_artifact_id": None,
            "source_page_id": page.page_id,
            "action_id": None,
            "enctype": enctype,
            "field_names": [str(x.get("name")) for x in fields if x.get("name")],
        }
        params = []
        position = "query" if method == "GET" else "body"
        for field in fields:
            name = str(field.get("name") or "")
            if not name:
                continue
            params.append({
                "parameter_id": "param_" + hashlib.sha1(f"declared|{endpoint_id}|{position}|{name}".encode()).hexdigest()[:16],
                "endpoint_id": endpoint_id,
                "provenance": "declared",
                "endpoint_path": path,
                "baseurl": base,
                "position": position,
                "name": name,
                "value_shape": None,
                "http_artifact_id": None,
                "content_type": None,
                "field_type": field.get("type"),
                "label": field.get("label"),
                "options": field.get("options") or [],
                "pattern": field.get("pattern") or None,
                "min": field.get("min") or None,
                "max": field.get("max") or None,
            })
        return {"endpoint": endpoint, "parameters": params}

    async def submit_form(self, page: PageState, f: dict) -> dict:
        aid = self.record_action(page, f, "form_submit")
        self.cdp.current_page_id = page.page_id
        self.cdp.current_action_id = aid
        try:
            for field in f.get("fields", []):
                t = str(field.get("type") or "").lower()
                sel = field.get("selector") or ""
                if not sel or t in ("hidden", "submit", "button", "reset", "image"):
                    continue
                if t == "file":
                    await cli("upload", (sel, "--", "/tmp/crawl-upload.txt"), timeout=60)
                elif t in ("checkbox", "radio"):
                    if not field.get("checked"):
                        await cli("check", (sel,), timeout=60)
                elif t == "select":
                    opts = [o for o in field.get("options", []) if o.get("value")]
                    if opts:
                        await cli("select", (sel, "--", str(opts[0]["value"])), timeout=60)
                else:
                    val = value_for(field)
                    if val is not None:
                        await cli("fill", (sel, "--", val), timeout=60)
            js = (
                ACTION_JS.replace("__ID__", json.dumps(f.get("id")))
                .replace("__KIND__", json.dumps("submit"))
                .replace("__VALUE__", json.dumps(""))
                .replace("__TARGET__", json.dumps(""))
            )
            res = await cli("eval", (js,), timeout=60)
            await asyncio.sleep(1.2)
            self.actions[-1]["outcome"] = "ok" if res.get("success") else "error"
            if not res.get("success"):
                self.actions[-1]["error"] = res.get("error")
                self.errors.append({"stage": "form_submit", "page_id": page.page_id, "action_id": aid, "error": res.get("error")})
            return res
        finally:
            self.cdp.current_action_id = None

    async def crawl(self, seed: str, deadline: float) -> None:
        stack = [PageState(seed, None, 0, "seed")]
        visited = {normalize(seed)}
        await self.navigate(seed, stack[0])
        while stack and time.time() < deadline:
            page = stack[-1]
            if not page.loaded:
                proj = await self.project(True)
                if proj.get("error"):
                    self.errors.append({"stage": "project", "page_url": page.url, "error": proj.get("error")})
                    stack.pop()
                    continue
                if proj.get("url"):
                    page.url = proj["url"]
                    visited.add(normalize(page.url))
                self.record_visit(proj, page)
                self.add_links(page, proj)
                if proj.get("snapshot"):
                    await cli("eval", (SCROLL_JS,), timeout=30)
                    await asyncio.sleep(0.4)
                page.loaded = True

            # Local controls first: the lowest impact class the prototype uses.
            cap = 0
            while time.time() < deadline and cap < PAGE_ACTION_CAP:
                proj = await self.project(False)
                if proj.get("error"):
                    self.errors.append({"stage": "project_control", "page_url": page.url, "error": proj.get("error")})
                    break
                self.add_links(page, proj)
                controls = [e for e in proj.get("elements", []) if is_control(e) and ekey(e) not in page.consumed]
                if not controls:
                    break
                e = controls[0]
                page.consumed.add(ekey(e))
                cap += 1
                reason = forbidden(e)
                if reason:
                    self.removed.append({"page_id": page.page_id, "element_key": ekey(e), "kind": e.get("kind"), "name": e.get("name"), "reason": reason})
                    self.record_action(page, e, "removed", outcome="removed")
                    continue
                kind = control_kind(e)
                target = e.get("target") if kind == "drag" else ""
                await self.act(page, e, kind, target=target or "")

            # Forms: the write class.
            fcap = 0
            while time.time() < deadline and fcap < PAGE_FORM_CAP:
                proj = await self.project(False)
                if proj.get("error"):
                    self.errors.append({"stage": "project_form", "page_url": page.url, "error": proj.get("error")})
                    break
                forms = [e for e in proj.get("elements", []) if e.get("kind") == "form" and ekey(e) not in page.consumed]
                if not forms:
                    break
                f = forms[0]
                page.consumed.add(ekey(f))
                fcap += 1
                declared = self.declared_form(page, f)
                self.declared.append(declared)
                reason = forbidden(f)
                if reason:
                    self.removed.append({"page_id": page.page_id, "element_key": ekey(f), "kind": "form", "name": f.get("name"), "reason": reason})
                    self.record_action(page, f, "removed", outcome="removed")
                    continue
                before = page.url
                await self.submit_form(page, f)
                after_res = await cli("get", ("url",), timeout=30)
                after = after_res.get("data") if after_res.get("success") else None
                if isinstance(after, str) and after and normalize(after) != normalize(before):
                    result = await self.project(False)
                    if not result.get("error"):
                        self.record_visit(result, page, source="form_submit")
                await self.navigate(page.url, page)
                page.loaded = True

            # Page axis: one unvisited same-origin link.
            advanced = False
            while page.link_index < len(page.links):
                u = page.links[page.link_index]
                page.link_index += 1
                n = normalize(u)
                if n in visited:
                    continue
                visited.add(n)
                aid = self.record_action(page, {"kind": "link", "href": u}, "navigate")
                await self.navigate(u, page, aid)
                stack.append(PageState(u, page.page_id, page.depth + 1, "link"))
                advanced = True
                break
            if not advanced:
                stack.pop()


def write_outputs(crawl: Crawl, out_dir: Path, started: float, stop_reason: str, session_started: dict, catalogue: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pages.jsonl").write_text("".join(json.dumps(p) + "\n" for p in crawl.pages))
    (out_dir / "actions.jsonl").write_text("".join(json.dumps(a) + "\n" for a in crawl.actions))
    (out_dir / "removed.jsonl").write_text("".join(json.dumps(r) + "\n" for r in crawl.removed))

    flows = []
    for f in crawl.cdp.flows.values():
        req = f.get("request") or {}
        resp = f.get("response") or {}
        req_body = req.get("postData") or ""
        req_hash = hashlib.sha256(req_body.encode("utf-8", "replace")).hexdigest() if req_body else None
        resp_hash = f.get("body_sha256")
        canonical = json.dumps({
            "project": "crawl-proto",
            "method": f.get("method") or req.get("method") or "",
            "url": f.get("url") or req.get("url") or "",
            "request_body_sha256": req_hash,
            "status": resp.get("status"),
            "response_body_sha256": resp_hash,
        }, sort_keys=True).encode()
        artifact_id = "http_" + base64.b32encode(hashlib.sha256(canonical).digest()).decode().lower().replace("=", "")[:26]
        flow = {
            "http_artifact_id": artifact_id,
            "flow_id": f.get("flow_id"),
            "page_id": f.get("page_id"),
            "action_id": f.get("action_id"),
            "method": f.get("method") or req.get("method"),
            "url": f.get("url") or req.get("url"),
            "resource_type": f.get("resource_type"),
            "status": resp.get("status"),
            "mime_type": resp.get("mimeType"),
            "initiator": f.get("initiator"),
            "request_body_sha256": req_hash,
            "response_body_sha256": resp_hash,
            "response_body_len": f.get("body_len"),
            "body_preview": (f.get("body") or "")[:2000],
            "error": f.get("error"),
        }
        flows.append(flow)
    (out_dir / "flows.jsonl").write_text("".join(json.dumps(x) + "\n" for x in flows))

    scripts = {}
    for s in crawl.cdp.scripts.values():
        url = s.get("script_url") or ""
        if not url:
            continue
        absolute = urllib.parse.urljoin(SEED, url)
        if absolute not in scripts:
            scripts[absolute] = {
                "script_asset_id": "script_" + hashlib.sha1(absolute.encode()).hexdigest()[:16],
                "script_url": absolute,
                "script_id": s.get("script_id"),
                "provenance": {"page_url": s.get("page_url"), "page_id": s.get("page_id")},
            }
    (out_dir / "scripts.jsonl").write_text("".join(json.dumps(x) + "\n" for x in scripts.values()))

    endpoints: dict[str, dict] = {}
    parameters: dict[str, dict] = {}
    graph_types = {"Document", "XHR", "Fetch", "Script"}
    for f in crawl.cdp.flows.values():
        url = f.get("url") or (f.get("request") or {}).get("url") or ""
        if not url or not in_scope(url):
            continue
        if f.get("resource_type") not in graph_types:
            continue
        method = f.get("method") or (f.get("request") or {}).get("method") or "GET"
        resp = f.get("response") or {}
        path, base = split_url(url)
        eid = "ep_" + hashlib.sha1(f"observed|{method}|{url}".encode()).hexdigest()[:16]
        endpoints.setdefault(eid, {
            "endpoint_id": eid,
            "provenance": "observed",
            "method": method,
            "url": url,
            "path": path,
            "baseurl": base,
            "status_code": resp.get("status"),
            "source": "steel",
            "resource_type": f.get("resource_type"),
            "http_artifact_id": None,
            "source_page_id": f.get("page_id"),
            "action_id": f.get("action_id"),
            "enctype": None,
            "field_names": [],
        })
        for k, v in urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query, keep_blank_values=True):
            if k.lower().startswith("utm_"):
                continue
            pid = "param_" + hashlib.sha1(f"observed|{eid}|query|{k}".encode()).hexdigest()[:16]
            parameters.setdefault(pid, {
                "parameter_id": pid,
                "endpoint_id": eid,
                "provenance": "observed",
                "endpoint_path": path,
                "baseurl": base,
                "position": "query",
                "name": k,
                "value_shape": {"type": type(v).__name__, "len_bucket": min(len(v) // 16, 8)},
                "http_artifact_id": None,
                "content_type": None,
                "field_type": None,
                "label": None,
                "options": [],
                "pattern": None,
                "min": None,
                "max": None,
            })
    for d in crawl.declared:
        ep = d["endpoint"]
        endpoints.setdefault(ep["endpoint_id"], ep)
        for p in d["parameters"]:
            parameters.setdefault(p["parameter_id"], p)

    duration_ms = int((time.time() - started) * 1000)
    bytes_total = sum(int(f.get("body_len") or 0) for f in crawl.cdp.flows.values())
    manifest = {
        "schema_version": "steel-crawl/v2",
        "run": {
            "crawl_run_id": "crawl_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
            "session_name": SESSION,
            "account": None,
            "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(),
            "finished_at": utcnow(),
            "stop_reason": stop_reason,
            "partial": stop_reason != "frontier_empty",
            "scope": [SEED_HOST],
            "auth": {"mode": "public_fixture", "oracle": None, "note": "the prototype target has no project auth surface"},
        },
        "endpoints": sorted(endpoints.values(), key=lambda x: (x["provenance"], x["url"])),
        "parameters": sorted(parameters.values(), key=lambda x: (x["provenance"], x["endpoint_path"], x["name"])),
        "scripts": sorted(scripts.values(), key=lambda x: x["script_url"]),
        "realtime": crawl.cdp.realtime,
        "errors": crawl.errors,
        "stats": {
            "endpoints": len(endpoints),
            "parameters": len(parameters),
            "flows": len(crawl.cdp.flows),
            "bytes": bytes_total,
            "duration_ms": duration_ms,
            "removed_elements": len(crawl.removed),
            "unrecoverable_pages": 0,
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    lines = [
        "# Local crawl prototype",
        "",
        f"- Target: `{SEED}`",
        f"- Session: `{SESSION}`",
        f"- Stop: `{stop_reason}`",
        f"- Policy: deterministic impact order, no Jev",
        f"- Auth: public fixture, no oracle",
        f"- Pages: {len(crawl.pages)}",
        f"- Actions: {len(crawl.actions)}",
        f"- Flows: {len(crawl.cdp.flows)}",
        f"- Endpoints: {len(endpoints)}",
        f"- Parameters: {len(parameters)}",
        f"- Scripts: {len(scripts)}",
        f"- Removed: {len(crawl.removed)}",
        f"- External links: {len(crawl.external)}",
        f"- Downloads: {len(crawl.downloads)}",
        f"- Errors: {len(crawl.errors)}",
        "",
        "## Pages",
        "",
    ]
    for p in crawl.pages:
        lines.append(f"- {p['url']} | status {p['status']} | {p.get('title') or ''}")
    lines += ["", "## Removed", ""]
    for r in crawl.removed:
        lines.append(f"- {r.get('kind')} `{r.get('name')}` | {r.get('reason')}")
    lines += ["", "## External", ""]
    for u in sorted(crawl.external):
        lines.append(f"- {u}")
    lines += ["", "## Deviations", "",
              "- The Jev policy is replaced by a deterministic impact order.",
              "- The HTTP-history edge and the graph curator are not exercised; the flows are local evidence.",
              "- Standalone input/select/textarea controls are outside the element map and are not exercised.",
              "- Per-page action and form caps bound the prototype.",
              "- Iframe and shadow content is walked; OOPIF and worker auto-attach is not enabled.",
              "- Form result pages are recorded, not traversed as new pages.",
              "- Source maps are not fetched."]
    (out_dir / "report.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"out_dir": str(out_dir), "pages": len(crawl.pages), "flows": len(crawl.cdp.flows), "endpoints": len(endpoints), "parameters": len(parameters), "scripts": len(scripts), "removed": len(crawl.removed), "errors": len(crawl.errors)}, indent=2))


async def main() -> int:
    global SESSION
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    SESSION = f"crawl-proto-{ts}"
    out_dir = OUT_DIR / f"crawl-proto-{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    deadline = started + RUN_MINUTES * 60
    cdp: Cdp | None = None
    crawl: Crawl | None = None
    session_started: dict = {}
    catalogue: dict = {}
    stop_reason = "error"
    try:
        res = await cli("start", ("--session-timeout", "900000", "--inactivity-timeout", "300000"), timeout=90)
        if not res.get("success"):
            raise RuntimeError(f"session start failed: {res.get('error')}")
        session_started = res.get("data") or {}
        await asyncio.sleep(1)
        ws = await asyncio.to_thread(get_page_ws)
        cdp = Cdp(out_dir)
        await cdp.connect(ws)
        crawl = Crawl(cdp, out_dir)
        await crawl.crawl(SEED, deadline)
        stop_reason = "session_deadline" if time.time() >= deadline else "frontier_empty"
    except Exception as exc:
        stop_reason = "error"
        if crawl is not None:
            crawl.errors.append({"stage": "run", "error": {"code": "run_error", "message": str(exc)}})
        else:
            print(json.dumps({"error": str(exc)}))
    finally:
        if cdp is not None:
            try:
                await cdp.close()
            except BaseException:
                pass
        try:
            await cli("stop", (), timeout=60)
        except Exception:
            pass
        try:
            catalogue = await asyncio.to_thread(run_sessions)
        except Exception:
            catalogue = {}
        if crawl is not None and cdp is not None:
            try:
                write_outputs(crawl, out_dir, started, stop_reason, session_started, catalogue)
            except Exception as exc:
                print(json.dumps({"output_error": str(exc)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
