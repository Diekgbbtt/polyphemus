import asyncio
import base64
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from polymerhus.app.data_root import ensure_project
from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_acquisition.api import build_router as build_acquisition_router
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_acquisition.recovery import SourceMapRecovery
from polymerhus.recon.js_acquisition.scan_store import ScanStore
from polymerhus.recon.js_acquisition.service import AcquisitionService
from polymerhus.recon.js_acquisition.structure_service import StructureService
from polymerhus.recon.js_acquisition.structure_service import StructureError
from polymerhus.recon.js_intake import (
    JsIntakeReader,
    JsIntakeStore,
    issue_js_intake_reference,
)
from polymerhus.recon.js_specialist.bridge import build_router as build_specialist_router


def _fixture(
    root: Path,
    *,
    exact_url: str | None = None,
) -> tuple[str, str, bytes]:
    ensure_project("proj-1", root=root)
    exact_url = exact_url or (
        "https://app.example.test/static/app.js?token=parent-private"
    )
    JsIntakeStore(root=root).record_exec_result(
        project_id="proj-1",
        run_id="run-1",
        pod_id="pod-1",
        producer="katana",
        input_context_ref="ctx-1",
        exec_result=ExecResult(
            stdout=json.dumps(
                {
                    "request": {"endpoint": exact_url, "method": "GET"},
                    "response": {
                        "status_code": 200,
                        "headers": {"Content-Type": "application/javascript"},
                    },
                }
            ),
            stderr="",
            returncode=0,
        ),
        auth_context_label="authenticated",
        auth_context_ref="account-a",
    )
    reference = issue_js_intake_reference(
        "proj-1",
        "run-1",
        context_ref="account-a",
        scope_domains=["app.example.test"],
    )
    lead_id = JsIntakeReader(root=root).list(
        reference=reference,
        limit=10,
    )["leads"][0]["lead_id"]
    source = (
        b'export const child = import("./child.js?token=child-private");\n'
    )
    digest = hashlib.sha256(source).hexdigest()
    manifest = AcquisitionManifest(
        project_id="proj-1",
        run_id="run-1",
        root=root,
        max_run_bytes=1024 * 1024,
    )
    work_ref = f"/work/js-analysis/run-1/{digest}.js"
    assert manifest.reserve(
        lead_id=lead_id,
        record={"context_ref": "account-a", "final_url": exact_url},
        work_file_ref=work_ref,
        sha256=digest,
        size=len(source),
    )
    assert manifest.confirm(
        lead_id=lead_id,
        size=len(source),
        sha256=digest,
        work_file_ref=work_ref,
    ) == "acquired"
    return lead_id, reference, source


def test_structure_route_and_exec_rpc_bind_body_and_context(tmp_path):
    root = tmp_path / "data"
    lead_id, reference, source = _fixture(root)
    digest = hashlib.sha256(source).hexdigest()
    structure = StructureService(root=root)
    app = FastAPI()
    app.include_router(build_acquisition_router(structure=structure))
    app.include_router(build_specialist_router(root=root))

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://agent:8080",
        ) as client:
            started = await client.post(
                f"/recon/js-analysis/structure/start/{lead_id}",
                content=source,
                headers={
                    "X-JS-Intake-Reference": reference,
                    "X-JS-Work-SHA256": digest,
                    "X-JS-Remaining-Seconds": "19",
                },
            )
            assert started.status_code == 200
            started_body = started.json()
            assert started_body["status"] == "complete"
            assert started_body["source_availability"] == "verified_current"
            assert "parent-private" not in started.text

            items = await client.post(
                "/recon/js-specialist/rpc",
                json={
                    "operation": "structure_items",
                    "lead_id": lead_id,
                    "kind": "import",
                    "limit": 5,
                },
                headers={"X-JS-Intake-Reference": reference},
            )
            assert items.status_code == 200
            assert "child-private" not in items.text
            item_id = items.json()["items"][0]["item_id"]

            detail = await client.post(
                "/recon/js-specialist/rpc",
                json={"operation": "structure_item", "target": item_id},
                headers={"X-JS-Intake-Reference": reference},
            )
            assert detail.status_code == 200
            assert detail.json()["item"]["kind"] == "import"
            assert "child-private" not in detail.text

            derived = await client.post(
                "/recon/js-specialist/rpc",
                json={"operation": "acquire_reference", "target": item_id},
                headers={"X-JS-Intake-Reference": reference},
            )
            assert derived.status_code == 200
            derived_body = derived.json()
            assert derived_body["status"] == "registered"
            assert derived_body["discovery_class"] == "code_reference"
            assert "child-private" not in derived.text
            return derived_body

    derived_body = asyncio.run(exercise())
    child = JsIntakeReader(root=root).get(
        reference=reference,
        lead_id=derived_body["lead_id"],
    )
    assert child["source_tool"] == "code_derived"
    assert child["discovery_class"] == "code_reference"
    assert "child-private" not in json.dumps(child)


def test_structure_routes_reject_wrong_context_and_tampered_body(tmp_path):
    root = tmp_path / "data"
    lead_id, reference, source = _fixture(root)
    digest = hashlib.sha256(source).hexdigest()
    app = FastAPI()
    app.include_router(
        build_acquisition_router(
            structure=StructureService(root=root),
        )
    )
    foreign = issue_js_intake_reference(
        "proj-1",
        "run-1",
        context_ref="account-b",
    )

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://agent:8080",
        ) as client:
            wrong = await client.post(
                f"/recon/js-analysis/structure/start/{lead_id}",
                content=source,
                headers={
                    "X-JS-Intake-Reference": foreign,
                    "X-JS-Work-SHA256": digest,
                    "X-JS-Remaining-Seconds": "19",
                },
            )
            changed = await client.post(
                f"/recon/js-analysis/structure/start/{lead_id}",
                content=source + b"\n",
                headers={
                    "X-JS-Intake-Reference": reference,
                    "X-JS-Work-SHA256": digest,
                    "X-JS-Remaining-Seconds": "19",
                },
            )
            return wrong, changed

    wrong_context, tampered = asyncio.run(exercise())

    assert wrong_context.status_code in {403, 404}
    assert tampered.status_code == 422
    assert tampered.json()["detail"] == "acquired_source_mismatch"


def test_structure_route_rejects_expired_reference(tmp_path):
    root = tmp_path / "data"
    lead_id, reference, source = _fixture(root)
    digest = hashlib.sha256(source).hexdigest()
    expired = issue_js_intake_reference(
        "proj-1",
        "run-1",
        context_ref="account-a",
        ttl_s=1,
    )
    app = FastAPI()
    app.include_router(
        build_acquisition_router(
            structure=StructureService(root=root),
        )
    )

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://agent:8080",
        ) as client:
            return await client.post(
                f"/recon/js-analysis/structure/start/{lead_id}",
                content=source,
                headers={
                    "X-JS-Intake-Reference": expired,
                    "X-JS-Work-SHA256": digest,
                    "X-JS-Remaining-Seconds": "19",
                },
            )

    # Avoid sleeping: issuing over the one-entry registry does not evict the
    # reference, and expiry is deterministic after this controlled wait.
    import time

    time.sleep(1.05)
    response = asyncio.run(exercise())
    assert response.status_code == 403
    assert reference not in response.text
    assert expired not in response.text


def test_reference_resolution_rejects_bare_and_cross_origin_without_http(
    tmp_path, monkeypatch
):
    root = tmp_path / "data"
    lead_id, reference, source = _fixture(root)
    service = StructureService(root=root)
    stored = service.structure_from_source(
        reference=reference,
        lead_id=lead_id,
        source_bytes=source,
    )
    item = service.list_items(
        reference=reference,
        lead_id=lead_id,
        kind="import",
    )["items"][0]
    assert "child-private" not in json.dumps(item)
    assert stored["index_id"] == item["index_id"]

    def forbidden_network(*args, **kwargs):
        pytest.fail("reference registration must not perform network I/O")

    monkeypatch.setattr(
        "polymerhus.recon.js_acquisition.service.httpx.Client",
        forbidden_network,
    )
    registered = service.register_reference(
        reference=reference,
        item_id=item["item_id"],
    )
    assert registered["status"] == "registered"

    bare_source = b'import("dependency-package");\n'
    AcquisitionManifest(
        project_id="proj-1",
        run_id="run-1",
        root=root,
        max_run_bytes=1024 * 1024,
    ).update(
        lambda value: value["leads"][lead_id].update(
            {
                "sha256": hashlib.sha256(bare_source).hexdigest(),
                "size": len(bare_source),
            }
        )
    )
    with pytest.raises(StructureError) as stale:
        service.register_reference(
            reference=reference,
            item_id=item["item_id"],
        )
    assert stale.value.reason == "structure_item_stale"
    service.structure_from_source(
        reference=reference,
        lead_id=lead_id,
        source_bytes=bare_source,
    )
    bare_item = service.list_items(
        reference=reference,
        lead_id=lead_id,
        kind="import",
    )["items"][0]
    with pytest.raises(StructureError) as bare:
        service.register_reference(
            reference=reference,
            item_id=bare_item["item_id"],
        )
    assert bare.value.reason == "import_map_context_missing"

    cross_origin = b'import("https://outside.invalid/child.js");\n'
    AcquisitionManifest(
        project_id="proj-1",
        run_id="run-1",
        root=root,
        max_run_bytes=1024 * 1024,
    ).update(
        lambda value: value["leads"][lead_id].update(
            {
                "sha256": hashlib.sha256(cross_origin).hexdigest(),
                "size": len(cross_origin),
            }
        )
    )
    service.structure_from_source(
        reference=reference,
        lead_id=lead_id,
        source_bytes=cross_origin,
    )
    cross_item = service.list_items(
        reference=reference,
        lead_id=lead_id,
        kind="import",
    )["items"][0]
    with pytest.raises(StructureError) as out_of_scope:
        service.register_reference(
            reference=reference,
            item_id=cross_item["item_id"],
        )
    assert out_of_scope.value.reason == "reference_out_of_scope"


def test_derived_child_is_scan_recovery_and_structure_eligible(tmp_path):
    child_source = b'export const child = import("./grandchild.js");\n'
    source_map = {
        "version": 3,
        "sources": ["child.ts"],
        "sourcesContent": ["export const child = true;\n"],
        "names": [],
        "mappings": "",
    }
    encoded_map = base64.b64encode(
        json.dumps(source_map, separators=(",", ":")).encode()
    ).decode()
    child_source += (
        f"//# sourceMappingURL=data:application/json;base64,{encoded_map}\n"
    ).encode()
    root = tmp_path / "data"
    lead_id, reference, parent_source = _fixture(root)
    structure = StructureService(root=root)
    structure.structure_from_source(
        reference=reference,
        lead_id=lead_id,
        source_bytes=parent_source,
    )
    item = structure.list_items(
        reference=reference,
        lead_id=lead_id,
        kind="import",
    )["items"][0]
    registered = structure.register_reference(
        reference=reference,
        item_id=item["item_id"],
    )
    child_id = registered["lead_id"]
    child_private, _ = JsIntakeReader(root=root).get_private(
        reference=reference,
        lead_id=child_id,
    )
    assert "child-private" in child_private["exact_url"]
    assert child_private["auth_context_ref"] == "account-a"

    digest = hashlib.sha256(child_source).hexdigest()
    work_ref = f"/work/js-analysis/run-1/{digest}.js"
    manifest = AcquisitionManifest(
        project_id="proj-1",
        run_id="run-1",
        root=root,
        max_run_bytes=1024 * 1024,
    )
    assert manifest.reserve(
        lead_id=child_id,
        record={
            "context_ref": "account-a",
            "final_url": child_private["exact_url"],
        },
        work_file_ref=work_ref,
        sha256=digest,
        size=len(child_source),
    )
    assert manifest.confirm(
        lead_id=child_id,
        size=len(child_source),
        sha256=digest,
        work_file_ref=work_ref,
    ) == "acquired"

    work_input = ScanStore(root=root).work_input(
        project_id="proj-1",
        run_id="run-1",
        lead_id=child_id,
        context_ref="account-a",
    )
    acquisition = AcquisitionService(root=root, work_root=tmp_path / "work")
    recovered = SourceMapRecovery(
        root=root,
        acquisition=acquisition,
    ).recover_from_source(
        reference=reference,
        lead_id=child_id,
        js_bytes=child_source,
    )
    indexed = structure.structure_from_source(
        reference=reference,
        lead_id=child_id,
        source_bytes=child_source,
    )

    assert work_input["sha256"] == digest
    assert len(recovered["sources"]) == 1
    assert indexed["status"] == "complete"
    assert "child-private" not in json.dumps(registered)
