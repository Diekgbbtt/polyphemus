from pathlib import Path

from lightrag_docprep.cli import main


def test_cli_processes_markdown_and_returns_zero(tmp_path: Path, capsys):
    source = tmp_path / "sample.md"
    source.write_text("# Sample\n\nBody", encoding="utf-8")
    output = tmp_path / "out"

    code = main([str(source), "--output", str(output)])

    captured = capsys.readouterr()
    assert code == 0
    assert "OK" in captured.out
    created = list(output.glob("*/document.md"))
    assert len(created) == 1


def test_cli_returns_nonzero_if_any_source_fails(tmp_path: Path, capsys):
    source = tmp_path / "unsupported.zip"
    source.write_bytes(b"x")

    code = main([str(source), "--output", str(tmp_path / "out")])

    captured = capsys.readouterr()
    assert code == 1
    assert "ERROR" in captured.out


def test_cli_expands_directory_recursively(tmp_path: Path, capsys):
    source_dir = tmp_path / "sources"
    nested = source_dir / "nested"
    nested.mkdir(parents=True)
    (source_dir / "one.md").write_text("# One\n\nBody", encoding="utf-8")
    (nested / "two.html").write_text("<main><h1>Two</h1><p>Body</p></main>", encoding="utf-8")
    (nested / "ignore.zip").write_bytes(b"x")
    output = tmp_path / "out"

    code = main([str(source_dir), "--profile", "generic", "--output", str(output)])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.count("OK") == 2
    assert len(list(output.glob("*/document.md"))) == 2


def test_cli_accepts_url_as_only_argument_and_uses_default_output(tmp_path: Path, capsys, monkeypatch):
    import threading
    from contextlib import contextmanager
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    @contextmanager
    def server():
        body = b"<html><body><main><h1>CLI Web</h1><p>Fetched from URL.</p></main></body></html>"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                return

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{httpd.server_port}/article"
        finally:
            httpd.shutdown()
            thread.join()
            httpd.server_close()

    monkeypatch.chdir(tmp_path)
    with server() as url:
        code = main([url])

    captured = capsys.readouterr()
    assert code == 0
    assert "OK" in captured.out
    created = list((tmp_path / "normalized").glob("*/document.md"))
    assert len(created) == 1
    assert "Fetched from URL." in created[0].read_text()
