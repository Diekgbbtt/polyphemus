"""The eval data-dependency placement endpoints (multipart direct file write + L1).

Covers the four NON-IDEMPOTENT `multipart/form-data` endpoints: their contract
(`file` required, `fileName` ignored for path building), archive unpack for the
`authn` bundle (traversal rejection, overwrite, create-if-absent), validation
refusals (nothing lands), and the L1 graph persistence reuse. Endpoint tests run
real HTTP against real stores rooted at `tmp_path` (the explicit-root seam), with
no live database or graph.
"""
from __future__ import annotations

import io
import tarfile
import zipfile

import yaml
import pytest
from fastapi.testclient import TestClient

from polymerhus.app.auth.store import AuthStore
from polymerhus.app.clients import pg
from polymerhus.app.llm.skills import SkillStore
from polymerhus.app.main import app
from polymerhus.project_management import repository

client = TestClient(app)

SKILL_MD = (
    "---\n"
    "name: authn\n"
    "description: a test authn bundle\n"
    "metadata:\n"
    "  version: '1.0'\n"
    "---\n\n"
    "# authn\n\nSign in with the seeded account.\n"
)

OVERVIEW = {
    "login_endpoint": "https://app.example.com/login",
    "mechanism": "password",
    "notes": "operator ground truth",
}

CREDENTIALS = {
    "accounts": {
        "admin-first_authn_bootstrap": {
            "origin": "operator",
            "procedure": "sign-in",
            "credentials": {
                "username": "admin",
                "password": "pw",
                "login_url": "https://app.example.com/login",
            },
        }
    }
}

OPERATOR_KB = """\
# Example (1.0)

## Overview
An example application.

## Services
### account-sign-in
- contract: Authenticates a user and mints their session.
- exposure: public
### content-management
- contract: Owns the articles and their publication state.
- exposure: authenticated

## Systems
### session - cookie
- description: Cookie-based identification.

## Roles
- admin
- editor
"""


def _live_pg(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: True)


def _tmp_stores(monkeypatch, tmp_path):
    monkeypatch.setattr(repository, "_default_auth_store", lambda: AuthStore(root_dir=tmp_path))
    monkeypatch.setattr(repository, "_default_skill_store", lambda: SkillStore(root_dir=tmp_path))
    return tmp_path


def _post(project_id, artifact, data: bytes, *, filename="upload.bin",
          content_type="application/octet-stream", extra=None):
    return client.post(
        f"/projects/{project_id}/data-dependencies/{artifact}",
        files={"file": (filename, data, content_type)},
        data=extra or {},
    )


def _tar_gz(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as archive:
        for name, text in members.items():
            payload = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def _zip(members: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, text in members.items():
            archive.writestr(name, text)
    return buf.getvalue()


# --- authn skill bundle (archive) ----------------------------------------------


def test_place_authn_skill_unpacks_tar_gz_and_writes_verbatim(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)

    resp = _post("p1", "authn-skill", _tar_gz({
        "SKILL.md": SKILL_MD,
        "references/login.sh": "#!/bin/sh\necho login\n",
    }), filename="authn.tar.gz", content_type="application/gzip")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "skill": "authn",
                           "files": ["SKILL.md", "references/login.sh"]}
    bundle = tmp_path / "p1" / "skills" / "authn"
    assert (bundle / "SKILL.md").read_text() == SKILL_MD
    assert (bundle / "references" / "login.sh").read_text() == "#!/bin/sh\necho login\n"


def test_place_authn_skill_unpacks_zip_with_wrapper_prefix(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)

    resp = _post("p1", "authn-skill", _zip({
        "authn/SKILL.md": SKILL_MD,
        "authn/references/verify.sh": "#!/bin/sh\necho verify\n",
    }), filename="authn.zip", content_type="application/zip")

    assert resp.status_code == 200
    bundle = tmp_path / "p1" / "skills" / "authn"
    assert (bundle / "SKILL.md").read_text() == SKILL_MD
    assert (bundle / "references" / "verify.sh").is_file()
    # the wrapper prefix must not land as a nested directory
    assert not (bundle / "authn").exists()


def test_place_authn_skill_overwrites_and_creates_on_second_post(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)
    _post("p1", "authn-skill", _tar_gz({"SKILL.md": SKILL_MD}), filename="authn.tar.gz")

    updated = SKILL_MD.replace("Sign in with the seeded account.", "Updated procedure.")
    resp = _post("p1", "authn-skill", _tar_gz({
        "SKILL.md": updated,
        "references/verify.sh": "#!/bin/sh\necho verify\n",
    }), filename="authn.tar.gz")

    assert resp.status_code == 200
    bundle = tmp_path / "p1" / "skills" / "authn"
    assert (bundle / "SKILL.md").read_text() == updated
    assert (bundle / "references" / "verify.sh").is_file()


def test_place_authn_skill_rejects_traversal_member(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)

    resp = _post("p1", "authn-skill", _tar_gz({
        "SKILL.md": SKILL_MD, "../evil.sh": "x"}), filename="authn.tar.gz")

    assert resp.status_code == 400
    assert resp.json()["error"] == "data_dependency_invalid"
    assert not (tmp_path / "p1" / "evil.sh").exists()
    assert not (tmp_path / "p1" / "skills" / "authn" / "SKILL.md").exists()


def test_place_authn_skill_rejects_absolute_member(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)

    resp = _post("p1", "authn-skill", _zip({
        "SKILL.md": SKILL_MD, "/etc/passwd": "x"}), filename="authn.zip")

    assert resp.status_code == 400
    assert resp.json()["error"] == "data_dependency_invalid"


def test_place_authn_skill_requires_skill_md(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)

    resp = _post("p1", "authn-skill", _tar_gz({"references/login.sh": "x"}),
                 filename="authn.tar.gz")

    assert resp.status_code == 400
    assert resp.json()["error"] == "data_dependency_invalid"


def test_place_authn_skill_rejects_non_archive(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)

    resp = _post("p1", "authn-skill", b"just some text", filename="SKILL.md")

    assert resp.status_code == 400
    assert resp.json()["error"] == "data_dependency_invalid"


def test_place_authn_skill_bad_frontmatter_writes_nothing(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)

    resp = _post("p1", "authn-skill",
                 _tar_gz({"SKILL.md": SKILL_MD.replace("name: authn", "name: not-authn")}),
                 filename="authn.tar.gz")

    assert resp.status_code == 400
    assert resp.json()["error"] == "skill_invalid"
    assert not (tmp_path / "p1" / "skills" / "authn" / "SKILL.md").exists()


def test_place_authn_skill_fileName_is_not_path_authority(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)

    resp = _post("p1", "authn-skill", _tar_gz({"SKILL.md": SKILL_MD}),
                 filename="../../evil.tar.gz",
                 extra={"fileName": "../../etc/evil"})

    assert resp.status_code == 200
    assert (tmp_path / "p1" / "skills" / "authn" / "SKILL.md").read_text() == SKILL_MD
    assert not (tmp_path / "p1" / "etc").exists()


def test_place_authn_skill_unknown_project_404(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)
    assert _post("nope", "authn-skill", _tar_gz({"SKILL.md": SKILL_MD})).status_code == 404


# --- auth overview -------------------------------------------------------------


def test_place_auth_overview_writes_and_is_replace_not_merge(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)

    resp = _post("p1", "auth-overview", yaml.safe_dump(OVERVIEW).encode(),
                 filename="overview.yaml")
    assert resp.status_code == 200
    assert client.get("/projects/p1/auth").json()["overview"] == OVERVIEW

    # NON-IDEMPOTENT: the second placement replaces the whole file.
    replaced = {"mechanism": "none"}
    assert _post("p1", "auth-overview", yaml.safe_dump(replaced).encode()).status_code == 200
    got = client.get("/projects/p1/auth").json()["overview"]
    assert got == replaced
    assert "login_endpoint" not in got


def test_place_auth_overview_shape_violation_400_and_writes_nothing(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)

    resp = _post("p1", "auth-overview", yaml.safe_dump({"bogus": 1}).encode())

    assert resp.status_code == 400
    body = resp.json()
    assert body["error"] == "auth_invalid"
    assert "overview.bogus" in body["detail"]
    assert client.get("/projects/p1/auth").json()["overview"] == {}


def test_place_auth_overview_empty_file_400(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)

    assert _post("p1", "auth-overview", b"").status_code == 400


def test_place_auth_overview_unknown_project_404(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)
    assert _post("nope", "auth-overview", b"{}").status_code == 404


# --- auth credentials ----------------------------------------------------------


def test_place_auth_credentials_writes_and_replaces_wholesale(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)

    resp = _post("p1", "auth-credentials", yaml.safe_dump(CREDENTIALS).encode(),
                 filename="credentials.yaml")
    assert resp.status_code == 200
    body = client.get("/projects/p1/auth").json()
    assert set(body["accounts"]) == {"admin-first_authn_bootstrap"}
    assert body["accounts"]["admin-first_authn_bootstrap"]["origin"] == "operator"

    only_empty = {"accounts": {}}
    assert _post("p1", "auth-credentials",
                 yaml.safe_dump(only_empty).encode()).status_code == 200
    assert client.get("/projects/p1/auth").json()["accounts"] == {}


def test_place_auth_credentials_missing_origin_defaults_to_operator(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)
    no_origin = {"accounts": {"admin-first_authn_bootstrap": {
        "credentials": {"username": "admin", "password": "pw",
                        "login_url": "https://app.example.com/login"}}}}

    assert _post("p1", "auth-credentials",
                 yaml.safe_dump(no_origin).encode()).status_code == 200
    assert client.get("/projects/p1/auth").json()["accounts"][
        "admin-first_authn_bootstrap"]["origin"] == "operator"


def test_place_auth_credentials_duplicate_identity_500(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)
    creds = {"username": "u", "password": "pw", "login_url": "https://x/login"}
    two = {"accounts": {
        "u-signup": {"credentials": creds, "procedure": "sign-up"},
        "u-signin": {"credentials": creds, "procedure": "sign-in"},
    }}

    resp = _post("p1", "auth-credentials", yaml.safe_dump(two).encode())

    assert resp.status_code == 500
    assert resp.json()["error"] == "duplicate_identity"
    assert client.get("/projects/p1/auth").json()["accounts"] == {}


def test_place_auth_credentials_shape_violation_400_writes_nothing(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)
    _post("p1", "auth-credentials", yaml.safe_dump(CREDENTIALS).encode())

    bad = {"accounts": {"broken": {"credentials": {"username": "x"}}}}
    resp = _post("p1", "auth-credentials", yaml.safe_dump(bad).encode())

    assert resp.status_code == 400
    assert resp.json()["error"] == "auth_invalid"
    assert set(client.get("/projects/p1/auth").json()["accounts"]) == {
        "admin-first_authn_bootstrap"}


def test_place_auth_credentials_unknown_project_404(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)
    assert _post("nope", "auth-credentials", b"{}").status_code == 404


# --- L1 graph persistence ------------------------------------------------------


def test_place_l1_persists_through_the_deterministic_scaffold(monkeypatch):
    _live_pg(monkeypatch)
    calls = []

    def fake_scaffold(project_id, operator_kb):
        calls.append((project_id, operator_kb))
        return 3, 2

    import polymerhus.analysis.scaffold as scaffold_mod

    monkeypatch.setattr(scaffold_mod, "scaffold_project", fake_scaffold)

    resp = _post("p1", "l1", OPERATOR_KB.encode(), filename="operator_kb.md")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "services_written": 3, "systems_written": 2}
    assert calls == [("p1", OPERATOR_KB)]


def test_place_l1_zero_services_is_a_400_scaffold_refusal(monkeypatch):
    _live_pg(monkeypatch)

    resp = _post("p1", "l1", b"## Overview\nnothing here\n")

    assert resp.status_code == 400
    assert resp.json()["error"] == "scaffold_invalid"


def test_place_l1_all_zero_persistence_is_a_503(monkeypatch):
    _live_pg(monkeypatch)
    import polymerhus.analysis.scaffold as scaffold_mod

    monkeypatch.setattr(scaffold_mod, "scaffold_project", lambda pid, kb: (0, 0))

    resp = _post("p1", "l1", OPERATOR_KB.encode())

    assert resp.status_code == 503
    assert resp.json()["error"] == "l1_persist_blocked"


def test_place_l1_unknown_project_404(monkeypatch):
    monkeypatch.setattr(pg, "project_exists", lambda pid: False)
    assert _post("nope", "l1", OPERATOR_KB.encode()).status_code == 404


# --- request contract ----------------------------------------------------------


def test_missing_file_part_is_422(monkeypatch, tmp_path):
    _live_pg(monkeypatch)
    _tmp_stores(monkeypatch, tmp_path)

    resp = client.post("/projects/p1/data-dependencies/auth-overview", data={})

    # FastAPI's own required-part validation, before the handler.
    assert resp.status_code == 422


@pytest.mark.parametrize("artifact", ["authn-skill", "auth-overview", "auth-credentials", "l1"])
def test_file_part_is_required_from_openapi(artifact):
    schema = client.get("/openapi.json").json()
    body = schema["paths"][
        f"/projects/{{project_id}}/data-dependencies/{artifact}"]["post"]["requestBody"]
    multipart = body["content"]["multipart/form-data"]["schema"]
    assert multipart["required"] == ["file"]
    assert multipart["properties"]["file"] == {"type": "string", "format": "binary"}
    assert multipart["properties"]["fileName"] == {"type": "string"}
