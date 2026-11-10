import hashlib
import json
from pathlib import Path

import pytest
from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_intake import JsIntakeStore,JsIntakeReader
from polymerhus.recon.js_intake.reader import issue_js_intake_reference,renew_js_intake_reference
from polymerhus.recon.js_acquisition.service import AcquisitionService,AcquisitionError
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_acquisition.capture import SteelCaptureStore
from polymerhus.recon.js_acquisition.structure import ParsedStructure
from polymerhus.recon.js_acquisition.structure_service import StructureService,_CURRENT_PARSER


def setup(root):
    source=b'import("./child.js");'
    JsIntakeStore(root=root).record_exec_result(project_id='p',run_id='r',pod_id='pod',producer='katana',input_context_ref='ctx',auth_context_label='authenticated',auth_context_ref='alice',exec_result=ExecResult(stdout=json.dumps({'request':{'endpoint':'https://app.test/a.js'}}),stderr='',returncode=0))
    ref=issue_js_intake_reference('p','r',context_ref='alice',scope_domains=['app.test'],allow_http_replay=False)
    lead=JsIntakeReader(root=root).list(reference=ref)['leads'][0]['lead_id']
    digest=hashlib.sha256(source).hexdigest()
    m=AcquisitionManifest(project_id='p',run_id='r',root=root,max_run_bytes=1024)
    work=f'/work/js-analysis/r/{digest}.js'
    m.reserve(lead_id=lead,record={'context_ref':'alice','final_url':'https://app.test/a.js'},work_file_ref=work,sha256=digest,size=len(source))
    m.confirm(lead_id=lead,work_file_ref=work,sha256=digest,size=len(source))
    return ref,lead,source


def test_actual_structure_child_register_and_renewed_broker_no_http(tmp_path,monkeypatch):
    ref,lead,source=setup(tmp_path)
    calls=[]
    def forbidden(*a,**k): calls.append('http');raise AssertionError('HTTP replay forbidden')
    monkeypatch.setattr('polymerhus.recon.js_acquisition.service.httpx.Client',forbidden)
    def parser(body):
        return ParsedStructure(format='esm',status='complete',items=({'kind':'import','subtype':'dynamic','resolved':True,'specifier':'./child.js','occurrence_key':'import:0','start_byte':7,'end_byte':17},),gaps=(),parse_errors=(),parser=_CURRENT_PARSER,source_sha256=hashlib.sha256(body).hexdigest(),source_size=len(body),index_bytes=1,parser_memory_bytes=1)
    structure=StructureService(root=tmp_path)
    structure.structure_from_source(reference=ref,lead_id=lead,source_bytes=source)
    item=structure.list_items(reference=ref,lead_id=lead,kind='import')['items'][0]
    child=structure.register_reference(reference=ref,item_id=item['item_id'])
    assert child['status']=='registered'
    private,_=JsIntakeReader(root=tmp_path).get_private(reference=ref,lead_id=child['lead_id'])
    assert private['source_tool']=='code_derived'
    assert private['exact_url']=='https://app.test/child.js'
    renewed=renew_js_intake_reference(ref,ttl_s=900)
    broker=AcquisitionService(root=tmp_path)
    for target in (lead,child['lead_id']):
        with pytest.raises(AcquisitionError,match='browser_only'): broker.fetch(reference=renewed,lead_id=target)
    with pytest.raises(AcquisitionError,match='browser_only'): broker.fetch_map(reference=renewed,lead_id=lead,map_url='https://app.test/a.map',max_bytes=1024)
    with pytest.raises(AcquisitionError,match='browser_only'): broker.fetch_missing_source(reference=renewed,lead_id=lead,source_url='https://app.test/s.js',max_bytes=1024)
    assert calls==[]



def test_browser_only_verified_local_bytes_and_context_capture_release(tmp_path,monkeypatch):
    ref,lead,source=setup(tmp_path)
    work_root=tmp_path/'work';(work_root/'r').mkdir(parents=True)
    digest=hashlib.sha256(source).hexdigest();(work_root/'r'/f'{digest}.js').write_bytes(source)
    monkeypatch.setattr('polymerhus.recon.js_acquisition.service.httpx.Client',lambda *a,**k: pytest.fail('HTTP replay forbidden'))
    broker=AcquisitionService(root=tmp_path,work_root=work_root)
    result=broker.fetch(reference=ref,lead_id=lead)
    assert result.body==source
    captures=SteelCaptureStore(root=tmp_path)
    common=dict(project_id='p',run_id='r',crawl_id='crawl',exact_url='https://app.test/a.js',status=200,content_type='application/javascript',body=source,sequence=1)
    captures.record_bytes(**common,pod_id='alice-pod',auth_context_ref='alice')
    captures.record_bytes(**common,pod_id='bob-pod',auth_context_ref='bob')
    for pod,context,l in [('alice-pod','alice','alice-lead'),('bob-pod','bob','bob-lead')]:
        captures.link_leads(project_id='p',run_id='r',pod_id=pod,auth_context_ref=context,exact_url=common['exact_url'],lead_ids=[l])
    captures.release_lead(project_id='p',run_id='r',pod_id='alice-pod',lead_id='alice-lead')
    released=captures.release_consumed(project_id='p',run_id='r',context_ref='alice')
    assert released['released_occurrences']==1 and released['deleted_blobs']==0
    bob=captures.find_by_url(project_id='p',run_id='r',pod_id='bob-pod',auth_context_ref='bob',exact_url=common['exact_url'])[0]
    assert captures.read_bytes(project_id='p',run_id='r',occurrence=bob)==source
