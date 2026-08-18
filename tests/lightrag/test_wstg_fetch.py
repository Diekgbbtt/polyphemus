from pathlib import Path

import pytest

from polymerhus.lightrag.wstg_fetch import (
    build_raw_url,
    fetch_and_preprocess_wstg,
    resolve_wstg_paths,
)


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


def test_resolve_wstg_alias_and_build_url():
    paths = resolve_wstg_paths(scenarios=["sql-injection"], paths=[])

    assert paths == [
        "4-Web_Application_Security_Testing/"
        "07-Input_Validation_Testing/"
        "05-Testing_for_SQL_Injection.md"
    ]
    assert build_raw_url(paths[0], ref="master") == (
        "https://raw.githubusercontent.com/OWASP/wstg/master/document/"
        "4-Web_Application_Security_Testing/07-Input_Validation_Testing/"
        "05-Testing_for_SQL_Injection.md"
    )


def test_resolve_wstg_rejects_unknown_alias_and_parent_paths():
    with pytest.raises(ValueError):
        resolve_wstg_paths(scenarios=["unknown"], paths=[])

    with pytest.raises(ValueError):
        resolve_wstg_paths(paths=["../secret.md"])


def test_fetch_and_preprocess_downloads_markdown_without_network(tmp_path):
    seen_urls = []

    def fake_open(url):
        seen_urls.append(url)
        return FakeResponse(
            b"""# Testing for SQL Injection

|ID|
|--|
|WSTG-INPV-05|

## Summary

SQL injection testing checks user-controlled SQL input.

## How to Test

Test the `id` parameter.
"""
        )

    result = fetch_and_preprocess_wstg(
        scenarios=["sql-injection"],
        raw_dir=tmp_path / "raw",
        output_dir=tmp_path / "out",
        opener=fake_open,
    )

    source_path = tmp_path / "raw" / (
        "4-Web_Application_Security_Testing/"
        "07-Input_Validation_Testing/"
        "05-Testing_for_SQL_Injection.md"
    )
    assert result.downloaded_files == [source_path]
    assert source_path.exists()
    assert seen_urls == [build_raw_url(resolve_wstg_paths(scenarios=["sql-injection"])[0])]
    assert (tmp_path / "out" / "wstg-inpv-05-methodology.md").exists()
    assert (tmp_path / "out" / ".manifest.json").exists()


def test_fetch_and_preprocess_skip_download_uses_existing_file(tmp_path):
    relative_path = Path(
        "4-Web_Application_Security_Testing/"
        "07-Input_Validation_Testing/"
        "05-Testing_for_SQL_Injection.md"
    )
    source = tmp_path / "raw" / relative_path
    source.parent.mkdir(parents=True)
    source.write_text(
        """# Testing for SQL Injection

|ID|
|--|
|WSTG-INPV-05|

## Summary

SQL injection testing checks user-controlled SQL input.
""",
        encoding="utf-8",
    )

    result = fetch_and_preprocess_wstg(
        paths=[relative_path.as_posix()],
        raw_dir=tmp_path / "raw",
        output_dir=tmp_path / "out",
        skip_download=True,
    )

    assert result.downloaded_files == [source]
    assert (tmp_path / "out" / "wstg-inpv-05-methodology.md").exists()


def test_fetch_and_preprocess_skip_download_accepts_flat_existing_file(tmp_path):
    source = tmp_path / "raw" / "05-Testing_for_SQL_Injection.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        """# Testing for SQL Injection

|ID|
|--|
|WSTG-INPV-05|

## Summary

SQL injection testing checks user-controlled SQL input.
""",
        encoding="utf-8",
    )

    result = fetch_and_preprocess_wstg(
        scenarios=["sql-injection"],
        raw_dir=tmp_path / "raw",
        output_dir=tmp_path / "out",
        skip_download=True,
    )

    assert result.downloaded_files == [source]
    assert (tmp_path / "out" / "wstg-inpv-05-methodology.md").exists()
