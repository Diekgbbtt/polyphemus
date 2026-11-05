"""The Steel CLI mount, execute, capture, and release adapter.

The CLI 0.5.0-preview.6 is the only browser executor. It creates the session
on the leased worker, runs every browsing command, restores cookies and
localStorage, and stops the session.

The CLI cannot create a session with ``sessionContext`` and cannot attach to
an API-created session. The restore therefore runs through CLI commands:
``browser cookies set`` for cookies, and a visit to each stored origin followed
by ``browser storage local set`` for localStorage. Cookie expiry, SameSite,
priority, and source metadata are not restorable.

The end path captures ``GET /v1/sessions/<id>/context`` for full evidence.
If the API capture fails, it falls back to ``browser cookies`` and
``browser storage local`` for the current origin.

The module is stdlib-only and performs no I/O at import.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import os
import subprocess
import sys
from urllib.parse import urlsplit

try:  # package layout
    from kali.steel_pool.api import WorkerAPI, WorkerAPIError
    from kali.steel_pool.store import BrowserSessionRecord, validate_name
except ImportError:  # flat deployment beside mcp_server.py
    from steel_pool.api import (  # type: ignore[no-redef]
        WorkerAPI,
        WorkerAPIError,
    )
    from steel_pool.store import (  # type: ignore[no-redef]
        BrowserSessionRecord,
        validate_name,
    )

DEFAULT_SESSION_TIMEOUT_MS = 3_600_000
DEFAULT_INACTIVITY_TIMEOUT_MS = 0
_RESET_URL = "about:blank"

__all__ = [
    "CaptureError",
    "CapturedContext",
    "CliError",
    "CliSession",
    "DEFAULT_INACTIVITY_TIMEOUT_MS",
    "DEFAULT_SESSION_TIMEOUT_MS",
    "RestoreError",
    "RestoreReport",
    "SteelCli",
]


class CliError(RuntimeError):
    """A Steel CLI invocation failed or returned an unusable envelope."""

    def __init__(
        self,
        message: str,
        *,
        returncode: int | None = None,
        payload: dict | None = None,
        stderr_tail: str = "",
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.payload = payload
        self.stderr_tail = stderr_tail


class RestoreError(RuntimeError):
    """A stored browser state could not be restored through the CLI."""


class CaptureError(RuntimeError):
    """The browser state could not be captured through the API or the CLI."""


@dataclass(frozen=True)
class CliSession:
    """One live CLI session on a leased worker."""

    name: str
    session_id: str
    remaining_ms: int | None = None

    def __post_init__(self) -> None:
        validate_name(self.name)
        if not isinstance(self.session_id, str) or not self.session_id:
            raise ValueError("a CLI session needs a Steel session id")


@dataclass(frozen=True)
class RestoreReport:
    """The counts from one state restore."""

    cookies_set: int
    origins_visited: int
    storage_keys_set: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CapturedContext:
    """A captured browser context and its source."""

    context: dict
    source: str
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.context, dict):
            raise ValueError("a captured context must be an object")
        if self.source not in {"api", "cli"}:
            raise ValueError("a captured context source is api or cli")


def _tail(text: str, limit: int = 300) -> str:
    return text[-limit:] if len(text) > limit else text


def _error_message(error: object) -> str | None:
    if isinstance(error, str):
        return error
    if isinstance(error, Mapping):
        message = error.get("message") or error.get("code")
        if isinstance(message, str):
            return message
    return None


def _origin(value: object) -> str | None:
    if isinstance(value, Mapping):
        value = value.get("url") or value.get("href")
    if not isinstance(value, str):
        return None
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}"


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def _split_key(value: str) -> tuple[str, str]:
    """Return the host and the authority of a captured storage key.

    The v0.5.5 API captures storage under the hostname. A caller may instead
    write a host and port, or a bracketed IPv6 host. The authority keeps the
    port so a synthesised origin is complete.
    """
    if value.startswith("http://") or value.startswith("https://"):
        parts = urlsplit(value)
        return parts.hostname or value, parts.netloc or value
    if value.startswith("["):
        end = value.find("]")
        if end != -1:
            return value[1:end], value
    if value.count(":") == 1:
        host, _, port = value.partition(":")
        if port.isdigit():
            return host, value
    return value, value


def _synthetic_origin(host: str, authority: str) -> str:
    scheme = "http" if host in _LOOPBACK_HOSTS else "https"
    if authority.startswith("[") or ":" not in host:
        return f"{scheme}://{authority}"
    return f"{scheme}://[{authority}]"


def _needs_origin_resolution(context: Mapping) -> bool:
    """Return True when a storage key is not already an origin."""
    for field in ("localStorage", "sessionStorage", "indexedDB"):
        values = context.get(field)
        if not isinstance(values, Mapping):
            continue
        for key in values:
            if not isinstance(key, str):
                continue
            if not (key.startswith("http://") or key.startswith("https://")):
                return True
    return False


def _known_origins(previous: BrowserSessionRecord | None) -> dict[str, str]:
    known: dict[str, str] = {}
    if previous is None:
        return known
    for field in (
        previous.local_storage,
        previous.session_storage,
        previous.indexed_db,
    ):
        for origin in field:
            if not isinstance(origin, str):
                continue
            parts = urlsplit(origin)
            if parts.hostname:
                known.setdefault(parts.hostname, origin)
    return known


def _normalise_storage(
    context: dict,
    current_url: str | None,
    previous: BrowserSessionRecord | None,
) -> dict:
    """Map captured hostname keys to origins.

    The API capture keys storage by hostname. The API restore and the CLI
    restore resolve by origin. The current page supplies the origin for its
    own host; a previous record supplies known origins for the rest. An
    unknown host defaults to HTTPS, and a loopback host defaults to HTTP.
    """
    current_origin = _origin(current_url)
    current_host = urlsplit(current_origin).hostname if current_origin else None
    known = _known_origins(previous)
    normalised = dict(context)
    for field in ("localStorage", "sessionStorage", "indexedDB"):
        values = normalised.get(field)
        if not isinstance(values, Mapping):
            continue
        target: dict[str, object] = {}
        for key, value in values.items():
            if not isinstance(key, str):
                continue
            if key.startswith("http://") or key.startswith("https://"):
                origin = key
            else:
                host, authority = _split_key(key)
                if current_host == host and current_origin:
                    origin = current_origin
                elif host in known:
                    origin = known[host]
                else:
                    origin = _synthetic_origin(host, authority)
            if isinstance(value, Mapping) and isinstance(target.get(origin), dict):
                merged = dict(target[origin])
                merged.update(value)
                target[origin] = merged
            else:
                target[origin] = dict(value) if isinstance(value, Mapping) else value
        normalised[field] = target
    return normalised


class SteelCli:
    """One CLI adapter bound to one worker API origin."""

    def __init__(
        self,
        worker_url: str,
        *,
        binary: str,
        guard_path: str | None = None,
        python: str | None = None,
        timeout_s: float = 180.0,
        api_timeout_s: float = 10.0,
        env: Mapping[str, str] | None = None,
        session_timeout_ms: int = DEFAULT_SESSION_TIMEOUT_MS,
        inactivity_timeout_ms: int = DEFAULT_INACTIVITY_TIMEOUT_MS,
    ) -> None:
        if not str(binary).strip():
            raise ValueError("the Steel CLI binary is required")
        if timeout_s <= 0:
            raise ValueError("the CLI timeout must be positive")
        if session_timeout_ms < 0 or inactivity_timeout_ms < 0:
            raise ValueError("CLI session timeouts must not be negative")
        self._worker_url = worker_url.rstrip("/")
        self._api_url = f"{self._worker_url}/v1"
        self._api = WorkerAPI(worker_url, timeout_s=api_timeout_s)
        self._binary = str(binary)
        self._guard_path = str(guard_path) if guard_path else None
        self._python = python or sys.executable
        self._timeout_s = timeout_s
        self._session_timeout_ms = session_timeout_ms
        self._inactivity_timeout_ms = inactivity_timeout_ms
        self._env = dict(os.environ if env is None else env)
        self._env["STEEL_BROWSER_API_URL"] = self._api_url
        self._env.setdefault("STEEL_TELEMETRY_DISABLED", "1")

    @property
    def api_url(self) -> str:
        return self._api_url

    def _command(self, args: Sequence[str]) -> list[str]:
        if self._guard_path:
            return [
                self._python,
                self._guard_path,
                "--api-url",
                self._api_url,
                *args,
            ]
        return [self._binary, "--api-url", self._api_url, *args]

    def _run(self, args: Sequence[str], *, check_success: bool) -> dict:
        command = self._command(args)
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
                check=False,
                env=dict(self._env),
            )
        except subprocess.TimeoutExpired as exc:
            raise CliError("the Steel CLI timed out") from exc
        except OSError as exc:
            raise CliError("the Steel CLI could not be started") from exc
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        try:
            payload = json.loads(stdout)
        except ValueError as exc:
            raise CliError(
                "the Steel CLI returned no JSON",
                returncode=completed.returncode,
                stderr_tail=_tail(stderr),
            ) from exc
        if not isinstance(payload, dict):
            raise CliError(
                "the Steel CLI returned no JSON object",
                returncode=completed.returncode,
                stderr_tail=_tail(stderr),
            )
        if check_success:
            error = payload.get("error")
            if completed.returncode != 0 or payload.get("success") is False or error:
                message = _error_message(error) or (
                    f"the Steel CLI exited {completed.returncode}"
                )
                raise CliError(
                    message,
                    returncode=completed.returncode,
                    payload=payload,
                    stderr_tail=_tail(stderr),
                )
        return payload

    def _with_session(self, args: Sequence[str], name: str) -> list[str]:
        if "--" in args:
            index = args.index("--")
            return [
                "browser",
                *args[:index],
                "--session",
                name,
                "--json",
                *args[index:],
            ]
        return ["browser", *args, "--session", name, "--json"]

    def start(self, name: str) -> CliSession:
        """Create the CLI session on the bound worker."""
        validate_name(name)
        payload = self._run(
            [
                "browser",
                "start",
                "--session",
                name,
                "--session-timeout",
                str(self._session_timeout_ms),
                "--inactivity-timeout",
                str(self._inactivity_timeout_ms),
                "--json",
            ],
            check_success=True,
        )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise CliError("the Steel CLI start returned no session object")
        session_id = data.get("id")
        if not isinstance(session_id, str) or not session_id:
            raise CliError("the Steel CLI start returned no session id")
        remaining = data.get("remainingMs")
        return CliSession(
            name=name,
            session_id=session_id,
            remaining_ms=remaining if isinstance(remaining, int) else None,
        )

    def exec(self, session: CliSession, args: Sequence[str]) -> dict:
        """Run one browser command and return the CLI envelope.

        A command-level failure stays in the envelope for the agent. A
        transport or non-JSON failure raises ``CliError``.
        """
        if not args:
            raise ValueError("a browser command is required")
        return self._run(
            self._with_session(args, session.name), check_success=False
        )

    def stop(self, session: CliSession) -> dict:
        """Stop the CLI session and release its API session."""
        return self._run(
            ["browser", "stop", "--session", session.name, "--json"],
            check_success=True,
        )

    def release(self, session: CliSession) -> bool:
        """Release the API session as the fallback after a failed stop."""
        return self._api.release(session.session_id)

    def restore(self, session: CliSession, record: BrowserSessionRecord) -> RestoreReport:
        """Restore cookies and localStorage through the CLI."""
        cookies_set = 0
        origins_visited = 0
        storage_keys_set = 0
        lossy_cookies = 0
        for cookie in record.cookies:
            if not isinstance(cookie, Mapping):
                raise RestoreError("a stored cookie is not an object")
            name = cookie.get("name")
            value = cookie.get("value")
            if not isinstance(name, str) or not name or not isinstance(value, str):
                raise RestoreError("a stored cookie has no name or value")
            args = ["browser", "cookies", "set"]
            domain = cookie.get("domain")
            if isinstance(domain, str) and domain:
                args += ["--domain", domain]
            path = cookie.get("path")
            if isinstance(path, str) and path:
                args += ["--path", path]
            if cookie.get("secure") is True:
                args.append("--secure")
            if cookie.get("httpOnly") is True or cookie.get("http_only") is True:
                args.append("--http-only")
            args += ["--session", session.name, "--json", "--", name, value]
            try:
                self._run(args, check_success=True)
            except CliError as exc:
                raise RestoreError(f"could not restore cookie {name!r}") from exc
            cookies_set += 1
            if any(
                key in cookie
                for key in ("expires", "sameSite", "same_site", "priority")
            ):
                lossy_cookies += 1
        for origin, values in record.local_storage.items():
            parts = urlsplit(origin) if isinstance(origin, str) else None
            if (
                parts is None
                or parts.scheme not in ("http", "https")
                or not parts.netloc
            ):
                raise RestoreError(
                    f"a stored localStorage origin is malformed: {origin!r}"
                )
            if not isinstance(values, Mapping):
                raise RestoreError(
                    f"stored localStorage for {origin!r} is not an object"
                )
            try:
                self._run(
                    [
                        "browser",
                        "navigate",
                        origin,
                        "--session",
                        session.name,
                        "--json",
                    ],
                    check_success=True,
                )
            except CliError as exc:
                raise RestoreError(
                    f"could not visit the stored origin {origin!r}"
                ) from exc
            origins_visited += 1
            for key, value in values.items():
                if (
                    not isinstance(key, str)
                    or not key
                    or not isinstance(value, str)
                ):
                    raise RestoreError(
                        f"stored localStorage for {origin!r} is not a string map"
                    )
                try:
                    self._run(
                        [
                            "browser",
                            "storage",
                            "local",
                            "set",
                            "--session",
                            session.name,
                            "--json",
                            "--",
                            key,
                            value,
                        ],
                        check_success=True,
                    )
                except CliError as exc:
                    raise RestoreError(
                        f"could not restore localStorage key {key!r}"
                    ) from exc
                storage_keys_set += 1
        if origins_visited:
            try:
                self._run(
                    [
                        "browser",
                        "navigate",
                        _RESET_URL,
                        "--session",
                        session.name,
                        "--json",
                    ],
                    check_success=True,
                )
            except CliError as exc:
                raise RestoreError("could not reset the page after restore") from exc
        warnings = ()
        if lossy_cookies:
            warnings = (
                f"{lossy_cookies} cookie attribute set is not restorable "
                "through the CLI",
            )
        return RestoreReport(
            cookies_set=cookies_set,
            origins_visited=origins_visited,
            storage_keys_set=storage_keys_set,
            warnings=warnings,
        )

    def _current_url(self, session: CliSession) -> str | None:
        try:
            payload = self._run(
                ["browser", "get", "url", "--session", session.name, "--json"],
                check_success=True,
            )
        except CliError:
            return None
        data = payload.get("data")
        if isinstance(data, str):
            return data
        if isinstance(data, Mapping):
            value = data.get("url") or data.get("href")
            if isinstance(value, str):
                return value
        return None

    def capture(
        self,
        session: CliSession,
        previous: BrowserSessionRecord | None = None,
    ) -> CapturedContext:
        """Capture the context through the API, with a CLI fallback."""
        try:
            context = self._api.context(session.session_id)
            if _needs_origin_resolution(context):
                context = _normalise_storage(
                    context, self._current_url(session), previous
                )
            return CapturedContext(context=context, source="api")
        except WorkerAPIError:
            pass
        warnings: list[str] = []
        try:
            cookies_payload = self._run(
                ["browser", "cookies", "--session", session.name, "--json"],
                check_success=True,
            )
        except CliError as exc:
            raise CaptureError("the browser state could not be captured") from exc
        cookies = cookies_payload.get("data")
        if not isinstance(cookies, list):
            raise CaptureError("the CLI cookie capture is not a list")
        storage: dict[str, dict[str, str]] = {}
        try:
            origin = _origin(self._current_url(session))
            if origin:
                storage_payload = self._run(
                    [
                        "browser",
                        "storage",
                        "local",
                        "--session",
                        session.name,
                        "--json",
                    ],
                    check_success=True,
                )
                values = storage_payload.get("data")
                if isinstance(values, dict):
                    storage[origin] = {
                        key: value
                        for key, value in values.items()
                        if isinstance(key, str) and isinstance(value, str)
                    }
        except CliError:
            warnings.append(
                "localStorage capture failed; the fallback saved cookies only"
            )
        return CapturedContext(
            context={"cookies": cookies, "localStorage": storage},
            source="cli",
            warnings=tuple(warnings),
        )
