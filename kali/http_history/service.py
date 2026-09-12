"""The MCP-facing HTTP-history service.

Owns project isolation, sanitized views, deterministic replay and the extended
``execute_command`` contract. All I/O seams (store, runner, lease manager,
probes) are injectable so the unit tier runs without docker, mitmproxy or a
live network namespace.
"""
from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from kali.http_history.addon import UNSCOPED_PROJECT
from kali.http_history.config import HttpHistoryConfig, load_config
from kali.http_history.ids import new_ulid
from kali.http_history.models import CaptureContext
from kali.http_history.replay import apply_overrides
from kali.http_history.sanitize import sanitize_artifact, sanitize_summary
from kali.http_history.store import HttpHistoryStore

RESERVED_PROJECTS = frozenset({UNSCOPED_PROJECT})


class NotFoundError(LookupError):
    """Project-scoped lookup/replay missed (also covers cross-project access)."""


@dataclass
class ExecOutcome:
    stdout: str
    stderr: str
    returncode: int
    duration_ms: int


def default_runner(
    command: str, session_id: str, timeout_s: int, namespace: str | None = None
) -> ExecOutcome:
    workdir = f"/work/{session_id}"
    os.makedirs(workdir, exist_ok=True)
    argv = ["bash", "-lc", command]
    if namespace:
        argv = ["ip", "netns", "exec", namespace, *argv]
    start = time.time()
    try:
        proc = subprocess.run(
            argv, cwd=workdir, capture_output=True, text=True, timeout=timeout_s
        )
        return ExecOutcome(
            stdout=proc.stdout,
            stderr=proc.stderr,
            returncode=proc.returncode,
            duration_ms=int((time.time() - start) * 1000),
        )
    except subprocess.TimeoutExpired as exc:
        return ExecOutcome(
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=f"timeout after {timeout_s}s",
            returncode=124,
            duration_ms=int((time.time() - start) * 1000),
        )


class HttpHistoryService:
    def __init__(
        self,
        *,
        config: HttpHistoryConfig | None = None,
        registry=None,
        lease_manager=None,
        store_factory: Callable[[str], HttpHistoryStore] | None = None,
        runner: Callable[..., ExecOutcome] | None = None,
        proxy_probe: Callable[[], dict] | None = None,
        routing_probe: Callable[[], dict] | None = None,
    ):
        self.config = config or load_config()
        self.registry = registry
        self.lease_manager = lease_manager
        self._runner = runner or default_runner
        self._store_factory = store_factory or (
            lambda project: HttpHistoryStore(self.config.store_root, project)
        )
        self._stores: dict[str, HttpHistoryStore] = {}
        self._lock = threading.RLock()
        self._proxy_probe = proxy_probe or self._default_proxy_probe
        self._routing_probe = routing_probe or self._default_routing_probe

    # --- store -----------------------------------------------------------------

    def store(self, project_id: str) -> HttpHistoryStore:
        with self._lock:
            store = self._stores.get(project_id)
            if store is None:
                store = self._store_factory(project_id)
                self._stores[project_id] = store
            return store

    @staticmethod
    def _guard_project(project_id: str) -> str:
        if not project_id:
            raise ValueError("project_id is required")
        if project_id in RESERVED_PROJECTS:
            raise ValueError(f"project {project_id!r} is reserved and not queryable")
        return project_id

    # --- search / get ----------------------------------------------------------

    def search(
        self,
        project_id: str,
        filters: list[dict] | None = None,
        cursor: str | None = None,
        limit: int = 50,
        text: str | None = None,
    ) -> dict:
        self._guard_project(project_id)
        store = self.store(project_id)
        page = (
            store.text_search(text, cursor=cursor, limit=limit)
            if text
            else store.search(filters or [], cursor=cursor, limit=limit)
        )
        return {
            "summaries": [sanitize_summary(artifact) for artifact in page.artifacts],
            "next_cursor": page.next_cursor,
            "limit": limit,
        }

    def get(self, project_id: str, artifact_id: str, include_body: bool = False) -> dict:
        self._guard_project(project_id)
        if include_body:
            raise ValueError(
                "include_body is not available on the model-facing surface; "
                "raw bodies are used only by the deterministic replay path"
            )
        artifact = self.store(project_id).get_raw(artifact_id)
        if artifact is None:
            raise NotFoundError(f"artifact {artifact_id!r} not found in project {project_id!r}")
        return sanitize_artifact(artifact)

    # --- replay ----------------------------------------------------------------

    def replay(
        self,
        project_id: str,
        artifact_id: str,
        overrides: dict | None = None,
        capture_context: CaptureContext | None = None,
        *,
        sender: Callable[[str, object, CaptureContext], str] | None = None,
    ) -> dict:
        self._guard_project(project_id)
        store = self.store(project_id)
        baseline = store.get_raw(artifact_id)
        if baseline is None:
            raise NotFoundError(f"artifact {artifact_id!r} not found in project {project_id!r}")
        raw_body = store.get_body(baseline.request.body_ref)
        plan = apply_overrides(baseline.request, raw_body, overrides or {})

        context = (capture_context or CaptureContext()).model_copy(
            update={
                "exec_id": new_ulid(),
                "derived_from": artifact_id,
                "replay_kind": plan.replay_kind,
            }
        )
        send = sender or self._default_sender
        new_id = send(project_id, plan, context)
        return {
            "artifact_id": new_id,
            "derived_from": artifact_id,
            "replay_kind": plan.replay_kind,
        }

    def _default_sender(self, project_id: str, plan, context: CaptureContext) -> str:
        from kali.http_history.sender import NamespaceCurlSender

        return NamespaceCurlSender(self).send(project_id, plan, context)

    # --- execute_command -------------------------------------------------------

    def execute(
        self,
        command: str,
        session_id: str,
        timeout_s: int = 300,
        project_id: str = "",
        run_id: str = "",
        spec_id: str = "",
        variant_ref: str = "",
    ) -> dict:
        exec_id = new_ulid()
        lease = None
        capture_warning: str | None = None
        if self.config.enabled and project_id and self.lease_manager is not None:
            try:
                lease = self.lease_manager.acquire(
                    session_id=session_id,
                    project_id=project_id,
                    context=CaptureContext(
                        session_id=session_id,
                        run_id=run_id,
                        spec_id=spec_id,
                        variant_ref=variant_ref,
                        exec_id=exec_id,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - capture is fail-open
                capture_warning = f"capture unavailable: {type(exc).__name__}: {exc}"
        elif self.config.enabled and project_id and self.lease_manager is None:
            capture_warning = "capture unavailable: no namespace lease manager configured"

        namespace = lease.namespace if lease is not None else None
        try:
            outcome = self._runner(command, session_id, timeout_s, namespace)
        finally:
            refs: list[str] = []
            if lease is not None and project_id:
                try:
                    refs = self._refs_for_exec(project_id, exec_id)
                except Exception as exc:  # noqa: BLE001
                    capture_warning = f"capture lookup failed: {type(exc).__name__}: {exc}"
                finally:
                    try:
                        self.lease_manager.release(lease)
                    except Exception:  # noqa: BLE001 - never break the command result
                        pass

        return {
            "stdout": outcome.stdout,
            "stderr": outcome.stderr,
            "returncode": outcome.returncode,
            "duration_ms": outcome.duration_ms,
            "exec_id": exec_id,
            "http_artifact_refs": refs,
            "capture_warning": capture_warning,
        }

    def _refs_for_exec(self, project_id: str, exec_id: str) -> list[str]:
        page = self.store(project_id).search(
            [
                {
                    "side": "context",
                    "namespace": "core",
                    "key": "exec_id",
                    "op": "eq",
                    "value": exec_id,
                }
            ]
        )
        return [artifact.artifact_id for artifact in page.artifacts]

    # --- status ----------------------------------------------------------------

    def proxy_status(self) -> dict:
        proxy = self._proxy_probe()
        routing = self._routing_probe()
        namespaces = (
            self.lease_manager.status()
            if self.lease_manager is not None
            else {"ok": False, "detail": "no namespace lease manager"}
        )
        store = self._store_status()
        mcp = {"ok": True, "detail": "mcp server responding"}
        capture = {"enabled": self.config.enabled, "store_root": self.config.store_root}
        ok = bool(proxy.get("ok") and routing.get("ok") and store.get("ok"))
        return {
            "ok": ok,
            "mcp": mcp,
            "proxy": proxy,
            "routing": routing,
            "namespaces": namespaces,
            "store": store,
            "capture": capture,
        }

    def _default_proxy_probe(self) -> dict:
        try:
            with socket.create_connection(
                (self.config.proxy_host, self.config.proxy_port), timeout=1.0
            ):
                return {"ok": True, "detail": f"{self.config.proxy_host}:{self.config.proxy_port} accepting"}
        except OSError as exc:
            return {"ok": False, "detail": f"proxy not reachable: {exc}"}

    def _default_routing_probe(self) -> dict:
        """Routing readiness for LEASED namespaces.

        A lease installs its own per-veth REDIRECT to mitmproxy (see
        notes in namespaces.SubprocessBackend); what must exist at boot is the
        namespace egress path: IP forwarding plus the MASQUERADE rule for the
        lease subnet. The proxy's own upstream connections stay in the root
        namespace and are never redirected, which is what prevents a loop.
        """
        forwarding = False
        try:
            with open("/proc/sys/net/ipv4/ip_forward", encoding="ascii") as handle:
                forwarding = handle.read().strip() == "1"
        except OSError:
            forwarding = False
        try:
            proc = subprocess.run(
                ["iptables", "-t", "nat", "-S", "POSTROUTING"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"ok": False, "detail": f"routing probe failed: {exc}"}
        masquerade = "172.30.0.0/24" in proc.stdout
        ok = forwarding and masquerade
        detail = (
            "namespace egress ready (forwarding + MASQUERADE; per-lease REDIRECT at lease time)"
            if ok
            else f"namespace egress not ready (forwarding={forwarding}, masquerade={masquerade})"
        )
        return {
            "ok": ok,
            "detail": detail,
        }

    def _store_status(self) -> dict:
        root = Path(self.config.store_root)
        if not root.exists():
            return {"ok": False, "detail": f"store root {root} does not exist"}
        writable = os.access(root, os.W_OK)
        projects = sorted(
            child.name
            for child in root.iterdir()
            if (child / "http-history" / "history.sqlite3").exists()
        )
        total = 0
        for project in projects:
            try:
                total += HttpHistoryStore(root, project).status()["artifact_count"]
            except Exception:  # noqa: BLE001
                continue
        return {
            "ok": bool(writable),
            "path": str(root),
            "writable": writable,
            "projects": projects,
            "artifact_count": total,
        }
