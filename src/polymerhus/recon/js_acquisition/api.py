"""Exec-invoked broker routes for bounded JavaScript acquisition."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from polymerhus.recon.js_acquisition.service import (
    AcquisitionError,
    AcquisitionService,
)
from polymerhus.recon.js_acquisition.recovery import (
    RecoveryError,
    SourceMapRecovery,
)
from polymerhus.recon.js_acquisition.structure_service import (
    StructureError,
    StructureService,
)
from polymerhus.recon.js_intake import (
    InvalidJsIntakeReference,
    JsIntakeLeadNotFound,
)


class _ConfirmBody(BaseModel):
    lead_id: str
    size: int
    sha256: str
    work_file_ref: str
    model_config = ConfigDict(extra="forbid")


class _FailBody(BaseModel):
    lead_id: str
    failure_reason: str
    model_config = ConfigDict(extra="forbid")


class _RecoveryConfirmBody(BaseModel):
    source_id: str
    size: int
    sha256: str
    work_file_ref: str
    model_config = ConfigDict(extra="forbid")


class _RecoveryFailBody(BaseModel):
    source_id: str
    failure_reason: str
    model_config = ConfigDict(extra="forbid")


def _reference_or_403(reference: str | None) -> str:
    if not reference:
        raise HTTPException(
            status_code=403,
            detail="missing or invalid JavaScript intake reference",
        )
    return reference


def _failure_response(lead_id: str, exc: AcquisitionError) -> JSONResponse:
    if exc.status_code in {401, 403}:
        status = exc.status_code
    elif exc.reason == "file_too_large":
        status = 413
    elif exc.reason == "quota_exhausted":
        status = 409
    elif exc.reason == "auth_context_unavailable":
        status = 403
    else:
        status = 422
    return JSONResponse(
        {
            "lead_id": lead_id,
            "status": "failed",
            "failure_reason": exc.reason,
        },
        status_code=status,
    )


def build_router(
    *,
    service: AcquisitionService | None = None,
    recovery: SourceMapRecovery | None = None,
    structure: StructureService | None = None,
) -> APIRouter:
    acquisition = service or AcquisitionService()
    recovery_service = recovery or SourceMapRecovery(
        acquisition=acquisition
    )
    structure_service = structure or StructureService()
    router = APIRouter(tags=["recon-js-acquisition"])

    @router.get("/recon/js-analysis/acquire/{lead_id}")
    def acquire(
        lead_id: str,
        reference: str | None = Header(
            default=None, alias="X-JS-Intake-Reference"
        ),
    ):
        scoped_reference = _reference_or_403(reference)
        try:
            result = acquisition.fetch(
                reference=scoped_reference, lead_id=lead_id
            )
        except InvalidJsIntakeReference as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except JsIntakeLeadNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except AcquisitionError as exc:
            return _failure_response(lead_id, exc)

        run_id = result.work_file_ref.split("/")[-2]
        metadata = result.public_metadata()
        return Response(
            content=result.body,
            media_type=result.content_type,
            headers={
                "X-JS-Run-Id": run_id,
                "X-JS-Status": metadata["status"],
                "X-JS-Size": str(metadata["size"]),
                "X-JS-SHA256": metadata["sha256"],
                "X-JS-Content-Type": metadata["content_type"],
                "X-JS-Work-File-Ref": metadata["work_file_ref"],
                "Cache-Control": "no-store",
            },
        )

    @router.post("/recon/js-analysis/confirm")
    def confirm(
        body: _ConfirmBody,
        reference: str | None = Header(
            default=None, alias="X-JS-Intake-Reference"
        ),
    ) -> dict:
        scoped_reference = _reference_or_403(reference)
        try:
            return acquisition.confirm(
                reference=scoped_reference,
                lead_id=body.lead_id,
                size=body.size,
                sha256=body.sha256,
                work_file_ref=body.work_file_ref,
            )
        except InvalidJsIntakeReference as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except JsIntakeLeadNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except AcquisitionError as exc:
            return _failure_response(body.lead_id, exc)

    @router.post("/recon/js-analysis/fail")
    def fail(
        body: _FailBody,
        reference: str | None = Header(
            default=None, alias="X-JS-Intake-Reference"
        ),
    ) -> dict:
        scoped_reference = _reference_or_403(reference)
        try:
            return acquisition.fail(
                reference=scoped_reference,
                lead_id=body.lead_id,
                failure_reason=body.failure_reason,
            )
        except InvalidJsIntakeReference as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except JsIntakeLeadNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    @router.post("/recon/js-analysis/recovery/start/{lead_id}")
    async def recovery_start(
        lead_id: str,
        request: Request,
        reference: str | None = Header(
            default=None, alias="X-JS-Intake-Reference"
        ),
        work_sha256: str = Header(default="", alias="X-JS-Work-SHA256"),
    ) -> dict:
        scoped_reference = _reference_or_403(reference)
        body = await request.body()
        import hashlib

        if (
            not work_sha256
            or hashlib.sha256(body).hexdigest() != work_sha256
        ):
            raise HTTPException(422, "acquired_source_mismatch")
        try:
            result = recovery_service.recover_from_source(
                reference=scoped_reference,
                lead_id=lead_id,
                js_bytes=body,
            )
        except InvalidJsIntakeReference as exc:
            raise HTTPException(403, str(exc)) from None
        except JsIntakeLeadNotFound as exc:
            raise HTTPException(404, str(exc)) from None
        except RecoveryError as exc:
            raise HTTPException(422, exc.reason) from None
        result["source_count"] = len(result.get("sources", []))
        result.pop("sources", None)
        return result

    @router.get("/recon/js-analysis/recovery/artifact/{source_id}")
    def recovery_artifact(
        source_id: str,
        reference: str | None = Header(
            default=None, alias="X-JS-Intake-Reference"
        ),
    ) -> Response:
        scoped_reference = _reference_or_403(reference)
        try:
            body = recovery_service.read_source_artifact(
                reference=scoped_reference, source_id=source_id
            )
            metadata = recovery_service.get_source(
                reference=scoped_reference, source_id=source_id
            )
        except RecoveryError as exc:
            raise HTTPException(422, exc.reason) from None
        return Response(
            content=body,
            media_type="application/octet-stream",
            headers={
                "X-JS-Source-Id": source_id,
                "X-JS-Source-SHA256": str(metadata["content_sha256"]),
                "X-JS-Source-Size": str(metadata["size"]),
                "X-JS-Work-File-Ref": str(metadata["work_file_ref"]),
                "Cache-Control": "no-store",
            },
        )

    @router.post("/recon/js-analysis/recovery/confirm")
    def recovery_confirm(
        body: _RecoveryConfirmBody,
        reference: str | None = Header(
            default=None, alias="X-JS-Intake-Reference"
        ),
    ) -> dict:
        scoped_reference = _reference_or_403(reference)
        try:
            return recovery_service.confirm_source(
                reference=scoped_reference,
                source_id=body.source_id,
                size=body.size,
                sha256=body.sha256,
                work_file_ref=body.work_file_ref,
            )
        except RecoveryError as exc:
            raise HTTPException(422, exc.reason) from None

    @router.post("/recon/js-analysis/recovery/fail")
    def recovery_fail(
        body: _RecoveryFailBody,
        reference: str | None = Header(
            default=None, alias="X-JS-Intake-Reference"
        ),
    ) -> dict:
        scoped_reference = _reference_or_403(reference)
        try:
            return recovery_service.fail_source(
                reference=scoped_reference,
                source_id=body.source_id,
                failure_reason=body.failure_reason,
            )
        except RecoveryError as exc:
            raise HTTPException(422, exc.reason) from None

    @router.post("/recon/js-analysis/structure/start/{lead_id}")
    async def structure_start(
        lead_id: str,
        request: Request,
        reference: str | None = Header(
            default=None, alias="X-JS-Intake-Reference"
        ),
        work_sha256: str = Header(default="", alias="X-JS-Work-SHA256"),
        remaining_seconds: str = Header(
            default="20",
            alias="X-JS-Remaining-Seconds",
        ),
    ) -> dict:
        scoped_reference = _reference_or_403(reference)
        body = await request.body()
        import hashlib

        if (
            not work_sha256
            or hashlib.sha256(body).hexdigest() != work_sha256
        ):
            raise HTTPException(422, "acquired_source_mismatch")
        if len(body) > 8 * 1024 * 1024:
            raise HTTPException(413, "structure_input_too_large")
        try:
            deadline_s = min(20.0, float(remaining_seconds))
        except ValueError:
            raise HTTPException(422, "invalid_structure_deadline") from None
        if deadline_s <= 0:
            raise HTTPException(422, "structure_deadline_exhausted")
        try:
            return structure_service.structure_from_source(
                reference=scoped_reference,
                lead_id=lead_id,
                source_bytes=body,
                deadline_s=deadline_s,
            )
        except InvalidJsIntakeReference as exc:
            raise HTTPException(403, str(exc)) from None
        except JsIntakeLeadNotFound as exc:
            raise HTTPException(404, str(exc)) from None
        except StructureError as exc:
            if exc.reason == "structure_reference_invalid":
                status = 403
            elif exc.reason == "structure_lead_not_found":
                status = 404
            else:
                status = 422
            raise HTTPException(status, exc.reason) from None

    return router


router = build_router()
