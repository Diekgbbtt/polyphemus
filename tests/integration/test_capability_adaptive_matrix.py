"""Matrix harness for C1-C26 (#99) - minimal fake-LLM scaffold.

Each test is hermetic, uses pure negotiation/capability seams, no real provider keys.
"""
from __future__ import annotations

import os
from typing import Any

import pytest
from pydantic import BaseModel

from polymerhus.app.llm.capability import CapabilityProfile
from polymerhus.app.llm.negotiation import (
    DEGRADE_CHAIN,
    THINKING_BUDGET,
    negotiate_method,
    negotiate_thinking,
    next_rung,
    result_validates,
    schema_shape_of,
)
from polymerhus.app.llm.sync_mapping import classify_reasoning_options

pytestmark = pytest.mark.live_neo4j  # no-op when live neo4j absent, keeps collection


class ClosedModel(BaseModel):
    name: str
    count: int


class OpenModel(BaseModel):
    name: str
    anchor: dict[str, Any]


class Inner(BaseModel):
    x: int


class Outer(BaseModel):
    inner: Inner


class WithDictAny(BaseModel):
    data: dict[str, Any]


def _profile(**kw) -> CapabilityProfile:
    return CapabilityProfile(**kw)


# C1
def test_C01_tools_bound_always_function_calling():
    for profile in [None, _profile(), _profile(supports_structured_output=True), _profile(supports_structured_output=False, supports_tool_calling=False)]:
        assert negotiate_method(profile, no_tools_bound=False, schema_shape="closed") == "function_calling"
        assert negotiate_method(profile, no_tools_bound=False, schema_shape="open") == "function_calling"


# C2
def test_C02_unknown_no_tools_defaults_json_schema():
    assert negotiate_method(None, no_tools_bound=True, schema_shape="closed") == "json_schema"
    assert negotiate_method(_profile(), no_tools_bound=True, schema_shape="open") == "json_schema"


# C3
def test_C03_structured_true_is_json_schema_both_shapes():
    p = _profile(supports_structured_output=True, supports_tool_calling=False)
    assert negotiate_method(p, True, "closed") == "json_schema"
    assert negotiate_method(p, True, "open") == "json_schema"


# C4
def test_C04_no_structured_but_tools_is_function_calling():
    for v in [False, None]:
        p = _profile(supports_structured_output=v, supports_tool_calling=True)
        assert negotiate_method(p, True, "closed") == "function_calling"


# C5
def test_C05_neither_is_json_mode_one_shot():
    p = _profile(supports_structured_output=False, supports_tool_calling=False)
    assert negotiate_method(p, True, "closed") == "json_mode"


# C6
def test_C06_session_neither_resolves_to_tool_strategy():
    from polymerhus.app.llm.session import _structured_response_format

    # monkeypatch a neither profile via env + fake capability
    from polymerhus.app.llm import capability as cap
    from polymerhus.app.llm import negotiation as neg

    cap._PROFILE_CACHE.clear()
    neg._PROBE_CACHE.clear()
    # Use a dummy schema, session seam should return ToolStrategy not json_object
    orig = os.environ.get("LLM_MODEL_TRIAGER")
    os.environ["LLM_MODEL_TRIAGER"] = "fake:matrix-neither"
    # inject profile directly via cache
    cap._PROFILE_CACHE[("fake", "matrix-neither")] = _profile(supports_structured_output=False, supports_tool_calling=False)
    try:
        fmt = _structured_response_format("triager", ClosedModel)
        # ToolStrategy has attribute schema or type; check not ProviderStrategy json_mode
        assert fmt is not None
        # ToolStrategy class name is ToolStrategy, json_mode would need ProviderStrategy with strict
        assert type(fmt).__name__ == "ToolStrategy"
    finally:
        cap._PROFILE_CACHE.clear()
        if orig is None:
            os.environ.pop("LLM_MODEL_TRIAGER", None)
        else:
            os.environ["LLM_MODEL_TRIAGER"] = orig


# C7
def test_C07_degrade_chain_and_next_rung_order():
    assert DEGRADE_CHAIN == ("json_schema", "function_calling", "json_mode")
    assert next_rung("json_schema") == "function_calling"
    assert next_rung("function_calling") == "json_mode"
    assert next_rung("json_mode") is None
    with pytest.raises(ValueError):
        next_rung("unknown")  # type: ignore[arg-type]


# C8
def test_C08_result_validates_companion():
    assert result_validates(None, ClosedModel) is False
    assert result_validates({"name": "a", "count": 1}, ClosedModel) is True
    assert result_validates({"name": "a"}, ClosedModel) is False
    assert result_validates({"ok": True}, {"type": "object"}) is True
    assert result_validates(None, {"type": "object"}) is False


# C9
def test_C09_schema_shape_both_map_same_rung():
    assert schema_shape_of(ClosedModel) == "closed"
    assert schema_shape_of(OpenModel) == "open"
    assert schema_shape_of(Outer) == "closed"
    assert schema_shape_of(WithDictAny) == "open"
    assert schema_shape_of({"not": "model"}) == "open"
    p = _profile(supports_structured_output=True)
    assert negotiate_method(p, True, "closed") == negotiate_method(p, True, "open")


# C10
def test_C10_absent_field_is_unknown_not_false(monkeypatch):
    from polymerhus.app.llm import capability as cap

    monkeypatch.setenv("LLM_GATEWAY_URL", "http://fake.invalid:4000")

    class FakeHttp:
        def get(self, url, headers=None):
            class R:
                status_code = 200

                def json(self):
                    return {"data": [{"model_name": "fake/m", "model_info": {"capability_source": "models.dev/fake/m", "capability_synced_at": "2026-08-11T12:00:00+00:00", "capability_staleness": "fresh", "supports_structured_output": "yes", "supports_function_calling": 1}}]}

            return R()

    cap._PROFILE_CACHE.clear()
    prof = cap.resolve_capability("fake", "m", http=FakeHttp())  # type: ignore[arg-type]
    assert prof.supports_structured_output is None
    assert prof.supports_tool_calling is None


# C11
def test_C11_off_maps_to_none_slot_or_omit():
    p_with = _profile(reasoning_control="effort", reasoning_efforts=("none", "low", "high"))
    assert negotiate_thinking("off", p_with) == ("effort", "none", "off-maps-to-offered-none-slot")
    p_without = _profile(reasoning_control="effort", reasoning_efforts=("low", "high"))
    assert negotiate_thinking("off", p_without)[0] == "omit"


# C12
def test_C12_thinking_exact_match():
    p = _profile(reasoning_control="effort", reasoning_efforts=("minimal", "low", "medium", "high"))
    assert negotiate_thinking("medium", p) == ("effort", "medium", "exact-match")


# C13
def test_C13_fallback_nearest_at_least_as_much():
    p = _profile(reasoning_control="effort", reasoning_efforts=("high", "max"))
    form, val, prov = negotiate_thinking("medium", p)
    assert val == "high"
    assert prov == "fallback-nearest-at-least-as-much"


# C14
def test_C14_fallback_none_when_no_level_at_or_above():
    p = _profile(reasoning_control="effort", reasoning_efforts=("low",))
    form, val, prov = negotiate_thinking("high", p)
    assert form == "omit" and val is None
    p2 = _profile(reasoning_control="effort", reasoning_efforts=("low", "high"))
    assert negotiate_thinking("max", p2)[0] == "omit"


# C15
def test_C15_toggle_only_semantics():
    p = _profile(reasoning_control="toggle", reasoning_efforts=None)
    assert negotiate_thinking("medium", p) == ("toggle", "on", "toggle-on")
    assert negotiate_thinking("off", p)[0] == "omit"


# C16
def test_C16_budget_canonical_map_and_clamp():
    p = _profile(reasoning_control="budget_tokens", thinking_budget_bounds=(2000, 10000))
    assert negotiate_thinking("medium", p) == ("budget", 4096, "budget-canonical-clamped")
    form, val, _ = negotiate_thinking("high", p)
    assert val == 10000  # clamped from 16384
    form2, val2, _ = negotiate_thinking("minimal", p)
    assert val2 == 2000  # clamped from 1024


# C17
def test_C17_always_on_and_unknown_thinking_fail_open():
    p_always = _profile(reasoning_control="none", reasoning_efforts=None)
    assert negotiate_thinking("medium", p_always)[0] == "omit"
    p_unknown = _profile()
    form, val, prov = negotiate_thinking("medium", p_unknown)
    assert form == "effort" and val == "medium" and prov == "unknown-profile-declared-kept"


# C18
def test_C18_null_canonicalized_to_none_off_slot():
    control, efforts, bounds = classify_reasoning_options([{"type": "effort", "values": [None, "low", "high"]}])
    assert efforts == ("none", "low", "high")
    p = _profile(reasoning_control=control, reasoning_efforts=efforts)
    assert negotiate_thinking("off", p)[1] == "none"
    assert negotiate_thinking("low", p)[1] == "low"


# C19
def test_C19_always_on_empty_list_is_omit():
    control, efforts, bounds = classify_reasoning_options([])
    assert control == "none" and efforts is None and bounds is None
    p = _profile(reasoning_control=control, reasoning_efforts=efforts)
    assert negotiate_thinking("medium", p)[0] == "omit"


# C20
def test_C20_invalid_budget_bounds_degrade_to_none():
    for bad in [[{"type": "budget_tokens", "min": -1, "max": 10000}], [{"type": "budget_tokens", "min": 5000}], [{"type": "budget_tokens", "min": 9000, "max": 1000}]]:
        control, efforts, bounds = classify_reasoning_options(bad)
        assert bounds is None


# C21
def test_C21_method_and_thinking_orthogonal_cross_product():
    p = _profile(supports_structured_output=True, reasoning_control="effort", reasoning_efforts=("low", "medium", "high"))
    m = negotiate_method(p, True, "closed")
    t = negotiate_thinking("medium", p)
    p2 = _profile(supports_structured_output=False, supports_tool_calling=True, reasoning_control="effort", reasoning_efforts=("low", "medium", "high"))
    m2 = negotiate_method(p2, True, "closed")
    t2 = negotiate_thinking("medium", p2)
    assert m == "json_schema" and m2 == "function_calling"
    assert t == t2  # thinking unchanged when method varies


# C22
def test_C22_probe_cache_hit_reused_without_probe():
    from polymerhus.app.llm.negotiation import _PROBE_CACHE, probe_with_invoker, resolve_method

    _PROBE_CACHE.clear()

    def invoker_ok(method):
        return {"name": "a", "count": 1} if method == "json_schema" else None

    winner = probe_with_invoker("prov", "m22", ClosedModel, invoker_ok)
    assert winner == "json_schema"
    # second resolve without invoker should hit cache
    prof = _profile()  # unknown
    method, prov = resolve_method(prof, ClosedModel, True, invoker=None, provider="prov", model="m22")
    assert prov == "probe-cache-hit"
    assert method == "json_schema"


# C23
def test_C23_all_miss_caches_none_next_is_json_schema():
    from polymerhus.app.llm.negotiation import _PROBE_CACHE, probe_with_invoker, resolve_method

    _PROBE_CACHE.clear()

    def invoker_none(_m):
        return None

    winner = probe_with_invoker("prov", "m23", ClosedModel, invoker_none)
    assert winner is None
    prof = _profile()
    method, _ = resolve_method(prof, ClosedModel, True, invoker=None, provider="prov", model="m23")
    assert method == "json_schema"


# C24
def test_C24_cold_start_session_unvalidated_sentinel():
    from polymerhus.app.llm.negotiation import _PROBE_CACHE, resolve_method

    _PROBE_CACHE.clear()
    prof = _profile()
    method, prov = resolve_method(prof, ClosedModel, True, invoker=None, provider="prov", model="m24")
    assert method == "json_schema"
    assert prov == "semantic-default-unvalidated; no prior probe entry"


# C25
def test_C25_gateway_forwards_reasoning_effort():
    from polymerhus.app.llm.providers import _thinking_wire_form

    # effort form should survive to wire via build_chat_model path
    # Use fake provider with effort profile via cache injection
    from polymerhus.app.llm import capability as cap

    cap._PROFILE_CACHE.clear()
    cap._PROFILE_CACHE[("fake", "c25model")] = _profile(reasoning_control="effort", reasoning_efforts=("low", "medium", "high"))
    os.environ["API_KEY_FAKE"] = "test"
    try:
        extra = _thinking_wire_form("fake", "c25model", "high")
        assert extra == {"reasoning_effort": "high"}
        # omit case
        cap._PROFILE_CACHE[("fake", "c25model")] = _profile(reasoning_control="none")
        extra2 = _thinking_wire_form("fake", "c25model", "high")
        assert extra2 == {}
    finally:
        cap._PROFILE_CACHE.clear()


# C26
def test_C26_thinking_wire_forms_emit_correct_extra():
    from polymerhus.app.llm.providers import _thinking_wire_form
    from polymerhus.app.llm import capability as cap

    cap._PROFILE_CACHE.clear()
    cap._PROFILE_CACHE[("fake", "c26effort")] = _profile(reasoning_control="effort", reasoning_efforts=("low", "high"))
    assert _thinking_wire_form("fake", "c26effort", "high") == {"reasoning_effort": "high"}
    cap._PROFILE_CACHE[("fake", "c26budget")] = _profile(reasoning_control="budget_tokens", thinking_budget_bounds=(1000, 50000))
    eff = _thinking_wire_form("fake", "c26budget", "medium")
    assert eff == {"extra_body": {"thinking": {"type": "enabled", "budget_tokens": 4096}}}
    cap._PROFILE_CACHE[("fake", "c26toggle")] = _profile(reasoning_control="toggle")
    assert _thinking_wire_form("fake", "c26toggle", "medium") == {"extra_body": {"thinking": {"type": "enabled"}}}
    cap._PROFILE_CACHE[("fake", "c26omit")] = _profile(reasoning_control="none")
    assert _thinking_wire_form("fake", "c26omit", "medium") == {}
    cap._PROFILE_CACHE.clear()
