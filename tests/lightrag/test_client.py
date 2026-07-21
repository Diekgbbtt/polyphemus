import httpx

from agent.lightrag.client import LightRAGHttpClient


def _response(method: str, url: str, payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload, request=httpx.Request(method, url))


def test_client_health_sends_api_key(monkeypatch):
    seen = {}

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen["headers"] = kwargs["headers"]
        return _response("GET", url, {"status": "ok"})

    monkeypatch.setattr(httpx, "get", fake_get)
    client = LightRAGHttpClient("http://lightrag:9621", api_key="secret", timeout=3)

    assert client.health() == {"status": "ok"}
    assert seen == {
        "url": "http://lightrag:9621/health",
        "headers": {"X-API-Key": "secret"},
    }


def test_client_insert_text_uses_documents_text_endpoint(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["json"] = kwargs["json"]
        return _response("POST", url, {"status": "success", "track_id": "insert-1"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = LightRAGHttpClient("http://localhost:9621", api_key="", timeout=3)

    result = client.insert_text("methodology note", file_source="manual.md")

    assert result["track_id"] == "insert-1"
    assert seen["url"] == "http://localhost:9621/documents/text"
    assert seen["json"] == {"text": "methodology note", "file_source": "manual.md"}


def test_client_uploads_all_files_in_directory(monkeypatch, tmp_path):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    (source_dir / "one.md").write_text("one", encoding="utf-8")
    (source_dir / "two.txt").write_text("two", encoding="utf-8")
    (source_dir / ".hidden").write_text("hidden", encoding="utf-8")
    uploaded = []

    def fake_post(url, **kwargs):
        uploaded.append(kwargs["files"]["file"][0])
        return _response("POST", url, {"status": "success", "track_id": f"upload-{len(uploaded)}"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = LightRAGHttpClient("http://localhost:9621", timeout=3)

    result = client.ingest_source(source_dir)

    assert uploaded == ["one.md", "two.txt"]
    assert [item["response"]["track_id"] for item in result["uploaded"]] == ["upload-1", "upload-2"]


def test_client_query_requests_references_and_chunk_content(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["json"] = kwargs["json"]
        return _response("POST", url, {"response": "answer", "references": []})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = LightRAGHttpClient("http://localhost:9621", timeout=3)

    assert client.query("How does bypass methodology work?", mode="mix")["response"] == "answer"
    assert seen["url"] == "http://localhost:9621/query"
    assert seen["json"]["mode"] == "mix"
    assert seen["json"]["include_references"] is True
    assert seen["json"]["include_chunk_content"] is True
