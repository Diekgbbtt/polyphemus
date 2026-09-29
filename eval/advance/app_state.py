"""app_state.py - the idle proxy for the eval sync daemon.

"An eval is executing" is read from polymerhus's own read-only running-state
surface (D26/#265): `GET /app-state` returns `{"idle": bool, "projects": [...]}`,
where `idle` is true when no project has an in-flight recon (`running`),
analysis (`draining`), or hunting (`running`) run. When the API is unreachable,
the daemon falls back to the exact same rows straight from postgres via `psql`
(the query in #265's route docstring and `eval/OPERATOR.md`), so a dead agent
never freezes the advance forever and a reachable-but-busy agent is never
mistaken for idle.

Both transports are injected and the module imports without I/O. The fallback
shells out to `psql` rather than importing a database driver, so the daemon
stays stdlib only. A failure of both transports raises `AppStateUnavailable`:
the caller must treat unknown as "do not advance" (fail closed, R9).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence, Tuple

from advance.effects import CommandResult, run_process

# The documented fallback: the same predicate `GET /app-state` applies. Idle
# iff this returns no rows. Kept verbatim with #265's route docstring and
# eval/OPERATOR.md so the two can never drift silently.
FALLBACK_QUERY = (
    "SELECT 'recon' AS kind, run_id AS id, project_id "
    "FROM recon_runs WHERE status = 'running' "
    "UNION ALL "
    "SELECT 'analysis', analysis_run_id, project_id "
    "FROM analysis_runs WHERE status = 'draining' "
    "UNION ALL "
    "SELECT 'hunting', hunting_run_id, project_id "
    "FROM hunting_runs WHERE status = 'running';"
)


class AppStateUnavailable(RuntimeError):
    """Neither the app-state endpoint nor the postgres fallback answered."""


@dataclass(frozen=True)
class AppState:
    """The idle verdict plus the per-project breakdown it was derived from."""

    idle: bool
    projects: Tuple[Mapping[str, object], ...]


# `url -> (status, body)`. Tests inject a fake; the default uses urllib.
HttpTransport = Callable[[str], Tuple[int, str]]
# `dsn -> psql stdout` (one line per in-flight run; empty means idle).
DsnTransport = Callable[[str], str]
CommandRunner = Callable[[Sequence[str]], CommandResult]


def app_state_endpoint(url: str) -> str:
    """The `/app-state` URL for a base URL that may or may not carry the path."""
    base = url.rstrip("/")
    return base if base.endswith("/app-state") else base + "/app-state"


def default_http_transport(url: str) -> Tuple[int, str]:
    """GET `url` with a short timeout; return `(status, body)`.

    A non-2xx response is returned, not raised, so the caller's fallback
    applies uniformly to an unreachable host and a 5xx agent.
    """
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def psql_command(dsn: str) -> list[str]:
    """The stdlib-only fallback: `psql` with the DSN and the documented query."""
    return ["psql", dsn, "-tA", "-c", FALLBACK_QUERY]


def default_dsn_transport(
    dsn: str, *, run: CommandRunner | None = None
) -> str:
    """Run the fallback query through `psql` and return its stdout.

    `psql` is used instead of a Python driver so this module adds no
    dependency. A non-zero exit raises `AppStateUnavailable`: the caller must
    not read an error stream as "no rows" (that would be a fail-open idle).
    """
    if run is None:
        run = run_process
    result = run(psql_command(dsn))
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise AppStateUnavailable(f"psql fallback failed: {detail}")
    return result.stdout


class IdleProxy:
    """The idle proxy: app-state endpoint first, postgres fallback second.

    Both paths answer the same question, so a caller injects one object and
    never branches on which transport answered. `log` receives a structured
    record when the HTTP path falls back, so an operator can see why.
    """

    def __init__(
        self,
        url: str,
        *,
        dsn: str | None = None,
        http_transport: HttpTransport = default_http_transport,
        dsn_transport: DsnTransport = default_dsn_transport,
        log: Callable[[dict], None] | None = None,
    ) -> None:
        self._url = app_state_endpoint(url)
        self._dsn = dsn
        self._http = http_transport
        self._dsn_transport = dsn_transport
        self._log = log or (lambda record: None)

    def fetch(self) -> AppState:
        """The app state, or `AppStateUnavailable` when neither path answers."""
        try:
            return self._from_http()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self._log({"event": "app_state_fallback", "error": str(exc)})
        if self._dsn is None:
            raise AppStateUnavailable(
                f"app-state endpoint {self._url!r} unreachable and no DSN fallback configured"
            )
        try:
            return AppState(idle=self._dsn_idle(), projects=())
        except AppStateUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 - any fallback failure is "unknown"
            raise AppStateUnavailable(f"postgres fallback failed: {exc}") from exc

    def is_idle(self) -> bool:
        return self.fetch().idle

    def _from_http(self) -> AppState:
        status, body = self._http(self._url)
        if status < 200 or status >= 300:
            raise OSError(f"app-state returned HTTP {status}")
        payload = json.loads(body)
        idle = payload["idle"]
        if not isinstance(idle, bool):
            raise ValueError(f"app-state idle is not a bool: {idle!r}")
        return AppState(idle=idle, projects=tuple(payload.get("projects") or ()))

    def _dsn_idle(self) -> bool:
        stdout = self._dsn_transport(self._dsn)  # type: ignore[arg-type]
        return not any(line.strip() for line in stdout.splitlines())
