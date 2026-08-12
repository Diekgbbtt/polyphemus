from pathlib import Path
from uuid import uuid4
import asyncio

from agent.app.clients import pg
from agent.app.config import config
from agent.ingestion.contracts import (
    IngestionError,
    SourceRecord,
    SourceStatus,
    classify_source,
)
from agent.ingestion.docprep_adapter import DocprepError, normalize_document
from agent.ingestion.lightrag_adapter import LightRAGAdapterError, LightRAGIngestionAdapter
from agent.ingestion.source_identity import (
    SourceValidationError,
    build_source_key,
    content_sha256,
    validate_source_path,
)
from agent.lightrag.client import LightRAGHttpClient


class IngestionService:
    def __init__(
        self,
        *,
        ingestion_root: Path,
        normalized_root: Path,
        lightrag_adapter: LightRAGIngestionAdapter | None = None,
    ):
        self.ingestion_root = ingestion_root
        self.normalized_root = normalized_root
        self.lightrag_adapter = lightrag_adapter or LightRAGIngestionAdapter(client=LightRAGHttpClient())

    @classmethod
    def from_config(cls) -> "IngestionService":
        ingestion_root = Path(config.INGESTION_ROOT)
        normalized_root = Path(config.INGESTION_NORMALIZED_DIR)
        return cls(ingestion_root=ingestion_root, normalized_root=normalized_root)

    def submit(self, *, source_kind: str, source_uri: str) -> dict:
        if source_kind != "file":
            raise ValueError("only file ingestion is supported in Milestone 1")
        source_path = validate_source_path(Path(source_uri), allowed_root=self.ingestion_root)
        content_hash = content_sha256(source_path)
        source_key = build_source_key(source_path, allowed_root=self.ingestion_root)
        source_record = SourceRecord(
            source_key=source_key,
            source_kind="file",
            source_uri=source_path.relative_to(self.ingestion_root.resolve()).as_posix(),
            content_hash=content_hash,
            status=SourceStatus.DISCOVERED,
        )
        classification = classify_source(pg.get_ingestion_source(source_key), incoming_hash=content_hash)
        job_id = str(uuid4())
        if classification.status == SourceStatus.SKIPPED_DUPLICATE:
            pg.create_ingestion_job(job_id=job_id, source_key=source_key, status=SourceStatus.SKIPPED_DUPLICATE)
            pg.set_ingestion_job_status(job_id, SourceStatus.SKIPPED_DUPLICATE)
            return {
                "job_id": job_id,
                "source_key": source_key,
                "status": SourceStatus.SKIPPED_DUPLICATE,
                "run_in_background": False,
            }

        processed_duplicate = pg.get_processed_ingestion_source_by_hash(content_hash)
        if processed_duplicate is not None:
            duplicate_record = SourceRecord(
                source_key=source_key,
                source_kind="file",
                source_uri=source_record.source_uri,
                content_hash=content_hash,
                status=SourceStatus.SKIPPED_DUPLICATE,
                parser=processed_duplicate.parser,
                parser_version=processed_duplicate.parser_version,
                normalization_version=processed_duplicate.normalization_version,
                lightrag_document_id=processed_duplicate.lightrag_document_id,
                normalized_markdown_path=processed_duplicate.normalized_markdown_path,
                normalized_json_path=processed_duplicate.normalized_json_path,
            )
            pg.upsert_ingestion_source(duplicate_record)
            pg.create_ingestion_job(job_id=job_id, source_key=source_key, status=SourceStatus.SKIPPED_DUPLICATE)
            pg.set_ingestion_job_status(job_id, SourceStatus.SKIPPED_DUPLICATE)
            return {
                "job_id": job_id,
                "source_key": source_key,
                "status": SourceStatus.SKIPPED_DUPLICATE,
                "run_in_background": False,
            }

        pg.upsert_ingestion_source(source_record)
        pg.create_ingestion_job(job_id=job_id, source_key=source_key, status=SourceStatus.DISCOVERED)
        return {
            "job_id": job_id,
            "source_key": source_key,
            "status": SourceStatus.DISCOVERED,
            "run_in_background": True,
        }

    def get_job(self, job_id: str) -> dict | None:
        return pg.get_ingestion_job(job_id)

    def process_job(self, job_id: str) -> None:
        job = pg.get_ingestion_job(job_id)
        if job is None:
            return
        source_key = job["source_key"]
        record = pg.get_ingestion_source(source_key)
        if record is None:
            return
        source_path = self.ingestion_root / record.source_uri
        try:
            self._set_status(record, job_id, SourceStatus.PROCESSING)
            normalized = asyncio.run(normalize_document(source_path, output_root=self.normalized_root))
            record.parser = normalized.parser
            record.normalization_version = "lightrag_docprep"
            record.normalized_markdown_path = str(normalized.markdown_path)
            record.normalized_json_path = str(normalized.json_path)
            self._set_status(record, job_id, SourceStatus.NORMALIZED)
            self._set_status(record, job_id, SourceStatus.INGESTING)
            result = self.lightrag_adapter.ingest_markdown(normalized.markdown_path, source_key=source_key)
            record.lightrag_document_id = result.document_id
            self._set_status(record, job_id, SourceStatus.AUDITING)
            audit = {"critical_issues": 0, "warnings": 0}
            self._set_status(record, job_id, SourceStatus.PROCESSED, audit=audit)
        except SourceValidationError as exc:
            self._fail(record, job_id, exc.code, str(exc), SourceStatus.PROCESSING)
        except DocprepError as exc:
            self._fail(record, job_id, exc.code, str(exc), SourceStatus.PROCESSING)
        except LightRAGAdapterError as exc:
            self._fail(record, job_id, exc.code, str(exc), SourceStatus.INGESTING)

    def _set_status(
        self,
        record: SourceRecord,
        job_id: str,
        status: SourceStatus,
        *,
        audit: dict | None = None,
    ) -> None:
        record.status = status
        record.last_error_code = None
        record.last_error_message = None
        pg.upsert_ingestion_source(record)
        pg.set_ingestion_job_status(job_id, status, audit=audit)

    def _fail(
        self,
        record: SourceRecord,
        job_id: str,
        code: str,
        message: str,
        stage: SourceStatus,
    ) -> None:
        record.status = SourceStatus.FAILED
        record.last_error_code = code
        record.last_error_message = message
        pg.upsert_ingestion_source(record)
        pg.set_ingestion_job_status(
            job_id,
            SourceStatus.FAILED,
            error=IngestionError(code=code, message=message, stage=stage.value).model_dump(),
        )
