import json
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from polymerhus.app.auth.store import AuthStore
from polymerhus.app.data_root import ensure_project
from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_acquisition import (
    AcquisitionError,
    AcquisitionLimits,
    AcquisitionResult,
    AcquisitionService,
)
from polymerhus.recon.js_intake import (
    InvalidJsIntakeReference,
    JsIntakeLeadNotFound,
    JsIntakeStore,
    issue_js_intake_reference,
)


class _FixtureHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    echo_cookie: str | None = None

    def do_GET(self):
        if self.path.startswith("/public.js"):
            body = b"export const answer = 42;\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/body-a.js"):
            body = b"export const bodyA = 'aaaaaaaaaaaaaaaa';\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/body-b.js"):
            body = b"export const bodyB = 'bbbbbbbbbbbbbbbb';\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/protected.js"):
            if "fixture=secret-cookie" not in (self.headers.get("Cookie") or ""):
                body = b"unauthorized"
                self.send_response(401)
                self.send_header("Content-Type", "text/plain")
            else:
                body = b"window.protectedValue = true;\n"
                self.send_response(200)
                self.send_header("Content-Type", "text/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/status401.js"):
            body = b"not authorized"
            self.send_response(401)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/fallback.js"):
            body = b"<!doctype html><html>login</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/redirect-outside.js"):
            self.send_response(302)
            self.send_header("Location", "http://outside.invalid/escape.js")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/redirect-protected.js"):
            self.send_response(302)
            self.send_header("Location", "/protected.js")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/redirect-cross-origin.js"):
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://localhost:{self.server.server_port}/echo-cookie.js",
            )
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/echo-cookie.js"):
            type(self).echo_cookie = self.headers.get("Cookie")
            body = b"window.crossOrigin = true;\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/large.js"):
            body = b"x" * 2048
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt, *args):
        pass


@pytest.fixture
def http_fixture():
    servers = []
    _FixtureHandler.echo_cookie = None

    def start():
        server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return f"http://127.0.0.1:{server.server_port}"

    yield start
    for server, thread in servers:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def _record_lead(
    root: Path,
    url: str,
    *,
    context_ref: str = "",
    producer: str = "steel_crawl",
) -> str:
    return _record_leads(
        root,
        [url],
        context_ref=context_ref,
        producer=producer,
    )[0]


def _record_leads(
    root: Path,
    urls: list[str],
    *,
    context_ref: str = "",
    producer: str = "steel_crawl",
) -> list[str]:
    store = JsIntakeStore(root=root)
    common = {
        "project_id": "proj-1",
        "run_id": "run-1",
        "pod_id": "pod-1",
        "producer": producer,
        "input_context_ref": "ctx-1",
        "auth_context_label": "authenticated" if context_ref else "anonymous",
        "auth_context_ref": context_ref or None,
    }
    if producer == "katana":
        stdout = "\n".join(
            json.dumps(
                {
                    "request": {"endpoint": url, "method": "GET"},
                    "response": {
                        "status_code": 200,
                        "headers": {"Content-Type": "application/javascript"},
                    },
                }
            )
            for url in urls
        )
        store.record_exec_result(
            **common,
            exec_result=ExecResult(stdout=stdout, stderr="", returncode=0),
        )
    else:
        store.record_manifest(
            **common,
            manifest={"endpoints": [], "js_urls": urls},
            terminal_result="success",
            output_completeness="complete",
        )
    path = root / "proj-1" / "recon" / "js-intake" / "run-1" / "pod-1.jsonl"
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").split("\n")
        if line
    ]
    return [record["lead_id"] for record in records[1:]]


def test_missing_authenticated_context_never_falls_back_to_anonymous(tmp_path, monkeypatch):
    lead_id = _record_lead(tmp_path, 'http://example.com/app.js', producer='katana')
    path = tmp_path / 'proj-1/recon/js-intake/run-1/pod-1.jsonl'
    records = [json.loads(row) for row in path.read_text().splitlines()]
    for row in records:
        row['auth_context_label'] = 'authenticated'
    path.write_text('\n'.join(json.dumps(row) for row in records) + '\n')
    service = AcquisitionService(root=tmp_path)
    def forbidden_network(*args, **kwargs):
        pytest.fail('missing context must not reach the network')
    monkeypatch.setattr('polymerhus.recon.js_acquisition.service.httpx.Client', forbidden_network)
    with pytest.raises(AcquisitionError, match='auth_context_missing'):
        service.fetch(reference=issue_js_intake_reference('proj-1', 'run-1', scope_domains=['example.com']), lead_id=lead_id)


def test_public_js_fetch_is_recorded_as_pending_until_kali_confirmation(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    url = f"{http_fixture()}/public.js?cache=public"
    lead_id = _record_lead(root, url)
    reference = issue_js_intake_reference(
        "proj-1", "run-1", scope_domains=["127.0.0.1"]
    )
    service = AcquisitionService(
        root=root,
        work_root=tmp_path / "work",
        limits=AcquisitionLimits(
            max_file_bytes=1024,
            max_run_bytes=4096,
            max_redirects=3,
            timeout_s=5,
        ),
    )

    result = service.fetch(reference=reference, lead_id=lead_id)

    assert result.body == b"export const answer = 42;\n"
    assert result.status_code == 200
    assert result.content_type == "application/javascript"
    assert result.size == 26
    assert result.sha256 == (
        "a2098bd92b10bf8b816d24b7556b1ce8c49a879d130489065ef1051c17e042f6"
    )
    public = result.public_metadata()
    assert public == {
        "lead_id": lead_id,
        "status": "fetched_pending_work_file",
        "content_type": "application/javascript",
        "size": 26,
        "sha256": result.sha256,
        "work_file_ref": f"/work/js-analysis/run-1/{result.sha256}.js",
    }
    assert "public" not in repr(public)

    manifest_path = (
        root
        / "proj-1"
        / "recon"
        / "js_analysis"
        / "run-1"
        / "manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    record = manifest["leads"][lead_id]
    assert record["status"] == "fetched_pending_work_file"
    assert record["final_url"] == url
    assert record["size"] == 26
    assert record["sha256"] == result.sha256


def test_protected_js_uses_private_context_and_hides_credentials(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    url = f"{http_fixture()}/protected.js?token=private-token"
    AuthStore(root_dir=root).replace_operator_state(
        "proj-1",
        overview={"login_endpoint": "https://example.test/login"},
        accounts={
            "account-1": {
                "credentials": {
                    "username": "fixture",
                    "password": "fixture-password",
                    "login_url": "https://example.test/login",
                },
                "snapshot": {
                    "cookies": [
                        {
                            "name": "fixture",
                            "value": "secret-cookie",
                            "domain": "127.0.0.1",
                            "path": "/",
                        }
                    ]
                },
            }
        },
    )
    lead_id = _record_lead(
        root, url, context_ref="account-1", producer="katana"
    )
    reference = issue_js_intake_reference(
        "proj-1",
        "run-1",
        context_ref="account-1",
        scope_domains=["127.0.0.1"],
    )
    service = AcquisitionService(
        root=root,
        work_root=tmp_path / "work",
        limits=AcquisitionLimits(max_file_bytes=1024, max_run_bytes=4096),
    )

    result = service.fetch(reference=reference, lead_id=lead_id)

    assert result.body == b"window.protectedValue = true;\n"
    rendered = repr(result.public_metadata())
    assert "private-token" not in rendered
    assert "secret-cookie" not in rendered
    assert "protected.js" not in rendered
    manifest = json.loads(
        (
            root
            / "proj-1"
            / "recon"
            / "js_analysis"
            / "run-1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    record = manifest["leads"][lead_id]
    assert record["auth_state_source"] == "auth_store_request_material"
    assert record["auth_state_equivalent"] is True


def test_expired_and_other_context_references_cannot_fetch(
    tmp_path: Path, http_fixture, monkeypatch
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    url = f"{http_fixture()}/public.js"
    lead_id = _record_lead(root, url)
    service = AcquisitionService(root=root, work_root=tmp_path / "work")
    clock = [1000.0]
    monkeypatch.setattr(
        "polymerhus.recon.js_intake.reader.time.monotonic", lambda: clock[0]
    )
    expired_reference = issue_js_intake_reference("proj-1", "run-1", ttl_s=1)
    clock[0] = 1002.0
    with pytest.raises(InvalidJsIntakeReference):
        service.fetch(reference=expired_reference, lead_id=lead_id)

    other_context = issue_js_intake_reference(
        "proj-1", "run-1", context_ref="other-context"
    )
    with pytest.raises(JsIntakeLeadNotFound):
        service.fetch(reference=other_context, lead_id=lead_id)


def test_missing_auth_material_is_a_gap_not_an_anonymous_fallback(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    url = f"{http_fixture()}/protected.js?token=private-token"
    lead_id = _record_lead(
        root, url, context_ref="missing-account", producer="katana"
    )
    reference = issue_js_intake_reference(
        "proj-1",
        "run-1",
        context_ref="missing-account",
        scope_domains=["127.0.0.1"],
    )
    service = AcquisitionService(root=root, work_root=tmp_path / "work")

    with pytest.raises(AcquisitionError) as exc:
        service.fetch(reference=reference, lead_id=lead_id)

    assert exc.value.reason == "auth_context_unavailable"
    manifest = json.loads(
        (
            root
            / "proj-1"
            / "recon"
            / "js_analysis"
            / "run-1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    record = manifest["leads"][lead_id]
    assert record["status"] == "failed"
    assert record["auth_state_equivalent"] is False
    assert record["auth_gap"] == "auth_context_unavailable"


def test_browser_requested_auth_lead_reports_unsynced_session_gap(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    AuthStore(root_dir=root).replace_operator_state(
        "proj-1",
        accounts={
            "account-1": {
                "snapshot": {
                    "cookies": [
                        {
                            "name": "fixture",
                            "value": "secret-cookie",
                            "domain": "127.0.0.1",
                            "path": "/",
                        }
                    ]
                }
            }
        },
    )
    lead_id = _record_lead(
        root,
        f"{http_fixture()}/protected.js",
        context_ref="account-1",
        producer="steel_crawl",
    )
    reference = issue_js_intake_reference(
        "proj-1",
        "run-1",
        context_ref="account-1",
        scope_domains=["127.0.0.1"],
    )
    service = AcquisitionService(root=root, work_root=tmp_path / "work")

    with pytest.raises(AcquisitionError) as exc:
        service.fetch(reference=reference, lead_id=lead_id)

    assert exc.value.reason == "browser_auth_state_not_captured"
    manifest = json.loads(
        (
            root
            / "proj-1"
            / "recon"
            / "js_analysis"
            / "run-1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    record = manifest["leads"][lead_id]
    assert record["auth_state_source"] == "unavailable"
    assert record["auth_state_equivalent"] is False
    assert record["auth_gap"] == "browser_session_updates_not_synced"


@pytest.mark.parametrize("script_path", ["protected.js", "module?id=42"])
def test_authenticated_debugger_script_never_falls_back_to_http(
    tmp_path: Path,
    monkeypatch,
    script_path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    url = f"http://127.0.0.1:9/{script_path}"
    AuthStore(root_dir=root).replace_operator_state(
        "proj-1",
        accounts={
            "account-1": {
                "snapshot": {
                    "cookies": [
                        {
                            "name": "fixture",
                            "value": "secret-cookie",
                            "domain": "127.0.0.1",
                            "path": "/",
                        }
                    ]
                }
            }
        },
    )
    JsIntakeStore(root=root).record_manifest(
        project_id="proj-1",
        run_id="run-1",
        pod_id="steel-session",
        producer="steel_crawl",
        input_context_ref="ctx-1",
        auth_context_label="authenticated",
        auth_context_ref="account-1",
        manifest={
            "schema_version": "steel-crawl/v2",
            "run": {"session_name": "steel-session", "account": "account-1"},
            "endpoints": [],
            "parameters": [],
            "scripts": [
                {
                    "script_id": "script-1",
                    "script_url": url,
                    "source_url": url,
                }
            ],
            "realtime": [],
            "errors": [],
            "stats": {"flows": 0},
        },
        terminal_result="success",
        output_completeness="complete",
    )
    path = (
        root
        / "proj-1"
        / "recon"
        / "js-intake"
        / "run-1"
        / "steel-session.jsonl"
    )
    lead_id = json.loads(
        path.read_text(encoding="utf-8").splitlines()[1]
    )["lead_id"]
    reference = issue_js_intake_reference(
        "proj-1",
        "run-1",
        context_ref="account-1",
        scope_domains=["127.0.0.1"],
    )
    service = AcquisitionService(root=root, work_root=tmp_path / "work")

    def forbidden_network(*args, **kwargs):
        pytest.fail("a debugger observation must not trigger an HTTP replay")

    monkeypatch.setattr(
        "polymerhus.recon.js_acquisition.service.httpx.Client",
        forbidden_network,
    )
    with pytest.raises(AcquisitionError) as exc:
        service.fetch(reference=reference, lead_id=lead_id)

    assert exc.value.reason == "browser_auth_state_not_captured"
    manifest = json.loads(
        (
            root
            / "proj-1"
            / "recon"
            / "js_analysis"
            / "run-1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["leads"][lead_id]["failure_reason"] == (
        "browser_auth_state_not_captured"
    )


@pytest.mark.parametrize(
    ("path", "reason", "status_code"),
    [
        ("/status401.js", "http_status_401", 401),
        ("/fallback.js", "non_js_content_type", 200),
    ],
)
def test_http_and_html_failures_are_explicit(
    tmp_path: Path, http_fixture, path: str, reason: str, status_code: int
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    url = f"{http_fixture()}{path}"
    lead_id = _record_lead(root, url)
    reference = issue_js_intake_reference(
        "proj-1", "run-1", scope_domains=["127.0.0.1"]
    )
    service = AcquisitionService(root=root, work_root=tmp_path / "work")

    with pytest.raises(AcquisitionError) as exc:
        service.fetch(reference=reference, lead_id=lead_id)

    assert exc.value.reason == reason
    assert exc.value.status_code == status_code
    manifest = json.loads(
        (
            root
            / "proj-1"
            / "recon"
            / "js_analysis"
            / "run-1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    record = manifest["leads"][lead_id]
    assert record["status"] == "failed"
    assert record["failure_reason"] == reason


def test_redirect_outside_scope_fails_without_following(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    url = f"{http_fixture()}/redirect-outside.js"
    lead_id = _record_lead(root, url)
    reference = issue_js_intake_reference(
        "proj-1", "run-1", scope_domains=["127.0.0.1"]
    )
    service = AcquisitionService(root=root, work_root=tmp_path / "work")

    with pytest.raises(AcquisitionError) as exc:
        service.fetch(reference=reference, lead_id=lead_id)

    assert exc.value.reason == "redirect_out_of_scope"


def test_redirect_keeps_auth_only_for_same_origin(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    AuthStore(root_dir=root).replace_operator_state(
        "proj-1",
        accounts={
            "account-1": {
                "credentials": {
                    "username": "fixture",
                    "password": "fixture-password",
                    "login_url": "https://example.test/login",
                },
                "snapshot": {
                    "cookies": [
                        {
                            "name": "fixture",
                            "value": "secret-cookie",
                            "domain": "127.0.0.1",
                            "path": "/",
                        }
                    ]
                },
            }
        },
    )
    base = http_fixture()
    same_origin_id, cross_origin_id = _record_leads(
        root,
        [
            f"{base}/redirect-protected.js",
            f"{base}/redirect-cross-origin.js",
        ],
        context_ref="account-1",
        producer="katana",
    )
    reference = issue_js_intake_reference(
        "proj-1",
        "run-1",
        context_ref="account-1",
        scope_domains=["127.0.0.1", "localhost"],
    )
    service = AcquisitionService(root=root, work_root=tmp_path / "work")

    same_origin = service.fetch(reference=reference, lead_id=same_origin_id)
    assert same_origin.body == b"window.protectedValue = true;\n"

    cross_origin = service.fetch(reference=reference, lead_id=cross_origin_id)
    assert cross_origin.body == b"window.crossOrigin = true;\n"
    assert _FixtureHandler.echo_cookie is None


def test_third_party_lead_never_receives_target_credentials(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    AuthStore(root_dir=root).replace_operator_state(
        "proj-1",
        accounts={
            "account-1": {
                "snapshot": {
                    "cookies": [
                        {
                            "name": "fixture",
                            "value": "secret-cookie",
                            "domain": "127.0.0.1",
                            "path": "/",
                        }
                    ]
                }
            }
        },
    )
    base = http_fixture()
    third_party = base.replace("127.0.0.1", "localhost")
    lead_id = _record_lead(
        root,
        f"{third_party}/echo-cookie.js",
        context_ref="account-1",
        producer="katana",
    )
    reference = issue_js_intake_reference(
        "proj-1",
        "run-1",
        context_ref="account-1",
        scope_domains=["target.example"],
    )
    service = AcquisitionService(root=root, work_root=tmp_path / "work")

    result = service.fetch(reference=reference, lead_id=lead_id)

    assert result.status_code == 200
    assert _FixtureHandler.echo_cookie is None


def test_too_large_file_and_exhausted_temporary_quota_are_distinct(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    base = http_fixture()
    large_id = _record_lead(root, f"{base}/large.js")
    large_reference = issue_js_intake_reference(
        "proj-1", "run-1", scope_domains=["127.0.0.1"]
    )
    large_service = AcquisitionService(
        root=root,
        work_root=tmp_path / "work-large",
        limits=AcquisitionLimits(max_file_bytes=100, max_run_bytes=4096),
    )
    with pytest.raises(AcquisitionError) as large_exc:
        large_service.fetch(reference=large_reference, lead_id=large_id)
    assert large_exc.value.reason == "file_too_large"

    quota_root = tmp_path / "data-quota"
    ensure_project("proj-1", root=quota_root)
    first_id, second_id = _record_leads(
        quota_root,
        [f"{base}/body-a.js?first=1", f"{base}/body-b.js?second=2"],
    )
    quota_reference = issue_js_intake_reference(
        "proj-1", "run-1", scope_domains=["127.0.0.1"]
    )
    quota_service = AcquisitionService(
        root=quota_root,
        work_root=tmp_path / "work-quota",
        limits=AcquisitionLimits(max_file_bytes=100, max_run_bytes=50),
    )
    quota_service.fetch(reference=quota_reference, lead_id=first_id)
    with pytest.raises(AcquisitionError) as quota_exc:
        quota_service.fetch(reference=quota_reference, lead_id=second_id)
    assert quota_exc.value.reason == "quota_exhausted"


def test_manifest_becomes_acquired_only_after_matching_confirmation(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    lead_id = _record_lead(root, f"{http_fixture()}/public.js")
    reference = issue_js_intake_reference(
        "proj-1", "run-1", scope_domains=["127.0.0.1"]
    )
    service = AcquisitionService(root=root, work_root=tmp_path / "work")
    result = service.fetch(reference=reference, lead_id=lead_id)

    confirmed = service.confirm(
        reference=reference,
        lead_id=lead_id,
        size=result.size,
        sha256=result.sha256,
        work_file_ref=result.work_file_ref,
    )

    assert confirmed["status"] == "acquired"
    manifest = json.loads(
        (
            root
            / "proj-1"
            / "recon"
            / "js_analysis"
            / "run-1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    record = manifest["leads"][lead_id]
    assert record["status"] == "acquired"
    assert record["available"] is True
    assert manifest["temporary"]["used_bytes"] == result.size


def test_ack_failure_is_explicit_and_releases_temporary_quota(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    lead_id = _record_lead(root, f"{http_fixture()}/public.js")
    reference = issue_js_intake_reference(
        "proj-1", "run-1", scope_domains=["127.0.0.1"]
    )
    service = AcquisitionService(root=root, work_root=tmp_path / "work")
    service.fetch(reference=reference, lead_id=lead_id)

    failed = service.fail(
        reference=reference,
        lead_id=lead_id,
        failure_reason="ack_failed",
    )

    assert failed["status"] == "failed"
    assert failed["failure_reason"] == "ack_failed"
    manifest = json.loads(
        (
            root
            / "proj-1"
            / "recon"
            / "js_analysis"
            / "run-1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    record = manifest["leads"][lead_id]
    assert record["status"] == "failed"
    assert record["available"] is False
    assert manifest["temporary"]["used_bytes"] == 0


def test_concurrent_fetches_cannot_over_reserve_the_same_run_quota(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    base = http_fixture()
    first_id, second_id = _record_leads(
        root,
        [f"{base}/body-a.js?lead=1", f"{base}/body-b.js?lead=2"],
        producer="katana",
    )
    reference = issue_js_intake_reference(
        "proj-1", "run-1", scope_domains=["127.0.0.1"]
    )
    service = AcquisitionService(
        root=root,
        work_root=tmp_path / "work",
        limits=AcquisitionLimits(max_file_bytes=1024, max_run_bytes=50),
    )

    def fetch(lead_id: str):
        try:
            return service.fetch(reference=reference, lead_id=lead_id)
        except AcquisitionError as exc:
            return exc.reason

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(fetch, [first_id, second_id]))

    assert sum(isinstance(item, AcquisitionResult) for item in outcomes) == 1
    assert sum(item == "quota_exhausted" for item in outcomes) == 1
    manifest = json.loads(
        (
            root
            / "proj-1"
            / "recon"
            / "js_analysis"
            / "run-1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    active = [
        record
        for record in manifest["leads"].values()
        if record["status"] == "fetched_pending_work_file"
    ]
    assert len(active) == 1
    assert manifest["temporary"]["used_bytes"] == active[0]["size"]


def test_shared_hash_counts_once_and_survives_second_confirmation_failure(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    base = http_fixture()
    first_id, second_id = _record_leads(
        root,
        [f"{base}/public.js?lead=1", f"{base}/public.js?lead=2"],
        producer="katana",
    )
    reference = issue_js_intake_reference(
        "proj-1", "run-1", scope_domains=["127.0.0.1"]
    )
    service = AcquisitionService(
        root=root,
        work_root=tmp_path / "work",
        limits=AcquisitionLimits(max_file_bytes=1024, max_run_bytes=30),
    )

    first = service.fetch(reference=reference, lead_id=first_id)
    second = service.fetch(reference=reference, lead_id=second_id)
    assert first.sha256 == second.sha256
    assert first.work_file_ref == second.work_file_ref
    service.confirm(
        reference=reference,
        lead_id=first_id,
        size=first.size,
        sha256=first.sha256,
        work_file_ref=first.work_file_ref,
    )

    failed = service.fail(
        reference=reference,
        lead_id=second_id,
        failure_reason="ack_failed",
    )

    assert failed["keep_work_file"] is True
    manifest = json.loads(
        (
            root
            / "proj-1"
            / "recon"
            / "js_analysis"
            / "run-1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["leads"][first_id]["status"] == "acquired"
    assert manifest["leads"][second_id]["status"] == "failed"
    assert manifest["temporary"]["used_bytes"] == first.size


def test_retry_after_failure_releases_and_reacquires_quota(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    lead_id = _record_lead(root, f"{http_fixture()}/public.js")
    reference = issue_js_intake_reference(
        "proj-1", "run-1", scope_domains=["127.0.0.1"]
    )
    service = AcquisitionService(
        root=root,
        work_root=tmp_path / "work",
        limits=AcquisitionLimits(max_file_bytes=1024, max_run_bytes=30),
    )

    first = service.fetch(reference=reference, lead_id=lead_id)
    service.fail(
        reference=reference,
        lead_id=lead_id,
        failure_reason="transfer_failed",
    )
    retry = service.fetch(reference=reference, lead_id=lead_id)
    service.confirm(
        reference=reference,
        lead_id=lead_id,
        size=retry.size,
        sha256=retry.sha256,
        work_file_ref=retry.work_file_ref,
    )

    manifest = json.loads(
        (
            root
            / "proj-1"
            / "recon"
            / "js_analysis"
            / "run-1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert first.sha256 == retry.sha256
    assert manifest["leads"][lead_id]["status"] == "acquired"
    assert manifest["temporary"]["used_bytes"] == retry.size


def test_late_failure_ack_does_not_invalidate_already_confirmed_lead(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    lead_id = _record_lead(root, f"{http_fixture()}/public.js")
    reference = issue_js_intake_reference(
        "proj-1", "run-1", scope_domains=["127.0.0.1"]
    )
    service = AcquisitionService(root=root, work_root=tmp_path / "work")
    fetched = service.fetch(reference=reference, lead_id=lead_id)
    service.confirm(
        reference=reference,
        lead_id=lead_id,
        size=fetched.size,
        sha256=fetched.sha256,
        work_file_ref=fetched.work_file_ref,
    )

    late_failure = service.fail(
        reference=reference,
        lead_id=lead_id,
        failure_reason="ack_failed",
    )

    assert late_failure["keep_work_file"] is True
    manifest = json.loads(
        (
            root
            / "proj-1"
            / "recon"
            / "js_analysis"
            / "run-1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["leads"][lead_id]["status"] == "acquired"
    assert manifest["temporary"]["used_bytes"] == fetched.size


def test_repeated_identical_confirmation_is_idempotent(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    lead_id = _record_lead(root, f"{http_fixture()}/public.js")
    reference = issue_js_intake_reference(
        "proj-1", "run-1", scope_domains=["127.0.0.1"]
    )
    service = AcquisitionService(root=root, work_root=tmp_path / "work")
    fetched = service.fetch(reference=reference, lead_id=lead_id)
    first = service.confirm(
        reference=reference,
        lead_id=lead_id,
        size=fetched.size,
        sha256=fetched.sha256,
        work_file_ref=fetched.work_file_ref,
    )
    second = service.confirm(
        reference=reference,
        lead_id=lead_id,
        size=fetched.size,
        sha256=fetched.sha256,
        work_file_ref=fetched.work_file_ref,
    )

    assert first["status"] == "acquired"
    assert second["status"] == "acquired"
    assert second["idempotent"] is True


def test_different_confirmation_after_acquired_cannot_downgrade(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    lead_id = _record_lead(root, f"{http_fixture()}/public.js")
    reference = issue_js_intake_reference(
        "proj-1", "run-1", scope_domains=["127.0.0.1"]
    )
    service = AcquisitionService(root=root, work_root=tmp_path / "work")
    fetched = service.fetch(reference=reference, lead_id=lead_id)
    service.confirm(
        reference=reference,
        lead_id=lead_id,
        size=fetched.size,
        sha256=fetched.sha256,
        work_file_ref=fetched.work_file_ref,
    )

    with pytest.raises(AcquisitionError) as exc:
        service.confirm(
            reference=reference,
            lead_id=lead_id,
            size=fetched.size + 1,
            sha256="0" * 64,
            work_file_ref="/work/js-analysis/run-1/wrong.js",
        )

    assert exc.value.reason == "confirmation_mismatch"
    manifest = json.loads(
        (
            root
            / "proj-1"
            / "recon"
            / "js_analysis"
            / "run-1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["leads"][lead_id]["status"] == "acquired"
    assert manifest["leads"][lead_id]["sha256"] == fetched.sha256


def test_confirm_fail_race_keeps_one_consistent_terminal_state(
    tmp_path: Path, http_fixture
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    lead_id = _record_lead(root, f"{http_fixture()}/public.js")
    reference = issue_js_intake_reference(
        "proj-1", "run-1", scope_domains=["127.0.0.1"]
    )
    first_service = AcquisitionService(root=root, work_root=tmp_path / "work")
    second_service = AcquisitionService(root=root, work_root=tmp_path / "work")
    fetched = first_service.fetch(reference=reference, lead_id=lead_id)

    def confirm():
        try:
            return first_service.confirm(
                reference=reference,
                lead_id=lead_id,
                size=fetched.size,
                sha256=fetched.sha256,
                work_file_ref=fetched.work_file_ref,
            )
        except AcquisitionError as exc:
            return exc.reason

    def fail():
        return second_service.fail(
            reference=reference,
            lead_id=lead_id,
            failure_reason="ack_failed",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        confirm_future = pool.submit(confirm)
        fail_future = pool.submit(fail)
        confirm_result = confirm_future.result()
        fail_result = fail_future.result()

    manifest = json.loads(
        (
            root
            / "proj-1"
            / "recon"
            / "js_analysis"
            / "run-1"
            / "manifest.json"
        ).read_text(encoding="utf-8")
    )
    status = manifest["leads"][lead_id]["status"]
    assert status in {"acquired", "failed"}
    if status == "acquired":
        assert confirm_result["status"] == "acquired"
        assert fail_result["keep_work_file"] is True
        assert manifest["temporary"]["used_bytes"] == fetched.size
    else:
        assert confirm_result == "confirmation_mismatch"
        assert fail_result["keep_work_file"] is False
        assert manifest["temporary"]["used_bytes"] == 0
