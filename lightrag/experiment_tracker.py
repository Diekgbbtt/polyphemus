from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_HISTORY_DB = Path("lightrag/data/lightrag/benchmarks/wstg_benchmark_history.sqlite3")


@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    timestamp: str
    run_label: str
    test_case_id: str
    abstracted_profile: dict[str, Any]
    query_template_type: str
    query_payload: dict[str, Any]
    lightrag_config: dict[str, Any]
    retrieved_subgraph: dict[str, Any]
    raw_response: str
    metrics: dict[str, Any]


@dataclass(frozen=True)
class IngestionBatchRecord:
    ingestion_event_id: str
    timestamp: str
    run_label: str
    batch_number: int
    input_dir: str
    uploaded_files: list[str]
    upload_responses: list[dict[str, Any]]
    processing: dict[str, Any]
    normalization: dict[str, Any] | None
    graph_gate: dict[str, Any] | None
    query_evaluations: list[dict[str, Any]]
    metrics: dict[str, Any]
    passed: bool
    error: str


class ExperimentTracker:
    """SQLite-backed history store for LightRAG benchmark and ingestion runs."""

    def __init__(self, db_path: str | Path = DEFAULT_HISTORY_DB):
        self.db_path = Path(db_path)
        if str(db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def __enter__(self) -> ExperimentTracker:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def log_run(
        self,
        *,
        test_case_id: str,
        abstracted_profile: Mapping[str, Any],
        query_template_type: str,
        query_payload: Mapping[str, Any],
        lightrag_config: Mapping[str, Any],
        retrieved_subgraph: Mapping[str, Any] | None,
        raw_response: str,
        metrics: Mapping[str, Any],
        run_label: str = "",
        experiment_id: str | None = None,
        timestamp: str | None = None,
    ) -> str:
        run_id = experiment_id or str(uuid.uuid4())
        run_timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO lightrag_benchmark_runs (
                experiment_id,
                timestamp,
                run_label,
                test_case_id,
                abstracted_profile,
                query_template_type,
                query_payload,
                lightrag_config,
                retrieved_subgraph,
                raw_response,
                metrics
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                run_timestamp,
                run_label,
                test_case_id,
                _json_dumps(abstracted_profile),
                query_template_type,
                _json_dumps(query_payload),
                _json_dumps(lightrag_config),
                _json_dumps(retrieved_subgraph or {}),
                raw_response,
                _json_dumps(metrics),
            ),
        )
        self._conn.commit()
        return run_id

    def log_ingestion_batch(
        self,
        *,
        batch_number: int,
        input_dir: str | Path,
        uploaded_files: Sequence[str],
        upload_responses: Sequence[Mapping[str, Any]],
        processing: Mapping[str, Any],
        normalization: Mapping[str, Any] | None,
        graph_gate: Mapping[str, Any] | None,
        query_evaluations: Sequence[Mapping[str, Any]],
        metrics: Mapping[str, Any],
        passed: bool,
        run_label: str = "",
        error: str = "",
        ingestion_event_id: str | None = None,
        timestamp: str | None = None,
    ) -> str:
        event_id = ingestion_event_id or str(uuid.uuid4())
        event_timestamp = timestamp or datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO lightrag_ingestion_batches (
                ingestion_event_id,
                timestamp,
                run_label,
                batch_number,
                input_dir,
                uploaded_files,
                upload_responses,
                processing,
                normalization,
                graph_gate,
                query_evaluations,
                metrics,
                passed,
                error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                event_timestamp,
                run_label,
                int(batch_number),
                str(input_dir),
                _json_dumps(list(uploaded_files)),
                _json_dumps(list(upload_responses)),
                _json_dumps(processing),
                _json_dumps(normalization) if normalization is not None else None,
                _json_dumps(graph_gate) if graph_gate is not None else None,
                _json_dumps(list(query_evaluations)),
                _json_dumps(metrics),
                1 if passed else 0,
                error,
            ),
        )
        self._conn.commit()
        return event_id

    def iter_ingestion_batches(
        self,
        *,
        run_label: str | None = None,
    ) -> Iterable[IngestionBatchRecord]:
        filters = []
        params: list[Any] = []
        if run_label is not None:
            filters.append("run_label = ?")
            params.append(run_label)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        rows = self._conn.execute(
            f"""
            SELECT *
            FROM lightrag_ingestion_batches
            {where_clause}
            ORDER BY timestamp ASC, batch_number ASC
            """,
            params,
        ).fetchall()
        return [_row_to_ingestion_record(row) for row in rows]

    def get_run(self, experiment_id: str) -> ExperimentRecord | None:
        row = self._conn.execute(
            """
            SELECT *
            FROM lightrag_benchmark_runs
            WHERE experiment_id = ?
            """,
            (experiment_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_record(row)

    def iter_runs(
        self,
        *,
        run_label: str | None = None,
        test_case_id: str | None = None,
        query_template_type: str | None = None,
    ) -> Iterable[ExperimentRecord]:
        filters = []
        params: list[Any] = []
        if run_label is not None:
            filters.append("run_label = ?")
            params.append(run_label)
        if test_case_id:
            filters.append("test_case_id = ?")
            params.append(test_case_id)
        if query_template_type:
            filters.append("query_template_type = ?")
            params.append(query_template_type)
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        rows = self._conn.execute(
            f"""
            SELECT *
            FROM lightrag_benchmark_runs
            {where_clause}
            ORDER BY timestamp ASC
            """,
            params,
        ).fetchall()
        return [_row_to_record(row) for row in rows]

    def latest_runs(self, *, limit: int = 50) -> list[ExperimentRecord]:
        rows = self._conn.execute(
            """
            SELECT *
            FROM lightrag_benchmark_runs
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_record(row) for row in rows]

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lightrag_benchmark_runs (
                experiment_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                run_label TEXT NOT NULL DEFAULT '',
                test_case_id TEXT NOT NULL,
                abstracted_profile TEXT NOT NULL,
                query_template_type TEXT NOT NULL,
                query_payload TEXT NOT NULL,
                lightrag_config TEXT NOT NULL,
                retrieved_subgraph TEXT NOT NULL,
                raw_response TEXT NOT NULL,
                metrics TEXT NOT NULL
            )
            """
        )
        columns = {
            row["name"]
            for row in self._conn.execute(
                "PRAGMA table_info(lightrag_benchmark_runs)"
            ).fetchall()
        }
        if "run_label" not in columns:
            self._conn.execute(
                "ALTER TABLE lightrag_benchmark_runs "
                "ADD COLUMN run_label TEXT NOT NULL DEFAULT ''"
            )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lightrag_benchmark_case_template
            ON lightrag_benchmark_runs (test_case_id, query_template_type)
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lightrag_benchmark_timestamp
            ON lightrag_benchmark_runs (timestamp)
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lightrag_benchmark_run_label
            ON lightrag_benchmark_runs (run_label)
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lightrag_ingestion_batches (
                ingestion_event_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                run_label TEXT NOT NULL DEFAULT '',
                batch_number INTEGER NOT NULL,
                input_dir TEXT NOT NULL,
                uploaded_files TEXT NOT NULL,
                upload_responses TEXT NOT NULL,
                processing TEXT NOT NULL,
                normalization TEXT,
                graph_gate TEXT,
                query_evaluations TEXT NOT NULL,
                metrics TEXT NOT NULL,
                passed INTEGER NOT NULL,
                error TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lightrag_ingestion_run_label
            ON lightrag_ingestion_batches (run_label)
            """
        )
        self._conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_lightrag_ingestion_timestamp
            ON lightrag_ingestion_batches (timestamp)
            """
        )
        self._conn.commit()


def _row_to_record(row: sqlite3.Row) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=row["experiment_id"],
        timestamp=row["timestamp"],
        run_label=row["run_label"],
        test_case_id=row["test_case_id"],
        abstracted_profile=json.loads(row["abstracted_profile"]),
        query_template_type=row["query_template_type"],
        query_payload=json.loads(row["query_payload"]),
        lightrag_config=json.loads(row["lightrag_config"]),
        retrieved_subgraph=json.loads(row["retrieved_subgraph"]),
        raw_response=row["raw_response"],
        metrics=json.loads(row["metrics"]),
    )


def _row_to_ingestion_record(row: sqlite3.Row) -> IngestionBatchRecord:
    return IngestionBatchRecord(
        ingestion_event_id=row["ingestion_event_id"],
        timestamp=row["timestamp"],
        run_label=row["run_label"],
        batch_number=row["batch_number"],
        input_dir=row["input_dir"],
        uploaded_files=json.loads(row["uploaded_files"]),
        upload_responses=json.loads(row["upload_responses"]),
        processing=json.loads(row["processing"]),
        normalization=(
            json.loads(row["normalization"])
            if row["normalization"] is not None
            else None
        ),
        graph_gate=json.loads(row["graph_gate"]) if row["graph_gate"] is not None else None,
        query_evaluations=json.loads(row["query_evaluations"]),
        metrics=json.loads(row["metrics"]),
        passed=bool(row["passed"]),
        error=row["error"],
    )


def _json_dumps(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, ensure_ascii=True)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    return value
