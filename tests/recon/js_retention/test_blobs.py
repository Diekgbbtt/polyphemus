import hashlib

import pytest

from polymerhus.app.data_root import ensure_project
from polymerhus.recon.js_retention import blobs as blobs_module
from polymerhus.recon.js_retention.blobs import BlobError, JsBlobStore


def test_project_blob_path_is_private_and_content_addressed(tmp_path):
    ensure_project("project-a", root=tmp_path)
    ensure_project("project-b", root=tmp_path)
    body = b"console.log('retained');\n"
    digest = hashlib.sha256(body).hexdigest()
    store = JsBlobStore(root=tmp_path)

    written = store.write(
        project_id="project-a",
        sha256=digest,
        expected_size=len(body),
        body=body,
    )

    path = store.path("project-a", digest)
    assert written["status"] == "written"
    assert written["archive_ref"] == f"recon/js-artifacts/blobs/{digest}.blob"
    assert path.read_bytes() == body
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.stat().st_mode & 0o077 == 0
    assert store.verify(
        project_id="project-a",
        sha256=digest,
        expected_size=len(body),
    )
    assert not store.verify(
        project_id="project-b",
        sha256=digest,
        expected_size=len(body),
    )
    assert str(tmp_path) in str(path)
    assert "console.log" not in str(path)


def test_zero_byte_blob_and_invalid_identity_are_explicit(tmp_path):
    ensure_project("p", root=tmp_path)
    store = JsBlobStore(root=tmp_path)
    digest = hashlib.sha256(b"").hexdigest()

    assert store.write(
        project_id="p",
        sha256=digest,
        expected_size=0,
        body=b"",
    )["status"] == "written"
    assert store.verify(project_id="p", sha256=digest, expected_size=0)

    with pytest.raises(BlobError, match="invalid_blob_hash"):
        store.archive_ref("../not-a-hash")
    with pytest.raises(BlobError, match="blob_size_mismatch"):
        store.write(
            project_id="p",
            sha256=hashlib.sha256(b"x").hexdigest(),
            expected_size=2,
            body=b"x",
        )
    with pytest.raises(BlobError, match="blob_hash_mismatch"):
        store.write(
            project_id="p",
            sha256="a" * 64,
            expected_size=1,
            body=b"x",
        )


def test_interrupted_atomic_write_never_publishes_partial_target(
    tmp_path,
    monkeypatch,
):
    ensure_project("p", root=tmp_path)
    body = b"complete source bytes"
    digest = hashlib.sha256(body).hexdigest()
    store = JsBlobStore(root=tmp_path)
    target = store.path("p", digest)

    def interrupted(path, data):
        path = target.with_name(".interrupted.tmp")
        path.write_bytes(data[:5])
        raise OSError("simulated crash")

    monkeypatch.setattr(blobs_module, "write_bytes_atomic", interrupted)
    with pytest.raises(OSError, match="simulated crash"):
        store.write(
            project_id="p",
            sha256=digest,
            expected_size=len(body),
            body=body,
        )

    assert not target.exists()


def test_existing_corrupt_blob_is_not_replaced_silently(tmp_path):
    ensure_project("p", root=tmp_path)
    body = b"expected bytes"
    digest = hashlib.sha256(body).hexdigest()
    store = JsBlobStore(root=tmp_path)
    path = store.path("p", digest)
    path.write_bytes(b"corrupt")

    with pytest.raises(BlobError, match="existing_blob_mismatch"):
        store.write(
            project_id="p",
            sha256=digest,
            expected_size=len(body),
            body=body,
        )
    assert path.read_bytes() == b"corrupt"
