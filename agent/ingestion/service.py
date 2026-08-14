from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import asyncio
from typing import Any, Callable

from agent.app.clients import pg
from agent.app.config import config
from agent.ingestion.audit import (
    LightRAGStorageReader,
    StorageParseError,
    build_storage_parse_error_report,
    run_post_ingestion_audit,
)
from agent.ingestion.contracts import (
    IngestionError,
    SourceChange,
    SourceRecord,
    SourceStatus,
    classify_source,
)
from agent.ingestion.docprep_adapter import (
    DocprepError,
    normalize_document,
    normalize_downloaded_artifact,
)
from agent.ingestion.lightrag_adapter import LightRAGAdapterError, LightRAGIngestionAdapter
from agent.ingestion.source_identity import (
    SourceValidationError,
    build_source_key,
    build_url_source_key,
    canonicalize_url,
    content_sha256,
    validate_source_path,
)
from agent.ingestion.url_downloader import URLDownloadError, UrlDownloadResult, UrlDownloader
from agent.lightrag.client import LightRAGHttpClient
from agent.lightrag.ontology import ENTITY_TYPES


_URL_MEDIA_TYPE_TO_SOURCE_TYPE = {
    "text/html": "html",
    "application/xhtml+xml": "html",
    "text/markdown": "markdown",
    "text/x-markdown": "markdown",
    "text/plain": "markdown",
}


def _url_source_type(result: UrlDownloadResult) -> str:
    """Map the declared download MIME type to the docprep parser type.

    The downloader has already applied the exact MIME policy, so an
    unsupported or ambiguous type never reaches this mapping. The defensive
    failure below keeps that invariant explicit.
    """
    media_type = (result.content_type or "").split(";", 1)[0].strip().lower()
    source_type = _URL_MEDIA_TYPE_TO_SOURCE_TYPE.get(media_type)
    if source_type is None:
        raise URLDownloadError("URL_CONTENT_TYPE_UNSUPPORTED")
    return source_type


def _docprep_native_metadata(result: UrlDownloadResult) -> dict[str, Any]:
    return {
        "source_url": result.canonical_url,
        "canonical_url": result.canonical_url,
        "resolved_url": result.final_url,
        "final_url": result.final_url,
        "redirect_chain": result.redirect_chain,
        "http_content_type": result.content_type,
        "content_type": result.content_type,
        "content_disposition": result.content_disposition,
        "etag": result.etag,
        "last_modified": result.last_modified,
        "downloaded_bytes": result.downloaded_bytes,
        "sha256": result.sha256,
        "fetched_at": result.fetched_at,
    }


class IngestionService:
    def __init__(
        self,
        *,
        ingestion_root: Path,
        normalized_root: Path,
        lightrag_adapter: LightRAGIngestionAdapter | None = None,
        audit_runner: Callable | None = None,
        storage_reader: LightRAGStorageReader | None = None,
        downloader: UrlDownloader | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.ingestion_root = ingestion_root
        self.normalized_root = normalized_root
        self.lightrag_adapter = lightrag_adapter or LightRAGIngestionAdapter(client=LightRAGHttpClient())
        self.audit_runner = audit_runner or run_post_ingestion_audit
        self.storage_reader = storage_reader or LightRAGStorageReader(Path(config.LIGHTRAG_STORAGE_DIR))
        self._now = now or (lambda: datetime.now(timezone.utc))
        if downloader is None:
            downloader = UrlDownloader(now=self._now)
        self.downloader = downloader
        self.url_artifact_dir = ingestion_root / "url-artifacts"

    @classmethod
    def from_config(cls) -> "IngestionService":
        ingestion_root = Path(config.INGESTION_ROOT)
        normalized_root = Path(config.INGESTION_NORMALIZED_DIR)
        return cls(ingestion_root=ingestion_root, normalized_root=normalized_root)

    def submit(self, *, source_kind: str, source_uri: str) -> dict:
        if source_kind == "url":
            return self._submit_url(source_uri)
        if source_kind != "file":
            raise ValueError("only file and URL ingestion are supported")
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
        existing_record = pg.get_ingestion_source(source_key)
        classification = classify_source(existing_record, incoming_hash=content_hash)
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

        if classification.change == SourceChange.UPDATED:
            pg.create_ingestion_job(job_id=job_id, source_key=source_key, status=SourceStatus.DISCOVERED)
            return {
                "job_id": job_id,
                "source_key": source_key,
                "status": SourceStatus.DISCOVERED,
                "run_in_background": True,
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

    def _submit_url(self, source_uri: str) -> dict:
        try:
            canonical = canonicalize_url(source_uri)
        except SourceValidationError as exc:
            raise ValueError(f"{exc.code}: {exc}") from exc

        source_key = build_url_source_key(canonical)
        job_id = str(uuid4())
        existing = pg.get_ingestion_source(source_key)
        if existing is None:
            stub = SourceRecord(
                source_key=source_key,
                source_kind="url",
                source_uri=canonical,
                content_hash=None,
                status=SourceStatus.DISCOVERED,
                source_metadata={"active_download": None, "latest_attempt": None},
            )
            pg.upsert_ingestion_source(stub)
        pg.create_ingestion_job(
            job_id=job_id,
            source_key=source_key,
            status=SourceStatus.DISCOVERED,
        )
        return {
            "job_id": job_id,
            "source_key": source_key,
            "status": SourceStatus.DISCOVERED,
            "run_in_background": True,
        }

    def get_job(self, job_id: str) -> dict | None:
        return pg.get_ingestion_job(job_id)

    def process_job(self, job_id: str, *, requested_url: str | None = None) -> None:
        job = pg.get_ingestion_job(job_id)
        if job is None:
            return
        source_key = job["source_key"]
        record = pg.get_ingestion_source(source_key)
        if record is None:
            return
        if record.source_kind == "url":
            self._process_url_job(
                job_id,
                record,
                requested_url or record.source_uri,
            )
            return
        source_path = self.ingestion_root / record.source_uri
        try:
            current_hash = content_sha256(source_path)
            if record.status == SourceStatus.PROCESSED and record.content_hash != current_hash:
                self._process_update(job_id, record, source_path, current_hash)
                return
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

            storage_snapshot = self.storage_reader.snapshot()
            report = self.audit_runner(
                job_id=job_id,
                source_key=source_key,
                lightrag_document_id=record.lightrag_document_id,
                storage_snapshot=storage_snapshot,
                allowed_entity_types=set(ENTITY_TYPES),
            )
            audit_payload = report.model_dump(mode="json")
            if report.critical_issues:
                self._set_status(
                    record,
                    job_id,
                    SourceStatus.FAILED_AUDIT,
                    audit=audit_payload,
                    error=IngestionError(
                        code="AUDIT_FAILED",
                        message="Post-ingestion audit found critical issues",
                        stage=SourceStatus.AUDITING.value,
                    ).model_dump(),
                )
            else:
                self._set_status(record, job_id, SourceStatus.PROCESSED, audit=audit_payload)
        except SourceValidationError as exc:
            self._fail(record, job_id, exc.code, str(exc), SourceStatus.PROCESSING)
        except DocprepError as exc:
            self._fail(record, job_id, exc.code, str(exc), SourceStatus.PROCESSING)
        except LightRAGAdapterError as exc:
            self._fail(record, job_id, exc.code, str(exc), SourceStatus.INGESTING)
        except StorageParseError as exc:
            report = build_storage_parse_error_report(
                job_id=job_id,
                source_key=source_key,
                error=exc,
            )
            audit_payload = report.model_dump(mode="json")
            self._set_status(
                record,
                job_id,
                SourceStatus.FAILED_AUDIT,
                audit=audit_payload,
                error=IngestionError(
                    code="AUDIT_FAILED",
                    message="Post-ingestion audit encountered a storage parse error",
                    stage=SourceStatus.AUDITING.value,
                ).model_dump(),
            )

    def _process_url_job(
        self,
        job_id: str,
        record: SourceRecord,
        requested_url: str,
    ) -> None:
        # Same-URL and cross-URL duplicate/update classification is Task 4.
        # Until then this is only a defensive invariant: a source that already
        # carries active content must not strand its scheduled job in a
        # non-terminal state, so it is failed with a stable code instead of
        # silently returning.
        if record.content_hash is not None:
            self._fail_job(
                job_id,
                "URL_SOURCE_ALREADY_ACTIVE",
                "URL source already has active content",
                SourceStatus.PROCESSING,
            )
            return

        download_result: UrlDownloadResult | None = None
        try:
            self._set_status(record, job_id, SourceStatus.PROCESSING)
            download_result = self.downloader.download(
                requested_url,
                artifact_dir=self.url_artifact_dir,
            )
            if download_result.raw_artifact_path is None:
                raise URLDownloadError("URL_INVALID")

            source_type = _url_source_type(download_result)
            normalized = asyncio.run(
                normalize_downloaded_artifact(
                    Path(download_result.raw_artifact_path),
                    output_root=self.normalized_root,
                    source_identity=download_result.canonical_url,
                    source_type=source_type,
                    native_metadata=_docprep_native_metadata(download_result),
                )
            )
            record.parser = normalized.parser
            record.normalization_version = "lightrag_docprep"
            record.normalized_markdown_path = str(normalized.markdown_path)
            record.normalized_json_path = str(normalized.json_path)
            self._set_status(record, job_id, SourceStatus.NORMALIZED)
            self._set_status(record, job_id, SourceStatus.INGESTING)
            ingest_result = self.lightrag_adapter.ingest_markdown(
                normalized.markdown_path,
                source_key=record.source_key,
            )
            record.lightrag_document_id = ingest_result.document_id
            self._set_status(record, job_id, SourceStatus.AUDITING)

            storage_snapshot = self.storage_reader.snapshot()
            report = self.audit_runner(
                job_id=job_id,
                source_key=record.source_key,
                lightrag_document_id=record.lightrag_document_id,
                storage_snapshot=storage_snapshot,
                allowed_entity_types=set(ENTITY_TYPES),
            )
            audit_payload = report.model_dump(mode="json")
            if report.critical_issues:
                record.source_metadata = self._url_metadata_payload(
                    requested_url=requested_url,
                    canonical_url=download_result.canonical_url,
                    result=download_result,
                    job_id=job_id,
                    terminal_outcome=SourceStatus.FAILED_AUDIT.value,
                    error_code="AUDIT_FAILED",
                    activated=False,
                )
                self._set_status(
                    record,
                    job_id,
                    SourceStatus.FAILED_AUDIT,
                    audit=audit_payload,
                    error=IngestionError(
                        code="AUDIT_FAILED",
                        message="Post-ingestion audit found critical issues",
                        stage=SourceStatus.AUDITING.value,
                    ).model_dump(),
                )
            else:
                record.content_hash = download_result.sha256
                record.source_metadata = self._url_metadata_payload(
                    requested_url=requested_url,
                    canonical_url=download_result.canonical_url,
                    result=download_result,
                    job_id=job_id,
                    terminal_outcome=SourceStatus.PROCESSED.value,
                    error_code=None,
                    activated=True,
                )
                self._set_status(
                    record,
                    job_id,
                    SourceStatus.PROCESSED,
                    audit=audit_payload,
                )
        except URLDownloadError as exc:
            self._fail_url_job(
                job_id,
                record,
                requested_url,
                download_result,
                exc.code,
                "URL download failed",
                SourceStatus.PROCESSING,
            )
        except DocprepError as exc:
            self._fail_url_job(
                job_id,
                record,
                requested_url,
                download_result,
                exc.code,
                "Document preprocessing failed",
                SourceStatus.PROCESSING,
            )
        except LightRAGAdapterError as exc:
            self._fail_url_job(
                job_id,
                record,
                requested_url,
                download_result,
                exc.code,
                "LightRAG ingestion failed",
                SourceStatus.INGESTING,
            )
        except StorageParseError:
            self._fail_url_job(
                job_id,
                record,
                requested_url,
                download_result,
                "AUDIT_PARSE_FAILED",
                "Post-ingestion audit storage parse failed",
                SourceStatus.AUDITING,
            )

    def _fail_url_job(
        self,
        job_id: str,
        record: SourceRecord,
        requested_url: str,
        download_result: UrlDownloadResult | None,
        code: str,
        message: str,
        stage: SourceStatus,
    ) -> None:
        canonical_url = (
            download_result.canonical_url
            if download_result is not None
            else record.source_uri
        )
        record.source_metadata = self._url_metadata_payload(
            requested_url=requested_url,
            canonical_url=canonical_url,
            result=download_result,
            job_id=job_id,
            terminal_outcome=SourceStatus.FAILED.value,
            error_code=code,
            activated=False,
        )
        self._fail(record, job_id, code, message, stage)

    def _url_metadata_payload(
        self,
        *,
        requested_url: str,
        canonical_url: str,
        result: UrlDownloadResult | None,
        job_id: str,
        terminal_outcome: str | None,
        error_code: str | None,
        activated: bool,
    ) -> dict[str, Any]:
        if result is None:
            active_download = None
            attempt = {
                "requested_url": requested_url,
                "canonical_url": canonical_url,
                "final_url": None,
                "redirect_chain": [],
                "content_type": None,
                "content_disposition": None,
                "etag": None,
                "last_modified": None,
                "downloaded_bytes": None,
                "sha256": None,
                "raw_artifact_path": None,
                "fetched_at": self._now_rfc3339(),
                "job_id": job_id,
                "terminal_outcome": terminal_outcome,
                "error_code": error_code,
            }
        else:
            download = {
                "requested_url": requested_url,
                "canonical_url": result.canonical_url,
                "final_url": result.final_url,
                "redirect_chain": result.redirect_chain,
                "content_type": result.content_type,
                "content_disposition": result.content_disposition,
                "etag": result.etag,
                "last_modified": result.last_modified,
                "downloaded_bytes": result.downloaded_bytes,
                "sha256": result.sha256,
                "raw_artifact_path": result.raw_artifact_path,
                "fetched_at": result.fetched_at,
            }
            active_download = download if activated else None
            attempt = {
                **download,
                "job_id": job_id,
                "terminal_outcome": terminal_outcome,
                "error_code": error_code,
            }
        return {"active_download": active_download, "latest_attempt": attempt}

    def _now_rfc3339(self) -> str:
        return (
            self._now()
            .astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    def _process_update(
        self,
        job_id: str,
        active_record: SourceRecord,
        source_path: Path,
        current_hash: str,
    ) -> None:
        previous_record = active_record.model_copy(deep=True)
        try:
            self._set_job_status(job_id, SourceStatus.PROCESSING)
            normalized = asyncio.run(normalize_document(source_path, output_root=self.normalized_root))
            self._set_job_status(job_id, SourceStatus.NORMALIZED)
            self._set_job_status(job_id, SourceStatus.INGESTING)
            if previous_record.lightrag_document_id:
                self.lightrag_adapter.delete_document(previous_record.lightrag_document_id)
            result = self.lightrag_adapter.ingest_markdown(normalized.markdown_path, source_key=previous_record.source_key)

            candidate_record = previous_record.model_copy(
                update={
                    "content_hash": current_hash,
                    "status": SourceStatus.AUDITING,
                    "parser": normalized.parser,
                    "normalization_version": "lightrag_docprep",
                    "normalized_markdown_path": str(normalized.markdown_path),
                    "normalized_json_path": str(normalized.json_path),
                    "lightrag_document_id": result.document_id,
                    "last_error_code": None,
                    "last_error_message": None,
                }
            )
            self._set_job_status(job_id, SourceStatus.AUDITING)

            storage_snapshot = self.storage_reader.snapshot()
            report = self.audit_runner(
                job_id=job_id,
                source_key=previous_record.source_key,
                lightrag_document_id=result.document_id,
                storage_snapshot=storage_snapshot,
                allowed_entity_types=set(ENTITY_TYPES),
            )
            audit_payload = report.model_dump(mode="json")

            if not report.critical_issues:
                self._set_status(candidate_record, job_id, SourceStatus.PROCESSED, audit=audit_payload)
            else:
                # Do not upsert candidate_record for a failed audit.
                self._restore_previous_after_update_failure(
                    job_id,
                    previous_record,
                    None,
                    rejected_document_id=result.document_id,
                    job_status=SourceStatus.FAILED_AUDIT,
                    audit=audit_payload,
                    error_stage=SourceStatus.AUDITING,
                )
        except DocprepError as exc:
            self._fail_job(job_id, exc.code, str(exc), SourceStatus.PROCESSING)
        except LightRAGAdapterError as exc:
            if exc.code == "LIGHTRAG_INGESTION_FAILED":
                self._restore_previous_after_update_failure(job_id, previous_record, exc)
                return
            self._fail_job(job_id, exc.code, str(exc), SourceStatus.INGESTING)
        except StorageParseError as exc:
            report = build_storage_parse_error_report(
                job_id=job_id,
                source_key=previous_record.source_key,
                error=exc,
            )
            self._restore_previous_after_update_failure(
                job_id,
                previous_record,
                None,
                rejected_document_id=result.document_id,
                job_status=SourceStatus.FAILED_AUDIT,
                audit=report.model_dump(mode="json"),
                error_stage=SourceStatus.AUDITING,
            )

    def _restore_previous_after_update_failure(
        self,
        job_id: str,
        previous_record: SourceRecord,
        original_error: LightRAGAdapterError | None = None,
        *,
        rejected_document_id: str | None = None,
        job_status: SourceStatus = SourceStatus.FAILED,
        audit: dict | None = None,
        error_stage: SourceStatus = SourceStatus.INGESTING,
    ) -> None:
        if rejected_document_id is not None:
            try:
                self.lightrag_adapter.delete_document(rejected_document_id)
            except LightRAGAdapterError as delete_error:
                failed_record = previous_record.model_copy(
                    update={
                        "status": SourceStatus.FAILED,
                        "last_error_code": "UPDATE_ROLLBACK_FAILED",
                        "last_error_message": str(delete_error),
                    }
                )
                pg.upsert_ingestion_source(failed_record)
                self._set_job_status(
                    job_id,
                    SourceStatus.FAILED_AUDIT,
                    audit=audit,
                    error=IngestionError(
                        code="UPDATE_ROLLBACK_FAILED",
                        message=f"Failed to delete rejected LightRAG document {rejected_document_id}: {delete_error}",
                        stage=SourceStatus.AUDITING.value,
                    ).model_dump(),
                )
                return

        previous_markdown_path = Path(previous_record.normalized_markdown_path or "")
        if not previous_markdown_path.is_file():
            failed_record = previous_record.model_copy(
                update={
                    "status": SourceStatus.FAILED,
                    "last_error_code": "UPDATE_ROLLBACK_FAILED",
                    "last_error_message": "Previous normalized markdown artifact is unavailable",
                }
            )
            pg.upsert_ingestion_source(failed_record)
            if job_status == SourceStatus.FAILED_AUDIT:
                self._set_job_status(
                    job_id,
                    SourceStatus.FAILED_AUDIT,
                    audit=audit,
                    error=IngestionError(
                        code="UPDATE_ROLLBACK_FAILED",
                        message="Previous normalized markdown artifact is unavailable",
                        stage=error_stage.value,
                    ).model_dump(),
                )
            else:
                self._fail_job(
                    job_id,
                    "UPDATE_ROLLBACK_FAILED",
                    "Previous normalized markdown artifact is unavailable",
                    error_stage,
                )
            return

        try:
            restored = self.lightrag_adapter.ingest_markdown(
                previous_markdown_path,
                source_key=previous_record.source_key,
            )
        except LightRAGAdapterError as rollback_error:
            failed_record = previous_record.model_copy(
                update={
                    "status": SourceStatus.FAILED,
                    "last_error_code": "UPDATE_ROLLBACK_FAILED",
                    "last_error_message": str(rollback_error),
                }
            )
            pg.upsert_ingestion_source(failed_record)
            if job_status == SourceStatus.FAILED_AUDIT:
                self._set_job_status(
                    job_id,
                    SourceStatus.FAILED_AUDIT,
                    audit=audit,
                    error=IngestionError(
                        code="UPDATE_ROLLBACK_FAILED",
                        message=str(rollback_error),
                        stage=error_stage.value,
                    ).model_dump(),
                )
            else:
                self._fail_job(job_id, "UPDATE_ROLLBACK_FAILED", str(rollback_error), error_stage)
            return

        restored_record = previous_record.model_copy(
            update={
                "status": SourceStatus.PROCESSED,
                "lightrag_document_id": restored.document_id,
                "last_error_code": None,
                "last_error_message": None,
            }
        )
        pg.upsert_ingestion_source(restored_record)

        if job_status == SourceStatus.FAILED_AUDIT:
            self._set_job_status(
                job_id,
                SourceStatus.FAILED_AUDIT,
                audit=audit,
                error=IngestionError(
                    code="AUDIT_FAILED",
                    message="Post-ingestion audit found critical issues",
                    stage=SourceStatus.AUDITING.value,
                ).model_dump(),
            )
        else:
            self._fail_job(
                job_id,
                original_error.code if original_error else "UPDATE_ROLLBACK_FAILED",
                f"{original_error}; previous version restored" if original_error else "Previous version restored",
                error_stage,
            )

    def _set_status(
        self,
        record: SourceRecord,
        job_id: str,
        status: SourceStatus,
        *,
        audit: dict | None = None,
        error: dict | None = None,
    ) -> None:
        record.status = status
        record.last_error_code = None
        record.last_error_message = None
        pg.upsert_ingestion_source(record)
        self._set_job_status(job_id, status, audit=audit, error=error)

    def _set_job_status(
        self,
        job_id: str,
        status: SourceStatus,
        *,
        audit: dict | None = None,
        error: dict | None = None,
    ) -> None:
        pg.set_ingestion_job_status(job_id, status, audit=audit, error=error)

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
        self._fail_job(job_id, code, message, stage)

    def _fail_job(
        self,
        job_id: str,
        code: str,
        message: str,
        stage: SourceStatus,
    ) -> None:
        pg.set_ingestion_job_status(
            job_id,
            SourceStatus.FAILED,
            error=IngestionError(code=code, message=message, stage=stage.value).model_dump(),
        )
