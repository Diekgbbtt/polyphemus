"""The documentation link check (T10b #397).

Every relative Markdown link in the repo must resolve to an existing path. A
link with a `#anchor` must also name a heading in the destination Markdown
file (GitHub's slug shape: lower-cased, punctuation stripped, spaces to `-`).

External URLs (`http`, `https`, `mailto`) and bare anchors are out of scope.
The check is a guard against a sweep that retires a doc or renames a heading
without updating its referrers.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")


def _strip_code(text: str) -> str:
    """Drop fenced blocks and inline code spans before link scanning.

    A code payload such as a Jinja call can contain literal ``](...)``; it is
    not a Markdown link. Scanning code as prose is a false positive, not a
    documentation defect."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`]*`", "", text)


def _markdown_files() -> list[Path]:
    return [
        path
        for path in REPO_ROOT.rglob("*.md")
        if ".venv" not in path.parts and ".git" not in path.parts
    ]


def _slug(heading: str) -> str:
    text = re.sub(r"[`*_~]", "", heading.strip().lower())
    text = re.sub(r"[^a-z0-9\- ]", "", text)
    return text.replace(" ", "-")


def _headings(path: Path) -> set[str]:
    headings: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.match(r"^#{1,6}\s+(.*)$", line)
        if match:
            headings.add(_slug(match.group(1)))
    return headings


def test_every_relative_markdown_link_resolves():
    broken: list[str] = []
    for path in _markdown_files():
        text = _strip_code(path.read_text(encoding="utf-8", errors="ignore"))
        for raw in _LINK.findall(text):
            target = raw.strip()
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = target.split(" ", 1)[0]
            file_part, _, anchor = target.partition("#")
            destination = (
                (path.parent / file_part).resolve() if file_part else path
            )
            relative = path.relative_to(REPO_ROOT)
            if not destination.exists():
                broken.append(f"{relative}: missing link target {raw!r}")
                continue
            if anchor and destination.suffix == ".md":
                if anchor.lower() not in _headings(destination):
                    broken.append(
                        f"{relative}: missing anchor #{anchor} in {raw!r}"
                    )
    assert not broken, "\n".join(broken)
