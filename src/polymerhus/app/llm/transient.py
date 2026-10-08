"""Transient upstream faults: classify, back off, rotate, count (#299).

The opencode-go lane intermittently enters a short degraded window in which it
returns a bare HTTP 400 - its body carrying ONLY the stripped wire model id
(`{"model": "deepseek-v4.1-flash"}`) - for EVERY request, independent of the
client's request well-formedness. The app cannot tell that precise 400 from a
deterministic contract error, so the actor degrades the turn and the hunt dies
on an upstream blip (the same class as #285's dropped recon extraction).

The operator ruling (D-1) NARROWS this to the exact lane signature: only a 400
whose single-key `model` body echoes the configured deepseek wire id, raised for
the opencode-go lane, is `transient`. An empty 400, a foreign-model echo, and
any multi-key envelope stay `contract`/`fatal`, so a deterministic client error
can never masquerade as a window.

This module is the ONE home of the transient-fault policy:

- `classify_error(exc, provider=..., model=...)` - the pure classifier: the
  EXACT opencode-go deepseek single-model-echo 400 is `transient`, the existing
  transport/timeout/5xx/429 class is `transient`, a recognisable `contract` 400
  is `contract`, and anything unknown is `fatal` (fail-open: never mint a retry
  for a fault we do not understand).
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

# The single key the transient lane body may carry. The D-1 ruling requires the
# body to be EXACTLY `{"model": <wire-id>}`: any other key (`error`, `message`,
# `type`, `param`, `code`, `detail`) means the raise is a contract/unrecognised
# 400 and must never branch into the fallback.
_MODEL_ECHO_KEY = "model"

# The one provider whose lane emits the transient single-model-echo 400 (#299).
# The lane leg is what keeps an identical body from another provider (or a bare
# model id) from matching: a model id alone is NOT the signature.
_TRANSIENT_LANE_PROVIDER = "opencode-go"

# The deepseek wire ids the lane is known to echo in its degraded window: the
# current `deepseek-v4.1-flash` (#299) and the `deepseek-v4-flash` variant
# observed in the #285 recon drop. Only these ids may branch.
_DEEPSEEK_WIRE_IDS = frozenset({"deepseek-v4.1-flash", "deepseek-v4-flash"})

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
    """Observability only: does the body read as a bare 400 surface (absent, an
    empty string/object, or a single-key `model` echo)? This is NOT the
    classification - the D-1 transient signature additionally requires the lane
    provider and the exact deepseek wire id (`_is_transient_lane_400`)."""
    if body is None:
        return True
    if isinstance(body, str):
        return body.strip() == ""
    if isinstance(body, dict):
        if not body:
            return True
        return (set(body.keys()) == {_MODEL_ECHO_KEY}
                and isinstance(body.get(_MODEL_ECHO_KEY), str))
    return False


def _is_contract_400_body(body) -> bool:
    text = _body_text(body).lower()
    return any(marker in text for marker in _CONTRACT_MARKERS)


def _status_code(exc: BaseException) -> int | None:
    from polymerhus.app.llm.provider_failure import status_code

    return status_code(exc)


def _wire_model_id(provider: str | None, model: str | None) -> str | None:
    """The provider-native wire model id a configured `(provider, model)` reaches
    the upstream as - the stripped bare id for the zen family, verbatim otherwise
    (the SAME mapping `build_chat_model` and the gateway use). None when either
    leg is unknown. It is the value the lane echoes back in its transient 400."""
    if not provider or not model:
        return None
    try:
        from polymerhus.app.llm.sync_mapping import native_litellm_model

        return native_litellm_model(provider, model)
    except Exception:  # noqa: BLE001 - an unresolvable id never branches
        return None


def _is_transient_lane_400(exc: BaseException, *, provider: str | None,
                           model: str | None) -> bool:
    """Whether a 400 carries the EXACT opencode-go deepseek degraded-window
    signature - the full conjunction the D-1 ruling demands:

    - the lane is `opencode-go` (`provider`), not merely an echoing model id;
    - the configured model's wire id is a known deepseek lane id;
    - the parsed body is an object whose ONLY key is `model`, a string whose
      value EQUALS that wire id (the stripped id the upstream echoes).

    An empty body, a foreign value, a provider-prefixed mismatch, or any extra
    key (`error`/`message`/...) is NOT this signature: such a 400 stays
    contract/fatal and never arms the fallback."""
    if provider != _TRANSIENT_LANE_PROVIDER:
        return False
    wire = _wire_model_id(provider, model)
    if wire is None or wire not in _DEEPSEEK_WIRE_IDS:
        return False
    body = _error_body(exc)
    if not isinstance(body, dict) or set(body.keys()) != {_MODEL_ECHO_KEY}:
        return False
    value = body.get(_MODEL_ECHO_KEY)
    return isinstance(value, str) and value == wire


def body_shape(exc: BaseException) -> str:
    """The observable body shape of a raise, for the structured counter:
    `empty` / `model` (the bare-400 surfaces), `contract`, `other` (a 400 with an
    unrecognised body), or `n/a` (not a 400). Purely descriptive: it names what a
    400 body looks like, not whether it is the D-1 transient signature."""
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


def classify_error(exc: BaseException, *, provider: str | None = None,
                   model: str | None = None) -> TransientKind:
    """Classify a turn raise for the retry policy.

    - `transient`: the existing transport/timeout/5xx/429 provider-failure class,
      PLUS the EXACT opencode-go deepseek single-model-echo 400 (operator ruling
      D-1): HTTP 400 whose parsed body is `{"model": <wire-id>}` for a known
      deepseek lane id, raised for the opencode-go lane (`provider`).
    - `contract`: a 400 with a recognisable, actionable contract body.
    - `fatal`: anything else - including an EMPTY 400, a foreign/unrecognised
      model echo, and any multi-key envelope (fail-open: never retried).

    `provider` and `model` are the lane identity the caller threads from its own
    routing (resolved role, or the `<provider>:<model>` call label). When they
    are unknown the lane leg cannot match, so a model id alone never branches,
    and the empty 400 can never be mistaken for the signature.
    """
    from polymerhus.app.llm.provider_failure import is_provider_unavailable

    if is_provider_unavailable(exc):
        return "transient"
    if _status_code(exc) == 400:
        if _is_transient_lane_400(exc, provider=provider, model=model):
            return "transient"
        if _is_contract_400_body(_error_body(exc)):
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
