import json
from pathlib import Path

from polymerhus.app.data_root import ensure_project
from polymerhus.recon.domain.pod import build_pod_graph
from polymerhus.recon.domain.types import ExecResult, JobSpec
from polymerhus.recon.js_intake import JsIntakeStore


def _job(tool: str) -> JobSpec:
    return JobSpec(
        tool=tool,
        skill="test",
        command_template=f"{tool} {{target}}",
        produces=["Endpoint"],
        consumes="BaseURL",
    )


def _curate(assets, observations, project_id, **kwargs):
    return len(assets), len(observations), assets, observations


def test_katana_pod_writes_inventory_before_curation(tmp_path: Path) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    exact_url = "https://app.example.com/private.js?token=private-value"
    seen_by_curator = []

    def curate(assets, observations, project_id, **kwargs):
        seen_by_curator.extend(assets)
        return len(assets), 0, assets, observations

    graph = build_pod_graph(
        exec_fn=lambda command, session_id, timeout_s: ExecResult(
            stdout=json.dumps(
                {
                    "request": {"endpoint": exact_url},
                    "response": {"status_code": 200},
                }
            ),
            stderr="",
            returncode=0,
        ),
        curate_fn=curate,
        triage_fn=lambda exec_result, assets, job: [],
        intake_store=JsIntakeStore(root=root),
    )

    graph.invoke(
        {
            "job": _job("katana"),
            "input_asset": {"url": "https://app.example.com"},
            "asset_context": "asset-1",
            "extra": {"project_id": "proj-1", "auth_account": "account-1"},
            "session_id": "run-1-4-katana-abcd1234",
            "project_id": "proj-1",
            "run_id": "run-1",
            "phase": 4,
        }
    )

    private_file = (
        root
        / "proj-1"
        / "recon"
        / "js-intake"
        / "run-1"
        / "run-1-4-katana-abcd1234.jsonl"
    )
    records = [
        json.loads(line)
        for line in private_file.read_text(encoding="utf-8").split("\n")
        if line
    ]
    assert records[0]["producer"] == "katana"
    assert records[0]["auth_context_label"] == "authenticated"
    assert records[0]["auth_context_ref"] == "account-1"
    assert records[0]["input_context_ref"].startswith("ctx_")
    assert records[1]["exact_url"] == exact_url
    assert seen_by_curator


def test_terminal_tool_failure_writes_a_failed_pod_without_changing_graph_export(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    curator_calls = []
    graph = build_pod_graph(
        exec_fn=lambda command, session_id, timeout_s: ExecResult(
            stdout="not json",
            stderr="ffuf failed",
            returncode=1,
        ),
        curate_fn=lambda assets, observations, project_id, **kwargs: (
            curator_calls.append((assets, observations)) or (0, 0, [], [])
        ),
        triage_fn=lambda exec_result, assets, job: [],
        intake_store=JsIntakeStore(root=root),
    )

    result = graph.invoke(
        {
            "job": _job("ffuf"),
            "input_asset": {"url": "https://app.example.com"},
            "asset_context": "asset-1",
            "extra": {"project_id": "proj-1"},
            "session_id": "run-1-4-ffuf-abcd1234",
            "project_id": "proj-1",
            "run_id": "run-1",
            "phase": 4,
        }
    )

    assert result["export"].verdict == "failed"
    assert curator_calls == []
    private_file = (
        root
        / "proj-1"
        / "recon"
        / "js-intake"
        / "run-1"
        / "run-1-4-ffuf-abcd1234.jsonl"
    )
    envelope = json.loads(private_file.read_text(encoding="utf-8").split("\n")[0])
    assert envelope["terminal_result"] == "failed"
    assert envelope["output_completeness"] == "failed"
