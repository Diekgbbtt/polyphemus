"""C12/E5: the capability reader against the LIVE gateway (#100, #106 T3).

`resolve_capability(provider, model)` inside the agent container with
`LLM_GATEWAY_URL` set to the co-located proxy (127.0.0.1:4000, ADR D1) - the
reader's own resolution chain: GET /model/info -> record -> typed profile ->
process-lifetime hold (D5 Rule 1, D6, D7).

Assertions:

- C12: for the synced triager model - `context_limit`/`output_limit`/
  `supports_tool_calling`/`source` equal the oracle; the D11 reasoning
  surface per the matrix; a model with NO registered record resolves to
  all-None fields with `context_limit` falling to the env override -> 150k
  default; two calls return the SAME held profile object (identity, not
  equality).
- E5: the full walkthrough of one live resolution + the hold (identity
  across calls), with the profile's authored provenance intact.

The unknown-model probe deliberately uses a name that cannot be registered
(`opencode/does-not-exist-xyz`), so the reader's degradation path is
exercised through the real gateway.
"""

import json

import pytest

from tests.e2e import gateway_stack as gs

pytestmark = pytest.mark.live_neo4j
skip = gs.skip_reason()
pytestmark = pytest.mark.skipif(skip is not None, reason=skip or "agent stack not up for the gateway live tier")

# The triager's configured model (LLM_MODEL_TRIAGER=opencode-go:deepseek/...).
PROVIDER = "opencode-go"
MODEL = "deepseek/deepseek-v4-flash"

GATEWAY_ENV = {"LLM_GATEWAY_URL": gs.GATEWAY_URL}

# The in-container probe: resolve twice (identity hold), probe the unknown
# model, and emit a JSON report. The first resolution may perform the one
# bounded /model/info read; both must return without raising.
PROBE = """
import json
from polymerhus.app.llm.capability import resolve_capability

p1 = resolve_capability(%(provider)r, %(model)r)
p2 = resolve_capability(%(provider)r, %(model)r)
unknown = resolve_capability(%(provider)r, 'does-not-exist-xyz')
print(json.dumps({
    "known": {
        "context_limit": p1.context_limit,
        "output_limit": p1.output_limit,
        "supports_tool_calling": p1.supports_tool_calling,
        "source": p1.source,
        "reasoning_in_response": p1.reasoning_in_response,
        "reasoning_field": p1.reasoning_field,
        "synced_at": str(p1.synced_at) if p1.synced_at else None,
    },
    "identity_held": p1 is p2,
    "unknown": {
        "context_limit": unknown.context_limit,
        "output_limit": unknown.output_limit,
        "supports_tool_calling": unknown.supports_tool_calling,
        "source": unknown.source,
    },
}))
""" % {"provider": PROVIDER, "model": MODEL}

# The unreachable-gateway probe (B4', D6/D7 fail-open): LLM_GATEWAY_URL
# points at a dead loopback port INSIDE the container (127.0.0.1:1 - nothing
# binds port 1), so the reader's one /model/info read is refused. Resolve
# twice to prove the degraded result is held (a second call never re-reads).
DEAD_GATEWAY_ENV = {"LLM_GATEWAY_URL": "http://127.0.0.1:1"}

DEAD_GATEWAY_PROBE = """
import json
from polymerhus.app.llm.capability import resolve_capability

p1 = resolve_capability(%(provider)r, %(model)r)
p2 = resolve_capability(%(provider)r, %(model)r)
print(json.dumps({
    "context_limit": p1.context_limit,
    "output_limit": p1.output_limit,
    "supports_tool_calling": p1.supports_tool_calling,
    "source": p1.source,
    "identity_held": p1 is p2,
}))
""" % {"provider": PROVIDER, "model": MODEL}


def _probe() -> dict:
    result = gs.agent_python(PROBE, env=GATEWAY_ENV, timeout=120)
    assert result.returncode == 0, f"reader probe failed:\n{result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# C12 - the reader vs live /model/info (D5 Rule 1, D6) ----------------------
# ---------------------------------------------------------------------------

def test_c12_known_model_profile_matches_the_oracle():
    report = _probe()
    known = report["known"]
    oracle_by_name = {
        m.model_name: m for m in gs.oracle_desired()}
    expected = oracle_by_name.get(f"opencode-go/deepseek-v4-flash")
    assert expected is not None, "the triager model must be in the oracle set"
    assert expected.known
    expected_info = expected.model_info
    assert known["context_limit"] == expected_info.get("max_input_tokens"), (
        f"context_limit {known['context_limit']} != oracle "
        f"{expected_info.get('max_input_tokens')}")
    assert known["output_limit"] == expected_info.get("max_output_tokens"), (
        f"output_limit {known['output_limit']} != oracle "
        f"{expected_info.get('max_output_tokens')}")
    assert known["supports_tool_calling"] == expected_info.get(
        "supports_function_calling"), "supports_tool_calling != oracle"
    assert known["source"] == f"models.dev/opencode-go/deepseek-v4-flash"
    # D11 reasoning surface per the matrix (interleaved {"field": ...}).
    assert known["reasoning_in_response"] is expected_info.get(
        "reasoning_in_response"), "reasoning_in_response != oracle"
    assert known["reasoning_field"] == expected_info.get("reasoning_field"), (
        "reasoning_field != oracle")


def test_c12_unknown_model_degrades_to_defaults():
    report = _probe()
    unknown = report["unknown"]
    assert unknown["context_limit"] == 150_000, (
        "unknown model must fall to the 150k default (no env override in the "
        f"agent env); got {unknown['context_limit']}")
    assert unknown["output_limit"] is None
    assert unknown["supports_tool_calling"] is None
    assert unknown["source"] is None


def test_c12_resolution_is_held_for_the_process():
    report = _probe()
    assert report["identity_held"] is True, (
        "resolve-and-hold (D7): the second resolution must return the SAME "
        "profile object")


# ---------------------------------------------------------------------------
# E5 - the reader walkthrough (resolve-and-hold through the gateway) ---------
# ---------------------------------------------------------------------------

def test_e5_reader_resolves_and_holds_live_profile():
    """The full path: reader GET /model/info (one synchronous read) -> tagged
    record -> typed profile -> held; identity across calls; provenance
    intact. The gateway's own log records the authed management read."""
    report = _probe()
    assert report["identity_held"] is True
    known = report["known"]
    assert known["source"].startswith("models.dev/")
    assert known["synced_at"], "capability_synced_at must parse"
    logs = gs.gateway_logs()
    # The gateway logs the management read's route; the assertion is
    # deliberately loose (litellm's log lines move between versions).
    assert "/model/info" in logs, (
        "the gateway log must show the /model/info management read")


# ---------------------------------------------------------------------------
# C12 - the reader's unreachable-gateway degradation (B4', D6/D7 fail-open) --
# ---------------------------------------------------------------------------

def test_c12_reader_degrades_to_defaults_when_gateway_unreachable():
    """B4' (D6/D7 fail-open): the gateway URL points at a dead port inside
    the container, so the reader's single /model/info read is refused. The
    resolution must NOT raise; it degrades to the env -> default chain (all
    capability fields None, context_limit falling to the 150k default), and
    the failed read is held - the second call returns the SAME degraded
    profile object without re-reading (off the retry axis; mirrors the unit
    test test_failed_read_is_held_never_retried at the live surface)."""
    result = gs.agent_python(DEAD_GATEWAY_PROBE, env=DEAD_GATEWAY_ENV,
                             timeout=120)
    assert result.returncode == 0, (
        f"dead-gateway probe must not raise:\n{result.stderr}")
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["context_limit"] == 150_000, (
        "an unreachable gateway must fall to the 150k default (no env "
        f"override in the agent env); got {report['context_limit']}")
    assert report["output_limit"] is None, "output_limit must degrade to None"
    assert report["supports_tool_calling"] is None, (
        "supports_tool_calling must degrade to None")
    assert report["source"] is None, "source must degrade to None"
    assert report["identity_held"] is True, (
        "fail-open holds the degraded result (D7): the second call must "
        "return the SAME profile object, never re-reading the dead gateway")
