"""Scoped adapters reached through the Kali CLI, not model-facing tools."""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field, ConfigDict, ValidationError
from typing import Literal

from polymerhus.app.llm.skills import SkillStore, build_load_skill_tool, skills_for_role
from polymerhus.recon.js_acquisition.scan_store import ScanStore
from polymerhus.recon.js_acquisition.recovery import SourceMapRecovery
from polymerhus.recon.js_acquisition.service import AcquisitionService
from polymerhus.recon.js_acquisition.code_access import (
    CodeAccessError,
    CodeAccessService,
)
from polymerhus.recon.js_acquisition.code_search import (
    CodeSearchError,
    CodeSearchService,
)
from polymerhus.recon.js_acquisition.structure_service import (
    StructureError,
    StructureService,
)
from polymerhus.recon.js_intake.reader import JsIntakeReader, resolve_js_intake_reference, InvalidJsIntakeReference, JsIntakeLeadNotFound
from polymerhus.recon.js_specialist.behavior import BehaviorError, BehaviorReconstruction
from polymerhus.recon.js_specialist.notes import RunNotes
from polymerhus.recon.js_specialist.triage import EvidenceTriage, TriageError
from polymerhus.recon.js_retention.service import JsRetentionService

SKILLS = skills_for_role('js_specialist')
JS_RETENTION_MAX_FILE_BYTES = 8 * 1024 * 1024


class DependencyNomination(BaseModel):
    selector_type: Literal['item', 'source', 'match']
    target: str = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=1, max_length=512)
    model_config = ConfigDict(extra='forbid')


class BridgeRequest(BaseModel):
    operation: Literal[
        'context',
        'skill',
        'reference',
        'inventory',
        'lead',
        'notes',
        'scan_input',
        'scan_reuse',
        'scan_results',
        'recovery_input',
        'recovery_sources',
        'recovery_source',
        'structure_input',
        'structure_items',
        'structure_item',
        'acquire_reference',
        'code_read_input',
        'code_read_confirm',
        'code_search_input',
        'code_search_results',
        'code_search_resume',
        'triage_select',
        'triage_update',
        'triage_list',
        'behavior_save',
        'behavior_list',
        'retention_status',
        'graph_candidates',
        'graph_note',
    ]
    name: str = Field(default='', max_length=80)
    target: str = Field(default='', max_length=80)
    lead_id: str = Field(default='', max_length=100)
    cursor: str | None = Field(default=None, max_length=256)
    limit: int = Field(default=5, ge=1, le=10)
    command: Literal['read', 'write'] = 'read'
    note: str = Field(default='', max_length=2048)
    mode: str = Field(default='', max_length=16)
    kind: str = Field(default='', max_length=16)
    selector_type: str = Field(default='', max_length=16)
    window_bytes: int = Field(default=4096, ge=1, le=8192)
    text: str = Field(default='', max_length=128)
    question: str = Field(default='', max_length=512)
    priority: str = Field(default='normal', max_length=16)
    state: str = Field(default='', max_length=16)
    read_id: str = Field(default='', max_length=100)
    reason: str = Field(default='', max_length=512)
    record: dict = Field(default_factory=dict)
    dependencies: list[DependencyNomination] = Field(
        default_factory=list,
        max_length=8,
    )
    behavior_id: str = Field(default='', max_length=100)
    behavior_revision: int = Field(default=0, ge=0)
    model_config = ConfigDict(extra='forbid')


class ScanSubmitRequest(BaseModel):
    lead_id: str = Field(max_length=100)
    mode: str = Field(max_length=16)
    result: dict
    model_config = ConfigDict(extra='forbid')


class CodeSearchSubmitRequest(BaseModel):
    lead_id: str = Field(max_length=100)
    text: str = Field(min_length=2, max_length=128)
    limit: int = Field(default=5, ge=1, le=10)
    contents: dict[str, str]
    max_examined_bytes: int = Field(
        default=64 * 1024 * 1024,
        ge=1,
        le=64 * 1024 * 1024,
    )
    deadline_s: float = Field(default=5.0, gt=0, le=5.0)
    resume_cursor: str | None = Field(default=None, max_length=512)
    model_config = ConfigDict(extra='forbid')


class SpecialistBridge:
    def __init__(self, *, root=None, retention=None):
        self.root = root
        self.reader = JsIntakeReader(root=root)
        self.skills = SkillStore(root_dir=root)
        self.scans = ScanStore(root=root)
        self.acquisition = AcquisitionService(root=root)
        self.recovery = SourceMapRecovery(
            root=root,
            acquisition=self.acquisition,
        )
        self.structure = StructureService(root=root)
        self.code_access = CodeAccessService(root=root)
        self.code_search = CodeSearchService(root=root)
        self.triage = EvidenceTriage(root=root, access=self.code_access)
        self.retention = retention or JsRetentionService(
            root=root,
            access=self.code_access,
        )
        self.behavior = BehaviorReconstruction(
            root=root,
            access=self.code_access,
            triage=self.triage,
            retention=self.retention,
        )

    @staticmethod
    def _selector(args: BridgeRequest) -> dict:
        if args.selector_type not in {'item', 'source', 'match'}:
            raise ValueError('unsupported_code_selector')
        return {'type': args.selector_type, 'id': args.target}

    def call(
        self,
        reference: str,
        payload: dict,
        *,
        deadline: float | None = None,
    ) -> dict:
        args = BridgeRequest.model_validate(payload)
        scope = resolve_js_intake_reference(reference)
        context = {'project_id': scope.project_id, 'run_id': scope.run_id,
                   'auth_context_ref': scope.context_ref,
                   'auth_context_label': 'authenticated' if scope.context_ref else 'anonymous',
                   'scope_domains': list(scope.scope_domains)}
        if args.operation == 'context':
            return {'context': context, 'skills': list(SKILLS)}
        if args.operation in {'skill', 'reference'}:
            if args.name not in SKILLS:
                raise ValueError('skill_not_in_specialist_roster')
            if args.operation == 'skill':
                content = build_load_skill_tool(project_id=scope.project_id, store=self.skills).invoke({'name': args.name})
            else:
                content = self.skills.read_reference(args.name, args.target, project_id=scope.project_id)
            if not content:
                return {'error': 'skill_or_reference_unavailable'}
            # Never silently truncate a procedure into apparently complete instructions.
            if len(content.encode()) > 12000:
                return {'error': 'skill_output_limit'}
            return {'content': content}
        if args.operation == 'inventory':
            return {'context': context, **self.reader.list(reference=reference, cursor=args.cursor, limit=args.limit)}
        if args.operation == 'lead':
            return {'context': context, **self.reader.get(reference=reference, lead_id=args.lead_id)}
        if args.operation == 'graph_candidates':
            from polymerhus.recon.control.js_graph_proposal import read_js_graph_candidates
            return read_js_graph_candidates(reference=reference, lead_id=args.lead_id,
                                             cursor=args.cursor, limit=args.limit, root=self.root)
        if args.operation == 'graph_note':
            from polymerhus.recon.control.js_graph_proposal import record_js_graph_annotation
            return record_js_graph_annotation(reference=reference, record=args.record, root=self.root)
        if args.operation == 'scan_input':
            self.reader.get_private(reference=reference, lead_id=args.lead_id)
            return self.scans.work_input(
                project_id=scope.project_id,
                run_id=scope.run_id,
                lead_id=args.lead_id,
                context_ref=scope.context_ref,
            )
        if args.operation == 'scan_reuse':
            self.reader.get_private(reference=reference, lead_id=args.lead_id)
            work_input = self.scans.work_input(
                project_id=scope.project_id,
                run_id=scope.run_id,
                lead_id=args.lead_id,
                context_ref=scope.context_ref,
            )
            scan = self.scans.get_scan(
                project_id=scope.project_id,
                run_id=scope.run_id,
                scan_key=args.target,
            )
            if (
                not scan
                or scan.get('status') != 'complete'
                or scan.get('source_sha256') != work_input['sha256']
            ):
                return {'reused': False}
            linked = self.scans.link_lead(
                project_id=scope.project_id,
                run_id=scope.run_id,
                lead_id=args.lead_id,
                context_ref=scope.context_ref,
                scan_key=args.target,
            )
            return {
                'reused': True,
                'scan_key': args.target,
                'status': linked['status'],
                'modes': scan.get('modes') or {},
            }
        if args.operation == 'scan_results':
            self.reader.get_private(reference=reference, lead_id=args.lead_id)
            return self.scans.read(
                project_id=scope.project_id,
                run_id=scope.run_id,
                lead_id=args.lead_id,
                mode=args.mode or None,
                cursor=args.cursor,
                limit=args.limit,
            )
        if args.operation == 'recovery_input':
            self.reader.get_private(reference=reference, lead_id=args.lead_id)
            return self.scans.work_input(
                project_id=scope.project_id,
                run_id=scope.run_id,
                lead_id=args.lead_id,
                context_ref=scope.context_ref,
            )
        if args.operation == 'recovery_sources':
            self.reader.get_private(reference=reference, lead_id=args.lead_id)
            return self.recovery.list_sources(
                reference=reference,
                lead_id=args.lead_id,
                cursor=args.cursor,
                limit=args.limit,
            )
        if args.operation == 'recovery_source':
            return self.recovery.get_source(
                reference=reference,
                source_id=args.target,
            )
        if args.operation == 'structure_input':
            self.reader.get_private(reference=reference, lead_id=args.lead_id)
            return self.scans.work_input(
                project_id=scope.project_id,
                run_id=scope.run_id,
                lead_id=args.lead_id,
                context_ref=scope.context_ref,
            )
        if args.operation == 'structure_items':
            self.reader.get_private(reference=reference, lead_id=args.lead_id)
            return self.structure.list_items(
                reference=reference,
                lead_id=args.lead_id,
                kind=args.kind or None,
                cursor=args.cursor,
                limit=args.limit,
            )
        if args.operation == 'structure_item':
            return self.structure.get_item(
                reference=reference,
                item_id=args.target,
            )
        if args.operation == 'acquire_reference':
            return self.structure.register_reference(
                reference=reference,
                item_id=args.target,
            )
        if args.operation == 'code_read_input':
            try:
                return self.code_access.read_target(
                    reference=reference,
                    selector=self._selector(args),
                )
            except CodeAccessError as exc:
                raise ValueError(exc.reason) from None
        if args.operation == 'code_read_confirm':
            try:
                return self.code_access.confirm_read(
                    reference=reference,
                    read_id=args.read_id,
                )
            except CodeAccessError as exc:
                raise ValueError(exc.reason) from None
        if args.operation == 'code_search_input':
            try:
                return self.code_search.source_inventory(
                    reference=reference,
                    lead_id=args.lead_id,
                    cursor=args.cursor,
                    limit=args.limit,
                )
            except CodeSearchError as exc:
                raise ValueError(exc.reason) from None
        if args.operation == 'code_search_results':
            try:
                return self.code_search.results(
                    reference=reference,
                    lead_id=args.lead_id,
                    text=args.text,
                    cursor=args.cursor,
                    limit=args.limit,
                )
            except CodeSearchError as exc:
                raise ValueError(exc.reason) from None
        if args.operation == 'code_search_resume':
            try:
                return self.code_search.resume_cursor(
                    reference=reference,
                    lead_id=args.lead_id,
                    text=args.text,
                    cursor=args.cursor or '',
                    limit=args.limit,
                )
            except CodeSearchError as exc:
                raise ValueError(exc.reason) from None
        if args.operation == 'triage_select':
            try:
                return self.triage.select(
                    reference=reference,
                    selector=self._selector(args),
                    question=args.question,
                    priority=args.priority,
                )
            except TriageError as exc:
                raise ValueError(exc.reason) from None
        if args.operation == 'triage_update':
            try:
                return self.triage.update(
                    reference=reference,
                    span_id=args.target,
                    state=args.state,
                    read_id=args.read_id,
                    reason=args.reason,
                )
            except TriageError as exc:
                raise ValueError(exc.reason) from None
        if args.operation == 'triage_list':
            try:
                return self.triage.list(
                    reference=reference,
                    limit=args.limit,
                    cursor=args.cursor,
                )
            except TriageError as exc:
                raise ValueError(exc.reason) from None
        if args.operation == 'behavior_save':
            return self.behavior.save(
                reference=reference,
                record=args.record,
                dependencies=[
                    dependency.model_dump()
                    for dependency in args.dependencies
                ],
                retention_deadline=deadline,
            )
        if args.operation == 'behavior_list':
            return self.behavior.list(
                reference=reference,
                limit=args.limit,
                cursor=args.cursor,
            )
        if args.operation == 'retention_status':
            return self.retention.status(
                reference=reference,
                behavior_id=args.behavior_id,
                behavior_revision=args.behavior_revision,
            )
        return RunNotes(scope, root=self.root).tool().invoke({'command': args.command, 'note': args.note})

    def submit_scan(
        self,
        reference: str,
        *,
        lead_id: str,
        mode: str,
        result: dict,
    ) -> dict:
        scope = resolve_js_intake_reference(reference)
        self.reader.get_private(reference=reference, lead_id=lead_id)
        return self.scans.submit_mode(
            project_id=scope.project_id,
            run_id=scope.run_id,
            lead_id=lead_id,
            context_ref=scope.context_ref,
            result=result,
            mode=mode,
        )

    def submit_search(
        self,
        reference: str,
        *,
        lead_id: str,
        text: str,
        limit: int,
        contents: dict[str, str],
        max_examined_bytes: int,
        deadline_s: float,
        resume_cursor: str | None = None,
    ) -> dict:
        import base64

        try:
            decoded = {
                source_id: base64.b64decode(value, validate=True)
                for source_id, value in contents.items()
            }
        except Exception:
            raise ValueError('invalid_search_content') from None
        return self.code_search.search_from_contents(
            reference=reference,
            lead_id=lead_id,
            text=text,
            contents=decoded,
            limit=limit,
            max_examined_bytes=max_examined_bytes,
            deadline_s=deadline_s,
            resume_cursor=resume_cursor,
        )


def build_router(*, root=None, retention=None):
    router = APIRouter(tags=['recon-js-specialist'])
    bridge = SpecialistBridge(root=root, retention=retention)

    @router.post('/recon/js-specialist/rpc')
    async def rpc(
        body: BridgeRequest,
        reference: str = Header(
            default='',
            alias='X-JS-Intake-Reference',
        ),
        remaining_s: float = Header(
            default=0,
            alias='X-JS-Remaining-Seconds',
        ),
    ):
        try:
            deadline = (
                time.monotonic() + remaining_s
                if remaining_s > 0
                else None
            )
            if deadline is None:
                result = bridge.call(reference, body.model_dump())
            else:
                result = bridge.call(
                    reference,
                    body.model_dump(),
                    deadline=deadline,
                )
            if (
                body.operation in {
                    'behavior_save',
                    'behavior_list',
                    'retention_status',
                    'graph_candidates',
                    'graph_note',
                }
                and len(
                    json.dumps(result, separators=(',', ':')).encode()
                ) > 16000
            ):
                raise HTTPException(413, 'behavior_response_limit')
            return result
        except BehaviorError as exc:
            raise HTTPException(422, exc.as_payload() if exc.details else exc.reason) from None
        except InvalidJsIntakeReference:
            raise HTTPException(403, 'unknown_or_expired_reference') from None
        except JsIntakeLeadNotFound:
            raise HTTPException(404, 'lead_outside_context') from None
        except ValueError as exc:
            raise HTTPException(
                422,
                getattr(exc, 'reason', 'invalid_specialist_request'),
            ) from None

    @router.post('/recon/js-specialist/scan/submit')
    def submit_scan(
        body: ScanSubmitRequest,
        reference: str = Header(default='', alias='X-JS-Intake-Reference'),
    ):
        try:
            return bridge.submit_scan(
                reference,
                lead_id=body.lead_id,
                mode=body.mode,
                result=body.result,
            )
        except InvalidJsIntakeReference:
            raise HTTPException(403, 'unknown_or_expired_reference') from None
        except JsIntakeLeadNotFound:
            raise HTTPException(404, 'lead_outside_context') from None
        except ValueError as exc:
            detail = getattr(exc, 'reason', 'invalid_scan_result')
            raise HTTPException(422, detail) from None

    @router.post('/recon/js-specialist/code/search/submit')
    async def submit_search(
        request: Request,
        reference: str = Header(default='', alias='X-JS-Intake-Reference'),
    ):
        try:
            payload = await request.json()
            body = CodeSearchSubmitRequest.model_validate(payload)
        except (ValueError, ValidationError):
            raise HTTPException(422, 'invalid_search_request') from None
        try:
            return bridge.submit_search(
                reference,
                lead_id=body.lead_id,
                text=body.text,
                limit=body.limit,
                contents=body.contents,
                max_examined_bytes=body.max_examined_bytes,
                deadline_s=body.deadline_s,
                resume_cursor=body.resume_cursor,
            )
        except InvalidJsIntakeReference:
            raise HTTPException(403, 'unknown_or_expired_reference') from None
        except ValueError as exc:
            raise HTTPException(
                422,
                getattr(exc, 'reason', str(exc) or 'invalid_search_request'),
            ) from None

    @router.post('/recon/js-specialist/code/read')
    async def read_code(
        request: Request,
        reference: str = Header(default='', alias='X-JS-Intake-Reference'),
        selector_type: str = Header(default='', alias='X-JS-Selector-Type'),
        selector_id: str = Header(default='', alias='X-JS-Selector-Id'),
        cursor: str = Header(default='', alias='X-JS-Code-Cursor'),
        window_bytes: int = Header(default=4096, alias='X-JS-Window-Bytes'),
    ):
        body = await request.body()
        if len(body) > 8 * 1024 * 1024:
            raise HTTPException(413, 'code_input_too_large')
        try:
            result = bridge.code_access.prepare_read(
                reference=reference,
                selector={'type': selector_type, 'id': selector_id},
                source_bytes=body,
                cursor=cursor or None,
                window_bytes=window_bytes,
            )
        except (InvalidJsIntakeReference, CodeAccessError) as exc:
            raise HTTPException(
                403 if isinstance(exc, InvalidJsIntakeReference) else 422,
                getattr(exc, 'reason', str(exc)),
            ) from None
        if len(json.dumps(result, separators=(',', ':')).encode()) > 16000:
            raise HTTPException(413, 'code_read_response_limit')
        return result

    @router.post('/recon/js-specialist/retention/transfer')
    async def retention_transfer(
        request: Request,
        reference: str = Header(
            default='',
            alias='X-JS-Intake-Reference',
        ),
        request_id: str = Header(
            default='',
            alias='X-JS-Retention-Request',
        ),
        remaining_s: float = Header(
            default=0,
            alias='X-JS-Remaining-Seconds',
        ),
    ):
        chunks = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > JS_RETENTION_MAX_FILE_BYTES:
                raise HTTPException(413, 'retention_transfer_too_large')
            chunks.append(chunk)
        try:
            result = bridge.retention.accept_transfer(
                reference=reference,
                request_id=request_id,
                body=b''.join(chunks),
                deadline=(
                    time.monotonic() + remaining_s
                    if remaining_s > 0
                    else None
                ),
            )
        except InvalidJsIntakeReference:
            raise HTTPException(403, 'unknown_or_expired_reference') from None
        except ValueError as exc:
            raise HTTPException(
                422,
                getattr(exc, 'reason', 'retention_transfer_failed'),
            ) from None
        if len(json.dumps(result, separators=(',', ':')).encode()) > 16000:
            raise HTTPException(413, 'retention_response_limit')
        return result
    return router
