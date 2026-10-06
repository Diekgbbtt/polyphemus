"""F3 (#330): the gateway cost guard trips a budget before the provider.

The litellm proxy lives INSIDE the agent container on 127.0.0.1:4000 (ADR D1),
so - exactly like the rest of the gateway live tier - this probe runs inside
the agent container via `docker compose exec` (see `tests/e2e/gateway_stack`).

It exercises the REAL sync seam (`GatewayClient.ensure_virtual_key`) against
the REAL litellm 1.96.0 management API, end to end:

1. provision a throwaway virtual key with a zero-USD 5h budget window;
2. `/key/info` round-trips the window (the server-set `reset_at` included);
3. a re-run with the SAME plan issues no write - idempotent (C9);
4. a chat request bearing that key is rejected 429 at auth, BEFORE the
   provider is called (a `budget_exceeded`, not a provider error);
5. the key is deleted.

Run (stack up, from the repo root):

    .venv/bin/python -m pytest tests/e2e/test_gateway_budget_guard.py -q
"""

import json

import pytest

from tests.e2e import gateway_stack as gs

pytestmark = pytest.mark.live_neo4j
skip = gs.skip_reason()
pytestmark = pytest.mark.skipif(
    skip is not None,
    reason=skip or "agent stack not up for the gateway live tier")


_PROBE = r'''
import json
from polymerhus.app.llm import sync as S

KEY = "sk-ph-budget-e2e-probe"
out = {"created": False, "roundtrip": None, "second_writes": None,
       "status": None, "body": None, "error": None}
gw = None
try:
    import os
    gw = S.GatewayClient("http://127.0.0.1:4000",
                         os.environ["LITELLM_MASTER_KEY"])
    models = [m["model_name"] for m in gw.list_models()
              if m.get("model_name") and m["model_name"] != S.SNAPSHOT_MODEL_NAME]
    if not models:
        raise RuntimeError("no registered model to scope the probe key to")
    plan = ({"budget_duration": "5h", "max_budget": 0.0},)

    gw.ensure_virtual_key(KEY, models[:1], budget_limits=list(plan), rpm_limit=None)
    info = gw.key_info(KEY) or {}
    out["created"] = True
    out["roundtrip"] = S._canonical_budget_limits(info.get("budget_limits"))

    # A re-run with the SAME plan must write nothing (only the info GET).
    writes = {"n": 0}
    original = gw._request
    def counting(method, path, *, json=None):
        writes["n"] += 1
        return original(method, path, json=json)
    gw._request = counting
    gw.ensure_virtual_key(KEY, models[:1], budget_limits=list(plan), rpm_limit=None)
    gw._request = original
    out["second_writes"] = writes["n"]

    import httpx
    r = httpx.post("http://127.0.0.1:4000/chat/completions",
                   headers={"Authorization": "Bearer " + KEY},
                   json={"model": models[0],
                         "messages": [{"role": "user", "content": "hi"}],
                         "max_tokens": 1}, timeout=30)
    out["status"] = r.status_code
    out["body"] = r.text[:400]
except Exception as exc:  # noqa: BLE001 - surface the failure to the test
    out["error"] = f"{type(exc).__name__}: {exc}"
finally:
    if gw is not None and out.get("created"):
        try:
            gw._request("POST", "/key/delete", json={"keys": [KEY]})
        except Exception:
            pass
print("BUDGET_GUARD_RESULT " + json.dumps(out))
'''


def _probe() -> dict:
    result = gs.agent_python(_PROBE)
    assert result.returncode == 0, (
        "in-container budget-guard probe failed:\n"
        f"stdout={result.stdout}\nstderr={result.stderr}")
    for line in result.stdout.splitlines():
        if line.startswith("BUDGET_GUARD_RESULT "):
            return json.loads(line[len("BUDGET_GUARD_RESULT "):])
    raise AssertionError(f"probe printed no result line:\n{result.stdout}")


def test_budget_guard_provisions_and_trips_before_the_provider():
    out = _probe()
    assert out.get("error") is None, f"probe raised: {out.get('error')}"

    # The sync seam provisioned the key AND litellm persisted the window.
    assert out["created"] is True
    assert out["roundtrip"] == [["5h", 0.0]], (
        "the provisioned 5h window must round-trip through /key/info "
        f"(got {out['roundtrip']!r})")

    # A no-change re-run is a no-op: no management write fires (C9).
    assert out["second_writes"] == 0, (
        "a converged re-run must issue no write, got "
        f"{out['second_writes']} request(s)")

    # The budget trips at auth, BEFORE the provider: a 429 budget_exceeded,
    # not a provider error and not a routed call.
    assert out["status"] == 429, (
        f"a budget-exceeded request must be 429, got {out['status']}: "
        f"{out['body']}")
    assert "budget" in (out["body"] or "").lower(), (
        f"the 429 must name the budget guard, got {out['body']}")
