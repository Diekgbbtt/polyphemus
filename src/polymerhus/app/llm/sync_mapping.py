"""The sync mapping layer (T2, #105) - the ONLY place product-specific field
names live (ADR D5, spec §3.3).

Converts a models.dev resolved model record into the canonical Capability
Record (spec §4) and then into the LiteLLM `model_info` schema per the D5
table; performs the per-million -> per-token cost unit conversion as a pure
function; resolves `base_model` inheritance BEFORE push (Rule 2) so one global
truth per (provider x model) lands in the gateway; authors the reasoning-replay
surface per the D11 assertion matrix; and decides the registered-name
convention (provider/model slash form, operator-ratified 2026-08-11).

Pure by construction (CODING_STANDARD §3): importing this module performs no
I/O, reads no env var, and no function here touches a driver. The impure
fetch/push orchestration lives in `sync.py`; the pipeline's only seams are the
callables injected there.

## Rule 1 (conservative-unknown, load-bearing)

LiteLLM merges its own bundled cost-map defaults into `model_info` for models
it recognises. Trusting those would re-introduce the "silent optimistic
default" failure the spec exists to eliminate. So every record the sync pushes
carries the `capability_source` / `capability_synced_at` / `capability_staleness`
provenance keys, and a capability field that is unknown is NEVER encoded as a
value - the key is simply ABSENT from the pushed `model_info`. The client-side
reader (T3, #106) gates trust on the provenance tag.

## Rule 2 (per-provider override, resolved before push)

models.dev supports `base_model` inheritance: a provider-scoped model record
may reference a canonical record and override/omit fields from it. The mapping
layer resolves the inheritance (deep-merge for nested dicts - `cost`, `limit`,
`modalities` - so an un-overridden sub-field survives; provider fields win;
`base_model_omit` drops fields) so the reader never re-resolves inheritance at
read time. A `base_model` that points at a missing base degrades to the
provider record as-is: fields the provider omits stay ABSENT (unknown), never
guessed.

## D11 reasoning-replay assertion matrix

The reasoning-replay surface is authored per the D11 matrix from models.dev
`interleaved` + the per-model `provider.shape` override sub-key (a string
`"responses" | "completions"`; absent on almost every live provider, including
the zen-family npm-SDK dict form which carries no string shape):

| `provider.shape` | `interleaved` | result |
|---|---|---|
| `"completions"` | any | NOT asserted (None, None), regardless of interleaved |
| `"responses"` | present | asserted |
| absent (incl. zen dict-npm form) | present | asserted (`interleaved` presence is the signal) |
| any | absent | not asserted |
| `interleaved: true` (Anthropic-style) | | `reasoning_in_response=True`, `reasoning_field` ABSENT |
| `interleaved: {"field": ...}` (deepseek-family) | | `reasoning_in_response=True`, `reasoning_field` authored |

Reasoning caching is NOT asserted here: `cache_read`/`cache_write` are pricing
fields only (D11 grey point) - they are mapped to the cost keys and never used
as capability evidence.
"""

from dataclasses import dataclass, field
from typing import Any

from polymerhus.app.llm.providers import _ZEN_FAMILY

# --- Provenance keys (D5 Rule 1; the exact names are load-bearing - T3 #106
# gates trust on them). -------------------------------------------------------
PROVENANCE_SOURCE_KEY = "capability_source"
PROVENANCE_SYNCED_AT_KEY = "capability_synced_at"
PROVENANCE_STALENESS_KEY = "capability_staleness"

# Staleness enum (spec §4). Every record the sync pushes is FRESH by
# definition (it just synced); UNKNOWN marks the no-registry-entry records
# (D9 unknown-model path) so the reader resolves them as unknown (D6).
STALENESS_FRESH = "fresh"
STALENESS_UNKNOWN = "unknown"

# The provenance tag value for models with NO registry entry (D9): they are
# real on `/v1/models` (registered for routing) but carry no capability data.
UNKNOWN_SOURCE = "unknown"

PER_MILLION = 1_000_000


# ---------------------------------------------------------------------------
# Unit conversion (D5: a pure, unit-tested function) -------------------------
# ---------------------------------------------------------------------------

def per_million_to_per_token(usd_per_million: float) -> float:
    """Convert models.dev per-million-token USD pricing to per-token USD.

    models.dev `cost.*` fields are USD per 1M tokens; LiteLLM
    `*_cost_per_token` fields are USD per token. The division by 1e6 is
    rounded to 12 decimal places: registry prices carry at most ~4
    significant digits (per 1M tokens), so per-token values never have a
    meaningful digit beyond ~1e-9 - the rounding absorbs binary float noise
    (e.g. `3.2 / 1e6 == 3.2000000000000003e-06`) without touching any real
    digit. This keeps the conversion a deterministic pure function."""
    return round(usd_per_million / PER_MILLION, 12)


# ---------------------------------------------------------------------------
# Registered-name convention (D5 model_id row; operator-ratified 2026-08-11) -
# ---------------------------------------------------------------------------
#
# The gateway registers the SLASH form `<provider>/<id>` as the litellm
# `model_name` (what the client sends in gateway mode, T4 #107). The
# zen-family id strip moves from `build_chat_model` (providers.py, `_ZEN_FAMILY`)
# INTO this mapping layer: `litellm_params.model` carries the provider-native
# id - the bare zen catalog id for the zen family (the zen gateway validates
# against bare ids), the model id verbatim for every other provider.

def strip_zen_id(model_id: str) -> str:
    """The zen-family strip (providers.py `_ZEN_FAMILY`): the zen catalog ids
    contain no `/`, so the last segment is always the bare id. Idempotent on a
    bare input."""
    return model_id.rsplit("/", 1)[-1]


def registered_model_name(provider: str, model_id: str) -> str:
    """The litellm `model_name` registered in the gateway: the string the
    client sends in gateway mode. `<provider>/<id>`; the zen family registers
    the STRIPPED (bare) zen id so the zen gateway accepts routing."""
    if provider in _ZEN_FAMILY:
        return f"{provider}/{strip_zen_id(model_id)}"
    return f"{provider}/{model_id}"


def native_litellm_model(provider: str, model_id: str) -> str:
    """The `litellm_params.model` value: the provider-native id the upstream
    expects. Bare zen id for the zen family; the id verbatim otherwise."""
    if provider in _ZEN_FAMILY:
        return strip_zen_id(model_id)
    return model_id


# ---------------------------------------------------------------------------
# Rule 2: base_model inheritance resolved before push ------------------------
# ---------------------------------------------------------------------------

_NESTED_MERGE_KEYS = ("cost", "limit", "modalities")


def resolve_model_record(provider_record: dict, global_models: dict) -> dict:
    """Resolve `base_model` inheritance (Rule 2): one global truth per
    (provider x model).

    `provider_record` is a provider-scoped models.dev model record; `global_models`
    is the catalog's canonical `models` dict (keyed by `provider/model`).

    Deep-merge the canonical base under the provider record for the nested
    tables (`cost`, `limit`, `modalities`) so an un-overridden sub-field
    survives; provider scalar fields always win; `base_model_omit` drops the
    named fields from the merged result. The resolution machinery keys
    (`base_model`, `base_model_omit`) never leak into the result.

    A `base_model` pointing at a missing canonical record degrades to the
    provider record as-is - fields the provider omits stay ABSENT (unknown per
    Rule 1), never guessed from a missing base."""
    merged: dict[str, Any] = dict(provider_record)
    base_id = provider_record.get("base_model")
    if isinstance(base_id, str):
        base = global_models.get(base_id)
        if isinstance(base, dict):
            merged = dict(base)
            for key, value in provider_record.items():
                if key in ("base_model", "base_model_omit"):
                    continue
                if key in _NESTED_MERGE_KEYS and isinstance(value, dict) \
                        and isinstance(merged.get(key), dict):
                    nested = dict(merged[key])
                    nested.update(value)
                    merged[key] = nested
                else:
                    merged[key] = value
    for key in ("base_model", "base_model_omit"):
        merged.pop(key, None)
    omit = provider_record.get("base_model_omit")
    if isinstance(omit, (list, tuple, set)):
        for key in omit:
            merged.pop(key, None)
    return merged


# ---------------------------------------------------------------------------
# D11 reasoning-replay assertion matrix --------------------------------------
# ---------------------------------------------------------------------------

def assert_reasoning_replay(model_record: dict) -> tuple[bool | None, str | None]:
    """Author the reasoning-replay surface per the D11 matrix.

    Returns `(reasoning_in_response, reasoning_field)`, both `None` when the
    surface is NOT asserted (unknown per Rule 1 - the keys are then simply
    absent from `model_info`).

    - `provider.shape == "completions"` -> NOT asserted regardless of
      `interleaved` (the chat-completions wire cannot replay reasoning).
    - otherwise `interleaved` presence is the signal: `True` (Anthropic-style)
      asserts `reasoning_in_response` with `reasoning_field` ABSENT;
      `{"field": ...}` (deepseek-family) authors the field
      (`reasoning_content` | `reasoning_details`).
    - no `interleaved` -> not asserted (conservative, never guessed)."""
    provider_block = model_record.get("provider")
    shape = provider_block.get("shape") if isinstance(provider_block, dict) else None
    if shape == "completions":
        return None, None
    interleaved = model_record.get("interleaved")
    if interleaved is None:
        return None, None
    if interleaved is True:
        return True, None
    if isinstance(interleaved, dict):
        field_name = interleaved.get("field")
        if isinstance(field_name, str) and field_name:
            return True, field_name
    return None, None


# ---------------------------------------------------------------------------
# Canonical Capability Record (spec §4) --------------------------------------
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapabilityRecord:
    """The canonical per-model capability record (spec §4).

    Costs are PER-TOKEN USD (converted at this seam). A `None` capability
    field means UNKNOWN - it is never encoded into `model_info` (Rule 1:
    absence is the encoding of unknown)."""

    model_id: str
    provider: str
    context_limit: int | None = None
    output_limit: int | None = None
    cost_input: float | None = None
    cost_output: float | None = None
    cost_cache_read: float | None = None
    cost_cache_write: float | None = None
    supports_tool_calling: bool | None = None
    supports_structured_output: bool | None = None
    supports_reasoning: bool | None = None
    reasoning_in_response: bool | None = None
    reasoning_field: str | None = None
    modalities_in: tuple[str, ...] | None = None
    modalities_out: tuple[str, ...] | None = None
    open_weights: bool | None = None
    source: str = UNKNOWN_SOURCE
    synced_at: str = ""
    staleness: str = STALENESS_UNKNOWN


def capability_record_from_resolved(provider: str, model_id: str,
                                    resolved: dict, *, synced_at: str) -> CapabilityRecord:
    """Build the canonical Capability Record from a Rule-2-resolved models.dev
    record (or mark the record unknown when `resolved` is None)."""
    if resolved is None:
        return CapabilityRecord(model_id=model_id, provider=provider,
                                source=UNKNOWN_SOURCE, synced_at=synced_at,
                                staleness=STALENESS_UNKNOWN)
    limits = resolved.get("limit") or {}
    costs = resolved.get("cost") or {}
    modalities = resolved.get("modalities") or {}
    reasoning_in_response, reasoning_field = assert_reasoning_replay(resolved)
    return CapabilityRecord(
        model_id=model_id,
        provider=provider,
        context_limit=limits.get("context"),
        output_limit=limits.get("output"),
        cost_input=per_million_to_per_token(costs["input"]) if "input" in costs else None,
        cost_output=per_million_to_per_token(costs["output"]) if "output" in costs else None,
        cost_cache_read=per_million_to_per_token(costs["cache_read"]) if "cache_read" in costs else None,
        cost_cache_write=per_million_to_per_token(costs["cache_write"]) if "cache_write" in costs else None,
        supports_tool_calling=resolved.get("tool_call"),
        supports_structured_output=resolved.get("structured_output"),
        supports_reasoning=resolved.get("reasoning"),
        reasoning_in_response=reasoning_in_response,
        reasoning_field=reasoning_field,
        modalities_in=tuple(modalities["input"]) if modalities.get("input") else None,
        modalities_out=tuple(modalities["output"]) if modalities.get("output") else None,
        open_weights=resolved.get("open_weights"),
        source=f"models.dev/{provider}/{model_id}",
        synced_at=synced_at,
        staleness=STALENESS_FRESH,
    )


# ---------------------------------------------------------------------------
# Capability Record -> LiteLLM model_info (the D5 table) ---------------------
# ---------------------------------------------------------------------------

def capability_to_model_info(record: CapabilityRecord) -> dict:
    """Map the canonical Capability Record to the LiteLLM `model_info` schema
    per the D5 table. A `None` field is UNKNOWN and the key is ABSENT (Rule 1:
    `unknown` is never encoded as a value). The provenance keys are authored
    on EVERY record, including unknown ones."""
    info: dict[str, Any] = {}
    if record.context_limit is not None:
        info["max_input_tokens"] = record.context_limit
    if record.output_limit is not None:
        info["max_output_tokens"] = record.output_limit
    if record.cost_input is not None:
        info["input_cost_per_token"] = record.cost_input
    if record.cost_output is not None:
        info["output_cost_per_token"] = record.cost_output
    if record.cost_cache_read is not None:
        info["input_cost_per_token_cache_read"] = record.cost_cache_read
    if record.cost_cache_write is not None:
        info["input_cost_per_token_cache_write"] = record.cost_cache_write
    if record.supports_tool_calling is not None:
        # D5: supports_tool_calling maps to BOTH keys (the crawl `bind_tools`
        # path uses the parallel form; models.dev carries no separate flag, so
        # the same authored value feeds both).
        info["supports_function_calling"] = record.supports_tool_calling
        info["supports_parallel_function_calling"] = record.supports_tool_calling
    if record.supports_structured_output is not None:
        info["supports_structured_output"] = record.supports_structured_output
    if record.supports_reasoning is not None:
        info["supports_reasoning"] = record.supports_reasoning
    if record.reasoning_in_response is not None:
        # D11: interleaved: true -> reasoning_in_response asserted with
        # reasoning_field ABSENT (never authored, never guessed).
        info["reasoning_in_response"] = record.reasoning_in_response
        if record.reasoning_field is not None:
            info["reasoning_field"] = record.reasoning_field
    if record.modalities_in is not None:
        info["modalities_in"] = record.modalities_in
    if record.modalities_out is not None:
        info["modalities_out"] = record.modalities_out
    if record.open_weights is not None:
        info["open_weights"] = record.open_weights
    info[PROVENANCE_SOURCE_KEY] = record.source
    info[PROVENANCE_SYNCED_AT_KEY] = record.synced_at
    info[PROVENANCE_STALENESS_KEY] = record.staleness
    return info


def unknown_model_info(synced_at: str) -> dict:
    """The `model_info` for a model that exists on `/v1/models` but has NO
    registry entry (D9): NO capability fields, only the provenance tag marking
    it unknown. The record is still registered for routing - existence is
    real - and the reader resolves it as unknown (D6/D7)."""
    return {
        PROVENANCE_SOURCE_KEY: UNKNOWN_SOURCE,
        PROVENANCE_SYNCED_AT_KEY: synced_at,
        PROVENANCE_STALENESS_KEY: STALENESS_UNKNOWN,
    }
