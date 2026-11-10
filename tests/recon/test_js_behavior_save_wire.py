"""Behavior-save feedback and transport remain usable without real infra."""
import asyncio
import io
import json
import shlex
from urllib.error import HTTPError

import pytest

from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_intake import cli
from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits


def test_cli_sends_a_compact_structured_record_above_old_note_size(monkeypatch):
    received = []

    def rpc(_url, _ref, payload, **_kwargs):
        received.append(payload['record'])
        return {'accepted_by_fixture': True}

    monkeypatch.setattr(cli, '_rpc', rpc)
    record = {'question_ref': 'span_test', 'gaps': ['x' * 350 for _ in range(8)]}
    result = cli._behavior_save('http://agent.invalid', 'synthetic',
                                {'record': json.dumps(record)})
    assert result == {'accepted_by_fixture': True}
    assert received == [record]


def test_cli_size_feedback_matches_backend_canonical_unicode_accounting():
    record = {'gaps': ['界' * 500, '界' * 200]}
    canonical_size = len(json.dumps(record, sort_keys=True, separators=(',', ':')).encode())
    assert canonical_size > 4096
    result = cli._behavior_save('http://agent.invalid', 'synthetic',
                                {'record': json.dumps(record, ensure_ascii=False)})
    assert result == {'error': 'behavior_record_too_large',
                      'actual_bytes': canonical_size, 'max_bytes': 4096,
                      'size_basis': 'canonical_json_bytes'}


def test_cli_preserves_structured_behavior_rejection_over_http(monkeypatch):
    detail = {'error': 'behavior_read_not_delivered', 'invalid_fields': [
        {'field': 'steps[2].read_ids[0]', 'reason': 'not_delivered'}]}

    def fail(request, **_kwargs):
        raise HTTPError(request.full_url, 422, 'invalid', {},
                        io.BytesIO(json.dumps({'detail': {**detail, 'source': 'must-not-escape'}}).encode()))

    monkeypatch.setattr(cli, 'urlopen', fail)
    assert cli._post_json('http://agent.invalid/rpc', 'synthetic', {}) == detail


@pytest.mark.parametrize('gaps', [["caller's " * 48 for _ in range(8)],
                                 ["'" * 480 for _ in range(8)]])
def test_runner_transports_larger_save_but_other_command_limits_stay(monkeypatch, gaps):
    from polymerhus.recon.js_specialist import agent

    async def immediate(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(agent.asyncio, 'to_thread', immediate)

    def execute(command, _session, _timeout):
        assert json.loads(shlex.split(command)[-1]) == record
        return ExecResult(stdout=json.dumps({'error': 'behavior_read_not_delivered',
                          'invalid_fields': [{'field': 'steps[0].read_ids[0]',
                                              'reason': 'not_delivered'}]}),
                          stderr='', returncode=1)

    prefix = ['cli', '--reference=synthetic']
    runner = BoundedExec(prefix=prefix, session_id='synthetic', exec_fn=execute,
                         limits=SpecialistLimits())
    record = {'question_ref': 'span_a', 'steps': [
        {'kind': 'call', 'text': 'A bounded supported call.',
         'read_ids': ['read_' + 'a' * 32]}],
        'assumptions': [], 'gaps': gaps}
    from polymerhus.recon.js_specialist.behavior import BehaviorSubmission
    BehaviorSubmission.model_validate(record)
    assert len(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()) <= 4096
    command = shlex.join([*prefix, 'behavior-save', '--record', json.dumps(record)])
    assert 4096 < len(command) < 32768

    async def check():
        result = await runner.run(command)
        assert result['result']['invalid_fields'][0]['field'] == 'steps[0].read_ids[0]'
        assert (await runner.run(shlex.join([*prefix, 'note', '--text', 'x' * 4100])))['error'] == 'command_rejected'

    asyncio.run(check())
    import time
    before = runner.attempts
    maintained = runner.maintenance_exec(command, deadline=time.monotonic() + 5)
    assert maintained['result']['invalid_fields'][0]['field'] == 'steps[0].read_ids[0]'
    assert runner.attempts == before


def test_raw_json_argument_is_bounded_before_parsing():
    result = cli._behavior_save('http://agent.invalid', 'synthetic',
                                {'record': 'x' * 8193})
    assert result == {'error': 'behavior_record_too_large',
                      'actual_bytes': 8193, 'max_bytes': 8192,
                      'size_basis': 'raw_json_input_bytes'}
