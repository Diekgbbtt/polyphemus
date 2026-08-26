from __future__ import annotations

import re
from collections.abc import Iterable

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify

_COMMON_CONTENT_SELECTORS = (
    "article",
    "main",
    '[role="main"]',
    ".post-content",
    ".entry-content",
    ".article-content",
    ".main-content",
    ".content",
)


def select_primary_content(
    soup: BeautifulSoup,
    *,
    selectors: Iterable[str] = _COMMON_CONTENT_SELECTORS,
) -> Tag:
    for selector in selectors:
        candidate = soup.select_one(selector)
        if candidate is not None:
            return candidate
    if soup.body is not None:
        return soup.body
    return soup


def remove_structural_noise(root: Tag, *, remove_aside: bool = False) -> None:
    tags = ["script", "style", "noscript", "nav", "footer"]
    if remove_aside:
        tags.append("aside")
    for tag in root.find_all(tags):
        tag.decompose()


def to_markdown(root: Tag) -> str:
    markdown = markdownify(str(root), heading_style="ATX").replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in markdown.splitlines()]
    compact: list[str] = []
    blank = False
    for line in lines:
        if not line.strip():
            if compact and not blank:
                compact.append("")
            blank = True
            continue
        compact.append(line)
        blank = False
    return "\n".join(compact).strip()


def clean_title(value: str | None) -> str | None:
    if value is None:
        return None
    title = re.sub(r"\s+", " ", value).strip()
    return title or None
