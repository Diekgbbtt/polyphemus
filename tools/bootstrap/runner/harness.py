"""The harness seam: opencode worker sessions over the local service API.

The architecture doc (section 4) fixes the integration point: the local opencode
v2 service API, driven through `opencode api ...` subprocesses - the same
discovery and provider authentication as the operator's own sessions. `opencode
run` is NOT usable here: every variant is refused by the provider with an HTTP
403 `FreeTierError` before any model call (the audit, section 3).

The four methods are exactly the issue's interface - `create_session`,
`prompt`, `wait_terminal`, `interrupt` - plus `messages` for introspection.
Session ids are EXPLICIT and deterministic (`ses_bt_<run_short>_<target>_
<phase>`), so any target's session can be inspected at any time and a resume
finds the same session instead of starting a second one.

Completion is a terminal `idle` message after the sent prompt (the OpenAPI
schema: `Session.Message.Idle` with `outcome: succeeded|failed|interrupted`);
provider failures surface as an assistant message's `error` and/or the idle's
`error`, and both are parsed here and classified for the caller's bounded
backoff. This module never retries by itself: the orchestrator owns the policy,
because it owns the run state the retry has to be recorded in.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, replace
from typing import Callable, Mapping, Protocol, Sequence

from orchestrator.commands import Command, CommandResult

# The retry backoff ladder the architecture doc pins (section 8 / the issue's
# decision list): three attempts, 60s then 300s then 900s.
RETRY_BACKOFF_S: tuple[float, ...] = (60.0, 300.0, 900.0)
DEFAULT_TURN_TIMEOUT_S = 3600.0
DEFAULT_POLL_INTERVAL_S = 5.0
# How many times `prompt` retries the transcript read that establishes the
# watermark before it raises: a degraded watermark would let a previous turn's
# idle count as this turn's completion.
WATERMARK_ATTEMPTS = 3

# Provider failure classes this harness recognises by text. Everything that
# looks transient is retried with backoff; a hard configuration error is not.
_RETRYABLE_PATTERNS: tuple[str, ...] = (
    "freetiererror",
    "free tier",
    "rate limit",
    "ratelimit",
    "too many requests",
    "429",
    "403",
    "quota",
    "503",
    "502",
    "504",
    "timeout",
    "timed out",
    "connection reset",
    "connection refused",
    "temporarily unavailable",
    "overloaded",
    "socket hang up",
    "econnreset",
    "etimedout",
)
_HARD_PATTERNS: tuple[str, ...] = (
    "session not found",
    "model not found",
    "unknown agent",
    "invalid request",
    "unauthorized",
)

_ERROR_RE = re.compile(r"FreeTierError|rate limit|429|403|5\d\d", re.IGNORECASE)

Executor = Callable[[Command], CommandResult]


@dataclass(frozen=True)
class ModelRef:
    """The provider model reference an explicit session pins."""

    provider_id: str
    id: str
    variant: str | None = None

    def payload(self) -> dict:
        body = {"providerID": self.provider_id, "id": self.id}
        if self.variant:
            body["variant"] = self.variant
        return body

    def __str__(self) -> str:
        return f"{self.provider_id}/{self.id}" + (f"#{self.variant}" if self.variant else "")


@dataclass(frozen=True)
class SessionSpec:
    """Everything one created session pins, so the run is reproducible."""

    session_id: str
    title: str
    agent: str
    model: ModelRef
    directory: str
    metadata: Mapping[str, str] = field(default_factory=dict)
    permissions: tuple[Mapping[str, str], ...] = (
        {"action": "*", "resource": "*", "effect": "allow"},
    )

    def payload(self) -> dict:
        return {
            "id": self.session_id,
            "title": self.title,
            "agent": self.agent,
            "model": self.model.payload(),
            "location": {"directory": self.directory},
            "metadata": dict(self.metadata),
            "permissions": [dict(rule) for rule in self.permissions],
        }


@dataclass(frozen=True)
class TurnResult:
    """One awaited turn: how it ended and what the transcript said.

    `model` is the model of the LAST assistant message of the turn, checked
    against the requested reference so a silent model substitution is visible.
    """

    session_id: str
    outcome: str
    ok: bool
    retryable: bool
    error: str = ""
    error_status: int | None = None
    model: Mapping[str, object] | None = None
    messages: tuple[Mapping[str, object], ...] = ()
    watermark: str | None = None


@dataclass(frozen=True)
class HarnessError(Exception):
    """A harness-level failure (transport, create, or an unusable transcript)."""

    message: str
    retryable: bool = False

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class TurnTimeout(HarnessError):
    """A turn that never reached a terminal message inside its window.

    Its own class because the orchestrator owns a distinct recovery policy for
    it (interrupt, then one resume re-prompt); every other HarnessError either
    takes the retry ladder or fails the phase.
    """


class Harness(Protocol):
    """The worker-session seam the orchestrator depends on."""

    def create_session(self, spec: SessionSpec) -> str: ...

    def prompt(self, session_id: str, text: str) -> str: ...

    def wait_terminal(self, session_id: str, timeout_s: float) -> TurnResult: ...

    def interrupt(self, session_id: str) -> CommandResult: ...


# --- pure parsing and classification (unit-tested on recorded shapes) --------


def decode_data(stdout: str) -> object | None:
    """The `{"data": ...}` envelope `opencode api` prints, or None."""
    try:
        decoded = json.loads(stdout or "")
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(decoded, dict) and "data" in decoded:
        return decoded["data"]
    return decoded if decoded is not None else None


def message_list(stdout: str) -> tuple[dict, ...]:
    """The message array from `GET /api/session/{id}/message`."""
    data = decode_data(stdout)
    if isinstance(data, dict):
        data = data.get("data")
    if not isinstance(data, list):
        return ()
    return tuple(item for item in data if isinstance(item, dict))


def _error_from(message: Mapping[str, object]) -> tuple[str, int | None]:
    error = message.get("error")
    if not isinstance(error, dict):
        return "", None
    text = str(error.get("message") or error.get("type") or "")
    status = error.get("status")
    return text, (int(status) if isinstance(status, (int, str)) and str(status).isdigit() else None)


def parse_terminal(
    messages: Sequence[Mapping[str, object]], after: str | None = None
) -> TurnResult | None:
    """The terminal turn in `messages`, or None when the turn is not finished.

    `messages` is expected to be already sliced to the messages NEWER than the
    prompt (see `OpenCodeApiHarness.prompt`), so a terminal message from a
    previous turn can never be mistaken for this one's completion. `after`, when
    given, drops everything up to and including that message id (the
    transcript-tail form used by tests and diagnostics).

    The transcript's assistant error, when present, wins over the idle's own:
    the assistant carries the provider's typed error, while the idle often
    carries only "request failed".
    """
    fresh: list[Mapping[str, object]] = []
    seen_watermark = after is None
    for message in messages:
        if not seen_watermark:
            if str(message.get("id") or "") == after:
                seen_watermark = True
            continue
        fresh.append(message)
    if after is not None and not seen_watermark:
        # The watermark is gone (a compacted or re-created transcript): treat
        # every message as fresh rather than reporting a turn that never ends.
        fresh = list(messages)
    terminal: Mapping[str, object] | None = None
    for message in fresh:
        if message.get("type") == "idle" and isinstance(message.get("outcome"), str):
            terminal = message
            break
    if terminal is None:
        return None
    assistant_error = next(
        (m for m in reversed(fresh) if m.get("type") == "assistant" and m.get("error")),
        None,
    )
    error_text, error_status = ("", None)
    if assistant_error is not None:
        error_text, error_status = _error_from(assistant_error)
    if not error_text:
        error_text, error_status = _error_from(terminal)
    outcome = str(terminal.get("outcome"))
    model = None
    last_assistant = next(
        (m for m in reversed(fresh) if m.get("type") == "assistant" and m.get("model")),
        None,
    )
    if last_assistant is not None:
        candidate = last_assistant.get("model")
        model = dict(candidate) if isinstance(candidate, dict) else None
    return TurnResult(
        session_id=str(terminal.get("sessionID") or ""),
        outcome=outcome,
        ok=outcome == "succeeded" and not error_text,
        retryable=is_retryable(error_text) if error_text else False,
        error=error_text,
        error_status=error_status,
        model=model,
        messages=tuple(fresh),
        watermark=after,
    )


def assistant_text(turn: TurnResult) -> str:
    """The turn's assistant text blocks, concatenated (the worker's report)."""
    parts: list[str] = []
    for message in turn.messages:
        if message.get("type") != "assistant":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "\n".join(parts)


def transcript_tail(turn: TurnResult, *, limit: int = 40, max_chars: int = 20000) -> str:
    """A bounded, human-readable rendering of the turn's own messages.

    This is what lands in a per-turn log: the worker's report, the tool lines,
    and the terminal idle, without the megabytes a long crawl's transcript can
    reach. It is evidence for a human; nothing reads it back.
    """
    lines: list[str] = []
    for message in turn.messages[-limit:]:
        kind = str(message.get("type") or "?")
        if kind == "assistant":
            text = " ".join(
                block.get("text", "")
                for block in (message.get("content") or [])
                if isinstance(block, dict)
            )
            if message.get("error"):
                text = f"{text} [error] {message['error']}"
            lines.append(f"assistant: {text.strip()}")
        elif kind == "idle":
            detail = f" idle: {message.get('outcome')}"
            if message.get("error"):
                detail += f" {message['error']}"
            lines.append(detail)
        elif kind == "user":
            lines.append("user: (the wrapper sent for this turn)")
        else:
            lines.append(f"{kind}: {json.dumps(message)[:400]}")
    rendered = "\n".join(lines)
    if len(rendered) > max_chars:
        rendered = "...[truncated]\n" + rendered[-max_chars:]
    return rendered


def is_retryable(text: str) -> bool:
    """True when a provider error looks transient (rate limit, auth gate, transport).

    The free tier's `FreeTierError` is retryable by decision: it is a provider
    quota event, the run's bounded backoff is what absorbs it, and the target
    phase fails only after the attempts run out.
    """
    lowered = (text or "").lower()
    if any(pattern in lowered for pattern in _HARD_PATTERNS):
        # An explicit unauthorized/not-found is a configuration error, even
        # though "unauthorized" shares the 401/403 range.
        if not _ERROR_RE.search(text or ""):
            return False
    if any(pattern in lowered for pattern in _RETRYABLE_PATTERNS):
        return True
    return bool(_ERROR_RE.search(text or ""))


def classify_stderr(text: str) -> bool:
    """True when an `opencode api` failure on stderr is worth another attempt."""
    return is_retryable(text)


# --- the adapter ------------------------------------------------------------


@dataclass
class OpenCodeApiHarness:
    """`opencode api` as the harness: create, prompt, await, interrupt.

    `executor` is the process seam (a fake in tests); `binary` is the CLI to
    invoke (`opencode`, resolved from PATH by the OS). No failure is retried
    with a backoff policy here; the caller owns that, because the caller also
    owns the run state it is recorded in. The one bounded retry inside is the
    watermark read itself (`_transcript`): it cannot be deferred, because the
    turn boundary has to be sound before the prompt goes out.
    """

    directory: str
    binary: str = "opencode"
    executor: Executor | None = None
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S
    sleep: Callable[[float], None] = time.sleep
    api_timeout_s: float = 120.0
    watermark_attempts: int = WATERMARK_ATTEMPTS
    session_store: dict[str, SessionSpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.executor is None:
            from runner.env import LocalExecutor

            self.executor = LocalExecutor(timeout_s=self.api_timeout_s)
        # The prompt watermark per session: the transcript length the turn
        # starts after, written only by a successful prompt (see `prompt`).
        self._watermarks: dict[str, int] = {}

    # --- command construction (asserted by the unit tests) ---

    def _api_command(self, method: str, path: str, data: object | None = None) -> Command:
        argv = [self.binary, "api", method, path]
        if data is not None:
            argv += ["--data", json.dumps(data)]
        return Command(argv=tuple(argv), cwd=self.directory, description=f"opencode api {method} {path}")

    def _call(self, method: str, path: str, data: object | None = None) -> CommandResult:
        assert self.executor is not None
        return self.executor(self._api_command(method, path, data))

    # --- create / resume ---

    def create_session(self, spec: SessionSpec) -> str:
        """Create the explicit-id session, or adopt the live one with that id.

        An existing id is the resume path, not an error: the API refuses a
        duplicate create, and the run must continue in the session that already
        holds the target's context instead of starting a second one.
        """
        created = self._call("post", "/api/session", spec.payload())
        if created.returncode == 0:
            self.session_store[spec.session_id] = spec
            return spec.session_id
        live = self._call("get", f"/api/session/{spec.session_id}")
        data = decode_data(live.stdout) if live.returncode == 0 else None
        if live.returncode == 0 and data is not None:
            self._align_adopted(spec, data)
            self.session_store[spec.session_id] = spec
            return spec.session_id
        detail = (created.stderr or created.stdout).strip() or "unknown error"
        raise HarnessError(
            f"session {spec.session_id} could not be created or resumed: {detail}",
            retryable=classify_stderr(detail),
        )

    def _align_adopted(self, spec: SessionSpec, live: Mapping[str, object]) -> None:
        """Bring an adopted session onto the run's agent and model.

        A session persists the agent and the model it was created with, so a
        resumed run (a crashed first attempt, a provider-lane change, config
        drift) would otherwise keep dispatching turns on the stale lane - the
        duplicate create only refuses, and nothing else re-examines the pin. A
        failed alignment is a HarnessError: every later turn would silently run
        on the wrong model otherwise.
        """
        live_model = live.get("model")
        pinned = spec.model
        current: ModelRef | None = None
        if isinstance(live_model, Mapping) and live_model.get("providerID") and live_model.get("id"):
            variant = live_model.get("variant")
            current = ModelRef(
                str(live_model["providerID"]),
                str(live_model["id"]),
                str(variant) if isinstance(variant, str) else None,
            )
        if current != pinned:
            aligned = self._call(
                "post", f"/api/session/{spec.session_id}/model", {"model": pinned.payload()}
            )
            if aligned.returncode != 0:
                detail = (aligned.stderr or aligned.stdout).strip() or "unknown error"
                raise HarnessError(
                    f"session {spec.session_id} could not be aligned to {pinned}: {detail}",
                    retryable=classify_stderr(detail),
                )
        if live.get("agent") != spec.agent:
            aligned = self._call(
                "post", f"/api/session/{spec.session_id}/agent", {"agent": spec.agent}
            )
            if aligned.returncode != 0:
                detail = (aligned.stderr or aligned.stdout).strip() or "unknown error"
                raise HarnessError(
                    f"session {spec.session_id} could not be aligned to agent "
                    f"{spec.agent}: {detail}",
                    retryable=classify_stderr(detail),
                )

    # --- prompt / await ---

    def prompt(self, session_id: str, text: str) -> str:
        """Send one user turn; returns its watermark (the transcript length it starts after).

        The watermark is the COUNT of messages already in the transcript, read
        strictly (`_transcript` retries a failed GET a bounded number of times
        and then raises): a degraded watermark of 0 would let the previous
        turn's idle count as this turn's completion. The prompt itself is only
        sent once the boundary is known.
        """
        watermark = len(self._transcript(session_id))
        sent = self._call("post", f"/api/session/{session_id}/prompt", {"text": text})
        if sent.returncode != 0:
            detail = (sent.stderr or sent.stdout).strip() or "unknown error"
            raise HarnessError(
                f"prompt to {session_id} failed: {detail}",
                retryable=classify_stderr(detail),
            )
        self._watermarks[session_id] = watermark
        return str(watermark)

    def messages(self, session_id: str) -> tuple[dict, ...]:
        """The live transcript, best-effort (for introspection and poll reads).

        `prompt` and `wait_terminal` must NOT use this lenient form for the
        turn boundary; they use `_transcript` (via `prompt`) and the stored
        watermark instead.
        """
        result = self._call("get", f"/api/session/{session_id}/message")
        if result.returncode != 0:
            return ()
        return message_list(result.stdout)

    def _transcript(self, session_id: str) -> tuple[dict, ...]:
        """The transcript, read strictly: bounded retries, then a HarnessError.

        A failed GET is never turned into an empty transcript, because an empty
        transcript is a watermark of 0 and a watermark of 0 accepts the
        previous turn's idle as the current turn's terminal message.
        """
        attempts = max(1, self.watermark_attempts)
        detail = "unknown error"
        for attempt in range(attempts):
            result = self._call("get", f"/api/session/{session_id}/message")
            if result.returncode == 0:
                return message_list(result.stdout)
            detail = (result.stderr or result.stdout).strip() or "unknown error"
            if attempt + 1 < attempts:
                self.sleep(max(0.1, self.poll_interval_s))
        raise HarnessError(
            f"transcript for {session_id} could not be read after {attempts} attempt(s): {detail}",
            retryable=classify_stderr(detail),
        )

    def wait_terminal(self, session_id: str, timeout_s: float = DEFAULT_TURN_TIMEOUT_S) -> TurnResult:
        """Poll until a terminal `idle` message newer than the prompt, or raise.

        Only a message that appears AFTER the prompt's watermark can be this
        turn's terminal message; without a watermark for this session there is
        no sound boundary, so the call refuses rather than guess.

        A timeout raises `TurnTimeout`: the orchestrator owns the
        interrupt-and-re-prompt recovery, because that policy has to be visible
        in the run state.
        """
        watermark = self._watermarks.get(session_id)
        if watermark is None:
            raise HarnessError(
                f"no prompt watermark for {session_id}: the turn boundary would be unsound"
            )
        deadline = time.monotonic() + max(0.0, timeout_s)
        interval = max(0.1, self.poll_interval_s)
        while True:
            messages = self.messages(session_id)
            turn = parse_terminal(messages[watermark:])
            if turn is not None:
                if not turn.session_id:
                    turn = replace(turn, session_id=session_id)
                return turn
            if time.monotonic() >= deadline:
                raise TurnTimeout(
                    f"session {session_id} did not reach a terminal turn within {timeout_s}s",
                    retryable=False,
                )
            self.sleep(min(interval, max(0.0, deadline - time.monotonic())))

    def interrupt(self, session_id: str) -> CommandResult:
        return self._call("post", f"/api/session/{session_id}/interrupt")

    def delete_session(self, session_id: str) -> CommandResult:
        """Delete a session (the opt-in smoke test's cleanup)."""
        return self._call("delete", f"/api/session/{session_id}")

    def session_model(self, session_id: str) -> Mapping[str, object] | None:
        """The live session's pinned model, for a resume-time verification."""
        result = self._call("get", f"/api/session/{session_id}")
        data = decode_data(result.stdout)
        if isinstance(data, dict) and isinstance(data.get("model"), dict):
            return data["model"]
        return None
