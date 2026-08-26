from lightrag_docprep.markdown_structure import parse_markdown_structure
from lightrag_docprep.page_provenance import assign_block_page_numbers


def _blocks(markdown: str):
    sections = parse_markdown_structure(markdown)
    return sections, [block for section in sections for block in section.blocks]


def test_assigns_starting_page_from_page_local_markdown():
    sections, blocks = _blocks(
        "## Section\n\n"
        "Alpha paragraph has enough distinctive text to match page one.\n\n"
        "Beta paragraph has enough distinctive text to match page two.\n"
    )

    assign_block_page_numbers(
        sections,
        [
            "## Section\n\nAlpha paragraph has enough distinctive text to match page one.",
            "Beta paragraph has enough distinctive text to match page two.",
        ],
    )

    assert [block.page_number for block in blocks] == [1, 2]


def test_page_matching_is_monotonic_for_repeated_text():
    sections, blocks = _blocks(
        "First unique paragraph establishes the first page position.\n\n"
        "Repeated short phrase.\n\n"
        "Second unique paragraph advances the document to page two.\n\n"
        "Repeated short phrase.\n"
    )

    assign_block_page_numbers(
        sections,
        [
            "First unique paragraph establishes the first page position.\n\nRepeated short phrase.",
            "Second unique paragraph advances the document to page two.\n\nRepeated short phrase.",
        ],
    )

    assert [block.page_number for block in blocks] == [1, 1, 2, 2]


def test_unmatched_or_ambiguous_short_block_keeps_none():
    sections, blocks = _blocks("Tiny\n\nText not present on any page.\n")

    assign_block_page_numbers(
        sections,
        ["Tiny", "Tiny"],
    )

    assert blocks[0].page_number is None
    assert blocks[1].page_number is None


def test_block_spanning_pages_uses_page_where_its_prefix_starts():
    sections, blocks = _blocks(
        "- A long list item begins on page one and keeps going with enough text "
        "to continue on page two after the physical page break.\n"
    )

    assign_block_page_numbers(
        sections,
        [
            "- A long list item begins on page one and keeps going with enough text",
            "to continue on page two after the physical page break.",
        ],
    )

    assert blocks[0].page_number == 1
