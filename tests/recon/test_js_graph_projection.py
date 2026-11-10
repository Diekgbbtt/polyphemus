"""Graph compatibility and honest reconstruction from sanitized scanner facts."""
import hashlib
import json
from urllib.parse import parse_qsl, urlsplit

import pytest

from polymerhus.recon.domain.parsers._urls import url_to_deltas
from polymerhus.recon.domain.parsers.jsluice_parser import parse
from polymerhus.recon.js_acquisition.scan_worker import _candidate, scan_key_for


SHA = 'a' * 64


def context(**changes):
    return {'project_id': 'p', 'run_id': 'r', 'context_ref': 'auth',
            'lead_id': 'lead', 'source_sha256': SHA, 'scan_key': 'b' * 64,
            'producer': 'jsluice', 'discovery_producer': 'katana',
            'source_url': 'https://cdn.example.test/scripts/app.mjs', **changes}


def build(entry, *, mode='urls', ctx=None, decisions=()):
    from polymerhus.recon.domain.js_graph_proposal import build_js_asset_deltas
    cand = _candidate(mode=mode, source_sha256=SHA, line_number=1, entry=entry)
    return build_js_asset_deltas([{'candidate': cand, 'source_context_id': 's'}],
                                source_contexts={'s': context(**(ctx or {}))},
                                decisions=decisions)


def structural_import(specifier='./part.js', **changes):
    return {
        'project_id': 'p',
        'run_id': 'r',
        'context_ref': 'auth',
        'lead_id': 'lead',
        'source_sha256': SHA,
        'source_size': 123,
        'index_id': 'stx_' + '1' * 32,
        'index_integrity': 'integrity-1',
        'item_id': 'sti_' + '2' * 32,
        'start_byte': 7,
        'end_byte': 20,
        'specifier': specifier,
        'subtype': 'static',
        'import_kind': 'named',
        'module_base_url': 'https://cdn.example.test/scripts/app.mjs',
        'module_base_ref': 'structure:stx_' + '1' * 32 + ':sti_' + '2' * 32,
        **changes,
    }


def structural_context(**changes):
    return context(
        module_base_url='https://cdn.example.test/scripts/app.mjs',
        module_base_ref='structure:stx_' + '1' * 32,
        **changes,
    )


def identities(assets):
    return [(a.type, a.identity, [e.model_dump() for e in a.edges]) for a in assets]


@pytest.mark.parametrize('secret', [
    {'data': {'secret': 'fixture-secret', 'key': 'other'}},
    {'data': {'key': 'fixture-key'}}, {'data': {'value': 'fixture-value'}},
    {'data': {'token': 'fixture-token'}}, {'data': {'nested': {'a': 2, 'b': 1}}},
    {'data': 'fixture-data'}, {'secret': 'legacy-fixture'},
])
def test_secret_sha1_equals_legacy_and_never_emits_value(secret):
    entry = {'kind': 'fixture-key', **secret}
    candidate = _candidate(mode='secrets', source_sha256=SHA, line_number=1, entry=entry)
    legacy = parse(json.dumps(entry))[-1]
    assert candidate.get('secret_hash_algorithm') == 'sha1'
    assert candidate['secret_fingerprint'] == legacy.identity['value_hash']
    result = build(entry, mode='secrets')
    actual = next(a for a in result.assets if a.type == 'Secret')
    assert actual.identity == legacy.identity
    assert actual.props['redacted'] is True
    assert 'fixture-secret' not in result.model_dump_json()


def test_url_parameter_identities_and_edges_equal_legacy_without_query_values():
    entry = {'url': 'https://api.example.test:8443/v1/items?view=PRIVATE&empty=',
             'method': 'POST', 'queryParams': ['view', 'page'], 'bodyParams': ['name']}
    result = build(entry)
    expected = url_to_deltas(entry['url'], method='POST', source='jsluice',
                             query_params=['view', 'page'], body_params=['name'])
    assert identities(result.assets) == identities(expected)
    assert 'PRIVATE' not in result.model_dump_json()
    assert next(a.props['url'] for a in result.assets if a.type == 'Endpoint') == 'https://api.example.test:8443/v1/items?view=&empty='
    assert result.outcomes[0].status == 'proposed'


@pytest.mark.parametrize('entry,ctx,endpoint,reason', [
    ({'url': '/api/items', 'type': 'fetch'}, {}, None, 'execution_base_unproven'),
    ({'url': '/api/items', 'kind': 'fetch'},
     {'execution_base_url': 'https://app.example.test/ui/', 'execution_base_ref': 'read-1'},
     'https://app.example.test/api/items', None),
    ({'url': 'items', 'kind': 'fetch'},
     {'execution_base_url': 'https://app.example.test/ui/', 'execution_base_ref': 'read-1'},
     'https://app.example.test/ui/items', None),
    ({'url': './part.mjs', 'kind': 'import'},
     {'module_base_url': 'https://cdn.example.test/scripts/app.mjs', 'module_base_ref': 'item-1'},
     'https://cdn.example.test/scripts/part.mjs', None),
    ({'url': './part.mjs', 'kind': 'import'}, {}, None, 'module_base_unproven'),
    ({'url': './part.mjs', 'kind': 'import'},
     {'module_base_url': 'webpack:///src/app.ts', 'module_base_ref': 'item-1'},
     None, 'module_base_unproven'),
    ({'url': '//api.example.test/v1', 'kind': 'fetch'}, {}, None, 'execution_base_unproven'),
    ({'url': 'https://api.example.test/token/private'}, {}, None, 'url_identity_redacted'),
    ({'url': '/v1/' + '/'.join('seg' for _ in range(1000))}, {}, None, 'url_identity_truncated'),
    ({'url': 'https://api.example.test/v1', 'method': 'GET' * 20}, {}, None, 'method_unresolved'),
    ({'url': 'https://api.example.test/v1', 'method': 'DYNAMIC'}, {}, None, 'method_unresolved'),
])
def test_operation_specific_bases_and_missing_identity_are_honest(entry, ctx, endpoint, reason):
    result = build(entry, ctx=ctx)
    urls = [a.props['url'] for a in result.assets if a.type == 'Endpoint']
    assert urls == ([endpoint] if endpoint else [])
    if reason:
        assert result.outcomes[0].reason == reason


def test_long_parameter_names_are_omitted_without_truncated_identities():
    raw = 'x' * 200
    result = build({'url': 'https://api.example.test/items',
                    'queryParams': [raw, 'page'], 'bodyParams': ['name']})
    names = {a.identity['name'] for a in result.assets if a.type == 'Parameter'}
    assert names == {'page', 'name'}
    assert 'parameter_names_limited' in result.gaps


def test_projection_version_changes_scan_cache_identity():
    kw = dict(source_sha256=SHA, binary={'sha256': 'b' * 64}, options={}, pattern_fingerprint='p')
    assert scan_key_for(**kw, candidate_schema_version=1) != scan_key_for(**kw)


def test_old_sha256_secret_is_unresolved_not_relabelled():
    from polymerhus.recon.domain.js_graph_proposal import build_js_asset_deltas
    cand = _candidate(mode='secrets', source_sha256=SHA, line_number=1,
                      entry={'kind': 'key', 'secret': 'fixture'})
    cand.pop('secret_hash_algorithm', None)
    cand['secret_fingerprint'] = hashlib.sha256(b'fixture').hexdigest()
    # Old IDs remain valid for their own old projection.
    from polymerhus.recon.js_acquisition.scan_worker import candidate_id_for
    cand['candidate_id'] = candidate_id_for(cand)
    result = build_js_asset_deltas([{'candidate': cand, 'source_context_id': 's'}],
                                  source_contexts={'s': context()})
    assert result.assets == []
    assert result.outcomes[0].reason == 'incompatible_secret_projection'


def test_occurrence_identity_includes_auth_run_and_project():
    refs = [build({'url': 'https://api.example.test/a'}, ctx=ctx).outcomes[0].candidate_ref
            for ctx in ({}, {'project_id': 'p2'}, {'run_id': 'r2'}, {'context_ref': 'auth2'})]
    assert len(set(refs)) == 4


def test_source_mismatch_and_unknown_context_never_produce_assets():
    result = build({'url': 'https://api.example.test/a'}, ctx={'source_sha256': 'f' * 64})
    assert result.assets == []
    assert result.outcomes[0].reason == 'candidate_source_mismatch'


def test_scan_candidate_names_are_bounded_and_never_contain_truncated_names():
    candidate = _candidate(mode='urls', source_sha256=SHA, line_number=1,
        entry={'url': 'https://api.example.test/a', 'bodyParams': ['name' + str(i) * 50 for i in range(100)]})
    assert len(json.dumps(candidate, separators=(',', ':')).encode()) <= 4096
    assert candidate['safe_metadata']['parameter_names_limited']


def test_sanitized_query_preserves_unchanged_curator_noise_admission():
    from polymerhus.recon.domain.noise_filter import filter_deltas
    entry = {'url': 'https://app.example.test/assets/preview.png?width=PRIVATE'}
    result = build(entry)
    expected = filter_deltas(parse(json.dumps(entry)))
    assert {a.type for a in filter_deltas(result.assets)} == {a.type for a in expected}
    assert any(a.type == 'Endpoint' for a in filter_deltas(result.assets))
    assert 'PRIVATE' not in result.model_dump_json()


def test_secret_uses_proven_source_origin_even_if_source_path_is_redacted():
    result = build({'kind':'key','secret':'fixture'}, mode='secrets',
                   ctx={'source_url':'https://cdn.example.test/token/private?auth=secret'})
    secret = next(a for a in result.assets if a.type == 'Secret')
    assert secret.edges[0].node_identity == {'url':'https://cdn.example.test'}


def test_duplicate_endpoint_preserves_query_evidence_for_unchanged_noise_filter():
    from polymerhus.recon.domain.js_graph_proposal import build_js_asset_deltas
    from polymerhus.recon.domain.noise_filter import filter_deltas
    entries = [
        {'url':'https://app.example.test/assets/preview.png'},
        {'url':'https://app.example.test/assets/preview.png?width=PRIVATE'},
        {'url':'https://app.example.test/assets/preview.png?height=PRIVATE'},
    ]
    occurrences = [{'candidate': _candidate(mode='urls', source_sha256=SHA, line_number=i+1, entry=e),
                    'source_context_id':'s'} for i,e in enumerate(entries)]
    result = build_js_asset_deltas(occurrences, source_contexts={'s':context()})
    filtered = filter_deltas(result.assets)
    endpoints = [a for a in filtered if a.type == 'Endpoint']
    assert len(endpoints) == 1
    assert {key for key,_ in parse_qsl(urlsplit(endpoints[0].props['url']).query, keep_blank_values=True)} == {'width','height'}
    assert 'PRIVATE' not in result.model_dump_json()
    # Reversing observations cannot change whether an identical endpoint survives.
    reversed_result = build_js_asset_deltas(list(reversed(occurrences)), source_contexts={'s':context()})
    assert len([a for a in filter_deltas(reversed_result.assets) if a.type == 'Endpoint']) == 1


def test_structure_import_resolves_from_exact_module_base():
    from polymerhus.recon.domain.js_graph_proposal import build_js_asset_deltas

    evidence = structural_import()
    result = build_js_asset_deltas(
        [],
        source_contexts={'s': structural_context()},
        structural_imports=[
            {'evidence': evidence, 'source_context_id': 's'}
        ],
    )

    endpoints = [asset for asset in result.assets if asset.type == 'Endpoint']
    assert [asset.props['url'] for asset in endpoints] == [
        'https://cdn.example.test/scripts/part.js'
    ]
    assert endpoints[0].props['source'] == 'js_structure'
    outcome = result.outcomes[0]
    assert outcome.candidate_id == evidence['item_id']
    assert outcome.status == 'proposed'
    assert outcome.facts == {
        'url': 'https://cdn.example.test/scripts/part.js',
        'method': 'GET',
        'context_ref': 'auth',
        'module_base_url': 'https://cdn.example.test/scripts/app.mjs',
        'resolution_base_ref': evidence['module_base_ref'],
        'structure_index_id': evidence['index_id'],
        'structure_index_integrity': evidence['index_integrity'],
        'structure_item_id': evidence['item_id'],
        'source_sha256': SHA,
        'source_span': {'start_byte': 7, 'end_byte': 20},
        'import_subtype': 'static',
        'import_kind': 'named',
    }


def test_structure_import_never_reclassifies_matching_scanner_literals():
    from polymerhus.recon.domain.js_graph_proposal import build_js_asset_deltas

    candidates = [
        _candidate(
            mode='urls',
            source_sha256=SHA,
            line_number=index,
            entry={'url': './part.js', 'kind': 'stringLiteral'},
        )
        for index in (1, 2)
    ]
    result = build_js_asset_deltas(
        [
            {'candidate': candidate, 'source_context_id': 's'}
            for candidate in candidates
        ],
        source_contexts={'s': structural_context()},
        structural_imports=[
            {
                'evidence': structural_import(),
                'source_context_id': 's',
            }
        ],
    )

    scanner = [
        outcome
        for outcome in result.outcomes
        if outcome.candidate_ref.startswith('occ_')
        and outcome.candidate_id.startswith('cand_')
    ]
    structural = [
        outcome
        for outcome in result.outcomes
        if outcome.candidate_id == structural_import()['item_id']
    ]
    assert len(scanner) == 2
    assert all(outcome.status == 'unresolved' for outcome in scanner)
    assert all(
        outcome.reason == 'relative_operation_unknown'
        for outcome in scanner
    )
    assert len(structural) == 1
    assert structural[0].status == 'proposed'
    assert [a.type for a in result.assets].count('Endpoint') == 1


def test_structure_import_requires_matching_scope_hash_and_base():
    from polymerhus.recon.domain.js_graph_proposal import build_js_asset_deltas

    cases = [
        (
            {'project_id': 'other'},
            'structure_import_context_mismatch',
        ),
        (
            {'source_sha256': 'f' * 64},
            'structure_import_source_mismatch',
        ),
        (
            {'module_base_url': 'https://cdn.example.test/other/app.mjs'},
            'structure_import_base_mismatch',
        ),
        (
            {'module_base_url': None, 'module_base_ref': None},
            'structure_import_base_unproven',
        ),
        (
            {'specifier': 'react'},
            'structure_import_specifier_unresolved',
        ),
    ]
    for changes, reason in cases:
        result = build_js_asset_deltas(
            [],
            source_contexts={'s': structural_context()},
            structural_imports=[
                {
                    'evidence': structural_import(**changes),
                    'source_context_id': 's',
                }
            ],
        )
        assert result.assets == []
        assert reason in result.gaps
        assert result.outcomes[0].status == 'unresolved'
        assert result.outcomes[0].reason == reason


def test_structure_import_deduplicates_assets_but_keeps_each_item_evidence():
    from polymerhus.recon.domain.js_graph_proposal import build_js_asset_deltas

    first = structural_import()
    second = structural_import(
        item_id='sti_' + '3' * 32,
        start_byte=30,
        end_byte=43,
        module_base_ref='structure:stx_' + '1' * 32 + ':sti_' + '3' * 32,
    )
    result = build_js_asset_deltas(
        [],
        source_contexts={'s': structural_context()},
        structural_imports=[
            {'evidence': first, 'source_context_id': 's'},
            {'evidence': second, 'source_context_id': 's'},
        ],
    )

    assert [asset.type for asset in result.assets] == ['BaseURL', 'Endpoint']
    assert len(result.outcomes) == 2
    assert len({o.candidate_ref for o in result.outcomes}) == 2
    assert result.outcomes[0].asset_refs == result.outcomes[1].asset_refs


def test_structure_import_dedupes_against_canonical_scanner_import():
    from polymerhus.recon.domain.js_graph_proposal import build_js_asset_deltas

    scanner = _candidate(
        mode='urls',
        source_sha256=SHA,
        line_number=1,
        entry={'url': './part.js', 'kind': 'import'},
    )
    result = build_js_asset_deltas(
        [{'candidate': scanner, 'source_context_id': 's'}],
        source_contexts={'s': structural_context()},
        structural_imports=[
            {'evidence': structural_import(), 'source_context_id': 's'}
        ],
    )

    assert [asset.type for asset in result.assets] == ['BaseURL', 'Endpoint']
    assert len(result.outcomes) == 2
    assert result.outcomes[0].asset_refs == result.outcomes[1].asset_refs


def test_structure_import_does_not_change_unproven_upload_candidate():
    from polymerhus.recon.domain.js_graph_proposal import build_js_asset_deltas

    upload = _candidate(
        mode='urls',
        source_sha256=SHA,
        line_number=2,
        entry={'url': '/upload/image', 'kind': 'm.fetchApi'},
    )
    result = build_js_asset_deltas(
        [{'candidate': upload, 'source_context_id': 's'}],
        source_contexts={'s': structural_context()},
        structural_imports=[
            {'evidence': structural_import(), 'source_context_id': 's'}
        ],
    )

    upload_outcome = next(
        outcome
        for outcome in result.outcomes
        if outcome.candidate_id == upload['candidate_id']
    )
    assert upload_outcome.status == 'unresolved'
    assert upload_outcome.reason == 'relative_operation_unknown'
    assert all('/upload/image' not in asset.props.get('url', '') for asset in result.assets)


def test_structure_import_does_not_reclassify_same_specifier_request():
    from polymerhus.recon.domain.js_graph_proposal import build_js_asset_deltas

    request = _candidate(
        mode='urls',
        source_sha256=SHA,
        line_number=3,
        entry={'url': './part.js', 'kind': 'fetch'},
    )
    result = build_js_asset_deltas(
        [{'candidate': request, 'source_context_id': 's'}],
        source_contexts={'s': structural_context()},
        structural_imports=[
            {'evidence': structural_import(), 'source_context_id': 's'}
        ],
    )

    request_outcome = next(
        outcome
        for outcome in result.outcomes
        if outcome.candidate_id == request['candidate_id']
    )
    assert request_outcome.status == 'unresolved'
    assert request_outcome.reason == 'execution_base_unproven'
    structural = next(
        outcome
        for outcome in result.outcomes
        if outcome.candidate_id.startswith('sti_')
    )
    assert structural.status == 'proposed'
