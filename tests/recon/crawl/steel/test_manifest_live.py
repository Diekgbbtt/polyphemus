"""Seam under test: the v2 manifest assembled from a live run's evidence.

Spec: `docs/design/steel-crawl-spec.md` sections 8.4, 11, and 14.

The manifest builder is the only place a run's flows, parameters, and declared
forms become graph records. The observed endpoint identity is the flow's actual
`(method, path, baseurl)`; two query variants of one route are one endpoint. A
parameter anchors to the endpoint its flow called. Declared records keep their
own provenance and never merge with observed ones.
"""
from __future__ import annotations

from polymerhus.recon.crawl.steel.capture.flow import Flow
from polymerhus.recon.crawl.steel.capture.history import (
    HttpArtifact,
    RequestRecord,
)
from polymerhus.recon.crawl.steel.frontier import FrontierResult, PageVisit
from polymerhus.recon.crawl.steel.manifest import RunBlock, build_manifest_from_output
from polymerhus.recon.crawl.steel.parameters import (
    DeclaredEndpoint,
    DeclaredField,
    ObservedParameter,
    ValueShape,
)
from polymerhus.recon.crawl.steel.run import RunOutput
from polymerhus.recon.crawl.steel.state import BrowserState
from polymerhus.recon.domain.parsers.steel_parser import parse as parse_steel


def _page():
    state = BrowserState()
    return state.open_page(
        page_visit_id="page_1",
        url="http://t.example/",
        final_url="http://t.example/",
        title="Target",
        snapshot=(),
    )


def _flow(
    request_id: str,
    url: str,
    *,
    status: int = 200,
    body: bytes = b'{"ok":true}',
) -> Flow:
    return Flow(
        request_id=request_id,
        page_id="page_1",
        action_id="act_1",
        attribution="action",
        method="GET",
        url=url,
        resource_type="XHR",
        status=status,
        response_headers={"Content-Type": "application/json"},
        mime_type="application/json",
        encoded_data_length=10,
        response_body=body,
        response_body_sha256="a" * 64,
        finished=True,
    )


def _artifact(artifact_id: str) -> HttpArtifact:
    return HttpArtifact(
        artifact_id=artifact_id,
        project_id="proj-1",
        request=RequestRecord(method="GET", url="http://t.example/api/items?page=2"),
    )


def _run() -> RunBlock:
    return RunBlock(
        crawl_run_id="run-1",
        session_name="session-1",
        account="admin",
        started_at="2026-11-02T10:00:00Z",
        stop_reason="frontier_empty",
        scope=["t.example"],
        auth={"classification": "authenticated"},
    )


def test_one_route_is_one_endpoint_and_a_parameter_anchors_to_it():
    page = _page()
    first = _flow("r1", "http://t.example/api/items?page=2")
    second = _flow("r2", "http://t.example/api/items?page=3")
    output = RunOutput(
        frontier=FrontierResult(
            stop_reason="frontier_empty", page_visits=(PageVisit(page=page),)
        ),
        flows=(first, second),
        artifacts=((_artifact("http_1"), {}), (_artifact("http_2"), {})),
        flow_artifacts={"r1": "http_1", "r2": "http_2"},
        parameters=(
            ObservedParameter(
                endpoint_key="GET http://t.example/api/items",
                method="GET",
                location="query",
                name="page",
                value_shape=ValueShape(type="number", length_band=0),
                source_flow_id="r1",
                content_type=None,
                endpoint_path="/api/items",
                baseurl="http://t.example",
            ),
        ),
    )

    manifest = build_manifest_from_output(output, run=_run(), flows=output.flows)

    assert len(manifest.endpoints) == 1
    endpoint = manifest.endpoints[0]
    assert endpoint.provenance == "observed"
    assert endpoint.endpoint_id.startswith("ep_observed_")
    assert (endpoint.method, endpoint.path, endpoint.baseurl) == (
        "GET",
        "/api/items",
        "http://t.example",
    )
    assert endpoint.status_code == 200
    assert endpoint.http_artifact_id == "http_1"
    assert endpoint.source_page_id == "page_1"
    assert endpoint.action_id == "act_1"
    assert len(manifest.parameters) == 1
    parameter = manifest.parameters[0]
    assert parameter.endpoint_id == endpoint.endpoint_id
    assert parameter.provenance == "observed"
    assert parameter.position == "query"
    assert parameter.name == "page"
    assert parameter.value_shape == {"type": "number", "length_band": 0}
    assert parameter.http_artifact_id == "http_1"
    assert manifest.stats.endpoints == 1
    assert manifest.stats.parameters == 1
    assert manifest.stats.flows == 2
    assert manifest.stats.bytes == 20
    assert manifest.run.auth == {"classification": "authenticated"}

    # The parser consumes the same manifest; the observed record survives the
    # graph projection with its provenance and its endpoint anchor.
    deltas = parse_steel(manifest.model_dump_json())
    endpoint_delta = next(
        delta
        for delta in deltas
        if delta.type == "Endpoint"
        and delta.identity["path"] == "/api/items"
    )
    assert endpoint_delta.props["provenance"] == "observed"
    parameter_delta = next(
        delta
        for delta in deltas
        if delta.type == "Parameter" and delta.identity["name"] == "page"
    )
    assert parameter_delta.props["provenance"] == "observed"
    assert parameter_delta.edges[0].node_identity == {
        "path": "/api/items",
        "method": "GET",
        "baseurl": "http://t.example",
    }


def test_a_declared_form_is_a_separate_record_with_its_own_provenance():
    page = _page()
    endpoint = DeclaredEndpoint(
        endpoint_id="ep_declared_1",
        method="POST",
        url="http://t.example/contact",
        path="/contact",
        baseurl="http://t.example",
        source_page_id="page_1",
        enctype="application/x-www-form-urlencoded",
        field_names=("name",),
    )
    field = DeclaredField(
        parameter_id="param_declared_1",
        endpoint_id="ep_declared_1",
        endpoint_path="/contact",
        baseurl="http://t.example",
        name="name",
        content_type="application/x-www-form-urlencoded",
        field_type="text",
        label="Name",
    )
    output = RunOutput(
        frontier=FrontierResult(
            stop_reason="frontier_empty", page_visits=(PageVisit(page=page),)
        ),
        declared_endpoints=(endpoint,),
        declared_fields=(field,),
    )

    manifest = build_manifest_from_output(output, run=_run())

    assert len(manifest.endpoints) == 1
    assert manifest.endpoints[0].provenance == "declared"
    assert manifest.endpoints[0].status_code is None
    assert len(manifest.parameters) == 1
    assert manifest.parameters[0].provenance == "declared"
    assert manifest.parameters[0].position == "body"
    assert manifest.parameters[0].value_shape is None
    assert manifest.stats.endpoints == 1
    assert manifest.stats.parameters == 1


def test_a_repeated_observed_parameter_is_one_manifest_record():
    page = _page()
    parameter = ObservedParameter(
        endpoint_key="GET http://t.example/api/items",
        method="GET",
        location="query",
        name="page",
        value_shape=ValueShape(type="number", length_band=0),
        source_flow_id="r1",
        content_type=None,
        endpoint_path="/api/items",
        baseurl="http://t.example",
    )
    flow = _flow("r1", "http://t.example/api/items?page=2")
    output = RunOutput(
        frontier=FrontierResult(
            stop_reason="frontier_empty", page_visits=(PageVisit(page=page),)
        ),
        flows=(flow,),
        artifacts=((_artifact("http_1"), {}),),
        flow_artifacts={"r1": "http_1"},
        parameters=(parameter, parameter.model_copy(update={"source_flow_id": "r2"})),
    )

    manifest = build_manifest_from_output(
        output, run=_run(), flows=output.flows
    )

    assert [record.parameter_id for record in manifest.parameters] == [
        "param_observed_" + __import__("hashlib").sha256(
            "\x1f".join(parameter.dedup_key).encode("utf-8")
        ).hexdigest()[:16]
    ]
    assert manifest.stats.parameters == 1


def test_a_vendor_script_is_marked_unless_its_body_has_a_target_signal():
    page = _page()
    library = _flow(
        "r1", "http://t.example/assets/lib/primevue/button/index.mjs",
        body=b"export const button = {}",
    )
    app = _flow(
        "r2", "http://t.example/assets/lib/app-api.js",
        body=b"fetch('/api/items')",
    )
    output = RunOutput(
        frontier=FrontierResult(
            stop_reason="frontier_empty", page_visits=(PageVisit(page=page),)
        ),
        flows=(library, app),
        artifacts=((_artifact("http_1"), {}), (_artifact("http_2"), {})),
        flow_artifacts={"r1": "http_1", "r2": "http_2"},
    )

    manifest = build_manifest_from_output(output, run=_run(), flows=output.flows)

    by_path = {record.path: record for record in manifest.endpoints}
    assert by_path["/assets/lib/primevue/button/index.mjs"].vendor_script is True
    assert by_path["/assets/lib/app-api.js"].vendor_script is False


def test_a_flow_only_run_is_a_valid_non_empty_manifest():
    page = _page()
    flow = _flow("r1", "http://t.example/", status=200)
    output = RunOutput(
        frontier=FrontierResult(
            stop_reason="frontier_empty", page_visits=(PageVisit(page=page),)
        ),
        flows=(flow,),
        artifacts=((_artifact("http_1"), {}),),
        flow_artifacts={"r1": "http_1"},
    )

    manifest = build_manifest_from_output(output, run=_run(), flows=output.flows)

    assert manifest.endpoints[0].path == "/"
    assert manifest.stats.flows == 1
    assert manifest.stats.endpoints == 1


def test_data_uri_flows_never_become_endpoints():
    page = _page()
    flow = _flow("r1", "data:image/png;base64,iVBORw0KGgo=")
    output = RunOutput(
        frontier=FrontierResult(
            stop_reason="frontier_empty", page_visits=(PageVisit(page=page),)
        ),
        flows=(flow,),
        artifacts=((_artifact("http_1"), {}),),
        flow_artifacts={"r1": "http_1"},
    )

    manifest = build_manifest_from_output(output, run=_run(), flows=output.flows)

    assert manifest.endpoints == []
    assert manifest.parameters == []
    assert manifest.stats.flows == 1
    assert manifest.stats.endpoints == 0


def test_http_media_flows_still_become_endpoints():
    page = _page()
    flow = _flow("r1", "http://t.example/uploads/20181224/abc.jpg")
    output = RunOutput(
        frontier=FrontierResult(
            stop_reason="frontier_empty", page_visits=(PageVisit(page=page),)
        ),
        flows=(flow,),
        artifacts=((_artifact("http_1"), {}),),
        flow_artifacts={"r1": "http_1"},
    )

    manifest = build_manifest_from_output(output, run=_run(), flows=output.flows)

    assert [endpoint.path for endpoint in manifest.endpoints] == [
        "/uploads/20181224/abc.jpg"
    ]
