"""Filesystem contract tests for the validated JS context store."""

from __future__ import annotations

import copy
import json
import multiprocessing
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from polymerhus.app.js_context import JsContextStore, JsContextStoreError
from polymerhus.app.js_context.records import MAX_DOCUMENT_BYTES, context_id_for


def _cross_process_publish(root: str, document: dict, start, queue) -> None:
    start.wait(timeout=5)
    try:
        result = JsContextStore(root_dir=root).publish(document)
        queue.put(("ok", result["status"]))
    except Exception as exc:  # pragma: no cover - surfaced through the queue
        queue.put(("error", type(exc).__name__, str(exc)))


def _behavior(index: int = 0) -> dict:
    suffix = chr(ord("a") + index)
    return {
        "behavior_id": f"behavior_{suffix}",
        "revision": 1,
        "reconstruction_level": "reconstructed",
        "question_ref": f"span_{suffix}",
        "question": f"Question {suffix}?",
        "priority": "high",
        "lead_id": f"lead_{suffix}",
        "record_sha256": suffix * 64,
        "redaction_policy": "js-source-redaction-v1",
        "redaction_count": 0,
        "steps": [
            {
                "kind": "request",
                "text": f"Step text {suffix}.",
                "read_ids": [f"read_{suffix}"],
            }
        ],
        "assumptions": [],
        "gaps": [],
    }


def _evidence(index: int = 0) -> dict:
    suffix = chr(ord("a") + index)
    return {
        "read_id": f"read_{suffix}",
        "lead_id": f"lead_{suffix}",
        "selector": {"type": "source", "id": f"source_{suffix}"},
        "content_sha256": suffix * 64,
        "range": {"start": 0, "end": 32},
        "redaction_policy": "js-source-redaction-v1",
        "delivery_status": "delivered",
        "availability": "retained_unverified",
        "retention_status": "retained",
        "artifact_ref": f"sha256/{suffix * 64}",
        "limitations": [],
    }


def _document(
    *,
    project_id: str = "project-a",
    run_id: str = "run-1",
    origin: str | None = "https://app.test",
    auth_ref: str = "account-a",
    behavior_count: int = 1,
    coverage: str = "complete",
) -> dict:
    behaviors = [_behavior(index) for index in range(behavior_count)]
    evidence = [_evidence(index) for index in range(behavior_count)]
    gaps = [] if coverage == "complete" else ["no_saved_behaviors"]
    if coverage == "empty":
        behaviors = []
        evidence = []
    return {
        "schema_version": 1,
        "context": {
            "project_id": project_id,
            "run_id": run_id,
            "origin": (
                {"status": "unknown", "value": None}
                if origin is None
                else {"status": "known", "value": origin}
            ),
            "auth_ref": auth_ref,
            "coverage": {"status": coverage, "gaps": gaps},
        },
        "behaviors": behaviors,
        "evidence": evidence,
    }


def _context_id(document: dict) -> str:
    context = document["context"]
    return context_id_for(
        project_id=context["project_id"],
        origin=context["origin"],
        auth_ref=context["auth_ref"],
    )


def _paths(root: Path, document: dict) -> tuple[Path, Path]:
    context_id = _context_id(document)
    directory = (
        root
        / document["context"]["project_id"]
        / "js-client-side"
        / context_id
    )
    return directory / f"{document['context']['run_id']}.yml", directory / "current.json"


def test_r1_r2_current_history_and_recreated_store(tmp_path: Path) -> None:
    store = JsContextStore(root_dir=tmp_path)
    first = _document(run_id="run-1")
    second = _document(run_id="run-2")
    context_id = _context_id(first)

    assert store.publish(first)["status"] == "published"
    assert store.publish(second)["status"] == "published"

    current = store.read(
        project_id="project-a",
        context_id=context_id,
        selector="current",
        section="metadata",
    )
    historical = JsContextStore(root_dir=tmp_path).read(
        project_id="project-a",
        context_id=context_id,
        selector="run-1",
        section="behaviors",
    )

    assert current["status"] == "ok"
    assert current["selector"] == {"kind": "current", "run_id": "run-2"}
    assert current["context"]["run_id"] == "run-2"
    assert historical["status"] == "ok"
    assert historical["selector"] == {"kind": "run", "run_id": "run-1"}
    assert historical["items"][0]["behavior_id"] == "behavior_a"

    first_yaml, current_file = _paths(tmp_path, first)
    assert first_yaml.is_file()
    assert _paths(tmp_path, second)[0].is_file()
    pointer = json.loads(current_file.read_text(encoding="utf-8"))
    assert pointer["run_id"] == "run-2"
    assert "behaviors" not in pointer
    assert "evidence" not in pointer


def test_projects_origins_unknown_and_auth_contexts_are_isolated(
    tmp_path: Path,
) -> None:
    store = JsContextStore(root_dir=tmp_path)
    first = _document()
    other_project = _document(project_id="project-b")
    other_origin = _document(origin="https://other.test")
    unknown = _document(origin=None)
    other_auth = _document(auth_ref="account-b")
    for document in (first, other_project, other_origin, unknown, other_auth):
        assert store.publish(document)["status"] == "published"

    context_ids = {
        _context_id(document)
        for document in (first, other_project, other_origin, unknown, other_auth)
    }
    assert len(context_ids) == 5
    assert store.read(
        project_id="project-a",
        context_id=_context_id(other_project),
        selector="current",
    )["status"] == "missing"
    listed = store.list(project_id="project-a", limit=20)
    assert {item["status"] for item in listed["publications"]} == {"ok"}
    assert {item["context_id"] for item in listed["publications"]} == {
        _context_id(first),
        _context_id(other_origin),
        _context_id(unknown),
        _context_id(other_auth),
    }


def test_identical_retry_is_idempotent(tmp_path: Path) -> None:
    store = JsContextStore(root_dir=tmp_path)
    document = _document()
    assert store.publish(document)["status"] == "published"
    yaml_path, current_path = _paths(tmp_path, document)
    before = (
        yaml_path.stat().st_mtime_ns,
        current_path.stat().st_mtime_ns,
        yaml_path.read_bytes(),
    )

    result = store.publish(copy.deepcopy(document))

    after = (
        yaml_path.stat().st_mtime_ns,
        current_path.stat().st_mtime_ns,
        yaml_path.read_bytes(),
    )
    assert result["status"] == "identical"
    assert result["current_advanced"] is False
    assert after == before


def test_conflicting_same_run_input_is_not_overwritten(tmp_path: Path) -> None:
    store = JsContextStore(root_dir=tmp_path)
    original = _document()
    conflicting = copy.deepcopy(original)
    conflicting["behaviors"][0]["steps"][0]["text"] = "Different semantics."
    assert store.publish(original)["status"] == "published"
    yaml_path, _ = _paths(tmp_path, original)
    original_bytes = yaml_path.read_bytes()

    result = store.publish(conflicting)

    assert result["status"] == "same_run_conflict"
    assert result["current_advanced"] is False
    assert yaml_path.read_bytes() == original_bytes
    read = store.read(
        project_id="project-a",
        context_id=_context_id(original),
        selector="run-1",
        section="behaviors",
    )
    assert read["items"][0]["steps"][0]["text"] == "Step text a."


def test_interrupted_promotion_preserves_r1_then_recovers_r2(
    tmp_path: Path,
) -> None:
    first = _document(run_id="run-1")
    second = _document(run_id="run-2")
    context_id = _context_id(first)
    current_writes = {"count": 0, "fail_after": 1}

    def write_text(path: Path, text: str) -> None:
        if Path(path).name == "current.json":
            current_writes["count"] += 1
            if current_writes["count"] > current_writes["fail_after"]:
                raise OSError("simulated lost current acknowledgement")
        from polymerhus.app.atomic_write import write_text_atomic

        write_text_atomic(path, text)

    store = JsContextStore(root_dir=tmp_path, write_text=write_text)
    assert store.publish(first)["status"] == "published"

    with pytest.raises(JsContextStoreError) as exc:
        store.publish(second)
    assert exc.value.reason == "current_write_failed"
    assert store.read(
        project_id="project-a",
        context_id=context_id,
        selector="current",
    )["context"]["run_id"] == "run-1"
    assert _paths(tmp_path, second)[0].is_file()

    current_writes["fail_after"] = 10
    recovered = store.publish(second)

    assert recovered["status"] == "recovered"
    assert recovered["current_advanced"] is True
    assert store.read(
        project_id="project-a",
        context_id=context_id,
        selector="current",
    )["context"]["run_id"] == "run-2"
    yaml_path, current_path = _paths(tmp_path, second)
    assert stat.S_IMODE(yaml_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(current_path.stat().st_mode) == 0o600


def test_lost_current_acknowledgement_is_idempotent_on_retry(
    tmp_path: Path,
) -> None:
    first = _document(run_id="run-1")
    second = _document(run_id="run-2")
    context_id = _context_id(first)
    current_writes = {"count": 0}

    def write_then_lose_second_ack(path: Path, text: str) -> None:
        from polymerhus.app.atomic_write import write_text_atomic

        write_text_atomic(path, text)
        if Path(path).name == "current.json":
            current_writes["count"] += 1
            if current_writes["count"] == 2:
                raise OSError("simulated lost current response")

    store = JsContextStore(
        root_dir=tmp_path,
        write_text=write_then_lose_second_ack,
    )
    store.publish(first)
    with pytest.raises(JsContextStoreError):
        store.publish(second)

    recovered = store.publish(second)

    assert recovered["status"] == "identical"
    assert recovered["current_advanced"] is False
    assert store.read(
        project_id="project-a",
        context_id=context_id,
        selector="current",
    )["context"]["run_id"] == "run-2"


def test_interrupted_document_write_leaves_current_and_target_unchanged(
    tmp_path: Path,
) -> None:
    first = _document(run_id="run-1")
    second = _document(run_id="run-2")
    context_id = _context_id(first)
    store = JsContextStore(root_dir=tmp_path)
    store.publish(first)

    def fail_document(path: Path, text: str) -> None:
        if Path(path).name == "run-2.yml":
            raise OSError("simulated document write failure")
        from polymerhus.app.atomic_write import write_text_atomic

        write_text_atomic(path, text)

    failing = JsContextStore(root_dir=tmp_path, write_text=fail_document)
    with pytest.raises(JsContextStoreError) as exc:
        failing.publish(second)
    assert exc.value.reason == "document_write_failed"
    assert not _paths(tmp_path, second)[0].exists()
    assert store.read(
        project_id="project-a",
        context_id=context_id,
        selector="current",
    )["context"]["run_id"] == "run-1"


def test_older_retry_does_not_move_current_backwards(tmp_path: Path) -> None:
    store = JsContextStore(root_dir=tmp_path)
    first = _document(run_id="run-1")
    second = _document(run_id="run-2")
    context_id = _context_id(first)
    store.publish(first)
    time.sleep(0.002)
    store.publish(second)

    result = store.publish(first)

    assert result["status"] == "not_current"
    assert result["current_advanced"] is False
    assert store.read(
        project_id="project-a",
        context_id=context_id,
        selector="current",
    )["context"]["run_id"] == "run-2"


def test_missing_current_recovers_the_newest_valid_run_not_the_retry(
    tmp_path: Path,
) -> None:
    store = JsContextStore(root_dir=tmp_path)
    first = _document(run_id="run-1")
    second = _document(run_id="run-2")
    context_id = _context_id(first)
    store.publish(first)
    time.sleep(0.002)
    store.publish(second)
    _paths(tmp_path, first)[1].unlink()

    result = store.publish(first)

    assert result["status"] == "recovered"
    assert result["current_advanced"] is True
    assert result["current_run_id"] == "run-2"
    assert store.read(
        project_id="project-a",
        context_id=context_id,
        selector="current",
    )["context"]["run_id"] == "run-2"


def test_concurrent_identical_publishers_converge(tmp_path: Path) -> None:
    document = _document()

    def publish_once(_index: int) -> dict:
        return JsContextStore(root_dir=tmp_path).publish(copy.deepcopy(document))

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(publish_once, range(4)))

    statuses = [result["status"] for result in results]
    assert statuses.count("published") == 1
    assert statuses.count("identical") == 3
    assert _paths(tmp_path, document)[0].is_file()


def test_cross_process_publishers_share_the_publication_lock(
    tmp_path: Path,
) -> None:
    document = _document()
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    queue = context.Queue()
    processes = [
        context.Process(
            target=_cross_process_publish,
            args=(str(tmp_path), copy.deepcopy(document), start, queue),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    start.set()
    results = [queue.get(timeout=10) for _ in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    assert all(result[0] == "ok" for result in results)
    assert sorted(result[1] for result in results) == ["identical", "published"]


def test_corrupt_document_and_current_are_explicit(tmp_path: Path) -> None:
    store = JsContextStore(root_dir=tmp_path)
    document = _document()
    store.publish(document)
    yaml_path, current_path = _paths(tmp_path, document)
    context_id = _context_id(document)
    yaml_path.write_text("schema_version: [\n", encoding="utf-8")

    assert store.read(
        project_id="project-a",
        context_id=context_id,
        selector="run-1",
    )["status"] == "corrupt"
    assert store.read(
        project_id="project-a",
        context_id=context_id,
        selector="current",
    )["status"] == "corrupt"

    yaml_path.unlink()
    current_path.write_text("{not-json", encoding="utf-8")
    assert store.read(
        project_id="project-a",
        context_id=context_id,
        selector="current",
    )["status"] == "corrupt"


def test_malformed_yaml_keys_and_oversized_documents_are_corrupt(
    tmp_path: Path,
) -> None:
    store = JsContextStore(root_dir=tmp_path)
    document = _document()
    store.publish(document)
    yaml_path, _ = _paths(tmp_path, document)
    context_id = _context_id(document)
    yaml_path.write_text(
        "schema_version: 1\n1: mixed-key\nother: mixed-key\ncontext: {}\n",
        encoding="utf-8",
    )

    assert store.read(
        project_id="project-a",
        context_id=context_id,
        selector="run-1",
    )["status"] == "corrupt"

    yaml_path.write_bytes(b"x" * (MAX_DOCUMENT_BYTES + 1))
    assert store.read(
        project_id="project-a",
        context_id=context_id,
        selector="run-1",
    )["status"] == "corrupt"


def test_boolean_current_metadata_is_corrupt(
    tmp_path: Path,
) -> None:
    store = JsContextStore(root_dir=tmp_path)
    document = _document()
    store.publish(document)
    _, current_path = _paths(tmp_path, document)
    original = json.loads(current_path.read_text(encoding="utf-8"))
    for field in ("published_at_ns", "schema_version"):
        pointer = copy.deepcopy(original)
        pointer[field] = True
        current_path.write_text(json.dumps(pointer), encoding="utf-8")

        assert store.read(
            project_id="project-a",
            context_id=_context_id(document),
            selector="current",
        )["status"] == "corrupt"


def test_explicit_read_and_list_require_a_matching_current_hash(
    tmp_path: Path,
) -> None:
    store = JsContextStore(root_dir=tmp_path)
    document = _document()
    store.publish(document)
    _, current_path = _paths(tmp_path, document)
    pointer = json.loads(current_path.read_text(encoding="utf-8"))
    pointer["document_sha256"] = "0" * 64
    current_path.write_text(json.dumps(pointer), encoding="utf-8")
    context_id = _context_id(document)

    explicit = store.read(
        project_id="project-a",
        context_id=context_id,
        selector="run-1",
        section="metadata",
    )
    listed = store.list(
        project_id="project-a",
        context_id=context_id,
        limit=10,
    )

    assert explicit["publication"]["current"] is False
    assert listed["publications"][0]["current"] is False


def test_stored_scope_mismatch_is_not_silently_accepted(tmp_path: Path) -> None:
    store = JsContextStore(root_dir=tmp_path)
    document = _document()
    store.publish(document)
    yaml_path, _ = _paths(tmp_path, document)
    changed = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    changed["context"]["run_id"] = "run-other"
    yaml_path.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")

    result = store.read(
        project_id="project-a",
        context_id=_context_id(document),
        selector="run-1",
    )

    assert result["status"] == "run_mismatch"


@pytest.mark.parametrize(
    "context_id,run_id",
    [
        ("../escape", "run-1"),
        ("jsctx_ok", "../run"),
        ("jsctx_ok\x00", "run-1"),
    ],
)
def test_hostile_identifiers_are_refused(
    tmp_path: Path,
    context_id: str,
    run_id: str,
) -> None:
    store = JsContextStore(root_dir=tmp_path)
    with pytest.raises(ValueError):
        store.read(
            project_id="project-a",
            context_id=context_id,
            selector=run_id,
        )


def test_symlinked_context_is_refused_without_touching_its_target(
    tmp_path: Path,
) -> None:
    document = _document()
    store = JsContextStore(root_dir=tmp_path)
    context_dir = _paths(tmp_path, document)[0].parent
    context_dir.parent.mkdir(parents=True, exist_ok=True)
    external = tmp_path / "external"
    external.mkdir()
    context_dir.symlink_to(external, target_is_directory=True)

    with pytest.raises(JsContextStoreError) as exc:
        store.publish(document)

    assert exc.value.reason == "unsafe_symlink"
    assert list(external.iterdir()) == []


def test_list_and_section_reads_are_bounded_and_paginated(
    tmp_path: Path,
) -> None:
    store = JsContextStore(root_dir=tmp_path)
    first = _document(run_id="run-1", behavior_count=2)
    context_id = _context_id(first)
    for run_id in ("run-1", "run-2", "run-3"):
        document = copy.deepcopy(first)
        document["context"]["run_id"] = run_id
        store.publish(document)

    page = store.list(project_id="project-a", limit=2)
    assert len(page["publications"]) == 2
    assert page["next_cursor"]
    remainder = store.list(
        project_id="project-a",
        limit=2,
        cursor=page["next_cursor"],
    )
    assert len(remainder["publications"]) == 1
    assert remainder["next_cursor"] is None

    behavior_page = store.read(
        project_id="project-a",
        context_id=context_id,
        selector="current",
        section="behaviors",
        limit=1,
    )
    assert len(behavior_page["items"]) == 1
    assert behavior_page["next_cursor"]
    next_page = store.read(
        project_id="project-a",
        context_id=context_id,
        selector="current",
        section="behaviors",
        limit=1,
        cursor=behavior_page["next_cursor"],
    )
    assert [item["behavior_id"] for item in next_page["items"]] == ["behavior_b"]


def test_list_cursor_is_bound_to_the_listing_snapshot(tmp_path: Path) -> None:
    store = JsContextStore(root_dir=tmp_path)
    for run_id in ("run-1", "run-2"):
        store.publish(_document(run_id=run_id))
    page = store.list(project_id="project-a", limit=1)
    assert page["view_id"]

    time.sleep(0.002)
    store.publish(_document(run_id="run-3"))

    with pytest.raises(ValueError, match="cursor"):
        store.list(
            project_id="project-a",
            limit=1,
            cursor=page["next_cursor"],
        )


def test_publication_files_and_context_directory_are_private(
    tmp_path: Path,
) -> None:
    store = JsContextStore(root_dir=tmp_path)
    document = _document()
    store.publish(document)
    yaml_path, current_path = _paths(tmp_path, document)

    assert stat.S_IMODE(yaml_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(yaml_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(current_path.stat().st_mode) == 0o600


def test_empty_new_run_becomes_current_without_erasing_history(
    tmp_path: Path,
) -> None:
    store = JsContextStore(root_dir=tmp_path)
    first = _document(run_id="run-1")
    empty = _document(run_id="run-2", coverage="empty")
    context_id = _context_id(first)

    store.publish(first)
    store.publish(empty)

    current = store.read(
        project_id="project-a",
        context_id=context_id,
        selector="current",
        section="context",
    )
    historical = store.read(
        project_id="project-a",
        context_id=context_id,
        selector="run-1",
        section="behaviors",
    )
    assert current["context"]["coverage"] == {
        "status": "empty",
        "gaps": ["no_saved_behaviors"],
    }
    assert current["publication"]["behavior_count"] == 0
    assert historical["items"][0]["behavior_id"] == "behavior_a"
