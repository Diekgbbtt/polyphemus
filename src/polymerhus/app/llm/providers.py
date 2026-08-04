import logging
import os
import httpx
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

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

# --- #73 (D6): one coherent, ESCALATING per-call budget across every role ------
#
# Multi-minute latency is EXPECTED for reasoning agents, and the failure mode we
# must tolerate is "the reasoning genuinely needs longer", not only "the provider
# died". So the retry does not repeat under a fixed budget - each attempt grants
# the call MORE wall-clock than the last. A slow-but-healthy generation that just
# missed one budget succeeds on the next; a truly dead call still terminates,
# because the schedule is finite.
#
# This is the SINGLE retry layer. The client's own `max_retries` and analysis'
# `bounded_retry` / `_invoke_with_retry` collapse into this one, so the worst case
# is the SUM of the schedule (an explicit, logged number) rather than the invisible
# product of three independent layers (#32 named that product; Q2 recommended
# collapsing it). Each entry is the TOTAL budget for one attempt, in seconds.
DEFAULT_ATTEMPT_TIMEOUTS_S = (300.0, 600.0, 900.0, 2700.0)


def attempt_timeouts() -> tuple[float, ...]:
    """The escalating per-attempt budget schedule, overridable via
    `LLM_ATTEMPT_TIMEOUTS_S` (comma-separated seconds) so a schedule that proves
    wrong in the field is correctable without a rebuild. An unusable override is a
    config lie, so it fails fast rather than silently degrading to the default."""
    raw = os.environ.get("LLM_ATTEMPT_TIMEOUTS_S")
    if raw is None or raw.strip() == "":
        return DEFAULT_ATTEMPT_TIMEOUTS_S
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if not parts:
        raise LLMConfigError(
            f"LLM_ATTEMPT_TIMEOUTS_S must be comma-separated seconds (got {raw!r})"
        )
    out: list[float] = []
    for p in parts:
        try:
            v = float(p)
        except ValueError:
            raise LLMConfigError(
                f"LLM_ATTEMPT_TIMEOUTS_S entries must be numbers of seconds (got {p!r})"
            ) from None
        if v <= 0:
            raise LLMConfigError(
                f"LLM_ATTEMPT_TIMEOUTS_S entries must be positive (got {p!r})"
            )
        out.append(v)
    return tuple(out)


def invoke_with_escalating_timeout(call):
    """Drive one logical LLM call across the escalating budget schedule.

    `call(read_timeout_s: float)` performs a SINGLE attempt bounded by the given
    budget (the caller builds its model/structured wrapper with that budget and
    invokes it). Semantics mirror the retries this replaces (`bounded_retry` /
    `_invoke_with_retry`, #73), which BOTH converted failure to a None return:

    - returns the first NON-None result;
    - a None result (a transient unmet generation - the fail-closed signal) OR a
      raised attempt (transport / timeout / transient parse) is retried under the
      NEXT, larger budget;
    - on exhaustion returns None - the caller's established fail-closed signal - so
      a dead/slow provider degrades that step, never hangs and never crashes the
      caller. The last error is logged so exhaustion is never silent.

    The whole point is that budget GROWS per attempt, so a legitimately slow
    reasoning call is not guillotined at a fixed ceiling."""
    schedule = attempt_timeouts()
    last_exc: Exception | None = None
    for i, budget in enumerate(schedule, 1):
        try:
            result = call(budget)
        except Exception as exc:  # transport / timeout / transient parse - escalate
            last_exc = exc
            logger.warning("llm attempt %d/%d (budget %.0fs) raised: %s",
                           i, len(schedule), budget, exc)
            continue
        if result is not None:
            return result
        logger.warning("llm attempt %d/%d (budget %.0fs) returned no result; escalating",
                       i, len(schedule), budget)
    if last_exc is not None:
        logger.warning("llm exhausted the escalating schedule; last error: %s (fail-closed to None)",
                       last_exc)
    return None


PROVIDERS: dict[str, str] = {
    "openai":     "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "swissai":    "https://api.swissai.svc.cscs.ch/v1",
    "opencode":   "https://opencode.ai/zen/v1"
}

# Providers that are the opencode zen gateway: they validate model ids against
# the zen catalog (bare ids), not the provider-prefixed app-style ids.
_ZEN_FAMILY = frozenset({"opencode", "zen"})

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

def build_chat_model(provider: str, model: str, *, temperature: float = 0,
                     read_timeout: float | None = None,
                     max_retries: int | None = None) -> ChatOpenAI:
    if provider not in PROVIDERS:
        raise LLMConfigError(f"unknown provider {provider!r}; known: {sorted(PROVIDERS)}")
    if provider in _ZEN_FAMILY:
        # The zen gateway speaks its own catalog ids (bare, no provider prefix -
        # e.g. `deepseek-v4-flash-free`), while the operator configures the
        # opencode-app style ids (`deepseek/deepseek-v4-flash-free`). The gateway
        # rejects the prefixed form, so strip the prefix here. The zen catalog
        # contains no `/`, so the last segment is always the id.
        model = model.rsplit("/", 1)[-1]
    api_key = os.environ.get(_key_env(provider))
    if not api_key:
        raise LLMConfigError(f"missing {_key_env(provider)} for provider {provider!r}")
    # `read_timeout` lets the escalating-budget wrapper (#73) build a per-ATTEMPT
    # client whose read budget grows across retries. Unset keeps the standing
    # `request_timeout()` (the #32 default), so every non-escalating caller is
    # unchanged. The connect budget stays short so a dead SYN still fails fast.
    timeout = (request_timeout() if read_timeout is None
               else httpx.Timeout(read_timeout, connect=min(CONNECT_TIMEOUT_SECONDS, read_timeout)))
    # `max_retries` defaults to MAX_RETRIES (the agent per-turn retry). The
    # single-shot escalating wrapper (#73) passes 0, because it OWNS the retry -
    # a client retry underneath it would silently re-multiply the budget (#32).
    retries = MAX_RETRIES if max_retries is None else max_retries
    # Attach Langfuse tracing at construction so every role LLM's reasoning
    # (inputs/outputs) is captured even when the model is invoked inside a
    # worker thread (async_bridge) where LangGraph's callback contextvar does
    # not propagate. Empty list (Langfuse unconfigured) is inert. Fail-open.
    from polymerhus.app.observability import get_langfuse_callbacks

    return ChatOpenAI(model=model, api_key=api_key,
                      base_url=PROVIDERS[provider], temperature=temperature,
                      timeout=timeout, max_retries=retries,
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
