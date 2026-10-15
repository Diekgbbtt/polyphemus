"""Pin-verification for the gateway's streamed-usage continuity patch.

The gateway pins litellm 1.96.0 (`gateway/requirements.txt`, ADR D10). In that
release, when a provider attaches `usage` to a chunk that ALSO carries choices,
`streaming_handler.py:1463` lands the RAW openai `CompletionUsage` object on the
message and `_usage_chunk_calculation_helper` drops its values: the
`"prompt_tokens" in usage_chunk` membership test and the
`isinstance(..., PromptTokensDetailsWrapper)` checks are false for that object
(`streaming_chunk_builder_utils.py:462-500`). `calculate_usage` then substitutes
a messages-only `token_counter` fallback (`:749`), so a warm streamed call
reports a synthetic prompt size with no `cached_tokens` - measured live through
the local gateway 2026-10-15: `prompt_tokens=3614` streamed vs `7215` with
`cached_tokens=7040` nonstream on the same body and session.

This tier reproduces the loss against the REAL pinned litellm 1.96.0, then pins
`gateway_proxy_bootstrap.install_stream_usage_patch()` as the restoring seam.
A future litellm bump that fixes or moves these internals turns the tests red on
purpose (the same discipline as the app's langchain-openai subclass). The file
runs in the dev venv (litellm 1.96.0 is importable there) and skips cleanly
otherwise, like `tests/test_gateway_reasoning_passthrough.py`.
"""
from __future__ import annotations

import sys

import pytest

litellm = pytest.importorskip("litellm")

from openai.types.completion_usage import (  # noqa: E402
    CompletionUsage,
    PromptTokensDetails,
)

import polymerhus.app.gateway_proxy_bootstrap as B  # noqa: E402

_MESSAGES = [{"role": "user", "content": "hello world"}]


def _degraded_chunk():
    """The production shape: a finish chunk carrying the raw provider usage."""
    from litellm.types.utils import Delta, ModelResponseStream, StreamingChoices

    chunk = ModelResponseStream(
        id="chatcmpl-pin",
        choices=[
            StreamingChoices(index=0, delta=Delta(content=""), finish_reason="stop")
        ],
    )
    chunk.usage = CompletionUsage(
        completion_tokens=7,
        prompt_tokens=7215,
        total_tokens=7222,
        prompt_tokens_details=PromptTokensDetails(cached_tokens=7040),
    )
    return chunk


def _usage_helper():
    from litellm.litellm_core_utils.streaming_chunk_builder_utils import ChunkProcessor

    processor = ChunkProcessor([_degraded_chunk()], messages=_MESSAGES)
    return processor, processor._usage_chunk_calculation_helper(_degraded_chunk().usage)


def _builder_usage():
    response = litellm.stream_chunk_builder([_degraded_chunk()], messages=_MESSAGES)
    assert response is not None and response.usage is not None
    return response.usage


def test_the_pinned_litellm_loses_the_streamed_cache_detail():
    """RED baseline, first half: on the UNPATCHED pinned release the raw usage
    object's scalars and cache detail are dropped, and the synthesized
    messages-only count (9 for "hello world") replaces the real 7215."""
    from litellm.litellm_core_utils.streaming_chunk_builder_utils import ChunkProcessor

    if getattr(ChunkProcessor, "_polymerhus_stream_usage_patch", False):
        pytest.skip("the patch is already installed in this process")
    _, helper_out = _usage_helper()
    assert helper_out["prompt_tokens"] == 0
    assert helper_out["prompt_tokens_details"] is None
    usage = _builder_usage()
    assert usage.prompt_tokens != 7215
    assert usage.prompt_tokens_details is None


def test_installing_the_patch_restores_the_streamed_cache_detail():
    """GREEN: after the patch the same chunk reports the provider's real
    spectrum - prompt size, cache read, and completion count."""
    assert B.install_stream_usage_patch() is True
    _, helper_out = _usage_helper()
    assert helper_out["prompt_tokens"] == 7215
    assert helper_out["completion_tokens"] == 7
    assert helper_out["prompt_tokens_details"].cached_tokens == 7040
    usage = _builder_usage()
    assert usage.prompt_tokens == 7215
    assert usage.completion_tokens == 7
    assert usage.total_tokens == 7222
    assert usage.prompt_tokens_details is not None
    assert usage.prompt_tokens_details.cached_tokens == 7040


def test_the_patch_is_idempotent():
    assert B.install_stream_usage_patch() is True
    assert B.install_stream_usage_patch() is True
    from litellm.litellm_core_utils.streaming_chunk_builder_utils import ChunkProcessor

    assert getattr(ChunkProcessor, "_polymerhus_stream_usage_patch", False) is True


def test_the_patch_is_fail_open_when_the_internal_moved(monkeypatch):
    """A future litellm whose internals moved must never stop the relay from
    booting: install() logs and returns False."""
    monkeypatch.setitem(
        sys.modules, "litellm.litellm_core_utils.streaming_chunk_builder_utils", None)
    assert B.install_stream_usage_patch() is False


def test_main_installs_the_patch_before_serving(monkeypatch):
    """The bootstrap's order: patch first, then the litellm CLI, with the
    original argv preserved for the CLI (program name restored)."""
    calls: list[str] = []
    monkeypatch.setattr(B, "install_stream_usage_patch",
                        lambda: calls.append("install") or True)
    monkeypatch.setattr(litellm, "run_server", lambda: calls.append("serve"))
    monkeypatch.setattr(sys, "argv", list(sys.argv))
    argv = ["--config", "/srv/gateway/litellm_config.yaml",
            "--host", "127.0.0.1", "--port", "4000"]
    B.main(argv)
    assert calls == ["install", "serve"]
    assert sys.argv == ["litellm", *argv]
