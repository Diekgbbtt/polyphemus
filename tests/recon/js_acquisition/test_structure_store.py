import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from polymerhus.app.data_root import ensure_project, project_dir
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_acquisition.structure import parse_structure_bytes
from polymerhus.recon.js_acquisition.structure_store import (
    StructureStore,
    StructureStoreError,
)


FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "data/js-analysis-mvp-eval/bundle-structure-comparison/fixtures"
)


def _parsed(name: str):
    source = (FIXTURES / name).read_bytes()
    return source, parse_structure_bytes(source)


def _store(tmp_path) -> StructureStore:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    return StructureStore(root=root)


def test_index_and_item_ids_are_stable_and_page_filters_are_bound(tmp_path):
    store = _store(tmp_path)
    source, parsed = _parsed("esm-controlled.js")

    first = store.store_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        source_bytes=source,
        parsed=parsed,
        parent_final_url="https://app.example.test/app.js?token=private",
    )
    repeated = store.store_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        source_bytes=source,
        parsed=parsed,
        parent_final_url="https://app.example.test/app.js?token=private",
    )
    foreign = store.store_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-b",
        lead_id="lead-b",
        source_bytes=source,
        parsed=parsed,
        parent_final_url="https://app.example.test/app.js?token=private",
    )

    assert first["index_id"] == repeated["index_id"]
    assert first["source_sha256"] == hashlib.sha256(source).hexdigest()
    first_page = store.list_items(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        kind="import",
        limit=5,
    )
    second_page = store.list_items(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        kind="import",
        limit=5,
        cursor=first_page["next_cursor"],
    )
    first_ids = {
        item["item_id"]
        for item in first_page["items"] + second_page["items"]
    }
    foreign_page = store.list_items(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-b",
        lead_id="lead-b",
        kind="import",
        limit=10,
    )
    assert len(first_ids) == 6
    assert first_ids.isdisjoint(
        {item["item_id"] for item in foreign_page["items"]}
    )
    assert "token=private" not in str(first_page)

    with pytest.raises(StructureStoreError) as wrong_filter:
        store.list_items(
            project_id="proj-1",
            run_id="run-1",
            context_ref="account-a",
            lead_id="lead-a",
            kind="loader",
            cursor=first["next_cursor"] if "next_cursor" in first else first_page["next_cursor"],
        )
    assert wrong_filter.value.reason == "invalid_structure_cursor"


def test_public_items_are_redacted_but_private_item_keeps_resolution_fact(tmp_path):
    store = _store(tmp_path)
    source = b'export const x = import("./safe.js?token=SECRET&view=1");\\n'
    parsed = parse_structure_bytes(source)
    stored = store.store_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        source_bytes=source,
        parsed=parsed,
    )
    page = store.list_items(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        kind="import",
    )
    item = page["items"][0]
    public = store.get_item(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        item_id=item["item_id"],
    )
    private = store.private_item(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        item_id=item["item_id"],
    )

    assert "SECRET" not in str(public)
    assert private["specifier"] == "./safe.js?token=SECRET&view=1"
    assert private["index_id"] == stored["index_id"]


def test_missing_corrupt_and_changed_identity_do_not_invalidate_silently(tmp_path):
    store = _store(tmp_path)
    source, parsed = _parsed("esm-controlled.js")
    stored = store.store_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        source_bytes=source,
        parsed=parsed,
    )
    assert store.find_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        source_sha256=stored["source_sha256"],
        parser_identity=parsed.parser,
        config_identity=store.config_identity(),
    )["index_id"] == stored["index_id"]
    assert store.find_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        source_sha256="0" * 64,
        parser_identity=parsed.parser,
        config_identity=store.config_identity(),
    ) is None
    assert store.find_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        source_sha256=stored["source_sha256"],
        parser_identity={**parsed.parser, "version": "changed"},
        config_identity=store.config_identity(),
    ) is None

    index_path = next(
        (
            project_dir("proj-1", "recon/js_analysis", root=tmp_path / "data")
            / "run-1"
            / "structures"
        ).glob("*.json")
    )
    index_path.write_text("{corrupt", encoding="utf-8")
    with pytest.raises(StructureStoreError) as corrupt:
        store.list_items(
            project_id="proj-1",
            run_id="run-1",
            context_ref="account-a",
            lead_id="lead-a",
            limit=5,
        )
    assert corrupt.value.reason == "structure_index_corrupt"
    index_path.unlink()
    with pytest.raises(StructureStoreError) as missing:
        store.list_items(
            project_id="proj-1",
            run_id="run-1",
            context_ref="account-a",
            lead_id="lead-a",
            limit=5,
        )
    assert missing.value.reason == "structure_index_missing"


def test_cross_file_links_require_namespace_and_ambiguity_is_explicit(tmp_path):
    store = _store(tmp_path)
    source_a = (
        b'window.webpackJsonp([1], {"a": function(m,e,load){load("shared")}}, ["a"]);'
    )
    source_b = (
        b'window.webpackJsonp([2], {"shared": function(m,e){m.exports=1}}, ["shared"]);'
    )
    source_c = (
        b'window.webpackJsonp([3], {"shared": function(m,e){m.exports=2}}, ["shared"]);'
    )
    index_a = store.store_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        source_bytes=source_a,
        parsed=parse_structure_bytes(source_a),
    )
    index_b = store.store_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-b",
        source_bytes=source_b,
        parsed=parse_structure_bytes(source_b),
    )
    dependency = store.list_items(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        kind="dependency",
    )["items"][0]
    private_before = store.private_item(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        item_id=dependency["item_id"],
    )
    assert private_before["resolution"] == "unresolved_in_file"

    linked = store.link_namespace(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        namespace_id="namespace-1",
        index_ids=[index_a["index_id"], index_b["index_id"]],
    )
    private_after = store.private_item(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        item_id=dependency["item_id"],
    )
    assert linked["changed_dependencies"] == 1
    assert private_after["resolution"] == "resolved"
    assert private_after["target_index_id"] == index_b["index_id"]
    assert private_after["namespace_id"] == "namespace-1"

    index_c = store.store_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-c",
        source_bytes=source_c,
        parsed=parse_structure_bytes(source_c),
    )
    ambiguous = store.link_namespace(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        namespace_id="namespace-2",
        index_ids=[
            index_a["index_id"],
            index_b["index_id"],
            index_c["index_id"],
        ],
    )
    private_ambiguous = store.private_item(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        item_id=dependency["item_id"],
    )
    assert ambiguous["ambiguous_dependencies"] == 1
    assert private_ambiguous["resolution"] == "ambiguous"
    assert private_ambiguous["target_item_id"] is None


def test_project_run_and_context_authorization_never_cross_scope(tmp_path):
    store = _store(tmp_path)
    ensure_project("proj-2", root=tmp_path / "data")
    source, parsed = _parsed("esm-controlled.js")
    local = store.store_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        source_bytes=source,
        parsed=parsed,
    )
    foreign_project = store.store_index(
        project_id="proj-2",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        source_bytes=source,
        parsed=parsed,
    )
    foreign_run = store.store_index(
        project_id="proj-1",
        run_id="run-2",
        context_ref="account-a",
        lead_id="lead-a",
        source_bytes=source,
        parsed=parsed,
    )
    image = store.list_items(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        kind="import",
    )["items"][0]

    assert local["index_id"] != foreign_project["index_id"]
    assert local["index_id"] != foreign_run["index_id"]
    for project_id, run_id in (("proj-2", "run-1"), ("proj-1", "run-2")):
        with pytest.raises(StructureStoreError) as isolated:
            store.get_item(
                project_id=project_id,
                run_id=run_id,
                context_ref="account-a",
                item_id=image["item_id"],
            )
        assert isolated.value.reason == "structure_item_missing"


def test_absent_namespace_target_remains_unresolved(tmp_path):
    store = _store(tmp_path)
    source = (
        b'window.webpackJsonp([1], {"a": function(m,e,load){load("absent")}}, ["a"]);'
    )
    stored = store.store_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        source_bytes=source,
        parsed=parse_structure_bytes(source),
    )
    dependency = store.list_items(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        kind="dependency",
    )["items"][0]

    linked = store.link_namespace(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        namespace_id="namespace-absent",
        index_ids=[stored["index_id"]],
    )
    private = store.private_item(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        item_id=dependency["item_id"],
    )

    assert linked["changed_dependencies"] == 0
    assert linked["ambiguous_dependencies"] == 0
    assert private["resolution"] == "unresolved_namespace"
    assert private["target_item_id"] is None


def test_current_imports_returns_bounded_verified_private_facts(tmp_path):
    store = _store(tmp_path)
    source = (
        b'import { value } from "./part.js";\n'
        b'import "./side-effect.mjs";\n'
        b'const unresolved = import(name);\n'
    )
    parsed = parse_structure_bytes(source)
    stored = store.store_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        source_bytes=source,
        parsed=parsed,
        parent_final_url="https://cdn.example.test/assets/app.js?token=private",
    )

    result = store.current_imports(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        source_sha256=stored["source_sha256"],
    )

    assert result["index_id"] == stored["index_id"]
    assert len(result["index_integrity"]) == 64
    assert result["source_sha256"] == stored["source_sha256"]
    assert result["source_size"] == len(source)
    assert result["parent_final_url"] == (
        "https://cdn.example.test/assets/app.js?token=private"
    )
    assert {
        item["specifier"] for item in result["imports"]
    } == {"./part.js", "./side-effect.mjs"}
    assert all(item["start_byte"] < item["end_byte"] for item in result["imports"])
    assert "structure_import_reference_unresolved" in result["gaps"]

    limited = store.current_imports(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        source_sha256=stored["source_sha256"],
        max_items=1,
    )
    assert len(limited["imports"]) == 1
    assert "structure_import_limit" in limited["gaps"]


def test_current_imports_refuses_missing_stale_and_source_mismatch(tmp_path):
    store = _store(tmp_path)
    source, parsed = _parsed("esm-controlled.js")
    stored = store.store_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        source_bytes=source,
        parsed=parsed,
        parent_final_url="https://cdn.example.test/assets/app.js",
    )

    with pytest.raises(StructureStoreError) as mismatch:
        store.current_imports(
            project_id="proj-1",
            run_id="run-1",
            context_ref="account-a",
            lead_id="lead-a",
            source_sha256="f" * 64,
        )
    assert mismatch.value.reason == "structure_source_mismatch"

    manifest = AcquisitionManifest(
        project_id="proj-1",
        run_id="run-1",
        root=tmp_path / "data",
        max_run_bytes=8 * 1024 * 1024,
    )
    manifest.update(
        lambda value: value["structures"]["indexes"][stored["index_id"]].update(
            index_sha256="0" * 64
        )
    )
    with pytest.raises(StructureStoreError) as stale:
        store.current_imports(
            project_id="proj-1",
            run_id="run-1",
            context_ref="account-a",
            lead_id="lead-a",
            source_sha256=stored["source_sha256"],
        )
    assert stale.value.reason == "structure_index_stale"

    scopes = [
        ("proj-2", "run-1", "account-a", "lead-a"),
        ("proj-1", "run-2", "account-a", "lead-a"),
        ("proj-1", "run-1", "account-b", "lead-a"),
        ("proj-1", "run-1", "account-a", "lead-b"),
    ]
    for project_id, run_id, context_ref, lead_id in scopes:
        with pytest.raises(StructureStoreError) as missing:
            store.current_imports(
                project_id=project_id,
                run_id=run_id,
                context_ref=context_ref,
                lead_id=lead_id,
                source_sha256=stored["source_sha256"],
            )
        assert missing.value.reason == "structure_index_missing"


def test_current_imports_reports_corrupt_and_oversized_index(tmp_path):
    store = _store(tmp_path)
    source, parsed = _parsed("esm-controlled.js")
    stored = store.store_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-a",
        source_bytes=source,
        parsed=parsed,
        parent_final_url="https://cdn.example.test/assets/app.js",
    )
    index_path = next(
        (
            project_dir("proj-1", "recon/js_analysis", root=tmp_path / "data")
            / "run-1"
            / "structures"
        ).glob("*.json")
    )
    index_path.write_text("{corrupt", encoding="utf-8")
    with pytest.raises(StructureStoreError) as corrupt:
        store.current_imports(
            project_id="proj-1",
            run_id="run-1",
            context_ref="account-a",
            lead_id="lead-a",
            source_sha256=stored["source_sha256"],
        )
    assert corrupt.value.reason == "structure_index_corrupt"

    index_path.write_text("{}", encoding="utf-8")
    with pytest.raises(StructureStoreError) as limited:
        store.current_imports(
            project_id="proj-1",
            run_id="run-1",
            context_ref="account-a",
            lead_id="lead-a",
            source_sha256=stored["source_sha256"],
            max_bytes=1,
        )
    assert limited.value.reason == "structure_index_limit"

    index_path.unlink()
    with pytest.raises(StructureStoreError) as missing:
        store.current_imports(
            project_id="proj-1",
            run_id="run-1",
            context_ref="account-a",
            lead_id="lead-a",
            source_sha256=stored["source_sha256"],
        )
    assert missing.value.reason == "structure_index_missing"


def test_current_imports_preserves_unsupported_index_status(tmp_path):
    store = _store(tmp_path)
    source, parsed = _parsed("esm-controlled.js")
    stored = store.store_index(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-unsupported",
        source_bytes=source,
        parsed=replace(parsed, status="unsupported"),
        parent_final_url="https://cdn.example.test/assets/app.js",
    )

    result = store.current_imports(
        project_id="proj-1",
        run_id="run-1",
        context_ref="account-a",
        lead_id="lead-unsupported",
        source_sha256=stored["source_sha256"],
    )

    assert result["status"] == "unsupported"
    assert "structure_index_unsupported" in result["gaps"]
