"""C14/E6: the crawl capability gate against the LIVE stack (#100, #108 T5).

`_refuse_crawl_without_tool_calling` (crawl_agentic.py) resolves the crawl
role's (provider, model) through the LIVE reader (LLM_GATEWAY_URL set) and
branches on `supports_tool_calling`:

- C14: the role `crawler` uses the configured model
  (`opencode-go:deepseek/deepseek-v4-flash`, tool_call True per the live
  catalog) -> the gate returns None (proceed). A reader that degrades to an
  all-None profile (D5 Rule 1 unknown) -> `supports_tool_calling` None is
  treated as false (spec §5) -> the gate refuses with the `<provider>:<model>`
  refusal string, never crashing.
- E6: the full live path - gate -> reader -> /model/info -> branch - returns
  None for the capable model and is deterministic across calls (the reader's
  process-lifetime hold).
"""

import json

import pytest

from tests.e2e import gateway_stack as gs

pytestmark = pytest.mark.live_neo4j
skip = gs.skip_reason()
pytestmark = pytest.mark.skipif(skip is not None, reason=skip or "agent stack not up for the gateway live tier")

GATEWAY_ENV = {"LLM_GATEWAY_URL": gs.GATEWAY_URL}

# The configured crawler model, verbatim from .env (LLM_MODEL_CRAWLER).
CRAWLER_IDENTITY = "opencode-go:deepseek/deepseek-v4-flash"

PROBE = """
import json
from polymerhus.recon.crawl.crawl_agentic import (
    AgenticCrawlRequest, _refuse_crawl_without_tool_calling,
)

body = AgenticCrawlRequest(target="example.com", scope=["example.com"],
                           model="crawler")
try:
    refusal = _refuse_crawl_without_tool_calling(body)
except Exception as exc:
    refusal = f"RAISED: {type(exc).__name__}: {exc}"
print(json.dumps({"refusal": refusal}))
"""

# The refusal branch, driven in-process: the REAL role identity + REAL env,
# with the reader's live resolution replaced by an all-None profile (D5 Rule 1
# unknown) so the gate's `false == refuse` branch is exercised against the
# same registered-lookup-key format the production warn log carries.
# NOTE: crawl_agentic binds `resolve_capability` at import, so the patch must
# land in ITS namespace (`polymerhus.recon.crawl.crawl_agentic`), not the
# capability module's.
REFUSAL_PROBE = """
import json
from polymerhus.recon.crawl.crawl_agentic import (
    AgenticCrawlRequest, _refuse_crawl_without_tool_calling,
)
from polymerhus.app.llm.capability import CapabilityProfile
import polymerhus.recon.crawl.crawl_agentic as gate

body = AgenticCrawlRequest(target="example.com", scope=["example.com"],
                           model="crawler")
original = gate.resolve_capability
gate.resolve_capability = lambda p, m, **kw: CapabilityProfile()
try:
    refusal = _refuse_crawl_without_tool_calling(body)
finally:
    gate.resolve_capability = original
print(json.dumps({"refusal": refusal}))
"""


def _run(probe: str) -> dict:
    result = gs.agent_python(probe, env=GATEWAY_ENV, timeout=120)
    assert result.returncode == 0, f"crawl gate probe failed:\n{result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------------------
# C14 - the gate's branch vs the live reader (D4 item 4, D5 Rule 1) ---------
# ---------------------------------------------------------------------------

def test_c14_gate_passes_for_the_capable_role_model():
    """The crawler role's model supports tool calling per the live oracle
    (tool_call True) -> the gate returns None (proceed) and never raises."""
    report = _run(PROBE)
    assert report["refusal"] is None, (
        "the gate must pass the crawler's capable model; got %r"
        % report["refusal"])


def test_c14_unknown_profile_refuses_with_the_lookup_key():
    """An all-None profile (Rule 1 unknown, treated as false per spec §5)
    must refuse with the `<provider>:<model>` string - the same identity the
    production warn log names - never a crash."""
    report = _run(REFUSAL_PROBE)
    assert report["refusal"] == CRAWLER_IDENTITY, (
        "the refusal string must be the role's provider:model identity; got %r"
        % report["refusal"])


# ---------------------------------------------------------------------------
# E6 - the live crawl-gate walkthrough ---------------------------------------
# ---------------------------------------------------------------------------

def test_e6_crawl_gate_live_pass_is_deterministic():
    """The full path through the live stack: gate -> reader -> /model/info ->
    branch. The capable model passes (None), and the decision is deterministic
    across calls (the reader's resolve-and-hold)."""
    first = _run(PROBE)
    second = _run(PROBE)
    assert first["refusal"] is None
    assert second["refusal"] is None, (
        "the gate's decision must be deterministic (resolve-and-hold)")
