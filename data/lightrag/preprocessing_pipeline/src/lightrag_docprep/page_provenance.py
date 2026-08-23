from __future__ import annotations

from .models import SectionNode

_MIN_PREFIX_LENGTH = 32
_PREFIX_LENGTHS = (160, 128, 96, 80, 64, 48, 32)


def _normalize_for_match(text: str) -> str:
    lines: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").splitlines():
        stripped = line.strip()
        if stripped.startswith(">"):
            stripped = stripped[1:].lstrip()
        if stripped:
            lines.append(stripped)
    return " ".join(" ".join(lines).split())


def _candidate_pages(text: str, normalized_pages: list[str]) -> list[int]:
    normalized = _normalize_for_match(text)
    if not normalized:
        return []

    if len(normalized) < _MIN_PREFIX_LENGTH:
        return [index for index, page in enumerate(normalized_pages) if normalized in page]

    for length in _PREFIX_LENGTHS:
        if length > len(normalized):
            continue
        probe = normalized[:length].rstrip()
        candidates = [
            index for index, page in enumerate(normalized_pages) if probe in page
        ]
        if candidates:
            return candidates
    return []


def assign_block_page_numbers(
    sections: list[SectionNode],
    page_markdown: list[str],
) -> None:
    """Assign best-effort starting pages without guessing ambiguous matches."""
    if not page_markdown:
        return

    normalized_pages = [_normalize_for_match(page) for page in page_markdown]
    current_page_index: int | None = None

    for section in sections:
        for block in section.blocks:
            candidates = _candidate_pages(block.content, normalized_pages)
            if not candidates:
                continue

            if current_page_index is not None:
                forward_candidates = [
                    index for index in candidates if index >= current_page_index
                ]
                if current_page_index in forward_candidates:
                    chosen = current_page_index
                elif len(forward_candidates) == 1:
                    chosen = forward_candidates[0]
                else:
                    continue
            elif len(candidates) == 1:
                chosen = candidates[0]
            else:
                continue

            block.page_number = chosen + 1
            current_page_index = chosen
