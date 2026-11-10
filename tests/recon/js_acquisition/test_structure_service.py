import hashlib
import json
from pathlib import Path

import pytest

from polymerhus.app.data_root import ensure_project
from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_acquisition.structure_service import (
    StructureError,
    StructureService,
)
from polymerhus.recon.js_intake import (
    JsIntakeReader,
    JsIntakeStore,
    issue_js_intake_reference,
)


def _acquired_lead(root: Path, source: bytes) -> tuple[str, str]:
    ensure_project("proj-1", root=root)
    intake = JsIntakeStore(root=root)
    intake.record_exec_result(
        project_id="proj-1",
        run_id="run-1",
        pod_id="pod-1",
        producer="katana",
        input_context_ref="ctx-1",
        exec_result=ExecResult(
            stdout=json.dumps(
                {
                    "request": {
                        "endpoint": (
                            "https://app.example.test/static/app.js?token=private"
                        ),
                        "method": "GET",
                    },
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
    )
    lead = JsIntakeReader(root=root).list(
        reference=reference,
        limit=10,
    )["leads"][0]
    digest = hashlib.sha256(source).hexdigest()
    manifest = AcquisitionManifest(
        project_id="proj-1",
        run_id="run-1",
        root=root,
        max_run_bytes=1024 * 1024,
    )
    work_ref = f"/work/js-analysis/run-1/{digest}.js"
    assert manifest.reserve(
        lead_id=lead["lead_id"],
        record={
            "context_ref": "account-a",
            "final_url": (
                "https://app.example.test/static/app.js?token=private"
            ),
        },
        work_file_ref=work_ref,
        sha256=digest,
        size=len(source),
    )
    assert manifest.confirm(
        lead_id=lead["lead_id"],
        size=len(source),
        sha256=digest,
        work_file_ref=work_ref,
    ) == "acquired"
    return lead["lead_id"], reference


def test_structure_service_revalidates_bytes_and_reuses_stable_index(tmp_path):
    source = b'export const x = import("./safe.js?token=SECRET");\n'
    lead_id, reference = _acquired_lead(tmp_path, source)
    service = StructureService(root=tmp_path)

    first = service.structure_from_source(
        reference=reference,
        lead_id=lead_id,
        source_bytes=source,
    )
    repeated = service.structure_from_source(
        reference=reference,
        lead_id=lead_id,
        source_bytes=source,
    )
    items = service.list_items(
        reference=reference,
        lead_id=lead_id,
        kind="import",
    )
    detail = service.get_item(
        reference=reference,
        item_id=items["items"][0]["item_id"],
    )

    assert first["index_id"] == repeated["index_id"]
    assert first["reused"] is False
    assert repeated["reused"] is True
    assert first["source_availability"] == "verified_current"
    assert items["source_availability"] == "historical_index"
    assert "SECRET" not in json.dumps(items)
    assert "SECRET" not in json.dumps(detail)
    assert detail["item"]["kind"] == "import"


def test_structure_service_rejects_unacquired_tampered_or_wrong_context(tmp_path):
    source = b"export const answer = 42;\n"
    lead_id, reference = _acquired_lead(tmp_path, source)
    service = StructureService(root=tmp_path)
    foreign = issue_js_intake_reference(
        "proj-1",
        "run-1",
        context_ref="account-b",
    )

    with pytest.raises(StructureError) as tampered:
        service.structure_from_source(
            reference=reference,
            lead_id=lead_id,
            source_bytes=source + b"\n",
        )
    assert tampered.value.reason == "structure_source_mismatch"

    with pytest.raises(StructureError) as wrong_context:
        service.structure_from_source(
            reference=foreign,
            lead_id=lead_id,
            source_bytes=source,
        )
    assert wrong_context.value.reason == "structure_lead_not_found"

    manifest = AcquisitionManifest(
        project_id="proj-1",
        run_id="run-1",
        root=tmp_path,
        max_run_bytes=1024 * 1024,
    )
    manifest.update(
        lambda value: value["leads"][lead_id].update(
            {"status": "failed", "available": False}
        )
    )
    with pytest.raises(StructureError) as unavailable:
        service.structure_from_source(
            reference=reference,
            lead_id=lead_id,
            source_bytes=source,
        )
    assert unavailable.value.reason == "structure_input_unavailable"


def test_saved_index_is_historical_when_current_acquisition_is_unavailable(
    tmp_path,
):
    source = b'export const answer = import("./answer.js");\n'
    lead_id, reference = _acquired_lead(tmp_path, source)
    service = StructureService(root=tmp_path)
    service.structure_from_source(
        reference=reference,
        lead_id=lead_id,
        source_bytes=source,
    )
    AcquisitionManifest(
        project_id="proj-1",
        run_id="run-1",
        root=tmp_path,
        max_run_bytes=1024 * 1024,
    ).update(
        lambda value: value["leads"][lead_id].update(
            {"status": "failed", "available": False}
        )
    )

    page = service.list_items(reference=reference, lead_id=lead_id)

    assert page["source_availability"] == "historical_index"
    assert page["status"] == "complete"
