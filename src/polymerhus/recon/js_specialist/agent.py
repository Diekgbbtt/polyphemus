"""Thin recon session owner using the shared model/session/compaction substrate."""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import math
import shlex
import threading
import time
import traceback
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from polymerhus.app.atomic_write import write_text_atomic
from polymerhus.app.data_root import project_dir, validate_path_component
from polymerhus.app.llm.session_address import JsSpecialistSession
from polymerhus.recon.js_intake.cli import MAX_BEHAVIOR_COMMAND_CHARS, parse_operation
from polymerhus.recon.js_intake.reader import (
    InvalidJsIntakeReference, issue_js_intake_reference, resolve_js_intake_reference,
)

ROLE = 'js_specialist'
logger = logging.getLogger(__name__)
TRIAGE_SKILL = 'js-evidence-triage'
TRIAGE_ANALYSIS_OPERATIONS = frozenset({
    'search-code',
    'read-code',
    'triage-select',
    'triage-update',
    'behavior-save',
    'graph-candidates',
    'graph-note',
})
TRIAGE_CLOSURE_OPERATION_ORDER = ('triage-list', 'note')
TRIAGE_CLOSURE_OPERATIONS = frozenset(TRIAGE_CLOSURE_OPERATION_ORDER)
RETENTION_RECONCILE_MAX_TIME_S = 20
RETENTION_RECONCILE_MAX_ITEMS = 4


@lru_cache(maxsize=1)
def _load_prompt():
    return (Path(__file__).parent / 'prompts' / 'specialist.md').read_text(encoding='utf-8')


@dataclass(frozen=True)
class TriageBudgetPolicy:
    """Opt-in single-lead attempt partitioning for evidence triage."""

    pre_triage_attempt_limit: int = 28
    minimum_triage_attempts: int = 16
    triage_closure_attempts: int = 2

    def __post_init__(self):
        values = vars(self)
        if any(value <= 0 for value in values.values()):
            raise ValueError('triage budget values must be positive')
        if self.minimum_triage_attempts < self.triage_closure_attempts:
            raise ValueError(
                'minimum triage attempts must cover the closure reserve'
            )


@dataclass(frozen=True)
class SpecialistLimits:
    max_attempts: int | None = None
    wall_time_s: float = 300
    command_time_s: int = 45
    max_output_bytes: int = 16384
    max_total_output_bytes: int = 131072
    max_batch: int = 3
    triage_budget: TriageBudgetPolicy | None = None

    def __post_init__(self):
        if any(
            name not in {'triage_budget', 'max_attempts'} and value <= 0
            for name, value in vars(self).items()
        ) or (self.max_attempts is not None and self.max_attempts <= 0):
            raise ValueError('specialist limits must be positive')
        if self.triage_budget is not None and self.max_attempts is None:
            raise ValueError('triage budget requires finite max_attempts')
        if (
            self.triage_budget is not None
            and self.max_attempts
            < (
                self.triage_budget.pre_triage_attempt_limit
                + self.triage_budget.minimum_triage_attempts
            )
        ):
            raise ValueError(
                'max_attempts must cover the triage preparation and reserve'
            )

    def budget_dict(self):
        return asdict(self)


class BoundedExec:
    """Exec adapter over the existing Kali transport, bounded before dispatch."""

    def __init__(self, *, prefix, session_id, exec_fn, limits):
        self.prefix = prefix
        self.command_prefix = shlex.join(prefix)
        self.session_id = session_id
        self.exec_fn = exec_fn
        self.limits = limits
        self.deadline = time.monotonic() + limits.wall_time_s
        self.started_at = time.monotonic()
        self._admission_lock = asyncio.Lock()
        self.attempts = self.executions = self.rejections = self.output_bytes = 0
        self.pre_analysis_attempts = 0
        self.preparation_attempts = 0
        self.triage_guidance_attempts = 0
        self.triage_skill_loaded = False
        self.triage_references_loaded = set()
        self.triage_shortlist_consulted = False
        self.triage_shortlist_consultations = 0
        self.triage_phase_attempts = 0
        self.triage_investigation_attempts = 0
        self.triage_closure_attempts = 0
        self.preparation_rejections = 0
        self.guidance_rejections = 0
        self.pre_analysis_rejections = 0
        self.closure_rejections = 0
        self.triage_phase_rejections = 0
        self.triage_phase_started = False
        self.triage_capacity = None
        self.triage_transition_attempt = None
        self.triage_list_operations = 0
        self.triage_closure_operation_names = set()
        self.triage_closure_success_operations = set()
        self.internal_confirmation_attempts = 0
        self.internal_confirmations_succeeded = 0
        self.maintenance_exec_attempts = 0
        self.maintenance_output_bytes = 0
        self.policy_decisions = []
        self.acquisition_attempts = 0
        self.scan_attempts = 0
        self.recovery_attempts = 0
        self.structure_attempts = 0
        self.child_acquisition_attempts = 0
        self.read_attempts = 0
        self.search_attempts = 0
        self.triage_attempts = 0
        self.behavior_attempts = 0
        self.behavior_save_attempts = 0
        self.behavior_list_attempts = 0
        self.events = []
        self.gaps = []
        self.context_loaded = False
        self.notes_loaded = False
        self.triage_guidance_seen = False
        self.triage_guidance_order_violation = False
        self.triage_skill_loaded_after_context_notes = False
        self.triage_references_loaded_after_context_notes = set()
        self.triage_shortlist_consulted_after_context_notes = False
        self.next_cursor = None
        self.inventory_read = False
        self.returned_leads = set()
        self.seen_leads = set()
        self.outcomes = {}
        self.scan_outcomes = {}
        self.recovery_outcomes = {}
        self.structure_outcomes = {}
        self.child_outcomes = {}
        self.read_outcomes = {}
        self.search_outcomes = {}
        self.triage_outcomes = {}
        self.behavior_save_outcomes = {}
        self.behavior_list_outcomes = {}
        self.triage_pending_count = 0

    def _reject(self, reason, **details):
        self.rejections += 1
        self.gaps.append(reason)
        return {'error': reason, **details}

    def _is_triage_guidance_command(self, operation, args):
        if operation in {'triage-list', 'behavior-list'}:
            return True
        return (
            operation in {'skill', 'reference'}
            and args.get('name') == TRIAGE_SKILL
        )

    def _is_triage_analysis_command(self, operation):
        return operation in TRIAGE_ANALYSIS_OPERATIONS

    def _record_policy_decision(
        self,
        *,
        attempt,
        operation,
        phase,
        allowed,
        reason=None,
    ):
        if self.limits.triage_budget is None:
            return
        capacity = self.triage_capacity
        self.policy_decisions.append({
            'attempt': attempt,
            'operation': operation,
            'phase': phase,
            'allowed': allowed,
            'reason': reason,
            'triage_attempts': self.triage_phase_attempts,
            'triage_capacity': capacity,
            'triage_capacity_remaining': (
                None if capacity is None else capacity - self.triage_phase_attempts
            ),
        })

    async def _begin_attempt(self):
        async with self._admission_lock:
            self.attempts += 1
            attempt = self.attempts
            if (
                self.limits.max_attempts is not None
                and attempt > self.limits.max_attempts
            ):
                return attempt, self._reject('attempt_budget_exhausted')
            return attempt, None

    async def _admit(self, attempt, operation, args):
        """Atomically apply total, phase, batch and operation counters."""
        async with self._admission_lock:
            if self.output_bytes >= self.limits.max_total_output_bytes:
                return self._reject('output_budget_exhausted')

            batch_counter = {
                'acquire': 'acquisition_attempts',
                'scan': 'scan_attempts',
                'recover': 'recovery_attempts',
                'structure': 'structure_attempts',
                'acquire-reference': 'child_acquisition_attempts',
            }.get(operation)
            if (
                batch_counter is not None
                and getattr(self, batch_counter) >= self.limits.max_batch
            ):
                return self._reject('batch_budget_exhausted')

            policy = self.limits.triage_budget
            phase = 'legacy'
            is_closure = False
            if policy is not None:
                guidance_command = self._is_triage_guidance_command(
                    operation,
                    args,
                )
                analysis_command = self._is_triage_analysis_command(
                    operation
                )
                if (
                    not self.triage_phase_started
                    and (guidance_command or not analysis_command)
                ):
                    phase = (
                        'guidance' if guidance_command else 'preparation'
                    )
                    if (
                        self.pre_analysis_attempts
                        >= policy.pre_triage_attempt_limit
                    ):
                        self.pre_analysis_rejections += 1
                        if guidance_command:
                            self.guidance_rejections += 1
                        else:
                            self.preparation_rejections += 1
                        self._record_policy_decision(
                            attempt=attempt,
                            operation=operation,
                            phase=phase,
                            allowed=False,
                            reason='pre_analysis_budget_exhausted',
                        )
                        return self._reject(
                            'pre_analysis_budget_exhausted',
                            triage_required=True,
                            pre_analysis_attempts=(
                                self.pre_analysis_attempts
                            ),
                            pre_analysis_limit=(
                                policy.pre_triage_attempt_limit
                            ),
                        )
                else:
                    if not self.triage_phase_started:
                        self.triage_phase_started = True
                        self.triage_transition_attempt = attempt
                        self.triage_capacity = max(
                            0,
                            self.limits.max_attempts - (attempt - 1),
                        )
                        if (
                            self.triage_capacity
                            < policy.minimum_triage_attempts
                        ):
                            self.gaps.append(
                                'triage_minimum_reserve_unavailable'
                            )
                    phase = 'triage'
                    remaining_triage = (
                        self.triage_capacity - self.triage_phase_attempts
                    )
                    if remaining_triage <= 0:
                        self.triage_phase_rejections += 1
                        self._record_policy_decision(
                            attempt=attempt,
                            operation=operation,
                            phase=phase,
                            allowed=False,
                            reason='triage_budget_exhausted',
                        )
                        return self._reject('triage_budget_exhausted')
                    if (
                        remaining_triage <= policy.triage_closure_attempts
                        and operation not in TRIAGE_CLOSURE_OPERATIONS
                    ):
                        self.closure_rejections += 1
                        self._record_policy_decision(
                            attempt=attempt,
                            operation=operation,
                            phase='triage_closure',
                            allowed=False,
                            reason='triage_closure_only',
                        )
                        return self._reject(
                            'triage_closure_only',
                            closure_operations=list(
                                TRIAGE_CLOSURE_OPERATION_ORDER
                            ),
                        )

            if batch_counter is not None:
                setattr(
                    self,
                    batch_counter,
                    getattr(self, batch_counter) + 1,
                )
            if operation == 'read-code':
                self.read_attempts += 1
            if operation == 'search-code':
                self.search_attempts += 1
            if operation in {'behavior-save', 'behavior-list'}:
                self.behavior_attempts += 1
            if operation == 'behavior-save':
                self.behavior_save_attempts += 1
            if operation == 'behavior-list':
                self.behavior_list_attempts += 1
            if operation in {'triage-select', 'triage-update', 'triage-list'}:
                self.triage_attempts += 1
            if policy is not None:
                if phase in {'preparation', 'guidance'}:
                    self.pre_analysis_attempts += 1
                if phase == 'preparation':
                    self.preparation_attempts += 1
                elif phase == 'triage':
                    self.triage_phase_attempts += 1
                    prior_triage_lists = self.triage_list_operations
                    if operation == 'triage-list':
                        self.triage_list_operations += 1
                    is_closure = (
                        operation == 'note'
                        or (
                            operation == 'triage-list'
                            and (
                                prior_triage_lists > 0
                                or remaining_triage
                                <= policy.triage_closure_attempts
                            )
                        )
                    )
                    if is_closure:
                        self.triage_closure_attempts += 1
                        self.triage_closure_operation_names.add(operation)
                    else:
                        self.triage_investigation_attempts += 1
                elif phase == 'guidance':
                    self.triage_guidance_attempts += 1
                    guidance_after_context_notes = (
                        self.context_loaded and self.notes_loaded
                    )
                    self.triage_guidance_seen = True
                    if not guidance_after_context_notes:
                        self.triage_guidance_order_violation = True
                    if operation == 'skill':
                        self.triage_skill_loaded = True
                        self.triage_skill_loaded_after_context_notes = (
                            guidance_after_context_notes
                        )
                    elif operation == 'reference':
                        target = str(args.get('target') or '')
                        if target:
                            self.triage_references_loaded.add(target)
                            if guidance_after_context_notes:
                                self.triage_references_loaded_after_context_notes.add(
                                    target
                                )
                    elif operation == 'triage-list':
                        self.triage_shortlist_consulted = True
                        self.triage_shortlist_consultations += 1
                        self.triage_list_operations += 1
                        self.triage_shortlist_consulted_after_context_notes = (
                            guidance_after_context_notes
                        )
                if operation == 'context':
                    self.context_loaded = True
                elif operation == 'notes':
                    self.notes_loaded = True
                self._record_policy_decision(
                    attempt=attempt,
                    operation=operation,
                    phase=(
                        'triage_closure'
                        if phase == 'triage' and is_closure
                        else phase
                    ),
                    allowed=True,
                )
            return {
                'phase': phase,
                'closure': bool(phase == 'triage' and is_closure),
            }

    async def run(self, command):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            return self._reject('time_budget_exhausted')
        attempt, rejection = await self._begin_attempt()
        if rejection is not None:
            return rejection
        try:
            if len(command) > MAX_BEHAVIOR_COMMAND_CHARS:
                raise ValueError
            tokens = shlex.split(command)
            if tokens[:len(self.prefix)] != self.prefix:
                raise ValueError
            args = parse_operation(tokens[len(self.prefix):])
            if len(command) > 4096 and args['operation'] != 'behavior-save':
                raise ValueError
        except (SystemExit, Exception):
            # Parser messages/invalid command text are never reflected to the model.
            return self._reject('command_rejected')
        operation = args['operation']
        admission = await self._admit(attempt, operation, args)
        if 'error' in admission:
            return admission
        self.executions += 1
        self.events.append({'operation': operation, **({'lead_id': args['lead_id']} if 'lead_id' in args else {}),
                            **({'item_id': args['item_id']} if 'item_id' in args else {}),
                            **({'source_id': args['source']} if args.get('source') else {}),
                            **({'match_id': args['match']} if args.get('match') else {}),
                            **({'span_id': args['span_id']} if args.get('span_id') else {}),
                            **({'name': args['name']} if 'name' in args else {})})
        try:
            # Use the pod's established Exec trace attribution; no hand-written span.
            from polymerhus.recon.domain.pod import trace_metadata_ctx
            token = trace_metadata_ctx().set({'langfuse_session_id': self.session_id,
                                              'langfuse_tags': ['recon', ROLE]})
            try:
                result = await asyncio.wait_for(asyncio.to_thread(
                    self.exec_fn, shlex.join(tokens), self.session_id,
                    max(1, math.ceil(min(remaining, self.limits.command_time_s)))),
                    timeout=min(remaining, self.limits.command_time_s) + 1)
            finally:
                trace_metadata_ctx().reset(token)
        except TimeoutError:
            self.gaps.append('command_timeout')
            if operation == 'behavior-save':
                self.gaps.append('behavior_save_outcome_uncertain')
            return {'error': 'command_timeout'}
        except Exception:
            self.gaps.append('exec_transport_failed')
            if operation == 'behavior-save':
                self.gaps.append('behavior_save_outcome_uncertain')
            return {'error': 'exec_transport_failed'}
        if len(result.stdout.encode()) + len(result.stderr.encode()) > self.limits.max_output_bytes:
            self.output_bytes += self.limits.max_output_bytes
            self.gaps.append('output_budget_exhausted')
            if operation == 'behavior-save':
                self.gaps.append('behavior_save_outcome_uncertain')
            return {'error': 'output_budget_exhausted'}
        try:
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, TypeError):
            self.gaps.append('invalid_cli_output')
            if operation == 'behavior-save':
                self.gaps.append('behavior_save_outcome_uncertain')
            return {'error': 'invalid_cli_output'}
        envelope = {'returncode': result.returncode, 'result': payload}
        output_size = len(json.dumps(envelope).encode())
        self.output_bytes += min(output_size, self.limits.max_output_bytes)
        if output_size > self.limits.max_output_bytes or self.output_bytes > self.limits.max_total_output_bytes:
            self.gaps.append('output_budget_exhausted')
            if operation == 'behavior-save':
                self.gaps.append('behavior_save_outcome_uncertain')
            return {'error': 'output_budget_exhausted'}
        if (
            operation == 'read-code'
            and payload.get('delivery_status') == 'prepared'
            and payload.get('read_id')
        ):
            self.internal_confirmation_attempts += 1
            confirmation_remaining = self.deadline - time.monotonic()
            try:
                if confirmation_remaining <= 0:
                    raise TimeoutError
                confirmed = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.exec_fn,
                        shlex.join(
                            [
                                *self.prefix,
                                'code-read-confirm',
                                str(payload['read_id']),
                            ]
                        ),
                        self.session_id,
                        max(
                            1,
                            math.ceil(
                                min(
                                    confirmation_remaining,
                                    self.limits.command_time_s,
                                )
                            ),
                        ),
                    ),
                    timeout=min(
                        confirmation_remaining,
                        self.limits.command_time_s,
                    )
                    + 1,
                )
                confirmation = json.loads(confirmed.stdout)
                if (
                    confirmed.returncode == 0
                    and confirmation.get('delivery_status') == 'delivered'
                ):
                    payload['delivery_status'] = 'delivered'
                    self.internal_confirmations_succeeded += 1
                else:
                    raise ValueError
            except Exception:
                self.gaps.append('read_delivery_unconfirmed')
                payload['delivery_status'] = 'unconfirmed'
        command_failed = bool(
            result.returncode != 0
            or payload.get('error')
            or payload.get('failure_reason')
        )
        if command_failed:
            self.gaps.append(
                str(
                    payload.get('error')
                    or payload.get('failure_reason')
                    or 'command_returned_nonzero'
                )[:100]
            )
        if admission['closure'] and not command_failed:
            self.triage_closure_success_operations.add(operation)
        if operation == 'inventory' and 'coverage' in payload:
            self.inventory_read = True
            self.next_cursor = payload.get('next_cursor')
            self.returned_leads.update(
                row['lead_id']
                for row in payload.get('leads', [])
                if row.get('lead_id')
            )
            if payload['coverage'].get('coverage_gap'):
                self.gaps.append(payload['coverage']['coverage_gap'])
        if operation in {'lead', 'acquire', 'structure'} and args.get('lead_id'):
            self.seen_leads.add(args['lead_id'])
        if operation == 'acquire':
            self.outcomes[args['lead_id']] = {key: payload[key] for key in (
                'status', 'failure_reason', 'sha256', 'size', 'work_file_ref') if key in payload}
        if operation == 'scan':
            scan_outcome = {
                key: payload[key]
                for key in (
                    'status',
                    'scan_key',
                    'modes',
                    'candidate_count',
                    'reused',
                    'failure_reason',
                )
                if key in payload
            }
            self.scan_outcomes[args['lead_id']] = scan_outcome
            if scan_outcome.get('status') != 'complete':
                self.gaps.append('scan_partial_or_failed')
        if operation == 'recover':
            recovery_outcome = {
                key: payload[key]
                for key in (
                    'status',
                    'map_id',
                    'source_count',
                    'available',
                    'transferred',
                    'skipped_existing',
                    'failures',
                    'gaps',
                )
                if key in payload
            }
            self.recovery_outcomes[args['lead_id']] = recovery_outcome
            for gap in payload.get('gaps') or []:
                self.gaps.append(str(gap)[:100])
            if recovery_outcome.get('status') != 'complete':
                self.gaps.append('recovery_partial_or_failed')
        if operation == 'structure':
            structure_outcome = {
                key: payload[key]
                for key in (
                    'status',
                    'index_id',
                    'source_sha256',
                    'source_size',
                    'format',
                    'counts',
                    'gaps',
                    'reused',
                    'source_availability',
                    'failure_reason',
                )
                if key in payload
            }
            self.structure_outcomes[args['lead_id']] = structure_outcome
            for gap in payload.get('gaps') or []:
                self.gaps.append(str(gap)[:100])
            if structure_outcome.get('status') not in {'complete'}:
                self.gaps.append('structure_partial_or_failed')
        if operation == 'acquire-reference':
            item_id = str(args.get('item_id') or '')
            self.child_outcomes[item_id] = {
                key: payload[key]
                for key in (
                    'status',
                    'lead_id',
                    'failure_reason',
                    'sha256',
                    'size',
                    'work_file_ref',
                    'reconcile_required',
                )
                if key in payload
            }
        if operation == 'read-code':
            read_id = str(payload.get('read_id') or '')
            if read_id:
                self.read_outcomes[read_id] = {
                    'delivery_status': payload.get('delivery_status'),
                    'selector': payload.get('selector')
                    or {
                        'type': next(
                            (
                                kind
                                for kind in ('item', 'source', 'match')
                                if args.get(kind)
                            ),
                            None,
                        ),
                        'id': next(
                            (
                                args.get(kind)
                                for kind in ('item', 'source', 'match')
                                if args.get(kind)
                            ),
                            None,
                        ),
                    },
                    'content_sha256': payload.get('content_sha256'),
                    'original_start': payload.get('original_start'),
                    'original_end': payload.get('original_end'),
                    'redaction_count': payload.get('redaction_count'),
                    'failure_reason': payload.get('error')
                    or payload.get('failure_reason'),
                }
        if operation == 'search-code':
            self.search_outcomes[args.get('lead_id', '')] = {
                key: payload[key]
                for key in (
                    'search_id',
                    'status',
                    'total_matches',
                    'examined_bytes',
                    'coverage_gap',
                    'next_cursor',
                    'failure_reason',
                )
                if key in payload
            }
        if operation == 'behavior-save':
            record_arg = args.get('record')
            if isinstance(record_arg, str):
                try:
                    record_arg = json.loads(record_arg)
                except (ValueError, TypeError):
                    record_arg = {}
            if not isinstance(record_arg, dict):
                record_arg = {}
            question_ref = str(
                payload.get('question_ref')
                or record_arg.get('question_ref')
                or ''
            )
            outcome_key = (
                question_ref
                or f'attempt_{len(self.behavior_save_outcomes) + 1}'
            )
            retention = (
                payload.get('retention')
                if isinstance(payload.get('retention'), dict)
                else {}
            )
            retention_outcome = {
                key: retention[key]
                for key in (
                    'status',
                    'retained_count',
                    'pending_count',
                    'gap_count',
                    'gaps',
                    'error',
                )
                if key in retention
            }
            self.behavior_save_outcomes[outcome_key] = {
                key: payload[key]
                for key in (
                    'behavior_id',
                    'revision',
                    'reconstruction_level',
                    'record_sha256',
                    'redaction_count',
                    'idempotent',
                    'error',
                    'failure_reason',
                )
                if key in payload
            }
            if retention_outcome:
                self.behavior_save_outcomes[outcome_key][
                    'retention'
                ] = retention_outcome
                if retention_outcome.get('status') in {
                    'pending',
                    'partial',
                    'gap',
                }:
                    self.gaps.append(
                        'behavior_retention_pending'
                        if retention_outcome.get('status') == 'pending'
                        else 'behavior_retention_partial_or_gap'
                    )
        if operation == 'behavior-list':
            self.behavior_list_outcomes = {
                key: payload[key]
                for key in (
                    'total',
                    'next_cursor',
                    'coverage',
                    'error',
                    'failure_reason',
                )
                if key in payload
            }
        if operation in {'triage-select', 'triage-update'}:
            span_id = str(
                payload.get('span_id')
                or args.get('span_id')
                or ''
            )
            if span_id:
                prior = self.triage_outcomes.get(span_id) or {}
                self.triage_outcomes[span_id] = {
                    **prior,
                    'state': payload.get('state') or prior.get('state'),
                    'idempotent': payload.get('idempotent', False),
                }
        if operation == 'triage-list':
            self.triage_pending_count = int(payload.get('pending_count') or 0)
        return envelope

    def maintenance_exec(self, command, *, deadline):
        """Run trusted retention maintenance without consuming model budget."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {
                'error': 'retention_reconcile_deadline',
                'remote_outcome_uncertain': True,
            }
        try:
            if len(command) > MAX_BEHAVIOR_COMMAND_CHARS:
                raise ValueError
            tokens = shlex.split(command)
            if tokens[:len(self.prefix)] != self.prefix:
                raise ValueError
            args = parse_operation(tokens[len(self.prefix):])
            if args.get('operation') != 'behavior-save':
                raise ValueError
        except (SystemExit, Exception):
            return {'error': 'maintenance_command_rejected'}
        self.maintenance_exec_attempts += 1
        started = time.monotonic()
        from polymerhus.recon.domain.pod import trace_metadata_ctx
        finished = threading.Event()
        outcome = {}

        def execute():
            token = trace_metadata_ctx().set({
                'langfuse_session_id': self.session_id,
                'langfuse_tags': ['recon', ROLE, 'retention-resume'],
            })
            try:
                outcome['result'] = self.exec_fn(
                    command,
                    self.session_id,
                    max(
                        1,
                        math.ceil(
                            min(remaining, self.limits.command_time_s)
                        ),
                    ),
                )
            except BaseException as exc:
                outcome['error'] = exc
            finally:
                trace_metadata_ctx().reset(token)
                finished.set()

        threading.Thread(target=execute, daemon=True).start()
        if not finished.wait(
            max(.001, min(remaining, self.limits.command_time_s))
        ):
            return {
                'error': 'retention_reconcile_deadline',
                'remote_outcome_uncertain': True,
            }
        if 'error' in outcome:
            return {
                'error': 'maintenance_exec_failed',
                'remote_outcome_uncertain': True,
            }
        result = outcome['result']
        output_size = len(result.stdout.encode()) + len(result.stderr.encode())
        if output_size > self.limits.max_output_bytes:
            self.maintenance_output_bytes += self.limits.max_output_bytes
            return {'error': 'maintenance_output_budget_exhausted'}
        self.maintenance_output_bytes += min(
            output_size,
            self.limits.max_output_bytes,
        )
        try:
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, TypeError):
            return {'error': 'invalid_maintenance_output'}
        return {
            'returncode': result.returncode,
            'result': payload,
            'duration_ms': int((time.monotonic() - started) * 1000),
        }

    def tool(self):
        from langchain_core.tools import tool

        @tool
        async def exec(command: str) -> str:
            """Execute one installed JS CLI command using the exact supplied prefix. No shell pipelines. Returns bounded metadata and, only for read-code, a redacted code window."""
            return json.dumps(await self.run(command))
        return exec

    def summary(self):
        gaps = list(self.gaps)
        if not self.inventory_read:
            gaps.append('inventory_not_read')
        if self.next_cursor:
            gaps.append('inventory_pages_remaining')
        acquired = {lead_id for lead_id, outcome in self.outcomes.items()
                    if outcome.get('status') == 'acquired'}
        pending = set(self.seen_leads - acquired)
        if pending:
            gaps.append('unacquired_selected_leads')
        for lead_id in acquired:
            if lead_id not in self.scan_outcomes:
                pending.add(lead_id)
                gaps.append('scan_not_attempted')
            if lead_id not in self.recovery_outcomes:
                pending.add(lead_id)
                gaps.append('recovery_not_attempted')
            if lead_id not in self.structure_outcomes:
                pending.add(lead_id)
                gaps.append('structure_not_attempted')
        pending_children = sorted(
            item_id
            for item_id, outcome in self.child_outcomes.items()
            if outcome.get('status') == 'reconcile_required'
            or outcome.get('reconcile_required')
        )
        if pending_children:
            gaps.append('child_acquisition_reconcile_pending')
        discovered_outcomes = sum(
            outcome.get('state') == 'discovered'
            for outcome in self.triage_outcomes.values()
        )
        effective_triage_pending = max(
            self.triage_pending_count,
            discovered_outcomes,
        )
        if effective_triage_pending:
            gaps.append('triage_pending_spans')
        triage_eligible_lead_ids = sorted(acquired) if acquired else []
        triage_policy_enabled = self.limits.triage_budget is not None
        triage_guidance_order_ok = (
            self.triage_guidance_seen
            and not self.triage_guidance_order_violation
        )
        triage_closure_complete = (
            TRIAGE_CLOSURE_OPERATIONS
            <= self.triage_closure_success_operations
        )
        if triage_policy_enabled:
            if not self.triage_skill_loaded:
                gaps.append('triage_guidance_not_loaded')
            if not self.triage_shortlist_consulted:
                gaps.append('triage_shortlist_not_consulted')
            if (
                self.triage_guidance_seen
                and not triage_guidance_order_ok
            ):
                gaps.append('triage_guidance_not_after_context_notes')
            if not self.triage_phase_started:
                gaps.append('triage_not_started')
                pending.update(acquired)
            elif not triage_eligible_lead_ids:
                gaps.append('triage_without_verified_code')
            elif not triage_closure_complete:
                gaps.append('triage_closure_incomplete')
                pending.update(triage_eligible_lead_ids)
        triage_capacity_remaining = (
            None
            if self.triage_capacity is None
            else max(0, self.triage_capacity - self.triage_phase_attempts)
        )
        pending = sorted(pending)
        return {'coverage': 'partial', 'gaps': list(dict.fromkeys(gaps)),
                'next_cursor': self.next_cursor, 'pending_lead_ids': pending,
                'outcomes': self.outcomes,
                'scan_outcomes': self.scan_outcomes,
                'recovery_outcomes': self.recovery_outcomes,
                'structure_outcomes': self.structure_outcomes,
                'child_outcomes': self.child_outcomes,
                'read_outcomes': self.read_outcomes,
                'search_outcomes': self.search_outcomes,
                'triage_outcomes': self.triage_outcomes,
                'behavior_save_outcomes': self.behavior_save_outcomes,
                'behavior_list_outcome': self.behavior_list_outcomes,
                'saved_behavior_count': sum(
                    bool(outcome.get('behavior_id'))
                    and not outcome.get('error')
                    and not outcome.get('failure_reason')
                    for outcome in self.behavior_save_outcomes.values()
                ),
                'retained_evidence_count': sum(
                    int(
                        (
                            outcome.get('retention')
                            or {}
                        ).get('retained_count')
                        or 0
                    )
                    for outcome in self.behavior_save_outcomes.values()
                ),
                'retention_pending_count': sum(
                    int(
                        (
                            outcome.get('retention')
                            or {}
                        ).get('pending_count')
                        or 0
                    )
                    for outcome in self.behavior_save_outcomes.values()
                ),
                'retention_gap_count': sum(
                    int(
                        (
                            outcome.get('retention')
                            or {}
                        ).get('gap_count')
                        or 0
                    )
                    for outcome in self.behavior_save_outcomes.values()
                ),
                'triage_pending_count': effective_triage_pending,
                'pending_child_item_ids': pending_children,
                'events': self.events,
                'budget': {'attempts': self.attempts, 'executions': self.executions,
                           'rejections': self.rejections, 'output_bytes': self.output_bytes,
                           'acquisition_attempts': self.acquisition_attempts,
                           'scan_attempts': self.scan_attempts,
                           'recovery_attempts': self.recovery_attempts,
                           'structure_attempts': self.structure_attempts,
                           'child_acquisition_attempts': self.child_acquisition_attempts,
                           'read_attempts': self.read_attempts,
                           'search_attempts': self.search_attempts,
                           'triage_attempts': self.triage_attempts,
                           'behavior_attempts': self.behavior_attempts,
                           'behavior_save_attempts': (
                               self.behavior_save_attempts
                           ),
                           'behavior_list_attempts': (
                               self.behavior_list_attempts
                           ),
                           'pre_analysis_attempts': (
                               self.pre_analysis_attempts
                           ),
                           'pre_analysis_limit': (
                               None
                               if self.limits.triage_budget is None
                               else self.limits.triage_budget.pre_triage_attempt_limit
                           ),
                           'pre_analysis_remaining': (
                               None
                               if self.limits.triage_budget is None
                               else max(
                                   0,
                                   self.limits.triage_budget.pre_triage_attempt_limit
                                   - self.pre_analysis_attempts,
                               )
                           ),
                           'preparation_attempts': self.preparation_attempts,
                           'triage_guidance_attempts': (
                               self.triage_guidance_attempts
                           ),
                           'triage_skill_loaded': self.triage_skill_loaded,
                           'triage_skill_loaded_after_context_notes': (
                               self.triage_skill_loaded_after_context_notes
                           ),
                           'triage_references_loaded': sorted(
                               self.triage_references_loaded
                           ),
                           'triage_references_loaded_after_context_notes': (
                               sorted(
                                   self.triage_references_loaded_after_context_notes
                               )
                           ),
                           'triage_shortlist_consulted': (
                               self.triage_shortlist_consulted
                           ),
                           'triage_shortlist_consulted_after_context_notes': (
                               self.triage_shortlist_consulted_after_context_notes
                           ),
                           'triage_shortlist_consultations': (
                               self.triage_shortlist_consultations
                           ),
                           'triage_guidance_order_ok': (
                               triage_guidance_order_ok
                           ),
                           'triage_phase_attempts': self.triage_phase_attempts,
                           'triage_analysis_started': (
                               self.triage_phase_started
                           ),
                           'triage_investigation_attempts': (
                               self.triage_investigation_attempts
                           ),
                           'triage_closure_attempts': (
                               self.triage_closure_attempts
                           ),
                           'preparation_rejections': (
                               self.preparation_rejections
                           ),
                           'guidance_rejections': self.guidance_rejections,
                           'pre_analysis_rejections': (
                               self.pre_analysis_rejections
                           ),
                           'closure_rejections': self.closure_rejections,
                           'triage_phase_rejections': (
                               self.triage_phase_rejections
                           ),
                           'policy_rejections': (
                               self.pre_analysis_rejections
                               + self.closure_rejections
                               + self.triage_phase_rejections
                           ),
                           'triage_policy_enabled': triage_policy_enabled,
                           'triage_phase_started': self.triage_phase_started,
                           'triage_transition_attempt': (
                               self.triage_transition_attempt
                           ),
                           'triage_capacity': self.triage_capacity,
                           'triage_capacity_remaining': (
                               triage_capacity_remaining
                           ),
                           'triage_minimum_attempts': (
                               None
                               if self.limits.triage_budget is None
                               else self.limits.triage_budget.minimum_triage_attempts
                           ),
                           'triage_minimum_reserve_met': (
                               None
                               if self.triage_capacity is None
                               else self.triage_capacity
                               >= self.limits.triage_budget.minimum_triage_attempts
                           ),
                           'triage_closure_reserve': (
                               None
                               if self.limits.triage_budget is None
                               else self.limits.triage_budget.triage_closure_attempts
                           ),
                           'triage_closure_guaranteed': (
                               None
                               if not self.triage_phase_started
                               else self.rejections == 0
                           ),
                           'triage_closure_operations': sorted(
                               self.triage_closure_operation_names
                           ),
                           'triage_closure_success_operations': sorted(
                               self.triage_closure_success_operations
                           ),
                           'triage_closure_complete': triage_closure_complete,
                           'triage_eligible_lead_ids': (
                               triage_eligible_lead_ids
                           ),
                           'internal_confirmation_attempts': (
                               self.internal_confirmation_attempts
                           ),
                           'internal_confirmations_succeeded': (
                               self.internal_confirmations_succeeded
                           ),
                           'maintenance_exec_attempts': (
                               self.maintenance_exec_attempts
                           ),
                           'maintenance_output_bytes': (
                               self.maintenance_output_bytes
                           ),
                           'elapsed_s': round(time.monotonic() - self.started_at, 3),
                           'limits': self.limits.budget_dict()}}


def _default_retention_reconcile(
    *,
    root,
    runner,
    reference,
    deadline,
    max_items,
):
    from polymerhus.recon.js_retention.service import JsRetentionService

    service = JsRetentionService(root=root)

    def retry(
        *,
        behavior_id,
        revision,
        behavior,
        dependencies,
        deadline,
    ):
        del behavior_id, revision
        parts = [
            *runner.prefix,
            'behavior-save',
            '--record',
            json.dumps(behavior, separators=(',', ':')),
            '--deadline-s',
            f'{max(.001, deadline - time.monotonic()):.3f}',
        ]
        for dependency in dependencies:
            parts.extend([
                '--dependency',
                json.dumps(dependency, separators=(',', ':')),
            ])
        return runner.maintenance_exec(
            shlex.join(parts),
            deadline=deadline,
        )

    return service.reconcile_run(
        reference=reference,
        deadline=deadline,
        max_items=max_items,
        retry_fn=retry,
    )


def build_js_specialist(*, root=None, agent_url='http://agent:8080', limits=None,
                        exec_fn=None, session_fn=None, checkpointer=None,
                        middleware=None, model_factory=None, observe=True,
                        retention_reconcile_fn=None):
    """Configured specialist executor for the native recon job; all live collaborators resolve lazily."""
    limits = limits or SpecialistLimits()

    async def dispatch(*, project_id, run_id, reference, auth_context_label, auth_context_ref, deadline=None):
        validate_path_component(project_id, 'project_id')
        validate_path_component(run_id, 'run_id')
        address = JsSpecialistSession(project_id, run_id, auth_context_ref)
        context_key = hashlib.sha256(json.dumps(auth_context_ref).encode()).hexdigest()[:16]
        summary_path = project_dir(project_id, 'recon/js_analysis', root=root) / run_id / f'specialist-{context_key}.json'
        summary = {'coverage': 'partial', 'gaps': ['invalid_or_mismatched_reference']}
        try:
            scope = resolve_js_intake_reference(reference)
            if (scope.project_id, scope.run_id, scope.context_ref) != (project_id, run_id, auth_context_ref):
                raise InvalidJsIntakeReference('scope mismatch')
            if auth_context_label != ('authenticated' if auth_context_ref else 'anonymous'):
                raise InvalidJsIntakeReference('missing context')
        except InvalidJsIntakeReference:
            write_text_atomic(summary_path, json.dumps(summary))
            return summary
        # Trusted in-process renewal only, same binding; cover the entire finite
        # runner deadline instead of relying on the intake default five-minute TTL.
        session_reference = issue_js_intake_reference(project_id, run_id,
            context_ref=auth_context_ref, scope_domains=scope.scope_domains, allow_http_replay=scope.allow_http_replay,
            ttl_s=math.ceil(limits.wall_time_s + limits.command_time_s + 60))
        from polymerhus.app.llm.skills import SkillStore, skill_agent_binding
        from polymerhus.app.llm.checkpoints import get_session_checkpointer, module_context
        from polymerhus.app.llm.compaction import build_role_compaction_middleware
        from polymerhus.app.llm.session import arun_session_turn
        from polymerhus.recon.domain.pod import default_exec_fn
        from langchain_core.messages import HumanMessage

        runner = BoundedExec(prefix=['python3', '/opt/polymerhus-js/cli.py', '--agent-url', agent_url,
                                    f'--reference={session_reference}'], session_id=address.thread_id,
                             exec_fn=exec_fn or default_exec_fn, limits=limits)
        if deadline is not None:
            runner.deadline = min(runner.deadline, deadline)
        retention_reconcile = {
            'status': 'not_run',
            'retry_attempts': 0,
            'maintenance_execs': 0,
            'gaps': [],
        }
        remaining = runner.deadline - time.monotonic()
        if remaining <= 0:
            retention_reconcile = {
                **retention_reconcile,
                'status': 'partial',
                'gaps': ['retention_reconcile_deadline'],
            }
            runner.gaps.append('retention_reconcile_deadline')
        else:
            reconcile_fn = (
                retention_reconcile_fn
                or _default_retention_reconcile
            )
            timeout_s = max(
                .001,
                min(RETENTION_RECONCILE_MAX_TIME_S, remaining),
            )
            try:
                if inspect.iscoroutinefunction(reconcile_fn):
                    reconcile_result = await asyncio.wait_for(
                        reconcile_fn(
                            root=root,
                            runner=runner,
                            reference=session_reference,
                            deadline=runner.deadline,
                            max_items=RETENTION_RECONCILE_MAX_ITEMS,
                        ),
                        timeout=timeout_s,
                    )
                else:
                    reconcile_result = await asyncio.wait_for(
                        asyncio.to_thread(
                            reconcile_fn,
                            root=root,
                            runner=runner,
                            reference=session_reference,
                            deadline=runner.deadline,
                            max_items=RETENTION_RECONCILE_MAX_ITEMS,
                        ),
                        timeout=timeout_s,
                    )
                if not isinstance(reconcile_result, dict):
                    raise ValueError(
                        'retention_reconcile_invalid_result'
                    )
                retention_reconcile = reconcile_result
                runner.maintenance_exec_attempts = int(
                    retention_reconcile.get('maintenance_execs') or 0
                )
                if retention_reconcile.get('status') not in {
                    'complete',
                    'no_work',
                }:
                    runner.gaps.append(
                        'retention_reconcile_incomplete'
                    )
            except TimeoutError:
                retention_reconcile = {
                    **retention_reconcile,
                    'status': 'partial',
                    'gaps': ['retention_reconcile_deadline'],
                    'remote_state_uncertain': True,
                }
                runner.gaps.append('retention_reconcile_deadline')
            except Exception as exc:
                retention_reconcile = {
                    **retention_reconcile,
                    'status': 'gap',
                    'gaps': [
                        getattr(
                            exc,
                            'reason',
                            'retention_reconcile_failed',
                        )
                    ],
                }
                runner.gaps.append('retention_reconcile_failed')
        binding = skill_agent_binding(ROLE, project_id=project_id, store=SkillStore(root_dir=root),
                                      exec_access='supplied CLI prefix + skill <name> / reference <name> <target>')
        brief = {'project_id': project_id, 'run_id': run_id, 'auth_context_label': auth_context_label,
                 'auth_context_ref': auth_context_ref, 'scope_domains': list(scope.scope_domains),
                 'exec_prefix': runner.command_prefix,
                 'budgets': limits.budget_dict()}
        try:
            if session_fn is None and model_factory is None:
                from polymerhus.app.llm.providers import JS_SPECIALIST_ROLES, validate_llm_config
                validate_llm_config(JS_SPECIALIST_ROLES)
            with module_context('recon'):
                cp = checkpointer if checkpointer is not None else get_session_checkpointer()
                mw = middleware if middleware is not None else [await asyncio.wait_for(
                    asyncio.to_thread(build_role_compaction_middleware, ROLE),
                    timeout=max(.001, runner.deadline - time.monotonic()))]
                turn = await asyncio.wait_for((session_fn or arun_session_turn)(ROLE, address,
                    [HumanMessage(content=json.dumps(brief))], checkpointer=cp, tools=[runner.tool()],
                    middleware=[*mw, *binding.middleware], context=binding.context,
                    system_prompt=_load_prompt(), model_factory=model_factory, observe=observe,
                    extra_tags=[run_id, project_id], usage_scope=project_id,
                    read_timeout_s=limits.wall_time_s),
                    timeout=max(.001, runner.deadline - time.monotonic()))
                if turn.blackloop:
                    runner.gaps.append('model_blackloop')
        except TimeoutError:
            runner.gaps.append('time_budget_exhausted')
        except asyncio.CancelledError:
            runner.gaps.append('interrupted')
            raise
        except Exception as exc:
            last_frame = traceback.extract_tb(exc.__traceback__)[-1]
            logger.warning(
                "js specialist session failed: %s at %s:%s (%s)",
                type(exc).__name__,
                Path(last_frame.filename).name,
                last_frame.lineno,
                last_frame.name,
            )
            runner.gaps.append('specialist_session_failed')
        finally:
            summary = {'project_id': project_id, 'run_id': run_id,
                       'auth_context_ref': auth_context_ref, 'thread_id': address.thread_id,
                       'retention_reconcile': retention_reconcile,
                       **runner.summary()}
            write_text_atomic(summary_path, json.dumps(summary, indent=2))
        return summary
    return dispatch
