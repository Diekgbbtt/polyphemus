"""Transient upstream faults: classify, back off, rotate, count (#299).

The opencode-go lane intermittently enters a short degraded window in which it
returns a bare HTTP 400 - an empty body, or a body that only echoes the
stripped wire model id (`{"model": "deepseek-v4.1-flash"}`) - for EVERY request,
independent of the client's request well-formedness. The app cannot tell that
bare 400 from a deterministic contract error, so the actor degrades the turn and
the hunt dies on an upstream blip (the same class as #285's dropped recon
extraction).

This module is the ONE home of the transient-fault policy:

- `classify_error(exc)` - the pure classifier: a bare 400 is `transient`
  (distinct from a recognisable `contract` 400), the existing
  transport/timeout/5xx/429 class is `transient`, and anything unknown is
  `fatal` (fail-open: never mint a retry for a fault we do not understand).
- `jittered_backoff(attempt)` - the exponential, capped, jittered delay that
  rides out a temporal window instead of re-firing inside it.
- `rotate_conversation(thread_id, attempt)` - the per-attempt conversation id
  (`<thread_id>#r<attempt>`) that abandons a pinned bad upstream replica without
  forking agent memory; the checkpointer keeps the original `thread_id`.
- `record_transient(...)` - the structured per-attempt counter and log record
  that makes a recurrence visible before it kills a run.

Import discipline (CODING_STANDARD section 6): the module top imports stdlib
and the app's own classifier only; the provider SDKs are imported lazily inside
the helpers, so importing this module is I/O- and env-var-free.
"""
from __future__ import annotations

import json
import logging
import random
from typing import Callable, Literal

logger = logging.getLogger(__name__)

TransientKind = Literal["transient", "contract", "fatal"]

# The bare-400 body shapes the opencode-go lane emits: the body is absent, or it
# echoes only the stripped wire model id. Both are the same class (DEBUG.md).
_BARE_MODEL_KEY = "model"

# Recognisable, ACTIONABLE contract-400 markers (the ticket's list). A body that
# carries one of these is a deterministic client-contract error - fail fast, do
# not burn the retry schedule on it. Lowercased substrings.
_CONTRACT_MARKERS = (
    "missingsessionid",
    "missing session",
    "reasoning_content",
    "response_format",
    "top_p",
    "missing field name",
)

DEFAULT_TRANSIENT_BACKOFF_S = 2.0
DEFAULT_TRANSIENT_BACKOFF_MAX_S = 30.0
DEFAULT_TRANSIENT_JITTER = 0.3


def _read_positive_float(env: str, default: float) -> float:
    import os

    from polymerhus.app.llm.providers import LLMConfigError

    raw = os.environ.get(env)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise LLMConfigError(f"{env} must be a number (got {raw!r})") from None
    if value <= 0:
        raise LLMConfigError(f"{env} must be positive (got {raw!r})")
    return value


def _read_fraction(env: str, default: float) -> float:
    import os

    from polymerhus.app.llm.providers import LLMConfigError

    raw = os.environ.get(env)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise LLMConfigError(f"{env} must be a fraction (got {raw!r})") from None
    if not 0.0 <= value <= 1.0:
        raise LLMConfigError(f"{env} must be within 0..1 (got {raw!r})")
    return value


def transient_backoff_base() -> float:
    """The base transient backoff, overridable via `LLM_TRANSIENT_BACKOFF_S`."""
    return _read_positive_float("LLM_TRANSIENT_BACKOFF_S", DEFAULT_TRANSIENT_BACKOFF_S)


def transient_backoff_max() -> float:
    """The transient backoff cap, overridable via `LLM_TRANSIENT_BACKOFF_MAX_S`."""
    return _read_positive_float("LLM_TRANSIENT_BACKOFF_MAX_S", DEFAULT_TRANSIENT_BACKOFF_MAX_S)


def transient_jitter() -> float:
    """The jitter fraction (0..1), overridable via `LLM_TRANSIENT_JITTER`."""
    return _read_fraction("LLM_TRANSIENT_JITTER", DEFAULT_TRANSIENT_JITTER)


def jittered_backoff(attempt: int, *, base: float | None = None, cap: float | None = None,
                     jitter: float | None = None,
                     rng: Callable[[], float] = random.random) -> float:
    """The delay before retry `attempt` (1-based): exponential from `base`, capped
    at `cap`, scaled by a +/-`jitter` fraction of a random draw. The observed
    window is seconds, so the default schedule (2, 4, 8, 16, 30s) rides it out
    instead of re-firing inside it. `rng` is injectable so the unit tier is
    deterministic."""
    base = transient_backoff_base() if base is None else base
    cap = transient_backoff_max() if cap is None else cap
    jitter = transient_jitter() if jitter is None else jitter
    delay = min(cap, base * (2 ** max(0, attempt - 1)))
    factor = 1.0 + (rng() * 2.0 - 1.0) * jitter
    return max(0.0, delay * factor)


_ROTATION_SUFFIX = "#r"


def rotate_conversation(thread_id: str, attempt: int) -> str:
    """The conversation id for retry `attempt` (0-based): attempt 0 is the
    thread's own id (unchanged); each later attempt appends `#r<attempt>`. Only
    the provider conversation primitive (`x-opencode-session`) rotates - the
    checkpointer keeps `thread_id`, so agent memory is never forked."""
    return thread_id if attempt <= 0 else f"{thread_id}{_ROTATION_SUFFIX}{attempt}"


def _error_body(exc: BaseException):
    """The raise's parsed body, best effort: the openai SDK's own `.body`, else
    the response's JSON, else its raw text. None when nothing is readable."""
    body = getattr(exc, "body", None)
    if body is not None:
        return body
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        return response.json()
    except Exception:  # noqa: BLE001 - a body is never load-bearing
        return getattr(response, "text", None)


def _body_text(body) -> str:
    if body is None:
        return ""
    if isinstance(body, str):
        return body
    try:
        return json.dumps(body, ensure_ascii=False)
    except Exception:  # noqa: BLE001 - a weird body is never load-bearing
        return str(body)


def _is_bare_400_body(body) -> bool:
    if body is None:
        return True
    if isinstance(body, str):
        return body.strip() == ""
    if isinstance(body, dict):
        if not body:
            return True
        return (set(body.keys()) == {_BARE_MODEL_KEY}
                and isinstance(body.get(_BARE_MODEL_KEY), str))
    return False


def _is_contract_400_body(body) -> bool:
    text = _body_text(body).lower()
    return any(marker in text for marker in _CONTRACT_MARKERS)


def _status_code(exc: BaseException) -> int | None:
    from polymerhus.app.llm.provider_failure import status_code

    return status_code(exc)


def body_shape(exc: BaseException) -> str:
    """The observable body shape of a raise, for the structured counter:
    `empty` / `model` (the bare-400 signatures), `contract`, `other` (a 400 with
    an unrecognised body), or `n/a` (not a 400)."""
    if _status_code(exc) != 400:
        return "n/a"
    body = _error_body(exc)
    if _is_bare_400_body(body):
        if isinstance(body, dict) and body:
            return "model"
        return "empty"
    if _is_contract_400_body(body):
        return "contract"
    return "other"


def classify_error(exc: BaseException) -> TransientKind:
    """Classify a turn raise for the retry policy.

    - `transient`: the existing transport/timeout/5xx/429 provider-failure class
      PLUS an HTTP 400 whose body is empty or only echoes the wire model id (the
      opencode-go transient-window signature).
    - `contract`: a 400 with a recognisable, actionable contract body.
    - `fatal`: anything else (fail-open: an unknown fault is never retried).
    """
    from polymerhus.app.llm.provider_failure import is_provider_unavailable

    if is_provider_unavailable(exc):
        return "transient"
    if _status_code(exc) == 400:
        body = _error_body(exc)
        if _is_bare_400_body(body):
            return "transient"
        if _is_contract_400_body(body):
            return "contract"
    return "fatal"


# The process-wide transient counter, keyed by (role, model, body_shape). It is
# observability, not control flow: a failed increment never affects a retry.
_TRANSIENT_COUNTS: dict[tuple[str, str, str], int] = {}


def record_transient(*, role: str, model: str, conversation_id: str, attempt: int,
                     status: int | None, body_shape: str) -> None:
    """Emit one structured counter record per transient bare-400 attempt, so a
    recurrence is visible (in logs and the in-process count) before exhaustion
    kills the turn. Purely descriptive and fail-open."""
    try:
        key = (str(role), str(model), str(body_shape))
        _TRANSIENT_COUNTS[key] = _TRANSIENT_COUNTS.get(key, 0) + 1
    except Exception:  # noqa: BLE001 - a counter never breaks a retry
        pass
    logger.warning(
        "llm-transient-upstream: role=%s model=%s conversation_id=%s attempt=%s "
        "status=%s body_shape=%s",
        role, model, conversation_id, attempt, status, body_shape)


def transient_counts() -> dict[tuple[str, str, str], int]:
    """A copy of the process-wide transient counts (role, model, body_shape) -> n."""
    return dict(_TRANSIENT_COUNTS)


def reset_transient_counts() -> None:
    """Clear the process-wide transient counts (the unit tier's isolation seam)."""
    _TRANSIENT_COUNTS.clear()


__all__ = [
    "TransientKind",
    "classify_error",
    "body_shape",
    "jittered_backoff",
    "transient_backoff_base",
    "transient_backoff_max",
    "transient_jitter",
    "rotate_conversation",
    "record_transient",
    "transient_counts",
    "reset_transient_counts",
    "DEFAULT_TRANSIENT_BACKOFF_S",
    "DEFAULT_TRANSIENT_BACKOFF_MAX_S",
    "DEFAULT_TRANSIENT_JITTER",
]
