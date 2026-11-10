import json
import sys
from pathlib import Path

import pytest

from polymerhus.recon.js_acquisition.structure import (
    StructureLimits,
    StructureParseError,
    parse_structure_bytes,
)


FIXTURES = (
    Path(__file__).resolve().parents[3]
    / "data/js-analysis-mvp-eval/bundle-structure-comparison/fixtures"
)


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _items(parsed, kind: str):
    return [item for item in parsed.items if item["kind"] == kind]


def test_esm_imports_bind_original_utf8_spans_with_unicode():
    parsed = parse_structure_bytes(_fixture("esm-controlled.js"))

    assert parsed.format == "esm"
    assert parsed.status == "complete"
    imports = _items(parsed, "import")
    static = [item for item in imports if item["subtype"] == "static"]
    dynamic = [item for item in imports if item["subtype"] == "dynamic"]
    assert {item["specifier"] for item in static} == {
        "./dep.js",
        "./named.js",
        "/absolute/ns.js",
        "./side-effect.js",
    }
    assert len(dynamic) == 2
    literal = next(item for item in dynamic if item["specifier"] == "./lazy.js")
    unresolved = next(item for item in dynamic if not item["resolved"])
    assert (literal["start_byte"], literal["end_byte"]) == (266, 277)
    assert (literal["start_utf16"], literal["end_utf16"]) == (263, 274)
    assert unresolved["expression"] == "dynamicName"
    assert unresolved["specifier"] is None


def test_webpack_shapes_distinguish_modules_chunks_and_runtime_ids():
    runtime = parse_structure_bytes(_fixture("webpack3-runtime.js"))
    webpack3 = parse_structure_bytes(_fixture("webpack3-context-a.js"))
    webpack4 = parse_structure_bytes(_fixture("webpack4-controlled.js"))
    webpack5 = parse_structure_bytes(_fixture("webpack5-controlled.js"))

    assert runtime.format == "webpack_runtime"
    runtime_loader = _items(runtime, "loader")
    state = next(item for item in runtime_loader if item["subtype"] == "runtime_state")
    assert state["runtime_ids"] == ["0", "3", "9"]

    assert webpack3.format == "webpack3"
    assert webpack4.format == "webpack4"
    assert webpack5.format == "webpack5"
    assert {
        item["module_id"] for item in _items(webpack3, "module")
    } == {"dup", "dep"}
    assert {
        item["module_id"] for item in _items(webpack4, "module")
    } == {"w4a", "w4b"}
    assert {
        item["module_id"] for item in _items(webpack5, "module")
    } == {"w5a", "w5b"}
    chunk = _items(webpack5, "chunk")[0]
    assert chunk["chunk_ids"] == ["5"]
    assert chunk["runtime_key"].startswith("webpack5:")
    assert chunk["runtime_key"] not in chunk["chunk_ids"]


def test_scope_binding_rejects_shadowing_reassignment_and_alias_guessing():
    source = b"""
window.webpackJsonp([1], {
  "bound": function(module, exports, load) {
    load("direct");
    function nested(load) { load("shadow-param"); }
    { let load = function() {}; load("shadow-block"); }
    try {} catch (load) { load("shadow-catch"); }
    { const { loader: load } = value; load("shadow-destructure"); }
    function captured() { return load("captured"); }
    const alias = load;
    alias("alias-unsupported");
  },
  "reassigned": function(module, exports, load) {
    load("before-reassignment");
    load = replacement;
    load("after-reassignment");
  }
}, ["bound"]);
"""

    parsed = parse_structure_bytes(source)
    dependencies = _items(parsed, "dependency")

    assert {
        item["target_module_id"]
        for item in dependencies
        if item.get("context_module_id") == "bound"
    } == {"direct", "captured"}
    assert not any(
        item.get("context_module_id") == "reassigned"
        for item in dependencies
    )
    assert "unsupported_alias_dataflow" in parsed.gaps
    assert "reassigned_loader_binding" in parsed.gaps


def test_duplicate_module_id_in_two_registrations_keeps_context():
    parsed = parse_structure_bytes(_fixture("webpack3-context-a.js"))
    second = parse_structure_bytes(_fixture("webpack3-context-b.js"))

    first_dup = next(
        item for item in _items(parsed, "module")
        if item["module_id"] == "dup"
    )
    second_dup = next(
        item for item in _items(second, "module")
        if item["module_id"] == "dup"
    )
    assert first_dup["context"]["chunk_ids"] == ["3"]
    assert second_dup["context"]["chunk_ids"] == ["9"]
    assert first_dup["occurrence_key"] != second_dup["occurrence_key"]


def test_malformed_and_unknown_inputs_are_explicit():
    malformed = parse_structure_bytes(_fixture("malformed.js"))
    unknown = parse_structure_bytes(_fixture("unknown-format.js"))

    assert malformed.status == "failed"
    assert malformed.parse_errors
    assert malformed.format == "unknown"
    assert unknown.status == "unsupported"
    assert unknown.format == "unknown"
    assert unknown.gaps == ("unsupported_format",)


def test_crlf_and_non_bmp_offsets_are_original_utf8_bytes():
    source = (
        "// 😀\r\n"
        "export const x = import(\"./after-crlf.js\");\r\n"
    ).encode()
    parsed = parse_structure_bytes(source)
    item = next(
        item for item in _items(parsed, "import")
        if item["subtype"] == "dynamic"
    )

    decoded = source.decode()
    prefix = decoded[:decoded.index('"./after-crlf.js"')]
    expected_utf16 = len(prefix.encode("utf-16-le")) // 2
    expected_byte = len(prefix.encode())
    assert item["start_utf16"] == expected_utf16
    assert item["start_byte"] == expected_byte
    assert source[item["start_byte"]:item["start_byte"] + 1] == b'"'


def test_item_and_index_caps_preserve_partial_status():
    parsed = parse_structure_bytes(
        _fixture("webpack3-context-a.js"),
        limits=StructureLimits(max_items=1, max_index_bytes=4096),
    )

    assert parsed.status == "partial"
    assert len(parsed.items) == 1
    assert "item_limit" in parsed.gaps


def test_parser_timeout_and_output_limit_are_bounded(tmp_path):
    slow = tmp_path / "slow.mjs"
    slow.write_text("import time\ntime.sleep(5)\n")
    with pytest.raises(StructureParseError) as timeout:
        parse_structure_bytes(
            _fixture("esm-controlled.js"),
            parser_command=[sys.executable, str(slow)],
            limits=StructureLimits(parser_timeout_s=0.1),
        )
    assert timeout.value.reason == "parser_timeout"

    output = tmp_path / "output.py"
    output.write_text(
        "import sys\n"
        "sys.stdout.write('x' * 10000)\n"
    )
    with pytest.raises(StructureParseError) as overflow:
        parse_structure_bytes(
            _fixture("esm-controlled.js"),
            parser_command=[sys.executable, str(output)],
            limits=StructureLimits(max_parser_output_bytes=1024),
        )
    assert overflow.value.reason == "parser_output_limit"
