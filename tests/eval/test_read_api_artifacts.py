"""The manifest-backed artifact read API (real eval project artifacts, Task 6).

Inventory, semantic detail, and streamed raw content are served exclusively
from an available schema-v2 project snapshot: ids resolve only through the
manifest inventory, never as filesystem paths, and every detail/content request
re-validates the allowlist, containment, file type, size, and SHA-256.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import pytest
import yaml
from fastapi.testclient import TestClient

from orchestrator import files as artifact_files
from orchestrator import project_artifacts as artifact_catalog
from orchestrator import project_graph as artifact_graph
from orchestrator import store as artifact_store
from read_api import app as app_module
from read_api import artifacts as artifact_reader
from read_api import source as source_module

TARGET = "jetlinks-1"
RUN = "run-a"
TRIAL = "t1"
PROJECT_ID = "proj-1"
CAPTURED_AT = "2024-01-01T00:00:00+00:00"
COPIED_AT = "2024-01-01T00:00:00+00:00"

MAX_PREVIEW = 512 * 1024
MAX_YAML = 2 * 1024 * 1024

# The standard synthetic project: two hunt configs, one test spec, one pod
# variant, one experiment log, one pod export, and one skill bundle.
STANDARD_FILES = {
    "hunting/orchestration/hunt_configs/produced/prod.yaml": b"kind: hunt-config\n",
    "hunting/orchestration/hunt_configs/consumed/cons.yaml": b"kind: hunt-config\n",
    "hunting/hunter/test-specs/fault-a/produced/spec.yaml": b"kind: test-spec\n",
    "hunting/test-executor-pod/spec-1/variants/variant.yaml": b"kind: pod-variant\n",
    "hunting/test-executor-pod/spec-1/experiment-log/order-0.yaml": b"kind: experiment-log\n",
    "hunting/test-executor-pod/spec-1/export.yaml": b"kind: pod-export\n",
    "skills/authn/SKILL.md": b"# Authn skill\n",
    "skills/authn/references/notes.md": b"# Notes\n",
    "skills/authn/scripts/run.sh": b"echo run\n",
    "skills/authn/assets/logo.bin": b"\x89PNG\r\n\x1a\n\x00\x01",
}


def _artifact_id(relative: str) -> str:
    return hashlib.sha256(relative.encode()).hexdigest()


def _record(target: str, run: str, trial: str, project_id: str) -> dict:
    return {
        "trial_id": trial,
        "target_id": target,
        "target_run_id": run,
        "instance_id": "inst-1",
        "project_id": project_id,
        "start_phase": "hunting",
        "terminal": "complete",
        "phases": [],
        "eval_sha": "eval-1",
        "stack_fingerprint": "fp-1",
    }


def _write_manifest(trial_dir: Path, target: str, run: str, trial: str, project_id: str) -> None:
    files = artifact_files.FileStore()
    artifacts = artifact_catalog.collect_project_artifacts(trial_dir, project_id, files=files)
    payload = {
        "project_id": project_id,
        "nodes": [{"id": "n1", "name": "a", "type": "L1Service", "properties": {}}],
        "links": [],
    }
    capture = artifact_graph.capture_project_graph(
        payload,
        project_id=project_id,
        captured_at=CAPTURED_AT,
        destination=trial_dir / artifact_graph.PROJECT_GRAPH_FILENAME,
        files=files,
    )
    snapshot = artifact_store.ProjectSnapshot(
        available=True,
        project_id=project_id,
        captured_at=CAPTURED_AT,
        graph_sha256=capture.sha256,
        graph_node_count=1,
        graph_link_count=0,
        artifacts=artifacts,
    )
    manifest = artifact_store.build_run_manifest(
        _record(target, run, trial, project_id),
        [],
        COPIED_AT,
        diagnoses_present=False,
        project_snapshot=snapshot,
    )
    fingerprint = artifact_store._snapshot_sha256(trial_dir, manifest, files)
    manifest["project_snapshot"]["snapshot_sha256"] = fingerprint
    manifest["project_artifacts"]["snapshot_sha256"] = fingerprint
    (trial_dir / "run-manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )


def _build_trial(
    store: Path,
    *,
    target: str = TARGET,
    run: str = RUN,
    trial: str = TRIAL,
    project_id: str = PROJECT_ID,
    extra: dict[str, bytes] | None = None,
) -> Path:
    trial_dir = store / target / run / trial
    project_root = trial_dir / project_id
    for relative, data in {**STANDARD_FILES, **(extra or {})}.items():
        path = project_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    _write_manifest(trial_dir, target, run, trial, project_id)
    return trial_dir


def _client(store: Path) -> TestClient:
    return TestClient(
        app_module.create_app(lambda: source_module.ArtifactStoreSnapshotSource(store))
    )


def _list_url(target: str = TARGET, run: str = RUN, trial: str = TRIAL) -> str:
    return f"/trials/{quote(target, safe='')}/{quote(run, safe='')}/{quote(trial, safe='')}/artifacts"


def _detail_url(artifact_id: str, *, target: str = TARGET, run: str = RUN, trial: str = TRIAL) -> str:
    return f"{_list_url(target, run, trial)}/{quote(artifact_id, safe='')}"


def _content_url(artifact_id: str, *, target: str = TARGET, run: str = RUN, trial: str = TRIAL) -> str:
    return f"{_detail_url(artifact_id, target=target, run=run, trial=trial)}/content"


def _entries_by_path(store: Path) -> dict[str, dict]:
    manifest = yaml.safe_load(
        (store / TARGET / RUN / TRIAL / "run-manifest.yaml").read_text(encoding="utf-8")
    )
    return {e["relative_path"]: e for e in manifest["project_artifacts"]["entries"]}


def _tamper_entry(store: Path, relative: str, **overrides: object) -> dict:
    """Rewrite one inventory entry's metadata without recollecting the files."""
    manifest_path = store / TARGET / RUN / TRIAL / "run-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["project_artifacts"]["entries"]:
        if entry["relative_path"] == relative:
            entry.update(overrides)
            manifest_path.write_text(
                yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
            )
            return entry
    raise AssertionError(f"no inventory entry for {relative}")


# --- inventory ------------------------------------------------------------------


def test_inventory_groups_and_orders_deterministically(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _build_trial(store)

    body = _client(store).get(_list_url()).json()

    assert body["status"] == "available"
    assert body["project_id"] == PROJECT_ID
    groups = {group["key"]: group for group in body["groups"]}
    assert list(groups) == sorted(groups)  # top-level groups sort lexically by key
    assert set(groups) == {"hunt-configs", "test-specs", "pod-executions", "skills"}

    hunt_configs = groups["hunt-configs"]
    assert hunt_configs["category"] == "hunting"
    assert [child["key"] for child in hunt_configs["children"]] == [
        "hunt-configs/consumed",
        "hunt-configs/produced",
    ]
    produced = hunt_configs["children"][1]
    assert produced["label"] == "Produced"
    assert [e["relative_path"] for e in produced["entries"]] == [
        "hunting/orchestration/hunt_configs/produced/prod.yaml"
    ]

    assert [c["key"] for c in groups["test-specs"]["children"]] == ["test-specs/fault-a"]
    assert [c["key"] for c in groups["pod-executions"]["children"]] == [
        "pod-executions/spec-1"
    ]

    skills = groups["skills"]
    assert skills["category"] == "skill"
    assert [c["key"] for c in skills["children"]] == ["skills/authn"]
    support = {c["key"]: c for c in skills["children"][0]["children"]}
    assert list(support) == sorted(support)
    assert set(support) == {
        "skills/authn/assets",
        "skills/authn/procedure",
        "skills/authn/references",
        "skills/authn/scripts",
    }
    assert support["skills/authn/procedure"]["label"] == "Procedure"
    assert support["skills/authn/procedure"]["entries"][0]["kind"] == "skill_procedure"
    assert support["skills/authn/assets"]["entries"][0]["representation"] == "binary"


def test_inventory_never_carries_a_host_path(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _build_trial(store)

    res = _client(store).get(_list_url())

    assert res.status_code == 200
    assert str(tmp_path) not in res.text
    for entry in _walk(res.json()):
        if isinstance(entry, str):
            assert not entry.startswith("/")


def _walk(value: object):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


# --- detail ---------------------------------------------------------------------


def test_detail_yaml_is_parsed_and_text_is_bounded(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _build_trial(store)
    entry = _entries_by_path(store)["hunting/orchestration/hunt_configs/produced/prod.yaml"]

    body = _client(store).get(_detail_url(entry["artifact_id"])).json()

    assert body["entry"] == entry
    assert body["preview"]["text"] == "kind: hunt-config\n"
    assert body["preview"]["parsed"] == {"kind": "hunt-config"}
    assert body["preview"]["truncated"] is False
    assert body["preview"]["parse_error"] is None
    assert body["content_url"].endswith(f"/artifacts/{entry['artifact_id']}/content")


def test_detail_malformed_yaml_keeps_raw_text_and_reports_parse_error(tmp_path: Path) -> None:
    store = tmp_path / "store"
    broken = b"key: [unterminated\n"
    _build_trial(store, extra={"hunting/orchestration/hunt_configs/produced/broken.yaml": broken})
    entry = _entries_by_path(store)[
        "hunting/orchestration/hunt_configs/produced/broken.yaml"
    ]

    body = _client(store).get(_detail_url(entry["artifact_id"])).json()

    assert body["preview"]["parsed"] is None
    assert body["preview"]["parse_error"] == "invalid_yaml"
    assert body["preview"]["text"] == broken.decode()
    # The raw download still works.
    assert (
        _client(store).get(_content_url(entry["artifact_id"])).content == broken
    )


def test_detail_invalid_utf8_reports_parse_error_but_raw_download_works(tmp_path: Path) -> None:
    store = tmp_path / "store"
    bad = b"\xff\xfe\x00invalid"
    _build_trial(store, extra={"skills/authn/references/bad.md": bad})
    entry = _entries_by_path(store)["skills/authn/references/bad.md"]

    body = _client(store).get(_detail_url(entry["artifact_id"])).json()

    assert body["preview"]["text"] is None
    assert body["preview"]["parsed"] is None
    assert body["preview"]["parse_error"] == "invalid_utf8"
    assert _client(store).get(_content_url(entry["artifact_id"])).content == bad


def test_detail_markdown_and_text_are_utf8_source(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _build_trial(store)
    client = _client(store)

    markdown = _entries_by_path(store)["skills/authn/SKILL.md"]
    text = _entries_by_path(store)["skills/authn/scripts/run.sh"]

    markdown_body = client.get(_detail_url(markdown["artifact_id"])).json()
    text_body = client.get(_detail_url(text["artifact_id"])).json()
    assert markdown_body["preview"]["text"] == "# Authn skill\n"
    assert markdown_body["preview"]["parsed"] is None
    assert markdown_body["preview"]["parse_error"] is None
    assert text_body["preview"]["text"] == "echo run\n"


def test_detail_binary_is_metadata_only(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _build_trial(store)
    entry = _entries_by_path(store)["skills/authn/assets/logo.bin"]

    body = _client(store).get(_detail_url(entry["artifact_id"])).json()

    assert body["preview"] == {
        "text": None,
        "parsed": None,
        "truncated": False,
        "parse_error": None,
    }
    assert "PNG" not in json.dumps(body)


def test_detail_yaml_binary_tag_is_unsupported_not_a_500(tmp_path: Path) -> None:
    store = tmp_path / "store"
    raw = b"payload: !!binary /w==\n"
    _build_trial(
        store,
        extra={"hunting/orchestration/hunt_configs/produced/binary.yaml": raw},
    )
    entry = _entries_by_path(store)[
        "hunting/orchestration/hunt_configs/produced/binary.yaml"
    ]
    client = _client(store)

    res = client.get(_detail_url(entry["artifact_id"]))

    assert res.status_code == 200
    preview = res.json()["preview"]
    assert preview["parsed"] is None
    assert preview["parse_error"] == "unsupported_yaml_value"
    assert preview["text"] == raw.decode()
    # The raw download is still available.
    assert client.get(_content_url(entry["artifact_id"])).content == raw


# --- exact preview boundaries ----------------------------------------------------


def test_text_preview_512k_boundary_is_not_truncated(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _build_trial(store, extra={"skills/authn/references/limit.md": b"a" * MAX_PREVIEW})
    entry = _entries_by_path(store)["skills/authn/references/limit.md"]

    preview = _client(store).get(_detail_url(entry["artifact_id"])).json()["preview"]

    assert preview["truncated"] is False
    assert preview["text"] == "a" * MAX_PREVIEW


def test_text_preview_512k_plus_one_is_truncated(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _build_trial(store, extra={"skills/authn/references/over.md": b"a" * (MAX_PREVIEW + 1)})
    entry = _entries_by_path(store)["skills/authn/references/over.md"]

    preview = _client(store).get(_detail_url(entry["artifact_id"])).json()["preview"]

    assert preview["truncated"] is True
    assert preview["text"] == "a" * MAX_PREVIEW


def test_truncated_preview_with_invalid_byte_reports_invalid_utf8(tmp_path: Path) -> None:
    store = tmp_path / "store"
    # The 0xff sits inside the preview window, not at a genuine UTF-8 boundary.
    over = b"a" * (MAX_PREVIEW - 1) + b"\xff" + b"x" * 16
    _build_trial(store, extra={"skills/authn/references/invalid.md": over})
    entry = _entries_by_path(store)["skills/authn/references/invalid.md"]

    preview = _client(store).get(_detail_url(entry["artifact_id"])).json()["preview"]

    assert preview["truncated"] is True
    assert preview["text"] is None
    assert preview["parse_error"] == "invalid_utf8"


def test_truncated_preview_trims_a_split_multibyte_character(tmp_path: Path) -> None:
    store = tmp_path / "store"
    # The euro sign's first byte lands exactly at the 512 KiB preview boundary.
    text = b"a" * (MAX_PREVIEW - 1) + "\u20ac".encode("utf-8")
    _build_trial(store, extra={"skills/authn/references/split.md": text})
    entry = _entries_by_path(store)["skills/authn/references/split.md"]

    res = _client(store).get(_detail_url(entry["artifact_id"]))

    assert res.status_code == 200
    preview = res.json()["preview"]
    assert preview["truncated"] is True
    assert preview["parse_error"] is None
    assert preview["text"] == "a" * (MAX_PREVIEW - 1)


def _yaml_bytes(size: int) -> bytes:
    prefix = b"value: "
    return prefix + b"a" * (size - len(prefix))


def test_yaml_2mib_is_parsed(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _build_trial(
        store,
        extra={"hunting/orchestration/hunt_configs/produced/big.yaml": _yaml_bytes(MAX_YAML)},
    )
    entry = _entries_by_path(store)[
        "hunting/orchestration/hunt_configs/produced/big.yaml"
    ]

    preview = _client(store).get(_detail_url(entry["artifact_id"])).json()["preview"]

    assert preview["parsed"] == {"value": "a" * (MAX_YAML - len(b"value: "))}
    assert preview["truncated"] is True  # the text preview is still 512 KiB-bounded
    assert preview["parse_error"] is None


def test_yaml_2mib_plus_one_is_download_only(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _build_trial(
        store,
        extra={
            "hunting/orchestration/hunt_configs/produced/over.yaml": _yaml_bytes(MAX_YAML + 1)
        },
    )
    entry = _entries_by_path(store)[
        "hunting/orchestration/hunt_configs/produced/over.yaml"
    ]

    preview = _client(store).get(_detail_url(entry["artifact_id"])).json()["preview"]

    assert preview["parsed"] is None
    assert preview["parse_error"] is None
    assert preview["truncated"] is True


# --- raw streaming ----------------------------------------------------------------


def test_content_streams_raw_bytes_with_safe_headers(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _build_trial(store)
    entry = _entries_by_path(store)["skills/authn/assets/logo.bin"]

    res = _client(store).get(_content_url(entry["artifact_id"]))

    assert res.status_code == 200
    assert res.content == STANDARD_FILES["skills/authn/assets/logo.bin"]
    assert res.headers["content-type"] == entry["media_type"]
    assert res.headers["content-length"] == str(entry["size_bytes"])
    disposition = res.headers["content-disposition"]
    assert disposition.startswith("attachment")
    assert 'filename="logo.bin"' in disposition
    assert "/" not in disposition


def test_content_text_is_inline_but_never_a_path(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _build_trial(store)
    entry = _entries_by_path(store)["skills/authn/SKILL.md"]

    res = _client(store).get(_content_url(entry["artifact_id"]))

    assert res.status_code == 200
    assert res.headers["content-disposition"].startswith("inline")
    assert str(tmp_path) not in res.text


# --- identity, compatibility, and errors -----------------------------------------


def test_routes_use_the_full_trial_identity_and_url_encoding(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _build_trial(store, run="run-a", project_id="proj-a")
    _build_trial(store, run="run:b", project_id="proj-b")
    client = _client(store)
    entry = _entries_by_path(store)["skills/authn/SKILL.md"]

    encoded = client.get(_list_url(run="run:b"))
    assert encoded.status_code == 200
    assert encoded.json()["project_id"] == "proj-b"
    assert client.get(_list_url(run="run-c")).status_code == 404
    # The same artifact id resolves only under a run that has it.
    assert client.get(_detail_url(entry["artifact_id"], run="run:b")).status_code == 200


def test_unknown_trial_and_artifact_are_404(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _build_trial(store)
    client = _client(store)

    missing_trial = client.get(_list_url(trial="missing"))
    assert missing_trial.status_code == 404
    assert missing_trial.json()["detail"] == "trial_not_found"
    assert str(tmp_path) not in missing_trial.text

    unknown = client.get(_detail_url("0" * 64))
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "artifact_not_found"


@pytest.mark.parametrize(
    "path",
    [
        "/trials/jetlinks-1/run-a/t1/artifacts",
        "/trials/jetlinks-1/run-a/t1/artifacts/" + "0" * 64,
        "/trials/jetlinks-1/run-a/t1/artifacts/" + "0" * 64 + "/content",
    ],
)
@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_artifact_routes_reject_mutation(tmp_path: Path, method: str, path: str) -> None:
    store = tmp_path / "store"
    _build_trial(store)

    assert getattr(_client(store), method)(path).status_code == 405


def test_schema_v1_is_project_artifacts_unavailable(tmp_path: Path) -> None:
    store = tmp_path / "store"
    trial_dir = _build_trial(store)
    manifest = yaml.safe_load((trial_dir / "run-manifest.yaml").read_text(encoding="utf-8"))
    manifest = {
        key: manifest[key]
        for key in (
            "schema_version",
            "trial_id",
            "target_id",
            "target_run_id",
            "instance_id",
            "project_id",
            "eval_sha",
            "stack_fingerprint",
        )
    }
    manifest["schema_version"] = 1
    (trial_dir / "run-manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )

    res = _client(store).get(_list_url())

    assert res.status_code == 409
    assert res.json()["detail"] == "project_artifacts_unavailable"
    assert str(tmp_path) not in res.text


def test_schema_v2_unavailable_is_project_snapshot_unavailable(tmp_path: Path) -> None:
    store = tmp_path / "store"
    trial_dir = _build_trial(store)
    manifest = yaml.safe_load((trial_dir / "run-manifest.yaml").read_text(encoding="utf-8"))
    manifest["project_artifacts"]["status"] = "unavailable"
    manifest["project_artifacts"]["entries"] = []
    (trial_dir / "run-manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )

    res = _client(store).get(_list_url())

    assert res.status_code == 409
    assert res.json()["detail"] == "project_snapshot_unavailable"
    assert str(tmp_path) not in res.text


def test_unsafe_inventory_metadata_is_artifact_unsafe(tmp_path: Path) -> None:
    store = tmp_path / "store"
    trial_dir = _build_trial(store)
    manifest = yaml.safe_load((trial_dir / "run-manifest.yaml").read_text(encoding="utf-8"))
    manifest["project_artifacts"]["entries"][0]["relative_path"] = "../../etc/passwd"
    (trial_dir / "run-manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )

    res = _client(store).get(_list_url())

    assert res.status_code == 409
    assert res.json()["detail"] == "artifact_unsafe"
    assert str(tmp_path) not in res.text


def test_representation_mismatch_is_artifact_unsafe(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _build_trial(store, extra={"skills/authn/assets/icon.svg": b"<svg></svg>\n"})
    _tamper_entry(store, "skills/authn/assets/icon.svg", media_type="text/plain", representation="text")

    res = _client(store).get(_list_url())

    assert res.status_code == 409
    assert res.json()["detail"] == "artifact_unsafe"
    assert str(tmp_path) not in res.text


def test_media_type_with_crlf_is_artifact_unsafe_without_header_injection(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    _build_trial(store)
    _tamper_entry(
        store,
        "skills/authn/SKILL.md",
        media_type="text/markdown\r\nX-Injected: yes",
    )

    res = _client(store).get(_list_url())

    assert res.status_code == 409
    assert res.json()["detail"] == "artifact_unsafe"
    assert "x-injected" not in {key.lower() for key in res.headers}
    assert str(tmp_path) not in res.text


def test_path_like_artifact_id_is_artifact_not_found(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _build_trial(store)
    adapter = source_module.ArtifactStoreSnapshotSource(store)

    with pytest.raises(artifact_reader.ArtifactLookupError) as caught:
        adapter.get_artifact(TARGET, RUN, TRIAL, "../../etc/passwd")

    assert caught.value.status_code == 404
    assert caught.value.code == "artifact_not_found"
    assert str(tmp_path) not in str(caught.value)


def test_missing_file_is_artifact_missing(tmp_path: Path) -> None:
    store = tmp_path / "store"
    trial_dir = _build_trial(store)
    entry = _entries_by_path(store)["skills/authn/SKILL.md"]
    (trial_dir / PROJECT_ID / "skills/authn/SKILL.md").unlink()
    client = _client(store)

    detail = client.get(_detail_url(entry["artifact_id"]))
    content = client.get(_content_url(entry["artifact_id"]))

    assert detail.status_code == 409
    assert detail.json()["detail"] == "artifact_missing"
    assert content.status_code == 409
    assert content.json()["detail"] == "artifact_missing"
    assert str(tmp_path) not in detail.text


def test_digest_mismatch_is_artifact_digest_mismatch(tmp_path: Path) -> None:
    store = tmp_path / "store"
    trial_dir = _build_trial(store)
    entry = _entries_by_path(store)["skills/authn/SKILL.md"]
    (trial_dir / PROJECT_ID / "skills/authn/SKILL.md").write_bytes(b"changed\n")
    client = _client(store)

    detail = client.get(_detail_url(entry["artifact_id"]))
    content = client.get(_content_url(entry["artifact_id"]))

    assert detail.status_code == 409
    assert detail.json()["detail"] == "artifact_digest_mismatch"
    assert content.status_code == 409
    assert content.json()["detail"] == "artifact_digest_mismatch"
    assert str(tmp_path) not in detail.text


def test_symlink_replacement_is_artifact_unsafe(tmp_path: Path) -> None:
    store = tmp_path / "store"
    trial_dir = _build_trial(store)
    entry = _entries_by_path(store)["skills/authn/SKILL.md"]
    target = trial_dir / PROJECT_ID / "skills/authn/SKILL.md"
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"outside\n")
    target.unlink()
    target.symlink_to(outside)

    res = _client(store).get(_detail_url(entry["artifact_id"]))

    assert res.status_code == 409
    assert res.json()["detail"] == "artifact_unsafe"
    assert str(tmp_path) not in res.text


def test_unconfigured_source_refuses_artifacts_without_a_path() -> None:
    adapter = source_module.ArtifactStoreSnapshotSource(None)

    with pytest.raises(source_module.SnapshotSourceUnavailable) as caught:
        adapter.list_artifacts(TARGET, RUN, TRIAL)

    assert "/" not in str(caught.value)


def test_source_factory_injection_is_honored(tmp_path: Path) -> None:
    store = tmp_path / "store"
    _build_trial(store)
    calls = 0

    def factory() -> source_module.ArtifactStoreSnapshotSource:
        nonlocal calls
        calls += 1
        return source_module.ArtifactStoreSnapshotSource(store)

    client = TestClient(app_module.create_app(factory))

    assert client.get(_list_url()).status_code == 200
    assert calls == 1


def test_strict_endpoint_stays_the_integrity_report_for_incoherent_capture(
    tmp_path: Path,
) -> None:
    """The strict historical contract is unchanged by the resolved layer.

    An incoherent snapshot fingerprint is a resolved-layer fallback trigger, but
    the strict `/artifacts` endpoint keeps serving the manifest inventory so
    operators still have an integrity diagnostic.
    """
    store = tmp_path / "store"
    _build_trial(store)
    _tamper_entry(store, "hunting/orchestration/hunt_configs/produced/prod.yaml")

    manifest_path = store / TARGET / RUN / TRIAL / "run-manifest.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["project_artifacts"]["snapshot_sha256"] = "incoherent"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    res = _client(store).get(_list_url())
    assert res.status_code == 200
    assert res.json()["status"] == "available"
