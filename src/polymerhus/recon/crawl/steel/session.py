"""The Steel session client: catalogue, attach, CLI envelope, and stop.

Spec: `docs/design/steel-crawl-spec.md` sections 4, 4.1, 4.3, and 4.4.

The crawl never starts a session: it attaches to exactly one pre-authenticated
session by name and runtime id, sends every later command with `--session` and
`--json`, and stops the session it owns. The two options are placed after the
verb and before every positional, so a variadic verb's mandatory `--` boundary
is the last thing before its value and no option can fold into the value text.
`start` is absent from the public surface by construction, so the lifecycle
cannot be reached from this client.

`SteelSessionRegistry` only observes; it owns no lifecycle action and cannot
start, stop, or release anything. The lifecycle owner calls the observations.

The websocket URL is a secret: it is wrapped in `SecretStr`, so neither the
record's `repr`/`str`, a `model_dump(mode="json")`, nor a log line that renders
the record can carry it. The CDP sidecar reads it with
`websocket_url.get_secret_value()` and never logs it.

Importing this module performs no I/O (CODING_STANDARD section 6): the default
`exec_fn` resolves a subprocess only when a command is executed.
"""
from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, SecretStr

DEFAULT_PREFIX: tuple[str, ...] = ("steel", "browser")


def steel_prefix(*, api_url: str | None = None) -> tuple[str, ...]:
    """The `steel browser` prefix, optionally with the global `--api-url`.

    `--api-url` is a global CLI flag, so it sits before `browser`. A caller
    passes the result as `SteelSessionClient(prefix=...)`; the client itself
    never hardcodes a host.
    """
    if api_url:
        return ("steel", "--api-url", api_url, "browser")
    return DEFAULT_PREFIX


class SteelSession(BaseModel):
    """One observed Steel browser session.

    `session_id` is the runtime id and `name` is the CLI name. The two are the
    stable identity pair; a name can be reused after a release, so the runtime
    id is the tiebreaker.
    """

    model_config = ConfigDict(frozen=True)

    session_id: str
    name: str
    status: str = "unknown"
    viewer_url: str = ""
    debug_url: str = ""
    debugger_url: str = ""
    websocket_url: SecretStr | None = None
    created_at: str | None = None
    remaining_ms: int | None = None
    inactivity_timeout_ms: int | None = None
    source: str = "unknown"

    @property
    def is_live(self) -> bool:
        return self.status == "live"

    @classmethod
    def from_catalogue(cls, item: Mapping[str, Any]) -> "SteelSession":
        """Build from one `steel browser sessions --json` entry."""
        return cls(
            session_id=str(item.get("id") or ""),
            name=str(item.get("name") or ""),
            status=str(item.get("status") or "unknown"),
            viewer_url=str(item.get("viewerUrl") or ""),
            source=str(item.get("source") or "cli.catalogue"),
        )

    @classmethod
    def from_api(
        cls, data: Mapping[str, Any], *, name: str | None = None
    ) -> "SteelSession":
        """Build from the full runtime record (`GET /v1/sessions/<id>`).

        `name` is the requested name, used only when the record omits it.
        """
        return cls(
            session_id=str(data.get("id") or ""),
            name=str(data.get("name") or name or ""),
            status=str(data.get("status") or "unknown"),
            viewer_url=str(data.get("viewerUrl") or ""),
            debug_url=str(data.get("debugUrl") or ""),
            debugger_url=str(data.get("debuggerUrl") or ""),
            websocket_url=data.get("websocketUrl") or None,
            created_at=_opt_str(data.get("createdAt")),
            remaining_ms=_opt_int(data.get("remainingMs")),
            inactivity_timeout_ms=_opt_int(data.get("inactivityTimeoutMs")),
            source=str(data.get("source") or "api"),
        )

    @classmethod
    def from_start(cls, name: str, data: Mapping[str, Any]) -> "SteelSession":
        """Build from a `steel browser start --json` payload.

        This module never issues the start; a lifecycle owner that did builds
        the record here and hands it to the registry to observe.
        """
        return cls(
            session_id=str(data.get("id") or ""),
            name=str(data.get("name") or name),
            status=str(data.get("status") or "live"),
            viewer_url=str(data.get("liveUrl") or ""),
            websocket_url=data.get("connectUrl") or None,
            created_at=_opt_str(data.get("createdAt")),
            remaining_ms=_opt_int(data.get("remainingMs")),
            inactivity_timeout_ms=_opt_int(data.get("inactivityTimeoutMs")),
            source="cli.start",
        )

    def merge(self, other: "SteelSession") -> "SteelSession":
        """Apply `other`'s observations to this record.

        A newer non-empty field wins; a missing field never erases an earlier
        one, so a catalogue read does not drop the websocket the API read
        learned. Two different runtime ids are not the same session (the name
        was reused), so the merge refuses them.
        """
        if (
            self.session_id
            and other.session_id
            and self.session_id != other.session_id
        ):
            raise ValueError("cannot merge two different Steel sessions")
        status = other.status if other.status not in ("", "unknown") else self.status
        return self.model_copy(
            update={
                "session_id": other.session_id or self.session_id,
                "name": other.name or self.name,
                "status": status,
                "viewer_url": other.viewer_url or self.viewer_url,
                "debug_url": other.debug_url or self.debug_url,
                "debugger_url": other.debugger_url or self.debugger_url,
                "websocket_url": (
                    other.websocket_url
                    if other.websocket_url is not None
                    else self.websocket_url
                ),
                "created_at": other.created_at or self.created_at,
                "remaining_ms": (
                    other.remaining_ms
                    if other.remaining_ms is not None
                    else self.remaining_ms
                ),
                "inactivity_timeout_ms": (
                    other.inactivity_timeout_ms
                    if other.inactivity_timeout_ms is not None
                    else self.inactivity_timeout_ms
                ),
                "source": other.source or self.source,
            }
        )


# `exec_fn(command) -> envelope`: the one impure seam. Tests inject a fake;
# production resolves the real CLI through `_subprocess_exec` on first call.
ExecFn = Callable[[Sequence[str]], Mapping[str, Any]]


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _opt_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _subprocess_exec(command: Sequence[str]) -> dict[str, Any]:
    """Run one Steel CLI command and return its parsed JSON envelope.

    The process facts are added to the CLI's own JSON: the process's own exit
    code, its stderr, and the measured duration. The envelope's `error` stays
    authoritative over the return code, so a successful envelope with a
    non-zero process exit is still a success; the result carries the exit code
    as evidence, not as the decision.
    """
    started = time.perf_counter()
    completed = subprocess.run(
        list(command), capture_output=True, text=True, check=False
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    stdout = completed.stdout.strip()
    try:
        payload = json.loads(stdout) if stdout else None
    except json.JSONDecodeError as exc:
        raise CommandFailed(
            "the Steel CLI did not return JSON "
            f"(exit {completed.returncode}): {completed.stderr.strip()[-200:]}"
        ) from exc
    if not isinstance(payload, dict):
        raise CommandFailed(
            "the Steel CLI returned no JSON object "
            f"(exit {completed.returncode}): {completed.stderr.strip()[-200:]}"
        )
    payload["returncode"] = completed.returncode
    payload["stderr"] = completed.stderr
    payload["duration_ms"] = duration_ms
    return payload


class SteelSessionClient:
    """A synchronous Steel CLI client bound to at most one owned session."""

    def __init__(
        self,
        *,
        exec_fn: ExecFn | None = None,
        prefix: Sequence[str] | None = None,
        registry: SteelSessionRegistry | None = None,
        api_fn: Callable[[str], Mapping[str, Any]] | None = None,
    ) -> None:
        self._exec_fn = exec_fn or _subprocess_exec
        self._prefix = tuple(prefix) if prefix is not None else DEFAULT_PREFIX
        self._registry = registry if registry is not None else SteelSessionRegistry()
        self._api_fn = api_fn
        self._attached: SteelSession | None = None

    @property
    def attached(self) -> SteelSession | None:
        """The session this client owns, or `None` before attach / after stop."""
        return self._attached

    @property
    def registry(self) -> SteelSessionRegistry:
        return self._registry

    def catalogue(self) -> list[SteelSession]:
        """Read the live catalogue. The one global read, so it has no `--session`."""
        envelope = self._run([*self._prefix, "sessions", "--json"])
        data = envelope.get("data")
        if not isinstance(data, list):
            raise CommandFailed("the Steel catalogue response carries no list")
        sessions = []
        for item in data:
            if not isinstance(item, Mapping):
                raise CommandFailed("a Steel catalogue entry is not an object")
            session = SteelSession.from_catalogue(item)
            if not session.name or not session.session_id:
                raise CommandFailed(
                    "a Steel catalogue entry is missing its name or runtime id"
                )
            sessions.append(session)
        self._registry.observe_catalogue(sessions)
        return sessions

    def attach(self, name: str) -> SteelSession:
        """Attach to one live pre-authenticated session by name.

        The filtered catalogue read proves the name is live and binds the
        runtime id. The optional `api_fn` reads the full runtime record by id
        (the websocket and the session clocks) when the caller has one; the
        CLI has no session-record verb, so a caller without it still has the
        identity and status needed for every command.
        """
        live = self.catalogue()
        if not any(session.name == name for session in live):
            if self._registry.was_live(name):
                raise SessionMissing(
                    f"the Steel session {name!r} was live and is now gone"
                )
            raise UnknownSession(f"no live Steel session named {name!r}")
        envelope = self._run(
            [*self._prefix, "sessions", "--session", name, "--json"]
        )
        data = envelope.get("data")
        item: Mapping[str, Any] | None = None
        if isinstance(data, list):
            item = next(
                (
                    entry
                    for entry in data
                    if isinstance(entry, Mapping) and entry.get("name") == name
                ),
                None,
            )
        elif isinstance(data, Mapping) and data.get("name") == name:
            item = data
        if item is None:
            item = next(
                (entry for entry in live if entry.name == name), None
            )
        if item is None:
            raise CommandFailed("the Steel session record is not an object")
        record = (
            item
            if isinstance(item, SteelSession)
            else SteelSession.from_catalogue(item)
        )
        if not record.session_id:
            raise CommandFailed("the Steel session record is missing its runtime id")
        if self._api_fn is not None:
            try:
                full = self._api_fn(record.session_id)
            except Exception:  # noqa: BLE001 - identity survives an API miss
                full = None
            if isinstance(full, Mapping):
                record = record.merge(SteelSession.from_api(full, name=name))
        session = self._registry.observe_api(record)
        self._attached = session
        return session

    def command(self, verb: str, *args: str) -> list[str]:
        """Build one session-bound command: options first, then positionals.

        `--session` and `--json` are options, so they sit directly after the
        verb, before every positional argument and before a variadic verb's
        `--` boundary. A trailing option would be swallowed by a variadic verb
        as value text, and a trailing `--session` would fold the command onto a
        billable auto-provisioned `default` session (skill `steel-browser`,
        variadic boundary).

        A command with no owned session is refused before the command exists:
        the envelope invariant is never left to the CLI to reject. `start` is
        refused outright: the crawl attaches to a pre-authenticated session and
        never creates one (spec 4.3).
        """
        if verb == "start":
            raise InvalidCommand("the crawl never starts a Steel session")
        session = self._require_attached(verb)
        return [
            *self._prefix,
            verb,
            "--session",
            session.name,
            "--json",
            *args,
        ]

    def execute(self, verb: str, *args: str) -> Mapping[str, Any]:
        """Run one session-bound command with the owned session and `--json`."""
        return self._run(self.command(verb, *args))

    def stop(self) -> None:
        """Stop the owned session and prove the catalogue no longer lists it.

        The `stoppedSessions` echo is not proof
        (`skills/internal/tools/steel-browser/SKILL.md`, Close: the catalogue is
        the liveness proof), so the stop is followed by one catalogue read. A
        name that survives raises: the run cannot claim a clean release.
        """
        session = self._require_attached("stop")
        self._run([*self._prefix, "stop", "--session", session.name, "--json"])
        self._registry.observe_stop(session.name)
        if any(entry.name == session.name for entry in self.catalogue()):
            raise SessionStillLive(
                f"the Steel catalogue still lists {session.name!r} after stop"
            )
        self._attached = None

    def _require_attached(self, action: str) -> SteelSession:
        if self._attached is None:
            raise InvalidCommand(
                f"{action} is session-bound but no Steel session is attached"
            )
        return self._attached

    def _run(self, command: Sequence[str]) -> Mapping[str, Any]:
        envelope = self._exec_fn(list(command))
        if not isinstance(envelope, Mapping):
            raise CommandFailed("the Steel CLI did not return a JSON object")
        _raise_for_error(envelope)
        return envelope


class SteelSessionRegistry:
    """A name-keyed observation store. It never starts, stops, or releases."""

    def __init__(self) -> None:
        self._by_name: dict[str, SteelSession] = {}
        self._ever_live: set[str] = set()

    def get(self, name: str) -> SteelSession | None:
        return self._by_name.get(name)

    def live(self) -> list[SteelSession]:
        return [session for session in self._by_name.values() if session.is_live]

    def was_live(self, name: str) -> bool:
        """Whether the name was ever observed live (the `session_missing` test)."""
        return name in self._ever_live

    def observe_catalogue(self, sessions: Iterable[SteelSession]) -> list[SteelSession]:
        incoming = {
            session.name: session
            for session in sessions
            if session.name and session.session_id
        }
        observed = []
        for name, session in incoming.items():
            existing = self._by_name.get(name)
            if existing is not None and existing.session_id == session.session_id:
                session = existing.merge(session)
            self._by_name[name] = session
            if session.is_live:
                self._ever_live.add(name)
            observed.append(session)
        for name, existing in list(self._by_name.items()):
            if name in incoming or not existing.is_live:
                continue
            self._by_name[name] = existing.model_copy(
                update={"status": "lost", "source": "cli.catalogue"}
            )
        return observed

    def observe_api(self, record: SteelSession) -> SteelSession:
        """Observe the full runtime record; the newer runtime id wins."""
        return self._observe(record)

    def observe_start(self, record: SteelSession) -> SteelSession:
        """Observe a start the lifecycle owner performed; the registry never starts."""
        return self._observe(record)

    def _observe(self, record: SteelSession) -> SteelSession:
        existing = self._by_name.get(record.name)
        if existing is not None and existing.session_id == record.session_id:
            record = existing.merge(record)
        self._by_name[record.name] = record
        if record.is_live:
            self._ever_live.add(record.name)
        return record

    def observe_stop(self, name: str) -> SteelSession | None:
        """Observe a successful stop. The registry does not perform it."""
        existing = self._by_name.get(name)
        if existing is None:
            return None
        released = existing.model_copy(
            update={"status": "released", "source": "cli.stop"}
        )
        self._by_name[name] = released
        return released


class SteelSessionError(RuntimeError):
    """A typed Steel session failure. `code` is the contract error code."""

    code = "command_failed"
    default_message = "the Steel command failed"

    def __init__(self, message: str = "") -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class UnknownSession(SteelSessionError):
    """The name was never live. Choose a live name."""

    code = "unknown_session"
    default_message = "the Steel session name was never live"


class SessionMissing(SteelSessionError):
    """The name was live and is gone. The crawl never recreates it."""

    code = "session_missing"
    default_message = "the Steel session was live and is now gone"


class InvalidCommand(SteelSessionError):
    """The session-bound command has no session to carry, or bad grammar."""

    code = "invalid_command"
    default_message = "the Steel command is invalid"


class SessionStillLive(SteelSessionError):
    """The stop proof failed: the catalogue still lists the owned name.

    This is a client-side invariant, not a CLI error code; the run must not
    report a released session when the catalogue disagrees.
    """

    code = "session_still_live"
    default_message = "the Steel catalogue still lists the stopped session"


class SessionTaken(SteelSessionError):
    """A start named a live session. Reuse the live session."""

    code = "session_taken"
    default_message = "the Steel session name is already taken by a live session"


class TargetLost(SteelSessionError):
    """The CDP target disappeared. Open a tab, then retry the read."""

    code = "target_lost"
    default_message = "the Steel CDP target disappeared"


class BrowserStuck(SteelSessionError):
    """The command exceeded its browser budget. Recreate the session."""

    code = "browser_stuck"
    default_message = "the Steel browser did not answer within its budget"


class GuardError(SteelSessionError):
    """The guard failed. Surface it; do not route around it."""

    code = "guard_error"
    default_message = "the Steel guard failed"


class CommandFailed(SteelSessionError):
    """The execution surface raised, or the envelope is unmapped."""

    code = "command_failed"
    default_message = "the Steel command failed"


# The eight contract codes (spec section 4.4). A code outside this table is a
# `command_failed`; the envelope's `error` is authoritative over its exit code
# and text, so this lookup - never a return-code check - decides the failure.
CLI_ERROR_TYPES: dict[str, type[SteelSessionError]] = {
    "unknown_session": UnknownSession,
    "session_missing": SessionMissing,
    "session_taken": SessionTaken,
    "target_lost": TargetLost,
    "browser_stuck": BrowserStuck,
    "invalid_command": InvalidCommand,
    "command_failed": CommandFailed,
    "guard_error": GuardError,
}


def _typed_error(error: Any) -> SteelSessionError:
    """Map one envelope `error` (a code string or a `{code, message}` object)."""
    if isinstance(error, Mapping):
        code = str(error.get("code") or "")
        detail = str(error.get("message") or "")
    else:
        code, detail = str(error), ""
    error_type = CLI_ERROR_TYPES.get(code)
    if error_type is None:
        return CommandFailed(f"unmapped Steel CLI error: {code or error!r}")
    return error_type(detail)


def _raise_for_error(envelope: Mapping[str, Any]) -> None:
    """Raise the envelope's error first; only then fall back to `success`."""
    error = envelope.get("error")
    if error:
        raise _typed_error(error)
    if envelope.get("success") is not True:
        raise CommandFailed("the Steel CLI reported failure without an error code")


__all__ = [
    "CLI_ERROR_TYPES",
    "DEFAULT_PREFIX",
    "BrowserStuck",
    "CommandFailed",
    "GuardError",
    "InvalidCommand",
    "SessionMissing",
    "SessionStillLive",
    "SessionTaken",
    "SteelSession",
    "SteelSessionClient",
    "SteelSessionError",
    "SteelSessionRegistry",
    "TargetLost",
    "UnknownSession",
    "steel_prefix",
]
