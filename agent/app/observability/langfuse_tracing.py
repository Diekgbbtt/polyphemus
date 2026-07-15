"""Lightweight, env-driven Langfuse tracing for the recon LangGraph runtime.

Design goals (deliberately minimal - see the Stream A observability brief):

- **Tracing only.** No prompt management, no datasets, no evals. We wire the
  standard LangChain `CallbackHandler` and let the LangGraph structure give us
  the trace tree for free: passing a single handler into `run_pipeline` /
  `graph.invoke` / `llm.invoke(config={"callbacks": [...]})` captures, per run,
  (a) every tool call + its response (the Kali MCP `execute_command` calls in
  pods and the `steel_*` tools in the crawl ReAct loop), (b) each role LLM's
  inputs/outputs (configurator / triager / job_orchestrator / crawler
  reasoning dumps), and (c) the phase DAG / job fan-out as the nested-span
  overview of the plan.

- **Env-driven + fail-open.** Tracing is enabled only when all three of
  `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST` are present
  in the environment. When any is missing - or the `langfuse` package is not
  installed, or handler construction raises for any reason - this module is a
  silent no-op: `get_langfuse_callbacks()` returns `[]` and NOTHING hard-fails.
  Passing `[]` as `config={"callbacks": []}` is inert in LangChain, so callers
  can wire the return value unconditionally.

The only public surface is `get_langfuse_callbacks() -> list`. Callers do:

    from agent.app.observability import get_langfuse_callbacks
    graph.invoke(state, config={"callbacks": get_langfuse_callbacks()})

Import safety: importing this module performs no network I/O and never
imports `langfuse` at module scope - the import is lazy, inside the factory,
so a runtime without the package (e.g. the offline test venv) imports this
module cleanly and simply gets an empty callback list.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# The three env vars that gate tracing. All must be present and non-empty.
_REQUIRED_ENV = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST")

# --- Export throttling / at-least-once delivery knobs ---------------------
#
# ROOT CAUSE (langfuse==4.13.0, verified against the installed SDK source):
#
# 1. `Langfuse.__init__` defaults `timeout = int(os.environ.get("LANGFUSE_TIMEOUT", 5))`
#    (langfuse/_client/client.py) - a 5s network timeout unless overridden.
# 2. That timeout flows into `LangfuseSpanProcessor` (langfuse/_client/span_processor.py),
#    which extends OTel's `BatchSpanProcessor` and builds an
#    `opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter`
#    with that same timeout.
# 3. `OTLPSpanExporter.export()` DOES have an internal retry loop (up to 6
#    attempts, exponential backoff) - but only for `requests.exceptions.ConnectionError`
#    or an HTTP status considered retryable (`_is_retryable`). A plain socket
#    *read timeout* (`requests.exceptions.ReadTimeout`, exactly what the
#    "Read timed out (read timeout=5s)" log line is) is NOT a `ConnectionError`,
#    so `retryable=False` and the exporter returns `SpanExportResult.FAILURE`
#    after exactly ONE attempt - no retry.
# 4. OTel's `BatchSpanProcessor` never retries a batch itself once `export()`
#    returns FAILURE - the batch of spans is dropped for good.
#
# So: langfuse 4.13.0 drops-on-timeout by default, with zero retries, for the
# exact failure mode observed live. Fix: (a) raise the timeout via the SDK's
# own `LANGFUSE_TIMEOUT`-equivalent knob so timeouts are rarer, and (b) wrap
# the exporter in `RetryingSpanExporter` below to add the missing outer
# retry/backoff, giving at-least-once delivery (a retried batch may duplicate
# spans already partially ingested server-side - accepted/expected).
_EXPORT_TIMEOUT_ENV = "LANGFUSE_EXPORT_TIMEOUT"
_DEFAULT_EXPORT_TIMEOUT_S = 60.0

_EXPORT_MAX_RETRIES_ENV = "LANGFUSE_EXPORT_MAX_RETRIES"
_DEFAULT_EXPORT_MAX_RETRIES = 3

_EXPORT_RETRY_BACKOFF_ENV = "LANGFUSE_EXPORT_RETRY_BACKOFF_S"
_DEFAULT_EXPORT_RETRY_BACKOFF_S = 1.0

# --- Per-attribute payload cap (large-tool-output truncation) -------------
#
# Heavy phase-4 tools (katana, ffuf, steel_crawl) attach their full
# stdout/observation verbatim as a single span input/output attribute. A
# ~1136-asset katana `-jsonl` dump is hundreds of KB (up to low MB with rich
# lines); batched together these oversized spans exhaust the OTLP exporter's
# shared retry/timeout budget and the whole batch is dropped ("Failed to
# export span batch due to timeout, max retries or shutdown"). Light phases
# (whois, httpx, naabu, subdomain_takeover) emit small payloads and land fine.
#
# We truncate any per-attribute payload above a HIGH cap BEFORE it becomes a
# span attribute, via the Langfuse `mask` hook (applied synchronously to
# input/output/metadata of every SDK-created span, which is what the LangChain
# `CallbackHandler` produces). The cap is sized from measured data: a full
# 1136-asset katana run is ~180 KB of compact stdout and up to ~570 KB with
# rich real `-jsonl` lines. 256 KiB sits above a compact full-katana run (so
# normal payloads pass untouched, structure preserved) while truncating the
# genuinely huge, rich-output payloads that were exhausting the timeout - and
# is only ~5% of Langfuse's documented 5 MB request limit, leaving ample
# headroom for OTLP protobuf/gzip overhead and multiple spans per batch.
_MAX_ATTRIBUTE_BYTES_ENV = "LANGFUSE_MAX_ATTRIBUTE_BYTES"
_DEFAULT_MAX_ATTRIBUTE_BYTES = 256 * 1024

# LANGFUSE_FLUSH_INTERVAL / LANGFUSE_FLUSH_AT are native SDK knobs (read
# directly by `langfuse._client.span_processor.LangfuseSpanProcessor`) that
# throttle spans into fewer, larger batches. We do not rename them; operators
# can set them directly and the SDK picks them up unchanged.


class RetryingSpanExporter:
    """Wrap an OTel `SpanExporter` with bounded retry + exponential backoff.

    Adds the outer batch-retry that langfuse 4.13.0's `OTLPSpanExporter` +
    `BatchSpanProcessor` do not provide for read-timeout failures (see the
    root-cause note above) - giving at-least-once delivery instead of
    silent, permanent drops.

    Fail-open by construction: any exception raised by the wrapped exporter
    (or by the injected `sleep`) is caught and treated as a failed attempt;
    once retries are exhausted this returns `SpanExportResult.FAILURE` -
    exactly today's drop behavior - rather than raising and disrupting the
    background export thread.
    """

    def __init__(
        self,
        exporter: Any,
        *,
        max_retries: int = _DEFAULT_EXPORT_MAX_RETRIES,
        backoff_base_s: float = _DEFAULT_EXPORT_RETRY_BACKOFF_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._exporter = exporter
        self._max_retries = max(0, max_retries)
        self._backoff_base_s = max(0.0, backoff_base_s)
        self._sleep = sleep

    def export(self, spans):
        from opentelemetry.sdk.trace.export import SpanExportResult

        attempt = 0
        while True:
            try:
                result = self._exporter.export(spans)
            except Exception as error:  # noqa: BLE001 - any exporter failure is retryable here
                logger.debug(
                    "langfuse span export raised on attempt %d: %s", attempt + 1, error
                )
                result = SpanExportResult.FAILURE

            if result == SpanExportResult.SUCCESS:
                return result

            if attempt >= self._max_retries:
                logger.warning(
                    "langfuse span export failed after %d attempt(s); dropping "
                    "batch (span_count=%d, at-least-once retry budget exhausted)",
                    attempt + 1,
                    len(spans) if hasattr(spans, "__len__") else -1,
                )
                return SpanExportResult.FAILURE

            backoff = self._backoff_base_s * (2**attempt)
            logger.info(
                "langfuse span export failed (attempt %d/%d); retrying in %.2fs",
                attempt + 1,
                self._max_retries + 1,
                backoff,
            )
            try:
                self._sleep(backoff)
            except Exception:  # noqa: BLE001 - fail-open: a broken sleep must not abort the retry
                logger.debug("langfuse retry sleep raised; continuing", exc_info=True)

            attempt += 1

    def shutdown(self) -> None:
        try:
            self._exporter.shutdown()
        except Exception:  # noqa: BLE001 - fail-open
            logger.debug("langfuse exporter shutdown raised", exc_info=True)

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        try:
            return bool(self._exporter.force_flush(timeout_millis=timeout_millis))
        except Exception:  # noqa: BLE001 - fail-open
            logger.debug("langfuse exporter force_flush raised", exc_info=True)
            return False


def _serialize_for_size(data: Any) -> str:
    """Best-effort textual form used only to MEASURE and truncate a payload.

    Mirrors closely enough what Langfuse serialises to JSON later. Never
    raises: a non-JSON-serialisable object falls back to `str(data)`.
    """
    if isinstance(data, str):
        return data
    try:
        import json

        return json.dumps(data, default=str, ensure_ascii=False)
    except Exception:  # noqa: BLE001 - fail-open: measurement must never raise
        return str(data)


def _truncate_attribute(data: Any, *, cap_bytes: int) -> Any:
    """Return `data` unchanged when it fits, else a truncated, marked string.

    Small payloads (the light phases) pass through untouched with their
    structure preserved. A payload whose serialised UTF-8 size exceeds
    `cap_bytes` is replaced by its first `cap_bytes` bytes (truncated on a
    valid UTF-8 boundary) plus a `...[truncated N bytes]` marker naming exactly
    how many bytes were dropped, so the truncation is obvious in the Langfuse
    UI. Fail-open: any error returns the original data rather than raising.
    """
    try:
        serialized = _serialize_for_size(data)
        encoded = serialized.encode("utf-8")
        if len(encoded) <= cap_bytes:
            return data

        dropped = len(encoded) - cap_bytes
        # Decode back on a valid boundary; errors="ignore" drops a partial
        # trailing multi-byte sequence so the result is always valid UTF-8.
        head = encoded[:cap_bytes].decode("utf-8", errors="ignore")
        return f"{head}...[truncated {dropped} bytes]"
    except Exception:  # noqa: BLE001 - fail-open: masking must never break a run
        logger.debug("langfuse attribute truncation raised; leaving data as-is", exc_info=True)
        return data


def _make_truncating_mask(*, cap_bytes: int) -> Callable[..., Any]:
    """Build a Langfuse `mask` callable that caps oversized attributes.

    Langfuse invokes the mask synchronously as `mask(data=<value>, **kwargs)`
    for the input / output / metadata of every SDK-created span (which is what
    the LangChain `CallbackHandler` produces), before the value becomes a span
    attribute - so heavy tool payloads are bounded at the source, not dropped
    on export. Extra keyword args (e.g. `field=`) are accepted and ignored.
    """

    def mask(*, data: Any = None, **_kwargs: Any) -> Any:
        return _truncate_attribute(data, cap_bytes=cap_bytes)

    return mask


def _active_span_exporter(client: Any) -> Any:
    """Return the span exporter actually in effect on a built Langfuse client.

    The exporter lives on the process-wide resource manager singleton
    (`client._resources.span_exporter`), which is keyed by public key and
    created on FIRST construction for that key - so this is what lets us detect
    the singleton hazard where a pre-existing client's exporter, not ours, is
    the one that will actually export. Fail-open: returns None if the private
    accessor is unavailable.
    """
    try:
        return client._resources.span_exporter
    except Exception:  # noqa: BLE001 - private accessor may move across SDK versions
        return None


def _verify_configured_exporter_in_effect(client: Any, expected_exporter: Any) -> bool:
    """True iff the exporter in effect on `client` is exactly the one we built.

    Guards the resource-manager singleton hazard: if any other code built a
    Langfuse client for this public key first, our `span_exporter=` (and
    `mask=`) were silently discarded and a different exporter is live. Returns
    False (never raises) when it cannot confirm identity.
    """
    return _active_span_exporter(client) is expected_exporter


def _resolve_base_url() -> str:
    """Mirror `Langfuse.__init__`'s base_url resolution (client.py)."""
    return (
        os.environ.get("LANGFUSE_BASE_URL")
        or os.environ.get("LANGFUSE_HOST")
        or "https://cloud.langfuse.com"
    )


def _build_wrapped_span_exporter(*, timeout_s: float):
    """Build the same `OTLPSpanExporter` the SDK builds internally, wrapped
    in `RetryingSpanExporter` for throttled, at-least-once delivery.

    Passing a custom `span_exporter` to `Langfuse(...)` opts out of the SDK
    wiring `base_url`/headers/auth/timeout into it (documented on the
    `span_exporter` kwarg in langfuse/_client/client.py), so this mirrors
    `langfuse._client.span_processor.LangfuseSpanProcessor`'s default
    exporter construction (endpoint + Basic-auth headers) exactly.
    """
    import base64

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    public_key = os.environ["LANGFUSE_PUBLIC_KEY"]
    secret_key = os.environ["LANGFUSE_SECRET_KEY"]
    base_url = _resolve_base_url()
    traces_export_path = os.environ.get("LANGFUSE_OTEL_TRACES_EXPORT_PATH")
    endpoint = (
        f"{base_url}/{traces_export_path}"
        if traces_export_path
        else f"{base_url}/api/public/otel/v1/traces"
    )
    basic_auth_header = "Basic " + base64.b64encode(
        f"{public_key}:{secret_key}".encode("utf-8")
    ).decode("ascii")
    headers = {
        "Authorization": basic_auth_header,
        "x-langfuse-sdk-name": "python",
        "x-langfuse-public-key": public_key,
    }

    inner_exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers, timeout=timeout_s)

    max_retries = int(os.environ.get(_EXPORT_MAX_RETRIES_ENV, _DEFAULT_EXPORT_MAX_RETRIES))
    backoff_base_s = float(
        os.environ.get(_EXPORT_RETRY_BACKOFF_ENV, _DEFAULT_EXPORT_RETRY_BACKOFF_S)
    )
    return RetryingSpanExporter(
        inner_exporter, max_retries=max_retries, backoff_base_s=backoff_base_s
    )

# Cache the constructed handler(s) so we build the CallbackHandler once per
# process rather than on every graph/LLM invocation. `_INIT_DONE` distinguishes
# "not yet attempted" from "attempted and found unconfigured" (cached []).
_lock = threading.Lock()
_INIT_DONE = False
_CALLBACKS: list = []
# Why tracing is off, set by `_build_callbacks` so operators get a SPECIFIC
# reason (which env var is missing, or a package/init failure) instead of a
# generic "unset" message. None once tracing is successfully enabled.
_DISABLED_REASON: str | None = None


def _is_configured() -> bool:
    """True only when every gating env var is present and non-empty."""
    return all(os.environ.get(name) for name in _REQUIRED_ENV)


def _build_callbacks() -> list:
    """Construct the Langfuse LangChain `CallbackHandler`, fail-open.

    Returns a one-element `[handler]` on success, or `[]` if tracing is not
    configured or anything goes wrong (missing package, bad keys, unreachable
    host at construction). Never raises.
    """
    global _DISABLED_REASON
    if not _is_configured():
        missing = [n for n in _REQUIRED_ENV if not os.environ.get(n)]
        _DISABLED_REASON = f"missing/empty env: {', '.join(missing)}"
        logger.debug("langfuse tracing disabled: %s", _DISABLED_REASON)
        return []

    try:
        # Lazy import: the offline runtime does not ship `langfuse`, and we must
        # not turn a missing optional dependency into an import-time failure.
        from langfuse import Langfuse, get_client
        from langfuse.langchain import CallbackHandler

        # Build our own client with a throttled, retrying span exporter (see
        # the root-cause note above `RetryingSpanExporter`) so a Langfuse
        # cloud read-timeout is retried instead of silently dropping the
        # batch. This is best-effort: if building the custom exporter fails
        # for any reason, fall back to the SDK's own `get_client()` - today's
        # behavior (5s timeout, no outer retry) - rather than losing tracing
        # entirely.
        client = None
        span_exporter = None
        try:
            export_timeout_s = float(
                os.environ.get(_EXPORT_TIMEOUT_ENV, _DEFAULT_EXPORT_TIMEOUT_S)
            )
            cap_bytes = int(
                os.environ.get(_MAX_ATTRIBUTE_BYTES_ENV, _DEFAULT_MAX_ATTRIBUTE_BYTES)
            )
            span_exporter = _build_wrapped_span_exporter(timeout_s=export_timeout_s)
            # `mask` truncates oversized tool payloads BEFORE they become span
            # attributes, so heavy phase-4 spans no longer exhaust the export
            # timeout budget (see the per-attribute cap note above).
            client = Langfuse(
                timeout=int(export_timeout_s),
                span_exporter=span_exporter,
                mask=_make_truncating_mask(cap_bytes=cap_bytes),
            )
            # Verify our exporter is the one actually in effect. The Langfuse
            # resource manager is a process-wide singleton keyed by public key
            # and built on first construction: if any other code built a client
            # for this key first, our `span_exporter=`/`mask=` were silently
            # discarded. Log a specific warning so that hazard is diagnosable.
            if not _verify_configured_exporter_in_effect(client, span_exporter):
                logger.warning(
                    "langfuse configured span exporter is NOT in effect - a "
                    "pre-existing client for this public key won the singleton; "
                    "the retry/timeout wrapper and payload truncation may be "
                    "bypassed for exported spans"
                )
        except Exception:  # noqa: BLE001 - fail-open to the SDK default exporter
            logger.warning(
                "langfuse retrying-export wrapper could not be built; falling back "
                "to the SDK default exporter (no throttle/retry wrapper)",
                exc_info=True,
            )
            client = None

        # `get_client()` reads LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY /
        # LANGFUSE_HOST from the environment. auth_check() is best-effort - a
        # failed check only logs; it must not disable tracing (the host may be
        # briefly unreachable at boot while still coming up).
        if client is None:
            client = get_client()
        try:
            if not client.auth_check():
                logger.warning(
                    "langfuse auth_check failed; tracing handler still wired "
                    "(verify LANGFUSE_* keys/host)"
                )
        except Exception:  # noqa: BLE001 - auth_check is advisory only
            logger.debug("langfuse auth_check raised; continuing", exc_info=True)

        # Bind the handler explicitly to our public key so it resolves the same
        # instance we configured above, instead of relying on the SDK's
        # "single active instance" fallback in `get_client()`.
        handler = CallbackHandler(public_key=os.environ["LANGFUSE_PUBLIC_KEY"])
        _DISABLED_REASON = None
        logger.info(
            "langfuse tracing enabled (host=%s)", os.environ.get("LANGFUSE_HOST")
        )
        return [handler]
    except Exception:  # noqa: BLE001 - fail-open: tracing never breaks the run
        _DISABLED_REASON = "langfuse env set but handler init failed (package/keys/host)"
        logger.warning(
            "langfuse tracing could not be initialised; continuing without it",
            exc_info=True,
        )
        return []


def get_langfuse_callbacks() -> list:
    """Return the LangChain callbacks that enable Langfuse tracing.

    - Returns `[handler]` when Langfuse is configured (all three
      `LANGFUSE_*` env vars set) and the handler builds successfully.
    - Returns `[]` otherwise. `[]` is inert as `config={"callbacks": []}`, so
      callers wire it unconditionally into `run_pipeline` / `graph.invoke` /
      `llm.invoke`.

    The handler is built once and cached for the process. Never raises.
    """
    global _INIT_DONE, _CALLBACKS
    if _INIT_DONE:
        return _CALLBACKS
    with _lock:
        if not _INIT_DONE:
            _CALLBACKS = _build_callbacks()
            _INIT_DONE = True
    return _CALLBACKS


def disabled_reason() -> str | None:
    """Human-readable reason tracing is off, or None when it is enabled.

    Triggers the one-time (cached) build so the reason reflects the real
    outcome - which env var is missing, or a package/handler init failure -
    rather than a generic message. For operator diagnostics (e.g. the startup
    log), so a misconfiguration names itself instead of hiding.
    """
    get_langfuse_callbacks()
    return _DISABLED_REASON


def reset_cache() -> None:
    """Clear the cached handler so the next call re-reads the environment.

    Intended for tests that toggle `LANGFUSE_*` env vars; not part of the
    normal runtime path.
    """
    global _INIT_DONE, _CALLBACKS, _DISABLED_REASON
    with _lock:
        _INIT_DONE = False
        _CALLBACKS = []
        _DISABLED_REASON = None
