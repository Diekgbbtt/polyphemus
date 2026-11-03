"""The append-only run ledger and the finalize path.

Spec: `docs/design/steel-crawl-spec.md` sections 10.4 and 12.

The ledger is the durable record of every artifact and manifest the run
produced. It is append-only JSONL, fsynced per entry, so a killed process leaves
a file the pipeline job's `finally` can finalize. `finalize` closes the sidecar,
appends the partial manifest, runs the HTTP-history flush and the graph
ingestion in parallel, and returns a result that is never mistaken for a complete
run when anything failed.
"""
from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from polymerhus.recon.crawl.steel.capture.history import HttpArtifact
from polymerhus.recon.crawl.steel.manifest import ErrorRecord, Manifest

COMPLETE_STOP_REASONS = frozenset({"frontier_empty", "complete"})


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunLedger:
    """Append-only JSONL ledger for one run.

    `append` writes one record, flushes it, and fsyncs it before returning. A
    reader sees only whole lines: a crash can lose the last append, never corrupt
    the earlier ones. The ledger is the recovery source, so it never rewrites or
    truncates itself.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A body is written once per run. The sidecar caps DISTINCT bodies at
        # `DEFAULT_MAX_RUN_BYTES`; repeating the same body on every artifact
        # that references it would make the ledger grow with the flow count,
        # not with the capture budget (an 8 GiB ledger on one admin target).
        self._written_bodies: set[str] = set()

    def append(self, kind: str, payload: Mapping[str, Any]) -> None:
        record = {"ts": _utcnow(), "kind": kind, "payload": dict(payload)}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def entries(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    def append_artifact(
        self, artifact: HttpArtifact, bodies: Mapping[str, bytes]
    ) -> None:
        encoded: list[dict[str, Any]] = []
        for ref, content in bodies.items():
            item: dict[str, Any] = {
                "body_ref": ref,
                "sha256": ref.removeprefix("sha256:"),
            }
            if ref not in self._written_bodies:
                item["data"] = base64.b64encode(content).decode("ascii")
                self._written_bodies.add(ref)
            encoded.append(item)
        self.append(
            "artifact",
            {
                "artifact": artifact.model_dump(mode="json"),
                "bodies": encoded,
            },
        )

    def artifacts(self) -> list[tuple[HttpArtifact, dict[str, bytes]]]:
        """Every artifact, with each distinct body attached once.

        The append-only file stores a body on its first occurrence only. A
        consumer that needs a later artifact's body resolves `body_ref` in the
        edge store; the recovery list therefore never materialises one copy per
        referencing flow (the 8 GiB-admin-target failure).
        """
        found: list[tuple[HttpArtifact, dict[str, bytes]]] = []
        known: dict[str, bytes] = {}
        for entry in self.entries():
            if entry.get("kind") != "artifact":
                continue
            payload = entry.get("payload")
            if not isinstance(payload, Mapping):
                continue
            try:
                artifact = HttpArtifact.model_validate(payload.get("artifact"))
            except Exception:  # noqa: BLE001 - a corrupt entry is skipped, not fatal
                continue
            bodies: dict[str, bytes] = {}
            for item in payload.get("bodies") or []:
                if not isinstance(item, Mapping):
                    continue
                ref = item.get("body_ref")
                if not isinstance(ref, str):
                    continue
                data = item.get("data")
                if isinstance(data, str) and data:
                    try:
                        decoded = base64.b64decode(data)
                    except (ValueError, TypeError):
                        continue
                    self._written_bodies.add(ref)
                    known[ref] = decoded
                    bodies[ref] = decoded
                # A later artifact references a digest whose bytes were already
                # attached to the first occurrence. The edge keys bodies by
                # digest, so nothing is lost and the recovery list stays
                # proportional to the DISTINCT capture budget, not the flows.
            found.append((artifact, bodies))
        return found

    def append_manifest(self, manifest: Manifest) -> None:
        self.append("manifest", manifest.model_dump(mode="json"))

    def manifests(self) -> list[Manifest]:
        found: list[Manifest] = []
        for entry in self.entries():
            if entry.get("kind") != "manifest":
                continue
            try:
                found.append(Manifest.model_validate(entry.get("payload")))
            except Exception:  # noqa: BLE001 - a corrupt entry is skipped
                continue
        return found

    def append_error(self, code: str, message: str, *, stage: str = "finalize") -> None:
        self.append("error", {"code": code, "message": message, "stage": stage})

    def errors(self) -> list[dict[str, Any]]:
        return [
            dict(entry["payload"])
            for entry in self.entries()
            if entry.get("kind") == "error" and isinstance(entry.get("payload"), Mapping)
        ]

    def cursor(self) -> int:
        for entry in reversed(self.entries()):
            if entry.get("kind") != "flush_cursor":
                continue
            payload = entry.get("payload")
            if isinstance(payload, Mapping):
                try:
                    return int(payload.get("cursor", 0))
                except (TypeError, ValueError):
                    return 0
        return 0

    def set_cursor(self, cursor: int) -> None:
        self.append("flush_cursor", {"cursor": int(cursor)})


@dataclass(frozen=True)
class FinalizeResult:
    """The terminal state of a finalize pass.

    `status` is `partial` whenever the stop reason was not a clean frontier
    exhaustion or any flush/ingest step failed, so a caller can never report a
    partial run as complete. `coverage` is the separate report the graph
    ingestion consumes; it is not a manifest block.
    """

    status: Literal["complete", "partial"]
    manifest: Manifest
    flush: Any = None
    ingest: Any = None
    errors: tuple[str, ...] = ()
    coverage: dict[str, Any] = field(default_factory=dict)

    @property
    def partial(self) -> bool:
        return self.status == "partial"


def finalize(
    *,
    ledger: RunLedger,
    manifest: Manifest,
    stop_reason: str,
    finished_at: str,
    flush_fn: Callable[[Sequence[tuple[HttpArtifact, dict[str, bytes]]]], Mapping[str, Any]],
    ingest_fn: Callable[[Manifest], Any],
    close_fn: Callable[[], None] | None = None,
    coverage: Mapping[str, Any] | None = None,
) -> FinalizeResult:
    """Finalize a run from its ledger, on success and on every failure path.

    The sidecar closes first, the partial manifest is appended, then the HTTP
    flush and the graph ingestion run in parallel. Each failure is recorded as a
    ledger error and in the manifest's error list; a failed flush leaves the
    ledger and its cursor intact. The returned manifest is always the final
    terminal state.
    """
    errors: list[str] = []
    if close_fn is not None:
        try:
            close_fn()
        except Exception as exc:  # noqa: BLE001 - close is best-effort
            errors.append(f"capture_close_failed: {exc}")
            ledger.append_error("capture_close_failed", str(exc), stage="finalize")

    partial = stop_reason not in COMPLETE_STOP_REASONS or bool(manifest.run.partial)
    run = manifest.run.model_copy(
        update={
            "stop_reason": stop_reason,
            "finished_at": finished_at,
            "partial": partial,
        }
    )
    manifest = manifest.model_copy(update={"run": run})
    ledger.append_manifest(manifest)

    artifacts = _dedupe_bodies(ledger.artifacts())
    flush_result: Any = None
    ingest_result: Any = None
    flush_error: str | None = None
    ingest_error: str | None = None

    def run_flush() -> tuple[Any, str | None, int | None]:
        try:
            result = flush_fn(artifacts)
        except Exception as exc:  # noqa: BLE001 - the ledger stays durable
            return None, f"http_history_flush_failed: {exc}", None
        cursor = None
        if isinstance(result, Mapping):
            try:
                cursor = int(result.get("cursor", 0))
            except (TypeError, ValueError):
                cursor = None
        return result, None, cursor

    def run_ingest() -> tuple[Any, str | None]:
        try:
            return ingest_fn(manifest), None
        except Exception as exc:  # noqa: BLE001 - the partial run is not complete
            return None, f"graph_ingest_failed: {exc}"

    with ThreadPoolExecutor(max_workers=2) as pool:
        flush_future = pool.submit(run_flush)
        ingest_future = pool.submit(run_ingest)
        flush_result, flush_error, cursor = flush_future.result()
        ingest_result, ingest_error = ingest_future.result()

    if flush_error is not None:
        errors.append(flush_error)
        ledger.append_error("http_history_flush_failed", flush_error, stage="flush")
    elif cursor is not None:
        ledger.set_cursor(cursor)
    if ingest_error is not None:
        errors.append(ingest_error)
        ledger.append_error("graph_ingest_failed", ingest_error, stage="ingest")

    if errors:
        partial = True
        recorded = list(manifest.errors) + [
            ErrorRecord(
                code=error.split(":", 1)[0],
                message=error,
                stage="finalize",
            )
            for error in errors
        ]
        manifest = manifest.model_copy(
            update={
                "run": manifest.run.model_copy(update={"partial": True}),
                "errors": recorded,
            }
        )

    ledger.append_manifest(manifest)
    return FinalizeResult(
        status="complete" if not partial else "partial",
        manifest=manifest,
        flush=flush_result,
        ingest=ingest_result,
        errors=tuple(errors),
        coverage=dict(coverage or {}),
    )


def _dedupe_bodies(
    artifacts: Sequence[tuple[HttpArtifact, dict[str, bytes]]],
) -> list[tuple[HttpArtifact, dict[str, bytes]]]:
    """Attach each body to the first artifact that references it.

    The edge keys bodies by content digest, so a later artifact with the same
    `body_ref` resolves the stored body without a second copy on the wire. The
    sidecar already caps DISTINCT bodies; this keeps the flush proportional to
    that budget instead of to the flow count.
    """
    seen: set[str] = set()
    deduped: list[tuple[HttpArtifact, dict[str, bytes]]] = []
    for artifact, bodies in artifacts:
        kept: dict[str, bytes] = {}
        for ref, content in bodies.items():
            if ref in seen:
                continue
            seen.add(ref)
            kept[ref] = content
        deduped.append((artifact, kept))
    return deduped


__all__ = [
    "COMPLETE_STOP_REASONS",
    "FinalizeResult",
    "RunLedger",
    "finalize",
]
