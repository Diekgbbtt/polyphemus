import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import pytest

from polymerhus.app.data_root import ensure_project
from polymerhus.recon.domain.types import ExecResult
from polymerhus.recon.js_acquisition.manifest import AcquisitionManifest
from polymerhus.recon.js_acquisition.recovery import (
    InvalidMapDataURI,
    discover_source_map_link,
    decode_map_data_uri,
)
from polymerhus.recon.js_acquisition.service import (
    AcquisitionError,
    AcquisitionLimits,
    AcquisitionService,
)
from polymerhus.recon.js_intake import (
    JsIntakeReader,
    JsIntakeStore,
    issue_js_intake_reference,
)


def test_header_precedes_conflicting_annotation_and_conflict_is_recorded():
    link = discover_source_map_link(
        b"const app = 1;\n//# sourceMappingURL=annotation.map\n",
        final_url="https://app.example.test/assets/app.js?build=1",
        sourcemap_header="../maps/header.map?token=private",
    )

    assert link.kind == "header"
    assert link.url == "https://app.example.test/maps/header.map?token=private"
    assert link.annotation_url == (
        "https://app.example.test/assets/annotation.map"
    )
    assert link.conflict is True


def test_comment_looking_strings_and_templates_do_not_beat_real_annotation():
    source = (
        b"const one = '//# sourceMappingURL=string.map';\n"
        b"const two = `\n//# sourceMappingURL=template.map\n`;\n"
        b"//# sourceMappingURL=real.map\n"
    )

    link = discover_source_map_link(
        source,
        final_url="https://app.example.test/assets/app.js",
    )

    assert link.kind == "annotation"
    assert link.url == "https://app.example.test/assets/real.map"
    assert link.conflict is False


def test_block_comment_annotation_and_no_map_guessed_companion():
    css = b"body{}\n/*# sourceMappingURL=styles.css.map */\n"
    link = discover_source_map_link(
        css,
        final_url="https://app.example.test/assets/styles.css",
    )
    assert link.url == "https://app.example.test/assets/styles.css.map"
    assert link.kind == "annotation"

    guessed = discover_source_map_link(
        b"const app = 1;\n",
        final_url="https://app.example.test/assets/app.js?build=1",
    )
    assert guessed.kind == "guessed"
    assert guessed.url == "https://app.example.test/assets/app.js.map?build=1"


def test_base64_and_percent_encoded_map_data_uris_decode_exactly():
    map_bytes = json.dumps(
        {
            "version": 3,
            "sources": ["src/app.js"],
            "sourcesContent": ["export const app = 1;\n"],
            "names": [],
            "mappings": "",
        },
        separators=(",", ":"),
    ).encode()
    base64_uri = (
        "data:application/json;charset=utf-8;base64,"
        + base64.b64encode(map_bytes).decode()
    )
    percent_uri = (
        "data:application/json;charset=utf-8,"
        + quote(map_bytes.decode(), safe="")
    )

    assert decode_map_data_uri(base64_uri, max_bytes=4096) == map_bytes
    assert decode_map_data_uri(percent_uri, max_bytes=4096) == map_bytes
    with pytest.raises(InvalidMapDataURI):
        decode_map_data_uri(percent_uri, max_bytes=10)


class _MapHandler(BaseHTTPRequestHandler):
    sourcemap_header = "../maps/header.map?token=private"
    auth_headers = []

    def do_GET(self):
        if self.path == "/app.js":
            body = b"const app = 1;\n"
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("SourceMap", self.sourcemap_header)
        elif self.path == "/maps/header.map?token=private":
            body = json.dumps(
                {
                    "version": 3,
                    "sources": ["src/app.js"],
                    "sourcesContent": ["export const app = 1;\n"],
                    "names": [],
                    "mappings": "",
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        elif self.path == "/redirect.map":
            self.send_response(302)
            self.send_header("Location", "/maps/final.map?token=keep")
            body = b""
        elif self.path == "/maps/final.map?token=keep":
            self.auth_headers.append(self.headers.get("Authorization"))
            body = b'{"version":3,"sourceRoot":"src","sources":["app.js"],"sourcesContent":["final\\n"],"names":[],"mappings":""}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        elif self.path == "/html.map":
            body = b"<html>login</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
        elif self.path == "/sources/missing.ts":
            self.auth_headers.append(self.headers.get("Authorization"))
            body = b"export const missing = true;\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
        elif self.path == "/unauth.map":
            body = b"unauthorized"
            self.send_response(401)
            self.send_header("Content-Type", "text/plain")
        else:
            body = b""
            self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


def _acquired_lead(root: Path, base: str):
    ensure_project("proj-1", root=root)
    intake = JsIntakeStore(root=root)
    intake.record_exec_result(
        project_id="proj-1",
        run_id="run-1",
        pod_id="pod-1",
        producer="katana",
        input_context_ref="ctx",
        exec_result=ExecResult(
            stdout=json.dumps({"request": {"endpoint": base + "/app.js"}}),
            stderr="",
            returncode=0,
        ),
        auth_context_label="authenticated",
        auth_context_ref="account-1",
    )
    reference = issue_js_intake_reference(
        "proj-1",
        "run-1",
        context_ref="account-1",
        scope_domains=["127.0.0.1"],
    )
    lead_id = JsIntakeReader(root=root).list(
        reference=reference, limit=1
    )["leads"][0]["lead_id"]
    manifest = AcquisitionManifest(
        project_id="proj-1",
        run_id="run-1",
        root=root,
        max_run_bytes=1024 * 1024,
    )
    work_ref = "/work/js-analysis/run-1/" + "a" * 64 + ".js"
    assert manifest.reserve(
        lead_id=lead_id,
        record={"context_ref": "account-1"},
        work_file_ref=work_ref,
        sha256="a" * 64,
        size=16,
    )
    assert manifest.confirm(
        lead_id=lead_id,
        size=16,
        sha256="a" * 64,
        work_file_ref=work_ref,
    ) == "acquired"
    return lead_id, reference


def _record_only_lead(root: Path, url: str):
    ensure_project("proj-1", root=root)
    intake = JsIntakeStore(root=root)
    intake.record_exec_result(
        project_id="proj-1",
        run_id="run-1",
        pod_id="pod-1",
        producer="katana",
        input_context_ref="ctx",
        exec_result=ExecResult(
            stdout=json.dumps({"request": {"endpoint": url}}),
            stderr="",
            returncode=0,
        ),
        auth_context_label="authenticated",
        auth_context_ref="account-1",
    )
    reference = issue_js_intake_reference(
        "proj-1",
        "run-1",
        context_ref="account-1",
        scope_domains=["127.0.0.1"],
    )
    lead_id = JsIntakeReader(root=root).list(
        reference=reference, limit=1
    )["leads"][0]["lead_id"]
    return lead_id, reference


def test_new_js_acquisition_keeps_sourcemap_header_private(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MapHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        root = tmp_path / "data"
        lead_id, reference = _record_only_lead(root, base + "/app.js")
        service = AcquisitionService(
            root=root,
            work_root=tmp_path / "work",
            auth_headers_for=lambda project, context: {
                "Authorization": "Bearer fixture"
            },
        )
        service.fetch(reference=reference, lead_id=lead_id)
        record = (
            service._manifest("proj-1", "run-1")
            .get()["leads"][lead_id]
        )
    finally:
        server.shutdown()
        server.server_close()

    assert record["sourcemap_header"] == (
        "../maps/header.map?token=private"
    )
    assert record["x_sourcemap_header"] is None


def test_authorized_map_fetch_preserves_final_url_and_credentials(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MapHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        lead_id, reference = _acquired_lead(tmp_path / "data", base)
        service = AcquisitionService(
            root=tmp_path / "data",
            work_root=tmp_path / "work",
            limits=AcquisitionLimits(max_file_bytes=4096),
            auth_headers_for=lambda project, context: {
                "Authorization": "Bearer fixture"
            },
        )

        fetched = service.fetch_map(
            reference=reference,
            lead_id=lead_id,
            map_url=base + "/redirect.map",
            max_bytes=1024,
        )
        source = service.fetch_missing_source(
            reference=reference,
            lead_id=lead_id,
            source_url=base + "/sources/missing.ts",
            max_bytes=1024,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert fetched.final_url == base + "/maps/final.map?token=keep"
    assert fetched.body.startswith(b'{"version":3')
    assert _MapHandler.auth_headers[-1] == "Bearer fixture"
    assert source.body == b"export const missing = true;\n"
    from polymerhus.recon.js_acquisition.recovery import parse_map_bytes

    parsed = parse_map_bytes(
        fetched.body,
        map_url=fetched.final_url,
    )
    assert parsed.occurrences[0].resolved_source == (
        base + "/maps/src/app.js"
    )


@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("/unauth.map", "http_status_401"),
        ("/html.map", "non_json_map_response"),
    ],
)
def test_map_fetch_failures_are_distinct(tmp_path, path, reason):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MapHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        lead_id, reference = _acquired_lead(tmp_path / "data", base)
        service = AcquisitionService(
            root=tmp_path / "data",
            auth_headers_for=lambda project, context: {
                "Authorization": "Bearer fixture"
            },
        )
        with pytest.raises(AcquisitionError) as exc:
            service.fetch_map(
                reference=reference,
                lead_id=lead_id,
                map_url=base + path,
                max_bytes=1024,
            )
    finally:
        server.shutdown()
        server.server_close()
    assert exc.value.reason == reason
