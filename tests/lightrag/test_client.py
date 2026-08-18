import httpx

from polymerhus.lightrag.client import LightRAGHttpClient


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


def test_build_lightrag_clients_uses_distinct_base_and_writeup_urls(monkeypatch):
    import importlib

    import polymerhus.app.config as config_module
    import polymerhus.lightrag.client as client_module

    with monkeypatch.context() as m:
        m.setenv("LIGHTRAG_BASE_API_URL", "http://base:9621")
        m.setenv("LIGHTRAG_WRITEUP_API_URL", "http://writeups:9621")
        m.setenv("LIGHTRAG_API_KEY", "secret")
        m.setenv("LIGHTRAG_TIMEOUT_SECONDS", "7")
        importlib.reload(config_module)

        clients = client_module.build_lightrag_clients()

        assert clients["base"].base_url == "http://base:9621"
        assert clients["writeups"].base_url == "http://writeups:9621"
        assert clients["base"].api_key == "secret"
        assert clients["writeups"].api_key == "secret"
        assert clients["base"].timeout == 7
        assert clients["writeups"].timeout == 7

    importlib.reload(config_module)


def test_client_clear_cache_sends_empty_json_body(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["json"] = kwargs["json"]
        return _response("POST", url, {"status": "success"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = LightRAGHttpClient("http://localhost:9621", timeout=3)

    assert client.clear_cache() == {"status": "success"}
    assert seen == {
        "url": "http://localhost:9621/documents/clear_cache",
        "json": {},
    }


def test_client_reprocess_failed_uses_reprocess_endpoint(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["headers"] = kwargs["headers"]
        return _response("POST", url, {"status": "reprocessing_started"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = LightRAGHttpClient("http://localhost:9621", api_key="secret", timeout=3)

    assert client.reprocess_failed() == {"status": "reprocessing_started"}
    assert seen == {
        "url": "http://localhost:9621/documents/reprocess_failed",
        "headers": {"X-API-Key": "secret"},
    }


def test_client_cancel_pipeline_uses_cancel_endpoint(monkeypatch):
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["json"] = kwargs["json"]
        return _response("POST", url, {"status": "cancellation_requested"})

    monkeypatch.setattr(httpx, "post", fake_post)
    client = LightRAGHttpClient("http://localhost:9621", timeout=3)

    assert client.cancel_pipeline() == {"status": "cancellation_requested"}
    assert seen == {
        "url": "http://localhost:9621/documents/cancel_pipeline",
        "json": {},
    }


def test_client_status_and_delete_entity_endpoints(monkeypatch):
    seen = []

    def fake_get(url, **kwargs):
        seen.append(("GET", url, None))
        return _response("GET", url, {"status_counts": {"processed": 1, "failed": 0, "all": 1}})

    def fake_request(method, url, **kwargs):
        seen.append((method, url, kwargs["json"]))
        return _response(method, url, {"status": "success"})

    monkeypatch.setattr(httpx, "get", fake_get)
    monkeypatch.setattr(httpx, "request", fake_request)
    client = LightRAGHttpClient("http://localhost:9621", timeout=3)

    assert client.status_counts()["status_counts"]["processed"] == 1
    assert client.delete_entity("Wikipedia") == {"status": "success"}
    assert seen == [
        ("GET", "http://localhost:9621/documents/status_counts", None),
        ("DELETE", "http://localhost:9621/documents/delete_entity", {"entity_name": "Wikipedia"}),
    ]


def test_client_paginated_documents_and_delete_document_endpoints(monkeypatch):
    seen = []

    def fake_post(url, **kwargs):
        seen.append(("POST", url, kwargs["json"]))
        return _response("POST", url, {"documents": [], "pagination": {}, "status_counts": {}})

    def fake_request(method, url, **kwargs):
        seen.append((method, url, kwargs["json"]))
        return _response(method, url, {"status": "deletion_started", "doc_id": "doc-1"})

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "request", fake_request)
    client = LightRAGHttpClient("http://localhost:9621", timeout=3)

    assert client.paginated_documents(page=2, page_size=10)["documents"] == []
    assert client.delete_document("doc-1", delete_llm_cache=True)["status"] == "deletion_started"
    assert seen == [
        (
            "POST",
            "http://localhost:9621/documents/paginated",
            {
                "page": 2,
                "page_size": 10,
                "sort_field": "file_path",
                "sort_direction": "asc",
            },
        ),
        (
            "DELETE",
            "http://localhost:9621/documents/delete_document",
            {
                "doc_ids": ["doc-1"],
                "delete_file": False,
                "delete_llm_cache": True,
            },
        ),
    ]
