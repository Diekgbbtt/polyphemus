import hashlib
import json
from pathlib import Path

import pytest

from polymerhus.app.data_root import ensure_project, project_dir
from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_acquisition.code_access import (
    CodeAccessError,
    CodeAccessService,
)
from polymerhus.recon.js_acquisition.code_search import CodeSearchService
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_acquisition.structure import parse_structure_bytes
from polymerhus.recon.js_acquisition.structure_store import StructureStore
from polymerhus.recon.js_intake import (
    JsIntakeReader,
    JsIntakeStore,
    issue_js_intake_reference,
)


def _lead(root: Path, source: bytes, *, context: str = "account-a") -> tuple[str, str]:
    ensure_project("p", root=root)
    JsIntakeStore(root=root).record_exec_result(
        project_id="p",
        run_id="r",
        pod_id="pod",
        producer="katana",
        input_context_ref="ctx",
        exec_result=ExecResult(
            stdout=json.dumps(
                {
                    "request": {"endpoint": "https://app.test/app.js"},
                    "response": {
                        "status_code": 200,
                        "headers": {"Content-Type": "application/javascript"},
                    },
                }
            ),
            stderr="",
            returncode=0,
        ),
        auth_context_label="authenticated" if context else "anonymous",
        auth_context_ref=context or None,
    )
    reference = issue_js_intake_reference(
        "p",
        "r",
        context_ref=context,
    )
    lead_id = JsIntakeReader(root=root).list(reference=reference)["leads"][0][
        "lead_id"
    ]
    digest = hashlib.sha256(source).hexdigest()
    work_ref = f"/work/js-analysis/r/{digest}.js"
    manifest = AcquisitionManifest(
        project_id="p",
        run_id="r",
        root=root,
        max_run_bytes=64 * 1024 * 1024,
    )
    assert manifest.reserve(
        lead_id=lead_id,
        record={"context_ref": context},
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
    return lead_id, reference


def _item(root: Path, source: bytes, lead_id: str, reference: str) -> str:
    store = StructureStore(root=root)
    store.store_index(
        project_id="p",
        run_id="r",
        context_ref="account-a",
        lead_id=lead_id,
        source_bytes=source,
        parsed=parse_structure_bytes(source),
        parent_final_url="https://app.test/app.js",
    )
    return store.list_items(
        project_id="p",
        run_id="r",
        context_ref="account-a",
        lead_id=lead_id,
        kind="import",
    )["items"][0]["item_id"]


def test_reads_verified_item_window_with_unicode_cursor_and_receipt(tmp_path):
    source = (
        "const emoji = '😀';\r\n"
        'import("./child.js");\r\n'
        f"const tail = '{'x' * 9000}';\r\n"
    ).encode()
    lead_id, reference = _lead(tmp_path, source)
    item_id = _item(tmp_path, source, lead_id, reference)
    service = CodeAccessService(root=tmp_path)

    target = service.read_target(
        reference=reference,
        selector={"type": "item", "id": item_id},
    )
    first = service.prepare_read(
        reference=reference,
        selector={"type": "item", "id": item_id},
        source_bytes=source,
        window_bytes=8,
    )
    second = service.prepare_read(
        reference=reference,
        selector={"type": "item", "id": item_id},
        source_bytes=source,
        cursor=first["next_cursor"],
        window_bytes=8,
    )
    confirmed = service.confirm_read(reference=reference, read_id=first["read_id"])

    assert target["work_file_ref"].endswith(".js")
    assert first["content_sha256"] == hashlib.sha256(source).hexdigest()
    assert first["original_end"] <= target["range_end"]
    assert first["delivery_status"] == "prepared"
    assert second["original_start"] >= first["original_end"]
    assert confirmed["delivery_status"] == "delivered"
    assert service.validate_read_for_focus(
        reference=reference,
        read_id=first["read_id"],
        focus={
            "content_sha256": first["content_sha256"],
            "start_byte": first["original_start"],
            "end_byte": first["original_end"],
        },
    )


def test_access_rejects_cross_context_tampering_stale_items_and_bad_encoding(tmp_path):
    source = b'import("./child.js");\n'
    lead_id, reference = _lead(tmp_path, source)
    item_id = _item(tmp_path, source, lead_id, reference)
    service = CodeAccessService(root=tmp_path)
    foreign = issue_js_intake_reference("p", "r", context_ref="account-b")

    with pytest.raises(CodeAccessError) as scope:
        service.read_target(
            reference=foreign,
            selector={"type": "item", "id": item_id},
        )
    assert scope.value.reason in {"item_not_found", "item_outside_context"}

    with pytest.raises(CodeAccessError) as tampered:
        service.prepare_read(
            reference=reference,
            selector={"type": "item", "id": item_id},
            source_bytes=source + b" ",
        )
    assert tampered.value.reason == "content_mismatch"

    AcquisitionManifest(
        project_id="p",
        run_id="r",
        root=tmp_path,
        max_run_bytes=64 * 1024 * 1024,
    ).update(
        lambda value: value["leads"][lead_id].update(
            {"sha256": "f" * 64, "size": len(source) + 1}
        )
    )
    with pytest.raises(CodeAccessError) as stale:
        service.read_target(
            reference=reference,
            selector={"type": "item", "id": item_id},
        )
    assert stale.value.reason == "item_stale"

    AcquisitionManifest(
        project_id="p",
        run_id="r",
        root=tmp_path,
        max_run_bytes=64 * 1024 * 1024,
    ).update(
        lambda value: value["leads"][lead_id].update(
            {
                "sha256": hashlib.sha256(source).hexdigest(),
                "size": len(source),
            }
        )
    )
    invalid = b"\xff\xfe\x00"
    with pytest.raises(CodeAccessError) as encoding:
        service.prepare_read(
            reference=reference,
            selector={"type": "item", "id": item_id},
            source_bytes=invalid,
        )
    assert encoding.value.reason in {"content_mismatch", "unsupported_encoding"}


def test_recovered_source_is_readable_without_claiming_javascript(tmp_path):
    parent = b'import("./child.js");\n'
    lead_id, reference = _lead(tmp_path, parent)
    content = "export const 安全 = true;\r\nconst password = '秘密';\r\n".encode()
    digest = hashlib.sha256(content).hexdigest()
    work_ref = f"/work/js-analysis/r/recovered/{digest}.js"
    object_ref = f"recovered/{digest}.js"
    object_path = project_dir("p", "recon/js_analysis", root=tmp_path) / "r" / object_ref
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(content)
    AcquisitionManifest(
        project_id="p",
        run_id="r",
        root=tmp_path,
        max_run_bytes=64 * 1024 * 1024,
    ).update(
        lambda value: value.setdefault("recovery", {}).setdefault("sources", {}).update(
            {
                "src_a": {
                    "source_id": "src_a",
                    "lead_id": lead_id,
                    "context_ref": "account-a",
                    "kind": "typescript",
                    "content_state": "text",
                    "content_sha256": digest,
                    "size": len(content),
                    "work_file_ref": work_ref,
                    "object_ref": object_ref,
                    "status": "available",
                    "available": True,
                }
            }
        )
    )
    service = CodeAccessService(root=tmp_path)

    target = service.read_target(
        reference=reference,
        selector={"type": "source", "id": "src_a"},
    )
    window = service.prepare_read(
        reference=reference,
        selector={"type": "source", "id": "src_a"},
        source_bytes=content,
    )

    assert target["kind"] == "typescript"
    assert target["range_start"] == 0
    assert "安全" in window["code"]
    assert "秘密" not in window["code"]


def test_empty_source_and_selector_exclusivity(tmp_path):
    parent = b'import("./child.js");\n'
    lead_id, reference = _lead(tmp_path, parent)
    empty = b""
    digest = hashlib.sha256(empty).hexdigest()
    AcquisitionManifest(
        project_id="p",
        run_id="r",
        root=tmp_path,
        max_run_bytes=64 * 1024 * 1024,
    ).update(
        lambda value: value.setdefault("recovery", {}).setdefault("sources", {}).update(
            {
                "src_empty": {
                    "source_id": "src_empty",
                    "lead_id": lead_id,
                    "context_ref": "account-a",
                    "kind": "unknown",
                    "content_state": "empty",
                    "content_sha256": digest,
                    "size": 0,
                    "work_file_ref": f"/work/js-analysis/r/recovered/{digest}.js",
                    "status": "available",
                    "available": True,
                }
            }
        )
    )
    service = CodeAccessService(root=tmp_path)
    empty_window = service.prepare_read(
        reference=reference,
        selector={"type": "source", "id": "src_empty"},
        source_bytes=empty,
    )

    assert empty_window["code"] == ""
    assert empty_window["content_state"] == "empty"
    with pytest.raises(CodeAccessError) as selectors:
        service.prepare_read(
            reference=reference,
            selector={"type": "item", "id": "a", "source_id": "b"},
            source_bytes=parent,
        )
    assert selectors.value.reason == "exactly_one_selector_required"


def test_match_selector_uses_private_search_snapshot_and_surrounding_window(tmp_path):
    source = (
        "const before = true;\n"
        'const result = fetch("/api/items");\n'
        "const after = true;\n"
    ).encode()
    lead_id, reference = _lead(tmp_path, source)
    search = CodeSearchService(root=tmp_path).search_from_contents(
        reference=reference,
        lead_id=lead_id,
        text='fetch("/api/items")',
        contents={lead_id: source},
        limit=5,
    )
    match_id = search["matches"][0]["match_id"]
    service = CodeAccessService(root=tmp_path)

    target = service.read_target(
        reference=reference,
        selector={"type": "match", "id": match_id},
    )
    window = service.prepare_read(
        reference=reference,
        selector={"type": "match", "id": match_id},
        source_bytes=source,
    )

    assert target["range_start"] <= search["matches"][0]["start_byte"]
    assert target["range_end"] >= search["matches"][0]["end_byte"]
    assert 'fetch("/api/items")' in window["code"]
    assert window["selector"] == {"type": "match", "id": match_id}
