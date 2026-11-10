"""Saved scan snapshots must retain occurrence scope and reject obsolete cache."""
import json
import pytest

from tests.recon.js_acquisition.test_scan_store import _acquired_lead, _scan_result
from polymerhus.app.data_root import ensure_project
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_acquisition.scan_store import ScanStore, ScanStoreError


def prepared(tmp_path):
    import hashlib
    root = tmp_path / 'data'
    ensure_project('proj-1', root=root)
    source = tmp_path / 'source.js'
    source.write_bytes(b'const saved = true;')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    lead, reference = _acquired_lead(root, source=source, digest=digest)
    result = _scan_result(source, digest, urls=[{'url': 'https://api.example.test/a'}],
                          secrets=[{'kind': 'key', 'secret': 'fixture-value'}])
    store = ScanStore(root=root)
    for mode in ('urls', 'secrets'):
        store.submit_mode(project_id='proj-1', run_id='run-1', lead_id=lead,
                          context_ref='account-1', result=result, mode=mode)
    return root, source, digest, lead, reference, result, store


def test_snapshot_is_scoped_and_reads_persisted_partial_results(tmp_path):
    root, source, digest, lead, _, result, store = prepared(tmp_path)
    second, _ = _acquired_lead(root, source=source, digest=digest, context_ref='account-2', pod_id='pod-2')
    store.link_lead(project_id='proj-1', run_id='run-1', lead_id=second,
                    context_ref='account-2', scan_key=result['scan_key'])
    snapshot = store.snapshot(project_id='proj-1', run_id='run-1', context_ref='account-1')
    assert [s['lead_id'] for s in snapshot['occurrences']] == [lead]
    assert len(snapshot['occurrences'][0]['candidates']) == 2
    assert snapshot['occurrences'][0]['scan_key'] == result['scan_key']
    assert store.snapshot(project_id='proj-1', run_id='run-2', context_ref='account-1')['occurrences'] == []
    assert store.snapshot(project_id='proj-2', run_id='run-1', context_ref='account-1')['occurrences'] == []


def test_old_cache_is_not_reusable_or_linkable_and_has_publication_gap(tmp_path):
    root, _, _, lead, _, result, store = prepared(tmp_path)
    manifest = AcquisitionManifest(project_id='proj-1', run_id='run-1', root=root, max_run_bytes=1024**2)
    manifest.update(lambda m: m['scans'][result['scan_key']].update(candidate_schema_version=1))
    assert store.find_reusable(project_id='proj-1', run_id='run-1', source_sha256=result['source']['sha256'],
        binary=result['binary'], options=result['options'], pattern_fingerprint=result['pattern_fingerprint']) is None
    with pytest.raises(ScanStoreError, match='incompatible_candidate_projection'):
        store.link_lead(project_id='proj-1', run_id='run-1', lead_id=lead, context_ref='account-1', scan_key=result['scan_key'])
    snap = store.snapshot(project_id='proj-1', run_id='run-1', context_ref='account-1')
    assert snap['occurrences'] == []
    assert 'incompatible_candidate_projection' in snap['gaps']


def test_snapshot_names_missing_corrupt_and_limited_inputs(tmp_path):
    root, _, _, _, _, result, store = prepared(tmp_path)
    path = root / 'proj-1/recon/js_analysis/run-1/scans' / (result['scan_key'] + '.jsonl')
    assert 'candidate_limit' in store.snapshot(project_id='proj-1', run_id='run-1', context_ref='account-1', max_candidates=1)['gaps']
    path.unlink()
    assert 'scan_candidate_file_missing' in store.snapshot(project_id='proj-1', run_id='run-1', context_ref='account-1')['gaps']
    path.write_text('{broken\n')
    assert 'scan_candidate_file_invalid' in store.snapshot(project_id='proj-1', run_id='run-1', context_ref='account-1')['gaps']


def test_snapshot_refuses_candidate_file_traversal(tmp_path):
    root, _, _, _, _, result, store = prepared(tmp_path)
    manifest = AcquisitionManifest(project_id='proj-1', run_id='run-1', root=root, max_run_bytes=1024**2)
    manifest.update(lambda m: m['scans'][result['scan_key']].update(candidate_file='scans/../../other.jsonl'))
    snap = store.snapshot(project_id='proj-1', run_id='run-1', context_ref='account-1')
    assert snap['occurrences'] == []
    assert 'scan_candidate_file_invalid' in snap['gaps']
