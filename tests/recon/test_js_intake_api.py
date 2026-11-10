from pathlib import Path

from polymerhus.app.data_root import ensure_project
from polymerhus.recon.js_intake import JsIntakeStore, issue_js_intake_reference
from polymerhus.recon.js_intake.api import JsIntakeExecBridge, build_router


def test_exec_bridge_lists_and_gets_only_redacted_scoped_leads(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    exact_url = "https://app.example.com/static/app.js?access_token=secret-value"
    JsIntakeStore(root=root).record_manifest(
        project_id="proj-1",
        run_id="run-1",
        pod_id="pod-1",
        producer="steel_crawl",
        input_context_ref="ctx-hash",
        manifest={"endpoints": [], "js_urls": [exact_url]},
        terminal_result="success",
        output_completeness="unknown",
    )
    reference = issue_js_intake_reference("proj-1", "run-1")
    bridge = JsIntakeExecBridge(root=root)
    payload = bridge.list(reference=reference, limit=1)
    assert len(payload["leads"]) == 1
    assert "secret-value" not in repr(payload)
    assert "exact_url" not in repr(payload)

    lead_id = payload["leads"][0]["lead_id"]
    fetched = bridge.get(reference=reference, lead_id=lead_id)
    assert fetched == payload["leads"][0]
    assert "secret-value" not in repr(fetched)


def test_exec_command_reaches_list_and_get_routes_without_exact_url(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    exact_url = "https://app.example.com/static/app.js?access_token=secret-value"
    JsIntakeStore(root=root).record_manifest(
        project_id="proj-1",
        run_id="run-1",
        pod_id="pod-1",
        producer="steel_crawl",
        input_context_ref="ctx-hash",
        manifest={"endpoints": [], "js_urls": [exact_url]},
        terminal_result="success",
        output_completeness="complete",
    )
    reference = issue_js_intake_reference("proj-1", "run-1")
    router = build_router(root=root)
    list_route = next(
        route for route in router.routes if route.path == "/recon/js-intake/leads"
    )
    get_route = next(
        route
        for route in router.routes
        if route.path == "/recon/js-intake/leads/{lead_id}"
    )
    exec_commands = []

    def exec_list(command: str) -> dict:
        exec_commands.append(command)
        assert reference in command
        assert exact_url not in command
        return list_route.endpoint(reference=reference, cursor=None, limit=10)

    page = exec_list(
        f"curl -fsS -H 'X-JS-Intake-Reference: {reference}' "
        "http://agent:8080/recon/js-intake/leads"
    )
    lead_id = page["leads"][0]["lead_id"]

    def exec_get(command: str) -> dict:
        exec_commands.append(command)
        assert reference in command
        assert exact_url not in command
        return get_route.endpoint(lead_id=lead_id, reference=reference)

    fetched = exec_get(
        f"curl -fsS -H 'X-JS-Intake-Reference: {reference}' "
        f"http://agent:8080/recon/js-intake/leads/{lead_id}"
    )

    assert fetched == page["leads"][0]
    assert len(exec_commands) == 2
    assert "secret-value" not in repr((page, fetched))
