"""Run-scoped YAML handle for the shared notes algorithm; never mounted in Kali."""
from __future__ import annotations

import fcntl
import re
import threading
import time
import uuid
from contextlib import contextmanager

import yaml
from pydantic import BaseModel, Field
from typing import Literal

from polymerhus.app.atomic_write import write_text_atomic
from polymerhus.app.data_root import project_dir, validate_path_component
from polymerhus.app.memory.tool_contract import NotesFieldMap, build_notes_tool

_LOCK = threading.RLock()
_SENSITIVE_NOTE = re.compile(
    r'https?://|cookie\s*[:=]|bearer\s|token\s*[:=]',
    re.I,
)
_TRIAGE_EVENT_TYPES = {'triage_select', 'triage_update'}


def _contains_sensitive(value) -> bool:
    if isinstance(value, str):
        return bool(_SENSITIVE_NOTE.search(value))
    if isinstance(value, dict):
        return any(_contains_sensitive(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_sensitive(item) for item in value)
    return False


class NotesArgs(BaseModel):
    command: Literal['read', 'write']
    option: Literal['append'] = 'append'
    note: str = Field(default='', max_length=2048)


class RunNotes:
    def __init__(self, scope, *, root=None):
        validate_path_component(scope.run_id, 'run_id')
        self.path = project_dir(scope.project_id, 'recon/js_analysis', root=root) / scope.run_id / 'notes.yaml'
        self.context_ref = scope.context_ref

    @contextmanager
    def _locked(self):
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.with_suffix('.lock').open('a+') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def _load(self):
        if not self.path.exists():
            return []
        return yaml.safe_load(self.path.read_text())['notes']

    def read(self, query):
        with self._locked():
            records = [n for n in self._load() if n['context_ref'] == self.context_ref]
            return {'notes': records[-4:], 'earlier_notes': max(0, len(records) - 4)}

    def write(self, request):
        if request.action != 'append' or not request.body:
            return {'error': 'append_requires_note'}
        # This slice records decisions/IDs, never URLs, credentials or code.
        if _SENSITIVE_NOTE.search(request.body):
            return {'error': 'non_sensitive_ids_and_decisions_only'}
        with self._locked():
            records = self._load()
            if len(records) >= 256:
                return {'error': 'notes_quota_exhausted'}
            record = {'note_id': uuid.uuid4().hex, 'context_ref': self.context_ref, 'note': request.body}
            records.append(record)
            write_text_atomic(self.path, yaml.safe_dump({'notes': records}, sort_keys=False))
            self.path.chmod(0o600)
            return {'note_id': record['note_id'], 'status': 'recorded'}

    def tool(self):
        return build_notes_tool(self, args_schema=NotesArgs,
                                field_map=NotesFieldMap(action='option', note='note', attributes=None))

    def append_typed_transaction(
        self,
        builder,
        *,
        allow_sanitized_text: bool = False,
    ) -> dict:
        """Build/append one typed event while holding the shared notes lock."""
        if not callable(builder):
            raise ValueError("typed note builder must be callable")
        with self._locked():
            records = self._load()
            outcome = builder([dict(record) for record in records])
            if not isinstance(outcome, dict):
                raise ValueError("typed note builder must return a mapping")
            if outcome.get("error") or outcome.get("existing_record"):
                return outcome
            record = outcome.get("record")
            if not isinstance(record, dict):
                raise ValueError("typed note record must be a mapping")
            if (
                not allow_sanitized_text
                and _contains_sensitive(record)
            ):
                return {'error': 'non_sensitive_ids_and_decisions_only'}
            if len(records) >= 256:
                return {'error': 'notes_quota_exhausted'}
            value = {
                **record,
                'record_id': uuid.uuid4().hex,
                'context_ref': self.context_ref,
                'created_at': int(time.time()),
            }
            records.append(value)
            write_text_atomic(
                self.path,
                yaml.safe_dump({'notes': records}, sort_keys=False),
            )
            self.path.chmod(0o600)
            return {'record': value, 'idempotent': False}

    def append_typed(
        self,
        record: dict,
        *,
        allow_sanitized_text: bool = False,
    ) -> dict:
        """Append an internally-authored typed record under the shared quota."""
        if not isinstance(record, dict):
            raise ValueError("typed note record must be a mapping")
        result = self.append_typed_transaction(
            lambda _records: {'record': record},
            allow_sanitized_text=allow_sanitized_text,
        )
        if result.get('error') or result.get('existing_record'):
            return result
        return result['record']

    def typed_records(
        self,
        *,
        event_types: set[str] | None = None,
    ) -> list[dict]:
        allowed = (
            _TRIAGE_EVENT_TYPES
            if event_types is None
            else set(event_types)
        )
        with self._locked():
            return [
                dict(record)
                for record in self._load()
                if (record.get('context_ref') or '') == (self.context_ref or '')
                and record.get('event_type') in allowed
            ]
