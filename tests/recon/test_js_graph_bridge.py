"""The existing Exec surface may record optional decisions, never submit graph writes."""
import argparse
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.recon.test_js_graph_scan_snapshot import prepared
from polymerhus.recon.js_specialist.bridge import build_router
from polymerhus.recon.js_intake.cli import parse_operation, invoke_operation


def test_graph_candidates_are_scoped_bounded_and_cursor_rejects_new_view(tmp_path):
    from polymerhus.recon.control.js_graph_proposal import read_js_graph_candidates
    root, _, _, lead, ref, _, _ = prepared(tmp_path)
    first = read_js_graph_candidates(reference=ref, lead_id=lead, root=root, limit=1)
    assert len(first['candidates']) == 1
    assert first['next_cursor']
    second = read_js_graph_candidates(reference=ref, lead_id=lead, root=root, limit=1, cursor=first['next_cursor'])
    assert len(second['candidates']) == 1
    assert second['candidates'][0]['candidate_ref'] != first['candidates'][0]['candidate_ref']
    assert second['next_cursor'] is None
    assert 'fixture-value' not in json.dumps(first) + json.dumps(second)
    assert len(json.dumps(first).encode()) <= 16000
    from polymerhus.recon.js_intake import issue_js_intake_reference
    other = issue_js_intake_reference('proj-1','run-1', context_ref='other')
    with pytest.raises((ValueError, LookupError)):
        read_js_graph_candidates(reference=other, lead_id=lead, root=root, cursor=first['next_cursor'])


def test_bridge_and_cli_use_the_existing_rpc_without_exposing_submission(tmp_path, monkeypatch):
    root, _, _, lead, ref, _, _ = prepared(tmp_path)
    app = FastAPI(); app.include_router(build_router(root=root, retention=None))
    client = TestClient(app)
    def rpc(url, reference, payload, **kw):
        response = client.post('/recon/js-specialist/rpc', headers={'X-JS-Intake-Reference':reference}, json=payload)
        assert response.status_code == 200, response.text
        return response.json()
    monkeypatch.setattr('polymerhus.recon.js_intake.cli._rpc', rpc)
    args = parse_operation(['graph-candidates', lead, '--limit', '1'])
    result = invoke_operation('http://unused', ref, args)
    assert result['candidates'][0]['candidate_ref'].startswith('occ_')
    with pytest.raises((argparse.ArgumentError, ValueError, SystemExit)):
        parse_operation(['graph-submit', 'anything'])
    response = client.post('/recon/js-specialist/rpc', headers={'X-JS-Intake-Reference':ref},
                           json={'operation':'graph_submit', 'target':'anything'})
    assert response.status_code == 422


def test_graph_note_rejects_unsupported_model_urls_and_foreign_read(tmp_path):
    from polymerhus.recon.control.js_graph_proposal import read_js_graph_candidates
    root, _, _, lead, ref, _, _ = prepared(tmp_path)
    view = read_js_graph_candidates(reference=ref, lead_id=lead, root=root)
    app = FastAPI(); app.include_router(build_router(root=root, retention=None))
    record = {'candidate_ref':view['candidates'][0]['candidate_ref'], 'action':'exclude',
              'reason':'false_positive', 'evidence_refs':['missing'], 'url':'https://invented.test'}
    response = TestClient(app).post('/recon/js-specialist/rpc', headers={'X-JS-Intake-Reference':ref},
                                    json={'operation':'graph_note', 'record':record})
    assert response.status_code == 422
