"""Unit tier: the capability-adaptive method negotiation substrate (#99, ADR A1,
ticket #145).

The pure-function selector `negotiate_method(profile, no_tools_bound,
schema_shape)` picks the structured-output / tool-calling method per the ratified
semantic-first + profile-corrected rungs:

- tools bound (the session/crawl tool loop) -> `function_calling`, the ONLY
  tool-loop option - no silent method-swap inside a tool loop (A1 rung 2, T5
  gate unchanged);
- no tools bound (pure one-shot extraction) -> `json_schema` with the profile
  correcting within the fixed degrade chain `json_schema` -> `function_calling`
  -> `json_mode`;
- unknown profile -> the semantic default (`json_schema` on the no-tool rung,
  `function_calling` on the tool rung) - capability never gates session start
  (D7 fail-open);
- `reasoning_effort` is orthogonal to method selection (operator corrigendum,
  A1) - the negotiation module carries no thinking input at all.

The negotiation contract includes the parse-validation step as a companion pure
predicate (`result_validates`): each degrade rung's result is VALIDATED (parsed
Pydantic), not merely exception-caught - the #44 `json_mode` silent-wrong-shape
failure is caught this way. `DEGRADE_CHAIN` + `next_rung` expose the ordered
chain the probe-on-miss orchestration (increment-2, ADR A2) descends.

Every test is fully mocked - no live model, no live gateway (CODING_STANDARD
sections 6, 10). Prior art: the `test_llm_capability.py` reader tests (same
pure-contract style), `tests/test_llm_structured_output_pin.py` for the
conversion-boundary pair.
"""
import pytest
from pydantic import BaseModel

from polymerhus.app.llm import negotiation as N
from polymerhus.app.llm.capability import CapabilityProfile


class _Batch(BaseModel):
    observations: list[dict]


def _prof(**kw) -> CapabilityProfile:
    """A minimal profile with only the negotiated capability fields set - the
    negotiate contract reads `supports_structured_output` / `supports_tool_calling`
    only (the other profile fields are irrelevant to method selection, exactly as
    `reasoning_effort` is orthogonal per the A1 corrigendum)."""
    return CapabilityProfile(**kw)


# ---------------------------------------------------------------------------
# The rung vocabulary --------------------------------------------------------
# ---------------------------------------------------------------------------

def test_methods_map_onto_with_structured_output_method_values():
    """The negotiated method strings are EXACTLY the `with_structured_output`
    `method=` values (`json_schema`, `function_calling`, `json_mode`) - the
    chosen rung must be passable straight into the construction seam."""
    assert set(N.Method.__args__) == {"json_schema", "function_calling", "json_mode"}


def test_degrade_chain_is_the_ratified_order():
    """A1: the profile-corrected degrade chain, in order."""
    assert N.DEGRADE_CHAIN == ("json_schema", "function_calling", "json_mode")


def test_next_rung_descends_the_chain():
    assert N.next_rung("json_schema") == "function_calling"
    assert N.next_rung("function_calling") == "json_mode"
    assert N.next_rung("json_mode") is None  # the chain's end


def test_next_rung_refuses_unknown_method():
    with pytest.raises(ValueError):
        N.next_rung("xml_mode")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Tools bound: function_calling is the ONLY tool-loop option (A1 rung 2) -----
# ---------------------------------------------------------------------------

def test_tools_bound_always_function_calling():
    """A1 rung 2: a tool-bound call (session/crawl tool loop) NEVER method-
    swaps - regardless of the profile, the rung is `function_calling`. The T5
    gate (crawl_agentic.py) refuses crawl on unsupported/unknown and stays."""
    for profile in (None,
                    _prof(supports_structured_output=True, supports_tool_calling=True),
                    _prof(supports_structured_output=False, supports_tool_calling=False),
                    _prof(supports_tool_calling=True),
                    _prof(supports_structured_output=True),
                    _prof(supports_structured_output=False, supports_tool_calling=None),
                    CapabilityProfile(),  # all fields unknown
                    ):
        for shape in N.SchemaShape.__args__:
            assert N.negotiate_method(profile, no_tools_bound=False, schema_shape=shape) == \
                "function_calling"


def test_tools_bound_unknown_profile_is_the_proven_mainline():
    """A1: unknown profile on the session/tool rung degrades to
    `function_calling` (the proven mainline), never blocks the session start."""
    assert N.negotiate_method(None, no_tools_bound=False, schema_shape="open") == \
        "function_calling"


# ---------------------------------------------------------------------------
# No tools bound, unknown profile: the semantic default (D7 fail-open) -------
# ---------------------------------------------------------------------------

def test_no_tools_unknown_profile_semantic_default_json_schema():
    """A1: unknown profile (no gateway, no record, no tag) on the no-tool rung
    -> `json_schema` - the semantic default; a session must always start."""
    assert N.negotiate_method(None, no_tools_bound=True, schema_shape="open") == "json_schema"


def test_no_tools_all_unknown_fields_semantic_default_json_schema():
    """A tagged-but-empty record (all capability fields None per D5 Rule 1) is
    the same unknown state as no profile at all - the semantic default."""
    p = N.negotiate_method(CapabilityProfile(), no_tools_bound=True, schema_shape="closed")
    assert p == "json_schema"


# ---------------------------------------------------------------------------
# No tools bound, known profile: the A1 profile-corrected rung table ---------
# ---------------------------------------------------------------------------

def test_no_tools_structured_output_profile_uses_json_schema():
    p = N.negotiate_method(
        _prof(supports_structured_output=True, supports_tool_calling=None),
        no_tools_bound=True, schema_shape="open")
    assert p == "json_schema"


def test_no_tools_structured_output_beats_tool_calling():
    """Structured output present AND tool calling present: json_schema wins
    (the SOTA fixed-shape extraction rung, strict=False per A1)."""
    p = N.negotiate_method(
        _prof(supports_structured_output=True, supports_tool_calling=True),
        no_tools_bound=True, schema_shape="open")
    assert p == "json_schema"


def test_no_tools_tool_calling_only_degrades_to_function_calling():
    """A1: profile with tool calling but unknown/absent structured output ->
    degrade to `function_calling` (forced tool returns a dict; the proven
    open-dict behavior, pod.py)."""
    p = N.negotiate_method(
        _prof(supports_structured_output=None, supports_tool_calling=True),
        no_tools_bound=True, schema_shape="open")
    assert p == "function_calling"


def test_no_tools_neither_capability_uses_json_mode():
    """A1: a profile with neither structured output nor tool calling (both
    authored False) -> `json_mode` plus the mandatory result-validation
    contract (`result_validates`) - the #44-absorbed path."""
    p = N.negotiate_method(
        _prof(supports_structured_output=False, supports_tool_calling=False),
        no_tools_bound=True, schema_shape="open")
    assert p == "json_mode"


def test_no_tools_structured_output_false_tool_unknown_uses_json_mode():
    p = N.negotiate_method(
        _prof(supports_structured_output=False, supports_tool_calling=None),
        no_tools_bound=True, schema_shape="open")
    assert p == "json_mode"


def test_no_tools_tool_calling_false_structured_unknown_uses_json_mode():
    p = N.negotiate_method(
        _prof(supports_structured_output=None, supports_tool_calling=False),
        no_tools_bound=True, schema_shape="open")
    assert p == "json_mode"


# ---------------------------------------------------------------------------
# schema_shape: total-contract input, neutral under A1's universal strict=False
# ---------------------------------------------------------------------------

def test_schema_shape_is_a_typed_literal():
    assert set(N.SchemaShape.__args__) == {"closed", "open"}


def test_schema_shape_does_not_reopen_method_swap():
    """A1 rung 1 is UNCONDITIONALLY `response_format=json_schema, strict=False`
    - `strict=False` accepts open `dict` fields (Observation.anchor), so BOTH
    schema shapes resolve to the same rung table. The shape is a required input
    of the total contract (the seam records whether a call's schema rides an
    open field); it must NEVER reopen a method swap inside a tool loop, and it
    must never change the rung of the ratified table. The construction seam
    maps shape -> strictness configuration (the pin tests lock that dict-schema
    construction is the one that honours strict=False on the pinned SDK)."""
    args = (None,
            _prof(supports_structured_output=True, supports_tool_calling=True),
            _prof(supports_structured_output=True),
            _prof(supports_tool_calling=True),
            _prof(supports_structured_output=False, supports_tool_calling=False),
            CapabilityProfile())
    for profile in args:
        for tools in (False, True):
            open_rung = N.negotiate_method(profile, no_tools_bound=not tools, schema_shape="open")
            closed_rung = N.negotiate_method(profile, no_tools_bound=not tools, schema_shape="closed")
            assert open_rung == closed_rung


def test_schema_shape_refuses_unknown_values():
    with pytest.raises(ValueError, match="schema_shape"):
        N.negotiate_method(None, no_tools_bound=True, schema_shape="loose")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The parse-validation companion (part of the negotiation contract) ----------
# ---------------------------------------------------------------------------

def test_result_validates_rejects_none():
    """A rung that returns no parsed result (unmet/empty generation) is INVALID
    on every rung - `None` never descends as a success."""
    assert N.result_validates(None, _Batch) is False


def test_result_validates_parses_a_dict_into_the_schema():
    good = N.result_validates({"observations": [{"name": "x"}]}, _Batch)
    assert good is True
    bad = N.result_validates({"observations": "not-a-list"}, _Batch)
    assert bad is False
    wrong = N.result_validates({"unexpected": True}, _Batch)
    assert wrong is False


def test_result_validates_accepts_an_already_parsed_model():
    parsed = _Batch(observations=[])
    assert N.result_validates(parsed, _Batch) is True


def test_result_validates_without_schema_requires_a_result():
    """The free-shape (e.g. free-text) case: any non-None result is a valid
    parse; only absence is invalid."""
    assert N.result_validates("anything") is True
    assert N.result_validates({}) is True
    assert N.result_validates(None) is False


def test_result_validates_supports_non_pydantic_schemas_by_type():
    """A non-pydantic schema target falls back to an isinstance check - the
    predicate stays total over the call shapes the seam actually negotiates."""
    assert N.result_validates({"kind": "x"}, dict) is True
    assert N.result_validates([1, 2], dict) is False
    assert N.result_validates(1.5, float) is True


def test_result_validates_with_a_dict_schema_never_raises():
    """The json_schema rung constructs with the DICT form (`model_json_schema()`)
    - a dict schema carries no executable validator, so the predicate applies
    the soft shape-level check and NEVER crashes on the dict form: a miss only
    on `None` (nothing parseable came back), True on any non-None parsed
    object. Regression: this used to raise isinstance() arg 2 must be a type
    and would have exploded the increment-2 probe on a json_schema miss."""
    json_schema = _Batch.model_json_schema()
    assert N.result_validates(None, json_schema) is False
    assert N.result_validates({"observations": [{"name": "x"}]}, json_schema) is True
    assert N.result_validates({}, json_schema) is True
    assert N.result_validates("parsed-json", json_schema) is True


def test_dict_schema_miss_descends_the_chain():
    """The probe-on-miss loop on a json_schema try (dict form) that returns no
    parsed result: the predicate reports the miss and the orchestration
    descends to the next rung - a dict-schema validation miss must NOT crash
    the loop, it must degrade per DEGRADE_CHAIN."""
    json_schema = _Batch.model_json_schema()
    assert N.result_validates(None, json_schema) is False
    assert N.next_rung("json_schema") == "function_calling"
    assert N.next_rung(N.next_rung("json_schema")) == "json_mode"


def test_json_mode_rung_is_covered_by_the_validation_contract():
    """The #44-absorbed json_mode rung is exactly the one where the SHAPE guard
    is the parse validation (a 200 with the wrong shape must be caught, not
    accepted silently). The contract pairs the rung with the predicate: a
    model-parsable dict passes, a wrong-shaped one fails."""
    negotiated = N.negotiate_method(
        _prof(supports_structured_output=False, supports_tool_calling=False),
        no_tools_bound=True, schema_shape="open")
    assert negotiated == "json_mode"
    assert N.result_validates({"observations": []}, _Batch) is True
    assert N.result_validates({"observations": "oops"}, _Batch) is False