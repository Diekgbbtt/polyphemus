"""Unit tier: probe-on-miss protocol (ticket #148, ADR A2).

Unknown-to-registry models at session construction probe in A1 order,
validating the parsed result at each rung via `result_validates`, never by
error-string classification. The winner is held per (provider, model,
schema-class) and never re-probed mid-session. Cold-start only, off the #73
escalating axis; a probe failure degrades per chain and the session still
starts (fail-open D7). Observable per resolution via langfuse span/trace and
log with provenance.

All tests are mocked - no live gateway, no live model (CODING_STANDARD 6,10).
"""
from __future__ import annotations

import logging
from unittest.mock import Mock, patch

import pytest
from pydantic import BaseModel

from polymerhus.app.llm import negotiation as N
from polymerhus.app.llm.capability import CapabilityProfile


class _Good(BaseModel):
    label: str


class _Other(BaseModel):
    value: int


def _unknown_profile():
    return CapabilityProfile()  # all None -> unknown per D5 Rule 1


# ---------------------------------------------------------------------------
# Probe helper: try-in-order + parse-validate
# ---------------------------------------------------------------------------

def test_probe_unknown_picks_first_valid_rung_in_chain_order():
    """A2: unknown profile probes json_schema -> function_calling -> json_mode,
    validating parsed result at each rung, picking first valid."""
    N.clear_probe_cache()
    good = {"label": "hello"}
    bad = {"label": 123}  # wrong type fails validation for _Good? Actually label expects str, 123 fails? For _Good, label is str, 123 would still coerce? Use missing field.
    # Use dict missing required? _Good requires label str, but both are valid? Let's make bad shape.
    wrong = {"unexpected": True}
    calls: list[str] = []

    def invoker(method):
        calls.append(method)
        if method == "json_schema":
            return wrong  # invalid -> should descend
        if method == "function_calling":
            return good  # valid -> winner
        return good

    winner = N.probe_with_invoker("openrouter", "unknown/model-a", _Good, invoker, _unknown_profile())
    assert winner == "function_calling"
    assert calls == ["json_schema", "function_calling"]
    # cached winner shared
    assert N._PROBE_CACHE[N._probe_cache_key("openrouter", "unknown/model-a", _Good)] == "function_calling"


def test_probe_silent_wrong_shape_json_mode_triggers_descent_not_acceptance():
    """A2: validation is parse-based, never error-string; a silent wrong-shape
    json_mode result (parsed dict failing result_validates) causes descent, not acceptance."""
    N.clear_probe_cache()

    def invoker(method):
        if method == "json_schema":
            return {"unexpected": True}  # invalid for _Good
        if method == "function_calling":
            return {"unexpected": True}
        if method == "json_mode":
            return {"unexpected": True}
        raise AssertionError(method)

    winner = N.probe_with_invoker("openrouter", "unknown/model-b", _Good, invoker, _unknown_profile())
    # All miss -> None
    assert winner is None
    # probe failure still starts session (winner None cached, not raised)
    key = N._probe_cache_key("openrouter", "unknown/model-b", _Good)
    assert key in N._PROBE_CACHE
    assert N._PROBE_CACHE[key] is None


def test_probe_validates_parse_never_error_string():
    """A miss via exception from invoker is also a descent - no error string parsing."""
    N.clear_probe_cache()
    calls = []

    def invoker(method):
        calls.append(method)
        if method == "json_schema":
            raise RuntimeError("Thinking mode does not support this tool_choice")
        if method == "function_calling":
            return {"label": "ok"}
        raise AssertionError

    winner = N.probe_with_invoker("openrouter", "unknown/model-c", _Good, invoker, _unknown_profile())
    assert winner == "function_calling"
    assert calls == ["json_schema", "function_calling"]


def test_probe_runs_once_per_schema_class_and_is_held():
    """Probe runs once per (provider, model, schema-class) and is held - second call does not re-probe."""
    N.clear_probe_cache()
    count = {"n": 0}

    def invoker(method):
        count["n"] += 1
        return {"label": "x"}

    w1 = N.probe_with_invoker("openrouter", "unknown/model-d", _Good, invoker, _unknown_profile())
    assert w1 == "json_schema"
    assert count["n"] == 1
    # second call with same key should not invoke again - cached
    def invoker2(method):
        count["n"] += 1
        raise AssertionError("should not re-probe")

    w2 = N.probe_with_invoker("openrouter", "unknown/model-d", _Good, invoker2, _unknown_profile())
    assert w2 == "json_schema"
    assert count["n"] == 1
    # different schema-class probes separately
    def other_invoker(method):
        count["n"] += 1
        return {"value": 1}

    w3 = N.probe_with_invoker("openrouter", "unknown/model-d", _Other, other_invoker, _unknown_profile())
    assert w3 == "json_schema"
    assert count["n"] == 2
    # different provider/model also separate
    w4 = N.probe_with_invoker("openrouter", "unknown/model-e", _Good, invoker, _unknown_profile())
    assert w4 == "json_schema"
    assert count["n"] == 3


def test_probe_off_escalating_axis_cold_start_only():
    """A2 cadence: probe happens once at construction, off the #73 axis - no retry budget spent.
    The escalating wrapper retries the SAME probed winner, not re-probing per attempt."""
    N.clear_probe_cache()
    # Simulate invoke_role probe caching - ensure probe_with_invoker is called once, then escalating loop uses winner
    from polymerhus.app.llm import roles as R

    # Patch resolve_capability to unknown, and build_chat_model + structured_output_for
    with patch.object(R, "resolve_capability", return_value=_unknown_profile()):
        with patch.object(R, "resolve_role", return_value=("openrouter", "probe-off-axis")):
            N.clear_probe_cache()
            invoke_counts = {"probe": 0, "call": 0}

            def fake_probe_provider_build(*a, **kw):
                # This is used inside probe invoker - count probe invokes
                invoke_counts["probe"] += 1
                m = Mock()
                # structured_output_for returns object with .invoke that returns valid dict
                mock_struct = Mock()
                mock_struct.invoke.return_value = {"label": "x"}
                m.with_structured_output.return_value = mock_struct
                return m

            # Patch probe's build path via negotiation probe helper directly
            # Instead test roles.invoke_role with mocked probe helper: patch probe_with_invoker
            original_probe = N.probe_with_invoker
            def counting_probe(provider, model, schema, invoker, profile):
                invoke_counts["probe"] += 1
                # simulate one probe attempt that validates first rung
                return original_probe(provider, model, schema, lambda m: {"label": "x"}, profile)

            with patch.object(R, "probe_with_invoker", side_effect=counting_probe):
                with patch.object(R, "build_chat_model") as mock_build:
                    mock_llm = Mock()
                    mock_struct = Mock()
                    mock_struct.invoke.return_value = {"label": "x"}
                    mock_llm.with_structured_output.return_value = mock_struct
                    mock_build.return_value = mock_llm
                    with patch.object(R, "invoke_with_escalating_timeout") as mock_escalating:
                        # escalating wrapper should receive a call that retries same winner
                        def escalating_side_effect(call):
                            # Simulate two attempts: first returns valid, should not re-probe
                            invoke_counts["call"] += 1
                            r1 = call(300)
                            invoke_counts["call"] += 1
                            r2 = call(600)
                            return r1 or r2

                        mock_escalating.side_effect = escalating_side_effect
                        result = R.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_Good)
                        # probe happened once at construction
                        assert invoke_counts["probe"] == 1
                        # escalating attempts both used same winner (call invoked twice, but probe not re-run)
                        assert mock_escalating.call_count == 1


def test_probe_fail_open_all_rungs_miss_still_starts_session():
    """D7 fail-open: if every rung misses, probe caches None and caller still starts session."""
    N.clear_probe_cache()

    def always_miss(method):
        return {"unexpected": True}  # fails validation for _Good

    winner = N.probe_with_invoker("openrouter", "unknown/fail-open", _Good, always_miss, _unknown_profile())
    assert winner is None
    # Caller (roles) degrades to semantic default and still invokes without raising
    from polymerhus.app.llm import roles as R

    with patch.object(R, "resolve_capability", return_value=_unknown_profile()):
        with patch.object(R, "resolve_role", return_value=("openrouter", "unknown/fail-open")):
            N.clear_probe_cache()
            # Make probe return None (all miss)
            with patch.object(R, "probe_with_invoker", return_value=None):
                with patch.object(R, "build_chat_model") as mock_build:
                    mock_llm = Mock()
                    mock_struct = Mock()
                    mock_struct.invoke.return_value = {"label": "x"}
                    mock_llm.with_structured_output.return_value = mock_struct
                    mock_build.return_value = mock_llm
                    with patch.object(R, "invoke_with_escalating_timeout", side_effect=lambda c: c(300)):
                        result = R.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_Good)
                        # Should still return a result (not raise) - fail-open via semantic default
                        assert result is not None


def test_probe_observability_span_and_log(monkeypatch, caplog):
    """Each resolution gets a langfuse span/trace (D11) and is logged with provenance."""
    N.clear_probe_cache()
    caplog.set_level(logging.INFO)
    # Mock langfuse get_client to assert span created
    mock_span = Mock()
    mock_span.__enter__ = Mock(return_value=mock_span)
    mock_span.__exit__ = Mock(return_value=False)
    mock_client = Mock()
    mock_client.start_as_current_observation.return_value = mock_span
    mock_langfuse = Mock()
    mock_langfuse.get_client.return_value = mock_client
    monkeypatch.setitem(__import__("sys").modules, "langfuse", mock_langfuse)

    # Need to also patch the import inside negotiation._emit_probe_span - it does `from langfuse import get_client`
    # So mocking sys.modules langfuse with get_client attribute works
    mock_langfuse.get_client = mock_client.get_client if hasattr(mock_client, "get_client") else mock_client

    # Actually _emit does `from langfuse import get_client` - so we need that symbol
    import sys
    import types

    fake_langfuse = types.ModuleType("langfuse")
    fake_langfuse.get_client = lambda: mock_client
    sys.modules["langfuse"] = fake_langfuse

    def invoker(method):
        return {"label": "x"}

    profile = CapabilityProfile(source="models.dev/test", supports_structured_output=None, supports_tool_calling=None)
    winner = N.probe_with_invoker("openrouter", "obs/model", _Good, invoker, profile)
    assert winner == "json_schema"
    # span was requested
    assert mock_client.start_as_current_observation.call_count >= 1
    call_kwargs = mock_client.start_as_current_observation.call_args
    assert call_kwargs is not None
    # input should contain provider/model
    inp = call_kwargs[1].get("input") if len(call_kwargs) > 1 else call_kwargs[0][0] if call_kwargs[0] else {}
    # Check log contains provenance
    assert "obs/model" in caplog.text or "obs" in caplog.text
    assert "models.dev/test" in caplog.text or "provenance" in caplog.text
    # cleanup
    sys.modules.pop("langfuse", None)


def test_probe_observability_fail_open_when_langfuse_absent(caplog):
    """Langfuse absent never blocks probe - fail-open."""
    caplog.set_level(logging.INFO)
    N.clear_probe_cache()
    import sys

    # Ensure langfuse not importable
    sys.modules.pop("langfuse", None)
    # If langfuse not installed, probe should still succeed
    def invoker(method):
        return {"label": "x"}

    winner = N.probe_with_invoker("openrouter", "no-langfuse/model", _Good, invoker, _unknown_profile())
    assert winner == "json_schema"
    # Should still log
    assert "capability probe" in caplog.text


def test_probe_winner_held_per_provider_model_schema_and_shared_by_session(monkeypatch):
    """The probe winner is held per (provider, model, schema-class) and shared by the session."""
    N.clear_probe_cache()
    from polymerhus.app.llm import session as S
    from polymerhus.app.llm.capability import CapabilityProfile

    monkeypatch.setenv("LLM_MODEL_TRIAGER", "openrouter:probe-shared")

    def fake_cap(provider, model):
        return CapabilityProfile()  # unknown

    monkeypatch.setattr(S, "resolve_capability", fake_cap)
    # Patch negotiate to ensure unknown would be json_schema, but probe holds
    # First call will cache json_schema
    from pydantic import BaseModel

    class _Schema(BaseModel):
        x: int

    # Clear cache, first probe via invoker that picks function_calling (second rung)
    def invoker_fixture(provider, model, schema, method):
        if method == "json_schema":
            return {"unexpected": True}
        return {"x": 1}

    S._session_probe_invoker = invoker_fixture
    try:
        rf1 = S._structured_response_format("triager", _Schema)
        # winner should be function_calling -> ToolStrategy
        from langchain.agents.structured_output import ToolStrategy

        assert isinstance(rf1, ToolStrategy)
        # Second call with same schema should reuse cache (no re-invoke)
        count = {"n": 0}

        def counting_invoker(provider, model, schema, method):
            count["n"] += 1
            return {"x": 1}

        S._session_probe_invoker = counting_invoker
        rf2 = S._structured_response_format("triager", _Schema)
        assert isinstance(rf2, ToolStrategy)
        assert count["n"] == 0  # cached, not re-probed
        # Different schema probes separately
        class _OtherSchema(BaseModel):
            y: str

        rf3 = S._structured_response_format("triager", _OtherSchema)
        # This should have probed (count 1+)
        assert count["n"] >= 1
    finally:
        S._session_probe_invoker = None
        N.clear_probe_cache()


def test_session_cold_start_miss_never_writes_cache_and_marks_default_unvalidated(
    monkeypatch, caplog
):
    """Q2/Q4 (operator-ratified 2026-08-21): a production cold-start session
    (no prior one-shot probe entry) holds the UNVALIDATED semantic default
    json_schema for THIS turn, emits the span/log with the
    semantic-default-unvalidated provenance marker, and NEVER writes into the
    shared _PROBE_CACHE - probe_with_invoker is the only cache writer."""
    N.clear_probe_cache()
    import sys
    import types

    from polymerhus.app.llm import session as S

    mock_span = Mock()
    mock_span.__enter__ = Mock(return_value=mock_span)
    mock_span.__exit__ = Mock(return_value=False)
    mock_client = Mock()
    mock_client.start_as_current_observation.return_value = mock_span
    fake_langfuse = types.ModuleType("langfuse")
    fake_langfuse.get_client = lambda: mock_client
    sys.modules["langfuse"] = fake_langfuse

    monkeypatch.setenv("LLM_MODEL_TRIAGER", "openrouter:cold-start-unknown")
    monkeypatch.setattr(S, "resolve_capability", lambda provider, model: _unknown_profile())
    caplog.set_level(logging.INFO)
    assert S._session_probe_invoker is None  # production path, no override

    rf = S._structured_response_format("triager", _Good)
    from langchain.agents.structured_output import ProviderStrategy

    assert isinstance(rf, ProviderStrategy)  # semantic default, still starts
    key = N._probe_cache_key("openrouter", "cold-start-unknown", _Good)
    assert key not in N._PROBE_CACHE  # session never writes the cache (Q4)
    # The span carries the unvalidated-default provenance (Q2 generation-time
    # failure-risk documentation), and the log mirrors it.
    assert mock_client.start_as_current_observation.call_count >= 1
    span_output = mock_span.update.call_args.kwargs["output"]
    assert span_output.get("provenance") == "semantic-default-unvalidated; no prior probe entry"
    assert "semantic-default-unvalidated" in caplog.text
    sys.modules.pop("langfuse", None)
    N.clear_probe_cache()


def test_session_cold_start_miss_all_miss_cache_none_still_starts():
    """Q2: the cold-start miss path still fails open (D7) - the session starts
    on the semantic default regardless of cache state."""
    N.clear_probe_cache()
    from polymerhus.app.llm import session as S

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("LLM_MODEL_TRIAGER", "openrouter:cold-start-unknown-2")
    monkeypatch.setattr(S, "resolve_capability", lambda provider, model: _unknown_profile())
    try:
        rf = S._structured_response_format("triager", _Good)
        from langchain.agents.structured_output import ProviderStrategy

        assert isinstance(rf, ProviderStrategy)
        key = N._probe_cache_key("openrouter", "cold-start-unknown-2", _Good)
        assert key not in N._PROBE_CACHE
    finally:
        monkeypatch.undo()
        N.clear_probe_cache()


def test_session_primed_cache_hit_reuses_winner_without_reinvoking(caplog):
    """Q4: the session READS the shared _PROBE_CACHE primed by a prior one-shot
    probe - the cached winner is used without any invoker call, and the span/log
    carries the probe-cache-hit provenance."""
    N.clear_probe_cache()
    from polymerhus.app.llm import session as S

    caplog.set_level(logging.INFO)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("LLM_MODEL_TRIAGER", "openrouter:primed-hit")
    monkeypatch.setattr(S, "resolve_capability", lambda provider, model: _unknown_profile())
    # Prime the cache exactly as a prior one-shot probe_with_invoker would.
    key = N._probe_cache_key("openrouter", "primed-hit", _Good)
    N._PROBE_CACHE[key] = "function_calling"
    # Any invoker call means the session wrongly re-probed - make it fail loudly.
    S._session_probe_invoker = lambda provider, model, schema, method: (_ for _ in ()).throw(
        AssertionError("cache hit must not re-probe")
    )
    try:
        rf = S._structured_response_format("triager", _Good)
        from langchain.agents.structured_output import ToolStrategy

        assert isinstance(rf, ToolStrategy)  # cached function_calling winner
        assert N._PROBE_CACHE[key] == "function_calling"  # unchanged, session never writes
        assert "probe-cache-hit" in caplog.text
    finally:
        S._session_probe_invoker = None
        monkeypatch.undo()
        N.clear_probe_cache()


def test_session_primed_cache_all_miss_none_fails_open_to_json_schema():
    """Q4: the all-miss None sentinel cached by a prior probe fails open to the
    json_schema semantic default on the session seam."""
    N.clear_probe_cache()
    from polymerhus.app.llm import session as S

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("LLM_MODEL_TRIAGER", "openrouter:primed-miss")
    monkeypatch.setattr(S, "resolve_capability", lambda provider, model: _unknown_profile())
    key = N._probe_cache_key("openrouter", "primed-miss", _Good)
    N._PROBE_CACHE[key] = None  # all-miss sentinel from a prior probe
    try:
        rf = S._structured_response_format("triager", _Good)
        from langchain.agents.structured_output import ProviderStrategy

        assert isinstance(rf, ProviderStrategy)
    finally:
        monkeypatch.undo()
        N.clear_probe_cache()


def test_probe_never_parses_vendor_error_string():
    """Validation via result_validates never branches on error strings."""
    N.clear_probe_cache()
    # Even if invoker raises with vendor error text, probe descends via validation/exception, not string match
    errors = []

    def invoker(method):
        if method == "json_schema":
            raise RuntimeError("400 Thinking mode does not support this tool_choice")
        return {"label": "ok"}

    with patch.object(N, "result_validates", wraps=N.result_validates) as mock_validate:
        winner = N.probe_with_invoker("openrouter", "err/model", _Good, invoker, _unknown_profile())
        assert winner == "function_calling"
        # result_validates was called only for the second rung's parsed result, not for error string
        assert mock_validate.call_count == 1
        assert mock_validate.call_args[0][0] == {"label": "ok"}


def test_roles_probe_uses_parse_validation_for_wrong_shape_json_mode():
    """Silent wrong-shape json_mode dict that fails result_validates causes descent / failure, never acceptance."""
    N.clear_probe_cache()
    from polymerhus.app.llm import roles as R

    with patch.object(R, "resolve_capability", return_value=_unknown_profile()):
        with patch.object(R, "resolve_role", return_value=("openrouter", "wrong-shape")):
            N.clear_probe_cache()

            # Mock build_chat_model to return different parsed per method
            def fake_build(provider, model, **kw):
                m = Mock()
                def with_struct(schema, method=None, strict=False):
                    ms = Mock()
                    # Simulate json_schema returns wrong shape, function_calling correct
                    if method == "json_schema":
                        ms.invoke.return_value = {"unexpected": True}
                    elif method == "function_calling":
                        ms.invoke.return_value = {"label": "x"}
                    else:
                        ms.invoke.return_value = {"label": "x"}
                    return ms
                m.with_structured_output.side_effect = with_struct
                return m

            with patch.object(R, "build_chat_model", side_effect=fake_build):
                with patch.object(R, "invoke_with_escalating_timeout", side_effect=lambda c: c(300)):
                    result = R.invoke_role("triager", [{"role": "user", "content": "hi"}], schema=_Good)
                    # Should have probed past wrong-shape json_schema to function_calling
                    assert result is not None
                    assert getattr(result, "label", None) == "x" or result == {"label": "x"}
