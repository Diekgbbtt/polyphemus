from __future__ import annotations

import re

from .models import BlockKind, ContentBlock, SectionNode

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LIST_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?\s*$")
_IMAGE_RE = re.compile(
    r"^\s*!\[(?P<alt>[^\]]*)\]\([^)]+\)\s*(?:\\\s*)?(?:\*(?P<caption>[^*]+)\*)?\s*$"
)
_LINKED_IMAGE_RE = re.compile(
    r"^\s*\[!\[(?P<alt>[^\]]*)\]\([^)]+\)\]\([^)]+\)\s*$"
)
_EMPHASIZED_CAPTION_RE = re.compile(r"^\s*\*(?P<caption>Figure[^*]+)\*\s*$", re.IGNORECASE)


def _section_id(index: int, heading: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-") or "root"
    return f"section-{index:04d}-{slug[:48]}"


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return "|" in lines[index] and bool(_TABLE_SEPARATOR_RE.match(lines[index + 1]))


def parse_markdown_structure(markdown: str) -> list[SectionNode]:
    lines = markdown.splitlines()
    sections: list[SectionNode] = []
    heading_stack: list[tuple[int, str]] = []
    current: SectionNode | None = None
    i = 0

    def ensure_section() -> SectionNode:
        nonlocal current
        if current is None:
            current = SectionNode(
                section_id=_section_id(len(sections), ""),
                heading="",
                level=0,
                heading_path=[],
            )
            sections.append(current)
        return current

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        heading_match = _HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            heading = heading_match.group(2).strip()
            heading_stack = [(l, h) for l, h in heading_stack if l < level]
            heading_stack.append((level, heading))
            current = SectionNode(
                section_id=_section_id(len(sections), heading),
                heading=heading,
                level=level,
                heading_path=[h for _, h in heading_stack],
            )
            sections.append(current)
            i += 1
            continue

        section = ensure_section()

        image_match = _IMAGE_RE.match(line) or _LINKED_IMAGE_RE.match(line)
        if image_match:
            caption = (image_match.groupdict().get("caption") or "").strip()
            alt = (image_match.group("alt") or "").strip()
            next_index = i + 1
            while next_index < len(lines) and not lines[next_index].strip():
                next_index += 1
            if not caption and next_index < len(lines):
                caption_match = _EMPHASIZED_CAPTION_RE.match(lines[next_index])
                if caption_match:
                    caption = caption_match.group("caption").strip()
                    next_index += 1
            text = caption or (f"Figure: {alt}" if alt else "Figure")
            section.blocks.append(ContentBlock(kind=BlockKind.IMAGE_TEXT, content=text))
            i = next_index if caption else i + 1
            continue

        if line.lstrip().startswith("```"):
            block = [line]
            i += 1
            while i < len(lines):
                block.append(lines[i])
                if lines[i].lstrip().startswith("```"):
                    i += 1
                    break
                i += 1
            section.blocks.append(ContentBlock(kind=BlockKind.CODE, content="\n".join(block).rstrip()))
            continue

        if line.strip().startswith("$$"):
            block = [line]
            i += 1
            if line.strip() != "$$" and line.strip().endswith("$$"):
                pass
            else:
                while i < len(lines):
                    block.append(lines[i])
                    if lines[i].strip().endswith("$$"):
                        i += 1
                        break
                    i += 1
            section.blocks.append(ContentBlock(kind=BlockKind.FORMULA, content="\n".join(block).rstrip()))
            continue

        if _is_table_start(lines, i):
            block: list[str] = []
            while i < len(lines) and lines[i].strip() and "|" in lines[i]:
                block.append(lines[i].rstrip())
                i += 1
            section.blocks.append(ContentBlock(kind=BlockKind.TABLE, content="\n".join(block)))
            continue

        if _LIST_RE.match(line):
            block = []
            while i < len(lines) and lines[i].strip() and (_LIST_RE.match(lines[i]) or lines[i].startswith(("  ", "\t"))):
                block.append(lines[i].rstrip())
                i += 1
            section.blocks.append(ContentBlock(kind=BlockKind.LIST, content="\n".join(block)))
            continue

        paragraph = [line.strip()]
        i += 1
        while i < len(lines):
            candidate = lines[i]
            if not candidate.strip():
                break
            if _HEADING_RE.match(candidate) or candidate.lstrip().startswith("```"):
                break
            if candidate.strip().startswith("$$") or _is_table_start(lines, i) or _LIST_RE.match(candidate):
                break
            paragraph.append(candidate.strip())
            i += 1
        section.blocks.append(ContentBlock(kind=BlockKind.PARAGRAPH, content=" ".join(paragraph).strip()))

    return sections
