import pytest

from agent.lightrag.ingest import ingest_approved_sources, is_approved_source_path


class FakeLightRAGClient:
    def __init__(self):
        self.sources = []

    def ingest_source(self, source_path):
        self.sources.append(source_path)
        return {"inserted": source_path}


def test_ingest_approved_source_passes_path_to_client(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    source = approved / "guide.md"
    source.write_text("methodology note", encoding="utf-8")
    client = FakeLightRAGClient()

    result = ingest_approved_sources(
        [source],
        lightrag_client=client,
        approved_sources=[approved],
    )

    assert client.sources == [str(source.resolve())]
    assert result[0]["source_path"] == str(source.resolve())


def test_unapproved_source_is_rejected(tmp_path):
    approved = tmp_path / "approved"
    unapproved = tmp_path / "unapproved"
    approved.mkdir()
    unapproved.mkdir()
    source = unapproved / "guide.md"
    source.write_text("methodology note", encoding="utf-8")

    assert is_approved_source_path(source, [approved]) is False
    with pytest.raises(ValueError):
        ingest_approved_sources([source], lightrag_client=FakeLightRAGClient(), approved_sources=[approved])


def test_missing_approved_source_fails_before_client_call(tmp_path):
    approved = tmp_path / "approved"
    approved.mkdir()
    missing = approved / "missing.md"
    client = FakeLightRAGClient()

    with pytest.raises(FileNotFoundError):
        ingest_approved_sources([missing], lightrag_client=client, approved_sources=[approved])
    assert client.sources == []
