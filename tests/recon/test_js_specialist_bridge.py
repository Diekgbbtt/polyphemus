import json
import base64
import hashlib
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from polymerhus.app.llm.skills import SkillStore, build_load_skill_tool
from polymerhus.recon.js_intake import issue_js_intake_reference
from polymerhus.recon.js_intake.reader import InvalidJsIntakeReference


def test_exec_bridge_shared_loader_reference_and_run_notes(tmp_path):
    from polymerhus.recon.js_specialist.bridge import SpecialistBridge

    skills = SkillStore(root_dir=tmp_path)
    skills.write('p', 'js-inventory-intake', 'procedure', 'Project procedure')
    skills.write('p', 'js-inventory-intake', 'references/commands', 'Project commands')
    reference = issue_js_intake_reference('p', 'r', context_ref='alice')
    bridge = SpecialistBridge(root=tmp_path)
    result = bridge.call(reference, {'operation': 'skill', 'name': 'js-inventory-intake'})
    expected = build_load_skill_tool(project_id='p', store=skills).invoke({'name': 'js-inventory-intake'})
    assert result['content'] == expected
    assert bridge.call(reference, {'operation': 'reference', 'name': 'js-inventory-intake', 'target': 'commands'})['content'] == 'Project commands'
    bridge.call(reference, {'operation': 'notes', 'command': 'write', 'note': 'Selected lead_1; pending acquisition; reason browser_requested'})
    recovered = SpecialistBridge(root=tmp_path).call(reference, {'operation': 'notes', 'command': 'read'})
    assert 'pending acquisition' in json.dumps(recovered)
    assert list(tmp_path.glob('p/recon/js_analysis/r/notes.yaml'))
    other = issue_js_intake_reference('p', 'r', context_ref='bob')
    assert bridge.call(other, {'operation': 'notes', 'command': 'read'})['notes'] == []
    with pytest.raises(InvalidJsIntakeReference):
        bridge.call('expired', {'operation': 'inventory'})
    with pytest.raises(ValueError):
        bridge.call(reference, {'operation': 'reference', 'name': 'js-inventory-intake', 'target': '../secret'})


def test_bridge_pagination_and_missing_inventory_are_explicit(tmp_path):
    from polymerhus.recon.js_specialist.bridge import SpecialistBridge
    from polymerhus.recon.js_intake import JsIntakeStore
    from polymerhus.recon.domain.types import ExecResult

    store = JsIntakeStore(root=tmp_path)
    store.record_exec_result(project_id='p', run_id='r', pod_id='pod', producer='katana', input_context_ref='ctx', exec_result=ExecResult(stdout='\n'.join(json.dumps({'request': {'endpoint': f'https://example.com/{i}.js?token=private'}}) for i in range(3)), stderr='', returncode=0))
    ref = issue_js_intake_reference('p', 'r')
    bridge = SpecialistBridge(root=tmp_path)
    page = bridge.call(ref, {'operation': 'inventory', 'limit': 1})
    assert page['next_cursor']
    assert 'private' not in json.dumps(page)
    assert page['context']['auth_context_label'] == 'anonymous'
    assert bridge.call(ref, {'operation': 'inventory', 'limit': 1, 'cursor': page['next_cursor']})['leads'] != page['leads']
    missing = issue_js_intake_reference('p', 'r', context_ref='unknown')
    assert bridge.call(missing, {'operation': 'inventory'})['coverage']['coverage_gap'] == 'missing_inventory'


def test_bridge_scan_input_authorizes_only_acquired_lead_in_context(tmp_path):
    from polymerhus.app.data_root import ensure_project
    from polymerhus.recon.domain.types import ExecResult
    from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
    from polymerhus.recon.js_intake import JsIntakeReader, JsIntakeStore
    from polymerhus.recon.js_specialist.bridge import SpecialistBridge
    import json

    ensure_project("p", root=tmp_path)
    store = JsIntakeStore(root=tmp_path)
    store.record_exec_result(
        project_id="p",
        run_id="r",
        pod_id="pod",
        producer="katana",
        input_context_ref="ctx",
        exec_result=ExecResult(
            stdout=json.dumps(
                {
                    "request": {
                        "endpoint": "https://example.test/app.js",
                        "method": "GET",
                    }
                }
            ),
            stderr="",
            returncode=0,
        ),
        auth_context_label="authenticated",
        auth_context_ref="alice",
    )
    reference = issue_js_intake_reference("p", "r", context_ref="alice")
    lead_id = JsIntakeReader(root=tmp_path).list(
        reference=reference, limit=1
    )["leads"][0]["lead_id"]

    bridge = SpecialistBridge(root=tmp_path)
    with pytest.raises(ValueError):
        bridge.call(
            reference,
            {"operation": "scan_input", "lead_id": lead_id},
        )

    manifest = AcquisitionManifest(
        project_id="p",
        run_id="r",
        root=tmp_path,
        max_run_bytes=1024,
    )
    digest = "a" * 64
    assert manifest.reserve(
        lead_id=lead_id,
        record={"context_ref": "alice"},
        work_file_ref=f"/work/js-analysis/r/{digest}.js",
        sha256=digest,
        size=12,
    )
    assert manifest.confirm(
        lead_id=lead_id,
        size=12,
        sha256=digest,
        work_file_ref=f"/work/js-analysis/r/{digest}.js",
    ) == "acquired"

    allowed = bridge.call(
        reference,
        {"operation": "scan_input", "lead_id": lead_id},
    )
    assert allowed["sha256"] == digest
    assert allowed["size"] == 12
    assert allowed["work_file_ref"].endswith(f"/r/{digest}.js")

    other = issue_js_intake_reference("p", "r", context_ref="bob")
    with pytest.raises(Exception):
        bridge.call(
            other,
            {"operation": "scan_input", "lead_id": lead_id},
        )


def test_scan_submit_route_accepts_json_body(tmp_path):
    from polymerhus.app.data_root import ensure_project
    from polymerhus.recon.domain.types import ExecResult
    from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
    from polymerhus.recon.js_acquisition.scan_worker import (
        PATTERN_FINGERPRINT,
        scan_key_for,
    )
    from polymerhus.recon.js_intake import JsIntakeReader, JsIntakeStore
    from polymerhus.recon.js_specialist.bridge import build_router

    ensure_project("p", root=tmp_path)
    store = JsIntakeStore(root=tmp_path)
    store.record_exec_result(
        project_id="p",
        run_id="r",
        pod_id="pod",
        producer="katana",
        input_context_ref="ctx",
        exec_result=ExecResult(
            stdout=json.dumps(
                {
                    "request": {
                        "endpoint": "https://example.test/app.js",
                        "method": "GET",
                    }
                }
            ),
            stderr="",
            returncode=0,
        ),
        auth_context_label="authenticated",
        auth_context_ref="alice",
    )
    reference = issue_js_intake_reference("p", "r", context_ref="alice")
    lead_id = JsIntakeReader(root=tmp_path).list(
        reference=reference, limit=1
    )["leads"][0]["lead_id"]
    digest = "a" * 64
    manifest = AcquisitionManifest(
        project_id="p",
        run_id="r",
        root=tmp_path,
        max_run_bytes=1024,
    )
    work_ref = f"/work/js-analysis/r/{digest}.js"
    assert manifest.reserve(
        lead_id=lead_id,
        record={"context_ref": "alice"},
        work_file_ref=work_ref,
        sha256=digest,
        size=12,
    )
    assert manifest.confirm(
        lead_id=lead_id,
        size=12,
        sha256=digest,
        work_file_ref=work_ref,
    ) == "acquired"
    options = {"urls": ["urls", "-j"], "secrets": ["secrets", "-j"]}
    binary = {"path": "jsluice", "sha256": "b" * 64, "version": None}
    result = {
        "schema_version": 1,
        "candidate_schema_version": 2,
        "status": "complete",
        "source": {"sha256": digest, "size": 12},
        "binary": binary,
        "options": options,
        "pattern_fingerprint": PATTERN_FINGERPRINT,
        "scan_key": scan_key_for(
            source_sha256=digest,
            binary=binary,
            options=options,
            pattern_fingerprint=PATTERN_FINGERPRINT,
        ),
        "limits": {},
        "modes": {
            "urls": {"status": "complete", "candidate_count": 0},
            "secrets": {"status": "complete", "candidate_count": 0},
        },
        "candidates": [],
    }
    app = FastAPI()
    app.include_router(build_router(root=tmp_path))
    response = TestClient(app).post(
        "/recon/js-specialist/scan/submit",
        headers={"X-JS-Intake-Reference": reference},
        json={"lead_id": lead_id, "mode": "urls", "result": result},
    )

    assert response.status_code == 200, response.text
    assert response.json()["overall_status"] == "partial"


def test_recovery_bridge_exposes_only_scoped_redacted_metadata(tmp_path):
    from polymerhus.app.data_root import ensure_project
    from polymerhus.recon.domain.types import ExecResult
    from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
    from polymerhus.recon.js_intake import JsIntakeReader, JsIntakeStore
    from polymerhus.recon.js_specialist.bridge import SpecialistBridge

    source_map = {
        "version": 3,
        "sources": ["src/private-name.js"],
        "sourcesContent": ["export const recovered = true;\n"],
        "names": [],
        "mappings": "",
    }
    raw_map = json.dumps(source_map, separators=(",", ":")).encode()
    js = (
        b"console.log('bundle');\n//# sourceMappingURL="
        b"data:application/json;charset=utf-8;base64,"
        + base64.b64encode(raw_map)
        + b"\n"
    )
    ensure_project("p", root=tmp_path)
    store = JsIntakeStore(root=tmp_path)
    store.record_exec_result(
        project_id="p",
        run_id="r",
        pod_id="pod",
        producer="katana",
        input_context_ref="ctx",
        exec_result=ExecResult(
            stdout=json.dumps(
                {"request": {"endpoint": "https://example.test/app.js?token=secret"}}
            ),
            stderr="",
            returncode=0,
        ),
        auth_context_label="authenticated",
        auth_context_ref="alice",
    )
    reference = issue_js_intake_reference("p", "r", context_ref="alice")
    lead_id = JsIntakeReader(root=tmp_path).list(
        reference=reference, limit=1
    )["leads"][0]["lead_id"]
    digest = hashlib.sha256(js).hexdigest()
    manifest = AcquisitionManifest(
        project_id="p", run_id="r", root=tmp_path, max_run_bytes=1024 * 1024
    )
    work_ref = f"/work/js-analysis/r/{digest}.js"
    assert manifest.reserve(
        lead_id=lead_id,
        record={
            "context_ref": "alice",
            "final_url": "https://example.test/app.js?token=secret",
        },
        work_file_ref=work_ref,
        sha256=digest,
        size=len(js),
    )
    assert manifest.confirm(
        lead_id=lead_id,
        size=len(js),
        sha256=digest,
        work_file_ref=work_ref,
    ) == "acquired"
    bridge = SpecialistBridge(root=tmp_path)
    bridge.recovery.recover_from_source(
        reference=reference, lead_id=lead_id, js_bytes=js
    )

    page = bridge.call(
        reference,
        {
            "operation": "recovery_sources",
            "lead_id": lead_id,
            "limit": 5,
        },
    )
    source = bridge.call(
        reference,
        {
            "operation": "recovery_source",
            "target": page["sources"][0]["source_id"],
        },
    )
    assert source["source_id"] == page["sources"][0]["source_id"]
    assert "https://" not in json.dumps(page)
    assert "secret" not in json.dumps(page)
    foreign = issue_js_intake_reference("p", "r", context_ref="bob")
    with pytest.raises(Exception):
        bridge.call(
            foreign,
            {"operation": "recovery_sources", "lead_id": lead_id},
        )


@pytest.mark.asyncio
async def test_dependency_nomination_is_bounded_at_rpc_boundary(tmp_path):
    from polymerhus.recon.js_specialist.bridge import build_router

    app = FastAPI()
    app.include_router(build_router(root=tmp_path))
    reference = issue_js_intake_reference("p", "r", context_ref="alice")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/recon/js-specialist/rpc",
            headers={"X-JS-Intake-Reference": reference},
            json={
                "operation": "behavior_save",
                "record": {},
                "dependencies": [{
                    "selector_type": "source",
                    "target": "src_a",
                    "rationale": "Required caller.",
                    "path": "/tmp/not-authorized",
                }],
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_retention_status_rpc_response_is_bounded(
    tmp_path,
    monkeypatch,
):
    from polymerhus.recon.js_specialist import bridge as bridge_module

    monkeypatch.setattr(
        bridge_module.SpecialistBridge,
        "call",
        lambda self, reference, payload: {"links": ["x" * 17000]},
    )
    app = FastAPI()
    app.include_router(bridge_module.build_router(root=tmp_path))
    reference = issue_js_intake_reference("p", "r")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/recon/js-specialist/rpc",
            headers={"X-JS-Intake-Reference": reference},
            json={
                "operation": "retention_status",
                "behavior_id": "behavior_a",
                "behavior_revision": 1,
            },
        )

    assert response.status_code == 413
    assert response.json()["detail"] == "behavior_response_limit"


@pytest.mark.asyncio
async def test_rpc_remaining_seconds_reaches_behavior_retention(
    tmp_path,
    monkeypatch,
):
    from polymerhus.recon.js_specialist import bridge as bridge_module

    seen = []

    def call(self, reference, payload, deadline=None):
        seen.append((deadline, time.monotonic()))
        return {'behavior_id': 'behavior_a', 'revision': 1}

    monkeypatch.setattr(
        bridge_module.SpecialistBridge,
        'call',
        call,
    )
    app = FastAPI()
    app.include_router(bridge_module.build_router(root=tmp_path))
    reference = issue_js_intake_reference('p', 'r', context_ref='alice')
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url='http://test',
    ) as client:
        response = await client.post(
            '/recon/js-specialist/rpc',
            headers={
                'X-JS-Intake-Reference': reference,
                'X-JS-Remaining-Seconds': '2',
            },
            json={
                'operation': 'behavior_save',
                'record': {},
            },
        )

    assert response.status_code == 200
    assert seen
    deadline, observed = seen[0]
    assert 1.8 < deadline - observed <= 2.01


@pytest.mark.asyncio
async def test_retention_transfer_rejects_oversize_stream_before_metadata(
    tmp_path,
):
    from polymerhus.recon.js_specialist import bridge as bridge_module

    app = FastAPI()
    app.include_router(bridge_module.build_router(root=tmp_path))
    reference = issue_js_intake_reference("p", "r", context_ref="alice")
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/recon/js-specialist/retention/transfer",
            headers={
                "X-JS-Intake-Reference": reference,
                "X-JS-Retention-Request": "jsret_oversize",
                "Content-Type": "application/javascript",
            },
            content=b"x" * (
                bridge_module.JS_RETENTION_MAX_FILE_BYTES + 1
            ),
        )

    assert response.status_code == 413
    assert response.json()["detail"] == "retention_transfer_too_large"
