import logging
import os
from dataclasses import dataclass
from typing import Literal, Sequence

import httpx
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration
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
    "opencode":   "https://opencode.ai/zen/v1",
    "opencode-go": "https://opencode.ai/zen/go/v1",
}

# --- Provider id-kind policy (D5, #100): how ids reach the upstream ----------
#
# Each provider's upstream validates model ids in ITS OWN namespace, which is
# NOT the operator's `<provider>:<model>` config string. Classifying by *how the
# upstream validates* - not by membership in a provider set - is what makes the
# seam generic over aggregators (opencode zen today, openrouter next):
#   zen aggregators (`opencode`, `zen`): validate BARE catalog ids. The operator
#     configures the backend-prefixed app-style id (`deepseek/deepseek-v4-flash-free`);
#     the prefix is stripped to the bare id (`deepseek-v4-flash-free`) before the
#     upstream (and in the registered gateway name). opencode zen reverse-proxies
#     to the real backend but admits only its own bare catalog ids.
#   verbatim providers (openai, swissai, openrouter, and anything unlisted):
#     the id is forwarded UNCHANGED - openrouter's catalog ids ARE the slashed
#     backend form (`deepseek/deepseek-v3.1-terminus`) and its upstream accepts
#     them as-is; native providers (openai/swissai) do too.
# Adding a provider with a different id namespace is a one-line table entry; a
# wrong classification surfaces at the sync (C8) and the live routing tiers
# (C13/E4) rather than silently mangling ids.

ID_KIND_ZEN = "zen"
ID_KIND_VERBATIM = "verbatim"

_ID_KIND_BY_PROVIDER: dict[str, str] = {
    "opencode": ID_KIND_ZEN,
    "opencode-go": ID_KIND_ZEN,
    "zen": ID_KIND_ZEN,
}

def id_kind(provider: str) -> str:
    """The id-kind policy for a provider: `ID_KIND_ZEN` (bare-catalog
    aggregator) or `ID_KIND_VERBATIM` (ids forwarded unchanged). Unlisted
    providers default to verbatim - the safe, transparent default."""
    return _ID_KIND_BY_PROVIDER.get(provider, ID_KIND_VERBATIM)

# Back-compat alias: the zen providers are exactly the ID_KIND_ZEN entries.
_ZEN_FAMILY = frozenset(
    p for p, k in _ID_KIND_BY_PROVIDER.items() if k == ID_KIND_ZEN)

# --- #107 (D4 item 1): the LLM_GATEWAY_URL base_url resolution seam ------------
#
# Two LLM-facing paths live, selected by a single env var (ADR D3 + D5):
#   UNSET -> direct per-provider mode (today's behaviour, UNCHANGED): base_url is
#            `PROVIDERS[provider]` and the zen-family id strip runs client-side.
#   SET   -> gateway mode: base_url is the gateway's (internal port 4000), the
#            zen-family id strip does NOT run client-side (the gateway's mapping
#            layer owns id translation, D5), and the client sends today's
#            `provider:model` string verbatim. The gateway is a hop with
#            `num_retries=0`, never a retry layer (D3), so the client's retry axis
#            and its Langfuse callbacks at construction are untouched in both modes.
def gateway_base_url() -> str | None:
    """The LLM gateway base URL when `LLM_GATEWAY_URL` is set, else None.

    An unset or blank value selects direct per-provider mode - the same
    unset-equivalent convention `request_timeout()` and `attempt_timeouts()` use
    for their overrides. A set value is returned VERBATIM (no trailing-slash
    normalisation), so an operator misconfiguration surfaces at the gateway
    instead of being silently masked here."""
    raw = os.environ.get("LLM_GATEWAY_URL")
    if raw is None or raw.strip() == "":
        return None
    return raw

# --- The role record (#93/#94) ------------------------------------------------
#
# A role is three INDEPENDENT properties (design: llm-role-architecture-agent-prompt.md §2):
#   role_id    - the stable identity of the cognitive job (the observability label).
#   model_key  - the env var NAME selecting the model; MANY role_ids may share one
#                (many-to-one), so splitting a shared model per agent later is a
#                one-line edit to this field, never a caller change.
#   agent_mode - `one_shot` (a stateless structured single call, the `invoke_role`
#                path) vs `session` (a resumable agent whose durable state persists
#                across invocations). agent_mode is a property of the ROLE's
#                lifecycle, not of the model, and NOT the same axis as the LLM
#                invocation mechanism: a `session` agent that externalises its state
#                (the analysis supervisor's L1 graph, the hunting agent's
#                working-set-in-prompt) still makes STRUCTURED one-shot `invoke_role`
#                turns; only a genuine tool-loop / conversation-memory consumer runs
#                on the checkpointer-backed session seam (`app/llm/session.py`,
#                `create_agent`). See `llm-role-architecture-agent-prompt.md` §0.
AgentMode = Literal["one_shot", "session"]

# The provider-agnostic thinking/reasoning-effort BASELINE per role (the enum mirrors
# pydantic-ai's `ModelSettings.thinking`, evaluated as the reference design). `off` is no
# reasoning. This is the DECLARED baseline; the dynamic capability-adaptive workstream
# (#99) is what will ADJUST it to what a given provider/model actually supports and
# fail-safe when it does not - here we only translate a non-`off` level to the OpenAI
# `reasoning_effort` param, which the configured (reasoning-capable) models accept.
ThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh"]


@dataclass(frozen=True)
class Role:
    """One LLM role record: cognitive-job identity + model selector + turn mode +
    thinking baseline."""

    role_id: str
    model_key: str
    agent_mode: AgentMode = "one_shot"
    thinking: ThinkingLevel = "off"


# Roles validated at APP BOOT (`validate_llm_config`, from `app/main.py`). The
# former single `analyser` key is split per cognitive job (#93): each analysis
# agent is its own role_id but they SHARE `LLM_MODEL_ANALYSER` for now (many-to-one),
# so no new env var is required and per-agent tuning is a one-line `model_key` edit.
# The hunting module is deliberately ABSENT - it is validated at the HUNTING module
# bootstrap, never at app boot (operator ruling 2026-08-06).
# The `thinking` baseline is set on the agents that reason hard enough to benefit
# (operator direction): the analysis proposers, the recon triager, and the
# recon-orchestrator (which shares the `job_orchestrator` role, `orchestrator_agent.py`).
# The rest stay `off`. `hunting_hunter` is `high`; `hunting_orchestrator` is `medium`
# (its Q8 gate + D2 re-match turns are reasoning-heavy but turn-count-bounded,
# feat/async-actor-agents). These are TUNABLE
# baselines; #99 makes them capability-adaptive and fail-safe per model.
# `agent_mode="session"` marks the roles that run STATEFUL per instance (#94): the
# per-pod triager and configurator (their own pod session thread each), the
# per-run orchestrator actor, and the analysis proposers (per-pass stateful turns).
ROLES: tuple[Role, ...] = (
    Role("configurator",     "LLM_MODEL_CONFIGURATOR",     "session"),
    Role("triager",          "LLM_MODEL_TRIAGER",          "session",  "medium"),
    Role("job_orchestrator", "LLM_MODEL_JOB_ORCHESTRATOR", "session",  "medium"),
    Role("crawler",          "LLM_MODEL_CRAWLER",          "session"),
    Role("bootstrapper",     "LLM_MODEL_ANALYSER",         "one_shot"),
    Role("assigner",         "LLM_MODEL_ANALYSER",         "session",  "medium"),
    Role("mechanism_typist", "LLM_MODEL_ANALYSER",         "session",  "medium"),
    Role("data_modeller",    "LLM_MODEL_ANALYSER",         "session",  "medium"),
    Role("anatomy",          "LLM_MODEL_ANALYSER",         "one_shot"),
    Role("curation",         "LLM_MODEL_ANALYSER",         "one_shot"),
    Role("sweep",            "LLM_MODEL_ANALYSER",         "one_shot"),
    Role("anti_cluttering",  "LLM_MODEL_ANALYSER",         "one_shot"),
)

# The hunting module's OWN roles (one model per agent), validated by the hunting
# module itself (`attack/hunting/llm.py`), not by app boot - so a fresh
# environment never needs the hunting vars unless hunting is launched.
HUNTING_ROLES: tuple[Role, ...] = (
    Role("hunting_orchestrator", "LLM_MODEL_HUNTING_ORCHESTRATOR", "session", "medium"),
    Role("hunting_hunter",       "LLM_MODEL_HUNTING_HUNTER",       "session", "high"),
)

_ROLE_BY_ID: dict[str, Role] = {r.role_id: r for r in ROLES + HUNTING_ROLES}


def role_record(role_id: str) -> Role | None:
    """The registered `Role` for a role_id, or None for an unregistered one (which
    `resolve_role` still resolves via the `LLM_MODEL_{ROLE_ID}` convention for
    back-compat)."""
    return _ROLE_BY_ID.get(role_id)


def agent_mode(role_id: str) -> AgentMode:
    """The turn mode of a role_id; unregistered ids default to `one_shot`."""
    r = _ROLE_BY_ID.get(role_id)
    return r.agent_mode if r is not None else "one_shot"


def thinking_for(role_id: str) -> ThinkingLevel:
    """The declared thinking/reasoning-effort baseline of a role_id (`off` for an
    unregistered id). The single source callers pass to `build_chat_model`."""
    r = _ROLE_BY_ID.get(role_id)
    return r.thinking if r is not None else "off"


def _key_env(provider: str) -> str:
    """The provider's API-key env var name, `API_KEY_<PROVIDER>`.

    The provider id is uppercased and hyphen->underscore normalized: a
    multi-word provider id like `opencode-go` (a dash) must resolve
    `API_KEY_OPENCODE_GO` (an underscore), because env var names cannot hold
    a dash. Every provider key lookup goes through this single function, so
    the build_chat_model key read, `validate_llm_config`, and the sync's
    `provider_api_key` all agree on the same convention."""
    return f"API_KEY_{provider.upper().replace('-', '_')}"

def resolve_role(role: str) -> tuple[str, str]:
    """Resolve a role_id to (provider, model) via its record's `model_key`.

    A registered role_id reads its declared `model_key` (several ids may share one,
    e.g. every analysis role -> `LLM_MODEL_ANALYSER`). An UNregistered id falls back
    to the `LLM_MODEL_{ID}` convention, so a legacy caller still on `"analyser"`
    keeps resolving `LLM_MODEL_ANALYSER` unchanged during the migration."""
    r = _ROLE_BY_ID.get(role)
    model_key = r.model_key if r is not None else f"LLM_MODEL_{role.upper()}"
    raw = os.environ.get(model_key)
    if not raw or ":" not in raw:
        raise LLMConfigError(
            f"{model_key} must be set to '<provider>:<model>' (got {raw!r})"
        )
    provider, model = raw.split(":", 1)
    return provider.strip(), model.strip()

class ReasoningPreservingChatOpenAI(ChatOpenAI):
    """The T6 reasoning-replay seam (D11 items 3-5): a ChatOpenAI subclass
    that preserves the wire reasoning fields the pinned langchain-openai
    otherwise strips at both conversion boundaries.

    INBOUND (parse): stock `_convert_dict_to_message` drops `reasoning_content`
    and `provider_specific_fields.reasoning_details` from responses - an
    AIMessage comes back with `additional_kwargs={}`. This subclass overrides
    `_create_chat_result` (the one funnel both `_generate` and `_agenerate`
    end in) to capture the RAW response and land the wire values onto the
    AIMessage's `additional_kwargs` (byte-identical), where the T6 extractor
    reads them. Fail-open: any capture failure degrades to the stock strip.

    OUTBOUND (replay): stock `_convert_message_to_dict` serializes only
    whitelisted keys, so a replayed `additional_kwargs` reasoning never
    reaches the wire. This subclass overrides `_get_request_payload` to
    re-serialize the messages and re-emit the reasoning at MESSAGE level
    (`reasoning_content` / `reasoning_details`) - exactly the shape T1
    verified the gateway forwards verbatim on the request transport.

    The subclass is the ticket-sanctioned role-construction path fix (D4
    additive: the seam lives in `app/llm`, no agent module touched). It is
    pinned to langchain-openai 1.3.x's internals (`_create_chat_result`,
    `_get_request_payload`); the unit tier pins the behavioral contract
    (wire capture + message-level re-emit) so a future SDK bump that moves
    these seams turns the tests red on purpose."""

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        try:
            from polymerhus.app.llm.reasoning import (
                land_wire_reasoning,
                response_wire_reasoning,
            )

            wires = response_wire_reasoning(response)
            if not wires or not result.generations:
                return result
            generation = result.generations[0]
            if not isinstance(generation.message, AIMessage):
                return result
            preserved = land_wire_reasoning(generation.message, wires)
            result.generations[0] = ChatGeneration(
                message=preserved, generation_info=generation.generation_info)
        except Exception as exc:  # noqa: BLE001 - fail-open: stock behavior
            logger.debug("reasoning wire capture failed (%s); continuing with "
                         "stock conversion", exc)
        return result

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        messages = payload.get("messages")
        if not isinstance(messages, list):
            return payload
        try:
            from langchain_openai.chat_models.base import (
                _convert_from_v1_to_chat_completions,
                _convert_message_to_dict,
            )
            from polymerhus.app.llm.reasoning import replayed_request_fields

            source = self._convert_input(input_).to_messages()
            serialized = []
            for message in source:
                message_dict = (
                    _convert_message_to_dict(
                        _convert_from_v1_to_chat_completions(message))
                    if isinstance(message, AIMessage)
                    else _convert_message_to_dict(message)
                )
                for surface, value in replayed_request_fields(message).items():
                    if value is not None and surface not in message_dict:
                        message_dict[surface] = value
                serialized.append(message_dict)
            payload["messages"] = serialized
        except Exception as exc:  # noqa: BLE001 - fail-open: request unchanged
            logger.debug("reasoning re-emit failed (%s); request payload "
                         "unchanged", exc)
        return payload


def _thinking_wire_form(provider: str, model: str, thinking: "ThinkingLevel") -> dict:
    """The A5 thinking-effort wire decision (ADR A5, increment-3): the `extra`
    kwargs that make `build_chat_model` emit EXACTLY what the provider/model
    offers for a role's DECLARED `thinking` baseline - never an unconditional
    translation.

    Resolves the capability profile once per (provider, model) (resolve-and-
    hold, D6; the reader is process-lifetime cached) and runs the pure
    `negotiate_thinking` selector to get `(form, value, provenance)`:

    - `form == "effort"` -> `reasoning_effort=<level>` (the wire the gateway
      forwards via `allowed_openai_params`).
    - `form == "budget"` -> `extra_body.thinking.budget_tokens=<int>` (the
      Anthropic-style thinking-budget form the OpenAI-compatible wire carries
      through `extra_body`; the pinned SDK passes it in `extra_body`).
    - `form == "toggle"` -> `extra_body.thinking = {"type": "enabled"}` (the
      thinking-ON toggle for toggle-only control).
    - `form == "omit"` -> `{}` (send nothing: always-on model, off declared,
      no offered level can honor the declared non-off level).

    Off the #73 axis (single synchronous read at first construction, never
    re-entered into the retry wrapper); fail-open (D7): an unknown or
    gateway-less profile keeps the declared baseline (the reader requires no
    gateway and degrades to all-unknown when unconfigured), and the mismatch /
    chosen provenance is logged so a degraded adaptation is observable, never
    silent."""
    if thinking == "off":
        return {}
    try:
        from polymerhus.app.llm.capability import resolve_capability
        from polymerhus.app.llm.negotiation import negotiate_thinking

        profile = resolve_capability(provider, model)
        form, value, provenance = negotiate_thinking(thinking, profile)
    except Exception as exc:  # noqa: BLE001 - fail-open: never into construction
        logger.warning(
            "thinking-effort adaptation failed for %s/%s (%s); keeping the "
            "declared baseline %r as the raw reasoning_effort",
            provider, model, exc, thinking)
        return {"reasoning_effort": thinking}
    logger.info("thinking-effort: provider=%s model=%s declared=%s decision=%s "
                "value=%r provenance=%s", provider, model, thinking, form, value, provenance)
    if form == "effort" and isinstance(value, str):
        return {"reasoning_effort": value}
    if form == "budget" and isinstance(value, int):
        return {"extra_body": {"thinking": {"type": "enabled",
                                            "budget_tokens": value}}}
    if form == "toggle":
        return {"extra_body": {"thinking": {"type": "enabled"}}}
    return {}


def build_chat_model(provider: str, model: str, *, temperature: float = 0,
                     read_timeout: float | None = None,
                     max_retries: int | None = None,
                     thinking: "ThinkingLevel" = "off") -> ChatOpenAI:
    if provider not in PROVIDERS:
        raise LLMConfigError(f"unknown provider {provider!r}; known: {sorted(PROVIDERS)}")
    # #107 (D4 item 1): the gateway base_url resolution seam. Direct mode (UNSET)
    # keeps today's behaviour exactly - `PROVIDERS[provider]` base_url and the
    # client-side zen-family id strip. Gateway mode (SET) routes the client at the
    # gateway; the id strip is NOT run client-side (the gateway's mapping layer
    # owns id translation, D5) and the `provider:model` string goes verbatim.
    base_url = gateway_base_url()
    routing_prefix = None
    if base_url is None:
        base_url = PROVIDERS[provider]
        if provider in _ZEN_FAMILY:
            # The zen gateway speaks its own catalog ids (bare, no provider prefix -
            # e.g. `deepseek-v4-flash-free`), while the operator configures the
            # opencode-app style ids (`deepseek/deepseek-v4-flash-free`). The gateway
            # rejects the prefixed form, so strip the prefix here. The zen catalog
            # contains no `/`, so the last segment is always the id.
            model = model.rsplit("/", 1)[-1]
    else:
        # Gateway mode (#107, D5): the client sends the REGISTERED name the sync
        # pushed - `registered_model_name(provider, model)` - NOT the operator's
        # `provider:model` string verbatim. That single canonical key is what the
        # reader looks up, what the sync registers, and what the D3 virtual-key
        # scopes name (C13/E4/E7: a verbatim `deepseek/deepseek-v4-flash-free`
        # matched no registered route and was either passed upstream unstripped
        # (400) or denied by the key scope (403)). The mapping layer is the sole
        # id translator for every provider kind (zen strip, openrouter verbatim).
        from polymerhus.app.llm.sync_mapping import registered_model_name
        model = registered_model_name(provider, model)
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

    # The thinking BASELINE (#94 / A5): a non-`off` level is ADAPTED to what the
    # provider/model actually offers (capability-adaptive workstream #99, ADR A5
    # increment-3) before it is emitted - the exact `reasoning_effort` / budget /
    # toggle / nothing the wire will carry is a resolved decision, never an
    # unconditional translation. Resolve-and-hold (D6) via the capability
    # reader; off the #73 retry axis; fail-open (D7): an unknown/gateway-less
    # profile keeps the declared baseline and the mismatches are logged.
    extra: dict = _thinking_wire_form(provider, model, thinking)
    return ReasoningPreservingChatOpenAI(model=model, api_key=api_key,
                                         base_url=base_url, temperature=temperature,
                                         timeout=timeout, max_retries=retries,
                                         callbacks=get_langfuse_callbacks(), **extra)

def validate_llm_config(roles: Sequence[Role] | None = None) -> None:
    """Fail fast: every configured role must name a known provider with a present key.

    `roles` defaults to the app-boot `ROLES`. The hunting module passes its own
    `HUNTING_ROLES` at its module bootstrap, so app boot never demands the hunting
    vars (operator ruling 2026-08-06). Roles that share a `model_key` are validated
    once per role_id, which is harmless (the same env var read twice)."""
    problems: list[str] = []
    for role in (ROLES if roles is None else roles):
        try:
            provider, _model = resolve_role(role.role_id)
        except LLMConfigError as e:
            problems.append(str(e)); continue
        if provider not in PROVIDERS:
            problems.append(f"role {role.role_id}: unknown provider {provider!r}")
        elif not os.environ.get(_key_env(provider)):
            problems.append(f"role {role.role_id}: missing {_key_env(provider)}")
    if problems:
        raise LLMConfigError("LLM configuration invalid:\n  - " + "\n  - ".join(problems))
