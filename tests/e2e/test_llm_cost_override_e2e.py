"""#330 iteration 2 END-TO-END: the deepseek cost override is factually active
through the live gateway.

This is the working proof the unit/integration tiers cannot give: a REAL
inference request traverses litellm and the budget guard's USD math consumes
the overridden cost.

Run from a side worktree (the e2e overlay is the side-worktree stack):

    # reuse the shared image (NO build): point the overlay's image tag at it
    docker tag polymerhus-agent:latest polymerhus-agent-e2e:latest
    POLYPHEMUS_MAIN_ENV=<main-checkout>/.env \
      docker compose -f docker-compose.e2e.yml up -d --no-build agent

`docker-compose.e2e.yml` gives the side worktree its own project
(`polymerhus-e2e`) on the SHARED network, bind-mounts THIS tree's `src`, and
loads the single main-worktree `.env` (provider keys, `LLM_GATEWAY_URL`) via
`POLYPHEMUS_MAIN_ENV`. The agent image is the shared `polymerhus-agent:latest`
(the deps layer, retagged as the overlay's image name so `--no-build` reuses
it); the source under test is the live mount, so no image rebuild is needed.

The gateway binds the agent's loopback (`127.0.0.1:4000`, ADR D1), so every
probe runs INSIDE the agent container via `docker compose exec`. The module
skips when the e2e agent is not up.

The three assertions:
  1. the registered `opencode-go/deepseek-v4.1-flash` `model_info` carries the
     override cost, NOT the models.dev record;
  2. a REAL chat request through litellm for that model succeeds;
  3. the app-minted virtual key's spend DELTA equals the override-priced cost
     of that request (~6x below the models.dev-priced cost) - i.e. the budget
     guard's USD math consumed the override.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ["docker", "compose", "-f", "docker-compose.e2e.yml"]
AGENT_SERVICE = "agent"

# The seeded override (per token) IS the models.dev opencode-go record - the
# provider's real rate, the ground truth the live record must carry (#330/EV-34).
OVERRIDE = {"input": 1.5e-07, "output": 6.0e-07, "cache_read": 3e-09}


def _run(cmd: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True,
                          timeout=timeout)


def _agent_is_up() -> bool:
    result = _run(COMPOSE + ["ps", "--format", "json", AGENT_SERVICE])
    if result.returncode != 0:
        return False
    for line in result.stdout.strip().splitlines():
        try:
            if json.loads(line).get("State") == "running":
                return True
        except json.JSONDecodeError:
            continue
    return False


skip = None if _agent_is_up() else (
    "the e2e side-worktree agent (docker-compose.e2e.yml, project "
    "polymerhus-e2e) is not up; bring it up from this worktree before running "
    "this tier")
pytestmark = pytest.mark.skipif(skip is not None, reason=skip or "")


def _agent_python(code: str, *, timeout: int = 600) -> subprocess.CompletedProcess:
    result = _run(COMPOSE + ["exec", "-T", AGENT_SERVICE, "python", "-c", code],
                  timeout=timeout)
    assert result.returncode == 0, (
        f"in-container probe failed:\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}")
    return result


def _run_sync_in_container() -> None:
    result = _run(COMPOSE + ["exec", "-T", AGENT_SERVICE,
                             "python", "-m", "polymerhus.app.llm.sync"],
                  timeout=600)
    assert result.returncode == 0, (
        f"sync failed (exit {result.returncode}):\n{result.stdout}\n{result.stderr}")


# --- 1. the registered model_info carries the override ----------------------

_MODEL_INFO_PROBE = r"""
import json, os, httpx
gw = "http://127.0.0.1:4000"
r = httpx.get(gw + "/model/info",
              headers={"Authorization": "Bearer " + os.environ["LITELLM_MASTER_KEY"]},
              timeout=20)
r.raise_for_status()
rec = next(e for e in r.json()["data"]
           if e.get("model_name") == "opencode-go/deepseek-v4.1-flash")
info = rec.get("model_info") or {}
print(json.dumps({
    "input_cost_per_token": info.get("input_cost_per_token"),
    "output_cost_per_token": info.get("output_cost_per_token"),
    "cache_read_input_token_cost": info.get("cache_read_input_token_cost"),
    "cost_source": info.get("cost_source"),
    "capability_source": info.get("capability_source"),
}))
"""


def test_e2e_registered_model_carries_the_override_cost():
    _run_sync_in_container()
    result = _agent_python(_MODEL_INFO_PROBE)
    info = json.loads(result.stdout.strip().splitlines()[-1])

    assert info["input_cost_per_token"] == pytest.approx(OVERRIDE["input"]), info
    assert info["output_cost_per_token"] == pytest.approx(OVERRIDE["output"]), info
    assert info["cache_read_input_token_cost"] == pytest.approx(OVERRIDE["cache_read"]), info
    assert info["cost_source"] == "provider-override"
    assert info["capability_source"] == \
        "models.dev/opencode-go/deepseek-v4.1-flash"


# --- 2+3. a real request through litellm, and the guard's spend delta -------

_REQUEST_AND_SPEND_PROBE = r"""
import json, os, time, httpx
from polymerhus.app.llm.providers import build_chat_model, gateway_virtual_key
from langchain_core.messages import HumanMessage

gw = "http://127.0.0.1:4000"
master = os.environ["LITELLM_MASTER_KEY"]
vkey = gateway_virtual_key("opencode-go", os.environ["API_KEY_OPENCODE_GO"])

def spend():
    r = httpx.get(gw + "/key/info", params={"key": vkey},
                  headers={"Authorization": "Bearer " + master}, timeout=20)
    r.raise_for_status()
    return float(r.json()["info"].get("spend") or 0.0)

before = spend()

# The app's own construction (gateway mode, D12 headers, app-minted virtual key).
model = build_chat_model("opencode-go", "deepseek-v4.1-flash")
resp = model.invoke([HumanMessage(content="Reply with exactly: OK")])
usage = getattr(resp, "usage_metadata", None) or {}
details = usage.get("input_token_details") or {}

# litellm records spend asynchronously; poll for the delta.
after = before
deadline = time.time() + 60
while time.time() < deadline:
    after = spend()
    if after > before:
        break
    time.sleep(2)

print(json.dumps({
    "content": str(getattr(resp, "content", resp))[:120],
    "input_tokens": usage.get("input_tokens", 0),
    "output_tokens": usage.get("output_tokens", 0),
    "cache_read_tokens": details.get("cache_read", 0),
    "spend_before": before,
    "spend_after": after,
    "spend_delta": after - before,
}))
"""


def test_e2e_real_request_through_gateway_and_guard_consumes_the_override():
    _run_sync_in_container()
    result = _agent_python(_REQUEST_AND_SPEND_PROBE, timeout=600)
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload["content"], f"the gateway returned no content: {payload}"

    inp = payload["input_tokens"]
    out = payload["output_tokens"]
    cache = payload["cache_read_tokens"]
    delta = payload["spend_delta"]
    assert delta > 0, f"the budget guard recorded no spend: {payload}"

    expected = (inp * OVERRIDE["input"]
                + out * OVERRIDE["output"]
                + cache * OVERRIDE["cache_read"])

    # The guard counted the provider's real rate (the Go record), so its spend
    # tracks the charge - the #330/EV-34 fix.
    assert delta == pytest.approx(expected, rel=0.05), (
        f"guard spend delta {delta!r} != provider-priced {expected!r}; "
        f"tokens={payload}")
