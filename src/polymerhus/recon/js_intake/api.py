"""Read-only HTTP bridge reached by the JavaScript specialist through Exec."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query

from polymerhus.recon.js_intake.reader import (
    InvalidJsIntakeReference,
    JsIntakeLeadNotFound,
    JsIntakeReader,
)


class JsIntakeExecBridge:
    """Thin adapter over the reader; no path or URL is accepted from the model."""

    def __init__(self, *, root=None) -> None:
        self._reader = JsIntakeReader(root=root)

    def list(
        self,
        *,
        reference: str,
        cursor: str | None = None,
        limit: int = 25,
    ) -> dict:
        return self._reader.list(reference=reference, cursor=cursor, limit=limit)

    def get(self, *, reference: str, lead_id: str) -> dict:
        return self._reader.get(reference=reference, lead_id=lead_id)


def build_router(*, root=None) -> APIRouter:
    bridge = JsIntakeExecBridge(root=root)
    router = APIRouter(tags=["recon-js-intake"])

    def reference_or_403(reference: str | None) -> str:
        if not reference:
            raise HTTPException(
                status_code=403,
                detail="missing or invalid JavaScript intake reference",
            )
        return reference

    @router.get("/recon/js-intake/leads")
    def list_leads(
        reference: str | None = Header(
            default=None, alias="X-JS-Intake-Reference"
        ),
        cursor: str | None = Query(default=None),
        limit: int = Query(default=25, ge=1),
    ) -> dict:
        scoped_reference = reference_or_403(reference)
        try:
            return bridge.list(
                reference=scoped_reference,
                cursor=cursor,
                limit=limit,
            )
        except InvalidJsIntakeReference as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None

    @router.get("/recon/js-intake/leads/{lead_id}")
    def get_lead(
        lead_id: str,
        reference: str | None = Header(
            default=None, alias="X-JS-Intake-Reference"
        ),
    ) -> dict:
        scoped_reference = reference_or_403(reference)
        try:
            return bridge.get(reference=scoped_reference, lead_id=lead_id)
        except InvalidJsIntakeReference as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from None
        except JsIntakeLeadNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None

    return router


router = build_router()
