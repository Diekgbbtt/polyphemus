import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from polymerhus.app.data_root import ensure_project
from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_acquisition.recovery import (
    RecoveryError,
    RecoveryLimits,
    SourceMapRecovery,
)
from polymerhus.recon.js_acquisition.service import AcquisitionError, AcquisitionService
from polymerhus.recon.js_intake import (
    JsIntakeReader,
    JsIntakeStore,
    issue_js_intake_reference,
)


FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "data/js-analysis-mvp-eval/sourcemap-extractors-comparison/fixtures.json"
)


def _inline_js(name: str = "section_same_name") -> bytes:
    value = json.loads(FIXTURES.read_text())[name]
    raw = json.dumps(value["map"], separators=(",", ":")).encode()
    marker = (
        "data:application/json;charset=utf-8;base64,"
        + base64.b64encode(raw).decode()
    )
    return (
        b"console.log('bundle');\n//# sourceMappingURL="
        + marker.encode()
        + b"\n"
    )


def _inline_from_map(source_map: dict) -> bytes:
    raw = json.dumps(source_map, separators=(",", ":")).encode()
    marker = (
        "data:application/json;charset=utf-8;base64,"
        + base64.b64encode(raw).decode()
    )
    return (
        b"console.log('bundle');\n//# sourceMappingURL="
        + marker.encode()
        + b"\n"
    )


def _acquired_lead(
    root: Path,
    js_bytes: bytes,
    *,
    context_ref: str = "account-1",
    run_id: str = "run-1",
    pod_id: str = "pod-1",
) -> tuple[str, str]:
    ensure_project("proj-1", root=root)
    intake = JsIntakeStore(root=root)
    intake.record_exec_result(
        project_id="proj-1",
        run_id=run_id,
        pod_id=pod_id,
        producer="katana",
        input_context_ref="ctx",
        exec_result=ExecResult(
            stdout=json.dumps(
                {"request": {"endpoint": "https://app.example.test/app.js"}}
            ),
            stderr="",
            returncode=0,
        ),
        auth_context_label="authenticated" if context_ref else "anonymous",
        auth_context_ref=context_ref or None,
    )
    reference = issue_js_intake_reference(
        "proj-1",
        run_id,
        context_ref=context_ref,
    )
    lead_id = JsIntakeReader(root=root).list(
        reference=reference, limit=1
    )["leads"][0]["lead_id"]
    digest = hashlib.sha256(js_bytes).hexdigest()
    manifest = AcquisitionManifest(
        project_id="proj-1",
        run_id=run_id,
        root=root,
        max_run_bytes=1024 * 1024,
    )
    work_ref = f"/work/js-analysis/{run_id}/{digest}.js"
    assert manifest.reserve(
        lead_id=lead_id,
        record={"context_ref": context_ref, "final_url": "https://app.example.test/app.js"},
        work_file_ref=work_ref,
        sha256=digest,
        size=len(js_bytes),
    )
    assert manifest.confirm(
        lead_id=lead_id,
        size=len(js_bytes),
        sha256=digest,
        work_file_ref=work_ref,
    ) == "acquired"
    return lead_id, reference


def _service(root: Path, *, max_run_bytes=1024 * 1024) -> SourceMapRecovery:
    acquisition = AcquisitionService(
        root=root,
        limits=None,
    )
    return SourceMapRecovery(
        root=root,
        acquisition=acquisition,
        limits=RecoveryLimits(max_run_bytes=max_run_bytes),
    )


def test_inline_sections_keep_distinct_stable_source_occurrences(tmp_path):
    root = tmp_path / "data"
    js = _inline_js()
    lead_id, reference = _acquired_lead(root, js)
    service = _service(root)

    first = service.recover_from_source(
        reference=reference, lead_id=lead_id, js_bytes=js
    )
    second = service.recover_from_source(
        reference=reference, lead_id=lead_id, js_bytes=js
    )

    first_ids = [row["source_id"] for row in first["sources"]]
    second_ids = [row["source_id"] for row in second["sources"]]
    assert first_ids == second_ids
    assert len(set(first_ids)) == 2
    assert [row["section_path"] for row in first["sources"]] == [[0], [1]]
    assert len({row["content_sha256"] for row in first["sources"]}) == 2
    assert first["status"] == "complete"


def test_artifact_read_confirm_retry_and_late_failure(tmp_path):
    root = tmp_path / "data"
    js = _inline_js()
    lead_id, reference = _acquired_lead(root, js)
    service = _service(root)
    recovered = service.recover_from_source(
        reference=reference, lead_id=lead_id, js_bytes=js
    )
    first, second = recovered["sources"]
    body = service.read_source_artifact(
        reference=reference, source_id=first["source_id"]
    )
    assert body == b"section-zero-shared\n"

    confirmed = service.confirm_source(
        reference=reference,
        source_id=first["source_id"],
        size=first["size"],
        sha256=first["content_sha256"],
        work_file_ref=first["work_file_ref"],
    )
    repeated = service.confirm_source(
        reference=reference,
        source_id=first["source_id"],
        size=first["size"],
        sha256=first["content_sha256"],
        work_file_ref=first["work_file_ref"],
    )
    late_failure = service.fail_source(
        reference=reference,
        source_id=first["source_id"],
        failure_reason="ack_failed",
    )

    assert confirmed["status"] == "available"
    assert repeated["idempotent"] is True
    assert late_failure["status"] == "available"
    assert late_failure["reconcile_required"] is True
    assert service.read_source_artifact(
        reference=reference, source_id=second["source_id"]
    ) == b"section-one-shared\n"


def test_source_index_paginates_and_is_auth_context_isolated(tmp_path):
    root = tmp_path / "data"
    js = _inline_js()
    first_lead, first_ref = _acquired_lead(
        root, js, context_ref="account-1", pod_id="pod-1"
    )
    second_lead, second_ref = _acquired_lead(
        root, js, context_ref="account-2", pod_id="pod-2"
    )
    service = _service(root)
    service.recover_from_source(
        reference=first_ref, lead_id=first_lead, js_bytes=js
    )
    service.recover_from_source(
        reference=second_ref, lead_id=second_lead, js_bytes=js
    )

    page = service.list_sources(
        reference=first_ref, lead_id=first_lead, limit=1
    )
    next_page = service.list_sources(
        reference=first_ref,
        lead_id=first_lead,
        limit=1,
        cursor=page["next_cursor"],
    )
    first_ids = {
        page["sources"][0]["source_id"],
        next_page["sources"][0]["source_id"],
    }
    foreign = service.list_sources(
        reference=second_ref, lead_id=second_lead, limit=10
    )
    assert len(first_ids) == 2
    assert first_ids.isdisjoint(
        {row["source_id"] for row in foreign["sources"]}
    )
    assert "https://" not in json.dumps(page)


def test_missing_object_is_explicit_and_retry_regenerates(tmp_path):
    root = tmp_path / "data"
    js = _inline_js()
    lead_id, reference = _acquired_lead(root, js)
    service = _service(root)
    recovered = service.recover_from_source(
        reference=reference, lead_id=lead_id, js_bytes=js
    )
    source = recovered["sources"][0]
    object_path = root / object_path_for_test(recovered, source)
    object_path.unlink()

    with pytest.raises(RecoveryError) as missing:
        service.read_source_artifact(
            reference=reference, source_id=source["source_id"]
        )
    assert missing.value.reason == "source_object_missing"

    service.recover_from_source(
        reference=reference, lead_id=lead_id, js_bytes=js
    )
    assert service.read_source_artifact(
        reference=reference, source_id=source["source_id"]
    ) == b"section-zero-shared\n"


def test_identical_content_is_shared_but_occurrence_ids_remain_distinct(tmp_path):
    root = tmp_path / "data"
    source_map = {
        "version": 3,
        "sources": ["a/shared.js", "b/shared.js"],
        "sourcesContent": ["same-content\n", "same-content\n"],
        "names": [],
        "mappings": "",
    }
    js = _inline_from_map(source_map)
    lead_id, reference = _acquired_lead(root, js)
    service = _service(root)
    result = service.recover_from_source(
        reference=reference, lead_id=lead_id, js_bytes=js
    )

    assert len({row["source_id"] for row in result["sources"]}) == 2
    assert len({row["object_ref"] for row in result["sources"]}) == 1
    manifest = service._manifest("proj-1", "run-1").get()
    assert manifest["temporary"]["used_bytes"] == (
        len(js) + len(json.dumps(source_map, separators=(",", ":")).encode())
        + len(b"same-content\n")
    )


def test_partial_quota_keeps_first_source_and_names_gap(tmp_path):
    root = tmp_path / "data"
    source_map = {
        "version": 3,
        "sources": ["one.js", "two.js"],
        "sourcesContent": ["first-content\n", "second-content\n"],
        "names": [],
        "mappings": "",
    }
    raw_map = json.dumps(source_map, separators=(",", ":")).encode()
    js = _inline_from_map(source_map)
    lead_id, reference = _acquired_lead(root, js)
    max_run = len(js) + len(raw_map) + len(b"first-content\n")
    service = _service(root, max_run_bytes=max_run)
    result = service.recover_from_source(
        reference=reference, lead_id=lead_id, js_bytes=js
    )

    assert result["status"] == "partial"
    assert [row["status"] for row in result["sources"]] == [
        "pending",
        "failed",
    ]
    assert result["sources"][1]["failure_reason"] == "run_scratch_limit"
    assert service.read_source_artifact(
        reference=reference,
        source_id=result["sources"][0]["source_id"],
    ) == b"first-content\n"


def test_recovery_http_routes_expose_metadata_and_transfer_only(tmp_path):
    from polymerhus.recon.js_acquisition.api import build_router

    root = tmp_path / "data"
    js = _inline_js()
    lead_id, reference = _acquired_lead(root, js)
    acquisition = AcquisitionService(root=root)
    service = SourceMapRecovery(root=root, acquisition=acquisition)
    app = FastAPI()
    app.include_router(build_router(service=acquisition, recovery=service))
    client = TestClient(app)

    started = client.post(
        f"/recon/js-analysis/recovery/start/{lead_id}",
        headers={
            "X-JS-Intake-Reference": reference,
            "X-JS-Work-SHA256": hashlib.sha256(js).hexdigest(),
        },
        content=js,
    )
    assert started.status_code == 200, started.text
    assert started.json()["source_count"] == 2
    assert "sources" not in started.json()

    page = service.list_sources(
        reference=reference, lead_id=lead_id, limit=10
    )
    first = page["sources"][0]
    artifact = client.get(
        f"/recon/js-analysis/recovery/artifact/{first['source_id']}",
        headers={"X-JS-Intake-Reference": reference},
    )
    assert artifact.status_code == 200
    assert artifact.content == b"section-zero-shared\n"
    confirmed = client.post(
        "/recon/js-analysis/recovery/confirm",
        headers={"X-JS-Intake-Reference": reference},
        json={
            "source_id": first["source_id"],
            "size": first["size"],
            "sha256": first["content_sha256"],
            "work_file_ref": first["work_file_ref"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "available"


def test_repeated_recovery_refetches_map_then_uses_cached_verified_snapshot(
    tmp_path, monkeypatch
):
    root = tmp_path / "data"
    js = b"console.log('bundle');\n//# sourceMappingURL=maps/app.js.map\n"
    lead_id, reference = _acquired_lead(root, js)
    service = _service(root)
    map_url = "https://app.example.test/maps/app.js.map"
    old_map = json.dumps(
        {
            "version": 3,
            "sources": ["old.js"],
            "sourcesContent": ["old-body\n"],
            "names": [],
            "mappings": "",
        },
        separators=(",", ":"),
    ).encode()
    new_map = json.dumps(
        {
            "version": 3,
            "sources": ["new.js"],
            "sourcesContent": ["new-body\n"],
            "names": [],
            "mappings": "",
        },
        separators=(",", ":"),
    ).encode()
    bodies = [old_map, new_map]
    calls = []

    def fetch_map(**kwargs):
        calls.append(kwargs["map_url"])
        if bodies:
            body = bodies.pop(0)
            return SimpleNamespace(body=body, final_url=map_url)
        raise AcquisitionError("transport_error")

    monkeypatch.setattr(service._acquisition, "fetch_map", fetch_map)

    first = service.recover_from_source(
        reference=reference, lead_id=lead_id, js_bytes=js
    )
    second = service.recover_from_source(
        reference=reference, lead_id=lead_id, js_bytes=js
    )
    cached = service.recover_from_source(
        reference=reference, lead_id=lead_id, js_bytes=js
    )

    assert first["sources"][0]["redacted_name"] == "old.js"
    assert second["sources"][0]["redacted_name"] == "new.js"
    assert calls == [map_url, map_url, map_url]
    assert cached["sources"][0]["redacted_name"] == "new.js"
    assert cached["gaps"] == [
        "map_refetch_unavailable_cached_snapshot",
        "transport_error",
    ]
    assert service.read_source_artifact(
        reference=reference,
        source_id=second["sources"][0]["source_id"],
    ) == b"new-body\n"


def test_available_source_survives_later_missing_content_fetch_failure(
    tmp_path, monkeypatch
):
    root = tmp_path / "data"
    js = b"console.log('bundle');\n//# sourceMappingURL=maps/app.js.map\n"
    lead_id, reference = _acquired_lead(root, js)
    service = _service(root)
    map_url = "https://app.example.test/app.js.map"
    source_url = "https://app.example.test/missing.js"
    map_body = json.dumps(
        {
            "version": 3,
            "sources": [source_url],
            "sourcesContent": [None],
            "names": [],
            "mappings": "",
        },
        separators=(",", ":"),
    ).encode()

    monkeypatch.setattr(
        service._acquisition,
        "fetch_map",
        lambda **kwargs: SimpleNamespace(body=map_body, final_url=map_url),
    )
    monkeypatch.setattr(
        service._acquisition,
        "fetch_missing_source",
        lambda **kwargs: SimpleNamespace(
            body=b"verified-body\n",
            final_url=source_url,
        ),
    )
    first = service.recover_from_source(
        reference=reference, lead_id=lead_id, js_bytes=js
    )
    source = first["sources"][0]
    confirmed = service.confirm_source(
        reference=reference,
        source_id=source["source_id"],
        size=source["size"],
        sha256=source["content_sha256"],
        work_file_ref=source["work_file_ref"],
    )

    def fail_missing_source(**kwargs):
        raise AcquisitionError("transport_error")

    monkeypatch.setattr(
        service._acquisition,
        "fetch_missing_source",
        fail_missing_source,
    )
    second = service.recover_from_source(
        reference=reference, lead_id=lead_id, js_bytes=js
    )
    reused = second["sources"][0]

    assert confirmed["status"] == "available"
    assert second["status"] == "complete"
    assert reused["status"] == "available"
    assert reused["available"] is True
    assert reused["failure_reason"] is None
    assert reused["work_file_ref"] == source["work_file_ref"]
    assert service.read_source_artifact(
        reference=reference, source_id=reused["source_id"]
    ) == b"verified-body\n"


def object_path_for_test(recovered, source):
    return (
        "proj-1/recon/js_analysis/run-1/"
        + source["object_ref"]
    )
