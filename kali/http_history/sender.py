"""Deterministic replay sender: run the planned request through the capture path.

The request is executed *inside* the leased network namespace so the flow's
source address correlates back to the replay's capture context; the addon then
stores the new artifact. No shell is involved - curl receives an argument
vector, and the body travels on stdin.
"""
from __future__ import annotations

import subprocess


class ReplaySendError(RuntimeError):
    """The replay ran but produced no captured artifact."""


class NamespaceCurlSender:
    def __init__(self, service, *, timeout_s: int = 60):
        self._service = service
        self._timeout_s = timeout_s

    def send(self, project_id: str, plan, context) -> str:
        if self._service.lease_manager is None:
            raise ReplaySendError("no namespace lease manager configured for replay")
        lease = self._service.lease_manager.acquire(
            session_id=f"replay-{context.exec_id}",
            project_id=project_id,
            context=context,
        )
        try:
            argv = [
                "ip", "netns", "exec", lease.namespace, "curl", "-k", "-sS",
                "-o", "/dev/null", "-X", plan.method,
            ]
            for name, value in plan.headers:
                argv += ["-H", f"{name}: {value}"]
            if plan.body:
                argv += ["--data-binary", "@-"]
            argv.append(plan.url)
            subprocess.run(
                argv,
                input=plan.body or None,
                capture_output=True,
                timeout=self._timeout_s,
                check=False,
            )
            refs = self._service._refs_for_exec(project_id, context.exec_id)
        finally:
            self._service.lease_manager.release(lease)
        if not refs:
            raise ReplaySendError(
                f"replay produced no captured artifact for exec {context.exec_id}"
            )
        return refs[0]
