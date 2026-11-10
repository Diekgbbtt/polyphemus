import json
from pathlib import Path

import pytest

from polymerhus.app.data_root import ensure_project
from polymerhus.recon.js_acquisition import (
    AcquisitionError,
    AcquisitionService,
)
from polymerhus.recon.js_acquisition.capture import CaptureLimits, SteelCaptureStore
from polymerhus.recon.js_intake import JsIntakeStore, issue_js_intake_reference


def _record_lead(
    root: Path,
    *,
    url: str,
    context_ref: str = "account-1",
    pod_id: str = "steel-pod",
    producer: str = "steel_crawl",
) -> str:
    store = JsIntakeStore(root=root)
    path = (
        root
        / "proj-1"
        / "recon"
        / "js-intake"
        / "run-1"
        / f"{pod_id}.jsonl"
    )
    if producer == "steel_crawl":
        store.record_manifest(
            project_id="proj-1",
            run_id="run-1",
            pod_id=pod_id,
            producer=producer,
            input_context_ref="ctx-steel",
            manifest={"endpoints": [], "js_urls": [url]},
            terminal_result="success",
            output_completeness="complete",
            auth_context_label="authenticated" if context_ref else "anonymous",
            auth_context_ref=context_ref or None,
        )
    elif producer == "katana":
        store.record_exec_result(
            project_id="proj-1",
            run_id="run-1",
            pod_id=pod_id,
            producer=producer,
            input_context_ref="ctx-katana",
            exec_result=__import__(
                "polymerhus.recon.domain.types",
                fromlist=["ExecResult"],
            ).ExecResult(
                stdout=json.dumps(
                    {
                        "request": {"endpoint": url, "method": "GET"},
                        "response": {
                            "status_code": 200,
                            "headers": {
                                "Content-Type": "application/javascript"
                            },
                        },
                    }
                ),
                stderr="",
                returncode=0,
            ),
            auth_context_label="authenticated" if context_ref else "anonymous",
            auth_context_ref=context_ref or None,
        )
    else:
        raise ValueError(producer)
    return json.loads(path.read_text(encoding="utf-8").split("\n")[1])["lead_id"]


def test_same_url_different_bodies_are_distinct_occurrences(tmp_path: Path) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    store = SteelCaptureStore(
        root=root,
        limits=CaptureLimits(max_file_bytes=1024, max_run_bytes=4096),
    )
    url = "https://app.example.test/static/chunk.js?token=private"
    first = store.record_bytes(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        crawl_id="crawl-1",
        auth_context_ref="account-1",
        exact_url=url,
        status=200,
        content_type="application/javascript",
        body=b"export const version = 1;\n",
        sequence=1,
    )
    second = store.record_bytes(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        crawl_id="crawl-1",
        auth_context_ref="account-1",
        exact_url=url,
        status=200,
        content_type="application/javascript",
        body=b"export const version = 2;\n",
        sequence=2,
    )

    found = store.find_by_url(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        auth_context_ref="account-1",
        exact_url=url,
    )

    assert first["capture_id"] != second["capture_id"]
    assert {item["sha256"] for item in found} == {
        first["sha256"],
        second["sha256"],
    }
    assert all(item["status"] == "stored" for item in found)
    manifest = (
        root
        / "proj-1"
        / "recon"
        / "js_analysis"
        / "run-1"
        / "captures"
        / "manifest.json"
    ).read_text(encoding="utf-8")
    assert "version = 1" not in manifest
    assert "version = 2" not in manifest


def test_capture_limits_and_non_js_outcomes_are_explicit(tmp_path: Path) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    store = SteelCaptureStore(
        root=root,
        limits=CaptureLimits(max_file_bytes=40, max_run_bytes=50),
    )
    url = "https://app.example.test/login.js"
    unauth = store.record_gap(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        crawl_id="crawl-1",
        auth_context_ref="account-1",
        exact_url=url,
        status=401,
        content_type="text/plain",
        reason="http_status_401",
        sequence=1,
    )
    html = store.record_gap(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        crawl_id="crawl-1",
        auth_context_ref="account-1",
        exact_url=url,
        status=200,
        content_type="text/html",
        reason="non_js_content_type",
        sequence=2,
    )
    too_large = store.record_bytes(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        crawl_id="crawl-1",
        auth_context_ref="account-1",
        exact_url=url,
        status=200,
        content_type="application/javascript",
        body=b"x" * 41,
        sequence=3,
    )
    first = store.record_bytes(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        crawl_id="crawl-1",
        auth_context_ref="account-1",
        exact_url="https://app.example.test/a.js",
        status=200,
        content_type="application/javascript",
        body=b"a" * 30,
        sequence=4,
    )
    quota = store.record_bytes(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        crawl_id="crawl-1",
        auth_context_ref="account-1",
        exact_url="https://app.example.test/b.js",
        status=200,
        content_type="application/javascript",
        body=b"b" * 30,
        sequence=5,
    )

    assert unauth["failure_reason"] == "http_status_401"
    assert html["failure_reason"] == "non_js_content_type"
    assert too_large["failure_reason"] == "file_too_large"
    assert first["status"] == "stored"
    assert quota["failure_reason"] == "run_capture_limit_exceeded"
    manifest = json.loads(
        (
            root
            / "proj-1"
            / "recon"
            / "js_analysis"
            / "run-1"
            / "captures"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["temporary"]["used_bytes"] == 30


def test_capture_lookup_is_isolated_by_project_run_and_context(tmp_path: Path) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    ensure_project("proj-2", root=root)
    store = SteelCaptureStore(root=root)
    store.record_bytes(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        crawl_id="crawl-1",
        auth_context_ref="account-1",
        exact_url="https://app.example.test/a.js",
        status=200,
        content_type="application/javascript",
        body=b"a",
        sequence=1,
    )

    assert store.find_by_url(
        project_id="proj-2",
        run_id="run-1",
        auth_context_ref="account-1",
        exact_url="https://app.example.test/a.js",
    ) == []
    assert store.find_by_url(
        project_id="proj-1",
        run_id="run-2",
        auth_context_ref="account-1",
        exact_url="https://app.example.test/a.js",
    ) == []
    assert store.find_by_url(
        project_id="proj-1",
        run_id="run-1",
        pod_id="another-steel-pod",
        auth_context_ref="account-1",
        exact_url="https://app.example.test/a.js",
    ) == []
    assert store.find_by_url(
        project_id="proj-1",
        run_id="run-1",
        auth_context_ref="account-2",
        exact_url="https://app.example.test/a.js",
    ) == []


def test_broker_prefers_unique_capture_without_network_and_rejects_versions(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    url = "http://127.0.0.1:1/protected.js?token=private"
    lead_id = _record_lead(root, url=url)
    capture_store = SteelCaptureStore(root=root)
    captured = b"export const capturedOnly = true;\n"
    occurrence = capture_store.record_bytes(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        crawl_id="crawl-1",
        auth_context_ref="account-1",
        exact_url=url,
        status=200,
        content_type="application/javascript",
        body=captured,
        sequence=1,
    )
    capture_store.link_leads(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        auth_context_ref="account-1",
        exact_url=url,
        lead_ids=[lead_id],
    )
    reference = issue_js_intake_reference(
        "proj-1",
        "run-1",
        context_ref="account-1",
        scope_domains=["127.0.0.1"],
    )
    service = AcquisitionService(
        root=root,
        work_root=tmp_path / "work",
        capture_store=capture_store,
    )

    result = service.fetch(reference=reference, lead_id=lead_id)

    assert result.body == captured
    assert result.sha256 == occurrence["sha256"]

    capture_store.record_bytes(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        crawl_id="crawl-1",
        auth_context_ref="account-1",
        exact_url=url,
        status=200,
        content_type="application/javascript",
        body=b"export const secondVersion = true;\n",
        sequence=2,
    )
    capture_store.link_leads(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        auth_context_ref="account-1",
        exact_url=url,
        lead_ids=[lead_id],
    )
    with pytest.raises(AcquisitionError) as exc:
        service.fetch(reference=reference, lead_id=lead_id)
    assert exc.value.reason == "multiple_capture_versions"


def test_two_steel_pods_with_same_url_receive_their_own_captured_body(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    url = "https://app.example.test/shared.js?context=account-1"
    first_lead = _record_lead(root, url=url, pod_id="steel-pod-a")
    second_lead = _record_lead(root, url=url, pod_id="steel-pod-b")
    store = SteelCaptureStore(root=root)
    first_body = b"export const podA = true;\n"
    second_body = b"export const podB = true;\n"
    for pod_id, body, sequence in (
        ("steel-pod-a", first_body, 1),
        ("steel-pod-b", second_body, 2),
    ):
        occurrence = store.record_bytes(
            project_id="proj-1",
            run_id="run-1",
            pod_id=pod_id,
            crawl_id=f"crawl-{pod_id}",
            auth_context_ref="account-1",
            exact_url=url,
            status=200,
            content_type="application/javascript",
            body=body,
            sequence=sequence,
        )
        lead_id = first_lead if pod_id == "steel-pod-a" else second_lead
        store.link_leads(
            project_id="proj-1",
            run_id="run-1",
            pod_id=pod_id,
            auth_context_ref="account-1",
            exact_url=url,
            lead_ids=[lead_id],
        )
    reference = issue_js_intake_reference(
        "proj-1", "run-1", context_ref="account-1"
    )
    service = AcquisitionService(
        root=root, work_root=tmp_path / "work", capture_store=store
    )

    first = service.fetch(reference=reference, lead_id=first_lead)
    second = service.fetch(reference=reference, lead_id=second_lead)

    assert first.body == first_body
    assert second.body == second_body


def test_two_versions_in_one_pod_fail_explicitly(tmp_path: Path) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    url = "https://app.example.test/versioned.js"
    lead_id = _record_lead(root, url=url, pod_id="steel-pod")
    store = SteelCaptureStore(root=root)
    for sequence, body in (
        (1, b"export const version = 1;\n"),
        (2, b"export const version = 2;\n"),
    ):
        store.record_bytes(
            project_id="proj-1",
            run_id="run-1",
            pod_id="steel-pod",
            crawl_id="crawl-1",
            auth_context_ref="account-1",
            exact_url=url,
            status=200,
            content_type="application/javascript",
            body=body,
            sequence=sequence,
        )
    store.link_leads(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        auth_context_ref="account-1",
        exact_url=url,
        lead_ids=[lead_id],
    )
    reference = issue_js_intake_reference(
        "proj-1", "run-1", context_ref="account-1"
    )
    service = AcquisitionService(
        root=root, work_root=tmp_path / "work", capture_store=store
    )

    with pytest.raises(AcquisitionError) as exc:
        service.fetch(reference=reference, lead_id=lead_id)

    assert exc.value.reason == "multiple_capture_versions"


def test_katana_lead_with_same_url_keeps_network_fetch_path(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    url = "https://app.example.test/shared.js"
    lead_id = _record_lead(
        root, url=url, pod_id="katana-pod", producer="katana"
    )
    store = SteelCaptureStore(root=root)
    store.record_bytes(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        crawl_id="crawl-1",
        auth_context_ref="account-1",
        exact_url=url,
        status=200,
        content_type="application/javascript",
        body=b"export const steelBytes = true;\n",
        sequence=1,
    )
    reference = issue_js_intake_reference(
        "proj-1", "run-1", context_ref="account-1", scope_domains=["app.example.test"]
    )
    service = AcquisitionService(
        root=root, work_root=tmp_path / "work", capture_store=store
    )

    with pytest.raises(AcquisitionError) as exc:
        service.fetch(reference=reference, lead_id=lead_id)

    assert exc.value.reason != "multiple_capture_versions"
    assert exc.value.reason in {"transport_error", "auth_context_unavailable"}


def test_release_then_resume_before_expiry_and_gap_after_cleanup(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    url = "https://app.example.test/reusable.js"
    lead_id = _record_lead(root, url=url)
    store = SteelCaptureStore(root=root)
    body = b"export const reusable = true;\n"
    occurrence = store.record_bytes(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        crawl_id="crawl-1",
        auth_context_ref="account-1",
        exact_url=url,
        status=200,
        content_type="application/javascript",
        body=body,
        sequence=1,
    )
    store.link_leads(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        auth_context_ref="account-1",
        exact_url=url,
        lead_ids=[lead_id],
    )
    store.release_lead(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        lead_id=lead_id,
    )
    resumed = store.find_by_lead(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        auth_context_ref="account-1",
        exact_url=url,
        lead_id=lead_id,
    )
    assert resumed[0]["status"] == "stored"
    assert store.read_bytes(
        project_id="proj-1", run_id="run-1", occurrence=resumed[0]
    ) == body

    cleanup = store.cleanup_expired(
        project_id="proj-1",
        run_id="run-1",
        ttl_s=60,
        now=occurrence["captured_at"] + 61,
        run_active=False,
    )
    assert cleanup["deleted_blobs"] == 1
    after = store.find_by_lead(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        auth_context_ref="account-1",
        exact_url=url,
        lead_id=lead_id,
    )[0]
    assert after["status"] == "released"
    assert after["failure_reason"] == "released_after_expiry"
    assert after["lead_ids"] == [lead_id]

    reference = issue_js_intake_reference(
        "proj-1", "run-1", context_ref="account-1"
    )
    service = AcquisitionService(
        root=root, work_root=tmp_path / "work", capture_store=store
    )
    with pytest.raises(AcquisitionError) as exc:
        service.fetch(reference=reference, lead_id=lead_id)
    assert exc.value.reason == "capture_unavailable"
    private_manifest = json.loads(
        (
            root
            / "proj-1"
            / "recon"
            / "js_analysis"
            / "run-1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    failed = private_manifest["leads"][lead_id]
    assert failed["failure_reason"] == "capture_unavailable"
    assert failed["capture_gap_reason"] == "released_after_expiry"


def test_confirmation_releases_capture_reference_but_not_needed_bytes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    url = "https://app.example.test/consumed.js"
    lead_id = _record_lead(root, url=url)
    store = SteelCaptureStore(root=root)
    body = b"export const consumed = true;\n"
    occurrence = store.record_bytes(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        crawl_id="crawl-1",
        auth_context_ref="account-1",
        exact_url=url,
        status=200,
        content_type="application/javascript",
        body=body,
        sequence=1,
    )
    store.link_leads(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        auth_context_ref="account-1",
        exact_url=url,
        lead_ids=[lead_id],
    )
    reference = issue_js_intake_reference(
        "proj-1", "run-1", context_ref="account-1"
    )
    service = AcquisitionService(
        root=root, work_root=tmp_path / "work", capture_store=store
    )

    result = service.fetch(reference=reference, lead_id=lead_id)
    service.confirm(
        reference=reference,
        lead_id=lead_id,
        size=result.size,
        sha256=result.sha256,
        work_file_ref=result.work_file_ref,
    )

    after = store.find_by_lead(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        auth_context_ref="account-1",
        exact_url=url,
        lead_id=lead_id,
    )[0]
    assert after["capture_id"] == occurrence["capture_id"]
    assert after["active_lead_ids"] == []
    assert store.read_bytes(
        project_id="proj-1", run_id="run-1", occurrence=after
    ) == body


def test_active_run_cleanup_keeps_blob_shared_by_occurrences(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    store = SteelCaptureStore(root=root)
    body = b"export const shared = true;\n"
    first = store.record_bytes(
        project_id="proj-1",
        run_id="run-1",
        pod_id="pod-a",
        crawl_id="crawl-a",
        auth_context_ref="account-1",
        exact_url="https://app.example.test/a.js",
        status=200,
        content_type="application/javascript",
        body=body,
        sequence=1,
    )
    second = store.record_bytes(
        project_id="proj-1",
        run_id="run-1",
        pod_id="pod-b",
        crawl_id="crawl-b",
        auth_context_ref="account-1",
        exact_url="https://app.example.test/b.js",
        status=200,
        content_type="application/javascript",
        body=body,
        sequence=2,
    )
    store.link_leads(
        project_id="proj-1",
        run_id="run-1",
        pod_id="pod-a",
        auth_context_ref="account-1",
        exact_url="https://app.example.test/a.js",
        lead_ids=["lead-a"],
    )
    store.link_leads(
        project_id="proj-1",
        run_id="run-1",
        pod_id="pod-b",
        auth_context_ref="account-1",
        exact_url="https://app.example.test/b.js",
        lead_ids=["lead-b"],
    )
    store.release_lead(
        project_id="proj-1",
        run_id="run-1",
        pod_id="pod-a",
        lead_id="lead-a",
    )

    cleanup = store.cleanup_expired(
        project_id="proj-1",
        run_id="run-1",
        ttl_s=10,
        now=first["captured_at"] + 11,
    )

    assert cleanup["deleted_blobs"] == 0
    assert store.read_bytes(
        project_id="proj-1", run_id="run-1", occurrence=second
    ) == body


def test_expired_abandoned_run_is_cleaned_even_with_unconsumed_leads(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    store = SteelCaptureStore(root=root)
    url = "https://app.example.test/abandoned.js"
    occurrence = store.record_bytes(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        crawl_id="crawl-1",
        auth_context_ref="account-1",
        exact_url=url,
        status=200,
        content_type="application/javascript",
        body=b"export const abandoned = true;\n",
        sequence=1,
    )
    store.link_leads(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        auth_context_ref="account-1",
        exact_url=url,
        lead_ids=["lead-unconsumed"],
    )

    cleanup = store.cleanup_expired(
        project_id="proj-1",
        run_id="run-1",
        ttl_s=10,
        now=occurrence["captured_at"] + 11,
        run_active=False,
    )

    assert cleanup["deleted_blobs"] == 1
    after = store.find_by_url(
        project_id="proj-1",
        run_id="run-1",
        auth_context_ref="account-1",
        exact_url=url,
    )[0]
    assert after["status"] == "released"
    assert after["failure_reason"] == "released_after_expiry"
    assert after["lead_ids"] == ["lead-unconsumed"]
