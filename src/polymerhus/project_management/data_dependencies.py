"""The pre-built eval data-dependency placement contract.

The eval harness creates a project deterministically, then places the target's
pre-built data-dependency artifacts into the app-owned data root through four
operator-only `multipart/form-data` write endpoints. The agent container finds
them already present at startup (a MOUNT, never a runtime provision):

    <data_root>/<project_id>/
    ├── skills/authn/SKILL.md (+ references/)   # the replayable authn procedure
    └── auth/{overview.yaml,credentials.yaml}   # the AuthContext

The L1 surface is not a file: its endpoint persists the deterministic skeleton
directly into the knowledge graph (through `polymerhus.analysis.scaffold`).

TRANSPORT - each endpoint takes one `file` part carrying the raw bytes.
`fileName` is an optional multipart attribute and is NEVER the path authority:
the canonical destination is hardcoded server-side.
The `authn-skill` `file` is a SINGLE ARCHIVE (`.tar.gz` or `.zip`) whose members
are the bundle's files; every other endpoint's `file` is the single canonical
file's bytes.

Pure logic, no I/O: archive unpacking, path canonicalisation, and text decoding
live here; the stores own every write.
"""
from __future__ import annotations

import io
import re
import tarfile
import zipfile

# The authn bundle's allowed relative paths: the canonical SKILL.md plus one
# safe file stem under each canonical subdirectory. No nesting, no traversal.
AUTHN_SKILL = "authn"
_AUTHN_FILE_RE = re.compile(
    r"(?:SKILL\.md|(?:references|scripts|assets)/[A-Za-z0-9][A-Za-z0-9._-]*)\Z"
)

# The canonical single-file artifact names.
OVERVIEW_FILE = "overview.yaml"
CREDENTIALS_FILE = "credentials.yaml"
OPERATOR_KB_FILE = "operator_kb.md"

# The wrapper directory names an archive may carry before the bundle root; both
# are stripped so `skills/authn/SKILL.md` and `authn/SKILL.md` both normalize to
# `SKILL.md`.
_WRAPPER_COMPONENTS = ("skills", AUTHN_SKILL)

_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_GZIP_MAGIC = b"\x1f\x8b"


class DataDependencyError(ValueError):
    """The denoted malformed-placement signal: the uploaded bytes are not a
    decodable file/archive, or a member path is not canonical. Carries a stable
    `code` for the HTTP envelope."""

    def __init__(self, detail: str, *, code: str = "data_dependency_invalid") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def decode_text(data: bytes) -> str:
    """Decode one uploaded file as strict UTF-8 text. Refuses empty or invalid
    bytes loudly (the caller parses the text as YAML/Markdown)."""
    if not data:
        raise DataDependencyError("the uploaded file is empty")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DataDependencyError(f"the uploaded file is not valid UTF-8: {exc}") from exc


def _is_unsafe_member(name: str) -> bool:
    """True for a member path that is absolute, traversing, or empty."""
    if not name or name.startswith("/") or name.startswith("\\"):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", name):  # a Windows absolute path
        return True
    return any(part == ".." for part in re.split(r"[\\/]+", name))


def _strip_wrapper(names: list[str]) -> list[str]:
    """Strip a leading `skills/` then `authn/` wrapper when EVERY member shares
    it, so an archive rooted at the bundle (or at the skills dir) normalizes to
    canonical bundle-relative paths. A wrapper is stripped only while every
    remaining path still has a component after it."""
    parts = [n.split("/") for n in names]
    for wrapper in _WRAPPER_COMPONENTS:
        if parts and len({p[0] for p in parts}) == 1 and parts[0][0] == wrapper \
                and all(len(p) > 1 for p in parts):
            parts = [p[1:] for p in parts]
    return ["/".join(p) for p in parts]


def _members_from_zip(data: bytes) -> dict[str, str]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DataDependencyError(f"the uploaded archive is not a valid zip: {exc}") from exc
    files: dict[str, str] = {}
    with archive:
        for info in archive.infolist():
            name = info.filename
            if info.is_dir():
                continue
            if _is_unsafe_member(name):
                raise DataDependencyError(f"archive member {name!r} is unsafe")
            try:
                files[name] = archive.read(info).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise DataDependencyError(
                    f"archive member {name!r} is not valid UTF-8: {exc}") from exc
    return files


def _members_from_tar(data: bytes) -> dict[str, str]:
    try:
        archive = tarfile.open(fileobj=io.BytesIO(data), mode="r:*")
    except tarfile.TarError as exc:
        raise DataDependencyError(f"the uploaded archive is not a valid tar: {exc}") from exc
    files: dict[str, str] = {}
    with archive:
        for member in archive.getmembers():
            if not member.isfile():
                # reject symlinks/devices; silently skip a directory entry.
                if member.isdir():
                    continue
                raise DataDependencyError(
                    f"archive member {member.name!r} is not a regular file")
            if _is_unsafe_member(member.name):
                raise DataDependencyError(f"archive member {member.name!r} is unsafe")
            handle = archive.extractfile(member)
            if handle is None:
                raise DataDependencyError(f"archive member {member.name!r} is unreadable")
            try:
                files[member.name] = handle.read().decode("utf-8")
            except UnicodeDecodeError as exc:
                raise DataDependencyError(
                    f"archive member {member.name!r} is not valid UTF-8: {exc}") from exc
    return files


def unpack_authn_archive(data: bytes) -> dict[str, str]:
    """Unpack the authn bundle archive into canonical bundle-relative files.

    Accepts `.zip` or `.tar.gz` (also a plain `.tar`). Rejects traversal,
    absolute, symlink, and non-UTF-8 members. Requires `SKILL.md` and every
    member to be a canonical bundle path. Returns `{relative_path: text}`.
    """
    if not data:
        raise DataDependencyError("the uploaded archive is empty")
    if data.startswith(_ZIP_MAGIC):
        files = _members_from_zip(data)
    elif data.startswith(_GZIP_MAGIC):
        files = _members_from_tar(data)
    else:
        # a plain tar or an unknown format: let tarfile decide, surface its error.
        files = _members_from_tar(data)

    normalized = {path: text for path, text in zip(_strip_wrapper(list(files)), files.values())}
    if "SKILL.md" not in normalized:
        raise DataDependencyError("the authn archive must include SKILL.md at its root")
    for path in normalized:
        if not _AUTHN_FILE_RE.match(path):
            raise DataDependencyError(
                f"authn archive member {path!r} is not a canonical bundle file")
    return normalized


# The canonical route paths (OpenAPI path templates), used to stamp the exact
# multipart requestBody FastAPI does not emit (it writes `contentMediaType`
# instead of the required `format: binary`).
DATA_DEPENDENCY_PATHS: tuple[str, ...] = (
    "/projects/{project_id}/data-dependencies/authn-skill",
    "/projects/{project_id}/data-dependencies/auth-overview",
    "/projects/{project_id}/data-dependencies/auth-credentials",
    "/projects/{project_id}/data-dependencies/l1",
)


def _request_body() -> dict:
    """The exact multipart requestBody contract for every placement endpoint."""
    return {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "fileName": {"type": "string"},
                        "file": {"type": "string", "format": "binary"},
                    },
                    "required": ["file"],
                }
            }
        },
    }


def patch_openapi(schema: dict) -> dict:
    """Stamp the exact multipart requestBody onto the four placement operations.

    FastAPI's generated schema uses `contentMediaType: application/octet-stream`
    for an `UploadFile`; the contract requires `format: binary`, so this rewrites
    the requestBody for those four paths only. Mutates and returns `schema`."""
    paths = schema.get("paths", {})
    for path in DATA_DEPENDENCY_PATHS:
        operation = paths.get(path, {}).get("post")
        if operation is not None:
            operation["requestBody"] = _request_body()
    return schema


__all__ = [
    "AUTHN_SKILL",
    "CREDENTIALS_FILE",
    "DATA_DEPENDENCY_PATHS",
    "DataDependencyError",
    "OPERATOR_KB_FILE",
    "OVERVIEW_FILE",
    "decode_text",
    "patch_openapi",
    "unpack_authn_archive",
]
