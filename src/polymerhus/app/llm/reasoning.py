"""The client-side reasoning-replay pipeline (#109 - T6 of the #100 gateway programme).

Realises ADR D11 items 3-4 (reasoning-replay caveat, grilled 2026-08-11): for
the stateful thinking roles, reasoning tokens that the provider SENT in a
response must be RE-PLAYED into the next turn's message history so the next
turn's request prefix is byte-identical and provider-native KV caching can hit
(fact D8.1: the KV cache lives only at the provider - the client only
influences hit rate via byte-identical prefixes).

Four responsibilities (the ticket's pipeline steps):

1. **PARSE** (`extract_reasoning`): extract reasoning from each response per
   the T3 profile (`reasoning_in_response` + `reasoning_field` from
   `capability.py`; profile unknown -> NO parse, gap logged). The field
   semantics are the ratified D11 item-5 surfaces:
   `reasoning_content` reads at message level (wire dict) /
   `additional_kwargs` level (AIMessage, the surface langchain_core's own
   `_extract_reasoning_from_additional_kwargs` reads), and `reasoning_details`
   reads via `provider_specific_fields.reasoning_details` (the surface litellm
   1.96.0 relocates non-schema message keys to - verified in
   `tests/test_gateway_reasoning_passthrough.py`). The extractor is TOLERANT
   of SDK-shape variance (`response_metadata` too) and returns None + gap log
   otherwise.

2. **REPLAY** (`attach_reasoning` + `replay_assistant_reasoning`): the
   assistant message that carried reasoning is re-persisted with the reasoning
   content included, BYTE-IDENTICAL (the seam performs the re-persist via
   `update_state`, so the NEXT turn restores the replay-ready prefix).
   Encrypted reasoning is replayed as well - the opaque payload attaches
   verbatim, never decrypted, never skipped (D11 item 4); readability is
   tracked, not gating.

3. **CACHE-TRACK** (`cached_tokens`): `usage.cached_tokens` arrives as
   `usage_metadata.input_token_details.cache_read` (langchain-openai maps the
   provider's `prompt_tokens_details.cached_tokens` there). Tracked as
   OBSERVABILITY ONLY - never gating, never on the #73 retry/timeout axis
   (D7). The D11 grey-point heuristic (interleaved + shape + cache-presence,
   explicitly low-confidence) is recorded as `heuristic`, never a gate.

4. **LANGFUSE READABILITY** (`readability` + `reasoning_readability_metadata`):
   a dedicated `reasoning_readability` field for the langfuse llm-response
   metadata the session seam feeds the Langfuse CallbackHandler (the app's
   existing integration point, `get_langfuse_callbacks` + the config metadata
   in `session._observe_config`). Fail-open: any failure degrades to no field.

Importing this module performs no I/O and requires no env var (CODING_STANDARD
section 6, D10: no litellm import - the gateway surface is consumed only via
the T3 reader).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage

from polymerhus.app.llm.capability import CapabilityProfile

logger = logging.getLogger(__name__)

# The two ratified field values (D11 item 1; the passthrough test constants).
SURFACE_REASONING_CONTENT = "reasoning_content"
SURFACE_REASONING_DETAILS = "reasoning_details"

# The `provider_specific_fields` relocation container litellm uses for
# non-schema response message keys (ratified surface, D11 item 5 amendment).
PROVIDER_SPECIFIC_FIELDS = "provider_specific_fields"

# The low-confidence D11 grey-point heuristic marker (interleaved + shape +
# cache-presence). Recorded as heuristic; NEVER a capability gate.
HEURISTIC_CACHE_EVIDENCE = "interleaved+shape+cache-presence"

# The readability field values recorded on the langfuse llm-response metadata.
READABILITY_REPLAYED = "replayed"
READABILITY_ABSENT = "absent"


@dataclass(frozen=True)
class ParsedReasoning:
    """One parsed reasoning payload.

    - `reasoning`: the value BYTE-IDENTICAL to what the response carried
      (`str`, or an opaque encrypted payload dict - never decoded).
    - `surface`: which ratified field the value came from
      (`reasoning_content` | `reasoning_details`).
    - `encrypted`: True when the value is NOT a plain string (D11 item 4:
      replayed regardless - readability tracked, never skipping).
    """

    reasoning: Any
    surface: str
    encrypted: bool


def _value(result: Any, surface: str) -> ParsedReasoning | None:
    """Wrap a raw field value; None/empty is absent (nothing to replay
    byte-identically), anything else - including opaque encrypted payloads -
    is a parsed value kept verbatim."""
    if result is None or result == "":
        return None
    return ParsedReasoning(reasoning=result, surface=surface,
                           encrypted=not isinstance(result, str))


def _dict_field(message: dict, surface: str) -> ParsedReasoning | None:
    """The wire-shaped message level: `reasoning_content` first-class, and
    `reasoning_details` under the ratified `provider_specific_fields`
    relocation container."""
    if surface == SURFACE_REASONING_CONTENT:
        return _value(message.get(SURFACE_REASONING_CONTENT), surface)
    provider_fields = message.get(PROVIDER_SPECIFIC_FIELDS)
    if isinstance(provider_fields, dict):
        return _value(provider_fields.get(surface), surface)
    return None


def _ai_field(message: AIMessage, surface: str) -> ParsedReasoning | None:
    """The AIMessage surfaces, tolerant of SDK-shape variance: the canonical
    `additional_kwargs`, the `response_metadata` as a second transport surface,
    and (for `reasoning_content`) the langchain-core blessed content block
    `{"type": "reasoning", "reasoning": ...}` form."""
    kwargs = message.additional_kwargs or {}
    metadata = message.response_metadata or {}
    if surface == SURFACE_REASONING_CONTENT:
        value = kwargs.get(SURFACE_REASONING_CONTENT)
        if value is None:
            value = metadata.get(SURFACE_REASONING_CONTENT)
        if value is None and isinstance(message.content, list):
            for block in message.content:
                if (isinstance(block, dict) and block.get("type") == "reasoning"
                        and "reasoning" in block):
                    value = block["reasoning"]
                    break
        return _value(value, surface)
    provider_fields = kwargs.get(PROVIDER_SPECIFIC_FIELDS)
    if not isinstance(provider_fields, dict):
        provider_fields = metadata.get(PROVIDER_SPECIFIC_FIELDS)
    if not isinstance(provider_fields, dict):
        return None
    return _value(provider_fields.get(surface), surface)


def _gap(message, profile, surface: str) -> None:
    logger.warning(
        "reasoning gap: profile expects %s (%s) but the response message "
        "carries no matching value (surface absent or wrong field)",
        surface, profile.source or "unknown source")


def extract_reasoning(
    message: BaseMessage | dict,
    profile: CapabilityProfile | None,
) -> ParsedReasoning | None:
    """PARSE: extract reasoning from one response message per the T3 profile.

    Profile gating (the ticket's contract):
    - profile None (D5 Rule 1 unknown) -> NO parse, gap logged.
    - `reasoning_in_response` falsy/None -> NO parse, gap logged.
    - `reasoning_field` names the ONE surface read; a response carrying only
      the OTHER surface is a gap (extract None), never a wrong-surface guess.
    - `reasoning_field` None (D11 item 1 interleaved-style profile) reads
      tolerant: `reasoning_content` first, then `provider_specific_fields`
      (the `_client_side_reasoning` fallback order).

    Accepts either the wire-shaped message dict (litellm/openai shape) or a
    langchain `AIMessage` (where the reasoning lands per the harness's SDK
    version - the current pinned langchain-openai strips the field, so the
    extractor gaps and the seam logs it; a provider subclass or a future SDK
    that preserves it parses here)."""
    if profile is None:
        logger.warning(
            "reasoning gap: capability profile unknown (D5 rule 1) - no "
            "reasoning parse for this response (provenance-gated)")
        return None
    if not profile.reasoning_in_response:
        logger.warning(
            "reasoning gap: profile says reasoning_in_response=%r - no parse "
            "for this response", profile.reasoning_in_response)
        return None

    surface = profile.reasoning_field
    if surface not in (None, SURFACE_REASONING_CONTENT, SURFACE_REASONING_DETAILS):
        logger.warning("reasoning gap: profile carries an unrecognised "
                       "reasoning_field %r - no parse", surface)
        return None
    if isinstance(message, dict):
        if surface is not None:
            parsed = _dict_field(message, surface)
            if parsed is None:
                _gap(message, profile, surface)
            return parsed
        return _dict_field(message, SURFACE_REASONING_CONTENT) or _dict_field(
            message, SURFACE_REASONING_DETAILS)
    if isinstance(message, AIMessage):
        if surface is not None:
            parsed = _ai_field(message, surface)
            if parsed is None:
                _gap(message, profile, surface)
            return parsed
        return _ai_field(message, SURFACE_REASONING_CONTENT) or _ai_field(
            message, SURFACE_REASONING_DETAILS)
    logger.warning("reasoning gap: unhandled response message type %s",
                   type(message).__name__)
    return None


def attach_reasoning(message: BaseMessage, parsed: ParsedReasoning) -> BaseMessage:
    """REPLAY: the assistant message copy that carries the reasoning on the
    canonical replay surface, BYTE-IDENTICAL to what the response carried.

    `reasoning_content` attaches at `additional_kwargs["reasoning_content"]`
    (the blessed client-side surface); `reasoning_details` attaches under
    `additional_kwargs["provider_specific_fields"]["reasoning_details"]` (the
    ratified relocation surface). Existing additional_kwargs are merged, never
    clobbered. Non-assistant messages pass through unchanged."""
    if not isinstance(message, AIMessage):
        return message
    kwargs = dict(message.additional_kwargs)
    if parsed.surface == SURFACE_REASONING_CONTENT:
        kwargs[SURFACE_REASONING_CONTENT] = parsed.reasoning
    else:
        provider_fields = dict(kwargs.get(PROVIDER_SPECIFIC_FIELDS) or {})
        provider_fields[parsed.surface] = parsed.reasoning
        kwargs[PROVIDER_SPECIFIC_FIELDS] = provider_fields
    return message.model_copy(update={"additional_kwargs": kwargs})


def cached_tokens(message: BaseMessage | None) -> int | None:
    """CACHE-TRACK: `usage.cached_tokens` from the message's
    `usage_metadata.input_token_details.cache_read` (the langchain-openai
    mapping of the provider's `prompt_tokens_details.cached_tokens`).
    Observability only - the caller never gates, never retries on it."""
    usage = getattr(message, "usage_metadata", None)
    if not isinstance(usage, dict):
        return None
    details = usage.get("input_token_details")
    if not isinstance(details, dict):
        return None
    value = details.get("cache_read")
    return value if isinstance(value, int) else None


def readability(profile: CapabilityProfile | None, parsed: ParsedReasoning | None) -> str:
    """The readability classification recorded for one response: whether
    reasoning was present / parsed (D11 item 4 - tracked, never gating)."""
    if profile is None:
        return "unknown_profile"
    if not profile.reasoning_in_response:
        return "not_expected"
    return "parsed" if parsed is not None else "gap"


def replay_assistant_reasoning(
    messages: list[BaseMessage],
    profile: CapabilityProfile | None,
) -> tuple[list[BaseMessage] | None, dict]:
    """REPLAY, pure: build the re-persist target for the turn's trail.

    Returns `(replacement, report)`:
    - `replacement`: the message trail with EVERY assistant message that
      carried parseable reasoning re-attached with it (byte-identical
      prefixes; untouched messages keep identity) - None when nothing parsed.
    - `report`: the per-turn observability record - `readability`, `surface`,
      `encrypted`, `cached_tokens` (usage observability), and the `heuristic`
      marker when cache presence coincides with the reasoning profile
      (D11 grey point - low confidence, recorded, never a gate)."""
    report: dict = {"readability": readability(profile, None),
                    "surface": None, "encrypted": None,
                    "cached_tokens": None, "heuristic": None}
    if profile is None:
        logger.warning("reasoning replay skipped: capability profile unknown "
                       "(D5 rule 1) - no re-persist this turn")
        return None, report
    if not profile.reasoning_in_response:
        return None, report

    replacement: list[BaseMessage] = []
    last_parsed: ParsedReasoning | None = None
    changed = False
    for message in messages:
        if not isinstance(message, AIMessage):
            replacement.append(message)
            continue
        parsed = extract_reasoning(message, profile)
        if parsed is None:
            replacement.append(message)
            continue
        last_parsed = parsed
        changed = True
        replacement.append(attach_reasoning(message, parsed))
    if not changed:
        report["readability"] = "gap"
        return None, report

    report["readability"] = readability(profile, last_parsed)
    report["surface"] = last_parsed.surface
    report["encrypted"] = last_parsed.encrypted
    if messages:
        report["cached_tokens"] = cached_tokens(messages[-1])
    if report["cached_tokens"] is not None:
        report["heuristic"] = HEURISTIC_CACHE_EVIDENCE
    return replacement, report


def reasoning_readability_metadata(messages: list) -> dict:
    """The D11 item-4 langfuse llm-response field: the `reasoning_readability`
    entry derived from a PERSISTED thread's last assistant message - "replayed"
    when the re-persisted reasoning is attached (with its surface + encryption
    flag), "absent" otherwise, omitted when the thread has no assistant message
    yet. Pure and fail-open: the seam merges this into the config metadata the
    Langfuse CallbackHandler records."""
    assistant = [m for m in messages if isinstance(m, AIMessage)]
    if not assistant:
        return {}
    last = assistant[-1]
    parsed = None
    kwargs = last.additional_kwargs or {}
    if kwargs.get(SURFACE_REASONING_CONTENT) is not None:
        parsed = _value(kwargs.get(SURFACE_REASONING_CONTENT), SURFACE_REASONING_CONTENT)
    else:
        provider_fields = kwargs.get(PROVIDER_SPECIFIC_FIELDS)
        if isinstance(provider_fields, dict):
            parsed = _value(provider_fields.get(SURFACE_REASONING_DETAILS),
                            SURFACE_REASONING_DETAILS)
    if parsed is None:
        return {"reasoning_readability": READABILITY_ABSENT}
    return {
        "reasoning_readability": READABILITY_REPLAYED,
        "reasoning_surface": parsed.surface,
        "reasoning_encrypted": parsed.encrypted,
    }