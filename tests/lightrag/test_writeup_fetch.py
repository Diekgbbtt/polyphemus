import json

import pytest

from agent.lightrag.writeup_fetch import (
    collect_0xdf_writeup_urls,
    fetch_and_preprocess_writeups,
    normalize_0xdf_url,
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


def test_normalize_0xdf_url_accepts_paths_and_rejects_external_hosts():
    assert normalize_0xdf_url("/2022/10/29/htb-trick.html") == (
        "https://0xdf.gitlab.io/2022/10/29/htb-trick.html"
    )

    with pytest.raises(ValueError):
        normalize_0xdf_url("https://example.com/2022/10/29/htb-trick.html")


def test_collect_0xdf_writeup_urls_from_homepage_without_network():
    def fake_open(url):
        assert url == "https://0xdf.gitlab.io/"
        return FakeResponse(
            b"""<html><body>
<a class="post-link" href="/2022/10/29/htb-trick.html">HTB: Trick</a>
<a class="post-link" href="/2021/05/15/htb-ready.html">HTB: Ready</a>
</body></html>"""
        )

    assert collect_0xdf_writeup_urls(limit=1, opener=fake_open) == [
        "https://0xdf.gitlab.io/2022/10/29/htb-trick.html"
    ]


def test_collect_0xdf_writeup_urls_can_filter_by_year_without_network():
    def fake_open(url):
        assert url == "https://0xdf.gitlab.io/"
        return FakeResponse(
            b"""<html><body>
<a class="post-link" href="/2026/07/18/htb-logging.html">HTB: Logging</a>
<a class="post-link" href="/2025/12/20/htb-older.html">HTB: Older</a>
<a class="post-link" href="/2026/07/12/htb-cctv.html">HTB: CCTV</a>
</body></html>"""
        )

    assert collect_0xdf_writeup_urls(year=2026, opener=fake_open) == [
        "https://0xdf.gitlab.io/2026/07/18/htb-logging.html",
        "https://0xdf.gitlab.io/2026/07/12/htb-cctv.html",
    ]


def test_fetch_and_preprocess_writeups_downloads_raw_and_generates_overlay(tmp_path):
    homepage = b"""<html><body>
<a class="post-link" href="/2022/10/29/htb-trick.html">HTB: Trick</a>
</body></html>"""
    writeup = b"""<!doctype html>
<html>
  <head>
    <title>HTB: Trick | 0xdf hacks stuff</title>
    <link rel="canonical" href="https://0xdf.gitlab.io/2022/10/29/htb-trick.html">
  </head>
  <body>
    <main class="page-content">
      <h1 class="post-title">HTB: Trick</h1>
      <time datetime="2022-10-29">Oct 29, 2022</time>
      <span class="tag-list"><a href="/tags#sqli" class="post-tag">sqli</a></span>
      <h2>SQL Injection</h2>
      <p>The login form is vulnerable to SQL injection and auth bypass.</p>
      <p>sqlmap --file-read=/etc/passwd gives file read.</p>
    </main>
  </body>
</html>"""

    def fake_open(url):
        if url == "https://0xdf.gitlab.io/":
            return FakeResponse(homepage)
        if url == "https://0xdf.gitlab.io/2022/10/29/htb-trick.html":
            return FakeResponse(writeup)
        raise AssertionError(url)

    result = fetch_and_preprocess_writeups(
        limit=1,
        raw_dir=tmp_path / "raw",
        output_dir=tmp_path / "out",
        opener=fake_open,
    )

    raw_file = tmp_path / "raw" / "2022-10-29-htb-trick.html"
    assert result.downloaded_files == [raw_file]
    assert raw_file.exists()

    raw_manifest = json.loads((tmp_path / "raw" / ".manifest.json").read_text(encoding="utf-8"))
    assert raw_manifest["source"] == "0xdf"
    assert raw_manifest["writeups"][0]["url"] == "https://0xdf.gitlab.io/2022/10/29/htb-trick.html"
    assert raw_manifest["writeups"][0]["tags"] == ["sqli"]

    methodology_doc = tmp_path / "out" / "htb-trick-methodology.md"
    assert methodology_doc.exists()
    assert methodology_doc in result.generated_files
    methodology_text = methodology_doc.read_text(encoding="utf-8")
    assert "Source type: 0xdf_writeup" not in methodology_text
    assert "Source URL:" not in methodology_text
    overlay_manifest = json.loads((tmp_path / "out" / ".manifest.json").read_text(encoding="utf-8"))
    assert overlay_manifest["writeups"][0]["source_url"] == (
        "https://0xdf.gitlab.io/2022/10/29/htb-trick.html"
    )
