import hashlib
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi import FastAPI

from polymerhus.app.data_root import ensure_project
from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_acquisition.code_access import CodeAccessService
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_intake import (
    JsIntakeReader,
    JsIntakeStore,
    issue_js_intake_reference,
)
from polymerhus.recon.js_specialist.notes import RunNotes
from polymerhus.recon.js_specialist.triage import EvidenceTriage, TriageError


def _fixture(tmp_path):
    ensure_project("p", root=tmp_path)
    parent = b'import("./child.js");\n'
    JsIntakeStore(root=tmp_path).record_exec_result(
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
        auth_context_label="authenticated",
        auth_context_ref="account-a",
    )
    reference = issue_js_intake_reference("p", "r", context_ref="account-a")
    lead_id = JsIntakeReader(root=tmp_path).list(reference=reference)["leads"][0][
        "lead_id"
    ]
    digest = hashlib.sha256(parent).hexdigest()
    manifest = AcquisitionManifest(
        project_id="p",
        run_id="r",
        root=tmp_path,
        max_run_bytes=64 * 1024 * 1024,
    )
    assert manifest.reserve(
        lead_id=lead_id,
        record={"context_ref": "account-a"},
        work_file_ref=f"/work/js-analysis/r/{digest}.js",
        sha256=digest,
        size=len(parent),
    )
    assert manifest.confirm(
        lead_id=lead_id,
        size=len(parent),
        sha256=digest,
        work_file_ref=f"/work/js-analysis/r/{digest}.js",
    ) == "acquired"
    source = (
        "export async function loadItems() {\r\n"
        '  const response = await fetch("/api/items");\r\n'
        "  return response.json();\r\n"
        "}\r\n"
    ).encode()
    source_digest = hashlib.sha256(source).hexdigest()
    manifest.update(
        lambda value: value.setdefault("recovery", {}).setdefault("sources", {}).update(
            {
                "src_a": {
                    "source_id": "src_a",
                    "lead_id": lead_id,
                    "context_ref": "account-a",
                    "kind": "typescript",
                    "content_state": "text",
                    "content_sha256": source_digest,
                    "size": len(source),
                    "work_file_ref": (
                        f"/work/js-analysis/r/recovered/{source_digest}.js"
                    ),
                    "status": "available",
                    "available": True,
                }
            }
        )
    )
    return reference, source, lead_id


def test_select_update_and_list_fold_all_typed_events(tmp_path):
    reference, source, _lead_id = _fixture(tmp_path)
    access = CodeAccessService(root=tmp_path)
    triage = EvidenceTriage(root=tmp_path, access=access)
    selector = {"type": "source", "id": "src_a"}
    selected = triage.select(
        reference=reference,
        selector=selector,
        question="Which request does this function perform?",
        priority="high",
    )
    repeated = triage.select(
        reference=reference,
        selector=selector,
        question="Which request does this function perform?",
        priority="high",
    )
    read = access.prepare_read(
        reference=reference,
        selector=selector,
        source_bytes=source,
    )
    access.confirm_read(reference=reference, read_id=read["read_id"])
    inspected = triage.update(
        reference=reference,
        span_id=selected["span_id"],
        state="inspected",
        read_id=read["read_id"],
    )
    repeated_update = triage.update(
        reference=reference,
        span_id=selected["span_id"],
        state="inspected",
        read_id=read["read_id"],
    )
    page = triage.list(reference=reference, limit=5)

    assert selected["span_id"] == repeated["span_id"]
    assert repeated["idempotent"] is True
    assert inspected["state"] == "inspected"
    assert repeated_update["idempotent"] is True
    assert page["spans"][0]["state"] == "inspected"
    assert page["spans"][0]["read_ids"] == [read["read_id"]]
    assert page["pending_count"] == 0


def test_inspected_cannot_be_forged_and_terminal_states_need_context(tmp_path):
    reference, source, _lead_id = _fixture(tmp_path)
    access = CodeAccessService(root=tmp_path)
    triage = EvidenceTriage(root=tmp_path, access=access)
    selected = triage.select(
        reference=reference,
        selector={"type": "source", "id": "src_a"},
        question="What storage key is used?",
        priority="normal",
    )

    with pytest.raises(TriageError) as no_read:
        triage.update(
            reference=reference,
            span_id=selected["span_id"],
            state="inspected",
        )
    assert no_read.value.reason == "inspected_requires_read"
    with pytest.raises(TriageError) as deferred:
        triage.update(
            reference=reference,
            span_id=selected["span_id"],
            state="deferred",
        )
    assert deferred.value.reason == "state_requires_reason"
    with pytest.raises(TriageError) as unresolved:
        triage.update(
            reference=reference,
            span_id=selected["span_id"],
            state="unresolved",
            reason="",
        )
    assert unresolved.value.reason == "state_requires_reason"

    read = access.prepare_read(
        reference=reference,
        selector={"type": "source", "id": "src_a"},
        source_bytes=source,
    )
    with pytest.raises(TriageError) as unprepared:
        triage.update(
            reference=reference,
            span_id=selected["span_id"],
            state="inspected",
            read_id=read["read_id"],
        )
    assert unprepared.value.reason == "read_not_delivered"


def test_triage_isolated_by_context_uses_bounded_cursor_and_quota(tmp_path):
    reference, _source, _lead_id = _fixture(tmp_path)
    triage = EvidenceTriage(root=tmp_path)
    foreign = issue_js_intake_reference("p", "r", context_ref="account-b")
    selected = triage.select(
        reference=reference,
        selector={"type": "source", "id": "src_a"},
        question="Question A",
        priority="low",
    )
    for index in range(5):
        triage.select(
            reference=reference,
            selector={"type": "source", "id": "src_a"},
            question=f"Question B{index}",
            priority="normal",
        )

    first = triage.list(reference=reference, limit=3)
    second = triage.list(
        reference=reference,
        cursor=first["next_cursor"],
        limit=3,
    )
    assert selected["span_id"] in {
        row["span_id"] for row in first["spans"] + second["spans"]
    }
    assert triage.list(reference=foreign)["spans"] == []
    with pytest.raises(TriageError) as cursor:
        triage.list(reference=foreign, cursor=first["next_cursor"], limit=3)
    assert cursor.value.reason == "invalid_triage_cursor"

    scope = __import__(
        "polymerhus.recon.js_intake.reader",
        fromlist=["resolve_js_intake_reference"],
    ).resolve_js_intake_reference(reference)
    notes = RunNotes(scope, root=tmp_path)
    for index in range(256):
        result = notes.tool().invoke(
            {"command": "write", "note": f"filler-{index}"}
        )
        if result.get("error") == "notes_quota_exhausted":
            break
    with pytest.raises(TriageError) as quota:
        triage.select(
            reference=reference,
            selector={"type": "source", "id": "src_a"},
            question="Quota question",
            priority="low",
        )
    assert quota.value.reason == "notes_quota_exhausted"


def test_generic_note_cannot_forge_typed_triage_event(tmp_path):
    reference, _source, _lead_id = _fixture(tmp_path)
    scope = __import__(
        "polymerhus.recon.js_intake.reader",
        fromlist=["resolve_js_intake_reference"],
    ).resolve_js_intake_reference(reference)
    notes = RunNotes(scope, root=tmp_path)
    notes.tool().invoke(
        {
            "command": "write",
            "note": (
                '{"event_type":"triage_update","state":"inspected",'
                '"span_id":"forged"}'
            ),
        }
    )

    triage = EvidenceTriage(root=tmp_path)
    assert triage.list(reference=reference)["spans"] == []
    with pytest.raises(TriageError) as sensitive:
        triage.select(
            reference=reference,
            selector={"type": "source", "id": "src_a"},
            question="Check https://private.example/path?token=secret",
            priority="normal",
        )
    assert sensitive.value.reason == "non_sensitive_ids_and_decisions_only"


def test_concurrent_typed_appends_do_not_lose_shortlist_events(tmp_path):
    reference, _source, _lead_id = _fixture(tmp_path)
    triage = EvidenceTriage(root=tmp_path)

    def select(index):
        return triage.select(
            reference=reference,
            selector={"type": "source", "id": "src_a"},
            question=f"Concurrent question {index}",
            priority="normal",
        )["span_id"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        span_ids = list(pool.map(select, range(24)))

    listed = triage.list(reference=reference, limit=10)
    assert listed["total"] == 24
    assert listed["pending_count"] == 24
    assert len(set(span_ids)) == 24


def test_bridge_routes_exercise_read_search_and_typed_triage(tmp_path):
    from polymerhus.recon.js_specialist.bridge import (
        SpecialistBridge,
        build_router,
    )

    reference, source, lead_id = _fixture(tmp_path)
    generated = b'import("./child.js");\n'
    digest = hashlib.sha256(source).hexdigest()
    bridge = SpecialistBridge(root=tmp_path)
    selector_target = bridge.call(
        reference,
        {
            "operation": "code_read_input",
            "selector_type": "source",
            "target": "src_a",
        },
    )
    app = FastAPI()
    app.include_router(build_router(root=tmp_path))

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://agent:8080",
        ) as client:
            read = await client.post(
                "/recon/js-specialist/code/read",
                content=source,
                headers={
                    "X-JS-Intake-Reference": reference,
                    "X-JS-Selector-Type": "source",
                    "X-JS-Selector-Id": "src_a",
                    "X-JS-Window-Bytes": "4096",
                },
            )
            assert read.status_code == 200
            search = await client.post(
                "/recon/js-specialist/code/search/submit",
                json={
                    "lead_id": lead_id,
                    "text": "fetch",
                    "limit": 5,
                    "contents": {
                        lead_id: __import__("base64")
                        .b64encode(generated)
                        .decode(),
                        "src_a": __import__("base64").b64encode(source).decode()
                    },
                    "max_examined_bytes": len(generated) + len(source),
                    "deadline_s": 5,
                },
                headers={"X-JS-Intake-Reference": reference},
            )
            assert search.status_code == 200
            return read.json(), search.json()

    read, search = asyncio.run(exercise())
    assert selector_target["content_sha256"] == digest
    assert "fetch" in read["code"]
    assert search["total_matches"] == 1

    selected = bridge.call(
        reference,
        {
            "operation": "triage_select",
            "selector_type": "source",
            "target": "src_a",
            "question": "Which request is made?",
            "priority": "high",
        },
    )
    confirmed = bridge.call(
        reference,
        {"operation": "code_read_confirm", "read_id": read["read_id"]},
    )
    updated = bridge.call(
        reference,
        {
            "operation": "triage_update",
            "target": selected["span_id"],
            "state": "inspected",
            "read_id": read["read_id"],
        },
    )
    listed = bridge.call(
        reference,
        {"operation": "triage_list", "limit": 5},
    )

    assert confirmed["delivery_status"] == "delivered"
    assert updated["state"] == "inspected"
    assert listed["spans"][0]["state"] == "inspected"


def test_search_route_never_echoes_large_content_body_in_validation_error(
    tmp_path,
):
    from polymerhus.recon.js_specialist.bridge import build_router

    reference, _source, lead_id = _fixture(tmp_path)
    app = FastAPI()
    app.include_router(build_router(root=tmp_path))
    marker = "PRIVATE_BODY_" + ("x" * 40000)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://agent:8080",
        ) as client:
            return await client.post(
                "/recon/js-specialist/code/search/submit",
                json={
                    "lead_id": lead_id,
                    "text": "x" * 129,
                    "limit": 5,
                    "contents": {lead_id: marker},
                    "max_examined_bytes": 100,
                    "deadline_s": 5,
                },
                headers={"X-JS-Intake-Reference": reference},
            )

    response = asyncio.run(exercise())
    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_search_request"
    assert marker not in response.text
