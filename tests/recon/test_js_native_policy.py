import hashlib
import json

import pytest
from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_intake import JsIntakeStore,JsIntakeReader
from polymerhus.recon.js_intake.reader import issue_js_intake_reference
from polymerhus.recon.js_acquisition.service import AcquisitionService,AcquisitionError
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_acquisition.capture import SteelCaptureStore


def fixture(tmp_path,producer='katana'):
    store=JsIntakeStore(root=tmp_path)
    if producer=='katana':
        store.record_exec_result(project_id='p',run_id='r',pod_id='pod',producer=producer,input_context_ref='ctx',
            auth_context_label='anonymous',auth_context_ref=None,
            exec_result=ExecResult(stdout=json.dumps({'request':{'endpoint':'https://app.test/a.js'}}),stderr='',returncode=0))
    else:
        store.record_manifest(project_id='p',run_id='r',pod_id='pod',producer='steel_crawl',input_context_ref='ctx',
            manifest={'js_urls':['https://app.test/a.js']},terminal_result='success',output_completeness='complete',
            auth_context_label='anonymous',auth_context_ref=None)
    ref=issue_js_intake_reference('p','r',allow_http_replay=False)
    lead=JsIntakeReader(root=tmp_path).list(reference=ref)['leads'][0]['lead_id']
    return ref,lead


@pytest.mark.parametrize('operation',['ordinary','child','map','source'])
def test_browser_only_broker_never_replays_http(tmp_path,monkeypatch,operation):
    ref,lead=fixture(tmp_path)
    calls=[]
    def forbidden(*a,**k):
        calls.append(1);raise AssertionError('forbidden replay')
    monkeypatch.setattr('polymerhus.recon.js_acquisition.service.httpx.Client',forbidden)
    service=AcquisitionService(root=tmp_path)
    m=AcquisitionManifest(project_id='p',run_id='r',root=tmp_path,max_run_bytes=1024)
    digest=hashlib.sha256(b'a').hexdigest()
    m.reserve(lead_id=lead,record={'context_ref':''},work_file_ref=f'/work/js-analysis/r/{digest}.js',sha256=digest,size=1)
    m.confirm(lead_id=lead,sha256=digest,size=1,work_file_ref=f'/work/js-analysis/r/{digest}.js')
    with pytest.raises(AcquisitionError,match='browser_only'):
        if operation in {'ordinary','child'}: service.fetch(reference=ref,lead_id=lead)
        elif operation=='map': service.fetch_map(reference=ref,lead_id=lead,map_url='https://app.test/a.map',max_bytes=1024)
        else: service.fetch_missing_source(reference=ref,lead_id=lead,source_url='https://app.test/src.js',max_bytes=1024)
    assert calls==[]


def test_capture_bytes_are_usable_and_release_protects_shared_pending_bytes(tmp_path,monkeypatch):
    ref,lead=fixture(tmp_path,'steel_crawl')
    captures=SteelCaptureStore(root=tmp_path)
    kw=dict(project_id='p',run_id='r',pod_id='pod',crawl_id='crawl',auth_context_ref=None,
            exact_url='https://app.test/a.js',status=200,content_type='application/javascript')
    body=b'export const captured = true;'
    captures.record_bytes(**kw,sequence=1,body=body)
    captures.link_leads(project_id='p',run_id='r',pod_id='pod',auth_context_ref=None,exact_url=kw['exact_url'],lead_ids=[lead,'pending-lead'])
    monkeypatch.setattr('polymerhus.recon.js_acquisition.service.httpx.Client',lambda *a,**k: pytest.fail('HTTP forbidden'))
    service=AcquisitionService(root=tmp_path,capture_store=captures)
    result=service.fetch(reference=ref,lead_id=lead)
    assert result.body==body
    service.confirm(reference=ref,lead_id=lead,size=len(body),sha256=hashlib.sha256(body).hexdigest(),work_file_ref=result.work_file_ref)
    assert captures.release_consumed(project_id='p',run_id='r')['deleted_blobs']==0
    captures.release_lead(project_id='p',run_id='r',pod_id='pod',lead_id='pending-lead')
    assert captures.release_consumed(project_id='p',run_id='r')['deleted_blobs']==1
    assert captures.release_consumed(project_id='p',run_id='r')['deleted_blobs']==0
