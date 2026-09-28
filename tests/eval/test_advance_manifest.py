"""Unit tests for the eval stack manifest (`eval/advance/manifest.py`).

The manifest is one SHA per alignment-relevant path group at a given commit,
plus an injected map of the running images' digests. The git access is
injected; most tests build a tiny temp repo with real git, which is the
end-to-end shape the daemon will use.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from advance import images, manifest

DIGESTS = {
    "postgres": "sha256:" + "1" * 64,
    "neo4j": "sha256:" + "2" * 64,
    "lightrag": "sha256:" + "3" * 64,
    "kali": "sha256:" + "4" * 64,
    "litellm": "sha256:" + "5" * 64,
    "agent": "sha256:" + "6" * 64,
}

# The reviewed map, one group name per artifact class (ADR section 4).
CLASSES = {
    "src": "agent_code",
    "skills": "agent_code",
    "lightrag": "agent_code",
    "kali": "exec_plane",
    "gateway": "gateway",
    "compose": "topology_env",
    "env_schema": "config_schema",
    "db": "schema_data_layout",
    "data_root_layout": "schema_data_layout",
    "requirements": "platform",
    "pyproject": "platform",
    "dependency_locks": "platform",
    "image_definitions": "image_definition",
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "eval@example.invalid")
    git(tmp_path, "config", "user.name", "eval test")
    return tmp_path


def write(repo: Path, rel: str, text: str) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def commit(repo: Path, message: str = "change") -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


def entry(manifest_obj: manifest.StackManifest, name: str) -> manifest.ManifestEntry:
    return next(e for e in manifest_obj.entries if e.name == name)


def test_manifest_covers_the_documented_path_set(repo: Path) -> None:
    samples = {
        "src/polymerhus/app.py": "src",
        "skills/foo/SKILL.md": "skills",
        "lightrag/pipeline.py": "lightrag",
        "kali/entrypoint.sh": "kali",
        "gateway/litellm_config.yaml": "gateway",
        "docker-compose.yml": "compose",
        "docker-compose.dev.yml": "compose",
        ".env.example": "env_schema",
        "db/postgres/init.sql": "db",
        "src/polymerhus/app/data_root.py": "data_root_layout",
        "requirements-app.txt": "requirements",
        "pyproject.toml": "pyproject",
        "skills-lock.json": "dependency_locks",
        "Dockerfile": "image_definitions",
        "Dockerfile.kali": "image_definitions",
        "kali/Dockerfile": "image_definitions",
    }
    for rel in samples:
        write(repo, rel, "x\n")
    sha = commit(repo)

    result = manifest.build_manifest(repo, sha, DIGESTS)

    assert {e.name for e in result.entries} == set(CLASSES)
    for name, artifact_class in CLASSES.items():
        assert entry(result, name).artifact_class == artifact_class
    for rel, group in samples.items():
        assert rel in entry(result, group).paths, (rel, group)
    assert result.image_digests == DIGESTS


def test_specific_groups_win_over_their_parent_directory(repo: Path) -> None:
    write(repo, "src/polymerhus/app/data_root.py", "layout\n")
    write(repo, "src/polymerhus/app/other.py", "code\n")
    write(repo, "kali/entrypoint.sh", "boot\n")
    write(repo, "kali/Dockerfile", "FROM base\n")
    sha = commit(repo)

    result = manifest.build_manifest(repo, sha, DIGESTS)

    assert "src/polymerhus/app/data_root.py" not in entry(result, "src").paths
    assert "kali/Dockerfile" not in entry(result, "kali").paths


def test_change_in_alignment_artifact_changes_only_its_group(repo: Path) -> None:
    write(repo, "src/polymerhus/app.py", "one\n")
    write(repo, "gateway/litellm_config.yaml", "model_list: []\n")
    first = commit(repo)
    before = manifest.build_manifest(repo, first, DIGESTS)

    write(repo, "src/polymerhus/app.py", "two\n")
    second = commit(repo)
    after = manifest.build_manifest(repo, second, DIGESTS)

    assert entry(before, "src").sha != entry(after, "src").sha
    assert entry(before, "gateway").sha == entry(after, "gateway").sha


def test_unrelated_change_leaves_every_group_sha_unchanged(repo: Path) -> None:
    write(repo, "src/polymerhus/app.py", "one\n")
    first = commit(repo)
    before = manifest.build_manifest(repo, first, DIGESTS)

    write(repo, "docs/notes.md", "unrelated\n")
    second = commit(repo)
    after = manifest.build_manifest(repo, second, DIGESTS)

    assert [(e.name, e.sha) for e in before.entries] == [
        (e.name, e.sha) for e in after.entries
    ]
    assert before.image_digests == after.image_digests


def test_kali_dockerfile_change_is_an_image_definition_not_exec_plane(repo: Path) -> None:
    write(repo, "kali/entrypoint.sh", "boot\n")
    write(repo, "kali/Dockerfile", "FROM base\n")
    first = commit(repo)
    before = manifest.build_manifest(repo, first, DIGESTS)

    write(repo, "kali/Dockerfile", "FROM other\n")
    second = commit(repo)
    after = manifest.build_manifest(repo, second, DIGESTS)

    assert entry(before, "image_definitions").sha != entry(after, "image_definitions").sha
    assert entry(before, "kali").sha == entry(after, "kali").sha


def test_data_root_layout_change_is_schema_not_agent_code(repo: Path) -> None:
    write(repo, "src/polymerhus/app/data_root.py", "layout\n")
    write(repo, "src/polymerhus/app/other.py", "code\n")
    first = commit(repo)
    before = manifest.build_manifest(repo, first, DIGESTS)

    write(repo, "src/polymerhus/app/data_root.py", "layout changed\n")
    second = commit(repo)
    after = manifest.build_manifest(repo, second, DIGESTS)

    assert (
        entry(before, "data_root_layout").sha
        != entry(after, "data_root_layout").sha
    )
    assert entry(before, "src").sha == entry(after, "src").sha


def test_single_object_group_reports_the_git_object_sha(repo: Path) -> None:
    write(repo, ".env.example", "AAA=one\n")
    sha = commit(repo)

    result = manifest.build_manifest(repo, sha, DIGESTS)

    expected = git(repo, "rev-parse", f"{sha}:.env.example").strip()
    assert entry(result, "env_schema").sha == expected


def test_git_access_is_injectable(tmp_path: Path) -> None:
    seen: list[list[str]] = []

    def fake_git(repo: Path, args):
        seen.append(list(args))
        return images.CommandResult(0, "100644 blob deadbeef\t.env.example\0")

    result = manifest.build_manifest(
        tmp_path, "some-commit", DIGESTS, git_runner=fake_git
    )

    assert seen[0] == ["ls-tree", "-r", "-z", "some-commit"]
    assert entry(result, "env_schema").sha == "deadbeef"


def test_unknown_commit_fails_closed(repo: Path) -> None:
    write(repo, "src/polymerhus/app.py", "one\n")
    commit(repo)

    with pytest.raises(manifest.ManifestError, match="deadbeef"):
        manifest.build_manifest(repo, "deadbeef", DIGESTS)
