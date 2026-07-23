"""TDD for large-tool-output truncation + the 60s export timeout.

Context: on heavy phase-4 tools (katana, ffuf, steel_crawl) the full tool
stdout/observation becomes a single Langfuse span input/output attribute.
A ~1136-asset katana dump is hundreds of KB (up to low MB with rich `-jsonl`
lines); batched together these oversized spans exhaust the OTLP exporter's
shared retry/timeout budget and the batch is dropped ("Failed to export span
batch due to timeout, max retries or shutdown"). Light phases (whois, httpx,
naabu, subdomain_takeover) emit small payloads and land fine.

Fix under test:
  1. Truncate any per-attribute payload above a HIGH cap (default 256 KiB,
     env-overridable) BEFORE it becomes a span attribute, via the Langfuse
     `mask` hook, appending a clear `...[truncated N bytes]` marker.
  2. Raise the default export timeout to 60s.
  3. Verify our configured span exporter is actually the one in effect
     (guard against the Langfuse resource-manager singleton silently
     returning a pre-existing client whose exporter is NOT ours).

None of these tests touch the network or require `langfuse`/`langchain`.
"""
from __future__ import annotations

import json

from polymerhus.app.observability.langfuse_tracing import (
    _DEFAULT_EXPORT_TIMEOUT_S,
    _DEFAULT_MAX_ATTRIBUTE_BYTES,
    _active_span_exporter,
    _make_truncating_mask,
    _truncate_attribute,
    _verify_configured_exporter_in_effect,
)


def test_default_export_timeout_is_60s():
    assert _DEFAULT_EXPORT_TIMEOUT_S == 60.0


def test_default_attribute_cap_is_256_kib_and_well_under_langfuse_5mb():
    assert _DEFAULT_MAX_ATTRIBUTE_BYTES == 256 * 1024
    # Comfortably under Langfuse's documented 5 MB request limit.
    assert _DEFAULT_MAX_ATTRIBUTE_BYTES < 5 * 1024 * 1024


def test_small_payload_passes_through_unchanged():
    # A light-phase-sized payload (structure preserved, not stringified).
    data = {"tool": "httpx", "results": [{"url": "https://x", "status": 200}]}
    assert _truncate_attribute(data, cap_bytes=_DEFAULT_MAX_ATTRIBUTE_BYTES) is data


def test_string_under_cap_passes_through_unchanged():
    data = "a" * 1000
    assert _truncate_attribute(data, cap_bytes=4096) == data


def test_large_payload_is_truncated_to_cap_with_marker():
    cap = 4096
    # A katana-shaped oversized string well above the cap.
    original = "X" * (cap * 4)
    original_bytes = len(original.encode("utf-8"))

    out = _truncate_attribute(original, cap_bytes=cap)

    assert isinstance(out, str)
    assert out.startswith("X" * 10)  # keeps the head of the payload
    # Kept body is capped; marker names exactly how many bytes were dropped.
    dropped = original_bytes - cap
    assert f"...[truncated {dropped} bytes]" in out
    # The retained body (excluding the marker) must not exceed the cap.
    body = out.rsplit("...[truncated", 1)[0]
    assert len(body.encode("utf-8")) <= cap


def test_large_structured_payload_is_serialized_then_truncated():
    cap = 2048
    # A big list of asset dicts, as katana/steel_crawl would produce.
    data = [{"url": f"https://app.example.com/path/{i}", "status": 200} for i in range(5000)]
    serialized_len = len(json.dumps(data, default=str).encode("utf-8"))
    assert serialized_len > cap  # precondition: genuinely oversized

    out = _truncate_attribute(data, cap_bytes=cap)

    assert isinstance(out, str)
    assert "...[truncated" in out
    body = out.rsplit("...[truncated", 1)[0]
    assert len(body.encode("utf-8")) <= cap


def test_truncation_is_utf8_safe_at_the_boundary():
    cap = 100
    # Multi-byte chars straddling the byte cap must not raise / must round-trip.
    original = "é" * 500  # each 'é' is 2 bytes in UTF-8
    out = _truncate_attribute(original, cap_bytes=cap)
    # Must be valid text and encodable (no lone surrogate / broken sequence).
    out.encode("utf-8")
    assert "...[truncated" in out


def test_truncating_mask_factory_applies_the_cap():
    mask = _make_truncating_mask(cap_bytes=1024)
    big = "Y" * 8192
    out = mask(data=big)
    assert "...[truncated" in out
    body = out.rsplit("...[truncated", 1)[0]
    assert len(body.encode("utf-8")) <= 1024


def test_truncating_mask_passes_small_data_through():
    mask = _make_truncating_mask(cap_bytes=1024)
    small = {"k": "v"}
    assert mask(data=small) is small


def test_truncating_mask_accepts_extra_kwargs_and_never_raises_on_unserializable():
    mask = _make_truncating_mask(cap_bytes=8)

    class _Unserializable:
        def __repr__(self):
            return "R" * 100

    # Langfuse calls mask(data=..., **kwargs); extra kwargs must be tolerated,
    # and a non-JSON-serializable object must degrade (str fallback), not raise.
    out = mask(data=_Unserializable(), field="output")
    assert "...[truncated" in out


class _FakeResources:
    def __init__(self, span_exporter):
        self.span_exporter = span_exporter


class _FakeClient:
    def __init__(self, span_exporter):
        self._resources = _FakeResources(span_exporter)


def test_active_span_exporter_reads_the_resource_manager_exporter():
    sentinel = object()
    assert _active_span_exporter(_FakeClient(sentinel)) is sentinel


def test_verify_exporter_in_effect_true_when_identity_matches():
    ours = object()
    assert _verify_configured_exporter_in_effect(_FakeClient(ours), ours) is True


def test_verify_exporter_in_effect_false_when_singleton_returned_another_exporter():
    ours = object()
    preexisting = object()
    # Simulates the resource-manager singleton hazard: some other code built a
    # Langfuse client for this public_key first, so our span_exporter was
    # discarded and a different exporter is actually in effect.
    assert _verify_configured_exporter_in_effect(_FakeClient(preexisting), ours) is False


def test_verify_exporter_in_effect_is_fail_open_on_odd_client():
    # A client missing the private attribute must not raise; treat as "unknown".
    assert _verify_configured_exporter_in_effect(object(), object()) is False
