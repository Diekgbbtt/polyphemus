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
    assert hunting_ids == {"hunting_orchestrator", "hunting_hunter"}
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
    """The operator-directed baseline: the hunter reasons `high`; the analysis
    proposers, the recon triager, and the recon-orchestrator (the `job_orchestrator`
    role) reason `medium`; every other role stays `off`."""
    assert P.thinking_for("hunting_hunter") == "high"
    assert P.thinking_for("assigner") == "medium"
    assert P.thinking_for("mechanism_typist") == "medium"
    assert P.thinking_for("data_modeller") == "medium"
    assert P.thinking_for("triager") == "medium"
    assert P.thinking_for("job_orchestrator") == "medium"      # = the recon-orchestrator
    # untouched agents + unregistered ids default off
    for r in ("bootstrapper", "curation", "sweep", "crawler", "configurator",
              "hunting_orchestrator", "not_a_role"):
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
