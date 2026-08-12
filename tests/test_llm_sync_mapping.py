"""Unit tests for the sync mapping layer (T2, #105).

The mapping layer (`polymerhus.app.llm.sync_mapping`) is the ONLY place
product-specific field names live (ADR D5, spec §3.3): it converts a models.dev
resolved model record into the canonical Capability Record (spec §4) and then
into the LiteLLM `model_info` schema per the D5 table, performs the
per-million -> per-token cost unit conversion as a pure function, resolves
`base_model` inheritance BEFORE push (Rule 2), authors the reasoning-replay
surface per the D11 assertion matrix, and decides the registered-name
convention (provider/model slash form, ratified by the operator 2026-08-11).

Every test here is pure - no HTTP, no gateway, no DB. The inputs mirror the
live `https://models.dev/catalog.json` schema (verified against the live feed
2026-08-11).
"""

import pytest

from polymerhus.app.llm import sync_mapping as M


# ---------------------------------------------------------------------------
# Per-million -> per-token unit conversion (D5: pure, unit-tested) ----------
# ---------------------------------------------------------------------------

def test_per_million_to_per_token_1_usd():
    assert M.per_million_to_per_token(1.0) == 0.000001


def test_per_million_to_per_token_fractional():
    # The live deepseek record: input 0.14 USD / 1M tokens -> 0.00000014 / token
    assert M.per_million_to_per_token(0.14) == 0.00000014


def test_per_million_to_per_token_zero():
    assert M.per_million_to_per_token(0.0) == 0.0


def test_per_million_to_per_token_3_2():
    assert M.per_million_to_per_token(3.2) == 0.0000032


# ---------------------------------------------------------------------------
# Registered-name convention (D5 model_id row; operator-ratified 2026-08-11) -
# ---------------------------------------------------------------------------

def test_zen_family_registered_name_strips_to_bare_id():
    # The operator configures opencode:deepseek/deepseek-v4-flash-free; the
    # zen gateway speaks the bare catalog id. In gateway mode the client sends
    # the slash form verbatim; the registered name is provider/bare-id.
    assert M.registered_model_name("opencode", "deepseek-v4-flash-free") == \
        "opencode/deepseek-v4-flash-free"


def test_zen_family_registered_name_strips_prefixed_input():
    # A prefixed id (the app-style form) is stripped to its last segment - the
    # zen strip is idempotent, so the mapping layer owns the translation (D5).
    assert M.registered_model_name("opencode", "deepseek/deepseek-v4-flash-free") == \
        "opencode/deepseek-v4-flash-free"


def test_non_zen_registered_name_is_provider_slash_id():
    assert M.registered_model_name("openai", "gpt-4o") == "openai/gpt-4o"


def test_openrouter_registered_name_keeps_prefixed_id():
    # OpenRouter model ids are themselves prefixed (anthropic/claude-sonnet-4-6);
    # the registered name is provider/model verbatim - no strip outside zen.
    assert M.registered_model_name("openrouter", "anthropic/claude-sonnet-4-6") == \
        "openrouter/anthropic/claude-sonnet-4-6"


def test_zen_native_litellm_model_is_bare_id():
    assert M.native_litellm_model("opencode", "deepseek-v4-flash-free") == \
        "deepseek-v4-flash-free"
    assert M.native_litellm_model("opencode", "deepseek/deepseek-v4-flash-free") == \
        "deepseek-v4-flash-free"


def test_non_zen_native_litellm_model_is_id_verbatim():
    assert M.native_litellm_model("openai", "gpt-4o") == "gpt-4o"
    assert M.native_litellm_model("openrouter", "anthropic/claude-sonnet-4-6") == \
        "anthropic/claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Rule 2: base_model inheritance resolved before push -----------------------
# ---------------------------------------------------------------------------

# A canonical (global) record, as the live catalog.json "models" dict holds.
_BASE_RECORD = {
    "id": "deepseek/deepseek-v4-flash",
    "tool_call": True,
    "reasoning": True,
    "structured_output": True,
    "modalities": {"input": ["text"], "output": ["text"]},
    "limit": {"context": 128000, "output": 32768},
    "cost": {"input": 0.14, "output": 0.28, "cache_read": 0.0028, "cache_write": 0.0},
}

# A provider-scoped override that references the base and overrides cost.
_OVERRIDE_RECORD = {
    "id": "deepseek-v4-flash",
    "name": "DeepSeek V4 Flash",
    "base_model": "deepseek/deepseek-v4-flash",
    "cost": {"input": 0.25, "output": 0.50},
}


def test_inheritance_provider_override_wins_scalar_fields():
    resolved = M.resolve_model_record(
        _OVERRIDE_RECORD, {"deepseek/deepseek-v4-flash": _BASE_RECORD})
    assert resolved["tool_call"] is True  # inherited from base
    assert resolved["limit"]["context"] == 128000  # inherited nested
    assert resolved["cost"]["input"] == 0.25  # provider override wins
    assert resolved["cost"]["output"] == 0.50
    # Un-overridden nested cost fields survive the deep merge (cache prices).
    assert resolved["cost"]["cache_read"] == 0.0028
    # The resolution machinery keys are gone from the result.
    assert "base_model" not in resolved


def test_inheritance_base_model_omit_drops_fields():
    rec = dict(_OVERRIDE_RECORD)
    rec["base_model_omit"] = ["structured_output"]
    resolved = M.resolve_model_record(
        rec, {"deepseek/deepseek-v4-flash": _BASE_RECORD})
    assert "structured_output" not in resolved
    assert resolved["tool_call"] is True


def test_inheritance_missing_base_falls_back_to_provider_record():
    rec = dict(_OVERRIDE_RECORD)
    rec["base_model"] = "nope/does-not-exist"
    resolved = M.resolve_model_record(rec, {})
    # Conservative: fields the provider record omits stay absent (unknown),
    # never guessed from a missing base.
    assert resolved["cost"]["input"] == 0.25  # provider's own override survives
    assert "tool_call" not in resolved  # absent = unknown (Rule 1)
    assert "limit" not in resolved


def test_inheritance_no_base_model_returns_record_verbatim():
    resolved = M.resolve_model_record({"tool_call": True}, {})
    assert resolved == {"tool_call": True}


def test_inheritance_base_provides_all_fields_when_provider_sparse():
    resolved = M.resolve_model_record(
        {"base_model": "deepseek/deepseek-v4-flash"},
        {"deepseek/deepseek-v4-flash": _BASE_RECORD})
    assert resolved["limit"]["context"] == 128000
    assert resolved["cost"]["cache_read"] == 0.0028
    assert resolved["reasoning"] is True


# ---------------------------------------------------------------------------
# D11 reasoning-replay assertion matrix --------------------------------------
# ---------------------------------------------------------------------------

def test_d11_responses_shape_with_field_dict_asserts():
    # string shape="responses" + interleaved {"field": ...} -> assert with field
    rec = {"interleaved": {"field": "reasoning_content"}, "provider": {"shape": "responses"}}
    assert M.assert_reasoning_replay(rec) == (True, "reasoning_content")


def test_d11_responses_shape_with_interleaved_true_asserts_field_absent():
    # interleaved: true (Anthropic-style) -> asserted with reasoning_field ABSENT
    rec = {"interleaved": True, "provider": {"shape": "responses"}}
    assert M.assert_reasoning_replay(rec) == (True, None)


def test_d11_completions_shape_never_asserts_even_with_interleaved():
    # shape="completions" -> NOT asserted regardless of interleaved
    rec = {"interleaved": {"field": "reasoning_content"}, "provider": {"shape": "completions"}}
    assert M.assert_reasoning_replay(rec) == (None, None)


def test_d11_no_shape_interleaved_presence_is_the_signal():
    # The zen-family npm-SDK dict form carries no string shape; interleaved
    # presence is the signal there (and for any provider without a per-model
    # shape override - the live catalog has none today).
    rec = {"interleaved": {"field": "reasoning_content"}}
    assert M.assert_reasoning_replay(rec) == (True, "reasoning_content")


def test_d11_no_shape_interleaved_true_asserts_field_absent():
    rec = {"interleaved": True}
    assert M.assert_reasoning_replay(rec) == (True, None)


def test_d11_reasoning_details_field():
    rec = {"interleaved": {"field": "reasoning_details"}}
    assert M.assert_reasoning_replay(rec) == (True, "reasoning_details")


def test_d11_no_interleaved_asserts_nothing():
    rec = {"provider": {"shape": "responses"}}
    assert M.assert_reasoning_replay(rec) == (None, None)
    assert M.assert_reasoning_replay({}) == (None, None)


# ---------------------------------------------------------------------------
# Canonical Capability Record (spec §4) -> LiteLLM model_info (D5 table) ----
# ---------------------------------------------------------------------------

def test_capability_to_model_info_full_record():
    rec = M.CapabilityRecord(
        model_id="deepseek/deepseek-v4-flash",
        provider="opencode",
        context_limit=128000,
        output_limit=32768,
        cost_input=0.00000014,
        cost_output=0.00000028,
        cost_cache_read=0.0000000028,
        cost_cache_write=0.0,
        supports_tool_calling=True,
        supports_structured_output=True,
        supports_reasoning=True,
        reasoning_in_response=True,
        reasoning_field="reasoning_content",
        modalities_in=("text",),
        modalities_out=("text",),
        open_weights=True,
        source="models.dev/deepseek/deepseek-v4-flash",
        synced_at="2026-08-11T12:00:00+00:00",
        staleness="fresh",
    )
    info = M.capability_to_model_info(rec)
    assert info["max_input_tokens"] == 128000
    assert info["max_output_tokens"] == 32768
    assert info["input_cost_per_token"] == 0.00000014
    assert info["output_cost_per_token"] == 0.00000028
    assert info["input_cost_per_token_cache_read"] == 0.0000000028
    assert info["input_cost_per_token_cache_write"] == 0.0
    assert info["supports_function_calling"] is True
    assert info["supports_parallel_function_calling"] is True
    assert info["supports_structured_output"] is True
    assert info["supports_reasoning"] is True
    assert info["reasoning_in_response"] is True
    assert info["reasoning_field"] == "reasoning_content"
    assert info["modalities_in"] == ("text",)
    assert info["modalities_out"] == ("text",)
    assert info["open_weights"] is True
    # Provenance - every record carries the full tag (D5 Rule 1).
    assert info["capability_source"] == "models.dev/deepseek/deepseek-v4-flash"
    assert info["capability_synced_at"] == "2026-08-11T12:00:00+00:00"
    assert info["capability_staleness"] == "fresh"


def test_capability_to_model_info_absence_is_unknown():
    # Rule 1: a field absent from the record is NEVER encoded as a value -
    # the key is simply absent, so the reader treats it as unknown.
    rec = M.CapabilityRecord(
        model_id="swissai/large",
        provider="swissai",
        source="unknown",
        synced_at="2026-08-11T12:00:00+00:00",
        staleness="unknown",
    )
    info = M.capability_to_model_info(rec)
    for key in ("max_input_tokens", "max_output_tokens", "input_cost_per_token",
                "output_cost_per_token", "input_cost_per_token_cache_read",
                "input_cost_per_token_cache_write", "supports_function_calling",
                "supports_parallel_function_calling", "supports_structured_output",
                "supports_reasoning", "reasoning_in_response", "reasoning_field",
                "modalities_in", "modalities_out", "open_weights"):
        assert key not in info, f"{key} must be ABSENT when unknown (Rule 1)"
    # Provenance keys are authored even for an unknown record.
    assert info["capability_source"] == "unknown"
    assert info["capability_staleness"] == "unknown"


def test_capability_to_model_info_interleaved_true_authors_no_field():
    rec = M.CapabilityRecord(
        model_id="anthropic/claude-sonnet-4-6",
        provider="opencode",
        reasoning_in_response=True,
        reasoning_field=None,
        source="models.dev/anthropic/claude-sonnet-4-6",
        synced_at="2026-08-11T12:00:00+00:00",
        staleness="fresh",
    )
    info = M.capability_to_model_info(rec)
    assert info["reasoning_in_response"] is True
    assert "reasoning_field" not in info  # ABSENT, per the D11 matrix


def test_unknown_model_info_marks_provenance_only():
    info = M.unknown_model_info("2026-08-11T12:00:00+00:00")
    assert info["capability_source"] == "unknown"
    assert info["capability_staleness"] == "unknown"
    assert info["capability_synced_at"] == "2026-08-11T12:00:00+00:00"
    # NO capability fields - the record exists for routing only (D9).
    assert len(info) == 3


def test_provenance_key_names_are_the_d5_contract():
    # The exact key names are load-bearing: T3 (#106) gates trust on them.
    assert M.PROVENANCE_SOURCE_KEY == "capability_source"
    assert M.PROVENANCE_SYNCED_AT_KEY == "capability_synced_at"
    assert M.PROVENANCE_STALENESS_KEY == "capability_staleness"
