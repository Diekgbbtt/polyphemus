import json
from pathlib import Path
from types import SimpleNamespace

from polymerhus.app.data_root import ensure_project
from polymerhus.recon.crawl.crawl_pod import build_crawl_pod, live_run_crawl_fn
from polymerhus.recon.crawl.steel.manifest import Manifest, RunBlock
from polymerhus.recon.domain.types import JobSpec
from polymerhus.recon.js_acquisition import CaptureLimits, SteelCaptureStore
from polymerhus.recon.js_intake import JsIntakeReader, JsIntakeStore, issue_js_intake_reference


STEEL_JOB = JobSpec(
    tool="steel_crawl",
    skill="agentic_crawl",
    command_template="",
    produces=["BaseURL", "Endpoint"],
    consumes="BaseURL",
    configurator_mode="agent",
)


def _invoke_normal_crawl_pod(
    monkeypatch,
    tmp_path: Path,
    *,
    extra: dict,
) -> tuple[dict, dict, Path]:
    import polymerhus.app.data_root as data_root_module
    import polymerhus.recon.crawl.crawl_pod as crawl_pod_module

    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    received: dict = {}
    exact_url = "https://app.example.test/static/authenticated.js"

    def fake_default_run_crawl_fn(
        target,
        *,
        scope,
        browser_auth=None,
        extra=None,
        capture_store=None,
    ):
        received.update(capture_store=capture_store)
        return {"endpoints": [], "js_urls": [exact_url]}

    monkeypatch.setattr(data_root_module, "DATA_ROOT", root)
    crawl_fn = crawl_pod_module.crawl_pod.nodes["crawl"].bound.func
    cells = dict(zip(crawl_fn.__code__.co_freevars, crawl_fn.__closure__))
    original_run_crawl_fn = cells["run_crawl_fn"].cell_contents
    cells["run_crawl_fn"].cell_contents = fake_default_run_crawl_fn

    def fake_curate_fn(assets, observations, project_id, **kwargs):
        return len(assets), len(observations), assets, observations

    collaborator_nodes = {
        "triager": ("triage_fn", lambda exec_result, assets, job: []),
        "curator": ("curate_fn", fake_curate_fn),
        "fail": ("curate_fn", fake_curate_fn),
    }
    original_collaborators: list[tuple[object, object]] = []
    try:
        for node_name, (freevar_name, replacement) in collaborator_nodes.items():
            node_fn = crawl_pod_module.crawl_pod.nodes[node_name].bound.func
            node_cells = dict(
                zip(node_fn.__code__.co_freevars, node_fn.__closure__)
            )
            cell = node_cells[freevar_name]
            original_collaborators.append((cell, cell.cell_contents))
            cell.cell_contents = replacement
        result = crawl_pod_module.crawl_pod.invoke(
            {
                "job": STEEL_JOB,
                "input_asset": {"url": "https://app.example.test"},
                "asset_context": "asset-1",
                "extra": {"project_id": "proj-1", **extra},
                "session_id": "normal-steel-pod",
                "project_id": "proj-1",
                "run_id": "run-1",
                "phase": 4,
            }
        )
    finally:
        cells["run_crawl_fn"].cell_contents = original_run_crawl_fn
        for cell, original in original_collaborators:
            cell.cell_contents = original

    return result, received, root


def test_normal_authenticated_crawl_records_leads_without_capture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    result, received, root = _invoke_normal_crawl_pod(
        monkeypatch,
        tmp_path,
        extra={
            "auth_account": "account-1",
            "auth_context": {"cookies": [{"name": "sid", "value": "secret"}]},
        },
    )

    intake = (
        root
        / "proj-1"
        / "recon"
        / "js-intake"
        / "run-1"
        / "normal-steel-pod.jsonl"
    )
    records = [
        json.loads(line)
        for line in intake.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert result["export"].verdict == "success", result["export"].error
    assert records[1]["record_type"] == "lead"
    assert received["capture_store"] is None
    assert not (
        root
        / "proj-1"
        / "recon"
        / "js_analysis"
        / "run-1"
        / "captures"
        / "manifest.json"
    ).exists()


def test_normal_anonymous_crawl_records_leads_without_capture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    result, received, root = _invoke_normal_crawl_pod(
        monkeypatch,
        tmp_path,
        extra={},
    )

    intake = (
        root
        / "proj-1"
        / "recon"
        / "js-intake"
        / "run-1"
        / "normal-steel-pod.jsonl"
    )
    records = [
        json.loads(line)
        for line in intake.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert result["export"].verdict == "success", result["export"].error
    assert records[1]["record_type"] == "lead"
    assert received["capture_store"] is None


def test_steel_url_filtered_from_graph_remains_in_pod_inventory(tmp_path: Path) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    hidden_url = "https://vendor.example.com/runtime/chunk.js?token=private-value"
    graph = build_crawl_pod(
        run_crawl_fn=lambda target, **kwargs: {
            "endpoints": [],
            "js_urls": [hidden_url],
        },
        parse_fn=lambda stdout: [],
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=lambda assets, observations, project_id, **kwargs: (
            len(assets),
            len(observations),
            assets,
            observations,
        ),
        intake_store=JsIntakeStore(root=root),
    )

    result = graph.invoke(
        {
            "job": STEEL_JOB,
            "input_asset": {"url": "https://app.example.com"},
            "asset_context": "asset-1",
            "extra": {"project_id": "proj-1"},
            "session_id": "run-1-4-steel_crawl-abcd1234",
            "project_id": "proj-1",
            "run_id": "run-1",
            "phase": 4,
        }
    )

    assert result["export"].assets == []
    private_file = (
        root
        / "proj-1"
        / "recon"
        / "js-intake"
        / "run-1"
        / "run-1-4-steel_crawl-abcd1234.jsonl"
    )
    records = [
        json.loads(line)
        for line in private_file.read_text(encoding="utf-8").split("\n")
        if line
    ]
    assert records[0]["lead_count"] == 1
    assert records[1]["exact_url"] == hidden_url

    reference = issue_js_intake_reference("proj-1", "run-1")
    lead = JsIntakeReader(root=root).list(reference=reference, limit=1)["leads"][0]
    assert lead["discovery_class"] == "browser_requested"
    assert "private-value" not in lead["redacted_url"]


def test_steel_failure_is_recorded_without_fabricating_a_parse_error(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    graph = build_crawl_pod(
        run_crawl_fn=lambda target, **kwargs: (_ for _ in ()).throw(
            RuntimeError("steel unavailable")
        ),
        parse_fn=lambda stdout: [],
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=lambda assets, observations, project_id, **kwargs: (
            0,
            len(observations),
            assets,
            observations,
        ),
        intake_store=JsIntakeStore(root=root),
    )

    result = graph.invoke(
        {
            "job": STEEL_JOB,
            "input_asset": {"url": "https://app.example.com"},
            "asset_context": "asset-1",
            "extra": {"project_id": "proj-1"},
            "session_id": "run-1-4-steel_crawl-failed",
            "project_id": "proj-1",
            "run_id": "run-1",
            "phase": 4,
        }
    )

    assert result["export"].verdict == "failed"
    private_file = (
        root
        / "proj-1"
        / "recon"
        / "js-intake"
        / "run-1"
        / "run-1-4-steel_crawl-failed.jsonl"
    )
    envelope = json.loads(private_file.read_text(encoding="utf-8").split("\n")[0])
    assert envelope["terminal_result"] == "failed"
    assert envelope["output_completeness"] == "failed"
    assert envelope["parse_error_count"] == 0


def test_session_fanout_records_each_manifest_and_keeps_failed_session_gap(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)

    def manifest(session_name: str, account: str, url: str, *, partial=False):
        return {
            "schema_version": "steel-crawl/v2",
            "run": {
                "crawl_run_id": session_name,
                "session_name": session_name,
                "account": account,
                "role": account,
                "partial": partial,
                "stop_reason": "partial" if partial else "complete",
            },
            "endpoints": [
                {
                    "url": url,
                    "resource_type": "script",
                    "provenance": "observed",
                    "status_code": 200,
                }
            ],
            "parameters": [],
            "scripts": [],
            "realtime": [],
            "errors": [],
            "stats": {"flows": 1},
        }

    graph = build_crawl_pod(
        run_crawl_fn=lambda target, **kwargs: {
            "manifests": [
                manifest(
                    "session-alpha",
                    "account-alpha",
                    "https://app.example.test/alpha.js",
                ),
                manifest(
                    "session-beta",
                    "account-beta",
                    "https://app.example.test/beta.js",
                    partial=True,
                ),
            ],
            "sessions": [
                {
                    "account": "account-failed",
                    "role": "account-failed",
                    "error": "session unavailable",
                }
            ],
        },
        parse_fn=lambda stdout: [],
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=lambda assets, observations, project_id, **kwargs: (
            len(assets),
            len(observations),
            assets,
            observations,
        ),
        intake_store=JsIntakeStore(root=root),
    )

    result = graph.invoke(
        {
            "job": STEEL_JOB,
            "input_asset": {"url": "https://app.example.test"},
            "asset_context": "asset-1",
            "extra": {"project_id": "proj-1"},
            "session_id": "pod-session",
            "project_id": "proj-1",
            "run_id": "run-1",
            "phase": 4,
        }
    )

    assert result["export"].verdict == "success"
    run_dir = root / "proj-1" / "recon" / "js-intake" / "run-1"
    assert {path.stem for path in run_dir.glob("*.jsonl")} == {
        "session-alpha",
        "session-beta",
        "pod-session--account-failed",
    }
    envelopes = {
        path.stem: json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        for path in run_dir.glob("*.jsonl")
    }
    assert envelopes["session-alpha"]["auth_context_ref"] == "account-alpha"
    assert envelopes["session-alpha"]["output_completeness"] == "complete"
    assert envelopes["session-beta"]["auth_context_ref"] == "account-beta"
    assert envelopes["session-beta"]["output_completeness"] == "partial"
    assert (
        envelopes["pod-session--account-failed"]["output_completeness"]
        == "failed"
    )


def test_explicit_capture_store_opt_in_links_capture_to_lead(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    exact_url = "https://app.example.test/static/authenticated.js?token=private"
    capture_store = SteelCaptureStore(
        root=root,
        limits=CaptureLimits(max_file_bytes=1024, max_run_bytes=4096),
    )
    received = {}

    def run_crawl_fn(
        target,
        *,
        scope,
        browser_auth=None,
        extra=None,
        capture_store=None,
    ):
        extra = extra or {}
        received.update(
            capture_store=capture_store,
        )
        capture_store.record_bytes(
            project_id=extra["project_id"],
            run_id=extra["run_id"],
            pod_id=extra["pod_id"],
            crawl_id="crawl-1",
            auth_context_ref=extra["auth_account"],
            exact_url=exact_url,
            status=200,
            content_type="application/javascript",
            body=b"export const authenticated = true;\n",
            sequence=1,
        )
        return {"endpoints": [], "js_urls": [exact_url]}

    graph = build_crawl_pod(
        run_crawl_fn=run_crawl_fn,
        parse_fn=lambda stdout: [],
        triage_fn=lambda exec_result, assets, job: [],
        curate_fn=lambda assets, observations, project_id, **kwargs: (
            len(assets),
            len(observations),
            assets,
            observations,
        ),
        intake_store=JsIntakeStore(root=root),
        capture_store=capture_store,
    )
    graph.invoke(
        {
            "job": STEEL_JOB,
            "input_asset": {"url": "https://app.example.test"},
            "asset_context": "asset-1",
            "extra": {
                "project_id": "proj-1",
                "run_id": "run-1",
                "pod_id": "run-1-4-steel_crawl-capture",
                "auth_account": "account-1",
                "auth_context": {"cookies": [{"name": "sid", "value": "secret"}]},
            },
            "session_id": "run-1-4-steel_crawl-capture",
            "project_id": "proj-1",
            "run_id": "run-1",
            "phase": 4,
        }
    )

    assert received["capture_store"] is capture_store
    occurrences = capture_store.find_by_url(
        project_id="proj-1",
        run_id="run-1",
        auth_context_ref="account-1",
        exact_url=exact_url,
    )
    assert occurrences[0]["pod_id"] == "run-1-4-steel_crawl-capture"
    assert occurrences[0]["lead_ids"]


def test_live_crawl_bridges_observed_script_flow_without_second_capture(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import polymerhus.app.data_root as data_root_module
    import polymerhus.recon.crawl.steel.live as live_module

    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    monkeypatch.setattr(data_root_module, "DATA_ROOT", root)
    exact_url = "https://app.example.test/static/runtime.js"
    capture_store = SteelCaptureStore(root=root)
    contexts = []
    flow = SimpleNamespace(
        request_id="request-1",
        page_id="page_1",
        action_id=None,
        method="GET",
        url=exact_url,
        resource_type="Script",
        status=200,
        response_headers={"content-type": "application/javascript"},
        mime_type="application/javascript",
        response_body=b"export const captured = true;\n",
        body_truncated=False,
        error=None,
        received_at=1.0,
    )
    monkeypatch.setattr(
        live_module,
        "run_live_crawl",
        lambda context: (
            contexts.append(context)
            or SimpleNamespace(
                manifest=Manifest(
                    run=RunBlock(
                        crawl_run_id=context.run_id,
                        session_name=context.session_name,
                        account=context.account,
                        root_url=context.root_url,
                        started_at="2026-11-09T00:00:00+00:00",
                        stop_reason="complete",
                    )
                ),
                flows=(flow,),
            )
        ),
    )

    result = live_run_crawl_fn(
        "https://app.example.test/",
        scope=["app.example.test"],
        extra={
            "project_id": "proj-1",
            "run_id": "run-1",
            "auth_sessions": [
                {
                    "account": "account-alpha",
                    "role": "account-alpha",
                    "root_url": "https://app.example.test/",
                    "browser_context_ref": "context-alpha",
                }
            ],
        },
        capture_store=capture_store,
    )

    assert contexts[0].account == "account-alpha"
    assert (
        result["manifests"][0]["run"]["session_name"]
        == contexts[0].session_name
    )
    occurrences = capture_store.find_by_url(
        project_id="proj-1",
        run_id="run-1",
        auth_context_ref="account-alpha",
        exact_url=exact_url,
    )
    assert len(occurrences) == 1
    assert occurrences[0]["status"] == "stored"
    assert occurrences[0]["pod_id"] == contexts[0].session_name
