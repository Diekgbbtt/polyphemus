"""Per-stage OpenTelemetry spans for the LightRAG query pipeline (#207).

The ``query_lightrag`` inner stages (retrieval, generation, validation) are
instrumented with child spans via the ``opentelemetry.trace`` API. When the
Langfuse OTel span processor is wired (``app/observability/langfuse_tracing.py``
registers it on the global tracer provider), these spans ride the same OTLP
exporter and nest under the active trace as first-class observations.

Fail-open (CODING_STANDARD section 12): if ``opentelemetry`` is absent or no
span is active, every helper degrades to a no-op and never raises into the
pipeline. Importing this module performs no I/O and never imports
``opentelemetry`` at module scope (CODING_STANDARD section 6) - the import is
lazy, inside the factories, so a runtime without the package imports cleanly.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator, Protocol

logger = logging.getLogger(__name__)

_TRACER_NAME = "lightrag.query"


def _tracer():
    """The module tracer, resolved lazily; None when opentelemetry is absent."""
    try:
        from opentelemetry import trace

        return trace.get_tracer(_TRACER_NAME)
    except Exception:  # noqa: BLE001 - tracing must never fail the pipeline
        return None


def _serialize(value: Any) -> Any:
    """Coerce a value into an OTel attribute (str/int/float/bool or a JSON str).

    OTel span attributes must be primitives or sequences of primitives, so
    structured payloads (dicts, lists) are encoded to a JSON string. Fail-open:
    an un-serialisable value falls back to ``str(value)``.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        import json

        return json.dumps(value, default=str, ensure_ascii=False)
    except Exception:  # noqa: BLE001 - fail-open
        return str(value)


class _SinkProto(Protocol):
    def record(self, **attributes: Any) -> None: ...
    def metric(self, name: str, value: float) -> None: ...


class _SpanSink:
    """Attach attributes / numeric metrics to the current OTel span.

    Every method is a fail-open no-op when there is no span (``_span`` is None),
    so callers can record unconditionally.
    """

    def __init__(self, span: Any) -> None:
        self._span = span

    def record(self, **attributes: Any) -> None:
        if self._span is None:
            return
        try:
            for key, value in attributes.items():
                self._span.set_attribute(key, _serialize(value))
        except Exception:  # noqa: BLE001
            logger.debug("span record failed for %r", attributes, exc_info=True)

    def metric(self, name: str, value: float) -> None:
        if self._span is None:
            return
        try:
            self._span.set_attribute(f"metric.{name}", float(value))
        except Exception:  # noqa: BLE001
            logger.debug("span metric failed for %r", name, exc_info=True)


class _NullSink:
    """The no-op sink used when opentelemetry / the tracer is unavailable."""

    def record(self, **attributes: Any) -> None:
        return None

    def metric(self, name: str, value: float) -> None:
        return None


@contextmanager
def stage_span(name: str, *, input: Any = None) -> Iterator[_SinkProto]:
    """Open one child span for a pipeline stage, fail-open.

    ``input`` is attached as the ``input`` attribute when provided. Yields a
    sink on which callers attach the stage's structured output (``record``) and
    numeric metrics (``metric``). Degrades to a null sink (never raises) when
    tracing is unavailable or misconfigured.
    """
    tracer = _tracer()
    if tracer is None:
        yield _NullSink()
        return
    try:
        with tracer.start_as_current_span(
            name, attributes={"input": _serialize(input)} if input is not None else None
        ) as span:
            yield _SpanSink(span)
    except Exception:  # noqa: BLE001 - tracing must never crash the pipeline
        logger.debug("stage_span %r unavailable; running untraced", name, exc_info=True)
        yield _NullSink()


@contextmanager
def kb_observation_span(*, query: str, scenario_id: str = "") -> Iterator[_SinkProto]:
    """Open the author-lane ``kb_observation`` span (#207 defect 1, point D).

    The hunter's ``kb_query`` has no D6 log, so its KB reads land as span
    metadata (grey pt 8): the query, the scenario id, and - via the yielded
    sink - the returned entity names and provenance references. Fail-open like
    ``stage_span``.
    """
    tracer = _tracer()
    if tracer is None:
        yield _NullSink()
        return
    try:
        with tracer.start_as_current_span(
            "kb_observation",
            attributes={
                "query": _serialize(query),
                "scenario_id": _serialize(scenario_id),
            },
        ) as span:
            yield _SpanSink(span)
    except Exception:  # noqa: BLE001 - tracing must never crash the pipeline
        logger.debug("kb_observation_span unavailable; running untraced", exc_info=True)
        yield _NullSink()


def registry_metadata(registry: Any) -> dict[str, dict[str, str]]:
    """Persist the ``ReferenceRegistryV1`` mapping for post-hoc resolution.

    Returns ``{index: {"reference_id": ..., "file_path": ...}}`` for the
    ordered returned references (1-based), so a cited ``[n]`` provenance index
    is checkable against a persisted artifact (grey pt 7: span metadata on the
    retrieval span). Pure and deterministic.
    """
    return {
        str(index): {
            "reference_id": reference.reference_id,
            "file_path": reference.file_path,
        }
        for index, reference in enumerate(registry.references, start=1)
    }
