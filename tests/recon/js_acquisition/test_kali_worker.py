import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from polymerhus.recon.js_acquisition.kali_worker import acquire_lead_to_work_file


class _BrokerHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    body = b"export const acquired = 'safe-marker';\n"
    confirm_status = 200
    invalid_confirmation = False
    transfer_failure = False
    keep_work_file = False
    confirm_ack_lost = False
    post_unreachable = False
    fail_status = "failed"
    fail_reconcile_required = False
    confirm_requests: list[dict] = []
    fail_requests: list[dict] = []

    def do_GET(self):
        digest = hashlib.sha256(self.body).hexdigest()
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript")
        declared = len(self.body) + (10 if self.transfer_failure else 0)
        self.send_header("Content-Length", str(declared))
        self.send_header("X-JS-Run-Id", "run-1")
        self.send_header("X-JS-Size", str(len(self.body)))
        self.send_header("X-JS-SHA256", digest)
        self.send_header("X-JS-Content-Type", "application/javascript")
        self.send_header(
            "X-JS-Work-File-Ref", f"/work/js-analysis/run-1/{digest}.js"
        )
        self.end_headers()
        self.wfile.write(self.body if not self.transfer_failure else self.body[:5])
        self.close_connection = True

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        if type(self).post_unreachable:
            self.close_connection = True
            return
        if self.path.endswith("/confirm"):
            type(self).confirm_requests.append(payload)
            if type(self).confirm_ack_lost:
                self.close_connection = True
                return
            status = type(self).confirm_status
        else:
            type(self).fail_requests.append(payload)
            status = 200
        body = (
            json.dumps(
                {
                    "status": type(self).fail_status,
                    "keep_work_file": type(self).keep_work_file,
                    "reconcile_required": type(self).fail_reconcile_required,
                }
            ).encode()
            if self.path.endswith("/fail")
            else json.dumps({**payload, 'status': 'acquired'} if not type(self).invalid_confirmation else {}).encode()
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


@pytest.fixture
def broker():
    _BrokerHandler.confirm_status = 200
    _BrokerHandler.invalid_confirmation = False
    _BrokerHandler.transfer_failure = False
    _BrokerHandler.keep_work_file = False
    _BrokerHandler.confirm_ack_lost = False
    _BrokerHandler.post_unreachable = False
    _BrokerHandler.fail_status = "failed"
    _BrokerHandler.fail_reconcile_required = False
    _BrokerHandler.confirm_requests = []
    _BrokerHandler.fail_requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _BrokerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", _BrokerHandler
    server.shutdown()
    thread.join(timeout=2)
    server.server_close()


def test_empty_confirmation_is_not_acquired(tmp_path, broker):
    agent_url, handler = broker
    handler.invalid_confirmation = True
    result = acquire_lead_to_work_file(agent_url=agent_url, reference='ref', lead_id='lead-bad-ack', work_root=tmp_path)
    assert result['status'] != 'acquired'
    assert result['failure_reason'] == 'ack_failed'


def test_worker_writes_verified_bytes_atomically_and_confirms(
    tmp_path: Path, broker
) -> None:
    agent_url, handler = broker
    work_root = tmp_path / "work" / "js-analysis"

    result = acquire_lead_to_work_file(
        agent_url=agent_url,
        reference="opaque-reference",
        lead_id="lead-1",
        work_root=work_root,
    )

    digest = hashlib.sha256(handler.body).hexdigest()
    work_file = work_root / "run-1" / f"{digest}.js"
    assert work_file.read_bytes() == handler.body
    assert result == {
        "lead_id": "lead-1",
        "status": "acquired",
        "content_type": "application/javascript",
        "size": len(handler.body),
        "sha256": digest,
        "work_file_ref": f"/work/js-analysis/run-1/{digest}.js",
    }
    assert handler.confirm_requests == [
        {
            "lead_id": "lead-1",
            "size": len(handler.body),
            "sha256": digest,
            "work_file_ref": f"/work/js-analysis/run-1/{digest}.js",
        }
    ]
    assert not list(work_file.parent.glob("*.part"))
    rendered = repr(result)
    assert "safe-marker" not in rendered
    assert "opaque-reference" not in rendered


def test_worker_removes_partial_file_and_records_transfer_failure(
    tmp_path: Path, broker
) -> None:
    agent_url, handler = broker
    handler.transfer_failure = True
    work_root = tmp_path / "work" / "js-analysis"

    result = acquire_lead_to_work_file(
        agent_url=agent_url,
        reference="opaque-reference",
        lead_id="lead-transfer",
        work_root=work_root,
    )

    assert result["status"] == "failed"
    assert result["failure_reason"] == "transfer_failed"
    assert handler.fail_requests[-1]["failure_reason"] == "transfer_failed"
    assert not any((work_root / "run-1").glob("*.js"))
    assert not any((work_root / "run-1").glob("*.part"))


def test_worker_removes_file_when_ack_fails(tmp_path: Path, broker) -> None:
    agent_url, handler = broker
    handler.confirm_status = 500
    work_root = tmp_path / "work" / "js-analysis"

    result = acquire_lead_to_work_file(
        agent_url=agent_url,
        reference="opaque-reference",
        lead_id="lead-ack",
        work_root=work_root,
    )

    assert result["status"] == "failed"
    assert result["failure_reason"] == "ack_failed"
    assert handler.fail_requests[-1]["failure_reason"] == "ack_failed"
    assert not any((work_root / "run-1").glob("*.js"))


def test_worker_keeps_vendor_named_acquisition_without_retention_policy(
    tmp_path: Path, broker
) -> None:
    agent_url, handler = broker
    work_root = tmp_path / "work" / "js-analysis"

    result = acquire_lead_to_work_file(
        agent_url=agent_url,
        reference="opaque-reference",
        lead_id="lead-vendor",
        work_root=work_root,
    )

    digest = hashlib.sha256(handler.body).hexdigest()
    assert result["status"] == "acquired"
    assert (work_root / "run-1" / f"{digest}.js").is_file()


def test_ack_failure_keeps_file_still_owned_by_another_lead(
    tmp_path: Path, broker
) -> None:
    agent_url, handler = broker
    handler.confirm_status = 500
    handler.keep_work_file = True
    work_root = tmp_path / "work" / "js-analysis"

    result = acquire_lead_to_work_file(
        agent_url=agent_url,
        reference="opaque-reference",
        lead_id="lead-shared",
        work_root=work_root,
    )

    digest = hashlib.sha256(handler.body).hexdigest()
    assert result["status"] == "failed"
    assert result["failure_reason"] == "ack_failed"
    assert result["keep_work_file"] is True
    assert (work_root / "run-1" / f"{digest}.js").is_file()


def test_lost_confirm_response_keeps_file_and_marks_reconciliation(
    tmp_path: Path, broker
) -> None:
    agent_url, handler = broker
    handler.confirm_ack_lost = True
    handler.keep_work_file = True
    handler.fail_status = "acquired"
    handler.fail_reconcile_required = True
    work_root = tmp_path / "work" / "js-analysis"

    result = acquire_lead_to_work_file(
        agent_url=agent_url,
        reference="opaque-reference",
        lead_id="lead-lost-ack",
        work_root=work_root,
    )

    digest = hashlib.sha256(handler.body).hexdigest()
    assert result["status"] == "reconcile_required"
    assert result["failure_reason"] == "confirmation_ack_lost"
    assert result["keep_work_file"] is True
    assert (work_root / "run-1" / f"{digest}.js").is_file()


def test_confirm_and_fail_unreachable_conservatively_keep_shared_file(
    tmp_path: Path, broker
) -> None:
    agent_url, handler = broker
    handler.post_unreachable = True
    work_root = tmp_path / "work" / "js-analysis"

    result = acquire_lead_to_work_file(
        agent_url=agent_url,
        reference="opaque-reference",
        lead_id="lead-unresolved",
        work_root=work_root,
    )

    digest = hashlib.sha256(handler.body).hexdigest()
    assert result["status"] == "reconcile_required"
    assert result["failure_reason"] == "ack_unresolved"
    assert result["keep_work_file"] is True
    assert (work_root / "run-1" / f"{digest}.js").is_file()
    assert list((work_root / "run-1" / ".reconcile").glob("*.json"))
