import os
from langchain_openai import ChatOpenAI

class LLMConfigError(RuntimeError):
    """Raised at bootstrap when an agent role references a provider/model
    whose base URL or API key is absent from the system context."""

PROVIDERS: dict[str, str] = {
    "openai":     "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "swissai":    "https://api.swissai.svc.cscs.ch/v1",
}

ROLES: tuple[str, ...] = ("configurator", "triager", "job_orchestrator", "crawler", "analyser")

# Per-request wall-clock bound on a provider call, and the SDK's own retry count.
# Both were unset, which is the mechanism behind the measured stall: an unbounded
# request sat under `_invoke_with_retry(attempts=3)`, so a provider that never
# answered blocked a caller indefinitely, three times over. One analyser pass on
# run 64f2ccb8 took 1157 s against a 59 s median.
# `max_retries=0` hands retry policy to the ONE layer that already owns it
# (`pod._invoke_with_retry`); leaving the SDK default of 2 multiplies the two
# ladders into up to nine attempts with no single place to reason about the bound.
LLM_REQUEST_TIMEOUT_S = float(os.environ.get("LLM_REQUEST_TIMEOUT_S", "120"))
LLM_SDK_MAX_RETRIES = int(os.environ.get("LLM_SDK_MAX_RETRIES", "0"))

def _key_env(provider: str) -> str:
    return f"API_KEY_{provider.upper()}"

def resolve_role(role: str) -> tuple[str, str]:
    raw = os.environ.get(f"LLM_MODEL_{role.upper()}")
    if not raw or ":" not in raw:
        raise LLMConfigError(
            f"LLM_MODEL_{role.upper()} must be set to '<provider>:<model>' (got {raw!r})"
        )
    provider, model = raw.split(":", 1)
    return provider.strip(), model.strip()

def build_chat_model(provider: str, model: str, *, temperature: float = 0) -> ChatOpenAI:
    if provider not in PROVIDERS:
        raise LLMConfigError(f"unknown provider {provider!r}; known: {sorted(PROVIDERS)}")
    api_key = os.environ.get(_key_env(provider))
    if not api_key:
        raise LLMConfigError(f"missing {_key_env(provider)} for provider {provider!r}")
    # Attach Langfuse tracing at construction so every role LLM's reasoning
    # (inputs/outputs) is captured even when the model is invoked inside a
    # worker thread (async_bridge) where LangGraph's callback contextvar does
    # not propagate. Empty list (Langfuse unconfigured) is inert. Fail-open.
    from polymerhus.app.observability import get_langfuse_callbacks

    return ChatOpenAI(model=model, api_key=api_key,
                      base_url=PROVIDERS[provider], temperature=temperature,
                      timeout=LLM_REQUEST_TIMEOUT_S, max_retries=LLM_SDK_MAX_RETRIES,
                      callbacks=get_langfuse_callbacks())

def validate_llm_config() -> None:
    """Fail fast: every configured role must name a known provider with a present key."""
    problems: list[str] = []
    for role in ROLES:
        try:
            provider, _model = resolve_role(role)
        except LLMConfigError as e:
            problems.append(str(e)); continue
        if provider not in PROVIDERS:
            problems.append(f"role {role}: unknown provider {provider!r}")
        elif not os.environ.get(_key_env(provider)):
            problems.append(f"role {role}: missing {_key_env(provider)}")
    if problems:
        raise LLMConfigError("LLM configuration invalid:\n  - " + "\n  - ".join(problems))
