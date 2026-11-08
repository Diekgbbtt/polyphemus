"""The one agent-facing browser tool over the shared pool.

The tool is a single software construct with three commands: `start`, `exec`,
and `end`. The session name is not an agent parameter; the binding derives it
from the execution unit. The auth context is a decoupled object in the pool
store, referenced by the auth store; `start` mounts it and `end` can update it
only when the agent asks with `persist_context`.

The tool description carries the usage contract, exactly as every other tool
does. The `steel-browser` skill carries the detailed command mechanics.

The module imports no driver and performs no I/O at import.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import json
import re
import threading
from typing import Any, Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from polymerhus.app.llm.browser_client import (
    BrowserMcpError,
    BrowserUnavailable,
    McpBrowserClient,
)

BROWSER_TOOL_NAME = "browser"
BROWSER_SKILL = "steel-browser"
BROWSER_CONTEXT_PREFIX = "steel-auth"
BROWSER_SESSION_PREFIX = "steel"
# The pool store accepts 128, but the Steel CLI daemon listens on
# /root/.config/steel/daemon-<name>.sock, and Linux sun_path is 108 bytes
# INCLUDING the terminator. The 27-byte prefix and the 5-byte suffix leave 75
# bytes for the name; a longer one makes the CLI answer
# "path must be shorter than SUN_LEN" and the session never starts.
_SESSION_MAX = 75
_SLUG = re.compile(r"[^A-Za-z0-9_-]+")

__all__ = [
    "BROWSER_CONTEXT_PREFIX",
    "BROWSER_SESSION_PREFIX",
    "BROWSER_SKILL",
    "BROWSER_TOOL_DESCRIPTION",
    "BROWSER_TOOL_NAME",
    "BrowserArgs",
    "BrowserTool",
    "browser_context_ref",
    "browser_session_name",
    "build_browser_tool",
]


BROWSER_TOOL_DESCRIPTION = (
    "One web browser over the shared pool. `command` is exactly one of:\n"
    "- `start`: mount the execution unit's browser. url is optional and "
    "loads the first page; if it is omitted, the first `exec` must be a "
    "`navigate`. `account` optionally selects an authenticated auth context; "
    "if it is omitted, the browser starts anonymous. "
    "The session name is internal; never pass one.\n"
    "- `exec`: run one browser command in `input` (`navigate https://...`, "
    "`snapshot -i`, `get text body`, `fill '#user' -- value`, `eval 1+1`, "
    "`wait --selector '#app'`, `batch -- \"snapshot -i\" \"click @e1\"`). The "
    "grammar has no session flag and no lifecycle verb; the lease supplies the "
    "session.\n"
    "- `end`: capture, save, stop, and release. `persist_context` writes the "
    "captured state back to the selected account's decoupled auth context; use "
    "it only when the agent intends to update the stored authentication state. "
    "End the session when the browser is not needed anymore.\n\n"
    "Open the web browser only for a client-side rendered page, a JS-heavy "
    "target, or a native client-side primitive needed in the interaction. A "
    "plain HTTP read belongs to `exec`, `graph_view`, or the HTTP-history "
    "pair. The full mechanics are the `steel-browser` skill.\n\n"
    "A failure is `{\"success\": false, \"error\": {\"code\", \"message\", "
    "\"retryable\"}}`. `session_in_use` means the internal session is already "
    "mounted; `no_session` means call `start` first; `pool_exhausted` means no "
    "worker is free; `restore_failed` means the auth context could not be "
    "mounted; `browser_unavailable` means the pool is unreachable."
)


class BrowserArgs(BaseModel):
    """The arguments of the one browser tool."""

    model_config = ConfigDict(extra="forbid")

    command: Literal["start", "exec", "end"] = Field(
        description="The operation: start, exec, or end."
    )
    url: str | None = Field(
        default=None,
        description=(
            "start only: the optional first page URL. If omitted, the first "
            "exec command must be a navigate."
        ),
    )
    input: str | None = Field(
        default=None,
        description=(
            "exec only: the browser command string, for example "
            "`navigate https://app.test` or `snapshot -i`."
        ),
    )
    account: str | None = Field(
        default=None,
        description=(
            "start only: the optional auth-context account name. If omitted, "
            "the browser starts anonymous."
        ),
    )
    persist_context: bool = Field(
        default=False,
        description=(
            "end only: write the captured browser state back to the account's "
            "decoupled auth context. Use it only when the agent intends to "
            "update the stored authentication state."
        ),
    )


def _slug(value: str, fallback: str) -> str:
    text = _SLUG.sub("-", (value or "").strip()).strip("-_")
    text = re.sub(r"-{2,}", "-", text).lower()
    return text or fallback


def _bounded(prefix: str, parts: list[str]) -> str:
    name = "-".join([prefix, *[part for part in parts if part]])
    if len(name) <= _SESSION_MAX:
        return name
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
    head = name[: _SESSION_MAX - len(digest) - 1].rstrip("-_")
    return f"{head}-{digest}"


def browser_context_ref(project_id: str, account: str) -> str:
    """The durable, decoupled auth-context key for one account.

    The context is independent of any browser session name. The auth store
    references it; the pool store holds the object.
    """
    return _bounded(
        BROWSER_CONTEXT_PREFIX,
        [_slug(project_id, "project"), _slug(account, "account")],
    )


def browser_session_name(
    project_id: str,
    role: str,
    instance_id: str,
    account: str | None = None,
) -> str:
    """The ephemeral browser session key for one execution unit.

    The name follows `steel-<project>[-<account>]-<role>-<instance>`. It is
    never an agent parameter; the binding derives it.
    """
    parts = [_slug(project_id, "project")]
    if account:
        parts.append(_slug(account, "account"))
    parts.append(_slug(role, "agent"))
    parts.append(_slug(instance_id, "run"))
    return _bounded(BROWSER_SESSION_PREFIX, parts)


class BrowserTool(BaseTool):
    """One browser tool over one MCP session, bound to one execution unit."""

    name: str = BROWSER_TOOL_NAME
    description: str = BROWSER_TOOL_DESCRIPTION
    args_schema: type[BaseModel] = BrowserArgs

    _client: McpBrowserClient | None = PrivateAttr(default=None)
    _session_name_factory: Callable[[str | None], str] = PrivateAttr()
    _context_ref_resolver: Callable[[str | None], str | None] = PrivateAttr()
    _bound_account: str | None = PrivateAttr(default=None)
    _unavailable_reason: str | None = PrivateAttr(default=None)
    _record_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], None] | None = (
        PrivateAttr(default=None)
    )
    _started: bool = PrivateAttr(default=False)
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    def __init__(
        self,
        *,
        client: McpBrowserClient | None,
        session_name_factory: Callable[[str | None], str],
        context_ref_resolver: Callable[[str | None], str | None],
        record_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], None] | None = None,
        unavailable_reason: str | None = None,
    ) -> None:
        super().__init__()
        self._client = client
        self._session_name_factory = session_name_factory
        self._context_ref_resolver = context_ref_resolver
        self._record_fn = record_fn
        self._unavailable_reason = unavailable_reason

    def _run(
        self,
        command: str,
        url: str | None = None,
        input: str | None = None,
        account: str | None = None,
        persist_context: bool = False,
    ) -> str:
        selected = account
        with self._lock:
            if command == "start":
                result = self._start(url=url, account=selected)
            elif command == "exec":
                result = self._exec(input=input)
            elif command == "end":
                result = self._end(persist_context=persist_context)
            else:
                result = self._error(
                    "invalid_command",
                    f"unknown browser command {command!r}",
                    retryable=False,
                )
        self._record(
            {
                "command": command,
                "url": url,
                "input": input,
                "account": selected,
                "persist_context": bool(persist_context),
            },
            result,
        )
        return json.dumps(result, ensure_ascii=False)

    def _start(self, *, url: str | None, account: str | None) -> dict:
        if self._client is None:
            return self._error(
                "browser_unavailable",
                self._unavailable_reason
                or "the browser capability is not configured",
                retryable=False,
            )
        try:
            context_ref = self._context_ref_resolver(account)
            start = self._client.start(
                self._session_name_factory(account),
                url=url,
                context_ref=context_ref,
            )
        except BrowserUnavailable as exc:
            return self._error(exc.code, str(exc), retryable=True)
        except BrowserMcpError as exc:
            return self._error(
                exc.code,
                str(exc),
                retryable=exc.retryable,
                recovery=exc.recovery,
            )
        except Exception as exc:  # noqa: BLE001 - the tool never raises
            return self._error(
                "internal_error",
                f"{type(exc).__name__}: {exc}",
                retryable=True,
            )
        self._started = True
        return {
            "success": True,
            "session": {
                "name": start.name,
                "session_id": start.session_id,
            },
            "restored": start.restored,
            "warnings": list(start.warnings),
            "remaining_ms": start.remaining_ms,
            "context_ref": start.context_ref,
        }

    def _exec(self, *, input: str | None) -> dict:
        if self._client is None:
            return self._error(
                "browser_unavailable",
                self._unavailable_reason
                or "the browser capability is not configured",
                retryable=False,
            )
        text = (input or "").strip()
        if not text:
            return self._error(
                "invalid_command",
                "the exec command is required",
                retryable=False,
            )
        if not self._started:
            return self._error(
                "no_session",
                "call browser start before exec",
                retryable=False,
                recovery="call_browser_start_first",
            )
        try:
            return dict(self._client.exec(text))
        except BrowserUnavailable as exc:
            return self._error(exc.code, str(exc), retryable=True)
        except BrowserMcpError as exc:
            if exc.code in {"no_session", "session_still_live"}:
                self._started = False
            return self._error(
                exc.code,
                str(exc),
                retryable=exc.retryable,
                recovery=exc.recovery,
            )
        except Exception as exc:  # noqa: BLE001 - the tool never raises
            return self._error(
                "internal_error",
                f"{type(exc).__name__}: {exc}",
                retryable=True,
            )

    def _end(self, *, persist_context: bool) -> dict:
        if self._client is None:
            return {
                "success": True,
                "ended": False,
                "reason": "no_client",
            }
        if not self._started:
            return {
                "success": True,
                "ended": False,
                "reason": "no_session",
            }
        try:
            result = dict(self._client.end(persist_context=persist_context))
        except BrowserUnavailable as exc:
            return self._error(exc.code, str(exc), retryable=True)
        except BrowserMcpError as exc:
            if exc.code not in {"session_still_live"}:
                self._started = False
            return self._error(
                exc.code,
                str(exc),
                retryable=exc.retryable,
                recovery=exc.recovery,
            )
        except Exception as exc:  # noqa: BLE001 - the tool never raises
            return self._error(
                "internal_error",
                f"{type(exc).__name__}: {exc}",
                retryable=True,
            )
        self._started = False
        return result

    def _record(
        self,
        arguments: Mapping[str, Any],
        result: Mapping[str, Any],
    ) -> None:
        if self._record_fn is None:
            return
        try:
            self._record_fn(arguments, result)
        except Exception:  # noqa: BLE001 - recording never gates a tool
            return None

    @staticmethod
    def _error(
        code: str,
        message: str,
        *,
        retryable: bool,
        recovery: str | None = None,
    ) -> dict:
        error: dict[str, Any] = {
            "code": code,
            "message": message,
            "retryable": bool(retryable),
        }
        if recovery is not None:
            error["recovery"] = recovery
        return {"success": False, "error": error}

    def close(self) -> None:
        """Close the MCP session. Idempotent; the lease TTL is the backstop."""
        with self._lock:
            self._started = False
            client = self._client
            self._client = None
        if client is not None:
            client.close()


def build_browser_tool(
    *,
    project_id: str,
    role: str,
    instance_id: str,
    mcp_url: str | None = None,
    record_fn: Callable[[Mapping[str, Any], Mapping[str, Any]], None] | None = None,
) -> BrowserTool:
    """Build the one browser tool for one execution unit.

    An unset MCP URL yields a bound tool that fails open with
    `browser_unavailable`; the agent surface stays stable in thin mode.
    """
    if mcp_url is None:
        from polymerhus.app.config import config  # noqa: PLC0415

        mcp_url = config.KALI_BROWSER_MCP_URL
    target = (mcp_url or "").strip()
    unavailable_reason = None
    try:
        client = McpBrowserClient(target) if target else None
    except (TypeError, ValueError) as exc:
        # A malformed deployment value is a degraded capability, never a
        # construction failure: the agent surface stays stable and reports
        # `browser_unavailable` with the reason.
        client = None
        unavailable_reason = f"the browser MCP URL is invalid: {exc}"

    def session_name(account_name: str | None) -> str:
        return browser_session_name(project_id, role, instance_id, account_name)

    def context_ref(account_name: str | None) -> str | None:
        if not account_name:
            return None
        return browser_context_ref(project_id, account_name)

    return BrowserTool(
        client=client,
        session_name_factory=session_name,
        context_ref_resolver=context_ref,
        record_fn=record_fn,
        unavailable_reason=unavailable_reason,
    )
