"""Native common-route tests replace the retired opt-in callback tests."""
import asyncio
from functools import partial
from types import SimpleNamespace

import pytest

from tests.recon.test_pipeline import FakeRegistry
from tests.recon.test_js_native_job import inventory
from polymerhus.recon.control.pipeline import run_pipeline
from polymerhus.recon.control.job_agent import run_job,build_job_agent,default_preprocess_fn
from polymerhus.recon.control.js_analysis_job import prepare_js_inventory,run_js_analysis_job
from polymerhus.recon.domain.types import PodExport,AssetDelta


class Gateway:
    def __init__(self,branch='request'): self.branch=branch
    async def run_gateway(self,**kw):
        return SimpleNamespace(outcome='anonymous',account=None,branch=self.branch,replayability_resolved=False)
    async def stop(self): pass


@pytest.mark.parametrize('selected',[False,True])
def test_job_selection_owns_one_specialist_activation(tmp_path,monkeypatch,selected):
    calls=[]
    registry=FakeRegistry()
    def pod(pi,job,run_id,phase):
        calls.append(job.tool)
        if job.tool=='katana': inventory(tmp_path,count=25)
        return PodExport(input_asset={},verdict='success')
    async def specialist(**kw): calls.append('specialist');return {'coverage':'partial','gaps':[]}
    def proposal(**kw): return {'proposal_id':'a'*64,'coverage':{'status':'partial','gaps':[]}}
    accepted=AssetDelta(type='BaseURL',identity={'url':'https://app.test'})
    def submit(**kw): return {'status':'confirmed','assets_merged':1,'merged_assets':[accepted.model_dump()]}
    async def executor(**kw):
        return await run_js_analysis_job(**kw,root=tmp_path,specialist_fn=specialist,prepare_fn=proposal,submit_fn=submit)
    runner=partial(run_job,agent=build_job_agent(pod_invoke=pod,preprocess_fn=default_preprocess_fn),specialist_executor=executor)
    chunks=[]
    class Feed:
        mode='queued'
        async def push(self,chunk): chunks.append(chunk)
        async def signal_end(self): pass
    monkeypatch.setattr('polymerhus.analysis.feed.get_or_create_feed',lambda *a,**k:Feed())
    subset=['httpx','katana']+(['js_analysis'] if selected else [])
    asyncio.run(run_pipeline('p',run_id='r',job_subset=subset,run_job=runner,
        input_provider=partial(prepare_js_inventory,root=tmp_path),
        load_settings=lambda p:{'target_seed':'*.example.com','streaming_analysis':True},
        registry=registry,read_assets=lambda *a:[{'url':'https://app.test'}],
        orchestrator_factory=lambda r:Gateway(),with_analysis=False))
    assert calls.count('specialist')==int(selected)
    assert not {'jsluice','webpack_chunks'} & set(calls)
    js=[r for r in registry.upsert_job_calls if r['job']=='js_analysis' and r['stats'] and r['status']!='in_progress']
    assert len(js)==int(selected)
    if selected:
        assert js[0]['status']=='success' and js[0]['stats']['pods']==0
        assert js[0]['stats']['execution'][0]['specialist_invocations']==1
        assert [a for c in chunks if c.job=='js_analysis' for a in c.assets]==[accepted]
