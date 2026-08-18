"""C13/E4: the client's gateway-mode seam against the LIVE gateway (#100, #107 T4).

C13 pins the `build_chat_model` mode selection (D4 item 1): `LLM_GATEWAY_URL`
unset -> direct per-provider mode (base_url = `PROVIDERS[provider]`, zen id
strip runs client-side); set -> gateway mode (base_url = the gateway verbatim,
`provider:model` string sent verbatim, no client-side strip); `max_retries=0`
holds in both modes.

E4 is the integration truth of the whole T4 chain: ONE live completion through
`build_chat_model` with `LLM_GATEWAY_URL=http://127.0.0.1:4000` - the client
hits the co-located litellm proxy, the proxy resolves the registered name and
routes to the opencode zen upstream, and a response returns. This is the first
live round-trip of the D5 registered-name convention: the client sends the
CANONICAL REGISTERED name (`opencode-go/deepseek-v4-flash`,
`sync_mapping.registered_model_name` - the name the sync pushed and the
reader/keys resolve); the gateway resolves it to the zen/go upstream. The
old verbatim-contract framing (client sends the operator string `deepseek/...`
unstripped) was the root cause of the 400/403 routing failures fixed in this
ticket: the client now sends the registered name, never a raw id.
"""

import json

import pytest

from tests.e2e import gateway_stack as gs

pytestmark = pytest.mark.live_neo4j
skip = gs.skip_reason()
pytestmark = pytest.mark.skipif(skip is not None, reason=skip or "agent stack not up for the gateway live tier")

PROVIDER = "opencode-go"
MODEL = "deepseek/deepseek-v4-flash"
GATEWAY_ENV = {"LLM_GATEWAY_URL": gs.GATEWAY_URL}


# ---------------------------------------------------------------------------
# C13 - build_chat_model env selection (D4 item 1) ---------------------------
# ---------------------------------------------------------------------------

def _mode_report(env: dict) -> dict:
    code = (
        "import json\n"
        "from polymerhus.app.llm.providers import build_chat_model, PROVIDERS\n"
        f"m = build_chat_model({PROVIDER!r}, {MODEL!r}, max_retries=0)\n"
        "print(json.dumps({\n"
        "    'base_url': m.openai_api_base,\n"
        "    'model': m.model_name,\n"
        "    'max_retries': m.max_retries,\n"
        "    'direct_expected': PROVIDERS[%r],\n"
        "}))\n" % PROVIDER)
    result = gs.agent_python(code, env=env, timeout=60)
    assert result.returncode == 0, f"build_chat_model probe failed:\n{result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_c13_direct_mode_when_url_unset():
    """UNSET -> direct mode: base_url is the provider's own endpoint and the
    zen-family id strip runs client-side (`deepseek/deepseek-v4-flash`
    -> `deepseek-v4-flash`, the bare zen/go catalog id)."""
    report = _mode_report({})
    assert report["base_url"] == report["direct_expected"] == (
        "https://opencode.ai/zen/go/v1")
    assert report["model"] == "deepseek-v4-flash", (
        "direct mode must strip the provider prefix client-side (the zen "
        "gateway validates bare ids); got %r" % report["model"])
    assert report["max_retries"] == 0


def test_c13_gateway_mode_when_url_set():
    """SET -> gateway mode: base_url is the gateway verbatim (no trailing-slash
    normalisation) and the model string is the CANONICAL REGISTERED name
    (`registered_model_name`, the D5 convention: `<provider>/<native-id>`) -
    not the operator string verbatim. The mapping layer is the sole id
    translator (D5), so a bare-catalog aggregator's id is stripped there while
    a verbatim aggregator's (openrouter) passes through; the client never does
    the translation itself."""
    report = _mode_report(GATEWAY_ENV)
    assert report["base_url"] == gs.GATEWAY_URL, (
        "gateway mode must point the client at the gateway verbatim")
    assert report["model"] == "opencode-go/deepseek-v4-flash", (
        "gateway mode must send the canonical registered name; got %r"
        % report["model"])
    assert report["max_retries"] == 0


# ---------------------------------------------------------------------------
# E4 - one live completion through the gateway (the routing truth) -----------
# ---------------------------------------------------------------------------

def test_e4_live_completion_routes_through_gateway():
    """The full T4 chain with real traffic: client (base_url = the gateway,
    model verbatim) -> litellm registered-name resolution -> opencode zen
    upstream -> response. HTTP 200, non-empty content, and the gateway's log
    records the routed model."""
    code = (
        "import json\n"
        "from polymerhus.app.llm.providers import build_chat_model\n"
        f"m = build_chat_model({PROVIDER!r}, {MODEL!r}, max_retries=0)\n"
        "r = m.invoke('Reply with exactly: ROUTE-OK')\n"
        "print(json.dumps({'content': r.content, 'base_url': m.openai_api_base,\n"
        "                  'model': m.model_name}))\n")
    result = gs.agent_python(code, env=GATEWAY_ENV, timeout=180)
    assert result.returncode == 0, (
        f"the live completion through the gateway FAILED:\n{result.stderr}\n"
        "the D5 registered-name convention is the suspect: the client sends "
        "'opencode-go/deepseek-v4-flash'; the gateway must resolve that "
        "registered name to the synced record and route to the zen/go upstream")
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["base_url"] == gs.GATEWAY_URL
    assert report["model"] == "opencode-go/deepseek-v4-flash"
    assert report["content"], "the routed completion returned empty content"
    logs = gs.gateway_logs()
    assert "deepseek" in logs.lower(), (
        "the gateway log must record the routed model_name")
