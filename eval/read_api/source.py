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

from .artifacts import (
    ArtifactDownload,
    ArtifactLookupError,
    get_artifact,
    list_artifacts,
    stream_artifact,
)
from .resolved import TrialContext, is_safe_identifier, resolve_trial_context
from .resolved_artifacts import (
    ResolvedInventory,
    content_download,
    detail_response,
    inventory_response,
    resolve_inventory,
)
from .resolved_graph import (
    DEFAULT_TIMEOUT_SECONDS,
    HttpProjectGraphClient,
    ProjectGraphClient,
    graph_response,
    resolve_graph,
    resolve_graph_timeout,
)
from orchestrator.files import FileStore
from orchestrator.project_artifacts import (
    ProjectArtifactError,
    collect_project_artifacts,
)
from .projection import (
    DEFAULT_DATASET_ID,
    DEFAULT_DATASET_NAME,
    assemble_snapshot,
    project_run_record,
    project_store_trials,
)
from .project_graph import HistoricalProjectGraphError, read_project_graph
from .run_records import RUN_RECORD_AMBIGUOUS, load_run_record_catalog
from .trial_spend import (
    SPEND_ROOT_UNCONFIGURED,
    TrialSpend,
    load_spend_records_from_roots,
    match_spend,
)

ENV_STORE = "EVAL_ARTIFACT_STORE"
ENV_DATASET_ID = "EVAL_DATASET_ID"
ENV_DATASET_NAME = "EVAL_DATASET_NAME"
ENV_PROJECT_DATA_ROOT = "EVAL_PROJECT_DATA_ROOT"
ENV_AGENT_BASE_URL = "EVAL_AGENT_BASE_URL"
ENV_INSTANCE_ID = "EVAL_INSTANCE_ID"
# The current-graph read timeout, in seconds; a bad value falls back to the safe
# default (see `resolved_graph.resolve_graph_timeout`).
ENV_GRAPH_TIMEOUT = "EVAL_GRAPH_TIMEOUT_SECONDS"
# The harness's runs root, holding each finished Trial's authoritative record
# (arbitrary filename). Read-only, and only for the recorded-spend block.
ENV_RUNS_ROOT = "EVAL_RUNS_ROOT"
# The optional legacy runs root, holding the historical Trials' records. Unset
# on a fresh install; when set, it is searched beside the primary root and a
# record present in both is ambiguous rather than arbitrarily chosen.
ENV_LEGACY_RUNS_ROOT = "EVAL_RUNS_LEGACY_ROOT"

MANIFEST_FILENAME = "run-manifest.yaml"
# Non-Trial siblings a store also contains: the materializer's scratch root, the
# rendered sync dir, and the raw live mirror. Never counted as materialized.
_SKIP_DIRNAMES = frozenset({"_staging", "_sync", "live"})
# The app provisions its shared fault catalogue at DATA_ROOT/hunting/fault-kb.yaml.
# That top-level directory is not a project, even though its name is a safe ID.
_NON_PROJECT_DATA_DIRNAMES = frozenset({"hunting"})


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

    def list_artifacts(
        self, target_id: str, target_run_id: str, trial_id: str
    ) -> dict[str, Any]:
        """The grouped artifact inventory for one fully-identified Trial."""

    def get_artifact(
        self, target_id: str, target_run_id: str, trial_id: str, artifact_id: str
    ) -> dict[str, Any]:
        """Metadata plus one safe representation for one inventory artifact id."""

    def stream_artifact(
        self, target_id: str, target_run_id: str, trial_id: str, artifact_id: str
    ) -> ArtifactDownload:
        """A bounded chunk iterator over one artifact's re-verified raw bytes."""

    def health(self) -> SourceHealth:
        """The source's own health."""

    def resolved_graph(
        self, target_id: str, target_run_id: str, trial_id: str
    ) -> dict[str, Any]:
        """The unified graph for one Trial: captured, else eligible current."""

    def list_resolved_artifacts(
        self, target_id: str, target_run_id: str, trial_id: str
    ) -> dict[str, Any]:
        """The unified artifact inventory for one Trial: captured, else raw."""

    def get_resolved_artifact(
        self, target_id: str, target_run_id: str, trial_id: str, artifact_id: str
    ) -> dict[str, Any]:
        """Metadata plus one safe preview for one resolved inventory artifact."""

    def stream_resolved_artifact(
        self,
        target_id: str,
        target_run_id: str,
        trial_id: str,
        artifact_id: str,
        expected_sha256: str,
    ) -> ArtifactDownload:
        """A bounded stream whose bytes must match `expected_sha256`."""


# A factory builds a fresh source per call, so configuration is read at request
# time and the source is trivially replaceable in tests.
SourceFactory = Callable[[], SnapshotSource]


@dataclass(frozen=True)
class ArtifactStoreSnapshotSource:
    """The filesystem adapter: the materialized store behind `build_snapshot`."""

    store: str | Path | None
    dataset_id: str = DEFAULT_DATASET_ID
    dataset_name: str = DEFAULT_DATASET_NAME
    project_data_root: str | Path | None = None
    agent_base_url: str | None = None
    # The bounded timeout for one current-graph read from the agent.
    graph_timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    instance_id: str | None = None
    # The read-only harness runs root the recorded-spend block resolves against;
    # None leaves every Trial's spend `unavailable` (never guessed).
    runs_root: str | Path | None = None
    # The optional read-only legacy runs root (historical records). Searched
    # beside the primary root; unset by default.
    legacy_runs_root: str | Path | None = None
    graph_client_factory: Callable[[], ProjectGraphClient | None] | None = None

    def snapshot(self) -> dict[str, Any]:
        snapshot = self._catalog_snapshot()
        snapshot["unassigned_saved_data"] = self._unassigned_saved_data(snapshot)
        self._attach_spend(snapshot)
        return snapshot

    def _catalog_snapshot(self) -> dict[str, Any]:
        """The unified catalogue: materialized Trials plus authoritative records.

        The store tree is projected first, then every unique run record whose
        identity is not already materialized is added. A shared identity keeps
        the materialized capture (never overwritten by current files), and a
        physically ambiguous identity is left out and reported as a path-free
        issue instead of being arbitrated. The whole report is re-aggregated
        from the merged Trial list, so targets, summary, versions, successes and
        the degraded list stay coherent.
        """
        if not self.store:
            raise SnapshotSourceUnavailable(f"{ENV_STORE} is not configured")
        trials = project_store_trials(self.store)
        materialized = {
            (trial["target_id"], trial["target_run_id"], trial["trial_id"])
            for trial in trials
        }
        catalog = load_run_record_catalog(self._runs_roots(), files=FileStore())
        for identity in sorted(catalog.records):
            if identity in materialized:
                continue
            trials.append(project_run_record(catalog.records[identity]))
        # Enrich every Trial - materialized included - with the real execution
        # instants from a unique record that also matches its project and
        # instance. An ambiguous or mismatched record never associates, and no
        # other field (results, provenance, identity) is touched.
        for trial in trials:
            record = catalog.records.get(
                (trial["target_id"], trial["target_run_id"], trial["trial_id"])
            )
            if record is None:
                continue
            if record.project_id != trial.get("project_id"):
                continue
            if record.instance_id != trial.get("instance_id"):
                continue
            trial["started_at"] = record.started_at
            trial["finished_at"] = record.finished_at
        snapshot = assemble_snapshot(
            trials, dataset_id=self.dataset_id, dataset_name=self.dataset_name
        )
        # A materialized capture already resolves its identity, so an ambiguity
        # over that same identity never reaches the operator. Scan/oversize
        # issues are not attributable to one identity, so they always surface.
        codes = set(catalog.issues)
        if all(identity in materialized for identity in catalog.ambiguous):
            codes.discard(RUN_RECORD_AMBIGUOUS)
        snapshot["issues"] = sorted(codes)
        return snapshot

    def _runs_roots(self) -> tuple[str | Path, ...]:
        return tuple(
            root for root in (self.runs_root, self.legacy_runs_root) if root
        )

    def get_project_graph(
        self, target_id: str, target_run_id: str, trial_id: str
    ) -> dict[str, Any]:
        if not self.store:
            raise SnapshotSourceUnavailable(f"{ENV_STORE} is not configured")
        return read_project_graph(self.store, target_id, target_run_id, trial_id)

    def list_artifacts(
        self, target_id: str, target_run_id: str, trial_id: str
    ) -> dict[str, Any]:
        if not self.store:
            raise SnapshotSourceUnavailable(f"{ENV_STORE} is not configured")
        return list_artifacts(self.store, target_id, target_run_id, trial_id)

    def get_artifact(
        self, target_id: str, target_run_id: str, trial_id: str, artifact_id: str
    ) -> dict[str, Any]:
        if not self.store:
            raise SnapshotSourceUnavailable(f"{ENV_STORE} is not configured")
        return get_artifact(self.store, target_id, target_run_id, trial_id, artifact_id)

    def stream_artifact(
        self, target_id: str, target_run_id: str, trial_id: str, artifact_id: str
    ) -> ArtifactDownload:
        if not self.store:
            raise SnapshotSourceUnavailable(f"{ENV_STORE} is not configured")
        return stream_artifact(self.store, target_id, target_run_id, trial_id, artifact_id)

    def resolved_graph(
        self, target_id: str, target_run_id: str, trial_id: str
    ) -> dict[str, Any]:
        context = self._resolve_context(target_id, target_run_id, trial_id)
        resolved = resolve_graph(self.store, context, client=self._graph_client())
        return graph_response(resolved)

    def list_resolved_artifacts(
        self, target_id: str, target_run_id: str, trial_id: str
    ) -> dict[str, Any]:
        inventory = self._resolve_inventory(target_id, target_run_id, trial_id)
        return inventory_response(inventory, target_id, target_run_id, trial_id)

    def get_resolved_artifact(
        self, target_id: str, target_run_id: str, trial_id: str, artifact_id: str
    ) -> dict[str, Any]:
        inventory = self._resolve_inventory(target_id, target_run_id, trial_id)
        return detail_response(
            inventory, target_id, target_run_id, trial_id, artifact_id
        )

    def stream_resolved_artifact(
        self,
        target_id: str,
        target_run_id: str,
        trial_id: str,
        artifact_id: str,
        expected_sha256: str,
    ) -> ArtifactDownload:
        inventory = self._resolve_inventory(target_id, target_run_id, trial_id)
        return content_download(inventory, artifact_id, expected_sha256)

    # --- resolved configuration helpers -----------------------------------------

    def _resolve_context(
        self, target_id: str, target_run_id: str, trial_id: str
    ) -> TrialContext:
        return resolve_trial_context(
            self._catalog_snapshot(),
            target_id,
            target_run_id,
            trial_id,
            configured_instance_id=self.instance_id,
        )

    def _resolve_inventory(
        self, target_id: str, target_run_id: str, trial_id: str
    ) -> ResolvedInventory:
        context = self._resolve_context(target_id, target_run_id, trial_id)
        return resolve_inventory(
            self.store, self.project_data_root, context, files=FileStore()
        )

    def _graph_client(self) -> ProjectGraphClient | None:
        if self.graph_client_factory is not None:
            return self.graph_client_factory()
        if self.agent_base_url:
            return HttpProjectGraphClient(
                self.agent_base_url, timeout=self.graph_timeout_seconds
            )
        return None

    def _attach_spend(self, snapshot: Mapping[str, object]) -> None:
        """Attach each projected Trial's recorded spend, resolved by identity.

        The runs root is walked once and every Trial is matched against the
        same preloaded records; an unconfigured root leaves every block
        `unavailable`, so a missing source never hides the rest of the report.
        """
        trials = snapshot.get("trials")
        if not isinstance(trials, list):
            return
        roots = [root for root in (self.runs_root, self.legacy_runs_root) if root]
        if not roots:
            block = TrialSpend(
                status="unavailable", reason=SPEND_ROOT_UNCONFIGURED
            ).to_dict()
            for trial in trials:
                if isinstance(trial, dict):
                    trial["spend"] = dict(block)
            return
        records = load_spend_records_from_roots(roots, files=FileStore())
        for trial in trials:
            if not isinstance(trial, dict):
                continue
            spend = match_spend(
                records,
                target_id=trial.get("target_id"),
                target_run_id=trial.get("target_run_id"),
                trial_id=trial.get("trial_id"),
                project_id=trial.get("project_id"),
                instance_id=trial.get("instance_id"),
            )
            trial["spend"] = spend.to_dict()

    def _unassigned_saved_data(self, snapshot: Mapping[str, object]) -> list[dict]:
        """Raw project directories no projected Trial proves belong to this instance."""
        root = self.project_data_root
        if not root:
            return []
        root_path = Path(root)
        try:
            if not root_path.is_dir():
                return []
            children = sorted(root_path.iterdir(), key=lambda path: path.name)
        except OSError:
            return []

        assigned = self._assigned_project_ids(snapshot)
        files = FileStore()
        rows: list[dict] = []
        for child in children:
            name = child.name
            if (
                not is_safe_identifier(name)
                or name in assigned
                or name in _NON_PROJECT_DATA_DIRNAMES
            ):
                continue
            if not (child.is_symlink() or child.is_dir()):
                continue
            try:
                collected = collect_project_artifacts(root_path, name, files=files)
            except ProjectArtifactError as exc:
                rows.append(
                    {
                        "project_id": name,
                        "status": "unavailable",
                        "hunting": 0,
                        "skills": 0,
                        "reason": exc.failure,
                    }
                )
                continue
            rows.append(
                {
                    "project_id": name,
                    "status": "available",
                    "hunting": sum(1 for a in collected if a.category == "hunting"),
                    "skills": sum(1 for a in collected if a.category == "skill"),
                }
            )
        return rows

    def _assigned_project_ids(self, snapshot: Mapping[str, object]) -> set[str]:
        """Project ids a projected Trial proves belong to this instance."""
        if self.instance_id is None:
            return set()
        assigned: set[str] = set()
        trials = snapshot.get("trials")
        if not isinstance(trials, list):
            return assigned
        for trial in trials:
            if not isinstance(trial, Mapping):
                continue
            if trial.get("instance_id") != self.instance_id:
                continue
            project_id = trial.get("project_id")
            if is_safe_identifier(project_id):
                assigned.add(project_id)  # type: ignore[arg-type]
        return assigned

    def health(self) -> SourceHealth:
        configured = bool(self.store)
        readable = configured and Path(self.store).is_dir()
        trials = _count_materialized_trials(self.store) if readable else 0
        run_records = _count_run_record_trials(self.store, self._runs_roots())
        data_root = Path(self.project_data_root) if self.project_data_root else None
        return SourceHealth(
            ok=configured and readable,
            detail={
                "store_configured": configured,
                "store_readable": readable,
                "materialized_trials": trials,
                # Catalogued authoritative records not yet copied into the
                # store; `materialized_trials` keeps its exact former meaning.
                "run_record_trials": run_records,
                "project_data_configured": bool(self.project_data_root),
                "project_data_readable": bool(data_root and data_root.is_dir()),
                "graph_client_configured": bool(
                    self.agent_base_url or self.graph_client_factory
                ),
            },
        )


def _count_materialized_trials(store: str | Path | None) -> int:
    """The number of `<target>/<run>/<trial>/run-manifest.yaml` trees.

    A readable empty store is healthy and reports zero; a walk error degrades
    the count to zero rather than failing health. Host paths never reach the
    response.
    """
    if not store:
        return 0
    root = Path(store)
    count = 0
    try:
        for target in root.iterdir():
            if not target.is_dir() or target.name in _SKIP_DIRNAMES:
                continue
            for run in target.iterdir():
                if not run.is_dir() or run.name in _SKIP_DIRNAMES:
                    continue
                for trial in run.iterdir():
                    if not trial.is_dir() or trial.name in _SKIP_DIRNAMES:
                        continue
                    if (trial / MANIFEST_FILENAME).is_file():
                        count += 1
    except OSError:
        return 0
    return count


def _count_run_record_trials(
    store: str | Path | None, roots: tuple[str | Path, ...]
) -> int:
    """Authoritative records catalogued from the runs roots but not materialized.

    The health block keeps `materialized_trials` as the exact store count and
    reports these separately, so a catalogued-but-uncopied Trial is never
    mistaken for a materialized one. All read errors degrade the count to zero.
    """
    if not roots:
        return 0
    try:
        catalog = load_run_record_catalog(roots, files=FileStore())
    except OSError:
        return 0
    root = Path(store) if store else None
    count = 0
    for target_id, target_run_id, trial_id in catalog.records:
        if root is not None and (
            root / target_id / target_run_id / trial_id / MANIFEST_FILENAME
        ).is_file():
            continue
        count += 1
    return count


def filesystem_source() -> SnapshotSource:
    """The default factory: an artifact-store source from the current environment."""
    return ArtifactStoreSnapshotSource(
        store=os.environ.get(ENV_STORE),
        dataset_id=os.environ.get(ENV_DATASET_ID) or DEFAULT_DATASET_ID,
        dataset_name=os.environ.get(ENV_DATASET_NAME) or DEFAULT_DATASET_NAME,
        project_data_root=os.environ.get(ENV_PROJECT_DATA_ROOT) or None,
        agent_base_url=os.environ.get(ENV_AGENT_BASE_URL) or None,
        graph_timeout_seconds=resolve_graph_timeout(os.environ.get(ENV_GRAPH_TIMEOUT)),
        instance_id=os.environ.get(ENV_INSTANCE_ID) or None,
        runs_root=os.environ.get(ENV_RUNS_ROOT) or None,
        legacy_runs_root=os.environ.get(ENV_LEGACY_RUNS_ROOT) or None,
    )
