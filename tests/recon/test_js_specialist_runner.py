import asyncio
import json
import shlex
import time
from types import SimpleNamespace

import pytest

from polymerhus.recon.js_intake import issue_js_intake_reference
from polymerhus.recon.domain.types import ExecResult


def test_dispatch_uses_shared_session_exec_only_and_renews_finite_scope(tmp_path):
    from polymerhus.recon.js_specialist.agent import build_js_specialist
    from polymerhus.app.llm.session_address import JsSpecialistSession
    from polymerhus.app.llm.providers import role_record

    calls = []
    async def session(role, address, messages, **kwargs):
        assert role == 'js_specialist'
        assert address == JsSpecialistSession('p', 'r', 'alice')
        assert [t.name for t in kwargs['tools']] == ['exec']
        assert kwargs['context']['skills'] == [
            'js-inventory-intake',
            'js-code-acquisition',
            'js-sourcemap-recovery',
            'js-bundle-structure',
            'js-evidence-triage',
            'js-behavior-reconstruction',
        ]
        assert kwargs['checkpointer'] is cp
        prefix = json.loads(messages[0].content)['exec_prefix']
        from polymerhus.recon.js_intake import resolve_js_intake_reference
        reference = shlex.split(prefix)[-1].split("=", 1)[1]
        assert resolve_js_intake_reference(reference).expires_at - time.monotonic() > 300
        for command in ['context', 'inventory --limit 1', 'notes']:
            result = await kwargs['tools'][0].ainvoke({'command': prefix + ' ' + command})
            assert json.loads(result)['returncode'] == 0
        return SimpleNamespace(content='invented complete', blackloop=False)

    def execute(command, session_id, timeout_s):
        calls.append((command, session_id, timeout_s))
        if ' inventory ' in command:
            out = {'leads': [{'lead_id': 'lead_a'}], 'next_cursor': 'remaining', 'coverage': {'coverage_gap': None}}
        else:
            out = {'notes': []}
        return ExecResult(stdout=json.dumps(out), stderr='', returncode=0)

    cp = object()
    ref = issue_js_intake_reference('p', 'r', context_ref='alice', scope_domains=['example.com'], ttl_s=1)
    dispatcher = build_js_specialist(root=tmp_path, session_fn=session, checkpointer=cp, middleware=[], exec_fn=execute)
    summary = asyncio.run(dispatcher(project_id='p', run_id='r', reference=ref, auth_context_label='authenticated', auth_context_ref='alice'))
    assert role_record('js_specialist').agent_mode == 'session'
    assert all(ref not in c[0] for c in calls)
    assert summary['next_cursor'] == 'remaining'
    assert summary['coverage'] == 'partial'
    assert 'inventory_pages_remaining' in summary['gaps']
    assert summary['budget']['attempts'] == summary['budget']['executions'] == 3
    assert list(tmp_path.glob('p/recon/js_analysis/r/specialist-*.json'))


@pytest.mark.parametrize(
    "renewed_reference",
    ["ordinary-synthetic-reference", "-synthetic-leading-hyphen"],
)
def test_native_prefix_keeps_opaque_reference_as_one_cli_argument(
    tmp_path,
    monkeypatch,
    capsys,
    renewed_reference,
):
    from polymerhus.recon.js_intake import cli
    from polymerhus.recon.js_specialist import agent as agent_module
    from polymerhus.recon.js_specialist.agent import build_js_specialist

    rpc_references = []

    def fake_rpc(agent_url, reference, payload, **kwargs):
        rpc_references.append(reference)
        return {"ok": True, "operation": payload["operation"]}

    monkeypatch.setattr(cli, "_rpc", fake_rpc)
    monkeypatch.setattr(
        agent_module,
        "issue_js_intake_reference",
        lambda *args, **kwargs: renewed_reference,
    )

    async def session(role, address, messages, **kwargs):
        prefix = json.loads(messages[0].content)["exec_prefix"]
        tokens = shlex.split(prefix)
        assert tokens[-1] == f"--reference={renewed_reference}"
        assert cli.main([*tokens[2:], "context"]) == 0
        output = json.loads(capsys.readouterr().out)
        assert output["ok"] is True
        return SimpleNamespace(content="done", blackloop=False)

    async def reconcile(**kwargs):
        return {
            "status": "no_work",
            "retry_attempts": 0,
            "maintenance_execs": 0,
            "gaps": [],
        }

    dispatch = build_js_specialist(
        root=tmp_path,
        session_fn=session,
        checkpointer=object(),
        middleware=[],
        exec_fn=lambda *args, **kwargs: ExecResult(
            stdout=json.dumps({"notes": []}),
            stderr="",
            returncode=0,
        ),
        retention_reconcile_fn=reconcile,
    )

    summary = asyncio.run(
        dispatch(
            project_id="p",
            run_id="r",
            reference=issue_js_intake_reference("p", "r"),
            auth_context_label="anonymous",
            auth_context_ref="",
        )
    )

    assert summary["coverage"] == "partial"
    assert rpc_references == [renewed_reference]


def test_dispatch_reconciles_retention_before_model_without_save_command(
    tmp_path,
    monkeypatch,
):
    from polymerhus.recon.js_specialist import agent as agent_module
    from polymerhus.recon.js_specialist.agent import build_js_specialist
    from polymerhus.recon.js_intake import resolve_js_intake_reference

    async def immediate(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(agent_module.asyncio, 'to_thread', immediate)
    calls = []
    reconcile_references = []

    async def reconcile(
        *,
        root,
        runner,
        reference,
        deadline,
        max_items,
    ):
        scope = resolve_js_intake_reference(reference)
        reconcile_references.append(reference)
        calls.append(('reconcile', scope.project_id, scope.run_id, scope.context_ref))
        return {
            'status': 'complete',
            'retry_attempts': 1,
            'maintenance_execs': 1,
            'gaps': [],
        }

    async def session(role, address, messages, **kwargs):
        calls.append(('session', role, address.project_id))
        return SimpleNamespace(content='done', blackloop=False)

    reference = issue_js_intake_reference(
        'p',
        'r',
        context_ref='alice',
    )
    dispatch = build_js_specialist(
        root=tmp_path,
        session_fn=session,
        checkpointer=object(),
        middleware=[],
        retention_reconcile_fn=reconcile,
    )
    summary = asyncio.run(dispatch(
        project_id='p',
        run_id='r',
        reference=reference,
        auth_context_label='authenticated',
        auth_context_ref='alice',
    ))

    assert calls == [
        ('reconcile', 'p', 'r', 'alice'),
        ('session', 'js_specialist', 'p'),
    ]
    assert reconcile_references[0] != reference
    assert summary['retention_reconcile']['status'] == 'complete'
    assert summary['budget']['maintenance_exec_attempts'] == 1
    assert summary['budget']['attempts'] == 0


def test_maintenance_exec_is_separate_from_model_budget():
    from polymerhus.recon.js_specialist.agent import (
        BoundedExec,
        SpecialistLimits,
    )

    commands = []

    def execute(command, session_id, timeout_s):
        commands.append((command, session_id, timeout_s))
        return ExecResult(
            stdout=json.dumps({
                'behavior_id': 'behavior_a',
                'revision': 1,
            }),
            stderr='',
            returncode=0,
        )

    runner = BoundedExec(
        prefix=['cli', '--reference', 'opaque'],
        session_id='s',
        exec_fn=execute,
        limits=SpecialistLimits(),
    )
    result = runner.maintenance_exec(
        'cli --reference opaque behavior-save --record {}',
        deadline=time.monotonic() + 5,
    )

    assert result['returncode'] == 0
    assert commands == [(
        'cli --reference opaque behavior-save --record {}',
        's',
        5,
    )]
    assert runner.attempts == 0
    assert runner.executions == 0
    assert runner.output_bytes == 0
    assert runner.maintenance_exec_attempts == 1
    assert runner.maintenance_output_bytes > 0


def test_maintenance_exec_returns_deadline_while_remote_work_is_uncertain():
    from polymerhus.recon.js_specialist.agent import (
        BoundedExec,
        SpecialistLimits,
    )

    def execute(command, session_id, timeout_s):
        time.sleep(0.25)
        return ExecResult(stdout='{}', stderr='', returncode=0)

    runner = BoundedExec(
        prefix=['cli', '--reference', 'opaque'],
        session_id='s',
        exec_fn=execute,
        limits=SpecialistLimits(),
    )
    started = time.monotonic()
    result = runner.maintenance_exec(
        'cli --reference opaque behavior-save --record {}',
        deadline=started + 0.05,
    )

    assert time.monotonic() - started < 0.15
    assert result == {
        'error': 'retention_reconcile_deadline',
        'remote_outcome_uncertain': True,
    }


def test_default_reconcile_is_noop_before_model_when_run_has_no_notes(
    tmp_path,
):
    from polymerhus.recon.js_specialist.agent import build_js_specialist

    calls = []

    async def session(role, address, messages, **kwargs):
        calls.append(role)
        return SimpleNamespace(content='done', blackloop=False)

    dispatch = build_js_specialist(
        root=tmp_path,
        session_fn=session,
        checkpointer=object(),
        middleware=[],
    )
    summary = asyncio.run(dispatch(
        project_id='p',
        run_id='r',
        reference=issue_js_intake_reference('p', 'r'),
        auth_context_label='anonymous',
        auth_context_ref='',
    ))

    assert calls == ['js_specialist']
    assert summary['retention_reconcile']['status'] == 'no_work'
    assert summary['retention_reconcile']['retry_attempts'] == 0
    assert summary['budget']['maintenance_exec_attempts'] == 0


def test_reconcile_failure_is_explicit_and_model_still_runs(
    tmp_path,
    monkeypatch,
):
    from polymerhus.recon.js_specialist import agent as agent_module
    from polymerhus.recon.js_specialist.agent import build_js_specialist

    async def immediate(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(agent_module.asyncio, 'to_thread', immediate)
    calls = []

    async def reconcile(**kwargs):
        raise RuntimeError('retention unavailable')

    async def session(role, address, messages, **kwargs):
        calls.append(role)
        return SimpleNamespace(content='done', blackloop=False)

    dispatch = build_js_specialist(
        root=tmp_path,
        session_fn=session,
        checkpointer=object(),
        middleware=[],
        retention_reconcile_fn=reconcile,
    )
    summary = asyncio.run(dispatch(
        project_id='p',
        run_id='r',
        reference=issue_js_intake_reference('p', 'r'),
        auth_context_label='anonymous',
        auth_context_ref='',
    ))

    assert calls == ['js_specialist']
    assert summary['retention_reconcile']['status'] == 'gap'
    assert summary['retention_reconcile']['gaps'] == [
        'retention_reconcile_failed'
    ]
    assert 'retention_reconcile_failed' in summary['gaps']


def test_specialist_prompt_continues_verified_acquisitions_into_recovery():
    from polymerhus.recon.js_specialist.agent import _load_prompt

    prompt = _load_prompt()
    lower = prompt.lower()

    assert 'js-sourcemap-recovery' in prompt
    assert 'with js-sourcemap-recovery' in prompt
    assert 'recover every acquired lead in the selected bounded batch' in lower
    assert 'even when the scan fails or is partial' in lower
    assert 'source recovery and behavioural analysis follow later' not in lower


def test_prompt_and_modular_skills_describe_one_continuous_workflow():
    from pathlib import Path
    from polymerhus.recon.js_specialist.agent import _load_prompt

    root = Path(__file__).resolve().parents[2]
    prompt = _load_prompt()
    inventory = (
        root / 'skills/internal/tools/js-inventory-intake/SKILL.md'
    ).read_text()
    acquisition = (
        root / 'skills/internal/tools/js-code-acquisition/SKILL.md'
    ).read_text()
    recovery = (
        root / 'skills/internal/tools/js-sourcemap-recovery/SKILL.md'
    ).read_text()
    structure = (
        root / 'skills/internal/tools/js-bundle-structure/SKILL.md'
    ).read_text()
    triage = (
        root / 'skills/internal/tools/js-evidence-triage/SKILL.md'
    ).read_text()
    priorities = (
        root
        / 'skills/internal/tools/js-evidence-triage/references/priorities.md'
    ).read_text()
    behavior = (
        root / 'skills/internal/tools/js-behavior-reconstruction/SKILL.md'
    ).read_text()
    behavior_flat = ' '.join(behavior.split())

    assert (
        'context/notes → early triage guidance → inventory selection → '
        'acquisition → baseline scan → recovery → bundle structure → '
        'per-question evidence triage → behaviour reconstruction/save → '
        'new priority → notes/summary'
    ) in prompt
    assert 'does not start the protected triage-analysis phase' in prompt
    assert 'Do not call `skill js-evidence-triage`' in prompt
    assert 'both context and notes have returned successfully' in prompt
    assert 'A search-code, read-code, triage-select or triage-update call' in prompt
    assert 'Load `js-code-acquisition`' in inventory
    assert '`triage-list`' in inventory
    assert 'early guidance' in inventory
    assert 'before acquisition' in inventory.lower()
    assert 'No scanning, source recovery' not in inventory
    assert 'whether baseline scan succeeds' in acquisition
    assert 'When original code is required' not in acquisition
    assert 'map_not_found' in acquisition
    assert 'next selected' in recovery
    assert 'Load `js-bundle-structure`' in acquisition
    assert 'regardless' in recovery.lower()
    assert 'structure-items' in structure
    assert 'acquire-reference' in structure
    assert 'search-code' in triage
    assert 'read-code' in triage
    assert 'triage-select' in triage
    assert 'triage-update' in triage
    assert 'inspected' in triage
    assert '## Early guidance' in triage
    assert 'Guidance and this initial list are planning' in triage
    assert 'Different labels or files alone do not make leads independent' in triage
    assert 'the new information needed' in triage
    assert 'behavior-save' in prompt
    assert 'js-behavior-reconstruction' in prompt
    assert 'behavior-save' in behavior
    assert 'Do not collapse an HTTP response' in behavior_flat
    assert 'runtime-observed' in behavior
    assert 'only one group' in priorities.lower()
    assert 'artificial variety' in priorities.lower()
    assert 'Firebase' in priorities
    assert 'API-key persistence' in priorities
    assert 'one mechanism' in priorities


def test_default_runner_can_execute_beyond_previous_attempt_limits():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits

    runner = BoundedExec(
        prefix=['python3', '/opt/polymerhus-js/cli.py', '--reference=good'],
        session_id='s',
        exec_fn=_generic_execute,
        limits=SpecialistLimits(),
    )

    async def exercise():
        for _ in range(60):
            result = await runner.run(runner.command_prefix + ' context')
            assert result.get('returncode') == 0, result

    asyncio.run(exercise())
    summary = runner.summary()
    assert summary['budget']['executions'] == 60
    assert summary['budget']['rejections'] == 0
    assert summary['budget']['limits']['max_attempts'] is None
    assert summary['budget']['limits']['triage_budget'] is None


def test_default_dispatcher_preserves_unlimited_attempts_in_session_and_summary(tmp_path):
    from polymerhus.recon.js_specialist.agent import build_js_specialist

    async def reconcile(**kwargs):
        return {'status': 'no_work', 'maintenance_execs': 0, 'gaps': []}

    async def session(role, address, messages, **kwargs):
        brief = json.loads(messages[0].content)
        assert brief['budgets']['max_attempts'] is None
        assert brief['budgets']['triage_budget'] is None
        for _ in range(60):
            result = await kwargs['tools'][0].ainvoke({
                'command': brief['exec_prefix'] + ' context',
            })
            assert json.loads(result)['returncode'] == 0
        return SimpleNamespace(content='done', blackloop=False)

    dispatch = build_js_specialist(
        root=tmp_path,
        session_fn=session,
        checkpointer=object(),
        middleware=[],
        exec_fn=_generic_execute,
        observe=False,
        retention_reconcile_fn=reconcile,
    )
    summary = asyncio.run(dispatch(
        project_id='p', run_id='r',
        reference=issue_js_intake_reference('p', 'r'),
        auth_context_ref='', auth_context_label='anonymous',
    ))
    assert summary['budget']['executions'] == 60
    assert summary['budget']['limits']['max_attempts'] is None
    assert 'specialist_session_failed' not in summary['gaps']


def test_unlimited_attempts_still_enforce_wall_time_and_output_limits():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits

    runner = BoundedExec(
        prefix=['python3', '/opt/polymerhus-js/cli.py', '--reference=good'],
        session_id='s',
        exec_fn=_generic_execute,
        limits=SpecialistLimits(),
    )

    async def exercise():
        runner.output_bytes = runner.limits.max_total_output_bytes
        result = await runner.run(runner.command_prefix + ' context')
        assert result['error'] == 'output_budget_exhausted'
        runner.output_bytes = 0
        runner.deadline = time.monotonic() - 1
        result = await runner.run(runner.command_prefix + ' context')
        assert result['error'] == 'time_budget_exhausted'

    asyncio.run(exercise())
    assert runner.executions == 0


def test_partitioned_attempt_policy_requires_explicit_finite_attempt_limit():
    from polymerhus.recon.js_specialist.agent import SpecialistLimits, TriageBudgetPolicy

    with pytest.raises(ValueError, match='finite max_attempts'):
        SpecialistLimits(max_attempts=None, triage_budget=TriageBudgetPolicy())


def test_runner_rejects_scope_changes_shell_and_hard_budgets():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits

    ran = []
    def execute(*args):
        ran.append(args)
        return ExecResult(stdout=json.dumps({'value': 'a' * 400}), stderr='', returncode=0)
    runner = BoundedExec(prefix=['python3', '/opt/polymerhus-js/cli.py', '--agent-url', 'http://agent:8080', '--reference', 'good'], session_id='s', exec_fn=execute, limits=SpecialistLimits(max_attempts=3, max_output_bytes=100))
    async def run():
        assert (await runner.run('curl http://elsewhere'))['error'] == 'command_rejected'
        assert (await runner.run(runner.command_prefix + ' context; cat /etc/passwd'))['error'] == 'command_rejected'
        assert (await runner.run(runner.command_prefix + ' context'))['error'] == 'output_budget_exhausted'
        assert (await runner.run(runner.command_prefix + ' context'))['error'] == 'attempt_budget_exhausted'
    asyncio.run(run())
    assert len(ran) == 1
    assert runner.attempts == 4
    assert runner.executions == 1
    assert runner.rejections == 3


@pytest.mark.parametrize('reference,context', [('invalid', ''), (None, 'alice'), (None, None)])
def test_invalid_reference_and_cross_context_never_run_model(tmp_path, reference, context):
    from polymerhus.recon.js_specialist.agent import build_js_specialist
    ref = reference or issue_js_intake_reference('p', 'r', context_ref='bob')
    async def session(*args, **kwargs):
        pytest.fail('must not run model')
    dispatch = build_js_specialist(root=tmp_path, session_fn=session, checkpointer=object(), middleware=[])
    summary = asyncio.run(dispatch(project_id='p', run_id='r', reference=ref, auth_context_ref=context, auth_context_label='authenticated' if context else 'anonymous'))
    assert summary['coverage'] == 'partial'
    assert summary['gaps'] == ['invalid_or_mismatched_reference']


def test_wall_clock_timeout_is_a_resumable_gap(tmp_path):
    from polymerhus.recon.js_specialist.agent import build_js_specialist, SpecialistLimits
    async def session(*args, **kwargs):
        await asyncio.sleep(1)
    dispatch = build_js_specialist(root=tmp_path, session_fn=session, checkpointer=object(), middleware=[], limits=SpecialistLimits(wall_time_s=.02))
    summary = asyncio.run(dispatch(project_id='p', run_id='r', reference=issue_js_intake_reference('p', 'r'), auth_context_ref='', auth_context_label='anonymous'))
    assert 'time_budget_exhausted' in summary['gaps']


def test_uncertain_and_failed_acquisitions_remain_pending():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits
    runner = BoundedExec(prefix=[], session_id='s', exec_fn=None, limits=SpecialistLimits())
    runner.seen_leads.update(['confirmed', 'uncertain', 'failed'])
    runner.outcomes = {'confirmed': {'status': 'acquired'}, 'uncertain': {'status': 'reconcile_required'}, 'failed': {'status': 'failed'}}
    runner.scan_outcomes = {'confirmed': {'status': 'complete'}}
    runner.recovery_outcomes = {'confirmed': {'status': 'complete'}}
    runner.structure_outcomes = {'confirmed': {'status': 'complete'}}
    assert runner.summary()['pending_lead_ids'] == ['failed', 'uncertain']


def test_output_limit_includes_tool_envelope_and_total_budget():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits
    payload = json.dumps({'value': 'x' * 70})
    runner = BoundedExec(prefix=['cli'], session_id='s',
        exec_fn=lambda *args: ExecResult(stdout=payload, stderr='', returncode=0),
        limits=SpecialistLimits(max_output_bytes=100))
    assert len(payload.encode()) < 100
    assert asyncio.run(runner.run('cli context'))['error'] == 'output_budget_exhausted'


def test_scan_commands_are_allowlisted_and_separate_from_acquisition_outcomes():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits
    from polymerhus.recon.js_intake.cli import parse_operation

    prefix = [
        'python3',
        '/opt/polymerhus-js/cli.py',
        '--agent-url',
        'http://agent:8080',
        '--reference',
        'opaque',
    ]
    assert parse_operation(['scan', 'lead_a'])['operation'] == 'scan'
    assert parse_operation(
        ['scan-results', 'lead_a', '--mode', 'urls', '--limit', '2']
    )['mode'] == 'urls'

    def execute(command, session_id, timeout_s):
        payload = {
            'lead_id': 'lead_a',
            'status': 'partial',
            'scan_key': 'scan-key',
            'modes': {
                'urls': {'status': 'complete', 'candidate_count': 2},
                'secrets': {'status': 'failed', 'candidate_count': 0},
            },
        }
        return ExecResult(
            stdout=json.dumps(payload),
            stderr='',
            returncode=1,
        )

    runner = BoundedExec(
        prefix=prefix,
        session_id='s',
        exec_fn=execute,
        limits=SpecialistLimits(max_batch=1),
    )

    async def run():
        assert (
            await runner.run(runner.command_prefix + ' scan lead_a')
        )['returncode'] == 1
        assert (
            await runner.run(runner.command_prefix + ' scan lead_b')
        )['error'] == 'batch_budget_exhausted'

    asyncio.run(run())
    summary = runner.summary()
    assert summary['scan_outcomes']['lead_a']['status'] == 'partial'
    assert summary['scan_outcomes']['lead_a']['modes']['urls']['status'] == 'complete'
    assert summary['outcomes'] == {}
    assert summary['budget']['scan_attempts'] == 1
    assert summary['gaps'].count('scan_partial_or_failed') == 1


def test_recovery_commands_are_allowlisted_and_recorded_separately():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits
    from polymerhus.recon.js_intake.cli import parse_operation

    prefix = [
        'python3',
        '/opt/polymerhus-js/cli.py',
        '--agent-url',
        'http://agent:8080',
        '--reference',
        'opaque',
    ]
    assert parse_operation(['recover', 'lead_a'])['operation'] == 'recover'
    assert parse_operation(['recovered-sources', 'lead_a'])['operation'] == (
        'recovered-sources'
    )
    assert parse_operation(['recovered-source', 'src_a'])['operation'] == (
        'recovered-source'
    )

    def execute(command, session_id, timeout_s):
        return ExecResult(
            stdout=json.dumps(
                {
                    'lead_id': 'lead_a',
                    'map_id': 'map_a',
                    'status': 'partial',
                    'source_count': 3,
                    'available': 2,
                    'transferred': 2,
                    'skipped_existing': 0,
                    'failures': ['transfer_failed'],
                    'gaps': ['source_count_limit'],
                }
            ),
            stderr='',
            returncode=1,
        )

    runner = BoundedExec(
        prefix=prefix,
        session_id='s',
        exec_fn=execute,
        limits=SpecialistLimits(max_batch=1),
    )

    async def run():
        assert (
            await runner.run(runner.command_prefix + ' recover lead_a')
        )['returncode'] == 1
        assert (
            await runner.run(runner.command_prefix + ' recover lead_b')
        )['error'] == 'batch_budget_exhausted'

    asyncio.run(run())
    summary = runner.summary()
    assert summary['recovery_outcomes']['lead_a']['map_id'] == 'map_a'
    assert summary['recovery_outcomes']['lead_a']['source_count'] == 3
    assert summary['outcomes'] == {}
    assert summary['scan_outcomes'] == {}
    assert summary['budget']['recovery_attempts'] == 1
    assert 'recovery_partial_or_failed' in summary['gaps']


def test_selected_batch_attempts_scan_then_recovery_for_each_lead():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits

    operations = []

    def execute(command, session_id, timeout_s):
        tokens = shlex.split(command)
        operation = tokens[3] if len(tokens) > 3 else ''
        lead_id = tokens[4] if len(tokens) > 4 else ''
        if operation == 'inventory':
            payload = {
                'leads': [{'lead_id': 'lead_a'}, {'lead_id': 'lead_b'}],
                'next_cursor': None,
                'coverage': {'coverage_gap': None},
            }
            return ExecResult(stdout=json.dumps(payload), stderr='', returncode=0)
        operations.append((operation, lead_id))
        if operation == 'lead':
            payload = {'lead_id': lead_id}
            return ExecResult(stdout=json.dumps(payload), stderr='', returncode=0)
        if operation == 'acquire':
            payload = {'lead_id': lead_id, 'status': 'acquired'}
            return ExecResult(stdout=json.dumps(payload), stderr='', returncode=0)
        if operation == 'scan' and lead_id == 'lead_a':
            payload = {'lead_id': lead_id, 'status': 'failed', 'modes': {}}
            return ExecResult(stdout=json.dumps(payload), stderr='', returncode=1)
        if operation == 'scan':
            payload = {'lead_id': lead_id, 'status': 'complete', 'modes': {}}
            return ExecResult(stdout=json.dumps(payload), stderr='', returncode=0)
        if operation == 'recover' and lead_id == 'lead_a':
            payload = {
                'lead_id': lead_id,
                'status': 'failed',
                'source_count': 0,
                'gaps': ['map_not_found'],
            }
            return ExecResult(stdout=json.dumps(payload), stderr='', returncode=1)
        if operation == 'recover':
            payload = {
                'lead_id': lead_id,
                'status': 'complete',
                'source_count': 2,
                'available': 2,
                'transferred': 2,
                'gaps': [],
            }
            return ExecResult(stdout=json.dumps(payload), stderr='', returncode=0)
        if operation == 'structure':
            payload = {
                'lead_id': lead_id,
                'status': 'complete' if lead_id == 'lead_b' else 'unsupported',
                'index_id': f'index_{lead_id}',
                'counts': {'import': 1 if lead_id == 'lead_b' else 0},
                'gaps': [] if lead_id == 'lead_b' else ['unsupported_format'],
            }
            return ExecResult(
                stdout=json.dumps(payload),
                stderr='',
                returncode=0,
            )
        payload = {'ok': True}
        return ExecResult(stdout=json.dumps(payload), stderr='', returncode=0)

    prefix = ['cli', '--reference', 'opaque']
    runner = BoundedExec(
        prefix=prefix,
        session_id='s',
        exec_fn=execute,
        limits=SpecialistLimits(max_batch=2),
    )

    async def run():
        assert (await runner.run(runner.command_prefix + ' inventory'))['returncode'] == 0
        for lead_id in ('lead_a', 'lead_b'):
            assert (await runner.run(
                runner.command_prefix + f' lead {lead_id}'
            ))['returncode'] == 0
            assert (await runner.run(
                runner.command_prefix + f' acquire {lead_id}'
            ))['returncode'] == 0
            await runner.run(runner.command_prefix + f' scan {lead_id}')
            await runner.run(runner.command_prefix + f' recover {lead_id}')
            await runner.run(runner.command_prefix + f' structure {lead_id}')

    asyncio.run(run())
    summary = runner.summary()
    assert operations == [
        ('lead', 'lead_a'),
        ('acquire', 'lead_a'),
        ('scan', 'lead_a'),
        ('recover', 'lead_a'),
        ('structure', 'lead_a'),
        ('lead', 'lead_b'),
        ('acquire', 'lead_b'),
        ('scan', 'lead_b'),
        ('recover', 'lead_b'),
        ('structure', 'lead_b'),
    ]
    assert summary['scan_outcomes']['lead_a']['status'] == 'failed'
    assert summary['recovery_outcomes']['lead_a']['gaps'] == ['map_not_found']
    assert summary['recovery_outcomes']['lead_b']['status'] == 'complete'
    assert summary['structure_outcomes']['lead_a']['status'] == 'unsupported'
    assert summary['structure_outcomes']['lead_b']['status'] == 'complete'
    assert summary['pending_lead_ids'] == []


def test_acquired_lead_is_pending_when_budget_blocks_recovery():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits

    def execute(command, session_id, timeout_s):
        tokens = shlex.split(command)
        operation = tokens[3] if len(tokens) > 3 else ''
        if operation == 'inventory':
            payload = {
                'leads': [{'lead_id': 'lead_a'}],
                'next_cursor': None,
                'coverage': {'coverage_gap': None},
            }
        elif operation == 'acquire':
            payload = {'lead_id': 'lead_a', 'status': 'acquired'}
        elif operation == 'scan':
            payload = {'lead_id': 'lead_a', 'status': 'failed', 'modes': {}}
        else:
            payload = {'ok': True}
        return ExecResult(
            stdout=json.dumps(payload),
            stderr='',
            returncode=1 if operation == 'scan' else 0,
        )

    runner = BoundedExec(
        prefix=['cli', '--reference', 'opaque'],
        session_id='s',
        exec_fn=execute,
        limits=SpecialistLimits(max_attempts=4, max_batch=2),
    )

    async def run():
        await runner.run(runner.command_prefix + ' inventory')
        await runner.run(runner.command_prefix + ' lead lead_a')
        await runner.run(runner.command_prefix + ' acquire lead_a')
        await runner.run(runner.command_prefix + ' scan lead_a')
        blocked = await runner.run(runner.command_prefix + ' recover lead_a')
        assert blocked['error'] == 'attempt_budget_exhausted'

    asyncio.run(run())
    summary = runner.summary()
    assert summary['pending_lead_ids'] == ['lead_a']
    assert 'attempt_budget_exhausted' in summary['gaps']
    assert 'recovery_not_attempted' in summary['gaps']
    assert summary['coverage'] == 'partial'


def test_free_selection_may_choose_fewer_than_max_batch():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits

    def execute(command, session_id, timeout_s):
        tokens = shlex.split(command)
        operation = tokens[3] if len(tokens) > 3 else ''
        lead_id = tokens[4] if len(tokens) > 4 else ''
        if operation == 'inventory':
            payload = {
                'leads': [
                    {'lead_id': 'lead_a'},
                    {'lead_id': 'lead_b'},
                    {'lead_id': 'lead_c'},
                ],
                'next_cursor': None,
                'coverage': {'coverage_gap': None},
            }
        elif operation == 'acquire':
            payload = {'lead_id': lead_id, 'status': 'acquired'}
        elif operation in {'lead', 'scan', 'recover', 'structure'}:
            payload = {'lead_id': lead_id, 'status': 'complete'}
        else:
            payload = {'ok': True}
        return ExecResult(stdout=json.dumps(payload), stderr='', returncode=0)

    runner = BoundedExec(
        prefix=['cli', '--reference', 'opaque'],
        session_id='s',
        exec_fn=execute,
        limits=SpecialistLimits(max_batch=3),
    )

    async def run():
        for command in (
            'inventory',
            'lead lead_a',
            'acquire lead_a',
            'scan lead_a',
            'recover lead_a',
            'structure lead_a',
        ):
            await runner.run(runner.command_prefix + ' ' + command)

    asyncio.run(run())
    summary = runner.summary()
    assert summary['pending_lead_ids'] == []
    assert 'unacquired_returned_leads' not in summary['gaps']
    assert 'scan_not_attempted' not in summary['gaps']
    assert 'recovery_not_attempted' not in summary['gaps']
    assert 'structure_not_attempted' not in summary['gaps']


def test_structure_attempt_follows_scan_and_map_failures():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits

    operations = []

    def execute(command, session_id, timeout_s):
        tokens = shlex.split(command)
        operation = tokens[3] if len(tokens) > 3 else ''
        lead_id = tokens[4] if len(tokens) > 4 else ''
        operations.append(operation)
        if operation == 'inventory':
            payload = {
                'leads': [{'lead_id': 'lead_a'}, {'lead_id': 'lead_b'}],
                'next_cursor': None,
                'coverage': {'coverage_gap': None},
            }
        elif operation == 'acquire':
            payload = {'lead_id': lead_id, 'status': 'acquired'}
        elif operation == 'scan':
            payload = {'lead_id': lead_id, 'status': 'failed', 'modes': {}}
        elif operation == 'recover':
            payload = {
                'lead_id': lead_id,
                'status': 'failed',
                'source_count': 0,
                'gaps': ['map_not_found'],
            }
        elif operation == 'structure':
            payload = {
                'lead_id': lead_id,
                'status': 'complete',
                'index_id': f'index_{lead_id}',
            }
        else:
            payload = {'lead_id': lead_id, 'status': 'complete'}
        return ExecResult(
            stdout=json.dumps(payload),
            stderr='',
            returncode=1 if operation in {'scan', 'recover'} else 0,
        )

    runner = BoundedExec(
        prefix=['cli', '--reference', 'opaque'],
        session_id='s',
        exec_fn=execute,
        limits=SpecialistLimits(max_batch=2),
    )

    async def run():
        await runner.run(runner.command_prefix + ' inventory')
        for lead_id in ('lead_a', 'lead_b'):
            for operation in ('acquire', 'scan', 'recover', 'structure'):
                await runner.run(
                    runner.command_prefix + f' {operation} {lead_id}'
                )

    asyncio.run(run())
    summary = runner.summary()
    assert summary['structure_outcomes']['lead_a']['status'] == 'complete'
    assert summary['structure_outcomes']['lead_b']['status'] == 'complete'
    assert summary['pending_lead_ids'] == []
    assert operations.count('structure') == 2


def test_acquired_lead_without_structure_attempt_is_pending():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits

    def execute(command, session_id, timeout_s):
        tokens = shlex.split(command)
        operation = tokens[3] if len(tokens) > 3 else ''
        if operation == 'inventory':
            payload = {
                'leads': [{'lead_id': 'lead_a'}],
                'next_cursor': None,
                'coverage': {'coverage_gap': None},
            }
        elif operation == 'acquire':
            payload = {'lead_id': 'lead_a', 'status': 'acquired'}
        else:
            payload = {'lead_id': 'lead_a', 'status': 'complete'}
        return ExecResult(stdout=json.dumps(payload), stderr='', returncode=0)

    runner = BoundedExec(
        prefix=['cli', '--reference', 'opaque'],
        session_id='s',
        exec_fn=execute,
        limits=SpecialistLimits(max_batch=1),
    )

    async def run():
        for command in (
            'inventory',
            'lead lead_a',
            'acquire lead_a',
            'scan lead_a',
            'recover lead_a',
        ):
            await runner.run(runner.command_prefix + ' ' + command)

    asyncio.run(run())
    summary = runner.summary()
    assert summary['pending_lead_ids'] == ['lead_a']
    assert 'structure_not_attempted' in summary['gaps']


def test_explicit_child_acquisition_is_recorded_without_recursive_scheduling():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits

    def execute(command, session_id, timeout_s):
        tokens = shlex.split(command)
        operation = tokens[3] if len(tokens) > 3 else ''
        payload = {
            'status': 'acquired',
            'lead_id': 'lead_child',
            'parent_item_id': 'sti_parent',
            'sha256': 'a' * 64,
            'size': 42,
        }
        return ExecResult(stdout=json.dumps(payload), stderr='', returncode=0)

    runner = BoundedExec(
        prefix=['cli', '--reference', 'opaque'],
        session_id='s',
        exec_fn=execute,
        limits=SpecialistLimits(max_batch=1),
    )

    async def run():
        return await runner.run(
            runner.command_prefix + ' acquire-reference sti_parent'
        )

    result = asyncio.run(run())
    summary = runner.summary()
    assert result['returncode'] == 0
    assert summary['child_outcomes']['sti_parent']['lead_id'] == 'lead_child'
    assert summary['pending_child_item_ids'] == []
    assert summary['pending_lead_ids'] == []


def test_read_is_confirmed_only_after_output_is_accepted():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits

    commands = []

    def execute(command, session_id, timeout_s):
        commands.append(command)
        if ' code-read-confirm ' in command:
            return ExecResult(
                stdout=json.dumps(
                    {"read_id": "read_a", "delivery_status": "delivered"}
                ),
                stderr='',
                returncode=0,
            )
        return ExecResult(
            stdout=json.dumps(
                {
                    "read_id": "read_a",
                    "code": "const visible = true;",
                    "delivery_status": "prepared",
                }
            ),
            stderr='',
            returncode=0,
        )

    runner = BoundedExec(
        prefix=['cli', '--reference', 'opaque'],
        session_id='s',
        exec_fn=execute,
        limits=SpecialistLimits(),
    )
    result = asyncio.run(
        runner.run(runner.command_prefix + ' read-code --source src_a')
    )

    assert result['result']['delivery_status'] == 'delivered'
    assert commands[-1].endswith(' code-read-confirm read_a')
    summary = runner.summary()
    assert summary['read_outcomes']['read_a']['delivery_status'] == 'delivered'
    assert summary['read_outcomes']['read_a']['selector'] == {
        'type': 'source',
        'id': 'src_a',
    }


def test_search_and_triage_outcomes_keep_pending_spans_explicit():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits

    def execute(command, session_id, timeout_s):
        tokens = shlex.split(command)
        operation = tokens[3]
        if operation == 'search-code':
            payload = {
                'search_id': 'search_a',
                'status': 'partial',
                'total_matches': 3,
                'examined_bytes': 100,
                'coverage_gap': 'examined_byte_limit',
                'matches': [],
                'next_cursor': 'next',
            }
        elif operation == 'triage-select':
            payload = {
                'span_id': 'span_a',
                'state': 'discovered',
                'idempotent': False,
            }
        elif operation == 'triage-list':
            payload = {
                'spans': [{'span_id': 'span_a', 'state': 'discovered'}],
                'pending_count': 1,
                'coverage': {
                    'discovered': 1,
                    'inspected': 0,
                    'deferred': 0,
                    'unresolved': 0,
                },
            }
        else:
            payload = {'ok': True}
        return ExecResult(
            stdout=json.dumps(payload),
            stderr='',
            returncode=1 if payload.get('status') == 'partial' else 0,
        )

    runner = BoundedExec(
        prefix=['cli', '--reference', 'opaque'],
        session_id='s',
        exec_fn=execute,
        limits=SpecialistLimits(),
    )

    async def run():
        await runner.run(
            runner.command_prefix
            + ' search-code lead_a --text alpha --limit 5'
        )
        await runner.run(
            runner.command_prefix
            + ' triage-select --source src_a --question request --priority high'
        )
        await runner.run(runner.command_prefix + ' triage-list --limit 5')

    asyncio.run(run())
    summary = runner.summary()
    assert summary['search_outcomes']['lead_a']['status'] == 'partial'
    assert summary['triage_outcomes']['span_a']['state'] == 'discovered'
    assert summary['triage_pending_count'] == 1
    assert 'triage_pending_spans' in summary['gaps']


def test_rejected_or_unconfirmed_read_never_becomes_delivered_evidence():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits

    commands = []

    def oversized(command, session_id, timeout_s):
        commands.append(command)
        return ExecResult(
            stdout=json.dumps(
                {
                    "read_id": "read_big",
                    'code': "x" * 20000,
                    "delivery_status": "prepared",
                }
            ),
            stderr='',
            returncode=0,
        )

    rejected = BoundedExec(
        prefix=['cli', '--reference', 'opaque'],
        session_id='s',
        exec_fn=oversized,
        limits=SpecialistLimits(max_output_bytes=1000),
    )
    result = asyncio.run(
        rejected.run(rejected.command_prefix + ' read-code --source src_a')
    )
    assert result['error'] == 'output_budget_exhausted'
    assert len(commands) == 1

    def lost_confirmation(command, session_id, timeout_s):
        if ' code-read-confirm ' in command:
            return ExecResult(stdout='{}', stderr='', returncode=1)
        return ExecResult(
            stdout=json.dumps(
                {
                    "read_id": "read_lost",
                    "code": "const visible = true;",
                    "delivery_status": "prepared",
                }
            ),
            stderr='',
            returncode=0,
        )

    unconfirmed = BoundedExec(
        prefix=['cli', '--reference', 'opaque'],
        session_id='s',
        exec_fn=lost_confirmation,
        limits=SpecialistLimits(),
    )
    result = asyncio.run(
        unconfirmed.run(
            unconfirmed.command_prefix + ' read-code --source src_a'
        )
    )
    assert result['result']['delivery_status'] == 'unconfirmed'
    assert 'read_delivery_unconfirmed' in unconfirmed.summary()['gaps']


def test_discovered_span_remains_pending_without_final_triage_list():
    from polymerhus.recon.js_specialist.agent import BoundedExec, SpecialistLimits

    def execute(command, session_id, timeout_s):
        return ExecResult(
            stdout=json.dumps(
                {
                    'span_id': 'span_pending',
                    'state': 'discovered',
                    'idempotent': False,
                }
            ),
            stderr='',
            returncode=0,
        )

    runner = BoundedExec(
        prefix=['cli', '--reference', 'opaque'],
        session_id='s',
        exec_fn=execute,
        limits=SpecialistLimits(),
    )
    asyncio.run(
        runner.run(
            runner.command_prefix
            + ' triage-select --source src_a --question request --priority high'
        )
    )
    summary = runner.summary()
    assert summary['triage_pending_count'] == 1
    assert 'triage_pending_spans' in summary['gaps']


def test_real_session_loop_and_checkpoint_resume_with_only_exec(tmp_path):
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
    from langgraph.checkpoint.memory import InMemorySaver
    from polymerhus.recon.js_specialist.agent import build_js_specialist
    from polymerhus.app.llm.session_address import JsSpecialistSession

    seen = []
    class Model(BaseChatModel):
        def bind_tools(self, tools, **kwargs):
            assert [t.name for t in tools] == ['exec']
            return self

        @property
        def _llm_type(self):
            return 'scripted-specialist'

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            seen.append(messages)
            if messages[-1].type == 'human':
                prefix = json.loads(messages[-1].content)['exec_prefix']
                answer = AIMessage(content='', tool_calls=[{'id': 'read-context', 'name': 'exec', 'args': {'command': prefix + ' context'}}])
            else:
                answer = AIMessage(content='Context checked; inventory pending.')
            return ChatResult(generations=[ChatGeneration(message=answer)])

    cp = InMemorySaver()
    errors = []
    async def checked_session(*args, **kwargs):
        from polymerhus.app.llm.session import arun_session_turn
        try:
            return await arun_session_turn(*args, **kwargs)
        except Exception as exc:
            errors.append(repr(exc))
            raise
    dispatch = build_js_specialist(root=tmp_path, session_fn=checked_session, checkpointer=cp, middleware=[], model_factory=lambda r: Model(), observe=False,
        exec_fn=lambda *args: ExecResult(stdout=json.dumps({'context': {'auth_context_ref': ''}}), stderr='', returncode=0))
    async def run():
        for _ in range(2):
            await dispatch(project_id='p', run_id='r', reference=issue_js_intake_reference('p', 'r'), auth_context_label='anonymous', auth_context_ref='')
    asyncio.run(run())
    assert errors == []
    assert len(seen[-1]) > len(seen[0])
    assert 'Skills available through Exec' in seen[0][0].content
    address = JsSpecialistSession('p', 'r', '')
    state = cp.get({'configurable': {'thread_id': address.thread_id}})
    assert len(state['channel_values']['messages']) >= 8


def _triage_budget_runner(execute, *, max_attempts=44):
    from polymerhus.recon.js_specialist.agent import (
        BoundedExec,
        SpecialistLimits,
        TriageBudgetPolicy,
    )

    return BoundedExec(
        prefix=['cli', '--reference', 'opaque'],
        session_id='s',
        exec_fn=execute,
        limits=SpecialistLimits(
            max_attempts=max_attempts,
            max_batch=1,
            triage_budget=TriageBudgetPolicy(),
        ),
    )


def _generic_triage_payload(command):
    tokens = shlex.split(command)
    operation = tokens[3] if len(tokens) > 3 else ''
    if operation == 'search-code':
        return {'status': 'complete', 'matches': [], 'examined_bytes': 1}
    if operation == 'triage-list':
        return {'spans': [], 'pending_count': 0}
    if operation == 'behavior-list':
        return {
            'behaviors': [],
            'total': 0,
            'next_cursor': None,
            'coverage': {
                'behavior_count': 0,
                'with_gaps': 0,
                'open_assumptions': 0,
            },
        }
    if operation == 'behavior-save':
        return {
            'behavior_id': 'behavior_saved',
            'revision': 1,
            'reconstruction_level': 'reconstructed',
            'question_ref': 'span_a',
            'record_sha256': 'a' * 64,
            'redaction_count': 0,
            'idempotent': False,
        }
    return {'ok': True}


def _generic_execute(command, session_id, timeout_s):
    return ExecResult(
        stdout=json.dumps(_generic_triage_payload(command)),
        stderr='',
        returncode=0,
    )


def _behavior_save_command(runner):
    return shlex.join([
        *runner.prefix,
        'behavior-save',
        '--record',
        '{"question_ref":"span_a","steps":[]}',
    ])


@pytest.mark.parametrize(
    ('preparation_count', 'expected_capacity'),
    [(21, 19), (24, 16)],
)
def test_guidance_and_preparation_share_pre_analysis_limit(
    preparation_count,
    expected_capacity,
):
    runner = _triage_budget_runner(_generic_execute)

    async def run():
        for _ in range(preparation_count):
            await runner.run(runner.command_prefix + ' context')
        await runner.run(
            runner.command_prefix + ' skill js-evidence-triage'
        )
        await runner.run(
            runner.command_prefix
            + ' reference js-evidence-triage commands'
        )
        await runner.run(
            runner.command_prefix
            + ' reference js-evidence-triage priorities'
        )
        await runner.run(runner.command_prefix + ' triage-list')
        await runner.run(
            runner.command_prefix
            + ' search-code lead_a --text request'
        )

    asyncio.run(run())
    budget = runner.summary()['budget']
    assert budget['preparation_attempts'] == preparation_count
    assert budget['triage_guidance_attempts'] == 4
    assert budget['pre_analysis_attempts'] == preparation_count + 4
    assert budget['pre_analysis_limit'] == 28
    assert budget['triage_analysis_started'] is True
    assert budget['triage_capacity'] == expected_capacity


def test_alternating_guidance_and_preparation_keep_same_allowance():
    runner = _triage_budget_runner(_generic_execute)
    guidance = (
        ' skill js-evidence-triage',
        ' reference js-evidence-triage commands',
        ' reference js-evidence-triage priorities',
        ' triage-list',
    )

    async def run():
        guidance_index = 0
        for index in range(1, 25):
            await runner.run(runner.command_prefix + ' context')
            if index % 6 == 0:
                await runner.run(
                    runner.command_prefix + guidance[guidance_index]
                )
                guidance_index += 1
        await runner.run(
            runner.command_prefix
            + ' search-code lead_a --text request'
        )

    asyncio.run(run())
    budget = runner.summary()['budget']
    assert budget['preparation_attempts'] == 24
    assert budget['triage_guidance_attempts'] == 4
    assert budget['pre_analysis_attempts'] == 28
    assert budget['pre_analysis_rejections'] == 0
    assert budget['triage_capacity'] == 16


def test_twenty_eight_preparation_plus_guidance_is_rejected_at_shared_limit():
    runner = _triage_budget_runner(_generic_execute)

    async def run():
        for _ in range(28):
            await runner.run(runner.command_prefix + ' context')
        rejected = []
        for command in (
            'skill js-evidence-triage',
            'reference js-evidence-triage commands',
            'reference js-evidence-triage priorities',
            'triage-list',
        ):
            rejected.append(
                await runner.run(runner.command_prefix + ' ' + command)
            )
        return rejected

    rejected = asyncio.run(run())
    summary = runner.summary()
    budget = summary['budget']
    assert all(
        result['error'] == 'pre_analysis_budget_exhausted'
        for result in rejected
    )
    assert budget['pre_analysis_attempts'] == 28
    assert budget['triage_guidance_attempts'] == 0
    assert budget['guidance_rejections'] == 4
    assert budget['pre_analysis_rejections'] == 4
    assert budget['attempts'] == 32
    assert budget['executions'] == 28


def test_triage_policy_returns_unused_preparation_attempts_to_triage():
    runner = _triage_budget_runner(_generic_execute)

    async def run():
        for _ in range(21):
            await runner.run(runner.command_prefix + ' context')
        assert (
            await runner.run(
                runner.command_prefix
                + ' reference js-evidence-triage commands'
            )
        )['returncode'] == 0
        await runner.run(runner.command_prefix + ' triage-list')
        for index in range(19):
            await runner.run(
                runner.command_prefix
                + f' search-code lead_a --text term{index}'
            )
        await runner.run(runner.command_prefix + ' triage-list')
        await runner.run(
            runner.command_prefix + ' note --text triage-summary'
        )

    asyncio.run(run())
    budget = runner.summary()['budget']
    assert budget['preparation_attempts'] == 21
    assert budget['triage_guidance_attempts'] == 2
    assert budget['pre_analysis_attempts'] == 23
    assert budget['pre_analysis_limit'] == 28
    assert budget['triage_capacity'] == 21
    assert budget['triage_phase_attempts'] == 21
    assert budget['triage_investigation_attempts'] == 19
    assert budget['triage_closure_attempts'] == 2
    assert budget['attempts'] == 44
    assert budget['triage_closure_guaranteed'] is True


def test_early_triage_guidance_does_not_start_analysis_or_preparation():
    runner = _triage_budget_runner(_generic_execute)

    async def run():
        await runner.run(runner.command_prefix + ' context')
        await runner.run(runner.command_prefix + ' notes')
        await runner.run(
            runner.command_prefix
            + ' reference js-evidence-triage commands'
        )
        await runner.run(
            runner.command_prefix + ' skill js-evidence-triage'
        )
        await runner.run(runner.command_prefix + ' triage-list')

    asyncio.run(run())
    budget = runner.summary()['budget']
    assert budget['attempts'] == 5
    assert budget['preparation_attempts'] == 2
    assert budget['triage_guidance_attempts'] == 3
    assert budget['pre_analysis_attempts'] == 5
    assert budget['triage_skill_loaded'] is True
    assert budget['triage_skill_loaded_after_context_notes'] is True
    assert budget['triage_references_loaded'] == ['commands']
    assert budget['triage_references_loaded_after_context_notes'] == [
        'commands'
    ]
    assert budget['triage_shortlist_consulted'] is True
    assert budget['triage_shortlist_consulted_after_context_notes'] is True
    assert budget['triage_guidance_order_ok'] is True
    assert budget['triage_analysis_started'] is False
    assert budget['triage_capacity'] is None


def test_early_guidance_preserves_later_preparation_accounting():
    runner = _triage_budget_runner(_generic_execute)

    async def run():
        await runner.run(runner.command_prefix + ' context')
        await runner.run(runner.command_prefix + ' notes')
        await runner.run(
            runner.command_prefix
            + ' reference js-evidence-triage priorities'
        )
        await runner.run(runner.command_prefix + ' triage-list')
        await runner.run(runner.command_prefix + ' acquire lead_a')
        await runner.run(runner.command_prefix + ' scan lead_a')

    asyncio.run(run())
    budget = runner.summary()['budget']
    assert budget['attempts'] == 6
    assert budget['triage_guidance_attempts'] == 2
    assert budget['preparation_attempts'] == 4
    assert budget['pre_analysis_attempts'] == 6
    assert budget['acquisition_attempts'] == 1
    assert budget['scan_attempts'] == 1
    assert budget['triage_guidance_order_ok'] is True
    assert budget['triage_analysis_started'] is False


def test_guidance_order_is_reported_from_structured_commands():
    runner = _triage_budget_runner(_generic_execute)

    async def run():
        await runner.run(
            runner.command_prefix + ' skill js-evidence-triage'
        )
        await runner.run(runner.command_prefix + ' triage-list')
        await runner.run(runner.command_prefix + ' context')
        await runner.run(runner.command_prefix + ' notes')

    asyncio.run(run())
    summary = runner.summary()
    assert summary['budget']['triage_skill_loaded'] is True
    assert (
        summary['budget']['triage_skill_loaded_after_context_notes']
        is False
    )
    assert summary['budget']['triage_shortlist_consulted'] is True
    assert (
        summary['budget'][
            'triage_shortlist_consulted_after_context_notes'
        ]
        is False
    )
    assert summary['budget']['triage_guidance_order_ok'] is False
    assert 'triage_guidance_not_after_context_notes' in summary['gaps']


def test_structured_analysis_operation_starts_triage_after_early_list():
    runner = _triage_budget_runner(_generic_execute)

    async def run():
        for _ in range(5):
            await runner.run(runner.command_prefix + ' context')
        await runner.run(
            runner.command_prefix + ' skill js-evidence-triage'
        )
        await runner.run(runner.command_prefix + ' triage-list')
        await runner.run(
            runner.command_prefix
            + ' search-code lead_a --text request'
        )

    asyncio.run(run())
    budget = runner.summary()['budget']
    assert budget['preparation_attempts'] == 5
    assert budget['triage_guidance_attempts'] == 2
    assert budget['pre_analysis_attempts'] == 7
    assert budget['triage_analysis_started'] is True
    assert budget['triage_transition_attempt'] == 8
    assert budget['triage_capacity'] == 37
    assert budget['triage_phase_attempts'] == 1


def test_early_list_resumes_existing_shortlist_without_analysis():
    def execute(command, session_id, timeout_s):
        if shlex.split(command)[3] == 'triage-list':
            payload = {
                'spans': [
                    {'span_id': 'span_existing', 'state': 'discovered'}
                ],
                'pending_count': 1,
                'next_cursor': 'resume',
            }
        else:
            payload = {'ok': True}
        return ExecResult(
            stdout=json.dumps(payload),
            stderr='',
            returncode=0,
        )

    runner = _triage_budget_runner(execute)

    async def run():
        await runner.run(runner.command_prefix + ' context')
        await runner.run(runner.command_prefix + ' notes')
        await runner.run(runner.command_prefix + ' triage-list --limit 1')

    asyncio.run(run())
    summary = runner.summary()
    budget = summary['budget']
    assert budget['triage_shortlist_consultations'] == 1
    assert budget['pre_analysis_attempts'] == 3
    assert budget['triage_shortlist_consulted'] is True
    assert budget['triage_analysis_started'] is False
    assert budget['triage_guidance_order_ok'] is True
    assert summary['triage_pending_count'] == 1
    assert 'triage_pending_spans' in summary['gaps']


def test_guidance_is_rejected_after_shared_pre_analysis_limit():
    runner = _triage_budget_runner(_generic_execute)

    async def run():
        for _ in range(28):
            assert (
                await runner.run(runner.command_prefix + ' context')
            )['returncode'] == 0
        rejected_guidance = await runner.run(
            runner.command_prefix
            + ' reference js-evidence-triage commands'
        )
        rejected_list = await runner.run(
            runner.command_prefix + ' triage-list'
        )
        assert (
            rejected_guidance['error']
            == 'pre_analysis_budget_exhausted'
        )
        assert rejected_list['error'] == 'pre_analysis_budget_exhausted'
        for index in range(12):
            await runner.run(
                runner.command_prefix
                + f' search-code lead_a --text term{index}'
            )
        await runner.run(runner.command_prefix + ' triage-list')
        await runner.run(
            runner.command_prefix + ' note --text triage-summary'
        )

    asyncio.run(run())
    budget = runner.summary()['budget']
    assert budget['preparation_attempts'] == 28
    assert budget['triage_guidance_attempts'] == 0
    assert budget['pre_analysis_attempts'] == 28
    assert budget['guidance_rejections'] == 2
    assert budget['pre_analysis_rejections'] == 2
    assert budget['triage_capacity'] == 14
    assert budget['triage_phase_attempts'] == 14
    assert budget['triage_investigation_attempts'] == 12
    assert budget['triage_closure_attempts'] == 2
    assert budget['triage_closure_guaranteed'] is False
    assert budget['preparation_rejections'] == 0
    assert budget['triage_minimum_reserve_met'] is False
    assert 'triage_minimum_reserve_unavailable' in runner.summary()['gaps']


def test_triage_policy_rejects_more_preparation_and_requests_triage():
    runner = _triage_budget_runner(_generic_execute)

    async def run():
        for _ in range(28):
            await runner.run(runner.command_prefix + ' context')
        return await runner.run(runner.command_prefix + ' notes')

    rejected = asyncio.run(run())
    budget = runner.summary()['budget']
    assert rejected['error'] == 'pre_analysis_budget_exhausted'
    assert rejected['triage_required'] is True
    assert budget['attempts'] == 29
    assert budget['executions'] == 28
    assert budget['preparation_attempts'] == 28
    assert budget['pre_analysis_attempts'] == 28
    assert budget['preparation_rejections'] == 1
    assert budget['pre_analysis_rejections'] == 1
    assert budget['triage_phase_started'] is False


def test_triage_policy_marks_missing_code_but_accepts_partial_verified_code():
    without_code = _triage_budget_runner(_generic_execute)
    with_code = _triage_budget_runner(_generic_execute)
    with_code.outcomes['lead_a'] = {'status': 'acquired'}
    with_code.seen_leads.add('lead_a')
    with_code.scan_outcomes['lead_a'] = {'status': 'failed'}
    with_code.recovery_outcomes['lead_a'] = {'status': 'partial'}
    with_code.recovery_outcomes['lead_a']['available'] = 1
    with_code.structure_outcomes['lead_a'] = {'status': 'partial'}

    async def run():
        for runner in (without_code, with_code):
            for _ in range(28):
                await runner.run(runner.command_prefix + ' context')
            blocked = await runner.run(
                runner.command_prefix + ' structure lead_a'
            )
            assert blocked['error'] == 'pre_analysis_budget_exhausted'
            await runner.run(runner.command_prefix + ' triage-list')
            await runner.run(
                runner.command_prefix
                + ' search-code lead_a --text request'
            )

    asyncio.run(run())
    no_code_summary = without_code.summary()
    code_summary = with_code.summary()
    assert no_code_summary['budget']['triage_eligible_lead_ids'] == []
    assert 'triage_without_verified_code' in no_code_summary['gaps']
    assert 'triage_minimum_reserve_unavailable' in no_code_summary['gaps']
    assert code_summary['budget']['triage_eligible_lead_ids'] == ['lead_a']
    assert 'triage_without_verified_code' not in code_summary['gaps']
    assert 'triage_minimum_reserve_unavailable' in code_summary['gaps']
    assert 'triage_closure_incomplete' in code_summary['gaps']
    assert code_summary['pending_lead_ids'] == ['lead_a']


def test_triage_policy_closure_slots_accept_list_and_note():
    runner = _triage_budget_runner(_generic_execute)

    async def run():
        for _ in range(21):
            await runner.run(runner.command_prefix + ' context')
        await runner.run(
            runner.command_prefix
            + ' reference js-evidence-triage commands'
        )
        await runner.run(runner.command_prefix + ' triage-list')
        for index in range(19):
            await runner.run(
                runner.command_prefix
                + f' search-code lead_a --text term{index}'
            )
        await runner.run(runner.command_prefix + ' triage-list')
        await runner.run(
            runner.command_prefix + ' note --text triage-summary'
        )

    asyncio.run(run())
    summary = runner.summary()
    assert summary['budget']['triage_closure_attempts'] == 2
    assert summary['budget']['closure_rejections'] == 0
    assert summary['budget']['triage_closure_guaranteed'] is True
    assert summary['budget']['triage_closure_complete'] is True


def test_triage_policy_rejected_work_can_expose_the_closure_reserve():
    runner = _triage_budget_runner(_generic_execute)

    async def run():
        for _ in range(21):
            await runner.run(runner.command_prefix + ' context')
        await runner.run(
            runner.command_prefix
            + ' reference js-evidence-triage commands'
        )
        await runner.run(runner.command_prefix + ' triage-list')
        for index in range(19):
            await runner.run(
                runner.command_prefix
                + f' search-code lead_a --text term{index}'
            )
        rejected = await runner.run(
            runner.command_prefix
            + ' search-code lead_a --text closure-work'
        )
        assert rejected['error'] == 'triage_closure_only'
        assert rejected['closure_operations'] == ['triage-list', 'note']

    asyncio.run(run())
    budget = runner.summary()['budget']
    assert budget['closure_rejections'] == 1
    assert budget['triage_capacity_remaining'] == 2
    assert budget['triage_closure_guaranteed'] is False


def test_failed_final_note_does_not_claim_triage_closure():
    def execute(command, session_id, timeout_s):
        operation = shlex.split(command)[3]
        if operation == 'note':
            payload = {'error': 'non_sensitive_ids_and_decisions_only'}
            return ExecResult(
                stdout=json.dumps(payload),
                stderr='',
                returncode=1,
            )
        return _generic_execute(command, session_id, timeout_s)

    runner = _triage_budget_runner(execute)
    runner.outcomes['lead_a'] = {'status': 'acquired'}
    runner.seen_leads.add('lead_a')
    runner.scan_outcomes['lead_a'] = {'status': 'failed'}
    runner.recovery_outcomes['lead_a'] = {'status': 'partial'}
    runner.structure_outcomes['lead_a'] = {'status': 'partial'}

    async def run():
        await runner.run(runner.command_prefix + ' context')
        await runner.run(runner.command_prefix + ' notes')
        await runner.run(
            runner.command_prefix + ' skill js-evidence-triage'
        )
        await runner.run(runner.command_prefix + ' triage-list')
        await runner.run(
            runner.command_prefix
            + ' search-code lead_a --text request'
        )
        await runner.run(runner.command_prefix + ' triage-list')
        await runner.run(runner.command_prefix + ' note --text summary')

    asyncio.run(run())
    summary = runner.summary()
    budget = summary['budget']
    assert budget['triage_closure_attempts'] == 2
    assert budget['triage_closure_success_operations'] == ['triage-list']
    assert budget['triage_closure_complete'] is False
    assert 'non_sensitive_ids_and_decisions_only' in summary['gaps']
    assert 'triage_closure_incomplete' in summary['gaps']
    assert summary['pending_lead_ids'] == ['lead_a']


def test_behavior_list_is_guidance_and_save_starts_analysis():
    runner = _triage_budget_runner(_generic_execute)

    async def run():
        await runner.run(runner.command_prefix + ' context')
        await runner.run(runner.command_prefix + ' notes')
        await runner.run(runner.command_prefix + ' behavior-list')
        await runner.run(runner.command_prefix + ' acquire lead_a')
        await runner.run(_behavior_save_command(runner))

    asyncio.run(run())
    summary = runner.summary()
    budget = summary['budget']
    assert budget['pre_analysis_attempts'] == 4
    assert budget['preparation_attempts'] == 3
    assert budget['triage_guidance_attempts'] == 1
    assert budget['behavior_list_attempts'] == 1
    assert budget['behavior_save_attempts'] == 1
    assert budget['triage_analysis_started'] is True
    assert budget['triage_transition_attempt'] == 5
    assert budget['triage_capacity'] == 40
    assert summary['saved_behavior_count'] == 1
    assert summary['triage_outcomes'] == {}


def test_uncertain_behavior_save_can_retry_idempotently_without_new_budget():
    calls = {'save': 0}

    def execute(command, session_id, timeout_s):
        operation = shlex.split(command)[3]
        if operation == 'behavior-save':
            calls['save'] += 1
            if calls['save'] == 1:
                raise OSError('response lost')
        return _generic_execute(command, session_id, timeout_s)

    runner = _triage_budget_runner(execute)

    async def run():
        await runner.run(runner.command_prefix + ' context')
        await runner.run(runner.command_prefix + ' notes')
        await runner.run(runner.command_prefix + ' behavior-list')
        first = await runner.run(_behavior_save_command(runner))
        second = await runner.run(_behavior_save_command(runner))
        return first, second

    first, second = asyncio.run(run())
    summary = runner.summary()
    assert first['error'] == 'exec_transport_failed'
    assert second['returncode'] == 0
    assert calls['save'] == 2
    assert summary['budget']['behavior_save_attempts'] == 2
    assert summary['saved_behavior_count'] == 1
    assert 'behavior_save_outcome_uncertain' in summary['gaps']
    assert summary['budget']['attempts'] == 5


def test_behavior_save_failure_is_explicit_and_not_counted_as_saved():
    def execute(command, session_id, timeout_s):
        if shlex.split(command)[3] == 'behavior-save':
            return ExecResult(
                stdout=json.dumps({
                    'error': 'behavior_record_too_large'
                }),
                stderr='',
                returncode=1,
            )
        return _generic_execute(command, session_id, timeout_s)

    runner = _triage_budget_runner(execute)

    async def run():
        await runner.run(runner.command_prefix + ' context')
        await runner.run(runner.command_prefix + ' behavior-list')
        return await runner.run(_behavior_save_command(runner))

    result = asyncio.run(run())
    summary = runner.summary()
    assert result['result']['error'] == 'behavior_record_too_large'
    assert summary['saved_behavior_count'] == 0
    assert 'behavior_record_too_large' in summary['gaps']


def test_behavior_save_retention_outcome_is_separate_and_visible(
    monkeypatch,
):
    from polymerhus.recon.js_specialist import agent as agent_module

    async def immediate(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(agent_module.asyncio, 'to_thread', immediate)

    def execute(command, session_id, timeout_s):
        if shlex.split(command)[3] == 'behavior-save':
            return ExecResult(
                stdout=json.dumps({
                    'behavior_id': 'behavior_saved',
                    'revision': 1,
                    'question_ref': 'span_a',
                    'retention': {
                        'status': 'pending',
                        'retained_count': 1,
                        'pending_count': 2,
                        'gap_count': 1,
                        'gaps': [{
                            'sha256': 'a' * 64,
                            'reason': 'retention_transfer_deadline',
                        }],
                    },
                }),
                stderr='',
                returncode=0,
            )
        return _generic_execute(command, session_id, timeout_s)

    runner = _triage_budget_runner(execute)

    async def run():
        await runner.run(runner.command_prefix + ' context')
        await runner.run(runner.command_prefix + ' behavior-list')
        return await runner.run(_behavior_save_command(runner))

    result = asyncio.run(run())
    summary = runner.summary()
    assert result['returncode'] == 0
    assert summary['saved_behavior_count'] == 1
    assert summary['retained_evidence_count'] == 1
    assert summary['retention_pending_count'] == 2
    assert summary['retention_gap_count'] == 1
    assert (
        summary['behavior_save_outcomes']['span_a']['retention']['status']
        == 'pending'
    )
    assert 'behavior_retention_pending' in summary['gaps']


def test_behavior_save_is_rejected_in_protected_closure_slots():
    runner = _triage_budget_runner(_generic_execute)

    async def run():
        for _ in range(21):
            await runner.run(runner.command_prefix + ' context')
        await runner.run(runner.command_prefix + ' triage-list')
        for index in range(20):
            await runner.run(
                runner.command_prefix
                + f' search-code lead_a --text term{index}'
            )
        return await runner.run(_behavior_save_command(runner))

    rejected = asyncio.run(run())
    assert rejected['error'] == 'triage_closure_only'
    assert rejected['closure_operations'] == ['triage-list', 'note']


def test_parallel_guidance_and_preparation_at_shared_threshold():
    runner = _triage_budget_runner(_generic_execute)

    async def run():
        for _ in range(27):
            await runner.run(runner.command_prefix + ' context')
        results = await asyncio.gather(
            runner.run(runner.command_prefix + ' context'),
            runner.run(
                runner.command_prefix + ' skill js-evidence-triage'
            ),
            runner.run(runner.command_prefix + ' triage-list'),
        )
        await runner.run(
            runner.command_prefix + ' search-code lead_a --text request'
        )
        return results

    results = asyncio.run(run())
    assert sum('error' not in result for result in results) == 1
    assert sum(
        result.get('error') == 'pre_analysis_budget_exhausted'
        for result in results
    ) == 2
    budget = runner.summary()['budget']
    assert budget['attempts'] == 31
    assert budget['executions'] == 29
    assert budget['pre_analysis_attempts'] == 28
    assert (
        budget['preparation_attempts']
        + budget['triage_guidance_attempts']
        == 28
    )
    assert budget['pre_analysis_rejections'] == 2
    assert budget['policy_rejections'] == 2
    assert budget['triage_transition_attempt'] == 31
    assert budget['triage_capacity'] == 14


def test_internal_read_confirmation_is_not_a_model_attempt():
    commands = []

    def execute(command, session_id, timeout_s):
        commands.append(command)
        if ' code-read-confirm ' in command:
            payload = {'read_id': 'read_a', 'delivery_status': 'delivered'}
        else:
            payload = {
                'read_id': 'read_a',
                'code': 'const visible = true;',
                'delivery_status': 'prepared',
            }
        return ExecResult(
            stdout=json.dumps(payload),
            stderr='',
            returncode=0,
        )

    runner = _triage_budget_runner(execute)
    runner.outcomes['lead_a'] = {'status': 'acquired'}

    async def run():
        await runner.run(
            runner.command_prefix
            + ' reference js-evidence-triage commands'
        )
        await runner.run(
            runner.command_prefix + ' read-code --source src_a'
        )

    asyncio.run(run())
    budget = runner.summary()['budget']
    assert commands[-1].endswith(' code-read-confirm read_a')
    assert budget['attempts'] == 2
    assert budget['executions'] == 2
    assert budget['triage_guidance_attempts'] == 1
    assert budget['pre_analysis_attempts'] == 1
    assert budget['triage_analysis_started'] is True
    assert budget['triage_capacity'] == 43
    assert budget['internal_confirmation_attempts'] == 1
    assert budget['internal_confirmations_succeeded'] == 1


def test_triage_policy_disabled_keeps_legacy_attempt_behavior():
    from polymerhus.recon.js_specialist.agent import (
        BoundedExec,
        SpecialistLimits,
    )

    runner = BoundedExec(
        prefix=['cli'],
        session_id='s',
        exec_fn=_generic_execute,
        limits=SpecialistLimits(max_attempts=44),
    )

    async def run():
        for _ in range(29):
            await runner.run('cli context')

    asyncio.run(run())
    budget = runner.summary()['budget']
    assert budget['triage_policy_enabled'] is False
    assert budget['pre_analysis_attempts'] == 0
    assert budget['pre_analysis_limit'] is None
    assert runner.attempts == 29


def test_build_js_specialist_passes_opt_in_policy_to_brief_and_summary(
    tmp_path,
):
    from polymerhus.recon.js_specialist.agent import (
        SpecialistLimits,
        TriageBudgetPolicy,
        build_js_specialist,
    )

    seen = []

    async def session(role, address, messages, **kwargs):
        seen.append(json.loads(messages[0].content))
        return SimpleNamespace(content="finished", blackloop=False)

    limits = SpecialistLimits(
        max_attempts=44,
        max_batch=1,
        triage_budget=TriageBudgetPolicy(),
    )
    dispatch = build_js_specialist(
        root=tmp_path,
        session_fn=session,
        checkpointer=object(),
        middleware=[],
        limits=limits,
    )
    summary = asyncio.run(
        dispatch(
            project_id='p',
            run_id='r',
            reference=issue_js_intake_reference('p', 'r'),
            auth_context_label='anonymous',
            auth_context_ref='',
        )
    )
    assert seen[0]['budgets']['triage_budget'] == {
        'pre_triage_attempt_limit': 28,
        'minimum_triage_attempts': 16,
        'triage_closure_attempts': 2,
    }
    assert summary['budget']['triage_policy_enabled'] is True
    assert summary['budget']['limits']['max_attempts'] == 44
