"""Unit tests for `tools/measure_gt_wellformedness.py` (plan 2026-10-17, W2.2).

The metric math is pure over plain dicts, so these tests build synthetic specs
and graph snapshots and never touch a database. One extra test lints the REAL
local corpus when it is present (skipped elsewhere, since the corpus is
declared local-only).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOL_PATH = _REPO_ROOT / "tools" / "measure_gt_wellformedness.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("measure_gt_wellformedness_tool", _TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def _service_spec() -> dict:
    return {
        "schema": "gt-unit-spec/v1",
        "bundle": "x-001",
        "vulnerability": {"type": "Stored XSS", "fault_class": "CWE-79"},
        "unit": {"kind": "Service", "match": {"business_function_slug": "svc"}},
        "typed_backbone": {"required": [
            {"field": "api_paradigm", "expected": "rest"},
            {"field": "exposure", "expected": "public"},
        ]},
        "edges_to_l0": {"mode": "service_aggregates", "endpoints": [
            {"method": "POST", "path": "/upload"},
            {"method": "GET", "path": "/view"},
        ], "parameters": [
            {"name": "image", "position": "body",
             "endpoint": {"method": "POST", "path": "/upload"}},
        ]},
        "service_to_system_edges": {"required": [
            {"rel": "EXPOSED_VIA", "target_kind": "RESTApi",
             "target_discriminator": "svc::rest", "discriminator_mode": "kind_any"},
            {"rel": "EXPOSED_VIA", "target_kind": "WebPresentation",
             "target_discriminator": "svc::shell", "discriminator_mode": "exact"},
        ]},
        "threat_modeller_sufficiency": None,
    }


def _system_spec() -> dict:
    return {
        "schema": "gt-unit-spec/v1",
        "bundle": "y-002",
        "vulnerability": {"type": "Access Control Bypass", "fault_class": "CWE-284"},
        "unit": {"kind": "System",
                 "match": {"kind": "AuthorizationSystem", "discriminator": "__singleton__"}},
        "typed_backbone": {
            "required": [{"field": "description", "non_empty": True}],
            "threat_modeller_sufficiency": {"statements": [
                {"id": "S1", "text": "refusal is redirect-shaped",
                 "keywords": ["302", "redirect"]},
                {"id": "S2", "text": "log sink", "keywords": ["log"]},
            ]},
        },
        "edges_to_l0": {"mode": "system_linked", "endpoints": [
            {"method": "GET", "path": "/api/admin/user"},
        ], "parameters": []},
        "service_to_system_edges": {"mode": "inbound", "required": [
            {"rel": "AUTHORIZED_BY", "from_service": "article-publishing"},
        ]},
        "threat_modeller_sufficiency": None,
    }


def _snapshot(**overrides) -> dict:
    snap = {
        "services": {},
        "systems": [],
        "aggregates": {},
        "system_edges": [],
        "system_linked_endpoints": [],
        "system_evidence": [],
    }
    snap.update(overrides)
    return snap


def test_service_all_matched_scores_one():
    spec = _service_spec()
    snapshot = _snapshot(
        services={"svc": {"props": {"api_paradigm": "rest", "exposure": "public"}}},
        aggregates={"svc": [
            {"label": "Endpoint", "method": "POST", "path": "/upload"},
            {"label": "Endpoint", "method": "GET", "path": "/view"},
            {"label": "Parameter", "name": "image", "position": "body",
             "endpoint_path": "/upload"},
        ]},
        systems=[
            {"kind": "RESTApi", "discriminator": "core-rest",
             "props": {"description": "shared REST overlay"}},
            {"kind": "WebPresentation", "discriminator": "svc::shell", "props": {}},
        ],
        system_edges=[
            {"service_slug": "svc", "rel": "EXPOSED_VIA", "kind": "RESTApi",
             "discriminator": "core-rest"},
            {"service_slug": "svc", "rel": "EXPOSED_VIA", "kind": "WebPresentation",
             "discriminator": "svc::shell"},
        ],
    )
    result = tool.score_spec(spec, snapshot)
    assert result["m1"]["pass"] is True
    assert result["m2"]["share"] == pytest.approx(1.0)
    assert result["m3"]["share"] == pytest.approx(1.0)
    assert result["m4"]["share"] == pytest.approx(1.0)
    assert result["score"] == pytest.approx(1.0)
    rest_edge = result["m4"]["items"][0]
    assert rest_edge["status"] == "matched"
    assert rest_edge["actual_discriminator"] == "core-rest"


def test_method_mismatch_and_parameter_missing_are_reported():
    spec = _service_spec()
    snapshot = _snapshot(
        services={"svc": {"props": {"api_paradigm": "rest", "exposure": "public"}}},
        aggregates={"svc": [
            {"label": "Endpoint", "method": "GET", "path": "/upload"},
            {"label": "Endpoint", "method": "GET", "path": "/view"},
        ]},
        systems=[{"kind": "RESTApi", "discriminator": "svc::rest", "props": {}},
                 {"kind": "WebPresentation", "discriminator": "svc::shell", "props": {}}],
    )
    result = tool.score_spec(spec, snapshot)
    items = result["m2"]["items"]
    upload = next(i for i in items if i["required"].get("path") == "/upload")
    assert upload["status"] == "method_mismatch"
    assert upload["actual_method"] == "GET"
    assert result["m2"]["share"] == pytest.approx(1.0 / 3.0)
    assert result["m2"]["parameter_matched"] == 0
    assert result["m2"]["parameter_total"] == 1


def test_placement_gate_zeroes_the_score_without_raising():
    spec = _service_spec()
    result = tool.score_spec(spec, _snapshot())
    assert result["m1"]["pass"] is False
    assert result["score"] == 0.0
    assert result["m3"]["matched"] == 0


def test_exact_discriminator_mismatch_is_missing():
    spec = _service_spec()
    snapshot = _snapshot(
        services={"svc": {"props": {"api_paradigm": "rest", "exposure": "public"}}},
        aggregates={"svc": [
            {"label": "Endpoint", "method": "POST", "path": "/upload"},
            {"label": "Endpoint", "method": "GET", "path": "/view"},
            {"label": "Parameter", "name": "image", "position": "body",
             "endpoint_path": "/upload"},
        ]},
        systems=[{"kind": "RESTApi", "discriminator": "svc::rest", "props": {}},
                 {"kind": "WebPresentation", "discriminator": "other::shell", "props": {}}],
        system_edges=[
            {"service_slug": "svc", "rel": "EXPOSED_VIA", "kind": "RESTApi",
             "discriminator": "svc::rest"},
        ],
    )
    result = tool.score_spec(spec, snapshot)
    web_edge = next(i for i in result["m4"]["items"]
                    if i["required"]["target_kind"] == "WebPresentation")
    assert web_edge["status"] == "missing"
    assert result["m4"]["share"] == pytest.approx(0.5)


def test_system_statements_inbound_edges_and_linked_endpoints():
    spec = _system_spec()
    snapshot = _snapshot(
        systems=[{"kind": "AuthorizationSystem", "discriminator": "__singleton__",
                  "props": {"description": "Unsecured access is answered 302 with a "
                                            "REDIRECT to a dead path."}}],
        system_linked_endpoints=[
            {"kind": "AuthorizationSystem", "discriminator": "__singleton__",
             "service_slug": "article-publishing", "rel": "AUTHORIZED_BY",
             "method": "GET", "path": "/api/admin/user"},
        ],
        system_edges=[
            {"service_slug": "article-publishing", "rel": "AUTHORIZED_BY",
             "kind": "AuthorizationSystem", "discriminator": "__singleton__"},
        ],
    )
    result = tool.score_spec(spec, snapshot)
    assert result["m1"]["pass"] is True
    assert result["m2"]["share"] == pytest.approx(1.0)
    assert result["m3"]["share"] == pytest.approx(2.0 / 3.0)  # description + S1, S2 missing
    assert result["m4"]["share"] == pytest.approx(1.0)
    assert result["score"] == pytest.approx((1.0 + 2.0 / 3.0 + 1.0) / 3.0)


def test_system_inbound_edge_missing_and_evidence_fallback():
    spec = _system_spec()
    snapshot = _snapshot(
        systems=[{"kind": "AuthorizationSystem", "discriminator": "__singleton__",
                  "props": {"description": "302 redirect ..."}}],
        system_evidence=[
            {"kind": "AuthorizationSystem", "discriminator": "__singleton__",
             "method": "GET", "path": "/api/admin/user"},
        ],
    )
    result = tool.score_spec(spec, snapshot)
    assert result["m2"]["share"] == pytest.approx(1.0)  # EVIDENCED_BY fallback
    assert result["m4"]["share"] == pytest.approx(0.0)


def test_load_spec_validates_and_lint_reports(tmp_path: Path):
    good = tmp_path / "good.yaml"
    good.write_text(
        "schema: gt-unit-spec/v1\n"
        "bundle: b-001\n"
        "unit: {kind: Service, match: {business_function_slug: svc}}\n"
        "typed_backbone:\n  required:\n    - {field: exposure}\n"
        "edges_to_l0:\n  endpoints:\n    - {method: GET, path: /x}\n"
        "service_to_system_edges:\n  required:\n"
        "    - {rel: EXPOSED_VIA, target_kind: RESTApi, target_discriminator: a::rest}\n",
        encoding="utf-8")
    spec = tool.load_spec(good)
    assert spec["bundle"] == "b-001"
    assert tool.lint_specs([good]) == []

    bad = tmp_path / "bad.yaml"
    bad.write_text("schema: gt-unit-spec/v1\nbundle: b-002\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing key 'unit'"):
        tool.load_spec(bad)
    assert tool.lint_specs([bad])

    empty_l0 = tmp_path / "empty.yaml"
    empty_l0.write_text(
        "schema: gt-unit-spec/v1\n"
        "bundle: b-003\n"
        "unit: {kind: Service, match: {business_function_slug: svc}}\n"
        "typed_backbone:\n  required:\n    - {field: exposure}\n"
        "edges_to_l0:\n  endpoints: []\n"
        "service_to_system_edges:\n  required:\n"
        "    - {rel: EXPOSED_VIA, target_kind: RESTApi, target_discriminator: a::rest}\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="edges_to_l0 is empty"):
        tool.load_spec(empty_l0)


def test_kind_any_prefers_the_gt_discriminator():
    spec = _service_spec()
    snapshot = _snapshot(
        services={"svc": {"props": {"api_paradigm": "rest", "exposure": "public"}}},
        aggregates={"svc": [
            {"label": "Endpoint", "method": "POST", "path": "/upload"},
            {"label": "Endpoint", "method": "GET", "path": "/view"},
            {"label": "Parameter", "name": "image", "position": "body",
             "endpoint_path": "/upload"},
        ]},
        systems=[{"kind": "RESTApi", "discriminator": "core-rest", "props": {}},
                 {"kind": "RESTApi", "discriminator": "svc::rest", "props": {}},
                 {"kind": "WebPresentation", "discriminator": "svc::shell", "props": {}}],
        system_edges=[
            {"service_slug": "svc", "rel": "EXPOSED_VIA", "kind": "RESTApi",
             "discriminator": "core-rest"},
            {"service_slug": "svc", "rel": "EXPOSED_VIA", "kind": "RESTApi",
             "discriminator": "svc::rest"},
        ],
    )
    result = tool.score_spec(spec, snapshot)
    rest_edge = result["m4"]["items"][0]
    assert rest_edge["actual_discriminator"] == "svc::rest"
    assert rest_edge["exact_discriminator"] is True


def test_outbound_edge_requires_the_edge_from_this_service():
    spec = _service_spec()
    snapshot = _snapshot(
        services={"svc": {"props": {"api_paradigm": "rest", "exposure": "public"}}},
        systems=[{"kind": "RESTApi", "discriminator": "svc::rest", "props": {}},
                 {"kind": "WebPresentation", "discriminator": "svc::shell", "props": {}}],
    )
    result = tool.score_spec(spec, snapshot)
    assert result["m4"]["matched"] == 0
    assert result["m4"]["share"] == pytest.approx(0.0)


def test_system_backbone_tolerates_non_json_props():
    import datetime

    spec = _system_spec()
    snapshot = _snapshot(
        systems=[{"kind": "AuthorizationSystem", "discriminator": "__singleton__",
                  "props": {"description": "Unsecured access is answered 302 with a "
                                            "REDIRECT.",
                            "first_seen": datetime.datetime(2026, 1, 1)}}],
    )
    result = tool.score_spec(spec, snapshot)
    assert result["m3"]["matched"] >= 1


def test_render_text_carries_the_target_score():
    result = tool.score_target([_service_spec()], _snapshot())
    text = tool.render_text("label", "project-id", Path("/corpus"), result)
    assert "TARGET SCORE" in text
    assert "M1 placement: FAIL" in text


def test_target_filter_selects_only_that_target(tmp_path: Path):
    spec_text = (
        "schema: gt-unit-spec/v1\n"
        "bundle: b-001\n"
        "unit: {kind: Service, match: {business_function_slug: svc}}\n"
        "typed_backbone:\n  required:\n    - {field: exposure}\n"
        "edges_to_l0:\n  endpoints:\n    - {method: GET, path: /x}\n"
        "service_to_system_edges:\n  required:\n"
        "    - {rel: EXPOSED_VIA, target_kind: RESTApi, target_discriminator: a::rest}\n")
    for target in ("alpha", "beta"):
        for bundle in (f"{target}-001", f"{target}-002"):
            path = tmp_path / target / bundle / "unit-spec.yaml"
            path.parent.mkdir(parents=True)
            path.write_text(spec_text, encoding="utf-8")
    assert len(tool.iter_spec_paths(tmp_path)) == 4
    alpha = tool.iter_spec_paths(tmp_path, "alpha")
    assert [p.parent.name for p in alpha] == ["alpha-001", "alpha-002"]


@pytest.mark.skipif(not tool.DEFAULT_CORPUS.exists(),
                    reason="local-only GT corpus is absent")
def test_real_corpus_specs_parse_and_lint_clean():
    paths = tool.iter_spec_paths(tool.DEFAULT_CORPUS)
    assert len(paths) >= 13
    assert tool.lint_specs(paths) == []
    bundles = {tool.load_spec(p)["bundle"] for p in paths}
    assert "comfyui-001" in bundles
    assert "white-jotter-007" in bundles
