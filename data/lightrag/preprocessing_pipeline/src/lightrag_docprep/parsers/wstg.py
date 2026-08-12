from __future__ import annotations

import re
from pathlib import Path

from ..models import RawParseResult
from .base import ParserAdapter
from .markdown import MarkdownParser

_WSTG_ID_RE = re.compile(r"\bWSTG-[A-Z]{4}-\d{2}(?:[-.]\d+)?\b")
_WSTG_PATH_NUMBER_RE = re.compile(r"^(?P<major>\d{2})(?:[._-](?P<minor>\d+))?[-_]")
_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

_WSTG_CATEGORY_CODES = {
    "01-Information_Gathering": "INFO",
    "02-Configuration_and_Deployment_Management_Testing": "CONF",
    "03-Identity_Management_Testing": "IDNT",
    "04-Authentication_Testing": "ATHN",
    "05-Authorization_Testing": "ATHZ",
    "06-Session_Management_Testing": "SESS",
    "07-Input_Validation_Testing": "INPV",
    "08-Testing_for_Error_Handling": "ERRH",
    "09-Testing_for_Weak_Cryptography": "CRYP",
    "10-Business_Logic_Testing": "BUSL",
    "11-Client-side_Testing": "CLNT",
    "12-API_Testing": "APIT",
}

_WSTG_CATEGORY_NAMES = {
    "INFO": "Information Gathering",
    "CONF": "Configuration and Deployment Management Testing",
    "IDNT": "Identity Management Testing",
    "ATHN": "Authentication Testing",
    "ATHZ": "Authorization Testing",
    "SESS": "Session Management Testing",
    "INPV": "Input Validation Testing",
    "ERRH": "Error Handling",
    "CRYP": "Weak Cryptography",
    "BUSL": "Business Logic Testing",
    "CLNT": "Client-side Testing",
    "APIT": "API Testing",
}


def _category_code_from_path(path: Path) -> str | None:
    for part in reversed(path.parts):
        if part in _WSTG_CATEGORY_CODES:
            return _WSTG_CATEGORY_CODES[part]
    return None


def _detect_wstg_id(path: Path, markdown: str) -> str | None:
    for value in (markdown, path.as_posix(), path.stem):
        match = _WSTG_ID_RE.search(value.upper())
        if match:
            return match.group(0)

    category_code = _category_code_from_path(path)
    number_match = _WSTG_PATH_NUMBER_RE.match(path.name)
    if category_code is None or number_match is None:
        return None
    suffix = number_match.group("major")
    minor = number_match.group("minor")
    if minor:
        suffix = f"{suffix}-{minor}"
    return f"WSTG-{category_code}-{suffix}"


def _detect_title(path: Path, markdown: str) -> str:
    for match in _HEADING_RE.finditer(markdown):
        title = match.group(1).strip()
        if title.lower() not in {"wstg - latest", "id"}:
            return title
    return path.stem.replace("-", " ").replace("_", " ").strip().title()


class WstgParser(ParserAdapter):
    name = "wstg"
    supported_suffixes = frozenset({".md", ".markdown"})

    def is_available(self) -> bool:
        return True

    async def parse(self, path: Path) -> RawParseResult:
        text = path.read_text(encoding="utf-8", errors="replace")
        markdown = MarkdownParser._strip_front_matter(text).rstrip()
        title = _detect_title(path, markdown)
        wstg_id = _detect_wstg_id(path, markdown)
        category_code = _category_code_from_path(path)
        if category_code is None and wstg_id:
            parts = wstg_id.split("-")
            category_code = parts[1] if len(parts) >= 3 else None

        metadata: dict[str, str] = {"wstg_title": title}
        if wstg_id:
            metadata["wstg_id"] = wstg_id
        if category_code:
            metadata["wstg_category_code"] = category_code
            category_name = _WSTG_CATEGORY_NAMES.get(category_code)
            if category_name:
                metadata["wstg_category"] = category_name

        return RawParseResult(
            parser_name=self.name,
            source_path=str(path),
            title_candidate=title,
            markdown=markdown,
            source_profile="wstg",
            native_metadata=metadata,
        )
