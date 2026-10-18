"""Unit tier: the data-dependency publisher (`tools/bootstrap`).

The publisher is the link between a regeneration and an eval run: it assembles
one coherent set per target from the run's two local roots (the committed KB
root and the gitignored staging root), replaces the target's directory on the
eval host, and verifies the landing by content hash. These tests cover the
assembly contract, the refusal cases, the rsync command shape, and the landing
verification; no network is touched.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "tools" / "bootstrap" / "publish_data_dependencies.py"
)


@pytest.fixture(scope="module")
def publisher():
    spec = importlib.util.spec_from_file_location("bootstrap_publish", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # `from __future__ import annotations` stringifies the dataclass field types:
    # dataclasses resolves them through `sys.modules[cls.__module__]`, so the
    # module has to be registered before it executes.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_target(
    tmp_path: Path,
    target: str = "shop",
    *,
    credentials: bool = True,
    skill: bool = True,
    assessment: bool = True,
    kb: bool = True,
    surface: bool = True,
    overview: bool = True,
) -> tuple[Path, Path]:
    kb_dir = tmp_path / "kbs" / target
    kb_dir.mkdir(parents=True)
    if kb:
        (kb_dir / "operator_kb.md").write_text(
            f"# {target}\n\n## Overview\n\n```yaml\ndomain: {target}\n```\n",
            encoding="utf-8",
        )
        (kb_dir / "research-notes.md").write_text("notes\n", encoding="utf-8")
        (kb_dir / "surface-map.md").write_text("map\n", encoding="utf-8")
    if kb and surface:
        (kb_dir / "l1-surface.yaml").write_text("nodes: []\n", encoding="utf-8")
    if assessment:
        (kb_dir / "assessment.yaml").write_text("verdicts: []\n", encoding="utf-8")
    staging_dir = tmp_path / "staging" / target
    (staging_dir / "auth").mkdir(parents=True)
    if overview:
        (staging_dir / "auth" / "overview.yaml").write_text(
            "mechanism: form\n", encoding="utf-8"
        )
    if credentials:
        (staging_dir / "auth" / "credentials.yaml").write_text(
            "accounts: []\n", encoding="utf-8"
        )
    if skill:
        (staging_dir / "skills" / "authn").mkdir(parents=True)
        (staging_dir / "skills" / "authn" / "SKILL.md").write_text(
            "sign in\n", encoding="utf-8"
        )
    return kb_dir, staging_dir


def test_assemble_set_takes_the_designed_files_and_leaves_the_assessment_out(
    publisher, tmp_path
):
    kb_dir, staging_dir = _write_target(tmp_path)
    into = tmp_path / "assembled"
    into.mkdir()
    hashes = publisher.assemble_set(kb_dir, staging_dir, into)
    assert set(hashes) == {
        "operator_kb.md",
        "l1-surface.yaml",
        "research-notes.md",
        "surface-map.md",
        "auth/overview.yaml",
        "auth/credentials.yaml",
        "skills/authn/SKILL.md",
    }
    assert "assessment.yaml" not in hashes
    assert (into / "auth" / "credentials.yaml").is_file()


def test_assemble_set_tolerates_an_absent_credentials_and_skill(publisher, tmp_path):
    """An unauthenticated target still publishes its reviewable auth context."""
    kb_dir, staging_dir = _write_target(tmp_path, credentials=False, skill=False)
    into = tmp_path / "assembled"
    into.mkdir()
    hashes = publisher.assemble_set(kb_dir, staging_dir, into)
    assert set(hashes) == {
        "operator_kb.md",
        "l1-surface.yaml",
        "research-notes.md",
        "surface-map.md",
        "auth/overview.yaml",
    }


def test_assemble_set_refuses_an_incomplete_set(publisher, tmp_path):
    """A set that cannot drive the placement endpoints must never be published."""
    cases = (
        ("no-kb", {"kb": False}, "operator_kb.md"),
        ("no-surface", {"surface": False}, "l1-surface.yaml"),
        ("no-overview", {"overview": False}, "AuthContext"),
    )
    for name, overrides, error in cases:
        kb_dir, staging_dir = _write_target(tmp_path, name, **overrides)
        into = tmp_path / f"assembled-{name}"
        into.mkdir()
        with pytest.raises(publisher.PublishError) as excinfo:
            publisher.assemble_set(kb_dir, staging_dir, into)
        assert error in str(excinfo.value)


def test_rsync_argv_replaces_the_target_directory(publisher, tmp_path):
    argv = publisher.rsync_argv(tmp_path / "set", "srv", Path("/root/eval-dd/data/shop"))
    assert argv == [
        "rsync",
        "-a",
        "--checksum",
        "-e",
        "ssh",
        "--delete",
        f"{tmp_path / 'set'}/",
        "srv:/root/eval-dd/data/shop/",
    ]


def test_snapshot_lands_beside_the_data_root_not_inside_it(publisher, monkeypatch, tmp_path):
    """One snapshot of the whole root before any change, stored outside it."""
    calls: list[list[str]] = []

    def fake_run(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(publisher, "_run", fake_run)
    archive = publisher.snapshot("srv", Path("/root/eval-dd/data"))
    assert archive.startswith("/root/eval-dd/data-pre-publish-")
    assert archive.endswith(".tar.gz")
    assert not archive.startswith("/root/eval-dd/data/")
    assert calls == [
        ["ssh", "srv", f"tar -czf {archive} -C /root/eval-dd data"]
    ]


def test_publish_sends_one_verified_rsync(publisher, monkeypatch, tmp_path):
    kb_dir, staging_dir = _write_target(tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    calls: list[list[str]] = []

    def fake_run(argv):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(publisher, "_run", fake_run)
    monkeypatch.setattr(
        publisher,
        "_remote_hashes",
        lambda ssh, remote: publisher._hash_tree(workdir / "shop"),
    )
    result = publisher.publish(
        "shop",
        kb_dir=kb_dir,
        staging_dir=staging_dir,
        ssh="srv",
        dest=Path("/root/eval-dd/data"),
        dry_run=False,
        workdir=workdir,
    )
    assert result.published is True
    assert result.files == 7
    assert calls == [
        publisher.rsync_argv(workdir / "shop", "srv", Path("/root/eval-dd/data/shop"))
    ]


def test_publish_fails_loudly_when_the_landing_differs(publisher, monkeypatch, tmp_path):
    kb_dir, staging_dir = _write_target(tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.setattr(
        publisher,
        "_run",
        lambda argv: subprocess.CompletedProcess(argv, 0, "", ""),
    )
    monkeypatch.setattr(
        publisher, "_remote_hashes", lambda ssh, remote: {"operator_kb.md": "0" * 64}
    )
    with pytest.raises(publisher.PublishError) as excinfo:
        publisher.publish(
            "shop",
            kb_dir=kb_dir,
            staging_dir=staging_dir,
            ssh="srv",
            dest=Path("/root/eval-dd/data"),
            dry_run=False,
            workdir=workdir,
        )
    assert "landing verification failed" in str(excinfo.value)


def test_publish_dry_run_sends_nothing(publisher, monkeypatch, tmp_path):
    kb_dir, staging_dir = _write_target(tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.setattr(
        publisher, "_run", lambda argv: pytest.fail("a dry run must not touch the host")
    )
    result = publisher.publish(
        "shop",
        kb_dir=kb_dir,
        staging_dir=staging_dir,
        ssh="srv",
        dest=Path("/root/eval-dd/data"),
        dry_run=True,
        workdir=workdir,
    )
    assert result.published is False
    assert result.files == 7
