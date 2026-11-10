import asyncio
import inspect
import json

import pytest

from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_intake import JsIntakeStore


def inventory(
    tmp_path,
    *,
    count=1,
    completeness='complete',
    project_id='p',
    run_id='r',
):
    rows = [{'request': {'endpoint': f'https://app.test/{i}.js'}} for i in range(count)]
    JsIntakeStore(root=tmp_path).record_exec_result(project_id=project_id, run_id=run_id, pod_id='pod',
        producer='katana', input_context_ref='ctx', auth_context_label='anonymous', auth_context_ref=None,
        exec_result=ExecResult(stdout='\n'.join(json.dumps(r) for r in rows),stderr='',returncode=0))


def test_native_registry_order_and_retired_selection():
    from polymerhus.recon.control.jobs import JOBS, PHASES, validate_job_subset
    assert not {'jsluice','webpack_chunks'} & set(JOBS)
    order = {name:i for i,phase in enumerate(PHASES) for name in phase}
    assert order['katana'] < order['js_analysis'] < order['httpx_reprofile']
    assert JOBS['js_analysis'].consumption.source == 'js_intake'
    assert JOBS['js_analysis'].executor == 'js_specialist'
    for old in ('jsluice','webpack_chunks'):
        with pytest.raises(ValueError,match='js_analysis'):
            validate_job_subset(['httpx',old])
    with pytest.raises(ValueError,match='inventory|JSInventory'):
        validate_job_subset(['httpx','js_analysis'])
    validate_job_subset(['httpx','katana','js_analysis'])


def test_old_callback_parameters_are_removed():
    from polymerhus.recon.control.pipeline import run_pipeline
    assert not {'js_specialist_fn','with_js_specialist'} & set(inspect.signature(run_pipeline).parameters)


@pytest.mark.parametrize('count,missing,expected', [(0,False,'empty'),(0,True,'unavailable'),(15,False,'ready')])
def test_inventory_one_unit_empty_missing_and_many_leads(tmp_path,count,missing,expected):
    from polymerhus.recon.control.js_analysis_job import prepare_js_inventory
    if not missing:
        inventory(tmp_path,count=count)
    unit=prepare_js_inventory(project_id='p',run_id='r',root=tmp_path)
    assert unit['state']==expected
    assert unit['coverage']['lead_count']==count
    assert 'https://' not in json.dumps(unit)


def test_empty_pod_does_not_hide_missing_failed_producer(tmp_path):
    from polymerhus.recon.control.js_analysis_job import prepare_js_inventory
    inventory(tmp_path,count=0)
    unit=prepare_js_inventory(project_id='p',run_id='r',root=tmp_path,
        producer_outcomes={'katana':{'status':'success','pods':1},'ffuf':{'status':'degraded','pods':1}})
    assert unit['state']=='unavailable'
    assert 'producer_incomplete' in unit['coverage']['gaps']


def test_browser_only_keeps_native_job():
    from polymerhus.recon.control.authn_loop import prune_plan
    assert prune_plan([['httpx'],['katana','steel_crawl'],['js_analysis'],['arjun']], 'browser_only') == [['steel_crawl'],['js_analysis']]


def test_reference_renewal_keeps_no_replay_policy():
    from polymerhus.recon.js_intake.reader import issue_js_intake_reference, renew_js_intake_reference,resolve_js_intake_reference
    ref=issue_js_intake_reference('p','r',allow_http_replay=False)
    new=renew_js_intake_reference(ref,ttl_s=900)
    assert resolve_js_intake_reference(new).allow_http_replay is False


def test_common_run_job_invokes_one_specialist_and_only_exports_confirmed(tmp_path):
    from polymerhus.recon.control.js_analysis_job import prepare_js_inventory, run_js_analysis_job
    from polymerhus.recon.control.job_agent import run_job
    from polymerhus.recon.control.jobs import JOBS
    from polymerhus.recon.domain.types import AssetDelta
    inventory(tmp_path,count=20)
    unit=prepare_js_inventory(project_id='p',run_id='r',root=tmp_path)
    calls=[]
    async def specialist(**kw):
        calls.append('specialist')
        assert kw['run_id']=='r' and kw['deadline']>0
        return {'coverage':'partial','gaps':['bounded_selection']}
    def prepare(**kw):
        calls.append('prepare')
        return {'proposal_id':'a'*64,'coverage':{'status':'partial','gaps':[]},'behavior_records':[]}
    def submit(**kw):
        calls.append('curator')
        return {'status':'confirmed','assets_merged':1,'observations_merged':0,
                'merged_assets':[AssetDelta(type='BaseURL',identity={'url':'https://app.test'}).model_dump()], 'merged_observations':[]}
    async def executor(**kw):
        return await run_js_analysis_job(**kw,root=tmp_path,specialist_fn=specialist,prepare_fn=prepare,submit_fn=submit)
    result=asyncio.run(run_job(JOBS['js_analysis'],[unit],run_id='r',phase=6,extra={'project_id':'p'},specialist_executor=executor))
    assert calls==['specialist','prepare','curator']
    assert len(result)==1 and result[0].verdict=='success'
    assert result[0].assets_merged==len(result[0].assets)==1
    assert result[0].stats['coverage']['status']=='partial'


@pytest.mark.parametrize('resume',[False,True])
def test_uncertain_frozen_submission_retries_without_model(tmp_path,resume):
    from polymerhus.recon.control.js_analysis_job import prepare_js_inventory,run_js_analysis_job
    inventory(tmp_path)
    unit=prepare_js_inventory(project_id='p',run_id='r',root=tmp_path)
    calls=[]
    async def specialist(**kw):
        calls.append('model'); return {'coverage':'partial','gaps':[]}
    def prepare(**kw):
        calls.append('prepare'); return {'proposal_id':'b'*64,'coverage':{'status':'partial','gaps':[]}}
    def submit(**kw):
        calls.append(kw['proposal_id'])
        return {'status':'uncertain' if calls.count('b'*64)==1 else 'confirmed',
                'assets_merged':0,'observations_merged':0,'merged_assets':[],'merged_observations':[]}
    kw=dict(input_assets=[unit],run_id='r',phase=6,extra={'project_id':'p'},root=tmp_path,specialist_fn=specialist,prepare_fn=prepare,submit_fn=submit)
    first=asyncio.run(run_js_analysis_job(**kw))
    kw['extra']['js_resume_analysis']=resume
    second=asyncio.run(run_js_analysis_job(**kw))
    assert first[0].verdict=='failed' and second[0].verdict=='success'
    assert calls==['model','prepare','b'*64,'b'*64]


@pytest.mark.parametrize('count,missing,exports',[(0,False,0),(0,True,1)])
def test_zero_inventory_never_starts_model(tmp_path,count,missing,exports):
    from polymerhus.recon.control.js_analysis_job import prepare_js_inventory,run_js_analysis_job
    if not missing: inventory(tmp_path,count=count)
    unit=prepare_js_inventory(project_id='p',run_id='r',root=tmp_path)
    async def forbidden(**kw): raise AssertionError('no model')
    result=asyncio.run(run_js_analysis_job(input_assets=[unit],run_id='r',phase=6,extra={'project_id':'p'},root=tmp_path,specialist_fn=forbidden))
    assert len(result)==exports
    if exports: assert result[0].verdict=='failed'


def test_confirmed_retry_reuses_snapshot_without_another_model(tmp_path):
    from polymerhus.recon.control.js_analysis_job import prepare_js_inventory,run_js_analysis_job
    inventory(tmp_path)
    unit=prepare_js_inventory(project_id='p',run_id='r',root=tmp_path)
    calls=[]
    async def specialist(**kw): calls.append('model');return {'coverage':'partial','gaps':[]}
    def prepare(**kw): return {'proposal_id':'c'*64,'coverage':{'status':'partial','gaps':[]}}
    def submit(**kw): return {'status':'confirmed','assets_merged':0,'merged_assets':[]}
    kw=dict(input_assets=[unit],run_id='r',phase=6,extra={'project_id':'p'},root=tmp_path,specialist_fn=specialist,prepare_fn=prepare,submit_fn=submit)
    assert asyncio.run(run_js_analysis_job(**kw))[0].verdict=='success'
    assert asyncio.run(run_js_analysis_job(**kw))[0].verdict=='success'
    assert calls==['model']


def test_notification_failure_never_discards_confirmed_export(tmp_path):
    from functools import partial
    from polymerhus.recon.control.js_analysis_job import prepare_js_inventory,run_js_analysis_job
    from polymerhus.recon.control.job_agent import run_job
    from polymerhus.recon.control.jobs import JOBS
    inventory(tmp_path)
    unit=prepare_js_inventory(project_id='p',run_id='r',root=tmp_path)
    async def specialist(**kw): return {'coverage':'partial','gaps':[]}
    def prepare(**kw): return {'proposal_id':'a'*64,'coverage':{'status':'partial','gaps':[]}}
    def submit(**kw): return {'status':'confirmed','assets_merged':0,'merged_assets':[]}
    executor=partial(run_js_analysis_job,root=tmp_path,specialist_fn=specialist,prepare_fn=prepare,submit_fn=submit)
    def notify(*a): raise ValueError('expired original reference')
    result=asyncio.run(run_job(JOBS['js_analysis'],[unit],run_id='r',phase=6,extra={'project_id':'p'},specialist_executor=executor,notify_fn=notify))
    assert result[0].verdict=='success'


def test_timed_out_worker_keeps_scope_owned_until_actual_completion(tmp_path):
    import threading
    from polymerhus.recon.control.js_analysis_job import prepare_js_inventory,run_js_analysis_job
    from polymerhus.recon.js_specialist.agent import SpecialistLimits
    inventory(tmp_path)
    unit=prepare_js_inventory(project_id='p',run_id='r',root=tmp_path)
    release=threading.Event();finished=threading.Event();calls=[]
    async def specialist(**kw): return {'coverage':'partial','gaps':[]}
    def prepare(**kw):
        calls.append('prepare')
        try: release.wait(timeout=3)
        finally: finished.set()
        return {'proposal_id':'a'*64,'coverage':{'status':'partial','gaps':[]}}
    def submit(**kw): return {'status':'confirmed','assets_merged':0,'merged_assets':[]}
    kw=dict(input_assets=[unit],run_id='r',phase=6,extra={'project_id':'p'},root=tmp_path,specialist_fn=specialist,prepare_fn=prepare,submit_fn=submit)
    async def scenario():
        first=await run_js_analysis_job(**kw,limits=SpecialistLimits(wall_time_s=.1))
        second=await run_js_analysis_job(**kw)
        release.set()
        until=asyncio.get_running_loop().time()+1
        while not finished.is_set() and asyncio.get_running_loop().time()<until:
            await asyncio.sleep(.01)
        assert first[0].stats['gap']=='js_finalization_pending_timeout'
        assert second[0].error=='js_analysis_in_progress'
    try: asyncio.run(scenario())
    finally: release.set()
    assert calls==['prepare']


@pytest.mark.parametrize('old',['jsluice','webpack_chunks'])
def test_api_launch_rejects_retired_names_actionably(monkeypatch,old):
    from polymerhus.project_management import repository
    monkeypatch.setattr(repository.pg,'project_exists',lambda p:True)
    with pytest.raises(ValueError,match='js_analysis'):
        repository.validate_launch('p',['httpx',old])


def test_targeted_js_uses_authorized_inventory_and_ignores_url_targets(tmp_path,monkeypatch):
    from polymerhus.app import data_root
    from polymerhus.recon.control.js_analysis_job import prepare_js_inventory
    from polymerhus.recon.control.targeted import AnalyserReconRequest,ReconScope,request_targeted_recon
    from tests.recon.test_targeted import _FakeRegistry
    monkeypatch.setattr(data_root,'DATA_ROOT',tmp_path)
    inventory(tmp_path)
    unit=prepare_js_inventory(project_id='p',run_id='r',root=tmp_path)
    seen=[]
    async def run(job,inputs,**kw): seen.extend(inputs);return []
    result=asyncio.run(request_targeted_recon(AnalyserReconRequest(job='js_analysis',requester_id='test',
        scope=ReconScope(targets=['https://forbidden.invalid'],inventory_reference=unit['reference'])),
        'r','p',run_job=run,registry=_FakeRegistry()))
    assert result.status=='skipped'
    assert len(seen)==1 and seen[0]['resource']=='JSInventory'
    assert 'forbidden.invalid' not in json.dumps(seen)
