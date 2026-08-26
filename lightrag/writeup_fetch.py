from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence
from urllib.parse import urljoin, urlparse

from lightrag.preprocess import (
    DEFAULT_WRITEUP_OUTPUT_DIR,
    preprocess_writeups_for_lightrag,
)


DEFAULT_0XDF_BASE_URL = "https://0xdf.gitlab.io/"
DEFAULT_WRITEUP_RAW_DIR = Path("lightrag/data/lightrag/inputs/writeups_raw/0xdf")
SUPPORTED_SOURCES = ("0xdf",)


@dataclass(frozen=True)
class WriteupFetchResult:
    downloaded_files: list[Path]
    generated_files: list[Path]


def _slug(value: str, *, fallback: str = "writeup") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or fallback


def _clean_html_text(value: str) -> str:
    without_tags = re.sub(r"(?is)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def normalize_0xdf_url(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("0xdf URL must not be blank")
    url = urljoin(DEFAULT_0XDF_BASE_URL, raw)
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc != "0xdf.gitlab.io":
        raise ValueError(f"unsupported 0xdf URL: {value}")
    if ".." in Path(parsed.path).parts:
        raise ValueError(f"0xdf URL path must not contain '..': {value}")
    path = parsed.path or "/"
    return f"https://0xdf.gitlab.io{path}"


def _open_url(url: str, opener: Callable[[str], object] | None = None):
    if opener is not None:
        return opener(url)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 Polyphemus-LightRAG/1.0"},
    )
    return urllib.request.urlopen(request, timeout=30)


def _download_url(
    url: str,
    destination: Path,
    *,
    opener: Callable[[str], object] | None = None,
) -> bytes:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _open_url(url, opener=opener) as response:
            payload = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"failed to download {url}: {exc}") from exc
    destination.write_bytes(payload)
    return payload


def _extract_title(source: str, url: str) -> str:
    for pattern in (
        r"<h1\b[^>]*class=[\"'][^\"']*post-title[^\"']*[\"'][^>]*>(.*?)</h1>",
        r"<h1\b[^>]*>(.*?)</h1>",
        r"<title\b[^>]*>(.*?)</title>",
    ):
        match = re.search(pattern, source, flags=re.I | re.S)
        if match:
            title = _clean_html_text(match.group(1))
            title = re.sub(r"\s+\|\s+0xdf.*$", "", title, flags=re.I).strip()
            if title:
                return title
    return Path(urlparse(url).path).stem.replace("-", " ").title()


def _extract_date(source: str, url: str) -> str | None:
    for pattern in (
        r"<time\b[^>]*datetime=[\"']([^\"']+)[\"']",
        r"<meta\b[^>]*property=[\"']article:published_time[\"'][^>]*content=[\"']([^\"']+)[\"']",
    ):
        match = re.search(pattern, source, flags=re.I | re.S)
        if match:
            return html.unescape(match.group(1).strip())
    parts = [part for part in Path(urlparse(url).path).parts if part.isdigit()]
    if len(parts) >= 3:
        return "-".join(parts[:3])
    return None


def _extract_tags(source: str) -> list[str]:
    tags = [
        _clean_html_text(tag)
        for tag in re.findall(r"class=[\"']post-tag[\"'][^>]*>(.*?)</a>", source, flags=re.I | re.S)
    ]
    return [tag for tag in dict.fromkeys(tags) if tag]


def _filename_for_0xdf_writeup(url: str, title: str, source_date: str | None) -> str:
    path = Path(urlparse(url).path)
    stem = _slug(path.stem or title)
    if source_date:
        date_prefix = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", source_date)
        if date_prefix:
            return f"{date_prefix.group(1)}-{date_prefix.group(2)}-{date_prefix.group(3)}-{stem}.html"
    parts = [part for part in path.parts if part.isdigit()]
    if len(parts) >= 3:
        return f"{parts[0]}-{parts[1]}-{parts[2]}-{stem}.html"
    return f"{stem}.html"


def collect_0xdf_writeup_urls(
    *,
    limit: int | None = None,
    year: int | None = None,
    index_url: str = DEFAULT_0XDF_BASE_URL,
    opener: Callable[[str], object] | None = None,
) -> list[str]:
    normalized_index = normalize_0xdf_url(index_url)
    try:
        with _open_url(normalized_index, opener=opener) as response:
            payload = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"failed to download {normalized_index}: {exc}") from exc
    source = payload.decode("utf-8", "ignore")
    urls: list[str] = []
    for href in re.findall(r"<a\b[^>]*class=[\"'][^\"']*post-link[^\"']*[\"'][^>]*href=[\"']([^\"']+)[\"']", source, flags=re.I):
        normalized = normalize_0xdf_url(href)
        if year is not None and f"/{year:04d}/" not in urlparse(normalized).path:
            continue
        if normalized.endswith(".html") and normalized not in urls:
            urls.append(normalized)
    if limit is not None:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        urls = urls[:limit]
    return urls


def _write_raw_manifest(raw_dir: Path, entries: Sequence[dict]) -> None:
    manifest_path = raw_dir / ".manifest.json"
    existing_entries: list[dict] = []
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            existing_entries = list(existing.get("writeups", []))
        except json.JSONDecodeError:
            existing_entries = []
    merged: dict[str, dict] = {
        entry.get("source_path") or entry.get("url") or str(index): entry
        for index, entry in enumerate(existing_entries)
    }
    for entry in entries:
        merged[entry.get("source_path") or entry["url"]] = entry
    payload = {
        "schema_version": 1,
        "source": "0xdf",
        "source_base_url": DEFAULT_0XDF_BASE_URL,
        "writeups": list(merged.values()),
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def fetch_0xdf_writeups(
    urls: Iterable[str],
    *,
    raw_dir: str | Path = DEFAULT_WRITEUP_RAW_DIR,
    opener: Callable[[str], object] | None = None,
) -> list[Path]:
    raw_path = Path(raw_dir)
    raw_path.mkdir(parents=True, exist_ok=True)
    downloaded: list[Path] = []
    manifest_entries: list[dict] = []
    fetched_at = datetime.now(timezone.utc).isoformat()
    for raw_url in urls:
        url = normalize_0xdf_url(raw_url)
        try:
            with _open_url(url, opener=opener) as response:
                payload = response.read()
        except urllib.error.URLError as exc:
            raise RuntimeError(f"failed to download {url}: {exc}") from exc
        source = payload.decode("utf-8", "ignore")
        title = _extract_title(source, url)
        source_date = _extract_date(source, url)
        tags = _extract_tags(source)
        destination = raw_path / _filename_for_0xdf_writeup(url, title, source_date)
        destination.write_bytes(payload)
        downloaded.append(destination)
        manifest_entries.append(
            {
                "url": url,
                "title": title,
                "date": source_date,
                "tags": tags,
                "source_path": destination.as_posix(),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "fetched_at": fetched_at,
            }
        )
    _write_raw_manifest(raw_path, manifest_entries)
    return downloaded


def _existing_writeup_sources(raw_dir: str | Path) -> list[Path]:
    raw_path = Path(raw_dir)
    files: list[Path] = []
    for suffix in ("*.html", "*.htm", "*.md", "*.markdown", "*.txt"):
        files.extend(sorted(raw_path.rglob(suffix)))
    return [path for path in sorted(files) if not path.name.startswith(".")]


def fetch_and_preprocess_writeups(
    *,
    source: str = "0xdf",
    urls: Iterable[str] = (),
    limit: int | None = None,
    year: int | None = None,
    raw_dir: str | Path = DEFAULT_WRITEUP_RAW_DIR,
    output_dir: str | Path = DEFAULT_WRITEUP_OUTPUT_DIR,
    skip_download: bool = False,
    opener: Callable[[str], object] | None = None,
) -> WriteupFetchResult:
    if source not in SUPPORTED_SOURCES:
        raise ValueError(f"unsupported writeup source {source!r}; supported: {', '.join(SUPPORTED_SOURCES)}")

    if skip_download:
        downloaded_files = _existing_writeup_sources(raw_dir)
        if not downloaded_files:
            raise FileNotFoundError(f"no existing writeup sources found under {raw_dir}")
    else:
        selected_urls = [normalize_0xdf_url(url) for url in urls]
        if not selected_urls:
            selected_urls = collect_0xdf_writeup_urls(limit=limit, year=year, opener=opener)
        elif limit is not None:
            if limit <= 0:
                raise ValueError("limit must be greater than zero")
            selected_urls = selected_urls[:limit]
        if year is not None:
            selected_urls = [
                url
                for url in selected_urls
                if f"/{year:04d}/" in urlparse(url).path
            ]
        if not selected_urls:
            raise ValueError("no 0xdf writeup URLs selected")
        downloaded_files = fetch_0xdf_writeups(selected_urls, raw_dir=raw_dir, opener=opener)

    result = preprocess_writeups_for_lightrag(downloaded_files, output_dir)
    return WriteupFetchResult(
        downloaded_files=downloaded_files,
        generated_files=result.generated_files,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download 0xdf writeups and preprocess them into LightRAG overlay methodology documents."
    )
    parser.add_argument("--source", choices=SUPPORTED_SOURCES, default="0xdf")
    parser.add_argument("--url", action="append", default=[], help="Specific 0xdf writeup URL or path.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Fetch the first N writeups from the 0xdf homepage when --url is omitted.",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Restrict selected 0xdf writeups to a publication year, e.g. 2026.",
    )
    parser.add_argument(
        "--raw-dir",
        default=DEFAULT_WRITEUP_RAW_DIR.as_posix(),
        help="Where downloaded raw writeup HTML is stored.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_WRITEUP_OUTPUT_DIR.as_posix(),
        help="Where normalized LightRAG overlay Markdown files are written.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Use existing raw writeup files under --raw-dir and only preprocess them.",
    )
    args = parser.parse_args(argv)

    if not args.skip_download and not args.url and args.limit is None and args.year is None:
        parser.error("provide --url, --limit, --year, or --skip-download")

    result = fetch_and_preprocess_writeups(
        source=args.source,
        urls=args.url,
        limit=args.limit,
        year=args.year,
        raw_dir=args.raw_dir,
        output_dir=args.output_dir,
        skip_download=args.skip_download,
    )
    print(
        json.dumps(
            {
                "downloaded_files": [path.as_posix() for path in result.downloaded_files],
                "generated_files": [path.as_posix() for path in result.generated_files],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
