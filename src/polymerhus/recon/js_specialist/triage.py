"""Typed shortlist state over the existing app-owned YAML notes algorithm."""

from __future__ import annotations

import base64
import hashlib
import json

from polymerhus.recon.js_acquisition.code_access import (
    CodeAccessError,
    CodeAccessService,
    DEFAULT_WINDOW_BYTES,
)
from polymerhus.recon.js_intake import resolve_js_intake_reference
from polymerhus.recon.js_specialist.notes import RunNotes


class TriageError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class EvidenceTriage:
    def __init__(
        self,
        *,
        root=None,
        access: CodeAccessService | None = None,
    ) -> None:
        self._root = root
        self._access = access or CodeAccessService(root=root)

    def _notes(self, scope) -> RunNotes:
        return RunNotes(scope, root=self._root)

    @staticmethod
    def _span_id(
        *,
        scope,
        selector: dict,
        question: str,
        priority: str,
        target: dict,
    ) -> str:
        return "span_" + hashlib.sha256(
            json.dumps(
                {
                    'project_id': scope.project_id,
                    'run_id': scope.run_id,
                    'context_ref': scope.context_ref,
                    'selector': selector,
                    'question': question,
                    'priority': priority,
                    'content_sha256': target['content_sha256'],
                    'range_start': target['range_start'],
                    'range_end': target['range_end'],
                },
                sort_keys=True,
                separators=(',', ':'),
            ).encode()
        ).hexdigest()[:32]

    def select(
        self,
        *,
        reference: str,
        selector: dict,
        question: str,
        priority: str,
    ) -> dict:
        question = question.strip()
        if not question or len(question) > 512:
            raise TriageError('invalid_triage_question')
        if priority not in {'high', 'normal', 'low'}:
            raise TriageError('invalid_triage_priority')
        scope = resolve_js_intake_reference(reference)
        try:
            target = self._access.read_target(
                reference=reference,
                selector=selector,
            )
        except CodeAccessError as exc:
            raise TriageError(exc.reason) from None
        span_id = self._span_id(
            scope=scope,
            selector=selector,
            question=question,
            priority=priority,
            target=target,
        )
        notes = self._notes(scope)
        records = notes.typed_records()
        for record in records:
            if (
                record.get('event_type') == 'triage_select'
                and record.get('span_id') == span_id
            ):
                return {
                    **self._public_span(record, records),
                    'idempotent': True,
                }
        focus_end = min(
            int(target['range_end']),
            int(target['range_start']) + DEFAULT_WINDOW_BYTES,
        )
        focus_sha256 = hashlib.sha256(
            (
                f"{target['content_sha256']}\0"
                f"{target['range_start']}\0{focus_end}"
            ).encode()
        ).hexdigest()
        record = notes.append_typed(
            {
                'event_type': 'triage_select',
                'span_id': span_id,
                'lead_id': target['lead_id'],
                'selector_type': selector['type'],
                'selector_id': selector['id'],
                'question': question,
                'priority': priority,
                'content_sha256': target['content_sha256'],
                'focus_sha256': focus_sha256,
                'start_byte': int(target['range_start']),
                'end_byte': focus_end,
                'kind': target['kind'],
                'state': 'discovered',
            }
        )
        if record.get('error'):
            raise TriageError(record['error'])
        return {**self._public_span(record, records + [record]), 'idempotent': False}

    def _selected(self, records: list[dict], span_id: str) -> dict:
        for record in records:
            if (
                record.get('event_type') == 'triage_select'
                and record.get('span_id') == span_id
            ):
                return record
        raise TriageError('triage_span_not_found')

    @staticmethod
    def _updates(records: list[dict], span_id: str) -> list[dict]:
        return [
            record
            for record in records
            if record.get('event_type') == 'triage_update'
            and record.get('span_id') == span_id
        ]

    def _public_span(self, selected: dict, records: list[dict]) -> dict:
        span_id = selected['span_id']
        updates = self._updates(records, span_id)
        latest = updates[-1] if updates else {}
        read_ids = [
            record['read_id']
            for record in updates
            if record.get('read_id')
        ]
        return {
            'span_id': span_id,
            'lead_id': selected['lead_id'],
            'selector': {
                'type': selected['selector_type'],
                'id': selected['selector_id'],
            },
            'question': selected['question'],
            'priority': selected['priority'],
            'kind': selected['kind'],
            'content_sha256': selected['content_sha256'],
            'focus_sha256': selected.get('focus_sha256'),
            'start_byte': selected['start_byte'],
            'end_byte': selected['end_byte'],
            'state': latest.get('state') or 'discovered',
            'reason': latest.get('reason'),
            'read_ids': list(dict.fromkeys(read_ids)),
        }

    def update(
        self,
        *,
        reference: str,
        span_id: str,
        state: str,
        read_id: str = '',
        reason: str = '',
    ) -> dict:
        if state not in {'inspected', 'deferred', 'unresolved'}:
            raise TriageError('invalid_triage_state')
        reason = reason.strip()
        if state in {'deferred', 'unresolved'} and not reason:
            raise TriageError('state_requires_reason')
        if state == 'inspected' and not read_id:
            raise TriageError('inspected_requires_read')
        scope = resolve_js_intake_reference(reference)
        notes = self._notes(scope)
        records = notes.typed_records()
        selected = self._selected(records, span_id)
        if state == 'inspected':
            delivered = self._access.validate_read_for_focus(
                reference=reference,
                read_id=read_id,
                focus={
                    'content_sha256': selected['content_sha256'],
                    'start_byte': selected['start_byte'],
                    'end_byte': selected['end_byte'],
                },
            )
            if not delivered:
                existing = self._access.read_receipt(
                    reference=reference,
                    read_id=read_id,
                )
                if existing and existing.get('delivery_status') != 'delivered':
                    raise TriageError('read_not_delivered')
                raise TriageError('read_does_not_cover_focus')
        updates = self._updates(records, span_id)
        if updates:
            latest = updates[-1]
            if (
                latest.get('state') == state
                and latest.get('read_id', '') == read_id
                and (latest.get('reason') or '') == reason
            ):
                return {
                    'span_id': span_id,
                    'state': state,
                    'idempotent': True,
                }
        record = notes.append_typed(
            {
                'event_type': 'triage_update',
                'span_id': span_id,
                'state': state,
                'read_id': read_id or None,
                'reason': reason or None,
            }
        )
        if record.get('error'):
            raise TriageError(record['error'])
        return {
            'span_id': span_id,
            'state': state,
            'idempotent': False,
        }

    def get_span(self, *, reference: str, span_id: str) -> dict:
        scope = resolve_js_intake_reference(reference)
        records = self._notes(scope).typed_records()
        selected = self._selected(records, span_id)
        return self._public_span(selected, records)

    @staticmethod
    def _cursor(context_ref: str, offset: int) -> str:
        body = json.dumps({'offset': offset}, separators=(',', ':')).encode()
        digest = hashlib.sha256(
            f'triage\0{context_ref or ""}'.encode() + body
        ).digest()[:8]
        return base64.urlsafe_b64encode(body + digest).decode().rstrip('=')

    @staticmethod
    def _offset(cursor: str | None, context_ref: str) -> int:
        if not cursor:
            return 0
        try:
            payload = base64.urlsafe_b64decode(
                cursor + '=' * (-len(cursor) % 4)
            )
            body, observed = payload[:-8], payload[-8:]
            expected = hashlib.sha256(
                f'triage\0{context_ref or ""}'.encode() + body
            ).digest()[:8]
            value = json.loads(body)
            offset = int(value['offset'])
            if observed != expected or offset < 0:
                raise ValueError
            return offset
        except Exception:
            raise TriageError('invalid_triage_cursor') from None

    def list(
        self,
        *,
        reference: str,
        limit: int = 5,
        cursor: str | None = None,
    ) -> dict:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
            raise TriageError('invalid_triage_limit')
        limit = min(limit, 10)
        scope = resolve_js_intake_reference(reference)
        offset = self._offset(cursor, scope.context_ref)
        records = self._notes(scope).typed_records()
        selected = [
            record
            for record in records
            if record.get('event_type') == 'triage_select'
        ]
        priority = {'high': 0, 'normal': 1, 'low': 2}
        selected.sort(
            key=lambda record: (
                priority.get(record.get('priority'), 9),
                record.get('created_at') or 0,
                record.get('span_id') or '',
            )
        )
        rows = [self._public_span(record, records) for record in selected]
        window = rows[offset : offset + limit]
        next_offset = offset + len(window)
        return {
            'spans': window,
            'total': len(rows),
            'pending_count': sum(row['state'] == 'discovered' for row in rows),
            'next_cursor': (
                self._cursor(scope.context_ref, next_offset)
                if next_offset < len(rows)
                else None
            ),
            'coverage': {
                'discovered': sum(row['state'] == 'discovered' for row in rows),
                'inspected': sum(row['state'] == 'inspected' for row in rows),
                'deferred': sum(row['state'] == 'deferred' for row in rows),
                'unresolved': sum(row['state'] == 'unresolved' for row in rows),
            },
        }


__all__ = ['EvidenceTriage', 'TriageError']
