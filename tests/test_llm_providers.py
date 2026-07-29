import socket
import threading
import time

import pytest
from polymerhus.app.llm import providers as P

def test_known_providers_have_base_urls():
    assert P.PROVIDERS["openai"].startswith("https://")
    assert "openrouter" in P.PROVIDERS
    assert "swissai" in P.PROVIDERS

def test_resolve_role_parses_provider_and_model(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_TRIAGER", "openrouter:anthropic/claude-3.5-sonnet")
    assert P.resolve_role("triager") == ("openrouter", "anthropic/claude-3.5-sonnet")

def test_validate_raises_when_key_missing(monkeypatch):
    monkeypatch.setenv("LLM_MODEL_TRIAGER", "openrouter:some/model")
    monkeypatch.setenv("LLM_MODEL_CONFIGURATOR", "openai:gpt-4o")
    monkeypatch.setenv("LLM_MODEL_JOB_ORCHESTRATOR", "openai:gpt-4o")
    monkeypatch.setenv("LLM_MODEL_CRAWLER", "openai:gpt-4o")
    monkeypatch.delenv("API_KEY_OPENROUTER", raising=False)
    monkeypatch.setenv("API_KEY_OPENAI", "sk-x")
    with pytest.raises(P.LLMConfigError) as e:
        P.validate_llm_config()
    assert "OPENROUTER" in str(e.value)

def test_validate_raises_on_unknown_provider(monkeypatch):
    # Derive from P.ROLES so adding a role (e.g. analyser) never breaks this test.
    for r in P.ROLES:
        monkeypatch.setenv(f"LLM_MODEL_{r.upper()}", "openai:gpt-4o")
    monkeypatch.setenv("LLM_MODEL_TRIAGER", "bogus:model")
    monkeypatch.setenv("API_KEY_OPENAI", "sk-x")
    with pytest.raises(P.LLMConfigError):
        P.validate_llm_config()

def test_validate_passes_when_all_present(monkeypatch):
    # Derive from P.ROLES so every configured role (incl. analyser) is covered.
    for r in P.ROLES:
        monkeypatch.setenv(f"LLM_MODEL_{r.upper()}", "swissai:meta-llama/Llama-3.3-70B-Instruct")
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    P.validate_llm_config()  # no raise

def test_analyser_role_is_registered_and_required(monkeypatch):
    """FR-ANALYSER: the analyser is a first-class role, so validate_llm_config
    requires LLM_MODEL_ANALYSER at boot (AST-ANALYSER-02)."""
    assert "analyser" in P.ROLES
    for r in P.ROLES:
        monkeypatch.setenv(f"LLM_MODEL_{r.upper()}", "swissai:x")
    monkeypatch.delenv("LLM_MODEL_ANALYSER", raising=False)  # analyser unset
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    with pytest.raises(P.LLMConfigError) as e:
        P.validate_llm_config()
    assert "ANALYSER" in str(e.value)

def test_build_chat_model_sets_base_url_and_key(monkeypatch):
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    m = P.build_chat_model("swissai", "meta-llama/Llama-3.3-70B-Instruct")
    assert str(m.openai_api_base) == P.PROVIDERS["swissai"]


def test_resolve_role_parses_the_qwen_swissai_swap(monkeypatch):
    """The operator's `.env` now points every role at
    `swissai:Qwen/Qwen3.5-397B-A17B-ETar` - a model id containing a slash, which
    is also the provider/model separator `resolve_role` splits on. Pin that the
    split is on the FIRST colon only, so a slash inside the model id never
    truncates it."""
    monkeypatch.setenv("LLM_MODEL_ANALYSER", "swissai:Qwen/Qwen3.5-397B-A17B-ETar")
    assert P.resolve_role("analyser") == ("swissai", "Qwen/Qwen3.5-397B-A17B-ETar")


def test_build_chat_model_accepts_the_qwen_swissai_model_id(monkeypatch):
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    m = P.build_chat_model("swissai", "Qwen/Qwen3.5-397B-A17B-ETar")
    assert m.model_name == "Qwen/Qwen3.5-397B-A17B-ETar"
    assert str(m.openai_api_base) == P.PROVIDERS["swissai"]


# --- #32: the effective client settings -------------------------------------
# These assert on the UNDERLYING openai client, never on the ChatOpenAI wrapper.
# The defect was invisible at the wrapper level: `ChatOpenAI.max_retries` reads
# None while the client it built was using 2, so a wrapper-level assertion would
# have passed with the defect fully in place.

def test_underlying_client_has_an_effective_request_timeout(monkeypatch):
    """#32/FM-1: langchain passes `timeout` into the client params
    unconditionally, so an unset value NULLS OUT the SDK's own default and a
    hung call blocks forever. Both clients must carry a finite budget."""
    monkeypatch.delenv("LLM_REQUEST_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    m = P.build_chat_model("swissai", "x")
    for client in (m.root_client, m.root_async_client):
        t = client.timeout
        assert t.read == P.DEFAULT_REQUEST_TIMEOUT_SECONDS
        assert t.connect == P.CONNECT_TIMEOUT_SECONDS  # FM-2: a dead SYN fails fast
        assert t.read > 150, "must clear the slowest legitimate call (rich-KB bootstrap)"


def test_underlying_client_bounds_its_own_retries(monkeypatch):
    """#32/FM-4: the SDK's silent default of 2 multiplies with analysis'
    `bounded_retry(attempts=3)` into 9 round-trips per logical attempt. The
    policy must be stated, not inherited."""
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    m = P.build_chat_model("swissai", "x")
    assert m.root_client.max_retries == P.MAX_RETRIES
    assert P.MAX_RETRIES == 1
    # FM-5: NOT zero. `bounded_retry` lives only in analysis, so this is the sole
    # retry the recon roles have, and the only layer that backs off / honours
    # Retry-After. Zeroing it would trade a latency bug for a recon resilience
    # regression.
    assert P.MAX_RETRIES > 0


def test_request_timeout_is_overridable_and_fails_fast_on_a_bad_value(monkeypatch):
    """FM-3 is the dangerous outlier: too tight a timeout makes every attempt
    fail on a HEALTHY provider, which fail-closes as if the model had failed. The
    override exists so that is correctable without a rebuild - and an unusable
    override must raise rather than silently pretend the default is in force."""
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "45")
    assert P.request_timeout().read == 45.0
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "")  # unset-equivalent
    assert P.request_timeout().read == P.DEFAULT_REQUEST_TIMEOUT_SECONDS
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "5")  # below the connect budget
    assert P.request_timeout().connect == 5.0
    for bad in ("soon", "0", "-1"):
        monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", bad)
        with pytest.raises(P.LLMConfigError):
            P.request_timeout()


def test_a_hung_provider_fails_within_the_timeout(monkeypatch):
    """#32/FM-1 end to end: a provider that ACCEPTS the connection and never
    answers. Before the fix this blocks indefinitely - the fail-closed contract
    covers an error but not a hang. It must now surface as an error the existing
    retry-then-fail-closed path can act on."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    port = listener.getsockname()[1]
    accepted: list[socket.socket] = []
    stop = threading.Event()

    def accept_and_stall():
        listener.settimeout(0.5)
        while not stop.is_set():
            try:
                accepted.append(listener.accept()[0])  # accept, never respond
            except OSError:
                continue

    t = threading.Thread(target=accept_and_stall, daemon=True)
    t.start()
    try:
        monkeypatch.setitem(P.PROVIDERS, "openai", f"http://127.0.0.1:{port}/v1")
        monkeypatch.setenv("LLM_REQUEST_TIMEOUT_SECONDS", "1")
        monkeypatch.setenv("API_KEY_OPENAI", "sk-x")
        m = P.build_chat_model("openai", "x")

        # The call runs on a watchdog thread, never inline: without the fix it
        # blocks FOREVER, and an inline call would hang the whole suite instead
        # of reporting a regression. A daemon thread lets this fail cleanly.
        outcome: list[object] = []
        started = time.monotonic()

        def call():
            try:
                m.invoke("hello")
                outcome.append(None)  # returned without error - no timeout fired
            except Exception as exc:
                outcome.append(exc)

        caller = threading.Thread(target=call, daemon=True)
        caller.start()
        caller.join(timeout=30)
        elapsed = time.monotonic() - started
        assert outcome, f"hung call still blocked after {elapsed:.1f}s; no timeout fired"
        assert isinstance(outcome[0], Exception), "a hang must surface as an error"
    finally:
        stop.set()
        t.join(timeout=5)
        for s in accepted:
            s.close()
        listener.close()

    # 1s read budget x (1 + MAX_RETRIES) attempts, plus the SDK's backoff. The
    # bound is loose on purpose - the assertion under test is "terminates at all".
    assert elapsed < 30, f"hung call took {elapsed:.1f}s; it must fail on the timeout"
