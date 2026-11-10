import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from polymerhus.app.data_root import ensure_project
from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_acquisition.scan_worker import scan_local_file
from polymerhus.recon.js_intake import (
    JsIntakeReader,
    JsIntakeStore,
    issue_js_intake_reference,
)
from polymerhus.recon.scripts.jsluice_scan import JsluiceProcessResult


def _executor(url_records: list[dict], secret_records: list[dict]):
    def run(mode, _path, *, timeout_s, max_output_bytes, executable):
        records = url_records if mode == "urls" else secret_records
        return JsluiceProcessResult(
            stdout="".join(json.dumps(item) + "\n" for item in records),
            returncode=0,
        )

    return run


def _acquired_lead(
    root: Path,
    *,
    source: Path,
    digest: str,
    context_ref: str = "account-1",
    pod_id: str = "pod-1",
    url: str = "https://app.example.test/static/source.js",
) -> tuple[str, str]:
    intake = JsIntakeStore(root=root)
    intake.record_exec_result(
        project_id="proj-1",
        run_id="run-1",
        pod_id=pod_id,
        producer="katana",
        input_context_ref="ctx",
        exec_result=ExecResult(
            stdout=json.dumps(
                {
                    "request": {
                        "endpoint": url,
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
        auth_context_label="authenticated" if context_ref else "anonymous",
        auth_context_ref=context_ref or None,
    )
    reference = issue_js_intake_reference(
        "proj-1",
        "run-1",
        context_ref=context_ref,
    )
    lead = JsIntakeReader(root=root).list(reference=reference, limit=10)["leads"][0]
    manifest = AcquisitionManifest(
        project_id="proj-1",
        run_id="run-1",
        root=root,
        max_run_bytes=1024 * 1024,
    )
    work_ref = f"/work/js-analysis/run-1/{digest}.js"
    assert manifest.reserve(
        lead_id=lead["lead_id"],
        record={"context_ref": context_ref},
        work_file_ref=work_ref,
        sha256=digest,
        size=source.stat().st_size,
    )
    assert manifest.confirm(
        lead_id=lead["lead_id"],
        size=source.stat().st_size,
        sha256=digest,
        work_file_ref=work_ref,
    ) == "acquired"
    return lead["lead_id"], reference


def _scan_result(
    source: Path,
    digest: str,
    *,
    urls: list[dict],
    secrets: list[dict] | None = None,
):
    return scan_local_file(
        source,
        expected_sha256=digest,
        expected_size=source.stat().st_size,
        executor=_executor(urls, secrets or []),
        binary_info={
            "path": "jsluice",
            "sha256": "a" * 64,
            "version": "test-build",
        },
    )


def test_scan_store_incremental_modes_preserve_acquisition_state(tmp_path):
    from polymerhus.recon.js_acquisition.scan_store import ScanStore

    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    source = tmp_path / "source.js"
    source.write_bytes(b"const scanStore = true;\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    lead_id, _reference = _acquired_lead(root, source=source, digest=digest)
    result = _scan_result(
        source,
        digest,
        urls=[{"url": "https://api.example.test/items?token=private"}],
        secrets=[{"kind": "aws-access-key", "data": {"secret": "AKIAFIXTURE"}}],
    )
    store = ScanStore(root=root)

    first = store.submit_mode(
        project_id="proj-1",
        run_id="run-1",
        lead_id=lead_id,
        context_ref="account-1",
        result=result,
        mode="urls",
    )
    manifest = AcquisitionManifest(
        project_id="proj-1",
        run_id="run-1",
        root=root,
        max_run_bytes=1024 * 1024,
    ).get()

    assert first["overall_status"] == "partial"
    assert manifest["leads"][lead_id]["status"] == "acquired"
    assert manifest["leads"][lead_id]["scan"]["modes"].keys() == {"urls"}
    assert manifest["scans"][result["scan_key"]]["candidate_file"].startswith(
        "scans/"
    )

    second = store.submit_mode(
        project_id="proj-1",
        run_id="run-1",
        lead_id=lead_id,
        context_ref="account-1",
        result=result,
        mode="secrets",
    )
    manifest = AcquisitionManifest(
        project_id="proj-1",
        run_id="run-1",
        root=root,
        max_run_bytes=1024 * 1024,
    ).get()

    assert second["overall_status"] == "complete"
    assert manifest["leads"][lead_id]["status"] == "acquired"
    assert set(manifest["leads"][lead_id]["scan"]["modes"]) == {
        "urls",
        "secrets",
    }
    assert manifest["temporary"]["used_bytes"] == source.stat().st_size


def test_scan_store_retry_is_idempotent_and_stable_ids(tmp_path):
    from polymerhus.recon.js_acquisition.scan_store import ScanStore

    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    source = tmp_path / "source.js"
    source.write_bytes(b"const retry = true;\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    lead_id, _reference = _acquired_lead(root, source=source, digest=digest)
    result = _scan_result(
        source,
        digest,
        urls=[{"url": "https://api.example.test/retry"}],
    )
    store = ScanStore(root=root)

    first = store.submit_mode(
        project_id="proj-1",
        run_id="run-1",
        lead_id=lead_id,
        context_ref="account-1",
        result=result,
        mode="urls",
    )
    second = store.submit_mode(
        project_id="proj-1",
        run_id="run-1",
        lead_id=lead_id,
        context_ref="account-1",
        result=result,
        mode="urls",
    )
    page = store.read(
        project_id="proj-1",
        run_id="run-1",
        lead_id=lead_id,
        mode="urls",
        limit=10,
    )

    assert first["submission_id"] == second["submission_id"]
    assert page["candidates"][0]["candidate_id"] == page["candidates"][0][
        "candidate_id"
    ]
    assert page["candidates"][0]["candidate_id"].startswith("cand_")


def test_scan_store_paginates_without_duplicate_or_cross_mode_records(tmp_path):
    from polymerhus.recon.js_acquisition.scan_store import ScanStore

    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    source = tmp_path / "source.js"
    source.write_bytes(b"const pages = true;\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    lead_id, _reference = _acquired_lead(root, source=source, digest=digest)
    result = _scan_result(
        source,
        digest,
        urls=[
            {"url": "https://api.example.test/one"},
            {"url": "https://api.example.test/two"},
            {"url": "https://api.example.test/three"},
        ],
        secrets=[{"kind": "jwt", "data": {"token": "SECRET_VALUE"}}],
    )
    store = ScanStore(root=root)
    store.submit_mode(
        project_id="proj-1",
        run_id="run-1",
        lead_id=lead_id,
        context_ref="account-1",
        result=result,
        mode="urls",
    )
    store.submit_mode(
        project_id="proj-1",
        run_id="run-1",
        lead_id=lead_id,
        context_ref="account-1",
        result=result,
        mode="secrets",
    )

    first = store.read(
        project_id="proj-1",
        run_id="run-1",
        lead_id=lead_id,
        mode="urls",
        limit=2,
    )
    second = store.read(
        project_id="proj-1",
        run_id="run-1",
        lead_id=lead_id,
        mode="urls",
        cursor=first["next_cursor"],
        limit=2,
    )

    ids = [
        candidate["candidate_id"]
        for candidate in first["candidates"] + second["candidates"]
    ]
    assert len(ids) == len(set(ids)) == 3
    assert second["next_cursor"] is None
    assert len(json.dumps(first).encode()) <= 16384


def test_scan_store_reuses_only_complete_matching_scan_and_links_contexts(tmp_path):
    from polymerhus.recon.js_acquisition.scan_store import ScanStore

    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    source = tmp_path / "source.js"
    source.write_bytes(b"const reuse = true;\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    first_lead, _ = _acquired_lead(
        root,
        source=source,
        digest=digest,
        context_ref="account-1",
        pod_id="pod-1",
        url="https://app.example.test/a.js",
    )
    second_lead, _ = _acquired_lead(
        root,
        source=source,
        digest=digest,
        context_ref="account-2",
        pod_id="pod-2",
        url="https://app.example.test/b.js",
    )
    result = _scan_result(
        source,
        digest,
        urls=[{"url": "https://api.example.test/shared"}],
        secrets=[],
    )
    store = ScanStore(root=root)
    store.submit_mode(
        project_id="proj-1",
        run_id="run-1",
        lead_id=first_lead,
        context_ref="account-1",
        result=result,
        mode="urls",
    )

    partial_reuse = store.find_reusable(
        project_id="proj-1",
        run_id="run-1",
        source_sha256=digest,
        binary=result["binary"],
        options=result["options"],
        pattern_fingerprint=result["pattern_fingerprint"],
    )
    assert partial_reuse is None

    store.submit_mode(
        project_id="proj-1",
        run_id="run-1",
        lead_id=first_lead,
        context_ref="account-1",
        result=result,
        mode="secrets",
    )
    reusable = store.find_reusable(
        project_id="proj-1",
        run_id="run-1",
        source_sha256=digest,
        binary=result["binary"],
        options=result["options"],
        pattern_fingerprint=result["pattern_fingerprint"],
    )
    assert reusable["scan_key"] == result["scan_key"]

    linked = store.link_lead(
        project_id="proj-1",
        run_id="run-1",
        lead_id=second_lead,
        context_ref="account-2",
        scan_key=result["scan_key"],
    )
    manifest = (
        root
        / "proj-1"
        / "recon"
        / "js_analysis"
        / "run-1"
        / "manifest.json"
    )
    private = json.loads(manifest.read_text())
    assert linked["status"] == "complete"
    assert private["scans"][result["scan_key"]]["context_links"] == [
        {"context_ref": "account-1", "lead_id": first_lead},
        {"context_ref": "account-2", "lead_id": second_lead},
    ]
    assert private["leads"][second_lead]["status"] == "acquired"

    changed = store.find_reusable(
        project_id="proj-1",
        run_id="run-1",
        source_sha256=digest,
        binary=result["binary"],
        options=result["options"],
        pattern_fingerprint="changed-patterns",
    )
    assert changed is None


def test_scan_store_rejects_missing_or_mismatched_acquisition(tmp_path):
    from polymerhus.recon.js_acquisition.scan_store import ScanStore, ScanStoreError

    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    source = tmp_path / "source.js"
    source.write_bytes(b"const missing = true;\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    lead_id, _ = _acquired_lead(root, source=source, digest=digest)
    result = _scan_result(source, digest, urls=[])
    tampered = json.loads(json.dumps(result))
    tampered["source"]["sha256"] = "0" * 64
    store = ScanStore(root=root)

    with pytest.raises(ScanStoreError) as mismatch:
        store.submit_mode(
            project_id="proj-1",
            run_id="run-1",
            lead_id=lead_id,
            context_ref="account-1",
            result=tampered,
            mode="urls",
        )
    assert mismatch.value.reason == "scan_key_mismatch"

    with pytest.raises(ScanStoreError) as missing:
        store.link_lead(
            project_id="proj-1",
            run_id="run-1",
            lead_id=lead_id,
            context_ref="account-1",
            scan_key="missing",
        )
    assert missing.value.reason == "scan_missing"


def test_scan_store_read_shrinks_to_full_16k_envelope_with_cursor(tmp_path):
    from polymerhus.recon.js_acquisition.scan_store import ScanStore

    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    source = tmp_path / "source.js"
    source.write_bytes(b"const envelope = true;\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    lead_id, _ = _acquired_lead(root, source=source, digest=digest)
    result = _scan_result(
        source,
        digest,
        urls=[
            {
                "url": "https://api.example.test/"
                + f"{index}/" + "/".join("a" for _ in range(2200)),
            }
            for index in range(8)
        ],
    )
    store = ScanStore(root=root)
    store.submit_mode(
        project_id="proj-1",
        run_id="run-1",
        lead_id=lead_id,
        context_ref="account-1",
        result=result,
        mode="urls",
    )

    page = store.read(
        project_id="proj-1",
        run_id="run-1",
        lead_id=lead_id,
        mode="urls",
        limit=10,
    )

    assert len(json.dumps(page, separators=(",", ":")).encode()) <= 16384
    assert page["next_cursor"]
    assert len(page["candidates"]) < 8
    runner_envelope = {
        "returncode": 0,
        "result": page,
    }
    assert len(json.dumps(runner_envelope, separators=(",", ":")).encode()) <= 16384


def test_scan_store_concurrent_retries_converge_on_one_candidate_set(tmp_path):
    from polymerhus.recon.js_acquisition.scan_store import ScanStore

    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    source = tmp_path / "source.js"
    source.write_bytes(b"const concurrent = true;\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    first_lead, _ = _acquired_lead(
        root,
        source=source,
        digest=digest,
        context_ref="account-1",
        pod_id="pod-1",
        url="https://app.example.test/a.js",
    )
    second_lead, _ = _acquired_lead(
        root,
        source=source,
        digest=digest,
        context_ref="account-2",
        pod_id="pod-2",
        url="https://app.example.test/b.js",
    )
    result = _scan_result(
        source,
        digest,
        urls=[{"url": "https://api.example.test/concurrent"}],
    )
    store = ScanStore(root=root)

    def submit(lead_id: str, context_ref: str):
        return store.submit_mode(
            project_id="proj-1",
            run_id="run-1",
            lead_id=lead_id,
            context_ref=context_ref,
            result=result,
            mode="urls",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(
            pool.map(
                lambda item: submit(*item),
                [
                    (first_lead, "account-1"),
                    (second_lead, "account-2"),
                ],
            )
        )

    scan_key = result["scan_key"]
    candidate_file = (
        root
        / "proj-1"
        / "recon"
        / "js_analysis"
        / "run-1"
        / "scans"
        / f"{scan_key}.jsonl"
    )
    assert {item["scan_key"] for item in outcomes} == {scan_key}
    assert len(candidate_file.read_text().splitlines()) == 1


def test_scan_store_missing_or_corrupt_candidate_file_is_not_zero_success(
    tmp_path,
):
    from polymerhus.recon.js_acquisition.scan_store import ScanStore, ScanStoreError

    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    source = tmp_path / "source.js"
    source.write_bytes(b"const candidateIntegrity = true;\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    lead_id, _ = _acquired_lead(root, source=source, digest=digest)
    result = _scan_result(
        source,
        digest,
        urls=[{"url": "https://api.example.test/integrity"}],
        secrets=[],
    )
    store = ScanStore(root=root)
    store.submit_mode(
        project_id="proj-1",
        run_id="run-1",
        lead_id=lead_id,
        context_ref="account-1",
        result=result,
        mode="urls",
    )
    store.submit_mode(
        project_id="proj-1",
        run_id="run-1",
        lead_id=lead_id,
        context_ref="account-1",
        result=result,
        mode="secrets",
    )
    path = (
        root
        / "proj-1"
        / "recon"
        / "js_analysis"
        / "run-1"
        / "scans"
        / f"{result['scan_key']}.jsonl"
    )

    path.unlink()
    assert store.find_reusable(
        project_id="proj-1",
        run_id="run-1",
        source_sha256=digest,
        binary=result["binary"],
        options=result["options"],
        pattern_fingerprint=result["pattern_fingerprint"],
    ) is None

    repaired = store.submit_mode(
        project_id="proj-1",
        run_id="run-1",
        lead_id=lead_id,
        context_ref="account-1",
        result=result,
        mode="urls",
    )
    assert repaired["idempotent"] is False
    assert path.is_file()
    assert store.read(
        project_id="proj-1",
        run_id="run-1",
        lead_id=lead_id,
        mode="urls",
    )["candidates"][0]["mode"] == "urls"

    path.unlink()
    with pytest.raises(ScanStoreError) as missing:
        store.read(
            project_id="proj-1",
            run_id="run-1",
            lead_id=lead_id,
            mode="urls",
        )
    assert missing.value.reason == "scan_candidate_file_missing"

    path.write_text("{corrupt\n")
    with pytest.raises(ScanStoreError) as corrupt:
        store.read(
            project_id="proj-1",
            run_id="run-1",
            lead_id=lead_id,
            mode="urls",
        )
    assert corrupt.value.reason == "scan_candidate_file_invalid"
