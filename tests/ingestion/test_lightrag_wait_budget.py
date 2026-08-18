import math

import pytest

from polymerhus.ingestion.lightrag_adapter import (
    LightRAGAdapterError,
    LightRAGIngestionAdapter,
)
from polymerhus.ingestion.service import IngestionService, SourceStatus


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


class FakeSleep:
    def __init__(self, clock: FakeClock):
        self.clock = clock
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        self.clock.now += seconds


class FakeClient:
    def __init__(
        self,
        *,
        upload: dict,
        statuses: list[dict],
        clock: FakeClock | None = None,
        advance_per_status: float = 0.0,
    ):
        self.upload_payload = upload
        self.statuses = list(statuses)
        self.tracked: list[str] = []
        self.clock = clock
        self.advance_per_status = advance_per_status

    def upload_file(self, source_path):
        return self.upload_payload

    def track_status(self, track_id: str):
        if self.clock is not None:
            self.clock.now += self.advance_per_status
        self.tracked.append(track_id)
        return self.statuses.pop(0)


def _document(tmp_path):
    document = tmp_path / "document.md"
    document.write_text("# Methodology\n", encoding="utf-8")
    return document


def test_deadline_mode_polls_past_legacy_120_seconds_and_succeeds(tmp_path):
    clock = FakeClock(0.0)
    sleep = FakeSleep(clock)
    client = FakeClient(
        upload={"track_id": "track-1"},
        statuses=[{"status": "processing"}] * 61
        + [{"status": "processed", "document_id": "doc-1"}],
    )
    adapter = LightRAGIngestionAdapter(
        client=client,
        poll_interval_seconds=2.0,
        timeout_seconds=1800.0,
        monotonic=clock,
        sleep_fn=sleep,
    )

    result = adapter.ingest_markdown(_document(tmp_path), source_key="file:inbox/example.md")

    assert result.document_id == "doc-1"
    assert len(client.tracked) == 62
    assert clock.now >= 120.0


def test_terminal_failed_stops_immediately_and_is_sanitized(tmp_path):
    clock = FakeClock(0.0)
    sleep = FakeSleep(clock)
    client = FakeClient(
        upload={"track_id": "track-1"},
        statuses=[
            {
                "status": "failed",
                "error": "C[3/3]: doc-1-chunk-001: extract LLM func: "
                "Worker execution timeout after 360s /secret/path",
            }
        ],
    )
    adapter = LightRAGIngestionAdapter(
        client=client,
        poll_interval_seconds=2.0,
        timeout_seconds=1800.0,
        monotonic=clock,
        sleep_fn=sleep,
    )

    with pytest.raises(LightRAGAdapterError) as exc:
        adapter.ingest_markdown(_document(tmp_path), source_key="file:inbox/example.md")

    assert exc.value.code == "LIGHTRAG_INGESTION_FAILED"
    assert str(exc.value) == "LightRAG ingestion failed"
    assert "360" not in str(exc.value)
    assert "chunk" not in str(exc.value)
    assert "/secret" not in str(exc.value)
    assert client.tracked == ["track-1"]
    assert sleep.calls == []
    assert clock.now == 0.0


def test_deadline_mode_never_sleeps_past_remaining_deadline(tmp_path):
    clock = FakeClock(0.0)
    sleep = FakeSleep(clock)
    client = FakeClient(
        upload={"track_id": "track-1"},
        statuses=[{"status": "processing"}] * 6,
    )
    adapter = LightRAGIngestionAdapter(
        client=client,
        poll_interval_seconds=2.0,
        timeout_seconds=5.0,
        monotonic=clock,
        sleep_fn=sleep,
    )

    with pytest.raises(LightRAGAdapterError) as exc:
        adapter.ingest_markdown(_document(tmp_path), source_key="file:inbox/example.md")

    assert exc.value.code == "LIGHTRAG_TIMEOUT"
    assert sleep.calls == [2.0, 2.0, 1.0]
    assert clock.now == 5.0


def test_deadline_exhaustion_raises_stable_timeout(tmp_path):
    clock = FakeClock(0.0)
    sleep = FakeSleep(clock)
    client = FakeClient(
        upload={"track_id": "track-1"},
        statuses=[{"status": "processing"}] * 3,
    )
    adapter = LightRAGIngestionAdapter(
        client=client,
        poll_interval_seconds=2.0,
        timeout_seconds=0.1,
        monotonic=clock,
        sleep_fn=sleep,
    )

    with pytest.raises(LightRAGAdapterError) as exc:
        adapter.ingest_markdown(_document(tmp_path), source_key="file:inbox/example.md")

    assert exc.value.code == "LIGHTRAG_TIMEOUT"
    assert exc.value.retryable is True
    assert str(exc.value) == "LightRAG did not reach a terminal status before timeout"


def test_adapter_rejects_both_limits_supplied():
    with pytest.raises(ValueError):
        LightRAGIngestionAdapter(
            client=FakeClient(upload={"track_id": "t"}, statuses=[]),
            timeout_seconds=1800.0,
            max_poll_attempts=60,
        )


def test_default_construction_selects_1800_second_deadline():
    adapter = LightRAGIngestionAdapter(
        client=FakeClient(upload={"track_id": "t"}, statuses=[])
    )

    assert adapter.timeout_seconds == 1800.0
    assert adapter.max_poll_attempts is None


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
def test_adapter_rejects_invalid_timeout(bad):
    with pytest.raises(ValueError):
        LightRAGIngestionAdapter(
            client=FakeClient(upload={"track_id": "t"}, statuses=[]),
            timeout_seconds=bad,
        )


def test_legacy_attempts_mode_is_used_only_when_explicit(tmp_path):
    client = FakeClient(
        upload={"track_id": "track-1"},
        statuses=[{"status": "processing"}, {"status": "processing"}],
    )
    adapter = LightRAGIngestionAdapter(
        client=client,
        poll_interval_seconds=0,
        max_poll_attempts=2,
    )

    with pytest.raises(LightRAGAdapterError) as exc:
        adapter.ingest_markdown(_document(tmp_path), source_key="file:inbox/example.md")

    assert exc.value.code == "LIGHTRAG_TIMEOUT"
    assert len(client.tracked) == 2
    assert adapter.max_poll_attempts == 2
    assert adapter.timeout_seconds is None


def test_no_status_request_at_or_after_deadline(tmp_path):
    clock = FakeClock(0.0)
    sleep = FakeSleep(clock)
    client = FakeClient(
        upload={"track_id": "track-1"},
        statuses=[{"status": "processing"}] * 6,
    )
    adapter = LightRAGIngestionAdapter(
        client=client,
        poll_interval_seconds=2.0,
        timeout_seconds=5.0,
        monotonic=clock,
        sleep_fn=sleep,
    )

    with pytest.raises(LightRAGAdapterError) as exc:
        adapter.ingest_markdown(_document(tmp_path), source_key="file:inbox/example.md")

    assert exc.value.code == "LIGHTRAG_TIMEOUT"
    assert sleep.calls == [2.0, 2.0, 1.0]
    assert len(client.tracked) == 3
    assert clock.now == 5.0


def test_in_flight_nonterminal_finishing_past_deadline_times_out_without_another_request(tmp_path):
    clock = FakeClock(0.0)
    sleep = FakeSleep(clock)
    client = FakeClient(
        upload={"track_id": "track-1"},
        statuses=[{"status": "processing"}, {"status": "processing"}],
        clock=clock,
        advance_per_status=10.0,
    )
    adapter = LightRAGIngestionAdapter(
        client=client,
        poll_interval_seconds=2.0,
        timeout_seconds=5.0,
        monotonic=clock,
        sleep_fn=sleep,
    )

    with pytest.raises(LightRAGAdapterError) as exc:
        adapter.ingest_markdown(_document(tmp_path), source_key="file:inbox/example.md")

    assert exc.value.code == "LIGHTRAG_TIMEOUT"
    assert len(client.tracked) == 1
    assert sleep.calls == []


def test_in_flight_terminal_success_finishing_past_deadline_is_accepted(tmp_path):
    clock = FakeClock(0.0)
    sleep = FakeSleep(clock)
    client = FakeClient(
        upload={"track_id": "track-1"},
        statuses=[{"status": "processed", "document_id": "doc-1"}],
        clock=clock,
        advance_per_status=10.0,
    )
    adapter = LightRAGIngestionAdapter(
        client=client,
        poll_interval_seconds=2.0,
        timeout_seconds=5.0,
        monotonic=clock,
        sleep_fn=sleep,
    )

    result = adapter.ingest_markdown(_document(tmp_path), source_key="file:inbox/example.md")

    assert result.document_id == "doc-1"
    assert result.status == "processed"
    assert len(client.tracked) == 1
    assert sleep.calls == []


def test_in_flight_terminal_failure_finishing_past_deadline_is_sanitized(tmp_path):
    clock = FakeClock(0.0)
    sleep = FakeSleep(clock)
    client = FakeClient(
        upload={"track_id": "track-1"},
        statuses=[
            {
                "status": "failed",
                "error": "C[3/3]: doc-1-chunk-001: extract LLM func: "
                "Worker execution timeout after 360s /secret/path",
            }
        ],
        clock=clock,
        advance_per_status=10.0,
    )
    adapter = LightRAGIngestionAdapter(
        client=client,
        poll_interval_seconds=2.0,
        timeout_seconds=5.0,
        monotonic=clock,
        sleep_fn=sleep,
    )

    with pytest.raises(LightRAGAdapterError) as exc:
        adapter.ingest_markdown(_document(tmp_path), source_key="file:inbox/example.md")

    assert exc.value.code == "LIGHTRAG_INGESTION_FAILED"
    assert str(exc.value) == "LightRAG ingestion failed"
    assert len(client.tracked) == 1
    assert sleep.calls == []


def test_from_config_wires_configured_deadline(monkeypatch):
    import polymerhus.app.config as config_module

    monkeypatch.setattr(config_module.config, "LIGHTRAG_INGESTION_TIMEOUT_SECONDS", 3600.5)
    monkeypatch.setattr(config_module.config, "LIGHTRAG_POLL_INTERVAL_SECONDS", 0.5)

    service = IngestionService.from_config()
    adapter = service.lightrag_adapter

    assert adapter.timeout_seconds == 3600.5
    assert adapter.poll_interval_seconds == 0.5
    assert adapter.max_poll_attempts is None


def test_public_job_error_payload_never_exposes_raw_lightrag_text(monkeypatch, tmp_path):
    import polymerhus.ingestion.service as service_module

    calls: list[tuple] = []
    monkeypatch.setattr(
        service_module.pg,
        "set_ingestion_job_status",
        lambda job_id, status, audit=None, error=None: calls.append((job_id, status, error)),
    )
    client = FakeClient(
        upload={"track_id": "track-1"},
        statuses=[
            {
                "status": "failed",
                "error": "C[3/3]: doc-1-chunk-001: extract LLM func: "
                "Worker execution timeout after 360s /secret/path",
            }
        ],
    )
    adapter = LightRAGIngestionAdapter(
        client=client,
        poll_interval_seconds=0.0,
        timeout_seconds=1800.0,
    )

    with pytest.raises(LightRAGAdapterError) as exc:
        adapter.ingest_markdown(_document(tmp_path), source_key="file:inbox/example.md")

    service = IngestionService(
        ingestion_root=tmp_path / "ingestion",
        normalized_root=tmp_path / "normalized",
        lightrag_adapter=adapter,
    )
    service._fail_job("job-1", exc.value.code, str(exc.value), SourceStatus.INGESTING)

    error_payload = calls[0][2]
    assert error_payload["code"] == "LIGHTRAG_INGESTION_FAILED"
    assert error_payload["message"] == "LightRAG ingestion failed"
    assert error_payload["stage"] == "INGESTING"
    assert "360" not in str(error_payload)
    assert "/secret" not in str(error_payload)
    assert "chunk" not in str(error_payload)
