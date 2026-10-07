"""Typed classification of LLM-provider failures (#329).

A provider failure - a 429 throttle or quota exhaustion, a 5xx, a timeout, or a
transport error - is an INFRASTRUCTURE condition, never a domain result. This
module is the ONE classifier: it names such a failure distinctly from a target
infeasibility, so the app layer can back off and pause a run instead of failing
it outright, and the test-executor pod can refuse to write a fabricated domain
verdict.

The classifier is shared, not duplicated. `app/llm/actor.py::_is_retryable`
delegates here, so the actor retry budget and the failure classification can
never drift; the pod, the pod triager, and the hunting runtime consume the same
`is_provider_unavailable` / `as_provider_error` pair.

Import discipline (CODING_STANDARD section 6): the module top imports stdlib
only; the provider SDKs (`httpx`, `openai`) are lazy-imported inside the
classifiers so this module is I/O- and env-var-free at import.
"""
from __future__ import annotations

import logging
from email.utils import parsedate_to_datetime

logger = logging.getLogger(__name__)


class ProviderUnavailableError(RuntimeError):
    """A provider failure surfaced as a typed, retryable infrastructure error.

    It carries the classification the app layer needs to back off and pause:
    the HTTP status class, the provider/model when known, and the provider's
    `Retry-After` hint when the upstream supplied one. It is deliberately NOT a
    domain verdict - a provider failure never becomes a `PodExport`
    `terminal_reason` (#329, #331)."""

    retryable = True

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after_s: float | None = None,
        provider: str | None = None,
        model: str | None = None,
        quota_exhausted: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_s = retry_after_s
        self.provider = provider
        self.model = model
        self.quota_exhausted = quota_exhausted

    def interrupt_reason(self) -> str:
        """A one-line, operator-readable cause carrying the classification the
        resume policy needs: the HTTP status class and whether the failure was a
        period-quota exhaustion (terminal) vs a transient throttle (resumable).
        Recorded on an `interrupted` run so the cause survives past the process
        and the eval can tell a 429 from consumed credits (#331)."""
        parts: list[str] = []
        if self.status_code is not None:
            parts.append(f"status={self.status_code}")
        if self.quota_exhausted:
            parts.append("quota_exhausted=true")
        if self.retry_after_s is not None:
            parts.append(f"retry_after_s={self.retry_after_s:g}")
        detail = ", ".join(parts) if parts else "no status"
        return f"provider unavailable ({detail})"


# Message markers observed live from the opencode-go 429 / LiteLLM gateway
# (`Go usage limit exceeded`, `Rate limit ... exceeded`, `x-ratelimit-limit`).
# They are a LAST-RESORT fallback, and they only apply to a raise from the
# PROVIDER ecosystem (see `_from_provider_ecosystem`): a bare application
# RuntimeError that merely mentions "429" or "quota" must never be reclassified
# as a provider failure. A status code on the exception is always preferred.
_THROTTLE_MARKERS = (
    "429",
    "too many requests",
    "rate limit",
    "rate_limit",
    "go usage limit",
    "usage limit exceeded",
    "quota",
)

# Type provenance markers for the last-resort message scan. A wrapper from the
# provider ecosystem (openai / litellm / httpx / a `<Something>RateLimit` or
# `<Something>UsageLimit` class) is eligible; a plain application error is not.
_PROVIDER_TYPE_MARKERS = (
    "ratelimit", "rate_limit", "apierror", "apistatus", "apiconnection",
    "apitimeout", "litellm", "openai", "anthropic", "httpcore",
    "usagelimit", "usage_limit", "provider",
)


def _from_provider_ecosystem(exc: BaseException) -> bool:
    """Whether a raise's TYPE names a provider-ecosystem error concept (its
    class, any base class, or the module). Gates the last-resort message scan so
    a domain error that happens to echo "429" / "quota" is never reclassified."""
    if getattr(exc, "llm_provider", None) or getattr(exc, "provider", None):
        return True
    for klass in type(exc).__mro__:
        name = f"{klass.__module__}.{klass.__name__}".lower()
        if any(marker in name for marker in _PROVIDER_TYPE_MARKERS):
            return True
    return False


def _status_code(exc: BaseException) -> int | None:
    """The HTTP status of a raising provider call, best effort. Reads the
    exception's own `status_code` (the openai SDK sets it) or its `response`
    attribute (`httpx.Response`)."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def retry_after_seconds(exc: BaseException) -> float | None:
    """The provider's `Retry-After` hint in seconds, when present and parseable.
    Accepts both the numeric delta-seconds form and an HTTP-date. Fail-open:
    anything unreadable returns None."""
    try:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers is None:
            return None
        raw = headers.get("retry-after")
        if raw is None:
            return None
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            pass
        parsed = parsedate_to_datetime(str(raw))
        if parsed is None:
            return None
        import datetime as _dt

        now = _dt.datetime.now(tz=parsed.tzinfo) if parsed.tzinfo else _dt.datetime.now()
        return max(0.0, (parsed - now).total_seconds())
    except Exception:  # noqa: BLE001 - a hint is never load-bearing
        return None


def _is_quota_exhausted(exc: BaseException) -> bool:
    """Whether the failure reads as a QUOTA/period-limit exhaustion (`Go usage
    limit exceeded`) rather than a transient per-minute throttle. Both are
    provider failures; the distinction is provenance for the operator and a
    future terminal-vs-resumable policy (#331)."""
    text = str(exc).lower()
    return "usage limit" in text or "quota" in text


def is_provider_unavailable(exc: BaseException) -> bool:
    """Classify a raise as a provider/LLM failure (transport/timeout/5xx/429/
    quota). This is the shared successor of the actor's private `_is_retryable`
    (#186), extended with duck-typed status and a last-resort message scan so a
    provider failure is never mistaken for a domain error.

    A raise matching none of the known classes is NON-provider: a genuine
    application error must not be retried as if the provider were down."""
    if isinstance(exc, ProviderUnavailableError):
        return True
    if isinstance(exc, (TimeoutError,)):
        return True

    import asyncio

    if isinstance(exc, asyncio.TimeoutError):  # builtin alias on 3.11+
        return True

    try:
        import httpx  # noqa: PLC0415

        if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
            return True
    except Exception:  # noqa: BLE001 - httpx unavailable: fall through
        pass

    try:
        import openai  # noqa: PLC0415

        if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError,
                            openai.RateLimitError)):
            return True
        if isinstance(exc, openai.APIStatusError):
            status = _status_code(exc)
            if status is not None and (status == 429 or status >= 500):
                return True
    except Exception:  # noqa: BLE001 - openai unavailable: fall through
        pass

    # Duck-typed status: any provider SDK error carrying 429/5xx, even one that
    # does not subclass the openai hierarchy (LiteLLM wrappers, httpx direct).
    status = _status_code(exc)
    if status == 429 or (status is not None and status >= 500):
        return True

    # Last resort: a wrapper with no readable status but the live throttle text.
    # Gated on the provider ecosystem so a domain error echoing "429"/"quota"
    # is never reclassified.
    if _from_provider_ecosystem(exc):
        text = str(exc).lower()
        return any(marker in text for marker in _THROTTLE_MARKERS)
    return False


def as_provider_error(
    exc: BaseException,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> ProviderUnavailableError | None:
    """Return the typed `ProviderUnavailableError` for a provider failure, or
    None when `exc` is not one. The caller chains the original with
    `raise failure from exc` so the provider traceback is preserved."""
    if not is_provider_unavailable(exc):
        return None
    return ProviderUnavailableError(
        f"provider unavailable: {exc}",
        status_code=_status_code(exc),
        retry_after_s=retry_after_seconds(exc),
        provider=provider,
        model=model,
        quota_exhausted=_is_quota_exhausted(exc),
    )
