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
    for r in ("TRIAGER", "CONFIGURATOR", "JOB_ORCHESTRATOR", "CRAWLER"):
        monkeypatch.setenv(f"LLM_MODEL_{r}", "openai:gpt-4o")
    monkeypatch.setenv("LLM_MODEL_TRIAGER", "bogus:model")
    monkeypatch.setenv("API_KEY_OPENAI", "sk-x")
    with pytest.raises(P.LLMConfigError):
        P.validate_llm_config()

def test_validate_passes_when_all_present(monkeypatch):
    for r in ("TRIAGER", "CONFIGURATOR", "JOB_ORCHESTRATOR", "CRAWLER"):
        monkeypatch.setenv(f"LLM_MODEL_{r}", "swissai:meta-llama/Llama-3.3-70B-Instruct")
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    P.validate_llm_config()  # no raise

def test_build_chat_model_sets_base_url_and_key(monkeypatch):
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    m = P.build_chat_model("swissai", "meta-llama/Llama-3.3-70B-Instruct")
    assert str(m.openai_api_base) == P.PROVIDERS["swissai"]
