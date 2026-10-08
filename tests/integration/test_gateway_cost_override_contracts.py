"""#330 iteration 2: the gateway authors the provider cost override, and the
litellm cost engine (the budget guard's USD math) consumes it.

Two contracts:

1. The REAL sync pipeline (`run_sync` -> `build_desired` -> `diff_desired` ->
   push) over a stateful, recording stand-in for the litellm management API
   registers `opencode-go/deepseek-v4.1-flash` with the OVERRIDE cost in its
   `model_info`, not the ~6x-higher models.dev record. A no-change re-run is
   idle (the override is idempotent and never fights the convergence diff).

2. The REAL litellm cost engine, given the authored `model_info`, prices a
   request at the override rate. The deployment `model_info` path
   (`_get_token_base_cost`, what the proxy registers into `litellm.model_cost`)
   reads the authored canonical keys, including `cache_read_input_token_cost`.

In-network: litellm is installed in the agent image the tests service inherits.
The litellm test is `importorskip`-guarded so a host run without the gateway
deps skips instead of erroring; the sync-authoring test is DB-free either way.
"""

import pytest

from polymerhus.app.llm import sync as S
from polymerhus.app.llm import sync_mapping as M
from tests.integration.test_llm_sync_key_rotation import RecordingGatewayAPI

CATALOG = {
    "providers": {
        "opencode-go": {
            "id": "opencode-go",
            "api": "https://opencode.ai/zen/go/v1",
            "models": {
                "deepseek-v4.1-flash": {
                    "id": "deepseek-v4.1-flash",
                    "limit": {"context": 1000000, "output": 384000},
                    # The models.dev record: ~6x above opencode-go's effective
                    # off-peak rate.
                    "cost": {"input": 0.15, "output": 0.6, "cache_read": 0.003},
                },
            },
        },
    },
}

PROVIDERS = {"opencode-go": "https://opencode.ai/zen/go/v1"}
SYNCED_AT = "2026-10-06T12:00:00+00:00"


def _run(recorder, catalog=CATALOG):
    return S.run_sync(
        fetch_catalog=lambda: catalog,
        fetch_provider_models=lambda provider, key: {"deepseek-v4.1-flash"},
        gateway=S.GatewayClient("http://127.0.0.1:4000", "sk-master",
                                client=recorder),
        providers=PROVIDERS,
        read_api_key=lambda provider: "oc_sk_key",
        synced_at=SYNCED_AT,
    )


def _registered_info(recorder):
    record = next(r for r in recorder.records.values()
                  if r["model_name"] == "opencode-go/deepseek-v4.1-flash")
    return record["model_info"]


def test_sync_registers_the_override_cost_in_model_info():
    recorder = RecordingGatewayAPI()
    assert _run(recorder) == S.SYNC_OK

    info = _registered_info(recorder)
    assert info["input_cost_per_token"] == 1.5e-07
    assert info["output_cost_per_token"] == 6.0e-07
    assert info["cache_read_input_token_cost"] == 3e-09
    assert info["cost_source"] == M.COST_SOURCE_OVERRIDE
    # The capability provenance stays models.dev-sourced (Rule 1).
    assert info["capability_source"] == \
        "models.dev/opencode-go/deepseek-v4.1-flash"

    # A no-change re-run is fully idle (the override is idempotent).
    writes = len(recorder.calls)
    assert _run(recorder) == S.SYNC_OK
    assert all(call[0] == "GET" for call in recorder.calls[writes:]), (
        "a converged override re-run must not write")


def test_sync_override_survives_a_missing_models_dev_record():
    # models.dev dropping the record degrades the model to the D9 unknown path;
    # the override is keyed by the registered name and MUST still apply, or the
    # budget guard silently fails OPEN for the eval's role model.
    recorder = RecordingGatewayAPI()
    empty = {"providers": {"opencode-go": {"id": "opencode-go", "models": {}}}}
    assert _run(recorder, catalog=empty) == S.SYNC_OK
    info = _registered_info(recorder)
    assert info["capability_staleness"] == "unknown"
    assert info["input_cost_per_token"] == 1.5e-07
    assert info["cost_source"] == M.COST_SOURCE_OVERRIDE


def test_litellm_cost_engine_prices_the_authored_model_info():
    """The budget guard's USD math is litellm's cost engine. The authored
    `model_info` must price at the provider's real rate (the models.dev Go
    record), and the cache-read key must be the one litellm reads."""
    litellm = pytest.importorskip("litellm")  # noqa: F841 - agent image only
    from litellm.cost_calculator import cost_per_token
    from litellm.litellm_core_utils.llm_cost_calc.utils import _get_token_base_cost
    from litellm.types.utils import Usage

    recorder = RecordingGatewayAPI()
    assert _run(recorder) == S.SYNC_OK
    info = _registered_info(recorder)

    # Public custom-pricing path: 1M input + 1M output at the authored rates.
    prompt_cost, completion_cost = cost_per_token(
        model="deepseek-v4.1-flash",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
        custom_cost_per_token={
            "input_cost_per_token": info["input_cost_per_token"],
            "output_cost_per_token": info["output_cost_per_token"],
            "cache_read_input_token_cost": info["cache_read_input_token_cost"],
        },
    )
    assert prompt_cost == pytest.approx(1_000_000 * 1.5e-07)
    assert completion_cost == pytest.approx(1_000_000 * 6.0e-07)

    # The deployment model_info path: litellm's base-cost function reads the
    # authored canonical keys directly (the proxy registers model_info into
    # litellm.model_cost, which this function then reads).
    (prompt_base, completion_base, _cache_creation,
     _cache_creation_1hr, cache_read) = _get_token_base_cost(
        model_info=dict(info),
        usage=Usage(prompt_tokens=1, completion_tokens=1))
    assert prompt_base == pytest.approx(1.5e-07)
    assert completion_base == pytest.approx(6.0e-07)
    assert cache_read == pytest.approx(3e-09)
