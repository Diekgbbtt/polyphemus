"""Unit tier: no test may leak the OPERATOR'S LOCAL LLM CONFIG into another test.

Importing `litellm` calls `load_dotenv()`, which loads the checkout's `.env` into
the process environment - so a single litellm-importing module sets the whole dev
configuration (`LLM_CRAWLER`, `LLM_GATEWAY_URL`, ...) for every later test in the
same process. `tests/recon/crawl/test_crawl_agent.py` is the observed victim: it
passed alone and failed after a litellm-importing module ran, because the leak
configured the `crawler` role, the capability reader then hit the unreachable
gateway and cached the DEGRADED (resolve-and-hold) profile, and the crawl refused
its tool loop and returned the empty manifest.

The key set is derived from the role registry, so these tests name roles rather
than hardcoding env var strings.
"""
from __future__ import annotations

import os

import pytest

from polymerhus.app.llm.providers import ROLES


def test_a_set_the_ambient_config_runs_first():
    """This file runs FIRST (named to sort first): it sets the ambient
    configuration exactly as the `.env` load does, so a later test can prove the
    isolation clears it."""
    os.environ["LLM_GATEWAY_URL"] = "http://localhost:4000"
    os.environ["LLM_CRAWLER"] = "opencode:step-5-preview-free"
    assert os.environ["LLM_GATEWAY_URL"] == "http://localhost:4000"


def test_b_a_later_unit_test_carries_no_ambient_llm_config():
    """The autouse unit-tier fixture clears the leaked configuration, so a role
    does not silently resolve to the dev stack's model inside a unit test."""
    from polymerhus.app.llm.capability import _gateway_url

    leaked = {r.model_key for r in ROLES
              if os.environ.get(r.model_key)} | {
        "LLM_GATEWAY_URL", "LLM_CAPABILITY_OVERRIDES",
    } & set(os.environ)
    assert not leaked, f"the unit tier must not carry the ambient LLM config: {leaked}"
    assert _gateway_url() is None


def test_c_a_leaked_crawler_role_no_longer_refuses_the_tool_loop():
    """The regression this guard exists for: with the leak isolated, the crawl
    capability gate cannot identify a model, so it proceeds fail-open instead of
    refusing the tool loop on an unreachable gateway's degraded profile."""
    from polymerhus.app.llm.providers import resolve_role
    from polymerhus.recon.crawl.crawl_agentic import _refuse_crawl_without_tool_calling

    with pytest.raises(Exception):  # noqa: B017 - the identity failure IS the point
        resolve_role("crawler")
    assert _refuse_crawl_without_tool_calling(type("B", (), {"model": "crawler"})()) is None
