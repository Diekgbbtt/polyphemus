"""T5 (#108) unit tier: the crawl capability gate at the crawl seam.

Covers the ticket's warn-refuse-degrade contract at
`crawl_agentic._run_agentic_crawl`, BEFORE `llm.bind_tools(tools)`:

  * `supports_tool_calling = true`  -> the tool-loop runs EXACTLY as today
    (regression pin: same scripted tool flow, same manifest, `bind_tools`
    called once);
  * `supports_tool_calling = false` or `unknown` (None, the provenance-
    gated absence per ADR D5 Rule 1) -> the seam warns the operator (the
    log carries the model, the capability state, and the gap), REFUSES the
    tool-loop (`bind_tools` never called, the LLM never invoked - no silent
    emulation, no silent retry) and degrades fail-open to the empty
    manifest without crashing the caller;
  * the T3 reader is a MOCKED collaborator here - no live gateway, no live
    model, no live crawl (ticket AC). The fake LLM/tools mirror
    `test_crawl_agent.py`'s fixtures exactly.

Model identity at the seam is role-based: the adapter passes `body.model`
= the role id ("crawler") and resolves the client from the role; the gate
derives the (provider, model) pair via `resolve_role(body.model)` (the
registered-name + zen-strip lookup convention lives INSIDE the reader,
`capability.py:_registered_name`). When the role has no bound model
(`LLM_MODEL_CRAWLER` absent - the injected pre-built-client seam), the
identity is unresolvable and the gate warns and proceeds as today (reachable
only when `build_llm_fn` is injected - the env-less identity would have
crashed the production `chat_model_for` builder before the gate).
"""
import asyncio
import logging

import pytest

from polymerhus.app.llm import CapabilityProfile
from polymerhus.app.llm.providers import LLMConfigError
from polymerhus.recon.crawl import crawl_agentic

EMPTY_MANIFEST = {"endpoints": [], "js_urls": []}

CANNED_MANIFEST = {
    "endpoints": [
        {"method": "GET", "url": "https://x.com/api/v1/items", "query": ["id"], "body": [], "status": 200},
    ],
    "js_urls": ["https://x.com/static/app.js"],
}

CRAWLER_ENV = "openrouter:openai/gpt-4o-mini"


class _AIMessage:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls
        self.content = ""


class _RecordingLLM:
    """Fake chat model recording every `bind_tools` / `ainvoke` entry, so the
    refusal path can prove bind_tools was never attempted and the loop never
    ran (no silent emulation, no silent retry)."""

    def __init__(self, script):
        self.script = list(script)
        self.bind_calls = 0
        self.invoke_calls = 0

    def bind_tools(self, tools):
        self.bind_calls += 1
        return self

    async def ainvoke(self, messages):
        self.invoke_calls += 1
        return _AIMessage(self.script.pop(0) if self.script else [])


class _FakeTool:
    def __init__(self, name, result=None, record=None):
        self.name = name
        self._result = result if result is not None else {}
        self._record = record

    async def ainvoke(self, args):
        if self._record is not None:
            self._record.append(self.name)
        return self._result


class _Mgr:
    def __init__(self, tools):
        self._tools = tools

    async def get_tools(self):
        return self._tools


def _body(**overrides):
    kwargs = dict(target="https://x.com", scope=["x.com"], model="crawler", max_iterations=10)
    kwargs.update(overrides)
    return crawl_agentic.AgenticCrawlRequest(**kwargs)


def _fake_tools(record=None):
    return [
        _FakeTool("steel_crawl_start", {"crawl_id": "c1"}, record=record),
        _FakeTool("steel_crawl_finish", CANNED_MANIFEST, record=record),
    ]


def _run(body, llm, tools, **kwargs):
    return asyncio.run(
        crawl_agentic._run_agentic_crawl(
            body, _Mgr(tools), build_llm_fn=lambda m, u: llm, **kwargs
        )
    )


# ---------------------------------------------------------------------------
# true -> proceed exactly as today (regression pin) ---------------------------
# ---------------------------------------------------------------------------

def test_true_capability_runs_the_tool_loop_exactly_as_today(monkeypatch, caplog):
    """`supports_tool_calling = true`: the loop behaves identically to the
    pre-gate crawl - bind_tools once, the scripted steel flow drives the
    tools, and the finish manifest is returned. No refusal warning."""
    monkeypatch.setenv("LLM_MODEL_CRAWLER", CRAWLER_ENV)
    monkeypatch.setattr(
        crawl_agentic, "resolve_capability",
        lambda provider, model: CapabilityProfile(supports_tool_calling=True),
    )
    calls_log: list[str] = []
    llm = _RecordingLLM([
        [{"name": "steel_crawl_start", "args": {}, "id": "1"}],
        [{"name": "steel_crawl_finish", "args": {}, "id": "2"}],
    ])
    result = _run(_body(), llm, _fake_tools(record=calls_log))
    assert result == CANNED_MANIFEST
    assert calls_log == ["steel_crawl_start", "steel_crawl_finish"]
    assert llm.bind_calls == 1
    assert llm.invoke_calls == 2
    assert "REFUSED" not in caplog.text
    assert "cannot identify" not in caplog.text


# ---------------------------------------------------------------------------
# false / unknown -> warn + refuse + degrade (never crash) -------------------
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("state,expected", [
    (False, "supports_tool_calling=false"),
    (None, "supports_tool_calling=unknown"),
], ids=["false", "unknown"])
def test_non_tool_callable_capability_refuses_and_degrades(monkeypatch, caplog, state, expected):
    """false / unknown both trip the warn-refuse-degrade: the empty manifest
    is returned, `bind_tools` is never attempted, the LLM is never invoked
    (no silent emulation, no silent retry of the loop)."""
    monkeypatch.setenv("LLM_MODEL_CRAWLER", CRAWLER_ENV)
    monkeypatch.setattr(
        crawl_agentic, "resolve_capability",
        lambda provider, model: CapabilityProfile(supports_tool_calling=state),
    )
    llm = _RecordingLLM([])
    with caplog.at_level(logging.WARNING, logger="crawl_agentic"):
        result = _run(_body(), llm, _fake_tools())
    assert result == EMPTY_MANIFEST
    assert llm.bind_calls == 0
    assert llm.invoke_calls == 0
    text = caplog.text
    assert "REFUSED" in text
    assert "openrouter:openai/gpt-4o-mini" in text  # the model
    assert expected in text  # the capability state
    assert "registry" in text  # the gap (how to close it, spec §5)


def test_refusal_gap_names_the_registry_and_manual_override(monkeypatch, caplog):
    """The gap must be actionable: the operator can close it by adding the
    model to the gateway registry or setting a manual override (spec §5)."""
    monkeypatch.setenv("LLM_MODEL_CRAWLER", CRAWLER_ENV)
    monkeypatch.setattr(
        crawl_agentic, "resolve_capability",
        lambda provider, model: CapabilityProfile(supports_tool_calling=None,
                                                  source=None, synced_at=None),
    )
    with caplog.at_level(logging.WARNING, logger="crawl_agentic"):
        _run(_body(), _RecordingLLM([]), _fake_tools())
    text = caplog.text
    assert "manual override" in text
    assert "registry" in text
    assert "bind_tools not attempted" in text


def test_refusal_never_crashes_the_caller_when_reader_raises(monkeypatch, caplog):
    """Fail-open invariant: even if the T3 reader raises (a config-lie
    context env), the seam treats it as unknown, warns, refuses, and returns
    the empty manifest - it never propagates an exception."""
    monkeypatch.setenv("LLM_MODEL_CRAWLER", CRAWLER_ENV)

    def boom(provider, model):
        raise LLMConfigError("LLM_ROLE_MODEL_CONTEXT_LIMIT must be a positive integer")

    monkeypatch.setattr(crawl_agentic, "resolve_capability", boom)
    llm = _RecordingLLM([])
    with caplog.at_level(logging.WARNING, logger="crawl_agentic"):
        result = _run(_body(), llm, _fake_tools())
    assert result == EMPTY_MANIFEST
    assert llm.bind_calls == 0
    assert llm.invoke_calls == 0
    text = caplog.text
    # The raise is treated as unknown (conservative) and the loop is refused -
    # the caller is never crashed and the restriction is never silent.
    assert "reader raised" in text
    assert "unknown" in text
    assert "refusing the tool-loop" in text


def test_refusal_goes_through_the_adapter_as_best_effort(monkeypatch, caplog):
    """The adapter contract on top of the seam: a refused crawl surfaces as
    the empty manifest (degrade), never as an exception, so the crawl pod
    marks the job degraded instead of crashing the pipeline."""
    from polymerhus.recon.crawl import crawl_agent

    monkeypatch.setenv("LLM_MODEL_CRAWLER", CRAWLER_ENV)
    monkeypatch.setattr(
        crawl_agentic, "resolve_capability",
        lambda provider, model: CapabilityProfile(supports_tool_calling=False),
    )
    llm = _RecordingLLM([])
    manifest = asyncio.run(crawl_agent.run_crawl(
        "https://x.com", scope=["x.com"], tools=_fake_tools(), llm=llm, max_iters=10
    ))
    assert manifest == EMPTY_MANIFEST
    assert llm.bind_calls == 0
    assert llm.invoke_calls == 0


# ---------------------------------------------------------------------------
# the "subscription is optional" case: unresolvable model identity -----------
# ---------------------------------------------------------------------------

def test_unresolvable_role_identity_proceeds_as_today_with_warning(monkeypatch, caplog):
    """When the role has NO bound model (no LLM_MODEL_CRAWLER - the injected
    pre-built-client seam, where the caller already vetted the client), the
    gate cannot classify and the seam warns and proceeds EXACTLY as today.
    This branch is reachable only on the injected seam: on the production
    path (`chat_model_for`), the env-less identity would have crashed
    `build_llm_fn` before the gate ever ran."""
    monkeypatch.delenv("LLM_MODEL_CRAWLER", raising=False)
    calls_log: list[str] = []
    llm = _RecordingLLM([
        [{"name": "steel_crawl_start", "args": {}, "id": "1"}],
        [{"name": "steel_crawl_finish", "args": {}, "id": "2"}],
    ])
    with caplog.at_level(logging.WARNING, logger="crawl_agentic"):
        result = _run(_body(), llm, _fake_tools(record=calls_log))
    assert result == CANNED_MANIFEST
    assert calls_log == ["steel_crawl_start", "steel_crawl_finish"]
    assert llm.bind_calls == 1
    assert "cannot identify the model" in caplog.text
    assert "crawler" in caplog.text  # the role id is named