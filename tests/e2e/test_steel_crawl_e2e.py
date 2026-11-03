"""Live steel-crawl walkthroughs on the eval server's three target stacks.

Spec: `docs/design/steel-crawl-spec.md` sections 2, 4, 9, 10.4, 11, and 14.
Catalogue: `eval/steel-crawl-e2e/ASSERTIONS.md` (E1-E3, N1-N8).

These tests are the gate, not the red/green loop. They start a real target
stack, mint a real pre-authenticated Steel session, place the real AuthContext
and project skill through the app API, and run the production `steel_crawl`
phase inside the deployed agent container. The crawl's gateway, pod, engine,
CLI, CDP sidecar, Jev policy, ledger, HTTP-history edge, and curator are the
deployed components; only the target stack and the Steel session are setup.

Run on the eval server:

    STEEL_CRAWL_E2E=1 /opt/steel-crawl-e2e/.venv/bin/python -m pytest \
      tests/e2e/test_steel_crawl_e2e.py -k comfyui -s
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

_REPO = Path(
    os.environ.get("STEEL_CRAWL_E2E_REPO", Path(__file__).resolve().parents[2])
)
_SCAFFOLD = _REPO / "eval" / "steel-crawl-e2e"
if str(_SCAFFOLD) not in sys.path:
    sys.path.insert(0, str(_SCAFFOLD))

import scaffold  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.environ.get("STEEL_CRAWL_E2E") != "1",
    reason="the live steel-crawl e2e needs the eval server and STEEL_CRAWL_E2E=1",
)

MAX_DURATION_S = int(os.environ.get("STEEL_CRAWL_MAX_DURATION_S", "900"))
MAX_ACTIONS = int(os.environ.get("STEEL_CRAWL_MAX_ACTIONS", "300"))
KEEP = os.environ.get("STEEL_CRAWL_E2E_KEEP") == "1"


def _evidence(target: str) -> scaffold.RunEvidence:
    return scaffold.run_target(
        target,
        repo=_REPO,
        keep=KEEP,
        max_duration_s=MAX_DURATION_S,
        max_actions=MAX_ACTIONS,
    )


def _host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _labels(node: dict) -> set[str]:
    value = (
        node.get("labels")
        or node.get("label")
        or node.get("type")
        or []
    )
    if isinstance(value, str):
        return {value}
    return {str(item) for item in value}


def _nodes(graph: dict, label: str) -> list[dict]:
    return [
        node
        for node in (graph.get("nodes") or [])
        if label in _labels(node)
    ]


def _json_no_secret(value: object, secrets: tuple[str, ...]) -> None:
    text = json.dumps(value, ensure_ascii=False, default=str)
    for secret in secrets:
        assert secret not in text, "a credential or session value reached the evidence"


def _assert_common(evidence: scaffold.RunEvidence, spec: scaffold.TargetSpec) -> None:
    phase = evidence.phase
    assert phase.get("ok") is True, phase.get("error") or phase.get("traceback")
    manifest = evidence.manifest
    summary = evidence.summary
    run = manifest["run"]

    assert manifest["schema_version"] == "steel-crawl/v2"
    assert run["crawl_run_id"] == evidence.run_id
    assert run["session_name"] == evidence.session_name
    assert run["scope"] == [scaffold.FRONT_HOST]
    assert run["stop_reason"] in {
        "frontier_empty",
        "operator_cancel",
        "session_deadline",
    }
    assert run["partial"] is (run["stop_reason"] != "frontier_empty")

    assert summary["status"] in {"complete", "partial"}
    assert summary["stop_reason"] == run["stop_reason"]
    assert summary["error"] is None
    assert len(summary["pages"]) >= 1
    assert len(summary["actions"]) <= MAX_ACTIONS
    assert summary["flow_count"] >= 1
    assert summary["artifact_count"] == summary["flow_count"]
    assert summary["script_count"] >= 1
    if run["stop_reason"] == "operator_cancel":
        assert len(summary["actions"]) == MAX_ACTIONS
    assert summary["duration_s"] <= MAX_DURATION_S + 300

    edge = phase["edge"]
    flush = summary["flush"]
    assert flush is not None, "the HTTP-history flush did not run"
    assert flush["rejected"] == 0, flush["errors"]
    assert flush["errors"] == []
    assert edge["status"]["artifact_count"] == flush["created"]
    assert flush["created"] + flush["duplicates"] == summary["artifact_count"]
    assert edge["status"]["body_count"] >= 1

    ledger = evidence.ledger_entries
    assert any(entry.get("kind") == "artifact" for entry in ledger)
    assert any(entry.get("kind") == "manifest" for entry in ledger)
    assert sum(1 for entry in ledger if entry.get("kind") == "artifact") == (
        summary["artifact_count"]
    )

    recon = evidence.recon
    assert recon["status"] == "complete"
    jobs = [job for job in recon["per_job"] if job["job"] == "steel_crawl"]
    assert len(jobs) == 1
    assert jobs[0]["status"] == "success"
    assert (jobs[0]["stats"] or {}).get("pods", 0) >= 1

    verdict = summary["verdict"]
    assert verdict is not None
    assert verdict["classification"] == "authenticated"
    if spec.probe:
        assert verdict["probe_source"] == "overview.auth_probe.url"
        assert verdict["probe_url"].endswith(spec.probe)
    else:
        assert verdict["probe_source"] == "legacy_surface_gate"
        assert "auth_probe.url is missing" in verdict["note"]

    auth_accounts = evidence.auth.get("accounts") or {}
    if spec.auth == "none":
        assert auth_accounts == {}
    else:
        assert auth_accounts, "the project auth store carries no account"
        account = auth_accounts.get(spec.account or next(iter(auth_accounts)))
        assert account is not None
        assert account.get("status") == "valid"
        assert (account.get("steel") or {}).get("state")

    before_names = {
        item.get("name") for item in evidence.session_catalogue_before
    }
    phase_names = {
        item.get("name") for item in evidence.session_catalogue
    }
    after_names = {
        item.get("name") for item in evidence.session_catalogue_after
    }
    assert evidence.session_name in before_names
    assert evidence.session_name not in phase_names
    assert evidence.session_name not in after_names

    endpoints = _nodes(evidence.graph, "Endpoint")
    parameters = _nodes(evidence.graph, "Parameter")
    parsed = phase.get("parsed") or {}
    assert parsed.get("present") is True
    assert len(endpoints) == parsed["endpoints"]
    assert len(parameters) == parsed["parameters"]
    assert len(endpoints) <= manifest["stats"]["endpoints"]
    for node in endpoints:
        baseurl = (node.get("properties") or {}).get("baseurl") or ""
        assert _host_of(baseurl) == scaffold.FRONT_HOST, node

    urls = [item["url"] for item in edge["artifacts"]]
    assert not any(".map" in url or "sourceMappingURL" in url for url in urls)
    page_hosts = {_host_of(page["final_url"]) for page in summary["pages"]}
    assert page_hosts == {scaffold.FRONT_HOST}

    removed_fingerprints = {
        item["fingerprint"] for item in summary["removed"]
    }
    action_fingerprints = {
        item["fingerprint"] for item in summary["actions"] if item.get("fingerprint")
    }
    assert not (removed_fingerprints & action_fingerprints)

    for form in summary["forms"]:
        if not form.get("submitted"):
            continue
        path = urlsplit(form["action"]).path or "/"
        assert any(
            urlsplit(item["url"]).path == path
            and 200 <= (item["status"] or 0) < 300
            for item in edge["artifacts"]
        ), form

    _json_no_secret(summary, evidence.secrets)
    _json_no_secret(phase, evidence.secrets)
    _json_no_secret(recon, evidence.secrets)


def test_the_unauthenticated_comfyui_branch_crawls_and_captures():
    evidence = _evidence("comfyui")
    spec = scaffold.TARGETS["comfyui"]

    _assert_common(evidence, spec)

    summary = evidence.summary
    assert len(summary["actions"]) == 0
    assert evidence.manifest["stats"]["parameters"] >= 1
    assert evidence.manifest["stats"]["endpoints"] >= 1
    assert summary["realtime_count"] >= 1
    assert summary["pages"][0]["title"] == "ComfyUI"


def test_the_prestashop_admin_branch_crawls_authenticated_surface():
    evidence = _evidence("prestashop")
    spec = scaffold.TARGETS["prestashop"]

    _assert_common(evidence, spec)

    summary = evidence.summary
    assert len(summary["pages"]) >= 1
    assert len(summary["actions"]) >= 1
    assert evidence.manifest["stats"]["endpoints"] >= 2
    assert evidence.manifest["stats"]["parameters"] >= 1


def test_the_siyucms_admin_branch_crawls_authenticated_surface():
    evidence = _evidence("siyucms")
    spec = scaffold.TARGETS["siyucms"]

    _assert_common(evidence, spec)

    summary = evidence.summary
    assert len(summary["pages"]) >= 2
    assert len(summary["actions"]) >= 1
    assert evidence.manifest["stats"]["endpoints"] >= 2
    assert evidence.manifest["stats"]["parameters"] >= 1
