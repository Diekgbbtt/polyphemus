"""Unit tests for the LiteLLM gateway proxy config (ADR D1, D8, D10 - #104, T1).

The config file is the declarative surface for the gateway: the EMPTY
`model_list` (T2 fills it via the management API), the D8 auto-inject
stanza, and `store_model_in_db`. These tests pin the shape so a silent edit
(a response-cache stanza slipping in, an accidental model entry, the
master_key landing in the repo) fails loudly in the unit tier before it ever
reaches the container.

PyYAML is available (the base image + the dev venv ship it). The test loads
and asserts; no disk write, no subprocess, no network.
"""

from pathlib import Path

import pytest
import yaml

from polymerhus.app.gateway_entrypoint import PROXY_PORT

# Resolve the config path relative to the repo root (the worktree shares the
# repo layout). The entrypoint reads `CONFIG_FILE_PATH` at boot; we don't
# couple this test to that env var - we resolve it from the known repo path.
CONFIG_PATH = Path(__file__).resolve().parents[1] / "gateway" / "litellm_config.yaml"


@pytest.fixture(scope="module")
def config() -> dict:
    if not CONFIG_PATH.exists():
        pytest.fail(
            f"gateway config not found at {CONFIG_PATH} - the YAML is a required "
            f"deliverable of #104")
    return yaml.safe_load(CONFIG_PATH.read_text())


# ---------------------------------------------------------------------------
# model_list: empty, T2 fills it via the mgmt API (ADR D10) ----------------
# ---------------------------------------------------------------------------

def test_model_list_is_empty_at_bootstrap(config):
    """The gateway ships with NO models registered in the YAML.

    T2 (#105) adds models via the management API (litellm.hooks); they land in
    `LiteLLM_ProxyModelTable` and overlay this empty bootstrap. A model entry
    here would short-circuit T2's diff-and-push and silently double register."""
    assert config.get("model_list") == [], (
        "the bootstrap model_list MUST be empty - T2 fills it via the mgmt API")


# ---------------------------------------------------------------------------
# store_model_in_db: against the shared postgres (ADR D1) ------------------
# ---------------------------------------------------------------------------

def test_store_model_in_db_is_true(config):
    """`store_model_in_db: true` so litellm persists model records in the shared
    postgres (ADR D1: "under litellm's own tables"). T2's diffable push relies
    on this - the management API writes land in `LiteLLM_ProxyModelTable`."""
    assert config.get("general_settings", {}).get("store_model_in_db") is True


# ---------------------------------------------------------------------------
# D8: prompt caching - auto-inject, NO response cache -----------------------
# ---------------------------------------------------------------------------

def test_d8_auto_inject_is_enabled(config):
    """ADR D8: the auto-inject primitive IS configured (`enable_anthropic_prompt_caching`).
    It is a gateway-wide system-prompt breakpoint + trailing-turn breakpoint
    for Claude-family models - a no-op on the current openai-compatible provider
    set (DeepSeek + OpenAI cache automatically server-side), covers a future
    Anthropic-family entry without a client code change."""
    assert config.get("litellm_settings", {}).get(
        "enable_anthropic_prompt_caching") is True


def test_unsupported_client_params_are_dropped(config):
    """The role thinking baseline (`providers.py` `thinking`) sends the OpenAI
    `reasoning_effort` param in gateway mode. The openai-compatible upstream
    wire has NO such param, and litellm's openai provider rejects it with
    `UnsupportedParamsError` (400) unless the proxy drops it - verified live
    2026-08-18 via the E7 reasoning-replay walkthrough. `drop_params: true`
    strips unsupported params before routing (litellm's own error directive)
    so a client tuning hint never 400s the whole turn."""
    assert config.get("litellm_settings", {}).get("drop_params") is True


def test_d8_response_cache_is_absent(config):
    """ADR D8: the `LITELLM_CACHE_TYPE` response cache is EXPLICITLY OUT.

    The cacheable surface of a stateful agent loop is the PREFIX (handled
    provider-side via auto-inject above), not the WHOLE request. A response
    cache would risk stale tool results and corrupted observability. The
    config carries NO `cache:` stanza under `litellm_settings` - its presence
    would be a silent ADR violation."""
    litellm_settings = config.get("litellm_settings", {})
    assert "cache" not in litellm_settings, (
        "ADR D8 rules out the response cache - no `litellm_settings.cache` "
        "stanza may live in this config")
    # Also block the env-var alias if it ever sneaks into the YAML's env block
    # (it wouldn't, but the test is cheap and the violation is loud).
    assert "LITELLM_CACHE_TYPE" not in config.get("environment_variables", {})


# ---------------------------------------------------------------------------
# Secrets NEVER in the repo (ADR D10) --------------------------------------
# ---------------------------------------------------------------------------

def test_no_secrets_in_config(config):
    """`LITELLM_MASTER_KEY` and `DATABASE_URL` enter via env only (ADR D10:
    "from env, never in the repo"). The config MUST NOT carry `master_key` or
    `database_url` under `general_settings` - their presence here would commit
    a secret to the repo."""
    general = config.get("general_settings", {})
    assert "master_key" not in general, (
        "LITELLM_MASTER_KEY must be env-only - never in the repo config")
    assert "database_url" not in general, (
        "DATABASE_URL must be env-only - never in the repo config")
