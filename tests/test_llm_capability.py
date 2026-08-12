"""Unit tier for the capability-profile reader (#106, ADR D5/D6/D7/D11).

The reader is client-side (`app/llm/capability.py`), fail-open, provenance-gated
(D5 Rule 1), resolve-and-hold (process-lifetime static cache - operator
refinement 2026-08-11), and off the #73 retry axis. Every test mocks
`/model/info` with a recording fake HTTP client - no live gateway, no live
model (ticket AC: unit tier touches neither).

The mocked `/model/info` bodies use the exact wire shape T2 (#105) authors
(`sync_mapping.py`): the provenance keys `capability_source` /
`capability_synced_at` / `capability_staleness`, the D5 mapped fields
`max_input_tokens` / `max_output_tokens`, the D11 keys `reasoning_in_response`
/ `reasoning_field`, and the slash-form registered model name.
"""
import datetime as dt

import pytest
from polymerhus.app.llm import capability as C
from polymerhus.app.llm.providers import LLMConfigError


class FakeHttp:
    """Recording /model/info fake: `.get(url, headers=...)` returns the canned
    litellm `{"data": [...]}` body; the call is recorded for assertions."""

    def __init__(self, body, *, status_code=200, raises=None, json_raises=None):
        self.body = body
        self.status_code = status_code
        self.raises = raises
        self.json_raises = json_raises
        self.calls = []

    def get(self, url, headers=None):
        self.calls.append({"url": url, "headers": headers})
        if self.raises is not None:
            raise self.raises
        return _FakeResponse(self.status_code, self.body, self.json_raises)

    @property
    def call_count(self):
        return len(self.calls)


class _FakeResponse:
    def __init__(self, status_code, body, json_raises=None):
        self.status_code = status_code
        self._body = body
        self._json_raises = json_raises

    def json(self):
        if self._json_raises is not None:
            raise self._json_raises
        return self._body


def _record(model_name, **info):
    return {"model_name": model_name, "model_info": info}


def _tagged(model_name, **info):
    """A provenance-tagged record (T2-authored shape): the `capability_source`
    tag is always present; capability fields only when authored."""
    info.setdefault("capability_source", f"models.dev/{model_name}")
    info.setdefault("capability_synced_at", "2026-08-11T12:00:00+00:00")
    info.setdefault("capability_staleness", "fresh")
    return _record(model_name, **info)


ISO = "2026-08-11T12:00:00+00:00"


# ---------------------------------------------------------------------------
# The CapabilityProfile dataclass -------------------------------------------
# ---------------------------------------------------------------------------

def test_profile_fields_default_to_none():
    p = C.CapabilityProfile()
    assert p.context_limit is None
    assert p.output_limit is None
    assert p.supports_tool_calling is None
    assert p.source is None
    assert p.synced_at is None
    assert p.reasoning_in_response is None
    assert p.reasoning_field is None


def test_profile_has_no_reasoning_caching_field():
    """D11 grey point: reasoning caching is unassertable from the registry -
    runtime cache-hit tracking is T6's work; the profile must NOT carry a
    caching field."""
    import dataclasses

    names = {f.name for f in dataclasses.fields(C.CapabilityProfile)}
    assert not {n for n in names if "cache" in n.lower()}


# ---------------------------------------------------------------------------
# Provenance-gating (D5 Rule 1) ---------------------------------------------
# ---------------------------------------------------------------------------

def test_untagged_record_trusts_nothing(monkeypatch):
    """Rule 1 load-bearing case: litellm merges its own bundled cost-map
    defaults into model_info; a record WITHOUT `capability_source` must yield
    ALL-unknown capability fields - even when it carries capability-looking
    fields. context_limit then falls to the env chain (D6 step 2); the held
    env value (123000) proves the record's 200_000 was never trusted."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    monkeypatch.setenv("LLM_ROLE_MODEL_CONTEXT_LIMIT", "123000")
    fake = FakeHttp({"data": [
        _record("openai/gpt-4o",
                max_input_tokens=200_000, max_output_tokens=8_192,
                reasoning_in_response=True),
    ]})
    p = C.resolve_capability("openai", "gpt-4o", http=fake)
    assert p.context_limit == 123_000  # env chain, NOT the record's 200_000
    assert p.output_limit is None
    assert p.source is None
    assert p.synced_at is None
    assert p.reasoning_in_response is None
    assert p.reasoning_field is None
    assert fake.call_count == 1


def test_tagged_record_trusts_present_fields(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    fake = FakeHttp({"data": [
        _tagged("openrouter/anthropic/claude-3.7-sonnet",
                max_input_tokens=200_000, max_output_tokens=64_000),
    ]})
    p = C.resolve_capability("openrouter", "anthropic/claude-3.7-sonnet", http=fake)
    assert p.context_limit == 200_000
    assert p.output_limit == 64_000
    assert p.source == "models.dev/openrouter/anthropic/claude-3.7-sonnet"
    assert p.synced_at == dt.datetime(2026, 8, 11, 12, 0, tzinfo=dt.timezone.utc)
    assert p.reasoning_in_response is None
    assert p.reasoning_field is None


def test_tagged_record_absent_fields_are_unknown(monkeypatch):
    """Tag present but a field absent -> that field is unknown, never guessed.
    Uses a model key distinct from the untagged test (the process-lifetime
    cache is keyed per (provider, model))."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    fake = FakeHttp({"data": [
        _tagged("openrouter/anthropic/claude-3.5-sonnet-autosized",
                max_input_tokens=200_000),
    ]})
    p = C.resolve_capability("openrouter", "anthropic/claude-3.5-sonnet-autosized", http=fake)
    assert p.context_limit == 200_000
    assert p.output_limit is None  # absent -> unknown
    assert p.source == "models.dev/openrouter/anthropic/claude-3.5-sonnet-autosized"


def test_unknown_source_tag_carries_no_capabilities(monkeypatch):
    """D9 unknown-model path: the record is tagged but the tag value is the
    literal `unknown` and no capability fields are authored (T2's
    `unknown_model_info`); the reader resolves all fields unknown."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    fake = FakeHttp({"data": [
        _record("openrouter/swissai-unknown-model",
                capability_source="unknown",
                capability_synced_at=ISO,
                capability_staleness="unknown"),
    ]})
    p = C.resolve_capability("openrouter", "swissai-unknown-model", http=fake)
    assert p.context_limit == DEFAULT_CONTEXT  # unknown -> env (absent) -> 150k default
    assert p.output_limit is None
    assert p.source == "unknown"
    assert p.synced_at == dt.datetime(2026, 8, 11, 12, 0, tzinfo=dt.timezone.utc)


def test_reasoning_fields_are_provenance_gated(monkeypatch):
    """D11 surface + Rule 1: reasoning keys on a record WITHOUT the tag are
    ignored (litellm could be echoing something of its own); on a tagged
    record they are trusted."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    untagged = FakeHttp({"data": [
        _record("openrouter/untagged-reasoner",
                reasoning_in_response=True, reasoning_field="reasoning_content"),
    ]})
    p = C.resolve_capability("openrouter", "untagged-reasoner", http=untagged)
    assert p.reasoning_in_response is None
    assert p.reasoning_field is None

    tagged = FakeHttp({"data": [
        _tagged("openrouter/tagged-reasoner",
                reasoning_in_response=True, reasoning_field="reasoning_content"),
    ]})
    p = C.resolve_capability("openrouter", "tagged-reasoner", http=tagged)
    assert p.reasoning_in_response is True
    assert p.reasoning_field == "reasoning_content"


def test_reasoning_interleaved_true_authors_field_absent(monkeypatch):
    """D11 matrix, Anthropic-style: interleaved: true asserts
    reasoning_in_response with reasoning_field ABSENT (never authored)."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    fake = FakeHttp({"data": [
        _tagged("openrouter/claude-interleaved", reasoning_in_response=True),
    ]})
    p = C.resolve_capability("openrouter", "claude-interleaved", http=fake)
    assert p.reasoning_in_response is True
    assert p.reasoning_field is None


def test_reasoning_in_response_false_is_trusted_not_unknown(monkeypatch):
    """An explicitly asserted False is a trustworthy authored value, distinct
    from unknown (None): conservative-unknown is about ABSENCE, not about
    distrusting authored False."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    fake = FakeHttp({"data": [
        _tagged("openrouter/no-reasoning", reasoning_in_response=False),
    ]})
    p = C.resolve_capability("openrouter", "no-reasoning", http=fake)
    assert p.reasoning_in_response is False


# ---------------------------------------------------------------------------
# The D5 tool-calling surface (the T5 #108 crawl gate consumes this) ---------
# ---------------------------------------------------------------------------

def test_tool_calling_is_provenance_gated(monkeypatch):
    """D5: supports_tool_calling maps to the wire key `supports_function_calling`
    (the sync authors it, `sync_mapping.py`). Rule 1: an UNTAGGED record's
    tool-calling flag is NEVER trusted (litellm could be echoing something of
    its own); a TAGGED record's flag is trusted."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    untagged = FakeHttp({"data": [
        _record("openrouter/untagged-toolcaller",
                supports_function_calling=True, supports_parallel_function_calling=True),
    ]})
    p = C.resolve_capability("openrouter", "untagged-toolcaller", http=untagged)
    assert p.supports_tool_calling is None

    tagged = FakeHttp({"data": [
        _tagged("openrouter/tagged-toolcaller", supports_function_calling=True),
    ]})
    p = C.resolve_capability("openrouter", "tagged-toolcaller", http=tagged)
    assert p.supports_tool_calling is True


def test_tool_calling_true_is_read_from_the_function_calling_key(monkeypatch):
    """The profile value comes from the mapped `supports_function_calling` key -
    the D5 wire field the sync authors from the canonical record."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    fake = FakeHttp({"data": [
        _tagged("openrouter/function-calling-wire",
                supports_function_calling=True, supports_parallel_function_calling=True),
    ]})
    p = C.resolve_capability("openrouter", "function-calling-wire", http=fake)
    assert p.supports_tool_calling is True


def test_tool_calling_absent_field_is_unknown(monkeypatch):
    """Tag present but the tool-calling field absent -> unknown (None), never
    guessed - the crawl gate must REFUSE on this state (spec §5)."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    fake = FakeHttp({"data": [
        _tagged("openrouter/tagged-no-toolkey", max_input_tokens=200_000),
    ]})
    p = C.resolve_capability("openrouter", "tagged-no-toolkey", http=fake)
    assert p.supports_tool_calling is None


def test_tool_calling_false_is_trusted_not_unknown(monkeypatch):
    """An explicitly authored False is a trustworthy value - the crawl gate
    REFUSES on it, distinct from the unknown (None) state it also refuses on."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    fake = FakeHttp({"data": [
        _tagged("openrouter/no-tool-calling", supports_function_calling=False),
    ]})
    p = C.resolve_capability("openrouter", "no-tool-calling", http=fake)
    assert p.supports_tool_calling is False


def test_tool_calling_wrong_typed_wire_value_degrades_to_unknown(monkeypatch):
    """The typed profile contract: a wrong-typed wire value degrades to
    unknown (None) - the crawl gate then REFUSES rather than trusting a
    string that looks true."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    fake = FakeHttp({"data": [
        _tagged("openrouter/toolkey-wrong-typed", supports_function_calling="yes"),
    ]})
    p = C.resolve_capability("openrouter", "toolkey-wrong-typed", http=fake)
    assert p.supports_tool_calling is None


# ---------------------------------------------------------------------------
# Resolution order (D6): gateway -> env -> 150k default ----------------------
# ---------------------------------------------------------------------------

DEFAULT_CONTEXT = 150_000


def test_context_gateway_beats_env_override(monkeypatch):
    """Never the reverse: an env override must not shadow a fresh synced
    record (D6 rationale)."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    monkeypatch.setenv("LLM_ROLE_MODEL_CONTEXT_LIMIT", "123000")
    fake = FakeHttp({"data": [
        _tagged("openrouter/gateway-wins", max_input_tokens=200_000),
    ]})
    p = C.resolve_capability("openrouter", "gateway-wins", http=fake)
    assert p.context_limit == 200_000


def test_context_env_beats_default_when_gateway_silent(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    monkeypatch.setenv("LLM_ROLE_MODEL_CONTEXT_LIMIT", "90000")
    fake = FakeHttp({"data": [
        _tagged("openrouter/env-beats-default"),  # no max_input_tokens authored
    ]})
    p = C.resolve_capability("openrouter", "env-beats-default", http=fake)
    assert p.context_limit == 90_000
    assert p.output_limit is None


def test_context_defaults_to_150k_when_gateway_and_env_silent(monkeypatch):
    """The SwissAI-is-not-on-models.dev gap takes the 150k default (D6)."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    monkeypatch.delenv("LLM_ROLE_MODEL_CONTEXT_LIMIT", raising=False)
    fake = FakeHttp({"data": [
        _tagged("swissai/meta-llama/Llama-3.3-70B-Instruct"),
    ]})
    p = C.resolve_capability("swissai", "meta-llama/Llama-3.3-70B-Instruct", http=fake)
    assert p.context_limit == DEFAULT_CONTEXT
    assert p.output_limit is None


def test_invalid_env_override_raises_config_error(monkeypatch):
    """Operator ruling 2026-08-11: an unusable env override is a config lie and
    fails fast (LLMConfigError, the providers.py precedent) - it is caught by
    the app-module config validation component (#112) at control-plane launch,
    not silently degraded."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    monkeypatch.setenv("LLM_ROLE_MODEL_CONTEXT_LIMIT", "not-a-number")
    fake = FakeHttp({"data": [
        _tagged("openrouter/silent-gateway"),
    ]})
    with pytest.raises(LLMConfigError, match="LLM_ROLE_MODEL_CONTEXT_LIMIT"):
        C.resolve_capability("openrouter", "silent-gateway", http=fake)


def test_nonpositive_env_override_raises_config_error(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    monkeypatch.setenv("LLM_ROLE_MODEL_CONTEXT_LIMIT", "0")
    fake = FakeHttp({"data": [
        _tagged("openrouter/silent-gateway"),
    ]})
    with pytest.raises(LLMConfigError, match="LLM_ROLE_MODEL_CONTEXT_LIMIT"):
        C.resolve_capability("openrouter", "silent-gateway", http=fake)


def test_output_limit_has_no_env_fallback(monkeypatch):
    """D6: output_limit resolves gateway-only; `None` when missing; the
    consumer (#95) decides. The context env override must not leak into it."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    monkeypatch.setenv("LLM_ROLE_MODEL_CONTEXT_LIMIT", "90000")
    fake = FakeHttp({"data": [
        _tagged("openrouter/no-output", max_input_tokens=200_000),
    ]})
    p = C.resolve_capability("openrouter", "no-output", http=fake)
    assert p.context_limit == 200_000
    assert p.output_limit is None


# ---------------------------------------------------------------------------
# Fail-open (D7): an unreachable/missing gateway never raises ----------------
# ---------------------------------------------------------------------------

def test_fail_open_on_connection_error(monkeypatch, caplog):
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    monkeypatch.setenv("LLM_ROLE_MODEL_CONTEXT_LIMIT", "80000")
    fake = FakeHttp({"data": []}, raises=ConnectionError("gateway down"))
    p = C.resolve_capability("openrouter", "connection-error", http=fake)
    assert p.context_limit == 80_000  # env fallback; session must start
    assert p.output_limit is None
    assert "gateway" in caplog.text.lower()  # the gap is surfaced


def test_fail_open_gateway_unconfigured_skips_fetch(monkeypatch):
    """No LLM_GATEWAY_URL -> the reader never attempts HTTP; env -> default."""
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    monkeypatch.setenv("LLM_ROLE_MODEL_CONTEXT_LIMIT", "70000")
    fake = FakeHttp({"data": []})
    p = C.resolve_capability("openrouter", "unconfigured", http=fake)
    assert p.context_limit == 70_000
    assert fake.call_count == 0


def test_fail_open_on_http_error_status(monkeypatch, caplog):
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    fake = FakeHttp({"data": []}, status_code=500)
    p = C.resolve_capability("openrouter", "http-500", http=fake)
    assert p.context_limit == DEFAULT_CONTEXT
    assert "gateway" in caplog.text.lower()


def test_fail_open_on_malformed_body(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    fake = FakeHttp({"unexpected": True})  # no "data" list
    p = C.resolve_capability("openrouter", "malformed", http=fake)
    assert p.context_limit == DEFAULT_CONTEXT


def test_fail_open_on_unparsable_json(monkeypatch, caplog):
    """The gateway answers HTTP 200 with a body that fails to parse as JSON:
    same fail-open contract as a transport error - env -> default, gap logged."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    monkeypatch.setenv("LLM_ROLE_MODEL_CONTEXT_LIMIT", "88000")
    fake = FakeHttp({"data": []}, json_raises=ValueError("not json"))
    p = C.resolve_capability("openrouter", "bad-json", http=fake)
    assert p.context_limit == 88_000
    assert "gateway" in caplog.text.lower()


def test_fail_open_model_not_registered(monkeypatch, caplog):
    """The gateway is up but has no record for this (provider, model): unknown
    -> env -> default, gap logged."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    monkeypatch.setenv("LLM_ROLE_MODEL_CONTEXT_LIMIT", "85000")
    fake = FakeHttp({"data": [
        _tagged("openrouter/some-other-model", max_input_tokens=1_000_000),
    ]})
    p = C.resolve_capability("openrouter", "not-registered", http=fake)
    assert p.context_limit == 85_000
    assert "not-registered" in caplog.text


def test_unparsable_synced_at_degrades_not_the_profile(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    fake = FakeHttp({"data": [
        _record("openrouter/bad-synced-at",
                capability_source="models.dev/x", capability_synced_at="garbage",
                capability_staleness="fresh", max_input_tokens=200_000),
    ]})
    p = C.resolve_capability("openrouter", "bad-synced-at", http=fake)
    assert p.context_limit == 200_000  # capability still trusted
    assert p.synced_at is None  # unparsable timestamp -> unknown, logged


def test_wrong_typed_wire_values_degrade_to_unknown(monkeypatch):
    """The profile is a typed contract; a wrong-typed wire value (e.g. a
    string token count - the wire is untrusted) degrades to unknown rather
    than leaking a wrong type to #95/#99. Context then falls to env/default."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    fake = FakeHttp({"data": [
        _tagged("openrouter/wrong-typed",
                max_input_tokens="200000", max_output_tokens=True,
                reasoning_in_response="yes", reasoning_field=123),
    ]})
    p = C.resolve_capability("openrouter", "wrong-typed", http=fake)
    assert p.context_limit == DEFAULT_CONTEXT  # string count -> unknown -> default
    assert p.output_limit is None  # bool output -> unknown
    assert p.reasoning_in_response is None
    assert p.reasoning_field is None


# ---------------------------------------------------------------------------
# Resolve-and-hold: process-lifetime static cache (operator 2026-08-11) ------
# ---------------------------------------------------------------------------

def test_resolve_and_hold_caches_per_model(monkeypatch):
    """One resolution per (provider, model), held forever; a second call for
    the SAME model never re-queries; a different model resolves separately."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    fake = FakeHttp({"data": [
        _tagged("openrouter/shared-model", max_input_tokens=200_000),
    ]})
    a = C.resolve_capability("openrouter", "shared-model", http=fake)
    b = C.resolve_capability("openrouter", "shared-model", http=fake)
    assert a is b  # the SAME held profile object
    assert fake.call_count == 1

    other = FakeHttp({"data": [
        _tagged("openrouter/other-model", max_input_tokens=150_000),
    ]})
    C.resolve_capability("openrouter", "other-model", http=other)
    assert other.call_count == 1


def test_failed_read_is_held_never_retried(monkeypatch):
    """Off the retry axis by construction: even a FAILED read is a single,
    never-retried attempt whose degraded result is held - no second chance
    query, no retry loop inside the reader (that is #73's axis, not this one)."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    failing = FakeHttp({"data": []}, raises=ConnectionError("gone"))
    a = C.resolve_capability("openrouter", "never-retried", http=failing)
    assert a.context_limit == DEFAULT_CONTEXT
    b = C.resolve_capability("openrouter", "never-retried", http=failing)
    assert a is b
    assert failing.call_count == 1  # exactly one read, held


def test_sync_single_read_of_model_info(monkeypatch):
    """The reader performs exactly one GET /model/info; never invokes the
    escalating wrapper (no wrap in invoke_with_escalating_timeout - the reader
    has no retry seam at all)."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    fake = FakeHttp({"data": [
        _tagged("openrouter/one-get", max_input_tokens=200_000),
    ]})
    C.resolve_capability("openrouter", "one-get", http=fake)
    assert fake.call_count == 1
    assert fake.calls[0]["url"].endswith("/model/info")


def test_auth_bearer_from_master_key(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "sk-live-secret")
    fake = FakeHttp({"data": [
        _tagged("openrouter/authed", max_input_tokens=200_000),
    ]})
    C.resolve_capability("openrouter", "authed", http=fake)
    assert fake.calls[0]["headers"]["Authorization"] == "Bearer sk-live-secret"


def test_no_auth_header_without_master_key(monkeypatch):
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    monkeypatch.delenv("LITELLM_MASTER_KEY", raising=False)
    fake = FakeHttp({"data": [
        _tagged("openrouter/open-gateway", max_input_tokens=200_000),
    ]})
    C.resolve_capability("openrouter", "open-gateway", http=fake)
    headers = fake.calls[0]["headers"] or {}
    assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# Lookup key: the T2 registered-name convention (slash form, zen strip) ------
# ---------------------------------------------------------------------------

def test_zen_family_matches_stripped_registered_name(monkeypatch):
    """D5: the zen-family id strip moves into the mapping layer; the gateway
    registers the stripped slash form (`opencode/deepseek-v4-flash-free`), and
    the reader must look that up - not the prefixed env form."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway.invalid:4000")
    fake = FakeHttp({"data": [
        _tagged("opencode/deepseek-v4-flash-free", max_input_tokens=200_000),
    ]})
    p = C.resolve_capability("opencode", "deepseek/deepseek-v4-flash-free", http=fake)
    assert p.context_limit == 200_000
    assert p.source == "models.dev/opencode/deepseek-v4-flash-free"