"""The capability-adaptive method negotiation substrate (#99, ADR A1, ticket #145).

The pure-function selector the seam wiring depends on: choose the
structured-output / tool-calling method per (capability_profile,
no_tools_bound, schema_shape), seeded from the gateway's synced capability
records and held for the session (D6 resolve-and-hold) - NEVER resolved
mid-turn, NEVER nested in the #73 escalating-timeout wrapper (this module is
pure: no I/O, no retry axis, no timeout, no live model/gateway).

Ratified rung table (ADR A1, authoritative):

1. **Tools bound** (a session/crawl tool loop): `function_calling` is the ONLY
   tool-loop option - there is no silent method-swap inside a tool loop (the
   T5 gate, `crawl_agentic.py`, refuses crawl on unsupported/unknown and stays).
2. **No tools bound** (a pure one-shot extraction): `json_schema` with the
   profile correcting within the fixed degrade chain
   `json_schema` -> `function_calling` -> `json_mode`:
   - structured output asserted -> `json_schema` (response_format, strict=False,
     the SOTA fixed-shape rung; open-dict tolerant, thinking models accept it);
   - structured output absent/unknown but tool calling asserted -> degrade to
     `function_calling` (forced tool returns a dict; the proven mainline
     behavior for open-dict fields);
   - neither asserted -> `json_mode` PLUS the mandatory parse-validation
     contract (`result_validates`) - the #44-absorbed path.
   - **Unknown profile** (no profile, or every capability field None per D5
     Rule 1): the semantic default - `json_schema` on the no-tool rung,
     `function_calling` on the tool rung. Capability never gates session start
     (D7 fail-open).

`reasoning_effort` is orthogonal (operator corrigendum, A1): the negotiated
method never depends on the thinking dial - this module carries no thinking
input at all.

`schema_shape` (`closed` | `open`) is the third input of the total contract
the ADR fixed (the seam records whether a call's schema carries free-form
`dict` fields, e.g. `Observation.anchor`). Under A1 rung 1, `strict=False` is
UNCONDITIONAL and accepts open dict fields, so both shapes resolve to the same
rung table - the shape must never reopen a method swap inside a tool loop, and
never changes the ratified rungs. The shape's construction consequence (dict
schemas honor `strict=False` on the pinned SDK; pydantic-CLASS schemas silently
default to strict) is locked by the pin-behavior tests
(`tests/test_llm_structured_output_pin.py`).

The negotiation contract includes the parse-validation step as a companion
pure predicate, `result_validates`: each degrade rung's outcome is the PARSED
result validated against the target schema - not an exception-caught miss, so
`json_mode`'s silent wrong-shape failure (HTTP 200, wrong JSON) is caught and
renegotiated per A2 (increment-2 probes the chain in `DEGRADE_CHAIN` order via
`next_rung`). No vendor error string is ever parsed (A2).

Importing this module performs no I/O and requires no env var (CODING_STANDARD
section 6).
"""
from __future__ import annotations

from typing import Any, Literal

from polymerhus.app.llm.capability import CapabilityProfile

# The negotiated method vocabulary - EXACTLY the `with_structured_output`
# `method=` values (langchain-openai ~1.3), so a chosen rung passes straight
# into the construction seam with no translation layer.
Method = Literal["json_schema", "function_calling", "json_mode"]

# The structural class of the target schema (ADR A1's third input): whether the
# schema carries free-form `dict` fields (`open`, e.g. `Observation.anchor`) or
# a fully-typed shape (`closed`). Total-contract input; see module docstring
# for why it does not alter the ratified rungs.
SchemaShape = Literal["closed", "open"]

_SCHEMA_SHAPES = set(SchemaShape.__args__)

# The fixed profile-corrected degrade chain (A1), in descent order. Each rung's
# result is validated via `result_validates`; a probe/construction orchestration
# descends with `next_rung` (increment-2, A2).
DEGRADE_CHAIN: tuple[Method, ...] = ("json_schema", "function_calling", "json_mode")

# A profile is "unknown" for negotiation when it is absent OR carries no
# authored capability field (D5 Rule 1: an absent field is the encoding of
# unknown; a record whose only authored fields are window/provenance tells the
# negotiation nothing).


def _unknown_profile(profile: CapabilityProfile | None) -> bool:
    return profile is None or (
        profile.supports_structured_output is None
        and profile.supports_tool_calling is None
    )


def negotiate_method(
    profile: CapabilityProfile | None,
    no_tools_bound: bool,
    schema_shape: SchemaShape,
) -> Method:
    """The A1 selector: the structured-output / tool-calling method for one
    call at construction time.

    `no_tools_bound` is the SEMANTIC axis: True for a pure one-shot extraction
    (no tools bound), False for a tool-bound session/crawl loop. `profile` is
    the resolved capability profile (or None when unknown - fail-open D7);
    `schema_shape` is the closed/open class of the target schema. Pure: same
    inputs, same method, always (unit-testable with LLM and gateway mocked).
    """
    if schema_shape not in _SCHEMA_SHAPES:
        raise ValueError(
            f"schema_shape must be one of {sorted(_SCHEMA_SHAPES)} (got {schema_shape!r})"
        )
    if not no_tools_bound:
        # A1 rung 2: tools bound -> the ONLY tool-loop option. No profile can
        # change this (the T5 gate refuses crawl on unsupported/unknown).
        return "function_calling"
    if _unknown_profile(profile):
        # A1 semantic default for the no-tool rung; the session must always start.
        return "json_schema"
    if profile.supports_structured_output:
        return "json_schema"
    if profile.supports_tool_calling:
        # Profile lacks structured output but can call tools: degrade to the
        # proven open-dict rung (forced tool returns a dict to validate).
        return "function_calling"
    # Neither capability asserted -> the #44-absorbed last rung. The parse
    # validation is the required guard on this rung (`result_validates`).
    return "json_mode"


def next_rung(method: Method) -> Method | None:
    """The next degrade rung after `method`, or None at the chain's end.

    The probe-on-miss orchestration (increment-2, A2) descends this on a
    `result_validates` failure - never by parsing vendor error strings."""
    if method not in DEGRADE_CHAIN:
        raise ValueError(f"unknown negotiation method {method!r}; known: {DEGRADE_CHAIN}")
    index = DEGRADE_CHAIN.index(method)
    return DEGRADE_CHAIN[index + 1] if index + 1 < len(DEGRADE_CHAIN) else None


def result_validates(parsed: Any, schema: type | None = None) -> bool:
    """The negotiation contract's parse-validation predicate.

    Whether a rung's PARSED result is valid for the target schema. This is what
    makes the degrade chain validate the parsed result rather than merely catch
    exceptions: `None` (an unmet generation) is invalid on every rung; a
    pydantic target validates the dict/model via `model_validate` (catching
    validation errors, never parsing vendor error text - A2); a non-pydantic
    target falls back to an isinstance check. The caller descends `next_rung`
    on False."""
    if parsed is None:
        return False
    if schema is None:
        return True
    validate = getattr(schema, "model_validate", None)
    if callable(validate):
        try:
            validate(parsed)
        except Exception:  # noqa: BLE001 - any validation failure is a rung miss
            return False
        return True
    return isinstance(parsed, schema)