"""The Steel browser command sanitizer and error canonicalizer.

The bare Steel CLI already rejects malformed subcommands and missing required
arguments with clear ``clap`` errors. This module does not re-implement that
grammar and does not rewrite those errors.

It fills the gaps the CLI leaves open:

* a browser command can silently target a missing, mistyped, or default
  session;
* a composed shell pipeline can hide a nonzero CLI exit behind the last
  command's zero exit;
* the CLI reports a stale CDP page target as a page error while the API session
  still reports ``live``;
* the caller needs one stable error envelope with a recovery directive.

No function here performs I/O. The MCP layer supplies the live session
catalogue and executes the returned recovery directives.
"""
from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass, field
from typing import Any, Iterable

# Browser verbs that do not require a target session.
_SESSION_OPTIONAL_VERBS = frozenset({"sessions", "live"})
# The pinned CLI's variadic verbs. A trailing flag after the first positional
# is folded into the value unless the caller supplies the ``--`` boundary.
_VARIADIC_VERBS = frozenset({"fill", "type", "setvalue", "select", "upload", "batch"})
_BOUNDARY = "--"
_SHELL_SEPARATORS = frozenset({";", "&&", "||", "|", "&"})
_STEEL_BINARIES = frozenset({"steel", "steel-real"})
_HELP_FLAGS = frozenset({"-h", "--help"})
_PAGE_COMMANDS = frozenset({"snapshot", "content", "get"})


@dataclass(frozen=True)
class ContractError:
    """A contextual refusal or a classified browser failure."""

    code: str
    message: str
    retryable: bool
    fatal: bool
    recovery: dict | None = None
    suggestion: str | None = None
    session: str | None = None
    platform_state: dict | None = None
    canonical_command: str | None = None

    def envelope(self) -> dict:
        """The additive MCP result envelope.

        The four legacy fields stay present, so every existing caller keeps
        working. The ``error`` object is the new contract.
        """
        platform = dict(self.platform_state or {})
        session_live = platform.pop("session_live", None)
        return {
            "stdout": "",
            "stderr": self.message,
            "returncode": 2,
            "duration_ms": 0,
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "fatal": self.fatal,
                "recovery": self.recovery,
                "suggestion": self.suggestion,
                "session": {
                    "name": self.session,
                    "live": session_live,
                },
                "platform_state": platform or None,
                "canonical_command": self.canonical_command,
            },
        }


@dataclass(frozen=True)
class BrowserCommand:
    """One parsed ``steel browser`` command."""

    verb: str
    session: str | None
    tokens: tuple[str, ...]
    canonical: str


def _quote(tokens: Iterable[str]) -> str:
    return shlex.join(list(tokens))


def _tokenize(command: str) -> list[str] | None:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return None


def _split_segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in _SHELL_SEPARATORS:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _first_binary(segment: list[str]) -> str | None:
    if not segment:
        return None
    base = os.path.basename(segment[0])
    return base if base in _STEEL_BINARIES else None


def _browser_index(segment: list[str]) -> int | None:
    for index, token in enumerate(segment):
        if token == "browser":
            return index
    return None


def _session_from_tokens(tokens: list[str]) -> tuple[str | None, str | None]:
    """Return ``(session, error_code)`` from a command segment.

    The scan stops at the variadic boundary: anything after ``--`` is a value,
    not an option.
    """
    values: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == _BOUNDARY:
            break
        if token == "--session":
            if index + 1 >= len(tokens):
                return None, "missing_session"
            values.append(tokens[index + 1])
            index += 2
            continue
        if token.startswith("--session="):
            values.append(token.split("=", 1)[1])
            index += 1
            continue
        index += 1
    if len(values) > 1:
        return None, "ambiguous_session"
    return (values[0] if values else None), None


def _contract_error(
    code: str,
    message: str,
    *,
    session: str | None = None,
    retryable: bool = True,
    fatal: bool = False,
    recovery: dict | None = None,
    suggestion: str | None = None,
    platform_state: dict | None = None,
    canonical_command: str | None = None,
) -> ContractError:
    return ContractError(
        code=code,
        message=message,
        retryable=retryable,
        fatal=fatal,
        recovery=recovery,
        suggestion=suggestion,
        session=session,
        platform_state=platform_state,
        canonical_command=canonical_command,
    )


def _boundary_gap(tokens: list[str]) -> str | None:
    if not tokens:
        return None
    verb = None
    for index, token in enumerate(tokens):
        if token == "browser" and index + 1 < len(tokens):
            verb = tokens[index + 1]
            break
    if verb not in _VARIADIC_VERBS:
        return None
    if _BOUNDARY not in tokens:
        return verb
    return None


def _parse_browser_segment(
    segment: list[str],
    *,
    live_sessions: set[str] | None,
) -> BrowserCommand | ContractError:
    binary = _first_binary(segment)
    if binary is None:
        return _contract_error(
            "not_steel_command",
            "command does not start with the steel executable",
            retryable=False,
            recovery={"action": "fix_command", "reason": "use the steel CLI"},
        )
    browser_at = _browser_index(segment)
    if browser_at is None:
        # A non-browser Steel command (for example `steel --version`) keeps the
        # legacy pass-through behavior. The tool-stack guards only the browser
        # surface.
        return BrowserCommand(verb="", session=None, tokens=tuple(segment),
                              canonical=_quote(segment))
    if browser_at + 1 >= len(segment):
        return _contract_error(
            "missing_browser_verb",
            "steel browser command has no verb",
            retryable=True,
            recovery={"action": "fix_command", "reason": "add a browser verb"},
        )
    verb = segment[browser_at + 1]
    canonical = _quote(segment)
    if verb in _HELP_FLAGS:
        return BrowserCommand(verb=verb, session=None, tokens=tuple(segment),
                              canonical=canonical)
    if any(token in _HELP_FLAGS for token in segment):
        # Help is read-only and never requires a live target.
        return BrowserCommand(verb=verb, session=None, tokens=tuple(segment),
                              canonical=canonical)

    session, session_error = _session_from_tokens(segment)
    if session_error == "ambiguous_session":
        return _contract_error(
            "ambiguous_session",
            "command carries more than one --session value",
            retryable=True,
            recovery={"action": "fix_command", "reason": "pass exactly one --session"},
        )
    if session_error == "missing_session":
        return _contract_error(
            "missing_session",
            "the --session flag has no value",
            retryable=True,
            recovery={"action": "fix_command", "reason": "add a session name"},
        )

    if verb not in _SESSION_OPTIONAL_VERBS and session is None:
        return _contract_error(
            "missing_session",
            f"steel browser {verb} requires --session <name>",
            retryable=True,
            recovery={
                "action": "fix_command",
                "reason": f"add --session <name> to steel browser {verb}",
            },
            suggestion=f"steel browser {verb} --session <name> ...",
            canonical_command=canonical,
        )

    gap = _boundary_gap(segment)
    if gap is not None:
        return _contract_error(
            "variadic_boundary",
            f"steel browser {gap} needs its -- boundary before the value",
            retryable=True,
            recovery={"action": "fix_command", "reason": "insert -- before values"},
            suggestion=f"steel browser {gap} [OPTIONS] <selector> -- <value>...",
            canonical_command=canonical,
        )

    if session is not None and live_sessions is not None:
        live = session in live_sessions
        if verb == "start":
            if live:
                return _contract_error(
                    "session_taken",
                    f"session {session!r} is already live",
                    session=session,
                    retryable=False,
                    fatal=False,
                    recovery={
                        "action": "use_live",
                        "reason": "reuse the live session or choose a new name",
                        "command": f"steel browser sessions --json",
                    },
                    platform_state={"session_live": True},
                )
        elif verb == "stop":
            # Stopping a name that is not live is a safe no-op. The CLI owns
            # the result; a guard would block a legitimate stray cleanup.
            pass
        elif verb == "sessions":
            # A --session value on sessions is a filter, not a target.
            pass
        elif not live:
            return _contract_error(
                "unknown_session",
                f"session {session!r} is not live",
                session=session,
                retryable=False,
                fatal=False,
                recovery={
                    "action": "use_live",
                    "reason": "use a live session name or start a new session",
                    "live_sessions": sorted(live_sessions),
                    "start_command": (
                        f"steel browser start --session <new-name> --json"
                    ),
                },
                platform_state={"session_live": False},
                canonical_command=canonical,
            )
    return BrowserCommand(
        verb=verb,
        session=session,
        tokens=tuple(segment),
        canonical=canonical,
    )


def sanitize_shell_command(
    command: str,
    *,
    live_sessions: set[str] | None,
) -> tuple[BrowserCommand, ...] | ContractError:
    """Validate every embedded ``steel browser`` command in a shell string.

    The function is fail-open for commands with no steel token. It is strict
    for a steel browser command: a missing or unknown target is refused before
    the shell runs. It does not validate the CLI's own subcommand grammar.
    """
    tokens = _tokenize(command)
    if tokens is None:
        if "steel" in command:
            return _contract_error(
                "unparseable_command",
                "the shell command containing steel cannot be parsed",
                retryable=True,
                recovery={"action": "fix_command", "reason": "simplify the shell quoting"},
            )
        return ()
    commands: list[BrowserCommand] = []
    for segment in _split_segments(tokens):
        if _first_binary(segment) is None:
            continue
        parsed = _parse_browser_segment(segment, live_sessions=live_sessions)
        if isinstance(parsed, ContractError):
            return parsed
        commands.append(parsed)
    sessions = {command.session for command in commands if command.session}
    if len(sessions) > 1:
        return _contract_error(
            "ambiguous_session",
            "the shell command targets more than one browser session",
            retryable=True,
            recovery={
                "action": "fix_command",
                "reason": "run one session per command",
                "sessions": sorted(sessions),
            },
        )
    return tuple(commands)


def sanitize_steel_command(
    command: str,
    *,
    live_sessions: set[str] | None,
) -> BrowserCommand | ContractError:
    """Validate one browser command, used by the dedicated ``steel_exec``."""
    parsed = sanitize_shell_command(command, live_sessions=live_sessions)
    if isinstance(parsed, ContractError):
        return parsed
    if not parsed:
        return _contract_error(
            "not_steel_command",
            "command carries no steel browser invocation",
            retryable=False,
            recovery={"action": "fix_command", "reason": "use steel browser"},
        )
    if len(parsed) > 1:
        return _contract_error(
            "multiple_browser_commands",
            "steel_exec accepts one browser command; use steel_exec per command",
            retryable=True,
            recovery={"action": "fix_command", "reason": "send one steel browser command"},
        )
    return parsed[0]


def _json_envelope(text: str) -> dict:
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _classified(
    result: dict,
    error: ContractError,
    *,
    session: str | None,
    live_sessions: set[str] | None,
) -> dict:
    out = dict(result)
    platform = dict(error.platform_state or {})
    platform.setdefault("session_live", session in live_sessions if live_sessions is not None else None)
    error = ContractError(
        code=error.code,
        message=error.message,
        retryable=error.retryable,
        fatal=error.fatal,
        recovery=error.recovery,
        suggestion=error.suggestion,
        session=session,
        platform_state=platform,
        canonical_command=error.canonical_command,
    )
    out["error"] = error.envelope()["error"]
    return out


def classify_result(
    command: str,
    result: dict,
    *,
    session: str | None,
    live_sessions: set[str] | None,
) -> dict:
    """Classify a completed command and add a canonical error or warning.

    The raw ``stdout``, ``stderr``, ``returncode``, and ``duration_ms`` fields
    are preserved. The caller executes any recovery command in ``error``.
    """
    out = dict(result)
    # The binary guard already classified the real invocation. Keep its
    # authoritative error rather than re-deriving one from composed shell text.
    if isinstance(out.get("error"), dict) and out["error"].get("code"):
        return out
    stdout = str(out.get("stdout") or "")
    stderr = str(out.get("stderr") or "")
    returncode = int(out.get("returncode") or 0)
    inner = _json_envelope(stdout)
    inner_error = str(inner.get("error") or "")
    inner_success = inner.get("success")
    session_live = session in live_sessions if (session and live_sessions is not None) else None
    canonical = command
    # Browser-state signals come from stderr or an explicit CLI error object.
    # A successful page body may legitimately contain words such as "websocket"
    # or "Session with given id not found"; those are page content, not CLI
    # state. Never classify page text as a browser failure.
    signal_text = f"{stderr}\n{inner_error}".lower()

    # A stale CDP target is a page-level failure, not a missing API session.
    if "session with given id not found" in signal_text or (
        "cdp error" in signal_text and "not found" in signal_text
    ):
        if session_live is False:
            return _classified(
                out,
                _contract_error(
                    "session_missing",
                    "the browser session is no longer live",
                    session=session,
                    retryable=False,
                    fatal=True,
                    recovery={
                        "action": "recreate_session",
                        "reason": "the API session disappeared",
                        "requires_state_restore": True,
                        "command": "steel browser start --session <new-name> --json",
                    },
                    platform_state={"session_live": False},
                    canonical_command=canonical,
                ),
                session=session,
                live_sessions=live_sessions,
            )
        return _classified(
            out,
            _contract_error(
                "target_lost",
                "the session is live but its page target is gone",
                session=session,
                retryable=False,
                fatal=False,
                recovery={
                    "action": "tab_new",
                    "reason": "create a fresh page target in the same browser context",
                    "command": f"steel browser tab new --session {session} --json",
                    "fallback": "recreate_session",
                },
                platform_state={"session_live": True, "target": "missing"},
                canonical_command=canonical,
            ),
            session=session,
            live_sessions=live_sessions,
        )

    if returncode == 124 or "timeout after" in stderr.lower() or "timed out" in stderr.lower():
        return _classified(
            out,
            _contract_error(
                "browser_stuck",
                "the browser command timed out and the page may be blocked",
                session=session,
                retryable=False,
                fatal=True,
                recovery={
                    "action": "recreate_session",
                    "reason": "a blocked page does not recover by retrying the command",
                    "requires_state_restore": True,
                    "command": "steel browser start --session <new-name> --json",
                },
                platform_state={"session_live": session_live, "target": "unresponsive"},
                canonical_command=canonical,
            ),
            session=session,
            live_sessions=live_sessions,
        )

    unavailable_markers = (
        "econnrefused",
        "connection refused",
        "websocket",
        "socket hang up",
        "connect failed",
        "connection reset",
    )
    if any(marker in signal_text for marker in unavailable_markers):
        return _classified(
            out,
            _contract_error(
                "browser_unavailable",
                "the Steel browser runtime is unreachable",
                session=session,
                retryable=False,
                fatal=True,
                recovery={
                    "action": "recreate_session",
                    "reason": "the browser runtime did not answer",
                    "requires_state_restore": True,
                    "command": "steel browser start --session <new-name> --json",
                },
                platform_state={"session_live": session_live, "runtime": "unavailable"},
                canonical_command=canonical,
            ),
            session=session,
            live_sessions=live_sessions,
        )

    if session and session_live is False and any(
        marker in signal_text for marker in (
            "session not found",
            "no such session",
            "session does not exist",
            "session expired",
            "session with given id not found",
        )
    ):
        return _classified(
            out,
            _contract_error(
                "session_missing",
                "the browser session is no longer live",
                session=session,
                retryable=False,
                fatal=True,
                recovery={
                    "action": "recreate_session",
                    "reason": "the API session disappeared",
                    "requires_state_restore": True,
                    "command": "steel browser start --session <new-name> --json",
                },
                platform_state={"session_live": False},
                canonical_command=canonical,
            ),
            session=session,
            live_sessions=live_sessions,
        )

    if returncode != 0 or inner_success is False or inner_error or (
        returncode == 0 and ("error:" in stderr.lower() or "usage:" in stderr.lower())
    ):
        message = inner_error or stderr.strip() or stdout.strip() or "the command failed"
        code = "invalid_command" if returncode != 0 else "cli_error"
        return _classified(
            out,
            _contract_error(
                code,
                message[:600],
                session=session,
                retryable=True,
                fatal=False,
                recovery={
                    "action": "fix_command",
                    "reason": "the Steel CLI rejected the command; fix the request",
                },
                platform_state={"session_live": session_live},
                canonical_command=canonical,
            ),
            session=session,
            live_sessions=live_sessions,
        )

    # A zero exit can still be a page-level success on a blank target. Treat it
    # as a warning, never as a positive page result.
    verb = ""
    for token_index, token in enumerate(shlex.split(command) if command else []):
        if token == "browser" and token_index + 1 < len(shlex.split(command)):
            verb = shlex.split(command)[token_index + 1]
            break
    if verb in _PAGE_COMMANDS and not any(
        separator in command for separator in (";", "|", "&", "\n")
    ):
        data = inner.get("data") if isinstance(inner, dict) else None
        blank = data in ("", None, "(no interactive elements)",
                         "<html><head></head><body></body></html>")
        if isinstance(data, dict):
            text_value = data.get("text")
            blank = text_value in ("", None) if text_value is not None else False
        if blank and "warning" not in out:
            out["warning"] = {
                "code": "empty_target",
                "message": "the page read returned no target content",
                "recovery": {
                    "action": "tab_new",
                    "reason": "the active page may be about:blank",
                    "command": f"steel browser tab new --session {session} --json",
                },
                "session": {"name": session, "live": session_live},
            }
    return out
