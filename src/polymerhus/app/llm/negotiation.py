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
(`tests/test_llm_structured_output_pin.py`). `schema_shape_of` is the seam's
deriver: a pydantic class carrying a free-form `dict` anywhere in its recursive
field tree is `open`, anything unprovably typed is conservatively `open`.

The negotiation contract includes the parse-validation step as a companion
pure predicate, `result_validates`: each degrade rung's outcome is the PARSED
result validated against the target schema - not an exception-caught miss, so
`json_mode`'s silent wrong-shape failure (HTTP 200, wrong JSON) is caught and
renegotiated per A2. The probe-on-miss orchestration walks the fixed
`DEGRADE_CHAIN` directly, validating the parsed result at each rung - it does
not call `next_rung` (that predicate is the one-shot construction/degrade
helper for a single held rung). No vendor error string is ever parsed (A2).

Importing this module performs no I/O and requires no env var (CODING_STANDARD
section 6).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Literal, get_args, get_origin

from pydantic import BaseModel

from polymerhus.app.llm.capability import CapabilityProfile

logger = logging.getLogger(__name__)

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

# The fixed profile-corrected degrade chain (A1), in descent order. The
# probe-on-miss orchestration walks this tuple directly (validating each rung
# via `result_validates`); `next_rung` is the one-shot construction/degrade
# helper for a single held rung, not the probe's iterator.
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


def schema_shape_of(schema: Any) -> SchemaShape:
    """The shape class of a schema TARGET - the A1 contract's third input,
    derived from a pydantic class: "open" when the class carries a free-form
    `dict` field ANYWHERE in its recursive field tree (the `Observation.anchor`
    case), else "closed". A non-pydantic target is conservatively "open" (the
    caller could not prove it typed). The shape never changes the ratified rung
    table - A1 rung 1's strict=False is unconditional - it is the total-contract
    input the construction seam records so every negotiate call is total.

    This is the seam's way of recording the shape; the SAME shape must be
    presented to `negotiate_method` that the construction will pass to the wire
    (dict-form for the json_schema rung, per the pin tests)."""
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return "open" if _annotation_is_open(schema) else "closed"
    return "open"


def _annotation_is_open(annotation: Any, _seen: frozenset[type] | None = None) -> bool:
    """Whether an annotation - recursively through nested models and generic /
    union args - carries a free-form `dict`: a dict type with no constrained
    value shape (bare `dict`, bare `Dict`, or a `dict[str, Any|object]` whose
    value slot is unprovably typed). A TYPED dict (`dict[str, X]`) serializes its
    value schema as the object's additionalProperties, so only the unconstrained
    form is the free-form field class A1 names; recursing into a typed dict's
    VALUE type still finds a nested model's open field.

    A `_seen` set of already-visited model classes keeps the recursion total over
    SELF-REFERENTIAL schemas (`class Node(BaseModel): children: list["Node"]`) -
    re-entering a visited model contributes nothing new, so it terminates with a
    fixed point instead of a RecursionError."""
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        _seen = _seen if _seen is not None else frozenset()
        if annotation in _seen:
            return False
        _seen = _seen | {annotation}
        return any(_annotation_is_open(f.annotation, _seen)
                   for f in annotation.model_fields.values())
    if annotation is dict:
        return True
    args = get_args(annotation)
    origin = get_origin(annotation)
    if origin is None:
        return False
    if origin is dict:
        if not args:
            return True
        value = args[-1]
        if value is Any or value is object:
            return True
        return _annotation_is_open(value, _seen)
    return any(_annotation_is_open(a, _seen) for a in args)


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


def result_validates(parsed: Any, schema: type | dict | None = None) -> bool:
    """The negotiation contract's parse-validation predicate.

    Whether a rung's PARSED result is valid for the target schema. This is what
    makes the degrade chain validate the parsed result rather than merely catch
    exceptions: `None` (an unmet generation) is invalid on every rung; a
    pydantic CLASS target validates the dict/model via `model_validate`
    (catching validation errors, never parsing vendor error text - A2); a
    non-pydantic class target falls back to an isinstance check.

    A DICT-form target (`model_json_schema()` - the construction form the
    json_schema rung passes to `with_structured_output`, see the pin tests)
    carries no executable validator, so only a soft shape-level check applies:
    the rung is a miss on `None` (nothing parseable came back), otherwise the
    wire returned a JSON-parseable object and the rung holds. Class targets
    VALIDATE, dict targets only SHAPE-check - "class for validation vs dict for
    construction". The caller descends `next_rung` on False."""
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
    if isinstance(schema, dict):
        # A JSON-schema dict holds no executable validator - shape-check only.
        return True
    return isinstance(parsed, schema)


# --- Probe-on-miss (increment-2, ADR A2) -----------------------------------
#
# Unknown-to-registry models get a try-in-order probe at session construction
# (the degenerate one-call session for one-shot) that validates the PARSED
# Pydantic result at each rung via `result_validates` - never parsing vendor
# error strings. Cadence: once per (provider, model, schema-class) and held
# for the process lifetime (D6 resolve-and-hold, off the #73 axis). Cost:
# cold-start only, no retry budget spent on #73; a probe failure degrades per
# the chain and the session still starts (fail-open D7). Observable: each
# resolution gets a langfuse span/trace (D11 discipline) and is logged.

# Process-lifetime probe hold: winner method per (provider, model, schema-class).
_PROBE_CACHE: dict[tuple[str, str, str], Method | None] = {}


def _probe_cache_key(provider: str, model: str, schema: Any) -> tuple[str, str, str]:
    """Cache key for the probe winner - per (provider, model, schema-class).

    The schema-class is the stable identity of the target type, not the shape.
    A pydantic class keys by its fully-qualified name; a dict schema or other
    target keys by its repr so distinct raw schemas do not collide. The key is
    hashable and stable for the process lifetime."""
    if isinstance(schema, type):
        name = f"{schema.__module__}.{schema.__qualname__}"
    elif isinstance(schema, dict):
        # A JSON-schema dict target - hash the repr truncated to keep keys bounded.
        name = repr(schema)[:400]
    elif schema is None:
        name = "None"
    else:
        name = getattr(schema, "__name__", repr(schema)[:200])
    return (provider, model, name)


def clear_probe_cache() -> None:
    """Clear the held probe winners - test seam only, not a production path."""
    _PROBE_CACHE.clear()


def _emit_probe_span(
    provider: str,
    model: str,
    schema: Any,
    chosen: Method | None,
    provenance: str | None,
    attempted: list[Method],
) -> None:
    """Emit a langfuse span/trace for one probe resolution (D11). Fail-open:
    never raises, never blocks the caller if langfuse is absent or misconfigured."""
    try:
        from langfuse import get_client

        name = "capability-probe"
        schema_name = getattr(schema, "__name__", str(schema)[:80])
        with get_client().start_as_current_observation(
            name=name,
            as_type="span",
            input={
                "provider": provider,
                "model": model,
                "schema": schema_name,
                "attempted": list(attempted),
            },
        ) as span:
            span.update(
                output={
                    "chosen": chosen,
                    "provenance": provenance,
                }
            )
    except Exception:
        logger.debug(
            "probe langfuse span unavailable for %s/%s; continuing untraced",
            provider,
            model,
            exc_info=True,
        )


def _emit_resolution(
    provider: str,
    model: str,
    schema: Any,
    method: Method | None,
    provenance: str | None,
    attempted: list[Method],
) -> None:
    """The ONE emit-span (D11) + info-log block for a capability resolution.

    Both `probe_with_invoker` (its internal probe winner) and `resolve_method`
    (the shared seam-owned orchestration) report through here, so the
    observable line and its provenance strings never diverge across the
    one-shot and session seams. Fail-open: never raises, never blocks the
    caller if langfuse is absent or misconfigured."""
    try:
        _emit_probe_span(provider, model, schema, method, provenance, attempted)
    except Exception:  # noqa: BLE001 - fail-open, never into the caller
        logger.debug(
            "probe span emit failed for %s/%s", provider, model, exc_info=True
        )
    logger.info(
        "capability probe: provider=%s model=%s schema=%s chosen=%s provenance=%s attempted=%s",
        provider,
        model,
        getattr(schema, "__name__", str(schema)[:80]) if schema is not None else "None",
        method,
        provenance,
        attempted,
    )


def probe_with_invoker(
    provider: str,
    model: str,
    schema: Any,
    invoker: Callable[[Method], Any],
    profile: CapabilityProfile | None = None,
) -> Method | None:
    """Try the degrade chain in order, validating the parsed result at each rung.

    `invoker(method)` performs one structured-output call for the given rung and
    returns its parsed result (or raises). The probe validates each parsed result
    via `result_validates` - never by parsing vendor error strings - and returns
    the first method whose result validates, or None if every rung misses. The
    winner (including None for all-miss) is held in `_PROBE_CACHE` per
    (provider, model, schema-class) and never re-probed at construction. Fail-open:
    a probe failure does not raise; the caller decides the degraded fallback.
    Observable: a langfuse span per resolution plus an info log with method and
    provenance.

    Off the #73 axis by construction - single-shot, no escalating wrapper, no retry
    budget spent. The caller must invoke this ONCE at construction, before the
    escalating loop, and cache the winner for the session."""
    key = _probe_cache_key(provider, model, schema)
    if key in _PROBE_CACHE:
        return _PROBE_CACHE[key]
    attempted: list[Method] = []
    winner: Method | None = None
    provenance = getattr(profile, "source", None) if profile is not None else None
    for method in DEGRADE_CHAIN:
        attempted.append(method)
        try:
            parsed = invoker(method)
        except Exception as exc:  # noqa: BLE001 - a rung miss, descend
            logger.debug(
                "probe rung %s for %s/%s raised %s; descending",
                method,
                provider,
                model,
                exc,
            )
            continue
        if result_validates(parsed, schema):
            winner = method
            break
        logger.debug(
            "probe rung %s for %s/%s failed validation; descending",
            method,
            provider,
            model,
        )
    _PROBE_CACHE[key] = winner
    _emit_resolution(provider, model, schema, winner, provenance, attempted)
    return winner


def resolve_method(
    profile: CapabilityProfile | None,
    schema: Any,
    no_tools_bound: bool,
    *,
    invoker: Callable[[Method], Any] | None = None,
    role: str | None = None,
    provider: str,
    model: str,
    negotiate: Callable[..., Method] = negotiate_method,
    probe: Callable[..., Method | None] = probe_with_invoker,
) -> tuple[Method, str | None]:
    """The shared capability-method resolver owning the whole decision, once.

    This is the single orchestration the one-shot (`roles.invoke_role`) and
    session (`session._structured_response_format`) seams both point at, so the
    resolve -> unknown-check -> cache-read -> (probe | semantic default) ->
    emit-span+log sequence never drifts between them. The caller hands it an
    ALREADY-RESOLVED `profile` (resolve-and-hold, D6) plus the seam's own
    `negotiate` / `probe` references (so each module's tests can patch them) and
    returns `(method, provenance)`.

    `no_tools_bound` is the A1 semantic axis (True for a one-shot/session
    no-tools extraction). Unknown-to-registry models (D5 Rule 1) apply
    probe-on-miss (A2): a `probe` (default `probe_with_invoker`) only runs when
    an `invoker` is supplied - the one-shot seam always supplies one, the
    session seam supplies one only under its test seam and otherwise takes the
    UNVALIDATED semantic default (Q2), never writing the shared cache (Q4). A
    cached winner (probed by a prior one-shot) is reused with the
    `probe-cache-hit` provenance. Fail-open (D7): every path returns a method;
    an all-miss probe or an unknown no-invoker profile degrades to the semantic
    default and the session still starts."""
    if not no_tools_bound:
        # A1 rung 1: tools bound -> the ONLY tool-loop option; no profile can
        # change this. No cache read, no probe, no unknown-check.
        method: Method = "function_calling"
        provenance: str | None = None
        _emit_resolution(provider, model, schema, method, provenance, [method])
        return method, provenance
    if not _unknown_profile(profile):
        # A known profile never probes (Q1): the pure negotiate contract picks
        # the rung from the held profile.
        method = negotiate(
            profile, no_tools_bound=True, schema_shape=schema_shape_of(schema)
        )
        provenance = getattr(profile, "source", None)
        _emit_resolution(provider, model, schema, method, provenance, [method])
        return method, provenance
    # Unknown profile (D5 Rule 1). Cache-read first (Q3): a prior one-shot probe
    # winner is held per (provider, model, schema-class) and reused.
    key = _probe_cache_key(provider, model, schema)
    if key in _PROBE_CACHE:
        winner = _PROBE_CACHE[key]
        method = "json_schema" if winner is None else winner
        provenance = "probe-cache-hit"
        _emit_resolution(provider, model, schema, method, provenance, [method])
        return method, provenance
    if invoker is not None:
        # The one-shot seam supplies an invoker -> real probe. `probe` writes
        # the shared cache and reports its own span/log; this resolver does not
        # double-emit here (that is the ONE place the probe itself observes).
        winner = probe(provider, model, schema, invoker, profile)
        method = "json_schema" if winner is None else winner
        return method, None
    # No invoker (the session seam's production path, Q2): no extra LLM call at
    # construction. Hold the UNVALIDATED semantic default for this turn, mark it
    # observable at generation time, and NEVER write the shared cache (Q4).
    method = negotiate(
        profile, no_tools_bound=True, schema_shape=schema_shape_of(schema)
    )
    provenance = "semantic-default-unvalidated; no prior probe entry"
    _emit_resolution(provider, model, schema, method, provenance, [method])
    return method, provenance
