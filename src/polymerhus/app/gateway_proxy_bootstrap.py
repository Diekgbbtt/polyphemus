"""Gateway proxy bootstrap: restore streamed usage detail, then serve.

The gateway relay pins litellm 1.96.0 (`gateway/requirements.txt`, ADR D10).
In that release the streamed-usage assembly drops the provider's real prompt
size and cache detail whenever the provider attaches `usage` to a chunk that
ALSO carries choices: `streaming_handler.py:1463` lands the raw openai
`CompletionUsage` on the message, and `_usage_chunk_calculation_helper`
(`streaming_chunk_builder_utils.py:462-500`) then reads it with tests that are
false for that object - `"prompt_tokens" in usage_chunk` (a pydantic model's
`__iter__` yields field/value pairs, not keys) and `isinstance(usage_chunk.
prompt_tokens_details, PromptTokensDetailsWrapper)`. The guards drop the real
values, and `calculate_usage` substitutes a messages-only
`token_counter(messages=...)` fallback (`:749`). Measured through the local
gateway 2026-10-15: a warm streamed call reported `prompt_tokens=3614` with no
`prompt_tokens_details`, while the nonstream twin reported `prompt_tokens=7215`
with `cached_tokens=7040`. A usage-ONLY chunk (`choices: []`) takes an earlier
conversion path and keeps the detail - which is why the loss is
time-intermittent and cannot be fixed by the client.

This bootstrap wraps that one method so the values the helper dropped are
restored from the raw object before `calculate_usage` reads them. A streamed
call then reports the same spectrum as a nonstream call, so the app's ledger,
Langfuse, and the eval harness all read one correct number.

Discipline (mirrors the app's own pinned-SDK subclass in
`polymerhus.app.llm.providers`): the patch is pinned to litellm 1.96.0
internals, unit-tested against the real pinned release (so a litellm bump that
moves the internals turns the tests red on purpose), idempotent, and FAIL-OPEN:
a moved internal logs loudly and the relay boots unpatched rather than not at
all. Evidence: `docs/design/cache-spectrum-measurement-research.md`.
"""
from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

__all__ = ["install_stream_usage_patch", "main"]

# Install guard: a re-entry (test + boot, or a re-exec) must never double-wrap.
_PATCH_MARKER = "_polymerhus_stream_usage_patch"

# Scalars `_usage_chunk_calculation_helper` drops when the usage chunk is the
# raw openai object (its membership tests are false for a pydantic model).
_SCALAR_KEYS = (
    "prompt_tokens",
    "completion_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)

# Detail maps the helper reads through `isinstance(..., <litellm wrapper>)`,
# which is false for the raw openai pydantic detail objects.
_DETAIL_KEYS = {
    "prompt_tokens_details": "PromptTokensDetailsWrapper",
    "completion_tokens_details": "CompletionTokensDetails",
}


def _value(usage_chunk: object, key: str):
    if isinstance(usage_chunk, dict):
        return usage_chunk.get(key)
    return getattr(usage_chunk, key, None)


def _coerce_details(value: object, wrapper_name: str):
    """The raw pydantic detail object -> the litellm wrapper the rest of the
    builder (and the proxy's response serializer) expects, or None."""
    if value is None:
        return None
    try:
        import litellm.types.utils as litellm_types

        wrapper = getattr(litellm_types, wrapper_name)
    except Exception:  # noqa: BLE001 - fail-open: leave the value as it is
        return None
    if isinstance(value, wrapper):
        return value
    dump = value.model_dump() if hasattr(value, "model_dump") else value
    if not isinstance(dump, dict):
        return None
    known = {
        key: item
        for key, item in dump.items()
        if key in wrapper.model_fields and item is not None
    }
    try:
        return wrapper(**known)
    except Exception:  # noqa: BLE001 - fail-open: no detail beats a broken turn
        return None


def _restore_dropped_usage(original):
    """Wrap `_usage_chunk_calculation_helper` with the tolerant re-read."""

    def helper(self, usage_chunk):
        result = original(self, usage_chunk)
        for key in _SCALAR_KEYS:
            if not result.get(key):
                restored = _value(usage_chunk, key)
                if restored:
                    result[key] = restored
        for key, wrapper_name in _DETAIL_KEYS.items():
            if result.get(key) is None:
                result[key] = _coerce_details(_value(usage_chunk, key), wrapper_name)
        return result

    return helper


def install_stream_usage_patch() -> bool:
    """Apply the streamed-usage continuity patch to the pinned litellm.

    Idempotent. Fail-open: returns True when the patch is active (either this
    call installed it or a previous one did), False when the pinned internal is
    not there (a litellm bump) - the caller boots regardless."""
    try:
        from litellm.litellm_core_utils.streaming_chunk_builder_utils import (
            ChunkProcessor,
        )

        if getattr(ChunkProcessor, _PATCH_MARKER, False):
            return True
        original = ChunkProcessor._usage_chunk_calculation_helper
        ChunkProcessor._usage_chunk_calculation_helper = _restore_dropped_usage(original)
        setattr(ChunkProcessor, _PATCH_MARKER, True)
        logger.info(
            "streamed-usage continuity patch installed "
            "(_usage_chunk_calculation_helper): streamed cache detail restored")
        return True
    except Exception as exc:  # noqa: BLE001 - fail-open: the relay must boot
        logger.warning(
            "streamed-usage continuity patch unavailable (%s); running "
            "unpatched - a streamed call may report a synthesized, "
            "messages-only prompt size without cache detail", exc)
        return False


def main(argv: list[str] | None = None) -> None:
    """Apply the patch, then run the litellm proxy CLI on `argv` (default
    `sys.argv`). The CLI is the console-script target (`litellm:run_server`);
    the argv rewrite restores the program name click expects."""
    install_stream_usage_patch()
    from litellm import run_server

    if argv is not None:
        sys.argv = ["litellm", *argv]
    run_server()


if __name__ == "__main__":  # pragma: no cover - process entry (`python -m ...`)
    main()
