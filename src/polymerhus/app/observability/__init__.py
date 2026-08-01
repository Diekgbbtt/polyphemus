"""Observability wiring for the recon agent (lightweight, opt-in tracing).

Currently exposes only Langfuse callback plumbing. Kept as a thin package so
the rest of the runtime imports one stable name (`get_langfuse_callbacks`)
regardless of the tracing backend.
"""
from polymerhus.app.observability.analyser_tracing import (
    analyser_span,
    flush_analyser_traces,
    trace_reasoning,
)
from polymerhus.app.observability.langfuse_tracing import (
    disabled_reason,
    get_langfuse_callbacks,
)

__all__ = [
    "get_langfuse_callbacks",
    "disabled_reason",
    "analyser_span",
    "trace_reasoning",
    "flush_analyser_traces",
]
