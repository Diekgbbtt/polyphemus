import pytest
from agent.app.llm import providers as P

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
