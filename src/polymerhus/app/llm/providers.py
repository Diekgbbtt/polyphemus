import os
import httpx
from langchain_openai import ChatOpenAI

class LLMConfigError(RuntimeError):
    """Raised at bootstrap when an agent role references a provider/model
    whose base URL or API key is absent from the system context."""

# Request timeout (#32). The openai SDK ships a sane default -
# `Timeout(connect=5, read=600, ...)` - but langchain_openai puts
# `"timeout": self.request_timeout` into the client params UNCONDITIONALLY, so
# leaving it unset does not inherit that default, it NULLS IT OUT: a provider
# that accepts the connection and never answers then blocks forever.
# That is the severe half of #32 - the fail-closed contract covers an error but
# not a hang, so a hung call holds its worker thread (and, via
# `POST /projects/{id}/bootstrap`, an API request) with no recovery path.
# The read budget is ~2x the slowest observed LEGITIMATE call (a Bootstrapper
# reasoning call over a rich operator KB runs ~150s): too tight a value would be
# the worse defect, because every attempt would time out, `bounded_retry` would
# exhaust, and the caller would fail closed on a HEALTHY provider - a silent
# capability regression indistinguishable from a model failure.
# The connect budget stays short so a blackholed route fails fast instead of
# spending the whole generation budget on a dead SYN.
DEFAULT_REQUEST_TIMEOUT_SECONDS = 300.0
CONNECT_TIMEOUT_SECONDS = 10.0

# Explicit, because the SDK's silent default of 2 MULTIPLIES with caller-side
# retry: analysis' `bounded_retry(attempts=3)` on top of a client that retries
# twice is up to 9 provider round-trips for one logical attempt, with neither
# layer revealing the other (#32).
# It is set to 1 rather than 0 because the two layers are complementary in KIND,
# not redundant: this one covers transport / 429 / 5xx and is the only one that
# backs off and honours Retry-After - and the only retry the recon roles have at
# all, since `bounded_retry` lives in analysis alone. Zeroing it would trade a
# latency bug for a resilience regression across the recon pipeline. 1 bounds
# the product at 6 round-trips while keeping that layer.
MAX_RETRIES = 1


def request_timeout() -> httpx.Timeout:
    """The effective per-request timeout, overridable via
    `LLM_REQUEST_TIMEOUT_SECONDS` so a value that proves too tight in the field
    is correctable without a rebuild. An unusable override is a config lie, so
    it fails fast rather than silently degrading to the default."""
    raw = os.environ.get("LLM_REQUEST_TIMEOUT_SECONDS")
    if raw is None or raw.strip() == "":
        read = DEFAULT_REQUEST_TIMEOUT_SECONDS
    else:
        try:
            read = float(raw)
        except ValueError:
            raise LLMConfigError(
                f"LLM_REQUEST_TIMEOUT_SECONDS must be a number of seconds (got {raw!r})"
            ) from None
        if read <= 0:
            raise LLMConfigError(
                f"LLM_REQUEST_TIMEOUT_SECONDS must be positive (got {raw!r})"
            )
    return httpx.Timeout(read, connect=min(CONNECT_TIMEOUT_SECONDS, read))

PROVIDERS: dict[str, str] = {
    "openai":     "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "swissai":    "https://api.swissai.svc.cscs.ch/v1",
}

ROLES: tuple[str, ...] = ("configurator", "triager", "job_orchestrator", "crawler", "analyser")

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
                      timeout=request_timeout(), max_retries=MAX_RETRIES,
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
