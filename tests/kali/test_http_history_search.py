"""Conjunctive attribute search, FTS, deterministic pagination, isolation."""
from __future__ import annotations

import sqlite3

import pytest

from kali.http_history.models import (
    CaptureContext,
    ConnectionRecord,
    HttpArtifact,
    NameValue,
    RequestRecord,
    ResponseRecord,
    TimingsRecord,
)
from kali.http_history.store import HttpHistoryStore


def _artifact(
    artifact_id: str,
    *,
    created_at: float,
    method: str = "POST",
    url: str = "https://target.example/login",
    req_headers=None,
    cookies=None,
    query=None,
    form=None,
    status: int = 200,
    request_body: bytes = b"",
    response_body: bytes = b"",
    exec_id: str = "e1",
) -> tuple[HttpArtifact, dict[str, bytes]]:
    import hashlib

    bodies: dict[str, bytes] = {}
    req_ref = None
    if request_body:
        req_ref = f"sha256:{hashlib.sha256(request_body).hexdigest()}"
        bodies[req_ref] = request_body
    resp_ref = None
    if response_body:
        resp_ref = f"sha256:{hashlib.sha256(response_body).hexdigest()}"
        bodies[resp_ref] = response_body
    artifact = HttpArtifact(
        artifact_id=artifact_id,
        project_id="proj-1",
        capture_context=CaptureContext(exec_id=exec_id, session_id="s1", variant_ref="v0"),
        request=RequestRecord(
            method=method,
            url=url,
            http_version="HTTP/2",
            headers=req_headers or [["content-type", "application/json"]],
            cookies=cookies or [],
            query=query or [],
            form=form or [],
            body_ref=req_ref,
            body_size=len(request_body),
        ),
        response=ResponseRecord(status=status, reason="OK", body_ref=resp_ref, body_size=len(response_body)),
        connection=ConnectionRecord(tls=True, sni="target.example", alpn="h2"),
        timings=TimingsRecord(total_ms=25.0),
        created_at=created_at,
    )
    return artifact, bodies


def _seed(store: HttpHistoryStore) -> None:
    for i, (created, status) in enumerate([(1000.0, 200), (1000.0, 404), (2000.0, 500)]):
        artifact, bodies = _artifact(
            f"http_01J000000000000000000000{i}A",
            created_at=created,
            status=status,
            cookies=[NameValue(name="sid", value="abc")],
            query=[NameValue(name="q", value=f"term{i}")],
            response_body=f"marker-{i}".encode(),
        )
        store.record(artifact, bodies=bodies)


def test_search_by_method_and_status(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _seed(store)
    page = store.search(
        [
            {"side": "request", "namespace": "core", "key": "method", "op": "eq", "value": "POST"},
            {"side": "response", "namespace": "core", "key": "status", "op": "eq", "value": 404},
        ]
    )
    assert [a.artifact_id for a in page.artifacts] == ["http_01J0000000000000000000001A"]


def test_search_ops_eq_contains_prefix_gte_lte(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _seed(store)
    contains = store.search(
        [{"side": "request", "namespace": "query", "key": "q", "op": "contains", "value": "erm1"}]
    )
    assert [a.artifact_id for a in contains.artifacts] == ["http_01J0000000000000000000001A"]
    prefix = store.search(
        [{"side": "request", "namespace": "query", "key": "q", "op": "prefix", "value": "term"}]
    )
    assert len(prefix.artifacts) == 3
    gte = store.search(
        [{"side": "response", "namespace": "core", "key": "status", "op": "gte", "value": 404}]
    )
    assert len(gte.artifacts) == 2
    lte = store.search(
        [{"side": "response", "namespace": "core", "key": "status", "op": "lte", "value": 404}]
    )
    assert len(lte.artifacts) == 2


def test_a_numeric_string_status_filter_matches(tmp_path):
    """JSON often carries a number as a string. `status` is indexed numeric
    only, so `eq "404"` used to compare `text_value` (NULL) and return an
    empty page that read as "no such traffic"."""
    store = HttpHistoryStore(tmp_path, "proj-1")
    _seed(store)
    page = store.search([
        {"side": "response", "namespace": "core", "key": "status",
         "op": "eq", "value": "404"},
    ])
    assert [a.artifact_id for a in page.artifacts] == [
        "http_01J0000000000000000000001A"]


def test_a_numeric_string_size_filter_matches(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _seed(store)
    page = store.search([
        {"side": "response", "namespace": "body", "key": "size",
         "op": "eq", "value": "8"},
    ])
    assert len(page.artifacts) == 3


def test_a_non_numeric_status_value_stays_a_text_match(tmp_path):
    """A response-less artifact indexes `status` with the text `none`, and
    `eq "none"` is a real control-group query. Coercion must not eat it."""
    store = HttpHistoryStore(tmp_path, "proj-1")
    artifact, bodies = _artifact(
        "http_01J0000000000000000000007A", created_at=5000.0)
    store.record(artifact.model_copy(update={"response": None}), bodies=bodies)
    page = store.search([
        {"side": "response", "namespace": "core", "key": "status",
         "op": "eq", "value": "none"},
    ])
    assert [a.artifact_id for a in page.artifacts] == [
        "http_01J0000000000000000000007A"]


def test_a_cookie_key_matches_regardless_of_case(tmp_path):
    """Cookie names are recorded as the application sends them (`JSESSIONID`).
    The row carries no cookies, so the model cannot learn the case; matching
    folds it instead of returning an empty page."""
    store = HttpHistoryStore(tmp_path, "proj-1")
    artifact, bodies = _artifact(
        "http_01J0000000000000000000008A", created_at=1000.0,
        cookies=[NameValue(name="JSESSIONID", value="abc")])
    store.record(artifact, bodies=bodies)

    for key in ("jsessionid", "JSESSIONID", "JsEsSiOnId"):
        page = store.search([
            {"side": "request", "namespace": "cookie", "key": key,
             "op": "eq", "value": "abc"},
        ])
        assert [a.artifact_id for a in page.artifacts] == [
            "http_01J0000000000000000000008A"], key


def test_cookie_absent_uses_the_same_case_folding(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    with_cookie, bodies = _artifact(
        "http_01J0000000000000000000008A", created_at=1000.0,
        cookies=[NameValue(name="JSESSIONID", value="abc")])
    without_cookie, bodies2 = _artifact(
        "http_01J0000000000000000000009A", created_at=2000.0, cookies=[])
    store.record(with_cookie, bodies=bodies)
    store.record(without_cookie, bodies=bodies2)

    page = store.search([
        {"side": "request", "namespace": "cookie", "key": "jsessionid",
         "op": "absent"},
    ])
    assert [a.artifact_id for a in page.artifacts] == [
        "http_01J0000000000000000000009A"]


def test_search_filters_are_conjunctive(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _seed(store)
    page = store.search(
        [
            {"side": "request", "namespace": "core", "key": "method", "op": "eq", "value": "GET"},
            {"side": "response", "namespace": "core", "key": "status", "op": "eq", "value": 200},
        ]
    )
    assert page.artifacts == []


def test_search_order_and_cursor_are_stable(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _seed(store)
    first = store.search([], limit=2)
    assert [a.artifact_id for a in first.artifacts] == [
        "http_01J0000000000000000000000A",
        "http_01J0000000000000000000001A",
    ]
    second = store.search([], limit=2, cursor=first.next_cursor)
    assert [a.artifact_id for a in second.artifacts] == ["http_01J0000000000000000000002A"]
    assert second.next_cursor is None


def test_search_rejects_limit_out_of_range(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    for bad in (0, 201, -1):
        with pytest.raises(ValueError):
            store.search([], limit=bad)


def test_search_rejects_unknown_vocabulary(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    with pytest.raises(ValueError):
        store.search([{"side": "request", "namespace": "core", "key": "method", "op": "regex", "value": "x"}])
    with pytest.raises(ValueError):
        store.search([{"side": "body", "namespace": "core", "key": "method", "op": "eq", "value": "x"}])


def test_a_core_key_is_bound_to_its_side(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _seed(store)
    with pytest.raises(ValueError, match="not valid on side 'request'"):
        store.search([{"side": "request", "namespace": "core",
                       "key": "host", "op": "eq", "value": "target.example"}])
    with pytest.raises(ValueError, match="not valid on side 'response'"):
        store.search([{"side": "response", "namespace": "core",
                       "key": "url", "op": "contains", "value": "/login"}])


def test_the_core_key_error_names_the_allowed_keys(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    with pytest.raises(ValueError) as raised:
        store.search([{"side": "request", "namespace": "core",
                       "key": "host", "op": "eq", "value": "target.example"}])
    assert "http_version" in str(raised.value)
    assert "method" in str(raised.value)
    assert "url" in str(raised.value)


def test_every_valid_core_key_still_searches(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _seed(store)
    matched = (
        ("request", "url", "contains", "/login"),
        ("response", "status", "eq", 200),
        ("timing", "total_ms", "gte", 25.0),
    )
    for side, key, op, value in matched:
        page = store.search([{"side": side, "namespace": "core",
                              "key": key, "op": op, "value": value}])
        assert page.artifacts, (side, key)
    for side, key, op, value in (
        ("context", "run_id", "eq", "r1"),
        ("connection", "protocol", "eq", "http"),
    ):
        store.search([{"side": side, "namespace": "core",
                       "key": key, "op": op, "value": value}])


def test_search_never_leaves_the_project(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _seed(store)
    other = HttpHistoryStore(tmp_path, "proj-2")
    artifact, bodies = _artifact("http_01J0000000000000000000009A", created_at=1.0, method="GET")
    other.record(artifact, bodies=bodies)
    assert other.search(
        [{"side": "request", "namespace": "core", "key": "method", "op": "eq", "value": "GET"}]
    ).artifacts
    assert store.search(
        [{"side": "request", "namespace": "core", "key": "method", "op": "eq", "value": "GET"}]
    ).artifacts == []


def test_text_search_finds_a_body_marker_and_url(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _seed(store)
    assert [a.artifact_id for a in store.text_search("marker-2").artifacts] == [
        "http_01J0000000000000000000002A"
    ]
    assert store.text_search("target.example").artifacts


def test_projection_covers_tls_and_timing_namespaces(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _seed(store)
    assert store.search(
        [{"side": "connection", "namespace": "tls", "key": "sni", "op": "eq", "value": "target.example"}]
    ).artifacts
    assert store.search(
        [{"side": "timing", "namespace": "core", "key": "total_ms", "op": "gte", "value": 10}]
    ).artifacts
    assert store.search(
        [{"side": "context", "namespace": "core", "key": "exec_id", "op": "eq", "value": "e1"}]
    ).artifacts


def test_absent_operator_matches_transactions_without_the_attribute(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    with_x = _artifact("http_01J0000000000000000000000A", created_at=1000.0,
                       req_headers=[["x-forwarded-for", "127.0.0.1"]])
    without_x = _artifact("http_01J0000000000000000000001A", created_at=1001.0,
                          req_headers=[["content-type", "application/json"]])
    for artifact, bodies in (with_x, without_x):
        store.record(artifact, bodies=bodies)

    page = store.search([
        {"side": "request", "namespace": "header", "key": "x-forwarded-for",
         "op": "absent"},
    ])
    assert [a.artifact_id for a in page.artifacts] == [
        "http_01J0000000000000000000001A"
    ]


def test_absent_does_not_require_a_value(tmp_path):
    store = HttpHistoryStore(tmp_path, "proj-1")
    _seed(store)
    page = store.search([
        {"side": "request", "namespace": "header", "key": "x-not-sent",
         "op": "absent"},
    ])
    assert len(page.artifacts) == 3


def _seed_flat(store: HttpHistoryStore, n: int) -> None:
    """N artifacts that ALL carry `response/header/server`, so the filter key's
    attribute cardinality equals the flow count - the shape that exposes a
    per-flow correlated scan as quadratic."""
    for i in range(n):
        artifact, bodies = _artifact(
            f"http_01J{i:024d}A",
            created_at=float(i),
            response_body=f"marker-{i}".encode(),
        )
        artifact.response.headers = [("server", "nginx")]
        store.record(artifact, bodies=bodies)


def _vm_progress_calls(store: HttpHistoryStore, filters: list[dict], budget: int = 5000):
    """Run a search under a SQLite progress handler and count how many VM-step
    checkpoints it crosses. This is a deterministic proxy for how many rows the
    query visits: the old correlated `EXISTS`/`NOT EXISTS` form crosses
    O(flows x matching-attributes), the semi-join crosses O(flows + attributes).
    Returns (aborted, checkpoints)."""
    conn = store._conn
    counter = {"n": 0}

    def handler():
        counter["n"] += 1
        return 1 if counter["n"] > budget else 0

    conn.set_progress_handler(handler, 100)
    aborted = False
    try:
        store.search(filters)
    except sqlite3.OperationalError:
        aborted = True
    finally:
        conn.set_progress_handler(None, 0)
    return aborted, counter["n"]


@pytest.mark.parametrize(
    "filters",
    [
        [{"side": "response", "namespace": "header", "key": "server", "op": "absent"}],
        [
            {"side": "response", "namespace": "header", "key": "server",
             "op": "contains", "value": "zzqqxx"},
        ],
    ],
)
def test_search_filter_does_not_scan_attributes_per_flow(tmp_path, filters):
    """Regression for the arm-F MCP hang: a filter on a common key must not make
    SQLite re-scan every matching attribute row once per flow."""
    store = HttpHistoryStore(tmp_path, "proj-1")
    _seed_flat(store, 800)
    aborted, calls = _vm_progress_calls(store, filters)
    assert not aborted, "search filter ran a per-flow correlated scan (quadratic)"
    assert calls < 5000, f"search filter is not linear in the store size ({calls} checkpoints)"
