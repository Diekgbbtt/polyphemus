import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from polymerhus.app.data_root import ensure_project
from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_acquisition.code_access import CodeAccessService
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_intake import (
    JsIntakeReader,
    JsIntakeStore,
    issue_js_intake_reference,
)
from polymerhus.recon.js_specialist.behavior import (
    BehaviorError,
    BehaviorReconstruction,
)
from polymerhus.recon.js_specialist.notes import RunNotes
from polymerhus.recon.js_specialist.triage import EvidenceTriage


def _add_source(
    manifest,
    *,
    lead_id,
    source_id,
    content,
    context_ref='account-a',
):
    digest = hashlib.sha256(content).hexdigest()
    manifest.update(
        lambda value: value.setdefault('recovery', {})
        .setdefault('sources', {})
        .update({
            source_id: {
                'source_id': source_id,
                'lead_id': lead_id,
                'context_ref': context_ref,
                'kind': 'typescript',
                'content_state': 'text',
                'content_sha256': digest,
                'size': len(content),
                'work_file_ref': (
                    f'/work/js-analysis/r/recovered/{digest}.js'
                ),
                'status': 'available',
                'available': True,
            }
        })
    )


def _fixture(tmp_path, *, context_ref='account-a'):
    ensure_project('p', root=tmp_path)
    JsIntakeStore(root=tmp_path).record_exec_result(
        project_id='p',
        run_id='r',
        pod_id='pod-' + context_ref,
        producer='katana',
        input_context_ref='ctx',
        exec_result=ExecResult(
            stdout=json.dumps({
                'request': {'endpoint': f'https://app.test/{context_ref}.js'},
                'response': {
                    'status_code': 200,
                    'headers': {
                        'Content-Type': 'application/javascript'
                    },
                },
            }),
            stderr='',
            returncode=0,
        ),
        auth_context_label='authenticated',
        auth_context_ref=context_ref,
    )
    reference = issue_js_intake_reference(
        'p',
        'r',
        context_ref=context_ref,
    )
    lead_id = JsIntakeReader(root=tmp_path).list(
        reference=reference,
        limit=10,
    )['leads'][0]['lead_id']
    parent = b'import("./child.js");\n'
    parent_digest = hashlib.sha256(parent).hexdigest()
    manifest = AcquisitionManifest(
        project_id='p',
        run_id='r',
        root=tmp_path,
        max_run_bytes=64 * 1024 * 1024,
    )
    assert manifest.reserve(
        lead_id=lead_id,
        record={'context_ref': context_ref},
        work_file_ref=f'/work/js-analysis/r/{parent_digest}.js',
        sha256=parent_digest,
        size=len(parent),
    )
    assert manifest.confirm(
        lead_id=lead_id,
        size=len(parent),
        sha256=parent_digest,
        work_file_ref=f'/work/js-analysis/r/{parent_digest}.js',
    ) == 'acquired'
    source = (
        "export async function loadItems(token) {\r\n"
        "  const value = token + ':suffix';\r\n"
        '  const response = await fetch("/api/items");\r\n'
        "  return response.json();\r\n"
        "}\r\n"
    ).encode()
    source_id = 'src_main_' + context_ref.replace('-', '_')
    _add_source(
        manifest,
        lead_id=lead_id,
        source_id=source_id,
        content=source,
        context_ref=context_ref,
    )
    access = CodeAccessService(root=tmp_path)
    triage = EvidenceTriage(root=tmp_path, access=access)
    selected = triage.select(
        reference=reference,
        selector={'type': 'source', 'id': source_id},
        question='How is the request value derived and sent?',
        priority='high',
    )
    read = access.prepare_read(
        reference=reference,
        selector={'type': 'source', 'id': source_id},
        source_bytes=source,
        window_bytes=128,
    )
    assert access.confirm_read(
        reference=reference,
        read_id=read['read_id'],
    )['delivery_status'] == 'delivered'
    return {
        'reference': reference,
        'access': access,
        'triage': triage,
        'selected': selected,
        'read': read,
        'source': source,
        'source_id': source_id,
        'manifest': manifest,
        'lead_id': lead_id,
    }


def _record(fixture, *, text='The token input is transformed before request.'):
    return {
        'question_ref': fixture['selected']['span_id'],
        'steps': [
            {
                'kind': 'transform',
                'text': text,
                'read_ids': [fixture['read']['read_id']],
            }
        ],
        'assumptions': [
            {
                'text': 'The server enforces the same rule.',
                'status': 'unverified',
                'read_ids': [],
            }
        ],
        'gaps': ['Server-side validation is not visible in client code.'],
    }


def test_schema_save_and_current_view_are_evidence_linked(tmp_path):
    fixture = _fixture(tmp_path)
    behavior = BehaviorReconstruction(
        root=tmp_path,
        access=fixture['access'],
        triage=fixture['triage'],
    )

    saved = behavior.save(
        reference=fixture['reference'],
        record=_record(fixture),
    )

    assert saved['reconstruction_level'] == 'reconstructed'
    assert saved['question_ref'] == fixture['selected']['span_id']
    assert saved['revision'] == 1
    assert saved['idempotent'] is False
    assert saved['steps'][0]['read_ids'] == [
        fixture['read']['read_id']
    ]
    listed = BehaviorReconstruction(
        root=tmp_path,
        access=fixture['access'],
        triage=fixture['triage'],
    ).list(reference=fixture['reference'])
    assert listed['total'] == 1
    assert listed['behaviors'][0]['behavior_id'] == saved['behavior_id']

    scope = __import__(
        'polymerhus.recon.js_intake.reader',
        fromlist=['resolve_js_intake_reference'],
    ).resolve_js_intake_reference(fixture['reference'])
    events = RunNotes(scope, root=tmp_path).typed_records(
        event_types={'behavior_save'}
    )
    assert len(events) == 1
    assert events[0]['event_type'] == 'behavior_save'
    assert events[0]['reconstruction_level'] == 'reconstructed'


def test_behavior_note_survives_retention_service_failure(tmp_path):
    fixture = _fixture(tmp_path)

    class FailingRetention:
        def retain_after_save(
            self,
            *,
            reference,
            behavior,
            dependencies,
            deadline=None,
        ):
            raise RuntimeError("postgres unavailable")

    behavior = BehaviorReconstruction(
        root=tmp_path,
        access=fixture['access'],
        triage=fixture['triage'],
        retention=FailingRetention(),
    )
    saved = behavior.save(
        reference=fixture['reference'],
        record=_record(fixture),
    )

    assert saved['behavior_id']
    assert saved['retention'] == {
        'status': 'gap',
        'retained_count': 0,
        'pending_count': 0,
        'gap_count': 1,
        'gaps': [{'reason': 'retention_service_failed'}],
        'transfer_requests': [],
    }
    scope = __import__(
        'polymerhus.recon.js_intake.reader',
        fromlist=['resolve_js_intake_reference'],
    ).resolve_js_intake_reference(fixture['reference'])
    events = RunNotes(scope, root=tmp_path).typed_records(
        event_types={'behavior_save'}
    )
    assert len(events) == 1
    assert events[0]['behavior_id'] == saved['behavior_id']


@pytest.mark.parametrize(
    'mutate,reason',
    [
        (
            lambda record: {**record, 'unexpected': 'field'},
            'invalid_behavior_record',
        ),
        (
            lambda record: {**record, 'steps': []},
            'invalid_behavior_record',
        ),
    ],
)
def test_schema_rejects_unknown_or_empty_explanations(
    tmp_path,
    mutate,
    reason,
):
    fixture = _fixture(tmp_path)
    behavior = BehaviorReconstruction(
        root=tmp_path,
        access=fixture['access'],
        triage=fixture['triage'],
    )
    with pytest.raises(BehaviorError) as exc:
        behavior.save(
            reference=fixture['reference'],
            record=mutate(_record(fixture)),
        )
    assert exc.value.reason == reason


def test_oversize_and_supported_assumption_without_read_are_rejected(
    tmp_path,
):
    fixture = _fixture(tmp_path)
    behavior = BehaviorReconstruction(
        root=tmp_path,
        access=fixture['access'],
        triage=fixture['triage'],
    )
    oversized = _record(fixture)
    oversized['gaps'] = ['x' * 500 for _ in range(8)]
    with pytest.raises(BehaviorError) as too_large:
        behavior.save(
            reference=fixture['reference'],
            record=oversized,
        )
    assert too_large.value.reason == 'behavior_record_too_large'

    unsupported = _record(fixture)
    unsupported['assumptions'][0] = {
        'text': 'A condition claimed as supported.',
        'status': 'supported',
        'read_ids': [],
    }
    with pytest.raises(BehaviorError) as invalid:
        behavior.save(
            reference=fixture['reference'],
            record=unsupported,
        )
    assert invalid.value.reason == 'invalid_behavior_record'


def test_structured_record_keeps_supported_detail_above_old_note_scale(tmp_path):
    fixture = _fixture(tmp_path)
    record = _record(fixture)
    record['gaps'] = ['Unknown runtime condition ' + str(i) + ': ' + 'x' * 340
                      for i in range(7)]
    size = len(json.dumps(record, sort_keys=True, separators=(',', ':')).encode())
    assert 2749 < size < 4096
    service = BehaviorReconstruction(root=tmp_path, access=fixture['access'],
                                     triage=fixture['triage'])
    saved = service.save(reference=fixture['reference'], record=record)
    assert len(saved['gaps']) == 7
    assert service.list(reference=fixture['reference'])['total'] == 1
    from types import SimpleNamespace
    from polymerhus.app.js_context.store import JsContextStore
    from polymerhus.app.js_context.tool import build_js_context_tool
    from polymerhus.recon.control.js_context_writer import JsContextWriter

    store = JsContextStore(root_dir=tmp_path)
    writer = JsContextWriter(root=tmp_path, store=store, access=fixture['access'],
                            retention=SimpleNamespace(status=lambda **_: {'links': []}))
    published = writer.publish(reference=fixture['reference'], origin='https://app.test',
                               analysis_coverage={'status': 'partial', 'gaps': ['fixture']})
    assert published['behavior_count'] == 1
    reader = build_js_context_tool('p', store)
    publication = reader.invoke({'command': 'list'})['publications'][0]
    page = reader.invoke({'command': 'read', 'context_id': publication['context_id'],
                          'selector': 'r', 'section': 'behaviors'})
    assert page['ok'] is True
    assert page['items'][0]['gaps'] == record['gaps']
    assert len(json.dumps(page, ensure_ascii=False).encode()) <= 16384


def test_oversize_feedback_reports_measured_size_without_echoing_content(tmp_path):
    fixture = _fixture(tmp_path)
    record = _record(fixture)
    record['gaps'] = ['private-marker-' + 'x' * 499 for _ in range(8)]
    size = len(json.dumps(record, sort_keys=True, separators=(',', ':')).encode())
    service = BehaviorReconstruction(root=tmp_path, access=fixture['access'],
                                     triage=fixture['triage'])
    with pytest.raises(BehaviorError) as rejected:
        service.save(reference=fixture['reference'], record=record)
    assert rejected.value.as_payload() == {
        'error': 'behavior_record_too_large', 'actual_bytes': size,
        'max_bytes': 4096, 'size_basis': 'canonical_json_bytes',
    }
    assert 'private-marker' not in json.dumps(rejected.value.as_payload())
    assert service.list(reference=fixture['reference'])['total'] == 0


def test_behavior_canonical_size_boundary_is_inclusive(tmp_path):
    fixture = _fixture(tmp_path)
    service = BehaviorReconstruction(root=tmp_path, access=fixture['access'],
                                     triage=fixture['triage'])
    record = _record(fixture)
    record['gaps'] = ['x' * 500 for _ in range(8)]
    excess = len(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()) - 4096
    assert 0 < excess < 500
    record['gaps'][-1] = record['gaps'][-1][excess:]
    assert len(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()) == 4096
    assert service.save(reference=fixture['reference'], record=record)['revision'] == 1
    record['gaps'][-1] += 'x'
    with pytest.raises(BehaviorError) as rejected:
        service.save(reference=fixture['reference'], record=record)
    assert rejected.value.details['actual_bytes'] == 4097
    assert service.list(reference=fixture['reference'])['behaviors'][0]['revision'] == 1


@pytest.mark.asyncio
async def test_behavior_feedback_is_structured_at_actual_rpc_boundary(tmp_path):
    from polymerhus.recon.js_specialist.bridge import build_router

    fixture = _fixture(tmp_path)
    app = FastAPI()
    app.include_router(build_router(root=tmp_path))
    record = _record(fixture)
    record['steps'][0]['read_ids'] = ['read_' + 'a' * 31]
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/recon/js-specialist/rpc',
            headers={'X-JS-Intake-Reference': fixture['reference']},
            json={'operation': 'behavior_save', 'record': record})
    assert response.status_code == 422
    assert response.json()['detail'] == {
        'error': 'behavior_read_not_delivered', 'invalid_count': 1,
        'invalid_fields': [{'field': 'steps[0].read_ids[0]', 'reason': 'not_delivered'}],
    }
    assert record['steps'][0]['read_ids'][0] not in json.dumps(response.json()['detail'])


def test_undelivered_foreign_and_wrong_question_refs_are_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    foreign = _fixture(tmp_path, context_ref='account-b')
    behavior = BehaviorReconstruction(
        root=tmp_path,
        access=fixture['access'],
        triage=fixture['triage'],
    )
    prepared = fixture['access'].prepare_read(
        reference=fixture['reference'],
        selector={'type': 'source', 'id': fixture['source_id']},
        source_bytes=fixture['source'],
    )
    record = _record(fixture)
    record['steps'][0]['read_ids'] = [prepared['read_id']]
    with pytest.raises(BehaviorError) as undelivered:
        behavior.save(reference=fixture['reference'], record=record)
    assert undelivered.value.reason == 'behavior_read_not_delivered'

    record = _record(fixture)
    record['steps'][0]['read_ids'] = [foreign['read']['read_id']]
    with pytest.raises(BehaviorError) as foreign_read:
        behavior.save(reference=fixture['reference'], record=record)
    assert foreign_read.value.reason == 'behavior_read_not_delivered'

    assert undelivered.value.details['invalid_fields'] == [
        {'field': 'steps[0].read_ids[0]', 'reason': 'not_delivered'}
    ]
    assert foreign_read.value.details == undelivered.value.details

    with pytest.raises(BehaviorError) as wrong_question:
        BehaviorReconstruction(
            root=tmp_path,
            access=foreign['access'],
            triage=foreign['triage'],
        ).save(
            reference=foreign['reference'],
            record={
                **_record(fixture),
                'question_ref': fixture['selected']['span_id'],
            },
        )
    assert wrong_question.value.reason == 'behavior_question_not_found'


def test_neighbouring_and_partial_delivered_reads_are_eligible(tmp_path):
    fixture = _fixture(tmp_path)
    child = b'export function child(value) { return value.trim(); }\n'
    _add_source(
        fixture['manifest'],
        lead_id=fixture['lead_id'],
        source_id='src_child',
        content=child,
    )
    child_read = fixture['access'].prepare_read(
        reference=fixture['reference'],
        selector={'type': 'source', 'id': 'src_child'},
        source_bytes=child,
        window_bytes=16,
    )
    fixture['access'].confirm_read(
        reference=fixture['reference'],
        read_id=child_read['read_id'],
    )
    record = _record(fixture)
    record['steps'][0]['read_ids'] = [
        fixture['read']['read_id'],
        child_read['read_id'],
    ]

    saved = BehaviorReconstruction(
        root=tmp_path,
        access=fixture['access'],
        triage=fixture['triage'],
    ).save(reference=fixture['reference'], record=record)

    assert set(saved['steps'][0]['read_ids']) == {
        fixture['read']['read_id'],
        child_read['read_id'],
    }


def test_historical_delivered_read_remains_referenceable_after_source_change(
    tmp_path,
):
    fixture = _fixture(tmp_path)
    fixture['manifest'].update(
        lambda value: value['recovery']['sources'][fixture['source_id']].update({
            'status': 'unavailable',
            'available': False,
            'content_sha256': 'f' * 64,
        })
    )

    saved = BehaviorReconstruction(
        root=tmp_path,
        access=fixture['access'],
        triage=fixture['triage'],
    ).save(reference=fixture['reference'], record=_record(fixture))

    assert saved['steps'][0]['read_ids'] == [
        fixture['read']['read_id']
    ]
    assert saved['reconstruction_level'] == 'reconstructed'


def test_local_only_behaviour_does_not_require_an_http_step(tmp_path):
    fixture = _fixture(tmp_path)
    record = _record(fixture)
    record['steps'] = [{
        'kind': 'effect',
        'text': 'The local DOM value is updated without a network request.',
        'read_ids': [fixture['read']['read_id']],
    }]
    saved = BehaviorReconstruction(
        root=tmp_path,
        access=fixture['access'],
        triage=fixture['triage'],
    ).save(reference=fixture['reference'], record=record)

    assert saved['steps'][0]['kind'] == 'effect'


def test_identical_retry_is_idempotent_and_changes_append_revision(tmp_path):
    fixture = _fixture(tmp_path)
    behavior = BehaviorReconstruction(
        root=tmp_path,
        access=fixture['access'],
        triage=fixture['triage'],
    )
    first = behavior.save(
        reference=fixture['reference'],
        record=_record(fixture),
    )
    repeated = behavior.save(
        reference=fixture['reference'],
        record=_record(fixture),
    )
    revised = behavior.save(
        reference=fixture['reference'],
        record=_record(fixture, text='A narrower supported explanation.'),
    )

    assert first['revision'] == 1
    assert repeated['behavior_id'] == first['behavior_id']
    assert repeated['revision'] == 1
    assert repeated['idempotent'] is True
    assert revised['behavior_id'] == first['behavior_id']
    assert revised['revision'] == 2
    current = behavior.list(reference=fixture['reference'])
    assert current['total'] == 1
    assert current['behaviors'][0]['revision'] == 2

    scope = __import__(
        'polymerhus.recon.js_intake.reader',
        fromlist=['resolve_js_intake_reference'],
    ).resolve_js_intake_reference(fixture['reference'])
    history = RunNotes(scope, root=tmp_path).typed_records(
        event_types={'behavior_save'}
    )
    assert [record['revision'] for record in history] == [1, 2]


def test_concurrent_identical_saves_append_once(tmp_path):
    fixture = _fixture(tmp_path)
    behavior = BehaviorReconstruction(
        root=tmp_path,
        access=fixture['access'],
        triage=fixture['triage'],
    )
    record = _record(fixture)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda _index: behavior.save(
                reference=fixture['reference'],
                record=record,
            ),
            range(2),
        ))

    assert {result['behavior_id'] for result in results} == {
        results[0]['behavior_id']
    }
    assert sum(result['idempotent'] for result in results) == 1
    scope = __import__(
        'polymerhus.recon.js_intake.reader',
        fromlist=['resolve_js_intake_reference'],
    ).resolve_js_intake_reference(fixture['reference'])
    history = RunNotes(scope, root=tmp_path).typed_records(
        event_types={'behavior_save'}
    )
    assert len(history) == 1


def test_concurrent_changed_saves_append_consecutive_revisions(tmp_path):
    fixture = _fixture(tmp_path)
    behavior = BehaviorReconstruction(
        root=tmp_path,
        access=fixture['access'],
        triage=fixture['triage'],
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda text: behavior.save(
                reference=fixture['reference'],
                record=_record(fixture, text=text),
            ),
            ('Concurrent explanation A.', 'Concurrent explanation B.'),
        ))

    assert sorted(result['revision'] for result in results) == [1, 2]
    scope = __import__(
        'polymerhus.recon.js_intake.reader',
        fromlist=['resolve_js_intake_reference'],
    ).resolve_js_intake_reference(fixture['reference'])
    history = RunNotes(scope, root=tmp_path).typed_records(
        event_types={'behavior_save'}
    )
    assert sorted(record['revision'] for record in history) == [1, 2]


def test_nested_text_is_redacted_without_losing_useful_names(tmp_path):
    fixture = _fixture(tmp_path)
    record = _record(
        fixture,
        text=(
            'Authorization: Bearer syntheticCredential123 at '
            'https://private.test/api/items?token=syntheticQueryValue; '
            'api_key: syntheticAssignedValue'
        ),
    )
    saved = BehaviorReconstruction(
        root=tmp_path,
        access=fixture['access'],
        triage=fixture['triage'],
    ).save(reference=fixture['reference'], record=record)

    text = saved['steps'][0]['text']
    assert 'Authorization:' in text
    assert '/api/items' in text
    assert 'api_key:' in text
    for secret in (
        'private.test',
        'syntheticCredential123',
        'syntheticQueryValue',
        'syntheticAssignedValue',
    ):
        assert secret not in text


def test_note_quota_and_context_isolation(tmp_path):
    fixture = _fixture(tmp_path)
    scope = __import__(
        'polymerhus.recon.js_intake.reader',
        fromlist=['resolve_js_intake_reference'],
    ).resolve_js_intake_reference(fixture['reference'])
    notes = RunNotes(scope, root=tmp_path)
    for index in range(255):
        result = notes.append_typed({
            'event_type': 'quota_filler',
            'text': f'filler-{index}',
        })
        assert result.get('error') is None

    behavior = BehaviorReconstruction(
        root=tmp_path,
        access=fixture['access'],
        triage=fixture['triage'],
    )
    with pytest.raises(BehaviorError) as quota:
        behavior.save(
            reference=fixture['reference'],
            record=_record(fixture),
        )
    assert quota.value.reason == 'notes_quota_exhausted'
    foreign = issue_js_intake_reference(
        'p',
        'r',
        context_ref='account-b',
    )
    assert behavior.list(reference=foreign)['behaviors'] == []


def test_prose_note_cannot_forge_behavior_event(tmp_path):
    fixture = _fixture(tmp_path)
    scope = __import__(
        'polymerhus.recon.js_intake.reader',
        fromlist=['resolve_js_intake_reference'],
    ).resolve_js_intake_reference(fixture['reference'])
    notes = RunNotes(scope, root=tmp_path)
    notes.tool().invoke({
        'command': 'write',
        'note': '{"event_type":"behavior_save","behavior_id":"forged"}',
    })

    assert notes.typed_records(event_types={'behavior_save'}) == []


def test_behavior_list_pagination_is_bound_to_current_view(tmp_path):
    fixture = _fixture(tmp_path)
    behavior = BehaviorReconstruction(
        root=tmp_path,
        access=fixture['access'],
        triage=fixture['triage'],
    )
    span_ids = []
    for index in range(3):
        selected = fixture['triage'].select(
            reference=fixture['reference'],
            selector={'type': 'source', 'id': fixture['source_id']},
            question=f'Question {index}?',
            priority='normal',
        )
        span_ids.append(selected['span_id'])
        behavior.save(
            reference=fixture['reference'],
            record={
                **_record(fixture),
                'question_ref': selected['span_id'],
            },
        )

    first = behavior.list(reference=fixture['reference'], limit=1)
    second = behavior.list(
        reference=fixture['reference'],
        limit=1,
        cursor=first['next_cursor'],
    )
    assert first['behaviors'][0]['behavior_id'] != (
        second['behaviors'][0]['behavior_id']
    )

    latest_span = span_ids[-1]
    behavior.save(
        reference=fixture['reference'],
        record={
            **_record(fixture, text='Changed after page one.'),
            'question_ref': latest_span,
        },
    )
    with pytest.raises(BehaviorError) as stale:
        behavior.list(
            reference=fixture['reference'],
            limit=1,
            cursor=first['next_cursor'],
        )
    assert stale.value.reason == 'invalid_behavior_cursor'


@pytest.mark.asyncio
async def test_behavior_rpc_route_saves_lists_and_rejects_bad_schema(
    tmp_path,
):
    from polymerhus.recon.js_specialist.bridge import build_router

    class Retention:
        def retain_after_save(
            self,
            *,
            reference,
            behavior,
            dependencies,
            deadline=None,
        ):
            return {
                'status': 'complete',
                'retained_count': 0,
                'pending_count': 0,
                'gap_count': 0,
                'gaps': [],
                'transfer_requests': [],
            }

        def status(
            self,
            *,
            reference,
            behavior_id,
            behavior_revision,
        ):
            return {
                'links': [],
                'retained_count': 0,
                'pending_count': 0,
                'gap_count': 0,
            }

    fixture = _fixture(tmp_path)
    app = FastAPI()
    app.include_router(build_router(root=tmp_path, retention=Retention()))
    headers = {'X-JS-Intake-Reference': fixture['reference']}
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url='http://test',
    ) as client:
        saved = await client.post(
            '/recon/js-specialist/rpc',
            headers=headers,
            json={
                'operation': 'behavior_save',
                'record': _record(fixture),
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()['revision'] == 1

        listed = await client.post(
            '/recon/js-specialist/rpc',
            headers=headers,
            json={'operation': 'behavior_list', 'limit': 5},
        )
        assert listed.status_code == 200, listed.text
        assert listed.json()['total'] == 1

        invalid = await client.post(
            '/recon/js-specialist/rpc',
            headers=headers,
            json={
                'operation': 'behavior_save',
                'record': {**_record(fixture), 'unknown': True},
            },
        )
        assert invalid.status_code == 422
        assert invalid.json()['detail'] == 'invalid_behavior_record'

        denied = await client.post(
            '/recon/js-specialist/rpc',
            headers={'X-JS-Intake-Reference': 'invalid'},
            json={'operation': 'behavior_list', 'limit': 5},
        )
        assert denied.status_code == 403


@pytest.mark.asyncio
async def test_behavior_rpc_response_is_bounded(tmp_path, monkeypatch):
    from polymerhus.recon.js_specialist import bridge as bridge_module

    monkeypatch.setattr(
        bridge_module.SpecialistBridge,
        'call',
        lambda self, reference, payload: {'behaviors': ['x' * 17000]},
    )
    app = FastAPI()
    app.include_router(bridge_module.build_router(root=tmp_path))
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url='http://test',
    ) as client:
        response = await client.post(
            '/recon/js-specialist/rpc',
            headers={
                'X-JS-Intake-Reference': issue_js_intake_reference(
                    'p',
                    'r',
                )
            },
            json={'operation': 'behavior_list', 'limit': 5},
        )
    assert response.status_code == 413
    assert response.json()['detail'] == 'behavior_response_limit'
