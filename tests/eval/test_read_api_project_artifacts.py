"""A project's own Hunting/Skill inventory, with no Trial in the path.

The project-scoped endpoint exists so a project no Trial has materialized can
still show what it produced. It reuses the same collector, the same allowlist
and the same validation as the per-Trial fallback, and it must keep three states
apart: a readable inventory (possibly empty), an unconfigured or unreadable data
root, and a project id that is not a path-safe segment.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orchestrator.files import FileStore
from read_api import app as app_module
from read_api import resolved_artifacts as resolved
from read_api.resolved import ResolvedDataError

# A project id from the live instance: an unassigned directory that no projected
# Trial claims.
PROJECT_ID = "6c357d47-2b7e-401e-9521-d268f2902365"

HUNTING_FILES = {
    "hunting/orchestration/hunt_configs/produced/prod.yaml": b"kind: hunt-config\n",
    "hunting/test-executor-pod/spec-1/export.yaml": b"kind: pod-export\n",
}
SKILL_FILES = {
    "skills/authn/SKILL.md": b"# Authn skill\n",
}


def _write_project(data_root: Path, project_id: str) -> None:
    for relative, data in {**HUNTING_FILES, **SKILL_FILES}.items():
        path = data_root / project_id / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _resolve(data_root: str | Path | None, project_id: str = PROJECT_ID) -> dict:
    inventory = resolved.resolve_project_inventory(
        data_root, project_id, files=FileStore()
    )
    return resolved.project_inventory_response(inventory)


def _entries(groups: list[dict]) -> list[dict]:
    """Every entry under a group tree; containers are never counted."""
    found: list[dict] = []
    for group in groups:
        found.extend(group.get("entries", []))
        found.extend(_entries(group.get("children", [])))
    return found


def test_serves_the_projects_own_hunting_and_skill_inventory(tmp_path):
    _write_project(tmp_path, PROJECT_ID)

    body = _resolve(tmp_path)

    assert body["status"] == "available"
    assert body["source"] == "project_storage"
    assert body["project_id"] == PROJECT_ID
    assert body["fallback_reason"] is None
    entries = _entries(body["groups"])
    assert {entry["relative_path"] for entry in entries} == set(HUNTING_FILES) | set(
        SKILL_FILES
    )
    assert {entry["category"] for entry in entries} == {"hunting", "skill"}
    # Every file is the project's own current tree, and the internal read handle
    # never reaches the wire.
    assert {entry["origin"] for entry in entries} == {"current"}
    assert all("source_path" not in entry for entry in entries)


def test_a_project_with_no_directory_is_an_empty_success(tmp_path):
    body = _resolve(tmp_path, "a-project-with-no-directory")

    # Nothing on disk is a readable empty inventory, not an error: the project
    # and the data root are both fine, there is simply nothing there yet.
    assert body["status"] == "available"
    assert body["project_id"] == "a-project-with-no-directory"
    assert _entries(body["groups"]) == []


def test_an_unconfigured_or_missing_data_root_is_unavailable(tmp_path):
    unconfigured = _resolve(None)
    assert unconfigured["status"] == "unavailable"
    assert unconfigured["reason"] == "project_data_unavailable"

    missing = _resolve(tmp_path / "absent")
    assert missing["status"] == "unavailable"
    assert missing["reason"] == "project_data_unavailable"


@pytest.mark.parametrize("unsafe", ["..", ".", "a/b", ""])
def test_an_unsafe_project_id_is_a_client_error(tmp_path, unsafe):
    with pytest.raises(ResolvedDataError) as caught:
        resolved.resolve_project_inventory(tmp_path, unsafe, files=FileStore())

    assert caught.value.code == "invalid_project_id"
    assert caught.value.status_code == 400


def test_a_symlinked_project_root_is_coded_not_served(tmp_path):
    (tmp_path / PROJECT_ID).symlink_to(tmp_path)

    body = _resolve(tmp_path)

    assert body["status"] == "unavailable"
    assert body["reason"] == "artifact_unsafe"
    assert body["groups"] == []


def test_the_route_serves_the_project_inventory(tmp_path, monkeypatch):
    _write_project(tmp_path, PROJECT_ID)
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("EVAL_PROJECT_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("EVAL_ARTIFACT_STORE", str(store))
    client = TestClient(app_module.create_app())

    response = client.get(f"/projects/{PROJECT_ID}/artifacts")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "available"
    assert body["project_id"] == PROJECT_ID
    assert {entry["relative_path"] for entry in _entries(body["groups"])} == set(
        HUNTING_FILES
    ) | set(SKILL_FILES)

    # A project the root does not hold is the same success with nothing in it.
    empty = client.get("/projects/another-project/artifacts")
    assert empty.status_code == 200
    assert empty.json()["status"] == "available"
    assert _entries(empty.json()["groups"]) == []
