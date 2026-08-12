from lightrag_docprep.models import RawParseResult
from lightrag_docprep.postprocessors.docling import postprocess_docling_result


def _raw(
    markdown: str,
    *,
    footnotes: list[dict] | None = None,
    page_markdown: list[str] | None = None,
) -> RawParseResult:
    return RawParseResult(
        parser_name="docling",
        parser_version="test",
        source_path="sample.pdf",
        markdown=markdown,
        source_profile="generic",
        parser_context={"footnotes": footnotes or []},
        page_markdown=page_markdown,
    )


def test_removes_empty_docling_image_placeholders_but_preserves_caption_text():
    raw = _raw(
        "# Report\n\n<!-- image -->\n\nFigure 2. Network architecture\n\nBody.\n"
    )

    result = postprocess_docling_result(raw)

    assert "<!-- image -->" not in result.markdown
    assert "Figure 2. Network architecture" in result.markdown
    assert "Body." in result.markdown


def test_removes_redundant_table_of_contents_section_only():
    raw = _raw(
        "# Report\n\n"
        "## Table of Contents\n\n"
        "| Section | Page |\n|---|---|\n| Intro | 1 |\n\n"
        "## Executive Summary\n\nKeep this.\n"
    )

    result = postprocess_docling_result(raw)

    assert "Table of Contents" not in result.markdown
    assert "| Intro | 1 |" not in result.markdown
    assert "## Executive Summary" in result.markdown
    assert "Keep this." in result.markdown


def test_removes_contents_aliases_without_matching_substantive_heading():
    raw = _raw(
        "# Report\n\n"
        "## Contents\n\nNoise\n\n"
        "## Content Security Policy\n\nKeep CSP.\n\n"
        "## List of Contents\n\nMore noise\n\n"
        "## Findings\n\nKeep findings.\n"
    )

    result = postprocess_docling_result(raw)

    assert "\n## Contents\n" not in f"\n{result.markdown}\n"
    assert "Noise" not in result.markdown
    assert "## Content Security Policy" in result.markdown
    assert "Keep CSP." in result.markdown
    assert "List of Contents" not in result.markdown
    assert "More noise" not in result.markdown
    assert "## Findings" in result.markdown


def test_normalizes_numbered_heading_hierarchy_using_top_level_anchor():
    raw = _raw(
        "# Report Title\n\n"
        "## 1. Introduction\n\nIntro.\n\n"
        "## 1.1 Scope\n\nScope.\n\n"
        "## 1.1.1 Limits\n\nLimits.\n\n"
        "## 2. Methods\n\nMethods.\n\n"
        "## Appendix A\n\nAppendix.\n"
    )

    result = postprocess_docling_result(raw)

    assert "## 1. Introduction" in result.markdown
    assert "### 1.1 Scope" in result.markdown
    assert "#### 1.1.1 Limits" in result.markdown
    assert "## 2. Methods" in result.markdown
    assert "## Appendix A" in result.markdown


def test_repairs_text_interrupted_by_native_docling_footnotes_only():
    raw = _raw(
        "## 2.2 Techniques\n\n"
        "- Target Identification Techniques include network discovery, network port and service\n\n"
        "2 Exact first footnote\n\n"
        "3 Exact second footnote\n\n"
        "identification, vulnerability scanning, and wireless scanning.\n\n"
        "Next paragraph.\n",
        footnotes=[
            {"text": "2 Exact first footnote", "page_number": 4},
            {"text": "3 Exact second footnote", "page_number": 4},
        ],
    )

    result = postprocess_docling_result(raw)

    assert (
        "- Target Identification Techniques include network discovery, network port and service "
        "identification, vulnerability scanning, and wireless scanning."
    ) in result.markdown
    assert "> 2 Exact first footnote" in result.markdown
    assert "> 3 Exact second footnote" in result.markdown
    assert result.markdown.index("wireless scanning.") < result.markdown.index("> 2 Exact first footnote")


def test_does_not_treat_unlabeled_numeric_paragraph_as_footnote():
    raw = _raw(
        "## Section\n\nBody fragment\n\n2 This looks like a note\n\ncontinuation text.\n",
        footnotes=[],
    )

    result = postprocess_docling_result(raw)

    assert "Body fragment\n\n2 This looks like a note\n\ncontinuation text." in result.markdown
    assert "> 2 This looks like a note" not in result.markdown


def test_preserves_native_footnote_in_place_when_bridge_is_not_safe():
    raw = _raw(
        "## Section\n\nThe sentence is complete.\n\n"
        "5 Exact footnote\n\nNext paragraph starts here.\n",
        footnotes=[{"text": "5 Exact footnote", "page_number": 2}],
    )

    result = postprocess_docling_result(raw)

    assert "The sentence is complete.\n\n> 5 Exact footnote\n\nNext paragraph starts here." in result.markdown


def test_native_footnote_repair_preserves_indentation_inside_fenced_code():
    raw = _raw(
        "## Example\n\n"
        "```text\n"
        "first line\n\n"
        "    indented line\n"
        "```\n\n"
        "Body fragment\n\n"
        "7 Exact footnote\n\n"
        "continuation text.\n",
        footnotes=[{"text": "7 Exact footnote", "page_number": 3}],
    )

    result = postprocess_docling_result(raw)

    assert "```text\nfirst line\n\n    indented line\n```" in result.markdown


def test_repairs_list_item_split_across_adjacent_docling_pages():
    raw = _raw(
        "## Executive Summary\n\n"
        "- Establish an assessment policy that assigns accountability to the appropriate\n\n"
        "individuals and documents required responsibilities.\n\n"
        "Next paragraph.\n",
        page_markdown=[
            "## Executive Summary\n\n- Establish an assessment policy that assigns accountability to the appropriate",
            "individuals and documents required responsibilities.\n\nNext paragraph.",
        ],
    )

    result = postprocess_docling_result(raw)

    assert (
        "- Establish an assessment policy that assigns accountability to the appropriate "
        "individuals and documents required responsibilities."
    ) in result.markdown
    assert "appropriate\n\nindividuals" not in result.markdown


def test_does_not_merge_list_continuation_when_both_blocks_are_on_same_page():
    raw = _raw(
        "## Section\n\n- Incomplete list fragment\n\ncontinuation text.\n",
        page_markdown=[
            "## Section\n\n- Incomplete list fragment\n\ncontinuation text."
        ],
    )

    result = postprocess_docling_result(raw)

    assert "- Incomplete list fragment\n\ncontinuation text." in result.markdown


def test_does_not_merge_page_break_after_complete_list_sentence():
    raw = _raw(
        "## Section\n\n- Complete list sentence.\n\ncontinuation text.\n",
        page_markdown=[
            "## Section\n\n- Complete list sentence.",
            "continuation text.",
        ],
    )

    result = postprocess_docling_result(raw)

    assert "- Complete list sentence.\n\ncontinuation text." in result.markdown


def test_does_not_merge_uppercase_paragraph_as_list_continuation():
    raw = _raw(
        "## Section\n\n- Incomplete list fragment\n\nNew paragraph starts here.\n",
        page_markdown=[
            "## Section\n\n- Incomplete list fragment",
            "New paragraph starts here.",
        ],
    )

    result = postprocess_docling_result(raw)

    assert "- Incomplete list fragment\n\nNew paragraph starts here." in result.markdown


def test_does_not_merge_list_across_heading_boundary():
    raw = _raw(
        "## Section One\n\n- Incomplete list fragment\n\n"
        "## Section Two\n\ncontinuation text.\n",
        page_markdown=[
            "## Section One\n\n- Incomplete list fragment",
            "## Section Two\n\ncontinuation text.",
        ],
    )

    result = postprocess_docling_result(raw)

    assert "- Incomplete list fragment\n\n## Section Two\n\ncontinuation text." in result.markdown
