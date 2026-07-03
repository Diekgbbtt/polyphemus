# tests/recon/test_parser_robustness.py
"""Fleet-wide parser robustness regression net (SP2 Task 11).

Two crash classes, found during per-tool reviews, generalised fleet-wide:

1. Non-dict JSON line: a syntactically-valid-but-non-dict JSON line (e.g.
   `42`, `[1,2,3]`, `"a"`, `null`) must never abort `parse()` - it should be
   silently skipped, and every delta already accumulated for prior lines
   must still be returned.
2. Non-string field value: a valid dict whose field value is a non-string
   (e.g. `{"url": 12345}`) must not crash a parser that does string ops
   (`urlparse`, `.encode()`, `.lower()`, `.strip()`, `.split()`, ...) on
   that `.get()`-sourced value.

Every tool registered in `agent.recon.parsers.PARSERS` is exercised.
"""
import pytest

from agent.recon.parsers import PARSERS, get_parser

# Non-dict-but-valid JSON lines, one per JSON value kind, plus a blank line
# and an invalid-JSON line for good measure.
_NON_DICT_LINES = "42\n[1, 2, 3]\n\"a string\"\nnull\ntrue\n\nNOT JSON\n"


@pytest.mark.parametrize("tool", sorted(PARSERS.keys()))
def test_non_dict_json_lines_never_raise(tool):
    parser = get_parser(tool)
    result = parser(_NON_DICT_LINES)
    assert isinstance(result, list)


@pytest.mark.parametrize("tool", sorted(PARSERS.keys()))
def test_empty_stdout_never_raises(tool):
    parser = get_parser(tool)
    assert get_parser(tool)("") == []
    assert parser("") == []


@pytest.mark.parametrize("tool", sorted(PARSERS.keys()))
def test_non_dict_lines_preserve_prior_valid_deltas(tool):
    """A non-dict/invalid line after a valid one must not discard the valid delta."""
    valid_line_by_tool = {
        "httpx": '{"url":"https://a.example.com","status_code":200}',
        "subfinder": '{"host":"a.example.com"}',
        "amass": '{"name":"a.example.com","domain":"example.com"}',
        "dnsx": '{"host":"a.example.com","a":["1.2.3.4"]}',
        "naabu": '{"ip":"1.2.3.4","port":80}',
        "katana": '{"request":{"endpoint":"https://a.example.com/x","method":"GET"}}',
        "jsluice": '{"url":"https://a.example.com/x"}',
        "kiterunner": '{"method":"GET","target":"https://a.example.com","path":"/x"}',
    }
    line = valid_line_by_tool.get(tool)
    if line is None:
        pytest.skip(f"{tool} is not a JSONL-per-line parser (or has no simple valid fixture)")

    parser = get_parser(tool)
    stdout = f"{line}\n42\n[1,2]\nnull\n"
    result = parser(stdout)
    assert isinstance(result, list)
    assert len(result) > 0


# --- Value-type guard: valid dict, non-string value on a string-op field ---

_NON_STRING_VALUE_LINES = {
    "httpx": '{"url": 12345, "tech": 999, "tls": "not-a-dict"}',
    "subfinder": '{"host": 12345}',
    "amass": '{"name": 12345, "domain": 999, "addresses": [{"ip": 42}]}',
    "dnsx": '{"host": 12345, "a": [42]}',
    "naabu": '{"ip": 12345, "port": "80"}',
    "katana": '{"request": {"endpoint": 12345, "method": 42}}',
    "jsluice": '{"url": 12345, "kind": "aws-key", "secret": 999}',
}


@pytest.mark.parametrize("tool", sorted(_NON_STRING_VALUE_LINES.keys()))
def test_non_string_field_value_never_raises(tool):
    parser = get_parser(tool)
    result = parser(_NON_STRING_VALUE_LINES[tool])
    assert isinstance(result, list)
