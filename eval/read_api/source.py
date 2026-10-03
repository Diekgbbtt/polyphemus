"""The `/snapshot` data-source seam (#278).

`SnapshotSource` is the only thing the read API depends on: it returns the eval
snapshot and its own health. `ArtifactStoreSnapshotSource` adapts today's
materialized artifact store (via `projection.build_snapshot`), and
`filesystem_source()` is the default factory. The environment is read *inside*
the factory, at request time - never at import - so the module stays import-safe
and a future source (REST, database, ...) can replace the filesystem without
touching the API or the frontend.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .projection import DEFAULT_DATASET_ID, DEFAULT_DATASET_NAME, build_snapshot
from .project_graph import HistoricalProjectGraphError, read_project_graph

ENV_STORE = "EVAL_ARTIFACT_STORE"
ENV_DATASET_ID = "EVAL_DATASET_ID"
ENV_DATASET_NAME = "EVAL_DATASET_NAME"


class SnapshotSourceUnavailable(RuntimeError):
    """The source cannot serve a snapshot (unconfigured or unreachable).

    The message is echoed in the API's 503 body, so it must stay free of host
    paths and other sensitive detail.
    """


@dataclass(frozen=True)
class SourceHealth:
    """The source's health, serialized as the `/health` body."""

    ok: bool
    detail: Mapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {"status": "ok" if self.ok else "degraded", **self.detail}


@runtime_checkable
class SnapshotSource(Protocol):
    """What the API needs from any data source - nothing more."""

    def snapshot(self) -> dict[str, Any]:
        """The eval snapshot (the `/snapshot` JSON body)."""

    def get_project_graph(
        self, target_id: str, target_run_id: str, trial_id: str
    ) -> dict[str, Any]:
        """The historical project graph for one fully-identified Trial."""

    def health(self) -> SourceHealth:
        """The source's own health."""


# A factory builds a fresh source per call, so configuration is read at request
# time and the source is trivially replaceable in tests.
SourceFactory = Callable[[], SnapshotSource]


@dataclass(frozen=True)
class ArtifactStoreSnapshotSource:
    """The filesystem adapter: the materialized store behind `build_snapshot`."""

    store: str | Path | None
    dataset_id: str = DEFAULT_DATASET_ID
    dataset_name: str = DEFAULT_DATASET_NAME

    def snapshot(self) -> dict[str, Any]:
        if not self.store:
            raise SnapshotSourceUnavailable(f"{ENV_STORE} is not configured")
        return build_snapshot(
            self.store, dataset_id=self.dataset_id, dataset_name=self.dataset_name
        )

    def get_project_graph(
        self, target_id: str, target_run_id: str, trial_id: str
    ) -> dict[str, Any]:
        if not self.store:
            raise SnapshotSourceUnavailable(f"{ENV_STORE} is not configured")
        return read_project_graph(self.store, target_id, target_run_id, trial_id)

    def health(self) -> SourceHealth:
        configured = bool(self.store)
        readable = configured and Path(self.store).is_dir()
        return SourceHealth(
            ok=configured,
            detail={"store_configured": configured, "store_readable": readable},
        )


def filesystem_source() -> SnapshotSource:
    """The default factory: an artifact-store source from the current environment."""
    return ArtifactStoreSnapshotSource(
        store=os.environ.get(ENV_STORE),
        dataset_id=os.environ.get(ENV_DATASET_ID) or DEFAULT_DATASET_ID,
        dataset_name=os.environ.get(ENV_DATASET_NAME) or DEFAULT_DATASET_NAME,
    )
