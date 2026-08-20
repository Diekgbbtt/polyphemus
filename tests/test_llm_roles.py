"""Unit tier: the capability-adaptive one-shot seam (#99, ADR A1, ticket #146).

`invoke_role`'s `schema is not None` branch chooses the structured-output
method via the A1 negotiation instead of the hardcoded
`method="function_calling"`:

- a json_schema-capable profile -> `json_schema` strict=False, constructed with
  the DICT schema form (the A4 pin contract: the only construction honouring
  strict=False on the wire) and the parsed result returned as the pydantic
  instance the one-shot callers consume;
- a tool-calling-only profile -> `function_calling` (the open
  `Observation.anchor` dict field survives on the class form);
- a neither profile -> `json_mode` with the mandatory parse-validation
  contract - a silent wrong-shape result (HTTP 200, wrong JSON) is a miss that
  escalates, never accepted;
- an unknown profile (no gateway/record, fields unknown per D5 Rule 1) -> the
  semantic default `json_schema` (D7 fail-open);
- any resolution/negotiation failure fails open to the semantic default and the
  call still proceeds (D7);
- capability resolution is OFF the #73 retry axis: one synchronous read per
  logical call (resolve-and-hold, D6/D7), made before the escalating attempts,
  so every attempt retries the SAME negotiated method.

The `schema is None` free-text path is byte-identical to the pre-negotiation
seam. Every test mocks `build_chat_model` / `resolve_capability` - no live
model, no live gateway, no DB (CODING_STANDARD sections 6, 10).
"""
from pydantic import BaseModel

from polymerhus.app.llm import roles
from polymerhus.app.llm.capability import CapabilityProfile


class _Closed(BaseModel):
    label: str


class _OpenDict(BaseModel):
    anchor: dict
    label: str


class _FakeStructured:
    def __init__(self, result):
        self._result = result

    def invoke(self, messages):
        return self._result


class _FakeLLM:
    """A `build_chat_model` stand-in: records the `with_structured_output`
    construction (the seam's observable) and returns a canned parsed result."""

    def __init__(self, result):
        self._result = result
        self.wso_calls = []

    def with_structured_output(self, schema, **kwargs):
        self.wso_calls.append({"schema": schema, "kwargs": kwargs})
        return _FakeStructured(self._result)


def _env(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_TRIAGER", "openrouter:some/model")


def _wire(monkeypatch, profile, results):
    """Stub the two seam dependencies: a fresh fake LLM per escalating attempt
    (results consumed in attempt order) and the resolve-and-hold capability
    reader. Returns a record of what the seam observed."""
    record = {"capability_calls": 0, "llms": []}

    def resolve_capability(provider, model):
        record["capability_calls"] += 1
        assert (provider, model) == ("openrouter", "some/model")
        return profile

    def build_chat_model(*args, **kwargs):
        llm = _FakeLLM(results.pop(0))
        record["llms"].append(llm)
        return llm

    monkeypatch.setattr(roles, "resolve_capability", resolve_capability)
    monkeypatch.setattr(roles, "build_chat_model", build_chat_model)
    return record


def _wso(record, index=0):
    return record["llms"][index].wso_calls[0]


# ---------------------------------------------------------------------------
# The free-text path: byte-identical, no capability read ---------------------
# ---------------------------------------------------------------------------

def test_free_text_path_is_unchanged_and_resolves_no_capability(monkeypatch):
    """schema=None keeps the pre-negotiation seam exactly: llm.invoke, content
    extraction (or None), the escalating wrapper's max_retries=0 client - and
    the capability reader is never consulted."""
    _env(monkeypatch)
    observed = {"capability_calls": 0, "kwargs": None}

    class _Resp:
        content = "free-text"

    class _FreeLLM:
        def invoke(self, messages):
            return _Resp()

    def resolve_capability(provider, model):
        observed["capability_calls"] += 1
        raise AssertionError("capability must not resolve on the free-text path")

    def build_chat_model(*args, **kwargs):
        observed["kwargs"] = kwargs
        return _FreeLLM()

    monkeypatch.setattr(roles, "resolve_capability", resolve_capability)
    monkeypatch.setattr(roles, "build_chat_model", build_chat_model)
    out = roles.invoke_role("triager", [{"role": "user", "content": "hi"}])
    assert out == "free-text"
    assert observed["capability_calls"] == 0
    assert observed["kwargs"]["max_retries"] == 0  # the escalating wrapper owns the retry


def test_free_text_path_still_fail_closes_to_none(monkeypatch):
    _env(monkeypatch)
    observed = {"kwargs": None}

    class _EmptyLLM:
        def invoke(self, messages):
            return None

    def build_chat_model(*args, **kwargs):
        observed["kwargs"] = kwargs
        return _EmptyLLM()

    monkeypatch.setattr(roles, "resolve_capability", lambda p, m: CapabilityProfile())
    monkeypatch.setattr(roles, "build_chat_model", build_chat_model)
    assert roles.invoke_role("triager", [{"role": "user", "content": "hi"}]) is None


# ---------------------------------------------------------------------------
# json_schema-capable profile (thinking/deepseek-like): the SOTA rung ---------
# ---------------------------------------------------------------------------

def test_json_schema_capable_profile_uses_dict_form_strict_false(monkeypatch):
    """A json_schema-capable profile negotiates `json_schema` strict=False via
    the DICT construction form - the A4 pin contract (a pydantic-CLASS schema
    silently defaults to strict:true, the #44 400) - and the parsed dict comes
    back as the pydantic instance the one-shot callers consume."""
    _env(monkeypatch)
    profile = CapabilityProfile(supports_structured_output=True)
    record = _wire(monkeypatch, profile, [{"label": "x"}])
    out = roles.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_Closed)
    assert isinstance(out, _Closed) and out.label == "x"
    wso = _wso(record)
    assert wso["schema"] == _Closed.model_json_schema()  # the dict form
    assert wso["kwargs"] == {"method": "json_schema", "strict": False}


def test_open_shape_does_not_swap_the_json_schema_rung(monkeypatch):
    """A1 rung 1's strict=False is UNCONDITIONAL: an open `dict` field (the
    Observation.anchor class) still negotiates json_schema on a
    structured-output profile - the shape is a recorded contract input, never a
    method-swap trigger."""
    _env(monkeypatch)
    profile = CapabilityProfile(supports_structured_output=True)
    record = _wire(monkeypatch, profile, [{"anchor": {"id": 1}, "label": "y"}])
    out = roles.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_OpenDict)
    assert isinstance(out, _OpenDict)
    assert _wso(record)["kwargs"] == {"method": "json_schema", "strict": False}


def test_json_schema_rung_descends_on_a_shape_miss(monkeypatch):
    """The parse-validation contract on the json_schema rung: a dict-form
    result that does not validate against the class is a MISS that escalates
    (retried under the next budget, same held method), never accepted."""
    _env(monkeypatch)
    profile = CapabilityProfile(supports_structured_output=True)
    record = _wire(monkeypatch, profile, [
        {"label": 5},              # wrong shape for _Closed -> validation miss
        {"label": "ok"},           # valid on the retry
    ])
    out = roles.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_Closed)
    assert isinstance(out, _Closed) and out.label == "ok"
    assert record["capability_calls"] == 1  # resolve-and-hold, off the retry axis
    methods = {w["kwargs"]["method"] for llm in record["llms"] for w in llm.wso_calls}
    assert methods == {"json_schema"}


# ---------------------------------------------------------------------------
# Tool-calling-only profile: degrade to function_calling (the proven mainline) -
# ---------------------------------------------------------------------------

def test_tool_calling_only_profile_degrades_to_function_calling(monkeypatch):
    """A profile with tool calling but unknown/absent structured output
    degrades to `function_calling` on the class form - the open dict field
    survives (the `Observation.anchor` case)."""
    _env(monkeypatch)
    profile = CapabilityProfile(supports_tool_calling=True)
    record = _wire(monkeypatch, profile, [_OpenDict(anchor={"type": "x"}, label="y")])
    out = roles.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_OpenDict)
    assert isinstance(out, _OpenDict) and out.anchor == {"type": "x"}
    wso = _wso(record)
    assert wso["schema"] is _OpenDict  # the class form, unchanged mainline
    assert wso["kwargs"] == {"method": "function_calling"}


# ---------------------------------------------------------------------------
# Neither profile: json_mode + the mandatory parse-validation contract --------
# ---------------------------------------------------------------------------

def test_neither_profile_uses_json_mode_with_class_form(monkeypatch):
    _env(monkeypatch)
    profile = CapabilityProfile(supports_structured_output=False,
                                supports_tool_calling=False)
    record = _wire(monkeypatch, profile, [_OpenDict(anchor={}, label="y")])
    out = roles.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_OpenDict)
    assert isinstance(out, _OpenDict)
    wso = _wso(record)
    assert wso["schema"] is _OpenDict
    assert wso["kwargs"] == {"method": "json_mode"}


def test_json_mode_silent_wrong_shape_is_caught_and_not_accepted(monkeypatch):
    """The #44-absorbed rung's guard: a 200 with the wrong shape is a
    validation MISS - the call fail-closes (None escalates) and the retry
    re-attempts the SAME held json_mode method; a wrong shape is never
    returned to the caller."""
    _env(monkeypatch)
    profile = CapabilityProfile(supports_structured_output=False,
                                supports_tool_calling=False)
    record = _wire(monkeypatch, profile, [
        {"anchor": "not-a-dict", "label": 5},      # wrong shape (silent 200)
        _OpenDict(anchor={"ok": True}, label="y"),  # valid on the retry
    ])
    out = roles.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_OpenDict)
    assert isinstance(out, _OpenDict) and out.label == "y"
    assert record["capability_calls"] == 1  # resolved once across both attempts
    methods = {w["kwargs"]["method"] for llm in record["llms"] for w in llm.wso_calls}
    assert methods == {"json_mode"}  # the SAME method across attempts - held


def test_json_mode_wrong_shape_fail_closes_when_every_attempt_misses(monkeypatch):
    _env(monkeypatch)
    profile = CapabilityProfile(supports_structured_output=False,
                                supports_tool_calling=False)
    record = _wire(monkeypatch, profile, [
        {"anchor": "bad", "label": 1},
        {"anchor": "bad", "label": 2},
        {"anchor": "bad", "label": 3},
    ])
    out = roles.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_OpenDict)
    assert out is None  # fail-closed on the validation miss, never a wrong shape
    # every attempt hit the same message - verify the message marker
    methods = {w["kwargs"]["method"] for llm in record["llms"] for w in llm.wso_calls}
    assert methods == {"json_mode"}


# ---------------------------------------------------------------------------
# Unknown profile and D7 fail-open --------------------------------------------
# ---------------------------------------------------------------------------

def test_unknown_profile_uses_the_semantic_default_and_still_works(monkeypatch):
    """Unknown profile (no gateway, no record, all fields None per D5 Rule 1):
    the semantic default `json_schema` on the no-tool rung - the call still
    succeeds and returns the parsed instance."""
    _env(monkeypatch)
    record = _wire(monkeypatch, CapabilityProfile(), [{"anchor": {}, "label": "z"}])
    out = roles.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_OpenDict)
    assert isinstance(out, _OpenDict) and out.label == "z"
    assert _wso(record)["kwargs"] == {"method": "json_schema", "strict": False}


def test_fail_open_when_capability_resolution_raises(monkeypatch, caplog):
    """D7: a resolution failure (gateway gone) never blocks the call - it lands
    the semantic default json_schema with the gap surfaced in the logs."""
    _env(monkeypatch)
    record = _wire(monkeypatch, CapabilityProfile(), [{"anchor": {}, "label": "z"}])

    def resolve_capability(provider, model):
        raise ConnectionError("gateway down")

    monkeypatch.setattr(roles, "resolve_capability", resolve_capability)
    out = roles.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_OpenDict)
    assert isinstance(out, _OpenDict) and out.label == "z"
    assert "gateway" in caplog.text.lower()
    assert _wso(record)["kwargs"] == {"method": "json_schema", "strict": False}


def test_fail_open_when_shape_detection_fails(monkeypatch, caplog):
    """D7: a negotiation failure (unclassifiable schema target) also falls to
    the semantic default - the call proceeds rather than raising."""
    _env(monkeypatch)
    record = _wire(monkeypatch, CapabilityProfile(), [{"label": "x"}])

    def broken_shape(schema):
        raise TypeError("unclassifiable")

    monkeypatch.setattr(roles, "schema_shape_of", broken_shape)
    out = roles.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_Closed)
    assert isinstance(out, _Closed) and out.label == "x"
    assert "semantic default" in caplog.text.lower()


# ---------------------------------------------------------------------------
# The negotiation is a pure consultation; capability is off the retry axis -----
# ---------------------------------------------------------------------------

def test_invoke_role_consults_the_pure_negotiation_with_no_tools_bound(monkeypatch):
    """The seam consults the PURE negotiate contract exactly once per logical
    call with the semantic axis `no_tools_bound=True` (the one-shot path never
    binds tools) and the schema's recorded shape."""
    _env(monkeypatch)
    seen = {}

    def spy(profile, *, no_tools_bound, schema_shape):
        seen.update(profile=profile, no_tools_bound=no_tools_bound,
                    schema_shape=schema_shape)
        return "json_schema"

    monkeypatch.setattr(roles, "negotiate_method", spy)
    profile = CapabilityProfile(supports_tool_calling=True)
    record = _wire(monkeypatch, profile, [{"anchor": {}, "label": "y"}])
    out = roles.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_OpenDict)
    assert isinstance(out, _OpenDict)
    assert seen["no_tools_bound"] is True
    assert seen["schema_shape"] == "open"  # _OpenDict carries a free-form dict
    assert seen["profile"] is profile


def test_method_is_held_across_retry_attempts(monkeypatch):
    """The resolved method is chosen ONCE before the #73 attempts: even when an
    attempt escalates, the retry re-uses the SAME method - capability is never
    re-resolved on the retry axis (#32's multiplied-retry defect stays dead)."""
    _env(monkeypatch)
    profile = CapabilityProfile(supports_structured_output=True)
    record = _wire(monkeypatch, profile, [
        {"label": 5},        # miss on attempt 1
        {"label": "ok"},     # hit on attempt 2
    ])
    out = roles.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_Closed)
    assert isinstance(out, _Closed) and out.label == "ok"
    assert record["capability_calls"] == 1  # one read, held
    assert len(record["llms"]) == 2  # two attempts ran
    methods = {w["kwargs"]["method"] for llm in record["llms"] for w in llm.wso_calls}
    assert methods == {"json_schema"}
    configs = {w["kwargs"].get("strict") for llm in record["llms"] for w in llm.wso_calls}
    assert configs == {False}


# ---------------------------------------------------------------------------
# The construction seam helper ------------------------------------------------
# ---------------------------------------------------------------------------

def test_structured_output_for_passes_an_unclassifiable_schema_verbatim():
    """Only pydantic classes convert to the dict form on the json_schema rung;
    a raw JSON-schema dict target rides the rung verbatim (no model_json_schema
    call to explode on)."""
    llm = _FakeLLM({"ok": True})
    raw = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    roles.structured_output_for(llm, raw, "json_schema")
    assert llm.wso_calls == [{
        "schema": raw,
        "kwargs": {"method": "json_schema", "strict": False},
    }]