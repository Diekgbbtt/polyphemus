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
    # Derive from P.ROLES so adding a role never breaks this test; each role now
    # carries its own model_key (records, #93/#94), not `LLM_MODEL_{role.upper()}`.
    for r in P.ROLES:
        monkeypatch.setenv(r.model_key, "openai:gpt-4o")
    monkeypatch.setenv("LLM_MODEL_TRIAGER", "bogus:model")
    monkeypatch.setenv("API_KEY_OPENAI", "sk-x")
    with pytest.raises(P.LLMConfigError):
        P.validate_llm_config()

def test_validate_passes_when_all_present(monkeypatch):
    # Derive from P.ROLES so every configured role's model_key is covered.
    for r in P.ROLES:
        monkeypatch.setenv(r.model_key, "swissai:meta-llama/Llama-3.3-70B-Instruct")
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    P.validate_llm_config()  # no raise

def test_analysis_roles_share_the_analyser_key_and_it_is_required(monkeypatch):
    """#93: `analyser` is split into per-cognitive-job role_ids (assigner,
    mechanism_typist, data_modeller, ...) that SHARE `LLM_MODEL_ANALYSER`
    (many-to-one), so validate_llm_config still requires that key at boot."""
    ids = {r.role_id for r in P.ROLES}
    assert {"assigner", "mechanism_typist", "data_modeller"} <= ids
    assert "analyser" not in ids  # the conflated single role is gone
    assert P.role_record("assigner").model_key == "LLM_MODEL_ANALYSER"
    assert P.role_record("mechanism_typist").model_key == "LLM_MODEL_ANALYSER"
    for r in P.ROLES:
        monkeypatch.setenv(r.model_key, "swissai:x")
    monkeypatch.delenv("LLM_MODEL_ANALYSER", raising=False)  # the shared analysis key unset
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    with pytest.raises(P.LLMConfigError) as e:
        P.validate_llm_config()
    assert "ANALYSER" in str(e.value)


def test_role_record_carries_agent_mode():
    """agent_mode is a property of the role (one_shot | session), not the model."""
    assert P.agent_mode("assigner") == "session"
    assert P.agent_mode("mechanism_typist") == "session"
    assert P.agent_mode("data_modeller") == "session"
    assert P.agent_mode("triager") == "session"
    assert P.agent_mode("configurator") == "session"
    assert P.agent_mode("curation") == "one_shot"
    assert P.agent_mode("hunting_hunter") == "session"
    assert P.agent_mode("hunting_orchestrator") == "session"
    assert P.agent_mode("job_orchestrator") == "session"
    assert P.agent_mode("unregistered_role") == "one_shot"  # safe default


def test_resolve_role_uses_the_shared_key_for_split_analysis_roles(monkeypatch):
    """Distinct analysis role_ids resolve the SAME model via LLM_MODEL_ANALYSER, and
    a legacy caller still on the bare `"analyser"` id resolves it via the fallback
    convention - so callers can migrate incrementally."""
    monkeypatch.setenv("LLM_MODEL_ANALYSER", "swissai:Qwen/Qwen3.5-397B-A17B-ETar")
    assert P.resolve_role("assigner") == ("swissai", "Qwen/Qwen3.5-397B-A17B-ETar")
    assert P.resolve_role("mechanism_typist") == ("swissai", "Qwen/Qwen3.5-397B-A17B-ETar")
    assert P.resolve_role("analyser") == ("swissai", "Qwen/Qwen3.5-397B-A17B-ETar")  # fallback


def test_hunting_roles_are_not_validated_at_app_boot(monkeypatch):
    """Operator ruling 2026-08-06: hunting roles validate at the HUNTING module
    bootstrap, never app boot. So validate_llm_config() (app boot) must not demand
    the hunting model keys, while validate_llm_config(HUNTING_ROLES) does."""
    hunting_ids = {r.role_id for r in P.HUNTING_ROLES}
    assert hunting_ids == {"hunting_orchestrator", "hunting_hunter",
                           "pod_runner", "pod_triager"}
    assert not (hunting_ids & {r.role_id for r in P.ROLES})  # absent from app-boot ROLES
    for r in P.ROLES:
        monkeypatch.setenv(r.model_key, "swissai:x")
    for r in P.HUNTING_ROLES:
        monkeypatch.delenv(r.model_key, raising=False)  # hunting vars ABSENT
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    P.validate_llm_config()  # app boot: no raise despite hunting vars absent
    with pytest.raises(P.LLMConfigError) as e:
        P.validate_llm_config(P.HUNTING_ROLES)  # hunting bootstrap: now demanded
    assert "HUNTING" in str(e.value)

def test_build_chat_model_sets_generous_max_completion_tokens_budget(monkeypatch):
    """The reasoning-token-exhaustion fix: EVERY model construction carries a
    generous `max_completion_tokens` (the reasoning-INCLUSIVE output budget) so a
    thinking-heavy turn still has room to emit its answer. It rides in
    `model_kwargs` (the pinned langchain-openai ChatOpenAI has no such field) and
    must reach the wire payload verbatim. Overridable via
    `LLM_MAX_COMPLETION_TOKENS`."""
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    m = P.build_chat_model("swissai", "meta-llama/Llama-3.3-70B-Instruct")
    payload = m._get_request_payload([{"role": "user", "content": "hi"}], stop=None)
    assert payload.get("max_completion_tokens") == P.DEFAULT_MAX_COMPLETION_TOKENS
    # the reasoning-INCLUSIVE param is sent; the legacy max_tokens is NOT (the
    # OpenAI SDK rejects sending both - the wire must carry exactly one).
    assert "max_tokens" not in payload


def test_build_chat_model_respects_llm_max_completion_tokens_override(monkeypatch):
    """The budget is a config dial: `LLM_MAX_COMPLETION_TOKENS` overrides the
    default; an unusable value (non-int or non-positive) is a config lie and
    fails fast rather than silently degrading."""
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    monkeypatch.setenv("LLM_MAX_COMPLETION_TOKENS", "65536")
    m = P.build_chat_model("swissai", "meta-llama/Llama-3.3-70B-Instruct")
    payload = m._get_request_payload([{"role": "user", "content": "hi"}], stop=None)
    assert payload.get("max_completion_tokens") == 65536
    for bad in ("not-a-number", "0", "-5"):
        monkeypatch.setenv("LLM_MAX_COMPLETION_TOKENS", bad)
        with pytest.raises(P.LLMConfigError):
            P.max_completion_tokens()


def test_build_chat_model_sets_base_url_and_key(monkeypatch):
    """Direct mode: the base_url is `PROVIDERS[provider]`. `LLM_GATEWAY_URL` is
    pinned UNSET so a gateway-configured shell cannot silently flip this test
    into gateway mode (#107) - these pre-seam assertions are direct-mode ones."""
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
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
    """Direct-mode pin (as in the base_url test above): the qwen id passes
    VERBATIM to the direct provider, with the strip a no-op for a non-zen
    provider."""
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
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
    """#32/FM-4: the SDK's silent default of 2 must not be inherited. `MAX_RETRIES`
    is the DEFAULT retry, which (post-#73) belongs to the AGENT / injectable-model
    per-turn callers (crawl, steering/job_agent) - single-shot role calls go through
    `invoke_role`, which passes `max_retries=0` and owns the escalating retry
    instead, so the two layers never multiply."""
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    m = P.build_chat_model("swissai", "x")
    assert m.root_client.max_retries == P.MAX_RETRIES
    assert P.MAX_RETRIES == 1
    # FM-5: NOT zero for the DEFAULT/agent path - it is the only layer that backs off
    # and honours Retry-After for a multi-turn agent turn. The escalating wrapper
    # explicitly opts single-shot calls down to 0.
    assert P.MAX_RETRIES > 0
    # invoke_role's per-attempt client carries no client-side retry (the wrapper is
    # the sole retry), so the #32 multiplication cannot recur.
    assert P.build_chat_model("swissai", "x", max_retries=0).root_client.max_retries == 0


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

    # Direct-mode pin (#107): the hang scenario is a DIRECT provider that accepts
    # and never answers; a gateway-configured shell must not redirect this probe.
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)

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


# --- #73 (D6): the single escalating-budget retry layer ----------------------

def test_attempt_timeouts_default_schedule_escalates(monkeypatch):
    monkeypatch.delenv("LLM_ATTEMPT_TIMEOUTS_S", raising=False)
    sched = P.attempt_timeouts()
    assert sched == P.DEFAULT_ATTEMPT_TIMEOUTS_S == (300.0, 600.0, 900.0, 2700.0)
    assert list(sched) == sorted(sched), "budget must grow, never shrink, per attempt"


def test_attempt_timeouts_override_and_fail_fast(monkeypatch):
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "10, 20, 40")
    assert P.attempt_timeouts() == (10.0, 20.0, 40.0)
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "")  # unset-equivalent -> default
    assert P.attempt_timeouts() == P.DEFAULT_ATTEMPT_TIMEOUTS_S
    for bad in ("soon", "0", "-5", "10,nope"):
        monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", bad)
        with pytest.raises(P.LLMConfigError):
            P.attempt_timeouts()


def test_escalating_invoke_grows_the_budget_and_returns_first_success(monkeypatch):
    """A slow-but-healthy call that misses the first budget succeeds on a later,
    larger one - and the budget handed to each attempt strictly grows."""
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "1, 2, 4")
    seen: list[float] = []

    def call(budget):
        seen.append(budget)
        return "ok" if budget >= 2 else None   # first (budget=1) unmet, second succeeds

    assert P.invoke_with_escalating_timeout(call) == "ok"
    assert seen == [1.0, 2.0]                   # stopped at the first success, budgets grew


def test_escalating_invoke_fail_closes_to_none_after_all_attempts_raise(monkeypatch):
    """Faithful to the retired bounded_retry/_invoke_with_retry: a persistently
    raising provider is retried under each larger budget, then fail-CLOSES to None
    (the caller's established empty-step signal) - it never re-raises to crash the
    caller, and never hangs."""
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "1, 2")
    budgets: list[float] = []

    def call(budget):
        budgets.append(budget)
        raise TimeoutError(f"hung@{budget}")

    assert P.invoke_with_escalating_timeout(call) is None
    assert budgets == [1.0, 2.0]                # every budget was tried, in order


def test_escalating_invoke_returns_none_when_every_attempt_is_unmet(monkeypatch):
    monkeypatch.setenv("LLM_ATTEMPT_TIMEOUTS_S", "1, 2, 3")
    assert P.invoke_with_escalating_timeout(lambda budget: None) is None


# --- thinking / reasoning-effort baseline (#94) -------------------------------

def test_thinking_baselines_are_set_on_the_reasoning_agents():
    """The operator-directed baseline: the hunter reasons `high` and the
    hunt-orchestrator (its Q8 gate + D2 re-match turns) `medium`; the analysis
    proposers, the recon triager, and the recon-orchestrator (the
    `job_orchestrator` role) reason `medium`; every other role stays `off`."""
    assert P.thinking_for("hunting_hunter") == "high"
    assert P.thinking_for("hunting_orchestrator") == "medium"   # Q8 gate + D2 re-match
    assert P.thinking_for("assigner") == "medium"
    assert P.thinking_for("mechanism_typist") == "medium"
    assert P.thinking_for("data_modeller") == "medium"
    assert P.thinking_for("triager") == "medium"
    assert P.thinking_for("job_orchestrator") == "medium"      # = the recon-orchestrator
    # untouched agents + unregistered ids default off
    for r in ("bootstrapper", "curation", "sweep", "crawler", "configurator",
              "not_a_role"):
        assert P.thinking_for(r) == "off"


def test_build_chat_model_applies_reasoning_effort_only_when_thinking_on(monkeypatch):
    monkeypatch.setenv("API_KEY_OPENROUTER", "tok")
    on = P.build_chat_model("openrouter", "openai/gpt-5-mini", thinking="high")
    off = P.build_chat_model("openrouter", "openai/gpt-4.1-mini", thinking="off")
    assert on.reasoning_effort == "high"
    assert getattr(off, "reasoning_effort", None) is None


def test_chat_model_for_carries_the_roles_thinking_baseline(monkeypatch):
    """The wiring: a model built for a thinking role reasons at its baseline, so a
    session/stateful agent off `chat_model_for` inherits it without extra plumbing."""
    from polymerhus.app.llm.roles import chat_model_for
    monkeypatch.setenv("LLM_MODEL_HUNTING_HUNTER", "openrouter:openai/gpt-5-mini")
    monkeypatch.setenv("LLM_MODEL_ANALYSER", "openrouter:openai/gpt-4.1-mini")
    monkeypatch.setenv("API_KEY_OPENROUTER", "tok")
    assert chat_model_for("hunting_hunter").reasoning_effort == "high"
    assert chat_model_for("assigner").reasoning_effort == "medium"
    assert getattr(chat_model_for("bootstrapper"), "reasoning_effort", None) is None


# --- A5 thinking-effort wire decision (increment-3, ticket #162) -------------

def _with_profile(monkeypatch, profile):
    """Pin the capability profile the seam resolves (via the lazily-imported
    `resolve_capability`) so the wire decision is deterministic - no live
    gateway. The profile is returned for every (provider, model)."""
    from polymerhus.app.llm import capability as C

    monkeypatch.setenv("API_KEY_OPENROUTER", "tok")
    monkeypatch.setattr(C, "resolve_capability", lambda provider, model: profile)


def test_wire_effort_exact_match(monkeypatch):
    from polymerhus.app.llm.capability import CapabilityProfile

    _with_profile(monkeypatch, CapabilityProfile(
        reasoning_control="effort", reasoning_efforts=("low", "medium", "high")))
    m = P.build_chat_model("openrouter", "openai/gpt-5-mini", thinking="medium")
    assert getattr(m, "reasoning_effort", None) == "medium"


def test_wire_effort_fallback_nearest_at_least_as_much(monkeypatch):
    """The ADR example through the real seam: declared `medium`, offered
    `[high, max]` -> the wire carries `high` (never a downgrade, never a 400)."""
    from polymerhus.app.llm.capability import CapabilityProfile

    _with_profile(monkeypatch, CapabilityProfile(
        reasoning_control="effort", reasoning_efforts=("high", "max")))
    m = P.build_chat_model("openrouter", "openai/gpt-5-mini", thinking="medium")
    assert getattr(m, "reasoning_effort", None) == "high"


def test_wire_budget_emits_extra_body_budget_tokens(monkeypatch):
    from polymerhus.app.llm.capability import CapabilityProfile

    _with_profile(monkeypatch, CapabilityProfile(
        reasoning_control="budget_tokens", thinking_budget_bounds=(1024, 32768)))
    m = P.build_chat_model("openrouter", "openai/gpt-5-mini", thinking="medium")
    assert m.extra_body == {"thinking": {"type": "enabled", "budget_tokens": 4096}}


def test_wire_budget_clamped_to_declared_bounds(monkeypatch):
    from polymerhus.app.llm.capability import CapabilityProfile

    _with_profile(monkeypatch, CapabilityProfile(
        reasoning_control="budget_tokens", thinking_budget_bounds=(1024, 2000)))
    m = P.build_chat_model("openrouter", "openai/gpt-5-mini", thinking="medium")
    assert m.extra_body["thinking"]["budget_tokens"] == 2000


def test_wire_toggle_emits_thinking_enabled(monkeypatch):
    from polymerhus.app.llm.capability import CapabilityProfile

    _with_profile(monkeypatch, CapabilityProfile(reasoning_control="toggle"))
    m = P.build_chat_model("openrouter", "openai/gpt-5-mini", thinking="high")
    assert m.extra_body == {"thinking": {"type": "enabled"}}


def test_wire_always_on_omits(monkeypatch):
    from polymerhus.app.llm.capability import CapabilityProfile

    _with_profile(monkeypatch, CapabilityProfile(reasoning_control="none"))
    m = P.build_chat_model("openrouter", "openai/gpt-5-mini", thinking="high")
    assert getattr(m, "reasoning_effort", None) is None
    assert m.extra_body is None


def test_wire_off_omits_even_with_an_effort_profile(monkeypatch):
    from polymerhus.app.llm.capability import CapabilityProfile

    _with_profile(monkeypatch, CapabilityProfile(
        reasoning_control="effort", reasoning_efforts=("low", "medium", "high")))
    m = P.build_chat_model("openrouter", "openai/gpt-5-mini", thinking="off")
    assert getattr(m, "reasoning_effort", None) is None
    assert m.extra_body is None


def test_wire_unknown_profile_keeps_the_declared_baseline(monkeypatch):
    """D7 fail-open through the real seam: a gateway-less environment (or an
    unregistered record) resolves an all-unknown profile, and the declared
    baseline is sent unchanged - the legacy behaviour is preserved exactly."""
    from polymerhus.app.llm.capability import CapabilityProfile

    _with_profile(monkeypatch, CapabilityProfile())
    m = P.build_chat_model("openrouter", "openai/gpt-5-mini", thinking="high")
    assert getattr(m, "reasoning_effort", None) == "high"


def test_wire_adaptation_failure_falls_back_to_declared_baseline(monkeypatch):
    """Fail-open: an unexpected adaptation error must never break construction -
    the declared baseline rides as the raw reasoning_effort, session still starts."""
    from polymerhus.app.llm import capability as C

    def _boom(provider, model):
        raise RuntimeError("boom")

    monkeypatch.setenv("API_KEY_OPENROUTER", "tok")
    monkeypatch.setattr(C, "resolve_capability", _boom)
    m = P.build_chat_model("openrouter", "openai/gpt-5-mini", thinking="high")
    assert getattr(m, "reasoning_effort", None) == "high"


# --- #107 (D4 item 1): the LLM_GATEWAY_URL base_url resolution seam ------------
#
# Two LLM-facing paths live, selected by a single env var (ADR D3 + D5):
#   LLM_GATEWAY_URL UNSET -> direct per-provider mode (today's behaviour, unchanged)
#   LLM_GATEWAY_URL SET   -> route the client at the gateway (internal port 4000);
#                            the client sends the canonical REGISTERED name
#                            (`registered_model_name`, the name the sync pushed and
#                            the reader/keys resolve) - the mapping layer is the
#                            sole id translator (D5), never the client.
# In BOTH modes the client keeps `max_retries=0` under the escalating wrapper
# (#73 - the client owns the SINGLE retry layer; the gateway is a hop with
# `num_retries=0`, never nested), and attaches Langfuse callbacks at
# construction (D8 passthrough).
# `validate_llm_config` keeps requiring `API_KEY_<PROVIDER>` in both modes
# (operator decision: the per-provider key stays the auth surface; the gateway
# trusts the authenticated caller and routes upstream with its own key custody).

def test_id_kind_classifies_aggregators_and_native_providers():
    """The id-kind policy table (D5): the bare-catalog zen aggregators are
    `ID_KIND_ZEN`; openrouter and native openai-compatible providers default to
    verbatim - so opencode zen's ids are stripped while openrouter's slashed ids
    (which the upstream accepts as-is) pass through untouched."""
    assert P.id_kind("opencode") == P.ID_KIND_ZEN
    assert P.id_kind("opencode-go") == P.ID_KIND_ZEN
    assert P.id_kind("zen") == P.ID_KIND_ZEN
    assert P.id_kind("openrouter") == P.ID_KIND_VERBATIM
    assert P.id_kind("openai") == P.ID_KIND_VERBATIM
    assert P.id_kind("swissai") == P.ID_KIND_VERBATIM
    # unlisted providers default to verbatim - the transparent, safe default
    assert P.id_kind("some-future-aggregator") == P.ID_KIND_VERBATIM


def test_gateway_unset_direct_mode_uses_provider_base_url_and_strips_zen_id(monkeypatch):
    """UNSET = today's direct mode: base_url is PROVIDERS[provider], and the zen
    family id strip RUNS client-side (the opencode/zen gateway speaks bare catalog
    ids, so the `provider/` prefix is stripped before the request)."""
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    monkeypatch.setenv("API_KEY_OPENCODE", "tok")
    m = P.build_chat_model("opencode", "deepseek/deepseek-v4-flash-free")
    assert str(m.openai_api_base) == P.PROVIDERS["opencode"]
    assert m.model_name == "deepseek-v4-flash-free"  # the strip ran client-side


def test_gateway_unset_direct_mode_keeps_non_zen_id_verbatim(monkeypatch):
    """UNSET + a non-zen provider: the strip is a no-op (the id has no provider
    prefix to remove). Pin both the base_url and the verbatim model name."""
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    m = P.build_chat_model("swissai", "Qwen/Qwen3.5-397B-A17B-ETar")
    assert str(m.openai_api_base) == P.PROVIDERS["swissai"]
    assert m.model_name == "Qwen/Qwen3.5-397B-A17B-ETar"


def test_gateway_set_routes_at_the_gateway_url(monkeypatch):
    """SET = gateway mode: base_url points at the env var's URL (internal port
    4000), NOT at PROVIDERS[provider]. The gateway then routes upstream."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway:4000")
    monkeypatch.setenv("API_KEY_OPENAI", "tok")
    m = P.build_chat_model("openai", "gpt-4o")
    assert str(m.openai_api_base) == "http://gateway:4000"
    assert str(m.openai_api_base) != P.PROVIDERS["openai"]


def test_key_env_normalizes_hyphens_to_underscores():
    """A provider id with a dash (e.g. `opencode-go`) must resolve its API key
    env var with the underscore form (`API_KEY_OPENCODE_GO`), never a dash -
    env var names cannot hold a dash. `_key_env` is the single source of this
    convention, used by build_chat_model, validate_llm_config, and the sync's
    provider_api_key alike."""
    assert P._key_env("opencode-go") == "API_KEY_OPENCODE_GO"
    assert P._key_env("opencode") == "API_KEY_OPENCODE"
    assert P._key_env("openai") == "API_KEY_OPENAI"


def test_gateway_set_does_not_strip_zen_id_client_side(monkeypatch):
    """SET + a zen-family provider: the client sends the REGISTERED name the
    sync pushed (`registered_model_name`): `<provider>/<bare-zen-id>`. The
    mapping layer owns id translation (ADR D5) - the operator's prefixed
    `provider:model` string is translated here, NOT sent verbatim (a verbatim
    `deepseek/deepseek-v4-flash-free` matches no registered route and is
    400/403'd by the gateway, C13/E4/E7)."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway:4000")
    monkeypatch.setenv("API_KEY_OPENCODE", "tok")
    m = P.build_chat_model("opencode", "deepseek/deepseek-v4-flash-free")
    assert m.model_name == "opencode/deepseek-v4-flash-free"
    assert str(m.openai_api_base) == "http://gateway:4000"


def test_gateway_set_sends_registered_name_across_providers(monkeypatch):
    """SET mode contract: the client sends the canonical REGISTERED name
    (`<provider>/<native-id>`) in EVERY case - openai, openrouter, swissai -
    the name the sync registered and the reader/keys resolve (D5, C13/E4/E7).
    For a verbatim aggregator/protocol provider the registered name is the id
    verbatim; for the bare-catalog zen family the strip already ran in the
    mapping layer."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway:4000")
    monkeypatch.setenv("API_KEY_OPENAI", "tok")
    monkeypatch.setenv("API_KEY_OPENROUTER", "tok")
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    assert P.build_chat_model("openai", "gpt-4o").model_name == "openai/gpt-4o"
    assert (P.build_chat_model("openrouter", "anthropic/claude-3.5-sonnet").model_name
            == "openrouter/anthropic/claude-3.5-sonnet")
    assert (P.build_chat_model("swissai", "Qwen/Qwen3.5-397B-A17B-ETar").model_name
            == "swissai/Qwen/Qwen3.5-397B-A17B-ETar")


def test_gateway_set_sends_per_provider_api_key_to_the_gateway(monkeypatch):
    """Operator decision: API_KEY_<PROVIDER> stays required in BOTH modes; in
    gateway mode the per-provider key is the auth surface the client presents to
    the gateway (the gateway holds the upstream keys itself, ADR D3)."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway:4000")
    monkeypatch.setenv("API_KEY_OPENAI", "sk-client-to-gateway")
    m = P.build_chat_model("openai", "gpt-4o")
    assert m.openai_api_key.get_secret_value() == "sk-client-to-gateway"


def test_gateway_unset_and_set_keep_max_retries_zero_for_escalating_wrapper(monkeypatch):
    """#73 non-regression: the escalating-budget wrapper passes `max_retries=0`
    because it OWNS the retry; the client must not silently re-multiply the budget.
    This holds in BOTH modes - the gateway is a hop with its own `num_retries=0`,
    never a nested retry layer (ADR D3)."""
    monkeypatch.setenv("API_KEY_OPENAI", "tok")
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    assert P.build_chat_model("openai", "x", max_retries=0).root_client.max_retries == 0
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway:4000")
    assert P.build_chat_model("swissai", "x", max_retries=0).root_client.max_retries == 0


def test_gateway_default_max_retries_unchanged_in_both_modes(monkeypatch):
    """The DEFAULT `max_retries` (the agent per-turn retry, MAX_RETRIES=1) is
    unchanged in both modes - the gateway seam touches base_url + the zen-strip,
    never the retry axis."""
    monkeypatch.setenv("API_KEY_OPENAI", "tok")
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    assert P.build_chat_model("openai", "x").root_client.max_retries == P.MAX_RETRIES == 1
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway:4000")
    assert P.build_chat_model("openai", "x").root_client.max_retries == P.MAX_RETRIES == 1


def test_gateway_set_keeps_langfuse_callbacks_at_construction(monkeypatch):
    """D8 passthrough: Langfuse callbacks are attached at construction in BOTH
    modes (no observability regression). The gateway must pass them through.
    `providers.py` imports `get_langfuse_callbacks` lazily INSIDE
    `build_chat_model`, so patching the observability module's function observes
    the real construction path - it must be invoked once per model built, in
    direct mode AND in gateway mode."""
    monkeypatch.setenv("API_KEY_OPENAI", "tok")
    seen_calls = []
    import polymerhus.app.observability as obs

    def fake_get():
        seen_calls.append(True)
        return []

    monkeypatch.setattr(obs, "get_langfuse_callbacks", fake_get)
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    P.build_chat_model("openai", "x")
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway:4000")
    P.build_chat_model("openai", "x")
    assert len(seen_calls) == 2, "Langfuse callbacks must be fetched at construction in BOTH modes"


def test_gateway_set_unknown_provider_still_raises(monkeypatch):
    """The known-provider check is invariant: gateway mode does NOT relax the
    provider gate (an unknown provider is a config error in both modes), because
    the client's `provider:model` contract is what the gateway maps to upstream -
    a provider the client does not know cannot be sent verbatim."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway:4000")
    with pytest.raises(P.LLMConfigError):
        P.build_chat_model("bogus", "x")


def test_validate_llm_config_still_requires_per_provider_key_in_gateway_mode(monkeypatch):
    """Operator decision (this ticket's open question, resolved): API_KEY_<PROVIDER>
    stays REQUIRED in BOTH modes - the per-provider key is the auth surface the
    client presents to the gateway. So `validate_llm_config` is UNCHANGED; setting
    LLM_GATEWAY_URL does not relax the boot-time key check."""
    for r in P.ROLES:
        monkeypatch.setenv(r.model_key, "openrouter:some/model")
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway:4000")
    monkeypatch.delenv("API_KEY_OPENROUTER", raising=False)
    with pytest.raises(P.LLMConfigError) as e:
        P.validate_llm_config()
    assert "OPENROUTER" in str(e.value)


def test_validate_llm_config_passes_in_gateway_mode_when_per_provider_key_present(monkeypatch):
    """Gateway mode is transparent to validate_llm_config: with the per-provider
    key present and a known provider, boot validation passes - the same green path
    as direct mode. The seam does not alter the boot-time role->provider->key
    chain."""
    for r in P.ROLES:
        monkeypatch.setenv(r.model_key, "swissai:meta-llama/Llama-3.3-70B-Instruct")
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway:4000")
    monkeypatch.setenv("API_KEY_SWISSAI", "tok")
    P.validate_llm_config()  # no raise


def test_gateway_url_with_trailing_slash_is_sent_as_configured(monkeypatch):
    """The seam sends the env var's URL VERBATIM as the base_url - it does not
    silently normalise a trailing slash away (a normalisation could mask an
    operator misconfiguration that the gateway then rejects, which is the
    hard-to-spot failure the conservative-unknown principle names)."""
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway:4000/")
    monkeypatch.setenv("API_KEY_OPENAI", "tok")
    m = P.build_chat_model("openai", "gpt-4o")
    assert str(m.openai_api_base) == "http://gateway:4000/"


def test_gateway_base_url_is_none_when_unset_or_blank(monkeypatch):
    """The mode selector: an unset, empty, or whitespace-only `LLM_GATEWAY_URL`
    all select DIRECT mode (None) - the same unset-equivalent convention the
    timeout overrides use - and a set value is returned verbatim."""
    monkeypatch.delenv("LLM_GATEWAY_URL", raising=False)
    assert P.gateway_base_url() is None
    monkeypatch.setenv("LLM_GATEWAY_URL", "")
    assert P.gateway_base_url() is None
    monkeypatch.setenv("LLM_GATEWAY_URL", "   ")
    assert P.gateway_base_url() is None
    monkeypatch.setenv("LLM_GATEWAY_URL", "http://gateway:4000")
    assert P.gateway_base_url() == "http://gateway:4000"
