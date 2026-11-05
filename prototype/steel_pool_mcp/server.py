"""Lightweight Steel pool MCP server prototype.

One process owns two responsibilities:
1. A streamable-HTTP MCP server for browser start, execute, and end.
2. A pool manager that leases one Steel API worker per MCP session.

The worker is addressed by the server. The client never sees the worker URL.
The executor is configurable:
- ``cli`` runs the pinned Steel CLI. This is the authoritative path.
- ``api`` runs the Steel command API. This was the local fallback while the
  local API image's root CDP proxy rejected the CLI Host header.
The lease protocol under test is independent of the executor.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastmcp import Context, FastMCP

TTL_S = float(os.environ.get("STEEL_POOL_TTL_S", "15"))
WAIT_S = float(os.environ.get("STEEL_POOL_WAIT_S", "8"))
PORT = int(os.environ.get("STEEL_MCP_PORT", "8003"))
LOG_PATH = os.environ.get("STEEL_POOL_LOG", "/tmp/steel-pool-events.jsonl")
WORKER_URLS = [
    item.strip()
    for item in os.environ.get("STEEL_POOL_WORKERS", "").split(",")
    if item.strip()
]
EXECUTOR = os.environ.get("STEEL_EXECUTOR", "api").strip().lower()
STEEL_CLI = os.environ.get("STEEL_CLI", "/opt/localbin/.steel/steel")
USE_GUARD = os.environ.get("STEEL_GUARD", "0") == "1"
GUARD = os.environ.get("STEEL_GUARD_PATH", "/opt/kali/steel_guard.py")

_LOG_LOCK = threading.Lock()


def log(event: str, **fields: Any) -> None:
    record = {"ts": round(time.time(), 3), "event": event, **fields}
    line = json.dumps(record, default=str, sort_keys=True)
    with _LOG_LOCK:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass
    print(line, flush=True)


@dataclass
class Worker:
    name: str
    base_url: str
    lease: "Lease | None" = None


@dataclass
class Lease:
    lease_id: str
    mcp_session_id: str
    owner: str
    name: str
    worker: Worker
    session_id: str | None = None
    state: str = "starting"
    last_activity: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)


class Pool:
    def __init__(
        self,
        worker_urls: list[str],
        ttl_s: float,
        wait_s: float,
        executor: str = EXECUTOR,
        cli: str = STEEL_CLI,
        use_guard: bool = USE_GUARD,
        guard: str = GUARD,
    ) -> None:
        self.executor = executor
        self.cli = cli
        self.use_guard = use_guard
        self.guard = guard
        self.workers = [
            Worker(name=f"worker-{index + 1}", base_url=url)
            for index, url in enumerate(worker_urls)
        ]
        self.leases: dict[str, Lease] = {}
        self.by_mcp: dict[str, str] = {}
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.ttl_s = ttl_s
        self.wait_s = wait_s
        self.client = httpx.Client(timeout=60.0)

    def _free_worker_locked(self) -> Worker | None:
        for worker in self.workers:
            if worker.lease is None:
                return worker
        return None

    def acquire(
        self, mcp_session_id: str, name: str, owner: str
    ) -> tuple[Lease | None, dict | None]:
        with self.cond:
            existing_id = self.by_mcp.get(mcp_session_id)
            existing = self.leases.get(existing_id) if existing_id else None
            if existing and existing.state in ("starting", "active"):
                return existing, None

            deadline = time.monotonic() + self.wait_s
            while True:
                worker = self._free_worker_locked()
                if worker is not None:
                    lease = Lease(
                        lease_id=str(uuid.uuid4()),
                        mcp_session_id=mcp_session_id,
                        owner=owner,
                        name=name,
                        worker=worker,
                    )
                    worker.lease = lease
                    self.leases[lease.lease_id] = lease
                    self.by_mcp[mcp_session_id] = lease.lease_id
                    log(
                        "acquire",
                        lease_id=lease.lease_id,
                        mcp_session_id=mcp_session_id,
                        owner=owner,
                        name=name,
                        worker=worker.name,
                    )
                    return lease, None

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    log(
                        "wait",
                        mcp_session_id=mcp_session_id,
                        owner=owner,
                        name=name,
                        workers=len(self.workers),
                        leases=len(self.leases),
                    )
                    return None, {
                        "status": "wait",
                        "reason": "pool_exhausted",
                        "retry_after_ms": 1000,
                        "workers": len(self.workers),
                        "leases": len(self.leases),
                    }
                self.cond.wait(remaining)

    def create(self, lease: Lease, url: str | None = None) -> dict:
        worker = lease.worker
        try:
            if self.executor == "cli":
                data = self._cli_create(lease)
            else:
                response = self.client.post(
                    f"{worker.base_url}/v1/sessions", json={}
                )
                response.raise_for_status()
                data = response.json()
        except Exception:
            self._free_lease(lease, reason="create_failed")
            raise

        lease.session_id = str(data["id"])
        lease.state = "active"
        lease.last_activity = time.time()
        log(
            "created",
            lease_id=lease.lease_id,
            worker=worker.name,
            session_id=lease.session_id,
            name=lease.name,
        )
        if url:
            self.exec(lease, {"command": "navigate", "url": url})
        return data

    def exec(self, lease: Lease, command: dict) -> dict:
        if not lease.session_id:
            raise RuntimeError("the lease has no session")
        if self.executor == "cli":
            data = self._cli_exec(lease, command)
            lease.last_activity = time.time()
            log(
                "exec",
                lease_id=lease.lease_id,
                worker=lease.worker.name,
                session_id=lease.session_id,
                command=command.get("command"),
                ok=bool(data.get("success", True)),
            )
            return data
        response = self.client.post(
            f"{lease.worker.base_url}/v1/sessions/{lease.session_id}/commands",
            json={"commands": [command]},
        )
        response.raise_for_status()
        data = response.json()
        lease.last_activity = time.time()
        results = data.get("results") or [{}]
        log(
            "exec",
            lease_id=lease.lease_id,
            worker=lease.worker.name,
            session_id=lease.session_id,
            command=command.get("command"),
            ok=bool(results[0].get("ok")),
        )
        return data

    def release(self, lease: Lease, reason: str = "explicit") -> None:
        worker = lease.worker
        session_id = lease.session_id
        if session_id:
            try:
                if self.executor == "cli":
                    self._cli_stop(lease)
                else:
                    self.client.post(
                        f"{worker.base_url}/v1/sessions/{session_id}/release"
                    )
            except Exception as exc:  # noqa: BLE001 - release is best effort
                log(
                    "release_error",
                    lease_id=lease.lease_id,
                    worker=worker.name,
                    error=str(exc),
                )
                try:
                    self.client.post(
                        f"{worker.base_url}/v1/sessions/{session_id}/release"
                    )
                except Exception:
                    pass
        with self.cond:
            self._free_locked(lease)
        log(
            "release",
            lease_id=lease.lease_id,
            worker=worker.name,
            session_id=session_id,
            reason=reason,
        )

    def _cli_run(self, lease: Lease, args: list[str]) -> dict:
        api_url = lease.worker.base_url.rstrip("/") + "/v1"
        if self.use_guard:
            command = [sys.executable, self.guard, "--api-url", api_url, *args]
        else:
            command = [self.cli, "--api-url", api_url, *args]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        try:
            payload = json.loads(completed.stdout) if completed.stdout.strip() else {}
        except ValueError as exc:
            raise RuntimeError(
                f"CLI returned non-JSON (exit {completed.returncode}): "
                f"{completed.stderr[-300:]}"
            ) from exc
        if payload.get("success") is False or payload.get("error"):
            raise RuntimeError(
                str(payload.get("error") or payload.get("error_code") or "CLI error")
            )
        if not isinstance(payload, dict):
            raise RuntimeError("CLI returned no JSON object")
        return payload

    def _cli_create(self, lease: Lease) -> dict:
        payload = self._cli_run(
            lease,
            [
                "browser",
                "start",
                "--session",
                lease.name,
                "--session-timeout",
                "120000",
                "--inactivity-timeout",
                "60000",
                "--json",
            ],
        )
        data = payload.get("data")
        if not isinstance(data, dict) or not data.get("id"):
            raise RuntimeError("CLI start returned no session id")
        return data

    def _cli_exec(self, lease: Lease, command: dict) -> dict:
        verb = command.get("command")
        args: list[str]
        if verb == "navigate":
            args = ["browser", "navigate", str(command["url"])]
        elif verb == "eval":
            args = ["browser", "eval", str(command["script"])]
        elif verb == "get":
            args = ["browser", "get", str(command["what"])]
        elif verb == "tab":
            args = ["browser", "tab", "list"]
        else:
            raise RuntimeError(f"unsupported CLI command: {verb}")
        args.extend(["--session", lease.name, "--json"])
        return self._cli_run(lease, args)

    def _cli_stop(self, lease: Lease) -> dict:
        return self._cli_run(
            lease,
            ["browser", "stop", "--session", lease.name, "--json"],
        )

    def _free_lease(self, lease: Lease, reason: str) -> None:
        with self.cond:
            self._free_locked(lease)
        log(
            "release",
            lease_id=lease.lease_id,
            worker=lease.worker.name,
            session_id=lease.session_id,
            reason=reason,
        )

    def _free_locked(self, lease: Lease) -> None:
        if lease.lease_id in self.leases:
            del self.leases[lease.lease_id]
        if self.by_mcp.get(lease.mcp_session_id) == lease.lease_id:
            del self.by_mcp[lease.mcp_session_id]
        lease.worker.lease = None
        lease.state = "released"
        self.cond.notify_all()

    def get(self, mcp_session_id: str) -> Lease | None:
        with self.lock:
            lease_id = self.by_mcp.get(mcp_session_id)
            lease = self.leases.get(lease_id) if lease_id else None
            if lease and lease.state == "active":
                return lease
        return None

    def status(self) -> dict:
        with self.lock:
            return {
                "workers": [
                    {
                        "name": worker.name,
                        "base_url": worker.base_url,
                        "lease_id": worker.lease.lease_id if worker.lease else None,
                        "session_id": worker.lease.session_id if worker.lease else None,
                        "session_name": worker.lease.name if worker.lease else None,
                    }
                    for worker in self.workers
                ],
                "leases": [
                    {
                        "lease_id": lease.lease_id,
                        "mcp_session_id": lease.mcp_session_id,
                        "owner": lease.owner,
                        "name": lease.name,
                        "worker": lease.worker.name,
                        "session_id": lease.session_id,
                        "state": lease.state,
                        "age_s": round(time.time() - lease.created_at, 2),
                        "idle_s": round(time.time() - lease.last_activity, 2),
                    }
                    for lease in self.leases.values()
                ],
            }

    def release_owner(self, owner: str, reason: str = "owner_stop") -> int:
        with self.lock:
            leases = [lease for lease in self.leases.values() if lease.owner == owner]
        for lease in leases:
            self.release(lease, reason=reason)
        return len(leases)

    def reap_loop(self) -> None:
        while True:
            time.sleep(2)
            now = time.time()
            with self.lock:
                expired = [
                    lease
                    for lease in self.leases.values()
                    if now - lease.last_activity > self.ttl_s
                ]
            for lease in expired:
                log(
                    "ttl",
                    lease_id=lease.lease_id,
                    worker=lease.worker.name,
                    session_id=lease.session_id,
                    idle_s=round(now - lease.last_activity, 2),
                )
                self.release(lease, reason="ttl")


pool = Pool(WORKER_URLS, TTL_S, WAIT_S)
mcp = FastMCP("steel-pool")


def _lease(ctx: Context) -> Lease | None:
    return pool.get(ctx.session_id)


async def _report(ctx: Context, value: float, total: float, message: str) -> None:
    try:
        await ctx.report_progress(value, total, message)
    except Exception:  # noqa: BLE001 - progress is diagnostic only
        pass


@mcp.tool()
async def browser_start(
    name: str,
    url: str | None = None,
    owner: str = "default",
    ctx: Context = None,
) -> dict:
    """Lease a worker and create one live browser session."""
    assert ctx is not None
    lease, wait = await asyncio.to_thread(
        pool.acquire, ctx.session_id, name, owner
    )
    if wait is not None:
        return wait
    assert lease is not None
    try:
        data = await asyncio.to_thread(pool.create, lease, url)
    except Exception as exc:  # noqa: BLE001 - create is a contract boundary
        return {"status": "error", "error": f"create_failed: {exc}"}
    return {
        "status": "ok",
        "lease_id": lease.lease_id,
        "session_id": lease.session_id,
        "name": lease.name,
        "worker": lease.worker.name,
        "live_url": data.get("sessionViewerUrl") or data.get("liveUrl"),
    }


@mcp.tool()
async def browser_navigate(url: str, ctx: Context = None) -> dict:
    """Navigate the leased session and report progress."""
    assert ctx is not None
    lease = _lease(ctx)
    if lease is None:
        return {"status": "error", "error": "no_session"}
    await _report(ctx, 0, 1, f"navigate {url}")
    result = await asyncio.to_thread(
        pool.exec, lease, {"command": "navigate", "url": url}
    )
    await _report(ctx, 1, 1, "navigate done")
    return {"status": "ok", "result": result}


@mcp.tool()
async def browser_eval(script: str, ctx: Context = None) -> dict:
    """Evaluate one script in the leased session."""
    assert ctx is not None
    lease = _lease(ctx)
    if lease is None:
        return {"status": "error", "error": "no_session"}
    result = await asyncio.to_thread(
        pool.exec, lease, {"command": "eval", "script": script}
    )
    return {"status": "ok", "result": result}


@mcp.tool()
async def browser_get(what: str, ctx: Context = None) -> dict:
    """Read one page fact in the leased session."""
    assert ctx is not None
    lease = _lease(ctx)
    if lease is None:
        return {"status": "error", "error": "no_session"}
    result = await asyncio.to_thread(
        pool.exec, lease, {"command": "get", "what": what}
    )
    return {"status": "ok", "result": result}


@mcp.tool()
async def browser_tabs(ctx: Context = None) -> dict:
    """List the tabs in the leased session."""
    assert ctx is not None
    lease = _lease(ctx)
    if lease is None:
        return {"status": "error", "error": "no_session"}
    result = await asyncio.to_thread(
        pool.exec, lease, {"command": "tab", "action": "list"}
    )
    return {"status": "ok", "result": result}


@mcp.tool()
async def browser_end(ctx: Context = None) -> dict:
    """Stop the leased session and release the worker."""
    assert ctx is not None
    lease = _lease(ctx)
    if lease is None:
        return {"status": "ok", "released": False, "reason": "no_session"}
    await asyncio.to_thread(pool.release, lease, "explicit")
    return {"status": "ok", "released": True, "lease_id": lease.lease_id}


@mcp.tool()
async def browser_status(ctx: Context = None) -> dict:
    """Return the caller's lease state."""
    assert ctx is not None
    lease = _lease(ctx)
    if lease is None:
        return {"status": "ok", "session": None}
    return {
        "status": "ok",
        "session": {
            "lease_id": lease.lease_id,
            "session_id": lease.session_id,
            "name": lease.name,
            "worker": lease.worker.name,
            "idle_s": round(time.time() - lease.last_activity, 2),
        },
    }


@mcp.tool()
async def pool_status() -> dict:
    """Return the live lease table."""
    return pool.status()


@mcp.tool()
async def release_owner(owner: str) -> dict:
    """Release every lease for one project or trial. This is the stop hook."""
    count = await asyncio.to_thread(pool.release_owner, owner)
    return {"status": "ok", "released": count}


if __name__ == "__main__":
    threading.Thread(target=pool.reap_loop, daemon=True).start()
    log(
        "startup",
        workers=[worker.base_url for worker in pool.workers],
        ttl_s=pool.ttl_s,
        wait_s=pool.wait_s,
        port=PORT,
        executor=pool.executor,
        cli=pool.cli if pool.executor == "cli" else None,
        guard=pool.guard if pool.use_guard else None,
    )
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=PORT,
        path="/mcp",
    )
