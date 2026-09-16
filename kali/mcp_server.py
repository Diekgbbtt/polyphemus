"""FastMCP execution server for the reused Kali image.

Backward-compatible ``execute_command`` (stdout/stderr/returncode/duration_ms)
plus the #196 HTTP-history surface: ``search_http_history``,
``get_http_artifact``, ``replay_http_request`` and ``proxy_status``.

Capture is fail-open: if the namespace lease, proxy or store is unavailable the
command still runs and the result carries a ``capture_warning``. Model-facing
views are sanitized; raw bodies never cross this boundary.
"""
import os
import re

from fastmcp import FastMCP

os.environ["PATH"] = ":".join([
    "/opt/localbin", "/root/go/bin", "/opt/venv/bin", "/usr/local/go/bin", os.environ.get("PATH", ""),
])

mcp = FastMCP("kali-exec")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_SERVICE = None


def _build_service():
    from kali.http_history.config import load_config
    from kali.http_history.namespaces import NamespaceLeaseManager, SubprocessBackend
    from kali.http_history.registry import SourceRegistry
    from kali.http_history.service import HttpHistoryService

    config = load_config()
    registry = None
    lease_manager = None
    if config.enabled:
        registry = SourceRegistry(config.registry_path)
        lease_manager = NamespaceLeaseManager(
            registry=registry,
            pool_size=config.pool_size,
            ttl_s=config.ttl_s,
            acquire_timeout_s=config.acquire_timeout_s,
            backend=SubprocessBackend(proxy_port=config.proxy_port),
        )
    return HttpHistoryService(
        config=config, registry=registry, lease_manager=lease_manager
    )


def _get_service():
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = _build_service()
    return _SERVICE


def _sanitize_output(text: str) -> str:
    return _ANSI.sub("", text or "")


def _error_payload(exc: Exception) -> dict:
    from kali.http_history.service import BodyUnavailableError, NotFoundError

    if isinstance(exc, NotFoundError):
        return {"error": "not_found", "detail": str(exc)}
    if isinstance(exc, BodyUnavailableError):
        return {"error": "body_unavailable", "detail": str(exc)}
    return {"error": "invalid_request", "detail": str(exc)}


def execute_command(
    command: str,
    session_id: str,
    timeout_s: int = 300,
    project_id: str = "",
    run_id: str = "",
    spec_id: str = "",
    variant_ref: str = "",
) -> dict:
    """Run a shell command in /work/{session_id}.

    Returns the legacy {stdout, stderr, returncode, duration_ms} plus exec_id,
    http_artifact_refs and capture_warning. Older callers that pass only
    (command, session_id) keep working unchanged.
    """
    try:
        result = _get_service().execute(
            command,
            session_id,
            timeout_s,
            project_id=project_id,
            run_id=run_id,
            spec_id=spec_id,
            variant_ref=variant_ref,
        )
    except Exception as exc:  # noqa: BLE001 - never take the exec server down
        return {
            "stdout": "",
            "stderr": f"execute_command failed: {type(exc).__name__}: {exc}",
            "returncode": 1,
            "duration_ms": 0,
            "exec_id": "",
            "http_artifact_refs": [],
            "capture_warning": f"execution error: {type(exc).__name__}: {exc}",
        }
    result["stdout"] = _sanitize_output(result["stdout"])
    result["stderr"] = _sanitize_output(result["stderr"])
    return result


def search_http_history(
    project_id: str,
    filters: list | None = None,
    cursor: str | None = None,
    limit: int = 50,
    text: str | None = None,
) -> dict:
    """Search recorded HTTP transactions for one project (sanitized rows)."""
    try:
        return _get_service().search(
            project_id, filters=filters, cursor=cursor, limit=limit, text=text
        )
    except Exception as exc:  # noqa: BLE001
        return _error_payload(exc)


def get_http_artifact(
    project_id: str, artifact_id: str, include_body: bool = False
) -> dict:
    """Fetch one recorded artifact, sanitized. include_body is refused here."""
    try:
        return _get_service().get(project_id, artifact_id, include_body=include_body)
    except Exception as exc:  # noqa: BLE001
        return _error_payload(exc)


def replay_http_request(
    project_id: str,
    artifact_id: str,
    overrides: dict | None = None,
    capture_context: dict | None = None,
) -> dict:
    """Replay a recorded request with deterministic, closed-set overrides."""
    from kali.http_history.models import CaptureContext

    try:
        context = (
            CaptureContext(**capture_context) if isinstance(capture_context, dict) else None
        )
        return _get_service().replay(project_id, artifact_id, overrides or {}, context)
    except Exception as exc:  # noqa: BLE001
        return _error_payload(exc)


def proxy_status() -> dict:
    """Per-component health: MCP, proxy, routing, namespace pool and store."""
    try:
        return _get_service().proxy_status()
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "mcp": {"ok": True},
            "proxy": {"ok": False, "detail": f"status error: {exc}"},
            "routing": {"ok": False, "detail": f"status error: {exc}"},
            "namespaces": {"ok": False, "detail": f"status error: {exc}"},
            "store": {"ok": False, "detail": f"status error: {exc}"},
            "capture": {"enabled": False},
        }


for _fn in (
    execute_command,
    search_http_history,
    get_http_artifact,
    replay_http_request,
    proxy_status,
):
    mcp.tool()(_fn)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, path="/mcp")
