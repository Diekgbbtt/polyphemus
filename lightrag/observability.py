"""Per-stage Langfuse observations for the LightRAG query pipeline (#207).

The ``query_lightrag`` inner stages (retrieval, generation, validation) are
instrumented as nested observations following the client-layer canon
(``docs/design/observability-recipe.md``): the ``langfuse`` SDK primitives
(``get_client().start_as_current_observation`` / ``span.update`` /
``score_current_span``), never raw OpenTelemetry - raw OTel tracer scopes are
silently dropped by the SDK processor's export filter (verified live
2026-09-09), so they never reach Langfuse.

Fail-open (CODING_STANDARD section 12): if ``langfuse`` is absent or no
observation is active, every helper degrades to a no-op and never raises into
the pipeline. Importing this module performs no I/O and never imports
``langfuse`` at module scope (CODING_STANDARD section 6) - the import is
lazy, inside the factories, so a runtime without the package imports cleanly.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator, Protocol

logger = logging.getLogger(__name__)


def _client():
    """The process Langfuse client, resolved lazily; None when unavailable."""
    try:
        from langfuse import get_client

        return get_client()
    except Exception:  # noqa: BLE001 - tracing must never fail the pipeline
        return None


def _jsonable(value: Any) -> Any:
    """Coerce a value into JSON-serialisable observation payload.

    Observation ``input``/``output``/``metadata`` must be JSON-serialisable, so
    anything beyond primitives is normalised through ``default=str``.
    Fail-open: an un-serialisable value falls back to ``str(value)``.
    """
    try:
        import json

        return json.loads(json.dumps(value, default=str, ensure_ascii=False))
    except Exception:  # noqa: BLE001 - fail-open
        return str(value)


class _SinkProto(Protocol):
    def record(self, **attributes: Any) -> None: ...
    def metric(self, name: str, value: float) -> None: ...


class _SpanSink:
    """Attach output / metadata / scores to the current SDK observation.

    ``record(output=X, **rest)`` sets the observation ``output`` to ``X`` and
    merges ``rest`` into its ``metadata`` (accumulated across calls, so
    repeated ``record`` calls merge rather than clobber). ``metric`` scores
    the current observation. Every method is fail-open, so callers can record
    unconditionally.
    """

    def __init__(self, span: Any) -> None:
        self._span = span
        self._metadata: dict[str, Any] = {}

    def record(self, **attributes: Any) -> None:
        if self._span is None:
            return
        try:
            attributes = _jsonable(attributes)
            if "output" in attributes:
                self._span.update(output=attributes.pop("output"))
            if attributes:
                self._metadata.update(attributes)
                self._span.update(metadata=dict(self._metadata))
        except Exception:  # noqa: BLE001
            logger.debug("span record failed for %r", attributes, exc_info=True)

    def metric(self, name: str, value: float) -> None:
        if self._span is None:
            return
        try:
            client = _client()
            if client is not None:
                client.score_current_span(name=name, value=float(value))
        except Exception:  # noqa: BLE001
            logger.debug("span metric failed for %r", name, exc_info=True)


class _NullSink:
    """The no-op sink used when langfuse is unavailable."""

    def record(self, **attributes: Any) -> None:
        return None

    def metric(self, name: str, value: float) -> None:
        return None


@contextmanager
def stage_span(name: str, *, input: Any = None) -> Iterator[_SinkProto]:
    """Open one child observation for a pipeline stage, fail-open.

    ``input`` is attached as the observation ``input`` when provided. Yields a
    sink on which callers attach the stage's structured output (``record``) and
    numeric metrics (``metric``). Degrades to a null sink (never raises) when
    tracing is unavailable or misconfigured.
    """
    client = _client()
    if client is None:
        yield _NullSink()
        return
    try:
        with client.start_as_current_observation(
            name=name, as_type="span",
            input=_jsonable(input) if input is not None else None,
        ) as span:
            yield _SpanSink(span)
    except Exception:  # noqa: BLE001 - tracing must never crash the pipeline
        logger.debug("stage_span %r unavailable; running untraced", name, exc_info=True)
        yield _NullSink()


@contextmanager
def kb_observation_span(*, query: str, scenario_id: str = "") -> Iterator[_SinkProto]:
    """Open the author-lane ``kb_observation`` observation (#207 defect 1, point D).

    The hunter's ``kb_query`` has no D6 log, so its KB reads land as
    observation I/O (grey pt 8): the query and scenario id ride the
    observation ``input``, and - via the yielded sink - the returned entity
    names and provenance references ride its ``metadata``. Fail-open like
    ``stage_span``.
    """
    client = _client()
    if client is None:
        yield _NullSink()
        return
    try:
        with client.start_as_current_observation(
            name="kb_observation", as_type="span",
            input={"query": query, "scenario_id": scenario_id},
        ) as span:
            yield _SpanSink(span)
    except Exception:  # noqa: BLE001 - tracing must never crash the pipeline
        logger.debug("kb_observation_span unavailable; running untraced", exc_info=True)
        yield _NullSink()


def registry_metadata(registry: Any) -> dict[str, dict[str, str]]:
    """Persist the ``ReferenceRegistryV1`` mapping for post-hoc resolution.

    Returns ``{index: {"reference_id": ..., "file_path": ...}}`` for the
    ordered returned references (1-based), so a cited ``[n]`` provenance index
    is checkable against a persisted artifact (grey pt 7: observation metadata
    on the retrieval observation). Pure and deterministic.
    """
    return {
        str(index): {
            "reference_id": reference.reference_id,
            "file_path": reference.file_path,
        }
        for index, reference in enumerate(registry.references, start=1)
    }
