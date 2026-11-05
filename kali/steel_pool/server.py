"""The browser MCP server: three agent tools over the Steel pool.

One MCP session is one browser client. The MCP session id is the lease key.
The agent sees three tools only:

* ``browser_start(name, url=None)``
* ``browser_exec(command)``
* ``browser_end()``

There is no status, pool, or owner tool. The worker URL, the container name,
and the pool manager stay inside this process. ``browser_exec`` takes the
browser command grammar (``navigate https://...``, ``snapshot -i``,
``fill '#user' -- value``) and never a session name: the lease binds it.

The MCP session close arrives as a ``DELETE`` on the streamable HTTP path.
FastMCP 2.14.7 exposes no close callback, so the ASGI wrapper in this module
observes the DELETE and runs the same capture-stop-release path as an explicit
end. The TTL remains the backstop when a client disappears without a DELETE.

This module imports FastMCP and anyio, so it is not re-exported by the
stdlib-only package. The process entrypoint is ``kali/browser_mcp_server.py``.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
import functools
import json
import math
import os
import shlex
import sys
import time
from typing import Protocol

import anyio
from fastmcp import Context, FastMCP

try:  # package layout
    from kali.steel_pool.cli import (
        CaptureError,
        CliError,
        RestoreError,
        SteelCli,
    )
    from kali.steel_pool.docker_api import DockerAPIError, DockerUnixClient
    from kali.steel_pool.lease import (
        DEFAULT_HEARTBEAT_S,
        DEFAULT_LEASE_TTL_S,
        DEFAULT_POOL_WAIT_S,
        EndReport,
        LeaseError,
        LeaseInUse,
        LeaseManager,
        LeaseView,
        NoLease,
        PoolExhausted,
    )
    from kali.steel_pool.pool import Worker, WorkerRegistry
    from kali.steel_pool.store import (
        CorruptSessionRecord,
        SessionStore,
        SessionStoreError,
    )
except ImportError:  # flat deployment beside mcp_server.py
    from steel_pool.cli import (  # type: ignore[no-redef]
        CaptureError,
        CliError,
        RestoreError,
        SteelCli,
    )
    from steel_pool.docker_api import (  # type: ignore[no-redef]
        DockerAPIError,
        DockerUnixClient,
    )
    from steel_pool.lease import (  # type: ignore[no-redef]
        DEFAULT_HEARTBEAT_S,
        DEFAULT_LEASE_TTL_S,
        DEFAULT_POOL_WAIT_S,
        EndReport,
        LeaseError,
        LeaseInUse,
        LeaseManager,
        LeaseView,
        NoLease,
        PoolExhausted,
    )
    from steel_pool.pool import Worker, WorkerRegistry  # type: ignore[no-redef]
    from steel_pool.store import (  # type: ignore[no-redef]
        CorruptSessionRecord,
        SessionStore,
        SessionStoreError,
    )

DEFAULT_MCP_PORT = 8003
DEFAULT_MCP_PATH = "/mcp"
DEFAULT_POOL_LABEL = "polymerhus.steel-pool=true"
DEFAULT_POOL_SIZE = 4
DEFAULT_POOL_HEALTH_S = 30.0
DEFAULT_CLI_TIMEOUT_S = 600.0
DEFAULT_WORKER_API_SUFFIX = "/v1"

_FORBIDDEN_VERBS = frozenset({"start", "stop", "sessions", "live"})
_FORBIDDEN_OPTIONS = frozenset(
    {"--session", "--api-url", "--local", "-l"}
)
_FORBIDDEN_OPTION_PREFIXES = ("--session=", "--api-url=")
_STRIP_OPTIONS = frozenset({"--json"})

__all__ = [
    "BrowserServerConfig",
    "BrowserService",
    "CommandParseError",
    "SessionCloseMiddleware",
    "build_service",
    "create_browser_mcp",
    "main",
    "parse_browser_command",
]


class CommandParseError(ValueError):
    """The agent command is not a valid bound browser command."""


class LeaseAPI(Protocol):
    """The lease manager slice the browser service needs."""

    def start(
        self, mcp_session_id: str, name: str, url: str | None = None
    ) -> LeaseView: ...

    def exec(self, mcp_session_id: str, args: Sequence[str]) -> dict: ...

    def end(self, mcp_session_id: str, *, reason: str = "explicit") -> EndReport: ...

    def close_mcp_session(self, mcp_session_id: str) -> EndReport: ...

    def shutdown(self) -> tuple[EndReport, ...]: ...


def _event_logger(event: str, **fields: object) -> None:
    """Write one structured event to stderr. Values are already safe."""
    record = {"ts": time.time(), "event": event, **fields}
    try:
        sys.stderr.write(json.dumps(record, default=str) + "\n")
        sys.stderr.flush()
    except Exception:
        return None


def error_envelope(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    **extra: object,
) -> dict:
    """Build the one error shape every tool returns."""
    return {
        "success": False,
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            **extra,
        },
    }


def _parse_head(tokens: list[str], *, nested: bool) -> list[str]:
    """Validate one command's head, strip server-owned options, return it."""
    if not tokens:
        raise CommandParseError("the command is empty")
    verb = tokens[0]
    if verb.startswith("-"):
        raise CommandParseError(
            f"{verb!r} is not a browser verb; put options after the verb"
        )
    if verb in _FORBIDDEN_VERBS:
        raise CommandParseError(
            f"the {verb!r} verb is owned by browser_start and browser_end"
        )
    boundary = tokens.index("--") if "--" in tokens else len(tokens)
    cleaned: list[str] = []
    for token in tokens[:boundary]:
        if token in _FORBIDDEN_OPTIONS or token.startswith(
            _FORBIDDEN_OPTION_PREFIXES
        ):
            raise CommandParseError(
                "the session and worker are bound by the lease; "
                f"{token!r} is not accepted"
            )
        if token in _STRIP_OPTIONS:
            continue
        cleaned.append(token)
    cleaned.extend(tokens[boundary:])
    if not cleaned:
        raise CommandParseError("the command is empty")
    if nested and cleaned[0] in _FORBIDDEN_VERBS:
        raise CommandParseError(
            f"the {cleaned[0]!r} verb is owned by browser_start and browser_end"
        )
    return cleaned


def parse_browser_command(command: object) -> list[str]:
    """Turn the agent command string into CLI arguments.

    The accepted grammar is the browser command grammar, with or without the
    ``steel browser`` prefix: ``navigate https://app.test``, ``snapshot -i``,
    ``fill '#user' -- value``, ``batch -- "snapshot -i" "click @e1"``.

    Session ownership stays in the server: ``start``, ``stop``, ``sessions``,
    ``live``, ``--session``, ``--api-url``, and ``--local`` are refused. A
    ``batch`` inner command is validated too, so the lifecycle cannot hide
    inside it. The command text is split with ``shlex`` and never handed to a
    shell.
    """
    if not isinstance(command, str) or not command.strip():
        raise CommandParseError("the command must be a non-empty string")
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise CommandParseError(f"the command is not parseable: {exc}") from exc
    if tokens and tokens[0] == "steel":
        tokens = tokens[1:]
        if not tokens or tokens[0] != "browser":
            raise CommandParseError("only browser commands are accepted")
    if tokens and tokens[0] == "browser":
        tokens = tokens[1:]
    cleaned = _parse_head(tokens, nested=False)
    if cleaned[0] == "batch" and "--" in cleaned:
        boundary = cleaned.index("--")
        for inner in cleaned[boundary + 1 :]:
            try:
                inner_tokens = shlex.split(inner)
            except ValueError as exc:
                raise CommandParseError(
                    f"a batch command is not parseable: {exc}"
                ) from exc
            _parse_head(inner_tokens, nested=True)
    return cleaned


class BrowserService:
    """The three browser operations, decoupled from FastMCP for testing."""

    def __init__(self, manager: LeaseAPI, *, emit=None) -> None:
        self._manager = manager
        self._emit = emit or _event_logger

    def start(
        self,
        mcp_session_id: str,
        name: str,
        url: str | None = None,
    ) -> dict:
        try:
            view = self._manager.start(mcp_session_id, name, url)
        except PoolExhausted as exc:
            return error_envelope(
                "pool_exhausted",
                str(exc),
                retryable=True,
                recovery="retry_after_a_lease_ends",
            )
        except LeaseInUse as exc:
            return error_envelope(
                "session_in_use",
                str(exc),
                retryable=False,
                recovery="reuse_the_mounted_name_or_end_it",
            )
        except LeaseError as exc:
            return error_envelope("lease_error", str(exc), retryable=False)
        except (SessionStoreError, CorruptSessionRecord) as exc:
            return error_envelope("store_error", str(exc), retryable=False)
        except DockerAPIError as exc:
            return error_envelope("pool_unavailable", str(exc), retryable=True)
        except CliError as exc:
            return error_envelope("browser_error", str(exc), retryable=True)
        except RestoreError as exc:
            return error_envelope("restore_failed", str(exc), retryable=False)
        except ValueError as exc:
            return error_envelope("invalid_argument", str(exc), retryable=False)
        except Exception as exc:  # noqa: BLE001 - never take the server down
            return error_envelope(
                "internal_error", f"{type(exc).__name__}: {exc}", retryable=True
            )
        return {
            "success": True,
            "session": {
                "name": view.name,
                "session_id": view.steel_session_id,
            },
            "warnings": list(view.warnings),
        }

    def exec(self, mcp_session_id: str, command: object) -> dict:
        try:
            args = parse_browser_command(command)
        except CommandParseError as exc:
            return error_envelope("invalid_command", str(exc), retryable=False)
        try:
            payload = self._manager.exec(mcp_session_id, args)
        except PoolExhausted as exc:
            return error_envelope("pool_exhausted", str(exc), retryable=True)
        except NoLease as exc:
            return error_envelope(
                "no_session",
                str(exc),
                retryable=False,
                recovery="call_browser_start_first",
            )
        except LeaseError as exc:
            return error_envelope("lease_error", str(exc), retryable=False)
        except CaptureError as exc:
            return error_envelope("capture_failed", str(exc), retryable=True)
        except CliError as exc:
            return error_envelope(
                "browser_error", str(exc), retryable=True
            )
        except (SessionStoreError, CorruptSessionRecord) as exc:
            return error_envelope("store_error", str(exc), retryable=False)
        except ValueError as exc:
            return error_envelope("invalid_argument", str(exc), retryable=False)
        except Exception as exc:  # noqa: BLE001 - never take the server down
            return error_envelope(
                "internal_error", f"{type(exc).__name__}: {exc}", retryable=True
            )
        if not isinstance(payload, dict):
            return error_envelope(
                "browser_error",
                "the browser command returned no envelope",
                retryable=True,
            )
        return payload

    def end(self, mcp_session_id: str) -> dict:
        try:
            report = self._manager.end(mcp_session_id)
        except LeaseError as exc:
            return error_envelope("lease_error", str(exc), retryable=False)
        except Exception as exc:  # noqa: BLE001 - never take the server down
            return error_envelope(
                "internal_error", f"{type(exc).__name__}: {exc}", retryable=True
            )
        return {
            "success": True,
            "ended": report.ended,
            "reason": report.reason,
            "captured": report.captured,
            "saved": report.saved,
            "stopped": report.stopped,
            "released": report.released,
            "warnings": list(report.warnings),
        }

    def close_session(self, mcp_session_id: str) -> EndReport | None:
        """The MCP session close hook. It never raises into the transport."""
        try:
            report = self._manager.close_mcp_session(mcp_session_id)
        except Exception as exc:  # noqa: BLE001 - the TTL is the backstop
            self._emit(
                "session.close_error",
                mcp_session_id=mcp_session_id,
                error=f"{type(exc).__name__}: {exc}",
            )
            return None
        self._emit(
            "session.close",
            mcp_session_id=mcp_session_id,
            ended=report.ended,
            reason=report.reason,
        )
        return report

    def shutdown(self) -> tuple[EndReport, ...]:
        try:
            reports = self._manager.shutdown()
        except Exception as exc:  # noqa: BLE001 - shutdown must finish
            self._emit(
                "server.shutdown_error",
                error=f"{type(exc).__name__}: {exc}",
            )
            return ()
        self._emit("server.shutdown", ended=len(reports))
        return reports


@dataclass(frozen=True)
class BrowserServerConfig:
    """The deployment inputs of the browser MCP process."""

    port: int
    docker_socket: str
    session_store: str
    cli_path: str
    guard_path: str
    pool_label: str = DEFAULT_POOL_LABEL
    pool_size: int = DEFAULT_POOL_SIZE
    pool_wait_s: float = DEFAULT_POOL_WAIT_S
    health_timeout_s: float = DEFAULT_POOL_HEALTH_S
    heartbeat_s: float = DEFAULT_HEARTBEAT_S
    lease_ttl_s: float = DEFAULT_LEASE_TTL_S
    cli_timeout_s: float = DEFAULT_CLI_TIMEOUT_S
    worker_api_suffix: str = DEFAULT_WORKER_API_SUFFIX
    mcp_path: str = DEFAULT_MCP_PATH

    def __post_init__(self) -> None:
        if not isinstance(self.port, int) or isinstance(self.port, bool):
            raise ValueError("the MCP port must be an integer")
        if not 0 < self.port < 65536:
            raise ValueError("the MCP port is out of range")
        for label, value in (
            ("Docker socket", self.docker_socket),
            ("session store", self.session_store),
            ("CLI path", self.cli_path),
            ("guard path", self.guard_path),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"the {label} is required")
        for label, value in (
            ("pool size", self.pool_size),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"the {label} must be a positive integer")
        for label, value in (
            ("pool wait", self.pool_wait_s),
            ("health timeout", self.health_timeout_s),
            ("heartbeat period", self.heartbeat_s),
            ("lease TTL", self.lease_ttl_s),
            ("CLI timeout", self.cli_timeout_s),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"the {label} must be positive and finite")
        if self.worker_api_suffix not in {"", "/v1"}:
            raise ValueError("the worker API suffix must be '' or '/v1'")
        if not self.mcp_path.startswith("/"):
            raise ValueError("the MCP path must start with '/'")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "BrowserServerConfig":
        """Read the deployment environment and fail loud on a missing input.

        The Docker socket and the session store have no guessable default.
        The CLI and the guard must be present before the process starts, so a
        misconfigured deployment fails at boot instead of at the first lease.
        """
        source = os.environ if env is None else env

        def required(name: str) -> str:
            value = (source.get(name) or "").strip()
            if not value:
                raise ValueError(f"{name} is unset")
            return value

        def number(name: str, default: float) -> float:
            raw = (source.get(name) or "").strip()
            if not raw:
                return default
            try:
                return float(raw)
            except ValueError as exc:
                raise ValueError(f"{name} is not a number") from exc

        def integer(name: str, default: int) -> int:
            raw = (source.get(name) or "").strip()
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError as exc:
                raise ValueError(f"{name} is not an integer") from exc

        docker_socket = required("STEEL_POOL_DOCKER_SOCKET")
        if not os.path.exists(docker_socket):
            raise ValueError(
                f"STEEL_POOL_DOCKER_SOCKET {docker_socket!r} does not exist"
            )
        session_store = required("STEEL_SESSION_STORE")
        cli_path = required("STEEL_CLI")
        guard_path = required("STEEL_GUARD")
        for label, path in (("STEEL_CLI", cli_path), ("STEEL_GUARD", guard_path)):
            if not os.path.isfile(path) or not os.access(path, os.X_OK):
                raise ValueError(f"{label} {path!r} is not an executable file")
        return cls(
            port=integer("STEEL_MCP_PORT", DEFAULT_MCP_PORT),
            docker_socket=docker_socket,
            session_store=session_store,
            cli_path=cli_path,
            guard_path=guard_path,
            pool_label=(source.get("STEEL_POOL_LABEL") or "")
            .strip()
            or DEFAULT_POOL_LABEL,
            pool_size=integer("STEEL_POOL_SIZE", DEFAULT_POOL_SIZE),
            pool_wait_s=number("STEEL_POOL_WAIT_S", DEFAULT_POOL_WAIT_S),
            health_timeout_s=number(
                "STEEL_POOL_HEALTH_S", DEFAULT_POOL_HEALTH_S
            ),
            heartbeat_s=number("STEEL_HEARTBEAT_S", DEFAULT_HEARTBEAT_S),
            lease_ttl_s=number("STEEL_LEASE_TTL_S", DEFAULT_LEASE_TTL_S),
            cli_timeout_s=number("STEEL_CLI_TIMEOUT_S", DEFAULT_CLI_TIMEOUT_S),
            worker_api_suffix=cls._suffix(source),
            mcp_path=(source.get("STEEL_MCP_PATH") or "").strip()
            or DEFAULT_MCP_PATH,
        )

    @staticmethod
    def _suffix(source: Mapping[str, str]) -> str:
        raw = source.get("STEEL_WORKER_API_SUFFIX")
        if raw is None:
            return DEFAULT_WORKER_API_SUFFIX
        return raw.strip()


def build_service(
    config: BrowserServerConfig,
    *,
    emit=None,
    cli_factory=None,
) -> BrowserService:
    """Build the pool manager, store, and CLI adapter from the config."""
    logger = emit or _event_logger
    store = SessionStore(config.session_store)
    docker = DockerUnixClient(config.docker_socket)
    registry = WorkerRegistry(
        docker,
        config.pool_label,
        config.pool_size,
        health_timeout_s=config.health_timeout_s,
        emit=logger,
    )
    child_env = dict(os.environ)
    child_env["STEEL_REAL_BINARY_REAL"] = config.cli_path

    def default_cli_factory(worker: Worker) -> SteelCli:
        return SteelCli(
            worker.url,
            binary=config.cli_path,
            guard_path=config.guard_path,
            python=sys.executable,
            timeout_s=config.cli_timeout_s,
            api_suffix=config.worker_api_suffix,
            env=child_env,
        )

    manager = LeaseManager(
        registry,
        store,
        cli_factory or default_cli_factory,
        pool_wait_s=config.pool_wait_s,
        heartbeat_s=config.heartbeat_s,
        ttl_s=config.lease_ttl_s,
        emit=logger,
    )
    return BrowserService(manager, emit=logger)


def _mcp_session_id(ctx: Context) -> str:
    session_id = ctx.session_id
    if not session_id:
        raise RuntimeError("the MCP request carries no session id")
    return session_id


def create_browser_mcp(
    service: BrowserService,
    *,
    mcp_path: str = DEFAULT_MCP_PATH,
    name: str = "polymerhus-browser",
) -> FastMCP:
    """Create the FastMCP app with exactly the three browser tools."""

    @asynccontextmanager
    async def lifespan(_server: FastMCP):
        try:
            yield {}
        finally:
            # The lifespan teardown runs inside a cancelled scope on client
            # disconnect, so the release must be shielded or a dropped client
            # would skip stop and release until the TTL.
            with anyio.CancelScope(shield=True):
                await anyio.to_thread.run_sync(service.shutdown)

    mcp = FastMCP(name, lifespan=lifespan)

    @mcp.tool()
    async def browser_start(
        name: str, url: str | None = None, ctx: Context = None
    ) -> dict:
        """Mount a durable named browser session for this MCP session.

        The name is the durable handle. A later ``browser_start`` with the
        same name restores its cookies and localStorage. The result carries
        the name and the Steel session id; the worker stays internal. Call
        ``browser_end`` when the flow is done.
        """
        return await anyio.to_thread.run_sync(
            functools.partial(
                service.start, _mcp_session_id(ctx), name, url
            )
        )

    @mcp.tool()
    async def browser_exec(command: str, ctx: Context = None) -> dict:
        """Run one browser command on this MCP session's live session.

        The grammar is the browser command grammar without the session:
        ``navigate https://app.test``, ``snapshot -i``, ``get text body``,
        ``fill '#user' -- value``, ``wait --selector '#app'``, ``eval 1+1``,
        ``batch -- "snapshot -i" "click @e1"``. The lease supplies the
        session. ``start``, ``stop``, ``sessions``, ``live``, and every
        session or worker flag are refused.
        """
        return await anyio.to_thread.run_sync(
            functools.partial(service.exec, _mcp_session_id(ctx), command)
        )

    @mcp.tool()
    async def browser_end(ctx: Context = None) -> dict:
        """Capture the browser state, save it, and release this lease.

        The state is saved under the session name, so a later
        ``browser_start`` with that name restores it. The call is idempotent.
        """
        return await anyio.to_thread.run_sync(
            functools.partial(service.end, _mcp_session_id(ctx))
        )

    # The path is consumed by the ASGI app, not by the tool registrations.
    mcp._browser_mcp_path = mcp_path  # type: ignore[attr-defined]
    return mcp


class SessionCloseMiddleware:
    """Run the close hook when the client DELETEs its MCP session.

    FastMCP 2.14.7 has no session close callback. The streamable HTTP
    transport answers DELETE by terminating the session, so this wrapper
    observes the request, lets FastMCP answer it, then releases the lease.
    The hook is shielded from the request result: a cleanup failure is logged
    and the TTL remains the backstop.
    """

    def __init__(
        self,
        app,
        service: BrowserService,
        *,
        path: str = DEFAULT_MCP_PATH,
    ) -> None:
        self._app = app
        self._service = service
        self._path = path

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope.get("type") != "http"
            or scope.get("method") != "DELETE"
            or scope.get("path") != self._path
        ):
            await self._app(scope, receive, send)
            return
        session_id = ""
        for key, value in scope.get("headers") or ():
            if key.lower() == b"mcp-session-id":
                session_id = value.decode("latin-1").strip()
                break
        try:
            await self._app(scope, receive, send)
        finally:
            if session_id:
                await anyio.to_thread.run_sync(
                    self._service.close_session, session_id
                )


def create_app(
    service: BrowserService,
    *,
    mcp_path: str = DEFAULT_MCP_PATH,
):
    """Build the wrapped ASGI app the process serves."""
    mcp = create_browser_mcp(service, mcp_path=mcp_path)
    app = mcp.http_app(path=mcp_path, transport="streamable-http")
    return SessionCloseMiddleware(app, service, path=mcp_path)


def main() -> int:
    config = BrowserServerConfig.from_env()
    service = build_service(config)
    app = create_app(service, mcp_path=config.mcp_path)
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=config.port,
        log_level=os.environ.get("STEEL_MCP_LOG_LEVEL", "info"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
