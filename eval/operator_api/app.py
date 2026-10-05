"""The operator-only ground-truth API: a separate, GET-only FastAPI.

This service exists to keep the benchmark reference off the discovery agent's
network. It is not part of `read_api`, it is published only on the server's
loopback, and it allows exactly one configured local dashboard origin in CORS.
CORS is a convenience for the browser, not the boundary: the boundary is the
separate Docker network plus the loopback publish (see the plan).

Like the read API, the app holds no paths or projection logic. A source factory
runs per request, so configuration is read at request time and module import
performs no filesystem or network I/O.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .ground_truth import GroundTruthError, GroundTruthSource

BENCHMARK_ROOT_ENV = "EVAL_OPERATOR_BENCHMARK_ROOT"
SETUP_ROOT_ENV = "EVAL_OPERATOR_SETUP_ROOT"
SETUP_FILES_ENV = "EVAL_OPERATOR_SETUP_FILES"
FRONTEND_ORIGIN_ENV = "EVAL_OPERATOR_FRONTEND_ORIGIN"

# The in-container defaults the Compose overlay sets explicitly.
DEFAULT_BENCHMARK_ROOT = "/srv/webexploitbench"
DEFAULT_SETUP_ROOT = "/srv/eval/setups"
DEFAULT_SETUP_FILES = "first.yaml,webexploitbench-chain.yaml"
DEFAULT_FRONTEND_ORIGIN = "http://localhost:15173"

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

SourceFactory = Callable[[], GroundTruthSource]


def _setup_files(raw: str) -> tuple[str, ...]:
    """Split the comma-separated basenames, dropping empty entries."""
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def filesystem_source() -> GroundTruthSource:
    """The configured source, read from the environment on every call."""
    return GroundTruthSource(
        benchmark_root=Path(
            os.environ.get(BENCHMARK_ROOT_ENV, DEFAULT_BENCHMARK_ROOT)
        ),
        setup_root=Path(os.environ.get(SETUP_ROOT_ENV, DEFAULT_SETUP_ROOT)),
        setup_files=_setup_files(os.environ.get(SETUP_FILES_ENV, DEFAULT_SETUP_FILES)),
    )


def _validated_origin(origin: str | None) -> str:
    """The one loopback http(s) origin the browser may call from.

    A wildcard, a remote host, credentials, or a path/query/fragment is a
    configuration error and fails closed at startup rather than being smoothed
    over into a permissive CORS policy.
    """
    if not isinstance(origin, str) or not origin:
        raise ValueError("operator frontend origin must be a non-empty string")
    parts = urlsplit(origin)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("operator frontend origin must be an http(s) origin")
    if parts.hostname.lower() not in LOOPBACK_HOSTS:
        raise ValueError("operator frontend origin must be a loopback origin")
    if parts.username or parts.password:
        raise ValueError("operator frontend origin must not carry credentials")
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        raise ValueError("operator frontend origin must carry no path, query or fragment")
    return f"{parts.scheme}://{parts.netloc}"


def create_app(
    source_factory: SourceFactory | None = None, *, frontend_origin: str | None = None
) -> FastAPI:
    """Build the operator app over `source_factory` and one allowed origin."""
    factory: SourceFactory = source_factory or filesystem_source
    origin = _validated_origin(
        frontend_origin
        if frontend_origin is not None
        else os.environ.get(FRONTEND_ORIGIN_ENV, DEFAULT_FRONTEND_ORIGIN)
    )

    app = FastAPI(
        title="Polyphemus operator ground truth API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin],
        allow_methods=["GET"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )

    @app.get("/health")
    def health() -> dict:
        return factory().health()

    @app.get("/ground-truth/targets/{target_id}")
    def ground_truth(target_id: str) -> dict:
        try:
            return factory().read(target_id)
        except GroundTruthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc

    return app


app = create_app()
