from __future__ import annotations

from pathlib import Path
from typing import Iterable

from agent.app.config import config


def _resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def is_approved_source_path(path: str | Path, approved_sources: Iterable[str | Path] | None = None) -> bool:
    resolved_path = _resolve(path)
    configured_sources = (
        approved_sources if approved_sources is not None else config.LIGHTRAG_APPROVED_SOURCES
    )
    roots = [_resolve(root) for root in configured_sources]
    return any(resolved_path == root or _is_relative_to(resolved_path, root) for root in roots)


def _call_ingest_client(lightrag_client, source_path: Path):
    source_arg = str(source_path)
    if hasattr(lightrag_client, "ingest_source"):
        return lightrag_client.ingest_source(source_arg)
    if hasattr(lightrag_client, "ingest"):
        return lightrag_client.ingest(source_arg)
    if callable(lightrag_client):
        return lightrag_client(source_arg)
    raise TypeError("lightrag_client must be callable or expose ingest()/ingest_source()")


def ingest_approved_sources(
    source_paths: Iterable[str | Path] | None = None,
    *,
    lightrag_client,
    approved_sources: Iterable[str | Path] | None = None,
) -> list[dict]:
    """Ingest only local paths covered by the approved offline-source allowlist."""
    selected_sources = list(source_paths or config.LIGHTRAG_APPROVED_SOURCES)
    if not selected_sources:
        raise ValueError("at least one LightRAG source path is required")

    results = []
    for source in selected_sources:
        source_path = _resolve(source)
        if not is_approved_source_path(source_path, approved_sources):
            raise ValueError(f"LightRAG source is not approved: {source}")
        if not source_path.exists():
            raise FileNotFoundError(f"LightRAG source does not exist: {source}")
        result = _call_ingest_client(lightrag_client, source_path)
        results.append({"source_path": str(source_path), "result": result})
    return results
