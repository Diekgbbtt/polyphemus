import json
from pathlib import Path

import pytest

from polymerhus.app.data_root import ensure_project
from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_intake import (
    InvalidJsIntakeReference,
    JsIntakeLeadNotFound,
    JsIntakeReader,
    JsIntakeStore,
    issue_js_intake_reference,
)


@pytest.mark.parametrize("url", [
    "https://app.example.test/assets/module?id=42&token=private",
    "http://app.example.test/script", "https://app.example.test/app.js?v=private",
])
def test_debugger_script_url_needs_no_extension_and_keeps_private_query(tmp_path, url):
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    path = JsIntakeStore(root=root).record_manifest(
        project_id="proj-1", run_id="run-1", pod_id="steel-pod", producer="steel_crawl",
        input_context_ref="ctx-hash", terminal_result="success",
        manifest={"schema_version": "steel-crawl/v2", "endpoints": [],
                  "scripts": [{"script_url": url, "script_id": "script-1"},
                              {"script_url": url, "script_id": "script-2"}]},
    )
    records = [json.loads(line) for line in path.read_text().splitlines()]
    page = JsIntakeReader(root=root).list(reference=issue_js_intake_reference("proj-1", "run-1"))
    assert page["coverage"]["complete_zero_result"] is False
    assert len(page["leads"]) == 1
    assert records[1]["exact_url"] == url
    lead = page["leads"][0]
    assert lead["discovery_class"] == "debugger_script"
    assert lead["discovery_classes"] == ["debugger_script"]
    assert lead["script_ids"] == ["script-1", "script-2"]
    assert lead["status"] is None and lead["content_type"] is None
    assert "private" not in json.dumps(page)
    assert page["pods"][0]["output_completeness"] == "complete"


@pytest.mark.parametrize("url", [
    "https://[broken/module", "https://app.test:bad/module", "https:///module",
    "https://app.test:99999/app.js", "http://app.test/a\nmodule", "relative/module",
    "blob:https://app.test/id", "data:text/javascript,alert(1)", "file:///app.js", "", None,
])
def test_unacquirable_debugger_script_is_a_gap_not_complete_zero_result(tmp_path, url):
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    JsIntakeStore(root=root).record_manifest(
        project_id="proj-1", run_id="run-1", pod_id="steel-pod", producer="steel_crawl",
        input_context_ref="ctx-hash", terminal_result="success",
        manifest={"schema_version": "steel-crawl/v2", "endpoints": [],
                  "scripts": [{"script_url": url, "script_id": "script-1"}]},
    )
    page = JsIntakeReader(root=root).list(reference=issue_js_intake_reference("proj-1", "run-1"))
    assert page["leads"] == []
    assert page["coverage"]["complete_zero_result"] is False
    assert page["coverage"]["coverage_gap"]
    assert page["pods"][0]["output_completeness"] == "partial"
    assert page["pods"][0]["parse_error_count"] == 1


def test_extensionless_script_merges_concurrent_discovery_classes():
    from polymerhus.recon.js_intake.extract import extract_steel

    url = "https://app.test/module?id=42"
    result = extract_steel({
        "schema_version": "steel-crawl/v2",
        "endpoints": [
            {"url": url, "resource_type": "script", "provenance": "observed", "status_code": 200},
            {"url": url, "resource_type": "script", "provenance": "declared"},
        ],
        "scripts": [{"script_url": url, "script_id": "script-1"}],
    })
    assert len(result.leads) == 1
    lead = result.leads[0]
    assert lead.exact_url == url
    assert lead.discovery_classes == ("browser_requested", "crawl_declared", "debugger_script")
    assert lead.script_ids == ("script-1",)
    assert lead.status == 200
    assert lead.content_type is None


def test_katana_u2028_record_stays_one_private_lead_and_query_is_redacted(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    exact_url = "https://app.example.com/static/bundle.js?token=private-value&suffix=1"
    stdout = json.dumps(
        {
            "request": {"endpoint": exact_url, "method": "GET"},
            "response": {
                "status_code": 200,
                "headers": {"Content-Type": "text/javascript"},
                "body": "physical line one\u2028still the same JSONL record",
            },
        },
        ensure_ascii=False,
    )

    store = JsIntakeStore(root=root)
    store.record_exec_result(
        project_id="proj-1",
        run_id="run-1",
        pod_id="pod-1",
        producer="katana",
        input_context_ref="ctx-hash",
        exec_result=ExecResult(stdout=stdout, stderr="", returncode=0),
    )

    private_file = root / "proj-1" / "recon" / "js-intake" / "run-1" / "pod-1.jsonl"
    records = [json.loads(line) for line in private_file.read_text().split("\n") if line]
    assert len(records) == 2
    assert records[1]["exact_url"] == exact_url

    reference = issue_js_intake_reference("proj-1", "run-1")
    page = JsIntakeReader(root=root).list(reference=reference, limit=10)

    assert page["leads"] == [
        {
            "lead_id": records[1]["lead_id"],
            "redacted_url": (
                "https://app.example.com/static/bundle.js"
                "?token=%5BREDACTED%5D&suffix=%5BREDACTED%5D"
            ),
            "source_pod": "pod-1",
            "source_tool": "katana",
            "discovery_class": "crawler_discovered",
            "discovery_classes": ["crawler_discovered"],
            "script_ids": [],
            "status": 200,
            "content_type": "text/javascript",
            "auth_context_label": "anonymous",
            "input_context_ref": "ctx-hash",
        }
    ]


def test_same_exact_url_from_two_pods_keeps_two_provenance_observations(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    exact_url = "https://app.example.com/static/shared.js"
    store = JsIntakeStore(root=root)
    store.record_exec_result(
        project_id="proj-1",
        run_id="run-1",
        pod_id="katana-pod",
        producer="katana",
        input_context_ref="ctx-hash",
        exec_result=ExecResult(
            stdout=json.dumps(
                {
                    "request": {"endpoint": exact_url, "method": "GET"},
                    "response": {"status_code": 200},
                }
            ),
            stderr="",
            returncode=0,
        ),
    )
    store.record_manifest(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        producer="steel_crawl",
        input_context_ref="ctx-hash",
        manifest={"endpoints": [], "js_urls": [exact_url]},
        terminal_result="success",
        output_completeness="unknown",
    )

    reference = issue_js_intake_reference("proj-1", "run-1")
    page = JsIntakeReader(root=root).list(reference=reference, limit=10)

    observations = [
        (lead["source_pod"], lead["source_tool"], lead["discovery_class"])
        for lead in page["leads"]
    ]
    assert observations == [
        ("katana-pod", "katana", "crawler_discovered"),
        ("steel-pod", "steel_crawl", "browser_requested"),
    ]
    assert {lead["redacted_url"] for lead in page["leads"]} == {exact_url}


def test_steel_v2_preserves_debugger_provenance_and_script_ids(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    observed_url = "https://app.example.test/static/runtime.js"
    debugger_only_url = "https://app.example.test/static/lazy.js"
    JsIntakeStore(root=root).record_manifest(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-pod",
        producer="steel_crawl",
        input_context_ref="ctx-hash",
        manifest={
            "schema_version": "steel-crawl/v2",
            "endpoints": [
                {
                    "url": observed_url,
                    "resource_type": "script",
                    "provenance": "observed",
                    "status_code": 200,
                }
            ],
            "parameters": [],
            "scripts": [
                {
                    "script_id": "script-observed",
                    "script_url": observed_url,
                    "source_url": observed_url,
                },
                {
                    "script_id": "script-lazy",
                    "script_url": debugger_only_url,
                    "source_url": debugger_only_url,
                },
            ],
            "realtime": [],
            "errors": [],
            "stats": {"flows": 1},
            "run": {"partial": False},
        },
        terminal_result="success",
    )

    private_file = (
        root
        / "proj-1"
        / "recon"
        / "js-intake"
        / "run-1"
        / "steel-pod.jsonl"
    )
    records = [
        json.loads(line)
        for line in private_file.read_text(encoding="utf-8").splitlines()
        if line
    ]
    by_url = {record["exact_url"]: record for record in records[1:]}

    assert by_url[observed_url]["discovery_class"] == "browser_requested"
    assert by_url[observed_url]["discovery_classes"] == [
        "browser_requested",
        "debugger_script",
    ]
    assert by_url[observed_url]["script_ids"] == ["script-observed"]
    assert by_url[debugger_only_url]["discovery_class"] == "debugger_script"
    assert by_url[debugger_only_url]["discovery_classes"] == ["debugger_script"]
    assert by_url[debugger_only_url]["script_ids"] == ["script-lazy"]

    reference = issue_js_intake_reference("proj-1", "run-1")
    page = JsIntakeReader(root=root).list(reference=reference, limit=10)
    public_by_url = {lead["redacted_url"]: lead for lead in page["leads"]}
    assert public_by_url[observed_url]["discovery_classes"] == [
        "browser_requested",
        "debugger_script",
    ]
    assert public_by_url[observed_url]["script_ids"] == ["script-observed"]
    assert public_by_url[debugger_only_url]["discovery_class"] == "debugger_script"


def test_reader_reports_empty_failed_and_partial_pods(tmp_path: Path) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    store = JsIntakeStore(root=root)
    store.record_exec_result(
        project_id="proj-1",
        run_id="run-1",
        pod_id="empty-pod",
        producer="ffuf",
        input_context_ref="ctx-hash",
        exec_result=ExecResult(stdout='{"results": []}', stderr="", returncode=0),
    )
    valid_line = json.dumps(
        {
            "request": {"endpoint": "https://app.example.com/partial.js"},
            "response": {"status_code": 200},
        }
    )
    store.record_exec_result(
        project_id="proj-1",
        run_id="run-1",
        pod_id="partial-pod",
        producer="katana",
        input_context_ref="ctx-hash",
        exec_result=ExecResult(
            stdout=f"{valid_line}\nNOT JSON\n", stderr="", returncode=0
        ),
    )
    store.record_exec_result(
        project_id="proj-1",
        run_id="run-1",
        pod_id="failed-pod",
        producer="ffuf",
        input_context_ref="ctx-hash",
        exec_result=ExecResult(
            stdout=json.dumps(
                {
                    "results": [
                        {
                            "url": "https://app.example.com/failed.js",
                            "status": 403,
                            "content-type": "application/javascript",
                        }
                    ]
                }
            ),
            stderr="ffuf interrupted",
            returncode=1,
        ),
    )

    reference = issue_js_intake_reference("proj-1", "run-1")
    page = JsIntakeReader(root=root).list(reference=reference, limit=10)

    assert {
        pod["pod_id"]: (
            pod["terminal_result"],
            pod["output_completeness"],
            pod["parse_error_count"],
        )
        for pod in page["pods"]
    } == {
        "empty-pod": ("success", "complete", 0),
        "partial-pod": ("success", "partial", 1),
        "failed-pod": ("failed", "failed", 0),
    }
    failed = next(lead for lead in page["leads"] if lead["source_pod"] == "failed-pod")
    assert failed["status"] == 403
    assert failed["content_type"] == "application/javascript"


def test_reader_paginates_without_duplicates_or_loss(tmp_path: Path) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    store = JsIntakeStore(root=root)
    for index in range(5):
        store.record_manifest(
            project_id="proj-1",
            run_id="run-1",
            pod_id=f"steel-{index}",
            producer="steel_crawl",
            input_context_ref="ctx-hash",
            manifest={
                "endpoints": [],
                "js_urls": [f"https://app.example.com/static/{index}.js"],
            },
            terminal_result="success",
            output_completeness="unknown",
        )

    reference = issue_js_intake_reference("proj-1", "run-1")
    reader = JsIntakeReader(root=root)
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        page = reader.list(reference=reference, cursor=cursor, limit=2)
        pages += 1
        seen.extend(lead["lead_id"] for lead in page["leads"])
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert pages == 3
    assert len(seen) == 5
    assert len(set(seen)) == 5


def test_reader_isolates_runs_and_rejects_another_runs_cursor(tmp_path: Path) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    store = JsIntakeStore(root=root)
    for run_id, pod_id, urls in (
        (
            "run-a",
            "pod-a",
            ["https://app.example.com/run-a.js", "https://app.example.com/run-a-2.js"],
        ),
        ("run-b", "pod-b", ["https://app.example.com/run-b.js"]),
    ):
        store.record_manifest(
            project_id="proj-1",
            run_id=run_id,
            pod_id=pod_id,
            producer="steel_crawl",
            input_context_ref="ctx-hash",
            manifest={
                "endpoints": [],
                "js_urls": urls,
            },
            terminal_result="success",
            output_completeness="unknown",
        )

    reader = JsIntakeReader(root=root)
    reference_a = issue_js_intake_reference("proj-1", "run-a")
    reference_b = issue_js_intake_reference("proj-1", "run-b")
    page_a = reader.list(reference=reference_a, limit=1)
    page_b = reader.list(reference=reference_b, limit=1)

    assert {lead["source_pod"] for lead in page_a["leads"]} == {"pod-a"}
    assert {lead["source_pod"] for lead in page_b["leads"]} == {"pod-b"}

    cursor_a = page_a["next_cursor"]
    assert cursor_a is not None
    with pytest.raises(InvalidJsIntakeReference):
        reader.list(reference=reference_b, cursor=cursor_a, limit=1)


def test_retry_atomically_replaces_the_same_pods_inventory(tmp_path: Path) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    store = JsIntakeStore(root=root)
    for url in (
        "https://app.example.com/first.js",
        "https://app.example.com/second.js",
    ):
        store.record_manifest(
            project_id="proj-1",
            run_id="run-1",
            pod_id="retried-pod",
            producer="steel_crawl",
            input_context_ref="ctx-hash",
            manifest={"endpoints": [], "js_urls": [url]},
            terminal_result="success",
            output_completeness="unknown",
        )

    private_file = root / "proj-1" / "recon" / "js-intake" / "run-1" / "retried-pod.jsonl"
    records = [
        json.loads(line)
        for line in private_file.read_text(encoding="utf-8").split("\n")
        if line
    ]
    assert [record.get("exact_url") for record in records[1:]] == [
        "https://app.example.com/second.js"
    ]


def test_get_returns_one_redacted_summary_and_never_exposes_exact_url(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    exact_url = "https://app.example.com/static/private.js?access_token=secret-value"
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
    reader = JsIntakeReader(root=root)
    listed = reader.list(reference=reference, limit=1)["leads"][0]
    fetched = reader.get(reference=reference, lead_id=listed["lead_id"])

    assert fetched == listed
    assert "access_token" in fetched["redacted_url"]
    assert "secret-value" not in json.dumps(fetched)
    assert "exact_url" not in fetched

    other_reference = issue_js_intake_reference("proj-1", "run-2")
    with pytest.raises(JsIntakeLeadNotFound):
        reader.get(reference=other_reference, lead_id=listed["lead_id"])


def test_two_auth_contexts_in_one_run_cannot_list_or_get_each_others_leads(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    store = JsIntakeStore(root=root)
    for context_ref, pod_id, url in (
        (
            "account-alpha",
            "pod-alpha",
            "https://app.example.com/alpha.js?token=alpha-secret",
        ),
        (
            "account-beta",
            "pod-beta",
            "https://app.example.com/beta.js?token=beta-secret",
        ),
    ):
        store.record_manifest(
            project_id="proj-1",
            run_id="run-1",
            pod_id=pod_id,
            producer="steel_crawl",
            input_context_ref="ctx-hash",
            manifest={"endpoints": [], "js_urls": [url]},
            terminal_result="success",
            output_completeness="unknown",
            auth_context_label="authenticated",
            auth_context_ref=context_ref,
        )

    reader = JsIntakeReader(root=root)
    alpha_ref = issue_js_intake_reference(
        "proj-1", "run-1", context_ref="account-alpha"
    )
    beta_ref = issue_js_intake_reference(
        "proj-1", "run-1", context_ref="account-beta"
    )
    alpha = reader.list(reference=alpha_ref, limit=10)
    beta = reader.list(reference=beta_ref, limit=10)

    assert [lead["source_pod"] for lead in alpha["leads"]] == ["pod-alpha"]
    assert [lead["source_pod"] for lead in beta["leads"]] == ["pod-beta"]
    assert [pod["pod_id"] for pod in alpha["pods"]] == ["pod-alpha"]
    assert [pod["pod_id"] for pod in beta["pods"]] == ["pod-beta"]
    assert "alpha-secret" not in repr(alpha)
    assert "beta-secret" not in repr(beta)

    with pytest.raises(JsIntakeLeadNotFound):
        reader.get(reference=beta_ref, lead_id=alpha["leads"][0]["lead_id"])


def test_complete_empty_pod_is_distinct_from_missing_inventory(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    JsIntakeStore(root=root).record_exec_result(
        project_id="proj-1",
        run_id="run-empty",
        pod_id="empty-pod",
        producer="ffuf",
        input_context_ref="ctx-hash",
        exec_result=ExecResult(stdout='{"results": []}', stderr="", returncode=0),
    )
    reader = JsIntakeReader(root=root)

    empty_ref = issue_js_intake_reference("proj-1", "run-empty")
    missing_ref = issue_js_intake_reference("proj-1", "run-missing")
    empty = reader.list(reference=empty_ref)
    missing = reader.list(reference=missing_ref)

    assert empty["coverage"] == {
        "inventory_present": True,
        "inventory_state": "present",
        "complete_zero_result": True,
        "lead_count": 0,
        "coverage_gap": None,
    }
    assert missing["coverage"] == {
        "inventory_present": False,
        "inventory_state": "missing",
        "complete_zero_result": False,
        "lead_count": 0,
        "coverage_gap": "missing_inventory",
    }
