from pathlib import Path
from urllib.parse import quote
import hashlib


class SourceValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def content_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def validate_source_path(path: Path, *, allowed_root: Path) -> Path:
    resolved_path = path.resolve()
    resolved_root = allowed_root.resolve()
    if not resolved_path.exists():
        raise SourceValidationError("SOURCE_NOT_FOUND", "Source file does not exist")
    if not resolved_path.is_file():
        raise SourceValidationError("UNSUPPORTED_FORMAT", "Source path is not a file")
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise SourceValidationError(
            "SOURCE_OUTSIDE_ALLOWED_ROOT",
            "Source path is outside the allowed ingestion root",
        ) from exc
    return resolved_path


def build_source_key(path: Path, *, allowed_root: Path) -> str:
    resolved_path = validate_source_path(path, allowed_root=allowed_root)
    relative = resolved_path.relative_to(allowed_root.resolve()).as_posix()
    return f"file:{quote(relative, safe='/.-_ ')}"
