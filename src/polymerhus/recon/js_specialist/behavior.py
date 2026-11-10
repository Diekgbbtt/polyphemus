"""Evidence-linked behavioural records over the shared run notes."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

from polymerhus.recon.js_acquisition.code_access import CodeAccessService
from polymerhus.recon.js_acquisition.code_redaction import redact_window
from polymerhus.recon.js_intake import resolve_js_intake_reference
from polymerhus.recon.js_intake.cli import (
    MAX_BEHAVIOR_RECORD_BYTES, behavior_record_size, behavior_size_rejection,
)
from polymerhus.recon.js_specialist.notes import RunNotes
from polymerhus.recon.js_specialist.triage import EvidenceTriage, TriageError

_BEHAVIOR_EVENT_TYPES = {'behavior_save'}
_URL = re.compile(r"https?://[^\s'\"<>]+", re.I)
_AUTH_HEADER_VALUE = re.compile(
    r"(?i)(\bauthorization\s*:\s*(?:bearer|basic)\s+)\S+"
)

BehaviorText = Annotated[str, Field(min_length=1, max_length=512)]
BehaviorReadId = Annotated[str, Field(min_length=1, max_length=100)]
GapText = Annotated[str, Field(min_length=1, max_length=512)]


class BehaviorError(ValueError):
    def __init__(self, reason: str, *, details: dict | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}

    def as_payload(self) -> dict:
        return {'error': self.reason, **self.details}


class BehaviorStep(BaseModel):
    model_config = ConfigDict(extra='forbid')

    kind: Literal[
        'trigger',
        'input',
        'transform',
        'call',
        'request',
        'sink',
        'response',
        'error',
        'effect',
    ]
    text: BehaviorText
    read_ids: list[BehaviorReadId] = Field(min_length=1, max_length=8)

    @field_validator('text')
    @classmethod
    def _strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('empty_behavior_text')
        return value

    @field_validator('read_ids')
    @classmethod
    def _unique_read_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError('duplicate_behavior_read')
        return value


class BehaviorAssumption(BaseModel):
    model_config = ConfigDict(extra='forbid')

    text: BehaviorText
    status: Literal['supported', 'unverified']
    read_ids: list[BehaviorReadId] = Field(default_factory=list, max_length=8)

    @field_validator('text')
    @classmethod
    def _strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('empty_behavior_text')
        return value

    @field_validator('read_ids')
    @classmethod
    def _unique_and_supported(
        cls,
        value: list[str],
        info,
    ) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError('duplicate_behavior_read')
        if info.data.get('status') == 'supported' and not value:
            raise ValueError('supported_assumption_requires_read')
        return value


class BehaviorSubmission(BaseModel):
    model_config = ConfigDict(extra='forbid')

    question_ref: str = Field(min_length=1, max_length=100)
    steps: list[BehaviorStep] = Field(min_length=1, max_length=12)
    assumptions: list[BehaviorAssumption] = Field(
        default_factory=list,
        max_length=8,
    )
    gaps: list[GapText] = Field(default_factory=list, max_length=8)

    @field_validator('gaps')
    @classmethod
    def _strip_gaps(cls, value: list[str]) -> list[str]:
        cleaned = []
        for gap in value:
            gap = gap.strip()
            if not gap:
                raise ValueError('empty_behavior_gap')
            cleaned.append(gap)
        return cleaned


def _canonical(value) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')


def _redact_url(match: re.Match[str]) -> str:
    try:
        path = urlsplit(match.group(0)).path or '/'
    except ValueError:
        path = '/'
    return '[REDACTED:url]' + path


def _sanitize_text(text: str) -> tuple[str, int]:
    url_matches = list(_URL.finditer(text))
    value = _URL.sub(_redact_url, text)
    auth_matches = list(_AUTH_HEADER_VALUE.finditer(value))
    value = _AUTH_HEADER_VALUE.sub(
        lambda match: match.group(1) + '[REDACTED:credential]',
        value,
    )
    redacted = redact_window(value.encode('utf-8'), 0, len(value.encode('utf-8')))
    return (
        redacted.display,
        len(url_matches) + len(auth_matches) + redacted.redaction_count,
    )


def _behavior_id(scope, question_ref: str) -> str:
    return 'behavior_' + hashlib.sha256(
        _canonical({
            'project_id': scope.project_id,
            'run_id': scope.run_id,
            'context_ref': scope.context_ref,
            'question_ref': question_ref,
        })
    ).hexdigest()[:32]


class BehaviorReconstruction:
    def __init__(
        self,
        *,
        root=None,
        access: CodeAccessService | None = None,
        triage: EvidenceTriage | None = None,
        retention=None,
    ) -> None:
        self._root = root
        self._access = access or CodeAccessService(root=root)
        self._triage = triage or EvidenceTriage(
            root=root,
            access=self._access,
        )
        self._retention = retention

    def _notes(self, scope) -> RunNotes:
        return RunNotes(scope, root=self._root)

    def _question(self, *, reference: str, question_ref: str) -> dict:
        try:
            return self._triage.get_span(
                reference=reference,
                span_id=question_ref,
            )
        except TriageError as exc:
            raise BehaviorError(
                'behavior_question_not_found'
                if exc.reason == 'triage_span_not_found'
                else exc.reason
            ) from None

    def _validate_read_ids(
        self,
        *,
        reference: str,
        submission: BehaviorSubmission,
    ) -> None:
        receipts = {}
        invalid = []
        for group in ('steps', 'assumptions'):
            for index, item in enumerate(getattr(submission, group)):
                for read_index, read_id in enumerate(item.read_ids):
                    if read_id not in receipts:
                        receipts[read_id] = self._access.read_receipt(
                            reference=reference, read_id=read_id,
                        )
                    receipt = receipts[read_id]
                    if not receipt or receipt.get('delivery_status') != 'delivered':
                        invalid.append({'field': f'{group}[{index}].read_ids[{read_index}]',
                                        'reason': 'not_delivered'})
        if invalid:
            # Report submitted field positions, never receipt contents or foreign state.
            raise BehaviorError('behavior_read_not_delivered', details={
                'invalid_fields': invalid[:8], 'invalid_count': len(invalid),
            })

    @staticmethod
    def _sanitized_record(
        submission: BehaviorSubmission,
    ) -> tuple[dict, int]:
        redactions = 0
        steps = []
        for step in submission.steps:
            text, count = _sanitize_text(step.text)
            redactions += count
            steps.append({
                'kind': step.kind,
                'text': text,
                'read_ids': list(step.read_ids),
            })
        assumptions = []
        for assumption in submission.assumptions:
            text, count = _sanitize_text(assumption.text)
            redactions += count
            assumptions.append({
                'text': text,
                'status': assumption.status,
                'read_ids': list(assumption.read_ids),
            })
        gaps = []
        for gap in submission.gaps:
            text, count = _sanitize_text(gap)
            redactions += count
            gaps.append(text)
        return {
            'question_ref': submission.question_ref,
            'steps': steps,
            'assumptions': assumptions,
            'gaps': gaps,
        }, redactions

    def save(
        self,
        *,
        reference: str,
        record: dict,
        dependencies: list[dict] | None = None,
        retention_deadline: float | None = None,
    ) -> dict:
        if not isinstance(record, dict):
            raise BehaviorError('invalid_behavior_record')
        try:
            raw_size = behavior_record_size(record)
        except (TypeError, ValueError):
            raise BehaviorError('invalid_behavior_record') from None
        if raw_size > MAX_BEHAVIOR_RECORD_BYTES:
            details = behavior_size_rejection(raw_size)
            details.pop('error')
            raise BehaviorError('behavior_record_too_large', details=details)
        try:
            submission = BehaviorSubmission.model_validate(record)
        except ValidationError:
            raise BehaviorError('invalid_behavior_record') from None
        scope = resolve_js_intake_reference(reference)
        selected = self._question(
            reference=reference,
            question_ref=submission.question_ref,
        )
        self._validate_read_ids(reference=reference, submission=submission)
        sanitized, redaction_count = self._sanitized_record(submission)
        record_sha256 = hashlib.sha256(_canonical(sanitized)).hexdigest()
        behavior_id = _behavior_id(scope, submission.question_ref)
        notes = self._notes(scope)

        def build(records: list[dict]) -> dict:
            history = [
                item
                for item in records
                if item.get('event_type') == 'behavior_save'
                and item.get('behavior_id') == behavior_id
                and (item.get('context_ref') or '') == (scope.context_ref or '')
            ]
            if history:
                latest = max(
                    history,
                    key=lambda item: int(item.get('revision') or 0),
                )
                if latest.get('record_sha256') == record_sha256:
                    return {
                        'existing_record': latest,
                        'idempotent': True,
                    }
                revision = int(latest.get('revision') or 0) + 1
            else:
                revision = 1
            return {
                'record': {
                    'event_type': 'behavior_save',
                    'schema_version': 1,
                    'behavior_id': behavior_id,
                    'revision': revision,
                    'reconstruction_level': 'reconstructed',
                    'question_ref': submission.question_ref,
                    'question': selected['question'],
                    'priority': selected['priority'],
                    'lead_id': selected['lead_id'],
                    'record_sha256': record_sha256,
                    'redaction_policy': 'js-source-redaction-v1',
                    'redaction_count': redaction_count,
                    **sanitized,
                }
            }

        result = notes.append_typed_transaction(
            build,
            allow_sanitized_text=True,
        )
        if result.get('error'):
            raise BehaviorError(result['error'])
        value = result.get('record') or result.get('existing_record')
        saved = {
            **self._public_record(value),
            'idempotent': bool(result.get('idempotent')),
        }
        if self._retention is not None:
            try:
                saved['retention'] = self._retention.retain_after_save(
                    reference=reference,
                    behavior=saved,
                    dependencies=dependencies,
                    deadline=retention_deadline,
                )
            except Exception as exc:
                saved['retention'] = {
                    'status': 'gap',
                    'retained_count': 0,
                    'pending_count': 0,
                    'gap_count': 1,
                    'gaps': [{
                        'reason': getattr(
                            exc,
                            'reason',
                            'retention_service_failed',
                        )
                    }],
                    'transfer_requests': [],
                }
        return saved

    @staticmethod
    def _public_record(record: dict) -> dict:
        return {
            key: record.get(key)
            for key in (
                'behavior_id',
                'revision',
                'reconstruction_level',
                'question_ref',
                'question',
                'priority',
                'lead_id',
                'steps',
                'assumptions',
                'gaps',
                'record_sha256',
                'redaction_policy',
                'redaction_count',
                'created_at',
            )
            if key in record
        }

    def _retention_status(self, *, reference: str, record: dict) -> dict:
        if self._retention is None:
            return {
                'status': 'disabled',
                'retained_count': 0,
                'pending_count': 0,
                'gap_count': 0,
                'gaps': [],
            }
        try:
            return self._retention.status(
                reference=reference,
                behavior_id=record['behavior_id'],
                behavior_revision=int(record['revision']),
            )
        except Exception as exc:
            return {
                'status': 'gap',
                'retained_count': 0,
                'pending_count': 0,
                'gap_count': 1,
                'gaps': [{
                    'reason': getattr(
                        exc,
                        'reason',
                        'retention_status_unavailable',
                    )
                }],
            }

    @staticmethod
    def _view_id(records: list[dict]) -> str:
        return hashlib.sha256(_canonical([
            {
                'behavior_id': record['behavior_id'],
                'revision': record['revision'],
                'record_id': record['record_id'],
            }
            for record in records
        ])).hexdigest()[:16]

    @staticmethod
    def _cursor(context_ref: str, view_id: str, offset: int) -> str:
        body = json.dumps(
            {'offset': offset, 'view': view_id},
            separators=(',', ':'),
        ).encode()
        digest = hashlib.sha256(
            f'behavior\0{context_ref or ""}\0{view_id}'.encode() + body
        ).digest()[:8]
        return base64.urlsafe_b64encode(body + digest).decode().rstrip('=')

    @staticmethod
    def _offset(
        cursor: str | None,
        context_ref: str,
        view_id: str,
    ) -> int:
        if not cursor:
            return 0
        try:
            payload = base64.urlsafe_b64decode(
                cursor + '=' * (-len(cursor) % 4)
            )
            body, observed = payload[:-8], payload[-8:]
            expected = hashlib.sha256(
                f'behavior\0{context_ref or ""}\0{view_id}'.encode() + body
            ).digest()[:8]
            value = json.loads(body)
            offset = int(value['offset'])
            if (
                observed != expected
                or value.get('view') != view_id
                or offset < 0
            ):
                raise ValueError
            return offset
        except Exception:
            raise BehaviorError('invalid_behavior_cursor') from None

    def list(
        self,
        *,
        reference: str,
        limit: int = 5,
        cursor: str | None = None,
    ) -> dict:
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit <= 0
        ):
            raise BehaviorError('invalid_behavior_limit')
        limit = min(limit, 10)
        scope = resolve_js_intake_reference(reference)
        history = self._notes(scope).typed_records(
            event_types=_BEHAVIOR_EVENT_TYPES,
        )
        latest_by_id = {}
        for record in history:
            behavior_id = str(record.get('behavior_id') or '')
            if not behavior_id:
                continue
            prior = latest_by_id.get(behavior_id)
            if (
                prior is None
                or int(record.get('revision') or 0)
                > int(prior.get('revision') or 0)
            ):
                latest_by_id[behavior_id] = record
        current = sorted(
            latest_by_id.values(),
            key=lambda item: (
                {'high': 0, 'normal': 1, 'low': 2}.get(
                    item.get('priority'),
                    9,
                ),
                item.get('created_at') or 0,
                item.get('behavior_id') or '',
            ),
        )
        view_id = self._view_id(current)
        offset = self._offset(cursor, scope.context_ref, view_id)
        window = current[offset : offset + limit]
        next_offset = offset + len(window)
        return {
            'behaviors': [
                {
                    **self._public_record(record),
                    'retention': self._retention_status(
                        reference=reference,
                        record=record,
                    ),
                }
                for record in window
            ],
            'total': len(current),
            'next_cursor': (
                self._cursor(scope.context_ref, view_id, next_offset)
                if next_offset < len(current)
                else None
            ),
            'coverage': {
                'behavior_count': len(current),
                'with_gaps': sum(bool(record.get('gaps')) for record in current),
                'open_assumptions': sum(
                    assumption.get('status') == 'unverified'
                    for record in current
                    for assumption in (record.get('assumptions') or [])
                ),
            },
        }


__all__ = [
    'BehaviorError',
    'BehaviorReconstruction',
    'MAX_BEHAVIOR_RECORD_BYTES',
]
