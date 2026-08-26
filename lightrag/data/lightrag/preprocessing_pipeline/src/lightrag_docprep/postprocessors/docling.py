from __future__ import annotations

import re

from ..models import RawParseResult

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_NUMBERED_HEADING_RE = re.compile(r"^(?P<number>\d+(?:\.\d+)*\.?)(?:\s+)(?P<title>.+)$")
_IMAGE_PLACEHOLDER_RE = re.compile(r"^\s*<!--\s*image\s*-->\s*$", re.IGNORECASE)
_TOC_HEADINGS = frozenset({"contents", "table of contents", "list of contents"})


def _heading(line: str) -> tuple[int, str] | None:
    match = _HEADING_RE.match(line)
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def _remove_image_placeholders(lines: list[str]) -> list[str]:
    return [line for line in lines if not _IMAGE_PLACEHOLDER_RE.match(line)]


def _remove_toc_sections(lines: list[str]) -> list[str]:
    output: list[str] = []
    skip_level: int | None = None

    for line in lines:
        heading = _heading(line)
        if skip_level is not None:
            if heading is None:
                continue
            level, title = heading
            if level > skip_level:
                continue
            skip_level = None
            if title.casefold() in _TOC_HEADINGS:
                skip_level = level
                continue
            output.append(line)
            continue

        if heading is not None:
            level, title = heading
            if title.casefold() in _TOC_HEADINGS:
                skip_level = level
                continue
        output.append(line)

    return output


def _numbered_depth(title: str) -> int | None:
    match = _NUMBERED_HEADING_RE.match(title)
    if not match:
        return None
    number = match.group("number").rstrip(".")
    return len(number.split("."))


def _normalize_numbered_headings(lines: list[str]) -> list[str]:
    top_level_candidates: list[int] = []
    for line in lines:
        heading = _heading(line)
        if heading is None:
            continue
        level, title = heading
        if _numbered_depth(title) == 1:
            top_level_candidates.append(level)

    if not top_level_candidates:
        return lines

    base_level = min(top_level_candidates)
    output: list[str] = []
    for line in lines:
        heading = _heading(line)
        if heading is None:
            output.append(line)
            continue
        current_level, title = heading
        depth = _numbered_depth(title)
        if depth is None:
            output.append(line)
            continue
        target_level = min(6, base_level + depth - 1)
        if target_level == current_level:
            output.append(line)
        else:
            output.append(f"{'#' * target_level} {title}")
    return output



def _normalize_block_text(text: str) -> str:
    return " ".join(text.split())


def _is_structural_block(block: str) -> bool:
    stripped = block.lstrip()
    return (
        stripped.startswith("#")
        or stripped.startswith("```")
        or stripped.startswith("|")
        or stripped.startswith("$$")
        or stripped.startswith(">")
    )


def _can_bridge_blocks(previous: str, following: str) -> bool:
    if _is_structural_block(previous) or _is_structural_block(following):
        return False
    previous_text = previous.rstrip()
    following_text = following.lstrip()
    if not previous_text or not following_text:
        return False
    if previous_text[-1] in ".?!:;":
        return False
    first = following_text[0]
    return first.islower() or first in ",.)]}"


def _blockquote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def _repair_native_footnotes(markdown: str, footnotes: list[dict]) -> str:
    if not footnotes:
        return markdown

    native_by_normalized = {
        _normalize_block_text(str(item.get("text", ""))): str(item.get("text", "")).strip()
        for item in footnotes
        if str(item.get("text", "")).strip()
    }
    if not native_by_normalized:
        return markdown

    blocks = [block.strip("\n") for block in re.split(r"\n\s*\n", markdown) if block.strip()]
    output: list[str] = []
    index = 0
    while index < len(blocks):
        normalized = _normalize_block_text(blocks[index])
        if normalized not in native_by_normalized:
            output.append(blocks[index])
            index += 1
            continue

        footnote_run: list[str] = []
        while index < len(blocks):
            normalized = _normalize_block_text(blocks[index])
            if normalized not in native_by_normalized:
                break
            footnote_run.append(native_by_normalized[normalized])
            index += 1

        following = blocks[index] if index < len(blocks) else None
        if output and following is not None and _can_bridge_blocks(output[-1], following):
            output[-1] = f"{output[-1].rstrip()} {following.lstrip()}"
            index += 1
            output.extend(_blockquote(text) for text in footnote_run)
        else:
            output.extend(_blockquote(text) for text in footnote_run)

    return "\n\n".join(output).strip() + "\n"



_LIST_BLOCK_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
_PAGE_PROBE_LENGTHS = (160, 128, 96, 80, 64, 48, 32)


def _normalized_pages(page_markdown: list[str] | None) -> list[str]:
    if not page_markdown:
        return []
    return [_normalize_block_text(page) for page in page_markdown]


def _matching_pages_for_probe(text: str, pages: list[str], *, from_end: bool = False) -> list[int]:
    normalized = _normalize_block_text(text)
    if not normalized:
        return []
    lengths = [length for length in _PAGE_PROBE_LENGTHS if length <= len(normalized)]
    if not lengths:
        lengths = [len(normalized)]
    for length in lengths:
        probe = normalized[-length:] if from_end else normalized[:length]
        probe = probe.strip()
        matches = [index for index, page in enumerate(pages) if probe and probe in page]
        if matches:
            return matches
    return []


def _is_list_block(block: str) -> bool:
    return bool(_LIST_BLOCK_RE.match(block.lstrip()))


def _last_list_item_text(block: str) -> str:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    for line in reversed(lines):
        if _LIST_BLOCK_RE.match(line):
            return _LIST_BLOCK_RE.sub("", line, count=1).strip()
    return ""


def _is_plain_paragraph_block(block: str) -> bool:
    stripped = block.lstrip()
    if not stripped or _is_structural_block(block) or _is_list_block(block):
        return False
    return True


def _can_continue_list_item(list_block: str, paragraph_block: str) -> bool:
    tail = _last_list_item_text(list_block).rstrip()
    continuation = paragraph_block.lstrip()
    if not tail or not continuation:
        return False
    if tail[-1] in ".?!:;":
        return False
    first = continuation[0]
    return first.islower() or first in ",.)]}"


def _repair_page_break_list_continuations(
    markdown: str,
    page_markdown: list[str] | None,
) -> str:
    pages = _normalized_pages(page_markdown)
    if len(pages) < 2:
        return markdown

    blocks = [block.strip("\n") for block in re.split(r"\n\s*\n", markdown) if block.strip()]
    output: list[str] = []
    index = 0
    while index < len(blocks):
        current = blocks[index]
        following = blocks[index + 1] if index + 1 < len(blocks) else None
        if (
            following is not None
            and _is_list_block(current)
            and _is_plain_paragraph_block(following)
            and _can_continue_list_item(current, following)
        ):
            tail_text = _last_list_item_text(current)
            current_pages = _matching_pages_for_probe(tail_text, pages, from_end=True)
            following_pages = _matching_pages_for_probe(following, pages)
            adjacent_pairs = [
                (left, right)
                for left in current_pages
                for right in following_pages
                if right == left + 1
            ]
            if len(adjacent_pairs) == 1:
                output.append(f"{current.rstrip()} {following.lstrip()}")
                index += 2
                continue

        output.append(current)
        index += 1

    return "\n\n".join(output).strip() + "\n"

def _compact_blank_lines(lines: list[str]) -> str:
    output: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line.strip()
        if blank and previous_blank:
            continue
        output.append(line.rstrip())
        previous_blank = blank
    return "\n".join(output).strip() + "\n"


def postprocess_docling_result(raw: RawParseResult) -> RawParseResult:
    """Clean structural artifacts produced by Docling without semantic rewriting."""
    lines = raw.markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = _remove_image_placeholders(lines)
    lines = _remove_toc_sections(lines)
    lines = _normalize_numbered_headings(lines)
    markdown = _compact_blank_lines(lines)
    footnotes = raw.parser_context.get("footnotes", [])
    markdown = _repair_native_footnotes(markdown, footnotes)
    markdown = _repair_page_break_list_continuations(markdown, raw.page_markdown)
    return raw.model_copy(update={"markdown": markdown})
