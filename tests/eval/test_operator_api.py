"""The operator-only ground-truth HTTP boundary (operator dashboard, Task 3).

`operator_api.app` is a second, GET-only FastAPI. It is deliberately separate
from `read_api`: it serves the benchmark reference through its own port and its
own CORS origin, and the shared read API must never grow this route.

These tests drive the ASGI app directly (`httpx.ASGITransport`) because the
sandboxed `TestClient`'s thread portal cannot open its self-pipe.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import yaml

from operator_api import app as app_module
from operator_api import ground_truth

ORIGIN = "http://localhost:15173"


def _setup_file(setup_root: Path, name: str, targets: list[tuple[str, str]]) -> None:
    payload = {
        "schema_version": 1,
        "artifact_store": "/srv/eval-artifacts",
        "instances": [
            {
                "instance_id": "inst-1",
                "targets": [
                    {"target_key": key, "target_id": target_id}
                    for target_id, key in targets
                ],
            }
        ],
    }
    setup_root.mkdir(parents=True, exist_ok=True)
    (setup_root / name).write_text(yaml.safe_dump(payload), encoding="utf-8")


def _challenge(
    benchmark_root: Path,
    target: str,
    vulnerabilities: list[object],
    *,
    metadata: dict[str, object | None] | None = None,
) -> None:
    challenge_dir = benchmark_root / target
    challenge_dir.mkdir(parents=True, exist_ok=True)
    (challenge_dir / "challenge.json").write_text(
        json.dumps({"id": f"challenge-{target}", "vulnerabilities": vulnerabilities}),
        encoding="utf-8",
    )
    for vuln_id, meta in (metadata or {}).items():
        if meta is None:
            continue
        vuln_dir = challenge_dir / "vulnerability" / vuln_id
        vuln_dir.mkdir(parents=True, exist_ok=True)
        (vuln_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")


def _seed(tmp_path: Path) -> ground_truth.GroundTruthSource:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    _setup_file(setup_root, "first.yaml", [("comfyui-1", "webexploitbench/comfyui")])
    _challenge(
        benchmark_root,
        "comfyui",
        [
            {"vuln_id": "comfyui-001", "scoring": ["LLM_judge"]},
            {"vuln_id": "comfyui-002", "scoring": ["route_probe"]},
        ],
        metadata={
            "comfyui-001": {
                "Location": "http://comfyui-manager:8288/",
                "Vulnerability Type": "Arbitrary File Read",
            },
            "comfyui-002": {
                "Location": "/api/v1/items",
                "Vulnerability Type": "Path Traversal",
            },
        },
    )
    return ground_truth.GroundTruthSource(
        benchmark_root=benchmark_root,
        setup_root=setup_root,
        setup_files=("first.yaml",),
    )


def _request(
    app, method: str, url: str, *, headers: dict[str, str] | None = None
) -> httpx.Response:
    async def go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://operator") as client:
            return await client.request(method, url, headers=headers)

    return asyncio.run(go())


def _client_app(source: ground_truth.GroundTruthSource):
    return app_module.create_app(lambda: source, frontend_origin=ORIGIN)


# --- routes --------------------------------------------------------------------


def test_health_reports_readiness_without_ground_truth(tmp_path: Path) -> None:
    app = _client_app(_seed(tmp_path))

    res = _request(app, "GET", "/health")

    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
    assert "comfyui-001" not in res.text


def test_ground_truth_route_returns_the_mapped_reference(tmp_path: Path) -> None:
    app = _client_app(_seed(tmp_path))

    res = _request(app, "GET", "/ground-truth/targets/comfyui-1")

    assert res.status_code == 200
    assert res.json() == {
        "target_id": "comfyui-1",
        "provenance": "current_benchmark_checkout",
        "vulnerabilities": [
            {
                "vuln_id": "comfyui-001",
                "location": "http://comfyui-manager:8288/",
                "type": "Arbitrary File Read",
                "scoring": ["LLM_judge"],
            },
            {
                "vuln_id": "comfyui-002",
                "location": "/api/v1/items",
                "type": "Path Traversal",
                "scoring": ["route_probe"],
            },
        ],
    }


def test_mapped_failures_keep_their_stable_status_and_code(tmp_path: Path) -> None:
    app = _client_app(_seed(tmp_path))

    unknown = _request(app, "GET", "/ground-truth/targets/nope-1")
    assert (unknown.status_code, unknown.json()["detail"]) == (
        404,
        "ground_truth_target_unknown",
    )

    # `a\b` is not one path-safe segment, but it still routes to the handler
    # (a `.`/`..` segment would be normalized away by the client instead).
    unsafe = _request(app, "GET", "/ground-truth/targets/a%5Cb")
    assert (unsafe.status_code, unsafe.json()["detail"]) == (
        400,
        "ground_truth_invalid_target_id",
    )


def test_unavailable_source_is_a_path_free_503(tmp_path: Path) -> None:
    source = ground_truth.GroundTruthSource(
        benchmark_root=tmp_path / "absent",
        setup_root=tmp_path / "setups",
        setup_files=("first.yaml",),
    )
    app = _client_app(source)

    res = _request(app, "GET", "/ground-truth/targets/comfyui-1")

    assert (res.status_code, res.json()["detail"]) == (503, "ground_truth_source_invalid")
    assert str(tmp_path) not in res.text


def test_the_operator_api_is_get_only(tmp_path: Path) -> None:
    app = _client_app(_seed(tmp_path))

    res = _request(app, "POST", "/ground-truth/targets/comfyui-1")

    assert res.status_code == 405


def test_docs_and_openapi_are_disabled(tmp_path: Path) -> None:
    app = _client_app(_seed(tmp_path))

    for path in ("/docs", "/redoc", "/openapi.json"):
        assert _request(app, "GET", path).status_code == 404


# --- CORS ----------------------------------------------------------------------


def test_cors_allows_only_the_configured_origin(tmp_path: Path) -> None:
    app = _client_app(_seed(tmp_path))

    allowed = _request(app, "GET", "/health", headers={"Origin": ORIGIN})
    assert allowed.headers.get("access-control-allow-origin") == ORIGIN

    denied = _request(app, "GET", "/health", headers={"Origin": "https://other.invalid"})
    assert denied.headers.get("access-control-allow-origin") is None


@pytest.mark.parametrize(
    "origin", ["*", "https://other.invalid", "http://10.0.0.5:15173", "null"]
)
def test_non_loopback_or_wildcard_origins_are_rejected(origin: str) -> None:
    with pytest.raises(ValueError):
        app_module.create_app(lambda: None, frontend_origin=origin)


# --- environment factory -------------------------------------------------------


def test_filesystem_source_reads_its_environment_per_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    benchmark_root, setup_root = tmp_path / "bench", tmp_path / "setups"
    monkeypatch.setenv("EVAL_OPERATOR_BENCHMARK_ROOT", str(benchmark_root))
    monkeypatch.setenv("EVAL_OPERATOR_SETUP_ROOT", str(setup_root))
    monkeypatch.setenv("EVAL_OPERATOR_SETUP_FILES", "first.yaml, extra.yaml ,")

    source = app_module.filesystem_source()

    assert source.benchmark_root == benchmark_root
    assert source.setup_root == setup_root
    assert source.setup_files == ("first.yaml", "extra.yaml")


def test_module_import_reads_no_source_configuration() -> None:
    # The module-level app is built at import with defaults only; a source is
    # constructed per request, so import never touches the mounted filesystem.
    assert app_module.DEFAULT_FRONTEND_ORIGIN == "http://localhost:15173"
    assert app_module.app is not None
