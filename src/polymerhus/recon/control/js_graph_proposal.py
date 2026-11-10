"""Prepare/freeze one scoped JS proposal; handoff uses the existing curator.

The proposal consumes saved scanner candidates and verified structural ESM
imports as separate evidence. Scans, reads and notes never invoke submission.
"""
from __future__ import annotations

import base64
import fcntl
import json
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from polymerhus.app.atomic_write import write_text_atomic
from polymerhus.app.data_root import project_dir
from polymerhus.recon.domain.js_graph_proposal import (
    PROPOSAL_SCHEMA_VERSION, SourceContext, build_js_asset_deltas,
    canonical_bytes, content_id, safe_network_url,
)
from polymerhus.recon.domain.types import AssetDelta
from polymerhus.recon.js_acquisition.code_access import CodeAccessService
from polymerhus.recon.js_acquisition.scan_store import ScanStore, _lock_for
from polymerhus.recon.js_acquisition.structure_store import (
    StructureStore,
    StructureStoreError,
)
from polymerhus.recon.js_intake.reader import JsIntakeReader, resolve_js_intake_reference
from polymerhus.recon.js_specialist.notes import RunNotes

_MAX_PROPOSAL_BYTES = 8 * 1024 * 1024
_MAX_NOTES_BYTES = 1024 * 1024


class JsGraphProposalError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class AnalysisClosure(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: Literal['complete', 'partial']
    reason: Literal['completed', 'budget', 'errors', 'cancelled']
    gaps: list[str] = Field(default_factory=list, max_length=64)


class GraphAnnotation(BaseModel):
    """Optional structured decisions; no URL/hash/source overrides from the model."""
    model_config = ConfigDict(extra='forbid')
    candidate_ref: str = Field(pattern=r'^occ_[0-9a-f]{64}$')
    action: Literal['exclude', 'include', 'link_behavior']
    reason: str = Field(pattern=r'^[a-z][a-z0-9_]{0,79}$')
    evidence_refs: list[str] = Field(min_length=1, max_length=8)
    behavior_id: str = Field(default='', max_length=100)
    behavior_revision: int = Field(default=0, ge=0)
    fact_id: str = Field(default='', max_length=64)


def _scope_dict(scope) -> dict:
    return {k: getattr(scope, k) for k in ('project_id', 'run_id', 'context_ref')}


class JsGraphProposalStore:
    """Private immutable snapshots plus separate recoverable submission receipts."""
    def __init__(self, scope, *, root=None):
        self.scope = scope
        self.path = (project_dir(scope.project_id, 'recon/js_analysis', root=root)
                     / scope.run_id / 'graph-proposals' / content_id(scope.context_ref))

    @contextmanager
    def locked(self):
        self.path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.chmod(0o700)
        self.path.parent.chmod(0o700)
        lock_path = self.path / '.proposal.lock'
        with _lock_for(lock_path):
            with lock_path.open('a+') as handle:
                lock_path.chmod(0o600)
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _file(self, proposal_id: str, suffix='.json') -> Path:
        if not re.fullmatch('[0-9a-f]{64}', proposal_id):
            raise JsGraphProposalError('invalid_proposal_id')
        return self.path / (proposal_id + suffix)

    @staticmethod
    def _read(path: Path, *, max_bytes=_MAX_PROPOSAL_BYTES) -> dict:
        try:
            if path.stat().st_size > max_bytes:
                raise JsGraphProposalError('proposal_size_limit')
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                raise ValueError
            return data
        except (OSError, ValueError) as exc:
            raise JsGraphProposalError(getattr(exc, 'reason', 'proposal_unavailable')) from None

    @staticmethod
    def _write(path: Path, body: dict):
        encoded = canonical_bytes(body)
        if len(encoded) > _MAX_PROPOSAL_BYTES:
            raise JsGraphProposalError('proposal_size_limit')
        write_text_atomic(path, encoded.decode() + '\n')
        path.chmod(0o600)

    def freeze(self, payload: dict) -> dict:
        proposal_id = content_id(payload)
        document = {'proposal_id': proposal_id, **payload}
        with self.locked():
            path = self._file(proposal_id)
            if path.exists():
                return self.load(proposal_id)
            self._write(path, document)
        return document

    def load(self, proposal_id: str) -> dict:
        data = self._read(self._file(proposal_id))
        payload = {k: v for k, v in data.items() if k != 'proposal_id'}
        if data.get('proposal_id') != proposal_id or content_id(payload) != proposal_id:
            raise JsGraphProposalError('proposal_integrity')
        if payload.get('scope') != _scope_dict(self.scope):
            raise JsGraphProposalError('proposal_scope_mismatch')
        if payload.get('schema_version') != PROPOSAL_SCHEMA_VERSION:
            raise JsGraphProposalError('proposal_schema_mismatch')
        return data


def _notes(scope, *, root=None, notes_fn=None):
    if notes_fn:
        return notes_fn(scope)
    notes = RunNotes(scope, root=root)
    if notes.path.exists() and notes.path.stat().st_size > _MAX_NOTES_BYTES:
        raise JsGraphProposalError('notes_size_limit')
    return notes.typed_records(event_types={'js_graph_annotation', 'behavior_save'})


def _collect(*, reference, root=None, scan_store=None, structure_store=None,
             reader=None, source_context_fn=None,
             max_scans=64, max_candidates=4096, max_bytes=8 * 1024 * 1024):
    scope = resolve_js_intake_reference(reference)
    scans = scan_store or ScanStore(root=root)
    structures = structure_store or StructureStore(root=root)
    reader = reader or JsIntakeReader(root=root)
    # Bound the existing private inventory reader before it materializes files.
    # This uses its established authorization seam, with no second inventory.
    if isinstance(reader, JsIntakeReader):
        inventory = project_dir(scope.project_id, 'recon/js-intake', root=root) / scope.run_id
        inventory_bytes = 0
        for index, path in enumerate(inventory.glob('*.jsonl')):
            inventory_bytes += path.stat().st_size
            if index >= 256 or inventory_bytes > max_bytes:
                return scope, [], {}, [], ['inventory_limit']
    snapshot = scans.snapshot(**_scope_dict(scope), max_scans=max_scans,
                              max_candidates=max_candidates, max_bytes=max_bytes)
    occurrences, contexts, structural_imports, inputs = [], {}, [], []
    gaps = list(snapshot['gaps'])
    seen_structural = set()
    for item in snapshot['occurrences']:
        try:
            lead, current_scope = reader.get_private(reference=reference, lead_id=item['lead_id'])
        except LookupError:
            gaps.append('scan_lead_unavailable')
            continue
        if _scope_dict(current_scope) != _scope_dict(scope):
            raise JsGraphProposalError('source_scope_mismatch')
        binding = {**_scope_dict(scope), **{k: item[k] for k in ('lead_id', 'scan_key', 'source_sha256')}}
        context_id = 'source_' + content_id(binding)
        final_url = item.get('final_url') or ''
        ctx = SourceContext(**binding, discovery_producer=lead.get('source_tool') or 'unknown',
                            source_url=final_url or lead.get('exact_url') or '',
                            module_base_url=final_url or None,
                            module_base_ref=context_id if final_url else None)
        if source_context_fn:
            ctx = SourceContext.model_validate(source_context_fn(scope, item, lead))
            if any(getattr(ctx, k) != v for k, v in binding.items()):
                raise JsGraphProposalError('source_scope_mismatch')
        contexts[context_id] = ctx
        inputs.append({'source_context_id': context_id, 'scan_key': item['scan_key'],
                       'candidate_schema_version': item['candidate_schema_version'],
                       'submissions': item['submissions'], 'status': item['status'],
                       'candidate_ids': [c['candidate_id'] for c in item['candidates']]})
        occurrences.extend({'candidate': c, 'source_context_id': context_id} for c in item['candidates'])
        remaining = max_candidates - len(occurrences) - len(structural_imports)
        if remaining <= 0:
            gaps.append('structure_import_limit')
            continue
        try:
            structure = structures.current_imports(
                project_id=scope.project_id,
                run_id=scope.run_id,
                context_ref=scope.context_ref,
                lead_id=item['lead_id'],
                source_sha256=item['source_sha256'],
                max_items=remaining,
                max_bytes=max_bytes,
            )
        except (OSError, ValueError, StructureStoreError) as exc:
            gaps.append(getattr(exc, 'reason', 'structure_unavailable'))
            continue
        gaps.extend(structure.get('gaps') or [])
        if (
            structure.get('source_sha256') != item['source_sha256']
            or not final_url
            or safe_network_url(structure.get('parent_final_url') or '')
            != safe_network_url(final_url)
        ):
            gaps.append('structure_module_base_mismatch')
            continue
        for imported in structure.get('imports') or []:
            item_id = str(imported.get('item_id') or '')
            identity = (context_id, structure['index_id'], item_id)
            if not item_id or identity in seen_structural:
                continue
            seen_structural.add(identity)
            structural_imports.append({
                'source_context_id': context_id,
                'evidence': {
                    'project_id': scope.project_id,
                    'run_id': scope.run_id,
                    'context_ref': scope.context_ref,
                    'lead_id': item['lead_id'],
                    'source_sha256': item['source_sha256'],
                    'source_size': structure['source_size'],
                    'index_id': structure['index_id'],
                    'index_integrity': structure['index_integrity'],
                    'item_id': item_id,
                    'start_byte': imported['start_byte'],
                    'end_byte': imported['end_byte'],
                    'specifier': imported['specifier'],
                    'subtype': imported['subtype'],
                    'import_kind': imported['import_kind'],
                    'module_base_url': structure.get('parent_final_url'),
                    'module_base_ref': (
                        f"structure:{structure['index_id']}:{item_id}"
                    ),
                },
            })
    return (
        scope,
        occurrences,
        contexts,
        structural_imports,
        inputs,
        gaps,
    )


def _latest_behaviors(records):
    latest = {}
    for record in records:
        if record.get('event_type') != 'behavior_save':
            continue
        key = record.get('behavior_id')
        if key and int(record.get('revision') or 0) > int(latest.get(key, {}).get('revision') or 0):
            latest[key] = record
    return latest


def _validate_annotation(annotation, *, reference, outcome, context, behaviors, access):
    if not outcome or not context:
        raise JsGraphProposalError('graph_candidate_missing')
    for read_id in annotation.evidence_refs:
        receipt = access.read_receipt(reference=reference, read_id=read_id)
        expected = {**{k: getattr(context, k) for k in ('project_id', 'run_id', 'context_ref', 'lead_id')},
                    'content_sha256': context.source_sha256, 'delivery_status': 'delivered'}
        if any(receipt.get(k) != value for k, value in expected.items()):
            raise JsGraphProposalError('graph_evidence_mismatch')
    if annotation.action == 'link_behavior':
        behavior = behaviors.get(annotation.behavior_id) or {}
        if behavior.get('revision') != annotation.behavior_revision:
            raise JsGraphProposalError('behavior_revision_mismatch')
        if not outcome.fact_id or annotation.fact_id != outcome.fact_id or outcome.status != 'proposed':
            raise JsGraphProposalError('graph_fact_mismatch')
        behavior_reads = {rid for step in behavior.get('steps') or [] for rid in step.get('read_ids') or []}
        if not set(annotation.evidence_refs) <= behavior_reads or behavior.get('lead_id') != context.lead_id:
            raise JsGraphProposalError('behavior_evidence_mismatch')


def prepare_js_graph_proposal(*, reference: str, closure: dict, root=None, scan_store=None,
                              structure_store=None, reader=None, notes_fn=None,
                              source_context_fn=None, access=None,
                              max_scans=64, max_candidates=4096, max_bytes=8 * 1024 * 1024) -> dict:
    closing = AnalysisClosure.model_validate(closure)
    if any(not re.fullmatch('[a-z][a-z0-9_]{0,79}', gap) for gap in closing.gaps):
        raise JsGraphProposalError('invalid_closure_gap')
    scope, occurrences, contexts, structural_imports, inputs, gaps = _collect(
        reference=reference, root=root, scan_store=scan_store,
        structure_store=structure_store, reader=reader,
        source_context_fn=source_context_fn, max_scans=max_scans,
        max_candidates=max_candidates, max_bytes=max_bytes)
    try:
        records = _notes(scope, root=root, notes_fn=notes_fn)
    except (OSError, ValueError, KeyError):
        records = []
        gaps.append('notes_unavailable')
    behaviors = _latest_behaviors(records)
    baseline = build_js_asset_deltas(
        occurrences,
        source_contexts=contexts,
        structural_imports=structural_imports,
    )
    by_ref = {o.candidate_ref: o for o in baseline.outcomes}
    access = access or CodeAccessService(root=root)
    decisions_by_ref = {}
    links = []
    annotations = []
    for record in records:
        if record.get('event_type') != 'js_graph_annotation':
            continue
        try:
            annotation = GraphAnnotation.model_validate(record['annotation'])
            outcome = by_ref.get(annotation.candidate_ref)
            context = contexts.get(outcome.source_context_id) if outcome else None
            _validate_annotation(annotation, reference=reference, outcome=outcome,
                                 context=context, behaviors=behaviors, access=access)
        except (ValueError, KeyError) as exc:
            gaps.append(getattr(exc, 'reason', 'unsupported_decision'))
            continue
        annotations.append({'record_id': record['record_id'], 'annotation_id': record['annotation_id'],
                            'annotation': annotation.model_dump()})
        if annotation.action in {'exclude', 'include'}:
            decisions_by_ref[annotation.candidate_ref] = {**annotation.model_dump(), 'record_id': record['record_id']}
        else:
            links.append({**annotation.model_dump(), 'record_id': record['record_id']})
    projected = build_js_asset_deltas(
        occurrences,
        source_contexts=contexts,
        structural_imports=structural_imports,
        decisions=list(decisions_by_ref.values()),
    )
    final_by_ref = {o.candidate_ref: o for o in projected.outcomes}
    consistent_links = []
    for link in links:
        if final_by_ref[link['candidate_ref']].status != 'proposed':
            gaps.append('behavior_candidate_excluded')
        else:
            consistent_links.append(link)
    if behaviors and not consistent_links:
        gaps.append('behavior_candidate_links_unavailable')
    gaps.extend(closing.gaps)
    gaps.extend(projected.gaps)
    gaps.extend(o.reason for o in projected.outcomes if o.status == 'unresolved' and o.reason)
    if closing.status == 'partial' or closing.reason != 'completed':
        gaps.append('analysis_' + closing.reason)
    sources = {}
    for key, ctx in contexts.items():
        value = ctx.model_dump()
        for field in ('source_url', 'execution_base_url', 'module_base_url'):
            value[field] = safe_network_url(value.get(field) or '')
        sources[key] = value
    payload = {
        'schema_version': PROPOSAL_SCHEMA_VERSION, 'scope': _scope_dict(scope),
        'closure': closing.model_dump(), 'inputs': inputs, 'sources': sources,
        'structure_inputs': sorted(
            (
                {
                    **occurrence['evidence'],
                    'source_context_id': occurrence['source_context_id'],
                }
                for occurrence in structural_imports
            ),
            key=lambda value: (
                value['source_context_id'],
                value['index_id'],
                value['item_id'],
            ),
        ),
        'assets': [a.model_dump() for a in projected.assets],
        'outcomes': [o.model_dump() for o in projected.outcomes],
        'annotations': annotations, 'behavior_links': consistent_links,
        'behavior_records': [{'behavior_id': b['behavior_id'], 'revision': b['revision'],
                              'record_sha256': b['record_sha256']} for _, b in sorted(behaviors.items())],
        'coverage': {'status': 'partial' if gaps else 'complete', 'exhaustive': False,
                     'gaps': sorted(set(gaps)), 'scan_occurrences': len(inputs)},
        'coherence': {'explicit_links_checked': len(consistent_links), 'semantic_text_verified': False},
    }
    # Recheck authorization at the freeze boundary after potentially slow reads.
    if _scope_dict(resolve_js_intake_reference(reference)) != _scope_dict(scope):
        raise JsGraphProposalError('proposal_scope_mismatch')
    return JsGraphProposalStore(scope, root=root).freeze(payload)


def load_js_graph_proposal(*, reference: str, proposal_id: str, root=None) -> dict:
    scope = resolve_js_intake_reference(reference)
    return JsGraphProposalStore(scope, root=root).load(proposal_id)


def record_js_graph_annotation(*, reference: str, record: dict, root=None, access=None) -> dict:
    if len(canonical_bytes(record)) > 2048:
        raise JsGraphProposalError('graph_annotation_limit')
    annotation = GraphAnnotation.model_validate(record)
    scope, candidates, contexts, structural_imports, _, _ = _collect(
        reference=reference,
        root=root,
    )
    baseline = build_js_asset_deltas(
        candidates,
        source_contexts=contexts,
        structural_imports=structural_imports,
    )
    outcome = next((o for o in baseline.outcomes if o.candidate_ref == annotation.candidate_ref), None)
    notes = RunNotes(scope, root=root)
    records = _notes(scope, root=root)
    _validate_annotation(annotation, reference=reference, outcome=outcome,
                         context=contexts.get(outcome.source_context_id) if outcome else None,
                         behaviors=_latest_behaviors(records), access=access or CodeAccessService(root=root))
    annotation_id = content_id({'scope': _scope_dict(scope), 'annotation': annotation.model_dump()})
    def build(history):
        relevant = []
        for saved in history:
            if saved.get('context_ref') != scope.context_ref or saved.get('event_type') != 'js_graph_annotation':
                continue
            previous = saved.get('annotation') or {}
            if previous.get('candidate_ref') != annotation.candidate_ref:
                continue
            if annotation.action in {'include', 'exclude'}:
                same_slot = previous.get('action') in {'include', 'exclude'}
            else:
                same_slot = (previous.get('action') == 'link_behavior'
                             and previous.get('behavior_id') == annotation.behavior_id
                             and previous.get('behavior_revision') == annotation.behavior_revision)
            if same_slot:
                relevant.append(saved)
        if relevant and relevant[-1].get('annotation_id') == annotation_id:
            return {'existing_record': relevant[-1], 'idempotent': True}
        return {'record': {'event_type': 'js_graph_annotation', 'schema_version': 1,
                           'annotation_id': annotation_id, 'annotation': annotation.model_dump()}}
    result = notes.append_typed_transaction(build)
    if result.get('error'):
        raise JsGraphProposalError(result['error'])
    saved = result.get('record') or result['existing_record']
    return {'status': 'recorded', 'record_id': saved['record_id'], 'annotation_id': annotation_id,
            'idempotent': bool(result.get('idempotent'))}


def submit_js_graph_proposal(*, reference: str, proposal_id: str, curate_fn=None,
                             scope_domain=None, seed_domain=None, seed_root_type='Domain', root=None) -> dict:
    """Submit the authenticated frozen version, serializing local attempts.

    A persisted confirmation is reusable. A crash/lost response after writes is
    uncertain; its retry replays exactly the snapshot through existing MERGE
    identities. This is not an exactly-once transaction across FS and Neo4j.
    Explicit scope policy is supplied by trusted orchestration, never by Exec.
    """
    scope = resolve_js_intake_reference(reference)
    store = JsGraphProposalStore(scope, root=root)
    policy = {'scope_domain': scope_domain, 'seed_domain': seed_domain, 'seed_root_type': seed_root_type}
    with store.locked():
        resolve_js_intake_reference(reference)
        proposal = store.load(proposal_id)
        receipt_path = store._file(proposal_id, '.receipt.json')
        previous = {}
        if receipt_path.exists():
            envelope = store._read(receipt_path)
            previous = envelope.get('receipt') or {}
            if envelope.get('receipt_sha256') != content_id(previous):
                raise JsGraphProposalError('receipt_integrity')
            if previous.get('scope') != _scope_dict(scope) or previous.get('proposal_id') != proposal_id:
                raise JsGraphProposalError('receipt_scope_mismatch')
            if previous.get('policy') != policy:
                raise JsGraphProposalError('submission_policy_mismatch')
            if previous.get('status') == 'confirmed':
                return {**previous, 'reused_confirmation': True}
        receipt = {
            'schema_version': 1, 'proposal_id': proposal_id, 'scope': _scope_dict(scope),
            'policy': policy, 'status': 'in_progress', 'attempts': previous.get('attempts', 0) + 1,
            'assets_merged': 0, 'observations_merged': 0, 'merged_assets': [], 'merged_observations': [],
            'unconfirmed_proposal_assets': len(proposal['assets']),
            'omission_reasons_available': False, 'reused_confirmation': False,
            'counts_are_new_nodes': False,
        }
        def persist():
            store._write(receipt_path, {'receipt': receipt, 'receipt_sha256': content_id(receipt)})
        # Persist intent before invoking the sole writer; in_progress on a
        # subsequent attempt has the same uncertain semantics as a lost reply.
        persist()
        if curate_fn is None:
            from polymerhus.recon.domain.curator import curate
            curate_fn = curate
        try:
            assets = [AssetDelta.model_validate(a) for a in proposal['assets']]
            returned = curate_fn(assets, [], scope.project_id, **policy)
            if not isinstance(returned, tuple) or len(returned) != 4:
                raise ValueError('invalid_curator_return')
            asset_count, obs_count, merged_assets, merged_observations = returned
            if (type(asset_count) is not int or type(obs_count) is not int
                or not isinstance(merged_assets, list) or not isinstance(merged_observations, list)
                or asset_count != len(merged_assets) or obs_count != len(merged_observations)):
                raise ValueError('invalid_curator_return')
            confirmed = [AssetDelta.model_validate(a).model_dump() for a in merged_assets]
            confirmed_obs = [o.model_dump() for o in merged_observations]
            receipt.update(status='confirmed', assets_merged=asset_count, observations_merged=obs_count,
                           merged_assets=confirmed, merged_observations=confirmed_obs,
                           unconfirmed_proposal_assets=max(0, len(proposal['assets']) - asset_count))
        except Exception:
            # Driver exceptions can carry credentials or query payloads. Do not
            # persist their text or invent per-item rejection classifications.
            receipt.update(status='uncertain', error='curator_call_outcome_uncertain')
        persist()
        return receipt



def read_js_graph_candidates(*, reference: str, lead_id: str, cursor=None, limit=5, root=None) -> dict:
    """Bounded optional inspection; never freezes a proposal or invokes curation."""
    if type(limit) is not int or not 1 <= limit <= 10:
        raise JsGraphProposalError('invalid_graph_limit')
    reader = JsIntakeReader(root=root)
    reader.get_private(reference=reference, lead_id=lead_id)
    scope, candidates, contexts, structural_imports, _, gaps = _collect(
        reference=reference,
        root=root,
        reader=reader,
    )
    projection = build_js_asset_deltas(
        candidates,
        source_contexts=contexts,
        structural_imports=structural_imports,
    )
    outcomes = [o.model_dump() for o in projection.outcomes if contexts[o.source_context_id].lead_id == lead_id]
    view = content_id({'scope': _scope_dict(scope), 'lead_id': lead_id, 'outcomes': outcomes})
    offset = 0
    if cursor:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
            offset = decoded['offset']
            if decoded['view'] != view or type(offset) is not int or offset < 0:
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise JsGraphProposalError('invalid_graph_cursor') from None
    count = min(limit, max(0, len(outcomes) - offset))
    while True:
        next_offset = offset + count
        next_cursor = base64.urlsafe_b64encode(canonical_bytes({'view': view, 'offset': next_offset})).decode().rstrip('=') if next_offset < len(outcomes) else None
        result = {'candidates': outcomes[offset:next_offset], 'next_cursor': next_cursor,
                  'coverage_gaps': sorted(set(gaps + projection.gaps)), 'semantic_text_verified': False}
        if len(canonical_bytes(result)) <= 15000:
            return result
        count -= 1
        if count <= 0:
            raise JsGraphProposalError('graph_response_limit')
