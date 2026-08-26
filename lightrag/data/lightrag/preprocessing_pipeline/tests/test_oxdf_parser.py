from pathlib import Path

import pytest

from lightrag_docprep.parsers.oxdf import OxdfParser


@pytest.mark.asyncio
async def test_oxdf_parser_keeps_article_and_removes_site_chrome(tmp_path: Path):
    source = tmp_path / "2024-01-01-htb-example.html"
    source.write_text(
        """<!doctype html>
<html><head>
<title>HTB: Example | 0xdf hacks stuff</title>
<link rel="canonical" href="https://0xdf.gitlab.io/2024/01/01/htb-example.html">
<meta property="article:published_time" content="2024-01-01T12:00:00Z">
</head><body>
<nav>Home About Tags Buy me a coffee</nav>
<article>
<h1 class="post-title">HTB: Example</h1>
<div class="post-tags"><a class="post-tag">jwt</a><a class="post-tag">linux</a></div>
<div class="toc">TOC <a href="#recon">Recon</a></div>
<p>Reusable technical introduction.</p>
<h2 id="recon">Recon</h2>
<p>Nmap finds SSH and HTTP.</p>
<pre><code>line one\n  indented line\nline three</code></pre>
</article>
<footer>0xdf hacks stuff CTF solutions</footer>
</body></html>""",
        encoding="utf-8",
    )

    raw = await OxdfParser().parse(source)

    assert raw.source_profile == "0xdf"
    assert raw.title_candidate == "HTB: Example"
    assert raw.native_metadata["canonical_url"] == "https://0xdf.gitlab.io/2024/01/01/htb-example.html"
    assert raw.native_metadata["publication_date"] == "2024-01-01T12:00:00Z"
    assert raw.native_metadata["tags"] == ["jwt", "linux"]
    assert "Home About Tags" not in raw.markdown
    assert "Buy me a coffee" not in raw.markdown
    assert "TOC" not in raw.markdown
    assert "post-tag" not in raw.markdown
    assert "Reusable technical introduction." in raw.markdown
    assert "## Recon" in raw.markdown
    assert "```" in raw.markdown
    assert "line one\n  indented line\nline three" in raw.markdown


@pytest.mark.asyncio
async def test_oxdf_parser_falls_back_to_main_when_article_is_absent(tmp_path: Path):
    source = tmp_path / "writeup.html"
    source.write_text(
        "<html><body><nav>noise</nav><main><h1>HTB: Main</h1><p>Body</p></main></body></html>",
        encoding="utf-8",
    )

    raw = await OxdfParser().parse(source)

    assert raw.title_candidate == "HTB: Main"
    assert "noise" not in raw.markdown
    assert "Body" in raw.markdown
