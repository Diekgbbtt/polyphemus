import hashlib
import json
import sys
from pathlib import Path

import pytest

from polymerhus.recon.js_acquisition.recovery import (
    SourceMapParseError,
    SourceMapParseLimits,
    artifact_file_name,
    parse_map_bytes,
)


FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "data/js-analysis-mvp-eval/sourcemap-extractors-comparison/fixtures.json"
)


def _fixture(name: str) -> bytes:
    value = json.loads(FIXTURES.read_text())[name]
    return json.dumps(value["map"], separators=(",", ":")).encode()


def _parse(name: str, *, map_url="https://app.example.test/assets/bundle.js.map"):
    return parse_map_bytes(_fixture(name), map_url=map_url)


def test_complete_v3_preserves_content_hashes_and_empty_is_available():
    parsed = _parse("v3_embedded")

    assert [row.source_ordinal for row in parsed.occurrences] == [0, 1]
    assert [row.section_path for row in parsed.occurrences] == [(), ()]
    assert parsed.occurrences[0].raw_name == "src/app.js"
    assert parsed.occurrences[0].resolved_source.endswith(
        "/assets/src/app.js"
    )
    assert (
        parsed.occurrences[0].content_sha256
        == hashlib.sha256(b"export const app = 'v3-embedded';\n").hexdigest()
    )
    assert artifact_file_name(parsed.occurrences[0].content_sha256) == (
        parsed.occurrences[0].content_sha256 + ".js"
    )


def test_index_sections_and_duplicate_exact_names_keep_occurrences():
    parsed = _parse("section_same_name")

    assert len(parsed.occurrences) == 2
    assert [row.section_path for row in parsed.occurrences] == [(0,), (1,)]
    assert [row.raw_name for row in parsed.occurrences] == [
        "shared.js",
        "shared.js",
    ]
    assert [row.content_state for row in parsed.occurrences] == ["text", "text"]
    assert parsed.occurrences[0].content != parsed.occurrences[1].content


def test_source_root_and_virtual_names_keep_raw_and_resolved_metadata():
    parsed = _parse("source_root_relative")

    app, virtual = parsed.occurrences
    assert app.raw_name == "app.js"
    assert app.resolved_source == "https://app.example.test/assets/src/app.js"
    assert virtual.raw_name == "webpack:///virtual/widget.js"
    assert "webpack" in virtual.resolved_source


def test_null_missing_and_empty_are_distinct():
    parsed = _parse("content_edge_cases")
    states = {
        row.raw_name: row.content_state for row in parsed.occurrences
    }

    assert states == {
        "null.js": "null",
        "empty.js": "empty",
        "missing.js": "missing",
        "also-missing.js": "missing",
    }
    empty = next(
        row for row in parsed.occurrences if row.raw_name == "empty.js"
    )
    assert empty.content == b""
    assert empty.size == 0
    assert empty.content_sha256 == hashlib.sha256(b"").hexdigest()


def test_short_content_array_is_valid_but_missing():
    parsed = _parse("inconsistent_lengths")

    assert [(row.raw_name, row.content_state) for row in parsed.occurrences] == [
        ("first.js", "text"),
        ("second.js", "missing"),
    ]


def test_invalid_source_type_is_rejected_not_coerced():
    with pytest.raises(SourceMapParseError) as exc:
        _parse("inconsistent_types")

    assert exc.value.reason == "invalid_source_type"


def test_traversal_like_names_are_metadata_only():
    parsed = _parse("dangerous_paths")

    assert [row.raw_name for row in parsed.occurrences] == [
        "/absolute/root.js",
        "../../escape.js",
        "safe/../normalized.js",
        "normalized.js",
        "C:\\temp\\windows.js",
    ]
    assert all(
        artifact_file_name(row.content_sha256).endswith(".js")
        and "/" not in artifact_file_name(row.content_sha256)
        and "\\" not in artifact_file_name(row.content_sha256)
        for row in parsed.occurrences
    )


def test_nested_sections_are_walked_with_depth_and_ordinal():
    nested = {
        "version": 3,
        "sections": [
            {
                "offset": {"line": 0, "column": 0},
                "map": {
                    "version": 3,
                    "sections": [
                        {
                            "offset": {"line": 0, "column": 0},
                            "map": {
                                "version": 3,
                                "sources": ["nested.js"],
                                "sourcesContent": ["nested\n"],
                                "names": [],
                                "mappings": "",
                            },
                        }
                    ],
                },
            }
        ],
    }

    parsed = parse_map_bytes(
        json.dumps(nested).encode(),
        map_url="https://app.example.test/bundle.js.map",
    )

    assert parsed.occurrences[0].section_path == (0, 0)
    assert parsed.occurrences[0].content == b"nested\n"


def test_section_depth_and_source_count_limits_are_explicit():
    too_deep = {
        "version": 3,
        "sections": [
            {
                "offset": {"line": 0, "column": 0},
                "map": {
                    "version": 3,
                    "sections": [
                        {
                            "offset": {"line": 0, "column": 0},
                            "map": {"version": 3, "sources": [], "sourcesContent": [], "names": [], "mappings": ""},
                        }
                    ],
                },
            }
        ],
    }
    with pytest.raises(SourceMapParseError) as depth:
        parse_map_bytes(
            json.dumps(too_deep).encode(),
            map_url="https://app.example.test/map",
            limits=SourceMapParseLimits(max_section_depth=1),
        )
    assert depth.value.reason == "section_depth_limit"

    too_many = {
        "version": 3,
        "sources": ["a.js", "b.js"],
        "sourcesContent": ["a", "b"],
        "names": [],
        "mappings": "",
    }
    parsed = parse_map_bytes(
        json.dumps(too_many).encode(),
        map_url="https://app.example.test/map",
        limits=SourceMapParseLimits(max_occurrences=1),
    )
    assert len(parsed.occurrences) == 1
    assert "source_count_limit" in parsed.gaps


def test_map_and_source_byte_limits_are_enforced_before_parse():
    with pytest.raises(SourceMapParseError) as map_limit:
        parse_map_bytes(
            b"{}" * 20,
            map_url="https://app.example.test/map",
            limits=SourceMapParseLimits(max_map_bytes=10),
        )
    assert map_limit.value.reason == "map_size_limit"

    source_too_large = {
        "version": 3,
        "sources": ["large.js"],
        "sourcesContent": ["x" * 20],
        "names": [],
        "mappings": "",
    }
    with pytest.raises(SourceMapParseError) as source_limit:
        parse_map_bytes(
            json.dumps(source_too_large).encode(),
            map_url="https://app.example.test/map",
            limits=SourceMapParseLimits(max_source_bytes=10),
        )
    assert source_limit.value.reason == "source_size_limit"


def test_invalid_json_and_index_structure_fail_explicitly():
    with pytest.raises(SourceMapParseError) as invalid_json:
        parse_map_bytes(b"{", map_url="https://app.example.test/map")
    assert invalid_json.value.reason == "invalid_map_json"

    invalid_index = {
        "version": 3,
        "sections": [
            {
                "offset": {"line": 0, "column": 0},
                "url": "https://app.example.test/remote.map",
            }
        ],
    }
    parsed = parse_map_bytes(
        json.dumps(invalid_index).encode(),
        map_url="https://app.example.test/map",
    )
    assert parsed.occurrences == ()
    assert parsed.gaps == ("unsupported_external_section",)


def test_parser_timeout_and_output_limit_are_bounded(tmp_path):
    slow = tmp_path / "slow.mjs"
    slow.write_text("import time\ntime.sleep(5)\n")
    with pytest.raises(SourceMapParseError) as timeout:
        parse_map_bytes(
            _fixture("v3_embedded"),
            map_url="https://app.example.test/map",
            parser_command=[sys.executable, str(slow)],
            limits=SourceMapParseLimits(parser_timeout_s=0.1),
        )
    assert timeout.value.reason == "parser_timeout"

    output = tmp_path / "output.py"
    output.write_text(
        "import sys\n"
        "sys.stdout.write('x' * 10000)\n"
    )
    with pytest.raises(SourceMapParseError) as overflow:
        parse_map_bytes(
            _fixture("v3_embedded"),
            map_url="https://app.example.test/map",
            parser_command=[sys.executable, str(output)],
            limits=SourceMapParseLimits(max_parser_output_bytes=1024),
        )
    assert overflow.value.reason == "parser_output_limit"
