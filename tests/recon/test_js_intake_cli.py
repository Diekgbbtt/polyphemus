import json
import hashlib
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


def test_cli_subprocess_accepts_leading_hyphen_reference(tmp_path):
    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length))
            seen["reference"] = self.headers.get("X-JS-Intake-Reference")
            seen["payload"] = body
            encoded = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        root = Path(__file__).resolve().parents[2]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(root / "src")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "polymerhus.recon.js_intake.cli",
                "--agent-url",
                f"http://127.0.0.1:{server.server_port}",
                "--reference=-diagnostic-placeholder",
                "context",
            ],
            cwd=root,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"ok": True}
    assert seen["reference"] == "-diagnostic-placeholder"
    assert seen["payload"] == {"operation": "context"}


def test_cli_scan_uses_authorized_input_and_submits_each_mode(monkeypatch, tmp_path):
    from polymerhus.recon.js_acquisition import scan_worker
    from polymerhus.recon.js_intake import cli

    digest = "a" * 64
    calls = []

    def rpc(agent_url, reference, payload, **kwargs):
        calls.append(("rpc", payload))
        if payload["operation"] == "scan_input":
            return {
                "lead_id": "lead_a",
                "run_id": "run-1",
                "work_file_ref": f"/work/js-analysis/run-1/{digest}.js",
                "sha256": digest,
                "size": 42,
            }
        if payload["operation"] == "scan_reuse":
            return {"reused": False}
        raise AssertionError(payload)

    def submit(agent_url, reference, lead_id, result, mode):
        calls.append(("submit", lead_id, mode))
        return {
            "scan_key": "scan-key",
            "overall_status": "complete",
            "idempotent": False,
        }

    def scan_local_file(path, **kwargs):
        assert Path(path) == Path("/work/js-analysis/run-1") / f"{digest}.js"
        assert kwargs["expected_sha256"] == digest
        assert kwargs["expected_size"] == 42
        assert kwargs["executable"] == "/usr/local/bin/jsluice"
        return {
            "status": "complete",
            "scan_key": "scan-key",
            "source": {"sha256": digest, "size": 42},
            "binary": {"sha256": "b" * 64, "version": None},
            "options": {"urls": ["urls", "-j"], "secrets": ["secrets", "-j"]},
            "pattern_fingerprint": scan_worker.PATTERN_FINGERPRINT,
            "modes": {
                "urls": {"status": "complete", "candidate_count": 1},
                "secrets": {"status": "complete", "candidate_count": 0},
            },
            "candidates": [],
        }

    monkeypatch.setattr(cli, "_rpc", rpc)
    monkeypatch.setattr(cli, "_submit_scan", submit)
    monkeypatch.setattr(scan_worker, "binary_identity", lambda executable: {
        "path": "/usr/local/bin/jsluice",
        "sha256": "b" * 64,
        "version": None,
    })
    monkeypatch.setattr(scan_worker, "scan_local_file", scan_local_file)

    result = cli.invoke_operation(
        "http://agent:8080",
        "opaque",
        {"operation": "scan", "lead_id": "lead_a"},
    )

    assert result["status"] == "complete"
    assert result["scan_key"] == "scan-key"
    assert result["modes"]["urls"]["candidate_count"] == 1
    assert [item[2] for item in calls if item[0] == "submit"] == [
        "urls",
        "secrets",
    ]


def test_cli_structure_transfers_verified_private_file_by_body(monkeypatch, tmp_path):
    from polymerhus.recon.js_intake import cli

    work_root = tmp_path / "work"
    source = b'export const child = import("./child.js");\n'
    digest = hashlib.sha256(source).hexdigest()
    source_path = work_root / "run-1" / f"{digest}.js"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(source)
    posted = {}

    def rpc(agent_url, reference, payload, **kwargs):
        assert payload["operation"] == "structure_input"
        return {
            "lead_id": "lead_a",
            "run_id": "run-1",
            "work_file_ref": f"/work/js-analysis/run-1/{digest}.js",
            "sha256": digest,
            "size": len(source),
        }

    def post_bytes(agent_url, reference, path, body, **kwargs):
        posted.update(
            {
                "path": path,
                "body": body,
                "headers": kwargs["headers"],
            }
        )
        return {
            "lead_id": "lead_a",
            "status": "complete",
            "index_id": "stx_test",
            "counts": {"import": 1},
            "source_availability": "verified_current",
            "reused": False,
        }

    monkeypatch.setattr(cli, "_rpc", rpc)
    monkeypatch.setattr(cli, "_post_bytes", post_bytes)

    result = cli._structure_lead(
        "http://agent:8080",
        "opaque",
        "lead_a",
        work_root=work_root,
    )

    assert result["status"] == "complete"
    assert posted["body"] == source
    assert posted["path"] == "/recon/js-analysis/structure/start/lead_a"
    assert posted["headers"]["X-JS-Work-SHA256"] == digest
    assert 0 < float(posted["headers"]["X-JS-Remaining-Seconds"]) <= 20
    assert source.decode() not in json.dumps(result)


def test_cli_acquire_reference_registers_then_uses_existing_worker(
    monkeypatch,
):
    from polymerhus.recon.js_acquisition import kali_worker
    from polymerhus.recon.js_intake import cli

    calls = []

    def rpc(agent_url, reference, payload):
        calls.append(("rpc", payload))
        return {
            "status": "registered",
            "lead_id": "lead_child",
            "parent_item_id": payload["target"],
            "discovery_class": "code_reference",
        }

    def acquire(**kwargs):
        calls.append(("acquire", kwargs))
        return {
            "lead_id": "lead_child",
            "status": "acquired",
            "sha256": "a" * 64,
            "size": 42,
            "work_file_ref": "/work/js-analysis/run-1/" + "a" * 64 + ".js",
        }

    monkeypatch.setattr(cli, "_rpc", rpc)
    monkeypatch.setattr(kali_worker, "acquire_lead_to_work_file", acquire)

    result = cli.invoke_operation(
        "http://agent:8080",
        "opaque",
        {"operation": "acquire-reference", "item_id": "sti_parent"},
    )

    assert result["lead_id"] == "lead_child"
    assert result["parent_item_id"] == "sti_parent"
    assert calls[0] == (
        "rpc",
        {
            "operation": "acquire_reference",
            "target": "sti_parent",
        },
    )
    assert calls[1][1]["lead_id"] == "lead_child"
    assert calls[1][1]["reference"] == "opaque"


def test_cli_main_serializes_structure_list_and_detail(monkeypatch, capsys):
    from polymerhus.recon.js_intake import cli

    payloads = []

    def rpc(agent_url, reference, payload, **kwargs):
        payloads.append(payload)
        if payload["operation"] == "structure_items":
            return {
                "items": [{"item_id": "sti_a", "kind": "import"}],
                "next_cursor": None,
            }
        return {"item": {"item_id": "sti_a", "kind": "import"}}

    monkeypatch.setattr(cli, "_rpc", rpc)
    assert cli.main(
        [
            "--agent-url",
            "http://agent:8080",
            "--reference",
            "opaque",
            "structure-items",
            "lead_a",
            "--kind",
            "import",
            "--limit",
            "2",
        ]
    ) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["items"][0]["item_id"] == "sti_a"

    assert cli.main(
        [
            "--agent-url",
            "http://agent:8080",
            "--reference",
            "opaque",
            "structure-item",
            "sti_a",
        ]
    ) == 0
    detailed = json.loads(capsys.readouterr().out)
    assert detailed["item"]["kind"] == "import"
    assert payloads == [
        {
            "operation": "structure_items",
            "lead_id": "lead_a",
            "kind": "import",
            "limit": 2,
            "cursor": None,
        },
        {
            "operation": "structure_item",
            "target": "sti_a",
        },
    ]


def test_cli_read_code_verifies_work_file_and_submits_private_bytes(
    monkeypatch, tmp_path
):
    from polymerhus.recon.js_intake import cli

    source = b'const api = fetch("/api/items");\n'
    digest = hashlib.sha256(source).hexdigest()
    work_root = tmp_path / "work"
    source_path = work_root / "run-1" / "recovered" / f"{digest}.js"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(source)
    posted = {}

    def rpc(agent_url, reference, payload, **kwargs):
        assert payload == {
            "operation": "code_read_input",
            "selector_type": "source",
            "target": "src_a",
        }
        return {
            "lead_id": "lead_a",
            "selector": {"type": "source", "id": "src_a"},
            "work_file_ref": (
                f"/work/js-analysis/run-1/recovered/{digest}.js"
            ),
            "content_sha256": digest,
            "size": len(source),
            "kind": "typescript",
            "range_start": 0,
            "range_end": len(source),
        }

    def post_bytes(agent_url, reference, path, body, **kwargs):
        posted.update(
            {
                "path": path,
                "body": body,
                "headers": kwargs["headers"],
            }
        )
        return {
            "read_id": "read_a",
            "code": 'const api = fetch("/api/items");\n',
            "content_sha256": digest,
            "original_start": 0,
            "original_end": len(source),
            "delivery_status": "prepared",
        }

    monkeypatch.setattr(cli, "_rpc", rpc)
    monkeypatch.setattr(cli, "_post_bytes", post_bytes)

    result = cli._read_code(
        "http://agent:8080",
        "opaque",
        {"item": None, "source": "src_a", "match": None},
        work_root=work_root,
        window_bytes=4096,
        cursor=None,
    )

    assert result["read_id"] == "read_a"
    assert posted["body"] == source
    assert posted["path"] == "/recon/js-specialist/code/read"
    assert posted["headers"]["X-JS-Selector-Type"] == "source"
    assert posted["headers"]["X-JS-Selector-Id"] == "src_a"


def test_cli_search_reads_only_authorized_verified_sources(monkeypatch, tmp_path):
    from polymerhus.recon.js_intake import cli

    generated = b'const alpha = "one";\n'
    recovered = b"export const alpha = true;\n"
    digests = {
        "lead_a": hashlib.sha256(generated).hexdigest(),
        "src_a": hashlib.sha256(recovered).hexdigest(),
    }
    work_root = tmp_path / "work"
    paths = {
        "lead_a": work_root / "run-1" / f"{digests['lead_a']}.js",
        "src_a": work_root
        / "run-1"
        / "recovered"
        / f"{digests['src_a']}.js",
    }
    for source_id, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(generated if source_id == "lead_a" else recovered)
    submitted = {}

    def rpc(agent_url, reference, payload, **kwargs):
        if payload["operation"] == "code_search_input":
            return {
                "lead_id": "lead_a",
                "sources": [
                    {
                        "source_id": "lead_a",
                        "lead_id": "lead_a",
                        "kind": "generated",
                        "content_sha256": digests["lead_a"],
                        "size": len(generated),
                        "work_file_ref": (
                            f"/work/js-analysis/run-1/{digests['lead_a']}.js"
                        ),
                    },
                    {
                        "source_id": "src_a",
                        "lead_id": "lead_a",
                        "kind": "typescript",
                        "content_sha256": digests["src_a"],
                        "size": len(recovered),
                        "work_file_ref": (
                            "/work/js-analysis/run-1/recovered/"
                            f"{digests['src_a']}.js"
                        ),
                    },
                ],
            }
        raise AssertionError(payload)

    def post_json(url, reference, payload, **kwargs):
        submitted.update(payload)
        return {
            "search_id": "search_a",
            "matches": [{"match_id": "match_a"}],
            "next_cursor": None,
        }

    monkeypatch.setattr(cli, "_rpc", rpc)
    monkeypatch.setattr(cli, "_post_json", post_json)

    result = cli._search_code(
        "http://agent:8080",
        "opaque",
        lead_id="lead_a",
        text="alpha",
        limit=5,
        cursor=None,
        work_root=work_root,
    )

    assert result["search_id"] == "search_a"
    assert set(submitted["contents"]) == {"lead_a", "src_a"}
    assert "alpha" in __import__("base64").b64decode(
        submitted["contents"]["lead_a"]
    ).decode()


def test_cli_search_resumes_scan_segment_with_snapshot_cursor(
    monkeypatch, tmp_path
):
    from polymerhus.recon.js_intake import cli

    source = b"export const alpha = true;\n"
    digest = hashlib.sha256(source).hexdigest()
    path = (
        tmp_path
        / "work"
        / "run-1"
        / "recovered"
        / f"{digest}.js"
    )
    path.parent.mkdir(parents=True)
    path.write_bytes(source)
    posted = {}

    def rpc(agent_url, reference, payload, **kwargs):
        assert payload["operation"] == "code_search_resume"
        return {
            "mode": "scan",
            "search_id": "search_a",
            "lead_id": "lead_a",
            "sources": [
                {
                    "source_id": "src_a",
                    "lead_id": "lead_a",
                    "kind": "typescript",
                    "source_tool": "source_map",
                    "content_sha256": digest,
                    "size": len(source),
                    "work_file_ref": (
                        f"/work/js-analysis/run-1/recovered/{digest}.js"
                    ),
                }
            ],
            "scan_resume_cursor": "scan-cursor",
        }

    def post_json(url, reference, payload, **kwargs):
        posted.update(payload)
        return {"search_id": "search_a", "matches": []}

    monkeypatch.setattr(cli, "_rpc", rpc)
    monkeypatch.setattr(cli, "_post_json", post_json)
    result = cli._search_code(
        "http://agent:8080",
        "opaque",
        lead_id="lead_a",
        text="alpha",
        limit=5,
        cursor="scan-cursor",
        work_root=tmp_path / "work",
    )

    assert result["search_id"] == "search_a"
    assert posted["resume_cursor"] == "scan-cursor"
    assert set(posted["contents"]) == {"src_a"}


def test_cli_triage_operations_are_serialized_without_new_tools(monkeypatch):
    from polymerhus.recon.js_intake import cli

    payloads = []

    def rpc(agent_url, reference, payload, **kwargs):
        payloads.append(payload)
        return {"ok": True}

    monkeypatch.setattr(cli, "_rpc", rpc)
    cli.invoke_operation(
        "http://agent:8080",
        "opaque",
        {
            "operation": "triage-select",
            "source": None,
            "item": None,
            "match": "match_a",
            "question": "Which request?",
            "priority": "high",
        },
    )
    cli.invoke_operation(
        "http://agent:8080",
        "opaque",
        {
            "operation": "triage-update",
            "span_id": "span_a",
            "state": "deferred",
            "read_id": None,
            "reason": "Need adjacent caller",
        },
    )
    cli.invoke_operation(
        "http://agent:8080",
        "opaque",
        {
            "operation": "triage-list",
            "limit": 2,
            "cursor": None,
        },
    )

    assert payloads[0]["operation"] == "triage_select"
    assert payloads[0]["selector_type"] == "match"
    assert payloads[0]["target"] == "match_a"
    assert payloads[1]["operation"] == "triage_update"
    assert payloads[1]["reason"] == "Need adjacent caller"
    assert payloads[2] == {
        "operation": "triage_list",
        "limit": 2,
        "cursor": None,
    }


def test_cli_behavior_operations_serialize_compact_json_and_limits(
    monkeypatch,
):
    from polymerhus.recon.js_intake import cli

    payloads = []

    def rpc(agent_url, reference, payload, **kwargs):
        payloads.append(payload)
        return {'ok': True}

    monkeypatch.setattr(cli, '_rpc', rpc)
    record = {
        'question_ref': 'span_a',
        'steps': [{
            'kind': 'input',
            'text': 'The caller supplies the value.',
            'read_ids': ['read_a'],
        }],
        'assumptions': [],
        'gaps': ['Runtime result is unknown.'],
    }
    result = cli.invoke_operation(
        'http://agent:8080',
        'opaque',
        cli.parse_operation([
            'behavior-save',
            '--record',
            json.dumps(record, separators=(',', ':')),
        ]),
    )
    assert result == {'ok': True}
    assert payloads[-1] == {
        'operation': 'behavior_save',
        'record': record,
        'dependencies': [],
    }

    cli.invoke_operation(
        'http://agent:8080',
        'opaque',
        cli.parse_operation(['behavior-list', '--limit', '3']),
    )
    assert payloads[-1] == {
        'operation': 'behavior_list',
        'limit': 3,
        'cursor': None,
    }

    before = len(payloads)
    assert cli.invoke_operation(
        'http://agent:8080',
        'opaque',
        cli.parse_operation([
            'behavior-save',
            '--record',
            json.dumps({'too_large': 'x' * 4100}),
        ]),
    )['error'] == 'behavior_record_too_large'
    assert cli.invoke_operation(
        'http://agent:8080',
        'opaque',
        cli.parse_operation([
            'behavior-save',
            '--record',
            '{not-json}',
        ]),
    )['error'] == 'invalid_behavior_record'
    assert len(payloads) == before


def test_cli_behavior_save_forwards_internal_remaining_deadline(
    monkeypatch,
):
    from polymerhus.recon.js_intake import cli

    headers = []

    def post_json(url, reference, payload, **kwargs):
        headers.append(kwargs.get('headers'))
        return {'ok': True}

    monkeypatch.setattr(cli, '_post_json', post_json)
    result = cli.invoke_operation(
        'http://agent:8080',
        'opaque',
        cli.parse_operation([
            'behavior-save',
            '--record',
            json.dumps({
                'question_ref': 'span_a',
                'steps': [],
            }),
            '--deadline-s',
            '2',
        ]),
    )

    assert result == {'ok': True}
    remaining = float(
        headers[0]['X-JS-Remaining-Seconds']
    )
    assert 0 < remaining <= 2


def test_cli_behavior_save_transfers_only_private_bytes_and_strips_requests(
    monkeypatch,
    tmp_path,
):
    from polymerhus.recon.js_intake import cli

    body = b"console.log('private body');\n"
    digest = hashlib.sha256(body).hexdigest()
    work = tmp_path / "r" / f"{digest}.js"
    work.parent.mkdir(parents=True)
    work.write_bytes(body)
    rpc_calls = []
    transfer_calls = []

    def rpc(agent_url, reference, payload, **kwargs):
        rpc_calls.append(payload)
        if payload["operation"] == "behavior_save":
            return {
                "behavior_id": "behavior_a",
                "revision": 1,
                "retention": {
                    "status": "pending",
                    "retained_count": 0,
                    "pending_count": 1,
                    "gap_count": 0,
                    "gaps": [],
                    "transfer_requests": [{
                        "request_id": "jsret_a",
                        "sha256": digest,
                        "size_bytes": len(body),
                        "work_file_ref": (
                            f"/work/js-analysis/r/{digest}.js"
                        ),
                    }],
                },
            }
        assert payload["operation"] == "retention_status"
        return {
            "links": [{
                "sha256": digest,
                "origin": "cited_read",
                "read_id": "read_a",
                "status": "retained",
                "failure_reason": None,
            }],
            "retained_count": 1,
            "pending_count": 0,
            "gap_count": 0,
        }

    def post_bytes(
        agent_url,
        reference,
        path,
        sent_body,
        *,
        headers=None,
        deadline=None,
    ):
        transfer_calls.append((path, sent_body, headers, deadline))
        return {
            "links": [{"sha256": digest, "status": "retained"}],
            "retained_count": 1,
            "pending_count": 0,
            "gap_count": 0,
        }

    monkeypatch.setattr(cli, "_rpc", rpc)
    monkeypatch.setattr(cli, "_post_bytes", post_bytes)
    result = cli._behavior_save(
        "http://agent:8080",
        "opaque",
        cli.parse_operation([
            "behavior-save",
            "--record",
            json.dumps({
                "question_ref": "span_a",
                "steps": [],
            }),
        ]),
        work_root=tmp_path,
    )

    assert result["record_saved"] is True
    assert result["retention"]["status"] == "complete"
    assert "transfer_requests" not in result["retention"]
    assert transfer_calls[0][1] == body
    assert transfer_calls[0][2]["X-JS-Retention-Request"] == "jsret_a"
    assert 0 < float(
        transfer_calls[0][2]["X-JS-Remaining-Seconds"]
    ) <= 42
    serialized = json.dumps(result)
    assert "console.log" not in serialized
    assert "private body" not in serialized
    assert all(
        "retention/transfer" not in json.dumps(payload)
        for payload in rpc_calls
    )


def test_cli_behavior_save_preserves_uncertain_transfer_as_pending(
    monkeypatch,
    tmp_path,
):
    from polymerhus.recon.js_intake import cli

    body = b"const uncertain = true;\n"
    digest = hashlib.sha256(body).hexdigest()
    work = tmp_path / "r" / f"{digest}.js"
    work.parent.mkdir(parents=True)
    work.write_bytes(body)

    def rpc(agent_url, reference, payload, **kwargs):
        if payload["operation"] == "behavior_save":
            return {
                "behavior_id": "behavior_a",
                "revision": 1,
                "retention": {
                    "status": "pending",
                    "retained_count": 0,
                    "pending_count": 1,
                    "gap_count": 0,
                    "gaps": [],
                    "transfer_requests": [{
                        "request_id": "jsret_a",
                        "sha256": digest,
                        "size_bytes": len(body),
                        "work_file_ref": (
                            f"/work/js-analysis/r/{digest}.js"
                        ),
                    }],
                },
            }
        return {
            "links": [{
                "sha256": digest,
                "origin": "cited_read",
                "read_id": "read_a",
                "status": "pending",
                "failure_reason": None,
            }],
            "retained_count": 0,
            "pending_count": 1,
            "gap_count": 0,
        }

    monkeypatch.setattr(cli, "_rpc", rpc)
    monkeypatch.setattr(
        cli,
        "_post_bytes",
        lambda *args, **kwargs: {
            "error": "recovery_deadline",
            "remote_outcome_uncertain": True,
        },
    )
    result = cli._behavior_save(
        "http://agent:8080",
        "opaque",
        cli.parse_operation([
            "behavior-save",
            "--record",
            json.dumps({"question_ref": "span_a", "steps": []}),
        ]),
        work_root=tmp_path,
    )

    assert result["record_saved"] is True
    assert result["retention"]["status"] == "pending"
    assert result["retention"]["pending_count"] == 1
    assert any(
        gap["reason"] == "recovery_deadline"
        for gap in result["retention"]["gaps"]
    )


def test_cli_behavior_save_does_not_hide_initial_gap_when_status_is_empty(
    monkeypatch,
    tmp_path,
):
    from polymerhus.recon.js_intake import cli

    def rpc(agent_url, reference, payload, **kwargs):
        if payload["operation"] == "behavior_save":
            return {
                "behavior_id": "behavior_a",
                "revision": 1,
                "retention": {
                    "status": "gap",
                    "retained_count": 0,
                    "pending_count": 0,
                    "gap_count": 1,
                    "gaps": [{
                        "sha256": "a" * 64,
                        "reason": "complete_file_unavailable",
                    }],
                    "transfer_requests": [],
                },
            }
        return {
            "links": [],
            "retained_count": 0,
            "pending_count": 0,
            "gap_count": 0,
        }

    monkeypatch.setattr(cli, "_rpc", rpc)
    result = cli._behavior_save(
        "http://agent:8080",
        "opaque",
        cli.parse_operation([
            "behavior-save",
            "--record",
            json.dumps({"question_ref": "span_a", "steps": []}),
        ]),
        work_root=tmp_path,
    )

    assert result["record_saved"] is True
    assert result["retention"]["status"] == "gap"
    assert {
        gap["reason"] for gap in result["retention"]["gaps"]
    } == {
        "complete_file_unavailable",
        "retention_links_missing",
    }


def test_cli_behavior_save_uses_one_deadline_for_multiple_transfers(
    monkeypatch,
    tmp_path,
):
    from polymerhus.recon.js_intake import cli

    bodies = (b"first transfer", b"second transfer")
    requests = []
    for index, body in enumerate(bodies):
        digest = hashlib.sha256(body).hexdigest()
        path = tmp_path / "r" / f"{index}-{digest}.js"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        requests.append({
            "request_id": f"jsret_{index}",
            "sha256": digest,
            "size_bytes": len(body),
            "work_file_ref": (
                f"/work/js-analysis/r/{index}-{digest}.js"
            ),
        })

    def rpc(agent_url, reference, payload, **kwargs):
        if payload["operation"] == "behavior_save":
            return {
                "behavior_id": "behavior_a",
                "revision": 1,
                "retention": {
                    "status": "pending",
                    "retained_count": 0,
                    "pending_count": 2,
                    "gap_count": 0,
                    "gaps": [],
                    "transfer_requests": requests,
                },
            }
        return {
            "links": [
                {
                    "sha256": requests[0]["sha256"],
                    "origin": "cited_read",
                    "read_id": "read_a",
                    "status": "retained",
                    "failure_reason": None,
                },
                {
                    "sha256": requests[1]["sha256"],
                    "origin": "cited_read",
                    "read_id": "read_b",
                    "status": "pending",
                    "failure_reason": None,
                },
            ],
            "retained_count": 1,
            "pending_count": 1,
            "gap_count": 0,
        }

    deadlines = []

    def post_bytes(*args, **kwargs):
        deadlines.append(kwargs["deadline"])
        if len(deadlines) == 1:
            return {"retained_count": 1}
        return {
            "error": "recovery_deadline",
            "remote_outcome_uncertain": True,
        }

    monkeypatch.setattr(cli, "_rpc", rpc)
    monkeypatch.setattr(cli, "_post_bytes", post_bytes)
    result = cli._behavior_save(
        "http://agent:8080",
        "opaque",
        cli.parse_operation([
            "behavior-save",
            "--record",
            json.dumps({"question_ref": "span_a", "steps": []}),
        ]),
        work_root=tmp_path,
    )

    assert len(deadlines) == 2
    assert deadlines[0] is deadlines[1]
    assert result["retention"]["status"] == "pending"
    assert result["retention"]["pending_count"] == 1
    assert any(
        gap["reason"] == "recovery_deadline"
        for gap in result["retention"]["gaps"]
    )


def test_cli_scan_reuses_completed_scan_without_running_jsluice(monkeypatch):
    from polymerhus.recon.js_intake import cli

    def rpc(agent_url, reference, payload):
        if payload["operation"] == "scan_input":
            return {
                "lead_id": "lead_a",
                "run_id": "run-1",
                "work_file_ref": "/work/js-analysis/run-1/" + "a" * 64 + ".js",
                "sha256": "a" * 64,
                "size": 10,
            }
        if payload["operation"] == "scan_reuse":
            return {
                "reused": True,
                "scan_key": "scan-key",
                "status": "complete",
                "modes": {
                    "urls": {"status": "complete"},
                    "secrets": {"status": "complete"},
                },
            }
        raise AssertionError(payload)

    monkeypatch.setattr(cli, "_rpc", rpc)
    monkeypatch.setattr(
        cli,
        "_scan_local_file",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("jsluice must not rerun")
        ),
    )

    result = cli.invoke_operation(
        "http://agent:8080",
        "opaque",
        {"operation": "scan", "lead_id": "lead_a"},
    )

    assert result["status"] == "complete"
    assert result["reused"] is True


def test_cli_recover_transfers_verified_source_and_resumes_after_failure(
    monkeypatch,
    tmp_path,
):
    from polymerhus.recon.js_intake import cli

    work_root = tmp_path / "work"
    source = b"export const recovered = true;\n"
    digest = hashlib.sha256(source).hexdigest()
    js = b"console.log('bundle');\n"
    js_hash = hashlib.sha256(js).hexdigest()
    js_path = work_root / "run-1" / f"{js_hash}.js"
    js_path.parent.mkdir(parents=True)
    js_path.write_bytes(js)
    attempts = {"get": 0}

    def rpc(agent_url, reference, payload, **kwargs):
        if payload["operation"] == "recovery_input":
            return {
                "run_id": "run-1",
                "work_file_ref": f"/work/js-analysis/run-1/{js_hash}.js",
                "sha256": js_hash,
                "size": len(js),
            }
        if payload["operation"] == "recovery_sources":
            return {
                "lead_id": "lead_a",
                "total": 1,
                "next_cursor": None,
                "sources": [
                    {
                        "source_id": "src_a",
                        "status": "pending",
                        "content_sha256": digest,
                        "size": len(source),
                        "work_file_ref": (
                            f"/work/js-analysis/run-1/recovered/{digest}.js"
                        ),
                    }
                ],
            }
        raise AssertionError(payload)

    monkeypatch.setattr(cli, "_rpc", rpc)
    monkeypatch.setattr(
        cli,
        "_post_bytes",
        lambda *args, **kwargs: {
            "status": "complete",
            "map_id": "map_a",
            "source_count": 1,
            "gaps": [],
        },
    )

    def get_bytes(*args, **kwargs):
        attempts["get"] += 1
        if attempts["get"] == 1:
            raise RuntimeError("transfer_failed")
        return source, {}

    monkeypatch.setattr(cli, "_get_bytes", get_bytes)
    monkeypatch.setattr(
        cli,
        "_post_json",
        lambda *args, **kwargs: {"status": "available"},
    )

    first = cli._recover_lead(
        "http://agent:8080",
        "opaque",
        "lead_a",
        work_root=work_root,
    )
    second = cli._recover_lead(
        "http://agent:8080",
        "opaque",
        "lead_a",
        work_root=work_root,
    )

    final = work_root / "run-1" / "recovered" / f"{digest}.js"
    assert first["status"] == "partial"
    assert second["status"] == "complete"
    assert final.read_bytes() == source
    assert source.decode() not in json.dumps(second)


def test_cli_recovered_commands_use_bridge_recovery_operations(monkeypatch):
    from polymerhus.recon.js_intake import cli

    payloads = []

    def rpc(agent_url, reference, payload):
        payloads.append(payload)
        return {"ok": True}

    monkeypatch.setattr(cli, "_rpc", rpc)

    cli.invoke_operation(
        "http://agent:8080",
        "opaque",
        cli.parse_operation(
            ["recovered-sources", "lead_a", "--limit", "5"]
        ),
    )
    cli.invoke_operation(
        "http://agent:8080",
        "opaque",
        cli.parse_operation(["recovered-source", "src_a"]),
    )

    assert payloads == [
        {
            "operation": "recovery_sources",
            "lead_id": "lead_a",
            "limit": 5,
            "cursor": None,
        },
        {
            "operation": "recovery_source",
            "target": "src_a",
        },
    ]


def test_cli_recover_stops_partial_at_recovery_deadline(monkeypatch, tmp_path):
    from polymerhus.recon.js_intake import cli

    work_root = tmp_path / "work"
    first = b"first-source\n"
    second = b"second-source\n"
    first_sha = hashlib.sha256(first).hexdigest()
    second_sha = hashlib.sha256(second).hexdigest()
    js = b"console.log('bundle');\n"
    js_sha = hashlib.sha256(js).hexdigest()
    js_path = work_root / "run-1" / f"{js_sha}.js"
    js_path.parent.mkdir(parents=True)
    js_path.write_bytes(js)
    confirmed = []
    clock = {"now": 0.0}

    monkeypatch.setattr(
        cli,
        "_rpc",
        lambda agent_url, reference, payload, **kwargs: (
            {
                "run_id": "run-1",
                "work_file_ref": f"/work/js-analysis/run-1/{js_sha}.js",
                "sha256": js_sha,
                "size": len(js),
            }
            if payload["operation"] == "recovery_input"
            else {
                "lead_id": "lead_a",
                "total": 2,
                "next_cursor": None,
                "sources": [
                    {
                        "source_id": "src_first",
                        "status": "pending",
                        "content_sha256": first_sha,
                        "size": len(first),
                        "work_file_ref": (
                            f"/work/js-analysis/run-1/recovered/{first_sha}.js"
                        ),
                    },
                    {
                        "source_id": "src_second",
                        "status": "pending",
                        "content_sha256": second_sha,
                        "size": len(second),
                        "work_file_ref": (
                            f"/work/js-analysis/run-1/recovered/{second_sha}.js"
                        ),
                    },
                ],
            }
        ),
    )
    monkeypatch.setattr(
        cli,
        "_post_bytes",
        lambda *args, **kwargs: {
            "status": "complete",
            "map_id": "map_a",
            "source_count": 2,
            "deadline_s": 1,
            "gaps": [],
        },
    )
    monkeypatch.setattr(
        cli,
        "_get_bytes",
        lambda *args, **kwargs: (
            first if not confirmed else second,
            {},
        ),
    )
    def post_json(url, reference, body, **kwargs):
        confirmed.append(body["source_id"])
        clock["now"] = 1.1
        return {"status": "available"}

    monkeypatch.setattr(cli, "_post_json", post_json)
    monkeypatch.setattr(cli.time, "monotonic", lambda: clock["now"])

    result = cli._recover_lead(
        "http://agent:8080",
        "opaque",
        "lead_a",
        work_root=work_root,
    )

    assert result["status"] == "partial"
    assert result["available"] == 1
    assert result["source_count"] == 2
    assert result["failures"] == ["recovery_deadline"]
    assert confirmed == ["src_first"]
    assert (
        work_root / "run-1" / "recovered" / f"{first_sha}.js"
    ).read_bytes() == first
    assert not (
        work_root / "run-1" / "recovered" / f"{second_sha}.js"
    ).exists()


def test_cli_get_bytes_deadline_bounds_slow_continuous_response(monkeypatch):
    from polymerhus.recon.js_intake import cli

    class SlowResponse:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            body = bytearray()
            for _ in range(6):
                time.sleep(0.02)
                body.extend(b"x")
            return bytes(body)

        def close(self):
            pass

    monkeypatch.setattr(
        cli,
        "urlopen",
        lambda request, timeout: SlowResponse(),
    )
    started = time.monotonic()

    with pytest.raises(cli.RecoveryDeadline):
        cli._get_bytes(
            "http://agent:8080",
            "opaque",
            "src_a",
            1024,
            deadline=started + 0.06,
        )

    assert time.monotonic() - started < 0.2


def test_cli_post_bytes_deadline_bounds_slow_recovery_start(monkeypatch):
    from polymerhus.recon.js_intake import cli

    class SlowResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            time.sleep(0.2)
            return b'{"status":"complete","deadline_s":35}'

    monkeypatch.setattr(
        cli,
        "urlopen",
        lambda request, timeout: SlowResponse(),
    )
    started = time.monotonic()

    result = cli._post_bytes(
        "http://agent:8080",
        "opaque",
        "/recon/js-analysis/recovery/start/lead_a",
        b"bundle",
        deadline=started + 0.06,
    )

    assert result == {
        "error": "recovery_deadline",
        "remote_outcome_uncertain": True,
    }
    assert time.monotonic() - started < 0.2


def test_recovery_start_uses_total_deadline_after_slow_input(
    monkeypatch, tmp_path
):
    from polymerhus.recon.js_intake import cli

    work_root = tmp_path / "work"
    js = b"console.log('bundle');\n"
    digest = hashlib.sha256(js).hexdigest()
    source = work_root / "run-1" / f"{digest}.js"
    source.parent.mkdir(parents=True)
    source.write_bytes(js)
    clock = {"now": 0.0}
    observed = {}

    def rpc(agent_url, reference, payload, **kwargs):
        clock["now"] = 30.0
        return {
            "run_id": "run-1",
            "work_file_ref": f"/work/js-analysis/run-1/{digest}.js",
            "sha256": digest,
            "size": len(js),
        }

    def post_bytes(*args, **kwargs):
        observed["remaining"] = kwargs["deadline"] - clock["now"]
        return {
            "error": "recovery_deadline",
            "remote_outcome_uncertain": True,
        }

    monkeypatch.setattr(cli, "_rpc", rpc)
    monkeypatch.setattr(cli, "_post_bytes", post_bytes)
    monkeypatch.setattr(cli.time, "monotonic", lambda: clock["now"])

    result = cli._recover_lead(
        "http://agent:8080",
        "opaque",
        "lead_a",
        work_root=work_root,
    )

    assert observed["remaining"] == pytest.approx(5.0)
    assert result["status"] == "partial"
    assert result["failures"] == ["recovery_deadline"]
    assert result["remote_state_uncertain"] is True


def test_recovery_deadline_during_confirm_preserves_file_and_is_uncertain(
    monkeypatch, tmp_path
):
    from polymerhus.recon.js_intake import cli

    work_root = tmp_path / "work"
    js = b"console.log('bundle');\n"
    js_sha = hashlib.sha256(js).hexdigest()
    source = b"export const slowConfirmation = true;\n"
    source_sha = hashlib.sha256(source).hexdigest()
    js_path = work_root / "run-1" / f"{js_sha}.js"
    js_path.parent.mkdir(parents=True)
    js_path.write_bytes(js)
    requested_urls = []

    def rpc(agent_url, reference, payload, **kwargs):
        if payload["operation"] == "recovery_input":
            return {
                "run_id": "run-1",
                "work_file_ref": f"/work/js-analysis/run-1/{js_sha}.js",
                "sha256": js_sha,
                "size": len(js),
            }
        return {
            "lead_id": "lead_a",
            "total": 1,
            "next_cursor": None,
            "sources": [
                {
                    "source_id": "src_a",
                    "status": "pending",
                    "content_sha256": source_sha,
                    "size": len(source),
                    "work_file_ref": (
                        f"/work/js-analysis/run-1/recovered/{source_sha}.js"
                    ),
                }
            ],
        }

    class SlowResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            time.sleep(0.2)
            return b'{"status":"available"}'

    monkeypatch.setattr(cli, "_rpc", rpc)
    monkeypatch.setattr(
        cli,
        "_post_bytes",
        lambda *args, **kwargs: {
            "status": "complete",
            "map_id": "map_a",
            "source_count": 1,
            "deadline_s": 0.06,
            "gaps": [],
        },
    )
    monkeypatch.setattr(
        cli,
        "_get_bytes",
        lambda *args, **kwargs: (source, {}),
    )
    monkeypatch.setattr(
        cli,
        "urlopen",
        lambda request, timeout: (
            requested_urls.append(request.full_url) or SlowResponse()
        ),
    )

    result = cli._recover_lead(
        "http://agent:8080",
        "opaque",
        "lead_a",
        work_root=work_root,
    )

    assert result["status"] == "partial"
    assert result["available"] == 0
    assert result["failures"] == [
        "recovery_deadline",
        "confirmation_outcome_uncertain",
    ]
    assert result["remote_state_uncertain"] is True
    assert (
        work_root / "run-1" / "recovered" / f"{source_sha}.js"
    ).read_bytes() == source
    assert not any(url.endswith("/recovery/fail") for url in requested_urls)

    monkeypatch.setattr(
        cli,
        "_post_json",
        lambda *args, **kwargs: {"status": "available"},
    )
    resumed = cli._recover_lead(
        "http://agent:8080",
        "opaque",
        "lead_a",
        work_root=work_root,
    )
    assert resumed["status"] == "complete"
    assert resumed["skipped_existing"] == 1
