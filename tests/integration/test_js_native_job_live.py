"""Actual native route with isolated PG/Neo4j/Kali and service HTTP.

Gateway, Steel response producer, triage and the LLM session are scripted;
run_pipeline/run_job/dispatcher/Exec/CLI/scanner/stores/curator/feed are real.
External containers must be task-owned. No compose or target access is started.
"""
import asyncio
import json
import os
import threading
import time
import uuid
from types import SimpleNamespace

import httpx
import psycopg
import pytest
import uvicorn
from fastapi import FastAPI

from tests.conftest import neo4j_target


def test_native_crawl_to_common_job_real_graph_registry_and_feed(tmp_path,monkeypatch,record_property):
    assert os.environ.get('PH_JS_NATIVE_ISOLATED')=='1'
    from polymerhus.app import data_root
    from polymerhus.app.clients import pg,neo4j_client
    from polymerhus.analysis.feed import get_feed,drop_feed
    from polymerhus.recon.control.pipeline import run_pipeline
    from polymerhus.recon.control.job_agent import run_job
    from polymerhus.recon.control.jobs import JOBS
    from polymerhus.recon.control.js_analysis_job import prepare_js_inventory
    from polymerhus.recon.control.authn_loop import GatewayVerdict
    from polymerhus.recon.crawl import crawl_pod
    from polymerhus.recon.js_intake import JsIntakeReader
    from polymerhus.recon.js_intake.cli import parse_operation
    from polymerhus.recon.js_specialist.agent import build_js_specialist
    from polymerhus.recon.js_specialist.bridge import build_router as specialist_router
    from polymerhus.recon.js_acquisition.api import build_router as acquisition_router
    from polymerhus.recon.js_acquisition.service import AcquisitionService
    import shlex
    project='js-native-'+uuid.uuid4().hex;run='run-'+uuid.uuid4().hex
    monkeypatch.setattr(data_root,'DATA_ROOT',tmp_path)
    data_root.ensure_project(project,root=tmp_path)
    pg.ensure_recon_schema();pg.ensure_js_retention_schema()
    app=FastAPI();app.include_router(specialist_router(root=tmp_path));app.include_router(acquisition_router(service=AcquisitionService(root=tmp_path)))
    @app.get('/health')
    def health(): return {'ok':True}
    server=uvicorn.Server(uvicorn.Config(app,host='0.0.0.0',port=18083,access_log=False,log_level='warning'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    for _ in range(100):
        if server.started: break
        time.sleep(.05)
    assert server.started
    captures=[];sessions=[];commands=[];replay_attempts=[]
    def forbidden_replay(*a,**kw):
        replay_attempts.append(1)
        raise AssertionError('browser-only transport bypass')
    monkeypatch.setattr('polymerhus.recon.js_acquisition.service.httpx.Client',forbidden_replay)
    def crawl(target,*,scope,auth_cookies=None,steel_profile=None,capture_store=None,project_id='',run_id='',pod_id='',auth_context_ref=None):
        assert capture_store is not None and auth_context_ref=='fixture-account'
        assert target.startswith('https://')
        urls=[f'https://app.test/assets/main{i}.js' for i in range(3)]
        for seq,url in enumerate(urls):
            capture_store.record_bytes(project_id=project_id,run_id=run_id,pod_id=pod_id,crawl_id='fixture',
                auth_context_ref=auth_context_ref,exact_url=url,status=200,content_type='application/javascript',sequence=seq,
                body=b'fetch("https://app.test/api/items?view=private-fixture");\n')
            captures.append(url)
        return {'js_urls':urls,'pages':[{'url':target,'status':200}]}
    monkeypatch.setattr(crawl_pod,'default_run_crawl_fn',crawl)
    monkeypatch.setattr(crawl_pod,'default_triage_fn',lambda *a:[])
    monkeypatch.setattr('polymerhus.recon.control.pipeline.resolve_account',lambda *a,**k:None)
    class Gateway:
        async def run_gateway(self,**kw):
            return GatewayVerdict(outcome='authenticated',account='fixture-account',branch='browser_only',rationale='isolated fixture')
        async def stop(self): pass
    async def session(role,address,messages,**kw):
        sessions.append(address.thread_id)
        brief=json.loads(messages[0].content)
        prefix=brief['exec_prefix'];tool=kw['tools'][0]
        async def execute(suffix):
            command=prefix+' '+suffix;commands.append(suffix.split()[0])
            result=json.loads(await tool.ainvoke({'command':command}))
            assert not result.get('error'),result
            return result.get('result',result)
        await execute('context')
        page=await execute('inventory --limit 5')
        lead=page['leads'][0]['lead_id']
        acquired=await execute('acquire '+lead)
        assert acquired['status']=='acquired',acquired
        scan=await execute('scan '+lead)
        assert scan['status']=='complete',scan
        return SimpleNamespace(content='fixture complete',blackloop=False)
    # Native factory and role/limits remain production; inject only the session,
    # checkpoint/middleware and the local service address. Real Kali Exec default.
    real_factory=build_js_specialist
    monkeypatch.setattr('polymerhus.recon.js_specialist.agent.build_js_specialist',
        lambda **kw:real_factory(**kw,agent_url='http://172.17.0.1:18083',session_fn=session,
            checkpointer=object(),middleware=[],observe=False))
    try:
        asyncio.run(run_pipeline(project,run_id=run,job_subset=['httpx','steel_crawl','js_analysis'],
            load_settings=lambda p:{'target_seed':'*.app.test','streaming_analysis':True},
            registry=pg,orchestrator_factory=lambda r:Gateway(),with_analysis=False))
        with psycopg.connect(os.environ['POSTGRES_DSN']) as conn,conn.cursor() as cur:
            cur.execute('SELECT job,status,stats,started_at,finished_at FROM recon_jobs WHERE run_id=%s ORDER BY phase',(run,))
            rows=cur.fetchall()
        assert [r[0] for r in rows]==['steel_crawl','js_analysis']
        js=rows[-1];assert js[1]=='success' and js[3] and js[4]
        assert js[2]['executions']==1 and js[2]['pods']==0
        stats=js[2]['execution'][0]
        assert stats['specialist_invocations']==1 and len(sessions)==1 and len(captures)==3
        assert commands==['context','inventory','acquire','scan']
        assert replay_attempts==[]
        proposal=next((tmp_path/project/'recon/js_analysis'/run/'graph-proposals').rglob(stats['proposal_id']+'.json'))
        receipt=json.loads(proposal.with_name(stats['proposal_id']+'.receipt.json').read_text())['receipt']
        assert receipt['status']=='confirmed' and receipt['merged_assets']
        feed=get_feed(run);chunks=[]
        while not feed._queue.empty(): chunks.append(feed._queue.get_nowait())
        js_chunks=[c for c in chunks if c.job=='js_analysis' and not c.terminal]
        assert len(js_chunks)==1
        assert [a.model_dump() for a in js_chunks[0].assets]==receipt['merged_assets']
        nodes=neo4j_client.read('MATCH (n:Endpoint {project_id:$p,path:"/api/items"}) RETURN count(n) AS count',{'p':project})
        assert nodes[0]['count']==1
        unit=prepare_js_inventory(project_id=project,run_id=run,context_ref='fixture-account',allow_http_replay=False,scope_domains=['app.test'])
        replay=asyncio.run(run_job(JOBS['js_analysis'],[unit],run_id=run,phase=1,
            extra={'project_id':project,'scope_domain':'app.test'}))
        assert len(sessions)==1 and replay[0].assets==js_chunks[0].assets
        record_property('specialist_invocations',len(sessions));record_property('captured_leads',len(captures))
        record_property('confirmed_assets',len(receipt['merged_assets']));record_property('api_endpoints',nodes[0]['count'])
        record_property('forbidden_http_replays',len(replay_attempts))
        record_property('actual_common_run_job',True);record_property('real_kali_exec_operations',len(commands))
    finally:
        server.should_exit=True;thread.join(timeout=5)
        neo4j_client.merge('MATCH (n {project_id:$p}) DETACH DELETE n',{'p':project})
        with psycopg.connect(os.environ['POSTGRES_DSN']) as conn,conn.cursor() as cur:
            cur.execute('DELETE FROM recon_jobs WHERE run_id=%s',(run,));cur.execute('DELETE FROM recon_runs WHERE run_id=%s',(run,))
        drop_feed(run)
