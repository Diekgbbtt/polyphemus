"""Final proposal freezing, real saved inputs and unchanged curator contract."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.recon.test_js_graph_scan_snapshot import prepared
from tests.recon.js_acquisition.test_scan_store import (
    _acquired_lead,
    _scan_result,
)
from polymerhus.app.data_root import ensure_project
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_acquisition.scan_store import ScanStore
from polymerhus.recon.js_acquisition.structure import parse_structure_bytes
from polymerhus.recon.js_acquisition.structure_store import StructureStore
from polymerhus.recon.js_intake import issue_js_intake_reference
from polymerhus.recon.js_specialist.notes import RunNotes
from polymerhus.recon.js_intake.reader import resolve_js_intake_reference


def prepare(root, reference, **kw):
    from polymerhus.recon.control.js_graph_proposal import prepare_js_graph_proposal
    return prepare_js_graph_proposal(reference=reference, closure={'status': 'complete', 'reason': 'completed'}, root=root, **kw)


def prepared_import(tmp_path, *, with_structure=True):
    root = tmp_path / 'data'
    ensure_project('proj-1', root=root)
    source = tmp_path / 'source.js'
    source.write_bytes(b'import { value } from "./part.js";\n')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    final_url = 'https://cdn.example.test/assets/app.js'
    lead, reference = _acquired_lead(
        root,
        source=source,
        digest=digest,
        url=final_url,
    )
    AcquisitionManifest(
        project_id='proj-1',
        run_id='run-1',
        root=root,
        max_run_bytes=1024**2,
    ).update(
        lambda value: value['leads'][lead].update(final_url=final_url)
    )
    result = _scan_result(
        source,
        digest,
        urls=[{'url': './part.js', 'kind': 'stringLiteral'}],
    )
    scans = ScanStore(root=root)
    for mode in ('urls', 'secrets'):
        scans.submit_mode(
            project_id='proj-1',
            run_id='run-1',
            lead_id=lead,
            context_ref='account-1',
            result=result,
            mode=mode,
        )
    structure = None
    if with_structure:
        structure = StructureStore(root=root)
        structure.store_index(
            project_id='proj-1',
            run_id='run-1',
            context_ref='account-1',
            lead_id=lead,
            source_bytes=source.read_bytes(),
            parsed=parse_structure_bytes(source.read_bytes()),
            parent_final_url=final_url,
        )
    return root, source, digest, lead, reference, structure


def test_snapshot_is_stable_private_and_new_evidence_gets_new_version(tmp_path):
    root, source, digest, lead, ref, _, scans = prepared(tmp_path)
    first = prepare(root, ref)
    assert {a['type'] for a in first['assets']} == {'BaseURL', 'Endpoint', 'Secret'}
    assert 'structure_index_missing' in first['coverage']['gaps']
    assert first['coherence']['semantic_text_verified'] is False
    assert first['proposal_id'] == prepare(root, ref)['proposal_id']
    from polymerhus.recon.control.js_graph_proposal import load_js_graph_proposal
    assert load_js_graph_proposal(reference=ref, proposal_id=first['proposal_id'], root=root) == first
    path = next((root / 'proj-1/recon/js_analysis/run-1/graph-proposals').rglob(first['proposal_id'] + '.json'))
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert 'fixture-value' not in path.read_text()
    changed = _scan_result(source, digest, urls=[{'url': 'https://api.example.test/new'}])
    scans.submit_mode(project_id='proj-1', run_id='run-1', lead_id=lead, context_ref='account-1', result=changed, mode='urls')
    second = prepare(root, ref)
    assert second['proposal_id'] != first['proposal_id']
    assert load_js_graph_proposal(reference=ref, proposal_id=first['proposal_id'], root=root) == first


@pytest.mark.parametrize('project,run,auth', [('proj-2','run-1','account-1'),('proj-1','run-2','account-1'),('proj-1','run-1','account-2')])
def test_reference_cannot_load_foreign_snapshot(tmp_path, project, run, auth):
    root, _, _, _, ref, _, _ = prepared(tmp_path)
    first = prepare(root, ref)
    other = issue_js_intake_reference(project, run, context_ref=auth)
    from polymerhus.recon.control.js_graph_proposal import load_js_graph_proposal
    with pytest.raises(ValueError):
        load_js_graph_proposal(reference=other, proposal_id=first['proposal_id'], root=root)


def test_empty_budget_closure_is_explicit_partial_not_exhaustive(tmp_path):
    from polymerhus.recon.control.js_graph_proposal import prepare_js_graph_proposal
    ref = issue_js_intake_reference('proj', 'run', context_ref='auth')
    result = prepare_js_graph_proposal(reference=ref, root=tmp_path, closure={'status': 'partial', 'reason': 'budget'})
    assert not result['assets']
    assert result['coverage']['status'] == 'partial'
    assert result['coverage']['exhaustive'] is False
    assert 'no_eligible_scans' in result['coverage']['gaps']


def test_partial_saved_scan_keeps_discoveries_and_named_coverage(tmp_path):
    root, _, _, _, ref, result, _ = prepared(tmp_path)
    manifest = AcquisitionManifest(project_id='proj-1', run_id='run-1', root=root, max_run_bytes=1024**2)
    manifest.update(lambda m: m['scans'][result['scan_key']].update(status='partial'))
    proposal = prepare(root, ref)
    assert any(a['type'] == 'Endpoint' for a in proposal['assets'])
    assert proposal['coverage']['status'] == 'partial'
    assert 'partial_scan' in proposal['coverage']['gaps']


def test_corrupt_snapshot_and_expired_reference_are_refused(tmp_path):
    from polymerhus.recon.control.js_graph_proposal import load_js_graph_proposal
    root, _, _, _, ref, _, _ = prepared(tmp_path)
    proposal = prepare(root, ref)
    path = next((root / 'proj-1/recon/js_analysis/run-1/graph-proposals').rglob(proposal['proposal_id'] + '.json'))
    data = json.loads(path.read_text()); data['assets'] = []; path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='proposal_integrity'):
        load_js_graph_proposal(reference=ref, proposal_id=proposal['proposal_id'], root=root)
    from polymerhus.recon.js_intake.reader import _REFERENCES
    _REFERENCES.pop(ref)
    with pytest.raises(ValueError):
        load_js_graph_proposal(reference=ref, proposal_id=proposal['proposal_id'], root=root)


def test_supported_exclusion_keeps_append_only_provenance(tmp_path):
    from polymerhus.recon.control.js_graph_proposal import record_js_graph_annotation
    root, _, digest, lead, ref, _, _ = prepared(tmp_path)
    first = prepare(root, ref)
    occurrence = next(o for o in first['outcomes'] if o['facts'].get('url'))
    manifest = AcquisitionManifest(project_id='proj-1', run_id='run-1', root=root, max_run_bytes=1024**2)
    manifest.update(lambda m: m.setdefault('code_access', {}).setdefault('reads', {}).update({
        'read-good': {'context_ref':'account-1', 'project_id':'proj-1', 'run_id':'run-1',
                      'lead_id':lead, 'content_sha256':digest, 'delivery_status':'delivered'}}))
    record = {'candidate_ref': occurrence['candidate_ref'], 'action':'exclude',
              'reason':'documented_false_positive', 'evidence_refs':['read-good']}
    saved = record_js_graph_annotation(reference=ref, record=record, root=root)
    assert saved['status'] == 'recorded'
    assert record_js_graph_annotation(reference=ref, record=record, root=root)['idempotent'] is True
    second = prepare(root, ref)
    assert second['proposal_id'] != first['proposal_id']
    assert next(o for o in second['outcomes'] if o['candidate_ref'] == occurrence['candidate_ref'])['status'] == 'excluded'
    assert all(a['type'] != 'Endpoint' for a in second['assets'])
    assert len(RunNotes(resolve_js_intake_reference(ref), root=root).typed_records(event_types={'js_graph_annotation'})) == 1


def test_unsupported_or_foreign_evidence_cannot_exclude_a_candidate(tmp_path):
    from polymerhus.recon.control.js_graph_proposal import record_js_graph_annotation
    root, _, _, _, ref, _, _ = prepared(tmp_path)
    occurrence = prepare(root, ref)['outcomes'][0]
    with pytest.raises(ValueError, match='graph_evidence'):
        record_js_graph_annotation(reference=ref, record={'candidate_ref':occurrence['candidate_ref'],
             'action':'exclude', 'reason':'false_positive', 'evidence_refs':['foreign-read']}, root=root)
    assert prepare(root, ref)['outcomes'][0]['status'] == 'proposed'


def test_explicit_behavior_links_check_canonical_facts_and_latest_revision(tmp_path):
    from polymerhus.recon.control.js_graph_proposal import record_js_graph_annotation
    root, _, digest, lead, ref, _, _ = prepared(tmp_path)
    first = prepare(root, ref)
    occurrence = next(o for o in first['outcomes'] if o['facts'].get('url'))
    notes = RunNotes(resolve_js_intake_reference(ref), root=root)
    notes.append_typed({'event_type':'behavior_save','behavior_id':'behavior-1','revision':1,
                        'lead_id':lead,'record_sha256':'c'*64,'steps':[{'read_ids':['read-good']}],
                        'assumptions':[]}, allow_sanitized_text=True)
    manifest = AcquisitionManifest(project_id='proj-1', run_id='run-1', root=root, max_run_bytes=1024**2)
    manifest.update(lambda m: m.setdefault('code_access', {}).setdefault('reads', {}).update({
        'read-good': {'project_id':'proj-1','run_id':'run-1','context_ref':'account-1','lead_id':lead,
                      'content_sha256':digest, 'delivery_status':'delivered'}}))
    record = {'candidate_ref':occurrence['candidate_ref'], 'action':'link_behavior',
              'reason':'request_in_flow', 'evidence_refs':['read-good'],
              'behavior_id':'behavior-1','behavior_revision':1,'fact_id':occurrence['fact_id']}
    record_js_graph_annotation(reference=ref, root=root, record=record)
    second = prepare(root, ref)
    assert len(second['behavior_links']) == 1
    assert second['coherence']['semantic_text_verified'] is False
    bad = {**record, 'fact_id':'0'*64}
    with pytest.raises(ValueError, match='graph_fact_mismatch'):
        record_js_graph_annotation(reference=ref, root=root, record=bad)
    notes.append_typed({'event_type':'behavior_save','behavior_id':'behavior-1','revision':2,
                        'lead_id':lead,'record_sha256':'d'*64,'steps':[]}, allow_sanitized_text=True)
    third = prepare(root, ref)
    assert third['behavior_links'] == []
    assert 'behavior_revision_mismatch' in third['coverage']['gaps']


def test_preparation_limit_reports_partial_instead_of_truncating_silently(tmp_path):
    root, _, _, _, ref, _, _ = prepared(tmp_path)
    proposal = prepare(root, ref, max_candidates=1)
    assert proposal['coverage']['status'] == 'partial'
    assert 'candidate_limit' in proposal['coverage']['gaps']


def test_curator_receipt_contains_only_actual_merged_assets_and_reuses_confirmation(tmp_path):
    from polymerhus.recon.control.js_graph_proposal import submit_js_graph_proposal
    root, _, _, _, ref, _, _ = prepared(tmp_path)
    proposal = prepare(root, ref)
    calls = []
    def curate(assets, observations, project_id, **scope):
        assert project_id == 'proj-1'
        assert observations == []
        assert scope == {'scope_domain':'example.test', 'seed_domain':'example.test', 'seed_root_type':'Domain'}
        calls.append([a.model_dump() for a in assets])
        return (1, 0, [assets[0]], [])
    kw = dict(reference=ref, proposal_id=proposal['proposal_id'], root=root,
              curate_fn=curate, scope_domain='example.test', seed_domain='example.test')
    result = submit_js_graph_proposal(**kw)
    assert result['status'] == 'confirmed'
    assert result['assets_merged'] == 1
    assert result['merged_assets'] == [proposal['assets'][0]]
    assert result['unconfirmed_proposal_assets'] == len(proposal['assets']) - 1
    assert result['omission_reasons_available'] is False
    assert submit_js_graph_proposal(**kw)['merged_assets'] == result['merged_assets']
    assert len(calls) == 1


def test_lost_response_retry_uses_frozen_assets_even_after_scan_changes(tmp_path):
    from polymerhus.recon.control.js_graph_proposal import submit_js_graph_proposal
    root, source, digest, lead, ref, _, scans = prepared(tmp_path)
    proposal = prepare(root, ref)
    calls = []
    def curate(assets, observations, project_id, **scope):
        calls.append([a.model_dump() for a in assets])
        if len(calls) == 1:
            raise TimeoutError('sensitive driver exception must not leak')
        return (len(assets), 0, assets, [])
    kw = dict(reference=ref, proposal_id=proposal['proposal_id'], root=root, curate_fn=curate)
    first = submit_js_graph_proposal(**kw)
    assert first['status'] == 'uncertain'
    assert first['merged_assets'] == []
    assert 'sensitive' not in json.dumps(first)
    changed = _scan_result(source, digest, urls=[{'url':'https://api.example.test/new'}])
    scans.submit_mode(project_id='proj-1', run_id='run-1', context_ref='account-1', lead_id=lead, result=changed, mode='urls')
    assert prepare(root, ref)['proposal_id'] != proposal['proposal_id']
    second = submit_js_graph_proposal(**kw)
    assert second['status'] == 'confirmed'
    assert second['attempts'] == 2
    assert calls == [proposal['assets'], proposal['assets']]


def test_concurrent_submission_has_one_curator_call(tmp_path):
    from polymerhus.recon.control.js_graph_proposal import submit_js_graph_proposal
    root, _, _, _, ref, _, _ = prepared(tmp_path)
    proposal = prepare(root, ref)
    calls = []
    def curate(assets, observations, project_id, **scope):
        calls.append(1)
        return len(assets), 0, assets, []
    def submit(_):
        return submit_js_graph_proposal(reference=ref, proposal_id=proposal['proposal_id'], root=root, curate_fn=curate)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(submit, range(4)))
    assert len(calls) == 1
    assert all(r['status'] == 'confirmed' for r in results)


@pytest.mark.parametrize('response', [(0,0,[],[]), (1,0,[],[]), None])
def test_zero_writes_and_invalid_curator_return_never_claim_proposed_assets(tmp_path, response):
    from polymerhus.recon.control.js_graph_proposal import submit_js_graph_proposal
    root, _, _, _, ref, _, _ = prepared(tmp_path)
    proposal = prepare(root, ref)
    result = submit_js_graph_proposal(reference=ref, proposal_id=proposal['proposal_id'], root=root,
                                      curate_fn=lambda *a, **k: response)
    assert result['merged_assets'] == []
    assert result['status'] == ('confirmed' if response == (0,0,[],[]) else 'uncertain')


def test_retry_cannot_silently_change_trusted_scope_policy(tmp_path):
    from polymerhus.recon.control.js_graph_proposal import submit_js_graph_proposal
    root, _, _, _, ref, _, _ = prepared(tmp_path)
    proposal = prepare(root, ref)
    def curate(assets, observations, project_id, **scope):
        return 0, 0, [], []
    submit_js_graph_proposal(reference=ref, proposal_id=proposal['proposal_id'], root=root, curate_fn=curate, scope_domain='example.test')
    with pytest.raises(ValueError, match='submission_policy_mismatch'):
        submit_js_graph_proposal(reference=ref, proposal_id=proposal['proposal_id'], root=root, curate_fn=curate)


def test_evidenced_include_correction_supersedes_exclusion_without_inventing_url(tmp_path):
    from polymerhus.recon.control.js_graph_proposal import record_js_graph_annotation
    root, _, digest, lead, ref, _, _ = prepared(tmp_path)
    initial = prepare(root, ref)
    occurrence = next(o for o in initial['outcomes'] if o['facts'].get('url'))
    manifest = AcquisitionManifest(project_id='proj-1', run_id='run-1', root=root, max_run_bytes=1024**2)
    manifest.update(lambda m: m.setdefault('code_access', {}).setdefault('reads', {}).update({
        'read-good': {'context_ref':'account-1', 'project_id':'proj-1', 'run_id':'run-1',
                      'lead_id':lead, 'content_sha256':digest, 'delivery_status':'delivered'}}))
    note = {'candidate_ref':occurrence['candidate_ref'], 'action':'exclude',
            'reason':'false_positive', 'evidence_refs':['read-good']}
    record_js_graph_annotation(reference=ref, root=root, record=note)
    excluded = prepare(root, ref)
    record_js_graph_annotation(reference=ref, root=root, record={**note,'action':'include','reason':'review_corrected_exclusion'})
    corrected = prepare(root, ref)
    assert corrected['assets'] == initial['assets']
    assert corrected['proposal_id'] not in {initial['proposal_id'], excluded['proposal_id']}
    assert next(o for o in corrected['outcomes'] if o['candidate_ref'] == occurrence['candidate_ref'])['decision_refs']


def test_reapplying_prior_admission_decision_after_correction_appends_new_intent(tmp_path):
    from polymerhus.recon.control.js_graph_proposal import record_js_graph_annotation
    root, _, digest, lead, ref, _, _ = prepared(tmp_path)
    occurrence = next(o for o in prepare(root, ref)['outcomes'] if o['facts'].get('url'))
    manifest = AcquisitionManifest(project_id='proj-1', run_id='run-1', root=root, max_run_bytes=1024**2)
    manifest.update(lambda m: m.setdefault('code_access', {}).setdefault('reads', {}).update({
        'read-good': {'context_ref':'account-1', 'project_id':'proj-1', 'run_id':'run-1',
                      'lead_id':lead, 'content_sha256':digest, 'delivery_status':'delivered'}}))
    exclude = {'candidate_ref':occurrence['candidate_ref'], 'action':'exclude',
               'reason':'false_positive', 'evidence_refs':['read-good']}
    first = record_js_graph_annotation(reference=ref, root=root, record=exclude)
    record_js_graph_annotation(reference=ref, root=root, record={**exclude,'action':'include','reason':'review_corrected_exclusion'})
    reapplied = record_js_graph_annotation(reference=ref, root=root, record=exclude)
    assert reapplied['idempotent'] is False
    assert reapplied['record_id'] != first['record_id']
    assert next(o for o in prepare(root, ref)['outcomes'] if o['candidate_ref'] == occurrence['candidate_ref'])['status'] == 'excluded'
    assert record_js_graph_annotation(reference=ref, root=root, record=exclude)['idempotent'] is True


def test_structure_import_is_added_without_reclassifying_scanner_candidate(tmp_path):
    root, _, _, lead, reference, _ = prepared_import(tmp_path)

    proposal = prepare(root, reference)

    endpoints = [
        asset for asset in proposal['assets'] if asset['type'] == 'Endpoint'
    ]
    assert [asset['props']['url'] for asset in endpoints] == [
        'https://cdn.example.test/assets/part.js'
    ]
    scanner = [
        outcome
        for outcome in proposal['outcomes']
        if outcome['candidate_id'].startswith('cand_')
    ]
    structural = [
        outcome
        for outcome in proposal['outcomes']
        if outcome['candidate_id'].startswith('sti_')
    ]
    assert len(scanner) == 1
    assert scanner[0]['status'] == 'unresolved'
    assert scanner[0]['reason'] == 'relative_operation_unknown'
    assert len(structural) == 1
    assert structural[0]['status'] == 'proposed'
    assert structural[0]['facts']['source_span']['end_byte'] > (
        structural[0]['facts']['source_span']['start_byte']
    )
    assert proposal['structure_inputs'][0]['item_id'] == structural[0][
        'candidate_id'
    ]
    assert proposal['structure_inputs'][0]['module_base_url'] == (
        'https://cdn.example.test/assets/app.js'
    )
    manifest = AcquisitionManifest(
        project_id='proj-1',
        run_id='run-1',
        root=root,
        max_run_bytes=1024**2,
    ).get()
    assert set(manifest['leads']) == {lead}


def test_structure_evidence_changes_new_version_but_not_frozen_snapshot(tmp_path):
    from polymerhus.recon.control.js_graph_proposal import load_js_graph_proposal

    root, _, _, lead, reference, _ = prepared_import(
        tmp_path,
        with_structure=False,
    )
    before = prepare(root, reference)
    assert before['assets'] == []
    assert 'structure_index_missing' in before['coverage']['gaps']

    source = tmp_path / 'source.js'
    StructureStore(root=root).store_index(
        project_id='proj-1',
        run_id='run-1',
        context_ref='account-1',
        lead_id=lead,
        source_bytes=source.read_bytes(),
        parsed=parse_structure_bytes(source.read_bytes()),
        parent_final_url='https://cdn.example.test/assets/app.js',
    )
    after = prepare(root, reference)

    assert after['assets']
    assert after['proposal_id'] != before['proposal_id']
    assert load_js_graph_proposal(
        reference=reference,
        proposal_id=before['proposal_id'],
        root=root,
    ) == before


def test_corrupt_structure_names_gap_without_hiding_scanner_outcome(tmp_path):
    from polymerhus.app.data_root import project_dir

    root, _, _, _, reference, _ = prepared_import(tmp_path)
    index_path = next(
        (
            project_dir('proj-1', 'recon/js_analysis', root=root)
            / 'run-1'
            / 'structures'
        ).glob('*.json')
    )
    index_path.write_text('{corrupt', encoding='utf-8')

    proposal = prepare(root, reference)

    assert proposal['assets'] == []
    assert 'structure_index_corrupt' in proposal['coverage']['gaps']
    assert any(
        outcome['reason'] == 'relative_operation_unknown'
        for outcome in proposal['outcomes']
        if outcome['candidate_id'].startswith('cand_')
    )


def test_structural_outcome_is_readable_with_span_without_raw_specifier(tmp_path):
    from polymerhus.recon.control.js_graph_proposal import read_js_graph_candidates

    root, _, _, lead, reference, _ = prepared_import(tmp_path)
    page = read_js_graph_candidates(
        reference=reference,
        lead_id=lead,
        root=root,
    )

    item = next(
        candidate
        for candidate in page['candidates']
        if candidate['candidate_id'].startswith('sti_')
    )
    assert item['status'] == 'proposed'
    assert item['facts']['source_span']['end_byte'] > (
        item['facts']['source_span']['start_byte']
    )
    assert item['facts']['structure_item_id'] == item['candidate_id']
    assert item['facts']['module_base_url'] == (
        'https://cdn.example.test/assets/app.js'
    )


def test_structure_import_passes_through_unchanged_curator(tmp_path):
    from polymerhus.recon.control.js_graph_proposal import submit_js_graph_proposal
    from polymerhus.recon.domain.curator import curate

    root, _, _, _, reference, _ = prepared_import(tmp_path)
    proposal = prepare(root, reference)
    proposed_sources = [
        asset['props'].get('source')
        for asset in proposal['assets']
        if asset['type'] == 'Endpoint'
    ]

    def common_curator(assets, observations, project_id, **scope):
        return curate(
            assets,
            observations,
            project_id,
            merge_fn=lambda cypher, params: None,
            **scope,
        )

    receipt = submit_js_graph_proposal(
        reference=reference,
        proposal_id=proposal['proposal_id'],
        root=root,
        curate_fn=common_curator,
        scope_domain='cdn.example.test',
        seed_domain='cdn.example.test',
        seed_root_type='Domain',
    )

    assert proposed_sources == ['js_structure']
    assert receipt['status'] == 'confirmed'
    assert receipt['assets_merged'] == 2
    assert {asset['type'] for asset in receipt['merged_assets']} == {
        'BaseURL',
        'Endpoint',
    }
    endpoint = next(
        asset
        for asset in receipt['merged_assets']
        if asset['type'] == 'Endpoint'
    )
    assert endpoint['props']['source'] == 'js_structure'
    assert endpoint['props']['url'] == 'https://cdn.example.test/assets/part.js'
    assert receipt['omission_reasons_available'] is False


def test_confirmed_structural_proposal_retries_without_rebuilding(tmp_path):
    from polymerhus.app.data_root import project_dir
    from polymerhus.recon.control.js_graph_proposal import submit_js_graph_proposal

    root, _, _, _, reference, _ = prepared_import(tmp_path)
    proposal = prepare(root, reference)
    calls = []

    def curator(assets, observations, project_id, **scope):
        calls.append([asset.model_dump() for asset in assets])
        return len(assets), 0, assets, []

    kwargs = {
        'reference': reference,
        'proposal_id': proposal['proposal_id'],
        'root': root,
        'curate_fn': curator,
        'scope_domain': 'cdn.example.test',
        'seed_domain': 'cdn.example.test',
    }
    first = submit_js_graph_proposal(**kwargs)
    index_path = next(
        (
            project_dir('proj-1', 'recon/js_analysis', root=root)
            / 'run-1'
            / 'structures'
        ).glob('*.json')
    )
    index_path.unlink()
    second = submit_js_graph_proposal(**kwargs)

    assert first['status'] == 'confirmed'
    assert second['status'] == 'confirmed'
    assert second['reused_confirmation'] is True
    assert second['merged_assets'] == first['merged_assets']
    assert calls == [proposal['assets']]
