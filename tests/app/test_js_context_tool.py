"""Native read-only js_context tool contract over the real publication store."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from langchain_core.messages import ToolMessage

from polymerhus.app.js_context.store import JsContextStore
from polymerhus.app.js_context.tool import (
    JS_CONTEXT_CONTRACT,
    MAX_RESPONSE_BYTES,
    build_js_context_tool,
)
from polymerhus.recon.control.js_context_writer import JsContextWriter
from polymerhus.recon.js_intake import issue_js_intake_reference
from tests.app.test_js_context_store import (
    _context_id,
    _document,
    _paths,
)
from tests.recon.test_js_context_writer import (
    FakeAccess,
    FakeNotes,
    FakeRetention,
    _event,
    _link,
    _receipt,
    _snapshot,
)


PROJECT = "project-a"


def _seed(
    tmp_path: Path,
    *,
    run_id: str = "run-1",
    context_id: str | None = None,
    behavior_count: int = 1,
) -> tuple[JsContextStore, dict, str]:
    document = _document(run_id=run_id, behavior_count=behavior_count)
    if context_id is not None:
        document["context"]["auth_ref"] = context_id
    store = JsContextStore(root_dir=tmp_path)
    assert store.publish(document)["status"] == "published"
    return store, document, _context_id(document)


def _bytes(value: dict) -> int:
    return len(
        json.dumps(
            value,
            ensure_ascii=False,
        ).encode("utf-8")
    )


def _invoke_tool_call(tool, args: dict, *, call_id: str = "call-1"):
    call = {
        "name": "js_context",
        "args": args,
        "id": call_id,
        "type": "tool_call",
    }
    output = tool.invoke(call)
    if isinstance(output, ToolMessage):
        message = output
    else:
        message = ToolMessage(
            content=json.dumps(
                output,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            tool_call_id=call_id,
            name=tool.name,
        )
    return message, json.loads(message.content)


def test_tool_name_schema_and_project_binding(tmp_path: Path) -> None:
    store, document, _ = _seed(tmp_path)
    tool = build_js_context_tool(PROJECT, store)

    assert tool.name == "js_context"
    assert set(tool.args) == {
        "command",
        "context_id",
        "selector",
        "section",
        "limit",
        "cursor",
    }
    assert "project_id" not in tool.args
    assert "path" not in tool.args
    assert "value" not in tool.args
    assert tool.description == JS_CONTEXT_CONTRACT

    out = tool.invoke({"command": "list"})
    assert out["ok"] is True
    assert out["publications"][0]["run_id"] == document["context"]["run_id"]


def test_real_tool_call_and_tool_message_boundary(tmp_path: Path) -> None:
    store, _, _ = _seed(tmp_path)
    tool = build_js_context_tool(PROJECT, store)

    message, payload = _invoke_tool_call(
        tool,
        {"command": "list", "limit": 5},
    )

    assert message.name == "js_context"
    assert message.status != "error"
    assert payload["ok"] is True
    assert _bytes(payload) <= MAX_RESPONSE_BYTES


def test_factory_defaults_project_lazily(tmp_path: Path, monkeypatch) -> None:
    from polymerhus.app.config import config

    monkeypatch.setattr(config, "PROJECT_ID", "project-cfg")
    store = JsContextStore(root_dir=tmp_path)
    document = _document(project_id="project-cfg", run_id="run-1")
    store.publish(document)
    tool = build_js_context_tool(store=store)

    out = tool.invoke({"command": "list"})

    assert out["ok"] is True
    assert any(
        item["context_id"] == _context_id(document)
        for item in out["publications"]
    )


def test_read_requires_explicit_context_and_selector(tmp_path: Path) -> None:
    store, _, context_id = _seed(tmp_path)
    tool = build_js_context_tool(PROJECT, store)

    no_context = tool.invoke({"command": "read", "selector": "current"})
    no_selector = tool.invoke(
        {"command": "read", "context_id": context_id}
    )

    assert no_context == {
        "ok": False,
        "error": "invalid_arguments",
    }
    assert no_selector == {
        "ok": False,
        "error": "invalid_arguments",
    }


def test_project_extra_write_and_path_arguments_are_refused(
    tmp_path: Path,
) -> None:
    store, _, context_id = _seed(tmp_path)
    tool = build_js_context_tool(PROJECT, store)

    assert tool.invoke(
        {"command": "list", "project_id": "project-b"}
    ) == {"ok": False, "error": "invalid_arguments"}
    assert tool.invoke(
        {"command": "read", "context_id": context_id, "path": "../x"}
    ) == {"ok": False, "error": "invalid_arguments"}
    assert tool.invoke(
        {
            "command": "write",
            "context_id": context_id,
            "selector": "current",
            "value": {},
        }
    ) == {"ok": False, "error": "invalid_arguments"}
    assert tool.invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "../run",
        }
    ) == {"ok": False, "error": "invalid_arguments"}


def test_list_is_compact_project_scoped_and_paginated(tmp_path: Path) -> None:
    store = JsContextStore(root_dir=tmp_path)
    for index in range(7):
        document = _document(
            project_id=PROJECT,
            run_id=f"run-{index}",
            auth_ref="account-a",
        )
        store.publish(document)
    other = _document(project_id="project-b", run_id="foreign")
    store.publish(other)
    tool = build_js_context_tool(PROJECT, store)

    first = tool.invoke({"command": "list"})
    second = tool.invoke(
        {"command": "list", "cursor": first["next_cursor"]}
    )

    assert first["ok"] is True
    assert len(first["publications"]) == 5
    assert first["next_cursor"]
    assert len(second["publications"]) == 2
    assert second["next_cursor"] is None
    assert "gaps" not in first["publications"][0]["coverage"]
    assert first["publications"][0]["coverage"]["gap_count"] == 0
    assert all(
        item["run_id"].startswith("run-")
        for item in first["publications"] + second["publications"]
    )
    assert _bytes(first) <= MAX_RESPONSE_BYTES


def test_list_context_filter_does_not_cross_auth_contexts(
    tmp_path: Path,
) -> None:
    store = JsContextStore(root_dir=tmp_path)
    first = _document(auth_ref="account-a")
    second = _document(auth_ref="account-b")
    store.publish(first)
    store.publish(second)
    tool = build_js_context_tool(PROJECT, store)
    first_context = _context_id(first)

    filtered = tool.invoke(
        {
            "command": "list",
            "context_id": first_context,
            "limit": 10,
        }
    )

    assert filtered["ok"] is True
    assert {
        item["context_id"] for item in filtered["publications"]
    } == {first_context}
    assert {
        item["auth_ref"] for item in filtered["publications"]
    } == {"account-a"}


def test_historical_current_and_all_sections(tmp_path: Path) -> None:
    store, first, context_id = _seed(tmp_path, run_id="run-1")
    second = _document(run_id="run-2")
    second["behaviors"][0]["steps"][0]["text"] = "Second run only."
    store.publish(second)
    tool = build_js_context_tool(PROJECT, store)

    historical = tool.invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "run-1",
            "section": "behaviors",
        }
    )
    current = tool.invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "current",
            "section": "behaviors",
        }
    )
    metadata = tool.invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "current",
            "section": "metadata",
        }
    )
    context = tool.invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "run-1",
            "section": "context",
        }
    )
    evidence = tool.invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "run-1",
            "section": "evidence",
        }
    )

    assert historical["items"][0]["steps"][0]["text"] == "Step text a."
    assert current["items"][0]["steps"][0]["text"] == "Second run only."
    assert metadata["publication"]["run_id"] == "run-2"
    assert context["context"]["coverage"]["status"] == "complete"
    assert evidence["items"][0]["availability"] == "retained_unverified"


def test_missing_and_corrupt_data_are_not_successful_empty_reads(
    tmp_path: Path,
) -> None:
    store, document, context_id = _seed(tmp_path)
    tool = build_js_context_tool(PROJECT, store)

    missing = tool.invoke(
        {
            "command": "read",
            "context_id": "jsctx_" + "0" * 40,
            "selector": "current",
        }
    )
    yaml_path, current_path = _paths(tmp_path, document)
    current_path.write_text("{bad", encoding="utf-8")
    current_corrupt = tool.invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "current",
        }
    )
    yaml_path.write_text("{bad", encoding="utf-8")
    corrupt = tool.invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "run-1",
        }
    )

    assert missing == {"ok": False, "error": "missing"}
    assert current_corrupt == {"ok": False, "error": "corrupt"}
    assert corrupt == {"ok": False, "error": "corrupt"}


def test_large_context_gaps_paginate_without_record_cuts(tmp_path: Path) -> None:
    store = JsContextStore(root_dir=tmp_path)
    document = _document(run_id="run-1")
    gaps = [
        f"gap_{index:03d}_" + ("é" * 80)
        for index in range(80)
    ]
    document["context"]["coverage"] = {
        "status": "partial",
        "gaps": gaps,
    }
    store.publish(document)
    context_id = _context_id(document)
    tool = build_js_context_tool(PROJECT, store)

    delivered = []
    cursor = None
    pages = 0
    while True:
        args = {
            "command": "read",
            "context_id": context_id,
            "selector": "run-1",
            "section": "context",
        }
        if cursor:
            args["cursor"] = cursor
        page = tool.invoke(args)
        pages += 1
        assert page["ok"] is True
        assert page["context"]["coverage"]["gap_count"] == len(gaps)
        assert len(page["gaps"]) <= 5
        assert _bytes(page) <= MAX_RESPONSE_BYTES
        delivered.extend(page["gaps"])
        cursor = page["gap_page"]["next_cursor"]
        if cursor is None:
            break

    assert pages > 1
    assert delivered == gaps


def test_unicode_and_byte_cap_reduce_items_without_skipping(
    tmp_path: Path,
) -> None:
    store = JsContextStore(root_dir=tmp_path)
    document = _document(run_id="run-1", behavior_count=10)
    for index, behavior in enumerate(document["behaviors"]):
        behavior["question"] = "é" * 500
        behavior["steps"][0]["text"] = "界" * 500
        behavior["record_sha256"] = f"{index + 1:064x}"
        document["evidence"][index]["content_sha256"] = (
            f"{index + 101:064x}"
        )
        document["evidence"][index]["artifact_ref"] = (
            f"sha256/{index + 101:064x}"
        )
    store.publish(document)
    context_id = _context_id(document)
    tool = build_js_context_tool(PROJECT, store)

    delivered = []
    cursor = None
    page_lengths = []
    first_call = True
    while True:
        args = {
            "command": "read",
            "context_id": context_id,
            "selector": "run-1",
            "section": "behaviors",
            "limit": 10,
        }
        if cursor:
            args["cursor"] = cursor
        if first_call:
            message, page = _invoke_tool_call(
                tool,
                args,
                call_id="unicode-page-1",
            )
            assert len(message.content.encode("utf-8")) <= MAX_RESPONSE_BYTES
            first_call = False
        else:
            page = tool.invoke(args)
        assert page["ok"] is True
        assert _bytes(page) <= MAX_RESPONSE_BYTES
        assert len(page["items"]) <= 10
        page_lengths.append(len(page["items"]))
        delivered.extend(item["behavior_id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert delivered == [
        f"behavior_{chr(ord('a') + index)}"
        for index in range(10)
    ]
    assert any(length < 10 for length in page_lengths)


def test_individually_oversized_record_is_explicit(
    tmp_path: Path,
) -> None:
    store = JsContextStore(root_dir=tmp_path)
    document = _document(run_id="run-1")
    read_ids = [
        f"read_large_{index:03d}_" + "x" * 80
        for index in range(160)
    ]
    steps = []
    for step in range(12):
        steps.append(
            {
                "kind": "request",
                "text": "s" * 512,
                "read_ids": read_ids[step * 8 : step * 8 + 8],
            }
        )
    document["behaviors"][0]["question"] = "q" * 500
    document["behaviors"][0]["steps"] = steps
    document["behaviors"][0]["assumptions"] = [
        {
            "text": "a" * 512,
            "status": "unverified",
            "read_ids": read_ids[96 + index * 8 : 104 + index * 8],
        }
        for index in range(8)
    ]
    document["evidence"] = [
        {
            **document["evidence"][0],
            "read_id": read_id,
            "lead_id": "lead-a",
            "content_sha256": f"{index:064x}",
            "artifact_ref": f"sha256/{index:064x}",
        }
        for index, read_id in enumerate(read_ids)
    ]
    store.publish(document)
    context_id = _context_id(document)
    tool = build_js_context_tool(PROJECT, store)

    out = tool.invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "run-1",
            "section": "behaviors",
        }
    )

    assert out == {
        "ok": False,
        "error": "record_too_large",
    }


def test_current_advancing_invalidates_read_cursor(tmp_path: Path) -> None:
    store, _, context_id = _seed(
        tmp_path,
        run_id="run-1",
        behavior_count=3,
    )
    tool = build_js_context_tool(PROJECT, store)
    first = tool.invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "current",
            "section": "behaviors",
            "limit": 1,
        }
    )
    assert first["next_cursor"]

    second_document = _document(run_id="run-2", behavior_count=3)
    second_document["behaviors"][0]["steps"][0]["text"] = "Run two."
    store.publish(second_document)
    stale = tool.invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "current",
            "section": "behaviors",
            "cursor": first["next_cursor"],
        }
    )

    assert stale == {"ok": False, "error": "stale_cursor"}


def test_new_publication_invalidates_list_cursor(tmp_path: Path) -> None:
    store, _, _ = _seed(tmp_path, run_id="run-1")
    store.publish(_document(run_id="run-2"))
    tool = build_js_context_tool(PROJECT, store)
    first = tool.invoke({"command": "list", "limit": 1})
    assert first["next_cursor"]

    store.publish(_document(run_id="run-3"))
    stale = tool.invoke(
        {
            "command": "list",
            "cursor": first["next_cursor"],
        }
    )

    assert stale == {"ok": False, "error": "stale_cursor"}


def test_cursor_tamper_and_cross_scope_are_refused(tmp_path: Path) -> None:
    store, _, context_id = _seed(tmp_path, behavior_count=3)
    other = _document(auth_ref="account-b", behavior_count=3)
    store.publish(other)
    other_context_id = _context_id(other)
    tool = build_js_context_tool(PROJECT, store)
    page = tool.invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "run-1",
            "section": "behaviors",
            "limit": 1,
        }
    )
    cursor = page["next_cursor"]
    tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")

    assert tool.invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "run-1",
            "section": "behaviors",
            "cursor": tampered,
        }
    ) == {"ok": False, "error": "invalid_cursor"}
    assert build_js_context_tool("project-b", store).invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "run-1",
            "section": "behaviors",
            "cursor": cursor,
        }
    ) == {"ok": False, "error": "invalid_cursor"}
    assert tool.invoke(
        {
            "command": "read",
            "context_id": other_context_id,
            "selector": "run-1",
            "section": "behaviors",
            "cursor": cursor,
        }
    ) == {"ok": False, "error": "invalid_cursor"}
    assert tool.invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "run-1",
            "section": "evidence",
            "cursor": cursor,
        }
    ) == {"ok": False, "error": "invalid_cursor"}


def test_reads_do_not_modify_published_files(tmp_path: Path) -> None:
    store, document, context_id = _seed(tmp_path, behavior_count=2)
    tool = build_js_context_tool(PROJECT, store)
    yaml_path, current_path = _paths(tmp_path, document)
    before = {
        path: (
            path.read_bytes(),
            path.stat().st_mtime_ns,
            path.stat().st_mode,
        )
        for path in (yaml_path, current_path)
    }

    tool.invoke({"command": "list"})
    for section in ("metadata", "context", "behaviors", "evidence"):
        tool.invoke(
            {
                "command": "read",
                "context_id": context_id,
                "selector": "current",
                "section": section,
            }
        )

    after = {
        path: (
            path.read_bytes(),
            path.stat().st_mtime_ns,
            path.stat().st_mode,
        )
        for path in (yaml_path, current_path)
    }
    assert after == before


def test_scan_truncation_is_preserved_in_list(tmp_path: Path) -> None:
    class FakeStore:
        def list(self, **kwargs):
            return {
                "publications": [
                    {
                        "status": "ok",
                        "context_id": "jsctx_" + "1" * 40,
                        "run_id": "run-1",
                        "origin": {"status": "unknown", "value": None},
                        "auth_ref": "",
                        "coverage": {
                            "status": "partial",
                            "gaps": ["gap_" + "x" * 200],
                        },
                        "behavior_count": 1,
                        "evidence_count": 1,
                        "document_sha256": "a" * 64,
                        "size_bytes": 100,
                        "current": True,
                    }
                ],
                "next_cursor": None,
                "scan_truncated": True,
                "view_id": "v" * 64,
            }

    tool = build_js_context_tool(PROJECT, FakeStore())
    out = tool.invoke({"command": "list"})

    assert out["scan_truncated"] is True
    assert out["publications"][0]["coverage"] == {
        "status": "partial",
        "gap_count": 1,
    }


def test_real_writer_to_tool_round_trip_is_scoped_and_sanitized(
    tmp_path: Path,
) -> None:
    refs = {
        ("project-a", "run-1", "account-a"): issue_js_intake_reference(
            "project-a", "run-1", context_ref="account-a"
        ),
        ("project-a", "run-2", "account-a"): issue_js_intake_reference(
            "project-a", "run-2", context_ref="account-a"
        ),
        ("project-a", "run-1", "account-b"): issue_js_intake_reference(
            "project-a", "run-1", context_ref="account-b"
        ),
        ("project-b", "run-1", "account-a"): issue_js_intake_reference(
            "project-b", "run-1", context_ref="account-a"
        ),
    }
    notes = {
        key: FakeNotes(
            [
                _event(
                    behavior_id=f"behavior-{key[1]}-{key[2]}",
                    context_ref=key[2],
                    read_ids=(f"read-{key[1]}-{key[2]}",),
                    text=(
                        "Tool proof behavior for "
                        f"{key[0]}:{key[1]}:{key[2]}."
                    ),
                )
            ]
        )
        for key in refs
    }
    access = FakeAccess(
        {
            f"read-{run_id}-{auth_ref}": _receipt(
                f"read-{run_id}-{auth_ref}",
                project_id=project_id,
                run_id=run_id,
                auth_ref=auth_ref,
            )
            for project_id, run_id, auth_ref in refs
        }
    )
    retention = FakeRetention(
        {
            (f"behavior-{run_id}-{auth_ref}", 2): _snapshot(
                _link(f"read-{run_id}-{auth_ref}")
            )
            for _, run_id, auth_ref in refs
        }
    )
    writer = JsContextWriter(
        root=tmp_path,
        store=JsContextStore(root_dir=tmp_path),
        notes_factory=lambda scope: notes[
            (scope.project_id, scope.run_id, scope.context_ref)
        ],
        access=access,
        retention=retention,
    )
    for key, reference in refs.items():
        writer.publish(
            reference=reference,
            origin="https://app.test",
            analysis_coverage={"status": "complete", "gaps": []},
        )

    tool = build_js_context_tool("project-a", JsContextStore(root_dir=tmp_path))
    listed = tool.invoke({"command": "list", "limit": 10})
    context_one = _document(run_id="run-1")
    context_id = _context_id(context_one)
    current = tool.invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "current",
            "section": "behaviors",
        }
    )
    historical = tool.invoke(
        {
            "command": "read",
            "context_id": context_id,
            "selector": "run-1",
            "section": "behaviors",
        }
    )

    assert listed["ok"] is True
    assert {item["run_id"] for item in listed["publications"]} == {
        "run-1",
        "run-2",
    }
    assert {item["auth_ref"] for item in listed["publications"]} == {
        "account-a",
        "account-b",
    }
    assert {
        item["context_id"] for item in listed["publications"]
    } == {
        _context_id(_document(run_id="run-1", auth_ref="account-a")),
        _context_id(_document(run_id="run-2", auth_ref="account-a")),
        _context_id(_document(run_id="run-1", auth_ref="account-b")),
    }
    assert current["ok"] is True
    assert current["publication"]["current"] is True
    assert historical["items"][0]["behavior_id"] == (
        "behavior-run-1-account-a"
    )
    serialized = json.dumps(
        [listed, current, historical],
        ensure_ascii=False,
    )
    assert "SECRET_SOURCE_MUST_NOT_PUBLISH" not in serialized
    assert str(tmp_path) not in serialized
