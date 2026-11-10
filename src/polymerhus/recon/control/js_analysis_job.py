"""Native inventory input and one scoped JS specialist execution.

The normal run_job owns dispatch. This adapter owns bounded finalization,
never graph mutation: only the existing proposal/curator handoff writes L0.
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import hashlib
import math
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from polymerhus.app.atomic_write import write_text_atomic
from polymerhus.app.data_root import project_dir
from polymerhus.app.js_context.records import (
    MAX_DOCUMENT_BYTES,
    document_identity,
    validate_document,
)
from polymerhus.recon.control.js_context_writer import JsContextWriter
from polymerhus.recon.domain.js_graph_proposal import canonical_bytes, content_id
from polymerhus.recon.domain.types import AssetDelta, PodExport
from polymerhus.recon.js_intake.reader import (
    JsIntakeReader, issue_js_intake_reference, resolve_js_intake_reference,
    renew_js_intake_reference,
)

_CONTEXT_SNAPSHOT_SCHEMA = 1
_CONTEXT_GAP_LIMIT = 64
_SAFE_CONTEXT_ERROR = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
_CONTEXT_SUCCESS = frozenset({"published", "identical", "recovered"})


def _context_error(exc: Exception) -> str:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, str) and _SAFE_CONTEXT_ERROR.fullmatch(reason):
        return reason
    text = str(exc)
    if _SAFE_CONTEXT_ERROR.fullmatch(text):
        return text
    return "context_publication_failed"


def _context_analysis_coverage(unit_coverage: dict, closure: dict) -> dict:
    gaps = {
        gap
        for gap in (
            list((unit_coverage or {}).get("gaps") or [])
            + list((closure or {}).get("gaps") or [])
        )
        if isinstance(gap, str) and re.fullmatch("[a-z][a-z0-9_]{0,79}", gap)
    }
    input_status = (unit_coverage or {}).get("status")
    closure_status = (closure or {}).get("status")
    if input_status == "partial" or closure_status == "partial" or gaps:
        return {"status": "partial", "gaps": sorted(gaps)}
    return {"status": "complete", "gaps": []}


def _context_snapshot_ref(context_ref: str) -> str:
    return (
        "context-publications/"
        + content_id({"context_ref": context_ref})
        + ".json"
    )


def _context_scope(scope, run_id: str) -> dict:
    return {
        "project_id": scope.project_id,
        "run_id": run_id,
        "auth_ref": scope.context_ref,
    }


def _write_context_snapshot(path: Path, *, scope: dict, prepared: dict) -> dict:
    if path.is_symlink():
        raise ValueError("context_snapshot_corrupt")
    document = validate_document(prepared["document"])
    document_id = document_identity(document)
    if prepared.get("document_id") != document_id:
        raise ValueError("context_snapshot_integrity")
    if (
        document["context"]["project_id"] != scope["project_id"]
        or document["context"]["run_id"] != scope["run_id"]
        or document["context"]["auth_ref"] != scope["auth_ref"]
    ):
        raise ValueError("context_snapshot_scope_mismatch")
    envelope = {
        "schema_version": _CONTEXT_SNAPSHOT_SCHEMA,
        "scope": scope,
        "origin": document["context"]["origin"],
        "document_id": document_id,
        "document": document,
    }
    encoded = canonical_bytes(envelope)
    if len(encoded) > MAX_DOCUMENT_BYTES + 64 * 1024:
        raise ValueError("context_snapshot_size_limit")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    write_text_atomic(path, encoded.decode() + "\n")
    path.chmod(0o600)
    return envelope


def _load_context_snapshot(path: Path, *, scope: dict) -> dict:
    try:
        if path.is_symlink():
            raise ValueError("context_snapshot_corrupt")
        if path.stat().st_size > MAX_DOCUMENT_BYTES + 64 * 1024:
            raise ValueError("context_snapshot_size_limit")
        envelope = json.loads(path.read_text())
        if (
            not isinstance(envelope, dict)
            or set(envelope)
            != {"schema_version", "scope", "origin", "document_id", "document"}
            or envelope.get("schema_version") != _CONTEXT_SNAPSHOT_SCHEMA
            or envelope.get("scope") != scope
        ):
            raise ValueError("context_snapshot_scope_mismatch")
        document = validate_document(envelope.get("document"))
        document_id = document_identity(document)
        if envelope.get("document_id") != document_id:
            raise ValueError("context_snapshot_integrity")
        if envelope.get("origin") != document["context"]["origin"]:
            raise ValueError("context_snapshot_integrity")
        if (
            document["context"]["project_id"] != scope["project_id"]
            or document["context"]["run_id"] != scope["run_id"]
            or document["context"]["auth_ref"] != scope["auth_ref"]
        ):
            raise ValueError("context_snapshot_scope_mismatch")
        return {
            "status": "prepared",
            "document": document,
            "document_id": document_id,
            "coverage": document["context"]["coverage"]["status"],
            "behavior_count": len(document["behaviors"]),
            "evidence_count": len(document["evidence"]),
            "run_gaps": list(document["context"]["coverage"]["gaps"]),
        }
    except Exception:
        raise ValueError("context_snapshot_corrupt") from None


def _context_stats(state: dict) -> dict:
    value = dict(state.get("context_publication") or {})
    gaps = value.get("gaps")
    if isinstance(gaps, list):
        value["gaps"] = gaps[:_CONTEXT_GAP_LIMIT]
    return value


def prepare_js_inventory(*, project_id, run_id, context_ref='', scope_domains=(),
                         allow_http_replay=True, producer_outcomes=None, root=None, reader=None):
    """One workflow resource, including unavailable/empty coverage, never a graph node."""
    reference = issue_js_intake_reference(project_id, run_id, context_ref=context_ref,
        scope_domains=scope_domains, allow_http_replay=allow_http_replay)
    page = (reader or JsIntakeReader(root=root)).list(reference=reference, limit=1)
    coverage = page['coverage']
    gaps = [coverage['coverage_gap']] if coverage.get('coverage_gap') else []
    pods = page['pods']
    for producer, outcome in (producer_outcomes or {}).items():
        observed = [p for p in pods if p['producer'] == producer]
        if outcome.get('status') not in {'success', 'skipped'} or any(p.get('terminal_result') != 'success' or p.get('output_completeness') != 'complete' for p in observed):
            gaps.append('producer_incomplete')
        expected = outcome.get('pods')
        if expected is None or len(observed) < expected:
            gaps.append('producer_inventory_missing')
    clean = bool(coverage.get('inventory_present')) and bool(pods) and not gaps and all(
        p.get('terminal_result') == 'success' and p.get('output_completeness') == 'complete' for p in pods)
    lead_count = coverage['lead_count']
    state = 'ready' if lead_count else 'empty' if clean else 'unavailable'
    return {'resource': 'JSInventory', 'reference': reference, 'state': state,
            'coverage': {'status': 'complete' if clean else 'partial', 'lead_count': lead_count,
                         'gaps': sorted(set(gaps)), 'exhaustive': False}}


async def run_js_analysis_job(*, input_assets, run_id, phase, extra, root=None,
                              specialist_fn=None, prepare_fn=None, submit_fn=None,
                              limits=None, capture_store=None, context_writer=None):
    """Return zero exports for clean zero work, otherwise one honest execution export."""
    from polymerhus.recon.js_specialist.agent import SpecialistLimits, build_js_specialist
    from polymerhus.recon.control.js_graph_proposal import prepare_js_graph_proposal, submit_js_graph_proposal
    limits = limits or SpecialistLimits()
    deadline = time.monotonic() + limits.wall_time_s
    public_input = {'resource': 'JSInventory'}
    stats = {'executor': 'js_specialist', 'specialist_invocations': 0, 'coverage': {'status':'partial','gaps':[]}}
    def failed(reason):
        return [PodExport(input_asset=public_input, verdict='failed', error=reason, stats={**stats, 'gap':reason})]
    if len(input_assets) != 1:
        return failed('js_inventory_work_unit_required')
    unit = input_assets[0]
    try:
        scope = resolve_js_intake_reference(unit['reference'])
        if scope.project_id != extra.get('project_id') or scope.run_id != run_id:
            return failed('js_inventory_scope_mismatch')
        stats['coverage']=unit.get('coverage') or stats['coverage']
    except (ValueError, KeyError):
        return failed('js_inventory_reference_invalid')
    reference = renew_js_intake_reference(unit['reference'],ttl_s=math.ceil(limits.wall_time_s + 60))
    base = project_dir(scope.project_id, 'recon/js_analysis', root=root) / run_id
    base.mkdir(parents=True, exist_ok=True)
    state_path = base / ('native-job-' + content_id(scope.context_ref) + '.json')
    lock = state_path.with_suffix('.lock').open('a+')
    ownership={'active':False,'left':False}
    ownership_guard=threading.Lock()
    try:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return failed('js_analysis_in_progress')
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        policy = {'scope_domain':extra.get('scope_domain'), 'seed_domain':extra.get('seed_domain'),
                  'seed_root_type':extra.get('seed_root_type','Domain')}
        binding = {'project_id':scope.project_id,'run_id':run_id,'context_ref':scope.context_ref}
        if state and state.get('scope') != binding:
            return failed('js_job_state_scope_mismatch')
        def save():
            write_text_atomic(state_path,json.dumps(state,sort_keys=True)); state_path.chmod(0o600)
        async def bounded(fn, **kwargs):
            remaining=deadline-time.monotonic()
            if remaining <= 0: raise TimeoutError
            # Ownership follows the actual sync operation, not its cancellable
            # asyncio waiter. A late freeze/receipt cannot overwrite a newer run.
            with ownership_guard:
                ownership['active']=True
            started = threading.Event()
            def work():
                started.wait()
                try:
                    return fn(**kwargs)
                finally:
                    with ownership_guard:
                        ownership['active']=False
                        if ownership['left']:
                            lock.close()
            executor = None
            worker = None
            try:
                executor = ThreadPoolExecutor(
                    max_workers=1,
                    thread_name_prefix="js-analysis-finalize",
                )
                worker = executor.submit(work)
                started.set()
                stop_at = time.monotonic() + remaining
                while not worker.done():
                    if time.monotonic() >= stop_at:
                        raise TimeoutError
                    await asyncio.sleep(0.01)
                return worker.result()
            except Exception:
                if worker is None:
                    with ownership_guard:
                        ownership['active'] = False
                        if ownership['left']:
                            lock.close()
                raise
            finally:
                if executor is not None:
                    executor.shutdown(wait=False)
        publication_scope = _context_scope(scope, run_id)
        snapshot_ref = _context_snapshot_ref(scope.context_ref)
        snapshot_path = base / snapshot_ref

        def context_failure(error):
            existing = state.get('context_publication') or {}
            state['context_publication'] = {
                **existing,
                'run_id': run_id,
                'status': 'pending',
                'error': error,
            }
            if existing.get('snapshot_ref') or snapshot_path.exists():
                state['context_publication']['snapshot_ref'] = snapshot_ref
            save()

        def prepare_context_work():
            try:
                writer = context_writer or JsContextWriter(root=root)
                prepared = writer.prepare(
                    reference=reference,
                    origin=extra.get('application_origin'),
                    analysis_coverage=_context_analysis_coverage(
                        unit.get('coverage') or {},
                        state.get('closure') or {},
                    ),
                    deadline=deadline,
                )
            except TimeoutError:
                context_failure('context_prepare_timeout')
                return None
            except Exception as exc:
                context_failure(_context_error(exc))
                return None
            try:
                _write_context_snapshot(
                    snapshot_path,
                    scope=publication_scope,
                    prepared=prepared,
                )
                snapshot_sha256 = hashlib.sha256(
                    snapshot_path.read_bytes()
                ).hexdigest()
            except Exception:
                context_failure('context_snapshot_write_failed')
                return None
            state['context_publication'] = {
                'status': 'prepared',
                'run_id': run_id,
                'snapshot_ref': snapshot_ref,
                'snapshot_sha256': snapshot_sha256,
                'document_id': prepared['document_id'],
                'coverage': prepared['coverage'],
                'behavior_count': prepared['behavior_count'],
                'evidence_count': prepared['evidence_count'],
                'gaps': list(prepared['run_gaps'])[:_CONTEXT_GAP_LIMIT],
            }
            state['new_analysis'] = False
            save()
            return prepared

        def publish_context_work(prepared):
            try:
                writer = context_writer or JsContextWriter(root=root)
                result = writer.publish_prepared(prepared)
            except TimeoutError:
                context_failure('context_publication_timeout')
                return
            except Exception:
                context_failure('context_publication_uncertain')
                return
            existing = state.get('context_publication') or {}
            publication_status = result.get('status')
            success = publication_status in _CONTEXT_SUCCESS
            state['context_publication'] = {
                **existing,
                'status': 'published' if success else 'pending',
                'run_id': run_id,
                'snapshot_ref': snapshot_ref,
                'document_id': result.get('document_id'),
                'context_id': result.get('context_id'),
                'document_sha256': result.get('document_sha256'),
                'publication_status': publication_status,
                'current_run_id': result.get('current_run_id'),
                'coverage': result.get('coverage'),
                'behavior_count': result.get('behavior_count'),
                'evidence_count': result.get('evidence_count'),
                'gaps': list(result.get('run_gaps') or [])[:_CONTEXT_GAP_LIMIT],
            }
            if not success:
                state['context_publication']['error'] = (
                    'context_same_run_conflict'
                    if publication_status == 'same_run_conflict'
                    else 'context_not_current'
                )
            save()

        def compare_resumed_context_work(existing_document_id):
            try:
                writer = context_writer or JsContextWriter(root=root)
                prepared = writer.prepare(
                    reference=reference,
                    origin=extra.get('application_origin'),
                    analysis_coverage=_context_analysis_coverage(
                        unit.get('coverage') or {},
                        state.get('closure') or {},
                    ),
                    deadline=deadline,
                )
            except TimeoutError:
                context_failure('context_prepare_timeout')
                return False
            except Exception as exc:
                context_failure(_context_error(exc))
                return False
            if prepared['document_id'] != existing_document_id:
                context_failure('context_same_run_conflict')
                return False
            return True

        async def finalize_context():
            existing = state.get('context_publication') or {}
            if snapshot_path.exists():
                try:
                    prepared = _load_context_snapshot(
                        snapshot_path,
                        scope=publication_scope,
                    )
                except Exception as exc:
                    context_failure(_context_error(exc))
                    return _context_stats(state)
                snapshot_sha256 = hashlib.sha256(
                    snapshot_path.read_bytes()
                ).hexdigest()
                if (
                    existing.get('snapshot_sha256')
                    and existing['snapshot_sha256'] != snapshot_sha256
                ) or (
                    existing.get('document_id')
                    and existing['document_id'] != prepared['document_id']
                ):
                    context_failure('context_snapshot_integrity')
                    return _context_stats(state)
                if state.get('new_analysis'):
                    try:
                        unchanged = await bounded(
                            compare_resumed_context_work,
                            existing_document_id=prepared['document_id'],
                        )
                    except TimeoutError:
                        return {
                            **existing,
                            'status': 'pending',
                            'run_id': run_id,
                            'snapshot_ref': snapshot_ref,
                            'error': 'context_prepare_timeout',
                        }
                    if not unchanged:
                        return _context_stats(state)
                    state['new_analysis'] = False
                    save()
                state['context_publication'] = {
                    **existing,
                    'status': (
                        'published'
                        if existing.get('status') == 'published'
                        else 'prepared'
                    ),
                    'run_id': run_id,
                    'snapshot_ref': snapshot_ref,
                    'snapshot_sha256': snapshot_sha256,
                    'document_id': prepared['document_id'],
                    'coverage': prepared['coverage'],
                    'behavior_count': prepared['behavior_count'],
                    'evidence_count': prepared['evidence_count'],
                    'gaps': list(prepared['run_gaps'])[:_CONTEXT_GAP_LIMIT],
                }
                state['context_publication'].pop('error', None)
                save()
            else:
                if existing.get('snapshot_ref'):
                    context_failure('context_snapshot_missing')
                    return _context_stats(state)
                try:
                    prepared = await bounded(prepare_context_work)
                except TimeoutError:
                    return {
                        **existing,
                        'status': 'pending',
                        'run_id': run_id,
                        'snapshot_ref': snapshot_ref,
                        'error': 'context_prepare_timeout',
                    }
                if prepared is None:
                    return _context_stats(state)
            try:
                await bounded(publish_context_work, prepared=prepared)
            except TimeoutError:
                current = state.get('context_publication') or existing
                return {
                    **current,
                    'status': 'pending',
                    'run_id': run_id,
                    'snapshot_ref': snapshot_ref,
                    'error': 'context_publication_timeout',
                }
            return _context_stats(state)

        post_analysis = state.get('stage') in {
            'analysis_closed',
            'prepared',
            'submission_uncertain',
            'confirmed',
        }
        context_pending = (
            post_analysis
            and (state.get('context_publication') or {}).get('status')
            != 'published'
        )
        pending = (
            state.get('stage')
            in {'analysis_closed', 'prepared', 'submission_uncertain'}
            or (state.get('stage') == 'confirmed'
                and not extra.get('js_resume_analysis'))
            or context_pending
        )
        if not pending:
            current=prepare_js_inventory(project_id=scope.project_id,run_id=run_id,context_ref=scope.context_ref,
                scope_domains=scope.scope_domains,allow_http_replay=scope.allow_http_replay,root=root)
            if current['state']=='empty' and unit.get('state')=='empty':
                return []
            if current['state']!='ready' or unit.get('state')!='ready':
                return failed('js_inventory_unavailable')
            reserve=min(15.0, limits.wall_time_s / 10)
            analysis_deadline=deadline-reserve
            prior_context = state.get('context_publication')
            state={'scope':binding,'stage':'analysing','new_analysis':True}
            if prior_context:
                state['context_publication']=prior_context
            save()
            stats['specialist_invocations']=1
            try:
                summary=await asyncio.wait_for((specialist_fn or build_js_specialist(root=root,limits=limits))(
                    project_id=scope.project_id,run_id=run_id,reference=reference,
                    auth_context_label='authenticated' if scope.context_ref else 'anonymous',
                    auth_context_ref=scope.context_ref,deadline=analysis_deadline),
                    timeout=max(.001,analysis_deadline-time.monotonic()))
            except TimeoutError:
                summary={'coverage':'partial','gaps':['time_budget_exhausted']}
            except asyncio.CancelledError:
                raise
            except Exception:
                summary={'coverage':'partial','gaps':['specialist_session_failed']}
            summary_gaps=list(summary.get('gaps') or [])
            blocking='specialist_session_failed' in summary_gaps or 'invalid_or_mismatched_reference' in summary_gaps
            closure={'status':'partial' if summary.get('coverage')!='complete' or summary_gaps else 'complete',
                     'reason':'errors' if blocking else 'budget' if 'time_budget_exhausted' in summary_gaps else 'completed'}
            safe_gaps=sorted({g for g in summary_gaps+(unit.get('coverage',{}).get('gaps') or []) if isinstance(g,str) and re.fullmatch('[a-z][a-z0-9_]{0,79}',g)})
            closure['gaps']=safe_gaps if len(safe_gaps)<=64 else safe_gaps[:63]+['closure_gaps_limited']
            state.update(stage='analysis_closed',closure=closure,blocking=blocking,
                summary_ref='specialist-' + hashlib.sha256(json.dumps(scope.context_ref).encode()).hexdigest()[:16] + '.json')
            save()
        from polymerhus.app.llm.session_address import JsSpecialistSession
        stats['thread_id']=JsSpecialistSession(scope.project_id,run_id,scope.context_ref).thread_id
        stats['summary_ref']=state.get('summary_ref')
        graph_error = None
        if state['stage']=='analysis_closed':
            def freeze():
                proposal=(prepare_fn or prepare_js_graph_proposal)(reference=reference,closure=state['closure'],root=root)
                state.update(stage='prepared',proposal_id=proposal['proposal_id'],coverage=proposal['coverage'])
                save()
                return proposal
            try:
                await bounded(freeze)
            except TimeoutError:
                raise
            except Exception:
                graph_error='js_graph_preparation_failed'
                state['graph']={'status':'pending','error':graph_error}
                save()
        if graph_error is None:
            stats['proposal_id']=state['proposal_id']
            stats['notes_ref']='notes.yaml'
            stats['evidence_ref']='manifest.json'
            proposal_coverage=state.get('coverage') or {}
            input_gaps=stats['coverage'].get('gaps') or []
            stats['coverage']={**proposal_coverage,'status':'partial' if stats['coverage'].get('status')=='partial' or proposal_coverage.get('status')=='partial' else 'complete', 'gaps':sorted(set(input_gaps+(proposal_coverage.get('gaps') or [])))}
            def submit():
                receipt=(submit_fn or submit_js_graph_proposal)(reference=reference,proposal_id=state['proposal_id'],root=root,**policy)
                state['stage']='confirmed' if receipt['status']=='confirmed' else 'submission_uncertain'
                save()
                return receipt
            try:
                receipt=await bounded(submit)
            except TimeoutError:
                raise
            except Exception:
                graph_error='js_graph_submission_failed'
                state['graph']={'status':'pending','error':graph_error}
                save()
                receipt={'status':'uncertain','assets_merged':0,'merged_assets':[]}
        else:
            receipt={'status':'uncertain','assets_merged':0,'merged_assets':[]}
        stats['context_publication']=await finalize_context()
        if graph_error is not None:
            return failed(graph_error)
        if receipt['status']!='confirmed':
            return failed('js_finalization_uncertain')
        if stats['context_publication'].get('status') != 'published':
            stats['capture_release']={
                'status':'pending',
                'gap':'context_publication_pending',
            }
        elif capture_store is None:
            from polymerhus.recon.js_acquisition.capture import SteelCaptureStore
            capture_store=SteelCaptureStore(root=root)
        if stats['context_publication'].get('status') == 'published':
            try:
                stats['capture_release']=await bounded(capture_store.release_consumed,project_id=scope.project_id,run_id=run_id,context_ref=scope.context_ref)
            except Exception:
                stats['capture_release']={'status':'pending','gap':'capture_release_incomplete'}
        assets=[AssetDelta.model_validate(a) for a in receipt['merged_assets']]
        return [PodExport(input_asset=public_input,verdict='failed' if state.get('blocking') else 'success',
            error='specialist_session_failed' if state.get('blocking') else None,
            assets_merged=receipt['assets_merged'],observations_merged=0,assets=assets,stats=stats)]
    except TimeoutError:
        return failed('js_finalization_pending_timeout')
    except asyncio.CancelledError:
        raise
    except Exception:
        return failed('js_analysis_failed')
    finally:
        with ownership_guard:
            ownership['left']=True
            if not ownership['active']:
                lock.close()
