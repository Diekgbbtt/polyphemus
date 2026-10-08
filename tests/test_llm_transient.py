"""Unit tier: the transient-upstream classifier and retry policy (#299).

The opencode-go lane intermittently returns a bare HTTP 400 (empty body, or a
body that only echoes the stripped wire model id) for every request during a
short window. This module classifies that bare-400 as TRANSIENT - distinct from
a deterministic CONTRACT 400 - and owns the jittered backoff, the session-id
rotation, and the structured transient counter the actor and one-shot seams
consume. Pure at the classification seam: no I/O, no live model.
"""
from __future__ import annotations

import httpx
import openai
import pytest

from polymerhus.app.llm import transient as T


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.example.test/v1/chat/completions")


def _bad_request(body) -> openai.BadRequestError:
    response = httpx.Response(400, request=_request(),
                              json=body if body is not None else None)
    return openai.BadRequestError("Error code: 400", response=response, body=body)


def _status_error(status: int, body=None) -> openai.APIStatusError:
    response = httpx.Response(status, request=_request(),
                              json=body if body is not None else None)
    return openai.APIStatusError("boom", response=response, body=body)


# --- the classification (operator ruling D-1) ---------------------------------
#
# Only the EXACT opencode-go deepseek single-model-echo 400 is transient: a 400
# whose parsed body is an object whose ONLY key is `model`, whose value equals
# the configured deepseek wire id, raised for the opencode-go lane. Everything
# else - an empty 400, a foreign-model echo, a multi-key envelope - stays
# contract/fatal and never arms the fallback.

_LANE = {"provider": "opencode-go", "model": "deepseek-v4.1-flash"}


def test_the_deepseek_single_model_echo_400_is_transient():
    """The reproduced signature (D-1): the body's ONLY key is `model`, its value
    EQUALS the configured deepseek wire id, and the raise is the opencode-go lane."""
    assert T.classify_error(
        _bad_request({"model": "deepseek-v4.1-flash"}),
        **_LANE) == "transient"
    assert T.classify_error(
        _bad_request({"model": "deepseek-v4-flash"}),
        provider="opencode-go", model="deepseek-v4-flash") == "transient"
    # the operator's provider-prefixed config strips to the same wire id
    assert T.classify_error(
        _bad_request({"model": "deepseek-v4.1-flash"}),
        provider="opencode-go", model="opencode-go/deepseek-v4.1-flash") == "transient"


def test_an_empty_400_is_not_transient():
    """An empty 400 is indistinguishable from a bare contract error from any
    provider, so D-1 refuses to branch on it."""
    assert T.classify_error(_bad_request(None), **_LANE) == "fatal"
    assert T.classify_error(_bad_request(""), **_LANE) == "fatal"
    assert T.classify_error(_bad_request({}), **_LANE) == "fatal"


def test_a_foreign_model_echo_400_is_not_transient():
    """A single-key `model` body whose value is NOT the configured deepseek wire
    id is not the lane signature."""
    assert T.classify_error(_bad_request({"model": "something-else"}),
                            **_LANE) == "fatal"
    assert T.classify_error(_bad_request({"model": "glm-5.2"}), **_LANE) == "fatal"


def test_a_model_echo_400_from_another_provider_is_not_transient():
    """The model id alone never branches: the same body from another provider (or
    with no provider identity) is fatal."""
    assert T.classify_error(
        _bad_request({"model": "deepseek-v4.1-flash"}),
        provider="openrouter", model="deepseek-v4.1-flash") == "fatal"
    assert T.classify_error(
        _bad_request({"model": "deepseek-v4.1-flash"}),
        model="deepseek-v4.1-flash") == "fatal"


def test_an_error_and_model_400_is_not_transient():
    """Any extra key (`error`/`message`/...) makes the body a contract/unrecognised
    envelope, never the single-key lane signature."""
    assert T.classify_error(
        _bad_request({"error": {"message": "x"}, "model": "deepseek-v4.1-flash"}),
        **_LANE) == "fatal"


def test_a_recognisable_contract_400_is_contract():
    for message in (
        "MissingSessionID",
        "reasoning_content must be passed back",
        "This response_format type is unavailable now",
        "top_p is not supported",
        "tools[0].function missing field name",
    ):
        assert T.classify_error(_bad_request({"error": {"message": message}})) == "contract"
        assert T.classify_error(_bad_request(message)) == "contract"


def test_transport_timeout_5xx_and_429_are_transient():
    assert T.classify_error(TimeoutError("hung")) == "transient"
    assert T.classify_error(httpx.ConnectTimeout("nope")) == "transient"
    assert T.classify_error(_status_error(503)) == "transient"
    assert T.classify_error(_status_error(502)) == "transient"
    assert T.classify_error(_status_error(429, {"error": "rate limited"})) == "transient"


def test_unknown_and_non_400_client_errors_are_fatal():
    assert T.classify_error(ValueError("a genuine application error")) == "fatal"
    assert T.classify_error(_status_error(403, {"error": "forbidden"})) == "fatal"
    assert T.classify_error(_bad_request({"error": "an unrecognised 400 body"})) == "fatal"


# --- the body shape (observability) -------------------------------------------

def test_body_shape_names_the_observed_surfaces():
    assert T.body_shape(_bad_request(None)) == "empty"
    assert T.body_shape(_bad_request("")) == "empty"
    assert T.body_shape(_bad_request({})) == "empty"
    assert T.body_shape(_bad_request({"model": "deepseek-v4.1-flash"})) == "model"
    assert T.body_shape(_bad_request({"error": {"message": "MissingSessionID"}})) == "contract"
    assert T.body_shape(_bad_request({"error": "unrecognised"})) == "other"
    assert T.body_shape(_status_error(503)) == "n/a"


# --- the jittered backoff -----------------------------------------------------

def test_backoff_is_exponential_from_the_base_and_capped(monkeypatch):
    monkeypatch.delenv("LLM_TRANSIENT_BACKOFF_S", raising=False)
    monkeypatch.delenv("LLM_TRANSIENT_BACKOFF_MAX_S", raising=False)
    monkeypatch.delenv("LLM_TRANSIENT_JITTER", raising=False)
    half = lambda: 0.5  # noqa: E731 - jitter centre: no jitter offset
    assert T.jittered_backoff(1, rng=half) == 2.0
    assert T.jittered_backoff(2, rng=half) == 4.0
    assert T.jittered_backoff(3, rng=half) == 8.0
    assert T.jittered_backoff(10, rng=half) == 30.0  # capped at the max


def test_backoff_jitter_stays_within_the_fraction(monkeypatch):
    monkeypatch.setenv("LLM_TRANSIENT_JITTER", "0.25")
    monkeypatch.setenv("LLM_TRANSIENT_BACKOFF_S", "8")
    low = T.jittered_backoff(1, rng=lambda: 0.0)
    high = T.jittered_backoff(1, rng=lambda: 1.0)
    assert low == pytest.approx(6.0)
    assert high == pytest.approx(10.0)


def test_backoff_env_overrides(monkeypatch):
    monkeypatch.setenv("LLM_TRANSIENT_BACKOFF_S", "1")
    monkeypatch.setenv("LLM_TRANSIENT_BACKOFF_MAX_S", "5")
    monkeypatch.setenv("LLM_TRANSIENT_JITTER", "0")
    assert T.jittered_backoff(1, rng=lambda: 0.5) == 1.0
    assert T.jittered_backoff(9, rng=lambda: 0.5) == 5.0


def test_a_bad_backoff_env_fails_fast(monkeypatch):
    from polymerhus.app.llm.providers import LLMConfigError

    for name, bad in (("LLM_TRANSIENT_BACKOFF_S", "soon"),
                      ("LLM_TRANSIENT_BACKOFF_MAX_S", "0"),
                      ("LLM_TRANSIENT_JITTER", "2")):
        monkeypatch.setenv(name, bad)
        with pytest.raises(LLMConfigError):
            T.jittered_backoff(1)
        monkeypatch.delenv(name)


# --- the session-id rotation --------------------------------------------------

def test_rotation_names_the_attempt_and_leaves_attempt_zero_untouched():
    assert T.rotate_conversation("run:hunt", 0) == "run:hunt"
    assert T.rotate_conversation("run:hunt", 1) == "run:hunt#r1"
    assert T.rotate_conversation("run:hunt", 2) == "run:hunt#r2"


# --- the structured counter ---------------------------------------------------

def test_record_transient_increments_the_counter_and_logs(monkeypatch, caplog):
    T.reset_transient_counts()
    T.record_transient(role="hunting_orchestrator",
                       model="opencode-go:deepseek-v4.1-flash",
                       conversation_id="run:hunt#r1", attempt=1, status=400,
                       body_shape="model")
    T.record_transient(role="hunting_orchestrator",
                       model="opencode-go:deepseek-v4.1-flash",
                       conversation_id="run:hunt#r2", attempt=2, status=400,
                       body_shape="model")
    counts = T.transient_counts()
    assert counts[("hunting_orchestrator", "opencode-go:deepseek-v4.1-flash", "model")] == 2
    with caplog.at_level("WARNING"):
        T.record_transient(role="triager", model="opencode-go:deepseek-v4-flash",
                           conversation_id=process_id(), attempt=1, status=400,
                           body_shape="model")
    assert any("llm-transient-upstream" in r.getMessage() for r in caplog.records)


def process_id() -> str:
    from polymerhus.app.llm.conversation import current_conversation_id

    return current_conversation_id()
