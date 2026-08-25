from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import asyncio
import logging
import shutil
from typing import Any, Callable

from polymerhus.app.clients import pg
from polymerhus.app.config import config
from polymerhus.ingestion.audit import (
    LightRAGStorageReader,
    StorageParseError,
    build_storage_parse_error_report,
    run_post_ingestion_audit,
)
from polymerhus.ingestion.contracts import (
    IngestionError,
    SourceChange,
    SourceRecord,
    SourceStatus,
    classify_source,
)
from polymerhus.ingestion.docprep_adapter import (
    DocprepError,
    NormalizedDocument,
    normalize_document,
    normalize_downloaded_artifact,
)
from polymerhus.ingestion.lightrag_adapter import LightRAGAdapterError, LightRAGIngestionAdapter
from polymerhus.ingestion.source_identity import (
    SourceValidationError,
    build_source_key,
    build_url_source_key,
    canonicalize_url,
    content_sha256,
    validate_source_path,
)
from polymerhus.ingestion.url_downloader import URLDownloadError, UrlDownloadResult, UrlDownloader
from polymerhus.lightrag.client import LightRAGHttpClient
from polymerhus.lightrag.ontology import ENTITY_TYPES


logger = logging.getLogger(__name__)

_GENERIC_INTERNAL_ERROR_CODE = "INTERNAL_PROCESSING_FAILED"
_GENERIC_INTERNAL_ERROR_MESSAGE = "Internal processing failed"
_CANDIDATE_CLEANUP_FAILED_MESSAGE = "Candidate cleanup failed; previous version preserved"
_NEW_URL_CANDIDATE_CLEANUP_FAILED_MESSAGE = "Candidate cleanup failed"
_PREVIOUS_VERSION_RESTORE_FAILED_MESSAGE = "Previous version restore failed"
_CANDIDATE_DOCUMENT_ID_MISSING_CODE = "LIGHTRAG_DOCUMENT_ID_MISSING"
_CANDIDATE_DOCUMENT_ID_MISSING_MESSAGE = "LightRAG did not return a valid document ID"
_CANDIDATE_DOCUMENT_ID_CONFLICT_CODE = "LIGHTRAG_DOCUMENT_ID_CONFLICT"
_CANDIDATE_DOCUMENT_ID_CONFLICT_MESSAGE = "LightRAG returned a document ID that is already active"

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
        self.lightrag_adapter = lightrag_adapter or LightRAGIngestionAdapter(
            client=LightRAGHttpClient(),
            poll_interval_seconds=config.LIGHTRAG_POLL_INTERVAL_SECONDS,
            timeout_seconds=config.LIGHTRAG_INGESTION_TIMEOUT_SECONDS,
        )
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
        if record.status == SourceStatus.PROCESSED and record.content_hash is not None:
            self._process_url_recrawl(job_id, record, requested_url)
            return

        download_result: UrlDownloadResult | None = None
        candidate_document_id: str | None = None
        normalized: NormalizedDocument | None = None
        stage = SourceStatus.PROCESSING
        try:
            self._set_job_status(job_id, SourceStatus.PROCESSING)
            download_result = self.downloader.download(
                requested_url,
                artifact_dir=self.url_artifact_dir,
            )
            if download_result.raw_artifact_path is None:
                raise URLDownloadError("URL_INVALID")

            duplicate_owner = pg.get_processed_ingestion_source_by_hash(download_result.sha256)
            if duplicate_owner is not None:
                record.status = SourceStatus.SKIPPED_DUPLICATE
                # A cross-URL duplicate keeps its own canonical identity with a
                # NULL content_hash and no copied activation fields: the
                # candidate SHA is recorded only in latest_attempt. Copying the
                # owner's parser/artifact/LightRAG fields would imply that this
                # source is active, which it is not.
                record.content_hash = None
                record.parser = None
                record.parser_version = None
                record.normalization_version = None
                record.lightrag_document_id = None
                record.normalized_markdown_path = None
                record.normalized_json_path = None
                record.last_error_code = None
                record.last_error_message = None
                record.source_metadata = self._url_metadata_payload(
                    requested_url=requested_url,
                    canonical_url=download_result.canonical_url,
                    result=download_result,
                    job_id=job_id,
                    terminal_outcome=SourceStatus.SKIPPED_DUPLICATE.value,
                    error_code=None,
                    activated=False,
                )
                pg.upsert_ingestion_source(record)
                self._set_job_status(job_id, SourceStatus.SKIPPED_DUPLICATE)
                return

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
            candidate_markdown_path = normalized.markdown_path
            candidate_json_path = normalized.json_path
            candidate_parser = normalized.parser
            self._set_job_status(job_id, SourceStatus.NORMALIZED)
            stage = SourceStatus.NORMALIZED
            self._set_job_status(job_id, SourceStatus.INGESTING)
            stage = SourceStatus.INGESTING
            ingest_result = self.lightrag_adapter.ingest_markdown(
                candidate_markdown_path,
                source_key=record.source_key,
            )
            candidate_document_id = ingest_result.document_id
            self._set_job_status(job_id, SourceStatus.AUDITING)
            stage = SourceStatus.AUDITING

            storage_snapshot = self.storage_reader.snapshot()
            report = self.audit_runner(
                job_id=job_id,
                source_key=record.source_key,
                lightrag_document_id=candidate_document_id,
                storage_snapshot=storage_snapshot,
                allowed_entity_types=set(ENTITY_TYPES),
            )
            audit_payload = report.model_dump(mode="json")
            if report.critical_issues:
                self._reject_new_url_candidate(
                    job_id=job_id,
                    record=record,
                    requested_url=requested_url,
                    download_result=download_result,
                    candidate_document_id=candidate_document_id,
                    audit=audit_payload,
                    public_code="AUDIT_FAILED",
                    public_message="Post-ingestion audit found critical issues",
                    terminal_outcome=SourceStatus.FAILED_AUDIT.value,
                )
                return

            record.content_hash = download_result.sha256
            record.parser = candidate_parser
            record.normalization_version = "lightrag_docprep"
            record.normalized_markdown_path = str(candidate_markdown_path)
            record.normalized_json_path = str(candidate_json_path)
            record.lightrag_document_id = candidate_document_id
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
        except Exception:
            logger.exception("Unexpected error processing URL job %s", job_id)
            try:
                self._fail_url_job(
                    job_id,
                    record,
                    requested_url,
                    download_result,
                    _GENERIC_INTERNAL_ERROR_CODE,
                    _GENERIC_INTERNAL_ERROR_MESSAGE,
                    stage,
                )
            except Exception:
                logger.exception("Could not persist terminal state for URL job %s", job_id)
                raise

    def _reject_new_url_candidate(
        self,
        *,
        job_id: str,
        record: SourceRecord,
        requested_url: str,
        download_result: UrlDownloadResult | None,
        candidate_document_id: str | None,
        audit: dict,
        public_code: str,
        public_message: str,
        terminal_outcome: str,
    ) -> None:
        """Reject a brand-new URL candidate after a critical audit.

        The rejected candidate LightRAG document is deleted when its ID is
        known, every activation-derived source field is left null, and the
        sanitized ``FAILED_AUDIT`` terminal state carries only the allowed
        attempt/audit provenance. A cleanup failure reuses the existing stable
        cleanup error code and sanitized messaging.
        """
        cleanup_failed = False
        if candidate_document_id is not None:
            try:
                self.lightrag_adapter.delete_document(candidate_document_id)
            except Exception:
                logger.exception(
                    "Rejected candidate cleanup failed for URL job %s",
                    job_id,
                )
                cleanup_failed = True

        attempt_error_code = "UPDATE_ROLLBACK_FAILED" if cleanup_failed else public_code
        sanitized = record.model_copy(
            update={
                "status": SourceStatus.FAILED_AUDIT,
                "content_hash": None,
                "parser": None,
                "parser_version": None,
                "normalization_version": None,
                "lightrag_document_id": None,
                "normalized_markdown_path": None,
                "normalized_json_path": None,
                "last_error_code": None,
                "last_error_message": None,
                "source_metadata": self._url_metadata_payload(
                    requested_url=requested_url,
                    canonical_url=(
                        download_result.canonical_url
                        if download_result is not None
                        else record.source_uri
                    ),
                    result=download_result,
                    job_id=job_id,
                    terminal_outcome=terminal_outcome,
                    error_code=attempt_error_code,
                    activated=False,
                ),
            }
        )
        pg.upsert_ingestion_source(sanitized)

        error_code = "UPDATE_ROLLBACK_FAILED" if cleanup_failed else public_code
        error_message = (
            _NEW_URL_CANDIDATE_CLEANUP_FAILED_MESSAGE if cleanup_failed else public_message
        )
        self._set_job_status(
            job_id,
            SourceStatus.FAILED_AUDIT,
            audit=audit,
            error=IngestionError(
                code=error_code,
                message=error_message,
                stage=SourceStatus.AUDITING.value,
            ).model_dump(),
        )

    def _process_url_recrawl(
        self,
        job_id: str,
        record: SourceRecord,
        requested_url: str,
    ) -> None:
        """Reclassify an already-active URL source after a fresh download.

        Unchanged content refreshes fetch/provenance metadata and skips as a
        duplicate. Changed content becomes a staged update candidate: the
        candidate is ingested under a distinct staging identity while the old
        LightRAG document still exists, audited, and the old document is
        deleted only after a clean audit.
        """
        previous_record = record.model_copy(deep=True)
        download_result: UrlDownloadResult | None = None
        candidate_document_id: str | None = None
        candidate_output_root: Path | None = None
        candidate_ingested = False
        old_deletion_attempted = False
        old_deleted = False
        stage = SourceStatus.PROCESSING
        try:
            self._set_job_status(job_id, SourceStatus.PROCESSING)
            download_result = self.downloader.download(
                requested_url,
                artifact_dir=self.url_artifact_dir,
            )
            if download_result.raw_artifact_path is None:
                raise URLDownloadError("URL_INVALID")

            if download_result.sha256 == previous_record.content_hash:
                refreshed = previous_record.model_copy(
                    update={
                        "source_metadata": self._url_metadata_payload(
                            requested_url=requested_url,
                            canonical_url=download_result.canonical_url,
                            result=download_result,
                            job_id=job_id,
                            terminal_outcome=SourceStatus.SKIPPED_DUPLICATE.value,
                            error_code=None,
                            activated=True,
                        ),
                    }
                )
                pg.upsert_ingestion_source(refreshed)
                self._set_job_status(job_id, SourceStatus.SKIPPED_DUPLICATE)
                return

            source_type = _url_source_type(download_result)
            candidate_output_root = self._candidate_normalized_root()
            normalized = asyncio.run(
                normalize_downloaded_artifact(
                    Path(download_result.raw_artifact_path),
                    output_root=candidate_output_root,
                    source_identity=download_result.canonical_url,
                    source_type=source_type,
                    native_metadata=_docprep_native_metadata(download_result),
                )
            )
            stage = SourceStatus.NORMALIZED
            self._set_job_status(job_id, SourceStatus.NORMALIZED)
            stage = SourceStatus.INGESTING
            self._set_job_status(job_id, SourceStatus.INGESTING)
            staging_source_key = self._staging_source_key(previous_record.source_key)
            ingest_result = self.lightrag_adapter.ingest_markdown(
                normalized.markdown_path,
                source_key=staging_source_key,
            )
            candidate_document_id = ingest_result.document_id
            if not isinstance(candidate_document_id, str) or not candidate_document_id.strip():
                self._record_url_attempt_failure(
                    job_id,
                    previous_record,
                    requested_url,
                    download_result,
                    _CANDIDATE_DOCUMENT_ID_MISSING_CODE,
                    _CANDIDATE_DOCUMENT_ID_MISSING_MESSAGE,
                    SourceStatus.INGESTING,
                    candidate_output_root=candidate_output_root,
                )
                return
            candidate_document_id = candidate_document_id.strip()
            if (
                previous_record.lightrag_document_id
                and candidate_document_id == previous_record.lightrag_document_id
            ):
                # Never delete the shared ID: it is the active document. The
                # candidate may nevertheless have replaced its remote content,
                # so restore from the preserved old artifact using the existing
                # update rollback path.
                self._compensate_url_update(
                    job_id=job_id,
                    previous_record=previous_record,
                    requested_url=requested_url,
                    download_result=download_result,
                    candidate_document_id=None,
                    code=_CANDIDATE_DOCUMENT_ID_CONFLICT_CODE,
                    message=_CANDIDATE_DOCUMENT_ID_CONFLICT_MESSAGE,
                    stage=SourceStatus.INGESTING,
                    candidate_output_root=candidate_output_root,
                )
                return
            candidate_ingested = True
            stage = SourceStatus.AUDITING
            self._set_job_status(job_id, SourceStatus.AUDITING)

            storage_snapshot = self.storage_reader.snapshot()
            report = self.audit_runner(
                job_id=job_id,
                source_key=previous_record.source_key,
                lightrag_document_id=candidate_document_id,
                storage_snapshot=storage_snapshot,
                allowed_entity_types=set(ENTITY_TYPES),
            )
            audit_payload = report.model_dump(mode="json")

            if report.critical_issues:
                self._reject_url_candidate(
                    job_id=job_id,
                    previous_record=previous_record,
                    requested_url=requested_url,
                    download_result=download_result,
                    candidate_document_id=candidate_document_id,
                    job_status=SourceStatus.FAILED_AUDIT,
                    audit=audit_payload,
                    public_code="AUDIT_FAILED",
                    public_message="Post-ingestion audit found critical issues",
                    terminal_outcome=SourceStatus.FAILED_AUDIT.value,
                    candidate_output_root=candidate_output_root,
                )
                return

            if previous_record.lightrag_document_id:
                old_deletion_attempted = True
                self.lightrag_adapter.delete_document(previous_record.lightrag_document_id)
            old_deleted = True

            candidate_record = previous_record.model_copy(
                update={
                    "content_hash": download_result.sha256,
                    "status": SourceStatus.PROCESSED,
                    "parser": normalized.parser,
                    "normalization_version": "lightrag_docprep",
                    "normalized_markdown_path": str(normalized.markdown_path),
                    "normalized_json_path": str(normalized.json_path),
                    "lightrag_document_id": candidate_document_id,
                    "last_error_code": None,
                    "last_error_message": None,
                    "source_metadata": self._url_metadata_payload(
                        requested_url=requested_url,
                        canonical_url=download_result.canonical_url,
                        result=download_result,
                        job_id=job_id,
                        terminal_outcome=SourceStatus.PROCESSED.value,
                        error_code=None,
                        activated=True,
                    ),
                }
            )
            pg.upsert_ingestion_source(candidate_record)
            self._set_job_status(job_id, SourceStatus.PROCESSED, audit=audit_payload)
        except URLDownloadError as exc:
            self._record_url_attempt_failure(
                job_id,
                previous_record,
                requested_url,
                download_result,
                exc.code,
                "URL download failed",
                SourceStatus.PROCESSING,
                candidate_output_root=candidate_output_root,
            )
            return
        except DocprepError as exc:
            self._record_url_attempt_failure(
                job_id,
                previous_record,
                requested_url,
                download_result,
                exc.code,
                "Document preprocessing failed",
                SourceStatus.PROCESSING,
                candidate_output_root=candidate_output_root,
            )
            return
        except LightRAGAdapterError as exc:
            self._handle_url_update_expected_failure(
                job_id=job_id,
                previous_record=previous_record,
                requested_url=requested_url,
                download_result=download_result,
                candidate_document_id=candidate_document_id,
                candidate_ingested=candidate_ingested,
                old_deletion_attempted=old_deletion_attempted,
                old_deleted=old_deleted,
                error=exc,
                stage=stage,
                candidate_output_root=candidate_output_root,
            )
        except StorageParseError as exc:
            report = build_storage_parse_error_report(
                job_id=job_id,
                source_key=previous_record.source_key,
                error=exc,
            )
            self._reject_url_candidate(
                job_id=job_id,
                previous_record=previous_record,
                requested_url=requested_url,
                download_result=download_result,
                candidate_document_id=candidate_document_id,
                job_status=SourceStatus.FAILED_AUDIT,
                audit=report.model_dump(mode="json"),
                public_code="AUDIT_FAILED",
                public_message="Post-ingestion audit encountered a storage parse error",
                terminal_outcome=SourceStatus.FAILED_AUDIT.value,
                candidate_output_root=candidate_output_root,
            )
        except Exception:
            logger.exception("Unexpected error processing URL update job %s", job_id)
            try:
                self._handle_url_update_unexpected(
                    job_id=job_id,
                    previous_record=previous_record,
                    requested_url=requested_url,
                    download_result=download_result,
                    candidate_document_id=candidate_document_id,
                    candidate_ingested=candidate_ingested,
                    old_deletion_attempted=old_deletion_attempted,
                    old_deleted=old_deleted,
                    stage=stage,
                    candidate_output_root=candidate_output_root,
                )
            except Exception:
                logger.exception("URL update compensation failed for job %s", job_id)
                raise

    @staticmethod
    def _staging_source_key(source_key: str) -> str:
        """Build a distinct staging identity so the candidate can coexist with
        the old document in LightRAG. The adapter derives its upload filename
        from this key, so the candidate always gets a different document."""
        return f"{source_key}#candidate-{uuid4().hex}"

    def _reject_url_candidate(
        self,
        *,
        job_id: str,
        previous_record: SourceRecord,
        requested_url: str,
        download_result: UrlDownloadResult | None,
        candidate_document_id: str | None,
        job_status: SourceStatus,
        audit: dict | None,
        public_code: str,
        public_message: str,
        terminal_outcome: str,
        candidate_output_root: Path | None = None,
    ) -> None:
        """Reject a staged candidate while the old activation stays intact."""
        previous_active_download = (previous_record.source_metadata or {}).get("active_download")
        cleanup_failed = False
        if candidate_document_id is not None:
            try:
                self.lightrag_adapter.delete_document(candidate_document_id)
            except Exception:
                logger.exception("Candidate cleanup failed for URL job %s", job_id)
                cleanup_failed = True
        self._cleanup_candidate_normalized_artifacts(candidate_output_root)

        attempt_error_code = "UPDATE_ROLLBACK_FAILED" if cleanup_failed else public_code
        kept = previous_record.model_copy(
            update={
                "source_metadata": self._url_metadata_payload(
                    requested_url=requested_url,
                    canonical_url=(
                        download_result.canonical_url
                        if download_result is not None
                        else previous_record.source_uri
                    ),
                    result=download_result,
                    job_id=job_id,
                    terminal_outcome=terminal_outcome,
                    error_code=attempt_error_code,
                    activated=False,
                    preserve_active_download=previous_active_download,
                ),
            }
        )
        pg.upsert_ingestion_source(kept)
        error_code = "UPDATE_ROLLBACK_FAILED" if cleanup_failed else public_code
        error_message = (
            _CANDIDATE_CLEANUP_FAILED_MESSAGE if cleanup_failed else public_message
        )
        self._set_job_status(
            job_id,
            job_status,
            audit=audit,
            error=IngestionError(
                code=error_code,
                message=error_message,
                stage=SourceStatus.AUDITING.value,
            ).model_dump(),
        )

    def _handle_url_update_expected_failure(
        self,
        *,
        job_id: str,
        previous_record: SourceRecord,
        requested_url: str,
        download_result: UrlDownloadResult | None,
        candidate_document_id: str | None,
        candidate_ingested: bool,
        old_deletion_attempted: bool,
        old_deleted: bool,
        error: LightRAGAdapterError,
        stage: SourceStatus,
        candidate_output_root: Path | None = None,
    ) -> None:
        """Map an expected LightRAG failure with stage-aware compensation."""
        if not candidate_ingested:
            self._record_url_attempt_failure(
                job_id,
                previous_record,
                requested_url,
                download_result,
                error.code,
                "LightRAG ingestion failed",
                stage,
                candidate_output_root=candidate_output_root,
            )
            return

        if old_deleted or old_deletion_attempted:
            self._compensate_url_update(
                job_id=job_id,
                previous_record=previous_record,
                requested_url=requested_url,
                download_result=download_result,
                candidate_document_id=candidate_document_id,
                code=error.code,
                message="LightRAG update failed; previous version restored",
                stage=stage,
                candidate_output_root=candidate_output_root,
            )
            return

        self._reject_url_candidate(
            job_id=job_id,
            previous_record=previous_record,
            requested_url=requested_url,
            download_result=download_result,
            candidate_document_id=candidate_document_id,
            job_status=SourceStatus.FAILED,
            audit=None,
            public_code=error.code,
            public_message="LightRAG update failed; previous version preserved",
            terminal_outcome=SourceStatus.FAILED.value,
            candidate_output_root=candidate_output_root,
        )

    def _handle_url_update_unexpected(
        self,
        *,
        job_id: str,
        previous_record: SourceRecord,
        requested_url: str,
        download_result: UrlDownloadResult | None,
        candidate_document_id: str | None,
        candidate_ingested: bool,
        old_deletion_attempted: bool,
        old_deleted: bool,
        stage: SourceStatus,
        candidate_output_root: Path | None = None,
    ) -> None:
        """Handle an unexpected exception with stage-aware compensation."""
        if not candidate_ingested:
            self._record_url_attempt_failure(
                job_id,
                previous_record,
                requested_url,
                download_result,
                _GENERIC_INTERNAL_ERROR_CODE,
                _GENERIC_INTERNAL_ERROR_MESSAGE,
                stage,
                candidate_output_root=candidate_output_root,
            )
            return

        if old_deleted or old_deletion_attempted:
            self._compensate_url_update(
                job_id=job_id,
                previous_record=previous_record,
                requested_url=requested_url,
                download_result=download_result,
                candidate_document_id=candidate_document_id,
                code=_GENERIC_INTERNAL_ERROR_CODE,
                message=_GENERIC_INTERNAL_ERROR_MESSAGE,
                stage=stage,
                candidate_output_root=candidate_output_root,
            )
            return

        self._reject_url_candidate(
            job_id=job_id,
            previous_record=previous_record,
            requested_url=requested_url,
            download_result=download_result,
            candidate_document_id=candidate_document_id,
            job_status=SourceStatus.FAILED,
            audit=None,
            public_code=_GENERIC_INTERNAL_ERROR_CODE,
            public_message=_GENERIC_INTERNAL_ERROR_MESSAGE,
            terminal_outcome=SourceStatus.FAILED.value,
            candidate_output_root=candidate_output_root,
        )

    def _compensate_url_update(
        self,
        *,
        job_id: str,
        previous_record: SourceRecord,
        requested_url: str,
        download_result: UrlDownloadResult | None,
        candidate_document_id: str | None,
        code: str,
        message: str,
        stage: SourceStatus,
        candidate_output_root: Path | None = None,
    ) -> None:
        """Restore the old document and registry state after old-document side
        effects have begun. Reuses the existing update rollback flow."""
        previous_active_download = (previous_record.source_metadata or {}).get("active_download")
        canonical_url = (
            download_result.canonical_url
            if download_result is not None
            else previous_record.source_uri
        )
        self._cleanup_candidate_normalized_artifacts(candidate_output_root)
        self._restore_previous_after_update_failure(
            job_id,
            previous_record,
            None,
            rejected_document_id=candidate_document_id,
            job_status=SourceStatus.FAILED,
            error_stage=stage,
            restored_updates={
                "source_metadata": self._url_metadata_payload(
                    requested_url=requested_url,
                    canonical_url=canonical_url,
                    result=download_result,
                    job_id=job_id,
                    terminal_outcome=SourceStatus.FAILED.value,
                    error_code=code,
                    activated=False,
                    preserve_active_download=previous_active_download,
                ),
            },
            failure_code=code,
            failure_message=message,
        )

    def _record_url_attempt_failure(
        self,
        job_id: str,
        record: SourceRecord,
        requested_url: str,
        download_result: UrlDownloadResult | None,
        code: str,
        message: str,
        stage: SourceStatus,
        candidate_output_root: Path | None = None,
    ) -> None:
        """Record a failed recrawl attempt without disturbing the active state.

        The active download, content hash, status, and LightRAG references are
        kept exactly as they were; only latest_attempt records the rejected
        fetch so failed attempt metadata can never overwrite active_download.
        """
        canonical_url = (
            download_result.canonical_url
            if download_result is not None
            else record.source_uri
        )
        preserved_active_download = (record.source_metadata or {}).get("active_download")
        record.source_metadata = self._url_metadata_payload(
            requested_url=requested_url,
            canonical_url=canonical_url,
            result=download_result,
            job_id=job_id,
            terminal_outcome=SourceStatus.FAILED.value,
            error_code=code,
            activated=False,
            preserve_active_download=preserved_active_download,
        )
        pg.upsert_ingestion_source(record)
        self._cleanup_candidate_normalized_artifacts(candidate_output_root)
        self._fail_job(job_id, code, message, stage)

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
        preserve_active_download: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if result is None:
            active_download = preserve_active_download
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
            active_download = download if activated else preserve_active_download
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

    def _candidate_normalized_root(self) -> Path:
        """Return a unique staging directory for one update candidate.

        The directory is distinct on every call, so candidate normalization
        can never collide with the active normalized artifact even when a
        different raw document normalizes to the same output identity.
        """
        return self.normalized_root / f"candidate-{uuid4().hex}"

    def _cleanup_candidate_normalized_artifacts(self, output_root: Path | None) -> None:
        """Remove incomplete candidate staging data after a failed update.

        Only the unique staging directory generated for one candidate is
        removed; the active artifact lives elsewhere and is never touched.
        """
        if output_root is None:
            return
        try:
            shutil.rmtree(output_root, ignore_errors=True)
        except Exception:
            logger.exception(
                "Candidate normalized artifact cleanup failed for %s",
                output_root,
            )

    def _process_update(
        self,
        job_id: str,
        active_record: SourceRecord,
        source_path: Path | None = None,
        current_hash: str | None = None,
        *,
        prepared: NormalizedDocument | None = None,
        candidate_updates: dict[str, Any] | None = None,
        restored_metadata_builder: Callable[[str, str | None], dict[str, Any] | None] | None = None,
    ) -> None:
        previous_record = active_record.model_copy(deep=True)

        def _restored_updates(terminal_outcome: str, error_code: str | None) -> dict[str, Any] | None:
            if restored_metadata_builder is None:
                return None
            return restored_metadata_builder(terminal_outcome, error_code)

        candidate_output_root: Path | None = None
        try:
            self._set_job_status(job_id, SourceStatus.PROCESSING)
            if prepared is None:
                if source_path is None or current_hash is None:
                    raise ValueError("file update requires source_path and current_hash")
                candidate_output_root = self._candidate_normalized_root()
                normalized = asyncio.run(
                    normalize_document(source_path, output_root=candidate_output_root)
                )
            else:
                if current_hash is None:
                    raise ValueError("prepared update requires current_hash")
                normalized = prepared
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
                    **(candidate_updates or {}),
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
                self._cleanup_candidate_normalized_artifacts(candidate_output_root)
                self._restore_previous_after_update_failure(
                    job_id,
                    previous_record,
                    None,
                    rejected_document_id=result.document_id,
                    job_status=SourceStatus.FAILED_AUDIT,
                    audit=audit_payload,
                    error_stage=SourceStatus.AUDITING,
                    restored_updates=_restored_updates(
                        SourceStatus.FAILED_AUDIT.value,
                        "AUDIT_FAILED",
                    ),
                )
        except DocprepError as exc:
            self._cleanup_candidate_normalized_artifacts(candidate_output_root)
            self._fail_job(job_id, exc.code, str(exc), SourceStatus.PROCESSING)
        except LightRAGAdapterError as exc:
            self._cleanup_candidate_normalized_artifacts(candidate_output_root)
            if exc.code == "LIGHTRAG_INGESTION_FAILED":
                self._restore_previous_after_update_failure(
                    job_id,
                    previous_record,
                    exc,
                    restored_updates=_restored_updates(SourceStatus.FAILED.value, exc.code),
                )
                return
            self._fail_job(job_id, exc.code, str(exc), SourceStatus.INGESTING)
        except StorageParseError as exc:
            self._cleanup_candidate_normalized_artifacts(candidate_output_root)
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
                restored_updates=_restored_updates(
                    SourceStatus.FAILED_AUDIT.value,
                    "AUDIT_FAILED",
                ),
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
        restored_updates: dict[str, Any] | None = None,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> None:
        if rejected_document_id is not None:
            try:
                self.lightrag_adapter.delete_document(rejected_document_id)
            except Exception:
                logger.exception("Rejected document cleanup failed for job %s", job_id)
                failed_record = previous_record.model_copy(
                    update={
                        "status": SourceStatus.FAILED,
                        "last_error_code": "UPDATE_ROLLBACK_FAILED",
                        "last_error_message": _CANDIDATE_CLEANUP_FAILED_MESSAGE,
                        **(restored_updates or {}),
                    }
                )
                pg.upsert_ingestion_source(failed_record)
                self._set_job_status(
                    job_id,
                    SourceStatus.FAILED_AUDIT,
                    audit=audit,
                    error=IngestionError(
                        code="UPDATE_ROLLBACK_FAILED",
                        message=_CANDIDATE_CLEANUP_FAILED_MESSAGE,
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
                    **(restored_updates or {}),
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
        except Exception:
            logger.exception("Previous version restore failed for job %s", job_id)
            failed_record = previous_record.model_copy(
                update={
                    "status": SourceStatus.FAILED,
                    "last_error_code": "UPDATE_ROLLBACK_FAILED",
                    "last_error_message": _PREVIOUS_VERSION_RESTORE_FAILED_MESSAGE,
                    **(restored_updates or {}),
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
                        message=_PREVIOUS_VERSION_RESTORE_FAILED_MESSAGE,
                        stage=error_stage.value,
                    ).model_dump(),
                )
            else:
                self._fail_job(
                    job_id,
                    "UPDATE_ROLLBACK_FAILED",
                    _PREVIOUS_VERSION_RESTORE_FAILED_MESSAGE,
                    error_stage,
                )
            return

        restored_record = previous_record.model_copy(
            update={
                "status": SourceStatus.PROCESSED,
                "lightrag_document_id": restored.document_id,
                "last_error_code": None,
                "last_error_message": None,
                **(restored_updates or {}),
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
                failure_code or (original_error.code if original_error else "UPDATE_ROLLBACK_FAILED"),
                failure_message or "Previous version restored",
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
