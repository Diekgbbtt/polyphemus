"""The apt-snapshot patcher: pins Debian sources so EOL suites still build."""
from __future__ import annotations

import apt_snapshot


SAMPLE = """\
FROM php:7.3-apache
RUN apt-get update && apt-get install -y curl
CMD ["apache2-foreground"]
"""


def test_patch_dockerfile_inserts_the_block_after_from() -> None:
    patched = apt_snapshot.patch_dockerfile(SAMPLE, "20260815T000000Z")

    assert apt_snapshot.MARKER in patched
    assert "snapshot.debian.org/archive/debian/20260815T000000Z" in patched
    assert "snapshot.debian.org/archive/debian-security/20260815T000000Z" in patched
    assert "[check-valid-until=no]" in patched
    # The block lands after FROM and before the first RUN.
    assert patched.index("FROM php:7.3-apache") < patched.index(apt_snapshot.MARKER)
    assert patched.index(apt_snapshot.MARKER) < patched.index("RUN apt-get update")
    # The original content is preserved.
    assert 'CMD ["apache2-foreground"]' in patched


def test_patch_dockerfile_is_idempotent() -> None:
    once = apt_snapshot.patch_dockerfile(SAMPLE, "20260815T000000Z")
    twice = apt_snapshot.patch_dockerfile(once, "20260815T000000Z")

    assert twice == once


def test_patch_dockerfile_leaves_a_dockerfile_without_apt_alone() -> None:
    text = "FROM alpine:3.20\nCMD [\"true\"]\n"

    assert apt_snapshot.patch_dockerfile(text, "20260815T000000Z") == text


def test_patch_dockerfile_handles_every_stage() -> None:
    text = (
        "FROM node:20-bookworm AS builder\n"
        "RUN apt-get install -y build-essential\n"
        "FROM nginx:1.27.0-alpine\n"
        "COPY --from=builder /app /app\n"
    )

    patched = apt_snapshot.patch_dockerfile(text, "20260815T000000Z")

    assert patched.count(apt_snapshot.MARKER) == 2


def test_patch_tree_finds_and_patches_only_apt_dockerfiles(tmp_path) -> None:
    (tmp_path / "target").mkdir()
    apt = tmp_path / "target" / "Dockerfile"
    apt.write_text(SAMPLE, encoding="utf-8")
    plain = tmp_path / "target" / "Dockerfile.plain"
    plain.write_text("FROM alpine:3.20\n", encoding="utf-8")
    ignored = tmp_path / ".git"
    ignored.mkdir()
    (ignored / "Dockerfile").write_text(SAMPLE, encoding="utf-8")

    changed = apt_snapshot.patch_tree(tmp_path, "20260815T000000Z")

    assert changed == [apt]
    assert apt_snapshot.MARKER in apt.read_text(encoding="utf-8")
    assert apt_snapshot.MARKER not in plain.read_text(encoding="utf-8")
    # A second run is a no-op.
    assert apt_snapshot.patch_tree(tmp_path, "20260815T000000Z") == []


def test_main_rejects_a_missing_root(tmp_path) -> None:
    assert apt_snapshot.main([str(tmp_path / "nope")]) == 2
