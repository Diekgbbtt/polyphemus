from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from agent.lightrag.preprocess import DEFAULT_WSTG_OUTPUT_DIR, preprocess_wstg_for_lightrag


DEFAULT_WSTG_RAW_DIR = Path("data/lightrag/inputs/wstg_raw")
DEFAULT_WSTG_REF = "master"
DEFAULT_WSTG_RAW_BASE = "https://raw.githubusercontent.com/OWASP/wstg"
WSTG_DOCUMENT_ROOT = "document"

SCENARIO_PATHS: dict[str, str] = {
    "sql-injection": (
        "4-Web_Application_Security_Testing/"
        "07-Input_Validation_Testing/"
        "05-Testing_for_SQL_Injection.md"
    ),
}


@dataclass(frozen=True)
class WSTGFetchResult:
    downloaded_files: list[Path]
    generated_files: list[Path]


def _normalize_relative_path(value: str) -> str:
    normalized = value.strip().lstrip("/")
    if not normalized:
        raise ValueError("WSTG path must not be blank")
    if normalized.startswith(f"{WSTG_DOCUMENT_ROOT}/"):
        normalized = normalized[len(WSTG_DOCUMENT_ROOT) + 1 :]
    if ".." in Path(normalized).parts:
        raise ValueError(f"WSTG path must not contain '..': {value}")
    return normalized


def resolve_wstg_paths(
    *,
    scenarios: Iterable[str] = (),
    paths: Iterable[str] = (),
) -> list[str]:
    resolved: list[str] = []
    for scenario in scenarios:
        key = scenario.strip().lower()
        if key not in SCENARIO_PATHS:
            known = ", ".join(sorted(SCENARIO_PATHS))
            raise ValueError(f"unknown WSTG scenario alias {scenario!r}; known aliases: {known}")
        resolved.append(SCENARIO_PATHS[key])
    for path in paths:
        resolved.append(_normalize_relative_path(path))
    return list(dict.fromkeys(resolved))


def build_raw_url(relative_path: str, *, ref: str = DEFAULT_WSTG_REF) -> str:
    normalized = _normalize_relative_path(relative_path)
    return f"{DEFAULT_WSTG_RAW_BASE}/{ref}/{WSTG_DOCUMENT_ROOT}/{normalized}"


def _download_url(
    url: str,
    destination: Path,
    *,
    opener: Callable[[str], object] | None = None,
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(url) as response:
            payload = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"failed to download {url}: {exc}") from exc
    destination.write_bytes(payload)
    return destination


def download_wstg_sources(
    relative_paths: Iterable[str],
    *,
    raw_dir: str | Path = DEFAULT_WSTG_RAW_DIR,
    ref: str = DEFAULT_WSTG_REF,
    opener: Callable[[str], object] | None = None,
) -> list[Path]:
    raw_path = Path(raw_dir)
    downloaded: list[Path] = []
    for relative_path in relative_paths:
        normalized = _normalize_relative_path(relative_path)
        destination = raw_path / normalized
        downloaded.append(
            _download_url(
                build_raw_url(normalized, ref=ref),
                destination,
                opener=opener,
            )
        )
    return downloaded


def fetch_and_preprocess_wstg(
    *,
    scenarios: Iterable[str] = (),
    paths: Iterable[str] = (),
    raw_dir: str | Path = DEFAULT_WSTG_RAW_DIR,
    output_dir: str | Path = DEFAULT_WSTG_OUTPUT_DIR,
    ref: str = DEFAULT_WSTG_REF,
    skip_download: bool = False,
    debug_facets: bool = False,
    opener: Callable[[str], object] | None = None,
) -> WSTGFetchResult:
    relative_paths = resolve_wstg_paths(scenarios=scenarios, paths=paths)
    if not relative_paths:
        raise ValueError("provide at least one --scenario or --path")

    if skip_download:
        downloaded_files = []
        missing = []
        for relative_path in relative_paths:
            normalized = _normalize_relative_path(relative_path)
            nested_path = Path(raw_dir) / normalized
            flat_path = Path(raw_dir) / Path(normalized).name
            if nested_path.exists():
                downloaded_files.append(nested_path)
            elif flat_path.exists():
                downloaded_files.append(flat_path)
            else:
                missing.append(nested_path)
        if missing:
            missing_text = ", ".join(path.as_posix() for path in missing)
            raise FileNotFoundError(f"skip-download requested but source files are missing: {missing_text}")
    else:
        downloaded_files = download_wstg_sources(
            relative_paths,
            raw_dir=raw_dir,
            ref=ref,
            opener=opener,
        )

    result = preprocess_wstg_for_lightrag(
        downloaded_files,
        output_dir,
        debug_facets=debug_facets,
    )
    return WSTGFetchResult(
        downloaded_files=downloaded_files,
        generated_files=result.generated_files,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download OWASP WSTG Markdown scenarios and preprocess them for LightRAG."
    )
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Known scenario alias to download. Currently supported: sql-injection.",
    )
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help=(
            "WSTG path relative to document/, e.g. "
            "4-Web_Application_Security_Testing/07-Input_Validation_Testing/"
            "05-Testing_for_SQL_Injection.md"
        ),
    )
    parser.add_argument("--ref", default=DEFAULT_WSTG_REF, help="OWASP/wstg git ref.")
    parser.add_argument(
        "--raw-dir",
        default=DEFAULT_WSTG_RAW_DIR.as_posix(),
        help="Where downloaded source Markdown files are stored.",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_WSTG_OUTPUT_DIR.as_posix(),
        help="Where preprocessed LightRAG Markdown files are written.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Use existing files under --raw-dir and only run preprocessing.",
    )
    parser.add_argument(
        "--debug-facets",
        action="store_true",
        help="Also write per-facet debug documents under _debug_facets/.",
    )
    args = parser.parse_args(argv)

    result = fetch_and_preprocess_wstg(
        scenarios=args.scenario,
        paths=args.path,
        raw_dir=args.raw_dir,
        output_dir=args.output_dir,
        ref=args.ref,
        skip_download=args.skip_download,
        debug_facets=args.debug_facets,
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
