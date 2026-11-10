"""Real unchanged curator proof; requires an explicitly isolated Neo4j target.

Never starts compose or connects to the ordinary development stack. Run with
PH_JS_GRAPH_ISOLATED=1 and NEO4J_* pointing at a task-owned ephemeral container.
"""
import hashlib
import json
import os
import uuid

import pytest
from neo4j import GraphDatabase

from tests.conftest import neo4j_target
from tests.recon.test_js_graph_scan_snapshot import prepared
from tests.recon.js_acquisition.test_scan_store import _scan_result
from polymerhus.recon.control.js_graph_proposal import prepare_js_graph_proposal, submit_js_graph_proposal
from polymerhus.recon.domain.curator import curate
from polymerhus.recon.domain.parsers.jsluice_parser import parse
from polymerhus.recon.js_intake import issue_js_intake_reference


@pytest.fixture
def graph():
    assert os.environ.get('PH_JS_GRAPH_ISOLATED') == '1', 'explicit isolated graph required'
    uri, auth = neo4j_target()
    with GraphDatabase.driver(uri, auth=auth) as driver:
        driver.verify_connectivity()
        with driver.session() as session:
            yield session


def _state(session, project_id):
    nodes = [dict(r) for r in session.run(
        'MATCH (n {project_id:$p}) RETURN labels(n) AS labels, properties(n) AS props ORDER BY labels(n)', p=project_id)]
    edges = [dict(r) for r in session.run(
        'MATCH (a {project_id:$p})-[r]->(b {project_id:$p}) RETURN type(r) AS rel, properties(a) AS source, properties(b) AS target ORDER BY type(r)', p=project_id)]
    return nodes, edges


def test_real_curator_filters_legacy_sha1_and_lost_response_retry(tmp_path, graph, record_property):
    root, source, digest, lead, ref, _, scans = prepared(tmp_path)
    result = _scan_result(source, digest, urls=[
        {'url':'https://app.example.test/api/items?token=PRIVATE_FIXTURE_QUERY', 'method':'POST',
         'queryParams':['page'], 'bodyParams':['name']},
        {'url':'https://app.example.test/assets/vendor-ui.chunk.js'},
        {'url':'https://outside.invalid/external'},
    ], secrets=[{'kind':'key','secret':'PRIVATE_FIXTURE_SECRET'}])
    for mode in ('urls','secrets'):
        scans.submit_mode(project_id='proj-1',run_id='run-1',lead_id=lead,
                          context_ref='account-1',result=result,mode=mode)
    # Move only task-owned input files to a unique project namespace.
    project_id = 'it-js-graph-' + uuid.uuid4().hex
    (root / 'proj-1').rename(root / project_id)
    ref = issue_js_intake_reference(project_id,'run-1',context_ref='account-1')
    proposal = prepare_js_graph_proposal(reference=ref,root=root,closure={'status':'complete','reason':'completed'})
    assert 'PRIVATE_FIXTURE_' not in json.dumps(proposal)
    attempts = []
    def merge(cypher, params):
        graph.run(cypher, **params).consume()
    def lost_reply(assets, observations, project_id, **scope):
        result = curate(assets, observations, project_id, merge_fn=merge, **scope)
        attempts.append(result)
        if len(attempts) == 1:
            raise TimeoutError('fixture reply lost after actual commits')
        return result
    kw = dict(reference=ref,root=root,proposal_id=proposal['proposal_id'],
              curate_fn=lost_reply,scope_domain='app.example.test',seed_domain='app.example.test')
    try:
        first = submit_js_graph_proposal(**kw)
        assert first['status'] == 'uncertain' and not first['merged_assets']
        before = _state(graph, project_id)
        second = submit_js_graph_proposal(**kw)
        assert second['status'] == 'confirmed' and second['attempts'] == 2
        after = _state(graph, project_id)
        record_property('nodes_before_retry', len(before[0]))
        record_property('nodes_after_retry', len(after[0]))
        record_property('edges_before_retry', len(before[1]))
        record_property('edges_after_retry', len(after[1]))
        assert len(before[0]) == len(after[0]) == 6
        assert len(before[1]) == len(after[1]) == 5
        node_props = [n['props'] for n in after[0]]
        endpoints = [n['props'] for n in after[0] if 'Endpoint' in n['labels']]
        assert [(e['baseurl'],e['path'],e['method']) for e in endpoints] == [('https://app.example.test','/api/items','POST')]
        params = {(n['props']['name'],n['props']['position']) for n in after[0] if 'Parameter' in n['labels']}
        assert params == {('page','query'),('token','query'),('name','body')}
        secrets = [n['props'] for n in after[0] if 'Secret' in n['labels']]
        expected_sha1 = hashlib.sha1(b'PRIVATE_FIXTURE_SECRET').hexdigest()
        assert [s['value_hash'] for s in secrets] == [expected_sha1]
        assert secrets[0]['redacted'] is True
        assert {'HAS_ENDPOINT','HAS_PARAMETER','HAS_SECRET'} == {e['rel'] for e in after[1]}
        legacy = parse(json.dumps({'kind':'key','secret':'PRIVATE_FIXTURE_SECRET','source_url':'https://app.example.test/source.js'}))
        curate(legacy, [], project_id, merge_fn=merge, scope_domain='app.example.test')
        assert len(_state(graph,project_id)[0]) == 6
        assert all('PRIVATE_FIXTURE_' not in json.dumps(p, default=str) for p in node_props)
        assert second['assets_merged'] == len(second['merged_assets'])
        assert len(second['merged_assets']) < len(proposal['assets'])
        # A confirmed retry uses its durable receipt and does not call the graph.
        assert submit_js_graph_proposal(**kw)['reused_confirmation'] is True
        assert len(attempts) == 2
        foreign = 'it-js-graph-foreign-' + uuid.uuid4().hex
        try:
            curate(legacy, [], foreign, merge_fn=merge, scope_domain='app.example.test')
            assert len(_state(graph,foreign)[0]) == 2
            assert len(_state(graph,project_id)[0]) == 6
        finally:
            graph.run('MATCH (n {project_id:$p}) DETACH DELETE n',p=foreign).consume()
    finally:
        graph.run('MATCH (n {project_id:$p}) DETACH DELETE n',p=project_id).consume()
