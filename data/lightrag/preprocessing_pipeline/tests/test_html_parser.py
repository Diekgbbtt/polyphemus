from pathlib import Path

import pytest

from lightrag_docprep.parsers.html import HtmlParser


@pytest.mark.asyncio
async def test_generic_html_prefers_main_content_and_removes_structural_noise(tmp_path: Path):
    source = tmp_path / "guide.html"
    source.write_text(
        """<html><body>
<header>Site Header</header><nav>Menu</nav>
<main><h1>Guide</h1><p>Useful body.</p><aside>Related links</aside><pre>alpha\n beta</pre></main>
<footer>Footer</footer>
</body></html>""",
        encoding="utf-8",
    )

    raw = await HtmlParser().parse(source)

    assert raw.source_profile == "generic"
    assert "# Guide" in raw.markdown
    assert "Useful body." in raw.markdown
    assert "Menu" not in raw.markdown
    assert "Footer" not in raw.markdown
    assert "Related links" not in raw.markdown
    assert "alpha\n beta" in raw.markdown


@pytest.mark.asyncio
async def test_generic_html_falls_back_to_body(tmp_path: Path):
    source = tmp_path / "simple.html"
    source.write_text("<html><body><h1>Title</h1><p>Body fallback.</p></body></html>", encoding="utf-8")

    raw = await HtmlParser().parse(source)

    assert "# Title" in raw.markdown
    assert "Body fallback." in raw.markdown
