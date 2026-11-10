import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from polymerhus.recon.scripts.jsluice_scan import (
    JsluiceProcessResult,
    run_bounded_process,
)


def _source(tmp_path: Path, body: bytes) -> tuple[Path, str]:
    path = tmp_path / "source.js"
    path.write_bytes(body)
    return path, hashlib.sha256(body).hexdigest()


def _executor(outputs: dict[str, JsluiceProcessResult]):
    def run(mode, _path, *, timeout_s, max_output_bytes, executable):
        assert timeout_s > 0
        assert max_output_bytes > 0
        assert executable
        return outputs[mode]

    return run


def test_scan_worker_rejects_missing_size_mismatch_and_hash_mismatch(tmp_path):
    from polymerhus.recon.js_acquisition.scan_worker import scan_local_file

    path, digest = _source(tmp_path, b"const ok = true;\n")
    missing = scan_local_file(
        tmp_path / "missing.js",
        expected_sha256=digest,
        expected_size=17,
    )
    wrong_size = scan_local_file(
        path,
        expected_sha256=digest,
        expected_size=16,
    )
    wrong_hash = scan_local_file(
        path,
        expected_sha256="0" * 64,
        expected_size=17,
    )

    assert missing["status"] == "failed"
    assert missing["error"] == "source_missing"
    assert wrong_size["error"] == "source_size_mismatch"
    assert wrong_hash["error"] == "source_hash_mismatch"
    assert wrong_size["modes"] == {}


def test_scan_worker_redacts_known_url_and_secret_candidates(tmp_path):
    from polymerhus.recon.js_acquisition.scan_worker import scan_local_file

    path, digest = _source(tmp_path, b"const fixture = true;\n")
    url_secret = "URL_QUERY_SECRET_123456789"
    raw_secret = "AKIAABCDEFGHIJKLMNOP"
    outputs = {
        "urls": JsluiceProcessResult(
            stdout=json.dumps(
                {
                    "kind": "fetch",
                    "url": (
                        "https://api.example.test/v1/items"
                        f"?token={url_secret}&view=full"
                    ),
                    "method": "POST",
                    "queryParams": ["token", "view"],
                    "bodyParams": ["username"],
                }
            )
            + "\n",
            returncode=0,
        ),
        "secrets": JsluiceProcessResult(
            stdout=json.dumps(
                {
                    "kind": "aws-access-key",
                    "severity": "high",
                    "data": {"secret": raw_secret},
                }
            )
            + "\n",
            returncode=0,
        ),
    }

    result = scan_local_file(
        path,
        expected_sha256=digest,
        expected_size=path.stat().st_size,
        executor=_executor(outputs),
        binary_info={"path": "jsluice", "sha256": "b" * 64, "version": "test"},
    )
    serialized = json.dumps(result)

    assert result["status"] == "complete"
    assert result["modes"]["urls"]["status"] == "complete"
    assert result["modes"]["secrets"]["status"] == "complete"
    assert len(result["candidates"]) == 2
    assert url_secret not in serialized
    assert raw_secret not in serialized
    redacted_query = parse_qs(
        urlsplit(unquote(result["candidates"][0]["redacted_url"])).query
    )
    assert redacted_query == {
        "token": ["[REDACTED]"],
        "view": ["[REDACTED]"],
    }
    assert result["candidates"][0]["mode"] == "urls"
    assert result["candidates"][0]["safe_metadata"]["method"] == "POST"
    assert result["candidates"][0]["safe_metadata"]["query_param_names"] == [
        "token",
        "view",
    ]
    assert result["candidates"][1]["secret_kind"] == "aws-access-key"
    assert len(result["candidates"][1]["secret_fingerprint"]) >= 32


def test_scan_worker_distinguishes_zero_results_from_failure(tmp_path):
    from polymerhus.recon.js_acquisition.scan_worker import scan_local_file

    path, digest = _source(tmp_path, b"const zero = true;\n")
    result = scan_local_file(
        path,
        expected_sha256=digest,
        expected_size=path.stat().st_size,
        executor=_executor(
            {
                "urls": JsluiceProcessResult(stdout="", returncode=0),
                "secrets": JsluiceProcessResult(
                    stdout="",
                    returncode=None,
                    error="binary_missing",
                ),
            }
        ),
        binary_info={"path": None, "sha256": None, "version": None},
    )

    assert result["modes"]["urls"]["candidate_count"] == 0
    assert result["modes"]["urls"]["status"] == "complete"
    assert result["modes"]["secrets"]["status"] == "failed"
    assert result["modes"]["secrets"]["error"] == "binary_missing"
    assert result["status"] == "partial"


def test_scan_worker_reports_missing_executable_per_mode(tmp_path):
    from polymerhus.recon.js_acquisition.scan_worker import scan_local_file

    path, digest = _source(tmp_path, b"const missingBinary = true;\n")
    result = scan_local_file(
        path,
        expected_sha256=digest,
        expected_size=path.stat().st_size,
        executable=str(tmp_path / "missing-jsluice"),
    )

    assert result["status"] == "failed"
    assert result["modes"]["urls"]["error"] == "binary_missing"
    assert result["modes"]["secrets"]["error"] == "binary_missing"


def test_scan_worker_marks_timeout_exit_and_malformed_lines(tmp_path):
    from polymerhus.recon.js_acquisition.scan_worker import scan_local_file

    path, digest = _source(tmp_path, b"const modes = true;\n")
    good_url = json.dumps({"url": "/api/items?token=hidden"}) + "\n"
    result = scan_local_file(
        path,
        expected_sha256=digest,
        expected_size=path.stat().st_size,
        executor=_executor(
            {
                "urls": JsluiceProcessResult(
                    stdout=good_url + "not-json\n",
                    returncode=0,
                ),
                "secrets": JsluiceProcessResult(
                    stdout="",
                    returncode=None,
                    timed_out=True,
                    error="timeout",
                ),
            }
        ),
        binary_info={"path": "jsluice", "sha256": "c" * 64, "version": None},
    )

    assert result["modes"]["urls"]["status"] == "partial"
    assert result["modes"]["urls"]["malformed_lines"] == 1
    assert result["modes"]["urls"]["candidate_count"] == 1
    assert result["modes"]["secrets"]["status"] == "failed"
    assert result["modes"]["secrets"]["timed_out"] is True
    assert "not-json" not in json.dumps(result)


def test_scan_worker_keeps_nonzero_exit_failed_even_with_complete_json(tmp_path):
    from polymerhus.recon.js_acquisition.scan_worker import scan_local_file

    path, digest = _source(tmp_path, b"const nonzero = true;\n")
    result = scan_local_file(
        path,
        expected_sha256=digest,
        expected_size=path.stat().st_size,
        executor=_executor(
            {
                "urls": JsluiceProcessResult(
                    stdout=json.dumps({"url": "/api"}) + "\n",
                    returncode=9,
                    stderr_bytes=42,
                ),
                "secrets": JsluiceProcessResult(stdout="", returncode=0),
            }
        ),
        binary_info={"path": "jsluice", "sha256": "e" * 64, "version": None},
    )

    assert result["modes"]["urls"]["status"] == "partial"
    assert result["modes"]["urls"]["error"] == "exit_9"
    assert result["modes"]["urls"]["candidate_count"] == 1
    assert result["status"] == "partial"


def test_scan_worker_does_not_report_complete_for_unclassified_json(tmp_path):
    from polymerhus.recon.js_acquisition.scan_worker import scan_local_file

    path, digest = _source(tmp_path, b"const unclassified = true;\n")
    result = scan_local_file(
        path,
        expected_sha256=digest,
        expected_size=path.stat().st_size,
        executor=_executor(
            {
                "urls": JsluiceProcessResult(
                    stdout=json.dumps({"unexpected": "shape"}) + "\n",
                    returncode=0,
                ),
                "secrets": JsluiceProcessResult(stdout="", returncode=0),
            }
        ),
        binary_info={"path": "jsluice", "sha256": "1" * 64, "version": None},
    )

    assert result["modes"]["urls"]["candidate_count"] == 0
    assert result["modes"]["urls"]["unclassified_records"] == 1
    assert result["modes"]["urls"]["status"] == "partial"
    assert result["status"] == "partial"


def test_scan_worker_truncates_oversized_redacted_url_candidate(tmp_path):
    from polymerhus.recon.js_acquisition.scan_worker import scan_local_file

    path, digest = _source(tmp_path, b"const longUrl = true;\n")
    result = scan_local_file(
        path,
        expected_sha256=digest,
        expected_size=path.stat().st_size,
        executor=_executor(
            {
                "urls": JsluiceProcessResult(
                    stdout=json.dumps(
                        {
                            "url": "https://example.test/"
                            + "/".join(f"s{index}" for index in range(1000)),
                            "queryParams": ["token"],
                        }
                    )
                    + "\n",
                    returncode=0,
                ),
                "secrets": JsluiceProcessResult(stdout="", returncode=0),
            }
        ),
        binary_info={"path": "jsluice", "sha256": "f" * 64, "version": None},
    )

    candidate = result["candidates"][0]
    assert candidate["url_truncated"] is True
    assert len(candidate["redacted_url"]) <= 2048
    assert len(json.dumps(candidate, separators=(",", ":")).encode()) <= 4096


def test_scan_worker_keeps_valid_mode_when_other_mode_exceeds_output(tmp_path):
    from polymerhus.recon.js_acquisition.scan_worker import scan_local_file

    path, digest = _source(tmp_path, b"const overflow = true;\n")
    result = scan_local_file(
        path,
        expected_sha256=digest,
        expected_size=path.stat().st_size,
        executor=_executor(
            {
                "urls": JsluiceProcessResult(
                    stdout=json.dumps({"url": "https://example.test/a"}) + "\n",
                    returncode=0,
                ),
                "secrets": JsluiceProcessResult(
                    stdout="",
                    returncode=None,
                    output_exceeded=True,
                    error="output_limit",
                ),
            }
        ),
        binary_info={"path": "jsluice", "sha256": "d" * 64, "version": None},
    )

    assert result["candidates"][0]["mode"] == "urls"
    assert result["modes"]["urls"]["status"] == "complete"
    assert result["modes"]["secrets"]["status"] == "failed"
    assert result["modes"]["secrets"]["output_exceeded"] is True


def test_bounded_process_enforces_timeout_and_reaps_child():
    result = run_bounded_process(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        stdin_path=None,
        timeout_s=0.1,
        max_output_bytes=1024,
    )

    assert result.timed_out is True
    assert result.returncode is not None
    assert result.error == "timeout"
    assert result.duration_ms < 3000


def test_bounded_process_stops_collection_at_output_cap():
    result = run_bounded_process(
        [
            sys.executable,
            "-c",
            "import sys, time; "
            "sys.stderr.buffer.write(b'y' * 1000); sys.stderr.buffer.flush(); "
            "time.sleep(0.1); sys.stdout.buffer.write(b'x' * 100000)",
        ],
        stdin_path=None,
        timeout_s=5,
        max_output_bytes=1024,
    )

    assert result.output_exceeded is True
    assert result.error == "output_limit"
    assert len(result.stdout.encode()) <= 1024
    assert result.stderr_bytes > 0


def test_bounded_process_preserves_nonzero_exit_for_classification():
    result = run_bounded_process(
        [
            sys.executable,
            "-c",
            "import sys; print('complete-record'); "
            "sys.stderr.write('sensitive error'); raise SystemExit(7)",
        ],
        stdin_path=None,
        timeout_s=5,
        max_output_bytes=1024,
    )

    assert result.returncode == 7
    assert result.stdout == "complete-record\n"
    assert result.stderr_bytes > 0
    assert result.error is None
    assert "sensitive error" not in repr(result)
