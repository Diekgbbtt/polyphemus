from pathlib import Path

import pytest
from fastapi import HTTPException

from polymerhus.app.data_root import ensure_project
from polymerhus.recon.js_acquisition import (
    AcquisitionResult,
    AcquisitionService,
)
from polymerhus.recon.js_acquisition.api import build_router


def test_acquire_route_streams_private_body_with_metadata_only_headers(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    service = AcquisitionService(root=root, work_root=tmp_path / "work")
    result = AcquisitionResult(
        lead_id="lead-1",
        body=b"export const answer = 42;\n",
        status_code=200,
        content_type="application/javascript",
        size=26,
        sha256="a2098bd92b10bf8b816d24b7556b1ce8c49a879d130489065ef1051c17e042f6",
        work_file_ref=(
            "/work/js-analysis/run-1/"
            "a2098bd92b10bf8b816d24b7556b1ce8c49a879d130489065ef1051c17e042f6.js"
        ),
    )
    monkeypatch.setattr(service, "fetch", lambda **kwargs: result)
    router = build_router(service=service)
    route = next(
        route for route in router.routes
        if route.path == "/recon/js-analysis/acquire/{lead_id}"
    )

    response = route.endpoint(lead_id="lead-1", reference="opaque-reference")

    assert response.body == result.body
    rendered_headers = repr(dict(response.headers))
    assert "private-token" not in rendered_headers
    assert "public.js" not in rendered_headers
    assert "exact_url" not in rendered_headers
    assert response.headers["x-js-status"] == "fetched_pending_work_file"


def test_acquire_route_requires_reference_and_returns_named_failure(
    tmp_path: Path,
) -> None:
    root = tmp_path / "data"
    ensure_project("proj-1", root=root)
    service = AcquisitionService(root=root, work_root=tmp_path / "work")
    router = build_router(service=service)
    route = next(
        route for route in router.routes
        if route.path == "/recon/js-analysis/acquire/{lead_id}"
    )

    with pytest.raises(HTTPException) as exc:
        route.endpoint(lead_id="lead-1", reference=None)

    assert exc.value.status_code == 403
