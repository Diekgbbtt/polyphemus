"""Deterministic, closed-set replay overrides (no shell, no source mutation)."""
from __future__ import annotations

import pytest

from kali.http_history.models import NameValue, RequestRecord
from kali.http_history.replay import ReplayOverrideError, apply_overrides


def _request() -> RequestRecord:
    return RequestRecord(
        method="POST",
        url="https://target.example/search?q=1",
        http_version="HTTP/2",
        headers=[["content-type", "application/json"], ["x-keep", "yes"]],
        cookies=[NameValue(name="sid", value="abc")],
        query=[NameValue(name="q", value="1")],
    )


def test_no_overrides_is_a_baseline_replay():
    plan = apply_overrides(_request(), b'{"a":1}', {})
    assert plan.method == "POST"
    assert plan.url == "https://target.example/search?q=1"
    assert plan.body == b'{"a":1}'
    assert plan.replay_kind == "baseline"


def test_method_and_path_overrides_change_only_those():
    plan = apply_overrides(_request(), b"", {"method": "PUT", "path": "/other"})
    assert plan.method == "PUT"
    # Only the declared locations change: the query is a separate attribute.
    assert plan.url == "https://target.example/other?q=1"
    assert plan.replay_kind == "mutated"


def test_query_override_replaces_the_named_value():
    plan = apply_overrides(_request(), b"", {"query": {"q": "' OR 1=1--"}})
    assert "q=%27+OR+1%3D1--" in plan.url


def test_header_and_cookie_overrides_merge():
    plan = apply_overrides(
        _request(), b"", {"headers": {"x-new": "1"}, "cookies": {"sid": "new"}}
    )
    headers = dict(plan.headers)
    assert headers["x-new"] == "1"
    assert headers["x-keep"] == "yes"
    assert "sid=new" in headers["cookie"]


def test_json_and_form_and_body_overrides_are_exclusive_replacements():
    json_plan = apply_overrides(_request(), b"", {"json": {"a": 2}})
    assert json_plan.body == b'{"a": 2}'
    form_plan = apply_overrides(_request(), b"", {"form": {"user": "a b"}})
    assert form_plan.body == b"user=a+b"
    body_plan = apply_overrides(_request(), b"", {"body": "raw"})
    assert body_plan.body == b"raw"


def test_unknown_override_key_is_rejected():
    with pytest.raises(ReplayOverrideError):
        apply_overrides(_request(), b"", {"command": "rm -rf /"})


def test_source_request_is_not_mutated():
    request = _request()
    apply_overrides(request, b"", {"method": "DELETE", "query": {"q": "x"}})
    assert request.method == "POST"
    assert request.url == "https://target.example/search?q=1"


def test_remove_header_drops_the_named_headers():
    plan = apply_overrides(_request(), b"", {"remove_headers": ["authorization", "X-Keep"]})
    names = [name.lower() for name, _ in plan.headers]
    assert "authorization" not in names
    assert "x-keep" not in names
    assert "content-type" in names
    assert plan.replay_kind == "mutated"


def test_remove_header_runs_after_setting_headers():
    plan = apply_overrides(
        _request(), b"", {"headers": {"x-new": "1"}, "remove_header": ["x-new"]}
    )
    assert [name.lower() for name, _ in plan.headers].count("x-new") == 0
