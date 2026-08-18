"""TDD for the Langfuse export retry/backoff wrapper.

Context: langfuse==4.13.0 exports spans via an OTel `BatchSpanProcessor` +
`OTLPSpanExporter`. That exporter's own retry loop only retries
`ConnectionError` or a retryable HTTP status - a plain socket *read timeout*
(`requests.exceptions.ReadTimeout`, what we see against cloud.langfuse.com)
is NOT retried: `export()` returns `SpanExportResult.FAILURE` after exactly
one attempt, and `BatchSpanProcessor` never retries a failed batch itself -
the batch is dropped for good. `RetryingSpanExporter` adds the missing outer
retry so a timed-out batch gets a bounded number of extra attempts
(at-least-once delivery; duplicates on retry are acceptable).

These tests exercise the wrapper against a FAKE exporter only - no network.
"""
from __future__ import annotations

from opentelemetry.sdk.trace.export import SpanExportResult

from polymerhus.app.observability.langfuse_tracing import (
    RetryingSpanExporter,
    _build_wrapped_span_exporter,
)


class _FakeExporter:
    """Fails N times (via configurable outcomes) then succeeds, or always fails."""

    def __init__(self, outcomes):
        # outcomes: list of either SpanExportResult values or Exception instances,
        # consumed in order; once exhausted, repeats the last entry.
        self._outcomes = list(outcomes)
        self.calls = 0
        self.shutdown_called = False
        self.force_flush_called_with = None

    def export(self, spans):
        self.calls += 1
        idx = min(self.calls - 1, len(self._outcomes) - 1)
        outcome = self._outcomes[idx]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def shutdown(self):
        self.shutdown_called = True

    def force_flush(self, timeout_millis=30000):
        self.force_flush_called_with = timeout_millis
        return True


class _RecordingSleep:
    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


def test_retries_until_success_and_delivers():
    fake = _FakeExporter(
        [SpanExportResult.FAILURE, SpanExportResult.FAILURE, SpanExportResult.SUCCESS]
    )
    sleep = _RecordingSleep()
    exporter = RetryingSpanExporter(
        fake, max_retries=5, backoff_base_s=1.0, sleep=sleep
    )

    result = exporter.export(["span-1"])

    assert result == SpanExportResult.SUCCESS
    assert fake.calls == 3
    # two retries happened -> two backoff sleeps, exponential from base 1.0
    assert sleep.calls == [1.0, 2.0]


def test_exception_from_inner_exporter_is_treated_as_a_failed_attempt_and_retried():
    fake = _FakeExporter([TimeoutError("read timed out"), SpanExportResult.SUCCESS])
    sleep = _RecordingSleep()
    exporter = RetryingSpanExporter(
        fake, max_retries=3, backoff_base_s=0.5, sleep=sleep
    )

    result = exporter.export(["span-1"])

    assert result == SpanExportResult.SUCCESS
    assert fake.calls == 2
    assert sleep.calls == [0.5]


def test_fail_open_when_exporter_always_fails():
    fake = _FakeExporter([SpanExportResult.FAILURE])
    sleep = _RecordingSleep()
    exporter = RetryingSpanExporter(
        fake, max_retries=2, backoff_base_s=0.1, sleep=sleep
    )

    # Must never raise - fail-open degrades to a dropped batch, same as today.
    result = exporter.export(["span-1"])

    assert result == SpanExportResult.FAILURE
    # first attempt + 2 retries = 3 calls total
    assert fake.calls == 3
    assert sleep.calls == [0.1, 0.2]


def test_fail_open_when_exporter_always_raises():
    fake = _FakeExporter([ConnectionError("boom")])
    exporter = RetryingSpanExporter(
        fake, max_retries=1, backoff_base_s=0.0, sleep=lambda _s: None
    )

    result = exporter.export(["span-1"])

    assert result == SpanExportResult.FAILURE
    assert fake.calls == 2


def test_zero_retries_behaves_like_the_unwrapped_exporter():
    fake = _FakeExporter([SpanExportResult.FAILURE])
    exporter = RetryingSpanExporter(fake, max_retries=0, backoff_base_s=1.0, sleep=lambda _s: None)

    result = exporter.export(["span-1"])

    assert result == SpanExportResult.FAILURE
    assert fake.calls == 1


def test_a_broken_sleep_callable_does_not_abort_the_retry_loop():
    def bad_sleep(_seconds):
        raise RuntimeError("scheduler unavailable")

    fake = _FakeExporter([SpanExportResult.FAILURE, SpanExportResult.SUCCESS])
    exporter = RetryingSpanExporter(fake, max_retries=1, backoff_base_s=0.0, sleep=bad_sleep)

    result = exporter.export(["span-1"])

    assert result == SpanExportResult.SUCCESS
    assert fake.calls == 2


def test_shutdown_and_force_flush_delegate_to_the_inner_exporter():
    fake = _FakeExporter([SpanExportResult.SUCCESS])
    exporter = RetryingSpanExporter(fake, max_retries=0, backoff_base_s=0.0, sleep=lambda _s: None)

    exporter.shutdown()
    assert fake.shutdown_called is True

    ok = exporter.force_flush(timeout_millis=1234)
    assert ok is True
    assert fake.force_flush_called_with == 1234


def test_force_flush_fail_open_when_inner_exporter_raises():
    class _RaisingFlush(_FakeExporter):
        def force_flush(self, timeout_millis=30000):
            raise RuntimeError("boom")

    fake = _RaisingFlush([SpanExportResult.SUCCESS])
    exporter = RetryingSpanExporter(fake, max_retries=0, backoff_base_s=0.0, sleep=lambda _s: None)

    assert exporter.force_flush() is False


def test_build_wrapped_span_exporter_wires_endpoint_and_retry_config_from_env(monkeypatch):
    # Fake, non-functional test credentials only - never a real key, and this
    # never calls .export()/auth_check() so no network I/O happens.
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test-only")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-only")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("LANGFUSE_EXPORT_MAX_RETRIES", "7")
    monkeypatch.setenv("LANGFUSE_EXPORT_RETRY_BACKOFF_S", "2.5")

    exporter = _build_wrapped_span_exporter(timeout_s=42.0)

    assert isinstance(exporter, RetryingSpanExporter)
    assert exporter._max_retries == 7
    assert exporter._backoff_base_s == 2.5
    inner = exporter._exporter
    assert inner._endpoint == "https://example.invalid/api/public/otel/v1/traces"
    assert inner._timeout == 42.0
    assert inner._headers["x-langfuse-public-key"] == "pk-test-only"
    assert inner._headers["Authorization"].startswith("Basic ")


def test_build_wrapped_span_exporter_uses_defaults_when_env_unset(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test-only")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test-only")
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("LANGFUSE_EXPORT_MAX_RETRIES", raising=False)
    monkeypatch.delenv("LANGFUSE_EXPORT_RETRY_BACKOFF_S", raising=False)

    exporter = _build_wrapped_span_exporter(timeout_s=30.0)

    assert exporter._max_retries == 3
    assert exporter._backoff_base_s == 1.0
    assert exporter._exporter._endpoint == (
        "https://cloud.langfuse.com/api/public/otel/v1/traces"
    )


def test_shutdown_fail_open_when_inner_exporter_raises():
    class _RaisingShutdown(_FakeExporter):
        def shutdown(self):
            raise RuntimeError("boom")

    fake = _RaisingShutdown([SpanExportResult.SUCCESS])
    exporter = RetryingSpanExporter(fake, max_retries=0, backoff_base_s=0.0, sleep=lambda _s: None)

    # Must not raise.
    exporter.shutdown()
