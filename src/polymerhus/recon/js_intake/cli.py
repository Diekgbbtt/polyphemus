"""Installed in Kali with kali_worker.py; standard library only, no app data mount."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_scan_local_file = None
# Shared wire contract; this module remains standard-library-only in Kali.
MAX_BEHAVIOR_RECORD_BYTES = 4096
MAX_BEHAVIOR_INPUT_BYTES = 8192
# shlex can expand each apostrophe into five characters; include prefix headroom.
MAX_BEHAVIOR_COMMAND_CHARS = 32768


def behavior_record_size(record):
    return len(json.dumps(record, sort_keys=True, separators=(',', ':')).encode('utf-8'))


def behavior_size_rejection(actual_bytes, *, size_basis='canonical_json_bytes', max_bytes=None):
    return {'error': 'behavior_record_too_large', 'actual_bytes': actual_bytes,
            'max_bytes': MAX_BEHAVIOR_RECORD_BYTES if max_bytes is None else max_bytes,
            'size_basis': size_basis}


class RecoveryDeadline(TimeoutError):
    pass


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RecoveryDeadline('recovery_deadline')
    return remaining


def _run_with_deadline(callback, deadline):
    if deadline is None:
        return callback()
    finished = threading.Event()
    outcome = {}

    def run():
        try:
            outcome['value'] = callback()
        except BaseException as exc:
            outcome['error'] = exc
        finally:
            finished.set()

    threading.Thread(target=run, daemon=True).start()
    if not finished.wait(_remaining(deadline)):
        raise RecoveryDeadline('recovery_deadline')
    if 'error' in outcome:
        raise outcome['error']
    return outcome['value']


def operation_parser():
    parser = argparse.ArgumentParser(exit_on_error=False)
    commands = parser.add_subparsers(dest='operation', required=True)
    commands.add_parser('context')
    commands.add_parser('notes')
    for name in ('skill', 'reference'):
        command = commands.add_parser(name)
        command.add_argument('name')
        if name == 'reference':
            command.add_argument('target')
    for name in ('lead', 'acquire'):
        commands.add_parser(name).add_argument('lead_id')
    inventory = commands.add_parser('inventory')
    inventory.add_argument('--limit', type=int, default=5, choices=range(1, 11))
    inventory.add_argument('--cursor')
    commands.add_parser('note').add_argument('--text', required=True)
    commands.add_parser('scan').add_argument('lead_id')
    graph_candidates = commands.add_parser('graph-candidates')
    graph_candidates.add_argument('lead_id')
    graph_candidates.add_argument('--limit', type=int, default=5, choices=range(1, 11))
    graph_candidates.add_argument('--cursor')
    commands.add_parser('graph-note').add_argument('--record', required=True)
    scan_results = commands.add_parser('scan-results')
    scan_results.add_argument('lead_id')
    scan_results.add_argument('--mode', choices=('urls', 'secrets'))
    scan_results.add_argument('--limit', type=int, default=5, choices=range(1, 11))
    scan_results.add_argument('--cursor')
    commands.add_parser('recover').add_argument('lead_id')
    recovered = commands.add_parser('recovered-sources')
    recovered.add_argument('lead_id')
    recovered.add_argument('--limit', type=int, default=5, choices=range(1, 11))
    recovered.add_argument('--cursor')
    commands.add_parser('recovered-source').add_argument('source_id')
    commands.add_parser('structure').add_argument('lead_id')
    structure_items = commands.add_parser('structure-items')
    structure_items.add_argument('lead_id')
    structure_items.add_argument(
        '--kind',
        choices=('import', 'module', 'dependency', 'chunk', 'loader'),
    )
    structure_items.add_argument(
        '--limit',
        type=int,
        default=5,
        choices=range(1, 11),
    )
    structure_items.add_argument('--cursor')
    commands.add_parser('structure-item').add_argument('item_id')
    commands.add_parser('acquire-reference').add_argument('item_id')
    read_code = commands.add_parser('read-code')
    selectors = read_code.add_mutually_exclusive_group(required=True)
    selectors.add_argument('--item')
    selectors.add_argument('--source')
    selectors.add_argument('--match')
    read_code.add_argument('--bytes', type=int, default=4096)
    read_code.add_argument('--cursor')
    search_code = commands.add_parser('search-code')
    search_code.add_argument('lead_id')
    search_code.add_argument('--text', required=True)
    search_code.add_argument('--limit', type=int, default=5, choices=range(1, 11))
    search_code.add_argument('--cursor')
    triage_select = commands.add_parser('triage-select')
    triage_selectors = triage_select.add_mutually_exclusive_group(required=True)
    triage_selectors.add_argument('--item')
    triage_selectors.add_argument('--source')
    triage_selectors.add_argument('--match')
    triage_select.add_argument('--question', required=True)
    triage_select.add_argument(
        '--priority',
        choices=('high', 'normal', 'low'),
        default='normal',
    )
    triage_update = commands.add_parser('triage-update')
    triage_update.add_argument('span_id')
    triage_update.add_argument(
        '--state',
        required=True,
        choices=('inspected', 'deferred', 'unresolved'),
    )
    triage_update.add_argument('--read-id')
    triage_update.add_argument('--reason', default='')
    triage_list = commands.add_parser('triage-list')
    triage_list.add_argument('--limit', type=int, default=5, choices=range(1, 11))
    triage_list.add_argument('--cursor')
    behavior_save = commands.add_parser('behavior-save')
    behavior_save.add_argument('--record', required=True)
    behavior_save.add_argument('--dependency', action='append', default=[])
    behavior_save.add_argument(
        '--deadline-s',
        type=float,
        help=argparse.SUPPRESS,
    )
    behavior_list = commands.add_parser('behavior-list')
    behavior_list.add_argument(
        '--limit',
        type=int,
        default=5,
        choices=range(1, 11),
    )
    behavior_list.add_argument('--cursor')
    read_confirm = commands.add_parser('code-read-confirm')
    read_confirm.add_argument('read_id')
    return parser


def parse_operation(tokens):
    return vars(operation_parser().parse_args(tokens))


def _post_json(
    url,
    reference,
    payload,
    *,
    timeout=30,
    deadline=None,
    headers=None,
):
    request = Request(
        url,
        data=json.dumps(payload).encode(),
        method='POST',
        headers={
            'Content-Type': 'application/json',
            'X-JS-Intake-Reference': reference,
            **dict(headers or {}),
        },
    )
    def perform():
        request_timeout = timeout
        if deadline is not None:
            request_timeout = min(timeout, _remaining(deadline))
        try:
            with urlopen(request, timeout=request_timeout) as response:
                body = response.read(16385)
            if len(body) > 16384:
                return {'error': 'bridge_output_limit'}
            return json.loads(body)
        except RecoveryDeadline:
            raise
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read(16385) or b'{}')
            except Exception:
                payload = {}
            detail = payload.get('detail')
            if (
                exc.code == 422 and isinstance(detail, dict)
                and detail.get('error') in {
                    'behavior_record_too_large', 'behavior_read_not_delivered',
                }
            ):
                return {key: detail[key] for key in (
                    'error', 'actual_bytes', 'max_bytes', 'size_basis',
                    'invalid_fields', 'invalid_count',
                ) if key in detail}
            return {
                'error': (
                    'unknown_or_expired_reference'
                    if exc.code == 403
                    else str(
                        payload.get('detail') or f'bridge_http_{exc.code}'
                    )
                )
            }
        except Exception:
            return {'error': 'bridge_unavailable'}

    try:
        return _run_with_deadline(perform, deadline)
    except RecoveryDeadline:
        return {
            'error': 'recovery_deadline',
            'remote_outcome_uncertain': True,
        }


def _rpc(
    agent_url,
    reference,
    payload,
    *,
    deadline=None,
    forward_deadline=False,
):
    operation = str(payload.get('operation') or '').replace('-', '_')
    body = {**payload, 'operation': operation}
    if operation == 'scan_results' and not body.get('mode'):
        body.pop('mode', None)
    headers = None
    if forward_deadline and deadline is not None:
        try:
            remaining = _remaining(deadline)
        except RecoveryDeadline:
            return {
                'error': 'recovery_deadline',
                'remote_outcome_uncertain': True,
            }
        headers = {
            'X-JS-Remaining-Seconds': f'{remaining:.3f}',
        }
    return _post_json(
        agent_url.rstrip('/') + '/recon/js-specialist/rpc',
        reference,
        body,
        deadline=deadline,
        headers=headers,
    )


def _submit_scan(agent_url, reference, lead_id, result, mode):
    return _post_json(
        agent_url.rstrip('/') + '/recon/js-specialist/scan/submit',
        reference,
        {
            'lead_id': lead_id,
            'mode': mode,
            'result': result,
        },
        timeout=45,
    )


def _post_bytes(
    agent_url,
    reference,
    path,
    body,
    *,
    headers=None,
    timeout=45,
    deadline=None,
):
    request = Request(
        agent_url.rstrip('/') + path,
        data=body,
        method='POST',
        headers={
            'Content-Type': 'application/javascript',
            'X-JS-Intake-Reference': reference,
            **dict(headers or {}),
        },
    )
    def perform():
        request_timeout = timeout
        if deadline is not None:
            request_timeout = min(timeout, _remaining(deadline))
        try:
            with urlopen(request, timeout=request_timeout) as response:
                payload = response.read(65537)
            if len(payload) > 65536:
                return {'error': 'bridge_output_limit'}
            return json.loads(payload)
        except RecoveryDeadline:
            raise
        except HTTPError as exc:
            try:
                value = json.loads(exc.read() or b'{}')
            except Exception:
                value = {}
            return {
                'error': str(value.get('detail') or f'bridge_http_{exc.code}')
            }
        except Exception:
            return {'error': 'bridge_unavailable'}

    try:
        return _run_with_deadline(perform, deadline)
    except RecoveryDeadline:
        return {
            'error': 'recovery_deadline',
            'remote_outcome_uncertain': True,
        }


def _get_bytes(
    agent_url,
    reference,
    source_id,
    max_bytes,
    *,
    deadline=None,
):
    request = Request(
        agent_url.rstrip('/')
        + f'/recon/js-analysis/recovery/artifact/{source_id}',
        headers={'X-JS-Intake-Reference': reference},
    )
    def perform():
        request_timeout = 45
        if deadline is not None:
            request_timeout = min(request_timeout, _remaining(deadline))
        try:
            response = urlopen(request, timeout=request_timeout)
        except RecoveryDeadline:
            raise
        except HTTPError as exc:
            try:
                value = json.loads(exc.read() or b'{}')
            except Exception:
                value = {}
            raise RuntimeError(
                str(value.get('detail') or f'bridge_http_{exc.code}')
            ) from None
        try:
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise RuntimeError('artifact_size_limit')
            return body, response.headers
        finally:
            response.close()

    return _run_with_deadline(perform, deadline)


def _write_artifact(target, source_id, body):
    fd, temp_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f'.{source_id}.',
        suffix='.part',
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _recover_lead(
    agent_url,
    reference,
    lead_id,
    *,
    work_root='/work/js-analysis',
):
    started_at = time.monotonic()
    deadline = started_at + 35.0
    work_input = _rpc(
        agent_url,
        reference,
        {'operation': 'recovery_input', 'lead_id': lead_id},
        deadline=deadline,
    )
    if work_input.get('error'):
        if work_input.get('error') == 'recovery_deadline':
            return {
                'lead_id': lead_id,
                'status': 'partial',
                'source_count': 0,
                'available': 0,
                'transferred': 0,
                'skipped_existing': 0,
                'failures': ['recovery_deadline'],
                'gaps': [],
                'remote_state_uncertain': True,
            }
        return work_input
    run_id = str(work_input.get('run_id') or '')
    digest = str(work_input.get('sha256') or '')
    size = work_input.get('size')
    work_ref = str(work_input.get('work_file_ref') or '')
    if (
        not _SAFE_COMPONENT.fullmatch(run_id)
        or not _SHA256.fullmatch(digest)
        or not isinstance(size, int)
        or size < 0
        or size > 8 * 1024 * 1024
        or work_ref != f'/work/js-analysis/{run_id}/{digest}.js'
    ):
        return {'error': 'invalid_recovery_input'}
    js_path = Path(work_root) / Path(work_ref).relative_to('/work/js-analysis')
    if not js_path.is_file():
        return {'error': 'acquired_source_missing'}
    js_bytes = js_path.read_bytes()
    if len(js_bytes) != size or hashlib.sha256(js_bytes).hexdigest() != digest:
        return {'error': 'acquired_source_mismatch'}
    started = _post_bytes(
        agent_url,
        reference,
        f'/recon/js-analysis/recovery/start/{lead_id}',
        js_bytes,
        headers={'X-JS-Work-SHA256': digest},
        deadline=deadline,
    )
    if started.get('error'):
        if started.get('error') == 'recovery_deadline':
            return {
                'lead_id': lead_id,
                'status': 'partial',
                'source_count': 0,
                'available': 0,
                'transferred': 0,
                'skipped_existing': 0,
                'failures': ['recovery_deadline'],
                'gaps': [],
                'remote_state_uncertain': True,
            }
        return started
    deadline_s = float(started.get('deadline_s') or 35.0)
    deadline = min(deadline, started_at + deadline_s)
    cursor = None
    transferred = 0
    skipped = 0
    failures = []
    available = 0
    total = 0
    remote_state_uncertain = False
    while True:
        try:
            _remaining(deadline)
        except RecoveryDeadline:
            failures.append('recovery_deadline')
            break
        page = _rpc(
            agent_url,
            reference,
            {
                'operation': 'recovery_sources',
                'lead_id': lead_id,
                'limit': 10,
                **({'cursor': cursor} if cursor else {}),
            },
            deadline=deadline,
        )
        if page.get('error'):
            failures.append(page['error'])
            if page.get('error') == 'recovery_deadline':
                remote_state_uncertain = True
            break
        total = int(page.get('total') or 0)
        for source in page.get('sources', []):
            if time.monotonic() >= deadline:
                failures.append('recovery_deadline')
                break
            if source.get('status') == 'failed':
                failures.append(str(source.get('failure_reason') or 'source_failed'))
                continue
            source_id = str(source.get('source_id') or '')
            expected_sha = str(source.get('content_sha256') or '')
            expected_size = int(source.get('size') or 0)
            target_ref = str(source.get('work_file_ref') or '')
            expected_target = (
                f'/work/js-analysis/{run_id}/recovered/'
                f'{expected_sha}.js'
            )
            if target_ref != expected_target:
                failures.append('invalid_work_file_ref')
                continue
            target = Path(work_root) / Path(target_ref).relative_to(
                '/work/js-analysis'
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            valid_local = (
                target.is_file()
                and target.stat().st_size == expected_size
                and hashlib.sha256(target.read_bytes()).hexdigest()
                == expected_sha
            )
            try:
                _remaining(deadline)
            except RecoveryDeadline:
                failures.append('recovery_deadline')
                break
            if not valid_local:
                try:
                    body, _headers = _get_bytes(
                        agent_url,
                        reference,
                        source_id,
                        8 * 1024 * 1024,
                        deadline=deadline,
                    )
                except RecoveryDeadline:
                    failures.append('recovery_deadline')
                    remote_state_uncertain = True
                    break
                except Exception as exc:
                    failures.append(str(exc))
                    _post_json(
                        agent_url.rstrip('/')
                        + '/recon/js-analysis/recovery/fail',
                        reference,
                        {
                            'source_id': source_id,
                            'failure_reason': 'transfer_failed',
                        },
                    )
                    continue
                try:
                    _remaining(deadline)
                except RecoveryDeadline:
                    failures.append('recovery_deadline')
                    break
                if (
                    len(body) != expected_size
                    or hashlib.sha256(body).hexdigest() != expected_sha
                ):
                    failures.append('artifact_hash_mismatch')
                    _post_json(
                        agent_url.rstrip('/')
                        + '/recon/js-analysis/recovery/fail',
                        reference,
                        {
                            'source_id': source_id,
                            'failure_reason': 'artifact_hash_mismatch',
                        },
                    )
                    continue
                try:
                    _run_with_deadline(
                        lambda: _write_artifact(target, source_id, body),
                        deadline,
                    )
                except RecoveryDeadline:
                    failures.append('recovery_deadline')
                    break
                transferred += 1
            else:
                skipped += 1
            try:
                _remaining(deadline)
            except RecoveryDeadline:
                failures.append('recovery_deadline')
                remote_state_uncertain = True
                break
            confirmation = _post_json(
                agent_url.rstrip('/')
                + '/recon/js-analysis/recovery/confirm',
                reference,
                {
                    'source_id': source_id,
                    'size': expected_size,
                    'sha256': expected_sha,
                    'work_file_ref': target_ref,
                },
                deadline=deadline,
            )
            if confirmation.get('error') == 'recovery_deadline':
                failures.extend(
                    ['recovery_deadline', 'confirmation_outcome_uncertain']
                )
                remote_state_uncertain = True
                break
            if confirmation.get('error'):
                failures.append('confirmation_outcome_uncertain')
                remote_state_uncertain = True
                break
            if confirmation.get('status') != 'available':
                failures.append(
                    str(confirmation.get('error') or 'confirmation_failed')
                )
                remote_state_uncertain = True
                break
            else:
                available += 1
        if failures and failures[-1] in {
            'recovery_deadline',
            'confirmation_outcome_uncertain',
            'confirmation_failed',
        }:
            break
        cursor = page.get('next_cursor')
        if not cursor:
            break
    return {
        'lead_id': lead_id,
        'map_id': started.get('map_id'),
        'status': (
            started.get('status')
            if not failures and available == total
            else 'partial'
        ),
        'source_count': total,
        'available': available,
        'transferred': transferred,
        'skipped_existing': skipped,
        'failures': list(dict.fromkeys(failures)),
        'gaps': started.get('gaps') or [],
        'remote_state_uncertain': remote_state_uncertain,
    }


def _scan_lead(agent_url, reference, lead_id):
    work_input = _rpc(
        agent_url,
        reference,
        {'operation': 'scan_input', 'lead_id': lead_id},
    )
    if work_input.get('error'):
        return work_input
    run_id = str(work_input.get('run_id') or '')
    digest = str(work_input.get('sha256') or '')
    size = work_input.get('size')
    work_ref = str(work_input.get('work_file_ref') or '')
    if (
        not _SAFE_COMPONENT.fullmatch(run_id)
        or not _SHA256.fullmatch(digest)
        or not isinstance(size, int)
        or size < 0
        or size > 8 * 1024 * 1024
        or work_ref != f'/work/js-analysis/{run_id}/{digest}.js'
    ):
        return {'error': 'invalid_scan_input'}

    try:
        from polymerhus.recon.js_acquisition import scan_worker
    except ModuleNotFoundError:
        import scan_worker  # type: ignore[no-redef]

    binary = scan_worker.binary_identity('jsluice')
    options = scan_worker.scan_options()
    scan_key = scan_worker.scan_key_for(
        source_sha256=digest,
        binary=binary,
        options=options,
        pattern_fingerprint=scan_worker.PATTERN_FINGERPRINT,
    )
    reused = _rpc(
        agent_url,
        reference,
        {
            'operation': 'scan_reuse',
            'lead_id': lead_id,
            'target': scan_key,
        },
    )
    if reused.get('reused'):
        return {
            'lead_id': lead_id,
            'status': reused.get('status', 'complete'),
            'scan_key': reused.get('scan_key', scan_key),
            'modes': reused.get('modes') or {},
            'reused': True,
        }

    source_path = Path('/work/js-analysis') / run_id / f'{digest}.js'
    scan = (_scan_local_file or scan_worker.scan_local_file)(
        source_path,
        expected_sha256=digest,
        expected_size=size,
        executable=binary.get('path') or 'jsluice',
        binary_info=binary,
    )
    if not scan.get('modes'):
        return {
            'lead_id': lead_id,
            'status': 'failed',
            'failure_reason': scan.get('error') or 'scan_failed',
            'scan_key': scan.get('scan_key'),
        }

    submissions = {}
    submission_errors = {}
    for mode in ('urls', 'secrets'):
        submitted = _submit_scan(
            agent_url,
            reference,
            lead_id,
            scan,
            mode,
        )
        submissions[mode] = submitted
        if submitted.get('error'):
            submission_errors[mode] = submitted['error']
    status = (
        'reconcile_required'
        if submission_errors
        else scan.get('status', 'partial')
    )
    return {
        'lead_id': lead_id,
        'status': status,
        'scan_key': scan.get('scan_key'),
        'modes': scan.get('modes') or {},
        'candidate_count': sum(
            int(state.get('candidate_count') or 0)
            for state in (scan.get('modes') or {}).values()
        ),
        'submission_errors': submission_errors,
        'reused': False,
    }


def _structure_lead(
    agent_url,
    reference,
    lead_id,
    *,
    work_root='/work/js-analysis',
):
    deadline = time.monotonic() + 20.0
    work_input = _rpc(
        agent_url,
        reference,
        {'operation': 'structure_input', 'lead_id': lead_id},
        deadline=deadline,
    )
    if work_input.get('error'):
        return {
            **work_input,
            'lead_id': lead_id,
            'status': 'partial',
            'failure_reason': work_input['error'],
        }
    run_id = str(work_input.get('run_id') or '')
    digest = str(work_input.get('sha256') or '')
    size = work_input.get('size')
    work_ref = str(work_input.get('work_file_ref') or '')
    if (
        not _SAFE_COMPONENT.fullmatch(run_id)
        or not _SHA256.fullmatch(digest)
        or not isinstance(size, int)
        or size < 0
        or size > 8 * 1024 * 1024
        or work_ref != f'/work/js-analysis/{run_id}/{digest}.js'
    ):
        return {
            'lead_id': lead_id,
            'status': 'failed',
            'failure_reason': 'invalid_structure_input',
        }
    source_path = Path(work_root) / Path(work_ref).relative_to(
        '/work/js-analysis'
    )
    try:
        source_bytes = _run_with_deadline(source_path.read_bytes, deadline)
    except RecoveryDeadline:
        return {
            'lead_id': lead_id,
            'status': 'partial',
            'failure_reason': 'structure_deadline',
            'remote_state_uncertain': True,
        }
    except OSError:
        return {
            'lead_id': lead_id,
            'status': 'failed',
            'failure_reason': 'acquired_source_missing',
        }
    if (
        len(source_bytes) != size
        or hashlib.sha256(source_bytes).hexdigest() != digest
    ):
        return {
            'lead_id': lead_id,
            'status': 'failed',
            'failure_reason': 'acquired_source_mismatch',
        }
    try:
        remaining = max(0.001, _remaining(deadline))
    except RecoveryDeadline:
        return {
            'lead_id': lead_id,
            'status': 'partial',
            'failure_reason': 'structure_deadline',
            'remote_state_uncertain': True,
        }
    result = _post_bytes(
        agent_url,
        reference,
        f'/recon/js-analysis/structure/start/{lead_id}',
        source_bytes,
        headers={
            'X-JS-Work-SHA256': digest,
            'X-JS-Remaining-Seconds': f'{remaining:.3f}',
        },
        deadline=deadline,
    )
    if result.get('error') == 'recovery_deadline':
        return {
            'lead_id': lead_id,
            'status': 'partial',
            'failure_reason': 'structure_deadline',
            'remote_state_uncertain': True,
        }
    return result


def _acquire_reference(agent_url, reference, item_id):
    registered = _rpc(
        agent_url,
        reference,
        {'operation': 'acquire_reference', 'target': item_id},
    )
    if registered.get('error'):
        return registered
    lead_id = str(registered.get('lead_id') or '')
    if not _SAFE_COMPONENT.fullmatch(lead_id):
        return {'error': 'invalid_derived_lead'}
    try:
        from polymerhus.recon.js_acquisition.kali_worker import (
            acquire_lead_to_work_file,
        )
    except ModuleNotFoundError:
        from kali_worker import acquire_lead_to_work_file
    acquired = acquire_lead_to_work_file(
        agent_url=agent_url,
        reference=reference,
        lead_id=lead_id,
        timeout_s=45.0,
    )
    return {
        **registered,
        **acquired,
        'parent_item_id': item_id,
    }


def _work_path(work_root, work_ref):
    prefix = '/work/js-analysis/'
    if not isinstance(work_ref, str) or not work_ref.startswith(prefix):
        raise ValueError('invalid_work_file_ref')
    relative = Path(work_ref).relative_to('/work/js-analysis')
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('invalid_work_file_ref')
    return Path(work_root) / relative


def _selector_from_args(args):
    for selector_type, key in (
        ('item', 'item'),
        ('source', 'source'),
        ('match', 'match'),
    ):
        value = args.get(key)
        if value:
            return selector_type, str(value)
    return None


def _read_code(
    agent_url,
    reference,
    args,
    *,
    work_root='/work/js-analysis',
    window_bytes=None,
    cursor=None,
):
    deadline = time.monotonic() + 5.0
    selector = _selector_from_args(args)
    if selector is None:
        return {'error': 'exactly_one_selector_required'}
    selector_type, selector_id = selector
    target = _rpc(
        agent_url,
        reference,
        {
            'operation': 'code_read_input',
            'selector_type': selector_type,
            'target': selector_id,
        },
        deadline=deadline,
    )
    if target.get('error'):
        return target
    digest = str(target.get('content_sha256') or '')
    size = target.get('size')
    try:
        path = _work_path(work_root, target.get('work_file_ref'))
    except ValueError:
        return {'error': 'invalid_code_input'}
    if (
        not _SHA256.fullmatch(digest)
        or not isinstance(size, int)
        or size < 0
        or size > 8 * 1024 * 1024
    ):
        return {'error': 'invalid_code_input'}
    try:
        body = _run_with_deadline(path.read_bytes, deadline)
    except RecoveryDeadline:
        return {
            'error': 'code_read_deadline',
            'remote_outcome_uncertain': True,
        }
    except OSError:
        return {'error': 'code_artifact_missing'}
    if len(body) != size or hashlib.sha256(body).hexdigest() != digest:
        return {'error': 'code_artifact_mismatch'}
    result = _post_bytes(
        agent_url,
        reference,
        '/recon/js-specialist/code/read',
        body,
        headers={
            'X-JS-Selector-Type': selector_type,
            'X-JS-Selector-Id': selector_id,
            'X-JS-Window-Bytes': str(window_bytes or args.get('bytes') or 4096),
            'X-JS-Code-Cursor': cursor or '',
        },
        deadline=deadline,
    )
    if result.get('error') == 'recovery_deadline':
        return {
            'error': 'code_read_deadline',
            'remote_outcome_uncertain': True,
        }
    return result


def _search_code(
    agent_url,
    reference,
    *,
    lead_id,
    text,
    limit,
    cursor,
    work_root='/work/js-analysis',
):
    deadline = time.monotonic() + 5.0
    if cursor:
        resumed = _rpc(
            agent_url,
            reference,
            {
                'operation': 'code_search_resume',
                'lead_id': lead_id,
                'text': text,
                'limit': limit,
                'cursor': cursor,
            },
            deadline=deadline,
        )
        if resumed.get('error') or resumed.get('mode') != 'scan':
            return resumed
        inventory = resumed
        source_cursor = resumed.get('sources_next_cursor')
        while source_cursor:
            page = _rpc(
                agent_url,
                reference,
                {
                    'operation': 'code_search_resume',
                    'lead_id': lead_id,
                    'text': text,
                    'limit': limit,
                    'cursor': source_cursor,
                },
                deadline=deadline,
            )
            if page.get('error'):
                return page
            inventory['sources'].extend(page.get('sources') or [])
            source_cursor = page.get('sources_next_cursor')
    else:
        inventory = {'sources': [], 'coverage_gaps': []}
        inventory_cursor = None
        while True:
            page = _rpc(
                agent_url,
                reference,
                {
                    'operation': 'code_search_input',
                    'lead_id': lead_id,
                    'limit': 10,
                    **(
                        {'cursor': inventory_cursor}
                        if inventory_cursor
                        else {}
                    ),
                },
                deadline=deadline,
            )
            if page.get('error'):
                return page
            inventory['sources'].extend(page.get('sources') or [])
            inventory['coverage_gaps'].extend(
                page.get('coverage_gaps') or []
            )
            inventory_cursor = page.get('next_cursor')
            if not inventory_cursor:
                break
            if time.monotonic() >= deadline:
                return {
                    'error': 'code_search_deadline',
                    'remote_outcome_uncertain': True,
                }
    if inventory.get('error'):
        return inventory
    contents = {}
    examined = 0
    for source in inventory.get('sources', []):
        if time.monotonic() >= deadline:
            return {
                'error': 'code_search_deadline',
                'remote_outcome_uncertain': True,
            }
        digest = str(source.get('content_sha256') or '')
        size = source.get('size')
        source_id = str(source.get('source_id') or '')
        if (
            not source_id
            or not _SHA256.fullmatch(digest)
            or not isinstance(size, int)
            or size < 0
            or size > 8 * 1024 * 1024
        ):
            return {'error': 'invalid_search_input'}
        try:
            path = _work_path(work_root, source.get('work_file_ref'))
        except ValueError:
            return {'error': 'invalid_search_input'}
        if examined + size > 64 * 1024 * 1024:
            break
        try:
            body = _run_with_deadline(path.read_bytes, deadline)
        except RecoveryDeadline:
            return {
                'error': 'code_search_deadline',
                'remote_outcome_uncertain': True,
            }
        except OSError:
            continue
        if len(body) != size or hashlib.sha256(body).hexdigest() != digest:
            return {'error': 'search_content_mismatch'}
        contents[source_id] = base64.b64encode(body).decode()
        examined += len(body)
    try:
        remaining = max(0.001, _remaining(deadline))
    except RecoveryDeadline:
        return {
            'error': 'code_search_deadline',
            'remote_outcome_uncertain': True,
        }
    return _post_json(
        agent_url.rstrip('/') + '/recon/js-specialist/code/search/submit',
        reference,
        {
            'lead_id': lead_id,
            'text': text,
            'limit': limit,
            'contents': contents,
            'max_examined_bytes': examined,
            'deadline_s': min(5.0, remaining),
            'resume_cursor': (
                inventory.get('scan_resume_cursor') if cursor else None
            ),
        },
        deadline=deadline,
    )


def _behavior_save(
    agent_url,
    reference,
    args,
    *,
    work_root='/work/js-analysis',
):
    started = time.monotonic()
    requested_timeout = args.get('deadline_s')
    if requested_timeout is not None and requested_timeout <= 0:
        return {'error': 'invalid_behavior_deadline'}
    deadline = started + (
        min(42.0, requested_timeout)
        if requested_timeout is not None
        else 42.0
    )
    raw = args['record']
    raw_size = len(raw.encode('utf-8'))
    if raw_size > MAX_BEHAVIOR_INPUT_BYTES:
        return behavior_size_rejection(raw_size, size_basis='raw_json_input_bytes',
                                       max_bytes=MAX_BEHAVIOR_INPUT_BYTES)
    try:
        record = json.loads(raw)
    except (TypeError, ValueError):
        return {'error': 'invalid_behavior_record'}
    if not isinstance(record, dict):
        return {'error': 'invalid_behavior_record'}
    size = behavior_record_size(record)
    if size > MAX_BEHAVIOR_RECORD_BYTES:
        return behavior_size_rejection(size)
    dependencies = []
    for raw_dependency in args.get('dependency') or []:
        if len(raw_dependency.encode('utf-8')) > 512:
            return {'error': 'dependency_nomination_too_large'}
        try:
            dependency = json.loads(raw_dependency)
        except (TypeError, ValueError):
            return {'error': 'invalid_dependency_nomination'}
        if not isinstance(dependency, dict):
            return {'error': 'invalid_dependency_nomination'}
        dependencies.append(dependency)
    result = _rpc(
        agent_url,
        reference,
        {
            'operation': 'behavior_save',
            'record': record,
            'dependencies': dependencies,
        },
        deadline=deadline,
        forward_deadline=True,
    )
    if result.get('error') or not result.get('behavior_id'):
        return result
    retention = dict(result.get('retention') or {})
    initial_gaps = [
        dict(gap)
        for gap in (retention.get('gaps') or [])
        if isinstance(gap, dict)
    ]
    requests = retention.pop('transfer_requests', [])
    result['record_saved'] = True
    transfer_gaps = []
    for request in requests:
        if not isinstance(request, dict):
            transfer_gaps.append('invalid_retention_transfer_request')
            continue
        request_id = str(request.get('request_id') or '')
        digest = str(request.get('sha256') or '')
        size = request.get('size_bytes')
        try:
            path = _work_path(work_root, request.get('work_file_ref'))
        except ValueError:
            transfer_gaps.append('invalid_retention_work_file')
            continue
        try:
            body = _run_with_deadline(path.read_bytes, deadline)
        except RecoveryDeadline:
            transfer_gaps.append('retention_transfer_deadline')
            continue
        except Exception:
            transfer_gaps.append('retention_work_file_unavailable')
            continue
        if (
            not _SHA256.fullmatch(digest)
            or not isinstance(size, int)
            or len(body) != size
            or hashlib.sha256(body).hexdigest() != digest
        ):
            transfer_gaps.append('retention_transfer_content_mismatch')
            continue
        try:
            remaining = _remaining(deadline)
        except RecoveryDeadline:
            transfer_gaps.append('retention_transfer_deadline')
            continue
        transfer = _post_bytes(
            agent_url,
            reference,
            '/recon/js-specialist/retention/transfer',
            body,
            headers={
                'X-JS-Retention-Request': request_id,
                'X-JS-Remaining-Seconds': f'{remaining:.3f}',
            },
            deadline=deadline,
        )
        if transfer.get('error'):
            transfer_gaps.append(str(transfer['error']))
    status = _rpc(
        agent_url,
        reference,
        {
            'operation': 'retention_status',
            'behavior_id': result['behavior_id'],
            'behavior_revision': int(result['revision']),
        },
        deadline=deadline,
    )
    if status.get('error'):
        result['retention'] = {
            **retention,
            'status': 'pending',
            'gaps': [
                *(retention.get('gaps') or []),
                {'reason': 'retention_status_uncertain'},
            ],
        }
        return result
    links = status.get('links') or []
    gaps = [
        *initial_gaps,
        *[
            {
                'sha256': link.get('sha256'),
                'read_id': link.get('read_id'),
                'reason': link.get('failure_reason') or 'retention_gap',
            }
            for link in links
            if link.get('status') == 'gap'
        ],
        *[{'reason': reason} for reason in transfer_gaps],
    ]
    if not links:
        gaps.append({'reason': 'retention_links_missing'})
    deduplicated_gaps = []
    seen_gaps = set()
    for gap in gaps:
        identity = json.dumps(
            gap,
            sort_keys=True,
            separators=(',', ':'),
        )
        if identity in seen_gaps:
            continue
        seen_gaps.add(identity)
        deduplicated_gaps.append(gap)
    gaps = deduplicated_gaps
    pending_count = int(status.get('pending_count') or 0)
    retained_count = int(status.get('retained_count') or 0)
    result['retention'] = {
        'status': (
            'complete'
            if links and not gaps and not pending_count and retained_count
            else 'pending'
            if pending_count
            else 'partial'
            if retained_count
            else 'gap'
        ),
        'retained_count': retained_count,
        'pending_count': pending_count,
        'gap_count': len(gaps),
        'gaps': gaps,
        'links': [
            {
                'sha256': link.get('sha256'),
                'origin': link.get('origin'),
                'read_id': link.get('read_id'),
                'status': link.get('status'),
                'failure_reason': link.get('failure_reason'),
            }
            for link in status.get('links') or []
        ],
    }
    return result


def invoke_operation(agent_url, reference, args):
    operation = args['operation']
    if operation == 'acquire':
        try:
            from polymerhus.recon.js_acquisition.kali_worker import acquire_lead_to_work_file
        except ModuleNotFoundError:
            from kali_worker import acquire_lead_to_work_file
        return acquire_lead_to_work_file(agent_url=agent_url, reference=reference, lead_id=args['lead_id'])
    if operation == 'scan':
        return _scan_lead(agent_url, reference, args['lead_id'])
    if operation == 'recover':
        return _recover_lead(agent_url, reference, args['lead_id'])
    if operation == 'structure':
        return _structure_lead(agent_url, reference, args['lead_id'])
    if operation == 'structure-items':
        return _rpc(
            agent_url,
            reference,
            {
                'operation': 'structure_items',
                'lead_id': args['lead_id'],
                'kind': args.get('kind') or '',
                'limit': args['limit'],
                'cursor': args.get('cursor'),
            },
        )
    if operation == 'structure-item':
        return _rpc(
            agent_url,
            reference,
            {
                'operation': 'structure_item',
                'target': args['item_id'],
            },
        )
    if operation == 'acquire-reference':
        return _acquire_reference(agent_url, reference, args['item_id'])
    if operation == 'read-code':
        return _read_code(
            agent_url,
            reference,
            args,
            window_bytes=args.get('bytes'),
            cursor=args.get('cursor'),
        )
    if operation == 'search-code':
        return _search_code(
            agent_url,
            reference,
            lead_id=args['lead_id'],
            text=args['text'],
            limit=args['limit'],
            cursor=args.get('cursor'),
        )
    if operation == 'triage-select':
        selector = _selector_from_args(args)
        if selector is None:
            return {'error': 'exactly_one_selector_required'}
        return _rpc(
            agent_url,
            reference,
            {
                'operation': 'triage_select',
                'selector_type': selector[0],
                'target': selector[1],
                'question': args['question'],
                'priority': args['priority'],
            },
        )
    if operation == 'triage-update':
        return _rpc(
            agent_url,
            reference,
            {
                'operation': 'triage_update',
                'target': args['span_id'],
                'state': args['state'],
                'read_id': args.get('read_id') or '',
                'reason': args.get('reason') or '',
            },
        )
    if operation == 'triage-list':
        return _rpc(
            agent_url,
            reference,
            {
                'operation': 'triage_list',
                'limit': args['limit'],
                'cursor': args.get('cursor'),
            },
        )
    if operation == 'graph-candidates':
        return _rpc(agent_url, reference, {'operation': 'graph_candidates',
                    'lead_id': args['lead_id'], 'limit': args['limit'], 'cursor': args.get('cursor')})
    if operation == 'graph-note':
        try:
            record = json.loads(args['record'])
        except (ValueError, TypeError):
            return {'error': 'invalid_graph_annotation'}
        return _rpc(agent_url, reference, {'operation': 'graph_note', 'record': record})
    if operation == 'behavior-save':
        return _behavior_save(agent_url, reference, args)
    if operation == 'behavior-list':
        return _rpc(
            agent_url,
            reference,
            {
                'operation': 'behavior_list',
                'limit': args['limit'],
                'cursor': args.get('cursor'),
            },
        )
    if operation == 'code-read-confirm':
        return _rpc(
            agent_url,
            reference,
            {
                'operation': 'code_read_confirm',
                'read_id': args['read_id'],
            },
        )
    if operation == 'recovered-sources':
        return _rpc(
            agent_url,
            reference,
            {
                'operation': 'recovery_sources',
                'lead_id': args['lead_id'],
                'limit': args['limit'],
                'cursor': args.get('cursor'),
            },
        )
    if operation == 'recovered-source':
        return _rpc(
            agent_url,
            reference,
            {
                'operation': 'recovery_source',
                'target': args['source_id'],
            },
        )
    payload = dict(args)
    if operation == 'note':
        payload = {'operation': 'notes', 'command': 'write', 'note': args['text']}
    return _rpc(agent_url, reference, payload)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--agent-url', default='http://agent:8080')
    parser.add_argument('--reference', required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        result = invoke_operation(args.agent_url, args.reference, parse_operation(args.command))
    except Exception:
        result = {'error': 'invalid_command'}
    print(json.dumps(result, sort_keys=True))
    return 1 if result.get('error') or result.get('status') in {'failed', 'reconcile_required'} else 0


if __name__ == '__main__':
    raise SystemExit(main())
