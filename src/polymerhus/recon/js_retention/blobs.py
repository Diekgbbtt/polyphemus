"""Private project-scoped content-addressed JS blob storage."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from polymerhus.app.atomic_write import write_bytes_atomic
from polymerhus.app.data_root import project_dir

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class BlobError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class JsBlobStore:
    def __init__(self, *, root=None) -> None:
        self._root = root

    def archive_ref(self, sha256: str) -> str:
        if not _SHA256.fullmatch(sha256):
            raise BlobError("invalid_blob_hash")
        return f"recon/js-artifacts/blobs/{sha256}.blob"

    def path(self, project_id: str, sha256: str) -> Path:
        return project_dir(
            project_id,
            "recon/js-artifacts/blobs",
            root=self._root,
        ) / f"{sha256}.blob"

    def write(
        self,
        *,
        project_id: str,
        sha256: str,
        expected_size: int,
        body: bytes,
    ) -> dict:
        if (
            not isinstance(body, bytes)
            or not isinstance(expected_size, int)
            or expected_size < 0
        ):
            raise BlobError("invalid_blob_body")
        if len(body) != expected_size:
            raise BlobError("blob_size_mismatch")
        if hashlib.sha256(body).hexdigest() != sha256:
            raise BlobError("blob_hash_mismatch")
        path = self.path(project_id, sha256)
        if path.is_file():
            current = path.read_bytes()
            if len(current) == expected_size and hashlib.sha256(current).hexdigest() == sha256:
                return {
                    "status": "already_retained",
                    "archive_ref": self.archive_ref(sha256),
                    "size_bytes": expected_size,
                }
            raise BlobError("existing_blob_mismatch")
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        write_bytes_atomic(path, body)
        path.chmod(0o600)
        if (
            path.read_bytes() != body
            or hashlib.sha256(path.read_bytes()).hexdigest() != sha256
        ):
            raise BlobError("blob_verification_failed")
        return {
            "status": "written",
            "archive_ref": self.archive_ref(sha256),
            "size_bytes": expected_size,
        }

    def verify(
        self,
        *,
        project_id: str,
        sha256: str,
        expected_size: int | None = None,
    ) -> bool:
        try:
            path = self.path(project_id, sha256)
            if not path.is_file():
                return False
            body = path.read_bytes()
            return (
                hashlib.sha256(body).hexdigest() == sha256
                and (
                    expected_size is None
                    or len(body) == expected_size
                )
            )
        except OSError:
            return False


__all__ = ["BlobError", "JsBlobStore"]
